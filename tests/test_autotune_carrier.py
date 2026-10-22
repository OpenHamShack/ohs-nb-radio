"""Auto-tune's leaked-carrier assist (ohscore/dsp/autotune.py leaked_carrier,
_assist): a steady line under a voice, where its carrier would be, lands
the dial on the line exactly when the voice's harmonics fit there too; a
line the harmonics do not vouch for, one inside the voice, one that comes
and goes or has a rival, and a line with no voice are never taken."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.dsp import autotune as at

RATE = 12_000.0


def voice(seed, carrier, snr_db=10.0, seconds=8.0, sideband="usb"):
    """The simulator's voice, its carrier `carrier` Hz from the dial, and
    the noise's standard deviation per sample (so lines can be put in at a
    known level over it)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    z = sg.voice(rng, seconds + 1.0)[:n].astype(np.complex128)
    if sideband == "lsb":
        z = np.conj(z)
    x = z * np.exp(2j * np.pi * carrier * np.arange(n) / RATE)
    ps = np.mean(np.abs(z[np.abs(z) > 0]) ** 2)
    sigma = np.sqrt(ps / 10 ** (snr_db / 10) * RATE / 2400 / 2)
    w = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    return x + w * sigma, sigma * np.sqrt(2)


def tone(freq, amp, n, start=0, stop=None):
    t = np.arange(n) / RATE
    y = amp * np.exp(2j * np.pi * freq * t + 0.7j)
    y[:start] = 0
    if stop is not None:
        y[stop:] = 0
    return y


class Finds(unittest.TestCase):
    def test_a_steady_line_is_found_to_a_fraction_of_a_hertz(self):
        rng = np.random.default_rng(1)
        n = int(8 * RATE)
        noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
        line = at.leaked_carrier(noise + tone(-312.4, 0.2, n), -500.0, -100.0)
        self.assertIsNotNone(line)
        self.assertLess(abs(line[0] + 312.4), 0.3)
        self.assertGreater(line[1], at.LINE_DB)

    def test_not_a_line_that_comes_and_goes(self):
        # Strong for the first two seconds, then gone: averaged over eight
        # it still stands out, but not in the second four.
        rng = np.random.default_rng(2)
        n = int(8 * RATE)
        noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
        y = noise + tone(-312.4, 1.0, n, stop=int(2 * RATE))
        self.assertIsNotNone(at.leaked_carrier(y[:int(4 * RATE)], -500.0, -100.0))
        self.assertIsNone(at.leaked_carrier(y, -500.0, -100.0))

    def test_not_one_of_two_lines_alike(self):
        rng = np.random.default_rng(3)
        n = int(8 * RATE)
        noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
        y = noise + tone(-312.4, 0.2, n) + tone(-190.0, 0.19, n)
        self.assertIsNone(at.leaked_carrier(y, -500.0, -100.0))

    def test_nothing_in_noise(self):
        for seed in range(5):
            rng = np.random.default_rng(10 + seed)
            n = int(12 * RATE)
            noise = rng.standard_normal(n) + 1j * rng.standard_normal(n)
            self.assertIsNone(at.leaked_carrier(noise, -500.0, -100.0))


class Assists(unittest.TestCase):
    def test_a_leaking_voice_lands_on_its_carrier(self):
        for seed, sb, carrier in ((21, "usb", 45.0), (22, "lsb", -60.0), (23, "usb", -180.0)):
            with self.subTest(sb=sb, carrier=carrier):
                x, s = voice(seed, carrier, sideband=sb)
                x = x + tone(carrier, 0.3 * s, len(x))
                r = at.listen(x, sb)
                self.assertTrue(r.ok, r.why)
                self.assertLess(abs(r.offset - carrier), 1.0)
                self.assertEqual(r.details.get("how"), "line")

    def test_a_tone_the_harmonics_do_not_vouch_for_is_not_taken(self):
        # A steady tone under the voice, 70 Hz below its carrier - where a
        # carrier could be, but the voice's comb does not fit there.
        for seed in (31, 32, 33):
            with self.subTest(seed=seed):
                x, s = voice(seed, 45.0)
                x = x + tone(45.0 - 70.0, 0.3 * s, len(x))
                r = at.listen(x, "usb")
                if r.ok:
                    self.assertLess(abs(r.offset - 45.0), 10.0, r)
                    self.assertNotEqual(r.details.get("how"), "line")

    def test_a_line_inside_the_voice_is_not_its_carrier(self):
        x, s = voice(41, 45.0)
        x = x + tone(45.0 + 300.0 + 150.0, 0.5 * s, len(x))
        r = at.listen(x, "usb")
        if r.ok:
            self.assertLess(abs(r.offset - 45.0), 10.0, r)
        self.assertNotIn("line", r.details or {})

    def test_a_carrier_without_a_voice_is_still_refused(self):
        rng = np.random.default_rng(51)
        n = int(8 * RATE)
        y = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1e-2 + tone(-200.0, 0.2, n)
        r = at.listen(y, "usb")
        self.assertFalse(r.ok)


class TheVoicesBottomIsNotItsCarrier(unittest.TestCase):
    def test_a_line_with_voice_starting_just_above_it_is_not_trusted(self):
        # A steady line, the comb fitting on it as well as anywhere: taken
        # when the voice starts 100 Hz above it, not when it starts 55 Hz
        # above it (a filter passes from 100-300 Hz; that line is the
        # bottom of the voice, or something else).
        rng = np.random.default_rng(61)
        n = int(8 * RATE)
        iq = rng.standard_normal(n) + 1j * rng.standard_normal(n) + tone(-200.0, 0.3, n)
        d = np.arange(-150.0, 250.5, 0.5)
        total = np.exp(-((d - 0.0) / 4.0) ** 2) + np.exp(-((d - 120.0) / 4.0) ** 2)

        def verdict(band):
            r = {"why": "", "delta": 3.0, "spread": 0.2, "agree": 0.4, "landscape": (d, total)}
            return at._assist(r, iq, -200.0, 1.0, band)

        far = verdict((-100.0, 2500.0))
        self.assertEqual(far.get("how"), "line")
        self.assertAlmostEqual(far["delta"], 0.0, delta=0.5)
        near = verdict((-145.0, 2500.0))
        self.assertNotIn("line", near)
        self.assertNotIn("how", near)
        self.assertEqual(near["delta"], 3.0)

    def test_a_line_never_settles_what_the_comb_could_not(self):
        # Two offsets a pitch apart fit equally and the comb refused; a
        # steady line sits on one of them. The refusal stands.
        rng = np.random.default_rng(62)
        n = int(8 * RATE)
        iq = rng.standard_normal(n) + 1j * rng.standard_normal(n) + tone(-200.0, 0.3, n)
        d = np.arange(-150.0, 250.5, 0.5)
        total = np.exp(-((d - 0.0) / 4.0) ** 2) + np.exp(-((d - 120.0) / 4.0) ** 2)
        r = {"why": "two offsets fit almost equally", "delta": 120.0, "spread": 0.2, "agree": 0.4,
             "landscape": (d, total)}
        r = at._assist(r, iq, -200.0, 1.0, (-100.0, 2500.0))
        self.assertEqual(r["why"], "two offsets fit almost equally")
        self.assertIn("line", r)


if __name__ == "__main__":
    unittest.main()
