"""tools/store-post-install.sh, run for real with its box half on this host
(OHS_BOX_LOCAL=1): fake dock360ctl, journalctl, podman and sudo on PATH say
what the box would, and a fake controller answers the smoke list through
the local-screen token. A failure must notify, print the rollback command
and never roll back; a pass must say so.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fake_controller import TOKEN, FakeRadio, token_file

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "store-post-install.sh"

FAKES = {
    "dock360ctl": """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
[ "$1 $2" = "module list" ] && echo "shack-radio              0.1.22-beta.17 ${FAKE_STATE:-active}     port 20002"
exit 0
""",
    # The unit's journal, its error-level part, or the kernel's, by the arguments.
    "journalctl": """#!/bin/sh
echo "journalctl $*" >> "$FAKE_LOG"
case "$*" in
    *-k*) cat "$FAKE_DIR/kernel" 2>/dev/null ;;
    *"-p err"*) cat "$FAKE_DIR/err" 2>/dev/null ;;
    *) cat "$FAKE_DIR/unit" 2>/dev/null ;;
esac
""",
    "podman": """#!/bin/sh
echo "podman $*" >> "$FAKE_LOG"
echo "selftest table"; echo "${FAKE_SELFTEST_SAYS:-selftest: PASS}"
exit ${FAKE_SELFTEST_RC:-0}
""",
    "sudo": """#!/bin/sh
[ "$1" = -u ] && shift 2
exec "$@"
""",
    "id": "#!/bin/sh\necho 990\n",
    "notify": "#!/bin/sh\necho \"$*\" >> \"$FAKE_DIR/notified\"\n",
}


class PostInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, text in FAKES.items():
            p = self.bin / name
            p.write_text(text)
            p.chmod(0o755)
        self.home = self.tmp / "home"
        (self.home / ".config" / "claude-account").mkdir(parents=True)
        shutil.copy2(self.bin / "notify", self.home / ".config" / "claude-account" / "notify")
        self.fake = FakeRadio(self.tmp, prefix="radio").start()
        self.addCleanup(self.fake.stop)
        self.smoke = self.tmp / "smoke.json"
        self.smoke.write_text(json.dumps({"checks": [{"get": "api/status", "keys": ["app", "rxOwner"]},
                                                     {"get": "api/ais/vessels"}]}))
        self.fake.extra["ais/vessels"] = {"vessels": []}
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.home),
                    "OHS_BOX_LOCAL": "1", "OHS_API_ROOT": self.fake.root, "OHS_TOKEN_FILE": str(token_file(self.tmp)),
                    "FAKE_DIR": str(self.tmp), "FAKE_LOG": str(self.tmp / "log"), "POST_INSTALL_WAIT_S": "0"}

    def run_it(self, *args, **env):
        res = subprocess.run(["bash", str(SCRIPT), "--version", "0.1.22-beta.17", "--since", "2026-10-28 10:00:00",
                              "--smoke", str(self.smoke), *args, "radio"],
                             env={**self.env, **env}, capture_output=True, text=True, timeout=60)
        self.assertNotIn(TOKEN, res.stdout + res.stderr)
        return res

    def notified(self):
        p = self.tmp / "notified"
        return p.read_text() if p.exists() else ""

    def assertFailedWithRollback(self, res):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("rollback-shack-radio-0.1.22-beta.17.sh", res.stdout)
        self.assertIn("Not rolled back", res.stdout)
        self.assertIn("FAILED", self.notified())
        # Never rolled back: nothing but reading was asked of dock360ctl.
        self.assertNotIn("update", (self.tmp / "log").read_text())
        self.assertNotIn("catalogue", (self.tmp / "log").read_text())

    def test_a_clean_install_passes(self):
        res = self.run_it()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for line in ("ok   active", "ok   journal clean", "ok   selftest", "smoke: 2 of 2 passed",
                     "post-install checks passed"):
            self.assertIn(line, res.stdout)
        self.assertEqual(self.notified(), "")
        log = (self.tmp / "log").read_text()
        self.assertIn("--since 2026-10-28 10:00:00", log)
        self.assertIn("podman exec -w /opt/shack-radio dock360-shack-radio python3 -m ohscore.selftest ohsradio", log)

    def test_a_module_that_is_not_active_fails(self):
        self.assertFailedWithRollback(self.run_it(FAKE_STATE="failed"))

    def test_a_segfault_in_the_unit_journal_fails(self):
        (self.tmp / "unit").write_text("Oct 28 conmon: dock360-shack-radio.service: Main process exited, status=139/n/a\n")
        res = self.run_it()
        self.assertIn("status=139", res.stdout)
        self.assertFailedWithRollback(res)

    def test_a_segfault_in_the_kernel_journal_fails(self):
        (self.tmp / "kernel").write_text("kernel: python3[4242]: segfault at 18 ip 00007f in libsdrplay_api.so\n")
        self.assertFailedWithRollback(self.run_it())

    def test_a_traceback_at_error_level_fails(self):
        (self.tmp / "err").write_text("dock360-shack-radio[1]: Traceback (most recent call last):\n")
        self.assertFailedWithRollback(self.run_it())

    def test_ordinary_errors_in_the_journal_do_not(self):
        # A radio unplugged is the operator's business, not a broken release.
        (self.tmp / "err").write_text("ohsradio.radio ERROR Could not open the soapy device: No SDRplay RSP\n")
        self.assertEqual(self.run_it().returncode, 0)

    def test_a_failing_selftest_fails(self):
        res = self.run_it(FAKE_SELFTEST_RC="1", FAKE_SELFTEST_SAYS="selftest: FAIL ft8")
        self.assertIn("selftest: FAIL ft8", res.stdout)
        self.assertFailedWithRollback(res)

    def test_a_smoke_check_that_lacks_a_key_fails(self):
        self.smoke.write_text(json.dumps({"checks": [{"get": "api/status", "keys": ["adsb"]}]}))
        res = self.run_it()
        self.assertIn("FAIL GET api/status has no adsb", res.stdout)
        self.assertFailedWithRollback(res)

    def test_a_smoke_route_that_does_not_answer_fails(self):
        self.smoke.write_text(json.dumps({"checks": [{"get": "api/nothing/here"}]}))
        res = self.run_it()
        self.assertIn("FAIL GET api/nothing/here", res.stdout)
        self.assertFailedWithRollback(res)
        self.assertEqual(self.fake.paths("POST"), [], "smoke checks only ever GET")

    def test_the_committed_smoke_lists_are_well_formed(self):
        for app in ("radio", "qo100nb"):
            checks = json.loads((REPO / "store" / app / "smoke.json").read_text())["checks"]
            self.assertTrue(checks)
            for c in checks:
                self.assertTrue(c["get"].startswith("api/"), c)
                self.assertLessEqual(set(c), {"get", "keys"}, c)

    def test_bad_arguments_are_refused(self):
        for args in (["--since", "yesterday"], ["--version", "1.0; rm -rf /"]):
            res = subprocess.run(["bash", str(SCRIPT), *args, "radio"], env=self.env, capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(res.returncode, 2, args)
        res = subprocess.run(["bash", str(SCRIPT), "icom"], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
