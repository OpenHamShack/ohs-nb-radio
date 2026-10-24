"""Decoders: decoders running on frequencies of their own, beside the mode's
(the engine's decoder sessions, ohscore/decoders.py; docs/ENGINE-API.md
`decoders`; RADIO-SDR-PLAN §4.5).

One card per session: what it is, where, its state in words and the text
it has copied, with Tune (the dial there, in the decoder's mode when the
radio has one) and Stop. The Add row starts one: the decoder, the
frequency (the dial's, until the operator types another) and the
decoder's own choices (RTTY's speed and shift, reverse). The scope's
right-click "Decode here as" starts one where the mouse is, without the
view. A card is what its decoder's `panel` hint says: a terminal for
text (RTTY, CW, PSK - a line per station when a PSK session hears
several), and for a picture (SSTV, milestone 2) the picture painting in
as its rows arrive, with the session's recent pictures under it.

A session only listens: nothing here keys, arms or answers anything.

DecodersStore holds the sessions and each one's text and outlives the
widgets (a theme change rebuilds the window); it reads the `decoders`
feed on the bridge's timer, and asks the engine for what it missed when
a session's `rev` jumps.

In ohscore rather than ohsradio so NB can show the same view when it wants
one; it reads only the engine's `decoders` and its feed.
"""
from __future__ import annotations

import base64
import time

import numpy as np
from PyQt6.QtCore import QCoreApplication, QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
                             QListWidget, QListWidgetItem, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Button
from ohscore.ui.panels.common import Terminal
from ohscore.ui.panels.sstv import SSTV_NAMES, Picture, sstv_name

TEXT_KEEP = 4000          # characters of each session's text kept here
LINE_KEEP = 120           # characters of each PSK station's line
REFRESH_S = 1.0           # how often the sessions' states and numbers are read again
THUMBS = 6                # a picture session's recent pictures shown under it
# Where a session goes when the frequency is left empty: the dial plus the
# decoder's usual audio offset - PSK's mode offset, SSTV's 1900 Hz leader
# (shack_sdr sstv.IQ_CENTRE_HZ); RTTY's and CW's are the dial itself.
DEFAULT_OFFSET = {"psk": 1000.0, "sstv": 1900.0}


def decoder_label(entry_or_id) -> str:
    """A decoder's name as the operator knows it."""
    did = entry_or_id["id"] if isinstance(entry_or_id, dict) else str(entry_or_id)
    return {"rtty": "RTTY", "cw": "CW", "ft8": "FT8", "ft4": "FT4", "q65": "Q65", "js8": "JS8", "psk": "PSK",
            "sstv": "SSTV"}.get(did, did.upper())


def params_text(decoder: str, params: dict) -> str:
    """RTTY's 45.45/170 (and "reversed"), as the mode's own label writes it."""
    if decoder == "rtty":
        baud = float(params.get("baud", 45.45))
        shift = float(params.get("shift", 170.0))
        text = f"{baud:g}/{shift:g}"
        if params.get("reverse"):
            text += " " + QCoreApplication.translate("DecodersView", "reversed")
        return text
    if decoder == "cw" and params.get("pitchHz"):
        return QCoreApplication.translate("DecodersView", "pitch {hz} Hz").format(hz=f"{float(params['pitchHz']):g}")
    if decoder == "psk":
        text = f"{float(params.get('baud', 31.25)):g} Bd"
        n = len(psk_channels(params))
        if n > 1:
            text += " " + QCoreApplication.translate("DecodersView", "%n station(s)", "", n)
        return text
    if decoder == "sstv":
        return sstv_name(params["mode"]) if params.get("mode") else \
            QCoreApplication.translate("DecodersView", "any mode")
    return ""


def psk_channels(params: dict) -> list[float]:
    """A PSK session's channels, Hz from its frequency ("0" when none is
    given: the decoder's default)."""
    out = []
    for part in str(params.get("channels", "0") or "0").split(","):
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out or [0.0]


def state_text(state: str) -> str:
    return {"starting": QCoreApplication.translate("DecodersView", "starting"),
            "running": QCoreApplication.translate("DecodersView", "listening"),
            "nosignal": QCoreApplication.translate("DecodersView", "no signal"),
            "synced": QCoreApplication.translate("DecodersView", "copying"),
            "outside": QCoreApplication.translate("DecodersView", "out of view"),
            "budget": QCoreApplication.translate("DecodersView", "paused"),
            "error": QCoreApplication.translate("DecodersView", "failed"),
            "stopped": QCoreApplication.translate("DecodersView", "stopped")}.get(state, state)


