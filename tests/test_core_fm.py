"""Narrowband FM (ohscore/dsp/fm.py): demodulator, squelch, CTCSS, modulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.dsp import fm
from ohscore.dsp.mod import AmMod

RATE = 24_000.0


def noise(rng, n, sigma):
    return (sigma * (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)).astype(np.complex64)


def run(demod, x, block=1800):
    return np.concatenate([demod(x[i:i + block])[0] for i in range(0, len(x), block)])


def peak_hz(a, rate=12_000.0):
    A = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    return np.fft.rfftfreq(len(a), 1 / rate)[int(np.argmax(A))]


class Demod(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(5)
        self.t = np.arange(int(RATE * 3)) / RATE

    def test_tone_through_and_squelch_open_on_a_signal(self):
        x = fm.modulate(0.5 * np.sin(2 * np.pi * 1000 * self.t), RATE, 2500, ctcss=88.5)
        d = fm.FmDemod(RATE, 2500)
        d.configure(2500, 0.5, 0.0)
        a = run(d, 0.1 * x + noise(self.rng, len(x), 0.01))
        self.assertAlmostEqual(peak_hz(a[12_000:]), 1000.0, delta=5)
        self.assertTrue(d.open)
        self.assertEqual(d.tone, 88.5)

    def test_noise_alone_keeps_the_squelch_shut_and_silent(self):
        d = fm.FmDemod(RATE, 2500)
        d.configure(2500, 0.5, 0.0)
        a = run(d, noise(self.rng, len(self.t), 0.01))
        self.assertFalse(d.open)
        self.assertLess(float(np.sqrt(np.mean(a[6000:] ** 2))), 1e-3)
        self.assertEqual(d.tone, 0.0)

    def test_squelch_level_zero_is_open(self):
        d = fm.FmDemod(RATE, 2500)
        d.configure(2500, 0.0, 0.0)
        run(d, noise(self.rng, len(self.t), 0.01))
        self.assertTrue(d.open)

    def test_every_tone_of_the_50_is_recognised(self):
        for tone in fm.TONES:
            x = fm.modulate(0.3 * np.sin(2 * np.pi * 700 * self.t), RATE, 2500, ctcss=tone)
            d = fm.FmDemod(RATE, 2500)
            d.configure(2500, 0.5, 0.0)
            run(d, 0.1 * x + noise(self.rng, len(x), 0.003))
            self.assertEqual(d.tone, tone, tone)

    def test_tone_squelch_passes_only_its_tone(self):
        x = fm.modulate(0.5 * np.sin(2 * np.pi * 1000 * self.t), RATE, 2500, ctcss=103.5)
        for want, audible in ((103.5, True), (94.8, False)):
            d = fm.FmDemod(RATE, 2500)
            d.configure(2500, 0.5, want)
            a = run(d, 0.1 * x)
            rms = float(np.sqrt(np.mean(a[-12_000:] ** 2)))
            self.assertEqual(rms > 0.01, audible, (want, rms))


class Mod(unittest.TestCase):
    def test_voice_with_ctcss_round_trip(self):
        m = fm.FmMod(RATE)
        m.configure(2500, 103.5, 0.12, 0.0, True)
        au = (0.3 * np.sin(2 * np.pi * 800 * np.arange(36_000) / 12_000)).astype(np.float32)
        bb = np.concatenate([m(au[i:i + 900]) for i in range(0, len(au), 900)])
        self.assertEqual(len(bb), 72_000)
        self.assertTrue(np.allclose(np.abs(bb), 1.0, atol=1e-4))     # constant envelope
        d = fm.FmDemod(RATE, 2500)
        d.configure(2500, 0.5, 0.0)
        out = run(d, bb)
        self.assertAlmostEqual(peak_hz(out[12_000:]), 800.0, delta=5)
        self.assertEqual(d.tone, 103.5)

    def test_occupied_bandwidth_of_full_deviation_voice_fits_12k5(self):
        rng = np.random.default_rng(2)
        m = fm.FmMod(RATE)
        m.configure(2500, 88.5, 0.12, 20.0, True)          # loud: driven into the clipper
        au = rng.standard_normal(48_000).astype(np.float32)
        bb = np.concatenate([m(au[i:i + 900]) for i in range(0, len(au), 900)])
        P = np.abs(np.fft.fftshift(np.fft.fft(bb))) ** 2
        f = np.fft.fftshift(np.fft.fftfreq(len(bb), 1 / RATE))
        c = np.cumsum(P) / P.sum()
        lo, hi = f[np.searchsorted(c, 0.005)], f[np.searchsorted(c, 0.995)]
        self.assertLess(hi - lo, 11_000.0)

    def test_toneburst(self):
        m = fm.FmMod(RATE)
        m.configure(2500, 0.0, 0.12, 0.0, False)
        m.toneburst(0.5)
        bb = np.concatenate([m(np.zeros(900, np.float32)) for _ in range(10)])
        a = fm.discriminate(bb[:12_000], RATE, 2500)
        A = np.abs(np.fft.rfft(a))
        self.assertAlmostEqual(np.fft.rfftfreq(len(a), 1 / RATE)[int(np.argmax(A))], 1750.0, delta=3)
        tail = fm.discriminate(bb[-6000:], RATE, 2500)
        self.assertLess(float(np.std(tail)), 0.01)            # burst over: plain carrier

    def test_tone_names(self):
        self.assertEqual(fm.tone_name(103.5), "G 103.5")
        self.assertEqual(fm.tone_name(123.0), "123.0")
        self.assertEqual(fm.tone_name(0.0), "off")
        self.assertEqual(len(fm.TONES), 50)


class Am(unittest.TestCase):
    def test_envelope_never_overmodulates(self):
        m = AmMod()
        m.configure(2700.0, 20.0, True)
        rng = np.random.default_rng(1)
        z = np.concatenate([m(rng.standard_normal(900).astype(np.float32)) for _ in range(40)])
        env = np.abs(z)
        self.assertLessEqual(float(env.max()), 0.951)
        self.assertGreaterEqual(float(env.min()), 0.049)


if __name__ == "__main__":
    unittest.main()
