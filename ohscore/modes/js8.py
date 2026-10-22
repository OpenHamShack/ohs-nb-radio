"""JS8, all five speeds: decoded by ohsdigi, OpenHamShack's own decoder,
with JS8Call's `js8` program as the fallback where it is installed.

**ohsdigi first (10/10/2026).** rust/ohsdigi/src/js8 is a port of JS8Call
2.2.0's modem, decoder and message layer. It decodes exactly what `js8`
decodes - the same frames, SNR, DT and frequency, line for line, on 200
crowded test slots across all five speeds and on JS8Call's own regression
recordings (rust/ohsdigi/tests/js8_golden.rs) - and it needs nothing
installed, so JS8 now works in the store images and the desktop bundles,
where `js8` (which comes with JS8Call's Qt GUI) was never carried. Where
ohsdigi is missing or raises on a period, `js8` decodes instead if present,
as jt9 backs up ohsdigi for FT8.

**The text is readable now.** `js8` prints each frame as JS8Call's raw
12-character token (e.g. "SIUT18l+CDqE"); turning that into what JS8Call
shows - "KN4CRD: @HB HEARTBEAT EM73", "KN4CRD: J1Y SNR -05", data text -
is JS8Call's message layer (varicode.cpp, decodedtext.cpp), which lived
only in its GUI. ohsdigi ports that too (js8_unpack, checked against
JS8Call's own code compiled unchanged), so every event carries `text` as
JS8Call would show it, plus `frame` and `i3bit` (the raw frame and its
header bits), `kind` (heartbeat, compound, compound_directed, directed,
data, unknown), `first`/`last` (a message is a run of frames from first
to last, one per period - joining them is the listener's business), and
`call`/`grid`/`to` where the frame names them. A frame decoded by `js8`
is read the same way when ohsdigi can be loaded at all.

**All five speeds (Brian, 17/10/2026).** Slow (30 s), Normal (15 s), Fast
(10 s), Turbo (6 s) and Ultra (4 s) are decoded at once, as JS8Call does:
AllSpeedsDecoder runs one Decoder per speed on the same audio, each on its
own period, and every event says its `speed`. A frame two speeds' passes
both report is reported once. All five cost about 8 % of one core on
ohs-dev (ohsdigi at depth 3), so none is a setting. Sending is at the
speed the operator picks, Normal by default (the "JS8Call" QO-100 preset,
ohsnb/bandplan.py 10489.548 MHz, assumes it); the speeds' timings are one
table, ohscore/modegroups.py JS8_SPEEDS, which the engine's slot tables,
this decoder and the panel all read.

**Sending (Brian, 17/10/2026).** ohsdigi makes JS8 frames from text and
the audio for them (js8_frames, js8_encode_audio - JS8Call's
buildMessageFrames and modulator, held to JS8Call's own output by
rust/ohsdigi/tests/js8_golden.rs). A message is several frames, one per
period; the engine's send() is one over in one slot, so each frame is its
own over - `send("js8", text=..., part=i)` - and the JS8 panel
(ohscore/ui/panels/js8.py) sends part 0, 1, ... in consecutive periods.
Every over therefore passes the same guard as an FT8 one (licence, band
plan segment, level guard, receive-only runs, TX lock). The encoder makes
the frames from the text and the station's own callsign each time, which
the engine supplies (Engine._render), so no caller can send frames under
another call; a message JS8 would send with no callsign in it (free text)
gets " DE <call>" added, as identification.

**js8's output format**, for the fallback (measured against js8call
2.2.0+ds-5+b1's own test WAVs, media/tests/*.wav, its `test` script
running `js8 -8 -b <mode> -d <depth> <file>.wav`): lib/decoder.f90's
`js8_decoded` callback writes

    format(i6.6,i4,f5.1,i5,a3,1x,a22,1x,a2)  ! "000000  11  0.1  500 A  SIUT18l+CDqE         3   "
    format(i6.6,i4,f5.1,i5,a3,1x,a37)        ! a message containing ';' - rare

nutc (never a real clock from a WAV, discarded as for FT8/Q65), SNR, DT,
frequency, the submode letter, then the 22-character message field: the
12-character frame, padding, and the frame's header bits as one digit in
column 22; then, only in the first form, an "aN" a-priori flag. Its `-p
MINUTES` option is never passed: its allowed values (1/2/5/10/30) have
nothing to do with JS8's periods, and the default reads a long enough
buffer, as js8call's own test script relies on."""
from __future__ import annotations

