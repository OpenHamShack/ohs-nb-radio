"""The one place the window meets the engine.

A QTimer at ~30 Hz calls `radio.heartbeat()` and drains every feed, then
hands what it found to the widgets as Qt signals. Spectrum lines are handed
over as a *batch* per tick, so a scope that receives three lines in one tick
writes three waterfall rows and repaints once.

Heartbeat and draining live on the same timer on purpose (docs/ENGINE-API.md
"Watchdog"): if the event loop hangs, both stop together and the engine
unkeys. Nothing in the window may block this thread for long.

Operator actions go through `set()`, `ptt()` and `send()` here, which turn
the engine's ValueError sentences into toasts instead of exceptions. A tune
out of the span background decoders pin (SpanPinned) asks the operator
first whether to stop them (`ask_stop`), here, so every way of tuning -
the knob, a scope click, a band button, a memory - asks the same question. `ptt()`
and `send()` also hold the UI's one extra gate: nothing keys until the
operator has acknowledged the licence conditions - except, in an app whose
face says so, a simulator, which never radiates.
"""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from ..engine import SpanPinned
from ..i18n import fmt
from .face import Face

log = logging.getLogger("ohsnb.ui")

LICENCE_SENTENCE = ("Transmit is locked until you acknowledge the licence conditions "
                    "(Settings › Station, or the welcome screen).")


