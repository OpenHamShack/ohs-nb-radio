import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""HSmodem's content layer (ohscore/modes/hsmodem.py): files and streams
written and read back through the same frame fields the modem carries, and
- where ohsdigi is built - through the modem itself."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from ohscore.modes import hsmodem as hs


def frames_of(items, counter_from=0):
    """(type, status, payload) -> the dicts ohsdigi's receiver hands over,
    with Pack()'s counter rules."""
    out, c = [], counter_from
    for t, s, p in items:
        if t != hs.T_EXT:
            c = 0 if s == hs.S_FIRST else (c + 1) & 0x3FF
        out.append({"type": t, "status": s, "counter": c, "payload": p})
    return out


class Collect:
    def __init__(self):
        self.ev = []

    def __call__(self, e):
        self.ev.append(e)

    def kinds(self, k):
        return [e for e in self.ev if e["kind"] == k]


class Packing(unittest.TestCase):
    def test_six_bit_values_round_trip_lsb_first(self):
        v = np.random.default_rng(1).integers(0, 64, 275)
        b = hs.pack6(v)
        self.assertEqual(len(b), (275 * 6 + 7) // 8)
        np.testing.assert_array_equal(hs.unpack6(b, 275), v)
        # LSB first: value 1 then 0 sets bit 0 of byte 0 only.
        self.assertEqual(hs.pack6([1, 0])[0], 1)
        self.assertEqual(hs.pack6([0, 1])[0], 1 << 6)

    def test_crc_is_hsmodems(self):
        self.assertEqual(hs.crc16(b"123456789"), 0x6F91)

    def test_file_header_as_filesend_writes_it(self):
        items = hs.file_payloads("a.jpg", bytes(range(256)) * 3)
        t, s, p = items[0]
        self.assertEqual((t, s), (hs.T_IMAGE, hs.S_FIRST))
        self.assertEqual(p[:5], b"a.jpg")
        self.assertEqual((p[50] << 8) | p[51], hs.crc16(bytes(range(256)) * 3))
        self.assertEqual((p[52] << 16) | (p[53] << 8) | p[54], 768)
        self.assertEqual(p[55:], (bytes(range(256)) * 3)[:164])
        self.assertEqual([s for _, s, _ in items], [0, 1, 1, 2])
        # Small: one frame, status single.
        self.assertEqual([(t, s) for t, s, _ in hs.file_payloads("n.blt", b"hi")], [(hs.T_ASCII, hs.S_SINGLE)])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "mmb"

    def tearDown(self):
        self.tmp.cleanup()

    def test_bulletin_unzipped_and_saved(self):
        text = "BULLETIN\n" + "line of news\n" * 60
        c = Collect()
        content = hs.Content(c, self.folder)
        for f in frames_of(hs.file_payloads("amsat_1.blt", text.encode())):
            content.frame(f)
        b = c.kinds("bulletin")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["text"], text)
        self.assertEqual((self.folder / "amsat_1.blt").read_text(), text)

    def test_image_bytes_exact_and_not_zipped(self):
        jpg = bytes(np.random.default_rng(2).integers(0, 256, 3000, dtype=np.uint8))
        c = Collect()
        content = hs.Content(c, self.folder)
        for f in frames_of(hs.file_payloads("pic.jpg", jpg)):
            content.frame(f)
        im = c.kinds("image")
        self.assertEqual(len(im), 1)
        self.assertEqual(im[0]["data"], jpg)
        self.assertEqual((self.folder / "pic.jpg").read_bytes(), jpg)

    def test_missing_blocks_filled_by_the_next_repeat(self):
        data = bytes(np.random.default_rng(3).integers(0, 256, 2000, dtype=np.uint8))
        fr = frames_of(hs.file_payloads("x.jpg", data))
        c = Collect()
        content = hs.Content(c, None)
        for i, f in enumerate(fr):
            if i not in (3, 5):
                content.frame(f)
        self.assertEqual(c.kinds("image"), [])
        for i, f in enumerate(fr):
            if i in (0, 3, 5):          # the repeat: its first frame, then what was missing
                content.frame(f)
        self.assertEqual([e["data"] for e in c.kinds("image")], [data])
        # A third time round it is a repeat of a file already kept.
        content.frame(fr[0])
        self.assertEqual(len(c.kinds("repeat")), 1)

    def test_corrupted_file_is_refused_not_delivered(self):
        data = b"A" * 900
        fr = frames_of(hs.file_payloads("y.jpg", data))
        bad = dict(fr[2])
        bad["payload"] = bytes([bad["payload"][0] ^ 1]) + bad["payload"][1:]
        c = Collect()
        content = hs.Content(c, None)
        for f in fr[:2] + [bad] + fr[3:]:
            content.frame(f)
        self.assertEqual(c.kinds("image"), [])
        self.assertEqual(len(c.kinds("file_bad")), 1)

    def test_blocks_without_their_first_frame_are_dropped(self):
        c = Collect()
        content = hs.Content(c, None)
        for f in frames_of(hs.file_payloads("z.jpg", b"B" * 1500))[1:]:
            content.frame(f)
        self.assertEqual([e for e in c.ev if e["kind"] in ("image", "file_start")], [])

    def test_hostile_file_name_stays_in_the_folder(self):
        c = Collect()
        content = hs.Content(c, self.folder)
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../../etc/evil.txt", "x")
        # The frames built by hand around a ZIP whose member has a path.
        body = z.getvalue()
        fid = hs.crc16(body)
        blob = b"../../evil.blt".ljust(50, b"\0") + bytes([fid >> 8, fid & 255, 0, len(body) >> 8, len(body) & 255]) + body
        items = []
        n = (len(blob) + 218) // 219
        for i in range(n):
            s = hs.S_SINGLE if n == 1 else hs.S_FIRST if i == 0 else hs.S_LAST if i == n - 1 else hs.S_NEXT
            items.append((hs.T_ASCII, s, blob[i * 219:(i + 1) * 219].ljust(219, b"\0")))
        for f in frames_of(items):
            content.frame(f)
        saved = [Path(e["path"]) for e in c.ev if e.get("path")]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].parent, self.folder)
        self.assertTrue(saved[0].exists())