import atexit
import math
import os
import re
import shutil
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .. import host
from ..i18n.text import _
from ..modegroups import JS8_DEFAULT_SPEED, JS8_SPEEDS
from .ft8 import _OHSDIGI, OHSDIGI_WHY_NOT, run_decoder_tool, _calls_now, _jt9_call, _jt9_nint, _jt9_round1, _parse_standard, _say_once

FS = 12_000.0
PERIOD_S = 15.0                  # JS8 Normal's real T/R period (measured: see module docstring)
SUBMODE = "A"                    # Normal's letter; the others are JS8_SPEEDS'
SPEEDS = tuple(JS8_SPEEDS)       # slowest first
# A frame decoded twice within this long, on the same offset, by two
# speeds' passes is one frame (AllSpeedsDecoder).
DUP_WINDOW_S = 30.0
# js8call's own default (mainwindow.cpp: m_ndepth=m_settings->value("NDepth",3)) -
# cheap for one 15 s slot, and matches what an operator running the GUI gets.
DEPTH = 3

_JS8 = host.find_tool("js8")


def _with_js8(ohsdigi):
    """`ohsdigi` if it carries JS8 (built from 10/10/2026 on), else None."""
    if ohsdigi is not None and hasattr(ohsdigi, "js8_decode") and hasattr(ohsdigi, "js8_unpack"):
        return ohsdigi
    return None


_OHSDIGI_JS8 = _with_js8(_OHSDIGI)
CAN_DECODE = bool(_OHSDIGI_JS8 is not None or _JS8)
AVAILABLE = CAN_DECODE
CAN_ENCODE = bool(_OHSDIGI_JS8 is not None and hasattr(_OHSDIGI_JS8, "js8_frames")
                  and hasattr(_OHSDIGI_JS8, "js8_encode_audio"))
# As FT8's (ft8.py): the store image carries ohsdigi and never js8, so there
# JS8 missing means ohsdigi did not load; elsewhere either would do.
_NO_OHSDIGI = OHSDIGI_WHY_NOT or "this ohsdigi was built without JS8"
WHY_UNAVAILABLE = (f"JS8 needs OpenHamShack's decoder (ohsdigi), which did not load in this app's image "
                   f"({_NO_OHSDIGI}); reinstall the app" if host.STORE
                   else f"JS8 needs OpenHamShack's decoder (ohsdigi), which did not load ({_NO_OHSDIGI}). "
                        + host.hint("js8"))
WHY_NO_ENCODER = (f"JS8 cannot be sent here: sending needs OpenHamShack's ohsdigi ({_NO_OHSDIGI}); js8, JS8Call's "
                  f"decoder, cannot send")


def describe_decoder() -> str:
    """Which decoder JS8 uses here, for the diagnostics report."""
    if _OHSDIGI_JS8 is not None:
        return f"ohsdigi, js8 as fallback ({_JS8})" if _JS8 else "ohsdigi; no js8, so no fallback"
    return f"js8 ({_JS8 or 'not found'}); no ohsdigi: {_NO_OHSDIGI}"


