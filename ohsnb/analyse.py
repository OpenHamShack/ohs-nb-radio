"""python3 -m ohsnb --analyse <file.sigmf-meta|.sigmf-data> [--out DIR] [--minutes N] [--jobs N]

A report on a SigMF receive recording (ohscore/sigmf.py), for a tester who
heard something nobody else can but cannot run the program under a
debugger: this reads the samples once, offline, and writes a few pages
instead of handing back the 300 MB they sent. Three files land in `--out`
(default: a folder named after the recording, beside it):

- `report.txt` - plain language, under ~2 KB, headline numbers first;
- `report.json` - the same numbers, structured, for another tool;
- `wide.png`, `beacon.png`, `ft8.png` - matplotlib, skipped (with a
  sentence in both reports) if matplotlib is not installed.

Nothing here re-implements the signal processing: the noise floor and the
transponder's rise over it come from the same windowed spectrum
(ohscore.dsp.spectrum.Scope) the live scope draws; the middle/lower/upper
beacons and the LNB's drift from ohsnb.dsp.lock.BeaconTracker, fed the file
instead of a device; FT8 from ohscore.modes.ft8.Decoder, which already runs
ohsdigi and - the comparison this report leans on - jt9 as its shadow, the
same pairing ohscore.modes.decoder_shadow logs and counts live, just
captured here as data; SSB offsets from
ohscore.dsp.autotune.auto_tune, the same function "Auto-tune" calls live.
Everything is read with numpy memmap and processed in blocks, as fast as
the CPU allows rather than paced to the sample rate - a 13-minute file
takes well under a minute.

Two recording shapes are understood, the same two ohscore.devices.filedev
(IQ playback) plays back by the same rule, so the two never disagree
about where a frequency sits. The one ohscore.sigmf.Recorder writes
(`openhamshack:receive`/`openhamshack:gain`/`openhamshack:beacon_lock`; each capture's
own `core:frequency` already *is* the nominal downlink at DC) and a
simpler one a developer's own capture script wrote directly on
07/10/2026 (flat `openhamshack:centre_downlink_nominal_hz` and
`openhamshack:lnb_error_hz`, no `core:extensions` declaration - ohscore.sigmf
.validate() rightly complains about it, but there is enough here to
analyse, and a recording a tester actually sent is the one this command
has to cope with): there, `core:frequency` is the SDR's own raw tuned
frequency (the LNB's output), not the downlink, so the nominal downlink
at DC has to be reassembled by adding `openhamshack:lnb_lo_hz` back
(`_capture_dc`). Getting this backwards - reading the flat field, which
is RX_CENTRE_DL, the *corrected* downlink, as if it were the nominal one
- cost ~25 kHz on Brian's real recordings (07/10/2026): seeding the
beacon tracker's rxCorr on top of an already-corrected dc searched 25 kHz
from where the beacon, and FT8, and the bandplan's edges, actually were.
`_adapt_meta` reads either shape into one this module works from.

A recording that is not QO-100 (wrong centre frequency, no QO-100 NB in
its metadata) gets the metadata summary, the noise floor and the
clipping/gap check; the beacon, FT8 and SSB sections say plainly why they
were skipped rather than reporting nonsense about bands that are not
there.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ohscore import sigmf
from ohscore.dsp import autotune
from ohscore.dsp.bank import Analysis, Channel, Geometry
from ohscore.dsp.demod import Demod, passband
from ohscore.engine import AUDIO_RATE
from ohscore.modes import decoder_shadow
from ohscore.modes import ft8 as ft8mod

from ohsnb.i18n import _, ngettext

from . import bandplan
from .dsp.lock import BeaconTracker, _Beacon
from .radio import WIDE_MARGIN

try:
    import matplotlib
    matplotlib.use("Agg")           # headless: this runs with no display
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

# The documented QO-100 NB calling frequency for FT8 (docs/qo100-research.md,
# "FT8 10489.540 dial"; also ohsnb.bandplan.PRESETS). Its 0-3 kHz audio runs
# into the 10489.540-.580 digimode segment either side of that.
FT8_DIAL_DL = 10_489_540_000.0
LOCK_SNR = BeaconTracker.LOCK_SNR    # dB: below this a beacon measurement does not count as "heard"
CHUNK_S = 1.0                        # raw IQ read per streaming step
# A slot's own Decoder (ohscore.modes.ft8/q65/js8) spawns a worker thread
# and a jt9/q65code/js8 subprocess per slot, with no limit of its own on
# how many may be outstanding at once - fine live, where real time paces
# slots tens of seconds apart, but this module reads a file as fast as
# the CPU allows: without a limit, a machine fast enough to channelise a
# recording quicker than jt9 can keep up (confirmed on this host, not the
# laptop that OOM-killed on the slower path) queues every slot's decode
# at once, each its own subprocess resident at the same time - hundreds
# of them for a multi-hour file, gigabytes rather than the handful of MB
# one jt9 call needs. _wait_for_room pauses feeding, not decoding, so
# slots already in flight still finish at their own pace.
MAX_CONCURRENT_DECODES = 4
REPORT_BUDGET = 2200                 # report.txt's rough byte ceiling (the brief: "under ~2 KB")


# --------------------------------------------------------------- metadata
def _adapt_meta(meta: dict) -> dict:
    """The fields this module needs, from whichever of the two recording
    shapes the module docstring describes `meta["global"]` is. Never
    raises: a field that is absent just comes back None/empty, and the
    report says what could not be found rather than failing the whole run."""
    g = meta.get("global", {})
    caps = meta.get("captures") or []
    recv = g.get("openhamshack:receive") if isinstance(g.get("openhamshack:receive"), dict) else {}
    gain = g.get("openhamshack:gain") if isinstance(g.get("openhamshack:gain"), dict) else {}
    bl = g.get("openhamshack:beacon_lock") if isinstance(g.get("openhamshack:beacon_lock"), dict) else {}
    gain_mode = gain.get("mode") or g.get("openhamshack:gain_mode")
    gain_db = gain.get("db")
    gain_log = g.get("openhamshack:gain_log_db")
    if gain_db is None and isinstance(gain_log, list) and gain_log:
        gain_db = gain_log[-1][1]
    rx_corr0 = bl.get("rxCorr")
    if rx_corr0 is None:
        rx_corr0 = g.get("openhamshack:lnb_error_hz")
    nominal_dc = g.get("openhamshack:centre_downlink_nominal_hz")
    lnb_lo = g.get("openhamshack:lnb_lo_hz")
    return {
        "app": g.get("openhamshack:app") or g.get("core:recorder") or "",
        "version": g.get("openhamshack:version") or "",
        "os": g.get("openhamshack:os") or "",
        "hw": g.get("core:hw") or "",
        "description": g.get("core:description") or "",
        "author": g.get("core:author") or g.get("openhamshack:callsign") or "",
        "fs": float(g.get("core:sample_rate") or 0.0),
        "datatype": g.get("core:datatype") or "",
        # Overrides the datatype's own default full scale (sigmf.DTYPES):
        # ohscore.devices.filedev.FileDevice reads this the same way for
        # playback, so the two can never disagree about it either. Without
        # it, a recording whose device is not full-scale at the container
        # width - the Pluto ad hoc captures of 07/10/2026, ci16 but +-2048,
        # not +-32768 - reads 24 dB (32768/2048) too quiet: the clipping
        # check never trips, the noise floor reads low, and every dBFS
        # figure in the report is wrong by exactly that much.
        "scale": g.get("openhamshack:scale"),
        "mode": recv.get("mode") or "",
        "dial": recv.get("rxDial"),
        "gain_mode": gain_mode,
        "gain_db": gain_db,
        "rx_corr0": float(rx_corr0) if rx_corr0 is not None else None,
        "nominal_dc_flat": float(nominal_dc) if nominal_dc is not None else None,
        "lnb_lo_hz": float(lnb_lo) if lnb_lo is not None else None,
        "clipped": g.get("openhamshack:clipped"),
        "dropped_samples": g.get("openhamshack:dropped_samples"),
        "captures": caps,
    }


def _capture_dc(cap: dict, info: dict) -> float | None:
    """The absolute downlink frequency a capture's sample 0 (DC of the IQ
    from there) represents, nominally - before the recording's own rxCorr
    (ohsnb.radio._rec_centre's docstring) - exactly the rule
    ohscore.devices.filedev.FileDevice._segments uses to play these same
    two recording shapes back through the real receiver, so this module
    and playback can never disagree about where a frequency sits.

    ohscore.sigmf.Recorder (ohsnb.radio._rec_centre) puts the nominal
    downlink straight in `core:frequency`, retune by retune. The
    developer's capture script of 07/10/2026 instead writes the SDR's own
    tuned frequency there (739-odd MHz, after the LNB's analogue
    downconversion) - its `openhamshack:lnb_lo_hz` is what turns that into the
    same on-air quantity. Getting this backwards (treating the flat
    `openhamshack:centre_downlink_nominal_hz` field as if it were already the
    nominal-at-DC figure) was tried first and cost ~25 kHz: that field is
    the *corrected* downlink - RX_CENTRE_DL itself - not the nominal one,
    so seeding the tracker's rxCorr on top of it searched 25 kHz from
    where the beacon actually was. `nominal_dc_flat` is kept only as a
    last resort, for a capture with neither `core:frequency` nor an LNB
    LO to add to it."""
    f = cap.get("core:frequency")
    lnb_lo = info.get("lnb_lo_hz")
    if f is not None:
        return float(f) + (lnb_lo if lnb_lo is not None else 0.0)
    return info.get("nominal_dc_flat")


def _dc_for_t(caps: list, info: dict, fs: float, t: float) -> float | None:
    """`_capture_dc` for whichever capture is in force at stream time t
    (the one with the largest core:sample_start at or before it) - the
    same rule _run_beacon_tracker and _ft8_stream_decode step through
    segment by segment, looked up directly here for the extended report
    sections (ohsnb.analyse_power, _ssb, _digital), each of which needs the
    capture at an arbitrary point rather than marching through every one
    in order."""
    samp = t * fs
    cap = max((c for c in caps if int(c.get("core:sample_start", 0)) <= samp),
             key=lambda c: int(c.get("core:sample_start", 0)), default=(caps[0] if caps else {}))
    return _capture_dc(cap, info)


# The names NB has written into a recording's metadata: "OpenHamShack NB" until
# the OpenHamShack rename (09/10/2026), and its recordings stay on disk -
# so both, for as long as an old recording can turn up.
NB_NAMES = ("openhamshack qo-100 nb", "openhamshack nb")


def _looks_like_qo100(info: dict, dc_hz: float | None) -> tuple[bool, str]:
    said = f'{info["app"]}\n{info["description"]}'.lower()
    if any(n in said for n in NB_NAMES):
        return True, ""
    if dc_hz is not None and (bandplan.DL_LO - 5e6) <= dc_hz <= (bandplan.DL_HI + 5e6):
        return True, ""
    where = f"{dc_hz / 1e6:.4f} MHz" if dc_hz is not None else "unknown"
    return False, (f"this does not look like a QO-100 NB recording (no OpenHamShack QO-100 NB in its metadata, and the "
                   f"centre frequency, {where}, is nowhere near the {bandplan.DL_LO / 1e6:.3f}-"
                   f"{bandplan.DL_HI / 1e6:.3f} MHz downlink)")


# ------------------------------------------------------------------ raw IQ
def _raw_iq(data_path: Path, datatype: str, scale_override: float | None = None):
    """(samples_view, scale, n_complex) - a memmap of the file's complex
    samples as (N, 2) native-width components, and the multiplier to the
    engine's full-scale-1.0 convention. The datatype's own default
    (ohscore.sigmf.DTYPES) is what a container width implies - ci16 is
    usually +-32768 - but `scale_override` (info["scale"], the meta's
    `openhamshack:scale`) takes over whenever a recorder's device is not
    full-scale at that width, exactly as ohscore.devices.filedev.FileDevice
    reads the same field for playback: the two must never disagree about
    what one raw sample is worth. Raises ValueError for a datatype this
    module has no reader for."""
    if datatype not in sigmf.DTYPES:
        raise ValueError(_("unsupported SigMF datatype {datatype}").format(datatype=repr(datatype)))
    dtype_str, scale = sigmf.DTYPES[datatype]
    if scale_override:
        scale = 1.0 / float(scale_override)
    raw = np.memmap(data_path, dtype=dtype_str, mode="r")
    n = (len(raw) // 2) * 2
    return raw[:n].reshape(-1, 2), scale, n // 2


def _chunk(view, scale: float, a: int, b: int) -> np.ndarray:
    i = view[a:b, 0].astype(np.float32)
    q = view[a:b, 1].astype(np.float32)
    return (i + 1j * q) * np.float32(scale)


def _wait_for_room(decoder, limit: int | None = None) -> None:
    """Block the feeding loop (never the decode threads themselves) while
    `limit` or more of a slotted Decoder's (ohscore.modes.ft8/q65/js8) own
    decode runs are already in flight - see MAX_CONCURRENT_DECODES. Read
    at call time rather than bound as a default argument, so a worker of
    a parallel run (ohsnb.analyse_parallel) can lower it for its whole
    process: several decoding workers at once, each allowed four jt9
    subprocesses, would otherwise put four times the worker count of
    them on the machine."""
    limit = MAX_CONCURRENT_DECODES if limit is None else limit
    while decoder._busy >= limit:
        time.sleep(0.05)


# ------------------------------------------------------- streaming, sliced
# The streaming sections all walk the recording the same way: capture
# segment by capture segment, CHUNK_S blocks within each, skipping a
# segment whose nominal frequency cannot be worked out. _chunk_grid is
# that walk written down once, so a parallel run (ohsnb.analyse_parallel)
# can hand a worker "blocks k0..k1" and know they are exactly the blocks
# the single-process loop would have visited, with the same frequency.
#
# A worker starting at block k0 must also start with the *state* a
# single pass would have had there, or its output is merely similar:
# - the filter bank (Analysis) holds the samples since its last frame -
#   _analysis_at rebuilds that buffer from the file, exactly;
# - a Channel's LO phase depends on every earlier block's frequency -
#   _audio_blocks replays it with Channel.advance, one line per block;
# - a Scope holds the last `need` samples and the time of its next line -
#   _scope_at rebuilds both;
# - the demodulator's filter and AGC have no exact shortcut, so a slice
#   runs WARM_CHUNKS blocks through them first and discards that audio.
#   The filter holds only its last taps-1 inputs; the AGC is a peak
#   follower that forgets at 20 dB/s, so once a fresh peak exceeds what
#   it remembers from before the warm-up both runs hold the same numbers
#   and stay identical (tests/test_analyse_parallel.py compares the audio
#   sample for sample). 30 s forgets 600 dB - more than any recording
#   has.
# All of this needs every block from 0 to have been pushed: a recording
# with a segment skipped (no frequency) reports contiguous=False and a
# parallel run leaves those sections whole rather than slice them.
WARM_CHUNKS = 30


def _chunk_grid(caps: list, info: dict, n: int, fs: float) -> tuple[list[tuple[int, int, float]], bool]:
    """([(a, b, dc)], contiguous): every CHUNK_S block the per-capture
    streaming loops visit, in order, with its capture's nominal DC
    (_capture_dc); `contiguous` is False if any segment was skipped."""
    step = int(CHUNK_S * fs)
    cap_bounds = sorted({int(c.get("core:sample_start", 0)) for c in caps} | {0, n})
    grid: list[tuple[int, int, float]] = []
    contiguous = True
    for seg_lo, seg_hi in zip(cap_bounds, cap_bounds[1:]):
        cap = next((c for c in caps if int(c.get("core:sample_start", 0)) == seg_lo), {})
        dc = _capture_dc(cap, info)
        if dc is None:
            contiguous = contiguous and seg_hi <= seg_lo
            continue
        for a in range(seg_lo, seg_hi, step):
            grid.append((a, min(a + step, seg_hi), dc))
    return grid, contiguous


class _CorrAt:
    """_rx_corr_at for one beacon_hist, with the locked entries picked out
    once instead of on every call - the same answer for every t. A slice
    replaying the LO phase from the start of a three-hour file asks this
    once per block, ~11,000 times; _rx_corr_at's own list comprehension
    over ~22,000 entries each time would cost minutes for nothing."""

    def __init__(self, beacon_hist: list[dict], default: float):
        locked = [e for e in beacon_hist if e.get("state") == "locked" and e.get("rxCorr") is not None]
        self.times = [e["t"] for e in locked]
        self.corrs = [e["rxCorr"] for e in locked]
        self.default = default

    def __call__(self, t: float) -> float:
        if not self.times:
            return self.default
        i = bisect.bisect_left(self.times, t)
        if i <= 0:
            return self.corrs[0]
        if i >= len(self.times):
            return self.corrs[-1]
        return self.corrs[i - 1] if (t - self.times[i - 1]) <= (self.times[i] - t) else self.corrs[i]


def _analysis_at(geo: Geometry, view, scale: float, a: int) -> Analysis:
    """An Analysis in exactly the state one that had been pushed samples
    0..a in any blocks would be in: frames at -V + kL, the buffer holding
    from the last completed frame's successor onward (zeros before 0, as
    a fresh Analysis starts)."""
    an = Analysis(geo)
    if a <= 0:
        return an
    base = (a // geo.L) * geo.L - geo.V
    buf = _chunk(view, scale, max(0, base), a)
    if base < 0:
        buf = np.concatenate([np.zeros(-base, np.complex64), buf])
    an.buf = np.asarray(buf, np.complex64)
    an.base = base
    return an


def _scope_at(scope, view, scale: float, a: int) -> None:
    """Put `scope` (ohscore.dsp.spectrum.Scope, fresh) into the state it
    would be in after process() had been fed samples 0..a: the last
    `need` samples buffered and the next line's end the same float that
    repeated `+= period` reaches - the same additions, not a
    multiplication, so a non-integer period lands on the same value."""
    if a <= 0:
        return
    need = scope.need
    buf = _chunk(view, scale, max(0, a - need), a)
    if a < need:
        buf = np.concatenate([np.zeros(need - a, np.complex64), buf])
    scope.buf = np.asarray(buf, np.complex64)
    scope.n = a
    period = scope.rate / scope.fps
    nl = float(need)
    while nl <= a:
        nl += period
    scope.next_line = nl


def _audio_blocks(view, scale: float, fs: float, grid: list, freq_for, k_lo: int = 0,
                  k_hi: int | None = None, k_warm: int | None = None):
    """12 kHz digital-mode audio (the FT8 passband, AGC "medium" - see
    _ft8_stream_decode for why both) for grid blocks k_lo..k_hi-1, yielded
    as (k, audio) for each block that produced any, exactly as a single
    pass from block 0 would produce them. `freq_for(a, b, dc)` is the
    channel's offset from DC for that block. Blocks k_warm..k_lo-1 are
    processed and their audio discarded (the demodulator's warm-up, see
    WARM_CHUNKS); k_warm defaults to k_lo, which is only exact when k_lo
    is 0 - the single-process path."""
    geo = Geometry(fs)
    d = geo.decimation_for(AUDIO_RATE)
    ch = Channel(geo, d)
    demod = Demod(ch.rate if abs(ch.rate - AUDIO_RATE) < 1e-6 else AUDIO_RATE)
    lo, hi = passband("ft8", 0.0, 0.0, 0.0, 0.0, 0.0)
    demod.configure("ft8", lo, hi, agc="medium", rf_gain_db=0.0)
    k_hi = len(grid) if k_hi is None else k_hi
    k_warm = k_lo if k_warm is None else min(k_warm, k_lo)
    for k in range(k_warm):
        a, b, dc = grid[k]
        m = b // geo.L - a // geo.L       # frames this block completes in a pass from 0
        if m:
            ch.set_freq(freq_for(a, b, dc))
            ch.advance(m)
    analysis = _analysis_at(geo, view, scale, grid[k_warm][0]) if k_warm < len(grid) else Analysis(geo)
    for k in range(k_warm, k_hi):
        a, b, dc = grid[k]
        ch.set_freq(freq_for(a, b, dc))
        X, starts = analysis.push(_chunk(view, scale, a, b))
        if X.shape[0] == 0:
            continue
        iq = ch.take(X, starts)
        audio, _level = demod(iq)
        if k >= k_lo and len(audio):
            yield k, audio


def _audio_fed_before(fs: float, a: int) -> int:
    """How many 12 kHz audio samples a single pass from sample 0 has
    produced before block-start `a`: L/D per completed frame."""
    geo = Geometry(fs)
    d = geo.decimation_for(AUDIO_RATE)
    return (a // geo.L) * (geo.L // d)


# --------------------------------------------------------------- clipping
def _level_stats(view, scale: float, n: int, full_scale: int) -> dict:
    """Clipping, peak and RMS over the whole file, from the raw integers
    (clipping is exact there; a float rescale could round a full-scale
    sample just under the line). `full_scale` is the datatype's own limit
    (32767 for ci16); the recorder already counts clipping at write time
    for its own format, so that figure is preferred when the metadata has
    it and this is just a cross-check for recordings that do not."""
    return _level_finish([_level_part(view, n, full_scale, 0, n)], n, full_scale)


LEVEL_STEP = 4_000_000    # raw samples per block: a parallel run's slices start on a multiple of it


def _level_part(view, n: int, full_scale: int, lo: int, hi: int) -> tuple[int, list[float], int]:
    """(clipped, [sum of squares per block], peak) for the LEVEL_STEP
    blocks from `lo` (a multiple of LEVEL_STEP) to `hi`. The per-block
    sums are kept separate, not added here, so _level_finish adds every
    block's in file order whichever process read it: float addition is
    not associative, and a sliced run that summed its own blocks first
    would read a different last digit."""
    near = int(round(full_scale * 0.97))
    clipped = 0
    sums: list[float] = []
    peak = 0
    for a in range(lo, hi, LEVEL_STEP):
        b = min(a + LEVEL_STEP, n, hi)
        i = view[a:b, 0].astype(np.int64)
        q = view[a:b, 1].astype(np.int64)
        mag = np.abs(i) | np.abs(q)       # cheap "either rail" check: a true magnitude needs sqrt for no benefit here
        clipped += int(np.count_nonzero((np.abs(i) >= near) | (np.abs(q) >= near)))
        peak = max(peak, int(mag.max()) if len(mag) else 0)
        sums.append(float(np.sum(i.astype(np.float64) ** 2 + q.astype(np.float64) ** 2)))
    return clipped, sums, peak


def _level_finish(parts: list, n: int, full_scale: int) -> dict:
    clipped = sum(p[0] for p in parts)
    peak = max((p[2] for p in parts), default=0)
    sumsq = 0.0
    for p in parts:
        for s in p[1]:
            sumsq += s
    rms = math.sqrt(sumsq / n) if n else 0.0
    peak_dbfs = 20 * math.log10(peak / full_scale + 1e-30)
    rms_dbfs = 10 * math.log10((rms * rms) / (full_scale * full_scale) + 1e-30)
    return {"clipped_samples": clipped, "clipped_pct": 100.0 * clipped / n if n else 0.0,
           "peak_dbfs": round(peak_dbfs, 1), "rms_dbfs": round(rms_dbfs, 1),
           "headroom_db": round(-peak_dbfs, 1)}


# -------------------------------------------------------------- gap check
def _gaps(captures: list, fs: float) -> list[dict]:
    out = []
    for c in captures:
        g = c.get("openhamshack:gap_samples")
        if g:
            out.append({"before_sample": c.get("core:sample_start"), "seconds": round(g / fs, 2)})
    return out


# A real transponder's own filter and the SDR's anti-alias/decimation
# filter both roll off gradually rather than stopping sharply, so there is
# no single frequency where "outside" begins: measured on Brian's
# 07/10/2026 recordings (once the frequency axis itself was corrected -
# see dc0/rx_corr_est above), the floor eases from -78 dB near the edge of
# what the SDR passes down to -72 dB inside the transponder with no flat
# step anywhere, and a reference taken right at the bandplan edge or right
# at the SDR's own rolloff both read the rise low for opposite reasons
# (too close to the transponder's own skirt; too close to the SDR's). A
# fixed guard either side, clear of both skirts on every file tried, is
# what OUTSIDE_GUARD below is for - chosen as far out as the profile stays
# flat (every file tried keeps a flat floor out past 250 kHz, and starts
# rolling off for the SDR's own filter only nearer 250-300 kHz).
#
# This still reads ~1.9-2.5 dB, not Brian's live dish-meter "~3 dB": a
# gradual transition has no one right answer, only the guard's own choice
# of how far out to look (wider sees more of the fall and reads higher -
# 50/150 kHz read 0.9-1.2 dB on these same files), and the remaining gap
# is most likely the live meter's own ballistics and the fact it reads
# one instant where this reads a percentile over the whole file, not a
# frequency error - that was the ~25 kHz dc0/rx_corr_est above fixes, and
# fixing it moved this number only slightly.
OUTSIDE_GUARD_NEAR, OUTSIDE_GUARD_FAR = 100_000.0, 250_000.0   # Hz beyond each bandplan edge


def _wide_spectrum(view, scale: float, n: int, fs: float, dc_hz: float, span: tuple[float, float]):
    """Averaged dB spectrum across the whole file (ohscore.dsp.spectrum.Scope,
    the live wide scope's own class), cropped to `span` for the plot, and
    (floor_db, rise_db): the noise floor in a guard band either side of the
    transponder (OUTSIDE_GUARD_NEAR..FAR beyond DL_LO/DL_HI, which Scope's
    spectrum already covers however narrow `span` is - a wideband FFT is
    never narrower than fs) against the floor inside its passband -
    "only 3-4 dB over the noise" is exactly this number."""
    return _wide_finish(_wide_lines(view, scale, n, fs, span[1] - span[0]), fs, span[1] - span[0], dc_hz, span)


def _wide_scope(fs: float, width: float):
    from ohscore.dsp.spectrum import Scope, wide_nfft
    nfft = wide_nfft(2048, fs, min(width, fs * 0.9))
    return Scope(fs, nfft, fps=0.2, avg=8)


def _wide_lines(view, scale: float, n: int, fs: float, width: float, lo: int = 0, hi: int | None = None) -> list:
    """The wide scope's lines whose end falls in (lo, hi] - every line
    from a pass over the whole file when lo=0, hi=n. Read in CHUNK_S
    blocks from sample 0 (not per capture: the median needs no frequency
    until _wide_finish), so `lo` must be a multiple of CHUNK_S * fs."""
    scope = _wide_scope(fs, width)
    hi = n if hi is None else hi
    _scope_at(scope, view, scale, lo)
    lines = []
    step = int(CHUNK_S * fs)
    for a in range(lo, hi, step):
        b = min(a + step, hi)
        for _end, db in scope.process(_chunk(view, scale, a, b)):
            lines.append(db)
    return lines


def _wide_finish(lines: list, fs: float, width: float, dc_hz: float, span: tuple[float, float]):
    lo, hi = span
    scope = _wide_scope(fs, width)
    nfft = scope.nfft
    if not lines:
        return None, None, None
    avg_db = np.median(np.stack(lines), axis=0)
    freqs = dc_hz + (np.arange(nfft) - nfft // 2) * scope.bin_hz
    guard_lo = (freqs >= bandplan.DL_LO - OUTSIDE_GUARD_FAR) & (freqs <= bandplan.DL_LO - OUTSIDE_GUARD_NEAR)
    guard_hi = (freqs >= bandplan.DL_HI + OUTSIDE_GUARD_NEAR) & (freqs <= bandplan.DL_HI + OUTSIDE_GUARD_FAR)
    outside = guard_lo | guard_hi
    inside = (freqs >= bandplan.DL_LO) & (freqs <= bandplan.DL_HI)
    floor_db = float(np.percentile(avg_db[outside], 20)) if outside.sum() >= 5 else None
    inside_floor_db = float(np.percentile(avg_db[inside], 20)) if inside.any() else None
    rise_db = (inside_floor_db - floor_db) if (floor_db is not None and inside_floor_db is not None) else None
    keep = (freqs >= lo) & (freqs <= hi)
    return (freqs[keep], avg_db[keep]), floor_db, rise_db


# ------------------------------------------------------------ beacon lock
def _run_beacon_tracker(view, scale: float, n: int, fs: float, caps: list, info: dict,
                        rx_corr0: float):
    """Feed the whole file through ohsnb.dsp.lock.BeaconTracker exactly as
    the engine's receive thread does (ohsnb.radio._rx_track), one capture
    segment at a time so a retune's new nominal centre is picked up. Adds
    the upper beacon to the tracker's own watch list (it only tracks lower
    and middle; `_Beacon`/`_search_one`/`_measure` do not care which name
    they are given) so all three are measured with no new DSP.

    Returns the tracker's reports, timestamped in stream seconds from the
    recording's start - absolute UTC is not needed here, only ohsnb/__main__
    --analyse's FT8 pass needs that."""
    geo = Geometry(fs)
    tracker = BeaconTracker(geo, choice="middle", rx_corr=rx_corr0,
                            narrow=BeaconTracker.NARROW_START if rx_corr0 else 0)
    tracker.beacons["upper"] = _Beacon("upper", geo)
    analysis = Analysis(geo)
    hist = []
    step = int(CHUNK_S * fs)
    cap_bounds = sorted({int(c.get("core:sample_start", 0)) for c in caps} | {0, n})
    for seg_lo, seg_hi in zip(cap_bounds, cap_bounds[1:]):
        cap = next((c for c in caps if int(c.get("core:sample_start", 0)) == seg_lo), {})
        dc = _capture_dc(cap, info)
        if dc is None:
            continue
        for a in range(seg_lo, seg_hi, step):
            b = min(a + step, seg_hi)
            X, starts = analysis.push(_chunk(view, scale, a, b))
            if X.shape[0] == 0:
                continue
            t = b / fs
            # rx_if=0, lnb_lo=dc: _offset(dl) = dl - dc + rx_corr, the same
            # net mapping ohsnb.radio._off reduces to once the hardware has
            # re-centred on the tracker's own correction (DESIGN.md's
            # frequency model) - this file's samples are already that
            # re-centred stream, so there is no separate hardware tuning
            # step to model.
            rep = tracker.process(X, starts, 0.0, dc, t)
            if rep is not None:
                # The middle beacon's own absolute power (linear, the same
                # |FFT|^2/window^2 units _wide_spectrum's dB axis is in - both
                # come from ohsnb.dsp.lock._psd/ohscore.dsp.spectrum.Scope's
                # identical Hann normalisation), captured here for free
                # rather than a second pass over the file: ohsnb.analyse_power
                # 's over-power scan uses it as "the middle beacon's level at
                # this moment" without re-measuring the beacon itself.
                mb = tracker.beacons.get("middle")
                hist.append({"t": t, "mid_power": mb.last["power"] if mb.last else None, **rep})
    return hist


