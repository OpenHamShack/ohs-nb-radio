"""The operator's state - the dial above all - reaches config.json soon
after it changes, and on any clean shutdown, whether or not the radio is
running (ohscore/engine.py `dirty`, `_saver_loop`, `stop`; the server's
`shutdown`).

What this follows (23/10/2026): ohs-box's Radio was on 145.650 MHz, but
config.json still said 145.500 when the 0.1.22-beta.3 update restarted
it, so it came back on 145.500. Until then unsaved state was written only
by the supervisor, which runs only while the radio does, and stop() saved
only a running radio: a dial moved while the radio was stopped, failing
to open or waiting for the broker was never written, and anything left
for stop() was lost to a kill after the container's grace period.

The file itself is replaced atomically (ohscore/config.py Config.save):
a crash part-way through a write leaves the old file whole."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ohscore.audio import NullAudio
from test_core_engine import TinyEngine

REPO_ROOT = Path(__file__).resolve().parent.parent


class CountingConfig:
    """The engine's Config with every write timed and counted."""

    def __init__(self, real):
        self.real, self.writes = real, []

    def save(self, cfg, path=None):
        self.real.save(cfg, path)
        self.writes.append((time.monotonic(), cfg.get("vfo")))

    def __getattr__(self, name):
        return getattr(self.real, name)


