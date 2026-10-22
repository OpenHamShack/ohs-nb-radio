"""Diagnostics: the log file, start-up facts, and the report an operator
sends back.

Until October 2026 the apps logged to stderr only, and the Windows build is
a GUI program with no console, so when Ray ran NB against the real
satellite nothing he saw could be read afterwards: what Brian got was a
description of a screenshot. This module is what makes a run leave a
trace. It has no Qt in it (the engine and headless runs use it too);
ohscore/ui/diagnostics.py is the window's half: the screenshot, the dialog,
the zip.

Decisions:

- **Always on, in the data folder.** `<data>/logs/<app>.log`, 2 MB x 5
  rotated, INFO by default: a log the operator has to remember to turn on
  is never on for the run that went wrong. `-v` makes it (and the console)
  DEBUG. The data folder rather than the config folder because it is the
  one the guide already sends people to for their logbook.
- **Never on the radio's threads.** Every record goes through a
  QueueHandler into a bounded queue, and one listener thread does the
  disk writes. A stalled disk (an SD card mid-erase on a Pi, a roaming
  profile on Windows) then costs log lines, counted and reported when the
  queue drains, never a receive block. A full queue drops rather than
  waits for the same reason.
- **Exceptions land in the file** however they escape: sys.excepthook
  (which is also where PyQt sends an exception out of a slot),
  threading.excepthook, and faulthandler for a crash in C (libiio, Qt)
  that Python never sees, written to `faults.log` beside the log since
  faulthandler needs a plain file. Installing a sys.excepthook changes
  PyQt's behaviour on an exception in a slot from aborting the process to
  carrying on; for a radio that is the better of the two (the engine's
  watchdog and transmit timeout do not depend on the slot that failed),
  and the hook chains to the one it replaced, so a console still shows it.
- **Facts, and redacted values.** Start-up facts are versions and paths.
  When settings are saved the log has each changed key's old and new
  value and who changed it (12/10/2026: a key's name alone could not say
  what Ray's sound device had become), redacted as `redact()` redacts a
  report's config; the whole config goes into a diagnostics zip only
  after `redact()` and only when they choose to send it.
"""
from __future__ import annotations

import faulthandler
import json
import logging
import logging.handlers
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import host

LOG_BYTES = 2_000_000
LOG_BACKUPS = 5
QUEUE_MAX = 10_000
FORMAT = "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"

log = logging.getLogger("ohscore.diag")


# ---------------------------------------------------------------- the log file
class _DroppingQueueHandler(logging.handlers.QueueHandler):
    """A QueueHandler that drops a record when the queue is full instead of
    raising (the stock one reports Full through handleError, to stderr,
    which on the Windows build is nowhere), and counts what it dropped."""

    def __init__(self, q):
        super().__init__(q)
        self.dropped = 0

    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def prepare(self, record):
        # The stock prepare() formats the whole message here, on the
        # caller's thread; that is the point (the args may be mutable
        # numpy arrays by the time the listener runs), so keep it, but
        # tell the listener about drops on the first record that fits.
        if self.dropped:
            n, self.dropped = self.dropped, 0
            record = logging.makeLogRecord({**record.__dict__,
                                            "msg": f"{record.getMessage()} [{n} earlier log lines dropped: "
                                                   f"the log could not keep up]", "args": None})
        return super().prepare(record)


