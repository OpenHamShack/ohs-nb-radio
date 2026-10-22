"""FT8 and FT4: both UTC-slotted, both encoded and decoded by ohsdigi, our
own port of WSJT-X 2.7.0, with WSJT-X's own tools as the fallback.

Encoding is our own when it can be: ohsdigi (rust/ohsdigi, imported as
ohscore.ohsdigi), a Rust port of WSJT-X 2.7.0's message packing, LDPC coding
and GFSK waveform, held bit for bit to WSJT-X's ft8code and ft4code by a
corpus of several thousand messages (docs/digimodes-rust.md). Until 0.1.x
this module ran ft8code/ft4code for every transmission and kept nothing of
its own, on the grounds that a second implementation would drift from
WSJT-X's; the corpus is what answers that now. What the port bought:
FT4 can be sent where WSJT-X ships no ft4code (Windows), the waveform is
WSJT-X's own rather than an approximation of it, and there is no child
process per transmission. Where ohsdigi is not built (an unusual
architecture, a run from source without tools/build-ohsdigi.sh), encoding
falls back to ft8code/ft4code exactly as before.

Decoding is ohsdigi's too, since 07/10/2026 (Brian's decision): its port of
jt9's FT8 and FT4 decoders matched jt9 decode for decode on every simulated
slot and on 2,659 real QO-100 decodes over a three-hour recording, with no
decode only one of them found. jt9 keeps two roles. It is the fallback:
where ohsdigi is not built, or raises on a slot, jt9 decodes instead,
without the operator being told more than the status saying which decoder
is in use (the log says why, once). And it is the shadow: where both are
present, jt9 decodes every slot as well, after ohsdigi's decodes have gone
out, and any disagreement is logged and counted (decoder_shadow), so a
difference that real signals expose is seen rather than assumed away.
Settings can put jt9 first instead ("ft8Decoder": "jt9"); ohsdigi is then
the shadow, as it was before the switch.

Both modes are UTC-slotted (transmissions start on slot boundaries everyone
agrees on without coordinating: 15 s for FT8, 7.5 s for FT4), which is why
feed() keys off the UTC timestamp its caller passes rather than counting
samples -- the decoder has to know where a slot boundary falls in real
time, and the DESIGN.md contract hands that in as `t` precisely so modes
like this one don't need a wall clock of their own.

A decode takes from a tenth of a second (ohsdigi here) to a second or more
(jt9 on a slow machine) over a 15 s slot's worth of audio, so it runs on a
worker thread (DESIGN.md: "mode decoders that are slow... run on their own
worker thread and never block the RX thread") -- feed() only ever places
audio in a slot buffer and, 13.5 s into the slot (FT8; 6.0 s FT4, see
EARLY_S) and again at its end, hands it to a thread; it never itself blocks
on a decoder finishing.
"""

from __future__ import annotations

import atexit
import importlib
import logging
import math
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import os
from pathlib import Path
from typing import Callable

import numpy as np

from .. import callsign, host
from . import decoder_shadow
from ..i18n.text import _


log = logging.getLogger("ohscore.modes.ft8")

FS = 12_000.0
SLOT_S = {"ft8": 15.0, "ft4": 7.5}
SYMBOL_S = {"ft8": 0.160, "ft4": 0.048}
TONE_SPACING_HZ = {"ft8": 6.25, "ft4": 20.833333333333332}
N_TONES = 8  # FT8 is 8-GFSK; FT4 is 4-GFSK (tones 0..3), so 8 covers both

# A WSJT-X the operator installed: PATH, then WSJT-X's own install folders
# on Windows and macOS (host.find_tool), since its installers never put it
# on PATH. No build carries one any more (see find_tool).
_JT9 = host.find_tool("jt9")
_FT8CODE = host.find_tool("ft8code")
_FT4CODE = host.find_tool("ft4code")


def _load_ohsdigi():
    """ohscore.ohsdigi, or None and why not. Only ImportError means "not
    here": a module that is present but broken in some other way should be
    seen, not quietly replaced by the fallback."""
    try:
        ohsdigi = importlib.import_module(".ohsdigi", __package__.rpartition(".")[0])
    except ImportError as exc:
        return None, str(exc)
    if getattr(ohsdigi, "WSJTX_VERSION", None) != "2.7.0":
        # The corpus it was tested against, and the jt9 that decodes what
        # it sends, are 2.7.0's.
        return None, f"ohsdigi follows WSJT-X {getattr(ohsdigi, 'WSJTX_VERSION', '?')}, not 2.7.0"
    return ohsdigi, ""


def _with_decoder(ohsdigi):
    """`ohsdigi` if it decodes as well as encodes, else None. A module built
    before the decoder was merged (phase 1's) has no ft8_decode: it is
    still the encoder, and jt9 decodes."""
    if ohsdigi is not None and hasattr(ohsdigi, "ft8_decode") and hasattr(ohsdigi, "ft4_decode"):
        return ohsdigi
    return None


_OHSDIGI, OHSDIGI_WHY_NOT = _load_ohsdigi()
_OHSDIGI_DEC = _with_decoder(_OHSDIGI)

# Receiving either mode needs a decoder: ohsdigi's, or jt9. Sending needs an
# encoder for that mode: ohsdigi for both, or else WSJT-X's ft8code /
# ft4code. WSJT-X's Windows build ships ft8code but no ft4code (2.7.0, and
# 3.0.1 as well), so without ohsdigi FT4 is receive-only there. Sending
# without receiving is never offered: a mode is listed only when it can be
# decoded too. Until ohsdigi decoded, both modes needed jt9; now a machine
# with ohsdigi and no WSJT-X has FT8 and FT4 both ways, and from 0.1.10
# its Country column too, from the cty.dat ohscore carries (ohscore/dxcc.py).
CAN_DECODE = bool(_JT9 or _OHSDIGI_DEC is not None)
ENCODER = {v: ("ohsdigi" if _OHSDIGI is not None else ({"ft8": "ft8code", "ft4": "ft4code"}[v] if c else None))
           for v, c in (("ft8", _FT8CODE), ("ft4", _FT4CODE))}
CAN_ENCODE = {v: bool(CAN_DECODE and ENCODER[v]) for v in ("ft8", "ft4")}
AVAILABLE = CAN_ENCODE["ft8"] and CAN_ENCODE["ft4"]
# The store image carries ohsdigi and never jt9 (store/<app>/Containerfile),
# so there FT8 and FT4 missing means ohsdigi did not load: say that, and
# why, rather than suggest installing WSJT-X into an image nobody can
# install into.
WHY_UNAVAILABLE = (f"FT8 and FT4 need OpenHamShack's decoder (ohsdigi), which did not load in this app's "
                   f"image ({OHSDIGI_WHY_NOT or 'built without its decoder'}); reinstall the app"
                   if host.STORE else host.hint("wsjtx"))
