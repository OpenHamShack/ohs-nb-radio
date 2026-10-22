"""Each scope's own controls: a popover from the button in its waterfall's
corner, in three tabs - the trace's scale, its peaks, and the waterfall's
floor, contrast, speed and palette.

They live on the scope rather than only in Settings because they are
adjusted while looking at the signal they are meant to bring out. Every
setting is per scope (the wide and the zoom have their own prefs keys; the
second display's big scope is a wide one and shares the wide's) and takes
effect as it is moved. Automatic scale and levels follow the noise floor;
switching either to manual starts from the values auto had reached, so
nothing jumps.

Tabs rather than one long column: with everything in one column the panel
ran past the bottom of a 1366x768 laptop screen.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from . import palettes, theme
from .controls import Button, Segmented, Slider, Toggle, hbox
from .scope import GHOST_TAU, labels_shown, set_labels_shown

SPEEDS = [("0.25", "¼×"), ("0.5", "½×"), ("1.0", "1×"), ("2.0", "2×")]


class PaletteSwatch(QWidget):
    picked = pyqtSignal(str)

    def __init__(self, name: str, on: bool, parent=None, w: int = 132):
        super().__init__(parent)
        self.name, self.on = name, on
        self.setFixedSize(w, 58 if w >= 100 else 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def mouseReleaseEvent(self, e):
        self.picked.emit(self.name)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = QLinearGradient(r.x(), 0, r.right(), 0)
        for pos, rgb in palettes.gradient_stops(self.name, 10):
            g.setColorAt(pos, QColor((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        bar = r.height() * 0.52
        p.drawRoundedRect(QRectF(r.x(), r.y(), r.width(), bar), 6, 6)
        p.setFont(theme.font(12 if r.width() >= 100 else 11, theme.QFont.Weight.DemiBold))
        p.setPen(theme.c("text") if self.on else theme.c("text2"))
        p.drawText(QRectF(r.x(), r.y() + bar + 1, r.width(), r.height() - bar - 1), Qt.AlignmentFlag.AlignCenter,
                   self.name)
        if self.on:
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 7, 7)


TABS = [("scope", "Scope"), ("peaks", "Peaks"), ("waterfall", "Waterfall")]
# Hold times in seconds; -1 holds until Clear. 1.5 s is the ghost's look
# from before it was adjustable, so it stays the default and an option.
HOLDS = [("0.0", "Off"), ("1.0", "1 s"), ("1.5", "1.5 s"), ("3.0", "3 s"), ("10.0", "10 s"), ("-1.0", "∞")]


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(8)
    return w, lay


def _caption(text: str) -> QLabel:
    cap = QLabel(text)
    cap.setObjectName("Muted")
    return cap


class AdjustPopover(QFrame):
    palette_changed = pyqtSignal(str)

    def __init__(self, scope, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.scope = scope
        self.prefs = scope.prefs
        self.key = "wf" if scope.wide else "zoomWf"
        self.skey = scope.spec_key()
        self.setObjectName("Popover")
        t = theme.t()
        self.setStyleSheet(f"#Popover {{ background: {t['bg1']}; border: 1px solid {t['line2']}; "
                           f"border-radius: 12px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        # Named for the scope it adjusts, as its pill's tooltip is: the two
        # popovers are otherwise the same, and both scopes have a pill.
        head = QLabel(self.tr("Adjust the wide scope") if scope.wide else self.tr("Adjust the zoom scope"))
        head.setFont(theme.caps(10.5))
        head.setStyleSheet(f"color: {t['text3']};")
        lay.addWidget(head)
        tab = str(self.prefs.get("adjustTab", "waterfall"))
        if tab not in dict(TABS):
            tab = "waterfall"
        # TABS is read at import, before a catalog is installed: its keys
        # stay, its words are looked up here.
        words = {"scope": self.tr("Scope"), "peaks": self.tr("Peaks"), "waterfall": self.tr("Waterfall")}
        self.tabs = Segmented([(k, words.get(k, label)) for k, label in TABS], tab, compact=True)
        self.tabs.picked.connect(self._tab)
        lay.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        for key, _label in TABS:
            w, pl = _page()
            getattr(self, "_build_" + key)(pl)
            pl.addStretch(1)
            self.pages[key] = w
            self.stack.addWidget(w)
        self.stack.setCurrentWidget(self.pages[tab])
        lay.addWidget(self.stack)
        self.setFixedWidth(340)

    def _tab(self, key):
        self.prefs["adjustTab"] = key
        self.stack.setCurrentWidget(self.pages[key])

    # ------------------------------------------------------------ the trace
    def _build_scope(self, lay):
        p, k = self.prefs, self.skey
        self.spec_auto = Toggle(self.tr("Automatic scale"), bool(p.get(k + "Auto", True)))
        self.spec_auto.toggled.connect(self._spec_auto)
        lay.addWidget(self.spec_auto)
        top, rg = self.scope.auto_scale()
        self.spec_top = Slider(self.tr("Top"), -140, 0, float(p.get(k + "Top", top)), 1, lambda v: f"{v:.0f} dBFS",
                               default=top)
        self.spec_range = Slider(self.tr("Range"), 10, 120, float(p.get(k + "Range", rg)), 1, lambda v: f"{v:.0f} dB",
                                 default=rg)
        self.spec_top.changed.connect(lambda v: self._spec("Top", v))
        self.spec_range.changed.connect(lambda v: self._spec("Range", v))
        lay.addWidget(self.spec_top)
        lay.addWidget(self.spec_range)
        self._spec_auto(self.spec_auto.on, init=True)
        lay.addSpacing(6)
        self.smooth = Slider(self.tr("Smoothing"), 0.0, 1.0, float(p.get(k + "Smooth", GHOST_TAU)), 0.01,
                             lambda v: self.tr("raw") if v <= 0 else f"{v:.2f} s", default=GHOST_TAU)
        self.smooth.changed.connect(lambda v: self._spec("Smooth", v))
        lay.addWidget(self.smooth)
        lay.addSpacing(6)
        # Here rather than in Settings for the reason the panel exists: it
        # is chosen while looking at the beacon and one's own signal. The
        # words name the look, not the app ("Standard", not "NB"), because
        # Radio shows the same panel.
        lay.addWidget(_caption(self.tr("Display style")))
        self.style = Segmented([("nb", self.tr("Standard")), ("sdrconsole", self.tr("SDR Console-like"))],
                               self.scope.display_style(), compact=True)
        self.style.setToolTip(self.tr(
            "SDR Console-like draws a wider resolution bandwidth (about 100 Hz) with a hang-and-decay trace, so a "
            "wide signal such as the PSK beacon stands as high against a narrow one as it does in SDR Console. "
            "The display only: no reading, limit or beacon lock changes with it."))
        self.style.picked.connect(self._style)
        lay.addWidget(self.style)
        lay.addSpacing(6)
        # Shared by every scope (scope.labels_shown), but asked for here,
        # where the crowded waterfall is being looked at.
        self.labels = Toggle(self.tr("Show signal labels"), labels_shown(self.prefs))
        self.labels.setToolTip(self.tr(
            "Decode labels, band marks and alert captions on every scope (L). The passband, cursors, "
            "beacon captions and the CW, PSK and RTTY text stay; \"What is this?\" still works."))
        self.labels.toggled.connect(lambda on: set_labels_shown(self.prefs, on))
        lay.addWidget(self.labels)
        lay.addSpacing(6)
        # Colours are shared by every scope, so they are in Settings rather
        # than here; this only leads there.
        colours = Button(self.tr("Colours…"), small=True)
        colours.setToolTip(self.tr("Trace, fill, peak, marker, grid and background colours, for every scope "
                                   "(Settings › Display)"))
        colours.clicked.connect(self._colours)
        lay.addLayout(hbox(colours, None))

    def _spec_auto(self, on, init=False):
        self.prefs[self.skey + "Auto"] = bool(on)
        if not on and not init:
            top, rg = self.scope.auto_scale()
            self.spec_top.set_value(top)
            self.spec_range.set_value(rg)
            self._spec("Top", self.spec_top.v)
            self._spec("Range", self.spec_range.v)
        self.spec_top.setEnabled(not on)
        self.spec_range.setEnabled(not on)
        self.scope.update()

    def _colours(self):
        self.close()
        self.scope.colours_requested.emit()

    def _spec(self, what, v):
        self.prefs[self.skey + what] = float(v)
        self.scope.update()

    def _style(self, v):
        self.prefs[self.skey + "Style"] = str(v)
        self.scope.update()

    # ------------------------------------------------------------ the peaks
    def _build_peaks(self, lay):
        p, k = self.prefs, self.skey
        self.peak_on = Toggle(self.tr("Peak hold"), bool(p.get(k + "Peak", True)))
        self.peak_on.toggled.connect(self._peak_on)
        lay.addWidget(self.peak_on)
        lay.addWidget(_caption(self.tr("Hold peaks for  (∞: until cleared)")))
        hold = float(p.get(k + "PeakHold", 1.5))
        holds = [(v, self.tr("Off") if v == "0.0" else label) for v, label in HOLDS]
        self.peak_hold = Segmented(holds, str(hold) if hold >= 0 else "-1.0", compact=True)
        self.peak_hold.picked.connect(lambda v: self._peak("PeakHold", float(v)))
        lay.addWidget(self.peak_hold)
        self.peak_fall = Slider(self.tr("Then fall at"), 1, 60, float(p.get(k + "PeakFall", 10.0)), 1,
                                lambda v: f"{v:.0f} dB/s", default=10.0)
        self.peak_fall.changed.connect(lambda v: self._peak("PeakFall", float(v)))
        lay.addWidget(self.peak_fall)
        self.peak_clear = Button(self.tr("Clear peaks"), small=True)
        self.peak_clear.clicked.connect(self.scope.clear_peaks)
        lay.addLayout(hbox(self.peak_clear, None))
        self._peak_on(self.peak_on.on, init=True)
        lay.addSpacing(6)
        self.marks_on = Toggle(self.tr("Label the strongest signals"), bool(p.get(k + "Marks", False)))
        self.marks_on.toggled.connect(self._marks_on)
        lay.addWidget(self.marks_on)
        self.mark_above = Slider(self.tr("Over the noise by"), 3, 40, float(p.get(k + "MarkAbove", 10.0)), 1,
                                 lambda v: f"{v:.0f} dB", default=10.0)
        self.mark_above.changed.connect(lambda v: self._mark("MarkAbove", float(v)))
        lay.addWidget(self.mark_above)
        self.mark_max = Slider(self.tr("At most"), 1, 10, float(p.get(k + "MarkMax", 5)), 1,
                               lambda v: f"{v:.0f}", default=5)
        self.mark_max.changed.connect(lambda v: self._mark("MarkMax", int(round(v))))
        lay.addWidget(self.mark_max)
        self._marks_on(self.marks_on.on, init=True)

    def _peak_on(self, on, init=False):
        if not init:
            self._peak("Peak", bool(on))
        for w in (self.peak_hold, self.peak_fall, self.peak_clear):
            w.setEnabled(bool(on))

    def _marks_on(self, on, init=False):
        if not init:
            self._mark("Marks", bool(on))
        self.mark_above.setEnabled(bool(on))
        self.mark_max.setEnabled(bool(on))

    def _mark(self, what, v):
        self.prefs[self.skey + what] = v
        self.scope.refresh_marks()

    def _peak(self, what, v):
        self.prefs[self.skey + what] = v
        self.scope.update()

    # --------------------------------------------------------- the waterfall
    def _build_waterfall(self, lay):
        p = self.prefs
        self.auto = Toggle(self.tr("Automatic levels"), bool(p.get(self.key + "Auto", True)))
        self.auto.toggled.connect(self._auto)
        lay.addWidget(self.auto)
        fl, rg = self.scope.auto_levels()
        self.floor = Slider(self.tr("Floor"), -160, -40, float(p.get(self.key + "Floor", fl)), 1,
                            lambda v: f"{v:.0f} dBFS", default=fl)
        self.range = Slider(self.tr("Contrast range"), 15, 90, float(p.get(self.key + "Range", rg)), 1,
                            lambda v: f"{v:.0f} dB", default=rg)
        self.floor.changed.connect(lambda v: self._set("Floor", v))
        self.range.changed.connect(lambda v: self._set("Range", v))
        lay.addWidget(self.floor)
        lay.addWidget(self.range)
        lay.addWidget(_caption(self.tr("Speed")))
        self.speed = Segmented(SPEEDS, str(float(p["wfSpeed"])), compact=True)
        self.speed.picked.connect(self._speed)
        lay.addWidget(self.speed)
        lay.addWidget(_caption(self.tr("Palette")))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.swatches = []
        for n in palettes.NAMES:
            s = PaletteSwatch(n, n == p["palette"], w=74)
            s.picked.connect(self._palette)
            self.swatches.append(s)
            row.addWidget(s)
        lay.addLayout(row)
        self._auto(self.auto.on, init=True)

    def _auto(self, on, init=False):
        self.prefs[self.key + "Auto"] = bool(on)
        if not on and not init:
            fl, rg = self.scope.auto_levels()
            self.floor.set_value(fl)
            self.range.set_value(rg)
            self._set("Floor", self.floor.v)
            self._set("Range", self.range.v)
        self.floor.setEnabled(not on)
        self.range.setEnabled(not on)

    def _set(self, what, v):
        self.prefs[self.key + what] = float(v)

    def _speed(self, v):
        self.prefs["wfSpeed"] = float(v)

    def _palette(self, name):
        self.prefs["palette"] = name
        for s in self.swatches:
            s.on = s.name == name
            s.update()
        self.palette_changed.emit(name)

    def hideEvent(self, e):
        self.prefs.save()
        super().hideEvent(e)
