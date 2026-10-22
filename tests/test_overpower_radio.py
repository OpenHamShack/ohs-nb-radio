import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The over-power and LEILA watch in the running radio (ohsnb/overpower.py):
on the simulated band, a station over the beacon and a LEILA siren come
out on the "overpower" feed and in Radio.overpower_view() where they are,
and with leilaCapture on the siren is saved as a SigMF recording that
reads back - the receive chain only; nothing here keys.

The judging itself is tests/test_overpower.py's (on the real sirens)."""
import tempfile
import unittest
from pathlib import Path

from helpers import make_radio, run_sim, wait_rx_lock
from ohscore import sigmf

HOT = 10_489_812_345.0       # a carrier 7 dB over the beacon (the simulator's is -40 dBFS)
SIREN = 10_489_700_000.0     # LEILA's lower tone; the upper is 205 Hz above


class Watch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        r = cls.radio = make_radio(Path(cls.tmp.name), simSignals=False, leilaCapture=True)
        cls.feed = r.subscribe("overpower", 256)
        r.start()
        r.dev.add_station("carrier", HOT, -33.0)
        assert wait_rx_lock(r)
        # The simulator's siren sounds for 5 s of every 15 from when it is
        # added: added once the lock is in, so the watch can judge it.
        r.dev.add_station("leila", SIREN, -38.0)
        cls.items = run_sim(r, 16.0, [cls.feed])["overpower"]
        cls.view = r.overpower_view()
        cls.state = r.state()

    @classmethod
    def tearDownClass(cls):
        cls.radio.stop()
        cls.tmp.cleanup()

    def test_the_station_over_the_beacon_is_listed_where_it_is(self):
        ops = [e for e in self.view["events"] if e["kind"] == "overpower"]
        self.assertEqual(len(ops), 1, self.view)
        self.assertAlmostEqual(ops[0]["freq"], HOT, delta=100.0)
        self.assertAlmostEqual(ops[0]["excessDb"], 7.0, delta=3.0)
        self.assertGreaterEqual(self.state["opActive"], 1)

    def test_the_siren_is_listed_with_its_two_tones(self):
        sirens = [e for e in self.view["events"] if e["kind"] == "leila"]
        self.assertEqual(len(sirens), 1, self.view)
        self.assertAlmostEqual(sirens[0]["lo"], SIREN, delta=30.0)
        self.assertAlmostEqual(sirens[0]["hi"], SIREN + 205.0, delta=30.0)
        self.assertEqual(self.state["opLeila"], 1)

    def test_the_feed_carried_the_same_list(self):
        self.assertTrue(self.items)
        last = self.items[-1]["events"]
        self.assertEqual({e["kind"] for e in last}, {"overpower", "leila"})

    def test_the_siren_was_saved_as_a_recording_that_reads_back(self):
        name = self.state["opCapture"]
        self.assertTrue(name.endswith(".sigmf-data"), self.state)
        data = self.radio.recordings_dir() / name
        meta = sigmf.read_meta(data.with_name(name.replace(".sigmf-data", ".sigmf-meta")))
        self.assertIn("openhamshack:leila", meta["global"])
        seconds = data.stat().st_size / sigmf.BYTES_PER_SAMPLE / meta["global"]["core:sample_rate"]
        self.assertGreater(seconds, 5.0)
        self.assertLessEqual(seconds, 20.5)

    def test_the_watch_is_cheap(self):
        self.assertLess(self.state["opCpu"], 30.0)
        self.assertEqual(self.state["opDropped"], 0)


class Off(unittest.TestCase):
    def test_off_it_watches_nothing_and_capture_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = make_radio(Path(tmp), simSignals=False, opWatch=False)
            r.start()
            try:
                run_sim(r, 1.0)
                self.assertEqual(r.state()["opState"], "off")
                self.assertEqual(r.overpower_view()["events"], [])
                with self.assertRaises(ValueError):
                    r.leila_capture_now()
            finally:
                r.stop()


if __name__ == "__main__":
    unittest.main()
