"""The QApplication's life, the same for every app: made once with the
app's names, garbage collected only on its own thread and only from its
event loop (see _GuiThreadGc), told to quit by a signal the way the
operator's Quit does (see QuitOnSignals), and destroyed explicitly at the
end (see shutdown)."""
from __future__ import annotations

import gc
import logging
import signal
import socket
import sys

log = logging.getLogger("ohscore.ui.qtapp")

# How often the GUI thread considers collecting (see _GuiThreadGc.check).
GC_INTERVAL_MS = 1000
# Ticks after which whatever has accumulated is collected even below
# Python's first-generation threshold, so a closed window's cycle is gone
# within ~10 s rather than whenever enough else has been allocated.
GC_IDLE_TICKS = 10


class _GuiThreadGc:
    """Python's cyclic garbage collector, run by a timer on the GUI thread
    instead of whenever and wherever an allocation tips a threshold.

    Why. A Qt object Python owns (a window without a parent, its bridge)
    and that ends up in a reference cycle - signal connections to lambdas
    and bound methods make cycles of nearly every window - is destroyed when
    the collector gets round to it, C++ side and all its children with it.
    Left to the automatic collector that is at an arbitrary allocation: on
    any thread (the radio's, a decoder's; Qt objects must die on their own
    thread), and, on the GUI thread, possibly in the middle of a Qt call
    that is calling back into Python. QApplication.setStyleSheet is the one
    that was caught: it takes a list of every widget, and repolishing each
    one calls Python reimplementations (event(), sizeHint()...) that
    allocate; a collection there freed a closed window's widgets that were
    later in the list, and Qt went on to repolish freed memory. The test
    suite died in test_ham_ui's theme switch (06/10/2026, five runs of five)
    - only after an ohsdigi decode had run earlier in the process, not because
    of anything the decoder did (it never touches Qt or Python objects from
    its threads) but because its allocations moved where the collector
    happened to run. With the thresholds forced to 1 the same crash happened
    with no ohsdigi at all, and the kernel log showed the earlier crashes all
    on the main thread, in QWidget::update, QWidget::setPalette and QtTest.

    Run from a timer, a collection happens only between events, from the
    event loop itself, where no Qt call is half done and nothing in Qt
    holds a pointer it has not yet used. This is what calibre does for the
    same reason. Automatic collection is off for the whole process while
    the application is in use; release_gc() and shutdown() turn it back
    on."""

    def __init__(self, app):
        from PyQt6.QtCore import QTimer
        self.threshold0 = gc.get_threshold()[0]
        self.ticks = 0
        gc.disable()
        self.timer = QTimer(app)
        self.timer.setInterval(GC_INTERVAL_MS)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self):
        """One tick: a full collection once Python's first-generation count
        has passed its threshold, or anything at all has accumulated for
        GC_IDLE_TICKS ticks.

        Full, not generation by generation as the automatic collector goes:
        its older generations are collected after so many younger
        collections, which at one tick a second rather than one per few
        thousand allocations would leave a closed window (long since in the
        oldest generation) alive for minutes - and every live widget is one
        more that a theme change repolishes. A full collection with a
        OpenHamShack Radio window open measured 4 ms (06/10/2026, development machine)."""
        self.ticks += 1
        c0 = gc.get_count()[0]
        if c0 > self.threshold0 or (c0 and self.ticks >= GC_IDLE_TICKS):
            gc.collect()
            self.ticks = 0

    def stop(self):
        self.timer.stop()
        gc.enable()


