"""tools/capture-and-test.sh end to end against a fake controller on a local
socket (tests/fake_controller.py), never the box: OHS_BOX_LOCAL=1 runs the
box half (tools/box_api.py) here with no ssh or sudo, and a fake cargo
stands in for ohs-libs' real-file test. What must hold: nothing without
--yes-receiver, a held receiver refused unless sessions may be dropped,
the receiver put back exactly - after success, after an error and after
Ctrl-C - the recording copied and checked and gone from the box, and the
token never printed.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from fake_controller import TOKEN, FakeRadio, token_file

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "capture-and-test.sh"

FAKE_CARGO = """#!/bin/sh
# Says what it was asked and what folder it was given, as the real test would read it.
echo "cargo $*"
echo "dirs: DMR=${SHACK_DMR_DIR:-} AIS=${SHACK_AIS_DIR:-} ADSB=${SHACK_ADSB_DIR:-} DAB=${SHACK_DAB_DIR:-}"
ls "${SHACK_DMR_DIR:-${SHACK_AIS_DIR:-${SHACK_ADSB_DIR:-$SHACK_DAB_DIR}}}"
echo "test result: ${FAKE_CARGO_SAYS:-ok}. 1 passed"
exit ${FAKE_CARGO_RC:-0}
"""


class CaptureAndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recdir = self.tmp / "recordings"
        self.recdir.mkdir()
        self.fake = FakeRadio(self.recdir).start()
        self.addCleanup(self.fake.stop)
        self.home = self.tmp / "home"
        (self.tmp / "libs" / "rust").mkdir(parents=True)
        cargo = self.tmp / "cargo"
        cargo.write_text(FAKE_CARGO)
        cargo.chmod(0o755)
        self.env = {**os.environ, "OHS_BOX_LOCAL": "1", "OHS_API_ROOT": self.fake.root,
                    "OHS_TOKEN_FILE": str(token_file(self.tmp)), "CAPTURE_RECORDINGS_DIR": str(self.recdir),
                    "HOME": str(self.home), "OHS_LIBS": str(self.tmp / "libs"), "CARGO": str(cargo),
                    "OHS_CAPTURE_SETTLE_S": "0"}
        self.original = dict(self.fake.st)

    def run_it(self, *args, **env):
        res = subprocess.run(["bash", str(SCRIPT), *args], env={**self.env, **env}, capture_output=True,
                             text=True, timeout=120)
        self.assertNotIn(TOKEN, res.stdout + res.stderr, "the token was printed")
        return res

    def assertRestored(self):
        self.assertEqual(self.fake.st, self.original)
        self.assertEqual(self.fake.owner, {})

    def summary(self, out: str) -> list[str]:
        lines = out.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith(("dmr ", "ais ", "adsb ", "dab ")))
        return lines[start:]

    def test_nothing_happens_without_yes_receiver(self):
        res = self.run_it("dmr", "430900000", "1")
        self.assertEqual(res.returncode, 2)
        self.assertIn("belongs to Brian", res.stderr)
        self.assertIn("--yes-receiver", res.stderr)
        self.assertEqual(self.fake.calls, [])

    def test_dmr_is_recorded_copied_checked_tested_and_put_back(self):
        res = self.run_it("--yes-receiver", "--antenna", "A", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        sets = [b["changes"] for m, p, b in self.fake.calls if p == "set"]
        self.assertIn({"soapyAntenna": "Antenna A"}, sets)
        self.assertIn({"vfo": 430900000, "mode": "fm"}, sets)
        self.assertRestored()
        # Copied with its channel, and gone from the box.
        folders = list((self.home / "build" / "real-dmr").iterdir())
        self.assertEqual(len(folders), 1)
        rid = folders[0].name
        got = sorted(p.name for p in folders[0].iterdir())
        for want in (f"{rid}.sigmf-data", f"{rid}.sigmf-meta", f"{rid}.channel", "test.log", "capture.log"):
            self.assertIn(want, got)
        self.assertEqual((folders[0] / f"{rid}.channel").read_text().strip(), "430900000")
        self.assertEqual(list(self.recdir.iterdir()), [])
        # The test ran on this capture's folder alone.
        log = (folders[0] / "test.log").read_text()
        self.assertIn("--test dmr_real recordings_of_local_repeaters -- --ignored", log)
        self.assertIn(f"DMR={folders[0]}", log)
        summary = self.summary(res.stdout)
        self.assertLessEqual(len(summary), 10, summary)
        self.assertIn("test dmr_real recordings_of_local_repeaters: PASS", res.stdout)
        self.assertIn("matches the box; deleted from the box", res.stdout)

    def test_keep_on_box_keeps_it(self):
        res = self.run_it("--yes-receiver", "--keep-on-box", "--no-test", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(len(list(self.recdir.glob("*.sigmf-data"))), 1)
        self.assertIn("test: not run", res.stdout)

    def test_ais_uses_its_session_and_gives_the_receiver_back(self):
        res = self.run_it("--yes-receiver", "ais", "162000000", "1")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("ais/session", self.fake.paths("POST"))
        self.assertIn("ais/session", self.fake.paths("DELETE"))
        self.assertNotIn("set", [p for m, p, b in self.fake.calls if p == "set" and "vfo" in b.get("changes", {})
                                 and b["changes"]["vfo"] == 162000000])
        self.assertRestored()
        meta = next((self.home / "build" / "real-ais").glob("*/*.sigmf-meta")).read_text()
        self.assertIn("162000000", meta)            # the session set the centre
        self.assertIn("--test ais real_air", res.stdout + next((self.home / "build" / "real-ais").glob("*/test.log")).read_text())

    def test_adsb_takes_no_rate(self):
        res = self.run_it("--yes-receiver", "--rate", "2.4M", "adsb", "1090000000", "1")
        self.assertEqual(res.returncode, 2)
        self.assertIn("sets its own rate", res.stderr)
        self.assertEqual(self.fake.calls, [])

    def test_dab_uses_a_dab_session(self):
        res = self.run_it("--yes-receiver", "--no-test", "dab", "222064000", "1")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        posted = [b for m, p, b in self.fake.calls if p == "decoders/sessions"]
        self.assertEqual(posted[0]["decoder"], "dab")
        self.assertIn("decoders/sessions/ds_dab1", self.fake.paths("DELETE"))
        self.assertRestored()

    def test_a_held_receiver_is_refused(self):
        self.fake.owner = {"by": "dab", "session": "ds_x", "text": "Playing DAB from 11D"}
        res = self.run_it("--yes-receiver", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("held by dab", res.stdout)
        self.assertNotIn("set", self.fake.paths("POST"))

    def test_drop_sessions_stops_what_holds_it(self):
        self.fake._hold("ais", 162000000, "ais")
        self.original = {**self.fake.st, **self.fake.prior}     # back where the operator had it
        res = self.run_it("--yes-receiver", "--drop-sessions", "--no-test", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("ais/session", self.fake.paths("DELETE"))
        self.assertEqual(self.fake.owner, {})

    def test_on_the_air_is_refused(self):
        self.fake.on_air = True
        res = self.run_it("--yes-receiver", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 3)
        self.assertIn("on the air", res.stdout)
        self.assertNotIn("set", self.fake.paths("POST"))

    def test_an_error_still_puts_everything_back(self):
        self.fake.fail["recordings/start"] = (507, "low_disk")
        res = self.run_it("--yes-receiver", "--antenna", "C", "--rate", "2048000", "dmr", "430900000", "1")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("low_disk", res.stdout)
        self.assertIn("receiver restored", res.stdout)
        self.assertRestored()
        # The rate came back through a restart, as it went.
        self.assertEqual(self.fake.paths("POST").count("start"), 2)
        self.assertFalse((self.home / "build" / "real-dmr").exists())

    def test_ctrl_c_during_the_recording_puts_everything_back(self):
        p = subprocess.Popen(["bash", str(SCRIPT), "--yes-receiver", "--antenna", "A", "dmr", "430900000", "60"],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        deadline = time.monotonic() + 30
        while "recordings/start" not in self.fake.paths("POST") and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn("recordings/start", self.fake.paths("POST"))
        os.killpg(p.pid, signal.SIGINT)          # what Ctrl-C does: the whole foreground group
        out, err = p.communicate(timeout=60)
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(p.returncode, 130, out + err)
        self.assertRestored()
        self.assertEqual(list(self.recdir.iterdir()), [], "the unfinished recording is deleted")
        self.assertIn("receiver restored", out)

    def test_a_failing_decoder_test_fails_the_run(self):
        res = self.run_it("--yes-receiver", "dmr", "430900000", "1", FAKE_CARGO_RC="101", FAKE_CARGO_SAYS="FAILED")
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAIL (rc 101)", res.stdout)
        self.assertIn("test result: FAILED", res.stdout)
        self.assertRestored()

    def test_bad_arguments_change_nothing(self):
        for args in (["dmr", "4309", "1"], ["dmr", "430900000", "0"], ["dmr", "430900000", "601"],
                     ["fm", "430900000", "1"], ["--antenna", "D", "dmr", "430900000", "1"],
                     ["--rate", "fast", "dmr", "430900000", "1"]):
            res = self.run_it("--yes-receiver", *args)
            self.assertEqual(res.returncode, 2, args)
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
