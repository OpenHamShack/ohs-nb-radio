"""The beacon-lock and TX-lock badges: QO-100's own status. Like everything
in ohscore/ui/status.py they say their state in colour *and* words, because
a red/green distinction alone fails one operator in twelve.

The beacon-lock badge (RxBadge) is also where beacon lock is worked: its
details panel picks Auto, Hold or Manual and, in Manual, nudges or types
rxCorr; the wheel over it nudges too."""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from ohscore.ui import icons, theme
from ohscore.ui.controls import Anim, Button, FocusVisible, Segmented, mix
from ohscore.ui.status import LockPopover
from ohsnb.i18n import _


# ------------------------------------------------------------------ lock badges
def hz_forms(v) -> tuple[str, ...]:
    """A frequency error written as precisely as the badge has room for,
    longest first (LockBadge._place_detail picks): -2.900 kHz, -2.90 kHz,
    -2.9 kHz; +12.3 Hz, +12 Hz."""
    if v is None:
        return ("—",)
    v = float(v)
    if abs(v) >= 1000:
        return tuple(f"{v / 1000:+.{n}f} kHz" for n in (3, 2, 1))
    return f"{v:+.1f} Hz", f"{v:+.0f} Hz"


def ppm_forms(v: float) -> tuple[str, ...]:
    return tuple(f"{float(v):+.{n}f} ppm" for n in (2, 1))


