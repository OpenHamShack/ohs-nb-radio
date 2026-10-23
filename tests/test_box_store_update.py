"""tools/box-store-update.sh's argument and config checks (--check): the
part that can be proved with no network, no box and no ohs-dev. The
update itself (two hosts, sudo, podman, a signing key) is not exercised
here - it is read by eye and run by hand, as the draft it replaces was.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "box-store-update.sh"
SHA = "a" * 64


def run(*args, conf=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path(tempfile.gettempdir()))}
    if conf is not None:
        env["BOX_UPDATE_CONF"] = str(conf)
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=20, env=env)


def write_conf(tmp: Path, **over) -> Path:
    vals = {"BOX_HOST": "box.example", "SIGN_HOST": "signer.example", "DOCK360_SRC": "~/src",
            "DOCK360_VENV": "~/venv/bin/python", "MODULES_KEY": "~/keys/modules.key"}
    vals.update(over)
    # Single-quoted, as the real conf keeps them (its own comment explains
    # why): these three are paths on SIGN_HOST, and an unquoted ~ would
    # expand here, against whoever runs this script's home, before ssh
    # ever sends the string to the host it actually belongs to.
    conf = tmp / "box-update.conf"
    conf.write_text("".join(f"{k}='{v}'\n" for k, v in vals.items()))
    return conf


class ArgChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conf = write_conf(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_arguments_is_a_usage_error(self):
        r = run("--check", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_good_arguments_pass_and_report_nothing_expanded_early(self):
        r = run("--check", "shack-radio", "0.1.23-beta.1", "dev.example:/tmp/x.d360mod", SHA, conf=self.conf)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("module=shack-radio", r.stdout)
        self.assertIn("new=0.1.23-beta.1", r.stdout)
        self.assertIn("from=dev.example:/tmp/x.d360mod", r.stdout)
        # The conf's remote paths are passed through, not locally expanded
        # (DOCK360_SRC etc. belong to SIGN_HOST, not to whoever runs this).
        self.assertIn("src=~/src", r.stdout)

    def test_bad_module_id_is_refused(self):
        r = run("--check", "shack radio", "0.1.23", "dev.example:/tmp/x", SHA, conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad module id", r.stderr)

    def test_bad_version_is_refused(self):
        r = run("--check", "shack-radio", "../etc", "dev.example:/tmp/x", SHA, conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad version", r.stderr)

    def test_source_without_a_host_is_refused(self):
        r = run("--check", "shack-radio", "0.1.23", "/tmp/x.d360mod", SHA, conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("host:path", r.stderr)

    def test_short_sha256_is_refused(self):
        r = run("--check", "shack-radio", "0.1.23", "dev.example:/tmp/x", "deadbeef", conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("sha256", r.stderr)

    def test_uppercase_sha256_is_refused(self):
        r = run("--check", "shack-radio", "0.1.23", "dev.example:/tmp/x", SHA.upper(), conf=self.conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("sha256", r.stderr)


class ConfigChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_config_is_refused(self):
        r = run("--check", "shack-radio", "0.1.23", "dev.example:/tmp/x", SHA, conf=self.tmp / "none.conf")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no config at", r.stderr)

    def test_a_blank_setting_is_refused(self):
        conf = write_conf(self.tmp, SIGN_HOST="")
        r = run("--check", "shack-radio", "0.1.23", "dev.example:/tmp/x", SHA, conf=conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("SIGN_HOST is not set", r.stderr)

    def test_a_missing_setting_is_refused(self):
        conf = self.tmp / "box-update.conf"
        conf.write_text("BOX_HOST=box.example\n")
        r = run("--check", "shack-radio", "0.1.23", "dev.example:/tmp/x", SHA, conf=conf)
        self.assertEqual(r.returncode, 2)
        self.assertIn("SIGN_HOST is not set", r.stderr)


class NoNetwork(unittest.TestCase):
    """--check must never reach for ssh or scp: a PATH with neither on it
    is still enough to pass, which is the easiest way to prove nothing
    network-shaped runs before the config is validated."""

    def test_check_runs_with_no_ssh_or_scp_on_path(self):
        import shutil
        tmp = Path(tempfile.mkdtemp())
        try:
            conf = write_conf(tmp)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            for tool in ("bash", "sh", "grep", "cut", "mktemp", "sha256sum"):
                found = shutil.which(tool)
                if found:
                    (bin_dir / tool).symlink_to(found)
            r = subprocess.run(["bash", str(SCRIPT), "--check", "shack-radio", "0.1.23",
                                "dev.example:/tmp/x.d360mod", SHA],
                                capture_output=True, text=True, timeout=20,
                                env={"PATH": str(bin_dir), "HOME": str(tmp), "BOX_UPDATE_CONF": str(conf)})
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
