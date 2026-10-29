"""APRS on the simulated air: a handful of fictional stations around Ayr on
144.800 MHz, near the station's own locator (IO75RL), so Radio's APRS map
can be built and tested with no radio (29/10/2026).

Each packet is a real one: an AX.25 UI frame from shack_packet's codec,
keyed as Bell 202 AFSK by its own modulator (shack_packet.afsk, the one
every OpenHamShack app transmits with) and FM-modulated at +-3 kHz, the
deviation a 2 m packet radio uses, at the simulator's own rate. Radio's
APRS session then demodulates it exactly as it would a station on the air:
its channel cut from the receiver's IQ, discriminated and decoded by
shack_packet's receiver. Nothing here is a shortcut past the demodulator.

The stations, all fictional (the "SIM" suffix, as the simulator's GB3SIM
repeaters; no such calls are issued):

- **MB7SIM**, a digipeater on high ground east of Ayr.
- **GM0SIM**, a home station in Ayr: a position, a status line, a message
  to the station's own call, and an object (the Ayr show's talk-in).
- **GM0SIM-9**, a car on the A77 between Ayr and Prestwick, sending Mic-E
  as most trackers do; every other one of its packets arrives through
  MB7SIM, as a mobile's would from a dip in the road.
- **GM1SIM-7**, a walker on the shore with a handheld, plain positions
  with course and speed.
- **GM2SIM-13**, a weather station at Prestwick.

One packet a second, round the stations in turn (a real channel carries
far fewer: a fixed station every 10-30 minutes, a car every minute or
two), so a map fills in seconds; never two at once, because two packets
on one FM channel at once is a collision and neither decodes. Movement
follows the simulator's clock, so a test that runs faster than real time
moves the stations as fast.

A test puts its own frames on the air with `AprsAir(beacons=...)`, each a
monitor line (`CALL>DEST,PATH:info`), so published examples go through the
same modulator and demodulator as the simulator's own.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

APRS_HZ = 144_800_000.0
HALF_SPAN = 12_500.0
AUDIO_RATE = 48_000
DEVIATION_HZ = 3_000.0
SLOT_S = 1.0
STATION = (55.4792, -4.5417)        # IO75RL's centre


def available() -> bool:
    """Whether this installation has shack_packet (its vendored wheel)."""
    from ohscore import shacklibs
    try:
        shacklibs.packet()
    except ImportError:
        return False
    return True


@dataclass
class Beacon:
    """One station's packet: `line(t)` is its monitor line at simulator time
    `t` (seconds), so a moving station says where it is now."""
    line: Callable[[float], str]


def fixed(line: str) -> Beacon:
    return Beacon(lambda _t: line)


def _mic_e(call: str, path: str, lat: float, lon: float, knots: float, course: float, symbol: str,
           comment: str = "") -> str:
    """A Mic-E position (APRS 1.0.1 ch. 10), message "en route", as the
    simulator's car sends it. Only for the simulator: the receive side is
    shack_packet.aprs's parser, and the tests check the two agree."""
    la = abs(lat)
    deg, mins = int(la), (la - int(la)) * 60.0
    digits = f"{deg:02d}{int(mins):02d}{int(round((mins - int(mins)) * 100)) % 100:02d}"
    lo = abs(lon)
    ldeg = int(lo)
    lmin = (lo - ldeg) * 60.0
    lhun = int(round((lmin - int(lmin)) * 100)) % 100
    lmin = int(lmin)
    offset = ldeg < 10 or ldeg >= 100
    # A, B, C (the message: 1 1 0 is "en route"), then north, offset, west.
    flags = (True, True, False, lat >= 0, offset, lon < 0)
    dest = "".join(chr((ord("P") if f else ord("0")) + int(d)) for d, f in zip(digits, flags))
    if ldeg < 10:
        d = ldeg + 118
    elif ldeg < 100:
        d = ldeg + 28
    elif ldeg < 110:
        d = ldeg + 8
    else:
        d = ldeg - 72
    m = lmin + 88 if lmin < 10 else lmin + 28
    sp, c = int(round(knots)), int(round(course)) % 360
    info = bytes([0x60, d, m, lhun + 28, sp // 10 + 28, (sp % 10) * 10 + c // 100 + 28, c % 100 + 28,
                  ord(symbol[1]), ord(symbol[0])]).decode("latin-1")
    return f"{call}>{dest}{',' + path if path else ''}:{info}{comment}"


def _along(a, b, knots: float, t: float) -> tuple[float, float, float, float]:
    """(lat, lon, knots, course) to and fro between `a` and `b` at time `t`."""
    km = math.dist((a[0] * 111.32, a[1] * 63.0), (b[0] * 111.32, b[1] * 63.0))
    leg = km * 1000.0 / (knots * 1852.0 / 3600.0)
    u = (t % (2 * leg)) / leg
    frm, to = (a, b) if u < 1 else (b, a)
    f = u if u < 1 else u - 1
    lat, lon = frm[0] + (to[0] - frm[0]) * f, frm[1] + (to[1] - frm[1]) * f
    course = (math.degrees(math.atan2((to[1] - frm[1]) * math.cos(math.radians(lat)), to[0] - frm[0])) + 360) % 360
    return lat, lon, knots, course


