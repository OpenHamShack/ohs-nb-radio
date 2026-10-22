"""Where the station is and whose licence it transmits under: the Settings
controls both apps share (ohscore/countries.py, ohscore/licences).

Until 08/10/2026 Settings offered one licence (Ofcom's) and its three
classes as fixed choices. Now:

- the station's country follows the callsign unless the operator picks
  one, and the line under it says what that gives (country, regulator,
  ITU region, the licence written for it - or that none is);
- the licence follows the country ("auto") unless the operator picks a
  written one or enters their own;
- the class picker offers the classes of the licence that will be in
  force, worked out from what is on the page now, not what was saved -
  so changing the callsign and the class in one visit works;
- the licence's own station questions (CONDITIONS: near an excluded area,
  holding a separate permit) appear as toggles;
- "My own licence" opens an editor for the segments and power limits of a
  country not written into OpenHamShack (the customLicence setting), so an
  operator anywhere can transmit within their own licence's terms rather
  than not at all.

Nothing here decides anything: every value goes to the engine in the
dialog's one set(), where the registry's validators (licences.clean_custom,
clean_conditions) refuse what is unsound, with their own sentence.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import countries, licences
from . import theme
from .controls import Button, Segmented, Toggle


class FieldError(ValueError):
    """A ValueError whose sentence the dialog shows as it is (not as "not a
    number")."""


class Value:
    """What the dialog's collect() needs of a field: get(), and the widget
    as `w` for tests that drive it."""

    def __init__(self, get, w=None):
        self.get, self.w = get, w


# Whole sentences: they will be translated whole (docs/ham/adding-a-country.md).
AUTO_FROM_CALL = "From the callsign"
STATION_FROM = "{entity}: IARU Region {region}. {licence}"
STATION_NOTHING = "No callsign yet: set one, or choose the country."
LICENCE_WRITTEN = "Licence written into OpenHamShack: {short}."
LICENCE_NONE = ("No licence for {entity} is written into OpenHamShack yet: choose one below, or enter your own "
                "licence's segments.")
FOLLOW = "Follow the station's country"
FOLLOW_NAMED = "Follow the station's country ({short})"
OWN = "My own licence (enter it below)"
NO_CLASS_HERE = "Choose a licence above, or enter your own: there are no classes to choose from yet."
CUSTOM_HELP = ("Your own licence, for a country whose rules are not written into OpenHamShack: one row per segment "
               "your licence allows, with its most power and how that power is measured (PEP at the "
               "transmitter, mean, carrier, ERP or EIRP - ERP and EIRP are worked out from the antenna gain on "
               "Bands & power). Tick Satellite where your licence allows the amateur-satellite service: OpenHamShack QO-100 NB "
               "transmits to QO-100 (2400.050-2400.300 MHz) only inside such a segment. Outside every segment, "
               "transmit is refused.")
COLUMNS = ["From (MHz)", "To (MHz)", "Most power (W)", "Measured as", "Satellite", "Note"]


def _mhz(v: float) -> str:
    return f"{v / 1e6:.6f}".rstrip("0").rstrip(".")


class CustomLicenceEditor(QWidget):
    """The customLicence setting as an editable table. value() is the list
    of segments, or FieldError with the sentence clean_custom gives."""

    changed = pyqtSignal()

    def __init__(self, value: list, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(180)
        hh = self.table.horizontalHeader()
        for i in range(len(COLUMNS) - 1):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.add_btn = Button(self.tr("Add segment"), icon="plus", small=True)
        self.add_btn.clicked.connect(lambda: self.add_row())
        self.del_btn = Button(self.tr("Delete"), icon="trash", small=True)
        self.del_btn.clicked.connect(self.delete_row)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        lay.addLayout(row)
        h = QLabel(CUSTOM_HELP)
        h.setWordWrap(True)
        h.setObjectName("Faint")
        h.setFont(theme.font(12))
        lay.addWidget(h)
        for seg in value or []:
            self.add_row(seg)

    def add_row(self, seg: dict | None = None) -> int:
        seg = seg or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, key in ((0, "lo"), (1, "hi")):
            self.table.setItem(r, c, QTableWidgetItem(_mhz(seg[key]) if key in seg else ""))
        self.table.setItem(r, 2, QTableWidgetItem(f"{seg['watts']:g}" if "watts" in seg else ""))
        unit = QComboBox()
        for u in licences.UNITS:
            unit.addItem(u, u)
        unit.setCurrentIndex(max(0, unit.findData(seg.get("unit", "PEP"))))
        self.table.setCellWidget(r, 3, unit)
        sat = QCheckBox()
        sat.setChecked(bool(seg.get("satellite", False)))
        self.table.setCellWidget(r, 4, sat)
        self.table.setItem(r, 5, QTableWidgetItem(seg.get("note", "")))
        self.changed.emit()
        return r

    def delete_row(self):
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self.changed.emit()

    def set_cell(self, r: int, c: int, text: str):
        """Type into a text cell (for tests and the Add flow)."""
        self.table.item(r, c).setText(text)

    def value(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            def text(c):
                it = self.table.item(r, c)
                return it.text().strip().replace(",", ".") if it is not None else ""
            if not any(text(c) for c in (0, 1, 2)):
                continue                       # an empty row just added: not a segment
            try:
                lo, hi, w = float(text(0)) * 1e6, float(text(1)) * 1e6, float(text(2))
            except ValueError:
                raise FieldError(f"Your own licence, row {r + 1}: give the lower and upper edges in MHz and the "
                                 f"most power in watts, as numbers") from None
            out.append({"lo": lo, "hi": hi, "watts": w, "unit": self.table.cellWidget(r, 3).currentData(),
                        "satellite": self.table.cellWidget(r, 4).isChecked(), "note": text(5)})
        try:
            return licences.clean_custom(out)
        except ValueError as e:
            raise FieldError(str(e)) from None


class LicencePanel(QWidget):
    """The licence choice, the class, the station questions and the
    operator's own licence. `dialog` is the Settings dialog: its `st`,
    `spec` and - when the Station page is built first - the callsign field
    and country combo, whose current text decides the licence "auto"
    means."""

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.d = dialog
        st = dialog.st
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        cap = QLabel(self.tr("Licence"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        self.licence = QComboBox()
        self.licence.addItem(FOLLOW, licences.AUTO)
        for rid, reg in sorted(licences.REGIMES.items(), key=lambda kv: kv[1].SHORT.lower()):
            self.licence.addItem(reg.SHORT, rid)
        self.licence.addItem(OWN, licences.CUSTOM)
        i = self.licence.findData(st.get("licence") or licences.AUTO)
        self.licence.setCurrentIndex(i if i >= 0 else 0)
        lay.addWidget(self.licence)
        self.licence_note = self._faint(lay)
        # What the engine says about the station as saved: abroad, CEPT,
        # QO-100's footprint, whether NB's uplink is allowed.
        self.station_notes = self._faint(lay)
        self.station_notes.setText("\n".join((st.get("station") or {}).get("notes", [])))
        self.station_notes.setVisible(bool(self.station_notes.text()))

        self.cls_cap = QLabel(self.tr("Licence class"))
        self.cls_cap.setObjectName("Muted")
        lay.addWidget(self.cls_cap)
        self.cls = Segmented([("", "Not chosen")], st.get("licenceClass", ""))
        lay.addWidget(self.cls)
        self.cls_note = self._faint(lay)

        self.cond_box = QVBoxLayout()
        self.cond_box.setSpacing(2)
        lay.addLayout(self.cond_box)
        self.cond_toggles: dict[str, Toggle] = {}

        self.custom = CustomLicenceEditor(st.get("customLicence") or [])
        lay.addWidget(self.custom)

        self.licence.currentIndexChanged.connect(lambda _i: self.refresh())
        call = dialog.fields.get("callsign")
        if call is not None:
            call.w.textChanged.connect(lambda _t: self.refresh())
        combo = getattr(dialog, "country_combo", None)
        if combo is not None:
            combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self.refresh()

    @staticmethod
    def _faint(lay) -> QLabel:
        lab = QLabel("")
        lab.setWordWrap(True)
        lab.setObjectName("Faint")
        lab.setFont(theme.font(12))
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(lab)
        return lab

    # ------------------------------------------------------------ what is on the page now
    def page_state(self) -> dict:
        d, st = self.d, dict(self.d.st)
        call = d.fields.get("callsign")
        if call is not None:
            st["callsign"] = call.w.text().strip().upper()
        combo = getattr(d, "country_combo", None)
        if combo is not None:
            st["stationCountry"] = combo.currentData() or ""
        st["licence"] = self.licence.currentData()
        return st

    def regime(self):
        """The written regime the class picker is for, or None (own licence,
        or nothing written for the country)."""
        st = self.page_state()
        choice = st["licence"]
        if choice == licences.CUSTOM:
            return None
        if choice == licences.AUTO:
            return licences.get(countries.station(st.get("callsign", ""), st.get("stationCountry", "")).regime)
        return licences.get(choice)

    def refresh(self):
        st = self.page_state()
        choice = st["licence"]
        reg = self.regime()
        s = countries.station(st.get("callsign", ""), st.get("stationCountry", ""))
        if choice == licences.AUTO:
            self.licence.setItemText(0, FOLLOW_NAMED.format(short=reg.SHORT) if reg is not None else FOLLOW)
            self.licence_note.setText(LICENCE_NONE.format(entity=s.entity) if reg is None and s.entity else
                                      (reg.TITLE if reg is not None else countries.NO_COUNTRY))
        elif choice == licences.CUSTOM:
            self.licence_note.setText("")
        else:
            self.licence_note.setText(countries.NOT_THIS_COUNTRY.format(country=s.entity, regime=reg.SHORT)
                                      if s.entity and (s.country is None or choice not in s.country.regimes)
                                      else reg.TITLE)
        own = choice == licences.CUSTOM
        self.custom.setVisible(own)
        for w in (self.cls_cap, self.cls, self.cls_note):
            w.setVisible(not own)
        keep = self.cls.value or self.d.st.get("licenceClass", "")
        opts = [("", "Not chosen")]
        if reg is not None:
            opts += [(c, licences.class_name(reg, c)) for c in reg.CLASSES]
        self.cls.options = opts
        self.cls.set_value(keep if any(v == keep for v, _ in opts) else "", animate=False)
        self.cls.updateGeometry()
        self.cls.update()
        self.cls_note.setText("" if reg is not None or own else NO_CLASS_HERE)
        self._conditions(reg)

    def _conditions(self, reg):
        while self.cond_box.count():
            item = self.cond_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.cond_toggles = {}
        if reg is None:
            return
        answers = licences.condition_answers(reg, self.d.st)
        for cond in getattr(reg, "CONDITIONS", []):
            t = Toggle(cond["label"], bool(answers.get(cond["key"], cond.get("default", False))))
            self.cond_box.addWidget(t)
            self.cond_toggles[cond["key"]] = t

    # ------------------------------------------------------------ values for collect()
    def fields(self) -> dict:
        """{setting key: Value} for the dialog's collect()."""
        d = self.d
        out = {"licence": Value(lambda: self.licence.currentData(), self.licence),
               "licenceClass": Value(self._class_value, self.cls),
               "customLicence": Value(self._custom_value, self.custom),
               "stationConditions": Value(self._conditions_value, None)}
        # A condition that is a setting of its own (the UK's nearLondon,
        # since 05/10/2026) is written there, so the two never disagree.
        for key in ("nearLondon",):
            if key in d.spec:
                out[key] = Value(lambda k=key: self.cond_toggles[k].on if k in self.cond_toggles
                                 else d.st.get(k, d.spec[k]["default"]), None)
        return out

    def _class_value(self) -> str:
        if self.licence.currentData() == licences.CUSTOM:
            return self.d.st.get("licenceClass", "")
        return self.cls.value if any(v == self.cls.value for v, _ in self.cls.options) else ""

    def _custom_value(self) -> list:
        if self.licence.currentData() != licences.CUSTOM:
            return self.d.st.get("customLicence") or []
        return self.custom.value()

    def _conditions_value(self) -> dict:
        out = dict(self.d.st.get("stationConditions") or {})
        for key, t in self.cond_toggles.items():
            if key not in self.d.spec:
                out[key] = t.on
        return out


def country_combo(st: dict, data_dir=None) -> QComboBox:
    """The stationCountry choice: from the callsign, or any DXCC entity."""
    c = QComboBox()
    c.addItem(AUTO_FROM_CALL, "")
    for prefix, name in countries.entities(data_dir):
        c.addItem(f"{name} ({prefix})", prefix)
    i = c.findData(st.get("stationCountry", ""))
    c.setCurrentIndex(i if i >= 0 else 0)
    return c


def station_line(callsign: str, override: str) -> str:
    """The sentence under the country choice: where the callsign (or the
    choice) puts the station, and the licence that gives."""
    s = countries.station(callsign, override)
    if not s.entity:
        return countries.AT_SEA if s.at_sea else STATION_NOTHING
    lic = licences.get(s.regime)
    which = LICENCE_WRITTEN.format(short=lic.SHORT) if lic is not None else LICENCE_NONE.format(entity=s.entity)
    return STATION_FROM.format(entity=s.entity, region=s.region or "?", licence=which)
