"""CW Activity: what the CW skimmer hears (Radio's ohsradio/cwskim.py; the
contract is docs/ENGINE-API.md `cwskim`/`cwspot`). Two lists in one view,
as CW Skimmer and the Remote's CW Activity have them:

- **Spots**: one row per call the skimmer has spotted, with the UTC it was
  last heard, its frequency, WPM, key-on SNR in 500 Hz (the RBN's measure),
  its country, CQ/DX/BEACON, and how long ago. Busted calls are never
  listed; unconfirmed ones (a single decode of a call in no history) are
  dim and say "?". Sorted by frequency (CW Skimmer's band map) or newest.
- **Signals**: one row per channel the skimmer is decoding now, its rolling
  text with the call it found, strongest first.

A click on either tunes the dial there in CW (the skimmer's `dial`, which
is the signal less the CW pitch, rounded as a click on the scope rounds
it). It only tunes: nothing here replies, keys or arms anything (Brian,
13/10/2026). The same spots are marks on the wide scope and call labels
on the waterfalls; the window wires those (ohsradio/ui/mainwindow.py).

The switch is the engine's `cwSkim` setting itself, off by default and
switched on per use (Brian, 13/10/2026): the skimmer costs a share of a
core while it runs, so the view offers it where it is wanted rather than
running it behind every session.

In ohscore rather than ohsradio so NB can show its own CW segment the same way
later (CW-SKIMMER-PLAN Phase 3); it reads only the engine's feeds and the
optional `cwskim_view()`, never an app.

CwSkimStore holds what the view shows and outlives the widgets (a theme
change rebuilds the window); it reads the feeds on the bridge's timer.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QSizePolicy, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Button, Segmented, Toggle

KEEP_S = 1800.0         # spots kept, as the server keeps them (GET api/cwskim)
KEEP_N = 500
MARK_S = 600.0          # a spot is a mark on the scope for this long after it was last heard
TEXT_KEEP = 240         # characters of each channel's text kept here (the server sends its last 48)
MARK_HALF_HZ = 60.0     # a mark's bar either side of the signal: about a CW signal's width


def merge_text(old: str, new: str, shown: int = 48) -> str:
    """A channel's text, kept here from the server's last `shown`
    characters each second: the longest end of `old` that `new` starts
    with is where the new characters begin. A channel whose `new` overlaps
    nothing and is shorter than a full window is a fresh one (a new track
    with an old id): it replaces rather than runs on."""
    if not old:
        return new[-TEXT_KEEP:]
    if old.endswith(new):
        return old
    for k in range(min(len(old), len(new)), 0, -1):
        if old.endswith(new[:k]):
            return (old + new[k:])[-TEXT_KEEP:]
    if len(new) < shown:
        return new
    return (old + " " + new)[-TEXT_KEEP:]


# The plain functions below translate under CwSkimView, the class whose
# lists show what they return, spelled out at each call so pylupdate6 finds
# the strings.


def khz_text(hz: float) -> str:
    """14025.31: the RBN's 10 Hz, in the locale's decimals (the column says kHz)."""
    return fmt.frequency(int(round(hz)), "kHz", 2).rsplit(fmt.NBSP, 1)[0]


def utc_text(t: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(t)) if t else ""


def age_text(t: float, now: float) -> str:
    s = max(0.0, now - (t or now))
    if s < 15:
        return QCoreApplication.translate("CwSkimView", "now")
    if s < 90:
        return QCoreApplication.translate("CwSkimView", "%n s ago", "", int(s))
    return QCoreApplication.translate("CwSkimView", "%n min ago", "", int(round(s / 60)))


def tag_text(kind: str | None) -> str:
    return {"cq": "CQ", "dx": "DX", "beacon": "BEACON"}.get(kind or "", "")


def colour_of(kind: str | None) -> str:
    """The theme scope key for a spot or call: CQ as the FT8 labels colour
    a CQ, a beacon as NB's beacons, anyone else as the receive passband."""
    return {"cq": "cq", "beacon": "beacon"}.get(kind or "", "rx")


