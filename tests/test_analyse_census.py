"""ohsnb.analyse_census.band_census: an occupied-run count per band-plan
segment, bucketed over time - behavioural, not textual: a steady tone
placed in one segment and nowhere else must show up counted in that
segment's buckets and nowhere in an empty one, from a small array built
directly (no file, no engine - the function reads raw IQ the same way
ohsnb.analyse's own wideband pass does)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohsnb import analyse_census, bandplan

FS = 1_200_000.0


def _segment_index(lo: float, hi: float) -> int:
    for i, (s_lo, s_hi, _label, _classes, _maxbw) in enumerate(bandplan.SEGMENTS):
        if s_lo == lo and s_hi == hi:
            return i
    raise KeyError((lo, hi))


class SteadyToneInOneSegment(unittest.TestCase):
    def setUp(self):
        self.dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
        cw_lo, cw_hi = bandplan._CW_LO, bandplan._CW_HI
        tone_abs = (cw_lo + cw_hi) / 2.0
        dur = 12.0
        n = int(dur * FS)
        t = np.arange(n) / FS
        rel = tone_abs - self.dc0
        rng = np.random.default_rng(3)
        noise = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        x = (0.3 * np.exp(2j * np.pi * rel * t) + noise).astype(np.complex64)
        self.view = np.stack([x.real, x.imag], axis=1).astype(np.float32)
        self.n = n
        self.caps = [{"core:sample_start": 0, "core:frequency": self.dc0}]
        self.info = {"lnb_lo_hz": None, "nominal_dc_flat": None}
        self.cw_i = _segment_index(cw_lo, cw_hi)

    def test_the_tone_is_counted_in_its_own_segment_and_not_elsewhere(self):
        r = analyse_census.band_census(self.view, 1.0, self.n, FS, self.caps, self.info, 0.0, [],
                                       bucket_s=12.0, fps=1.0)
        self.assertEqual(len(r["segments"]), len(bandplan.SEGMENTS))
        self.assertEqual(len(r["counts"]), len(bandplan.SEGMENTS))
        self.assertEqual(r["bucket_starts"], [0.0])
        cw_count = r["counts"][self.cw_i][0]
        self.assertGreater(cw_count, 0.5)       # the tone's own segment: an occupied run on most lines
        for i, row in enumerate(r["counts"]):
            if i == self.cw_i:
                continue
            # The "AMSAT-DL broadcast" and beacon segments (classes None,
            # 0-7.5 kHz wide) are a handful of bins wide - too few for
            # occupied() to be asked (band_census skips a segment with
            # under 5 bins) - those read exactly 0.0, as asserted here too.
            self.assertLess(row[0], 0.3, f"segment {i} ({bandplan.SEGMENTS[i][2]}) unexpectedly occupied")

    def test_bucketing_splits_a_tone_that_starts_half_way_through(self):
        # A second recording, silent for the first half and the same tone
        # for the second: the first bucket must read ~0, the second ~1.
        cw_lo, cw_hi = bandplan._CW_LO, bandplan._CW_HI
        tone_abs = (cw_lo + cw_hi) / 2.0
        dur = 16.0
        n = int(dur * FS)
        half = n // 2
        t = np.arange(n) / FS
        rel = tone_abs - self.dc0
        rng = np.random.default_rng(4)
        noise = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        x = noise.astype(np.complex64)
        x[half:] += (0.3 * np.exp(2j * np.pi * rel * t[half:])).astype(np.complex64)
        view = np.stack([x.real, x.imag], axis=1).astype(np.float32)
        r = analyse_census.band_census(view, 1.0, n, FS, self.caps, self.info, 0.0, [], bucket_s=8.0, fps=1.0)
        self.assertEqual(r["bucket_starts"], [0.0, 8.0])
        self.assertLess(r["counts"][self.cw_i][0], 0.3)
        self.assertGreater(r["counts"][self.cw_i][1], 0.5)


if __name__ == "__main__":
    unittest.main()
