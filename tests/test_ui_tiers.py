"""Window tiers and the minimum (docs/ui-overhaul-2026-10.md section 3, WP6).

The window picks Full, Compact or Tight from its size over the text scale
(ohscore/ui/layoutrules.py) and lays itself out for it: the header, the
rail (a drawer in Tight), the status strip. Below 1180 x 700 the layout
used to break (Mac FINDINGS 9: the dial lost a digit, "HSmodem" read
"iSmoden", the band activity's header and footer overlapped; Windows at
its 1195 x 737 minimum likewise), so these tests drive the real window on
the simulator at the sizes operators have and check what it draws: every
digit inside the readout, nothing squeezed under its least size, the
drawer opening and closing and never standing between Esc and a key-up.
Also the readout's editor (Mac FINDINGS 27), whose file this package owns.
Nothing here keys a real radio; the keyed cases key the simulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QObject, Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover - the engine's tests still run without PyQt6
    HAVE_QT = False

from helpers import make_radio


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class WindowCase(unittest.TestCase):
    APP = "nb"

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        if cls.APP == "radio":
            from ohsradio.ui import make_app
            cls.app = qt_app(make_app)
        else:
            cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui-radio.json")
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))
        self.wins = []

    def tearDown(self):
        from ohscore.ui import theme
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        theme.set_scale(1.0)
        from ohscore.ui import window as winmod
        winmod.BaseWindow.SCREEN_ROOM = None
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def window(self, size=(1920, 1080), scale=1.0, room=None, **over):
        """The app's window on the simulator at `size` and text `scale`.
        `room`: the screen's available size the window is told it has (the
        offscreen platform's screen is 800 x 800, smaller than any size
        here, so every case says what screen it means)."""
        from ohscore.ui.prefs import Prefs
        for k, v in (("licenceClass", "full"), ("callsign", "GM4BRI"), ("locator", "IO75RL")):
            over.setdefault(k, v)
        if self.APP == "radio":
            from ham_helpers import make_radio as make_ham
            from ohsradio import config
            from ohsradio.ui import build
            radio = make_ham(**{k: v for k, v in over.items() if k not in ("licenceClass",)})
        else:
            from ohsnb import config
            from ohsnb.ui import build
            radio = make_radio(self.tmp, audio_source=lambda n: __import__("numpy").full(n, 0.2, "float32"), **over)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        prefs["textScale"] = scale
        from ohscore.ui import window as winmod
        winmod.BaseWindow.SCREEN_ROOM = room or (2560, 1440)
        win, bridge = build(radio, prefs)
        win.resize(*size)
        win.show()
        self.wins.append((win, bridge))
        self.settle()
        return win, bridge, radio

    def settle(self, n=5):
        for _ in range(n):
            self.app.processEvents()
            time.sleep(0.01)

    def run_for(self, radio, until, timeout=20.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until():
                return True
        return False

    def key(self, win, k):
        win.activateWindow()
        QTest.keyClick(win, k)
        self.settle()


def squeezed(win, widths_only=False):
    """The visible widgets the layout gave less than they need: less than
    their minimum size where one is set, else their minimumSizeHint (Qt's
    own rule, qSmartMinSize), as "Class WxH < WxH". Heights are not judged
    inside a scroll area, which is there to scroll them."""
    from PyQt6.QtWidgets import QAbstractScrollArea, QSizePolicy, QWidget
    out = []
    for w in win.centralWidget().findChildren(QWidget):
        if not w.isVisible() or w.isWindow():
            continue
        p, inscroll = w.parentWidget(), False
        while p is not None and p is not win:
            if isinstance(p, QAbstractScrollArea):
                inscroll = True
                break
            p = p.parentWidget()
        hint, mn = w.minimumSizeHint(), w.minimumSize()
        pol = w.sizePolicy()
        mw = mn.width() or (hint.width() if pol.horizontalPolicy() != QSizePolicy.Policy.Ignored else 0)
        mh = mn.height() or (hint.height() if pol.verticalPolicy() != QSizePolicy.Policy.Ignored else 0)
        short_w = w.width() < mw - 1
        short_h = w.height() < mh - 1 and not inscroll and not widths_only
        if short_w or short_h:
            out.append(f"{type(w).__name__} {w.width()}x{w.height()} < {mw}x{mh}")
    return out


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class ReadoutEditor(WindowCase):
    def test_return_tunes_and_closes_the_editor(self):
        # Mac FINDINGS 27: F, digits, Return tuned the radio and left the
        # editor open, the new frequency selected in it, until Esc.
        win, bridge, radio = self.window()
        r = win.readout
        tuned = []
        r.tune.connect(tuned.append)
        r.open_editor()
        self.settle()
        self.assertTrue(r.edit.isVisible())
        r.edit.clear()
        QTest.keyClicks(r.edit, "10489.600")
        QTest.keyClick(r.edit, Qt.Key.Key_Return)
        self.settle()
        self.assertEqual(len(tuned), 1)
        self.assertAlmostEqual(tuned[0], 10489.600e6, delta=1)
        self.assertFalse(r.edit.isVisible())

    def test_a_frequency_it_cannot_read_keeps_the_editor_open(self):
        win, bridge, radio = self.window()
        r = win.readout
        tuned = []
        r.tune.connect(tuned.append)
        r.open_editor()
        r.edit.clear()
        QTest.keyClicks(r.edit, "banana")
        QTest.keyClick(r.edit, Qt.Key.Key_Enter)
        self.settle()
        self.assertEqual(tuned, [])
        self.assertTrue(r.edit.isVisible())
        QTest.keyClick(r.edit, Qt.Key.Key_Escape)
        self.settle()
        self.assertFalse(r.edit.isVisible())


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class Minimum(WindowCase):
    def test_the_least_window_is_1024_by_600_scaled_with_the_text_and_capped_to_the_screen(self):
        win, bridge, radio = self.window(room=(2560, 1440))
        self.assertEqual((win.minimumWidth(), win.minimumHeight()), (1024, 600))
        win.resize(1000, 640)                 # the Mac test's Accessibility resize
        self.settle()
        self.assertEqual((win.width(), win.height()), (1024, 640))
        win, bridge, radio = self.window(scale=1.3, room=(2560, 1440))
        self.assertEqual((win.minimumWidth(), win.minimumHeight()), (1332, 780))
        win, bridge, radio = self.window(scale=1.15, room=(2560, 1440))
        self.assertEqual((win.minimumWidth(), win.minimumHeight()), (1178, 690))
        # A 1366 x 768 laptop less its task bar: never taller than the screen.
        win, bridge, radio = self.window(scale=1.3, room=(1366, 728), size=(1366, 728))
        self.assertEqual((win.minimumWidth(), win.minimumHeight()), (1332, 728))

    def test_settings_offers_only_the_text_sizes_that_fit_the_screen(self):
        win, bridge, radio = self.window(room=(1366, 728), size=(1366, 728))
        d = win.settings_dialog()
        sizes = d.pref_widgets["textScale"]
        self.assertEqual(set(sizes.disabled), {"1.3"})
        self.assertIn("1332 x 780", sizes.disabled["1.3"])
        sizes._choose(2)                      # a click on 130 %: refused
        self.assertNotEqual(sizes.value, "1.3")
        d.deleteLater()
        win, bridge, radio = self.window(room=(1920, 1040))
        d = win.settings_dialog()
        self.assertEqual(d.pref_widgets["textScale"].disabled, {})
        d.deleteLater()


# The sizes operators have (plan section 3), the tier each is in, and the
# text scales: 130 % only where its least window (1332 x 780) fits, which
# is what Settings offers.
SIZES = (((1920, 1080), 1.0, "full"), ((1366, 768), 1.0, "compact"), ((1280, 720), 1.0, "compact"),
         ((1024, 600), 1.0, "tight"), ((1920, 1080), 1.3, "compact"), ((1332, 780), 1.3, "tight"))


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class Fits(WindowCase):
    """Mac FINDINGS 9 and the Windows test's finding 3, measured: at every
    size, nothing is squeezed, every digit of the dial is drawn whole, the
    status strip's items stand apart and the wide waterfall has rows."""

    MODES = ("usb",)

    def check(self, win, bridge, label, widths_only=False):
        self.assertEqual(squeezed(win, widths_only), [], label)
        r = win.readout
        r.grab()
        rect = r.rect()
        self.assertTrue(r.cells, label)
        for cell, _place in r.cells:
            self.assertGreaterEqual(cell.left(), rect.left() - 0.5, label)
            self.assertLessEqual(cell.right(), rect.right() + 0.5, label)
            self.assertLessEqual(cell.bottom(), rect.bottom() + 0.5, label)
            self.assertGreaterEqual(cell.top(), rect.top() - 0.5, label)
        win.status.grab()
        hits = sorted(win.status.hits)
        for (a0, a1, _k), (b0, _b1, _k2) in zip(hits, hits[1:]):
            self.assertLess(a1, b0, label)
        self.assertTrue(all(x1 < win.status.width() for _x0, x1, _k in hits), label)
        self.assertGreaterEqual(win.wide.r_wf.height(), 40, label)
        # The lower panel's tabs whole, and the Workspace button never "Wo…".
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import theme
        fm = QFontMetricsF(theme.font(12.5, theme.QFont.Weight.DemiBold))
        cell = (win.views.width() - 6) / len(win.views.options)
        for _v, lab in win.views.options:
            self.assertLessEqual(fm.horizontalAdvance(lab), cell - 8, (label, lab))
        self.assertGreaterEqual(win.ws_button.width(), win.ws_button.minimumWidth(), label)

    def test_every_size_and_text_scale(self):
        for mode in self.MODES:
            for size, scale, tier in SIZES:
                win, bridge, radio = self.window(size=size, scale=scale, mode=mode)
                label = f"{self.APP} {mode} {size[0]}x{size[1]} at {scale}"
                self.assertEqual(win.tier, tier, label)
                self.assertEqual((win.width(), win.height()), size, label)
                self.check(win, bridge, label)
                if tier == "tight":
                    win.open_drawer()
                    self.settle()
                    self.assertEqual(squeezed(win, widths_only=True), [], label + " drawer open")
                win.close()
                bridge.stop()
                self.wins.remove((win, bridge))

    def test_ft8_fits(self):
        # Heights too, now that the QSO card scrolls its Tx rows and has a
        # short form (ohscore/ui/panels/ft8.py; tests/test_ui_fit.py).
        for size, scale, tier in SIZES:
            win, bridge, radio = self.window(size=size, scale=scale, mode="ft8")
            self.check(win, bridge, f"{self.APP} ft8 {size} at {scale}")
            win.close()
            bridge.stop()
            self.wins.remove((win, bridge))


