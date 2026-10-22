import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The band skimmer in NB's window (ohsnb/ui/skimview.py, the scope's band
marks): its list as the Band view shows it, a click on a row tuning there
in the signal's mode, the same signals marked on the wide scope - a click
on a mark tunes too - and the marks turned off. The list is put on the
engine's "skim" feed by hand (the skimmer itself is off), so every entry is
known; tests/test_skimmer.py proves the skimmer makes such lists."""
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

SSB = 10_489_773_700.0


def entry(**kw):
    e = {"id": 1, "f": 0.0, "lo": 0.0, "hi": 0.0, "kind": "signal", "label": "", "mode": "usb", "dial": None,
         "exact": False, "measured": "", "why": "", "snr": 12.0, "first": time.time() - 30, "last": time.time(),
         "active": True, "looks": 1, "count": 1}
    e.update(kw)
    return e


LIST = [
    entry(id=1, f=10_489_521_000.0, lo=10_489_520_975.0, hi=10_489_521_025.0, kind="cw", label="CW", mode="cw"),
    entry(id=-10489540, f=10_489_540_000.0, lo=10_489_540_150.0, hi=10_489_543_100.0, kind="digital", label="FT8",
          mode="ft8", dial=10_489_540_000.0, exact=True, count=7, calls=["G4XYZ", "DL1ABC"]),
    entry(id=3, f=SSB, lo=SSB + 300.0, hi=SSB + 2_700.0, kind="ssb", label="SSB", dial=SSB, exact=True,
          measured="twice"),
    entry(id=4, f=10_489_800_000.0, lo=10_489_800_300.0, hi=10_489_802_600.0, kind="ssb", label="SSB?",
          dial=10_489_800_000.0, measured="", why="no voice heard: 3 of 180 frames had pitch harmonics"),
]


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class BandView(WindowCase):
    def on_air(self):
        win, bridge, radio = self.window(skimDecode=False, beaconMode="hold", vfo=10_489_700_000.0)
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        radio._publish("skim", {"t": time.time(), "entries": [dict(e) for e in LIST]})
        self.run_for(radio, until=lambda: len(win.skim_store.entries) == len(LIST), timeout=10)
        win.show_view("skim")
        self.app.processEvents()
        return win, bridge, radio

    def test_the_list_says_what_each_signal_is(self):
        win, _bridge, _radio = self.on_air()
        t = win.skim_view.table
        rows = [[t.item(r, c).text() for c in range(t.columnCount())] for r in range(t.rowCount())]
        self.assertEqual([r[1] for r in rows], ["CW", "FT8", "SSB", "SSB?"])
        self.assertEqual(rows[2][0], "10489.773 700")          # a confirmed dial, to the hertz
        self.assertEqual(rows[3][0], "~10489.800")              # a guess says it is one
        self.assertEqual(rows[1][5], "7 signals: G4XYZ DL1ABC")
        self.assertIn("not measured yet", rows[3][5])
        self.assertIn("no voice heard", rows[3][5])
        # The filter: voices only.
        win.skim_view.filter.picked.emit("voice")
        self.assertEqual([t.item(r, 1).text() for r in range(t.rowCount())], ["SSB", "SSB?"])

    def click_row(self, win, label):
        t = win.skim_view.table
        r = next(i for i in range(t.rowCount()) if t.item(i, 1).text() == label)
        rect = t.visualItemRect(t.item(r, 1))
        QTest.mouseClick(t.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    def test_a_click_tunes_there_in_its_mode(self):
        win, _bridge, radio = self.on_air()
        self.click_row(win, "SSB")
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("usb", SSB))
        self.click_row(win, "FT8")
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("ft8", 10_489_540_000.0))
        self.click_row(win, "CW")
        s = radio.state()
        self.assertEqual(s["mode"], "cw")
        self.assertEqual(s["vfo"], 10_489_521_000.0 - s["cwPitch"])     # the tone lands on the pitch

    def test_a_voice_not_yet_measured_is_auto_tuned(self):
        win, bridge, radio = self.on_air()
        self.click_row(win, "SSB?")
        self.assertEqual(radio.state()["mode"], "usb")
        self.assertEqual(radio.state()["autoBusy"], "tune")      # listening there, as a right-click would
        self.assertLess(abs(radio.state()["vfo"] - 10_489_800_000.0), 200.0)

    def test_marks_on_the_wide_scope_and_a_click_on_one_tunes(self):
        win, _bridge, radio = self.on_air()
        sc = win.wide
        texts = sorted(m["text"] for m in sc.band_marks)
        self.assertEqual(texts, sorted(["CW", "FT8 ×7", "SSB", "SSB?"]))
        ssb = next(m for m in sc.band_marks if m["text"] == "SSB")
        self.assertEqual(ssb["dial"], SSB)
        sc._set_wide_view(10_489_760_000.0, 10_489_790_000.0)      # zoomed in so the mark is wide enough
        self.app.processEvents()
        lay = {m["text"]: (bar, box) for m, bar, box in sc.band_mark_layout()}
        bar, box = lay["SSB"]
        at = (box or bar).center()
        QTest.mouseClick(sc, Qt.MouseButton.LeftButton, pos=QPoint(int(at.x()), int(at.y())))
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("usb", SSB))
        # Off: no marks.
        win.skim_view.marks_on.toggled.emit(False)
        self.app.processEvents()
        self.assertEqual(sc.band_marks, [])


if __name__ == "__main__":
    unittest.main()
