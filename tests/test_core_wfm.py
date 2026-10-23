"""Wide FM (ohscore/dsp/wfm.py): a synthetic broadcast signal through the
demodulator - the tone it carries, its SNR, the de-emphasis curve, the mono
band flat to 15 kHz at 48 kHz, that nothing above the mono band (the stereo
pilot, L-R) reaches the audio, the decoders' 12 kHz, and the stereo hook."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import unittest

import numpy as np

from ohscore.dsp import wfm

RATE = 240_000.0
OUT = wfm.AUDIO_RATE          # 48 kHz since 23/10/2026


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


def tone_snr(a, hz, rate=OUT, top=15_000.0):
    """(frequency of the strongest bin, SNR dB of the tone against everything
    else in 100 Hz-`top`)."""
    w = np.hanning(len(a))
    A = np.abs(np.fft.rfft(a * w)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / rate)
    band = (f > 100) & (f < top)
    peak = f[band][int(np.argmax(A[band]))]
    near = band & (np.abs(f - hz) < 30)
    sig = A[near].sum()
    rest = A[band & ~near].sum()
    return peak, 10 * math.log10(sig / (rest + 1e-30))


def amplitude(a, hz, rate=OUT):
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
        a = run(d, (x + noise).astype(np.complex64))[24_000:]        # past the filters' start-up
        peak, snr = tone_snr(a, 1000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=3)
        # FM's improvement above threshold makes this far better than the
        # 30 dB CNR (72 dB measured); 55 is a floor that a broken
        # discriminator, or a filter folding the channel's noise in, misses.
        self.assertGreater(snr, 55.0)
        self.assertAlmostEqual(amplitude(a, 1000.0), wfm.LEVEL * 50 / 75, delta=0.02)

    def test_other_audio_frequencies_come_back_where_they_were_sent(self):
        # Treble at a broadcaster's levels: pre-emphasis lifts 14 kHz by
        # 13 dB, so a half-deviation tone there would over-deviate 2x.
        for hz, amp in ((300.0, 0.5), (2500.0, 0.5), (4500.0, 0.5), (10_000.0, 0.15), (14_000.0, 0.15)):
            d = wfm.WfmDemod(RATE, 50.0)
            a = run(d, broadcast(amp * np.sin(2 * np.pi * hz * self.t), tau_us=50.0))[24_000:]
            peak, snr = tone_snr(a, hz)
            self.assertAlmostEqual(peak, hz, delta=3, msg=hz)
            self.assertGreater(snr, 50.0, hz)

    def test_the_mono_band_is_flat_to_15_khz(self):
        # Pre-emphasised as broadcast, so de-emphasis gives each tone back
        # at its own level: what is left is the mono lowpass, flat to
        # 15 kHz. At 12 kHz (before 23/10/2026) 10 kHz was not there at all.
        for hz in (1000.0, 8000.0, 12_000.0, 15_000.0):
            d = wfm.WfmDemod(RATE, 50.0)
            a = run(d, broadcast(0.2 * np.sin(2 * np.pi * hz * self.t), tau_us=50.0))[24_000:]
            self.assertAlmostEqual(amplitude(a, hz), 0.2 * wfm.LEVEL, delta=0.2 * wfm.LEVEL * 0.03, msg=hz)

    def test_the_stereo_pilot_never_reaches_the_audio(self):
        # A 1 kHz tone plus the 19 kHz pilot at its usual 10 % of deviation:
        # mono audio carries the tone and nothing of the pilot, which is
        # inside 48 kHz audio's band and so has to be filtered, not folded.
        m = 0.4 * np.sin(2 * np.pi * 1000 * self.t) + 0.1 * np.sin(2 * np.pi * 19_000 * self.t)
        d = wfm.WfmDemod(RATE, 50.0)
        a = run(d, broadcast(m))[24_000:]
        self.assertLess(amplitude(a, 19_000.0), amplitude(a, 1000.0) * 1e-3)

    def test_nothing_of_l_minus_r_folds_into_the_audio(self):
        # The L-R subcarrier's sidebands sit at 23-53 kHz; at 48 kHz a
        # component at 38 kHz would fold to 10 kHz, one at 31 kHz to 17.
        m = 0.4 * np.sin(2 * np.pi * 1000 * self.t) + 0.2 * np.sin(2 * np.pi * 38_000 * self.t) \
            + 0.2 * np.sin(2 * np.pi * 31_000 * self.t)
        d = wfm.WfmDemod(RATE, 50.0)
        a = run(d, broadcast(m))[24_000:]
        tone = amplitude(a, 1000.0)
        for alias in (10_000.0, 17_000.0):
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
        self.assertEqual(len(a), len(self.t) // 5)          # 48 kHz
        self.assertEqual(a.dtype, np.float32)
        self.assertEqual(a.ndim, 1)
        self.assertEqual(d.channels, 1)

    def test_the_decoders_get_the_same_audio_at_12_khz(self):
        d = wfm.WfmDemod(RATE, 50.0)
        x = broadcast(0.5 * np.sin(2 * np.pi * 1000 * self.t), tau_us=50.0)
        dec = np.concatenate([d.for_decoders(d(x[i:i + 18_000])[0]) for i in range(0, len(x), 18_000)])
        self.assertEqual(len(dec), len(self.t) // 20)
        a = dec[6000:]
        peak, snr = tone_snr(a, 1000.0, rate=12_000.0, top=5000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=3)
        self.assertGreater(snr, 50.0)
        self.assertAlmostEqual(amplitude(a, 1000.0, rate=12_000.0), 0.5 * wfm.LEVEL, delta=0.01)


class DcBlocker(unittest.TestCase):
    def test_a_dc_step_dies_away_and_bass_stays(self):
        dc = wfm.DcBlocker(20.0, OUT)
        t = np.arange(int(OUT)) / OUT
        y = dc(0.3 + 0.2 * np.sin(2 * np.pi * 100 * t))
        tail = y[int(OUT * 0.5):]
        self.assertLess(abs(float(np.mean(tail))), 1e-3)                 # the step is gone
        self.assertAlmostEqual(amplitude(tail, 100.0), 0.2, delta=0.2 * 0.03)   # 100 Hz is not

    def test_blocks_of_any_length_give_the_same_answer(self):
        x = np.random.default_rng(1).standard_normal(20_000)
        whole = wfm.DcBlocker(20.0, OUT)(x)
        dc = wfm.DcBlocker(20.0, OUT)
        parts = np.concatenate([dc(c) for c in np.array_split(x, [7, 3600, 3601, 9000, 17_000])])
        np.testing.assert_allclose(parts, whole, atol=1e-5)


class StereoHook(unittest.TestCase):
    """Where shack_sdr's stereo decoder plugs in (wfm.py docstring): it is
    given the composite and, while it has the pilot, is what is heard."""

    class FakeStereo:
        """Mono from the composite in L, silence in R: shape, not quality."""

        def __init__(self, pilot):
            self.pilot = pilot
            self.inputs = 0

        def __call__(self, mpx):
            self.inputs += len(mpx)
            n = len(mpx) // 5
            return np.stack([mpx[::5][:n], np.zeros(n, np.float32)], axis=1)

    def test_with_the_pilot_it_is_heard_in_stereo(self):
        d = wfm.WfmDemod(RATE, 50.0)
        d.stereo = self.FakeStereo(pilot=True)
        x = broadcast(0.5 * np.sin(2 * np.pi * 1000 * np.arange(24_000) / RATE))
        a, _level = d(x)
        self.assertEqual(a.shape, (24_000 // 5, 2))
        self.assertEqual(d.stereo.inputs, 24_000)
        self.assertEqual(d.channels, 2)
        # The decoders still get 12 kHz mono from it.
        self.assertEqual(d.for_decoders(a).ndim, 1)

    def test_without_the_pilot_the_mono_path_is_heard(self):
        d = wfm.WfmDemod(RATE, 50.0)
        d.stereo = self.FakeStereo(pilot=False)
        a, _level = d(broadcast(np.zeros(24_000)))
        self.assertEqual((a.ndim, d.channels), (1, 1))


class Deemphasis(unittest.TestCase):
    """The receiver's de-emphasis against the analogue curve 1/(1 + j w tau):
    a flat (not pre-emphasised) tone comes back lowered by exactly it."""

    def response_db(self, tau_us, hz):
        t = np.arange(int(RATE * 1.0)) / RATE
        d = wfm.WfmDemod(RATE, tau_us)
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * hz * t)))[12_000:]
        return 20 * math.log10(amplitude(a, hz) / (0.5 * wfm.LEVEL))

    def test_50_and_75_us_follow_the_one_pole_curve(self):
        for tau in (50.0, 75.0):
            for hz in (200.0, 1000.0, 3000.0, 4500.0, 10_000.0, 14_000.0):
                want = -10 * math.log10(1 + (2 * math.pi * hz * tau * 1e-6) ** 2)
                self.assertAlmostEqual(self.response_db(tau, hz), want, delta=0.25, msg=(tau, hz))

    def test_75_us_cuts_the_treble_harder_than_50(self):
        self.assertLess(self.response_db(75.0, 3000.0), self.response_db(50.0, 3000.0) - 2.0)

    def test_the_time_constant_can_change_while_running(self):
        d = wfm.WfmDemod(RATE, 50.0)
        d.set_deemphasis(75.0)
        self.assertEqual(d.tau_us, 75.0)
        t = np.arange(int(RATE)) / RATE
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * 3000 * t)))[12_000:]
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
        a = run(d, broadcast(0.5 * np.sin(2 * np.pi * 1000 * t), rate=rate, tau_us=50.0))[12_000:]
        peak, snr = tone_snr(a, 1000.0)
        self.assertAlmostEqual(peak, 1000.0, delta=3)
        self.assertGreater(snr, 50.0)


if __name__ == "__main__":
    unittest.main()
