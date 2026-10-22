#!/usr/bin/env python3
"""Run the band skimmer (ohsnb/dsp/skim.py) over IQ recordings, and score
what it lists against the labelled auto-tune corpora.

    tools/skimmer_eval.py run REC.sigmf-data OUT.jsonl [--start S] [--seconds S]
                              [--dc HZ] [--budget 0.05] [--every 5]
    tools/skimmer_eval.py score CORPUS/index.json OUT.jsonl [...] [--rec NAME=OUT.jsonl]
    tools/skimmer_eval.py summary OUT.jsonl

`run` feeds the recording through the engine's own filter bank (ohscore.dsp.
bank Analysis, as the receive thread does) into a Skimmer, exactly as
ohsnb/skimmer.py does live, but as fast as the CPU allows: the budget
charges CPU against signal seconds, so a run is the live behaviour at that
budget on this machine, only sooner. Every --every seconds of signal it
writes one JSON line: {"t": stream seconds, "entries": [...], "cpu",
"level", "looks_min", "credit"}. --dc is the downlink frequency of the
recording's DC (default: from its SigMF meta, the receive LO less rxCorr
if the meta has one); the corpora's frequencies are Hz from DC, so the
score converts back with the same number and an error in it cancels.

`score` takes a corpus (c3: tools/autotune_labels.py, its `t_s`, `seconds`,
`lo`, `hi`, `truth`; c1: 4 s windows `w`, truth by work/score.py's rule)
and, for every label, the skimmer's entries while that label's window was
on air: was the station listed (an entry overlapping the label's voice
band), as SSB with a measured dial, and was that dial within 10 Hz of the
label's leaked carrier. Stations are counted once each (the label's
`station`), by their best and worst listings.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohscore.dsp.bank import Analysis, Geometry  # noqa: E402
from ohsnb import bandplan  # noqa: E402
from ohsnb.dsp import skim  # noqa: E402

NEAR_HZ = 700.0
BLOCK_S = 0.05          # the receive thread's blocks are about this long


def meta_of(data: Path) -> dict:
    return json.loads(data.with_suffix(".sigmf-meta").read_text())


def dc_of(meta: dict) -> float:
    """The downlink the recording's DC would be with no LNB error: the
    SDR's LO plus the LNB's nominal 9750 MHz. The real downlink there is
    this less rxCorr (Radio._off)."""
    g = meta["global"]
    lo = (g.get("openhamshack:device") or {}).get("rxLo")
    if lo is None:                       # the hand-made recordings of 07/10: the capture's frequency
        lo = meta["captures"][0]["core:frequency"]
    return float(lo) + float(g.get("openhamshack:lnb_lo_hz") or 9_750_000_000.0)


class Corr:
    """rxCorr against time in the recording, from a beacon-lock track
    (tools/playback_lock_report.py's report.json "track", or analyse's):
    what the live receiver's beacon lock would have had at each moment."""

    def __init__(self, path: str | None, default: float = 0.0):
        self.t, self.c = np.zeros(1), np.array([default])
        if path:
            tr = [e for e in json.load(open(path))["track"] if e.get("rxCorr") is not None
                  and e.get("state", "locked") == "locked"]
            self.t = np.array([e["pos_s"] for e in tr])
            self.c = np.array([e["rxCorr"] for e in tr])

    def __call__(self, t: float) -> float:
        return float(np.interp(t, self.t, self.c))

    @classmethod
    def from_meta(cls, meta: dict, fs: float) -> "Corr | None":
        """The recording's own rxCorr track, if its meta carries one
        (ohscore.sigmf.Recorder writes `openhamshack:track` {"rxCorr": [[sample,
        Hz], ...]} since 0.1.2x). Without it a run over such a recording
        put every signal rxCorr (~31 kHz on 17/10/2026) too high: the
        skimmer then named the KG-STV signal "Data" and the AMSAT-DL slot
        an SSB voice."""
        tr = ((meta.get("global") or {}).get("openhamshack:track") or {}).get("rxCorr")
        if not tr:
            return None
        c = cls(None)
        c.t = np.array([float(s) / fs for s, _ in tr])
        c.c = np.array([float(v) for _, v in tr])
        return c


