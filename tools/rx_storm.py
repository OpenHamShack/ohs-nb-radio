"""Does anything the window does disturb receive? A scripted "UI storm"
against the real NB window, with a receiver that keeps time like a Pluto.

    QT_QPA_PLATFORM=offscreen python3 tools/rx_storm.py [--script storm|idle|psk] [--json out.json]

Why this exists: on 17/10/2026 NB on an M4 Mac mini (Pluto over Tailscale,
1.2 MS/s) counted a receive overrun for each window resize, theme toggle and
dialog opened, and PSK63/PSK125 brought bursts of audio underruns
(~/build/mac-nb-test/FINDINGS.md, 10, 23, 29). Neither shows in the test
suite, whose simulator runs faster than real time and whose audio is the
null backend, so nothing there has a deadline to miss. Here both do:

- **The device** is the NB simulator's own signal, generated once and
  looped, delivered as a Pluto's DMA does: samples arrive at the sample
  rate whether or not anybody reads them, into a fixed number of kernel
  buffers (four of one block, pluto.py's set_kernel_buffers_count); a
  reader that comes back later than they hold loses the difference, which
  is counted (`lost_s`). Modelled from wall time, not with a producer
  thread, because a producer thread would need the GIL and the hardware
  does not.
- **The sound card** is ohscore.audio.PortAudio itself over a stand-in
  pyaudio whose output callback is called every 20 ms from its own thread,
  as PortAudio calls it, so its underruns are the backend's real ones.
- **A canary thread** sleeps 1 ms at a time and records how late it
  wakes: the longest time some other thread held the GIL (`gil_ms`). Under
  PyQt6 a long Qt call (a stylesheet, a layout, scaling an image) holds the
  GIL for its whole length (measured 17/10: QApplication.setStyleSheet over
  1500 widgets froze every other thread for 145 ms), so this is the number
  that says whether the window could have stopped receive.

Each action runs, then the harness waits `--settle` seconds; the report
gives, per action, the worst GIL hold, the engine's late blocks, samples
lost at the device, audio underruns and what the engine itself counted.
tests/test_rx_undisturbed.py runs a short storm and asserts nothing is lost.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ------------------------------------------------------------------ the device
def paced_device(kernel_buffers: int = 4, loop_s: float = 4.0, prefetch: bool = True):
    """A SimDevice subclass that plays `loop_s` of its own signal round and
    round, paced and buffered like a Pluto (module docstring)."""
    from ohsnb.devices.sim import SimDevice

    class PacedSim(SimDevice):
        rx_prefetch = prefetch      # as a Pluto is read (Device.rx_prefetch), unless --no-prefetch

        def open(self):
            super().open()
            self.realtime = False
            n = int(loop_s * self.fs) // self.geo.L * self.geo.L
            parts, got = [], 0
            while got < n:
                part = super().read(min(8 * self.geo.L, n - got))
                parts.append(part)
                got += len(part)
            self.loop = np.concatenate(parts)
            self.pos = 0
            self.t0 = None
            self.taken = 0              # samples handed to read()
            self.lost = 0               # samples the "DMA" overwrote before anyone read them
            self.loss_events = 0
            self.cap_n = None

        def stall(self, seconds: float) -> None:
            """The link to the radio stops delivering for `seconds` (a
            network hiccup): the next read waits that long, and what the
            kernel buffers cannot hold meanwhile is lost upstream."""
            self.stall_s = float(seconds)

        def read(self, n: int) -> np.ndarray:
            if self.cap_n is None:
                self.cap_n = kernel_buffers * n
            if getattr(self, "stall_s", 0.0):
                s, self.stall_s = self.stall_s, 0.0
                time.sleep(s)
            now = time.monotonic()
            if self.t0 is None:
                self.t0 = now - n / self.fs
            produced = int((now - self.t0) * self.fs)
            backlog = produced - self.taken - self.lost
            if backlog > self.cap_n:
                # The kernel's buffers were full: what arrived after that is gone.
                self.lost += backlog - self.cap_n
                self.loss_events += 1
            due = self.t0 + (self.taken + self.lost + n) / self.fs
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            idx = (self.pos + np.arange(n)) % len(self.loop)
            self.pos = (self.pos + n) % len(self.loop)
            self.taken += n
            self.n += n
            return self.loop[idx]

    return PacedSim


# ------------------------------------------------------------------ the sound card
def fake_pyaudio(period_s: float = 0.02):
    """A pyaudio stand-in: one output stream whose callback runs every
    `period_s` on its own thread, as PortAudio's does."""
    mod = types.ModuleType("pyaudio")
    mod.paFloat32, mod.paContinue = 1, 0

    class Stream:
        def __init__(self, cb, rate, frames):
            self.cb, self.rate, self.frames = cb, rate, frames
            self.stop_ev = threading.Event()
            self.thread = None

        def start_stream(self):
            def run():
                t = time.monotonic()
                while not self.stop_ev.is_set():
                    t += self.frames / self.rate
                    d = t - time.monotonic()
                    if d > 0:
                        time.sleep(d)
                    if self.cb is not None:
                        self.cb(None, self.frames, None, 0)
            self.thread = threading.Thread(target=run, name="fake-portaudio", daemon=True)
            self.thread.start()

        def stop_stream(self):
            self.stop_ev.set()

        def close(self):
            self.stop_ev.set()

    class PyAudio:
        def get_device_count(self):
            return 0

        def is_format_supported(self, *a, **k):
            return True

        def get_default_output_device_info(self):
            return {"index": 0, "defaultSampleRate": 48000}

        def open(self, rate, frames_per_buffer, stream_callback=None, **_k):
            return Stream(stream_callback, rate, frames_per_buffer)

        def terminate(self):
            pass

    mod.PyAudio = PyAudio
    return mod