def frames(text: str, callsign: str, locator: str = "", ohsdigi=..., speed: str = JS8_DEFAULT_SPEED
           ) -> list[tuple[str, int]]:
    """The frames (frame, i3bit) JS8Call would send for `text` from
    `callsign`, one per period, identified: a message whose frames would not
    name the sender (free text) gets " DE <call>" on the end. Text is sent
    in upper case, as JS8Call sends it. ValueError for text JS8 cannot
    carry, no callsign, or no ohsdigi (WHY_NO_ENCODER) - a ValueError, so
    the window shows the sentence (Bridge.send) as it does the guard's."""
    lb = _OHSDIGI_JS8 if ohsdigi is ... else _with_js8(ohsdigi)
    if lb is None or not hasattr(lb, "js8_frames"):
        raise ValueError(WHY_NO_ENCODER)
    call = str(callsign or "").strip().upper()
    if not call:
        raise ValueError(_("Set your callsign (Settings › Station) before sending: JS8 sends it with every message"))
    msg = " ".join(str(text or "").upper().split())
    if not msg:
        raise ValueError(_("Nothing to send"))
    grid = str(locator or "").strip().upper()[:4]
    out = lb.js8_frames(msg, call, grid, submode=speed)
    if not any((lb.js8_unpack(f, i).get("from") or "").upper() == call for f, i in out):
        out = lb.js8_frames(f"{msg} DE {call}", call, grid, submode=speed)
    return [(str(f), int(i)) for f, i in out]


class Encoder:
    """One frame of a JS8 message as audio at `speed`: `part` picks which
    (module docstring). Started its speed's `start` into the period by the
    engine (SLOT_LEAD), as JS8Call's modulator starts it."""

    def __init__(self, ohsdigi=...):
        self.ohsdigi = _OHSDIGI_JS8 if ohsdigi is ... else _with_js8(ohsdigi)

    def render(self, text: str = "", offset: float = 1500.0, part: int = 0, callsign: str = "",
               locator: str = "", speed: str = JS8_DEFAULT_SPEED, **_opts) -> np.ndarray:
        if speed not in JS8_SPEEDS:
            raise ValueError(_("Unknown JS8 speed {speed}").format(speed=repr(speed)))
        fr = frames(text, callsign, locator, ohsdigi=self.ohsdigi, speed=speed)
        part = int(part)
        if not 0 <= part < len(fr):
            raise ValueError(_("That message is {n} JS8 frames; there is no frame {part}").format(n=len(fr),
                                                                                                part=part + 1))
        frame, i3 = fr[part]
        raw = self.ohsdigi.js8_encode_audio(frame, i3, speed, float(offset))
        audio = np.frombuffer(raw, dtype="<f4")
        peak = float(np.max(np.abs(audio))) or 1.0
        return (audio / peak * 0.95).astype(np.float32)


# jt9-family stdout, stripped of the leading/trailing whitespace a `format`
# statement pads with (see module docstring for the two format strings this
# matches): utc, snr, dt, df, the submode letter, then the rest of the line
# verbatim - the message token, and only sometimes a trailing "aN" flag,
# which _AP_RE below pulls off the same way ft8.py's _JT9_MARKER_RE does.
_LINE_RE = re.compile(
    r"^(?P<utc>\d{6})\s*(?P<snr>-?\d+)\s+(?P<dt>-?\d+\.\d)\s+(?P<df>\d+)\s+(?P<submode>[A-Z])\s+(?P<frame>.+)$"
)
_AP_RE = re.compile(r"\s(?P<ap>a\d)$")


def _read_frame(ev: dict, frame: str, i3bit: int, lb) -> dict:
    """Add what a frame says (ohsdigi's js8_unpack, JS8Call's own reading)
    to an event: text as JS8Call shows it, kind, first/last, and the
    sender as `call` (with `grid`, `to`) when the frame names a station
    rather than a group or JS8Call's "<....>" placeholder."""
    u = lb.js8_unpack(frame, i3bit)
    ev.update(frame=frame, i3bit=i3bit, text=str(u["text"]).rstrip(), kind=u["kind"],
              first=bool(u["first"]), last=bool(u["last"]))
    who = u.get("from") or ""
    if who and not who.startswith(("@", "<")):
        ev["call"] = who
        if u.get("grid"):
            ev["grid"] = u["grid"]
    if u.get("to"):
        ev["to"] = u["to"]
    return ev


