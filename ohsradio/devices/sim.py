"""A simulated set of amateur bands - the default device, so the whole
program can be learnt, demonstrated and tested with no radio and no
licence (docs/ham/DESIGN-HAM.md section 4.5).

It simulates **bands, not a radio**: wherever the engine tunes it, from
160 m to 6 cm, it produces what a receiver there would hear, built from
the band's plan when the receiver first arrives (a band is populated on a
worker thread in real time, so arriving on a band is like switching the
rig on: the stations fade in over a second or two).

- **HF**: the band's own noise floor (atmospheric noise is far higher on
  160 m than on 10 m), QRN impulses on the low bands for the noise
  blanker, SSB QSOs in the all-modes segment (LSB below 10 MHz, USB above),
  CW in the CW segment, FT8 at the band's WSJT-X dial, a few PSK31 and
  RTTY signals in the narrow segment, the IBP beacons on 20-10 m, and a
  dead carrier on 80 m and 40 m (for a notch). How many of each depends on
  the **UTC hour** (simHourUtc, or the real time): 160 m and 80 m come
  alive after dark, 20 m by day, 15-10 m only around midday (2026 is past
  the cycle 25 peak).
- **VHF/UHF**: CW beacons in the beacon sub-band, SSB and CW around the
  calling frequency, FT8 at its dial, FM simplex on the calling channel and
  the V/U channels, and two **repeaters** per band - fictional callsigns
  (GB3SIM...), real UK channel pairs - each with a CTCSS tone, relaying
  their own users now and then.
- **DAB**: one ensemble on Band III's 11D (222.064 MHz), the test
  ensemble of shack_sdr's DAB transmitter model (simdab.py), so a DAB
  session finds stations with no radio.
- **AIS**: six fictional ships and a buoy in the Firth of Clyde on
  161.975 and 162.025 MHz (simais.py), so the ship map fills with no radio.
- **ADS-B**: six fictional aircraft around Prestwick on 1090 MHz
  (simadsb.py), for the aircraft map.
- **Broadcast FM**: six fictional stations on Band II from shack_sdr's FM
  stereo and RDS test transmitter (simfm.py), so wide FM is heard in
  stereo with RDS, and the band scanner finds something, with no radio.
- **DMR**: a repeater on 439.6125 MHz playing shack_sdr's DMR test
  transmitter's showcase (simdmr.py): both slots busy, talker alias, an
  encrypted call and an SMS, so a DMR session has something to decode.
- **Our own transmission** comes back, a local signal, at the dial it was
  sent on (half duplex: the engine mutes it, the scope shows it). A
  repeater whose input we transmit on with its tone (or a 1750 Hz
  toneburst, where it accepts one) **opens**: it relays us on its output
  while we transmit, then sends its courtesy "K" and drops after a hang.
  The wrong tone, or none, and it stays closed.
- **A converter** (a transverter, an up/down-converter) in front of it, when
  the engine says one is in use (`set_rx_converter`, `set_tx_converter`):
  the simulator is then the radio *and* the converter, so tuned to 144.2
  MHz through a 1296 MHz transverter it produces 23 cm, and through an
  inverting one it hands back a mirrored spectrum and mirrors what it is
  sent - which the engine must undo for anything to sound right.
- **Telemetry** while transmitting: forward power from the drive and the
  device figure, reflected power from the simulated antenna's SWR
  (simAntSwr), and a PA temperature that rises with duty - so the SWR and
  temperature guards can be tested without a radio.

The device figure for full drive is a Hermes-Lite 2's 5 W below 30 MHz and
a Pluto's 4.5 mW above (ohsradio/power.py), so the power chain and the
licence guard see believable numbers.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.devices.base import DeviceError
from ohscore.devices.simcore import FT8Activity, Presence, SimCore, Station
from ohscore.dsp import fm as fmdsp
from ohscore.dsp import morse
from ohscore.dsp.bank import Geometry, Source, Synthesis

from .. import bands as bandmod
from ..plans import rsgb_2026 as plan

FLOOR_DB_HZ = -112.0            # the receiver's own floor, dBFS/Hz
# Atmospheric/galactic noise over the receiver floor, dBFS/Hz, by band.
BAND_NOISE = {"160m": -94.0, "80m": -97.0, "60m": -99.0, "40m": -101.0, "30m": -103.0, "20m": -105.0,
              "17m": -106.0, "15m": -107.0, "12m": -108.0, "10m": -109.0, "6m": -110.0, "4m": -111.0}
QRN = {"160m": 18.0, "80m": 12.0, "60m": 6.0, "40m": 5.0, "30m": 2.0}      # impulses per second
OWN_DB = -22.0                  # our own transmission as heard locally at full drive, dBFS
CALLS = ["G4XYZ", "DL1ABC", "EA4QRP", "F5KLM", "OH8ZZ", "PA3QOS", "ON4BB", "SV1QO", "I0XYZ", "OE3ABC", "SP5QO",
         "HB9QQ", "GM4SAT", "CT1QO", "LA9NB", "EI7ABC", "F4GHI", "DK2JKL", "SM0MNO", "9A1PQR", "IW2STU", "OZ3VWX",
         "PE1YZA", "HA5BCD", "MM0SIM", "GM3ZZZ", "2E0SIM", "M7XYZ", "GW4ABC", "MI0QRP"]
IBP_CALLS = ["4U1UN", "VE8AT", "W6WX", "KH6RS", "ZL6B", "VK6RBP", "JA2IGY", "RR9O", "VR2B", "4S7B", "ZS6DN", "5Z4B",
             "4X6TU", "OH2B", "CS3B", "LU4AA", "OA4B", "YV5B"]


def activity(band: str, hour: float) -> float:
    """0..1: how busy `band` is at UTC `hour` - a plausible daily shape,
    not a propagation model."""
    def window(a, b):
        return (hour >= a or hour < b) if a > b else (a <= hour < b)
    h = {
        "160m": 1.0 if window(19, 6) else 0.12,
        "80m": 1.0 if window(17, 8) else 0.35,
        "60m": 0.8 if window(7, 19) else 0.35,
        "40m": 1.0 if window(16, 9) else 0.7,
        "30m": 0.6,
        "20m": 1.0 if window(7, 20) else 0.35,
        "17m": 0.8 if window(8, 18) else 0.12,
        "15m": 0.7 if window(9, 17) else 0.06,
        "12m": 0.5 if window(10, 16) else 0.05,
        "10m": 0.55 if window(10, 16) else 0.06,
        "2m": 1.0 if window(18, 23) else (0.6 if window(7, 18) else 0.2),
        "70cm": 0.75 if window(18, 23) else (0.45 if window(7, 18) else 0.15),
        "23cm": 0.4 if window(18, 23) else 0.2,
        "4m": 0.4 if window(8, 22) else 0.1,
    }
    return h.get(band, 0.2)


def fm_station(rng, seconds: float, ctcss: float, dev: float = 2500.0, talk=(0.0, 1.0)) -> np.ndarray:
    """An FM voice transmission at 12 kHz baseband: speech-like audio with a
    CTCSS tone, the carrier present only while it talks."""
    speech = sg.voice(rng, seconds, (0.0, 1.0)).real
    speech = speech / (np.max(np.abs(speech)) + 1e-9) * 0.9
    z = fmdsp.modulate(speech, sg.RATE, dev, ctcss)
    n = len(z)
    gate = np.zeros(n, np.float32)
    lo, hi = int(talk[0] * n), int(talk[1] * n)
    ramp = int(0.01 * sg.RATE)
    gate[lo:hi] = 1.0
    gate[lo:lo + ramp] = np.linspace(0, 1, ramp)
    gate[hi - ramp:hi] = np.linspace(1, 0, ramp)
    return (z * gate).astype(np.complex64)


def lsb(z: np.ndarray) -> np.ndarray:
    """An analytic (USB) template mirrored to the lower sideband."""
    return np.conj(z).astype(np.complex64)


class Repeater:
    """A simulated repeater: output channel, input = output + shift, CTCSS
    tone (and whether a 1750 Hz toneburst opens it). Relays its own users
    on a schedule; relays us when we open it."""

    HANG = 2.5

    def __init__(self, rng, call: str, out: float, shift: float, tone: float, toneburst: bool, level_db: float):
        self.call, self.dl, self.shift, self.tone, self.toneburst = call, out, shift, tone, toneburst
        self.f_in = out + shift
        self.amp = 10 ** (level_db / 20)
        self.name = f"repeater {call}"
        self.lock = threading.Lock()
        self.users = fm_station(rng, 50.0, tone, talk=(0.0, 0.42))
        self.users_pres = Presence(rng, (90.0, 300.0), (60.0, 300.0))
        self.pos = int(rng.integers(0, len(self.users)))
        self.relay = np.zeros(0, np.complex64)
        self.open_until = 0.0          # sim time
        self.opened = 0                # times we opened it
        self.heard_tone = 0.0
        self.courtesy = self._courtesy()
        self.court_pos = None
        self.phase = 0.0
        self.src: Source | None = None

    def _courtesy(self) -> np.ndarray:
        env = morse.envelope("K", 14.0, sg.RATE, tail=0.3)
        t = np.arange(len(env)) / sg.RATE
        audio = 0.6 * env * np.sin(2 * np.pi * 1000.0 * t)
        return fmdsp.modulate(audio, sg.RATE, 2500.0, self.tone)

    def access(self, tone: float, burst: bool, t: float, keyed: bool) -> bool:
        """Our signal on the input with `tone` (and/or a toneburst) at sim time t."""
        ok = (self.tone and abs(tone - self.tone) < 0.6) or (burst and self.toneburst)
        if ok and t > self.open_until:
            self.opened += 1
        if ok or (keyed and t < self.open_until):
            self.open_until = t + self.HANG
            self.court_pos = 0
        return ok

    def push_relay(self, z12: np.ndarray):
        with self.lock:
            self.relay = np.concatenate([self.relay[-int(sg.RATE):], z12])

    def take_at(self, n: int, t: float, our_carrier: bool) -> np.ndarray:
        out = np.zeros(n, np.complex64)
        if t < self.open_until or our_carrier and t < self.open_until + 0.1:
            with self.lock:
                k = min(n, len(self.relay))
                out[:k] = self.relay[:k]
                self.relay = self.relay[k:]
            if k < n:
                if not our_carrier and self.court_pos is not None and self.court_pos < len(self.courtesy):
                    c = self.courtesy[self.court_pos:self.court_pos + (n - k)]
                    out[k:k + len(c)] = c
                    self.court_pos += len(c)
                    k += len(c)
                if k < n:       # the carrier holds with just its tone through the hang
                    tt = np.arange(n - k) / sg.RATE
                    m = 0.12 * np.sin(2 * np.pi * self.tone * (tt + t)) if self.tone else np.zeros(n - k)
                    ph = self.phase + 2 * np.pi * 2500.0 / sg.RATE * np.cumsum(m)
                    self.phase = float(ph[-1] % (2 * np.pi)) if len(ph) else self.phase
                    out[k:] = np.exp(1j * ph)
            return out * np.float32(self.amp)
        g = self.users_pres.gain(t)
        if g <= 0:
            self.pos = (self.pos + n) % len(self.users)
            return out
        idx = (self.pos + np.arange(n)) % len(self.users)
        self.pos = (self.pos + n) % len(self.users)
        return (self.users[idx] * np.float32(self.amp * g)).astype(np.complex64)


class IbpBeacons:
    """The NCDXF/IARU beacons on one band's IBP frequency: 18 stations, 10 s
    each, a 3-minute cycle, on UTC - callsign at 100 W then four dashes
    falling 10 dB each."""

    def __init__(self, rng, band_idx: int, dl: float, level_db: float):
        self.dl, self.name = dl, "IBP"
        self.band_idx = band_idx
        self.amp = 10 ** (level_db / 20)
        self.slots = {}
        self.src: Source | None = None
        self.rng = rng
        self.levels = [float(rng.uniform(-14, 6)) for _ in IBP_CALLS]       # propagation per beacon

    def _slot(self, i: int) -> np.ndarray:
        if i not in self.slots:
            call = IBP_CALLS[i]
            env = morse.envelope(call, 22.0, sg.RATE, tail=0.1)
            parts = [env]
            dash = np.ones(int(1.0 * sg.RATE), np.float32)
            gap = np.zeros(int(0.15 * sg.RATE), np.float32)
            for k in range(4):
                parts += [gap, dash * 10 ** (-k * 10 / 20)]
            e = np.concatenate(parts)[: int(10 * sg.RATE)]
            e = np.concatenate([e, np.zeros(int(10 * sg.RATE) - len(e), np.float32)])
            self.slots[i] = (e * 10 ** (self.levels[i] / 20)).astype(np.complex64)
        return self.slots[i]

    def take_at(self, n: int, t: float, _our=False) -> np.ndarray:
        out = np.empty(n, np.complex64)
        i = 0
        while i < n:
            tt = t + i / sg.RATE
            slot = int(tt // 10)
            beacon = (slot - self.band_idx) % 18
            k = int(round((tt - slot * 10) * sg.RATE)) % int(10 * sg.RATE)
            buf = self._slot(beacon)
            m = min(n - i, len(buf) - k)
            out[i:i + m] = buf[k:k + m]
            i += m
        return out * np.float32(self.amp)


class HamSim(SimCore):
    kind = "sim"
    rx_range = (100e3, 6e9)
    tx_range = (100e3, 6e9)

    def __init__(self, cfg: dict, fs: float = 1_200_000.0):
        self.cfg = cfg
        self.fs = float(fs)
        self.geo = Geometry(self.fs)
        self.syn = Synthesis(self.geo)
        self.signals = bool(cfg.get("simSignals", True))
        self.realtime = bool(cfg.get("simRealtime", True))
        self.hour_cfg = float(cfg.get("simHourUtc", -1.0))
        self.ant_swr = float(cfg.get("simAntSwr", 1.3))
        self.rtt = 0.02                 # our signal comes back after the TX buffer: a local signal
        seed = int(cfg.get("simSeed", 0)) or None
        self.seed = seed if seed is not None else int(np.random.default_rng().integers(2**31))
        self.rng = np.random.default_rng(self.seed)
        self.rx_if = float(cfg.get("vfo", 145_500_000.0))
        self.n = 0
        self.out = np.zeros(0, np.complex64)
        self.opened = False
        self.pops: dict[str, list] = {}       # band -> stations, built on arrival
        # Stations a test (or someone trying a decoder by hand) put on the
        # air with add_station, whatever band they are on.
        self.extra: list = []
        self.building: set[str] = set()
        self.pop_lock = threading.Lock()
        self.drive = 0.0
        self.tx_hz = 0.0                      # where our signal is (set by the engine through set_tx_freq + offset)
        self.temp = 31.0
        self.fwd = 0.0
        self.last_peak = 0.0
        self.tx_listen = None                 # repeater access measurement while we transmit
        self.repeaters: list[Repeater] = []
        self.rx_conv = None                   # converters in front of the simulated radio
        self.tx_conv = None
        self.tx_radio = 0.0                   # what the engine tuned the transmitter to (the IF)
        # A DAB ensemble on 11D (simdab.py): Band III has no amateur band,
        # so the stations above never reach it, and a DAB session needs
        # something to find there. Made only when first in view.
        self.dab = None
        # Band II likewise (simfm.py): made per station, only once in view.
        self.fm = None
        # Ships off the Ayrshire coast on AIS's two channels (simais.py).
        self.ais = None
        # Aircraft around Prestwick on 1090 MHz (simadsb.py).
        self.adsb = None
        # A DMR repeater on 70 cm likewise (simdmr.py).
        self.dmr = None
        if self.signals:
            from . import simdab
            if simdab.available():
                self.dab = simdab.DabEnsemble("11D")
                from .simfm import FmBand
                self.fm = FmBand()
                from .simais import AisFleet
                self.ais = AisFleet(t0=time.time())
                from .simadsb import AdsbAir
                self.adsb = AdsbAir(t0=time.time())
                from .simdmr import DmrBand
                self.dmr = DmrBand()
        self._init_loop()

    # -- set-up -------------------------------------------------------------
    def hour(self) -> float:
        if self.hour_cfg >= 0:
            return self.hour_cfg
        t = time.gmtime()
        return t.tm_hour + t.tm_min / 60

    def open(self) -> None:
        if self.opened:
            return
        self.t_epoch = time.time()
        self.t_wall0 = time.monotonic()
        self._noise_bank(0.0)
        self.opened = True
        self._arrive()

    def tx_full_w(self, hz: float) -> float:
        return 5.0 if hz < 30e6 else 0.0045

    def _bands_in_view(self) -> list[bandmod.Band]:
        lo, hi = self.rx_if - self.fs / 2, self.rx_if + self.fs / 2
        return [b for b in bandmod.BANDS if b.lo < hi and b.hi > lo]

    def _arrive(self):
        """Populate the bands now in view (on a worker in real time)."""
        if not self.signals:
            return
        for b in self._bands_in_view():
            with self.pop_lock:
                if b.name in self.pops or b.name in self.building:
                    continue
                self.building.add(b.name)
            if self.realtime:
                threading.Thread(target=self._build, args=(b,), name="sim-band", daemon=True).start()
            else:
                self._build(b)
        # Forget bands long out of view: each costs tens of MB of templates.
        with self.pop_lock:
            keep = {b.name for b in self._bands_in_view()}
            for name in [k for k in self.pops if k not in keep]:
                if len(self.pops) > 3:
                    del self.pops[name]

    def _build(self, b: bandmod.Band):
        # Each band's population depends only on simSeed and the band, not
        # on the order bands are visited in.
        rng = np.random.default_rng([self.seed, bandmod.NAMES.index(b.name)])
        try:
            stations = self._populate(b, rng)
        except Exception:  # noqa: BLE001 - a broken template costs a band's stations, not the sim
            stations = []
        for st in stations:
            st.src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)
        with self.pop_lock:
            self.pops[b.name] = stations
            self.building.discard(b.name)
            self.repeaters = [s for pop in self.pops.values() for s in pop if isinstance(s, Repeater)]

    def add_station(self, name: str, dial: float, template: np.ndarray, level_db: float) -> Station:
        """One more signal on the air: `template` complex baseband at 12 kHz
        (looped) heard on a USB dial of `dial`, at `level_db` dBFS. For the
        tests that put a known PSK station or SSTV picture through the
        engine, and for trying a decoder by hand."""
        st = Station(name, float(dial), np.asarray(template, np.complex64), level_db)
        st.src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)
        with self.pop_lock:
            self.extra.append(st)
        return st

    def _level(self, rng, lo, hi, strong=(-48.0, -38.0), p=0.12) -> float:
        return float(rng.uniform(*strong) if rng.random() < p else rng.uniform(lo, hi))

    def _spaced(self, rng, lo, hi, used, gap=2000.0, grid=100.0):
        best, best_gap = None, -1.0
        for _ in range(14):
            c = float(int(rng.uniform(lo, hi) // grid) * grid)
            g = min((abs(c - u) for u in used), default=gap)
            if g >= gap:
                return c
            if g > best_gap:
                best, best_gap = c, g
        return best

    def _populate(self, b: bandmod.Band, rng) -> list:
        act = activity(b.name, self.hour())
        out: list = []
        calls = list(CALLS)
        rng.shuffle(calls)
        ci = iter(calls * 3)
        segs = [s for s in plan.SEGMENTS if b.lo <= s.lo < b.hi]
        if b.hf:
            # SSB QSOs in the all-modes segments: two stations taking turns.
            phone = [s for s in segs if s.modes and "ssb" in s.modes and s.label.startswith("all modes")
                     or s.label == "60 m segment"]
            n_ssb = int(round((14 if b.name not in ("30m",) else 0) * act * rng.uniform(0.8, 1.2)))
            if b.name == "60m":
                n_ssb = min(n_ssb, 4)
            used: list[float] = []
            weights = np.array([s.hi - s.lo for s in phone]) if phone else np.zeros(0)
            for _ in range(n_ssb if phone else 0):
                s = phone[int(rng.choice(len(phone), p=weights / weights.sum()))]
                side = bandmod.natural_sideband(s.lo)
                lo_d, hi_d = (s.lo + 3000, s.hi) if side == "lsb" else (s.lo, s.hi - 3000)
                if hi_d <= lo_d:
                    continue
                dial = self._spaced(rng, lo_d, hi_d, used, gap=3000.0, grid=1000.0 if rng.random() < 0.6 else 500.0)
                used.append(dial)
                loop = float(rng.uniform(20, 32))
                pres = Presence(rng, (240.0, 720.0), (30.0, 150.0))
                level = self._level(rng, -64.0, -40.0, strong=(-36.0, -26.0))
                for talk, d in (((0.0, 0.5), 0.0), ((0.5, 1.0), rng.uniform(-30, 30))):
                    z = sg.voice(rng, loop, talk)
                    out.append(Station(f"SSB {dial / 1e6:.3f}", dial + d, lsb(z) if side == "lsb" else z,
                                       level + rng.uniform(-6, 6), presence=pres))
            # CW.
            cw = [s for s in segs if s.label == "CW"]
            for _ in range(int(round(9 * act * rng.uniform(0.7, 1.3))) if cw else 0):
                s = cw[0]
                a, c2 = next(ci), next(ci)
                dial = float(int(rng.uniform(s.lo + 2000, s.hi - 2000) // 10) * 10)
                wpm = float(rng.uniform(15, 30))
                text = f"CQ CQ DE {a} {a} K   {a} DE {c2} GM UR 599 599 TU {c2} K"
                out.append(Station(f"CW {a}", dial, sg.cw_station(rng, text, wpm, 40.0),
                                   self._level(rng, -80.0, -52.0, p=0.08),
                                   presence=Presence(rng, (60.0, 300.0), (60.0, 420.0))))
            if b.ft8:
                out.append(FT8Activity(rng, b.ft8, -60.0 + 8 * act + rng.uniform(-3, 3), 0.0))
            narrow = [s for s in segs if s.label.startswith("narrow digital")]
            if narrow and act > 0.2:
                s = narrow[0]
                for k in range(2):
                    # Real Varicode text (sg.psk_text), so the PSK modes and
                    # their several channels have something to copy, as the
                    # RTTY station below. psk_like's random draws are still
                    # made and dropped, and the call read without taking it
                    # from `ci`, so every other station is as it was.
                    rng.random(int(40.0 * 31.25) + 2)
                    p = calls[(len(calls) // 2 + 1 + k) % len(calls)]
                    out.append(Station(f"PSK31 {k}", s.lo + 0.5 * (s.hi - s.lo),
                                       sg.psk_text(f"CQ CQ DE {p} {p} K ", 40.0, 31.25, 600 + 900 * k,
                                                   (0.08 * k, 0.6 + 0.2 * k)),
                                       self._level(rng, -68.0, -52.0, p=0.05),
                                       presence=Presence(rng, (180.0, 600.0), (120.0, 900.0))))
                # Real ITA2 text (sg.rtty_text), so the RTTY mode and the
                # Decoders view have something to copy on every HF band. Its
                # random bits used to come from rng; the same draws are made
                # and dropped, and the call is read without taking it from
                # `ci`, so every other station of a seeded band is as it was.
                rng.integers(0, 2, int(40.0 * 45.45) + 1)
                r = calls[len(calls) // 2]
                out.append(Station("RTTY", s.lo + 0.75 * (s.hi - s.lo),
                                   sg.rtty_text(f"CQ TEST {r} {r} {r} TEST\n", 40.0, centre=1500.0),
                                   self._level(rng, -66.0, -52.0, p=0.05),
                                   presence=Presence(rng, (150.0, 480.0), (120.0, 720.0))))
            if b.name in ("20m", "17m", "15m", "12m", "10m"):
                ibp = {"20m": 0, "17m": 1, "15m": 2, "12m": 3, "10m": 4}[b.name]
                out.append(IbpBeacons(rng, ibp, plan.IBP[ibp], -66.0 + 14 * act))
            if b.name in ("80m", "40m"):
                f = float(int(rng.uniform(b.hi - 60_000, b.hi - 10_000) // 100) * 100)
                out.append(Station("carrier", f, np.ones(int(sg.RATE), np.complex64), -62.0))
            return out
        # VHF and up.
        beacons = [s for s in segs if s.kind == "beacon"]
        for s in beacons:
            for k in range(3 if b.name in ("2m", "70cm") else 1):
                f = float(int(rng.uniform(s.lo + 5000, s.hi - 5000) // 1000) * 1000)
                call = f"GB3V{chr(65 + k)}{chr(65 + int(rng.integers(0, 26)))}"
                text = f"{call} IO86HA  " + "T" * 6
                out.append(Station(f"beacon {call}", f, sg.cw_station(rng, text, 12.0, 40.0),
                                   self._level(rng, -86.0, -62.0, p=0.0)))
        weak = [s for s in segs if s.label in ("narrow band", "SSB & MGM")]
        if weak:
            s = weak[0]
            centre = {"2m": 144_300_000.0, "70cm": 432_200_000.0, "23cm": 1_296_200_000.0}.get(b.name, s.lo + 100_000)
            for _ in range(int(round(8 * act * rng.uniform(0.7, 1.3)))):
                dial = self._spaced(rng, centre - 20_000, centre + 60_000, [], grid=500.0)
                loop = float(rng.uniform(20, 30))
                pres = Presence(rng, (180.0, 600.0), (60.0, 400.0))
                level = self._level(rng, -72.0, -46.0, strong=(-40.0, -30.0))
                for talk in ((0.0, 0.5), (0.5, 1.0)):
                    out.append(Station(f"SSB {dial / 1e6:.3f}", dial, sg.voice(rng, loop, talk), level, presence=pres))
            cwseg = next((x for x in segs if x.label == "CW"), None)
            for _ in range(int(round(3 * act)) if cwseg else 0):
                a = next(ci)
                f = float(int(rng.uniform(cwseg.lo + 5000, cwseg.lo + 60_000) // 10) * 10)
                out.append(Station(f"CW {a}", f, sg.cw_station(rng, f"CQ CQ DE {a} {a} K", float(rng.uniform(14, 24)),
                                                               30.0), self._level(rng, -84.0, -60.0),
                                   presence=Presence(rng, (60.0, 240.0), (60.0, 480.0))))
        if b.ft8 and b.name in ("2m", "70cm", "4m", "23cm"):
            out.append(FT8Activity(rng, b.ft8, -72.0 + 8 * act, 0.0))
        # FM: the calling channel, simplex QSOs and repeaters.
        fm_call = next((f for f, lab, m in plan.CENTRES if m == "fm" and "calling" in lab and b.lo <= f <= b.hi), None)
        if fm_call:
            out.append(Station("FM calling", fm_call, fm_station(rng, 40.0, 0.0, talk=(0.05, 0.6)),
                               self._level(rng, -72.0, -46.0, strong=(-44.0, -34.0), p=0.3),
                               presence=Presence(rng, (90.0, 240.0), (60.0, 240.0))))
        simplex = [s for s in bandmod.SIMPLEX if b.lo <= s[1] <= b.hi]
        for name, lo, step, first, hi in simplex:
            nch = int(round((hi - lo) / step)) + 1
            for _ in range(int(round(4 * act)) + 1):
                ch = lo + step * int(rng.integers(0, nch))
                if abs(ch - (fm_call or 0)) < 1:
                    continue
                pres = Presence(rng, (240.0, 600.0), (60.0, 300.0))
                level = self._level(rng, -76.0, -46.0)
                for talk in ((0.0, 0.48), (0.5, 0.98)):
                    out.append(Station(f"FM {name}", ch, fm_station(rng, 36.0, 0.0, talk=talk), level, presence=pres))
        tones = [103.5, 94.8, 118.8, 77.0, 82.5, 67.0]
        k = 0
        for r in bandmod.REPEATERS:
            if not b.lo <= r.out_lo <= b.hi or r.name in ("DV",):
                continue
            nch = int(round((r.out_hi - r.out_lo) / r.step)) + 1
            for j in range(2 if r.name in ("RV", "RB") else 1):
                ch = r.out_lo + r.step * int(rng.integers(0, nch))
                tone = tones[(k + j) % len(tones)]
                call = f"GB3S{chr(73 + k)}{chr(65 + j)}"
                out.append(Repeater(rng, call, ch, r.shift, tone, toneburst=(j == 0),
                                    level_db=self._level(rng, -60.0, -40.0, p=0.0)))
            k += 1
        return out

    # -- the band's noise ----------------------------------------------------
    def _noise_density(self, f: np.ndarray, err: float) -> np.ndarray:
        b = bandmod.band_at(self.rx_if)
        band_db = BAND_NOISE.get(b.name if b else "", FLOOR_DB_HZ - 30)
        return np.full(len(f), 10 ** (FLOOR_DB_HZ / 10) + 10 ** (band_db / 10))

    # -- receive ------------------------------------------------------------
    def set_rx_converter(self, conv) -> None:
        self.rx_conv = conv

    def set_tx_converter(self, conv) -> None:
        self.tx_conv = conv

    def set_rx_if(self, hz: float) -> None:
        # rx_if is where the simulated air is centred: through a converter,
        # the air frequency of the IF the radio is tuned to.
        self.rx_if = float(hz) if self.rx_conv is None else self.rx_conv.air(float(hz))
        if self.opened:
            self._noise_bank(0.0)
            self._arrive()

    def _generate(self, m: int) -> np.ndarray:
        g = self.geo
        if self.rx_if != self.bank_if:
            self._noise_bank(0.0)
        hop = g.L // int(round(self.fs / sg.RATE))
        t_mid = (self.n + m * g.L / 2) / self.fs
        t_abs = self.t_epoch + self.n / self.fs
        feeds = []
        with self.pop_lock:
            stations = [s for pop in self.pops.values() for s in pop] + list(self.extra)
        keyed = self.tx_active
        for st in stations:
            st.src.freq = st.dl - self.rx_if
            if abs(st.src.freq) > self.fs * 0.5 - 10_000:
                continue
            if isinstance(st, FT8Activity):
                feeds.append((st.src, st.take(m * hop, t_abs)))
            elif isinstance(st, Repeater):
                feeds.append((st.src, st.take_at(m * hop, t_mid, keyed)))
            elif isinstance(st, IbpBeacons):
                feeds.append((st.src, st.take_at(m * hop, t_abs)))
            else:
                gain = st.presence.gain(t_mid) if st.presence is not None else 1.0
                if gain > 0:
                    feeds.append((st.src, st.take(m * hop, gain)))
        pick = self.rng.integers(0, len(self.bank), m)
        rot = np.array([1, 1j, -1, -1j], np.complex64)[self.rng.integers(0, 4, m)]
        extra = self.bank[pick] * rot[:, None]
        for extra_band in (self.fm, self.dmr):
            if extra_band is not None:
                feeds += extra_band.feeds(g, self.rx_if, m, background=self.realtime)
        y = self.syn.render(m, feeds, extra)
        b = bandmod.band_at(self.rx_if)
        rate = QRN.get(b.name if b else "", 0.0) * activity(b.name, self.hour()) if b else 0.0
        if rate:
            k = self.rng.poisson(rate * len(y) / self.fs)
            if k:
                at = self.rng.integers(0, len(y) - 3, k)
                amp = (self.rng.uniform(0.05, 0.4, k) * np.exp(2j * np.pi * self.rng.random(k))).astype(np.complex64)
                for j in range(3):
                    y[at + j] += amp * np.float32(1.0 - 0.3 * j)
        dab = self.dab
        if dab is not None and dab.in_view(self.rx_if, self.fs):
            dab.prepare(self.fs, background=self.realtime)
            z = dab.take(self.n, len(y), self.fs, self.rx_if)
            if z is not None:
                y += z
        for air in (self.ais, self.adsb):
            if air is not None and air.in_view(self.rx_if, self.fs):
                z = air.take(self.n, len(y), self.fs, self.rx_if)
                if z is not None:
                    y += z
        self._loopback(y, 0.0)
        self.n += m * g.L
        return y

    def _loopback_amp(self, tx_gain: float) -> float:
        return 10 ** (OWN_DB / 20) * 10 ** (tx_gain / 20)

    def _loopback_shift(self, tx_lo: float, err: float) -> float:
        return tx_lo - self.rx_if

    # -- transmit -------------------------------------------------------------
    def set_drive(self, x: float) -> None:
        self.drive = max(0.0, min(1.0, float(x)))
        super().set_tx_gain(-89.75 if self.drive <= 0 else 20 * math.log10(self.drive))

    def tx_start(self) -> None:
        super().tx_start()
        self.tx_listen = {}            # per repeater: what it has heard of this over

    def tx_stop(self) -> None:
        super().tx_stop()
        self.tx_listen = None
        self.fwd = 0.0

    def set_tx_freq(self, hz: float) -> None:
        # tx_lo is the air frequency (what the loopback and the repeaters
        # hear); tx_radio the radio's own, for its output figure.
        self.tx_radio = float(hz)
        super().set_tx_freq(float(hz) if self.tx_conv is None else self.tx_conv.air(float(hz), tx=True))

    def write(self, iq: np.ndarray) -> None:
        iq = np.asarray(iq, np.complex64)
        if self.tx_conv is not None and self.tx_conv.inverted:
            iq = np.conj(iq)             # the converter mirrors what the radio sends
        super().write(iq)
        pk = float(np.max(np.abs(iq))) if len(iq) else 0.0
        self.last_peak = pk
        f_lo = self.tx_lo if self.tx_lo is not None else 0.0
        full = self.tx_full_w(self.tx_radio or f_lo)
        self.fwd = full * self.drive ** 2 * min(1.0, pk) ** 2
        self.temp = min(70.0, self.temp + 0.02 * len(iq) / self.fs * (self.fwd / max(1e-9, full)) * 10)
        self._listen(iq, f_lo)

    def _listen(self, iq: np.ndarray, f_lo: float):
        """What a repeater whose input we are on hears of us: our audio, its
        CTCSS tone, a toneburst."""
        st = self.tx_listen
        if st is None:
            return
        n = len(iq)
        d = int(round(self.fs / 24_000))
        i0 = self.tx_written - n
        t = self.n / self.fs
        for r in list(self.repeaters):
            off = r.f_in - f_lo
            if abs(off) > self.fs / 2:
                continue
            # Our signal, if it is on this input, mixed to DC and boxcar-
            # decimated to 24 kS/s: anything else is attenuated away.
            ph = (-2 * np.pi * off / self.fs) * (i0 + np.arange(n - n % d))
            z = (iq[: n - n % d] * np.exp(1j * ph).astype(np.complex64)).reshape(-1, d).mean(axis=1)
            if np.mean(np.abs(z) ** 2) < 1e-4:
                continue
            a = fmdsp.discriminate(z, 24_000.0, 2500.0)
            lis = st.setdefault(r.call, {"det": fmdsp.CtcssDetector(24_000.0), "buf": np.zeros(0, np.float32),
                                         "burst": False})
            lis["det"].push(a)
            lis["buf"] = np.concatenate([lis["buf"], a])[-12_000:]
            if len(lis["buf"]) >= 12_000 and not lis["burst"]:
                A = np.abs(np.fft.rfft(lis["buf"] * np.hanning(12_000)))
                fr = np.fft.rfftfreq(12_000, 1 / 24_000)
                lis["burst"] = bool(A[np.argmin(abs(fr - 1750))] > 8 * np.median(A[(fr > 300) & (fr < 3000)]))
            r.heard_tone = lis["det"].tone
            # Relay: our audio, re-modulated with the repeater's own tone, at 12 kHz.
            z12 = fmdsp.modulate(np.clip(a[::2], -1, 1) * 0.9, sg.RATE, 2500.0, r.tone)
            if r.access(lis["det"].tone, lis["burst"], t, True) or t < r.open_until:
                r.push_relay(z12)

    def telemetry(self) -> dict:
        if not self.tx_active:
            return {"temp": round(self.temp, 1)}
        gamma = (self.ant_swr - 1) / (self.ant_swr + 1)
        return {"fwd": self.fwd, "rev": self.fwd * gamma ** 2, "temp": round(self.temp, 1)}

    def status(self) -> dict:
        with self.pop_lock:
            n = sum(len(p) for p in self.pops.values())
            bands_ = sorted(self.pops)
        return {"kind": "sim", "fs": self.fs, "rxIf": self.rx_if, "txLo": self.tx_lo, "txActive": self.tx_active,
                "underruns": self.underruns, "stations": n, "bands": bands_, "hourUtc": round(self.hour(), 2),
                "seconds": round(self.n / self.fs, 1),
                "repeaters": [{"call": r.call, "out": r.dl, "in": r.f_in, "tone": r.tone, "opened": r.opened}
                              for r in self.repeaters]}

    def read(self, n: int) -> np.ndarray:
        if not self.opened:
            raise DeviceError("The simulator is not open")
        y = super().read(n)
        if self.rx_conv is not None and self.rx_conv.inverted:
            y = np.conj(y)               # the radio sees the air mirrored
        return y
