import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The "What is this?" card in NB's window (ohsnb/ui/whatis.py): a
right-click on the scope over the simulator's FT8 window opens it, says what
is there and Decode FT8 tunes there in FT8, bringing the Digital workspace;
on the middle beacon Show its text opens Beacon › Middle beacon; an
over-power column says what its number means; while the simulator is keyed
every action is greyed and nothing retunes, even if one is pressed anyway.
The skimmer's list is put on the engine's feed by hand, as in
tests/test_ui_skim.py, so every entry is known; tests/test_whatis.py covers
the rules row by row."""
import time
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

FT8 = 10_489_540_000.0
MID = 10_489_750_000.0


def entry(**kw):
    e = {"id": 1, "f": 0.0, "lo": 0.0, "hi": 0.0, "kind": "signal", "label": "", "mode": "usb", "dial": None,
         "exact": False, "measured": "", "voice": False, "why": "", "snr": 18.0, "first": time.time() - 30,
         "last": time.time(), "active": True, "looks": 1, "count": 1}
    e.update(kw)
    return e


LIST = [
    entry(id=-10489540, f=FT8, lo=FT8 + 150.0, hi=FT8 + 3_100.0, kind="digital", label="FT8", mode="ft8", dial=FT8,
          exact=True, count=12, calls=["7P8GE", "EA1EAU", "II4JOTA", "DL5XL"]),
    entry(id=2, f=MID, lo=MID - 400.0, hi=MID + 400.0, kind="beacon", label="Middle beacon (400 Bd BPSK)"),
]


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Card(WindowCase):
    def on_air(self, entries=LIST, **over):
        win, bridge, radio = self.window(skimDecode=False, beaconMode="hold", vfo=10_489_700_000.0, **over)
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        radio._publish("skim", {"t": time.time(), "entries": [dict(e) for e in entries]})
        self.run_for(radio, until=lambda: len(win.skim_store.entries) == len(entries), timeout=10)
        return win, bridge, radio

    def right_click(self, win, f, scope=None):
        sc = scope or win.wide
        x = int(round(sc.fmap.x(f)))
        QTest.mouseClick(sc, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(x, int(sc.r_spec.center().y())))
        card = win.scope_menu_open
        self.assertEqual(type(card).__name__, "WhatIsCard")
        self.assertTrue(card.isVisible())
        return card

    def test_decode_ft8_from_the_calling_window(self):
        win, _bridge, radio = self.on_air()
        self.assertEqual(win.workspace, "voice")
        card = self.right_click(win, FT8 + 1_500.0)
        texts = card.texts()
        self.assertEqual(texts[0], "FT8 calling window · 12 signals")
        self.assertIn("7P8GE EA1EAU II4JOTA DL5XL", texts)
        self.assertIn("Narrow digimodes (500 Hz max)", texts)
        self.assertTrue(texts[1].startswith("10489.540 000 FT8 · heard now · SNR 18 dB"), texts[1])
        # The menu's own items stay under it.
        self.assertIn("Lock to this as the lower beacon", [a.text() for a in card.actions()])
        card.button("Decode FT8").clicked.emit()
        self.assertFalse(card.isVisible())
        self.run_for(radio, until=lambda: win.workspace == "digital", timeout=5)
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("ft8", FT8))
        self.assertEqual(win.workspace, "digital")

    def test_with_the_labels_hidden_it_still_opens(self):
        # L hides what is drawn on the scopes (scope.labels_shown), not the
        # card: it reads the skimmer's list, not the labels.
        win, bridge, radio = self.on_air()
        self.addCleanup(lambda: win.prefs.__setitem__("scopeLabels", True) or win.prefs.save())
        win.wide.setFocus()
        QTest.keyClick(win, "l")
        self.assertFalse(win.prefs["scopeLabels"])
        card = self.right_click(win, FT8 + 1_500.0)
        self.assertEqual(card.texts()[0], "FT8 calling window · 12 signals")
        card.close()

    def test_the_simulators_own_ft8_window_from_its_skimmer(self):
        """The same, with nothing put on the feed: the simulator's FT8
        stations, as its own band skimmer lists them."""
        win, _bridge, radio = self.window(vfo=10_489_700_000.0)
        self.assertTrue(self.run_for(radio, until=lambda: any(
            e["kind"] == "digital" and e["label"] == "FT8" for e in win.skim_store.entries), timeout=30))
        card = self.right_click(win, FT8 + 1_500.0)
        self.assertTrue(card.texts()[0].startswith("FT8 calling window"), card.texts())
        card.button("Decode FT8").clicked.emit()
        self.run_for(radio, until=lambda: win.workspace == "digital", timeout=5)
        self.assertEqual((radio.state()["mode"], radio.state()["vfo"]), ("ft8", FT8))

    def test_the_middle_beacon_shows_its_text(self):
        win, _bridge, radio = self.on_air()
        vfo = radio.state()["vfo"]
        card = self.right_click(win, MID + 100.0, scope=None)
        self.assertEqual(card.texts()[0], "Middle beacon (400 Bd BPSK)")
        self.assertIn("Middle beacon: no transmitting", card.texts())
        card.button("Show its text").clicked.emit()
        self.app.processEvents()
        self.assertEqual(win.views.value, "mmb")
        self.assertEqual(win.mmb_view.pages.value, "midtext")
        self.assertEqual(radio.state()["vfo"], vfo)                 # a page, not a retune

    def test_an_over_power_column_says_what_its_number_means(self):
        win, _bridge, radio = self.on_air()
        now = time.time()
        radio._publish("overpower", {"t": now, "events": [
            {"id": 1, "kind": "overpower", "lo": FT8 + 900.0, "hi": FT8 + 2_400.0, "freq": FT8 + 1_650.0,
             "width": 1_500.0, "excessDb": 14.2, "start": now - 40, "end": now, "active": True, "leila": False,
             "call": None}]})
        self.run_for(radio, until=lambda: bool(win.op_store.events), timeout=10)
        card = self.right_click(win, FT8 + 1_500.0)
        texts = card.texts()
        self.assertEqual(texts[0], "+14 dB over the beacon")
        self.assertIn("1 kHz slice", texts[1])
        self.assertIn("FT8 calling window · 12 signals", texts)

    def test_nothing_there_and_the_skimmer_off_say_so(self):
        win, _bridge, _radio = self.on_air(entries=[])
        card = self.right_click(win, 10_489_720_000.0)
        texts = card.texts()
        self.assertEqual(texts[0], "Nothing the band skimmer has found here")
        self.assertIn("SSB only", texts)
        self.assertIn("Band skimmer off: Settings › LNB & locks", texts)
        self.assertEqual(card.buttons, [])

    def test_kgstv_names_the_last_sender(self):
        kg = entry(id=8, f=10_489_624_900.0, lo=10_489_625_100.0, hi=10_489_627_800.0, kind="known",
                   label="KG-STV picture", dial=10_489_624_900.0, exact=True)
        win, _bridge, _radio = self.on_air(entries=[kg])
        win.mmb_store.kg["call"] = "DH1BM"
        card = self.right_click(win, 10_489_626_400.0)
        self.assertEqual(card.texts()[0], "KG-STV picture")
        self.assertIn("Last sent by DH1BM", card.texts())
        self.assertEqual([b.text for _a, b in card.buttons], ["Show pictures", "Listen"])

    def test_while_keyed_every_action_is_greyed_and_nothing_retunes(self):
        win, bridge, radio = self.on_air()
        bridge.ptt(True)                                 # the simulator: nothing radiates
        try:
            self.assertTrue(self.run_for(radio, until=lambda: bridge.face.on_air(bridge.st), timeout=10))
            before = (radio.state()["mode"], radio.state()["vfo"], radio.state()["rxCorr"])
            card = self.right_click(win, FT8 + 1_500.0)
            self.assertIn("Not while transmitting", card.texts())
            self.assertTrue(card.buttons)
            self.assertFalse(any(b.isEnabled() for _a, b in card.buttons))
            self.assertFalse(any(a.isEnabled() for a in card.actions()))
            self.assertFalse(any(b.isEnabled() for b in card.items))
            # Pressed anyway (a disabled Button refuses; the window is asked
            # directly, and the menu items' callables too).
            for a, _b in card.buttons:
                win.whatis_do(a, card.ident)
            for act in card.actions():
                act.setEnabled(True)
                act.trigger()
            self.run_for(radio, 0.3)
            self.assertEqual((radio.state()["mode"], radio.state()["vfo"], radio.state()["rxCorr"]), before)
            self.assertTrue(radio.state()["keyed"])
        finally:
            bridge.ptt(False)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class BandListNotes(WindowCase):
    """The Band list's Note column: what a faint narrow signal is (Mac test
    FINDINGS 7), the surveys' guess where they have one, and a long note
    wrapped to two lines with the whole of it in the tooltip."""

    on_air = Card.on_air

    def test_notes_say_what_the_signal_may_be_and_wrap(self):
        faint = entry(id=5, f=10_489_521_500.0, lo=10_489_521_450.0, hi=10_489_521_550.0, kind="signal",
                      label="Signal (narrow)", why="nothing stands out in the channel", looks=2)
        fsk = entry(id=6, f=10_489_569_500.0, lo=10_489_569_470.0, hi=10_489_569_530.0, kind="data",
                    label="Data (narrow)")
        cw = entry(id=7, f=10_489_525_000.0, lo=10_489_524_980.0, hi=10_489_525_020.0, kind="cw", label="CW",
                   mode="cw")
        win, _bridge, _radio = self.on_air(entries=[faint, cw, fsk])
        win.show_view("skim")
        self.app.processEvents()
        t = win.skim_view.table
        notes = {t.item(r, 1).text(): t.item(r, 5) for r in range(t.rowCount())}
        self.assertIn("too faint to tell CW, a carrier or data apart", notes["Signal (narrow)"].text())
        self.assertNotIn("nothing stands out", notes["Signal (narrow)"].text())
        self.assertIn("QRSS or FSK-CW beacon?", notes["Data (narrow)"].text())
        self.assertEqual(notes["Data (narrow)"].toolTip(), notes["Data (narrow)"].text())
        one = t.verticalHeader().defaultSectionSize()
        rows = {t.item(r, 1).text(): r for r in range(t.rowCount())}
        self.assertEqual(t.rowHeight(rows["CW"]), one)                  # no note: one line
        # Squeezed so the survey's note cannot fit on one line: two lines, no more.
        t.setColumnWidth(5, 220)
        win.skim_view._fit_rows()
        two = one + t.fontMetrics().lineSpacing()
        self.assertEqual(t.rowHeight(rows["Data (narrow)"]), two)


if __name__ == "__main__":
    unittest.main()
