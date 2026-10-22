"""Settings › Display › Scope colours: the editor for scopelook.

Presets first, because most operators want "something like a green
phosphor tube", not ten colour dialogs; any single change from a preset
makes the look Custom, starting from that preset's values. A small preview
paints with the same Look the scopes will, so a choice is seen before Save.
Nothing reaches the scopes until the dialog is saved.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QColorDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from . import scopelook, theme
from .controls import Button, FocusVisible, Segmented, Slider, Toggle, hbox

WIDTHS = [("1", "1 px"), ("2", "2 px"), ("3", "3 px")]


class ColourButton(FocusVisible, QWidget):
    """A swatch that opens the colour dialog."""

    picked = pyqtSignal(str)

    def __init__(self, title: str, value: str, alpha: bool, fallback: QColor | None = None, parent=None):
        super().__init__(parent)
        self.title, self.alpha, self.fallback = title, alpha, fallback
        self.value = value
        self.setFixedSize(56, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(self.tr("{item}: choose a colour").format(item=title))

    def colour(self) -> QColor:
        return QColor(self.value) if self.value else QColor(self.fallback or QColor("#000000"))

    def set_value(self, v: str):
        self.value = v
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.choose()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.choose()
        else:
            super().keyPressEvent(e)

    def choose(self):
        opts = QColorDialog.ColorDialogOption.ShowAlphaChannel if self.alpha else QColorDialog.ColorDialogOption(0)
        c = QColorDialog.getColor(self.colour(), self, self.title, opts)
        if c.isValid():
            self.picked.emit(c.name(QColor.NameFormat.HexArgb if self.alpha else QColor.NameFormat.HexRgb))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        # A checker under it, so a translucent colour reads as one.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(r, 5, 5)
        p.setBrush(QColor("#c8c8c8"))
        for i in range(0, int(r.width()), 6):
            for j in range(0, int(r.height()), 6):
                if (i // 6 + j // 6) % 2:
                    p.drawRect(QRectF(r.x() + i, r.y() + j, 6, 6).intersected(r))
        p.setBrush(self.colour())
        p.setPen(QPen(theme.c("line2"), 1))
        p.drawRoundedRect(r, 5, 5)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 5, 5)


class LookPreview(QWidget):
    """A few hundred pixels of scope painted with the edited look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.look = scopelook.Look({})
        self.setFixedHeight(96)
        self.setMinimumWidth(240)

    def sizeHint(self):
        return QSize(420, 96)

    def set_look(self, d: dict):
        self.look = scopelook.Look(d)
        self.update()

    def paintEvent(self, _e):
        lk = self.look
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), lk.background)
        p.setPen(lk.grid_pen)
        for k in range(1, 4):
            p.drawLine(QPointF(0, k * h / 4 + 0.5), QPointF(w, k * h / 4 + 0.5))
        for k in range(1, 6):
            p.drawLine(QPointF(k * w / 6 + 0.5, 0), QPointF(k * w / 6 + 0.5, h))
        # A made-up band: noise and two signals, its peak ghost a little above.
        n = max(2, w)
        ys, pk = [], []
        for i in range(n):
            x = i / n
            noise = 3.0 * math.sin(i * 1.7) * math.sin(i * 0.31) + 2.0 * math.sin(i * 2.9)
            sig = 38 * math.exp(-((x - 0.3) / 0.012) ** 2) + 22 * math.exp(-((x - 0.72) / 0.03) ** 2)
            y = h * 0.78 - noise - sig
            ys.append(y)
            pk.append(y - 4 - 0.15 * sig)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if lk.fill:
            path = QPainterPath(QPointF(0, h))
            for i, y in enumerate(ys):
                path.lineTo(QPointF(i, y))
            path.lineTo(QPointF(n, h))
            path.closeSubpath()
            # The scope's fade, approximated with a two-stop gradient.
            top = QColor(*[int(v) for v in lk.fill_top])
            top.setAlphaF(min(1.0, lk.fill_opacity))
            foot = QColor(*[int(v) for v in lk.fill_foot])
            foot.setAlphaF(min(1.0, 0.04 * lk.fill_opacity / 0.54))
            g = QLinearGradient(0, h * 0.4, 0, h)
            g.setColorAt(0, top)
            g.setColorAt(1, foot)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        dpr = self.devicePixelRatioF()
        p.setPen(lk.peak_pen)
        ghost = [QPointF(i, y) for i, y in enumerate(pk)]
        for dx, dy in scopelook.trace_passes(1, dpr):
            p.translate(dx, dy)
            p.drawPolyline(ghost)
            p.translate(-dx, -dy)
        p.setPen(lk.trace_pen)
        pts = [QPointF(i, y) for i, y in enumerate(ys)]
        for dx, dy in scopelook.trace_passes(lk.width, dpr):
            p.translate(dx, dy)
            p.drawPolyline(pts)
            p.translate(-dx, -dy)
        x = 0.3 * n
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lk.marker)
        tri = QPainterPath()
        y = ys[int(x)] - 4
        tri.moveTo(x - 4, y - 5)
        tri.lineTo(x + 4, y - 5)
        tri.lineTo(x, y)
        tri.closeSubpath()
        p.drawPath(tri)
        p.setFont(theme.font(10.5, theme.QFont.Weight.DemiBold, mono=True))
        p.setPen(lk.marker)
        p.drawText(QRectF(x - 40, y - 22, 80, 14), Qt.AlignmentFlag.AlignCenter, "540.20  -52")


