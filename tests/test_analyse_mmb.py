"""ohsnb.analyse_mmb.mmb_report: the multimedia beacon, decoded across a
whole recording. Two tiers, as HANDOVER's house style asks tests to be
behavioural:

- `StubbedReceiver` exercises this module's own logic (bucketing,
  MER-filtering, content-shaping, the retune/reset trigger) with
  ohscore.modes.hsmodem.BeaconReceiver replaced by a small fake that calls
  the real emit callback mmb_report builds - deterministic, and runs
  without ohsdigi built (this development tree has none: see
  tests/test_ohsnb_analyse.py's own Ft8JT9VsOhsdigi for the same situation).
- `RealDecode` is the end-to-end case, a real HSmodem signal (the
  simulator's own template, ohsnb.devices.mmbeacon, the exact fixture
  test_mmbeacon.py already proves decodes cleanly) embedded in a wideband
  IQ array the way a real capture holds it, read back by mmb_report
  exactly as `python3 -m ohsnb --analyse --mmb` would. Skipped wherever
  ohsdigi is not built."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.modes import hsmodem
from ohsnb import analyse_mmb, bandplan

FS = 1_200_000.0


class _FakeHsReceiver:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1


class _FakeBeaconReceiver:
    """Stands in for ohscore.modes.hsmodem.BeaconReceiver: real __init__
    signature and a real `.rx.reset()` to count, but `feed_iq` just calls
    back with scripted events instead of running ohsdigi - what is under
    test here is mmb_report's own handling of those events, not the
    decoder."""

    instances: list = []

    def __init__(self, rate, emit, folder=None, afc=True):
        self.rate, self.emit, self.folder = rate, emit, folder
        self.rx = _FakeHsReceiver()
        self.calls = 0
        _FakeBeaconReceiver.instances.append(self)

    def feed_iq(self, iq, t=None):
        i = self.calls
        self.calls += 1
        # Two more frames decoded every call, one lost on the 5th; MER
        # alternates sync True/False so the bucket's MER average must
        # count only the synced ones.
        ok = (i + 1) * 2
        lost = 1 if i >= 5 else 0
        self.emit({"kind": "stats", "ok": ok, "failed": lost, "sync": i % 2 == 0,
                  "mer": 10.0 + i, "freq": 0.0, "last": 0.0, "resets": 0})
        self.emit({"kind": "frame", "type": 3, "counter": i})       # must be ignored
        if i == 10:
            self.emit({"mode": "mmb", "kind": "bulletin", "name": "amsat_1.blt",
                      "text": "hello", "data": b"hello", "path": "/tmp/x/amsat_1.blt"})
        if i == 11:
            self.emit({"mode": "mmb", "kind": "file_progress", "name": "amsat_1.blt",  # must be ignored
                      "have": 1, "blocks": 2})


class StubbedReceiver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
        self.n = int(30.0 * FS)      # 30 s -> 30 one-second chunks -> 30 feed_iq calls
        self.view = np.zeros((self.n, 2), np.float32)
        self.caps = [{"core:sample_start": 0, "core:frequency": self.dc0}]
        self.info = {"lnb_lo_hz": None, "nominal_dc_flat": None}

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, beacon_hist, rx_corr_est=0.0):
        with mock.patch.object(hsmodem, "AVAILABLE", True), \
             mock.patch.object(hsmodem, "BeaconReceiver", _FakeBeaconReceiver):
            return analyse_mmb.mmb_report(self.view, 1.0, self.n, FS, self.caps, self.info, rx_corr_est,
                                          beacon_hist, self.dir, bucket_s=600.0)

    def test_frames_and_mer_are_bucketed_and_mer_only_counts_synced_reports(self):
        r = self._run(beacon_hist=[])
        self.assertTrue(r["available"])
        self.assertEqual(len(r["buckets"]), 1)        # 30 s, one 600 s bucket
        b = r["buckets"][0]
        # 30 calls, ok = 2*(i+1): cumulative final is 60, all counted (i=0 start from 2-0).
        self.assertEqual(b["ok"], 60)
        self.assertEqual(r["frames_ok_total"], 60)
        # lost becomes 1 from i=5 on and stays 1 (cumulative): one single +1 step.
        self.assertEqual(b["lost"], 1)
        self.assertEqual(r["frames_lost_total"], 1)
        # MER only from the 15 synced calls (i even, 0..28): mean of 10+i for even i in 0..29.
        synced = [10.0 + i for i in range(30) if i % 2 == 0]
        self.assertAlmostEqual(b["mer_db_avg"], sum(synced) / len(synced), places=1)
        self.assertAlmostEqual(b["mer_db_min"], min(synced), places=1)
        self.assertAlmostEqual(b["mer_db_max"], max(synced), places=1)

    def test_content_keeps_only_delivered_kinds_and_drops_raw_bytes(self):
        r = self._run(beacon_hist=[])
        self.assertEqual(len(r["content"]), 1)        # the bulletin; "frame" and "file_progress" dropped
        c = r["content"][0]
        self.assertEqual(c["kind"], "bulletin")
        self.assertEqual(c["name"], "amsat_1.blt")
        self.assertEqual(c["text"], "hello")
        self.assertEqual(c["size_bytes"], len(b"hello"))
        self.assertNotIn("data", c)

    def test_a_beacon_lock_jump_bigger_than_retune_hz_restarts_the_afc_once(self):
        # Flat at 0 Hz for the first half, then a single 100 Hz step - past
        # beaconrx.RETUNE_HZ (40 Hz) - for the rest: one reset, not one per
        # chunk once the new value is adopted as the reference.
        hist = ([{"t": 0.0, "state": "locked", "rxCorr": 0.0}] +
                [{"t": 20.0, "state": "locked", "rxCorr": 100.0}])
        _FakeBeaconReceiver.instances = []
        with mock.patch.object(hsmodem, "AVAILABLE", True), \
             mock.patch.object(hsmodem, "BeaconReceiver", _FakeBeaconReceiver):
            analyse_mmb.mmb_report(self.view, 1.0, self.n, FS, self.caps, self.info, 0.0, hist, self.dir,
                                   bucket_s=600.0)
        self.assertEqual(len(_FakeBeaconReceiver.instances), 1)
        self.assertEqual(_FakeBeaconReceiver.instances[0].rx.resets, 1)

    def test_a_steady_correction_never_restarts_the_afc(self):
        hist = [{"t": float(i), "state": "locked", "rxCorr": 500.0} for i in range(30)]
        _FakeBeaconReceiver.instances = []
        with mock.patch.object(hsmodem, "AVAILABLE", True), \
             mock.patch.object(hsmodem, "BeaconReceiver", _FakeBeaconReceiver):
            analyse_mmb.mmb_report(self.view, 1.0, self.n, FS, self.caps, self.info, 500.0, hist, self.dir,
                                   bucket_s=600.0)
        self.assertEqual(_FakeBeaconReceiver.instances[0].rx.resets, 0)

    def test_without_ohsdigi_it_says_so_rather_than_fail(self):
        with mock.patch.object(hsmodem, "AVAILABLE", False), mock.patch.object(hsmodem, "WHY_NOT", "no ohsdigi here"):
            r = analyse_mmb.mmb_report(self.view, 1.0, self.n, FS, self.caps, self.info, 0.0, [], self.dir)
        self.assertFalse(r["available"])
        self.assertEqual(r["why"], "no ohsdigi here")
        self.assertEqual(r["buckets"], [])
        self.assertEqual(r["content"], [])


@unittest.skipUnless(hsmodem.AVAILABLE, hsmodem.WHY_NOT or "ohsdigi")
class RealDecode(unittest.TestCase):
    """A real HSmodem signal, embedded in wideband IQ, decoded by
    mmb_report exactly as a recording would be - the simulator's own
    fixture (ohsnb.devices.mmbeacon.template), already proven in
    test_mmbeacon.py to decode cleanly over two or three loops."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bulletins_a_picture_and_spots_come_out_and_are_bucketed(self):
        from ohsnb.devices import mmbeacon
        fs = 240_000.0
        dc0 = bandplan.BEACONS["mm"]["dl"] - 2_000.0
        geo = Geometry(fs)
        x = mmbeacon.template(np.random.default_rng(9))
        # Twice round the loop, entered part way through - test_mmbeacon.py's
        # own "no seam" case - so every stream is seen complete at least once.
        y = np.concatenate([x[len(x) // 3:], x, x])
        d = geo.decimation_for(12_000.0)
        src = Source(geo, d, freq=2_000.0, gain=1.0)
        synth = Synthesis(geo)
        m = len(y) // src.hop
        wide = synth.render(m, [(src, y[:m * src.hop])])
        view = np.stack([wide.real, wide.imag], axis=1).astype(np.float32)
        caps = [{"core:sample_start": 0, "core:frequency": dc0}]
        info = {"lnb_lo_hz": None, "nominal_dc_flat": None}
        r = analyse_mmb.mmb_report(view, 1.0, len(wide), fs, caps, info, 0.0, [], self.dir, bucket_s=60.0)
        self.assertTrue(r["available"])
        self.assertGreater(r["frames_ok_total"], 0)
        self.assertEqual(r["frames_lost_total"], 0)
        names = {c["name"] for c in r["content"] if c["kind"] == "bulletin"}
        self.assertTrue(set(mmbeacon.BULLETINS) <= names)
        for c in r["content"]:
            if c["kind"] == "bulletin":
                self.assertEqual(c["text"], mmbeacon.BULLETINS[c["name"]])
        images = [c for c in r["content"] if c["kind"] == "image"]
        self.assertTrue(images)
        self.assertTrue(Path(images[0]["path"]).exists())
        self.assertEqual(Path(images[0]["path"]).read_bytes(), mmbeacon.TESTCARD.read_bytes())
        self.assertTrue(any(c["kind"] == "dx" for c in r["content"]))
        self.assertGreaterEqual(sum(b["ok"] for b in r["buckets"]), r["frames_ok_total"])


if __name__ == "__main__":
    unittest.main()
