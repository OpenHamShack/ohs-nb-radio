"""Radio › Dish alignment…: the window's half of dish alignment (the engine
measures: ohsnb/dishmeter.py, Radio.dish_open).

Decisions:

- **A window of its own, not modal**, so the bandscope stays in view behind
  it - the transponder coming up out of the noise is the other thing a
  dish-peaker watches - and the big number can be read from the dish on a
  laptop turned to face it.
- **Opening it is the engine's to refuse** (transmitting); the refusal is a
  toast and no window. While it is open transmit is refused with its own
  sentence, which the PTT button shows as any refusal.
- **Closing it is the only way back**: the gain, the tone and the phone
  page all end with the window, however it closes (button, Escape, the
  title bar, or the main window closing).
- **The phone page's addresses are shown, never guessed at by the user**:
  one line per address the machine has, selectable; on Windows, the
  firewall's question the first time is said beforehand, because the
  answer that blocks the phone is the one people click.
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QSpinBox, QVBoxLayout

from ohscore import host
from ohscore.ui import theme
from ohscore.ui.controls import Button, Card, Check

KEYS = ("dishOpen", "dishSnr", "dishBest", "dishRise", "dishWhere", "dishGain", "dishUrls", "dishPhoneError",
        "dishTone", "dishPhone", "dishPort", "running", "playing")
BAR_DB = 25.0             # the bar is full at this SNR: a good dish's beacon is 15-20 dB

def firewall() -> str:
    # A function, not a module constant: tr() must run once the catalog
    # is installed, which is after this module is imported.
    return QCoreApplication.translate(
        "DishDialog", "Windows asks the first time whether OpenHamShack QO-100 NB may accept connections: allow it on "
        "private networks, or the phone cannot reach the page.")


def db_text(v, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{float(v):+.1f}" if signed else f"{float(v):.1f}"


class DishDialog(QDialog):
    """The meter. Built only once Radio.dish_open() has accepted."""

    def __init__(self, win):
        super().__init__(win)
        self.win, self.bridge = win, win.bridge
        self.setWindowTitle(self.tr("Dish alignment - {app}").format(app=win.face.app_name))
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        h = QLabel(self.tr("Dish alignment"))
        h.setFont(theme.font(16, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        t = QLabel(self.tr("Move the dish a little at a time and watch the middle beacon: the higher, the better. "
                           "Transmit is off while this is open."))
        t.setWordWrap(True)
        t.setObjectName("Muted")
        lay.addWidget(t)

        card = Card()
        cl = card.lay
        cl.setSpacing(4)
        cap = QLabel(self.tr("Middle beacon, dB over the noise"))
        cap.setObjectName("Muted")
        cl.addWidget(cap, 0, Qt.AlignmentFlag.AlignHCenter)
        self.snr = QLabel("—")
        big = theme.font(96, theme.QFont.Weight.Bold, mono=True)
        self.snr.setFont(big)
        self.snr.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # Readable from the dish: the layout must never squash it.
        self.snr.setMinimumHeight(QFontMetrics(big).height())
        cl.addWidget(self.snr)
        self.bar = QProgressBar()
        self.bar.setRange(0, int(BAR_DB * 10))
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        # The theme's colours (the app's stylesheet has no progress bar):
        # the track as an input's, the fill the accent.
        tt = theme.t()
        self.bar.setStyleSheet(f"QProgressBar {{ background: {tt['bg2']}; border: 1px solid {tt['line']}; "
                               f"border-radius: 7px; }} QProgressBar::chunk {{ background: {tt['accent']}; "
                               f"border-radius: 6px; }}")
        cl.addWidget(self.bar)
        row = QHBoxLayout()
        self.best = QLabel(self.tr("Best {value}").format(value="—"))
        self.best.setFont(theme.font(20, theme.QFont.Weight.DemiBold, mono=True))
        row.addWidget(self.best)
        row.addStretch(1)
        self.btn_reset = Button(self.tr("Reset best"))
        self.btn_reset.clicked.connect(self.reset_best)
        row.addWidget(self.btn_reset)
        cl.addLayout(row)
        self.rise = QLabel("")
        self.rise.setFont(theme.font(15, theme.QFont.Weight.DemiBold))
        self.rise.setWordWrap(True)
        cl.addWidget(self.rise)
        self.where = QLabel("")
        self.where.setObjectName("Faint")
        self.where.setWordWrap(True)
        cl.addWidget(self.where)
        lay.addWidget(card)

        self.tone = Check(self.tr("Tone: a pitch that rises with the beacon, in place of the receive audio"))
        self.tone.toggled.connect(lambda on: self.bridge.set(dishTone=bool(on)))
        lay.addWidget(self.tone)

        self.phone = Check(self.tr("Phone page: the same numbers, and a tone, on a phone on this network"))
        self.phone.toggled.connect(self._phone_toggled)
        lay.addWidget(self.phone)
        row = QHBoxLayout()
        row.setContentsMargins(34, 0, 0, 0)
        row.addWidget(QLabel(self.tr("Port")))
        self.port = QSpinBox()
        spec = self.bridge.spec("dishPort")
        self.port.setRange(int(spec["min"]), int(spec["max"]))
        self.port.setValue(int(self.bridge.st.get("dishPort") or spec["default"]))
        self.port.editingFinished.connect(lambda: self.bridge.set(dishPort=int(self.port.value())))
        row.addWidget(self.port)
        row.addStretch(1)
        lay.addLayout(row)
        self.urls = QLabel("")
        self.urls.setTextFormat(Qt.TextFormat.PlainText)
        self.urls.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.urls.setFont(theme.font(15, theme.QFont.Weight.DemiBold, mono=True))
        self.urls.setContentsMargins(34, 0, 0, 0)
        lay.addWidget(self.urls)
        self.phone_note = QLabel("")
        self.phone_note.setWordWrap(True)
        self.phone_note.setObjectName("Faint")
        self.phone_note.setContentsMargins(34, 0, 0, 0)
        lay.addWidget(self.phone_note)

        self.gain = QLabel("")
        self.gain.setWordWrap(True)
        self.gain.setObjectName("Faint")
        lay.addWidget(self.gain)
        row = QHBoxLayout()
        row.addStretch(1)
        done = Button(self.tr("Close"))
        done.clicked.connect(self.close)
        row.addWidget(done)
        lay.addLayout(row)

        self.finished.connect(self._closed)
        self.bridge.changed.connect(self.on_state)
        self.sync()

    # ------------------------------------------------------------- the engine
    def _phone_toggled(self, on: bool):
        if on:
            # A port typed but not yet confirmed is the one meant.
            self.bridge.set(dishPort=int(self.port.value()), quiet=True)
        self.bridge.set(dishPhone=bool(on))
        self.sync()

    def reset_best(self):
        self.bridge.radio.dish_reset()
        self.bridge.st["dishBest"] = None
        self.sync()

    def _closed(self, *_):
        try:
            self.bridge.changed.disconnect(self.on_state)
        except TypeError:
            pass
        self.bridge.radio.dish_close()
        if getattr(self.win, "dish_dialog", None) is self:
            self.win.dish_dialog = None

    def closeEvent(self, e):
        # The title bar's close and Escape end it as Close does.
        self.done(0)
        super().closeEvent(e)

    def on_state(self, ch: dict):
        if any(k in ch for k in KEYS):
            self.sync()

    def sync(self):
        st = self.bridge.st
        snr = st.get("dishSnr")
        self.snr.setText(db_text(snr))
        self.bar.setValue(int(max(0.0, min(BAR_DB, float(snr or 0.0))) * 10))
        self.best.setText(self.tr("Best {value}").format(value=db_text(st.get("dishBest"))))
        rise = st.get("dishRise")
        if not st.get("running"):
            self.rise.setText(self.tr("The radio is not running."))
        elif rise is None:
            self.rise.setText(self.tr("Transponder: no room beside it to measure the noise at this sample rate"))
        else:
            self.rise.setText(self.tr("Transponder {db} dB over the noise beside it").format(
                db=db_text(rise, signed=True)))
        self.where.setText(st.get("dishWhere") or "")
        for box, key in ((self.tone, "dishTone"), (self.phone, "dishPhone")):
            box.blockSignals(True)
            box.setChecked(bool(st.get(key)))
            box.blockSignals(False)
        self.port.setEnabled(not st.get("dishPhone"))
        urls = [u for u in str(st.get("dishUrls") or "").split(", ") if u]
        self.urls.setText("\n".join(urls))
        self.urls.setVisible(bool(urls))
        err = st.get("dishPhoneError") or ""
        if err:
            note = err
        elif st.get("dishPhone"):
            note = self.tr("Open that address on a phone on the same network (Wi-Fi), and tap Tone on there. It "
                           "stops when you close this window.")
            if not urls:
                note = self.tr("No network address found: is this computer on a network?")
            if host.WINDOWS:
                note += " " + firewall()
        else:
            note = self.tr("Off: nothing is served.") + (" " + firewall() if host.WINDOWS else "")
        self.phone_note.setText(note)
        self.gain.setText(st.get("dishGain") or "")
        self._fit()

    def _fit(self):
        # Never shorter than what it holds. A window does not apply its
        # layout's height-for-width (the wrapped sentences, which appear
        # and grow: the phone page's addresses, the gain note), and the big
        # number was drawn squashed under the bar.
        h = self.layout().totalHeightForWidth(max(self.width(), self.minimumWidth()))
        if h > self.minimumHeight():
            self.setMinimumHeight(h)
        if h > self.height():
            self.resize(self.width(), h)


def open_dialog(win) -> DishDialog | None:
    """Radio › Dish alignment…: open it (or bring it forward if open). A
    refusal (transmitting) is a toast and no window."""
    d = getattr(win, "dish_dialog", None)
    if d is not None:
        d.raise_()
        d.activateWindow()
        return d
    try:
        win.bridge.radio.dish_open()
    except ValueError as e:
        win.bridge.say(str(e))
        return None
    st = win.bridge.radio.state()
    win.bridge.st.update(st)
    d = win.dish_dialog = DishDialog(win)
    d.show()
    return d
