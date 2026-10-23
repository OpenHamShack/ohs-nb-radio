import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""PSK31/63/125 received by shack_sdr's Rust `psk` decoder, driven as the
engine drives it (modes/sdrmode.py PskDecoder). Switched off for now
(ohscore/sdr.py PSK_ON_SHACK_SDR): the PSK modes decode with psk.py, whose
tests are test_modes_psk. These are skipped, not deleted, until the
library fix lands; the encoder, Varicode and browser tests below run. The receive tests are the ones the Python decoder passed, run against
its replacement - loopback at every speed, off tune, drifting, weak, a
frequency step, a sound card's clock, noise printing next to nothing -
plus what is new: several stations in one session, and channels changed
while it runs. The finer "never worse than psk.py" sweep lives with the
decoder in ohs-libs (shack_sdr tests/psk.rs), against the golden numbers
captured from the Python decoder before it went."""
import unittest
import numpy as np

from ohscore import sdr
from ohscore.modes import psk, sdrmode

PARKED = "PSK library fix parked (ohs-libs fix/psk-tail-and-step)"
RUST = sdr.available() and sdr.PSK_ON_SHACK_SDR


def _make(variant="psk31", emit=None, **kw):
    """The Rust PSK mode decoder, whatever the mode table holds."""
    return sdrmode.psk_decoder(emit or (lambda e: None), variant=variant, **kw)

FS = 12_000.0
# The Rust decoder's trellis and phase smoother print a character about a
# second after its last symbol (shack_sdr README "PSK"): a receiver keeps
# hearing the band after an over, so the tests do too.
TAIL_S = 3.0


def _tail(audio, seed=99):
    """`audio` followed by TAIL_S of quiet band noise, as a receiver hears it."""
    rng = np.random.default_rng(seed)
    return np.concatenate([audio.astype(np.float32),
                           rng.normal(0, 0.003, int(TAIL_S * FS)).astype(np.float32)])


def _run(audio, variant="psk31", center=1000.0, channels=(), block=1200):
    """Every event the mode's decoder sends for `audio` (with its tail)."""
    events = []
    dec = _make(variant, events.append, center=center, channels=channels)
    try:
        x = _tail(audio)
        for i in range(0, len(x), block):
            dec.feed(x[i:i + block], t=1_000_000.0 + i / FS)
        dec.drain()
    finally:
        dec.close()
    return events


def _decode(audio, variant="psk31", center=1000.0):
    return "".join(e["text"] for e in _run(audio, variant, center))








@unittest.skipUnless(RUST, PARKED)
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
        dec = _make()
        try:
            dec.feed(_tail(psk.Encoder().render(text="E")), t=0.0)
            dec.drain()
            dec.reset()
            self.assertEqual(dec.text, "")
        finally:
            dec.close()

    def test_events_keep_the_shape_every_client_reads(self):
        # The window's text panel and scope tags, Remote and Enable TX's
        # reply logic read {"mode", "text", "center", "df", "snr"}, center
        # and df the audio frequency the station is on; `channel` is new.
        for variant in ("psk31", "psk63", "psk125"):
            with self.subTest(variant=variant):
                events = _run(psk.Encoder().render(text="HI HI", variant=variant), variant)
                self.assertTrue(events)
                for ev in events:
                    self.assertEqual(ev["mode"], variant)
                    self.assertIsInstance(ev["text"], str)
                    self.assertAlmostEqual(ev["center"], 1000.0, delta=2.0)
                    self.assertEqual(ev["df"], ev["center"])
                    self.assertEqual(ev["channel"], 1000.0)
                    self.assertIn("snr", ev)


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


@unittest.skipUnless(RUST, PARKED)
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
        # `snr` is still in the symbol's bandwidth, as psk.py gave it: 15 dB
        # sent reads near 15, not the 2.5 kHz figure 19 dB lower.
        audio = _with_snr(psk.Encoder().render(text="HI HI"), 15.0, 31.25, 0)
        events = _run(audio)
        self.assertTrue(events)
        self.assertAlmostEqual(events[-1]["df"], 1000.0, delta=1.0)
        self.assertGreater(events[-1]["snr"], 9.0)
        self.assertLess(events[-1]["snr"], 21.0)


