"""NB's multimedia beacon view (ohsnb/ui/mmbview.py), in the real window
against a real Radio on the simulator: its content arrives from the
engine's "mmb" feed - first as the simulator's own beacon decodes, then as
items placed on the feed - and the operator's controls do what they say."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
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
from ohscore.modes import hsmodem as hs


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class BeaconView(unittest.TestCase):
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
        radio = make_radio(self.tmp, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def pump(self, radio, sim_s=0.0, until=None, timeout=60.0):
        start = sim_seconds(radio)
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until is not None and until():
                return True
            if until is None and sim_seconds(radio) - start >= sim_s:
                return True
        return False

    def put(self, radio, **ev):
        radio._publish("mmb", {"mode": "mmb", "t": time.time(), **ev})

    @unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
    def test_the_simulators_beacon_fills_the_view(self):
        win, bridge, radio = self.window()
        win.show_view("mmb")
        store = win.mmb_store
        ok = self.pump(radio, until=lambda: store.bulletins and store.pictures and len(store.spots) >= 5)
        self.assertTrue(ok, (len(store.bulletins), len(store.pictures), len(store.spots)))
        v = win.mmb_view
        self.assertGreaterEqual(v.blist.count(), 1)
        self.assertIn("OPENHAMSHACK NB SIMULATOR", v.btext.toPlainText())
        self.assertGreaterEqual(v.table.rowCount(), 5)
        self.assertEqual(v.plist.count(), 1)
        self.assertIn("receiving", v.status.text())

    def test_spots_tables_pictures_and_scope_labels(self):
        win, bridge, radio = self.window(mmbDecode=False)
        win.show_view("mmb")
        v = win.mmb_view
        before = len([lab for lab in win.wide.labels if lab["kind"] == "dx"])
        self.put(radio, kind="dx", reporter="DL1ABC", qrg_khz=10489540.0, dxcall="G4XYZ", comment="FT8", utc="1200Z",
                 loc="JO31")
        self.put(radio, kind="dx", reporter="DL1ABC", qrg_khz=14074.0, dxcall="OH8ZZ", comment="FT8", utc="1201Z",
                 loc="")
        self.put(radio, kind="dx", reporter="DL1ABC", qrg_khz=14074.0, dxcall="OH8ZZ", comment="FT8", utc="1201Z",
                 loc="")          # a repeat: one row
        self.put(radio, kind="bulletin", name="amsat_9.blt", text="Hello\n", data=b"Hello\n", path="")
        jpg = (win.mmb_store.folder.parent / "x.jpg")
        from PyQt6.QtGui import QImage
        img = QImage(64, 48, QImage.Format.Format_RGB888)
        img.fill(0x3366CC)
        img.save(str(jpg), "JPG")
        self.put(radio, kind="image", name="pic.jpg", data=jpg.read_bytes(), path="")
        self.put(radio, kind="nbspec", values=np.arange(275, dtype=np.uint8) % 64, start=10_489_475_000.0,
                 step=2000.0)
        self.pump(radio, until=lambda: v.table.rowCount() == 2 and v.plist.count() == 1, timeout=10)
        self.assertEqual(v.table.rowCount(), 2)
        self.assertEqual(v.table.item(0, 1).text(), "OH8ZZ")        # newest first
        self.assertEqual(v.btext.toPlainText(), "Hello\n")
        self.assertEqual(v.plist.count(), 1)
        self.assertIsNotNone(v.nbspec.ev)
        # Only the QO-100 spot is a label on the wide scope, at its frequency.
        dx = [lab for lab in win.wide.labels if lab["kind"] == "dx"]
        self.assertEqual(len(dx) - before, 1)
        self.assertAlmostEqual(dx[-1]["f"], 10_489_540_000.0)
        # Switched off, a new spot is not.
        v.spots_on.set_on(False, emit=True)
        self.put(radio, kind="dx", reporter="F5KLM", qrg_khz=10489700.0, dxcall="EA4QRP", comment="SSB",
                 utc="1202Z", loc="")
        self.pump(radio, until=lambda: v.table.rowCount() == 3, timeout=10)
        self.assertEqual(len([lab for lab in win.wide.labels if lab["kind"] == "dx"]) - before, 1)
        # Double-clicking a QO-100 spot tunes to it; an HF one does nothing.
        rows = {v.table.item(r, 1).text(): r for r in range(v.table.rowCount())}
        v.table.cellDoubleClicked.emit(rows["EA4QRP"], 1)
        self.pump(radio, until=lambda: abs(radio.state()["vfo"] - 10_489_700_000.0) < 1, timeout=10)
        self.assertAlmostEqual(radio.state()["vfo"], 10_489_700_000.0)
        v.table.cellDoubleClicked.emit(rows["OH8ZZ"], 1)
        self.pump(radio, sim_s=0.2)
        self.assertAlmostEqual(radio.state()["vfo"], 10_489_700_000.0)

    def test_content_survives_a_theme_change(self):
        win, bridge, radio = self.window(mmbDecode=False)
        self.put(radio, kind="bulletin", name="a.blt", text="kept\n", data=b"kept\n", path="")
        self.pump(radio, until=lambda: win.mmb_store.bulletins, timeout=10)
        old = win.mmb_view
        win.set_theme("light")
        self.assertIsNot(win.mmb_view, old)
        win.show_view("mmb")
        self.assertEqual(win.mmb_view.btext.toPlainText(), "kept\n")
        # The old view no longer listens: since 17/10/2026 it is deleted
        # with the old window before the new one is built (set_theme), not
        # left for the event loop; a new bulletin refreshes the new one.
        from PyQt6 import sip
        self.assertTrue(sip.isdeleted(old))
        self.put(radio, kind="bulletin", name="b.blt", text="new\n", data=b"new\n", path="")
        self.pump(radio, until=lambda: win.mmb_view.blist.count() == 2, timeout=10)
        win.set_theme("dark")

    def test_saved_files_are_there_at_start(self):
        folder = os.path.join(self.tmp, "mmbeacon")
        os.makedirs(folder)
        with open(os.path.join(folder, "amsat_1.blt"), "w") as f:
            f.write("from yesterday\n")
        win, bridge, radio = self.window(mmbDecode=False)
        win.show_view("mmb")
        self.assertEqual(win.mmb_view.btext.toPlainText(), "from yesterday\n")
        self.assertIn("off", win.mmb_view.status.text())


class Clock(unittest.TestCase):
    def test_lists_say_utc_whatever_the_computers_zone(self):
        # Mac test 17/10/2026, finding 19: KG-STV pictures stamped 17:09 local
        # beside a chat line at 16:14 UTC.
        from ohsnb.ui import mmbview
        was = os.environ.get("TZ")
        self.addCleanup(time.tzset)
        self.addCleanup(lambda: os.environ.__setitem__("TZ", was) if was is not None else os.environ.pop("TZ", None))
        os.environ["TZ"] = "Asia/Kolkata"            # UTC+5:30, so a local stamp cannot pass for UTC
        time.tzset()
        t = 1_760_717_340.0                          # 17 Oct 2025 16:09:00 UTC
        self.assertEqual(mmbview.utc_stamp(t), "17 Oct 16:09 UTC")
        self.assertEqual(mmbview.ago(t, now=t + 3 * 3600), "16:09 UTC")


if __name__ == "__main__":
    unittest.main()
