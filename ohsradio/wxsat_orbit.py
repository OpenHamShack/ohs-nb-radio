"""Satellite passes over the station: SGP4 (the vendored sgp4 wheel,
ohscore/shacklibs.py) from a two-line element set to azimuth and
elevation, and the passes - acquisition (AOS), closest approach (TCA)
and loss (LOS) - in a time window.

    sat = Orbit(l1, l2)
    sat.look(t, lat, lon)                       # (az, el) in degrees at Unix time t
    sat.doppler_hz(t, lat, lon, freq_hz)        # the shift of freq_hz heard at the station
    passes(sat, lat, lon, start, end)           # [{"aos", "tca", "los", "maxEl", "aosAz", "losAz"}]
    track(sat, lat, lon, aos, los, step=10.0)   # [{"t", "az", "el"}]

**Frames.** SGP4 gives a position in TEME; turning that into the
station's sky needs only Earth's rotation, by Greenwich mean sidereal time
(the IAU 1982 formula, UT1 taken as UTC). Polar motion, nutation and the
UT1-UTC difference are left out: together they move a low-orbit satellite
by well under a kilometre, a few hundredths of a degree at the horizon and
a tenth of a second in AOS - far below what a pass recorded from horizon
to horizon cares about, and below what the element sets themselves are
good for after a day. The station is on the WGS-84 ellipsoid at height 0:
Radio's station profile has a locator, not an altitude.

**Passes** are found by stepping STEP_S (30 s: a Meteor pass above 0° is
at least a couple of minutes, and the shortest above the horizon that a
30 s step could miss entirely peaks below 1°, never a pass anyone records)
and then bisecting each horizon crossing to REFINE_S; the closest approach
is a golden-section search for the highest elevation between them. A
pass already in progress at `start` is found from where it rose.
"""
from __future__ import annotations

import math

from ohscore import shacklibs

STEP_S = 30.0
REFINE_S = 0.5
WGS84_A = 6378.137                 # km
WGS84_F = 1 / 298.257223563
JD_UNIX = 2440587.5                # the Julian date of 1970-01-01 00:00 UTC
C_KM_S = 299792.458                # the speed of light


def gmst(jd: float) -> float:
    """Greenwich mean sidereal time (radians) at Julian date `jd` (UT1)."""
    t = (jd - 2451545.0) / 36525.0
    sec = 67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return math.radians((sec % 86400.0) / 240.0)


def sun_elevation(lat: float, lon: float, t: float) -> float:
    """The Sun's elevation in degrees at (lat, lon) at Unix time `t`: the
    low-precision formula of the Astronomical Almanac (about 0.01 deg in
    declination, far finer than night against day needs). Used to tell a
    night pass, whose visible channels are dark, from a day one."""
    n = t / 86400.0 + 2440587.5 - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360.0)
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ha = gmst(n + 2451545.0) + math.radians(lon) - ra
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def station_ecef(lat: float, lon: float, h_km: float = 0.0) -> tuple[float, float, float]:
    la, lo = math.radians(lat), math.radians(lon)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + h_km) * math.cos(la) * math.cos(lo), (n + h_km) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h_km) * math.sin(la))


