import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""Over the beacon and LEILA in NB's window (ohsnb/ui/opview.py, the scope's
alerts): the watch's list as the Band view's table shows it, the same
events as amber and red columns on the wide scope, a click on a row or a
caption tuning the receiver there - the dial only, never a key-up - and
the evidence button refusing with the reason while capture is off. The
list is put on the engine's "overpower" feed by hand (the watch itself is
off), so every entry is known; tests/test_overpower_radio.py proves the
watch makes such lists."""
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

HOT = 10_489_812_400.0
SIREN = 10_489_541_400.0


def events(now):
    return [
        {"kind": "overpower", "id": 1, "start": now - 12, "end": now, "active": True, "freq": HOT,
         "lo": HOT - 30.0, "hi": HOT + 30.0, "width": 60.0, "excessDb": 4.2, "leila": False, "siren": None,
         "call": None},
        {"kind": "leila", "id": 2, "start": now - 3, "end": now, "active": True, "freq": SIREN,
         "lo": SIREN - 103.0, "hi": SIREN + 103.0, "width": 206.0, "levelDb": 2.0, "leila": True, "on": None,
         "call": "G4XYZ"},
        {"kind": "overpower", "id": 3, "start": now - 900, "end": now - 880, "active": False,
         "freq": 10_489_700_000.0, "lo": 10_489_699_000.0, "hi": 10_489_701_000.0, "width": 2000.0,
         "excessDb": 6.0, "leila": False, "siren": None, "call": None},
    ]


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class OverTheBeacon(WindowCase):
    def on_air(self):
        win, bridge, radio = self.window(opWatch=False, skimDecode=False, beaconMode="hold",
                                         vfo=10_489_700_000.0, mode="usb")
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        radio._publish("overpower", {"t": time.time(), "events": events(time.time()), "beacon": "ok"})
        self.run_for(radio, until=lambda: len(win.op_store.events) == 3, timeout=10)
        win.show_view("skim")
        self.app.processEvents()
        return win, bridge, radio

    def test_the_table_says_what_and_where(self):
        win, _bridge, _radio = self.on_air()
        t = win.op_panel.table
        rows = [[t.item(r, c).text() for c in range(t.columnCount())] for r in range(t.rowCount())]
        self.assertEqual([r[1] for r in rows], ["10489.812 400", "10489.541 400", "10489.700 000"])
        self.assertEqual(rows[0][2], "+4.2 dB over beacon")
        self.assertEqual(rows[1][2], "LEILA? siren-like")
        self.assertEqual(rows[1][3], "G4XYZ")

    def test_the_wide_scope_marks_what_is_happening_now(self):
        win, _bridge, _radio = self.on_air()
        alerts = {a["text"]: a for a in win.wide.alerts}
        # The one that ended 15 minutes ago is in the table, not on the scope.
        self.assertEqual(set(alerts), {"+4 dB over beacon", "LEILA?"})
        self.assertEqual(alerts["LEILA?"]["colour"], "tx")
        self.assertEqual(alerts["+4 dB over beacon"]["colour"], "warn")

    def test_a_click_on_a_row_tunes_the_receiver_only(self):
        win, _bridge, radio = self.on_air()
        t = win.op_panel.table
        rect = t.visualItemRect(t.item(1, 1))
        QTest.mouseClick(t.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        s = radio.state()
        self.assertEqual((s["mode"], s["vfo"]), ("usb", SIREN - 1000.0))       # the siren at 1 kHz of audio
        self.assertFalse(s["keyed"])

    def test_a_click_on_a_caption_tunes_there(self):
        win, _bridge, radio = self.on_air()
        sc = win.wide
        sc._set_wide_view(HOT - 10_000.0, HOT + 10_000.0)
        self.app.processEvents()
        box = next(b for a, _c, b in sc.alert_layout() if a["text"] == "+4 dB over beacon")
        QTest.mouseClick(sc, Qt.MouseButton.LeftButton, pos=QPoint(int(box.center().x()), int(box.center().y())))
        self.assertEqual(radio.state()["vfo"], HOT - 1000.0)

    def test_saving_evidence_with_capture_off_says_why(self):
        win, bridge, _radio = self.on_air()
        said = []
        bridge.toast.connect(said.append)
        win.op_panel._save()
        self.assertTrue(said and "watch is off" in said[-1]["text"])


if __name__ == "__main__":
    unittest.main()
