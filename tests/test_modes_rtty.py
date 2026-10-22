import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import types
import unittest
import numpy as np

from ohscore.modes import rtty

FS = 12_000.0


def _decode(audio, **opts):
    events = []
    dec = rtty.Decoder(events.append, **opts)
    block = 1200
    for i in range(0, len(audio), block):
        dec.feed(audio[i:i + block], t=i / FS)
    return "".join(e["text"] for e in events)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cer(heard: str, sent: str) -> float:
    """Character error rate of everything printed against what was sent:
    garbage printed before or after the message counts, as it does on screen."""
    return _edit_distance(heard, sent) / len(sent)


def _in_noise(audio, snr_db, seed, lead=3.0, tail=3.0):
    """`audio` (a unit sine) between `lead` and `tail` seconds of noise, at
    `snr_db` signal-to-noise in a 3 kHz bandwidth: the way an RTTY signal
    turns up in a receiver, which was listening to noise before it."""
    rng = np.random.default_rng(seed)
    n0 = 0.5 / 10 ** (snr_db / 10) / 3000.0
    sigma = np.sqrt(n0 * FS / 2)
    a = np.concatenate([np.zeros(int(lead * FS)), audio.astype(np.float64), np.zeros(int(tail * FS))])
    return (0.3 * (a + rng.normal(0, sigma, len(a)))).astype(np.float32)


class RttyEncoderTests(unittest.TestCase):
    def test_peak_within_limit(self):
        audio = rtty.Encoder().render(text="CQ DE GM4BRI")
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_render_is_float32_mono(self):
        audio = rtty.Encoder().render(text="E")
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)

    def test_empty_text_renders_nothing_crashy(self):
        audio = rtty.Encoder().render(text="")
        self.assertLessEqual(len(audio), 1)

    def test_timing_and_tones(self):
        # 45.45 Bd, 1.5 stop bits, mark 85 Hz above the centre and space 85
        # below. One "E" (data 10000) after the leading LTRS pair: read each
        # bit's tone back from the audio at the times the standard puts it.
        enc = rtty.Encoder()
        audio = enc.render(text="E", preamble=0.2, postamble=0.5)
        bit = FS / 45.45
        chars = 2 + 1
        self.assertAlmostEqual(len(audio), round((0.2 + chars * 7.5 / 45.45 + 0.5) * FS), delta=1)
        e0 = int(round(0.2 * FS + 2 * 7.5 * bit))       # the E's start bit

        def tone(at):
            seg = audio[int(at + 0.2 * bit):int(at + 0.8 * bit)].astype(np.float64)
            n = np.arange(len(seg))
            m = abs(seg @ np.exp(-2j * np.pi * 1085.0 * n / FS))
            s = abs(seg @ np.exp(-2j * np.pi * 915.0 * n / FS))
            return "M" if m > s else "S"
        got = "".join(tone(e0 + k * bit) for k in range(8))
        #          start E=1 0 0 0 0 stop(1.5)
        self.assertEqual(got, "S" + "MSSSS" + "MM")


class RttyCodeTableTests(unittest.TestCase):
    def test_ltrs_figs_shift_round_trips_through_text_to_codes(self):
        codes = rtty._text_to_codes("A1B")
        # A, then a shift to FIGS, then "1", then a shift back to LTRS, then B.
        self.assertEqual(codes, [rtty.LETTER_TO_CODE["A"], rtty.FIGS,
                                  rtty.FIGURE_TO_CODE["1"], rtty.LTRS, rtty.LETTER_TO_CODE["B"]])

    def test_every_code_is_five_bits_and_unique(self):
        codes = [c for c, _, _ in rtty._ROWS]
        self.assertTrue(all(len(c) == 5 for c in codes))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(codes), 32)

    def test_table_is_ita2_letters_with_us_tty_figures(self):
        # ITU-T S.1 letters case, and the US-TTY figures that fldigi and
        # MMTTY use by default. Spot checks where the two figure sets differ,
        # and the code points a wrong bit order would move.
        self.assertEqual(rtty.LETTER_TO_CODE["E"], "10000")
        self.assertEqual(rtty.LETTER_TO_CODE["T"], "00001")
        self.assertEqual(rtty.LETTER_TO_CODE["A"], "11000")
        self.assertEqual(rtty.CODE_TO_FIGURE[rtty.LETTER_TO_CODE["S"]], "\a")
        self.assertEqual(rtty.CODE_TO_FIGURE[rtty.LETTER_TO_CODE["J"]], "'")
        self.assertEqual(rtty.CODE_TO_FIGURE[rtty.LETTER_TO_CODE["D"]], "$")
        self.assertEqual(rtty.CODE_TO_FIGURE[rtty.LETTER_TO_CODE["Q"]], "1")

    def test_space_unshifts_so_a_figure_after_it_is_shifted_again(self):
        # Unshift-on-space: the receiver goes back to letters at a space, so
        # "1 2" must send FIGS again before the 2.
        f = rtty.FIGURE_TO_CODE
        self.assertEqual(rtty._text_to_codes("1 2"), [rtty.FIGS, f["1"], rtty.SPACE, rtty.FIGS, f["2"]])
        # and a letter after "1 " needs no LTRS: the space already gave one.
        self.assertEqual(rtty._text_to_codes("1 A"), [rtty.FIGS, f["1"], rtty.SPACE, rtty.LETTER_TO_CODE["A"]])

    def test_newline_is_cr_lf(self):
        self.assertEqual(rtty._text_to_codes("A\nB"), [rtty.LETTER_TO_CODE["A"], rtty.CR, rtty.LF,
                                                       rtty.LETTER_TO_CODE["B"]])
        self.assertEqual(rtty._text_to_codes("A\r\nB"), rtty._text_to_codes("A\nB"))


