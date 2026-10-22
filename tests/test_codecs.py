import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""codec2 through the shared codec loader (ohscore/sdr.py, shack_sdr codecs;
RADIO-SDR-PLAN §5, §8.1 item 2): FreeDV's ctypes binding opens the file the
loader chose, which is one that passed its probe in a child process - an
explicit SHACK_CODEC_CODEC2 first, a file that is not a codec2 refused and
the search carrying on past it - and a frozen build's probe is the program
itself, the console twin on Windows."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ohscore import sdr

ROOT = Path(__file__).resolve().parent.parent


def _libname(env_extra: dict) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHACK_CODEC_")}
    env.update(env_extra)
    env["PYTHONPATH"] = str(ROOT)
    with tempfile.TemporaryDirectory() as cwd:
        res = subprocess.run([sys.executable, "-c", "from ohscore.modes import freedv; print(freedv._LIBNAME)"],
                             env=env, cwd=cwd, capture_output=True, text=True, timeout=120)
    if res.returncode:
        raise AssertionError(res.stderr)
    return res.stdout.strip().splitlines()[-1]


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Codec2ThroughTheLoader(unittest.TestCase):
    def setUp(self):
        self.system = sdr.codec_path("codec2")
        if not self.system:
            self.skipTest("no codec2 installed here to copy")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_an_explicit_library_is_the_one_freedv_opens(self):
        copy = Path(self.tmp.name) / "libcodec2.so.1.2"
        shutil.copy(self.system, copy)
        self.assertEqual(_libname({"SHACK_CODEC_CODEC2": str(copy)}), str(copy))

    def test_a_file_that_is_not_codec2_is_refused_and_the_search_goes_on(self):
        bad = Path(self.tmp.name) / "libcodec2.so.1.2"
        bad.write_bytes(b"\x7fELF this is not a library")
        got = _libname({"SHACK_CODEC_CODEC2": str(bad)})
        self.assertNotEqual(got, str(bad))
        self.assertEqual(Path(got).name, Path(self.system).name)

    def test_the_status_says_found_and_where(self):
        st = next(c for c in sdr.codecs().status() if c["id"] == "codec2")
        self.assertEqual(st["state"], "found")
        self.assertTrue(st["shippable"])
        others = {c["id"]: c for c in sdr.codecs().status() if c["id"] != "codec2"}
        self.assertEqual(set(others), {"faad2", "fdk-aac", "mbelib"})
        for c in others.values():
            self.assertFalse(c["shippable"])


class FrozenProbe(unittest.TestCase):
    def test_from_source_the_loader_uses_its_own_python_module(self):
        self.assertIsNone(sdr.probe_argv())

    def test_a_frozen_build_probes_with_itself_and_windows_with_its_console_twin(self):
        with tempfile.TemporaryDirectory() as tmp:
            gui = Path(tmp) / "openhamshack-radio.exe"
            gui.write_bytes(b"")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", str(gui)), mock.patch.object(sys, "platform", "win32"):
                self.assertEqual(sdr.probe_argv(), [str(gui), "--codec-probe"])
                (Path(tmp) / "openhamshack-radio-console.exe").write_bytes(b"")
                self.assertEqual(sdr.probe_argv(),
                                 [str(Path(tmp) / "openhamshack-radio-console.exe"), "--codec-probe"])
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "executable", "/Applications/R.app/Contents/MacOS/openhamshack-radio"), \
                    mock.patch.object(sys, "platform", "darwin"):
                self.assertEqual(sdr.probe_argv(),
                                 ["/Applications/R.app/Contents/MacOS/openhamshack-radio", "--codec-probe"])

    @unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
    def test_the_apps_answer_the_probe_before_anything_else(self):
        path = sdr.codec_path("codec2")
        if not path:
            self.skipTest("no codec2 installed here")
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        for app in ("ohsradio", "ohsnb"):
            with self.subTest(app=app):
                res = subprocess.run([sys.executable, "-m", app, "--codec-probe", "codec2", path], env=env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn('"ok": true', res.stdout)


if __name__ == "__main__":
    unittest.main()
