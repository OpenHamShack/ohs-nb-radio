"""Ships on the simulated air: AIS bursts from a handful of vessels moving in
the Firth of Clyde off the Ayrshire coast, near the station's own locator
(IO75RL, by Ayr), so the ship map can be built and tested with no radio
(Brian, 28/10/2026).

Each burst is a real one: the message is written by shack_sdr's AIS
writer (`_native.ais_encode`) and keyed by its test transmitter
(`_native.testsig_ais`: training, HDLC, NRZI, GMSK) at the simulator's own
rate, on channel A or B in turn, so Radio's AIS session decodes it exactly
as it would a ship. The ships, all fictional (MMSIs in 2359990xx, which no
ship has):

- **CLYDE SPIRIT**, a passenger ferry, Ardrossan to Brodick and back at
  16 knots: positions (type 1) every 4 s, static and voyage (type 5)
  every 30 s.
- **ARRAN TRADER**, a cargo ship, up and down the firth between Ailsa
  Craig and the Cumbraes at 11 knots.
- **GIRVAN LASS**, a fishing boat off Girvan, engaged in fishing at 4 knots.
- **SEA HAWK**, a yacht with a Class B transponder (types 18 and 24),
  from south of the Cumbraes to off Troon at 6 knots.
- **TROON PILOT**, moored in Troon harbour.
- **LADY ISLE**, an aid to navigation (type 21) on the island of that name.

The real rates are slower - a ship's static data comes every six minutes -
but a map that took six minutes to name its ships would be a poor test.
Every route lies on water: tests/test_ham_ais.py checks each against the
bundled land map. Movement follows the simulator's clock, so a recording or
a test that runs faster than real time moves the ships as fast.

A level is set by each ship's distance from the station, about -40 dBFS
for one 10 km away (the simulator's noise floor puts that near 30 dB Eb/N0).
"""
from __future__ import annotations

import math
import threading

import numpy as np

CENTRE_HZ = 162_000_000.0
HALF_SPAN = 25_000.0 + 12_500.0
STATION = (55.4792, -4.5417)        # IO75RL's centre


def _knots_deg(kn: float, lat: float) -> tuple[float, float]:
    """Degrees of latitude and longitude a second at `kn` knots."""
    m_s = kn * 1852.0 / 3600.0
    return m_s / 111_320.0, m_s / (111_320.0 * math.cos(math.radians(lat)))


class Ship:
    """One station on the air, moving to and fro between `a` and `b`
    (lat, lon) at `knots` (0: still at `a`)."""

    def __init__(self, mmsi: int, name: str, kind: str, a, b=None, knots: float = 0.0, ship_type: int = 0,
                 status: int = 0, callsign: str = "", dims=(0, 0, 0, 0), destination: str = "",
                 every_s: float = 4.0, static_s: float = 30.0, phase_s: float = 0.0):
        self.mmsi, self.name, self.kind = mmsi, name, kind
        self.a, self.b = a, b or a
        self.knots, self.ship_type, self.status = knots, ship_type, status
        self.callsign, self.dims, self.destination = callsign, dims, destination
        self.every_s, self.static_s, self.phase_s = every_s, static_s, phase_s
        km = math.dist((a[0] * 111.32, a[1] * 111.32 * math.cos(math.radians(a[0]))),
                       (self.b[0] * 111.32, self.b[1] * 111.32 * math.cos(math.radians(a[0]))))
        self.leg_s = km * 1000.0 / (knots * 1852.0 / 3600.0) if knots > 0 else 0.0

    def where(self, t: float) -> tuple[float, float, float, float]:
        """(lat, lon, speed knots, course degrees) at time `t` (seconds)."""
        if self.leg_s <= 0:
            return self.a[0], self.a[1], 0.0, 0.0
        u = (t % (2 * self.leg_s)) / self.leg_s
        frm, to = (self.a, self.b) if u < 1 else (self.b, self.a)
        f = u if u < 1 else u - 1
        lat = frm[0] + (to[0] - frm[0]) * f
        lon = frm[1] + (to[1] - frm[1]) * f
        dy = to[0] - frm[0]
        dx = (to[1] - frm[1]) * math.cos(math.radians(lat))
        course = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
        return lat, lon, self.knots, course

    def messages(self, t: float, n: int) -> list[dict]:
        """The raw fields of what it sends in its `n`-th slot at `t`."""
        lat, lon, kn, course = self.where(t)
        pos = {"mmsi": self.mmsi, "lat": round(lat * 600_000), "lon": round(lon * 600_000),
               "speed": round(kn * 10), "course": round(course * 10) % 3600,
               "heading": round(course) % 360 if kn > 0 else 511, "second": int(t) % 60, "accuracy": 1}
        bow, stern, port, stbd = self.dims
        if self.kind == "aton":
            return [{"type": 21, "mmsi": self.mmsi, "aid_type": 5, "name": self.name, "lat": pos["lat"],
                     "lon": pos["lon"], "epfd": 7, "second": pos["second"], "accuracy": 1}]
        if self.kind == "B":
            if n % 2:
                return [{"type": 24, "mmsi": self.mmsi, "partno": 0, "shipname": self.name},
                        {"type": 24, "mmsi": self.mmsi, "partno": 1, "shiptype": self.ship_type,
                         "callsign": self.callsign, "vendorid": "SIM", "to_bow": bow, "to_stern": stern,
                         "to_port": port, "to_starboard": stbd}]
            return [dict(pos, type=18, cs=1)]
        if n % 2:
            return [{"type": 5, "mmsi": self.mmsi, "shipname": self.name, "callsign": self.callsign,
                     "shiptype": self.ship_type, "to_bow": bow, "to_stern": stern, "to_port": port,
                     "to_starboard": stbd, "epfd": 1, "destination": self.destination, "draught": 45,
                     "month": 10, "day": 29, "hour": 18, "minute": 30, "ais_version": 2}]
        return [dict(pos, type=1, status=self.status, turn=0 if kn > 0 else -128)]


