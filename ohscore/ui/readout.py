"""The frequency readout: the dial in large figures, the app's second line
beneath (NB: the uplink).

Each digit is drawn centred in a fixed-width cell, so the number never
shifts sideways as it changes whatever the font's figures are like. The
wheel over a digit tunes by that digit's place value; a click opens an
editor that accepts the forms operators actually type (the app's
Face.parse_freq). How the digits are grouped is the app's too.

Forms, one per window tier (ohscore/ui/layoutrules.py; overhaul section 3):
"full" and "compact" are two rows - a caption, the digits, then the
app's second line and the RIT/XIT/SPLIT/STEP chips; "tight" is one line,
the digits then the second line and the chips beside them, for a header
of one line at 1024 x 600. In every form the digits are sized to the room
they have, never the other way round: a fixed 58 px lost the last digit
when the window was narrow (Mac FINDINGS 9: "10 489.540 00") and spilled
out of the widget at 130 % text. Every size here is at the text scale.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from . import theme
from .controls import Anim

STEPS = [1, 10, 50, 100, 500, 1000, 5000, 10000]
FORMS = ("full", "compact", "tight")

# Heights at 100 % text: two rows, or Tight's one line.
TALL_H, LINE_H = 104, 52
# The least the digits shrink to (px at 100 %) before the readout asks the
# layout for more room: about the height of the status strip's text times
# two, still read at a glance across the room.
MIN_BIG = 26.0


class Readout(QWidget):
    tune = pyqtSignal(float)            # absolute vfo Hz
    step_clicked = pyqtSignal()
    step_wheel = pyqtSignal(int)
    chip_clicked = pyqtSignal(str)      # "rit", "xit", "split"

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.step = 100
        self.hover_place: int | None = None
        self.cells: list[tuple[QRectF, int | None]] = []   # (rect, place value exponent) per drawn char
        self.chips: dict[str, QRectF] = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.form = "full"
        self.setFixedHeight(theme.px(TALL_H))
        # Where the digits were last painted: a click there opens the editor.
        self.digits_rect = QRectF()
        self.flash = Anim(self)
        self.kbd_focus = False
        self.edit = QLineEdit(self)
        self.edit.hide()
        self.edit.setPlaceholderText(bridge.face.freq_hint)
        self.edit.installEventFilter(self)
        bridge.changed.connect(self._changed)

    def sizeHint(self):
        return QSize(theme.px(520), self.height())

    def minimumSizeHint(self):
        """Every digit at MIN_BIG, and in Tight the second line and the
        STEP chip beside them: what the layout must leave the readout so
        that nothing it says is lost."""
        w = self._row_width(MIN_BIG * theme.scale()) + 4
        if self.form == "tight":
            w += self._rest_width(always_only=True)
        return QSize(int(w + 1), self.height())

    def set_form(self, form: str) -> None:
        """The window's tier: "full", "compact" (both two rows) or "tight"
        (one line)."""
        if form not in FORMS or form == self.form:
            return
        self.form = form
        self.edit.hide()
        self.setFixedHeight(theme.px(LINE_H if form == "tight" else TALL_H))
        self.updateGeometry()
        self.update()

    # ----------------------------------------------------------- measuring
    @staticmethod
    def _font(final_px: float, weight=None, mono: bool = False, spacing: float = 0.0):
        """A font `final_px` high on screen (theme.font takes the size at
        100 % and scales it; the readout works out its sizes on screen)."""
        return theme.font(final_px / theme.scale(), weight if weight is not None else theme.QFont.Weight.Medium,
                          mono=mono, spacing=spacing)

    def _cell_widths(self, big: float) -> tuple[float, float]:
        fm_b = QFontMetricsF(self._font(big))
        fm_s = QFontMetricsF(self._font(big * 0.62))
        return (max(fm_b.horizontalAdvance(d) for d in "0123456789") * 1.02,
                max(fm_s.horizontalAdvance(d) for d in "0123456789") * 1.02)

    def _row_width(self, big: float, hz: int | None = None) -> float:
        """The digits' width at size `big` (px on screen), as paintEvent lays
        them out."""
        if hz is None:
            hz = int(round(float(self.bridge.st.get("vfo") or 0.0)))
        cw_b, cw_s = self._cell_widths(big)
        x = 0.0
        for text, _top, kind in self.bridge.face.digit_groups(hz):
            if kind in ("gap", "gapS"):
                x += cw_b * (0.32 if kind == "gap" else 0.22)
            elif kind == "dot":
                x += cw_b * 0.42
            else:
                x += len(text) * (cw_s if kind == "small" else cw_b)
        return x

    def _big_px(self) -> float:
        """The digits' size on screen: as tall as the form allows (58 px at
        100 % in two rows), and no wider than the room there is."""
        s = theme.scale()
        h = self.height()
        if self.form == "tight":
            big = h * 0.66
            room = self.width() - 4 - self._rest_width(always_only=True)
        else:
            big = min(58.0 * s, h * 0.5)
            room = self.width() - 4
        ref = 100.0
        fit = ref * room / max(1.0, self._row_width(ref))
        return max(MIN_BIG * s * 0.8, min(big, fit))

    def _chip_font(self):
        return theme.font(10.5, theme.QFont.Weight.Bold, spacing=0.6)

    def _chips(self) -> list[tuple[str, str, bool, str]]:
        st = self.bridge.st
        rit = float(st.get("rit") or 0)
        xit = float(st.get("xit") or 0)
        return [("rit", f"RIT {rit:+.0f}" if st.get("ritOn") else "RIT", bool(st.get("ritOn")), "accent"),
                # XIT in the accent as RIT is: an offset switched on is a
                # setting, not the air (it was red, overhaul section 5.3).
                ("xit", f"XIT {xit:+.0f}" if st.get("xitOn") else "XIT", bool(st.get("xitOn")), "accent"),
                ("split", "SPLIT", bool(st.get("split")), "warn"),
                ("step", f"STEP {self.step if self.step < 1000 else f'{self.step / 1000:g}'}"
                         f"{' Hz' if self.step < 1000 else ' kHz'}", True, "text2")]

    def _secondary_parts(self):
        """(caption, text, caption font, text font) of the app's second line, or None."""
        sec = self.bridge.face.secondary(self.bridge.st)
        if sec is None:
            return None
        return sec[0], sec[1], theme.caps(10), theme.font(15, theme.QFont.Weight.Medium, mono=True)

    def _rest_width(self, always_only: bool = False) -> float:
        """Tight's line after the digits: the second line and the chips
        (`always_only`: only what is never dropped - the second line and
        STEP - plus the chips that are on, which say something is set)."""
        gap = theme.px(14)
        w = gap
        sec = self._secondary_parts()
        if sec is not None:
            cap, text, fc, ft = sec
            w += QFontMetricsF(fc).horizontalAdvance(cap) + theme.px(6) + QFontMetricsF(ft).horizontalAdvance(text) + gap
        fmc = QFontMetricsF(self._chip_font())
        for key, text, on, _col in self._chips():
            if key == "step" or on or not always_only:
                w += fmc.horizontalAdvance(text) + theme.px(14) + theme.px(6)
        return w

    def _changed(self, ch):
        if any(k in ch for k in ("vfo", "txDial", "rit", "ritOn", "xit", "xitOn", "split", "segment", "keyed")
               + self.bridge.face.secondary_keys + self.bridge.face.on_air_keys):
            self.update()

    def set_step(self, step: int):
        self.step = step
        self.update()

    # ----------------------------------------------------------- editing
    def open_editor(self):
        big = self._big_px()
        self.edit.setFont(self._font(big * 0.62, theme.QFont.Weight.DemiBold, mono=True))
        eh = int(min(self.height() - 2, big + theme.px(10)))
        y = (self.height() - eh) // 2 if self.form == "tight" else theme.px(18)
        self.edit.setGeometry(0, y, min(self.width(), theme.px(420)), eh)
        self.edit.setText(f"{float(self.bridge.st.get('vfo', 0)) / 1e6:.6f}")
        self.edit.selectAll()
        self.edit.show()
        self.edit.setFocus()

    def _commit(self):
        try:
            f = self.bridge.face.parse_freq(self.edit.text())
        except ValueError as e:
            self.bridge.say(str(e))
            self.edit.selectAll()
            return
        self.edit.hide()
        self.tune.emit(f)
        self.setFocus()

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Taken here, not through returnPressed: QLineEdit emits that
            # and then ignores the key, so a dialog's default button gets
            # it - which sent it on to this widget, whose Return opens the
            # editor. A typed frequency tuned the radio and reopened the
            # editor at once with the new one selected (Mac FINDINGS 27).
            self._commit()
            return True
        if obj is self.edit and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self.edit.hide()
            self.setFocus()
            return True
        if obj is self.edit and ev.type() == ev.Type.FocusOut:
            self.edit.hide()
        return False

    # ----------------------------------------------------------- mouse
    def _place_at(self, pos) -> int | None:
        for r, place in self.cells:
            if place is not None and r.adjusted(-1, 0, 1, 0).contains(pos):
                return place
        return None

    def mouseMoveEvent(self, e):
        pl = self._place_at(e.position())
        if pl != self.hover_place:
            self.hover_place = pl
            self.setCursor(Qt.CursorShape.SizeVerCursor if pl is not None else
                           Qt.CursorShape.PointingHandCursor if self._chip_at(e.position()) else
                           Qt.CursorShape.ArrowCursor)
            self.update()

    def _chip_at(self, pos) -> str | None:
        for k, r in self.chips.items():
            if r.contains(pos):
                return k
        return None

    def leaveEvent(self, e):
        self.hover_place = None
        self.update()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d:
            return
        chip = self._chip_at(e.position())
        if chip in ("rit", "xit"):
            # The wheel over RIT/XIT sets the offset, 10 Hz a click, and turns it on.
            k = chip
            v = float(self.bridge.st.get(k) or 0) + (10 if d > 0 else -10)
            self.bridge.set(**{k: max(-5000.0, min(5000.0, v)), k + "On": True})
            e.accept()
            return
        if chip == "step":
            self.step_wheel.emit(1 if d > 0 else -1)
            e.accept()
            return
        pl = self._place_at(e.position())
        step = 10 ** pl if pl is not None else self.step
        vfo = float(self.bridge.st.get("vfo", 0))
        self.tune.emit(vfo + (step if d > 0 else -step))
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        chip = self._chip_at(e.position())
        if chip == "step":
            self.step_clicked.emit()
        elif chip:
            self.chip_clicked.emit(chip)
        elif self.digits_rect.adjusted(-4, -6, 4, 8).contains(e.position()):
            self.open_editor()

    def focusInEvent(self, e):
        # Ring only when focus came from the keyboard: a click already says where you are.
        self.kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.kbd_focus = False
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_editor()
        else:
            super().keyPressEvent(e)

    # ----------------------------------------------------------- paint
    def title(self) -> str:
        """The line above the digits: "Downlink   ● on air" while radiating."""
        face = self.bridge.face
        if face.on_air(self.bridge.st):
            return self.tr("{title}   ● on air").format(title=face.readout_title())
        return face.readout_title()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.bridge.st
        vfo = float(st.get("vfo") or 0.0)
        keyed = self.bridge.face.on_air(st)     # radiating, not merely queued (Face.on_air)
        tight = self.form == "tight"
        big = self._big_px()
        face = self.bridge.face
        seg = face.segment_at(vfo)
        if not tight:
            # Tight has no caption line: the digits turn red on the air,
            # as in every form, and the TX tile beside them says ON AIR.
            p.setFont(theme.caps(10.5))
            p.setPen(theme.c("tx") if keyed else theme.c("text3"))
            p.drawText(QRectF(2, 0, self.width() - 4, theme.px(16)), Qt.AlignmentFlag.AlignVCenter, self.title())
        hz = int(round(vfo))
        f_big = self._font(big)
        f_small = self._font(big * 0.62)
        fm_b, fm_s = QFontMetricsF(f_big), QFontMetricsF(f_small)
        cw_b, cw_s = self._cell_widths(big)
        x = 0.0
        y_top = (self.height() - big) / 2.0 if tight else float(theme.px(18))
        base_b = y_top + fm_b.ascent() * 0.98
        self.cells = []
        for text, top_place, kind in face.digit_groups(hz):
            small = kind == "small"
            p.setFont(f_small if small else f_big)
            if kind in ("gap", "gapS"):
                x += cw_b * (0.32 if kind == "gap" else 0.22)
                continue
            if kind == "dot":
                p.setPen(theme.c("text2"))
                w = cw_b * 0.42
                p.drawText(QRectF(x, y_top, w, big * 1.2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                           ".")
                x += w
                continue
            for i, ch in enumerate(text):
                place = top_place - i if top_place is not None else None
                if kind == "dim" or (place is not None and not face.tunable_place(place)):
                    place = None
                cw = cw_s if small else cw_b
                r = QRectF(x, y_top + (big - big * 0.62) * (0.80 if small else 0), cw, (big * 0.62 if small else big))
                hot = place is not None and place == self.hover_place
                if hot:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(theme.c("accent", 0.14))
                    p.drawRoundedRect(QRectF(r.x() - 1, y_top - 2, r.width() + 2, min(big + 8, self.height() - y_top + 2)),
                                      4, 4)
                    p.setBrush(theme.c("accent"))
                    p.drawRoundedRect(QRectF(r.x() + 3, min(y_top + big + 4, self.height() - 3), r.width() - 6, 2.5), 1, 1)
                col = {"dim": theme.c("text3"), "small": theme.c("text2")}.get(kind, theme.c("text"))
                if keyed and kind == "bright":
                    col = theme.c("tx")
                p.setPen(col)
                fm = fm_s if small else fm_b
                p.drawText(QRectF(r.x(), base_b - fm.ascent(), cw, fm.height()), Qt.AlignmentFlag.AlignHCenter, ch)
                self.cells.append((r, place))
                x += cw
        self.digits_rect = QRectF(0, y_top, x, big)
        # The app's second line (NB: the uplink), then the chips: under the
        # digits in two rows, beside them in Tight.
        row_h = float(theme.px(20))
        if tight:
            y2 = (self.height() - row_h) / 2.0
            cx = x + theme.px(14)
        else:
            y2 = y_top + big + theme.px(12)
            cx = 2.0
        sec = self._secondary_parts()
        if sec is not None:
            caption, utext, fc, ft = sec
            p.setFont(fc)
            p.setPen(theme.c("text3"))
            cap_w = QFontMetricsF(fc).horizontalAdvance(caption)
            p.drawText(QRectF(cx, y2, cap_w + 2, row_h), Qt.AlignmentFlag.AlignVCenter, caption)
            p.setFont(ft)
            p.setPen(theme.c("tx") if keyed else theme.c("text2"))
            ux = cx + max(cap_w + theme.px(6), theme.px(26))
            uw = QFontMetricsF(ft).horizontalAdvance(utext)
            p.drawText(QRectF(ux, y2, uw + 2, row_h), Qt.AlignmentFlag.AlignVCenter, utext)
            cx = ux + uw + theme.px(14)
        self.chips = {}
        p.setFont(self._chip_font())
        fmc = QFontMetricsF(p.font())
        chips = self._chips()
        pad, gap = theme.px(14), theme.px(6)
        room = self.width() - cx
        if tight or sum(fmc.horizontalAdvance(c[1]) + pad + gap for c in chips) > room:
            # Short of room: an offset that is off says nothing (r, x and s
            # still switch it on); one that is on, and the step, stay.
            chips = [c for c in chips if c[0] == "step" or c[2]]
        for key, text, on, col in chips:
            w = fmc.horizontalAdvance(text) + pad
            if cx + w > self.width():
                break
            r = QRectF(cx, y2 + 1, w, row_h - 1)
            self.chips[key] = r
            if key == "step":
                p.setPen(QPen(theme.c("line2"), 1))
                p.setBrush(theme.c("bg2"))
                p.drawRoundedRect(r, 4, 4)
                p.setPen(theme.c("text2"))
            elif on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.c(col, 0.18))
                p.drawRoundedRect(r, 4, 4)
                p.setPen(theme.c(col))
            else:
                p.setPen(QPen(theme.c("line"), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r, 4, 4)
                p.setPen(theme.c("text3"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            cx += w + gap
        if seg:
            key = theme.segment_colour_key(seg["label"], seg["modes"] or None)
            p.setFont(theme.font(12))
            fms = QFontMetricsF(p.font())
            text = seg["label"]
            x0 = cx + theme.px(8)
            if x0 + fms.horizontalAdvance(text) + theme.px(14) < self.width():
                d = theme.px(7)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.c(key))
                p.drawEllipse(QRectF(x0, y2 + (row_h - d) / 2, d, d))
                p.setPen(theme.c("text2"))
                p.drawText(QRectF(x0 + d + theme.px(5), y2, self.width() - x0 - d - theme.px(5), row_h),
                           Qt.AlignmentFlag.AlignVCenter, text)
        if self.hasFocus() and self.kbd_focus and not self.edit.isVisible():
            p.setPen(QPen(theme.c("accent", 0.5), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
