"""Under pytest, every window a test opens is destroyed when the test ends,
and each module's freed memory is given back when the module ends
(_give_back_the_modules_memory says why).

Why. The whole suite in one interpreter (beta-build's `pytest tests`) had
stopped finishing: past its 2400 s limit, and a run left for three hours
stalled at about 2,510 of 2,937 tests (21/10/2026). Each test was slower
than the one before because every window, dialog and face an earlier
test had opened was still alive - closed, which only hides a window -
and every main window built calls QApplication.setStyleSheet and setFont
(ohsnb/ui/__init__.py build(), and ohscore/ui/window.py on a theme
change), which repolish every widget in the process, hidden or not.
Measured on ohs-dev, 22/10/2026: 266 top-level windows and 9,400
widgets alive a third of the way through; test_ham_ui took 433 s after
the modules before it and 100 s with this in place, test_i18n 290 s and
32 s.

Closing is not enough and waiting for the collector is not either. A
closed main window is never garbage. For one (the one the leak hunt
found), BaseWindow.showEvent connects its window handle's screenChanged
to a lambda that calls the window, PyQt holds that lambda from C++
where the collector cannot see it, and the handle lives as long as the
window - so the window keeps itself alive until something destroys its
C++ side. That is harmless in the app,
which builds one window; the suite builds hundreds. So the C++ side is
destroyed outright: close(), deleteLater(), and the deferred deletes
delivered at once, on the GUI thread, between Qt calls - the same safe
point and the same steps as qtapp.shutdown() at the end of the run.

Which windows. Only parentless top-level widgets that did not exist
when the test started. Parentless, because a dialog or menu with a
parent goes with its parent, and one whose parent the class keeps is
the class's. Not there before the test, because anything a class made
in setUpClass (pytest runs that before a function fixture) is the
class's to keep for its other tests, and the test's own tearDown has
already run when this does. A test that kept a window for the next test
in a class attribute would see it destroyed; none does, and the run
would say so at once (a RuntimeError about a deleted C++ object), not
by getting slow.

The same windows are counted, and the modules whose tests left any
alive are listed at the end of the run, so it stays visible without
costing anything. Nearly every UI module is on that list: its tests
close their windows, which hides them and nothing more. A window that
survives the clean-up itself is a warning on the test that left it.

This is pytest's only (conftest.py): `unittest discover` and
tools/run-suite-split.sh do not need it - the split runner gives each
module its own interpreter - and nothing here changes what any test
checks.
"""
import collections
import warnings

import pytest

_left: collections.Counter = collections.Counter()


def _qt_app():
    """The QApplication if one exists. Never makes one: a test that does
    not use Qt must not start it."""
    import sys
    if "PyQt6.QtWidgets" not in sys.modules:
        return None
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance()


def _roots(app) -> dict:
    """The parentless top-level widgets, by C++ address: a widget Qt made
    itself (a tooltip, say) can come back in a new Python wrapper on each
    call, so the wrapper's id() would make an old window look new."""
    from PyQt6 import sip
    return {sip.unwrapinstance(w): w for w in app.topLevelWidgets() if w.parentWidget() is None}


def _destroy(widgets) -> None:
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    for w in widgets:
        if sip.isdeleted(w):
            continue
        try:
            w.close()
        except Exception:  # noqa: BLE001 - a closeEvent that raises must not keep the window alive
            pass
        if not sip.isdeleted(w):
            w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _malloc_trim():
    """glibc's malloc_trim(0), where there is a glibc; a no-op elsewhere."""
    import ctypes
    import ctypes.util
    import sys
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        return libc.malloc_trim
    except (OSError, AttributeError):     # musl has no malloc_trim
        return None


_trim = _malloc_trim()


