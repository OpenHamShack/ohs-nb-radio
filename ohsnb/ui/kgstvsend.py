"""Sending a KG-STV picture: the Beacon view's KG-STV page's "Send
picture…" dialog, and the strip on that page that follows the over.

The dialog only prepares. Choose a file; it is cut to 4:3 and scaled to
320x240 as KG-STV does, and shown as a receiver will paint it at the
chosen quality (ohscore/modes/kgstv.py Transmission.preview), with each
quality's over length beside it, as KG-STV shows "TxTime" beside its own
quality list. The callsign line is the station's call and locator, from
Settings › Station; it is shown, not edited here. Where it goes: KG-STV's
own frequency (10489.6249 MHz USB, where every picture on QO-100 is
heard; choosing it retunes the transmitter there, as a click on a spot
does), or wherever the transmitter is tuned now.

Nothing transmits until Send is pressed, and then only through the
engine's send() (Engine.OVER_MODES: the over is judged as KG-STV by the
band plan, the licence, the beacons and the level checks, refused before
key-up if it is longer than the transmit time-out, and keyed through the
Pluto or, with CAT PTT on, the IC-9700 - ohsnb/radio.py). The dialog then
closes, so that Escape and Halt in the main window reach the over: a
modal dialog left open would have kept Escape for itself.

Why no longer time-out for KG-STV: at NB's default 300 s every picture
measured fits at the standard quality (93-172 s for real pictures, 264 s
for noise, the slowest content there is), so a special limit would only
matter to an operator who set a shorter one - and that is the limit they
chose. Instead each quality longer than the time-out is shown and
unavailable, and the dialog starts on the finest that fits.

The strip (SendingStrip) shows the picture going out: "block 120 of 300",
from the over's seconds on the air (the engine's txSeconds) and where
each block ends in it, with a Halt button; afterwards, how it ended.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPen
from PyQt6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel, QRadioButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from ohscore.dsp import kgstv as codec
from ohscore.modes import kgstv
from ohscore.ui import theme
from ohscore.ui.controls import Button

from ..kgstvrx import DIAL

PICTURES = "*.png *.jpg *.jpeg *.bmp *.gif *.webp"


def mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def image_array(path: str) -> np.ndarray | None:
    """A picture file as H x W x 3 uint8 RGB, or None if Qt cannot read it."""
    img = QImage(path)
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).copy()


class Preview(QWidget):
    """A 320x240 RGB picture, scaled to fit, or a line saying what to do."""

    def __init__(self, empty: str, parent=None):
        super().__init__(parent)
        self.empty = empty
        self.rgb: np.ndarray | None = None
        self.img: QImage | None = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set(self, rgb: np.ndarray | None) -> None:
        if rgb is None:
            self.rgb = self.img = None
        else:
            self.rgb = np.ascontiguousarray(rgb, np.uint8)
            h, w = self.rgb.shape[:2]
            self.img = QImage(self.rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("scope"))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self.img is None:
            p.setPen(theme.c("text3"))
            p.setFont(theme.font(13))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.empty)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        k = min((r.width() - 16) / self.img.width(), (r.height() - 16) / self.img.height())
        tw, th = self.img.width() * k, self.img.height() * k
        p.drawImage(QRectF(r.center().x() - tw / 2, r.center().y() - th / 2, tw, th), self.img)


class SendPictureDialog(QDialog):
    """Choose, see and send one picture (module docstring). `sent` holds
    the Transmission once the engine has taken it."""

    def __init__(self, bridge, parent=None, path: str | None = None):
        super().__init__(parent)
        self.bridge = bridge
        self.radio = bridge.radio
        self.picture: np.ndarray | None = None
        self.name = ""
        self.txs: dict[int, kgstv.Transmission] = {}
        self.sent: kgstv.Transmission | None = None
        self.refusal = ""
        self.setWindowTitle(self.tr("Send a KG-STV picture"))
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(theme.S2)

        row = QHBoxLayout()
        row.setSpacing(theme.S4)
        left = QVBoxLayout()
        self.preview = Preview(self.tr("Choose a picture: it is cut to 4:3 and scaled to 320x240, as KG-STV "
                                       "does, and shown here as a receiver will see it"))
        left.addWidget(self.preview, 1)
        pick = QHBoxLayout()
        self.choose_btn = Button(self.tr("Choose picture…"), icon="image", small=True)
        self.choose_btn.clicked.connect(self.choose)
        pick.addWidget(self.choose_btn)
        self.file_label = QLabel("")
        self.file_label.setObjectName("Muted")
        pick.addWidget(self.file_label, 1)
        left.addLayout(pick)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(theme.S1)
        right.addWidget(self._heading(self.tr("Quality")))
        self.quality = QButtonGroup(self)
        self.quality_btns: dict[int, QRadioButton] = {}
        for q in kgstv.QUALITIES:
            b = QRadioButton()
            self.quality.addButton(b, q)
            self.quality_btns[q] = b
            right.addWidget(b)
        self.quality.idToggled.connect(lambda _q, on: on and self._show_preview())
        self.limit_label = QLabel("")
        self.limit_label.setObjectName("Faint")
        self.limit_label.setWordWrap(True)
        right.addWidget(self.limit_label)
        right.addSpacing(theme.S3)
        right.addWidget(self._heading(self.tr("Frequency")))
        self.freq = QButtonGroup(self)
        self.freq_std = QRadioButton(self.tr("KG-STV's frequency, {mhz} MHz USB").format(mhz=f"{DIAL / 1e6:.4f}"))
        self.freq_std.setToolTip(self.tr("Where KG-STV pictures are sent and heard on QO-100. Sending retunes the "
                                         "transmitter there first."))
        self.freq_here = QRadioButton("")
        self.freq.addButton(self.freq_std, 0)
        self.freq.addButton(self.freq_here, 1)
        self.freq_std.setChecked(True)
        self.freq.idToggled.connect(lambda _i, on: on and self._enable())
        right.addWidget(self.freq_std)
        right.addWidget(self.freq_here)
        right.addSpacing(theme.S3)
        right.addWidget(self._heading(self.tr("Callsign line")))
        self.call_label = QLabel("")
        self.call_label.setFont(theme.font(13, mono=True))
        self.call_label.setWordWrap(True)
        right.addWidget(self.call_label)
        right.addStretch(1)
        row.addLayout(right, 2)
        lay.addLayout(row, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = Button(self.tr("Cancel"), small=True)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.send_btn = Button(self.tr("Send"), icon="send", kind="danger", small=True)
        self.send_btn.setToolTip(self.tr("Transmits the picture now. Escape or Halt in the main window stops it"))
        self.send_btn.clicked.connect(self.send)
        buttons.addWidget(self.send_btn)
        lay.addLayout(buttons)

        self._station()
        self._qualities()
        if path:
            self.load(path)
        self._enable()

    def _heading(self, text: str) -> QLabel:
        h = QLabel(text)
        h.setFont(theme.font(12, theme.QFont.Weight.DemiBold))
        return h

    # -- what goes out ----------------------------------------------------------
    def line(self) -> str:
        """The callsign line, '' (with the reason in self.refusal) if none."""
        st = self.bridge.st
        try:
            return kgstv.header(str(st.get("callsign") or ""), str(st.get("locator") or ""))
        except ValueError as e:
            self.refusal = str(e)
            return ""

    def limit(self) -> float:
        return float(self.bridge.st.get("txTimeoutSec") or 300.0)

    def _station(self) -> None:
        line = self.line()
        if line:
            self.call_label.setText(line)
            self.call_label.setToolTip(self.tr("Your callsign and locator, from Settings › Station"))
        else:
            self.call_label.setText(self.tr("No callsign set: Settings › Station"))
        st = self.bridge.st
        tx_dial = (st.get("txVfo") if st.get("split") else st.get("vfo")) or 0.0
        tx_dial = float(tx_dial) + (float(st.get("xit") or 0.0) if st.get("xitOn") else 0.0)
        self.freq_here.setText(self.tr("Where the transmitter is tuned now, {mhz} MHz").format(
            mhz=f"{tx_dial / 1e6:.4f}"))

    def load(self, path: str) -> bool:
        rgb = image_array(path)
        if rgb is None:
            self.status.setText(self.tr("That file is not a picture this program can read"))
            return False
        self.picture = kgstv.fit_picture(rgb)
        self.name = Path(path).name
        self.file_label.setText(self.name)
        self.txs = {q: kgstv.Transmission(self.picture, self.line() or "?", q) for q in kgstv.QUALITIES}
        self._qualities()
        want = kgstv.fitting_scale(self.picture, self.line() or "?", self.limit())
        if want is not None:
            self.quality_btns[want].setChecked(True)
        self._show_preview()
        self._enable()
        return True

    def choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Choose a picture to send"), str(Path.home()),
                                              self.tr("Pictures ({patterns})").format(patterns=PICTURES))
        if path:
            self.load(path)

    def _qualities(self) -> None:
        limit = self.limit()
        names = {8: self.tr("Finer"), 10: self.tr("Standard"), 12: self.tr("Faster"), 15: self.tr("Fastest")}
        for q, b in self.quality_btns.items():
            name = names.get(q, str(q))
            tx = self.txs.get(q)
            if tx is None:
                b.setText(self.tr("{name} (x{scale:g})").format(name=name, scale=codec.SCALES[q]))
                b.setEnabled(self.picture is None)
                continue
            b.setText(self.tr("{name} (x{scale:g}) · {length}").format(name=name, scale=codec.SCALES[q],
                                                                       length=mmss(tx.seconds)))
            fits = tx.seconds <= limit
            b.setEnabled(fits)
            b.setToolTip("" if fits else self.tr("Longer than the transmit time-out ({limit}, Settings › Transmit "
                                                 "& safety)").format(limit=mmss(limit)))
        if self.quality.checkedId() == -1:
            self.quality_btns[kgstv.STANDARD].setChecked(True)
        self.limit_label.setText(self.tr("Transmit time-out {limit} (Settings › Transmit & safety)").format(
            limit=mmss(limit)))

    def scale(self) -> int:
        q = self.quality.checkedId()
        return q if q in self.quality_btns else kgstv.STANDARD

    def _show_preview(self) -> None:
        tx = self.txs.get(self.scale())
        self.preview.set(tx.preview() if tx is not None else None)
        self._enable()

    def _enable(self) -> None:
        why = ""
        tx = self.txs.get(self.scale())
        if not self.line():
            why = self.refusal
        elif self.picture is None:
            why = self.tr("Choose a picture to send")
        elif tx is None or tx.seconds > self.limit():
            why = self.tr("No quality fits the transmit time-out ({limit}): raise it in Settings › Transmit & "
                          "safety, or choose a simpler picture").format(limit=mmss(self.limit()))
        elif self.bridge.st.get("keyed"):
            why = self.tr("Already transmitting")
        self.send_btn.setEnabled(not why)
        if why:
            self.status.setText(why)
            self.status.setStyleSheet(f"color: {theme.t()['warn']};")
        elif self.freq.checkedId() == 0 and self.bridge.st.get("kgstvState") == "receiving":
            # KG-STV's readme: check the frequency is not in use before
            # sending. NB is hearing a picture there now; said, not refused -
            # the operator may be answering it, or it may be their own echo.
            call = str(self.bridge.st.get("kgstvCall") or "") or self.tr("a station")
            self.status.setText(self.tr("A KG-STV picture from {call} is coming in on that frequency now: sending "
                                        "would go over it").format(call=call))
            self.status.setStyleSheet(f"color: {theme.t()['warn']};")
        elif tx is not None:
            self.status.setText(self.tr("{blocks} blocks in {length} on the air").format(
                blocks=tx.blocks, length=mmss(tx.seconds)))
            self.status.setStyleSheet(f"color: {theme.t()['text2']};")

    # -- sending ------------------------------------------------------------------
    def tune(self) -> None:
        """Put the transmitter on KG-STV's dial: the TX VFO when split,
        else the VFO (taking off any XIT, so the over lands there)."""
        st = self.bridge.st
        dial = DIAL - (float(st.get("xit") or 0.0) if st.get("xitOn") else 0.0)
        self.bridge.set(**({"txVfo": dial} if st.get("split") else {"vfo": dial}))

    def send(self) -> None:
        tx = self.txs.get(self.scale())
        if tx is None or self.picture is None or not self.send_btn.isEnabled():
            return
        if self.freq.checkedId() == 0:
            self.tune()
        said: list[str] = []

        def heard(ev):
            said.append(str(ev.get("text", "")))
        self.bridge.toast.connect(heard)
        try:
            ok = self.bridge.send("kgstv", picture=self.picture, scale=tx.scale)
        finally:
            self.bridge.toast.disconnect(heard)
        if ok:
            self.sent = tx
            self.accept()
            return
        # Refused before key-up: say why here, where the operator is
        # looking; the main window's toast has said it too.
        self.status.setText(said[-1] if said else self.tr("Not sent"))
        self.status.setStyleSheet(f"color: {theme.t()['err']};")


class SendingStrip(QWidget):
    """The over in progress on the KG-STV page (module docstring). `store`
    keeps what is being sent (MmbStore.kg_sending), so a theme change that
    rebuilds the view keeps the progress."""

    def __init__(self, bridge, store, parent=None):
        super().__init__(parent)
        self.bridge, self.store = bridge, store
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        self.thumb = Preview("")
        self.thumb.setMinimumSize(64, 48)
        self.thumb.setFixedSize(80, 60)
        lay.addWidget(self.thumb)
        self.text = QLabel("")
        self.text.setFont(theme.font(12, mono=True))
        lay.addWidget(self.text, 1)
        self.halt_btn = Button(self.tr("Halt"), icon="close", kind="danger", small=True)
        self.halt_btn.setToolTip(self.tr("Stop sending now (Escape does the same)"))
        self.halt_btn.clicked.connect(bridge.halt)
        lay.addWidget(self.halt_btn)
        self.refresh()

    def start(self, tx: kgstv.Transmission) -> None:
        self.store.kg_sending = {"tx": tx, "keyed": False, "on_air": False, "secs": 0.0, "done": False}
        self.thumb.set(tx.picture)
        self.refresh()

    def refresh(self) -> None:
        s = self.store.kg_sending
        if s is None:
            self.hide()
            return
        st = self.bridge.st
        tx = s["tx"]
        mine = str(st.get("txSource") or "") == "send:kgstv"
        if self.thumb.rgb is None:
            self.thumb.set(tx.picture)
        if not s["done"]:
            # The engine had keyed when the dialog handed the over here, but
            # the window's copy of the state can be a frame behind: it ends
            # only once this strip has seen it keyed and then not.
            if st.get("keyed") and mine:
                s["keyed"] = True
                if st.get("txOnAir"):
                    s["on_air"] = True
                    s["secs"] = max(s["secs"], float(st.get("txSeconds") or 0.0))
            elif not st.get("keyed") and s["keyed"]:
                s["done"] = True
        n = tx.blocks_sent(s["secs"])
        if s["done"]:
            if n >= tx.blocks or s["secs"] >= tx.seconds - 0.5:
                text = self.tr("Sent {line}: all {total} blocks in {length}").format(
                    line=tx.line, total=tx.blocks, length=mmss(tx.seconds))
            elif s["on_air"]:
                text = self.tr("Stopped after block {n} of {total}").format(n=n, total=tx.blocks)
            else:
                text = self.tr("Not sent")
            colour = "text2"
        elif not s["on_air"]:
            text = self.tr("Keying…")
            colour = "warn"
        else:
            text = self.tr("Sending {line} · block {n} of {total} · {at} of {length}").format(
                line=tx.line, n=n, total=tx.blocks, at=mmss(s["secs"]), length=mmss(tx.seconds))
            colour = "err"
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {theme.t()[colour]};")
        self.halt_btn.setVisible(not s["done"])
        self.show()


__all__ = ["SendPictureDialog", "SendingStrip", "image_array", "mmss"]
