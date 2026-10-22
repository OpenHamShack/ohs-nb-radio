"""Settings: everything that is set once rather than operated.

Every engine setting is built from its entry in the app's state registry -
label, range, choices and the help sentence printed under it - so a limit
is never written twice. Saving applies all engine changes in one `set(authorise=
True, ...)` (all or nothing; this dialog is the only caller allowed to pass
authorise), then the window restarts the radio if a `restart` key changed.
Nothing here can key the transmitter.
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..devices.pluto import discover as discover_pluto
from . import icons, layoutrules, palettes, theme
from .audiotest import AudioTester
from .converters import ConverterEditor
from . import licence as licence_ui
from . import controller as controller_ui
from . import padpage
from .controls import FocusVisible, Anim, Button, Segmented, Slider, Toggle, check_row
from .lookedit import LookEditor
from . import smeter
from .meters import BarMeter
from .wfpanel import PaletteSwatch

# Labels, help, choice names and slider steps for the shared keys. An app's
# dialog extends these with its own keys (ohsnb/ui/settings.py).
LABELS = {
    "device": "Radio", "plutoUri": "Pluto address", "soapyArgs": "SoapySDR device", "sampleRate": "Sample rate",
    "rxGainMode": "Receiver gain control", "rxGain": "Receiver gain",
    "txFilterLo": "TX audio low edge", "txFilterHi": "TX audio high edge",
    "txTimeoutSec": "Transmit time-out", "deadAirSec": "Dead-air unkey",
    "watchdogSec": "UI watchdog", "audioIn": "Microphone", "audioOut": "Speaker", "audioOut2": "Second output",
    "callsign": "Callsign", "locator": "Locator", "pttMode": "Space bar / PTT button",
    "modeAutoTune": "Tune to usual frequency on mode", "scopeFps": "Scope speed",
    "wideAvg": "Wide scope averaging", "zoomAvg": "Zoom scope averaging", "wideBins": "Wide scope resolution",
    "simSignals": "Other stations", "zoomSpanHz": "Zoom span",
    "nr": "Noise reduction (NR2)", "nrStrength": "Noise reduction strength",
    "checkUpdates": "Check for updates", "ft8Decoder": "FT8 and FT4 decoder",
    "pskReporter": "Report stations heard to PSKReporter",
}
EXTRA_HELP = {
    "callsign": "Used in macros, FT8 messages and the log.",
    "locator": "Maidenhead locator, e.g. IO86 or IO86ha.",
    "pttMode": "Hold: transmit while held. Toggle: press once to transmit, again to stop. Esc always stops.",
    "modeAutoTune": "Off: picking a mode only changes the mode - the dial stays exactly where it was.",
    "txFilterLo": "", "audioIn": "", "audioOut": "",
}
CHOICE_LABELS = {
    "device": {"sim": "Simulator", "pluto": "Pluto family", "soapy": "SoapySDR (RX only)"},
    "rxGainMode": {"manual": "Manual", "slow_attack": "Slow AGC", "fast_attack": "Fast AGC"},
    "pttMode": {"hold": "Hold to talk", "toggle": "Toggle"},
    "ft8Decoder": {"auto": "Automatic", "jt9": "WSJT-X's jt9"},
}
STEPS = {"rxGain": 1, "txFilterLo": 50, "txFilterHi": 50, "txTimeoutSec": 10, "deadAirSec": 1, "watchdogSec": 0.5,
         "scopeFps": 1, "wideAvg": 1, "zoomAvg": 1, "zoomSpanHz": 500, "wideBins": 256, "nrStrength": 5}


def add_device(cb: QComboBox, d: dict) -> None:
    """A sound device from audio.list_devices() as a picker's item: shown
    by its tidy label, saved by its whole name, which the tooltip gives in
    full - Windows cuts names at 31 characters and the label may be elided
    by the picker's width besides (Windows test 17/10/2026, finding 2)."""
    full = d.get("full") or d["name"]
    cb.addItem(d.get("label") or d["name"], full)
    cb.setItemData(cb.count() - 1, full, Qt.ItemDataRole.ToolTipRole)


def find_device(cb: QComboBox, saved: str) -> int:
    """The item for the device saved as `saved`: its exact data, else the
    device it names under Windows' 31-character cut either way round (a
    name saved before 17/10/2026 is the cut one). -1 when not listed."""
    from .. import audio
    i = cb.findData(saved)
    if i >= 0 or not saved:
        return i
    for j in range(cb.count()):
        data = cb.itemData(j)
        if data and (audio.same_device(saved, data) or audio.same_device(data, saved)):
            return j
    return -1


def add_missing_device(cb: QComboBox, saved: str, label: str) -> int:
    """A saved device that is not plugged in, kept in the list as `label`
    ("... (not connected)") so the choice is not lost; returns its row."""
    cb.addItem(label, saved)
    cb.setItemData(cb.count() - 1, saved, Qt.ItemDataRole.ToolTipRole)
    return cb.count() - 1


