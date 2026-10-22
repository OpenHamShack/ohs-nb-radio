"""File › Play IQ recording…, File › Back to the radio, File › Loop playback.

The window's half of playback (the engine plays: Engine.start_playback,
ohscore/devices/filedev.py). Decisions:

- **One menu item both ways**, as Record is: "Play IQ recording…" opens a
  file chooser in the recordings folder (either file of a pair will do);
  while playing it reads "Back to the radio". Ctrl+Shift+P.
- **Playback must never be mistaken for the air.** The status strip's
  first item, where the radio's name stands, becomes a PLAYBACK item in
  the accent colour with the file's name, the position and when the sample
  playing was recorded; the strip's own clock stays the wall clock.
- **Transmit says why it is off**: the engine's sentence ("Playing a
  recording: there is no transmitter...") reaches the PTT button through
  txBlocked, as any refusal does.
- Back to the radio may open real hardware, so it is only ever the
  operator's choice - the end of a recording leaves it playing silence and
  says so.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import QFileDialog

from ..devices import DeviceError


def play_status(st: dict) -> str:
    """The status strip's PLAYBACK item ('' when not playing)."""
    if not st.get("playing"):
        return ""
    name = str(st.get("playFile") or "")
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if name.endswith(".sigmf-data"):
        name = name[:-len(".sigmf-data")]

    def mmss(s):
        m, s = divmod(int(s or 0), 60)
        return f"{m}:{s:02d}"

    out = f"▶ PLAYBACK  {name}  {mmss(st.get('playPos'))} / {mmss(st.get('playLength'))}"
    utc = float(st.get("playUtc") or 0)
    if utc:
        out += f"  recorded {time.strftime('%H:%M:%S UTC', time.gmtime(utc))}"
    if st.get("playEnded"):
        out += "  (ended)"
    elif st.get("playLoop"):
        out += "  (looping)"
    return out


def _refresh(win) -> None:
    b = win.bridge
    b.st = b.radio.state()
    b.changed.emit(dict(b.st))
    sync(win)


def play(win, path) -> bool:
    """Play `path`; a refusal is a toast and the radio stays as it was."""
    try:
        win.bridge.radio.start_playback(path)
    except ValueError as e:
        win.bridge.say(str(e))
        _refresh(win)
        return False
    _refresh(win)
    return True


def back(win) -> str:
    """Back to the radio; '' or the sentence why it did not start."""
    err = ""
    try:
        win.bridge.radio.stop_playback()
    except DeviceError as e:
        err = str(e)
    _refresh(win)
    after = getattr(win, "after_start", None)
    if after is not None:
        after(err)
    elif err:
        win.bridge.say(err, "error")
    return err


def choose(win) -> str:
    """Ask for a recording: '' when the operator cancels."""
    where = win.bridge.radio.recordings_dir()
    # Under BaseWindow's context: these are its File menu item's words
    # (ohscore/ui/window.py), as recording.py's are.
    path, _ = QFileDialog.getOpenFileName(win, QCoreApplication.translate("BaseWindow", "Play IQ recording"),
                                          str(where if where.exists() else where.parent),
                                          QCoreApplication.translate(
                                              "BaseWindow", "SigMF recordings (*.sigmf-meta *.sigmf-data);;All "
                                                            "files (*)"))
    return path


def toggle(win) -> None:
    """The menu item: back to the radio while playing, else choose a recording."""
    if win.bridge.radio.state().get("playing"):
        back(win)
        return
    path = choose(win)
    if path:
        play(win, path)
    else:
        sync(win)


def sync(win) -> None:
    """Menu items on what the engine is doing."""
    act = getattr(win, "act_play", None)
    if act is None:
        return
    st = win.bridge.st
    on = bool(st.get("playing"))
    act.setChecked(on)
    act.setText(QCoreApplication.translate("BaseWindow", "Back to the radio") if on
                else QCoreApplication.translate("BaseWindow", "Play IQ recording…"))
    win.act_loop.setChecked(bool(st.get("playLoop")))
    # A recording of a recording is refused by the engine; the menu says so first.
    if getattr(win, "act_rec", None) is not None:
        win.act_rec.setEnabled(not on)
