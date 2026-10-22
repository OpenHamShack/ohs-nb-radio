import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The filter bank's channels and sources keep their phase when their
frequency crosses a bin boundary (ohscore/dsp/bank.py). Before 06/10 each
crossing turned the signal by pi/4 at 1.2 MS/s - found because HSmodem's
carrier loop, on the multimedia beacon's channel, lost frames to it."""
import unittest

import numpy as np

from ohscore.dsp.bank import Analysis, Channel, Geometry, Source, Synthesis

FS = 1_200_000.0
EDGE = 248_475.0          # a bin boundary (bins are fs/N = 50 Hz)


def jumps(z: np.ndarray, tol: float = 0.05) -> float:
    d = np.diff(np.unwrap(np.angle(z)))
    return float(np.abs(d - np.median(d)).max())


class Channels(unittest.TestCase):
    def test_a_channel_crossing_a_bin_boundary_keeps_its_phase(self):
        g = Geometry(FS)
        an = Analysis(g)
        ch = Channel(g, g.decimation_for(12_000.0), cutoff=2_400.0)
        n = int(FS * 2)
        x = np.exp(2j * np.pi * (EDGE + 3.0) * np.arange(n) / FS).astype(np.complex64)
        out = []
        for i, b in enumerate(range(0, n, 4 * g.L)):
            X, starts = an.push(x[b:b + 4 * g.L])
            ch.set_freq(EDGE - 0.1 if i % 2 else EDGE + 0.1)
            out.append(ch.take(X, starts))
        y = np.concatenate(out)[2000:]
        self.assertLess(jumps(y), 0.01)

    def test_a_source_crossing_a_bin_boundary_keeps_its_phase(self):
        g = Geometry(FS)
        syn = Synthesis(g)
        d = g.decimation_for(12_000.0)
        src = Source(g, d)
        m = 4
        hop = m * g.L // d
        ys, fs_ = [], []
        for i in range(30):
            src.freq = EDGE - 0.1 if i % 2 else EDGE + 0.1
            t = np.arange(i * hop, (i + 1) * hop) / (FS / d)
            ys.append(syn.render(m, [(src, np.exp(2j * np.pi * 3.0 * t).astype(np.complex64))]))
            fs_.append(np.full(m * g.L, src.freq))
        y = np.concatenate(ys)
        f = np.concatenate(fs_)
        # Down again by an ideal mixer that follows the same frequency.
        z = (y * np.exp(-1j * np.cumsum(2 * np.pi * f / FS)))[50_000::d]
        self.assertLess(jumps(z), 0.01)


if __name__ == "__main__":
    unittest.main()
