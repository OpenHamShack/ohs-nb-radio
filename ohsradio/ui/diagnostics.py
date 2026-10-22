"""HAM's diagnostics dialogs: Save diagnostics… with HAM's findings added,
Check radio…, the chip-mode dialog a 2 m pick on an AD9363 Pluto opens,
and the AD9364 fix (ohsradio/plutofix.py) with its consent, password and
progress steps.

Every slow step (discovery, an IIO probe, the SSH session, a reboot) runs
on a worker thread and is polled from a QTimer, never waited for on the
UI thread: the bridge's timer is the engine's watchdog heartbeat
(docs/ENGINE-API.md), so a dialog that blocked for the 30 s a Pluto takes
to reboot would look to the engine like a hung window. For the same
reason no dialog here uses exec(); each is opened with open() and reports
back through a callback, which is also what lets the tests drive them.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QVBoxLayout, QWidget)

from ohscore.ui import theme
from ohscore.ui.controls import Button

from .. import diagnostics, plutofix


class Async:
    """fn() on a thread; done(ok, value) on the UI thread when it returns."""

    def __init__(self, parent, fn, done, interval_ms: int = 50):
        self.result = None
        self.thread = threading.Thread(target=self._run, args=(fn,), daemon=True, name="ohsradio-diag")
        self.done_cb = done
        self.timer = QTimer(parent)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._poll)
        self.thread.start()
        self.timer.start()

    def _run(self, fn):
        try:
            self.result = (True, fn())
        except Exception as e:  # noqa: BLE001 - shown in the dialog, never raised into Qt
            self.result = (False, e)

    def _poll(self):
        if self.result is None:
            return
        self.timer.stop()
        self.done_cb(*self.result)

    @property
    def finished(self) -> bool:
        return self.result is not None and not self.timer.isActive()


def _label(text: str, muted: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    if muted:
        lab.setObjectName("Muted")
    return lab


def _mono(text: str, lines: int = 10) -> QPlainTextEdit:
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setFont(theme.font(12, mono=True))
    box.setMinimumHeight(18 * lines)
    return box


class _Dialog(QDialog):
    def __init__(self, parent, title: str, width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(10)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.extra: dict[str, Button] = {}

    def add_button(self, key: str, text: str, fn, kind: str = "plain") -> Button:
        # The house buttons (ohscore.ui.controls), as Welcome and Settings
        # use: QDialogButtonBox's native ones drew blank under the theme's
        # stylesheet.
        b = Button(text, kind=kind)
        b.clicked.connect(fn)
        self.buttons.addWidget(b)
        self.extra[key] = b
        return b

    def finish_layout(self):
        self.lay.addLayout(self.buttons)


# ------------------------------------------------------------------ the report
class ReportJob:
    """Help › Save diagnostics… in HAM: HAM's findings (a fresh Find, the
    Pluto probe - seconds, so on a worker thread) first, then the shared
    dialog (ohscore/ui/diagnostics.py) with them in its report, opened
    rather than exec'd. on_dialog(dialog) when it is showing."""

    def __init__(self, win, on_dialog=None, discover: bool = True, identify=None):
        self.win = win
        self.dialog = None
        self.error = ""
        self.on_dialog = on_dialog or (lambda d: None)
        if hasattr(win, "on_toast"):
            win.on_toast({"level": "info", "text": QCoreApplication.translate(
                "ReportJob", "Collecting diagnostics (finding radios takes a few seconds)…")})
        radio = win.bridge.radio
        self.job = Async(win, lambda: diagnostics.findings(radio, discover=discover, identify=identify),
                         self._found)

    def _found(self, ok, value):
        from ohscore.ui import diagnostics as core
        more = value if ok else {"ham findings": f"could not be collected: {value}"}
        try:
            self.dialog = core.save_diagnostics(self.win, more)
        except Exception as e:  # noqa: BLE001 - say so rather than lose the click
            self.error = QCoreApplication.translate("ReportJob", "Diagnostics could not be collected: {error}").format(
                error=e)
            if hasattr(self.win, "on_toast"):
                self.win.on_toast({"level": "error", "text": self.error})
            return
        self.dialog.open()
        self.on_dialog(self.dialog)

    @property
    def finished(self) -> bool:
        return self.dialog is not None or bool(self.error)


