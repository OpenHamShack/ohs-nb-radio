#!/usr/bin/env python3
"""Build an OpenHamShack app's website into its release folder.

    tools/site-build.py [--app nb|ham] [--out <release folder>] [--url <site url>]

    --app nb   QO-100 NB (the default): site/, docs/USERGUIDE.md,
               docs/screenshots/, /srv/openhamshack-nb-releases,
               https://openhamshack.com/desktop/nb/
    --app ham  OpenHamShack Radio: site/ham/, docs/ham/USERGUIDE.md,
               docs/ham/screenshots/, /srv/openhamshack-ham-releases,
               https://openhamshack.com/desktop/ham/

The release folder IS the site: the newest version's .debs in it -
<package>_<version>_amd64.deb, _arm64.deb and _all.deb, or just _all.deb
for releases before ohsdigi - are what the Download card offers, so a .deb
cannot be on the site without being in the folder. tools/release.sh runs this after building the
.deb, so the page always names the version it just built.

Release notes are the commit subjects between release commits: written for
someone reading them in a year, which suits a changelog too (same
convention as the sibling OpenHamShack project's tools/site-build.py). NB's
release commits are "Release x.y.z", as they always were; HAM's are
"Release HAM x.y.z", so neither app's notes ever take the other's release
commit for its own. The two apps share one repository, so each app's notes
are only the commits that touch its files (APPS[app]["paths"]): HAM's are
HAM's own files - the NB history before HAM existed is not HAM's
changelog - and NB's are everything NB is built from, the shared core and
tooling included, less HAM's files. NB's notes were unfiltered until NB
0.1.2, whose list would otherwise have been mostly HAM's work.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

try:
    from PIL import Image
except ImportError:  # Pillow is optional: the page still builds without it,
    Image = None      # just with the screenshots' own PNGs at full size.

# tools/sitemap_sync.py is a sibling, not a package: inserted explicitly so
# the import works whether this file is run as a script (which would find
# it anyway) or loaded by path, as the test suite loads it, the same reason
# tools/make-ico.py and tools/tone-test.py insert a path before their own
# imports of the main package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sitemap_sync import sync_page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOTS = [  # (file in docs/screenshots, caption) - shown when present
    ("main-ft8-1920.png", "FT8: callsigns on the waterfall, click a CQ to answer"),
    ("transmitting-landed-1920.png", "TX lock: where your signal really landed, and the beacon-level guard"),
    ("main-usb-1920.png", "USB: bandscope and waterfall across the transponder"),
    ("main-cw-1920.png", "CW: keyer and decoder"),
    ("main-sstv-1920.png", "SSTV receive"),
    ("second-display-waterfall.png", "Second display: a large waterfall on its own screen"),
    ("settings-station.png", "Settings: your station, the PTT button and the licence"),
    ("main-usb-light-1920.png", "The light theme"),
]
HAM_SHOTS = [  # (file in docs/ham/screenshots, caption)
    ("main-20m-usb-1920.png", "20 m USB on the simulator: the band bar, the licence chip and the band plan "
                              "along the scope"),
    ("main-2m-fm-repeater-1920.png", "2 m FM on a simulated repeater: channel RV57, the −600 kHz shift and "
                                     "the CTCSS tone"),
    ("transmitting-fm-repeater-1920.png", "Keyed into the simulated repeater: its tone heard back, the "
                                          "sequencer chip and the estimated power"),
    ("main-ft8-20m-1920.png", "FT8 on 20 m, at the band's FT8 dial"),
    ("main-23cm-foundation-refused-1366.png", "A Foundation licence on 23 cm: transmit refused, with the "
                                              "reason on the licence chip"),
    ("settings-power.png", "Settings › Bands & power: the power chain that turns drive into watts"),
    ("welcome-licence.png", "First run: your licence class, and what the guard does"),
    ("main-2m-ssb-light-1920.png", "The light theme: 2 m SSB"),
]
NOTES_RELEASES = 12
SKIP = re.compile(r"^(Merge |Release )")
INLINE_MAX_WIDTH = 960  # inline screenshot width; the original stays behind a "full size" link
GUIDE_PAGE = "guide.html"
WINDOWS_ANCHOR = "installing-on-windows"   # the guide's "## Installing on Windows"

# Everything that differs between the two apps' sites. "paths" limits the
# release notes to commits touching those paths (git pathspecs; None: every
# commit).
#
# HAM_ONLY is what only OpenHamShack Radio is built from, and its notes' filter.
# NB's is the folders NB is built from or published with, less HAM_ONLY,
# so a file moved into HAM_ONLY drops out of NB's notes without a second
# list to keep in step. ohscore is shared and so counts for NB - a core fix
# is in the NB it ships with - but the Hermes-Lite 2 driver in it is HAM's
# alone. Tests and the handover are not shipped and are in neither.
HAM_ONLY = ["ohsradio", "docs/ham", "site/ham", "packaging/openhamshack-radio", "packaging/openhamshack-radio.1",
            "packaging/openhamshack-radio.desktop", "packaging/openhamshack-radio.metainfo.xml",
            "packaging/openhamshack-radio.svg",
            "packaging/windows/openhamshack-radio.spec", "packaging/windows/openhamshack-radio.iss",
            "packaging/windows/launch-ham.py", "ohscore/devices/hl2.py", "ohscore/devices/hl2sim.py"]
NB_FROM = ["ohsnb", "ohscore", "docs", "site", "packaging", "tools", "DESIGN.md"]
#
# "name" is the program's name wherever a page names it in prose (the
# source notes, the 404 page, the structured data). It used to be read from
# the front page's <title>, which stopped being only the name when the
# titles were given search-friendly copy (06/10/2026). "os" and "kind" are
# for the structured data, and may claim no more than the page's own status
# section does: HAM is a preview tested mainly on its simulator, NB an
# early preview that has not transmitted on air.
APPS = {
    "nb": {"pkg": "openhamshack-nb", "name": "OpenHamShack QO-100 NB", "site": ROOT / "site",
           "shots_dir": ROOT / "docs" / "screenshots", "shots": SHOTS,
           "guide": ROOT / "docs" / "USERGUIDE.md", "out": "/srv/openhamshack-nb-releases",
           "url": "https://openhamshack.com/desktop/nb/", "release": r"^Release (\d+\.\d+\.\d+)$",
           "paths": NB_FROM + [f":(exclude){p}" for p in HAM_ONLY],
           "os": "Linux (Debian, Ubuntu, Linux Mint, Raspberry Pi OS)",
           "kind": "Amateur radio transceiver for the QO-100 narrowband transponder (early preview)"},
    "ham": {"pkg": "openhamshack-radio", "name": "OpenHamShack Radio", "site": ROOT / "site" / "ham",
            "shots_dir": ROOT / "docs" / "ham" / "screenshots", "shots": HAM_SHOTS,
            "guide": ROOT / "docs" / "ham" / "USERGUIDE.md", "out": "/srv/openhamshack-ham-releases",
            "url": "https://openhamshack.com/desktop/ham/", "release": r"^Release HAM (\d+\.\d+\.\d+)$",
            "paths": HAM_ONLY,
            "os": "Linux (Debian, Ubuntu, Linux Mint)",
            "kind": "Amateur radio transceiver (preview, tested mainly on its simulator)"},
}


def releases(app: str = "nb") -> list[tuple[str, str, list[str]]]:
    """(version, date, [subjects]) newest first. Each release's notes are the
    commits reachable from it and not from the release before it - by date
    alone a branch merged late would land under the wrong release."""
    cfg = APPS[app]
    git = ["git", "-C", str(ROOT)]
    log = subprocess.run(git + ["log", "--first-parent", "--date=short", "--format=%H%x09%ad%x09%s"],
                         capture_output=True, text=True, check=True).stdout
    marks = [(sha, date, m.group(1)) for sha, date, subj in (l.split("\t", 2) for l in log.splitlines())
             if (m := re.match(cfg["release"], subj))]
    only = ["--", *cfg["paths"]] if cfg["paths"] else []
    out = []
    for (sha, date, ver), older in zip(marks, marks[1:] + [None]):
        rng = f"{older[0]}..{sha}" if older else sha
        subjects = subprocess.run(git + ["log", "--no-merges", "--format=%s", rng] + only,
                                  capture_output=True, text=True, check=True).stdout.splitlines()
        out.append((ver, date, [s for s in subjects if not SKIP.match(s)]))
    return out


def notes_html(rels: list[tuple[str, str, list[str]]]) -> str:
    parts = []
    for ver, date, subjects in rels[:NOTES_RELEASES]:
        items = "".join(f"<li>{html.escape(s)}</li>" for s in subjects) or "<li>Maintenance release.</li>"
        parts.append(f"<h3>{html.escape(ver)} <span class=\"meta\">{html.escape(date)}</span></h3><ul>{items}</ul>")
    return "\n".join(parts) if parts else '<span class="meta">No tagged release yet.</span>'


def _version_key(name: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", name)]


# The packages a release may have, in the order the page offers them. From
# the release that brought ohsdigi (the Rust FT8/FT4 encoder) there is one
# per architecture it is built for, and the pure-Python "all" one for
# anything else; earlier releases have "all" only.
DEB_ARCHES = (
    ("amd64", "PC or laptop (64-bit Intel or AMD)"),
    ("arm64", "Raspberry Pi 4, 400, 5 or 500 (64-bit Raspberry Pi OS)"),
    ("all", "Any other machine"),
)


def names(app: str) -> str:
    """An app's package name, as its release folder names files."""
    return APPS[app]["pkg"]


