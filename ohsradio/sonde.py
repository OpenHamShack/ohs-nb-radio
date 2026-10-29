"""Radiosondes on a map: Radio's sonde receive (Brian, 29/10/2026;
docs/SERVER-API.md "Radiosondes").

    radio.sonde.join(client)          # POST api/sonde/session?client=: start, or keep alive; raises Refused
    radio.sonde.leave(client)         # DELETE api/sonde/session?client=
    radio.sonde.end("stopped")        # DELETE api/sonde/session?all=1, or the radio stopping
    radio.sonde.view()                # the session (also `sonde` in the state)
    radio.sonde.sondes()              # GET api/sonde/sondes
    radio.sonde.table.sonde(serial)   # GET api/sonde/sondes/{serial}, with its track and profile
    radio.sonde.launches()            # GET api/sonde/launches
    radio.sonde.tick(now)             # the supervisor, ten times a second

**Shaped exactly like Ships (ais.py)**, as Brian asked: the receiver is
used only while a client holds the session, renewed at least every
CLIENT_LEASE_S (30 s) or vouched for by client presence ("sonde" in its
holds); no linger after the last client goes (LINGER_S, 0); the moment
presence says the client has gone the hold is released (Server.
client_gone); the receiver goes back exactly as it was - dial, mode,
repeater offset, centre (Engine.hold_receiver / release_receiver). While
it holds the receiver a tune or a key-up is refused with a sentence
saying why; background decoder sessions pin the span and refuse it
`span_pinned` unless the caller says to stop them (`dropSessions`).

**Scan, then one sonde at a time.** 400-406 MHz is wider than the
receiver, so the scan hops across it (`hops`: as many receiver spans as
it takes, each used to USABLE of the rate, the receiver's own DC spike
DC_GUARD_HZ either side left out, and every other pass shifted by
ALT_SHIFT_HZ so nothing stays in a spike's shadow). At each hop the
power spectrum is averaged over SCAN_DWELL_S in BIN_HZ bins and the
carriers SNR_DB above the median are the candidates, rounded to the 10
kHz channel grid every radiosonde uses - auto_rx's own rtl_power step
(800 Hz bins, 10 dB, 10 kHz), done here in Python because the receiver
is ours, not an rtl_power's. This is the only part of finding a sonde
written here, and the brief allows exactly this much. Each candidate,
strongest first, then gets DETECT_S of its channel through auto_rx's
`dft_detect`, which says which kind of sonde it is (or none). The first
that is a kind Radio decodes is **locked on**: the receiver's centre
moves TRACK_OFFSET_HZ above it (the dial on the sonde itself) and its
channel goes through auto_rx's decoding chain until no frame has come for
RX_TIMEOUT_S (auto_rx's rx_timeout), then the scan resumes. A sonde that
has landed and kept transmitting is let go after LANDED_LEAVE_FRAMES
frames on the ground, and an encrypted one (an RS41-SGM) at once; either's
channel is passed over for BLOCK_S, so the scan finds the next. Other
sondes are never decoded at the same time: the list shows each as it was
last heard.

**Decoding is radiosonde_auto_rx's**, never Radio's (projecthorus, GPL-3,
pinned at v1.9.0, built into the image by store/radio/Containerfile):
the channel is cut from the receiver's IQ (Ddc), handed as 16-bit IQ at
the rate each decoder wants to `iq_dec` (DC removal), then David Rowe's
`fsk_demod`, then the sonde's own demodulator with `--softin --json`,
with exactly the options auto_rx's decode.py gives each kind in its
fsk_demod chain (CHAINS, copied from v1.9.0's
generate_decoder_command_experimental, the chain auto_rx uses by default
for every kind listed). The decoders' JSON lines are read as auto_rx's
handle_decoder_line reads them (required fields, the version they were
built for, the type and serial each kind spells its own way); no
demodulation, framing or error correction is done here. RS92s (their GPS
needs an ephemeris from the internet) and the rarer kinds auto_rx decodes
another way are found and named by the scan but not decoded.

**The table** (SondeTable) is keyed by serial: where each sonde last was,
its climb, heading and speed, its temperature, humidity, pressure and
battery, its phase (ascent, descent, landed), where it burst and where it
landed or will land, a track and a profile of the atmosphere it measured
on the way. Kept KEEP_S (24 hours) after it was last heard, LANDED_KEEP_S
(7 days) once it has landed, in the data folder (`sonde/sondes.json`), and
survives a restart. Every change bumps `rev`; the `sonde` feed on
api/events carries each change.

**Predictions.** While a sonde is being decoded and in the air, its burst
(during the ascent) and landing are estimated: SondeHub's Tawhiri
predictor when Radio has internet and `sondeOnline` is on (sondehub.py),
otherwise a simple ballistic estimate here (`ballistic`: the present
climb to the burst altitude, a parachute's fall through NASA's simple
atmosphere, the present drift all the way). Either is marked `"predicted":
true` on the burst; the burst seen (the highest point before a descent)
is `"predicted": false`. `landing` is the estimate until the phase is
`landed`, then where it came down.

**SondeHub** (sondehub.py): every frame decoded off the air is uploaded
as auto_rx uploads it, under the station's callsign and its locator's
centre, unless `sondeHubUpload` is off; nothing the simulator makes is
ever uploaded.
"""
from __future__ import annotations

import json
import logging
import math
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np

from ohscore.countries import distance_bearing, locator_position
from ohscore.decoders import Refused, sessions_text
from ohscore.dsp.fir import lowpass
from ohscore.dsp.resample import Resampler

from ohsradio import sondehub
from ohsradio.i18n import _

log = logging.getLogger("ohsradio.sonde")

SID = "sonde"
BAND_LO, BAND_HI = 400_000_000.0, 406_000_000.0
CLIENT_LEASE_S = 30.0
LINGER_S = 0.0            # no linger (ais.py's docstring)
CLIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_CLIENTS = 32
# The receiver must give each hop room for a channel either side of DC.
MIN_RATE = 240_000.0
USABLE = 0.45             # of fs/2 either side of the centre, inside the receiver's own filter's edge
DC_GUARD_HZ = 25_000.0    # the spike, and a 10 kHz-wide sonde beside it, are left out
ALT_SHIFT_HZ = 60_000.0
EDGE_HZ = 15_000.0        # a candidate needs its whole channel inside the hop
BIN_HZ = 800.0            # auto_rx's search_step
SNR_DB = 10.0             # auto_rx's snr_threshold
GRID_HZ = 10_000.0        # auto_rx's quantization: every sonde channel is on it
MAX_PEAKS = 10            # auto_rx's max_peaks
SCAN_DWELL_S = 5.0
DETECT_S = 5              # auto_rx's detect_dwell_time
DETECT_RATE = 48_000      # dft_detect's IQ rate for 400 MHz sondes
TRACK_OFFSET_HZ = 50_000.0
RX_TIMEOUT_S = 120.0      # auto_rx's rx_timeout
LANDED_LEAVE_FRAMES = 300
BLOCK_S = 3600.0          # auto_rx's temporary_block_time, an hour
QUEUE_BLOCKS = 64
KEEP_S = 24 * 3600.0
LANDED_KEEP_S = 7 * 24 * 3600.0
TRACK_POINTS = 3000
TRACK_MIN_S = 10.0         # a flight is ~900 points: every sonde's track is in each api/sonde/sondes
PROFILE_POINTS = 1500
PROFILE_STEP_M = 50.0
DESCENT_MS = 1.5          # falling faster than this...
DESCENT_FRAMES = 3        # ...for this many frames, from DESCENT_DROP_M below the highest, is a descent
DESCENT_DROP_M = 100.0
LANDED_CLIMB_MS = 1.0
LANDED_SPEED_MS = 1.0
LANDED_FRAMES = 10
PREDICT_EVERY_S = 30.0    # the ballistic estimate; Tawhiri's own pace is sondehub.PREDICT_EVERY_S
SAVE_S = 30.0
EXPIRE_EVERY_S = 10.0
REMOVED_KEPT = 2000
BIN_DIR = os.environ.get("OHS_SONDE_BIN", "/opt/shack-radio/sonde")
# What the decoders were built as (-DVER_JSN_STR, store/radio/Containerfile):
# auto_rx refuses a decoder line from any other build, and so does this.
AUTO_RX_VERSION = "1.9.0"
REQUIRED = ("frame", "id", "datetime", "lat", "lon", "alt", "version")
MAX_ALT_M = 50_000.0      # auto_rx's max_altitude
TIME_LIMIT_S = 3 * 3600.0  # auto_rx's sonde_time_threshold