class RttyLoopbackTests(unittest.TestCase):
    MESSAGE = "CQ CQ DE GM4BRI GM4BRI PSE K 1234567890"

    def test_clean_loopback(self):
        audio = rtty.Encoder().render(text=self.MESSAGE)
        self.assertEqual(_decode(audio), self.MESSAGE)

    def test_every_character_round_trips(self):
        # All 26 letters and every printable figure, figures run together and
        # broken up by spaces (so FIGS, LTRS and unshift-on-space are all
        # exercised in both directions), and a line break.
        figs = "".join(f for _, _, f in rtty._ROWS if f and len(f) == 1 and f.isprintable() and f != " ")
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        text = (letters + " " + figs + "\n" + " ".join(figs) + " " + "".join(a + b for a, b in zip(letters, figs))
                + " 73 DE GM4BRI 599 599 K")
        self.assertEqual(len(set(figs)), 25)
        self.assertEqual(_decode(rtty.Encoder().render(text=text)), text)

    def test_noisy_loopback(self):
        audio = rtty.Encoder().render(text=self.MESSAGE)
        rng = np.random.default_rng(5)
        noisy = audio + rng.normal(0, 0.4, len(audio)).astype(np.float32)
        self.assertEqual(_decode(noisy), self.MESSAGE)

    def test_fed_in_small_ragged_blocks(self):
        # feed() must tolerate any block length, not just the 100 ms blocks
        # every other test happens to use -- a real audio pipeline won't
        # politely hand over whole-frame-aligned chunks.
        audio = rtty.Encoder().render(text="CQ DE TEST")
        events = []
        dec = rtty.Decoder(events.append)
        i = 0
        sizes = [37, 101, 5, 250, 1, 900]
        s = 0
        while i < len(audio):
            n = sizes[s % len(sizes)]
            s += 1
            dec.feed(audio[i:i + n], t=i / FS)
            i += n
        self.assertEqual(dec.text, "CQ DE TEST")

    def test_different_shift_and_centre(self):
        audio = rtty.Encoder().render(text="TEST DE OPERATOR", shift=850.0, center=1500.0)
        text = _decode(audio, shift=850.0, center=1500.0)
        self.assertEqual(text, "TEST DE OPERATOR")

    def test_reset_clears_state(self):
        dec = rtty.Decoder(lambda e: None)
        dec.feed(rtty.Encoder().render(text="E"), t=0.0)
        dec.reset()
        self.assertEqual(dec.text, "")


class RttyShiftStateTests(unittest.TestCase):
    """The screenshot's fault: our own "CQ CQ CQ de GM4BRI" came back as
    ":1 :1 $3 &.4BRI" because the decoder was left in FIGS by noise and the
    transmission never said LTRS."""

    def test_a_transmission_opens_in_letters_whatever_the_decoder_was_in(self):
        enc = rtty.Encoder()
        left_in_figs = enc.render_codes([rtty.FIGS])
        audio = np.concatenate([left_in_figs, enc.render(text="CQ CQ DE GM4BRI")])
        self.assertEqual(_decode(audio), "CQ CQ DE GM4BRI")

    def test_decoder_unshifts_on_space(self):
        # FIGS 1 SPACE then Q's code with no shift in between: a USOS
        # receiver (fldigi's default) prints "1 Q"; without USOS it was "1 1".
        enc = rtty.Encoder()
        audio = enc.render_codes([rtty.FIGS, rtty.FIGURE_TO_CODE["1"], rtty.SPACE, rtty.LETTER_TO_CODE["Q"]])
        self.assertEqual(_decode(audio), "1 Q")

    def test_no_control_character_is_printed(self):
        # Every code in both shifts. A teleprinter printed nothing for CR,
        # BELL or blank; handed to the terminal raw they drew as empty boxes
        # (the screenshot's box was a noise-decoded FIGS S, which is BELL).
        # LF is the line break and stays.
        enc = rtty.Encoder()
        codes = []
        for shift in (rtty.LTRS, rtty.FIGS):
            for c, _, _ in rtty._ROWS:
                if c not in (rtty.LTRS, rtty.FIGS):
                    codes += [shift, c]
        heard = _decode(enc.render_codes(codes))
        self.assertIn("\n", heard)
        self.assertEqual([ch for ch in heard if not ch.isprintable() and ch != "\n"], [])


