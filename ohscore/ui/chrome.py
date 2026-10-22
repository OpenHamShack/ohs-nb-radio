"""Window furniture: the status strip, the shortcuts overlay, the header's
small icon buttons, and the view switcher above the lower panel."""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from . import icons, theme
from .controls import FocusVisible, Anim, mix
from .playback import play_status
from .recording import rec_status


class StatusStrip(QWidget):
    """One line at the bottom: device, rate, load, the app's own items
    (NB: its rxCorr and txCorr), UTC. `items(state)` returns the app's
    (text, colour token) pairs, shown while the radio runs.

    The window's own timings (frame, wide paint, line: `timings`) were
    shown here as a fourth group of numbers until the October 2026
    overhaul (section 5.10). They are a developer's, not an operator's,
    and took the room the app's items needed on a laptop; they live in the
    CPU item's tooltip now, beside the receive thread's load they explain,
    and in Help › Save diagnostics' report."""

    # Below this share of the radio's stream arriving, the strip says so in
    # place of the sample rate. 95, not 100: one lost 75 ms block in ten
    # seconds is not news, a link that keeps losing them is.
    STREAM_SHORT_PCT = 95.0

    def __init__(self, bridge, parent=None, items=None):
        super().__init__(parent)
        self.bridge = bridge
        self.items = items or (lambda st: [])
        self.setFixedHeight(theme.px(28))
        self.timings = ""
        # The window's tier (overhaul section 3): what the strip has room
        # for. Compact moves the sample rate and the CPU into the radio's
        # tooltip; Tight keeps the radio, a recording, overruns once there
        # are any, the app's first item (NB: rxCorr) and the time.
        self.tier = "full"
        # Where each item was last painted, for its tooltip: [(x0, x1, key)].
        self.hits: list[tuple[float, float, str]] = []

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), theme.c("bg0"))
        p.setPen(QPen(theme.c("line"), 1))
        p.drawLine(0, 0, self.width(), 0)
        st = self.bridge.st
        running = bool(st.get("running"))
        x = 14.0
        utc = time.strftime("%H:%M:%S UTC", time.gmtime())
        f_utc = theme.font(12, theme.QFont.Weight.DemiBold, mono=True)
        utc_w = QFontMetricsF(f_utc).horizontalAdvance(utc) + 14 + 16
        p.setFont(theme.font(11.5))
        fm = QFontMetricsF(p.font())
        dot = theme.c("ok") if running else theme.c("err") if st.get("error") else theme.c("text3")
        d = theme.px(8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QRectF(x, (self.height() - d) / 2, d, d))
        x += d + 8
        self.hits = []
        gap = theme.px(22)
        for text, col, *key in self.entries(st):
            if not text:
                continue
            p.setPen(theme.c(col))
            w = fm.horizontalAdvance(text)
            if x + w > self.width() - utc_w:
                break
            p.drawText(QRectF(x, 0, w + 4, self.height()), Qt.AlignmentFlag.AlignVCenter, text)
            if key:
                self.hits.append((x, x + w, key[0]))
            x += w + gap
        p.setFont(f_utc)
        p.setPen(theme.c("text2"))
        p.drawText(QRectF(self.width() - utc_w, 0, utc_w - 14, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, utc)

    def set_tier(self, tier: str) -> None:
        if tier != self.tier:
            self.tier = tier
            self.update()

    def entries(self, st: dict) -> list[tuple]:
        """What the strip says for state `st`, left to right: (text, colour
        token) or (text, colour token, tooltip key), before it is cut to
        the room there is."""
        running = bool(st.get("running"))
        dev = {"sim": "Simulator", "pluto": "Pluto", "soapy": "SoapySDR (receive only)"}.get(st.get("device"), "?")
        items = [(dev + ("" if running else "  —  " + (st.get("error") or "stopped")), "text", "device")]
        if st.get("playing"):
            # Where the radio's name stands, so a recording is never taken for the air.
            items = [(play_status(st) + ("" if running else "  —  " + (st.get("error") or "stopped")), "accent", "device")]
        # Recording comes straight after the radio, where the strip never
        # runs out of room for it. Amber with its filled dot (overhaul
        # decision 7): red is only ever transmit.
        items.append((rec_status(st), "rec"))
        if running:
            fs = float(st.get("fs") or 0)
            # cpu is the receive thread's own CPU time (Engine._rx_loop,
            # time.thread_time()); wait is wall-clock time a block took
            # beyond that - waiting for the GIL or the OS scheduler, not
            # doing work. Shown only once it is worth a second number (10
            # points): without it, a GUI-thread stall starving receive
            # read as a plausible-looking "CPU 41%" instead of what it was.
            wait = 100 * float(st.get("cpuWait") or 0)
            cpu_text = f"CPU {100 * float(st.get('cpu') or 0):.0f} %"
            if wait > 10.0:
                cpu_text += f" (wait {wait:.0f} %)"
            # The rate the radio was set to, unless less than that is
            # arriving: then how much (Engine._stream_pct; a PC over a
            # Tailscale relay got 37 % while this said "1.2 MS/s", Windows
            # test 17/10/2026).
            share = float(st.get("rxStreamPct", 100.0) or 0.0)
            rate = (f"{fs / 1e6:.1f} MS/s" if fs else "", "text2")
            if share < self.STREAM_SHORT_PCT:
                rate = (f"receiving {share:.0f} % of the stream", "warn")
            overruns = (f"overruns {st.get('overruns', 0)}", "warn" if st.get("overruns") else "text3")
            own = self.items(st)
            if self.tier == "full":
                items += [rate, (cpu_text, "text2", "cpu"), overruns] + own
            elif self.tier == "compact":
                # The rate and the load are in the radio's tooltip
                # (tooltip_at), unless less than the whole stream arrives:
                # that is news, and stays in sight.
                items += ([rate] if share < self.STREAM_SHORT_PCT else []) + [overruns] + own
            else:
                items += ([rate] if share < self.STREAM_SHORT_PCT else []) + (
                    [overruns] if st.get("overruns") else []) + own[:1]
        return items

    def _rate_and_load(self, st: dict) -> str:
        """The sample rate and the receive thread's load, for the radio's
        tooltip where the strip has no room for them."""
        fs = float(st.get("fs") or 0)
        parts = [f"{fs / 1e6:.1f} MS/s"] if fs else []
        parts.append(f"CPU {100 * float(st.get('cpu') or 0):.0f} %")
        wait = 100 * float(st.get("cpuWait") or 0)
        if wait > 10.0:
            parts[-1] += f" (wait {wait:.0f} %)"
        return "  ·  ".join(parts)

    def tooltip_at(self, x: float) -> str:
        """The tooltip of the item painted at `x` ("" for none)."""
        for x0, x1, key in self.hits:
            cpu_here = key == "cpu" or (key == "device" and self.tier != "full" and self.bridge.st.get("running"))
            if x0 <= x <= x1 and cpu_here:
                lines = [self.tr("The receive thread's share of one processor core; \"wait\" is time it was "
                                 "ready but not running (another thread, or the system, had it).")]
                if key == "device":
                    lines.insert(0, self._rate_and_load(self.bridge.st))
                if self.timings:
                    lines.append(self.tr("Window: {timings}").format(timings=self.timings))
                return "\n".join(lines)
        return ""

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            tip = self.tooltip_at(e.pos().x())
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)


