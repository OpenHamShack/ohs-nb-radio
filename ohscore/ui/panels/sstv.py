"""SSTV receive: the picture paints line by line as it arrives; finished
pictures join a gallery read from the data directory.

Received by shack_sdr's sstv decoder since Radio's SDR milestone 2, in its
fourteen modes (SSTV_NAMES); sent by sstv.py's encoder in its four, as
before."""
from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QWidget

from .. import theme
from ..controls import Button, Card, Segmented
from .common import ModePanel


# shack_sdr's SSTV mode ids, as the operator knows them, in the decoder's
# own order (shack_sdr sstv.modes()).
SSTV_NAMES = {"martin1": "Martin M1", "martin2": "Martin M2", "scottie1": "Scottie S1", "scottie2": "Scottie S2",
              "scottiedx": "Scottie DX", "robot36": "Robot 36", "robot72": "Robot 72", "pd50": "PD50",
              "pd90": "PD90", "pd120": "PD120", "pd160": "PD160", "pd180": "PD180", "pd240": "PD240",
              "pd290": "PD290"}


def sstv_name(mode_id: str) -> str:
    """An SSTV mode's name ("Martin M1") from either decoder's id."""
    return SSTV_NAMES.get(mode_id) or {"martinm1": "Martin M1", "scottie_s1": "Scottie S1"}.get(mode_id) \
        or str(mode_id or "").upper()


class Picture(QWidget):
    """A picture painting in as it arrives. `waiting` is what it says
    before the first one: the owner's words, since HSmodem shows its
    pictures here too and said "Tune to an SSTV signal" until 17/10/2026
    (Mac test, finding 24)."""

    def __init__(self, parent=None, waiting: str | None = None):
        super().__init__(parent)
        self.waiting = waiting if waiting is not None else self.tr("Waiting for a picture…\nTune to an SSTV signal")
        self.img: QImage | None = None
        self.buf: np.ndarray | None = None
        self.line = 0
        self.of = 0
        self.setMinimumSize(220, 160)

    def start(self, w: int, h: int):
        self.buf = np.zeros((h, w), np.uint32)
        self.buf[:] = 0xFF0A0D12
        self.img = QImage(self.buf.data, w, h, w * 4, QImage.Format.Format_RGB32)
        self.line, self.of = 0, h
        self.update()

    def put_row(self, line: int, rgb: bytes):
        if self.buf is None:
            return
        h, w = self.buf.shape
        a = np.frombuffer(rgb, np.uint8)
        if len(a) < w * 3 or not 0 < line <= h:
            return
        a = a[:w * 3].reshape(w, 3).astype(np.uint32)
        self.buf[line - 1] = 0xFF000000 | (a[:, 0] << 16) | (a[:, 1] << 8) | a[:, 2]
        self.line = line
        self.update()

    def show_file(self, path: str):
        img = QImage(path)
        if not img.isNull():
            self.buf = None
            self.img = img
            self.line = self.of = img.height()
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("scope"))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self.img is None:
            p.setPen(theme.c("text3"))
            p.setFont(theme.font(13))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.waiting)
            return
        iw, ih = self.img.width(), self.img.height()
        k = min((r.width() - 16) / iw, (r.height() - 16) / ih)
        tw, th = iw * k, ih * k
        tr = QRectF(r.center().x() - tw / 2, r.center().y() - th / 2, tw, th)
        p.drawImage(tr, self.img)
        if self.buf is not None and self.of and self.line < self.of:
            y = tr.y() + th * self.line / self.of
            p.setPen(QPen(theme.c("accent"), 1.5))
            p.drawLine(QPointF(tr.x(), y), QPointF(tr.right(), y))