def run(args) -> None:
    data = Path(args.rec)
    meta = meta_of(data)
    fs = float(meta["global"]["core:sample_rate"])
    raw = np.memmap(data, np.int16, "r")
    n_all = len(raw) // 2
    dc = args.dc if args.dc is not None else dc_of(meta)
    corr = Corr(args.lock, args.corr)
    if not args.lock and args.corr == 0.0:
        corr = Corr.from_meta(meta, fs) or corr
    a = int(args.start * fs)
    b = n_all if args.seconds is None else min(n_all, a + int(args.seconds * fs))
    geo = Geometry(fs)
    an = Analysis(geo)
    sk = skim.Skimmer(geo, budget=args.budget, listen=args.listen)
    looks = open(str(args.out) + ".looks", "w")
    sk.on_look = lambda d: looks.write(json.dumps({**d, "dc": dc, "corr": round(corr(d["t"]), 2)}) + "\n")
    step = int(BLOCK_S * fs) // geo.L * geo.L or geo.L
    out = open(args.out, "w")
    next_t = args.every
    t_wall0, c0 = time.monotonic(), time.process_time()
    i = a
    while i < b:
        j = min(b, i + step)
        v = raw[2 * i:2 * j].astype(np.float32) * np.float32(1 / 32768.0)
        x = (v[0::2] + 1j * v[1::2]).astype(np.complex64)
        X, starts = an.push(x)
        if X.shape[0]:
            # Where DL_LO sits in the IQ, Hz from DC, with the rxCorr beacon
            # lock had then (Radio._off).
            sk.push(X, starts + a, bandplan.DL_LO - dc + corr(i / fs))
        i = j
        if sk.t - a / fs >= next_t:
            next_t += args.every
            out.write(json.dumps({"t": round(sk.t, 2), "dc": dc, "corr": round(corr(sk.t), 2),
                                  "entries": sk.entries(), "cpu": round(sk.cpu(), 4),
                                  "level": sk.level, "looks_min": sk.looks_per_minute(),
                                  "credit": round(sk.credit, 3), "gaps": sk.gaps}) + "\n")
            out.flush()
    out.close()
    wall, cpu = time.monotonic() - t_wall0, time.process_time() - c0
    print(f"{(b - a) / fs:.0f} s of signal in {wall:.0f} s wall, {cpu:.0f} s CPU (bank + skimmer); "
          f"dc {dc:.0f}")


def load_snaps(path) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def c1_truth(rows):
    """work/score.py's truth_of: a leaked carrier >= 12 dB seen again
    (within 3 Hz) in an adjacent window, 50-260 Hz under the band."""
    by = collections.defaultdict(list)
    for x in rows:
        by[(x["rec"], x["w"])].append(x)
    out = []
    for x in rows:
        if x["line_db"] < 12.0 or not (50.0 <= x["lo"] - x["line"] <= 260.0):
            continue
        if any(y["line_db"] >= 10.0 and abs(y["line"] - x["line"]) <= 3.0
               for dw in (-1, 1) for y in by[(x["rec"], x["w"] + dw)]):
            out.append(dict(x, t_s=x["w"] * 4.0, seconds=4.0, truth=x["line"]))
    return out


