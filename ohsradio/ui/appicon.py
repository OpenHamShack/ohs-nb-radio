"""Radio's icon: packaging/openhamshack-radio.svg, found and loaded by
ohscore/ui/appicon.py (which explains where it looks), and the simplified
painted version that stands in when no file or SVG plugin is there."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from ohscore.ui import appicon as loader

_HERE = Path(__file__).resolve()


def svg_path() -> Path | None:
    return loader.find("openhamshack-radio", _HERE.parents[1])      # parents[1]: .../ohsradio


def _painted(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    g = QLinearGradient(0, 0, 0, 64)
    g.setColorAt(0, QColor("#14261f"))
    g.setColorAt(1, QColor("#070a12"))
    p.setPen(QPen(QColor("#2a5844"), 1.5))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(2.75, 2.75, 58.5, 58.5), 12, 12)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#05070c"))
    p.drawRoundedRect(QRectF(8, 41, 48, 16), 3.5, 3.5)
    for x, w, c in ((12, 2, "#fbb33a"), (19, 7, "#d23a4a"), (33, 3, "#fbb33a"), (42, 9, "#f0602a")):
        p.setBrush(QColor(c))
        p.drawRect(QRectF(x, 41, w, 16))
    pen = QPen(QColor("#dfe6ef"), 2.4, cap=Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(32, 14, 32, 38)
    p.drawLine(22, 14, 42, 14)
    p.drawLine(25, 20, 39, 20)
    p.drawLine(27, 26, 37, 26)
    p.setPen(QPen(QColor("#3ddc84"), 2.2, cap=Qt.PenCapStyle.RoundCap))
    path = QPainterPath()
    path.moveTo(17, 12)
    path.quadTo(11, 19, 17, 26)
    path.moveTo(47, 12)
    path.quadTo(53, 19, 47, 26)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffb547"))
    p.drawEllipse(QRectF(29.4, 6.9, 5.2, 5.2))
    p.end()
    return pm


def app_icon() -> QIcon:
    return loader.load(svg_path(), _painted)


def pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    return loader.pixmap(app_icon(), size, dpr)
