"""The multimedia beacon (AMSAT-DL's HSmodem, docs/hsmodem-research.md),
decoded across a whole recording rather than only live: frames decoded
and lost per 10 minutes, MER over time, and what content actually came
out - bulletins, pictures, files - saved into the report's own folder.

New --mmb section of `python3 -m ohsnb --analyse`. Reuses ohsnb.beaconrx's
own channel settings (12 kHz, a 2.4 kHz cutoff: room either side of the
beacon's own +-1.44 kHz for the frequency search) and
ohscore.modes.hsmodem.BeaconReceiver - the live receiver's own class, fed
here directly from the file instead of a queue a worker thread drains -
rather than a second implementation of either. Nothing here decodes the
HSmodem waveform itself: that is ohsdigi's (rust/ohsdigi/src/hsmodem), as it
is live.

The live radio restarts the receiver's AFC on a rxCorr jump bigger than
beaconrx.RETUNE_HZ (a beacon-lock correction, not the small per-update
nudges the carrier loop already follows) - reproduced here the same way,
since an offline run across a multi-hour recording can cross exactly that
kind of jump (a relock after the beacon faded) and a receiver left
chasing the wrong frequency afterwards would silently under-report the
rest of the file."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ohscore.dsp.bank import Analysis, Channel, Geometry
from ohscore.modes import hsmodem

from . import bandplan
from .analyse import CHUNK_S, _capture_dc, _chunk, _rx_corr_at
from .beaconrx import CHANNEL_RATE, CUTOFF, RETUNE_HZ

DL = bandplan.BEACONS["mm"]["dl"]
BUCKET_S = 600.0     # the task's own "per 10 minutes"
CONTENT_KINDS = {"image", "bulletin", "file", "dx", "cw", "station"}


def mmb_report(view, scale: float, n: int, fs: float, caps: list, info: dict, rx_corr_est: float,
              beacon_hist: list[dict], out_dir, bucket_s: float = BUCKET_S) -> dict:
    """{"available", "why" (when not), "buckets": [{"t0","t1","ok","lost",
    "mer_db_avg","mer_db_min","mer_db_max"}], "content": [{"t","kind",
    "name","path","size_bytes","text"}], "frames_ok_total",
    "frames_lost_total"}. Files/pictures/bulletins are written to
    `out_dir`/mmbeacon/ by BeaconReceiver itself (its own `folder`
    argument), exactly as the live radio saves them - this module only
    reports what arrived, not how it is written to disk."""
    if not hsmodem.AVAILABLE:
        return {"available": False, "why": hsmodem.WHY_NOT, "buckets": [], "content": [],
               "frames_ok_total": 0, "frames_lost_total": 0}
    geo = Geometry(fs)
    d = geo.decimation_for(CHANNEL_RATE)
    ch = Channel(geo, d, cutoff=CUTOFF)
    analysis = Analysis(geo)
    total_s = n / fs
    nbuck = max(1, int(math.ceil(total_s / bucket_s)))
    buckets = [{"t0": round(i * bucket_s, 1), "t1": round(min((i + 1) * bucket_s, total_s), 1),
               "ok": 0, "lost": 0, "_mer": []} for i in range(nbuck)]
    content: list[dict] = []
    state = {"last_ok": 0, "last_lost": 0, "t": 0.0}

    def _bucket_for(t: float) -> int:
        return min(nbuck - 1, int(t // bucket_s))

    def _emit(ev: dict) -> None:
        kind = ev.get("kind")
        b = buckets[_bucket_for(state["t"])]
        if kind == "stats":
            ok, lost = int(ev["ok"]), int(ev["failed"])
            b["ok"] += max(0, ok - state["last_ok"])
            b["lost"] += max(0, lost - state["last_lost"])
            state["last_ok"], state["last_lost"] = ok, lost
            if ev["sync"]:
                b["_mer"].append(float(ev["mer"]))
            return
        if kind not in CONTENT_KINDS:
            return
        ev = dict(ev)
        size = len(ev.get("data") or b"") if isinstance(ev.get("data"), (bytes, bytearray)) else None
        entry = {"t": round(state["t"], 1), "kind": kind, "name": ev.get("name") or ev.get("call") or "",
                "path": ev.get("path", ""), "size_bytes": size}
        if "text" in ev:
            entry["text"] = ev["text"]
        if kind == "dx":
            entry.update({k: ev.get(k) for k in ("reporter", "qrg_khz", "dxcall", "comment")})
        content.append(entry)

    rx = hsmodem.BeaconReceiver(ch.rate, _emit, Path(out_dir) / "mmbeacon")
    corr_ref = rx_corr_est
    cap_bounds = sorted({int(c.get("core:sample_start", 0)) for c in caps} | {0, n})
    step = int(CHUNK_S * fs)
    for seg_lo, seg_hi in zip(cap_bounds, cap_bounds[1:]):
        cap = next((c for c in caps if int(c.get("core:sample_start", 0)) == seg_lo), {})
        dc = _capture_dc(cap, info)
        if dc is None:
            continue
        for a in range(seg_lo, seg_hi, step):
            b_ = min(a + step, seg_hi)
            t_end = b_ / fs
            corr = _rx_corr_at(beacon_hist, t_end, rx_corr_est)
            if abs(corr - corr_ref) > RETUNE_HZ:
                corr_ref = corr
                rx.rx.reset()
            ch.set_freq(DL - (dc - corr))
            X, starts = analysis.push(_chunk(view, scale, a, b_))
            y = ch.take(X, starts)
            if not len(y):
                continue
            state["t"] = t_end
            rx.feed_iq(y, t=t_end)
    for bucket in buckets:
        mers = bucket.pop("_mer")
        bucket["mer_db_avg"] = round(float(np.mean(mers)), 1) if mers else None
        bucket["mer_db_min"] = round(float(np.min(mers)), 1) if mers else None
        bucket["mer_db_max"] = round(float(np.max(mers)), 1) if mers else None
    return {"available": True, "why": "", "buckets": buckets, "content": content,
           "frames_ok_total": state["last_ok"], "frames_lost_total": state["last_lost"]}