def latest_debs(out: Path, pkg: str = "openhamshack-nb") -> tuple[str, dict[str, Path]] | None:
    """The newest version in the folder and its .deb for each architecture."""
    found: dict[str, dict[str, Path]] = {}
    arches = "|".join(a for a, _ in DEB_ARCHES)
    for p in out.glob(f"{pkg}_*.deb"):
        m = re.match(rf"^{re.escape(pkg)}_(.+)_({arches})\.deb$", p.name)
        if m:
            found.setdefault(m.group(1), {}).setdefault(m.group(2), p)
    if not found:
        return None
    ver = max(found, key=_version_key)
    return ver, found[ver]


def latest_deb(out: Path, pkg: str = "openhamshack-nb") -> Path | None:
    """The newest release's main .deb: amd64 when there is one, else all."""
    r = latest_debs(out, pkg)
    if r is None:
        return None
    debs = r[1]
    return debs.get("amd64") or debs.get("all") or next(iter(debs.values()))


def deb_version(out: Path, pkg: str = "openhamshack-nb") -> str | None:
    r = latest_debs(out, pkg)
    return r[0] if r else None


def latest_exe(out: Path, pkg: str = "openhamshack-nb") -> Path | None:
    """The newest Windows installer (tools/release.sh --windows put it there).
    The page links this one only, and only as found in the folder: release.sh
    --windows moves older installers off the site, and nothing here may name
    one that is gone (release notes are commit subjects and link no files;
    older .debs stay in the folder, reachable by name)."""
    found = []
    for p in out.glob(f"{pkg}-*-setup.exe"):
        m = re.match(rf"^{re.escape(pkg)}-(.+)-setup\.exe$", p.name)
        if m:
            found.append((_version_key(m.group(1)), p))
    return max(found, key=lambda f: f[0])[1] if found else None


def latest_dmg(out: Path, pkg: str = "openhamshack-nb") -> tuple[Path, str] | None:
    """The Mac disk image on offer (tools/release.sh --macos put it there)
    and the version its About shows: <release>+<label> for a preview named
    <package>-<release>-<label>-arm64.dmg (build-macos.sh --preview). As
    with the installer, release.sh moves older ones off the site."""
    found = []
    for p in out.glob(f"{pkg}-*-arm64.dmg"):
        m = re.match(rf"^{re.escape(pkg)}-(\d+(?:\.\d+)+)(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?-arm64\.dmg$",
                     p.name)
        if m:
            found.append((_version_key(m.group(1)), _version_key(m.group(2) or ""), p,
                          m.group(1) + (f"+{m.group(2)}" if m.group(2) else "")))
    if not found:
        return None
    best = max(found, key=lambda f: (f[0], f[1]))
    return best[2], best[3]


