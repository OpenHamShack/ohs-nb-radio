"""The Local view: what there is to listen to near the station
(ohsradio/localfreq.py; the same listing Remote gets from
api/local-frequencies), and the editor for the operator's own list that
Settings › Local frequencies holds.

A click on a row tunes there: the dial, the mode and, where the
desktop's step list has it, the step (MainWindow.local_tune). It only
receives: nothing here keys, and a tune into a band the licence does not
cover is refused for transmit exactly as any other dial is.

The listing is read from the engine on demand (opening the view, a
change of category or radius, Reload) and every 10 s while the view is
on screen, which is when the NCDXF beacon on each band changes."""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Button

from ..localfreq import CATEGORIES, Invalid

REFRESH_MS = 10_000
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def category_names() -> dict[str, str]:
    t = QCoreApplication.translate
    return {"": t("LocalView", "Everything"), "airband": t("LocalView", "Airband"),
            "enroute": t("LocalView", "Area control"), "marine": t("LocalView", "Marine"),
            "pmr": t("LocalView", "PMR446"), "cb": t("LocalView", "CB"), "lpd": t("LocalView", "LPD433"),
            "beacon": t("LocalView", "Beacons"), "mine": t("LocalView", "My frequencies")}


def mhz_text(hz: int) -> str:
    """146.712 500: MHz to the hertz, without trailing zeros past the kHz."""
    places = 6 if hz % 1000 else 3
    return fmt.frequency(int(hz), "MHz", places).rsplit(fmt.NBSP, 1)[0]


def bearing_text(deg) -> str:
    if deg is None:
        return ""
    return f"{int(deg):03d}° {COMPASS[int((float(deg) + 22.5) // 45) % 8]}"


def number(v: float, places: int) -> str:
    """In the locale's decimals, never grouped (I18N.md 4.1, as fmt.frequency)."""
    from PyQt6.QtCore import QLocale
    loc = QLocale()
    loc.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    return loc.toString(float(v), "f", places)


def km_text(km) -> str:
    return "" if km is None else number(km, 1 if km < 10 else 0)


