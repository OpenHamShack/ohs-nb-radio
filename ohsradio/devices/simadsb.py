"""Aircraft on the simulated air: Mode S squitters from a handful of
aircraft around Glasgow Prestwick (EGPK), near the station's own locator
(IO75RL, by Ayr), so the aircraft map can be built and tested with no radio
(Brian, 28/10/2026).

Every reply is a real one: the message is written by shack_sdr's ADS-B
writer (`_native.adsb_encode`) and keyed by its test transmitter
(`_native.testsig_adsb`: preamble, pulse-position bits) at the simulator's
own rate, 1090 MHz wherever it falls from the receiver's centre, so Radio's
ADS-B session decodes it exactly as it would an aircraft - and must earn
each one as it would (a confirmed address, a position pair seen twice).
The aircraft are fictional: addresses F000xx, an unallocated block, and
callsigns SIM...:

- **SIM101**, a large jet on final approach to Prestwick's runway 30 from
  over Troon's coast, 3000 ft down to 600 ft, 150 kn.
- **SIM202**, a heavy overflying Ayrshire westbound at 37000 ft, 460 kn.
- **SIM303**, a light aircraft in the circuit north of the airfield,
  1500 ft, 90 kn.
- **SIM404**, a jet out of Glasgow (EGPF) climbing south-west, 4000 to
  14000 ft, 280 kn.
- **SIM505**, a helicopter over the Firth of Clyde at 800 ft, 110 kn.
- **SIM606**, an aircraft taxiing on Prestwick's apron (surface
  positions) at 12 kn.

Each sends positions twice a second (even and odd in turn), its velocity
twice a second, its identification every five seconds and an all-call
squitter every second, as DO-260B has them; the operational status every
ten. A level is set by distance: -20 dBFS for one 20 km away, at most -10
dBFS, which over the simulator's floor (-112 dBFS/Hz: -44 dBFS a sample
at 6 MS/s) is 24 dB at 20 km and 15 dB for the farthest, 55 km out. At
-40 dBFS, the AIS fleet's level, the aircraft past 30 km were under the
noise at 6 MS/s.
Movement follows the simulator's clock, as the ships' does.
"""
from __future__ import annotations

import math
import threading

import numpy as np

CENTRE_HZ = 1_090_000_000.0
HALF_SPAN = 1_000_000.0
STATION = (55.4792, -4.5417)        # IO75RL's centre
REPLY_S = 0.000125                  # the longest reply, with a little room


class Aircraft:
    """One aircraft, to and fro between `a` and `b` (lat, lon) at `knots`,
    its altitude going from `alt_a` to `alt_b` along the way (feet)."""

    def __init__(self, icao: int, callsign: str, a, b, knots: float, alt_a: int, alt_b: int | None = None,
                 tc: int = 4, ca: int = 3, surface: bool = False, phase_s: float = 0.0):
        self.icao, self.callsign, self.a, self.b = icao, callsign, a, b
        self.knots, self.alt_a, self.alt_b = knots, alt_a, alt_a if alt_b is None else alt_b
        self.tc, self.ca, self.surface, self.phase_s = tc, ca, surface, phase_s
        km = math.dist((a[0] * 111.32, a[1] * 111.32 * math.cos(math.radians(a[0]))),
                       (b[0] * 111.32, b[1] * 111.32 * math.cos(math.radians(a[0]))))
        self.leg_s = km * 1000.0 / (knots * 1852.0 / 3600.0)

    def where(self, t: float):
        """(lat, lon, altitude ft, knots, track degrees, vertical rate ft/min) at `t`."""
        u = (t % (2 * self.leg_s)) / self.leg_s
        frm, to, alt0, alt1 = (self.a, self.b, self.alt_a, self.alt_b) if u < 1 else \
            (self.b, self.a, self.alt_b, self.alt_a)
        f = u if u < 1 else u - 1
        lat = frm[0] + (to[0] - frm[0]) * f
        lon = frm[1] + (to[1] - frm[1]) * f
        dy = to[0] - frm[0]
        dx = (to[1] - frm[1]) * math.cos(math.radians(lat))
        track = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
        alt = alt0 + (alt1 - alt0) * f
        vrate = (alt1 - alt0) / (self.leg_s / 60.0)
        return lat, lon, alt, self.knots, track, vrate

    def message(self, t: float, k: int) -> dict:
        """The `k`-th of its squitters, every 0.25 s from its phase."""
        lat, lon, alt, kn, track, vrate = self.where(t)
        e = kn * math.sin(math.radians(track))
        n = kn * math.cos(math.radians(track))
        slot = k % 4
        if slot in (0, 2):
            odd = slot == 2
            if self.surface:
                return {"kind": "surface", "icao": self.icao, "speed_kn": kn, "track": track, "odd": odd,
                        "lat": lat, "lon": lon}
            return {"kind": "airborne", "icao": self.icao, "alt_ft": int(round(alt / 25.0) * 25), "odd": odd,
                    "lat": lat, "lon": lon}
        if slot == 1:
            if self.surface:
                return {"kind": "allcall", "icao": self.icao, "ca": 4}
            return {"kind": "velocity", "icao": self.icao, "east_kn": e, "north_kn": n,
                    "vrate_fpm": int(round(vrate / 64.0) * 64), "baro": True, "geo_minus_baro_ft": 175}
        if k % 20 == 3:
            return {"kind": "ident", "icao": self.icao, "tc": self.tc, "ca": self.ca, "callsign": self.callsign}
        if k % 40 == 7:
            return {"kind": "opstatus", "icao": self.icao, "version": 2, "surface": self.surface}
        return {"kind": "allcall", "icao": self.icao, "ca": 4 if self.surface else 5}


