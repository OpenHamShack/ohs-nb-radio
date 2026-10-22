"""Q65-60A: decoded and encoded by ohsdigi, OpenHamShack's own port of
WSJT-X 2.7.0's Q65, with WSJT-X's jt9 and q65code as the fallback where
they are installed - the same arrangement as FT8 (ft8.py).

**ohsdigi first (10/10/2026).** rust/ohsdigi/src/q65 ports the QRA codec,
genq65 and the decoder `jt9 -3` runs (q65_decode.f90 and the q65 module).
On test periods made with ohsdigi's encoder and with WSJT-X's own q65sim
(fading included), at every period and submode, it prints the same lines
jt9 prints - text, SNR, DT, frequency and the "q" flag
(rust/ohsdigi/tests/q65_golden.rs) - and its tones are q65code's. It needs
nothing installed, so Q65 now works in the store images and desktop
bundles, which never carried WSJT-X (jt9 brings Qt with it). Where ohsdigi
is missing or raises, jt9 decodes instead if present.

**The transmitted waveform is now WSJT-X's own** (ohsdigi's
q65_encode_audio: Modulator.cpp's unshaped continuous-phase FSK and its
short fade at the end), where it was a switched tone with a ramp the
app made itself; q65code and that tone generator remain the fallback.

AMSAT-DL's QO-100 NB bandplan reserves 10489.540-.580 MHz for "narrow
digimodes... (<=500 Hz)" (docs/qo100-research.md); the geostationary
transponder has no meaningful Doppler or multipath for a fixed ground
station to spread across, which is the entire reason Q65 offers submodes
B-E (wider tone spacing, traded for speed: WSJT-X's own Quick-Start Guide
to Q65, https://wsjt.sourceforge.io/Q65_Quick_Start.pdf, "basic parameters
of Q65... minimum tone spacings", and its own worked examples only reach
for B/C/D/E on scatter and EME paths with real frequency spread). So this
only offers the narrowest, most sensitive submode, "A": at 10489.5xx MHz's
flat 0.75 ppm or so of thermal drift this transponder does not move enough
in 60 s to need anything wider, and A's occupied bandwidth (108 Hz at 60 s,
from the same table) fits the narrow-digimode segment many times over.
No on-air convention for a QO-100 NB Q65 period was found (the research
doc's own notes mark Q65 "[unverified]" for calling frequency, let alone
period) - 60 s is a reasoned default: deep enough to be worth having
alongside FT8 (-27.6 dB vs FT8's ~-20 to -24 dB, same source) without
making a single exchange a five-minute wait the way 300 s would. ohsdigi
decodes every period and submode (q65_decode's arguments); offering them
is a later change to the engine and the UI.

Not implemented: WSJT-X's own "Enable averaging" (several periods combined
before a weak signal decodes) - its benefit is real but it is a different
interaction model from FT8/FT4's "decode this slot, now", and bolting it
on had its own risks worth a design pass of its own rather than folding
into this one. ohsdigi does not port it either. This decodes one period at
a time, same as FT8/FT4 do.
"""
from __future__ import annotations

import atexit
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .. import host
from ..i18n.text import _

from .ft8 import (_OHSDIGI, OHSDIGI_WHY_NOT, run_decoder_tool, _call_ok, _calls_now, _jt9_call, _jt9_nint, _jt9_round1,
                  _parse_standard, _say_once)

FS = 12_000.0
PERIOD_S = 60.0                  # T/R sequence length: see the module docstring
SUBMODE = "A"
TONE_SPACING_HZ = 1.667          # Q65-60A, WSJT-X's Quick-Start Guide to Q65
SYMBOL_S = 0.6                   # 60 s / 100 symbol slots = 0.6 s/symbol, per the same table
N_SYMBOLS = 85                   # 63 + 22 sync (the Quick-Start Guide, "FEC in Q65")
N_TONES = 65

