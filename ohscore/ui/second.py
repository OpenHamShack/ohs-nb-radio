"""The second display: a top-level window for another screen.

It shows either a big waterfall of the whole band (NB: the transponder) with
the decodes on it and the frequency, or the active mode panel at a
reading-across-the-room size. Settings picks which, which screen, and full screen. On a machine with
one screen it is simply a second window.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from . import theme
from .panels import make_panel, panel_key
from .scope import ScopeView


class BigFreq(QWidget):
    """The frequency and mode, large, across the top of the second display."""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setFixedHeight(84)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), theme.c("bg0"))
        st = self.bridge.st
        vfo = float(st.get("vfo") or 0)
        keyed = self.bridge.face.on_air(st)     # radiating, not merely queued (Face.on_air)
        text = self.bridge.face.big_freq(int(round(vfo)))
        p.setFont(theme.font(52, theme.QFont.Weight.Medium))
        p.setPen(theme.c("tx") if keyed else theme.c("text"))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(24, 0, fm.horizontalAdvance(text) + 10, self.height()), Qt.AlignmentFlag.AlignVCenter, text)
        x = 24 + fm.horizontalAdvance(text) + 24
        p.setFont(theme.font(22, theme.QFont.Weight.Bold))
        p.setPen(theme.c("accent"))
        mode = str(st.get("mode", "")).upper()
        p.drawText(QRectF(x, 0, 200, self.height()), Qt.AlignmentFlag.AlignVCenter, mode)
        if keyed:
            p.setFont(theme.font(26, theme.QFont.Weight.Black, spacing=2))
            p.setPen(theme.c("tx"))
            p.drawText(QRectF(0, 0, self.width() - 30, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.tr("ON AIR"))
        else:
            status = self.bridge.face.big_status(st)
            if status is not None:
                text, col = status
                p.setFont(theme.font(16, theme.QFont.Weight.Bold))
                p.setPen(theme.c(col))
                p.drawText(QRectF(0, 0, self.width() - 30, self.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
        if keyed:
            p.setPen(QPen(theme.c("tx"), 4))
            p.drawLine(0, self.height() - 2, self.width(), self.height() - 2)


class SecondDisplay(QWidget):
    closed = pyqtSignal()

    def __init__(self, bridge, prefs, main):
        super().__init__(None, Qt.WindowType.Window)
        # Closing it is the end of it: the main window makes a new one on
        # the next open, so a closed one is deleted rather than kept hidden.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.bridge, self.prefs, self.main = bridge, prefs, main
        self.setWindowTitle(self.tr("{app} — second display").format(app=bridge.face.app_name))
        self.setWindowIcon(bridge.face.icon())
        self.setObjectName("Root")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.content = None
        self.panel = None
        self.scope = None
        self.rebuild()
        self.resize(1280, 720)

    def rebuild(self):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                if isinstance(w, ScopeView):
                    w.detach()
                w.hide()          # deleteLater alone leaves it painting until the loop next idles
                w.deleteLater()
        self.setStyleSheet(f"#Root {{ background: {theme.t()['bg0']}; }}")
        self.freq = BigFreq(self.bridge)
        self.lay.addWidget(self.freq)
        self.scope = None
        self.panel = None
        if self.prefs["secondContent"] == "panel":
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(16, 12, 16, 16)
            self.panel_stack = QStackedWidget()
            hl.addWidget(self.panel_stack)
            self.lay.addWidget(holder, 1)
            self._panel_for(self.bridge.st.get("mode", "usb"))
        else:
            self.scope = ScopeView(self.bridge, self.prefs, "wide", big=True)
            self.scope.clicked.connect(self.main.scope_click)
            self.scope.wheel_step.connect(lambda d: self.main.step_tune(d))
            self.scope.colours_requested.connect(self.main.open_scope_colours)
            self.scope.context_requested.connect(self.main.scope_menu)
            self.lay.addWidget(self.scope, 1)
            self.scope.setMinimumSize(320, 240)
            self._adopt_pending = True

    def _panel_for(self, mode):
        key = panel_key(mode)
        if self.panel is not None and getattr(self.panel, "_key", None) == key:
            return
        p = make_panel(key, self.bridge, self.prefs, big=True)
        p.set_mirror()
        p._key = key
        src = self.main.panels.get(key) if self.main is not None else None
        if src is not None and hasattr(p, "adopt"):
            p.adopt(src)
        if self.panel is not None:
            self.panel_stack.removeWidget(self.panel)
            self.panel.deleteLater()
        self.panel = p
        self.panel_stack.addWidget(p)

    def apply_prefs(self):
        self.rebuild()
        if self.scope is not None:
            self.scope.set_palette(self.prefs["palette"])
        self.open_on_screen()

    def open_on_screen(self):
        screens = QGuiApplication.screens()
        want = self.prefs["secondScreen"]
        scr = next((s for s in screens if s.name() == want), None)
        if scr is None:
            # Default: any screen that is not the main window's, else the same one.
            mine = self.main.screen() if self.main is not None else None
            scr = next((s for s in screens if s is not mine), screens[0] if screens else None)
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.x() + 40, g.y() + 40)
            if self.width() > g.width() or self.height() > g.height():
                self.resize(int(g.width() * 0.9), int(g.height() * 0.9))
        if self.prefs["secondFullScreen"]:
            if scr is not None:
                self.setScreen(scr)
                self.setGeometry(scr.geometry())
            self.showFullScreen()
        else:
            self.showNormal()
            self.show()

    def on_state(self, ch):
        self.freq.update()
        if self.panel is not None:
            if "mode" in ch:
                self._panel_for(ch["mode"])
            self.panel.on_state(ch)

    def on_meter(self, m):
        # The mirror's CW panel shows the decoder's speed too, and clears it
        # from the meter as the main one does.
        if self.panel is not None and hasattr(self.panel, "on_meter"):
            self.panel.on_meter(m)

    def on_event(self, ev):
        if self.panel is not None:
            self.panel.on_event(ev)
        if self.scope is not None:
            self.main.label_event(ev, (self.scope,))

    def showEvent(self, e):
        super().showEvent(e)
        self._adopt_soon()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adopt_soon()

    def _adopt_soon(self):
        # Once the scope has its real size, take the main wide scope's history.
        if getattr(self, "_adopt_pending", False) and self.scope is not None and self.scope.height() > 200:
            self._adopt_pending = False
            self.scope.adopt(self.main.wide)

    def tick(self, dt):
        if self.panel is not None:
            self.panel.tick(dt)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.isFullScreen() and not self.bridge.st.get("keyed"):
            self.showNormal()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        if self.scope is not None:
            self.scope.detach()
        self.closed.emit()
        super().closeEvent(e)