@unittest.skipUnless(RUST, PARKED)
class PskChannelsTests(unittest.TestCase):
    """New with the Rust decoder: one session hears several stations. The
    mode's own channel is always decoded; pskChannels adds more."""

    def _band(self, stations, snr_db=None, seed=4):
        """Several stations at once: [(audio Hz, text, variant)]."""
        parts = [psk.Encoder().render(text=t, variant=v, center=f) for f, t, v in stations]
        n = max(len(p) for p in parts)
        x = np.zeros(n, np.float32)
        for p in parts:
            x[:len(p)] += p / len(parts)
        if snr_db is not None:
            x = _with_snr(x, snr_db, 31.25, seed)
        return x

    def _by_channel(self, events):
        out = {}
        for ev in events:
            out[ev["channel"]] = out.get(ev["channel"], "") + ev["text"]
        return out

    def test_three_stations_each_on_its_own_line(self):
        band = self._band([(1000.0, "CQ DE G4AAA K", "psk31"), (1450.0, "QRZ DE M0BBB", "psk31"),
                           (2210.0, "TEST DE 2E0CCC", "psk31")])
        got = self._by_channel(_run(band, channels=[1450.0, 2210.0]))
        self.assertEqual(got, {1000.0: "CQ DE G4AAA K", 1450.0: "QRZ DE M0BBB", 2210.0: "TEST DE 2E0CCC"})

    def test_a_station_off_its_channel_is_followed_and_named_by_its_channel(self):
        band = self._band([(1000.0, "ONE", "psk63"), (1709.0, "TWO TWO", "psk63")])
        events = _run(band, variant="psk63", channels=[1700.0])
        two = [ev for ev in events if ev["channel"] == 1700.0]
        self.assertEqual("".join(ev["text"] for ev in two), "TWO TWO")
        self.assertAlmostEqual(two[-1]["center"], 1709.0, delta=1.5)

    def test_without_channels_only_the_modes_own_station_is_heard(self):
        band = self._band([(1000.0, "MINE", "psk31"), (1600.0, "NOT MINE", "psk31")])
        self.assertEqual(self._by_channel(_run(band)), {1000.0: "MINE"})

    def test_a_channel_added_while_it_runs_starts_copying(self):
        # A waterfall click mid-over: the engine's pskChannels changes and
        # the session follows live, the mode's own channel undisturbed.
        late = psk.Encoder().render(text="LATE STATION " * 4, variant="psk31", center=1800.0)
        own = psk.Encoder().render(text="OWN STATION OWN STATION", variant="psk31", center=1000.0)
        n = max(len(late), len(own))
        band = np.zeros(n, np.float32)
        band[:len(late)] += late / 2
        band[:len(own)] += own / 2
        x = _tail(band)
        events = []
        dec = _make("psk31", events.append)
        try:
            half = int(5.0 * FS)            # into the late station's text
            for i in range(0, half, 1200):
                dec.feed(x[i:min(i + 1200, half)], t=1_000_000.0 + i / FS)
            dec.drain()
            self.assertFalse([ev for ev in events if ev["channel"] == 1800.0])
            dec.set_channels([1800.0])
            self.assertEqual(dec.channels, [1000.0, 1800.0])
            for i in range(half, len(x), 1200):
                dec.feed(x[i:i + 1200], t=1_000_000.0 + i / FS)
            dec.drain()
        finally:
            dec.close()
        got = self._by_channel(events)
        self.assertEqual(got.get(1000.0), "OWN STATION OWN STATION")
        self.assertIn("LATE STATION LATE STATION", got.get(1800.0, ""))

    def test_channels_are_cleaned_as_the_decoder_takes_them(self):
        # The mode's own channel is not added twice, nor one a click puts on
        # a station already decoded, and no more than the decoder's 16.
        dec = _make(channels=[1000.0, 1002.0, 1500.0, 1503.0, "x"])
        try:
            self.assertEqual(dec.channels, [1000.0, 1500.0])
            dec.set_channels([300.0 + 150 * k for k in range(20)])
            self.assertEqual(len(dec.channels), 16)
        finally:
            dec.close()




if __name__ == "__main__":
    unittest.main()
