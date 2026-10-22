"""The small hand-painted controls every panel is built from.

Stock Qt sliders, group boxes and push buttons look like a form; these look
like an instrument, and - more usefully - they all share one set of
behaviours: wheel and arrow keys adjust, a visible focus ring, an eased
transition on every state change (theme.ANIM_MS), and a value always printed
next to the control so nothing has to be hovered to be read.
"""
from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import (QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import icons, theme
from .theme import S1, S2, S3, S4


def mix(a: QColor, b: QColor, k: float) -> QColor:
    k = max(0.0, min(1.0, k))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
                           a.blueF() + (b.blueF() - a.blueF()) * k, a.alphaF() + (b.alphaF() - a.alphaF()) * k)


class Anim:
    """One eased float, animating towards whatever it was last told."""

    def __init__(self, owner: QWidget, value: float = 0.0, ms: int = theme.ANIM_MS):
        # Always a float. QVariantAnimation interpolates only between values
        # of one type: from an int start (Segmented passed its option index)
        # to a float end it produces nothing at all - no valueChanged, the
        # value never moves - so the lower panel's tabs stayed on Mode while
        # Logbook showed, until something happened to set them instantly.
        self.value = float(value)
        self.a = QVariantAnimation(owner)
        self.a.setDuration(ms)
        self.a.setEasingCurve(QEasingCurve(theme.EASE))
        self.a.valueChanged.connect(self._step)
        self.owner = owner

    def _step(self, v):
        self.value = float(v)
        self.owner.update()

    def to(self, target: float, instant: bool = False):
        target = float(target)
        if instant or not self.owner.isVisible():
            self.a.stop()
            self.value = target
            self.owner.update()
            return
        if abs(target - self.value) < 1e-6:
            return
        self.a.stop()
        self.a.setStartValue(self.value)
        self.a.setEndValue(target)
        self.a.start()


class FocusVisible:
    """Mixin: like CSS :focus-visible - a focus ring only when focus arrived
    from the keyboard. A click already says where the operator is; a ring
    after every click is noise. Put it first in the bases."""

    _kbd_focus = False

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                         Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        self.update()
        super().focusOutEvent(e)

    def focus_visible(self) -> bool:
        return self.hasFocus() and self._kbd_focus

    # Screen readers. Every control here is painted, so Qt has no text to
    # give UI Automation, VoiceOver or Orca, and Narrator read nothing at
    # all on a mode button, a toggle, a tab or an icon button (Windows test
    # 17/10/2026, finding 5). Each control says what it is in
    # accessible_text() - its label and state - and the name is brought up
    # to date as it is shown and each time it repaints, which every change
    # of state does, so no setter has to remember to. A control that says
    # nothing is named by its tooltip, as icon-only ones all have.
    # Repainting alone was not enough: a control scrolled out of its scroll
    # area (the Receive card's Mute, below the fold at 1600x960) is never
    # painted, so a reader walking the tree heard the state it had when
    # last seen. Every change of state asks for a repaint through update(),
    # so the name is brought up to date there as well, painted or not.
    _ACCESSIBLE_EVENTS = (QEvent.Type.Polish, QEvent.Type.Show, QEvent.Type.ToolTipChange, QEvent.Type.Paint)

    def accessible_text(self) -> str:
        return ""

    def sync_accessible(self) -> None:
        name = self.accessible_text() or self.toolTip()
        if name != self.accessibleName():
            self.setAccessibleName(name)

    def update(self, *args):
        self.sync_accessible()
        super().update(*args)

    def event(self, e):
        if e.type() in self._ACCESSIBLE_EVENTS:
            self.sync_accessible()
        return super().event(e)


def on_off(on: bool) -> str:
    """A switch's state as a screen reader says it."""
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.translate("Controls", "on") if on else QCoreApplication.translate("Controls", "off")


def focus_ring(p: QPainter, r: QRectF, radius: float):
    pen = QPen(theme.c("accent"), 2)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)


