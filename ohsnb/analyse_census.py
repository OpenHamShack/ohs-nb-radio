"""Band census: how occupied each band-plan segment was, in short buckets
across a whole recording - "what did an evening on QO-100 actually look
like" without a human watching the waterfall the whole time.

A `--census` section of `python3 -m ohsnb --analyse`, not folded into the
base report: it reads the wideband spectrum at a much faster line rate
than the noise-floor pass does (ohsnb.analyse._wide_spectrum, one median
over the whole file), so it costs a real second pass over the IQ - the
slow kind the module's own docstring says belongs behind a flag.

Reuses, rather than reimplements:

- `ohscore.dsp.spectrum.Scope`, the live wide scope's own averaged-spectrum
  class, exactly as `ohsnb.analyse._wide_spectrum` already reads it;
- `ohscore.dsp.autotune.noise_floor`/`occupied`, the same run-finding the
  SSB scan already uses, segment by segment rather than across the whole
  band - the transponder's noise floor is not flat enough across 500 kHz
  (see analyse.py's own OUTSIDE_GUARD comment) to share one threshold, and
  a beacon's own segment needs its own floor beneath it in any case;
- `ohsnb.bandplan.SEGMENTS`, the one list of segment edges every other part
  of QO-100 NB already works from.

What "signals per 5 minutes" means here, deliberately: the average number
of occupied runs autotune.occupied() finds in a segment, over the lines
that fall in that bucket - not a station count. A steady QSO sitting in
one segment for an hour scores on every line it is seen on, not once;
turning this into a true station census needs following a signal frame to
frame (identity, not just occupancy), a different and harder job than
this one. Reported as such, not dressed up as more than it is.
"""
from __future__ import annotations

import math

import numpy as np

from ohscore.dsp import autotune
from ohscore.dsp.spectrum import Scope, wide_nfft

from . import bandplan
from .analyse import _chunk, _chunk_grid, _CorrAt, _scope_at

BUCKET_S = 300.0     # the task's own "per 5 minutes"
FPS = 0.5            # one spectral line every 2 s: fine enough to see a segment fill and empty again
# autotune.occupied/noise_floor were built for a 12 kHz SSB channel's Welch
# periodogram (~1-3 Hz bins, dozens of averaged frames): asked of a
# 500 kHz-wide line at the wide scope's usual 2048-bin resolution (~240 Hz
# bins, avg=8) they found 3-20 spurious one-bin "runs" a line in pure
# noise - too coarse for occupied()'s 60 Hz smoothing window to smooth
# anything, and too few averaged frames to tame a single periodogram's own
# variance. Measured on 6 s of white noise alone (no signal): 2048 bins/
# avg=8 -> dozens of false runs; 32768 bins (~15 Hz bins) with avg=16 ->
# zero, and a real tone in the same span still comes back as exactly one
# run. Costs more FFT work per line (a bigger nfft, twice the averaged
# frames) - acceptable behind this section's own flag.
NFFT_BINS = 32_768
AVG = 16
RISE_DB = 4.0        # over the segment's own floor to count as occupied
BRIDGE_HZ = 150.0     # gaps narrower than this, within one segment, are one signal not two (autotune's SSB default)


def band_census(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                beacon_hist: list[dict], bucket_s: float = BUCKET_S, fps: float = FPS) -> dict:
    """Occupied-run counts per band-plan segment, bucketed every `bucket_s`
    seconds across the file. Returns {"bucket_s", "segments": [{"label",
    "lo", "hi"}], "bucket_starts": [s, ...], "counts": [[per-bucket avg
    occupied runs] per segment]}. `counts[i][j]` is the mean, over every
    spectral line whose end fell in bucket j, of how many occupied runs
    autotune.occupied() found in segment i's own slice of that line.

    Frequencies are corrected for the LNB's measured error exactly as
    lnb.analyse.analyse()'s own wideband pass is (dc0 - rx_corr_at(t)):
    a band census misregistered by the same ~25 kHz analyse.py's module
    docstring describes would put CW-segment energy in the SSB count and
    the reverse."""
    segs = bandplan.SEGMENTS
    nbuck = max(1, int(math.ceil((n / fs) / bucket_s)))
    sums, counts_n = _tally(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, bucket_s, fps)
    return _finish(sums, counts_n, bucket_s, nbuck)


def _tally(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
           beacon_hist: list[dict], bucket_s: float = BUCKET_S, fps: float = FPS,
           k_lo: int = 0, k_hi: int | None = None) -> tuple[list, list]:
    """(sums, counts_n) per segment per bucket, for the spectral lines
    ending in grid blocks k_lo..k_hi-1 (ohsnb.analyse._chunk_grid; all of
    them by default). Each line is judged on its own, and both tallies are
    whole numbers (a float sum of integers is exact), so a parallel run
    (ohsnb.analyse_parallel) adds every slice's tallies and gets the
    single pass's figures to the last digit."""
    segs = bandplan.SEGMENTS
    span = bandplan.DL_HI - bandplan.DL_LO
    nfft = wide_nfft(NFFT_BINS, fs, span)
    scope = Scope(fs, nfft, fps=fps, avg=AVG)
    nbuck = max(1, int(math.ceil((n / fs) / bucket_s)))
    sums = [[0.0] * nbuck for _ in segs]
    counts_n = [[0] * nbuck for _ in segs]
    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    k_hi = len(grid) if k_hi is None else k_hi
    if k_lo < len(grid):
        _scope_at(scope, view, scale, grid[k_lo][0])
    corr_at = _CorrAt(beacon_hist, rx_corr_est)
    for a, b, dc in grid[k_lo:k_hi]:
        for end, db in scope.process(_chunk(view, scale, a, b)):
            t = end / fs
            freqs = (dc - corr_at(t)) + (np.arange(nfft) - nfft // 2) * scope.bin_hz
            p_lin = 10.0 ** (db / 10.0)
            bucket = min(nbuck - 1, int(t // bucket_s))
            for i, (lo, hi, _label, _classes, _maxbw) in enumerate(segs):
                keep = (freqs >= lo) & (freqs < hi)
                if keep.sum() < 5:
                    continue
                f_seg = freqs[keep]
                p_seg = p_lin[keep]
                floor = autotune.noise_floor(p_seg, f_seg - f_seg.mean(), reach=(hi - lo) / 2)
                runs = autotune.occupied(f_seg, p_seg, floor, rise_db=RISE_DB, bridge_hz=BRIDGE_HZ)
                sums[i][bucket] += len(runs)
                counts_n[i][bucket] += 1
    return sums, counts_n


def _finish(sums: list, counts_n: list, bucket_s: float, nbuck: int) -> dict:
    segs = bandplan.SEGMENTS
    counts = [[round(s / c, 2) if c else 0.0 for s, c in zip(srow, nrow)] for srow, nrow in zip(sums, counts_n)]
    return {
        "bucket_s": bucket_s,
        "segments": [{"label": label, "lo": lo, "hi": hi} for lo, hi, label, _classes, _maxbw in segs],
        "bucket_starts": [round(j * bucket_s, 1) for j in range(nbuck)],
        "counts": counts,
    }
