import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The middle beacon's text on NB's Beacon view (ohsnb/ui/mmbview.py, the
"Middle beacon" page), in the real window against a real Radio on the
simulator: blocks come from the engine's "midtext" feed - first as the
simulator's own middle beacon decodes, then as items placed on the feed -
and from the data folder at start."""
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio, sim_seconds


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class MiddleBeaconPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
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

    def window(self, **over):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp, mmbDecode=False, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        win.show_view("mmb")
        win.mmb_view.show_page("midtext")
        return win, bridge, radio

    def pump(self, radio, until, timeout=60.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until():
                return True
        return False

    def test_the_simulators_middle_beacon_fills_the_page(self):
        win, bridge, radio = self.window()
        v = win.mmb_view
        ok = self.pump(radio, until=lambda: "OPENHAMSHACK NB SIMULATOR" in v.mtext.toPlainText()
                       and "receiving" in v.status.text(), timeout=180)
        self.assertTrue(ok, (v.mtext.toPlainText()[:200], v.status.text(), sim_seconds(radio)))
        self.assertIn("10489.750", v.status.text())
        self.assertRegex(v.status.text(), r"blocks [1-9]\d* ok")

    def test_blocks_are_shown_in_type_order_latest_of_each(self):
        win, bridge, radio = self.window(midTextDecode=False)
        v = win.mmb_view
        t = time.time()
        radio._publish("midtext", {"type": "M", "text": "M first M", "lines": [], "t": t})
        radio._publish("midtext", {"type": "K", "text": "K old", "lines": [], "t": t})
        radio._publish("midtext", {"type": "K", "text": "K new", "lines": [], "t": t + 1})
        self.pump(radio, until=lambda: "K new" in v.mtext.toPlainText(), timeout=10)
        text = v.mtext.toPlainText()
        self.assertNotIn("K old", text)
        self.assertLess(text.index("K new"), text.index("M first M"))
        self.assertIn("off", v.status.text())
        # The other pages keep the multimedia beacon's own status line.
        v.show_page("bulletins")
        self.assertNotIn("Middle beacon text", v.status.text())

    def test_saved_blocks_are_there_at_start(self):
        folder = os.path.join(self.tmp, "midbeacon")
        os.makedirs(folder)
        with open(os.path.join(folder, "L.txt"), "w") as f:
            f.write("L from yesterday\n")
        win, bridge, radio = self.window(midTextDecode=False)
        self.assertIn("L from yesterday", win.mmb_view.mtext.toPlainText())
        self.assertIn("── L", win.mmb_view.mtext.toPlainText())

    def test_content_survives_a_theme_change(self):
        win, bridge, radio = self.window(midTextDecode=False)
        radio._publish("midtext", {"type": "N", "text": "N kept", "lines": [], "t": time.time()})
        self.pump(radio, until=lambda: "N kept" in win.mmb_view.mtext.toPlainText(), timeout=10)
        win.set_theme("light")
        win.show_view("mmb")
        win.mmb_view.show_page("midtext")
        self.assertIn("N kept", win.mmb_view.mtext.toPlainText())
        win.set_theme("dark")


if __name__ == "__main__":
    unittest.main()