def _sha256(path: Path) -> str:
    """A .sha256 beside the file (written by release.sh) is trusted over
    recomputing it, but recomputing is the fallback for a folder built by
    hand (as the tests do)."""
    sha_file = path.with_name(path.name + ".sha256")
    if sha_file.exists():
        return sha_file.read_text().split()[0]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_html(path: Path) -> str:
    size_mb = path.stat().st_size / 1e6
    return (f'<a class="btn" href="{html.escape(path.name)}">Download {html.escape(path.name)}</a>'
            f'<span class="meta">{size_mb:.1f} MB</span>'
            f'<span class="meta">SHA-256 <span class="mono">{html.escape(_sha256(path))}</span></span>')


# What HAM's page says where the Windows download goes while the folder has
# no HAM installer. It is published separately (release.sh ham --windows),
# so a release can be on the site before any .exe is.
HAM_NO_WINDOWS = ('<div class="planned"><h3>Windows</h3><p class="note">No Windows installer has been '
                  'published yet. Use Linux, or check back.</p></div>')


def download_html(out: Path, guide: bool = False, app: str = "nb") -> str:
    """The newest .deb in the folder, its size and checksum, and the one-line
    install command; then the Windows installer, when one has been added.
    NB says nothing about Windows until there is one, as it always has;
    HAM says there is none yet (HAM_NO_WINDOWS)."""
    r = latest_debs(out, names(app))
    if r is None:
        return '<span class="meta">No release has been published yet; check back shortly.</span>'
    win = windows_html(out, guide, app)
    if not win and app == "ham":
        win = HAM_NO_WINDOWS
    debs = r[1]
    deb = latest_deb(out, names(app))
    if set(debs) == {"all"}:
        linux = _file_html(deb)
    else:
        linux = "".join(f'<h3>{html.escape(label)}</h3>' + _file_html(debs[a])
                        for a, label in DEB_ARCHES if a in debs)
        linux += ('<p class="note">Not sure which? <code>dpkg --print-architecture</code> says '
                  '<code>amd64</code> or <code>arm64</code>; for anything else take the <code>all</code> '
                  'package, which sends FT8 and FT4 with WSJT-X\'s own encoders instead of the built-in '
                  'one.</p>')
    return (linux + f'<pre class="mono">sudo apt install ./{html.escape(deb.name)}</pre>' + win
            + macos_html(out, app) + source_html(out, app))


# The macOS preview's minimum system: NumPy 2.5's arm64 wheels need 14
# (packaging/macos/*.spec's LSMinimumSystemVersion; build-macos.sh fails a
# build with any binary that needs later).
MACOS_MIN = "macOS 14 (Sonoma)"


def macos_html(out: Path, app: str = "nb") -> str:
    """The Mac disk image, when release.sh --macos has put one in the
    folder (Brian, 07/10/2026: the first went up as a preview ahead of
    0.1.10). Nothing at all otherwise. It says plainly what it is - an
    unsigned preview for Apple Silicon - and the things a Mac user would
    otherwise find out the hard way: how to get past Gatekeeper the first
    time (macOS 15 and 26 have no right-click Open any more), the
    microphone permission (refused, macOS hands the program silence with no
    error), the Local Network permission a radio on the LAN needs from
    mac-preview.2 on (refused, the radio is simply unreachable), that a
    Pluto is reached over the network only, and what is not in it. (Until
    17/10/2026 it also said FT8 decoding ran WSJT-X's Intel tools under
    Rosetta 2; the app carries no WSJT-X now and runs natively.)
    And where its source is: its own section of the source site, apart
    from the Windows installer's - a different set of third-party code."""
    found = latest_dmg(out, names(app))
    if found is None:
        return ""
    dmg, shown = found
    name = html.escape(APPS[app]["name"])
    src = html.escape(f"{SOURCE_SITE_URL}#{APPS[app]['pkg']}-macos")
    preview = "+" in shown
    # The Hermes-Lite 2 is HAM's alone (see windows_html's own hl2 note).
    radios = "a Pluto, LibreSDR or Hermes-Lite 2" if app == "ham" else "a Pluto or LibreSDR"
    return (f'<h3 id="macos">macOS{" (preview)" if preview else ""}: Apple Silicon, {MACOS_MIN} or later</h3>'
            + _file_html(dmg)
            + '<p class="note">'
            + (f'<b>A preview, and unsigned.</b> It is built from the code after the release above, and calls '
               f'itself {html.escape(shown)} in Help › About. ' if preview else '<b>Unsigned.</b> ')
            + f'It is signed ad hoc only - not with an Apple Developer ID, and not notarised - so it does not '
              f'update itself: check this page for a newer one. Apple Silicon Macs only (M1 or later); there '
              f'is no Intel build.</p>'
            + f'<p class="note"><b>Opening it the first time.</b> Open the <code>.dmg</code> and drag {name} '
              f'onto Applications. macOS then refuses the first start. On <b>macOS 15 (Sequoia) and 26</b>: '
              f'open the app once and choose <b>Done</b>; then open <b>System Settings › Privacy &amp; '
              f'Security</b>, scroll down to <i>"{name}" was blocked to protect your Mac</i>, click <b>Open '
              f'Anyway</b>, and confirm with <b>Open Anyway</b> and your password. On macOS 14: right-click '
              f'the app, choose <b>Open</b>, then <b>Open</b>. After that it opens normally.</p>'
            + f'<p class="note"><b>The microphone.</b> When macOS asks whether {name} may use the '
              f'microphone, allow it - otherwise macOS gives the program silence, with no error, and you '
              f'transmit nothing. It can be changed later in System Settings › Privacy &amp; Security › '
              f'Microphone.</p>'
            + f'<p class="note"><b>Local network access.</b> When macOS asks whether {name} may find and '
              f'connect to devices on your local network, allow it - otherwise {radios} on your LAN is '
              f'simply unreachable, with no clear error. It can be changed later in System Settings › '
              f'Privacy &amp; Security › Local Network.</p>'
            + '<p class="note"><b>Radios and modes.</b> A Pluto (or LibreSDR, Pluto+) over the network only, '
              'as <code>ip:&lt;address&gt;</code>; a Pluto plugged in by USB is a network connection to the '
              'Mac and works as <code>ip:192.168.2.1</code> (<code>usb:</code> does not). Not in this build: '
              'SoapySDR receivers, JS8 and FreeDV 2020 (FreeDV 1600, 700C and 700D are there). FT8, FT4 and '
              'Q65 are decoded and sent by OpenHamShack\'s own decoder, natively on Apple silicon: no '
              'WSJT-X is needed. One you have installed in Applications is used as a cross-check.</p>'
            + f'<p class="note">Its source, and that of the GPL and LGPL components inside it (Qt 6 and '
              f'PyQt6, libiio, libad9361, codec2 and more): '
              f'<a href="{src}">{src}</a>.</p>')


