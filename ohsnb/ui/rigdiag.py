"""Settings > Transmitter > "IC-9700 diagnostic…": the window over
ohsnb/rigdiag.py.

Two buttons, nothing on opening: "Run checks" (reads only, never
transmits) and "Run keyed checks…", which stays disabled until the
dummy-load box is ticked and then asks once more, naming the band and the
RF POWER the radio is set to, before anything is keyed. Stop (and the
main window's Halt and Escape) end a keyed check at once. The report
builds up in the box as each part finishes; "Copy report" puts it on the
clipboard and "Save report…" writes it to a .txt file, Documents by
default, for the operator to send.

The calls block for seconds, so each runs on a thread of its own and
reports back through a signal, one at a time, as in the setup assistant.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QGuiApplication
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                             QVBoxLayout)

from ohscore.ui.controls import Button
from ohsnb.rigdiag import RigDiagnostic, default_path


class _Relay(QObject):
    done = pyqtSignal(object, object, object)        # (what, result, error)
    said = pyqtSignal(str)


class RigDiagnosticDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent or settings)
        self.settings = settings
        self.radio = settings.bridge.radio
        self.busy = False
        self.diag: RigDiagnostic | None = None
        self.parts: dict[str, dict] = {}
        self.relay = _Relay()
        self.relay.done.connect(self._done)
        self.relay.said.connect(lambda text: self.state.setText(text))
        self.setWindowTitle(self.tr("IC-9700 diagnostic"))
        self.resize(760, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(6)
        intro = QLabel(self.tr("Gathers what NB can find out about the IC-9700 and its connection into a report "
                               "to send to the people who write NB. 'Run checks' only reads. 'Run keyed checks' "
                               "transmits four short overs of a tone, into a dummy load, on the band and at the "
                               "power the radio is set to; it changes no setting on the radio. The report holds "
                               "no callsign, locator or serial number."))
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        lay.addWidget(intro)
        r = QHBoxLayout()
        self.read_btn = Button(self.tr("Run checks"), icon="check", small=True)
        self.read_btn.clicked.connect(self.run_reads)
        r.addWidget(self.read_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.dummy = QCheckBox(self.tr("The IC-9700 is connected to a dummy load"))
        self.dummy.toggled.connect(lambda _on: self._enable())
        lay.addWidget(self.dummy)
        r = QHBoxLayout()
        self.keyed_btn = Button(self.tr("Run keyed checks…"), icon="send", kind="danger", small=True)
        self.keyed_btn.clicked.connect(self.run_keyed)
        self.stop_btn = Button(self.tr("Stop"), small=True)
        self.stop_btn.clicked.connect(self.stop)
        r.addWidget(self.keyed_btn)
        r.addWidget(self.stop_btn)
        r.addStretch(1)
        lay.addLayout(r)
        self.state = QLabel("")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        lay.addWidget(self.text, 1)
        r = QHBoxLayout()
        self.copy_btn = Button(self.tr("Copy report"), small=True)
        self.copy_btn.clicked.connect(self.copy)
        self.save_btn = Button(self.tr("Save report…"), small=True)
        self.save_btn.clicked.connect(self.save)
        r.addWidget(self.copy_btn)
        r.addWidget(self.save_btn)
        r.addStretch(1)
        close = Button(self.tr("Close"), kind="ghost")
        close.clicked.connect(self.close)
        r.addWidget(close)
        lay.addLayout(r)
        self._enable()

    # ------------------------------------------------------------ pieces
    def _enable(self) -> None:
        idle = not self.busy
        has = bool(self.parts)
        self.read_btn.setEnabled(idle)
        self.keyed_btn.setEnabled(idle and self.dummy.isChecked())
        self.stop_btn.setEnabled(self.busy)
        self.copy_btn.setEnabled(idle and has)
        self.save_btn.setEnabled(idle and has)

    def _diag(self) -> RigDiagnostic:
        """With the link settings as the Settings dialog has them now,
        saved or not (as the setup assistant does)."""
        changes = {}
        for k in self.settings.RIG_LINK_KEYS:
            if k in self.settings.fields:
                try:
                    changes[k] = self.settings.fields[k].get()
                except ValueError:
                    pass
        self.diag = RigDiagnostic(self.radio, changes)
        return self.diag

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _run(self, what: str, fn) -> None:
        self.busy = True
        self._enable()

        def go():
            try:
                result, error = fn(), None
            except Exception as e:  # noqa: BLE001 - every failure becomes the window's sentence
                result, error = None, e
            self.relay.done.emit(what, result, error)
        threading.Thread(target=go, name=f"ohsnb-rigdiag-{what}", daemon=True).start()

    def report(self) -> str:
        return RigDiagnostic.report(self.parts.get("reads"), self.parts.get("keyed"))

    # ------------------------------------------------------------ actions
    def run_reads(self) -> None:
        d = self._diag()
        self.state.setText(self.tr("Reading the IC-9700 (up to about fifteen seconds; nothing is transmitted)…"))
        self._run("reads", d.read_only)

    def run_keyed(self) -> None:
        if not self.dummy.isChecked():
            return
        d = self._diag()
        self.state.setText(self.tr("Reading the band and RF POWER…"))
        self._run("plan", d.keyed_plan)

    def _keyed_confirmed(self, plan: dict) -> None:
        rf = plan["rfPower"]
        power = (self.tr("RF POWER {pct} %").format(pct=round(rf * 100 / 255)) if rf is not None
                 else self.tr("RF POWER unknown"))
        if plan["watts"] is not None:
            power += self.tr(", about {w:.1f} W").format(w=plan["watts"])
        text = self.tr("NB will key the IC-9700 four times, each for up to six seconds, a second apart, with a "
                       "tone at levels from -40 dB up to NB's own - on {band} at {mhz:.3f} MHz, at {power}, as "
                       "the radio is set now. NB changes no setting on the radio. Is the {band} socket into a "
                       "dummy load?").format(band=plan["bandName"], mhz=(plan["mainHz"] or 0) / 1e6, power=power)
        if not self._confirm(self.tr("Transmit into the dummy load?"), text):
            self.state.setText(self.tr("Keyed checks not run."))
            return
        d, tick = self.diag, self.dummy.isChecked()
        self.state.setText(self.tr("Transmitting… (Stop, Halt or Escape ends it)"))
        self._run("keyed", lambda: d.keyed(tick, True, progress=self.relay.said.emit))

    def stop(self) -> None:
        if self.diag is not None:
            self.diag.cancel()
        else:
            self.radio.halt()

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.report())
        self.state.setText(self.tr("Report copied: paste it into an email or message."))

    def save(self, path: str | None = None) -> None:
        if path is None:
            docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            path, _f = QFileDialog.getSaveFileName(self, self.tr("Save report"),
                                                   str(default_path(Path(docs) if docs else None)),
                                                   self.tr("Text files (*.txt)"))
            if not path:
                return
        try:
            Path(path).write_text(self.report(), encoding="utf-8")
        except OSError as e:
            self.state.setText(self.tr("Could not save the report: {error}").format(error=e))
            return
        self.state.setText(self.tr("Report saved to {path}").format(path=path))

    # ------------------------------------------------------------ answers
    def _done(self, what: str, result, error) -> None:
        self.busy = False
        if error is not None:
            self.state.setText(str(error))
        elif what == "plan":
            self._enable()
            self._keyed_confirmed(result)
            return
        else:
            self.parts[what] = result
            self.text.setPlainText(self.report())
            if what == "reads":
                self.state.setText(self.tr("Checks done. Copy or save the report to send it."))
            elif result.get("result") == "stopped":
                self.state.setText(self.tr("Keyed checks stopped. What was measured is in the report."))
            else:
                self.state.setText(self.tr("Keyed checks done. Copy or save the report to send it."))
        self._enable()
