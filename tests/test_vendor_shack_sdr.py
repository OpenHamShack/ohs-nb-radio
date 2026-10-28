"""tools/vendor-shack-sdr.sh: a build-wheels-safe.sh folder into
tools/vendor/ and shack-sdr.lock, run for real on a scratch copy of the
tree with small stand-in wheels. The hashes, the header's "Built by"
sentence and its history must come out right; a folder that is not a
finished, matching, complete build must change nothing.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TAGS = ("manylinux_2_35_x86_64", "manylinux_2_35_aarch64", "win_amd64")
OLD = "a" * 64
LOCK = f"""# shack-sdr, the decoder host (openhamshack docs/RADIO-SDR-PLAN.md, Milestones
# 1, 2 and 4). Built by ohs-libs tools/build-sdr-wheels.sh at ohs-libs main
# c4dd24c (28/10/2026; still 0.2.0, no version bump; SHA256SUMS in
# ~/build/ohs-dist/shack-sdr-adsb2 match the lines below): nothing reaches a
# receiver's C library once it is closed (the segfault in _ctypes).
# 21226b1 before it (shack-sdr-adsb1): the `adsb` decoder.
#
# There is no macOS wheel yet.
shack-sdr==0.2.0 --hash=sha256:{OLD}  # manylinux_2_35_x86_64
shack-sdr==0.2.0 --hash=sha256:{OLD}  # manylinux_2_35_aarch64
shack-sdr==0.2.0 --hash=sha256:{OLD}  # win_amd64
#
# The encumbered check, after the pins.
"""


class VendorShackSdr(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.nb = self.tmp / "nb"
        (self.nb / "tools" / "vendor").mkdir(parents=True)
        shutil.copy2(REPO / "tools" / "vendor-shack-sdr.sh", self.nb / "tools")
        self.lock = self.nb / "tools" / "vendor" / "shack-sdr.lock"
        self.lock.write_text(LOCK)
        for t in TAGS:
            (self.nb / "tools" / "vendor" / f"shack_sdr-0.2.0-cp311-abi3-{t}.whl").write_text("old " + t)
        # ohs-libs, with the commit the new build was made from.
        self.libs = self.tmp / "libs"
        self.libs.mkdir()
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "shack_sdr dmr: talker alias from the embedded LC")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=self.libs,
                              check=True, capture_output=True, text=True).stdout

    def build(self, name="shack-sdr-dmr2", tags=TAGS, version="0.2.0", status="built", commit=None):
        d = self.tmp / "dist" / name
        d.mkdir(parents=True)
        for t in tags:
            (d / f"shack_sdr-{version}-cp311-abi3-{t}.whl").write_text(f"new {t} {version}")
        sums = "".join(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}\n" for w in sorted(d.glob("*.whl")))
        (d / "SHA256SUMS").write_text(sums)
        (d / "BUILD-INFO").write_text(f"commit={commit or self.commit}\nbuilt=2026-10-29T09:15:00+00:00\n"
                                      f"host=shack\nstatus={status}\n")
        return d

    def vendor(self, *args):
        return subprocess.run(["sh", str(self.nb / "tools" / "vendor-shack-sdr.sh"), *args], cwd=self.tmp,
                              env={**os.environ, "OHS_LIBS": str(self.libs)}, capture_output=True, text=True,
                              timeout=60)

    def pins(self):
        return re.findall(r"^shack-sdr==(\S+) --hash=sha256:([0-9a-f]{64})  # (\S+)$", self.lock.read_text(), re.M)

    def test_hashes_wheels_and_header_follow_the_build(self):
        d = self.build()
        res = self.vendor(str(d))
        self.assertEqual(res.returncode, 0, res.stderr)
        want = {t: hashlib.sha256(f"new {t} 0.2.0".encode()).hexdigest() for t in TAGS}
        self.assertEqual({t: h for _, h, t in self.pins()}, want)
        vendored = {w.name: w.read_text() for w in (self.nb / "tools" / "vendor").glob("*.whl")}
        self.assertEqual(set(vendored), {f"shack_sdr-0.2.0-cp311-abi3-{t}.whl" for t in TAGS})
        self.assertTrue(all(v.startswith("new") for v in vendored.values()))
        text = " ".join(l[2:] for l in self.lock.read_text().splitlines() if l.startswith("# "))
        self.assertIn(f"Built by ohs-libs tools/build-wheels-safe.sh at ohs-libs main {self.commit[:7]} "
                      "(29/10/2026; shack-sdr 0.2.0; SHA256SUMS in ~/build/ohs-dist/shack-sdr-dmr2 match the "
                      "lines below): shack_sdr dmr: talker alias from the embedded LC.", text)
        # The build it replaces is history now, in its own words, before the older ones.
        self.assertIn("c4dd24c before it (shack-sdr-adsb2): nothing reaches a receiver's C library once it is "
                      "closed (the segfault in _ctypes). 21226b1 before it", text)
        self.assertTrue(self.lock.read_text().startswith("# shack-sdr, the decoder host"))
        self.assertIn("# The encumbered check, after the pins.", self.lock.read_text())
        self.assertTrue(all(len(l) <= 80 for l in self.lock.read_text().splitlines() if l.startswith("# ")))

    def test_why_is_used_when_given(self):
        res = self.vendor("--why", "TII levels in dB", str(self.build()))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("match the lines below): TII levels in dB.", " ".join(self.lock.read_text().split()))

    def test_a_new_platform_is_added_after_the_others(self):
        res = self.vendor(str(self.build(tags=TAGS + ("macosx_11_0_universal2",))))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([t for _, _, t in self.pins()], list(TAGS) + ["macosx_11_0_universal2"])

    def test_a_version_bump_moves_every_pin(self):
        res = self.vendor(str(self.build(version="0.3.0")))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual({v for v, _, _ in self.pins()}, {"0.3.0"})
        self.assertEqual(len(list((self.nb / "tools" / "vendor").glob("shack_sdr-0.2.0-*"))), 0)

    def test_the_same_commit_again_adds_no_history(self):
        res = self.vendor(str(self.build(commit="c4dd24c" + "0" * 33)))
        self.assertEqual(res.returncode, 0, res.stderr)
        text = " ".join(self.lock.read_text().split())
        self.assertIn("~/build/ohs-dist/shack-sdr-dmr2 match the lines below): nothing reaches", text)
        self.assertNotIn("c4dd24c before it", text)

    def assertRefusedUnchanged(self, res, why):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn(why, res.stderr)
        self.assertEqual(self.lock.read_text(), LOCK)
        self.assertTrue(all(w.read_text().startswith("old") for w in (self.nb / "tools" / "vendor").glob("*.whl")))

    def test_an_unfinished_build_is_refused(self):
        self.assertRefusedUnchanged(self.vendor(str(self.build(status="building"))), "status=built")

    def test_wheels_that_do_not_match_their_sums_are_refused(self):
        d = self.build()
        (d / f"shack_sdr-0.2.0-cp311-abi3-{TAGS[0]}.whl").write_text("overwritten by another build")
        self.assertRefusedUnchanged(self.vendor(str(d)), "do not match")

    def test_a_missing_platform_is_refused(self):
        self.assertRefusedUnchanged(self.vendor(str(self.build(tags=TAGS[:2]))), "no wheel for win_amd64")

    def test_an_unknown_commit_needs_why(self):
        d = self.build(commit="f" * 40)
        self.assertRefusedUnchanged(self.vendor(str(d)), "--why")


if __name__ == "__main__":
    unittest.main()
