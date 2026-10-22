"""Where everything on the "?" sheet goes (ohscore/ui/chrome.py
ShortcutOverlay), measured rather than assumed.

The sheet was drawn on a fixed 1100 x 520 card in three columns, the key
column 138 px wide and every row 27 px, whatever the text. At 130 % text,
in a longer language or once the mode menu and the workspace keys were
added, it ran off the bottom of the card and the descriptions over the
column beside them (Mac test FINDINGS 13). Now each piece of text is
measured in the font it is drawn in; a description wraps inside its column;
the sections are shared out over three or four columns, in reading order,
so the tallest is as short as it can be; and if the sheet still does not
fit the window, everything is drawn a step smaller until it does. A test
lays it out at every text size, in both apps, in the pseudo-language, at
the smallest window, and checks that no text leaves its box.

No painting here: plan() is what ShortcutOverlay.paintEvent draws and
what the test reads.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from PyQt6.QtCore import QCoreApplication, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetricsF

from . import theme

# Steps the whole sheet is drawn smaller by, largest first, until it fits.
FACTORS = (1.0, 0.93, 0.86, 0.8, 0.74, 0.68, 0.62)
COLUMN_CHOICES = (3, 4)
WRAP = Qt.TextFlag.TextWordWrap.value


def translated(text: str) -> str:
    """What the sheet says for one of the apps' SHORTCUTS strings: marked
    for the catalog with QT_TRANSLATE_NOOP("Shortcuts", ...) where the list
    is written, translated here as it is drawn."""
    return QCoreApplication.translate("Shortcuts", text)


@dataclass
class Item:
    kind: str           # "title", "hint", "heading", "key" or "what"
    rect: QRectF
    text: str
    font: QFont
    flags: int = 0


@dataclass
class Plan:
    card: QRectF
    factor: float
    columns: int
    fits: bool
    items: list[Item] = field(default_factory=list)


def _fonts(f: float) -> dict:
    return {"title": theme.font(20 * f, QFont.Weight.Bold), "hint": theme.font(12 * f),
            "heading": theme.caps(10.5 * f), "key": theme.font(12 * f, QFont.Weight.DemiBold, mono=True),
            "what": theme.font(13 * f)}


def _split(heights: list[float], cols: int) -> list[list[int]]:
    """The sections (by index, in order) shared over `cols` columns so the
    tallest column is as short as it can be. At most five sections and
    four columns: every split is tried."""
    n = len(heights)
    cols = min(cols, n)
    best, best_h = None, None
    for cuts in itertools.combinations(range(1, n), cols - 1):
        bounds = (0, *cuts, n)
        groups = [list(range(bounds[i], bounds[i + 1])) for i in range(cols)]
        h = max(sum(heights[i] for i in g) for g in groups)
        if best_h is None or h < best_h:
            best, best_h = groups, h
    return best or [list(range(n))]


def _flow(entries: list, cols: int) -> list[list]:
    """`entries` ((kind, data, height) in reading order) poured into at
    most `cols` columns as evenly as they go: the least column height that
    holds them all, found by halving. A column never ends on a heading
    (it moves to the next, with its rows) nor starts with a section's gap."""
    def pour(limit: float) -> list[list] | None:
        runs, cur, h = [], [], 0.0
        for e in entries:
            if cur and h + e[2] > limit and e[0] != "gap":
                if cur[-1][0] == "heading":
                    moved = [cur.pop()]
                else:
                    moved = []
                runs.append(cur)
                cur, h = moved, sum(m[2] for m in moved)
            if e[0] == "gap" and not cur:
                continue
            cur.append(e)
            h += e[2]
        if cur:
            runs.append(cur)
        return runs if len(runs) <= cols else None

    lo = max(e[2] for e in entries)
    hi = sum(e[2] for e in entries)
    best = pour(hi)
    for _ in range(30):
        mid = (lo + hi) / 2
        got = pour(mid)
        if got is None:
            lo = mid
        else:
            best, hi = got, mid
    return best


def plan(sections, width: float, height: float) -> Plan:
    """The sheet for `sections` (an app's SHORTCUTS: [(title, [(keys,
    what), ...])]) over a window `width` x `height`."""
    last = None
    for f in FACTORS:
        # Whole sections first, which reads best; then a long section may
        # run on into the next column, before anything is made smaller.
        for whole in (True, False):
            for cols in COLUMN_CHOICES:
                p = _try(sections, width, height, f, cols, split_sections=whole)
                if p is not None and p.fits:
                    return p
                last = p or last
    return last if last is not None else _try(sections, width, height, FACTORS[-1], COLUMN_CHOICES[-1], force=True)


