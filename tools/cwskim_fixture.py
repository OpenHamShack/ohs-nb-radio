#!/usr/bin/env python3
"""Record what Radio's CW skimmer sends, from an IQ recording, as a fixture
for clients: one JSON object per line, each a `cwskim` or `cwspot` item
exactly as GET api/events carries it ({"kind", ...item}), plus "at", its
time in seconds from the start of the fixture.

    tools/cwskim_fixture.py REC.sigmf-data OUT.txt [--start S] [--seconds S]
                            [--every 1] [--max 64] [--plan rsgb-2026]

Remote's fakeshack replays it (FAKESHACK_CWSKIM) and Remote's unit tests
read it (android/app/src/test/resources/shack/radio-events-cwskim.txt),
so a client is built and tested against a real band rather than a
simulator's tidy one. The source is the IQ library's ohs-box capture of
20 m CW (iqlib 20261013-ohs-box-20m-cwskimmer-200k: 200 kS/s round
14.050 MHz, which holds the whole 14.000-14.070 segment).

The skimmer is shack_cw.skim.Skimmer, the core ohsradio/cwskim.py's worker
runs, fed in 75 ms blocks as the receive thread hands them over, but in
stream time rather than wall time: the worker snapshots once a wall
second, which run faster than real time would leave the snapshots sparse.
Here a snapshot is taken every --every seconds of the recording, so the
fixture has the cadence a live server has. Each item is made by the same
code the server uses (CwSkim's _item for cwskim; cwspot numbered by its
own rev, the worker's rev stripped), with the country from ohscore.dxcc's
skim_lookup as the worker's is. Times are the recording's own (UTC).

Receive only: it reads a file and writes a file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohscore import dxcc, shacklibs  # noqa: E402
from ohsradio import plans  # noqa: E402
from ohsradio.cwskim import off_item, segment  # noqa: E402

BLOCK_S = 0.075


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rec", type=Path, help="the .sigmf-data file")
    ap.add_argument("out", type=Path)
    ap.add_argument("--start", type=float, default=0.0, help="seconds into the recording")
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--every", type=float, default=1.0, help="seconds between cwskim snapshots")
    ap.add_argument("--max", type=int, default=64, help="cwSkimMax")
    ap.add_argument("--plan", default="rsgb-2026", help="the band plan whose CW rows make the segment")
    a = ap.parse_args(argv)

    shacklibs.cw()
    from shack_cw.skim import Skimmer
    from shack_cw.skim.bench import load_sigmf

    z, rate, centre, t0 = load_sigmf(a.rec)
    i0 = int(a.start * rate)
    z = z[i0:i0 + int(a.seconds * rate)]
    t0 += a.start
    plan = plans.PLANS[a.plan]
    seg = segment(plan, centre)
    if seg is None:
        print(f"no CW segment at {centre / 1e6:.3f} MHz in {a.plan}", file=sys.stderr)
        return 2
    lo, hi, band = seg
    # What ohsradio/cwskim.py would cover: the segment, inside the recording's
    # usable span (the bank channel's 0.42 of its rate either side).
    clo, chi = max(lo, centre - 0.42 * rate + 3000.0), min(hi, centre + 0.42 * rate - 3000.0)
    where = {"band": band, "segment": {"lo": lo, "hi": hi, "plan": a.plan}, "cover": {"lo": clo, "hi": chi}}
    state = "partial" if clo > lo + 1 or chi < hi - 1 else "running"
    sk = Skimmer(rate, clo, chi, centre, max_channels=a.max, squelch_db=6.0, country=dxcc.skim_lookup(None),
                 band=band, pitch=700.0)
    blk = int(round(BLOCK_S * rate))
    rev = 0
    next_snap = a.every
    counts = {"cwskim": 0, "cwspot": 0}
    with a.out.open("w") as f:
        def put(kind, item, t):
            counts[kind] += 1
            f.write(json.dumps({"kind": kind, "at": round(t - t0, 3), **item}, separators=(",", ":")) + "\n")
        for i in range(0, len(z), blk):
            t = t0 + i / rate
            for sp in sk.feed(z[i:i + blk], t=t, centre=centre, generation=0):
                rev += 1
                put("cwspot", {"t": round(t, 3), "rev": rev, "spot": {k: v for k, v in sp.items() if k != "rev"}}, t)
            if (i + blk) / rate >= next_snap:
                next_snap += a.every
                snap = sk.snapshot()
                item = dict(off_item(), **where, channels=snap["channels"], carriers=snap["carriers"])
                item.update(t=round(t, 3), state=state, spotsRev=rev)
                put("cwskim", item, t)
    print(f"{a.out}: {counts['cwskim']} cwskim, {counts['cwspot']} cwspot over {len(z) / rate:.0f} s "
          f"({band} {lo / 1e6:.3f}-{hi / 1e6:.3f} MHz, {state})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
