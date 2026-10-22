"""The FM panel (docs/ham/DESIGN-HAM.md section 7): repeater shift, its
offset and reverse, the channel name, the 1750 Hz toneburst, the CTCSS tone sent and
the tone squelch, the tone heard, squelch and deviation."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ohscore.dsp.fm import tone_name
from ohscore.ui import theme
from ohscore.ui.controls import Anim, Button, Card, FocusVisible, Segmented, Slider, Toggle, focus_ring, mix
from ohscore.ui.keyer import VoiceKeyerBar
from ohscore.ui.panels.common import ModePanel

from ..state import TONE_CHOICES
from .face import mhz_text


class ToneWheel(FocusVisible, QWidget):
    """One CTCSS tone of the 50 (or off): the tone large, UK letter first;
    the wheel, the arrow keys or the two arrows step through them."""

    picked = pyqtSignal(float)

    def __init__(self, label: str, value: float, parent=None):
        super().__init__(parent)
        self.label = label
        self.value = float(value or 0.0)
        self.hover = Anim(self)
        self.setFixedHeight(58)
        self.setMinimumWidth(170)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(200, 58)

    def set_value(self, v: float):
        v = float(v or 0.0)
        if v != self.value:
            self.value = v
            self.update()

    def _step(self, d: int):
        i = TONE_CHOICES.index(self.value) if self.value in TONE_CHOICES else 0
        i = max(0, min(len(TONE_CHOICES) - 1, i + d))
        if TONE_CHOICES[i] != self.value:
            self.value = TONE_CHOICES[i]
            self.update()
            self.picked.emit(self.value)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self._step(1 if d > 0 else -1)
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Up, Qt.Key.Key_Right):
            self._step(1)
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_Left):
            self._step(-1)
        elif k == Qt.Key.Key_Home:
            self._step(-len(TONE_CHOICES))
        else:
            super().keyPressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            x = e.position().x()
            self._step(-1 if x < self.width() / 2 else 1)

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 18.5, -0.5, -0.5)
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignVCenter, self.label)
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(mix(theme.c("bg2"), theme.c("bg3"), self.hover.value))
        p.drawRoundedRect(r, 6, 6)
        on = bool(self.value)
        text = tone_name(self.value)
        p.setFont(theme.font(17, theme.QFont.Weight.Bold, mono=True))
        p.setPen(theme.c("text") if on else theme.c("text3"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.tr("{tone} Hz").format(tone=text) if on else text)
        p.setPen(QPen(theme.c("text3"), 1.6, cap=Qt.PenCapStyle.RoundCap))
        cy = r.center().y()
        for x, d in ((r.x() + 14, -1), (r.right() - 14, 1)):
            p.drawLine(QPointF(x - 3 * d, cy - 5), QPointF(x + 2 * d, cy))
            p.drawLine(QPointF(x + 2 * d, cy), QPointF(x - 3 * d, cy + 5))
        if self.focus_visible():
            focus_ring(p, r, 6)


class ToneHeard(QWidget):
    """The CTCSS tone on the received signal, lit while heard, with the
    squelch state beside it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tone = 0.0
        self.open = False
        self.setFixedHeight(58)

    def set(self, tone: float, open_: bool):
        if (tone, open_) != (self.tone, self.open):
            self.tone, self.open = tone, open_
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignVCenter, self.tr("Heard"))
        r = QRectF(self.rect()).adjusted(0.5, 18.5, -0.5, -0.5)
        col = theme.c("ok") if self.tone else (theme.c("rx") if self.open else theme.c("text3"))
        p.setPen(QPen(theme.c(("ok" if self.tone else "line")), 1))
        p.setBrush(theme.c("ok", 0.10) if self.tone else theme.c("bg2"))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("rx") if self.open else theme.c("line2"))
        p.drawEllipse(QRectF(r.x() + 12, r.center().y() - 5, 10, 10))
        p.setFont(theme.font(17, theme.QFont.Weight.Bold, mono=True))
        p.setPen(col)
        text = (tone_name(self.tone) + " Hz") if self.tone else ("carrier" if self.open else "squelched")
        p.drawText(r.adjusted(26, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, text)


class ChannelPlate(QWidget):
    """Channel name and the input/output pair, large."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name, self.line = "", ""
        self.setFixedHeight(64)

    def set(self, name: str, line: str):
        if (name, line) != (self.name, self.line):
            self.name, self.line = name, line
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(theme.font(26, theme.QFont.Weight.Bold))
        p.setPen(theme.c("text") if self.name else theme.c("text3"))
        fm = QFontMetricsF(p.font())
        name = self.name or "—"
        p.drawText(QRectF(0, 0, self.width(), 36), Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(theme.font(12.5, mono=True))
        p.setPen(theme.c("text2"))
        p.drawText(QRectF(0, 38, self.width(), 22), Qt.AlignmentFlag.AlignVCenter, self.line)
        _ = fm


class FmPanel(ModePanel):
    modes = ("fm",)

    def __init__(self, bridge, prefs, parent=None):
        super().__init__(bridge, prefs, parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.S3)
        lay = QHBoxLayout()
        lay.setSpacing(theme.S3)
        outer.addLayout(lay, 1)

        rpt = Card(self.tr("Repeater"))
        self.plate = ChannelPlate()
        rpt.lay.addWidget(self.plate)
        self.shift = Segmented([("auto", self.tr("Auto")), ("simplex", self.tr("Simplex")), ("minus", "−"),
                                ("plus", "+")],
                               self.st("rptShift", "auto"))
        self.shift.picked.connect(lambda v: bridge.set(rptShift=v))
        rpt.lay.addWidget(self.shift)
        # The size of − and +, in MHz. Arriving in a band sets it to the
        # band's usual split in the plan or country in force
        # (plans/repeaters.py); this is for the rest - an RBW repeater's
        # 5 MHz, a 7.6 MHz RU pair, anything non-standard.
        orow = QHBoxLayout()
        cap = QLabel(self.tr("Offset for − and +"))
        cap.setObjectName("Muted")
        self.offset = QLineEdit()
        self.offset.setObjectName("Offset")
        self.offset.setFont(theme.font(13, mono=True))
        self.offset.setFixedWidth(110)
        self.offset.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.offset.setToolTip(self.tr("The repeater offset − and + use, in MHz (e.g. 0.6, 1.6, 5, 6). It is set to "
                                       "the band's usual split in your country's plan when you arrive in a band; "
                                       "Auto ignores it."))
        self.offset.editingFinished.connect(self._offset)
        unit = QLabel(self.tr("MHz"))
        unit.setObjectName("Muted")
        orow.addWidget(cap)
        orow.addStretch(1)
        orow.addWidget(self.offset)
        orow.addWidget(unit)
        rpt.lay.addLayout(orow)
        row = QHBoxLayout()
        self.reverse = Toggle(self.tr("Reverse"), bool(self.st("rptReverse")))
        self.reverse.toggled.connect(lambda on: bridge.set(rptReverse=on))
        self.burst = Button(self.tr("1750 Hz"), icon="waves", small=True)
        self.burst.setToolTip(self.tr("Toneburst: 1750 Hz for the time set in Settings. Still accepted by many UK "
                                      "repeaters, but being withdrawn in favour of CTCSS (RSGB)."))
        self.burst.clicked.connect(self._burst)
        row.addWidget(self.reverse)
        row.addStretch(1)
        row.addWidget(self.burst)
        rpt.lay.addLayout(row)
        rpt.lay.addStretch(1)
        lay.addWidget(rpt, 3)

        tones = Card(self.tr("CTCSS"))
        g = QGridLayout()
        g.setHorizontalSpacing(theme.S4)
        g.setVerticalSpacing(theme.S2)
        self.tx_tone = ToneWheel(self.tr("Send"), self.st("ctcssTx", 0.0))
        self.tx_tone.picked.connect(lambda v: bridge.set(ctcssTx=v))
        self.rx_tone = ToneWheel(self.tr("Tone squelch"), self.st("ctcssRx", 0.0))
        self.rx_tone.picked.connect(lambda v: bridge.set(ctcssRx=v))
        self.heard = ToneHeard()
        g.addWidget(self.tx_tone, 0, 0)
        g.addWidget(self.rx_tone, 0, 1)
        g.addWidget(self.heard, 1, 0, 1, 2)
        tones.lay.addLayout(g)
        self.use_heard = Button(self.tr("Send the tone heard"), small=True)
        self.use_heard.clicked.connect(self._use_heard)
        tones.lay.addWidget(self.use_heard)
        tones.lay.addStretch(1)
        lay.addWidget(tones, 3)

        rx = Card(self.tr("Receive & audio"))
        sp = bridge.radio.STATE.spec
        self.sql = Slider(self.tr("Squelch"), 0.0, 1.0, self.st("sqlLevel", 0.5), 0.05,
                          lambda v: self.tr("open") if v == 0 else f"{v * 100:.0f} %", default=0.5)
        self.sql.changed.connect(lambda v: bridge.set(quiet=True, sqlLevel=v))
        self.dev = Segmented([("2500.0", "12.5 kHz ·2.5"), ("5000.0", "25 kHz ·5")],
                             str(float(self.st("fmDeviation", 2500.0))))
        self.dev.picked.connect(lambda v: bridge.set(fmDeviation=float(v)))
        self.mic = Slider(self.tr("Mic gain"), sp["micGain"]["min"], sp["micGain"]["max"], self.st("micGain", 0), 1,
                          lambda v: f"{v:+.0f} dB", default=0)
        self.mic.committed.connect(lambda v: bridge.set(micGain=v))
        cap = QLabel(self.tr("Channel and deviation"))
        cap.setObjectName("Muted")
        rx.lay.addWidget(self.sql)
        rx.lay.addWidget(cap)
        rx.lay.addWidget(self.dev)
        rx.lay.addWidget(self.mic)
        rx.lay.addStretch(1)
        lay.addWidget(rx, 3)
        # The voice memories (ohscore/ui/keyer.py): one row across the foot of
        # the panel. A fourth card beside these three squeezed Receive &
        # audio until its deviation buttons clipped (tried first, 08/10).
        kc = Card(self.tr("Voice keyer"))
        self.keyer = VoiceKeyerBar(bridge, inline=True)
        kc.lay.addWidget(self.keyer)
        self.keyer_card = kc
        outer.addWidget(kc)
        self._sync()

    def _burst(self):
        b = self.bridge
        if not b.licence_ok:
            b.say(self.tr("Transmit is locked until the licence box is ticked (Settings › Station)"))
            return
        try:
            b.radio.toneburst()
        except ValueError as e:
            b.say(str(e))

    def _offset(self):
        text = self.offset.text().strip().replace(",", ".")
        try:
            hz = round(float(text) * 1e6)
        except ValueError:
            self.bridge.say(self.tr("{text} is not an offset in MHz (e.g. 1.6)").format(text=repr(text)))
            self._show_offset(force=True)
            return
        if not self.bridge.set(rptOffsetHz=float(abs(hz))):
            self._show_offset(force=True)

    def _show_offset(self, force: bool = False):
        # Not while the operator is typing in it: a state update would
        # overwrite what they have half entered.
        if force or not self.offset.hasFocus():
            hz = float(self.st("rptOffsetHz", 600_000.0) or 0.0)
            self.offset.setText(f"{hz / 1e6:.4f}".rstrip("0").rstrip(".") if hz else "0")

    def _use_heard(self):
        t = float(self.st("ctcssHeard") or 0.0)
        if t:
            self.bridge.set(ctcssTx=t)
        else:
            self.bridge.say(self.tr("No CTCSS tone heard on this channel yet"))

    def _sync(self):
        st = self.bridge.st
        vfo = float(st.get("vfo") or 0.0)
        name = st.get("channel") or ""          # the plan in force's name (ohsradio/radio.py)
        sh = float(st.get("shift") or 0.0)
        txd = float(st.get("txDial") or vfo)
        if sh:
            line = f"out {mhz_text(int(round(vfo)))}   in {mhz_text(int(round(vfo + sh)))}   ({sh / 1e6:+.3f})"
        else:
            line = f"simplex {mhz_text(int(round(txd)))}"
        self.plate.set(name, line.replace("-", "−"))
        self.shift.set_value(st.get("rptShift", "auto"))
        self._show_offset()
        self.reverse.set_on(bool(st.get("rptReverse")))
        self.tx_tone.set_value(st.get("ctcssTx", 0.0))
        self.rx_tone.set_value(st.get("ctcssRx", 0.0))
        self.heard.set(float(st.get("ctcssHeard") or 0.0), bool(st.get("sqlOpen")))

    def set_mirror(self):
        super().set_mirror()
        self.keyer_card.hide()

    def on_state(self, ch):
        self.keyer.on_state(ch)
        if any(k in ch for k in ("vfo", "shift", "txDial", "rptShift", "rptOffsetHz", "rptReverse", "ctcssTx",
                                 "ctcssRx", "ctcssHeard", "sqlOpen", "mode")):
            self._sync()
        if "sqlLevel" in ch:
            self.sql.set_value(ch["sqlLevel"])
        if "fmDeviation" in ch:
            self.dev.set_value(str(float(ch["fmDeviation"])))
