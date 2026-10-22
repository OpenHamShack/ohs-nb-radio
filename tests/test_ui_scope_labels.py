import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The scopes' own furniture after WP7 (ohscore/ui/scope.py): decode labels
on a crowded zoom never overlap, never cross the right edge and never sit
under the Adjust pill, and fall back to the call alone when the full text
has no room; the pill says "Adjust" (the glyph alone in the Tight tier),
and its tooltip and popover name the scope; JS8's labels and TX mark follow
its speed, not Normal's."""
import random
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QLabel


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Labels(WindowCase):
    def zoom(self, width=270, height=520):
        from ohscore.ui.scope import ScopeView
        win, bridge, radio = self.window(mode="ft8", vfo=10_489_540_000.0)
        self.run_for(radio, 1.0)
        sc = ScopeView(bridge, win.prefs, "zoom")
        sc.resize(width, height)
        sc.show()
        self.addCleanup(sc.detach)
        self.addCleanup(sc.close)
        self.app.processEvents()
        return win, bridge, sc

    def test_thirty_labels_on_a_270_px_zoom(self):
        win, bridge, sc = self.zoom()
        dial = float(bridge.st["rxDial"])
        lo, hi = sc.fmap.f(0), sc.fmap.f(sc.width())
        rng = random.Random(7)
        now = time.time()
        sc.last_line_t = now
        calls = ["7P8GE", "EA1EAU", "II4JOTA", "DL5XL", "G4XYZ", "F6GHG", "IU5OHC", "DK5AI", "LX9S", "HB0AA"]
        for n in range(30):
            call = calls[n % len(calls)]
            f = rng.uniform(max(lo, dial + 200), min(hi, dial + 3_000))
            sc.add_label(f, f"CQ {call} JO31", now - rng.uniform(0, 12), "cq", call=call)
        # One right at the edge: it must go left of its signal.
        edge_f = sc.fmap.f(sc.width() - 12)
        sc.add_label(edge_f, "CQ GM4BRI IO75", now, "cq", call="GM4BRI")
        lay = sc.decode_layout()
        self.assertGreater(len(lay), 5)
        pill = sc._levels_button()
        boxes = [box for _lab, box, _t, _a in lay]
        for i, a in enumerate(boxes):
            self.assertGreaterEqual(a.left(), 0)
            self.assertLessEqual(a.right(), sc.width())
            self.assertLessEqual(a.bottom(), sc.r_wf.bottom())
            self.assertFalse(a.intersects(pill), a)
            for b in boxes[i + 1:]:
                self.assertFalse(a.intersects(b), (a, b))
        edge = next(x for x in lay if x[0]["call"] == "GM4BRI")
        self.assertLessEqual(edge[1].right(), sc.fmap.x(edge_f))
        # Crowded: some got the call alone rather than nothing.
        self.assertTrue(any(text == lab["call"] for lab, _b, text, _a in lay))
        sc.repaint()                                      # and it paints what it laid out

    def test_streaming_tags_keep_out_from_under_the_pill(self):
        # The RTTY screenshot of 18/10 had a ticker running under the zoom's
        # Adjust pill: tags shared the pill's row and were never laid out.
        win, bridge, sc = self.zoom()
        pill = sc._levels_button()
        now = time.time()
        long_text = "CQ CQ DE GM4BRI GM4BRI PSE K"
        # Under the pill, right of it at the edge, and a short one far left.
        sc.add_tag(sc.fmap.f(pill.center().x()), long_text, now)
        sc.add_tag(sc.fmap.f(sc.width() - 3), "RYRYRY", now)
        sc.add_tag(sc.fmap.f(30), "DE G4XYZ", now)
        lay = sc.tag_layout()
        self.assertEqual(len(lay), 3)
        for _tag, box, text, _age in lay:
            self.assertGreaterEqual(box.left(), 0)
            self.assertLessEqual(box.right(), sc.width())
            self.assertFalse(box.intersects(pill), (text, box, pill))
        shown = {t["text"].strip(): text for t, _b, text, _a in lay}
        # Too long for the room left of the pill: the newest end survives.
        self.assertNotEqual(shown[long_text], long_text)
        self.assertTrue(shown[long_text].endswith("PSE K"), shown[long_text])
        self.assertEqual(shown["RYRYRY"], "RYRYRY")
        self.assertEqual(shown["DE G4XYZ"], "DE G4XYZ")
        sc.repaint()

    def test_the_adjust_pill_names_its_scope(self):
        win, bridge, radio = self.window()
        self.run_for(radio, 1.0)
        for sc, name in ((win.wide, "wide"), (win.zoom, "zoom")):
            self.assertEqual(sc.pill_text(), "Adjust")
            b = sc._levels_button()
            self.assertGreater(b.width(), sc.PILL_GLYPH)
            QTest.mouseMove(sc, b.center().toPoint())
            self.app.processEvents()
            self.assertEqual(sc.toolTip(), f"Adjust the {name} scope: scale, peaks, waterfall levels and palette")
            QTest.mouseClick(sc, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b.center().toPoint())
            pop = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "AdjustPopover"
                       and w.isVisible())
            self.assertIn(f"Adjust the {name} scope", [lab.text() for lab in pop.findChildren(QLabel)])
            pop.close()
        # Tight: the glyph alone.
        win.resize(1024, 600)
        self.run_for(radio, until=lambda: win.tier == "tight", timeout=5)
        self.assertEqual(win.zoom.pill_text(), "")
        self.assertEqual(win.zoom._levels_button().width(), win.zoom.PILL_GLYPH)
        QTest.mouseMove(win.zoom, win.zoom._levels_button().center().toPoint())
        self.app.processEvents()
        self.assertIn("zoom scope", win.zoom.toolTip())


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class HideLabels(WindowCase):
    """Adjust › "Show signal labels" and L (19/10): off, no scope lays out
    a decode label, a band mark or an alert caption; the alert's column,
    the passband and the streaming text tag stay. Remembered in ui.json."""

    def crowd(self, win):
        """Decode labels on the zoom, a band mark and an alert on the wide."""
        now = time.time()
        zoom, wide = win.zoom, win.wide
        zoom.last_line_t = now
        dial = float(win.bridge.st["rxDial"])
        for n, call in enumerate(("7P8GE", "GM0OTB", "EA5XX")):
            zoom.add_label(dial + 500 + 600 * n, f"CQ {call} IO75", now, "cq", call=call)
        zoom.add_tag(dial + 1_200, "CQ DE GM4BRI", now)
        mid = wide.fmap.f(wide.width() / 2)
        wide.set_band_marks([{"lo": mid - 2_000, "hi": mid + 2_000, "text": "CW", "colour": "peak"}])
        wide.set_alerts([{"lo": mid + 5_000, "hi": mid + 8_000, "text": "Over the beacon", "colour": "warn"}])

    def shown(self, win):
        """(decode labels, band marks, alert columns, alert captions, tags) laid out."""
        alerts = win.wide.alert_layout()
        return (len(win.zoom.decode_layout()), len(win.wide.band_mark_layout()), len(alerts),
                sum(box is not None for _a, _c, box in alerts), len(win.zoom.tag_layout()))

    def test_l_hides_and_shows_them_and_ui_json_keeps_it(self):
        from ohscore.ui.prefs import Prefs
        win, bridge, radio = self.window(mode="ft8", vfo=10_489_540_000.0)
        self.addCleanup(lambda: win.prefs.__setitem__("scopeLabels", True) or win.prefs.save())
        self.run_for(radio, 1.0)
        self.crowd(win)
        self.assertEqual(self.shown(win), (3, 1, 1, 1, 1))              # on by default
        win.wide.setFocus()
        QTest.keyClick(win, "l")
        self.assertFalse(win.prefs["scopeLabels"])
        self.assertEqual(self.shown(win), (0, 0, 1, 0, 1))              # column and ticker stay
        self.assertFalse(Prefs(win.prefs.path)["scopeLabels"])          # saved, not only in memory
        win.zoom.repaint()
        win.wide.repaint()
        # Caps Lock sends "L": the same key.
        QTest.keyClick(win, "L", Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(win.prefs["scopeLabels"])
        self.assertEqual(self.shown(win), (3, 1, 1, 1, 1))
        listed = {k for _t, rows in win.overlay.sections for k, _w in rows}
        self.assertIn("L", listed)

    def test_the_adjust_toggle_is_the_same_setting(self):
        from ohscore.ui.controls import Toggle
        win, bridge, radio = self.window(mode="ft8", vfo=10_489_540_000.0)
        self.addCleanup(lambda: win.prefs.__setitem__("scopeLabels", True) or win.prefs.save())
        self.run_for(radio, 1.0)
        self.crowd(win)
        b = win.zoom._levels_button()
        QTest.mouseClick(win.zoom, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b.center().toPoint())
        pop = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "AdjustPopover"
                   and w.isVisible())
        t = next(w for w in pop.findChildren(Toggle) if w.label == "Show signal labels")
        self.assertTrue(t.on)
        t.set_on(False, emit=True)
        pop.close()
        self.assertEqual(self.shown(win), (0, 0, 1, 0, 1))              # the wide too, not only the zoom
        QTest.keyClick(win, "l")
        self.assertTrue(win.prefs["scopeLabels"])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Js8Speeds(WindowCase):
    def test_labels_and_the_tx_mark_follow_the_speed(self):
        from ohscore.modegroups import JS8_SPEEDS
        win, bridge, radio = self.window(mode="js8", vfo=10_489_548_000.0)
        self.run_for(radio, 0.5)
        sc = win.zoom
        for speed, sp in JS8_SPEEDS.items():
            win.prefs["js8Speed"] = speed
            self.assertEqual(sc.slot("js8").tone_width, 8 * sp.spacing)
            slot = 1_760_000_000.0
            win.label_event({"mode": "js8", "text": "GM4BRI: HELLO", "call": "GM4BRI", "slot": slot, "df": 1000,
                             "dial": 10_489_548_000.0, "speed": speed}, (sc,))
            self.assertAlmostEqual(sc.labels[-1]["t"], slot + sp.start + sp.duration / 2, delta=0.06)
        win.prefs["js8Speed"] = "normal"


if __name__ == "__main__":
    unittest.main()
