"""Settings' Radio page, antenna section (ohscore/ui/settings.py
_antenna_section): the drop-down lists what a running FakeAntennaDevice
(tests/test_ham_antenna.py) reports, the label table relabels it live,
and Save writes both soapyAntenna and soapyAntennaLabels in one line of
JSON - the same device shape test_ham_antenna.py drives at the engine,
here driven through the dialog an operator actually opens."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from test_ham_antenna import FakeAntennaDevice


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class AntennaPage(unittest.TestCase):
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

    def window(self, soapy_antenna_labels=""):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.radio import Radio
        from ohsradio.ui import build
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI",
               "licenceClass": "foundation", "soapyAntenna": "Antenna A",
               "soapyAntennaLabels": soapy_antenna_labels}
        self.dev = FakeAntennaDevice(initial="Antenna A")
        radio = Radio(cfg, persist=False, data_dir=self.tmp, device=self.dev)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        self.wins.append((win, bridge))
        self.settle_until(lambda: radio.state().get("deviceStatus", {}).get("antenna"))
        bridge.st.update(radio.state())
        return win, bridge, radio, prefs

    def settle_until(self, cond, sec=5.0):
        import time
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def settle(self, sec):
        import time
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def open_radio_page(self, bridge, win, prefs):
        from ohsradio.ui.settings import SettingsDialog
        return SettingsDialog(bridge, prefs, win, page=1)      # ("antenna", "Radio", "page_radio")

    def test_the_drop_down_lists_every_input_the_device_reported(self):
        win, bridge, radio, prefs = self.window()
        d = self.open_radio_page(bridge, win, prefs)
        names = [d.antenna_combo.itemData(i) for i in range(d.antenna_combo.count())]
        self.assertEqual(names, ["", "Antenna A", "Antenna B", "Antenna C"])
        self.assertEqual(d.antenna_combo.currentData(), "Antenna A")
        d.close()

    def test_a_label_shows_in_the_drop_down_without_closing_the_dialog(self):
        win, bridge, radio, prefs = self.window()
        d = self.open_radio_page(bridge, win, prefs)
        d.antenna_label_edits["Antenna C"].setText("80 m dipole")
        i = d.antenna_combo.findData("Antenna C")
        self.assertEqual(d.antenna_combo.itemText(i), "Antenna C — 80 m dipole")
        d.close()

    def test_save_writes_the_antenna_and_the_label_as_one_line_of_json(self):
        win, bridge, radio, prefs = self.window()
        d = self.open_radio_page(bridge, win, prefs)
        d.antenna_label_edits["Antenna C"].setText("80 m dipole")
        i = d.antenna_combo.findData("Antenna C")
        d.antenna_combo.setCurrentIndex(i)
        d.save()
        self.settle(0.3)
        st = radio.state()
        self.assertEqual(st["soapyAntenna"], "Antenna C")
        self.assertEqual(st["soapyAntennaLabels"], '{"Antenna C":"80 m dipole"}')
        self.assertNotIn("\n", st["soapyAntennaLabels"])
        self.assertFalse(d.restart_needed)          # no reopen: SoapySDRPlay3 switches live

    def test_a_saved_label_is_shown_on_reopening_the_dialog(self):
        win, bridge, radio, prefs = self.window(soapy_antenna_labels='{"Antenna B":"2 m vertical"}')
        d = self.open_radio_page(bridge, win, prefs)
        self.assertEqual(d.antenna_label_edits["Antenna B"].text(), "2 m vertical")
        i = d.antenna_combo.findData("Antenna B")
        self.assertEqual(d.antenna_combo.itemText(i), "Antenna B — 2 m vertical")
        d.close()


if __name__ == "__main__":
    unittest.main()
