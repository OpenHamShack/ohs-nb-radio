"""Settings' licence controls, shared by both apps (ohscore/ui/licence.py),
driven as an operator would on Qt's offscreen platform: the class picker
offers the classes of the licence the page now implies, the operator's own
licence is entered as segments and reaches the guard, an unsound one is
refused with its sentence, and OpenHamShack NB's Licence page and uplink check
follow the same settings."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ham_helpers import close, make_radio


class HamLicencePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def dialog(self, **over):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        from ohsradio.ui.settings import SettingsDialog
        radio = make_radio(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        self.addCleanup(bridge.stop)
        self.addCleanup(win.close)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Licence & plan"))
        self.addCleanup(d.close)
        return d, radio

    def test_classes_follow_the_callsign_on_the_page(self):
        d, radio = self.dialog(licenceClass="")
        p = d.licence_panel
        self.assertEqual([v for v, _ in p.cls.options], ["", "foundation", "intermediate", "full"])
        self.assertIn("nearLondon", p.cond_toggles)              # the UK's one station question
        # A callsign from a country with no licence written: no classes, and
        # the page says what to do instead.
        d.fields["callsign"].w.setText("ZS1ABC")
        self.assertEqual([v for v, _ in p.cls.options], [""])
        self.assertIn("South Africa", p.licence_note.text())
        self.assertIn("South Africa", d.country_line.text())
        self.assertEqual(p.cond_toggles, {})
        # Choosing the UK licence by name brings its classes back.
        p.licence.setCurrentIndex(p.licence.findData("ofcom-2024"))
        p.cls.set_value("full")
        d.save()
        st = radio.state()
        self.assertEqual((st["callsign"], st["licence"], st["licenceClass"]), ("ZS1ABC", "ofcom-2024", "full"))
        self.assertEqual(st["txBlocked"], "")

    def test_the_operators_own_licence_reaches_the_guard(self):
        d, radio = self.dialog(callsign="ZS1ABC", vfo=14_200_000.0, mode="usb")
        p = d.licence_panel
        p.licence.setCurrentIndex(p.licence.findData("custom"))
        self.assertTrue(p.custom.isVisibleTo(d))
        r = p.custom.add_row()
        for c, text in ((0, "14.0"), (1, "14.35"), (2, "100")):
            p.custom.set_cell(r, c, text)
        d.save()
        st = radio.state()
        self.assertEqual(st["licence"], "custom")
        self.assertEqual(st["customLicence"][0]["lo"], 14_000_000.0)
        self.assertEqual(st["txBlocked"], "")
        radio.set(vfo=7_100_000.0, mode="lsb")
        self.assertIn("outside every segment of your own licence", radio.state()["txBlocked"])

    def test_an_unsound_own_licence_is_refused_with_its_sentence(self):
        d, radio = self.dialog(callsign="ZS1ABC")
        p = d.licence_panel
        p.licence.setCurrentIndex(p.licence.findData("custom"))
        for lo, hi in (("14.0", "14.35"), ("14.2", "14.3")):
            r = p.custom.add_row()
            p.custom.set_cell(r, 0, lo)
            p.custom.set_cell(r, 1, hi)
            p.custom.set_cell(r, 2, "100")
        d.save()
        self.assertIn("overlap", d.error.text())
        self.assertEqual(radio.state()["licence"], "auto")
        p.custom.set_cell(1, 2, "lots")
        d.save()
        self.assertIn("as numbers", d.error.text())


class WelcomeClasses(unittest.TestCase):
    """Welcome offers the classes of the callsign's country, not the UK's
    to everyone."""

    def test_by_callsign(self):
        from ohsradio.ui.welcome import NO_CALL_YET, class_choices
        opts, why = class_choices("GM4BRI")
        self.assertEqual(([v for v, _ in opts], why), (["foundation", "intermediate", "full"], ""))
        opts, why = class_choices("ZS1ABC")
        self.assertEqual(opts, [])
        self.assertIn("No licence for South Africa", why)
        self.assertEqual(class_choices(""), ([], NO_CALL_YET))


class NbUplink(unittest.TestCase):
    """NB's uplink follows the licence in force: a class with no 13 cm, or a
    regime without the amateur-satellite service there, refuses it."""

    def radio(self, **over):
        from ohscore.audio import NullAudio
        from ohsnb.radio import Radio
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "mode": "usb"}
        cfg.update(over)
        r = Radio(cfg, persist=False, data_dir=tmp.name, audio=NullAudio(realtime=False))
        self.addCleanup(r.stop)
        r.start()
        return r

    def test_uk_classes(self):
        # Ofcom Schedule 1: every class holds 2400-2450 MHz, amateur-satellite.
        r = self.radio(callsign="GM4BRI", licenceClass="foundation")
        self.assertNotIn("licence", r.state()["txBlocked"].lower())
        self.assertTrue(any("satellite uplink allowed" in n for n in r.state()["station"]["notes"]))

    def test_a_licence_with_no_satellite_uplink_there_refuses(self):
        seg = [{"lo": 2_400_000_000.0, "hi": 2_450_000_000.0, "watts": 10.0, "unit": "PEP"}]
        r = self.radio(callsign="ZS1ABC", licence="custom", customLicence=seg)
        self.assertIn("does not permit an amateur-satellite uplink", r.state()["txBlocked"])
        r.set(authorise=True, customLicence=[dict(seg[0], satellite=True)])
        self.assertEqual(r.state()["txBlocked"], "")

    def test_not_known_is_not_refused_but_said(self):
        r = self.radio()
        self.assertEqual(r.state()["txBlocked"], "")
        self.assertTrue(any("not checked" in n for n in r.state()["station"]["notes"]))


if __name__ == "__main__":
    unittest.main()
