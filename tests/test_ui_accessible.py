"""Screen readers find a name on NB's painted controls (ohscore/ui/controls.py
FocusVisible.accessible_text): Narrator read nothing on Windows on the
mode buttons, TX and lock tiles, the tab row, toggles and icon buttons
(Windows test 17/10/2026, finding 5). Asked here as a screen reader asks,
through Qt's accessibility interface - the text UI Automation, VoiceOver
and Orca are given - in NB's real window on the simulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio


def spoken(w) -> str:
    """The name a screen reader is given for widget `w`: through Qt's
    accessibility interface where this PyQt6 has it, else the widget's
    accessibleName, which is what that interface gives for a plain widget
    (Debian's PyQt6 is built without QAccessible)."""
    try:
        from PyQt6.QtGui import QAccessible
    except ImportError:
        return w.accessibleName()
    iface = QAccessible.queryAccessibleInterface(w)
    return iface.text(QAccessible.Text.Name) if iface is not None else ""


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))
        radio = make_radio(self.tmp, mode="usb")
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        self.win, self.bridge = build(radio, prefs)
        self.win.resize(1600, 960)
        self.win.show()
        self.settle()

    def tearDown(self):
        self.win.close()
        self.bridge.stop()
        self.app.processEvents()
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                           for e in self.errors))

    def settle(self, s=0.4):
        end = time.monotonic() + s
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_every_control_shown_has_a_name(self):
        from ohscore.ui.controls import FocusVisible
        from ohscore.ui.rail import ModeCell
        shown = [w for w in self.win.findChildren(FocusVisible) if w.isVisible()]
        self.assertGreater(len(shown), 20)
        # The mode buttons are named by the UI plan's WP0/WP2 (ohscore/ui/rail.py,
        # moving to modegrid.py); everything else is named here.
        nameless = [type(w).__name__ for w in shown if not spoken(w) and not isinstance(w, ModeCell)]
        self.assertEqual(nameless, [])

    def test_names_say_the_state_and_follow_it(self):
        from ohscore.ui.controls import Toggle
        from ohscore.ui.status import PttButton
        from ohsnb.ui.status import LockBadge
        win = self.win
        self.assertTrue(spoken(win.views).startswith("Operate, 1 of "), spoken(win.views))
        win.show_view("log")
        self.settle(0.3)
        self.assertTrue(spoken(win.views).startswith("Logbook, 2 of "), spoken(win.views))
        ptt = win.findChild(PttButton)
        self.assertTrue(spoken(ptt).startswith("TX: "), spoken(ptt))
        badges = [spoken(b) for b in win.findChildren(LockBadge)]
        self.assertTrue(any(b.startswith("TX · own signal: ") for b in badges), badges)
        toggles = [t for t in win.findChildren(Toggle) if t.isVisible()]
        self.assertTrue(toggles)
        t = toggles[0]
        before = spoken(t)
        self.assertEqual(before, f"{t.label}: {'on' if t.on else 'off'}")
        t.set_on(not t.on)
        self.settle(0.3)
        self.assertEqual(spoken(t), f"{t.label}: {'on' if t.on else 'off'}")
        self.assertNotEqual(spoken(t), before)
        t.set_on(not t.on)


if __name__ == "__main__":
    unittest.main()