def _try(sections, width: float, height: float, f: float, cols: int, force: bool = False,
         split_sections: bool = True) -> Plan | None:
    fonts = _fonts(f)
    margin_x = min(theme.px(40), width * 0.04)
    margin_y = min(theme.px(30), height * 0.04)
    pad = theme.px(32) * f
    gap = theme.px(28) * f
    card_w = min(theme.px(1180), width - 2 * margin_x)
    inner = card_w - 2 * pad
    colw = (inner - (cols - 1) * gap) / cols
    if colw < theme.px(170) * f and not force:
        return None
    key_fm = QFontMetricsF(fonts["key"])
    what_fm = QFontMetricsF(fonts["what"])
    head_fm = QFontMetricsF(fonts["heading"])
    key_pad = theme.px(14) * f
    key_h = key_fm.height() + theme.px(8) * f
    # One key column for every section, so the sheet reads as a table:
    # as wide as the widest key, but never more than 45 % of a column.
    keys_w = max(key_fm.horizontalAdvance(k) for _t, rows in sections for k, _w in rows) + key_pad
    key_col = min(keys_w, colw * 0.45) + theme.px(10) * f
    what_w = colw - key_col
    row_gap = theme.px(5) * f
    head_h = head_fm.height() + theme.px(6) * f
    sec_gap = theme.px(14) * f
    fits = True
    measured = []           # per section: (title, [(key, kw, what, wh)], height)
    for title, rows in sections:
        out = []
        h = head_h
        for k, what in rows:
            kw = key_fm.horizontalAdvance(k) + key_pad
            if kw > key_col:
                fits = False
            text = translated(what)
            br = what_fm.boundingRect(QRectF(0, 0, what_w, 10_000), WRAP, text)
            if br.width() > what_w + 0.5:
                fits = False            # one word longer than the column
            # The description's first line level with the key's text.
            off = max(0.0, (key_h - what_fm.height()) / 2)
            rh = max(key_h, off + br.height())
            out.append((k, kw, text, off, br.height(), rh))
            h += rh + row_gap
        measured.append((translated(title), out, h))
    heights = [m[2] + sec_gap for m in measured]
    # Entries in reading order: a section's heading, its rows, the gap
    # after it; each column is a run of them.
    entries = []
    for i, (title, rows, _h) in enumerate(measured):
        entries.append(("heading", title, head_h))
        entries += [("row", r, r[5] + row_gap) for r in rows]
        entries.append(("gap", None, sec_gap))
    if split_sections:
        runs, at = [], 0
        for g in _split(heights, cols):
            n = sum(len(measured[i][1]) + 2 for i in g)
            runs.append(entries[at:at + n])
            at += n
    else:
        runs = _flow(entries, cols)
    body_h = max(sum(e[2] for e in run) - (sec_gap if run[-1][0] == "gap" else 0.0) for run in runs if run)
    title_h = QFontMetricsF(fonts["title"]).height() + theme.px(24) * f
    card_h = pad * 0.7 + title_h + body_h + pad * 0.7
    if card_h > height - 2 * margin_y:
        fits = False
    card_h = min(card_h, max(0.0, height - 2 * margin_y))
    card = QRectF((width - card_w) / 2, (height - card_h) / 2, card_w, card_h)
    p = Plan(card, f, cols, fits)
    top = card.y() + pad * 0.7
    title_rect = QRectF(card.x() + pad, top, inner, title_h - theme.px(24) * f)
    p.items.append(Item("title", title_rect,
                        QCoreApplication.translate("ShortcutOverlay", "Keyboard shortcuts"), fonts["title"],
                        Qt.AlignmentFlag.AlignVCenter.value))
    hint = QCoreApplication.translate("ShortcutOverlay", "any key closes")
    hint_w = QFontMetricsF(fonts["hint"]).horizontalAdvance(hint) + 2
    p.items.append(Item("hint", QRectF(title_rect.right() - hint_w, top, hint_w, title_rect.height()), hint,
                        fonts["hint"], (Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight).value))
    if QFontMetricsF(fonts["title"]).horizontalAdvance(p.items[0].text) + hint_w + theme.px(16) > inner:
        p.fits = False
    y0 = top + title_h
    for c, run in enumerate(runs):
        x = card.x() + pad + c * (colw + gap)
        y = y0
        for kind, data, h in run:
            if kind == "heading":
                p.items.append(Item("heading", QRectF(x, y, colw, head_fm.height()), data, fonts["heading"],
                                    Qt.AlignmentFlag.AlignVCenter.value))
                if head_fm.horizontalAdvance(data) > colw:
                    p.fits = False
            elif kind == "row":
                k, kw, text, off, th, _rh = data
                p.items.append(Item("key", QRectF(x, y, min(kw, key_col), key_h), k, fonts["key"],
                                    Qt.AlignmentFlag.AlignCenter.value))
                p.items.append(Item("what", QRectF(x + key_col, y + off, what_w, th), text, fonts["what"],
                                    (Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft).value | WRAP))
            y += h
    return p