def _ohsdigi_decode(lb, ints: np.ndarray, slot_t0: float, speed: str = JS8_DEFAULT_SPEED) -> list[dict]:
    """One period through ohsdigi, as events."""
    out = []
    for d in lb.js8_decode(ints.tobytes(), speed, depth=DEPTH):
        ev = {"mode": "js8", "slot": slot_t0, "snr": int(d["snr"]), "dt": _jt9_round1(float(d["dt"])),
              "df": _jt9_nint(float(d["freq"])), "speed": speed}
        out.append(_read_frame(ev, d["frame"], int(d["i3bit"]), lb))
    return out


# The frame and its header digit inside js8's 22-character message field.
_FRAME_RE = re.compile(r"^(?P<frame>[0-9A-Za-z+-]{12})\s+(?P<i3>[0-7])$")


def _parse_jt9_output(stdout: str, slot_t0: float, lb=None) -> list[dict]:
    """js8's stdout as events (module docstring). With `lb` (ohsdigi), each
    frame is read as JS8Call reads it; without, `text` is what js8 printed."""
    events = []
    for line in stdout.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        frame = m.group("frame")
        ap_m = _AP_RE.search(frame)
        ap = None
        if ap_m:
            frame = frame[:ap_m.start()]
            ap = ap_m.group("ap")
        # The Fortran format pads the message field to 22 characters: the
        # 12-character frame, blanks, and the header digit in column 22.
        frame = frame.rstrip()
        ev = {"mode": "js8", "slot": slot_t0, "snr": int(m.group("snr")), "dt": float(m.group("dt")),
              "df": int(m.group("df")), "text": frame}
        if ap:
            ev["ap"] = ap
        fm = _FRAME_RE.match(frame)
        if fm and lb is not None:
            _read_frame(ev, fm.group("frame"), int(fm.group("i3")), lb)
        else:
            # Without ohsdigi the frame stays as js8 printed it; a frame is
            # never a standard message (it has no spaces), so this adds
            # nothing in practice and is kept for the shape of the event.
            ev.update(_parse_standard(frame))
        events.append(ev)
    return events


def _pcm16(pcm: np.ndarray) -> np.ndarray:
    return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2")


def _write_wav16(path: Path, ints: np.ndarray) -> None:
    n = len(ints)
    byte_rate = int(FS) * 2
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n * 2))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, int(FS), byte_rate, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", n * 2))
        f.write(ints.tobytes())


TMP_PREFIX = "ohsnb-js8-"
KEEP = {"jt9_wisdom.dat"}
STALE_S = 24 * 3600

_live_dirs: set[str] = set()
_live_lock = threading.Lock()
_swept = False


@atexit.register
def _remove_live_dirs() -> None:
    with _live_lock:
        dirs = list(_live_dirs)
        _live_dirs.clear()
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _sweep_stale(now: float | None = None) -> None:
    global _swept
    with _live_lock:
        if _swept:
            return
        _swept = True
        live = set(_live_dirs)
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(tempfile.gettempdir()))
    except OSError:
        return
    for e in entries:
        if not e.name.startswith(TMP_PREFIX):
            continue
        try:
            if not e.is_dir(follow_symlinks=False) or e.path in live or now - e.stat().st_mtime < STALE_S:
                continue
        except OSError:
            continue
        shutil.rmtree(e.path, ignore_errors=True)


