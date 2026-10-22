"""Best audio (ohscore/dsp/autoaudio.py): what it measures of a station,
and what its rules choose from that - NR off for a strong signal and on
for a weak one, the filter round the speech, the blanker for impulses,
the AGC for weak and impulsive signals - each with its reason."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.dsp import autoaudio as aa
from ohscore.dsp.demod import NoiseBlanker

RATE = 12_000.0
N = int(aa.CAPTURE_SECONDS * RATE)


def station(snr_db, sideband="usb", seed=77):
    """The simulator's voice, carrier on the dial, in white noise `snr_db`
    under it (2.4 kHz)."""
    rng = np.random.default_rng(seed)
    z = sg.voice(rng, 6.0)[:N].astype(np.complex128)
    if sideband == "lsb":
        z = np.conj(z)
    ps = np.mean(np.abs(z) ** 2)
    w = (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * np.sqrt(ps / 10 ** (snr_db / 10) * RATE / 2400 / 2)
    return (z + w).astype(np.complex64)


class Measures(unittest.TestCase):
    def test_snr_follows_the_signal(self):
        got = [aa.measure(station(s), "usb", 0.0).snr for s in (6.0, 12.0, 24.0)]
        self.assertTrue(got[0] < got[1] < got[2], got)
        # Speech peaks over noise: a little above the mean-power SNR.
        for want, have in zip((6.0, 12.0, 24.0), got):
            self.assertLess(abs(have - want - 3.0), 3.0, got)

    def test_band_is_the_speech_not_its_skirt(self):
        for sideband in ("usb", "lsb"):
            with self.subTest(sideband=sideband):
                m = aa.measure(station(30.0, sideband), sideband, 0.0)
                self.assertLess(abs(m.band[0] - 300.0), 60.0, m.band)
                self.assertTrue(2000.0 < m.band[1] < 2800.0, m.band)

    def test_nothing_there(self):
        rng = np.random.default_rng(1)
        x = ((rng.standard_normal(N) + 1j * rng.standard_normal(N)) * 0.01).astype(np.complex64)
        c = aa.best_audio(x, "usb", 0.0)
        self.assertFalse(c.ok)
        self.assertIn("nothing", c.why)

    def test_counts_impulses_as_the_blanker_sees_them(self):
        rng = np.random.default_rng(2)
        x = ((rng.standard_normal(90_000) + 1j * rng.standard_normal(90_000)) * 0.01).astype(np.complex64)
        self.assertEqual(aa.count_impulses(x, 8.0), 0)
        at = rng.choice(np.arange(100, 89_000, 50), 12, replace=False)
        for i in at:
            x[i:i + 3] = 1.0
        self.assertEqual(aa.count_impulses(x, 8.0), 12)
        # The same samples the noise blanker zeroes.
        self.assertTrue(np.all(NoiseBlanker(8.0)(x)[at] == 0))


class Chooses(unittest.TestCase):
    def reasons(self, c):
        return dict(c.reasons)

    def test_strong_signal_nr_off(self):
        c = aa.best_audio(station(30.0), "usb", 0.0)
        self.assertTrue(c.ok)
        self.assertFalse(c.settings["nr"])
        self.assertIn("strong", self.reasons(c)["nr"])
        self.assertEqual(c.settings["agc"], "medium")
        self.assertFalse(c.settings["nb"])

    def test_weaker_signals_get_more_nr_and_a_narrower_filter(self):
        mid = aa.best_audio(station(12.0), "usb", 0.0).settings
        weak = aa.best_audio(station(3.0), "usb", 0.0).settings
        self.assertTrue(mid["nr"] and weak["nr"])
        self.assertGreater(weak["nrStrength"], mid["nrStrength"])
        self.assertLessEqual(weak["filterHi"], 2300.0)
        self.assertEqual(weak["agc"], "slow")

    def test_filter_wraps_the_speech(self):
        c = aa.choose(aa.Measured(snr=25.0, band=(310.0, 2620.0), impulses=0.0))
        self.assertEqual((c.settings["filterLo"], c.settings["filterHi"]), (250.0, 2700.0))
        c = aa.choose(aa.Measured(snr=25.0, band=(120.0, 3600.0), impulses=0.0))
        self.assertEqual((c.settings["filterLo"], c.settings["filterHi"]), (100.0, 2900.0))

    def test_impulses_switch_the_blanker_on_and_speed_the_agc(self):
        c = aa.choose(aa.Measured(snr=25.0, band=(300.0, 2600.0), impulses=10.0))
        self.assertTrue(c.settings["nb"])
        self.assertEqual(c.settings["agc"], "fast")
        self.assertIn("10.0 impulses", self.reasons(c)["nb"])

    def test_the_summary_says_what_was_chosen(self):
        c = aa.best_audio(station(12.0, "lsb"), "lsb", 0.0)
        s = c.summary()
        for part in ("dB SNR", "filter", "AGC", "NR", "NB"):
            self.assertIn(part, s)

    def test_a_neighbour_s_edge_is_not_taken_for_the_station(self):
        # The station on the dial is silent; another's voice shows only its
        # top, 2-3 kHz up the passband.
        rng = np.random.default_rng(5)
        z = sg.voice(rng, 6.0)[:N] * np.exp(2j * np.pi * 1900 * np.arange(N) / RATE)
        lowpass = np.fft.fftfreq(N, 1 / RATE) < 3000
        z = np.fft.ifft(np.fft.fft(z) * lowpass)
        x = z + (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * 0.02
        c = aa.best_audio(x.astype(np.complex64), "usb", 0.0)
        self.assertFalse(c.ok, c.summary())
        self.assertIn("no speech of the station on the dial", c.why)

    def test_a_beacon_is_not_given_a_voice_s_settings(self):
        rng = np.random.default_rng(4)
        t = np.arange(N) / RATE
        x = sg.bpsk_beacon(rng, 5.0)[:N] * np.exp(2j * np.pi * 1000 * t)
        x = x + (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * 0.05
        c = aa.best_audio(x.astype(np.complex64), "usb", 0.0)
        self.assertFalse(c.ok)
        self.assertIn("holds its level", c.why)

    def test_not_a_voice_mode(self):
        self.assertFalse(aa.best_audio(station(20.0), "am", 0.0).ok)


if __name__ == "__main__":
    unittest.main()
