"""tests/conftest.py, the pytest hooks that destroy every window a test
left alive and give back each module's memory: run for real, under
pytest in a child process, against scratch trees. The windows: one test
keeps a window alive the way the UI tests do (closed, and still
referenced), one opens nothing, one checks that what the class made in
setUpClass is still whole. The memory: a module leaves a reference
cycle with the collector off, as a UI module has it, and the next
module finds it collected."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import PyQt6.QtWidgets  # noqa: F401
    import pytest  # noqa: F401
    HAVE = True
except ImportError:  # pragma: no cover - the conftest only runs under pytest, with Qt
    HAVE = False

HERE = Path(__file__).resolve().parent

SCRATCH = '''import os, unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

KEPT = []      # what a bridge or a connected lambda does: keeps the window referenced


class Windows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["t"])
        cls.shared = QWidget()
        cls.shared.show()

    def test_1_leaves_a_window_and_a_dialog(self):
        w = QWidget()
        w.show()
        w.close()
        KEPT.append(w)
        d = QDialog()
        d.show()
        KEPT.append(d)

    def test_2_finds_only_the_classes_window(self):
        from PyQt6 import sip
        tops = [w for w in QApplication.topLevelWidgets() if w.parentWidget() is None]
        self.assertEqual(tops, [self.shared])
        self.assertTrue(all(sip.isdeleted(w) for w in KEPT))

    def test_3_the_classes_window_is_whole(self):
        self.assertTrue(self.shared.isVisible())
'''


@unittest.skipUnless(HAVE, "needs PyQt6 and pytest")
class DestroysWhatATestLeft(unittest.TestCase):
    def test_a_tests_windows_are_destroyed_and_listed_and_the_classes_kept(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(HERE / "conftest.py", tmp / "conftest.py")
        (tmp / "test_scratch.py").write_text(SCRATCH)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_scratch.py"],
                             cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("3 passed", res.stdout)
        summary = res.stdout.split("windows tests left alive", 1)[1]
        self.assertIn("    2  test_scratch.py", summary)


FIRST = '''import gc, unittest, weakref
import shared


class Big:
    pass


class Leaves(unittest.TestCase):
    def test_a_cycle_while_the_collector_is_off(self):
        gc.disable()                 # as a UI module's QApplication has it
        b = Big()
        b.me = b
        shared.ref = weakref.ref(b)
'''
SECOND = '''import gc, unittest
import shared


class Finds(unittest.TestCase):
    def test_the_last_modules_garbage_is_gone(self):
        gc.enable()
        self.assertIsNone(shared.ref())
'''


@unittest.skipUnless(HAVE, "needs PyQt6 and pytest")
class GivesBackWhatAModuleLeft(unittest.TestCase):
    def test_a_modules_cyclic_garbage_is_collected_when_it_ends(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy2(HERE / "conftest.py", tmp / "conftest.py")
        (tmp / "shared.py").write_text("ref = None\n")
        (tmp / "test_a.py").write_text(FIRST)
        (tmp / "test_b.py").write_text(SECOND)
        res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_a.py", "test_b.py"],
                             cwd=tmp, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("2 passed", res.stdout)


@unittest.skipUnless(HAVE, "needs pytest")
class RememberedTemplates(unittest.TestCase):
    """conftest.memoised, which the run puts around simsignals.voice: a
    remembered template is the one the simulator would have made, and
    the generator ends where it would have."""

    def setUp(self):
        import numpy as np
        from conftest import memoised
        from ohscore.devices import simsignals as sg
        self.np = np
        self.real = getattr(sg.voice, "__wrapped__", sg.voice)
        self.memo = memoised(self.real, 64 << 20)

    def test_a_repeat_is_the_same_samples_and_leaves_the_generator_where_the_real_one_does(self):
        np = self.np
        plain = np.random.default_rng(7)
        want = self.real(plain, 2.0, (0.0, 0.5))
        for _ in range(2):                                  # made, then remembered
            rng = np.random.default_rng(7)
            got = self.memo(rng, 2.0, (0.0, 0.5))
            np.testing.assert_array_equal(got, want)
            self.assertEqual(rng.bit_generator.state, plain.bit_generator.state)
            self.assertEqual(rng.random(), self._next(plain))     # what the simulator draws next
        self.assertEqual(len(self.memo.cache), 1)
        self.assertFalse(got.flags.writeable)

    def _next(self, g):
        """The next draw from a copy of `g`, leaving `g` alone."""
        c = self.np.random.Generator(type(g.bit_generator)())
        c.bit_generator.state = g.bit_generator.state
        return c.random()

    def test_another_generator_state_or_argument_is_another_template(self):
        np = self.np
        a = self.memo(np.random.default_rng(7), 1.0)
        b = self.memo(np.random.default_rng(8), 1.0)
        c = self.memo(np.random.default_rng(7), 1.5)
        self.assertEqual(len(self.memo.cache), 3)
        self.assertFalse(np.array_equal(a, b))
        self.assertNotEqual(len(a), len(c))


if __name__ == "__main__":
    unittest.main()
