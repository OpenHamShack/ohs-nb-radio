"""The rail's Mode card and the mode menus.

ModeGrid and ModeCell moved here from ohscore/ui/rail.py (which re-exports
them) when the UI overhaul (docs/ui-overhaul-2026-10.md, section 5.1)
grouped the modes - Voice, Digital, Pictures & data (ohscore/modegroups.py)
- and gave the card two forms:

- **full** (a roomy rail): a small heading per group and the group's
  buttons under it, always in the same order, so a button stays where the
  operator's hand learnt it (decision 3). The current group's heading is
  in the accent colour.
- **compact** (Watch's slim rail, the Compact tier): one button per group
  showing that group's most recent mode. A click selects it; the arrow at
  its right end opens the group's menu. "Recent first" lives here, where
  there is no room for every button, and in the Ctrl + E menu, never in the
  full grid: buttons that reorder themselves are buttons nobody can find.

Every mode label fits its button at every text size (Brian, 17/10/2026:
"HSmodem" was clipped at both ends on a Mac at 1920 x 1080 in its bold,
selected state). A button's least width is its label measured in the
font it is painted in, never a fixed number, and the full form puts as
many buttons in a row as fit at that width (four at most): at 130 % text,
or in a narrow rail, a group takes another row rather than cutting a name.

The Ctrl + E menu (ModeGrid.menu, also ModeMenuButton's on the Tight tier's
tab row) lists the recent modes first, then every group under its name,
and takes type-ahead: "q" goes to Q65, "psk1" to PSK125, "h" to HSmodem.
Before it, Q65, JS8, PSK63, PSK125 and HSmodem had no key at all (Mac test
FINDINGS 13): Ctrl + 1 ... 0 are ten keys for fifteen modes.

KG-STV's button (NB) is not a mode: KG-STV is received in the background
and sent as an over from Beacon › KG-STV (decision 4). It is an over
button (modegroups.OVER_BUTTONS): a press emits `over_picked`, never
`picked`, so nothing here can change the rail's mode under a picture
going out. The app adds it with attach().

The window makes the card without the app's preferences (ohscore/ui/
window.py), so attach() is how the app gives it them: the recent modes
are kept in ui.json `modeRecent`, and survive a theme change's rebuild.
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QCoreApplication, QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from .. import modegroups
from ..modegroups import MODE_LABELS
from . import theme
from .controls import FocusVisible, Anim, Card, mix

FORMS = ("full", "compact")
# The most buttons a row of the full form holds: four was the grid's width
# before the groups, and a fifth in a 400 px rail leaves cells too short
# to hit reliably.
MAX_COLS = 4
# How many recent modes, besides the current one, the Ctrl + E menu lists
# above the groups.
MENU_RECENT = 4
# Type-ahead: letters typed closer together than this are one word.
TYPE_AHEAD_S = 1.0


def group_label(group: str) -> str:
    """A mode group's name on screen (ohscore/modegroups.py GROUPS)."""
    names = {modegroups.VOICE: QCoreApplication.translate("ModeGrid", "Voice"),
             modegroups.DIGITAL: QCoreApplication.translate("ModeGrid", "Digital"),
             modegroups.PICTURES: QCoreApplication.translate("ModeGrid", "Pictures & data")}
    return names.get(group, group)


def label_font():
    """The font a mode's name is painted in, selected or not: bold in both,
    so selecting a button cannot make its label wider than it was measured."""
    return theme.font(13, theme.QFont.Weight.Bold, spacing=0.4)


def label_width(mode: str) -> float:
    return QFontMetricsF(label_font()).horizontalAdvance(modegroups.label(mode))


def cell_height() -> int:
    return theme.px(34)


def cell_pad() -> int:
    """Room each side of a label: enough that the warning dot in the top
    right corner (painted above the text, not beside it) never touches
    the letters, and that a label never meets the rounded edge. Six, not
    eight: at eight PSK125 needed 66 px and a 320 px rail's Digital group
    fell to three in a row."""
    return theme.px(6)


