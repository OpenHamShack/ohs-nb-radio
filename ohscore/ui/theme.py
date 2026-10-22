"""The look: colour tokens, the spacing scale, fonts and the animation timing.

Everything that paints asks this module for colours by *meaning* (rx, tx,
lockOk, segment kind...) rather than by value, so the light theme is one more
dict and not a hunt through every paintEvent. The stock widgets that remain
(line edits, combo boxes, tables, scroll bars) are styled from the same tokens
by `stylesheet()`.

Fonts: the machine may be offline and must not be sent fetching anything, so
the families are chosen from what Debian and Raspberry Pi OS install, best
first, and the first one present wins. Figures that change while the
operator watches (the frequency, meter values) are drawn digit-by-digit in
fixed cells by the widgets themselves, so a sans with proportional figures
still never makes a number jitter sideways.

Text size (Settings › Display, 100/115/130 %): set_scale() once at start and
on a change, before the window is built or rebuilt. font() multiplies every
size by it, px() scales a fixed pixel size (a widget's height, a column)
the same way, and stylesheet() scales the stock widgets' text. A widget
that fixes its own pixel height is converted to px() by whoever next owns
its file; until then it keeps its height at any scale.
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve
from PyQt6.QtGui import QColor, QFont, QFontDatabase

from .layoutrules import nearest_scale

# Spacing scale (px). Every gap and padding in the UI is one of these; that is
# most of what makes a dense screen look calm rather than busy.
S1, S2, S3, S4, S5, S6 = 4, 8, 12, 16, 24, 32
RADIUS = 8          # cards
RADIUS_SM = 6       # controls, chips

# One animation language: state changes ease out over ~180 ms; nothing loops
# except things that are genuinely in progress (a lock searching, TX on air).
ANIM_MS = 180
EASE = QEasingCurve.Type.OutCubic

DARK = {
    "name": "dark",
    "bg0": "#0a0d12",        # window
    "bg1": "#10141b",        # cards
    "bg2": "#171c25",        # inputs, raised
    "bg3": "#1f2531",        # hover
    "scope": "#06080c",      # behind the spectrum
    "line": "#232a36",       # hairlines
    "line2": "#2f3846",      # stronger hairlines, grid majors
    "grid": "#141a23",       # scope grid
    "text": "#e8edf4",
    "text2": "#a3adbb",
    # #667284 until October 2026: 3.5:1 on bg2, under WCAG AA's 4.5:1 for
    # small text, and most small text is this colour (section labels,
    # units, hints). test_ui_foundations holds every text token to 4.5:1.
    "text3": "#8590a1",
    "accent": "#4fd1e8",     # the one accent: focus, selection, RX
    "accentText": "#041016",
    "rx": "#4fd1e8",
    "tx": "#ff4d5e",
    "txGlow": "#ff2e45",
    "ok": "#3ddc84",
    "warn": "#ffb547",
    "err": "#ff5d6c",
    "beacon": "#c39bff",
    "own": "#ffd166",        # where our own signal actually landed
    "cq": "#3ddc84",
    # "mine" is WSJT-X's pink-red for a message to us. Red is kept for being
    # on the air (overhaul decision 8), so such messages turn gold: toYou,
    # which the decode list and the scope labels move to (WP4, WP7); mine
    # stays until nothing reads it.
    "mine": "#ff8fa3",
    "toYou": "#f5c451",
    "worked": "#8590a1",
    # REC in the status strip and on the pad (amber, not red: decision 7),
    # and a ceiling mark such as the power slider's limit.
    "rec": "#ffb547",
    "limit": "#ffb547",
    "segCw": "#5b8def",
    "segNarrow": "#22b5a6",
    "segDigi": "#38c98d",
    "segSsb": "#d9a84e",
    "segBeacon": "#a77bf3",
    "segEmerg": "#ff7a59",
    "segMixed": "#8592a8",
    "segNone": "#4a5260",
    "trace": "#cfe9ff",
    "peak": "#7f93ad",
    "shadow": "#000000",
}

LIGHT = {
    "name": "light",
    "bg0": "#eef1f5",
    "bg1": "#ffffff",
    "bg2": "#f3f5f8",
    "bg3": "#e6eaf0",
    "scope": "#0b0f15",      # scopes stay dark: a waterfall on white is unreadable
    "line": "#dde2e9",
    "line2": "#c7ced8",
    "grid": "#161d27",
    "text": "#0f1722",
    "text2": "#4a5566",
    # Every colour below that is also written as text is darkened from its
    # first value (in brackets) to reach 4.5:1 on bg0, the darkest of the
    # light backgrounds: at 2.4-3.9:1 the light theme's grey labels, amber
    # warnings and green "ok"s were hard to read (October 2026). Each keeps
    # its hue, so a fill still reads as the same colour, only deeper.
    "text3": "#5f6b7c",      # (#8592a3)
    "accent": "#087691",     # (#0a8fb0)
    "accentText": "#ffffff",
    "rx": "#087691",         # (#0a8fb0)
    "tx": "#d02437",         # (#e5283c)
    "txGlow": "#ff2e45",
    "ok": "#0e7c44",         # (#12a35a)
    "warn": "#976000",       # (#d98a00)
    "err": "#cd2c3a",        # (#e0303f)
    "beacon": "#7a51da",     # (#8a5cf6)
    "own": "#8e6500",        # (#d99a00)
    "cq": "#0e7c44",         # (#12a35a)
    "mine": "#c13a5b",       # (#e0446a)
    "toYou": "#886800",
    "worked": "#5f6b7c",     # (#8592a3)
    "rec": "#976000",
    "limit": "#976000",
    "segCw": "#3f74e0",
    "segNarrow": "#14998c",
    "segDigi": "#20a872",
    "segSsb": "#c08a28",
    "segBeacon": "#8a5cf6",
    "segEmerg": "#ea5a35",
    "segMixed": "#6b7891",
    "segNone": "#9aa3b0",
    "trace": "#cfe9ff",
    "peak": "#7f93ad",
    "shadow": "#1a2230",
}

# Colours drawn *inside* the scopes always come from the dark set, because the
# scope background is dark in both themes.
SCOPE_KEYS = ("rx", "tx", "ok", "warn", "beacon", "own", "trace", "peak", "cq", "mine", "toYou")

# The tokens anything writes text in. Each must reach WCAG AA (4.5:1) on
# bg0, bg1 and bg2 in both themes, and a SCOPE_KEYS one on the scope's
# background (tests/test_ui_foundations.py computes the ratios from these
# dicts, so a later colour edit cannot slip under).
TEXT_TOKENS = ("text", "text2", "text3", "accent", "rx", "tx", "ok", "warn", "err", "beacon", "own", "cq", "mine",
               "toYou", "worked", "rec", "limit")

_current = DARK


def set_theme(name: str) -> dict:
    global _current
    _current = LIGHT if name == "light" else DARK
    return _current


def t() -> dict:
    return _current


def c(key: str, alpha: float | None = None) -> QColor:
    col = QColor(_current[key])
    if alpha is not None:
        col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def sc(key: str, alpha: float | None = None) -> QColor:
    """A colour for use on a scope (always dark-backed)."""
    col = QColor(DARK[key]) if key in SCOPE_KEYS else QColor(_current[key])
    if alpha is not None:
        col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def segment_colour_key(label: str, modes) -> str:
    """Bandplan segment -> colour token, by what the segment is for."""
    lab = label.lower()
    if "beacon" in lab:
        return "segBeacon"
    if modes is None or not modes:
        return "segNone"
    if "emergency" in lab:
        return "segEmerg"
    if "cw" in lab:
        return "segCw"
    if "narrow" in lab:
        return "segNarrow"
    if "digi" in lab:
        return "segDigi"
    if "ssb" in lab:
        return "segSsb"
    return "segMixed"


# ---------------------------------------------------------------- fonts
SANS = ["Inter", "Cantarell", "Noto Sans", "Lato", "Piboto", "Ubuntu", "Roboto", "DejaVu Sans", "Liberation Sans"]
MONO = ["JetBrains Mono", "Fira Mono", "Noto Sans Mono", "Ubuntu Mono", "DejaVu Sans Mono", "Liberation Mono",
        "Monospace"]
_families: dict[str, str] = {}


def _pick(cands: list[str], key: str) -> str:
    if key not in _families:
        have = set(QFontDatabase.families())
        _families[key] = next((f for f in cands if f in have), cands[-1])
    return _families[key]


def sans_family() -> str:
    return _pick(SANS, "sans")


def mono_family() -> str:
    return _pick(MONO, "mono")


_scale = 1.0


def set_scale(scale: float) -> float:
    """Set the text scale (snapped to a Settings step) for every font and
    px() from now on; returns it. Widgets built before keep their sizes,
    so a change is followed by the window's rebuild (BaseWindow.set_theme)."""
    global _scale
    _scale = nearest_scale(scale)
    return _scale


