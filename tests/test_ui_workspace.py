"""Workspaces (docs/ui-overhaul-2026-10.md section 2), the fixed tab row
(5.2), the status strip's timings and REC, and the Receive card's compact
form (5.10, FINDINGS 6).

The rules first, on the model alone (ohscore/ui/workspace.py); then the
real window on the simulator, driven as an operator would - mode buttons,
W and Shift+W, the Band list, dragging a splitter - and checked by what
it shows: the splitters' shares, which view is up, which controls are
visible, what the strip and the diagnostics report say. Nothing here
keys a real radio; the keyed cases key the simulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QObject, Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover - the engine's tests still run without PyQt6
    HAVE_QT = False

from helpers import make_radio, sim_seconds

from ohscore.ui import workspace as wsm


class Rules(unittest.TestCase):
    def test_auto_follows_the_mode(self):
        w = wsm.Workspaces()
        self.assertEqual(w.effective("usb"), "voice")
        self.assertEqual(w.effective("ft8"), "digital")
        self.assertEqual(w.effective("sstv"), "digital")       # pictures share Digital's (decision 1)
        self.assertEqual(w.effective("fm"), "voice")

    def test_w_cycles_from_the_one_showing_and_pins(self):
        w = wsm.Workspaces()
        self.assertEqual(w.cycle("usb"), "watch")              # Voice showing: Watch is next
        self.assertTrue(w.pinned)
        self.assertEqual(w.effective("ft8"), "watch")          # a mode change does not move a pin
        self.assertEqual(w.cycle("ft8"), "digital")
        self.assertEqual(w.cycle("ft8"), "voice")
        w.auto()
        self.assertEqual(w.effective("ft8"), "digital")

    def test_a_mode_request_unpins(self):
        w = wsm.Workspaces("watch")
        w.mode_requested()
        self.assertEqual(w.choice, "auto")

    def test_an_unknown_choice_is_auto(self):
        self.assertEqual(wsm.Workspaces("sideways").choice, "auto")

    def test_layout_is_the_defaults_with_the_operators_changes_over_them(self):
        lay = wsm.layout("watch", None, watch_view="skim")
        self.assertEqual((lay["wide"], lay["zoom"], lay["rail"], lay["view"]), (0.66, 0.22, 210, "skim"))
        self.assertEqual(wsm.layout("digital", None)["view"], "mode")
        lay = wsm.layout("voice", {"wide": 0.5, "zoom": 2.0, "rail": True, "view": "log",
                                   "expanded": ["receive", "nonsense"]})
        self.assertEqual(lay["wide"], 0.5)
        self.assertEqual(lay["zoom"], 0.45)                     # out of range: the default
        self.assertEqual(lay["rail"], 320)                      # not a width: the default
        self.assertEqual((lay["view"], lay["expanded"]), ("log", ["receive"]))

    def test_remember_and_expanded(self):
        saved = {"voice": {"wide": 0.5}}
        out = wsm.remember(saved, "voice", view="log")
        self.assertEqual(out["voice"], {"wide": 0.5, "view": "log"})
        self.assertEqual(saved, {"voice": {"wide": 0.5}})       # a new dict: Prefs sees the assignment
        self.assertEqual(wsm.expanded_with([], "transmit", True), ["transmit"])
        self.assertEqual(wsm.expanded_with(["transmit"], "receive", True), ["receive", "transmit"])
        self.assertEqual(wsm.expanded_with(["receive", "transmit"], "receive", False), ["transmit"])

    def test_watch_never_hides_transmit_over_the_air_an_arm_or_a_warning(self):
        idle = dict(on_air=False, armed=False, warning=False)
        self.assertEqual(wsm.transmit_form("watch", **idle), "hidden")
        for k in idle:
            self.assertEqual(wsm.transmit_form("watch", **{**idle, k: True}), "full", k)
        self.assertEqual(wsm.transmit_form("digital", **idle), "compact")
        self.assertEqual(wsm.transmit_form("voice", **idle), "full")


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class WindowCase(unittest.TestCase):
    APP = "nb"

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        if cls.APP == "radio":
            from ohsradio.ui import make_app
            cls.app = qt_app(make_app)
        else:
            cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui-radio.json")
        self.errors = []
        self._hook = sys.excepthook
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
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def window(self, size=(1920, 1080), **over):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        # A licence class, so the sim's standing "no licence class" warning
        # (which rightly keeps Watch's Transmit card up) is not there.
        for k, v in (("licenceClass", "full"), ("callsign", "GM4BRI"), ("locator", "IO75RL")):
            over.setdefault(k, v)
        radio = make_radio(self.tmp, audio_source=lambda n: __import__("numpy").full(n, 0.2, "float32"), **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(*size)
        win.show()
        self.wins.append((win, bridge))
        self.settle()
        return win, bridge, radio

    def close(self, win, bridge):
        win.close()
        bridge.stop()
        self.wins.remove((win, bridge))
        self.app.processEvents()

    def settle(self, n=5):
        for _ in range(n):
            self.app.processEvents()
            time.sleep(0.01)

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

    @staticmethod
    def shares(win):
        """(wide scope's share of the body, zoom's share of the lower width, rail px)."""
        m, lo, side = win.split_main.sizes(), win.split_low.sizes(), win.split_side.sizes()
        return m[0] / sum(m), lo[0] / sum(lo), side[1]

    @staticmethod
    def drag(splitter, first_share):
        """As the operator's drag: new sizes, then the signal Qt sends."""
        t = sum(splitter.sizes())
        a = int(t * first_share)
        splitter.setSizes([a, t - a])
        splitter.splitterMoved.emit(a, 1)

    def press_mode(self, win, mode):
        QTest.mouseClick(win.modegrid.cells[mode], Qt.MouseButton.LeftButton)
        self.settle()

    def key(self, win, k, mods=Qt.KeyboardModifier.NoModifier):
        win.activateWindow()
        QTest.keyClick(win, k, mods)
        self.settle()