class QuitOnSignals:
    """SIGTERM, SIGINT (Ctrl-C) and SIGHUP quit the application as its own
    Quit does - Cmd-Q on a Mac: QApplication.quit() from the event loop,
    which closes every window (each window's closeEvent unkeys and saves)
    and then ends app.exec().

    Why not the window's close() from the signal handler, as until
    17/10/2026. A Python signal handler runs on the GUI thread at whatever
    Python bytecode comes next, which in a Qt program is very often inside
    a Qt call that has called back into Python - a widget's paintEvent,
    say, from QWidgetRepaintManager::paintAndFlush. Closing the window
    there tore it down under the paint still in progress: NB on a Mac,
    full screen, `kill -TERM` -> SIGSEGV in QBackingStore::endPaint
    (crash report of 17/10/2026, 17:55). So the handler does nothing at
    all but exist (Python's own C-level handler has already written the
    signal's number to a socket, signal.set_wakeup_fd); a QSocketNotifier
    on the other end wakes the event loop, and its slot - an ordinary
    event, never nested in a paint - asks the application to quit. The
    socket also wakes a Qt event loop that is blocked in the system,
    which a Python flag alone cannot: the 250 ms idle timer that used to
    give Python the chance to run is gone.

    Where the wakeup socket cannot be had (not on the main thread, say), a
    timer polling a flag the handler sets does the same, a little later.
    `close()` puts back the handlers and wakeup fd it found."""

    SIGNALS = ("SIGTERM", "SIGINT", "SIGHUP")
    POLL_MS = 200

    def __init__(self, app=None):
        from PyQt6.QtCore import QSocketNotifier, QTimer
        from PyQt6.QtWidgets import QApplication
        self.app = app or QApplication.instance()
        self.got: int | None = None
        self.old: dict = {}
        self.old_fd = None
        self.notifier = self.timer = None
        self.rsock = self.wsock = None
        for name in self.SIGNALS:
            num = getattr(signal, name, None)
            if num is None:
                continue                  # SIGHUP: not on Windows
            try:
                self.old[num] = signal.signal(num, self._handler)
            except (OSError, ValueError):
                continue
        try:
            self.rsock, self.wsock = socket.socketpair()
            for s in (self.rsock, self.wsock):
                s.setblocking(False)
            self.old_fd = signal.set_wakeup_fd(self.wsock.fileno(), warn_on_full_buffer=False)
            self.notifier = QSocketNotifier(self.rsock.fileno(), QSocketNotifier.Type.Read, self.app)
            self.notifier.activated.connect(self._woken)
        except (OSError, ValueError) as e:
            log.debug("no signal wakeup socket (%s): polling for signals instead", e)
            self._close_socks()
            self.timer = QTimer(self.app)
            self.timer.timeout.connect(self._poll)
            self.timer.start(self.POLL_MS)
        log.debug("%s quit through the event loop (%s)", ", ".join(signal.Signals(n).name for n in self.old),
                  "wakeup socket" if self.notifier is not None else "polled")

    def _handler(self, signum, _frame) -> None:
        # Nothing that touches Qt (class docstring): a flag for the timer.
        self.got = signum

    def _woken(self, *_a) -> None:
        nums = b""
        try:
            while True:
                chunk = self.rsock.recv(64)
                if not chunk:
                    break
                nums += chunk
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            return
        mine = [n for n in nums if n in self.old]
        if mine:
            self._quit(mine[-1])

    def _poll(self) -> None:
        if self.got is not None:
            self._quit(self.got)

    def _quit(self, signum: int) -> None:
        # Asked again on every signal: a quit a window refused (its
        # closeEvent ignored) is not latched as done.
        self.got = None
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        log.info("%s: quitting as the Quit command does (windows closed, then the event loop ends)", name)
        self.app.quit()

    def _close_socks(self) -> None:
        for s in (self.rsock, self.wsock):
            if s is not None:
                s.close()
        self.rsock = self.wsock = None

    def close(self) -> None:
        if self.notifier is not None:
            self.notifier.setEnabled(False)
            self.notifier = None
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.old_fd is not None:
            try:
                signal.set_wakeup_fd(self.old_fd)
            except (OSError, ValueError):
                pass
            self.old_fd = None
        for num, old in self.old.items():
            try:
                signal.signal(num, old if old is not None else signal.SIG_DFL)
            except (OSError, ValueError):
                pass
        self.old = {}
        self._close_socks()


def make_app(argv, name: str, desktop: str):
    """The process's QApplication, made on first call. `name` is what Qt
    shows ("OpenHamShack QO-100 NB"), `desktop` the .desktop file and
    organisation name ("openhamshack-nb").

    `name` changed with the OpenHamShack rename (09/10/2026) and `desktop`
    on 17/10/2026, with the package. Both are safe only because nothing
    derives a path from either: there is no QSettings and no
    QStandardPaths App* location here - settings live where
    ohscore/config.py puts them, under the app id. Should either ever be
    used, key it on the app id, not on `name` or `desktop`, or a later
    rename would move the operator's settings out from under them.

    No setApplicationDisplayName: the display name already defaults to
    `name`, and setting it explicitly makes Qt append it to every window
    title on X11 and Windows ("About X - X"), which the dialogs' own titles
    already say."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app = QApplication(list(argv or sys.argv[:1]))
        app.setApplicationName(name)
        app.setOrganizationName(desktop)
        app.setDesktopFileName(desktop)
        # An install proof's photograph, only when one is asked for
        # (snapshot.py says why the app takes it itself).
        from . import snapshot
        app._lb_snapshot = snapshot.arm(app)
    if getattr(app, "_lb_gc", None) is None:
        app._lb_gc = _GuiThreadGc(app)
    return app


def release_gc():
    """Collect now, and hand collection back to Python's automatic collector
    until make_app() is next called.

    For a process that keeps its QApplication but stops using it: the test
    suite, whose other tests share the process with the UI tests and never
    turn the event loop, so the guard's timer would never fire for them and
    their cyclic garbage (radios, with their buffers) would pile up: the
    full suite's peak memory went from 3.1 GB to 4.2 GB until the test
    helper called this at the end of each UI test module (2.3 GB since,
    06/10/2026). Call it on the GUI thread, between
    Qt calls, once its windows are closed: this collection is the safe one
    that frees them, and what is left alive afterwards is not garbage."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    guard = getattr(app, "_lb_gc", None) if app is not None else None
    if guard is None:
        return
    gc.collect()
    guard.stop()
    app._lb_gc = None


def shutdown():
    """Destroy every window and then the QApplication, now, while Python is
    still whole.

    Left to interpreter shutdown, PyQt deletes the C++ side of whatever is
    still referenced - the application, windows, their timers - in the order
    module teardown happens to reach them. On Linux that has been harmless;
    on Windows it ended processes with an access violation after their work
    was done (the test suite in two runs of five, the screenshot tool), so
    the exit code said "crashed" about a program that had finished cleanly.
    Everything that makes a QApplication calls this once it is done with it."""
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    app.processEvents()
    release_gc()
    sip.delete(app)