FLEET = [
    Ship(235999001, "CLYDE SPIRIT", "A", (55.636, -4.840), (55.578, -5.120), 16.0, ship_type=60,
         callsign="MCLY1", dims=(70, 20, 8, 8), destination="BRODICK", phase_s=0.3),
    Ship(235999002, "ARRAN TRADER", "A", (55.300, -5.050), (55.800, -4.990), 11.0, ship_type=70,
         callsign="MARN2", dims=(90, 15, 7, 7), destination="GREENOCK", phase_s=1.1),
    Ship(235999003, "GIRVAN LASS", "A", (55.240, -4.900), (55.300, -4.980), 4.0, ship_type=30, status=7,
         callsign="MGIR3", dims=(15, 5, 3, 3), destination="GIRVAN", every_s=6.0, phase_s=2.2),
    Ship(235999004, "SEA HAWK", "B", (55.690, -4.970), (55.570, -4.780), 6.0, ship_type=37,
         callsign="2SEA4", dims=(9, 3, 2, 2), every_s=10.0, phase_s=3.4),
    Ship(235999005, "TROON PILOT", "A", (55.5465, -4.6905), None, 0.0, ship_type=50, status=5,
         callsign="MTRN5", dims=(12, 4, 3, 3), destination="TROON", every_s=10.0, phase_s=0.7),
    Ship(992359006, "LADY ISLE", "aton", (55.5217, -4.7317), None, 0.0, every_s=30.0, static_s=1e9,
         phase_s=5.0),
]


class AisFleet:
    """The fleet as a simulator hears it (module docstring): `take` gives
    the bursts that fall in samples k..k+n at a receiver centred on
    `rx_if`; `iq(t, rx_if)` the same for a simulator that counts time.
    `level_db` is a ship's burst power 10 km from the station, dBFS."""

    def __init__(self, ships=FLEET, level_db: float = -40.0, t0: float = 0.0):
        self.ships = list(ships)
        self.level_db = float(level_db)
        self.t0 = float(t0)
        self.lock = threading.Lock()
        self.pending: list[tuple[int, np.ndarray]] = []
        self.done_to = 0.0           # bursts are scheduled up to this time
        self.counts: dict[int, int] = {}
        self.slot = 0

    def in_view(self, rx_if: float, fs: float) -> bool:
        return abs(CENTRE_HZ - rx_if) + HALF_SPAN < fs / 2

    def _bursts(self, t_lo: float, t_hi: float):
        """(start time, ship, raw fields) of every burst starting in [t_lo, t_hi)."""
        out = []
        for s in self.ships:
            k = math.ceil((t_lo - s.phase_s) / s.every_s)
            while s.phase_s + k * s.every_s < t_hi:
                t = s.phase_s + k * s.every_s
                if k >= 0:
                    n = self.counts.get(s.mmsi, 0)
                    self.counts[s.mmsi] = n + 1
                    # Static data in every (static_s / every_s)-th slot.
                    every = max(1, round(s.static_s / s.every_s))
                    msgs = s.messages(self.t0 + t, 1 if (k % every == every - 1) else 0)
                    for j, m in enumerate(msgs):
                        out.append((t + 0.04 * j, s, m))
                k += 1
        return out

    def take(self, k: int, n: int, fs: float, rx_if: float) -> np.ndarray | None:
        if not self.in_view(rx_if, fs):
            self.pending.clear()
            self.done_to = (k + n) / fs
            return None
        from shack_sdr import _native
        y = np.zeros(n, np.complex64)
        t_lo, t_hi = k / fs, (k + n) / fs
        with self.lock:
            lo = max(self.done_to, t_lo)
            for t, ship, fields in self._bursts(lo, t_hi):
                lat, lon, _kn, _c = ship.where(self.t0 + t)
                km = math.dist((lat * 111.32, lon * 63.0), (STATION[0] * 111.32, STATION[1] * 63.0))
                level = self.level_db - 20 * math.log10(max(km, 1.0) / 10.0)
                ch = "A" if self.slot % 2 == 0 else "B"
                self.slot += 1
                payload = _native.ais_encode(fields)
                dur = 0.002 + len(payload) * 8 * 1.25 / 9600.0 + 0.004
                z = np.frombuffer(_native.testsig_ais([{"t": 0.0, "channel": ch, "payload": payload,
                                                        "level_db": level}], rate=float(fs), duration_s=dur,
                                                      centre_hz=CENTRE_HZ - rx_if), np.complex64)
                self.pending.append((int(round(t * fs)), z))
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