class Field(QWidget):
    """One setting: label, control, the help sentence. `vocab` is the
    dialog, which knows the app's registry and its words for each key."""

    def __init__(self, key: str, value, vocab, parent=None, label: str | None = None, help_: str | None = None):
        super().__init__(parent)
        self.key = key
        spec = vocab.spec.get(key, {})
        LABELS, CHOICE_LABELS, STEPS, EXTRA_HELP = vocab.LABELS, vocab.CHOICE_LABELS, vocab.STEPS, vocab.EXTRA_HELP
        mhz = vocab.MHZ_FIELDS
        typed = vocab.TYPED_FIELDS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.setSpacing(4)
        t = spec.get("type")
        lab = label or LABELS.get(key, key)
        self.get = None
        if t == "bool":
            self.w = Toggle(lab, bool(value))
            lay.addWidget(self.w)
            self.get = lambda: self.w.on
        elif t == "enum":
            cap = QLabel(lab)
            cap.setObjectName("Muted")
            lay.addWidget(cap)
            names = CHOICE_LABELS.get(key, {})
            self.w = Segmented([(str(c), names.get(c, str(c))) for c in spec["choices"]], str(value))
            lay.addWidget(self.w)
            choices = {str(c): c for c in spec["choices"]}
            self.get = lambda: choices[self.w.value]
        elif t in ("float", "int") and spec.get("min") is not None and key not in mhz and key not in typed:
            step = STEPS.get(key, 1)
            self.w = Slider(lab, spec["min"], spec["max"], float(value), step, vocab.unit_fmt(key),
                            default=spec["default"])
            lay.addWidget(self.w)
            self.get = (lambda: int(round(self.w.v))) if t == "int" else (lambda: float(self.w.v))
        else:
            cap = QLabel(lab)
            cap.setObjectName("Muted")
            lay.addWidget(cap)
            self.w = QLineEdit("" if value is None else (f"{value / 1e6:.6f}" if key in mhz else str(value)))
            if key in typed:
                fmt, parse, hint = typed[key]
                self.w.setText(fmt(value))
                self.w.setPlaceholderText(hint)
                self.get = lambda: parse(self.w.text().strip())
            elif key in mhz:
                self.w.setPlaceholderText(mhz[key])
                self.get = lambda: float(self.w.text().replace(",", ".")) * 1e6
            elif key in ("callsign", "locator"):
                self.w.setFont(theme.font(15, theme.QFont.Weight.DemiBold, mono=True))
                self.get = lambda: self.w.text().strip().upper() if key == "callsign" else self.w.text().strip()
            else:
                self.get = lambda: self.w.text().strip()
            lay.addWidget(self.w)
        h = help_ if help_ is not None else EXTRA_HELP.get(key, spec.get("help", ""))
        if h:
            hl = QLabel(h)
            # Help sentences are plain text from the state registry. Left to
            # guess, QLabel took "ip:<address>" for markup and showed the
            # Pluto address examples as "ip:" with the address swallowed.
            hl.setTextFormat(Qt.TextFormat.PlainText)
            hl.setWordWrap(True)
            hl.setObjectName("Faint")
            hl.setFont(theme.font(12))
            lay.addWidget(hl)


