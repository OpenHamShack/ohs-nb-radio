import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The ohs-ohsdigi wheel as an app gets it: pip-installed into a fresh venv,
imported from there as `ohsdigi`, and its app API (decode, encode_audio,
version - docs/OHSDIGI-PYTHON.md) round-tripped: a message encoded to audio,
laid into a slot with noise, and decoded back, in FT8 and FT4, from each
kind of buffer an app might hold.

What test_ohsdigi.py proves of the bare module copied into ohscore, this
proves of the wheel: that it installs, that the package maturin wraps the
module in still exposes everything (it once would have hidden
__version__), and that the binary inside it - not the source - works.

The wheel is OHSDIGI_WHEEL if set, else the one in rust/dist/wheels/ for
this machine (tools/build-wheels.sh); without one the tests skip. The venv
goes under OHSDIGI_WHEEL_WORK, else the real ~/build when there is one (a
venv is too big for a shared /tmp), else the system temporary folder.
Only the standard library is used, so the same file runs in the bookworm
build container's Python 3.11 - the oldest the abi3 wheel promises - and
on the Mac.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WHEELS = REPO / "rust" / "dist" / "wheels"


def _runs_here(platform_tag):
    """Whether a wheel's platform tag (possibly several joined by '.')
    names this machine. Matched on OS and architecture together: a macOS
    universal2 tag says x86_64 too, and an amd64 Linux must not pick it."""
    m = platform.machine().lower()
    for tag in platform_tag.split("."):
        if sys.platform == "darwin":
            if tag.startswith("macosx_") and tag.endswith(("_universal2", "_" + m)):
                return True
        elif sys.platform == "win32":
            if tag == {"amd64": "win_amd64", "x86_64": "win_amd64", "arm64": "win_arm64"}.get(m):
                return True
        elif tag.startswith(("manylinux", "linux_")):
            if tag.endswith("_" + {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)):
                return True
    return False


def _find_wheel():
    if os.environ.get("OHSDIGI_WHEEL"):
        return Path(os.environ["OHSDIGI_WHEEL"])
    if not WHEELS.is_dir():
        return None
    for w in sorted(WHEELS.glob("ohs_ohsdigi-*.whl")):
        if _runs_here(w.name[:-len(".whl")].rsplit("-", 1)[-1]):
            return w
    return None


def _work_parent():
    if os.environ.get("OHSDIGI_WHEEL_WORK"):
        p = Path(os.environ["OHSDIGI_WHEEL_WORK"])
        p.mkdir(parents=True, exist_ok=True)
        return p
    real = Path(os.environ.get("OHSTEST_REAL_HOME", Path.home())) / "build"
    return real if real.is_dir() else None


WHEEL = _find_wheel()

# Run inside the venv; prints one JSON object. A slot is built the way a
# receiver would hand one over: 12 kHz mono from the slot boundary, the
# transmission starting 0.5 s in (where WSJT-X sends it), in Gaussian noise
# of a fixed seed. Signal 0.05 peak in noise of 0.1 rms is about -6 dB in
# 2500 Hz - comfortably decodable, but not a clean tone the decoder could
# find by accident of having nothing else to look at.
ROUND_TRIP = r'''
import array, json, random, sys, importlib.metadata as md
import ohsdigi

out = {"file": ohsdigi.__file__, "version": ohsdigi.version(), "dunder": ohsdigi.__version__,
       "dist": md.version("ohs-ohsdigi"), "modes": list(ohsdigi.MODES), "wsjtx": ohsdigi.WSJTX_VERSION}

def slot(mode, message, freq, seconds):
    sig = array.array("f")
    sig.frombytes(ohsdigi.encode_audio(mode, message, freq))
    rnd = random.Random(1234)
    n = int(seconds * 12000)
    x = array.array("f", (rnd.gauss(0.0, 0.1) for _ in range(n)))
    start = 6000
    for i, s in enumerate(sig[: n - start]):
        x[start + i] += 0.05 * s
    return sig, x

for mode, seconds, freq in (("ft8", 15.0, 1234.0), ("ft4", 7.5, 987.0)):
    sig, x = slot(mode, "CQ G4XYZ IO91", freq, seconds)
    i16 = array.array("h", (max(-32768, min(32767, round(v * 32767))) for v in x))
    f64 = array.array("d", x)
    r = {"samples": len(sig), "peak": max(abs(v) for v in sig)}
    r["float32"] = ohsdigi.decode(mode, x, time=1700000000.0)
    r["float64"] = ohsdigi.decode(mode, memoryview(f64), time="120000")
    r["int16"] = ohsdigi.decode(mode, i16)
    r["bytes"] = ohsdigi.decode(mode, i16.tobytes())
    r["silence"] = ohsdigi.decode(mode, array.array("h", bytes(2 * int(seconds * 12000))))
    out[mode] = r

# JS8 (ohsdigi 10/10/2026 on): a heartbeat's one frame, sent 0.5 s into a
# Normal period at the same level, read back as JS8Call shows it.
if hasattr(ohsdigi, "js8_decode"):
    (frame, i3bit), = ohsdigi.js8_frames("HB IO75", "GM4BRI", "IO75")
    sig = array.array("f")
    sig.frombytes(ohsdigi.js8_encode_audio(frame, i3bit, "normal", 1300.0))
    rnd = random.Random(99)
    x = array.array("f", (rnd.gauss(0.0, 0.1) for _ in range(15 * 12000)))
    for i, s in enumerate(sig):
        x[6000 + i] += 0.05 * s
    out["js8"] = {"frame": frame, "samples": len(sig), "decodes": ohsdigi.js8_decode(x, "normal")}

# Q65 (ohsdigi 10/10/2026 on): a Q65-60A transmission 1 s into its period.
if hasattr(ohsdigi, "q65_decode"):
    sig = array.array("f")
    sig.frombytes(ohsdigi.q65_encode_audio("CQ G4XYZ IO91", 60, "A", 1500.0))
    rnd = random.Random(65)
    x = array.array("f", (rnd.gauss(0.0, 0.1) for _ in range(60 * 12000)))
    for i, s in enumerate(sig):
        x[12000 + i] += 0.05 * s
    out["q65"] = {"samples": len(sig), "decodes": ohsdigi.q65_decode(x, 60, "A")}

try:
    ohsdigi.encode_audio("ft8", "K1ABC W9XYZ +999")
    out["bad"] = None
except ohsdigi.BadMessage as e:
    out["bad"] = ["BadMessage", isinstance(e, ValueError)]
try:
    ohsdigi.decode("ft8", [0.0] * 100)
    out["list"] = None
except TypeError as e:
    out["list"] = str(e)
print(json.dumps(out))
'''


