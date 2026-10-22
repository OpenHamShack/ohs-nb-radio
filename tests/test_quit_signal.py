"""SIGTERM, SIGINT and SIGHUP quit both apps' windows the way their own Quit
does (ohscore/ui/qtapp.py QuitOnSignals): the real program, started as an
operator starts it (python -m ohsnb / ohsradio, offscreen, the simulator), is
sent the signal once its window is up, and must close its window (which
saves the window's state), end with exit code 0 and leave nothing in
faults.log, where faulthandler writes a crash in C.

The crash this follows (17/10/2026, NB on a Mac, full screen): the old
handler closed the window from inside whatever Qt call the signal landed
in, and Qt went on painting a torn-down window - SIGSEGV in
QBackingStore::endPaint. That needs a Mac's window system to show itself;
here the test proves the quit now goes by the event loop, which is what
removes the hazard on every system."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
@unittest.skipIf(sys.platform == "win32", "Windows has no SIGTERM to send a process that it can catch")
class QuitOnSignal(unittest.TestCase):
    def run_until_signal(self, module: str, prefix: str, signum: int) -> tuple[int, str, Path]:
        tmp = Path(tempfile.mkdtemp(prefix="ohs-quit-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        env = {k: v for k, v in os.environ.items() if not k.startswith((prefix + "_", "OHSNB_", "OHSRADIO_"))}
        env.update({f"{prefix}_CONF": str(tmp / "config.json"), f"{prefix}_DATA": str(tmp / "data"),
                    f"{prefix}_UI_CONF": str(tmp / "ui.json"),
                    # Nothing leaves this machine: no update check, no report upload.
                    f"{prefix}_UPDATE_URL": "http://127.0.0.1:9/feed.json",
                    f"{prefix}_DIAG_URL": "http://127.0.0.1:9/diag",
                    "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(REPO_ROOT)})
        (tmp / "config.json").write_text(json.dumps({"audioBackend": "null", "simSignals": False,
                                                     "checkUpdates": False}), encoding="utf-8")
        (tmp / "ui.json").write_text(json.dumps({"welcomed": True}), encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-X", "faulthandler", "-m", module, "-v"], cwd=str(REPO_ROOT),
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        watchdog = threading.Timer(120, p.kill)
        watchdog.start()
        lines = []
        try:
            for line in p.stdout:
                lines.append(line)
                if "quit through the event loop" in line:
                    break
            time.sleep(1.0)                  # the window painting, its timers running
            p.send_signal(signum)
            lines += p.stdout.readlines()
            p.wait(timeout=60)
        finally:
            watchdog.cancel()
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
        return p.returncode, "".join(lines), tmp

    def check(self, module, prefix, signum):
        code, out, tmp = self.run_until_signal(module, prefix, signum)
        name = signal.Signals(signum).name
        self.assertIn("quit through the event loop (wakeup socket)", out, out[-3000:])
        self.assertEqual(code, 0, out[-3000:])
        self.assertIn(f"{name}: quitting as the Quit command does", out, out[-3000:])
        self.assertNotIn("Fatal Python error", out)
        faults = tmp / "data" / "logs" / "faults.log"
        self.assertEqual(faults.read_text() if faults.exists() else "", "")
        # The window was closed, not abandoned: closing it saves its state.
        ui = json.loads((tmp / "ui.json").read_text(encoding="utf-8"))
        self.assertIn("geometry", ui, sorted(ui))

    def test_nb_sigterm(self):
        self.check("ohsnb", "OHS_NB", signal.SIGTERM)

    def test_nb_sighup(self):
        self.check("ohsnb", "OHS_NB", signal.SIGHUP)

    def test_radio_sigint(self):
        self.check("ohsradio", "OHS_RADIO", signal.SIGINT)


if __name__ == "__main__":
    unittest.main()
