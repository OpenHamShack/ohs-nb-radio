"""The smallest window in a longer language (UI overhaul WP9 acceptance,
docs/ui-overhaul-2026-10.md section 8): with SHACK_LOCALE=en-XA, the
pseudo-language every string survives 40 % longer and bracketed in
(tools/i18n.py), each app's window at 1024 x 600 in both themes draws no
text cut off. Measured on the real window on the simulator, as geometry:
nothing given less than it needs (test_ui_tiers.squeezed), and every
label's and button's text inside what it was given, the drawer open as
well as shut. Nothing here keys anything."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_ui_tiers import HAVE_QT, WindowCase, squeezed

ROOT = Path(__file__).resolve().parent.parent


def i18n_tool():
    spec = importlib.util.spec_from_file_location("ohs_i18n_tool", ROOT / "tools" / "i18n.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cut_text(win) -> list[str]:
    """Visible labels and buttons whose one-line text is wider than the
    room they were given, as "Class 'text' needs N > M". Word-wrapped and
    rich-text labels are left to squeezed(): they grow downwards."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractButton, QLabel
    out = []
    for w in win.findChildren(QLabel) + win.findChildren(QAbstractButton):
        if not w.isVisible() or not w.text() or not w.window().isVisible():
            continue
        if isinstance(w, QLabel):
            if w.wordWrap() or Qt.mightBeRichText(w.text()) or w.textFormat() == Qt.TextFormat.RichText:
                continue
            room = w.contentsRect().width() - 2 * w.margin() - max(0, w.indent())
            need = max(w.fontMetrics().horizontalAdvance(line) for line in w.text().replace("&", "").split("\n"))
        else:
            room = w.width()
            need = w.sizeHint().width()
        if need > room + 1:
            out.append(f"{type(w).__name__} {w.text()!r} needs {need} > {room}")
    return out


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class PseudoFits(WindowCase):
    APP = "nb"
    PKG = "ohsnb"
    MODES = ("usb", "ft8", "rtty")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from ohscore import i18n
        cls.cat = tempfile.mkdtemp()
        i18n_tool().write_pseudo(Path(cls.cat))
        i18n.install(locale="en-XA", catalogs=[(Path(cls.cat), "ohscore"), (Path(cls.cat), cls.PKG)])

    @classmethod
    def tearDownClass(cls):
        # Back to what every other UI test expects: the app's own catalogs,
        # in the desktop's language.
        if cls.APP == "radio":
            from ohsradio.ui import make_app
        else:
            from ohsnb.ui import make_app
        make_app(["test"])
        shutil.rmtree(cls.cat, ignore_errors=True)
        super().tearDownClass()

    def test_nothing_cut_off_at_1024_by_600_in_both_themes(self):
        for mode in self.MODES:
            for theme_name in ("dark", "light"):
                label = f"{self.APP} {mode} {theme_name} en-XA 1024x600"
                win, bridge, radio = self.window(size=(1024, 600), room=(1024, 600), mode=mode)
                if theme_name != "dark":
                    win.set_theme(theme_name)
                    self.settle()
                with self.subTest(label):
                    self.assertTrue(win.windowTitle().startswith("["), win.windowTitle())   # en-XA is on
                    self.assertEqual(win.tier, "tight")
                    self.assertEqual(squeezed(win, widths_only=True), [])
                    self.assertEqual(cut_text(win), [])
                win.open_drawer()
                self.settle()
                with self.subTest(label + " drawer open"):
                    self.assertEqual(squeezed(win, widths_only=True), [])
                    self.assertEqual(cut_text(win), [])
                win.close()
                bridge.stop()
                self.wins.remove((win, bridge))


class RadioPseudoFits(PseudoFits):
    APP = "radio"
    PKG = "ohsradio"


if __name__ == "__main__":
    unittest.main()