EGPK = (55.5094, -4.5867)

FLEET = [
    Aircraft(0xF00101, "SIM101", (55.455, -4.475), (55.503, -4.570), 150.0, 3000, 600, phase_s=0.03),
    Aircraft(0xF00202, "SIM202", (55.40, -3.90), (55.65, -5.40), 460.0, 37000, ca=5, phase_s=0.11),
    Aircraft(0xF00303, "SIM303", (55.535, -4.640), (55.560, -4.540), 90.0, 1500, ca=1, phase_s=0.17),
    Aircraft(0xF00404, "SIM404", (55.86, -4.43), (55.60, -4.95), 280.0, 4000, 14000, phase_s=0.07),
    Aircraft(0xF00505, "SIM505", (55.62, -4.92), (55.78, -4.92), 110.0, 800, ca=7, phase_s=0.21),
    Aircraft(0xF00606, "SIM606", (55.5085, -4.5830), (55.5102, -4.5885), 12.0, 0, tc=4, ca=3, surface=True,
             phase_s=0.13),
]


class AdsbAir:
    """The fleet as a simulator hears it: `take` gives the replies that fall
    in samples k..k+n at a receiver centred on `rx_if` (as simais.AisFleet).
    `level_db` is a reply's pulse power 20 km from the station, dBFS."""

    def __init__(self, aircraft=FLEET, level_db: float = -20.0, t0: float = 0.0, every_s: float = 0.25):
        self.aircraft = list(aircraft)
        self.level_db = float(level_db)
        self.t0 = float(t0)
        self.every_s = float(every_s)
        self.lock = threading.Lock()
        self.pending: list[tuple[int, np.ndarray]] = []
        self.done_to = 0.0

    def in_view(self, rx_if: float, fs: float) -> bool:
        return abs(CENTRE_HZ - rx_if) + HALF_SPAN < fs / 2

    def _replies(self, t_lo: float, t_hi: float):
        out = []
        for a in self.aircraft:
            k = math.ceil((t_lo - a.phase_s) / self.every_s)
            while a.phase_s + k * self.every_s < t_hi:
                if k >= 0:
                    t = a.phase_s + k * self.every_s
                    out.append((t, a, a.message(self.t0 + t, k)))
                k += 1
        return out

    def take(self, k: int, n: int, fs: float, rx_if: float) -> np.ndarray | None:
        if not self.in_view(rx_if, fs):
            self.pending.clear()
            self.done_to = (k + n) / fs
            return None
        from shack_sdr import _native
        if not hasattr(_native, "testsig_adsb"):
            return None                 # a shack_sdr from before ADS-B
        y = np.zeros(n, np.complex64)
        t_lo, t_hi = k / fs, (k + n) / fs
        with self.lock:
            lo = max(self.done_to, t_lo)
            for t, a, m in self._replies(lo, t_hi):
                lat, lon = a.where(self.t0 + t)[:2]
                km = math.dist((lat * 111.32, lon * 63.0), (STATION[0] * 111.32, STATION[1] * 63.0))
                level = min(-10.0, self.level_db - 20 * math.log10(max(km, 1.0) / 20.0))
                start = int(math.floor(t * fs))
                z = np.frombuffer(_native.testsig_adsb([{"t": t - start / fs, "payload": _native.adsb_encode(m),
                                                         "level_db": level, "offset_hz": CENTRE_HZ - rx_if,
                                                         "phase": (a.icao % 97) / 97.0}],
                                                       rate=float(fs), duration_s=REPLY_S + 2.0 / fs), np.complex64)
                self.pending.append((start, z))
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