class Orbit:
    """One satellite's element set, propagated by SGP4."""

    def __init__(self, l1: str, l2: str):
        shacklibs.sgp4()                        # on the path: installed, or the vendored wheel
        from sgp4.api import Satrec
        self.sat = Satrec.twoline2rv(l1, l2)
        self._cache: tuple | None = None        # (lat, lon, station ECEF)

    def ecef(self, t: float) -> tuple[float, float, float] | None:
        """Earth-fixed position (km) at Unix time `t`; None where SGP4
        reports an error (a decayed orbit)."""
        jd = t / 86400.0 + JD_UNIX
        whole = math.floor(jd)
        e, r, _v = self.sat.sgp4(whole, jd - whole)
        if e != 0:
            return None
        g = gmst(jd)
        c, s = math.cos(g), math.sin(g)
        return (r[0] * c + r[1] * s, -r[0] * s + r[1] * c, r[2])

    def _station(self, lat: float, lon: float) -> tuple[float, float, float]:
        if self._cache is None or self._cache[:2] != (lat, lon):
            self._cache = (lat, lon, station_ecef(lat, lon))
        return self._cache[2]

    def look(self, t: float, lat: float, lon: float) -> tuple[float, float]:
        """(azimuth, elevation) in degrees from the station; elevation -90
        where SGP4 cannot place the satellite."""
        p = self.ecef(t)
        if p is None:
            return 0.0, -90.0
        sx, sy, sz = self._station(lat, lon)
        dx, dy, dz = p[0] - sx, p[1] - sy, p[2] - sz
        la, lo = math.radians(lat), math.radians(lon)
        sla, cla, slo, clo = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
        east = -slo * dx + clo * dy
        north = -sla * clo * dx - sla * slo * dy + cla * dz
        up = cla * clo * dx + cla * slo * dy + sla * dz
        az = math.degrees(math.atan2(east, north)) % 360.0
        el = math.degrees(math.atan2(up, math.hypot(east, north)))
        return az, el

    def doppler_hz(self, t: float, lat: float, lon: float, freq_hz: float, dt: float = 0.5) -> float:
        """The Doppler shift (Hz) of `freq_hz` sent by the satellite and
        heard at the station at Unix time `t`: positive while it comes
        closer. From the rate of change of range, by central difference of
        two Earth-fixed positions `dt` apart - simpler than turning SGP4's
        TEME velocity into the Earth's frame (which needs Earth's rotation
        added to it) and, over half a second, good to well under a hertz of
        a shift of a few kHz. 0.0 where SGP4 cannot place the satellite,
        as look() gives -90 there."""
        a, b = self.ecef(t - dt / 2), self.ecef(t + dt / 2)
        if a is None or b is None:
            return 0.0
        s = self._station(lat, lon)
        rate = (math.dist(b, s) - math.dist(a, s)) / dt        # km/s, positive while it goes away
        return -freq_hz * rate / C_KM_S


def _crossing(sat: Orbit, lat: float, lon: float, a: float, b: float, rising: bool) -> float:
    """The horizon crossing between a and b (elevation changes sign)."""
    while b - a > REFINE_S:
        m = (a + b) / 2
        above = sat.look(m, lat, lon)[1] > 0.0
        if above == rising:
            b = m
        else:
            a = m
    return (a + b) / 2


def _peak(sat: Orbit, lat: float, lon: float, a: float, b: float) -> float:
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    while b - a > REFINE_S:
        if sat.look(c, lat, lon)[1] > sat.look(d, lat, lon)[1]:
            b, d = d, c
            c = b - g * (b - a)
        else:
            a, c = c, d
            d = a + g * (b - a)
    return (a + b) / 2


def passes(sat: Orbit, lat: float, lon: float, start: float, end: float) -> list[dict]:
    """Every pass above the horizon that is in the sky at any time between
    `start` and `end` (Unix): {"aos", "tca", "los", "maxEl", "aosAz",
    "losAz"}, times as Unix seconds."""
    out = []
    t = start
    el = sat.look(t, lat, lon)[1]
    if el > 0.0:
        # Already up: walk back to where it rose (never further than a pass lasts).
        back = t
        while back > start - 3600.0 and sat.look(back - STEP_S, lat, lon)[1] > 0.0:
            back -= STEP_S
        aos = _crossing(sat, lat, lon, back - STEP_S, back, True)
    else:
        aos = None
    while t < end:
        nxt = t + STEP_S
        el2 = sat.look(nxt, lat, lon)[1]
        if aos is None and el <= 0.0 < el2:
            aos = _crossing(sat, lat, lon, t, nxt, True)
        elif aos is not None and el > 0.0 >= el2:
            los = _crossing(sat, lat, lon, t, nxt, False)
            tca = _peak(sat, lat, lon, aos, los)
            out.append({"aos": aos, "tca": tca, "los": los, "maxEl": sat.look(tca, lat, lon)[1],
                        "aosAz": sat.look(aos, lat, lon)[0], "losAz": sat.look(los, lat, lon)[0]})
            aos = None
        t, el = nxt, el2
    if aos is not None:
        # Still up at `end`: finish the pass it is in.
        while sat.look(t, lat, lon)[1] > 0.0 and t < end + 3600.0:
            t += STEP_S
        los = _crossing(sat, lat, lon, t - STEP_S, t, False)
        tca = _peak(sat, lat, lon, aos, los)
        out.append({"aos": aos, "tca": tca, "los": los, "maxEl": sat.look(tca, lat, lon)[1],
                    "aosAz": sat.look(aos, lat, lon)[0], "losAz": sat.look(los, lat, lon)[0]})
    return out


def track(sat: Orbit, lat: float, lon: float, aos: float, los: float, step: float = 10.0) -> list[tuple]:
    """(t, az, el) every `step` seconds from AOS, and LOS itself."""
    out = []
    t = aos
    while t < los:
        az, el = sat.look(t, lat, lon)
        out.append((t, az, el))
        t += step
    az, el = sat.look(los, lat, lon)
    out.append((los, az, el))
    return out
