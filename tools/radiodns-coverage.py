#!/usr/bin/env python3
"""How many of a station list's DAB services RadioDNS has logos for.

    tools/radiodns-coverage.py <bandscan/dab.json> [--keep DIR]

Runs Radio's own fetcher (ohsradio/radiodns.py) once, on the real internet,
against a scratch logo store (a temporary folder, or DIR to look at the
pictures afterwards), and prints one line per service and the totals. It
never touches a Radio's data folder. Get a box's list with, for example,
`ssh <box> sudo cat /var/lib/dock360/modules/shack-radio/data/bandscan/dab.json`.
"""
import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohscore.dabpics import DabPictures  # noqa: E402
from ohsradio import radiodns  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stations", type=Path)
    ap.add_argument("--keep", type=Path, help="keep the fetched logos in this folder")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ensembles = json.loads(a.stations.read_text())["ensembles"]
    with tempfile.TemporaryDirectory(prefix="radiodns-", dir=Path.home() / "build") as tmp:
        folder = a.keep or Path(tmp)
        pics = DabPictures(folder)
        f = radiodns.RadioDns(pics, lambda: ensembles, lambda: True)
        counts = f.run_once()
        services = {}
        for e in ensembles:
            for s in e["services"]:
                services.setdefault(s["sid"], (e["block"], e, s["label"]))
        with_logo = 0
        for sid, (block, e, label) in sorted(services.items(), key=lambda kv: (kv[1][0], kv[1][2])):
            have = [v for v in ("square", "wide") if v in pics.logos.get(sid, {})]
            with_logo += bool(have)
            name = radiodns.fqdn(sid, e["id"], e.get("ecc"), e.get("country"))
            print(f"{block:4} {e['id']} {sid:8} {label:20} {'+'.join(have) or '-':12} {name or '(no RadioDNS name)'}")
        print(f"\n{len(services)} services, {with_logo} with RadioDNS logos; run: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
