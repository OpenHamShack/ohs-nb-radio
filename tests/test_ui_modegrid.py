import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The Mode card, the mode menus, the "?" sheet and the pad's MODE and
HALT keys (docs/ui-overhaul-2026-10.md section 5.1, work package 2), in
the real windows of both apps against a real Radio on the simulator. They
press the buttons, type into the menus and lay the sheet out at every text
size, and check what the engine was told and what fits; nothing keys
outside the simulator."""
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio, sim_seconds

ROOT = Path(__file__).resolve().parent.parent
ELSEWHERE = 10_489_700_000.0       # an SSB frequency: where the operator happens to be
MIXED = 10_489_900_000.0           # mixed modes and contests, where a picture may go
SCALES = (1.0, 1.15, 1.3)


def pseudo(text: str) -> str:
    """The en-XA pseudo-language's form of `text` (tools/i18n.py): accented,
    40 % longer, bracketed - what any label must survive."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ohs_i18n_tool", ROOT / "tools" / "i18n.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pseudo_text(text)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
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
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def prefs(self, scale=1.0, **keep):
        from ohscore.ui.prefs import Prefs
        if self.APP == "radio":
            from ohsradio import config
        else:
            from ohsnb import config
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        prefs["textScale"] = scale
        for k, v in keep.items():
            prefs[k] = v
        return prefs

    def window(self, size=(1920, 1080), scale=1.0, prefs=None, **over):
        if self.APP == "radio":
            from ham_helpers import make_radio as make_ham
            from ohsradio.ui import build
            radio = make_ham(**over)
        else:
            from ohsnb.ui import build
            for k, v in (("licenceClass", "full"), ("callsign", "GM4BRI"), ("locator", "IO75RL")):
                over.setdefault(k, v)
            radio = make_radio(self.tmp, audio_source=lambda n: np.full(n, 0.2, "float32"), **over)
        win, bridge = build(radio, prefs or self.prefs(scale))
        win.resize(*size)
        win.show()
        self.wins.append((win, bridge))
        self.settle()
        return win, bridge, radio

    def settle(self, n=6):
        for _ in range(n):
            self.app.processEvents()
            time.sleep(0.01)

    def pump(self, until, timeout=30.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.005)
            if until():
                return True
        return False

    def click(self, w, x=None):
        """A left click on `w`, in its middle or at `x`."""
        pos = QPoint(w.width() // 2 if x is None else int(x), w.height() // 2)
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        self.settle(3)

    def ctrl_e(self, win):
        win.activateWindow()
        win.wide.setFocus()
        QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        self.settle(3)
        menu = win.modegrid._last_menu
        self.assertIsNotNone(menu, "Ctrl+E opened no menu")
        self.assertTrue(menu.isVisible())
        return menu

    def type_into(self, menu, text, enter=True):
        for ch in text:
            QTest.keyClick(menu, ch)
        if enter:
            QTest.keyClick(menu, Qt.Key.Key_Return)
        self.settle(3)

    @staticmethod
    def menu_modes(menu):
        return [a.data() for a in menu.actions() if a.data()]

    @staticmethod
    def menu_text(menu):
        return [a.text() for a in menu.actions()]

    def labels_fit(self, win):
        """Every mode button showing on the rail has room for its label in
        the font it is drawn in, and is inside the rail's view across: the
        one clipped at both ends on the Mac was HSmodem, selected (bold)."""
        from PyQt6.QtCore import QRectF
        from ohscore.ui.modegrid import GroupCell, ModeCell, label_width
        cells = [c for c in win.modegrid.findChildren(ModeCell) if c.isVisibleTo(win)]
        self.assertTrue(cells)
        # The rail's scroll area, or the Tight tier's drawer's (WP6).
        holder = win.drawer.scroll if win.drawer.isAncestorOf(win.rail) else win.rail_scroll
        view = holder.viewport()
        for c in cells:
            room = c.text_rect(QRectF(c.rect())).width()
            need = (max(label_width(m) for m in c.modes) if isinstance(c, GroupCell) else label_width(c.mode))
            self.assertGreaterEqual(room, math.ceil(need), (c.mode, room, need, c.width()))
            left = c.mapTo(view, QPoint(0, 0)).x()
            self.assertGreaterEqual(left, 0, c.mode)
            self.assertLessEqual(left + c.width(), view.width(), (c.mode, left, c.width(), view.width()))
        return cells


class ModeCardNB(WindowCase):
    def test_full_form_has_three_headed_groups_each_mode_once_in_a_fixed_order(self):
        from ohscore import modegroups
        from ohsnb import state
        win, bridge, radio = self.window(mode="ft8")
        g = win.modegrid
        self.assertEqual(win.workspace, "digital")
        self.assertEqual(g.form, "full")
        self.assertTrue(g.full.isVisible())
        self.assertFalse(g.compact.isVisible())
        got = {grp: [c.mode for c in b.cells] for grp, b in g.blocks.items()}
        self.assertEqual(got, {"voice": ["usb", "lsb", "cw", "am", "freedv"],
                               "digital": ["ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty"],
                               "pictures": ["sstv", "kgstv", "hsmodem"]})
        shown = [m for ms in got.values() for m in ms]
        self.assertEqual(sorted(shown), sorted(state.MODES + ["kgstv"]))     # each once
        self.assertEqual([g.headings[k].text() for k in got], ["Voice", "Digital", "Pictures & data"])
        # The current group's heading is the accent colour, the others not.
        from ohscore.ui import theme
        self.assertIn(theme.t()["accent"], g.headings["digital"].styleSheet())
        self.assertNotIn(theme.t()["accent"], g.headings["voice"].styleSheet())
        # Positions do not follow use: picking modes leaves every button
        # where it was.
        # where it was: the same group, row and column (the rail's width
        # may change with the workspace, the pixels with it).
        def places():
            out = {}
            for grp, b in g.blocks.items():
                rows = sorted({c.y() for c in b.cells})
                for c in b.cells:
                    row = [x.x() for x in b.cells if x.y() == c.y()]
                    out[c.mode] = (grp, rows.index(c.y()), sorted(row).index(c.x()))
            return out
        where = places()
        for m in ("rtty", "usb", "hsmodem", "q65"):
            self.click(g.cells[m])
            self.assertEqual(radio.state()["mode"], m)
            self.assertEqual(places(), where, m)
        self.assertIn(theme.t()["accent"], g.headings["digital"].styleSheet())
        self.assertEqual(modegroups.group_of("q65"), "digital")

    def test_compact_form_shows_each_groups_last_mode_and_its_menu_lists_the_group(self):
        win, bridge, radio = self.window(mode="usb")
        g = win.modegrid
        for m in ("psk63", "freedv", "ft4", "usb"):
            g.cells[m].picked.emit(m)
            self.settle(2)
        self.assertEqual(radio.state()["mode"], "usb")
        win.choose_workspace("watch")
        self.settle()
        self.assertEqual(g.form, "compact")
        self.assertTrue(g.compact.isVisible())
        self.assertFalse(g.full.isVisible())
        gc = g.group_cells
        self.assertEqual([gc[k].mode for k in ("voice", "digital", "pictures")], ["usb", "ft4", "sstv"])
        # A click on the button picks the mode it shows ...
        self.click(gc["digital"])
        self.assertEqual(radio.state()["mode"], "ft4")
        # ... the arrow opens the group's menu, which lists the group only.
        self.click(gc["voice"], x=gc["voice"].width() - gc["voice"].arrow_w() / 2)
        menu = g._last_menu
        self.assertTrue(menu.isVisible())
        self.assertEqual(self.menu_modes(menu), ["usb", "lsb", "cw", "am", "freedv"])
        self.assertEqual(self.menu_text(menu)[0], "Voice")
        [lsb] = [a for a in menu.actions() if a.data() == "lsb"]
        lsb.trigger()
        self.settle(3)
        menu.close()
        self.assertEqual(radio.state()["mode"], "lsb")
        self.assertEqual(gc["voice"].mode, "lsb")
        # The slim rail: the compact card is narrower than the full grid.
        self.assertLess(win.rail_scroll.minimumWidth(), win.GRID_RAIL)
        self.assertEqual(gc["voice"].accessibleName(), "Voice: LSB")

    def test_recent_modes_are_kept_in_the_preferences_and_survive_a_rebuild(self):
        win, bridge, radio = self.window(mode="usb")
        for m in ("q65", "psk125", "cw"):
            win.set_mode(m)
            self.settle(2)
        self.assertEqual(win.prefs["modeRecent"][:4], ["cw", "psk125", "q65", "usb"])
        win.set_theme("light")
        self.settle()
        self.assertEqual(win.modegrid.recent[:4], ["cw", "psk125", "q65", "usb"])
        self.assertEqual(win.modegrid.group_cells["digital"].mode, "psk125")
        self.assertIn("kgstv", win.modegrid.cells)          # the KG-STV button came back too
        # A new window over the same preferences file.
        win.close()
        bridge.stop()
        self.wins.remove((win, bridge))
        win2, _b, _r = self.window(mode="usb", prefs=self.prefs())
        self.assertEqual(win2.modegrid.shown_for("digital"), "psk125")

    def test_ctrl_e_lists_recent_modes_first_and_types_ahead(self):
        win, bridge, radio = self.window(mode="usb")
        for m in ("ft8", "psk31", "usb"):
            win.set_mode(m)
            self.settle(2)
        menu = self.ctrl_e(win)
        text = self.menu_text(menu)
        self.assertEqual(text[0], "Recent")
        self.assertEqual(self.menu_modes(menu)[:2], ["psk31", "ft8"])        # the current one is not "recent"
        self.assertEqual([t for t in text if t in ("Voice", "Digital", "Pictures & data")],
                         ["Voice", "Digital", "Pictures & data"])
        self.type_into(menu, "q")
        self.assertEqual(radio.state()["mode"], "q65")
        menu = self.ctrl_e(win)
        self.type_into(menu, "psk1", enter=False)
        self.assertEqual(menu.activeAction().data(), "psk125")
        QTest.keyClick(menu, Qt.Key.Key_Return)
        self.settle(3)
        self.assertEqual(radio.state()["mode"], "psk125")
        menu = self.ctrl_e(win)
        self.type_into(menu, "h")
        self.assertEqual(radio.state()["mode"], "hsmodem")

    def test_every_mode_is_reachable_from_the_keyboard(self):
        from ohscore import modegroups
        from ohsnb import state
        win, bridge, radio = self.window(mode="usb")
        keyed = set(win.MODE_KEYS.values())
        for m in state.MODES:
            if m in keyed:
                continue
            menu = self.ctrl_e(win)
            self.type_into(menu, modegroups.label(m).lower())
            self.assertEqual(radio.state()["mode"], m)
        self.assertGreaterEqual(set(state.MODES) - keyed, {"q65", "js8", "psk63", "psk125", "hsmodem"})

    def test_a_mode_from_the_menu_is_a_request_to_operate(self):
        # Decision 2: a mode chosen by hand leaves a pinned Watch for its
        # workspace, as a button does.
        win, bridge, radio = self.window(mode="usb")
        win.choose_workspace("watch")
        self.settle()
        menu = self.ctrl_e(win)
        self.type_into(menu, "js")
        self.assertEqual(radio.state()["mode"], "js8")
        self.assertEqual(win.workspace, "digital")
        self.assertEqual(win.views.value, "mode")

    def test_the_kgstv_button_shows_its_page_and_tunes_to_kgstv(self):
        from ohsnb.kgstvrx import DIAL
        win, bridge, radio = self.window(mode="ft8", vfo=ELSEWHERE)
        win.show_view("log")
        self.click(win.modegrid.cells["kgstv"])
        self.assertEqual(win.views.value, "mmb")
        self.assertEqual(win.mmb_view.pages.value, "kgstv")
        self.assertEqual(radio.state()["mode"], "usb")
        self.assertEqual(radio.state()["vfo"], DIAL)
        self.assertEqual(win.modegrid.shown_for("pictures"), "kgstv")
        self.assertFalse(radio.state()["keyed"])

    def test_the_kgstv_button_never_retunes_under_a_picture_going_out(self):
        from ohscore.modes.sstv import _write_png
        pic = os.path.join(self.tmp, "p.png")
        _write_png(pic, np.full((240, 320, 3), 90, np.uint8))
        win, bridge, radio = self.window(mode="cw", vfo=MIXED, mmbDecode=False, midTextDecode=False,
                                         kgstvDecode=False, simUlErrorHz=0.0)
        self.pump(lambda: radio.running, 10)
        dlg = win.mmb_view.send_picture(pic)
        self.settle(2)
        dlg.freq_here.setChecked(True)          # sent where the radio is, in CW
        dlg.send()
        self.assertTrue(radio.state()["keyed"], dlg.status.text())
        win.show_view("log")
        self.click(win.modegrid.cells["kgstv"])
        self.assertEqual(win.views.value, "mmb")
        self.assertEqual(win.mmb_view.pages.value, "kgstv")
        self.pump(lambda: False, 0.5)
        self.assertTrue(radio.state()["keyed"], (radio.state()["mode"], radio.state()["vfo"],
                                                 [t.text for t in win.toasts.toasts]))    # the picture keeps going
        self.assertEqual(radio.state()["mode"], "cw")
        self.assertEqual(radio.state()["vfo"], MIXED)
        win.unkey_all()
        self.assertTrue(self.pump(lambda: not radio.state()["keyed"], 5))

    def test_no_mode_label_is_clipped_at_any_text_size_in_either_form(self):
        # Whatever form the workspace and the window's size choose (Digital
        # gives the full card at 1920 x 1080; Watch the compact one), and
        # with HSmodem selected, the bold label that was clipped.
        forms = set()
        for scale in SCALES:
            for size in ((1920, 1080), (1366, 768)):
                with self.subTest(scale=scale, size=size):
                    win, bridge, radio = self.window(size=size, scale=scale, mode="hsmodem")
                    if win.tier == "tight":
                        win.open_drawer()       # the rail is in the Tight tier's drawer (WP6)
                        self.settle()
                    forms.add(win.modegrid.form)
                    self.labels_fit(win)
                    win.choose_workspace("watch")
                    self.settle()
                    self.assertEqual(win.modegrid.form, "compact")
                    self.labels_fit(win)
                    win.close()
                    bridge.stop()
                    self.wins.remove((win, bridge))
        self.assertIn("full", forms)


class ModeCardRadio(WindowCase):
    APP = "radio"

    def test_radio_has_its_own_modes_grouped_and_no_kgstv(self):
        from ohsradio import state
        win, bridge, radio = self.window(mode="usb")
        got = {grp: [c.mode for c in b.cells] for grp, b in win.modegrid.blocks.items()}
        self.assertEqual(got, {"voice": ["usb", "lsb", "cw", "am", "fm", "freedv"],
                               "digital": ["ft8", "ft4", "js8", "psk31", "psk63", "psk125", "rtty"],
                               "pictures": ["sstv"]})
        self.assertEqual(sorted(m for ms in got.values() for m in ms), sorted(state.MODES))
        self.assertNotIn("kgstv", win.modegrid.cells)
        for m in state.MODES:
            if m in win.MODE_KEYS.values():
                continue
            menu = self.ctrl_e(win)
            self.assertNotIn("q65", self.menu_modes(menu))
            from ohscore import modegroups
            self.type_into(menu, modegroups.label(m).lower())
            self.assertEqual(radio.state()["mode"], m)

    def test_no_mode_label_is_clipped_at_any_text_size(self):
        for scale in SCALES:
            with self.subTest(scale=scale):
                win, bridge, radio = self.window(size=(1366, 768), scale=scale, mode="psk125")
                if win.tier == "tight":
                    win.open_drawer()           # the rail is in the Tight tier's drawer (WP6)
                    self.settle()
                self.labels_fit(win)
                win.choose_workspace("watch")
                self.settle()
                self.labels_fit(win)
                win.close()
                bridge.stop()
                self.wins.remove((win, bridge))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class ShortcutSheet(unittest.TestCase):
    """The "?" sheet laid out at every text size, in both apps, in English
    and the pseudo-language, from the smallest window to a large one: every
    piece of text inside its box, every box inside the card, the card
    inside the window, and no two boxes overlapping (FINDINGS 13)."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def tearDown(self):
        from ohscore.ui import theme
        theme.set_scale(1.0)

    def check(self, sections, size, scale):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QFontMetricsF
        from ohscore.ui import shortcutsheet, theme
        theme.set_scale(scale)
        p = shortcutsheet.plan(sections, *size)
        self.assertTrue(p.fits, (size, scale, p.factor, p.columns))
        win = QRectF(0, 0, *size)
        self.assertTrue(win.contains(p.card), (p.card, size))
        for it in p.items:
            self.assertTrue(p.card.contains(it.rect), (it.kind, it.text, it.rect, p.card))
            fm = QFontMetricsF(it.font)
            if it.kind == "what":
                br = fm.boundingRect(QRectF(0, 0, it.rect.width(), 10_000), shortcutsheet.WRAP, it.text)
                self.assertLessEqual(br.width(), it.rect.width() + 0.5, it.text)
                self.assertLessEqual(br.height(), it.rect.height() + 0.5, it.text)
            else:
                self.assertLessEqual(fm.horizontalAdvance(it.text), it.rect.width() + 0.5, (it.kind, it.text))
        boxes = [it.rect for it in p.items if it.kind in ("key", "what", "heading")]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a.intersects(b), (a, b))
        return p

    @staticmethod
    def smallest(scale):
        """The overlay's room in the least window at `scale` (section 3:
        1024 x 600 times the text scale), less the menu bar."""
        return [(round(1024 * scale), round(570 * scale))]

    def sections(self):
        from ohsradio.ui.mainwindow import SHORTCUTS as RADIO
        from ohsnb.ui.chrome import SHORTCUTS as NB
        return {"nb": NB, "radio": RADIO}

    def test_the_sheet_fits_at_every_text_size_in_both_apps(self):
        for app, sections in self.sections().items():
            for scale in SCALES:
                for size in (*self.smallest(scale), (1366, 768), (1920, 1080)):
                    if size[1] < self.smallest(scale)[0][1]:
                        continue                # below this text size's least window
                    with self.subTest(app=app, size=size, scale=scale):
                        p = self.check(sections, size, scale)
                        if size == (1920, 1080) and scale == 1.0:
                            self.assertEqual(p.factor, 1.0)      # full size where there is room

    def test_the_sheet_fits_in_a_longer_language(self):
        from ohscore.ui import shortcutsheet
        with mock.patch.object(shortcutsheet, "translated", pseudo):
            for app, sections in self.sections().items():
                for scale in SCALES:
                    with self.subTest(app=app, scale=scale):
                        self.check(sections, self.smallest(scale)[0], scale)
                        self.check(sections, (1920, 1080), scale)

    def test_the_sheet_lists_the_mode_menu_and_the_workspace_keys(self):
        for app, sections in self.sections().items():
            rows = dict(r for _t, rs in sections for r in rs)
            with self.subTest(app=app):
                self.assertIn("Mode menu", rows["Ctrl + E"])
                self.assertIn("workspace", rows["W"].lower())
                self.assertIn("Auto", rows["Shift + W"])
                self.assertEqual(rows["Ctrl + J"], "Operate")
                self.assertNotIn("Mode panel", rows.values())


class PadModeOrder(unittest.TestCase):
    def test_mode_steps_in_group_order_in_both_apps(self):
        from ohscore.padactions import mode_order
        from ohsradio import state as ham
        from ohsnb import state as nb
        self.assertEqual(mode_order(nb.MODES), ["usb", "lsb", "cw", "am", "freedv", "ft8", "ft4", "q65", "js8",
                                                "psk31", "psk63", "psk125", "rtty", "sstv", "hsmodem"])
        self.assertEqual(mode_order(ham.MODES), ["usb", "lsb", "cw", "am", "fm", "freedv", "ft8", "ft4", "js8",
                                                 "psk31", "psk63", "psk125", "rtty", "sstv"])

    def test_the_mode_key_cycles_the_radio_through_the_groups(self):
        from ohscore.padactions import mode_order
        from ohsnb import state as nb
        with tempfile.TemporaryDirectory() as d:
            r = make_radio(d, mode="usb")
            pa = r.pad_actions()
            seen = []
            for _ in range(len(nb.MODES) + 1):
                pa.perform("mode:next")
                seen.append(r.state()["mode"])
            want = mode_order(nb.MODES)
            self.assertEqual(seen, want[1:] + want[:2])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class DesktopPadKeys(WindowCase):
    """The window's PadLink with a fake AKP03E: the MODE key is a request
    to operate, and HALT is dimmed while transmit waits for setting up but
    still halts."""

    def link(self, win, radio):
        from ohscore import shacklibs
        shacklibs.pad()
        from shack_pad.drivers.ajazz import AKP03E
        from shack_pad.fake import FakeHid
        from ohscore.ui.padlink import PadLink
        fakes = []

        def open_device():
            f = FakeHid()
            fakes.append(f)
            return AKP03E(f)
        link = PadLink(win, radio, "qo100nb", "QO-100 NB", ROOT / "ohsnb", prefs=win.prefs, open_device=open_device)
        self.addCleanup(link.close)
        self.assertTrue(self.pump(lambda: fakes and link.pad.serving(), 5))
        return link, fakes

    def press(self, fakes, code):
        from shack_pad.fake import akp03e_report
        fakes[-1].push(akp03e_report(code, 1))
        fakes[-1].push(akp03e_report(code, 0))

    def test_the_mode_key_brings_the_modes_workspace_back_from_a_pinned_one(self):
        win, bridge, radio = self.window(mode="usb")
        win.choose_workspace("watch")
        self.settle()
        self.assertEqual(win.workspace, "watch")
        link, fakes = self.link(win, radio)
        self.press(fakes, 0x04)                  # K4: MODE
        self.assertTrue(self.pump(lambda: radio.state()["mode"] == "lsb", 5), radio.state()["mode"])
        self.assertTrue(self.pump(lambda: win.workspace == "voice", 5), win.workspace)
        self.assertEqual(win.ws.choice, "auto")
        self.assertEqual(win.views.value, "mode")

    def test_halt_is_dimmed_until_transmit_is_set_up_and_still_halts(self):
        from helpers import RadiatingSim
        from ohsnb.devices.sim import SimDevice
        win, bridge, radio = self.window(mode="usb",
                                         device=type("Radio", (RadiatingSim, SimDevice), {}))
        bridge.licence_ok = False
        self.pump(lambda: radio.state()["running"], 10)
        link, fakes = self.link(win, radio)
        self.assertEqual(link._faces()["faces"]["halt"]["tone"], "disabled")
        with mock.patch.object(radio, "halt", wraps=radio.halt) as halt:
            self.press(fakes, 0x06)              # K6: HALT
            self.assertTrue(self.pump(lambda: halt.called, 5))
        # On the air (here: the engine says keyed, as an IC-9700 keyed at
        # its own microphone would make it) HALT is never dimmed.
        real = radio.state

        def keyed_state():
            return {**real(), "keyed": True, "txOnAir": True}
        with mock.patch.object(radio, "state", keyed_state):
            self.assertNotEqual(link._faces()["faces"]["halt"]["tone"], "disabled")
        # Acknowledged: an ordinary HALT.
        bridge.licence_ok = True
        self.assertNotEqual(link._faces()["faces"]["halt"]["tone"], "disabled")


if __name__ == "__main__":
    unittest.main()
