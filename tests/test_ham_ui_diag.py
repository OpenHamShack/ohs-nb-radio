"""OpenHamShack HAM's diagnostics in the window: the Help menu's entries, the
chip dialog a 2 m pick on an AD9363 Pluto opens, Check radio…, the AD9364
fix from consent to result (password prompt included), and saving a
report. The window runs on the band simulator; the Pluto is the pretend
one in tests/pluto_fakes.py. Offscreen Qt; nothing reaches a real radio."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtGui import QAction
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ham_helpers import make_radio
from pluto_fakes import Pluto, fixer
from ohsradio import bands


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Diagnostics(unittest.TestCase):
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
        # Find would scan the network for real radios: not in a test.
        from ohsradio import diagnostics
        self.no_find = mock.patch.object(diagnostics, "discovery", return_value=["Pluto: none found"])
        self.no_find.start()

    def tearDown(self):
        self.no_find.stop()
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
        from ohsradio import config
        from ohsradio.ui import build
        radio = make_radio(**over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.settle(0.6)
        return win, bridge, radio

    def settle(self, sec, until=None):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            if until is not None and until():
                return True
            time.sleep(0.01)
        return until() if until is not None else True

    def as_ad9363_pluto(self, radio):
        # The simulator stands in for the radio; only what the chip check
        # asks of a device is changed.
        radio.dev.kind = "pluto"
        radio.dev.identity = "ad9363"
        radio.dev.uri = "ip:192.168.2.1"
        radio.dev.rx_range = radio.dev.tx_range = (325e6, 3.8e9)

    def test_clicking_the_greyed_2m_button_explains_and_offers_the_fix(self):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest

        from ohsradio.ui.diagnostics import ChipModeDialog
        win, _bridge, radio = self.window()
        radio.band("70cm")
        self.as_ad9363_pluto(radio)
        st, why = win.bandbar._status(bands.BY_NAME["2m"])
        self.assertEqual(st, "off")
        self.assertIn("AD9364", why)
        r = next(rect for rect, kind, key in win.bandbar.cells if key == "2m")
        QTest.mouseClick(win.bandbar, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()),
                                                                             int(r.center().y())))
        self.settle(0.2)
        self.assertIsInstance(win.dialog, ChipModeDialog)
        self.assertEqual(radio.state()["band"], "70cm")

    def test_help_menu_offers_check_radio_and_the_report(self):
        win, _bridge, _radio = self.window()
        texts = [a.text() for a in win.findChildren(QAction)]
        self.assertIn("Check radio…", texts)
        self.assertIn("Save diagnostics…", texts)

    def test_2m_on_an_ad9363_pluto_opens_the_chip_dialog_and_stays(self):
        from ohsradio.ui.diagnostics import ChipModeDialog
        win, _bridge, radio = self.window()
        radio.band("70cm")
        self.as_ad9363_pluto(radio)
        win.pick_band("2m")
        self.settle(0.1)
        self.assertIsInstance(win.dialog, ChipModeDialog)
        self.assertIn("This Pluto is running as an AD9363, which tunes 325 MHz–3.8 GHz. 2 m needs the AD9364 "
                      "setting.", win.dialog.text)
        self.assertEqual({"apply", "report", "close"}, set(win.dialog.extra))
        self.assertEqual(radio.state()["band"], "70cm")
        win.dialog.reject()
        win.pick_band("23cm")                          # reachable: no dialog, the band changes
        self.settle(0.1)
        self.assertEqual(radio.state()["band"], "23cm")

    def test_starting_on_2m_as_an_ad9363_says_so(self):
        from ohsradio.ui.diagnostics import ChipModeDialog
        win, _bridge, radio = self.window()
        self.as_ad9363_pluto(radio)
        if radio.state()["band"] != "2m":
            radio.band("2m")
        win.after_start("")
        self.assertIsInstance(win.dialog, ChipModeDialog)

    def test_a_device_that_will_not_open_gets_the_report_button(self):
        from ohsradio.ui.diagnostics import DeviceErrorDialog
        win, _bridge, _radio = self.window()
        win.after_start("Could not open the pluto device: No Pluto at ip:192.0.2.1")
        self.assertIsInstance(win.dialog, DeviceErrorDialog)
        self.assertIn("report", win.dialog.extra)
        self.assertIn("check", win.dialog.extra)

    def test_check_radio_lists_identity_and_bands_and_offers_the_fix(self):
        win, _bridge, _radio = self.window(licenceClass="intermediate")
        pluto = Pluto(fw="v0.38")
        win.identify = pluto.identify
        d = win.check_radio()
        self.assertTrue(self.settle(3.0, until=lambda: d.results))
        by = {c.label: c for c in d.results}
        self.assertEqual(by["Chip identity"].level, "warn")
        self.assertEqual(by["2 m"].level, "fail")
        self.assertEqual(by["70 cm"].level, "ok")
        self.assertFalse(d.apply_b.isHidden())
        self.assertTrue(d.undo_b.isHidden())

    def run_fix(self, win, pluto, password=None):
        win.make_fixer = lambda uri, progress: fixer(pluto, uri, progress=progress)
        flow = win.apply_ad9364()
        self.assertTrue(self.settle(3.0, until=lambda: flow.dialog is not None))
        return flow

    def test_the_fix_shows_the_commands_runs_them_after_consent_and_reconnects(self):
        win, bridge, radio = self.window()
        pluto = Pluto(fw="v0.38")
        flow = self.run_fix(win, pluto)
        self.assertIn("fw_setenv compatible ad9364", flow.dialog.box.toPlainText())
        self.assertIn("reboot", flow.dialog.box.toPlainText())
        self.assertNotIn("fw_setenv compatible ad9364", pluto.commands)    # nothing before consent
        flow.dialog.extra["ok"].clicked.emit()
        self.assertTrue(self.settle(5.0, until=lambda: flow.finished))
        self.assertTrue(flow.result.ok, flow.result.message)
        self.assertIn("fw_setenv compatible ad9364", pluto.commands)
        self.assertEqual(pluto.reboots, 1)
        self.assertTrue(radio.state()["running"])                       # the radio was started again

    def test_a_refused_default_password_asks_once_and_is_not_kept(self):
        win, _bridge, _radio = self.window()
        pluto = Pluto(password="pw2")
        flow = self.run_fix(win, pluto)
        flow.dialog.extra["ok"].clicked.emit()
        self.assertTrue(self.settle(5.0, until=lambda: flow.password_dialog is not None))
        pd = flow.password_dialog
        pd.edit.setText("pw2")
        pd.extra["ok"].clicked.emit()
        self.assertTrue(self.settle(5.0, until=lambda: flow.finished))
        self.assertTrue(flow.result.ok, flow.result.message)
        self.assertEqual(pluto.logins, ["analog", "pw2"])
        self.assertEqual(pd.edit.text(), "")
        self.assertNotIn("pw2", repr(vars(flow)))

    def test_unsupported_firmware_shows_manual_steps_and_runs_nothing(self):
        win, _bridge, _radio = self.window()
        pluto = Pluto(fw="tezuka-v0.3.21")
        flow = self.run_fix(win, pluto)
        self.assertEqual(flow.dialog.windowTitle(), "Change it by hand")
        self.assertIn("fw_setenv compatible ad9364", flow.dialog.box.toPlainText())
        self.assertNotIn("ok", flow.dialog.extra)
        self.assertEqual(pluto.logins, [])

    def test_save_diagnostics_adds_hams_findings_and_writes_a_zip(self):
        from ohscore.ui.diagnostics import DiagnosticsDialog
        win, _bridge, _radio = self.window()
        job = win.save_diagnostics()
        self.assertTrue(self.settle(15.0, until=lambda: job.finished))
        self.assertEqual(job.error, "")
        self.assertIsInstance(win.dialog, DiagnosticsDialog)
        target = Path(self.tmp) / "report.zip"
        self.assertTrue(win.dialog.save_to(target))
        with zipfile.ZipFile(target) as z:
            report = z.read("report.txt").decode()
        self.assertIn("Pluto: none found", report)
        self.assertIn("callsign: GM4BRI", report)
        win.dialog.reject()

if __name__ == "__main__":
    unittest.main()
