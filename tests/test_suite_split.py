"""tools/run-suite-split.sh, the runner release.sh gates a release on: one
interpreter per module, and with RERUN_RED=1 a second, serial run of the
modules that came out red, which then decides. Run for real against a
scratch tree whose tests fail on purpose.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Fails the first time it runs in a tree and passes after: what a test
# paced in real time does on a loaded host and then alone.
FLAKY = """import os, unittest
MARK = os.path.join(os.path.dirname(__file__), "ran-once")
class Flaky(unittest.TestCase):
    def test_once(self):
        first = not os.path.exists(MARK)
        open(MARK, "w").close()
        self.assertFalse(first, "first run fails")
"""
BROKEN = """import unittest
class Broken(unittest.TestCase):
    def test_always(self):
        self.fail("fails every time")
"""
OK = """import unittest
class Ok(unittest.TestCase):
    def test_ok(self):
        pass
"""


class RerunRed(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "tools").mkdir()
        shutil.copy2(REPO / "tools" / "run-suite-split.sh", self.tmp / "tools")
        (self.tmp / "tests").mkdir()
        (self.tmp / "tests" / "test_ok.py").write_text(OK)
        (self.tmp / "tests" / "test_flaky.py").write_text(FLAKY)

    def run_split(self, **env):
        # Not this run's own RERUN_RED: release.sh sets it for the suite
        # that runs this test.
        e = {k: v for k, v in os.environ.items() if k != "RERUN_RED"}
        e.update(LOG_DIR=str(self.tmp / "logs"), **env)
        return subprocess.run(["sh", str(self.tmp / "tools" / "run-suite-split.sh")], cwd=self.tmp, env=e,
                              capture_output=True, text=True, timeout=120)

    def test_without_it_a_flaky_module_is_red(self):
        res = self.run_split()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("test_flaky", res.stdout)

    def test_a_module_that_passes_alone_the_second_time_is_green(self):
        res = self.run_split(RERUN_RED="1")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("rerunning the red modules", res.stdout)
        self.assertTrue(res.stdout.rstrip().endswith("all green"), res.stdout)
        # Only the red module ran again, in a log folder of its own.
        self.assertEqual(sorted(p.name for p in (self.tmp / "logs" / "rerun").glob("*.log")), ["test_flaky.log"])

    def test_a_module_that_fails_twice_is_still_red(self):
        (self.tmp / "tests" / "test_broken.py").write_text(BROKEN)
        res = self.run_split(RERUN_RED="1")
        self.assertEqual(res.returncode, 1, res.stdout)
        second = res.stdout.split("rerunning the red modules", 1)[1]
        self.assertIn("test_broken", second)
        self.assertNotIn("test_flaky", second)

    def test_scratch_files_go_to_a_disk_folder_of_the_runs_own_and_are_removed(self):
        # Each test records where tempfile put its scratch; the module that
        # fails once makes the run exec a rerun, which must use the same
        # folder and still remove it at the end.
        probe = ("import tempfile, unittest\nclass P(unittest.TestCase):\n    def test_p(self):\n"
                 "        open({out!r}, 'a').write(tempfile.mkdtemp() + '\\n')\n")
        out = self.tmp / "seen"
        (self.tmp / "tests" / "test_ok.py").write_text(probe.format(out=str(out)))
        (self.tmp / "tests" / "test_flaky.py").write_text(
            FLAKY.replace("first = not", "open(%r, 'a').write(__import__('tempfile').mkdtemp() + '\\n')\n"
                          "        first = not" % str(out)))
        root = self.tmp / "disk-tmp"
        res = self.run_split(RERUN_RED="1", SUITE_TMP_ROOT=str(root), TMPDIR="/nonexistent-ram")
        self.assertEqual(res.returncode, 0, res.stdout)
        seen = out.read_text().split()
        self.assertEqual(len(seen), 3)              # ok, flaky, flaky again
        parents = {Path(p).parent for p in seen}
        self.assertEqual(len(parents), 1, seen)    # one folder for the run and its rerun
        self.assertEqual(next(iter(parents)).parent, root)
        self.assertEqual(list(root.iterdir()), [])  # and gone at the end

    def test_each_rerun_takes_only_what_is_still_red(self):
        # Fails twice, then passes: two reruns are needed and enough.
        (self.tmp / "tests" / "test_twice.py").write_text(FLAKY.replace("ran-once", "ran-twice").replace(
            "first = not os.path.exists(MARK)\n        open(MARK, \"w\").close()",
            "n = int(open(MARK).read()) if os.path.exists(MARK) else 0\n"
            "        open(MARK, \"w\").write(str(n + 1))\n        first = n < 2"))
        self.assertEqual(self.run_split(RERUN_RED="1").returncode, 1)
        for f in self.tmp.glob("tests/ran-*"):
            f.unlink()
        shutil.rmtree(self.tmp / "logs")
        res = self.run_split(RERUN_RED="2")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(sorted(p.name for p in (self.tmp / "logs" / "rerun" / "rerun").glob("*.log")),
                         ["test_twice.log"])


if __name__ == "__main__":
    unittest.main()


# Records how many modules run at once: each one adds a file while it runs
# and counts the others it can see.
OVERLAP = """import os, time, unittest
D = os.path.join(os.path.dirname(__file__), "running")
class Overlap(unittest.TestCase):
    def test_overlap(self):
        os.makedirs(D, exist_ok=True)
        me = os.path.join(D, str(os.getpid()))
        open(me, "w").close()
        try:
            peak = 0
            for _ in range(10):
                peak = max(peak, len(os.listdir(D)))
                time.sleep(0.1)
            with open(os.path.join(os.path.dirname(__file__), "peak-%d" % os.getpid()), "w") as f:
                f.write(str(peak))
        finally:
            os.remove(me)
"""


class JobPool(unittest.TestCase):
    """-j N must keep at most N modules running, under dash as under bash:
    a pool that counted with `jobs -p` in a subshell started every module
    at once under dash and ran the host out of memory."""

    def test_j_limits_the_modules_running_at_once(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "tools").mkdir()
        shutil.copy2(REPO / "tools" / "run-suite-split.sh", tmp / "tools")
        (tmp / "tests").mkdir()
        for i in range(6):
            (tmp / "tests" / f"test_overlap{i}.py").write_text(OVERLAP)
        e = {k: v for k, v in os.environ.items() if k != "RERUN_RED"}
        e.update(LOG_DIR=str(tmp / "logs"))
        shell = shutil.which("dash") or "sh"
        res = subprocess.run([shell, str(tmp / "tools" / "run-suite-split.sh"), "-j", "2"], cwd=tmp, env=e,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        peaks = [int(p.read_text()) for p in (tmp / "tests").glob("peak-*")]
        self.assertEqual(len(peaks), 6)
        self.assertLessEqual(max(peaks), 2, peaks)
        self.assertEqual(max(peaks), 2, "the pool should use both slots")
