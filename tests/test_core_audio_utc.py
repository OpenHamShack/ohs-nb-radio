"""Decoder timestamps in real time: contiguous whatever the arrival jitter,
and the simulators' UTC anchored where their pacing starts. Both were why
FT8 decoded nothing from a simulated band in real time (and decoded fine
faster than real time)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import time
import unittest

import numpy as np

from ohscore.dsp.bank import Geometry
from ohscore.engine import AUDIO_RATE, Engine


class Stamps(unittest.TestCase):
    def setUp(self):
        self.e = Engine.__new__(Engine)          # only _audio_utc's own state is needed
        self.e.dev = type("Dev", (), {"realtime": True})()
        self.e.geo = Geometry(1_200_000.0)
        self.e.rx_samples = 0

    def stamps(self, jitter, blocks=200, stall_at=None):
        rng = np.random.default_rng(1)
        out = []
        t0 = 1_791_000_000.0
        n_dev, n_aud = 90_000, 900
        for k in range(blocks):
            self.e.rx_samples += n_dev
            now = t0 + self.e.rx_samples / self.e.geo.fs + abs(rng.normal(0, jitter))
            if stall_at is not None and k >= stall_at:
                now += 1.0
            out.append(self.e._audio_utc(now, n_aud))
        return np.array(out)

    def test_jittery_arrival_still_gives_contiguous_blocks(self):
        t = self.stamps(jitter=0.004)
        steps = np.diff(t[20:])
        # Each block starts exactly where the last ended, to well under a sample.
        self.assertLess(float(np.max(np.abs(steps - 900 / AUDIO_RATE))), 0.5 / AUDIO_RATE)

    def test_a_stall_re_anchors(self):
        t = self.stamps(jitter=0.001, stall_at=100)
        self.assertGreater(t[100] - t[99], 0.9)
        self.assertLess(abs(np.diff(t[101:]) - 900 / AUDIO_RATE).max(), 0.5 / AUDIO_RATE)


class SimEpoch(unittest.TestCase):
    def test_realtime_sim_utc_starts_at_the_first_read(self):
        from ohsnb.devices.sim import SimDevice
        s = SimDevice({"simSeed": 1, "simSignals": False, "simRealtime": True}, 1_200_000.0)
        s.open()
        time.sleep(0.4)
        s.read(18_000)
        # t_epoch + samples produced is "now", not 0.4 s ago.
        self.assertLess(abs((s.t_epoch + s.n / s.fs) - time.time()), 0.15)
        s.close()


if __name__ == "__main__":
    unittest.main()