WHY_NO_FT4_ENCODER = "FT4 receive only: this WSJT-X has no ft4code to encode FT4"

# The "ft8Decoder" setting (ohscore/state.py): "auto" decodes with ohsdigi
# where it can, jt9 otherwise; "jt9" puts jt9 first - WSJT-X's own decoder,
# for an operator who wants it or wants to compare. Either way the other
# one, where present, is the fallback and the shadow.
DECODER_CHOICES = ("auto", "jt9")


def describe_encoder() -> str:
    """Which encoder FT8 and FT4 send with, for the start-up facts and the
    diagnostics report: ohsdigi and the file it loaded from, or WSJT-X's
    tools and why ohsdigi was not used."""
    if _OHSDIGI is not None:
        return f"ohsdigi {getattr(_OHSDIGI, '__version__', '?')} ({getattr(_OHSDIGI, '__file__', '?')})"
    return (f"ft8: {ENCODER['ft8'] or 'none'}, ft4: {ENCODER['ft4'] or 'none'} "
            f"(no ohsdigi: {OHSDIGI_WHY_NOT})")


def describe_decoder() -> str:
    """Which decoders this installation has, for the start-up facts and the
    diagnostics report. Which one a running radio is using - the setting,
    and a fallback after a failure, decide that - is its ft8DecoderInUse
    status."""
    if _OHSDIGI_DEC is not None:
        return (f"ohsdigi, jt9 as fallback and shadow ({_JT9})" if _JT9
                else "ohsdigi; no jt9, so no fallback or shadow")
    why = OHSDIGI_WHY_NOT or "this ohsdigi was built without the decoder"
    return f"jt9 ({_JT9 or 'not found'}); no ohsdigi: {why}"


BAD_MESSAGE = '*** bad message ***'


def _channel_symbols(codec_bin: str, message: str) -> str:
    """Run ft8code/ft4code and pull the 79 (FT8) or 105 (FT4) tone digits
    off the "Channel symbols" line -- the two space-separated digit groups
    either side of (and including) the sync words, concatenated back into
    one string of '0'..'7'.

    A message WSJT-X cannot pack it answers with "*** bad message ***" and
    symbols that are all zero (ft8code) or whatever was in memory
    (ft4code); that is refused here, as ohsdigi refuses it, rather than
    sent."""
    out = subprocess.run([codec_bin, message], capture_output=True, text=True, timeout=10,
                         **host.no_console()).stdout
    lines = out.splitlines()
    try:
        idx = next(i for i, l in enumerate(lines) if "Channel symbols" in l)
    except StopIteration:
        raise ValueError(_("{codec} produced no 'Channel symbols' line for {message}: {output}").format(
            codec=codec_bin, message=repr(message), output=repr(out)))
    if len(lines) > 2 and BAD_MESSAGE in lines[2]:
        raise ValueError(_("{message} cannot be sent: WSJT-X makes it \"{bad}\"").format(
            message=repr(message), bad=BAD_MESSAGE))
    return lines[idx + 2].replace(" ", "")


# WSJT-X's Gaussian filter bandwidth-time products: gen_ft8wave is called
# with BT = 2.0, gen_ft4wave fixes 1.0 (WSJT-X 2.7.0, lib/ft8/gen_ft8wave.f90,
# lib/ft4/gen_ft4wave.f90).
GFSK_BT = {"ft8": 2.0, "ft4": 1.0}


def _gfsk_pulse(bt: float, t: np.ndarray) -> np.ndarray:
    """WSJT-X's gfsk_pulse (lib/ft2/gfsk_pulse.f90): one symbol's frequency
    step through a Gaussian filter of bandwidth-time product `bt`, `t` in
    symbols from the symbol's centre. Equivalently a Gaussian of standard
    deviation sqrt(ln 2) / (2 pi bt) symbols - 0.066 of a symbol at BT 2 -
    convolved with the one-symbol rectangle."""
    c = math.pi * math.sqrt(2.0 / math.log(2.0))
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return 0.5 * (erf(c * bt * (t + 0.5)) - erf(c * bt * (t - 0.5)))


def _gfsk_audio(tones: str, variant: str, base_freq: float) -> np.ndarray:
    """The fallback's waveform, for when ohsdigi is absent: WSJT-X's
    gen_ft8wave / gen_ft4wave in numpy, from ft8code's 79 tones or
    ft4code's 105 (its 103 plus the two ramp symbols, tone 0, at either
    end). Continuous-phase GFSK: each symbol's frequency step is smoothed by
    a pulse three symbols long and the smoothed frequency integrated to
    phase, so the spectrum stays inside the channel; the first and last
    symbols are ramped in amplitude so a transmission starts and stops
    without a click.

    This used to be a Gaussian convolution whose width, sym_n / (2 BT)
    samples, was chosen until jt9 decoded the result rather than taken
    from WSJT-X: 0.25 of a symbol at BT 2 against WSJT-X's 0.066, nearly
    four times too wide, and FT4 was given BT 2 as well. jt9 still decoded
    it, but about 5 dB less sensitively than WSJT-X's own waveform (the
    smeared tones put energy between jt9's tone bins). Now it is WSJT-X's
    pulse and framing, and tests/test_ohsdigi.py holds it to ohsdigi's
    waveform, which is itself proven against WSJT-X's ft8sim. Done in
    double precision, so it differs from ohsdigi's single-precision port by
    the phase drift that rounding leaves in WSJT-X's, a few parts in 10^3
    of full scale by the end of a transmission - far inside anything a
    decoder can see."""
    nsps = int(round(SYMBOL_S[variant] * FS))
    itone = np.array([int(c) for c in tones], dtype=np.float64)
    if variant == "ft4":
        itone = itone[1:-1]                 # gen_ft4wave takes the 103; the ramps are its own
    nsym = len(itone)
    twopi = 2.0 * math.pi
    pulse = _gfsk_pulse(GFSK_BT[variant], (np.arange(1, 3 * nsps + 1) - 1.5 * nsps) / nsps)
    dphi_peak = twopi / nsps                 # hmod = 1: one tone step is one cycle a symbol
    # Each symbol's pulse starts one symbol before the symbol itself, so
    # symbol j's frequency sits in samples (j+1)*nsps ... (j+2)*nsps-1.
    dphi = np.zeros((nsym + 2) * nsps)
    for j in range(nsym):
        dphi[j * nsps:(j + 3) * nsps] += dphi_peak * pulse * itone[j]
    if variant == "ft8":
        # gen_ft8wave's dummy symbols: the first and last tones extended
        # into the pulse tails beyond them, which it then leaves out.
        dphi[:2 * nsps] += dphi_peak * itone[0] * pulse[nsps:]
        dphi[nsym * nsps:] += dphi_peak * itone[-1] * pulse[:2 * nsps]
        dphi = dphi[nsps:(nsym + 1) * nsps]
    dphi += twopi * base_freq / FS
    # phi starts at 0 and each sample is the sine before that sample's step.
    phi = np.concatenate(([0.0], np.cumsum(dphi[:-1])))
    wave = np.sin(phi)
    nramp = int(round(nsps / 8.0)) if variant == "ft8" else nsps
    g = np.cos(twopi * np.arange(nramp) / (2.0 * nramp))
    wave[:nramp] *= (1.0 - g) / 2.0
    wave[len(wave) - nramp:] *= (1.0 + g) / 2.0
    return wave.astype(np.float32)