class EngineSaves(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.conf = Path(tmp.name) / "config.json"
        self.e = TinyEngine({"device": "sim", "audioBackend": "null"}, persist=True, conf_path=self.conf,
                            data_dir=tmp.name, audio=NullAudio(realtime=False))
        self.addCleanup(self.e.stop)
        self.cfg = CountingConfig(self.e.CONFIG)
        self.e.CONFIG = self.cfg

    def on_disk(self):
        return json.loads(self.conf.read_text())["vfo"] if self.conf.exists() else None

    def wait_for_write(self, n=1, timeout=6.0):
        end = time.monotonic() + timeout
        while len(self.cfg.writes) < n and time.monotonic() < end:
            time.sleep(0.02)

    def test_a_change_while_stopped_is_saved_soon_without_a_supervisor(self):
        self.assertFalse(self.e.running)
        t0 = time.monotonic()
        self.e.set(vfo=145_650_000.0)
        self.wait_for_write()
        self.assertEqual(self.on_disk(), 145_650_000.0)
        self.assertLess(self.cfg.writes[0][0] - t0, self.e.SAVE_QUIET_S + 1.0)

    def test_a_burst_of_changes_is_written_once_after_the_debounce(self):
        last = 0.0
        for k in range(10):                  # a dial spun for half a second
            self.e.set(vfo=145_500_000.0 + k * 12_500.0)
            last = time.monotonic()
            time.sleep(0.05)
        self.wait_for_write()
        time.sleep(self.e.SAVE_QUIET_S + 0.5)       # and nothing more after it
        self.assertEqual(len(self.cfg.writes), 1, self.cfg.writes)
        when, vfo = self.cfg.writes[0]
        self.assertEqual(vfo, 145_612_500.0)
        self.assertGreaterEqual(when - last, self.e.SAVE_QUIET_S - 0.05)
        self.assertEqual(self.on_disk(), 145_612_500.0)

    def test_a_dial_that_never_rests_is_still_written_within_the_longest_wait(self):
        t0 = time.monotonic()
        end = t0 + self.e.SAVE_LONGEST_S + 1.0
        k = 0
        while time.monotonic() < end and not self.cfg.writes:
            self.e.set(vfo=145_500_000.0 + k * 12_500.0)
            k += 1
            time.sleep(0.2)
        self.assertTrue(self.cfg.writes)
        self.assertLess(self.cfg.writes[0][0] - t0, self.e.SAVE_LONGEST_S + 0.5)

    def test_a_change_then_a_stop_is_on_disk_at_once_running_or_not(self):
        self.e.set(vfo=145_650_000.0)
        self.e.stop()                         # not running: used to return without saving
        self.assertEqual(self.on_disk(), 145_650_000.0)
        self.e.start()
        self.e.set(vfo=145_675_000.0)
        self.e.stop()                         # well inside the debounce
        self.assertEqual(self.on_disk(), 145_675_000.0)

    def test_the_saver_thread_goes_once_everything_is_written(self):
        self.e.set(vfo=145_650_000.0)
        self.assertIsNotNone(self.e.saver_thread)
        self.wait_for_write()
        end = time.monotonic() + 2.0
        while self.e.saver_thread is not None and time.monotonic() < end:
            time.sleep(0.02)
        self.assertIsNone(self.e.saver_thread)
        self.e.set(vfo=145_700_000.0)         # and the next change starts one again
        self.wait_for_write(2)
        self.assertEqual(self.on_disk(), 145_700_000.0)


class AWriteCutShortLeavesTheOldFile(unittest.TestCase):
    """Config.save writes a temporary file, fsyncs it and renames it over
    config.json, so the file is always the old one or the new one."""

    def setUp(self):
        from ohsradio.config import CONFIG
        self.CONFIG = CONFIG
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.conf = self.dir / "config.json"
        CONFIG.save({"vfo": 145_500_000.0}, self.conf)
        self.before = self.conf.read_bytes()

    def test_an_error_mid_write_leaves_the_old_file_and_no_temporary_one(self):
        with mock.patch("ohscore.config.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.CONFIG.save({"vfo": 145_650_000.0}, self.conf)
        self.assertEqual(self.conf.read_bytes(), self.before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["config.json"])

    def test_a_process_killed_mid_write_leaves_the_old_file(self):
        # A real kill, not an exception: the child writes half a file and is
        # SIGKILLed before it can fsync or rename.
        child = (
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "import ohscore.config as c\n"
            "def stall(fd):\n"
            "    print('writing', flush=True)\n"
            "    time.sleep(60)\n"
            "c.os.fsync = stall\n"
            "from ohsradio.config import CONFIG\n"
            "CONFIG.save({'vfo': 145650000.0}, Path(sys.argv[1]))\n")
        p = subprocess.Popen([sys.executable, "-c", child, str(self.conf)], cwd=str(REPO_ROOT),
                             env={**os.environ, "PYTHONPATH": str(REPO_ROOT)}, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "writing")
            p.kill()
            p.wait(timeout=10)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
        self.assertEqual(self.conf.read_bytes(), self.before)
        self.assertEqual(self.CONFIG.load(self.conf)["vfo"], 145_500_000.0)


@unittest.skipIf(sys.platform == "win32", "Windows has no SIGTERM to send a process that it can catch")
class StoreFormSavesOnSigterm(unittest.TestCase):
    """The store form, run as the container runs it (python -m ohsradio
    --server), is sent SIGTERM - what podman stop sends - straight after
    the dial moves, well inside the debounce: the dial is on disk when it
    has exited."""

    SECRET = "test-proxy-secret"

    def test_the_dial_moved_just_before_sigterm_is_saved(self):
        tmp = Path(tempfile.mkdtemp(prefix="ohs-sigterm-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OHS_RADIO_", "OHSRADIO_", "SHACK_"))}
        env.update({"OHS_RADIO_CONF": str(tmp / "config.json"), "OHS_RADIO_DATA": str(tmp / "data"),
                    "OHS_RADIO_UPDATE_URL": "http://127.0.0.1:9/feed.json",
                    "OHS_RADIO_DIAG_URL": "http://127.0.0.1:9/diag", "HOME": str(tmp),
                    "DOCK360_SHACK_PROXY_SECRET": self.SECRET, "PYTHONPATH": str(REPO_ROOT)})
        (tmp / "config.json").write_text(json.dumps({"audioBackend": "null", "simSignals": False,
                                                     "checkUpdates": False, "vfo": 145_500_000.0,
                                                     "licenceClass": "full"}), encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "ohsradio", "--server", "--port", str(port)],
                             cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        watchdog = threading.Timer(120, p.kill)
        watchdog.start()
        out = []
        try:
            for line in p.stdout:
                out.append(line)
                if "serving on" in line:
                    break
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request("POST", "/api/set", json.dumps({"vfo": 145_650_000.0}),
                      {"Content-Type": "application/json", "X-OpenHamShack-Proxy-Secret": self.SECRET,
                       "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": "control",
                       "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
            r = c.getresponse()
            body = r.read()
            c.close()
            self.assertEqual(r.status, 200, body)
            p.send_signal(signal.SIGTERM)
            out += p.stdout.readlines()
            p.wait(timeout=60)
        finally:
            watchdog.cancel()
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()
        self.assertEqual(p.returncode, 0, "".join(out)[-3000:])
        self.assertEqual(json.loads((tmp / "config.json").read_text())["vfo"], 145_650_000.0, "".join(out)[-3000:])


if __name__ == "__main__":
    unittest.main()
