import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""QO-100's multimedia beacon in OpenHamShack NB: the simulator sends a real
HSmodem signal, and what it carries comes out the other end."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohscore.modes import hsmodem as hs
from ohsnb.devices import mmbeacon


class Collect(list):
    def __call__(self, e):
        self.append(e)

    def kinds(self, k):
        return [e for e in self if e["kind"] == k]


@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class SimulatedBeacon(unittest.TestCase):
    def test_its_signal_carries_bulletins_a_picture_and_spots(self):
        x = mmbeacon.template(np.random.default_rng(1))
        c = Collect()
        rx = hs.BeaconReceiver(12000.0, c)
        # Twice round the loop, entered part way through as a receiver would.
        y = np.concatenate([x[len(x) // 3:], x, x])
        for i in range(0, len(y), 900):
            rx.feed_iq(y[i:i + 900])
        names = sorted({e["name"] for e in c.kinds("bulletin")})
        self.assertEqual(names, sorted(mmbeacon.BULLETINS))
        for e in c.kinds("bulletin"):
            self.assertEqual(e["text"], mmbeacon.BULLETINS[e["name"]])
        self.assertEqual({e["data"] for e in c.kinds("image")}, {mmbeacon.TESTCARD.read_bytes()})
        spots = {(e["dxcall"], e["qrg_khz"]) for e in c.kinds("dx")}
        self.assertGreaterEqual(len(spots), 10)
        self.assertTrue(any(10_489_500 <= q <= 10_490_000 for _, q in spots))
        self.assertTrue(c.kinds("nbspec") and c.kinds("wbspec") and c.kinds("cw"))
        self.assertEqual(c.kinds("stats")[-1]["failed"], 0)

    def test_the_loop_has_no_seam(self):
        # One period of a periodic signal: played end to end it decodes
        # every frame across the join.
        x = mmbeacon.template(np.random.default_rng(2))
        c = Collect()
        rx = hs.BeaconReceiver(12000.0, c)
        y = np.concatenate([x, x, x])
        for i in range(0, len(y), 900):
            rx.feed_iq(y[i:i + 900])
        ok = c.kinds("stats")[-1]
        self.assertEqual(ok["failed"], 0)
        self.assertGreater(ok["ok"], 2 * len(mmbeacon.schedule(np.random.default_rng(0))) - 3)

    def test_the_rest_of_the_band_is_unchanged_by_it(self):
        # The beacon draws its stand-in from the simulator's generator
        # either way, so a seeded band is the band it was.
        r1, r2 = np.random.default_rng(7), np.random.default_rng(7)
        mmbeacon.template(r1)
        from ohscore.devices import simsignals as sg
        sg.apsk_beacon(r2, 10.0)
        self.assertEqual(r1.integers(0, 1 << 30), r2.integers(0, 1 << 30))


@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class InTheRadio(unittest.TestCase):
    """The engine decodes the beacon from the wide IQ through its own
    channel, wherever the dial is."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.radio = None

    def tearDown(self):
        if self.radio is not None:
            self.radio.stop()
        self.tmp.cleanup()

    def _run(self, seconds, **over):
        r = self.radio = make_radio(Path(self.tmp.name), **over)
        f = r.subscribe("mmb", 4096)
        r.start()

        def got_all():
            kinds = {e["kind"] for e in seen}
            return {"bulletin", "image", "dx"} <= kinds

        seen: list = []

        def until():
            seen.extend(f.drain())
            return got_all()
        run_sim(r, seconds, until=until, timeout=240)
        seen.extend(f.drain())
        return seen

    def test_bulletins_picture_and_spots_arrive_while_tuned_elsewhere(self):
        # Tuned to the lower SSB segment in LSB: nowhere near the beacon.
        ev = self._run(100.0, vfo=10_489_700_000.0, mode="lsb")
        kinds = {e["kind"] for e in ev}
        self.assertTrue({"bulletin", "image", "dx"} <= kinds, kinds)
        names = {e["name"] for e in ev if e["kind"] == "bulletin"}
        self.assertTrue(names <= set(mmbeacon.BULLETINS) and names, names)
        img = [e for e in ev if e["kind"] == "image"][0]
        self.assertEqual(img["data"], mmbeacon.TESTCARD.read_bytes())
        # Saved in the data folder, under the name it was sent with.
        self.assertEqual((Path(self.tmp.name) / "mmbeacon" / "testcard.jpg").read_bytes(), img["data"])
        st = self.radio.state()
        self.assertEqual(st["mmbState"], "receiving")
        self.assertGreater(st["mmbFrames"], 10)
        self.assertGreater(st["mmbMer"], 12.0)
        self.assertGreater(st["mmbLast"], 0)

    def test_switched_off_it_costs_nothing_and_says_so(self):
        r = self.radio = make_radio(Path(self.tmp.name), mmbDecode=False)
        f = r.subscribe("mmb", 64)
        r.start()
        run_sim(r, 5.0)
        self.assertEqual(f.drain(), [])
        self.assertIsNone(r.mmb)
        self.assertEqual(r.state()["mmbState"], "off")
        # And on again without a restart.
        r.set(mmbDecode=True)
        run_sim(r, 2.0)
        self.assertIsNotNone(r.mmb)
        self.assertIn(r.state()["mmbState"], ("searching", "receiving"))


if __name__ == "__main__":
    unittest.main()