class IconButton(FocusVisible, QWidget):
    clicked = pyqtSignal()

    def __init__(self, icon: str, tip: str, parent=None, checkable: bool = False):
        super().__init__(parent)
        self.icon = icon
        self.checkable = checkable
        self.checked = False
        self.hover = Anim(self)
        self.setToolTip(tip)
        self.set_side(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_side(self, n: int) -> None:
        """Square, `n` px a side at 100 % text (the header's tiers make it
        smaller where the header is one line)."""
        self.setFixedSize(theme.px(n), theme.px(n))
        self.update()

    def set_checked(self, on):
        self.checked = bool(on)
        self.update()

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = mix(theme.c("bg1", 0.0), theme.c("bg3"), self.hover.value)
        if self.checked:
            bg = theme.c("accent", 0.18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)
        col = theme.c("accent") if self.checked else mix(theme.c("text2"), theme.c("text"), self.hover.value)
        g = self.width() * 20 / 38          # the glyph keeps its share of the button at any size
        self.paint_glyph(p, QRectF(r.center().x() - g / 2, r.center().y() - g / 2, g, g), col)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 8, 8)


    def paint_glyph(self, p: QPainter, rect: QRectF, col) -> None:
        icons.paint(p, self.icon, rect, col, 1.7)


class MoreButton(IconButton):
    """Three dots: the header's "more" in the Tight tier, holding second
    display, Settings, Logbook and the shortcuts, each still on its own
    key. Drawn here rather than as a path in icons.py: dots are filled."""

    def __init__(self, tip: str, parent=None):
        super().__init__("", tip, parent)

    def paint_glyph(self, p: QPainter, rect: QRectF, col) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        d = rect.width() * 0.18
        for i in (-1, 0, 1):
            c = rect.center()
            p.drawEllipse(QRectF(c.x() + i * rect.width() * 0.32 - d / 2, c.y() - d / 2, d, d))


class ShortcutOverlay(QWidget):
    """'?' - every shortcut, over a dimmed window. Any key or click closes it.
    `sections` is the app's list of (title, [(keys, what), ...])."""

    def __init__(self, parent, sections):
        super().__init__(parent)
        self.sections = sections
        self.k = Anim(self)
        self.hide()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def open(self):
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.k.value = 0.0
        self.k.to(1.0)

    def close_(self):
        self.hide()
        if self.parentWidget():
            self.parentWidget().setFocus()

    def keyPressEvent(self, e):
        self.close_()

    def mousePressEvent(self, e):
        self.close_()

    def plan(self):
        """Where each piece of the sheet goes at this size (ohscore/ui/
        shortcutsheet.py: measured, wrapped, smaller if it must be)."""
        from .shortcutsheet import plan
        return plan(self.sections, self.width(), self.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self.k.value
        p.fillRect(self.rect(), QColor(0, 0, 0, int(150 * k)))
        sheet = self.plan()
        p.translate(0, (1 - k) * 12)
        p.setOpacity(k)
        p.setPen(QPen(theme.c("line2"), 1))
        p.setBrush(theme.c("bg1"))
        p.drawRoundedRect(sheet.card, 14, 14)
        colours = {"title": "text", "hint": "text3", "heading": "accent", "key": "text", "what": "text2"}
        for it in sheet.items:
            if it.kind == "key":
                p.setPen(QPen(theme.c("line2"), 1))
                p.setBrush(theme.c("bg2"))
                p.drawRoundedRect(it.rect, 5, 5)
            p.setFont(it.font)
            p.setPen(theme.c(colours[it.kind]))
            p.drawText(it.rect, it.flags, it.text)

    def sizeHint(self):
        return QSize(800, 600)
