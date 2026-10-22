"""Help › Send diagnostics… and the automatic upload's timing: the
window's half of ohscore/diagupload.py.

Decisions (Brian, 12/10/2026: "fully automatic, with opt in"):

- **Off until the operator turns it on in Settings › Station,** where the
  whole consent text sits beside the switch: what is sent, that the
  callsign and locator can be in it, where it goes, how long it is kept,
  how to stop. Turning it on there is the only thing that writes the
  consent stamp (ui.json `diagUploadConsent`); see diagupload's docstring.
- **Help › Send diagnostics… works whatever the switch says.** It shows the
  same summary and sends only when Send is pressed: pressing it is the
  consent for that one report.
- **One look a minute,** on the GUI thread, which only decides; the bundle
  is gathered and sent on a thread with a timeout, and comes back through
  a signal. Nothing is sent while transmitting, on a metered connection
  (when Qt can tell: QNetworkInformation), or from a window the app's
  run() did not start (tests and the screenshot tools never upload).
- **Quiet.** An automatic upload says nothing on screen; its code goes in
  the log and in Help › Send diagnostics…. A failure is a log line and a
  retry later.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from .. import diag, diagupload
from . import theme
from .controls import Button

log = logging.getLogger("ohscore.diagupload")


def what_is_sent(app_name: str) -> str:
    """The consent text: the same words in Settings and in Help › Send
    diagnostics…, so what the operator agreed to is what the dialog shows."""
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.translate(
        "DiagSend",
        "What is sent: {app}'s diagnostics - its recent log, its settings with anything secret removed, the "
        "IC-9700 diagnostic's report when you have run one, the program's version and your computer's operating "
        "system - with a random number made for this installation, not taken from the computer. Your callsign "
        "and locator are in it where they appear in the log and settings. It goes to openhamshack.com, where "
        "only the people who write {app} read it, and it is deleted after 30 days. Nothing is sent while you "
        "transmit or on a metered connection. To stop, turn this off in Settings › Station. More: {url}"
    ).format(app=app_name, url=diagupload.PRIVACY_URL)


def metered_now() -> bool:
    """Whether the system says this connection is metered (a phone's data,
    a capped plan). False when it cannot tell: Qt has no backend on some
    systems, and "unknown" must not stop a station on a home line."""
    try:
        from PyQt6.QtNetwork import QNetworkInformation as NI
        if NI.instance() is None:
            if not NI.loadBackendByFeatures(NI.Feature.Metered):
                return False
        inst = NI.instance()
        return bool(inst is not None and inst.supports(NI.Feature.Metered) and inst.isMetered())
    except (ImportError, AttributeError, RuntimeError):
        return False


class DiagSendController(QObject):
    """One per window: watches for triggers, decides when, sends on a thread."""

    _done = pyqtSignal(object)
    TICK_MS = 60_000

    def __init__(self, win, *, url: str | None = None, clock=time.time, poster=diagupload.post,
                 metered=metered_now, timeout: float = diagupload.TIMEOUT_S, state_path: Path | None = None):
        super().__init__(win)
        self.win = win
        self.bridge = win.bridge
        radio = self.bridge.radio
        appid = radio.CONFIG.app
        self.app_name = win.face.app_name
        self.app = getattr(win.face, "diag_app", "") or appid.name
        self.version = diag.app_version(type(radio).__module__.split(".")[0]) or "0.0.0"
        self.url = url or appid.getenv("DIAG_URL") or diagupload.URL
        self.clock, self.poster, self.metered, self.timeout = clock, poster, metered, timeout
        self.state = diagupload.State(state_path or radio.CONFIG.conf_path().parent / "diag-upload.json")
        self.plan = diagupload.Plan(self.state, clock())
        self.watcher = diagupload.Watcher(clock)
        self.sending = ""                 # "", or the kind on its way
        self.last_error = ""
        self.timer: QTimer | None = None
        self.dialog: SendDialog | None = None
        self._done.connect(self._on_done)

    # ------------------------------------------------------------ wiring
    def start(self) -> None:
        """Called by the app's run() once the window is showing."""
        if self.timer is not None:
            return
        self.watcher.install()
        self._check_faults_file()
        self.timer = QTimer(self)
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def stop(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.watcher.remove()

    def enabled(self) -> bool:
        p = self.win.prefs
        return bool(p["diagUpload"]) and diagupload.consented(p["diagUploadConsent"])

    def keyed(self) -> bool:
        return bool(self.bridge.radio.state().get("keyed"))

    def _setup(self):
        s = diag.current()
        return s if s is not None and s.app == self.bridge.radio.CONFIG.app.name else None

    def _log_paths(self) -> list[Path]:
        radio = self.bridge.radio
        return diag.log_files(radio.CONFIG.app.name, radio.data_dir)

    def _fault_path(self) -> Path:
        from . import diagnostics
        return diagnostics.log_folder(self.bridge.radio) / "faults.log"

    def _check_faults_file(self) -> None:
        """A crash in C (faulthandler) ends the process before anything can
        be sent: the next run sees faults.log longer than at the last report
        and treats it as a fault. The first look only takes the size."""
        try:
            size = self._fault_path().stat().st_size
        except OSError:
            size = 0
        known = self.state.get("faultsSize")
        if known is None or size < known:
            self.state.set(faultsSize=size)
        elif size > known and self.enabled():
            self.plan.note([("crash", "a crash in an earlier run (faults.log)", self.clock())])

    def _logged_since(self) -> float:
        t = 0.0
        for p in self._log_paths():
            try:
                t = max(t, p.stat().st_mtime)
            except OSError:
                pass
        return t

    # ------------------------------------------------------------ deciding
    def tick(self) -> str:
        """One look: take what was heard, send if due. Returns the kind sent ("" for none)."""
        self.plan.note(self.watcher.take())
        if self.sending:
            return ""
        on = self.enabled()
        if not on:
            # Off means off: faults heard while off are not saved up for later.
            self.plan.taken()
            return ""
        kind = self.plan.due(self.clock(), enabled=on, keyed=self.keyed(), metered=self.metered(),
                             logged_since=self._logged_since())
        if kind:
            self.send(kind)
        return kind

    # ------------------------------------------------------------ sending
    def send(self, kind: str) -> bool:
        """Gather and send on a thread; False if one is on its way already
        or the radio is transmitting."""
        if self.sending:
            return False
        if self.keyed():
            self.last_error = self.tr("Not sent: not while transmitting.")
            self._refresh()
            return False
        events = self.plan.taken() if kind == "fault" else []
        if kind == "manual":
            events = self.plan.taken() + self.watcher.take()
        self.sending = kind
        self.last_error = ""
        radio = self.bridge.radio
        from . import diagnostics
        try:
            screen = diagnostics.screen_facts(self.win)
        except Exception:  # noqa: BLE001 - a report without screen facts is still a report
            screen = {}
        conf = diagnostics._conf_path(radio)
        ui_path = self.win.prefs.path
        setup = self._setup()
        facts = dict(setup.facts) if setup is not None and setup.facts else {}
        install = self.state.install_id()
        log_paths, fault_path = self._log_paths(), self._fault_path()

        def work():
            try:
                f = facts or diag.facts(self.app_name, self.version, radio.data_dir, radio.cfg, audio=False)
                report = diag.build_report(f, radio.state(), device_context=radio.device_context(), screen=screen,
                                           extra={"sent": kind})
                body, info = diagupload.build(app=self.app, version=self.version, install=install, kind=kind,
                                              events=events, report=report, status_lines=list(radio.status_lines),
                                              conf_path=conf, ui_path=ui_path, log_paths=log_paths,
                                              fault_path=fault_path if fault_path.is_file() else None)
                code = self.poster(self.url, body, app=self.app, version=self.version, install=install,
                                   timeout=self.timeout)
                self._done.emit((kind, events, code, len(body), info))
            except diagupload.UploadError as e:
                self._done.emit((kind, events, e, 0, {}))
            except Exception as e:  # noqa: BLE001 - nothing an upload does may reach the radio
                log.warning("diagnostics upload: failed", exc_info=True)
                err = diagupload.UploadError(f"something went wrong making or sending the report ({e})")
                self._done.emit((kind, events, err, 0, {}))
        threading.Thread(target=work, daemon=True, name="diag-upload").start()
        self._refresh()
        return True

    def _on_done(self, res) -> None:
        kind, events, code, size, info = res
        self.sending = ""
        now = self.clock()
        trigger = diagupload.trigger_text(events, kind)
        if isinstance(code, Exception):
            self.last_error = str(code)
            log.info("diagnostics upload (%s) not sent: %s; tried again later", trigger, code)
            if kind != "manual":
                self.plan.failed(now, kind, str(code), events)
            elif events:
                # Faults a failed manual send carried wait for the automatic one.
                self.plan.pending = list(events) + self.plan.pending
        else:
            self.plan.sent(now, kind, code, trigger)
            try:
                self.state.set(faultsSize=self._fault_path().stat().st_size)
            except OSError:
                pass
            log.info("diagnostics sent to OpenHamShack (%s): reference %s, %d bytes%s", trigger, code, size,
                     ", log cut to fit" if info.get("logCut") else "")
        self._refresh()

    # ------------------------------------------------------------ the dialog
    def open_dialog(self) -> "SendDialog":
        if self.dialog is None:
            self.dialog = SendDialog(self)
            self.dialog.finished.connect(lambda _r: setattr(self, "dialog", None))
        self.dialog.refresh()
        self.dialog.show()
        self.dialog.raise_()
        return self.dialog

    def _refresh(self) -> None:
        if self.dialog is not None:
            self.dialog.refresh()

    def status_text(self) -> str:
        if self.sending:
            return self.tr("Sending…")
        if self.last_error:
            return self.tr("The last try did not work: {why}. Nothing else is affected.").format(why=self.last_error)
        code = self.state.get("lastCode")
        at = self.state.get("lastSent")
        if code and at:
            return self.tr("Last sent at {when}: reference {code}. Quote it when you write to us.").format(
                when=time.strftime("%Y-%m-%d %H:%M", time.localtime(at)), code=code)
        return self.tr("Nothing sent yet.")


class SendDialog(QDialog):
    """Help › Send diagnostics…: the summary, whether automatic sending is
    on, the last reference code, and Send."""

    def __init__(self, ctl: DiagSendController):
        super().__init__(ctl.win)
        self.ctl = ctl
        self.setWindowTitle(self.tr("Send diagnostics - {app}").format(app=ctl.app_name))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        h = QLabel(self.tr("Send diagnostics to OpenHamShack"))
        h.setFont(theme.font(16, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        self.summary = QLabel(what_is_sent(ctl.app_name))
        self.summary.setWordWrap(True)
        self.summary.setObjectName("Muted")
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.summary)
        self.auto = QLabel("")
        self.auto.setWordWrap(True)
        self.auto.setObjectName("Faint")
        lay.addWidget(self.auto)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        privacy = Button(self.tr("Privacy note"), kind="ghost")
        privacy.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(diagupload.PRIVACY_URL)))
        row.addWidget(privacy)
        row.addStretch(1)
        close = Button(self.tr("Close"), kind="ghost")
        close.clicked.connect(self.close)
        row.addWidget(close)
        self.btn_send = Button(self.tr("Send now"), kind="primary")
        self.btn_send.clicked.connect(lambda: ctl.send("manual"))
        row.addWidget(self.btn_send)
        lay.addLayout(row)

    def refresh(self) -> None:
        c = self.ctl
        if c.enabled():
            self.auto.setText(self.tr("Automatic sending is on (Settings › Station): after a fault and once a day."))
        else:
            self.auto.setText(self.tr("Automatic sending is off (Settings › Station). Send now sends this one "
                                      "report only."))
        self.status.setText(c.status_text())
        self.btn_send.setEnabled(not c.sending)