class LogSetup:
    """The running process's logging: where it writes and how to stop it."""

    def __init__(self, app: str, log_dir: Path, verbose: bool):
        self.app = app
        self.log_dir = Path(log_dir)
        self.path = self.log_dir / f"{app}.log"
        self.fault_path = self.log_dir / "faults.log"
        self.verbose = verbose
        self.facts: dict = {}
        self.queue: queue.Queue = queue.Queue(QUEUE_MAX)
        self.file_handler: logging.Handler | None = None
        self.console_handler: logging.Handler | None = None
        self.queue_handler = _DroppingQueueHandler(self.queue)
        self.listener: logging.handlers.QueueListener | None = None
        self.problem = ""
        self._fault_file = None
        self._hooks: tuple = ()

    def start(self, console: bool = True) -> "LogSetup":
        fmt = logging.Formatter(FORMAT)
        handlers = []
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(self.path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS,
                                                      encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)
            self.file_handler = fh
            handlers.append(fh)
        except OSError as e:
            # No log file must never stop the radio; say so on the console.
            self.problem = f"Could not open the log file {self.path}: {e}"
        # The Windows GUI build has no stderr at all (sys.stderr is None).
        if console and sys.stderr is not None:
            ch = logging.StreamHandler(sys.stderr)
            ch.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
            ch.setLevel(logging.DEBUG if self.verbose else logging.WARNING)
            self.console_handler = ch
            handlers.append(ch)
        self.listener = logging.handlers.QueueListener(self.queue, *handlers, respect_handler_level=True)
        self.listener.start()
        root = logging.getLogger()
        for h in list(root.handlers):
            if isinstance(h, _DroppingQueueHandler):
                root.removeHandler(h)
        root.addHandler(self.queue_handler)
        root.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        try:
            self._fault_file = open(self.fault_path, "a", encoding="utf-8")
            faulthandler.enable(self._fault_file)
        except (OSError, RuntimeError, ValueError):
            self._fault_file = None
        self._install_hooks()
        if self.problem:
            log.warning("%s", self.problem)
        return self

    def _install_hooks(self) -> None:
        prev_sys, prev_thread = sys.excepthook, threading.excepthook

        def sys_hook(t, v, tb):
            logging.getLogger("ohscore.crash").error("Uncaught exception", exc_info=(t, v, tb))
            if prev_sys is not None and sys.stderr is not None:
                prev_sys(t, v, tb)

        def thread_hook(args):
            if args.exc_type is SystemExit:
                return
            name = args.thread.name if args.thread is not None else "?"
            logging.getLogger("ohscore.crash").error("Uncaught exception in thread %s", name,
                                                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            if prev_thread is not None and sys.stderr is not None:
                prev_thread(args)

        sys.excepthook, threading.excepthook = sys_hook, thread_hook
        self._hooks = (prev_sys, prev_thread, sys_hook, thread_hook)

    def flush(self, timeout: float = 2.0) -> None:
        """Wait (up to `timeout`) until every queued record is on disk:
        before the files are zipped, and in tests."""
        end = time.monotonic() + timeout
        while not self.queue.empty() and time.monotonic() < end:
            time.sleep(0.01)
        # The listener has taken the last record; give it the moment to write it.
        time.sleep(0.02)
        if self.file_handler is not None:
            try:
                self.file_handler.flush()
            except (OSError, ValueError):
                pass

    def stop(self) -> None:
        global _CURRENT
        _clock_stop.set()
        root = logging.getLogger()
        root.removeHandler(self.queue_handler)
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        for h in (self.file_handler, self.console_handler):
            if h is not None:
                h.close()
        if self._hooks:
            prev_sys, prev_thread, mine_sys, mine_thread = self._hooks
            if sys.excepthook is mine_sys:
                sys.excepthook = prev_sys
            if threading.excepthook is mine_thread:
                threading.excepthook = prev_thread
            self._hooks = ()
        if self._fault_file is not None:
            try:
                faulthandler.disable()
                self._fault_file.close()
            except (OSError, ValueError):
                pass
            self._fault_file = None
        if _CURRENT is self:
            _CURRENT = None

    def files(self) -> list[Path]:
        """Every log file there is, newest first, faults.log last."""
        out = [p for p in [self.path] + [self.path.with_name(f"{self.path.name}.{i}")
                                         for i in range(1, LOG_BACKUPS + 1)] if p.is_file()]
        if self.fault_path.is_file() and self.fault_path.stat().st_size:
            out.append(self.fault_path)
        return out


_CURRENT: LogSetup | None = None


def log_dir(data_dir: Path, app: str = "") -> Path:
    """data_dir/logs; on a Mac with the default data folder, ~/Library/Logs/<app>
    (host.log_dir says why)."""
    return host.log_dir(app, data_dir) if app else Path(data_dir) / "logs"


def start_logging(app: str, data_dir: Path, verbose: bool = False, console: bool = True) -> LogSetup:
    """Start this process's logging (once; a second call replaces the first)."""
    global _CURRENT
    if _CURRENT is not None:
        _CURRENT.stop()
    _CURRENT = LogSetup(app, log_dir(data_dir, app), verbose).start(console=console)
    return _CURRENT


def current() -> LogSetup | None:
    return _CURRENT


def log_files(app: str, data_dir: Path) -> list[Path]:
    """The log files of `app` in `data_dir`, whether or not this process
    is the one writing them."""
    setup = _CURRENT if _CURRENT is not None and _CURRENT.app == app else LogSetup(app, log_dir(data_dir, app), False)
    return setup.files()


# ---------------------------------------------------------------- facts
def app_version(package: str) -> str:
    """An app's VERSION file (ohsnb/VERSION, ohsradio/VERSION), as its About shows it."""
    mod = sys.modules.get(package)
    if mod is None or not getattr(mod, "__file__", None):
        return ""
    try:
        return (Path(mod.__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return ""


def _os_name() -> str:
    if sys.platform == "win32":
        rel, ver, _csd, _ptype = platform.win32_ver()
        # Windows 11 still reports release "10"; the build number tells them apart.
        try:
            build = int(ver.split(".")[2])
        except (IndexError, ValueError):
            build = 0
        name = "11" if rel == "10" and build >= 22000 else rel
        return f"Windows {name} ({ver}, {platform.machine()})"
    if sys.platform == "darwin":
        # A Mac has no os-release; "Darwin 25.5.0" alone would send the
        # reader to a table of kernel versions to learn it is macOS 26.
        ver = platform.mac_ver()[0]
        return f"macOS {ver or '?'} (Darwin {platform.release()}, {platform.machine()})"
    try:
        info = platform.freedesktop_os_release()
        pretty = info.get("PRETTY_NAME") or info.get("NAME", "")
    except (OSError, AttributeError):
        pretty = ""
    return f"{pretty or platform.system()} (kernel {platform.release()}, {platform.machine()})"


def loaded_library(cdll) -> str:
    """The full path of the file behind a ctypes CDLL. ctypes only keeps
    the name it was asked for ("libiio.so.0", "libiio.dll"), and which
    file that resolved to is exactly what a Windows report needs: the
    libiio 1.0 DLL ADI's newest installer leaves in System32, or the 0.26
    one beside the program."""
    name = getattr(cdll, "_name", "") or ""
    handle = getattr(cdll, "_handle", None)
    if sys.platform == "win32" and handle:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(handle), buf, 1024):
                return buf.value
        except (OSError, AttributeError):
            pass
        return name
    base = os.path.basename(name).split(".so")[0]
    if base:
        try:
            with open("/proc/self/maps", encoding="utf-8", errors="replace") as f:
                for line in f:
                    path = line.rstrip("\n").split(" ")[-1]
                    if path.startswith("/") and os.path.basename(path).startswith(base + ".so"):
                        return path
        except OSError:
            pass
    return name


def _libiio() -> tuple[str, str]:
    try:
        from .devices.pluto import import_iio
        iio = import_iio()
    except Exception as e:  # noqa: BLE001 - DeviceError with the install sentence, or worse
        return f"not usable: {e}", ""
    ver = getattr(iio, "version", None)
    v = ".".join(str(x) for x in ver[:2]) + (f" ({ver[2]})" if len(ver) > 2 else "") if ver else "?"
    lib = getattr(iio, "_lib", None)
    return v, loaded_library(lib) if lib is not None else ""


def _pyserial() -> str:
    try:
        import serial
    except ImportError:
        return "not installed"
    return f"{getattr(serial, 'VERSION', getattr(serial, '__version__', '?'))} ({Path(serial.__file__).parent})"


def _cty(data_dir: Path | None) -> str:
    from . import dxcc
    for p in dxcc.candidates(data_dir):
        if p.is_file():
            return str(p)
    return "none found"


def _codec2() -> str:
    from . import host
    return host.find_library("codec2") or "not found"


def _ft8_encoder() -> str:
    try:
        from .modes import ft8
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unknown ({e})"
    return ft8.describe_encoder()


def _ft8_decoder() -> str:
    try:
        from .modes import ft8
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unknown ({e})"
    return ft8.describe_decoder()


def _jt9() -> str:
    """Where an installed WSJT-X's jt9 is. No build carries one since
    17/10/2026, so its absence is normal wherever ohsdigi decodes and is
    said calmly; it is only a fault where nothing else can decode."""
    found = host.find_tool("jt9")
    if found:
        return found
    try:
        from .modes import ft8
        have_ohsdigi = ft8._OHSDIGI_DEC is not None
    except Exception:  # noqa: BLE001 - a fact we cannot find must not stop the program
        have_ohsdigi = False
    return "not installed (optional; ohsdigi decodes)" if have_ohsdigi else "not found, and no ohsdigi: nothing decodes FT8"


def _shadow_summary() -> dict:
    try:
        from .modes import decoder_shadow
        return decoder_shadow.summary()
    except Exception as e:  # noqa: BLE001 - the report must be written whatever else is broken
        return {"summary": f"unavailable ({e})"}


def _q65_encoder() -> str:
    try:
        from .modes import q65
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unknown ({e})"
    if q65._OHSDIGI_Q65 is not None:
        return "ohsdigi"
    return f"q65code ({q65._Q65CODE})" if q65._Q65CODE else "not found"


def _q65_decoder() -> str:
    try:
        from .modes import q65
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unknown ({e})"
    return q65.describe_decoder()


def _js8_decoder() -> str:
    try:
        from .modes import js8
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unknown ({e})"
    return js8.describe_decoder()


def _update_verifier() -> str:
    # Which library checks the update feed's signature, proved by a test
    # vector: a frozen build missing part of cryptography would otherwise
    # only show it by never updating (tools/build-windows.ps1 looks for it).
    from . import update
    return update.describe_verifier()


def _pad() -> str:
    # What the AKP03E controller pad has in this installation: hidapi (how
    # Windows and macOS reach it), Pillow (its key pictures), the font. A
    # frozen build that lost either says so here; tools/build-windows.ps1
    # looks for both.
    try:
        from . import shacklibs
        shacklibs.pad()
        from shack_pad import diagnose
        return diagnose.describe_libraries()
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        return f"unavailable ({e})"


def _qt() -> tuple[str, str]:
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, qVersion
    except ImportError:
        return "not installed", ""
    return PYQT_VERSION_STR, qVersion()


def audio_devices() -> list[str]:
    from . import audio
    try:
        devs = audio.list_devices()
    except Exception as e:  # noqa: BLE001 - PortAudio can fail in many ways; the report says which
        return [f"could not list: {e}"]
    return [f"[{d['index']}] {d['name']} (in {d['inputs']}, out {d['outputs']}, {d['rate']:g} Hz)" for d in devs]


def facts(app_name: str, version: str, data_dir: Path | None = None, cfg: dict | None = None,
          audio: bool = True) -> dict:
    """What this installation is, once per run: versions, which shared
    libraries and helpers were found where, the audio devices. Flat
    {label: str | list}, in the order the report prints them."""
    import numpy
    from . import host
    cfg = cfg or {}
    pyqt, qt = _qt()
    iio_v, iio_path = _libiio()
    out = {
        "app": app_name,
        "version": version or "?",
        "os": _os_name(),
        "python": f"{platform.python_version()} ({sys.executable})",
        "frozen": f"yes ({host.bundle_dir()})" if getattr(sys, "frozen", False) else "no",
        "pyqt": pyqt,
        "qt": qt,
        "numpy": numpy.__version__,
        "libiio": iio_v,
        "libiio library": iio_path or "-",
        "pyserial": _pyserial(),
        "jt9": _jt9(),
        "ft8/ft4 encoder": _ft8_encoder(),
        "ft8/ft4 decoder": _ft8_decoder(),
        "q65 encoder": _q65_encoder(),
        "q65 decoder": _q65_decoder(),
        "js8 decoder": _js8_decoder(),
        "cty.dat": _cty(data_dir),
        "codec2": _codec2(),
        "update signatures": _update_verifier(),
        "controller pad": _pad(),
        "audio backend": cfg.get("audioBackend", "portaudio"),
        "audio out": cfg.get("audioOut") or "system default",
        "audio in": cfg.get("audioIn") or "system default",
    }
    if audio and cfg.get("audioBackend", "portaudio") != "null":
        out["audio devices"] = audio_devices()
        # What "system default" above meant on this run, as Settings › Audio
        # shows it: "default" alone says nothing about which headset.
        try:
            from . import audio as audio_mod
            d = audio_mod.default_devices()
            out["system default"] = (d["error"] or f"in {d['input'] or 'none'}, out {d['output'] or 'none'}")
        except Exception as e:  # noqa: BLE001 - as audio_devices(): the report says what failed
            out["system default"] = f"could not ask: {e}"
    return out


def log_facts(f: dict) -> None:
    """The facts as INFO lines, one per item, so a grep finds each."""
    log.info("---- %s %s starting ----", f.get("app", ""), f.get("version", ""))
    for k, v in f.items():
        if isinstance(v, list):
            log.info("%s: %d", k, len(v))
            for item in v:
                log.info("  %s", item)
        else:
            log.info("%s: %s", k, v)


def record_facts(setup: LogSetup, app_name: str, package: str, data_dir: Path, cfg: dict) -> LogSetup:
    """What each app's main() calls once it has its config: gather the
    start-up facts, keep them for a report, and log them."""
    try:
        setup.facts = facts(app_name, app_version(package), data_dir, cfg)
    except Exception as e:  # noqa: BLE001 - a fact we cannot find must not stop the program
        log.exception("could not gather start-up facts")
        setup.facts = {"app": app_name, "version": app_version(package), "facts": f"failed: {e}"}
    log_facts(setup.facts)
    start_clock_log()
    return setup


# ---------------------------------------------------------------- the clock
# FT8 and FT4 need the PC's clock within about a second of UTC, and a
# clock that is not being kept is the commonest reason a station hears
# nothing and is heard by nobody. NB has no time check of its own, and a
# network one (NTP, an HTTP Date) was judged not worth adding for a log
# line; so the log says what the system says about its own time source,
# with the commands it already has, at start-up and hourly. Off the
# start-up path: a slow w32tm must never hold the window back.
CLOCK_EVERY_S = 3600.0
_clock_stop = threading.Event()


def clock_source() -> str:
    """One line: whether the system keeps its clock, by its own report."""
    try:
        if host.WINDOWS:
            r = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, text=True, timeout=5,
                               **host.no_console())
            text = (r.stdout or r.stderr or "").strip()
            if r.returncode != 0:
                # "The service has not been started" is the useful answer.
                return f"w32tm: {' '.join(text.split())[:200] or f'exit {r.returncode}'}"
            want = ("Source", "Last Successful Sync Time", "Leap Indicator", "Stratum")
            got = {}
            for line in text.splitlines():
                k, _, v = line.partition(":")
                if k.strip() in want:
                    got[k.strip()] = v.strip()
            return "w32tm: " + (", ".join(f"{k} {got[k]}" for k in want if k in got) or "no status")
        if sys.platform == "darwin":
            return "macOS: not checked (asking needs administrator rights)"
        r = subprocess.run(["timedatectl", "show", "--property=NTP", "--property=NTPSynchronized"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return f"timedatectl: {' '.join((r.stderr or '').split())[:200] or f'exit {r.returncode}'}"
        props = dict(line.partition("=")[::2] for line in r.stdout.splitlines() if "=" in line)
        return (f"timedatectl: NTP service {props.get('NTP', '?')}, "
                f"synchronised {props.get('NTPSynchronized', '?')}")
    except FileNotFoundError as e:
        return f"not checked: {e.filename or e} not found"
    except (OSError, subprocess.SubprocessError) as e:
        return f"could not ask: {e}"


def log_clock() -> None:
    log.info("clock: %s UTC; time source: %s",
             time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), clock_source())


def start_clock_log(every: float = CLOCK_EVERY_S) -> threading.Thread:
    """log_clock() now and every `every` seconds, on a daemon thread, until
    the log stops."""
    _clock_stop.clear()

    def run():
        while True:
            try:
                log_clock()
            except Exception:  # noqa: BLE001 - a log line must never take a thread down noisily
                log.debug("clock check failed", exc_info=True)
            if _clock_stop.wait(every):
                return

    th = threading.Thread(target=run, name="ohscore-clock", daemon=True)
    th.start()
    return th


# ---------------------------------------------------------------- engine watch
class Watch:
    """Turns the engine's 10 Hz status into log lines worth reading.

    The supervisor calls tick() ten times a second with the state; most
    ticks log nothing. `keys` are logged on every change (lock states, the
    link to an external radio, keyed): they change a few times a run.
    `slow` keys change continuously while something is moving (the
    IC-9700's frequency as its knob turns) and are logged at most every
    `slow_s`, with the value they settled on. Counters (overruns,
    underruns) are never logged one by one: every `every` seconds, a line
    saying how many there were in that window, only if there were any."""

    def __init__(self, logger: logging.Logger, keys=(), slow=(), every: float = 10.0, slow_s: float = 5.0):
        self.log = logger
        self.keys = tuple(keys)
        self.slow = tuple(slow)
        self.every = every
        self.slow_s = slow_s
        self.last: dict = {}
        self.slow_logged: dict = {}      # key -> (value logged, monotonic time)
        self.counts: dict = {}           # counter -> total at the last summary
        self.next_summary = None

    def seed(self, st: dict) -> None:
        """Take the starting values from the state the engine starts with,
        before its threads run. Seeding from the first tick instead missed
        any change made before it: a beacon lock found within the first
        100 ms - which a narrow search from a trusted correction does -
        was never logged as searching -> locked."""
        self.last = {k: st.get(k) for k in self.keys}

    def tick(self, now: float, st: dict, counters: dict, detail=None) -> None:
        for k in self.keys:
            v = st.get(k)
            if k not in self.last:
                self.last[k] = v
                continue
            if v != self.last[k]:
                extra = detail(k, st) if detail is not None else ""
                self.log.info("%s: %s -> %s%s", k, _short(self.last[k]), _short(v), extra)
                self.last[k] = v
        for k in self.slow:
            v = st.get(k)
            was, at = self.slow_logged.get(k, (None, -1e9))
            if v != was and v not in (None, 0, "") and now - at >= self.slow_s:
                self.log.info("%s: %s", k, _short(v))
                self.slow_logged[k] = (v, now)
        if self.next_summary is None:
            self.next_summary = now + self.every
            self.counts = dict(counters)
            return
        if now >= self.next_summary:
            self.next_summary = now + self.every
            parts = []
            for k, total in counters.items():
                d = total - self.counts.get(k, 0)
                if d > 0:
                    parts.append(f"{k} +{d} (total {total})")
            self.counts = dict(counters)
            if parts:
                self.log.warning("in the last %.0f s: %s", self.every, ", ".join(parts))


def _short(v) -> str:
    if isinstance(v, float):
        return f"{v / 1e6:.6f} MHz" if abs(v) >= 1e6 else f"{v:.1f}"
    if isinstance(v, str):
        return repr(v[:160])
    return str(v)


# ---------------------------------------------------------------- the report
# A key that looks like it holds a secret, in any config or status a
# report includes. Nothing in either app holds one today (rigctld has no
# authentication, QRZ links are plain URLs), so this is a guard for the
# day a log-upload key or a password arrives, not a list of known fields.
_SECRET_KEY = re.compile(r"passw|passphrase|token|secret|api_?key|apikey|credential|cookie|private_?key|auth",
                         re.IGNORECASE)
_URL_CRED = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^:/@\s]+):(?P<pw>[^@/\s]+)@", re.IGNORECASE)
REDACTED = "<redacted>"
# Secrets by shape, whatever key holds them: a key block, and the prefixes
# of the API tokens an operator is likeliest to paste somewhere (OpenAI/
# Anthropic-style sk-, GitHub, Slack, AWS, a JWT). Added for HAM's planned
# QRZ/Clublog keys (DESIGN-HAM "Added to the plan" 4): a key stored later
# under a name nobody anticipated is still caught. Deliberately not "any
# long random-looking string": a Pluto's hw_serial is 34 hex digits, and
# the report is about the radio.
_SECRET_SHAPE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}"
                           r"|\bxox[abpr]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b"
                           r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+")