class RttyNoiseTests(unittest.TestCase):
    MESSAGE = "CQ CQ CQ DE GM4BRI GM4BRI GM4BRI PSE K"

    def test_noise_prints_nothing(self):
        # Unsquelched, a minute of noise printed ~300 characters: the garbage
        # around the screenshot's message, and the source of its FIGS state.
        rng = np.random.default_rng(1)
        heard = _decode((0.3 * rng.standard_normal(int(60 * FS))).astype(np.float32))
        self.assertLessEqual(len(heard), 1, repr(heard))

    def test_message_out_of_noise_copies_down_to_minus_3_db(self):
        # Ideal noncoherent FSK at 45.45 Bd reaches 1e-3 bit errors at about
        # -7 dB SNR in 3 kHz (Eb/N0 10.9 dB, Proakis); this decoder, with its
        # squelch, copies cleanly to -3 dB, and at 25 Hz off tune too.
        # Everything printed counts - noise before and after included.
        audio = rtty.Encoder().render(text=self.MESSAGE)
        for snr in (14, 3, -3):
            for off in (0.0, 25.0):
                cers = []
                for seed in range(4):
                    a = audio if off == 0 else rtty.Encoder().render(text=self.MESSAGE, center=1000.0 + off)
                    cers.append(_cer(_decode(_in_noise(a, snr, seed)), self.MESSAGE))
                with self.subTest(snr=snr, off=off):
                    self.assertLessEqual(float(np.mean(cers)), 0.03, cers)


class RttyOwnEchoTests(unittest.TestCase):
    """Our own transmission, round NB's simulated transponder at the
    conditions of the RTTY screenshot (docs/screenshots/main-rtty-1920.png,
    ohsnb/ui/screenshots.py): the band populated, our echo 250 ms late and
    25 Hz high until TX lock pulls it in, about +14 dB SNR in 3 kHz, and the
    decoder listening to noise for seconds before it arrives."""

    def test_echo_at_the_screenshot_snr(self):
        from helpers import make_radio, run_sim, wait_rx_lock
        tmp = tempfile.mkdtemp()
        try:
            r = make_radio(tmp, simSeed=11, simSignals=True, simRxErrorHz=1800.0, simUlErrorHz=25.0,
                           txGain=-30.0, simRefGainDb=-20.0, mode="rtty", vfo=10_489_575_000.0)
            ev = r.subscribe("events", 2000)
            r.start()
            try:
                if not r.state()["modes"]["rtty"]["encode"]:
                    self.skipTest("RTTY not available: " + r.state()["modes"]["rtty"]["missing"])
                self.assertTrue(wait_rx_lock(r))
                got = run_sim(r, 4.0, [ev])["events"]
                text = "CQ CQ CQ DE GM4BRI GM4BRI GM4BRI PSE K"
                r.send("rtty", text=text)
                got += run_sim(r, 25.0, [ev], until=lambda: not r.state()["keyed"])["events"]
                got += run_sim(r, 3.0, [ev])["events"]
            finally:
                r.stop()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        heard = "".join(e.get("text", "") for e in got if e.get("mode") == "rtty")
        # Measured 0.97-1.34 before (seeds 1-6, 11), now 0 on all of them.
        self.assertLessEqual(_cer(heard, text), 0.03, repr(heard))


class TerminalControlCharacterTests(unittest.TestCase):
    """Whatever a decoder emits, the keyboard terminal never draws a control
    code as an empty box. PSK's varicode spans all 256 byte values, so it
    can hand over NUL, BEL or ESC as readily as RTTY once did BELL."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_control_codes_never_reach_the_terminal(self):
        from ohscore.ui.panels.common import Terminal
        from ohscore.ui.panels.text import TEXT_MODES, TextPanel
        panel = types.SimpleNamespace(modes=TEXT_MODES, cw=False, term=Terminal())
        for mode, text in (("rtty", "AB"), ("rtty", "\a"), ("psk31", "\x00"), ("psk31", "C\r"), ("psk31", "\n"),
                           ("psk31", "D\x1b\x07\x85\x7fE"), ("psk31", "\tF")):
            TextPanel.on_event(panel, {"mode": mode, "text": text})
        shown = panel.term.toPlainText()
        self.assertEqual(shown, "ABC\nDE\tF")
        panel.term.deleteLater()


if __name__ == "__main__":
    unittest.main()
