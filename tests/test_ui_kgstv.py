import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""KG-STV pictures on NB's Beacon view (ohsnb/ui/mmbview.py, the "KG-STV"
page), in the real window against a real Radio on the simulator: the
picture builds from the engine's "kgstv" feed - first as the simulator's
own KG-STV station decodes, then from items placed on the feed - and the
pictures kept in the data folder are there at start."""
import os
import shutil
import sys
import tempfile
import time
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio, sim_seconds


def write_png(path, colour):
    from ohscore.modes.sstv import _write_png
    _write_png(path, np.full((240, 320, 3), colour, np.uint8))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class KgStvPage(unittest.TestCase):
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
        radio = make_radio(self.tmp, mmbDecode=False, midTextDecode=False, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        win.show_view("mmb")
        win.mmb_view.show_page("kgstv")
        return win, bridge, radio

    def pump(self, until, timeout=60.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until():
                return True
        return False

    def test_the_simulators_station_builds_a_picture(self):
        win, bridge, radio = self.window()
        v = win.mmb_view
        ok = self.pump(until=lambda: "OPENHAMSHACK-SIM" in v.kgcap.text() and "receiving" in v.status.text()
                       and int(win.mmb_store.kg["have"].sum()) >= 20, timeout=180)
        self.assertTrue(ok, (v.kgcap.text(), v.status.text(), sim_seconds(radio)))
        self.assertIn("MSK/NORM", v.kgcap.text())
        self.assertRegex(v.kgcap.text(), r" \d+/300 blocks")
        self.assertIn("10489.6249", v.status.text())
        self.assertIsNotNone(v.kgpic.img)

    def test_blocks_from_the_feed_and_the_finished_picture_kept(self):
        win, bridge, radio = self.window(kgstvDecode=False)
        v = win.mmb_view
        t = time.time()
        red = np.zeros((16, 16, 3), np.uint8)
        red[..., 0] = 200
        radio._publish("kgstv", {"kind": "start", "id": 7, "call": "G0ABC", "t": t})
        for x in range(3):
            radio._publish("kgstv", {"kind": "block", "id": 7, "x": x, "y": 2, "rgb": red.tobytes(), "call": "G0ABC",
                                     "blocks": x + 1, "mode": "MSK/NORM", "t": t})
        self.pump(until=lambda: "3/300" in v.kgcap.text(), timeout=10)
        self.assertIn("G0ABC · MSK/NORM", v.kgcap.text())
        self.assertIn("receiving", v.kgcap.text())
        img = v.kgpic.img
        self.assertEqual(img.pixelColor(20, 40).red(), 200)      # block (1, 2)
        self.assertNotEqual(img.pixelColor(100, 100).red(), 200)  # nothing there yet
        path = os.path.join(self.tmp, "20261008_120000_G0ABC.png")
        write_png(path, (200, 0, 0))
        radio._publish("kgstv", {"kind": "done", "id": 7, "call": "G0ABC", "why": "end", "blocks": 3, "bad": 0,
                                 "mode": "MSK/NORM", "path": path, "t": t})
        self.pump(until=lambda: v.kglist.count() == 1, timeout=10)
        self.assertIn("complete", v.kgcap.text())
        self.assertEqual(v.kglist.item(0).data(256), path)        # Qt.ItemDataRole.UserRole
        self.assertIn("off", v.status.text())
        # The other pages keep the multimedia beacon's own status line.
        v.show_page("bulletins")
        self.assertNotIn("KG-STV", v.status.text())

    def test_pictures_kept_are_there_at_start(self):
        folder = os.path.join(self.tmp, "kgstv")
        os.makedirs(folder)
        write_png(os.path.join(folder, "20261007_171316_DL4CQ.png"), (0, 0, 90))
        win, bridge, radio = self.window(kgstvDecode=False)
        v = win.mmb_view
        self.assertEqual(v.kglist.count(), 1)
        self.assertTrue(v.kglist.item(0).text().startswith("DL4CQ"))

    def test_content_survives_a_theme_change(self):
        win, bridge, radio = self.window(kgstvDecode=False)
        radio._publish("kgstv", {"kind": "block", "id": 3, "x": 0, "y": 0, "rgb": bytes(768), "call": "M0KEPT",
                                 "blocks": 1, "mode": "MSK/NORM", "t": time.time()})
        self.pump(until=lambda: "M0KEPT" in win.mmb_view.kgcap.text(), timeout=10)
        win.set_theme("light")
        win.show_view("mmb")
        win.mmb_view.show_page("kgstv")
        self.assertIn("M0KEPT", win.mmb_view.kgcap.text())
        win.set_theme("dark")


if __name__ == "__main__":
    unittest.main()