def redact(obj):
    """A copy of `obj` (dicts, lists, strings) with secret-looking values
    replaced: any value under a secret-looking key, and the password in a
    user:password@ URL anywhere. The callsign and locator stay: they are
    what the report is about."""
    if isinstance(obj, dict):
        return {k: (REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) and v not in ("", None)
                    else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact(v) for v in obj)
    if isinstance(obj, str):
        if _SECRET_SHAPE.search(obj):
            return REDACTED
        return _URL_CRED.sub(lambda m: f"{m['scheme']}{m['user']}:{REDACTED}@", obj)
    return obj


SETTING_CHARS = 160


def setting_value(key: str, v) -> str:
    """A setting's value for a log line (Engine._log_saved): redacted as a
    report's config is (a secret-looking key, or a value shaped like a
    token, whatever its key), and cut at SETTING_CHARS so a list of
    memories or converters cannot swamp the line. The key test is
    _SECRET_KEY, not anything containing "key": that would hide
    keyerRepeat, which the log is meant to show."""
    v = redact({key: v})[key]
    text = repr(v) if isinstance(v, str) else json.dumps(v, sort_keys=True, default=str)
    return text if len(text) <= SETTING_CHARS else text[:SETTING_CHARS] + "..."


# A secret written into a log line as `password=…`, `token: …`, `api_key "…"`:
# the key's name, its separator, then the value up to the next space or
# quote. Log lines are free text, so redact() (which needs a key to look
# at) cannot see these; added with automatic diagnostics upload (12/10/2026),
# when the log first left the machine without the operator reading it.
_SECRET_ASSIGN = re.compile(r"(?P<key>\b[\w.-]*(?:passw\w*|passphrase|token|secret|api_?key|apikey|credential|cookie"
                            r"|private_?key|authorization)\b[\"']?\s*[:=]\s*)(?P<q>[\"']?)(?P<val>[^\s\"',;]+)",
                            re.IGNORECASE)


