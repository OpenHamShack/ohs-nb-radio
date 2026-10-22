"""Auto-tune and best audio from the window: the Receive card's buttons,
A and Shift+A, and the scopes' right-click - driven as an operator would,
checked against where the engine ended up and what the card says."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from test_ui_window import HAVE_QT, WindowCase

if HAVE_QT:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

STATION = 10_489_700_000.0
LEVEL_10DB = -48.0          # tests/test_auto_listen.py says why


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class AutoUi(WindowCase):
    def on_air(self, dial_off=0.0, **over):
        win, bridge, radio = self.window(rxCorr=2500.0, beaconMode="hold", vfo=STATION + dial_off, **over)
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        radio.dev.add_station("talk-usb", STATION, LEVEL_10DB, seed=5)
        self.run_for(radio, 0.3)
        return win, bridge, radio

    def settled(self, radio, bridge):
        return self.run_for(radio, until=lambda: not radio.state()["autoBusy"] and not bridge.st.get("autoBusy")
                            and radio.listening is None, timeout=40)

    def landed(self, radio, bridge, press):
        """Press (button, key, menu) as an operator would - again if it
        refused, as it may when the voice pauses (tests/test_autotune.py
        holds it to answering three times in four) - until it lands."""
        for _ in range(3):
            press()
            self.assertTrue(self.settled(radio, bridge))
            if not radio.state()["autoTuneRefused"]:
                break
        self.assertLess(abs(radio.state()["vfo"] - STATION), 10.0, radio.state()["autoTuneRefused"])

    def test_the_button_lands_the_station_and_says_so(self):
        win, bridge, radio = self.on_air(dial_off=-180.0)
        card = win.rxcard
        QTest.mouseClick(card.tune_btn, Qt.MouseButton.LeftButton)
        self.assertEqual(card.tune_btn.text, "Listening…")
        self.assertFalse(card.audio_btn.isEnabled())
        self.assertTrue(self.settled(radio, bridge))
        if radio.state()["autoTuneRefused"]:
            self.assertIn("Auto-tune refused: ", card.auto_note.text())
            self.landed(radio, bridge, lambda: QTest.mouseClick(card.tune_btn, Qt.MouseButton.LeftButton))
        self.assertLess(abs(radio.state()["vfo"] - STATION), 10.0, radio.state()["autoTuneRefused"])
        note = card.auto_note.text()
        self.assertRegex(note, r"^Auto-tune: \+1[789]\d Hz \(USB, pitch")
        self.assertEqual(card.tune_btn.text, "Auto-tune")

    def test_a_refusal_is_said_on_the_card(self):
        win, bridge, radio = self.window(rxCorr=2500.0, beaconMode="hold", vfo=STATION)
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        QTest.mouseClick(win.rxcard.tune_btn, Qt.MouseButton.LeftButton)
        self.assertTrue(self.settled(radio, bridge))
        self.assertEqual(radio.state()["vfo"], STATION)
        self.assertIn("Auto-tune refused: nothing near the dial", win.rxcard.auto_note.text())

    def test_keys_a_and_shift_a(self):
        win, bridge, radio = self.on_air(dial_off=60.0, nr=False)
        win.wide.setFocus()
        self.landed(radio, bridge, lambda: QTest.keyClick(win, "a"))
        QTest.keyClick(win, "A", Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(self.settled(radio, bridge))
        s = radio.state()
        self.assertTrue(s["nr"], s["autoAudioRefused"])
        self.assertIn("Best audio: ", win.rxcard.auto_note.text())
        self.assertIn("agc: slow", win.rxcard.audio_btn.toolTip())
        listed = {k for _t, rows in win.overlay.sections for k, _w in rows}
        self.assertTrue({"A", "Shift + A"} <= listed)

    def test_right_click_on_the_voice_tunes_there(self):
        win, bridge, radio = self.on_air(dial_off=8000.0)
        self.run_for(radio, 0.5)
        sc = win.wide
        # Where the voice is on the scope - the middle of it, 1.3 kHz above
        # its carrier - not where its carrier is.
        x = int(round(sc.fmap.x(STATION + 1300.0)))

        def right_click():
            QTest.mouseClick(sc, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(x, int(sc.r_spec.center().y())))
            menu = win.scope_menu_open
            act = [a for a in menu.actions() if a.text() == "Auto-tune onto the voice here"]
            self.assertEqual(len(act), 1, [a.text() for a in menu.actions()])
            act[0].trigger()
            menu.close()
            # Listening from the carrier the spectrum shows, not the mouse.
            self.assertLess(abs(radio.listening["dial"] - STATION), 150.0)
        self.landed(radio, bridge, right_click)
        st = radio.state()
        self.assertLessEqual(st["filterLo"], 300.0)
        self.assertGreaterEqual(st["filterHi"], 2500.0)

    def test_not_offered_outside_usb_and_lsb(self):
        win, bridge, radio = self.window(mode="cw")
        self.run_for(radio, until=lambda: radio.state()["running"], timeout=10)
        self.run_for(radio, 0.3)
        card = win.rxcard
        self.assertFalse(card.tune_btn.isEnabled())
        self.assertFalse(card.audio_btn.isEnabled())
        self.assertIn("USB and LSB", card.auto_note.text())
        self.assertNotIn("Auto-tune onto the voice here", [t for t, _f, _d in win.scope_menu_items(STATION)])


if __name__ == "__main__":
    unittest.main()
