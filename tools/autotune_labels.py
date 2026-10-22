#!/usr/bin/env python3
"""A labelled auto-tune corpus from recordings, using leaked carriers.

    tools/autotune_labels.py build OUTDIR REC.sigmf-data [...] [--jobs 6]
                                   [--seconds 20] [--lnb FILE=report.json]
                                   [--name FILE=short]
    tools/autotune_labels.py score OUTDIR [--gaps 100,125,150] [--jobs 6]
    tools/autotune_labels.py inspect OUTDIR [--n 30] [--seed 1]

SSB sends no carrier, which is why auto-tune has to find one from the
voice - and also why its answers are hard to check on real signals: there
is nothing to compare them with. Except that many QO-100 stations' carriers
are not quite suppressed. A transmitter with 40-50 dB of carrier
suppression still leaves a steady line a few hundred hertz under its voice
(USB), standing 15-30 dB out of the noise in a few seconds' spectrum, and
that line IS the answer, independent of anything auto-tune measures.

`build` walks each recording in non-overlapping windows of --seconds and
looks for the line first, then the voice above it - not the other way
round, which was tried first and found almost nothing: a busy segment's
noise floor (the 20th percentile of its spectrum) sits high enough that
weaker voices - the ones whose carriers show, often - were never
candidates. A line is a label only if:

- it stands LINE_DB over its neighbourhood (the median of 50 Hz block
  medians within +-150 Hz) in the average of the window's 4 s spectra
  (0.25 Hz bins), and SEGMENT_DB over it in at least PRESENT of those
  spectra, at frequencies within DRIFT_HZ of each other - steady, as a
  carrier is and a CW signal, a data mode or a voice harmonic is not;
- it is not the top of something wider (a CW or data station): the
  spectrum 15-40 Hz either side of it stands under SHOULDER_DB;
- above it, its carrier-side edge GAP Hz from the line, is a voice by the
  same test --analyse --ssb-scale uses (ohsnb.analyse_ssb._candidates:
  1.5 kHz or more wide while talking, a level that swings like speech),
  measured with the line notched out, and that edge at least LABEL_GAP_HZ
  (100 Hz) above the line - see LABEL_GAP_HZ. GAP is wide on purpose (30-650 Hz):
  a label must not assume the gap auto-tune assumes (MIN_EDGE_GAP), or
  scoring that gap against it would prove nothing;
- no other line within RIVAL_DB of it lies 650 Hz under to 40 Hz over
  that edge: two lines are a choice the label cannot make;
- it does not outlive the voice: a carrier leaks only while its
  transmitter is keyed, so a line seen in a 4 s segment where the voice
  band is silent belongs to something else.

Each label's window is saved as auto-tune hears it: the 12 kHz receive
channel (ohscore.dsp.bank Analysis + Channel, as the engine takes it) for
--seconds, complex64, at four dials, in the format of the 07/10 corpora
(~/openhamshack-samples/qo100-2026-10-07/autotune-eval/c1, its index.json and
work/score.py): `lo`, `hi`, `line`, `dials` and `truth` in Hz from the
recording's DC, one .npz per key holding each dial's capture. Added:
`seconds`, `t_s` (start in the recording), `busy_s` (start of the 4 s
where the voice band was busiest, found without the label), `gap_hz`,
`drift_hz`, `present`, `width_hz`, `station` (the same carrier, within
300 Hz, in one recording), `abs_carrier_khz`.

`score` runs ohscore.dsp.autotune.auto_tune(iq, "usb") - the public entry
point only, so it scores whichever auto-tune is checked out - on each
dial's busiest 4 s and on the whole capture, against the labels: answered,
right (within 10 Hz), wrong, refusals by reason; and again with
autotune.MIN_EDGE_GAP set to each of --gaps, if that module has one.

`inspect` draws a spectrogram PNG of a random sample of labels into
OUTDIR/inspect/, the label marked, for checking by eye.

Bounded memory: a window is read from a read-only memmap, and its filter
bank is fed 2 s at a time; a worker peaks near 0.5 GB at 1.2 MS/s.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohscore import sigmf  # noqa: E402
from ohscore.dsp import autotune  # noqa: E402
from ohscore.dsp.bank import Analysis, Channel, Geometry  # noqa: E402
from ohsnb import analyse as A  # noqa: E402
from ohsnb import analyse_ssb, bandplan  # noqa: E402

RATE = 12_000.0
# Voice segments searched: every one SSB is allowed in - the two SSB-only
# ones, the emergency channel and the mixed one above them (SSB is common
# there too). True Hz.
SEGMENTS = [(lo, hi) for lo, hi, _l, classes, _m in bandplan.SEGMENTS if "ssb" in (classes or ())]
SEG_S = 4.0            # line-search segment: 0.25 Hz bins, Hann
BLOCK_BINS, REF_BLOCKS = 200, 3   # neighbourhood: 50 Hz block medians, +-150 Hz
LINE_DB = 10.0         # averaged spectrum: line over its neighbourhood
SEGMENT_DB = 8.0       # one segment: line over its neighbourhood
PRESENT = 0.4          # share of the segments it must be seen in
# Most its segment-by-segment frequency may spread, LNB motion taken out.
# Not 2 Hz, which was tried first: on 07/10 the leaked carriers that are
# plainly carriers by eye wander +-3-4 Hz over 20 s (the LNB's wobble, 2.7
# Hz rms, plus each transmitter's own), and 2 Hz kept almost none. A voice
# harmonic moves tens of hertz; the scorer compares an answer with the
# track at the time of its capture, not with the average.
DRIFT_HZ = 10.0
WOBBLE_HZ = 6.0        # how far from its average a segment's peak is looked for
SHOULDER_DB = 6.0      # the spectrum 15-40 Hz beside the line, over the neighbourhood
GAP = (30.0, 650.0)    # the voice's lower edge over the line, Hz: searched
# Least gap a label may have. Practically all QO-100 voice is USB, and an
# SSB transmit filter only starts passing audio ~100-300 Hz above the
# carrier, so a voice that seems to start under 100 Hz above a line is a
# line at the bottom of the voice (a low harmonic, or the voice's own
# lowest energy), not its carrier. On c3 (07/10, 3 h) those were 160 of 405
# labels, and auto-tune answered ~150 Hz under nearly all of them - the
# disagreement was the label's. Still the search starts at GAP[0], so such
# a voice is refused for this reason by name ("voice too near the line")
# rather than passed over for a voice further up. 100, not MIN_EDGE_GAP,
# so labels between 100 and 150 Hz still test that constant.
LABEL_GAP_HZ = 100.0
# The line removed (+-) before the voice test. Not 4 Hz, which was tried
# first: over 20 s a real carrier wanders +-3-4 Hz with the LNB (and up
# to DRIFT_HZ on its own), so a 4 Hz notch left enough of it that the
# voice test's 150 Hz bridge joined it to the voice, whose edge then read
# 12 Hz UNDER its own carrier and was refused. 20 stays under GAP[0], so
# no voice edge the label accepts is ever inside it.
NOTCH_HZ = 20.0
SEARCH = (-650.0, 40.0)   # rival lines: Hz from the voice's lower edge
RIVAL_DB = 10.0        # the next line there at least this far down
# A line seen in this many 4 s segments where the voice above it is silent
# (under QUIET_SHARE of its frames active) is not that voice's carrier.
# Found on the 3 h file's first build: a 3 s wideband burst over a line
# seen in two of the five segments, one of them silent. Two silent
# segments, tried first to allow for an operator pausing with the PTT
# held, let it through; a label has to be right more than it has to be
# plentiful, so one is enough.
SILENT_SEGS = 1
# ...and seen there clearly: SEGMENT_DB finds a line in pure noise in ~8 %
# of segments (the best of 48 bins searched), which refused a real label
# whose operator was silent for 14 s of the 20. At 12 dB noise does it
# about once in 10^4.
SILENT_LINE_DB = 12.0
QUIET_SHARE = 0.05
TRUE_HZ = 10.0         # an answer this close to the label is right
WARM_S = 1.0           # filter bank warm-up read before each window, discarded


# --------------------------------------------------------------- reading
class Rec:
    """A recording: memmap, scale, sample rate, and the true frequency at DC
    at any time (nominal DC minus the LNB's error)."""

    def __init__(self, data: str, report: str | None = None):
        self.data_path, meta_path = sigmf.paths(Path(data))
        self.info = A._adapt_meta(json.loads(meta_path.read_text(encoding="utf-8")))
        self.fs = self.info["fs"]
        self.view, self.scale, self.n = A._raw_iq(self.data_path, self.info["datatype"], self.info.get("scale"))
        self.caps = self.info["captures"]
        self.rx0 = self.info["rx_corr0"] or 0.0
        self.hist: list[dict] = []
        if report:
            # A previous --analyse report's 10-minute LNB buckets, as a
            # coarse beacon history: true frequency only decides which
            # bins are in an SSB segment and the label's absolute kHz.
            for b in json.loads(Path(report).read_text(encoding="utf-8"))["beacons"].get("lnb_evening", {}).get("buckets", []):
                if b.get("rx_corr_start_hz") is not None:
                    self.hist.append({"t": b["t0"], "state": "locked", "rxCorr": b["rx_corr_start_hz"]})
                    self.hist.append({"t": b["t1"] - 0.5, "state": "locked", "rxCorr": b["rx_corr_end_hz"]})

    def dc(self, t: float) -> tuple[float, float]:
        dc0 = A._dc_for_t(self.caps, self.info, self.fs, t)
        return dc0, dc0 - A._rx_corr_at(self.hist, t, self.rx0)


def _channels(rec: Rec, a: int, b: int, freqs: list[float]) -> list[np.ndarray]:
    """The 12 kHz channel at each of `freqs` (Hz from DC) for samples a..b,
    the filter bank warmed up on WARM_S before a and fed 2 s at a time."""
    geo = Geometry(rec.fs)
    d = geo.decimation_for(RATE)
    warm = min(a, int(WARM_S * rec.fs) // d * d)
    an = Analysis(geo)
    chs = [Channel(geo, d, freq=f) for f in freqs]
    outs: list[list[np.ndarray]] = [[] for _ in freqs]
    step = int(2.0 * rec.fs) // geo.L * geo.L
    end = min(rec.n, b + geo.V + geo.L)
    for p in range(a - warm, end, step):
        X, starts = an.push(A._chunk(rec.view, rec.scale, p, min(end, p + step)))
        for ch, o in zip(chs, outs):
            o.append(ch.take(X, starts))
    want = (b - a) // d
    return [np.concatenate(o)[warm // d:warm // d + want] for o in outs]


# ------------------------------------------------------------ the label
def _spec(y: np.ndarray, nfft: int | None = None) -> np.ndarray:
    w = np.hanning(len(y)).astype(np.float32)
    return np.fft.fftshift(np.abs(np.fft.fft(y * w, nfft)) ** 2)


def _block_ref(P: np.ndarray) -> np.ndarray:
    """Each bin's neighbourhood level: the median of the REF_BLOCKS
    block medians around its own (blocks of BLOCK_BINS)."""
    nb = len(P) // BLOCK_BINS
    med = np.median(P[:nb * BLOCK_BINS].reshape(nb, BLOCK_BINS), axis=1)
    pad = np.pad(med, REF_BLOCKS, mode="edge")
    ref = np.median(np.lib.stride_tricks.sliding_window_view(pad, 2 * REF_BLOCKS + 1), axis=1)
    out = np.repeat(ref, BLOCK_BINS)
    return np.concatenate([out, np.full(len(P) - len(out), ref[-1])])


def lines(iq: np.ndarray, fs: float, dc_true: float, segments) -> list[dict]:
    """Steady narrow lines in `segments` (true Hz) of a window of wideband
    IQ: [{"line" (Hz from DC), "db", "present", "drift", "lnb_hz" (the
    common motion, per segment), "shoulder_db", "why"}], "why" empty for
    one that passed (see the module docstring)."""
    ns = int(SEG_S * fs)
    k = len(iq) // ns
    if k < 2:
        return []
    f = np.fft.fftshift(np.fft.fftfreq(ns, 1 / fs))
    keep = np.zeros(ns, bool)
    for lo, hi in segments:
        keep |= (f + dc_true >= lo) & (f + dc_true <= hi)
    if not keep.any():
        return []
    # The segments' bins side by side: a neighbourhood straddling a join
    # (150 Hz either side of three of them) is the only place this blurs.
    f = f[keep]
    w = np.hanning(ns).astype(np.float32)
    S = np.empty((k, len(f)), np.float32)
    for i in range(k):
        S[i] = (np.abs(np.fft.fftshift(np.fft.fft(iq[i * ns:(i + 1) * ns] * w))) ** 2)[keep]
    df = float(f[1] - f[0])
    avg = S.mean(axis=0)
    ref = _block_ref(avg)
    hot = np.nonzero(avg >= ref * 10 ** (LINE_DB / 10))[0]
    out = []
    if not len(hot):
        return out
    # Clusters of hot bins, 8 Hz apart or more: one line each, at its peak.
    cuts = np.nonzero(np.diff(hot) * df > 8.0)[0]
    seg_refs = [_block_ref(s) for s in S]
    found = []
    for grp in np.split(hot, cuts + 1):
        i = int(grp[np.argmax(avg[grp])])
        if i == 0 or i == len(f) - 1:
            continue
        fi = _peak(f, avg, i)
        # Segment by segment: where it is (within WOBBLE_HZ), and whether
        # it stands SEGMENT_DB out there at all.
        near = np.nonzero(np.abs(f - fi) <= WOBBLE_HZ)[0]
        pk = np.full(k, np.nan)
        pdb = np.full(k, np.nan)
        for n, (s, r) in enumerate(zip(S, seg_refs)):
            j = int(near[np.argmax(s[near])])
            if 0 < j < len(f) - 1 and s[j] >= r[j] * 10 ** (SEGMENT_DB / 10):
                pk[n] = _peak(f, s, j)
                pdb[n] = 10 * np.log10(s[j] / r[j])
        found.append((i, fi, pk, pdb))
    # The LNB moves every line together - 2.7 Hz rms of wobble on 07/10 -
    # so a steady carrier's own drift is what is left after the motion all
    # the lines seen in every segment share (their median, segment by
    # segment). With fewer than three such lines it is not taken out.
    full = [pk - pk.mean() for _i, _fi, pk, _d in found if not np.isnan(pk).any()]
    lnb = np.median(full, axis=0) if len(full) >= 3 else np.zeros(k)
    out = []
    for i, fi, pk, pdb in found:
        seen = ~np.isnan(pk)
        own = pk[seen] - lnb[seen]
        sh = (np.abs(f - fi) >= 15.0) & (np.abs(f - fi) <= 40.0)
        ln = {"line": fi, "db": round(float(10 * np.log10(avg[i] / ref[i])), 1),
              "present": round(float(seen.mean()), 2),
              "drift": round(float(own.max() - own.min()), 2) if seen.sum() >= 2 else None,
              "lnb_hz": [round(float(x), 2) for x in lnb],
              "track_hz": [None if np.isnan(x) else round(float(x - fi), 2) for x in pk],
              "seg_db": [None if np.isnan(x) else round(float(x), 1) for x in pdb],
              "shoulder_db": round(float(10 * np.log10(np.median(avg[sh]) / ref[i])), 1) if sh.any() else 0.0,
              "why": "", "_f": f, "_avg": avg}
        if ln["present"] < PRESENT:
            ln["why"] = "intermittent"
        elif ln["drift"] is None or ln["drift"] > DRIFT_HZ:
            ln["why"] = "drifts"
        elif ln["shoulder_db"] > SHOULDER_DB:
            ln["why"] = "on a wider signal"
        out.append(ln)
    return out


def _peak(f: np.ndarray, P: np.ndarray, i: int) -> float:
    """Bin i's peak, parabolically interpolated in log power."""
    y0, y1, y2 = (np.log(P[i + j] + 1e-30) for j in (-1, 0, 1))
    den = y0 - 2 * y1 + y2
    return float(f[i] + (0.5 * (y0 - y2) / den if den < 0 else 0.0) * (f[1] - f[0]))


def _notch(y: np.ndarray, at: float) -> np.ndarray:
    """y with everything within NOTCH_HZ of `at` (Hz from y's centre)
    removed - the line, so the voice test sees only the voice (a strong
    carrier inside 150 Hz of the voice would otherwise be bridged into its
    run and read as its edge)."""
    Y = np.fft.fft(y)
    fy = np.fft.fftfreq(len(y), 1 / RATE)
    Y[np.abs(fy - at) <= NOTCH_HZ] = 0.0
    return np.fft.ifft(Y).astype(np.complex64)


def voice_above(y: np.ndarray, centre: float, line: float) -> dict | None:
    """The voice whose carrier-side edge is GAP Hz above `line`, in the
    channel `y` centred on `centre` (both Hz from DC), by the same test
    --ssb-scale uses (ohsnb.analyse_ssb._candidates), or None."""
    yn = _notch(y, line - centre)
    cands = analyse_ssb._candidates(yn, RATE, centre, [(line - 1500.0, line + 4500.0)])
    best = None
    for c in cands:
        lo = c["centre_hz"] - c["width_hz"] / 2
        if GAP[0] <= lo - line <= GAP[1] and (best is None or lo < best["lo"]):
            best = {"lo": lo, "hi": lo + c["width_hz"], "width": c["width_hz"], "swing": c["swing_db"]}
    return best


def _active(y: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, int]:
    """Frame by frame (512 samples), whether the band lo..hi (Hz from the
    channel's centre) was active - nearer, in dB, its loud frames than its
    quiet ones, analyse_ssb's rule - and the frame length."""
    fr = 512
    n = len(y) // fr
    x = y[:n * fr].reshape(n, fr)
    fb = np.fft.fftfreq(fr, 1 / RATE)
    pw = (np.abs(np.fft.fft(x * np.hanning(fr), axis=1)) ** 2)[:, (fb >= lo) & (fb <= hi)].sum(axis=1)
    p10, p90 = np.percentile(pw, 10), np.percentile(pw, 90)
    return (10 * np.log10(np.maximum(pw, 1e-30)) >= 5 * np.log10(max(p10, 1e-30) * p90)).astype(float), fr


def _silent_with_line(y: np.ndarray, lo: float, hi: float, seg_db: list) -> int:
    """How many SEG_S segments the line stood SILENT_LINE_DB out in
    (`seg_db`, one entry per segment, None where not seen) while the voice
    band lo..hi (Hz from y's centre) was silent: under QUIET_SHARE of its
    frames active."""
    on, fr = _active(y, lo, hi)
    per = int(round(SEG_S * RATE / fr))
    n = 0
    for k, v in enumerate(seg_db):
        seg = on[k * per:(k + 1) * per]
        if v is not None and v >= SILENT_LINE_DB and len(seg) and seg.mean() < QUIET_SHARE:
            n += 1
    return n


def _busy(y: np.ndarray, lo: float, hi: float) -> float:
    """Start (s) of the CAPTURE_SECONDS in which the band lo..hi (Hz from
    the channel's centre) was most often active - analyse_ssb's rule."""
    on, fr = _active(y, lo, hi)
    n = len(on)
    m = int(round(autotune.CAPTURE_SECONDS * RATE / fr))
    c = np.concatenate([[0.0], np.cumsum(on)])
    return float(int(np.argmax(c[m:] - c[:-m])) * fr / RATE) if n > m else 0.0


# ----------------------------------------------------------------- build
_REC: dict = {}


class _Inline:
    """--jobs 1: map in this process. No pool to start, and nothing has to
    be pickled - which a worker can only do for a module it can import by
    name, not this file loaded from its path (as the tests load it)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def map(fn, items, chunksize=1):
        return map(fn, items)


def _pool(jobs: int):
    return _Inline() if jobs <= 1 else ProcessPoolExecutor(jobs)


def _rec(path, report):
    if path not in _REC:
        _REC[path] = Rec(path, report)
    return _REC[path]


def _window(job) -> tuple[list[dict], collections.Counter]:
    path, name, w, seconds, report, out_dir = job
    rec = _rec(path, report)
    fs = rec.fs
    a = int(w * seconds * fs)
    b = a + int(seconds * fs)
    tally: collections.Counter = collections.Counter()
    if b > rec.n:
        return [], tally
    _dc0, dc_true = rec.dc((a + b) / 2 / fs)
    found = lines(A._chunk(rec.view, rec.scale, a, b), fs, dc_true, SEGMENTS)
    rows = []
    taken: list[tuple[float, float]] = []
    tally["lines"] += len(found)
    tally.update(ln["why"] for ln in found if ln["why"])
    steady = sorted((ln for ln in found if not ln["why"]), key=lambda x: -x["db"])
    # Every steady line's channel from one pass of the filter bank.
    ys = _channels(rec, a, b, [ln["line"] + 1500.0 for ln in steady]) if steady else []
    for ln, y in zip(steady, ys):
        line = ln["line"]
        centre = line + 1500.0
        v = voice_above(y, centre, line)
        if v is None:
            tally["no voice above"] += 1
            continue
        lo, hi = v["lo"], v["hi"]
        if lo - line < LABEL_GAP_HZ:
            tally["voice too near the line"] += 1
            continue
        if any(t_lo <= lo <= t_hi for t_lo, t_hi in taken):
            tally["second line under one voice"] += 1
            continue
        if _silent_with_line(y, lo - centre, hi - centre, ln["seg_db"]) >= SILENT_SEGS:
            tally["line outlives the voice"] += 1
            continue
        # Another line in the search range within RIVAL_DB of this one: two
        # candidates for the carrier, and the label cannot choose. Lines,
        # not bins: comparing with the loudest 0.25 Hz bin there, as first
        # written, compared a 10 dB line with the peaks of 2760 bins of
        # noise and with the voice's own lowest 40 Hz, and called nearly
        # every weak carrier contested. A rival is another peak that
        # passed LINE_DB and could be a carrier - steady, or riding a wider
        # signal; one that comes and goes or wanders is not.
        others = [o["db"] for o in found if o is not ln and o["why"] in ("", "on a wider signal")
                  and lo + SEARCH[0] <= o["line"] <= lo + SEARCH[1] and abs(o["line"] - line) > 8.0]
        rival = ln["db"] - max(others) if others else 99.0
        if rival < RIVAL_DB:
            tally["rival line"] += 1
            continue
        taken.append((lo, hi))
        tally["labelled"] += 1
        mid = 0.5 * (lo + hi)
        dials = {"mid": mid, "lowq": lo + 0.25 * (hi - lo), "c-180": lo - 480.0, "c+45": lo - 255.0}
        iqs = dict(zip(dials, _channels(rec, a, b, list(dials.values()))))
        busy = _busy(iqs["mid"], lo - mid, hi - mid)
        key = f"{name}-{w:04d}-{int(round(lo))}"
        np.savez(os.path.join(out_dir, key + ".npz"), **{k: v.astype(np.complex64) for k, v in iqs.items()})
        rows.append({"key": key, "rec": name, "w": w, "lo": lo, "hi": hi, "truth": line,
                     "line_db": ln["db"], "line": line, "dials": dials,
                     "abs_lo_khz": round((lo + dc_true - 10489e6) / 1e3, 2),
                     "abs_carrier_khz": round((line + dc_true - 10489e6) / 1e3, 3),
                     "seconds": seconds, "t_s": round(a / fs, 2), "busy_s": busy,
                     "gap_hz": round(lo - line, 1), "drift_hz": ln["drift"], "present": ln["present"],
                     "track_hz": ln["track_hz"], "seg_db": ln["seg_db"], "seg_s": SEG_S,
                     "rival_db": round(rival, 1), "shoulder_db": ln["shoulder_db"],
                     "width_hz": round(v["width"]), "swing_db": round(v["swing"], 1)})
    return rows, tally


def build(args) -> None:
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for path in args.recordings:
        rep = args.lnb.get(Path(path).name)
        rec = Rec(path, rep)
        name = args.names.get(Path(path).name, Path(path).stem[:24])
        nwin = int(rec.n // (args.seconds * rec.fs))
        jobs += [(path, name, w, args.seconds, rep, str(out)) for w in range(nwin)]
    rows, tally = [], collections.Counter()
    with _pool(args.jobs) as ex:
        for i, (r, t) in enumerate(ex.map(_window, jobs, chunksize=1)):
            rows += r
            tally += t
            if (i + 1) % 25 == 0:
                print(f"{i + 1}/{len(jobs)} windows, {len(rows)} labels", file=sys.stderr, flush=True)
    rows.sort(key=lambda r: r["key"])
    # Same carrier (within 300 Hz) in one recording: one station.
    sid = 0
    for name in sorted({r["rec"] for r in rows}):
        last: list[tuple[float, int]] = []
        for r in sorted((r for r in rows if r["rec"] == name), key=lambda r: r["abs_carrier_khz"]):
            if last and abs(r["abs_carrier_khz"] - last[-1][0]) * 1e3 <= 300.0:
                r["station"] = last[-1][1]
            else:
                sid += 1
                r["station"] = sid
            last.append((r["abs_carrier_khz"], r["station"]))
    (out / "index.json").write_text(json.dumps(rows, indent=0), encoding="utf-8")
    print(json.dumps({"windows": len(jobs), **tally, "stations": len({r["station"] for r in rows})}))


# ----------------------------------------------------------------- score
def _score_one(job):
    row, out_dir, gaps, spans = job
    z = np.load(os.path.join(out_dir, row["key"] + ".npz"))
    m = int(autotune.CAPTURE_SECONDS * RATE)
    b0 = int(row["busy_s"] * RATE)
    # Where the carrier was during the busy 4 s: the track's value for the
    # 4 s segment holding the capture's middle (the nearest one seen).
    tr = row.get("track_hz") or []
    seen = [(n, v) for n, v in enumerate(tr) if v is not None]
    at = (row["busy_s"] + autotune.CAPTURE_SECONDS / 2) / row.get("seg_s", 4.0)
    busy_truth = row["truth"] + (min(seen, key=lambda nv: abs(nv[0] + 0.5 - at))[1] if seen else 0.0)
    res = []
    # A worker scores many rows: "as is" must mean the checked-out value,
    # not whichever gap the previous row tried last.
    default_gap = getattr(autotune, "MIN_EDGE_GAP", None)
    try:
        for gap in gaps:
            if default_gap is not None:
                autotune.MIN_EDGE_GAP = default_gap if gap is None else gap
            for dial, d in row["dials"].items():
                if dial not in z.files:
                    continue
                iq = z[dial]
                for span, y in (("busy4", iq[b0:b0 + m]), ("whole", iq)):
                    if span not in spans:
                        continue
                    r = autotune.auto_tune(y, "usb")
                    truth = busy_truth if span == "busy4" else row["truth"]
                    res.append({"key": row["key"], "gap": gap, "dial": dial, "span": span, "ok": bool(r.ok),
                                "err": (d + r.offset - truth) if r.ok else None,
                                "why": "" if r.ok else r.why})
    finally:
        if default_gap is not None:
            autotune.MIN_EDGE_GAP = default_gap
    return res


def _reason(why: str) -> str:
    return why.split(" (")[0].split(":")[0].split(" - ")[0][:60]


def score(args) -> None:
    out = Path(args.outdir)
    rows = json.loads((out / "index.json").read_text(encoding="utf-8"))
    gaps = [None]
    if hasattr(autotune, "MIN_EDGE_GAP"):
        gaps += [float(g) for g in args.gaps.split(",")]
    else:
        print("this auto-tune has no MIN_EDGE_GAP: scoring it as it is only")
    default_gap = getattr(autotune, "MIN_EDGE_GAP", None)
    spans = tuple(x for x in args.spans.split(",") if x)
    with _pool(args.jobs) as ex:
        res = [r for rr in ex.map(_score_one, [(r, str(out), gaps, spans) for r in rows], chunksize=4) for r in rr]
    (out / args.results).write_text(json.dumps(res), encoding="utf-8")
    print(f"{len(rows)} labelled captures, {len({r['station'] for r in rows})} stations; "
          f"auto-tune MIN_EDGE_GAP as checked out: {default_gap}")
    for span in spans:
        for gap in gaps:
            sel = [r for r in res if r["span"] == span and r["gap"] == gap]
            ok = [r for r in sel if r["ok"]]
            right = sum(abs(r["err"]) <= TRUE_HZ for r in ok)
            wrong = [round(r["err"]) for r in ok if abs(r["err"]) > TRUE_HZ]
            g = "as is" if gap is None else f"gap {gap:.0f}"
            print(f"{span:5s} {g:8s}: {len(sel)} tries, {len(ok)} answered ({100 * len(ok) / max(1, len(sel)):.0f} %), "
                  f"{right} right (<= {TRUE_HZ:.0f} Hz), {len(wrong)} wrong {sorted(wrong)[:12]}")
            if gap is None:
                why = collections.Counter(_reason(r["why"]) for r in sel if not r["ok"])
                for k, v in why.most_common():
                    print(f"      {v:4d} x {k}")
    print("by dial (busy4, as is):")
    for dial in ("mid", "lowq", "c-180", "c+45"):
        sel = [r for r in res if r["span"] == "busy4" and r["gap"] is None and r["dial"] == dial]
        ok = [r for r in sel if r["ok"]]
        print(f"  {dial:6s} {len(ok)}/{len(sel)} answered, {sum(abs(r['err']) <= TRUE_HZ for r in ok)} right")


# --------------------------------------------------------------- inspect
def inspect(args) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = Path(args.outdir)
    rows = json.loads((out / "index.json").read_text(encoding="utf-8"))
    pick = np.random.default_rng(args.seed).choice(len(rows), min(args.n, len(rows)), replace=False)
    (out / "inspect").mkdir(exist_ok=True)
    for i in sorted(pick):
        r = rows[int(i)]
        y = np.load(out / (r["key"] + ".npz"))["c+45"]
        dial = r["dials"]["c+45"]
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [2, 1]})
        a1.specgram(y, NFFT=4096, Fs=RATE, Fc=0, noverlap=3072, cmap="viridis", scale="dB")
        a1.set_ylim(-900, 3200)
        a1.axhline(r["truth"] - dial, color="r", lw=0.6, ls="--")
        a1.axhline(r["lo"] - dial, color="w", lw=0.6, ls=":")
        a1.set_title(f"{r['key']}  label {r['abs_carrier_khz']:.3f} kHz  line {r['line_db']} dB  gap {r['gap_hz']} Hz  "
                     f"drift {r['drift_hz']}  present {r['present']}", fontsize=8)
        f = np.fft.fftshift(np.fft.fftfreq(1 << 16, 1 / RATE))
        P = np.mean([_spec(y[k * 48000:(k + 1) * 48000], 1 << 16) for k in range(len(y) // 48000)], axis=0)
        sel = (f > r["truth"] - dial - 500) & (f < r["truth"] - dial + 900)
        a2.plot(f[sel], 10 * np.log10(P[sel] + 1e-30), lw=0.6)
        a2.axvline(r["truth"] - dial, color="r", lw=0.6, ls="--")
        a2.set_xlabel("Hz from the c+45 dial")
        fig.tight_layout()
        fig.savefig(out / "inspect" / f"{r['key']}.png", dpi=80)
        plt.close(fig)
    print(f"{len(pick)} PNGs in {out / 'inspect'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tools/autotune_labels.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("outdir")
    b.add_argument("recordings", nargs="+")
    b.add_argument("--jobs", type=int, default=6)
    b.add_argument("--seconds", type=float, default=20.0)
    b.add_argument("--lnb", action="append", default=[],
                   help="FILE=report.json: a previous --analyse report of FILE, for its LNB history")
    b.add_argument("--name", action="append", default=[], help="FILE=short name for keys")
    s = sub.add_parser("score")
    s.add_argument("outdir")
    s.add_argument("--gaps", default="100,125,150")
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--results", default="scores.json")
    # The whole capture is 20 s against auto-tune's 4, and costs five times
    # as much: scoring both at four gaps on c3's 405 labels was heading for
    # nine hours on a loaded host. busy4 alone is what MIN_EDGE_GAP decides.
    s.add_argument("--spans", default="busy4,whole", help="busy4 (auto-tune's own 4 s), whole (the label's capture)")
    i = sub.add_parser("inspect")
    i.add_argument("outdir")
    i.add_argument("--n", type=int, default=30)
    i.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        args.names = dict(x.split("=", 1) for x in args.name)
        args.lnb = dict(x.split("=", 1) for x in args.lnb)
        build(args)
    elif args.cmd == "score":
        score(args)
    else:
        inspect(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