def redact_text(text: str) -> str:
    """Free text (a log, a status line) with what looks like a secret
    replaced: a value after a secret-looking name (`password=…`), a
    user:password@ URL's password, and any token by its shape. Unlike
    redact() on a string, only the secret goes, not the whole line: a log
    line that mentions a key is still the line the reader needs. Device
    serial numbers go as well (scrub_serials): every upload path runs
    through here, so that is the one place they can be caught for all."""
    text = _SECRET_SHAPE.sub(REDACTED, text)
    text = _URL_CRED.sub(lambda m: f"{m['scheme']}{m['user']}:{REDACTED}@", text)
    text = _SECRET_ASSIGN.sub(lambda m: f"{m['key']}{m['q']}{REDACTED}", text)
    return scrub_serials(text)


# ---------------------------------------------------------------- serial numbers
# A device's serial number identifies one radio, and so one operator, as
# surely as a name: openhamshack.com publishes no personal name, and an
# uploaded report must not carry the equivalent. Added for 0.1.18, when
# the IC-9700's serial was found in by-id port names and Windows device
# ids that reach the log through saved settings, fault details and the
# diagnostic. The IC-9700 diagnostic (ohsnb/rigdiag.scrub) had its own
# rules; these are those rules made safe for a whole log and shared.
#
# Deliberately not rigdiag's "any run of six digits or more": a log is
# full of frequencies in hertz (10489750000), sample rates and dates, and
# they are what a reader of the report needs. So serials are found by
# where they sit - a by-id name, a Windows instance id, pyserial's SER=,
# a key called serial - and by the two shapes that are unmistakable (a
# Pluto's 34 hex digits, an SDRplay serial's six digits and four hex with
# a letter). A value found by key is then removed everywhere else in the
# text too: SoapySDR's label repeats the serial it lists under "serial".
SERIAL = "<serial>"
# /dev/serial/by-id/usb-Silicon_Labs_CP2102N_..._IC-9700_13012144_A-if00-port0:
# the serial is among the underscore-separated parts before -ifNN/-portN.
_BY_ID = re.compile(r"\busb-(?P<name>[\w.,+-]+?)(?P<tail>-if\d+(?:-port\d+)?|-port\d+)\b")
# USB\VID_10C4&PID_EA60\IC-9700_13012144_A, FTDIBUS\VID_0403+PID_6001+A50285BIA\0000,
# and either with its backslashes doubled, as repr() and JSON write them.
_PNP = re.compile(r"(?i)\b(?P<head>(?:USB|FTDIBUS|USBSTOR|HID|SWD)\\{1,2}VID_[0-9A-F]{4}[&+]PID_[0-9A-F]{4}"
                  r"[^\\\s'\"]*?)(?P<sep>\\{1,2}|\+)(?P<val>[^\\\s'\",;)\]]+)")