class Streams(unittest.TestCase):
    def test_dx_spot_fields_and_repeat_dropped(self):
        p = hs.dx_payload("IZ3HLJ", 10489500.0, "CO8LY", "TNX QSO 73", "1346Z", "JN65")
        c = Collect()
        content = hs.Content(c, None)
        for _ in range(3):
            content.frame({"type": hs.T_EXT, "status": 3, "counter": 0, "payload": p})
        d = c.kinds("dx")
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["reporter"], d[0]["qrg_khz"], d[0]["dxcall"], d[0]["comment"], d[0]["utc"], d[0]["loc"]),
                         ("IZ3HLJ", 10489500.0, "CO8LY", "TNX QSO 73", "1346Z", "JN65"))

    def test_dx_line_as_the_beacon_cuts_it(self):
        # ams_extension.cpp's fixed columns: a reporter's "IZ3HLJ:" keeps
        # nothing after column 14; the receiver strips the colon.
        p = bytes([0, 75]) + b"IZ3HLJ:~10489500.0~CO8LY~TNX QSO 73~1346Z~JN65\0"
        d = hs.parse_dx(p.ljust(219, b"\0"))
        self.assertEqual(d["reporter"], "IZ3HLJ")
        self.assertIsNone(hs.parse_dx(bytes([0, 5]) + b"not a spot\0"))

    def test_spectra_and_cw(self):
        c = Collect()
        content = hs.Content(c, None)
        nb = np.arange(275) % 64
        content.frame({"type": 8, "status": 3, "counter": 0, "payload": hs.spectrum_payload(hs.X_NBSPEC, nb)})
        wb = (np.arange(266) * 7) % 64
        content.frame({"type": 8, "status": 3, "counter": 0, "payload": hs.spectrum_payload(hs.X_WBSPEC, wb)})
        content.frame({"type": 8, "status": 3, "counter": 0, "payload": hs.cw_payload("10489525.0 G4XYZ 20 dB CQ\x07")})
        np.testing.assert_array_equal(c.kinds("nbspec")[0]["values"], nb)
        np.testing.assert_array_equal(c.kinds("wbspec")[0]["values"], wb)
        self.assertEqual(c.kinds("cw")[0]["text"], "10489525.0 G4XYZ 20 dB CQ")


@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class ThroughTheModem(unittest.TestCase):
    """The content layer on ohsdigi's own HSmodem frames and signal."""

    def _signal(self, items, snr_db=None, seed=0):
        frames = hs.beacon_frames(items)
        x = np.frombuffer(hs.OHSDIGI.hs_baseband(frames, 5, 300), np.complex64).copy()
        if snr_db is not None:
            rng = np.random.default_rng(seed)
            n0 = np.mean(np.abs(x) ** 2) * 5 / 10 ** (snr_db / 10)
            x = (x + np.sqrt(n0 / 2) * (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x)))).astype(np.complex64)
        return x

    def _run(self, x, folder=None):
        c = Collect()
        rx = hs.BeaconReceiver(12000.0, c, folder)
        for i in range(0, len(x), 900):
            rx.feed_iq(x[i:i + 900])
        return c, rx

    def test_bulletin_image_and_spots_end_to_end(self):
        jpg = bytes(np.random.default_rng(4).integers(0, 256, 1500, dtype=np.uint8))
        items = ([(8, 3, hs.dx_payload("DL1ABC", 10489540.0, "G4XYZ", "FT8", "1200Z"))] * 2
                 + hs.file_payloads("amsat_1.blt", b"Hello from the beacon\n")
                 + hs.file_payloads("p.jpg", jpg)
                 + [(8, 3, hs.dx_payload("F5KLM", 14074.0, "OH8ZZ", "FT8", "1201Z"))] * 2)
        c, rx = self._run(self._signal(items, snr_db=25))
        self.assertEqual([e["text"] for e in c.kinds("bulletin")], ["Hello from the beacon\n"])
        self.assertEqual([e["data"] for e in c.kinds("image")], [jpg])
        self.assertEqual([e["dxcall"] for e in c.kinds("dx")], ["G4XYZ", "OH8ZZ"])
        stats = c.kinds("stats")[-1]
        self.assertGreater(stats["mer"], 15)
        self.assertEqual(stats["failed"], 0)

    def test_too_noisy_fails_cleanly(self):
        items = hs.file_payloads("p.jpg", b"C" * 3000) * 2
        c, rx = self._run(self._signal(items, snr_db=6, seed=9))
        self.assertEqual(c.kinds("image"), [])
        self.assertEqual(c.kinds("frame"), [])
        self.assertTrue(c.kinds("stats"))
        self.assertLess(c.kinds("stats")[-1]["mer"], 10)

    def test_garbage_payloads_never_raise(self):
        c = Collect()
        content = hs.Content(c, None)
        rng = np.random.default_rng(5)
        for _ in range(2000):
            t = int(rng.choice([2, 3, 4, 5, 7, 8]))
            content.frame({"type": t, "status": int(rng.integers(0, 4)), "counter": int(rng.integers(0, 1024)),
                           "payload": bytes(rng.integers(0, 256, 219, dtype=np.uint8))})


if __name__ == "__main__":
    unittest.main()