def status_text(st: dict, item: dict) -> str:
    """One line on what the skimmer is doing, from the engine's status keys
    and the newest cwskim item."""
    state = st.get("cwSkimState") or item.get("state") or "off"
    if not st.get("cwSkim") and state == "off":
        return QCoreApplication.translate(
            "CwSkimView", "Off. Switch it on to decode every CW signal in the band's CW segment at once. It only "
                          "listens: a click on a spot tunes there and never transmits.")
    if state in ("outside", "error"):
        why = st.get("cwSkimWhy") or item.get("why")
        if why or state == "outside":
            return why or ""
        return QCoreApplication.translate("CwSkimView", "The CW skimmer stopped.")
    if state == "off":
        return QCoreApplication.translate("CwSkimView", "Starting…")
    seg, cover = item.get("segment") or {}, item.get("cover") or {}
    fields = []
    if seg:
        fields.append(QCoreApplication.translate("CwSkimView", "{band} CW {lo}–{hi} MHz").format(
            band=item.get("band") or "", lo=fmt.frequency(int(seg["lo"]), "MHz", 3).rsplit(fmt.NBSP, 1)[0],
            hi=fmt.frequency(int(seg["hi"]), "MHz", 3).rsplit(fmt.NBSP, 1)[0]))
    if state == "partial" and cover:
        fields.append(QCoreApplication.translate("CwSkimView", "only {lo}–{hi} MHz is in view").format(
            lo=fmt.frequency(int(cover["lo"]), "MHz", 3).rsplit(fmt.NBSP, 1)[0],
            hi=fmt.frequency(int(cover["hi"]), "MHz", 3).rsplit(fmt.NBSP, 1)[0]))
    fields.append(QCoreApplication.translate("CwSkimView", "%n signal(s)", "", int(st.get("cwSkimSignals") or 0)))
    fields.append(QCoreApplication.translate("CwSkimView", "%n decoding", "", int(st.get("cwSkimChannels") or 0)))
    fields.append(QCoreApplication.translate("CwSkimView", "CPU {cpu:.1f} % of a core").format(
        cpu=float(st.get("cwSkimCpu") or 0.0)))
    drop = int(st.get("cwSkimDropped") or 0)
    if drop:
        fields.append(QCoreApplication.translate("CwSkimView", "%n block(s) dropped", "", drop))
    return " · ".join(fields)