def memoised(fn, max_bytes: int):
    """`fn(rng, *args)` - a simulator template drawn from a numpy
    Generator - remembered by the generator's state and the arguments.
    A repeat call returns the same samples, read-only, and leaves the
    generator exactly where `fn` would have left it, so whatever the
    simulator draws next is unchanged: a cached run is the uncached run.
    A function whose first argument is not a Generator (f1a_beacon) is
    remembered by its arguments alone.

    Why. The Radio simulator builds each band's stations when it opens,
    synchronously when it runs faster than real time (the tests): about
    2 s a radio, nearly all of it simsignals.voice. Every Radio test
    builds the same bands from the same seed (ham_helpers: simSeed 7,
    13:00 UTC), so across the suite that was about 380 s of the same
    templates made again (12% of the one-process run, main-thread
    samples on ohs-dev, 22/10/2026).

    Read-only so a template shared between two simulators can never be
    changed under one of them: anything that tried would fail loudly. At
    most `max_bytes` of templates are kept, the least recently used going
    first. Thread-safe: the real-time simulator builds bands on workers."""
    import collections
    import functools
    import threading
    lock = threading.Lock()
    cache: collections.OrderedDict = collections.OrderedDict()
    size = [0]

    import numpy as np

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        rng = args[0] if args and isinstance(args[0], np.random.Generator) else None
        key = (repr(rng.bit_generator.state) if rng is not None else None,
               args[1:] if rng is not None else args, tuple(sorted(kwargs.items())))
        with lock:
            hit = cache.get(key)
            if hit is not None:
                cache.move_to_end(key)
        if hit is not None:
            out, after = hit
            if rng is not None:
                rng.bit_generator.state = after
            return out
        out = fn(*args, **kwargs)
        out.flags.writeable = False
        with lock:
            if key not in cache:
                cache[key] = (out, rng.bit_generator.state if rng is not None else None)
                size[0] += out.nbytes
                while size[0] > max_bytes and cache:
                    _k, (old, _s) = cache.popitem(last=False)
                    size[0] -= old.nbytes
        return out
    wrapper.cache = cache
    return wrapper


def _remember_voices() -> None:
    try:
        import scratch_home  # noqa: F401  first, as in every test file: no test may touch the real config
        from ohscore.devices import simsignals
    except ImportError:          # this file copied into a scratch tree (test_conftest.py)
        return
    if not hasattr(simsignals.voice, "cache"):
        simsignals.voice = memoised(simsignals.voice, 512 << 20)
    # The NB simulator's lower and upper beacons, built afresh by every NB
    # radio: 2% of the run (60 s), the same two templates each time.
    if not hasattr(simsignals.f1a_beacon, "cache"):
        simsignals.f1a_beacon = memoised(simsignals.f1a_beacon, 64 << 20)


_remember_voices()


@pytest.fixture(autouse=True, scope="module")
def _give_back_the_modules_memory():
    """After each test module, collect its garbage and hand the freed
    memory back to the system.

    Why. Measured on ohs-dev (22/10/2026): with the windows destroyed,
    the one-process run still grew to 6 GB and was killed by a 6 GB
    limit at 55%, yet after gc.collect() and malloc_trim(0) a process
    that had run the worst modules held about 400 MB: the growth was not
    live objects but memory already freed and kept. With this, the whole
    run peaked at 2.9 GB.
    Two causes, both of the process rather than of any test. A radio's
    buffers sit in reference cycles (callbacks, threads, signal hooks),
    which only the collector frees, and the collector counts objects, not
    bytes - and in a UI module it does not run at all except from the
    event loop (ohscore/ui/qtapp.py). And glibc gives each thread that
    allocates its own arena; every radio runs a dozen threads that
    allocate numpy blocks, and a freed arena's memory stays with the
    process unless trimmed. tracemalloc showed 6.5 MB of real growth over
    a module that put 800 MB on the process.

    Per module, not per test: both together cost about 70 ms with the
    suite's heap, 200 s over 2,937 tests, and a module's own growth is
    bounded. On the main thread between Qt calls - qtapp.release_gc's
    safe point."""
    yield
    import gc
    gc.collect()
    if _trim is not None:
        _trim(0)


@pytest.fixture(autouse=True)
def _destroy_windows_the_test_opened(request):
    app = _qt_app()
    before = _roots(app) if app is not None else {}
    yield
    app = _qt_app()
    if app is None:
        return
    new = [w for k, w in _roots(app).items() if k not in before]
    if not new:
        return
    _left[request.node.nodeid.split("::", 1)[0]] += len(new)
    _destroy(new)
    still = [type(w).__name__ for k, w in _roots(app).items() if k not in before]
    if still:
        warnings.warn(f"{len(still)} top-level widget(s) outlived the test's clean-up: {', '.join(sorted(set(still)))}",
                      stacklevel=1)


def pytest_terminal_summary(terminalreporter):
    if not _left:
        return
    terminalreporter.section("windows tests left alive (destroyed by tests/conftest.py)")
    for mod, n in sorted(_left.items(), key=lambda kv: -kv[1]):
        terminalreporter.write_line(f"{n:5d}  {mod}")