def windows_html(out: Path, guide: bool = False, app: str = "nb") -> str:
    """The app's Windows installer, if the folder has one, with the three
    things a first-time Windows user trips over: SmartScreen may still ask
    about a newly signed publisher (the installers are signed by 360
    Technology since NB 0.1.5 / HAM 0.1.6 - this note said "Not code-signed"
    until 06/10, after that stopped being true), and the Pluto's
    USB drivers - which the installer offers, ticked - need Windows'
    "install this device software?" answered Install, before the Pluto is
    plugged in. (libiio 0.26 is inside the program; until installers that
    carry it, the note told people to fetch it and the drivers from ADI.)
    Nothing at all when there is no .exe. With the guide published, a link
    to its Windows section, which has the details and the check to run
    before starting."""
    exe = latest_exe(out, names(app))
    if exe is None:
        return ""
    more = (f' <a href="{GUIDE_PAGE}#{WINDOWS_ANCHOR}">Installing on Windows, step by step</a>.' if guide else "")
    # The Hermes-Lite 2 is HAM's alone: reached over the network, so the
    # firewall's first-run question is the one thing in its way.
    hl2 = (' For a Hermes-Lite 2, allow the program on <b>private networks</b> when Windows Firewall asks.'
           if app == "ham" else "")
    return ('<h3>Windows 10/11 (64-bit)</h3>' + _file_html(exe)
            + '<p class="note">Signed by <b>360 Technology</b>. While Windows is still learning a new '
              'publisher, SmartScreen may show "Windows protected your PC": choose <b>More info</b>, check '
              'it names 360 Technology, then <b>Run anyway</b>. S mode cannot run it. For a Pluto, libiio 0.26 '
              'is built in and the installer offers Analog Devices\' <b>PlutoSDR USB drivers</b>: leave '
              'it ticked, answer <b>Install</b> when Windows asks about their device software, and do it '
              'before plugging the Pluto in. FT8, FT4 and FreeDV are built in, with no WSJT-X to '
              'install.'
            + hl2 + more + '</p>')


# --------------------------------------------------------------------------- third-party source
#
# The Windows installers carry GPL and LGPL code by others. Its exact source
# is published once, for every OpenHamShack project, on the shared source site
# (tools/source-site.py; release.sh --windows publishes this app's list
# there and will not publish an installer without it), under an anchor per
# project. GPL-3 section 6(d) allows that, provided the page offering the
# installer gives clear directions to it - which is this paragraph. Until
# 06/10/2026 each site carried its own copy in source/ and listed every
# tarball here; the list now lives on the source site, so the two can
# never disagree.

SOURCE_SITE_URL = "https://openhamshack.com/source/"
SOURCE_DIR = "source"

SOURCE_WHY = ('The Windows installer carries programs and libraries by others under the GPL and LGPL — '
              'Qt, PyQt6, libiio, codec2 and more — whose licences require their source to be available '
              'with it.')


def source_url(app: str = "nb") -> str:
    return f"{SOURCE_SITE_URL}#{APPS[app]['pkg']}"


# The program's own source, every release of it, is on the same site, in
# the same section (release.sh publishes each release commit's tarball
# there before building anything; Brian, 06/10/2026). It is offered
# wherever a package is: every .deb is GPL code by us, and from NB 0.1.5 /
# HAM 0.1.6 the amd64 and arm64 ones carry ohsdigi compiled - nothing but
# the source tarball shows what it was compiled from.
OWN_SOURCE = ('{name} is free software under the GNU GPL, version 3 or later. The complete source of every '
              'release - the program, and ohsdigi, its FT8/FT4 encoder ported from WSJT-X - is published at '
              '<a href="{url}">{url}</a>, one tarball per version, for as long as that version is offered.')


def source_html(out: Path, app: str = "nb") -> str:
    """The download card's directions to the source: the program's own,
    always (the card only exists once a release is published), and the
    installer's third-party source whenever the folder offers an
    installer (the .deb carries none of that code). Also, where the site
    once had its own source/ folder, rewrites source/index.html as a
    pointer to the source site: installers already out there name that
    address in their THIRD-PARTY.txt, and must still find the source from
    it."""
    url = html.escape(source_url(app))
    name = html.escape(APPS[app]["name"])
    own = (f'<h3 id="source">Source code</h3>'
           f'<p class="note">{OWN_SOURCE.format(name=name, url=url)}</p>')
    if latest_exe(out, names(app)) is None:
        return own
    if (out / SOURCE_DIR).is_dir():
        # noindex: a page that only sends people elsewhere is not one a
        # search engine should list (the audit found it indexed as an
        # orphan). The site's .htaccess answers /source/ with a 301 to the
        # same place before this page is ever served; it stays for a host
        # that ignores .htaccess.
        page =(f'<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<meta name="robots" content="noindex">'
                f'<meta http-equiv="refresh" content="0; url={url}">'
                f'<title>{name}: third-party source</title><style>{_base_style(app)}</style></head>'
                f'<body><div class="wrap"><header><h1>Third-party source</h1>'
                f'<p class="lede">{SOURCE_WHY} It has moved to <a href="{url}">{url}</a>.</p></header>'
                f'<p><a href="../">Back to {name}</a></p></div></body></html>\n')
        tmp = out / SOURCE_DIR / "index.html.tmp"
        tmp.write_text(page)
        tmp.replace(out / SOURCE_DIR / "index.html")
    return own + (f'<h3>Source code for the bundled third-party components</h3>'
                  f'<p class="note">{SOURCE_WHY} The exact source release of each, with its licence and what it '
                  f'is the source of, is in the same place: <a href="{url}">{url}</a>.</p>')


# --------------------------------------------------------------------------- what search engines and link previews read
#
# Each page's <title> and description are written in its template
# (site/index.html, site/guide.html and HAM's), beside the copy they
# summarise, and read back from there: one place to keep them honest. The
# rest of the head is derived here from those two and the release folder,
# so it can never name a version, a download or a screenshot the site
# does not have. Nothing in it may claim more than the page's own status
# section - no ratings, no reviews (there are none), no "tested on air".