class LookEditor(QWidget):
    """Presets, one control per item, Reset, and the preview. `stored()`
    is what Save writes to prefs["scopeLook"]."""

    def __init__(self, stored: dict | None, parent=None):
        super().__init__(parent)
        self.d = scopelook.values(stored)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.preset = Segmented(scopelook.PRESET_NAMES + [("custom", self.tr("Custom"))], self.d["preset"],
                                compact=True)
        self.preset.picked.connect(self.pick_preset)
        lay.addWidget(self.preset)
        self.preview = LookPreview()
        lay.addWidget(self.preview)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.buttons: dict[str, ColourButton] = {}
        colours = [k for k, (_l, kind) in scopelook.ITEMS.items() if kind == "colour"]
        for i, k in enumerate(colours):
            lab = QLabel(scopelook.ITEMS[k][0])
            lab.setObjectName("Muted")
            fallback = theme.c("scope") if k == "background" else None
            b = ColourButton(scopelook.ITEMS[k][0], self.d[k], alpha=k in ("trace", "peak"), fallback=fallback)
            b.picked.connect(lambda v, k=k: self.set_item(k, v))
            self.buttons[k] = b
            grid.addWidget(lab, i // 2, (i % 2) * 2)
            grid.addWidget(b, i // 2, (i % 2) * 2 + 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        cap = QLabel(self.tr("Trace width"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        self.width_seg = Segmented(WIDTHS, str(self.d["traceWidth"]), compact=True)
        self.width_seg.picked.connect(lambda v: self.set_item("traceWidth", int(v)))
        lay.addWidget(self.width_seg)
        self.fill = Toggle(self.tr("Fill under the trace"), bool(self.d["fill"]))
        self.fill.toggled.connect(lambda on: self.set_item("fill", bool(on)))
        lay.addWidget(self.fill)
        self.fill_opacity = Slider(self.tr("Fill opacity (at the trace)"), 0, 100, float(self.d["fillOpacity"]), 1,
                                   lambda v: f"{v:.0f} %", default=scopelook.PRESETS["classic"]["fillOpacity"])
        self.fill_opacity.changed.connect(lambda v: self.set_item("fillOpacity", float(v)))
        lay.addWidget(self.fill_opacity)
        self.grid_opacity = Slider(self.tr("Grid opacity"), 0, 100, float(self.d["gridOpacity"]), 1,
                                   lambda v: f"{v:.0f} %", default=100.0)
        self.grid_opacity.changed.connect(lambda v: self.set_item("gridOpacity", float(v)))
        lay.addWidget(self.grid_opacity)
        reset = Button(self.tr("Reset to default"), small=True)
        reset.clicked.connect(lambda: self.pick_preset("classic"))
        lay.addLayout(hbox(reset, None))
        self._sync()

    def pick_preset(self, name: str):
        if name == "custom":                    # the current values, to change from
            self.d["preset"] = "custom"
        else:
            self.d = scopelook.values({"preset": name})
        self._sync()

    def set_item(self, k: str, v):
        if self.d.get(k) == v:
            return
        self.d[k] = v
        self.d["preset"] = "custom"
        self._sync()

    def _sync(self):
        d = self.d
        self.preset.set_value(d["preset"], animate=False)
        for k, b in self.buttons.items():
            b.set_value(d[k])
        self.width_seg.set_value(str(d["traceWidth"]), animate=False)
        self.fill.set_on(bool(d["fill"]))
        self.fill_opacity.set_value(float(d["fillOpacity"]))
        self.fill_opacity.setEnabled(bool(d["fill"]))
        self.buttons["fillColour"].setEnabled(bool(d["fill"]))
        self.grid_opacity.set_value(float(d["gridOpacity"]))
        self.preview.set_look(d)

    def stored(self) -> dict:
        """A preset is stored by name alone, so a later improvement to it
        reaches the operator; a custom look is stored whole."""
        if self.d["preset"] in scopelook.PRESETS:
            return {} if self.d["preset"] == "classic" else {"preset": self.d["preset"]}
        return dict(self.d)
