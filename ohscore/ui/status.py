"""The things that must never be missed: the PTT button, the on-air frame
glow and the toasts (and, in QO-100 NB, the lock badges built from the
same parts: ohsnb/ui/status.py).

Every one of these says its state in two ways at once - colour *and* words
or shape - because a red/green distinction alone fails one operator in
twelve, and because an operator sat back from a laptop reads shape before
colour.
"""
from __future__ import annotations

import html
import math
import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import icons, theme, txstate
from .controls import FocusVisible, Anim, mix


class LockPopover(QFrame):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popover")
        self.setStyleSheet(f"#Popover {{ background: {theme.t()['bg1']}; border: 1px solid {theme.t()['line2']};"
                           f" border-radius: 10px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 12, 16, 14)
        self.head = QLabel()
        self.head.setFont(theme.caps(10.5))
        self.lay.addWidget(self.head)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(6)
        self.lay.addLayout(self.grid)

    def fill(self, title, rows):
        self.head.setText(title)
        self.head.setStyleSheet(f"color: {theme.t()['text3']};")
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                # Hidden at once: deleteLater() waits for the event loop, and
                # until then the old row still paints under the new one.
                w.hide()
                w.deleteLater()
        for i, (k, v) in enumerate(rows):
            a, b = QLabel(k), QLabel(v)
            a.setStyleSheet(f"color: {theme.t()['text2']};")
            b.setFont(theme.font(13, theme.QFont.Weight.DemiBold, mono=True))
            b.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.grid.addWidget(a, i, 0)
            self.grid.addWidget(b, i, 1)


def fmt_hz(v, signed=True) -> str:
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1000:
        return f"{v / 1000:+.3f} kHz" if signed else f"{v / 1000:.3f} kHz"
    return f"{v:+.1f} Hz" if signed else f"{v:.1f} Hz"


# ------------------------------------------------------------------ PTT
# The few words under TX when a key-up would be refused here and now
# (txstate HERE): the engine's sentence is the tooltip, and the tile has
# room for three or four words. Matched on the engine's own English
# sentences (ohscore/engine.py, ohsnb/radio.py, ohsradio/radio.py, the band
# plans), first match wins; anything unforeseen says "Not available here",
# which is still true, and the tooltip says the rest. Ids, not words: the
# words are PttButton.words(), each a literal tr() so the catalogs hold it.
_HERE_WORDS = (
    ("receive-only", "rxonly"),
    ("not running", "stopped"),
    ("Dish alignment", "dish"),
    ("key it on the radio", "onradio"),
    ("SWR", "swr"),
    ("sequencer", "sequencer"),
    ("beacon", "beacon"),
    ("wide", "wide"),
    ("segment", "segment"),
    ("not allowed", "segment"),
    ("cannot transmit on", "band"),
    ("licence class", "class"),
    ("licence", "licence"),
    ("ceiling", "power"),
    ("dBm into", "power"),
    ("Drive", "power"),
    ("transmit LO", "rate"),
    ("recording", "playing"),
)


def here_words(why: str) -> str:
    """The id of the short form of a HERE refusal (PttButton.words)."""
    for needle, words in _HERE_WORDS:
        if needle in why:
            return words
    return "here"


def mode_words(mode: str) -> str:
    """The id of how `mode` transmits (PttButton.words), shown under TX
    while a key-up would be allowed (overhaul section 5.9). Asked of the
    same lookup that picks the panel (panels.panel_key), so the tile and
    the panel below it never disagree."""
    from .panels import panel_key
    from ..modegroups import slot_spec
    spec = slot_spec(mode)
    # JS8 sends since 17/10/2026 (its slot spec says so), from its panel's
    # Enable TX like FT8's.
    if spec is not None and not spec.transmits:
        return "rxonly"
    key = panel_key(mode)
    if key == "slot" or mode in ("ft8", "ft4", "q65"):
        return "enable"
    if key in ("text", "cw"):
        return "type"
    if key in ("image", "data") or mode in ("sstv", "hsmodem", "kgstv"):
        return "panel"
    return "talk"


class PttButton(FocusVisible, QWidget):
    """The big TX button. Hold or toggle (pttMode). Greyed with the reason
    when keying would be refused; red and counting down while on air.

    FT8/FT4 and the other modes with their own send panel (PSK/RTTY, SSTV)
    never key from here - they transmit queued/scheduled messages, so Space
    hitting this button has nothing useful to do. Telling the operator that
    is more useful than "unavailable", which reads like a fault.

    Under TX it says, in sentence case, how this mode transmits ("Space to
    talk", "Enable TX below", ...), or why it cannot: the four-word
    transmit state (ohscore/ui/txstate.py) says "Receive only" for a run
    that can never transmit, "Set up to transmit" for a radio with the
    licence box unticked, and a few words of the engine's refusal for
    "not here" (Mac test FINDINGS 14 and 25: capitals and "unavailable"
    read as a fault under --receive-only).

    Red is only for the air (overhaul section 5.3): idle it is a neutral
    outline and text; armed a red outline; on the air a red fill. It used
    to be red-tinted whenever transmit was available, which put red on
    the screen of every receiving station."""

    pressed = pyqtSignal()
    released = pyqtSignal()

    # (width, height) at 100 % text per window tier (overhaul section 3):
    # the two-line tile, or Tight's short one for a header of one line.
    SIZES = {"full": (150, 92), "compact": (150, 92), "tight": (128, 48)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keyed = False
        self.blocked = ""
        self.tx_seconds = 0.0
        self.timeout = 300.0
        self.source = ""
        self.panel = False
        self.armed_at: float | None = None
        self.mode = ""
        self.tx = txstate.TxState(txstate.OK)
        self.hover = Anim(self)
        self.on = Anim(self)
        self.down = False
        self.glow_t = 0.0
        self.form = ""
        self.set_form("full")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_form(self, form: str) -> None:
        """The window's tier: "full", "compact" or "tight". Only the size
        and the drawing change; what the tile says and does is the same in
        every form, so halting is never harder in a small window."""
        if form not in self.SIZES or form == self.form:
            return
        self.form = form
        w, h = self.SIZES[form]
        self.setFixedSize(theme.px(w), theme.px(h))
        self.update()

    def set_status(self, keyed: bool, blocked: str, tx_seconds: float, timeout: float, source: str,
                   panel: bool = False, armed_at: float | None = None, mode: str = "",
                   tx: "txstate.TxState | None" = None):
        """`keyed`: on the air now (the window's Face.on_air, not the
        engine's keyed). `armed_at`: transmit armed between overs - when
        the next is due (UTC seconds, 0.0 unknown) - or None. `mode`: the
        radio's mode, for the words under TX. `tx`: txstate.of_bridge();
        without it, `blocked` alone decides (HERE with that sentence, else
        OK)."""
        if keyed != self.keyed:
            self.on.to(1.0 if keyed else 0.0)
        self.keyed, self.blocked, self.tx_seconds, self.timeout, self.source, self.panel = (
            keyed, blocked, tx_seconds, timeout, source, panel)
        self.mode = mode
        if tx is None:
            tx = txstate.TxState(txstate.HERE, blocked) if blocked else txstate.TxState(txstate.OK)
        self.tx = tx
        if tx.kind != txstate.OK and not blocked and not keyed:
            # The class and the sentence must agree: a refusal the window
            # did not pass as `blocked` still greys the tile and locks it.
            self.blocked = tx.why or tx.kind
        self.armed_at = None if keyed else armed_at
        tip = ("On air - release (or click again in toggle mode) to stop. Esc always unkeys." if keyed else
               "Armed: nothing is on the air until the next over. Click, Esc or Halt TX stops it."
               if self.armed_at is not None else
               self.tr("This run cannot transmit:") + f"\n{tx.why}" if tx.kind == txstate.NEVER else
               self.tr("Not set up to transmit yet:") + f"\n{tx.why}" if tx.kind == txstate.SETUP else
               # Panel modes keep the engine's refusal (if any) after the redirect, rather
               # than hiding it, so a genuine band/gain refusal is still visible on hover.
               "This mode sends from its panel below, on its own schedule. Halt there stops it."
               + (f"\n\n{self.blocked}" if self.blocked else "") if self.panel else
               f"Transmit is not available here:\n{self.blocked}" if self.blocked else
               "Transmit (Space). Hold to talk, or toggle - see Settings.")
        self.setToolTip(tip)
        self.update()

    def accessible_text(self) -> str:
        # The big word and, off the air, why (controls.FocusVisible). Not
        # the on-air clock: a name that changed every second would have a
        # screen reader announce it every second.
        label, sub = self.caption()
        return f"TX: {label}" + (f", {sub}" if sub and not self.keyed else "")

    def caption(self) -> tuple[str, str]:
        """(the big word, the line under it) as painted."""
        if self.keyed:
            left = max(0.0, self.timeout - self.tx_seconds)
            return "ON AIR", self.tr("{elapsed}  •  {left} left").format(
                elapsed=f"{int(self.tx_seconds) // 60}:{int(self.tx_seconds) % 60:02d}",
                left=f"{int(left) // 60}:{int(left) % 60:02d}")
        if self.armed_at is not None:
            wait = self.armed_at - time.time()
            return "ARMED", (self.tr("next over in {s} s").format(s=math.ceil(wait)) if wait >= 0.5
                             else self.tr("next over"))
        k = self.tx.kind
        if k == txstate.NEVER:
            return "TX", self.words("rxonly")
        if k == txstate.SETUP:
            return "TX", self.words("setup")
        words = mode_words(self.mode) if self.mode else ("panel" if self.panel else "talk")
        if words == "rxonly" or not self.blocked:
            return "TX", self.words(words)
        return "TX", self.words(here_words(self.blocked))

    def words(self, key: str) -> str:
        """The line under TX for an id from mode_words() or here_words()."""
        return {"talk": self.tr("Space to talk"), "enable": self.tr("Enable TX below"),
                "type": self.tr("Type, Enter sends"), "panel": self.tr("Send from the panel"),
                "rxonly": self.tr("Receive only"), "setup": self.tr("Set up to transmit"),
                "stopped": self.tr("Radio stopped"), "dish": self.tr("Dish alignment open"),
                "onradio": self.tr("Key on the radio"), "swr": self.tr("SWR tripped"),
                "sequencer": self.tr("Sequencer not ready"), "beacon": self.tr("Too near a beacon"),
                "wide": self.tr("Signal too wide"), "segment": self.tr("Not in this segment"),
                "band": self.tr("Not on this band"), "class": self.tr("Choose a licence class"),
                "licence": self.tr("Not on your licence"),
                "power": self.tr("Power over the limit"), "rate": self.tr("Sample rate too low"),
                "playing": self.tr("Playing a recording")}.get(key, self.tr("Not available here"))

    def tick(self, dt):
        if self.keyed:
            self.glow_t += dt
            self.update()

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.down = True
            self.pressed.emit()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.down:
            self.down = False
            self.released.emit()
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        k = self.on.value
        red = theme.c("tx")
        # A panel mode is drawn like a refusal (greyed, no red outline) because
        # pressing this button is never the right move for it - but it isn't
        # one, so it skips the "blocked" lock icon below in favour of its own
        # redirect text.
        avail = not self.blocked and not self.panel
        if k > 0.01:
            pulse = 0.5 + 0.5 * math.sin(self.glow_t * 2 * math.pi / 1.6)
            for i in range(3):
                gl = QColor(theme.t()["txGlow"])
                gl.setAlphaF(0.18 * k * (0.6 + 0.4 * pulse) / (i + 1))
                p.setPen(QPen(gl, 3 + i * 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-i, -i, i, i), 14, 14)
        armed = self.armed_at is not None and not self.keyed
        if armed:
            # Armed is drawn as a live control - red outline and text, no
            # fill or glow - so it reads "about to", never "on the air".
            avail = True
        # Idle and available: neutral - the text colour faintly over the
        # card, a line-coloured outline that brightens on hover. Red only
        # armed (outline and words) and on the air (the fill, faded in by
        # `on`), so nothing red stands on a receiving station's screen.
        base = theme.c("bg2")
        ink = theme.c("text")
        idle_bg = mix(base, ink, 0.04 + 0.05 * self.hover.value) if avail else theme.c("bg2", 0.6)
        bg = mix(idle_bg, red, k)
        if self.down and not self.keyed:
            bg = mix(bg, ink, 0.12)
        idle_line = mix(theme.c("line2"), theme.c("text2"), 0.35 + 0.4 * self.hover.value)
        p.setPen(QPen(red if armed else mix(idle_line, red, k) if avail else theme.c("line2"),
                      2.0 if armed else 1.5))
        p.setBrush(bg)
        p.drawRoundedRect(r, 14, 14)
        fg = QColor("#ffffff") if k > 0.5 else (red if armed else ink if avail else theme.c("text3"))
        label, sub_text = self.caption()
        short = self.form == "tight"
        px = theme.px
        if short:
            # One line's height: the word above, its few words under it.
            p.setFont(theme.font(14 if (self.keyed or armed) else 17, theme.QFont.Weight.Black, spacing=1.2))
            top = QRectF(r.x(), r.y() + px(1), r.width(), r.height() * 0.55)
            sub = QRectF(r.x() + px(6), r.y() + r.height() * 0.52, r.width() - px(12), r.height() * 0.42)
            sub_px, least = 10.0, 8.0
        else:
            p.setFont(theme.font(26, theme.QFont.Weight.Black, spacing=2))
            if self.keyed or armed:
                p.setFont(theme.font(19, theme.QFont.Weight.Black, spacing=1.5))
            top = QRectF(r.x(), r.y() + px(8), r.width(), px(40))
            sub = QRectF(r.x() + px(8), r.y() + px(50), r.width() - px(16), px(30))
            sub_px, least = 12.0, 9.0
        p.setPen(fg)
        locked = self.tx.kind in (txstate.NEVER, txstate.SETUP) or not self.panel
        if not avail and not self.keyed and not armed and locked:
            word_w = QFontMetricsF(p.font()).horizontalAdvance(label)
            ic = px(14 if short else 18)
            icons.paint(p, "lock", QRectF(top.center().x() - word_w / 2 - ic - px(8), top.center().y() - ic / 2, ic, ic),
                        fg, 1.8)
        p.drawText(top, Qt.AlignmentFlag.AlignCenter, label)
        # The line under TX is a few words in the operator's language: the
        # font gives way before the words do, down to `least` px, then it
        # elides (the tooltip has the whole of it).
        size = sub_px
        while True:
            p.setFont(theme.font(size, theme.QFont.Weight.DemiBold, mono=self.keyed))
            fits = QFontMetricsF(p.font()).horizontalAdvance(sub_text) <= sub.width()
            if fits or size <= least:
                break
            size -= 0.5
        if not fits:
            sub_text = QFontMetricsF(p.font()).elidedText(sub_text, Qt.TextElideMode.ElideRight, sub.width())
        if self.keyed:
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(sub, Qt.AlignmentFlag.AlignCenter, sub_text)
            # Time-out progress along the bottom edge.
            frac = min(1.0, self.tx_seconds / max(1.0, self.timeout))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            bar = QRectF(r.x() + theme.px(14), r.bottom() - theme.px(5 if short else 9), r.width() - theme.px(28), 3)
            p.drawRoundedRect(bar, 1.5, 1.5)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * (1 - frac), 3), 1.5, 1.5)
        else:
            p.setPen(red if armed else theme.c("text3") if not avail else theme.c("text2"))
            p.drawText(sub, Qt.AlignmentFlag.AlignCenter, sub_text)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 15, 15)


