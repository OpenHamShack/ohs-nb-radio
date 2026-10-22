"""QO-100 NB's icon: packaging/openhamshack-nb.svg, found and loaded by
ohscore/ui/appicon.py (which explains where it looks), and the simplified
painted version that stands in when no file or SVG plugin is there."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from ohscore.ui import appicon as loader

_HERE = Path(__file__).resolve()


def svg_path() -> Path | None:
    return loader.find("openhamshack-nb", _HERE.parents[1])      # parents[1]: .../ohsnb


def _painted(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    g = QLinearGradient(0, 0, 0, 64)
    g.setColorAt(0, QColor("#16213a"))
    g.setColorAt(1, QColor("#070a12"))
    p.setPen(QPen(QColor("#2a3a58"), 1.5))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(2.75, 2.75, 58.5, 58.5), 12, 12)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#05070c"))
    p.drawRoundedRect(QRectF(8, 41, 48, 16), 3.5, 3.5)
    for x, w, c in ((14.5, 3, "#fbb33a"), (24, 8, "#d23a4a"), (39, 2, "#fbb33a"), (46.5, 4, "#f0602a")):
        p.setBrush(QColor(c))
        p.drawRect(QRectF(x, 41, w, 16))
    path = QPainterPath()
    pts = [(8, 40), (13.5, 40), (16, 32), (18.5, 40), (23.5, 40), (25, 35.5), (28, 34), (31, 35.5), (32.5, 40),
           (38.5, 40), (40, 36), (41.5, 40), (46, 40), (48.5, 33.5), (51, 40), (56, 40)]
    path.moveTo(*pts[0])
    for q in pts[1:]:
        path.lineTo(*q)
    p.setPen(QPen(QColor("#7fe6f5"), 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffb547"))
    p.drawEllipse(QPointF(30, 17), 3, 3)
    p.setPen(QPen(QColor("#dfe6ef"), 4, cap=Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(8, 8, 26, 26), 120 * 16, 150 * 16)
    p.end()
    return pm


def app_icon() -> QIcon:
    return loader.load(svg_path(), _painted)


def pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    return loader.pixmap(app_icon(), size, dpr)