class CwSkimStore(QObject):
    """The skimmer's newest picture and the spots of the last 30 minutes.

    Spots are kept by id and replaced whole when the server sends one
    again; `rev` follows the server's numbering, and a gap in it (a feed
    that overflowed) or a cwskim item naming a newer rev than any spot
    seen fetches the whole list again (`cwskim_view()`, GET api/cwskim's
    answer). A skimmer switched off and on again numbers from 1, so a rev
    going backwards starts a new run: ids are kept per run, so the new
    run's spot 1 never overwrites the old run's."""

    changed = pyqtSignal()
    spotted = pyqtSignal(dict)      # a call confirmed for the first time (valid or qsy): for the waterfall's labels

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.item: dict = {"state": "off", "channels": [], "carriers": []}
        self.spots: dict[tuple[int, int], dict] = {}
        self.texts: dict[int, str] = {}
        self.rev = 0
        self.run = 0
        self.cleared = 0.0
        try:
            self.feeds = (bridge.radio.subscribe("cwskim", 8), bridge.radio.subscribe("cwspot", 256))
        except ValueError:          # an engine with no skimmer (NB today)
            self.feeds = None
        self.refill()
        bridge.tick.connect(self.pump)

    # ------------------------------------------------------------- feeds
    def refill(self) -> None:
        view = getattr(self.bridge.radio, "cwskim_view", None)
        if view is None:
            return
        v = dict(view())
        spots = v.pop("spots", [])
        self._take_item(v)
        for s in reversed(spots):           # oldest first, as they were heard
            self._take_spot(s, announce=False)
        self.rev = max(self.rev, int(v.get("spotsRev") or 0))

    def pump(self, _dt: float = 0.0) -> None:
        if self.feeds is None:
            return
        snaps = self.feeds[0].drain()
        items = self.feeds[1].drain()
        gap = False
        for it in items:
            rev = int(it.get("rev") or 0)
            if rev < self.rev:              # the skimmer was started again
                self.run += 1
                self.rev = 0
            if self.rev and rev > self.rev + 1:
                gap = True
            self.rev = max(self.rev, rev)
            self._take_spot(it["spot"], announce=True)
        for snap in snaps:
            self._take_item(snap)
        if snaps and int(snaps[-1].get("spotsRev") or 0) > self.rev:
            gap = True
        if gap:
            self.refill()
        if snaps or items:
            self._prune()
            self.changed.emit()

    def _take_item(self, item: dict) -> None:
        self.item = item
        chans = item.get("channels") or []
        ids = set()
        for c in chans:
            ids.add(c["id"])
            self.texts[c["id"]] = merge_text(self.texts.get(c["id"], ""), c.get("text") or "")
        for k in [k for k in self.texts if k not in ids]:
            del self.texts[k]

    def _take_spot(self, s: dict, announce: bool) -> None:
        if float(s.get("last") or 0) <= self.cleared:
            return
        key = (self.run, int(s["id"]))
        was = (self.spots.get(key) or {}).get("status")
        self.spots[key] = s
        # Labelled once, when the call is first confirmed: a spot is sent
        # again with the same id as its hits grow, and an unconfirmed one
        # becomes valid under its own id.
        good = ("valid", "qsy")
        if announce and s.get("status") in good and was not in good:
            self.spotted.emit(s)

    def _prune(self) -> None:
        now = time.time()
        for k in [k for k, v in self.spots.items() if now - float(v.get("last") or 0) > KEEP_S]:
            del self.spots[k]
        if len(self.spots) > KEEP_N:
            for k, _v in sorted(self.spots.items(), key=lambda kv: kv[1].get("last") or 0)[:len(self.spots) - KEEP_N]:
                del self.spots[k]

    def clear(self) -> None:
        """The list only, as Band Activity's Clear: the server keeps what it
        keeps, and what it sends from now on is listed again."""
        self.cleared = time.time()
        self.spots.clear()
        self.changed.emit()

    # ------------------------------------------------------------- reading
    @property
    def running(self) -> bool:
        # The newest item, not the status key: an item comes every second
        # while the skimmer runs and an "off" one when it stops, and the
        # status reaches the window on the state feed a tick apart from it.
        return self.item.get("state") in ("running", "partial")

    def shown(self, order: str = "freq") -> list[dict]:
        rows = [s for s in self.spots.values() if s.get("status") != "busted"]
        if order == "new":
            return sorted(rows, key=lambda s: -(s.get("last") or 0))
        return sorted(rows, key=lambda s: s.get("f") or 0)

    def channels(self) -> list[dict]:
        return list(self.item.get("channels") or [])

    def marks(self, now: float | None = None) -> list[dict]:
        """The wide scope's marks (ScopeView.set_band_marks): each spot on
        the dial's band heard in the last ten minutes, its call as the
        caption, CQ in the FT8 labels' colour; unconfirmed ones faint."""
        if not self.running:
            return []
        now = time.time() if now is None else now
        band = self.item.get("band")
        out = []
        for s in self.shown():
            if (band and s.get("band") and s["band"] != band) or now - float(s.get("last") or 0) > MARK_S:
                continue
            f = float(s["f"])
            tip = QCoreApplication.translate("CwSkimView", "<b>{call}</b> {khz} kHz, {wpm} WPM, {snr} dB<br>"
                                                           "Click to tune").format(
                call=s["call"], khz=khz_text(f), wpm=_num(s.get("wpm")), snr=_num(s.get("snr")))
            out.append({"lo": f - MARK_HALF_HZ, "hi": f + MARK_HALF_HZ, "text": s["call"],
                        "colour": colour_of(s.get("kind")), "dial": None, "tip": tip,
                        "active": s.get("status") in ("valid", "qsy"), "spot": s})
        return out


def _num(v) -> str:
    return "" if v is None else f"{float(v):.0f}"


