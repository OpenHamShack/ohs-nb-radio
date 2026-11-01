#!/usr/bin/env python3
"""Build Radio's bundled port names (ohsradio/data/ships/locode.json.gz,
read by ohsradio/shipdata.py; docs/SERVER-API.md "AIS", "Flag and port").

    tools/ships-data-build.py [--src DIR] [--offline]

Made from the UN/LOCODE code list as UNECE keeps it in its own repository,
https://opensource.unicc.org/un/unece/uncefact/vocab-locode (one CSV per
country under locodes/, GPL-3.0 like Radio), downloaded into --src (default
~/build/locode-src) unless already there. That source rather than the
better-known datasets/un-locode copy on GitHub: that copy's maintainers
could not settle the data's licence ("unclear", their README), while the
UN's own repository carries GPL-3.0 for all of it.

Only locations whose function says "port" (the first function digit is 1)
are kept, every country's, since an AIS destination may name any port in
the world and the whole list is ~150 kB compressed. Rows marked for
removal (X) or that are only references to another code (=) are left out.

Run it with network access when a release wants fresher data; commit only
the files it writes, never the download in --src.

The MID table beside it (mid.json) is not built: it is the ITU's table of
Maritime Identification Digits typed in by hand (mid.LICENCE.txt), since
the ITU's page refuses scripted clients.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ohsradio" / "data" / "ships"
PROJECT = "un%2Funece%2Funcefact%2Fvocab-locode"
API = f"https://opensource.unicc.org/api/v4/projects/{PROJECT}"
AGENT = "OpenHamShack-Radio tools/ships-data-build.py (+https://openhamshack.com/)"
LICENCE = ("Port names from UN/LOCODE, the United Nations Code for Trade and Transport\n"
           "Locations, maintained by UNECE, as published in UNECE's repository\n"
           "https://opensource.unicc.org/un/unece/uncefact/vocab-locode (locodes/*.csv,\n"
           "commit {sha}), which is licensed GPL-3.0.\n"
           "Converted by tools/ships-data-build.py: ports only (function 1), code to\n"
           "name; rows marked for removal (X) or reference entries (=) left out.\n")


def _get(url: str, timeout: float):
    # The host refuses urllib's own User-Agent (403).
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=timeout)


def download(src: Path) -> str:
    """The repository's newest locodes/ into `src`; its commit."""
    with _get(f"{API}/repository/commits?per_page=1", 30) as r:
        sha = json.load(r)[0]["id"]
    tgz = src / f"locodes-{sha}.tar.gz"
    if not tgz.exists():
        with _get(f"{API}/repository/archive.tar.gz?path=locodes&sha={sha}", 120) as r:
            tgz.write_bytes(r.read())
    with tarfile.open(tgz) as tf:
        tf.extractall(src / sha, filter="data")
    return sha


def build(folder: Path) -> dict[str, str]:
    ports: dict[str, str] = {}
    for f in sorted(folder.rglob("locodes/*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                # Change, Country, Location, Name, NameWoDiacritics,
                # Subdivision, Function, Status, Date, IATA, Coordinates, Remarks
                if len(row) < 7 or not row[2] or row[0] in ("X", "=") or row[6][:1] != "1":
                    continue
                code, name = (row[1] + row[2]).upper(), row[3].strip()
                if len(code) == 5 and name:
                    ports[code] = name
    return dict(sorted(ports.items()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(Path.home() / "build" / "locode-src"))
    ap.add_argument("--offline", action="store_true", help="use only what is already in --src")
    a = ap.parse_args()
    src = Path(a.src)
    src.mkdir(parents=True, exist_ok=True)
    if a.offline:
        done = sorted(p for p in src.iterdir() if p.is_dir())
        if not done:
            print(f"nothing in {src}", file=sys.stderr)
            return 1
        sha = done[-1].name
    else:
        sha = download(src)
    ports = build(src / sha)
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(ports, ensure_ascii=False, separators=(",", ":")).encode()
    # mtime 0: the same list gives the same bytes, so a rebuild with no
    # change in the data shows no change in git.
    (OUT / "locode.json.gz").write_bytes(gzip.compress(raw, 9, mtime=0))
    (OUT / "locode.LICENCE.txt").write_text(LICENCE.format(sha=sha))
    print(f"{len(ports)} ports from commit {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
