"""Settings' Radio page, S-meter section (ohscore/ui/smeter.py
settings_section): on Radio the calibration table is server-side (the
engine's own `sMeterCal` setting), so the page shows every stored entry,
not only the current radio's row, and its offset field is read-only -
written only by Calibrate to…, through the engine, never typed by hand
(docs/SERVER-API.md "S-meter calibration")."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class SMeterPage(unittest.TestCase):
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

    def window(self):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.radio import Radio
        from ohsradio.ui import build
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI",
               "licenceClass": "foundation", "vfo": 145_650_000.0, "mode": "fm",
               "rxGainMode": "manual", "rxGain": 40.0}
        radio = Radio(cfg, persist=False, data_dir=self.tmp)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        self.wins.append((win, bridge))
        self.settle_until(lambda: radio.state().get("band"))
        bridge.st.update(radio.state())
        return win, bridge, radio, prefs

    def settle_until(self, cond, sec=5.0):
        import time
        end = time.monotonic() + sec
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def radio_page(self, bridge, win, prefs):
        from ohsradio.ui.settings import SettingsDialog
        return SettingsDialog(bridge, prefs, win, page=1)      # ("antenna", "Radio", "page_radio")

    def test_the_offset_field_is_server_side_and_read_only(self):
        win, bridge, radio, prefs = self.window()
        d = self.radio_page(bridge, win, prefs)
        self.assertTrue(d._smeter["server"])
        self.assertTrue(d._smeter["offset"].isReadOnly())
        d.close()

    def test_an_empty_table_says_so(self):
        from PyQt6.QtWidgets import QLabel
        win, bridge, radio, prefs = self.window()
        d = self.radio_page(bridge, win, prefs)
        texts = [w.text() for w in d.findChildren(QLabel)]
        self.assertTrue(any("No calibrations stored yet." in t for t in texts), texts)
        d.close()

    def test_calibrating_through_the_widget_writes_to_the_engine_not_prefs(self):
        win, bridge, radio, prefs = self.window()
        meter = win.rxcard.s
        self.assertIn("sMeterCal", meter._st())        # Radio's engine state carries the key
        from ohscore.smeter_cal import calibrate, clean_cal
        store = calibrate(meter._cal_source(), meter._st(), -42.6, -93.0)
        meter._write_cal(store)
        self.app.processEvents()
        self.assertTrue(clean_cal(radio.st.get("sMeterCal")))
        # Nothing landed in the window's own preferences for this app.
        self.assertEqual(prefs.get("sMeterCal") or {}, {})
        win.close()

    def test_forgetting_clears_the_engine_setting(self):
        win, bridge, radio, prefs = self.window()
        meter = win.rxcard.s
        from ohscore.smeter_cal import calibrate, clean_cal, forget
        meter._write_cal(calibrate(meter._cal_source(), meter._st(), -42.6, -93.0))
        self.app.processEvents()
        self.assertTrue(clean_cal(radio.st.get("sMeterCal")))
        meter._write_cal(forget(meter._cal_source(), meter._st()))
        self.app.processEvents()
        self.assertEqual(clean_cal(radio.st.get("sMeterCal")), {})
        win.close()


if __name__ == "__main__":
    unittest.main()