class CwSkimView(QWidget):
    """The view, rebuilt with the window; reads a CwSkimStore. `tune` is
    called with a frequency on the air (Hz) when the operator picks a row."""

    def __init__(self, bridge, prefs, store: CwSkimStore, tune, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.store, self.tune = bridge, prefs, store, tune
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.onoff = Toggle(self.tr("CW skimmer"), bool(bridge.st.get("cwSkim")))
        self.onoff.setToolTip(self.tr("Decode every CW signal in the band's CW segment at once, whatever the dial is "
                                      "on. Receive only."))
        self.onoff.toggled.connect(self._switched)
        self.onoff.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.onoff)
        self.tab = prefs.get("cwSkimTab", "spots")
        self.tabs = Segmented([("spots", self.tr("Spots")), ("signals", self.tr("Signals"))], self.tab, compact=True)
        self.tabs.setFixedWidth(220)
        self.tabs.picked.connect(self._tab_picked)
        top.addWidget(self.tabs)
        self.order = prefs.get("cwSkimSort", "freq")
        self.sort = Segmented([("freq", self.tr("By frequency")), ("new", self.tr("Newest"))], self.order, compact=True)
        self.sort.setFixedWidth(240)
        self.sort.picked.connect(self._sort_picked)
        top.addWidget(self.sort)
        top.addStretch(1)
        self.marks_on = Toggle(self.tr("Marks on scope"), bool(prefs.get("cwSkimMarks", True)))
        self.marks_on.setToolTip(self.tr("Mark each spotted call along the bottom of the wide scope"))
        self.marks_on.toggled.connect(self._marks_toggled)
        self.marks_on.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.marks_on)
        self.clear_btn = Button(self.tr("Clear"), small=True)
        self.clear_btn.setToolTip(self.tr("Empty this list. Nothing is sent to the radio; new spots are listed again."))
        self.clear_btn.clicked.connect(store.clear)
        top.addWidget(self.clear_btn)
        lay.addLayout(top)
        self.status = QLabel("")
        self.status.setFont(theme.font(12, mono=True))
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status)
        self.pages = QStackedWidget()
        self.spot_table = self._table([self.tr("UTC"), self.tr("kHz"), self.tr("Call"), self.tr("WPM"), self.tr("dB"),
                                       self.tr("Country"), self.tr("Tag"), self.tr("Heard")], stretch=5,
                                      tip=self.tr("Click a spot to tune to it in CW"))
        self.chan_table = self._table([self.tr("kHz"), self.tr("WPM"), self.tr("dB"), self.tr("Call"), self.tr("Text")],
                                      stretch=4, tip=self.tr("Click a signal to tune to it in CW"))
        # A channel's text grows at its end: what does not fit is cut from
        # the start, so the newest letters are the ones on screen.
        self.chan_table.setTextElideMode(Qt.TextElideMode.ElideLeft)
        self.pages.addWidget(self.spot_table)
        self.pages.addWidget(self.chan_table)
        lay.addWidget(self.pages, 1)
        self.spot_rows: list[dict] = []
        self.chan_rows: list[dict] = []
        self.spot_table.cellClicked.connect(lambda r, _c: self._picked(self.spot_rows, r))
        self.spot_table.cellActivated.connect(lambda r, _c: self._picked(self.spot_rows, r))
        self.chan_table.cellClicked.connect(lambda r, _c: self._picked(self.chan_rows, r))
        self.chan_table.cellActivated.connect(lambda r, _c: self._picked(self.chan_rows, r))
        store.changed.connect(self.refresh)
        bridge.changed.connect(self._state_changed)
        self._show_tab()
        self.refresh()

    def _table(self, heads: list[str], stretch: int, tip: str) -> QTableWidget:
        t = QTableWidget(0, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = t.horizontalHeader()
        for i in range(len(heads)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == stretch
                                    else QHeaderView.ResizeMode.ResizeToContents)
        t.setToolTip(tip)
        t.setFont(theme.font(12.5))
        return t

    def detach(self):
        for sig, slot in ((self.store.changed, self.refresh), (self.bridge.changed, self._state_changed)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    # ------------------------------------------------------------ controls
    def _switched(self, on: bool):
        if not self.bridge.set(cwSkim=bool(on)):
            self.onoff.set_on(bool(self.bridge.st.get("cwSkim")))

    def _tab_picked(self, v: str):
        self.tab = self.prefs["cwSkimTab"] = v
        self._show_tab()
        self.refresh()

    def _show_tab(self):
        self.pages.setCurrentIndex(0 if self.tab == "spots" else 1)
        self.sort.setVisible(self.tab == "spots")

    def _sort_picked(self, v: str):
        self.order = self.prefs["cwSkimSort"] = v
        self.refresh()

    def _marks_toggled(self, on: bool):
        self.prefs["cwSkimMarks"] = bool(on)
        self.store.changed.emit()

    def _picked(self, rows: list[dict], r: int):
        if 0 <= r < len(rows) and rows[r].get("f"):
            self.tune(float(rows[r]["f"]))

    def _state_changed(self, ch: dict):
        if "cwSkim" in ch:
            self.onoff.set_on(bool(self.bridge.st.get("cwSkim")))
        if any(k.startswith("cwSkim") for k in ch):
            self._update_status()

    # ------------------------------------------------------------ the lists
    def refresh(self):
        if self.tab == "spots":
            self._fill_spots()
        else:
            self._fill_channels()
        self._update_status()

    @staticmethod
    def _cell(t: QTableWidget, r: int, c: int, text: str) -> QTableWidgetItem:
        it = t.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            t.setItem(r, c, it)
        it.setText(text)
        return it

    def _fill_spots(self):
        t = self.spot_table
        rows = self.store.shown(self.order)
        keep = self._selected_key(t, self.spot_rows, lambda s: (s.get("call"), s.get("id")))
        self.spot_rows = rows
        t.setRowCount(len(rows))
        now = time.time()
        text, dim = QColor(theme.c("text")), theme.c("text3")
        for r, s in enumerate(rows):
            confirmed = s.get("status") in ("valid", "qsy")
            tag = tag_text(s.get("kind")) + ("" if confirmed else " ?")
            cells = [utc_text(s.get("last") or 0), khz_text(s["f"]), s.get("call", ""), _num(s.get("wpm")),
                     _num(s.get("snr")), s.get("country") or "", tag.strip(), age_text(s.get("last") or 0, now)]
            for c, v in enumerate(cells):
                it = self._cell(t, r, c, v)
                if c in (1, 2):
                    it.setFont(theme.font(12.5, theme.QFont.Weight.DemiBold if c == 2 else theme.QFont.Weight.Normal,
                                          mono=True))
                if not confirmed:
                    it.setForeground(dim)
                elif c in (2, 6):
                    it.setForeground(theme.sc(colour_of(s.get("kind"))))
                else:
                    it.setForeground(text)
            t.item(r, 2).setToolTip(self.tr("{call}: {hits} decodes, {status}").format(
                call=s.get("call", ""), hits=int(s.get("hits") or 0), status=s.get("status", "")))
        self._reselect(t, rows, keep, lambda s: (s.get("call"), s.get("id")))

    def _fill_channels(self):
        t = self.chan_table
        rows = self.store.channels()
        keep = self._selected_key(t, self.chan_rows, lambda c: c.get("id"))
        self.chan_rows = rows
        t.setRowCount(len(rows))
        text, dim = QColor(theme.c("text")), theme.c("text3")
        for r, ch in enumerate(rows):
            line = self.store.texts.get(ch["id"], ch.get("text") or "")
            cells = [khz_text(ch["f"]), _num(ch.get("wpm")), _num(ch.get("snr")), ch.get("call") or "",
                     line.strip()[-120:]]
            for c, v in enumerate(cells):
                it = self._cell(t, r, c, v)
                if c in (0, 4):
                    it.setFont(theme.font(12.5, mono=True))
                if not ch.get("active", True) or not ch.get("decoding", True):
                    it.setForeground(dim)
                elif c == 3:
                    it.setForeground(theme.sc(colour_of(ch.get("kind"))))
                else:
                    it.setForeground(text)
        self._reselect(t, rows, keep, lambda c: c.get("id"))

    @staticmethod
    def _selected_key(t, rows, key):
        sel = t.currentRow()
        return key(rows[sel]) if 0 <= sel < len(rows) else None

    @staticmethod
    def _reselect(t, rows, keep, key):
        if keep is None:
            return
        idx = next((i for i, x in enumerate(rows) if key(x) == keep), -1)
        if idx >= 0:
            t.selectRow(idx)

    def _update_status(self):
        self.status.setText(status_text(self.bridge.st, self.store.item))


__all__ = ["CwSkimStore", "CwSkimView", "merge_text", "khz_text", "status_text"]
