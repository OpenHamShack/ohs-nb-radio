#!/usr/bin/env python3
"""Build the shared source site, https://openhamshack.com/source/

    tools/source-site.py [--site DIR] [--archive DIR] build
    tools/source-site.py ... publish PROJECT LIST [--carried-by WORD] [--title T] [--home URL]
    tools/source-site.py ... tarball REPO REV PREFIX --out DIR [--scrub LIST | --no-scrub]
    tools/source-site.py ... publish-own PROJECT TARBALL --licence L --carried C --covers C [--title T] [--home URL]
                                         [--replace-unpublished [URL]]
    tools/source-site.py ... check PROJECT [--live URL]
    tools/source-site.py ... withdraw PROJECT

--site     the site folder (default $SOURCE_SITE, else /srv/source-site)
--archive  where files leaving the site go (default $SOURCE_SITE_ARCHIVE,
           else the site folder's name plus -archive)

This is the one tool for every project whose installers carry GPL or LGPL
code by others - QO-100 NB and HAM (this repository) and, as they join,
OpenHamShack DATV, Desktop and ATV. Other projects call it by path from a
checkout of this repository; docs/source-site.md (copied onto the site as
HOW-TO-PUBLISH.txt) is the format and procedure, so nobody needs to read
this file to join.

Why one site rather than a source/ folder on each product site: the same
Qt, GCC and WSJT-X tarballs were being uploaded twice (NB and HAM, ~210 MB
each), and three more projects were about to make it five times. GPL-3
section 6(d) and the LGPL allow the source to sit on a different server,
provided each download page says clearly where it is and it stays up for
as long as the binaries are offered (Brian, 06/10/2026).

The layout:
    files/<tarball>          each tarball once, whichever projects need it
    manifests/<project>.txt  what each project's installers need (the format
                             of this repository's packaging/windows/sources.txt)
    SHA256SUMS               every file under files/, for sha256sum -c
    index.html               a section per project, anchored #<project>
    HOW-TO-PUBLISH.txt       docs/source-site.md, for the other projects

A tarball is identified by its name and SHA-256 together: two manifests
naming one file with one hash share a single copy; the same name with two
hashes is refused rather than letting one project's file replace the
other's under a URL both their pages point at.

build fetches whatever is missing or damaged (every file is hashed again on
every run, so a damaged copy is never published), then writes SHA256SUMS
and index.html, then moves any file no manifest lists any more into the
archive - never deleting - and prints a "remove from the remote source
site:" list, because an upload adds files and never takes any away.

publish stages one project's manifest and builds with it, but writes the
manifest and moves nothing out until every file it names is present and
verified: a manifest is only on the site once its files are. It does not
archive either - the installer the old manifest described is still on
offer until the caller has replaced it, and then runs build.

check downloads nothing: it says whether every file a project's manifest
names is in files/ with the right hash, and with --live, whether the
public copy of the site has that manifest, the files' SHA256SUMS lines
and each file at its full size.

withdraw is for a project that stops offering installers: its manifest
goes to the archive, and build archives whatever only it needed.

Each project's own source, one tarball per release, sits beside its
third-party list (from 06/10/2026: QO-100 NB and HAM are PyQt6 programs,
GPL, whose Windows installers ship only bytecode, and from NB 0.1.5 / HAM
0.1.6 every package also carries ohsdigi, compiled from a port of WSJT-X).
The repositories stay private; only release tarballs are published.
tarball makes one reproducibly from a commit, with the checkout's scrub
list (packaging/source-scrub.txt) applied; publish-own copies it in
and adds an "@own" line to the project's manifest. Own lines are never
dropped by publish-own or publish - a release's source stays for as long
as any of its binaries is offered, and every .deb ever released still is.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fcntl
import hashlib
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# A sibling module, not a package: inserted explicitly so the import works
# whether this file is run as a script (which would find it anyway) or
# loaded by path, as the tests load tools/site-build.py - the same reason
# tools/make-ico.py and tools/tone-test.py insert a path before their own
# imports of the main package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitemap_sync import sync_page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HOWTO = ROOT / "docs" / "source-site.md"
HTACCESS = ROOT / "packaging" / "source-site" / "htaccess"
DEFAULT_SITE = "/srv/source-site"
PUBLIC_URL = "https://openhamshack.com/source/"

# A name with a slash would write outside files/; a leading dot would hide
# it, or be "." or "..". The project name is also the page anchor.
NAME_RE = re.compile(r"^[A-Za-z0-9_+-][A-Za-z0-9._+-]*$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class SiteError(Exception):
    pass


@dataclass
class Entry:
    name: str
    sha: str
    licence: str
    carried: str
    covers: str
    urls: list[str]


@dataclass
class Manifest:
    project: str
    title: str = ""
    home: str = ""
    entries: list[Entry] = field(default_factory=list)     # third-party
    notes: list[str] = field(default_factory=list)
    own: list[Entry] = field(default_factory=list)         # the project's own, newest first

    def every(self) -> list[Entry]:
        return self.own + self.entries


# The url field of an own-source line. The tarball is made from a private
# repository, so there is no upstream to fetch it from: the site's copy,
# put there by publish-own, is the original. A file:// URL to the build
# folder was the alternative, and was rejected: it would print a path on
# the release host on the public page, and the build folder is not kept for ever.
# A damaged copy is mended by making the tarball again from the same
# commit (it is reproducible) and running publish-own again.
LOCAL = "local"


# --------------------------------------------------------------------------- manifests

def parse_manifest(text: str, project: str, origin: str) -> Manifest:
    """The sources.txt format: "#" comments and blank lines skipped, "@title"
    and "@home" naming the project, ">" lines prose for the page, and
    everything else
        file | sha256 | licence | installers that carry it | what it is the source of | url [fallback url ...]
    A line of the same six fields after "@own " is one of the project's own
    release tarballs (publish-own writes them; url is "local")."""
    m = Manifest(project)
    seen = set()
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if line.startswith(">"):
            rest = line[1:]
            m.notes.append(rest[1:] if rest.startswith(" ") else rest)
            continue
        own = s.startswith("@own ")
        if own:
            s = line = s[len("@own "):]
        elif s.startswith("@"):
            key, _, value = s[1:].partition(" ")
            if key not in ("title", "home") or not value.strip():
                raise SiteError(f"{origin}:{n}: unknown or empty directive: {s}")
            setattr(m, key, value.strip())
            continue
        parts = [p.strip() for p in line.split("|")]
        if (len(parts) != 6 or not NAME_RE.match(parts[0]) or not SHA_RE.match(parts[1])
                or not parts[5] or not all(parts[2:5])):
            raise SiteError(f"{origin}:{n}: malformed line: {line}")
        if parts[0] in seen:
            raise SiteError(f"{origin}:{n}: {parts[0]} is listed twice")
        seen.add(parts[0])
        (m.own if own else m.entries).append(Entry(parts[0], parts[1], parts[2], parts[3], parts[4],
                                                   parts[5].split()))
    return m


def render_manifest(m: Manifest, origin: str) -> str:
    """The manifest as published: the project's lines in the same format,
    with a header saying where they came from. The source list's own long
    comments stay in its repository; they are notes for its maintainers."""
    out = [f"# {m.project}: its own source, per release (@own lines), and the third-party source its "
           f"installers carry.",
           f"# Published by tools/source-site.py from {origin}.",
           "# Format: docs/source-site.md (HOW-TO-PUBLISH.txt on this site).", ""]
    if m.title:
        out.append(f"@title {m.title}")
    if m.home:
        out.append(f"@home {m.home}")
    out.append("")

    def line(e: Entry) -> str:
        return " | ".join([e.name, e.sha, e.licence, e.carried, e.covers, " ".join(e.urls)])
    out += [f"@own {line(e)}" for e in m.own]
    if m.own and m.entries:
        out.append("")
    out += [line(e) for e in m.entries]
    if m.notes:
        out.append("")
        out += [f"> {n}" if n else ">" for n in m.notes]
    return "\n".join(out) + "\n"


def load_manifests(site: Path) -> dict[str, Manifest]:
    out = {}
    d = site / "manifests"
    if d.is_dir():
        # By project name, as publish orders them, not by file name: "-"
        # sorts before ".", so openhamshack-nb-macos.txt came before openhamshack-nb.txt
        # and the page's sections changed order depending on which ran last.
        for p in sorted(d.glob("*.txt"), key=lambda p: p.stem):
            if not PROJECT_RE.match(p.stem):
                raise SiteError(f"{p}: a project name is lower-case letters, digits and hyphens")
            out[p.stem] = parse_manifest(p.read_text(encoding="utf-8"), p.stem, str(p))
    return out


def combine(manifests: dict[str, Manifest]) -> dict[str, Entry]:
    """Every tarball any manifest names, once each."""
    out: dict[str, Entry] = {}
    owner: dict[str, str] = {}
    for project, m in manifests.items():
        for e in m.every():
            if e.name in out and out[e.name].sha != e.sha:
                raise SiteError(f"{e.name}: {owner[e.name]} pins SHA-256 {out[e.name].sha} and {project} pins "
                                f"{e.sha}; one name cannot be two files - one of them is wrong, or the file "
                                f"needs another name")
            out.setdefault(e.name, e)
            owner.setdefault(e.name, project)
    return out


# --------------------------------------------------------------------------- files

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, text: str) -> None:
    """Whole, then moved into place: a reader (or an upload in progress)
    never sees half of a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def fetch(e: Entry, files: Path) -> bool:
    """Make files/<name> the pinned bytes: kept when it already hashes
    right, else fetched from the first URL that gives them. The fetch must
    hash right before it replaces anything."""
    path = files / e.name
    if path.is_file() and sha256_of(path) == e.sha:
        return True
    if e.urls == [LOCAL]:
        print(f"{e.name}: missing or damaged, and it has no upstream - it is a project's own release source. "
              f"Make it again from its release commit (tools/source-site.py tarball; the same commit gives the "
              f"same bytes) and run publish-own with it, or restore it from the archive", file=sys.stderr)
        return False
    part = path.with_name(path.name + ".part")
    for url in e.urls:
        print(f"fetching {e.name} from {url}", file=sys.stderr)
        # curl rather than urllib: it is what fetch-sources.sh used, it
        # retries, and with a plain tool's user agent SourceForge sends the
        # file instead of its "your download will start" page.
        r = subprocess.run(["curl", "-sSfL", "--retry", "3", "-A", "Wget/1.21", "-o", str(part), url],
                           stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            got = sha256_of(part)
            if got == e.sha:
                part.replace(path)
                return True
            print(f"{e.name} from {url}: SHA-256 {got}, expected {e.sha}", file=sys.stderr)
        else:
            print(f"{e.name} from {url}: {r.stderr.strip()}", file=sys.stderr)
        part.unlink(missing_ok=True)
    print(f"{e.name}: no URL gave the pinned file; upstream moved or changed it - check, then fix the manifest",
          file=sys.stderr)
    return False


def archive_file(src: Path, dest_dir: Path) -> Path:
    """Move src into dest_dir, never overwriting and never deleting what
    is not already safe there. The same bytes already archived: the site's
    copy is simply dropped. Different bytes under that name (a tarball
    re-pinned and later retired again): kept beside it with its hash in the
    name. fetch-sources.sh refused in that case instead, which left the
    file on the site and failed the release over something harmless."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        digest = sha256_of(src)
        if sha256_of(dest) == digest:
            src.unlink()
            return dest
        dest = dest_dir / f"{src.name}.{digest[:12]}"
        if dest.exists():
            src.unlink()
            return dest
    shutil.move(str(src), str(dest))
    return dest


def archived_manifest(archive: Path, project: str) -> Path:
    """A free name for a manifest leaving the site: <project>.<time>.txt,
    or with -2, -3... after the time when that second is taken. The time
    alone was the name until the own-source backfill published a dozen
    manifests in three seconds, and each one landing in a second already
    used replaced the earlier record."""
    d = archive / "manifests"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest, n = d / f"{project}.{stamp}.txt", 1
    while dest.exists():
        n += 1
        dest = d / f"{project}.{stamp}-{n}.txt"
    return dest


class Locked:
    """One build at a time: several sessions, one per project, share this
    folder. A lock on the folder itself, so no lock file ends up uploaded."""

    def __init__(self, site: Path):
        site.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(site, os.O_RDONLY)

    def __enter__(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


# --------------------------------------------------------------------------- the page

def _size(n: int) -> str:
    if n < 1000:
        return f"{n} bytes"
    return f"{n / 1e6:.1f} MB" if n >= 100_000 else f"{n / 1e3:.0f} kB"


# The product sites' tokens and type, copied rather than read from this
# repository's site/index.html: this page belongs to every project, and
# must not change when QO-100 NB's own page is restyled. Dark resting
# state, light override, no fonts or scripts from elsewhere - as the
# product sites.
STYLE = """
:root {
  --bg: #0a0d12; --card: #10141b; --ink: #e8edf4; --dim: #a3adbb; --line: #232a36;
  --accent: #4fd1e8; --code: #171c25;
}
@media (prefers-color-scheme: light) {
  :root { --bg: #eef1f5; --card: #ffffff; --ink: #0f1722; --dim: #4a5566; --line: #dde2e9;
          --accent: #0a8fb0; --code: #f3f5f8; }
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink); }
body { font: 17px/1.55 "DejaVu Sans", "Segoe UI", system-ui, -apple-system, sans-serif; }
a { color: var(--accent); }
.wrap { max-width: 1040px; margin: 0 auto; padding: 0 16px; }
header { padding: 40px 0 8px; }
header h1 { margin: 0; font-size: 36px; letter-spacing: .5px; }
header p.lede { margin: 8px 0 0; font-size: 19px; color: var(--dim); max-width: 780px; }
section { margin: 28px 0; }
h2 { font-size: 24px; margin: 0 0 6px; }
h3 { font-size: 19px; margin: 22px 0 4px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 20px; }
.meta { color: var(--dim); font-size: 14px; }
.note { color: var(--dim); font-size: 15px; margin: 8px 0 0; }
.projects { margin: 10px 0 0; padding-left: 20px; }
code, .mono { font-family: "DejaVu Sans Mono", ui-monospace, monospace; font-size: 13px;
  background: var(--code); padding: 1px 5px; border-radius: 5px; word-break: break-all; }
ul.files { list-style: none; margin: 14px 0 0; padding: 0; }
ul.files li { border-top: 1px solid var(--line); padding: 10px 0; }
ul.files li .name { font-weight: 700; word-break: break-all; }
ul.files li .lic { display: inline-block; font-size: 13px; border: 1px solid var(--line); border-radius: 999px;
  padding: 0 8px; margin-left: 6px; color: var(--dim); }
ul.files li div { color: var(--dim); font-size: 14px; margin-top: 2px; overflow-wrap: anywhere; }
@media (max-width: 520px) { header h1 { font-size: 30px; } header p.lede { font-size: 17px; } }
.notes { margin-top: 14px; font-size: 15px; color: var(--dim); }
.notes p { margin: 8px 0; }
.notes ul { margin: 4px 0; padding-left: 20px; }
footer { color: var(--dim); font-size: 14px; padding: 24px 0 48px; border-top: 1px solid var(--line); margin-top: 40px; }
footer a { color: var(--dim); }
footer p { margin: 4px 0; }
"""


def notes_html(notes: list[str]) -> str:
    """The ">" lines, reflowed: they are wrapped for a text file, and a
    phone would show those hard breaks as a ragged column. A blank line
    ends a paragraph; a line starting "- " starts a list item."""
    blocks: list[tuple[str, list[str]]] = []      # ("p", [text]) or ("ul", [items])
    for line in notes + [""]:
        s = line.strip()
        if not s:
            blocks.append(("break", []))
        elif s.startswith("- "):
            if not blocks or blocks[-1][0] != "ul":
                blocks.append(("ul", []))
            blocks[-1][1].append(s[2:])
        elif blocks and blocks[-1][0] in ("p", "ul") and blocks[-1][1]:
            blocks[-1][1][-1] += " " + s
        else:
            blocks.append(("p", [s]))
    out = []
    for kind, items in blocks:
        if kind == "p":
            out.append(f"<p>{html.escape(items[0])}</p>")
        elif kind == "ul":
            out.append("<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>")
    return f'<div class="notes">{"".join(out)}</div>' if out else ""


def _file_item(files: Path, e: Entry, own: bool) -> str:
    size = (files / e.name).stat().st_size
    # An own tarball has no upstream to name (its url is "local"): the
    # site's copy is the original, so "From" would only print the word.
    origin = ("" if own else
              f'<div>From <a href="{html.escape(e.urls[0])}">{html.escape(e.urls[0])}</a></div>')
    return (f'<li><a class="name" href="files/{html.escape(e.name)}">{html.escape(e.name)}</a> '
            f'<span class="meta">{_size(size)}</span><span class="lic">{html.escape(e.licence)}</span>'
            f'<div>Source of {html.escape(e.covers)}</div>'
            f'<div>In: {html.escape(e.carried)}</div>{origin}'
            f'<div>SHA-256 <span class="mono">{e.sha}</span></div></li>')


# What a project with no files at all says instead of a list: OpenHamShack ATV
# (06/10/2026) bundles no third-party code by design - its .deb is its own
# Python, everything else comes from Debian - so its manifest is notes
# only. The audit of that day read the bare section, "0 files, 0 bytes", as
# an archive not yet filled in. A manifest is by definition the third-party
# source its packages carry, so an empty one says exactly this.
NOTHING_BUNDLED = ('<p class="note"><b>No files to download here, by design.</b> {t}\'s packages carry no '
                   'third-party code, so there is no third-party source to publish with them.{more}</p>')


def _short(title: str) -> str:
    # "OpenHamShack " too: the other projects' manifests keep their old titles
    # until each is renamed, and a published manifest is never rewritten.
    for family in ("OpenHamShack ", "OpenHamShack "):
        if title.startswith(family):
            return title[len(family):]
    return title


def _and(names: list[str], last: str = " and ") -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + last + names[-1]


def page_meta(manifests: dict[str, Manifest]) -> tuple[str, str]:
    """(title, description), naming only the projects that have files here:
    the audit asked that the archive not be described as covering a
    program whose source is not on it."""
    with_files = [m.title or p for p, m in manifests.items() if m.every()]
    if not with_files:
        return "OpenHamShack source archive", "Source code for the OpenHamShack radio programs."
    return (f"OpenHamShack source archive: GPL and LGPL source for {_and([_short(t) for t in with_files], ' & ')}",
            f"Source code, under the GPL and LGPL, for the {_and(with_files)} radio programs, and for the "
            f"open-source components their installers carry.")


def _licence_url(licence: str) -> str:
    return f"https://spdx.org/licenses/{licence}.html" if re.fullmatch(r"[A-Za-z0-9.+-]+", licence) else licence


def head_html(manifests: dict[str, Manifest]) -> str:
    """Canonical address, link-preview tags and schema.org data. The page
    has no images, so the card is the small "summary" one. The structured
    data is a CollectionPage whose parts are each project's own source,
    tied to the program it builds - what the page is, an archive, rather
    than a product page."""
    title, desc = page_meta(manifests)
    e = html.escape
    parts = []
    for project, m in manifests.items():
        if not m.own:
            continue
        part = {"@type": "SoftwareSourceCode", "name": f"{m.title or project} source code",
                "url": f"{PUBLIC_URL}#{project}", "license": _licence_url(m.own[0].licence)}
        if m.home:
            part["targetProduct"] = {"@type": "SoftwareApplication", "name": m.title or project, "url": m.home}
        parts.append(part)
    data = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "description": desc,
            "url": PUBLIC_URL, "inLanguage": "en-GB",
            "publisher": {"@type": "Organization", "name": "360 Technology"}}
    if parts:
        data["hasPart"] = parts
    jsonld = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return (f'<title>{e(title)}</title><meta name="description" content="{e(desc)}">'
            f'<link rel="canonical" href="{PUBLIC_URL}">'
            f'<meta property="og:type" content="website"><meta property="og:locale" content="en_GB">'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">'
            f'<meta property="og:url" content="{PUBLIC_URL}"><meta name="twitter:card" content="summary">'
            f'<script type="application/ld+json">{jsonld}</script>')


def index_html(site: Path, manifests: dict[str, Manifest]) -> str:
    files = site / "files"
    nav, sections = [], []
    for project, m in manifests.items():
        title = m.title or project
        t = html.escape(title)
        total = sum((files / e.name).stat().st_size for e in m.every())
        count = (f'{len(m.every())} files, {_size(total)}' if m.every()
                 else 'nothing to download: it bundles no third-party code')
        nav.append(f'<li><a href="#{project}">{t}</a> <span class="meta">{count}</span></li>')
        home = (f'Its downloads: <a href="{html.escape(m.home)}">{html.escape(m.home)}</a>. ' if m.home else "")
        parts = [f'<section class="card" id="{project}"><h2>{t}</h2>'
                 f'<p class="note">{home}The list as a text file: '
                 f'<a href="manifests/{project}.txt">manifests/{project}.txt</a>.</p>']
        # The project's own source first, under a heading of its own: it is
        # the program itself, and must never read as one more third-party
        # component in the list below it.
        if m.own:
            own_total = sum((files / e.name).stat().st_size for e in m.own)
            parts.append(
                f'<h3>{t}\'s own source, per release</h3>'
                f'<p class="note">The complete source of each release of {t}, newest first - everything its '
                f'packages and installers are built from - made by <code>git archive</code> from that '
                f'release\'s commit; each unpacks into one folder named after the version. '
                f'{len(m.own)} files, {_size(own_total)}.</p>'
                f'<ul class="files">{"".join(_file_item(files, e, True) for e in m.own)}</ul>')
        if m.entries:
            tp_total = sum((files / e.name).stat().st_size for e in m.entries)
            parts.append(
                f'<h3>Third-party source in {t}\'s installers</h3>'
                f'<p class="note">The source of the third-party GPL and LGPL components in {t}\'s '
                f'installers: {len(m.entries)} files, {_size(tp_total)}.</p>'
                f'<ul class="files">{"".join(_file_item(files, e, False) for e in m.entries)}</ul>')
        if not m.every():
            parts.append(NOTHING_BUNDLED.format(
                t=t, more=" Its notes below say what it uses instead, and where that source is." if m.notes else ""))
        # Whether or not there is a list: a project whose installers carry
        # nothing by others (OpenHamShack ATV) says so, and why, in its notes.
        parts.append(notes_html(m.notes))
        sections.append("".join(parts) + "</section>")
    every = combine(manifests)
    total = sum((files / n).stat().st_size for n in every)
    body = "".join(sections) or '<section class="card"><p class="note">Nothing is published yet.</p></section>'
    return (
        '<!doctype html>\n<html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'{head_html(manifests)}'
        f'<style>{STYLE}</style></head><body><div class="wrap">'
        '<header><h1>Source code</h1>'
        '<p class="lede">The programs below are free software. Each one\'s section has its own source, one '
        'tarball per release, where it publishes it here, and the exact source release, unmodified, of every '
        'program and library by others under the GPL and LGPL that its installers carry. Each file stays '
        'for as long as anything built from it is offered.</p></header>'
        '<section class="card"><h2>Projects</h2>'
        f'<ul class="projects">{"".join(nav)}</ul>'
        f'<p class="note">{len(every)} files, {_size(total)}; a file two programs need is here once. '
        'Check downloads with <a href="SHA256SUMS">SHA256SUMS</a>: from a folder holding a '
        '<code>files/</code> folder with them in it, <code>sha256sum -c --ignore-missing SHA256SUMS</code>. '
        'Each program\'s own THIRD-PARTY.txt, installed beside it, has the licence texts.</p></section>'
        f'{body}'
        f'<footer><p>Built {datetime.date.today().isoformat()} by tools/source-site.py. '
        'Back to <a href="https://openhamshack.com/">openhamshack.com</a>.</p></footer>'
        '</div></body></html>\n')


def not_found_html() -> str:
    """The 404 page, in the archive's own look. Apache serves it at whatever
    address was asked for, so its links are absolute. The likeliest way
    here is a link to a tarball that has since been archived, because no
    installer still on offer needs it: say so."""
    # The archive is the /source/ folder of openhamshack.com since 12/10/2026,
    # not a host of its own, so its absolute links carry that folder: a bare
    # "/" would be the OpenHamShack home page.
    base = html.escape(urlsplit(PUBLIC_URL).path or "/")
    return ('<!doctype html>\n<html lang="en-GB"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="robots" content="noindex"><title>Not found - OpenHamShack source archive</title>'
            f'<style>{STYLE}</style></head><body><div class="wrap">'
            '<header><h1>Not found</h1><p class="lede">Nothing is published at this address. A source '
            'tarball stays here for as long as anything built from it is offered; once nothing is, it is '
            'moved off the site.</p></header>'
            '<section class="card"><h2>Where to go instead</h2><ul class="projects">'
            f'<li><a href="{base}">The source archive</a>: every file on offer now, by program</li>'
            f'<li><a href="{base}SHA256SUMS">SHA256SUMS</a>, the checksum of each</li>'
            '<li><a href="https://openhamshack.com/">openhamshack.com</a> and the OpenHamShack '
            'programs</li></ul></section></div></body></html>\n')


# --------------------------------------------------------------------------- verbs

def build(site: Path, archive: Path, manifests: dict[str, Manifest], *, prune: bool = True,
          stage: tuple[Manifest, str] | None = None, removed: list[str] | None = None) -> int:
    """Fetch and verify everything the manifests name, then write the page
    and sums; then, with prune, archive what nothing names. `stage` is a
    manifest to write only once its files are all in place (publish);
    `removed`, paths the caller already took off the site, to report with
    the files this run archives."""
    every = combine(manifests)
    files = site / "files"
    files.mkdir(parents=True, exist_ok=True)
    failed = [e.name for e in every.values() if not fetch(e, files)]
    if failed:
        print(f"not complete: {', '.join(failed)}; nothing on the site was changed apart from files "
              f"fetched whole", file=sys.stderr)
        return 1
    if stage:
        m, text = stage
        (site / "manifests").mkdir(exist_ok=True)
        path = site / "manifests" / f"{m.project}.txt"
        # The manifest it replaces is kept: it is the record of what an
        # earlier installer was offered with.
        if path.exists() and path.read_text(encoding="utf-8") != text:
            shutil.copy2(path, archived_manifest(archive, m.project))
        write_atomic(path, text)
    write_atomic(site / "SHA256SUMS", "".join(f"{e.sha}  files/{e.name}\n" for e in every.values()))
    new_index = index_html(site, manifests)
    old_index = (site / "index.html").read_text(encoding="utf-8") if (site / "index.html").is_file() else None
    write_atomic(site / "index.html", new_index)
    # The site's one page, so it is always "/" - home base is read from the
    # sitemap's own <loc> (see sitemap_sync); the public address is only
    # the fallback for a sitemap with nothing in it yet to read one from.
    # PUBLIC_URL, not $SOURCE_SITE_URL: that one says where to check the
    # live copy (a stand-in, in the tests), while a sitemap names the real
    # address, folder included.
    sync_page(site / "sitemap.xml", "/", old_index, new_index, PUBLIC_URL)
    if HOWTO.exists():
        write_atomic(site / "HOW-TO-PUBLISH.txt", HOWTO.read_text(encoding="utf-8"))
    # The server-level files: redirects, caching and the 404 page (why each,
    # in packaging/source-site/htaccess). Written on every build so the
    # site's copy is always the repository's; like robots.txt and
    # sitemap.xml, never removed by anything here - the prune below only
    # ever looks inside files/.
    if HTACCESS.exists():
        write_atomic(site / ".htaccess", HTACCESS.read_text(encoding="utf-8"))
    write_atomic(site / "404.html", not_found_html())
    print(f"{len(every)} tarballs present and verified in {files}, for "
          f"{', '.join(manifests) or 'no project'}", file=sys.stderr)
    if prune:
        removed = list(removed or [])
        for p in sorted(files.iterdir()):
            if p.name in every or not p.is_file() or p.name.endswith((".part", ".tmp")):
                continue
            dest = archive_file(p, archive / "files")
            print(f"moved {p.name} (no manifest lists it) to {dest}", file=sys.stderr)
            removed.append(f"files/{p.name}")
        report_removed(removed)
    return 0


def report_removed(removed: list[str]) -> None:
    if removed:
        print("remove from the remote source site:")
        for r in removed:
            print(f"  {r}")
    else:
        print("nothing to remove from the remote source site")


def publish(site: Path, archive: Path, project: str, list_path: Path, carried_by: str | None,
            title: str | None, home: str | None) -> int:
    if not PROJECT_RE.match(project):
        raise SiteError(f"{project}: a project name is lower-case letters, digits and hyphens")
    m = parse_manifest(list_path.read_text(encoding="utf-8"), project, str(list_path))
    if carried_by:
        # One list can serve several programs built from one repository
        # (NB and HAM): its "installers" field already says which carry
        # each tarball, so that is the filter - a second list per program
        # would be a copy to keep in step by hand.
        word = re.compile(rf"\b{re.escape(carried_by)}\b")
        m.entries = [e for e in m.entries if word.search(e.carried)]
    m.title = title or m.title
    m.home = home or m.home
    if m.own:
        # A list replaces the whole third-party half of the manifest on every
        # release, so own lines in it would have to name every version ever
        # released, for ever, or silently drop the source of binaries still
        # on offer. publish-own adds them one release at a time instead.
        raise SiteError(f"{list_path} has @own lines; a project's own source is published with publish-own")
    if not m.entries:
        raise SiteError(f"{list_path} lists nothing for {project}" + (f" carried by {carried_by}" if carried_by else ""))
    origin = list_path.name + (f", the lines whose installers name {carried_by}" if carried_by else "")
    with Locked(site):
        manifests = load_manifests(site)
        # The project's own source stays whatever its third-party list says.
        if project in manifests:
            m.own = manifests[project].own
        text = render_manifest(m, origin)
        manifests[project] = parse_manifest(text, project, f"manifests/{project}.txt")
        manifests = dict(sorted(manifests.items()))
        rc = build(site, archive, manifests, prune=False, stage=(m, text))
    if rc == 0:
        print(f"published manifests/{project}.txt ({len(m.entries)} tarballs) in {site}")
    return rc


# The scrub list's usual place in a checkout. Read from the checkout, not
# from the commit, for the reason --worktree-attributes is: the releases
# made before the list existed are made again with it.
SCRUB_LIST = Path("packaging") / "source-scrub.txt"
NOTES_NAME = "SOURCE-NOTES.txt"

# Files a replacement may never change, whatever the list says: what the
# compilers and Cargo read. A Python file is checked more finely (below);
# every other text file - documentation, shell and PowerShell scripts, the
# Debian copyright file - is the list's reviewer's to vouch for, and
# SOURCE-NOTES.txt names each one changed.
NEVER_CHANGED = {".rs", ".toml", ".lock", ".c", ".h", ".cc", ".cpp", ".hpp", ".f", ".f90", ".for", ".pyx",
                 ".spec", ".iss"}
NEVER_CHANGED_NAMES = {"Makefile", "CMakeLists.txt", "meson.build"}


@dataclass
class Scrub:
    """packaging/source-scrub.txt: literal replacements applied, in order,
    to every text file of a tarball while it is made, and patterns that
    must not be left anywhere afterwards. The format:
        old => new          a literal replacement, both sides exactly as
                            written apart from the one space either side of
                            "=>"; "\\n" is a line break, so a phrase wrapped
                            in a comment can be matched whole; "old =>"
                            replaces with nothing
        @forbid REGEX       a Python regex; a text file matching it after the
                            replacements stops the tarball
        > prose             copied into SOURCE-NOTES.txt
        # comment, blank    ignored"""
    path: Path
    pairs: list[tuple[int, str, str]] = field(default_factory=list)     # (list line, old, new)
    forbid: list[tuple[int, re.Pattern]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_scrub(path: Path) -> Scrub:
    s = Scrub(path)
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(">"):
            rest = line[1:]
            s.notes.append(rest[1:] if rest.startswith(" ") else rest)
        elif line.startswith("@forbid "):
            try:
                s.forbid.append((n, re.compile(line[len("@forbid "):].strip())))
            except re.error as e:
                raise SiteError(f"{path}:{n}: not a regex: {e}")
        elif " => " in line or line.endswith(" =>"):
            # Exactly as written, but for the one space either side of
            # "=>": a leading space is how " on <host>" stays clear of a
            # word that merely ends in "on".
            old, _, new = (line[:-3], "", "") if line.endswith(" =>") else line.partition(" => ")
            old, new = old.replace("\\n", "\n"), new.replace("\\n", "\n")
            if not old or old in new:
                # old inside new would make the result depend on how often
                # the list is applied; it is applied exactly once.
                raise SiteError(f"{path}:{n}: a replacement needs a text to replace, not contained in its "
                                f"replacement")
            s.pairs.append((n, old, new))
        else:
            raise SiteError(f"{path}:{n}: not 'old => new', '@forbid REGEX' or '> prose'")
    return s


def _py_shape(src: str, strings: bool) -> str | None:
    """A Python file's syntax tree with its docstrings blanked (and, with
    strings, every string constant): what must stay identical for a
    replacement to have changed nothing a run of it could see. Comments
    are not in the tree, and ast.dump leaves out line numbers, so a
    reworded comment, or a docstring that gained a line, compares equal.
    None if it does not parse."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body[0].value.value = ""
        if strings and isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.dump(tree)


def _is_test(rel: str) -> bool:
    return rel.startswith("tests/") or "/tests/" in rel


def _text(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scrub_file(s: Scrub, rel: str, data: bytes) -> tuple[bytes, int]:
    """One file's bytes after the list's replacements, and how many were
    made. Refuses (SiteError) any change the list must never make: to a
    file that is not UTF-8 text, to anything a compiler or Cargo reads, or
    to Python code - only comments and docstrings may change, and in the
    tests, string constants too (the test data's addresses: a test that
    still passes with another one shows the address was only a name)."""
    text = _text(data)
    if text is None:
        hit = [n for n, old, _ in s.pairs if old.encode("utf-8") in data]
        if hit:
            raise SiteError(f"{rel}: not text, so it cannot be scrubbed, and it holds what {s.path}:{hit[0]} "
                            f"replaces")
        return data, 0
    out, count = text, 0
    for _, old, new in s.pairs:
        k = out.count(old)
        if k:
            out, count = out.replace(old, new), count + k
    if not count:
        return data, 0
    name = rel.rsplit("/", 1)[-1]
    if Path(name).suffix in NEVER_CHANGED or name in NEVER_CHANGED_NAMES:
        raise SiteError(f"{rel}: {s.path} would change a file the build compiles or Cargo reads; those are "
                        f"never changed - fix the source instead")
    if name.endswith(".py"):
        strings = _is_test(rel)
        before = _py_shape(text, strings)
        if before is None or before != _py_shape(out, strings):
            raise SiteError(f"{rel}: {s.path} would change Python code, not only comments and docstrings"
                            + (" and the tests' strings" if strings else ""))
    return out.encode("utf-8"), count


def _left_out(tree: list[str], archived: set[str]) -> list[str]:
    """What export-ignore took out, for SOURCE-NOTES.txt: each path, or the
    highest folder all of whose files went, as "folder/ (N files)"."""
    total: dict[str, int] = {}
    missing: dict[str, int] = {}
    for p in tree:
        parts = p.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i]) + "/"
            total[d] = total.get(d, 0) + 1
            if p not in archived:
                missing[d] = missing.get(d, 0) + 1
    out: dict[str, int] = {}
    for p in tree:
        if p in archived:
            continue
        parts = p.split("/")[:-1]
        dirs = ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]
        top = next((d for d in dirs if missing.get(d) == total[d]), p)
        out[top] = out.get(top, 0) + 1
    return [f"{k} ({n} file{'' if n == 1 else 's'})" if k.endswith("/") else k for k, n in sorted(out.items())]


def _wrap(line: str, width: int = 76) -> list[str]:
    """A paragraph line wrapped for a text file, list items with a hanging
    indent."""
    if len(line) <= width:
        return [line]
    indent = len(line) - len(line.lstrip())
    item = re.match(r"\s*(\d+\.|-) ", line)
    hang = " " * (item.end() if item else indent)
    out, cur = [], line[:indent]
    for word in line[indent:].split(" "):
        if cur.strip() and len(cur) + len(word) > width:
            out.append(cur.rstrip())
            cur = hang
        cur += word + " "
    return out + [cur.rstrip()]


def source_notes(s: Scrub, prefix: str, commit: str, left_out: list[str], changed: list[str]) -> str:
    """SOURCE-NOTES.txt: how the tarball differs from its commit, and the
    promise that none of it changes how anything builds or runs. Only what
    the tool established - the files left out and changed are computed -
    and nothing that depends on the clock or the machine."""
    paras = [
        f"{prefix}: how this tarball differs from its release commit",
        "",
        f"This is the tree of commit {commit} of the project's repository, which is private, made by "
        f"tools/source-site.py tarball. It differs from that commit in the two ways below; neither changes "
        f"how anything here builds or runs.",
        "",
        "1. Left out, being marked export-ignore in .gitattributes (which says why):",
        *[f"     {p}" for p in left_out or ["nothing"]],
        "",
        "2. Internal host names, network addresses and account names, and a personal e-mail address, in "
        "comments, documentation and test data, were replaced with generic wording, the project's own "
        "address, or RFC 5737 documentation addresses (192.0.2.x), in:",
        *[f"     {p}" for p in changed or ["no file: none of them occurs in this commit"]],
        "",
        "   The tool that made this tarball refuses a replacement that would change code: in Python only "
        "comments and docstrings may change (and in tests, the test data's strings, which the tests still "
        "pass with), and Rust, Cargo and other compiled sources, and any file that is not text, are never "
        "changed.",
    ]
    if s.notes:
        paras += [""] + s.notes
    return "\n".join(w for p in paras for w in _wrap(p)) + "\n"


def _scrubbed_tar(src: Path, dst: Path, s: Scrub, prefix: str, commit: str, tree: list[str],
                  list_rel: str | None) -> None:
    """Copy git archive's tar member for member, in its order, with the
    list applied to each file and SOURCE-NOTES.txt added after the top
    folder. Every member keeps git's name, mode, owner and the commit's
    time; only a changed file's size and bytes differ, and the same input
    always gives the same output - so the tarball stays reproducible."""
    with tarfile.open(src, "r:") as tin:
        members = [(m, tin.extractfile(m).read() if m.isfile() else None) for m in tin.getmembers()]
        globals_ = dict(tin.pax_headers)
    archived = {m.name[len(prefix) + 1:] for m, _ in members if not m.isdir()}
    if NOTES_NAME in archived:
        raise SiteError(f"{commit} has a {NOTES_NAME} of its own, which the tarball's notes would replace")
    if list_rel in archived:
        # The list holds every name it hides; published, it would publish them.
        raise SiteError(f"{list_rel} would be in the tarball; mark it export-ignore in .gitattributes")
    changed, forbidden, out = [], [], []
    for m, data in members:
        rel = m.name[len(prefix) + 1:]
        if data is not None:
            data, n = scrub_file(s, rel, data)
            if n:
                changed.append(rel)
            text = _text(data) or ""
            for ln, pat in s.forbid:
                found = pat.search(text)
                if found:
                    forbidden.append(f"{rel}:{text.count(chr(10), 0, found.start()) + 1}: {found.group(0)!r} "
                                     f"(forbidden by {s.path}:{ln})")
        out.append((m, data))
    if forbidden:
        raise SiteError("left after the replacements - reword the source, or add a reviewed replacement to "
                        f"{s.path}:\n  " + "\n  ".join(forbidden))
    notes = source_notes(s, prefix, commit, _left_out(tree, archived), changed).encode("utf-8")
    top = out[0][0]
    ti = tarfile.TarInfo(f"{prefix}/{NOTES_NAME}")
    ti.size, ti.mtime, ti.mode, ti.uname, ti.gname = len(notes), top.mtime, 0o644, top.uname, top.gname
    out.insert(1, (ti, notes))
    with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT, pax_headers=globals_) as tout:
        for m, data in out:
            # git's own extended headers (long names) are made again from
            # the member as it now is; a stale size or path must not survive.
            m.pax_headers = {}
            if data is None:
                tout.addfile(m)
            else:
                m.size = len(data)
                tout.addfile(m, io.BytesIO(data))


def make_tarball(repo: Path, rev: str, prefix: str, out_dir: Path, scrub: Path | None = None,
                 no_scrub: bool = False) -> Path:
    """<out_dir>/<prefix>-src.tar.gz: the tree of commit `rev`, every path
    under <prefix>/, made so that the same commit always gives the same
    bytes - which is what lets a damaged or lost copy be made again and
    still match the SHA-256 the manifest pins, and lets anyone check that a
    tarball is that commit.

    git archive given a commit (not a tree) stamps every member with the
    commit's time, never the clock's. tar.umask is pinned because it
    sets the members' modes and a user's git config could change it. gzip
    -n leaves out the name and time gzip would otherwise put in its
    header. (git archive's own tar.gz is not used: its compressor has
    changed between git versions, and gzip is one fewer thing to trust.)

    --worktree-attributes applies the checkout's own .gitattributes, so
    export-ignore (private notes, never needed to build) is honoured even
    for commits made before that line was added - the backfill of every
    release did exactly that. Run from a clean checkout of the release
    commit, as release.sh is, those are the commit's own attributes.

    With a scrub list (`scrub`, else the checkout's packaging/
    source-scrub.txt when it has one) the tar passes through
    _scrubbed_tar before gzip: the internal names a commit already made
    public cannot be taken out of its history, only out of what is
    published from it (NB and HAM's releases up to 06/10/2026 named build
    hosts, the signing account and a home address). The list is applied to
    new releases too, as a net under the source's own care. Without a list
    the tar is exactly git archive's, as it always was - the other
    projects that call this tool are unaffected."""
    if not NAME_RE.match(prefix):
        raise SiteError(f"{prefix}: a prefix is letters, digits and . _ + - only")
    git = ["git", "-C", str(repo)]
    r = subprocess.run(git + ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SiteError(f"{rev}: not a commit in {repo}")
    commit = r.stdout.strip()
    if no_scrub:
        scrub = None
    elif scrub is None and (repo / SCRUB_LIST).is_file():
        scrub = repo / SCRUB_LIST
    s = parse_scrub(scrub) if scrub else None
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{prefix}-src.tar.gz"
    tmp = dest.with_name(dest.name + ".tmp")
    raw = dest.with_name(dest.name + ".tar.tmp")
    clean = dest.with_name(dest.name + ".scrubbed.tmp")
    try:
        with open(raw, "wb") as f:
            if subprocess.run(git + ["-c", "tar.umask=0022", "archive", "--format=tar", "--worktree-attributes",
                                     f"--prefix={prefix}/", commit], stdout=f).returncode != 0:
                raise SiteError(f"could not make {dest.name} from {commit}")
        if s:
            tree = subprocess.run(git + ["ls-tree", "-r", "-z", "--name-only", commit], capture_output=True,
                                  check=True).stdout.decode("utf-8", "surrogateescape").split("\0")
            try:
                list_rel = scrub.resolve().relative_to(repo.resolve()).as_posix()
            except ValueError:
                list_rel = None
            _scrubbed_tar(raw, clean, s, prefix, commit, [p for p in tree if p], list_rel)
            clean.replace(raw)
        with open(raw, "rb") as fin, open(tmp, "wb") as f:
            if subprocess.run(["gzip", "-n", "-9", "-c"], stdin=fin, stdout=f).returncode != 0:
                raise SiteError(f"could not compress {dest.name}")
        tmp.replace(dest)
    finally:
        for p in (raw, clean, tmp):
            p.unlink(missing_ok=True)
    return dest


def _origin(text: str) -> str:
    """The "from ..." of an existing manifest's header, so publish-own
    keeps saying where its third-party lines came from."""
    found = re.search(r"^# Published by tools/source-site\.py from (.*)\.$", text, re.M)
    return found.group(1) if found else "publish-own"


def _never_uploaded(live: str, name: str) -> str | None:
    """Why `name` may have reached the public site, or None if it surely
    has not: the public SHA256SUMS (read fresh) does not list it, and the
    file itself is not served. A SHA256SUMS that cannot be read proves
    nothing, so that counts as a reason too."""
    live = live if live.endswith("/") else live + "/"
    bust = f"?v={time.time_ns()}"
    sums = _curl(f"{live}SHA256SUMS{bust}")
    if sums is None:
        return f"{live}SHA256SUMS cannot be read, so whether {name} was uploaded cannot be told"
    if any(l.endswith(f"  files/{name}") for l in sums.splitlines()):
        return f"{live}SHA256SUMS lists {name}"
    if _curl(f"{live}files/{name}{bust}", head=True) is not None:
        return f"{live}files/{name} is served"
    return None


def publish_own(site: Path, archive: Path, project: str, tarball: Path, licence: str, carried: str,
                covers: str, title: str | None, home: str | None, replace_unpublished: str | None = None) -> int:
    """Add one release's own source to the project's manifest, at the top,
    and the tarball to files/. A name already published with the same bytes
    is a no-op (a re-run, or the backfill run twice); with other bytes it
    is refused - like a .deb, a version's source is never replaced: anyone
    who has the old file must be able to trust the name. Nothing is ever
    dropped here: old releases' source stays for as long as their binaries
    are offered, which for the .debs is for ever.

    replace_unpublished (the public site's address) is the one exception:
    a tarball that has never left this folder has no holder to mislead.
    It was added when the first own-source backfill had to be made again
    before its upload - screenshots left out and internal names scrubbed -
    and is refused unless the public site shows no trace of the name. The
    file it replaces goes to the archive, as anything leaving the site
    does, and the manifest line keeps its place."""
    if not PROJECT_RE.match(project):
        raise SiteError(f"{project}: a project name is lower-case letters, digits and hyphens")
    if not NAME_RE.match(tarball.name):
        raise SiteError(f"{tarball.name}: a file name is letters, digits and . _ + - only")
    for what, v in (("licence", licence), ("carried", carried), ("covers", covers)):
        if not v.strip() or "|" in v or "\n" in v:
            raise SiteError(f"--{what} must be one line, not empty, without '|'")
    digest = sha256_of(tarball)
    entry = Entry(tarball.name, digest, licence.strip(), carried.strip(), covers.strip(), [LOCAL])
    with Locked(site):
        manifests = load_manifests(site)
        path = site / "manifests" / f"{project}.txt"
        m = manifests.get(project) or Manifest(project)
        origin = _origin(path.read_text(encoding="utf-8")) if path.exists() else "publish-own"
        m.title = title or m.title
        m.home = home or m.home
        same = [e for e in m.own if e.name == entry.name]
        files = site / "files"
        files.mkdir(parents=True, exist_ok=True)
        dest = files / entry.name
        replaced = None
        if same and same[0].sha != digest:
            if not replace_unpublished:
                raise SiteError(f"{entry.name} is already published with SHA-256 {same[0].sha}, and this file "
                                f"is {digest}; a release's source is never replaced - a fix is a new version "
                                f"(unless it was never uploaded: --replace-unpublished)")
            why = _never_uploaded(replace_unpublished, entry.name)
            if why:
                raise SiteError(f"{entry.name} is not replaced: {why}. Once uploaded, a release's source is "
                                f"never replaced - a fix is a new version")
            replaced = same[0].sha
            m.own[m.own.index(same[0])] = entry
            if dest.is_file():
                print(f"moved the replaced {entry.name} to {archive_file(dest, archive / 'files')}",
                      file=sys.stderr)
        elif not same:
            m.own.insert(0, entry)
        if not (dest.is_file() and sha256_of(dest) == digest):
            # combine() below refuses a name another project pins with other
            # bytes before anything is written; checked here first so the
            # copy never replaces a file some manifest still needs.
            others = {k: v for k, v in manifests.items() if k != project}
            combine({**others, project: Manifest(project, own=[entry])})
            part = dest.with_name(dest.name + ".part")
            shutil.copyfile(tarball, part)
            if sha256_of(part) != digest:
                part.unlink()
                raise SiteError(f"{tarball} changed while it was being copied")
            part.replace(dest)
        text = render_manifest(m, origin)
        manifests[project] = parse_manifest(text, project, f"manifests/{project}.txt")
        manifests = dict(sorted(manifests.items()))
        rc = build(site, archive, manifests, prune=False, stage=(m, text))
    if rc == 0:
        print(f"published {entry.name} ({digest}) as {project}'s own source in {site}"
              + (f", replacing the never-uploaded {replaced}" if replaced else ""))
    return rc


def _curl(url: str, head: bool = False) -> str | None:
    args = ["curl", "-sSfL", "--max-time", "60"] + (["-I"] if head else []) + [url]
    r = subprocess.run(args, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def check(site: Path, project: str, live: str | None) -> int:
    path = site / "manifests" / f"{project}.txt"
    if not path.exists():
        print(f"{site} has no manifest for {project}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    m = parse_manifest(text, project, str(path))
    bad = []
    for e in m.every():
        f = site / "files" / e.name
        if not f.is_file():
            bad.append(f"{e.name}: missing")
        elif sha256_of(f) != e.sha:
            bad.append(f"{e.name}: wrong SHA-256")
    if not bad and live:
        live = live if live.endswith("/") else live + "/"
        # A random query on every request: 20i's CDN serves stale copies of
        # replaced files at the edge for a while, and this must see the
        # real one. (curl ignores it on file://, which the tests use.)
        bust = f"?v={time.time_ns()}"
        if _curl(f"{live}manifests/{project}.txt{bust}") != text:
            bad.append(f"{live}manifests/{project}.txt is missing or not the local one")
        sums = _curl(f"{live}SHA256SUMS{bust}") or ""
        lines = set(sums.splitlines())
        for e in m.every():
            if f"{e.sha}  files/{e.name}" not in lines:
                bad.append(f"{live}SHA256SUMS does not list {e.name} with its hash")
            head = _curl(f"{live}files/{e.name}{bust}", head=True) or ""
            sizes = re.findall(r"(?im)^content-length:\s*(\d+)", head)
            if not sizes or int(sizes[-1]) != (site / "files" / e.name).stat().st_size:
                bad.append(f"{live}files/{e.name} is missing or not its full size")
    for b in bad:
        print(b, file=sys.stderr)
    if bad:
        return 1
    print(f"{project}: all {len(m.every())} tarballs present and verified in {site}"
          + (f", and live at {live}" if live else ""))
    return 0


def withdraw(site: Path, archive: Path, project: str) -> int:
    with Locked(site):
        path = site / "manifests" / f"{project}.txt"
        if not path.exists():
            print(f"{site} has no manifest for {project}", file=sys.stderr)
            return 1
        shutil.move(str(path), str(archived_manifest(archive, project)))
        print(f"withdrew {project}", file=sys.stderr)
        return build(site, archive, load_manifests(site), removed=[f"manifests/{project}.txt"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the shared source site.")
    ap.add_argument("--site", default=os.environ.get("SOURCE_SITE") or DEFAULT_SITE)
    ap.add_argument("--archive", default=os.environ.get("SOURCE_SITE_ARCHIVE"))
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("build", help="fetch, verify, write the page, archive what nothing lists")
    p = sub.add_parser("publish", help="publish one project's manifest (moves nothing out)")
    p.add_argument("project")
    p.add_argument("list", type=Path)
    p.add_argument("--carried-by", help="only the lines whose installers field names this word")
    p.add_argument("--title")
    p.add_argument("--home")
    t = sub.add_parser("tarball", help="make <PREFIX>-src.tar.gz from a commit, reproducibly")
    t.add_argument("repo", type=Path)
    t.add_argument("rev")
    t.add_argument("prefix", help="the folder it unpacks into, e.g. openhamshack-nb-0.1.22")
    t.add_argument("--out", type=Path, required=True)
    sc = t.add_mutually_exclusive_group()
    sc.add_argument("--scrub", type=Path, help=f"the scrub list (default: REPO/{SCRUB_LIST}, if there is one)")
    sc.add_argument("--no-scrub", action="store_true", help="the archive's tar exactly, even with a list")
    o = sub.add_parser("publish-own", help="add one release's own source tarball to a project")
    o.add_argument("project")
    o.add_argument("tarball", type=Path)
    o.add_argument("--licence", required=True)
    o.add_argument("--carried", required=True, help="what is built from it, e.g. 'NB 0.1.5: its .debs and installer'")
    o.add_argument("--covers", required=True, help="what it is the source of")
    o.add_argument("--title")
    o.add_argument("--home")
    o.add_argument("--replace-unpublished", nargs="?", metavar="URL",
                   const=os.environ.get("SOURCE_SITE_URL") or PUBLIC_URL,
                   help="replace this name's other bytes, only if the public site (default $SOURCE_SITE_URL, "
                        f"else {PUBLIC_URL}) has never had it")
    c = sub.add_parser("check", help="is everything a project's manifest names here (and live)?")
    c.add_argument("project")
    c.add_argument("--live", nargs="?", const=os.environ.get("SOURCE_SITE_URL") or PUBLIC_URL,
                   help=f"also check the public copy (default $SOURCE_SITE_URL, else {PUBLIC_URL})")
    w = sub.add_parser("withdraw", help="a project that no longer offers installers")
    w.add_argument("project")
    a = ap.parse_args(argv)
    site = Path(a.site)
    archive = Path(a.archive or f"{str(site).rstrip('/')}-archive")
    try:
        if a.verb == "build":
            with Locked(site):
                return build(site, archive, load_manifests(site))
        if a.verb == "publish":
            return publish(site, archive, a.project, a.list, a.carried_by, a.title, a.home)
        if a.verb == "tarball":
            print(make_tarball(a.repo, a.rev, a.prefix, a.out, scrub=a.scrub, no_scrub=a.no_scrub))
            return 0
        if a.verb == "publish-own":
            return publish_own(site, archive, a.project, a.tarball, a.licence, a.carried, a.covers,
                               a.title, a.home, a.replace_unpublished)
        if a.verb == "check":
            return check(site, a.project, a.live)
        return withdraw(site, archive, a.project)
    except SiteError as e:
        print(f"source-site: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
