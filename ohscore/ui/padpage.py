"""Settings › Control pad: is the Ajazz AKP03E found and working, and if
not, why - in words the operator can act on, because the first people to
plug one in are remote and on Windows, where nobody has seen it run.

What is here and why:

- **Status, refreshed twice a second while the page is open**: found and
  open (which model, which HID path), held by another OpenHamShack app,
  not plugged in, or a problem (shack_pad.diagnose's sentence: close the
  Ajazz or Mirabox Stream Dock software, the udev rule is missing...).
- **"The pad may transmit"**, off until ticked (ohscore/ui/padlink.py says
  why). Saved with the dialog's Save, like every other setting here.
- **Keys and knobs**: what each key, button and knob does, one row each
  with the actions that control can run (ohscore/padmap.py has the rules:
  PTT only on a picture key and on one at most, unknown stored actions
  fall back to the default). Edited here and stored with Save, like the
  rest of the dialog; Cancel leaves the pad as it was. The pictures on the
  keys follow, because shack_pad draws each key from the mapping in force.
- **Test controller**: every key lights in turn, then each press shows on
  its own key and every key, button and knob event is listed here as it
  arrives. Nothing reaches the radio during the test - no tuning, and no
  transmit whatever the setting - and it cannot start while on the air.
- **Copy controller report**: the text to paste into an email
  (ohscore/padreport.py): what is plugged in, which interface would be
  opened, what this installation has for the pad, the problems and their
  times. No callsign, locator, tokens or serial numbers. Gathered on a
  thread - on Windows it lists the running programs, which takes a moment.

Pad events arrive on shack_pad's thread; a signal carries them to this
page, which Qt delivers on the window's thread.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from .. import padmap
from . import padlink, theme
from .controls import Button, Toggle

EVENT_ROWS = 40
log = logging.getLogger("ohscore.ui.padpage")


class _Relay(QObject):
    # Not "event": that would shadow QObject.event(), and Qt would call the
    # signal for every event the relay receives ("native Qt signal is not
    # callable" when a window closes).
    pad_event = pyqtSignal(str, str, int)   # kind, control, step: from the pad's thread
    report = pyqtSignal(str)                # the finished report, from the worker thread


class PadPage(QWidget):
    """`prefs` is the window's Prefs; `app_name`/`package` name the app in
    the report when there is no pad link to ask. `radio` (the engine) is
    where the key mapping is stored, in its station profile; without one
    the page has no mapping editor."""

    def __init__(self, prefs, app_name: str, package: str, parent=None, radio=None):
        super().__init__(parent)
        self.prefs, self.app_name, self.package, self.radio = prefs, app_name, package, radio
        self.relay = _Relay(self)
        self.relay.pad_event.connect(self._event)
        self.relay.report.connect(self._copied)
        self._listening = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.state = QLabel("")
        self.state.setWordWrap(True)
        self.state.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        lay.addWidget(self.state)
        self.detail = QLabel("")
        self.detail.setObjectName("Muted")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(f"color: {theme.t()['err']};")
        lay.addWidget(self.problem)

        self.transmit = Toggle(self.tr("The pad may transmit (hold the PTT key)"), bool(prefs["padTransmit"]))
        lay.addWidget(self.transmit)
        note = QLabel(self.tr(
            "Off until you turn it on. While it is off, the PTT key (K1 unless you move it below) shows PTT off "
            "and pressing it keys nothing; every other key and knob works. When on, it keys through every check "
            "the PTT button makes, and the transmitter stops if the pad is unplugged."))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)

        self._build_map(lay)

        row = QHBoxLayout()
        self.test_btn = Button(self.tr("Test controller"))
        self.test_btn.clicked.connect(self.toggle_test)
        self.copy_btn = Button(self.tr("Copy controller report"))
        self.copy_btn.clicked.connect(self.copy_report)
        row.addWidget(self.test_btn)
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        self.events = QListWidget()
        self.events.setMaximumHeight(160)
        lay.addWidget(self.events)
        hint = QLabel(self.tr(
            "Using the Ajazz or Mirabox Stream Dock software? Close it first, from the system tray too: both "
            "programs cannot drive the pad at once. If the pad still does not work, copy the controller report "
            "and send it to the developers."))
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # ---------------------------------------------------------- the mapping
    def _build_map(self, lay) -> None:
        """One row per control: K1-K6, B1-B3, then each knob's turn and
        press, each with the actions that control may run here."""
        self.map: padmap.PadMap | None = None
        self.map_rows: dict[tuple[str, str], QComboBox] = {}
        head = QLabel(self.tr("Keys and knobs"))
        head.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        lay.addWidget(head)
        if self.radio is None:
            return
        try:
            pkg = Path(__import__(type(self.radio).__module__.split(".")[0]).__file__).resolve().parent
            self.map = padmap.PadMap(pkg, self.radio.station.profile.get().get("controllerMaps") or {})
        except Exception as e:  # noqa: BLE001  the rest of the page still helps
            log.info("no pad mapping editor", exc_info=True)
            why = QLabel(self.tr("The keys cannot be changed here: {why}").format(why=e))
            why.setObjectName("Faint")
            why.setWordWrap(True)
            lay.addWidget(why)
            return
        about = QLabel(self.tr(
            "What each key, button and knob does in this app. The pictures on the keys follow. Changes take "
            "effect when you press Save."))
        about.setObjectName("Faint")
        about.setWordWrap(True)
        lay.addWidget(about)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for n, (cid, slot) in enumerate(self.map.rows()):
            grid.addWidget(QLabel(self._control_text(cid, slot)), n, 0)
            box = QComboBox()
            box.setAccessibleName(self._control_text(cid, slot))
            for aid in self.map.choices(cid, slot):
                box.addItem(self.action_text(aid), aid)
            box.activated.connect(lambda _i, c=cid, sl=slot, b=box: self._chosen(c, sl, b))
            grid.addWidget(box, n, 1)
            self.map_rows[(cid, slot)] = box
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        self.map_note = QLabel("")
        self.map_note.setWordWrap(True)
        lay.addWidget(self.map_note)
        row = QHBoxLayout()
        self.reset_btn = Button(self.tr("Reset to defaults"))
        self.reset_btn.clicked.connect(self.reset_map)
        row.addWidget(self.reset_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._show_map()

    def _control_text(self, cid: str, slot: str) -> str:
        if cid.startswith("K"):
            return self.tr("Key {control}").format(control=cid)
        if cid.startswith("B"):
            return self.tr("Button {control}").format(control=cid)
        if slot == "turn":
            return self.tr("Knob {control}, turned").format(control=cid)
        return self.tr("Knob {control}, pressed").format(control=cid)

    def action_text(self, aid: str) -> str:
        """An action as the drop-down lists it. One that this version has
        no words for (a newer declaration) is shown by its id."""
        words = {
            "none": self.tr("Nothing"), "none-turn": self.tr("Nothing"),
            "ptt": self.tr("PTT (hold to transmit)"), "halt": self.tr("Stop transmitting"),
            "tune": self.tr("Tune"), "tune:up": self.tr("Tune up one step"), "tune:down": self.tr("Tune down one step"),
            "step": self.tr("Next tuning step"), "mode:next": self.tr("Next mode"),
            "band": self.tr("Band"), "band:next": self.tr("Next band"),
            "band:up": self.tr("Band up"), "band:down": self.tr("Band down"),
            "channel": self.tr("Memories"), "channel:up": self.tr("Next memory"),
            "channel:down": self.tr("Previous memory"),
            "auto-tune": self.tr("Auto-tune"), "beacon-hold": self.tr("Beacon lock: Hold / Auto"),
            "mute": self.tr("Mute"), "volume": self.tr("Volume"),
            "volume:up": self.tr("Volume up"), "volume:down": self.tr("Volume down"),
            "nr": self.tr("Noise reduction on/off"), "filter": self.tr("Filter width"),
            "filter:up": self.tr("Filter wider"), "filter:down": self.tr("Filter narrower"),
            "record": self.tr("Record"), "power": self.tr("Transmit power"),
            "power:up": self.tr("Transmit power up"), "power:down": self.tr("Transmit power down"),
            "page": self.tr("Next page"),
        }
        return words.get(aid, aid)

    def _show_map(self) -> None:
        """Every row from the mapping (one choice can change another: PTT
        moves), and what the mapping means for transmitting."""
        pm = self.map
        for (cid, slot), box in self.map_rows.items():
            aid = pm.current(cid, slot)
            i = box.findData(aid)
            if i < 0:
                # Not offered here (a stored map from another version that
                # the library still accepts): shown as it is, not lost.
                box.addItem(self.action_text(aid), aid)
                i = box.count() - 1
            box.blockSignals(True)
            box.setCurrentIndex(i)
            box.blockSignals(False)
        key = pm.ptt_key()
        if key is None:
            self.map_note.setText(self.tr("No key is set to PTT, so the pad cannot transmit."))
        else:
            self.map_note.setText(self.tr("PTT is {key}: hold it to transmit.").format(key=key))
        self.reset_btn.setEnabled(not pm.is_default())

    def _chosen(self, cid: str, slot: str, box: QComboBox) -> None:
        try:
            self.map.set(cid, slot, box.currentData())
        except ValueError as e:
            self._say(str(e), False)
        self._show_map()

    def reset_map(self) -> None:
        if self.map is not None:
            self.map.reset()
            self._show_map()

    def store_map(self) -> None:
        """The dialog's Save: store the mapping if it was changed, and use it
        from the next press. ValueError (a sentence) when it cannot be
        stored now - moving the PTT key while on the air."""
        pm = self.map
        if pm is None or not pm.changed():
            return
        link = padlink.current()
        if link is not None:
            link.apply_map(pm)
        else:
            padmap.store(self.radio.station.profile, pm.kind, pm.entry())
        pm.stored = pm.entry()

    # ---------------------------------------------------------- showing
    def refresh(self) -> None:
        link = padlink.current()
        if link is None:
            self.state.setText(self.tr("Controller support is not running in this window."))
            self.state.setToolTip("")
            self.detail.setText(padlink.failure())
            self.problem.setText("")
            self.test_btn.setEnabled(False)
            return
        st = link.status()
        words = {
            "serving": self.tr("Connected: {name}."),
            "waiting": self.tr("Another OpenHamShack app has the pad. Click in this window to take it over."),
            "missing": self.tr("No controller found. Plug in the Ajazz AKP03E, with a data cable rather than a "
                               "charge-only one."),
            "error": self.tr("The controller is not working."),
            "idle": self.tr("Not in use by this window. Click in this window to take the pad."),
        }
        self.state.setText(words.get(st["state"], st["state"]).format(name=st.get("name", "")))
        # The system's own name for the device ("/dev/hidraw3", "\\?\HID#VID_0300...",
        # "DevSrvsID:4295056854" on a Mac) is for a fault report, which
        # carries it (Copy report), not for the page: shown as text it read as
        # debug output (Mac test 17/10/2026, finding 15). Kept as the state's
        # tooltip for whoever is asked to read it out.
        self.detail.setText("")
        path = st.get("path") or ""
        self.state.setToolTip(self.tr("The system's name for it: {path}").format(path=path) if path else "")
        self.problem.setText(st.get("error") or "")
        self.test_btn.setEnabled(st["state"] == "serving" or st.get("testing", False))
        testing = bool(st.get("testing"))
        self.test_btn.set_text(self.tr("Stop the test") if testing else self.tr("Test controller"))
        if not testing and self._listening is not None:
            self._stop_listening()

    def _say(self, text: str, ok: bool = True) -> None:
        self.result.setText(text)
        self.result.setStyleSheet(f"color: {theme.t()['ok' if ok else 'err']};")

    # ---------------------------------------------------------- the test
    def toggle_test(self) -> None:
        link = padlink.current()
        if link is None:
            return
        if link.testing():
            link.stop_test()
            self._stop_listening()
            self._say(self.tr("Test stopped."))
        else:
            try:
                link.start_test()
            except RuntimeError as e:
                self._say(str(e), False)
                return
            self.events.clear()
            self._listening = lambda model, ev: self.relay.pad_event.emit(ev[0], ev[1], int(ev[2]))
            link.add_listener(self._listening)
            self._say(self.tr("Testing: each key lights in turn. Now press every key and button and turn every "
                              "knob; each one shows below. Nothing reaches the radio during the test."))
        self.refresh()

    def _stop_listening(self) -> None:
        link = padlink.current()
        if link is not None and self._listening is not None:
            link.remove_listener(self._listening)
        self._listening = None

    def _event(self, kind: str, control: str, step: int) -> None:
        text = {"press": self.tr("{control} pressed"), "release": self.tr("{control} released"),
                "turn": self.tr("{control} turned {step:+d}")}.get(kind, "{control} {kind}")
        self.events.insertItem(0, text.format(control=control, step=step, kind=kind))
        while self.events.count() > EVENT_ROWS:
            self.events.takeItem(self.events.count() - 1)

    # ---------------------------------------------------------- the report
    def copy_report(self) -> None:
        self.copy_btn.setEnabled(False)
        self._say(self.tr("Gathering the controller report…"))
        link = padlink.current()

        def go():
            try:
                if link is not None:
                    text = link.report()
                else:
                    from .. import padreport
                    text = padreport.text(self.app_name, self.package, [f"pad link: {padlink.failure() or 'none'}"])
            except Exception as e:  # noqa: BLE001  said on the page, never a crash
                text = f"OpenHamShack controller report\n\ncould not be gathered: {e}\n"
            self.relay.report.emit(text)
        threading.Thread(target=go, name="pad-report", daemon=True).start()

    def _copied(self, text: str) -> None:
        self.last_report = text
        QGuiApplication.clipboard().setText(text)
        self.copy_btn.setEnabled(True)
        self._say(self.tr("Copied. Paste it into an email to the developers."))

    def stop(self) -> None:
        """The dialog is closing: no test left running, no listener left behind."""
        self.timer.stop()
        link = padlink.current()
        if link is not None and link.testing():
            link.stop_test()
        self._stop_listening()