class Card(QFrame):
    """A rounded panel with an optional small-caps title and a right-side slot."""

    def __init__(self, title: str = "", parent=None, pad: int = S3):
        super().__init__(parent)
        self.title = title
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        top = S3 + (18 if title else 0)
        self.lay.setContentsMargins(pad, top if title else pad, pad, pad)
        self.lay.setSpacing(S2)
        self.header_right: QWidget | None = None

    def set_header_widget(self, w: QWidget):
        w.setParent(self)
        self.header_right = w
        w.show()
        m = self.lay.contentsMargins()
        need = S2 + w.sizeHint().height() + S2
        if m.top() < need:
            self.lay.setContentsMargins(m.left(), need, m.right(), m.bottom())
        self._place()

    def resizeEvent(self, e):
        self._place()
        super().resizeEvent(e)

    def event(self, e):
        # The header widget is outside the layout, so when its text changes
        # the request to re-measure lands here.
        if e.type() == QEvent.Type.LayoutRequest:
            self._place()
        return super().event(e)

    def _place(self):
        if self.header_right is not None:
            sh = self.header_right.sizeHint()
            w = min(sh.width(), self.width() - 2 * S3 - 90)    # never over the title
            self.header_right.setGeometry(self.width() - w - S3, S2, w, sh.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("bg1"))
        p.drawRoundedRect(r, theme.RADIUS, theme.RADIUS)
        if self.title:
            p.setFont(theme.caps())
            p.setPen(theme.c("text3"))
            p.drawText(QRectF(S3, S2 + 1, self.width() - 2 * S3, 18), Qt.AlignmentFlag.AlignLeft |
                       Qt.AlignmentFlag.AlignVCenter, self.title)