# pyserial's hwid: "USB VID:PID=10C4:EA60 SER=IC-9700 13012144 A LOCATION=1-1.2:1.0"
# (the IC-9700's serial has spaces in it, so up to LOCATION= or the end).
_SER = re.compile(r"(?i)\bSER=(?P<val>(?:(?!\s+LOCATION=)[^\n'\"),\]])+)")
# hw_serial: …, 'serial': '191101D142', serial=UQRUR7HPFYWAMKGY, serialNumber=…
# Six characters at least, so "serial: ?" and "pyserial: 3.5" stay.
_SERIAL_KEY = re.compile(r"(?i)(?P<key>\b[\w-]*serial(?:_?(?:number|no))?[\"']?\s*[:=]\s*[\"']?)"
                         r"(?P<val>[A-Za-z0-9][\w.-]{5,})")
_ICOM = re.compile(r"\b(?P<model>IC-?\d{3,4}[A-Z]*)(?P<sep>[ _])\d{6,}")
_SDRPLAY_LABEL = re.compile(r"(?P<head>\bSDRplay Dev\d+ \S+) [0-9A-Za-z]{6,}")
_SDRPLAY_SHAPE = re.compile(r"\b(?=[0-9A-F]*[A-F])\d{6}[0-9A-F]{4}\b")
_PLUTO_SHAPE = re.compile(r"\b[0-9a-f]{34}\b")