PUBLISHER = {"@type": "Organization", "name": "360 Technology", "email": "noreply@openhamshack.com"}
LICENCE_URL = "https://spdx.org/licenses/GPL-3.0-or-later.html"


def page_meta(template: str) -> tuple[str, str]:
    """(title, description) as the template writes them, unescaped."""
    title = re.search(r"<title>(.*?)</title>", template, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)"', template)
    return (html.unescape(title.group(1).strip()) if title else "",
            html.unescape(desc.group(1)) if desc else "")


def og_shot(app: str, shots: Shots) -> tuple[Shot, str] | None:
    """The screenshot a link preview shows: the front page's first one that
    exists, at full size (1920x1080 for both apps' main shots - large
    enough for every preview size the big-image card is drawn at)."""
    for name, caption in APPS[app]["shots"]:
        src = APPS[app]["shots_dir"] / name
        if src.exists():
            return shots.publish(src), caption
    return None


def _json_for_html(data: dict) -> str:
    """JSON safe inside <script>: "<" escaped, so no string in it can close
    the element early."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def software_jsonld(out: Path, app: str, url: str, version: str | None, description: str,
                    og: tuple[Shot, str] | None, guide: bool) -> dict:
    """schema.org SoftwareApplication for the front page. Windows is listed
    only while an installer is on offer, the version and downloads only
    once a release is in the folder."""
    cfg = APPS[app]
    exe = latest_exe(out, names(app))
    data = {"@context": "https://schema.org", "@type": "SoftwareApplication",
            "name": cfg["name"], "description": description, "url": url,
            "applicationCategory": "CommunicationApplication", "applicationSubCategory": cfg["kind"],
            "operatingSystem": cfg["os"] + (", Windows 10/11 (64-bit)" if exe else ""),
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "GBP"},
            "license": LICENCE_URL, "author": PUBLISHER, "publisher": PUBLISHER, "inLanguage": "en-GB"}
    r = latest_debs(out, names(app))
    if version and r:
        data["softwareVersion"] = version
        files = [r[1][a] for a, _label in DEB_ARCHES if a in r[1]] + ([exe] if exe else [])
        data["downloadUrl"] = [url + f.name for f in files]
    if og:
        shot, caption = og
        data["screenshot"] = {"@type": "ImageObject", "url": f"{url}shots/{shot.full}", "caption": caption,
                              "width": shot.full_size[0], "height": shot.full_size[1]}
    if guide:
        data["softwareHelp"] = {"@type": "CreativeWork", "name": f"{cfg['name']} user guide",
                                "url": url + GUIDE_PAGE}
    return data


def head_html(app: str, template: str, canonical: str, url: str, og: tuple[Shot, str] | None,
              jsonld: dict | None = None) -> str:
    """The canonical address, Open Graph and Twitter card tags, and any
    structured data, for a page whose template is `template`."""
    e = html.escape
    title, desc = page_meta(template)
    tags = [f'<link rel="canonical" href="{e(canonical)}">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{e(APPS[app]["name"])}">',
            '<meta property="og:locale" content="en_GB">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta property="og:url" content="{e(canonical)}">']
    if og:
        shot, caption = og
        tags += [f'<meta property="og:image" content="{e(url)}shots/{e(shot.full)}">',
                 f'<meta property="og:image:width" content="{shot.full_size[0]}">',
                 f'<meta property="og:image:height" content="{shot.full_size[1]}">',
                 f'<meta property="og:image:alt" content="{e(caption)}">',
                 '<meta name="twitter:card" content="summary_large_image">']
    else:
        tags.append('<meta name="twitter:card" content="summary">')
    if jsonld:
        tags.append(f'<script type="application/ld+json">{_json_for_html(jsonld)}</script>')
    return "\n".join(tags)


# --------------------------------------------------------------------------- the user guide
#
# docs/USERGUIDE.md is the guide's one source: read on GitHub-style viewers as
# Markdown, and published here as guide.html. No Markdown library is
# installed on the host that builds the site, and none may be added (the
# site, like the program, has no dependencies it cannot vouch for), so this
# is a small renderer for exactly the subset the guide uses: ATX headings,
# paragraphs, "-" and "1." lists one level deep with indented sub-items,
# pipe tables, fenced code, standalone images (which become figures), and
# inline `code`, **bold**, *italic*, [links](...) and HTML comments (dropped).
# Anything else is shown as escaped text - never passed through as HTML,
# so "<address>" in the guide is shown, not swallowed as a tag.

def slug(text: str) -> str:
    """The anchor for a heading, as GitHub makes it - so a link written as
    #installing-on-windows works both there and on the site."""
    s = re.sub(r"[`*_\[\]()]", "", text).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


