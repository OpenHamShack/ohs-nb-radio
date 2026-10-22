"""The Qt window against a real Radio on the simulator (null audio, faster
than real time), on Qt's offscreen platform. These drive the window the way
an operator would - mouse clicks, the PTT button, the mode grid - and check
what the engine was told, never what the source says."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - the engine's tests still run without PyQt6
    HAVE_QT = False

from helpers import make_radio, sim_seconds


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class WindowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.errors = []
        self._hook = sys.excepthook
        # PyQt aborts the process on an exception escaping a slot unless a hook
        # is set; collect them instead and fail the test that caused them.
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))
        self.wins = []

    def tearDown(self):
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            msg = "".join("".join(traceback.format_exception(*e)) for e in self.errors)
            self.fail("exceptions in Qt slots:\n" + msg)

    def window(self, licence=True, device=None, **over):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp, audio_source=lambda n: __import__("numpy").full(n, 0.2, "float32"),
                           device=device, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = licence
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def run_for(self, radio, sim_s=0.0, until=None, timeout=30.0):
        start = sim_seconds(radio)
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until is not None and until():
                return True
            if until is None and sim_seconds(radio) - start >= sim_s:
                return True
        return False


class Window(WindowCase):
    def test_builds_and_drains_feeds(self):
        win, bridge, radio = self.window()
        self.assertTrue(self.run_for(radio, 3.0))
        self.assertTrue(radio.state()["running"])
        self.assertGreater(win.wide.wf.rows_total, 10)       # wide lines reached the waterfall
        self.assertGreater(win.zoom.wf.rows_total, 10)
        self.assertIsNotNone(win.wide.avg)
        for f in bridge.feeds.values():
            self.assertLess(len(f), 64)                      # the pump keeps up

    def test_a_stalled_window_catches_up_with_a_change_its_state_feed_dropped(self):
        # The GUI thread stalls (nothing drains the feeds) while the engine
        # goes on publishing; the one change made at the start of the stall
        # falls off the front of the full state feed and is never published
        # again. Once the thread is back the window must still know it.
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.5)
        feed = bridge.feeds["state"]
        self.app.processEvents()
        before = feed.dropped
        radio.set(vfo=10_489_612_300.0)
        t0 = time.monotonic()
        while feed.dropped - before < 3 and time.monotonic() - t0 < 60:
            time.sleep(0.05)                                 # the stall: no event loop
        self.assertGreaterEqual(feed.dropped - before, 3, "the engine never filled the state feed")
        self.assertNotEqual(bridge.st["vfo"], 10_489_612_300.0)
        heard = []
        bridge.changed.connect(lambda ch: heard.append(ch.get("vfo")))
        self.run_for(radio, until=lambda: bridge.st["vfo"] == 10_489_612_300.0, timeout=2)
        self.assertEqual(bridge.st["vfo"], 10_489_612_300.0)
        self.assertIn(10_489_612_300.0, heard)              # and the widgets were told

    def test_pixel_frequency_round_trip(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 0.5)
        for scope in (win.wide, win.zoom):
            fm = scope.fmap
            for f in (fm.lo + 1234.5, (fm.lo + fm.hi) / 2, fm.hi - 10.0):
                self.assertAlmostEqual(fm.f(fm.x(f)), f, places=3)
            for x in (0.0, 17.25, scope.width() - 1.0):
                self.assertAlmostEqual(fm.x(fm.f(x)), x, places=6)

    def test_click_on_panadapter_tunes(self):
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.5)
        sc = win.wide
        target = 10_489_712_340.0
        x = int(round(sc.fmap.x(target)))
        y = int(sc.r_spec.center().y())
        clicked = sc.fmap.f(x)
        QTest.mouseClick(sc, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
        self.run_for(radio, until=lambda: radio.state()["vfo"] != 10_489_700_000.0, timeout=5)
        self.assertEqual(radio.state()["vfo"], round(clicked / 100) * 100)    # USB: the click is the carrier
        # CW: the clicked signal is put at the pitch.
        bridge.set(mode="cw")
        self.run_for(radio, 0.2)
        x = int(round(sc.fmap.x(10_489_520_700.0)))
        clicked = sc.fmap.f(x)
        QTest.mouseClick(sc, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
        self.run_for(radio, 0.2)
        self.assertEqual(radio.state()["vfo"], round((clicked - radio.state()["cwPitch"]) / 10) * 10)

    def test_mode_switch_updates_panel(self):
        from ohscore.ui.panels.ft8 import Ft8Panel
        from ohscore.ui.panels.text import TextPanel
        from ohscore.ui.panels.voice import VoicePanel
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.3)
        self.assertIsInstance(win.panel, VoicePanel)
        cell = win.modegrid.cells["ft8"]
        QTest.mouseClick(cell, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        self.assertEqual(radio.state()["mode"], "ft8")
        self.assertIsInstance(win.panel, Ft8Panel)
        self.assertIs(win.panel_stack.currentWidget(), win.panel)
        # The panel says which decoder its lines come from (ohsdigi, or jt9).
        from ohscore.modes import ft8
        if ft8.CAN_DECODE:
            self.run_for(radio, until=lambda: win.panel.decoder_label.text(), timeout=5)
            self.assertEqual(win.panel.decoder_label.text(), f"decoder: {radio.state()['ft8DecoderInUse']}")
            self.assertIn(radio.state()["ft8DecoderInUse"], ("ohsdigi", "jt9"))
        bridge.set(mode="cw")
        self.run_for(radio, until=lambda: isinstance(win.panel, TextPanel), timeout=5)
        self.assertTrue(win.panel.cw)
        bridge.set(mode="psk31")
        self.run_for(radio, until=lambda: isinstance(win.panel, TextPanel) and not win.panel.cw, timeout=5)
        self.assertFalse(win.panel.cw)

    def test_function_keys_send_the_macros_they_are_labelled_with(self):
        from ohscore.ui.panels.text import TextPanel
        win, bridge, radio = self.window(mode="cw", vfo=10_489_520_000.0, callsign="GM4BRI")
        self.run_for(radio, until=lambda: isinstance(win.panel, TextPanel), timeout=5)
        panel = win.panel
        win.activateWindow()
        panel.entry.edit.setFocus()          # typing in the transmit line: F-keys still work
        self.app.processEvents()
        QTest.keyClick(panel.entry.edit, Qt.Key.Key_F3)
        self.assertIn("TU 73 DE GM4BRI SK", panel.txq.pending)
        panel.txq.clear()
        QTest.keyClick(panel.entry.edit, Qt.Key.Key_F8)   # past the last macro: nothing
        self.assertEqual(panel.txq.pending, "")
        win.show_view("log")                 # the buttons are out of sight: no transmitting blind
        self.app.processEvents()
        QTest.keyClick(win, Qt.Key.Key_F1)
        self.assertEqual(panel.txq.pending, "")

    def test_settings_help_shows_angle_bracketed_examples_as_written(self):
        # "ip:<address>" was taken for markup and shown as "ip:", losing
        # the very examples the sentence exists to give.
        from PyQt6.QtWidgets import QLabel
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window()
        d = SettingsDialog(bridge, win.prefs, win, page=1)
        try:
            helps = [w for w in d.fields["plutoUri"].findChildren(QLabel) if w.objectName() == "Faint"]
            self.assertEqual(len(helps), 1)
            self.assertIn("ip:<address>", helps[0].text())
            self.assertIn("usb:<bus>.<dev>.<n>", helps[0].text())
            self.assertEqual(helps[0].textFormat(), Qt.TextFormat.PlainText)
        finally:
            d.close()

    def test_noise_reduction_from_the_card_the_key_and_settings(self):
        from PyQt6.QtCore import QPointF
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.3)
        card = win.rxcard
        self.assertFalse(radio.state()["nr"])                        # off by default
        self.assertFalse(card.nrs.isEnabled())
        QTest.mouseClick(card.nr, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: radio.state()["nr"], timeout=5)
        self.assertTrue(card.nrs.isEnabled())
        # Shift+N toggles it (N alone stays the noise blanker), and the
        # "?" list says so.
        QTest.keyClick(win, "N", Qt.KeyboardModifier.ShiftModifier)   # text "N", as a keyboard sends it
        self.run_for(radio, until=lambda: not radio.state()["nr"], timeout=5)
        self.assertFalse(radio.state()["nb"])
        listed = {k for _t, rows in win.overlay.sections for k, _w in rows}
        self.assertIn("Shift + N", listed)
        # The strength slider: its far right end is 100 %.
        tr = card.nrs._track()
        QTest.mouseClick(card.nrs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPointF(tr.right(), tr.center().y()).toPoint())
        self.run_for(radio, until=lambda: radio.state()["nrStrength"] == 100.0, timeout=5)
        # Settings › Audio carries both, and saving them reaches the engine.
        d = SettingsDialog(bridge, win.prefs, win)
        try:
            d.fields["nr"].w.set_on(True, emit=True)
            d.fields["nrStrength"].w.set_value(30.0, emit=True)
            d.save()
        finally:
            d.close()
        self.assertTrue(radio.state()["nr"])
        self.assertEqual(radio.state()["nrStrength"], 30.0)
        self.assertEqual(radio.cfg["nrStrength"], 30.0)              # persisted with the controls

    def test_every_menu_shortcut_is_in_the_shortcuts_overlay(self):
        # Ctrl+J and Ctrl+Q worked but the "?" list left them out.
        from PyQt6.QtGui import QAction
        win, bridge, radio = self.window()
        listed = {k.replace(" ", "") for _title, rows in win.overlay.sections for k, _what in rows}
        bound = {a.shortcut().toString() for a in win.findChildren(QAction) if not a.shortcut().isEmpty()}
        self.assertTrue(bound)
        self.assertEqual(bound - listed, set())

    def test_ptt_without_licence_acknowledgement_does_not_key(self):
        # A radio - here a simulator that says it radiates, with the
        # `device` setting still saying "sim": the gate goes by the device.
        from helpers import RadiatingSim
        from ohsnb.devices.sim import SimDevice
        win, bridge, radio = self.window(licence=False, mode="usb",
                                         device=type("Radio", (RadiatingSim, SimDevice), {}))
        self.assertEqual(radio.cfg["device"], "sim")
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        self.assertEqual(radio.state()["txBlocked"], "")     # the engine itself would key here
        QTest.mousePress(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, 0.3)
        self.assertFalse(radio.state()["keyed"])
        QTest.mouseRelease(win.ptt, Qt.MouseButton.LeftButton)
        self.assertTrue(any("licence" in t.text for t in win.toasts.toasts))
        # Space bar too.
        win.wide.setFocus()
        QTest.keyPress(win, Qt.Key.Key_Space)
        self.run_for(radio, 0.2)
        self.assertFalse(radio.state()["keyed"])
        QTest.keyRelease(win, Qt.Key.Key_Space)

    def test_the_simulator_transmits_without_the_licence_box(self):
        # Settings › Simulator says no licence is needed to try everything;
        # on the simulator nothing leaves the computer, so NB keeps that.
        win, bridge, radio = self.window(licence=False, mode="usb")
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        self.assertEqual(bridge.can_key(), "")
        QTest.mousePress(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5)
        self.assertTrue(radio.state()["keyed"])
        QTest.mouseRelease(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5)
        self.assertFalse(radio.state()["keyed"])

    def test_switching_to_a_radio_brings_the_licence_lock_back_at_once(self):
        from helpers import RadiatingSim
        from ohsnb.devices.sim import SimDevice
        from ohscore.ui.bridge import LICENCE_SENTENCE
        win, bridge, radio = self.window(licence=False, mode="usb")
        self.run_for(radio, 0.3)
        self.assertEqual(bridge.can_key(), "")
        # What a Settings save to the Pluto does: stop, then start on the new
        # device. The gate must not wait for the state feed to catch up.
        radio._inj_device = type("Radio", (RadiatingSim, SimDevice), {})(dict(radio.cfg))
        bridge.restart()
        self.assertEqual(bridge.can_key(), LICENCE_SENTENCE)
        self.assertFalse(bridge.ptt(True))
        self.assertFalse(bridge.send("cw", text="CQ"))
        self.run_for(radio, 0.3)
        self.assertFalse(radio.state()["keyed"])

    def test_ptt_with_licence_keys_and_releases(self):
        win, bridge, radio = self.window(licence=True, mode="usb")
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        QTest.mousePress(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5)
        self.assertTrue(radio.state()["keyed"])
        self.run_for(radio, until=lambda: win.glow.isVisible(), timeout=2)
        self.assertTrue(win.glow.isVisible())                 # the on-air frame
        QTest.mouseRelease(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5)
        self.assertFalse(radio.state()["keyed"])

    def test_ptt_button_redirects_to_the_panel_for_modes_that_send_from_it(self):
        """FT8/FT4, PSK/RTTY and SSTV transmit queued/scheduled messages from
        their own panel; the big PTT button used to say "unavailable" for
        them, indistinguishable from a real refusal. It should say what to
        do instead, and CW (which still keys a tuning carrier from Space)
        must not be swept into that."""
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.3)
        self.assertFalse(win.ptt.panel)
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: win.ptt.panel, timeout=5)
        self.assertIn("panel", win.ptt.toolTip().lower())
        bridge.set(mode="psk31")
        self.run_for(radio, until=lambda: win.ptt.panel, timeout=5)
        bridge.set(mode="sstv")
        self.run_for(radio, until=lambda: win.ptt.panel, timeout=5)
        bridge.set(mode="cw")
        self.run_for(radio, until=lambda: not win.ptt.panel, timeout=5)
        bridge.set(mode="usb")
        self.run_for(radio, until=lambda: not win.ptt.panel, timeout=5)

    def test_second_display_opens_and_closes(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 0.3)
        win.toggle_second()
        self.assertIsNotNone(win.second)
        sec = win.second
        self.run_for(radio, 1.0)
        self.assertTrue(sec.isVisible())
        self.assertGreater(sec.scope.wf.rows_total, 0)         # it is fed like the main scopes
        win.toggle_second()
        self.app.processEvents()
        self.assertIsNone(win.second)
        from PyQt6 import sip
        self.assertTrue(sip.isdeleted(sec) or not sec.isVisible())    # closed, and deleted on close

    def test_the_tx_button_in_every_mode_in_the_narrow_digimodes_segment(self):
        # After an FT4 send its tooltip carried "this signal is 2400 Hz wide":
        # the idle check judged FT4 by the SSB passband.
        win, bridge, radio = self.window(mode="usb", vfo=10_489_545_000.0)
        self.run_for(radio, 0.3)
        want = {"usb": "refused", "lsb": "refused", "cw": "free", "freedv": "refused", "am": "refused",
                "ft8": "panel", "ft4": "panel", "psk31": "panel", "psk63": "panel", "psk125": "panel",
                "rtty": "panel", "sstv": "panel"}
        for mode, what in want.items():
            bridge.set(mode=mode)
            self.run_for(radio, until=lambda: bridge.st.get("mode") == mode and
                         bridge.st.get("txBlocked") == radio.state()["txBlocked"], timeout=5)
            self.run_for(radio, 0.3)
            tip = win.ptt.toolTip()
            self.assertNotIn("2400 Hz wide", tip, mode)
            if what == "panel":
                self.assertTrue(win.ptt.panel, mode)
                if mode == "sstv":                   # 1.25 kHz: a real refusal here, and it says so
                    self.assertIn("1250 Hz wide", tip)
                else:
                    self.assertEqual(win.ptt.blocked, "", mode)
            elif what == "refused":
                self.assertTrue(win.ptt.blocked, mode)
                self.assertIn("not available", tip, mode)
            else:
                self.assertEqual(win.ptt.blocked, "", mode)
                self.assertIn("Transmit (Space)", tip, mode)

    def test_the_lower_tabs_follow_the_view_however_it_was_reached(self):
        # The 0.1.3 screenshots showed Logbook and Memories with the Mode tab
        # still lit. Checked on the painted pixels, since that is what was
        # wrong: the tab's value was right and its highlight never moved.
        from ohscore.ui import theme
        from ohscore.ui.chrome import IconButton
        win, bridge, radio = self.window()
        self.run_for(radio, 0.3)

        def lit():
            img = win.views.grab().toImage()
            acc = theme.c("accent")
            dist = []
            for i in range(len(win.views.options)):
                cell = win.views._cell(i)
                c = img.pixelColor(int(cell.left() + 6), int(cell.center().y()))
                dist.append(abs(c.red() - acc.red()) + abs(c.green() - acc.green()) + abs(c.blue() - acc.blue()))
            return win.views.options[dist.index(min(dist))][0]

        def settles_on(view, how):
            end = time.monotonic() + 0.5          # wall time: the slide is a 180 ms animation
            while time.monotonic() < end:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertEqual(win.stack.currentIndex(), {"mode": 0, "log": 1, "mem": 2}[view], how)
            self.assertEqual(lit(), view, how)

        self.assertEqual(lit(), "mode")
        book = next(b for b in win.findChildren(IconButton) if b.toolTip().startswith("Logbook"))
        QTest.mouseClick(book, Qt.MouseButton.LeftButton)
        settles_on("log", "the header's book button")
        mem = win.views._cell(2).center().toPoint()
        QTest.mouseClick(win.views, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mem)
        settles_on("mem", "the tab itself")
        menu = {a.text(): a for m in win.menuBar().actions() if m.menu() for a in m.menu().actions()}
        menu["Operate"].trigger()
        settles_on("mode", "View > Operate")
        win.activateWindow()
        QTest.keyClick(win, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        settles_on("log", "Ctrl+L")
        menu["Memories"].trigger()
        settles_on("mem", "View > Memories")
        win.toggle_second()                       # a second display opening leaves the view alone
        settles_on("mem", "the second display")
        win.toggle_second()
        menu["Logbook"].trigger()
        settles_on("log", "View > Logbook")

    def test_the_tx_badge_says_what_tx_lock_says_and_fits(self):
        # 0.1.3: "SEARCHING -2.900 …" - the error cut off, and a word that
        # contradicted the txCorr beside it in the status strip.
        from ohsnb.ui.status import LockBadge
        win, bridge, radio = self.window()
        self.run_for(radio, 0.3)
        b = win.tx_badge
        cases = [
            # (engine state, keyed, txErr, trusted) -> word, the value drawn (None: no value)
            ("searching", True, -2900.0, True, "SEARCHING", None),     # txErr is the last over's: not shown
            ("searching", True, 0.0, False, "SEARCHING", None),        # was "SEARCHING +0.0 Hz"
            ("landed", True, -2900.0, True, "LANDED", "-2.9"),
            ("landed", True, -47_000.0, True, "LANDED", "-47"),        # a Pluto 20 ppm out
            ("landed", True, 312.4, True, "LANDED", "+312"),
            ("locked", True, 0.8, True, "LOCKED", "+0.8 Hz"),
            ("idle", False, 0.8, True, "IDLE", "ppm"),
        ]
        for size in ((1366, 768), (1920, 1080)):
            win.resize(*size)
            self.run_for(radio, 0.2)
            for tl, keyed, err, trusted, word, value in cases:
                bridge.st.update(txLockState=tl, keyed=keyed, txErr=err, txCorrTrusted=trusted, txLock=True,
                                 txPpm=-1.2083, txRadio="sdr")
                win._sync_locks()
                how = f"{tl} {err} at {size[0]} wide ({b.width()} px)"
                self.assertEqual(LockBadge.WORDS[b.state], word, how)
                text, _x, _w = b.detail_layout()
                if value is None:
                    self.assertEqual(text, "", how)
                else:
                    self.assertIn(value, text, how)
                    self.assertNotIn("…", text, how)                   # whole, never cut off
                b.grab()

    def test_a_closed_window_stops_filtering_the_applications_events(self):
        # The window's key filter is on the whole application. A closed one
        # left it there, and every later window's events went through it:
        # a test module's worth of them stalled the event loop for seconds.
        old, _bridge, old_radio = self.window()
        self.run_for(old_radio, 0.2)
        seen = []
        old.eventFilter = lambda obj, ev: (seen.append(ev.type()), False)[1]
        self.run_for(old_radio, 0.2)
        self.assertTrue(seen, "the probe never saw an event while the window was open")
        old.close()
        self.app.processEvents()
        seen.clear()
        win, bridge, radio = self.window()
        self.run_for(radio, 0.3)
        QTest.keyClick(win.wide, Qt.Key.Key_Up)
        self.assertEqual(seen, [])

    def test_a_closed_second_display_is_deleted_and_stops_listening(self):
        # Each open used to leave a hidden window behind, still connected to
        # the bridge and repainting its scope on every spectrum line.
        import gc
        from PyQt6.QtCore import QCoreApplication, QEvent
        from ohscore.ui.second import SecondDisplay
        win, bridge, radio = self.window()
        self.run_for(radio, 0.3)
        before = (bridge.receivers(bridge.changed), bridge.receivers(bridge.wide))
        for _ in range(3):
            win.toggle_second()
            self.run_for(radio, 0.3)
            win.toggle_second()
            self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        gc.collect()
        alive = [w for w in QApplication.topLevelWidgets() if isinstance(w, SecondDisplay)]
        self.assertEqual(alive, [])
        self.assertEqual((bridge.receivers(bridge.changed), bridge.receivers(bridge.wide)), before)

    def test_waterfall_levels_popover(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 2.0)
        b = win.wide._levels_button()
        QTest.mouseClick(win.wide, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         b.center().toPoint())
        pop = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "AdjustPopover"
                   and w.isVisible())
        auto_floor, auto_range = win.wide.auto_levels()
        pop.auto.set_on(False, emit=True)               # manual starts where auto was
        self.assertFalse(win.prefs["wfAuto"])
        self.assertAlmostEqual(win.prefs["wfFloor"], round(auto_floor), delta=1.0)
        self.assertEqual(win.wide._wf_levels(), (win.prefs["wfFloor"], win.prefs["wfRange"]))
        lut_before = win.zoom.wf.lut.copy()
        pop._palette("Glacier")                         # the palette is shared by every scope
        self.assertEqual(win.prefs["palette"], "Glacier")
        self.assertFalse((win.zoom.wf.lut == lut_before).all())
        pop.hide()

    def test_scope_colours_from_the_adjust_panel_to_every_scope(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 1.0)
        win.toggle_second()
        self.run_for(radio, 0.5)
        asked = []
        win.open_settings = lambda page="", anchor="": asked.append((page, anchor))
        b = win.zoom._levels_button()
        QTest.mouseClick(win.zoom, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         b.center().toPoint())
        pop = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "AdjustPopover"
                   and w.isVisible())
        pop._colours()
        self.run_for(radio, 0.1)
        self.assertEqual(asked, [("page_display", "look_anchor")])     # Settings › Display, at the colours
        del win.open_settings
        d = win.settings_dialog()
        d.show_page("page_display", "look_anchor")
        self.assertEqual(d.PAGES[d.stack.currentIndex()][2], "page_display")
        d.look_editor.pick_preset("amber")
        d.save()
        self.assertEqual(win.prefs["scopeLook"], {"preset": "amber"})
        win.apply_prefs(False)
        self.run_for(radio, 0.3)
        scopes = [win.wide, win.zoom, win.second.scope]
        for sc in scopes:
            sc.repaint()
            self.assertEqual(sc.look.background.name(), "#0a0703")       # the second display's too
        win.toggle_second()

    def test_the_display_style_changes_the_display_and_no_reading(self):
        """The zoom scope's SDR Console-like style, chosen in its adjust
        panel, on the simulator: the engine is told nothing, and the
        window's receive SNR - read from the same spectrum lines the scope
        draws - comes out the same in either style."""
        win, bridge, radio = self.window()
        self.run_for(radio, 2.0)
        got = []
        bridge.zoom.connect(got.append)
        self.run_for(radio, 1.0)
        bridge.zoom.disconnect(got.append)
        lines = [ln for batch in got for ln in batch][-10:]
        self.assertTrue(lines)
        told = []
        real_set = bridge.set
        bridge.set = lambda *a, **kw: (told.append((a, kw)), real_set(*a, **kw))[1]
        b = win.zoom._levels_button()
        QTest.mouseClick(win.zoom, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b.center().toPoint())
        pop = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "AdjustPopover"
                   and w.isVisible())
        snr = {}
        for style in ("nb", "sdrconsole"):
            pop.style._choose([k for k, _ in pop.style.options].index(style))
            self.assertEqual(win.zoom.display_style(), style)
            seen = []
            with mock.patch.object(win.rxcard, "set_snr", lambda v, n=None: seen.append((v, n))):
                win.zoom.on_lines(lines)
                win.on_zoom_lines(lines)
            snr[style] = seen
        pop.hide()
        del bridge.set
        self.assertEqual(told, [])                         # nothing reached the engine
        self.assertTrue(snr["nb"])
        self.assertEqual(snr["nb"], snr["sdrconsole"])
        self.assertEqual(win.prefs["zoomSpecStyle"], "sdrconsole")
        self.assertIn("RBW", win.zoom.rbw_text())
        self.assertTrue(self.run_for(radio, 1.0))          # and it keeps drawing, live

    def test_theme_switch_rebuilds_and_keeps_running(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 1.0)
        win.set_theme("light")
        self.run_for(radio, 1.0)
        self.assertEqual(win.prefs["theme"], "light")
        self.assertGreater(win.wide.wf.rows_total, 0)         # the new scopes are fed
        win.set_theme("dark")
        self.run_for(radio, 0.5)

    def test_escape_unkeys(self):
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        bridge.ptt(True)
        self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5)
        win.activateWindow()
        QTest.keyClick(win, Qt.Key.Key_Escape)
        self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5)
        self.assertFalse(radio.state()["keyed"])

    def test_readout_wheel_tunes_by_digit(self):
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 0.3)
        win.readout.repaint()
        rect, place = next((r, p) for r, p in win.readout.cells if p == 3)   # the 1 kHz digit
        before = radio.state()["vfo"]
        from PyQt6.QtGui import QWheelEvent
        pos = rect.center()
        ev = QWheelEvent(pos, win.readout.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(win.readout, ev)
        self.run_for(radio, 0.2)
        self.assertEqual(radio.state()["vfo"], before + 1000)


    def test_a_logged_call_opens_its_qrz_page_and_a_double_click_still_edits(self):
        from PyQt6.QtWidgets import QApplication
        win, bridge, radio = self.window()
        radio.log_qso("EA8/g4abc/p", rstSent="59")
        lv = win.logview
        lv.reload()
        row, col = lv.table.rowCount() - 1, lv.call_col
        wait = QApplication.styleHints().mouseDoubleClickInterval() / 1000 + 0.3
        with mock.patch("ohscore.ui.logbook.QDesktopServices.openUrl", return_value=True) as opened:
            lv.table.cellClicked.emit(row, col)
            lv.table.cellDoubleClicked.emit(row, col)        # the second click of a double-click
            self.run_for(radio, timeout=wait, until=lambda: False)
            opened.assert_not_called()
            lv.table.cellClicked.emit(row, col - 1 if col else col + 1)   # not the call column
            lv.table.cellClicked.emit(row, col)
            self.run_for(radio, timeout=wait, until=lambda: False)
        opened.assert_called_once()
        self.assertEqual(opened.call_args[0][0].toString(), "https://www.qrz.com/db/G4ABC")


    def test_ft8_decoder_is_told_my_call_and_the_dx_call(self):
        # jt9's a-priori passes (-c/-x): the operator's call, and whoever
        # the sequencer is working - set by answering a CQ, gone with
        # Clear - reach the engine's decoder, which asks at every slot.
        from ohscore.ui.panels.ft8 import Ft8Panel
        win, bridge, radio = self.window(mode="ft8", callsign="GM4BRI")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel) and radio.decoder is not None, timeout=5)
        if radio.decoder is None or not hasattr(radio.decoder, "calls"):
            self.skipTest("no FT8 decoder here (jt9 not installed)")
        p = win.panel
        self.assertEqual(radio.decoder.calls(), ("GM4BRI", ""))
        p.on_event({"mode": "ft8", "slot": 1_700_000_000.0, "text": "CQ EA8/G4ABC IL18", "call": "EA8/G4ABC",
                    "snr": -10, "dt": 0.1, "df": 1200})
        p._row_clicked(p.table.rowCount() - 1, 5)
        self.assertEqual(radio.state()["dxCall"], "EA8/G4ABC")
        self.assertEqual(radio.decoder.calls(), ("GM4BRI", "EA8/G4ABC"))
        p.set_tx_enabled(False)
        p.clear_qso()
        self.assertEqual(radio.decoder.calls(), ("GM4BRI", ""))

    def test_ft8_band_activity_shows_the_senders_country(self):
        from ohscore import dxcc
        from ohscore.ui.panels.ft8 import Ft8Panel
        from test_dxcc import SAMPLE
        win, bridge, radio = self.window(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        p = win.panel
        p.countries = dxcc.Countries(SAMPLE)
        p.table.setColumnHidden(6, False)
        p.on_event({"mode": "ft8", "slot": 1_700_000_000.0, "text": "CQ EA8/G4ABC IL18", "call": "EA8/G4ABC",
                    "snr": -10, "dt": 0.1, "df": 1200})
        p.on_event({"mode": "ft8", "slot": 1_700_000_000.0, "text": "G4ABC KH6AB -12", "call": "KH6AB",
                    "snr": -12, "dt": 0.2, "df": 900})
        last = p.table.rowCount() - 1
        self.assertEqual(p.table.item(last - 1, 6).text(), "Canary Islands")
        self.assertEqual(p.table.item(last, 6).text(), "Hawaii")
        self.assertEqual(p.table.item(last, 5).text(), "G4ABC KH6AB -12")   # the message keeps its column

    def test_ft8_gives_the_band_activity_most_of_the_window_and_keeps_its_own_sizes(self):
        from ohscore.ui.panels.ft8 import Ft8Panel
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        win, bridge, radio = self.window(mode="usb")
        win.resize(1920, 1080)
        self.run_for(radio, sim_s=0.3)
        usb = win.split_main.sizes()
        self.assertAlmostEqual(usb[0] / sum(usb), 0.42, delta=0.03)   # Voice's share for the wide scope
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        self.app.processEvents()
        ft8 = win.split_main.sizes()
        self.assertGreater(ft8[1], 2 * ft8[0])             # the band activity's half, much the larger
        self.assertLess(win.split_low.sizes()[0], 0.25 * sum(win.split_low.sizes()))
        rows_ft8 = win.panel.table.viewport().height()
        # The operator drags the FT8 layout; SSB's is untouched by it and
        # each comes back as it was left, after a restart too.
        win.split_main.setSizes([300, sum(ft8) - 300])
        win.split_main.splitterMoved.emit(300, 1)
        bridge.set(mode="usb")
        self.run_for(radio, until=lambda: not isinstance(win.panel, Ft8Panel), timeout=5)
        # SSB's default again (within what the panel stack, which now holds
        # the taller FT8 panel too, lets the lower half shrink to).
        back = win.split_main.sizes()
        self.assertLess(abs(back[0] - usb[0]), 40)
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        self.assertEqual(win.split_main.sizes(), [300, sum(ft8) - 300])
        self.assertLess(win.panel.table.viewport().height(), rows_ft8)
        # Kept as a share of the height (the Digital workspace's), so on a
        # smaller window the FT8 layout is the same layout, not 300 px.
        share = 300 / sum(ft8)
        win.save_state()
        win.prefs.save()
        saved = Prefs(config.CONFIG)
        self.assertAlmostEqual(saved["workspaces"]["digital"]["wide"], share, places=3)
        self.assertNotIn("voice", saved["workspaces"])      # SSB's never dragged: still the default
        self.assertEqual(saved["slotSplitters"]["split_main"], [300, sum(ft8) - 300])   # for a downgrade
        # (1600 x 960, not smaller: below that the FT8 panel's own minimum
        # height decides, which is the window tiers' business.)
        win.resize(1600, 960)
        bridge.set(mode="usb")
        self.run_for(radio, until=lambda: not isinstance(win.panel, Ft8Panel), timeout=5)
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        self.app.processEvents()
        small = win.split_main.sizes()
        self.assertLess(sum(small), sum(ft8) - 100)
        self.assertAlmostEqual(small[0] / sum(small), share, delta=0.01)

    def test_ft8_text_size_follows_ctrl_and_the_wheel_and_is_kept(self):
        from PyQt6.QtCore import QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent
        from ohscore.ui.panels.ft8 import Ft8Panel
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        win, bridge, radio = self.window(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        p = win.panel
        p.on_event({"mode": "ft8", "slot": 1_700_000_000.0, "text": "CQ DL1ABC JO31", "call": "DL1ABC",
                    "snr": -10, "dt": 0.1, "df": 1200})
        last = p.table.rowCount() - 1
        h0, px0 = p.table.rowHeight(last), p.table.font().pixelSize()
        vp = p.table.viewport()
        for _ in range(3):
            ev = QWheelEvent(QPointF(10, 10), QPointF(vp.mapToGlobal(QPoint(10, 10))), QPoint(), QPoint(0, 120),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                             Qt.ScrollPhase.NoScrollPhase, False)
            self.app.sendEvent(vp, ev)
        self.assertEqual(p.table.font().pixelSize(), px0 + 3)
        self.assertGreater(p.table.rowHeight(last), h0)       # the rows already there grow with it
        self.assertEqual(Prefs(config.CONFIG)["ft8FontPx"], px0 + 3)
        QTest.keyClick(p.table, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(p.table.font().pixelSize(), px0 + 2)

    def test_ft8_tx_eq_rx_puts_tx_on_rx_and_keeps_them_together(self):
        from ohscore.ui.panels.ft8 import Ft8Panel
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        win, bridge, radio = self.window(mode="ft8")
        self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5)
        p = win.panel
        p.set_offsets(rx=1200, tx=1500)

        def offsets():
            return p.prefs["ft8RxOffset"], p.prefs["ft8TxOffset"], dict(win.zoom.audio_offsets)

        QTest.mouseClick(p.lock, Qt.MouseButton.LeftButton)
        self.assertEqual(offsets(), (1200, 1200, {"rx": 1200, "tx": 1200}))
        self.assertFalse(p.hold.isEnabled())
        # The zoom scope's clicks, TX marker and RX marker: both follow either.
        win.offset_click(900, is_tx=True)
        self.assertEqual(offsets()[:2], (900, 900))
        win.offset_click(1700, is_tx=False)
        self.assertEqual(offsets()[:2], (1700, 1700))
        # Answering a station with Hold TX freq on still lands TX on it.
        self.assertTrue(p.hold.on)
        p.on_event({"mode": "ft8", "slot": 1_700_000_000.0, "text": "CQ DL1ABC JO31", "call": "DL1ABC",
                    "snr": -10, "dt": 0.1, "df": 1234})
        p._row_clicked(p.table.rowCount() - 1, 5)
        p.set_tx_enabled(False)
        self.assertEqual(offsets()[:2], (1234, 1234))
        self.assertTrue(Prefs(config.CONFIG)["ft8TxEqRx"])          # saved
        # Off: the two move apart again.
        QTest.mouseClick(p.lock, Qt.MouseButton.LeftButton)
        self.assertTrue(p.hold.isEnabled())
        win.offset_click(1000, is_tx=True)
        self.assertEqual(offsets()[:2], (1234, 1000))
        self.assertFalse(Prefs(config.CONFIG)["ft8TxEqRx"])


if __name__ == "__main__":
    unittest.main()
