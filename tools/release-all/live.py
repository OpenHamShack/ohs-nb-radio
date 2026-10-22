#!/usr/bin/env python3
"""release-all's checks of openhamshack.com once publish.sh has uploaded
(promote-host.sh runs it on the release host; feedcheck.py and the curl
lines of the NB 0.1.19-0.1.22 releases, kept as one script).

    live.py --run <run dir on the release host> --platforms linux,windows,macos --app nb=V [--app ham=V]

For each app released: the live feed is byte for byte the one feed.py
wrote; ohscore.update's own check, as an installed copy runs it, offers the
new version to the version each released platform had before, and says
"current" at the new one; every released file downloads at the size and
SHA-256 the feed gives (the installer's Authenticode signature verified
as release.sh verifies it); every file the release removed answers 404.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from ohscore import update  # noqa: E402

FEED_APP = {"nb": "openhamshack-nb", "ham": "openhamshack-radio"}
BASE = {"nb": "https://openhamshack.com/desktop/nb/", "ham": "https://openhamshack.com/desktop/ham/"}
SOURCE = "https://openhamshack.com/source/"
SLOTS = {"linux": [("linux", "amd64"), ("linux", "arm64"), ("linux", "all")],
         "windows": [("windows", "amd64")], "macos": [("macos", "arm64")]}
PEM = ROOT / "packaging" / "windows" / "microsoft-identity-verification-root-2020.pem"


def get(url: str) -> bytes:
    req = urllib.request.Request(f"{url}?v={random.getrandbits(48):x}", headers={"Cache-Control": "no-cache",
                                                                                 "User-Agent": "release-all"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{url}?v={random.getrandbits(48):x}", method="HEAD"),
                                    timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--platforms", required=True)
    ap.add_argument("--app", action="append", required=True, metavar="APP=VERSION")
    a = ap.parse_args(argv)
    platforms = [p for p in a.platforms.split(",") if p]
    bad = []
    for app, _, ver in (x.partition("=") for x in a.app):
        feed_url = BASE[app] + "update.json"
        wrote = (a.run / f"feed-{app}" / "update.json").read_bytes()
        live = get(feed_url)
        if live != wrote:
            bad.append(f"{app}: the live feed is not the one written")
        before = json.loads((a.run / f"feed-{app}" / "live-update.json").read_text())
        old = {(e["platform"], e["arch"]): e["version"] for e in before["files"]}
        new = {(e["platform"], e["arch"]): e for e in json.loads(wrote)["files"]}
        for p in platforms:
            for plat, arch in SLOTS[p]:
                e = new[(plat, arch)]
                prev = old.get((plat, arch))
                if prev and prev != ver:
                    r = update.check(feed_url, FEED_APP[app], prev, plat=plat, arch=arch)
                    got = r.offer.entry.version if r.offer else None
                    print(f"{app} {plat}/{arch}: {prev} is offered {got} ({r.status})")
                    if got != ver:
                        bad.append(f"{app} {plat}/{arch}: {prev} is offered {got}, not {ver}")
                r = update.check(feed_url, FEED_APP[app], ver, plat=plat, arch=arch)
                print(f"{app} {plat}/{arch}: {ver} is {r.status}")
                if r.offer:
                    bad.append(f"{app} {plat}/{arch}: {ver} is still offered {r.offer.entry.version}")
                data = get(BASE[app] + e["url"])
                if len(data) != e["size"] or hashlib.sha256(data).hexdigest() != e["sha256"]:
                    bad.append(f"{app}: {e['url']} over HTTPS is not the file the feed names")
                else:
                    print(f"live {e['url']}: {e['size']} bytes, sha256 {e['sha256'][:12]} as the feed says")
                if plat == "windows":
                    with tempfile.NamedTemporaryFile(suffix=".exe") as f:
                        f.write(data)
                        f.flush()
                        r2 = subprocess.run(["osslsigncode", "verify", "-in", f.name, "-CAfile", str(PEM),
                                             "-TSA-CAfile", str(PEM), "-ignore-crl"], capture_output=True, text=True)
                    ok = r2.returncode == 0 and "Signature verification: ok" in r2.stdout
                    print(f"live {e['url']}: Authenticode {'verified' if ok else 'NOT verified'}")
                    if not ok:
                        bad.append(f"{app}: {e['url']}'s signature does not verify")
        for line in (a.run / f"remove-{app}.txt").read_text().splitlines():
            if line.strip():
                code = status(BASE[app] + line.strip())
                print(f"gone {line.strip()}: {code}")
                if code != 404:
                    bad.append(f"{app}: {line.strip()} still answers {code}")
    for line in (a.run / "remove-source.txt").read_text().splitlines():
        if line.strip():
            code = status(SOURCE + line.strip())
            if code != 404:
                bad.append(f"source: {line.strip()} still answers {code}")
    if bad:
        print("LIVE FAIL:\n  " + "\n  ".join(bad))
        sys.exit(1)
    print("LIVE PASS")


if __name__ == "__main__":
    main()
