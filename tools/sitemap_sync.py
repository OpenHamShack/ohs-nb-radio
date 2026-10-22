#!/usr/bin/env python3
"""Keep a release folder's sitemap.xml current with the pages
tools/site-build.py and tools/source-site.py actually write.

Another session added sitemap.xml and robots.txt to each site folder
(/srv/openhamshack-nb-releases, /srv/openhamshack-ham-releases, /srv/source-site) on
06/10/2026; creating and placing them is that session's concern, not this
one's. What is this one's concern - agreed afterwards - is that a page's
<lastmod> moves to today when the page it describes actually changes, that
a page which is new to the site gets a <url> entry at all, and that an
untouched page or an entry neither tool wrote keeps exactly what it had.
Shared by both tools (imported by file path, as tools/make-ico.py and
tools/tone-test.py already reach into the parent package) rather than
written twice, since the rule is the one thing both sites must agree on -
two copies would drift the day only one of them was changed for a fix.

Hand-rolled text editing, not xml.etree: parsing a sitemap into a tree and
writing it back out would reformat whatever the other session's generator
produced - attribute order, quoting, whether a line is one element or
several - none of which this module has any business changing. A
<url>...</url> element, in the one-line-per-entry form the example sitemap
uses, is simple enough that splicing in a replacement for just its
<lastmod>, or a whole new element before </urlset>, leaves every byte this
module was not asked to touch exactly as it was.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

_URL_ELEM = re.compile(r"<url>.*?</url>", re.S)
_LOC = re.compile(r"<loc>(.*?)</loc>", re.S)
_LASTMOD = re.compile(r"<lastmod>.*?</lastmod>", re.S)
_FIRST_URL_INDENT = re.compile(r"(?m)^([ \t]*)<url>")


def _today() -> str:
    """UTC, not the build host's local date: a release cut just either
    side of midnight must log the same day a browser in another timezone
    would compute from the same instant."""
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _base_of(text: str) -> str | None:
    """scheme://host/ from the sitemap's first <loc> - the one thing in the
    file guaranteed to already be the site's real address, since the other
    session wrote it from that address and nothing here ever did."""
    m = _LOC.search(text)
    if not m:
        return None
    parts = urlsplit(m.group(1).strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/"


def sync_page(sitemap: Path, url_path: str, old_text: str | None, new_text: str, fallback_base: str) -> None:
    """Note that the page at `url_path` (e.g. "/" for index.html, "/guide.html")
    now reads `new_text`, having read `old_text` before this run (None: the
    page did not exist). Does nothing if `sitemap` does not exist - this
    module never creates one - and nothing to an entry whose page's bytes
    are unchanged, so a run that changes nothing on a page does not bump
    its date anyway. `fallback_base` (the tool's own known public URL) is
    used only if the sitemap has no <loc> of its own to read a base from,
    which a sitemap with at least a home entry never should.
    """
    if not sitemap.is_file():
        return
    changed = old_text != new_text
    text = sitemap.read_text(encoding="utf-8")
    base = _base_of(text) or fallback_base
    # A site in a folder of another (the source archive at
    # openhamshack.com/source/ since 12/10/2026): the first <loc> names only
    # the host, but the tool's own address carries the folder too, and a
    # sitemap already written for that address is the proof it is the right
    # one. Without this, "/" meant the host's home page, not the archive's.
    first = _LOC.search(text)
    if first and first.group(1).strip().startswith(fallback_base):
        base = fallback_base
    target_path = urlsplit(urljoin(base, url_path.lstrip("/"))).path or "/"

    for m in _URL_ELEM.finditer(text):
        loc = _LOC.search(m.group(0))
        if not loc or (urlsplit(loc.group(1).strip()).path or "/") != target_path:
            continue
        if not changed:
            return  # listed already, and still correct: touch nothing
        elem = m.group(0)
        stamped = f"<lastmod>{_today()}</lastmod>"
        updated = _LASTMOD.sub(stamped, elem, count=1) if _LASTMOD.search(elem) \
            else elem.replace("</url>", f"{stamped}</url>", 1)
        if updated != elem:
            _write_atomic(sitemap, text[:m.start()] + updated + text[m.end():])
        return

    # Not listed yet, changed or not ("Add a <url> entry if the page isn't
    # listed" has no condition on change): add it just inside </urlset>,
    # after whatever is already there - never reordering, never guessing
    # where among the existing entries a new one belongs.
    close = text.find("</urlset>")
    if close == -1:
        return  # not a shape this module recognises; leave it rather than guess
    indent_m = _FIRST_URL_INDENT.search(text)
    indent = indent_m.group(1) if indent_m else "  "
    full_url = urljoin(base, url_path.lstrip("/"))
    line = f"{indent}<url><loc>{full_url}</loc><lastmod>{_today()}</lastmod></url>\n"
    _write_atomic(sitemap, text[:close] + line + text[close:])


def _write_atomic(path: Path, text: str) -> None:
    """Whole, then moved into place - the same reason release.sh's own
    writes are atomic: a reader must never see a half-written sitemap."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