# Where a transmission starts in its period: WSJT-X's Modulator starts
# Q65-60 1 s in (0.5 s only for Q65-15 and -30), and its decoder's DT 0 is
# the same instant (ohsdigi.Q65_PERIODS[60]["start"]).
START_S = 1.0

_JT9 = host.find_tool("jt9")
_Q65CODE = host.find_tool("q65code")


def _with_q65(ohsdigi):
    """`ohsdigi` if it carries Q65 (built from 10/10/2026 on), else None."""
    if ohsdigi is not None and hasattr(ohsdigi, "q65_decode") and hasattr(ohsdigi, "q65_encode_audio"):
        return ohsdigi
    return None


_OHSDIGI_Q65 = _with_q65(_OHSDIGI)
CAN_DECODE = bool(_OHSDIGI_Q65 is not None or _JT9)
CAN_ENCODE = bool(CAN_DECODE and (_OHSDIGI_Q65 is not None or (_JT9 and _Q65CODE)))
AVAILABLE = CAN_ENCODE
_NO_OHSDIGI = OHSDIGI_WHY_NOT or "this ohsdigi was built without Q65"
# As FT8's: the store image carries ohsdigi and never WSJT-X, so there Q65
# missing means ohsdigi did not load.
WHY_UNAVAILABLE = (f"Q65 needs OpenHamShack's decoder (ohsdigi), which did not load in this app's image "
                   f"({_NO_OHSDIGI}); reinstall the app" if host.STORE
                   else f"Q65 cannot be received here ({_NO_OHSDIGI}). " + host.hint("wsjtx"))


def describe_decoder() -> str:
    """Which decoder Q65 uses here, for the diagnostics report."""
    if _OHSDIGI_Q65 is not None:
        return f"ohsdigi, jt9 as fallback ({_JT9})" if _JT9 else "ohsdigi; no jt9, so no fallback"
    return f"jt9 ({_JT9 or 'not found'}); no ohsdigi: {_NO_OHSDIGI}"


def _channel_symbols(message: str) -> list[int]:
    """Run q65code and read its "Channel symbols (85 total)" block: unlike
    ft8code/ft4code's single line of single digits, q65code's are 0..64
    (two digits) wrapped over several lines, so every line after the
    header up to N_SYMBOLS values is read, not just the next one.

    q65code has no ft8code-style "*** bad message ***" refusal (checked:
    an unpackable message quietly becomes the same all-but-blank codeword
    as an empty one) - there is nothing here to catch that, so a message
    this cannot pack sends sense-free tones instead of raising. The UI's
    own standard-message templates (CQ, a reply, a report) are what every
    other mode relies on to only ever offer packable text; this is no
    worse off than they are, and no better."""
    out = subprocess.run([_Q65CODE, message], capture_output=True, text=True, timeout=10,
                         **host.no_console()).stdout
    lines = out.splitlines()
    try:
        idx = next(i for i, l in enumerate(lines) if "Channel symbols" in l)
    except StopIteration:
        raise ValueError(_("q65code produced no 'Channel symbols' line for {message}: {output}").format(
            message=repr(message), output=repr(out)))
    syms: list[int] = []
    for line in lines[idx + 1:]:
        if not line.strip():
            break
        syms.extend(int(v) for v in line.split())
        if len(syms) >= N_SYMBOLS:
            break
    if len(syms) != N_SYMBOLS:
        raise ValueError(_("q65code gave {n} channel symbols for {message}, expected {want}").format(
            n=len(syms), message=repr(message), want=N_SYMBOLS))
    return syms


