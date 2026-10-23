"""Wide FM (ohscore/dsp/wfm.py): a synthetic broadcast signal through the
demodulator - the tone it carries, its SNR, the de-emphasis curve, and that
nothing above the mono band (the stereo pilot) reaches the audio."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import unittest

import numpy as np

from ohscore.dsp import wfm

RATE = 240_000.0


def broadcast(audio, rate=RATE, deviation=wfm.DEVIATION, tau_us=None):
    """A WFM carrier at baseband modulated by `audio` (1.0 = full
    deviation), pre-emphasised with time constant `tau_us` if given: the
    exact inverse of the receiver's one-pole de-emphasis, so a broadcast
    tone comes out at its own level."""
    m = np.asarray(audio, np.float64)
    if tau_us is not None:
        a = math.exp(-1.0 / (tau_us * 1e-6 * rate))
        prev = np.concatenate([[0.0], m[:-1]])
        m = (m - a * prev) / (1 - a)
    return np.exp(1j * 2 * np.pi * deviation / rate * np.cumsum(m)).astype(np.complex64)


def run(demod, x, block=18_000):
    return np.concatenate([demod(x[i:i + block])[0] for i in range(0, len(x), block)])


def tone_snr(a, hz, rate=12_000.0):
    """(frequency of the strongest bin, SNR dB of the tone against everything
    else in 100 Hz-5 kHz)."""
    w = np.hanning(len(a))
    A = np.abs(np.fft.rfft(a * w)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / rate)
    band = (f > 100) & (f < 5000)
    peak = f[band][int(np.argmax(A[band]))]
    near = band & (np.abs(f - hz) < 30)
    sig = A[near].sum()
    rest = A[band & ~near].sum()
    return peak, 10 * math.log10(sig / (rest + 1e-30))


def amplitude(a, hz, rate=12_000.0):
    t = np.arange(len(a)) / rate
    return 2 * abs(np.mean(a * np.exp(-2j * np.pi * hz * t)))


class Demodulates(unittest.TestCase):
    def setUp(self):
        self.t = np.arange(int(RATE * 2)) / RATE
        self.rng = np.random.default_rng(3)

    def test_a_tone_at_known_deviation_comes_back_at_its_frequency_and_level(self):
        # 1 kHz at 50 kHz deviation (two thirds of full), pre-emphasised as a
        # broadcaster does, with noise at a 30 dB carrier-to-noise ratio in
        # the 240 kHz channel.
        x = broadcast(50 / 75 * np.sin(2 * np.pi * 1000 * self.t), tau_us=50.0)
        noise = ((self.rng.standard_normal(len(x)) + 1j * self.rng.standard_normal(len(x)))
                 * 10 ** (-30 / 20) / math.sqrt(2))
        d = wfm.WfmDemod(RATE, 50.0)
        a = run(d, (x + noise).astype(np.complex64))[6000:]          # past the filters' start-up
        peak, snr = tone_snr(a, 1000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=3)
        # FM's improvement above threshold makes this far better than the
        # 30 dB CNR (72 dB measured); 55 is a floor that a broken
        # discriminator, or a filter folding the channel's noise in, misses.
        self.assertGreater(snr, 55.0)
        self.assertAlmostEqual(amplitude(a, 1000.0), wfm.LEVEL * 50 / 75, delta=0.02)

    def test_other_audio_frequencies_come_back_where_they_were_sent(self):
        for hz in (300.0, 2500.0, 4500.0):
            d = wfm.WfmDemod(RATE, 50.0)
            a = run(d, broadcast(0.5 * np.sin(2 * np.pi * hz * self.t), tau_us=50.0))[6000:]
            peak, snr = tone_snr(a, hz)
            self.assertAlmostEqual(peak, hz, delta=3, msg=hz)
            self.assertGreater(snr, 50.0, hz)

    def test_the_stereo_pilot_never_reaches_the_audio(self):
        # A 1 kHz tone plus the 19 kHz pilot at its usual 10 % of deviation:
        # mono audio carries the tone and nothing of the pilot (it would
        # fold to 7 kHz at 12 kS/s, then alias again to 5 kHz; neither is there).
        m = 0.4 * np.sin(2 * np.pi * 1000 * self.t) + 0.1 * np.sin(2 * np.pi * 19_000 * self.t)
        d = wfm.WfmDemod(RATE, 50.0)
        a = run(d, broadcast(m))[6000:]
        tone = amplitude(a, 1000.0)
        for alias in (5000.0, 7000.0):
            self.assertLess(amplitude(a, alias), tone * 1e-3, alias)

    def test_the_composite_carries_what_stereo_and_rds_need(self):
        # composite() is the hook for stereo and RDS: the pilot is there,
        # at the channel rate, at its level.
        d = wfm.WfmDemod(RATE, 50.0)
        x = broadcast(0.1 * np.sin(2 * np.pi * 19_000 * self.t))
        mpx = np.concatenate([d.composite(c) for c in np.array_split(x, 7)])
        t = np.arange(len(mpx)) / RATE
        self.assertAlmostEqual(2 * abs(np.mean(mpx * np.exp(-2j * np.pi * 19_000 * t))), 0.1, delta=0.005)

    def test_audio_comes_out_at_the_audio_rate(self):
        d = wfm.WfmDemod(RATE, 50.0)
        a = run(d, broadcast(np.zeros(len(self.t))))
        self.assertEqual(len(a), len(self.t) // 20)
        self.assertEqual(a.dtype, np.float32)


class Deemphasis(unittest.TestCase):
    """The receiver's de-emphasis against the analogue curve 1/(1 + j w tau):
    a flat (not pre-emphasised) tone comes back lowered by exactly it."""

    def response_db(self, tau_us, hz):
        t = np.arange(int(RATE * 1.0)) / RATE
        d = wfm.WfmDemod(RATE, tau_us)
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * hz * t)))[3000:]
        return 20 * math.log10(amplitude(a, hz) / (0.5 * wfm.LEVEL))

    def test_50_and_75_us_follow_the_one_pole_curve(self):
        for tau in (50.0, 75.0):
            for hz in (200.0, 1000.0, 3000.0, 4500.0):
                want = -10 * math.log10(1 + (2 * math.pi * hz * tau * 1e-6) ** 2)
                self.assertAlmostEqual(self.response_db(tau, hz), want, delta=0.25, msg=(tau, hz))

    def test_75_us_cuts_the_treble_harder_than_50(self):
        self.assertLess(self.response_db(75.0, 3000.0), self.response_db(50.0, 3000.0) - 2.0)

    def test_the_time_constant_can_change_while_running(self):
        d = wfm.WfmDemod(RATE, 50.0)
        d.set_deemphasis(75.0)
        self.assertEqual(d.tau_us, 75.0)
        t = np.arange(int(RATE)) / RATE
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * 3000 * t)))[3000:]
        want = -10 * math.log10(1 + (2 * math.pi * 3000 * 75e-6) ** 2)
        self.assertAlmostEqual(20 * math.log10(amplitude(a, 3000.0) / (0.5 * wfm.LEVEL)), want, delta=0.25)


class Rates(unittest.TestCase):
    def test_which_channel_rates_hold_a_station(self):
        self.assertTrue(wfm.can_receive(240_000.0))      # 1.2 MS/s / 5, 2.4 MS/s / 10
        self.assertTrue(wfm.can_receive(384_000.0))      # a Hermes-Lite 2 at its top rate
        self.assertFalse(wfm.can_receive(192_000.0))     # nor its default
        self.assertFalse(wfm.can_receive(48_000.0))
        with self.assertRaises(ValueError):
            wfm.WfmDemod(192_000.0)

    def test_a_384_ks_channel_demodulates_too(self):
        rate = 384_000.0
        t = np.arange(int(rate)) / rate
        d = wfm.WfmDemod(rate, 50.0)
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * 1000 * t), rate=rate, tau_us=50.0))[3000:]
        peak, snr = tone_snr(a, 1000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=3)
        self.assertGreater(snr, 50.0)


if __name__ == "__main__":
    unittest.main()
