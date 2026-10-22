import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""Sending KG-STV (ohscore/modes/kgstv.py): an over is the receiver's exact
inverse. Every test sends audio the way the engine will and hears it with
NB's own receiver (ohscore/dsp/kgstv.py Receiver and Pictures, fed as the
background receiver feeds them: mixed down from 1500 Hz and low-passed to
1.2 kHz), so a transmitter that drifted from what the receiver reads - and
the receiver was proved on real stations' frames (test_kgstv.py) - fails
here.

The band's part is what QO-100 does to a KG-STV picture: noise at the
SNRs pictures are copied at, an offset of a few hundred hertz (an LNB that
beacon lock has not finished with), a sound card whose clock is 300 ppm
out, and a receiver that tunes in half way."""
import unittest
from unittest import mock

import numpy as np

from ohscore.dsp import kgstv as codec
from ohscore.modes import MODES
from ohscore.modes import kgstv

from test_kgstv import card

RATE = 12000.0
LINE = "GM4BRI IO75RL"


def hear(audio, chunk=2400, tail_s=35.0):
    """Audio through the decoder; then quiet long enough for a picture
    with no end frame to time out. Returns (events, decoder)."""
    out = []
    dec = kgstv.Decoder(out.append)
    for i in range(0, len(audio), chunk):
        dec.feed(audio[i:i + chunk])
    dec.freq_heard = dec.rx.freq        # before the quiet lets the centre wander
    dec.feed(np.zeros(int(tail_s * RATE), np.float32))
    return out, dec


def frames_heard(audio, chunk=2400):
    """The receiver's frame events for `audio`, as the decoder mixes it."""
    rx = codec.Receiver(RATE)
    dec = kgstv.Decoder(lambda e: None)
    got = []
    dec.rx = rx
    orig = rx.feed

    def feed(y):
        ev = orig(y)
        got.extend(e for e in ev if e["kind"] == "frame")
        return ev
    rx.feed = feed
    for i in range(0, len(audio), chunk):
        dec.feed(audio[i:i + chunk])
    dec.feed(np.zeros(int(RATE), np.float32))
    return got, rx


def with_noise(a, snr_db, seed=1):
    """White noise at `snr_db` in 2.5 kHz (the SSB channel's width, as
    test_kgstv measures SNR)."""
    rng = np.random.default_rng(seed)
    sig = float(np.mean(a.astype(np.float64) ** 2))
    npow = sig * 10 ** (-snr_db / 10) * (RATE / 2) / 2500.0
    return (a + rng.standard_normal(len(a)) * np.sqrt(npow)).astype(np.float32)