class DeviceErrorDialog(_Dialog):
    """A device that would not open: the sentence, plus the two ways on."""

    def __init__(self, parent, text: str, on_report, on_check):
        super().__init__(parent, self.tr("The radio did not start"))
        self.lay.addWidget(_label(text))
        self.lay.addWidget(_label(self.tr("Save diagnostics… collects what is needed to work out why. It is saved "
                                          "where you choose and nothing is sent anywhere."), muted=True))
        self.add_button("report", self.tr("Save diagnostics…"), on_report)
        self.add_button("check", self.tr("Check radio…"), on_check)
        self.add_button("close", self.tr("Close"), self.reject, "ghost")
        self.finish_layout()


class ChipModeDialog(_Dialog):
    """Shown instead of a bare error when an AD9363-identified Pluto is
    asked for a band outside 325 MHz-3.8 GHz."""

    def __init__(self, parent, band_label: str, on_apply, on_report):
        super().__init__(parent, self.tr("This Pluto cannot reach {band}").format(band=band_label))
        self.text = self.tr("This Pluto is running as an AD9363, which tunes 325 MHz–3.8 GHz. {band} needs the "
                            "AD9364 setting.").format(band=band_label)
        self.lay.addWidget(_label(self.text))
        self.lay.addWidget(_label(self.tr("The radio itself covers 70 MHz–6 GHz; the AD9363 setting is only what "
                                          "ADI's firmware tells the driver to allow. OpenHamShack Radio can change it "
                                          "for you over the Pluto's network link: it shows the commands first and asks "
                                          "before running them, and it can undo the change the same way."),
                                  muted=True))
        self.add_button("apply", self.tr("Apply the AD9364 setting…"), lambda: (self.accept(), on_apply()), "primary")
        self.add_button("report", self.tr("Save diagnostics…"), on_report)
        self.add_button("close", self.tr("Close"), self.reject, "ghost")
        self.finish_layout()


LEVEL_MARK = {"ok": ("✓", "ok"), "warn": ("!", "warn"), "fail": ("✗", "err"), "info": ("·", "text2")}


class CheckRadioDialog(_Dialog):
    """Help › Check radio…: what the Pluto says it is and which licensed
    bands it can reach, with the fix and its undo offered where they apply."""

    def __init__(self, parent, uri: str, licence_class: str, dev=None, identify=plutofix.probe,
                 on_apply=None, on_undo=None, on_report=None):
        super().__init__(parent, self.tr("Check radio"))
        self.uri = uri
        self.results: list[plutofix.Check] = []
        self.info = None
        self.status = _label(self.tr("Checking {uri}…").format(uri=uri), muted=True)
        self.lay.addWidget(self.status)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setHorizontalSpacing(12)
        self.lay.addWidget(self.grid_host)
        self.apply_b = self.add_button("apply", self.tr("Apply the AD9364 setting…"),
                                       lambda: (self.accept(), on_apply and on_apply()))
        self.undo_b = self.add_button("undo", self.tr("Undo (back to AD9363)…"),
                                      lambda: (self.accept(), on_undo and on_undo()))
        self.add_button("report", self.tr("Save diagnostics…"), lambda: on_report and on_report())
        self.add_button("close", self.tr("Close"), self.reject, "ghost")
        self.apply_b.setVisible(False)
        self.undo_b.setVisible(False)
        self.finish_layout()
        self.job = Async(self, lambda: plutofix.check_radio(uri, licence_class, dev, identify=identify), self._done)

    def _done(self, ok, value):
        if not ok:
            self.status.setText(self.tr("The check itself failed: {error}").format(error=value))
            return
        self.results, self.info = value
        self.status.setText(self.tr("Radio at {uri}:").format(uri=self.uri))
        t = theme.t()
        for row, c in enumerate(self.results):
            mark, colour = LEVEL_MARK.get(c.level, ("·", "text2"))
            m = QLabel(mark)
            m.setStyleSheet(f"color: {t.get(colour, t['text2'])}; font-weight: bold;")
            self.grid.addWidget(m, row, 0)
            self.grid.addWidget(QLabel(c.label), row, 1)
            self.grid.addWidget(QLabel(c.text), row, 2)
        self.grid.setColumnStretch(2, 1)
        ident = self.info.identity if self.info is not None else ""
        self.apply_b.setVisible(ident == "ad9363")
        self.undo_b.setVisible(ident == "ad9364")
        self.adjustSize()


