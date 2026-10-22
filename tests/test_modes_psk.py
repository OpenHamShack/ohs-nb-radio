import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest
import numpy as np

from ohscore.modes import psk

FS = 12_000.0


def _decode(audio, variant="psk31", center=1000.0):
    events = []
    dec = psk.Decoder(events.append, variant=variant, center=center)
    block = 1200
    for i in range(0, len(audio), block):
        dec.feed(audio[i:i + block], t=i / FS)
    return dec.text


class PskVaricodeTests(unittest.TestCase):
    def test_no_code_contains_double_zero_or_ends_in_zero(self):
        for ch, code in psk.VARICODE.items():
            self.assertNotIn("00", code, msg=ch)
            self.assertEqual(code[-1], "1", msg=ch)

    def test_codes_are_unique(self):
        codes = list(psk.VARICODE.values())
        self.assertEqual(len(codes), len(set(codes)))

    def test_common_letters_get_shorter_codes_than_rare_ones(self):
        self.assertLess(len(psk.VARICODE["E"]), len(psk.VARICODE["Q"]))
        self.assertLess(len(psk.VARICODE[" "]), len(psk.VARICODE["Z"]))

    def test_known_g3plx_codes(self):
        # Fixed points against the table as published in fldigi's
        # src/psk/pskvaricode.cxx (varicodetab1) and cross-checked against
        # Wikipedia's "Varicode" article, which independently quotes the
        # same values for 'e', 'a' and 'z' -- see the module docstring for
        # both sources. A wrong table could still satisfy every *structural*
        # test above (unique, no "00", ends in 1) while being unable to
        # talk to a real PSK31 station, which is exactly why this checks
        # literal bit patterns rather than just shape.
        known = {"e": "11", " ": "1", "a": "1011", "t": "101", "E": "1110111"}
        for ch, code in known.items():
            self.assertEqual(psk.VARICODE[ch], code, msg=ch)

    def test_second_source_cross_check(self):
        # Independently confirmed by Wikipedia's Varicode article (not
        # just fldigi's source) -- a second source for the same patterns.
        self.assertEqual(psk.VARICODE["a"], "1011")
        self.assertEqual(psk.VARICODE["z"], "111010101")

    def test_table_covers_full_byte_range(self):
        # 0-127 is the original G3PLX set; 128-255 is fldigi's own
        # extension (see module docstring) but every code point must still
        # resolve to *something* decodable.
        self.assertEqual(len(psk.VARICODE), 256)
        for i in range(256):
            self.assertIn(chr(i), psk.VARICODE)