def _ohsdigi_audio(ohsdigi, text: str, variant: str, offset: float) -> np.ndarray:
    """WSJT-X's own waveform for the message, from ohsdigi. Its BadMessage
    is a ValueError, as the fallback's refusal is, and says why."""
    enc = ohsdigi.encode(variant, text)
    return np.frombuffer(enc.waveform(offset, FS), dtype="<f4")


class Encoder:
    """render(text="CQ GM4BRI IO86", variant="ft8", offset=1500.0).

    `ohsdigi` is the module to encode with (None for ft8code/ft4code); the
    default is what this installation has, and tests pass None to run the
    fallback on a machine that has both."""

    def __init__(self, ohsdigi=...):
        self.ohsdigi = _OHSDIGI if ohsdigi is ... else ohsdigi

    def render(self, text: str = "", variant: str = "ft8", offset: float = 1500.0, **_opts) -> np.ndarray:
        if self.ohsdigi is not None:
            audio = _ohsdigi_audio(self.ohsdigi, text, variant, offset)
        else:
            codec = _FT8CODE if variant == "ft8" else _FT4CODE
            if not (_JT9 and codec):
                raise RuntimeError(WHY_NO_FT4_ENCODER if _JT9 and variant == "ft4" else WHY_UNAVAILABLE)
            audio = _gfsk_audio(_channel_symbols(codec, text), variant, offset)
        peak = float(np.max(np.abs(audio))) or 1.0
        return (audio / peak * 0.95).astype(np.float32)


_STANDARD_MSG_RE = re.compile(
    r"^(?:CQ(?: (?P<cqdx>DX))? (?P<cqcall>[A-Z0-9/]+)(?: (?P<cqgrid>[A-R]{2}[0-9]{2}))?"
    r"|(?P<tocall>[A-Z0-9/]+) (?P<fromcall>[A-Z0-9/]+) (?P<tail>R?-?\d+|RRR|RR73|73|[A-R]{2}[0-9]{2}))$"
)


def _parse_standard(text: str) -> dict:
    """Pull call/grid out of the handful of standard FT8 message shapes
    (CQ, CQ DX, a reply with a report or RRR/RR73/73, or a grid exchange).
    Anything else (free text, telemetry) is passed through with call/grid
    absent -- DESIGN.md's event shape treats those as optional fields, not
    required ones, and guessing at a non-standard message's structure would
    be worse than leaving them out."""
    m = _STANDARD_MSG_RE.match(text.strip())
    if not m:
        return {}
    g = m.groupdict()
    if g.get("cqcall"):
        return {"call": g["cqcall"], "grid": g.get("cqgrid") or ""}
    if g.get("fromcall"):
        out = {"call": g["fromcall"]}
        tail = g.get("tail")
        # RR73 happens to have the same shape as a grid locator (two letters
        # then two digits) purely by coincidence -- it is a procedural
        # signal, not a place, so the literal signal reports/acks are
        # checked first and only an unmatched tail is offered as a grid.
        if tail and tail not in ("RRR", "RR73", "73") and re.match(r"^[A-R]{2}[0-9]{2}$", tail):
            out["grid"] = tail
        return out
    return {}


# When to decode, seconds into the slot. A transmission starts 0.5 s into an
# FT8 slot and lasts 79 x 0.16 = 12.64 s, so it is complete at 13.14 s;
# decoding only when the slot *ended* put every decode 15 s plus jt9's own
# time after the slot began -- after the next slot had started, so a reply
# to a CQ missed the slot it belonged in and went out a whole cycle late.
# WSJT-X decodes FT8 in passes at 11.8, 13.5 and 14.7 s into the slot (ARRL
# news on WSJT-X 2.2.0-rc1, "New WSJT-X Beta Version Offers Significant FT4
# and FT8 Upgrades"); 13.5 s is its main pass and is ours. FT4's 105 x
# 0.048 = 5.04 s from 0.5 s ends at 5.54 s of a 7.5 s slot: 6.0 s.
#
# A second pass at the end of the slot catches what the early one cannot:
# a signal that started late (FT8's decoder searches +-2.5 s of DT -- WSJT-X
# lib/ft8/sync8.f90 -- so a station may legitimately still be sending after
# 13.5 s) and so was cut short. Messages the early pass already reported
# are not reported again.
EARLY_S = {"ft8": 13.5, "ft4": 6.0}


class _SlotRun:
    """One slot's decode passes: what has been reported, so the final pass
    adds only what the early one missed, and the early pass's thread, which
    the final one waits for so the two never race on that record."""

    def __init__(self, slot_t0: float):
        self.slot_t0 = slot_t0
        self.seen: set[str] = set()
        self.events: list[dict] = []        # every pass's decodes, for the slot's log line
        # Passes started and finished, and whether the slot has ended: the
        # pass that finishes last after the end is the one that logs the
        # slot (Decoder._summarise). Counted by the callers of _start, not
        # in it, so a test's stand-in _start leaves them alone.
        self.started = self.done = 0
        self.closed = False
        self.lock = threading.Lock()
        self.early: threading.Thread | None = None


