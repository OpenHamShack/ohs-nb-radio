"""The multimedia beacon view: what AMSAT-DL's High-Speed Multimedia Beacon
(10489.995 MHz) is sending, received in the background by the engine
(ohsnb/beaconrx.py) whatever the dial is tuned to.

Pages, in the order the beacon's content matters to an operator:
bulletins (text), the DX cluster (a table, and QO-100 spots as labels on
the wide scope when "Spots on scope" is on), pictures (thumbnails; a click
enlarges one) and the transponders' spectra as the beacon sends them. A
status line over them says how well the beacon is decoding: MER, frames
decoded and lost, when the last one came.

Then the other beacon with something to read: the middle beacon's text
(ohsnb/beacontext.py) - DK0SB's K, L, M and N blocks, the latest of each,
with when it came. Last, not a beacon but received the same way, in the
background: KG-STV pictures from 10489.6249 (ohsnb/kgstvrx.py) - the one
coming in, block by block as it arrives, and the ones kept. On those two
pages the status line is their receiver's.

MmbStore holds what has arrived and outlives the widgets: a theme change
rebuilds the window, not the store. It reads the engine's "mmb" feed on the
bridge's timer and, at start, what earlier sessions saved in the data
folder, so the view is not empty until the next bulletin comes round.
"""
from __future__ import annotations

import html
import time
from collections import deque
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QListView, QListWidget,
                             QListWidgetItem, QPlainTextEdit, QSizePolicy, QSplitter, QStackedWidget, QTableWidget,
                             QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from ohscore.ui import theme
from ohscore.ui.controls import Button, Segmented, Toggle

from .. import bandplan, bulletin
from ..beacontext import saved_blocks
from ohscore.dsp import kgstv
from ..kgstvrx import saved_pictures
from .kgstvsend import SendingStrip, SendPictureDialog

PAGES = [("bulletins", "Bulletins"), ("dx", "DX cluster"), ("pictures", "Pictures"), ("spectra", "Spectra"),
         ("midtext", "Middle beacon"), ("kgstv", "KG-STV")]
QO100_KHZ = (bandplan.DL_LO / 1e3, bandplan.DL_HI / 1e3)


def is_qo100(qrg_khz: float) -> bool:
    return QO100_KHZ[0] <= qrg_khz <= QO100_KHZ[1]


def fmt_khz(qrg: float) -> str:
    """Cluster frequencies are kHz: 10489540.0 reads better as 10 489.540 MHz."""
    if qrg >= 1e6:
        return f"{qrg / 1e3:,.3f} MHz".replace(",", " ")
    return f"{qrg:,.1f} kHz".replace(",", " ")


def utc_stamp(t: float) -> str:
    """When something arrived, as the lists show it: in UTC, and saying so.
    They were in local time until 17/10/2026 while the status bar, the
    chat and the decodes are in UTC - a KG-STV picture "17:09" beside a
    chat line "16:14 UTC" on a Mac in BST (Mac test, finding 19)."""
    return time.strftime("%d %b %H:%M UTC", time.gmtime(t))


def ago(t: float, now: float | None = None) -> str:
    if not t:
        return "none yet"
    s = max(0.0, (now or time.time()) - t)
    if s < 90:
        return f"{s:.0f} s ago"
    if s < 5400:
        return f"{s / 60:.0f} min ago"
    return time.strftime("%H:%M UTC", time.gmtime(t))


class BulletinView(QTextBrowser):
    """A bulletin, read: HTML ones drawn as HTML, plain ones as the text
    they are (ohsnb/bulletin.py makes either of what the beacon sent).

    Nothing a bulletin names is ever fetched: loadResource refuses every
    resource - an image, a stylesheet, a file: URL on this computer - and
    bulletin.clean_html has already taken out the tags that ask for one,
    so a bulletin cannot make NB reach out to anywhere or read a local
    file into view. A link opens in the system's browser, and only when
    clicked: QTextBrowser's own link following (which would navigate this
    view) is off."""

    refused: list[str]       # what loadResource turned away, newest last (kept for tests)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.refused = []
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._clicked)

    def loadResource(self, kind: int, url: QUrl):
        self.refused = (self.refused + [url.toString()])[-20:]
        return None

    @staticmethod
    def _clicked(url: QUrl) -> None:
        if url.scheme().lower() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def show_bulletin(self, text: str, name: str = "") -> bulletin.Bulletin:
        b = bulletin.parse(text, name)
        if b.is_html:
            self.setFont(theme.font(13))
            body = bulletin.under_title(b.body) if b.title else b.body
            head = f"<h1>{html.escape(b.title)}</h1>" if b.title else ""
            self.document().setDefaultStyleSheet(f"a {{ color: {theme.t()['accent']}; }}")
            self.setHtml(head + body)
        else:
            self.setFont(theme.font(13, mono=True))
            self.setPlainText((b.title + "\n\n" if b.title else "") + b.body)
        return b