class TextDialog(_Dialog):
    """A message and, below it, text to read or copy (manual steps, the
    commands about to run)."""

    def __init__(self, parent, title: str, message: str, text: str = "", ok_text: str = "",
                 on_ok=None, cancel_text: str = ""):
        super().__init__(parent, title, 640)
        self.message = message
        self.msg_label = _label(message)
        self.lay.addWidget(self.msg_label)
        self.box = None
        if text:
            self.box = _mono(text, 14)
            self.lay.addWidget(self.box)
        if ok_text:
            self.add_button("ok", ok_text, lambda: (self.accept(), on_ok and on_ok()),
                            "primary")
        self.add_button("cancel", cancel_text or self.tr("Close"), self.reject, "ghost")
        self.finish_layout()


class PasswordDialog(_Dialog):
    def __init__(self, parent, host: str, on_answer):
        super().__init__(parent, self.tr("Pluto password"))
        self.on_answer = on_answer
        self.lay.addWidget(_label(self.tr("The radio at {host} did not accept ADI's default password (analog). Type "
                                          "the root password you set on it. It is used for this one connection and "
                                          "not saved.").format(host=host)))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.lay.addWidget(self.edit)
        self.add_button("ok", self.tr("Connect"), self._ok, "primary")
        self.add_button("cancel", self.tr("Cancel"), self._cancel, "ghost")
        self.finish_layout()
        self.answered = False

    def _ok(self):
        self._answer(self.edit.text())
        self.accept()

    def _cancel(self):
        self._answer(None)
        self.reject()

    def _answer(self, value):
        if not self.answered:
            self.answered = True
            self.edit.clear()
            self.on_answer(value)

    def reject(self):
        self._answer(None)
        super().reject()