class ModeCell(FocusVisible, QWidget):
    picked = pyqtSignal(str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.sel = Anim(self)
        self.hover = Anim(self)
        self.why = ""
        self.rx_only = False
        self.setFixedHeight(cell_height())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def text(self) -> str:
        return modegroups.label(self.mode)

    def label_room(self) -> float:
        """The least width the label needs, measured."""
        return label_width(self.mode)

    def minimumSizeHint(self) -> QSize:
        return QSize(math.ceil(self.label_room()) + 2 * cell_pad(), cell_height())

    def sizeHint(self) -> QSize:
        return self.minimumSizeHint()

    def set_selected(self, on: bool):
        self.sel.to(1.0 if on else 0.0)

    def accessible_text(self) -> str:
        # The name a screen reader gives the button (FocusVisible): the
        # mode as it is painted, which Qt cannot see on a painted cell.
        return self.text()

    def set_why(self, why: str, rx_only: bool = False):
        self.why, self.rx_only = why, rx_only
        tip = why or (self.tr("Receive only") if rx_only else "")
        self.setToolTip(tip)
        self.update()

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.mode)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.picked.emit(self.mode)
        else:
            super().keyPressEvent(e)

    def text_rect(self, r: QRectF) -> QRectF:
        return r

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        k, h = self.sel.value, self.hover.value
        bg = mix(mix(theme.c("bg2"), theme.c("bg3"), h), theme.c("accent"), k)
        p.setPen(QPen(mix(theme.c("line"), theme.c("accent"), k), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 6, 6)
        p.setFont(label_font())
        fg = mix(theme.c("text") if not self.why else theme.c("text3"), theme.c("accentText"), k)
        p.setPen(fg)
        p.drawText(self.text_rect(r), Qt.AlignmentFlag.AlignCenter, self.text())
        self.paint_extra(p, r, fg)
        if self.why:
            # A small slashed dot: "listed, but missing something here".
            p.setPen(QPen(theme.c("warn"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.text_rect(r).right() - 11, r.y() + 4, 7, 7))
        elif self.rx_only:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("text3"))
            p.drawEllipse(QRectF(self.text_rect(r).right() - 9, r.y() + 5, 4, 4))
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)

    def paint_extra(self, p: QPainter, r: QRectF, fg) -> None:
        """Anything a kind of cell draws besides its label."""


class GroupCell(ModeCell):
    """The compact form's button for one group: the group's most recent
    mode, picked by a click; the arrow at its right end (or Down, or F4,
    from the keyboard) opens the group's menu instead."""

    menu_asked = pyqtSignal()

    def __init__(self, group: str, modes: list[str], parent=None):
        super().__init__(modes[0], parent)
        self.group = group
        self.modes = list(modes)

    @staticmethod
    def arrow_w() -> int:
        return theme.px(22)

    def show_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.update()

    def label_room(self) -> float:
        # The widest of the group's modes, not the one showing: the button
        # must not change width (and the rail with it) as the mode does.
        return max(label_width(m) for m in self.modes)

    def minimumSizeHint(self) -> QSize:
        return QSize(math.ceil(self.label_room()) + 2 * cell_pad() + self.arrow_w(), cell_height())

    def text_rect(self, r: QRectF) -> QRectF:
        return r.adjusted(0, 0, -self.arrow_w(), 0)

    def accessible_text(self) -> str:
        return QCoreApplication.translate("ModeGrid", "{group}: {mode}").format(
            group=group_label(self.group), mode=self.text())

    def set_why(self, why: str, rx_only: bool = False):
        super().set_why(why, rx_only)
        if not self.toolTip():
            self.setToolTip(QCoreApplication.translate("ModeGrid", "{group}: the arrow lists all of them").format(
                group=group_label(self.group)))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().x() >= self.width() - self.arrow_w():
            self.menu_asked.emit()
        else:
            super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_F4):
            self.menu_asked.emit()
        else:
            super().keyPressEvent(e)

    def paint_extra(self, p: QPainter, r: QRectF, fg) -> None:
        x = r.right() - self.arrow_w()
        p.setPen(QPen(mix(theme.c("line2"), fg, 0.35), 1))
        p.drawLine(QPointF(x, r.top() + 7), QPointF(x, r.bottom() - 7))
        cx, cy, s = x + self.arrow_w() / 2, r.center().y() + 1, theme.px(4)
        tri = QPainterPath()
        tri.moveTo(cx - s, cy - s / 2)
        tri.lineTo(cx + s, cy - s / 2)
        tri.lineTo(cx, cy + s / 2)
        tri.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fg)
        p.drawPath(tri)