_INLINE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|\*(.+?)\*|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text: str) -> str:
    """Inline Markdown to HTML; everything that is not markup is escaped."""
    out, pos = [], 0
    text = text.replace("\\|", "|")
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        code, bold, ital, alt, src, label, href = m.groups()
        if code is not None:
            out.append(f"<code>{html.escape(code)}</code>")
        elif bold is not None:
            out.append(f"<b>{inline(bold)}</b>")
        elif ital is not None:
            out.append(f"<i>{inline(ital)}</i>")
        elif src is not None:
            out.append(f'<img src="{html.escape(src)}" alt="{html.escape(alt)}">')
        else:
            out.append(f'<a href="{html.escape(href)}">{inline(label)}</a>')
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def render_markdown(md: str, image=None) -> tuple[str, list[tuple[str, str]]]:
    """(body html, [(anchor, title)] of the level-2 headings). `image(src,
    alt)` returns the html for a standalone image; by default a plain
    figure."""
    image = image or (lambda src, alt: f'<figure><img src="{html.escape(src)}" alt="{html.escape(alt)}">'
                                       f'<figcaption>{inline(alt)}</figcaption></figure>')
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    lines = md.splitlines()
    out: list[str] = []
    toc: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    # (Markdown level, page level) of each heading still open; the page's
    # own <h1> encloses them all.
    depth: list[tuple[int, int]] = [(1, 1)]
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush()
            i += 1
            continue
        if s.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append(f'<pre class="mono">{html.escape(chr(10).join(lines[i + 1:j]))}</pre>')
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            # The page's level is one below its nearest enclosing heading's,
            # never more: HAM's guide went from "## Settings" straight to
            # "#### Station" and seven more, which on the page skipped h3
            # (the audit of 06/10/2026). Fixed here rather than in the
            # Markdown, which is HAM's to write and reads fine as it is;
            # any guide that skips a level gets the same outline.
            while len(depth) > 1 and depth[-1][0] >= level:
                depth.pop()
            page_level = min(level, depth[-1][1] + 1)
            depth.append((level, page_level))
            a = slug(title)
            if a in seen:
                seen[a] += 1
                a = f"{a}-{seen[a]}"
            else:
                seen[a] = 0
            if level == 2:
                toc.append((a, title))
            out.append(f'<h{page_level} id="{a}">{inline(title)}</h{page_level}>')
            i += 1
            continue
        m = re.match(r"^!\[([^\]]*)\]\(([^)\s]+)\)$", s)
        if m:
            flush()
            out.append(image(m.group(2), m.group(1)))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            flush()
            head = _cells(s)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(_cells(lines[j]))
                j += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            body = []
            for r in rows:
                # A row with only its first cell filled is a sub-heading
                # inside the table (the shortcuts table's "Tuning", ...).
                if len(r) > 1 and r[0] and not any(r[1:]):
                    body.append(f'<tr class="sub"><th colspan="{len(head)}">{inline(r[0])}</th></tr>')
                else:
                    # data-label: on a phone each row is stacked as a small card,
                    # every cell under its column's name (CSS in site/guide.html).
                    body.append("<tr>" + "".join(
                        f'<td data-label="{html.escape(re.sub(r"[*`]", "", head[k]) if k < len(head) else "")}">'
                        f'{inline(c)}</td>' for k, c in enumerate(r)) + "</tr>")
            out.append(f'<div class="table"><table><thead><tr>{th}</tr></thead>'
                       f'<tbody>{"".join(body)}</tbody></table></div>')
            i = j
            continue
        m = re.match(r"^(-|\d+\.)\s+(.*)$", s)
        if m and not line.startswith(" "):
            flush()
            tag = "ol" if m.group(1)[0].isdigit() else "ul"
            items: list[str] = []
            j = i
            while j < len(lines):
                lm = re.match(r"^(-|\d+\.)\s+(.*)$", lines[j])
                if lm and (lm.group(1)[0].isdigit()) == (tag == "ol"):
                    items.append(inline(lm.group(2)))
                    j += 1
                    subs = []
                    while j < len(lines) and re.match(r"^\s{2,}- ", lines[j]):
                        subs.append(f"<li>{inline(lines[j].strip()[2:])}</li>")
                        j += 1
                    if subs:
                        items[-1] += f"<ul>{''.join(subs)}</ul>"
                elif lines[j].startswith("  ") and lines[j].strip() and items:
                    items[-1] += " " + inline(lines[j].strip())   # a wrapped continuation line
                    j += 1
                else:
                    break
            out.append(f"<{tag}>" + "".join(f"<li>{it}</li>" for it in items) + f"</{tag}>")
            i = j
            continue
        para.append(s)
        i += 1
    flush()
    return "\n".join(out), toc


def guide_html(out: Path, version: str, app: str = "nb", shots: "Shots | None" = None, url: str | None = None,
               og: tuple[Shot, str] | None = None) -> bool:
    """Render the app's guide (docs/USERGUIDE.md, docs/ham/USERGUIDE.md) into
    out/guide.html, its screenshots into out/shots/ (full size, plus an
    inline copy as for the front page). False, and nothing written, when
    the repository has no guide."""
    guide_md = APPS[app]["guide"]
    if not guide_md.exists():
        return False
    shots = shots or Shots(out)

    def image(src: str, alt: str) -> str:
        source = (guide_md.parent / src).resolve()
        if not source.is_file():
            raise SystemExit(f"site-build: {guide_md.name} shows {src}, which does not exist")
        return figure_html(shots.publish(source), re.sub(r"[*`]", "", alt), inline(alt))

    # The page's own header carries the title, so the Markdown's "# ..." line
    # (which a viewer of the .md needs) would only repeat it.
    md = re.sub(r"\A\s*# [^\n]*\n", "", guide_md.read_text(encoding="utf-8"))
    body, toc = render_markdown(md, image)
    nav = "".join(f'<li><a href="#{a}">{inline(t)}</a></li>' for a, t in toc)
    page = (APPS[app]["site"] / "guide.html").read_text()
    url = url or APPS[app]["url"]
    for key, value in {
        "{{HEAD}}": head_html(app, page, url + GUIDE_PAGE, url, og),
        "{{BASE_STYLE}}": _base_style(app),
        "{{VERSION}}": html.escape(version),
        "{{TOC}}": nav,
        "{{GUIDE}}": body,
        "{{BUILT}}": datetime.date.today().isoformat(),
    }.items():
        page = page.replace(key, value)
    dest = out / GUIDE_PAGE
    old = dest.read_text() if dest.exists() else None
    tmp = out / f"{GUIDE_PAGE}.tmp"
    tmp.write_text(page)
    tmp.replace(dest)
    # Not shots/ (copied above) or source/ (rewritten in source_html, and a
    # pointer page, not a page of ours): only the guide itself is a URL.
    sync_page(out / "sitemap.xml", f"/{GUIDE_PAGE}", old, page, APPS[app]["url"])
    return True


def _base_style(app: str = "nb") -> str:
    """The front page's stylesheet, so the guide is styled from the same
    tokens (colours, light/dark, type) rather than a copy that drifts."""
    m = re.search(r"<style>(.*?)</style>", (APPS[app]["site"] / "index.html").read_text(), re.S)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- screenshots
