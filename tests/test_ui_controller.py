"""Settings › Controller (ohscore/ui/controller.py), driven as an operator
would on Qt's offscreen platform against shack_client's reference
controller over loopback HTTP: open the page from either app's Settings,
type the address and the account, pair, see it say so, unpair and keep
the log. The password never outlives the attempt."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ham_helpers import close, make_radio
from ohscore import shacklibs


class ControllerPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        shacklibs.client()
        from shack_client.testing import ReferenceController
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.ctl = ReferenceController(Path(self.tmp) / "controller.db", name="GM4BRI")
        self.url = self.ctl.serve()
        self.addCleanup(self.ctl.close)

    def dialog(self):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.ui import build
        from ohsradio.ui.settings import SettingsDialog
        radio = make_radio()
        self.addCleanup(close, radio)
        self.addCleanup(lambda: radio.station.close())
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        self.addCleanup(bridge.stop)
        self.addCleanup(win.close)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Controller"))
        self.addCleanup(d.close)
        from ohscore.ui.controller import ControllerPage as Page
        page = d.stack.currentWidget().findChild(Page)
        self.assertIsNotNone(page)
        # Closing the dialog hides the page but leaves its 2 s refresh
        # timer running; stopped first, it cannot fire in a later test
        # against this test's closed station and removed folder, which
        # raised in the slot and so aborted the whole interpreter (PyQt6).
        self.addCleanup(page.timer.stop)
        return page, radio

    def wait(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_pair_and_unpair_from_settings(self):
        page, radio = self.dialog()
        radio.log_qso("g4xyz", rf=144_300_000.0, mode="usb", t=1_790_000_000)
        self.assertIn("Not paired", page.state.text())
        self.assertFalse(page.unpair_btn.isEnabled())
        page.address.setText(self.url)
        page.user.setText("brian")
        page.password.setText("pw")
        page.pair()
        self.assertTrue(self.wait(lambda: "Paired with GM4BRI" in page.result.text()), page.result.text())
        self.assertEqual(page.password.text(), "")
        self.assertIn("Paired with GM4BRI", page.state.text())
        self.assertTrue(page.unpair_btn.isEnabled())
        self.assertEqual(len(self.ctl.records()), 1)
        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.unpair()
        self.assertIn("Not paired", page.state.text())
        self.assertEqual(len(radio.log_entries()), 1)

    def test_a_wrong_password_says_so_and_stays_unpaired(self):
        page, _radio = self.dialog()
        page.address.setText(self.url)
        page.user.setText("brian")
        page.password.setText("wrong")
        page.pair()
        self.assertTrue(self.wait(lambda: page.pair_btn.isEnabled() and page.result.text() != "Pairing…"))
        self.assertNotIn("Paired with", page.result.text())
        self.assertIn("Not paired", page.state.text())

    def test_nothing_typed_is_explained_not_sent(self):
        page, _radio = self.dialog()
        page.pair()
        self.assertIn("address", page.result.text())
        self.assertEqual(self.ctl.requests, [])


if __name__ == "__main__":
    unittest.main()
