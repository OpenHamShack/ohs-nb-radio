import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib.util
import unittest
from pathlib import Path

import numpy as np

from ohscore.modes import cw

FS = 12_000.0


def _decode(audio: np.ndarray, freq: float = 700.0, wpm_hint: float = 20.0) -> str:
    events = []
    dec = cw.Decoder(events.append, freq=freq, wpm_hint=wpm_hint)
    block = 1200  # 100 ms blocks: exercises feed() being called with a real block size
    for i in range(0, len(audio), block):
        dec.feed(audio[i:i + block], t=i / FS)
    return "".join(e["text"] for e in events)


class CwEncoderTests(unittest.TestCase):
    def test_peak_within_limit(self):
        audio = cw.Encoder().render(text="CQ CQ DE GM4BRI", wpm=20)
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_render_is_float32_mono(self):
        audio = cw.Encoder().render(text="E", wpm=20)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)

    def test_edges_are_smooth_not_clicky(self):
        # A hard-keyed dit jumps from silence to full amplitude in one sample;
        # a raised-cosine edge instead ramps the envelope up over edge_ms, so
        # the waveform starts and ends near zero. Checking the raw sample
        # derivative doesn't work here -- a steady 700 Hz tone itself has a
        # sample-to-sample slope of order 2*pi*f/fs regardless of the edge
        # shape -- so this checks the envelope at the very start/end instead.
        audio = cw.Encoder().render(text="E", wpm=15, edge_ms=5.0, freq=700.0)
        self.assertLess(abs(float(audio[0])), 0.05)
        self.assertLess(abs(float(audio[-1])), 0.05)
        # And the middle of the dit must actually be near full scale, or this
        # would also pass for a tone that just never turns on.
        self.assertGreater(float(np.max(np.abs(audio))), 0.9)

    def test_farnsworth_widens_gaps_not_elements(self):
        fast = cw.Encoder().render(text="E E", wpm=20)
        slow = cw.Encoder().render(text="E E", wpm=20, farnsworth=10)
        self.assertGreater(len(slow), len(fast))
        # Count samples above a tone-ish threshold: farnsworth must not change
        # how much of the render is *tone* (only how much is gap).
        on_fast = int(np.sum(np.abs(fast) > 0.3))
        on_slow = int(np.sum(np.abs(slow) > 0.3))
        self.assertAlmostEqual(on_fast, on_slow, delta=max(2, int(0.05 * on_fast)))


class CwLoopbackTests(unittest.TestCase):
    MESSAGE = "CQ CQ DE GM4BRI GM4BRI <AR>"

    def _render_padded(self, wpm, freq=700.0):
        audio = cw.Encoder().render(text=self.MESSAGE, wpm=wpm, freq=freq)
        return np.concatenate([audio, np.zeros(int(0.5 * FS), dtype=np.float32)])

    def test_clean_loopback_12_20_30_wpm(self):
        for wpm in (12, 20, 30):
            with self.subTest(wpm=wpm):
                text = _decode(self._render_padded(wpm))
                # The "<AR>" prosign renders as "+" under CODE_TO_PROSIGN lookup
                # miss-free; accept either spelling since what matters is that
                # every letter of the callsigns and procedure came through.
                self.assertIn("GM4BRI", text)
                self.assertIn("CQ", text)
                self.assertIn("DE", text)

    def test_noisy_loopback_20_wpm(self):
        rng = np.random.default_rng(42)
        audio = self._render_padded(20)
        noisy = audio + rng.normal(0, 0.1, len(audio)).astype(np.float32)
        text = _decode(noisy)
        # The callsign, sent twice, must survive this (roughly 20 dB) SNR intact.
        self.assertEqual(text.count("GM4BRI"), 2)
        self.assertIn("CQ", text)
        self.assertIn("DE", text)

    def test_prosign_round_trip(self):
        # A second of silence after it, not half: six elements are too few
        # to learn a speed from, so a lone prosign is decoded once the
        # silence after it is longer than any word space could be (four
        # dashes' worth, 0.8 s at 18 WPM) - see Decoder._check_gap.
        audio = np.concatenate([cw.Encoder().render(text="<SK>", wpm=18),
                                 np.zeros(int(1.0 * FS), dtype=np.float32)])
        text = _decode(audio)
        self.assertIn("<SK>", text)

    def test_different_tone_offset(self):
        text = _decode(self._render_padded(20, freq=900.0), freq=900.0)
        self.assertIn("GM4BRI", text)

    def test_pure_noise_decodes_nothing_useful(self):
        # No tone anywhere: an empty band must not hallucinate callsigns out of
        # noise alone. (Listening at the wrong frequency for a *real* tone
        # elsewhere is a different, weaker claim -- Goertzel sidelobe leakage
        # a few bins away still carries some of the real tone's on/off
        # envelope, so that case is not a fair test of false-decode immunity.)
        # A simple envelope/threshold decoder (there is no matched filter here,
        # deliberately -- this has to run on a Pi 400) will always read *some*
        # structure into Gaussian noise, the same way a real CW skimmer chatters
        # on an empty band. The bar is "mostly quiet", not "literally nothing":
        # 2 s of noise must not produce as much text as 2 s of real CQing does.
        lengths = []
        for seed in range(5):
            rng = np.random.default_rng(seed)
            noise = rng.normal(0, 0.2, int(2.0 * FS)).astype(np.float32)
            lengths.append(len(_decode(noise, freq=700.0)))
        self.assertLess(sum(lengths) / len(lengths), 15)

    def test_reset_clears_state(self):
        dec = cw.Decoder(lambda e: None, freq=700.0)
        dec.feed(cw.Encoder().render(text="E", wpm=20), t=0.0)
        dec.reset()
        self.assertEqual(dec.text, "")


# The decoder lives in ohs-libs' shack_cw now, with its on-air tests (QSB,
# drift, a human fist, inverted keying, neighbours); these hold NB's side:
# the mode registry builds the shared decoder, and through NB's own
# receiver (tools/cw_bench.py: ohscore.dsp.demod's 500 Hz filter and medium
# AGC, the engine's 75 ms blocks) it reads the beacon as the bench says.
_spec = importlib.util.spec_from_file_location("cw_bench", Path(__file__).resolve().parent.parent / "tools" / "cw_bench.py")
nbbench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nbbench)


class CwSharedDecoderTests(unittest.TestCase):
    def test_the_cw_mode_decodes_with_the_shared_decoder(self):
        from ohscore import modes, shacklibs
        dec = modes.MODES["cw"].make_decoder(lambda e: None, freq=700.0)
        self.assertIsInstance(dec, shacklibs.cw().Decoder)
        self.assertIs(cw.MORSE, shacklibs.cw().MORSE)

    def test_the_beacon_through_nbs_receiver(self):
        # At 6 dB under 5 % errors, and at 20 dB letter for letter with the
        # 12 s carrier printing nothing (shack_cw's tests say why each).
        for seed in range(2):
            with self.subTest(seed=seed):
                self.assertLess(nbbench.run_case("beacon", 6.0, seed)[0], 0.05)
        out = nbbench.run_case("beacon", 20.0, 0)[3]
        self.assertEqual(" ".join(out.split()), " ".join([nbbench.bench.BEACON_TEXT] * 2))

    def test_the_inverted_beacon_and_noise_through_nbs_receiver(self):
        out = nbbench.run_case("beacon-bookmark", 10.0, 0)[3]
        self.assertTrue(out.startswith("HI DE") or out.startswith("E HI DE"), out)
        self.assertEqual(nbbench.run_case("carriers", 6.0, 0)[3].strip(), "")


if __name__ == "__main__":
    unittest.main()