def score(args) -> None:
    rows = json.load(open(args.index))
    labels = rows if "t_s" in rows[0] else c1_truth(rows)
    recs = dict(r.split("=", 1) for r in args.rec)
    snaps = {name: load_snaps(p) for name, p in recs.items()}
    tally = collections.Counter()
    per_station: dict = collections.defaultdict(list)
    wrong_ex = []
    for x in labels:
        sn = snaps.get(x["rec"])
        if sn is None:
            continue
        t0, t1 = x["t_s"], x["t_s"] + x["seconds"]
        # The entries listed during the label's window (and up to `--late`
        # seconds after it: an answer takes one look).
        during = [s for s in sn if t0 <= s["t"] <= t1 + args.late]
        if not during:
            continue
        best = "missed"
        dial_err = None
        for s in during:
            # The label's carrier as a downlink, with the rxCorr of then.
            truth = s["dc"] + x["truth"] - s["corr"]
            lo = s["dc"] + x["lo"] - s["corr"]
            for e in s["entries"]:
                if e["kind"] in ("digital", "beacon"):
                    continue
                # This station's entry: its dial (or the carrier its band
                # suggests) near the label's carrier. One further off than
                # NEAR_HZ is the next station's: a voice starts 100-650 Hz
                # over its carrier and stations sit 2-3 kHz apart.
                guess = e["dial"] if e.get("dial") is not None else e["lo"] - 300.0
                if abs(guess - truth) > NEAR_HZ and abs(e["lo"] - lo) > NEAR_HZ:
                    continue
                dialled = e["exact"] or (args.once and e.get("measured") == "once")
                if e["kind"] == "ssb" and dialled and e["dial"] is not None and abs(e["dial"] - truth) <= NEAR_HZ:
                    err = e["dial"] - truth
                    if abs(err) <= 10.0:
                        best = "right"
                        dial_err = err
                    elif best != "right":
                        best = "wrong"
                        dial_err = err
                elif best == "missed":
                    best = "listed-no-dial" if e["kind"] in ("ssb", "signal") else f"listed-as-{e['kind']}"
        tally[best] += 1
        per_station[x.get("station", x["key"])].append(best)
        if best == "wrong":
            wrong_ex.append((x["key"], round(dial_err, 1)))
    print(f"labels scored: {sum(tally.values())}")
    for k, v in tally.most_common():
        print(f"  {k:24s} {v}")
    st = collections.Counter()
    for sid, outcomes in per_station.items():
        if "right" in outcomes:
            st["right at least once"] += 1
        if "wrong" in outcomes:
            st["wrong at least once"] += 1
        if all(o == "missed" for o in outcomes):
            st["never listed"] += 1
        if all(o not in ("right", "wrong") for o in outcomes) and not all(o == "missed" for o in outcomes):
            st["listed, never with a dial"] += 1
    print(f"stations: {len(per_station)}")
    for k, v in st.most_common():
        print(f"  {k:28s} {v}")
    if wrong_ex:
        print("wrong:", wrong_ex[:40])


def summary(args) -> None:
    sn = load_snaps(args.out)
    cpu = [s["cpu"] for s in sn]
    kinds = collections.Counter()
    exact = []
    for s in sn:
        for e in s["entries"]:
            kinds[e["kind"]] += 1
        exact.append(sum(1 for e in s["entries"] if e["kind"] == "ssb" and e["exact"]))
    n = len(sn)
    print(f"{n} snapshots; cpu mean {np.mean(cpu) * 100:.2f} % max {np.max(cpu) * 100:.2f} %; "
          f"levels {collections.Counter(s['level'] for s in sn)}; looks/min mean "
          f"{np.mean([s['looks_min'] for s in sn]):.1f}")
    print("entries per snapshot by kind:", {k: round(v / n, 1) for k, v in kinds.most_common()})
    print(f"SSB with a measured dial per snapshot: mean {np.mean(exact):.1f}, last {exact[-1]}")
    last = sn[-1]
    for e in last["entries"]:
        print(f"  {e['f'] / 1e6:.6f} {e['kind']:8s} {e['label']:32s} {'*' if e['exact'] else ' '} "
              f"w={e['hi'] - e['lo']:.0f} snr={e['snr']} {'' if e['active'] else 'quiet'} {e['why'][:60]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("rec")
    r.add_argument("out")
    r.add_argument("--start", type=float, default=0.0)
    r.add_argument("--seconds", type=float)
    r.add_argument("--dc", type=float, help="the downlink of DC with no LNB error (default: the meta's LO + 9750 MHz)")
    r.add_argument("--lock", help="a beacon-lock track (playback_lock_report.py's report.json) for rxCorr")
    r.add_argument("--corr", type=float, default=0.0,
                   help="a constant rxCorr, without --lock (default: the meta's own rxCorr track, if it has one)")
    r.add_argument("--budget", type=float, default=skim.BUDGET)
    r.add_argument("--every", type=float, default=5.0)
    r.add_argument("--listen", type=float, default=4.0, help="seconds a voice look may listen (4: auto-tune's "
                   "first look only; up to 12, autotune.Listener)")
    s = sub.add_parser("score")
    s.add_argument("index")
    s.add_argument("--rec", action="append", default=[], help="NAME=OUT.jsonl, the run of that recording")
    s.add_argument("--late", type=float, default=15.0)
    s.add_argument("--once", action="store_true", help="count a dial measured once (unconfirmed) as a dial too")
    m = sub.add_parser("summary")
    m.add_argument("out")
    a = p.parse_args()
    if a.cmd == "run":
        run(a)
    elif a.cmd == "score":
        score(a)
    else:
        summary(a)


if __name__ == "__main__":
    main()
