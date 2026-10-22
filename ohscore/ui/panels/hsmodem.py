"""HSmodem station to station: what other stations send, and a file, a
picture or a message of our own to send (ohscore/modes/hsmodem.py).

Receive (left): how the receiver is doing (in sync or searching, MER, how
far off tune, frames), the file arriving block by block, and what has
arrived - pictures and text shown, everything saved in the data folder
under a safe name. Send (right): the speed (both stations must agree, so
it is the receiver's too), then a file, a picture or typed text; its size
and how long it takes at that speed; for a picture, the size and quality
reductions HSmodem's own GUI offers, so a camera's 4 MB photo becomes the
20 kB JPEG a QO-100 link carries in a minute. Send goes through the
engine's send() like every digital mode, so every transmit guard applies;
Stop is the engine's halt().
"""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from ohscore.modes import hsmodem as hs

from .. import theme
from ..controls import Button, Card
from .common import ModePanel
from .sstv import Picture

# HSmodem's picture choices (oscardata Form1.cs prepareImage / getResolution):
# a resolution, and a "quality" that is really a size budget - the JPEG is
# saved at quality 100, 95, 90 ... until it fits - divided by how many
# times smaller than 640 pixels the picture is.
RESOLUTIONS = [("640x480", "640×480"), ("480x360", "480×360"), ("320x240", "320×240"), ("160x120", "160×120"),
               ("", "As it is")]
QUALITIES = [("low", "Low (about 30 s at 4410)", 12_000), ("medium", "Medium (1 min)", 22_500),
             ("high", "High (2 min)", 45_000), ("veryhigh", "Very high (4 min)", 90_000)]
MAX_FILE = 1_000_000        # HSmodem's GUI will not loop a file over 1 MB; NB says why before rendering


def jpeg_for_hsmodem(img: QImage, resolution: str, budget: int) -> tuple[bytes, int, QSize]:
    """HSmodem's prepareImage(): scale to `resolution` ("640x480"; "" keeps
    the size), then save as JPEG at falling quality until it is no bigger
    than `budget` bytes / (640 / width) - its SaveJpgAtFileSize, steps of
    5 down to 5. Returns (bytes, quality used, size). The aspect ratio is
    kept inside the box (HSmodem's GUI stretches to it)."""
    if resolution:
        w, h = (int(v) for v in resolution.split("x"))
        img = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        budget = budget // max(1, 640 // max(1, w))
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    data = b""
    for q in range(100, 4, -5):
        buf = QByteArray()
        dev = QBuffer(buf)
        dev.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(dev, "JPG", q)
        dev.close()
        data = bytes(buf)
        if len(data) <= budget:
            return data, q, img.size()
    return data, 5, img.size()


def fmt_bytes(n: int) -> str:
    return f"{n} B" if n < 1000 else f"{n / 1000:.1f} kB" if n < 1_000_000 else f"{n / 1e6:.2f} MB"


def fmt_secs(s: float) -> str:
    return f"{s:.0f} s" if s < 90 else f"{s / 60:.1f} min"


def speed_label(bps: int) -> str:
    i = hs.speed_info(bps)
    std = " — HSmodem's standard" if bps == hs.DEFAULT_SPEED else ""
    return f"{bps} bit/s  {i['scheme']}  {i['baud']:g} Bd{std}"


