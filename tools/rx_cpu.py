"""What Radio's receive costs, per mode: the engine's receive thread's own
CPU time per second of signal, on the band simulator.

    python3 tools/rx_cpu.py [--fs 2400000] [--seconds 20] [--repeat 3] usb fm wfm

Written for the 48 kHz audio change (23/10/2026), which had to say what it
cost on an i5-9400T before and after. It times `Engine._rx_block` alone
with `time.thread_time()`, the same clock the engine's own `cpu` status
uses, so the simulator generating the band (in `_rx_read`, outside the
block) is not counted and other sessions' load on a shared host costs
wall time but not this figure. The simulator runs faster than real time,
so a 20 s measurement takes a few seconds. The null sound card: the
engine does everything up to handing the audio to a backend, which is
where the desktop's PortAudio (a copy into a ring when the card runs at
the engine's audio rate) and the store's PCM conversion take over.

Each mode is measured `--repeat` times and the lowest kept: interference
from other processes only ever adds.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Where each mode is listened to: a busy amateur band for the voice modes,
# Band II for wide FM (the simulator covers 100 kHz-6 GHz; Band II is noise
# there, which costs the demodulator the same as a station).
DIALS = {"usb": 14_200_000.0, "lsb": 7_100_000.0, "cw": 14_030_000.0, "am": 7_150_000.0,
         "fm": 145_500_000.0, "wfm": 97_700_000.0}


def measure(mode: str, fs: float, seconds: float) -> float:
    """Percent of one core the receive thread spent per second of signal."""
    from ohscore.audio import NullAudio
    from ohsradio.radio import Radio
    tmp = tempfile.TemporaryDirectory()
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "callsign": "GM4BRI", "licenceClass": "full", "sampleRate": int(fs)}
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=NullAudio(realtime=False))
    acc = {"cpu": 0.0, "n": 0, "on": False}
    inner = r._rx_block

    def timed(x):
        c0 = time.thread_time()
        inner(x)
        if acc["on"]:
            acc["cpu"] += time.thread_time() - c0
            acc["n"] += len(x)
    r._rx_block = timed
    try:
        r.start()
        r.set(mode=mode, vfo=DIALS[mode])
        # Two seconds of signal first: numpy plans its FFTs and the dial's
        # re-centring settles.
        t_end = time.monotonic() + 60
        while r.rx_samples < 2 * fs and time.monotonic() < t_end:
            r.heartbeat()
            time.sleep(0.01)
        acc["on"] = True
        while acc["n"] < seconds * fs and time.monotonic() < t_end:
            r.heartbeat()
            time.sleep(0.01)
    finally:
        r.stop()
        tmp.cleanup()
    return 100.0 * acc["cpu"] / (acc["n"] / fs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("modes", nargs="*", default=["usb", "fm", "wfm"])
    ap.add_argument("--fs", type=float, default=2_400_000.0)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--repeat", type=int, default=3)
    a = ap.parse_args()
    for mode in a.modes:
        runs = [measure(mode, a.fs, a.seconds) for _ in range(a.repeat)]
        print(f"{mode:4} {a.fs / 1e6:.1f} MS/s  {min(runs):5.2f} % of a core  "
              f"(runs: {', '.join(f'{x:.2f}' for x in runs)})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