class SstvPanel(ModePanel):
    modes = ("sstv",)

    def __init__(self, bridge, prefs, parent=None, big=False):
        super().__init__(bridge, prefs, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        live = Card(self.tr("Receiving"))
        self.pic = Picture()
        live.lay.addWidget(self.pic, 1)
        self.info = QLabel(self.tr("Idle"))
        self.info.setObjectName("Faint")
        self.info.setFont(theme.font(12, mono=True))
        live.set_header_widget(self.info)
        lay.addWidget(live, 3)
        gal = Card(self.tr("Gallery"))
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(132, 100))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setSpacing(6)
        self.list.setMovement(QListView.Movement.Static)
        self.list.itemClicked.connect(lambda it: self.pic.show_file(it.data(Qt.ItemDataRole.UserRole)))
        self.list.itemDoubleClicked.connect(
            lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.ItemDataRole.UserRole))))
        gal.lay.addWidget(self.list, 1)
        op = Button(self.tr("Open folder"), icon="folder", small=True)
        op.clicked.connect(self.open_folder)
        gal.set_header_widget(op)
        # Sending: the modes' encoder exists, so a picture can go out too.
        self.tx_mode = Segmented([("robot36", "Robot 36"), ("martinm1", "Martin 1"), ("scottie_s1", "Scottie 1"),
                                  ("pd120", "PD 120")], "robot36", compact=True)
        self.tx_mode.setToolTip(self.tr("Picture mode for sending"))
        send = Button(self.tr("Send a picture…"), icon="image", small=True)
        send.clicked.connect(self.send_picture)
        gal.lay.addWidget(self.tx_mode)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(send)
        gal.lay.addLayout(row)
        self.send_btn = send
        lay.addWidget(gal, 2)
        self.load_gallery()

    def folder(self) -> Path:
        try:
            return Path(self.bridge.radio.sstv_dir())
        except Exception:  # noqa: BLE001
            return Path(".")

    def open_folder(self):
        d = self.folder()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def load_gallery(self):
        self.list.clear()
        d = self.folder()
        files = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:60] if d.is_dir() else []
        for f in files:
            self._add_thumb(str(f), first=False)
        if not files:
            it = QListWidgetItem("Received pictures appear here")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setForeground(theme.c("text3"))
            self.list.addItem(it)

    def _add_thumb(self, path: str, first=True):
        pm = QPixmap(path)
        if pm.isNull():
            return
        if self.list.count() == 1 and self.list.item(0).data(Qt.ItemDataRole.UserRole) is None:
            self.list.clear()
        it = QListWidgetItem(QIcon(pm.scaled(132, 100, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)), Path(path).stem[-12:])
        it.setData(Qt.ItemDataRole.UserRole, path)
        it.setToolTip(path)
        if first:
            self.list.insertItem(0, it)
        else:
            self.list.addItem(it)

    def set_mirror(self):
        super().set_mirror()
        self.tx_mode.hide()
        self.send_btn.hide()

    def send_picture(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Send a picture"), str(Path.home()),
                                              self.tr("Pictures (*.png *.jpg *.jpeg *.bmp *.gif)"))
        if not path:
            return
        img = QImage(path).convertToFormat(QImage.Format.Format_RGB888)
        if img.isNull():
            self.bridge.say(self.tr("That file is not a picture Qt can read"))
            return
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr, np.uint8).reshape(h, bpl)[:, :w * 3].reshape(h, w, 3).copy()
        if self.bridge.send("sstv", image=arr, sstvMode=self.tx_mode.value):
            self.info.setText(self.tr("sending {name}").format(name=Path(path).name))

    def on_event(self, ev):
        if ev.get("mode") != "sstv":
            return
        st = ev.get("state")
        if st == "start":
            self.pic.start(int(ev.get("width", 320)), int(ev.get("height", 256)))
            if ev.get("partial"):
                # Started from its line syncs: tuned in part way through.
                self.info.setText(self.tr("{mode}  joined part way").format(mode=sstv_name(ev.get("fmt", ""))))
            else:
                self.info.setText(self.tr("{mode}  starting").format(mode=sstv_name(ev.get("fmt", ""))))
        elif st == "line":
            try:
                self.pic.put_row(int(ev.get("line", 0)), base64.b64decode(ev.get("row", "")))
            except (ValueError, TypeError):
                return
            self.info.setText(self.tr("line {line}/{of}").format(line=ev.get('line'), of=ev.get('of')))
        elif st == "done":
            self.info.setText(self.tr("done — saved"))
            if ev.get("path"):
                self._add_thumb(ev["path"])
        elif st == "unsupported":
            self.info.setText(self.tr("{mode}: a mode that cannot be shown yet").format(mode=sstv_name(ev.get("fmt"))))
        elif st == "bad_vis":
            self.info.setText(self.tr("a picture's header was too weak to read"))
