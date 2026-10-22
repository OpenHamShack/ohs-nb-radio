"""The Band view: every signal the band skimmer (ohsnb/skimmer.py) has found
on the transponder, one row each, in frequency order. A click on a row
tunes to it, in its mode: an SSB voice whose dial auto-tune has measured
to that dial; one not yet measured to where its spectrum puts the carrier,
and auto-tune then listens there (as a right-click's "Auto-tune onto the
voice here" does); CW, data and beacons as a click on the scope would;
a calling window (FT8, FT4, Q65, JS8) to its calling frequency in its mode.

The same list is a layer on the wide scope (ScopeView.set_band_marks):
a bar under each signal, a tick at a measured dial, a caption where there
is room. "Marks on scope" turns it off.

SkimStore holds the latest list and outlives the widgets (a theme change
rebuilds the window); it reads the engine's "skim" feed on the bridge's
timer.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QSizePolicy, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ohscore.ui import theme
from ohscore.ui.controls import Segmented, Toggle

FILTERS = [("all", "All"), ("voice", "Voice"), ("cw", "CW"), ("digital", "Data"), ("other", "Other")]
KIND_FILTER = {"ssb": "voice", "cw": "cw", "digital": "digital", "data": "digital", "known": "digital",
               "beacon": "other", "carrier": "other", "signal": "other"}
# Scope colours (theme scope keys) by kind; a measured SSB dial is "ok",
# one only guessed is "warn".
COLOURS = {"cw": "rx", "digital": "cq", "data": "segDigi", "known": "own", "beacon": "beacon",
           "carrier": "peak", "signal": "peak"}
COLUMNS = ["Frequency", "Signal", "Mode", "Heard", "SNR", "Note"]
NOTE_LINES = 2           # a note wraps to this many lines, then is cut short (its tooltip has it all)


def colour_of(e: dict) -> str:
    if e["kind"] == "ssb":
        return "ok" if e["exact"] else "warn"
    return COLOURS.get(e["kind"], "peak")


def freq_text(e: dict) -> str:
    """10489.773 700 for a measured dial; ~10489.774 for a guess."""
    f = e["dial"] if e.get("dial") is not None else e["f"]
    mhz = int(f // 1_000_000)
    rest = int(round(f - mhz * 1_000_000))
    if e["kind"] == "ssb" and not e["exact"]:
        if e.get("measured") == "once":
            return f"~{mhz}.{rest // 1000:03d} {rest % 1000:03d}"
        return f"~{mhz}.{rest // 1000:03d}"
    if e["kind"] == "ssb" or (e.get("dial") is not None and e["exact"]):
        return f"{mhz}.{rest // 1000:03d} {rest % 1000:03d}"
    return f"{mhz}.{rest // 1000:03d} {rest % 1000 // 10 * 10:03d}"


def heard_text(e: dict, now: float) -> str:
    if e["active"]:
        return "now"
    s = max(0.0, now - e["last"])
    return f"{s:.0f} s ago" if s < 90 else f"{s / 60:.0f} min ago"


def note_text(e: dict) -> str:
    if e["kind"] == "digital":
        n = e.get("count", 1)
        calls = e.get("calls") or []
        # Under SkimView, the table that shows it: this is a plain function.
        txt = QCoreApplication.translate("SkimView", "%n signal(s)", "", n)
        return txt + (": " + " ".join(calls) if calls else "")
    if e["kind"] == "ssb" and not e["exact"]:
        if e.get("measured") == "once":
            return "dial measured once, waiting for a second look to agree"
        return ("dial not measured yet" + (f" - {e['why']}" if e.get("why") else "")) if e.get("looks") \
            else "dial not measured yet"
    if e["kind"] == "known" and e.get("dial") is None:
        return _with_hint(e, "not decoded by OpenHamShack QO-100 NB")
    if e["kind"] == "signal" and e.get("why") == FAINT_WHY:
        # The skimmer's own words for a narrow look that found no line ten
        # dB over the rest of its channel. On the Mac test (FINDINGS 7)
        # several rows said just that, and it told the operator nothing
        # about the signal; this says what it means.
        return _with_hint(e, QCoreApplication.translate(
            "SkimView", "too faint to tell CW, a carrier or data apart; looked at again in a few minutes"))
    return _with_hint(e, e.get("why") or "")


# ohsnb/dsp/skim.py judge_narrow's sentence for a look that heard nothing
# standing out.
FAINT_WHY = "nothing stands out in the channel"


def _with_hint(e: dict, note: str) -> str:
    """The note, then what the surveys learnt about signals found where
    this one is (ohsnb/whatis.py HINTS), when they learnt anything: the
    band list's best guess at what an unidentified signal is."""
    if e["kind"] not in ("known", "data", "carrier", "signal"):
        return note
    from .. import whatis
    from .whatis import hint_text
    hint = hint_text(whatis.hint_at(float(e.get("f") or (e["lo"] + e["hi"]) / 2)))
    return note + (" - " if note and hint else "") + hint


