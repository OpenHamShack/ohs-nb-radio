"""Settings > Transmitter > "IC-9700 setup": the window over ohsnb/rigsetup.py.

Three steps, each started by its own button and nothing by opening the
window (rigsetup.py's docstring says what each does and why):

1. Find the radio - fills the CI-V address, baud rate and the IC-9700
   sound device into the Settings dialog behind it; Save keeps them, as
   for anything typed there. With two USB Audio CODECs and nothing to say
   which is the radio's, it chooses none and says so (Ray's PC, 12/10/2026,
   where the name match took his other radio's); "Which sound device?"
   in step 3 then finds it with a tone into the dummy load.
2. Check and set - a row per item, "now -> will be", a tick on each that
   would change; Apply asks once, listing exactly what will change, and
   "Restore the radio as it was" asks once too.
3. Set the audio level - transmits, so its button stays disabled until the
   dummy-load box is ticked and nothing stands in its way; Stop (and the
   main window's Halt and Escape) end it at once. What stands in its way
   is said above the button, with a button for each of the two NB can put
   right itself: CAT PTT off ("Turn on and save...", after saying what NB
   will then do with the radio) and no digital mode ("Choose FT8"). Until
   12/10/2026 the step only said so in red, a dead end inside a window
   whose point is to set things up. When no level is set, the readings
   are listed under the result, with where NB's log is, so an operator
   far away can send them.

The assistant's calls block for up to seconds (a CI-V address sweep, the
level set's over), so each runs on a thread of its own and reports back
through a signal; one at a time, and every button is disabled meanwhile.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout,
                             QWidget)

from ohscore import diag
from ohscore.ui import theme
from ohscore.ui.controls import Button
from ohsnb.rigsetup import MAX_S, RigSetup, find_codec


class _Relay(QObject):
    done = pyqtSignal(object, object, object)        # (what, result, error)
    step = pyqtSignal(dict)


class RigSetupDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent or settings)
        self.settings = settings
        self.radio = settings.bridge.radio
        self.busy = False
        self.rows: list[dict] = []
        self.ticks: dict[str, QCheckBox] = {}
        self.relay = _Relay()
        self.relay.done.connect(self._done)
        self.relay.step.connect(self._step)
        self.setWindowTitle(self.tr("IC-9700 setup"))
        self.resize(640, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(6)
        intro = QLabel(self.tr("Finds the IC-9700, checks the settings NB's digital modes need, and sets them "
                               "with your say-so. Steps 1 and 2 never transmit; step 3 does, into a dummy load. "
                               "Nothing here happens until you press its button."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)

        self._heading(lay, self.tr("1. Find the radio"))
        r = QHBoxLayout()
        self.find_btn = Button(self.tr("Find"), icon="antenna", small=True)
        self.find_btn.clicked.connect(self.find)
        r.addWidget(self.find_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.find_out = self._result(lay)

        self._heading(lay, self.tr("2. Check and set the radio"))
        r = QHBoxLayout()
        self.check_btn = Button(self.tr("Check"), icon="check", small=True)
        self.check_btn.clicked.connect(self.check)
        self.apply_btn = Button(self.tr("Apply…"), small=True)
        self.apply_btn.clicked.connect(self.apply)
        self.restore_btn = Button(self.tr("Restore the radio as it was"), small=True)
        self.restore_btn.clicked.connect(self.restore)
        for b in (self.check_btn, self.apply_btn, self.restore_btn):
            r.addWidget(b)
        r.addStretch(1)
        lay.addLayout(r)
        self.table = QWidget()
        self.grid = QGridLayout(self.table)
        self.grid.setContentsMargins(0, 4, 0, 4)
        lay.addWidget(self.table)
        self.check_out = self._result(lay)

        self._heading(lay, self.tr("3. Set the audio level (transmits)"))
        how = QLabel(self.tr("Sends a steady tone through the IC-9700 for up to {secs:.0f} seconds, the way NB "
                             "sends FT8, and raises NB's digital level until the radio's power stops rising, "
                             "keeping the lowest level that makes nearly all of it. NB's level is the one "
                             "adjusted; the radio's USB MOD Level is left alone unless it is at an extreme "
                             "(step 2 offers 50 %).").format(secs=MAX_S))
        how.setWordWrap(True)
        how.setObjectName("Faint")
        lay.addWidget(how)
        self.needs_out = self._result(lay)
        r = QHBoxLayout()
        self.cat_btn = Button(self.tr("Turn on CAT PTT and save…"), small=True)
        self.cat_btn.clicked.connect(self.cat_on)
        self.ft8_btn = Button(self.tr("Choose FT8"), small=True)
        self.ft8_btn.clicked.connect(self.choose_ft8)
        r.addWidget(self.cat_btn)
        r.addWidget(self.ft8_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.dummy = QCheckBox(self.tr("The IC-9700 is connected to a dummy load"))
        self.dummy.toggled.connect(lambda _on: self._enable())
        lay.addWidget(self.dummy)
        r = QHBoxLayout()
        self.level_btn = Button(self.tr("Set audio level"), icon="send", kind="danger", small=True)
        self.level_btn.clicked.connect(self.level)
        self.stop_btn = Button(self.tr("Stop"), small=True)
        self.stop_btn.clicked.connect(self.stop)
        self.codec_btn = Button(self.tr("Which sound device?…"), small=True)
        self.codec_btn.setToolTip(self.tr("Keys the IC-9700 briefly once per USB Audio CODEC, with a tone into each, "
                                          "and shows which one makes power: that one is the radio's."))
        self.codec_btn.clicked.connect(self.which_codec)
        r.addWidget(self.level_btn)
        r.addWidget(self.codec_btn)
        r.addWidget(self.stop_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.level_out = self._result(lay)
        lay.addStretch(1)
        r = QHBoxLayout()
        r.addStretch(1)
        close = Button(self.tr("Close"), kind="ghost")
        close.clicked.connect(self.close)
        r.addWidget(close)
        lay.addLayout(r)
        self._enable()

    # ------------------------------------------------------------ pieces
    def _heading(self, lay, text: str) -> None:
        lab = QLabel(text)
        lab.setFont(theme.caps(10.5))
        lab.setStyleSheet(f"color: {theme.t()['text3']}; padding-top: 14px;")
        lay.addWidget(lab)

    def _result(self, lay) -> QLabel:
        lab = QLabel("")
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(lab)
        return lab

    @staticmethod
    def _say(lab: QLabel, text: str, ok: bool | None = True) -> None:
        lab.setText(text)
        lab.setStyleSheet("" if ok is None else f"color: {theme.t()['ok' if ok else 'err']};")

    def _enable(self) -> None:
        idle = not self.busy
        self.find_btn.setEnabled(idle)
        self.check_btn.setEnabled(idle)
        self.apply_btn.setEnabled(idle and any(row["writes"] for row in self.rows))
        self.restore_btn.setEnabled(idle and bool(self._setup().saved()))
        needs = RigSetup(self.radio).level_needs()
        keys = {n["key"] for n in needs}
        self._say(self.needs_out, "\n".join(n["text"] for n in needs), False)
        self.needs_out.setVisible(bool(needs))
        self.cat_btn.setVisible("catPtt" in keys)
        self.ft8_btn.setVisible("mode" in keys)
        self.cat_btn.setEnabled(idle)
        self.ft8_btn.setEnabled(idle)
        self.level_btn.setEnabled(idle and self.dummy.isChecked() and not needs)
        self.codec_btn.setEnabled(idle and self.dummy.isChecked() and not needs)
        self.stop_btn.setEnabled(self.busy)

    def _setup(self) -> RigSetup:
        """The assistant with the link settings as the Settings dialog has
        them now, saved or not (as Test connection reads them)."""
        changes = {}
        for k in self.settings.RIG_LINK_KEYS:
            if k in self.settings.fields:
                try:
                    changes[k] = self.settings.fields[k].get()
                except ValueError:
                    pass
        return RigSetup(self.radio, changes)

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _run(self, what: str, fn) -> None:
        """fn() on its own thread; the answer comes back to _done."""
        self.busy = True
        self._enable()

        def go():
            try:
                result, error = fn(), None
            except Exception as e:  # noqa: BLE001 - every failure becomes the step's sentence
                result, error = None, e
            self.relay.done.emit(what, result, error)
        threading.Thread(target=go, name=f"ohsnb-rigsetup-{what}", daemon=True).start()

    # ------------------------------------------------------------ the steps
    def find(self) -> None:
        self._say(self.find_out, self.tr("Looking for the IC-9700 (up to about ten seconds)…"), None)
        s = self._setup()
        self._run("find", lambda: s.detect(cancel=lambda: not self.isVisible()))

    def check(self) -> None:
        s = self._setup()
        self._run("check", lambda: s.plan(s.read()))

    def apply(self) -> None:
        keys = {k for k, cb in self.ticks.items() if cb.isChecked()}
        chosen = [row for row in self.rows if row["writes"] and row["key"] in keys]
        if not chosen:
            self._say(self.check_out, self.tr("Nothing ticked to change."), None)
            return
        lines = "\n".join(f"• {row['label']}: {row['now']} → {row['will']}" for row in chosen)
        if not self._confirm(self.tr("Change the IC-9700?"),
                             self.tr("NB will change these on the IC-9700 (it does not transmit):\n\n{lines}\n\n"
                                     "What they were now is kept, and 'Restore the radio as it was' puts them "
                                     "back.").format(lines=lines)):
            return
        s, rows = self._setup(), list(self.rows)
        self._run("apply", lambda: s.apply(rows, keys))

    def restore(self) -> None:
        s = self._setup()
        if not self._confirm(self.tr("Restore the IC-9700?"),
                             self.tr("NB will put back the IC-9700 settings it changed, as they were before "
                                     "(it does not transmit).")):
            return
        self._run("restore", s.restore)

    def level(self) -> None:
        if not self.dummy.isChecked():
            return
        s = self._setup()
        self._say(self.level_out, self.tr("Transmitting a tone… (Stop, Halt or Escape ends it)"), None)
        self._run("level", lambda: s.level_set(self.dummy.isChecked(), progress=self.relay.step.emit))

    def stop(self) -> None:
        self.radio.halt()

    def which_codec(self) -> None:
        if not self.dummy.isChecked():
            return
        s, tick = self._setup(), self.dummy.isChecked()
        names = find_codec(s.outputs())
        if not names:
            self._say(self.level_out, self.tr("No USB Audio CODEC sound device found: is the IC-9700's USB cable "
                                              "connected?"), False)
            return
        if not self._confirm(self.tr("Find the radio's sound device?"),
                             self.tr("NB will key the IC-9700 {n} times, about three seconds each, into the dummy "
                                     "load, playing a tone into one USB Audio CODEC each time, and see which one "
                                     "makes power:\n\n{names}\n\nIf another radio is connected with VOX on, the "
                                     "tone could make it transmit: switch its VOX off first.").format(
                                 n=len(names), names="\n".join(f"• {n}" for n in names))):
            return
        self._say(self.level_out, self.tr("Trying each sound device… (Stop, Halt or Escape ends it)"), None)
        self._run("codec", lambda: s.which_codec(tick, names))

    def cat_on(self) -> None:
        """Switch CAT PTT on and save it, with the IC-9700 sound device the
        Settings dialog shows if that is not saved yet (Find fills it in
        unsaved), after saying what it means."""
        changes = {"rigCatPtt": True}
        device = self.settings.rig_audio.currentData() or ""
        if device and device != self.radio.st.get("rigTxAudioOut", ""):
            changes["rigTxAudioOut"] = device
        text = self.tr("NB will switch on 'Key the IC-9700 for digital modes' and save it. From then on NB keys the "
                       "IC-9700 by CAT for its own digital-mode overs - Enable TX in FT8 and FT4, and the lines you "
                       "send in PSK, RTTY and CW - in USB-D, with the audio to the radio's USB sound device. Never "
                       "for voice: you still key speech on the radio. Halt TX or Escape unkeys it at once, and you "
                       "can switch it off again in Settings > Transmitter.")
        if "rigTxAudioOut" in changes:
            text += "\n\n" + self.tr("It also saves the IC-9700 sound device: {name}.").format(name=device)
        if not self._confirm(self.tr("Let NB key the IC-9700?"), text):
            return
        try:
            self.radio.set(authorise=True, **changes)
        except ValueError as e:
            self._say(self.level_out, str(e), False)
            return
        # The Settings dialog behind this one would otherwise save its own
        # unticked toggle over it.
        self.settings.fields["rigCatPtt"].w.set_on(True)
        self._say(self.level_out, self.tr("CAT PTT is on and saved."), True)
        self._enable()

    def choose_ft8(self) -> None:
        self.radio.set(mode="ft8")
        self._enable()

    # ------------------------------------------------------------ answers
    def _step(self, step: dict) -> None:
        self._say(self.level_out, self.tr("NB's level {level:.0f} dB: power {po}, ALC {alc}").format(**step), None)

    def _done(self, what: str, result, error) -> None:
        self.busy = False
        if what == "find":
            self._found(result, error)
        elif what == "check":
            if error is None:
                self._show_rows(result)
            else:
                self._say(self.check_out, str(error), False)
        elif what in ("apply", "restore"):
            if error is None:
                self._say(self.check_out, "\n".join(result), True)
                self.rows = []
                self._show_rows([])
            else:
                self._say(self.check_out, str(error), False)
        elif what == "codec":
            self._codec_done(result, error)
        elif what == "level":
            if error is not None:
                self._say(self.level_out, str(error), False)
            else:
                text = result["text"]
                if result["result"] != "set" and result["steps"]:
                    text += "\n\n" + self._readings(result)
                self._say(self.level_out, text, result["result"] == "set")
                if result["result"] == "set" and "rigTxAudioDb" in self.settings.fields:
                    self.settings.fields["rigTxAudioDb"].w.set_value(result["level"])
        self._enable()

    def _readings(self, result: dict) -> str:
        """The level set's readings, for an operator to send on."""
        lines = [self.tr("Readings (USB MOD Level {usb}, RF POWER {rf}):").format(
            usb=f"{round(result['usbMod'] * 100 / 255)} %",
            rf="?" if result.get("rfPower") is None else f"{round(result['rfPower'] * 100 / 255)} %")]
        for s in result["steps"]:
            lines.append(self.tr("  {level:.0f} dB: Po {po}, ALC {alc}").format(**s)
                         + (self.tr(" (passed over)") if s.get("dropout") else ""))
        setup = diag.current()
        if setup is not None:
            lines.append(self.tr("They are also in NB's log: {path}").format(path=setup.path))
        return "\n".join(lines)

    def _codec_done(self, result, error) -> None:
        if error is not None:
            self._say(self.level_out, str(error), False)
            return
        lines = [self.tr("  {name}: Po {po}").format(name=n, po=po) for n, po in result["po"].items()]
        if result["radio"]:
            self._choose_audio(result["radio"])
            self._say(self.level_out, "\n".join([self.tr("{name} makes power: it is the IC-9700's, and is chosen. "
                                                          "Save Settings to keep it.").format(name=result["radio"])]
                                                 + lines), True)
        else:
            self._say(self.level_out, "\n".join([self.tr("No single sound device made the IC-9700 transmit power, "
                                                          "so none was chosen. Check DATA MOD (step 2) and that "
                                                          "the radio is into the dummy load:")] + lines), False)

    def _choose_audio(self, name: str) -> None:
        cb = self.settings.rig_audio
        i = cb.findData(name)
        if i < 0:
            cb.addItem(name, name)
            i = cb.count() - 1
        cb.setCurrentIndex(i)

    def _found(self, result, error) -> None:
        if error is not None:
            self._say(self.find_out, str(error), False)
            return
        lines = []
        if result["address"] is None:
            lines.append(self.tr("No IC-9700 answered on that port at any baud rate or CI-V address. Is it on, and "
                                 "is the port right (Settings > Transmitter)?"))
        else:
            self.settings.fields["civAddress"].w.setText(f"{result['address']:02X}")
            if "civBaud" in self.settings.fields:
                self.settings.fields["civBaud"].w.set_value(str(result["baud"]))
            lines.append(self.tr("The radio answers at CI-V address {addr:02X}h, {baud} baud: filled in.").format(
                addr=result["address"], baud=result["baud"]))
        names, pick = result["audio"], result.get("pick")
        if pick:
            self._choose_audio(pick)
            if len(names) > 1:
                lines.append(self.tr("{n} USB Audio CODEC sound devices (one per radio): {name} is on the same USB "
                                     "hub as this radio's CI-V port, and is chosen.").format(n=len(names), name=pick))
            else:
                lines.append(self.tr("Its sound device is {name}: chosen.").format(name=pick))
        elif names:
            lines.append(self.tr("{n} USB Audio CODEC sound devices (one per radio): {names}. NB cannot tell from "
                                 "where they sit on USB which is this radio's, so it has chosen none. Choose it in "
                                 "Settings, or tick the dummy load below and use 'Which sound device?'.").format(
                n=len(names), names=", ".join(names)))
        else:
            lines.append(self.tr("No USB Audio CODEC sound device found: is the IC-9700's USB cable connected?"))
        lines.append(self.tr("Save Settings to keep them."))
        self._say(self.find_out, "\n".join(lines), result["address"] is not None and bool(pick))

    def _show_rows(self, rows: list[dict]) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.rows, self.ticks = rows, {}
        for i, row in enumerate(rows):
            tick = QCheckBox(row["label"])
            tick.setChecked(bool(row["writes"]))
            tick.setEnabled(bool(row["writes"]))
            self.ticks[row["key"]] = tick
            self.grid.addWidget(tick, i, 0)
            self.grid.addWidget(QLabel(row["now"]), i, 1)
            self.grid.addWidget(QLabel("→"), i, 2)
            self.grid.addWidget(QLabel(row["will"]), i, 3)
        if rows:
            n = sum(1 for row in rows if row["writes"])
            self._say(self.check_out, self.tr("{n} to change: untick any to leave, then Apply.").format(n=n)
                      if n else self.tr("The IC-9700 is set up as NB needs it."), True if not n else None)
        self._enable()