class Nav(FocusVisible, QWidget):
    picked = pyqtSignal(int)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.items = items
        self.cur = 0
        self.k = Anim(self, 0.0)
        self.hover = -1
        self.setFixedWidth(210)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _row(self, i):
        return QRectF(10, 64 + i * 40, self.width() - 20, 36)

    def mouseMoveEvent(self, e):
        h = next((i for i in range(len(self.items)) if self._row(i).contains(e.position())), -1)
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        for i in range(len(self.items)):
            if self._row(i).contains(e.position()):
                self.select(i)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Down:
            self.select(min(len(self.items) - 1, self.cur + 1))
        elif e.key() == Qt.Key.Key_Up:
            self.select(max(0, self.cur - 1))
        else:
            super().keyPressEvent(e)

    def select(self, i):
        self.cur = i
        self.k.to(i)
        self.picked.emit(i)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), theme.c("bg1"))
        p.setPen(QPen(theme.c("line"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.setFont(theme.font(19, theme.QFont.Weight.Bold))
        p.setPen(theme.c("text"))
        p.drawText(QRectF(22, 18, 180, 30), Qt.AlignmentFlag.AlignVCenter, self.tr("Settings"))
        sel = self._row(0).translated(0, self.k.value * 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("accent", 0.16))
        p.drawRoundedRect(sel, 8, 8)
        p.setBrush(theme.c("accent"))
        p.drawRoundedRect(QRectF(sel.x(), sel.y() + 8, 3, sel.height() - 16), 1.5, 1.5)
        for i, (icon, name) in enumerate(self.items):
            r = self._row(i)
            if i == self.hover and i != self.cur:
                p.setBrush(theme.c("bg3"))
                p.drawRoundedRect(r, 8, 8)
            col = theme.c("accent") if i == self.cur else theme.c("text2")
            icons.paint(p, icon, QRectF(r.x() + 14, r.center().y() - 9, 18, 18), col, 1.6)
            p.setFont(theme.font(13.5, theme.QFont.Weight.DemiBold if i == self.cur else theme.QFont.Weight.Normal))
            p.setPen(theme.c("text") if i == self.cur else theme.c("text2"))
            p.drawText(QRectF(r.x() + 44, r.y(), r.width() - 48, r.height()), Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(Qt.PenStyle.NoPen)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(sel, 8, 8)


class SettingsDialog(QDialog):
    """The framework and the pages every app has. An app's dialog
    subclasses it: its PAGES (icon, title, builder method) in its order, its
    own pages, and its words for its own keys."""

    PAGES = [("star", "Station", "page_station"), ("antenna", "Radio", "page_radio"),
             ("lock", "Transmit & safety", "page_transmit"), ("mic", "Audio", "page_audio"),
             ("waves", "Display", "page_display"), ("screen", "Second display", "page_second"),
             ("link", "Controller", "page_controller"), ("keyboard", "Control pad", "page_pad"), ("gear", "Simulator", "page_simulator")]
    LABELS, EXTRA_HELP, CHOICE_LABELS, STEPS = LABELS, EXTRA_HELP, CHOICE_LABELS, STEPS
    MHZ_FIELDS: dict = {}          # keys typed in MHz rather than slid: {key: placeholder}
    # Keys typed rather than slid, in the app's own notation (a CI-V address
    # in hex, a TCP port): {key: (format(value) -> text, parse(text) -> value
    # or ValueError, placeholder)}.
    TYPED_FIELDS: dict = {}
    SIM_KEYS = ("simSignals",)     # the Simulator page's settings
    SIM_TEXT = "The simulator used when Radio is 'Simulator'. Changes restart the radio."

    def __init__(self, bridge, prefs, parent=None, page: int = 0):
        super().__init__(parent)
        self.bridge, self.prefs = bridge, prefs
        self.spec = bridge.radio.STATE.spec
        self.restart_needed = False
        # Every string in SettingsDialog is translate("SettingsDialog", ...)
        # rather than self.tr(): only the apps' subclasses are ever built,
        # and PyQt's self.tr() looks up under the subclass's name, where
        # none of these strings is (docs/I18N.md, the subclass trap).
        self.setWindowTitle(QCoreApplication.translate("SettingsDialog", "Settings"))
        self.setModal(True)
        self.resize(980, 720)
        self.st = dict(bridge.radio.state())
        self.fields: dict[str, Field] = {}
        self.pref_widgets: dict[str, object] = {}
        self.tester = AudioTester()
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # PAGES is a class table, read before any catalog is installed, so
        # its titles are looked up here; each core page's title is also the
        # literal heading its builder passes to _scroll, which is what puts
        # it in the catalog under this context.
        self.nav = Nav([(icon, QCoreApplication.translate("SettingsDialog", title)) for icon, title, _ in self.PAGES])
        root.addWidget(self.nav)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {theme.t()['err']}; padding: 0 28px;")
        self.error.hide()
        right.addWidget(self.error)
        bar = QHBoxLayout()
        bar.setContentsMargins(28, 12, 28, 18)
        self.restart_note = QLabel("")
        self.restart_note.setObjectName("Faint")
        bar.addWidget(self.restart_note, 1)
        cancel = Button(QCoreApplication.translate("SettingsDialog", "Cancel"), kind="ghost")
        cancel.clicked.connect(self.reject)
        save = Button(QCoreApplication.translate("SettingsDialog", "Save"), kind="primary")
        save.setMinimumWidth(110)
        save.clicked.connect(self.save)
        bar.addWidget(cancel)
        bar.addWidget(save)
        right.addLayout(bar)
        root.addLayout(right, 1)
        for _icon, _title, builder in self.PAGES:
            self.stack.addWidget(getattr(self, builder)())
        self.nav.picked.connect(self.stack.setCurrentIndex)
        self.nav.select(page)
        self.nav.k.value = float(page)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._meter)

    # ------------------------------------------------------------ vocabulary
    def unit_fmt(self, key):
        """How a slider shows its value."""
        unit = self.spec[key]["unit"]
        step = self.STEPS.get(key, 1)
        if key == "txTimeoutSec":
            return lambda v: f"{int(v) // 60}:{int(v) % 60:02d} min"
        places = 0 if step >= 1 else (2 if step < 0.1 else 1)
        if step == 0.25:
            places = 2
        return lambda v: f"{v:.{places}f}{(' ' + unit) if unit else ''}"

    # ------------------------------------------------------------ pages
    def _scroll(self, title: str, sub: str):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 22, 28, 12)
        lay.setSpacing(4)
        h = QLabel(title)
        h.setFont(theme.font(20, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        if sub:
            s = QLabel(sub)
            s.setObjectName("Muted")
            s.setWordWrap(True)
            lay.addWidget(s)
        lay.addSpacing(10)
        sc.setWidget(inner)
        return sc, lay

    def _add(self, lay, key, **kw):
        f = Field(key, self.st.get(key, self.spec[key]["default"]), self, **kw)
        self.fields[key] = f
        lay.addWidget(f)
        return f

    def _section(self, lay, text):
        lab = QLabel(text)
        lab.setFont(theme.caps(10.5))
        lab.setStyleSheet(f"color: {theme.t()['text3']}; padding-top: 14px;")
        lay.addWidget(lab)

    def page_station(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Station"),
                               QCoreApplication.translate("SettingsDialog",
                                                          "Who you are, and how the transmit controls behave."))
        row = QHBoxLayout()
        row.setSpacing(16)
        a = Field("callsign", self.st.get("callsign", ""), self)
        b = Field("locator", self.st.get("locator", ""), self)
        self.fields["callsign"], self.fields["locator"] = a, b
        row.addWidget(a)
        row.addWidget(b)
        lay.addLayout(row)
        # Where the station is decides whose licence applies (08/10/2026):
        # from the callsign's prefix unless the operator says otherwise.
        if "stationCountry" in self.spec:
            cap = QLabel(QCoreApplication.translate("SettingsDialog", "Station's country"))
            cap.setObjectName("Muted")
            lay.addWidget(cap)
            self.country_combo = licence_ui.country_combo(self.st, getattr(self.bridge.radio, "data_dir", None))
            lay.addWidget(self.country_combo)
            self.country_line = QLabel("")
            self.country_line.setWordWrap(True)
            self.country_line.setObjectName("Faint")
            self.country_line.setFont(theme.font(12))
            self.country_line.setTextFormat(Qt.TextFormat.PlainText)
            lay.addWidget(self.country_line)

            def show_country():
                self.country_line.setText(licence_ui.station_line(a.w.text().strip().upper(),
                                                                  self.country_combo.currentData() or ""))
            a.w.textChanged.connect(lambda _t: show_country())
            self.country_combo.currentIndexChanged.connect(lambda _i: show_country())
            show_country()
            self.fields["stationCountry"] = licence_ui.Value(lambda: self.country_combo.currentData() or "",
                                                             self.country_combo)
        self._add(lay, "pttMode")
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Tuning"))
        self._add(lay, "modeAutoTune")
        # With the callsign: both are the operator's, both shape what the
        # FT8 panel shows, and neither has a page of its own to go on.
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Digital modes"))
        self._add(lay, "ft8Decoder")
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Licence"))
        face = self.bridge.face
        lic_row, self.licence = check_row(face.text("licence"), bool(self.prefs["licenceAck"]), bold=True)
        # Two whole variants rather than a second sentence appended, so a
        # language can join them its own way.
        if face.sim_needs_licence:
            lic_text = QCoreApplication.translate(
                "SettingsDialog", "Until this is ticked, {app} receives only: the TX button and every send "
                "button stay locked.").format(app=face.app_name)
        else:
            lic_text = QCoreApplication.translate(
                "SettingsDialog", "Until this is ticked, {app} receives only: the TX button and every send "
                "button stay locked. The simulator is the exception: nothing it transmits leaves this "
                "computer.").format(app=face.app_name)
        lic_wrap = QLabel(lic_text)
        lic_wrap.setObjectName("Faint")
        lic_wrap.setWordWrap(True)
        lay.addWidget(lic_row)
        lay.addWidget(lic_wrap)
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Updates"))
        self._add(lay, "checkUpdates")
        self._diagnostics_section(lay)
        # Beside the other thing that uses the network, and on the page
        # with the callsign and locator it cannot do without.
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Spotting"))
        self._add(lay, "pskReporter")
        lay.addStretch(1)
        return sc

    def _diagnostics_section(self, lay) -> None:
        """The opt-in automatic diagnostics upload (ohscore/diagupload.py):
        the switch, with the whole consent text under it rather than behind
        a link, since turning it on here is the consent (ui.json, saved
        with the dialog)."""
        from .. import diagupload
        from .diagsend import what_is_sent
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Diagnostics"))
        p = self.prefs
        on = bool(p["diagUpload"]) and diagupload.consented(p["diagUploadConsent"])
        self.diag_toggle = Toggle(QCoreApplication.translate(
            "SettingsDialog", "Send diagnostics to OpenHamShack automatically"), on)
        lay.addWidget(self.diag_toggle)
        text = QLabel(QCoreApplication.translate(
            "SettingsDialog", "Off unless you turn it on. When on, {app} sends its diagnostics after a fault (an "
            "over that failed or was stopped, no power out, a lost radio link, a sound card failure, a crash), "
            "after the IC-9700 diagnostic or level set, and once a day if anything new was logged; at most one "
            "fault report every 30 minutes. Each one gets a reference code, shown in Help › Send diagnostics…."
        ).format(app=self.bridge.face.app_name) + " " + what_is_sent(self.bridge.face.app_name))
        text.setObjectName("Faint")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(text)

    def _store_diagnostics(self, p) -> None:
        from .. import diagupload
        toggle = getattr(self, "diag_toggle", None)
        if toggle is None:
            return
        if toggle.on:
            if not (p["diagUpload"] and diagupload.consented(p["diagUploadConsent"])):
                p["diagUploadConsent"] = diagupload.consent_stamp()
        else:
            p["diagUploadConsent"] = ""
        p["diagUpload"] = bool(toggle.on)

    def _licence_section(self, lay) -> "licence_ui.LicencePanel":
        """The licence, class, station questions and own-licence editor
        (ohscore/ui/licence.py), as fields of this dialog. Both apps' pages
        call it after the Station page is built, whose callsign and country
        it follows."""
        self.licence_panel = licence_ui.LicencePanel(self)
        lay.addWidget(self.licence_panel)
        self.fields.update(self.licence_panel.fields())
        return self.licence_panel

    def page_controller(self) -> QWidget:
        # translate("SettingsDialog", ...), not self.tr(): each app builds
        # its own subclass, which self.tr() would look the string up under.
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Controller"), QCoreApplication.translate(
            "SettingsDialog",
            "An OpenHamShack controller on your network shares one logbook and station profile with every app "
            "paired to it. This app works the same without one: unpairing keeps everything on this computer."))
        lay.addWidget(controller_ui.ControllerPage(self.bridge.radio.station_link, self))
        lay.addStretch(1)
        return sc

    def page_pad(self) -> QWidget:
        # The AKP03E controller pad (ohscore/ui/padpage.py): found or not and
        # why, whether it may transmit, the test, the report to send.
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Control pad"), QCoreApplication.translate(
            "SettingsDialog",
            "The Ajazz AKP03E: six keys with pictures, three buttons and three knobs that tune, change mode and "
            "mute without the mouse. This app works the same without one."))
        self.pad_page = padpage.PadPage(self.prefs, self.bridge.face.app_name,
                                        type(self.bridge.radio).__module__.split(".")[0], self, radio=self.bridge.radio)
        lay.addWidget(self.pad_page)
        lay.addStretch(1)
        return sc

    def page_radio(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Radio"),
                               QCoreApplication.translate(
                                   "SettingsDialog", "Which SDR, and how it is reached. A change of radio, "
                                   "address or sample rate restarts the radio (it comes back receiving, never "
                                   "transmitting); the receiver gain applies at once."))
        self._add(lay, "device")
        f = self._add(lay, "plutoUri")
        find = Button(QCoreApplication.translate("SettingsDialog", "Find"), icon="antenna", small=True)
        find.clicked.connect(self.find_pluto)
        self.pluto_found = QComboBox()
        self.pluto_found.hide()
        self.pluto_found.activated.connect(lambda _i: f.w.setText(self.pluto_found.currentData() or f.w.text()))
        r = QHBoxLayout()
        r.addWidget(find)
        r.addWidget(self.pluto_found, 1)
        r.addStretch(1)
        lay.addLayout(r)
        g = self._add(lay, "soapyArgs")
        det = Button(QCoreApplication.translate("SettingsDialog", "Detect"), icon="antenna", small=True)
        det.clicked.connect(self.find_soapy)
        self.soapy_found = QComboBox()
        self.soapy_found.hide()
        self.soapy_found.activated.connect(lambda _i: g.w.setText(self.soapy_found.currentData() or g.w.text()))
        r = QHBoxLayout()
        r.addWidget(det)
        r.addWidget(self.soapy_found, 1)
        r.addStretch(1)
        lay.addLayout(r)
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Receiver"))
        self._add(lay, "sampleRate")
        self._add(lay, "rxGainMode")
        self._add(lay, "rxGain")
        smeter.settings_section(self, lay)
        lay.addStretch(1)
        return sc

    def page_transmit(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Transmit & safety"),
                               QCoreApplication.translate("SettingsDialog", "Limits that only this dialog can change."))
        self._transmit_limits(lay)
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Timers"))
        self._add(lay, "txTimeoutSec")
        self._add(lay, "deadAirSec")
        self._add(lay, "watchdogSec")
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Transmit audio"))
        self._add(lay, "txFilterLo")
        self._add(lay, "txFilterHi")
        lay.addStretch(1)
        return sc

    def _transmit_limits(self, lay) -> None:
        """The app's power limits, first on the Transmit & safety page."""

    def page_audio(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Audio"),
                               QCoreApplication.translate("SettingsDialog", "Sound devices are remembered by name, "
                                                          "so a USB headset is found on any port."))
        self.audio_combos = {}
        for key in self.AUDIO_KEYS:
            cap = QLabel(self.LABELS[key])
            cap.setObjectName("Muted")
            lay.addWidget(cap)
            cb = QComboBox()
            # Sized by the page, not the longest name: "System default
            # (Tiger Lake-LP Smart Sound Technology Audio Controller Digital
            # Microphone)" is a real one, and would widen the dialog.
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(24)
            lay.addWidget(cb)
            if key == "audioOut2":
                h = QLabel(self.spec[key]["help"])
                h.setTextFormat(Qt.TextFormat.PlainText)
                h.setObjectName("Faint")
                h.setWordWrap(True)
                lay.addWidget(h)
            self.audio_combos[key] = cb
            lay.addSpacing(6)
        r = QHBoxLayout()
        rescan = Button(QCoreApplication.translate("SettingsDialog", "Look again"), icon="waves", small=True)
        rescan.setToolTip(QCoreApplication.translate(
            "SettingsDialog", "List the sound devices again, after plugging one in or changing the system's default"))
        rescan.clicked.connect(self.fill_audio)
        r.addWidget(rescan)
        r.addStretch(1)
        lay.addLayout(r)
        self.audio_none = QLabel("")
        self.audio_none.setStyleSheet(f"color: {theme.t()['warn']};")
        self.audio_none.setWordWrap(True)
        lay.addWidget(self.audio_none)
        self.fill_audio()
        # Also on the Receive card (and Shift+N); here too so the strength
        # can be set once, with its explanation, rather than found by ear.
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Receive noise reduction"))
        self._add(lay, "nr")
        self._add(lay, "nrStrength")
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Check"))
        self.mic_meter = BarMeter(QCoreApplication.translate("SettingsDialog", "Microphone level"), -60, 0,
                                  lambda v: f"{v:.0f}", ticks=(-60, -40, -20, 0),
                                  zones=((-60, -6, "ok"), (-6, -3, "warn"), (-3, 0, "err")), unit="dBFS")
        lay.addWidget(self.mic_meter)
        r = QHBoxLayout()
        self.mic_test = Toggle(QCoreApplication.translate("SettingsDialog", "Listen to the microphone"), False)
        self.mic_test.toggled.connect(self._mic_test)
        tone = Button(QCoreApplication.translate("SettingsDialog", "Play a test tone"), icon="waves", small=True)
        tone.clicked.connect(self._tone)
        r.addWidget(self.mic_test)
        r.addSpacing(16)
        r.addWidget(tone)
        r.addStretch(1)
        lay.addLayout(r)
        self.audio_msg = QLabel("")
        self.audio_msg.setObjectName("Faint")
        self.audio_msg.setWordWrap(True)
        lay.addWidget(self.audio_msg)
        lay.addStretch(1)
        return sc

    AUDIO_KEYS = ("audioIn", "audioOut", "audioOut2")     # the device pickers, in page order

    @staticmethod
    def default_label(name: str | None, error: str) -> str:
        """The "System default" entry, saying what it means now: the device
        the system would give us (its real name where it can be learnt,
        else the sound server's own word - never a guess), "none found"
        when the system has none of that kind, or plain "System default"
        when PortAudio could not be asked at all."""
        if error:
            return QCoreApplication.translate("SettingsDialog", "System default")
        if name:
            return QCoreApplication.translate("SettingsDialog", "System default ({name})").format(name=name)
        return QCoreApplication.translate("SettingsDialog", "System default (none found)")

    def fill_audio(self) -> None:
        """(Re)list the sound devices and what "System default" is now,
        keeping each picker's choice - including one in the dialog not yet
        saved. On opening the page and on Look again: PortAudio reads its
        device list when it starts, so a headset plugged in since then, or
        a new system default, shows only on a fresh look."""
        from .. import audio
        try:
            devs = audio.list_devices()
        except Exception:  # noqa: BLE001 - PortAudio fails in many ways; the page says none were found
            devs = []
        try:
            defaults = audio.default_devices()
        except Exception as e:  # noqa: BLE001
            defaults = {"input": None, "output": None, "error": str(e)}
        for key, cb in self.audio_combos.items():
            inputs = key == "audioIn"
            cur = cb.currentData() if cb.count() else self.st.get(key, "")
            cb.blockSignals(True)
            cb.clear()
            if key == "audioOut2":
                cb.addItem(QCoreApplication.translate("SettingsDialog", "None"), "")
            else:
                cb.addItem(self.default_label(defaults["input" if inputs else "output"], defaults["error"]), "")
            for d in devs:
                if (d["inputs"] if inputs else d["outputs"]) > 0:
                    add_device(cb, d)
            i = find_device(cb, cur or "")
            if i < 0 and cur:
                i = add_missing_device(cb, cur, QCoreApplication.translate(
                    "SettingsDialog", "{device} (not connected)").format(device=audio.display_name(cur)))
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)
        if defaults["error"]:
            self.audio_none.setText(QCoreApplication.translate("SettingsDialog", "No sound devices: {error}.")
                                    .format(error=defaults["error"]))
        elif not devs:
            self.audio_none.setText(QCoreApplication.translate("SettingsDialog", "No sound devices found."))
        else:
            self.audio_none.setText("")
        self.audio_none.setVisible(bool(self.audio_none.text()))

    def screen_room(self) -> tuple[int, int]:
        """The available size of the screen the main window is on (its
        own answer, which a test can set), for the text sizes offered."""
        win = self.parent()
        if win is not None and hasattr(win, "screen_room"):
            return win.screen_room()
        scr = self.screen() or QApplication.primaryScreen()
        g = scr.availableGeometry()
        return g.width(), g.height()

    def page_display(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Display"),
                               QCoreApplication.translate(
                                   "SettingsDialog", "Theme, text size, the scopes' colours, waterfall colours "
                                   "and levels, scope speed."))
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Theme"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        th = Segmented([("dark", QCoreApplication.translate("SettingsDialog", "Dark instrument")),
                        ("light", QCoreApplication.translate("SettingsDialog", "Light"))], self.prefs["theme"])
        self.pref_widgets["theme"] = th
        lay.addWidget(th)
        lay.addSpacing(10)
        # Text size (ohscore/ui/theme.py set_scale): the whole window, applied
        # on Save through the same rebuild as a theme change.
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Text size"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        ts = Segmented([(str(v), f"{v * 100:.0f} %") for v in layoutrules.TEXT_SCALES],
                       str(layoutrules.nearest_scale(self.prefs["textScale"])))
        self.pref_widgets["textScale"] = ts
        lay.addWidget(ts)
        # Only the sizes whose least window fits this screen (the window's
        # minimum grows with the text, ohscore/ui/layoutrules.py): a size
        # that does not is greyed, and hovering it says why.
        room = self.screen_room()
        ts.set_disabled({str(v): QCoreApplication.translate(
            "SettingsDialog", "Needs a screen of at least {w} x {h}; this one has {rw} x {rh} to spare.").format(
                w=layoutrules.minimum_size(v)[0], h=layoutrules.minimum_size(v)[1], rw=room[0], rh=room[1])
            for v in layoutrules.TEXT_SCALES if not layoutrules.scale_fits(v, room)})
        note = QLabel(QCoreApplication.translate(
            "SettingsDialog", "The size of the text throughout the window, the decode list's own size "
            "(Ctrl and the wheel over it) on top."))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addSpacing(10)
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Waterfall palette"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        row = QHBoxLayout()
        self.swatches = []
        for n in palettes.NAMES:
            s = PaletteSwatch(n, n == self.prefs["palette"])
            s.picked.connect(self._pick_palette)
            self.swatches.append(s)
            row.addWidget(s)
        row.addStretch(1)
        lay.addLayout(row)
        self.palette = self.prefs["palette"]
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Waterfall levels"))
        auto = Toggle(QCoreApplication.translate("SettingsDialog", "Automatic floor and contrast"),
                      self.prefs["wfAuto"])
        self.pref_widgets["wfAuto"] = auto
        lay.addWidget(auto)
        fl = Slider(QCoreApplication.translate("SettingsDialog", "Floor (manual)"), -160, -40, self.prefs["wfFloor"], 1,
                    lambda v: f"{v:.0f} dBFS", default=-110)
        rg = Slider(QCoreApplication.translate("SettingsDialog", "Contrast range (manual)"), 15, 90,
                    self.prefs["wfRange"], 1, lambda v: f"{v:.0f} dB", default=50)
        self.pref_widgets["wfFloor"], self.pref_widgets["wfRange"] = fl, rg
        lay.addWidget(fl)
        lay.addWidget(rg)
        for w in (fl, rg):
            w.setEnabled(not auto.on)
            auto.toggled.connect(lambda on, w=w: w.setEnabled(not on))
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Waterfall speed"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        sp = Segmented([("0.25", "¼×"), ("0.5", "½×"), ("1.0", "1×"), ("2.0", "2×")],
                       str(float(self.prefs["wfSpeed"])))
        self.pref_widgets["wfSpeed"] = sp
        lay.addWidget(sp)
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Scope colours"))
        note = QLabel(QCoreApplication.translate(
            "SettingsDialog", "The trace, its fill, the peak ghost and markers, the grid and the background, for "
            "every scope. Classic is the original look."))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.look_editor = LookEditor(self.prefs.get("scopeLook"))
        lay.addWidget(self.look_editor)
        self.look_anchor = self.look_editor
        self._section(lay, QCoreApplication.translate("SettingsDialog", "Scopes"))
        self._add(lay, "scopeFps")
        self._add(lay, "wideAvg")
        self._add(lay, "zoomAvg")
        lay.addStretch(1)
        return sc

    def page_second(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Second display"),
                               QCoreApplication.translate(
                                   "SettingsDialog", "A separate window for another screen - a big waterfall "
                                   "across the room, or the mode panel at reading size."))
        en = Toggle(QCoreApplication.translate("SettingsDialog", "Open the second display"),
                    self.prefs["secondDisplay"])
        self.pref_widgets["secondDisplay"] = en
        lay.addWidget(en)
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Screen"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        cb = QComboBox()
        cb.addItem(QCoreApplication.translate("SettingsDialog", "Automatic (any screen but the main window's)"), "")
        for s in QGuiApplication.screens():
            g = s.geometry()
            cb.addItem(f"{s.name()}  —  {g.width()}×{g.height()}", s.name())
        i = cb.findData(self.prefs["secondScreen"])
        cb.setCurrentIndex(max(0, i))
        self.pref_widgets["secondScreen"] = cb
        lay.addWidget(cb)
        fs = Toggle(QCoreApplication.translate("SettingsDialog", "Full screen on that screen"),
                    self.prefs["secondFullScreen"])
        self.pref_widgets["secondFullScreen"] = fs
        lay.addWidget(fs)
        cap = QLabel(QCoreApplication.translate("SettingsDialog", "Show"))
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        ct = Segmented([("waterfall", QCoreApplication.translate("SettingsDialog", "Big waterfall + decodes")),
                        ("panel", QCoreApplication.translate("SettingsDialog", "Mode panel"))],
                       self.prefs["secondContent"])
        self.pref_widgets["secondContent"] = ct
        lay.addWidget(ct)
        n = QLabel(QCoreApplication.translate(
            "SettingsDialog", "%n screen(s) connected. With one screen the second display is simply another "
            "window.", "", len(QGuiApplication.screens())))
        n.setObjectName("Faint")
        n.setWordWrap(True)
        lay.addWidget(n)
        lay.addStretch(1)
        return sc

    # ------------------------------------------------------------ converters
    # The Converters page (ohscore/ui/converters.py). An app that lists it in
    # PAGES says which preset packs it offers, the on-air ranges its
    # examples are worked out on, whether an RX/TX definition must give its
    # most drive, and - in _converter_uses - where definitions are chosen.
    CONVERTER_PACKS: tuple = ("vhf",)
    CONVERTER_DRIVE_REQUIRED = False
    CONVERTER_TEXT = "Transverters, LNBs and up/down-converters between the radio and the air."

    def page_converters(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Converters"), self.CONVERTER_TEXT)
        self.conv_editor = ConverterEditor(self.st.get("converters") or [], self.CONVERTER_PACKS,
                                           self._converter_ranges(), self.CONVERTER_DRIVE_REQUIRED,
                                           self._converter_in_use)
        lay.addWidget(self.conv_editor)
        self._converter_uses(lay)
        lay.addStretch(1)
        return sc

    def _converter_ranges(self) -> list[tuple[float, float, str]]:
        """On-air ranges the edit form's example line is worked out on:
        (lo, hi, "rx" | "tx" | "both")."""
        return []

    def _converter_in_use(self, title: str) -> str:
        """'' or what chooses converter `title` (so it cannot be deleted)."""
        return ""

    def _converter_uses(self, lay) -> None:
        """The app's choices of converter, under the list."""

    def _converter_combo(self, current: str, none: str | None, eligible=lambda c: True, key: str = "") -> QComboBox:
        """A choice of converter that follows the list as it is edited:
        `none` is the text for no converter ('' value), or None for a choice
        that must name one. A choice whose converter is renamed follows it.
        `key`, the state key it sets, lets tools/settings-ref.py list it
        with the dialog's other settings."""
        cb = QComboBox()
        if key:
            cb.setProperty("settingKey", key)
            cb.setProperty("settingNone", none or "")

        def fill():
            want = cb.currentData() if cb.count() else current
            cb.blockSignals(True)
            cb.clear()
            if none is not None:
                cb.addItem(none, "")
            for d in self.conv_editor.value():
                if eligible(d):
                    cb.addItem(d["title"], d["title"])
            i = cb.findData(want)
            if i < 0 and want:
                cb.addItem(QCoreApplication.translate("SettingsDialog", "{converter} (not in the list)")
                           .format(converter=want), want)
                i = cb.count() - 1
            cb.setCurrentIndex(max(0, i))
            cb.blockSignals(False)

        def renamed(old, new):
            if cb.currentData() == old:
                cb.setItemData(cb.currentIndex(), new)
            fill()

        fill()
        self.conv_editor.changed.connect(fill)
        self.conv_editor.renamed.connect(renamed)
        return cb

    def page_simulator(self) -> QWidget:
        sc, lay = self._scroll(QCoreApplication.translate("SettingsDialog", "Simulator"), self.SIM_TEXT)
        for k in self.SIM_KEYS:
            self._add(lay, k)
        lay.addStretch(1)
        return sc

    # ------------------------------------------------------------ actions
    def _pick_palette(self, name):
        self.palette = name
        for s in self.swatches:
            s.on = s.name == name
            s.update()

    def find_pluto(self):
        # The actual scan/probe/dedupe lives in the engine (ohscore.devices.
        # pluto.discover) so it's testable headless and reusable outside
        # this dialog; this method only turns its result into widgets and
        # a sentence. See discover()'s docstring for why a plain
        # iio.scan_contexts() isn't trusted on its own.
        notes: list[str] = []
        results = discover_pluto(notes=notes)
        self.pluto_found.clear()
        for uri, desc in results:
            self.pluto_found.addItem(f"{uri}  —  {desc}", uri)
        if not results:
            msg = QCoreApplication.translate(
                "SettingsDialog", "No Pluto found. Tried a full scan, USB, and ip:192.168.2.1 / ip:pluto.local "
                "directly. If it's connected by USB, try entering ip:192.168.2.1 above by hand - that works "
                "without any USB permissions.")
            if notes:
                msg = " ".join(notes) + " " + msg
            self._say(msg)
            self.pluto_found.hide()
        else:
            self.pluto_found.show()
            self.fields["plutoUri"].w.setText(self.pluto_found.currentData())
            self._say("")

    def find_soapy(self):
        try:
            import SoapySDR
            devs = SoapySDR.Device.enumerate()
        except ImportError:
            from .. import host
            self._say(host.hint("soapysdr"))
            return
        except Exception as e:  # noqa: BLE001
            self._say(QCoreApplication.translate("SettingsDialog", "Search failed: {error}").format(error=e))
            return
        self.soapy_found.clear()
        for d in devs:
            kv = {k: d[k] for k in d.keys()} if hasattr(d, "keys") else dict(d)
            args = ",".join(f"{k}={v}" for k, v in kv.items() if k in ("driver", "serial", "label") and v)
            self.soapy_found.addItem(kv.get("label", args) or args, args)
        if not devs:
            self._say(QCoreApplication.translate(
                "SettingsDialog", "No SoapySDR device found. Is the SDR plugged in, and its Soapy module installed?"))
            self.soapy_found.hide()
        else:
            self.soapy_found.show()
            self.fields["soapyArgs"].w.setText(self.soapy_found.currentData())
            self._say("")

    def _engine_audio(self):
        """The running engine's audio backend, or None - so the audio test
        can ride its stream instead of fighting it for the same ALSA device
        (see ohscore/ui/audiotest.py)."""
        radio = self.bridge.radio
        return radio.audio if radio.state().get("running") else None

    def _mic_test(self, on):
        if on:
            name = self.audio_combos["audioIn"].currentData() or ""
            err = self.tester.start_input(name, engine_audio=self._engine_audio())
            if err:
                self.audio_msg.setText(err)
                self.mic_test.set_on(False)
                return
            self.audio_msg.setText(QCoreApplication.translate(
                "SettingsDialog", "Speak normally: peaks should reach the amber, never the red."))
            self.timer.start()
        else:
            self.tester.stop_input()
            self.timer.stop()
            self.mic_meter.set_value(None)

    def _meter(self):
        self.mic_meter.set_value(self.tester.level())
        self.mic_meter.tick(0.05)

    def _tone(self):
        err = self.tester.tone(self.audio_combos["audioOut"].currentData() or "", engine_audio=self._engine_audio())
        self.audio_msg.setText(err or QCoreApplication.translate("SettingsDialog",
                                                                 "Playing a 700 Hz tone for one second."))

    def _say(self, text):
        self.error.setText(text)
        self.error.setVisible(bool(text))

    # ------------------------------------------------------------ save
    def collect(self) -> dict:
        changes = {}
        for k, f in self.fields.items():
            try:
                v = f.get()
            except licence_ui.FieldError:
                raise                              # already a whole sentence
            except ValueError:
                raise ValueError(QCoreApplication.translate("SettingsDialog", "{setting}: not a number")
                                 .format(setting=self.LABELS.get(k, k))) from None
            cur = self.st.get(k)
            if v != cur:
                changes[k] = v
        for k, cb in getattr(self, "audio_combos", {}).items():
            v = cb.currentData() or ""
            if v != self.st.get(k, ""):
                changes[k] = v
        ed = getattr(self, "conv_editor", None)
        if ed is not None and ed.value() != (self.st.get("converters") or []):
            changes["converters"] = ed.value()
        return changes

    def save(self):
        try:
            # The pad's keys first: the one part that can be refused for
            # what is happening now (moving PTT while on the air), and
            # refused, nothing else has changed either.
            if getattr(self, "pad_page", None) is not None:
                self.pad_page.store_map()
            meter_prefs = smeter.read_settings(self)
            changes = self.collect()
            if changes:
                self.bridge.radio.set(authorise=True, **changes)
        except ValueError as e:
            self._say(str(e))
            return
        self.restart_needed = any(self.spec[k]["restart"] for k in changes)
        p = self.prefs
        p["licenceAck"] = bool(self.licence.isChecked())
        self._store_diagnostics(p)
        smeter.store_settings(p, meter_prefs)
        pw = self.pref_widgets
        p["theme"] = pw["theme"].value
        p["textScale"] = layoutrules.nearest_scale(pw["textScale"].value)
        p["palette"] = self.palette
        p["wfAuto"] = pw["wfAuto"].on
        p["wfFloor"] = float(pw["wfFloor"].v)
        p["wfRange"] = float(pw["wfRange"].v)
        p["wfSpeed"] = float(pw["wfSpeed"].value)
        p["scopeLook"] = self.look_editor.stored()
        p["secondScreen"] = pw["secondScreen"].currentData() or ""
        p["secondFullScreen"] = pw["secondFullScreen"].on
        p["secondContent"] = pw["secondContent"].value
        want_second = pw["secondDisplay"].on
        if getattr(self, "pad_page", None) is not None:
            p["padTransmit"] = bool(self.pad_page.transmit.on)
            self.pad_page.stop()
        p.save()
        self.bridge.st.update(self.bridge.radio.state())
        self.tester.close()
        self.accept()
        parent = self.parent()
        if parent is not None and hasattr(parent, "toggle_second"):
            if want_second != (parent.second is not None):
                QTimer.singleShot(0, parent.toggle_second)

    def reject(self):
        self.tester.close()
        if getattr(self, "pad_page", None) is not None:
            self.pad_page.stop()
        super().reject()

    def sizeHint(self):
        return QSize(980, 720)

    def show_page(self, builder: str, anchor: str = ""):
        """Open on the page that `builder` makes ("page_display"), scrolled
        to `anchor` (an attribute naming a widget on it) if given - the
        adjust panel's "Colours..." lands on the scope colours."""
        i = next((n for n, (_i, _t, b) in enumerate(self.PAGES) if b == builder), None)
        if i is None:
            return
        self.nav.select(i)
        self.nav.k.value = float(i)
        self.stack.setCurrentIndex(i)
        w = getattr(self, anchor, None) if anchor else None
        page = self.stack.widget(i)
        if w is not None and hasattr(page, "ensureWidgetVisible"):
            # After the dialog has laid itself out; before, there is nothing to scroll.
            QTimer.singleShot(0, lambda: page.ensureWidgetVisible(w, 0, 40))
