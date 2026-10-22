import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""HSmodem station to station, the content layer and the modem together
(ohscore/modes/hsmodem.py Encoder, Decoder, transmission_items): what the
"hsmodem" mode sends is HSmodem's own protocol, and what it sends comes
back intact at every speed. The engines and the band plan are
test_hsmodem_link.py; HSmodem's own code against ours is rust/ohsdigi
(tests/hsmodem_speeds.rs, harness/hsmodem/compare.py speeds)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohscore.modes import hsmodem as hs

CARD = Path(__file__).resolve().parents[1] / "ohsnb" / "devices" / "mmb-testcard.jpg"
# 800 random bytes: a ZIP cannot shrink them, so five frames.
BLOB = np.random.default_rng(8).integers(0, 256, 800, dtype=np.uint8).tobytes()


def receive(audio: np.ndarray, speed: int, folder: Path, noise: float = 0.01, seed: int = 1) -> list[dict]:
    """The decoder fed `audio` as the engine feeds it: 12 kHz blocks, with
    a little receiver noise before, during and after."""
    ev: list[dict] = []
    dec = hs.Decoder(ev.append, speed=speed, folder=folder)
    rng = np.random.default_rng(seed)
    a = np.concatenate([np.zeros(6000, np.float32), audio, np.zeros(9000, np.float32)])
    a = (a + noise * rng.standard_normal(len(a))).astype(np.float32)
    for i in range(0, len(a), 900):
        dec.feed(a[i:i + 900], i / 12000.0)
    return ev


class Protocol(unittest.TestCase):
    def test_speed_table_is_ohsdigis(self):
        if not hs.AVAILABLE:
            self.skipTest(hs.WHY_NOT)
        theirs = {s["bitrate"]: (s["mode"], s["scheme"], s["baud"]) for s in hs.OHSDIGI.hs_speeds()}
        self.assertEqual(theirs, hs.SPEEDS)
        for s in hs.OHSDIGI.hs_speeds():
            self.assertEqual(hs.idle_repetitions(s["bitrate"]), s["idle_repetitions"])

    def test_a_file_goes_out_as_hsmodem_sends_one(self):
        # hsmodem.cpp: the first frame, then idle_repetitions() repeats of it
        # (13 at 4410 bit/s: six seconds), the station frame twice, middle
        # frames once, the last one six times.
        items = hs.file_payloads("a.bin", BLOB)
        self.assertEqual([s for _t, s, _p in items], [0, 1, 1, 1, 2])
        out = hs.transmission_items(items, 4410, "g4xyz", "IO91")
        kinds = [(t, s, r) for t, s, _p, r in out]
        self.assertEqual(kinds[:14], [(hs.T_BINARY, 0, False)] + [(hs.T_BINARY, 0, True)] * 13)
        self.assertEqual(kinds[14:16], [(hs.T_USER, 1, True)] * 2)
        self.assertEqual(kinds[16:19], [(hs.T_BINARY, 1, False)] * 3)
        self.assertEqual(kinds[19:], [(hs.T_BINARY, 2, False)] + [(hs.T_BINARY, 2, True)] * 5)
        self.assertEqual(out[14][2][:5], b"G4XYZ")
        self.assertEqual(out[14][2][20:24], b"IO91")
        # Without a call no station frame (the engine refuses to send then).
        self.assertFalse(any(t == hs.T_USER for t, *_ in hs.transmission_items(items, 4410)))

    def test_counters_follow_packs_rules(self):
        if not hs.AVAILABLE:
            self.skipTest(hs.WHY_NOT)
        items = hs.file_payloads("a.bin", BLOB)
        frames = hs.transmission_frames(items, 7200, "G4XYZ")
        # Decoded straight back by ohsdigi's own deframer, through its modem.
        x = np.frombuffer(hs.OHSDIGI.hs_baseband(frames, 5, 300, 9), np.complex64)
        rx = hs.OHSDIGI.HsReceiver(12000.0, afc=False)
        got = rx.feed(np.concatenate([np.zeros(600, np.complex64), x]).tobytes())
        files = [(f["status"], f["counter"]) for f in got if f["type"] == hs.T_BINARY]
        # Repeats keep their frame's counter; the file's blocks are 0..4.
        self.assertEqual(sorted(set(files)), [(0, 0), (1, 1), (1, 2), (1, 3), (2, 4)])

    def test_plan_says_how_long(self):
        if not hs.AVAILABLE:
            self.skipTest(hs.WHY_NOT)
        p = hs.plan(text="Hello", speed=4410)
        self.assertEqual((p["name"], p["ftype"]), ("message.txt", hs.T_ASCII))
        a = hs.Encoder().render(text="Hello", speed=4410, callsign="G4XYZ")
        self.assertAlmostEqual(len(a) / 12000.0, p["seconds"], delta=0.1)
        img = CARD.read_bytes()
        p = hs.plan(name="card.jpg", data=img, speed=1200)
        self.assertEqual((p["ftype"], p["bytes"]), (hs.T_IMAGE, len(img)))     # a picture is not zipped
        self.assertGreater(p["seconds"], hs.plan(name="card.jpg", data=img, speed=7200)["seconds"] * 4)
        with self.assertRaises(ValueError):
            hs.plan(text="   ")


@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "hsmodem"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_message_at_every_speed(self):
        text = "CQ QO-100 de G4XYZ: HSmodem test at every speed. 73"
        for bps in hs.SPEEDS:
            a = hs.Encoder().render(text=text, speed=bps, callsign="G4XYZ", locator="IO91wm")
            ev = receive(a, bps, self.folder / str(bps))
            got = [e for e in ev if e["kind"] == "bulletin"]
            self.assertEqual([e["text"] for e in got], [text], f"{bps} bit/s")
            self.assertEqual(got[0]["mode"], "hsmodem")
            st = [e for e in ev if e["kind"] == "station"]
            self.assertTrue(st and st[0]["call"] == "G4XYZ" and st[0]["loc"] == "IO91wm", f"{bps}: {st[:1]}")

    def test_a_picture_arrives_byte_for_byte_and_is_saved(self):
        img = CARD.read_bytes()
        a = hs.Encoder().render(name="card.jpg", data=img, speed=4410, callsign="G4XYZ")
        ev = receive(a, 4410, self.folder)
        got = [e for e in ev if e["kind"] == "image"]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["data"], img)
        self.assertEqual(Path(got[0]["path"]).read_bytes(), img)
        self.assertEqual(Path(got[0]["path"]).parent, self.folder)
        prog = [e["have"] for e in ev if e["kind"] == "file_progress"]
        self.assertEqual(prog[-1], -(-(len(img) + hs.HEADER) // hs.PAYLOAD))

    def test_a_second_file_of_the_same_name_does_not_overwrite_the_first(self):
        for i, body in enumerate((b"first file\n", b"second file\n", b"first file\n")):
            a = hs.Encoder().render(name="notes.txt", data=body, speed=7200, callsign="G4XYZ")
            receive(a, 7200, self.folder, seed=i)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["notes-2.txt", "notes.txt"])
        self.assertEqual((self.folder / "notes-2.txt").read_bytes(), b"second file\n")

    def test_the_wrong_speed_hears_nothing(self):
        # HSmodem does not detect a sender's speed: both ends must agree.
        a = hs.Encoder().render(text="hello", speed=4410, callsign="G4XYZ")
        ev = receive(a, 4800, self.folder)
        self.assertFalse([e for e in ev if e["kind"] in ("bulletin", "station")])