# ------------------------------------------------------------------ simulator badge
class SimBadge(QWidget):
    """SIMULATOR, beside the app's name, whenever the open radio is the
    simulator; hidden otherwise. Before it, "Simulator" was one word in the
    status strip and the band looked real: operators on Windows and macOS
    (NB/HAM 0.1.9) spent evenings listening to simulated stations believing
    their radio was connected. So it is filled, not outlined, and says it
    in words and colour and shape: amber with an (i) when Settings chose
    it, red with a warning triangle when it stands in for a radio that
    could not be had. The engine's simWhy sentence is the hover."""

    H = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.why = ""
        self.fallback = False
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hide()

    @staticmethod
    def _font():
        return theme.font(12, theme.QFont.Weight.Black, spacing=1.2)

    def sizeHint(self):
        w = QFontMetricsF(self._font()).horizontalAdvance(self.tr("SIMULATOR"))
        return QSize(int(w + 8 + 14 + 6 + 10), self.H)

    def set_state(self, st: dict) -> None:
        self.why = str(st.get("simWhy") or "")
        self.fallback = bool(st.get("simFallback"))
        # One whole tooltip per case, the heading inside it.
        if self.fallback:
            tip = self.tr("<b>Simulator standing in for your radio</b><br>{why}<br><br>Every signal on screen is "
                          "simulated, and nothing you transmit leaves this computer.")
        else:
            tip = self.tr("<b>Simulator</b><br>{why}<br><br>Every signal on screen is simulated, and nothing you "
                          "transmit leaves this computer.")
        self.setToolTip(tip.format(why=html.escape(self.why)) if self.why else "")
        self.setFixedWidth(self.sizeHint().width())
        self.setVisible(bool(self.why))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = theme.c("err" if self.fallback else "warn")
        # Dark ink on amber, white on red: each the higher-contrast choice
        # on its fill in both themes.
        ink = QColor("#ffffff") if self.fallback else QColor("#14100a")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        icons.paint(p, "warn" if self.fallback else "info", QRectF(r.x() + 7, r.center().y() - 7, 14, 14), ink, 1.8)
        p.setFont(self._font())
        p.setPen(ink)
        p.drawText(QRectF(r.x() + 25, r.y(), r.width() - 29, r.height()), Qt.AlignmentFlag.AlignVCenter,
                   self.tr("SIMULATOR"))


