"""Over the beacon and LEILA, in the window: the over-power watch's list
(ohsnb/overpower.py) as a short table at the top of the Band view, and as
alerts on the wide scope - an amber column over a signal with more power
than the middle beacon ("+4 dB over beacon"), a red one where LEILA's siren
sounded ("LEILA?").

"LEILA?", with its question mark, because the siren detector is built from
six real sirens (docs/qo100-research.md section 9): the pattern is
measured, but what makes LEILA mark a station is not known, and six from
one evening are few. The tooltip says so.

A click on a row or on an alert's caption tunes the receiver there - the
dial only, in the mode it is in; nothing here touches the transmitter.
"Save the last 20 s" saves the LEILA evidence ring (Settings › LNB & locks ›
Keep LEILA evidence) for a siren heard that nothing marked.

OpStore holds the latest list and outlives the widgets (a theme change
rebuilds the window); it reads the engine's "overpower" feed on the
bridge's timer.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QSizePolicy,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ohscore.ui import theme
from ohscore.ui.controls import Button

FADE_S = 60.0        # an ended over-power event stays on the scope, faded, this long
LEILA_FADE_S = 120.0     # and a siren this long
ROWS = 6             # the table's most height, in rows (then it scrolls): the Band view's own list is below it


def mhz(f: float) -> str:
    m = int(f // 1_000_000)
    rest = int(round(f - m * 1_000_000))
    return f"{m}.{rest // 1000:03d} {rest % 1000:03d}"


def what_text(e: dict) -> str:
    if e["kind"] == "leila":
        return QCoreApplication.translate("OpPanel", "LEILA? siren-like")
    text = QCoreApplication.translate("OpPanel", "+{db:.1f} dB over beacon").format(db=e["excessDb"])
    return text + (" · " + QCoreApplication.translate("OpPanel", "LEILA?") if e.get("leila") else "")


def caption(e: dict) -> str:
    if e["kind"] == "leila":
        return QCoreApplication.translate("OpPanel", "LEILA?")
    return QCoreApplication.translate("OpPanel", "+{db:.0f} dB over beacon").format(db=e["excessDb"])


def tip_text(e: dict) -> str:
    when = time.strftime("%H:%M:%S", time.gmtime(e["start"]))
    where = (QCoreApplication.translate("OpPanel", "{freq} MHz, {width:.0f} Hz wide, {when} UTC, now")
             if e["active"] else QCoreApplication.translate("OpPanel", "{freq} MHz, {width:.0f} Hz wide, {when} UTC"))
    lines = [f"<b>{what_text(e)}</b>", where.format(freq=mhz(e["freq"]), width=e["width"], when=when)]
    if e["kind"] == "leila":
        lines.append(QCoreApplication.translate(
            "OpPanel", "Two tones {lo} and {hi} MHz taking turns every 200 ms: the pattern of LEILA's siren on "
                       "real recordings. Not confirmed as LEILA.").format(lo=mhz(e["lo"]), hi=mhz(e["hi"])))
    if e.get("call"):
        lines.append(QCoreApplication.translate("OpPanel", "Heard here by your decoder: {call}").format(call=e["call"]))
    lines.append(QCoreApplication.translate("OpPanel", "Click to tune the receiver here"))
    return "<br>".join(lines)


class OpStore(QObject):
    """The watch's latest list."""

    changed = pyqtSignal()

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.events: list[dict] = []
        self.next_fade = 0.0
        try:
            self.feed = bridge.radio.subscribe("overpower", 16)
        except ValueError:
            self.feed = None
        bridge.tick.connect(self.pump)

    def pump(self, _dt: float = 0.0) -> None:
        if self.feed is None:
            return
        items = self.feed.drain()
        now = time.monotonic()
        if items:
            self.events = list(items[-1]["events"])
            self.changed.emit()
            self.next_fade = now + 5.0
        elif self.events and now >= self.next_fade:
            # The feed is quiet once nothing is active; the scope's faded
            # alerts still have to go when their time is up.
            self.next_fade = now + 5.0
            self.changed.emit()

    def alerts(self, now: float | None = None) -> list[dict]:
        """The wide scope's alerts (ScopeView.set_alerts): what is happening
        now, strong; what ended in the last minute or two, faded."""
        now = time.time() if now is None else now
        out = []
        for e in self.events:
            fade = LEILA_FADE_S if e["kind"] == "leila" or e.get("leila") else FADE_S
            if not e["active"] and now - e["end"] > fade:
                continue
            red = e["kind"] == "leila" or e.get("leila")
            out.append({"lo": e["lo"], "hi": e["hi"], "text": caption(e), "colour": "tx" if red else "warn",
                        "strong": bool(e["active"]), "tip": tip_text(e), "event": e})
        return out