class Switching(WindowCase):
    def test_the_workspace_follows_the_mode_until_pinned_and_a_mode_button_unpins(self):
        win, bridge, radio = self.window(mode="usb")
        self.assertEqual(win.workspace, "voice")
        self.press_mode(win, "ft8")
        self.assertEqual((radio.state()["mode"], win.workspace), ("ft8", "digital"))
        bridge.set(mode="sstv")
        self.settle()
        self.assertEqual(win.workspace, "digital")              # pictures stay in Digital
        self.press_mode(win, "usb")
        self.assertEqual(win.workspace, "voice")
        self.key(win, Qt.Key.Key_W)
        self.assertEqual((win.workspace, win.ws.choice), ("watch", "watch"))
        self.assertEqual(win.prefs["workspace"], "watch")
        self.assertEqual(win.views.value, "skim")                # Watch opens on the Band list
        self.assertIn("Watch", win.ws_button.text)
        # Browsing the band from Watch stays in Watch: a Band-list tune to
        # the FT8 calling window changes the mode, not the workspace.
        win.skim_tune({"kind": "digital", "mode": "ft8", "dial": 10_489_540_000.0, "exact": True,
                       "f": 10_489_541_500.0})
        self.settle()
        self.assertEqual((radio.state()["mode"], win.workspace), ("ft8", "watch"))
        # A mode button is a request to operate: its workspace, Auto, Operate.
        self.press_mode(win, "usb")
        self.assertEqual((win.workspace, win.ws.choice, win.views.value), ("voice", "auto", "mode"))
        self.key(win, Qt.Key.Key_W)
        self.key(win, Qt.Key.Key_W)
        self.assertEqual(win.ws.choice, "digital")
        self.key(win, Qt.Key.Key_W, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual((win.ws.choice, win.workspace), ("auto", "voice"))
        self.assertIn("auto", win.ws_button.text)

    def test_the_view_menu_and_the_button_choose_the_same_way(self):
        win, bridge, radio = self.window(mode="usb")
        self.assertIs(win.ws_menu, next(a.menu() for m in win.menuBar().actions() if m.menu()
                                        for a in m.menu().actions() if a.menu() is not None))
        win.ws_actions["digital"].trigger()
        self.assertEqual((win.workspace, win.ws.choice), ("digital", "digital"))
        self.assertTrue(win.ws_actions["digital"].isChecked())
        QTest.mouseClick(win.ws_button, Qt.MouseButton.LeftButton)
        self.settle()
        self.assertTrue(win.ws_menu.isVisible())
        win.ws_menu.hide()
        win.ws_actions["auto"].trigger()
        self.assertEqual(win.workspace, "voice")

    def test_a_switch_changes_nothing_about_the_radio(self):
        win, bridge, radio = self.window(mode="usb")
        keys = ("mode", "vfo", "txVfo", "keyed", "txGain", "split", "xitOn")
        before = {k: radio.state().get(k) for k in keys}
        for _ in range(3):
            win.cycle_workspace()
            self.settle(2)
            self.assertEqual({k: radio.state().get(k) for k in keys}, before)

    def test_a_switch_builds_nothing_and_is_quick(self):
        # The GUI thread's own time (thread_time), with the radio stopped
        # so that the simulator's lines and decodes arriving meanwhile are
        # not counted. A switch is its own work (ws_switch_ms) and the one
        # repaint of the window it causes. On ohs-dev's offscreen platform
        # at 1600 x 960 that repaint alone is about 40 ms - any resize
        # costs it - and the switch adds 5 ms (to Voice) to 25 ms (Watch,
        # where showing the Band view is 22 ms of Qt's own; Digital, where
        # resizing the FT8 panel is as much). So: the switch's own work
        # under 50 ms, and switch plus repaint under 50 ms more
        # than a repaint with no switch. Medians, since the event loop's
        # garbage collection lands in one of them.
        win, bridge, radio = self.window(mode="ft8", size=(1600, 960))
        self.run_for(radio, 1.0)
        for _ in range(6):                               # every view and form shown once
            win.cycle_workspace()
            self.settle(2)
        bridge.stop()
        self.settle(2)

        def median(xs):
            return sorted(xs)[len(xs) // 2]

        repaint = []
        for _ in range(5):
            c0 = time.thread_time()
            win.centralWidget().update()
            self.app.processEvents()
            repaint.append((time.thread_time() - c0) * 1000.0)
        def objects():
            # Animations come and go by themselves (a fade finishing is
            # deleted); anything else new would be the switch building.
            from PyQt6.QtCore import QAbstractAnimation
            return sum(1 for o in win.findChildren(QObject) if not isinstance(o, QAbstractAnimation))

        n = objects()
        costs, own = [], []
        for _ in range(9):
            c0 = time.thread_time()
            win.cycle_workspace()
            self.app.processEvents()
            costs.append((time.thread_time() - c0) * 1000.0)
            own.append(win.ws_switch_ms)
            self.assertEqual(objects(), n, win.workspace)          # nothing built, nothing lost
        self.assertLess(median(own), 50.0, own)
        self.assertLess(median(costs), median(repaint) + 50.0, (costs, repaint))


    def test_the_workspace_button_is_never_cut_off(self):
        from PyQt6.QtGui import QFontMetricsF
        win, bridge, radio = self.window(mode="usb")
        for size in ((1920, 1080), (1366, 768), (1180, 700)):
            win.resize(*size)
            self.settle()
            b = win.ws_button
            need = QFontMetricsF(b._font()).horizontalAdvance(b.text) + 20
            self.assertGreaterEqual(b.width(), need, f"{size}: {b.text!r}")
            self.assertIn("Voice", b.text)
        win.resize(1920, 1080)
        self.settle()
        self.assertTrue(win.ws_button.text.startswith("Workspace: Voice"))


class Proportions(WindowCase):
    def test_each_workspace_has_the_plans_proportions_at_two_sizes(self):
        # Section 4's mock-ups at 1920 x 1080, and the same shares on a
        # 1366 x 768 laptop, within 5 %. Watch's rail is as slim as its
        # cards allow; it is checked against what they need.
        #
        # The wide scope's share holds where the lower panel's own minimum
        # allows it: Watch's two thirds leave 300 px at 1920 x 1080, and
        # the Band view needs 394 (its over-the-beacon table is a fixed six
        # rows, ohsnb/ui/opview.py) - so here Watch shows Operate (USB's
        # panel, 290 px), and below that the share gives way, never the
        # panel.
        win, bridge, radio = self.window(mode="usb")
        for size in ((1920, 1080), (1366, 768)):
            win.resize(*size)
            self.settle()
            for ws in ("voice", "digital", "watch"):
                win.choose_workspace(ws)
                win.show_view("mode")
                self.settle()
                spec = wsm.SPECS[ws]
                wide, zoom, rail = self.shares(win)
                lower = win.split_low
                if lower.height() > lower.minimumSizeHint().height() + 2:
                    self.assertAlmostEqual(wide, spec.wide, delta=0.05, msg=f"{ws} {size}")
                else:
                    self.assertLess(wide, spec.wide, f"{ws} {size}")
                    self.assertNotEqual(size, (1920, 1080), f"{ws}: no room for its share at 1920 x 1080")
                self.assertAlmostEqual(zoom, spec.zoom, delta=0.05, msg=f"{ws} {size}")
                # At 1366 x 768, the Compact tier, the rail is Compact's (WP6).
                want = wsm.rail_width(wsm.layout(ws, None), win.tier)
                self.assertLessEqual(abs(rail - max(want, win.rail_scroll.minimumWidth())), 2, f"{ws} {size}")
                self.assertGreaterEqual(win.zoom.width(), spec.zoom_min)

    def test_dragged_layouts_survive_a_resize_full_screen_a_theme_change_and_a_restart(self):
        # Shares each panel has room for at 1366 x 768 too (USB's Operate
        # panel needs about 330 px under the wide scope, FT8's 430 and 890
        # px across), so what is checked is the fraction kept, not a
        # panel's minimum.
        win, bridge, radio = self.window(mode="usb")
        self.drag(win.split_main, 0.36)                     # Voice
        bridge.set(mode="ft8")
        self.settle()
        self.assertEqual(win.workspace, "digital")
        self.drag(win.split_main, 0.20)                     # Digital
        win.choose_workspace("watch")
        bridge.set(mode="usb")
        win.show_view("mode")
        self.settle()
        self.drag(win.split_main, 0.35)                     # Watch
        want = {"voice": (0, 0.36, "usb"), "digital": (0, 0.20, "ft8"), "watch": (0, 0.35, "usb")}

        def check(how):
            for ws, (i, share, mode) in want.items():
                win.choose_workspace(ws)
                bridge.set(mode=mode)
                win.show_view("mode", remember=False)
                self.settle()
                self.assertAlmostEqual(self.shares(win)[i], share, delta=0.02, msg=f"{ws} after {how}")

        check("dragging")
        win.resize(1366, 768)
        self.settle()
        check("1920x1080 -> 1366x768")
        win.showFullScreen()
        self.settle(10)
        check("full screen")
        win.showNormal()
        self.settle(10)
        win.set_theme("light")
        self.settle()
        check("Ctrl+T")
        win.choose_workspace("watch")
        self.close(win, bridge)
        win, bridge, radio = self.window(mode="ft8")
        self.assertEqual(win.workspace, "watch")             # still pinned after a restart
        check("a restart")
        # The two older layouts are still written for a downgrade.
        win.choose_workspace("auto")
        bridge.set(mode="ft8")
        self.settle()
        self.assertEqual(win.workspace, "digital")
        win.save_state()
        self.assertEqual(win.prefs["slotSplitters"]["split_main"], win.split_main.sizes())

    def test_reset_puts_the_workspaces_defaults_back(self):
        win, bridge, radio = self.window(mode="usb")
        self.drag(win.split_main, 0.7)
        win.show_view("log")
        win.reset_workspace()
        self.settle()
        self.assertAlmostEqual(self.shares(win)[0], wsm.SPECS["voice"].wide, delta=0.03)
        self.assertEqual(win.views.value, "mode")
        self.assertNotIn("voice", win.prefs["workspaces"])


class Views(WindowCase):
    def test_each_workspace_remembers_its_view(self):
        win, bridge, radio = self.window(mode="usb")
        win.show_view("log")                                # Voice: the Logbook
        win.choose_workspace("digital")
        self.assertEqual(win.views.value, "mode")           # Digital: never chosen, Operate
        win.show_view("mem")
        win.choose_workspace("watch")
        self.assertEqual(win.views.value, "skim")
        win.choose_workspace("voice")
        self.assertEqual(win.views.value, "log")
        win.choose_workspace("digital")
        self.assertEqual(win.views.value, "mem")
        self.assertEqual(win.stack.currentIndex(), win.view_keys().index("mem"))

    def test_the_tabs_are_the_same_in_every_mode_and_operate_names_the_mode(self):
        from ohscore.ui import theme
        win, bridge, radio = self.window(mode="usb")
        tabs = list(win.views.options)
        self.assertEqual([lab for _k, lab in tabs[:3]], ["Operate", "Logbook", "Memories"])
        for mode, first in (("ft8", "FT8"), ("q65", "Q65"), ("js8", "JS8"), ("usb", "USB")):
            bridge.set(mode=mode)
            self.settle()
            self.assertEqual(win.views.options, tabs, mode)          # no "q65" tab
            self.assertTrue(win.panel_title.text().startswith(first), win.panel_title.text())
            self.assertIs(win.panel_title.parentWidget(), win.stack.widget(0))
        self.assertIn("15 s periods", win.mode_line("ft8", {})[0])
        # A mode missing something here says so, in the warning colour.
        bridge.st["modes"] = {**(bridge.st.get("modes") or {}), "freedv": {"missing": "needs codec2"}}
        bridge.set(mode="freedv")
        self.settle()
        self.assertIn("needs codec2", win.panel_title.text())
        self.assertIn(theme.t()["warn"], win.panel_title.styleSheet())


class Transmit(WindowCase):
    def test_escape_unkeys_from_each_workspace_and_watch_shows_transmit_while_keyed(self):
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked", timeout=20)
        for ws in ("digital", "voice", "watch"):
            win.choose_workspace(ws)
            self.settle()
            if ws == "watch":
                self.assertFalse(win.txcard.isVisibleTo(win.rail))
            bridge.ptt(True)
            self.assertTrue(self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5), ws)
            self.settle()
            self.assertTrue(win.txcard.isVisibleTo(win.rail), ws)
            if ws == "watch":
                self.assertEqual(win.txcard.form, "full")
            self.key(win, Qt.Key.Key_Escape)
            self.assertTrue(self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5), ws)
        self.settle()
        win._sync_ptt()
        self.settle()
        self.assertEqual(win.txcard.form, "hidden")
        self.assertFalse(win.txcard.isVisibleTo(win.rail))      # Watch, nothing on the air: hidden again

    def test_watch_shows_transmit_while_a_warning_stands(self):
        win, bridge, radio = self.window(mode="usb")
        win.choose_workspace("watch")
        self.assertFalse(win.txcard.isVisibleTo(win.rail))
        w = {"key": "rig-aim", "level": "warn", "text": "The IC-9700 is aimed where NB would not transmit"}
        bridge.st["txWarning"] = w
        win.on_state({"txWarning": w})
        self.assertTrue(win.txcard.isVisibleTo(win.rail))
        bridge.st["txWarning"] = {}
        win.on_state({"txWarning": {}})
        self.assertFalse(win.txcard.isVisibleTo(win.rail))


