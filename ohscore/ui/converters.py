"""The Converters settings page's list and editor, shared by both apps.

Modelled on SDR Console's Converter Definitions window, which Brian asked
for on 07/10/2026: a list with Title / Up-Dn / RX-TX / RX offset / TX
offset columns; Add, Copy, Edit, Delete and up/down ordering; buttons that
append a preset pack; an edit form with an example line ("144-146 MHz on
air appears at 28-30 MHz on the radio") and help text. The definitions
themselves, their maths and their presets are ohscore/converters.py.

The editor works on a copy of the list and changes nothing until the
dialog's Save, which sends the whole list in the same set() as everything
else on every page - so a list the engine refuses (two titles alike, a
converter the LNB choice cannot use) costs nothing. Offsets are shown in
Hz with separators, as SDR Console shows them, and typed in MHz, as every
other frequency in Settings is typed.

What the app adds: which preset packs it offers, which air ranges an
example is worked out on (NB: the downlink and the uplink; HAM: its
bands), whether a transmitting definition must give its most drive (HAM,
which drives transverters; NB never sets the IC-9700's power), and which
definitions are in use (a used one cannot be deleted, and a rename is
followed by whatever chose it).
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import converters as cv
from . import theme
from .controls import Button, Segmented, Toggle

# The table's headings; translated where they are set (ConverterEditor).
COLUMNS = ["Title", "Up/Dn", "RX/TX", "RX offset (Hz)", "TX offset (Hz)"]


def hz_text(v: float) -> str:
    return f"{v:,.0f}"


def mhz_text(v: float | None) -> str:
    return "" if v is None else f"{v / 1e6:.6f}".rstrip("0").rstrip(".")


class ConverterEditor(QWidget):
    """The list, its buttons and the edit form. `value()` is the list as
    edited. `in_use(title)` is the app's: '' or the sentence saying what
    uses it. `ranges` are (lo, hi) on-air ranges to show the example on."""

    changed = pyqtSignal()              # the list changed
    renamed = pyqtSignal(str, str)      # (old title, new title)

    def __init__(self, value: list, packs=("vhf",), ranges=(), drive_required: bool = False,
                 in_use=lambda title: "", parent=None):
        super().__init__(parent)
        self.items: list[dict] = [dict(d) for d in (value or [])]
        self.ranges = list(ranges)
        self.drive_required = drive_required
        self.in_use = in_use
        self.editing: int | None = None          # row being edited; None: a new one
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([self.tr("Title"), self.tr("Up/Dn"), self.tr("RX/TX"),
                                              self.tr("RX offset (Hz)"), self.tr("TX offset (Hz)")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(200)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.edit())
        lay.addWidget(self.table)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.buttons = {}
        for key, text, icon, fn in [("add", self.tr("Add"), "plus", self.add), ("copy", self.tr("Copy"), "", self.copy),
                                    ("edit", self.tr("Edit"), "", self.edit),
                                    ("delete", self.tr("Delete"), "trash", self.delete),
                                    ("up", self.tr("Up"), "", lambda: self.move(-1)),
                                    ("down", self.tr("Down"), "", lambda: self.move(1))]:
            b = Button(text, icon=icon, small=True)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        for key in packs:
            name, _pack = cv.PACKS[key]
            b = Button(f"+ {name}", small=True)
            b.setToolTip(self.tr("Add SDR Console-style {name} presets (any already in the list are left as they "
                                 "are)").format(name=name))
            b.clicked.connect(lambda k=key: self.add_pack(k))
            row.addWidget(b)
            self.buttons[f"pack:{key}"] = b
        lay.addLayout(row)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setStyleSheet(f"color: {theme.t()['err']};")
        self.note.hide()
        lay.addWidget(self.note)

        self.form = self._build_form()
        self.form.hide()
        lay.addWidget(self.form)

        h = QLabel(self.tr(
            "A converter sits between the radio and the air. A down-converter puts the air frequency lower on the "
            "radio: a 144 MHz transverter feeding an HF radio brings 144-146 MHz out as 28-30 MHz, 116 MHz lower, so "
            "its offset is 116 MHz. An up-converter puts it higher: an HF upconverter feeding a VHF-only SDR brings "
            "1-30 MHz in as 126-155 MHz with a 125 MHz offset. RX only is for something that only receives (an LNB, "
            "an upconverter); RX/TX for a transverter, used both ways with its own TX offset; TX only for something "
            "only transmitted through, such as an uplink upconverter when another radio receives. A TX only "
            "converter is named by what it does on transmit, so one fed from below the air frequency is an "
            "up-converter. Inverted is for a high-side local oscillator: the radio sits at offset minus air, the "
            "spectrum is mirrored - USB becomes LSB and the dial runs backwards - and OpenHamShack converts both "
            "ways. Most drive is the most power the converter's input takes, from its manual: transverters typically "
            "want 0 dBm or less, and a radio's full power destroys them."))
        h.setWordWrap(True)
        h.setObjectName("Faint")
        h.setFont(theme.font(12))
        lay.addWidget(h)
        self._fill()

    # ------------------------------------------------------------ the list
    def value(self) -> list[dict]:
        return [dict(d) for d in self.items]

    def titles(self) -> list[str]:
        return [d["title"] for d in self.items]

    def current(self) -> int | None:
        r = self.table.currentRow()
        return r if 0 <= r < len(self.items) else None

    def _fill(self, select: int | None = None):
        self.table.setRowCount(len(self.items))
        for i, d in enumerate(self.items):
            c = cv.Converter.from_dict(d)
            typ = (self.tr("{type}, inverted").format(type=cv.TYPE_NAMES[c.kind()]) if c.inverted
                   else cv.TYPE_NAMES[c.kind()])
            for j, text in enumerate([c.title, typ, cv.USE_NAMES[c.use], hz_text(c.rx_offset) if c.receives else "",
                                      hz_text(c.tx_offset) if c.transmits else ""]):
                it = QTableWidgetItem(text)
                if j >= 3:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, j, it)
        if select is not None and 0 <= select < len(self.items):
            self.table.selectRow(select)

    def _say(self, text: str):
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _changed(self, select: int | None = None):
        self._fill(select)
        self.changed.emit()

    def add(self):
        self.editing = None
        self._load_form(None)

    def copy(self):
        i = self.current()
        if i is None:
            self._say(self.tr("Choose a converter to copy"))
            return
        d = dict(self.items[i])
        d["title"] = cv.unique_title(self.items, d["title"])
        self.items.insert(i + 1, d)
        self._say("")
        self._changed(i + 1)

    def edit(self):
        i = self.current()
        if i is None:
            self._say(self.tr("Choose a converter to edit"))
            return
        self.editing = i
        self._load_form(self.items[i])

    def delete(self):
        i = self.current()
        if i is None:
            self._say(self.tr("Choose a converter to delete"))
            return
        why = self.in_use(self.items[i]["title"])
        if why:
            self._say(self.tr("{title} is in use ({why}): choose another there first").format(
                title=self.items[i]['title'], why=why))
            return
        del self.items[i]
        self._say("")
        self._changed(min(i, len(self.items) - 1))

    def move(self, d: int):
        i = self.current()
        if i is None or not 0 <= i + d < len(self.items):
            return
        self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
        self._changed(i + d)

    def add_pack(self, key: str):
        before = len(self.items)
        self.items = cv.add_pack(self.items, cv.PACKS[key][1])
        self._say("" if len(self.items) > before else
                  self.tr("The {name} presets are all in the list already").format(name=cv.PACKS[key][0]))
        self._changed(before if len(self.items) > before else None)

    # ------------------------------------------------------------ the form
    def _build_form(self) -> QWidget:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.StyledPanel)
        g = QGridLayout(f)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)

        def cap(text, r, c):
            lab = QLabel(text)
            lab.setObjectName("Muted")
            g.addWidget(lab, r, c)

        self.f_title = QLineEdit()
        self.f_title.setPlaceholderText(self.tr("e.g. 1296 MHz (144 MHz IF)"))
        self.f_type = Segmented(self._type_options(cv.RX), "down")
        self.f_use = Segmented([(u, cv.USE_NAMES[u]) for u in (cv.RX, cv.TX, cv.RXTX)], "rx")
        self.f_rx = QLineEdit()
        self.f_rx.setPlaceholderText(self.tr("MHz, e.g. 1152"))
        self.f_tx = QLineEdit()
        self.f_tx.setPlaceholderText(self.tr("MHz; empty: the RX offset"))
        self.f_inv = Toggle(self.tr("Inverted (high-side LO: the spectrum is mirrored)"), False)
        self.f_drive = QLineEdit()
        self.f_drive.setPlaceholderText(self.tr("dBm, from its manual, e.g. 0"))
        cap(self.tr("Title"), 0, 0)
        g.addWidget(self.f_title, 0, 1, 1, 3)
        cap(self.tr("Type"), 1, 0)
        g.addWidget(self.f_type, 1, 1)
        cap(self.tr("Use"), 1, 2)
        g.addWidget(self.f_use, 1, 3)
        cap(self.tr("RX offset (MHz)"), 2, 0)
        g.addWidget(self.f_rx, 2, 1)
        cap(self.tr("TX offset (MHz)"), 2, 2)
        g.addWidget(self.f_tx, 2, 3)
        g.addWidget(self.f_inv, 3, 0, 1, 2)
        self.drive_cap = QLabel(self.tr("Most drive (dBm)"))
        self.drive_cap.setObjectName("Muted")
        g.addWidget(self.drive_cap, 3, 2)
        g.addWidget(self.f_drive, 3, 3)
        self.example = QLabel("")
        self.example.setWordWrap(True)
        self.example.setTextFormat(Qt.TextFormat.PlainText)
        g.addWidget(self.example, 4, 0, 1, 4)
        self.f_error = QLabel("")
        self.f_error.setWordWrap(True)
        self.f_error.setTextFormat(Qt.TextFormat.PlainText)
        self.f_error.setStyleSheet(f"color: {theme.t()['err']};")
        self.f_error.hide()
        g.addWidget(self.f_error, 5, 0, 1, 4)
        r = QHBoxLayout()
        r.addStretch(1)
        cancel = Button(self.tr("Cancel"), kind="ghost", small=True)
        cancel.clicked.connect(self.form_cancel)
        ok = Button(self.tr("OK"), kind="primary", small=True)
        ok.clicked.connect(self.form_ok)
        self.form_buttons = {"ok": ok, "cancel": cancel}
        r.addWidget(cancel)
        r.addWidget(ok)
        g.addLayout(r, 6, 0, 1, 4)
        for w in (self.f_title, self.f_rx, self.f_tx, self.f_drive):
            w.textChanged.connect(self._preview)
        self.f_type.picked.connect(lambda _v: self._preview())
        self.f_use.picked.connect(lambda _v: self._preview())
        self.f_inv.toggled.connect(lambda _v: self._preview())
        return f

    def _load_form(self, d: dict | None):
        c = cv.Converter.from_dict(d) if d else None
        self.f_title.setText(c.title if c else "")
        self.f_type.set_value(c.type if c else cv.DOWN, animate=False)
        self.f_use.set_value(c.use if c else cv.RX, animate=False)
        self.f_rx.setText(mhz_text(c.rx_offset) if c and c.receives else "")
        self.f_tx.setText(mhz_text(c.tx_offset) if c and (c.use == cv.TX or c.tx_offset != c.rx_offset) else "")
        self.f_inv.set_on(bool(c and c.inverted))
        self.f_drive.setText("" if c is None or c.max_drive_dbm is None else f"{c.max_drive_dbm:g}")
        self.f_error.hide()
        self._say("")
        self.form.show()
        self.f_title.setFocus()
        self._preview()

    def _form_dict(self) -> dict:
        """The form as a stored definition; ValueError with a sentence."""
        # `bad` is the whole sentence for each box, not a field name put
        # into a shared one, so each translates with its own grammar.
        def mhz(text, bad):
            t = text.strip().replace(",", ".")
            try:
                return float(t) * 1e6
            except ValueError:
                raise ValueError(bad) from None
        use = self.f_use.value
        tx_bad = self.tr("TX offset: a frequency in MHz")
        if use == cv.TX:
            # The RX offset box is greyed and whatever it holds is ignored:
            # nothing is received through this converter.
            rx = tx = mhz(self.f_tx.text(), tx_bad)
        else:
            rx = mhz(self.f_rx.text(), self.tr("RX offset: a frequency in MHz"))
            tx = mhz(self.f_tx.text(), tx_bad) if self.f_tx.text().strip() else rx
        drive = None
        if self.f_drive.text().strip():
            try:
                drive = float(self.f_drive.text().strip().replace(",", "."))
            except ValueError:
                raise ValueError(self.tr("Most drive: a number of dBm")) from None
        d = {"title": self.f_title.text().strip(), "type": self.f_type.value, "use": use, "rxOffset": rx,
             "txOffset": tx, "inverted": self.f_inv.on, "maxDriveDbm": drive}
        return cv.Converter.from_dict(d).to_dict()

    def _example(self, c: cv.Converter) -> str:
        # Ranges are (lo, hi, "rx" | "tx" | "both"). A transmitting
        # converter is shown on a transmit range first (NB's uplink
        # upconverter on the uplink, not on the downlink it would also
        # reach), a receive-only one never on one, a transmit-only one only
        # on one (or on HAM's bands, which are both) and worked out for
        # transmit, with its TX offset.
        tx_first = [r for r in self.ranges if r[2] == "tx"] + [r for r in self.ranges if r[2] != "tx"]
        order = {cv.RX: [r for r in self.ranges if r[2] != "tx"], cv.RXTX: tx_first,
                 cv.TX: [r for r in self.ranges if r[2] != "rx"]}[c.use]
        for lo, hi, kind in order:
            tx = kind == "tx" or c.use == cv.TX
            if not c.check(lo, hi, tx):
                return c.example(lo, hi, tx)
        how = {(cv.DOWN, False): self.tr("on air = radio + {o}"), (cv.UP, False): self.tr("on air = radio - {o}")}.get(
            (c.type, c.inverted), self.tr("on air = {o} - radio (inverted: USB becomes LSB)"))
        return how.format(o=f"{c.offset(c.use == cv.TX) / 1e6:g} MHz")

    @staticmethod
    def _type_options(use: str) -> list[tuple[str, str]]:
        """The Type buttons for a use. The stored value is where the radio
        sits (down: below the air) and keeps its place; the name is what a
        converter with it is called (Converter.kind): the receive
        direction's, and for TX only the transmit direction's, so the
        QO-100 uplink upconverter - radio below the air - is the
        "Up-converter" it is sold as, not the "Down-converter" it read as
        while every converter was named for receive (Brian, 07/10/2026)."""
        names = {cv.DOWN: QCoreApplication.translate("ConverterEditor", "Down-converter"),
                 cv.UP: QCoreApplication.translate("ConverterEditor", "Up-converter")}
        return [(t, names[cv.Converter("x", t, use, 1.0, 1.0).kind()]) for t in (cv.DOWN, cv.UP)]

    def _preview(self):
        use = self.f_use.value
        transmits = use != cv.RX
        self.f_rx.setEnabled(use != cv.TX)
        self.f_tx.setEnabled(transmits)
        self.f_tx.setPlaceholderText(self.tr("MHz, e.g. 1104") if use == cv.TX
                                     else self.tr("MHz; empty: the RX offset"))
        self.f_drive.setEnabled(transmits)
        # Two whole captions rather than ", required" appended.
        self.drive_cap.setText(self.tr("Most drive (dBm), required") if transmits and self.drive_required
                               else self.tr("Most drive (dBm)"))
        opts = self._type_options(use)
        if opts != self.f_type.options:
            self.f_type.options = opts
            self.f_type.update()
        try:
            c = cv.Converter.from_dict(self._form_dict())
        except ValueError:
            self.example.setText("")
            return
        self.example.setText(self._example(c))

    def form_ok(self) -> bool:
        try:
            d = self._form_dict()
        except ValueError as e:
            return self._form_error(str(e))
        if d["use"] != cv.RX and d["maxDriveDbm"] is None and self.drive_required:
            return self._form_error(self.tr("Most drive: enter it from the converter's manual. It is the one number "
                                            "here that, wrong, destroys hardware - so it is never guessed"))
        others = [t for j, t in enumerate(self.titles()) if j != self.editing]
        if d["title"].casefold() in (t.casefold() for t in others):
            return self._form_error(self.tr("There is already a converter called {title}").format(title=d['title']))
        if self.editing is None:
            self.items.append(d)
            at = len(self.items) - 1
        else:
            at = self.editing
            old = self.items[at]["title"]
            self.items[at] = d
            if old != d["title"]:
                self.renamed.emit(old, d["title"])
        self.form.hide()
        self.editing = None
        self._changed(at)
        return True

    def _form_error(self, text: str) -> bool:
        self.f_error.setText(text)
        self.f_error.show()
        return False

    def form_cancel(self):
        self.form.hide()
        self.editing = None