class MmbStore(QObject):
    """What the beacon has sent this session (and earlier ones, from disk)."""

    changed = pyqtSignal(str)          # "bulletin", "dx", "picture", "spectra", "cw", "progress", "midtext", "kgstv"
    qo100_spot = pyqtSignal(dict)      # a new spot on the QO-100 downlink

    MAX_SPOTS = 400

    def __init__(self, bridge, folder: Path, mid_folder: Path | None = None, kg_folder: Path | None = None):
        super().__init__()
        self.bridge = bridge
        self.folder = Path(folder)
        # The middle beacon's text: {block type: (text, t)}, the latest of each.
        self.mid_folder = Path(mid_folder) if mid_folder is not None else self.folder.parent / "midbeacon"
        self.midtext: dict[str, tuple[str, float]] = saved_blocks(self.mid_folder)
        # KG-STV: the picture coming in (or the last one), and those kept.
        self.kg_folder = Path(kg_folder) if kg_folder is not None else self.folder.parent / "kgstv"
        self.kg = self._kg_blank()
        self.kg_saved: list[tuple[str, float]] = saved_pictures(self.kg_folder)
        self.kg_texts: deque = deque(maxlen=50)
        # The picture we are sending, or sent last (kgstvsend.SendingStrip).
        self.kg_sending: dict | None = None
        self.bulletins: dict[str, tuple[str, float]] = {}
        self.pictures: list[tuple[str, bytes, str, float]] = []      # name, data, path, t
        self.spots: deque = deque(maxlen=self.MAX_SPOTS)
        self.spot_keys: set = set()
        self.cw: deque = deque(maxlen=200)
        self.nbspec = None
        self.wbspec = None
        self.progress: dict | None = None
        try:
            self.feed = bridge.radio.subscribe("mmb", 512)
        except ValueError:
            self.feed = None      # an engine without the beacon (never NB's)
        try:
            self.mid_feed = bridge.radio.subscribe("midtext", 64)
        except ValueError:
            self.mid_feed = None
        try:
            self.kg_feed = bridge.radio.subscribe("kgstv", 1024)
        except ValueError:
            self.kg_feed = None
        self._load_saved()
        bridge.tick.connect(self.pump)

    def _load_saved(self) -> None:
        if not self.folder.is_dir():
            return
        files = sorted(self.folder.iterdir(), key=lambda p: p.stat().st_mtime)
        for p in files:
            low = p.name.lower()
            try:
                if low.endswith((".blt", ".txt")):
                    self.bulletins[p.name] = (p.read_bytes().decode("utf-8", "replace"), p.stat().st_mtime)
                elif low.endswith((".jpg", ".jpeg")):
                    self.pictures.append((p.name, p.read_bytes(), str(p), p.stat().st_mtime))
            except OSError:
                continue

    @staticmethod
    def _kg_blank(pid=None, call: str = "", t: float = 0.0) -> dict:
        return {"id": pid, "rgb": np.zeros((kgstv.HEIGHT, kgstv.WIDTH, 3), np.uint8),
                "have": np.zeros((kgstv.BLOCKS_Y, kgstv.BLOCKS_X), bool), "call": call, "mode": "", "t": t,
                "done": False, "why": "", "path": ""}

    def _kg_event(self, ev: dict) -> None:
        k = ev.get("kind")
        t = float(ev.get("t") or time.time())
        if k == "start":
            self.kg = self._kg_blank(ev["id"], ev.get("call", ""), t)
        elif k == "block":
            if ev["id"] != self.kg["id"]:
                self.kg = self._kg_blank(ev["id"], ev.get("call", ""), t)
            x, y = int(ev["x"]), int(ev["y"])
            self.kg["rgb"][y * 16:(y + 1) * 16, x * 16:(x + 1) * 16] = \
                np.frombuffer(ev["rgb"], np.uint8).reshape(16, 16, 3)
            self.kg["have"][y, x] = True
            self.kg["call"] = ev.get("call") or self.kg["call"]
            self.kg["mode"] = ev.get("mode", "")
        elif k == "done":
            if ev["id"] == self.kg["id"]:
                self.kg.update(done=True, why=ev.get("why", ""), path=ev.get("path", ""),
                               call=ev.get("call") or self.kg["call"])
            if ev.get("path"):
                self.kg_saved = [(p, m) for p, m in self.kg_saved if p != ev["path"]]
                self.kg_saved.insert(0, (ev["path"], t))
        elif k == "call" and not self.kg["call"] and self.kg["id"] is not None and not self.kg["done"]:
            self.kg["call"] = ev.get("call", "")
        elif k == "text":
            self.kg_texts.append((t, ev.get("call", ""), ev.get("text", "")))

    def pump(self, _dt: float = 0.0) -> None:
        what = set()
        if self.mid_feed is not None:
            for ev in self.mid_feed.drain():
                self.midtext[ev["type"]] = (ev.get("text", ""), float(ev.get("t") or time.time()))
                what.add("midtext")
        if self.kg_feed is not None:
            for ev in self.kg_feed.drain():
                self._kg_event(ev)
                what.add("kgstv")
        if self.feed is None:
            for w in what:
                self.changed.emit(w)
            return
        for ev in self.feed.drain():
            k = ev.get("kind")
            t = float(ev.get("t") or time.time())
            if k == "bulletin":
                self.bulletins.pop(ev["name"], None)
                self.bulletins[ev["name"]] = (ev.get("text", ""), t)
                what.add("bulletin")
            elif k == "image":
                self.pictures = [x for x in self.pictures if x[0] != ev["name"]]
                self.pictures.append((ev["name"], ev["data"], ev.get("path", ""), t))
                what.add("picture")
            elif k == "dx":
                key = (ev["dxcall"], ev["qrg_khz"], ev["utc"], ev["reporter"])
                if key in self.spot_keys:
                    continue
                if len(self.spots) == self.spots.maxlen:
                    old = self.spots[0]
                    self.spot_keys.discard((old["dxcall"], old["qrg_khz"], old["utc"], old["reporter"]))
                self.spot_keys.add(key)
                spot = {**ev, "t": t}
                self.spots.append(spot)
                what.add("dx")
                if is_qo100(ev["qrg_khz"]):
                    self.qo100_spot.emit(spot)
            elif k == "cw":
                self.cw.append((t, ev["text"]))
                what.add("cw")
            elif k == "nbspec":
                self.nbspec = ev
                what.add("spectra")
            elif k == "wbspec":
                self.wbspec = ev
                what.add("spectra")
            elif k in ("file_start", "file_progress"):
                self.progress = ev
                what.add("progress")
            if k in ("bulletin", "image", "file", "repeat", "file_bad") and self.progress \
                    and self.progress.get("name") == ev.get("name"):
                self.progress = None          # finished (or given up): no longer "receiving ... 2/3"
                what.add("progress")
        for w in what:
            self.changed.emit(w)