class HsmodemPanel(ModePanel):
    modes = ("hsmodem",)

    def __init__(self, bridge, prefs, parent=None, big=False):
        super().__init__(bridge, prefs, parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)

        # ---- receive ------------------------------------------------------
        rx = Card(self.tr("Received"))
        self.status = QLabel(self.tr("Waiting for a station"))
        self.status.setObjectName("Faint")
        self.status.setFont(theme.font(12, mono=True))
        rx.set_header_widget(self.status)
        body = QHBoxLayout()
        body.setSpacing(theme.S2)
        self.view = QStackedWidget()
        self.pic = Picture(waiting=self.tr("Waiting for a picture or a file…\n"
                                           "from an HSmodem station at the same speed"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(theme.font(13, mono=True))
        self.text.setPlaceholderText(self.tr("Text a station sends appears here"))
        self.view.addWidget(self.pic)
        self.view.addWidget(self.text)
        body.addWidget(self.view, 3)
        side = QVBoxLayout()
        side.setSpacing(theme.S2)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 36))
        self.list.setViewMode(QListView.ViewMode.ListMode)
        self.list.itemClicked.connect(self._show_item)
        self.list.itemDoubleClicked.connect(
            lambda it: it.data(Qt.ItemDataRole.UserRole) and
            QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.ItemDataRole.UserRole)["path"])))
        side.addWidget(self.list, 1)
        self.incoming = QLabel("")
        self.incoming.setObjectName("Faint")
        self.incoming.setFont(theme.font(11.5, mono=True))
        self.rx_bar = self._bar()
        side.addWidget(self.incoming)
        side.addWidget(self.rx_bar)
        row = QHBoxLayout()
        row.addStretch(1)
        op = Button(self.tr("Open folder"), icon="folder", small=True)
        op.clicked.connect(self.open_folder)
        row.addWidget(op)
        side.addLayout(row)
        body.addLayout(side, 2)
        rx.lay.addLayout(body, 1)
        lay.addWidget(rx, 3)

        # ---- send ---------------------------------------------------------
        tx = Card(self.tr("Send"))
        self.tx_card = tx
        g = QGridLayout()
        g.setHorizontalSpacing(theme.S2)
        g.setVerticalSpacing(6)
        cap = QLabel(self.tr("Speed"))
        cap.setObjectName("Muted")
        self.speed = QComboBox()
        choices = bridge.radio.STATE.spec.get("hsSpeed", {}).get("choices") or sorted(hs.SPEEDS)
        for b in choices:
            self.speed.addItem(speed_label(int(b)), int(b))
        self.speed.setToolTip(self.tr("Both stations must use the same speed: HSmodem does not detect it. The "
                                      "receiver listens at this speed too."))
        self.speed.setCurrentIndex(max(0, self.speed.findData(int(self.st("hsSpeed", hs.DEFAULT_SPEED)))))
        self.speed.activated.connect(lambda _i: self.bridge.set(hsSpeed=int(self.speed.currentData())))
        g.addWidget(cap, 0, 0)
        g.addWidget(self.speed, 0, 1, 1, 3)
        self.pick_file = Button(self.tr("File…"), icon="folder", small=True)
        self.pick_file.clicked.connect(self.choose_file)
        self.pick_pic = Button(self.tr("Picture…"), icon="image", small=True)
        self.pick_pic.clicked.connect(self.choose_picture)
        g.addWidget(self.pick_file, 1, 1)
        g.addWidget(self.pick_pic, 1, 2)
        self.res_cap = QLabel(self.tr("Picture"))
        self.res_cap.setObjectName("Muted")
        self.res = QComboBox()
        for k, t in RESOLUTIONS:
            self.res.addItem(t, k)
        self.qual = QComboBox()
        for k, t, _n in QUALITIES:
            self.qual.addItem(t, k)
        self.qual.setCurrentIndex(1)
        self.res.setToolTip(self.tr("HSmodem's picture sizes; the aspect ratio is kept"))
        self.qual.setToolTip(self.tr("HSmodem's quality choices: a size budget, the JPEG quality lowered until it "
                                     "fits"))
        self.res.activated.connect(lambda _i: self._reprepare())
        self.qual.activated.connect(lambda _i: self._reprepare())
        g.addWidget(self.res_cap, 2, 0)
        g.addWidget(self.res, 2, 1)
        g.addWidget(self.qual, 2, 2, 1, 2)
        tx.lay.addLayout(g)
        self.msg = QPlainTextEdit()
        self.msg.setPlaceholderText(self.tr("…or type a message: it goes as a text file, as HSmodem sends one"))
        self.msg.setFont(theme.font(13, mono=True))
        self.msg.setMaximumHeight(70)
        self.msg.textChanged.connect(self._typed)
        tx.lay.addWidget(self.msg)
        self.what = QLabel(self.tr("Nothing chosen"))
        self.what.setWordWrap(True)
        self.what.setObjectName("Muted")
        tx.lay.addWidget(self.what)
        self.tx_bar = self._bar()
        tx.lay.addWidget(self.tx_bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.send_btn = Button(self.tr("Send"), icon="send", kind="primary")
        self.send_btn.clicked.connect(self.send)
        self.stop_btn = Button(self.tr("Stop"), icon="close", kind="ghost")
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        row.addWidget(self.send_btn)
        tx.lay.addLayout(row)
        tx.lay.addStretch(1)
        lay.addWidget(tx, 2)

        self.sender = ""                     # the last station frame heard: call and locator
        self.chosen: dict | None = None      # {"name", "data", "path"?, "image": QImage?}
        self.sending: dict | None = None     # the plan of what is on air
        self.items: dict[str, QListWidgetItem] = {}
        self._set_picture_controls(False)
        self._refresh_what()
        self.load_folder()

    # ------------------------------------------------------------ helpers
    def _bar(self) -> QProgressBar:
        b = QProgressBar()
        b.setRange(0, 1000)
        b.setTextVisible(False)
        b.setFixedHeight(8)
        tt = theme.t()
        b.setStyleSheet(f"QProgressBar {{ background: {tt['bg2']}; border: 1px solid {tt['line']}; "
                        f"border-radius: 4px; }} QProgressBar::chunk {{ background: {tt['accent']}; "
                        f"border-radius: 3px; }}")
        b.setValue(0)
        return b

    def folder(self) -> Path:
        try:
            return Path(self.bridge.radio.hsmodem_dir())
        except Exception:  # noqa: BLE001
            return Path(".")

    def open_folder(self):
        d = self.folder()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def speed_now(self) -> int:
        return int(self.st("hsSpeed", hs.DEFAULT_SPEED) or hs.DEFAULT_SPEED)

    def set_mirror(self):
        super().set_mirror()
        self.tx_card.hide()

    # ------------------------------------------------------------ receive
    def load_folder(self):
        d = self.folder()
        if not d.is_dir():
            return
        for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime)[-60:]:
            if f.is_file():
                self._add_item(f.name, str(f), "", f.stat().st_mtime, first=True)

    def _add_item(self, name: str, path: str, sender: str, t: float, first: bool = True) -> QListWidgetItem:
        it = self.items.get(path)
        if it is None:
            it = QListWidgetItem()
            self.items[path] = it
            if first:
                self.list.insertItem(0, it)
            else:
                self.list.addItem(it)
        is_pic = path.lower().endswith((".jpg", ".jpeg", ".png"))
        pm = QPixmap(path) if is_pic else QPixmap()
        if not pm.isNull():
            it.setIcon(QIcon(pm.scaled(48, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)))
        size = Path(path).stat().st_size if Path(path).exists() else 0
        when = time.strftime("%H:%M", time.localtime(t))
        if sender:
            it.setText(self.tr("{name}\n{size}  {when}  from {sender}").format(
                name=name, size=fmt_bytes(size), when=when, sender=sender))
        else:
            it.setText(f"{name}\n{fmt_bytes(size)}  {when}")
        it.setToolTip(path)
        it.setData(Qt.ItemDataRole.UserRole, {"path": path, "pic": is_pic})
        return it

    def _show_item(self, it: QListWidgetItem):
        d = it.data(Qt.ItemDataRole.UserRole)
        if not d:
            return
        if d["pic"]:
            self.pic.show_file(d["path"])
            self.view.setCurrentWidget(self.pic)
            return
        try:
            raw = Path(d["path"]).read_bytes()[:200_000]
        except OSError:
            return
        if b"\0" in raw[:4096]:
            self.text.setPlainText(self.tr("{name}: a binary file ({size}). Double-click it in the list to open "
                                           "it.").format(name=Path(d['path']).name, size=fmt_bytes(len(raw))))
        else:
            self.text.setPlainText(raw.decode("utf-8", "replace"))
        self.view.setCurrentWidget(self.text)

    def on_event(self, ev: dict):
        if ev.get("mode") != "hsmodem":
            return
        k = ev.get("kind")
        if k == "stats":
            if ev.get("sync"):
                self.status.setText(self.tr("{speed} bit/s  in sync  MER {mer} dB  {offset} Hz  %n frame(s)", "",
                                            int(ev.get('ok', 0))).format(
                    speed=ev.get('speed'), mer=f"{ev.get('mer', 0):.1f}", offset=f"{ev.get('freq', 0):+.0f}"))
            else:
                self.status.setText(self.tr("{speed} bit/s  searching…").format(speed=ev.get('speed')))
        elif k == "station":
            self.sender = " ".join(x for x in (ev.get("call"), ev.get("loc")) if x)
        elif k == "file_start":
            self.incoming.setText(f"{ev.get('name')}  {fmt_bytes(int(ev.get('size') or 0))}")
            self.rx_bar.setValue(0)
        elif k == "file_progress":
            have, n = int(ev.get("have") or 0), max(1, int(ev.get("blocks") or 1))
            # Whole lines with and without the sender, not a clause appended.
            if self.sender:
                self.incoming.setText(self.tr("{name}  {have}/{n} blocks  from {sender}").format(
                    name=ev.get('name'), have=have, n=n, sender=self.sender))
            else:
                self.incoming.setText(self.tr("{name}  {have}/{n} blocks").format(name=ev.get('name'), have=have, n=n))
            self.rx_bar.setValue(int(1000 * have / n))
        elif k == "file_bad":
            self.incoming.setText(self.tr("{name}: arrived damaged; waiting for it again").format(name=ev.get('name')))
        elif k in ("image", "bulletin", "file"):
            self.rx_bar.setValue(1000)
            sender = self.sender
            if sender:
                self.incoming.setText(self.tr("{name}  received  from {sender}").format(name=ev.get('name'),
                                                                                      sender=sender))
            else:
                self.incoming.setText(self.tr("{name}  received").format(name=ev.get('name')))
            if ev.get("path"):
                it = self._add_item(ev["name"], ev["path"], sender, float(ev.get("t") or time.time()))
                self.list.setCurrentItem(it)
                self._show_item(it)
            elif k == "bulletin":
                self.text.setPlainText(ev.get("text", ""))
                self.view.setCurrentWidget(self.text)

    # ------------------------------------------------------------ send
    def choose_file(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Send a file with HSmodem"), str(Path.home()),
                                              self.tr("All files (*)"))
        if path:
            self.set_file(path)

    def choose_picture(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Send a picture with HSmodem"), str(Path.home()),
                                              self.tr("Pictures (*.jpg *.jpeg *.png *.bmp *.gif)"))
        if path:
            self.set_picture(path)

    def set_file(self, path: str) -> bool:
        p = Path(path)
        try:
            size = p.stat().st_size
            if size > MAX_FILE:
                self.bridge.say(self.tr("{name} is {size}: too big for HSmodem (1 MB at most, and at 4410 bit/s "
                                        "that would take over half an hour)").format(name=p.name, size=fmt_bytes(size)))
                return False
            data = p.read_bytes()
        except OSError as e:
            self.bridge.say(self.tr("Cannot read {name}: {error}").format(name=p.name, error=e))
            return False
        self.chosen = {"name": p.name, "data": data, "path": str(p)}
        self._set_picture_controls(False)
        self.msg.blockSignals(True)
        self.msg.clear()
        self.msg.blockSignals(False)
        self._refresh_what()
        return True

    def set_picture(self, path: str) -> bool:
        img = QImage(path)
        if img.isNull():
            self.bridge.say(self.tr("That file is not a picture Qt can read"))
            return False
        self.chosen = {"name": Path(path).stem + ".jpg", "image": img, "path": path, "orig": Path(path).stat().st_size}
        self._set_picture_controls(True)
        self.msg.blockSignals(True)
        self.msg.clear()
        self.msg.blockSignals(False)
        self._reprepare()
        return True

    def _set_picture_controls(self, on: bool):
        for w in (self.res_cap, self.res, self.qual):
            w.setVisible(on)

    def _reprepare(self):
        c = self.chosen
        if not c or "image" not in c:
            return
        budget = next(n for k, _t, n in QUALITIES if k == self.qual.currentData())
        c["data"], c["quality"], c["dims"] = jpeg_for_hsmodem(c["image"], self.res.currentData() or "", budget)
        self._refresh_what()

    def _typed(self):
        if self.msg.toPlainText().strip():
            self.chosen = None
            self._set_picture_controls(False)
        self._refresh_what()

    def message(self) -> dict | None:
        """What Send would send: send() arguments, or None."""
        t = self.msg.toPlainText()
        if t.strip():
            return {"text": t}
        if self.chosen and self.chosen.get("data") is not None:
            return {"name": self.chosen["name"], "data": self.chosen["data"]}
        return None

    def _refresh_what(self):
        m = self.message()
        if m is None:
            self.what.setText(self.tr("Nothing chosen: pick a file or a picture, or type a message."))
            return
        bps = self.speed_now()
        try:
            pl = hs.plan(speed=bps, **m)
        except ValueError as e:
            self.what.setText(str(e))
            return
        if "text" in m:
            head = self.tr("Message, %n character(s)", "", len(m['text']))
        elif self.chosen and "image" in self.chosen:
            c = self.chosen
            d = c.get("dims")
            head = self.tr("{name}: {size} picture → {width}×{height} JPEG, quality {quality}, {jpeg}").format(
                name=self.chosen['name'], size=fmt_bytes(c['orig']), width=d.width(), height=d.height(),
                quality=c['quality'], jpeg=fmt_bytes(pl['size']))
        else:
            head = self.tr("{name}, {size} ({zipped} zipped)").format(
                name=pl['name'], size=fmt_bytes(pl['size']), zipped=fmt_bytes(pl['bytes']))
        # Two lines: what is sent, then how long it takes (a sentence of its own).
        self.what.setText(head + "\n" + self.tr(
            "%n frame(s), about {time} at {bps} bit/s, six seconds of it the preamble every HSmodem receiver locks "
            "on", "", int(pl['frames'])).format(time=fmt_secs(pl['seconds']), bps=bps))

    def send(self):
        m = self.message()
        if m is None:
            self.bridge.say(self.tr("Choose a file or a picture, or type a message, first"))
            return
        try:
            pl = hs.plan(speed=self.speed_now(), **m)
        except ValueError as e:
            self.bridge.say(str(e))
            return
        if self.bridge.send("hsmodem", **m):
            self.sending = pl
            self.tx_bar.setValue(0)

    def stop(self):
        if self.st("keyed"):
            self.bridge.halt()
        self.sending = None
        self.tx_bar.setValue(0)

    def on_state(self, ch: dict):
        if "hsSpeed" in ch:
            i = self.speed.findData(int(ch["hsSpeed"]))
            if i >= 0:
                self.speed.setCurrentIndex(i)
            self._refresh_what()
        if "keyed" in ch and not ch["keyed"] and self.sending is not None:
            self.tx_bar.setValue(1000 if not self.st("txBlocked") else 0)
            self.sending = None
        if "txSeconds" in ch and self.sending and self.st("keyed"):
            self.tx_bar.setValue(int(1000 * min(1.0, float(ch["txSeconds"] or 0) / max(0.1, self.sending["seconds"]))))