class Strip(WindowCase):
    def test_timings_are_in_the_cpu_tooltip_and_the_report_not_the_strip(self):
        from ohscore.ui import diagnostics
        win, bridge, radio = self.window(mode="usb")
        self.run_for(radio, 2.5)
        texts = [e[0] for e in win.status.entries(bridge.st)]
        self.assertFalse([t for t in texts if "frame" in t or "paint" in t], texts)
        # window.on_tick fills `timings` once a *real* second of ticks has
        # accumulated (bridge.py's dt is wall-clock, for the meters'
        # ballistics) - not once `sim_s` of simulated signal has passed,
        # which the sim can do in far less wall-clock time on a quiet host.
        # `run_for(radio, 2.5)` alone was a bet that 2.5 sim-seconds would
        # not finish before 1 real second had: true on a quiet host, false
        # under load from sibling sessions, so wait for the fill itself.
        self.assertTrue(self.run_for(radio, until=lambda: bool(win.status.timings)),
                         "window.timings_text was never applied to the strip")
        win.status.grab()                                    # painted: the items have their places
        cpu = next((x0, x1) for x0, x1, k in win.status.hits if k == "cpu")
        tip = win.status.tooltip_at((cpu[0] + cpu[1]) / 2)
        self.assertIn("receive thread", tip)
        self.assertIn("frame", tip)
        self.assertIn("workspace switch", tip)
        self.assertEqual(win.status.tooltip_at(2.0), "")
        report = dict(diagnostics.gather(win))["report.txt"].decode()
        self.assertIn("window timings: frame", report)

    def test_the_stream_share_is_still_said(self):
        win, bridge, radio = self.window(mode="usb")
        st = {**bridge.st, "running": True, "rxStreamPct": 37.0}
        self.assertIn(("receiving 37 % of the stream", "warn"), win.status.entries(st))

    def test_rec_is_amber_with_its_dot(self):
        win, bridge, radio = self.window(mode="usb")
        st = {**bridge.st, "recording": True, "recSeconds": 65, "recBytes": 1e6}
        rec = next(e for e in win.status.entries(st) if "REC" in e[0])
        self.assertEqual(rec[1], "rec")
        self.assertTrue(rec[0].startswith("●"))