def default_beacons() -> list[Beacon]:
    from ohscore import shacklibs
    aprs = shacklibs.packet().aprs
    car_a, car_b = (55.4600, -4.6150), (55.5050, -4.6050)          # Ayr to Prestwick, on the A77
    walk_a, walk_b = (55.4700, -4.6400), (55.4550, -4.6450)        # Ayr's shore
    n = {"car": 0}

    def car(t):
        lat, lon, kn, c = _along(car_a, car_b, 30.0, t)
        n["car"] += 1
        path = "MB7SIM*,WIDE2-1" if n["car"] % 2 == 0 else "WIDE1-1,WIDE2-1"
        return _mic_e("GM0SIM-9", path, lat, lon, kn, c, "/>", "]On the A77")

    def walker(t):
        lat, lon, kn, c = _along(walk_a, walk_b, 3.0, t)
        return "GM1SIM-7>APZOHS,WIDE1-1:" + aprs.format_position(lat, lon, "/[", "Walking the front",
                                                                   course_deg=c, speed_kmh=kn * 1.852)

    return [
        fixed("MB7SIM>APZOHS:" + aprs.format_position(55.4400, -4.5200, "/#", "Ayr digipeater (simulated)",
                                                     messaging=False)),
        Beacon(car),
        fixed("GM0SIM>APZOHS,WIDE1-1:" + aprs.format_position(55.4630, -4.6290, "/-", "Home in Ayr")),
        Beacon(walker),
        fixed("GM2SIM-13>APZOHS,WIDE1-1:" + aprs.format_weather(
            55.5090, -4.5940, {"wind_dir_deg": 230, "wind_kmh": 24.0, "gust_kmh": 40.0, "temp_c": 11.0,
                               "rain_hour_mm": 0.5, "humidity_pct": 82, "pressure_hpa": 1004.2}, "Prestwick WX")),
        fixed("GM0SIM>APZOHS,WIDE1-1:" + aprs.format_status("Listening on 144.800 in Ayr")),
        Beacon(car),
        fixed("GM0SIM>APZOHS,WIDE1-1:" + aprs.format_object("AYRSHOW", 55.4560, -4.6180, "/E",
                                                            "Talk-in on 145.500", when=1793232000.0)),
        Beacon(walker),
        fixed("GM0SIM>APZOHS,WIDE1-1:" + aprs.format_message("GM4BRI", "See you at the show", "7")),
    ]


class AprsAir:
    """144.800 as a simulator hears it (module docstring): `take` gives what
    falls in samples k..k+n at a receiver centred on `rx_if`; `iq(t, rx_if)`
    the same for a simulator that counts time. `level_db` is every packet's
    carrier, dBFS: FM is captured or not, so one strong level serves."""

    def __init__(self, beacons=None, level_db: float = -40.0, t0: float = 0.0, slot_s: float = SLOT_S):
        self.beacons = default_beacons() if beacons is None else [b if isinstance(b, Beacon) else fixed(b)
                                                                  for b in beacons]
        self.level_db = float(level_db)
        self.t0 = float(t0)
        self.slot_s = float(slot_s)
        self.lock = threading.Lock()
        self.pending: list[tuple[int, np.ndarray]] = []
        self.done_to = 0.0
        self.sent: list[str] = []            # every line put on the air, for a test

    def in_view(self, rx_if: float, fs: float) -> bool:
        return abs(APRS_HZ - rx_if) + HALF_SPAN < fs / 2

    def _burst(self, line: str, fs: float, offset_hz: float) -> np.ndarray:
        from ohscore import shacklibs
        sp = shacklibs.packet()
        frame = sp.ax25.Frame.from_monitor(line).encode()
        audio = sp.afsk.modulate([frame], AUDIO_RATE, amplitude=1.0, txdelay_ms=150.0, tail_ms=20.0)
        n = int(len(audio) * fs / AUDIO_RATE)
        a = np.interp(np.arange(n) * (AUDIO_RATE / fs), np.arange(len(audio)), audio)
        phase = 2 * np.pi * np.cumsum(offset_hz + DEVIATION_HZ * a) / fs
        return (10 ** (self.level_db / 20) * np.exp(1j * phase)).astype(np.complex64)

    def take(self, k: int, n: int, fs: float, rx_if: float) -> np.ndarray | None:
        if not self.in_view(rx_if, fs) or not self.beacons:
            self.pending.clear()
            self.done_to = (k + n) / fs
            return None
        y = np.zeros(n, np.complex64)
        t_lo, t_hi = k / fs, (k + n) / fs
        with self.lock:
            lo = max(self.done_to, t_lo)
            j = math.ceil(lo / self.slot_s)
            while j * self.slot_s < t_hi:
                line = self.beacons[j % len(self.beacons)].line(self.t0 + j * self.slot_s)
                self.sent.append(line)
                self.pending.append((int(round(j * self.slot_s * fs)), self._burst(line, fs, APRS_HZ - rx_if)))
                j += 1
            self.done_to = max(self.done_to, t_hi)
            keep = []
            for start, z in self.pending:
                a, b = max(start, k), min(start + len(z), k + n)
                if a < b:
                    y[a - k:b - k] += z[a - start:b - start]
                if start + len(z) > k + n:
                    keep.append((start, z))
            self.pending = keep
        return y

    def iq(self, t: np.ndarray, rx_if: float) -> np.ndarray:
        fs = 1.0 / float(t[1] - t[0]) if len(t) > 1 else 2_400_000.0
        z = self.take(int(round(float(t[0]) * fs)), len(t), fs, rx_if)
        return np.zeros(len(t), np.complex64) if z is None else z