# ------------------------------------------------------------------ the canary
class Canary:
    """Sleeps 1 ms at a time; how late it wakes is how long it could not
    get the GIL (module docstring)."""

    def __init__(self):
        self.worst = 0.0
        self.stop_ev = threading.Event()
        self.thread = threading.Thread(target=self._run, name="gil-canary", daemon=True)

    def _run(self):
        last = time.perf_counter()
        while not self.stop_ev.is_set():
            time.sleep(0.001)
            now = time.perf_counter()
            self.worst = max(self.worst, now - last - 0.001)
            last = now

    def take(self) -> float:
        w, self.worst = self.worst, 0.0
        return w


def rss_mb() -> int:
    """Resident memory now (Linux), or -1."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 2**20
    except (OSError, ValueError):
        return -1


# ------------------------------------------------------------------ scripts
def _close_modals(app, after_ms=400):
    from PyQt6.QtCore import QTimer

    def close():
        w = app.activeModalWidget()
        if w is not None:
            w.reject()
    QTimer.singleShot(after_ms, close)


def actions(win, app, script: str):
    """[(label, callable)] for `script`."""
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    if script == "idle":
        return [("idle", lambda: None)] * 6
    if script == "sweep":
        # The Mac test's mode sweep (FINDINGS 21-30), each mode left running a while.
        modes = ("ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv",
                 "hsmodem", "cw", "am", "usb")
        return [(f"mode {m}", lambda m=m: win.set_mode(m)) for m in modes]
    if script == "psk":
        out = []
        for m in ("usb", "psk31", "psk63", "psk125", "rtty", "ft8"):
            out.append((f"mode {m}", lambda m=m: win.set_mode(m)))
            out.append((f"{m} running", lambda: None))
        return out

    def resize(w, h):
        return lambda: win.resize(w, h)

    def theme():
        return lambda: win.set_theme("light" if win.prefs["theme"] == "dark" else "dark")

    def dish():
        def go():
            d = win.open_dish()
            app.processEvents()
            if d is not None:
                d.close()
        return go

    def welcome():
        def go():
            _close_modals(app)
            win.open_welcome()
        return go

    def settings():
        def go():
            _close_modals(app)
            win.open_settings()
        return go

    return [
        ("resize 1000x640", resize(1000, 640)),
        ("resize 1600x960", resize(1600, 960)),
        ("theme toggle", theme()),
        ("theme toggle back", theme()),
        ("dish alignment", dish()),
        ("welcome", welcome()),
        ("settings", settings()),
        ("tab log", lambda: win.show_view("log")),
        ("tab memories", lambda: win.show_view("mem")),
        ("tab band", lambda: win.show_view("skim")),
        ("tab beacon", lambda: win.show_view("mmb")),
        ("tab mode", lambda: win.show_view("mode")),
        ("mode ft8", lambda: win.set_mode("ft8")),
        ("mode cw", lambda: win.set_mode("cw")),
        ("mode usb", lambda: win.set_mode("usb")),
    ]


# ------------------------------------------------------------------ run
def run(script="storm", settle=2.0, warm=6.0, size=(1600, 960), kernel_buffers=4, record=False,
        vfo=10_489_700_000.0, prefetch=True, log=print) -> dict:
    tmp = tempfile.mkdtemp(prefix="rx-storm-")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["OHS_NB_UI_CONF"] = str(Path(tmp) / "ui.json")
    sys.modules.setdefault("pyaudio", fake_pyaudio())

    from ohscore.audio import PortAudio
    from ohscore.ui.prefs import Prefs
    from ohsnb import config, state
    from ohsnb.radio import Radio
    from ohsnb.ui import build, make_app

    app = make_app(["rx-storm"])
    cfg = state.defaults(("setting", "control"))
    cfg.update(device="sim", simSeed=5, vfo=vfo, mode="usb")
    dev_cls = paced_device(kernel_buffers, prefetch=prefetch)
    audio = PortAudio()
    radio = Radio(cfg, persist=False, data_dir=Path(tmp), audio=audio, device=dev_cls(dict(cfg)))
    prefs = Prefs(config.CONFIG)
    prefs["welcomed"] = True
    prefs["licenceAck"] = True
    win, bridge = build(radio, prefs)
    win.resize(*size)
    win.show()

    late = [0]
    orig_block = radio._rx_block
    block_s = radio.BLOCK_HOPS * radio.geo.L / radio.geo.fs

    def timed_block(x):
        t0 = time.perf_counter()
        orig_block(x)
        if time.perf_counter() - t0 > block_s:
            late[0] += 1
    radio._rx_block = timed_block

    canary = Canary()
    canary.thread.start()

    def pump(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.002)

    pump(warm)
    if record:
        radio.start_recording(folder=Path(tmp) / "rec")
    dev = radio.dev
    rows = []

    def snap():
        return dict(lost=dev.lost, late=late[0], under=audio.underruns, over=radio.overruns)

    canary.take()
    for label, fn in actions(win, app, script):
        a = snap()
        t0 = time.perf_counter()
        fn()
        app.processEvents()
        took = time.perf_counter() - t0
        pump(settle)
        b = snap()
        row = dict(action=label, took_ms=round(took * 1000), gil_ms=round(canary.take() * 1000, 1),
                   late=b["late"] - a["late"], lost_s=round((b["lost"] - a["lost"]) / dev.fs, 3),
                   underruns=b["under"] - a["under"], overruns=b["over"] - a["over"], rss_mb=rss_mb())
        rows.append(row)
        log(f"{label:22s} took {row['took_ms']:5d} ms  GIL {row['gil_ms']:6.1f} ms  late {row['late']:2d}  "
            f"lost {row['lost_s']:.3f} s  underruns {row['underruns']:3d}  overruns {row['overruns']:2d}  "
            f"RSS {row['rss_mb']} MB")
    rec = None
    if record:
        rec = radio.rec
        radio.stop_recording()
    canary.stop_ev.set()
    total = {k: sum(r[k] for r in rows) for k in ("late", "underruns", "overruns")}
    total["lost_s"] = round(sum(r["lost_s"] for r in rows), 3)
    total["gil_ms"] = max(r["gil_ms"] for r in rows)
    out = {"script": script, "kernel_buffers": kernel_buffers, "rows": rows, "total": total,
           "recording": None if rec is None else {"dropped": rec.dropped}}
    win.close()
    bridge.stop()
    app.processEvents()
    shutil.rmtree(tmp, ignore_errors=True)       # a --record run leaves gigabytes otherwise
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--script", default="storm", choices=("storm", "idle", "psk", "sweep"))
    p.add_argument("--settle", type=float, default=2.0)
    p.add_argument("--kernel-buffers", type=int, default=4)
    p.add_argument("--record", action="store_true", help="record IQ while the script runs")
    p.add_argument("--switch-ms", type=float, help="sys.setswitchinterval for the run, ms (Python's default is 5)")
    p.add_argument("--vfo", type=float, default=10_489_700_000.0, help="dial, Hz (the FT8 channel is 10489540000)")
    p.add_argument("--no-prefetch", action="store_true", help="read the device on the receive thread, as before 17/10/2026")
    p.add_argument("--json")
    a = p.parse_args(argv)
    if a.switch_ms:
        sys.setswitchinterval(a.switch_ms / 1000)
    out = run(a.script, settle=a.settle, kernel_buffers=a.kernel_buffers, record=a.record, vfo=a.vfo, prefetch=not a.no_prefetch)
    print("total:", json.dumps(out["total"]))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
