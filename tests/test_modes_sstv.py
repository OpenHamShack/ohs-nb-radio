import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np

from ohscore.modes import sstv

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


def _decode_image(img: np.ndarray, mode: str, noise_std: float = 0.0, seed: int = 1):
    audio = sstv.Encoder().render(image=img, mode=mode)
    if noise_std:
        rng = np.random.default_rng(seed)
        audio = audio + rng.normal(0, noise_std, len(audio)).astype(np.float32)
    outdir = tempfile.mkdtemp()
    events = []
    dec = sstv.Decoder(events.append, out_dir=outdir)
    block = 1200
    for i in range(0, len(audio), block):
        dec.feed(audio[i:i + block], t=i / FS)
    return events


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


class Robot36LoopbackTests(unittest.TestCase):
    def test_solid_colour_recovers_approximately(self):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 200, 50, 220
        events = _decode_image(img, "robot36")
        self.assertEqual([e["state"] for e in events if e["state"] in ("start", "done")], ["start", "done"])
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        self.assertEqual(decoded.shape, (240, 320, 3))
        # Not pixel-exact: Robot36's chroma is subsampled 2:1 vertically and
        # this demodulator necessarily blurs across adjacent pixels (SSTV's
        # pixel rate -- 3.3 samples/pixel here -- is faster than any filter
        # long enough to reject noise can cleanly resolve; see _FreqDemod's
        # docstring). The colour must still clearly be the right colour.
        mean_err = np.abs(decoded.astype(int) - np.array([200, 50, 220])).mean()
        self.assertLess(mean_err, 20)

    def test_gradient_correlates_with_source(self):
        img = _gradient_image(240, 320)
        events = _decode_image(img, "robot36")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        corr_r = np.corrcoef(img[:, :, 0].astype(float).flatten(),
                              decoded[:, :, 0].astype(float).flatten())[0, 1]
        corr_g = np.corrcoef(img[:, :, 1].astype(float).flatten(),
                              decoded[:, :, 1].astype(float).flatten())[0, 1]
        self.assertGreater(corr_r, 0.8)
        self.assertGreater(corr_g, 0.9)

    def test_modest_noise_still_recovers(self):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 180, 90, 60
        events = _decode_image(img, "robot36", noise_std=0.03)
        done = [e for e in events if e["state"] == "done"]
        self.assertTrue(done)
        decoded = _read_png(done[0]["path"])
        mean_err = np.abs(decoded.astype(int) - np.array([180, 90, 60])).mean()
        self.assertLess(mean_err, 30)

    def test_line_events_carry_decodable_base64_rows(self):
        img = np.full((240, 320, 3), 100, dtype=np.uint8)
        events = _decode_image(img, "robot36")
        lines = [e for e in events if e["state"] == "line"]
        self.assertEqual(len(lines), 240)
        row = np.frombuffer(base64.b64decode(lines[0]["row"]), dtype=np.uint8)
        self.assertEqual(len(row), 320 * 3)
        self.assertEqual(lines[0]["of"], 240)