class Decoder:
    """feed() buffers one period's audio by its timestamp and, a few
    seconds before the period ends, decodes it on a worker thread - ohsdigi,
    or js8 when ohsdigi is absent or raises - in one pass, q65.py's shape
    (not FT8's early-plus-final two): one decode easily finishes inside a
    15 s period's own slack (ohsdigi takes about 0.1 s at depth 3).

    `ohsdigi` is the module to decode with (default: the one that loaded;
    None decodes with js8 only).

    EARLY_S is FT8's own 13.5 s (ft8.py), not Q65's "period - 5" - measured
    (not assumed): with Q65's formula transplanted here (15 - 5 = 10.0),
    decoding js8call's own test WAV A_2_6.wav found only 4 of its 6 named
    decodes, because a transmission starting after 10 s of a 15 s period is
    real and common (JS8 and FT8 share the same 79-symbol frame, so the
    same slot occupancy) and this decoder's one pass only ever sees audio
    captured up to the moment it copies the buffer. Q65's "-5" was sized
    for its own 60 s period (the last 5 s is a twelfth of it); the same five
    seconds is a third of JS8 Normal's 15 s - far too much to give up.
    13.5 s (FT8's own figure, same period length, same WSJT-X release-notes
    citation in ft8.py) leaves only the last 1.5 s unseen, and found all 6
    of A_2_6.wav's decodes."""

    EARLY_S = 13.5

    def __init__(self, emit: Callable[[dict], None], calls: Callable[[], tuple[str, str]] | None = None,
                 ohsdigi=..., speed: str = JS8_DEFAULT_SPEED, **_opts):
        self.emit = emit
        self.calls = calls
        self.ohsdigi = _OHSDIGI_JS8 if ohsdigi is ... else _with_js8(ohsdigi)
        self.speed = speed
        sp = JS8_SPEEDS[speed]
        self.period, self.letter = sp.period, sp.letter
        self.slot_n = int(round(self.period * FS))
        self.early_n = int(round(early_s(speed) * FS))
        self._tmpdir: str | None = None
        self._dir_lock = threading.Lock()
        self._busy = 0
        self._closed = False
        self.reset()

    def reset(self) -> None:
        self._slot_t0 = None
        self._pcm = np.zeros(self.slot_n, dtype=np.float32)
        self._got = 0
        self._end = 0
        self._started_this_slot = False

    def close(self) -> None:
        with self._dir_lock:
            self._closed = True
            if self._busy == 0:
                self._drop_dir()

    def _drop_dir(self) -> None:
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            with _live_lock:
                _live_dirs.discard(self._tmpdir)
            self._tmpdir = None

    def _enter(self) -> str | None:
        with self._dir_lock:
            if self._closed:
                return None
            if self._tmpdir is None or not os.path.isdir(self._tmpdir):
                self._tmpdir = tempfile.mkdtemp(prefix=TMP_PREFIX)
                with _live_lock:
                    _live_dirs.add(self._tmpdir)
            return self._tmpdir

    def _leave(self, workdir: str | None) -> None:
        with self._dir_lock:
            self._busy -= 1
            if self._busy:
                return
            if self._closed:
                self._drop_dir()
                return
            if workdir is None:
                return
            try:
                entries = list(os.scandir(workdir))
            except OSError:
                return
            for e in entries:
                if e.name not in KEEP:
                    try:
                        os.unlink(e.path)
                    except OSError:
                        pass

    def _open(self, slot_t0: float) -> None:
        self._slot_t0 = slot_t0
        self._pcm = np.zeros(self.slot_n, dtype=np.float32)
        self._got = 0
        self._end = 0
        self._started_this_slot = False

    def _enough(self) -> bool:
        return self._got >= int(0.5 * self.period * FS)

    def feed(self, audio: np.ndarray, t: float) -> None:
        if self.ohsdigi is None and not _JS8:
            return
        x = np.asarray(audio, dtype=np.float32)
        while len(x):
            if self._slot_t0 is None or t >= self._slot_t0 + self.period - 0.5 / FS:
                if self._slot_t0 is not None and self._enough() and not self._started_this_slot:
                    self._start(self._slot_t0, self._pcm.copy())
                self._open(math.floor(t / self.period + 1e-9) * self.period)
            pos = max(0, int(round((t - self._slot_t0) * FS)))
            n = min(len(x), self.slot_n - pos)
            if n <= 0:
                t = self._slot_t0 + self.period
                continue
            self._pcm[pos:pos + n] = x[:n]
            self._got += n
            self._end = max(self._end, pos + n)
            x = x[n:]
            t += n / FS
            if not self._started_this_slot and self._end >= self.early_n and self._enough():
                self._start(self._slot_t0, self._pcm.copy())

    def _start(self, slot_t0: float, pcm: np.ndarray) -> threading.Thread:
        self._started_this_slot = True
        with self._dir_lock:
            self._busy += 1
        th = threading.Thread(target=self._decode_slot, args=(slot_t0, pcm), daemon=True)
        th.start()
        return th

    def _decode_slot(self, slot_t0: float, pcm: np.ndarray) -> None:
        workdir = None
        try:
            ints = _pcm16(pcm)
            if self.ohsdigi is not None:
                try:
                    events = _ohsdigi_decode(self.ohsdigi, ints, slot_t0, self.speed)
                except Exception as exc:  # noqa: BLE001 - ohsdigi raising is its bug; js8, if here, still decodes
                    if not _JS8:
                        raise
                    _say_once("js8-ohsdigi-raised", "ohsdigi failed to decode a JS8 period; js8 decodes instead: %s",
                              exc, exc_info=True)
                else:
                    for ev in events:
                        self.emit(ev)
                    return
            workdir = self._enter()
            if workdir is None:
                return
            _sweep_stale()
            wav_path = Path(workdir) / f"js8_{slot_t0:.3f}_{threading.get_ident()}.wav"
            _write_wav16(wav_path, ints)
            mycall, dxcall = _calls_now(self.calls)
            result = run_decoder_tool("js8", [_JS8, "-8", "-b", self.letter, "-d", str(DEPTH),
                                              "-c", _jt9_call(mycall), "-x", _jt9_call(dxcall), str(wav_path)],
                                      workdir)
            for ev in _parse_jt9_output(result.stdout, slot_t0, _with_js8(_OHSDIGI)):
                ev["speed"] = self.speed
                self.emit(ev)
        except Exception as exc:  # a stuck/crashed decoder must not take the daemon down with it
            self.emit({"mode": "js8", "slot": slot_t0, "error": str(exc)})
        finally:
            self._leave(workdir)