class OpPanel(QWidget):
    """The table, rebuilt with the window; reads an OpStore. `tune` is
    called with an event when the operator picks one."""

    def __init__(self, bridge, store: OpStore, tune, parent=None):
        super().__init__(parent)
        self.bridge, self.store, self.tune = bridge, store, tune
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.title = QLabel(self.tr("Over the beacon"))
        self.title.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        top.addWidget(self.title)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setFont(theme.font(12, mono=True))
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.status, 1)
        self.save = Button(self.tr("Save the last 20 s"), small=True)
        self.save.setToolTip(self.tr("Heard LEILA and nothing marked it? Save the last 20 s of receive IQ to "
                                     "Recordings, to check the siren detector against"))
        self.save.clicked.connect(self._save)
        top.addWidget(self.save)
        lay.addLayout(top)
        cols = [self.tr("UTC"), self.tr("Frequency"), self.tr("What"), self.tr("Call")]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        for i in range(len(cols) - 1):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.setFont(theme.font(12.5))
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.table.cellClicked.connect(self._clicked)
        self.table.cellActivated.connect(self._clicked)
        lay.addWidget(self.table)
        self.rows: list[dict] = []
        store.changed.connect(self.refresh)
        bridge.changed.connect(self._state_changed)
        self.refresh()

    def detach(self):
        for sig, slot in ((self.store.changed, self.refresh), (self.bridge.changed, self._state_changed)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def refresh(self):
        rows = self.store.events
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            red = e["kind"] == "leila" or e.get("leila")
            cells = [time.strftime("%H:%M:%S", time.gmtime(e["start"])), mhz(e["freq"]), what_text(e),
                     e.get("call") or ""]
            for c, text in enumerate(cells):
                it = self.table.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.table.setItem(r, c, it)
                it.setText(text)
                if c == 1:
                    it.setFont(theme.font(12.5, mono=True))
                if c == 2:
                    it.setForeground(theme.sc("tx" if red else "warn", 1.0 if e["active"] else 0.6))
                else:
                    it.setForeground(theme.c("text") if e["active"] else theme.c("text3"))
                it.setToolTip(tip_text(e))
        self._fit()
        self._state_changed({"opState": None})

    def _fit(self) -> None:
        """As tall as its rows, up to ROWS and then scrolling; hidden while
        empty, when the status line already says nothing is over the
        beacon. It was six rows tall whatever it held, and that fixed
        height was part of the Band view's least height: in the Watch
        workspace at 1920 x 1080 it held the wide scope to 52 % of the
        body instead of Watch's 66 % (WP1's note)."""
        n = len(self.rows)
        self.table.setVisible(n > 0)
        row = self.table.verticalHeader().defaultSectionSize()
        head = self.table.horizontalHeader().sizeHint().height() + 4
        # Its least height is one row, not six: in the short Band view Watch
        # has, a least height of two or three rows already pushed the
        # scopes' splitter when the list arrived. It scrolls instead.
        self.table.setMinimumHeight(head + row)
        self.table.setMaximumHeight(head + row * min(max(n, 1), ROWS))

    def _clicked(self, row: int, _col: int):
        if 0 <= row < len(self.rows):
            self.tune(self.rows[row])

    def _save(self):
        try:
            self.bridge.radio.leila_capture_now()
        except ValueError as e:
            self.bridge.say(str(e))

    def _state_changed(self, ch: dict):
        if not any(k.startswith("op") or k == "leilaCapture" for k in ch):
            return
        st = self.bridge.st
        self.save.setEnabled(bool(st.get("leilaCapture")) and st.get("opState") == "running")
        state = st.get("opState", "off")
        if state == "off":
            self.status.setText(self.tr("Watch off (Settings › LNB & locks › Watch for signals over the beacon)"))
        elif state == "error":
            self.status.setText(self.tr("Watch stopped after an error (see the log)"))
        elif st.get("opBeacon") == "unlocked":
            self.status.setText(self.tr("Waiting for beacon lock: nothing is judged without the beacon"))
        elif st.get("opBeacon") == "weak":
            self.status.setText(self.tr("The beacon is too weak to compare with"))
        elif not self.rows:
            self.status.setText(self.tr("Nothing over the beacon, and no LEILA, in the last 30 minutes"))
        else:
            self.status.setText(" · ".join([
                self.tr("%n over the beacon now", "", int(st.get("opActive") or 0)),
                self.tr("%n LEILA? siren(s)", "", int(st.get("opLeila") or 0))]))


class BandView(QWidget):
    """The Band view: the over-power table above the band skimmer's list."""

    def __init__(self, panel: OpPanel, skim: QWidget, parent=None):
        super().__init__(parent)
        self.panel, self.skim = panel, skim
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        lay.addWidget(panel)
        lay.addWidget(skim, 1)

    def detach(self):
        self.panel.detach()
        self.skim.detach()


__all__ = ["BandView", "OpPanel", "OpStore", "caption", "what_text"]