# Each kind's chain, from auto_rx v1.9.0 decode.py
# (generate_decoder_command_experimental): the IQ rate, fsk_demod's
# options and the decoder's command line, word for word.
CHAINS = {
    "RS41": (48_000, 4800, ["-b", "-5000", "-u", "5000", "-s", "--mask", "5000", "--nsym=300", "-p", "5",
                            "--stats=5"],
             ["rs41mod", "--ptu2", "--json", "--jsnsubfrm1", "--softin", "-i"]),
    "DFM": (50_000, 2500, ["-b", "-5000", "-u", "5000", "-s", "-i", "--stats=5"],
            ["dfm09mod", "-vv", "--ecc", "--json", "--dist", "--auto", "--softin"]),
    "M10": (48_000, 9600, ["-b", "-10000", "-u", "10000", "-s", "-p", "5", "--stats=5"],
            ["m10m20mod", "--json", "--ptu", "-vvv", "--softin", "-i"]),
    "LMS6": (48_000, 4800, ["-b", "-10000", "-u", "10000", "-s", "--stats=5"],
             ["lms6Xmod", "--json", "--softin", "--vit2", "-i"]),
    "IMET5": (48_000, 4800, ["-b", "-10000", "-u", "10000", "-s", "--stats=5"],
              ["imet54mod", "--ecc", "--json", "--softin", "-i", "--ptu"]),
    "MEISEI": (48_000, 2400, ["-s", "-b", "-15000", "-u", "15000", "--stats=5"],
               ["meisei100mod", "--softin", "--json", "--ptu", "--ecc"]),
}
CHAINS["M20"] = CHAINS["M10"]
PROGRAMS = ("iq_dec", "fsk_demod", "dft_detect", "rs41mod", "dfm09mod", "m10m20mod", "lms6Xmod", "imet54mod",
            "meisei100mod")
# dft_detect's names (auto_rx scan.py parse_dft_detect_output) to the
# chains above, or to a kind found but not decoded here.
DETECTED = (("RS41", "RS41"), ("RS92", "RS92"), ("DFM", "DFM"), ("M10", "M10"), ("M20", "M20"),
            ("IMET4", "IMET"), ("IMET1", "IMET"), ("IMETafsk", "IMET1"), ("IMET5", "IMET5"), ("LMS6", "LMS6"),
            ("C34C50", "SRSC50"), ("MRZ", "MRZ"), ("MK2LMS", "MK2LMS"), ("MEISEI", "MEISEI"),
            ("MTS01", "MTS01"), ("WXR301", "WXR301"), ("WXRPN9", "WXRPN9"), ("RD94RD41", "RD94RD41"),
            ("CF6GTH", "CF6GTH"))
CONTRACT = ("serial", "type", "freqHz", "lat", "lon", "altM", "climbMs", "headingDeg", "speedKmh", "tempC",
            "humidity", "pressureHpa", "batteryV", "frame", "lastHeard", "phase", "burst", "landing")


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# -- the scan ------------------------------------------------------------------
def hops(fs: float, shifted: bool = False) -> list[float]:
    """The receiver centres that cover 400-406 MHz at rate `fs` (module
    docstring); `shifted` for the other pass's."""
    half = USABLE * fs - EDGE_HZ
    width = 2.0 * half
    n = max(1, math.ceil((BAND_HI - BAND_LO) / width))
    step = (BAND_HI - BAND_LO) / n
    return [BAND_LO + step * (i + 0.5) + (ALT_SHIFT_HZ if shifted else 0.0) for i in range(n)]


def find_peaks(power: np.ndarray, freqs: np.ndarray, centre: float, fs: float,
               blocked=lambda f: False) -> list[tuple[float, float]]:
    """Candidates in one hop's averaged spectrum (`power`, linear, at
    absolute `freqs`): [(channel Hz, SNR dB)], strongest first, at most
    MAX_PEAKS, as auto_rx's scan finds them (module docstring)."""
    off = freqs - centre
    usable = (np.abs(off) <= USABLE * fs - EDGE_HZ) & (np.abs(off) >= DC_GUARD_HZ) \
        & (freqs >= BAND_LO) & (freqs <= BAND_HI)
    if not usable.any():
        return []
    db = 10.0 * np.log10(np.maximum(power, 1e-30))
    noise = float(np.median(db[usable]))
    hot = usable & (db > noise + SNR_DB)
    loc = np.zeros_like(hot)
    loc[1:-1] = hot[1:-1] & (db[1:-1] >= db[:-2]) & (db[1:-1] >= db[2:])
    best: dict[float, float] = {}
    for i in np.flatnonzero(loc):
        q = round(float(freqs[i]) / GRID_HZ) * GRID_HZ
        best[q] = max(best.get(q, -1e9), float(db[i]) - noise)
    # One sonde's two tones can round to neighbouring channels: the weaker
    # neighbour of a stronger one is the same signal.
    keep = [(q, s) for q, s in best.items()
            if not any(abs(q2 - q) <= GRID_HZ and s2 > s for q2, s2 in best.items())]
    keep = [(q, s) for q, s in keep if not blocked(q)]
    keep.sort(key=lambda p: -p[1])
    return keep[:MAX_PEAKS]


def parse_detect(out: str) -> tuple[str | None, float]:
    """dft_detect's line ("RS41: 0.9835 , -232.2Hz", or "TYPE: score") as
    (kind, offset Hz), auto_rx's parse_dft_detect_output; (None, 0) for
    nothing found. The score's sign is the signal's polarity: auto_rx
    ignores it except for the four kinds it decodes only one way up (MRZ,
    MK2LMS, MEISEI, MTS01), and so does this. An M20 reads -0.98 on
    auto_rx's own recording of one."""
    line = (out or "").strip().splitlines()
    if not line or ":" not in line[-1]:
        return None, 0.0
    kind, _, rest = line[-1].partition(":")
    try:
        if "," in rest:
            score = float(rest.split(",")[0])
            offset = float(rest.split(",")[1].split("Hz")[0])
        else:
            score, offset = float(rest), 0.0
    except ValueError:
        return None, 0.0
    for tag, name in DETECTED:
        if tag in kind:
            return (None if score < 0 and name in ("MRZ", "MK2LMS", "MEISEI", "MTS01") else name), offset
    return None, 0.0


