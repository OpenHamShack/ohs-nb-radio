import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The HSmodem panel (ohscore/ui/panels/hsmodem.py) in NB's real window on
the simulator: it is the panel the mode shows, its speed is the engine's,
a picture is reduced as HSmodem's GUI reduces one, Send keys through the
engine (the simulator: nothing radiates) with progress shown, Stop halts,
and what a station sends lands in the list and the preview."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio, sim_seconds, wait_rx_lock
from ohscore.modes import hsmodem as hs

CARD = Path(__file__).resolve().parents[1] / "ohsnb" / "devices" / "mmb-testcard.jpg"


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class HsmodemPanel(unittest.TestCase):
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
        over.setdefault("callsign", "G4AAA")
        radio = make_radio(self.tmp, mode="hsmodem", vfo=10_489_620_000.0, **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.pump(radio, until=lambda: radio.state()["running"])
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

    def test_mode_shows_the_panel_and_its_speed_is_the_engines(self):
        from ohscore.ui.panels.hsmodem import HsmodemPanel as P
        win, bridge, radio = self.window()
        self.assertIsInstance(win.panel, P)
        p = win.panel
        self.assertEqual(p.speed.currentData(), 4410)
        p.speed.setCurrentIndex(p.speed.findData(7200))
        p.speed.activated.emit(p.speed.currentIndex())
        self.pump(radio, until=lambda: radio.state()["hsSpeed"] == 7200)
        self.assertEqual(radio.state()["hsSpeed"], 7200)
        # ... and the engine's receiver follows (a new decoder at that speed).
        self.pump(radio, until=lambda: getattr(radio.decoder, "speed", 0) == 7200)
        self.assertEqual(radio.decoder.speed, 7200)
        # Set elsewhere (Settings, another window), the combo follows.
        bridge.set(hsSpeed=2400)
        self.pump(radio, 0.3)
        self.assertEqual(p.speed.currentData(), 2400)

    def test_a_picture_is_reduced_as_hsmodem_reduces_one(self):
        from PyQt6.QtGui import QColor, QImage, QPainter
        from ohscore.ui.panels.hsmodem import QUALITIES
        win, bridge, radio = self.window()
        p = win.panel
        # A big, busy picture: a camera's would be bigger still. Filled 8x8
        # blocks, not single coloured dots on an unset (black) image: a lone
        # bright pixel surrounded by black is the one thing a JPEG encoder
        # and Qt's smooth downscale both handle least predictably, so the
        # compressed size swung by ~1000 bytes run to run - enough to clear
        # 22_500 occasionally once this test stopped skipping (no ohsdigi
        # built, so it never ran at all before).
        img = QImage(1600, 1200, QImage.Format.Format_RGB888)
        painter = QPainter(img)
        for y in range(0, 1200, 8):
            for x in range(0, 1600, 8):
                painter.fillRect(x, y, 8, 8, QColor((x * 7) % 256, (y * 5) % 256, (x + y) % 256))
        painter.end()
        f = Path(self.tmp) / "big.png"
        img.save(str(f))
        for res, budget in (("640x480", 22_500), ("320x240", 11_250)):
            p.res.setCurrentIndex(p.res.findData(res))
            p.qual.setCurrentIndex(p.qual.findData("medium"))
            self.assertTrue(p.set_picture(str(f)))
            c = p.chosen
            self.assertLessEqual(len(c["data"]), budget)
            self.assertEqual(c["data"][:2], b"\xff\xd8")          # a JPEG
            self.assertEqual((c["dims"].width(), c["dims"].height()), tuple(int(v) for v in res.split("x")))
            self.assertEqual(c["name"], "big.jpg")
            self.assertIn("JPEG", p.what.text())
            self.assertIn("at 4410 bit/s", p.what.text())
        self.assertEqual([k for k, _t, _n in QUALITIES], ["low", "medium", "high", "veryhigh"])

    def test_send_keys_shows_progress_and_stop_halts(self):
        win, bridge, radio = self.window()
        self.assertTrue(wait_rx_lock(radio))
        p = win.panel
        self.assertTrue(p.set_file(str(CARD)))
        self.assertIn("about", p.what.text())
        p.send()
        self.assertTrue(radio.state()["keyed"])
        self.assertTrue(self.pump(radio, until=lambda: p.tx_bar.value() > 100, timeout=60))
        p.stop()
        self.pump(radio, until=lambda: not radio.state()["keyed"])
        self.assertFalse(radio.state()["keyed"])
        self.assertEqual(p.tx_bar.value(), 0)

    def test_typed_text_goes_as_a_message(self):
        win, bridge, radio = self.window()
        self.assertTrue(wait_rx_lock(radio))
        p = win.panel
        p.msg.setPlainText("Hello from G4AAA")
        self.assertEqual(p.message(), {"text": "Hello from G4AAA"})
        self.assertIn("Message, 16 characters", p.what.text())
        p.send()
        self.assertTrue(radio.state()["keyed"])
        radio.halt()

    def test_no_callsign_says_why_and_does_not_key(self):
        win, bridge, radio = self.window(callsign="")
        toasts = []
        bridge.toast.connect(toasts.append)
        p = win.panel
        p.msg.setPlainText("hello")
        p.send()
        self.assertFalse(radio.state()["keyed"])
        self.assertTrue(any("callsign" in t["text"] for t in toasts), toasts)

    def test_what_a_station_sends_is_listed_and_shown(self):
        win, bridge, radio = self.window()
        p = win.panel
        events = []
        dec = hs.Decoder(events.append, speed=4410, folder=radio.hsmodem_dir())
        import numpy as np
        rng = np.random.default_rng(2)
        for msg in ({"name": "station.jpg", "data": CARD.read_bytes()}, {"text": "Hello from G4XYZ, 73"}):
            a = hs.Encoder().render(speed=4410, callsign="G4XYZ", locator="IO91", **msg)
            a = np.concatenate([np.zeros(3000, np.float32), a, np.zeros(9000, np.float32)])
            a = (a + 0.01 * rng.standard_normal(len(a))).astype(np.float32)
            for i in range(0, len(a), 1200):
                dec.feed(a[i:i + 1200], i / 12000.0)
        for e in events:
            bridge.decoded.emit(dict(e, t=time.time()))
        # The decoder's last word (before the window's own decoder, hearing
        # only the simulator, says "searching" again).
        self.assertIn("in sync", p.status.text())
        self.assertIn("4410 bit/s", p.status.text())
        self.app.processEvents()
        names = [p.list.item(i).text().split("\n")[0] for i in range(p.list.count())]
        self.assertEqual(names[:2], ["message.txt", "station.jpg"])
        self.assertIn("from G4XYZ IO91", p.list.item(1).text())
        # The last one in is shown: the message.
        self.assertIs(p.view.currentWidget(), p.text)
        self.assertEqual(p.text.toPlainText(), "Hello from G4XYZ, 73")
        p._show_item(p.list.item(1))
        self.assertIs(p.view.currentWidget(), p.pic)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Words(unittest.TestCase):
    """What the panel says, which needs no modem: run where ohsdigi is not
    built as well."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_the_waiting_picture_speaks_of_hsmodem_not_sstv(self):
        # Mac test 17/10/2026, finding 24: "Tune to an SSTV signal" here.
        from unittest import mock
        from PyQt6.QtGui import QPainter
        from ohscore.ui.bridge import Bridge
        from ohscore.ui.panels.hsmodem import HsmodemPanel as P
        from ohscore.ui.panels.sstv import Picture
        from ohscore.ui.prefs import Prefs
        from ohsnb.ui.face import Qo100Face
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        radio = make_radio(tmp, mode="hsmodem")
        bridge = Bridge(radio, face=Qo100Face())
        self.addCleanup(lambda: [radio.unsubscribe(f) for f in bridge.feeds.values()])
        panel = P(bridge, Prefs(Path(tmp) / "ui.json"))
        panel.resize(900, 400)
        drawn = []
        real = QPainter.drawText

        def spy(painter, *a):
            drawn.append(next((x for x in a if isinstance(x, str)), ""))
            return real(painter, *a)
        with mock.patch.object(QPainter, "drawText", spy):
            panel.pic.grab()
            hs_words = list(drawn)
            drawn.clear()
            Picture().grab()                  # SSTV's own, as it was
        self.assertTrue(any("HSmodem" in t for t in hs_words), hs_words)
        self.assertFalse(any("SSTV" in t for t in hs_words), hs_words)
        self.assertTrue(any("SSTV" in t for t in drawn), drawn)