# jt9 works in its current directory: besides the WAV it is given it writes
# decoded.txt and timer.out there on every run, and jt9_wisdom.dat (FFTW's
# plans) when it exits. Each decoder gets one directory in the system temp
# folder for its life. Every run's leftovers are removed when the run ends,
# except the wisdom, which is worth keeping: measured with wsjtx 2.7.0, a
# 15 s FT8 slot took 0.24 s to decode without it and 0.03 s with it. The
# directory itself goes when the decoder is closed (the engine closes one
# it replaces, and its decoder when it stops) or, failing that, when the
# program exits.
#
# Until NB 0.1.2 nothing removed these directories: one was made every time
# a decoder was created or reset, used or not, and each kept the three
# files of its last decode. 1,561 had piled up on the development machine.
TMP_PREFIX = "ohsnb-"            # + "ft8-" / "ft4-" + mkdtemp's suffix; the name 0.1.x used
KEEP = {"jt9_wisdom.dat"}
# A directory of ours this old belongs to a program that did not exit
# cleanly (killed, crashed, or a version from before this cleanup): a
# running decoder writes into its own every slot, which keeps it new.
STALE_S = 24 * 3600

_live_dirs: set[str] = set()
_live_lock = threading.Lock()
_swept = False


@atexit.register
def _remove_live_dirs() -> None:
    """The last chance, for decoders nobody closed."""
    with _live_lock:
        dirs = list(_live_dirs)
        _live_dirs.clear()
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _sweep_stale(now: float | None = None) -> None:
    """Remove other runs' FT8/FT4 directories left behind more than a day
    ago. Once per process, on a decode thread (the temp folder can hold
    thousands of entries). A directory that cannot be removed - in use on
    Windows, another user's - is simply left."""
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
        if not (e.name.startswith(TMP_PREFIX + "ft8-") or e.name.startswith(TMP_PREFIX + "ft4-")):
            continue
        try:
            if not e.is_dir(follow_symlinks=False) or e.path in live or now - e.stat().st_mtime < STALE_S:
                continue
        except OSError:
            continue
        shutil.rmtree(e.path, ignore_errors=True)


class ToolFailed(RuntimeError):
    """A decoder program (jt9, js8) that exited with an error."""


def run_decoder_tool(name: str, argv: list[str], cwd: str) -> subprocess.CompletedProcess:
    """Run jt9 (or JS8Call's js8, its fork) on a WAV, as every slot decoder
    here does. A non-zero exit raises ToolFailed with what it wrote to
    stderr, so the caller's fallback and decoder_shadow.failed see a
    failure and log it; anything on stderr from a run that succeeded is
    logged once.

    Until 17/10/2026 the exit status and stderr were thrown away and only
    stdout was parsed, so a jt9 that crashed on every run looked like one
    that heard nothing: the Mac app's bundled jt9 aborted in 0.05 s on every
    slot (libgcc's __enable_execute_stack refused under the hardened
    runtime) and the shadow logged "jt9 0" for each one, for days, while
    ohsdigi decoded."""
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, cwd=cwd, **host.no_console())
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        how = (f"was killed by signal {-result.returncode}" if result.returncode < 0
               else f"exited with status {result.returncode}")
        tail = " | ".join(err.splitlines()[-4:]) if err else "nothing on stderr"
        raise ToolFailed(f"{name} ({argv[0]}) {how}: {tail}")
    if err:
        _say_once(f"{name}-stderr", "%s wrote to stderr on a run that succeeded: %s", name,
                  " | ".join(err.splitlines()[-4:]), level=logging.WARNING)
    return result


# jt9's mycall/hiscall are character*12 (dec_data): a longer call, valid or
# not, cannot be passed whole, so it is passed as none.
JT9_CALL_MAX = 12


def _call_ok(call: str) -> bool:
    """A callsign by the rule both apps share (ohscore/callsign.py) that jt9
    can take whole."""
    return len(call) <= JT9_CALL_MAX and callsign.valid(call)


def _jt9_call(call: str) -> str:
    """The argument for jt9's -c (MyCall) or -x (DxCall).

    jt9 run without them assumes MyCall K1ABC and DxCall W9XYZ (jt9.f90),
    and its a-priori passes then hunt for messages to K1ABC - on the air,
    where nobody is K1ABC, that is work spent on nothing and a source of
    false "K1ABC ..." decodes, while messages to the operator get no
    help. WSJT-X itself hands its decoder the operator's call and the DX
    Call box; this does the same.

    Two details of how jt9 reads them (jt9.f90, `read (optarg, *) mycall`,
    Fortran list-directed input). An unquoted value ends at the first
    "/", so -c G4XYZ/P would make MyCall G4XYZ - measured: AP-decoded
    messages to G4XYZ appear with that argument and not with the quoted
    one. Quoted in apostrophes the whole call arrives, and WSJT-X's own
    AP set-up (ft8apset, ft4_decode) then decides what to do with a
    nonstandard one: try it as a hashed <call>, or leave it out. And the
    literal "b" means blank, which is how an empty call is said: WSJT-X
    with no call configured passes blanks, which turn the MyCall and DxCall
    AP types off, rather than K1ABC. Anything that is not a callsign at
    all (a typo with a space or punctuation) is treated as empty too,
    rather than passed through to break the argument."""
    call = (call or "").strip().upper()
    if not _call_ok(call):
        return "b"
    return f"'{call}'"


def _calls_now(calls: Callable[[], tuple[str, str]] | None) -> tuple[str, str]:
    """(MyCall, DxCall) for this slot, "" for either that is not a usable
    callsign (see _jt9_call). Never raises: a fault in the caller's
    lookup costs AP decoding, not the decode."""
    if calls is None:
        return "", ""
    try:
        my, dx = calls()
    except Exception:  # noqa: BLE001
        return "", ""
    norm = [(c or "").strip().upper() for c in (my, dx)]
    return tuple(c if _call_ok(c) else "" for c in norm)