# ------------------------------------------------------------------ on-air glow
class OnAirGlow(QWidget):
    """A red glow framing the whole window while transmitting. Transparent
    to the mouse; painted only while on air (or fading out)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.k = Anim(self, ms=220)
        self.on = False
        self.t = 0.0
        self.hide()

    def set_on(self, on: bool):
        self.on = bool(on)            # what it was last told, for a test to read
        if on:
            self.show()
            self.raise_()
        self.k.to(1.0 if on else 0.0)

    def tick(self, dt):
        if self.k.value > 0.001:
            self.t += dt
            self.update()
        elif self.isVisible():
            self.hide()

    def paintEvent(self, _e):
        k = self.k.value
        if k <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = 0.75 + 0.25 * math.sin(self.t * 2 * math.pi / 1.6)
        w, h = self.width(), self.height()
        base = QColor(theme.t()["txGlow"])
        for i in range(10):
            c = QColor(base)
            c.setAlphaF(k * pulse * 0.55 * (1 - i / 10) ** 2)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(1 + i * 2, 1 + i * 2, w - 2 - i * 4, h - 2 - i * 4))
        c = QColor(base)
        c.setAlphaF(k)
        p.setPen(QPen(c, 3))
        p.drawRect(QRectF(1.5, 1.5, w - 3, h - 3))


# ------------------------------------------------------------------ toasts
class Toast(QWidget):
    closed = pyqtSignal(object)

    def __init__(self, parent, level: str, text: str):
        super().__init__(parent)
        self.level, self.text = level, text
        self.k = Anim(self)
        self.born = time.monotonic()
        self.life = {"info": 5.0, "warn": 10.0, "error": 16.0}.get(level, 6.0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hover = False

    def height_for(self, w: int) -> int:
        fm = QFontMetricsF(theme.font(14, theme.QFont.Weight.Medium))
        r = fm.boundingRect(QRectF(0, 0, w - 76, 1000), Qt.TextFlag.TextWordWrap, self.text)
        return int(max(52, r.height() + 30))

    def enterEvent(self, e):
        self.hover = True

    def leaveEvent(self, e):
        self.hover = False

    def mouseReleaseEvent(self, e):
        self.closed.emit(self)

    def expired(self) -> bool:
        return not self.hover and time.monotonic() - self.born > self.life

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.k.value)
        key = {"info": "accent", "warn": "warn", "error": "err"}.get(self.level, "accent")
        col = theme.c(key)
        r = QRectF(self.rect()).adjusted(6, 4, -6, -4)
        sh = QColor(0, 0, 0, 90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sh)
        p.drawRoundedRect(r.translated(0, 3), 10, 10)
        p.setBrush(theme.c("bg2"))
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 140), 1))
        p.drawRoundedRect(r, 10, 10)
        clip = QPainterPath()
        clip.addRoundedRect(r, 10, 10)
        p.save()
        p.setClipPath(clip)
        p.fillRect(QRectF(r.x(), r.y(), 5, r.height()), col)
        # Life left, as a hairline along the bottom.
        left = max(0.0, 1 - (time.monotonic() - self.born) / self.life) if not self.hover else 1.0
        p.fillRect(QRectF(r.x(), r.bottom() - 2, r.width() * left, 2), QColor(col.red(), col.green(), col.blue(), 120))
        p.restore()
        icons.paint(p, "warn" if self.level != "info" else "info", QRectF(r.x() + 18, r.center().y() - 11, 22, 22),
                    col, 2)
        p.setFont(theme.font(14, theme.QFont.Weight.Medium))
        p.setPen(theme.c("text"))
        p.drawText(QRectF(r.x() + 52, r.y() + 8, r.width() - 64, r.height() - 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.text)


class ToastHost(QWidget):
    """Stacks toasts top-centre over the scopes. Non-modal: nothing waits on
    them; a click dismisses one; identical repeats refresh rather than pile up."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.toasts: list[Toast] = []
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._expire)
        self.timer.start()
        self.width_px = 560

    def show_toast(self, level: str, text: str):
        for t in self.toasts:
            if t.text == text:
                t.born = time.monotonic()
                t.update()
                return
        t = Toast(self, level, text)
        t.closed.connect(self._remove)
        self.toasts.insert(0, t)
        del_extra = self.toasts[5:]
        for x in del_extra:
            self._remove(x)
        t.show()
        t.k.to(1.0)
        self._place()

    def _remove(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
            t.hide()
            t.deleteLater()
            self._place()

    def _expire(self):
        for t in list(self.toasts):
            if t.expired():
                self._remove(t)
            else:
                t.update()

    def _place(self):
        pw = self.parentWidget().width() if self.parentWidget() else 800
        w = min(self.width_px, pw - 40)
        y = 0
        for t in self.toasts:
            h = t.height_for(w)
            t.setGeometry(0, y, w, h)
            y += h + 2
        self.setGeometry((pw - w) // 2, 70, w, max(1, y))
        self.raise_()

    def reposition(self):
        self._place()
