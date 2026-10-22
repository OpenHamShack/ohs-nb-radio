"""ohscore.engine.Engine with nothing of NB's: the smallest app an engine
subclass can be still receives, publishes spectra and keeps its safety
rules. This is what OpenHamShack HAM's Radio will start from; NB's own engine
behaviour is tested through ohsnb.radio.Radio in test_radio.py."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from ohscore.audio import NullAudio
from ohscore.config import AppId, Config
from ohscore.devices import Device, DeviceRegistry
from ohscore.engine import Engine, TxRefused
from ohscore.state import Registry, add_shared_keys

FS = 1_200_000.0


class Noise(Device):
    """A receive-only device producing a tone in noise, in real time-ish
    blocks (no pacing: the engine's threads just run)."""
    kind = "noise"

    def __init__(self, cfg, fs):
        self.fs = fs
        self.rng = np.random.default_rng(1)
        self.n = 0

    def open(self):
        pass

    def set_rx_if(self, hz):
        self.centre = hz

    def read(self, n):
        time.sleep(n / self.fs / 4)
        t = (self.n + np.arange(n)) / self.fs
        self.n += n
        x = 0.01 * (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n))
        return (x + 0.1 * np.exp(2j * np.pi * 100_000.0 * t)).astype(np.complex64)


REG = Registry(["usb", "lsb", "cw", "am"], set())
add_shared_keys(REG)
REG.override("vfo", default=145_000_000.0)
DEVICES = DeviceRegistry()
DEVICES.register("sim", Noise)


class TinyEngine(Engine):
    STATE = REG
    CONFIG = Config(AppId("openhamshack-test", "OHSTEST"), REG)
    DEVICES = DEVICES
    FREQ_KEY = "rf"

    def _initial_tuning(self):
        return 145_000_000.0

    def _off(self, dial):
        return dial - self.rx_if

    def _dial_at(self, off):
        return off + self.rx_if

    def wide_span(self):
        return self.rx_if - 400_000.0, self.rx_if + 400_000.0

    def _tx_guard(self, mode, dial, occupied, req=None):
        return ""

    def _tx_key_up(self, dev):
        dev.tx_start()


class MinimalApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = TinyEngine({"device": "sim", "audioBackend": "null"}, persist=False, data_dir=self.tmp.name,
                            audio=NullAudio(realtime=False))

    def tearDown(self):
        self.e.stop()
        self.tmp.cleanup()

    def test_receives_and_places_the_spectrum_on_the_dial(self):
        wide = self.e.subscribe("wide")
        self.e.start()
        deadline = time.monotonic() + 20
        items = []
        while time.monotonic() < deadline and len(items) < 3:
            self.e.heartbeat()
            items += wide.drain()
            time.sleep(0.05)
        self.assertGreaterEqual(len(items), 3)
        t, start, bin_hz, db = items[-1]
        peak = start + bin_hz * int(np.argmax(db))
        self.assertLess(abs(peak - 145_100_000.0), 2 * bin_hz)

    def test_receive_only_device_refuses_to_key(self):
        self.e.start()
        with self.assertRaisesRegex(TxRefused, "receive-only"):
            self.e.ptt(True)
        self.assertFalse(self.e.state()["keyed"])

    def test_memories_and_log_use_the_apps_frequency_key(self):
        self.e.save_memory("calling", 144_300_000.0, "usb")
        self.e.recall("calling")
        self.assertEqual(self.e.state()["vfo"], 144_300_000.0)
        rec = self.e.log_qso("M0ABC", t=1.0)
        self.assertIn("rf", rec)