def short_text(e: dict) -> str:
    """The caption on the scope."""
    if e["kind"] == "digital":
        return f"{e['label']} ×{e.get('count', 1)}"
    if e["kind"] == "ssb":
        # The skimmer's own word (skim.ssb_label): "SSB" once speech was
        # heard, whether or not the dial is confirmed yet - the list's
        # colour and note say that part.
        return "SSB" if e["exact"] or e.get("voice") else "SSB?"
    return {"cw": "CW", "carrier": "", "data": "Data", "signal": ""}.get(e["kind"], e["label"].split(" (")[0])


def tip_text(e: dict) -> str:
    lines = [f"<b>{e['label']}</b> {freq_text(e)} MHz", f"{e['mode'].upper()}, {e['snr']:.0f} dB over the noise"]
    n = note_text(e)
    if n:
        lines.append(n)
    lines.append("Click to tune")
    return "<br>".join(lines)


class SkimStore(QObject):
    """The skimmer's latest list."""

    changed = pyqtSignal()

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.entries: list[dict] = []
        self.t = 0.0
        try:
            self.feed = bridge.radio.subscribe("skim", 8)
        except ValueError:
            self.feed = None
        bridge.tick.connect(self.pump)

    def pump(self, _dt: float = 0.0) -> None:
        if self.feed is None:
            return
        items = self.feed.drain()
        if items:
            self.entries = list(items[-1]["entries"])
            self.t = float(items[-1]["t"])
            self.changed.emit()

    def marks(self) -> list[dict]:
        out = []
        for e in self.entries:
            out.append({"lo": e["lo"], "hi": e["hi"], "text": short_text(e), "colour": colour_of(e),
                        "dial": e["dial"] if e["kind"] == "ssb" and e["exact"] else None,
                        "tip": tip_text(e), "active": e["active"], "entry": e})
        return out


