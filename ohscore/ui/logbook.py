"""The logbook and the memories, as two views in the lower panel."""
from __future__ import annotations

import time
from urllib.parse import quote

from PyQt6.QtCore import QCoreApplication, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                             QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QWidget)

from .. import callsign
from . import theme
from .controls import Button, Card
from .rail import MODE_LABELS


def columns(freq_key: str, freq_label: str) -> list[tuple[str, str]]:
    """The log table's (record key, heading) columns; the frequency is the
    app's (NB: "dl", "Downlink")."""
    return [("t", QCoreApplication.translate("LogView", "UTC")),
            ("call", QCoreApplication.translate("LogView", "Call")),
            ("mode", QCoreApplication.translate("LogView", "Mode")), (freq_key, freq_label),
            ("rstSent", QCoreApplication.translate("LogView", "Sent")),
            ("rstRcvd", QCoreApplication.translate("LogView", "Rcvd")),
            ("name", QCoreApplication.translate("LogView", "Name")),
            ("grid", QCoreApplication.translate("LogView", "Grid")),
            ("comment", QCoreApplication.translate("LogView", "Comment"))]


def qrz_call(call: str) -> str:
    """The callsign QRZ.com files a logged call under. A portable or
    foreign-licence call (G4ABC/P, EA8/G4ABC, G4ABC/MM) is listed under the
    station's own call: ohscore/callsign.py's home call. Something that is
    not a callsign by that rule falls back to its longest part holding a
    digit, as before the shared rule, so an odd logged call still links."""
    p = callsign.parts(call)
    if p is not None:
        return p.home
    parts = [p for p in call.strip().upper().split("/") if p]
    calls = [p for p in parts if any(ch.isdigit() for ch in p) and any(ch.isalpha() for ch in p)]
    return max(calls or parts or [""], key=len)


def qrz_url(call: str) -> str:
    return "https://www.qrz.com/db/" + quote(qrz_call(call), safe="")


class LogView(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.fkey = bridge.radio.FREQ_KEY
        self.cols = columns(self.fkey, bridge.face.freq_label)
        self.loading = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        card = Card(self.tr("Logbook"))
        self.count = QLabel("")
        self.count.setObjectName("Faint")
        card.set_header_widget(self.count)
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c[1] for c in self.cols])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setFont(theme.font(13, mono=True))
        self.table.verticalHeader().setDefaultSectionSize(26)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(self.cols) - 1, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemChanged.connect(self._edited)
        # A click on a call opens its QRZ.com page, but a double-click still
        # edits the cell as every other one does. The first click of a
        # double-click arrives as a click too, so the page is opened only
        # once the double-click interval has passed without a second one -
        # otherwise correcting a misheard call would also open a browser.
        self.call_col = next(j for j, (k, _) in enumerate(self.cols) if k == "call")
        self._qrz_row = None
        self._qrz_timer = QTimer(self)
        self._qrz_timer.setSingleShot(True)
        self._qrz_timer.timeout.connect(self._open_qrz)
        self.table.cellClicked.connect(self._clicked)
        self.table.cellDoubleClicked.connect(lambda *_: self._qrz_timer.stop())
        card.lay.addWidget(self.table, 1)
        bar = QHBoxLayout()
        exp = Button(self.tr("Export ADIF"), icon="export")
        exp.clicked.connect(self.export)
        dele = Button(self.tr("Delete"), icon="trash", kind="ghost")
        dele.clicked.connect(self.delete)
        hint = QLabel(self.tr("Click a call to open it on QRZ.com. Double-click a cell to edit it."))
        hint.setObjectName("Faint")
        bar.addWidget(exp)
        bar.addWidget(dele)
        bar.addSpacing(12)
        bar.addWidget(hint)
        bar.addStretch(1)
        card.lay.addLayout(bar)
        lay.addWidget(card, 5)

        add = Card(self.tr("Log a QSO"))
        self.fields = {}
        for key, label in (("call", self.tr("Call")), ("rstSent", self.tr("Report sent")),
                           ("rstRcvd", self.tr("Report received")), ("name", self.tr("Name")),
                           ("grid", self.tr("Grid")), ("comment", self.tr("Comment"))):
            e = QLineEdit()
            e.setPlaceholderText(label)
            if key == "call":
                e.setFont(theme.font(15, theme.QFont.Weight.Bold, mono=True))
            e.returnPressed.connect(self.add)
            self.fields[key] = e
            add.lay.addWidget(e)
        note = QLabel(self.tr("Frequency and mode are taken from the radio."))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        add.lay.addWidget(note)
        b = Button(self.tr("Log"), icon="plus", kind="primary")
        b.clicked.connect(self.add)
        add.lay.addWidget(b)
        add.lay.addStretch(1)
        lay.addWidget(add, 2)
        self.reload()

    def reload(self):
        self.loading = True
        rows = self.bridge.radio.log_entries()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, (k, _) in enumerate(self.cols):
                v = r.get(k, "")
                if k == "t":
                    v = time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(v)))
                elif k == self.fkey:
                    v = f"{float(v) / 1e6:.4f}"
                elif k == "mode":
                    v = MODE_LABELS.get(v, str(v))
                it = QTableWidgetItem(str(v))
                if k in ("t", self.fkey, "mode"):
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    it.setForeground(theme.c("text2"))
                if k == "call" and str(v).strip():
                    it.setForeground(theme.c("accent"))
                    f = it.font()
                    f.setUnderline(True)
                    it.setFont(f)
                    it.setToolTip(self.tr("Open {call} on QRZ.com (double-click to edit)").format(
                        call=qrz_call(str(v))))
                self.table.setItem(i, j, it)
        self.table.scrollToBottom()
        self.count.setText(self.tr("%n QSO(s)", "", len(rows)))
        self.loading = False

    def _clicked(self, row: int, col: int):
        if col != self.call_col:
            return
        self._qrz_row = row
        self._qrz_timer.start(QApplication.styleHints().mouseDoubleClickInterval())

    def _open_qrz(self):
        it = self.table.item(self._qrz_row, self.call_col) if self._qrz_row is not None else None
        if it is None or not it.text().strip():
            return
        url = qrz_url(it.text())
        if not QDesktopServices.openUrl(QUrl(url)):
            self.bridge.say(self.tr("No web browser opened {url}").format(url=url))

    def _edited(self, it: QTableWidgetItem):
        if self.loading:
            return
        key = self.cols[it.column()][0]
        try:
            self.bridge.radio.edit_qso(it.row(), **{key: it.text()})
        except ValueError as e:
            self.bridge.say(str(e))
            self.reload()

    def add(self):
        call = self.fields["call"].text().strip()
        if not call:
            self.fields["call"].setFocus()
            return
        try:
            self.bridge.radio.log_qso(call, **{k: e.text().strip() for k, e in self.fields.items() if k != "call"})
        except ValueError as e:
            self.bridge.say(str(e))
            return
        for e in self.fields.values():
            e.clear()
        self.reload()
        self.bridge.say(self.tr("Logged {call}").format(call=call.upper()), "info")

    def delete(self):
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        for r in rows:
            try:
                self.bridge.radio.delete_qso(r)
            except ValueError:
                pass
        self.reload()

    def export(self):
        default = str(self.bridge.radio.data_dir / "log.adi")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export ADIF"), default, self.tr("ADIF (*.adi *.adif)"))
        if not path:
            return
        p = self.bridge.radio.export_adif(path)
        self.bridge.say(self.tr("Exported %n QSO(s) to {path}", "", self.table.rowCount()).format(path=p), "info")


