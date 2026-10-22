#!/usr/bin/env python3
"""Replay auto-tune on real recordings: one attempt, or a sweep of many.

    tools/autotune_replay.py scan REC.sigmf-data [--from 10489.65 --to 10489.95]
                                  [--step 2] [--png OUT.png]
    tools/autotune_replay.py truth REC.sigmf-data --dial MHZ --t0 S --seconds S
                                  [--png OUT.png]
    tools/autotune_replay.py label REC.sigmf-data --dial MHZ [--dominance 1.2]
    tools/autotune_replay.py replay REC.sigmf-data --dial MHZ --t0 S [--mode usb]
    tools/autotune_replay.py sweep STATIONS.json [--offsets 100,250] [--every 4]
                                  [--jobs 4] [--out RESULTS.json] [--set NAME=VALUE]
    tools/autotune_replay.py corpus DIR [--dials mid,c-180] [--set NAME=VALUE]
    tools/autotune_replay.py excerpt REC.sigmf-data --dial MHZ --t0 S --seconds S
                                  OUT.npz

Brian's report on 17/10/2026 was that auto-tune "doesn't work a lot of
the time"; the log said only what it refused and why. This replays a
recording through the same measurement the engine runs, so any attempt
can be run again, on the same seconds at the same dial, and changed code
scored against it. Run it under a memory cap (systemd-run --user --scope
-p MemoryMax=4G): it holds little, but its workers are many.

- `scan` finds voices in a recording: per --step seconds, every occupied
  band 1.2-3.6 kHz wide, in kHz over 10489 MHz (true downlink). A PNG of
  the segment's spectrogram, for checking by eye, with --png (written by
  hand: there is no matplotlib on the hosts this runs on).
- `truth` measures a station's suppressed carrier from a long stretch of
  its speech: the pitch harmonics' vote (autotune.judge's landscape) over
  every voiced frame of --seconds, searched 600 Hz either way, and the
  same on each 20 s of it separately, plus any leaked carrier. Over a
  minute of speech the pitch has moved through so many values that only
  the true offset collects every frame's vote; a 4-12 s listen has far
  fewer, which is the whole difficulty. --png draws the voice demodulated
  at the answer.
- `label` does the same per over (a stretch of speech between pauses of
  more than 1.2 s): in a QSO each operator has a carrier of their own,
  tens of hertz from the other's. An over is a label only when one offset
  stands --dominance ahead of the next, both halves of the over agree to
  10 Hz, and the voice starts 40-650 Hz over the carrier found. On
  17/10/2026 two stations it labelled leaked their carrier, within 15 Hz of
  the label each time, and one QSO's two carriers came out within 20 Hz of
  the same in recordings ten minutes apart.
- `replay` runs autotune.listen() - the Listener, looking at 4 s and
  every second to 12 s, as the engine does on air - on the receive
  channel at --dial from --t0.
- `sweep` replays every station in STATIONS.json (a list of {"name",
  "rec", "spans": [[t0, t1, carrier_mhz], ...]}, from `label`) from dials
  --offsets either side of the carrier, a start every --every seconds
  through each over, and scores each: right (within TRUE_HZ), wrong, on
  another station, or refused (by reason, with how often its guesses were
  right). An answer barely depends on where it started (the spectrum
  places the voice first), so two offsets each way are enough.
- `corpus` scores a corpus of tools/autotune_labels.py (07/10/2026's c3:
  leaked carriers) the same way, with the Listener.
- `--set NAME=VALUE` changes an autotune constant for one run, in every
  worker, so the old behaviour can be scored against the new.
- `excerpt` saves the 12 kHz receive channel at --dial as 16-bit I/Q and
  a scale, for a regression test (tests/test_autotune_real.py): 12 s is
  about 560 kB.

The receive channel is cut as the engine cuts it (the analysis filter
bank and a Channel, as tools/autotune_labels.py does) at the dial's
position in the recording: IF = downlink - converter + rxCorr, with
rxCorr from the recording's own beacon-lock track (openhamshack:track) at the
middle of the window. The recording is a read-only memmap fed through the
filter bank 2 s at a time.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ohscore.dsp import autotune  # noqa: E402
from ohsnb import analyse as A  # noqa: E402

import autotune_labels as L  # noqa: E402

RATE = autotune.RATE
TRUE_HZ = 15.0     # an answer this close to the station's carrier is right: within the ear's tolerance
# An answer further than this from the label landed on some other voice
# (a label's capture often holds two): not this station a pitch off, and
# whether it is right there the label cannot say.
ELSEWHERE_HZ = 450.0


class Rec(L.Rec):
    """A recording, its rxCorr taken from its own beacon-lock track."""

    def __init__(self, data: str):
        super().__init__(data)
        meta = json.loads(L.sigmf.paths(Path(data))[1].read_text(encoding="utf-8"))
        track = meta["global"].get("openhamshack:track", {}).get("rxCorr") or []
        self.hist = [{"t": s / self.fs, "state": "locked", "rxCorr": float(v)} for s, v in track]

    def offset(self, dial_hz: float, t: float) -> float:
        """Where `dial_hz` (true downlink) is in the recording, Hz from DC, at t s."""
        return dial_hz - self.dc(t)[1]

    def channel(self, dial_hz: float, t0: float, seconds: float) -> np.ndarray:
        a = max(0, int(t0 * self.fs))
        b = min(self.n, a + int(seconds * self.fs))
        return L._channels(self, a, b, [self.offset(dial_hz, (a + b) / 2 / self.fs)])[0]

    def channels(self, dials_hz: list[float], t0: float, seconds: float) -> list[np.ndarray]:
        a = max(0, int(t0 * self.fs))
        b = min(self.n, a + int(seconds * self.fs))
        t = (a + b) / 2 / self.fs
        return L._channels(self, a, b, [self.offset(d, t) for d in dials_hz])

    @property
    def seconds(self) -> float:
        return self.n / self.fs


def write_png(img: np.ndarray, path: str, lo: float | None = None, hi: float | None = None,
              marks: tuple = ()) -> None:
    """A dB image (rows bottom to top) as a PNG, by hand: no matplotlib
    on the hosts this runs on. `marks` are column indices drawn red."""
    import struct
    import zlib
    lo = np.percentile(img, 20) if lo is None else lo
    hi = np.percentile(img, 99.5) if hi is None else hi
    v = np.clip((img - lo) / max(hi - lo, 1e-9), 0, 1)[::-1]
    rgb = np.stack([v ** 2.0, v ** 0.8, 0.35 + 0.4 * v - 0.3 * v ** 2], axis=-1)
    rgb = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    for c in marks:
        if 0 <= c < rgb.shape[1]:
            rgb[:, c] = (255, 0, 0)
    raw = b"".join(b"\x00" + row.tobytes() for row in rgb)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    hdr = struct.pack(">IIBBBBB", rgb.shape[1], rgb.shape[0], 8, 2, 0, 0, 0)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", hdr) + chunk(b"IDAT", zlib.compress(raw, 6))
                           + chunk(b"IEND", b""))


_RECS: dict[str, Rec] = {}


def apply_settings(pairs) -> None:
    """--set NAME=VALUE: an autotune module constant changed for this run
    (in every worker), to score a variant without editing the code."""
    for kv in pairs or ():
        k, v = kv.split("=", 1)
        old = getattr(autotune, k)
        setattr(autotune, k, type(old)(v) if not isinstance(old, bool) else v.lower() in ("1", "true", "yes"))



def rec_for(path: str) -> Rec:
    if path not in _RECS:
        _RECS[path] = Rec(path)
    return _RECS[path]


# ------------------------------------------------------------------- scan
def scan(args) -> None:
    rec = Rec(args.rec)
    lo, hi = args.lo * 1e6, args.hi * 1e6
    nfft = 1 << 14                       # 73 Hz bins at 1.2 MS/s
    step = int(args.step * rec.fs)
    rows, img = [], []
    for a in range(0, rec.n - step + 1, step):
        t = (a + step / 2) / rec.fs
        dc = rec.dc(t)[1]
        f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / rec.fs)) + dc
        P = np.zeros(nfft)
        k = 0
        for p in range(a, a + step - nfft + 1, nfft):
            x = A._chunk(rec.view, rec.scale, p, p + nfft) * np.hanning(nfft)
            P += np.fft.fftshift(np.abs(np.fft.fft(x)) ** 2)
            k += 1
        P /= max(k, 1)
        sel = (f >= lo) & (f <= hi)
        img.append(10 * np.log10(P[sel] + 1e-30))
        fs_, Ps = f[sel], P[sel]
        floor = float(np.percentile(Ps, 20))
        for b_lo, b_hi in autotune.occupied(fs_ - fs_[0], Ps, floor, rise_db=3.0, bridge_hz=150.0):
            w = b_hi - b_lo
            if 1200.0 <= w <= 3600.0:
                inside = (fs_ - fs_[0] >= b_lo) & (fs_ - fs_[0] <= b_hi)
                rows.append({"t": round(t, 1), "lo_khz": round((fs_[0] + b_lo - 10489e6) / 1e3, 2),
                             "hi_khz": round((fs_[0] + b_hi - 10489e6) / 1e3, 2),
                             "db": round(10 * np.log10(Ps[inside].mean() / floor), 1)})
    for r in rows:
        print(json.dumps(r))
    if args.png:
        # 5 columns per kHz is too few to see a voice; keep the 73 Hz bins.
        m = min(len(r) for r in img)       # rxCorr's drift moves the edges a bin
        write_png(np.array([r[:m] for r in img]), args.png)
        print(f"PNG {args.png}: {len(img)} rows of {args.step:g} s, {len(img[0])} bins of "
              f"{rec.fs / nfft:.0f} Hz from {args.lo} MHz", file=sys.stderr)


# ------------------------------------------------------------------ truth
def _frames(iq: np.ndarray, top: float = 2800.0):
    """Per-frame pitch data (autotune._pitches) of the capture, demodulated
    at its own 0 Hz (the dial)."""
    band, fb = autotune._bins(top, RATE)
    X, env = autotune._ripple(autotune._demod(iq, 0.0, "usb", RATE), band, fb)
    C = autotune._comb_frames(X, env, np.percentile(env, 25, axis=0), autotune._combs(fb))
    return autotune._pitches(C)


def landscape(h, k, c, d: np.ndarray) -> np.ndarray:
    """autotune.judge's vote over offsets d (Hz above the demodulation
    carrier) from every voiced frame."""
    voiced = h >= autotune.VOICED
    if voiced.sum() < autotune.MIN_VOICED:
        return np.zeros(len(d))
    f0 = autotune._F0[k[voiced]]
    cv = c[:, voiced]
    ph = np.exp(2j * np.pi * np.outer(1.0 / f0, d))
    w = np.asarray(autotune.RAHMONICS)
    vote = sum(a * np.real(cv[m][:, None] * ph ** (m + 1)) for m, a in enumerate(autotune.RAHMONICS)) / w.sum()
    hv = h[voiced]
    wt = np.maximum(hv - autotune.NOISE_FIT, 0.0)
    return (vote * wt[:, None]).sum(axis=0) / max(float(np.sum(wt * hv)), 1e-30)


def _peaks(d, t, n=3, sep=25.0):
    out, t = [], t.copy()
    for _ in range(n):
        i = int(np.argmax(t))
        out.append((float(d[i]), float(t[i])))
        t[np.abs(d - d[i]) <= sep] = -np.inf
    return out


def truth(args) -> None:
    rec = Rec(args.rec)
    dial = args.dial * 1e6
    d = np.arange(-600.0, 600.25, 0.5)
    chunk = 20.0
    whole_h, whole_k, whole_c = [], [], []
    print(f"dial {args.dial:.6f} MHz, {args.t0:.0f}-{args.t0 + args.seconds:.0f} s")
    t = args.t0
    while t < args.t0 + args.seconds - 2.0:
        sec = min(chunk, args.t0 + args.seconds - t)
        y = rec.channel(dial, t, sec)
        h, k, c = _frames(y)
        whole_h.append(h)
        whole_k.append(k)
        whole_c.append(c)
        tot = landscape(h, k, c, d)
        v = int((h >= autotune.VOICED).sum())
        pk = _peaks(d, tot)
        line = autotune.leaked_carrier(y, -600.0, 300.0)
        print(f"  {t:6.1f}+{sec:.0f}s voiced {v:4d}: " + ", ".join(f"{p:+7.1f} ({s:.2f})" for p, s in pk)
              + (f"  line {line[0]:+.1f} Hz {line[1]:.0f} dB" if line else ""))
        t += chunk
    h, k, c = (np.concatenate(whole_h), np.concatenate(whole_k), np.concatenate(whole_c, axis=1))
    tot = landscape(h, k, c, d)
    pk = _peaks(d, tot, 4)
    print("  all: " + ", ".join(f"{p:+7.1f} ({s:.3f})" for p, s in pk)
          + f"  -> carrier {(dial + pk[0][0]) / 1e6:.6f} MHz")
    if args.png:
        # The voice demodulated at the answer, -300..+1500 Hz, 30 s.
        y = rec.channel(dial + pk[0][0], args.t0, min(args.seconds, 30.0))
        n, hop = 4096, 1024
        fr = np.lib.stride_tricks.sliding_window_view(y, n)[::hop] * np.hanning(n)
        S = np.fft.fftshift(np.abs(np.fft.fft(fr, axis=1)) ** 2, axes=1)
        f = np.fft.fftshift(np.fft.fftfreq(n, 1 / RATE))
        sel = (f >= -300) & (f <= 1500)
        img = 10 * np.log10(S[:, sel] + 1e-30).T          # rows: frequency, bottom up
        write_png(np.repeat(img, 2, axis=1), args.png, marks=())
        row0 = int(np.argmin(np.abs(f[sel])))
        print(f"PNG {args.png}: rows -300..+1500 Hz ({RATE / n:.1f} Hz), 0 Hz at row {row0} "
              f"from the bottom", file=sys.stderr)


def _overs(y: np.ndarray, lo: float, hi: float, gap_s: float = 1.2,
           least_s: float = 8.0) -> list[tuple[float, float]]:
    """Stretches of speech in [lo, hi] Hz of the channel `y`: 85 ms frames
    whose power stands 6 dB over the quietest tenth, joined across pauses
    shorter than gap_s; kept if least_s long. An over ends where its
    operator lets go: the pause between overs is the longest silence in a
    QSO, and a new operator may be tens of hertz from the last."""
    n = 1024
    m = len(y) // n
    x = y[:m * n].reshape(m, n) * np.hanning(n)
    S = np.abs(np.fft.fft(x, axis=1)) ** 2
    f = np.fft.fftfreq(n, 1 / RATE)
    pw = S[:, (f >= lo) & (f <= hi)].sum(axis=1)
    on = pw > np.percentile(pw, 10) * 10 ** 0.6
    out, start, last = [], None, None
    for i, v in enumerate(on):
        t = i * n / RATE
        if v:
            if start is None or t - last > gap_s:
                if start is not None and last - start >= least_s:
                    out.append((start, last))
                start = t
            last = t
    if start is not None and last - start >= least_s:
        out.append((start, last))
    return out


def label(args) -> None:
    """Per over of one station: its carrier from that over's speech alone,
    kept only when one offset stands clearly ahead (DOMINANCE over the
    next more than 25 Hz away) and both halves of the over say the same."""
    rec = Rec(args.rec)
    dial = args.dial * 1e6
    t1 = min(rec.seconds, args.t0 + args.seconds)
    y = rec.channel(dial, args.t0, t1 - args.t0)
    d = np.arange(-600.0, 600.25, 0.5)
    # Frames 30 s at a time (a 5 min recording at once is gigabytes of
    # spectra); a piece starts where the last one's frames stopped.
    hs, ks, cs = [], [], []
    step = int(30 * RATE) // autotune.HOP * autotune.HOP
    for p in range(0, len(y), step):
        piece = y[p:p + step + autotune.FRAME - autotune.HOP]
        if len(piece) >= autotune.FRAME:
            h_, k_, c_ = _frames(piece)
            hs.append(h_[:step // autotune.HOP])
            ks.append(k_[:step // autotune.HOP])
            cs.append(c_[:, :step // autotune.HOP])
    h, k, c = np.concatenate(hs), np.concatenate(ks), np.concatenate(cs, axis=1)
    rows = []
    for a, b in _overs(y, 150.0, 2700.0):
        fa, fb = int(a * RATE / autotune.HOP), int(b * RATE / autotune.HOP)
        sel = slice(fa, fb)
        tot = landscape(h[sel], k[sel], c[:, sel], d)
        pk = _peaks(d, tot, 2)
        mid = (fa + fb) // 2
        h1 = _peaks(d, landscape(h[fa:mid], k[fa:mid], c[:, fa:mid], d), 1)[0][0]
        h2 = _peaks(d, landscape(h[mid:fb], k[mid:fb], c[:, mid:fb], d), 1)[0][0]
        dom = pk[0][1] / max(pk[1][1], 1e-9)
        # The voice must start over the carrier found (USB passes nothing
        # at its carrier): the over's own edge, measured at that carrier.
        yo = y[int(a * RATE):int(b * RATE)]
        c0, _band, _w = autotune.coarse(yo * np.exp(-2j * np.pi * pk[0][0] * np.arange(len(yo)) / RATE), "usb")
        gap = None if c0 is None else round(c0 + autotune.LOW_CUT)
        ok = (dom >= args.dominance and abs(h1 - pk[0][0]) <= 10 and abs(h2 - pk[0][0]) <= 10
              and gap is not None and 40 <= gap <= 650)
        row = {"gap": gap, "t0": round(args.t0 + a, 1), "t1": round(args.t0 + b, 1),
               "carrier_mhz": round((dial + pk[0][0]) / 1e6, 6),
               "score": round(pk[0][1], 3), "dominance": round(dom, 2), "halves": [h1, h2], "next": pk[1][0],
               "ok": bool(ok)}
        rows.append(row)
        print(json.dumps(row))


# ----------------------------------------------------------------- replay
def replay_one(rec: Rec, dial_hz: float, t0: float, mode: str = "usb", y: np.ndarray | None = None) -> dict:
    if y is None:
        y = rec.channel(dial_hz, t0, autotune.LISTEN_SECONDS)
    r = autotune.listen(y, mode)
    det = r.details or {}
    return {"ok": bool(r.ok), "offset": round(r.offset, 1) if r.ok else None,
            "carrier_mhz": round((dial_hz + r.offset) / 1e6, 6) if r.ok else None,
            "why": r.why, "heard": det.get("heard"), "voiced": r.voiced, "pitch": round(r.pitch),
            "coarse": None if r.coarse is None else round(r.coarse), "how": det.get("how", ""),
            "guess": det.get("guess"), "guesses": det.get("guesses") if not r.ok else None,
            "alt": det.get("alt") if r.ok else None, "rival": round(r.rival, 3), "near_rival": det.get("near_rival"),
            "near": bool(det.get("near_answer"))}


def replay(args) -> None:
    rec = Rec(args.rec)
    out = replay_one(rec, args.dial * 1e6, args.t0, args.mode)
    print(json.dumps(out))


# ------------------------------------------------------------------ sweep
def _sweep_job(job):
    st, t0, offsets, carrier = job
    rec = rec_for(st["rec"])
    dials = [carrier + o for o in offsets]
    ys = rec.channels(dials, t0, autotune.LISTEN_SECONDS)
    res = []
    for o, d, y in zip(offsets, dials, ys):
        r = replay_one(rec, d, t0, "usb", y)
        err = None if not r["ok"] else d + r["offset"] - carrier
        g = r.get("guess")
        res.append({"station": st["name"], "t0": t0, "start": o, "ok": r["ok"], "err": err, "why": r["why"],
                    "guesses_err": [d + x - carrier for x in r["guesses"] or []],
                    "alt_err": None if r["alt"] is None else d + r["alt"] - carrier,
                    "heard": r["heard"], "rival": r["rival"], "near_rival": r["near_rival"], "near": r["near"],
                    "guess_err": None if not g else d + g - carrier})
    return res


def reason(why: str) -> str:
    import re
    w = re.sub(r"[+-]?\d+", "#", why.replace("after 12 s, ", ""))
    return w.split(" (")[0].split(":")[0].split(" - ")[0][:58]


def summarise(res: list[dict], label: str = "") -> dict:
    ok = [r for r in res if r["ok"]]
    right = [r for r in ok if abs(r["err"]) <= TRUE_HZ]
    wrong = [r for r in ok if TRUE_HZ < abs(r["err"]) <= ELSEWHERE_HZ]
    away = [r for r in ok if abs(r["err"]) > ELSEWHERE_HZ]
    g = [r for r in res if not r["ok"] and r.get("guess_err") is not None]
    g_right = sum(abs(r["guess_err"]) <= TRUE_HZ for r in g)
    g_any = sum(any(abs(e) <= TRUE_HZ for e in r.get("guesses_err") or []) for r in g)
    alt_fix = sum(r.get("alt_err") is not None and abs(r["alt_err"]) <= TRUE_HZ for r in wrong)
    print(f"{label}{len(res)} tries: {len(right)} right ({100 * len(right) / max(1, len(res)):.0f} %), "
          f"{len(wrong)} wrong {sorted(round(r['err']) for r in wrong)[:16]}"
          + (f" (the next best fit right in {alt_fix})" if wrong else "") + ", "
          + (f"{len(away)} on another station {sorted(round(r['err']) for r in away)[:8]}, " if away else "")
          + f"{len(res) - len(ok)} refused"
          + (f" ({len(g)} with a guess offered: the first right in {g_right}, one of two in {g_any})"
                                                  if g else ""))
    why = collections.Counter(reason(r["why"]) for r in res if not r["ok"])
    for k, v in why.most_common():
        print(f"      {v:4d} x {k}")
    return {"tries": len(res), "right": len(right), "wrong": len(wrong), "away": len(away),
            "refused": len(res) - len(ok)}


def sweep(args) -> None:
    stations = json.loads(Path(args.stations).read_text(encoding="utf-8"))
    offsets = [float(x) for x in args.offsets.split(",")]
    offsets = sorted({o for x in offsets for o in (x, -x)})
    jobs = []
    for st in stations:
        if args.only and st["name"] not in args.only.split(","):
            continue
        for span in st["spans"]:
            # [t0, t1] at the station's carrier, or [t0, t1, carrier] for one
            # over: in a QSO each operator is on a carrier of their own.
            a, b = span[:2]
            carrier = (span[2] if len(span) > 2 else st["carrier_mhz"]) * 1e6
            t = a
            # A listen may run past the over's end (12 s is longer than many
            # overs) but starts with at least `least` seconds of it to hear.
            while t + min(autotune.LISTEN_SECONDS, args.least) <= b + 0.01:
                jobs.append((st, t, offsets, carrier))
                t += args.every
    print(f"{len(jobs)} windows x {len(offsets)} starts", file=sys.stderr)
    res = []
    apply_settings(args.set)
    ex = ProcessPoolExecutor(args.jobs, initializer=apply_settings, initargs=(args.set,)) if args.jobs > 1 else None
    it = ex.map(_sweep_job, jobs, chunksize=1) if ex else map(_sweep_job, jobs)
    for i, r in enumerate(it):
        res += r
        if (i + 1) % 10 == 0:
            print(f"{i + 1}/{len(jobs)}", file=sys.stderr, flush=True)
    if ex:
        ex.shutdown()
    if args.out:
        Path(args.out).write_text(json.dumps(res), encoding="utf-8")
    summarise(res, "all: ")
    for name in sorted({r["station"] for r in res}):
        summarise([r for r in res if r["station"] == name], f"  {name}: ")
    print("by start offset:")
    for o in offsets:
        sel = [r for r in res if r["start"] == o]
        ok = [r for r in sel if r["ok"]]
        print(f"  {o:+5.0f}: {sum(abs(r['err']) <= TRUE_HZ for r in ok)}/{len(sel)} right, "
              f"{sum(abs(r['err']) > TRUE_HZ for r in ok)} wrong")


# ----------------------------------------------------------------- corpus
def _corpus_one(job):
    row, out_dir, dials = job
    z = np.load(os.path.join(out_dir, row["key"] + ".npz"))
    n = int(autotune.LISTEN_SECONDS * RATE)
    # 12 s of the label's 20, starting a little before its busiest 4 s, so
    # the first look hears the voice as an operator pressing then would.
    b0 = int(max(0.0, min(row["busy_s"] - 1.0, row["seconds"] - autotune.LISTEN_SECONDS)) * RATE)
    res = []
    for dial, d in row["dials"].items():
        if dial not in z.files or dial not in dials:
            continue
        r = autotune.listen(z[dial][b0:b0 + n], "usb")
        g = (r.details or {}).get("guess")
        gs = (r.details or {}).get("guesses") if not r.ok else None
        alt = (r.details or {}).get("alt") if r.ok else None
        res.append({"guesses_err": [d + x - row["truth"] for x in gs or []],
                    "alt_err": None if alt is None else d + alt - row["truth"],
                    "station": f"{row['rec']}:{row['station']}", "key": row["key"], "start": dial, "ok": bool(r.ok),
                    "err": (d + r.offset - row["truth"]) if r.ok else None, "why": r.why,
                    "heard": (r.details or {}).get("heard"), "rival": round(r.rival, 3),
                    "near_rival": (r.details or {}).get("near_rival"),
                    "near": bool((r.details or {}).get("near_answer")),
                    "guess_err": None if not g else d + g - row["truth"]})
    return res


def corpus(args) -> None:
    """A labelled corpus of tools/autotune_labels.py (c1, c3: leaked
    carriers on 07/10/2026) scored with the Listener, as on air."""
    out = Path(args.dir)
    rows = json.loads((out / "index.json").read_text(encoding="utf-8"))
    if args.max_gap:
        rows = [r for r in rows if r.get("gap_hz", 0) <= args.max_gap]
    apply_settings(args.set)
    ex = ProcessPoolExecutor(args.jobs, initializer=apply_settings, initargs=(args.set,)) if args.jobs > 1 else None
    jobs = [(r, str(out), args.dials.split(",")) for r in rows]
    it = ex.map(_corpus_one, jobs, chunksize=2) if ex else map(_corpus_one, jobs)
    res = [x for rr in it for x in rr]
    if ex:
        ex.shutdown()
    if args.out:
        Path(args.out).write_text(json.dumps(res), encoding="utf-8")
    print(f"{out.name}: {len(rows)} labels, {len({r['station'] for r in res})} stations")
    summarise(res, "all: ")


# ---------------------------------------------------------------- excerpt
def excerpt(args) -> None:
    """The receive channel at --dial as 16-bit I/Q and a scale: half the
    size of complex64, and its quantisation 80 dB under the band's noise."""
    rec = Rec(args.rec)
    y = rec.channel(args.dial * 1e6, args.t0, args.seconds)
    scale = float(np.abs(np.concatenate([y.real, y.imag])).max()) / 32000.0
    q = np.round(np.stack([y.real, y.imag], axis=-1) / scale).astype(np.int16)
    np.savez_compressed(args.out, iq16=q, scale=scale, rate=RATE, dial_hz=args.dial * 1e6, t0=args.t0,
                        source=Path(args.rec).name)
    print(f"{args.out}: {len(y) / RATE:.1f} s, {os.path.getsize(args.out) / 1e3:.0f} kB")


