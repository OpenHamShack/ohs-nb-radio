"""tools/store-release.sh's argument and config checks (--check): the part
that can be proved with no git fetch, no ssh and no box. The release itself
(the suite, a build on the signing host, an install) is exercised by
running it, as tools/box-store-update.sh's is.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "store-release.sh"


def run(*args, conf=None, **env_over):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path(tempfile.gettempdir()))}
    if conf is not None:
        env["BOX_UPDATE_CONF"] = str(conf)
    env.update(env_over)
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=20, env=env)


class ArgChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conf = self.tmp / "box-update.conf"
        self.conf.write_text("BOX_HOST=box.example\nSIGN_HOST=signer.example\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_good_arguments_pass(self):
        r = run("--check", "radio", "54dcb2c", conf=self.conf)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("app=radio commit=54dcb2c box=box.example sign=signer.example jobs=10", r.stdout)
        self.assertIn("suite=1 install=1", r.stdout)

    def test_flags_are_reported(self):
        r = run("--no-install", "--skip-suite", "--check", "qo100nb", "abcdef1", conf=self.conf, JOBS="4")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("jobs=4 suite=0 install=0", r.stdout)

    def test_missing_arguments_is_a_usage_error(self):
        r = run("--check", "radio", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_unknown_app_is_refused(self):
        r = run("--check", "icom", "54dcb2c", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown app", r.stderr)

    def test_a_commit_must_look_like_one(self):
        # A branch name could move between the suite and the build; only a
        # commit id names one tree for both.
        r = run("--check", "radio", "main", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a commit id", r.stderr)

    def test_missing_config_is_refused(self):
        r = run("--check", "radio", "54dcb2c", conf=self.tmp / "absent.conf")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no config", r.stderr)

    def test_config_without_hosts_is_refused(self):
        self.conf.write_text("BOX_HOST=box.example\n")
        r = run("--check", "radio", "54dcb2c", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("must set BOX_HOST and SIGN_HOST", r.stderr)

    def test_bad_jobs_is_refused(self):
        r = run("--check", "radio", "54dcb2c", conf=self.conf, JOBS="lots")
        self.assertEqual(r.returncode, 2)
        self.assertIn("JOBS", r.stderr)


if __name__ == "__main__":
    unittest.main()