#
# docs/screenshots/*.png stay the source: lossless, what the guide's own
# Markdown shows, and what a re-render replaces. What the site serves is
# made from them here, on every build:
#
# Format. Each image is encoded both as PNG and as JPEG, and the smaller
# is published. The program's main window - waterfall, scope noise,
# gradients - is 3-4x smaller as JPEG; a settings dialog or a welcome page
# is flat colour, where PNG is sometimes smaller and always exact. WebP
# was tried and rejected (06/10/2026): a third smaller again than JPEG,
# but lossy WebP always halves the colour resolution, and on the 1920
# shots that wiped out the one-pixel magenta passband edges on the
# waterfall. JPEG is written with no chroma subsampling (4:4:4) for the
# same reason; quality 85 for the inline copy, which a reader skims, and 90
# for the full-size one, which is opened to read the small print. Both were
# compared against the PNG at 2x zoom on the FT8 and waterfall shots: the
# scale labels, callsigns and the coloured band-plan text stay clean.
#
# Inline copies. A screenshot more than a quarter wider than the inline
# width is resized for the page; anything narrower is shown as itself,
# because shaving 20 pixels off a 980-wide dialog only resampled its
# text, blurred it, and - as PNG - made the "thumbnail" 75% bigger than the
# original (settings-radio.png, the audit of 06/10/2026). And a copy that
# still came out no smaller than the full-size file is not published: the
# page shows the full-size one inline instead.
#
# Names. A published file is named after its own bytes (<name>-<12 hex
# digits of its SHA-256>.jpg), so the site can tell browsers and the CDN
# to keep it for a year (.htaccess) - a re-rendered screenshot is a new
# name, never stale bytes under an old one. The price is that renders
# leave old names behind; Shots.retire moves whatever no page uses any
# more into the archive beside the site, as release.sh does with old
# installers, and lists it for removal from the public host.

INLINE_QUALITY = 85
FULL_QUALITY = 90
INLINE_SLACK = 1.25     # resized only when wider than INLINE_MAX_WIDTH by more than this
SHOT_HASH = 12          # hex digits of the SHA-256 in a published screenshot's name


# A NamedTuple, not a dataclass: the tests load this file by path without
# registering it as a module, and a dataclass needs to find its module.
class Shot(NamedTuple):
    full: str                    # file name in shots/
    full_size: tuple[int, int]
    inline: str                  # the copy the page shows; the same file as full when that is no bigger
    inline_size: tuple[int, int]


