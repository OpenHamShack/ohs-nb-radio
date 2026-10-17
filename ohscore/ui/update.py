"""The window's half of self-update: when to check, the banner, Help ›
Check for updates…, and installing (ohscore/update.py does the proving).

Decisions, Brian's of 07/10/2026 and what follows from them:

- **Checked at start-up, never delaying it.** run() starts the controller
  after the window is on screen; the first check is a few seconds later,
  on a thread, then the schedule looks every ten minutes and checks once a
  day (update.Schedule). Checking is automatic only for an installed copy
  (the .deb or the Windows installer): a run from source has nothing to
  install, and the test suite and the screenshot tools never fetch
  anything unless asked. Help › Check for updates… checks on demand,
  whatever kind of copy it is and whatever the setting says.
- **Quiet when it fails.** Offline, refused or broken checks are logged and
  shown in Help › Check for updates…, never as a toast: an operator with no
  network on a field day must not be nagged about it.
- **A banner, not a dialog.** A new version is a strip above the scopes:
  "QO-100 NB 0.1.9 is available - Install and restart / Later / What's
  new". Later hides it until the next start (or a check by hand).
- **Nothing that touches the radio's work.** Install and restart is
  refused while transmitting or recording (the button says why), the
  automatic check waits until the over ends, and a download that finishes
  mid-over waits for another click. The restart itself is a normal close -
  closeEvent unkeys and saves - and the new copy starts only after this
  process has exited (atexit), so the two never hold the radio at once.
- **Linux:** pkexec apt-get install, with the desktop's own password
  prompt, then "Restart now". Without pkexec the banner shows the command.
- **Windows:** the installer's Authenticode signer is checked as well, then
  it runs unattended once this process has exited, and starts the program
  again itself (packaging/windows/self-update.iss).
- **macOS (07/10/2026):** the .dmg is downloaded and proved like the
  others, then opened in Finder for the operator to drag across - nothing
  is replaced behind their back while the build is unsigned
  (update.install_command says why). The button says "Download", not
  "Install and restart", so it never promises what it will not do.
"""
from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from .. import diag, update
from . import theme
from .controls import Button

log = logging.getLogger("ohscore.update")


def _run(argv: list[str]) -> tuple[int, str]:
    import subprocess
    try:
        res = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)
    return res.returncode, (res.stdout + res.stderr)[-2000:]


def _at_exit(argv: list[str]) -> None:
    atexit.register(update.spawn_detached, argv)


class UpdateBanner(QFrame):
    """The strip above the scopes. Shows whatever the controller says; the
    window rebuilds it with the theme, and the controller fills the new one."""

    primary = pyqtSignal()
    later = pyqtSignal()
    notes = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        k = theme.t()
        self.setStyleSheet(f"#UpdateBanner {{ background: {k['bg2']}; border-bottom: 1px solid {k['line2']}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.S3, 6, theme.S3, 6)
        lay.setSpacing(theme.S2)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.label, 1)
        self.bar = QProgressBar()
        self.bar.setFixedWidth(180)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)
        lay.addWidget(self.bar)
        self.btn_primary = Button(self.tr("Install and restart"), kind="primary", small=True)
        self.btn_later = Button(self.tr("Later"), kind="ghost", small=True)
        self.btn_notes = Button(self.tr("What's new"), kind="ghost", small=True)
        for b in (self.btn_primary, self.btn_later, self.btn_notes):
            b.setMinimumWidth(96)
            lay.addWidget(b)
        self.btn_primary.clicked.connect(self.primary)
        self.btn_later.clicked.connect(self.later)
        self.btn_notes.clicked.connect(self.notes)
        self.hide()

    def show_state(self, s: dict | None) -> None:
        if not s:
            self.hide()
            return
        self.label.setText(s["text"])
        self.label.setToolTip(s.get("tip", ""))
        self.bar.setVisible(s.get("progress") is not None)
        if s.get("progress") is not None:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * s["progress"]))
        self.btn_primary.setVisible(bool(s.get("primary")))
        if s.get("primary"):
            self.btn_primary.text = s["primary"]
            self.btn_primary.update()
        self.btn_primary.setEnabled(not s.get("blocked"))
        self.btn_primary.setToolTip(s.get("blocked", ""))
        self.btn_later.setVisible(s.get("later", True))
        self.btn_later.text = s.get("later_text", self.tr("Later"))
        self.btn_later.update()
        self.btn_notes.setVisible(bool(s.get("notes")))
        self.show()