class Spectrum(QWidget):
    """One of the beacon's spectra: 6-bit levels as bars, beacons marked."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.ev = None
        self.setMinimumHeight(90)

    def set(self, ev):
        self.ev = ev
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("scope"))
        p.drawRoundedRect(r, 6, 6)
        p.setFont(theme.font(11, theme.QFont.Weight.DemiBold))
        p.setPen(theme.c("text2"))
        p.drawText(r.adjusted(8, 4, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.title)
        if self.ev is None:
            p.setPen(theme.c("text3"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.tr("Waiting for the beacon…"))
            return
        v = np.asarray(self.ev["values"], float)
        start, step = float(self.ev["start"]), float(self.ev["step"])
        n = len(v)
        plot = r.adjusted(8, 20, -8, -18)
        w = plot.width() / max(n, 1)
        col = theme.c("trace")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        for i, x in enumerate(v):
            h = plot.height() * x / 63.0
            p.drawRect(QRectF(plot.x() + i * w, plot.bottom() - h, max(1.0, w * 0.85), h))
        p.setFont(theme.font(10, mono=True))
        p.setPen(theme.c("text3"))
        for frac in (0.0, 0.5, 1.0):
            f = start + step * (n - 1) * frac
            x = plot.x() + plot.width() * frac
            align = (Qt.AlignmentFlag.AlignLeft if frac == 0 else Qt.AlignmentFlag.AlignRight if frac == 1
                     else Qt.AlignmentFlag.AlignHCenter)
            box = QRectF(x - (0 if frac == 0 else 120 if frac == 1 else 60), plot.bottom() + 2, 120, 14)
            p.drawText(box, align | Qt.AlignmentFlag.AlignTop, f"{f / 1e6:.3f}")


class KgPicture(QWidget):
    """The KG-STV picture coming in: the blocks received so far, the rest
    the scope's colour, scaled to fit at 4:3."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img: QImage | None = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set(self, kg: dict) -> None:
        if kg["id"] is None:
            self.img = None
        else:
            rgb = kg["rgb"].copy()
            bg = theme.c("scope")
            missing = np.repeat(np.repeat(~kg["have"], 16, 0), 16, 1)
            rgb[missing] = (bg.red(), bg.green(), bg.blue())
            self._buf = np.ascontiguousarray(rgb)
            self.img = QImage(self._buf.data, kgstv.WIDTH, kgstv.HEIGHT, kgstv.WIDTH * 3,
                              QImage.Format.Format_RGB888)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        k = min(r.width() / kgstv.WIDTH, r.height() / kgstv.HEIGHT)
        box = QRectF(0, 0, kgstv.WIDTH * k, kgstv.HEIGHT * k)
        box.moveCenter(r.center())
        p.setPen(QPen(theme.c("line"), 1))
        p.setBrush(theme.c("scope"))
        p.drawRect(box.adjusted(-0.5, -0.5, 0.5, 0.5))
        if self.img is None:
            p.setPen(theme.c("text3"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.tr("KG-STV pictures from 10489.6249 USB appear here as they arrive, block by block"))
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(box, self.img)


class Enlarged(QDialog):
    def __init__(self, name: str, pm: QPixmap, parent=None, source: str = "multimedia beacon"):
        super().__init__(parent)
        self.setWindowTitle(f"{name} - {source}")
        lay = QVBoxLayout(self)
        lab = QLabel()
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scr = parent.screen().availableGeometry() if parent is not None and parent.screen() else None
        cap = QSize(int(scr.width() * 0.8), int(scr.height() * 0.8)) if scr else QSize(1200, 900)
        k = max(1.0, min(cap.width() / max(pm.width(), 1), cap.height() / max(pm.height(), 1), 3.0))
        lab.setPixmap(pm.scaled(int(pm.width() * k), int(pm.height() * k), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(lab)


class MmbView(QWidget):
    """The view itself, rebuilt with the window; reads an MmbStore."""

    def __init__(self, bridge, prefs, store: MmbStore, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.store = bridge, prefs, store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)

        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.pages = Segmented(PAGES, prefs.get("mmbTab", "bulletins"), compact=True)
        self.pages.setFixedWidth(620)
        self.pages.picked.connect(self.show_page)
        top.addWidget(self.pages)
        top.addStretch(1)
        # The decode status on a line of its own, the width of the view: on
        # a 1366-pixel screen the lower panel has no room for it beside the
        # pages and the controls.
        self.status = QLabel("")
        self.status.setFont(theme.font(12, mono=True))
        self.status.setObjectName("Muted")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.spots_on = Toggle(self.tr("Spots on scope"), bool(prefs.get("mmbSpots", True)))
        self.spots_on.setToolTip(self.tr("Label the wide scope's waterfall with DX-cluster spots on the QO-100 "
                                         "downlink as the beacon sends them"))
        self.spots_on.toggled.connect(self._spots_toggled)
        self.spots_on.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.spots_on)
        op = Button(self.tr("Open folder"), icon="folder", small=True)
        op.setToolTip(self.tr("Where received files are saved: {folder}").format(folder=store.folder))
        op.clicked.connect(self.open_folder)
        op.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(op)
        lay.addLayout(top)
        lay.addWidget(self.status)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._bulletins())
        self.stack.addWidget(self._dx())
        self.stack.addWidget(self._pictures())
        self.stack.addWidget(self._spectra())
        self.stack.addWidget(self._midtext())
        self.stack.addWidget(self._kgstv())
        lay.addWidget(self.stack, 1)

        store.changed.connect(self.refresh)
        bridge.changed.connect(self._state_changed)
        bridge.tick.connect(self._tick)
        self._last_status = 0.0
        for w in ("bulletin", "dx", "picture", "spectra", "cw", "midtext", "kgstv"):
            self.refresh(w)
        self.show_page(self.pages.value)
        self._update_status()

    def detach(self):
        """Stop listening to the store and the bridge: a theme change builds
        a new view, and a connection to this one would keep it alive and
        refreshing (ScopeView.detach says why that matters)."""
        for sig, slot in ((self.store.changed, self.refresh), (self.bridge.changed, self._state_changed),
                          (self.bridge.tick, self._tick)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    # -- pages ---------------------------------------------------------------
    def _bulletins(self) -> QWidget:
        sp = QSplitter(Qt.Orientation.Horizontal)
        self.blist = QListWidget()
        self.blist.setMinimumWidth(150)
        self.blist.currentItemChanged.connect(self._show_bulletin)
        self.btext = BulletinView()
        self.btext.setFont(theme.font(13, mono=True))
        self.btext.setPlaceholderText(self.tr("Bulletins from the beacon appear here as they arrive "
                                              "(each comes round every few minutes)."))
        sp.addWidget(self.blist)
        sp.addWidget(self.btext)
        sp.setStretchFactor(0, 1)
        sp.setStretchFactor(1, 4)
        return sp

    def _dx(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.S2)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([self.tr("UTC"), self.tr("DX"), self.tr("Frequency"), self.tr("Comment"),
                                              self.tr("Spotter"), self.tr("Locator")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        for i, mode in enumerate([QHeaderView.ResizeMode.ResizeToContents] * 3 + [QHeaderView.ResizeMode.Stretch]
                                 + [QHeaderView.ResizeMode.ResizeToContents] * 2):
            hh.setSectionResizeMode(i, mode)
        self.table.cellDoubleClicked.connect(self._spot_clicked)
        self.table.setToolTip(self.tr("Double-click a QO-100 spot to tune to it"))
        v.addWidget(self.table, 3)
        self.cwtext = QPlainTextEdit()
        self.cwtext.setReadOnly(True)
        self.cwtext.setFont(theme.font(12, mono=True))
        self.cwtext.setMaximumHeight(90)
        self.cwtext.setPlaceholderText(self.tr("CW skimmer"))
        v.addWidget(self.cwtext, 1)
        return w

    def _pictures(self) -> QWidget:
        self.plist = QListWidget()
        self.plist.setViewMode(QListView.ViewMode.IconMode)
        self.plist.setIconSize(QSize(160, 120))
        self.plist.setResizeMode(QListView.ResizeMode.Adjust)
        self.plist.setSpacing(8)
        self.plist.setMovement(QListView.Movement.Static)
        self.plist.itemClicked.connect(self._enlarge)
        self.plist.setToolTip(self.tr("Click a picture to enlarge it"))
        return self.plist

    def _spectra(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.S2)
        self.nbspec = Spectrum(self.tr("NB transponder (MHz)"))
        self.wbspec = Spectrum(self.tr("WB transponder (MHz)"))
        v.addWidget(self.nbspec, 1)
        v.addWidget(self.wbspec, 1)
        return w

    def _midtext(self) -> QWidget:
        self.mtext = QPlainTextEdit()
        self.mtext.setReadOnly(True)
        self.mtext.setFont(theme.font(13, mono=True))
        self.mtext.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.mtext.setPlaceholderText(self.tr("The middle beacon's text (10489.750 MHz) appears here as it is "
                                              "decoded: a block about every 25 s, each one coming round every "
                                              "couple of minutes."))
        return self.mtext

    def _kgstv(self) -> QWidget:
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        v = QVBoxLayout(left)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.S2)
        self.kgsend = SendingStrip(self.bridge, self.store)
        v.addWidget(self.kgsend)
        self.kgpic = KgPicture()
        v.addWidget(self.kgpic, 1)
        cap = QHBoxLayout()
        self.kgcap = QLabel("")
        self.kgcap.setFont(theme.font(12, mono=True))
        self.kgcap.setObjectName("Muted")
        self.kgcap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cap.addWidget(self.kgcap, 1)
        self.kg_send_btn = Button(self.tr("Send picture…"), icon="send", small=True)
        self.kg_send_btn.setToolTip(self.tr("Send a picture in KG-STV: choose it, see it as it will be received, "
                                            "then Send"))
        self.kg_send_btn.clicked.connect(self.send_picture)
        cap.addWidget(self.kg_send_btn)
        v.addLayout(cap)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(theme.S2)
        self.kglist = QListWidget()
        self.kglist.setViewMode(QListView.ViewMode.IconMode)
        self.kglist.setIconSize(QSize(160, 120))
        self.kglist.setResizeMode(QListView.ResizeMode.Adjust)
        self.kglist.setSpacing(8)
        self.kglist.setMovement(QListView.Movement.Static)
        self.kglist.itemClicked.connect(self._kg_enlarge)
        self.kglist.setToolTip(self.tr("Pictures kept (50 blocks or more). Click one to enlarge it"))
        rv.addWidget(self.kglist, 1)
        self.kgtext = QPlainTextEdit()
        self.kgtext.setReadOnly(True)
        self.kgtext.setFont(theme.font(12, mono=True))
        self.kgtext.setMaximumHeight(80)
        self.kgtext.setPlaceholderText(self.tr("KG-STV text messages"))
        rv.addWidget(self.kgtext)
        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 3)
        sp.setStretchFactor(1, 2)
        return sp

    def show_page(self, key: str) -> None:
        keys = [k for k, _ in PAGES]
        if key not in keys:
            key = "bulletins"
        self.pages.set_value(key)
        self.stack.setCurrentIndex(keys.index(key))
        self.prefs["mmbTab"] = key
        self._update_status()

    # -- content -------------------------------------------------------------
    def refresh(self, what: str) -> None:
        s = self.store
        if what == "bulletin":
            cur = self.blist.currentItem().data(Qt.ItemDataRole.UserRole) if self.blist.currentItem() else None
            self.blist.blockSignals(True)
            self.blist.clear()
            for name, (text, t) in sorted(s.bulletins.items(), key=lambda kv: -kv[1][1]):
                title = bulletin.title_of(text, name) or name
                it = QListWidgetItem(f"{title}\n{utc_stamp(t)}")
                it.setToolTip(name)
                it.setData(Qt.ItemDataRole.UserRole, name)
                self.blist.addItem(it)
            self.blist.blockSignals(False)
            names = [self.blist.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.blist.count())]
            if names:
                self.blist.setCurrentRow(names.index(cur) if cur in names else 0)
        elif what == "dx":
            spots = list(s.spots)[::-1]
            self.table.setRowCount(len(spots))
            for r, sp in enumerate(spots):
                cells = [sp["utc"], sp["dxcall"], fmt_khz(sp["qrg_khz"]), sp["comment"], sp["reporter"], sp["loc"]]
                for c, text in enumerate(cells):
                    it = QTableWidgetItem(text)
                    if is_qo100(sp["qrg_khz"]):
                        it.setForeground(theme.c("accent"))
                    if c == 2:
                        it.setData(Qt.ItemDataRole.UserRole, sp["qrg_khz"])
                    self.table.setItem(r, c, it)
        elif what == "picture":
            self.plist.clear()
            for name, data, path, t in reversed(s.pictures):
                pm = QPixmap()
                if not pm.loadFromData(data):
                    continue
                it = QListWidgetItem(QIcon(pm.scaled(160, 120, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)),
                                     f"{name}\n{utc_stamp(t)}")
                it.setData(Qt.ItemDataRole.UserRole, name)
                it.setToolTip(path or name)
                self.plist.addItem(it)
            if not self.plist.count():
                it = QListWidgetItem(self.tr("Pictures from the beacon appear here"))
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                it.setForeground(theme.c("text3"))
                self.plist.addItem(it)
        elif what == "spectra":
            self.nbspec.set(s.nbspec)
            self.wbspec.set(s.wbspec)
        elif what == "cw":
            self.cwtext.setPlainText("\n".join(f"{time.strftime('%H:%M:%S', time.gmtime(t))}Z  {x}"
                                               for t, x in list(s.cw)[-40:]))
            self.cwtext.verticalScrollBar().setValue(self.cwtext.verticalScrollBar().maximum())
        elif what == "progress":
            self._update_status()
        elif what == "kgstv":
            kg = s.kg
            self.kgpic.set(kg)
            if kg["id"] is None:
                self.kgcap.setText("")
            else:
                n = int(kg["have"].sum())
                when = time.strftime("%H:%M UTC", time.gmtime(kg["t"]))
                state = {"end": self.tr("complete"), "abort": self.tr("aborted by the sender"),
                         "timeout": self.tr("signal lost"), "restart": self.tr("a new picture began")
                         }.get(kg["why"], self.tr("receiving")) if kg["done"] else self.tr("receiving")
                # A line of fields, not a sentence: each field is translated
                # whole and the separators stay where they are.
                self.kgcap.setText(self.tr("{call} · {mode} · {when} · {n}/{total} blocks · {state}").format(
                    call=kg["call"] or self.tr("no callsign yet"), mode=kg["mode"], when=when, n=n,
                    total=kgstv.BLOCKS_X * kgstv.BLOCKS_Y, state=state))
            if [self.kglist.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.kglist.count())] \
                    != [p for p, _ in s.kg_saved]:
                self.kglist.clear()
                for path, t in s.kg_saved:
                    pm = QPixmap(path)
                    if pm.isNull():
                        continue
                    it = QListWidgetItem(QIcon(pm.scaled(160, 120, Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation)),
                                         f"{Path(path).stem.split('_', 2)[-1]}\n"
                                         f"{utc_stamp(t)}")
                    it.setData(Qt.ItemDataRole.UserRole, path)
                    it.setToolTip(path)
                    self.kglist.addItem(it)
            self.kgtext.setPlainText("\n".join(f"{time.strftime('%H:%M', time.gmtime(t))}Z {c}: {x}"
                                               for t, c, x in s.kg_texts))
        elif what == "midtext":
            parts = []
            for kind, (text, t) in sorted(s.midtext.items()):
                when = time.strftime("%d %b %H:%M UTC", time.gmtime(t))
                parts.append(f"── {kind} · {when} " + "─" * 30 + "\n" + text)
            self.mtext.setPlainText("\n\n".join(parts))

    def _show_bulletin(self, item, _prev=None):
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.btext.show_bulletin(self.store.bulletins.get(name, ("", 0))[0], name)

    def _enlarge(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        for n, data, _path, _t in self.store.pictures:
            if n == name:
                pm = QPixmap()
                if pm.loadFromData(data):
                    Enlarged(n, pm, self.window()).exec()
                return

    def send_picture(self, path: str | None = None) -> SendPictureDialog:
        """The Send picture dialog (kgstvsend.py); once the engine has taken
        the picture, the strip above the picture follows it."""
        dlg = SendPictureDialog(self.bridge, self.window(), path=path)
        dlg.finished.connect(lambda _r: dlg.sent is not None and self.kgsend.start(dlg.sent))
        dlg.open()
        return dlg

    def _kg_enlarge(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        pm = QPixmap(path)
        if not pm.isNull():
            Enlarged(Path(path).stem, pm, self.window(), source="KG-STV").exec()

    def _spot_clicked(self, row: int, _col: int):
        it = self.table.item(row, 2)
        if it is None:
            return
        khz = float(it.data(Qt.ItemDataRole.UserRole))
        if is_qo100(khz):
            self.bridge.set(vfo=khz * 1e3)

    def _spots_toggled(self, on: bool):
        self.prefs["mmbSpots"] = bool(on)

    def open_folder(self):
        self.store.folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.folder)))

    # -- status --------------------------------------------------------------
    def _state_changed(self, ch: dict):
        if any(k.startswith(("mmb", "midText", "kgstv")) for k in ch):
            self._update_status()
        if any(k in ch for k in ("keyed", "txSeconds", "txSource", "txOnAir")):
            self.kgsend.refresh()

    def _tick(self, _dt):
        now = time.monotonic()
        if now - self._last_status > 1.0:      # "12 s ago" moves on by itself
            self._last_status = now
            self._update_status()

    def _update_status(self):
        if not hasattr(self, "status"):
            return                      # show_page() during construction
        st = self.bridge.st
        if self.pages.value in ("midtext", "kgstv"):
            text, colour = (midtext_status if self.pages.value == "midtext" else kgstv_status)(st)
            self.status.setText(text)
            self.status.setStyleSheet(f"color: {theme.t()[colour]};")
            return
        state = str(st.get("mmbState") or "off")
        if state == "receiving":
            text = (f"● receiving 10489.995 {float(st.get('mmbFreq') or 0):+.1f} Hz   "
                    f"MER {float(st.get('mmbMer') or 0):.1f} dB   "
                    f"frames {int(st.get('mmbFrames') or 0)} ok · {int(st.get('mmbLost') or 0)} lost   "
                    f"last {ago(float(st.get('mmbLast') or 0))}")
            colour = "ok"
        elif state == "searching":
            text = f"○ looking for the beacon at 10489.995   last frame {ago(float(st.get('mmbLast') or 0))}"
            colour = "warn"
        elif state == "off":
            text = "off - Settings › LNB & locks › Multimedia beacon"
            colour = "text3"
        else:
            text = state
            colour = "err"
        pr = self.store.progress
        if pr and state == "receiving" and pr.get("have", 0) < pr.get("blocks", 1):
            text += f"   receiving {pr['name']} {pr.get('have', 0)}/{pr.get('blocks', 0)}"
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.t()[colour]};")


