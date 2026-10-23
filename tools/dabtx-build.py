#!/usr/bin/env python3
"""Build Radio's bundled DAB transmitter list (ohsradio/data/dabtx/, read by
ohsradio/dabtx.py; docs/SERVER-API.md "DAB (Radio)", "Transmitters heard").

    tools/dabtx-build.py [--src DIR] [--offline]

Made from Ofcom's "Technical parameters for broadcast radio transmitters",
DAB file (TxParamsDAB.csv, Open Government Licence v3.0), downloaded into
--src (default ~/build/dabtx-src) unless already there, through the same
builder Refresh uses; its licence notice is written beside it. Ireland has
no open list to add (ohsradio/dabtx.py says why).

Run it with network access when a release wants fresher data; commit only
the files it writes, never the download in --src.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ohsradio import dabtx  # noqa: E402
from ohsradio import localfreq as lf  # noqa: E402

LICENCE = ("Contains public sector information licensed under the Open Government Licence v3.0:\n"
           "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/\n"
           "Source: Ofcom, Technical parameters for broadcast radio transmitters, DAB\n"
           f"({dabtx.OFCOM_PAGE}).\n"
           "Converted by tools/dabtx-build.py: TII codes from hex to numbers, ERP to kW,\n"
           "rows with no TII or position left out.\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(Path.home() / "build" / "dabtx-src"))
    ap.add_argument("--offline", action="store_true", help="use only what is already in --src")
    a = ap.parse_args()
    src = Path(a.src)
    src.mkdir(parents=True, exist_ok=True)
    path = src / "txparamsdab.csv"
    if not path.exists():
        if a.offline:
            raise SystemExit(f"{path} is missing and --offline was given")
        path.write_bytes(lf.http_fetch(dabtx.OFCOM_URL, timeout=300))
    data = dabtx.build_ofcom(path.read_bytes(), time.strftime("%Y-%m-%d", time.gmtime()))
    out = dabtx.BUNDLED / dabtx.FILE
    dabtx.write_file(out, data)
    (dabtx.BUNDLED / (dabtx.FILE.split(".")[0] + ".LICENCE.txt")).write_text(LICENCE, encoding="utf-8")
    print(f"{out.name}: {len(data['rows'])} transmitters ({data['skipped']} rows without TII or position left out), "
          f"{out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
