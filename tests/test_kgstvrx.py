import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""KG-STV in the radio (ohsnb/kgstvrx.py): the engine receives the
simulator's KG-STV station from the wide IQ through its own channel,
wherever the dial is, and keeps the pictures.

The decoder itself is held to real frames in test_kgstv.py; this is the
glue - channel, worker, feed, status keys, saved files."""
import calendar
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohsnb import kgstvrx
from ohsnb.devices import kgsim
from ohscore.dsp import kgstv


def reference_block(x, y):
    """What the receiver should paint at block (x, y) of the simulator's card."""
    blk = kgsim.card()[y * 16:(y + 1) * 16, x * 16:(x + 1) * 16]
    return kgstv.decode_block(kgstv.encode_block(blk, kgsim.SCALE), kgsim.SCALE)


class InTheRadio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.radio = None

    def tearDown(self):
        if self.radio is not None:
            self.radio.stop()
        self.tmp.cleanup()

    def test_a_picture_arrives_while_tuned_elsewhere_and_is_kept(self):
        r = self.radio = make_radio(Path(self.tmp.name), vfo=10_489_700_000.0, mode="usb", mmbDecode=False,
                                    midTextDecode=False)
        f = r.subscribe("kgstv", 1024)
        r.start()
        seen: list = []

        def until():
            seen.extend(f.drain())
            return any(e["kind"] == "done" for e in seen)
        run_sim(r, 110.0, until=until, timeout=400)
        seen.extend(f.drain())
        kinds = [e["kind"] for e in seen]
        self.assertIn("done", kinds, kinds[-5:])
        self.assertIn(kgsim.CALL, [e["call"] for e in seen if e["kind"] == "call"])
        blocks = [e for e in seen if e["kind"] == "block"]
        # Beacon lock takes the first few seconds; everything after is there.
        self.assertGreater(len(blocks), 250)
        for e in blocks[::25]:
            got = np.frombuffer(e["rgb"], np.uint8).reshape(16, 16, 3)
            self.assertTrue(np.array_equal(got, reference_block(e["x"], e["y"])), (e["x"], e["y"]))
        done = [e for e in seen if e["kind"] == "done"][0]
        self.assertEqual((done["call"], done["why"], done["mode"]), (kgsim.CALL, "end", "MSK/NORM"))
        self.assertTrue(done["path"].endswith(f"_{kgsim.CALL}.png"), done["path"])
        png = Path(done["path"]).read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual([p for p, _ in kgstvrx.saved_pictures(Path(self.tmp.name) / "kgstv")], [done["path"]])
        st = r.state()
        self.assertEqual(st["kgstvState"], "receiving")
        self.assertEqual(st["kgstvCall"], kgsim.CALL)
        self.assertGreater(st["kgstvFrames"], 250)
        self.assertLess(abs(st["kgstvFreq"]), 30.0)
        self.assertGreater(st["kgstvLast"], time.time() - 60)

    def test_switched_off_it_costs_nothing_and_says_so(self):
        r = self.radio = make_radio(Path(self.tmp.name), kgstvDecode=False, mmbDecode=False, midTextDecode=False)
        f = r.subscribe("kgstv", 64)
        r.start()
        run_sim(r, 3.0)
        self.assertEqual(f.drain(), [])
        self.assertIsNone(r.kgstv)
        self.assertEqual(r.state()["kgstvState"], "off")
        r.set(kgstvDecode=True)
        run_sim(r, 2.0)
        self.assertIsNotNone(r.kgstv)
        self.assertIn(r.state()["kgstvState"], ("listening", "receiving"))
        r.set(kgstvDecode=False)
        run_sim(r, 1.0)
        self.assertIsNone(r.kgstv)
        self.assertEqual(r.state()["kgstvState"], "off")


class Clock(unittest.TestCase):
    """A picture belongs to when it was on the air: a played recording's
    own time, a fast simulator's, else the wall clock."""

    def rx(self, dev):
        from types import SimpleNamespace
        from ohscore.dsp.bank import Geometry
        radio = SimpleNamespace(geo=Geometry(1_200_000.0), dev=dev, rx_samples=2_400_000,
                                data_dir=Path(tempfile.gettempdir()))
        return kgstvrx.KgStvRx(radio)

    def test_a_recording_keeps_its_own_clock(self):
        from types import SimpleNamespace
        t = calendar.timegm((2026, 10, 7, 15, 28, 57))
        self.assertEqual(self.rx(SimpleNamespace(own_clock=True, utc_end=t))._utc(), t)

    def test_a_fast_simulator_keeps_its_own(self):
        from types import SimpleNamespace
        self.assertEqual(self.rx(SimpleNamespace(realtime=False, t_epoch=1000.0))._utc(), 1002.0)

    def test_a_radio_is_the_wall_clock(self):
        from types import SimpleNamespace
        self.assertAlmostEqual(self.rx(SimpleNamespace())._utc(), time.time(), delta=1.0)


class Files(unittest.TestCase):
    def test_a_callsign_becomes_a_safe_file_name(self):
        t = calendar.timegm((2026, 10, 8, 0, 0, 0))
        self.assertEqual(kgstvrx.file_name("DL4CQ", t), "20261008_000000_DL4CQ.png")
        self.assertEqual(kgstvrx.file_name("VU2SAA    Sam     NK03CA", t), "20261008_000000_VU2SAA-Sam-NK03CA.png")
        self.assertEqual(kgstvrx.file_name("../..\\x:*?", t), "20261008_000000_x.png")
        self.assertEqual(kgstvrx.file_name("", t), "20261008_000000_no-call.png")

    def test_saved_pictures_are_listed_newest_first(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(kgstvrx.saved_pictures(Path(d) / "missing"), [])
            for i, name in enumerate(["a.png", "b.png", "notes.txt"]):
                p = Path(d) / name
                p.write_bytes(b"x")
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual([Path(p).name for p, _ in kgstvrx.saved_pictures(d)], ["b.png", "a.png"])


if __name__ == "__main__":
    unittest.main()
