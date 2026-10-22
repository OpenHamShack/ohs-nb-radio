#!/usr/bin/env python3
"""Vendor a dated Big CTY into ohscore/data, or check the one there.

    tools/cty-refresh.py YYYYMMDD    fetch AD1C's Big CTY of that date from
                                     country-files.com, put its cty.dat and
                                     copyright.txt into ohscore/data, and
                                     rewrite ohscore/data/cty-source.txt
    tools/cty-refresh.py --check     the files in ohscore/data against the pin
                                     (offline; the suite runs this)
    tools/cty-refresh.py --verify    --check, and fetch the pinned zip again
                                     and compare it and its members too

Why vendored rather than fetched at build time, as build-windows.ps1 and
build-macos.sh fetch their third-party parts: the file is small plain text
(340 KB), it goes into every package on every platform - the .deb as well,
which fetches nothing - and a build that needs country-files.com up is a
build that cannot be repeated from the release commit alone. The commit
itself is the record of which edition a release carried; the pin is how
anybody checks that copy is AD1C's, unmodified.

Why a release refreshes it by hand rather than the program updating it:
an edition goes out every few weeks, and a program that phones a third
party's website on its own would be a new kind of network traffic for
something an operator can do by dropping a newer cty.dat into the data
folder (ohscore/dxcc.py). Refresh before a release: find the newest Big
CTY on https://www.country-files.com/ ("Big CTY - <date>"), run this with
its date, and read what it prints - it shows the licence text if that
changed, which must then be re-read before the edition is shipped.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "ohscore" / "data"
PIN = DATA / "cty-source.txt"
URL = "https://www.country-files.com/bigcty/download/{y}/bigcty-{d}.zip"
# Vendored name -> the zip member it is. The notice is renamed so that it
# reads as cty.dat's beside it, and keeps the name the installers' licences/
# folders have always given it.
MEMBERS = {"cty.dat": "cty.dat", "cty.dat-copyright.txt": "copyright.txt"}


class PinError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pin(path: Path = PIN) -> tuple[tuple[str, str, str], dict[str, tuple[str, str]]]:
    """((zip name, sha256, url), {vendored name: (sha256, member)})."""
    zip_line, files = None, {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        f = [x.strip() for x in line.split("|")]
        if f[0] == "zip" and len(f) == 4:
            zip_line = (f[1], f[2], f[3])
        elif f[0] == "file" and len(f) == 4:
            files[f[1]] = (f[2], f[3])
        else:
            raise PinError(f"{path}:{n}: not a zip or file line")
    if zip_line is None or set(files) != set(MEMBERS):
        raise PinError(f"{path}: needs one zip line and a file line for each of {', '.join(MEMBERS)}")
    return zip_line, files


def check(data: Path = DATA, pin: Path = PIN) -> list[str]:
    """What is wrong with the vendored files; empty when they match the pin."""
    _, files = read_pin(pin)
    wrong = []
    for name, (want, _) in files.items():
        p = data / name
        if not p.is_file():
            wrong.append(f"{p}: missing")
        elif sha256(p.read_bytes()) != want:
            # The usual cause is git turning CRLF into LF: .gitattributes
            # marks both files -text so it never does.
            wrong.append(f"{p}: sha256 {sha256(p.read_bytes())}, the pin says {want}")
    return wrong


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "openhamshack cty-refresh"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def members(zdata: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zdata)) as z:
        names = {Path(n).name: n for n in z.namelist()}
        missing = [m for m in MEMBERS.values() if m not in names]
        if missing:
            raise PinError(f"the zip has no {', '.join(missing)}")
        return {mine: z.read(names[theirs]) for mine, theirs in MEMBERS.items()}


def verify() -> list[str]:
    (zname, zsha, url), files = read_pin()
    zdata = fetch(url)
    wrong = check()
    if sha256(zdata) != zsha:
        wrong.append(f"{url}: sha256 {sha256(zdata)}, the pin says {zsha}")
    for name, data in members(zdata).items():
        if sha256(data) != files[name][0]:
            wrong.append(f"{zname}:{MEMBERS[name]}: not the pinned {name}")
    return wrong


def refresh(date: str) -> None:
    if not re.fullmatch(r"20\d{6}", date):
        raise PinError(f"{date}: give the edition's date as YYYYMMDD")
    url = URL.format(y=date[:4], d=date)
    zdata = fetch(url)
    got = members(zdata)
    old_notice = (DATA / "cty.dat-copyright.txt").read_bytes() if (DATA / "cty.dat-copyright.txt").is_file() else b""
    DATA.mkdir(parents=True, exist_ok=True)
    for name, data in got.items():
        (DATA / name).write_bytes(data)
    head = []
    for line in PIN.read_text(encoding="utf-8").splitlines() if PIN.is_file() else []:
        if line.strip() and not line.startswith("#"):
            break
        head.append(line)
    rows = [f"zip  | bigcty-{date}.zip | {sha256(zdata)} | {url}"]
    rows += [f"file | {name} | {sha256(data)} | {MEMBERS[name]}" for name, data in got.items()]
    PIN.write_text("\n".join(head + rows) + "\n", encoding="utf-8")
    print(f"vendored Big CTY {date} into {DATA} and pinned it in {PIN}")
    # The notice's first line names the edition's date, so it differs on
    # every refresh; anything after it is the licence itself.
    if old_notice.splitlines()[1:] != got["cty.dat-copyright.txt"].splitlines()[1:]:
        print("\nTHE LICENCE TEXT HAS CHANGED - read it before shipping this edition:\n")
        print(got["cty.dat-copyright.txt"].decode("utf-8", "replace"))


def main(argv: list[str]) -> int:
    try:
        if argv == ["--check"]:
            wrong = check()
        elif argv == ["--verify"]:
            wrong = verify()
        elif len(argv) == 1 and not argv[0].startswith("-"):
            refresh(argv[0])
            wrong = check()
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except PinError as e:
        print(f"cty-refresh: {e}", file=sys.stderr)
        return 1
    for w in wrong:
        print(f"cty-refresh: {w}", file=sys.stderr)
    if not wrong:
        print("ohscore/data/cty.dat matches its pin")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
