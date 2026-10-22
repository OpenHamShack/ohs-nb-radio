#!/usr/bin/env python3
"""release-all's website step, on the development VM, where the website's
repository and its live build are (release-all's site.sh runs it).

    site.py --release nb=V [--release ham=V] --platforms linux,windows,macos
            --files DIR --site REPO --live DIST --stage DIST [--source-root DIR]

What NB 0.1.22 / Radio 0.1.21 did by hand (site-release.py), and what
Packet Radio's site-downloads.py does for Packet:

1. data/downloads.json: ONLY the released slots of the released apps
   change (version, file name, size, SHA-256, url, source), matched by
   product, OS, kind and architecture. collect-downloads.py is not run:
   run plain it offers the newest build of every product it finds, and on
   13/10 would have moved six other products to unreleased builds.
2. The stage is a copy of the live dist: the superseded downloads and
   their .sha256 out, the new ones in (from --files, under their published
   names, each checked against its .sha256), downloads/SHA256SUMS
   rewritten from the data, then tools/build.py --dist <stage>.
3. The guard: everything that differs between the live dist and the stage
   must be a page that lists these downloads (the home page, the
   downloads page and each released app's page), SHA256SUMS, or an old or
   new download of this release. Anything else - another product's line,
   a page somebody changed and never published - stops it here.
4. tools/check-site.py --dist <stage> must pass.

Prints "remove: downloads/<old>" for each file publish-web.sh must delete
and "stage: <path>". Changes nothing but the stage and the site
repository's data/downloads.json (run it in a worktree).
"""
from __future__ import annotations

import argparse
import datetime as dt
import filecmp
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

PRODUCT = {"nb": ("qo100-nb", "QO-100-NB"), "ham": ("radio", "Radio")}
# platform -> (os, kind, arch, published suffix, signed)
SLOTS = {"linux": [("linux", "deb", "x86-64", "linux-x86_64.deb", None),
                   ("linux", "deb", "arm64", "linux-arm64.deb", None),
                   ("linux", "deb", "any", "linux-all.deb", None)],
         "windows": [("windows", "installer", "x86-64", "windows-x64.exe", True)],
         "macos": [("macos", "dmg", "arm64", "macos-arm64.dmg", None)]}


def die(msg: str) -> None:
    print(f"site: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def published_name(app: str, version: str, suffix: str) -> str:
    return f"OpenHamShack-{PRODUCT[app][1]}-{version}-{suffix}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="append", required=True, metavar="APP=VERSION")
    ap.add_argument("--platforms", required=True)
    ap.add_argument("--files", required=True, type=Path)
    ap.add_argument("--site", required=True, type=Path)
    ap.add_argument("--live", required=True, type=Path)
    ap.add_argument("--stage", required=True, type=Path)
    ap.add_argument("--source-root", default="~/build/nb-radio-release",
                    help="what downloads.json's source fields name (where the copies are kept)")
    ap.add_argument("--skip-build", action="store_true", help=argparse.SUPPRESS)  # the tests' site has no build.py
    a = ap.parse_args(argv)
    releases = dict(r.split("=", 1) for r in a.release)
    platforms = [p for p in a.platforms.split(",") if p]
    if a.stage.exists():
        die(f"{a.stage} already exists (a previous attempt?); look at it, delete it, run again")

    new = {}   # (product, os, kind, arch) -> (name, path, sha, signed)
    for app, ver in releases.items():
        for p in platforms:
            for os_name, kind, arch, suffix, signed in SLOTS[p]:
                name = published_name(app, ver, suffix)
                f = a.files / name
                if not f.is_file():
                    die(f"{name} is not in {a.files}")
                digest = sha256(f)
                if (a.files / f"{name}.sha256").read_text().split()[0] != digest:
                    die(f"{name} does not match its .sha256")
                new[(PRODUCT[app][0], os_name, kind, arch)] = (name, f, digest, signed)

    data_path = a.site / "data" / "downloads.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    old_names = []
    todo = dict(new)
    for e in data["artefacts"]:
        key = (e.get("product"), e.get("os"), e.get("kind"), e.get("arch"))
        if key not in todo:
            continue
        name, f, digest, signed = todo.pop(key)
        if e.get("filename") and e["filename"] != name:
            old_names.append(e["filename"])
        app = next(k for k, v in PRODUCT.items() if v[0] == key[0])
        sub = f"{a.source_root}/{app}" if key[1] != "macos" else f"~/build/beta-build/desktop/macos/{key[0].replace('qo100-', '')}"
        e.update(version=releases[app], status="available", filename=name, size=f.stat().st_size, sha256=digest,
                 url=f"downloads/{name}", source=f"{sub}/{name}")
        if signed is not None:
            e["signed"] = signed
    if todo:
        die(f"downloads.json has no entry for {sorted(todo)}; add the slot by hand first")
    data["generated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    shutil.copytree(a.live, a.stage, symlinks=True)
    dl = a.stage / "downloads"
    for old in old_names:
        for x in (old, f"{old}.sha256"):
            (dl / x).unlink(missing_ok=True)
    for name, f, digest, _signed in new.values():
        shutil.copy2(f, dl / name)
        (dl / name).chmod(0o644)
        (dl / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    (dl / "SHA256SUMS").write_text("".join(f"{e['sha256']}  {e['filename']}\n" for e in data["artefacts"]
                                           if e.get("status") == "available"))
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not a.skip_build:
        subprocess.run([sys.executable, str(a.site / "tools" / "build.py"), "--dist", str(a.stage)], check=True,
                       stdout=subprocess.DEVNULL)

    before, after = tree(a.live), tree(a.stage)
    changed = {p for p in before & after if not filecmp.cmp(a.live / p, a.stage / p, shallow=False)}
    gone, added = before - after, after - before
    allowed = {"index.html", "downloads/index.html", "downloads/SHA256SUMS"}
    allowed |= {f"apps/{PRODUCT[app][0]}/index.html" for app in releases}
    moved = {f"downloads/{n}{s}" for n in old_names for s in ("", ".sha256")}
    moved |= {f"downloads/{v[0]}{s}" for v in new.values() for s in ("", ".sha256")}
    unexpected = sorted((changed - allowed) | (gone - moved) | (added - moved))
    for p in sorted(changed | gone | added):
        print(f"  {'changed' if p in changed else 'removed' if p in gone else 'added'}: {p}")
    if unexpected:
        die("the stage differs from the live site in more than this release:\n  " + "\n  ".join(unexpected))
    if not a.skip_build:
        subprocess.run([sys.executable, str(a.site / "tools" / "check-site.py"), "--dist", str(a.stage)], check=True)
    for old in old_names:
        print(f"remove: downloads/{old}")
        print(f"remove: downloads/{old}.sha256")
    print(f"stage: {a.stage}")
    print("SITE PASS")


if __name__ == "__main__":
    main()