class RadioFits(Fits):
    APP = "radio"


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class Tiers(WindowCase):
    def test_each_tier_lays_the_header_and_rail_out_as_the_plan_says(self):
        win, bridge, radio = self.window(size=(1920, 1080), mode="usb")
        self.assertEqual(win.tier, "full")
        self.assertTrue(win.brand.words[0].isVisible())
        self.assertTrue(all(b.isVisible() for b in win.tool_buttons))
        self.assertFalse(win.more_btn.isVisible() or win.controls_btn.isVisible() or win.mode_btn.isVisible())
        self.assertIs(win.split_side.widget(1), win.rail_scroll)
        win.resize(1280, 720)
        self.settle()
        self.assertEqual(win.tier, "compact")
        self.assertFalse(win.brand.words[0].isVisible())
        self.assertTrue(win.brand.icon.isVisible() and win.sim_badge.isVisible())
        self.assertEqual(win.rxcard.form, "compact")
        win.resize(1024, 600)
        self.settle()
        self.assertEqual(win.tier, "tight")
        self.assertTrue(win.sim_badge.isVisible())                 # SIMULATOR in every tier
        self.assertEqual(win.readout.form, "tight")
        self.assertLessEqual(win.readout.height(), 60)            # the header is one line
        self.assertLessEqual(win.ptt.height(), 60)
        self.assertFalse(any(b.isVisible() for b in win.tool_buttons))
        self.assertTrue(win.more_btn.isVisible() and win.controls_btn.isVisible() and win.mode_btn.isVisible())
        self.assertTrue(win.drawer.isAncestorOf(win.rail))        # the rail is in the drawer
        self.assertFalse(win.rail_scroll.isVisible())
        self.assertFalse(win.drawer.isVisible())
        self.assertEqual(win.mode_btn.text().split()[0], "USB")
        texts = [e[0] for e in win.status.entries(bridge.st)]
        self.assertFalse([t for t in texts if "MS/s" in t or "CPU" in t or "txCorr" in t], texts)
        self.assertTrue(any(t.startswith("rxCorr") for t in texts), texts)
        win.resize(1920, 1080)
        self.settle()
        self.assertEqual(win.tier, "full")
        self.assertIs(win.rail_scroll.widget(), win.rail)         # back where it was
        self.assertTrue(win.rail_scroll.isVisible() and win.rail.isVisible())
        self.assertEqual(win.readout.form, "full")

    def test_the_mode_button_sets_the_mode_as_a_mode_button(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        win.choose_workspace("watch")
        win.mode_btn.picked.emit("ft8")
        self.settle()
        self.assertEqual(radio.state()["mode"], "ft8")
        self.assertEqual((win.ws.choice, win.workspace), ("auto", "digital"))   # a request to operate
        self.assertEqual(win.mode_btn.text().split()[0], "FT8")

    def test_the_mode_menu_offers_kgstv_and_the_recent_modes_as_the_card_does(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        win.mode_btn.picked.emit("ft8")
        self.settle()
        win.mode_btn.picked.emit("usb")
        self.settle()
        win.mode_btn.menu_.aboutToShow.emit()
        texts = [a.text() for a in win.mode_btn.menu_.actions()]
        self.assertTrue(any("KG-STV" in t for t in texts), texts)
        self.assertEqual(win.mode_btn.recent[:2], win.modegrid.recent[:2])
        self.assertIn("ft8", win.mode_btn.recent)
        overs = []
        win.over_button = overs.append              # what NB's MainWindow does with it
        win.modegrid.over_picked.disconnect()
        win.modegrid.over_picked.connect(lambda m: win.over_button(m))
        win.mode_btn.over_picked.emit("kgstv")
        self.assertEqual(overs, ["kgstv"])
        self.assertEqual(radio.state()["mode"], "usb")     # an over button is never a rail mode

    def test_the_more_menu_holds_the_four_header_buttons(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        acts = [a for a in win.more_menu.actions() if a.text()]
        self.assertEqual(len(acts), 4)
        next(a for a in acts if a.text().startswith("Logbook")).trigger()
        self.settle()
        self.assertEqual(win.views.value, "log")

    def test_a_tier_change_builds_nothing_and_is_quick(self):
        from PyQt6.QtCore import QAbstractAnimation
        win, bridge, radio = self.window(size=(1920, 1080), mode="usb")
        for size in ((1280, 720), (1024, 600), (1920, 1080)):          # every tier once
            win.resize(*size)
            self.settle(2)

        def objects():
            return sum(1 for o in win.findChildren(QObject) if not isinstance(o, QAbstractAnimation))
        n = objects()
        own = []
        for _ in range(3):
            for size in ((1280, 720), (1024, 600), (1920, 1080)):
                win.resize(*size)
                self.settle(2)
                own.append(win.tier_switch_ms)
                self.assertEqual(objects(), n, win.tier)              # nothing built, nothing lost
        self.assertLess(sorted(own)[len(own) // 2], 50.0, own)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class Drawer(WindowCase):
    def test_controls_opens_it_over_the_panel_and_esc_closes_it(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        QTest.mouseClick(win.controls_btn, Qt.MouseButton.LeftButton)
        self.settle()
        self.assertTrue(win.drawer.isVisible())
        g = win.drawer.geometry()
        root = win.centralWidget()
        self.assertEqual(g.right(), root.width() - 1)                 # over the right edge
        wide_bottom = win.wide.mapTo(root, win.wide.rect().bottomLeft()).y()
        self.assertGreater(g.top(), wide_bottom)                       # never over the wide scope
        tabs_bottom = win.controls_btn.mapTo(root, win.controls_btn.rect().bottomLeft()).y()
        self.assertGreater(g.top(), tabs_bottom)                       # nor over Controls itself
        self.assertTrue(win.modegrid.isVisible() and win.rxcard.isVisible())
        focus = QApplication_focus()
        self.assertFalse(focus is not None and win.drawer.isAncestorOf(focus))   # never takes the keys
        self.key(win, Qt.Key.Key_Escape)
        self.assertFalse(win.drawer.isVisible())
        QTest.mouseClick(win.controls_btn, Qt.MouseButton.LeftButton)
        QTest.mouseClick(win.controls_btn, Qt.MouseButton.LeftButton)
        self.settle()
        self.assertFalse(win.drawer.isVisible())

    def test_esc_while_keyed_unkeys_and_leaves_it_open(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        self.assertTrue(self.run_for(radio, until=lambda: radio.state()["rxLock"] == "locked"))
        self.assertFalse(win.drawer.isVisible())
        bridge.ptt(True)
        self.assertTrue(self.run_for(radio, until=lambda: radio.state()["keyed"], timeout=5))
        # On the air from the TX tile or Space: the Transmit card comes
        # out (plan section 7, rule 3) and Controls reads red - once the
        # state feed has carried "keyed" to the window.
        self.assertTrue(self.run_for(radio, until=win.drawer.isVisible, timeout=5))
        self.assertTrue(win.txcard.isVisibleTo(win.rail))
        self.assertEqual(win.controls_btn.kind, "danger")
        self.key(win, Qt.Key.Key_Escape)
        self.assertTrue(self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=5))
        self.assertTrue(win.drawer.isVisible())                         # Esc stopped the air, nothing else
        self.settle()
        win._sync_ptt()
        self.assertEqual(win.controls_btn.kind, "ghost")
        self.key(win, Qt.Key.Key_Escape)
        self.assertFalse(win.drawer.isVisible())

    def test_a_transmit_warning_opens_it(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        self.assertFalse(win.drawer.isVisible())
        w = {"key": "rig-aim", "level": "warn", "text": "The IC-9700 is aimed where NB would not transmit"}
        bridge.st["txWarning"] = w
        win.on_state({"txWarning": w})
        self.assertTrue(win.drawer.isVisible())
        self.assertTrue(win.txcard.isVisibleTo(win.rail))
        win.close_drawer()
        win.on_state({"txWarning": w})                     # the same warning: not again
        self.assertFalse(win.drawer.isVisible())

    def test_a_larger_window_puts_the_rail_back_and_closes_it(self):
        win, bridge, radio = self.window(size=(1024, 600), mode="usb")
        win.open_drawer()
        win.resize(1366, 768)
        self.settle()
        self.assertFalse(win.drawer.isVisible())
        self.assertIs(win.rail_scroll.widget(), win.rail)
        self.assertTrue(win.rail_scroll.isVisible())


def QApplication_focus():
    from PyQt6.QtWidgets import QApplication
    return QApplication.focusWidget()


if __name__ == "__main__":
    unittest.main()