def mhz_text(hz: float) -> str:
    return fmt.frequency(int(round(hz)), "MHz", 4)


def transmitters_text(meta: dict) -> str:
    """A DAB session's transmitters heard (its feed's `transmitters`, Radio's
    names for the TII codes), a line each, strongest first: the site, how
    far and which way from the station, and its share of the signal. A
    code no list knows shows as itself."""
    lines = []
    for t in meta.get("transmitters") or []:
        n = round(float(t["levelDb"])) if t.get("levelDb") is not None else None
        db = "?" if n is None else f"{n:+d}" if n else "0"
        if not t.get("site"):
            lines.append(QCoreApplication.translate("DecodersView", "TII {main}/{sub} (not in the list), {db} dB")
                         .format(main=t.get("main"), sub=t.get("sub"), db=db))
        else:
            site = t["site"]
            listed = t.get("listedAs")
            if listed:
                # Heard under another code than the regulator's list gives
                # it (matched by its site or sub identifier): say both.
                site = QCoreApplication.translate("DecodersView", "{site} (sends TII {main}/{sub})").format(
                    site=site, main=t.get("main"), sub=t.get("sub"))
            if t.get("distanceKm") is None:
                lines.append(QCoreApplication.translate("DecodersView", "{site}, {db} dB").format(site=site, db=db))
            else:
                lines.append(QCoreApplication.translate("DecodersView", "{site}, {km} km at {deg}°, {db} dB")
                             .format(site=site, km=f"{float(t['distanceKm']):.0f}",
                                     deg=f"{int(t['bearingDeg']):03d}", db=db))
    if not lines:
        return ""
    return QCoreApplication.translate("DecodersView", "Transmitters heard:") + "\n" + "\n".join(lines)


