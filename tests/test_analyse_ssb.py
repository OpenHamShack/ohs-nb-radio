"""ohsnb.analyse_ssb.ssb_at_scale: SSB auto-tune, every window_s across a
recording rather than once from the middle - behavioural: a real voice
(ohscore.devices.simsignals.voice, the same generator ohscore's own
autotune tests use) embedded in only the first half of a two-window
recording must be found and tuned in that window and not invented in the
second, silent one."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.dsp.bank import Geometry, Source, Synthesis

from ohsnb import analyse_ssb, bandplan

FS = 240_000.0
WINDOW_S = 12.0
TOTAL_S = 24.0   # two windows: voice in the first, silence in the second


class VoiceInTheFirstWindowOnly(unittest.TestCase):
    RX = 0.0          # the LNB's measured error (rx_corr_est): none here

    def setUp(self):
        self.geo = Geometry(FS)
        seg_lo, seg_hi = next((lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS
                              if classes == {"ssb"})
        self.dc0 = (seg_lo + seg_hi) / 2.0 - 20_000.0     # DC not on the voice itself
        self.carrier_abs = (seg_lo + seg_hi) / 2.0 + 300.0
        # A true frequency F sits at F - (dc0 - RX) in the file's IQ.
        rel = self.carrier_abs - (self.dc0 - self.RX)
        rng = np.random.default_rng(5)
        n12 = int(TOTAL_S * 12_000.0)
        audio = sg.voice(rng, TOTAL_S)[:n12].astype(np.complex128)
        audio[int(WINDOW_S * 12_000.0):] = 0.0      # silent for the second window
        d = self.geo.decimation_for(12_000.0)
        # Weak enough that the occupied-band detector sees the voice's own
        # ~2-3 kHz width, not a much wider skirt of spectral leakage around
        # an unrealistically loud signal (measured: gain 1.0 read back over
        # 5.8 kHz wide, past MAX_WIDTH_HZ, and so found no candidate at
        # all; 0.015 reads 3.7 kHz, inside it, and auto-tune still accepts).
        src = Source(self.geo, d, freq=rel, gain=0.015)
        synth = Synthesis(self.geo)
        m = len(audio) // src.hop
        wide = synth.render(m, [(src, audio[:m * src.hop].astype(np.complex64))])
        rngn = np.random.default_rng(6)
        noise = (0.002 * (rngn.standard_normal(len(wide)) + 1j * rngn.standard_normal(len(wide))))
        self.wide = (wide + noise).astype(np.complex64)
        self.view = np.stack([self.wide.real, self.wide.imag], axis=1).astype(np.float32)
        self.n = len(self.wide)
        self.caps = [{"core:sample_start": 0, "core:frequency": self.dc0}]
        self.info = {"lnb_lo_hz": None, "nominal_dc_flat": None}

    def test_the_voice_is_found_and_tuned_in_its_own_window(self):
        r = analyse_ssb.ssb_at_scale(self.view, 1.0, self.n, FS, self.caps, self.info, self.RX, [],
                                     window_s=WINDOW_S)
        first_window = [a for a in r["attempts"] if a["t_s"] < WINDOW_S]
        second_window = [a for a in r["attempts"] if a["t_s"] >= WINDOW_S]
        self.assertTrue(first_window, "no candidate at all was found in the window the voice was in")
        self.assertEqual(second_window, [])    # nothing in the silent window
        accepted = [a for a in first_window if a["ok"]]
        self.assertTrue(accepted, f"auto-tune never accepted the voice: {first_window}")
        self.assertAlmostEqual(accepted[0]["carrier_mhz"], self.carrier_abs / 1e6, delta=0.0002)
        self.assertEqual(r["accepted"], len(accepted))
        self.assertIsNotNone(r["offset_hz"])
        self.assertEqual(r["offset_hz"]["n"], len(accepted))

    def test_a_recording_with_no_voice_anywhere_accepts_nothing(self):
        rng = np.random.default_rng(9)
        noise = (0.002 * (rng.standard_normal(self.n) + 1j * rng.standard_normal(self.n))).astype(np.complex64)
        view = np.stack([noise.real, noise.imag], axis=1).astype(np.float32)
        r = analyse_ssb.ssb_at_scale(view, 1.0, self.n, FS, self.caps, self.info, self.RX, [], window_s=WINDOW_S)
        self.assertEqual(r["accepted"], 0)
        self.assertIsNone(r["offset_hz"])


class WithAnLnbError(VoiceInTheFirstWindowOnly):
    """The same, with the LNB reading 7 kHz off, as every real QO-100
    recording does (07/10/2026's: 25-28 kHz). Until 08/10 the candidates
    were found at their true frequencies but the capture was tuned from
    the nominal DC, rx_corr_est Hz away from them: on the 3 h recording
    of 07/10 every attempt auto-tuned whatever was 28 kHz below the
    candidate - 73 of 107 found nothing there, and the 3 "tuned" were
    other stations. With RX at 0, as above, the two agree, which is why
    nothing caught it."""
    RX = 7000.0


def _render(geo, d, parts, seconds, noise_seed=6):
    """Wide IQ at FS holding each (audio at 12 kHz, offset Hz from DC,
    gain), plus a little noise: the (N, 2) float view analyse reads."""
    synth = Synthesis(geo)
    m = None
    srcs = []
    for audio, rel, gain in parts:
        src = Source(geo, d, freq=rel, gain=gain)
        m = len(audio) // src.hop if m is None else min(m, len(audio) // src.hop)
        srcs.append((src, audio))
    wide = synth.render(m, [(src, a[:m * src.hop].astype(np.complex64)) for src, a in srcs])
    rng = np.random.default_rng(noise_seed)
    wide = wide + 0.002 * (rng.standard_normal(len(wide)) + 1j * rng.standard_normal(len(wide)))
    wide = wide[:int(seconds * FS)].astype(np.complex64)
    return np.stack([wide.real, wide.imag], axis=1).astype(np.float32), len(wide)


class OnlyVoiceLikeCandidates(unittest.TestCase):
    """A candidate must look like speech: wide enough at some point and a
    level that comes and goes. Until 08/10 anything 300-4200 Hz wide in a
    146 Hz-bin average was one, and on the 3 h recording of 07/10 dozens
    were CW, carriers or lumps of noise, each auto-tuned and counted as a
    refusal."""

    def setUp(self):
        self.geo = Geometry(FS)
        self.d = self.geo.decimation_for(12_000.0)
        seg_lo, seg_hi = next((lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS
                              if classes == {"ssb"})
        self.mid = (seg_lo + seg_hi) / 2.0
        self.dc0 = self.mid - 20_000.0
        self.caps = [{"core:sample_start": 0, "core:frequency": self.dc0}]
        self.info = {"lnb_lo_hz": None, "nominal_dc_flat": None}

    def _attempts(self, parts):
        view, n = _render(self.geo, self.d, parts, WINDOW_S)
        return analyse_ssb.ssb_at_scale(view, 1.0, n, FS, self.caps, self.info, 0.0, [],
                                        window_s=WINDOW_S)["attempts"]

    def test_a_steady_data_signal_as_wide_as_a_voice_is_not_a_candidate(self):
        # 8APSK at 2400 Bd, ~2.7 kHz wide: a voice's width, a machine's level.
        rng = np.random.default_rng(3)
        n12 = int((WINDOW_S + 1) * 12_000.0)
        apsk = sg.apsk_beacon(rng, WINDOW_S + 1)[:n12]
        self.assertEqual(self._attempts([(apsk, self.mid - self.dc0, 0.01)]), [])

    def test_a_cw_station_is_not_a_candidate(self):
        rng = np.random.default_rng(4)
        cw = sg.cw_station(rng, "CQ CQ DE G0ABC G0ABC K", 20, WINDOW_S + 1)
        self.assertEqual(self._attempts([(cw.astype(np.complex64), self.mid - self.dc0, 0.02)]), [])


class CaptureWhileTalking(unittest.TestCase):
    """The 4 s auto-tune capture is taken where the candidate's band was
    busiest inside the 10 s candidate window, not at its centre. Here the
    station talks only in the first ~3.5 s of that window (1.0-4.5 s into
    the recording): a capture at the centre (4-8 s) would hear half a
    second of it."""

    def test_the_capture_is_taken_while_the_station_talks_and_tunes_it(self):
        geo = Geometry(FS)
        d = geo.decimation_for(12_000.0)
        seg_lo, seg_hi = next((lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS
                              if classes == {"ssb"})
        dc0 = (seg_lo + seg_hi) / 2.0 - 20_000.0
        carrier_abs = (seg_lo + seg_hi) / 2.0 + 300.0
        n12 = int((WINDOW_S + 1) * 12_000.0)
        audio = sg.voice(np.random.default_rng(5), WINDOW_S + 1)[:n12].astype(np.complex128)
        on = np.zeros(n12, bool)
        on[int(1.0 * 12_000):int(4.5 * 12_000)] = True
        audio[~on] = 0.0
        view, n = _render(geo, d, [(audio, carrier_abs - dc0, 0.015)], WINDOW_S)
        caps = [{"core:sample_start": 0, "core:frequency": dc0}]
        r = analyse_ssb.ssb_at_scale(view, 1.0, n, FS, caps, {"lnb_lo_hz": None, "nominal_dc_flat": None},
                                     0.0, [], window_s=WINDOW_S)
        self.assertTrue(r["attempts"], "the voice was not found as a candidate")
        a = r["attempts"][0]
        self.assertLessEqual(a["capture_s"], 1.5, a)        # starts as the talking does, not at 4 s
        self.assertTrue(a["ok"], a)
        self.assertAlmostEqual(a["carrier_mhz"], carrier_abs / 1e6, delta=0.0002)


if __name__ == "__main__":
    unittest.main()
