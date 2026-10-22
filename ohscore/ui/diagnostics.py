"""Help › Save diagnostics… and Help › Open log folder.

The window's half of ohscore/diag.py: what only Qt can supply (a picture of
the window, the screen's size and scaling) and the dialog the operator
saves the zip from. The aim is one file Ray can email Brian after an
on-air session, with nothing to find by hand in %APPDATA%.

Decisions:

- **Snapshot first, dialog second.** Everything is collected when the
  menu item is chosen, before the dialog opens, so the screenshot is the
  window as the operator was looking at it, not the dialog over it, and
  what the dialog lists is exactly what the zip will hold.
- **The window, not the desktop.** QWidget.grab() renders the main window
  only. A desktop grab could carry the operator's email or anything else
  open beside the radio; the window is all a report needs.
- **Shown before saved.** The dialog lists every file with its size and
  says what is in it (callsign and locator kept; secrets redacted) before
  anything is written, and Save… asks where. Nothing is sent anywhere:
  emailing it stays the operator's decision.
- **Desktop on Windows, home on Linux**, as the default place: where
  someone attaching a file to an email will look first. QStandardPaths
  finds a Desktop that OneDrive has moved.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QStandardPaths, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from .. import diag, host
from . import theme
from .controls import Button

log = logging.getLogger("ohscore.ui.diagnostics")


def screenshot_png(widget: QWidget) -> bytes:
    """The widget as it is drawn now, as PNG bytes ("" if it cannot be grabbed)."""
    pm = widget.grab()
    if pm.isNull():
        return b""
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return bytes(data)


def screen_facts(widget: QWidget) -> dict:
    """The window's screen and every other one: size, DPI, scale factor -
    what makes a caption clip on one laptop and not another."""
    out = {}
    scr = widget.screen() if widget is not None else None
    for i, s in enumerate(QGuiApplication.screens()):
        g, a = s.geometry(), s.availableGeometry()
        here = " (this window)" if s is scr else ""
        out[f"screen {i}{here}"] = (f"{s.name() or '?'}: {g.width()}x{g.height()} at {g.x()},{g.y()}, available "
                                    f"{a.width()}x{a.height()}, scale {s.devicePixelRatio():g}, logical DPI "
                                    f"{s.logicalDotsPerInch():.0f}, physical DPI {s.physicalDotsPerInch():.0f}")
    if widget is not None:
        out["window"] = f"{widget.width()}x{widget.height()}, scale {widget.devicePixelRatioF():g}"
    out["platform"] = QGuiApplication.platformName()
    for var in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_ENABLE_HIGHDPI_SCALING", "QT_QPA_PLATFORM"):
        if os.environ.get(var):
            out[var] = os.environ[var]
    return out


def gather(win, more: dict | None = None) -> list[tuple[str, bytes]]:
    """Everything a diagnostics zip holds, for the BaseWindow `win`.
    `more` is the app's own findings (HAM: a fresh Find and what the Pluto
    says it is, which matter most when the radio would not open), added to
    the report's "more" section and redacted with it."""
    radio = win.bridge.radio
    app_dir = radio.CONFIG.app.name
    setup = diag.current()
    f = dict(setup.facts) if setup is not None and setup.facts else {}
    if not f:
        # Not started through the app's main() (tests, the screenshot
        # tool): gather the facts now, the same way.
        pkg = type(radio).__module__.split(".")[0]
        f = diag.facts(win.face.app_name, diag.app_version(pkg), radio.data_dir, radio.cfg)
    elif radio.cfg.get("audioBackend", "portaudio") != "null":
        f["audio devices"] = diag.audio_devices()       # now, not as they were at start-up
    log.info("diagnostics requested")
    shot = screenshot_png(win)
    # What the GUI thread costs (a frame, a wide-scope paint, a line, the
    # last workspace switch): out of the status strip since the October
    # 2026 overhaul, and wanted here, where a report of receive overruns
    # during window work (Mac test FINDINGS 10) is read.
    timings = getattr(win, "timings_text", None)
    report = diag.build_report(f, radio.state(), device_context=radio.device_context(),
                               screen={**screen_facts(win), **({"window timings": timings()} if timings else {})},
                               extra={"log folder": str(log_folder(radio)), "config": str(_conf_path(radio)),
                                      "ui.json": str(win.prefs.path), **(more or {})})
    return diag.collect(app_dir, radio.data_dir, _conf_path(radio), win.prefs.path, report,
                        list(radio.status_lines), shot)