class ReceiveCard(WindowCase):
    LONG = ("Auto-tune refused: after 12 s, the best fit (+212 Hz) puts the carrier 86 Hz from the voice's edge, "
            "nearer than a voice's carrier ever sits, so the dial was left where it was")

    def test_compact_in_digital_full_in_voice_and_more_is_remembered(self):
        win, bridge, radio = self.window(mode="ft8")
        c = win.rxcard
        self.assertEqual(c.form, "compact")
        for w in (c.s, c.snr, c.vol, c.mute, c.agc):
            self.assertTrue(w.isVisibleTo(c))
        for w in c.extras:
            self.assertFalse(w.isVisibleTo(c))
        self.assertTrue(c.more.isVisibleTo(c))
        QTest.mouseClick(c.more, Qt.MouseButton.LeftButton)
        self.settle()
        self.assertTrue(c.rf.isVisibleTo(c))
        self.assertEqual(win.prefs["workspaces"]["digital"]["expanded"], ["receive"])
        self.press_mode(win, "usb")
        self.assertEqual(c.form, "full")
        self.assertFalse(c.more.isVisibleTo(c))
        self.assertTrue(all(w.isVisibleTo(c) for w in c.extras))
        win.choose_workspace("watch")
        self.assertFalse(c.rf.isVisibleTo(c))                   # Watch was never expanded
        self.press_mode(win, "ft8")
        self.assertTrue(c.rf.isVisibleTo(c))                    # Digital still is
        self.close(win, bridge)
        win, bridge, radio = self.window(mode="ft8")
        self.assertTrue(win.rxcard.rf.isVisibleTo(win.rxcard))   # and after a restart

    def test_a_long_note_wraps_whole_in_full_and_is_one_line_with_a_tooltip_in_compact(self):
        # 1600 x 960, the Full tier: at 1366 x 768 (Compact) every rail
        # card is compact (overhaul section 3), Voice's Receive card too.
        win, bridge, radio = self.window(mode="usb", size=(1600, 960))
        c = win.rxcard
        c._note(self.LONG)
        self.settle()
        n = c.auto_note
        self.assertEqual(n.text(), self.LONG)
        self.assertTrue(n.wordWrap())
        self.assertGreaterEqual(n.height(), n.heightForWidth(n.width()))     # every line has its room
        # The whole card is inside the rail, so scrolling reaches the end of it.
        bottom = n.mapTo(win.rail, n.rect().bottomLeft()).y()
        self.assertLessEqual(bottom, win.rail.height())
        win.choose_workspace("digital")
        self.settle()
        self.assertFalse(n.wordWrap())
        self.assertTrue(n.isVisibleTo(c))
        self.assertTrue(n.text().endswith("…"), n.text())
        self.assertEqual(n.toolTip(), self.LONG)
        self.assertLessEqual(n.sizeHint().height(), n.fontMetrics().height() + 4)
        # One line never widens the rail to the sentence's width.
        self.assertLessEqual(win.split_side.sizes()[1], 400)


class Radio(WindowCase):
    APP = "radio"

    def window(self, size=(1920, 1080), **over):
        from ham_helpers import make_radio as make_ham
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_ham(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(*size)
        win.show()
        self.wins.append((win, bridge))
        self.settle()
        return win, bridge, radio

    def test_radio_has_the_same_workspaces_and_watch_opens_on_cw_activity(self):
        win, bridge, radio = self.window()
        self.press_mode(win, "fm")
        self.assertEqual(win.workspace, "voice")
        self.press_mode(win, "ft8")
        self.assertEqual(win.workspace, "digital")
        self.key(win, Qt.Key.Key_W)
        self.key(win, Qt.Key.Key_W)
        self.assertEqual(win.workspace, "watch")
        self.assertEqual(win.views.value, "cwskim")
        from ohsradio.ui.widgets import BandBar
        bars = win.findChildren(BandBar)
        self.assertTrue(bars and all(b.isVisible() for b in bars))     # the band bar stays in Watch


if __name__ == "__main__":
    unittest.main()