class CpuReadout(unittest.TestCase):
    """_rx_loop's cpu/cpuWait split (07/10): cpu is the receive thread's own
    time.thread_time(), cpuWait is wall-clock time a block took beyond that
    - the GIL/scheduler wait 'cpu' used to be charged as if it were work
    (engine.py's _rx_loop comment). A GIL-holding competitor is the one
    thing that reliably tells the two apart without a slow device or a real
    stall: it cannot make the rx thread do more work (cpu stays where it
    is), only keep it waiting longer for its turn at the GIL (cpuWait
    rises) - which is exactly the 41%-shown-while-starved case this was
    built to stop hiding."""

    def setUp(self):
        self.tmps = []

    def tearDown(self):
        for tmp in self.tmps:
            tmp.cleanup()

    def _engine(self):
        tmp = tempfile.TemporaryDirectory()
        self.tmps.append(tmp)
        e = TinyEngine({"device": "sim", "audioBackend": "null"}, persist=False, data_dir=tmp.name,
                        audio=NullAudio(realtime=False))
        self.addCleanup(e.stop)
        return e

    def _run_for(self, e, seconds):
        # e.cpu/e.cpu_wait directly, not state()["cpu"]/["cpuWait"]: those
        # are only republished by the supervisor thread (10 Hz), which is
        # itself one more thread the GIL hogs below starve - reading them
        # would measure the supervisor's own scheduling luck as much as
        # the rx thread's, not what this test is about. test_state_keys...
        # below checks the state-dict path separately, without hogs.
        e.start()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            e.heartbeat()
            time.sleep(0.02)
        # Under severe starvation the rx thread may not finish even one
        # block in time, so self.cpu/self.cpu_wait (set only once a block
        # completes - _rx_loop) may not exist yet; 0.0 is the honest
        # "nothing measured yet" reading, same as the state registry's own
        # default for both keys.
        return getattr(e, "cpu", 0.0), getattr(e, "cpu_wait", 0.0)

    def test_a_gil_holding_competitor_raises_wait_but_not_cpu(self):
        baseline_engine = self._engine()
        base_cpu, base_wait = self._run_for(baseline_engine, 1.0)
        baseline_engine.stop()  # not just addCleanup's end-of-test stop: a
        # second engine's rx/decode/supervisor threads left running would
        # compete for the GIL right alongside the hogs below and confound
        # exactly what this test measures.

        stop_ev = threading.Event()

        def hog():
            # Pure Python, no I/O or sleep: the only way to yield the GIL is
            # CPython's own switch interval, so this keeps the rx thread
            # waiting for its turn without doing any of its work for it.
            # One is deliberate, not several: this host runs several other
            # sessions already (CLAUDE.md), and two or more of these on top
            # was measured to starve the rx thread completely (it never
            # finished even one block in 2 s, so self.cpu/cpu_wait stayed
            # at their stale pre-hog values - a real effect, but not the
            # "wait rises, cpu does not" one this test demonstrates). One
            # reliably leaves it partially starved instead: measured
            # (10 runs) busy cpu 0.069-0.078 against a baseline of
            # 0.034-0.040, and busy wait 1.15-1.39 against a baseline near
            # zero - a clear, repeatable gap either side of the thresholds
            # below.
            x = 0
            while not stop_ev.is_set():
                x = x + 1 if x < 10_000_000 else 0

        hogs = [threading.Thread(target=hog, daemon=True) for _ in range(1)]
        for t in hogs:
            t.start()
        try:
            busy_cpu, busy_wait = self._run_for(self._engine(), 1.5)
        finally:
            stop_ev.set()
            for t in hogs:
                t.join(timeout=2)

        self.assertGreater(busy_wait, base_wait + 0.1, (base_cpu, base_wait, busy_cpu, busy_wait))
        self.assertLess(busy_cpu, base_cpu + 0.1, (base_cpu, base_wait, busy_cpu, busy_wait))

    def test_cpu_and_cpu_wait_reach_the_state_dict(self):
        e = self._engine()
        e.start()
        deadline = time.monotonic() + 2.0
        s = e.state()
        while time.monotonic() < deadline and "cpuWait" not in s:
            e.heartbeat()
            time.sleep(0.05)
            s = e.state()
        self.assertIn("cpu", s)
        self.assertIn("cpuWait", s)
        self.assertIsInstance(s["cpu"], float)
        self.assertIsInstance(s["cpuWait"], float)


class ForcedSaveIsOnDisk(unittest.TestCase):
    """_save(force=True) means "on disk when this returns" - stop() relies
    on it, and so does anything that reads the config straight after. The
    supervisor saves on its own thread and fsyncs outside the engine's
    lock; a forced save that found nothing left dirty used to return while
    that write was still going, and the file read next was the old one
    (test_playback, red on a loaded nightly run). The supervisor's write is
    made slow here so the overlap happens every time, not one run in fifty."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = Path(self.tmp.name) / "config.json"
        self.e = TinyEngine({"device": "sim", "audioBackend": "null"}, persist=True, conf_path=self.conf,
                            data_dir=self.tmp.name, audio=NullAudio(realtime=False))

    def tearDown(self):
        self.e.stop()
        self.tmp.cleanup()

    def test_waits_for_the_write_another_thread_has_begun(self):
        self.e.set(filterHi=2_650.0)
        self.e._save(force=True)
        real, writing = self.e.CONFIG, threading.Event()

        class SlowConfig:
            def save(self, cfg, path=None):
                writing.set()
                time.sleep(0.5)
                real.save(cfg, path)

        self.e.CONFIG = SlowConfig()
        self.e.set(filterHi=2_600.0)
        supervisor = threading.Thread(target=self.e._save)
        supervisor.start()
        self.addCleanup(supervisor.join)
        self.assertTrue(writing.wait(5))
        self.e._save(force=True)
        self.assertEqual(json.loads(self.conf.read_text())["filterHi"], 2_600.0)


if __name__ == "__main__":
    unittest.main()
