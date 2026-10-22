import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""Sending a KG-STV picture from NB's window (ohsnb/ui/kgstvsend.py, on the
Beacon view's KG-STV page), in the real window against a real Radio on
the simulator: the dialog shows the picture as it will be received, each
quality's length against the time-out and the station's callsign line;
nothing keys until Send; Send retunes to KG-STV's frequency and keys
through the engine; the strip counts blocks from the over's seconds;
Halt and Escape stop it; a refusal is said in the dialog."""
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

from helpers import make_radio

ELSEWHERE = 10_489_700_000.0       # an SSB frequency: where the operator happens to be


def write_png(path, rgb):
    from ohscore.modes.sstv import _write_png
    _write_png(path, rgb)


def photo(h=360, w=640):
    """A 16:9 picture with its own detail, and red sides that a 4:3 cut
    takes off."""
    y, x = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = (x * 255 // w).astype(np.uint8)
    img[..., 1] = (y * 255 // h).astype(np.uint8)
    img[..., 2] = np.where(((x // 20) + (y // 20)) % 2, 200, 40).astype(np.uint8)
    img[:, :80] = (255, 0, 0)
    img[:, -80:] = (255, 0, 0)
    return img


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class SendPicture(unittest.TestCase):
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
        self.pic = os.path.join(self.tmp, "photo.png")
        write_png(self.pic, photo())

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
        cfg = dict(mmbDecode=False, midTextDecode=False, kgstvDecode=False, vfo=ELSEWHERE, mode="usb",
                   callsign="GM4BRI", locator="IO75RL", licenceClass="full", simUlErrorHz=0.0)
        cfg.update(over)
        radio = make_radio(self.tmp, **cfg)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        win.show_view("mmb")
        win.mmb_view.show_page("kgstv")
        self.pump(lambda: radio.running, 10)
        return win, bridge, radio

    def pump(self, until, timeout=60.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until():
                return True
        return False

    def dialog(self, win, path=None):
        dlg = win.mmb_view.send_picture(path or self.pic)
        self.app.processEvents()
        return dlg

    def test_the_dialog_shows_what_will_be_received_and_keys_nothing(self):
        win, bridge, radio = self.window()
        dlg = self.dialog(win)
        self.assertTrue(dlg.isVisible())
        # The picture cut to 4:3 (the red sides gone) and as a receiver
        # will paint it at the standard quality.
        self.assertEqual(dlg.picture.shape, (240, 320, 3))
        self.assertLess(int(dlg.picture[:, :, 0].min()), 200)
        self.assertEqual(dlg.scale(), 10)
        self.assertTrue(np.array_equal(dlg.preview.rgb, dlg.txs[10].preview()))
        # Each quality with its length on the air; all fit 300 s here.
        for q, b in dlg.quality_btns.items():
            self.assertRegex(b.text(), r"\d:\d\d$")
            self.assertTrue(b.isEnabled())
        self.assertEqual(dlg.call_label.text(), "GM4BRI IO75RL")
        self.assertIn("10489.6249", dlg.freq_std.text())
        self.assertIn("10489.7000", dlg.freq_here.text())
        self.assertTrue(dlg.freq_std.isChecked())
        self.assertTrue(dlg.send_btn.isEnabled())
        self.assertRegex(dlg.status.text(), r"300 blocks in \d:\d\d")
        # A finer quality shows its own preview, and the over is longer.
        dlg.quality_btns[8].setChecked(True)
        self.assertTrue(np.array_equal(dlg.preview.rgb, dlg.txs[8].preview()))
        self.assertGreater(dlg.txs[8].seconds, dlg.txs[10].seconds)
        # Open, chosen, previewed: nothing has keyed, nothing has retuned.
        self.pump(lambda: False, 0.5)
        self.assertFalse(radio.state()["keyed"])
        self.assertEqual(radio.state()["vfo"], ELSEWHERE)
        dlg.reject()
        self.pump(lambda: False, 0.3)
        self.assertFalse(radio.state()["keyed"])
        self.assertFalse(win.mmb_view.kgsend.isVisible())

    def test_send_retunes_keys_counts_blocks_and_halt_stops_it(self):
        from ohsnb.kgstvrx import DIAL
        win, bridge, radio = self.window()
        dlg = self.dialog(win)
        dlg.quality_btns[15].setChecked(True)
        tx = dlg.txs[15]
        dlg.send()
        self.assertFalse(dlg.isVisible())
        self.assertEqual(radio.state()["vfo"], DIAL)
        self.assertTrue(radio.state()["keyed"])
        strip = win.mmb_view.kgsend
        self.assertTrue(self.pump(lambda: radio.state()["txSeconds"] > 1.5 and "block" in strip.text.text(), 30),
                        (strip.text.text(), radio.state()["txSeconds"], radio.state()["keyed"],
                         radio.state()["txSource"], radio.state()["txOnAir"], bridge.st.get("txSource")))
        self.assertTrue(strip.isVisible())
        self.assertRegex(strip.text.text(), r"Sending GM4BRI IO75RL · block \d+ of 300 · \d:\d\d of \d:\d\d")
        n = int(strip.text.text().split("block ")[1].split(" ")[0])
        self.assertEqual(n, tx.blocks_sent(win.mmb_store.kg_sending["secs"]))
        self.assertTrue(strip.halt_btn.isVisible())
        strip.halt_btn.clicked.emit()
        self.assertFalse(radio.state()["keyed"])
        self.assertTrue(self.pump(lambda: "Stopped after block" in strip.text.text(), 5), strip.text.text())
        self.assertFalse(strip.halt_btn.isVisible())

    def test_escape_in_the_main_window_stops_it(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        win, bridge, radio = self.window()
        dlg = self.dialog(win)
        dlg.send()
        self.assertTrue(radio.state()["keyed"])
        self.pump(lambda: False, 0.3)
        win.activateWindow()
        target = win.focusWidget() or win.mmb_view
        QTest.keyClick(target, Qt.Key.Key_Escape)
        self.assertTrue(self.pump(lambda: not radio.state()["keyed"], 3))

    def test_qualities_longer_than_the_time_out_are_unavailable(self):
        win, bridge, radio = self.window()
        rng = np.random.default_rng(1)
        busy = os.path.join(self.tmp, "busy.png")
        write_png(busy, rng.integers(0, 256, (240, 320, 3), dtype=np.uint8))
        bridge.set(authorise=True, txTimeoutSec=200.0)
        dlg = self.dialog(win, busy)
        lengths = {q: tx.seconds for q, tx in dlg.txs.items()}
        for q, b in dlg.quality_btns.items():
            self.assertEqual(b.isEnabled(), lengths[q] <= 200.0, (q, lengths[q]))
        self.assertFalse(dlg.quality_btns[10].isEnabled())
        # It starts on the finest that fits.
        self.assertEqual(dlg.scale(), min(q for q in lengths if lengths[q] <= 200.0))
        self.assertTrue(dlg.send_btn.isEnabled())
        dlg.reject()
        bridge.set(authorise=True, txTimeoutSec=60.0)
        dlg = self.dialog(win, busy)
        self.assertFalse(dlg.send_btn.isEnabled())
        self.assertIn("time-out", dlg.status.text())
        dlg.send()
        self.assertFalse(radio.state()["keyed"])
        dlg.reject()

    def test_a_picture_coming_in_on_the_frequency_is_said(self):
        win, bridge, radio = self.window()
        dlg = self.dialog(win)
        bridge.st.update(kgstvState="receiving", kgstvCall="DG8RW JN69CV")
        dlg._enable()
        self.assertIn("DG8RW JN69CV is coming in", dlg.status.text())
        self.assertTrue(dlg.send_btn.isEnabled())          # said, not refused
        dlg.freq_here.setChecked(True)
        self.assertNotIn("coming in", dlg.status.text())
        dlg.reject()

    def test_no_callsign_no_send(self):
        win, bridge, radio = self.window(callsign="")
        dlg = self.dialog(win)
        self.assertFalse(dlg.send_btn.isEnabled())
        self.assertIn("callsign", dlg.status.text())
        self.assertIn("Settings › Station", dlg.call_label.text())
        dlg.send()
        self.assertFalse(radio.state()["keyed"])
        dlg.reject()

    def test_a_refusal_is_said_in_the_dialog_and_it_stays_open(self):
        # Sent where the transmitter is - the narrow digimode segment, too
        # narrow for KG-STV - the engine refuses before key-up.
        win, bridge, radio = self.window(vfo=10_489_560_000.0)
        dlg = self.dialog(win)
        dlg.freq_here.setChecked(True)
        dlg.send()
        self.assertFalse(radio.state()["keyed"])
        self.assertTrue(dlg.isVisible())
        self.assertIn("500", dlg.status.text())
        self.assertEqual(radio.state()["vfo"], 10_489_560_000.0)
        self.assertIsNone(win.mmb_store.kg_sending)
        dlg.reject()


if __name__ == "__main__":
    unittest.main()