def _tone_audio(symbols: list[int], offset: float) -> np.ndarray:
    """65-tone FSK at TONE_SPACING_HZ, phase held continuous from one
    symbol to the next (so there is no click at a symbol boundary) but
    the frequency itself switched abruptly rather than Gaussian-smoothed
    the way ft8.py's _gfsk_audio shapes FT8/FT4's tones. Checked against
    jt9 -3 (tests/test_modes_q65.py): a plain switched tone decodes
    cleanly at a clean SNR. WSJT-X's own Q65 modulator likely shapes its
    tones too, for a tidier transmitted spectrum next to other QO-100 NB
    traffic; reproducing that exactly (unlike FT8/FT4's GFSK, which NB
    already had to study for ohsdigi) was not done here for a first cut -
    see docs/ideas-2026-10.md."""
    nsps = int(round(SYMBOL_S * FS))
    n = len(symbols)
    t = np.arange(nsps)
    phase = 0.0
    out = np.empty(n * nsps, np.float64)
    for i, s in enumerate(symbols):
        f = offset + s * TONE_SPACING_HZ
        dphi = 2 * math.pi * f / FS
        out[i * nsps:(i + 1) * nsps] = np.sin(phase + dphi * t)
        phase = (phase + dphi * nsps) % (2 * math.pi)
    nramp = int(round(nsps / 8.0))
    g = np.cos(math.pi * np.arange(nramp) / nramp)
    out[:nramp] *= (1.0 - g) / 2.0
    out[len(out) - nramp:] *= (1.0 + g) / 2.0
    return out.astype(np.float32)


class Encoder:
    """render(text="CQ GM4BRI IO86", offset=1500.0) -> float32 audio, the
    whole 51 s (85 x 0.6 s) transmission, un-slotted (the caller places it
    in its 60 s period, START_S in, as ft8.py's does). ohsdigi's waveform
    (WSJT-X's own) where ohsdigi is built, else q65code's tones through
    _tone_audio. `ohsdigi` picks the module (None: q65code)."""

    def __init__(self, ohsdigi=...):
        self.ohsdigi = _OHSDIGI_Q65 if ohsdigi is ... else _with_q65(ohsdigi)

    def render(self, text: str = "", offset: float = 1500.0, **_opts) -> np.ndarray:
        if self.ohsdigi is not None:
            try:
                raw = self.ohsdigi.q65_encode_audio(text, 60, SUBMODE, float(offset))
            except ValueError as exc:   # BadMessage: WSJT-X would not send it either
                raise ValueError(str(exc)) from exc
            audio = np.frombuffer(raw, dtype="<f4")
        else:
            if not (_JT9 and _Q65CODE):
                raise RuntimeError(WHY_UNAVAILABLE)
            audio = _tone_audio(_channel_symbols(text), offset)
        peak = float(np.max(np.abs(audio))) or 1.0
        return (audio / peak * 0.95).astype(np.float32)


_LINE_RE = re.compile(
    # jt9 -3's own stdout line: a leading field that is not a reliable
    # clock (measured: "0000" or "****" depending on the WAV's name, never
    # a real hhmmss - FT8/FT4 discard this field too, so this only differs
    # in width), SNR, DT, df, then Q65's own sync-tone marker ":" (where
    # FT8/FT4 print "~"/"+"), then the text.
    r"^\S+\s+(?P<snr>-?\d+)\s+(?P<dt>-?\d+\.\d)\s+(?P<df>\d+)\s+:\s+(?P<text>.+?)\s*$"
)
# The Quick-Start Guide's "q#" flags: first digit is which a priori fields
# were used (0 none .. 4 both calls and the reply type), an optional second
# is how many periods "Enable averaging" combined - jt9 prints it even
# though this never turns averaging on, always "0" or absent.
_MARKER_RE = re.compile(r"\s+q(?P<ap>\d)(?P<avg>\d)?\s*$")


def _parse_jt9_output(stdout: str, slot_t0: float) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        text = m.group("text").strip()
        mk = _MARKER_RE.search(text)
        marker = {}
        if mk:
            text = text[:mk.start()].rstrip()
            marker = {"ap": f"q{mk.group('ap')}"}
            if mk.group("avg"):
                marker["averaged"] = int(mk.group("avg"))
        ev = {"mode": "q65", "slot": slot_t0, "snr": int(m.group("snr")), "dt": float(m.group("dt")),
              "df": int(m.group("df")), "text": text}
        ev.update(marker)
        ev.update(_parse_standard(text))
        events.append(ev)
    return events