@unittest.skipUnless(WHEEL is not None and WHEEL.exists(),
                     "no ohs-ohsdigi wheel for this machine (tools/build-wheels.sh)")
class WheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="ohsdigi-wheel-", dir=_work_parent()))
        # A class cleanup, not tearDownClass: it runs when setUpClass fails
        # too, which is exactly when a half-made venv would be left behind.
        cls.addClassCleanup(shutil.rmtree, cls.work, ignore_errors=True)
        venv = cls.work / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        # --no-index: the wheel must install from nothing but itself (it
        # has no dependencies; a host with no route out must manage it).
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-index", "--disable-pip-version-check",
                        str(WHEEL)], check=True)
        # From the work folder, so neither the repo's ohscore nor anything
        # beside this file can be what gets imported.
        p = subprocess.run([str(py), "-I", "-c", ROUND_TRIP], cwd=cls.work, capture_output=True, text=True,
                           timeout=600)
        if p.returncode:
            raise AssertionError(f"round trip failed in the venv:\n{p.stderr}")
        cls.r = json.loads(p.stdout)
        cls.venv = venv

    def test_imported_from_the_venv_not_the_tree(self):
        self.assertTrue(Path(self.r["file"]).resolve().is_relative_to(self.venv.resolve()), self.r["file"])

    def test_one_version_everywhere(self):
        name_version = WHEEL.name.split("-")[1]
        self.assertEqual({self.r["version"], self.r["dunder"], self.r["dist"]}, {name_version})
        self.assertEqual(self.r["wsjtx"], "2.7.0")
        self.assertEqual(self.r["modes"], ["ft8", "ft4"])

    def _check(self, mode, freq, n_samples):
        r = self.r[mode]
        self.assertEqual(r["samples"], n_samples)
        self.assertLessEqual(r["peak"], 1.0)
        for kind in ("float32", "float64", "int16", "bytes"):
            with self.subTest(kind=kind):
                d = r[kind]
                self.assertEqual([x["message"] for x in d], ["CQ G4XYZ IO91"], d)
                d = d[0]
                self.assertEqual(d["mode"], mode)
                self.assertAlmostEqual(d["freq"], freq, delta=3.0)
                self.assertAlmostEqual(d["dt"], 0.0, delta=0.1)
                self.assertTrue(-15 <= d["snr"] <= 5, d["snr"])
                self.assertEqual(set(d), {"time", "snr", "dt", "freq", "message", "mode",
                                          "bits", "ap", "hard_errors", "qual"})
        self.assertEqual(r["float32"][0]["time"], 1700000000.0)
        self.assertEqual(r["float64"][0]["time"], "120000")
        self.assertIsNone(r["int16"][0]["time"])
        self.assertEqual(r["silence"], [])

    def test_ft8_round_trip(self):
        # 79 symbols of 1920 samples, the ramps included.
        self._check("ft8", 1234.0, 151_680)

    def test_ft4_round_trip(self):
        # 103 symbols and two ramp symbols of 576 samples.
        self._check("ft4", 987.0, 60_480)

    def test_js8_round_trip(self):
        if "js8" not in self.r:
            self.skipTest("this wheel predates JS8")
        r = self.r["js8"]
        self.assertEqual(r["samples"], 79 * 1920)
        self.assertEqual([(d["frame"], d["text"], d["kind"]) for d in r["decodes"]],
                         [(r["frame"], "GM4BRI: @HB HEARTBEAT IO75 ", "heartbeat")])
        self.assertAlmostEqual(r["decodes"][0]["freq"], 1300.0, delta=1.0)

    def test_q65_round_trip(self):
        if "q65" not in self.r:
            self.skipTest("this wheel predates Q65")
        r = self.r["q65"]
        self.assertEqual(r["samples"], 85 * 7200)
        self.assertEqual([(d["text"], d["ap"]) for d in r["decodes"]], [("CQ G4XYZ IO91", 0)])

    def test_refusals(self):
        self.assertEqual(self.r["bad"], ["BadMessage", True])
        self.assertIn("int16, float32 or float64", self.r["list"] or "")


if __name__ == "__main__":
    unittest.main()
