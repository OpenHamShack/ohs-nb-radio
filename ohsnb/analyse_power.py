"""Over-power events (a downlink stronger than the middle beacon - the
licence condition itself: AMSAT-DL's "keep your signal below the beacon
level", docs/qo100-research.md section 9) and AMSAT-DL's LEILA siren,
their own automatic warning for exactly that, in a recording.

Both are judged by ohsnb/dsp/overpower.py, the module the radio's live
watch runs, so a recording analysed here reads as the radio showed it:

- **Over-power events**: any stretch where a downlink has more power in a
  beacon-wide slice than the middle beacon has in its own, by `MARGIN_DB`,
  outside the beacons' guard zones, both read off the same wideband
  spectral line (ohsnb.dsp.overpower.judge_line). Grouped across lines
  into (start, end, frequency range, duration, excess over the beacon).
- **A LEILA flag on each one**: whether LEILA's siren - two tones 205 Hz
  apart taking turns every 200 ms, measured on Brian's recordings of
  17/10/2026 - sounded on it during the event or the 20 s after
  (ohsnb.dsp.overpower.Siren). Until then this was a guess at a swept tone,
  which the real siren is not.
"""
from __future__ import annotations

import numpy as np

from ohscore.dsp.bank import Analysis, Geometry
from ohscore.dsp.spectrum import Scope, wide_nfft

from . import bandplan
from .analyse import CHUNK_S, _chunk, _chunk_grid, _CorrAt, _dc_for_t, _rx_corr_at, _scope_at

# The definitions themselves are shared with the live watch (ohsnb/overpower.py),
# so a recording analysed here reads as the radio showed it live.
from .dsp.overpower import (AVG, FPS, MARGIN_DB, MIN_DURATION_S, NFFT_BINS, SIREN_AFTER_S,  # noqa: F401
                            SIREN_MATCH_HZ, Siren, Tracker, judge_line)

_Tracker = Tracker      # the name this module's callers and tests have used


def _leila_check(view, scale: float, fs: float, dc: float, rx_corr: float, f_lo: float, f_hi: float,
                 t_start: float, t_end: float) -> dict:
    """Whether LEILA's siren sounded on this event: ohsnb.dsp.overpower.Siren
    (the live watch's own detector) over the event and SIREN_AFTER_S after
    it - the siren comes in the FT8 slot after the over - restricted to the
    event's band and 2 kHz either side."""
    a = max(0, int((t_start - 1.0) * fs))
    b = min(int((t_end + SIREN_AFTER_S) * fs), len(view))
    if b - a < int(3.0 * fs):
        return {"leila_like": False, "why": "the recording ends too soon after the event to say"}
    geo = Geometry(fs)
    an = Analysis(geo)
    base = dc - rx_corr
    siren = Siren(geo, span=(f_lo - 2_000.0, f_hi + 2_000.0))
    # Streamed a CHUNK_S block at a time: an event's whole span was once read
    # in one piece, ~10 GB for a 10-minute event, and an hours-long carrier
    # is more than any machine has. Siren itself keeps two seconds of bins.
    step = int(CHUNK_S * fs)
    for lo in range(a, b, step):
        X, starts = an.push(_chunk(view, scale, lo, min(lo + step, b)))
        siren.push(X, starts, base)
    heard = [e for e in siren.sirens if e["looks"] >= 3 and e["hi"] >= f_lo - SIREN_MATCH_HZ
             and e["lo"] <= f_hi + SIREN_MATCH_HZ]
    if heard:
        e = heard[0]
        return {"leila_like": True,
                "why": (f"LEILA's siren at {e['freq'] / 1e6:.6f} MHz, {e['t_start']:.1f}-{e['t_last']:.1f} s: two "
                        f"tones {e['hi'] - e['lo']:.0f} Hz apart taking turns every 200 ms")}
    return {"leila_like": False, "why": "no siren on it during the event or the 20 s after"}