def midtext_status(st: dict) -> tuple[str, str]:
    """The status line on the middle beacon's page, and its colour."""
    state = str(st.get("midTextState") or "off")
    last = ago(float(st.get("midTextLast") or 0))
    counts = f"blocks {int(st.get('midTextFrames') or 0)} ok · {int(st.get('midTextLost') or 0)} lost   last {last}"
    if state in ("receiving", "tracking"):
        head = "● receiving" if state == "receiving" else "◐ beacon found, waiting for a block"
        return (f"{head} 10489.750 {float(st.get('midTextFreq') or 0):+.1f} Hz   "
                f"SNR {float(st.get('midTextSnr') or 0):.1f} dB   {counts}", "ok" if state == "receiving" else "warn")
    if state == "searching":
        return f"○ looking for the middle beacon at 10489.750   last block {last}", "warn"
    if state == "off":
        return "off - Settings › LNB & locks › Middle beacon text", "text3"
    return state, "err"


def kgstv_status(st: dict) -> tuple[str, str]:
    """The status line on the KG-STV page, and its colour."""
    state = str(st.get("kgstvState") or "off")
    counts = (f"frames {int(st.get('kgstvFrames') or 0)} ok · {int(st.get('kgstvLost') or 0)} lost   "
              f"last {ago(float(st.get('kgstvLast') or 0))}")
    if state == "receiving":
        call = str(st.get("kgstvCall") or "")
        return (f"● receiving {call + ' ' if call else ''}on 10489.6249 USB "
                f"{float(st.get('kgstvFreq') or 0):+.0f} Hz   {counts}", "ok")
    if state == "listening":
        return f"○ listening on 10489.6249 USB   {counts}", "text2"
    if state == "off":
        return "off - Settings › LNB & locks › KG-STV pictures", "text3"
    return state, "err"


def spot_label(scope, spot: dict) -> None:
    """A QO-100 spot as a label on a scope's waterfall, at its frequency."""
    scope.add_label(float(spot["qrg_khz"]) * 1e3, f"{spot['dxcall']}", time.time(), "dx")


__all__ = ["MmbStore", "MmbView", "spot_label"]