class UpdateDialog(QDialog):
    """Help › Check for updates…: what this copy is, what the last check
    found (including why it failed), and the same choices as the banner."""

    def __init__(self, ctl: "UpdateController"):
        super().__init__(ctl.win)
        self.ctl = ctl
        self.setWindowTitle(self.tr("Check for updates - {app}").format(app=ctl.app_name))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        h = QLabel(f"{ctl.app_name} {ctl.version or self.tr('(version unknown)')}")
        h.setFont(theme.font(16, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.about = QLabel("")
        self.about.setWordWrap(True)
        self.about.setObjectName("Faint")
        lay.addWidget(self.about)
        row = QHBoxLayout()
        self.btn_install = Button(self.tr("Download") if ctl.kind == "dmg" else self.tr("Install and restart"),
                                  kind="primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_again = Button(self.tr("Check again"), kind="plain")
        self.btn_again.clicked.connect(lambda: ctl.check(manual=True))
        close = Button(self.tr("Close"), kind="ghost")
        close.clicked.connect(self.close)
        row.addWidget(self.btn_install)
        row.addStretch(1)
        row.addWidget(self.btn_again)
        row.addWidget(close)
        lay.addLayout(row)
        self.refresh()

    def _install(self) -> None:
        self.close()
        self.ctl.install()

    def refresh(self) -> None:
        c = self.ctl
        self.status.setText(c.status_text())
        # Whole sentences for on and off, not the word put into one.
        if c.auto_enabled():
            about = self.tr("Automatic checks are on (Settings › Station). A check fetches {url} and its "
                            "signature, and sends nothing but the program's name and version.")
        else:
            about = self.tr("Automatic checks are off (Settings › Station). A check fetches {url} and its "
                            "signature, and sends nothing but the program's name and version.")
        self.about.setText(about.format(url=c.feed_url))
        offer = c.result.offer if c.result is not None else None
        self.btn_install.setVisible(offer is not None and bool(c.kind))
        self.btn_install.setEnabled(not c.busy())
        self.btn_install.setToolTip(c.busy_text())
        self.btn_again.setEnabled(not c.checking)


class UpdateController(QObject):
    """One per window. Everything that could block - the check, the
    download, Windows' signature check, apt - runs on a thread and comes
    back through a signal; the rest happens on the GUI thread."""

    _checked = pyqtSignal(object)
    _progress = pyqtSignal(int, int)
    _fetched = pyqtSignal(object)
    _applied = pyqtSignal(object)

    FIRST_DELAY_MS = 8_000
    TICK_MS = 10 * 60_000

    def __init__(self, win, *, feed_url: str | None = None, keys=None, plat: str | None = None,
                 arch: str | None = None, kind: str | None = None, version: str | None = None,
                 runner=_run, at_exit=_at_exit, authenticode=update.authenticode, pkexec: str | None = None,
                 clock=time.time, fetcher=update.fetch, opener=None):
        super().__init__(win)
        self.win = win
        self.bridge = win.bridge
        radio = self.bridge.radio
        face = win.face
        self.app_name = face.app_name
        self.package = face.package
        appid = radio.CONFIG.app
        # The addresses to check, in order. An explicit one (the tests) or
        # the environment's (a test feed, by hand) is the ONLY one tried:
        # pointing a copy at a test feed must not let it wander off to the
        # real site's mirror when the test feed is down. Otherwise the
        # face's list - its own site first, then any mirror (update.
        # with_mirrors) - or, for a face that declares no list, its one
        # update_feed.
        explicit = feed_url or appid.getenv("UPDATE_URL")
        if explicit:
            self.feed_urls = (explicit,) if isinstance(explicit, str) else tuple(explicit)
        else:
            one = getattr(face, "update_feed", "")
            self.feed_urls = tuple(getattr(face, "update_feeds", ()) or ((one,) if one else ()))
        # The address Help › Check for updates… names: the canonical one.
        self.feed_url = self.feed_urls[0] if self.feed_urls else ""
        self.version = version if version is not None else diag.app_version(type(radio).__module__.split(".")[0])
        self.keys = keys
        self.plat = plat or ("windows" if update.WINDOWS else "macos" if update.MACOS else "linux")
        self._arch = arch
        self.kind = update.install_kind(self.package) if kind is None else kind
        self.runner, self.at_exit, self.authenticode = runner, at_exit, authenticode
        self.pkexec = pkexec
        self.clock, self.fetcher, self.opener = clock, fetcher, opener
        self.seen = update.Seen(radio.CONFIG.conf_path().parent / "update-seen.json")
        self.folder = Path(radio.data_dir) / "updates"
        self.schedule = update.Schedule()
        self.open_url = lambda url: QDesktopServices.openUrl(QUrl(url))
        self.result: update.Result | None = None
        self.checking = False
        self.phase = ""              # "", offer, downloading, ready, installing, installed, failed
        self.message = ""
        self.done = 0.0
        self.file: Path | None = None
        self.dismissed = ""
        self._manual = ""
        self.banner: UpdateBanner | None = None
        self.dialog: UpdateDialog | None = None
        self.timer: QTimer | None = None
        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._fetched.connect(self._on_fetched)
        self._applied.connect(self._on_applied)
        self.bridge.changed.connect(self._on_state)

    # ------------------------------------------------------------ wiring
    @property
    def arch(self) -> str:
        if self._arch is None:
            self._arch = update.machine_arch() if self.plat in ("linux", "macos") else "amd64"
        return self._arch

    def attach(self, banner: UpdateBanner) -> None:
        """A (re)built window's banner: connect it and show the current state."""
        self.banner = banner
        banner.primary.connect(self._primary)
        banner.later.connect(self.later)
        banner.notes.connect(self.whats_new)
        self._render()

    def start(self) -> None:
        """Called by the app's run() once the window is showing."""
        if self.timer is not None or not self.kind or not self.feed_url:
            return
        self.timer = QTimer(self)
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QTimer.singleShot(self.FIRST_DELAY_MS, self.tick)

    def auto_enabled(self) -> bool:
        return bool(self.bridge.st.get("checkUpdates", True))

    def busy(self) -> str:
        return update.busy_reason(self.bridge.radio.state())

    def busy_text(self) -> str:
        b = self.busy()
        return self.tr("Not while {activity}: an update never interrupts that.").format(activity=b) if b else ""

    # ------------------------------------------------------------ checking
    def tick(self) -> None:
        if self.schedule.due(self.clock(), self.auto_enabled(), self.busy()):
            self.check(manual=False)

    def check(self, manual: bool = False) -> bool:
        """Start a check on a thread; False if one is already running."""
        if self.checking:
            return False
        if not self.feed_url:
            self.result = update.Result("offline", self.tr("this build has no update feed"), when=self.clock())
            self._refresh_dialog()
            return False
        self.checking = True
        if manual:
            self.dismissed = ""
        self.schedule.mark(self.clock())
        args = dict(plat=self.plat, arch=self.arch, seen=self.seen, keys=self.keys, fetcher=self.fetcher,
                    clock=self.clock)
        threading.Thread(target=lambda: self._checked.emit(
            update.check(self.feed_urls, self.package, self.version, **args)), daemon=True,
            name="update-check").start()
        self._refresh_dialog()
        return True

    def _on_checked(self, res: update.Result) -> None:
        self.checking = False
        self.result = res
        if res.status == "offline":
            self.schedule.retry_soon(res.when)
        if res.offer is not None and self.phase in ("", "failed") and res.offer.entry.version != self.dismissed:
            self.phase, self.message = "offer", ""
        elif res.offer is None and self.phase == "offer":
            self.phase = ""
        self._render()
        self._refresh_dialog()

    def open_dialog(self) -> UpdateDialog:
        """Help › Check for updates…: shows the last result and checks again."""
        if self.dialog is None:
            self.dialog = UpdateDialog(self)
            self.dialog.finished.connect(lambda _r: setattr(self, "dialog", None))
        self.dialog.show()
        self.dialog.raise_()
        self.check(manual=True)
        return self.dialog

    def status_text(self) -> str:
        if self.checking:
            return self.tr("Checking…")
        r = self.result
        if r is None:
            return self.tr("Not checked yet.")
        when = time.strftime("%H:%M", time.localtime(r.when))
        if r.status == "available":
            e = r.offer.entry
            # One sentence per case rather than the verb put into a shared
            # one; the further sentences are whole and joined after it.
            if r.offer.rollback:
                text = self.tr("{app} {version} is recommended instead of this version (released {date}).")
            else:
                text = self.tr("{app} {version} is available (released {date}).")
            text = text.format(app=self.app_name, version=e.version, date=e.date)
            if e.notes:
                text += " " + self.tr("What's new: {notes}").format(notes=e.notes)
            if not self.kind:
                text += " " + self.tr("This copy runs from source, so update it the way it was put there.")
            return text
        if r.status == "current":
            return self.tr("Up to date: {app} {version} is the newest (checked {when}).").format(
                app=self.app_name, version=self.version, when=when)
        if r.status == "offline":
            return self.tr("Could not check at {when}: {why}. It is tried again later.").format(when=when,
                                                                                                 why=r.message)
        if r.status == "unsupported":
            return self.tr("Checked at {when}: {why}.").format(when=when, why=r.message)
        return self.tr("An update was found at {when} but refused, because it could not be proved genuine: "
                       "{why}.").format(when=when, why=r.message)

    # ------------------------------------------------------------ the banner's buttons
    def _primary(self) -> None:
        if self.phase == "installed":
            self.restart()
        elif self.phase == "opened":
            self._apply()                    # open the .dmg again: its Finder window was closed
        else:
            self.install()

    def later(self) -> None:
        """Hide the banner until the next start or a check by hand. After
        an install, it stays hidden for good: this run is the old version
        until restarted, and saying so again each day would be nagging."""
        offer = self.result.offer if self.result is not None else None
        if offer is not None:
            self.dismissed = offer.entry.version
        self.phase = "later" if self.phase == "installed" else ""
        self.message = ""
        self._render()

    def whats_new(self) -> None:
        offer = self.result.offer if self.result is not None else None
        if offer is not None and offer.notes_url:
            self.open_url(offer.notes_url)

    def install(self) -> None:
        """Install and restart: download and prove the file, then install it
        - or, if the radio became busy meanwhile, wait for another click."""
        offer = self.result.offer if self.result is not None else None
        if offer is None or self.phase in ("downloading", "installing"):
            return
        if not self.kind:
            self._fail(self.tr("This copy runs from source, so it cannot install an update itself."))
            return
        if self.busy():
            self._render()
            return
        if self.phase == "ready" and self.file is not None and self.file.exists():
            self._apply()
            return
        self.phase, self.done, self.message = "downloading", 0.0, ""
        self._render()
        ua = update.user_agent(self.package, self.version)

        def work():
            try:
                kw = {"opener": self.opener} if self.opener is not None else {}
                path = update.download(offer, self.folder, ua, progress=lambda a, b: self._progress.emit(a, b), **kw)
                if self.kind == "exe":
                    update.check_authenticode(path, query=self.authenticode)
                self._fetched.emit(path)
            except update.UpdateError as e:
                self._fetched.emit(e)
        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _on_progress(self, got: int, size: int) -> None:
        self.done = got / size if size else 0.0
        self._render()

    def _on_fetched(self, res) -> None:
        if isinstance(res, Exception):
            log.warning("update: %s", res)
            self._fail(self.tr("The update was not installed: {error}").format(error=res))
            return
        self.file = res
        self.phase = "ready"
        if self.busy():
            # Finished mid-over: it waits for the operator, who may well
            # key again in a moment - never installed behind their back.
            self._render()
            return
        self._apply()

    def _apply(self) -> None:
        if self.busy():
            self._render()
            return
        try:
            cmd = update.install_command(self.kind, self.file, pkexec=self.pkexec)
        except update.UpdateError as e:
            self._fail(str(e))
            return
        v = self.result.offer.entry.version
        if self.kind == "exe":
            # The installer replaces this program's files, so it runs once
            # this process has gone; the window closes the usual way.
            log.info("update: running %s after exit", cmd.argv)
            self.phase, self.message = "installing", self.tr("Installing {app} {version}; it starts again by "
                                                             "itself.").format(app=self.app_name, version=v)
            self._render()
            self.at_exit(cmd.argv)
            self.win.close()
            return
        if self.kind == "dmg":
            # Opened, not installed: Finder shows the new app beside a link
            # to Applications. This copy keeps running; the operator quits
            # it, drags the new one across and starts it.
            rc, out = self.runner(cmd.argv)
            if rc != 0:
                self._fail(self.tr("{app} {version} is downloaded and checked, but could not be opened ({why}): "
                                   "open {file} in Finder").format(app=self.app_name, version=v,
                                                                   why=out.strip()[-200:] or f"exit {rc}",
                                                                   file=self.file))
                return
            log.info("update: opened %s for the operator to install", self.file)
            self.phase = "opened"
            self._render()
            return
        if cmd.argv is None:
            self._fail(self.tr("{app} {version} is downloaded and checked. Install it from a terminal with: "
                               "{command}").format(app=self.app_name, version=v, command=cmd.manual))
            return
        self.phase, self.message = "installing", self.tr("Installing {app} {version}: your system asks for "
                                                         "your password…").format(app=self.app_name, version=v)
        self._render()
        self._manual = cmd.manual
        threading.Thread(target=lambda: self._applied.emit(self.runner(cmd.argv)), daemon=True,
                         name="update-install").start()

    def _on_applied(self, res: tuple[int, str]) -> None:
        rc, out = res
        v = self.result.offer.entry.version
        if rc == 0:
            log.info("update: installed %s %s", self.package, v)
            self.phase, self.message = "installed", ""
        elif rc in (126, 127):
            # pkexec: the prompt was dismissed, or authorisation refused.
            log.info("update: install not authorised (pkexec %d)", rc)
            self.phase, self.message = "ready", self.tr("The password prompt was closed, so nothing was installed.")
        else:
            log.warning("update: install failed (%d): %s", rc, out.strip()[-500:])
            self._fail(self.tr("Installing {version} failed (exit {code}). From a terminal: {command}").format(
                version=v, code=rc, command=self._manual))
            return
        self._render()

    def restart(self) -> None:
        """Close the window the normal way and start the new copy once this
        process has exited - never while transmitting or recording."""
        if self.busy():
            self._render()
            return
        cmd = update.relaunch_command(self.package)
        if cmd is None:
            self._fail(self.tr("Close and start {app} again to use the new version.").format(app=self.app_name))
            return
        self.at_exit(cmd)
        self.win.close()

    def _fail(self, text: str) -> None:
        self.phase, self.message = "failed", text
        self._render()

    # ------------------------------------------------------------ showing it
    def _on_state(self, ch: dict) -> None:
        if ("keyed" in ch or "recording" in ch) and self.phase:
            self._render()
            if self.dialog is not None:
                self.dialog.refresh()

    def _refresh_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.refresh()

    def banner_state(self) -> dict | None:
        """What the banner shows (None: hidden) - its whole content, so the
        tests read it and the banner only draws it."""
        offer = self.result.offer if self.result is not None else None
        if not self.phase or self.phase == "later" or offer is None:
            return None
        e = offer.entry
        name = f"{self.app_name} {e.version}"
        blocked = self.busy_text()
        s = {"text": "", "tip": e.notes, "notes": bool(offer.notes_url), "blocked": blocked}
        install = self.tr("Download") if self.kind == "dmg" else self.tr("Install and restart")
        if self.phase == "offer":
            s["text"] = (self.tr("{name} is recommended instead of {version}").format(name=name, version=self.version)
                         if offer.rollback else self.tr("{name} is available").format(name=name))
            s["primary"] = install
        elif self.phase == "downloading":
            s.update(text=self.tr("Downloading {name}… {percent} %").format(name=name, percent=int(100 * self.done)),
                     progress=self.done, later=False, notes=False)
        elif self.phase == "ready":
            s["text"] = self.message or self.tr("{name} is downloaded and checked").format(name=name)
            if blocked:
                s["text"] = self.tr("{text} - install it when you have finished {activity}").format(
                    text=s["text"], activity=self.busy())
            s["primary"] = install
        elif self.phase == "installing":
            s.update(text=self.message, later=False, notes=False)
        elif self.phase == "opened":
            s.update(text=self.tr("{name} is open in Finder: quit {app}, drag the new one onto Applications "
                                  "(replacing this one), then start it again.").format(name=name, app=self.app_name),
                     primary=self.tr("Show it again"), notes=False, blocked="")
        elif self.phase == "installed":
            s.update(text=self.tr("{name} is installed. Restart to use it.").format(name=name),
                     primary=self.tr("Restart now"), notes=False)
        elif self.phase == "failed":
            s.update(text=self.message, later_text=self.tr("Close"), notes=False, blocked="")
        return s

    def _render(self) -> None:
        if self.banner is not None:
            try:
                self.banner.show_state(self.banner_state())
            except RuntimeError:            # a banner from before a rebuild, already deleted
                self.banner = None