class DecodersStore(QObject):
    """The engine's sessions and what each has copied."""

    changed = pyqtSignal()

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.sessions: list[dict] = []
        self.texts: dict[str, str] = {}
        # A PSK session's text per channel: {sid: {offset Hz: text}}.
        self.lines: dict[str, dict[float, str]] = {}
        # A picture session's picture being received: {sid: {"w", "h",
        # "rgb" (h x w x 3), "rows" (rows painted), "file" (once done),
        # "n" (a count of changes, for the card)}}.
        self.pictures: dict[str, dict] = {}
        self.revs: dict[str, int] = {}
        self.next_refresh = 0.0
        try:
            self.feed = bridge.radio.subscribe("decoders", 2000)
        except ValueError:          # an engine without decoder sessions
            self.feed = None
        bridge.tick.connect(self.pump)

    @property
    def decoders(self):
        return getattr(self.bridge.radio, "decoders", None)

    def catalogue(self) -> list[dict]:
        d = self.decoders
        return d.catalogue() if d is not None else []

    def pump(self, _dt: float = 0.0) -> None:
        if self.feed is None:
            return
        items = self.feed.drain()
        changed = False
        gaps = set()
        for it in items:
            sid = it.get("session")
            if sid is None:
                continue
            rev = int(it.get("rev") or 0)
            last = self.revs.get(sid)
            if last is not None and rev > last + 1:
                gaps.add(sid)
            self.revs[sid] = max(last or 0, rev)
            if it.get("type") == "text" and it.get("text"):
                self.texts[sid] = (self.texts.get(sid, "") + it["text"])[-TEXT_KEEP:]
                self._line(sid, it)
            elif it.get("type") == "image":
                self._image(sid, it)
            changed = True
        for sid in gaps:
            self._refill(sid)
        now = time.monotonic()
        if changed or now >= self.next_refresh:
            self.next_refresh = now + REFRESH_S
            self.refresh()

    def _line(self, sid: str, it: dict) -> None:
        """A character onto its PSK station's line (the session's channel
        nearest the frequency it was heard on)."""
        sess = next((x for x in self.sessions if x["id"] == sid), None)
        if sess is None or sess.get("decoder") != "psk" or it.get("offsetHz") is None:
            return
        chans = psk_channels(sess.get("params") or {})
        if len(chans) < 2:
            return
        c = min(chans, key=lambda c: abs(c - float(it["offsetHz"])))
        lines = self.lines.setdefault(sid, {})
        lines[c] = (lines.get(c, "") + it["text"].replace("\n", " "))[-LINE_KEEP:]

    def _image(self, sid: str, it: dict) -> None:
        """An `image` result into the session's picture."""
        ev = it.get("event")
        pic = self.pictures.get(sid)
        if ev == "start":
            w, h = int(it.get("width") or 0), int(it.get("height") or 0)
            if not (0 < w <= 2048 and 0 < h <= 2048):
                return
            self.pictures[sid] = {"w": w, "h": h, "rgb": np.zeros((h, w, 3), np.uint8), "rows": 0, "file": None,
                                  "n": (pic or {}).get("n", 0) + 1}
        elif pic is None:
            return
        elif ev == "lines":
            try:
                raw = np.frombuffer(base64.b64decode(it.get("rgb") or ""), np.uint8)
            except (ValueError, TypeError):
                return
            k = len(raw) // (pic["w"] * 3)
            first = int(it.get("from") or 0)
            if k <= 0 or not 0 <= first < pic["h"]:
                return
            k = min(k, pic["h"] - first)
            pic["rgb"][first:first + k] = raw[:k * pic["w"] * 3].reshape(k, pic["w"], 3)
            pic["rows"] = max(pic["rows"], first + k)
            pic["n"] += 1
        elif ev == "done":
            pic["file"] = it.get("file") or None
            pic["n"] += 1

    def files(self, sid: str | None = None) -> list[dict]:
        """The decoders' saved pictures, newest first; only `sid`'s if given."""
        d = self.decoders
        try:
            out = d.files() if d is not None else []
        except Exception:  # noqa: BLE001 - an engine without files: none
            return []
        return [f for f in out if sid is None or f.get("session") == sid]

    def file(self, name: str) -> bytes | None:
        d = self.decoders
        return d.file(name) if d is not None else None

    def _refill(self, sid: str) -> None:
        """A gap in `rev`: the text again from what the engine kept."""
        d = self.decoders
        sess = d.session(sid) if d is not None else None
        if not sess:
            return
        text = "".join(r.get("text", "") for r in sess.get("results", []) if r.get("type") == "text")
        self.texts[sid] = text[-TEXT_KEEP:]

    def refresh(self) -> None:
        d = self.decoders
        self.sessions = d.sessions() if d is not None else []
        live = {s["id"] for s in self.sessions}
        for sid in [k for k in self.texts if k not in live]:
            del self.texts[sid]
            self.revs.pop(sid, None)
        for store in (self.lines, self.pictures):
            for sid in [k for k in store if k not in live]:
                del store[sid]
        self.changed.emit()

    def start(self, decoder: str, freq: float, params: dict) -> dict:
        """Raises ohscore.decoders.Refused (a ValueError with the sentence)."""
        sess = self.decoders.start(decoder, freq, params)
        self.refresh()
        return sess

    def stop(self, sid: str) -> None:
        self.decoders.stop(sid)
        self.refresh()


