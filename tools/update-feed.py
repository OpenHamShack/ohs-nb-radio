#!/usr/bin/env python3
"""Write, sign and check an OpenHamShack desktop app's update feed (docs/update-feed.md).

    tools/update-feed.py keygen  [--key PATH]
    tools/update-feed.py pubkey  [--key PATH]
    tools/update-feed.py write   [--app nb|ham] [--releases DIR] [--version V] [--notes TEXT]
                                 [--recommended] [--key PATH]
    tools/update-feed.py verify  [--app nb|ham] [--releases DIR]

keygen makes the release key: "360 Technology OpenHamShack release key", an
Ed25519 key pair, the private half at ~/.config/openhamshack-release/ed25519.key
(mode 0600, in a 0700 folder; $OHS_RELEASE_KEY, $OPENHAMSHACK_RELEASE_KEY or
--key name another place), never overwritten. It prints the line to add to RELEASE_KEYS in
ohscore/update.py - an app trusts only keys compiled into it - and nothing
else ever prints the private half. Back the file up offline: losing it
means every installed copy can only be updated by hand, once, to a release
that trusts a new key.

write makes <releases>/update.json from what is in the release folder and
signs it, as update.json.sig beside it. tools/release.sh runs it after the
.debs are built and again after --windows adds the installer. Every entry
is measured from the file itself (size, SHA-256), and must agree with the
.sha256 file release.sh wrote beside it. A platform this run did not build
keeps the previous manifest's entry, if that file is still in the folder
unchanged: the .debs of a new version go out a day before its Windows
installer, and Windows users must go on being offered the installer that
is there. The key must be one ohscore/update.py trusts, or every client
would refuse the result; --untrusted-ok skips that check, for the tests
alone. `published` only ever moves forward, because clients refuse a
manifest older than one they have accepted.

verify checks the folder as a client would: the signature against the keys
ohscore/update.py trusts, then every file's size and SHA-256.

The manifest and its signature must reach the public site LAST, after
every file they name: a client that sees the new manifest first would
fetch a file that is not there yet (and, finding it missing, say nothing
until the next day's check).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ohscore import update  # noqa: E402

KEY_NAME = "360 Technology OpenHamShack release key"
DEFAULT_KEY = Path.home() / ".config" / "openhamshack-release" / "ed25519.key"
# (package, python package, release folder, title). The feed's "app" is the
# package's own name: both installed apps' own update checkers (face.package)
# have asked for exactly these names since NB/HAM 0.1.21/0.1.22, so there is
# no older copy left to strand with a different one (docs/update-feed.md,
# "The app's name"). The release folders keep their own names: they are the
# release host's, and publish.sh maps them onto /desktop/nb and /desktop/ham.
APPS = {"nb": ("openhamshack-nb", "ohsnb", "/srv/openhamshack-nb-releases", "OpenHamShack QO-100 NB"),
        "ham": ("openhamshack-radio", "ohsradio", "/srv/openhamshack-ham-releases", "OpenHamShack Radio")}
DEB_ARCHES = ("amd64", "arm64", "all")


def die(msg: str) -> None:
    print(f"update-feed: {msg}", file=sys.stderr)
    sys.exit(1)


def key_path(a) -> Path:
    named = a.key or os.environ.get("OHS_RELEASE_KEY") or os.environ.get("OPENHAMSHACK_RELEASE_KEY")
    return Path(named).expanduser() if named else DEFAULT_KEY


def load_key(path: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except FileNotFoundError:
        die(f"no release key at {path} (tools/update-feed.py keygen makes one; docs/update-feed.md)")
    except ValueError as e:
        die(f"{path} is not a private key ({e})")
    if not isinstance(key, Ed25519PrivateKey):
        die(f"{path} is not an Ed25519 key")
    return key


def raw_public(key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def cmd_keygen(a) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    path = key_path(a)
    if path.exists():
        die(f"{path} already exists; a release key is never replaced by this tool (docs/update-feed.md, "
            "Key rotation)")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    # O_EXCL, 0600 from the first byte: never a moment when the file is
    # readable by anyone else, and never over a key that appeared meanwhile.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    pub = raw_public(key)
    print(f"made {path} (0600): {KEY_NAME}, key id {update.key_id(pub)}")
    print("add this line to RELEASE_KEYS in ohscore/update.py, commit, and release that before "
          "the first signed feed - an app trusts only keys compiled into it:")
    print(f'    ("{KEY_NAME} {dt.date.today().year}", "{pub.hex()}"),')
    print("then back the private key up offline.")


def cmd_pubkey(a) -> None:
    pub = raw_public(load_key(key_path(a)))
    trusted = update.key_id(pub) in update.trusted_keys()
    print(f"{update.key_id(pub)} {pub.hex()} ({'trusted' if trusted else 'NOT trusted'} by ohscore/update.py)")
    if not trusted:
        # release.sh's gate: a key the apps do not list signs nothing useful.
        die(f"{key_path(a)} is not in RELEASE_KEYS in ohscore/update.py; add the line keygen printed, "
            "commit, and release from that commit")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def measured(path: Path) -> tuple[int, str]:
    """(size, sha256) of a file, checked against its .sha256 sidecar when
    there is one - a copy damaged since release.sh wrote that stops here."""
    digest = sha256_of(path)
    side = path.with_name(path.name + ".sha256")
    if side.is_file():
        want = side.read_text(encoding="ascii").split()[0].lower()
        if want != digest:
            die(f"{path.name} does not match {side.name}")
    return path.stat().st_size, digest


def release_notes(app: str, version: str) -> str:
    """One line for the banner's "What's new", written for the people who
    will read it: docs/release-notes/<app>-<version>.txt, cut to fit.
    Without one the line is empty and the banner offers only its link to
    the site's notes. (Until 07/10 this joined the release's commit
    subjects, which are written for whoever reads the history - the first
    signed feed would have told every user about scrubbing a hosting API's
    name from source tarballs.)"""
    path = ROOT / "docs" / "release-notes" / f"{app}-{version}.txt"
    try:
        line = " ".join(path.read_text(encoding="utf-8").split())
    except OSError:
        return ""
    if len(line) > update.NOTES_MAX:
        line = line[:update.NOTES_MAX - 1].rsplit(" ", 1)[0] + "…"
    return line


def previous(folder: Path) -> dict:
    try:
        return json.loads((folder / "update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_write(a) -> None:
    pkg, pydir, default_out, _title = APPS[a.app]
    folder = Path(a.releases or os.environ.get("RELEASES") or default_out)
    version = a.version or (ROOT / pydir / "VERSION").read_text().strip()
    update.parse_version(version)
    key = load_key(key_path(a))
    pub = raw_public(key)
    kid = update.key_id(pub)
    if kid not in update.trusted_keys() and not a.untrusted_ok:
        die(f"the key at {key_path(a)} ({kid}) is not in RELEASE_KEYS in ohscore/update.py: every installed "
            "copy would refuse this feed. Add it there and release that first")
    old = previous(folder)
    old_entries = {(e.get("platform"), e.get("arch")): e for e in old.get("files", []) if isinstance(e, dict)}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    notes = a.notes if a.notes is not None else None

    def entry(plat, arch, name):
        size, digest = measured(folder / name)
        was = old_entries.get((plat, arch), {})
        same = was.get("version") == version
        text = notes if notes is not None else (was.get("notes") if same and "notes" in was
                                                else release_notes(a.app, version))
        return {"platform": plat, "arch": arch, "kind": update.KINDS[plat], "version": version,
                "url": name, "size": size, "sha256": digest,
                "date": was.get("date") if same and was.get("date") else today, "notes": text or ""}

    files = []
    built = 0
    slots = [("linux", arch, f"{pkg}_{version}_{arch}.deb") for arch in DEB_ARCHES]
    slots.append(("windows", "amd64", f"{pkg}-{version}-setup.exe"))
    # The Mac .dmg (tools/build-macos.sh), arm64 only. release.sh does not
    # place one in the folder yet - the Mac build is unsigned and not
    # published - but a .dmg put there by hand is measured and offered
    # like the rest, and kept across later writes like the installer.
    slots.append(("macos", "arm64", f"{pkg}-{version}-arm64.dmg"))
    for plat, arch, name in slots:
        if (folder / name).is_file():
            files.append(entry(plat, arch, name))
            built += 1
            continue
        was = old_entries.get((plat, arch))
        if was and (folder / str(was.get("url", ""))).is_file():
            size, digest = measured(folder / was["url"])
            if (size, digest) != (was.get("size"), was.get("sha256")):
                die(f"{was['url']} is no longer the file the last manifest named")
            files.append(was)
            print(f"kept {plat} {arch}: {was['url']} ({was.get('version')}, from the last manifest)")
    if not built:
        die(f"nothing of {pkg} {version} is in {folder}")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    last = old.get("published", "")
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if last and stamp <= last:
        # Clients refuse a manifest older than the newest they have seen:
        # a second write within the same second must still move forward.
        stamp = (dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(seconds=1)
                 ).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"schema": update.SCHEMA, "app": pkg, "key": kid, "published": stamp}
    if a.recommended:
        doc["recommended"] = version
    # No notesUrl by default since 0.1.16. The feed's folder on
    # openhamshack.com (/desktop/<app>/) carries only the packages and the
    # feed. The product pages site-build.py writes beside them name people,
    # and the site publishes no personal name (BETA-PLAN decision 5), so
    # publish.sh leaves them behind. A link to index.html#notes would then
    # be a 404 in every banner. The field is optional (docs/update-feed.md):
    # the banner keeps its one-line notes and shows no "What's new" link. A
    # notesUrl must stay inside the feed's folder (ohscore/update.py refuses
    # "../"), so it cannot point at the website's downloads page instead.
    # --notes-url puts one back for a folder that does have the page.
    if a.notes_url:
        if not update._NOTES_URL.match(a.notes_url):
            die(f"--notes-url {a.notes_url!r} is not a page beside the feed (ohscore/update.py would refuse it)")
        doc["notesUrl"] = a.notes_url
    doc["files"] = files
    data = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    sig = key.sign(data)
    # Proved as a client would before it is written, with the same code.
    m = update.read_manifest(data, sig, pkg, keys=[(KEY_NAME, pub.hex())])
    tmp_json, tmp_sig = folder / "update.json.tmp", folder / "update.json.sig.tmp"
    tmp_json.write_bytes(data)
    tmp_sig.write_bytes(sig)
    os.replace(tmp_sig, folder / "update.json.sig")
    os.replace(tmp_json, folder / "update.json")
    for e in m.entries:
        print(f"  {e.platform:7s} {e.arch:5s} {e.version:8s} {e.url}  {e.size} bytes  sha256 {e.sha256[:12]}…")
    print(f"signed {folder / 'update.json'} with {kid}, published {stamp}"
          + (f", recommending {version}" if a.recommended else ""))
    print("upload update.json.sig and update.json LAST, after every file they name")


def cmd_verify(a) -> None:
    pkg, _pydir, default_out, _title = APPS[a.app]
    folder = Path(a.releases or os.environ.get("RELEASES") or default_out)
    try:
        data = (folder / "update.json").read_bytes()
        sig = (folder / "update.json.sig").read_bytes()
    except OSError as e:
        die(str(e))
    keys = None
    if a.pubkey:
        keys = [("given", a.pubkey)]
    try:
        m = update.read_manifest(data, sig, pkg, keys=keys)
    except update.NotTrusted as e:
        die(str(e))
    bad = 0
    for e in m.entries:
        p = folder / e.url
        if not p.is_file():
            print(f"MISSING {e.url}")
            bad = 1
            continue
        if (p.stat().st_size, sha256_of(p)) != (e.size, e.sha256):
            print(f"DIFFERENT {e.url}")
            bad = 1
            continue
        print(f"ok {e.platform} {e.arch} {e.version} {e.url}")
    if bad:
        die("the folder does not hold what its manifest names")
    print(f"{folder / 'update.json'}: signed by {m.key}, published {m.published}, every file present and matching")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="tools/update-feed.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("keygen", "pubkey", "write", "verify"):
        # pubkey exits 1 unless ohscore/update.py trusts the key (release.sh's gate).
        p = sub.add_parser(name)
        p.add_argument("--key", help=f"the private key (default $OHS_RELEASE_KEY, $OPENHAMSHACK_RELEASE_KEY or "
                                     f"{DEFAULT_KEY})")
        if name in ("write", "verify"):
            p.add_argument("--app", choices=sorted(APPS), default="nb")
            p.add_argument("--releases", help="the release folder (default $RELEASES or the app's /srv folder)")
        if name == "write":
            p.add_argument("--version", help="the release (default the app's VERSION file)")
            p.add_argument("--notes", help="the one-line notes (default: the release's notes from git)")
            p.add_argument("--notes-url", help="a \"What's new\" page beside the feed, e.g. index.html#notes "
                                               "(default none: the openhamshack.com folders carry no pages)")
            p.add_argument("--recommended", action="store_true",
                           help="name this version as recommended: clients on a newer one may go back to it")
            p.add_argument("--untrusted-ok", action="store_true",
                           help="sign with a key ohscore/update.py does not trust (tests only)")
        if name == "verify":
            p.add_argument("--pubkey", help="check against this public key (hex) instead of the trusted ones")
    a = ap.parse_args(argv)
    {"keygen": cmd_keygen, "pubkey": cmd_pubkey, "write": cmd_write, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
