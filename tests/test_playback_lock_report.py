"""tools/playback_lock_report.py: beacon lock through the real headless
engine, run for real (a subprocess, as tests/test_update.py's own
tools/update-feed.py tests do) against a short simulator recording with a
known, constant LNB error - the same shape tests/test_ohsnb_analyse.py's
BeaconOffsetAndDrift uses to check ohsnb.analyse's own (direct) beacon
section, so the two can be compared."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohscore import sigmf

REPO_ROOT = Path(__file__).resolve().parent.parent


def _wait_saved(radio, timeout=15.0):
    deadline = time.monotonic() + timeout
    while radio.rec_closing and time.monotonic() < deadline:
        radio.heartbeat()
        time.sleep(0.02)


class PlaybackLockReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, **over):
        r = make_radio(self.dir, **over)
        r.start()
        try:
            path = r.start_recording()
            run_sim(r, 30.0)
            self.assertEqual(r.stop_recording(), path)
            _wait_saved(r)
        finally:
            r.stop()
        return path

    def test_a_steady_beacon_reads_mostly_locked_at_the_known_offset(self):
        path = self._record(simRxErrorHz=12_000.0, simDriftHz=0.0, simSignals=False)
        out = self.dir / "out-playback-lock"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        res = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "playback_lock_report.py"),
                              str(path), "--out", str(out)],
                             cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(res.returncode, 0, f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        report = json.loads((out / "report.json").read_text())
        self.assertIsNotNone(report["locked_pct"])
        self.assertGreater(report["locked_pct"], 50.0, report)
        self.assertAlmostEqual(report["final_rx_corr"], 12_000.0, delta=50.0)
        self.assertTrue(any(t["to"] == "locked" for t in report["transitions"]))
        self.assertEqual(report["dropped"], 0)
        text = (out / "report.txt").read_text()
        self.assertIn("Locked", text)
        self.assertIn("Final rxCorr", text)

    def test_a_file_that_cannot_be_played_is_refused_with_a_sentence(self):
        # Recorded at a frequency OpenHamShack NB never tunes anywhere near:
        # start_playback must refuse it, and this tool must say why rather
        # than crash or write a half-made report.
        base = self.dir / "not-qo100"
        n = 4800
        rng = np.random.default_rng(1)
        data = (rng.standard_normal(2 * n) * 0.01).astype("<f4")
        (self.dir / "not-qo100.sigmf-data").write_bytes(data.tobytes())
        meta = {
            "global": {"core:datatype": "cf32_le", "core:sample_rate": 48_000.0,
                      "core:version": sigmf.SIGMF_VERSION, "core:num_channels": 1,
                      "core:extensions": [dict(sigmf.EXT)], "core:description": "nowhere near QO-100"},
            "captures": [{"core:sample_start": 0, "core:frequency": 7_100_000.0,
                         "core:datetime": sigmf.iso_utc(time.time())}],
            "annotations": [],
        }
        (self.dir / "not-qo100.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
        out = self.dir / "out-refused"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        res = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "playback_lock_report.py"),
                              str(base), "--out", str(out)],
                             cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Could not play", res.stderr)
        self.assertFalse((out / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