class Decoder:
    """feed() only ever buffers and, at the early-decode point and the end
    of each slot, dispatches a worker thread; no decode ever runs on the
    caller's thread.

    Audio is placed in the slot by its timestamp, not appended: a decoder
    started part way through a slot, or a block the engine dropped, would
    otherwise slide everything after it earlier in the slot and give the
    decoder a wrong DT, or nothing it could decode.

    `calls`, if given, returns (MyCall, DxCall) - the operator's call and
    the station the FT8 sequencer is working, "" for none - and is asked
    afresh for every decode, so a QSO started mid-slot steers the next
    slot's a-priori passes as it does in WSJT-X.

    `decoder` is the "ft8Decoder" setting ("auto" or "jt9"), or a callable
    returning it, asked at every decode like `calls`, so a change in
    Settings takes effect from the next slot without a new decoder.
    `on_decoder(text)` hears which decoder produced the decodes ("ohsdigi",
    "jt9", "jt9 (ohsdigi failed)") whenever that changes. `ohsdigi` is the
    module to decode with: the default is this installation's; tests pass
    None for "not built", or a stand-in."""

    def __init__(self, emit: Callable[[dict], None], variant: str = "ft8", offset: float = 1500.0,
                 calls: Callable[[], tuple[str, str]] | None = None,
                 decoder: str | Callable[[], str] = "auto",
                 on_decoder: Callable[[str], None] | None = None, ohsdigi=..., **_opts):
        self.emit = emit
        self.calls = calls
        self.variant = variant
        self.offset = offset
        self.choice = decoder
        self.on_decoder = on_decoder
        self.ohsdigi = _OHSDIGI_DEC if ohsdigi is ... else _with_decoder(ohsdigi)
        self.slot_s = SLOT_S[variant]
        self.slot_n = int(round(self.slot_s * FS))
        self.early_n = int(round(EARLY_S[variant] * FS))
        self._tmpdir: str | None = None     # made by the first jt9 run, not before (see TMP_PREFIX)
        self._dir_lock = threading.Lock()
        # jt9 runs in the working directory and writes fixed names there
        # (decoded.txt, timer.out, its FFTW wisdom at exit), so two runs of
        # one decoder - a shadow run still going when the next pass's
        # fallback starts, say - must not overlap.
        self._jt9_lock = threading.Lock()
        self._busy = 0                      # decode and shadow runs started and not yet finished
        self._closed = False
        self._empty_slots = 0               # slots decoded in a row with nothing found (_summarise)
        self._empty_said = 0.0
        self._skipped = 0                   # slots not decoded for want of audio since that was last said
        self._skip_said = None              # monotonic time it was last said at INFO
        self._in_use = None
        if self.ohsdigi is None:
            _say_once("no-ohsdigi", "FT8/FT4 decode with jt9: no ohsdigi decoder (%s)",
                      OHSDIGI_WHY_NOT or "this ohsdigi was built without one")
        order = self._order()
        # Said before any slot is decoded, so the status shows the decoder
        # from the moment the mode is picked.
        self._report(order[0] if order else "")
        self.reset()

    # ------------------------------------------------------------ which decoder
    def _choice(self) -> str:
        c = self.choice
        if callable(c):
            try:
                c = c()
            except Exception:  # noqa: BLE001 - a broken lookup costs the preference, not the decode
                c = "auto"
        return c if c in DECODER_CHOICES else "auto"

    def _order(self) -> list[str]:
        """The decoders this slot may use, first choice first: the one the
        setting puts first, then the other, where each is present."""
        have = [n for n, ok in (("ohsdigi", self.ohsdigi is not None), ("jt9", bool(_JT9))) if ok]
        if self._choice() == "jt9":
            have.reverse()
        return have

    def _report(self, text: str) -> None:
        if text == self._in_use:
            return
        self._in_use = text
        if self.on_decoder is not None:
            try:
                self.on_decoder(text)
            except Exception:  # noqa: BLE001 - the status line must not cost a decode
                log.exception("ft8 decoder status callback failed")

    # ------------------------------------------------------------ working directory
    def reset(self) -> None:
        self._joining = True      # the next slot is the first since start or reset
        self._first_pos = None    # where in the slot its first audio landed, samples
        self._slot_t0 = None      # UTC second the current slot began, once known
        self._pcm = np.zeros(self.slot_n, dtype=np.float32)
        self._got = 0             # samples of this slot actually received
        self._end = 0             # furthest sample position written
        self._run: _SlotRun | None = None

    def close(self) -> None:
        """No more decoding: remove the working directory, now, or when the
        decode still running finishes. Safe to call twice."""
        with self._dir_lock:
            self._closed = True
            if self._busy == 0:
                self._drop_dir()

    def _drop_dir(self) -> None:
        """Under _dir_lock."""
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            with _live_lock:
                _live_dirs.discard(self._tmpdir)
            self._tmpdir = None

    def _enter(self) -> str | None:
        """The working directory for a jt9 run, made if need be - or
        again, if something removed it. None once closed."""
        with self._dir_lock:
            if self._closed:
                return None
            if self._tmpdir is None or not os.path.isdir(self._tmpdir):
                self._tmpdir = tempfile.mkdtemp(prefix=f"{TMP_PREFIX}{self.variant}-")
                with _live_lock:
                    _live_dirs.add(self._tmpdir)
            return self._tmpdir

    def _leave(self) -> None:
        """After a run (a pass, or a shadow decode): clear what jt9 left
        (it has exited, so nothing holds the files open, which on Windows
        would stop them being deleted), and remove the directory if the
        decoder was closed meanwhile. Only the last run out does either: a
        slot's final pass is already counted while it waits for the early
        one, and a shadow run is counted from before its pass ends, so no
        run ever deletes files from under another."""
        with self._dir_lock:
            self._busy -= 1
            if self._busy:
                return
            if self._closed:
                self._drop_dir()
                return
            workdir = self._tmpdir
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
                        pass          # gone already, or held: close() takes the whole directory

    # ------------------------------------------------------------ slots
    def _open(self, slot_t0: float) -> None:
        self._slot_t0 = slot_t0
        self._pcm = np.zeros(self.slot_n, dtype=np.float32)
        self._got = 0
        self._end = 0
        self._first_pos = None
        self._run = _SlotRun(slot_t0)

    def _enough(self) -> bool:
        # Too little of the slot captured (e.g. we just started) to be worth decoding.
        return self._got >= int(0.5 * self.slot_s * FS)

    def feed(self, audio: np.ndarray, t: float) -> None:
        if self.ohsdigi is None and not _JT9:
            return
        x = np.asarray(audio, dtype=np.float32)
        while len(x):
            if self._slot_t0 is None or t >= self._slot_t0 + self.slot_s - 0.5 / FS:
                if self._slot_t0 is not None:
                    self._close()
                self._open(math.floor(t / self.slot_s + 1e-9) * self.slot_s)
            pos = max(0, int(round((t - self._slot_t0) * FS)))
            if self._first_pos is None:
                self._first_pos = pos
            n = min(len(x), self.slot_n - pos)
            if n <= 0:
                t = self._slot_t0 + self.slot_s
                continue
            self._pcm[pos:pos + n] = x[:n]
            self._got += n
            self._end = max(self._end, pos + n)
            x = x[n:]
            t += n / FS
            if self._run.early is None and self._end >= self.early_n and self._enough():
                # Everything after early_n is still zero. jt9 decodes a WAV
                # cut at 13.5 s exactly as it does one zero-padded to 15 s
                # (measured, wsjtx 2.7.0), but the full length is what it
                # documents reading, so that is what both decoders get.
                with self._run.lock:
                    self._run.started += 1
                self._run.early = self._start(self._run, self._pcm.copy(), None)
        if self._slot_t0 is not None and self._end >= self.slot_n:
            self._close()
            self._slot_t0 = None

    def _close(self) -> None:
        if self._run is not None and self._enough():
            with self._run.lock:
                self._run.closed = True
                self._run.started += 1
            self._start(self._run, self._pcm.copy(), self._run.early)
        elif self._run is not None:
            self._skip(self._run.slot_t0)
        self._joining = False
        self._run = None

    # Skipped slots (too little audio to decode) are said, with why. They
    # were silent until 17/10/2026: a Windows PC getting 37 % of the Pluto's
    # stream over a Tailscale relay decoded nothing for an hour and the log,
    # even with -v, said nothing at all (Windows test, finding 1). The slot
    # the decoder joins part-way through is expected and DEBUG; any other
    # is INFO, the first at once and then at most every SKIP_EVERY_S with a
    # count, so a stream that is short all the time is said once a minute.
    SKIP_EVERY_S = 60.0

    def _skip(self, slot_t0: float) -> None:
        pct = 100.0 * self._got / self.slot_n
        name = self.variant.upper()
        if self._joining and (self._first_pos or 0) > FS:
            log.debug("%s slot %s not decoded: joined part-way through (%.0f %% of its audio)", name,
                      _hms(slot_t0), pct)
            return
        self._skipped += 1
        now = time.monotonic()
        if self._skip_said is None or now - self._skip_said >= self.SKIP_EVERY_S:
            more = (f"; {self._skipped} slots skipped so in the last {now - self._skip_said:.0f} s"
                    if self._skip_said is not None else "")
            log.info("%s slot %s not decoded: only %.0f %% of its audio arrived (under half; the receive "
                     "stream is losing samples, or receive stopped)%s", name, _hms(slot_t0), pct, more)
            self._skip_said = now
            self._skipped = 0
        else:
            log.debug("%s slot %s not decoded: only %.0f %% of its audio arrived", name, _hms(slot_t0), pct)

    def _start(self, run: _SlotRun, pcm: np.ndarray, after: threading.Thread | None) -> threading.Thread:
        with self._dir_lock:
            self._busy += 1
        th = threading.Thread(target=self._decode_slot, args=(run, pcm, after), daemon=True)
        th.start()
        return th

    # ------------------------------------------------------------ decoding
    def _decode_slot(self, run: _SlotRun, pcm: np.ndarray, after: threading.Thread | None = None) -> None:
        if after is not None:
            after.join()
        slot_t0 = run.slot_t0
        mycall = ""
        try:
            if self._closed:
                return
            _sweep_stale()
            ints = _pcm16(pcm)
            mycall, dxcall = _calls_now(self.calls)
            order = self._order()
            used = failed = None
            events: list[dict] = []
            took = 0.0
            for i, name in enumerate(order):
                t = time.perf_counter()
                try:
                    events = self._decode_with(name, pcm, ints, slot_t0, mycall, dxcall)
                except Exception as exc:  # noqa: BLE001
                    # A decoder failing is not a reason to go without
                    # decodes: the other decodes this slot, and the log has
                    # the first such failure in full. ohsdigi raising is a
                    # bug in ohsdigi; jt9 failing is an installed WSJT-X
                    # that does not run (a crash, a missing library), which
                    # until 17/10/2026 went unnoticed (run_decoder_tool).
                    # The last decoder failing is reported as before.
                    if i + 1 == len(order):
                        raise
                    _say_once(f"{name}-raised", "%s failed to decode an %s slot; %s decodes instead: %s",
                              name, self.variant, order[i + 1], exc, exc_info=True)
                    failed = name
                    continue
                took = time.perf_counter() - t
                used = name
                break
            if used is None:
                return
            self._report(f"{used} ({failed} failed)" if failed else used)
            for ev in events:
                with run.lock:
                    if ev["text"] in run.seen:
                        continue
                    run.seen.add(ev["text"])
                    run.events.append(ev)
                log.debug("%s %s %+d %.1f %d %s", self.variant.upper(), _hms(slot_t0), ev.get("snr", 0),
                          ev.get("dt", 0.0), ev.get("df", 0), ev["text"])
                self.emit(ev)
            # The other decoder, on exactly these samples and calls, for
            # comparison only (decoder_shadow): started after this pass's
            # decodes have gone out, so it never delays them, and on its
            # own thread, so the slot's final pass - which waits for this
            # one - does not wait for it too (on a Pi, jt9 alone can take
            # most of the 1.5 s between the early pass and the slot's end).
            # Counted in _busy from here, before this pass's _leave(), so
            # "no decode for this slot is still running" stays true of the
            # shadow as well; ohsnb.analyse waits on it to know every slot's
            # comparison has landed.
            shadow = next((n for n in order if n not in (used, failed)), None)
            if shadow is not None and decoder_shadow.enabled():
                with self._dir_lock:
                    self._busy += 1
                threading.Thread(target=self._shadow, daemon=True,
                                 args=(shadow, used, events, took, pcm, ints, slot_t0, mycall, dxcall)).start()
        except Exception as exc:  # a stuck/crashed decoder must not take the daemon down with it
            self.emit({"mode": self.variant, "slot": slot_t0, "error": str(exc)})
        finally:
            with run.lock:
                run.done += 1
                final = run.closed and run.done >= run.started
            if final and not self._closed:
                try:
                    self._summarise(run, mycall, pcm)
                except Exception:  # noqa: BLE001 - a log line must never cost a decode
                    log.debug("slot summary failed", exc_info=True)
            self._leave()

    # One line per slot that decoded anything, so a remote operator's log
    # alone says whether NB was hearing the band and whether anyone
    # answered: how many, best and median SNR, how many CQs, and every
    # message addressed to the operator in full. A slot with nothing is
    # DEBUG; INFO only once nothing has decoded for EMPTY_SLOTS slots in a
    # row, and then at most every EMPTY_EVERY_S, with the slot's audio
    # level - silence (no audio reaching the decoder) and a band of noise
    # are different faults. Every decode itself is DEBUG (-v).
    EMPTY_SLOTS = 4
    EMPTY_EVERY_S = 60.0

    def _summarise(self, run: _SlotRun, mycall: str, pcm: np.ndarray) -> None:
        name = self.variant.upper()
        with run.lock:
            evs = list(run.events)
        if not evs:
            self._empty_slots += 1
            now = time.monotonic()
            rms = float(np.sqrt(np.mean(np.square(pcm, dtype=np.float64)))) if len(pcm) else 0.0
            peak = float(np.max(np.abs(pcm))) if len(pcm) else 0.0
            audio = f"slot audio {20 * math.log10(rms + 1e-12):.1f} dBFS rms, peak {20 * math.log10(peak + 1e-12):.1f} dBFS"
            if self._empty_slots >= self.EMPTY_SLOTS and now - self._empty_said >= self.EMPTY_EVERY_S:
                self._empty_said = now
                log.info("%s: nothing decoded in the last %d slots, the decoder running (%s)", name,
                         self._empty_slots, audio)
            else:
                log.debug("%s slot %s: nothing decoded (%s)", name, _hms(run.slot_t0), audio)
            return
        self._empty_slots = 0
        snrs = sorted(int(e.get("snr", 0)) for e in evs)
        cqs = sum(1 for e in evs if e["text"].split()[:1] == ["CQ"])
        me = mycall.strip().upper()
        to_me = [e["text"] for e in evs if me and e["text"].split()[:1] in ([me], [f"<{me}>"])]
        log.info("%s slot %s: %d decoded, SNR best %+d median %+d dB, %d CQ, to %s: %s", name, _hms(run.slot_t0),
                 len(evs), snrs[-1], snrs[len(snrs) // 2], cqs, me or "me",
                 "; ".join(to_me) if to_me else "none")

    def _shadow(self, name: str, primary: str, primary_events: list[dict], primary_s: float,
                pcm: np.ndarray, ints: np.ndarray, slot_t0: float, mycall: str, dxcall: str) -> None:
        try:
            t = time.perf_counter()
            try:
                theirs = self._decode_with(name, pcm, ints, slot_t0, mycall, dxcall)
            except Exception as exc:  # noqa: BLE001 - the shadow must never touch decoding
                decoder_shadow.failed(self.variant, name, exc)
                return
            decoder_shadow.record(self.variant, slot_t0, primary, primary_events, primary_s,
                                  name, theirs, time.perf_counter() - t)
        finally:
            self._leave()

    def _decode_with(self, name: str, pcm: np.ndarray, ints: np.ndarray, slot_t0: float,
                     mycall: str, dxcall: str) -> list[dict]:
        if name == "ohsdigi":
            return _ohsdigi_decode(self.ohsdigi, self.variant, ints, slot_t0, mycall, dxcall)
        return self._jt9(pcm, ints, slot_t0, mycall, dxcall)

    def _jt9(self, pcm: np.ndarray, ints: np.ndarray, slot_t0: float, mycall: str, dxcall: str) -> list[dict]:
        with self._jt9_lock:
            workdir = self._enter()
            if workdir is None:
                return []                   # closed meanwhile: nobody wants the decodes
            wav_path = Path(workdir) / f"{self.variant}_{slot_t0:.3f}_{threading.get_ident()}.wav"
            _write_wav16(wav_path, pcm, ints)
            flag = "-8" if self.variant == "ft8" else "-5"
            result = run_decoder_tool("jt9", [_JT9, flag, "-p", str(int(self.slot_s)) if self.variant == "ft4" else "15",
                                              "-c", _jt9_call(mycall), "-x", _jt9_call(dxcall), str(wav_path)],
                                      workdir)
            return _parse_jt9_output(result.stdout, self.variant, slot_t0)


# ohsdigi as NB runs jt9: no -d, so depth 1 (jt9.f90's default). Raising it
# is a separate decision (decode time on a Pi: docs/digimodes-rust.md,
# "Speed"); this keeps the two decoders doing the same work.
DEPTH = 1

# WSJT-X's low-confidence threshold: an a-priori decode whose quality is
# below it gets a "?" (lib/decoder.f90, ft8_decoded and ft4_decoded:
# `if(qual.lt.0.17) decoded0(37:37)='?'`, inside `if(nap.ne.0)`).
LOW_QUAL = 0.17


def _jt9_round1(x: float) -> float:
    """x as jt9 prints it with f5.1: to the nearest tenth, a half away
    from zero. ohsdigi's numbers are single precision, so x*10 is exact in a
    double and the rounding is of the value jt9 itself formats."""
    return math.copysign(math.floor(abs(x) * 10.0 + 0.5) / 10.0, x)


def _jt9_nint(x: float) -> int:
    """Fortran's nint, which jt9 prints the frequency with."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def _stdcall(call: str) -> bool:
    """WSJT-X's stdcall (lib/qra/q65/q65_set_list.f90): a call FT8 can
    send in full in a standard message - one or two characters (at least
    one a letter) before the call-area digit, at most three letters after.
    "G4XYZ/P" and "PJ4/K1ABC" are not."""
    n = len(call)
    i = n
    while i >= 2 and not call[i - 1].isdigit():
        i -= 1
    iarea = i
    npdig = sum(c.isdigit() for c in call[:iarea - 1])
    nplet = sum("A" <= c <= "Z" for c in call[:iarea - 1])
    nslet = sum("A" <= c <= "Z" for c in call[iarea:])
    return not (iarea < 2 or iarea > 3 or nplet == 0 or npdig >= iarea - 1 or nslet > 3)


def _jt9_hashes(lb, variant: str, mycall: str, dxcall: str):
    """The hashed-call table as jt9, started once per WAV with -c/-x, has
    it by the time it unpacks the slot's decodes - or None where `lb` has
    no CallHashes (a stand-in in a test).

    Without it ohsdigi showed "<...>" where jt9 shows the operator's or the
    DX station's call: a message to "<G4XYZ>" from a nonstandard call, the
    very message that should light up as "to you". jt9 knows those calls
    because its a-priori set-up packs and unpacks a message made of them
    before the decode, which saves their hashes, and FT8 and FT4 do it
    differently: FT8's ft8apset runs before MyCall is set in packjt77 (so
    MyCall's own hash is saved), packs "MYCALL DXCALL RRR" - with MyCall
    in <> when it is not a standard call, and a dummy KA1ABC for a missing
    DX call - and saves the DX call's hash itself; FT4's ft4_decode sets
    MyCall and DxCall first, then packs "MYCALL DXCALL RR73", with MyCall
    standing in for a missing DX call. Reproduced here step for step,
    because the measure is jt9: on messages to and from standard,
    portable and prefixed calls, with each combination of MyCall and DX
    call, ohsdigi then names exactly the calls jt9 names
    (tests/test_modes_ft8.py, HashedCalls)."""
    if getattr(lb, "CallHashes", None) is None:
        return None
    h = lb.CallHashes()

    def pack_unpack(msg: str) -> None:
        try:
            bits, _i3, _n3 = lb.pack77(msg, h)
            lb.unpack77(bits, True, h)
        except ValueError:
            pass                    # WSJT-X cannot pack it either; its AP set-up gives up the same way

    if variant == "ft8":
        if len(mycall) >= 3:
            if len(dxcall) >= 3:
                h.save(dxcall)
            his = dxcall if len(dxcall) >= 3 else "KA1ABC"
            pack_unpack(f"{mycall} {his} RRR" if _stdcall(mycall) else f"<{mycall}> {his} RRR")
        if mycall:
            h.set_mycall(mycall)
        if dxcall:
            h.set_dxcall(dxcall)
    else:
        if mycall:
            h.set_mycall(mycall)
        if dxcall:
            h.set_dxcall(dxcall)
        if len(mycall) >= 3:
            pack_unpack(f"{mycall} {dxcall if len(dxcall) >= 3 else mycall} RR73")
    return h


def _ohsdigi_decode(lb, variant: str, ints: np.ndarray, slot_t0: float, mycall: str, dxcall: str) -> list[dict]:
    """One slot through ohsdigi, as the events jt9's output becomes."""
    fn = lb.ft8_decode if variant == "ft8" else lb.ft4_decode
    kw = {"depth": DEPTH, "mycall": mycall, "dxcall": dxcall}
    h = _jt9_hashes(lb, variant, mycall, dxcall)
    if h is not None:
        kw["hashes"] = h
    return [_ohsdigi_event(d, variant, slot_t0) for d in fn(ints.tobytes(), **kw)]


def _ohsdigi_event(d: dict, variant: str, slot_t0: float) -> dict:
    """ohsdigi's decode as the event _parse_jt9_output makes of the line jt9
    prints for it: SNR as is, DT to a tenth and frequency to a hertz as
    jt9 rounds them, the AP type as "a1".."a6", and "?" - only ever on an
    a-priori decode, as in WSJT-X - as lowConfidence."""
    text = str(d["text"]).strip()
    ev = {
        "mode": variant,
        "slot": slot_t0,
        "snr": int(d["snr"]),
        "dt": _jt9_round1(float(d["dt"])),
        "df": _jt9_nint(float(d["freq"])),
        "text": text,
    }
    ap = int(d.get("ap") or 0)
    if ap:
        ev["ap"] = f"a{ap}"
        if float(d.get("qual", 1.0)) < LOW_QUAL:
            ev["lowConfidence"] = True
    ev.update(_parse_standard(text))
    return ev


def _hms(t: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(t))


_said: set[str] = set()


def _say_once(key: str, msg: str, *args, exc_info=False, level: int | None = None) -> None:
    """Log `msg` the first time `key` comes up in this process: a fallback
    taken every slot would otherwise write the same line four times a
    minute for the rest of the run. A warning with the traceback when
    there is one, else INFO unless `level` says otherwise."""
    if key in _said:
        return
    _said.add(key)
    if exc_info:
        log.warning(msg, *args, exc_info=True)
    else:
        log.log(level or logging.INFO, msg, *args)


def _pcm16(pcm: np.ndarray) -> np.ndarray:
    """The slot as the 16-bit samples jt9 reads (and ohsdigi is given)."""
    return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2")


def _write_wav16(path: Path, pcm: np.ndarray, ints: np.ndarray | None = None) -> None:
    if ints is None:
        ints = _pcm16(pcm)
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


_JT9_LINE_RE = re.compile(
    # The single character before the text is jt9's mode marker ("~" for
    # FT8, "+" for FT4, others for its other modes); it carries no
    # information this module needs, just which decoder produced the line.
    r"^\d{6}\s+(?P<snr>-?\d+)\s+(?P<dt>-?\d+\.\d)\s+(?P<df>\d+)\s+[~#&@+$]?\s+(?P<text>.+?)\s*$"
)


# jt9 appends a quality marker after the text, padded out to a column:
# "a1".."a7" for a decode made with a priori help (expected calls or
# message content), "?" for a low-confidence one, and - on a low-confidence
# a-priori decode - both, in that order ("...text...   ? a1"). Left in, it
# became part of the message, so the decode lost its call and country and
# could not be clicked to answer. "a1" is lowercase and FT8 text is
# uppercase, so it cannot be a word of the message; "?" can be, so it is
# only taken as the marker when padding separates it from the text.
#
# Stripped in two passes, AP then "?", rather than one combined regex: a
# single pattern with both markers optional matches an empty string at
# position 0 of anything (nothing is mandatory left for `search()` to
# anchor on), so it would "strip" the very start of a plain decode instead
# of finding nothing at the end. Two mandatory, sequential patterns have no
# such hole, and each is exactly the single-marker case already proven
# (06/10/2026) - 07/10/2026, after a real on-air decode's AP-and-low-confidence
# combination ("CQ RN3DDW KO85 ... ? a1") came back with the "?" and its
# padding still in the text: only the trailing "a1" was ever being removed.
_JT9_AP_RE = re.compile(r"\s+(?P<ap>a[1-7])\s*$")
_JT9_LOW_RE = re.compile(r"\s{2,}(?P<low>\?)\s*$")


def _parse_jt9_output(stdout: str, variant: str, slot_t0: float) -> list[dict]:
    """jt9's stdout is one line per decode: hhmmss, SNR, dt, frequency (Hz),
    mode marker, then the decoded text. Lines that don't match (a summary
    line, a warning) are silently skipped -- jt9's logging format isn't a
    contract either of us owns, so being lenient about unrecognised lines
    costs nothing and being strict would break on the next WSJT-X update."""
    events = []
    for line in stdout.splitlines():
        m = _JT9_LINE_RE.match(line.strip())
        if not m:
            continue
        text = m.group("text").strip()
        marker = {}
        m_ap = _JT9_AP_RE.search(text)
        if m_ap:
            marker["ap"] = m_ap.group("ap")
            text = text[:m_ap.start()].rstrip()
        m_low = _JT9_LOW_RE.search(text)
        if m_low:
            marker["lowConfidence"] = True
            text = text[:m_low.start()].rstrip()
        ev = {
            "mode": variant,
            "slot": slot_t0,
            "snr": int(m.group("snr")),
            "dt": float(m.group("dt")),
            "df": int(m.group("df")),
            "text": text,
        }
        ev.update(marker)
        ev.update(_parse_standard(text))
        events.append(ev)
    return events
