"""tools/suite-affected.sh: the test modules near a branch's changes, run
for real in a scratch repository with a small package and tests that say
when they ran.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RAN = """import os, unittest
class T(unittest.TestCase):
    def test_ran(self):
        open(os.environ["RAN_DIR"] + "/" + __name__, "w").close()
"""


class SuiteAffected(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        r = self.repo = self.tmp / "repo"
        (r / "tools").mkdir(parents=True)
        for f in ("suite-affected.sh", "suite_affected.py", "run-suite-split.sh"):
            shutil.copy2(REPO / "tools" / f, r / "tools")
        (r / "tools" / "thing.sh").write_text("#!/bin/sh\n")
        for pkg in ("ohsradio", "ohscore/server"):
            (r / pkg).mkdir(parents=True)
            (r / pkg / "__init__.py").write_text("")
        (r / "ohsradio" / "ais.py").write_text("A = 1\n")
        (r / "ohsradio" / "dmr.py").write_text("D = 1\n")
        (r / "ohscore" / "server" / "app.py").write_text("S = 1\n")
        t = r / "tests"
        t.mkdir()
        tests = {
            "test_ham_ais": "",                                          # by name
            "test_ham_aisle": "",                                        # a longer word: not by name
            "test_map_view": "from ohsradio import ais\n",               # imports it
            "test_mentions": "# ohsradio.ais is not imported here\n",   # a comment is not an import
            "test_server_routes": "",                                    # by package folder
            "test_tool": "SCRIPT = 'tools/thing.sh'\n",                  # names a script
            "test_dmr": "import ohsradio.dmr\n",
        }
        for name, head in tests.items():
            (t / f"{name}.py").write_text(head + RAN)
        self.git("init", "-q", "-b", "main")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                              cwd=self.repo, check=True, capture_output=True, text=True).stdout

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def affected(self, *args):
        e = {k: v for k, v in os.environ.items() if k not in ("RERUN_RED", "SUITE_CACHE_PID")}
        ran = self.tmp / "ran"
        ran.mkdir(exist_ok=True)
        e.update(RAN_DIR=str(ran), LOG_DIR=str(self.tmp / "logs"), SUITE_CACHE_DIR=str(self.tmp / "cache"),
                 SUITE_TMP_ROOT=str(self.tmp / "scratch"))
        res = subprocess.run(["sh", str(self.repo / "tools" / "suite-affected.sh"), *args], cwd=self.repo,
                             env=e, capture_output=True, text=True, timeout=120)
        return res, sorted(p.name for p in ran.iterdir())

    def listed(self, *args):
        res, _ = self.affected("--list", *args, "main")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return [ln for ln in res.stdout.splitlines() if ln.startswith("test_")]

    def test_a_module_picks_its_namesakes_and_importers(self):
        (self.repo / "ohsradio" / "ais.py").write_text("A = 2\n")
        self.commit("ais")
        self.assertEqual(self.listed(), ["test_ham_ais", "test_map_view"])

    def test_a_package_folder_picks_its_tests(self):
        (self.repo / "ohscore" / "server" / "app.py").write_text("S = 2\n")
        self.commit("server")
        self.assertEqual(self.listed(), ["test_server_routes"])

    def test_a_script_picks_the_tests_that_name_it(self):
        (self.repo / "tools" / "thing.sh").write_text("#!/bin/sh\necho\n")
        self.commit("tool")
        self.assertEqual(self.listed(), ["test_tool"])

    def test_uncommitted_and_untracked_changes_count(self):
        (self.repo / "ohsradio" / "dmr.py").write_text("D = 2\n")          # uncommitted
        (self.repo / "tests" / "test_new.py").write_text(RAN)              # untracked
        self.assertEqual(self.listed(), ["test_dmr", "test_new"])

    def test_a_change_nothing_maps_to_is_said(self):
        (self.repo / "ohsradio" / "lonely.py").write_text("L = 1\n")
        self.commit("lonely")
        res, _ = self.affected("--list", "main")
        self.assertIn("no test found near ohsradio/lonely.py", res.stdout)
        self.assertIn("0 test modules", res.stdout)

    def test_it_runs_only_what_it_chose(self):
        (self.repo / "ohsradio" / "dmr.py").write_text("D = 2\n")
        self.commit("dmr")
        res, ran = self.affected("main")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(ran, ["test_dmr"])
        self.assertIn("all green", res.stdout)

    def test_a_bad_base_is_refused(self):
        res, _ = self.affected("no-such-branch")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not a commit", res.stderr)


if __name__ == "__main__":
    unittest.main()