def shifted(a, hz):
    """Real audio moved up `hz` (an analytic signal's shift)."""
    n = len(a)
    X = np.fft.fft(a)
    h = np.zeros(n)
    h[0] = 1
    h[1:(n + 1) // 2] = 2
    if n % 2 == 0:
        h[n // 2] = 1
    z = np.fft.ifft(X * h)
    return np.real(z * np.exp(2j * np.pi * hz * np.arange(n) / RATE)).astype(np.float32)


def fast_clock(a, ppm):
    """The audio as a sender whose sound card runs `ppm` fast makes it."""
    t = np.arange(0, len(a) - 1, 1 + ppm * 1e-6)
    i = t.astype(int)
    f = t - i
    return (a[i] * (1 - f) + a[i + 1] * f).astype(np.float32)


def block_of(rgb, x, y):
    return rgb[y * 16:(y + 1) * 16, x * 16:(x + 1) * 16]


class RoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = card()
        cls.tx = kgstv.Transmission(cls.img, LINE)
        cls.audio = cls.tx.audio()
        cls.preview = cls.tx.preview()

    def test_every_frame_comes_back_as_it_was_sent(self):
        # Block for block, in order: command, place, scale and the data
        # bits themselves, and the callsign line's text exactly.
        got, rx = frames_heard(self.audio)
        sent = self.tx.frames
        self.assertEqual(len(got), len(sent))
        for g, s in zip(got, sent):
            self.assertEqual((g["com"], g["x"], g["y"], g["sc"], g["mode"]), (s["com"], s["x"], s["y"], s["sc"],
                                                                             "MSK/NORM"))
            if s["data"] is not None:
                self.assertTrue(np.array_equal(g["data"], s["data"]))
        calls = {codec.text_of(g["data"]) for g in got if g["com"] == 6}
        self.assertEqual(calls, {LINE})
        self.assertEqual((rx.lost, rx.repaired), (0, 0))
        self.assertEqual([s["com"] for s in sent].count(1), 300)
        self.assertEqual([s["com"] for s in sent][:5], [6] * 5)
        self.assertEqual([s["com"] for s in sent][-kgstv.END_REPEATS:], [3] * kgstv.END_REPEATS)

    def test_the_picture_is_painted_as_the_preview_shows_it(self):
        out, _dec = hear(self.audio)
        done = [e for e in out if e["state"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["why"], done[0]["call"], done[0]["blocks"], done[0]["bad"]), ("end", LINE, 300, 0))
        self.assertTrue(np.array_equal(done[0]["rgb"], self.preview))
        # And the preview is the picture, as closely as JPEG-like coding at
        # x1.0 allows: a few levels on average.
        err = np.abs(self.preview.astype(int) - self.img.astype(int)).mean()
        self.assertLess(err, 6.0)

    def test_the_over_is_as_long_as_its_bits_and_says_so(self):
        self.assertEqual(len(self.audio), int(round(self.tx.seconds * RATE)))
        self.assertAlmostEqual(self.tx.seconds, len(self.tx.bits) / 1200.0)
        self.assertLessEqual(float(np.max(np.abs(self.audio))), kgstv.LEVEL + 1e-6)
        # Faded in and out: the first and last samples are silent.
        self.assertLess(abs(float(self.audio[0])), 1e-3)
        self.assertLess(abs(float(self.audio[-1])), 0.02)

    def test_the_tones_are_kgstvs(self):
        # Each bit is a burst of 1800 Hz for a 1 and 1200 Hz for a 0 - what
        # a KG-STV station's waterfall markers frame: over every bit the
        # right tone correlates better than the other.
        bits = self.tx.bits[:3000]
        a = self.audio[:len(bits) * 10].astype(np.float64).reshape(-1, 10)
        t = np.arange(len(bits) * 10).reshape(-1, 10) / RATE
        e = {f: np.abs((a * np.exp(-2j * np.pi * f * t)).sum(1)) for f in (1200.0, 1800.0)}
        hi = e[1800.0] > e[1200.0]
        self.assertTrue(np.array_equal(hi[8:], bits[8:] > 0))          # past the 5 ms fade-in
        # And nothing much outside them: 99 % of the over's power within
        # 700-2300 Hz of the dial.
        P = np.abs(np.fft.rfft(self.audio)) ** 2
        f = np.fft.rfftfreq(len(self.audio), 1 / RATE)
        self.assertGreater(P[(f > 700) & (f < 2300)].sum() / P.sum(), 0.99)

    def test_progress_counts_blocks_as_they_finish(self):
        tx = self.tx
        self.assertEqual(tx.blocks_sent(0.0), 0)
        self.assertEqual(tx.blocks_sent(tx.seconds), 300)
        # Block 120 is wholly on the air at the end of its frame, not before.
        end_120 = tx.block_ends[119] / 1200.0
        self.assertEqual(tx.blocks_sent(end_120 - 0.01), 119)
        self.assertEqual(tx.blocks_sent(end_120), 120)
        steps = [tx.blocks_sent(t) for t in np.linspace(0, tx.seconds, 400)]
        self.assertEqual(steps, sorted(steps))


class TheBand(unittest.TestCase):
    """What QO-100 does to a picture on its way, and what survives."""

    @classmethod
    def setUpClass(cls):
        cls.tx = kgstv.Transmission(card(), LINE)
        cls.audio = cls.tx.audio()
        cls.preview = cls.tx.preview()

    def check_no_wrong_block(self, out):
        for e in out:
            if e["state"] == "block":
                self.assertTrue(np.array_equal(e["rgb"], block_of(self.preview, e["x"], e["y"])))

    def test_a_good_signal_through_noise_is_whole(self):
        out, dec = hear(with_noise(self.audio, 12.0))
        done = [e for e in out if e["state"] == "done"]
        self.assertEqual((done[0]["blocks"], done[0]["call"]), (300, LINE))
        self.check_no_wrong_block(out)

    def test_a_weak_one_loses_blocks_never_paints_a_wrong_one(self):
        out, dec = hear(with_noise(self.audio, 8.0, seed=4))
        done = [e for e in out if e["state"] == "done"]
        self.assertGreater(done[0]["blocks"], 240)
        self.assertGreater(dec.rx.lost, 0)
        self.check_no_wrong_block(out)

    def test_an_offset_and_a_fast_sound_card(self):
        # 200 Hz high (beacon lock not settled), the sender's card 300 ppm
        # fast (35 bits of slip over this picture), at 15 dB.
        a = with_noise(fast_clock(shifted(self.audio, 200.0), 300.0), 15.0, seed=2)
        out, dec = hear(a)
        done = [e for e in out if e["state"] == "done"]
        self.assertEqual(done[0]["blocks"], 300)
        self.assertAlmostEqual(dec.freq_heard, 200.0, delta=20.0)
        self.check_no_wrong_block(out)

    def test_low_and_slow_too(self):
        a = with_noise(fast_clock(shifted(self.audio, -250.0), -300.0), 15.0, seed=3)
        out, _dec = hear(a)
        self.assertEqual([e["blocks"] for e in out if e["state"] == "done"], [300])

    def test_tuned_in_half_way(self):
        half = self.audio[len(self.audio) // 2:]
        out, _dec = hear(with_noise(half, 15.0, seed=5))
        done = [e for e in out if e["state"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertTrue(120 < done[0]["blocks"] < 180, done[0]["blocks"])
        # The callsign line comes again every ten blocks, so a late
        # receiver still knows whose picture it has.
        self.assertEqual(done[0]["call"], LINE)


class Pictures(unittest.TestCase):
    def test_a_wide_picture_loses_its_sides(self):
        # 640x360 (16:9): the middle 480 columns are kept, as KG-STV does.
        img = np.zeros((360, 640, 3), np.uint8)
        img[:, :80] = (255, 0, 0)
        img[:, 80:560] = (0, 200, 0)
        img[:, 560:] = (0, 0, 255)
        out = kgstv.fit_picture(img)
        self.assertEqual(out.shape, (240, 320, 3))
        self.assertTrue(np.all(out == (0, 200, 0)))

    def test_a_tall_one_loses_top_and_bottom(self):
        img = np.zeros((1000, 600, 3), np.uint8)
        img[:275] = 255
        img[725:] = 255
        img[275:725] = (10, 20, 30)
        out = kgstv.fit_picture(img)
        self.assertEqual(out.shape, (240, 320, 3))
        self.assertTrue(np.all(out == (10, 20, 30)))

    def test_shrinking_averages_and_alpha_is_dropped(self):
        # A one-pixel checkerboard four times too big averages to grey,
        # which point sampling would turn into black or white.
        y, x = np.mgrid[0:960, 0:1280]
        img = np.zeros((960, 1280, 4), np.uint8)
        img[..., :3] = (((x + y) % 2) * 255)[..., None]
        img[..., 3] = 7
        out = kgstv.fit_picture(img)
        self.assertTrue(np.all(np.abs(out.astype(int) - 128) <= 1))

    def test_a_small_one_is_enlarged(self):
        img = np.full((30, 40, 3), (90, 60, 30), np.uint8)
        self.assertTrue(np.all(kgstv.fit_picture(img) == (90, 60, 30)))

    def test_not_a_picture(self):
        with self.assertRaises(ValueError):
            kgstv.fit_picture(np.zeros((10, 10), np.uint8))


class Header(unittest.TestCase):
    def test_call_and_locator(self):
        self.assertEqual(kgstv.header(" gm4bri ", "io75rl"), "GM4BRI IO75RL")
        self.assertEqual(kgstv.header("GM4BRI"), "GM4BRI")

    def test_no_callsign_no_picture(self):
        with self.assertRaises(ValueError) as e:
            kgstv.header("", "IO75RL")
        self.assertIn("callsign", str(e.exception))
        with self.assertRaises(ValueError):
            kgstv.Encoder().render(picture=card(), callsign="", locator="IO75RL")

    def test_only_what_a_receiver_can_show(self):
        with self.assertRaises(ValueError):
            kgstv.header("GM4BRÏ")


class TimeLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(1)
        cls.busy = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)      # the slowest a picture gets

    def test_quality_sets_the_length(self):
        secs = [kgstv.Transmission(self.busy, LINE, q).seconds for q in kgstv.QUALITIES]
        self.assertEqual(secs, sorted(secs, reverse=True))

    def test_the_standard_quality_when_it_fits(self):
        self.assertEqual(kgstv.fitting_scale(card(), LINE, 300.0), kgstv.STANDARD)

    def test_a_coarser_one_when_it_does_not(self):
        t = {q: kgstv.Transmission(self.busy, LINE, q).seconds for q in kgstv.QUALITIES}
        limit = (t[12] + t[10]) / 2
        self.assertEqual(kgstv.fitting_scale(self.busy, LINE, limit), 12)
        self.assertIsNone(kgstv.fitting_scale(self.busy, LINE, t[15] - 1))

    def test_a_block_too_busy_for_the_size_field_is_coarsened_alone(self):
        # Shrink the size field so an ordinary busy block overflows it: that
        # block alone goes at a coarser scale, says so in its own frame,
        # and the receiver paints it at that scale.
        busy = self.busy[:16, :16]
        normal = len(codec.encode_block(busy, 10))
        with mock.patch.object(codec, "MAX_DATA_BITS", normal - 1):
            data, sc = codec.block_data(busy, 10)
            self.assertGreater(sc, 10)
            self.assertLessEqual(len(data), normal - 1)
            pic = np.zeros((240, 320, 3), np.uint8)
            pic[:16, :16] = busy
            tx = kgstv.Transmission(pic, LINE)
        first = next(f for f in tx.frames if f["com"] == 1)
        self.assertEqual(first["sc"], sc)
        got, _rx = frames_heard(tx.audio())
        g = next(f for f in got if f["com"] == 1)
        self.assertEqual(g["sc"], sc)
        self.assertTrue(np.array_equal(codec.decode_block(g["data"], g["sc"]), block_of(tx.preview(), 0, 0)))


class Registry(unittest.TestCase):
    def test_the_mode_registry_sends_and_hears_it(self):
        info = MODES["kgstv"]
        self.assertTrue(info.available)
        audio = info.make_encoder(picture=np.full((48, 64, 3), 200, np.uint8), callsign="GM4BRI", locator="IO75RL")
        out = []
        dec = info.make_decoder(out.append)
        for i in range(0, len(audio), 4800):
            dec.feed(audio[i:i + 4800], t=0.0)
        self.assertEqual([(e["blocks"], e["call"]) for e in out if e["state"] == "done"], [(300, LINE)])


if __name__ == "__main__":
    unittest.main()