def _conf_path(radio) -> Path:
    return Path(radio.conf_path) if radio.conf_path else radio.CONFIG.conf_path()


def log_folder(radio) -> Path:
    setup = diag.current()
    if setup is not None and setup.app == radio.CONFIG.app.name:
        return setup.log_dir
    return diag.log_dir(radio.data_dir, radio.CONFIG.app.name)


def default_folder() -> Path:
    # The Desktop on Windows and macOS, where a saved report is found again
    # to attach to an e-mail; a Linux home folder is that place already.
    if host.WINDOWS or host.MACOS:
        d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if d and Path(d).is_dir():
            return Path(d)
    return Path.home()


def open_folder(path: Path) -> bool:
    """Show `path` in the system's file manager."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB" if n >= 1e3 else f"{n} bytes"


class DiagnosticsDialog(QDialog):
    """Lists what the zip holds; Save… writes it where the operator says."""

    def __init__(self, app_name: str, app_dir: str, entries: list[tuple[str, bytes]], parent=None):
        super().__init__(parent)
        self.app_dir = app_dir
        self.entries = entries
        self.saved: Path | None = None
        self.setWindowTitle(self.tr("Save diagnostics - {app}").format(app=app_name))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        h = QLabel(self.tr("Save diagnostics"))
        h.setFont(theme.font(16, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        t = QLabel(self.tr("One zip file to email to Brian. It holds {app}'s log, its settings, a report on this "
                           "computer and the radio, a picture of the main window and the last two minutes of "
                           "status. Your callsign and locator are included; anything that looks like a password "
                           "is removed. Nothing is sent: you choose where to save it.").format(app=app_name))
        t.setWordWrap(True)
        t.setObjectName("Muted")
        lay.addWidget(t)
        self.files = QListWidget()
        self.files.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for name, data in entries:
            self.files.addItem(f"{name}    {_size(len(data))}")
        self.files.setMinimumHeight(min(320, 26 * (len(entries) + 1)))
        lay.addWidget(self.files)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.result_label)
        row = QHBoxLayout()
        self.btn_folder = Button(self.tr("Open folder"))
        self.btn_folder.setEnabled(False)
        self.btn_folder.clicked.connect(self.open_saved_folder)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        close = Button(self.tr("Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.btn_save = Button(self.tr("Save…"), kind="primary")
        self.btn_save.clicked.connect(self.choose_and_save)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    def choose_and_save(self):
        start = default_folder() / diag.bundle_name(self.app_dir)
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save diagnostics"), str(start),
                                              self.tr("Zip files (*.zip)"))
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.save_to(Path(path))

    def save_to(self, path: Path) -> bool:
        try:
            diag.write_zip(path, self.entries)
        except OSError as e:
            self.result_label.setText(self.tr("Could not save {path}: {error}").format(path=path, error=e))
            log.warning("could not save diagnostics to %s: %s", path, e)
            return False
        self.saved = Path(path)
        log.info("diagnostics saved (%d files, %d bytes)", len(self.entries), self.saved.stat().st_size)
        self.result_label.setText(self.tr("Saved {path}. Attach it to an email to Brian.").format(path=self.saved))
        self.btn_folder.setEnabled(True)
        return True

    def open_saved_folder(self):
        if self.saved is not None:
            open_folder(self.saved.parent)


def save_diagnostics(win, more: dict | None = None) -> DiagnosticsDialog:
    """Help › Save diagnostics…: collect, then show the dialog (not exec'd
    here, so a test can drive it)."""
    t0 = time.monotonic()
    entries = gather(win, more)
    log.debug("diagnostics gathered in %.2f s", time.monotonic() - t0)
    return DiagnosticsDialog(win.face.app_name, win.bridge.radio.CONFIG.app.name, entries, win)