def _by_id(m: re.Match) -> str:
    parts = m["name"].split("_")
    parts = [re.sub(r"\d{6,}", SERIAL, p) for p in parts]
    # A serial with fewer than six digits in a row (FTDI's A50285BI, a
    # Pluto's hex) is the last part when it is long and mostly not a word.
    last = parts[-1]
    if len(last) >= 8 and sum(c.isdigit() for c in last) >= 3 and SERIAL not in last:
        parts[-1] = SERIAL
    return f"usb-{'_'.join(parts)}{m['tail']}"


def scrub_serials(text) -> str:
    """`text` with every device serial number it can find replaced by
    <serial>; everything else, frequencies included, as it was."""
    text = str(text)
    known = {m["val"].strip() for m in _SERIAL_KEY.finditer(text)} | {m["val"].strip() for m in _SER.finditer(text)}
    text = _BY_ID.sub(_by_id, text)
    text = _PNP.sub(lambda m: f"{m['head']}{m['sep']}{SERIAL}", text)
    text = _SER.sub(f"SER={SERIAL}", text)
    text = _SERIAL_KEY.sub(lambda m: f"{m['key']}{SERIAL}", text)
    text = _ICOM.sub(lambda m: f"{m['model']}{m['sep']}{SERIAL}", text)
    text = _SDRPLAY_LABEL.sub(lambda m: f"{m['head']} {SERIAL}", text)
    text = _SDRPLAY_SHAPE.sub(SERIAL, text)
    text = _PLUTO_SHAPE.sub(SERIAL, text)
    for v in sorted((v for v in known if len(v) >= 6 and v != SERIAL), key=len, reverse=True):
        text = text.replace(v, SERIAL)
    return text


