"""File › Record receive IQ… and File › Open recordings folder.

The window's half of IQ recording (the engine records: ohscore/sigmf.py,
Engine.start_recording). Written for a tester asked to "send a sample":
one menu item, a dialog that says what it will cost before anything is
written, a red REC item in the status strip with the time and size while
it runs, and the same menu item (or Ctrl+Shift+R) to stop.

Decisions:

- **The cost is said first.** A minute is about 290 MB at 1.2 MS/s;
  someone recording on a laptop with a nearly full disk should find that
  out from the dialog, with the free space beside it, not from Windows.
- **The time limit is optional and remembered** (recLimitMin): a tester
  told "record two minutes" sets 2 once.
- **No pause.** A recording is one stretch of time; two are two files.
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout

from .. import host, sigmf
from . import theme
from .controls import Button
from .diagnostics import open_folder as _open


def rec_status(st: dict) -> str:
    """The status strip's REC item ('' when not recording): elapsed time,
    size, and the samples lost, if any."""
    if not st.get("recording"):
        return ""
    m, s = divmod(int(st.get("recSeconds") or 0), 60)
    out = f"● REC {m}:{s:02d}  {sigmf.size_text(float(st.get('recBytes') or 0))}"
    if st.get("recDropped"):
        out += "  " + QCoreApplication.translate("RecordDialog", "(samples dropped: disk too slow)")
    if st.get("recRxLost"):
        out += "  " + QCoreApplication.translate("RecordDialog", "(gaps in the radio's stream)")
    return out


def folder(win):
    return win.bridge.radio.recordings_dir()


def open_folder(win) -> bool:
    return _open(folder(win))


class RecordDialog(QDialog):
    """Says where, how big and for how long; Record starts it."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.bridge = win.bridge
        st = self.bridge.st
        fs = float(st.get("fs") or 0) or float(st.get("sampleRate") or 1_200_000)
        where = folder(win)
        self.setWindowTitle(self.tr("Record receive IQ - {app}").format(app=win.face.app_name))
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        h = QLabel(self.tr("Record receive IQ"))
        h.setFont(theme.font(16, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        t = QLabel(self.tr("Records exactly what the radio receives - everything the wide scope shows - so the "
                           "developers can analyse it, or play it back through the receiver. Nothing you transmit "
                           "is recorded."))
        t.setWordWrap(True)
        t.setObjectName("Muted")
        lay.addWidget(t)
        free = host.free_bytes(where)
        cost = sigmf.cost_sentence(fs)
        if free is not None:
            mins = free / sigmf.bytes_per_second(fs) / 60
            # A whole sentence for hours and one for minutes, each with its
            # own plural, rather than the count's phrase put into a third.
            if mins >= 120:
                room = self.tr("{free} is free there: room for about %n hour(s).", "", round(mins / 60))
            else:
                room = self.tr("{free} is free there: room for about %n minute(s).", "", round(mins))
            cost += " " + room.format(free=sigmf.size_text(free))
        self.cost = QLabel(cost)
        self.cost.setWordWrap(True)
        self.cost.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        lay.addWidget(self.cost)
        self.where = QLabel(str(where))
        self.where.setTextFormat(Qt.TextFormat.PlainText)
        self.where.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.where.setObjectName("Faint")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Stop by itself after")))
        self.limit = QSpinBox()
        self.limit.setRange(0, int(self.bridge.spec("recLimitMin")["max"]))
        self.limit.setSuffix(" min")
        self.limit.setSpecialValueText(self.tr("no limit"))
        self.limit.setValue(int(round(float(st.get("recLimitMin") or 0))))
        row.addWidget(self.limit)
        row.addStretch(1)
        lay.addLayout(row)
        n = QLabel(self.tr("Each recording is two files with the same name: .sigmf-data (the samples) and "
                           ".sigmf-meta (what they are). Send both."))
        n.setWordWrap(True)
        n.setObjectName("Faint")
        lay.addWidget(n)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        lay.addWidget(self.result_label)
        row = QHBoxLayout()
        b = Button(self.tr("Open folder"))
        b.clicked.connect(lambda: open_folder(win))
        row.addWidget(b)
        row.addStretch(1)
        cancel = Button(self.tr("Cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.btn_record = Button(self.tr("Record"), kind="danger")
        self.btn_record.clicked.connect(self.record)
        row.addWidget(self.btn_record)
        lay.addLayout(row)

    def record(self) -> bool:
        mins = self.limit.value()
        self.bridge.set(recLimitMin=float(mins), quiet=True)
        try:
            path = self.bridge.radio.start_recording(mins * 60.0 or 0.0)
        except ValueError as e:
            self.result_label.setText(str(e))
            return False
        self.bridge.st.update(recording=True, recSeconds=0.0, recBytes=0, recDropped=0, recRxLost=0, recFile=str(path))
        self.bridge.changed.emit({"recording": True})
        self.bridge.say(self.tr("Recording to {name}").format(name=path.name), "info")
        self.accept()
        return True


def toggle(win) -> None:
    """The menu item: stop the recording in progress, else ask to start one."""
    radio = win.bridge.radio
    if radio.state().get("recording"):
        radio.stop_recording()
        win.bridge.st.update(recording=False)
        win.bridge.changed.emit({"recording": False})
    else:
        RecordDialog(win).exec()
    sync(win)


def sync(win) -> None:
    """Keep the menu item's tick and text on what the engine is doing (a
    time limit ends a recording without the menu)."""
    act = getattr(win, "act_rec", None)
    if act is None:
        return
    on = bool(win.bridge.st.get("recording"))
    act.setChecked(on)
    # BaseWindow's context: this is its File menu item, whose first text
    # is written there (ohscore/ui/window.py).
    act.setText(QCoreApplication.translate("BaseWindow", "Stop recording") if on
                else QCoreApplication.translate("BaseWindow", "Record receive IQ…"))