def load_excerpt(path) -> tuple[np.ndarray, dict]:
    """An `excerpt` back as complex64, and its other fields."""
    z = np.load(path)
    y = (z["iq16"][:, 0] + 1j * z["iq16"][:, 1]).astype(np.complex64) * np.float32(z["scale"])
    return y, {k: z[k].item() for k in z.files if k not in ("iq16",)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tools/autotune_replay.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("rec")
    p.add_argument("--from", dest="lo", type=float, default=10489.60)
    p.add_argument("--to", dest="hi", type=float, default=10490.0)
    p.add_argument("--step", type=float, default=5.0)
    p.add_argument("--png")
    p = sub.add_parser("truth")
    p.add_argument("rec")
    p.add_argument("--dial", type=float, required=True, help="MHz, near the carrier")
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--png")
    p = sub.add_parser("label")
    p.add_argument("rec")
    p.add_argument("--dial", type=float, required=True, help="MHz, near the carrier")
    p.add_argument("--t0", type=float, default=0.0)
    p.add_argument("--seconds", type=float, default=1e9)
    p.add_argument("--dominance", type=float, default=1.4)
    p = sub.add_parser("replay")
    p.add_argument("rec")
    p.add_argument("--dial", type=float, required=True, help="MHz")
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--mode", default="usb")
    p = sub.add_parser("sweep")
    p.add_argument("stations")
    p.add_argument("--offsets", default="100,250")
    p.add_argument("--every", type=float, default=6.0)
    p.add_argument("--least", type=float, default=8.0)
    p.add_argument("--set", action="append")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--only", default="")
    p.add_argument("--out")
    p = sub.add_parser("corpus")
    p.add_argument("dir")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--max-gap", type=float, default=0.0)
    p.add_argument("--dials", default="mid,c-180")
    p.add_argument("--set", action="append")
    p.add_argument("--out")
    p = sub.add_parser("excerpt")
    p.add_argument("rec")
    p.add_argument("--dial", type=float, required=True)
    p.add_argument("--t0", type=float, required=True)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("out")
    args = ap.parse_args(argv)
    cmds = {"scan": scan, "truth": truth, "label": label, "replay": replay, "sweep": sweep, "corpus": corpus,
            "excerpt": excerpt}
    cmds[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
