"""tools/run-suite-split.sh's suite cache: a green full run in a clean
worktree is recorded by its tree, and --if-needed then answers at once for
that tree - or for one that differs only in a store module.yaml's version
line, which is what a store release commit changes. Run for real against
scratch git repositories whose tests count how often they ran.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Counts its runs in a file outside the repository, so counting never
# dirties the tree it runs in.
COUNTED = """import os, unittest
class Counted(unittest.TestCase):
    def test_counted(self):
        with open(os.environ["RUNS_FILE"], "a") as f:
            f.write("x")
"""
BROKEN = """import unittest
class Broken(unittest.TestCase):
    def test_always(self):
        self.fail("fails every time")
"""
FLAKY = """import os, unittest
MARK = os.environ["RUNS_FILE"] + ".flaky"
class Flaky(unittest.TestCase):
    def test_once(self):
        first = not os.path.exists(MARK)
        open(MARK, "w").close()
        self.assertFalse(first, "first run fails")
"""
YAML = "id: shack-x\nname: X\nversion: {v}\nsummary: s\n"


class SuiteCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        (self.repo / "tools").mkdir(parents=True)
        shutil.copy2(REPO / "tools" / "run-suite-split.sh", self.repo / "tools")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_counted.py").write_text(COUNTED)
        (self.repo / "store" / "x").mkdir(parents=True)
        (self.repo / "store" / "x" / "module.yaml").write_text(YAML.format(v="0.1.0"))
        (self.repo / "ohscore").mkdir()
        (self.repo / ".gitignore").write_text("__pycache__/\nohscore/ohsdigi.abi3.so\n")
        self.git("init", "-q")
        self.commit("first")
        self.runs = self.tmp / "runs"
        self.cache = self.tmp / "cache"

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                              cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def split(self, *args, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("RERUN_RED", "SUITE_CACHE_PID")}
        e.update(LOG_DIR=str(self.tmp / "logs"), SUITE_CACHE_DIR=str(self.cache), RUNS_FILE=str(self.runs),
                 SUITE_TMP_ROOT=str(self.tmp / "scratch"), **env)
        return subprocess.run(["sh", str(self.repo / "tools" / "run-suite-split.sh"), *args], cwd=self.repo,
                              env=e, capture_output=True, text=True, timeout=120)

    def ran(self):
        return len(self.runs.read_text()) if self.runs.exists() else 0

    def test_a_green_clean_run_is_recorded_and_if_needed_then_skips_it(self):
        res = self.split()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("suite cache: recorded", res.stdout)
        self.assertEqual(len(list(self.cache.iterdir())), 1)
        res = self.split("--if-needed")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertRegex(res.stdout, r"^tree [0-9a-f]{40} already green at \d{4}-\d\d-\d\dT")
        self.assertEqual(self.ran(), 1, "the second call ran nothing")

    def test_if_needed_runs_a_tree_that_never_passed(self):
        res = self.split("--if-needed")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(self.ran(), 1)
        self.assertIn("all green", res.stdout)

    def test_only_the_store_version_line_is_ignored(self):
        self.assertEqual(self.split().returncode, 0)
        # A store release commit: the version line and nothing else.
        (self.repo / "store" / "x" / "module.yaml").write_text(YAML.format(v="0.1.1"))
        self.commit("Store X 0.1.1")
        res = self.split("--if-needed")
        self.assertIn("already green", res.stdout)
        self.assertEqual(self.ran(), 1)
        # Any other change to the same file is a new tree.
        (self.repo / "store" / "x" / "module.yaml").write_text(YAML.format(v="0.1.1").replace("name: X", "name: Y"))
        self.commit("renamed")
        res = self.split("--if-needed")
        self.assertNotIn("already green", res.stdout)
        self.assertEqual(self.ran(), 2)

    def test_a_code_change_is_a_new_tree(self):
        self.assertEqual(self.split().returncode, 0)
        (self.repo / "ohscore" / "x.py").write_text("X = 1\n")
        self.commit("code")
        self.assertNotIn("already green", self.split("--if-needed").stdout)
        self.assertEqual(self.ran(), 2)

    def test_a_dirty_worktree_never_counts(self):
        (self.repo / "ohscore" / "x.py").write_text("X = 1\n")      # untracked, but the suite could import it
        res = self.split()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("uncommitted changes", res.stdout)
        self.assertFalse(self.cache.exists())
        self.split("--if-needed")
        self.assertEqual(self.ran(), 2)

    def test_a_red_run_is_not_recorded(self):
        (self.repo / "tests" / "test_broken.py").write_text(BROKEN)
        self.commit("broken")
        self.assertEqual(self.split().returncode, 1)
        self.assertFalse(self.cache.exists())

    def test_a_run_naming_modules_is_not_recorded(self):
        self.assertEqual(self.split("test_counted").returncode, 0)
        self.assertFalse(self.cache.exists())

    def test_a_different_ohsdigi_is_a_different_run(self):
        self.assertEqual(self.split().returncode, 0)
        (self.repo / "ohscore" / "ohsdigi.abi3.so").write_bytes(b"not the same module")   # ignored by git
        self.assertNotIn("already green", self.split("--if-needed").stdout)
        self.assertEqual(self.ran(), 2)
        self.assertEqual(len(list(self.cache.iterdir())), 2)

    def test_green_after_a_rerun_is_recorded(self):
        (self.repo / "tests" / "test_flaky.py").write_text(FLAKY)
        self.commit("flaky")
        res = self.split(RERUN_RED="1")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("suite cache: recorded", res.stdout)
        self.assertIn("already green", self.split("--if-needed").stdout)

    def test_a_tree_changed_during_the_run_is_not_recorded(self):
        (self.repo / "tests" / "test_writer.py").write_text(
            "import pathlib, unittest\nclass W(unittest.TestCase):\n    def test_w(self):\n"
            "        pathlib.Path(__file__).parent.parent.joinpath('store/x/module.yaml').write_text('changed')\n")
        self.commit("writer")
        res = self.split()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("changed during the run", res.stdout)
        self.assertFalse(self.cache.exists())

    def test_if_needed_with_modules_is_a_usage_error(self):
        res = self.split("--if-needed", "test_counted")
        self.assertEqual(res.returncode, 2)
        self.assertIn("name no modules", res.stderr)


if __name__ == "__main__":
    unittest.main()