# ---------------------------------------------------------------- notable events
# What automatic diagnostics upload (ohscore/diagupload.py) reacts to. The
# places a fault is known - the engine's emergency unkey, the transmit
# thread's failure, the IC-9700 link, the sound card - call notable(), which
# is only a WARNING line on its own logger with the trigger attached; the
# uploader listens to that logger. A log line rather than a callback so the
# engine and the rig code know nothing about uploads, the fault is in the
# log the report carries, and every thread can call it without a lock.
NOTABLE_LOGGER = "ohscore.notable"
TRIGGERS = ("over-failed", "over-aborted", "no-power-out", "rig-link-lost", "audio-failed", "radio-lost", "crash",
            "ic9700-diagnostic", "ic9700-level-set")


def notable(trigger: str, detail: str = "") -> None:
    """Note that `trigger` (one of TRIGGERS) happened, with a sentence."""
    logging.getLogger(NOTABLE_LOGGER).warning("%s%s", trigger, f": {detail}" if detail else "",
                                              extra={"ohs_trigger": trigger})


# The newest copy of each report a run produced that is not in the log as
# such (the IC-9700 diagnostic's text), for the next diagnostics bundle.
# Process memory only: a report from a previous run has already been sent
# or saved, or the operator did not want it.
_ATTACHED: dict[str, str] = {}
_ATTACHED_LOCK = threading.Lock()


def attach(name: str, text: str) -> None:
    with _ATTACHED_LOCK:
        _ATTACHED[name] = text