class CellBlock(QWidget):
    """One group's buttons in the full form: equal widths, as many to a
    row as their longest label allows (MAX_COLS at most), in the group's
    fixed order. Laid out by hand rather than by a QGridLayout because the
    number of columns follows the width: its least height is worked out
    for the width it was given, so a narrower rail or larger text adds a
    row instead of squeezing a label."""

    def __init__(self, cells: list[ModeCell], parent=None):
        super().__init__(parent)
        self.cells: list[ModeCell] = []
        self._min_h = 0
        self.set_cells(cells)

    def set_cells(self, cells: list[ModeCell]) -> None:
        self.cells = list(cells)
        for c in self.cells:
            c.setParent(self)
            c.show()
        self._min_h = self.height_for(self.sizeHint().width())
        self.updateGeometry()
        self._place()

    @staticmethod
    def gap() -> int:
        return theme.px(6)

    def cell_min(self) -> int:
        return max((c.minimumSizeHint().width() for c in self.cells), default=0)

    def columns(self, w: float) -> int:
        n = len(self.cells)
        fit = int((w + self.gap()) // max(1, self.cell_min() + self.gap()))
        return max(1, min(MAX_COLS, n, fit))

    def height_for(self, w: float) -> int:
        n = len(self.cells)
        if not n:
            return 0
        rows = math.ceil(n / self.columns(w))
        return rows * cell_height() + (rows - 1) * self.gap()

    def sizeHint(self) -> QSize:
        cols = max(1, min(MAX_COLS, len(self.cells)))
        w = cols * self.cell_min() + (cols - 1) * self.gap()
        return QSize(w, self.height_for(w))

    def minimumSizeHint(self) -> QSize:
        return QSize(self.cell_min(), self._min_h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def _place(self) -> None:
        w = self.width()
        cols = self.columns(w)
        gap = self.gap()
        cw = (w - (cols - 1) * gap) / cols
        for i, c in enumerate(self.cells):
            row, col = divmod(i, cols)
            x = round(col * (cw + gap))
            c.setGeometry(x, row * (cell_height() + gap), round((col + 1) * (cw + gap) - gap) - x, cell_height())
        h = self.height_for(w)
        if h != self._min_h:
            # The height this width needs. Asked again of the layout, which
            # then gives the same width back, so this settles at once.
            self._min_h = h
            self.updateGeometry()


class TypeAheadMenu(QMenu):
    """A menu that moves to the first item starting with what is typed:
    "p" PSK31, "psk1" PSK125, "fr" FreeDV. Qt's menus only answer
    mnemonics, and mode names cannot carry one each (fifteen modes, and
    five start with P or F). Enter picks, as in any menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.typed = ""
        self._typed_at = 0.0
        self.setToolTipsVisible(True)

    def type_ahead(self, text: str) -> bool:
        now = time.monotonic()
        word = (self.typed if now - self._typed_at < TYPE_AHEAD_S else "") + text.lower()
        self._typed_at = now
        for attempt in (word, text.lower()):
            for a in self.actions():
                if a.isEnabled() and a.data() and a.text().lower().startswith(attempt):
                    self.typed = attempt
                    self.setActiveAction(a)
                    return True
        self.typed = ""
        return False

    def keyPressEvent(self, e):
        t = e.text()
        if t and t.isprintable() and not t.isspace() and not (
                e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.type_ahead(t)
            e.accept()
            return
        super().keyPressEvent(e)


def fill_menu(menu: QMenu, groups: list[tuple[str, list[str]]], current: str, why: dict, emit,
              recent: list[str] | None = None) -> None:
    """Fill `menu` with modes: the `recent` ones first (if given and any
    besides the current), then each group under its name, each mode once
    per section. `emit(mode)` is called with the one picked. A mode the
    radio cannot use here is listed, with the reason as its tooltip, as
    the buttons show it."""
    menu.clear()

    def heading(text: str):
        a = menu.addAction(text)
        a.setEnabled(False)
        f = theme.caps(10)
        a.setFont(f)

    def item(m: str):
        a = menu.addAction(modegroups.label(m))
        a.setData(m)
        a.setCheckable(True)
        a.setChecked(m == current)
        if why.get(m):
            a.setToolTip(why[m])
        a.triggered.connect(lambda _=False, m=m: emit(m))

    have = {m for _g, ms in groups for m in ms}
    others = [m for m in (recent or []) if m in have and m != current][:MENU_RECENT]
    if others:
        heading(QCoreApplication.translate("ModeGrid", "Recent"))
        for m in others:
            item(m)
    for g, ms in groups:
        heading(group_label(g))
        for m in ms:
            item(m)


class ModeGrid(Card):
    picked = pyqtSignal(str)
    over_picked = pyqtSignal(str)
    # The compact form is real (WP2 of the overhaul): the window may give
    # Watch its slim rail (BaseWindow._fit_rail).
    HAS_COMPACT = True
    _last_menu = None

    def __init__(self, modes: list[str], parent=None):
        # translate(), not self.tr(): the QWidget is not made until this returns.
        super().__init__(QCoreApplication.translate("ModeGrid", "Mode"), parent)
        self.modes = list(modes)
        self.buttons: tuple[str, ...] = ()
        self.mode = ""
        self.form = "full"
        self.prefs = None
        self.recent: list[str] = []
        self.caps: dict = {}
        self.cells: dict[str, ModeCell] = {}
        self.blocks: dict[str, CellBlock] = {}
        self.headings: dict[str, QLabel] = {}
        self.group_cells: dict[str, GroupCell] = {}

        self.full = QWidget()
        fl = QVBoxLayout(self.full)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(theme.px(4))
        self.compact = QWidget()
        cl = QVBoxLayout(self.compact)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(theme.px(6))
        for i, (g, ms) in enumerate(self.groups()):
            head = QLabel(group_label(g))
            head.setFont(theme.caps(9.5))
            self.headings[g] = head
            if i:
                fl.addSpacing(theme.px(4))
            fl.addWidget(head)
            block = CellBlock([self._cell(m) for m in ms])
            self.blocks[g] = block
            fl.addWidget(block)
            gc = GroupCell(g, ms)
            gc.picked.connect(self._pick)
            gc.menu_asked.connect(lambda g=g: self.open_group_menu(g))
            self.group_cells[g] = gc
            cl.addWidget(gc)
        self.compact.hide()
        self.lay.addWidget(self.full)
        self.lay.addWidget(self.compact)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {theme.t()['warn']}; font-size: {theme.px(12)}px;")
        self.note.hide()
        self.lay.addWidget(self.note)
        self._sync_headings()

    # ---------------------------------------------------------- building
    def groups(self) -> list[tuple[str, list[str]]]:
        return modegroups.groups(self.modes, self.buttons)

    def _cell(self, m: str) -> ModeCell:
        c = ModeCell(m)
        c.picked.connect(self._pick)
        self.cells[m] = c
        return c

    def attach(self, prefs, buttons=()) -> None:
        """The app's part, after the window has made the card: its
        preferences (the recent modes, kept in ui.json `modeRecent`) and
        its over buttons (NB: "kgstv"), each put in its group at its fixed
        place. Called on every build, as a theme change makes a new card."""
        self.prefs = prefs
        if prefs is not None:
            kept = [m for m in prefs.get("modeRecent", []) or [] if m not in self.recent]
            self.recent = (self.recent + kept)[:self._recent_max()]
        new = [b for b in buttons if b in modegroups.OVER_BUTTONS and b not in self.buttons]
        if new:
            self.buttons = self.buttons + tuple(new)
            for g, ms in self.groups():
                if g not in self.blocks:
                    continue                    # a group the app has no radio mode in: not offered
                for m in ms:
                    if m not in self.cells:
                        self._cell(m)
                self.blocks[g].set_cells([self.cells[m] for m in ms])
                self.group_cells[g].modes = list(ms)
                self.group_cells[g].updateGeometry()
        self._store_recent()
        self._sync_groups()

    @staticmethod
    def _recent_max() -> int:
        from .prefs import MODE_RECENT_MAX
        return MODE_RECENT_MAX

    # ---------------------------------------------------------- state
    def _pick(self, mode: str) -> None:
        if mode in modegroups.OVER_BUTTONS:
            self.note_recent(mode)
            self.over_picked.emit(mode)
        else:
            self.picked.emit(mode)

    def note_recent(self, mode: str) -> None:
        """`mode` was used just now: first in the recent list."""
        if self.recent[:1] == [mode]:
            return
        self.recent = ([mode] + [m for m in self.recent if m != mode])[:self._recent_max()]
        self._store_recent()
        self._sync_groups()

    def _store_recent(self) -> None:
        # Written to the preferences, saved with them when the window
        # closes: a mode change is not worth a disk write of its own.
        if self.prefs is not None:
            self.prefs["modeRecent"] = list(self.recent)

    def shown_for(self, group: str) -> str:
        """The mode the compact form's button for `group` shows: the
        group's most recent, or its first if none of it has been used."""
        ms = dict(self.groups()).get(group, [])
        for m in self.recent:
            if m in ms:
                return m
        return ms[0] if ms else ""

    def set_mode(self, mode: str):
        self.mode = mode
        for m, c in self.cells.items():
            c.set_selected(m == mode)
        why = self.cells[mode].why if mode in self.cells else ""
        self.note.setText(why)
        self.note.setVisible(bool(why))
        if mode in self.cells:
            self.note_recent(mode)
        self._sync_groups()

    def set_caps(self, modes: dict):
        self.caps = dict(modes)
        for m, c in self.cells.items():
            c.set_why(*self._why(m))
        self._sync_groups()

    def _why(self, m: str) -> tuple[str, bool]:
        info = self.caps.get(m) or {}
        return info.get("missing", ""), bool(info) and bool(info.get("decode")) and not info.get("encode")

    def _sync_groups(self) -> None:
        cur = modegroups.group_of(self.mode)
        for g, gc in self.group_cells.items():
            gc.show_mode(self.shown_for(g))
            gc.set_why(*self._why(gc.mode))
            gc.set_selected(g == cur and gc.mode == self.mode)
        self._sync_headings()

    def _sync_headings(self) -> None:
        cur = modegroups.group_of(self.mode)
        for g, head in self.headings.items():
            colour = theme.t()["accent" if g == cur else "text3"]
            sheet = f"color: {colour};"
            if head.styleSheet() != sheet:
                head.setStyleSheet(sheet)

    def set_form(self, form: str):
        """The card's form, "full" or "compact" (the workspace and the
        window's tier decide). Shows one prepared form and hides the
        other: no widget is made or rebuilt (plan section 7, rule 6)."""
        if form not in FORMS:
            return
        self.form = form
        self.full.setVisible(form == "full")
        self.compact.setVisible(form == "compact")

    # ---------------------------------------------------------- menus
    def why_map(self) -> dict:
        return {m: self._why(m)[0] for g, ms in self.groups() for m in ms}

    def menu(self, parent=None) -> TypeAheadMenu:
        """Every mode, the recent ones first: Ctrl + E's menu."""
        menu = TypeAheadMenu(parent or self)
        fill_menu(menu, self.groups(), self.mode, self.why_map(), self._pick, self.recent)
        return menu

    def group_menu(self, group: str, parent=None) -> TypeAheadMenu:
        menu = TypeAheadMenu(parent or self)
        fill_menu(menu, [(g, ms) for g, ms in self.groups() if g == group], self.mode, self.why_map(), self._pick)
        return menu

    def open_group_menu(self, group: str) -> TypeAheadMenu:
        gc = self.group_cells[group]
        menu = self.group_menu(group)
        menu.popup(gc.mapToGlobal(QPoint(0, gc.height())))
        self._last_menu = menu
        return menu

    def open_menu(self, window: QWidget) -> TypeAheadMenu:
        """Ctrl + E: the mode menu, over the card when the rail shows it,
        else in the middle of `window` (the Tight tier's drawer is shut).
        Typing goes to the menu at once."""
        menu = self.menu(window)
        if self.isVisible():
            at = self.mapToGlobal(QPoint(theme.S3, theme.S3 + 18))
        else:
            hint = menu.sizeHint()
            at = window.mapToGlobal(QPoint((window.width() - hint.width()) // 2,
                                           (window.height() - hint.height()) // 3))
        menu.popup(at)
        self._last_menu = menu
        return menu


class ModeMenuButton(QToolButton):
    """The current mode's name; a click opens the mode menu (recent modes,
    then each group: the menu Ctrl + E opens) and picking one emits
    `picked`, as a mode button does. A mode the radio cannot use here is
    listed with the reason as its tooltip, as the buttons show it. For
    where the rail is out of sight (the Tight tier's tab row, section 3).
    `buttons` adds over buttons (NB: "kgstv"), which emit `over_picked`;
    set_recent() gives it the card's recent modes."""

    picked = pyqtSignal(str)
    over_picked = pyqtSignal(str)

    def __init__(self, modes: list[str], parent=None, buttons=()):
        super().__init__(parent)
        self.modes = list(modes)
        self.buttons = tuple(buttons)
        self.mode = ""
        self.recent: list[str] = []
        self.why: dict[str, str] = {}
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self.tr("Mode (Ctrl+E)"))
        self.menu_ = TypeAheadMenu(self)
        self.setMenu(self.menu_)
        self.menu_.aboutToShow.connect(self._fill)
        self._fill()

    def _emit(self, m: str) -> None:
        (self.over_picked if m in modegroups.OVER_BUTTONS else self.picked).emit(m)

    def _fill(self):
        fill_menu(self.menu_, modegroups.groups(self.modes, self.buttons), self.mode, self.why, self._emit,
                  self.recent)

    def set_mode(self, mode: str):
        self.mode = mode
        self.setText(MODE_LABELS.get(mode, mode.upper()) + "  ▾")

    def set_recent(self, modes: list[str]) -> None:
        self.recent = list(modes)

    def set_caps(self, modes: dict):
        self.why = {m: (modes.get(m) or {}).get("missing", "") for m in self.modes}