class Ddc:
    """One channel cut from the receiver's IQ: mixed to DC, filtered and
    decimated by a whole number to at least four times `out_rate`
    (polyphase, as matrix products), then resampled exactly to `out_rate`
    (dsp.Resampler, I and Q apart). Signal processing on Radio's own
    samples - the receiver's job - never a sonde's demodulation."""

    def __init__(self, fs: float, offset_hz: float, out_rate: int, taps_per_phase: int = 12):
        self.fs, self.offset, self.out_rate = float(fs), float(offset_hz), int(out_rate)
        self.d = max(1, int(self.fs // (4 * out_rate)))
        mid = self.fs / self.d
        self.k = taps_per_phase
        h = lowpass(0.25 * mid, self.fs, self.k * self.d, 70.0).astype(np.float32)
        # Rows are the polyphase branches, newest sample last.
        self.h = h[::-1].reshape(self.k, self.d).copy()
        self.hist = np.zeros((self.k - 1) * self.d, np.complex64)
        self.rem = np.zeros(0, np.complex64)
        self.phase = 0.0
        ratio = Fraction(int(round(out_rate * self.d)), int(round(self.fs))).limit_denominator(4000)
        self.re = Resampler(ratio.numerator, ratio.denominator)
        self.im = Resampler(ratio.numerator, ratio.denominator)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        w = -2.0 * math.pi * self.offset / self.fs
        mixed = np.asarray(x, np.complex64) * np.exp(1j * (self.phase + w * np.arange(n))).astype(np.complex64)
        self.phase = (self.phase + w * n) % (2.0 * math.pi)
        buf = np.concatenate([self.rem, mixed])
        whole = len(buf) // self.d * self.d
        self.rem = buf[whole:]
        if whole == 0:
            return np.zeros(0, np.complex64)
        full = np.concatenate([self.hist, buf[:whole]])
        rows = full.reshape(-1, self.d)                # one row a decimated sample
        m = rows.shape[0] - (self.k - 1)
        y = np.zeros(m, np.complex64)
        for j in range(self.k):
            y += rows[j:j + m] @ self.h[j]
        self.hist = full[-(self.k - 1) * self.d:] if self.k > 1 else self.hist
        return (self.re(y.real) + 1j * self.im(y.imag)).astype(np.complex64)


class Cs16:
    """Complex samples to interleaved 16-bit IQ, as rtl_fm -M raw gives
    auto_rx: a slow gain holding the channel's RMS near TARGET, so a weak
    sonde is not lost in the bottom bits nor a strong one clipped. Not
    near full scale: iq_dec casts its filtered output to 16 bits without
    clipping, so it wraps; on auto_rx's own RS41 recording an RMS of 3000
    decoded nothing and 300-900 every frame (29/10/2026). 400 is that with
    room for a sonde coming closer between two of the gain's steps."""
    TARGET = 400.0

    def __init__(self):
        self.gain = None

    def __call__(self, y: np.ndarray) -> bytes:
        if len(y) == 0:
            return b""
        rms = float(np.sqrt(np.mean(np.abs(y) ** 2))) + 1e-12
        want = self.TARGET / rms
        self.gain = want if self.gain is None else self.gain * 0.8 + want * 0.2
        z = np.empty(2 * len(y), np.float32)
        z[0::2], z[1::2] = y.real * self.gain, y.imag * self.gain
        return np.clip(z, -32767, 32767).astype("<i2").tobytes()


class Programs:
    """auto_rx's binaries, where the image puts them (BIN_DIR)."""
    simulated = False

    def __init__(self, folder: str = BIN_DIR):
        self.folder = Path(folder)
        self.env: dict = {}

    def available(self) -> bool:
        return all(os.access(self.folder / p, os.X_OK) for p in PROGRAMS)

    def argv(self, name: str, *args: str) -> list[str]:
        return [str(self.folder / name), *args]


class Chain:
    """Processes piped one into the next (auto_rx's shell pipeline, without
    the shell): IQ written to the first, the last one's lines read."""

    def __init__(self, argvs: list[list[str]], env: dict):
        self.procs: list[subprocess.Popen] = []
        prev = None
        try:
            for i, argv in enumerate(argvs):
                p = subprocess.Popen(argv, stdin=subprocess.PIPE if prev is None else prev.stdout,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                     start_new_session=True, close_fds=True)
                if prev is not None:
                    prev.stdout.close()        # the next process owns it now
                self.procs.append(p)
                prev = p
        except OSError:
            self.kill()
            raise
        self.stdin = self.procs[0].stdin
        self.stdout = self.procs[-1].stdout

    def write(self, data: bytes) -> bool:
        try:
            self.stdin.write(data)
            self.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def close_input(self) -> None:
        try:
            self.stdin.close()
        except OSError:
            pass

    def kill(self) -> None:
        for p in self.procs:
            try:
                os.killpg(p.pid, 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        for p in self.procs:
            try:
                p.wait(2.0)
            except subprocess.TimeoutExpired:
                pass
            for f in (p.stdin, p.stdout):
                try:
                    if f is not None:
                        f.close()
                except OSError:
                    pass


# -- a decoder's line --------------------------------------------------------------
def parse_datetime(s, now: float) -> float | None:
    """A decoder's `datetime`: a full ISO time, or only "HH:MM:SS[.s]Z"
    (LMS6, iMet-54 and others), put on the day that brings it nearest
    `now`, as auto_rx's fix_datetime does."""
    s = str(s or "").strip()
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        h, m, sec = s.rstrip("Z").split(":")
        day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        t = day.timestamp() + int(h) * 3600 + int(m) * 60 + float(sec)
        if t - now > 43200:
            t -= 86400
        elif now - t > 43200:
            t += 86400
        return t
    except (ValueError, TypeError):
        return None


def _num(v, ok=lambda x: True):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and ok(x) else None


def reading(tel: dict, kind: str, freq_hz: float, now: float) -> dict | None:
    """One decoder line (its JSON) from the `kind` chain on `freq_hz` as
    a reading: the contract's fields and what SondeHub's upload needs,
    following auto_rx's handle_decoder_line and its SondeHub reformat for
    the type, subtype, serial and units. None for a line auto_rx would
    not take: a field missing, another build's decoder, no time, or one
    its telemetry_filter refuses - no GPS fix (0, 0, or under 4
    satellites), above MAX_ALT_M, a time more than TIME_LIMIT_S from now,
    or a serial not yet decoded (a DFM's or Meisei's "xxxxxxxx", a
    Vaisala serial not of its form)."""
    if not isinstance(tel, dict) or any(f not in tel for f in REQUIRED):
        return None
    if str(tel.get("version")) != AUTO_RX_VERSION:
        return None
    encrypted = bool(tel.get("encrypted"))
    t = now if encrypted else parse_datetime(tel.get("datetime"), now)
    if t is None:
        return None
    sid = str(tel.get("id") or "")
    kind_now = str(tel.get("type") or kind) if kind in ("M10", "M20") else kind
    sub = tel.get("subtype")
    dfmcode = None
    if sub:
        if kind == "RS41":
            ttype = str(sub)
        elif kind == "DFM":
            if ":" in str(sub):
                dfmcode, ttype = str(sub).split(":", 1)
                sub = ttype
            else:
                ttype = sub = "DFM"
        elif kind == "MEISEI":
            ttype = str(sub)
        else:
            ttype = kind_now
    else:
        ttype = kind_now
    if encrypted:
        sub = f"{sub}-Encrypted" if sub else None

    def tail(sep="-"):
        return sid.split(sep, 1)[1] if sep in sid else sid

    shsub = None
    if ttype.startswith("RS41"):
        man, sh, serial, shsub = "Vaisala", "RS41", sid, sub
        shown = str(sub or "RS41")
    elif ttype.startswith("DFM"):
        man, sh, serial, shsub = "Graw", "DFM", tail(), ttype
        shown = ttype
    elif ttype.startswith("M10") or ttype.startswith("M20"):
        man, sh, serial = "Meteomodem", ttype, sid[4:]
        shown = ttype
    elif ttype == "LMS6":
        man, sh, serial, shsub = "Lockheed Martin", "LMS6-403", tail(), sub
        shown = "LMS6-403"
    elif ttype == "IMET5":
        man, sh, serial = "Intermet Systems", str(sub or "iMet-5x"), tail()
        shsub = sub
        shown = sh
    elif ttype in ("IMS100", "RS11G"):
        man, sh, serial = "Meisei", {"IMS100": "iMS-100", "RS11G": "RS-11G"}[ttype], tail()
        shown = sh
    else:
        return None
    if not serial:
        return None
    if "x" in serial or (sh in ("RS41", "RS92") and not re.match(r"[C-Z]\d{7}", serial)):
        return None
    lat, lon, alt = _num(tel.get("lat"), lambda x: -90 <= x <= 90), _num(tel.get("lon"), lambda x: -180 <= x <= 180), \
        _num(tel.get("alt"), lambda x: -1000 <= x <= MAX_ALT_M)
    sats = _num(tel.get("sats"))
    if encrypted:
        # An RS41-SGM: its position is not ours to read. Listed by serial
        # (auto_rx shows it too), never mapped or uploaded, and let go.
        lat = lon = alt = None
    elif lat is None or lon is None or alt is None or (lat == 0.0 and lon == 0.0) or (sats is not None and sats < 4):
        return None
    elif abs(now - t) > TIME_LIMIT_S:
        return None
    vel_h = _num(tel.get("vel_h"), lambda x: x > -9999)
    heading = _num(tel.get("heading"), lambda x: x > -9999)
    rd = {"serial": serial, "type": shown, "manufacturer": man, "shType": sh, "shSubtype": shsub,
          "kind": kind, "t": t, "datetimeSh": datetime.fromtimestamp(t, timezone.utc).strftime(
              "%Y-%m-%dT%H:%M:%S.%fZ"),
          "frame": int(_num(tel.get("frame")) or 0), "lat": lat, "lon": lon, "altM": alt,
          "climbMs": _num(tel.get("vel_v"), lambda x: x > -9999), "velH": vel_h,
          "speedKmh": round(vel_h * 3.6, 1) if vel_h is not None else None,
          "headingDeg": heading, "tempC": _num(tel.get("temp"), lambda x: x > -273),
          "humidity": _num(tel.get("humidity"), lambda x: x >= 0),
          "pressureHpa": _num(tel.get("pressure"), lambda x: x >= 0),
          "batteryV": _num(tel.get("batt"), lambda x: x >= 0), "sats": tel.get("sats"),
          "burstTimer": tel.get("bt"), "xdata": tel.get("aux"), "dfmcode": dfmcode,
          "refPosition": tel.get("ref_position"), "refDatetime": tel.get("ref_datetime"),
          "rs41Mainboard": tel.get("rs41_mainboard"),
          "rs41MainboardFw": str(tel["rs41_mainboard_fw"]) if "rs41_mainboard_fw" in tel else None,
          "rs41Subframe": tel.get("rs41_calconf51x16"), "encrypted": encrypted,
          "freqHz": float(freq_hz) if freq_hz else None,
          "txFreqHz": _num(tel.get("tx_frequency"), lambda x: x > 0)}
    if rd["txFreqHz"] is not None:
        rd["txFreqHz"] *= 1e3                 # kHz, as auto_rx reads it
    return rd


# -- predictions -------------------------------------------------------------------
def _destination(lat: float, lon: float, bearing_deg: float, km: float) -> tuple[float, float]:
    r = km / 6371.0088
    b, p1, l1 = math.radians(bearing_deg), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(r) + math.cos(p1) * math.sin(r) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(r) * math.cos(p1), math.cos(r) - math.sin(p1) * math.sin(p2))
    return round(math.degrees(p2), 5), round(((math.degrees(l2) + 540) % 360) - 180, 5)


def fall_time(alt_m: float, ground_m: float, sea_level_ms: float) -> float:
    """Seconds for a parachute with sea-level descent rate `sea_level_ms`
    to fall from `alt_m` to `ground_m` (speed as 1/sqrt(density))."""
    t, z, step = 0.0, float(alt_m), 100.0
    while z > ground_m:
        dz = min(step, z - ground_m)
        v = sea_level_ms * (1.22 / sondehub.air_density(z - dz / 2)) ** 0.5
        t += dz / max(v, 0.1)
        z -= dz
    return t


def ballistic(v: dict, now: float, burst_alt: float, descent_ms: float, ground_m: float = 0.0) -> dict | None:
    """The simple estimate (module docstring): {"burst", "landing"} from a
    sonde's last reading, or None without a position and climb."""
    lat, lon, alt, climb = v.get("lat"), v.get("lon"), v.get("altM"), v.get("climbMs")
    if lat is None or alt is None or climb is None:
        return None
    speed = (v.get("speedKmh") or 0.0) / 3.6
    heading = v.get("headingDeg") or 0.0
    burst = None
    if v.get("phase") == "ascent":
        if climb < 0.5:
            return None                       # on the pad, or floating: no flight to predict
        top = max(burst_alt, alt + 100.0)
        up = (top - alt) / climb
        blat, blon = _destination(lat, lon, heading, speed * up / 1000.0)
        burst = {"lat": blat, "lon": blon, "altM": round(top), "predicted": True}
        down = fall_time(top, ground_m, descent_ms)
        llat, llon = _destination(blat, blon, heading, speed * down / 1000.0)
        return {"burst": burst, "landing": {"lat": llat, "lon": llon, "utc": _iso(now + up + down)}}
    rate = sondehub.sea_level_descent(climb, alt) if climb < -0.5 else descent_ms
    down = fall_time(alt, ground_m, rate)
    llat, llon = _destination(lat, lon, heading, speed * down / 1000.0)
    return {"burst": None, "landing": {"lat": llat, "lon": llon, "utc": _iso(now + down)}}


def tawhiri_query(v: dict, now: float, burst_alt: float, descent_ms: float) -> dict | None:
    """Tawhiri's parameters for a sonde in flight (sondehub.py), as the
    SondeHub tracker's predictor asks: a descending sonde 'bursts' a metre
    above where it is, at its sea-level descent rate."""
    lat, lon, alt, climb = v.get("lat"), v.get("lon"), v.get("altM"), v.get("climbMs")
    if lat is None or alt is None or climb is None:
        return None
    q = {"launch_latitude": round(lat, 5), "launch_longitude": round(lon % 360.0, 5),
         "launch_datetime": _iso(now), "launch_altitude": round(max(alt, 0.0), 1)}
    if v.get("phase") == "ascent":
        if climb < 0.5:
            return None
        q.update(ascent_rate=round(climb, 2), burst_altitude=round(max(burst_alt, alt + 100.0)),
                 descent_rate=round(descent_ms, 2))
    else:
        rate = sondehub.sea_level_descent(climb, alt) if climb < -0.5 else descent_ms
        q.update(ascent_rate=5.0, burst_altitude=round(max(alt, 0.0) + 1.0, 1), descent_rate=round(rate, 2))
    return q


# -- the table ---------------------------------------------------------------------
class SondeTable:
    """Every radiosonde decoded, by serial (module docstring). Thread-safe:
    readings arrive on the supervisor's thread, clients read on the
    server's."""

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()
        self.s: dict[str, dict] = {}
        self.tracks: dict[str, deque] = {}        # serial -> [t, lat, lon, altM]
        self.profiles: dict[str, list] = {}       # serial -> [altM, tempC, humidity, pressureHpa, windKmh, windDirDeg]
        self.rev = 0
        self.removed: deque = deque(maxlen=REMOVED_KEPT)
        self.dirty = False
        self.saved_at = 0.0
        self.load()
        self.expire(time.time())

    @staticmethod
    def public(v: dict) -> dict:
        return {k: v.get(k) for k in CONTRACT}

    def heard(self, rd: dict, now: float) -> dict:
        """One reading (`reading`) heard at UTC `now`: the sonde as it now
        stands, its public view."""
        with self.lock:
            v = self.s.get(rd["serial"])
            if v is None:
                v = self.s[rd["serial"]] = {"serial": rd["serial"], "phase": "ascent", "burst": None,
                                            "landing": None, "firstHeardTs": now, "maxAlt": None,
                                            "descentRun": 0, "landedRun": 0, "landedFrames": 0}
            prev = (v.get("lat"), v.get("altM"), v.get("t"))
            v["lastHeardTs"], v["lastHeard"] = now, _iso(now)
            for k in ("type", "frame", "tempC", "humidity", "pressureHpa", "batteryV", "freqHz", "t",
                      "encrypted"):
                v[k] = rd.get(k)
            if rd.get("lat") is not None:
                v["lat"], v["lon"], v["altM"] = round(rd["lat"], 5), round(rd["lon"], 5), round(rd["altM"], 1)
                climb = rd.get("climbMs")
                if climb is None and prev[1] is not None and prev[2] is not None and rd["t"] > prev[2]:
                    climb = (rd["altM"] - prev[1]) / (rd["t"] - prev[2])
                v["climbMs"] = round(climb, 2) if climb is not None else None
                v["headingDeg"] = round(rd["headingDeg"], 1) if rd.get("headingDeg") is not None else None
                v["speedKmh"] = rd.get("speedKmh")
                self._phase(v, rd["t"])
                self._track(v, rd["t"])
                self._profile(v)
            self.rev += 1
            v["rev"] = self.rev
            self.dirty = True
            return self.public(v)

    def _phase(self, v: dict, t: float) -> None:
        alt, climb = v["altM"], v.get("climbMs")
        if v["maxAlt"] is None or alt > v["maxAlt"][2]:
            v["maxAlt"] = [v["lat"], v["lon"], alt, t]
        if v["phase"] == "landed":
            v["landedFrames"] += 1
            return
        if climb is not None and climb < -DESCENT_MS and v["maxAlt"][2] - alt > DESCENT_DROP_M:
            v["descentRun"] += 1
        else:
            v["descentRun"] = 0
        if v["phase"] == "ascent" and v["descentRun"] >= DESCENT_FRAMES:
            v["phase"] = "descent"
            m = v["maxAlt"]
            v["burst"] = {"lat": m[0], "lon": m[1], "altM": round(m[2]), "predicted": False}
        speed = (v.get("speedKmh") or 0.0) / 3.6
        if v["phase"] == "descent" and climb is not None and abs(climb) < LANDED_CLIMB_MS \
                and speed < LANDED_SPEED_MS:
            v["landedRun"] += 1
        else:
            v["landedRun"] = 0
        if v["landedRun"] >= LANDED_FRAMES:
            v["phase"] = "landed"
            v["landing"] = {"lat": v["lat"], "lon": v["lon"], "utc": _iso(t)}
            v["landedFrames"] = 0

    def _track(self, v: dict, t: float) -> None:
        tr = self.tracks.setdefault(v["serial"], deque(maxlen=TRACK_POINTS))
        if tr and t - tr[-1][0] < TRACK_MIN_S:
            return
        if tr and v["phase"] == "landed" and tr[-1][1:3] == [v["lat"], v["lon"]]:
            return
        tr.append([round(t, 1), v["lat"], v["lon"], v["altM"]])

    def _profile(self, v: dict) -> None:
        if v["phase"] == "landed":
            return
        pr = self.profiles.setdefault(v["serial"], [])
        if pr and abs(v["altM"] - pr[-1][0]) < PROFILE_STEP_M:
            return
        if len(pr) >= PROFILE_POINTS:
            return
        h = v.get("headingDeg")
        pr.append([round(v["altM"]), v.get("tempC"), v.get("humidity"), v.get("pressureHpa"), v.get("speedKmh"),
                   round((h + 180.0) % 360.0, 1) if h is not None else None])

    def predicted(self, serial: str, result: dict | None) -> dict | None:
        """A prediction for a sonde in flight: the burst replaced only
        while it is still a prediction, the landing until it has landed.
        The public view when anything changed, else None."""
        if result is None:
            return None
        with self.lock:
            v = self.s.get(serial)
            if v is None or v["phase"] == "landed":
                return None
            burst = v["burst"] if (v["burst"] or {}).get("predicted") is False else result.get("burst")
            landing = result.get("landing")
            if (burst, landing) == (v["burst"], v["landing"]):
                return None
            v["burst"], v["landing"] = burst, landing
            self.rev += 1
            v["rev"] = self.rev
            self.dirty = True
            return self.public(v)

    def get(self, serial: str) -> dict | None:
        with self.lock:
            v = self.s.get(serial)
            return dict(v) if v is not None else None

    # -- ageing -------------------------------------------------------------
    def expire(self, now: float) -> list[str]:
        """Drop each sonde not heard for KEEP_S, or LANDED_KEEP_S once landed."""
        with self.lock:
            gone = [k for k, v in self.s.items()
                    if now - float(v.get("lastHeardTs") or 0) > (LANDED_KEEP_S if v.get("phase") == "landed"
                                                                 else KEEP_S)]
            for k in gone:
                self.s.pop(k, None)
                self.tracks.pop(k, None)
                self.profiles.pop(k, None)
                self.rev += 1
                self.removed.append((self.rev, k))
            if gone:
                self.dirty = True
        return gone

    # -- views --------------------------------------------------------------
    def view(self) -> list[dict]:
        """Every sonde, most recently heard first, each with its track."""
        with self.lock:
            out = []
            for v in sorted(self.s.values(), key=lambda v: (-float(v.get("lastHeardTs") or 0), v["serial"])):
                p = self.public(v)
                p["track"] = [{"t": _iso(q[0]), "lat": q[1], "lon": q[2], "altM": q[3]}
                              for q in self.tracks.get(v["serial"], ())]
                out.append(p)
        return out

    def sonde(self, serial: str) -> dict | None:
        with self.lock:
            v = self.s.get(serial)
            if v is None:
                return None
            p = self.public(v)
            p["track"] = [{"t": _iso(q[0]), "lat": q[1], "lon": q[2], "altM": q[3]}
                          for q in self.tracks.get(serial, ())]
            p["profile"] = [{"altM": q[0], "tempC": q[1], "humidity": q[2], "pressureHpa": q[3], "windKmh": q[4],
                             "windDirDeg": q[5]} for q in self.profiles.get(serial, ())]
        return p

    def __len__(self) -> int:
        return len(self.s)

    # -- disk -----------------------------------------------------------------
    def load(self) -> None:
        if self.path is None:
            return
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict) or doc.get("schema") != 1:
            return
        for v in doc.get("sondes", []):
            if isinstance(v, dict) and isinstance(v.get("serial"), str):
                self.s[v["serial"]] = v
        for k, tr in (doc.get("tracks") or {}).items():
            if k in self.s and isinstance(tr, list):
                self.tracks[k] = deque((list(p) for p in tr if isinstance(p, list) and len(p) == 4),
                                       maxlen=TRACK_POINTS)
        for k, pr in (doc.get("profiles") or {}).items():
            if k in self.s and isinstance(pr, list):
                self.profiles[k] = [list(p) for p in pr if isinstance(p, list) and len(p) == 6]
        self.rev = int(doc.get("rev") or 0)

    def save(self, force: bool = False) -> None:
        if self.path is None:
            return
        with self.lock:
            if not self.dirty or (not force and time.time() - self.saved_at < SAVE_S):
                return
            doc = {"schema": 1, "rev": self.rev, "sondes": list(self.s.values()),
                   "tracks": {k: list(q) for k, q in self.tracks.items()},
                   "profiles": {k: list(q) for k, q in self.profiles.items()}}
            self.dirty, self.saved_at = False, time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save the radiosonde table: %s", e)


# -- the session ---------------------------------------------------------------------
class SondeService:
    """The radiosonde session, the scan and the decoder, and the table
    (module docstring)."""

    def __init__(self, radio):
        self.radio = radio
        folder = Path(radio.data_dir) / "sonde" if getattr(radio, "data_dir", None) else None
        self.table = SondeTable(folder / "sondes.json" if folder is not None else None)
        st = radio.st
        self.hub = sondehub.SondeHub(folder, upload_on=lambda: bool(st.get("sondeHubUpload", True)),
                                     online_on=lambda: bool(st.get("sondeOnline", True)),
                                     station=lambda: (st.get("callsign") or "", st.get("locator") or ""))
        self.lock = threading.RLock()
        self.clients: dict[str, float] = {}
        self.state = "idle"
        self.why: str | None = None
        self.started_at: float | None = None
        self.linger_until: float | None = None
        # Set by the server: client presence vouching for a client ("sonde"
        # in its holds), as AisService.vouch.
        self.vouch = None
        # Where auto_rx's programs are: None picks (Programs, or the
        # simulator's for the simulated radio); a test sets its own.
        self.programs = None
        self.progs = None
        self.q: queue.Queue | None = None
        self.worker: threading.Thread | None = None
        self.lines: deque = deque(maxlen=2000)      # (kind, freq, json) from the decoder, for tick
        self.freq: float | None = None              # what the dial is on: the hop, or the sonde
        self.tracking: dict | None = None           # {"kind", "freqHz", "serial"} while locked on
        self.candidates: list[dict] = []
        self.blocked: dict[float, float] = {}       # channel -> until (time.time)
        self.let_go: str | None = None              # the supervisor asking the worker to let go, and why
        self.counts = {"frames": 0, "dropped": 0, "scans": 0, "detections": 0}
        self.expired_at = 0.0
        self.predicted_at: dict[str, float] = {}
        self._published: dict | None = None
        self._run = None

    # -- the session --------------------------------------------------------
    def texts(self) -> dict:
        return {"tune": _("The receiver is listening for radiosondes: close the radiosonde map, or stop it, to "
                          "tune or change mode"),
                "transmit": _("The receiver is listening for radiosondes: stop it to transmit"),
                "on_air": _("Not while transmitting: radiosondes take the receiver to 400-406 MHz"),
                "busy": _("Radiosondes have the receiver: close the radiosonde map first")}

    def join(self, client: str, drop_sessions: bool = False) -> dict:
        """Client `client` has the radiosonde map open: start if not
        running, and keep running for CLIENT_LEASE_S more. Raises Refused
        (code, sentence) when it cannot start."""
        client = str(client or "")
        if not CLIENT_RE.match(client):
            raise Refused("bad_client", _("The client must name itself: 1-64 letters, digits, '.', '_', ':' or "
                                          "'-'"))
        now = time.monotonic()
        with self.lock:
            if client not in self.clients and len(self.clients) >= MAX_CLIENTS:
                raise Refused("too_many_clients", _("Too many screens have the radiosonde map open"))
            if self.state == "idle":
                self._start(drop_sessions)
            self.clients[client] = now + CLIENT_LEASE_S
            self.linger_until = None
            self._publish()
            return self.view()

    def _vouched(self, client: str) -> bool:
        try:
            return self.vouch is not None and bool(self.vouch(client))
        except Exception:  # noqa: BLE001 - a vouch that fails vouches for nobody
            return False

    def leave(self, client: str) -> dict:
        with self.lock:
            if self.clients.pop(str(client or ""), None) is not None and not self.clients and \
                    self.state != "idle":
                self.linger_until = time.monotonic() + LINGER_S
            self._publish()
            return self.view()

    def _choose_programs(self):
        if self.programs is not None:
            return self.programs
        if self.radio.st.get("device") == "sim":
            from .devices import simsonde
            return simsonde.Programs()
        return Programs()

    def _start(self, drop_sessions: bool) -> None:
        r = self.radio
        progs = self._choose_programs()
        if not progs.available():
            raise Refused("decoder_unavailable", _("Radiosondes need radiosonde_auto_rx's decoders, which this "
                                                   "install does not have"))
        if not r.running:
            raise Refused("not_running", _("Start the radio to see radiosondes: they need the receiver"))
        pinning = r.decoders.pinned_by() if r.PINS_SPAN else []
        if pinning:
            if not drop_sessions:
                raise Refused("span_pinned", _("Radiosondes take the receiver to 400-406 MHz and stop {sessions}")
                              .format(sessions=sessions_text(pinning)), sessions=pinning)
            r.decoders.stop_background()
        r.client_activity("decoder")
        first = hops(float(r.geo.fs))[0]
        r.hold_receiver(SID, "sonde", first, "Radiosondes", MIN_RATE, feed=self._feed, texts=self.texts(),
                        tune={"vfo": first})
        self.progs = progs
        self.q = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.counts = {"frames": 0, "dropped": 0, "scans": 0, "detections": 0}
        self.candidates, self.tracking, self.let_go, self.freq = [], None, None, first
        self.worker = threading.Thread(target=self._work, args=(self.q,), name="sonde", daemon=True)
        self.state, self.why = "scanning", None
        self.started_at = time.time()
        self.worker.start()
        log.info("radiosondes: scanning 400-406 MHz")

    def end(self, why: str = "stopped") -> None:
        """End the session now, whoever has the map open: the receiver back
        as it was. `why` as ais.AisService.end."""
        # As AIS: the receiver given back before the state says idle.
        with self.lock:
            q, worker, self.q, self.worker = self.q, self.worker, None, None
            if q is not None:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass
            if self.state != "idle":
                h = self.radio.held
                if h is not None and h.get("session") == SID:
                    self.radio.release_receiver(SID)
                log.info("radiosondes ended (%s)", why)
            self.state, self.why = "idle", why
            self.clients.clear()
            self.linger_until = None
            self.tracking, self.freq = None, None
            run = self._run
        if run is not None:
            # A worker waiting on dft_detect's answer, or writing to a
            # decoder, is let go at once: its programs are killed under it.
            run.kill()
        if worker is not None and worker is not threading.current_thread():
            worker.join(5.0)
        self.table.save(force=True)
        self._publish()

    def _feed(self, raw, settled: bool) -> None:
        """The receive thread, once per block, while radiosondes hold the
        receiver: the block onto the worker's queue, or dropped."""
        q = self.q
        r = self.radio
        if q is None or not settled or r.centre is None:
            return
        try:
            q.put_nowait((raw.copy(), float(r.geo.fs), float(r.centre)))
        except queue.Full:
            self.counts["dropped"] += 1

    # -- the worker: the scan and the decoder ---------------------------------
    def _env(self, freq: float) -> dict:
        env = dict(os.environ)
        env.update(self.progs.env)
        # The channel's frequency: nothing of auto_rx's reads it, the
        # simulator's stand-ins do (devices/simsonde.py).
        env["OHS_SONDE_FREQ"] = str(int(round(freq)))
        return env

    def _work(self, q: queue.Queue) -> None:
        run = _Run(self)
        self._run = run
        try:
            while True:
                item = q.get()
                if item is None or self.q is not q:
                    return
                try:
                    run.step(*item)
                except Exception:  # noqa: BLE001 - a block the worker cannot take costs that block
                    log.warning("radiosondes: a block could not be handled", exc_info=True)
                    run.reset()
        finally:
            run.close()

    def _move(self, centre: float, dial: float, label: str) -> bool:
        return self.radio.move_hold(SID, centre, label, vfo=dial)

    def _is_blocked(self, f: float) -> bool:
        now = time.time()
        return any(abs(f - b) < GRID_HZ and until > now for b, until in list(self.blocked.items()))

    # -- the supervisor ------------------------------------------------------
    def tick(self, now_mono: float | None = None) -> None:
        now = time.monotonic() if now_mono is None else now_mono
        r = self.radio
        ending = None
        with self.lock:
            if self.state != "idle":
                for c, until in list(self.clients.items()):
                    if until < now and not self._vouched(c):
                        del self.clients[c]
                if not self.clients and self.linger_until is None:
                    self.linger_until = now + LINGER_S
                lost = r.held is None or r.held.get("session") != SID
                if not r.running:
                    ending = "radio_stopped"
                elif lost:
                    ending = "lost"
                elif self.linger_until is not None and now >= self.linger_until:
                    ending = "idle"
        if ending is not None:
            # Outside the lock: end() waits for the worker, which takes the
            # lock to say it has locked on or let go.
            self.end(ending)
        while self.lines:
            try:
                kind, freq, line = self.lines.popleft()
            except IndexError:
                break
            self._line(kind, freq, line)
        t = time.time()
        if t - self.expired_at >= EXPIRE_EVERY_S:
            self.expired_at = t
            for serial in self.table.expire(t):
                r._publish("sonde", {"type": "removed", "serial": serial, "rev": self.table.rev})
        self.table.save()
        self._publish()

    def _line(self, kind: str, freq: float, line: str) -> None:
        """One line of the decoder's output into the table, the upload and
        the feed (auto_rx's handle_decoder_line, module docstring)."""
        try:
            tel = json.loads(line)
        except ValueError:
            return
        now = time.time()
        rd = reading(tel, kind, freq, now)
        if rd is None:
            if isinstance(tel, dict) and "version" in tel and str(tel["version"]) != AUTO_RX_VERSION:
                log.warning("radiosondes: a decoder built for %s, not %s: its lines are not used",
                            tel.get("version"), AUTO_RX_VERSION)
            return
        self.counts["frames"] += 1
        v = self.table.heard(rd, now)
        tr = self.tracking
        if tr is not None and tr.get("freqHz") == freq:
            tr["serial"] = rd["serial"]
        if rd["encrypted"] and tr is not None:
            self.let_go = "encrypted"
        full = self.table.get(rd["serial"])
        if full and full.get("phase") == "landed" and full.get("landedFrames", 0) >= LANDED_LEAVE_FRAMES \
                and tr is not None:
            self.let_go = "landed"
        if not (self.progs is not None and self.progs.simulated):
            self.hub.add(rd)                    # never the simulator's (module docstring)
        self.radio._publish("sonde", {"type": "sonde", "rev": self.table.rev, "sonde": v})
        self._predict(rd["serial"], now)

    def _predict(self, serial: str, now: float) -> None:
        v = self.table.get(serial)
        if v is None or v.get("phase") == "landed" or v.get("lat") is None:
            return
        if now - self.predicted_at.get(serial, -1e18) < PREDICT_EVERY_S:
            return
        self.predicted_at[serial] = now
        launch = self.hub.site_near(*(self._launch_of(v)))
        burst_alt = float((launch or {}).get("burst_altitude") or sondehub.BURST_DEFAULT_M)
        descent = float((launch or {}).get("descent_rate") or sondehub.DESCENT_DEFAULT_MS)
        ground = float((launch or {}).get("alt") or 0.0)
        result = self.hub.prediction(serial, max_age=4 * PREDICT_EVERY_S, now=now) if self.hub.online_on() \
            else None
        if result is None:
            result = ballistic(v, now, burst_alt, descent, ground)
        changed = self.table.predicted(serial, result)
        if changed is not None:
            self.radio._publish("sonde", {"type": "sonde", "rev": self.table.rev, "sonde": changed})
        q = tawhiri_query(v, now, burst_alt, descent)
        if q is not None:
            self.hub.predict(serial, q, now)

    def _launch_of(self, v: dict) -> tuple[float, float]:
        tr = self.table.tracks.get(v["serial"])
        if tr:
            return tr[0][1], tr[0][2]
        return v["lat"], v["lon"]

    # -- views -------------------------------------------------------------
    def sondes(self) -> dict:
        """GET api/sonde/sondes: the contract's shape (module docstring)."""
        with self.lock:
            state, freq = self.state, self.freq
        return {"state": state, "freqHz": freq, "sondehub": self.hub.view(), "sondes": self.table.view()}

    def launches(self) -> list[dict]:
        pos = locator_position(self.radio.st.get("locator") or "")
        return self.hub.launches(*(pos if pos else (None, None)))

    def view(self) -> dict:
        with self.lock:
            now = time.monotonic()
            ends = None
            if self.state != "idle" and self.linger_until is not None:
                ends = max(0.0, self.linger_until - now)
            tr = self.tracking
            return {"state": self.state, "why": self.why, "text": self._text(), "clients": len(self.clients),
                    "startedAt": _iso(self.started_at) if self.state != "idle" else None,
                    "endsInS": None if ends is None else round(ends, 1), "freqHz": self.freq,
                    "tracking": dict(tr) if tr else None, "candidates": [dict(c) for c in self.candidates],
                    "leaseS": CLIENT_LEASE_S, "lingerS": LINGER_S, "sondes": len(self.table),
                    "rev": self.table.rev, "decoders": f"radiosonde_auto_rx {AUTO_RX_VERSION}", **self.counts}

    def _text(self) -> str:
        if self.state == "scanning":
            return _("Looking for radiosondes on 400-406 MHz")
        if self.state == "tracking":
            tr = self.tracking or {}
            return _("Decoding a radiosonde on {mhz} MHz").format(mhz=f"{(tr.get('freqHz') or 0) / 1e6:.3f}")
        return {"idle": _("Stopped: nobody had the radiosonde map open"),
                "stopped": _("Stopped"),
                "radio_stopped": _("Stopped: the radio stopped"),
                "lost": _("Stopped: the receiver was taken back")}.get(self.why or "", _("Not running"))

    def _publish(self) -> None:
        v = self.view()
        key = {"state": v["state"], "why": v["why"], "clients": v["clients"], "ending": v["endsInS"] is not None,
               "freq": v["freqHz"], "tracking": v["tracking"], "candidates": v["candidates"]}
        if key != self._published:
            self._published = key
            self.radio._status(sonde=v)
            self.radio._publish("sonde", {"type": "session", "session": v})



class _Run:
    """The worker's own state (SondeService._work): which hop, the
    spectrum so far, the candidate being identified, the decoder chain.
    Touched only on the worker's thread; the service reads its results."""

    def __init__(self, svc: SondeService):
        self.svc = svc
        self.cycle = 0
        self.hop_list: list[float] = []
        self.hop = -1
        self.centre: float | None = None
        self.psd = None
        self.psd_n = 0
        self.seen = 0               # samples of this hop taken
        self.todo: list[tuple[float, float]] = []
        self.detect: dict | None = None
        self.track: dict | None = None
        self.fs = None
        self.window = None

    # The receiver's blocks -------------------------------------------------
    def step(self, raw: np.ndarray, fs: float, centre: float) -> None:
        if self.fs != fs:
            self.reset()
            self.fs = fs
        if self.track is not None:
            self._tracking(raw, centre)
        else:
            self._scanning(raw, centre)

    def reset(self) -> None:
        self._stop_detect()
        self._stop_track()
        self.hop, self.hop_list, self.centre = -1, [], None
        self.psd, self.psd_n, self.seen, self.todo = None, 0, 0, []

    def close(self) -> None:
        self._stop_detect()
        self._stop_track()

    def kill(self) -> None:
        """The programs killed from another thread (SondeService.end); the
        worker then finds its pipes closed and stops."""
        for job in (self.detect, self.track):
            if job is not None:
                job["chain"].kill()

    # The scan ----------------------------------------------------------------
    def _next_hop(self) -> None:
        svc = self.svc
        self.hop += 1
        if self.hop >= len(self.hop_list):
            self.hop_list = hops(self.fs, shifted=bool(self.cycle % 2))
            self.cycle += 1
            self.hop = 0
            svc.counts["scans"] += 1
        c = self.hop_list[self.hop]
        self.centre, self.psd, self.psd_n, self.seen, self.todo = c, None, 0, 0, []
        svc.freq = c
        svc._move(c, c, "Radiosondes")

    def _scanning(self, raw: np.ndarray, centre: float) -> None:
        if self.centre is None:
            self.hop_list = hops(self.fs, shifted=bool(self.cycle % 2))
            self.hop, self.centre = 0, self.hop_list[0]
            self.svc.freq = self.centre
            self.svc._move(self.centre, self.centre, "Radiosondes")
        if abs(centre - self.centre) > 1.0:
            return                            # still the last hop's samples
        if self.detect is not None:
            self._detecting(raw)
            return
        if self.todo:
            self._start_detect()
            if self.detect is not None:
                self._detecting(raw)
            return
        n = int(round(self.fs / BIN_HZ))
        if self.window is None or len(self.window) != n:
            self.window = np.hanning(n).astype(np.float32)
        # Every fourth stretch of n samples: the average needs seconds of
        # air, not every sample of them.
        for a in range(0, len(raw) - n + 1, 4 * n):
            seg = raw[a:a + n] * self.window
            p = np.abs(np.fft.fftshift(np.fft.fft(seg))) ** 2
            self.psd = p if self.psd is None else self.psd + p
            self.psd_n += 1
        self.seen += len(raw)
        if self.seen < SCAN_DWELL_S * self.fs or self.psd is None:
            return
        freqs = self.centre + np.fft.fftshift(np.fft.fftfreq(n, 1.0 / self.fs))
        found = find_peaks(self.psd / self.psd_n, freqs, self.centre, self.fs, self.svc._is_blocked)
        self.svc.candidates = [c for c in self.svc.candidates if abs(c["freqHz"] - self.centre) > self.fs / 2] + \
            [{"freqHz": f, "snrDb": round(s, 1), "type": None} for f, s in found]
        self.todo = list(found)
        if not self.todo:
            self._next_hop()

    def _start_detect(self) -> None:
        f, _snr = self.todo.pop(0)
        svc = self.svc
        p = svc.progs
        argv = p.argv("dft_detect", "-t", str(DETECT_S), "--iq", "--bw", "15", "--dc", "--exclude-types",
                      "IMET1AB,C34C50", "-", str(DETECT_RATE), "16")
        try:
            chain = Chain([argv], svc._env(f))
        except OSError as e:
            log.warning("radiosondes: dft_detect would not start: %s", e)
            self._next_hop()
            return
        self.detect = {"freq": f, "chain": chain, "ddc": Ddc(self.fs, f - self.centre, DETECT_RATE),
                       "cs16": Cs16(), "n": 0, "done": False}

    def _detecting(self, raw: np.ndarray) -> None:
        d = self.detect
        y = d["ddc"](raw)
        ok = d["chain"].write(d["cs16"](y))
        d["n"] += len(y)
        if ok and d["n"] < DETECT_S * DETECT_RATE:
            return
        d["chain"].close_input()
        timer = threading.Timer(10.0, d["chain"].kill)
        timer.start()
        try:
            out = d["chain"].stdout.read().decode("ascii", "replace")
        except (OSError, ValueError):
            out = ""
        finally:
            timer.cancel()
        d["chain"].kill()
        self.detect = None
        kind, offset = parse_detect(out)
        svc = self.svc
        f = d["freq"]
        for c in svc.candidates:
            if c["freqHz"] == f:
                c["type"] = kind
        if kind is not None:
            svc.counts["detections"] += 1
        if kind in CHAINS:
            self._start_track(kind, round((f + offset) / 1000.0) * 1000.0)
        elif not self.todo:
            self._next_hop()

    def _stop_detect(self) -> None:
        if self.detect is not None:
            self.detect["chain"].kill()
            self.detect = None

    # The decoder ---------------------------------------------------------------
    def _start_track(self, kind: str, freq: float) -> None:
        svc = self.svc
        p = svc.progs
        rate, baud, demod, decoder = CHAINS[kind]
        argvs = [p.argv("iq_dec", "--bo", "16", "-", str(rate), "16"),
                 p.argv("fsk_demod", "--cs16", *demod, "2", str(rate), str(baud), "-", "-"),
                 p.argv(*decoder)]
        try:
            chain = Chain(argvs, svc._env(freq))
        except OSError as e:
            log.warning("radiosondes: the %s decoder would not start: %s", kind, e)
            self._next_hop()
            return
        centre = freq + TRACK_OFFSET_HZ
        self.track = {"kind": kind, "freq": freq, "centre": centre, "chain": chain, "ddc": None, "cs16": Cs16(),
                      "rate": rate, "n": 0, "last": 0}
        reader = threading.Thread(target=self._read, args=(self.track,), name="sonde-decoder", daemon=True)
        self.track["reader"] = reader
        reader.start()
        with svc.lock:
            if svc.state == "idle":
                # Ended while dft_detect answered: nothing to lock on for.
                self._stop_track()
                return
            svc.tracking = {"kind": kind, "freqHz": freq, "serial": None}
            svc.state = "tracking"
            svc.freq = freq
        svc.let_go = None
        log.info("radiosondes: decoding a %s on %.3f MHz", kind, freq / 1e6)
        svc._move(centre, freq, "Radiosonde")

    def _read(self, tr: dict) -> None:
        """The decoder's lines (its own thread: a read blocks)."""
        svc = self.svc
        for raw in tr["chain"].stdout:
            line = raw.decode("ascii", "replace").strip()
            if not line.startswith("{"):
                continue
            tr["last"] = tr["n"]
            svc.lines.append((tr["kind"], tr["freq"], line))

    def _tracking(self, raw: np.ndarray, centre: float) -> None:
        tr = self.track
        svc = self.svc
        if svc.let_go is not None:
            why, svc.let_go = svc.let_go, None
            log.info("radiosondes: leaving %.3f MHz (%s)", tr["freq"] / 1e6, why)
            svc.blocked[tr["freq"]] = time.time() + BLOCK_S
            self._back_to_scan()
            return
        if abs(centre - tr["centre"]) > 1.0:
            return
        if tr["ddc"] is None:
            tr["ddc"] = Ddc(self.fs, tr["freq"] - centre, tr["rate"])
        y = tr["ddc"](raw)
        ok = tr["chain"].write(tr["cs16"](y))
        tr["n"] += len(y)
        if not ok or any(p.poll() is not None for p in tr["chain"].procs):
            log.info("radiosondes: the decoder stopped")
            svc.blocked[tr["freq"]] = time.time() + 60.0
            self._back_to_scan()
        elif tr["n"] - tr["last"] > RX_TIMEOUT_S * tr["rate"]:
            log.info("radiosondes: nothing decoded on %.3f MHz for %d s", tr["freq"] / 1e6, RX_TIMEOUT_S)
            self._back_to_scan()

    def _stop_track(self) -> None:
        tr, self.track = self.track, None
        if tr is not None:
            tr["chain"].kill()
            tr["reader"].join(2.0)

    def _back_to_scan(self) -> None:
        self._stop_track()
        svc = self.svc
        with svc.lock:
            svc.tracking = None
            if svc.state == "tracking":
                svc.state = "scanning"
        self.hop = len(self.hop_list)        # a new pass from the bottom
        self._next_hop()