class MartinM1LoopbackTests(unittest.TestCase):
    def test_solid_colour_recovers_closely(self):
        img = np.zeros((256, 320, 3), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 10, 200, 90
        events = _decode_image(img, "martinm1")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        self.assertEqual(decoded.shape, (256, 320, 3))
        mean_err = np.abs(decoded.astype(int) - np.array([10, 200, 90])).mean()
        self.assertLess(mean_err, 10)

    def test_gradient_correlates_strongly(self):
        # Martin M1's scans are slower (5.5 samples/pixel vs Robot36's 3.3)
        # and RGB-direct (no chroma subsampling to reconstruct), and comes
        # out visibly cleaner for it -- this is the mode whose numbers this
        # module's own tests can hold to the higher bar.
        img = _gradient_image(256, 320)
        events = _decode_image(img, "martinm1")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        for ch in (0, 1):  # channel 2 is a flat 128 in _gradient_image -- no variance to correlate
            corr = np.corrcoef(img[:, :, ch].astype(float).flatten(),
                                decoded[:, :, ch].astype(float).flatten())[0, 1]
            self.assertGreater(corr, 0.97, msg=f"channel {ch}")

    def test_modest_noise_still_recovers(self):
        img = _gradient_image(256, 320)
        events = _decode_image(img, "martinm1", noise_std=0.05)
        done = [e for e in events if e["state"] == "done"]
        self.assertTrue(done)
        decoded = _read_png(done[0]["path"])
        mean_err = np.abs(decoded.astype(int) - img.astype(int)).mean()
        self.assertLess(mean_err, 20)


class ScottieS1LoopbackTests(unittest.TestCase):
    """Scottie S1's first line has an extra "starting" sync pulse and its
    regular sync sits between Blue and Red rather than at the line break
    (JL Barber's Dayton paper, "SCOTTIE MODES"); these tests exercise line
    0 and later lines both, not just steady-state."""

    def test_solid_colour_recovers_closely(self):
        img = np.zeros((256, 320, 3), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 10, 200, 90
        events = _decode_image(img, "scottie_s1")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        self.assertEqual(decoded.shape, (256, 320, 3))
        mean_err = np.abs(decoded.astype(int) - np.array([10, 200, 90])).mean()
        self.assertLess(mean_err, 10)

    def test_gradient_correlates_strongly(self):
        img = _gradient_image(256, 320)
        events = _decode_image(img, "scottie_s1")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        for ch in (0, 1):
            corr = np.corrcoef(img[:, :, ch].astype(float).flatten(),
                                decoded[:, :, ch].astype(float).flatten())[0, 1]
            self.assertGreater(corr, 0.95, msg=f"channel {ch}")

    def test_first_line_is_not_corrupted_by_its_extra_sync_pulse(self):
        # Line 0 alone is 9 ms longer than every other line (the "starting"
        # sync); if that extra pulse weren't accounted for it would shift
        # every *following* sample by 9 ms, visible as line 1 onward being
        # wrong even though line 0 itself might look fine. (The very first
        # pixel or two of *any* scan segment can read low from an ordinary
        # demod filter transient at a sharp sync-to-scan edge, the same
        # artifact every other mode's "solid colour" tests tolerate by
        # checking a mean rather than a single sample -- this test does
        # the same, past the first few pixels rather than at pixel 0.)
        img = np.full((256, 320, 3), 77, dtype=np.uint8)
        img[0, :, :] = 200  # line 0 is visibly different from the rest
        events = _decode_image(img, "scottie_s1")
        lines = [e for e in events if e["state"] == "line"]
        self.assertEqual(len(lines), 256)
        row0 = np.frombuffer(base64.b64decode(lines[0]["row"]), dtype=np.uint8).reshape(-1, 3)
        row1 = np.frombuffer(base64.b64decode(lines[1]["row"]), dtype=np.uint8).reshape(-1, 3)
        self.assertLess(abs(float(row0[10:].mean()) - 200), 10)
        self.assertLess(abs(float(row1[10:].mean()) - 77), 10)

    def test_modest_noise_still_recovers(self):
        img = _gradient_image(256, 320)
        events = _decode_image(img, "scottie_s1", noise_std=0.03)
        done = [e for e in events if e["state"] == "done"]
        self.assertTrue(done)
        decoded = _read_png(done[0]["path"])
        mean_err = np.abs(decoded.astype(int) - img.astype(int)).mean()
        self.assertLess(mean_err, 20)


class Pd120LoopbackTests(unittest.TestCase):
    def test_solid_colour_recovers_closely(self):
        img = np.zeros((496, 640, 3), dtype=np.uint8)
        img[:, :, 0], img[:, :, 1], img[:, :, 2] = 50, 150, 250
        events = _decode_image(img, "pd120")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        self.assertEqual(decoded.shape, (496, 640, 3))
        mean_err = np.abs(decoded.astype(int) - np.array([50, 150, 250])).mean()
        self.assertLess(mean_err, 10)

    def test_gradient_correlates_strongly(self):
        img = _gradient_image(496, 640)
        events = _decode_image(img, "pd120")
        done = next(e for e in events if e["state"] == "done")
        decoded = _read_png(done["path"])
        for ch in (0, 1):
            corr = np.corrcoef(img[:, :, ch].astype(float).flatten(),
                                decoded[:, :, ch].astype(float).flatten())[0, 1]
            self.assertGreater(corr, 0.95, msg=f"channel {ch}")

    def test_chroma_is_shared_across_its_line_pair(self):
        # PD120's R-Y/B-Y are each "averaged for two lines" and sent once
        # per pair (JL Barber, "PD Modes") -- two adjacent output rows of a
        # flat-coloured image must come out (near enough) identical, since
        # they share one chroma sample between them. Each row's own Y scan
        # starts fresh though, so (as with Scottie's first line, above) the
        # first pixel or two of each row can show an ordinary demod filter
        # transient independent of the other row's -- and so can the last,
        # running into the next sync -- compared inside those.
        img = np.full((496, 640, 3), 130, dtype=np.uint8)
        events = _decode_image(img, "pd120")
        lines = [e for e in events if e["state"] == "line"]
        self.assertEqual(len(lines), 496)
        row0 = np.frombuffer(base64.b64decode(lines[0]["row"]), dtype=np.uint8).reshape(-1, 3)
        row1 = np.frombuffer(base64.b64decode(lines[1]["row"]), dtype=np.uint8).reshape(-1, 3)
        np.testing.assert_allclose(row0[10:-10].astype(int), row1[10:-10].astype(int), atol=8)

    def test_modest_noise_still_recovers(self):
        img = _gradient_image(496, 640)
        events = _decode_image(img, "pd120", noise_std=0.03)
        done = [e for e in events if e["state"] == "done"]
        self.assertTrue(done)
        decoded = _read_png(done[0]["path"])
        mean_err = np.abs(decoded.astype(int) - img.astype(int)).mean()
        self.assertLess(mean_err, 20)


# --- alignment and noise, every mode ------------------------------------------

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


def _decode_audio(audio):
    events = []
    dec = sstv.Decoder(events.append, out_dir=tempfile.mkdtemp())
    for i in range(0, len(audio), 1200):
        dec.feed(audio[i:i + 1200], t=i / FS)
    done = [e for e in events if e["state"] == "done"]
    return events, (_read_png(done[0]["path"]) if done else None)


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


class AlignmentAndNoiseTests(unittest.TestCase):
    """The reported faults, per mode: pictures came out shifted sideways
    (25-80 px) with the sync pulse as a green band down one side, and no
    header at all was found at sigma 0.05. Noise here is sigma 0.05 on a
    full-scale tone, about 23 dB in 3 kHz, *throughout* -- before the header
    as well, as off the air -- and the transmission starts at an arbitrary
    sample, not on a convenient boundary."""

    LIMITS = {"robot36": 12, "martinm1": 6, "scottie_s1": 6, "pd120": 10}   # mean |error| per channel, 0-255

    def _run(self, mode, sigma=0.05, seed=4, lead_s=0.4321):
        spec = sstv.MODES[mode]
        img = _bars(spec["height"], spec["width"])
        tx = sstv.Encoder().render(image=img, mode=mode)
        audio = np.concatenate([np.zeros(int(lead_s * FS), np.float32), tx, np.zeros(int(FS), np.float32)])
        audio = audio + np.random.default_rng(seed).normal(0, sigma, len(audio)).astype(np.float32)
        events, dec = _decode_audio(audio)
        return img, events, dec

    def test_every_mode_decodes_aligned_in_noise(self):
        for mode in sstv.MODES:
            with self.subTest(mode=mode):
                img, events, dec = self._run(mode)
                starts = [e for e in events if e["state"] == "start"]
                self.assertEqual([e["fmt"] for e in starts], [mode])
                self.assertIsNotNone(dec)
                self.assertEqual(dec.shape, img.shape)
                err = np.abs(dec.astype(int) - img.astype(int)).mean()
                self.assertLess(err, self.LIMITS[mode])
                h = img.shape[0]
                # Top, middle and bottom of the picture: a decoder that only
                # gets the first line right, or slants, fails one of them.
                for rows in (slice(h // 20, h // 6), slice(h // 3, 2 * h // 3), slice(5 * h // 6, h - h // 20)):
                    truth, found = _edge_columns(dec, rows)
                    for t, f in zip(truth, found):
                        self.assertLessEqual(abs(t - f), 2, f"{mode}: edge at {t} found at {f}, rows {rows}")
                # Each bar the right colour: catches a channel swap or a
                # chroma mix-up that leaves the edges where they belong.
                w = img.shape[1]
                for k in range(8):
                    x0, x1 = k * w // 8 + w // 32, (k + 1) * w // 8 - w // 32
                    got = dec[h // 4:3 * h // 4, x0:x1].reshape(-1, 3).mean(axis=0)
                    self.assertLess(np.abs(got - BARS[k]).max(), 40, f"{mode} bar {k}: {got}")

    def test_header_found_in_heavier_noise(self):
        # sigma 0.2 is about 11 dB in 3 kHz: a picture worth keeping is
        # still there, so the header must be found.
        for mode in ("robot36", "martinm1"):
            with self.subTest(mode=mode):
                _, events, dec = self._run(mode, sigma=0.2, seed=8)
                self.assertEqual([e["fmt"] for e in events if e["state"] == "start"], [mode])
                self.assertIsNotNone(dec)

    def test_line_timing_follows_a_slow_sound_card(self):
        # The sending sound card's clock 300 ppm slow: over Martin M1's 114 s
        # the picture would drift 34 ms -- 75 px -- by the bottom without
        # following the sync pulses.
        spec = sstv.MODES["martinm1"]
        img = _bars(spec["height"], spec["width"])
        tx = sstv.Encoder().render(image=img, mode="martinm1").astype(np.float64)
        stretch = 1.0003
        slow = np.interp(np.arange(int(len(tx) * stretch)) / stretch, np.arange(len(tx)), tx).astype(np.float32)
        audio = np.concatenate([np.zeros(5000, np.float32), slow, np.zeros(int(FS), np.float32)])
        audio += np.random.default_rng(2).normal(0, 0.05, len(audio)).astype(np.float32)
        _, dec = _decode_audio(audio)
        self.assertIsNotNone(dec)
        h = img.shape[0]
        truth, found = _edge_columns(dec, slice(5 * h // 6, h - h // 20))
        for t, f in zip(truth, found):
            self.assertLessEqual(abs(t - f), 2, f"edge at {t} found at {f}")


def _shift(x, hz):
    """`x` moved up `hz` in frequency: the dial that far off the station."""
    X = np.fft.fft(x.astype(np.float64))
    n = len(x)
    X[n // 2 + 1:] = 0
    X[1:n // 2] *= 2
    return np.real(np.fft.ifft(X) * np.exp(2j * np.pi * hz * np.arange(n) / FS)).astype(np.float32)


class JoinedPartWayTests(unittest.TestCase):
    """Brian's controller, 10/10/2026: a Scottie picture on the waterfall
    for half a minute, tuned in after its VIS header, and not one event -
    only a header started a picture. Now line syncs alone start one
    (marked partial), in the right mode, aligned, ending when the syncs
    stop; and nothing that is not SSTV starts one."""

    LIMITS = AlignmentAndNoiseTests.LIMITS

    def _joined(self, mode, at=0.6, offset_hz=0.0, sigma=0.05, seed=5):
        spec = sstv.MODES[mode]
        img = _bars(spec["height"], spec["width"])
        tx = sstv.Encoder().render(image=img, mode=mode)
        cut = int(len(tx) * at)
        audio = np.concatenate([np.zeros(3000, np.float32), tx[cut:], np.zeros(int(3 * FS), np.float32)])
        if offset_hz:
            audio = _shift(audio, offset_hz)
        audio = audio + np.random.default_rng(seed).normal(0, sigma, len(audio)).astype(np.float32)
        events, dec = _decode_audio(audio)
        # Rows the cut left whole: the picture's lines that start after it.
        lay = sstv._layout(spec)
        first = (cut - sstv._ms_f(sstv.VIS_MS + lay["head"])) / sstv._ms_f(lay["line"])
        per = 2 if spec["kind"] == "pd" else 1
        left = (spec["height"] // per - int(np.ceil(first))) * per
        return img, events, dec, left

    def test_every_mode_starts_from_its_line_syncs(self):
        for mode in sstv.MODES:
            with self.subTest(mode=mode):
                img, events, dec, left = self._joined(mode)
                starts = [e for e in events if e["state"] == "start"]
                self.assertEqual([(e["fmt"], e.get("partial")) for e in starts], [(mode, True)])
                self.assertIsNotNone(dec)
                # The lines after the join, less at most the few it takes to
                # be sure of the train, and none of the noise after the end.
                self.assertLessEqual(dec.shape[0], left + 2)
                self.assertGreaterEqual(dec.shape[0], left - 2 * (2 if mode == "pd120" else 1))
                bottom = img[-dec.shape[0]:]
                self.assertLess(np.abs(dec.astype(int) - bottom.astype(int)).mean(), self.LIMITS[mode])
                h = dec.shape[0]
                truth, found = _edge_columns(dec, slice(h // 4, 3 * h // 4))
                for t, f in zip(truth, found):
                    self.assertLessEqual(abs(t - f), 2, f"{mode}: edge at {t} found at {f}")

    def test_a_pd_picture_30_hz_off_the_dial_stays_one_picture(self):
        # The matched 20 ms sync window loses PD's sync 30 Hz out; before
        # the short presence window this broke into a picture every few lines.
        _img, events, dec, left = self._joined("pd120", offset_hz=30.0)
        self.assertEqual(len([e for e in events if e["state"] == "start"]), 1)
        self.assertIsNotNone(dec)
        self.assertGreaterEqual(dec.shape[0], left - 4)

    def test_a_picture_with_its_header_is_not_partial(self):
        spec = sstv.MODES["scottie_s1"]
        tx = sstv.Encoder().render(image=_bars(spec["height"], spec["width"]), mode="scottie_s1")
        events, _dec = _decode_audio(np.concatenate([np.zeros(3000, np.float32), tx]))
        self.assertEqual([e.get("partial") for e in events if e["state"] == "start"], [None])

    def test_neither_noise_nor_a_steady_1200_hz_tone_starts_a_picture(self):
        rng = np.random.default_rng(9)
        t = np.arange(int(20 * FS)) / FS
        for name, audio in (("noise", rng.normal(0, 0.3, len(t))),
                            ("1200 Hz carrier", 0.5 * np.sin(2 * np.pi * 1200 * t) + rng.normal(0, 0.05, len(t)))):
            with self.subTest(name):
                events, _ = _decode_audio(audio.astype(np.float32))
                self.assertEqual([e for e in events if e["state"] == "start"], [])


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


class DecoderRobustnessTests(unittest.TestCase):
    def test_silence_produces_no_image(self):
        events = []
        dec = sstv.Decoder(events.append, out_dir=tempfile.mkdtemp())
        silence = np.zeros(int(3.0 * FS), dtype=np.float32)
        for i in range(0, len(silence), 1200):
            dec.feed(silence[i:i + 1200], t=i / FS)
        self.assertEqual(events, [])

    def test_noise_alone_does_not_crash_or_false_trigger(self):
        rng = np.random.default_rng(3)
        noise = rng.normal(0, 0.3, int(5.0 * FS)).astype(np.float32)
        events = []
        dec = sstv.Decoder(events.append, out_dir=tempfile.mkdtemp())
        for i in range(0, len(noise), 1200):
            dec.feed(noise[i:i + 1200], t=i / FS)
        self.assertEqual([e for e in events if e["state"] == "start"], [])

    def test_reset_returns_to_idle(self):
        dec = sstv.Decoder(lambda e: None, out_dir=tempfile.mkdtemp())
        img = np.full((240, 320, 3), 100, dtype=np.uint8)
        audio = sstv.Encoder().render(image=img, mode="robot36")
        dec.feed(audio[:12000], t=0.0)
        dec.reset()
        self.assertEqual(dec._state, "idle")

    def test_ragged_block_sizes(self):
        img = np.full((240, 320, 3), 150, dtype=np.uint8)
        audio = sstv.Encoder().render(image=img, mode="robot36")
        events = []
        dec = sstv.Decoder(events.append, out_dir=tempfile.mkdtemp())
        sizes = [37, 500, 1, 2000, 193]
        i, s = 0, 0
        while i < len(audio):
            n = sizes[s % len(sizes)]
            s += 1
            dec.feed(audio[i:i + n], t=i / FS)
            i += n
        self.assertTrue(any(e["state"] == "done" for e in events))


if __name__ == "__main__":
    unittest.main()
