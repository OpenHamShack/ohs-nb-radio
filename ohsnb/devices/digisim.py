"""A Q65 station and two JS8 stations (Normal and Turbo) for the simulated band.

Without them the Q65 and JS8 panels (ohscore/ui/panels/ft8.py, js8.py) could
only be seen with a dish: neither mode is on the simulator's band otherwise,
and an empty list proves nothing about a panel that joins frames into
messages or runs a QSO over a minute. Each station is a scripted exchange,
the same every time, at its mode's usual dial (ohsnb/bandplan.py: Q65-60A at
10489.545, JS8Call at 10489.548), rendered by the modes' own encoders
(ohsdigi), so what the app decodes from them is exactly what it would decode
from the air.

Like the simulator's FT8 (ohscore/devices/simcore.py FT8Activity), each is
rendered a period at a time, one period ahead on a worker thread, and timed
by the simulator's own clock in UTC periods, so the decoders see real slot
timing whether the simulator runs in real time or faster. They take nothing
from the simulator's random generator: a seeded band (simSeed) is the same
band it was before they were added.

Nothing here transmits: the simulator never radiates (Device.radiates), and
these are signals it receives.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from ohscore.devices import simsignals as sg

from .. import bandplan

log = logging.getLogger(__name__)

Q65_DL = next(p["dl"] for p in bandplan.PRESETS if p["mode"] == "q65")
JS8_DL = next(p["dl"] for p in bandplan.PRESETS if p["mode"] == "js8")

# A Q65 QSO, one message per 60 s period, then a pause and round again;
# each (audio offset Hz, level dB relative to the station's, text). The two
# stations take alternate periods, as a real QSO does, and a second CQ in
# some periods gives the list more than one line a minute.
Q65_SCRIPT: tuple[tuple[tuple[float, float, str], ...], ...] = (
    ((1200.0, 0.0, "CQ G4XYZ IO91"), (1750.0, -6.0, "CQ SV1QO KM18")),
    ((1500.0, -3.0, "G4XYZ DL1ABC JO31"),),
    ((1200.0, 0.0, "DL1ABC G4XYZ -12"),),
    ((1500.0, -3.0, "G4XYZ DL1ABC R-09"), (1750.0, -6.0, "CQ SV1QO KM18")),
    ((1200.0, 0.0, "DL1ABC G4XYZ RR73"),),
    ((1500.0, -3.0, "G4XYZ DL1ABC 73"),),
    (),
    ((1750.0, -6.0, "CQ SV1QO KM18"),),
)

# JS8: (period, sender, grid, offset, text) - a heartbeat, a directed
# message long enough to take three frames, its answer, a CQ, another
# heartbeat. A message of n frames goes out over n periods in a row from
# its first.
JS8_SCRIPT: tuple[tuple[int, str, str, float, str], ...] = (
    (0, "G4XYZ", "IO91", 1000.0, "@HB HEARTBEAT IO91"),
    (1, "DL1ABC", "JO31", 1450.0, "G4XYZ HELLO FROM BERLIN TNX FOR THE QSO"),
    (4, "G4XYZ", "IO91", 1000.0, "DL1ABC SNR?"),
    (5, "SV1QO", "KM18", 1800.0, "CQ CQ CQ"),
    (7, "EA4QRP", "IN80", 1250.0, "@HB HEARTBEAT IN80"),
)
JS8_CYCLE = 9                         # periods before the script starts again
# A second JS8 station at Turbo (6 s periods), so the list shows JS8's other
# speeds being received alongside Normal: a CQ and a heartbeat in a
# 10-period (one minute) cycle, on an offset clear of the Normal traffic.
JS8_TURBO_SCRIPT: tuple[tuple[int, str, str, float, str], ...] = (
    (0, "OH8ZZ", "KP24", 2300.0, "CQ CQ CQ"),
    (5, "OH8ZZ", "KP24", 2300.0, "@HB HEARTBEAT KP24"),
)
JS8_TURBO_CYCLE = 10


class SlotActivity:
    """Signals in a UTC-slotted mode, rendered a period at a time.

    `render(k)` gives period k's 12 kHz real audio from the period's start
    (zeros where nothing is sent), or None when nothing is sent at all.
    The simulator feeds it like FT8Activity: take(n, t) with t the
    absolute time in seconds since the epoch."""

    def __init__(self, name: str, dial: float, level_db: float, period: float,
                 render: Callable[[int], np.ndarray | None]):
        self.name, self.dial, self.dl = name, dial, dial
        self.amp = 10 ** (level_db / 20)
        self.period = float(period)
        self.slot_len = int(round(self.period * sg.RATE))
        self._render_audio = render
        self.cur_slot = None
        self.buf = np.zeros(self.slot_len, np.complex64)
        self.src = None
        self.presence = None
        self.lock = threading.Lock()
        self.ready: dict[int, np.ndarray] = {}

    def _render_slot(self, k: int) -> np.ndarray:
        try:
            a = self._render_audio(k)
        except Exception as e:  # noqa: BLE001 - a station that cannot render is silent, not a dead receiver
            log.warning("simulated %s station: %s", self.name, e)
            a = None
        buf = np.zeros(self.slot_len, np.complex64)
        if a is not None and len(a):
            z = sg.analytic(np.asarray(a, np.float32)[:self.slot_len])
            buf[:len(z)] = z
        return buf

    def _prepare(self, k: int):
        def work():
            buf = self._render_slot(k)
            with self.lock:
                self.ready[k] = buf

        threading.Thread(target=work, name=f"sim-{self.name}", daemon=True).start()

    def take(self, n: int, t: float) -> np.ndarray:
        out = np.empty(n, np.complex64)
        i = 0
        while i < n:
            tt = t + i / sg.RATE
            k = int(tt // self.period)
            if k != self.cur_slot:
                self.cur_slot = k
                with self.lock:
                    buf = self.ready.pop(k, None)
                    self.ready = {s: v for s, v in self.ready.items() if s > k}
                self.buf = buf if buf is not None else self._render_slot(k)
                self._prepare(k + 1)
            j = int(round((tt - k * self.period) * sg.RATE)) % self.slot_len
            m = min(n - i, self.slot_len - j)
            out[i:i + m] = self.buf[j:j + m]
            i += m
        return out * self.amp


def _place(period: float, start: float, parts: list[tuple[np.ndarray, float]]) -> np.ndarray | None:
    """Audio pieces (each with its level in dB) mixed into one period,
    `start` seconds in, as the engine starts an over (SLOT_LEAD)."""
    if not parts:
        return None
    n = int(round(period * sg.RATE))
    out = np.zeros(n, np.float32)
    s = int(round(start * sg.RATE))
    for a, db in parts:
        m = min(len(a), n - s)
        out[s:s + m] += a[:m] * np.float32(10 ** (db / 20))
    return out


def q65_station(level_db: float = -68.0) -> SlotActivity | None:
    """The Q65 QSO at 10489.545, or None where Q65 cannot be encoded
    (no ohsdigi and no WSJT-X)."""
    try:
        from ohscore import modes_glue
        from ohscore.engine import SLOT_LEAD
        from ohscore.modes import q65
        enc = modes_glue.encoder("q65")
    except Exception:  # noqa: BLE001 - the simulator runs without ohscore.modes
        return None
    if enc is None:
        return None
    period, start = q65.PERIOD_S, SLOT_LEAD["q65"]

    def render(k: int):
        return _place(period, start, [(enc.render(text=text, offset=off), db)
                                      for off, db, text in Q65_SCRIPT[k % len(Q65_SCRIPT)]])

    return SlotActivity("Q65", Q65_DL, level_db, period, render)


def js8_frames(lb, script=JS8_SCRIPT, cycle=JS8_CYCLE, speed="normal") -> dict[int, list[tuple[float, str, int]]]:
    """A JS8 script as {period in the cycle: [(offset, frame, i3bit)]}."""
    out: dict[int, list] = {}
    for k, call, grid, off, text in script:
        for i, (frame, i3) in enumerate(lb.js8_frames(text, call, grid, submode=speed)):
            out.setdefault((k + i) % cycle, []).append((off, frame, int(i3)))
    return out


def js8_station(level_db: float = -70.0, speed: str = "normal", script=JS8_SCRIPT,
                cycle: int = JS8_CYCLE) -> SlotActivity | None:
    """JS8 traffic at 10489.548 at `speed`, or None without ohsdigi's JS8
    encoder (js8 itself, JS8Call's program, only decodes)."""
    try:
        from ohscore.modes import js8
        lb = js8._OHSDIGI_JS8
    except Exception:  # noqa: BLE001
        return None
    if lb is None or not hasattr(lb, "js8_frames") or not hasattr(lb, "js8_encode_audio"):
        return None
    sub = lb.JS8_SUBMODES[speed]
    frames = js8_frames(lb, script, cycle, speed)

    def render(k: int):
        return _place(sub["period"], sub["start"],
                      [(np.frombuffer(lb.js8_encode_audio(frame, i3, speed, off), "<f4"), 0.0)
                       for off, frame, i3 in frames.get(k % cycle, [])])

    name = "JS8" if speed == "normal" else f"JS8 {speed}"
    return SlotActivity(name, JS8_DL, level_db, sub["period"], render)


def stations() -> list[SlotActivity]:
    """The stations this build can make."""
    return [s for s in (q65_station(), js8_station(),
                        js8_station(-72.0, "turbo", JS8_TURBO_SCRIPT, JS8_TURBO_CYCLE)) if s is not None]
