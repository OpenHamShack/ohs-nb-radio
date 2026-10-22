"""tests/conftest.py, the pytest hook that destroys every window a test
left alive: run for real, under pytest in a child process, against a
scratch tree of three tests - one that keeps a window alive the way the
UI tests do (closed, and still referenced), one that opens nothing, and
one that checks what the class made in setUpClass is still whole."""
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


if __name__ == "__main__":
    unittest.main()