class LockBadge(FocusVisible, QWidget):
    """searching -> locked -> lost, with the error underneath. Hover for the
    full set of numbers; click to pin them open."""

    # Hold and Manual are the operator's choice, not a fault, so not red or
    # amber; but they are not "locked" either - nothing follows the drift -
    # so not green. The accent, a dashed outline and their own symbol.
    # Landed (TX lock): our signal found, off the dial by the error shown,
    # and being corrected - amber like searching, but a steady dot, not the
    # spinner: nothing is being looked for any more.
    COLOURS = {"locked": "ok", "searching": "warn", "landed": "warn", "lost": "err", "off": "text3", "idle": "text3",
               "hold": "accent", "manual": "accent"}
    WORDS = {"locked": "LOCKED", "searching": "SEARCHING", "landed": "LANDED", "lost": "LOST", "off": "OFF",
             "idle": "IDLE", "hold": "HOLD", "manual": "MANUAL"}
    UNTRACKED = ("hold", "manual")
    popover_class = LockPopover

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.state = "off"
        self.detail = ""
        self.rows: list[tuple[str, str]] = []
        self.k_col = Anim(self)
        self.spin = 0.0
        self.pulse = 0.0          # one ring of light on reaching "locked"
        self.prev_col = theme.c("text3")
        # A pill one line high in the window's Tight tier (overhaul section
        # 3): the dot, the word and the value, the title in the tooltip
        # (which always starts with it), so the header is one line at
        # 1024 x 600.
        self.pill = False
        self.setFixedHeight(theme.px(48))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pop: LockPopover | None = None

    def accessible_text(self) -> str:
        # "RX lock: LOCKED" (controls.FocusVisible); the numbers stay in the
        # popover, as they move too often to be announced.
        return f"{self.title}: {self.WORDS.get(self.state, self.state)}"

    def sizeHint(self):
        return QSize(theme.px(150 if self.pill else 196), self.height())

    def minimumSizeHint(self):
        # The longest word whole ("SEARCHING") after the symbol.
        return QSize(int(self._word_x() + self._tag_w() + QFontMetricsF(self.word_font()).horizontalAdvance("SEARCHING")
                         + 10),
                     self.height())

    def set_tier(self, tier: str) -> None:
        pill = tier == "tight"
        if pill != self.pill:
            self.pill = pill
            self.setFixedHeight(theme.px(24 if pill else 48))
            self.updateGeometry()
            self.update()

    def pill_tag(self) -> str:
        return self.title.split("·")[0].strip()

    def _word_x(self) -> float:
        return float(theme.px(24 if self.pill else 40))

    def _tag_w(self) -> float:
        return QFontMetricsF(theme.caps(10)).horizontalAdvance(self.pill_tag()) + theme.px(6) if self.pill else 0.0

    def _symbol_x(self) -> float:
        return float(theme.px(12 if self.pill else 22))

    def set_state(self, st: str, detail, rows: list[tuple[str, str]]):
        if st != self.state:
            self.prev_col = theme.c(self.COLOURS.get(self.state, "text3"))
            self.k_col.value = 0.0
            self.k_col.to(1.0)
            if st == "locked":
                self.pulse = 1.0
            self.state = st
        self.detail = detail
        self.rows = rows
        tip = f"<b>{self.title}: {self.WORDS.get(st, st)}</b><table>" + "".join(
            f"<tr><td style='color:#8794a6;padding-right:10px'>{k}</td><td><b>{v}</b></td></tr>" for k, v in rows) \
            + "</table>"
        self.setToolTip(tip)
        if self.pop is not None and self.pop.isVisible():
            self.pop.fill(self.title, rows)
        self.update()

    def tick(self, dt: float):
        moving = False
        if self.state == "searching":
            self.spin = (self.spin + dt * 300) % 360
            moving = True
        if self.pulse > 0:
            self.pulse = max(0.0, self.pulse - dt * 1.4)
            moving = True
        if moving:
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_popover()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.toggle_popover()
        else:
            super().keyPressEvent(e)

    def toggle_popover(self):
        if self.pop is None:
            self.pop = self.popover_class(self)
        if self.pop.isVisible():
            self.pop.hide()
            return
        self.pop.fill(self.title, self.rows)
        self.pop.adjustSize()
        g = self.mapToGlobal(self.rect().bottomLeft())
        self.pop.move(g.x(), g.y() + 6)
        self.pop.show()

    def word_font(self):
        return theme.font(11.5 if self.pill else 13.5, theme.QFont.Weight.Bold)

    def detail_font(self):
        return theme.font(11 if self.pill else 12, theme.QFont.Weight.Medium, mono=True)

    def detail_layout(self) -> tuple[str, float, float]:
        """(text, x, width) of the value as painted beside the state word,
        text "" when none is drawn.

        The value shares the state's row, never the title's: moving overflow
        up beside the title (the old behaviour) put the two texts on the same
        line with no mutual awareness, so a long error (e.g. "-2.900 kHz")
        silently overlapped "OWN SIGNAL". Eliding within the row that's left
        after the word keeps title/state/value on separate, non-colliding
        regions at any width or value length."""
        if not self.detail:
            return "", 0.0, 0.0
        word = self.WORDS.get(self.state, self.state.upper())
        word_right = self._word_x() + self._tag_w() + QFontMetricsF(self.word_font()).horizontalAdvance(word)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        return self._place_detail(word_right, r.right() - 8, self.detail, QFontMetricsF(self.detail_font()))

    @staticmethod
    def _place_detail(word_right: float, row_right: float, detail, fm: QFontMetricsF,
                       gap: float = 8.0) -> tuple[str, float, float]:
        """Where, if anywhere, the detail value fits to the right of the state
        word on its row. Returns (text, x, width); text is "" when there is
        no usable room (the value stays available via the tooltip/popover
        rather than being drawn somewhere it would collide).

        `detail` may be one string or the same value written shorter and
        shorter (see hz_forms): the longest that fits whole is drawn, and
        only the shortest is ever elided. "SEARCHING -2.900 …" (0.1.3) was
        a number cut off where a coarser one would have fitted."""
        forms = (detail,) if isinstance(detail, str) else tuple(detail)
        avail = row_right - word_right - gap
        if not forms or avail < fm.horizontalAdvance("…"):
            return "", 0.0, 0.0
        for text in forms:
            if fm.horizontalAdvance(text) <= avail:
                return text, word_right + gap, avail
        return fm.elidedText(forms[-1], Qt.TextElideMode.ElideRight, avail), word_right + gap, avail

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        col = mix(self.prev_col, theme.c(self.COLOURS.get(self.state, "text3")), self.k_col.value)
        bg = QColor(col)
        bg.setAlphaF(0.10)
        untracked = self.state in self.UNTRACKED
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 160 if untracked else 90), 1.2 if untracked else 1,
                      Qt.PenStyle.DashLine if untracked else Qt.PenStyle.SolidLine))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2 if self.pill else 10, r.height() / 2 if self.pill else 10)
        cx, cy = self._symbol_x(), r.center().y()
        # The symbols are drawn for a 48 px badge; a pill's are smaller.
        p.translate(cx, cy)
        p.scale(*(2 * (0.62,) if self.pill else (1.0, 1.0)))
        p.translate(-cx, -cy)
        if untracked:
            # Hold: a pause sign. Manual: a knob - the hand is on it.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            if self.state == "hold":
                p.drawRoundedRect(QRectF(cx - 5.5, cy - 7, 4, 14), 1.2, 1.2)
                p.drawRoundedRect(QRectF(cx + 1.5, cy - 7, 4, 14), 1.2, 1.2)
            else:
                p.setPen(QPen(col, 2.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), 7, 7)
                p.drawLine(QPointF(cx, cy), QPointF(cx + 3.5, cy - 6))
        elif self.state == "searching":
            p.setPen(QPen(col, 2.6, cap=Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(cx - 8, cy - 8, 16, 16), int(-self.spin * 16), 100 * 16)
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 60), 2.6))
            p.drawEllipse(QPointF(cx, cy), 8, 8)
        else:
            if self.pulse > 0:
                rr = 8 + (1 - self.pulse) * 12
                ring = QColor(col)
                ring.setAlphaF(0.5 * self.pulse)
                p.setPen(QPen(ring, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            g = QRadialGradient(QPointF(cx, cy), 10)
            glow = QColor(col)
            glow.setAlphaF(0.35 if self.state == "locked" else 0.0)
            g.setColorAt(0, glow)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(cx, cy), 11, 11)
            p.setBrush(col)
            p.drawEllipse(QPointF(cx, cy), 5.5, 5.5)
            if self.state == "locked":
                p.setPen(QPen(theme.c("bg1"), 1.6, cap=Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx - 2.5, cy), QPointF(cx - 0.7, cy + 1.8))
                p.drawLine(QPointF(cx - 0.7, cy + 1.8), QPointF(cx + 2.6, cy - 1.8))
        p.resetTransform()
        wx = self._word_x()
        if self.pill:
            # "RX" or "TX" before the word: the title's first part, so the
            # two pills are told apart without the hover.
            tag = self.pill_tag()
            p.setFont(theme.caps(10))
            p.setPen(theme.c("text3"))
            tw = QFontMetricsF(p.font()).horizontalAdvance(tag)
            p.drawText(QRectF(wx, r.y(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, tag)
            wx += tw + theme.px(6)
            row = QRectF(wx, r.y(), r.width() - wx - 4, r.height())
        else:
            p.setFont(theme.caps(10))
            p.setPen(theme.c("text3"))
            title_font_metrics = QFontMetricsF(p.font())
            title_rect = QRectF(wx, theme.px(6), r.width() - wx - 4, theme.px(14))
            p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter,
                       title_font_metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, title_rect.width()))
            row = QRectF(wx, theme.px(21), r.width() - wx - 4, theme.px(20))
        p.setFont(self.word_font())
        p.setPen(col)
        word = self.WORDS.get(self.state, self.state.upper())
        p.drawText(row, Qt.AlignmentFlag.AlignVCenter, word)
        text, x, w = self.detail_layout()
        if text:
            p.setFont(self.detail_font())
            p.setPen(theme.c("text2"))
            p.drawText(QRectF(x, row.y(), w, row.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       text)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 9, 9)


# ------------------------------------------------------------- beacon lock
MODES = [("auto", "Auto"), ("hold", "Hold"), ("manual", "Manual")]
NUDGES = (-100.0, -10.0, 10.0, 100.0)


def parse_hz(text: str) -> float:
    """A typed rxCorr: Hz, or kHz with a k ("-27454", "-27.454k", "+1 800")."""
    t = text.strip().lower().replace(" ", "").replace(",", ".").removesuffix("hz")
    k = t.endswith("k")
    try:
        v = float(t.removesuffix("k"))
    except ValueError:
        raise ValueError(_("{text} is not a number of hertz").format(text=repr(text))) from None
    return v * 1000.0 if k else v


class RxPopover(LockPopover):
    """The beacon-lock badge's details: the numbers, the mode, and in Manual
    the controls that set rxCorr - next to the error they correct, which is
    what the operator nudging by hand is watching."""

    def __init__(self, badge: "RxBadge"):
        super().__init__(badge)
        self.badge = badge
        self.mode = Segmented(MODES, badge.mode, compact=True)
        self.mode.picked.connect(badge.mode_chosen)
        self.lay.addSpacing(6)
        self.lay.addWidget(self.mode)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setMaximumWidth(300)
        self.lay.addWidget(self.note)
        self.manual = QWidget()
        ml = QVBoxLayout(self.manual)
        ml.setContentsMargins(0, 4, 0, 0)
        ml.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.nudge_buttons = []
        for hz in NUDGES:
            b = Button(f"{hz:+.0f}", small=True)
            b.setToolTip(self.tr("rxCorr {hz:+.0f} Hz (the wheel over the badge: 10 Hz, Shift 1 Hz)").format(hz=hz))
            b.clicked.connect(lambda hz=hz: badge.nudged.emit(hz))
            row.addWidget(b)
            self.nudge_buttons.append(b)
        ml.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.field = QLineEdit()
        self.field.setPlaceholderText(self.tr("rxCorr in Hz, e.g. -27454"))
        self.field.returnPressed.connect(self._typed)
        go = Button(self.tr("Set"), small=True)
        go.clicked.connect(self._typed)
        row.addWidget(self.field, 1)
        row.addWidget(go)
        ml.addLayout(row)
        self.lay.addWidget(self.manual)

    def _typed(self):
        try:
            v = parse_hz(self.field.text())
        except ValueError as e:
            self.note.setText(str(e))
            self.note.setStyleSheet(f"color: {theme.t()['err']};")
            return
        self.badge.corr_typed.emit(v)

    def fill(self, title, rows):
        super().fill(title, rows)
        b = self.badge
        self.mode.set_value(b.mode)
        self.manual.setVisible(b.mode == "manual")
        if not self.field.hasFocus():
            self.field.setText(f"{b.corr:.1f}")
        self.note.setStyleSheet(f"color: {theme.t()['text3']};")
        self.note.setText({
            "auto": "Auto: beacon lock follows the beacon. Right-click the beacon on a scope if it is "
                    "following something else.",
            "hold": "Hold: rxCorr is kept exactly as it is; nothing follows the LNB's drift. H returns to Auto.",
            "manual": "Manual: nothing follows the drift. Nudge rxCorr until the error above is near zero.",
        }.get(b.mode, ""))
        self.adjustSize()


class RxBadge(LockBadge):
    """The beacon-lock badge. `mode` and `corr` (beaconMode, rxCorr) are
    set by the window with the state; what the operator does here comes
    back as signals, and the window turns them into settings."""

    mode_chosen = pyqtSignal(str)
    nudged = pyqtSignal(float)
    corr_typed = pyqtSignal(float)
    wheel_refused = pyqtSignal()       # the wheel, outside Manual
    popover_class = RxPopover

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.mode = "auto"
        self.corr = 0.0

    def wheelEvent(self, e):
        # Shift turns a vertical wheel horizontal on some platforms (Qt
        # reports it in x), so either counts.
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        e.accept()
        if self.mode != "manual":
            self.wheel_refused.emit()
            return
        step = 1.0 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 10.0
        self.nudged.emit(step if d > 0 else -step)
