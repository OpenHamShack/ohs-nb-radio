#!/usr/bin/env python3
"""Key OpenHamShack Radio with a test tone, headless, for a repeatable on-air check.

    python3 tools/tone-test.py --rf 433.550 --drive 0.1 --seconds 10           # dry run: guard verdict only
    python3 tools/tone-test.py --rf 433.550 --drive 0.1 --seconds 10 --key     # transmits
    ... --mode usb | fm      the same tone in another mode, for comparison
    ... --mic                the sound card's microphone instead of the injected tone
                             (play the tone into it; this exercises PortAudio.read_mic,
                             where the 05/10/2026 distortion was)

Written after Ray's 70 cm AM report (strong signal, terrible audio) so the
same test can be run on hardware before and after a change. Everything goes
through the real program: the user's own config (licence class, band-plan
guard, device, sample rate, PTT sequencer) loaded read-only, Radio.ptt(),
and so every guard and timer a key-up from the window passes - the tone
replaces the microphone and nothing else. A refusal is printed and nothing
is sent. Without --key it starts the radio receive-only and reports what the
guard would say. Ctrl-C unkeys.

Never run with --key without Brian, a licensed operator and a dummy load or
an antenna the test is meant for (HANDOVER: "Never key real hardware").
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohscore.audio import RATE, NullAudio  # noqa: E402
from ohsradio import config  # noqa: E402
from ohsradio.radio import Radio  # noqa: E402


def tone_source(freq: float, level: float):
    """A continuous-phase sine as the microphone, in the engine's blocks."""
    pos = {"n": 0}

    def source(n: int) -> np.ndarray:
        t = (pos["n"] + np.arange(n)) / RATE
        pos["n"] += n
        return (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return source


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rf", type=float, required=True, help="dial frequency, MHz")
    ap.add_argument("--drive", type=float, required=True, help="drive, 0..1 (the window's Drive control)")
    ap.add_argument("--seconds", type=float, required=True, help="how long to stay keyed")
    ap.add_argument("--mode", default="am", choices=["am", "usb", "lsb", "fm"])
    ap.add_argument("--tone", type=float, default=1000.0, help="tone, Hz (default 1000)")
    ap.add_argument("--level", type=float, default=0.5, help="tone level at the mic input, 0..1 (default 0.5)")
    ap.add_argument("--device", choices=["sim", "pluto", "hl2", "soapy"], help="override the configured device")
    ap.add_argument("--mic", action="store_true", help="use the sound card's microphone, not the injected tone")
    ap.add_argument("--key", action="store_true", help="actually transmit (without it: guard verdict only)")
    a = ap.parse_args(argv)

    notes: list[str] = []
    cfg = config.load(notes=notes)
    for n in notes:
        print("config:", n)
    if a.device:
        cfg["device"] = a.device
    audio = None if a.mic else NullAudio(realtime=True, source=tone_source(a.tone, a.level))
    # persist=False: a test run must not rewrite the operator's settings.
    radio = Radio(cfg, persist=False, audio=audio)
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("now", True))
    toasts = radio.subscribe("toast", 64)

    def drain():
        for it in toasts.drain():
            print(f"[{it['level']}] {it['text']}", flush=True)

    rc = 0
    try:
        radio.set(vfo=a.rf * 1e6, mode=a.mode, drive=a.drive)
        radio.start()
        t_end = time.monotonic() + 2.0                  # let receive and the guard settle
        while time.monotonic() < t_end and not stop["now"]:
            radio.heartbeat()
            time.sleep(0.05)
        s = radio.state()
        info = s.get("licenceInfo") or {}
        print(f"device {cfg.get('device')} fs {s.get('fs')} | {s['mode'].upper()} {s['vfo'] / 1e6:.6f} MHz "
              f"drive {s['drive']:.3f} | licence {info.get('class') or 'unset'} | "
              f"guard: {s.get('txBlocked') or 'clear'}", flush=True)
        drain()
        if not a.key:
            print("dry run: not keyed (add --key to transmit)")
            return 0
        radio.ptt(True)
        t0 = time.monotonic()
        next_line = t0 + 1.0
        while not stop["now"] and time.monotonic() - t0 < a.seconds:
            radio.heartbeat()
            drain()
            if not radio.state()["keyed"]:
                print("unkeyed by the program (see above)")
                rc = 1
                break
            if time.monotonic() >= next_line:
                next_line += 1.0
                st = radio.state()
                print(f"  keyed {st.get('txSeconds', 0):5.1f} s  modulator peak {radio.tx_peak:.3f}  "
                      f"mic {radio.mic_level:6.1f} dBFS  est PEP {st.get('estPep', 0)}", flush=True)
            time.sleep(0.05)
    except ValueError as e:                             # TxRefused is a ValueError
        print(f"refused: {e}", file=sys.stderr)
        rc = 1
    finally:
        try:
            radio.ptt(False)
            t_end = time.monotonic() + 3.0
            while radio.state()["keyed"] and time.monotonic() < t_end:
                radio.heartbeat()
                time.sleep(0.05)
        finally:
            radio.stop()
        drain()
    print("unkeyed, stopped")
    return rc


if __name__ == "__main__":
    sys.exit(main())
