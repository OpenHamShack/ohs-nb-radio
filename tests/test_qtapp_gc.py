import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The QApplication's garbage collection (ohscore/ui/qtapp.py, _GuiThreadGc):
while the application exists, Python's cyclic collector runs only on the
GUI thread, from its event loop - never on a radio or decoder thread, and
never inside a Qt call that happens to allocate. A closed window freed by
a collection inside QApplication.setStyleSheet crashed the suite (06/10)."""
import gc
import os
import subprocess
import sys
import textwrap
import threading
import time
import unittest
import weakref
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QWidget
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class GuiThreadGc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohscore.ui import qtapp
        cls.app = qt_app()
        cls.interval = qtapp.GC_INTERVAL_MS / 1000.0

    def spin(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def churn(self):
        """Enough live new container objects to pass the first generation's
        threshold, as a real program's allocations would (freeing them at
        once would take the count back down)."""
        return [[] for _ in range(5 * gc.get_threshold()[0])]

    def test_automatic_collection_is_off_while_the_app_exists(self):
        self.assertFalse(gc.isenabled())

    def test_the_event_loop_collects_a_window_left_in_a_cycle(self):
        w = QWidget()
        w.me = w                      # a cycle: only the collector can free it
        gone = weakref.ref(w)
        del w
        junk = self.churn()  # noqa: F841 - kept until the end: see churn
        self.assertIsNotNone(gone(), "collected before the event loop ran: automatic collection is on")
        self.spin(self.interval * 2.5)
        self.assertIsNone(gone(), "the GUI thread's timer did not collect it")

    def test_garbage_made_on_another_thread_dies_on_the_gui_thread(self):
        died_on = []
        junk = []

        class Marker:
            def __del__(self):
                died_on.append(threading.current_thread().name)

        def worker():
            m = Marker()
            m.me = m
            del m
            junk.append(self.churn())  # would have started a collection here, on this thread

        t = threading.Thread(target=worker, name="radio-like-worker")
        t.start()
        t.join()
        self.assertEqual(died_on, [])
        self.spin(self.interval * 2.5)
        self.assertEqual(died_on, [threading.main_thread().name])

    def test_release_collects_and_hands_collection_back_until_the_next_make_app(self):
        # What the test helper does when a UI test module ends, so the
        # non-UI tests after it are collected as usual.
        from helpers import qt_app
        from ohscore.ui import qtapp
        w = QWidget()
        w.me = w
        gone = weakref.ref(w)
        del w
        qtapp.release_gc()
        self.assertIsNone(gone())
        self.assertTrue(gc.isenabled())
        qt_app()
        self.assertFalse(gc.isenabled())

    def test_a_collection_cannot_land_inside_set_style_sheet(self):
        # The crash itself, in a process of its own (it was a segfault):
        # a closed window kept only by a cycle, then a stylesheet change
        # whose repolish calls a Python event() that allocates, with the
        # collector set to run at every allocation. Without the guard this
        # died with SIGSEGV in the first round (Qt 6.8.2, PyQt 6.8).
        code = textwrap.dedent("""
            import gc, os
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from PyQt6.QtCore import QEvent
            from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
            from ohscore.ui.qtapp import make_app, shutdown
            app = make_app(["t"], "t", "t")

            class Busy(QWidget):
                def event(self, ev):
                    if ev.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange, QEvent.Type.Polish):
                        junk = [[] for _ in range(50)]
                    return super().event(ev)

            def window(cls):
                w = cls()
                lay = QVBoxLayout(w)
                for i in range(200):
                    lay.addWidget(QLabel(str(i), w))
                w.me = w
                w.show()
                return w

            app.setStyleSheet("QLabel { color: #123456; }")
            for r in range(10):
                old = window(QWidget)
                app.processEvents()
                old.close()
                del old
                new = window(Busy)
                gc.set_threshold(1, 1, 1)
                app.setStyleSheet("QLabel { color: #%02d3456; }" % r)
                gc.set_threshold(700, 10, 10)
                app.processEvents()
                new.close()
                new.deleteLater()
            shutdown()
            assert gc.isenabled()
            print("survived")
        """)
        env = dict(os.environ, PYTHONPATH=str(REPO))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env,
                           cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("survived", r.stdout)


if __name__ == "__main__":
    unittest.main()
