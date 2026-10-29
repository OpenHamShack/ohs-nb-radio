"""A radiosonde on the simulated air, and stand-ins for auto_rx's programs
(29/10/2026), so Radio's radiosonde map can be built and tested with no
radio and none of radiosonde_auto_rx's binaries.

**On the air**, `SondeAir` puts one fictional sonde's carrier on 403.500
MHz: continuous 2-FSK at an RS41's 4800 baud and +-2.4 kHz, random bits.
It is real enough for what Radio does with it itself - the scan's power
spectrum finds it, and the channel is cut from the receiver's IQ - and no
more: it carries no frames, because writing a sonde *modulator* to test a
decoder Radio did not write would test nothing but the modulator.

**The programs** (`Programs`, given to SondeService as auto_rx's would be;
sonde.py picks it for the simulated radio by itself) are this module run
as `python3 -m ohsradio.devices.simsonde <name> <auto_rx's arguments>`, so
the pipeline Radio builds - processes started with auto_rx's command
lines, 16-bit IQ written down the pipe at each decoder's rate, the last
one's JSON lines read back - runs exactly as it would with the real ones:

- `iq_dec`, `fsk_demod`: pass their input on.
- `dft_detect`: reads its `-t` seconds of IQ and names the sonde when the
  channel is the simulated sonde's (OHS_SONDE_FREQ, which Radio sets for
  every program it starts), as the real one prints it ("RS41: 0.95, +0.0
  Hz"); otherwise prints nothing, as for a channel with no sonde.
- the decoders (`rs41mod`, `dfm09mod`): one frame a second *of IQ read*, so
  a simulator faster than real time decodes as fast; each line in the
  decoder's own JSON form (its printf in auto_rx's demod/mod/*.c), version
  "1.9.0", from the flight below. Silent on any other channel.

**The flight** (`flight`): launched from a fictional site west of Ayr
(SITE), climbing at 5 m/s to burst at 30 km, drifting east-north-east on a
wind that strengthens with height, falling under a parachute at 5 m/s at
sea level (faster in thin air, sondehub.air_density) and then lying in a
field still transmitting, as real ones do. The default sonde (serial
Z0000001: Vaisala's form, which Radio checks as auto_rx does, and a
letter no real sonde will reach for years) launches at 11:15 and 23:15
UTC every day, as the UK's synoptic sondes do, so the simulator shows one in
flight or lying where it landed at any hour. A test gives its own
`launch` time and `speedup` (flight seconds per frame) to see a whole
flight in a few hundred frames.

The simulator's sondes are never uploaded to SondeHub: Programs says it is
`simulated` and sonde.py keeps its frames at home.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FREQ_HZ = 403_500_000.0
SERIAL = "Z0000001"
SITE = (55.4400, -4.6300, 20.0)          # fictional, on the coast west of Ayr
ASCENT_MS = 5.0
BURST_M = 30_000.0
DESCENT_MS = 5.0                          # at sea level
HEADING = 70.0
LAUNCHES_UTC = (11 * 3600 + 15 * 60, 23 * 3600 + 15 * 60)
BAUD = 4800
DEVIATION_HZ = 2400.0
HALF_SPAN = 10_000.0
VERSION = "1.9.0"


WIND0, WIND_PER_M = 3.0, 0.0006     # m/s at the ground, and more for each metre up


def _wind(alt: float) -> float:
    return WIND0 + WIND_PER_M * max(alt, 0.0)


def _descent_table() -> list[tuple[float, float]]:
    """(altitude, distance drifted) a second at a time from the burst."""
    from ohsradio.sondehub import air_density
    alt, dist, out = BURST_M, 0.0, []
    while alt > SITE[2]:
        out.append((alt, dist))
        v = DESCENT_MS * (1.22 / air_density(alt)) ** 0.5
        alt -= v
        dist += _wind(alt)
    out.append((SITE[2], dist))
    return out


_DESCENT = None
T_UP = (BURST_M - SITE[2]) / ASCENT_MS


def _destination(lat, lon, bearing, km):
    r = km / 6371.0088
    b, p1, l1 = math.radians(bearing), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(r) + math.cos(p1) * math.sin(r) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(r) * math.cos(p1), math.cos(r) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def flight(ft: float) -> dict:
    """The sonde `ft` seconds after launch (module docstring)."""
    global _DESCENT
    if _DESCENT is None:
        _DESCENT = _descent_table()
    ft = max(ft, 0.0)
    if ft <= T_UP:
        alt = SITE[2] + ASCENT_MS * ft
        a0 = _wind(SITE[2])
        dist = a0 * ft + WIND_PER_M * ASCENT_MS * ft * ft / 2
        vv, vh = ASCENT_MS, _wind(alt)
    else:
        up_dist = _wind(SITE[2]) * T_UP + WIND_PER_M * ASCENT_MS * T_UP * T_UP / 2
        i = int(ft - T_UP)
        if i < len(_DESCENT) - 1:
            alt, d = _DESCENT[i]
            vv, vh = -(alt - _DESCENT[i + 1][0]), _wind(alt)
        else:
            alt, d = _DESCENT[-1]
            vv, vh = 0.0, 0.0
        dist = up_dist + d
    lat, lon = _destination(SITE[0], SITE[1], HEADING, dist / 1000.0)
    temp = 15.0 - 6.5 * min(alt, 11000.0) / 1000.0 + (max(alt - 20000.0, 0.0) / 1000.0)
    return {"lat": round(lat, 5), "lon": round(lon, 5), "alt": round(alt, 1), "vel_v": round(vv, 2),
            "vel_h": round(vh, 2), "heading": HEADING, "temp": round(temp, 1),
            "humidity": round(max(80.0 - alt / 400.0, 2.0), 1),
            "pressure": round(1013.25 * math.exp(-alt / 7400.0), 2)}


def last_launch(now: float) -> float:
    """The most recent of the daily launches (LAUNCHES_UTC) at or before `now`."""
    day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    best = day - 86400 + LAUNCHES_UTC[-1]
    for s in LAUNCHES_UTC:
        if day + s <= now:
            best = day + s
    return best


class Programs:
    """The stand-ins (module docstring), for SondeService.programs."""
    simulated = True

    def __init__(self, freq_hz: float = FREQ_HZ, kind: str = "RS41", serial: str = SERIAL,
                 launch: float | None = None, speedup: float = 1.0):
        root = str(Path(__file__).resolve().parents[2])
        cfg = {"freqHz": float(freq_hz), "kind": kind, "serial": serial, "launch": launch, "speedup": speedup}
        self.env = {"OHS_SIMSONDE": json.dumps(cfg),
                    "PYTHONPATH": os.pathsep.join(p for p in (root, os.environ.get("PYTHONPATH", "")) if p)}

    def available(self) -> bool:
        return True

    def argv(self, name: str, *args: str) -> list[str]:
        return [sys.executable, "-m", "ohsradio.devices.simsonde", name, *args]


class SondeAir:
    """The sonde's carrier as a simulator hears it (module docstring):
    `take(k, n, fs, rx_if)` what falls in samples k..k+n at a receiver
    centred on `rx_if`; `iq(t, rx_if)` the same for one that counts time."""

    def __init__(self, freq_hz: float = FREQ_HZ, level_db: float = -45.0, seed: int = 41):
        import numpy as np
        self.freq = float(freq_hz)
        self.amp = 10 ** (level_db / 20)
        self.bits = np.random.default_rng(seed).integers(0, 2, 4800 * 8).astype(np.float32) * 2 - 1
        self.phase = 0.0

    def in_view(self, rx_if: float, fs: float) -> bool:
        return abs(self.freq - rx_if) + HALF_SPAN < fs / 2

    def take(self, k: int, n: int, fs: float, rx_if: float):
        import numpy as np
        if not self.in_view(rx_if, fs):
            return None
        idx = ((k + np.arange(n)) * (BAUD / fs)).astype(np.int64) % len(self.bits)
        f = (self.freq - rx_if) + DEVIATION_HZ * self.bits[idx]
        ph = self.phase + 2 * np.pi * np.cumsum(f) / fs
        self.phase = float(ph[-1] % (2 * np.pi))
        return (self.amp * np.exp(1j * ph)).astype(np.complex64)

    def iq(self, t, rx_if: float):
        import numpy as np
        fs = 1.0 / float(t[1] - t[0]) if len(t) > 1 else 2_400_000.0
        z = self.take(int(round(float(t[0]) * fs)), len(t), fs, rx_if)
        return np.zeros(len(t), np.complex64) if z is None else z


# -- the stand-ins themselves (run as a program) -------------------------------------
def _cfg() -> dict:
    try:
        cfg = json.loads(os.environ.get("OHS_SIMSONDE") or "{}")
    except ValueError:
        cfg = {}
    return {"freqHz": FREQ_HZ, "kind": "RS41", "serial": SERIAL, "launch": None, "speedup": 1.0, **cfg}


def _on_channel(cfg: dict) -> bool:
    try:
        return abs(float(os.environ.get("OHS_SONDE_FREQ", "0")) - cfg["freqHz"]) <= 5000.0
    except ValueError:
        return False


def _line(cfg: dict, n: int, ft: float, launch: float) -> str:
    f = flight(ft)
    t = datetime.fromtimestamp(launch + ft, timezone.utc)
    stamp = t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
    doc = {"type": "RS41", "frame": n, "id": cfg["serial"], "datetime": stamp, "lat": f["lat"], "lon": f["lon"],
           "alt": f["alt"], "vel_h": f["vel_h"], "heading": f["heading"], "vel_v": f["vel_v"], "sats": 9,
           "bt": 65535, "batt": 2.9, "temp": f["temp"], "humidity": f["humidity"], "pressure": f["pressure"],
           "subtype": "RS41-SGP"}
    if cfg["kind"] == "DFM":
        doc.update(type="DFM", id="DFM-" + cfg["serial"], subtype="0xD:DFM17", frame=n + 256)
        doc.pop("bt")
    doc["version"] = VERSION
    return json.dumps(doc)


def main(argv: list[str]) -> int:
    name, args = argv[0], argv[1:]
    cfg = _cfg()
    src, dst = sys.stdin.buffer, sys.stdout.buffer
    if name in ("iq_dec", "fsk_demod"):
        while True:
            b = src.read1(65536) if hasattr(src, "read1") else src.read(65536)
            if not b:
                return 0
            try:
                dst.write(b)
                dst.flush()
            except BrokenPipeError:
                return 0
    if name == "dft_detect":
        secs = int(args[args.index("-t") + 1]) if "-t" in args else 5
        want, got = secs * 48000 * 4, 0
        while got < want:
            b = src.read1(65536)
            if not b:
                break
            got += len(b)
        if _on_channel(cfg) and got >= want // 2:
            tag = {"RS41": "RS41", "DFM": "DFM9"}.get(cfg["kind"], cfg["kind"])
            dst.write(f"{tag}: 0.9500, +0.0 Hz\n".encode())
            dst.flush()
            return 2
        return 1
    # A decoder: a frame a second of IQ (48 kS/s, 16-bit I and Q), or of DFM's 50.
    per = (50_000 if cfg["kind"] == "DFM" else 48_000) * 4
    now = time.time()
    launch = float(cfg["launch"]) if cfg.get("launch") is not None else last_launch(now)
    ft0 = now - launch
    on = _on_channel(cfg)
    n, have = 0, 0
    while True:
        b = src.read1(65536)
        if not b:
            return 0
        have += len(b)
        while have >= per:
            have -= per
            n += 1
            if on:
                ft = ft0 + n * float(cfg["speedup"])
                try:
                    dst.write((_line(cfg, int(ft) + 1, ft, launch) + "\n").encode())
                    dst.flush()
                except BrokenPipeError:
                    return 0


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except BrokenPipeError:
        rc = 0
    # Not sys.exit: its flush of a pipe the reader has closed only complains.
    os._exit(rc)
