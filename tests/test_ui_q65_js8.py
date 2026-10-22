"""Q65 and JS8 in the window (the UI overhaul's WP3, docs/ui-overhaul-2026-10.md
section 5.1), and the simulator's Q65 and JS8 stations.

Until 17/10/2026 both modes fell through to the microphone panel (the Mac
test's finding 21) and AM showed a microphone it could never use (finding
26). These drive the window on the simulator as an operator would and read
what it shows and what the engine was asked; the end-to-end cases decode
the simulator's own stations through the engine's decoders.

Nothing here keys the simulator: where the Q65 sequencer must queue an
over, the panel's call to the engine is recorded instead of made."""
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
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover - the engine's tests still run without PyQt6
    HAVE_QT = False

from helpers import make_radio, run_sim, sim_seconds

Q65_DL, JS8_DL = 10_489_545_000.0, 10_489_548_000.0


def js8_frame(slot, df, text, first, last, kind="data", call="", to=""):
    ev = {"mode": "js8", "slot": float(slot), "snr": -8, "dt": 0.2, "df": df, "text": text, "kind": kind,
          "first": first, "last": last}
    if call:
        ev["call"] = call
    if to:
        ev["to"] = to
    return ev


class JoinFrames(unittest.TestCase):
    """JS8's frames become messages as JS8Call joins them."""

    def setUp(self):
        from ohscore.ui.panels.js8 import join_frame
        self.join = join_frame
        self.open = []

    def test_three_frames_on_one_offset_make_one_message(self):
        t = 1_700_000_100.0
        m, new = self.join(self.open, js8_frame(t, 1450, "DL1ABC: G4XYZ  ", True, False, "directed", "DL1ABC",
                                                "G4XYZ"), 15.0)
        self.assertTrue(new)
        # Someone else in between, on another offset, is a message of its own.
        other, new2 = self.join(self.open, js8_frame(t + 15, 1000, "G4XYZ: @HB HEARTBEAT IO91 ", True, True,
                                                     "heartbeat", "G4XYZ"), 15.0)
        self.assertTrue(new2)
        m2, new3 = self.join(self.open, js8_frame(t + 15, 1452, "HELLO FROM BERLIN TNX ", False, False), 15.0)
        m3, new4 = self.join(self.open, js8_frame(t + 30, 1449, "FOR THE QSO", False, True), 15.0)
        self.assertIs(m2, m)
        self.assertIs(m3, m)
        self.assertFalse(new3 or new4)
        self.assertEqual(m.text(), "G4XYZ HELLO FROM BERLIN TNX FOR THE QSO")
        self.assertEqual((m.call, m.to, m.slot), ("DL1ABC", "G4XYZ", t))
        self.assertTrue(other.heartbeat())
        self.assertFalse(m.heartbeat())
        self.assertEqual(self.open, [])            # both finished

    def test_a_message_heard_from_its_middle_says_so(self):
        t = 1_700_000_100.0
        m, _ = self.join(self.open, js8_frame(t, 1450, "HELLO FROM BERLIN TNX", False, False), 15.0)
        self.assertEqual(m.text(), "… HELLO FROM BERLIN TNX …")
        # Its last frame never came: the next one on that offset a minute
        # later is another message.
        n, new = self.join(self.open, js8_frame(t + 60, 1450, "MORE", False, True), 15.0)
        self.assertTrue(new)
        self.assertIsNot(n, m)

    def test_a_first_frame_starts_a_new_message_where_one_was_unfinished(self):
        t = 1_700_000_100.0
        a, _ = self.join(self.open, js8_frame(t, 1450, "DL1ABC: G4XYZ ", True, False, "directed", "DL1ABC"), 15.0)
        b, new = self.join(self.open, js8_frame(t + 15, 1450, "DL1ABC: G4XYZ ", True, False, "directed",
                                                "DL1ABC"), 15.0)
        self.assertTrue(new)
        self.assertIsNot(a, b)
        self.assertEqual(a.text(), "G4XYZ …")
        self.assertEqual(self.open, [b])

    def test_frames_as_the_engine_gives_them_keep_their_spaces(self):
        # The engine trims each frame's text; the raw frame it also carries
        # says where the spaces were.
        from ohscore.modes import js8
        lb = js8._OHSDIGI_JS8
        if lb is None or not hasattr(lb, "js8_frames"):
            self.skipTest("ohsdigi with JS8 is not built here")
        t = 1_700_000_100.0
        frames = lb.js8_frames("G4XYZ HELLO FROM BERLIN TNX FOR THE QSO", "DL1ABC", "JO31")
        self.assertGreater(len(frames), 2)
        for i, (frame, i3) in enumerate(frames):
            u = lb.js8_unpack(frame, i3)
            ev = js8_frame(t + 15 * i, 1450, u["text"].rstrip(), u["first"], u["last"], u["kind"],
                           u.get("from") or "", u.get("to") or "")
            ev.update(frame=frame, i3bit=i3)
            m, _ = self.join(self.open, ev, 15.0)
        self.assertEqual(m.text(), "G4XYZ HELLO FROM BERLIN TNX FOR THE QSO")

    def test_cq_is_not_a_heartbeat(self):
        m, _ = self.join(self.open, js8_frame(1_700_000_100.0, 1800, "SV1QO: @ALLCALL CQ CQ CQ  ", True, True,
                                              "heartbeat", "SV1QO"), 15.0)
        self.assertFalse(m.heartbeat())
        self.assertEqual(m.text(), "@ALLCALL CQ CQ CQ")


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Q65AndJs8Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
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

    def window(self, **over):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp, audio_source=lambda n: __import__("numpy").full(n, 0.2, "float32"), **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def run_for(self, radio, sim_s=0.0, until=None, timeout=10.0):
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

    def slot_window(self, mode, dial, **over):
        from ohscore.ui.panels.ft8 import Ft8Panel
        win, bridge, radio = self.window(mode=mode, vfo=dial, callsign="GM4BRI", locator="IO75RL", **over)
        self.assertTrue(self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel)))
        self.app.processEvents()
        return win, bridge, radio, win.panel

    # ------------------------------------------------------------------ Q65
    def test_q65_has_the_slot_panel_with_a_60_s_ring(self):
        win, bridge, radio, p = self.slot_window("q65", Q65_DL)
        self.assertTrue(p.qso_card.isVisible())
        self.assertTrue(p.act_card.isVisible())
        self.assertEqual(p.ring.mode, "q65")
        self.assertEqual(p.period_note.text(), "Q65-60A · 60 s periods")
        # With Enable TX on in the odd periods, the next over is the next
        # odd minute, not the next odd quarter-minute.
        p.period.set_value("1")
        p.set_tx_enabled(True)
        with mock.patch("ohscore.ui.panels.ft8.time.time", return_value=1_700_000_040.0 + 20.0):
            self.assertEqual(p.next_over_at(), 1_700_000_100.0)
        p.set_tx_enabled(False)
        # The period note is Q65's alone.
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: p.ring.mode == "ft8")
        self.assertEqual(p.period_note.text(), "")

    def test_q65_decodes_fill_the_band_activity_and_a_click_answers(self):
        win, bridge, radio, p = self.slot_window("q65", Q65_DL)
        rows = p.table.rowCount()
        slot = 1_700_000_040.0                      # a 60 s period start (even)
        p.on_event({"mode": "q65", "slot": slot, "text": "CQ G4XYZ IO91", "call": "G4XYZ", "grid": "IO91",
                    "snr": -14, "dt": 0.1, "df": 1210})
        self.assertEqual(p.table.rowCount(), rows + 2)    # the period's separator and the decode
        self.assertEqual(p.table.item(rows + 1, 5).text(), "CQ G4XYZ IO91")
        with mock.patch.object(p.bridge, "send", return_value=True):
            p._row_clicked(rows + 1, 5)
        self.assertEqual(p.dx.text(), "G4XYZ")
        self.assertEqual(radio.state()["dxCall"], "G4XYZ")
        # Answering a CQ in an even 60 s period: we go in the odd ones.
        self.assertEqual(p.period.value, "1")
        self.assertTrue(p.tx_enabled)
        self.assertEqual(p.prefs["ft8RxOffset"], 1210)
        p.set_tx_enabled(False)

    def test_q65_queues_the_next_over_after_the_55_s_decode(self):
        win, bridge, radio, p = self.slot_window("q65", Q65_DL)
        p.seq.answer("G4XYZ", "IO91", -14)
        p.period.set_value("1")
        p.set_tx_enabled(True)
        p.fresh = ""
        base = 1_700_000_040.0                  # an even period: theirs; ours (odd) starts at base + 60
        sent = []

        def send(mode, **msg):
            sent.append((mode, msg))
            return True

        def at(t):
            with mock.patch("ohscore.ui.panels.ft8.time.time", return_value=t), \
                    mock.patch.object(p.bridge, "send", side_effect=send):
                p.tick(0.03)

        at(base + 3.0)                          # FT8 would queue here; Q65's decode is a minute away
        self.assertEqual(sent, [])
        at(base + 50.0)
        self.assertEqual(sent, [])
        at(base + 56.7)                         # the decode is in: queue for our period
        self.assertEqual(len(sent), 1)
        mode, msg = sent[0]
        self.assertEqual(mode, "q65")
        self.assertEqual(msg["text"], "G4XYZ GM4BRI IO75")
        self.assertEqual(msg["period"], "odd")
        self.assertEqual(p.sent_slot, int((base + 60.0) // 60))
        at(base + 57.5)                         # once per period
        self.assertEqual(len(sent), 1)
        # The ARMED countdown names our period's start.
        with mock.patch("ohscore.ui.panels.ft8.time.time", return_value=base + 57.5):
            self.assertEqual(p.next_over_at(), base + 60.0)
        p.set_tx_enabled(False)

    def test_q65_zoom_marks_are_108_hz_wide_and_a_click_moves_them(self):
        # The zoom at its narrowest, centred over the offsets: 108 Hz is then
        # a band of pixels, not two.
        win, bridge, radio, p = self.slot_window("q65", Q65_DL, zoomSpanHz=2000.0, zoomPan=1000.0)
        p.set_offsets(rx=1200, tx=1600)
        self.assertEqual(win.zoom.audio_offsets, {"rx": 1200.0, "tx": 1600.0})
        win.offset_click(900, is_tx=False)
        self.assertEqual(p.prefs["ft8RxOffset"], 900)
        # The RX band, as painted: 80 Hz above the offset is inside Q65's
        # 108 Hz and outside FT8's 50.
        inside, outside = self.band_tint(win, 900 + 80), self.band_tint(win, 900 + 200)
        self.assertGreater(inside, outside + 8)
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: p.ring.mode == "ft8")
        self.app.processEvents()
        self.assertLess(abs(self.band_tint(win, 900 + 80) - outside), 8)

    def band_tint(self, win, off):
        """How green the zoom's spectrum area is `off` Hz above the dial (the
        RX band's fill), as the green channel minus the red, averaged down
        a column."""
        z = win.zoom
        z.repaint()
        img = z.grab().toImage()
        dial = float(radio_st(win)["rxDial"] or radio_st(win)["vfo"])
        x = int(round(z.fmap.x(dial + off)))
        r = z.r_spec
        vals = []
        # Below the RX/TX flags, which sit at the top of the spectrum.
        for y in range(int(r.y() + 40), int(r.bottom() - 4), 3):
            c = img.pixelColor(x, y)
            vals.append(c.green() - c.red())
        return sum(vals) / len(vals)

    def test_q65_decodes_label_the_waterfalls_mid_period(self):
        win, bridge, radio, p = self.slot_window("q65", Q65_DL)
        slot = 1_700_000_040.0
        win.on_event({"mode": "q65", "slot": slot, "text": "CQ G4XYZ IO91", "call": "G4XYZ", "snr": -14,
                      "dt": 0.1, "df": 1210, "dial": Q65_DL})
        zl = [lb for lb in win.zoom.labels if lb["text"] == "CQ G4XYZ IO91"]
        wl = [lb for lb in win.wide.labels if lb["text"] == "G4XYZ"]
        self.assertEqual(len(zl), 1)
        self.assertEqual(len(wl), 1)
        self.assertEqual(zl[0]["f"], Q65_DL + 1210)
        self.assertEqual(zl[0]["t"], slot + 25.0)     # in the middle of its ~49 s on the waterfall

    def test_slot_mode_clicks_round_to_the_500_hz_channels(self):
        from ohscore.ui.tuning import click_to_dial
        self.assertEqual(click_to_dial("q65", 10_489_546_620.0, {}), 10_489_545_000.0)
        self.assertEqual(click_to_dial("js8", 10_489_549_400.0, {}), 10_489_548_000.0)

    # ------------------------------------------------------------------ JS8
    def test_js8_shows_its_list_and_send_card_in_the_slot_panel(self):
        from ohscore.ui.panels.js8 import Js8Panel
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        self.assertIsInstance(j, Js8Panel)
        self.assertTrue(j.isVisible())
        self.assertTrue(j.send_card.isVisible())
        self.assertFalse(p.act_card.isVisible())
        self.assertFalse(p.qso_card.isVisible())
        # Typed messages, not FT8's QSO sequence: no Tx rows.
        self.assertFalse(hasattr(j, "rows") or hasattr(j, "seq"))
        # The FT8 sequencer behind it never sends while JS8 shows.
        p.tx_enabled = True
        with mock.patch.object(p.bridge, "send") as send:
            p.fresh = "operator"
            p.tick(0.03)
        send.assert_not_called()
        p.tx_enabled = False

    def need_js8_encoder(self):
        # Sending needs ohsdigi's JS8 encoder (ohscore/modes/js8.py
        # CAN_ENCODE); JS8Call's js8 only decodes. A tree without the built
        # ohsdigi (any development checkout, and release.sh's suite, which
        # runs before build-ohsdigi.sh) refuses every queue, so these tests
        # skip there as the frame test above does rather than fail on a
        # refusal that is the panel working as meant.
        from ohscore.modes import js8
        if not js8.CAN_ENCODE:
            self.skipTest("ohsdigi with the JS8 encoder is not built here")

    def js8_sender(self, p):
        """Run the JS8 panel's tick at chosen times with its sends recorded."""
        sent = []

        def send(mode, **msg):
            sent.append((mode, msg))
            return True

        def at(t):
            with mock.patch("ohscore.ui.panels.js8.time.time", return_value=t), \
                    mock.patch.object(p.bridge, "send", side_effect=send):
                p.tick(0.03)
        return sent, at

    def test_js8_sends_a_message_a_frame_per_period(self):
        self.need_js8_encoder()
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        sent, at = self.js8_sender(p)
        text = "G4XYZ HELLO FROM BERLIN TNX FOR THE QSO"
        j.entry.setText(text.lower())
        QTest.keyClick(j.entry, Qt.Key.Key_Return)
        self.assertEqual(j.pending, text)
        self.assertGreater(j.nframes, 2)
        self.assertTrue(j.tx_enabled and j.enable.on)
        base = 1_700_000_100.0 - (1_700_000_100.0 % 15.0)
        at(base + 5.0)                          # too late for this period, too early to queue the next
        self.assertEqual(sent, [])
        for i in range(j.nframes):
            at(base + 15.0 * i + 13.6)          # just after the frame before has ended
            self.assertEqual(len(sent), i + 1)
            mode, msg = sent[-1]
            self.assertEqual((mode, msg["text"], msg["part"]), ("js8", text, i))
            self.assertEqual(msg["freq"], p.prefs["ft8TxOffset"])
            at(base + 15.0 * i + 14.0)          # once per period
            self.assertEqual(len(sent), i + 1)
        # The last frame queued: Enable TX goes off, as FT8's does after 73.
        self.assertFalse(j.tx_enabled)
        self.assertIn("Sent", j.tx_status.text())

    def test_js8_enable_tx_halt_and_escape_stop_it(self):
        self.need_js8_encoder()
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        sent, at = self.js8_sender(p)
        QTest.mouseClick(j.cq_btn, Qt.MouseButton.LeftButton)
        self.assertEqual((j.pending, j.nframes), ("CQ CQ CQ", 1))
        self.assertTrue(j.tx_enabled)
        # The ARMED countdown names the next period.
        with mock.patch("ohscore.ui.panels.js8.time.time", return_value=1_700_000_105.0):
            self.assertEqual(win.panel.next_over_at(), 1_700_000_115.0)
        # Enable TX off while a frame is on the air ends it.
        with mock.patch.object(p.bridge, "halt") as halt:
            bridge.st["keyed"] = True
            QTest.mouseClick(j.enable, Qt.MouseButton.LeftButton)
            bridge.st["keyed"] = False
        halt.assert_called_once()
        self.assertFalse(j.tx_enabled)
        # Halt TX: nothing more of it goes.
        QTest.mouseClick(j.hb_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(j.pending, "@HB HEARTBEAT IO75")
        QTest.mouseClick(j.halt, Qt.MouseButton.LeftButton)
        self.assertEqual((j.pending, j.tx_enabled), ("", False))
        at(1_700_000_100.0 + 13.6)
        self.assertEqual(sent, [])
        # Escape, from the window, likewise.
        j.queue("CQ CQ CQ")
        win.unkey_all()
        self.assertEqual((j.pending, j.tx_enabled), ("", False))
        # A refused over (here: no callsign) switches Enable TX off and says why.
        bridge.set(callsign="")
        self.run_for(radio, until=lambda: not bridge.st.get("callsign"))
        self.assertFalse(j.queue("CQ CQ CQ"))
        self.assertFalse(j.tx_enabled)

    def test_js8_sends_at_the_speed_picked_and_lists_each_speed(self):
        self.need_js8_encoder()
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        sent, at = self.js8_sender(p)
        self.assertEqual(j.speed_pick.value, "normal")         # the QO-100 preset's
        j.set_speed("turbo")
        j.queue("CQ CQ CQ")
        # Not while a message is going: it was counted at Turbo.
        self.assertFalse(j.speed_pick.isEnabled())
        j.set_speed("slow")
        self.assertEqual(j.speed, "turbo")
        base = 1_700_000_040.0                  # a whole minute: a Turbo period starts here
        at(base + 2.0)                          # 6 s periods: too late for this one...
        self.assertEqual(sent, [])
        at(base + 4.5)                          # ...and Turbo's frame (to 4.05 s) is over: queue the next
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["speed"], "turbo")
        self.assertTrue(j.speed_pick.isEnabled())               # the last frame is queued
        # Every speed is listed, each frame joined only with its own speed's.
        win.on_event(dict(js8_frame(base, 1900, "OH8ZZ: @ALLCALL CQ CQ CQ  ", True, True, "heartbeat", "OH8ZZ"),
                          speed="turbo"))
        self.assertEqual(j.table.item(j.table.rowCount() - 1, 4).text(), "Turbo")

    def test_js8_reply_starts_a_message_to_the_station_picked(self):
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        win.on_event(js8_frame(1_700_000_100.0, 1820, "SV1QO: @ALLCALL CQ CQ CQ  ", True, True, "heartbeat",
                               "SV1QO"))
        j.table.selectRow(0)
        QTest.mouseClick(j.reply_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(j.entry.text(), "SV1QO ")

    def test_js8_messages_are_one_row_each_and_filter(self):
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        j = p.js8
        t = 1_700_000_100.0
        for ev in (js8_frame(t, 1450, "DL1ABC: GM4BRI  ", True, False, "directed", "DL1ABC", "GM4BRI"),
                   js8_frame(t, 1000, "G4XYZ: @HB HEARTBEAT IO91 ", True, True, "heartbeat", "G4XYZ"),
                   js8_frame(t + 15, 1451, "HELLO FROM BERLIN TNX ", False, False),
                   js8_frame(t + 30, 1450, "FOR THE QSO", False, True),
                   js8_frame(t + 30, 1800, "SV1QO: @ALLCALL CQ CQ CQ  ", True, True, "heartbeat", "SV1QO")):
            win.on_event(ev)                    # as the engine's events reach it
        self.assertEqual(j.table.rowCount(), 3)
        texts = [j.table.item(r, j.TEXT).text() for r in range(3)]
        self.assertEqual(texts, ["GM4BRI HELLO FROM BERLIN TNX FOR THE QSO", "@HB HEARTBEAT IO91",
                                 "@ALLCALL CQ CQ CQ"])
        self.assertEqual([j.table.item(r, j.FROM).text() for r in range(3)], ["DL1ABC", "G4XYZ", "SV1QO"])
        self.assertEqual({j.table.item(r, 4).text() for r in range(3)}, {"Normal"})
        self.assertEqual(j.table.item(0, 0).text(), time.strftime("%H:%M:%S", time.gmtime(t)))
        # The FT8 list was not given JS8's frames.
        self.assertFalse(any((p.table.item(r, 5) or None) and "BERLIN" in p.table.item(r, 5).text()
                             for r in range(p.table.rowCount())))
        shown = lambda: [r for r in range(3) if not j.table.isRowHidden(r)]   # noqa: E731
        QTest.mouseClick(j.show_hb, Qt.MouseButton.LeftButton)
        self.assertEqual(shown(), [0, 2])           # heartbeats hidden, the CQ kept
        QTest.mouseClick(j.only_me, Qt.MouseButton.LeftButton)
        self.assertEqual(shown(), [0])              # only the message to GM4BRI
        QTest.mouseClick(j.only_me, Qt.MouseButton.LeftButton)
        QTest.mouseClick(j.show_hb, Qt.MouseButton.LeftButton)
        self.assertEqual(shown(), [0, 1, 2])

    def test_js8_zoom_marks_and_clicks(self):
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        p.set_offsets(rx=1200, tx=1600)
        self.assertEqual(win.zoom.audio_offsets, {"rx": 1200.0, "tx": 1600.0})
        win.offset_click(1400, is_tx=True)          # Shift + click moves TX
        self.assertEqual(win.zoom.audio_offsets, {"rx": 1200.0, "tx": 1400.0})
        win.offset_click(1450, is_tx=False)
        self.assertEqual(win.zoom.audio_offsets["rx"], 1450.0)
        # A click on a message puts the RX mark on it.
        win.on_event(js8_frame(1_700_000_100.0, 1820, "SV1QO: @ALLCALL CQ CQ CQ  ", True, True, "heartbeat",
                               "SV1QO"))
        p.js8._row_clicked(p.js8.table.rowCount() - 1, 5)
        self.assertEqual(win.zoom.audio_offsets["rx"], 1820.0)
        # And JS8's frames label the waterfalls as FT8's do.
        self.assertTrue(any(lb["text"].startswith("SV1QO:") for lb in win.zoom.labels))

    def test_enable_tx_does_not_carry_into_another_mode(self):
        win, bridge, radio, p = self.slot_window("ft8", 10_489_540_000.0)
        # The event loop runs the panel's sequencer below: record its overs
        # rather than key the simulator.
        send = mock.patch.object(p.bridge, "send", return_value=True)
        send.start()
        self.addCleanup(send.stop)
        p.set_tx_enabled(True)
        # An FT8 over of ours queued as the mode changes is FT8's audio: halted.
        with mock.patch.object(p.bridge, "halt") as halt:
            bridge.st["keyed"] = True
            bridge.set(mode="js8")
            self.run_for(radio, until=lambda: p.js8 is not None and p.js8.isVisible())
            bridge.st["keyed"] = False
        halt.assert_called()
        self.assertFalse(p.tx_enabled)
        bridge.set(mode="q65")
        self.run_for(radio, until=lambda: p.act_card.isVisible())
        self.assertFalse(p.tx_enabled)
        p.set_tx_enabled(True)                      # Q65 transmits: Enable TX works there
        self.assertTrue(p.tx_enabled)
        bridge.set(mode="ft8")
        self.run_for(radio, until=lambda: p.ring.mode == "ft8")
        self.assertFalse(p.tx_enabled)

    def test_js8_rows_survive_a_theme_change(self):
        win, bridge, radio, p = self.slot_window("js8", JS8_DL)
        win.on_event(js8_frame(1_700_000_100.0, 1000, "G4XYZ: @HB HEARTBEAT IO91 ", True, True, "heartbeat",
                               "G4XYZ"))
        win.set_theme("light" if win.prefs["theme"] == "dark" else "dark")
        self.run_for(radio, until=lambda: win.panels.get("slot") is not p and win.panels["slot"].js8 is not None
                     and win.panels["slot"].js8.table.rowCount() == 1)
        self.assertEqual(win.panels["slot"].js8.table.item(0, 6).text(), "@HB HEARTBEAT IO91")

    # ------------------------------------------------------------------ AM
    def test_am_shows_no_microphone(self):
        from ohscore.ui.panels.voice import VoicePanel
        win, bridge, radio = self.window(mode="am", vfo=10_489_750_000.0)
        self.assertTrue(self.run_for(radio, until=lambda: isinstance(win.panel, VoicePanel)))
        self.app.processEvents()
        self.assertFalse(win.panel.mic.isVisible())
        self.assertFalse(win.panel.keyer.isVisible())
        self.assertTrue(win.panel.am_note.isVisible())
        bridge.set(mode="usb")
        self.run_for(radio, until=lambda: win.panel.mic.isVisible())
        self.assertTrue(win.panel.mic.isVisible())


def radio_st(win):
    return win.bridge.st


class DigiOnlySim:
    """The simulator's band cut to its beacons and the Q65 and JS8 stations
    (ohsnb/devices/digisim.py), so a minute and more of it runs quickly."""

    @staticmethod
    def device():
        from ohsnb.devices import digisim
        from ohsnb.devices.sim import SimDevice

        class DigiOnly(SimDevice):
            def open(self):
                super().open()
                self.stations = [s for s in self.stations
                                 if isinstance(s, digisim.SlotActivity) or "beacon" in s.name]
        return DigiOnly


class SimulatorStations(unittest.TestCase):
    """The simulator's Q65 and JS8 stations, decoded by the engine's own
    decoders, so the panels can be seen and tested with no dish."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def decode(self, mode, dial, seconds):
        r = make_radio(self.tmp, device=DigiOnlySim.device(), simSignals=True, mode=mode, vfo=dial)
        ev = r.subscribe("events", 500)
        r.start()
        try:
            info = r.state()["modes"][mode]
            if not info["decode"]:
                self.skipTest(f"{mode} decoder not available: {info['missing']}")
            names = [s.name for s in r.dev.stations]
            if mode.upper() not in names:
                self.skipTest(f"no simulated {mode} station: its encoder is not available here")
            got = run_sim(r, seconds, [ev], timeout=300)["events"]
            # The last period's decode runs on a worker as the run ends.
            t0 = time.monotonic()
            while time.monotonic() - t0 < 10 and not any(e.get("mode") == mode and e.get("text") for e in got):
                time.sleep(0.2)
                r.heartbeat()
                got += ev.drain()
            return [e for e in got if e.get("mode") == mode and e.get("text")]
        finally:
            r.stop()

    def test_the_q65_station_decodes_within_two_periods(self):
        from ohsnb.devices import digisim
        got = self.decode("q65", digisim.Q65_DL, 125.0)
        sent = {text for period in digisim.Q65_SCRIPT for _off, _db, text in period}
        texts = {e["text"] for e in got}
        self.assertTrue(texts & sent, texts)
        self.assertLessEqual(texts, sent)          # nothing decoded that was not sent
        for e in got:
            self.assertEqual(e["slot"] % 60.0, 0.0)

    def test_the_js8_station_decodes_into_messages(self):
        from ohscore.ui.panels.js8 import join_frame
        from ohsnb.devices import digisim
        # Wherever in its 9-period cycle the run starts, 12 periods hold
        # the three-frame message whole.
        got = self.decode("js8", digisim.JS8_DL, 12 * 15.0 + 5.0)
        open_msgs, msgs = [], []
        for e in sorted(got, key=lambda e: e["slot"]):
            m, new = join_frame(open_msgs, e, 15.0)
            if new:
                msgs.append(m)
        whole = {m.text() for m in msgs if m.started and m.done}
        self.assertIn("G4XYZ HELLO FROM BERLIN TNX FOR THE QSO", whole)
        self.assertTrue(any(m.heartbeat() for m in msgs), whole)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class RadioJs8(unittest.TestCase):
    """OpenHamShack Radio has JS8 (no Q65): the same panel."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.wins = []

    def tearDown(self):
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def window(self, **over):
        from ham_helpers import make_radio as make_ham
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_ham(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def settle(self, until, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not until():
            self.app.processEvents()
            time.sleep(0.01)

    def test_js8_shows_the_js8_panel(self):
        from ohscore.ui.panels.js8 import Js8Panel
        win, bridge, radio = self.window(mode="js8")
        self.settle(lambda: getattr(win.panel, "js8", None) is not None and win.panel.js8.isVisible())
        self.assertIsInstance(win.panel.js8, Js8Panel)
        self.assertTrue(win.panel.js8.isVisible())
        self.assertFalse(win.panel.qso_card.isVisible())

    def test_radio_am_keeps_its_microphone(self):
        # Radio's AM transmits (ohsradio/radio.py), unlike NB's.
        from ohscore.ui.panels.voice import VoicePanel
        win, bridge, radio = self.window(mode="am")
        self.settle(lambda: isinstance(win.panel, VoicePanel) and win.panel.isVisible())
        self.assertTrue(win.panel.mic.isVisible())


if __name__ == "__main__":
    unittest.main()