class Caption(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(theme.caps())
        self.setStyleSheet(f"color: {theme.t()['text3']};")


class StandingWarning(QLabel):
    """The transmit card's one standing warning: the engine's txWarning
    status (Engine.tx_warn) - the most serious transmit condition there is
    now, changed in place and gone when it clears. It replaced the toasts
    those conditions used to raise, which stacked over the scopes. Both
    apps' transmit cards put it straight under the power control: below
    it, so its coming and going never moves the slider from under the
    pointer mid-over; not last, because at 1366x768 the rail scrolls and
    the card's foot is out of sight (tried first, 08/10)."""

    COLOUR = {"error": "err", "warn": "warn", "info": "text2"}

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setObjectName("TxWarning")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.key = ""
        self.level = ""
        self.hide()

    def set_warning(self, w: dict | None) -> None:
        w = w or {}
        text = str(w.get("text") or "")
        self.key = str(w.get("key") or "") if text else ""
        self.level = str(w.get("level") or "warn") if text else ""
        self.setText(text)
        self.setToolTip(str(w.get("detail") or ""))
        if text:
            self.setStyleSheet(f"color: {theme.t()[self.COLOUR.get(self.level, 'warn')]};")
        self.setVisible(bool(text))


class Slider(FocusVisible, QWidget):
    """Label, value and a track on one line. Drag, wheel, arrows, Home/End;
    double-click resets to the default. `fmt` prints the value."""

    changed = pyqtSignal(float)        # while dragging
    committed = pyqtSignal(float)      # on release / each wheel or key step

    def __init__(self, label: str, lo: float, hi: float, value: float, step: float,
                 fmt: Callable[[float], str] = lambda v: f"{v:g}", default: float | None = None,
                 colour: str = "accent", parent=None):
        super().__init__(parent)
        self.label, self.lo, self.hi, self.step, self.fmt = label, lo, hi, step, fmt
        self.default = value if default is None else default
        self.v = value
        self.cap: float | None = None            # a hard ceiling drawn as a notch (TX gain)
        self.colour = colour
        self.drag = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hover = Anim(self)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(max(200, self.minimumSizeHint().width()), 40)

    # The label and the value share the top line: the value right-aligned
    # in its own room, the label in what is left. They used to take fixed
    # shares (60 % and 60 %, overlapping by a fifth), which at 130 % text
    # ran "Low edge" into "300 Hz" and cut "Monitor level" to "Monitor
    # leve". Now the least width holds both whole, and below it (a layout
    # that cannot give it) the label is elided rather than overlapped.
    GAP = 8

    @staticmethod
    def _label_font():
        return theme.font(12.5)

    @staticmethod
    def _value_font():
        return theme.font(12.5, theme.QFont.Weight.DemiBold, mono=True)

    def _value_width(self) -> float:
        """The widest the value gets: at either end of the range or now."""
        fm = QFontMetricsF(self._value_font())
        widest = 0.0
        for v in (self.lo, self.hi, self.v):
            try:
                widest = max(widest, fm.horizontalAdvance(self.fmt(v)))
            except Exception:  # noqa: BLE001 - a format that cannot print an end of its range
                pass
        return widest

    def minimumSizeHint(self):
        lab = QFontMetricsF(self._label_font()).horizontalAdvance(self.label) if self.label else 0.0
        return QSize(math.ceil(lab + self.GAP + self._value_width()) + 1, 40)

    def accessible_text(self) -> str:
        return f"{self.label}: {self.fmt(self.v)}" if self.label else self.fmt(self.v)

    def set_value(self, v: float, emit: bool = False):
        hi = self.hi if self.cap is None else min(self.hi, self.cap)
        v = max(self.lo, min(hi, float(v)))
        if abs(v - self.v) > 1e-9:
            self.v = v
            self.update()
            if emit:
                self.changed.emit(v)
        return v

    def set_range(self, lo: float, hi: float):
        self.lo, self.hi = lo, hi
        self.set_value(self.v)
        self.updateGeometry()           # the widest value, and so the least width, may have changed
        self.update()

    def _track(self) -> QRectF:
        return QRectF(2, 28, self.width() - 4, 4)

    def _from_x(self, x: float) -> float:
        tr = self._track()
        k = (x - tr.x()) / tr.width()
        v = self.lo + max(0.0, min(1.0, k)) * (self.hi - self.lo)
        return round(v / self.step) * self.step

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag = True
            self.set_value(self._from_x(e.position().x()), emit=True)

    def mouseMoveEvent(self, e):
        if self.drag:
            self.set_value(self._from_x(e.position().x()), emit=True)

    def mouseReleaseEvent(self, e):
        if self.drag:
            self.drag = False
            self.committed.emit(self.v)

    def mouseDoubleClickEvent(self, e):
        self.set_value(self.default, emit=True)
        self.committed.emit(self.v)

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.set_value(self.v + (self.step if d > 0 else -self.step), emit=True)
            self.committed.emit(self.v)
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        big = (self.hi - self.lo) / 10
        moves = {Qt.Key.Key_Right: self.step, Qt.Key.Key_Up: self.step, Qt.Key.Key_Left: -self.step,
                 Qt.Key.Key_Down: -self.step, Qt.Key.Key_PageUp: big, Qt.Key.Key_PageDown: -big}
        if k in moves:
            self.set_value(self.v + moves[k], emit=True)
            self.committed.emit(self.v)
        elif k == Qt.Key.Key_Home:
            self.set_value(self.lo, emit=True)
            self.committed.emit(self.v)
        elif k == Qt.Key.Key_End:
            self.set_value(self.hi, emit=True)
            self.committed.emit(self.v)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        en = self.isEnabled()
        value = self.fmt(self.v)
        p.setFont(self._value_font())
        vw = min(float(w), p.fontMetrics().horizontalAdvance(value) + 1.0)
        p.setPen(theme.c("text" if en else "text3"))
        p.drawText(QRectF(w - vw, 0, vw, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
        p.setFont(self._label_font())
        p.setPen(theme.c("text2" if en else "text3"))
        room = max(0.0, w - vw - self.GAP)
        label = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, int(room))
        p.drawText(QRectF(0, 0, room, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        tr = self._track()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("bg3"))
        p.drawRoundedRect(tr, 2, 2)
        k = (self.v - self.lo) / ((self.hi - self.lo) or 1)
        fill = QRectF(tr.x(), tr.y(), tr.width() * k, tr.height())
        col = theme.c(self.colour) if en else theme.c("text3")
        p.setBrush(col)
        p.drawRoundedRect(fill, 2, 2)
        if self.cap is not None and self.cap < self.hi:
            # The ceiling in the `limit` amber, not the transmit red: it is a
            # setting's edge, and red is kept for being on the air (overhaul
            # section 5.3).
            kc = (self.cap - self.lo) / ((self.hi - self.lo) or 1)
            x = tr.x() + tr.width() * kc
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(theme.c("limit"), 2))
            p.drawLine(QPointF(x, tr.y() - 5), QPointF(x, tr.bottom() + 5))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("limit", 0.12))
            p.drawRect(QRectF(x, tr.y(), tr.right() - x, tr.height()))
        cx = tr.x() + tr.width() * k
        r = 6 + 1.5 * self.hover.value + (1.5 if self.drag else 0)
        p.setBrush(theme.c("bg1"))
        p.setPen(QPen(col, 2))
        p.drawEllipse(QPointF(cx, tr.center().y()), r, r)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent", 0.45), 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, tr.center().y()), r + 3, r + 3)


class Segmented(FocusVisible, QWidget):
    """A row of mutually exclusive options; the selection slides between them."""

    picked = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], value: str | None = None, parent=None, compact=False):
        super().__init__(parent)
        self.options = options               # [(value, label)]
        self.disabled: dict[str, str] = {}   # value -> why
        self.value = value if value is not None else (options[0][0] if options else "")
        self.pos = Anim(self, self._index(self.value))
        self.hover_i = -1
        self.compact = compact
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        h = 28 if compact else 32
        self.setFixedHeight(h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _index(self, v):
        for i, (val, _) in enumerate(self.options):
            if val == v:
                return i
        return 0

    def sizeHint(self):
        fm = QFontMetricsF(theme.font(12.5, theme.QFont.Weight.DemiBold))
        w = sum(fm.horizontalAdvance(lab) + 22 for _, lab in self.options)
        return QSize(int(w) + 6, self.height())

    def minimumSizeHint(self):
        # The cells are equal, so the least width is the longest label's
        # cell times their number. Without it a layout short of room
        # squeezed the labels into each other unseen (the Receive card's
        # AGC at 130 % in the pseudo-locale: "[Méd~]Slõw~~").
        fm = QFontMetricsF(theme.font(12 if self.compact else 12.5, theme.QFont.Weight.DemiBold))
        cell = max((fm.horizontalAdvance(lab) for _, lab in self.options), default=0.0) + 12
        return QSize(math.ceil(cell * len(self.options)) + 6, self.height())

    def _selected(self) -> bool:
        return any(val == self.value for val, _ in self.options)

    def accessible_text(self) -> str:
        # The choice made and where it sits among the others ("Pictures, 3
        # of 6"); the tooltip, where there is one, says what is chosen.
        i = self._index(self.value)
        label = self.options[i][1] if self._selected() else "-"
        text = f"{label}, {i + 1} of {len(self.options)}" if self._selected() else label
        tip = self.toolTip()
        return f"{tip}: {text}" if tip else text

    def set_value(self, v: str, animate: bool = True):
        if v == self.value:
            return
        # From no selection there is nothing to slide from: appear in place.
        was = self._selected()
        self.value = v
        self.pos.to(self._index(v), instant=not animate or not was)

    def set_disabled(self, why: dict[str, str]):
        self.disabled = dict(why)
        self.update()

    def _cell(self, i) -> QRectF:
        n = max(1, len(self.options))
        w = (self.width() - 6) / n
        return QRectF(3 + i * w, 3, w, self.height() - 6)

    def _hit(self, x):
        n = max(1, len(self.options))
        return max(0, min(n - 1, int((x - 3) / ((self.width() - 6) / n))))

    def mouseMoveEvent(self, e):
        i = self._hit(e.position().x())
        if i != self.hover_i:
            self.hover_i = i
            why = self.disabled.get(self.options[i][0], "")
            self.setToolTip(why)
            self.update()

    def leaveEvent(self, e):
        self.hover_i = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._choose(self._hit(e.position().x()))

    def _choose(self, i):
        v = self.options[i][0]
        if v in self.disabled:
            return
        self.set_value(v)
        self.picked.emit(v)

    def keyPressEvent(self, e):
        i = self._index(self.value)
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            j = i - 1
            while j >= 0 and self.options[j][0] in self.disabled:
                j -= 1
            if j >= 0:
                self._choose(j)
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            j = i + 1
            while j < len(self.options) and self.options[j][0] in self.disabled:
                j += 1
            if j < len(self.options):
                self._choose(j)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("bg2"))
        p.drawRoundedRect(r, theme.RADIUS_SM, theme.RADIUS_SM)
        n = max(1, len(self.options))
        w = (self.width() - 6) / n
        p.setPen(Qt.PenStyle.NoPen)
        # A value that is none of the options (HAM's licence class before
        # one is chosen) shows nothing selected, rather than the first option
        # looking chosen when it is not.
        chosen = self._selected()
        if chosen:
            sel = QRectF(3 + self.pos.value * w, 3, w, self.height() - 6)
            p.setBrush(theme.c("accent"))
            p.drawRoundedRect(sel, theme.RADIUS_SM - 2, theme.RADIUS_SM - 2)
        p.setFont(theme.font(12 if self.compact else 12.5, theme.QFont.Weight.DemiBold))
        for i, (val, lab) in enumerate(self.options):
            cell = self._cell(i)
            if i == self.hover_i and val != self.value and val not in self.disabled:
                p.setBrush(theme.c("bg3"))
                p.drawRoundedRect(cell, 4, 4)
            k = max(0.0, 1.0 - abs(self.pos.value - i)) if chosen else 0.0
            if val in self.disabled:
                col = theme.c("text3", 0.55)
            else:
                col = mix(theme.c("text2"), theme.c("accentText"), k)
            p.setPen(col)
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, lab)
            p.setPen(Qt.PenStyle.NoPen)
        if self.focus_visible():
            focus_ring(p, QRectF(self.rect()), theme.RADIUS_SM)