class SkimView(QWidget):
    """The view itself, rebuilt with the window; reads a SkimStore. `tune`
    is called with an entry when the operator picks one."""

    def __init__(self, bridge, prefs, store: SkimStore, tune, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.store, self.tune = bridge, prefs, store, tune
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.want = prefs.get("skimFilter", "all")
        self.filter = Segmented(FILTERS, self.want, compact=True)
        self.filter.setFixedWidth(400)
        self.filter.picked.connect(self._filter_picked)
        top.addWidget(self.filter)
        top.addStretch(1)
        self.marks_on = Toggle(self.tr("Marks on scope"), bool(prefs.get("skimMarks", True)))
        self.marks_on.setToolTip(self.tr("Mark each signal the skimmer has found along the bottom of the wide scope"))
        self.marks_on.toggled.connect(self._marks_toggled)
        self.marks_on.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.marks_on)
        lay.addLayout(top)
        self.status = QLabel("")
        self.status.setFont(theme.font(12, mono=True))
        self.status.setObjectName("Muted")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        for i in range(len(COLUMNS) - 1):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self._clicked)
        self.table.cellActivated.connect(self._clicked)
        self.table.setToolTip(self.tr("Click a signal to tune to it"))
        self.table.setFont(theme.font(12.5))
        # A long note wraps to two lines, then is cut short with its whole
        # text in the cell's tooltip: one line cut most notes in half
        # (FINDINGS 6's twin on this list), and unlimited lines let one
        # note take the list's height.
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        # A bound method, not a lambda: PyQt keeps a lambda slot alive with
        # the header, and the lambda's self then kept the whole window -
        # and the Settings dialog's Station timer, which outlived the
        # station it polls - from ever being freed (test_pad aborted).
        hh.sectionResized.connect(self._note_resized)
        lay.addWidget(self.table, 1)
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

    def _filter_picked(self, v: str):
        self.want = self.prefs["skimFilter"] = v
        self.refresh()

    def _marks_toggled(self, on: bool):
        self.prefs["skimMarks"] = bool(on)
        self.store.changed.emit()

    def shown(self) -> list[dict]:
        want = self.want
        return [e for e in self.store.entries if want == "all" or KIND_FILTER.get(e["kind"], "other") == want]

    def refresh(self):
        rows = self.shown()
        sel = self.table.currentRow()
        keep = self.rows[sel]["id"] if 0 <= sel < len(self.rows) else None
        self.rows = rows
        self.table.setRowCount(len(rows))
        now = time.time()
        dim = theme.c("text3")
        for r, e in enumerate(rows):
            cells = [freq_text(e), e["label"], e["mode"].upper(), heard_text(e, now), f"{e['snr']:.0f}",
                     note_text(e)]
            for c, text in enumerate(cells):
                it = self.table.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.table.setItem(r, c, it)
                it.setText(text)
                if c == 0:
                    it.setFont(theme.font(12.5, mono=True))
                    it.setForeground(theme.sc(colour_of(e)))
                elif not e["active"]:
                    it.setForeground(dim)
                else:
                    it.setForeground(QColor(theme.c("text")))
            self.table.item(r, 0).setToolTip(tip_text(e))
            self.table.item(r, len(COLUMNS) - 1).setToolTip(cells[-1])
        self._fit_rows()
        if keep is not None:
            idx = next((i for i, e in enumerate(rows) if e["id"] == keep), -1)
            if idx >= 0:
                self.table.selectRow(idx)
        self._update_status()

    def _note_resized(self, i: int, _old: int, _new: int) -> None:
        if i == len(COLUMNS) - 1:
            self._fit_rows()

    def _fit_rows(self) -> None:
        """Each row as tall as its note wrapped in the Note column's width,
        up to NOTE_LINES lines."""
        t = self.table
        col = len(COLUMNS) - 1
        fm = t.fontMetrics()
        one = t.verticalHeader().defaultSectionSize()
        w = max(40, t.columnWidth(col) - 12)
        for r in range(t.rowCount()):
            it = t.item(r, col)
            text = it.text() if it is not None else ""
            lines = 1
            if text and fm.horizontalAdvance(text) > w:
                lines = fm.boundingRect(0, 0, w, 10_000, Qt.TextFlag.TextWordWrap, text).height() // max(
                    1, fm.lineSpacing())
            n = max(1, min(NOTE_LINES, lines))
            h = one if n == 1 else one + (n - 1) * fm.lineSpacing()
            if t.rowHeight(r) != h:
                t.setRowHeight(r, h)

    def _clicked(self, row: int, _col: int):
        if 0 <= row < len(self.rows):
            self.tune(self.rows[row])

    def _state_changed(self, ch: dict):
        if any(k.startswith("skim") for k in ch):
            self._update_status()

    def _update_status(self):
        st = self.bridge.st
        state = st.get("skimState", "off")
        if state == "off":
            self.status.setText(self.tr("Band skimmer off (Settings › LNB & locks › Skim the whole band)"))
            return
        if state == "error":
            self.status.setText(self.tr("Band skimmer stopped after an error (see the log)"))
            return
        level = int(st.get("skimLevel") or 0)
        drop = int(st.get("skimDropped") or 0)
        # A line of fields, each translated whole with its own plural, and
        # joined by the separator: the English reads as it did, except that
        # one signal, dial or block is now singular.
        fields = [self.tr("%n signal(s)", "", int(st.get("skimSignals") or 0)),
                  self.tr("%n SSB dial(s) measured", "", int(st.get("skimExact") or 0)),
                  self.tr("{looks:.0f} looks/min").format(looks=float(st.get("skimLooks") or 0)),
                  self.tr("CPU {cpu:.1f} % of a core (budget {budget:g} %)").format(
                      cpu=float(st.get("skimCpu") or 0), budget=float(st.get("skimBudget") or 0))]
        if level:
            fields.append(self.tr("spectrum thinned ½") if level == 1 else self.tr("spectrum thinned ¼"))
        if drop:
            fields.append(self.tr("%n block(s) dropped", "", drop))
        self.status.setText(" · ".join(fields))


__all__ = ["SkimStore", "SkimView", "freq_text", "note_text", "short_text"]