class Bridge(QObject):
    wide = pyqtSignal(list)
    zoom = pyqtSignal(list)
    meter = pyqtSignal(dict)
    lock = pyqtSignal(dict)
    changed = pyqtSignal(dict)       # {key: value} of state keys that changed
    toast = pyqtSignal(dict)         # {level, text}
    decoded = pyqtSignal(dict)      # decoder events (not "event": that is QObject.event)
    tick = pyqtSignal(float)         # dt seconds, once per timer tick (meters' ballistics)

    KINDS = ("wide", "zoom", "meter", "lock", "state", "toast", "events")
    # After a No, how long further refusals of the same kind are only
    # toasted: a knob turned past the span's edge refuses on every step,
    # and one question per turn is enough.
    DECLINED_QUIET_S = 2.0

    def __init__(self, radio, parent=None, hz: float = 30.0, face=None):
        super().__init__(parent)
        self.radio = radio
        # What the shared widgets ask about the app's band (ohscore/ui/face.py);
        # they reach it through the bridge they already hold.
        self.face = face if face is not None else Face()
        self.licence_ok = False
        # Every kind the engine offers: QO-100 NB's has a "lock" feed for
        # beacon and TX lock; an app without one simply never emits `lock`.
        offered = getattr(radio, "FEED_KINDS", self.KINDS)
        self.feeds = {k: radio.subscribe(k, 128 if k in ("events", "toast") else 64)
                      for k in self.KINDS if k in offered}
        self.st = radio.state()
        self.state_dropped = 0       # the state feed's drops already made good by re-reading (pump)
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / hz))
        self.timer.timeout.connect(self.pump)
        self.last = time.monotonic()
        self.frame_ms = 0.0          # how long the last pump took, signal handlers included
        # How a question is put to the operator (ask_stop): a dialog; a test
        # puts its own answer here. And when they last said No.
        self.asker = self._ask_dialog
        self.declined_at = -1e9

    # ------------------------------------------------------------- lifecycle
    def start(self) -> str:
        """Start the engine; returns '' or the sentence saying why not."""
        self.timer.start()
        try:
            self.radio.start()
        except Exception as e:  # noqa: BLE001 - DeviceError or anything else: show it, keep the window
            self.st = self.radio.state()
            self.changed.emit(dict(self.st))
            return str(e)
        self.st = self.radio.state()
        self.changed.emit(dict(self.st))
        return ""

    def restart(self) -> str:
        """After a Settings save that changed a restart key. Never keys."""
        self.radio.stop()
        return self.start()

    def stop(self):
        self.timer.stop()
        try:
            self.radio.stop()
        finally:
            for f in self.feeds.values():
                self.radio.unsubscribe(f)

    # ------------------------------------------------------------- the pump
    def pump(self):
        t0 = time.perf_counter()
        now = time.monotonic()
        dt, self.last = now - self.last, now
        self.radio.heartbeat()
        f = self.feeds
        changes = {}
        for it in f["state"].drain():
            changes.update(it.get("changes", {}))
        if f["state"].dropped != self.state_dropped:
            # The engine publishes each state change once, as a diff, and the
            # feed drops its oldest when full, so a dropped item is a change
            # the window would never hear of again: after a stall of the GUI
            # thread longer than the feed holds (64 supervisor ticks, ~6 s),
            # the IC-9700 card said "connecting…" for good while the link was
            # up (17/10/2026: test_ui_extrig's card test, behind a test
            # module's worth of leaked windows' event filters). Take the
            # whole state again instead, and tell every widget all of it.
            self.state_dropped = f["state"].dropped
            log.warning("state feed dropped %d changes: the window re-reads the engine's state",
                        self.state_dropped)
            self.st = self.radio.state()
            self.changed.emit(dict(self.st))
        elif changes:
            self.st.update(changes)
            self.changed.emit(changes)
        lines = f["wide"].drain()
        if lines:
            self.wide.emit(lines)
        lines = f["zoom"].drain()
        if lines:
            self.zoom.emit(lines)
        for it in f["meter"].drain():
            self.meter.emit(it)
        for it in (f["lock"].drain() if "lock" in f else ()):
            self.lock.emit(it)
        for it in f["events"].drain():
            self.decoded.emit(it)
        for it in f["toast"].drain():
            self.toast.emit(it)
        self.tick.emit(dt)
        self.frame_ms = (time.perf_counter() - t0) * 1000.0

    # ------------------------------------------------------------- actions
    def say(self, text: str, level: str = "warn"):
        self.toast.emit({"t": time.time(), "level": level, "text": text})

    def set(self, authorise: bool = False, quiet: bool = False, **changes) -> bool:
        try:
            try:
                done = self.radio.set(authorise=authorise, **changes)
            except SpanPinned as e:
                if quiet or not self.ask_stop(e.sessions, e.freq, str(e)):
                    return False
                done = self.radio.set(authorise=authorise, drop_sessions=True, **changes)
        except ValueError as e:
            if not quiet:
                self.say(str(e))
            return False
        # Operator changes also arrive on the state feed; applying them here
        # too makes the control that caused them settle this frame, not next.
        if done:
            self.st.update(done)
            self.changed.emit(dict(done))
        return True

    def set_mode_tuned(self, mode: str) -> bool:
        """A mode button or shortcut (window.set_mode): Engine.set_mode_tuned
        also tunes to the mode's usual frequency, so this needs its own
        wrapper rather than plain set() - the same settle-this-frame and
        toast-not-exception treatment, for whichever of mode or mode+vfo
        the engine actually applied."""
        got = []
        if not self.tune_with(lambda: got.append(self.radio.set_mode_tuned(mode))):
            return False
        changed = got[-1] if got else None
        if changed:
            self.st.update(changed)
            self.changed.emit(dict(changed))
        return True

    def tune_with(self, fn) -> bool:
        """Run `fn` (a band button, a memory, a mode's usual frequency: an
        engine call that tunes), asking first if it would leave the span
        background decoders pin, and stopping them on a Yes before trying
        again. False, with the sentence toasted, when it did not tune."""
        try:
            try:
                fn()
            except SpanPinned as e:
                if not self.ask_stop(e.sessions, e.freq, str(e)):
                    return False
                self.radio.decoders.stop_background()
                fn()
        except ValueError as e:
            self.say(str(e))
            return False
        return True

    def ask_stop(self, sessions: list[dict], freq: float | None = None, refusal: str = "") -> bool:
        """Ask whether to stop `sessions` (the background decoders pinning
        the span) to tune to `freq`, or to play DAB when `freq` is None.
        Shortly after a No, only toasts `refusal` (DECLINED_QUIET_S)."""
        if time.monotonic() - self.declined_at < self.DECLINED_QUIET_S:
            if refusal:
                self.say(refusal)
            return False
        names = ", ".join(s.get("label") or s.get("decoder", "") for s in sessions)
        if freq is None:
            text = QCoreApplication.translate("Bridge", "Playing DAB stops: {sessions}. Continue?").format(
                sessions=names)
        else:
            text = QCoreApplication.translate("Bridge", "Tuning to {freq} stops: {sessions}. Continue?").format(
                freq=fmt.frequency(int(round(freq)), "MHz", 4), sessions=names)
        yes = bool(self.asker(text))
        if not yes:
            self.declined_at = time.monotonic()
        return yes

    def _ask_dialog(self, text: str) -> bool:
        parent = self.parent() if isinstance(self.parent(), QWidget) else None
        title = QCoreApplication.translate("Bridge", "Stop the decoders?")
        ans = QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def licence_locked(self) -> bool:
        """Whether the licence acknowledgement stops a key-up now. The one
        exception is asked of the engine's actual device (Engine.radiates),
        not of the Settings choice, so a radio is gated from the moment the
        engine holds one; anything unsure counts as radiating."""
        if self.licence_ok:
            return False
        if self.face.sim_needs_licence:
            return True
        try:
            return bool(self.radio.radiates())
        except Exception:  # noqa: BLE001 - an engine that cannot say is treated as a radio
            return True

    def can_key(self) -> str:
        """'' if a key-up would be attempted, else the sentence why not."""
        if self.licence_locked():
            return LICENCE_SENTENCE
        if not self.st.get("running"):
            return self.st.get("error") or "The radio is not running"
        if not self.st.get("canTx"):
            # The engine's own sentence when it has one (playing a recording).
            return self.st.get("txBlocked") or "This device is receive-only"
        return self.st.get("txBlocked", "")

    def halt(self) -> None:
        """Stop transmitting now, the end of the over dropped (Escape, Halt
        TX, Stop); ptt(False) lets it finish going out."""
        self.radio.halt()

    def ptt(self, on: bool) -> bool:
        if on and self.licence_locked():
            self.say(LICENCE_SENTENCE)
            return False
        try:
            self.radio.ptt(on)
        except ValueError as e:      # TxRefused is a ValueError
            self.say(str(e))
            return False
        return True

    def send(self, mode: str, /, **msg) -> bool:
        if self.licence_locked():
            self.say(LICENCE_SENTENCE)
            return False
        try:
            self.radio.send(mode, **msg)
        except ValueError as e:
            self.say(str(e))
            return False
        return True

    def send_voice(self, slot: int) -> bool:
        """A voice memory (Engine.send_voice), behind the same licence gate."""
        if self.licence_locked():
            self.say(LICENCE_SENTENCE)
            return False
        try:
            self.radio.send_voice(slot)
        except ValueError as e:
            self.say(str(e))
            return False
        return True

    def spec(self, key: str) -> dict:
        return self.radio.STATE.spec[key]