class FixFlow:
    """Apply (or undo) the AD9364 setting: look, explain, ask, run, report.

    The engine is stopped before anything is sent to the radio - the
    reboot would otherwise look like a lost device mid-stream and the
    reconnect loop would race the check - and started again at the end
    whatever happened, so the operator is never left with a stopped radio."""

    def __init__(self, window, uri: str, undo: bool = False, make_fixer=None, bridge=None):
        self.win = window
        self.uri = uri
        self.undo = undo
        self.bridge = bridge
        self.progress_text = ""
        self.dialog = None              # whatever this flow is showing now (tests drive it)
        self.password_dialog = None
        self.result: plutofix.Result | None = None
        self._pw_request = None
        self._pw_event = threading.Event()
        self._pw_value = None
        self.make_fixer = make_fixer or (lambda uri, progress: plutofix.Fixer(uri, progress=progress))
        self.fixer = self.make_fixer(uri, self._progress)
        self.job = Async(window, lambda: self.fixer.preview(undo), self._previewed)

    # -- step 1: what would happen
    def _previewed(self, ok, value):
        if not ok:
            self._show_result(plutofix.Result(False, QCoreApplication.translate(
                "FixFlow", "The radio could not be checked: {error}").format(error=value),
                                              manual=plutofix.manual_steps(self.uri, None, self.undo)))
            return
        info, plan, cmds, why = value
        if not cmds:
            if info.reachable and info.identity == ("ad9363" if self.undo else "ad9364"):
                self._show_result(plutofix.Result(True, why, identity=info.identity))
                return
            self.dialog = TextDialog(self.win, QCoreApplication.translate("FixFlow", "Change it by hand"), why,
                                     plutofix.manual_steps(self.uri, plan if plan.reason else None, self.undo))
            self.dialog.open()
            return
        host = plutofix.network_host(self.uri)
        text = "\n".join(f"{cmd}\n    {what}" for cmd, what in cmds)
        # One whole paragraph each way: the undo names ADI's default and
        # drops the "can be undone" clause, which a translation cannot
        # splice in where English did.
        if self.undo:
            msg = QCoreApplication.translate(
                "FixFlow", "OpenHamShack Radio will log in to the Pluto at {host} (SSH, as root) and run the commands "
                "below to set it to AD9363 (ADI's default). {reason} They change two settings the radio reads when "
                "it starts, not its firmware. The radio then restarts: receiving stops for about half a minute and "
                "OpenHamShack Radio reconnects when it is back.")
        else:
            msg = QCoreApplication.translate(
                "FixFlow", "OpenHamShack Radio will log in to the Pluto at {host} (SSH, as root) and run the commands "
                "below to set it to AD9364. {reason} They change two settings the radio reads when it starts, not "
                "its firmware, and can be undone the same way. The radio then restarts: receiving stops for about "
                "half a minute and OpenHamShack Radio reconnects when it is back.")
        msg = msg.format(host=host, reason=plan.reason)
        self.dialog = TextDialog(self.win, QCoreApplication.translate("FixFlow", "Set the Pluto to {chip}").format(
                                     chip="AD9363" if self.undo else "AD9364"), msg, text,
                                 ok_text=QCoreApplication.translate("FixFlow", "Run these commands"),
                                 on_ok=self.consent, cancel_text=QCoreApplication.translate("FixFlow", "Cancel"))
        self.dialog.open()

    # -- step 2: consent given
    def consent(self):
        bridge = self.bridge or getattr(self.win, "bridge", None)
        if bridge is not None:
            try:
                bridge.radio.stop()
            except Exception:  # noqa: BLE001 - a radio that will not stop is about to be rebooted anyway
                pass
        self.dialog = TextDialog(self.win, QCoreApplication.translate("FixFlow", "Changing the Pluto"),
                                 QCoreApplication.translate("FixFlow", "Working…"),
                                 cancel_text=QCoreApplication.translate("FixFlow", "Hide"))
        self.dialog.open()
        self.timer = QTimer(self.win)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.job = Async(self.win, lambda: self.fixer.run(self.undo, ask_password=self._ask_password), self._ran)

    def _progress(self, text: str):
        self.progress_text = text           # read by _tick on the UI thread

    def _ask_password(self):
        """Called on the worker thread: hand the question to the UI thread
        and wait for the answer."""
        self._pw_event.clear()
        self._pw_request = plutofix.network_host(self.uri)
        self._pw_event.wait(600)
        value, self._pw_value = self._pw_value, None
        return value

    def _tick(self):
        if isinstance(self.dialog, TextDialog) and self.progress_text:
            self.dialog.msg_label.setText(self.progress_text)
        if self._pw_request is not None and self.password_dialog is None:
            host, self._pw_request = self._pw_request, None
            self.password_dialog = PasswordDialog(self.win, host, self._answer)
            self.password_dialog.open()

    def _answer(self, value):
        self._pw_value = value
        self._pw_event.set()

    # -- step 3: the outcome
    def _ran(self, ok, value):
        self.timer.stop()
        if self.password_dialog is not None and self.password_dialog.isVisible():
            self.password_dialog.reject()
        res = value if ok else plutofix.Result(False, QCoreApplication.translate(
            "FixFlow", "The change failed: {error}").format(error=value),
                                               manual=plutofix.manual_steps(self.uri, None, self.undo))
        if self.dialog is not None:
            self.dialog.close()
        bridge = self.bridge or getattr(self.win, "bridge", None)
        if bridge is not None:
            err = bridge.start()
            if err:
                res = plutofix.Result(res.ok, QCoreApplication.translate(
                    "FixFlow", "{message}\n\nRestarting the radio: {error}").format(message=res.message, error=err),
                                      res.manual,
                                      res.ran, res.identity)
        self._show_result(res)

    def _show_result(self, res: plutofix.Result):
        self.result = res
        title = (QCoreApplication.translate("FixFlow", "Done") if res.ok else
                 QCoreApplication.translate("FixFlow", "Not changed") if not res.ran else
                 QCoreApplication.translate("FixFlow", "Check the radio"))
        self.dialog = TextDialog(self.win, title, res.message, res.manual)
        self.dialog.open()

    @property
    def finished(self) -> bool:
        return self.result is not None
