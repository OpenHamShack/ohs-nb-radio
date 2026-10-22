"""How much of the radio's stream is arriving, said where the operator looks
(ohscore/engine.py Engine._stream_pct -> rxStreamPct; ohscore/ui/chrome.py
StatusStrip). On 17/10/2026 a Windows PC over a Tailscale relay got 37 %
of the Pluto's samples while the status bar said "1.2 MS/s".

Against tools/rx_storm.py's paced simulator, which loses samples as a
Pluto's DMA does when nobody reads it: a stalled link loses a known amount
and the share falls by that much. Nothing transmits."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib.util
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_radio

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_spec = importlib.util.spec_from_file_location(
    "rx_storm", Path(__file__).resolve().parent.parent / "tools" / "rx_storm.py")
rx_storm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx_storm)

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def pump(seconds, radio, feeds=()):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        radio.heartbeat()
        for f in feeds:
            f.drain()
        time.sleep(0.01)


class Share(unittest.TestCase):
    def test_a_stalled_link_shows_as_the_share_that_arrived(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        r = make_radio(tmp, device=rx_storm.paced_device(loop_s=2.0), vfo=10_489_700_000.0)
        r.start()
        self.addCleanup(r.stop)
        feeds = [r.subscribe(k, 64) for k in ("toast", "state", "wide", "zoom")]
        pump(3.0, r, feeds)
        self.assertEqual(r.state()["rxStreamPct"], 100.0)
        r.dev.stall(1.0)                  # 0.7 s more than the kernel buffers hold
        pump(5.0, r, feeds)               # the loss is known once the stream settles (rxprefetch window_s)
        lost_s = r.dev.lost / r.dev.fs
        self.assertGreater(lost_s, 0.5)
        pct = r.state()["rxStreamPct"]
        # 0.7 s of a ten-second window, give or take the window's edges.
        self.assertLess(pct, 95.0)
        self.assertGreater(pct, 85.0)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Strip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def painted(self, st):
        from PyQt6.QtGui import QPainter
        from ohscore.ui.chrome import StatusStrip
        strip = StatusStrip(type("B", (), {"st": st})())
        strip.resize(1400, 28)
        drawn = []
        real = QPainter.drawText

        def spy(painter, *a):
            drawn.append(next((x for x in a if isinstance(x, str)), ""))
            return real(painter, *a)
        with mock.patch.object(QPainter, "drawText", spy):
            strip.grab()
        return drawn

    def test_the_rate_or_the_share_arriving(self):
        st = {"running": True, "device": "pluto", "fs": 1_200_000.0, "cpu": 0.2}
        self.assertIn("1.2 MS/s", self.painted(dict(st, rxStreamPct=100.0)))
        self.assertIn("1.2 MS/s", self.painted(dict(st, rxStreamPct=97.0)))      # one lost block: not news
        got = self.painted(dict(st, rxStreamPct=37.2))
        self.assertIn("receiving 37 % of the stream", got)
        self.assertNotIn("1.2 MS/s", got)
        self.assertIn("1.2 MS/s", self.painted(st))                               # an engine without the key


if __name__ == "__main__":
    unittest.main()