class MemoriesView(QWidget):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.COLS = ["", self.tr("Name"), bridge.face.freq_label, self.tr("Mode"), self.tr("Segment")]
        self.rows: list[dict] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        card = Card(self.tr("Memories"))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFont(theme.font(13.5))
        self.table.verticalHeader().setDefaultSectionSize(27)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(self.COLS) - 1, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.cellClicked.connect(lambda r, _c: self.recall_index(r))
        self.table.cellActivated.connect(lambda r, _c: self.recall_index(r))
        card.lay.addWidget(self.table, 1)
        bar = QHBoxLayout()
        save = Button(self.tr("Save current"), icon="star", kind="primary")
        save.clicked.connect(self.save)
        dele = Button(self.tr("Delete"), icon="trash", kind="ghost")
        dele.clicked.connect(self.delete)
        hint = QLabel(self.tr("Click to tune. Alt+1 … Alt+9 recall the first nine from anywhere."))
        hint.setObjectName("Faint")
        bar.addWidget(save)
        bar.addWidget(dele)
        bar.addSpacing(12)
        bar.addWidget(hint)
        bar.addStretch(1)
        card.lay.addLayout(bar)
        lay.addWidget(card)
        self.reload()

    def reload(self):
        self.rows = self.bridge.radio.memories()
        self.table.setRowCount(len(self.rows))
        for i, m in enumerate(self.rows):
            f = m[self.bridge.radio.FREQ_KEY]
            seg = self.bridge.face.segment_at(f)
            cells = [f"Alt+{i + 1}" if i < 9 else "", m["name"], f"{f / 1e6:.4f}",
                     MODE_LABELS.get(m["mode"], m["mode"]), seg["label"] if seg else ""]
            for j, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if j in (0, 2):
                    it.setFont(theme.font(13, mono=True))
                if j == 0 or j == 4:
                    it.setForeground(theme.c("text3"))
                elif not m.get("builtin"):
                    it.setForeground(theme.c("accent"))
                self.table.setItem(i, j, it)

    def recall_index(self, i: int):
        if not 0 <= i < len(self.rows):
            return
        try:
            self.bridge.radio.recall(self.rows[i]["name"])
        except ValueError as e:
            self.bridge.say(str(e))

    def save(self):
        name, ok = QInputDialog.getText(self, self.tr("Save memory"), self.tr("Name for this frequency and mode:"))
        if ok and name.strip():
            try:
                self.bridge.radio.save_memory(name.strip())
            except ValueError as e:
                self.bridge.say(str(e))
            self.reload()

    def delete(self):
        i = self.table.currentRow()
        if not 0 <= i < len(self.rows):
            return
        m = self.rows[i]
        if m.get("builtin"):
            self.bridge.say(self.tr("Built-in memories cannot be deleted"), "info")
            return
        try:
            self.bridge.radio.delete_memory(m["name"])
        except ValueError as e:
            self.bridge.say(str(e))
        self.reload()