WOBBLE_WINDOW_S = 60.0   # short enough that a real LNB's own drift is close to linear across it


def _locked_wobble(locked: list[dict], window_s: float = WOBBLE_WINDOW_S) -> float | None:
    """Short-term jitter (Hz rms) around a *local* linear trend, fit fresh
    inside each window_s-second window of locked samples and pooled across
    every window - rather than one fit over the whole file, whose residual
    is inflated by anything a straight line over the whole span cannot
    follow: a real LNB's drift rate changing hours apart (not exactly
    linear, just locally so), or the one-off jump a hysteresis relock
    makes after a fade. Found on Brian's 3-hour 07/10/2026 recording: a
    single whole-file fit read 141.9 Hz rms where every short stretch of
    it read 5-6 Hz - the gap is almost entirely that global curvature, not
    jitter an operator would call "wobble". A window (including a last,
    short one) with fewer than 10 samples contributes nothing rather than
    being fit on too little to mean anything."""
    if len(locked) < 10:
        return None
    t = np.array([e["t"] for e in locked])
    c = np.array([e["rxCorr"] for e in locked])
    resid = []
    i = 0
    n = len(t)
    while i < n:
        j = i
        while j < n and t[j] - t[i] < window_s:
            j += 1
        tw, cw = t[i:j], c[i:j]
        if len(tw) >= 10:
            slope, intercept = np.polyfit(tw - tw[0], cw, 1)
            resid.append(cw - (slope * (tw - tw[0]) + intercept))
        i = j
    if not resid:
        return None
    return float(np.sqrt(np.mean(np.concatenate(resid) ** 2)))


