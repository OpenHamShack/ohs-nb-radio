"""A multimedia-beacon bulletin made fit to read: its title, and its body as
safe HTML or as the plain text it was.

What the beacon sends (AMSAT-DL's HSmodem bulletins, seen on the Mac test
of 17/10/2026): a header line "~<kind>:<number>:<id or title>~", then
either plain text or HTML pasted from an e-mail - AMSAT News Service's
ANS-249 came as <h3> and <p style> with Word's <o:p></o:p> and
font-family &quot;Georgia&quot; spans, "~B:5:249~" before it; the QO-100
DX Club's news as "~D:0:QO-100 DX Club News~" and <h1><a href>. NB showed
all of it as text, tags and entities included.

parse() makes a Bulletin of it; clean_html() takes the HTML down to what a
reader needs: structure, emphasis and links. Dropped are the things that
fetch or run (img, script, style, link, iframe...), Office's namespaced
tags, and every inline style, colour and font, so the theme's own text
colour holds - ANS's #1a639b headings are unreadable on the dark theme.
Never imports Qt (ohsnb/ui/mmbview.py shows the result); the window's
browser refuses any resource besides, in case something gets through.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import PurePath

_HEADER = re.compile(r"\A\s*~([A-Za-z]):(\d+):([^~\r\n]*)~[ \t]*\r?\n?")
# Enough to tell a bulletin written in HTML from one in plain text, where a
# stray "<" (an e-mail address, "<3 dB") must not count.
_LOOKS_HTML = re.compile(r"<\s*(p|br|h[1-6]|span|div|a\s|b|i|u|em|strong|hr|ul|ol|li|table|tr|td|font|html|body)"
                         r"\b[^>]*>", re.I)
# Elements that are removed with everything inside them.
_DROP_WHOLE = re.compile(r"<\s*(script|style|head|title|iframe|object|embed|svg|math|template|noscript)\b.*?"
                         r"<\s*/\s*\1\s*>", re.I | re.S)
# Tags that are removed alone: they fetch something or carry nothing a
# reader sees. Office's namespaced tags (<o:p>, <v:shape>...) too.
_DROP_TAG = re.compile(r"<\s*/?\s*(link|meta|base|img|image|input|button|form|frame|frameset|audio|video|source|"
                       r"track|picture|font|[a-z]+:[a-z0-9_-]+)\b[^>]*>", re.I)
_COMMENT = re.compile(r"<!--.*?-->|<!\[if.*?<!\[endif\]>|<!doctype[^>]*>|<\?xml[^>]*>", re.I | re.S)
# Attributes kept on the tags that remain: a link's address, and a table
# cell's spans. Everything else (style, class, color, face, on*, target...)
# goes.
_KEEP_ATTR = {"href", "colspan", "rowspan"}
_TAG = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*?)?\s*(/?)\s*>")
_ATTR = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*(?:=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")
_SAFE_LINK = re.compile(r"\A(https?:|mailto:)", re.I)


@dataclass
class Bulletin:
    title: str          # "Bulletin 5 - ANS-249", "QO-100 DX Club News", or "" with no header
    body: str           # the text after the header: cleaned HTML when is_html, else as sent
    is_html: bool


def _title(m: re.Match | None, name: str) -> str:
    if m is None:
        return ""
    number, ident = m.group(2), html.unescape(m.group(3).strip())
    if ident and not ident.isdigit():
        return ident
    # A number for an id: the file's name says more ("ANS-249" for 249),
    # and is what the operator saw in the list until now.
    label = (PurePath(name).stem if name else "") or ident
    return f"Bulletin {number} – {label}" if label else f"Bulletin {number}"


def title_of(text: str, name: str = "") -> str:
    """parse(text, name).title, without cleaning the body: for a list."""
    return _title(_HEADER.match(text), name)


def parse(text: str, name: str = "") -> Bulletin:
    """The bulletin `text` (as sent, header and all) received as file `name`."""
    m = _HEADER.match(text)
    title = _title(m, name)
    if m:
        text = text[m.end():]
    if _LOOKS_HTML.search(text):
        return Bulletin(title, clean_html(text), True)
    return Bulletin(title, text, False)


def clean_html(src: str) -> str:
    """`src` with only what a reader needs left (module docstring)."""
    s = _COMMENT.sub("", src)
    s = _DROP_WHOLE.sub("", s)
    s = _DROP_TAG.sub("", s)

    def tag(m: re.Match) -> str:
        name, attrs, close = m.group(1).lower(), m.group(2) or "", m.group(3)
        kept = []
        for am in _ATTR.finditer(attrs):
            key = am.group(1).lower()
            if key not in _KEEP_ATTR or am.group(2) is None:
                continue
            value = html.unescape(am.group(2).strip("\"'")).strip()
            if key == "href" and not _SAFE_LINK.match(value):
                continue
            kept.append(f'{key}="{html.escape(value, quote=True)}"')
        return "<" + " ".join([name, *kept]) + (" /" if close else "") + ">"
    s = _TAG.sub(tag, s)
    # Office leaves empty paragraphs where its <o:p> was.
    s = re.sub(r"<p>\s*</p>", "", s)
    return s.strip()


def under_title(body: str) -> str:
    """`body`'s headings one level down (h1 becomes h2...), for showing it
    under its title as an h1: the QO-100 DX Club's news is all h1s, which
    drew each item larger than the bulletin's own name."""
    return re.sub(r"<(/?)h([1-5])\b", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", body, flags=re.I)
