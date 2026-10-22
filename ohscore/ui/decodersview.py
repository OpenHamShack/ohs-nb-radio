"""Decoders: decoders running on frequencies of their own, beside the mode's
(the engine's decoder sessions, ohscore/decoders.py; docs/ENGINE-API.md
`decoders`; RADIO-SDR-PLAN §4.5).

One card per session: what it is, where, its state in words and the text
it has copied, with Tune (the dial there, in the decoder's mode when the
radio has one) and Stop. The Add row starts one: the decoder, the
frequency (the dial's, until the operator types another) and the
decoder's own choices (RTTY's speed and shift, reverse). The scope's
right-click "Decode here as" starts one where the mouse is, without the
view. Milestone 1's decoders print text, so every card is a terminal; the
`panel` hint each decoder carries is how later ones (frames, pictures)
will get theirs.

A session only listens: nothing here keys, arms or answers anything.

DecodersStore holds the sessions and each one's text and outlives the
widgets (a theme change rebuilds the window); it reads the `decoders`
feed on the bridge's timer, and asks the engine for what it missed when
a session's `rev` jumps.

In ohscore rather than ohsradio so NB can show the same view when it wants
one; it reads only the engine's `decoders` and its feed.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)

from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Button
from ohscore.ui.panels.common import Terminal

TEXT_KEEP = 4000          # characters of each session's text kept here
REFRESH_S = 1.0           # how often the sessions' states and numbers are read again


def decoder_label(entry_or_id) -> str:
    """A decoder's name as the operator knows it."""
    did = entry_or_id["id"] if isinstance(entry_or_id, dict) else str(entry_or_id)
    return {"rtty": "RTTY", "cw": "CW", "ft8": "FT8", "ft4": "FT4", "q65": "Q65", "js8": "JS8"}.get(did, did.upper())


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
    return ""


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


class DecodersStore(QObject):
    """The engine's sessions and what each has copied."""

    changed = pyqtSignal()

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.sessions: list[dict] = []
        self.texts: dict[str, str] = {}
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
            changed = True
        for sid in gaps:
            self._refill(sid)
        now = time.monotonic()
        if changed or now >= self.next_refresh:
            self.next_refresh = now + REFRESH_S
            self.refresh()

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
        if text != self.shown:
            if text.startswith(self.shown):
                self.term.put(text[len(self.shown):])
            else:
                self.term.clear()
                self.term.put(text)
            self.shown = text


class DecodersView(QWidget):
    """The view, rebuilt with the window; reads a DecodersStore. `tune(f,
    decoder)` puts the dial on a session's signal."""

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
        self.freq.setToolTip(self.tr("Where the signal is, MHz: for RTTY the middle of its two tones. Empty: the "
                                     "dial's frequency. Right-click a signal on a scope to start one there."))
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
        for p in e.get("params") or []:
            if p.get("type") == "choice":
                cb = QComboBox()
                for c in p["choices"]:
                    unit = names.get(p["key"])
                    cb.addItem(f"{c:g} {unit}" if unit else f"{c:g}", c)
                cb.setCurrentIndex(max(0, p["choices"].index(p["default"]) if p["default"] in p["choices"] else 0))
                self.params_box.addWidget(cb)
                self.param_widgets[p["key"]] = cb
            elif p.get("type") == "bool" and p["key"] == "reverse":
                chk = QCheckBox(self.tr("Reversed"))
                chk.setChecked(bool(p.get("default")))
                self.params_box.addWidget(chk)
                self.param_widgets[p["key"]] = chk

    def params(self) -> dict:
        out = {}
        for key, w in self.param_widgets.items():
            out[key] = w.currentData() if isinstance(w, QComboBox) else bool(w.isChecked())
        return out

    def add(self):
        if not self.entries:
            return
        did = self.pick.currentData()
        text = self.freq.text().strip().replace(",", ".")
        try:
            f = float(text) * 1e6 if text else float(self.bridge.st.get("rxDial") or self.bridge.st.get("vfo") or 0)
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
            self.tune(float(sess["freqHz"]), sess["decoder"])

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


def scope_menu_entries(store: DecodersStore) -> list[tuple[str, str]]:
    """(label, decoder id) for "Decode here as": every decoder that can run
    on a frequency of its own."""
    return [(decoder_label(e), e["id"]) for e in store.catalogue() if e.get("fixed")]
