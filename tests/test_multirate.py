"""The decimator and interpolator the Pluto runs when its firmware refuses
the AD9361's FIR (ohscore/dsp/multirate.py)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.dsp.multirate import Decimator, Interpolator


def tone(f, rate, n, amp=1.0):
    return (amp * np.exp(2j * np.pi * f * np.arange(n) / rate)).astype(np.complex64)


def level_db(x, f, rate):
    """Amplitude (dB re 1) of the component of x at f, by projection."""
    a = np.mean(x * np.exp(-2j * np.pi * f * np.arange(len(x)) / rate))
    return 20 * np.log10(abs(a) + 1e-15)


def in_blocks(fn, x, sizes):
    out, i, k = [], 0, 0
    while i < len(x):
        n = sizes[k % len(sizes)]
        out.append(fn(x[i:i + n]))
        i, k = i + n, k + 1
    return np.concatenate(out)


def worst_spur_db(y, rate, f, exclude_hz=5_000.0):
    """Highest spectral line other than the wanted one, dB below it
    (4-term Blackman-Harris window: sidelobes 92 dB down, below what is
    being measured)."""
    n = len(y)
    t = 2 * np.pi * np.arange(n) / n
    w = 0.35875 - 0.48829 * np.cos(t) + 0.14128 * np.cos(2 * t) - 0.01168 * np.cos(3 * t)
    Y = np.abs(np.fft.fft(y * w))
    fr = np.fft.fftfreq(n, 1 / rate)
    want = Y[np.abs(fr - f) < exclude_hz].max()
    other = Y[np.abs(fr - f) >= exclude_hz].max()
    return 20 * np.log10(want / other)


class Decimation(unittest.TestCase):
    # The engine's two rates: 1.2 MS/s from a 2.4 MS/s radio (M=2), 600 kS/s
    # from 2.4 MS/s (M=4).
    CASES = [(1_200_000.0, 2), (600_000.0, 4)]

    def test_in_band_tone_keeps_frequency_and_amplitude(self):
        for fs, m in self.CASES:
            hw = fs * m
            # The transponder is +-250 kHz around DC (radio.RX_CENTRE_DL);
            # test well past it, to the filter's flat edge.
            for f in (0.0, 3_500.0, -250_000.0, 0.40 * fs, -0.42 * fs):
                with self.subTest(fs=fs, f=f):
                    d = Decimator(m)
                    y = in_blocks(d, tone(f, hw, int(hw * 0.2), 0.5), [9_001, 18_000, 3])[2000:]
                    self.assertAlmostEqual(level_db(y, f, fs), 20 * np.log10(0.5), delta=0.01)
                    # and nothing else: the tone is the whole signal
                    resid = y - 0.5 * np.exp(2j * np.pi * f * (np.arange(len(y)) + 2000) / fs
                                             - 2j * np.pi * f * d.delay / hw)
                    self.assertLess(np.abs(resid).max(), 1e-3)

    def test_out_of_band_tone_that_would_alias_is_rejected(self):
        for fs, m in self.CASES:
            hw = fs * m
            # 0.58 fs aliases onto -0.42 fs, the edge of what we keep; 0.9 fs
            # onto -0.1 fs, the middle of the transponder.
            for f in (0.58 * fs, -0.6 * fs, 0.9 * fs, -fs):
                with self.subTest(fs=fs, f=f):
                    alias = (f + fs / 2) % fs - fs / 2
                    y = Decimator(m)(tone(f, hw, int(hw * 0.2)))[2000:]
                    self.assertLess(level_db(y, alias, fs), -85.0)

    def test_block_boundaries_are_seamless(self):
        # Streaming in awkward pieces (odd sizes, smaller than the filter,
        # not multiples of M) must give exactly the one-shot result.
        rng = np.random.default_rng(3)
        x = (rng.standard_normal(60_000) + 1j * rng.standard_normal(60_000)).astype(np.complex64)
        for m in (2, 4):
            with self.subTest(m=m):
                whole = Decimator(m)(x)
                parts = in_blocks(Decimator(m), x, [1, 7, 333, 5_000, 12_345])
                self.assertEqual(len(whole), len(x) // m)
                self.assertEqual(len(parts), len(whole))
                np.testing.assert_allclose(parts, whole, atol=2e-5)


class Interpolation(unittest.TestCase):
    def test_tx_image_is_well_suppressed(self):
        # What reaches the satellite: a tone at +400 kHz in the engine's
        # 1.2 MS/s, interpolated to the radio's 2.4 MS/s. Zero-stuffing makes
        # an image at 400 - 1200 = -800 kHz; the TX NCO may reach 0.40 fs
        # (radio.TX_USABLE), 480 kHz, whose image is at -720 kHz. Any line
        # other than the wanted one must be at least 80 dB down (the
        # requirement is 50; this guards the margin).
        for fs, m, f in [(1_200_000.0, 2, 400_000.0), (1_200_000.0, 2, 480_000.0),
                         (1_200_000.0, 2, -480_000.0), (600_000.0, 4, 240_000.0)]:
            with self.subTest(fs=fs, f=f):
                hw = fs * m
                it = Interpolator(m)
                y = in_blocks(it, tone(f, fs, int(fs * 0.25), 0.9), [90_000, 4_097, 1])[4_000:4_000 + 2 ** 17]
                self.assertGreater(worst_spur_db(y, hw, f), 80.0)
                self.assertAlmostEqual(level_db(y, f, hw), 20 * np.log10(0.9), delta=0.01)

    def test_block_boundaries_are_seamless(self):
        rng = np.random.default_rng(4)
        x = (rng.standard_normal(30_000) + 1j * rng.standard_normal(30_000)).astype(np.complex64)
        for m in (2, 4):
            with self.subTest(m=m):
                whole = Interpolator(m)(x)
                parts = in_blocks(Interpolator(m), x, [1, 5, 999, 7_000])
                self.assertEqual(len(whole), m * len(x))
                np.testing.assert_allclose(parts, whole, atol=2e-5)

    def test_round_trip_is_a_pure_delay(self):
        # Interpolate then decimate: the signal comes back unchanged, late by
        # the two filters' group delays - the figure Pluto.tx_latency() adds.
        fs, m = 1_200_000.0, 2
        f = 123_000.0
        x = tone(f, fs, 60_000, 0.7)
        it, d = Interpolator(m), Decimator(m)
        y = d(it(x))
        lag = (it.delay + d.delay) / m           # in low-rate samples
        self.assertEqual(lag, int(lag))
        np.testing.assert_allclose(y[2000 + int(lag):], x[2000:len(x) - int(lag)], atol=1e-3)


if __name__ == "__main__":
    unittest.main()
