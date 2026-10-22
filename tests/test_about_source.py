"""The About box says where the program's source is: each app's own
section on the source site, which lists every release's own tarball
(ohsdigi included) and the third-party source. On Windows the installed
program is bytecode and compiled ohsdigi, so this is where a user is sure
to find the directions the GPL requires. Opened on Qt's offscreen
platform and read as a user would see it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class AboutNamesTheSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def about(self, module: str):
        if module == "nb":
            from ohsnb.ui.welcome import About
        else:
            from ohsradio.ui.welcome import About
        dlg = About()
        self.addCleanup(dlg.deleteLater)
        return dlg

    def check(self, dlg, name: str, anchor: str) -> None:
        from PyQt6.QtCore import Qt
        label = dlg.source
        self.assertEqual(label.textFormat(), Qt.TextFormat.RichText)
        self.assertTrue(label.openExternalLinks(), "the link must open in the browser when clicked")
        self.assertIn(f'href="https://openhamshack.com/source/#{anchor}"', label.text())
        self.assertIn("GNU GPL", label.text())
        self.assertIn(name, label.text())
        self.assertIn("ohsdigi", label.text())
        # It fits: the fixed-size box was made taller for it, so the line
        # must not be squeezed out of sight.
        dlg.show()
        self.assertTrue(label.isVisible())
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))

    def test_nb_points_at_nbs_section(self):
        self.check(self.about("nb"), "OpenHamShack QO-100 NB", "openhamshack-nb")

    def test_ham_points_at_hams_section(self):
        self.check(self.about("ham"), "OpenHamShack Radio", "openhamshack-radio")

    def test_each_names_itself_and_says_once_what_it_was_called(self):
        # The OpenHamShack rename (09/10/2026): the About box is the one
        # place the old name appears, so someone who installed "OpenHamShack NB"
        # can tell this is the same program. The section anchor is the
        # package name, which followed on 17/10/2026: releases from then on
        # are filed on the source site under it, the older ones stay under
        # openhamshack-nb, where the copies that link there look.
        for module, new, old in (("nb", "OpenHamShack QO-100 NB", "OpenHamShack NB"),
                                 ("ham", "OpenHamShack Radio", "OpenHamShack HAM")):
            with self.subTest(module):
                dlg = self.about(module)
                dlg.show()
                self.assertEqual(dlg.windowTitle(), f"About {new}")
                self.assertTrue(dlg.former.isVisible())
                self.assertEqual(dlg.former.text(), f"Formerly {old}")
                self.assertNotIn(old, dlg.source.text())


if __name__ == "__main__":
    unittest.main()
