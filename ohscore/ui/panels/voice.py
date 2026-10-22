"""USB / LSB / AM / FreeDV: the microphone chain, and FreeDV's modem status."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import fmt
from .. import theme
from ..controls import Card, Segmented, Slider, Toggle
from ..keyer import VoiceKeyerBar
from ..meters import BarMeter
from .common import ModePanel

FREEDV_LABELS = [("700d", "700D"), ("700c", "700C"), ("700e", "700E"), ("1600", "1600"), ("2020", "2020")]


class SyncBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sync = False
        self.setFixedHeight(54)

    def set_sync(self, on: bool):
        if on != self.sync:
            self.sync = on
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = theme.c("ok") if self.sync else theme.c("text3")
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = theme.c("ok", 0.14) if self.sync else theme.c("bg2")
        p.setPen(QPen(col if self.sync else theme.c("line"), 1.2))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        p.setFont(theme.font(20, theme.QFont.Weight.Black, spacing=2))
        p.setPen(col)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.tr("SYNC") if self.sync else self.tr("NO SYNC"))


class TxBand(QWidget):
    """The transmit audio passband on a 0-3 kHz ruler, against the app's
    width limit (NB: QO-100's 2.7 kHz) - what the two sliders beneath it
    actually mean."""

    def __init__(self, parent=None, limit: float | None = None):
        super().__init__(parent)
        self.limit = limit
        self.lo, self.hi = 300.0, 2700.0
        self.setFixedHeight(46)

    def set_band(self, lo, hi):
        self.lo, self.hi = float(lo), float(hi)
        self.update()

    def _tick_font(self):
        return theme.font(10, mono=True)

    def tick_labels(self) -> list[tuple[QRectF, str]]:
        """The ruler's figures and where each is drawn: centred on its
        tick, but kept inside the widget. The ends' ticks sit 4 px in
        from the edges, so "3k" centred on its tick lost its last 3 px off
        the right (WP9's 1024 x 600 check) and "0" nearly its first."""
        fm = QFontMetricsF(self._tick_font())
        w = self.width()
        out = []
        for f in (0, 500, 1000, 1500, 2000, 2500, 3000):
            text = f"{f / 1000:g}k" if f else "0"
            tw = fm.horizontalAdvance(text) + 2
            cx = 4 + (w - 8) * f / 3000.0
            left = min(max(0.0, cx - tw / 2), w - tw)
            out.append((QRectF(left, 25, tw, 14), text))
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        def x(f):
            return 4 + (w - 8) * f / 3000.0

        tr = QRectF(4, 8, w - 8, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("bg3"))
        p.drawRoundedRect(tr, 4, 4)
        width = self.hi - self.lo
        over = self.limit is not None and width > self.limit
        col = theme.c("err") if over else theme.c("tx")
        band = QRectF(x(self.lo), tr.y(), x(self.hi) - x(self.lo), tr.height())
        c = QColor(col)
        c.setAlphaF(0.35)
        p.setBrush(c)
        p.drawRoundedRect(band, 3, 3)
        p.setPen(QPen(col, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(band, 3, 3)
        p.setFont(self._tick_font())
        p.setPen(theme.c("text3"))
        for box, text in self.tick_labels():
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.setFont(theme.font(11.5, theme.QFont.Weight.DemiBold))
        p.setPen(col if over else theme.c("text"))
        p.drawText(band, Qt.AlignmentFlag.AlignCenter, fmt.frequency(int(round(width)), "kHz", 2))


class VoicePanel(ModePanel):
    modes = ("usb", "lsb", "am", "freedv")

    def __init__(self, bridge, prefs, parent=None):
        super().__init__(bridge, prefs, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        sp = bridge.radio.STATE.spec
        mic = Card(self.tr("Microphone"))
        self.mic_gain = Slider(self.tr("Mic gain"), sp["micGain"]["min"], sp["micGain"]["max"], self.st("micGain", 0),
                               1, lambda v: f"{v:+.0f} dB", default=0)
        self.mic_gain.committed.connect(lambda v: bridge.set(micGain=v))
        self.mic_gain.changed.connect(lambda v: bridge.set(quiet=True, micGain=v))
        self.comp = Slider(self.tr("Compressor"), sp["compressor"]["min"], sp["compressor"]["max"],
                           self.st("compressor", 6), 1,
                           lambda v: self.tr("off") if v == 0 else f"{v:.0f} dB", default=6)
        self.comp.changed.connect(lambda v: bridge.set(quiet=True, compressor=v))
        self.mic_meter = BarMeter(self.tr("Mic level"), -60, 0, lambda v: f"{v:.0f}", ticks=(-60, -40, -20, -10, 0),
                                  zones=((-60, -20, "ok"), (-20, -6, "ok"), (-6, -3, "warn"), (-3, 0, "err")),
                                  unit="dBFS")
        mon = QHBoxLayout()
        # The switch alone: "Monitor level" beside it names it, and with its
        # own word as well the pair did not fit the card at 130 % text in a
        # longer language ("M" and a switch).
        self.monitor = Toggle(self.tr("Monitor"), bool(self.st("monitor")), show_label=False)
        self.monitor.toggled.connect(lambda on: bridge.set(monitor=on))
        self.mon_level = Slider(self.tr("Monitor level"), 0, 1, self.st("monitorLevel", 0.3), 0.05,
                                lambda v: f"{v * 100:.0f} %", default=0.3)
        self.mon_level.changed.connect(lambda v: bridge.set(quiet=True, monitorLevel=v))
        mon.addWidget(self.monitor, 0, Qt.AlignmentFlag.AlignBottom)
        mon.addWidget(self.mon_level, 1)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.S5)
        grid.setVerticalSpacing(theme.S2)
        grid.addWidget(self.mic_gain, 0, 0)
        grid.addWidget(self.comp, 0, 1)
        grid.addWidget(self.mic_meter, 1, 0)
        grid.addLayout(mon, 1, 1)
        mic.lay.addLayout(grid)
        mic.lay.addSpacing(theme.S2)
        # The voice memories sit with the microphone they stand in for.
        self.keyer = VoiceKeyerBar(bridge)
        mic.lay.addWidget(self.keyer)
        mic.lay.addStretch(1)
        self.mic = mic
        lay.addWidget(mic, 3)

        txa = Card(self.tr("Transmit audio"))
        self.band = TxBand(limit=bridge.face.tx_width_limit)
        txa.lay.addWidget(self.band)
        self.txlo = Slider(self.tr("Low edge"), sp["txFilterLo"]["min"], sp["txFilterLo"]["max"],
                           self.st("txFilterLo", 300), 50, lambda v: f"{v:.0f} Hz", default=300)
        self.txhi = Slider(self.tr("High edge"), sp["txFilterHi"]["min"], sp["txFilterHi"]["max"],
                           self.st("txFilterHi", 2700), 50, lambda v: f"{v:.0f} Hz", default=2700)
        self.txlo.committed.connect(lambda v: self._txf(txFilterLo=v))
        self.txhi.committed.connect(lambda v: self._txf(txFilterHi=v))
        self.txlo.changed.connect(lambda v: self.band.set_band(v, self.txhi.v))
        self.txhi.changed.connect(lambda v: self.band.set_band(self.txlo.v, v))
        row2 = QHBoxLayout()
        row2.setSpacing(theme.S4)
        row2.addWidget(self.txlo)
        row2.addWidget(self.txhi)
        txa.lay.addLayout(row2)
        note = QLabel(bridge.face.text("txWidth"))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        txa.lay.addWidget(note)
        txa.lay.addStretch(1)
        self.band.set_band(self.txlo.v, self.txhi.v)
        self.txa = txa
        lay.addWidget(txa, 2)

        self.fdv = Card("FreeDV")
        self.wave = Segmented(FREEDV_LABELS, self.st("freedvMode", "700d"))
        self.wave.picked.connect(lambda v: bridge.set(freedvMode=v))
        self.sync = SyncBadge()
        self.snr = BarMeter(self.tr("Modem SNR"), -5, 20, lambda v: f"{v:.1f}", ticks=(-5, 0, 5, 10, 15, 20),
                            zones=((-5, 2, "err"), (2, 6, "warn"), (6, 20, "ok")), unit="dB")
        self.fdv_text = QLabel("—")
        self.fdv_text.setFont(theme.font(15, theme.QFont.Weight.DemiBold, mono=True))
        self.fdv_text.setStyleSheet(f"color: {theme.t()['text']};")
        self.fdv_text.setToolTip(self.tr("FreeDV's text channel (usually the other station's callsign)"))
        self.fdv.lay.addWidget(self.wave)
        row = QHBoxLayout()
        row.setSpacing(theme.S3)
        row.addWidget(self.sync, 1)
        col = QVBoxLayout()
        col.addWidget(self.snr)
        col.addWidget(self.fdv_text)
        row.addLayout(col, 2)
        self.fdv.lay.addLayout(row)
        self.fdv.lay.addStretch(1)
        lay.addWidget(self.fdv, 3)

        self.am_note = Card("AM")
        n = QLabel(bridge.face.text("am"))
        n.setWordWrap(True)
        n.setObjectName("Muted")
        self.am_note.lay.addWidget(n)
        self.am_note.lay.addStretch(1)
        lay.addWidget(self.am_note, 2)
        self._mode_changed()

    def _txf(self, **kw):
        if not self.bridge.set(**kw):
            st = self.bridge.st
            self.txlo.set_value(st.get("txFilterLo", 300))
            self.txhi.set_value(st.get("txFilterHi", 2700))
        self.band.set_band(self.txlo.v, self.txhi.v)

    def _mode_changed(self):
        mode = self.st("mode")
        info = (self.st("modes") or {}).get(mode, {})
        # A microphone, its keyer and the transmit audio only for a mode
        # this app can send. NB's AM is receive-only (listening to the
        # beacons), and its panel offered a mic gain and voice memories that
        # could never go anywhere (Mac test of 17/10/2026, finding 26);
        # Radio's AM transmits (ohsradio/radio.py marks it encode) and keeps
        # them.
        sends = mode != "am" or (isinstance(info, dict) and bool(info.get("encode")))
        self.mic.setVisible(sends)
        self.fdv.setVisible(mode == "freedv")
        self.am_note.setVisible(mode == "am")
        self.txa.setVisible(mode in ("usb", "lsb"))
        info = (self.st("modes") or {}).get("freedv", {})
        waves = info.get("waveforms", {}) if isinstance(info, dict) else {}
        self.wave.set_disabled({k: v for k, v in waves.items() if v})

    def set_mirror(self):
        super().set_mirror()
        self.keyer.hide()

    def on_state(self, ch):
        self.keyer.on_state(ch)
        if "mode" in ch or "modes" in ch:
            self._mode_changed()
        if "freedvMode" in ch:
            self.wave.set_value(ch["freedvMode"])
        if "micGain" in ch:
            self.mic_gain.set_value(ch["micGain"])
        if "compressor" in ch:
            self.comp.set_value(ch["compressor"])
        if "monitor" in ch:
            self.monitor.set_on(ch["monitor"])
        if "txFilterLo" in ch or "txFilterHi" in ch:
            self.txlo.set_value(self.st("txFilterLo", 300))
            self.txhi.set_value(self.st("txFilterHi", 2700))
            self.band.set_band(self.txlo.v, self.txhi.v)

    def on_meter(self, m):
        self.mic_meter.set_value(m.get("mic") if m.get("keyed") else None)

    def on_event(self, ev):
        if ev.get("mode") != "freedv":
            return
        if "sync" in ev:
            self.sync.set_sync(bool(ev["sync"]))
            self.snr.set_value(ev.get("snr") if ev["sync"] else None)
        if ev.get("text"):
            t = (self.fdv_text.text().replace("—", "") + ev["text"])[-40:]
            self.fdv_text.setText(t)

    def tick(self, dt):
        self.mic_meter.tick(dt)
        self.snr.tick(dt)
