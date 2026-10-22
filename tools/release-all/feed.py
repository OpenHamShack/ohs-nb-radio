#!/usr/bin/env python3
"""release-all's update feed: written once per app, at the end, FROM THE
LIVE FEED, and checked before anything is uploaded.

    feed.py --app nb|ham --version V --releases DIR --live-url URL --out DIR
            [--platforms linux,windows,macos] [--rehearsal --key PATH]

tools/update-feed.py write takes the folder's own update.json as the
previous manifest: it keeps that manifest's entries for platforms this
release does not build, and moves `published` past it (clients refuse a
manifest older than one they have seen). Both are only right if the
folder's update.json IS what clients have seen - the one on
openhamshack.com. Before NB 0.1.19 the release host's copy was the only
copy and that held; since the one-platform releases (0.1.19-0.1.21:
.debs held back, the feed put back by hand) a folder's update.json can
differ from the live one, and a feed written from it could drop the live
Windows entry or come out older than the live one. So: the live feed is
fetched and its signature checked, and if the folder's differs it is
replaced by the live one before update-feed.py write runs. Then, before
the result may be uploaded: `published` later than the live feed's;
every platform released (--platforms) offers this version; every other
platform's entry exactly as live; no platform the live feed offers lost.

--rehearsal (release-all's dry run): the same, in a copy of the folder
under --out, signed with a throw-away key (--key; made if missing), so a
dry run proves the whole step without the release key signing anything
that could be uploaded. A dry run's version may be labelled (0.1.23+rc0);
the feed carries release numbers only, so the rehearsal names this
release's files under the plain version (0.1.23).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from ohscore import update  # noqa: E402

PKG = {"nb": "openhamshack-nb", "ham": "openhamshack-radio"}
SLOTS = {"linux": [("linux", "amd64"), ("linux", "arm64"), ("linux", "all")],
         "windows": [("windows", "amd64")], "macos": [("macos", "arm64")]}


def die(msg: str) -> None:
    print(f"feed: {msg}", file=sys.stderr)
    sys.exit(1)


def fetch(url: str) -> bytes:
    # A cache-buster on the web: the CDN in front of the site has served a
    # feed minutes stale before. (file: URLs, for the tests, take none.)
    if url.startswith("http"):
        url += f"?v={random.getrandbits(48):x}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "release-all"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def names(pkg: str, version: str, plat: str, arch: str) -> str:
    return {"linux": f"{pkg}_{version}_{arch}.deb", "windows": f"{pkg}-{version}-setup.exe",
            "macos": f"{pkg}-{version}-arm64.dmg"}[plat]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, choices=PKG)
    ap.add_argument("--version", required=True)
    ap.add_argument("--releases", required=True, type=Path)
    ap.add_argument("--live-url", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--platforms", default="linux,windows,macos")
    ap.add_argument("--rehearsal", action="store_true")
    ap.add_argument("--key", type=Path)
    a = ap.parse_args(argv)
    pkg = PKG[a.app]
    release = a.version.partition("+")[0]
    if release != a.version and not a.rehearsal:
        die(f"{a.version} is not a release version; only a rehearsal takes a label")
    wanted = [s for p in a.platforms.split(",") if p for s in SLOTS[p]]
    a.out.mkdir(parents=True, exist_ok=True)

    live_json = fetch(a.live_url)
    live_sig = fetch(a.live_url + ".sig")
    try:
        update.read_manifest(live_json, live_sig, pkg)
    except Exception as e:  # noqa: BLE001 - any refusal is a stop
        die(f"the live feed at {a.live_url} does not verify ({e}); not writing over it")
    live = json.loads(live_json)
    (a.out / "live-update.json").write_bytes(live_json)
    (a.out / "live-update.json.sig").write_bytes(live_sig)
    live_slots = {(e["platform"], e["arch"]): e for e in live.get("files", [])}
    print(f"live feed: published {live['published']}, "
          + ", ".join(f"{p}/{ar} {e['version']}" for (p, ar), e in sorted(live_slots.items())))

    if a.rehearsal:
        folder = a.out / "folder"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        # What the live feed names and this release does not replace, as
        # the release folder holds it (update-feed.py keeps an entry only
        # if its file is still there, unchanged).
        for slot, e in live_slots.items():
            if slot in wanted:
                continue
            for n in (e["url"], e["url"] + ".sha256"):
                if (a.releases / n).is_file():
                    shutil.copy2(a.releases / n, folder / n)
        for plat, arch in wanted:
            src = a.releases / names(pkg, a.version, plat, arch)
            if src.is_file():
                dst = folder / names(pkg, release, plat, arch)
                shutil.copy2(src, dst)
                shutil.copy2(src.with_name(src.name + ".sha256"), dst.with_name(dst.name + ".sha256"))
        key = a.key or a.out / "rehearsal.key"
        if not key.exists():
            subprocess.run([sys.executable, str(ROOT / "tools" / "update-feed.py"), "keygen", "--key", str(key)],
                           check=True, stdout=subprocess.DEVNULL)
        extra = ["--key", str(key), "--untrusted-ok"]
    else:
        folder = a.releases
        extra = []
    have = (folder / "update.json").read_bytes() if (folder / "update.json").is_file() else b""
    if have != live_json:
        if not a.rehearsal:
            print(f"{folder}/update.json is not the live feed; writing from the live one")
        (folder / "update.json").write_bytes(live_json)
        (folder / "update.json.sig").write_bytes(live_sig)

    res = subprocess.run([sys.executable, str(ROOT / "tools" / "update-feed.py"), "write", "--app", a.app,
                          "--releases", str(folder), "--version", release, *extra],
                         capture_output=True, text=True)
    print(res.stdout, end="")
    if res.returncode:
        die(f"update-feed.py write failed: {res.stderr.strip()}")

    new = json.loads((folder / "update.json").read_text())
    bad = []
    if not new["published"] > live["published"]:
        bad.append(f"published {new['published']} is not later than the live feed's {live['published']}")
    new_slots = {(e["platform"], e["arch"]): e for e in new.get("files", [])}
    for slot in wanted:
        got = new_slots.get(slot, {}).get("version")
        if got != release:
            bad.append(f"{slot[0]}/{slot[1]} offers {got or 'nothing'}, not {release}")
    for slot, e in live_slots.items():
        if slot in wanted:
            continue
        if new_slots.get(slot) != e:
            bad.append(f"{slot[0]}/{slot[1]} is not left as the live feed has it")
    for slot in set(new_slots) - set(live_slots) - set(wanted):
        bad.append(f"{slot[0]}/{slot[1]} appeared, though not released")
    if bad:
        die("the new feed is wrong; not to be uploaded:\n  " + "\n  ".join(bad))
    shutil.copy2(folder / "update.json", a.out / "update.json")
    shutil.copy2(folder / "update.json.sig", a.out / "update.json.sig")
    print(f"feed {a.app}: published {new['published']} (live {live['published']}); "
          + ", ".join(f"{p}/{ar} {e['version']}" for (p, ar), e in sorted(new_slots.items()))
          + (" [rehearsal: throw-away key]" if a.rehearsal else ""))
    print("FEED PASS")


if __name__ == "__main__":
    main()