def attachments() -> dict[str, str]:
    with _ATTACHED_LOCK:
        return dict(_ATTACHED)


def redact_json_file(path: Path) -> bytes | None:
    """A JSON file's contents, redacted, or None if it does not exist. A
    file that is not JSON is included as a note, not as its text: it could
    be anything."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        return f"(could not read {path}: {e})\n".encode()
    try:
        data = json.loads(text)
    except ValueError as e:
        return f"(not valid JSON, so not included: {e})\n".encode()
    return (json.dumps(redact(data), indent=2, sort_keys=True) + "\n").encode()


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}" if abs(v) < 1e6 else f"{v:.1f}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    return str(v)


# Engine state shown at the top of the report's engine section, in this
# order, where the app has them; the whole snapshot follows as JSON.
SUMMARY_KEYS = ("running", "error", "device", "simWhy", "fs", "cpu", "cpuWait", "overruns", "mode", "vfo", "rxDial", "txDial", "keyed",
                "txSource", "txBlocked", "rxLock", "rxCorr", "rxErr", "rxSnr", "beaconUsed", "txLock", "txLockState",
                "txCorr", "txPpm", "txCorrTrusted", "vsBeacon", "txRadio", "rigLink", "rigFreq", "rigMode", "rigKeyed",
                "rigError", "rigTxCorr", "band", "segment", "licenceClass", "plutoUri", "hl2Address", "callsign",
                "locator", "ft8Decoder", "ft8DecoderInUse")


def build_report(f: dict, state: dict | None, *, device_context: dict | None = None,
                 screen: dict | None = None, extra: dict | None = None, now: float | None = None) -> str:
    """report.txt: `== section ==` headings over `key: value` lines, so
    both a person and a test can read it."""
    now = time.time() if now is None else now
    lines = [f"{f.get('app', 'OpenHamShack')} diagnostics report",
             f"created: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}", ""]

    def section(title: str, items):
        lines.append(f"== {title} ==")
        for k, v in items:
            if isinstance(v, list) and v and not isinstance(v[0], (dict, list)):
                lines.append(f"{k}: {len(v)}")
                lines.extend(f"  {x}" for x in v)
            else:
                lines.append(f"{k}: {_fmt(v)}")
        lines.append("")

    section("installation", list(f.items()))
    if screen:
        section("screen", list(screen.items()))
    st = redact(dict(state or {}))
    if st:
        section("engine", [(k, st[k]) for k in SUMMARY_KEYS if k in st])
        dev = st.get("deviceStatus") or {}
        if dev:
            section("device", list(dev.items()))
        aud = st.get("audio") or {}
        if aud:
            section("audio", list(aud.items()))
    # The FT8/FT4 decoder and its shadow, compared slot by slot since the
    # program started (ohscore/modes/decoder_shadow.py): what a tester's
    # report needs to say whether the two decoders ever disagreed on the air.
    shadow = _shadow_summary()
    if shadow:
        section("ft8/ft4 decoder comparison", list(shadow.items()))
    section("radio context (IIO attributes)", list((device_context or {}).items())
            or [("context", "none open (not a Pluto, or the radio is not running)")])
    if extra:
        section("more", list(redact(extra).items()))
    if st:
        lines.append("== full engine state ==")
        lines.append(json.dumps(st, indent=1, sort_keys=True, default=str))
        lines.append("")
    return "\n".join(lines)


def bundle_name(app: str, now: float | None = None) -> str:
    return f"{app}-diagnostics-{time.strftime('%Y%m%d-%H%M', time.localtime(time.time() if now is None else now))}.zip"


def write_zip(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    """Write the entries (name, contents) to a zip at `path`, via a
    temporary file so a failed save never leaves half a zip behind."""
    import zipfile
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries:
                z.writestr(name, data)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def collect(app_dir: str, data_dir: Path, conf_path: Path | None, ui_path: Path | None, report: str,
            status_lines: list[str], screenshot: bytes | None = None) -> list[tuple[str, bytes]]:
    """Everything a diagnostics zip holds, as (name, contents), in the
    order the dialog lists them. The logs are flushed first so the zip has
    the line that says it was made."""
    setup = current()
    if setup is not None:
        setup.flush()
    out: list[tuple[str, bytes]] = [("report.txt", report.encode("utf-8"))]
    out.append(("status-recent.txt", ("\n".join(status_lines) + "\n").encode("utf-8")))
    for p in log_files(app_dir, data_dir):
        try:
            out.append((f"logs/{p.name}", p.read_bytes()))
        except OSError as e:
            out.append((f"logs/{p.name}.unreadable.txt", f"{e}\n".encode()))
    for name, p in (("config.json", conf_path), ("ui.json", ui_path)):
        if p is None:
            continue
        data = redact_json_file(p)
        if data is not None:
            out.append((name, data))
    if screenshot:
        out.append(("screenshot.png", screenshot))
    return out
