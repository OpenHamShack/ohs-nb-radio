"""CW, PSK and RTTY: a terminal, type-ahead transmit, macros - and for the
keyboard modes a signal browser that lists the carriers in the passband.

PSK decodes several stations at once (shack_sdr's psk decoder, Radio's SDR
milestone 2): the terminal is the mode's own channel, the one the dial puts
at its offset and transmit answers on; each further station - a click on
it on the zoom, kept in pskChannels - is a line under "Also decoding" with
the end of what it is sending, and its text is on the zoom at its signal."""
from __future__ import annotations

import time

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QWidget

from .. import theme
from ..controls import Button, Card, Slider
from ..prefs import expand_macro, macro_missing
from .common import MacroBar, ModePanel, Terminal, TxEntry, TxQueue

TEXT_MODES = ("psk31", "psk63", "psk125", "rtty")
PSK_MODES = ("psk31", "psk63", "psk125")
# Characters of each further PSK station's text shown on its line.
STATION_KEEP = 48

# What a decoder may hand the terminal that the terminal must not draw.
# PSK's varicode covers all 256 byte values, so noise (or a station's
# software) can produce NUL, BEL, ESC and the C1 controls; a QTextEdit
# draws each of those as an empty box. A line feed is a line break and a
# tab is spacing, so they stay; CR is dropped because senders follow it with
# LF (CR LF), and turning it into a break as well would double-space every
# line. Everything else in C0, DEL and C1 prints nothing, as on a teleprinter.
_UNPRINTABLE = {c: None for c in [*range(0x00, 0x20), *range(0x7F, 0xA0)] if chr(c) not in "\n\t"}


def printable(text: str) -> str:
    """`text` as the terminal should show it: line feeds and tabs kept,
    every other control character removed."""
    return text.translate(_UNPRINTABLE)


def mode_offset(mode: str) -> float:
    try:
        from ...modes import MODES
        return float(MODES[mode].offset_hz)
    except Exception:  # noqa: BLE001 - the registry may be missing; the decoders' default
        return 1000.0


