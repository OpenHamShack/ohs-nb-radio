"""The suite never writes to the operator's real config or data folders.

scratch_home.py moves HOME/APPDATA and both apps' variables to a
throw-away folder when a test file imports it. These check that this
actually holds, by doing it rather than by reading the test files: every
test file is imported on its own in a fresh interpreter whose home is a
decoy, and the apps' folders are then asked where they are; and both apps
are run headless, as the release suite's subprocesses run them, and the
real folders are compared before and after.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

# Runs in the child, with tests/ and the repository on sys.path. Between
# test files the environment goes back to the decoy's and every module
# loaded from tests/ is forgotten, so each file has to redirect the home
# by itself: a file that relied on an earlier one having imported
# scratch_home (as discovery's alphabetical order would hide) fails here.
_CHILD = r"""
import importlib, json, os, sys, unittest
from pathlib import Path
from ohscore import host
from ohsnb import config as nb_config
from ohsradio import config as ham_config

tests, decoy = Path(sys.argv[1]), Path(sys.argv[2])
base = dict(os.environ)
bad = {}
for name in sys.argv[3:]:
    os.environ.clear()
    os.environ.update(base)
    for m, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and Path(f).resolve().parent == tests:
            del sys.modules[m]
    try:
        importlib.import_module(name)
    except unittest.SkipTest:
        pass          # skipped where it cannot run (no dpkg-deb...): still imported first
    except Exception as e:  # noqa: BLE001
        bad[name] = f"import failed: {e!r}"
        continue
    paths = [nb_config.conf_path(), nb_config.data_dir(), ham_config.conf_path(), ham_config.data_dir(),
             host.conf_dir("openhamshack-nb"), host.data_dir("openhamshack-radio"),
             host.conf_dir("openhamshack-nb"), host.data_dir("openhamshack-ham")]
    leaked = [str(p) for p in paths if Path(p).resolve().is_relative_to(decoy)]
    if leaked:
        bad[name] = leaked
print(json.dumps(bad))
"""


def snapshot(dirs):
    """Every file under `dirs` with its size, mtime and content: enough to
    see any write, including one that puts back the same bytes."""
    out = {}
    for d in dirs:
        if not d.exists():
            out[str(d)] = None
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns, p.read_bytes())
    return out


class EveryTestFile(unittest.TestCase):
    def test_each_file_alone_moves_the_home(self):
        names = sorted(p.stem for p in TESTS.glob("test_*.py"))
        self.assertIn("test_lock", names)
        with tempfile.TemporaryDirectory() as decoy:
            decoy = Path(decoy).resolve()
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("OHS_NB_", "OHS_RADIO_", "OHSNB_", "OHSRADIO_", "OHSTEST_"))}
            env["HOME"] = str(decoy)
            env["APPDATA"] = str(decoy / "AppData" / "Roaming")
            env["PYTHONPATH"] = os.pathsep.join([str(TESTS), str(REPO_ROOT)])
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
            res = subprocess.run([sys.executable, "-c", _CHILD, str(TESTS), str(decoy), *names],
                                 cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(res.returncode, 0, res.stderr[-3000:])
            bad = json.loads(res.stdout.strip().splitlines()[-1])
            self.assertEqual(bad, {}, "these test files would use the real config folders; "
                                      "make `import scratch_home` their first import")


class HeadlessRuns(unittest.TestCase):
    """Both apps headless, persisting as an operator's run does (no
    override flags), in child processes that inherit the suite's
    environment. The scratch config is seeded first and each run is shown
    to have read or written it: real folders found unchanged prove nothing
    about a run that never looked for its config at all."""

    def setUp(self):
        self.real = scratch_home.real_dirs()
        for d in self.real:
            self.assertFalse(scratch_home.ROOT.resolve().is_relative_to(d.resolve()))
        self.before = snapshot(self.real)
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(REPO_ROOT)

    def tearDown(self):
        self.assertEqual(snapshot(self.real), self.before, "a headless run wrote to the real config")

    # Every seed turns the simulator's other stations off: rendering them
    # is eight seconds of start-up per run and nothing here listens to them.
    def seed(self, env_prefix, cfg):
        conf = Path(os.environ[f"{env_prefix}_CONF"])
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(json.dumps(cfg), encoding="utf-8")
        return conf

    def run_app(self, module, seconds):
        res = subprocess.run([sys.executable, "-m", module, "--headless", "--seconds", str(seconds)],
                             cwd=str(REPO_ROOT), env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stderr[-3000:])
        return res.stdout

    def test_both_apps_read_their_config_from_scratch(self):
        # A dial away from each app's default, reported back when it stops.
        self.seed("OHS_NB", {"audioBackend": "null", "simSignals": False, "vfo": 10_489_520_000.0})
        self.assertIn("dial was in CW only", self.run_app("ohsnb", 1))
        self.seed("OHS_RADIO", {"audioBackend": "null", "simSignals": False, "vfo": 145_437_500.0})
        self.assertIn("dial was 145.437500 MHz", self.run_app("ohsradio", 1))

    @unittest.skipIf(sys.platform == "win32", "stopping the run as Ctrl-C does needs a POSIX signal; "
                                              "the read check above covers the folders on Windows")
    def test_nb_saves_its_lock_correction_into_scratch(self):
        # The write that reached the development machine's config on 04/10: NB saves the
        # beacon-lock correction when it stops. The run is stopped by SIGINT
        # once it reports lock rather than after a fixed time: how long lock
        # takes depends on how busy the machine is, and a two-second run
        # that ended before lock saved nothing - it failed this test once in
        # four tries while it was being written.
        conf = self.seed("OHS_NB", {"audioBackend": "null", "simSignals": False})
        p = subprocess.Popen([sys.executable, "-m", "ohsnb", "--headless", "--seconds", "0"],
                             cwd=str(REPO_ROOT), env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        watchdog = threading.Timer(90, p.kill)
        watchdog.start()
        lines = []
        try:
            for line in p.stdout:
                lines.append(line)
                if "rx-lock locked" in line:
                    break
            p.send_signal(signal.SIGINT)
            lines += p.stdout.readlines()
            p.wait(timeout=60)
        finally:
            watchdog.cancel()
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
        out = "".join(lines)
        self.assertIn("rx-lock locked", out)
        self.assertEqual(p.returncode, 0, out[-3000:])
        self.assertNotEqual(json.loads(conf.read_text(encoding="utf-8")).get("rxCorr", 0.0), 0.0, out[-3000:])


if __name__ == "__main__":
    unittest.main()
