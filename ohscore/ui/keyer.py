"""The voice keyer's window side: a row of memory buttons for the voice
mode panels (USB/LSB/AM/FreeDV, and HAM's FM) and the dialog that names,
records, previews, imports and clears them.

The engine does the work (ohscore/keyer.py, Engine.send_voice); this only
asks it. Sending goes through Bridge.send_voice, which holds the licence
acknowledgement like every other key-up from the window.

F1 ... F6 reach the bar through BaseWindow.fire_macro, the same way they
reach the CW and keyboard macros in those modes: one row of function keys,
whichever kind of memory the mode has. A key that transmits does so only
with its button in view (fire_macro's rule): not over the Logbook, not
from the second display's mirror.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QVBoxLayout, QWidget)

from .. import keyer as keyer_mod
from . import theme
from .controls import Button, Caption, Slider, Toggle
from .meters import BarMeter


class VoiceKeyerBar(QWidget):
    """F1 ... F6 for the voice memories, a Repeat toggle and Edit. A grid
    that re-flows with the width, as the macro bar does: one row of six on
    a wide screen, two of three in a laptop's narrow card. `inline` puts
    the toggle and Edit on the buttons' row and leaves out the caption, for
    a card of its own titled "Voice keyer" (HAM's FM panel, whose three
    cards have no room for it inside one)."""

    def __init__(self, bridge, parent=None, inline: bool = False):
        super().__init__(parent)
        self.bridge = bridge
        self.slots = bridge.radio.keyer.slots
        self.inline = inline
        lay = QHBoxLayout(self) if inline else QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if not inline:
            lay.addWidget(Caption(self.tr("Voice keyer")))
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(6)
        lay.addLayout(self.grid, 1)
        self.buttons: list[Button] = []
        for i in range(self.slots.n):
            b = Button("", small=True)
            b.clicked.connect(lambda i=i: self.trigger(i))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p: self.open_editor())
            self.buttons.append(b)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.repeat = Toggle(self.tr("Repeat"), bool(bridge.st.get("keyerRepeat")))
        self.repeat.toggled.connect(lambda on: bridge.set(keyerRepeat=on))
        self.every = QLabel("")
        self.every.setObjectName("Faint")
        self.edit = Button(self.tr("Edit…"), small=True, kind="ghost")
        self.edit.clicked.connect(self.open_editor)
        row.addWidget(self.repeat)
        row.addWidget(self.every)
        if not inline:
            row.addStretch(1)
        else:
            row.insertSpacing(0, 10)
        row.addWidget(self.edit)
        lay.addLayout(row)
        self.cols = 0
        self.rebuild()

    def rebuild(self):
        """Labels from the slots on disk (after the editor, or a rename)."""
        for i, b in enumerate(self.buttons):
            secs = self.slots.seconds(i)
            name = self.slots.name(i)
            b.set_text(f"F{i + 1}  {name}" if name else f"F{i + 1}")
            b.setToolTip(self.tr("{memory}: {secs} s - sends it (F{key})").format(
                             memory=self.slots.label(i), secs=f"{secs:.1f}", key=i + 1) if secs else
                         self.tr("Voice memory {n} is empty: Edit… records it").format(n=i + 1))
            b.setEnabled(secs > 0)
        self._every()
        self.cols = 0
        self._flow()

    def _every(self):
        self.every.setText(self.tr("every {secs} s").format(
            secs=f"{float(self.bridge.st.get('keyerRepeatSec', 10)):.0f}"))

    def open_editor(self):
        open_editor(self.bridge, self.window())
        self.rebuild()

    def trigger(self, i: int) -> bool:
        """Send memory i (a button or its F-key). False when there is
        nothing to send or the bar is not in view."""
        if not 0 <= i < len(self.buttons) or not self.isVisible():
            return False
        if self.slots.seconds(i) <= 0:
            self.bridge.say(self.tr("Voice memory {n} is empty: record it first (Radio › Voice memories…)")
                            .format(n=i + 1))
            return True
        self.bridge.send_voice(i)
        return True

    def on_state(self, ch: dict):
        if "keyerRepeat" in ch:
            self.repeat.set_on(bool(ch["keyerRepeat"]))
        if "keyerRepeatSec" in ch:
            self._every()

    def _flow(self):
        w = max(1, self.width())
        cols = 6 if self.inline or w >= 6 * 96 else 3
        if cols == self.cols:
            return
        self.cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, b in enumerate(self.buttons):
            self.grid.addWidget(b, i // cols, i % cols)

    def resizeEvent(self, e):
        self._flow()
        super().resizeEvent(e)

    def showEvent(self, e):
        # The editor may have changed the slots while another panel showed.
        self.rebuild()
        super().showEvent(e)


class VoiceKeyerDialog(QDialog):
    """Radio › Voice memories…: per slot, its name, length, Record/Stop,
    Play (to the speaker - never transmits), Import WAV… and Clear; and
    the repeat pause. Recording and playing use the running radio's own
    microphone and speaker, so what is recorded is what PTT would send."""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.keyer = bridge.radio.keyer
        self.slots = self.keyer.slots
        self.setWindowTitle(self.tr("Voice memories"))
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        hint = QLabel(self.tr("Up to {n} recorded messages, sent with F1 to F{n} in the voice modes (or their "
                              "buttons on the mode panel). They go through your mic gain, compressor and transmit "
                              "filter, and every transmit check, exactly as your voice would. Play listens on the "
                              "speaker and does not transmit. Recording stops by itself after {secs} s.").format(
                                  n=self.slots.n, secs=f"{keyer_mod.MAX_SECONDS:.0f}"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.meter = BarMeter(self.tr("Mic level"), -60, 0, lambda v: f"{v:.0f}", ticks=(-60, -40, -20, -10, 0),
                              zones=((-60, -20, "ok"), (-20, -6, "ok"), (-6, -3, "warn"), (-3, 0, "err")),
                              unit="dBFS")
        lay.addWidget(self.meter)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.rows = []
        for i in range(self.slots.n):
            key = QLabel(f"F{i + 1}")
            key.setFont(theme.font(13, theme.QFont.Weight.DemiBold, mono=True))
            name = QLineEdit(self.slots.name(i))
            name.setPlaceholderText(self.tr("Memory {n}").format(n=i + 1))
            name.setMaxLength(24)
            name.setMinimumWidth(150)
            name.editingFinished.connect(lambda i=i, w=name: self._rename(i, w.text()))
            length = QLabel("")
            length.setFont(theme.font(12, mono=True))
            length.setMinimumWidth(64)
            rec = Button(self.tr("Record"), small=True)
            rec.clicked.connect(lambda i=i: self._record(i))
            play = Button(self.tr("Play"), small=True)
            play.clicked.connect(lambda i=i: self._play(i))
            imp = Button(self.tr("Import WAV…"), small=True, kind="ghost")
            imp.clicked.connect(lambda i=i: self._import(i))
            clr = Button(self.tr("Clear"), small=True, kind="ghost")
            clr.clicked.connect(lambda i=i: self._clear(i))
            for c, w in enumerate((key, name, length, rec, play, imp, clr)):
                if isinstance(w, Button):
                    # Small buttons may elide in a crowded row; here there is room.
                    w.setMinimumWidth(max(w.sizeHint().width(), 64))   # "Play" becomes "Stop"
                g.addWidget(w, i, c)
            self.rows.append({"name": name, "length": length, "rec": rec, "play": play, "imp": imp, "clr": clr})
        lay.addLayout(g)
        sp = bridge.radio.STATE.spec["keyerRepeatSec"]
        self.pause = Slider(self.tr("Repeat: pause between calls"), sp["min"], sp["max"],
                            float(bridge.st.get("keyerRepeatSec", sp["default"])), 1, lambda v: f"{v:.0f} s",
                            default=sp["default"])
        self.pause.committed.connect(lambda v: bridge.set(keyerRepeatSec=v))
        lay.addWidget(self.pause)
        self.status = QLabel("")
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        close = Button(self.tr("Close"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._refresh()

    # ----------------------------------------------------------------- actions
    def _say(self, text: str):
        self.status.setText(text)

    def _rename(self, i: int, text: str):
        try:
            self.slots.rename(i, text)
        except OSError as e:
            self._say(self.tr("Could not save the name: {error}").format(error=e.strerror or e))

    def _record(self, i: int):
        # A recording that has stopped by itself (the time limit, a key-up)
        # still has its thread until someone collects it, and its button
        # still says Stop until the next tick: a press then is that Stop,
        # not a new recording - which would have recorded over the memory
        # just made. The suite's microphone is faster than real time, so it
        # reached the limit before the test's Stop and showed this.
        if self.keyer.recording() is not None or self.keyer.rec_thread is not None:
            self._say(self.keyer.stop_recording())
            self._refresh()
            return
        try:
            self.keyer.record(i)
        except ValueError as e:
            self._say(str(e))
            return
        self._say(self.tr("Recording F{key}… speak now; press Stop when done.").format(key=i + 1))
        self._refresh()

    def _play(self, i: int):
        if self.keyer.previewing() is not None:
            self.keyer.stop_preview()
            self._refresh()
            return
        try:
            secs = self.keyer.preview(i)
        except ValueError as e:
            self._say(str(e))
            return
        self._say(self.tr("Playing F{key} on the speaker ({secs} s) - not transmitting.").format(
            key=i + 1, secs=f"{secs:.1f}"))
        self._refresh()

    def _import(self, i: int):
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Import a WAV into F{key}").format(key=i + 1), "",
                                              self.tr("WAV files (*.wav)"))
        if path:
            self.import_file(i, path)

    def import_file(self, i: int, path: str) -> bool:
        """Import `path` into slot i (the file dialog's choice; tests call it)."""
        try:
            secs = self.slots.store(i, keyer_mod.read_wav(path))
        except (ValueError, OSError) as e:
            self._say(str(e))
            return False
        self._say(self.tr("Imported into F{key}: {secs} s").format(key=i + 1, secs=f"{secs:.1f}"))
        self._refresh()
        return True

    def _clear(self, i: int):
        if self.keyer.recording() is not None or self.keyer.previewing() is not None:
            self._say(self.tr("Stop recording or playing first"))
            return
        self.slots.clear(i)
        self._refresh()

    # ----------------------------------------------------------------- display
    def _refresh(self):
        rec = self.keyer.recording()
        play = self.keyer.previewing()
        busy = rec is not None or play is not None
        for i, r in enumerate(self.rows):
            secs = self.slots.seconds(i)
            if rec is not None and rec["slot"] == i:
                r["length"].setText(f"{rec['seconds']:.1f} s")
            else:
                r["length"].setText(f"{secs:.1f} s" if secs else self.tr("empty"))
            recording = rec is not None and rec["slot"] == i
            r["rec"].set_text(self.tr("Stop") if recording else self.tr("Record"))
            r["rec"].setEnabled(recording or not busy)
            playing = play == i
            r["play"].set_text(self.tr("Stop") if playing else self.tr("Play"))
            r["play"].setEnabled(playing or (not busy and secs > 0))
            r["imp"].setEnabled(not busy)
            r["clr"].setEnabled(not busy and secs > 0)

    def _tick(self):
        rec = self.keyer.recording()
        self.meter.set_value(rec["level"] if rec is not None else None)
        self.meter.tick(0.1)
        if rec is None and self.keyer.rec_thread is not None:
            # It stopped by itself (the time limit, or a key-up took the mic).
            self._say(self.keyer.stop_recording())
        self._refresh()

    def done(self, r):
        self.timer.stop()
        if self.keyer.recording() is not None:
            self._say(self.keyer.stop_recording())
        self.keyer.stop_preview()
        super().done(r)


def open_editor(bridge, parent=None) -> None:
    """The editor, modal: Radio › Voice memories…, a bar's Edit…, or a
    right-click on one of its buttons."""
    d = VoiceKeyerDialog(bridge, parent)
    d.exec()