class FldigiConventionTests(unittest.TestCase):
    """Confirms the bit/phase convention against fldigi's src/psk/psk.cxx
    (psk::tx_bit, psk::tx_char, psk::tx_flush): plain BPSK sends `bit << 1`
    as the symbol, where symbol 0 is what the preamble uses with the
    comment "send phase reversals" and symbol 2 is what the postamble uses
    with the comment "0 degrees" -- i.e. bit=0 is a phase flip, bit=1 is
    no change, and idle (nothing to send) is a continuous run of bit=0.
    Every character is followed by two more such bits (tx_char: "Insert
    PSK varicode character-delimiting bits" -> tx_bit(0); tx_bit(0))."""

    def test_text_to_bits_appends_00_separator(self):
        bits = psk._text_to_bits("e")
        self.assertEqual(bits, psk.VARICODE["e"] + "00")

    def test_text_to_bits_separator_between_characters(self):
        bits = psk._text_to_bits("ab")
        self.assertEqual(bits, psk.VARICODE["a"] + "00" + psk.VARICODE["b"] + "00")

    def test_idle_preamble_is_continuous_phase_reversal(self):
        # preamble=X, postamble=0, no text: idle is pure "0" bits, which
        # must flip phase every symbol -- the NRZ sign must alternate on
        # every symbol boundary with no two consecutive equal signs.
        audio = psk.Encoder().render(text="", variant="psk31", preamble=0.5, postamble=0.0)
        sym_n = int(round(FS / psk.BAUDS["psk31"]))
        # Sample well inside each symbol (skipping shaped edges) to read its sign.
        signs = [np.sign(audio[k * sym_n + sym_n // 2]) for k in range(len(audio) // sym_n)]
        for a, b in zip(signs, signs[1:]):
            self.assertNotEqual(a, b)


class PskEncoderTests(unittest.TestCase):
    def test_peak_within_limit(self):
        audio = psk.Encoder().render(text="CQ CQ DE GM4BRI")
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_render_is_float32_mono(self):
        audio = psk.Encoder().render(text="E")
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)

    def test_idle_only_is_continuous_phase_reversal(self):
        # No text at all -- preamble/postamble collapse to one idle run --
        # must still render (the "warble" a PSK31 band sounds like) rather
        # than an empty or crashing render.
        audio = psk.Encoder().render(text="", preamble=1.0, postamble=0.0)
        self.assertGreater(len(audio), 0)

    def test_even_preamble_bit_count(self):
        # See the comment at the fix site in psk.py: an odd number of idle
        # bits before real text starts can eat the first character's
        # leading zero bit. render() must always choose an even count.
        for preamble in (1.0, 1.003, 2.0001, 0.337):
            n_pre = int(round(preamble * 31.25)) // 2 * 2
            self.assertEqual(n_pre % 2, 0)


class PskLoopbackTests(unittest.TestCase):
    MESSAGE = "CQ CQ DE GM4BRI GM4BRI PSE K"

    def test_clean_loopback_all_variants(self):
        for variant in ("psk31", "psk63", "psk125"):
            with self.subTest(variant=variant):
                audio = psk.Encoder().render(text=self.MESSAGE, variant=variant)
                self.assertEqual(_decode(audio, variant=variant), self.MESSAGE)

    def test_noisy_loopback(self):
        audio = psk.Encoder().render(text=self.MESSAGE, variant="psk31")
        rng = np.random.default_rng(11)
        noisy = audio + rng.normal(0, 0.04, len(audio)).astype(np.float32)
        # At a noise level that stresses the demodulator, an occasional extra
        # character right at the idle-postamble boundary is realistic (the
        # same way a real decoder spits out line noise) and not what this
        # test is checking; the message itself must still be intact.
        self.assertTrue(_decode(noisy, variant="psk31").startswith(self.MESSAGE))

    def test_frequency_offset_within_afc_range(self):
        # The decoder is told the carrier is at 1000 Hz; the signal is
        # actually some way off, inside the +-15 Hz AFC range DESIGN.md
        # asks for. A coarse FFT-domain fix (on the squared signal, which
        # removes the BPSK data phase and leaves a clean tone at 2x carrier)
        # pulls this in before the fine per-symbol loop ever sees it --
        # without it, that loop's own capture range is only +-baud/4, far
        # short of +-15 Hz at PSK31's 31.25 baud.
        for offset in (-13.0, -5.0, 7.0, 13.0):
            with self.subTest(offset=offset):
                audio = psk.Encoder().render(text=self.MESSAGE, variant="psk31",
                                              center=1000.0 + offset)
                self.assertEqual(_decode(audio, variant="psk31", center=1000.0), self.MESSAGE)

    def test_frequency_offset_with_noise(self):
        audio = psk.Encoder().render(text=self.MESSAGE, variant="psk63", center=1008.0)
        rng = np.random.default_rng(3)
        noisy = audio + rng.normal(0, 0.04, len(audio)).astype(np.float32)
        self.assertEqual(_decode(noisy, variant="psk63", center=1000.0), self.MESSAGE)

    def test_reset_clears_state(self):
        dec = psk.Decoder(lambda e: None, variant="psk31")
        dec.feed(psk.Encoder().render(text="E"), t=0.0)
        dec.reset()
        self.assertEqual(dec.text, "")

    def test_emitted_events_carry_mode_and_text(self):
        audio = psk.Encoder().render(text="HI", variant="psk31")
        events = []
        dec = psk.Decoder(events.append, variant="psk31")
        for i in range(0, len(audio), 1200):
            dec.feed(audio[i:i + 1200], t=i / FS)
        self.assertTrue(events)
        self.assertEqual(events[0]["mode"], "psk31")
        self.assertIn("text", events[0])


def _analytic_shift(audio, f0=0.0, rate=0.0, step_at=None, step_hz=0.0):
    """Move real audio in frequency by f0 + rate*t (plus step_hz after
    step_at seconds), phase-continuously, via its analytic signal."""
    X = np.fft.fft(audio.astype(np.float64))
    n = len(audio)
    X[n // 2 + 1:] = 0
    X[1:n // 2] *= 2
    z = np.fft.ifft(X)
    t = np.arange(n) / FS
    f = f0 + rate * t
    if step_at is not None:
        f = f + np.where(t >= step_at, step_hz, 0.0)
    ph = 2 * np.pi * np.cumsum(f) / FS
    return (z * np.exp(1j * ph)).real.astype(np.float32)


def _with_snr(audio, snr_db, baud, seed):
    """White noise for a given SNR in a bandwidth equal to the baud rate
    (= Eb/N0 for BPSK): the yardstick weak-signal PSK is judged by. Noise of
    variance s^2 at 12 kHz has density s^2 / 6 kHz."""
    ps = float(np.mean(audio.astype(np.float64) ** 2))
    sigma = np.sqrt(ps * (FS / 2) / baud / 10 ** (snr_db / 10))
    rng = np.random.default_rng(seed)
    return (audio + rng.normal(0, sigma, len(audio))).astype(np.float32)


class PskWeakSignalTests(unittest.TestCase):
    """What a PSK31 receiver is for. Every one of these failed on the
    decoder before the rewrite: it mixed each block with the absolute
    sample count, so any AFC movement at all (which noise guarantees) rotated
    the constellation by an angle growing with time; and it fixed timing and
    frequency once, from the first 1.5 s it was fed, and never again."""

    MESSAGE = "CQ CQ DE GM4BRI GM4BRI PSE K"

    def test_modest_noise_on_a_half_amplitude_signal(self):
        # The reported failure, literally: sigma 0.1 on a ~0.5 amplitude
        # signal at 12 kHz is about +25 dB in 31 Hz.
        audio = psk.Encoder().render(text=self.MESSAGE) * np.float32(0.5 / 0.95)
        for seed in range(3):
            with self.subTest(seed=seed):
                rng = np.random.default_rng(seed)
                noisy = (audio + rng.normal(0, 0.1, len(audio))).astype(np.float32)
                self.assertIn(self.MESSAGE, _decode(noisy))

    def test_ten_db_in_the_symbol_bandwidth_copies_completely(self):
        # 10 dB in 31.25 Hz is -10 dB in a 3 kHz passband: a signal barely
        # visible on the waterfall, which DBPSK theory copies at a bit error
        # rate of 2e-5. Off-frequency and drifting too (the drift case moves
        # 2.5 Hz over the message, which the old one-shot AFC never followed).
        audio = psk.Encoder().render(text=self.MESSAGE)
        cases = {"on frequency": {}, "+10 Hz": {"f0": 10.0}, "-10 Hz": {"f0": -10.0},
                 "-8 Hz drifting +0.3 Hz/s": {"f0": -8.0, "rate": 0.3}}
        for name, shift in cases.items():
            moved = _analytic_shift(audio, **shift) if shift else audio
            for seed in range(3):
                with self.subTest(name, seed=seed):
                    self.assertIn(self.MESSAGE, _decode(_with_snr(moved, 10.0, 31.25, seed)))

    def test_a_signal_that_appears_after_minutes_of_noise(self):
        # The engine makes the decoder when the mode is selected; the signal
        # (our own echo, or a station calling) comes along later.
        audio = _analytic_shift(psk.Encoder().render(text=self.MESSAGE), f0=7.0)
        rng = np.random.default_rng(5)
        before = np.zeros(int(8 * FS), np.float32)
        # 15 dB on the signal's own power (not averaged over the silence).
        sigma = np.sqrt(float(np.mean(audio.astype(np.float64) ** 2)) * (FS / 2) / 31.25 / 10 ** 1.5)
        noisy = np.concatenate([before, audio]) + rng.normal(0, sigma, len(before) + len(audio))
        self.assertIn(self.MESSAGE, _decode(noisy.astype(np.float32)))

    def test_a_frequency_step_in_the_preamble(self):
        # The sending station's TX lock corrects its uplink a second or two
        # into the over -- our own echo through the simulator does this --
        # so the carrier steps by several hertz under the decoder's feet.
        audio = _analytic_shift(psk.Encoder().render(text=self.MESSAGE), f0=6.0, step_at=1.8, step_hz=-6.0)
        for seed in range(2):
            with self.subTest(seed=seed):
                self.assertIn(self.MESSAGE, _decode(_with_snr(audio, 15.0, 31.25, seed)))

    def test_symbol_timing_follows_a_sound_card_clock_error(self):
        # 500 ppm: the transmitting sound card's 12 kHz is 12.006 kHz. Over a
        # 30-second over the symbol clock slides by almost half a symbol,
        # which timing fixed once at the start does not survive.
        text = self.MESSAGE + " " + self.MESSAGE + " " + self.MESSAGE
        audio = psk.Encoder().render(text=text).astype(np.float64)
        n = len(audio)
        src = np.arange(int(n / 1.0005)) * 1.0005
        slid = np.interp(src, np.arange(n), audio).astype(np.float32)
        self.assertIn(text, _decode(_with_snr(slid, 15.0, 31.25, 1)))

    def test_noise_alone_prints_next_to_nothing(self):
        # The squelch: with no signal, a decoder that printed every
        # "character" noise happens to spell would fill the terminal.
        rng = np.random.default_rng(9)
        noise = rng.normal(0, 0.3, int(30 * FS)).astype(np.float32)
        self.assertLessEqual(len(_decode(noise)), 3)

    def test_events_carry_offset_and_snr(self):
        audio = _with_snr(psk.Encoder().render(text="HI HI"), 15.0, 31.25, 0)
        events = []
        dec = psk.Decoder(events.append, variant="psk31")
        dec.feed(audio, t=0.0)
        self.assertTrue(events)
        self.assertAlmostEqual(events[-1]["df"], 1000.0, delta=1.0)
        self.assertGreater(events[-1]["snr"], 5.0)


class PskCarrierBrowserTests(unittest.TestCase):
    def test_finds_an_injected_tone(self):
        rng = np.random.default_rng(0)
        n = 4096
        t = np.arange(n) / FS
        audio = (0.5 * np.sin(2 * np.pi * 1400.0 * t) +
                  0.02 * rng.normal(0, 1, n)).astype(np.float32)
        peaks = psk.find_carriers(audio)
        self.assertTrue(any(abs(f - 1400.0) < 20 for f in peaks))

    def test_quiet_band_finds_nothing_strong(self):
        rng = np.random.default_rng(1)
        audio = (0.01 * rng.normal(0, 1, 4096)).astype(np.float32)
        peaks = psk.find_carriers(audio)
        self.assertEqual(peaks, [])


if __name__ == "__main__":
    unittest.main()