def _beacon_summary(hist: list[dict]) -> dict:
    out = {}
    for name in ("lower", "middle", "upper"):
        snrs = [e["beacons"][name]["snr"] for e in hist if name in e.get("beacons", {})
               and e["beacons"][name].get("snr") is not None]
        heard = sum(1 for s in snrs if s >= LOCK_SNR)
        out[name] = {
            "measurements": len(snrs),
            "heard": heard > 0 and heard >= max(1, len(snrs) // 10),
            "median_snr_db": round(float(np.median(snrs)), 1) if snrs else None,
            "max_snr_db": round(float(np.max(snrs)), 1) if snrs else None,
        }
    locked = [e for e in hist if e.get("state") == "locked" and e.get("rxCorr") is not None]
    drift = wobble = None
    if len(locked) >= 10:
        t = np.array([e["t"] for e in locked])
        c = np.array([e["rxCorr"] for e in locked])
        slope, _intercept = np.polyfit(t - t[0], c, 1)
        drift = round(slope * 60.0, 2)                 # Hz/min, the whole file's own average rate
        # Short-term jitter, not this fit's own residual: see
        # _locked_wobble's docstring for why a single whole-file fit
        # overstates it on anything but a short recording.
        w = _locked_wobble(locked)
        wobble = round(w, 1) if w is not None else None
    locked_seconds = len(locked) * BeaconTracker.UPDATE
    final_corr = locked[-1]["rxCorr"] if locked else (hist[-1]["rxCorr"] if hist else None)
    out["lnb"] = {
        "locked_seconds": round(locked_seconds, 1),
        "total_seconds": round(hist[-1]["t"], 1) if hist else 0.0,
        "rx_corr_hz": round(final_corr, 1) if final_corr is not None else None,
        "drift_hz_per_min": drift,
        "wobble_hz_rms": wobble,
    }
    return out


LNB_BUCKET_S = 600.0   # the task's own "per 10 minutes"


def _lnb_evening(hist: list[dict], bucket_s: float = LNB_BUCKET_S,
                 search_hz: float = 50_000.0) -> dict:
    """The LNB's drift bucketed by `bucket_s` (a fresh linear fit inside
    each bucket, the same fit _beacon_summary takes over the whole file -
    nothing new, just windowed), the total excursion it amounts to, and
    whether BeaconTracker's own numbers (its default +-50 kHz full search,
    MAX_TRACK_ERR=60 Hz between 0.5 s updates) have room to spare against
    what this LNB actually did, for a tester wondering whether a *longer*
    recording's LNB might one day outrun either. A bucket with under 10
    locked samples (most of it spent searching, not tracking) reports
    drift_hz_per_min None rather than fit a line through a handful of
    points either side of a gap."""
    locked = [e for e in hist if e.get("state") == "locked" and e.get("rxCorr") is not None]
    if not locked:
        return {"buckets": [], "excursion_hz": None, "max_abs_drift_hz_per_min": None,
               "search_adequate": None, "search_why": "the beacon was never locked long enough to measure drift",
               "rate_adequate": None, "rate_why": ""}
    t_end = hist[-1]["t"]
    nbuck = max(1, int(math.ceil(t_end / bucket_s)))
    buckets = []
    for i in range(nbuck):
        lo, hi = i * bucket_s, min((i + 1) * bucket_s, t_end)
        pts = [e for e in locked if lo <= e["t"] < hi or (i == nbuck - 1 and e["t"] >= hi)]
        entry = {"t0": round(lo, 1), "t1": round(hi, 1), "locked_seconds": round(len(pts) * BeaconTracker.UPDATE, 1),
                 "drift_hz_per_min": None, "rx_corr_start_hz": None, "rx_corr_end_hz": None}
        if len(pts) >= 10:
            t = np.array([e["t"] for e in pts])
            c = np.array([e["rxCorr"] for e in pts])
            slope, _ = np.polyfit(t - t[0], c, 1)
            entry["drift_hz_per_min"] = round(float(slope) * 60.0, 2)
            entry["rx_corr_start_hz"] = round(float(c[0]), 1)
            entry["rx_corr_end_hz"] = round(float(c[-1]), 1)
        buckets.append(entry)
    corr = np.array([e["rxCorr"] for e in locked])
    excursion = float(corr.max() - corr.min())
    drifts = [abs(b["drift_hz_per_min"]) for b in buckets if b["drift_hz_per_min"] is not None]
    max_drift = max(drifts) if drifts else None
    # Room to spare, not a bare pass/fail: the search is a full +-search_hz
    # look from a trusted correction (BeaconTracker.TIGHT_HZ/NARROW_START
    # try +-2 kHz first, but a search that resumes after a longer gap falls
    # back to the full range), so half of it used across a whole evening
    # leaves margin for a longer session or a colder/warmer LNB; the
    # tracking loop's hysteresis (MAX_TRACK_ERR) is what is actually spent
    # every 0.5 s, so the fastest bucket's drift is judged against a third
    # of that - comfortably inside it, not just under it.
    search_adequate = excursion < search_hz
    search_why = (f"the LNB moved {excursion:.0f} Hz across the recording, "
                 f"{'well inside' if excursion < search_hz * 0.5 else 'using more than half of'} "
                 f"the +-{search_hz / 1000:.0f} kHz full search")
    if max_drift is None:
        rate_adequate, rate_why = None, "too few locked samples in any one bucket to fit a rate"
    else:
        per_update_hz = max_drift * BeaconTracker.UPDATE / 60.0
        margin = BeaconTracker.MAX_TRACK_ERR * 0.3
        rate_adequate = per_update_hz < margin
        rate_why = (f"the fastest 10-minute bucket drifted {max_drift:+.1f} Hz/min, "
                   f"{per_update_hz:.2f} Hz per {BeaconTracker.UPDATE:g} s tracking step against the "
                   f"{BeaconTracker.MAX_TRACK_ERR:.0f} Hz outlier threshold")
    return {"buckets": buckets, "excursion_hz": round(excursion, 1),
           "max_abs_drift_hz_per_min": round(max_drift, 2) if max_drift is not None else None,
           "search_adequate": search_adequate, "search_why": search_why,
           "rate_adequate": rate_adequate, "rate_why": rate_why}


# ----------------------------------------------------------------- FT8/ohsdigi
def _rx_corr_at(beacon_hist: list[dict], t: float, default: float) -> float:
    """The LNB's measured correction at stream time `t`: the locked hist
    entry nearest `t`, or `default` (the seed, or 0) with no locked
    entries at all. A free-running LNB drifts tens of Hz a minute (the
    real recordings: 120-145 Hz/min) - over a 13-minute file that is
    ~1-2 kHz, inside FT8's 3.2 kHz digital filter but not by much, so a
    single rxCorr for the whole file loses slots near the ends of a long
    recording. Nearest-neighbour, not interpolation: UPDATE is 0.5 s and
    the loop's own smoothing already removes the jitter interpolating
    would otherwise chase."""
    locked = [e for e in beacon_hist if e.get("state") == "locked" and e.get("rxCorr") is not None]
    if not locked:
        return default
    times = [e["t"] for e in locked]
    i = bisect.bisect_left(times, t)
    if i <= 0:
        return locked[0]["rxCorr"]
    if i >= len(locked):
        return locked[-1]["rxCorr"]
    before, after = locked[i - 1], locked[i]
    return before["rxCorr"] if (t - before["t"]) <= (after["t"] - t) else after["rxCorr"]


def _ft8_stream_decode(view, scale: float, n: int, fs: float, caps: list, info: dict,
                       rx_corr_est: float, beacon_hist: list[dict],
                       start_utc: float) -> tuple[list[dict], list[dict]]:
    """FT8's channel audio (the same Channel/Demod the engine's VFO uses,
    AGC at the "medium" preset - the state registry's own default,
    ohscore/state.py, and what an operator's own FT8 decoding runs with
    live, so this reads the signal at the level jt9 is actually tuned
    against) built and fed to ohscore.modes.ft8.Decoder one CHUNK_S block
    at a time, never held as a whole-file array: a three-hour recording's
    worth (12 kHz x ~11000 s is half a gigabyte) is exactly the shape of
    memory growth that OOM-killed a laptop running this section
    (07/10/2026) - the fix is to never build it. Feeding also pauses
    (_wait_for_room) once MAX_CONCURRENT_DECODES slots are already being
    decoded, found needing it on a machine fast enough to channelise a
    file quicker than jt9 can keep up: unthrottled, every slot's own
    subprocess launches at once rather than a handful at a time, which is
    its own, larger way to the same place. AGC off was tried first,
    on the reasoning that jt9 judges its own noise floor so an absolute
    level should not matter; it does, on a weak real signal (Brian's
    07/10/2026 recordings): unboosted, a quiet QO-100 FT8 signal is a
    handful of ci16 counts after the 100 Hz passband and the 16-bit WAV
    jt9 reads, which is no longer enough bits for jt9's own algorithm to
    resolve - AGC's up to 100 dB of gain (ohscore/dsp/agc.py) is what turns
    that back into a normally-scaled signal before it is quantised. Only
    one FT8 recording decoded anything with AGC off: whatever was already
    strong enough to need none.

    Returns (events, slots): the decodes the operator would have seen
    (ohscore.modes.ft8.Decoder, unchanged: ohsdigi's since 07/10/2026, jt9's
    where ohsdigi is not built) and, per slot, both decoders' own lists -
    the decoder's and its jt9 or ohsdigi shadow's, captured from
    ohscore.modes.decoder_shadow.record rather than only counted and
    logged, so this report can table them. Either decoder alone is enough
    to decode; with only one there is no second column, and the slots
    list is empty. Returns ([], []) if neither is installed (CAN_DECODE
    False); the caller says so."""
    if not ft8mod.CAN_DECODE:
        return [], []
    events, pairs_raw = _ft8_decode_raw(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, start_utc)
    return events, _ft8_slots(events, pairs_raw)


def _ft8_decode_raw(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                    beacon_hist: list[dict], start_utc: float, part: dict | None = None) -> tuple[list, list]:
    """(events, pairs_raw) - the decoder's own emitted events and each
    pass's decoder-vs-shadow lists - for the whole file, or with `part`
    for one time slice of a parallel run: {"warm", "lo", "hi"} (grid
    blocks: demodulator warm-up from "warm", decoder fed from "lo",
    stopped before "hi"), "own": (u_lo, u_hi), the UTC slot starts this
    slice reports (every slot is reported by exactly one slice), and
    "last" (only the last slice flushes the recording's final, partial
    slot, as the single pass does at the end of the file). A slot's
    decode depends only on the audio placed in it (ohscore.modes.ft8
    places by timestamp; the call-sign tables start fresh each slot), so
    a slice fed from at least a second before u_lo to a second past u_hi
    decodes its own slots from exactly the samples a single pass gives
    them."""
    os.environ.setdefault(decoder_shadow.ENV, "1")
    events: list[dict] = []
    lock = threading.Lock()

    def _emit(ev):
        with lock:
            events.append(ev)

    pairs_raw: list[dict] = []

    def _capture(variant, slot_t0, primary, primary_events, primary_s, shadow, shadow_events, shadow_s):
        with lock:
            pairs_raw.append({"slot": slot_t0, primary: list(primary_events), shadow: list(shadow_events)})
        return {}

    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    corr_at = _CorrAt(beacon_hist, rx_corr_est)
    part = part or {}
    k_lo = part.get("lo", 0)
    samples_fed = _audio_fed_before(fs, grid[k_lo][0]) if (k_lo and k_lo < len(grid)) else 0
    orig_record = decoder_shadow.record
    decoder_shadow.record = _capture
    decoder = ft8mod.Decoder(_emit, variant="ft8")
    try:
        blocks = _audio_blocks(view, scale, fs, grid,
                               lambda a, b, dc: FT8_DIAL_DL - (dc - corr_at(b / fs)),
                               k_lo=k_lo, k_hi=part.get("hi"), k_warm=part.get("warm"))
        for _k, audio in blocks:
            _wait_for_room(decoder)
            decoder.feed(audio, start_utc + samples_fed / ft8mod.FS)
            samples_fed += len(audio)
        if part.get("last", True):
            decoder._close()
        deadline = time.monotonic() + 60.0
        while decoder._busy and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        decoder.close()
        decoder_shadow.record = orig_record
    if "own" in part:
        events = [e for e in events if _owns(part["own"], e.get("slot"))]
        pairs_raw = [p for p in pairs_raw if _owns(part["own"], p["slot"])]
    return events, pairs_raw


def _owns(own: tuple[float, float], slot) -> bool:
    """Whether a slice owning slot starts [own[0], own[1]) reports `slot`.
    Both ends come from the same floor(t / period) * period the decoders
    themselves use, so equal slots are equal floats; the 1 ms only stops a
    last-bit difference ever giving one slot to two slices or to none."""
    if slot is None:
        return False
    return own[0] - 1e-3 <= slot < own[1] - 1e-3


def _ft8_slots(events: list[dict], pairs_raw: list[dict]) -> list[dict]:
    # One decoder only (ohsdigi or jt9 not installed): record() is never
    # called, so the slots are built from the decodes themselves below and
    # the report says there was nothing to compare against.
    #
    # A slot usually gets two decode passes (ohscore.modes.ft8's early one
    # at 13.5 s, the final one at 15 s), each compared on its own: the
    # decoder's dedup (run.seen) only governs what it *emits*, not the
    # list each pass hands to the comparison, so a message the early pass
    # already found is handed over, and counted, again by the final pass.
    # Merging same-slot entries here - unique by text, the same key the
    # emitted events are deduplicated by - is what keeps a report of N
    # real decodes from reading 2N.
    merged: dict[float, dict] = {}
    for p in pairs_raw:
        m = merged.setdefault(p["slot"], {"slot": p["slot"], "jt9": [], "ohsdigi": [], "ohsdigi_ran": True})
        for name in ("jt9", "ohsdigi"):
            for ev in p.get(name, []):
                if not any(e["text"] == ev["text"] for e in m[name]):
                    m[name].append(ev)
    # With one decoder, every decode joins its slot under that decoder's
    # name: until 07/10 the table came from the comparison alone, so a
    # machine without ohsdigi reported jt9 0 on a busy evening.
    if not pairs_raw:
        alone = "ohsdigi" if ft8mod._OHSDIGI_DEC is not None else "jt9"
        for ev in events:
            if "text" not in ev or "slot" not in ev:
                continue
            m = merged.setdefault(ev["slot"], {"slot": ev["slot"], "jt9": [], "ohsdigi": [],
                                               "ohsdigi_ran": alone == "ohsdigi"})
            if not any(e["text"] == ev["text"] for e in m[alone]):
                m[alone].append(ev)
    slots = sorted(merged.values(), key=lambda s: s["slot"])
    return slots


def _ft8_report(events: list[dict], slots: list[dict]) -> dict:
    table = []
    tot_jt9 = tot_ohsdigi = tot_both = 0
    jt9_snrs, ohsdigi_snrs = [], []
    for s in slots:
        pairs, only_jt9, only_ohsdigi = decoder_shadow.pair(s["jt9"], s["ohsdigi"])
        tot_jt9 += len(s["jt9"])
        tot_ohsdigi += len(s["ohsdigi"])
        tot_both += len(pairs)
        jt9_snrs += [e["snr"] for e in s["jt9"]]
        ohsdigi_snrs += [o["snr"] for o in s["ohsdigi"]]
        table.append({
            "slot_utc": time.strftime("%H:%M:%S", time.gmtime(s["slot"])),
            "jt9": len(s["jt9"]), "ohsdigi": len(s["ohsdigi"]), "both": len(pairs),
            "jt9_only": [f'{e["text"]} ({e["snr"]:+d} dB)' for e in only_jt9],
            "ohsdigi_only": [f'{o["text"]} ({o["snr"]:+d} dB)' for o in only_ohsdigi],
        })

    def _dist(xs):
        if not xs:
            return None
        a = np.array(xs, dtype=float)
        return {"n": len(a), "min": round(float(a.min()), 1), "median": round(float(np.median(a)), 1),
               "max": round(float(a.max()), 1)}

    return {"slots": table, "ohsdigi_built": any(s.get("ohsdigi_ran") for s in slots),
            "jt9_total": tot_jt9, "ohsdigi_total": tot_ohsdigi, "both": tot_both,
           "jt9_only_total": tot_jt9 - tot_both, "ohsdigi_only_total": tot_ohsdigi - tot_both,
           "jt9_snr": _dist(jt9_snrs), "ohsdigi_snr": _dist(ohsdigi_snrs)}


# --------------------------------------------------------------- SSB scan
def _ssb_segments() -> list[tuple[float, float]]:
    return [(lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS if classes == {"ssb"}]


def _scan_ssb(view, scale: float, n: int, fs: float, dc_hz: float) -> list[dict]:
    """Candidate SSB voice stations in the bandplan's SSB-only segments,
    each with auto-tune's offset (ohscore.dsp.autotune.auto_tune, the same
    function Auto-tune calls live). One ~10 s window from the middle of
    the recording finds the candidates (occupied(), same module); each
    candidate is then auto-tuned from up to three different times in the
    file (auto-tune refuses a quiet moment, so more than one is given a
    chance) before being reported as refused.

    `dc_hz` must already be the *true* frequency at DC (the caller's
    dc0 - rx_corr_est, not dc0 alone): the bandplan segments this
    searches are true frequencies, and a signal appears rx_corr_est Hz
    high of where it nominally sits."""
    mid = n // 2
    win = min(n, int(10.0 * fs))
    a = max(0, mid - win // 2)
    iq = _chunk(view, scale, a, a + win)
    nper = min(8192, len(iq))
    if nper < 256:
        return []
    f_rel, p = autotune.psd(iq, rate=fs, nper=nper)
    f_abs = f_rel + dc_hz
    out = []
    for seg_lo, seg_hi in _ssb_segments():
        keep = (f_abs >= seg_lo) & (f_abs <= seg_hi)
        if not keep.any():
            continue
        centre = (seg_lo + seg_hi) / 2
        f_seg, p_seg = f_abs[keep] - centre, p[keep]
        floor = autotune.noise_floor(p_seg, f_seg, reach=(seg_hi - seg_lo) / 2)
        for lo, hi in autotune.occupied(f_seg, p_seg, floor, rise_db=2.5, bridge_hz=150.0):
            width = hi - lo
            if 300.0 <= width <= 4200.0:
                out.append({"segment": (seg_lo, seg_hi), "centre_hz": centre + (lo + hi) / 2, "width_hz": width})
    geo = Geometry(fs)
    d = geo.decimation_for(autotune.RATE)
    results = []
    times = [0.5, 0.25, 0.75]
    for cand in out:
        tune = None
        for frac in times:
            t0 = max(0, min(n - int(autotune.CAPTURE_SECONDS * fs) - 1, int(frac * n)))
            geo2 = Geometry(fs)
            an2 = Analysis(geo2)
            ch2 = Channel(geo2, d, freq=cand["centre_hz"] - dc_hz)
            span = int(autotune.CAPTURE_SECONDS * fs) + geo2.V + 4000
            seg = _chunk(view, scale, t0, min(n, t0 + span))
            X, starts = an2.push(seg)
            iq12 = ch2.take(X, starts)
            if len(iq12) < int(autotune.CAPTURE_SECONDS * autotune.RATE * 0.9):
                continue
            tune = autotune.auto_tune(iq12, "usb")
            if tune.ok:
                break
        results.append({"candidate_mhz": round(cand["centre_hz"] / 1e6, 6), "width_hz": round(cand["width_hz"]),
                       "ok": bool(tune and tune.ok),
                       "offset_hz": round(tune.offset, 1) if tune and tune.ok else None,
                       "carrier_mhz": round((cand["centre_hz"] + tune.offset) / 1e6, 6) if tune and tune.ok else None,
                       "why": "" if (tune and tune.ok) else (tune.why if tune else "no signal there at the times tried")})
    return results


# --------------------------------------------------------------------- plots
def _save_plots(out_dir: Path, wide, beacon_hist: list[dict], ft8_table: list[dict]) -> list[str]:
    if not HAVE_MPL:
        return []
    made = []
    if wide is not None:
        f, p = wide
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(f / 1e6, p, linewidth=0.8)
        ax.set_xlabel("MHz"); ax.set_ylabel("dBFS"); ax.set_title("Wideband spectrum (median)")
        fig.tight_layout(); fig.savefig(out_dir / "wide.png", dpi=110); plt.close(fig)
        made.append("wide.png")
    locked = [e for e in beacon_hist if "middle" in e.get("beacons", {})]
    if locked:
        t = [e["t"] for e in locked]
        snr = [e["beacons"]["middle"].get("snr") for e in locked]
        corr = [e["rxCorr"] for e in locked]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
        ax1.plot(t, snr, ".", markersize=2); ax1.set_ylabel("middle beacon SNR (dB)")
        ax2.plot(t, corr, ".", markersize=2); ax2.set_ylabel("rxCorr (Hz)"); ax2.set_xlabel("seconds into the recording")
        fig.tight_layout(); fig.savefig(out_dir / "beacon.png", dpi=110); plt.close(fig)
        made.append("beacon.png")
    if ft8_table:
        jt9 = [r["jt9"] for r in ft8_table]
        ohsdigi = [r["ohsdigi"] for r in ft8_table]
        fig, ax = plt.subplots(figsize=(9, 4))
        x = np.arange(len(ft8_table))
        ax.bar(x - 0.2, jt9, width=0.4, label="jt9")
        ax.bar(x + 0.2, ohsdigi, width=0.4, label="ohsdigi")
        ax.set_xlabel("slot"); ax.set_ylabel("decodes"); ax.legend(); ax.set_title("FT8 decodes per slot")
        fig.tight_layout(); fig.savefig(out_dir / "ft8.png", dpi=110); plt.close(fig)
        made.append("ft8.png")
    return made


def _save_ext_plots(out_dir: Path, ext: dict) -> list[str]:
    """One PNG per extended section that has something to draw - plain
    matplotlib, the same unstyled Agg convention _save_plots already uses
    (this is a batch CLI report, not a dashboard): a census heat map
    (explicitly asked for), and a plot apiece for the others where a
    picture says more than the table beside it. A sequential, single-hue
    colourmap for the heat map (never a rainbow): "viridis", built into
    matplotlib, needs no asset of its own and reads correctly to someone
    colourblind."""
    if not HAVE_MPL:
        return []
    made = []
    mb = ext.get("mmb")
    if mb is not None and mb["available"] and mb["buckets"]:
        t = [b["t0"] / 60.0 for b in mb["buckets"]]
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
        ax1.bar(t, [b["ok"] for b in mb["buckets"]], width=8, label="ok")
        ax1.bar(t, [-b["lost"] for b in mb["buckets"]], width=8, label="lost", color="tab:red")
        ax1.set_ylabel("frames / 10 min"); ax1.legend()
        mer = [b["mer_db_avg"] for b in mb["buckets"]]
        ax2.plot([tt for tt, m in zip(t, mer) if m is not None], [m for m in mer if m is not None], ".-")
        ax2.set_ylabel("MER (dB)"); ax2.set_xlabel("minutes into the recording")
        fig.tight_layout(); fig.savefig(out_dir / "mmb.png", dpi=110); plt.close(fig)
        made.append("mmb.png")
    op = ext.get("overpower")
    if op is not None and op["events"]:
        fig, ax = plt.subplots(figsize=(9, 4))
        for e in op["events"]:
            colour = "tab:red" if e["leila_like"] else "tab:orange"
            ax.plot([e["t_start_s"] / 60.0, e["t_end_s"] / 60.0],
                    [e["freq_lo_hz"] / 1e6] * 2, color=colour, linewidth=3)
        ax.set_xlabel("minutes into the recording"); ax.set_ylabel("MHz")
        ax.set_title("Over-power events (red: possible LEILA)")
        fig.tight_layout(); fig.savefig(out_dir / "overpower.png", dpi=110); plt.close(fig)
        made.append("overpower.png")
    ss = ext.get("ssb_scale")
    if ss is not None and ss["offset_hz"]:
        offs = [a["offset_hz"] for a in ss["attempts"] if a["ok"]]
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.hist(offs, bins=min(20, max(5, len(offs) // 2)))
        ax.set_xlabel("tuning offset (Hz)"); ax.set_ylabel("count"); ax.set_title("SSB auto-tune offsets")
        fig.tight_layout(); fig.savefig(out_dir / "ssb_scale.png", dpi=110); plt.close(fig)
        made.append("ssb_scale.png")
    om = ext.get("other_modes")
    if om is not None:
        modes = [m for m in ("ft4", "q65", "js8", "psk31") if om[m]["available"] and om[m]["buckets"]]
        if modes:
            fig, ax = plt.subplots(figsize=(9, 4))
            width = 0.8 / len(modes)
            for i, mode in enumerate(modes):
                buckets = om[mode]["buckets"]
                x = np.arange(len(buckets)) + i * width
                ax.bar(x, [b["decodes"] for b in buckets], width=width, label=mode.upper())
            ax.set_xlabel("10-minute bucket"); ax.set_ylabel("decodes"); ax.legend()
            ax.set_title("FT4/Q65/JS8/PSK31 decodes per 10 minutes")
            fig.tight_layout(); fig.savefig(out_dir / "other_modes.png", dpi=110); plt.close(fig)
            made.append("other_modes.png")
    cs = ext.get("census")
    if cs is not None and cs["counts"]:
        fig, ax = plt.subplots(figsize=(10, 5))
        data = np.array(cs["counts"])
        im = ax.imshow(data, aspect="auto", cmap="viridis", interpolation="nearest",
                       extent=(0, len(cs["bucket_starts"]) * cs["bucket_s"] / 60.0, len(cs["segments"]), 0))
        ax.set_yticks(np.arange(len(cs["segments"])) + 0.5)
        ax.set_yticklabels([s["label"] for s in cs["segments"]], fontsize=7)
        ax.set_xlabel("minutes into the recording")
        ax.set_title("Band census: average occupied runs per line")
        fig.colorbar(im, ax=ax, label="signals")
        fig.tight_layout(); fig.savefig(out_dir / "census.png", dpi=110); plt.close(fig)
        made.append("census.png")
    return made


# ----------------------------------------------------------------------- text
def _report_text(r: dict) -> str:
    lines = []
    L = lines.append
    m = r["meta"]
    L(f"IQ analysis: {r['file']}" + (f" (recorded by {m['author']})" if m["author"] else ""))
    L(f"{m['duration_s']:.1f} s at {m['fs'] / 1e6:g} MS/s ({m['datatype']}), {sigmf.size_text(r['bytes'])}")
    if r["warnings"]:
        for w in r["warnings"]:
            L(f"! {w}")
    lv = r["levels"]
    clip_line = (f"Peak {lv['peak_dbfs']:+.1f} dBFS, RMS {lv['rms_dbfs']:+.1f} dBFS, headroom {lv['headroom_db']:.1f} dB, "
                f"clipping {lv['clipped_pct']:.3f}% ({lv['clipped_samples']} samples)")
    if m["dropped_samples"]:
        clip_line += f", {m['dropped_samples']} samples dropped while recording (a slow disk)"
    L(clip_line)
    if r["gaps"]:
        # Built apart: a quote of the same kind inside a nested f-string is
        # Python 3.12 syntax, and this module must load on 3.11 (Debian 12,
        # the AppImage's bookworm), as ohsnb/__main__ imports it at start.
        gaps = ", ".join(f"{g['seconds']:.1f} s" for g in r["gaps"][:4])
        L(f"Gaps: {len(r['gaps'])} ({gaps}"
          f"{', ...' if len(r['gaps']) > 4 else ''})")
    if r["noise"]["floor_db"] is not None:
        n = r["noise"]
        rise = f"{n['rise_db']:+.1f} dB" if n["rise_db"] is not None else "n/a"
        L(f"Noise floor {n['floor_db']:+.1f} dB, transponder {rise} over it")
    radio_line = f"Radio: {m['hw'] or '(not recorded)'}; gain {m['gain_mode'] or '?'} {m['gain_db']}"
    if m["dial"] is not None:
        radio_line += f"; dial {m['dial'] / 1e6:.6f} MHz {(m['mode'] or '?').upper()}"
    if m["rx_corr0"] is not None:
        radio_line += f"; rxCorr at start {m['rx_corr0']} Hz"
    L(radio_line)
    if not r["qo100"]:
        L(f"Not analysed as QO-100 NB: {r['qo100_why']}")
    else:
        b = r["beacons"]
        lnb = b["lnb"]
        L(f"Middle beacon: {'heard' if b['middle']['heard'] else 'not reliably heard'}"
          + (f", median SNR {b['middle']['median_snr_db']:+.1f} dB" if b["middle"]["median_snr_db"] is not None else ""))
        if lnb["drift_hz_per_min"] is not None:
            L(f"LNB: rxCorr {lnb['rx_corr_hz']:+.1f} Hz, drift {lnb['drift_hz_per_min']:+.2f} Hz/min, "
              f"wobble {lnb['wobble_hz_rms']:.1f} Hz rms (locked {lnb['locked_seconds']:.0f} of "
              f"{lnb['total_seconds']:.0f} s)")
        else:
            L(f"LNB: beacon lock did not hold long enough to measure drift (locked {lnb['locked_seconds']:.0f} of "
              f"{lnb['total_seconds']:.0f} s)")
        ev = b.get("lnb_evening", {})
        if len(ev.get("buckets", [])) > 1:
            L(f"LNB over the recording: {ev['excursion_hz']:.0f} Hz total excursion, "
              f"{ev['max_abs_drift_hz_per_min']:+.2f} Hz/min at its fastest 10 minutes; "
              f"{ev['search_why']}; {ev['rate_why']}")
        for name in ("lower", "upper"):
            bb = b[name]
            L(f"{name.capitalize()} beacon: {'heard' if bb['heard'] else 'not heard'}"
              + (f", median SNR {bb['median_snr_db']:+.1f} dB" if bb["median_snr_db"] is not None else ""))
        f8 = r["ft8"]
        if f8 is None:
            L("FT8: not decoded (neither ohsdigi nor jt9 is installed)")
        else:
            if not f8.get("ohsdigi_built", True) and f8["slots"]:
                L(f"FT8 @ {FT8_DIAL_DL / 1e6:.3f} MHz: jt9 {f8['jt9_total']} (ohsdigi not built here: no comparison)")
            else:
                L(f"FT8 @ {FT8_DIAL_DL / 1e6:.3f} MHz: jt9 {f8['jt9_total']}, ohsdigi {f8['ohsdigi_total']}, "
                  f"both {f8['both']} ({f8['jt9_only_total']} jt9-only, {f8['ohsdigi_only_total']} ohsdigi-only)")
            if f8["jt9_snr"]:
                L(f"  jt9 SNR {f8['jt9_snr']['min']:+.0f}..{f8['jt9_snr']['max']:+.0f} dB "
                  f"(median {f8['jt9_snr']['median']:+.0f})")
            if f8["ohsdigi_snr"]:
                L(f"  ohsdigi SNR {f8['ohsdigi_snr']['min']:+.0f}..{f8['ohsdigi_snr']['max']:+.0f} dB "
                  f"(median {f8['ohsdigi_snr']['median']:+.0f})")
        ssb = r["ssb"]
        heard = [s for s in ssb if s["ok"]]
        L(f"SSB voice: {len(heard)} of {len(ssb)} candidate signal(s) auto-tuned"
          if ssb else "SSB voice: no candidate signals found in the SSB segments")
        for s in heard[:6]:
            L(f"  ~{s['candidate_mhz']:.4f} MHz: carrier {s['carrier_mhz']:.4f} MHz (offset {s['offset_hz']:+.0f} Hz)")
        _ext_text(L, r.get("ext") or {})
    if r["plots"]:
        L(f"Plots: {', '.join(r['plots'])}")
    elif not HAVE_MPL:
        L("Plots skipped: matplotlib is not installed")
    text = "\n".join(lines) + "\n"
    if not r.get("ext") and len(text.encode("utf-8")) > REPORT_BUDGET:
        # Headline numbers are already first; a long SSB or gap list is what
        # grows this, so that is what gives way. An --extended report is
        # explicitly asked to be long (seven analyses' worth); only the
        # base report promises "under ~2 KB".
        keep = [ln for ln in lines if not ln.startswith("  ~")]
        text = "\n".join(keep) + "\n"
    return text


def _ext_text(L, ext: dict) -> None:
    """Lines for whichever --extended/--mmb/--overpower/--ssb-scale/
    --other-modes/--census sections were run - nothing printed for one
    that was not asked for, so a plain --analyse report is unchanged."""
    mb = ext.get("mmb")
    if mb is not None:
        if not mb["available"]:
            L(f"Multimedia beacon: not decoded ({mb['why']})")
        else:
            L(f"Multimedia beacon: {mb['frames_ok_total']} frames ok, {mb['frames_lost_total']} lost "
              f"(over {len(mb['buckets'])} x 10-min buckets)")
            for c in mb["content"][:8]:
                size = f" ({c['size_bytes']} bytes)" if c.get("size_bytes") else ""
                L(f"  mmb {c['kind']}: {c['name'] or c.get('text', '')[:40]}{size}")
    op = ext.get("overpower")
    if op is not None:
        evs = op["events"]
        L(f"Over-power events (> middle beacon +{op['margin_db']:.0f} dB): {len(evs)}")
        for e in evs[:8]:
            if e["leila_like"] is None:
                leila = ""
            elif e["leila_like"]:
                leila = f"; possible LEILA ({e['leila_why']})"
            else:
                leila = f"; not LEILA-shaped ({e['leila_why']})"
            L(f"  {e['t_start_s']:.0f}-{e['t_end_s']:.0f} s, {e['freq_lo_hz'] / 1e6:.4f}-"
              f"{e['freq_hi_hz'] / 1e6:.4f} MHz, +{e['max_excess_db']:.1f} dB{leila}")
    ss = ext.get("ssb_scale")
    if ss is not None:
        total = ss["accepted"] + ss["refused"]
        L(f"SSB at scale: {ss['accepted']} of {total} candidate attempts auto-tuned")
        if ss["refusals"]:
            top = sorted(ss["refusals"].items(), key=lambda kv: -kv[1])[:3]
            L("  refused: " + "; ".join(f"{n} x {why}" for why, n in top))
        if ss["offset_hz"]:
            o = ss["offset_hz"]
            L(f"  accepted offsets: {o['min']:+.0f}..{o['max']:+.0f} Hz (median {o['median']:+.0f}, n={o['n']})")
    om = ext.get("other_modes")
    if om is not None:
        for mode in ("ft4", "q65", "js8", "psk31"):
            s = om[mode]
            if not s["available"]:
                L(f"{mode.upper()}: not decoded ({s['why']})")
            else:
                where = f" near {s['dial_mhz']:.4f} MHz" if s["dial_mhz"] is not None else ""
                L(f"{mode.upper()}: {s['total']} decodes{where}")
    cs = ext.get("census")
    if cs is not None:
        busiest = max(((sum(row) / max(1, len(row)), seg["label"]) for row, seg in zip(cs["counts"], cs["segments"])),
                     default=(0.0, ""))
        L(f"Band census: {len(cs['bucket_starts'])} x {cs['bucket_s'] / 60:.0f}-min buckets, "
          f"{len(cs['segments'])} segments; busiest on average: {busiest[1]} ({busiest[0]:.1f} signals/line)")


# ------------------------------------------------------------------- driver
class _Clock:
    """Progress lines for a long run (stderr, from run()): until 08/10 a
    three-hour --extended analysis printed nothing at all for hours, so
    nobody could tell a slow section from a hung one."""

    def __init__(self, say):
        self.say = say
        self.t0 = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def run(self, label: str, fn):
        self.say(_("{label}: started").format(label=label))
        t = time.monotonic()
        out = fn()
        self.say(_("{label}: done in {secs:.1f} s").format(label=label, secs=time.monotonic() - t))
        return out


def _beacons_from(beacon_hist: list[dict], rx_corr0: float) -> tuple[dict, float]:
    """The beacon section of the report from the tracker's history, and
    the LNB correction everything after it works in (rx_corr0, the
    recording's own figure, until the tracker measured one)."""
    beacons = _beacon_summary(beacon_hist)
    beacons["lnb_evening"] = _lnb_evening(beacon_hist)
    measured = beacons["lnb"]["rx_corr_hz"]
    return beacons, (measured if measured is not None else rx_corr0)


def _compute_serial(view, scale: float, n_total: int, fs: float, info: dict, full_scale: int,
                    start_utc: float, dc0, qo100: bool, span, want: dict, out_dir: Path, clock: _Clock) -> dict:
    """Every section, one after another in this process - the analysis
    as it always ran, and what --jobs 1 still does. ohsnb.analyse_parallel
    .compute returns the same dict from worker processes."""
    caps = info["captures"]
    levels = clock.run("levels", lambda: _level_stats(view, scale, n_total, full_scale))

    # The beacon tracker runs first: everything below that talks in absolute
    # ("true") frequencies - the wideband plot's axis, the FT8 dial, the SSB
    # scan - needs the LNB's own measured error (rx_corr_est) as well as
    # dc0, because dc0 alone is only the *nominal* frequency at DC (what
    # the hardware was tuned to assuming no LNB error); the true frequency
    # a raw offset-from-DC represents is dc0 - rx_corr_est + offset. Missing
    # this (an earlier version of this module did) looks for FT8 and SSB
    # tens of kHz from where they really are, and crops the wideband
    # spectrum against the bandplan's edges mis-registered by the same
    # amount - this is what was wrong on Brian's 07/10/2026 recordings,
    # whose LNB was ~25-27 kHz off.
    beacons = {}
    beacon_hist: list[dict] = []
    ft8_report = None
    ssb: list[dict] = []
    rx_corr_est = info["rx_corr0"] or 0.0
    if qo100 and dc0 is not None:
        beacon_hist = clock.run("beacon tracker", lambda: _run_beacon_tracker(view, scale, n_total, fs, caps,
                                                                               info, rx_corr_est))
        beacons, rx_corr_est = _beacons_from(beacon_hist, rx_corr_est)

    wide = floor_db = rise_db = None
    if dc0 is not None and fs > 0:
        wide, floor_db, rise_db = clock.run("wide spectrum", lambda: _wide_spectrum(
            view, scale, n_total, fs, dc0 - rx_corr_est, span))

    if qo100 and dc0 is not None:
        if not ft8mod.CAN_DECODE:
            ft8_report = None
        else:
            events, slots = clock.run("FT8", lambda: _ft8_stream_decode(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist, start_utc))
            ft8_report = _ft8_report(events, slots)
        ssb = clock.run("SSB scan", lambda: _scan_ssb(view, scale, n_total, fs, dc0 - rx_corr_est))

    ext: dict = {}
    if qo100 and dc0 is not None:
        if want["mmb"]:
            from . import analyse_mmb
            ext["mmb"] = clock.run("multimedia beacon", lambda: analyse_mmb.mmb_report(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist, out_dir))
        if want["overpower"]:
            from . import analyse_power
            ext["overpower"] = clock.run("over-power", lambda: analyse_power.overpower_events(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist))
        if want["ssb_scale"]:
            from . import analyse_ssb
            ext["ssb_scale"] = clock.run("SSB at scale", lambda: analyse_ssb.ssb_at_scale(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist))
        if want["other_modes"]:
            from . import analyse_digital
            ext["other_modes"] = clock.run("other modes", lambda: analyse_digital.other_modes_report(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist, start_utc))
        if want["census"]:
            from . import analyse_census
            ext["census"] = clock.run("census", lambda: analyse_census.band_census(
                view, scale, n_total, fs, caps, info, rx_corr_est, beacon_hist))
    return {"levels": levels, "beacon_hist": beacon_hist, "beacons": beacons, "rx_corr_est": rx_corr_est,
            "wide": wide, "floor_db": floor_db, "rise_db": rise_db, "ft8": ft8_report, "ssb": ssb, "ext": ext}


def analyse(path: Path, out_dir: Path | None = None, minutes: float | None = None, *,
           extended: bool = False, mmb: bool = False, overpower: bool = False,
           ssb_scale: bool = False, other_modes: bool = False, census: bool = False,
           jobs: int = 1, progress=None, slice_s: float | None = None) -> dict:
    """The base report, plus whichever of the slow, opt-in sections are
    asked for (each also turned on by `extended`): `mmb` (the multimedia
    beacon across the whole file, ohsnb.analyse_mmb), `overpower` (events
    stronger than the middle beacon, with a LEILA plausibility check,
    ohsnb.analyse_power), `ssb_scale` (auto-tune at scale, ohsnb.analyse_ssb),
    `other_modes` (FT4/Q65/JS8/PSK31 decode counts, ohsnb.analyse_digital)
    and `census` (occupied-run counts per band-plan segment over time,
    ohsnb.analyse_census). None of them run on a recording that is not
    QO-100 NB (the same gate the base beacon/FT8/SSB sections already use):
    there is nothing in any of them to report on a band they do not cover.

    `jobs` > 1 runs the sections in that many worker processes, most of
    them also cut into time slices (ohsnb.analyse_parallel says how, and
    which are left whole and why); the report is the same either way.
    `progress(text)`, if given, hears a line as each section or slice
    starts and finishes. `slice_s` overrides the shortest slice a
    parallel run will cut - for tests, which need slice boundaries inside
    a recording of a minute or two."""
    data_path, meta_path = sigmf.paths(path)
    raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    problems = sigmf.validate(raw_meta)
    info = _adapt_meta(raw_meta)
    fs = info["fs"]
    if fs <= 0:
        raise ValueError(_("{file} has no usable core:sample_rate").format(file=meta_path.name))
    view, scale, n_total = _raw_iq(data_path, info["datatype"], info.get("scale"))
    full_scale = int(round(1.0 / scale)) - 1
    if minutes:
        n_total = min(n_total, int(minutes * 60 * fs))
    duration_s = n_total / fs

    caps = info["captures"]
    dc0 = _capture_dc(caps[0] if caps else {}, info)
    qo100, qo100_why = _looks_like_qo100(info, dc0)
    start_cap = caps[0] if caps else {}
    start_utc = sigmf.parse_utc(start_cap["core:datetime"]) if start_cap.get("core:datetime") else time.time()
    out_dir = Path(out_dir) if out_dir else path.parent / (data_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    want = {"mmb": extended or mmb, "overpower": extended or overpower, "ssb_scale": extended or ssb_scale,
            "other_modes": extended or other_modes, "census": extended or census}
    say = progress or (lambda _msg: None)
    clock = _Clock(say)
    span = (bandplan.DL_LO - WIDE_MARGIN, bandplan.DL_HI + WIDE_MARGIN) if qo100 and dc0 else \
        (dc0 - fs * 0.45, dc0 + fs * 0.45) if dc0 else (0.0, 0.0)
    if jobs and jobs > 1:
        from . import analyse_parallel
        say(ngettext("{secs:.0f} s of IQ, {jobs} worker process", "{secs:.0f} s of IQ, {jobs} worker processes",
                     jobs).format(secs=duration_s, jobs=jobs))
        res = analyse_parallel.compute(
            data_path=data_path, info=info, n=n_total, full_scale=full_scale, start_utc=start_utc,
            dc0=dc0, qo100=qo100, span=span, want=want, out_dir=out_dir, jobs=jobs, say=say,
            slice_s=slice_s, verbose=hasattr(progress, "t0_wall"), t0_wall=getattr(progress, "t0_wall", None))
    else:
        say(_("{secs:.0f} s of IQ, one process").format(secs=duration_s))
        res = _compute_serial(view, scale, n_total, fs, info, full_scale, start_utc, dc0, qo100, span,
                              want, out_dir, clock)
    levels, beacon_hist, beacons, rx_corr_est = res["levels"], res["beacon_hist"], res["beacons"], res["rx_corr_est"]
    wide, ft8_report, ssb, ext = res["wide"], res["ft8"], res["ssb"], res["ext"]
    floor_db, rise_db = res["floor_db"], res["rise_db"]
    say(_("analysis done in {secs:.1f} s").format(secs=clock.elapsed()))

    gaps = _gaps(caps, fs)
    warnings = list(problems)
    if info["clipped"] is not None and int(info["clipped"]) != levels["clipped_samples"]:
        warnings.append(f"the recorder counted {info['clipped']} clipped samples; this read counted "
                        f"{levels['clipped_samples']} (a --minutes cap, most likely)")
    noise = {"floor_db": None, "rise_db": None}
    if dc0 is not None and fs > 0:
        noise = {"floor_db": round(floor_db, 1) if floor_db is not None else None,
                "rise_db": round(rise_db, 1) if rise_db is not None else None}

    report = {
        "file": str(data_path.name),
        "bytes": data_path.stat().st_size,
        "meta": {"app": info["app"], "version": info["version"], "os": info["os"], "hw": info["hw"],
                "fs": fs, "datatype": info["datatype"], "duration_s": round(duration_s, 1),
                "gain_mode": info["gain_mode"], "gain_db": info["gain_db"], "rx_corr0": info["rx_corr0"],
                "mode": info["mode"], "dial": info["dial"], "dropped_samples": info["dropped_samples"],
                "author": info["author"]},
        "warnings": warnings,
        "levels": levels,
        "gaps": gaps,
        "noise": noise,
        "qo100": qo100,
        "qo100_why": qo100_why,
        "beacons": beacons,
        "ft8": ft8_report,
        "ssb": ssb,
        "ext": ext,
        "plots": [],
    }

    ft8_table = ft8_report["slots"] if ft8_report else []
    report["plots"] = _save_plots(out_dir, wide, beacon_hist, ft8_table) + _save_ext_plots(out_dir, ext)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "report.txt").write_text(_report_text(report), encoding="utf-8")
    return report


# ------------------------------------------------------------------------ CLI
def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ohsnb --analyse",
                                 description="Report on a SigMF receive IQ recording, offline")
    ap.add_argument("file", help="a .sigmf-meta or .sigmf-data path (either names the pair)")
    ap.add_argument("--out", type=Path, default=None, help="folder for the report (default: beside the recording)")
    ap.add_argument("--minutes", type=float, default=None, help="only analyse the first N minutes")
    ap.add_argument("--extended", action="store_true",
                    help="every slow section below (a long recording: expect minutes, not seconds)")
    ap.add_argument("--mmb", action="store_true", help="the multimedia beacon across the whole recording")
    ap.add_argument("--overpower", action="store_true",
                    help="downlink events stronger than the middle beacon, with a LEILA plausibility check")
    ap.add_argument("--ssb-scale", action="store_true", dest="ssb_scale",
                    help="SSB auto-tune every 10 minutes across the recording, not just once")
    ap.add_argument("--other-modes", action="store_true", dest="other_modes",
                    help="FT4/Q65/JS8/PSK31 decode counts beside FT8")
    ap.add_argument("--census", action="store_true",
                    help="occupied-run counts per band-plan segment, as a heat map and a table")
    ap.add_argument("--jobs", type=int, default=None,
                    help="worker processes (default: one per core less one, fewer if memory is short; "
                         "1 = everything in this process, as before)")
    ap.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    a = ap.parse_args(argv)
    path = Path(a.file)
    if a.jobs is None:
        from .analyse_parallel import default_jobs
        jobs = default_jobs()
    else:
        jobs = max(1, a.jobs)
    t0 = time.time()

    def progress(text: str) -> None:
        print(f"[{time.time() - t0:7.1f} s] {text}", file=sys.stderr, flush=True)
    progress.t0_wall = t0       # the workers' own "started" lines count from the same moment

    try:
        report = analyse(path, a.out, a.minutes, extended=a.extended, mmb=a.mmb, overpower=a.overpower,
                         ssb_scale=a.ssb_scale, other_modes=a.other_modes, census=a.census,
                         jobs=jobs, progress=None if a.quiet else progress)
    except (ValueError, OSError) as e:
        print(f"Could not analyse {path}: {e}", file=sys.stderr)
        return 1
    out_dir = a.out or (path.parent / sigmf.paths(path)[0].stem)
    print(_report_text(report), end="")
    print(f"(full report: {out_dir}/report.txt, report.json)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
