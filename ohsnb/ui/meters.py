"""The own-signal-vs-beacon meter: the QO-100 meter. The meters every app
has (BarMeter, and the Ballistic they ride on) are ohscore/ui/meters.py."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ohscore.ui import theme
from ohscore.ui.meters import Ballistic


class BeaconMeter(QWidget):
    """Our own downlink against the beacon: the one QO-100 rule an operator
    can break without knowing. The scale is dB relative to the beacon; the
    beacon itself is the hard line at 0, the configured margin a dashed line
    below it, and the region between and above is coloured accordingly."""

    LO, HI = -30.0, 10.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.b = Ballistic(self.LO, self.HI, attack=8, release=2)
        self.margin = 6.0
        self.value: float | None = None
        self.keyed = False
        self.beacon_dbfs: float | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rows = self._rows()
        self.setFixedHeight(int(self.rows["height"]))
        self.setToolTip(self.tr("Your own downlink compared with the beacon, measured by TX lock while you transmit.\n"
                                "QO-100 rule: never stronger than the beacon. The dashed line is the margin set in "
                                "Settings; 'limit' trims TX gain to stay below it."))

    # Every line's height comes from its font as drawn, so the meter grows
    # with the text size (Settings › Display). It was laid out in fixed
    # pixels for 100 %: at 130 % the BEACON tag and the "beacon -40.0 dBFS"
    # line were cut off at the bottom, and the hint ran into the margin's
    # dashed line, on the narrow rail of a 1332 x 780 window.
    @staticmethod
    def _fonts() -> dict:
        return {"title": theme.caps(10), "value": theme.font(15, theme.QFont.Weight.Bold, mono=True),
                "hint": theme.font(11), "tag": theme.font(9.5, theme.QFont.Weight.Bold, spacing=0.8),
                "tick": theme.font(9.5, mono=True), "foot": theme.font(10.5)}

    def _rows(self) -> dict:
        """The top of each line and the meter's height, in pixels."""
        f = {k: QFontMetricsF(v).height() for k, v in self._fonts().items()}
        top = max(f["title"], f["value"])
        hint = top + 1
        bar = hint + max(f["hint"], f["tag"]) + 3
        ticks = bar + 14 + 3
        foot = ticks + f["tick"] + 1
        return {"top": top, "hint": hint, "hint_h": max(f["hint"], f["tag"]), "bar": bar, "ticks": ticks,
                "tick_h": f["tick"], "foot": foot, "foot_h": f["foot"], "height": math.ceil(foot + f["foot"] + 1)}

    def sizeHint(self):
        return QSize(260, self.height())

    def set_value(self, v):
        self.value = v
        self.b.set(v)

    def tick(self, dt):
        if self.b.step(dt):
            self.update()

    def _x(self, tr: QRectF, v: float) -> float:
        return tr.x() + (v - self.LO) / (self.HI - self.LO) * tr.width()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        fonts, rows = self._fonts(), self.rows
        v = self.value
        if v is None:
            txt, col = "—", theme.c("text3")
        else:
            col = theme.c("err") if v > 0 else theme.c("warn") if v > -self.margin else theme.c("ok")
            txt = self.tr("{vs:+.1f} dB").format(vs=v)
        # The figure first, whole; the title in what is left of the line.
        p.setFont(fonts["value"])
        vw = min(float(w), QFontMetricsF(fonts["value"]).horizontalAdvance(txt) + 1)
        p.setPen(col)
        p.drawText(QRectF(w - vw, 0, vw, rows["top"]), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   txt)
        p.setFont(fonts["title"])
        p.setPen(theme.c("text3"))
        room = max(0.0, w - vw - 8)
        title = QFontMetricsF(fonts["title"]).elidedText(self.tr("Own signal vs beacon"), Qt.TextElideMode.ElideRight,
                                                         room)
        p.drawText(QRectF(0, 0, room, rows["top"]), Qt.AlignmentFlag.AlignVCenter, title)
        tr = QRectF(0, rows["bar"], w, 14)
        hint = QRectF(0, rows["hint"], w, rows["hint_h"])
        xm, x0 = self._x(tr, -self.margin), self._x(tr, 0.0)
        tag = self.tag_box(tr)
        # Zones.
        p.setPen(Qt.PenStyle.NoPen)
        for a, b, key in ((tr.x(), xm, "ok"), (xm, x0, "warn"), (x0, tr.right(), "err")):
            g = QLinearGradient(a, 0, b, 0)
            g.setColorAt(0, theme.c(key, 0.10))
            g.setColorAt(1, theme.c(key, 0.22))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(a, tr.y(), b - a, tr.height()))
        if v is not None:
            xv = self._x(tr, self.b.value)
            g = QLinearGradient(tr.x(), 0, tr.right(), 0)
            k_m = (xm - tr.x()) / tr.width()
            k_0 = (x0 - tr.x()) / tr.width()
            g.setColorAt(0, theme.c("ok", 0.55))
            g.setColorAt(max(0.0, k_m - 0.001), theme.c("ok"))
            g.setColorAt(k_m, theme.c("warn"))
            g.setColorAt(max(k_m, k_0 - 0.001), theme.c("warn"))
            g.setColorAt(k_0, theme.c("err"))
            g.setColorAt(1, theme.c("err"))
            p.setBrush(QBrush(g))
            p.drawRect(QRectF(tr.x(), tr.y() + 2, max(0.0, xv - tr.x()), tr.height() - 4))
            # Needle.
            p.setBrush(theme.c("text"))
            needle = QPainterPath()
            needle.moveTo(xv, tr.y() - 2)
            needle.lineTo(xv - 5, tr.y() - 9)
            needle.lineTo(xv + 5, tr.y() - 9)
            needle.closeSubpath()
            p.drawPath(needle)
            p.drawRect(QRectF(xv - 1, tr.y() - 2, 2, tr.height() + 4))
        else:
            # Up to the beacon line, which rises through this line.
            p.setPen(theme.c("text3"))
            p.setFont(fonts["hint"])
            room = max(0.0, min(x0, tag.left()) - 6 - (tr.x() + 6))
            words = QFontMetricsF(fonts["hint"]).elidedText(self.tr("Measured while you transmit"),
                                                            Qt.TextElideMode.ElideRight, room)
            p.drawText(QRectF(tr.x() + 6, hint.y(), room, hint.height()), Qt.AlignmentFlag.AlignLeft |
                       Qt.AlignmentFlag.AlignVCenter, words)
        # The beacon line - the one that must never be crossed.
        p.setPen(QPen(theme.c("beacon"), 2.5))
        p.drawLine(QPointF(x0, hint.y() + 2), QPointF(x0, tr.bottom() + 3))
        p.setFont(fonts["tag"])
        p.setPen(theme.c("beacon"))
        p.drawText(tag, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.tr("BEACON"))
        p.setPen(QPen(theme.c("warn"), 1.2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(xm, tr.y() - 4), QPointF(xm, tr.bottom() + 3))
        self._paint_ticks(p, tr, fonts["tick"])
        if self.beacon_dbfs is not None and self.beacon_dbfs > -199:
            p.setFont(fonts["foot"])
            p.setPen(theme.c("text3"))
            p.drawText(QRectF(0, rows["foot"], w, rows["foot_h"]), Qt.AlignmentFlag.AlignRight,
                       self.tr("beacon {dbfs:.1f} dBFS").format(dbfs=self.beacon_dbfs))

    def tag_box(self, tr: QRectF) -> QRectF:
        """Where the BEACON tag goes: right of the beacon line, or left of
        it when the room to the right is too small for the word (a narrow
        rail in a longer language)."""
        x0 = self._x(tr, 0.0)
        tw = QFontMetricsF(self._fonts()["tag"]).horizontalAdvance(self.tr("BEACON")) + 1
        x = x0 + 4 if x0 + 4 + tw <= self.width() else max(0.0, x0 - 4 - tw)
        return QRectF(x, self.rows["hint"], tw, self.rows["hint_h"])

    def tick_labels(self, tr: QRectF, font) -> list[tuple[QRectF, str, str]]:
        """The scale's labels as drawn: (box, text, colour token). The
        margin's figure comes first and the scale gives way to it: a tick
        whose figure would touch one already placed is left out (at 130 %
        on the narrow rail, "-10" and "-6" ran together)."""
        fm = QFontMetricsF(font)
        y, h, w = self.rows["ticks"], self.rows["tick_h"], self.width()
        out: list[tuple[QRectF, str, str]] = []

        def place(x: float, lab: str, key: str) -> None:
            lw = fm.horizontalAdvance(lab)
            box = QRectF(max(0.0, min(w - lw - 1, x - lw / 2)), y, lw + 1, h)
            if all(box.right() + 6 < o.left() or o.right() + 6 < box.left() for o, _l, _k in out):
                out.append((box, lab, key))

        place(self._x(tr, -self.margin), f"−{self.margin:g}", "warn")
        for t in (-30, -20, -10, 0, 10):
            place(self._x(tr, t), f"{t:+d}" if t else "0", "text3")
        return out

    def _paint_ticks(self, p: QPainter, tr: QRectF, font) -> None:
        p.setFont(font)
        for box, lab, key in self.tick_labels(tr, font):
            p.setPen(theme.c(key))
            p.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lab)