def _ohsdigi_decode(lb, ints: np.ndarray, slot_t0: float, mycall: str, dxcall: str) -> list[dict]:
    """One period through ohsdigi, as the events jt9's output becomes: DT
    to a tenth and frequency to a hertz as jt9 prints them, and the "q"
    flag jt9 prints after every decode."""
    out = []
    for d in lb.q65_decode(ints.tobytes(), 60, SUBMODE, mycall=mycall if _call_ok(mycall) else "",
                           dxcall=dxcall if _call_ok(dxcall) else ""):
        text = str(d["text"]).strip()
        ev = {"mode": "q65", "slot": slot_t0, "snr": int(d["snr"]), "dt": _jt9_round1(float(d["dt"])),
              "df": _jt9_nint(float(d["freq"])), "text": text, "ap": f"q{int(d['ap'])}"}
        if int(d.get("averaged") or 1) >= 2:
            ev["averaged"] = int(d["averaged"])
        ev.update(_parse_standard(text))
        out.append(ev)
    return out


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


TMP_PREFIX = "ohsnb-q65-"
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
    or jt9 where ohsdigi is absent or raises - in one pass, not FT8's
    early-plus-final two (a 60 s period has far more slack before the next
    one than a 15 s FT8 slot does). `ohsdigi` picks the module (None: jt9
    only)."""

    EARLY_S = PERIOD_S - 5.0

    def __init__(self, emit: Callable[[dict], None], calls: Callable[[], tuple[str, str]] | None = None,
                 ohsdigi=..., **_opts):
        self.emit = emit
        self.calls = calls
        self.ohsdigi = _OHSDIGI_Q65 if ohsdigi is ... else _with_q65(ohsdigi)
        self.slot_n = int(round(PERIOD_S * FS))
        self.early_n = int(round(self.EARLY_S * FS))
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
        return self._got >= int(0.5 * PERIOD_S * FS)

    def feed(self, audio: np.ndarray, t: float) -> None:
        if self.ohsdigi is None and not _JT9:
            return
        x = np.asarray(audio, dtype=np.float32)
        while len(x):
            if self._slot_t0 is None or t >= self._slot_t0 + PERIOD_S - 0.5 / FS:
                if self._slot_t0 is not None and self._enough() and not self._started_this_slot:
                    self._start(self._slot_t0, self._pcm.copy())
                self._open(math.floor(t / PERIOD_S + 1e-9) * PERIOD_S)
            pos = max(0, int(round((t - self._slot_t0) * FS)))
            n = min(len(x), self.slot_n - pos)
            if n <= 0:
                t = self._slot_t0 + PERIOD_S
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
            mycall, dxcall = _calls_now(self.calls)
            if self.ohsdigi is not None:
                try:
                    events = _ohsdigi_decode(self.ohsdigi, ints, slot_t0, mycall, dxcall)
                except Exception as exc:  # noqa: BLE001 - ohsdigi raising is its bug; jt9, if here, still decodes
                    if not _JT9:
                        raise
                    _say_once("q65-ohsdigi-raised", "ohsdigi failed to decode a Q65 period; jt9 decodes instead: %s",
                              exc, exc_info=True)
                else:
                    for ev in events:
                        self.emit(ev)
                    return
            workdir = self._enter()
            if workdir is None:
                return
            _sweep_stale()
            wav_path = Path(workdir) / f"q65_{slot_t0:.3f}_{threading.get_ident()}.wav"
            _write_wav16(wav_path, ints)
            result = run_decoder_tool("jt9", [_JT9, "-3", "-p", str(int(PERIOD_S)), "-b", SUBMODE,
                                              "-c", _jt9_call(mycall), "-x", _jt9_call(dxcall), str(wav_path)],
                                      workdir)
            for ev in _parse_jt9_output(result.stdout, slot_t0):
                self.emit(ev)
        except Exception as exc:  # a stuck/crashed decoder must not take the daemon down with it
            self.emit({"mode": "q65", "slot": slot_t0, "error": str(exc)})
        finally:
            self._leave(workdir)