class SessionCard(QFrame):
    """One session: title, state, its text, Tune and Stop."""

    def __init__(self, view: "DecodersView", sess: dict):
        super().__init__()
        self.view, self.sid = view, sess["id"]
        self.setObjectName("Card")
        k = theme.t()
        self.setStyleSheet(f"QFrame#Card {{ background: {k['bg1']}; border: 1px solid {k['line']};"
                           f" border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S3)
        lay.setSpacing(theme.S1)
        head = QHBoxLayout()
        self.title = QLabel("")
        self.title.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(self.title, 1)
        self.tune_btn = Button(QCoreApplication.translate("DecodersView", "Tune"), small=True)
        self.tune_btn.setToolTip(QCoreApplication.translate("DecodersView", "Put the dial on this signal"))
        self.tune_btn.clicked.connect(lambda: view.tune_to(self.sid))
        head.addWidget(self.tune_btn)
        self.stop_btn = Button(QCoreApplication.translate("DecodersView", "Stop"), small=True)
        self.stop_btn.clicked.connect(lambda: view.stop(self.sid))
        head.addWidget(self.stop_btn)
        lay.addLayout(head)
        self.state = QLabel("")
        self.state.setObjectName("Muted")
        self.state.setWordWrap(True)
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.state)
        self.term = Terminal()
        self.term.setMinimumHeight(70)
        lay.addWidget(self.term, 1)
        # A PSK session hearing several stations: a line for each.
        self.lines = QLabel("")
        self.lines.setFont(theme.font(12, mono=True))
        self.lines.setTextFormat(Qt.TextFormat.PlainText)
        self.lines.setWordWrap(True)
        self.lines.hide()
        lay.addWidget(self.lines)
        # A picture session (SSTV): the picture as it arrives, and its recent
        # ones beside it (a click shows one).
        self.pic: Picture | None = None
        self.thumbs: QListWidget | None = None
        self.pic_n = -1
        self.thumb_names: list[str] = []
        if sess.get("panel") == "image":
            self.term.hide()
            row = QHBoxLayout()
            self.pic = Picture(waiting=QCoreApplication.translate("DecodersView", "Waiting for a picture…"))
            self.pic.setMinimumSize(240, 180)
            row.addWidget(self.pic, 3)
            self.thumbs = QListWidget()
            self.thumbs.setViewMode(QListView.ViewMode.IconMode)
            self.thumbs.setIconSize(QSize(96, 72))
            self.thumbs.setMovement(QListView.Movement.Static)
            self.thumbs.setMaximumWidth(theme.px(230))
            self.thumbs.setToolTip(QCoreApplication.translate("DecodersView", "This decoder's recent pictures"))
            self.thumbs.itemClicked.connect(self._show_thumb)
            self.thumbs.hide()
            row.addWidget(self.thumbs, 1)
            lay.addLayout(row, 1)
        self.shown = ""
        self.update_from(sess, "")

    def update_from(self, sess: dict, text: str) -> None:
        mode = bool(sess.get("mode"))
        name = decoder_label(sess["decoder"])
        extra = params_text(sess["decoder"], sess.get("params") or {})
        where = mhz_text(float(sess.get("freqHz") or 0))
        if mode:
            self.title.setText(QCoreApplication.translate("DecodersView", "{name} - the mode's decoder, on the dial")
                               .format(name=name))
        else:
            self.title.setText(" · ".join(x for x in (name, extra, where) if x))
        self.tune_btn.setVisible(not mode)
        self.stop_btn.setVisible(not mode)
        stats = sess.get("stats") or {}
        words = [state_text(sess.get("state", ""))]
        if sess.get("whyText"):
            words.append(sess["whyText"])
        if stats.get("snrDb") is not None and sess.get("state") in ("synced", "running", "nosignal"):
            words.append(QCoreApplication.translate("DecodersView", "SNR {db} dB").format(db=f"{stats['snrDb']:.0f}"))
        if stats.get("offsetHz") is not None and sess.get("state") == "synced":
            words.append(QCoreApplication.translate("DecodersView", "{hz} Hz off").format(
                hz=f"{stats['offsetHz']:+.0f}"))
        self.state.setText(" · ".join(words))
        if self.pic is not None:
            self._update_picture()
            return
        lines = self.view.store.lines.get(self.sid) or {}
        multi = sess.get("decoder") == "psk" and len(psk_channels(sess.get("params") or {})) > 1
        # DAB names the transmitters it hears, under its state.
        heard = transmitters_text(sess.get("meta") or {}) if sess.get("decoder") == "dab" else ""
        self.lines.setVisible(multi or bool(heard))
        self.term.setVisible(not multi)
        if multi:
            self.lines.setText("\n".join(f"{c:+6.0f} Hz  {lines.get(c, '').strip()}"
                                          for c in psk_channels(sess.get("params") or {})))
            return
        if heard:
            self.lines.setText(heard)
        if text != self.shown:
            if text.startswith(self.shown):
                self.term.put(text[len(self.shown):])
            else:
                self.term.clear()
                self.term.put(text)
            self.shown = text


    def _update_picture(self) -> None:
        """The picture being received, and the session's saved ones."""
        pic = self.view.store.pictures.get(self.sid)
        if pic is not None and pic["n"] != self.pic_n:
            self.pic_n = pic["n"]
            h, w = pic["h"], pic["w"]
            if self.pic.buf is None or self.pic.buf.shape != (h, w):
                self.pic.start(w, h)
            a = pic["rgb"].astype(np.uint32)
            self.pic.buf[:] = 0xFF000000 | (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
            self.pic.line = h if pic["file"] else pic["rows"]
            self.pic.update()
        names = [f["name"] for f in self.view.store.files(self.sid)[:THUMBS]]
        if names == self.thumb_names:
            return
        self.thumb_names = names
        self.thumbs.clear()
        for name in names:
            data = self.view.store.file(name)
            img = QImage.fromData(data or b"", "PNG")
            if img.isNull():
                continue
            it = QListWidgetItem(QIcon(QPixmap.fromImage(img).scaled(
                96, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)), "")
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setToolTip(name)
            self.thumbs.addItem(it)
        self.thumbs.setVisible(self.thumbs.count() > 0)

    def _show_thumb(self, it: QListWidgetItem) -> None:
        data = self.view.store.file(it.data(Qt.ItemDataRole.UserRole))
        img = QImage.fromData(data or b"", "PNG")
        if not img.isNull():
            self.pic.buf = None
            self.pic.img = img
            self.pic.line = self.pic.of = img.height()
            self.pic.update()
            self.pic_n = -1                 # the next change paints the live picture again


class DecodersView(QWidget):
    """The view, rebuilt with the window; reads a DecodersStore. `tune(f,
    decoder, params)` puts the dial on a session's signal."""

    def __init__(self, bridge, prefs, store: DecodersStore, tune, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.store, self.tune = bridge, prefs, store, tune
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        add = QHBoxLayout()
        add.setSpacing(theme.S2)
        self.pick = QComboBox()
        self.pick.setToolTip(self.tr("The decoder to start"))
        self.pick.currentIndexChanged.connect(self._picked)
        add.addWidget(self.pick)
        self.freq = QLineEdit()
        self.freq.setPlaceholderText(self.tr("MHz (the dial's when empty)"))
        self.freq.setToolTip(self.tr("Where the signal is, MHz: for RTTY the middle of its two tones, for SSTV "
                                     "its 1900 Hz leader. Empty: where the dial puts the mode's signal. Right-click "
                                     "a signal on a scope to start one there."))
        self.freq.setMaximumWidth(theme.px(170))
        add.addWidget(self.freq)
        self.params_box = QHBoxLayout()
        self.params_box.setSpacing(theme.S1)
        add.addLayout(self.params_box)
        self.add_btn = Button(self.tr("Add"), small=True)
        self.add_btn.clicked.connect(self.add)
        add.addWidget(self.add_btn)
        add.addStretch(1)
        lay.addLayout(add)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.cards_lay = QVBoxLayout(inner)
        self.cards_lay.setContentsMargins(0, 0, 0, 0)
        self.cards_lay.setSpacing(theme.S2)
        self.cards_lay.addStretch(1)
        self.scroll.setWidget(inner)
        lay.addWidget(self.scroll, 1)
        self.cards: dict[str, SessionCard] = {}
        self.param_widgets: dict[str, object] = {}
        self.entries: list[dict] = []
        self._fill_picker()
        store.changed.connect(self.refresh)
        self.refresh()

    def detach(self):
        try:
            self.store.changed.disconnect(self.refresh)
        except (TypeError, RuntimeError):
            pass

    # ------------------------------------------------------------ the Add row
    def _fill_picker(self):
        self.entries = [e for e in self.store.catalogue() if e.get("fixed")]
        self.pick.blockSignals(True)
        self.pick.clear()
        for e in self.entries:
            self.pick.addItem(decoder_label(e), e["id"])
        self.pick.blockSignals(False)
        self._picked(0)
        usable = bool(self.entries)
        for w in (self.pick, self.freq, self.add_btn):
            w.setEnabled(usable)

    def _picked(self, _i: int):
        while self.params_box.count():
            w = self.params_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.param_widgets = {}
        e = self.entries[self.pick.currentIndex()] if 0 <= self.pick.currentIndex() < len(self.entries) else None
        if e is None:
            return
        names = {"baud": self.tr("Bd"), "shift": self.tr("Hz shift")}
        checks = {"reverse": self.tr("Reversed"), "afc": self.tr("AFC"), "syncStart": self.tr("Join part way")}
        for p in e.get("params") or []:
            if e["id"] == "sstv" and p["key"] == "mode":
                # Which SSTV mode to listen for: any (the decoder's default),
                # or one of the fourteen it decodes.
                cb = QComboBox()
                cb.addItem(self.tr("Any SSTV mode"), "")
                for mid in sstv_modes():
                    cb.addItem(sstv_name(mid), mid)
                cb.setToolTip(self.tr("The picture mode to listen for"))
                self.params_box.addWidget(cb)
                self.param_widgets[p["key"]] = cb
            elif e["id"] == "psk" and p["key"] == "channels":
                ed = QLineEdit()
                ed.setPlaceholderText(self.tr("stations, Hz from it"))
                ed.setToolTip(self.tr("More stations in the same session, Hz from its frequency, separated by "
                                      "commas, such as -400,0,350. Empty: the one on its frequency."))
                ed.setMaximumWidth(theme.px(150))
                self.params_box.addWidget(ed)
                self.param_widgets[p["key"]] = ed
            elif p.get("type") == "bool" and p["key"] in checks:
                chk = QCheckBox(checks[p["key"]])
                chk.setChecked(bool(p.get("default")))
                self.params_box.addWidget(chk)
                self.param_widgets[p["key"]] = chk
            elif p.get("type") == "choice":
                cb = QComboBox()
                for c in p["choices"]:
                    unit = names.get(p["key"])
                    cb.addItem(f"{c:g} {unit}" if unit else f"{c:g}", c)
                cb.setCurrentIndex(max(0, p["choices"].index(p["default"]) if p["default"] in p["choices"] else 0))
                self.params_box.addWidget(cb)
                self.param_widgets[p["key"]] = cb

    def params(self) -> dict:
        out = {}
        for key, w in self.param_widgets.items():
            if isinstance(w, QLineEdit):
                text = w.text().strip().replace(" ", "")
                if text:
                    out[key] = text
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            else:
                out[key] = bool(w.isChecked())
        return out

    def add(self):
        if not self.entries:
            return
        did = self.pick.currentData()
        text = self.freq.text().strip().replace(",", ".")
        try:
            f = float(text) * 1e6 if text else (float(self.bridge.st.get("rxDial") or self.bridge.st.get("vfo") or 0)
                                                 + DEFAULT_OFFSET.get(did, 0.0))
        except ValueError:
            self._say(self.tr("The frequency is a number of MHz, such as 14.0835"))
            return
        self.start(did, f, self.params())

    def start(self, decoder: str, f: float, params: dict | None = None):
        try:
            self.store.start(decoder, f, params or {})
        except ValueError as e:
            self._say(str(e))
            return
        self.freq.clear()

    def stop(self, sid: str):
        self.store.stop(sid)

    def tune_to(self, sid: str):
        sess = next((s for s in self.store.sessions if s["id"] == sid), None)
        if sess is not None:
            self.tune(float(sess["freqHz"]), sess["decoder"], sess.get("params") or {})

    def _say(self, text: str):
        self.status.setText(text)

    # ------------------------------------------------------------ the cards
    def refresh(self):
        if not self.entries and self.store.catalogue():
            self._fill_picker()
        sessions = self.store.sessions
        live = {s["id"] for s in sessions}
        for sid in [k for k in self.cards if k not in live]:
            card = self.cards.pop(sid)
            self.cards_lay.removeWidget(card)
            card.deleteLater()
        for i, s in enumerate(sessions):
            card = self.cards.get(s["id"])
            if card is None:
                card = self.cards[s["id"]] = SessionCard(self, s)
                self.cards_lay.insertWidget(i, card)
            card.update_from(s, self.store.texts.get(s["id"], ""))
        self.status.setText(self._summary(sessions))

    def _summary(self, sessions: list[dict]) -> str:
        st = self.bridge.st
        info = st.get("decoders") or {}
        if not self.entries:
            return self.tr("No decoders can run on frequencies of their own in this installation.")
        fixed = [s for s in sessions if not s.get("mode")]
        if not fixed:
            return self.tr("Each decoder here listens on its own frequency, whatever the dial does, as long as the "
                           "receiver's span covers it. Up to {n} at once (Settings › Decoders). They only listen.") \
                .format(n=int(st.get("decodersMax", 4)))
        line = self.tr("%n decoder(s) running", "", len(fixed))
        if info.get("cpuMax"):
            line += " · " + self.tr("processor share allowed {pct} %").format(pct=f"{float(info['cpuMax']) * 100:.0f}")
        return line


def sstv_modes() -> list[str]:
    """The SSTV modes the decoder takes, its own ids in its own order."""
    try:
        from ohscore import sdr
        m = sdr.load()
        if m is not None:
            return [x["id"] for x in m.sstv.modes()]
    except Exception:  # noqa: BLE001 - the names this view knows, then
        pass
    return list(SSTV_NAMES)


def scope_menu_entries(store: DecodersStore) -> list[tuple[str, str]]:
    """(label, decoder id) for "Decode here as": every decoder that can run
    on a frequency of its own."""
    return [(decoder_label(e), e["id"]) for e in store.catalogue() if e.get("fixed")]
