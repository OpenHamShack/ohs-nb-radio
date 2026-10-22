"""OpenHamShack HAM's window against its engine on the band simulator, on Qt's
offscreen platform: the readout's band-dependent digits, the band bar,
the licence chip, the FM panel, Settings' power chain and the first-run
licence class. Driven as an operator would, checked against what the
engine was told."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ham_helpers import make_radio, pump
from ohsradio.ui.face import HamFace, mhz_text, parse_freq


class Face(unittest.TestCase):
    def test_digit_groups_follow_the_size_of_the_number(self):
        f = HamFace()

        def text(hz):
            return "".join(t for t, _p, k in f.digit_groups(hz))

        self.assertEqual(text(7_074_000), "7.074 000")
        self.assertEqual(text(14_074_000), "14.074 000")
        self.assertEqual(text(145_500_000), "145.500 000")
        self.assertEqual(text(1_296_200_000), "1 296.200 000")
        self.assertEqual(text(5_760_100_000), "5 760.100 000")
        # Each digit's place value is what the wheel over it tunes by.
        g = f.digit_groups(145_500_000)
        self.assertEqual(g[0], ("145", 8, "bright"))
        self.assertEqual(g[2], ("500", 5, "bright"))
        self.assertEqual(g[4], ("000", 2, "small"))
        self.assertEqual(f.digit_groups(1_296_200_000)[0], ("1", 9, "bright"))

    def test_parse_freq(self):
        self.assertEqual(parse_freq("14.074"), 14_074_000)
        self.assertEqual(parse_freq("145.5"), 145_500_000)
        self.assertEqual(parse_freq("433500"), 433_500_000)
        self.assertEqual(parse_freq("1296.2"), 1_296_200_000)
        self.assertEqual(parse_freq("7074 kHz"), 7_074_000)
        self.assertEqual(parse_freq("2.4g"), 2_400_000_000)
        self.assertEqual(parse_freq("14074000"), 14_074_000)
        with self.assertRaisesRegex(ValueError, "not a frequency"):
            parse_freq("fourteen")
        with self.assertRaisesRegex(ValueError, "outside"):
            parse_freq("9000")

    def test_mhz_text(self):
        self.assertEqual(mhz_text(433_500_000), "433.500 000")
        self.assertEqual(mhz_text(2_320_200_000), "2 320.200 000")


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
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

    def window(self, licence=True, **over):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_radio(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = licence
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle(0.3)
        return win, bridge, radio, prefs

    def settle(self, sec):
        import time
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def settle_until(self, cond, sec=5.0):
        """Process events until cond() holds or sec has passed. For a test
        waiting on the meter stream: a fixed settle is enough on an idle
        machine and not on a loaded one (the development machine at load 20 on 05/10 left the
        PA temperature meter hidden after 0.3 s, though the radio had
        reported it), so the wait ends on the outcome, with a deadline."""
        import time
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_band_bar_click_recalls_the_band(self):
        win, bridge, radio, _ = self.window()
        bar = win.bandbar
        r = next(rect for rect, kind, key in bar.cells if key == "20m")
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.center().y())))
        self.settle(0.2)
        self.assertEqual(radio.state()["band"], "20m")
        self.assertEqual(radio.state()["vfo"], 14_125_000.0)        # from FM: the SSB segment's start
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.center().y())))
        self.settle(0.2)
        self.assertEqual(radio.state()["vfo"], 14_074_000.0)

    def test_deferred_band_is_not_on_the_bar(self):
        # Since 13/10/2026 the bar holds only what the receiver covers: 6 m,
        # with no radio here, is left off rather than drawn faint (its
        # reason is still what band("6m") refuses with, test_ham_radio).
        win, bridge, radio, _ = self.window()
        win.bandbar.repaint()
        keys = [key for _r, kind, key in win.bandbar.cells if kind == "band"]
        self.assertNotIn("6m", keys)
        self.assertIn("4m", keys)

    def test_licence_chip_says_refused_on_23cm_for_foundation(self):
        win, bridge, radio, _ = self.window()
        radio.band("23cm")
        radio.set(mode="usb")
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertEqual(win.lic_chip.word, "NO TX HERE")
        self.assertIn("Foundation licence", win.lic_chip.toolTip())
        self.assertIn("Foundation licence", bridge.can_key())

    def test_with_no_class_the_chip_the_tx_button_and_the_strip_say_why(self):
        win, bridge, radio, _ = self.window(licenceClass="")
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertEqual(win.lic_chip.word, "NO CLASS")
        self.assertIn("not chosen", win.lic_chip.title)
        self.assertIn("No licence class chosen", win.lic_chip.toolTip())
        self.assertIn("No licence class chosen", bridge.can_key())
        self.assertIn("No licence class chosen", win.ptt.toolTip())
        self.assertIn(("no licence class: TX locked", "warn"), win.status_items(bridge.st))
        self.assertEqual(win.ptt.caption(), ("TX", "Choose a licence class"))
        # Choosing one in Settings unlocks it.
        from ohsradio.ui.settings import SettingsDialog
        d = SettingsDialog(bridge, win.prefs, win, page=2)
        d.fields["licenceClass"].w.set_value("intermediate")
        d.save()
        self.settle(0.2)
        self.assertEqual(radio.state()["licenceClass"], "intermediate")
        self.assertEqual(bridge.can_key(), "")
        self.assertNotEqual(win.lic_chip.word, "NO CLASS")

    def test_welcome_preselects_no_class_and_will_not_vouch_for_none(self):
        from ohsradio.ui.welcome import Welcome
        win, bridge, radio, prefs = self.window(licenceClass="")
        w = Welcome(bridge, prefs, win)
        w.show()
        self.assertEqual(w.cls.value, "")
        w.go(1)
        w.ack.setChecked(True)
        w.go(2)
        w._next()
        self.settle(0.05)
        self.assertEqual(w.stack.currentIndex(), 1)       # back to the class, with the reason
        self.assertIn("Choose your licence class", w.cls_msg.text())
        self.assertEqual(radio.state()["licenceClass"], "")
        w.cls.set_value("intermediate")
        w.go(2)
        w._next()
        self.assertEqual(radio.state()["licenceClass"], "intermediate")

    def test_welcome_listens_only_with_no_class_and_no_box(self):
        from ohsradio.ui.welcome import Welcome
        win, bridge, radio, prefs = self.window(licence=False, licenceClass="")
        w = Welcome(bridge, prefs, win)
        w.go(2)
        w._next()
        self.assertTrue(prefs["welcomed"])
        self.assertEqual(radio.state()["licenceClass"], "")

    def test_licence_chip_is_not_green_on_a_band_with_no_radio(self):
        win, bridge, radio, _ = self.window()
        radio.set(vfo=50_150_000.0, mode="usb")          # typed: the band button refuses 6 m
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertEqual(win.lic_chip.word, "NO RADIO")
        self.assertNotIn(win.lic_chip.colour, ("ok", "warn"))
        self.assertIn("38.4 MHz", win.lic_chip.toolTip())
        self.assertIn("38.4 MHz", bridge.can_key())

    def test_fm_panel_and_repeater_shift(self):
        win, bridge, radio, _ = self.window()
        bridge.set(mode="fm", vfo=145_650_000.0)
        self.settle(0.3)
        panel = win.panels.get("fm")
        self.assertIsNotNone(panel)
        self.assertIs(win.panel, panel)
        self.assertEqual(panel.plate.name, "RV52")
        self.assertEqual(radio.state()["txDial"], 145_050_000.0)
        panel.tx_tone._step(3)                     # off -> the third tone
        self.settle(0.1)
        self.assertEqual(radio.state()["ctcssTx"], 71.9)              # off, 67.0, 69.3, 71.9
        panel.reverse.set_on(True, emit=True)
        self.settle(0.1)
        st = radio.state()
        self.assertEqual((st["rxDial"], st["txDial"]), (145_050_000.0, 145_650_000.0))

    def test_the_offset_field_sets_minus_and_plus(self):
        win, bridge, radio, _ = self.window()
        toasts = []
        bridge.toast.connect(toasts.append)
        radio.band("70cm")
        bridge.set(mode="fm", vfo=433_150_000.0, rptShift="plus")
        self.settle(0.3)
        panel = win.panels.get("fm")
        self.assertEqual(panel.offset.text(), "1.6")                  # 70 cm's own split on arrival
        panel.offset.setText("5")
        panel.offset.editingFinished.emit()
        self.settle(0.1)
        self.assertEqual(radio.state()["txDial"], 438_150_000.0)     # an RBW repeater's input
        panel.offset.setText("five")
        panel.offset.editingFinished.emit()
        self.settle(0.1)
        self.assertEqual(radio.state()["rptOffsetHz"], 5_000_000.0)  # unchanged
        self.assertEqual(panel.offset.text(), "5")
        self.assertTrue(any("not an offset" in t["text"] for t in toasts))

    def test_pa_temperature_appears_once_the_radio_reports_it(self):
        win, bridge, radio, _ = self.window()
        card = win.txcard
        self.assertTrue(card.temp.isHidden())          # nothing reported yet: no meter that can only say "-"
        bridge.set(vfo=144_050_000.0, mode="cw")      # in the band already simulated: no template build
        card.tune.set_checked(True)
        card._tune()
        self.settle(1.5)
        self.assertTrue(radio.state()["keyed"])
        card.tune.set_checked(False)
        card._tune()
        self.settle_until(lambda: not card.temp.isHidden())
        temp = radio.state()["paTemp"]
        self.assertGreater(temp, 0)
        self.assertFalse(card.temp.isHidden())
        self.assertAlmostEqual(card.temp.text_value, temp, delta=1.0)
        self.assertEqual(card.temp.cap, radio.state()["paTempLimit"])

    def test_an_estimate_over_the_licence_warns_on_the_transmit_card(self):
        win, bridge, radio, _ = self.window()
        # A 100 W PA on 2 m with a Foundation licence: 25 W PEP is a drive of
        # 0.5. The slider goes past it (only the ceiling holds it), and the
        # card says, in its standing warning, that the estimate is over.
        radio.set(authorise=True, bandPower={"2m": {"devW": 1.0, "paGainDb": 20.0, "ceiling": 0.9}})
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertAlmostEqual(win.txcard.drive.cap, 0.9)
        self.assertTrue(win.txcard.warning.isHidden())
        win.txcard.drive.set_value(1.0, emit=True)
        self.settle(0.2)
        self.assertAlmostEqual(radio.state()["drive"], 0.9)
        self.assertFalse(win.txcard.warning.isHidden())
        self.assertIn("Estimate over the licence limit", win.txcard.warning.text())
        self.assertIn("estimate", win.lic_chip.toolTip())
        self.assertEqual(win.lic_chip.colour, "warn")
        self.assertEqual(bridge.can_key(), "")

    def test_through_a_transverter_with_no_output_entered_the_card_says_unknown(self):
        # 23 cm from the simulator on a 2 m IF: the radio's few milliwatts
        # are not what reaches the antenna, so no figure is printed.
        xv = {"title": "1296 MHz (144 MHz IF)", "type": "down", "rxtx": True, "rxOffset": 1152e6,
              "txOffset": 1152e6, "inverted": False, "maxDriveDbm": -10.0}
        win, bridge, radio, _ = self.window(converters=[xv], bandConverters={"23cm": xv["title"]},
                                            vfo=1_296_200_000.0, mode="usb", drive=0.1)
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertFalse(win.txcard.warning.isHidden())
        self.assertIn("transverter output not entered", win.txcard.warning.text())
        self.assertNotIn("≈", win.txcard.power.text())
        radio.set(authorise=True, bandPower={"23cm": {"paGainDb": 30.0}})
        bridge.st.update(radio.state())
        win.on_state(dict(bridge.st))
        self.assertTrue(win.txcard.warning.isHidden())
        self.assertIn("≈", win.txcard.power.text())

    def test_settings_power_chain_round_trip(self):
        from ohsradio.ui.settings import SettingsDialog
        win, bridge, radio, prefs = self.window()
        d = SettingsDialog(bridge, prefs, win, page=3)
        d.power_edits["2m"]["paGainDb"].setText("30")
        d.power_edits["2m"]["ceiling"].setText("50")
        d.save()
        self.assertEqual(radio.state()["bandPower"]["2m"], {"paGainDb": 30.0, "lossDb": 0.0, "antGainDbi": 0.0,
                                                           "ceiling": 0.5})
        d2 = SettingsDialog(bridge, prefs, win, page=3)
        d2.power_edits["2m"]["paGainDb"].setText("loud")
        d2.save()
        self.assertIn("not a number", d2.error.text())
        d2.reject()

    def test_welcome_sets_the_licence_class(self):
        from ohsradio.ui.welcome import Welcome
        win, bridge, radio, prefs = self.window()
        w = Welcome(bridge, prefs, win)
        w.cls.set_value("full")
        w.finish()
        self.assertEqual(radio.state()["licenceClass"], "full")

    def test_welcome_shows_a_licence_class_error_where_the_class_is(self):
        from unittest import mock
        from ohsradio.ui.welcome import Welcome
        win, bridge, radio, prefs = self.window()
        w = Welcome(bridge, prefs, win)
        w.show()
        w.go(1)
        w.cls.set_value("full")
        w.go(2)                                       # on the last page, pressing Start
        real = radio.set

        def refuse(*a, **kw):
            if "licenceClass" in kw:
                raise ValueError("Licence class refused for this test")
            return real(*a, **kw)
        with mock.patch.object(radio, "set", side_effect=refuse):
            w._next()
        self.settle(0.05)
        self.assertEqual(w.stack.currentIndex(), 1)   # taken back to the licence page
        self.assertTrue(w.cls_msg.isVisible())
        self.assertIn("refused for this test", w.cls_msg.text())
        self.assertTrue(w.isVisible())                # not closed as if it had worked
        self.assertEqual(radio.state()["licenceClass"], "foundation")
        w.go(2)
        w._next()                                     # without the fault it saves and closes
        self.assertEqual(radio.state()["licenceClass"], "full")
        self.assertEqual(w.cls_msg.text(), "")

    def test_welcome_and_settings_give_the_pluto_one_safety_rule(self):
        # They used to disagree: Welcome wanted a low-pass filter before any
        # PA, Settings said a PA's filter would do. Both now say what the
        # guide does - no output filter, and a dummy load and spectrum
        # analyser before any PA - as the operator sees them.
        import re
        from PyQt6.QtWidgets import QLabel
        from ohsradio.ui.settings import SettingsDialog
        from ohsradio.ui.welcome import Welcome
        win, bridge, radio, prefs = self.window()
        w = Welcome(bridge, prefs, win)
        d = SettingsDialog(bridge, prefs, win, page=3)
        for dialog in (w, d):
            said = [re.sub("<[^>]+>", "", lab.text()) for lab in dialog.findChildren(QLabel)]
            rule = [t for t in said if "no output filter" in t.lower()]
            self.assertTrue(rule, type(dialog).__name__)
            for t in rule:
                self.assertIn("dummy load", t)
                self.assertIn("spectrum analyser", t)
                self.assertIn("before it drives any PA", t)
                self.assertNotIn("a PA or a low-pass filter", t)
        w.reject()
        d.reject()

    @unittest.skipUnless(sys.platform.startswith("linux"), "loopback broadcast (127.255.255.255) is Linux's")
    def test_settings_find_lists_a_hermes_lite_2_and_picking_it_fixes_the_address(self):
        from unittest import mock
        from ohscore.devices import hl2
        from ohscore.devices.hl2sim import HL2Sim
        from ohsradio.ui.settings import SettingsDialog
        win, bridge, radio, prefs = self.window()
        d = SettingsDialog(bridge, prefs, win, page=1)
        field = d.fields["hl2Address"].w
        # Nothing answering: a sentence, no list, the address left alone.
        with mock.patch.object(hl2, "_broadcast_addresses", lambda: []):
            d.find_hl2()
        self.assertTrue(d.hl2_found.isHidden())
        self.assertIn("No Hermes-Lite 2 answered", d.error.text())
        self.assertEqual(field.text(), "")
        # The emulator, answering the broadcast (on loopback, at its port).
        sim = HL2Sim(host="0.0.0.0").start()
        self.addCleanup(sim.stop)
        with mock.patch.object(hl2, "_broadcast_addresses", lambda: ["127.255.255.255"]), \
                mock.patch.object(hl2, "PORT", sim.port):
            d.find_hl2()
        self.assertFalse(d.hl2_found.isHidden())
        self.assertEqual(d.hl2_found.count(), 1)
        self.assertIn("gateware 74.2", d.hl2_found.itemText(0))
        self.assertEqual(d.error.text(), "")
        self.assertEqual(field.text(), "")            # listed, not pinned: broadcast still finds it
        d.hl2_found.activated.emit(0)
        self.assertEqual(field.text(), "127.0.0.1")
        d.reject()

    def test_noise_reduction_on_the_card_and_shift_n(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ohsradio.ui.settings import SettingsDialog
        win, bridge, radio, prefs = self.window(mode="usb")
        QTest.mouseClick(win.rxcard.nr, Qt.MouseButton.LeftButton)
        self.settle(0.2)
        self.assertTrue(radio.state()["nr"])
        QTest.keyClick(win, "N", Qt.KeyboardModifier.ShiftModifier)   # text "N", as a keyboard sends it
        self.settle(0.2)
        self.assertFalse(radio.state()["nr"])
        self.assertFalse(radio.state()["nb"])
        self.assertIn("Shift + N", {k for _t, rows in win.overlay.sections for k, _w in rows})
        d = SettingsDialog(bridge, prefs, win)
        try:
            self.assertIn("nr", d.fields)
            d.fields["nrStrength"].w.set_value(80.0, emit=True)
            d.save()
        finally:
            d.close()
        self.assertEqual(radio.state()["nrStrength"], 80.0)

    def test_all_settings_pages_build(self):
        from ohsradio.ui.settings import SettingsDialog
        win, bridge, radio, prefs = self.window()
        d = SettingsDialog(bridge, prefs, win)
        for i in range(len(d.PAGES)):
            d.nav.select(i)
            self.settle(0.02)
        d.reject()

    def test_second_display_and_theme_switch(self):
        win, bridge, radio, prefs = self.window()
        win.toggle_second()
        self.settle(0.3)
        self.assertIsNotNone(win.second)
        win.set_theme("light")
        self.settle(0.3)
        self.assertTrue(win.bandbar.isVisible())
        win.second.close()
        self.settle(0.1)

    def test_shortcut_overlay_paints(self):
        win, bridge, radio, prefs = self.window()
        win.overlay.open()
        self.settle(0.3)
        win.overlay.grab()
        win.overlay.close_()

    def test_every_menu_shortcut_is_in_the_shortcuts_overlay(self):
        from PyQt6.QtGui import QAction
        win, bridge, radio, _ = self.window()
        listed = {k.replace(" ", "") for _title, rows in win.overlay.sections for k, _what in rows}
        bound = {a.shortcut().toString() for a in win.findChildren(QAction) if not a.shortcut().isEmpty()}
        self.assertTrue(bound)
        self.assertEqual(bound - listed, set())

    def test_without_licence_ack_nothing_keys(self):
        win, bridge, radio, _ = self.window(licence=False)
        bridge.ptt(True)
        self.settle(0.2)
        self.assertFalse(radio.state()["keyed"])
        win.txcard.tune.set_checked(True)
        win.txcard._tune()
        self.settle(0.2)
        self.assertFalse(radio.state()["keyed"])


if __name__ == "__main__":
    unittest.main()