def _png_size(data: bytes) -> tuple[int, int] | None:
    """Width/height from a PNG's IHDR chunk, with no dependency beyond the
    bytes themselves - used for the <img width height> that stops the page
    jumping while a screenshot loads, even when Pillow is not there to
    open the image."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def _opaque(im) -> bool:
    """JPEG has no transparency; an image that uses its alpha channel stays
    PNG. smeter-analogue.png is RGBA with every pixel opaque, so it may
    still be a JPEG."""
    if im.mode in ("RGBA", "LA"):
        return im.getchannel("A").getextrema()[0] == 255
    return "transparency" not in im.info


def _smallest(im, quality: int, png: bytes | None = None) -> tuple[bytes, str]:
    """The smaller of a PNG (`png`, if given: the source's own bytes) and a
    4:4:4 JPEG at `quality`, as (bytes, extension)."""
    if png is None:
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        png = buf.getvalue()
    best = (png, "png")
    if _opaque(im):
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=quality, subsampling=0, optimize=True, progressive=True)
        if len(buf.getvalue()) < len(png):
            best = (buf.getvalue(), "jpg")
    return best


class Shots:
    """Every screenshot one build publishes into out/shots/, made once per
    source file however many places show it (the front page and the guide
    share several)."""

    def __init__(self, out: Path):
        self.dir = out / "shots"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.done: dict[Path, Shot] = {}

    def _write(self, stem: str, data: bytes, ext: str) -> str:
        name = f"{stem}-{hashlib.sha256(data).hexdigest()[:SHOT_HASH]}.{ext}"
        dest = self.dir / name
        if not dest.is_file() or dest.read_bytes() != data:
            tmp = self.dir / f"{name}.tmp"
            tmp.write_bytes(data)
            tmp.replace(dest)
        return name

    def publish(self, source: Path) -> Shot:
        source = source.resolve()
        if source in self.done:
            return self.done[source]
        stem, raw = source.stem, source.read_bytes()
        if Image is None:
            print(f"site-build: Pillow is not installed; publishing {source.name} as it is")
            size = _png_size(raw) or (0, 0)
            name = self._write(stem, raw, source.suffix.lstrip(".") or "png")
            shot = Shot(name, size, name, size)
        else:
            with Image.open(source) as im:
                im.load()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if not _opaque(im) else "RGB")
            full_bytes, full_ext = _smallest(im, FULL_QUALITY, raw if source.suffix.lower() == ".png" else None)
            full = self._write(stem, full_bytes, full_ext)
            shot = Shot(full, im.size, full, im.size)
            if im.width > INLINE_MAX_WIDTH * INLINE_SLACK:
                size = (INLINE_MAX_WIDTH, round(im.height * INLINE_MAX_WIDTH / im.width))
                small_bytes, small_ext = _smallest(im.resize(size, Image.LANCZOS), INLINE_QUALITY)
                if len(small_bytes) < len(full_bytes):
                    shot = Shot(full, im.size, self._write(f"sm-{stem}", small_bytes, small_ext), size)
        self.done[source] = shot
        return shot

    def names(self) -> set[str]:
        return {n for s in self.done.values() for n in (s.full, s.inline)}

    def retire(self, archive: Path) -> None:
        """Move every file in shots/ that no page of this build shows into
        archive/shots/ - never deleting, as release.sh never does - and say
        what to remove from the public host, since an upload only adds.
        Files of the same name already archived with the same bytes are
        dropped from the site; with different bytes both are kept and the
        site's copy stays, with a warning."""
        keep = self.names()
        moved = []
        for p in sorted(self.dir.iterdir()):
            if not p.is_file() or p.name in keep:
                continue
            dest = archive / "shots" / p.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if dest.read_bytes() != p.read_bytes():
                    print(f"site-build: {p.name}: {dest.parent} already holds a different file of that name; "
                          f"left on the site", file=sys.stderr)
                    continue
                p.unlink()
            else:
                shutil.move(str(p), dest)
            moved.append(f"shots/{p.name}")
        if moved:
            print(f"moved screenshots no page shows any more into {archive / 'shots'}; remove from the remote site:")
            for m in moved:
                print(f"  {m}")


def figure_html(shot: Shot, alt: str, caption_html: str) -> str:
    """A screenshot as the pages show it: the inline copy, sized so the
    page does not jump as it loads and fetched only as it scrolls into
    view (every screenshot on both pages is below the first screenful),
    linked to the full-size one."""
    full, small = html.escape(shot.full), html.escape(shot.inline)
    w, h = shot.inline_size
    return (f'<figure><a href="shots/{full}"><img src="shots/{small}" width="{w}" height="{h}" '
            f'alt="{html.escape(alt)}" loading="lazy" decoding="async"></a>'
            f'<figcaption>{caption_html} &middot; <a href="shots/{full}">full size</a></figcaption></figure>')


def shots_html(out: Path, app: str = "nb", shots: Shots | None = None) -> str:
    src = APPS[app]["shots_dir"]
    shots = shots or Shots(out)
    figs = []
    for name, caption in APPS[app]["shots"]:
        full_src = src / name
        if not full_src.exists():
            continue
        figs.append(figure_html(shots.publish(full_src), caption, html.escape(caption)))
    # A heading for the outline and for screen readers, which otherwise
    # meet a run of figures with nothing saying what they are; the
    # screenshots say it for everyone else.
    return (f'<section aria-labelledby="screenshots"><h2 id="screenshots" class="vh">Screenshots</h2>'
            f'<div class="grid">{"".join(figs)}</div></section>' if figs else "")


# --------------------------------------------------------------------------- server-level files
#
# The site's .htaccess (redirects, caching, the 404 page; why each, in the
# file) is kept in the repository as site/htaccess and site/ham/htaccess -
# no leading dot, so it is never hidden in a listing and never acts on
# whatever serves a checkout - and written into the folder on every build,
# so the folder's copy is always the repository's. Like robots.txt and
# sitemap.xml, neither it nor 404.html is ever removed by anything here.

def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def not_found_html(app: str, guide: bool, url: str | None = None) -> str:
    """The 404 page: the site's own look and the way back. Apache serves it
    at whatever address was asked for, however deep, so every link and the
    icon are root-relative, and the style is inline. noindex: it is not a
    page of the site."""
    name = html.escape(APPS[app]["name"])
    # Since 0.1.16 the site is a folder of openhamshack.com (/desktop/nb/),
    # not a host of its own, so "root-relative" means the folder's path,
    # taken from the app's address: a bare "/" would now be the OpenHamShack
    # home page, and "/favicon.svg" that site's icon rather than this one's.
    base = html.escape(urlsplit(url or APPS[app]["url"]).path or "/")
    guide_li = f'<li><a href="{base}{GUIDE_PAGE}">The user guide</a></li>' if guide else ""
    return (f'<!doctype html>\n<html lang="en-GB"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="robots" content="noindex">'
            f'<title>Page not found - {name}</title>'
            f'<link rel="icon" href="{base}favicon.svg" type="image/svg+xml">'
            f'<style>{_base_style(app)}</style></head>'
            f'<body><div class="wrap"><header><h1>Page not found</h1>'
            f'<p class="lede">Nothing is published at this address on the {name} site. The link may be '
            f'mistyped, or it may be to something the site no longer offers: each site keeps only its '
            f'newest Windows installer, and the source code has moved to its own site.</p></header>'
            f'<section class="card"><h2>Where to go instead</h2><ul class="features">'
            f'<li><a href="{base}">{name}</a>: the newest download, its status and release notes</li>{guide_li}'
            f'<li><a href="{html.escape(source_url(app))}">Source code</a>, for every release</li>'
            f'<li><a href="https://openhamshack.com/">openhamshack.com</a> and the other OpenHamShack '
            f'programs</li></ul></section>'
            f'<footer><p>{name} - free software under the GNU GPL, version 3 or later.</p></footer>'
            f'</div></body></html>\n')


def server_files(out: Path, app: str, guide: bool, url: str | None = None) -> None:
    htaccess = APPS[app]["site"] / "htaccess"
    if htaccess.is_file():
        _write_atomic(out / ".htaccess", htaccess.read_text(encoding="utf-8"))
    _write_atomic(out / "404.html", not_found_html(app, guide, url))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", choices=sorted(APPS), default="nb", help="which program's site (default nb)")
    ap.add_argument("--out", help="the release folder (default: the app's, e.g. /srv/openhamshack-nb-releases)")
    ap.add_argument("--url", help="the site's public address (default: the app's)")
    ap.add_argument("--archive", help="where files leaving the site go (default: the release folder's name "
                                      "plus -archive, as for tools/release.sh)")
    a = ap.parse_args()
    app = APPS[a.app]
    out = Path(a.out or app["out"])
    out.mkdir(parents=True, exist_ok=True)
    archive = Path(a.archive or f"{str(out).rstrip('/')}-archive")
    url = a.url or app["url"]
    url = url if url.endswith("/") else url + "/"
    released = deb_version(out, names(a.app))
    version = released or "unreleased"
    shots = Shots(out)
    og = og_shot(a.app, shots)
    guide = guide_html(out, version, a.app, shots, url, og)
    page = (app["site"] / "index.html").read_text()
    jsonld = software_jsonld(out, a.app, url, released, page_meta(page)[1], og, guide)
    for key, value in {
        "{{HEAD}}": head_html(a.app, page, url, url, og, jsonld),
        "{{VERSION}}": html.escape(version),
        "{{SITE_URL}}": html.escape(url),
        "{{GUIDE_NAV}}": (f'<p class="guide-nav"><a class="btn" href="{GUIDE_PAGE}">User guide</a>'
                          f'<span class="meta">installing, first run, every control, transmitting safely, '
                          f'troubleshooting</span></p>' if guide else ""),
        "{{GUIDE_LINK}}": (f'<a class="btn ghost" href="{GUIDE_PAGE}">Read the user guide</a>' if guide else ""),
        "{{DOWNLOAD}}": download_html(out, guide, a.app),
        "{{SHOTS}}": shots_html(out, a.app, shots),
        "{{NOTES}}": notes_html(releases(a.app)),
        "{{BUILT}}": datetime.date.today().isoformat(),
    }.items():
        page = page.replace(key, value)
    favicon = app["site"] / "favicon.svg"
    if favicon.exists():
        shutil.copy2(favicon, out / "favicon.svg")
    server_files(out, a.app, guide, url)
    dest = out / "index.html"
    old = dest.read_text() if dest.exists() else None
    tmp = out / "index.html.tmp"
    tmp.write_text(page)
    tmp.replace(dest)
    sync_page(out / "sitemap.xml", "/", old, page, app["url"])
    # Only once both pages are written: until then the old ones still
    # name the old files.
    shots.retire(archive)
    print(f"site built in {out} for {version}" + (" (with the user guide)" if guide else ""))


if __name__ == "__main__":
    main()