class QsoFields(QWidget):
    """The other station's call and the report, for macro substitution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.call = QLineEdit()
        self.call.setPlaceholderText(self.tr("Their call"))
        self.call.setFont(theme.font(13.5, theme.QFont.Weight.DemiBold, mono=True))
        self.call.setMinimumWidth(116)
        self.call.setMaximumWidth(150)
        self.rst = QLineEdit("599")
        self.rst.setFont(theme.font(13.5, mono=True))
        self.rst.setFixedWidth(62)
        self.rst.setToolTip(self.tr("Report sent ({RST})"))
        lab = QLabel(self.tr("QSO"))
        lab.setFont(theme.caps())
        lab.setStyleSheet(f"color: {theme.t()['text3']};")
        lay.addWidget(lab)
        lay.addWidget(self.call)
        lay.addWidget(self.rst)


class TextPanel(ModePanel):
    """CW when built with cw=True; otherwise PSK31/63/125 and RTTY."""

    def __init__(self, bridge, prefs, parent=None, cw: bool = False, big: bool = False):
        super().__init__(bridge, prefs, parent)
        self.cw = cw
        self.modes = ("cw",) if cw else TEXT_MODES
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        sp = bridge.radio.STATE.spec
        main = Card("CW" if cw else self.tr("Keyboard"))
        self.main = main
        self.term = Terminal(big=big)
        main.lay.addWidget(self.term, 1)
        self.entry = TxEntry(self.tr("Type to transmit — Enter sends (Morse)") if cw
                             else self.tr("Type to transmit — Enter sends"))
        self.entry.submit.connect(self._queue)
        self.entry.stop_btn.clicked.connect(self.stop_tx)
        main.lay.addWidget(self.entry)
        row = QHBoxLayout()
        row.setSpacing(theme.S3)
        self.qso = QsoFields()
        row.addWidget(self.qso)
        self.macros = MacroBar(prefs, "cwMacros" if cw else "textMacros", mycall_fn=self.mycall,
                               loc_fn=lambda: str(self.st("locator") or ""))
        self.macros.fire.connect(self._macro)
        row.addWidget(self.macros, 1)
        main.lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Faint")
        self.status.setFont(theme.font(12, mono=True))
        main.set_header_widget(self.status)
        lay.addWidget(main, 5)

        side = Card(self.tr("Keyer") if cw else self.tr("Signals"))
        if cw:
            self.wpm = Slider(self.tr("Speed"), sp["cwWpm"]["min"], sp["cwWpm"]["max"], self.st("cwWpm", 20), 1,
                              lambda v: f"{v:.0f} wpm", default=20)
            self.wpm.changed.connect(lambda v: bridge.set(quiet=True, cwWpm=v))
            self.pitch = Slider(self.tr("Pitch"), sp["cwPitch"]["min"], sp["cwPitch"]["max"], self.st("cwPitch", 700),
                                10, lambda v: f"{v:.0f} Hz", default=700)
            self.pitch.changed.connect(lambda v: bridge.set(quiet=True, cwPitch=v))
            self.width_ = Slider(self.tr("Filter"), sp["cwWidth"]["min"], sp["cwWidth"]["max"],
                                 self.st("cwWidth", 500), 50, lambda v: f"{v:.0f} Hz", default=500)
            self.width_.changed.connect(lambda v: bridge.set(quiet=True, cwWidth=v))
            for w in (self.wpm, self.pitch, self.width_):
                side.lay.addWidget(w)
            self.heard = QLabel(self.tr("Decoder speed —"))
            self.heard.setObjectName("Muted")
            side.lay.addWidget(self.heard)
            side.lay.addStretch(1)
        else:
            hint = QLabel(self.tr("Carriers in the passband. Click one to tune it to the decoder."))
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            side.lay.addWidget(hint)
            self.sig = QListWidget()
            self.sig.setFont(theme.font(13, mono=True))
            self.sig.itemClicked.connect(self._pick_signal)
            side.lay.addWidget(self.sig, 1)
            more = QHBoxLayout()
            self.more_title = QLabel(self.tr("Also decoding"))
            self.more_title.setFont(theme.caps())
            self.more_title.setStyleSheet(f"color: {theme.t()['text3']};")
            more.addWidget(self.more_title, 1)
            self.more_clear = Button(self.tr("Stop all"), small=True)
            self.more_clear.setToolTip(self.tr("Stop decoding the stations below; the decoder's own channel carries on"))
            self.more_clear.clicked.connect(lambda: bridge.set(quiet=True, pskChannels=[]))
            more.addWidget(self.more_clear)
            side.lay.addLayout(more)
            self.more = QListWidget()
            self.more.setFont(theme.font(12, mono=True))
            self.more.setToolTip(self.tr("Click a station on the zoom to decode it too, and again to stop. "
                                         "Shift-click puts it on the decoder's own channel."))
            side.lay.addWidget(self.more, 1)
        lay.addWidget(side, 2)
        # PSK's further stations: audio Hz -> the end of what each sent.
        self.station_text: dict[float, str] = {}
        self.side = side
        self.txq = TxQueue(bridge, self._send_opts, lambda t: self.term.put(t, "tx"))
        self.carriers: list[tuple[float, float]] = []
        self.last_scan = 0.0
        self.offset = prefs["textOffset"]
        if not cw:
            self._show_stations()

    def _send_opts(self):
        mode = self.st("mode")
        if self.cw:
            return "cw", {}
        return mode, {"freq": mode_offset(mode)}

    def _queue(self, text: str):
        self.txq.add(text if self.cw else text)
        self._status()

    def _macro(self, m: str) -> bool:
        call = self.qso.call.text().strip().upper()
        loc = str(self.st("locator") or "").strip()
        why = macro_missing(m, self.mycall(), call, loc)
        if why:
            self.bridge.say(why)
            return False
        text = expand_macro(m, self.mycall(), call, self.qso.rst.text().strip(), loc)
        self._queue(text + " ")
        return True

    def stop_tx(self):
        # Stop means now, not after the radio has sent what it holds.
        self.txq.clear()
        if self.st("keyed"):
            self.bridge.halt()
        self._status()

    def _status(self):
        n = len(self.txq.pending)
        self.status.setText(f"{n} queued" if n else "")
        self.status.adjustSize()
        self.main._place()

    def on_event(self, ev):
        mode = ev.get("mode")
        if mode not in self.modes or "text" not in ev:
            return
        text = printable(ev["text"])
        if not text:
            return
        chan = ev.get("channel")
        if not self.cw and chan is not None and abs(float(chan) - mode_offset(mode)) > 1.0:
            # A further PSK station: its own line, not the terminal.
            key = float(chan)
            line = (self.station_text.get(key, "") + text.replace("\n", " "))[-STATION_KEEP:]
            self.station_text[key] = line
            self._show_stations()
            return
        # The CW decoder spells a pattern it cannot read as "[.-..-]": shown,
        # but quietly - it is noise more often than it is a message.
        self.term.put(text, "dim" if text.startswith("[") and text.endswith("]") else "rx")
        if self.cw and ev.get("wpm"):
            self.heard.setText(self.tr("Decoder hears {wpm} wpm").format(wpm=f"{ev['wpm']:.0f}"))

    def on_meter(self, m):
        # The speed is the decoder's while it hears someone; once its
        # squelch closes the label goes back to saying it hears no one,
        # rather than keeping the last station's speed for good. Absent
        # (no CW decoder yet), the label is left as it is.
        if self.cw and m.get("cwHearing") is False:
            self.heard.setText(self.tr("Decoder speed —"))

    def on_state(self, ch):
        if "callsign" in ch or "locator" in ch:
            self.macros.rebuild()
        if self.cw:
            for k, w in (("cwWpm", self.wpm), ("cwPitch", self.pitch), ("cwWidth", self.width_)):
                if k in ch:
                    w.set_value(ch[k])
        if "mode" in ch and not self.cw:
            self.main.title = {"rtty": "RTTY 45.45 / 170"}.get(ch["mode"], str(ch["mode"]).upper())
            self.main.update()
        if not self.cw and ("mode" in ch or "pskChannels" in ch):
            self._show_stations()

    def _show_stations(self):
        """The "Also decoding" list: PSK only, one line per further station
        (pskChannels), what it last sent beside its frequency."""
        psk = self.st("mode") in PSK_MODES
        for w in (self.more_title, self.more_clear, self.more):
            w.setVisible(psk)
        chans = [float(c) for c in (self.st("pskChannels") or [])] if psk else []
        for k in [k for k in self.station_text if k not in chans]:
            del self.station_text[k]
        self.more.clear()
        for c in sorted(chans):
            it = QListWidgetItem(f"{c:5.0f} Hz  {self.station_text.get(c, '').strip()}")
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.more.addItem(it)
        self.more_clear.setEnabled(bool(chans))
        if psk and not chans:
            it = QListWidgetItem(self.tr("Click a station on the zoom to decode it too"))
            it.setForeground(theme.c("text3"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.more.addItem(it)

    def adopt(self, other: "TextPanel"):
        """Start a mirror with what the main terminal already shows."""
        for text, kind, t in other.term.history:
            self.term.put(text, kind, t)

    def carry_from(self, other: "TextPanel"):
        """The window was rebuilt (a theme change): what was received, in
        this theme's colours - replayed, as for a mirror. Text typed but
        not sent goes too; the transmit queue does not."""
        self.adopt(other)
        self.entry.edit.setText(other.entry.edit.text())

    def set_mirror(self):
        super().set_mirror()
        self.entry.hide()
        self.macros.hide()
        self.qso.hide()

    def tick(self, dt):
        if self.mirror:
            return
        self.txq.pump()
        self._status()

    # --------------------------------------------------- signal browser
    def scan(self, lines: list):
        """Find carriers in the receive passband from the zoom spectrum: local
        peaks well above the median, merged when closer than 40 Hz."""
        if self.cw or not lines:
            return
        now = time.monotonic()
        if now - self.last_scan < 1.0:
            return
        self.last_scan = now
        t, start, bin_hz, db = lines[-1]
        dial = float(self.st("rxDial") or self.st("vfo"))
        f = start + np.arange(len(db)) * bin_hz - dial
        sel = (f > 150) & (f < 3000)
        if sel.sum() < 8:
            return
        d, ff = db[sel], f[sel]
        floor = float(np.median(d))
        pk = (d[1:-1] > d[:-2]) & (d[1:-1] >= d[2:]) & (d[1:-1] > floor + 8)
        idx = np.nonzero(pk)[0] + 1
        found = []
        for i in idx[np.argsort(-d[idx])][:12]:
            if all(abs(ff[i] - x) > 40 for x, _ in found):
                found.append((float(ff[i]), float(d[i] - floor)))
        found.sort()
        self.sig.clear()
        off = mode_offset(self.st("mode"))
        for fo, snr in found:
            it = QListWidgetItem(f"{fo:6.0f} Hz   {snr:4.0f} dB")
            it.setData(Qt.ItemDataRole.UserRole, fo)
            if abs(fo - off) < 30:
                it.setForeground(theme.c("ok"))
                it.setText(self.tr("{signal}   ◀ decoding").format(signal=it.text()))
            self.sig.addItem(it)
        if not found:
            it = QListWidgetItem(self.tr("No carriers heard"))
            it.setForeground(theme.c("text3"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.sig.addItem(it)

    def _pick_signal(self, it: QListWidgetItem):
        fo = it.data(Qt.ItemDataRole.UserRole)
        if fo is None:
            return
        off = mode_offset(self.st("mode"))
        vfo = float(self.st("vfo"))
        self.bridge.set(vfo=round(vfo + fo - off))