def overpower_events(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                     beacon_hist: list[dict], margin_db: float = MARGIN_DB,
                     min_duration_s: float = MIN_DURATION_S, fps: float = FPS,
                     leila_check: bool = True) -> dict:
    """Events where some part of the downlink read more than `margin_db`
    over the middle beacon's own peak, timed and bounded in frequency, with
    a LEILA plausibility check on each (see the module docstring for both).
    Returns {"events": [{"t_start_s", "t_end_s", "duration_s", "freq_lo_hz",
    "freq_hi_hz", "max_excess_db", "leila_like", "leila_why"}]}.

    In three steps a parallel run (ohsnb.analyse_parallel) can split
    differently: the spectral lines (_lines - the expensive part, and
    each line depends only on its own samples, so it slices exactly),
    then joining them into events (_events_from_lines - sequential, each
    line's matching depends on what is open from the lines before, so it
    is never sliced; it is a few list operations a line, run once in the
    parent over every slice's lines in order), then a LEILA check per
    event (_entry - independent of every other event)."""
    lines = _lines(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, margin_db, fps)
    events = _events_from_lines(lines, min_duration_s)
    return {"events": [_entry(view, scale, fs, caps, info, rx_corr_est, beacon_hist, e, leila_check)
                       for e in events],
            "margin_db": margin_db}


def _lines(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
           beacon_hist: list[dict], margin_db: float = MARGIN_DB, fps: float = FPS,
           k_lo: int = 0, k_hi: int | None = None) -> list[tuple[float, list]]:
    """[(t, hits)] for every spectral line ending in grid blocks
    k_lo..k_hi-1 (ohsnb.analyse._chunk_grid) - all of them by default."""
    span = bandplan.DL_HI - bandplan.DL_LO
    nfft = wide_nfft(NFFT_BINS, fs, span)
    scope = Scope(fs, nfft, fps=fps, avg=AVG)
    grid, _contiguous = _chunk_grid(caps, info, n, fs)
    k_hi = len(grid) if k_hi is None else k_hi
    if k_lo < len(grid):
        _scope_at(scope, view, scale, grid[k_lo][0])
    corr_at = _CorrAt(beacon_hist, rx_corr_est)
    offsets = (np.arange(nfft) - nfft // 2) * scope.bin_hz
    out = []
    for a, b, dc in grid[k_lo:k_hi]:
        for end, db in scope.process(_chunk(view, scale, a, b)):
            t = end / fs
            why, hits = judge_line((dc - corr_at(t)) + offsets, db, scope.bin_hz, margin_db)
            if why == "none":
                continue
            out.append((t, hits))
    return out


def _events_from_lines(lines: list[tuple[float, list]], min_duration_s: float = MIN_DURATION_S) -> list[dict]:
    tracker = _Tracker()
    for t, hits in lines:
        tracker.add_line(hits, t)
    return [e for e in tracker.finish() if (e["t_last"] - e["t_start"]) >= min_duration_s]


def _entry(view, scale: float, fs: float, caps: list, info: dict, rx_corr_est: float,
           beacon_hist: list[dict], e: dict, leila_check: bool = True) -> dict:
    entry = {"t_start_s": round(e["t_start"], 1), "t_end_s": round(e["t_last"], 1),
             "duration_s": round(e["t_last"] - e["t_start"], 1),
             "freq_lo_hz": round(e["f_lo"], 1), "freq_hi_hz": round(e["f_hi"], 1),
             "max_excess_db": round(e["max_excess_db"], 1), "leila_like": None, "leila_why": ""}
    if leila_check:
        dc = _dc_for_t(caps, info, fs, (e["t_start"] + e["t_last"]) / 2)
        if dc is not None:
            rc = _rx_corr_at(beacon_hist, (e["t_start"] + e["t_last"]) / 2, rx_corr_est)
            lc = _leila_check(view, scale, fs, dc, rc, e["f_lo"], e["f_hi"], e["t_start"], e["t_last"])
            entry["leila_like"], entry["leila_why"] = lc["leila_like"], lc["why"]
    return entry