class LocalView(QWidget):
    """The list, rebuilt with the window. `tune(entry)` is the window's."""

    def __init__(self, bridge, prefs, tune, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.tune = bridge, prefs, tune
        self.rows: list[dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.cat = QComboBox()
        names = category_names()
        for c in ("",) + CATEGORIES:
            self.cat.addItem(names[c], c)
        want = prefs.get("localCategory", "")
        self.cat.setCurrentIndex(max(0, self.cat.findData(want)))
        self.cat.currentIndexChanged.connect(self._cat_picked)
        top.addWidget(self.cat)
        self.radius = QLabel("")
        self.radius.setObjectName("Muted")
        top.addWidget(self.radius)
        top.addStretch(1)
        self.reload_btn = Button(self.tr("Reload"), small=True)
        self.reload_btn.setToolTip(self.tr("Read the list again (the radius and your locator are in Settings)"))
        self.reload_btn.clicked.connect(self.refresh)
        top.addWidget(self.reload_btn)
        lay.addLayout(top)
        self.why = QLabel("")
        self.why.setWordWrap(True)
        self.why.setObjectName("Muted")
        self.why.hide()
        lay.addWidget(self.why)
        heads = [self.tr("Name"), self.tr("Detail"), self.tr("MHz"), self.tr("Mode"), self.tr("km"),
                 self.tr("Bearing")]
        t = self.table = QTableWidget(0, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = t.horizontalHeader()
        for i in range(len(heads)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch if i == 1
                                    else QHeaderView.ResizeMode.ResizeToContents)
        t.setToolTip(self.tr("Click a row to tune there (receive only)"))
        t.setFont(theme.font(12.5))
        t.cellClicked.connect(lambda r, _c: self._picked(r))
        t.cellActivated.connect(lambda r, _c: self._picked(r))
        lay.addWidget(t, 1)
        # The sources' attributions: their licences want them wherever the
        # list is shown.
        self.credits = QLabel("")
        self.credits.setWordWrap(True)
        self.credits.setObjectName("Faint")
        self.credits.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.credits.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.credits)
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.listing: dict = {}

    def showEvent(self, e):
        # Read when shown, not when the window is built: a session that
        # never opens the view never reads the data (about 0.1 s the first
        # time).
        super().showEvent(e)
        self.refresh()

    def detach(self):
        """The window is rebuilding (a theme change): stop reading. The
        timer is this widget's child, so it may already be gone with it."""
        try:
            self.timer.stop()
        except RuntimeError:
            pass

    def _tick(self):
        if self.isVisible():
            self.refresh()

    def _cat_picked(self, _i: int):
        self.prefs["localCategory"] = self.cat.currentData() or ""
        self.refresh()

    def _picked(self, r: int):
        if 0 <= r < len(self.rows):
            self.tune(self.rows[r])

    def refresh(self):
        self.listing = self.bridge.radio.local_frequencies(None, self.cat.currentData() or None)
        self.rows = self.listing["entries"]
        self.radius.setText(self.tr("within {km} km of {locator}").format(
            km=number(self.listing["radiusKm"], 0), locator=self.listing["locator"] or "?"))
        why = self.listing.get("why", "")
        self.why.setText(why)
        self.why.setVisible(bool(why))
        keep = self.table.currentRow()
        keep_id = self.rows[keep]["id"] if 0 <= keep < len(self.rows) else None
        t = self.table
        t.setRowCount(len(self.rows))
        text = theme.c("text")          # a QColor
        for r, e in enumerate(self.rows):
            sub = e.get("sub", "")
            if e.get("source") == "mine" and e.get("userCategory"):
                sub = f"{e['userCategory']}: {sub}" if sub else e["userCategory"]
            cells = [e["name"], sub, mhz_text(e["freqHz"]), e["mode"].upper(), km_text(e.get("distanceKm")),
                     bearing_text(e.get("bearingDeg"))]
            for c, v in enumerate(cells):
                it = t.item(r, c)
                if it is None:
                    it = QTableWidgetItem()
                    t.setItem(r, c, it)
                it.setText(v)
                it.setForeground(text)
                if c in (2, 4, 5):
                    it.setFont(theme.font(12.5, mono=True))
            if e.get("notes"):
                t.item(r, 0).setToolTip(e["notes"])
        if keep_id is not None:
            idx = next((i for i, e in enumerate(self.rows) if e["id"] == keep_id), -1)
            if idx >= 0:
                t.selectRow(idx)
        self.credits.setText(" · ".join(a["text"] for a in self.listing.get("attributions", []) if a.get("text")))


class MineDialog(QDialog):
    """Add or edit one of "my frequencies": the API's fields, checked by
    the same rules (ohsradio/localfreq.py clean_mine) when OK is pressed."""

    def __init__(self, modes, entry: dict | None = None, parent=None):
        super().__init__(parent)
        self.modes = list(modes)
        self.setWindowTitle(self.tr("Edit frequency") if entry else self.tr("Add a frequency"))
        e = entry or {}
        form = QFormLayout(self)
        self.name = QLineEdit(e.get("name", ""))
        self.mhz = QLineEdit(mhz_text(e["freqHz"]).replace(fmt.NBSP, "").replace(" ", "") if e.get("freqHz") else "")
        self.mhz.setPlaceholderText("145.7125")
        self.mode = QComboBox()
        for m in self.modes:
            self.mode.addItem(m.upper(), m)
        self.mode.setCurrentIndex(max(0, self.mode.findData(e.get("mode", "fm"))))
        self.category = QLineEdit(e.get("category", "") or "")
        self.category.setPlaceholderText(self.tr("repeater"))
        self.locator = QLineEdit(e.get("locator", "") or "")
        self.locator.setPlaceholderText(self.tr("IO75TU"))
        self.sub = QLineEdit(e.get("sub", "") or "")
        self.notes = QLineEdit(e.get("notes", "") or "")
        form.addRow(self.tr("Name"), self.name)
        form.addRow(self.tr("Frequency (MHz)"), self.mhz)
        form.addRow(self.tr("Mode"), self.mode)
        form.addRow(self.tr("Category"), self.category)
        form.addRow(self.tr("Locator (optional)"), self.locator)
        form.addRow(self.tr("Detail (optional)"), self.sub)
        form.addRow(self.tr("Notes (optional)"), self.notes)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {theme.t()['err']};")
        self.error.hide()
        form.addRow(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.body: dict = {}

    def values(self) -> dict:
        try:
            hz = int(round(float(self.mhz.text().strip().replace(",", ".")) * 1e6))
        except ValueError:
            raise Invalid(self.tr("Give the frequency in MHz, for example 145.7125"), "freqHz") from None
        return {"name": self.name.text(), "freqHz": hz, "mode": self.mode.currentData(),
                "category": self.category.text().strip() or "other", "locator": self.locator.text(),
                "sub": self.sub.text(), "notes": self.notes.text()}

    def accept(self):
        from ..localfreq import clean_mine
        try:
            self.body = self.values()
            clean_mine(self.body, self.modes)
        except Invalid as e:
            self.error.setText(str(e))
            self.error.show()
            return
        super().accept()


__all__ = ["LocalView", "MineDialog", "mhz_text", "bearing_text", "category_names"]
