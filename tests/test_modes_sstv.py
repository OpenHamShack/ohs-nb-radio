import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""SSTV: sstv.py's encoder, VIS header and PNG writer, and the mode's
receive, which is shack_sdr's Rust `sstv` decoder driven as the engine
drives it (modes/sdrmode.py SstvDecoder) since Radio's SDR milestone 2.

The receive tests are the ones the Python decoder passed, run against its
replacement: what our own encoder sends in each of its four modes comes
back as the picture sent, in noise, from a slow sound card, joined part
way; noise and a steady tone start nothing; ragged blocks are fine. They
read the events the SSTV panel and Remote paint from (start, a row at a
time, done with the PNG). The finer "never worse than sstv.py" sweep, and
the ten modes sstv.py never had, live with the decoder in ohs-libs
(shack_sdr tests/sstv.rs), against the golden numbers captured from the
Python decoder before it went."""
import base64
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np

from ohscore import sdr
from ohscore.modes import MODES, sstv

FS = 12_000.0


def _read_png(path) -> np.ndarray:
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = b""
    w = h = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
        elif tag == b"IDAT":
            idat += chunk
        pos += 8 + length + 4
    raw = zlib.decompress(idat)
    rowlen = w * 3 + 1
    rows = [np.frombuffer(raw[y * rowlen + 1:(y + 1) * rowlen], dtype=np.uint8).reshape(w, 3)
            for y in range(h)]
    return np.stack(rows)


def _png(data: bytes) -> np.ndarray:
    """A PNG the decoder wrote (it filters its rows, which _read_png, made
    for sstv._write_png's unfiltered ones, does not undo)."""
    from shack_sdr import sstv as rust
    return rust.png_rgb(data)


def _decode_audio(audio, block=1200, folder=None):
    """Every event the mode's decoder sends for `audio`, and the folder its
    pictures went to."""
    folder = folder or tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
    events = []
    dec = MODES["sstv"].make_decoder(events.append, out_dir=folder)
    try:
        x = np.concatenate([audio.astype(np.float32), np.zeros(int(2.0 * FS), np.float32)])
        for i in range(0, len(x), block):
            dec.feed(x[i:i + block], t=1_000_000.0 + i / FS)
        dec.drain(quiet_s=0.6)
    finally:
        dec.close()
    return events, folder


def _decode_image(img: np.ndarray, mode: str, noise_std: float = 0.0, seed: int = 1, cut: float = 0.0):
    audio = sstv.Encoder().render(image=img, mode=mode)
    if cut:
        audio = audio[int(cut * len(audio)):]
    if noise_std:
        rng = np.random.default_rng(seed)
        audio = audio + rng.normal(0, noise_std, len(audio)).astype(np.float32)
    return _decode_audio(audio)


def _picture(events):
    """The finished picture as the decoder saved it, and its start event."""
    start = next(e for e in events if e["state"] == "start")
    done = next(e for e in events if e["state"] == "done")
    with open(done["path"], "rb") as f:
        return _png(f.read()), start, done


def _gradient_image(h, w):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = np.linspace(0, 255, w)[None, :]
    img[:, :, 1] = np.linspace(0, 255, h)[:, None]
    img[:, :, 2] = 128
    return img


class PngWriterTests(unittest.TestCase):
    def test_round_trips_pixels(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, (12, 20, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.png"
            sstv._write_png(path, img)
            self.assertGreater(path.stat().st_size, 0)
            back = _read_png(path)
        np.testing.assert_array_equal(img, back)

    def test_starts_with_png_signature(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.png"
            sstv._write_png(path, np.zeros((2, 2, 3), dtype=np.uint8))
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class VisCodeTests(unittest.TestCase):
    def test_bits_have_even_parity(self):
        for mode_id in (8, 44, 60, 95):
            bits = sstv._vis_bits(mode_id)
            self.assertEqual(len(bits), 8)
            self.assertEqual(sum(int(b) for b in bits) % 2, 0)

    def test_mode_table_round_trips_through_vis_to_mode(self):
        for name, spec in sstv.MODES.items():
            self.assertEqual(sstv.VIS_TO_MODE[spec["vis"]], name)


BARS = np.array([[255, 255, 0], [0, 255, 255], [0, 255, 0], [255, 0, 255],
                 [255, 0, 0], [0, 0, 255], [0, 0, 0], [128, 128, 128]], dtype=np.uint8)


def _bars(h, w):
    """Eight colour bars (each channel on in a different pattern, so a
    swapped or misplaced channel shows as the wrong colour) inside a white
    border (so a picture shifted sideways shows at its edges). No bar is
    white, so every border edge is an edge."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for k in range(8):
        img[:, k * w // 8:(k + 1) * w // 8] = BARS[k]
    b = w // 40
    img[:b], img[-b:], img[:, :b], img[:, -b:] = 255, 255, 255, 255
    return img


def _edge_columns(img, rows):
    """Where, along a row, the picture changes most sharply near each true
    bar boundary and border edge -- the decoded picture's own edges, found
    rather than assumed."""
    prof = img[rows].astype(float).mean(axis=0)               # w x 3
    grad = np.abs(np.diff(prof, axis=0)).sum(axis=1)          # change between x and x+1
    w = img.shape[1]
    b = w // 40
    truth = [b] + [k * w // 8 for k in range(1, 8)] + [w - b]
    found = []
    for x in truth:
        # (Not the first or last pixel pair: every scan's first and last
        # pixel carry the demodulator's transient from the tone before it.)
        lo, hi = max(1, x - w // 20), min(len(grad) - 1, x + w // 20)
        found.append(lo + int(np.argmax(grad[lo:hi])) + 1)
    return truth, found


# The Rust decoder's ids for sstv.py's four (shack_sdr sstv.modes()).
RUST_ID = {"robot36": "robot36", "martinm1": "martin1", "scottie_s1": "scottie1", "pd120": "pd120"}


def _psnr(a, b):
    err = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return 10 * np.log10(255.0 ** 2 / max(err, 1e-9))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OurPicturesComeBack(unittest.TestCase):
    """What sstv.py sends, in each of its four modes, decoded by the Rust
    decoder: the transmit path is unchanged and must stay readable."""

    def test_every_mode_we_send_decodes_as_the_picture_sent(self):
        for mode, spec in sstv.MODES.items():
            with self.subTest(mode=mode):
                img = _gradient_image(spec["height"], spec["width"])
                events, _ = _decode_image(img, mode)
                got, start, _done = _picture(events)
                self.assertEqual(start["fmt"], RUST_ID[mode])
                self.assertEqual(got.shape, img.shape)
                self.assertGreater(_psnr(got, img), 25.0)

    def test_every_bar_edge_is_where_it_was_sent(self):
        # The fault the Python decoder's alignment tests pinned: pictures
        # shifted sideways. Colour bars in a white border, every edge found
        # within two pixels of where it was sent, in each mode we send.
        for mode, spec in sstv.MODES.items():
            with self.subTest(mode=mode):
                img = _bars(spec["height"], spec["width"])
                got, _start, _done = _picture(_decode_image(img, mode, noise_std=0.1)[0])
                truth, found = _edge_columns(got, slice(spec["height"] // 6, spec["height"] * 5 // 6))
                for t, f in zip(truth, found):
                    self.assertLessEqual(abs(t - f), 2, f"edge at {t} found at {f}")

    def test_modest_noise_still_recovers(self):
        for mode in ("robot36", "martinm1"):
            with self.subTest(mode=mode):
                spec = sstv.MODES[mode]
                img = _gradient_image(spec["height"], spec["width"])
                events, _ = _decode_image(img, mode, noise_std=0.3, seed=3)
                got, _start, _done = _picture(events)
                self.assertGreater(_psnr(got, img), 18.0)

    def test_a_picture_joined_part_way_starts_from_its_line_syncs(self):
        # Tuned in, or the radio started, 40 % into a picture: no header.
        spec = sstv.MODES["scottie_s1"]
        img = _gradient_image(spec["height"], spec["width"])
        events, _ = _decode_image(img, "scottie_s1", cut=0.4)
        got, start, _done = _picture(events)
        self.assertTrue(start.get("partial"))
        self.assertEqual(start["fmt"], "scottie1")
        rows = got.shape[0]
        self.assertGreater(rows, 100)
        # The rows it has are the bottom of the picture, in place.
        self.assertGreater(_psnr(got[-rows // 2:], img[-rows // 2:]), 20.0)

    def test_a_slow_sound_card_is_followed(self):
        # The sending card's 12 kHz is 11.994: 500 ppm slow over the picture.
        spec = sstv.MODES["martinm1"]
        img = _gradient_image(spec["height"], spec["width"])
        tx = sstv.Encoder().render(image=img, mode="martinm1").astype(np.float64)
        n = len(tx)
        slid = np.interp(np.arange(int(n * 1.0005)) / 1.0005, np.arange(n), tx).astype(np.float32)
        events, _ = _decode_audio(slid)
        got, _start, _done = _picture(events)
        self.assertGreater(_psnr(got, img), 22.0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheEvents(unittest.TestCase):
    """The shapes the SSTV panel and Remote paint from (sdrmode.SstvDecoder)."""

    def test_start_rows_as_they_come_then_done_with_the_file(self):
        spec = sstv.MODES["robot36"]
        img = _gradient_image(spec["height"], spec["width"])
        events, folder = _decode_image(img, "robot36")
        start = events[0]
        self.assertEqual((start["mode"], start["state"], start["width"], start["height"]),
                         ("sstv", "start", 320, 240))
        lines = [e for e in events if e["state"] == "line"]
        self.assertEqual(lines[0]["line"], 1)                       # counts from 1
        self.assertTrue(all(e["of"] == 240 and e["name"] == start["name"] for e in lines))
        self.assertEqual({e["line"] for e in lines}, set(range(1, 241)))
        row = base64.b64decode(lines[0]["row"])
        self.assertEqual(len(row), 320 * 3)
        done = events[-1]
        self.assertEqual((done["state"], done["name"]), ("done", start["name"]))
        self.assertEqual(Path(done["path"]).parent, Path(folder))
        self.assertEqual(Path(done["path"]).name, done["file"])
        # The rows painted are the picture saved (the last copy of each), to
        # within the few levels the decoder's final reading moves a row it
        # does not send again (a row is re-sent only when it moved).
        painted = np.zeros((240, 320, 3), np.uint8)
        for e in lines:
            painted[e["line"] - 1] = np.frombuffer(base64.b64decode(e["row"]), np.uint8).reshape(320, 3)
        with open(done["path"], "rb") as f:
            self.assertGreater(_psnr(painted, _png(f.read())), 45.0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class DecoderRobustnessTests(unittest.TestCase):
    def test_silence_and_noise_start_no_picture(self):
        rng = np.random.default_rng(2)
        for name, audio in (("silence", np.zeros(int(5 * FS), np.float32)),
                            ("noise", rng.normal(0, 0.3, int(30 * FS)).astype(np.float32)),
                            ("a steady 1200 Hz tone", (0.5 * np.sin(2 * np.pi * 1200 * np.arange(int(10 * FS)) / FS))
                             .astype(np.float32))):
            with self.subTest(name):
                events, folder = _decode_audio(audio)
                self.assertFalse([e for e in events if e["state"] in ("start", "done")])
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_ragged_block_sizes(self):
        spec = sstv.MODES["robot36"]
        img = _gradient_image(spec["height"], spec["width"])
        audio = sstv.Encoder().render(image=img, mode="robot36")
        for block in (37, 1001):
            with self.subTest(block=block):
                events, _ = _decode_audio(audio, block=block)
                got, _start, _done = _picture(events)
                self.assertGreater(_psnr(got, img), 25.0)

    def test_reset_forgets_a_picture_half_heard(self):
        spec = sstv.MODES["robot36"]
        audio = sstv.Encoder().render(image=_gradient_image(spec["height"], spec["width"]), mode="robot36")
        events = []
        dec = MODES["sstv"].make_decoder(events.append, out_dir=tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
        try:
            dec.feed(audio[:len(audio) // 3], t=0.0)
            dec.drain()
            self.assertEqual(events[0]["state"], "start")
            dec.reset()
            dec.drain()
            self.assertFalse([e for e in events if e["state"] == "done"])
        finally:
            dec.close()


class EncoderTimingTests(unittest.TestCase):
    """What we send must keep to the specification's line period, or every
    other station's receiver slants our picture. Measured from the rendered
    audio itself: where each sync pulse actually begins."""

    def _sync_starts(self, audio):
        # Instantaneous frequency from the analytic signal; a sync is where
        # it drops below 1350 Hz after being above it.
        X = np.fft.fft(audio.astype(np.float64))
        n = len(audio)
        X[n // 2 + 1:] = 0
        X[1:n // 2] *= 2
        ph = np.unwrap(np.angle(np.fft.ifft(X)))
        f = np.diff(ph) * FS / (2 * np.pi)
        low = f < 1350
        return np.flatnonzero(low[1:] & ~low[:-1]) + 1

    def test_line_period_has_no_rounding_drift(self):
        for mode in ("martinm1", "pd120"):
            with self.subTest(mode=mode):
                spec = sstv.MODES[mode]
                img = np.full((spec["height"], spec["width"], 3), 128, np.uint8)
                audio = sstv.Encoder().render(image=img, mode=mode)
                starts = self._sync_starts(audio)
                line_ms = {"martinm1": 446.446, "pd120": 508.48}[mode]
                vis_ms = 300 + 10 + 300 + 30 + 8 * 30 + 30
                syncs = starts[starts > vis_ms / 1000 * FS + 10]   # after the header's own 1200 Hz pulses
                n_lines = spec["height"] // (2 if mode == "pd120" else 1)
                self.assertEqual(len(syncs), n_lines - 1)        # the first abuts the stop bit
                expect = (vis_ms + line_ms * np.arange(1, n_lines)) / 1000 * FS
                self.assertLess(np.abs(syncs - expect).max(), 2.0)


class VisBitConventionTests(unittest.TestCase):
    """Pins the VIS data-bit frequency convention against the Dayton
    paper's calibration-header table literally (1=1100 Hz, the *lower*
    tone -- the opposite of what an earlier revision of this module had),
    not just "the right mode decodes", so a future regression back to the
    wrong convention would be caught even if it somehow didn't change
    which VIS codes still happened to round-trip through this module's
    own symmetric encoder/decoder pair."""

    def test_bit_one_is_the_lower_tone(self):
        self.assertEqual(sstv._vis_bit_freq("1"), 1100.0)
        self.assertEqual(sstv._vis_bit_freq("0"), 1300.0)

    def test_robot36_vis_bits_match_known_value(self):
        # VIS 8 = 0b0001000 (LSB first: 0,0,0,1,0,0,0), even parity -> 1
        # ones among the 7 data bits is odd, so parity bit is 1.
        bits = sstv._vis_bits(8)
        self.assertEqual(bits, "0001000" + "1")


if __name__ == "__main__":
    unittest.main()