def early_s(speed: str) -> float:
    """When a speed's single decode pass runs, seconds into its period:
    Normal's measured 13.5 s (the Decoder docstring says why), which is
    1.5 s before the end, for any speed whose frame has ended by then;
    for Ultra, whose 2.5 s mark is inside the frame, just after it ends."""
    sp = JS8_SPEEDS[speed]
    end = sp.start + sp.duration + 0.3
    return sp.period - 1.5 if sp.period - 1.5 >= end else min(end, sp.period - 0.2)


class AllSpeedsDecoder:
    """Every JS8 speed at once, as JS8Call decodes them: one Decoder per
    speed on the same audio, each on its own period. A frame two passes
    both report (the same frame on the same offset within DUP_WINDOW_S)
    is emitted once, the first time."""

    def __init__(self, emit: Callable[[dict], None], calls: Callable[[], tuple[str, str]] | None = None,
                 ohsdigi=..., speeds=SPEEDS, **_opts):
        self.emit = emit
        self._seen: dict[tuple[str, int], float] = {}
        self._lock = threading.Lock()
        self.decoders = [Decoder(self._emit, calls=calls, ohsdigi=ohsdigi, speed=sp) for sp in speeds]

    def _emit(self, ev: dict) -> None:
        if ev.get("frame"):
            key = (str(ev["frame"]), int(round(float(ev.get("df") or 0) / 10.0)))
            t = float(ev.get("slot") or 0.0)
            with self._lock:
                for k, seen in list(self._seen.items()):
                    if t - seen > DUP_WINDOW_S:
                        del self._seen[k]
                if key in self._seen and abs(t - self._seen[key]) <= DUP_WINDOW_S:
                    return
                self._seen[key] = t
        self.emit(ev)

    def feed(self, audio: np.ndarray, t: float) -> None:
        for d in self.decoders:
            d.feed(audio, t)

    def reset(self) -> None:
        for d in self.decoders:
            d.reset()

    def close(self) -> None:
        for d in self.decoders:
            d.close()
