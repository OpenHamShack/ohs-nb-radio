"""SSB auto-tune, run at scale across a whole recording.

ohsnb.analyse's own `_scan_ssb` finds candidates from one ~10 s window at
the middle of the file and retries auto-tune from three fixed fractions
of it (0.25/0.5/0.75) - right for a tester's short recording, where a
station heard at all is probably still on when any of those three land,
but wrong for a multi-hour one: a station that came and went in the first
half-hour is simply never looked at. This section instead looks every
`window_s` seconds (default 10 minutes) across the whole file, each time
finding candidates and auto-tuning them from that window's own IQ - the
same primitives `_scan_ssb` itself is built from (ohsnb.bandplan's SSB-only
segments, ohscore.dsp.autotune's occupied-band detection and `auto_tune`,
the same function Auto-tune calls live), not a second way of deciding what
is a voice signal.

What it measures is auto-tune on voices, as an operator would use it: a
candidate must look like speech in the 10 s it is found in (a band at
least MIN_WIDTH_HZ wide while active, whose level swings MIN_SWING_DB or
more), and its 4 s capture is taken where that band was busiest, as an
operator right-clicks while somebody talks. Until 08/10 the candidates
were any 300-4200 Hz run of a 146 Hz-bin average and the capture was the
window's centre, so the acceptance figure counted CW, carriers, noise and
the silence between overs as auto-tune's refusals. On 07/10/2026's 3 h
recording (with the capture also tuned to the right frequency - see
_attempts): 107 candidates, 17 accepted, became 61 and 17; capturing at
the centre instead of where the band was busiest, 15 of those 61.

Reports the acceptance rate (candidates found vs successfully tuned),
refusals tallied by auto_tune's own reason, and the distribution of
accepted stations' tuning offsets from their own candidate band's centre -
what "at scale" means for this task beyond the single data point
`_scan_ssb` gives.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from ohscore.dsp import autotune
from ohscore.dsp.bank import Analysis, Channel, Geometry

from .analyse import _chunk, _dc_for_t, _rx_corr_at, _ssb_segments

WINDOW_S = 600.0                     # the task's own "at scale": a look every 10 minutes
CANDIDATE_WINDOW_S = 10.0            # how much IQ finds candidates, same as _scan_ssb's own single window
# Spectrum frames for finding candidates: the shortest power-of-two FFT
# whose bins are no wider than this - 36.6 Hz at 1.2 MS/s (32768 points,
# 27 ms). Until 08/10 one Welch average at 8192 points (146 Hz bins)
# found them, coarse enough that a CW carrier, a run of FT8-like tones or
# a lump of noise read 439-732 Hz wide and passed for a voice.
BIN_HZ = 40.0
# Frames are averaged into blocks this long; a candidate's spectrum is each
# bin's ACTIVE_PCT percentile over the blocks - what the band looks like
# while the station is talking, not averaged with the pauses between its
# overs (a station talking for 3 s of the 10 hardly shows in the mean).
BLOCK_S = 0.25
ACTIVE_PCT = 90.0
# Real SSB speech reaches most of a 2.4-2.7 kHz transmit filter at some
# point; nothing else in the SSB segments that is this wide moves its
# level like speech. MAX is auto-tune's own (ohscore.dsp.autotune
# MAX_WIDTH): the band while talking is wider than its average - 4.7 kHz
# for the simulator's voice at 20 dB over the noise, which read 3.7 kHz
# in the old mean spectrum and _scan_ssb's 4.2 kHz limit.
MIN_WIDTH_HZ, MAX_WIDTH_HZ = 1500.0, 4800.0
# Least swing (dB, 90th over 10th percentile of the band's power, frame by
# frame across the 10 s) for speech. Measured on 07/10/2026's 3 h
# recording: see the commit that added it.
MIN_SWING_DB = 6.0


def _frames_spectra(iq: np.ndarray, keep: np.ndarray, nper: int) -> np.ndarray:
    """Power of each non-overlapping Hann frame of `iq` (fft-shifted), only
    in the bins `keep` selects: (frames, kept bins). Batched, so 10 s of
    1.2 MS/s never needs more than a few MB of FFT at once."""
    nf = len(iq) // nper
    w = np.hanning(nper).astype(np.float32)
    out = np.empty((nf, int(keep.sum())), np.float32)
    for a in range(0, nf, 16):
        b = min(nf, a + 16)
        x = iq[a * nper:b * nper].reshape(b - a, nper) * w
        out[a:b] = (np.abs(np.fft.fftshift(np.fft.fft(x, axis=1), axes=1)) ** 2)[:, keep]
    return out


def _candidates(iq: np.ndarray, fs: float, dc_true: float, segments: list | None = None) -> list[dict]:
    """Voice-like occupied bands in the SSB-only segments (or `segments`,
    true Hz - tools/autotune_labels.py also searches the mixed one): wide
    enough at some point to be speech (MIN_WIDTH_HZ), and with a level that
    comes and goes as speech does (MIN_SWING_DB). Each carries `t_busy_s`, the
    start (seconds into `iq`) of the CAPTURE_SECONDS where its own band
    was most often active - where an operator would right-click."""
    nper = 1 << int(np.ceil(np.log2(fs / BIN_HZ)))
    nf = len(iq) // nper
    blk = max(1, int(round(BLOCK_S * fs / nper)))
    if nf < 2 * blk:
        return []
    f_abs = np.fft.fftshift(np.fft.fftfreq(nper, 1 / fs)) + dc_true
    segs = [(lo, hi) for lo, hi in (_ssb_segments() if segments is None else segments)
            if ((f_abs >= lo) & (f_abs <= hi)).any()]
    if not segs:
        return []
    keep = np.zeros(nper, bool)
    for lo, hi in segs:
        keep |= (f_abs >= lo) & (f_abs <= hi)
    S = _frames_spectra(iq, keep, nper)
    f_k = f_abs[keep]
    nb = nf // blk
    B = S[:nb * blk].reshape(nb, blk, -1).mean(axis=1)
    active = np.percentile(B, ACTIVE_PCT, axis=0)
    cap_frames = max(1, int(round(autotune.CAPTURE_SECONDS * fs / nper)))
    out = []
    for seg_lo, seg_hi in segs:
        ins = (f_k >= seg_lo) & (f_k <= seg_hi)
        centre = (seg_lo + seg_hi) / 2
        f_seg, p_seg = f_k[ins] - centre, active[ins]
        floor = autotune.noise_floor(p_seg, f_seg, reach=(seg_hi - seg_lo) / 2)
        cols = np.nonzero(ins)[0]
        for lo, hi in autotune.occupied(f_seg, p_seg, floor, rise_db=2.5, bridge_hz=150.0):
            width = hi - lo
            if not MIN_WIDTH_HZ <= width <= MAX_WIDTH_HZ:
                continue
            band = cols[(f_seg >= lo) & (f_seg <= hi)]
            pw = S[:, band].sum(axis=1)
            p10, p90 = np.percentile(pw, 10), np.percentile(pw, 90)
            swing = float(10 * np.log10(p90 / max(p10, 1e-30)))
            if swing < MIN_SWING_DB:
                continue
            # Active: nearer, in dB, the band's loud frames than its quiet
            # ones. The capture is the run of cap_frames with most of them.
            on = (10 * np.log10(np.maximum(pw, 1e-30)) >= 5 * np.log10(max(p10, 1e-30) * p90)).astype(float)
            c = np.concatenate([[0.0], np.cumsum(on)])
            k = int(np.argmax(c[cap_frames:] - c[:-cap_frames])) if nf > cap_frames else 0
            out.append({"segment": (seg_lo, seg_hi), "centre_hz": centre + (lo + hi) / 2, "width_hz": width,
                        "swing_db": swing, "t_busy_s": k * nper / fs})
    return out


def ssb_at_scale(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
                 beacon_hist: list[dict], window_s: float = WINDOW_S) -> dict:
    """{"attempts": [{"t_s","candidate_mhz","width_hz","ok","offset_hz",
    "carrier_mhz","why"}], "accepted": n, "refused": n, "refusals":
    {reason: count}, "offset_hz": {"n","min","median","max"}}."""
    return _summary(_attempts(view, scale, n, fs, caps, info, rx_corr_est, beacon_hist, window_s))


def _windows(n: int, fs: float, window_s: float = WINDOW_S) -> int:
    win = int(window_s * fs)
    return max(1, n // win) if n >= win else 1


def _attempts(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
              beacon_hist: list[dict], window_s: float = WINDOW_S, i_lo: int = 0,
              i_hi: int | None = None) -> list[dict]:
    """The attempts of windows i_lo..i_hi-1 (all of them by default). Each
    window reads only its own IQ and starts its own filter bank, so a
    parallel run (ohsnb.analyse_parallel) gives each worker a range of
    windows and joins the lists in window order - the same list."""
    geo = Geometry(fs)
    d = geo.decimation_for(autotune.RATE)
    win = int(window_s * fs)
    cwin = int(CANDIDATE_WINDOW_S * fs)
    nwin = _windows(n, fs, window_s)
    attempts = []
    for i in range(i_lo, nwin if i_hi is None else min(i_hi, nwin)):
        a0 = i * win
        b0 = min(n, a0 + win) if n >= win else n
        t_mid = (a0 + b0) / 2 / fs
        dc0 = _dc_for_t(caps, info, fs, t_mid)
        if dc0 is None:
            continue
        dc_true = dc0 - _rx_corr_at(beacon_hist, t_mid, rx_corr_est)
        ca = max(a0, (a0 + b0) // 2 - cwin // 2)
        cb = min(b0, ca + cwin)
        if cb - ca < 256:
            continue
        for cand in _candidates(_chunk(view, scale, ca, cb), fs, dc_true):
            # The capture starts where the candidate was busiest (until 08/10:
            # the window's centre, whether or not anyone was talking then).
            t0 = max(a0, min(b0 - int(autotune.CAPTURE_SECONDS * fs) - 1, ca + int(cand["t_busy_s"] * fs)))
            span = int(autotune.CAPTURE_SECONDS * fs) + geo.V + 4000
            seg = _chunk(view, scale, t0, min(n, t0 + span))
            an = Analysis(geo)
            # centre_hz is a true frequency, so it sits centre_hz - dc_true
            # from the IQ's DC. Until 08/10 this said dc0 (nominal), and
            # every capture was tuned rx_corr Hz - 28 kHz on 07/10's 3 h
            # recording - away from the candidate it was meant to test.
            ch = Channel(geo, d, freq=cand["centre_hz"] - dc_true)
            X, starts = an.push(seg)
            iq12 = ch.take(X, starts)
            entry = {"t_s": round(t_mid, 1), "candidate_mhz": round(cand["centre_hz"] / 1e6, 6),
                    "width_hz": round(cand["width_hz"]), "swing_db": round(cand["swing_db"], 1),
                    "capture_s": round(t0 / fs, 2), "ok": False, "offset_hz": None, "carrier_mhz": None,
                    "why": ""}
            if len(iq12) < int(autotune.CAPTURE_SECONDS * autotune.RATE * 0.9):
                entry["why"] = "too little signal captured at this window"
            else:
                tune = autotune.auto_tune(iq12, "usb")
                entry["ok"] = bool(tune.ok)
                if tune.ok:
                    entry["offset_hz"] = round(tune.offset, 1)
                    entry["carrier_mhz"] = round((cand["centre_hz"] + tune.offset) / 1e6, 6)
                else:
                    entry["why"] = tune.why
            attempts.append(entry)
    return attempts


def _summary(attempts: list[dict]) -> dict:
    accepted =[a for a in attempts if a["ok"]]
    refused = [a for a in attempts if not a["ok"]]
    refusals = Counter(a["why"] for a in refused)
    offs = [a["offset_hz"] for a in accepted]
    offset_dist = None
    if offs:
        arr = np.array(offs, dtype=float)
        offset_dist = {"n": len(arr), "min": round(float(arr.min()), 1), "median": round(float(np.median(arr)), 1),
                       "max": round(float(arr.max()), 1)}
    return {"attempts": attempts, "accepted": len(accepted), "refused": len(refused),
           "refusals": dict(refusals.most_common()), "offset_hz": offset_dist}