def scale() -> float:
    return _scale


def px(n: float) -> int:
    """A fixed pixel size (a height, a width, a margin) at the text scale."""
    return int(round(n * _scale))


def font(px: float, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False, spacing: float = 0.0) -> QFont:
    """`px` is the size at 100 % text; the font is made at the text scale."""
    f = QFont(mono_family() if mono else sans_family())
    f.setPixelSize(max(6, int(round(px * _scale))))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def caps(px: float = 10.5) -> QFont:
    """Small spaced capitals for section labels."""
    f = font(px, QFont.Weight.DemiBold, spacing=1.1)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    return f


# ---------------------------------------------------------------- stock widgets
def app_font():
    """The application font. Set with QApplication.setFont, not in the style
    sheet: a font in a style sheet overrides every widget's own setFont."""
    return font(13)


def stylesheet(scale: float | None = None) -> str:
    """The stock widgets' style at text `scale` (the current one if None)."""
    k = _current
    fs = int(round(13 * (_scale if scale is None else scale)))
    return f"""
    QWidget {{ color: {k['text']}; }}
    QMainWindow, QDialog, #Root {{ background: {k['bg0']}; }}
    QToolTip {{ background: {k['bg2']}; color: {k['text']}; border: 1px solid {k['line2']};
               padding: 6px 8px; border-radius: 6px; }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {k['bg2']}; border: 1px solid {k['line']}; border-radius: {RADIUS_SM}px;
        padding: 5px 8px; selection-background-color: {k['accent']}; selection-color: {k['accentText']}; }}
    QPlainTextEdit, QTextEdit {{ padding: 6px; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QComboBox:focus {{ border: 1px solid {k['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {k['text3']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {k['bg2']}; border: 1px solid {k['line2']};
        selection-background-color: {k['bg3']}; selection-color: {k['text']}; outline: none; padding: 4px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0; border: none; }}
    QTableView, QTableWidget, QListWidget, QTreeView {{ background: {k['bg1']}; border: none;
        alternate-background-color: {k['bg2']}; gridline-color: transparent; outline: none;
        selection-background-color: {k['bg3']}; selection-color: {k['text']}; }}
    QTableView::item, QTableWidget::item {{ padding: 0 6px; }}
    QHeaderView::section {{ background: {k['bg1']}; color: {k['text3']}; border: none;
        border-bottom: 1px solid {k['line']}; padding: 6px; font-size: {int(fs * 0.85)}px;
        font-weight: 600; text-transform: uppercase; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {k['line2']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {k['text3']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {k['line2']}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: {k['bg0']}; }}
    QSplitter::handle:hover {{ background: {k['line']}; }}
    QMenuBar {{ background: {k['bg0']}; color: {k['text2']}; }}
    QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 4px; }}
    QMenuBar::item:selected {{ background: {k['bg2']}; color: {k['text']}; }}
    QMenu {{ background: {k['bg1']}; border: 1px solid {k['line2']}; padding: 6px; border-radius: 8px; }}
    QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {k['bg3']}; }}
    QMenu::separator {{ height: 1px; background: {k['line']}; margin: 5px 8px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {k['line2']};
        background: {k['bg2']}; }}
    QCheckBox::indicator:checked {{ background: {k['accent']}; border-color: {k['accent']}; }}
    QCheckBox::indicator:focus {{ border-color: {k['accent']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QStackedWidget {{ background: transparent; }}
    QLabel#Muted {{ color: {k['text2']}; }}
    QLabel#Faint {{ color: {k['text3']}; }}
    """
