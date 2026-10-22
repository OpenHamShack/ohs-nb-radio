"""Meters with real ballistics.

The engine's meter feed is 10 Hz; drawn raw it twitches. Each meter here
chases its target with a fast attack and a slow release (an analogue
meter's feel, and what the eye reads as "level"), and keeps a peak marker
that holds for 1.5 s and then falls. The motion is integrated on the
bridge's frame tick, so meters animate at the display rate without a timer
of their own, and stop repainting once they have settled.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import theme


class Ballistic:
    def __init__(self, lo: float, hi: float, attack: float = 18.0, release: float = 3.5):
        self.lo, self.hi = lo, hi
        self.attack, self.release = attack, release
        self.value = lo
        self.target = lo
        self.peak = lo
        self.hold = 0.0
        self.valid = False

    def set(self, v):
        if v is None:
            self.valid = False
            self.target = self.lo
            return
        self.valid = True
        self.target = max(self.lo, min(self.hi, float(v)))

    def step(self, dt: float) -> bool:
        """Advance; True if anything visibly moved."""
        before = (self.value, self.peak)
        k = self.attack if self.target > self.value else self.release
        self.value += (self.target - self.value) * min(1.0, dt * k)
        if self.value >= self.peak:
            self.peak, self.hold = self.value, 1.5
        else:
            self.hold -= dt
            if self.hold <= 0:
                self.peak = max(self.value, self.peak - (self.hi - self.lo) * 0.25 * dt)
        span = (self.hi - self.lo) or 1.0
        return abs(before[0] - self.value) / span > 0.0008 or abs(before[1] - self.peak) / span > 0.0008


class BarMeter(QWidget):
    """Label and value on top, a bar beneath, a scale under that.
    zones: [(from, to, colour token)] colour the bar by where it reaches."""

    def __init__(self, label: str, lo: float, hi: float, fmt=lambda v: f"{v:.0f}", ticks=(),
                 zones=(), unit: str = "", parent=None, compact: bool = False):
        super().__init__(parent)
        self.label, self.fmt, self.ticks, self.zones, self.unit = label, fmt, ticks, zones, unit
        self.b = Ballistic(lo, hi)
        self.text_value: float | None = None
        self.active = True
        self.cap: float | None = None
        self.compact = compact
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(40 if compact else 50)

    def sizeHint(self):
        return QSize(220, self.height())

    def set_value(self, v):
        self.text_value = v
        self.b.set(v)

    def set_active(self, on: bool):
        if on != self.active:
            self.active = on
            self.update()

    def tick(self, dt: float):
        if self.b.step(dt):
            self.update()

    def _colour(self, v: float) -> QColor:
        for a, b, key in self.zones:
            if a <= v <= b:
                return theme.c(key)
        return theme.c("accent")

    def value_text(self) -> str:
        """The figure at the top right. The S-meter (smeter.py) says it in
        its own units; every other meter is fmt + unit."""
        on = self.active and self.b.valid
        txt = (self.fmt(self.text_value) if self.text_value is not None and on else "—")
        if self.unit and on and self.text_value is not None:
            txt += " " + self.unit
        return txt

    def tick_label(self, v: float) -> str:
        return f"{v:g}"

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_bar(p)

    def paint_bar(self, p: QPainter):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        on = self.active and self.b.valid
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(0, 0, w * 0.6, 16), Qt.AlignmentFlag.AlignVCenter, self.label)
        p.setFont(theme.font(13, theme.QFont.Weight.DemiBold, mono=True))
        p.setPen(theme.c("text") if on else theme.c("text3"))
        p.drawText(QRectF(w * 0.3, 0, w * 0.7, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self.value_text())
        tr = QRectF(0, 21, w, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("bg3"))
        p.drawRoundedRect(tr, 3, 3)
        b = self.b
        span = (b.hi - b.lo) or 1.0

        def xv(v):
            return tr.x() + (v - b.lo) / span * tr.width()

        # Faint zone tints so the scale reads even with the bar empty.
        for a, z, key in self.zones:
            col = theme.c(key, 0.13)
            p.setBrush(col)
            p.drawRect(QRectF(xv(a), tr.y(), xv(z) - xv(a), tr.height()))
        if on:
            g = QLinearGradient(tr.x(), 0, tr.right(), 0)
            if self.zones:
                for a, z, key in self.zones:
                    g.setColorAt(max(0.0, min(1.0, (a - b.lo) / span)), theme.c(key))
                    g.setColorAt(max(0.0, min(1.0, (z - b.lo) / span)), theme.c(key))
            else:
                g.setColorAt(0, theme.c("accent", 0.6))
                g.setColorAt(1, theme.c("accent"))
            clip = QPainterPath()
            clip.addRoundedRect(tr, 3, 3)
            p.save()
            p.setClipPath(clip)
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(tr.x(), tr.y(), xv(b.value) - tr.x(), tr.height()))
            p.restore()
            px = xv(b.peak)
            p.setBrush(theme.c("text"))
            p.drawRoundedRect(QRectF(px - 1.25, tr.y() - 2, 2.5, tr.height() + 4), 1, 1)
        if self.cap is not None:
            # A limit (Radio's PA temperature that unkeys), amber as the
            # sliders' ceilings are: red is for the air.
            x = xv(self.cap)
            p.setPen(QPen(theme.c("limit"), 2))
            p.drawLine(QPointF(x, tr.y() - 3), QPointF(x, tr.bottom() + 3))
        if not self.compact:
            p.setFont(theme.font(9.5, mono=True))
            p.setPen(theme.c("text3"))
            fm = QFontMetricsF(p.font())
            for v in self.ticks:
                x = xv(v)
                lab = self.tick_label(v)
                lw = fm.horizontalAdvance(lab)
                lx = max(0.0, min(w - lw, x - lw / 2))
                p.drawText(QRectF(lx, 32, lw + 2, 14), Qt.AlignmentFlag.AlignLeft, lab)