class Toggle(FocusVisible, QWidget):
    """A labelled switch. The thumb slides; the track fills with the colour."""

    toggled = pyqtSignal(bool)

    def __init__(self, label: str, on: bool = False, colour: str = "accent", parent=None, show_label: bool = True):
        super().__init__(parent)
        self.label, self.on, self.colour = label, on, colour
        # show_label=False: the switch alone, for one whose neighbour already
        # says what it is ("Monitor" before "Monitor level"); the label is
        # still its name to a screen reader and its tooltip.
        self.show_label = show_label
        if not show_label:
            self.setToolTip(label)
        self.k = Anim(self, 1.0 if on else 0.0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        if not self.show_label:
            return QSize(42, 28)
        fm = QFontMetricsF(theme.font(12.5))
        return QSize(int(fm.horizontalAdvance(self.label)) + 52, 28)

    def minimumSizeHint(self):
        # Its whole label: a layout short of room used to cut "Monitor" to
        # "M" beside the switch, and nothing said so.
        return self.sizeHint()

    def accessible_text(self) -> str:
        return f"{self.label}: {on_off(self.on)}"

    def set_on(self, on: bool, emit: bool = False):
        on = bool(on)
        if on != self.on:
            self.on = on
            self.k.to(1.0 if on else 0.0)
            if emit:
                self.toggled.emit(on)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.set_on(not self.on, emit=True)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.set_on(not self.on, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        en = self.isEnabled()
        tr = QRectF(self.width() - 38, 6, 34, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(theme.c("bg3"), theme.c(self.colour) if en else theme.c("text3"), self.k.value))
        p.drawRoundedRect(tr, 9, 9)
        x = tr.x() + 9 + (tr.width() - 18) * self.k.value
        p.setBrush(QColor("#ffffff") if en else theme.c("bg2"))
        p.drawEllipse(QPointF(x, tr.center().y()), 7, 7)
        if self.show_label:
            p.setFont(theme.font(12.5))
            p.setPen(theme.c("text2" if en else "text3"))
            p.drawText(QRectF(0, 0, self.width() - 44, self.height()), Qt.AlignmentFlag.AlignLeft |
                       Qt.AlignmentFlag.AlignVCenter, self.label)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent", 0.6), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tr.adjusted(-2, -2, 2, 2), 11, 11)


class Button(FocusVisible, QWidget):
    """A flat button: text and/or icon; `kind` is primary (accent fill),
    danger (red), ghost (no fill), or plain. `checkable` turns it into a chip."""

    clicked = pyqtSignal()

    def __init__(self, text: str = "", icon: str = "", kind: str = "plain", parent=None, checkable=False,
                 small=False):
        super().__init__(parent)
        self.text, self.icon, self.kind, self.checkable, self.small = text, icon, kind, checkable, small
        self.checked = False
        self.hover = Anim(self)
        self.press = Anim(self, ms=90)
        self.chk = Anim(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26 if small else 32)

    def _font(self):
        return theme.font(12 if self.small else 12.5, theme.QFont.Weight.DemiBold)

    def sizeHint(self):
        fm = QFontMetricsF(self._font())
        w = (fm.horizontalAdvance(self.text) if self.text else 0) + (18 if self.icon else 0)
        w += (6 if self.icon and self.text else 0) + (20 if self.small else 28)
        # Rounded up: int() gave the text up to a pixel less than it needs,
        # and the Workspace button laid out at its hint cut a sliver off.
        return QSize(math.ceil(w), self.height())

    def accessible_text(self) -> str:
        name = self.text or self.toolTip()
        return f"{name}: {on_off(self.checked)}" if self.checkable and name else name

    def minimumSizeHint(self):
        # Small buttons (macro rows) may shrink and elide; a row of six must
        # not set the minimum width of the whole lower panel.
        return QSize(56, self.height()) if self.small else self.sizeHint()

    def set_text(self, text):
        self.text = text
        self.updateGeometry()
        self.update()

    def set_checked(self, on: bool):
        self.checked = bool(on)
        self.chk.to(1.0 if on else 0.0)

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.press.to(1)

    def mouseReleaseEvent(self, e):
        self.press.to(0)
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self._activate()

    def _activate(self):
        if not self.isEnabled():
            return
        if self.checkable:
            self.set_checked(not self.checked)
        self.clicked.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        en = self.isEnabled()
        h, pr, ck = self.hover.value, self.press.value, self.chk.value
        if self.kind == "primary":
            bg = mix(theme.c("accent"), QColor("#ffffff"), 0.12 * h - 0.1 * pr)
            fg = theme.c("accentText")
            border = Qt.PenStyle.NoPen
        elif self.kind == "danger":
            bg = mix(theme.c("tx"), QColor("#ffffff"), 0.1 * h)
            fg = QColor("#ffffff")
            border = Qt.PenStyle.NoPen
        elif self.kind == "ghost":
            bg = theme.c("bg3", 0.9 * h)
            fg = theme.c("text2")
            border = Qt.PenStyle.NoPen
        else:
            bg = mix(theme.c("bg2"), theme.c("bg3"), h)
            bg = mix(bg, theme.c("accent", 0.22), ck)
            fg = mix(theme.c("text"), theme.c("accent"), ck)
            border = QPen(mix(theme.c("line"), theme.c("accent"), ck), 1)
        if not en:
            bg = theme.c("bg2", 0.6)
            fg = theme.c("text3")
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(r, theme.RADIUS_SM, theme.RADIUS_SM)
        fm = QFontMetricsF(self._font())
        tw = fm.horizontalAdvance(self.text) if self.text else 0
        iw = 16 if self.icon else 0
        gap = 6 if self.icon and self.text else 0
        x = (self.width() - (tw + iw + gap)) / 2
        if self.icon:
            icons.paint(p, self.icon, QRectF(x, (self.height() - 16) / 2, 16, 16), fg, 1.7)
        if self.text:
            p.setFont(self._font())
            p.setPen(fg)
            room = self.width() - (iw + gap) - 16
            text = self.text if tw <= room else fm.elidedText(self.text, Qt.TextElideMode.ElideRight, room)
            tw = min(tw, room)
            x = max(8.0, x)
            p.drawText(QRectF(x + iw + gap, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, text)
        if self.focus_visible():
            focus_ring(p, QRectF(self.rect()), theme.RADIUS_SM)


class Check(FocusVisible, QWidget):
    """A checkbox, painted: a rounded box that fills with the accent and
    draws a tick, and a label that wraps (QCheckBox's never does). Clicking
    the label toggles it too. QCheckBox's isChecked/setChecked/toggle API."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, checked: bool = False, bold: bool = False, parent=None):
        super().__init__(parent)
        self.text, self.bold, self.on = text, bold, bool(checked)
        self.k = Anim(self, 1.0 if checked else 0.0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def _font(self):
        return theme.font(14, theme.QFont.Weight.DemiBold if self.bold else theme.QFont.Weight.Normal)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        fm = QFontMetricsF(self._font())
        r = fm.boundingRect(QRectF(0, 0, max(50, w - 34), 2000), Qt.TextFlag.TextWordWrap, self.text)
        return int(max(24, r.height() + 6))

    def sizeHint(self):
        return QSize(400, self.heightForWidth(400))

    def accessible_text(self) -> str:
        return f"{self.text}: {on_off(self.on)}"

    def isChecked(self):
        return self.on

    def setChecked(self, on):
        on = bool(on)
        if on != self.on:
            self.on = on
            self.k.to(1.0 if on else 0.0)
            self.toggled.emit(on)

    def toggle(self):
        self.setChecked(not self.on)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self.k.value
        box = QRectF(1, 3, 20, 20)
        p.setPen(QPen(mix(theme.c("line2"), theme.c("accent"), k), 1.5))
        p.setBrush(mix(theme.c("bg2"), theme.c("accent"), k))
        p.drawRoundedRect(box, 5, 5)
        if k > 0.02:
            tick = QPainterPath()
            tick.moveTo(box.x() + 5, box.y() + 10.5)
            tick.lineTo(box.x() + 8.5, box.y() + 14)
            tick.lineTo(box.x() + 15, box.y() + 6.5)
            pen = QPen(theme.c("accentText"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setOpacity(k)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(tick)
            p.setOpacity(1.0)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent", 0.6), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-3, -3, 3, 3), 7, 7)
        p.setFont(self._font())
        p.setPen(theme.c("text"))
        p.drawText(QRectF(34, 2, self.width() - 34, self.height() - 2),
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, self.text)


def check_row(text: str, checked: bool = False, bold: bool = False):
    """(widget, checkbox) - kept as a pair for the callers' layouts."""
    c = Check(text, checked, bold)
    return c, c


def hbox(*widgets, spacing=S2, margins=(0, 0, 0, 0), stretch_last=False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


def vbox(*widgets, spacing=S2, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, (QHBoxLayout, QVBoxLayout)):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def rounded_path(r: QRectF, rad: float) -> QPainterPath:
    pp = QPainterPath()
    pp.addRoundedRect(r, rad, rad)
    return pp


__all__ = ["Anim", "Button", "Card", "Caption", "Segmented", "Slider", "Toggle", "hbox", "vbox", "mix", "S1", "S2",
           "S3", "S4"]
