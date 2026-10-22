import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""shack-sdr as this repository vendors it (tools/vendor/shack-sdr.lock):
the one native wheel, one per platform, chosen for the machine a build is
for; the packages carrying the right one or, for the .deb's "all", none;
a checkout importing it through ohscore/shacklibs.py; and the encumbered
check every installer goes through (RADIO-SDR-PLAN 5.5), run for real on
stand-in files - a clean folder passes, one carrying a codec's name, or a
binary defining one of its entry points, fails, and a hand-edited copy of
the check is refused before it can run."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
import shack_vendor  # noqa: E402

from ohscore import shacklibs  # noqa: E402


class PlatformWheels(unittest.TestCase):
    def test_each_pinned_platform_gets_its_own_wheel_and_only_that(self):
        with tempfile.TemporaryDirectory() as tmp:
            for tag, want in (("linux_x86_64", "x86-64"), ("linux_aarch64", "AArch64"), ("win_amd64", None)):
                dest = Path(tmp) / tag
                shack_vendor.unpack(ROOT, dest, tag)
                native = sorted(p.name for p in (dest / "shack_sdr").glob("_native*"))
                self.assertEqual(len(native), 1, (tag, native))
                data = (dest / "shack_sdr" / native[0]).read_bytes()
                if tag == "win_amd64":
                    self.assertTrue(data.startswith(b"MZ"), tag)
                else:
                    self.assertTrue(data.startswith(b"\x7fELF"), tag)
                    machine = int.from_bytes(data[18:20], "little")
                    self.assertEqual({0x3E: "x86-64", 0xB7: "AArch64"}[machine], want)

    def test_a_platform_with_no_pinned_wheel_stops_the_build_with_a_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                shack_vendor.unpack(ROOT, Path(tmp) / "mac", "macosx")
            self.assertIn("no shack_sdr wheel for macosx", str(cm.exception))
            self.assertIn("could not decode RTTY", str(cm.exception))

    def test_the_pure_set_carries_no_native_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = shack_vendor.unpack(ROOT, Path(tmp) / "all", "pure")
            self.assertFalse((dest / "shack_sdr").exists())
            self.assertTrue((dest / "shack_cw").is_dir())

    def test_a_wheel_that_is_not_the_pinned_one_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "root"
            shutil.copytree(ROOT / "tools" / "vendor", fake / "tools" / "vendor")
            whl = next((fake / "tools" / "vendor").glob("shack_sdr-*x86_64.whl"))
            with zipfile.ZipFile(whl, "a") as z:
                z.writestr("shack_sdr/extra.py", "")
            with self.assertRaises(SystemExit) as cm:
                shack_vendor.unpack(fake, Path(tmp) / "out", "linux_x86_64")
            self.assertIn("is not a wheel the locks", str(cm.exception))

    def test_frozen_builds_name_the_native_module_as_an_import_not_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = shack_vendor.unpack(ROOT, Path(tmp) / "w", "win_amd64")
            self.assertIn("shack_sdr._native", shack_vendor.hidden(dest))
            self.assertIn("shack_sdr.sources.rtlsdr", shack_vendor.hidden(dest))
            self.assertFalse([d for d in shack_vendor.datas(dest) if "_native" in d[0]])


class Checkout(unittest.TestCase):
    def test_tags_pick_the_wheel_for_this_kind_of_machine(self):
        name = "shack_sdr-0.1.0-cp311-abi3-manylinux_2_35_{}.whl"
        self.assertTrue(shacklibs.runs_on(name.format("x86_64"), "linux_x86_64"))
        self.assertFalse(shacklibs.runs_on(name.format("aarch64"), "linux_x86_64"))
        self.assertTrue(shacklibs.runs_on(name.format("aarch64"), shacklibs.platform_tag("linux", "arm64")))
        self.assertFalse(shacklibs.runs_on("shack_sdr-0.1.0-cp311-abi3-win_amd64.whl", "linux_x86_64"))
        self.assertTrue(shacklibs.runs_on("shack_sdr-0.1.0-cp311-abi3-win_amd64.whl",
                                          shacklibs.platform_tag("win32", "AMD64")))
        self.assertTrue(shacklibs.runs_on("shack_cw-0.1.0-py3-none-any.whl", "macosx"))

    def test_a_checkout_imports_the_pinned_wheel_for_this_machine(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as cache:
            env["XDG_CACHE_HOME"] = cache
            res = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                                  "from ohscore import shacklibs; m = shacklibs.sdr(); print(m.__file__); "
                                  "print([e['id'] for e in m.catalogue()][0])", str(ROOT)],
                                 env=env, capture_output=True, text=True, timeout=60, cwd=cache)
        self.assertEqual(res.returncode, 0, res.stderr)
        path, first = res.stdout.split()
        whl = next(w for w in (ROOT / "tools" / "vendor").glob("shack_sdr-*.whl")
                   if shacklibs.runs_on(w.name, shacklibs.platform_tag()))
        digest = hashlib.sha256(whl.read_bytes()).hexdigest()
        self.assertIn(digest[:16], path)
        self.assertEqual(first, "rtty")


class Encumbered(unittest.TestCase):
    def check(self, *paths, skip=()):
        with open(os.devnull, "w") as quiet:
            old = os.dup(1)
            os.dup2(quiet.fileno(), 1)
            try:
                return shack_vendor.encumbered(ROOT, list(paths), skip=skip)
            finally:
                os.dup2(old, 1)
                os.close(old)

    def test_the_vendored_wheels_are_clean(self):
        self.assertEqual(self.check(*sorted((ROOT / "tools" / "vendor").glob("shack_sdr-*.whl"))), 0)

    def test_a_folder_carrying_a_codec_fails_and_without_it_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lib").mkdir()
            (Path(tmp) / "lib" / "readme.txt").write_text("nothing here\n")
            self.assertEqual(self.check(tmp), 0)
            (Path(tmp) / "lib" / "libfaad.so.2").write_bytes(b"not even a binary")
            self.assertEqual(self.check(tmp), 1)

    def test_a_binary_defining_a_codec_entry_point_fails(self):
        cc = shutil.which("cc") or shutil.which("gcc")
        if cc is None:
            self.skipTest("no C compiler to build a stand-in library")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "stub.c"
            src.write_text("int NeAACDecDecode(void) { return 0; }\n")
            subprocess.run([cc, "-shared", "-fPIC", "-o", str(Path(tmp) / "libhelper.so"), str(src)], check=True)
            src.unlink()
            self.assertEqual(self.check(tmp), 1)

    def test_sdrplay_files_count_unless_the_store_check_says_they_are_still_carried(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sdrplay_apiService").write_bytes(b"#!/bin/sh\n")
            self.assertEqual(self.check(tmp), 1)
            self.assertEqual(self.check(tmp, skip=("libsdrplay_api*", "sdrplay_api*.dll", "sdrplay_apiService*",
                                                   "sdrplay_api_*")), 0)

    def test_a_hand_edited_check_is_refused_before_it_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "root"
            shutil.copytree(ROOT / "tools" / "vendor", fake / "tools" / "vendor")
            script = fake / "tools" / "vendor" / "encumbered" / "check-encumbered.py"
            script.write_text(script.read_text() + "\n# edited\n")
            with self.assertRaises(SystemExit) as cm:
                shack_vendor.encumbered(fake, [tmp])
            self.assertIn("is not the copy shack-sdr.lock pins", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
