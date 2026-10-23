"""The shared pieces of the October 2026 UI overhaul (docs/ui-overhaul-2026-10.md,
WP0): the mode groups, the theme's contrast and text size, the window
preferences' new keys and their migration, the transmit-state classifier
and the window-size rules. Most are pure and tested without a window; the
text size is also checked through the real window and Settings, on Qt's
offscreen platform."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover - the engine's tests still run without PyQt6
    HAVE_QT = False


class ModeGroups(unittest.TestCase):
    def test_every_mode_of_both_apps_is_in_exactly_one_group(self):
        from ohscore import modegroups
        from ohsradio import state as ham
        from ohsnb import state as nb
        for app, modes in (("NB", nb.MODES), ("Radio", ham.MODES)):
            for m in modes:
                homes = [g for g, ms in modegroups.GROUPS if m in ms]
                self.assertEqual(len(homes), 1, f"{app}: {m} is in {homes}")
            shown = [m for _g, ms in modegroups.groups(modes) for m in ms]
            self.assertEqual(sorted(shown), sorted(modes), app)       # each once, nothing extra

    def test_the_groups_an_app_shows(self):
        from ohscore import modegroups as mg
        from ohsradio import state as ham
        from ohsnb import state as nb
        nbg = dict(mg.groups(nb.MODES, buttons=("kgstv",)))
        self.assertEqual(nbg[mg.VOICE], ["usb", "lsb", "cw", "am", "freedv"])
        self.assertEqual(nbg[mg.DIGITAL], ["ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty"])
        self.assertEqual(nbg[mg.PICTURES], ["sstv", "kgstv", "hsmodem"])
        hamg = dict(mg.groups(ham.MODES))
        self.assertEqual(hamg[mg.VOICE], ["usb", "lsb", "cw", "am", "fm", "wfm", "freedv"])
        self.assertNotIn("q65", hamg[mg.DIGITAL])
        self.assertEqual(hamg[mg.PICTURES], ["sstv"])
        # KG-STV is a button only where asked for, never a mode by default.
        self.assertNotIn("kgstv", dict(mg.groups(nb.MODES))[mg.PICTURES])

    def test_the_workspace_each_mode_brings(self):
        from ohscore.modegroups import workspace_for
        self.assertEqual(workspace_for("usb"), "voice")
        self.assertEqual(workspace_for("fm"), "voice")
        self.assertEqual(workspace_for("ft8"), "digital")
        self.assertEqual(workspace_for("js8"), "digital")
        self.assertEqual(workspace_for("sstv"), "digital")        # decision 1: pictures use Digital
        self.assertEqual(workspace_for("hsmodem"), "digital")
        self.assertEqual(workspace_for("nonsense"), "voice")

    def test_slot_modes_behave_as_ft8_and_ft4_did(self):
        from ohscore.modegroups import is_slot, slot_spec
        from ohscore.ui.panels import panel_key
        from ohscore.ui.tuning import click_to_dial
        self.assertEqual(panel_key("ft8"), "slot")
        self.assertEqual(panel_key("ft4"), "slot")
        # Q65 and JS8 are slot modes since WP3: the slot panel shows both
        # (JS8 in its own view, tests/test_ui_q65_js8.py), and both send.
        self.assertEqual(panel_key("q65"), "slot")
        self.assertEqual(panel_key("js8"), "slot")
        self.assertTrue(is_slot("q65"))
        self.assertTrue(slot_spec("js8").transmits)
        self.assertEqual(click_to_dial("ft8", 10_489_541_620.0, {}), 10_489_540_000.0)
        self.assertEqual(click_to_dial("ft4", 10_489_541_620.0, {}), 10_489_540_000.0)
        self.assertEqual(click_to_dial("usb", 10_489_541_620.0, {}), 10_489_541_600.0)
        self.assertEqual((slot_spec("ft8").period, slot_spec("ft8").tone_width), (15.0, 50.0))
        self.assertEqual((slot_spec("ft4").period, slot_spec("ft4").tone_width), (7.5, 83.3))

    def test_labels(self):
        from ohscore.modegroups import label
        from ohscore.ui.rail import MODE_LABELS        # still importable from where it was
        self.assertEqual(label("q65"), "Q65")
        self.assertEqual(label("js8"), "JS8")
        self.assertEqual(label("kgstv"), "KG-STV")
        self.assertEqual(MODE_LABELS["hsmodem"], "HSmodem")
        self.assertEqual(label("xyz"), "XYZ")


class LayoutRules(unittest.TestCase):
    def test_the_tier_table(self):
        from ohscore.ui.layoutrules import COMPACT, FULL, TIGHT, tier
        for (w, h), want in (((1920, 1080), FULL), ((1500, 860), FULL), ((1499, 1080), COMPACT),
                             ((1920, 859), COMPACT), ((1366, 768), COMPACT), ((1180, 700), COMPACT),
                             ((1179, 900), TIGHT), ((1280, 699), TIGHT), ((1280, 720), COMPACT),
                             ((1024, 600), TIGHT)):
            self.assertEqual(tier(w, h), want, (w, h))

    def test_larger_text_moves_the_window_into_a_smaller_tier(self):
        from ohscore.ui.layoutrules import COMPACT, FULL, TIGHT, tier
        self.assertEqual(tier(1920, 1080, 1.15), FULL)         # 1670 x 939
        self.assertEqual(tier(1920, 1080, 1.3), COMPACT)       # 1477 x 831
        self.assertEqual(tier(2560, 1440, 1.3), FULL)          # 1969 x 1108
        self.assertEqual(tier(1366, 768, 1.15), TIGHT)         # 1188 x 668
        self.assertEqual(tier(1366, 768, 1.3), TIGHT)

    def test_the_minimum_scales_and_never_exceeds_the_screen(self):
        from ohscore.ui.layoutrules import minimum_size, scale_fits
        self.assertEqual(minimum_size(), (1024, 600))
        self.assertEqual(minimum_size(1.15), (1178, 690))
        self.assertEqual(minimum_size(1.3), (1332, 780))
        self.assertEqual(minimum_size(1.3, room=(1366, 728)), (1332, 728))
        self.assertTrue(scale_fits(1.0, (1280, 680)))
        self.assertFalse(scale_fits(1.3, (1366, 728)))        # a 1366 x 768 laptop, less its task bar
        self.assertTrue(scale_fits(1.3, (1920, 1040)))

    def test_text_scale_steps(self):
        from ohscore.ui.layoutrules import nearest_scale
        self.assertEqual(nearest_scale(1.3), 1.3)
        self.assertEqual(nearest_scale(1.2), 1.15)
        self.assertEqual(nearest_scale(5), 1.3)
        self.assertEqual(nearest_scale("big"), 1.0)
        self.assertEqual(nearest_scale(None), 1.0)
        self.assertEqual(nearest_scale(float("nan")), 1.0)


class PrefsKeys(unittest.TestCase):
    # As 0.1.21 left them: dragged at 1600 x 960 (split_main's 770 is the
    # body under the header, split_side's 1584 the window less its margins).
    OLD = {"split_main": [421, 349], "split_low": [403, 873], "split_side": [1276, 300]}
    OLD_SLOT = {"split_main": [231, 539], "split_low": [281, 995], "split_side": [1276, 300]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "ui.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def load(self, d):
        from ohscore.ui.prefs import Prefs
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(d, f)
        return Prefs(self.file)

    def test_the_new_keys_and_their_defaults(self):
        from ohscore.ui.prefs import Prefs
        p = Prefs(self.file)                               # no file at all
        self.assertEqual(p["workspace"], "auto")
        self.assertEqual(p["workspaces"], {})
        self.assertEqual(p["modeRecent"], [])
        self.assertEqual(p["textScale"], 1.0)

    def test_old_splitters_load_as_voice_and_digital_fractions_that_give_the_same_pixels(self):
        from ohscore.ui.prefs import sizes_from_layout
        p = self.load({"splitters": self.OLD, "slotSplitters": self.OLD_SLOT, "geometry": "AdnQywADAAA="})
        ws = p["workspaces"]
        self.assertEqual(set(ws), {"voice", "digital"})
        for name, old in (("voice", self.OLD), ("digital", self.OLD_SLOT)):
            totals = {n: sum(v) for n, v in old.items()}
            back = sizes_from_layout(ws[name], totals)
            for n, sizes in old.items():
                for a, b in zip(back[n], sizes):
                    self.assertLessEqual(abs(a - b), 2, (name, n, back[n], sizes))
        self.assertAlmostEqual(ws["digital"]["wide"], 231 / 770, places=6)
        self.assertEqual(ws["voice"]["rail"], 300)
        # The old keys stay, for a downgrade.
        self.assertEqual(p["splitters"], self.OLD)
        self.assertEqual(p["slotSplitters"], self.OLD_SLOT)

    def test_the_migration_runs_once(self):
        # Once workspaces are in the file, old keys never overwrite them:
        # the window keeps writing both, and the newer is the workspace.
        p = self.load({"splitters": self.OLD, "workspaces": {"voice": {"wide": 0.42}}})
        self.assertEqual(p["workspaces"], {"voice": {"wide": 0.42}})
        p = self.load({"splitters": {}, "slotSplitters": {}})
        self.assertEqual(p["workspaces"], {})                   # nothing dragged: nothing to keep
        p = self.load({"splitters": {"split_main": "tall", "split_low": [1, 2, 3]}})
        self.assertEqual(p["workspaces"], {})                   # unreadable: the defaults again

    def test_values_the_window_cannot_show_fall_back(self):
        p = self.load({"textScale": 1.2, "workspace": "cinema", "modeRecent": ["ft8", 7, "usb"],
                       "workspaces": {"watch": {"wide": 0.66}, "party": {"wide": 0.1}, "voice": "big"}})
        self.assertEqual(p["textScale"], 1.15)
        self.assertEqual(p["workspace"], "auto")
        self.assertEqual(p["modeRecent"], ["ft8", "usb"])
        self.assertEqual(p["workspaces"], {"watch": {"wide": 0.66}})
        p = self.load({"textScale": 1.3, "workspace": "watch"})
        self.assertEqual((p["textScale"], p["workspace"]), (1.3, "watch"))

    def test_sizes_from_a_layout_fit_the_room_there_is(self):
        from ohscore.ui.prefs import sizes_from_layout
        got = sizes_from_layout({"wide": 0.25, "zoom": 0.17, "rail": 320},
                                {"split_main": 1000, "split_low": 1600, "split_side": 1920})
        self.assertEqual(got, {"split_main": [250, 750], "split_low": [272, 1328], "split_side": [1600, 320]})
        self.assertEqual(sizes_from_layout({"wide": 1.7, "rail": True}, {"split_main": 1000, "split_side": 900}), {})
        self.assertEqual(sizes_from_layout({"rail": 2000}, {"split_side": 900})["split_side"], [0, 900])


class ShotMatrix(unittest.TestCase):
    def test_the_command_line(self):
        from ohscore.ui.shotmatrix import ALL_SIZES, parse
        self.assertEqual(parse(["out", "--quick"]), (None, ["out", "--quick"]))
        m, rest = parse(["out", "--matrix", "modes=usb,ft8", "sizes=1366x768,1024x600", "scales=1,1.3",
                         "themes=light", "--workspace", "watch", "--receive-only", "--locale", "en-XA", "--quick"])
        self.assertEqual(rest, ["out", "--quick"])               # the tool's own words are left to it
        self.assertEqual((m.modes, m.sizes, m.scales, m.themes), (("usb", "ft8"), ((1366, 768), (1024, 600)),
                                                                   ("1", "1.3"), ("light",)))
        self.assertEqual((m.workspace, m.receive_only, m.locale), ("watch", True, "en-XA"))
        m, _ = parse(["out", "--matrix"])
        self.assertEqual((m.modes, m.sizes, m.themes), (("usb", "ft8", "q65", "js8", "sstv"), ALL_SIZES,
                                                         ("dark", "light")))
        for bad in (["--matrix", "sizes=big"], ["--matrix", "themes=blue"], ["--matrix", "--workspace"],
                    ["--matrix", "scales=x"]):
            with self.assertRaises((SystemExit, ValueError)):
                parse(bad)

    def test_names_and_waits(self):
        from ohscore.ui.shotmatrix import filename, settle_seconds
        self.assertEqual(filename("ft8", (1920, 1080), "1.3", "dark"), "m-ft8-1920x1080-1.3-dark.png")
        self.assertEqual(filename("usb", (1024, 600), "1", "light", "watch"), "m-usb-1024x600-1-light-watch.png")
        self.assertEqual(settle_seconds("ft8"), 35.0)
        self.assertEqual(settle_seconds("q65"), 125.0)           # two Q65 periods
        self.assertGreater(settle_seconds("usb"), 10.0)


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two #rrggbb colours."""
    def lum(h):
        r, g, b_ = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b_)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Contrast(unittest.TestCase):
    def test_the_ratio_itself(self):
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(contrast("#767676", "#ffffff"), 4.54, places=2)   # WCAG's own example

    def test_every_text_token_reaches_aa_on_every_background_in_both_themes(self):
        from ohscore.ui import theme
        low = []
        for th in (theme.DARK, theme.LIGHT):
            for k in theme.TEXT_TOKENS:
                for bg in ("bg0", "bg1", "bg2"):
                    r = contrast(th[k], th[bg])
                    if r < 4.5:
                        low.append(f"{th['name']} {k} {th[k]} on {bg} {th[bg]}: {r:.2f}")
        self.assertEqual(low, [])

    def test_scope_colours_reach_aa_on_the_scope_in_both_themes(self):
        # sc() draws these from the dark set on either theme's scope.
        from ohscore.ui import theme
        for scope_bg in (theme.DARK["scope"], theme.LIGHT["scope"]):
            for k in theme.SCOPE_KEYS:
                self.assertGreaterEqual(contrast(theme.DARK[k], scope_bg), 4.5, k)

    def test_the_new_tokens_exist_in_both_themes_and_to_you_is_not_red(self):
        from ohscore.ui import theme
        for th in (theme.DARK, theme.LIGHT):
            self.assertEqual(set(theme.DARK) - set(th), set())
            for k in ("toYou", "rec", "limit"):
                h = th[k].lstrip("#")
                r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
                self.assertGreater(g, b, k)                  # amber/gold: red and green over blue
                self.assertGreater(g, 0.55 * r, k)           # not a red


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class TextSize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "ui.json")
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
        # The scale is the process's, and the suite's next window expects 100 %.
        theme.set_scale(1.0)
        theme.set_theme("dark")
        self.app.setFont(theme.app_font())
        self.app.setStyleSheet(theme.stylesheet())
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                           for e in self.errors))

    def window(self):
        from helpers import make_radio
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        radio = make_radio(self.tmp)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def test_scale_multiplies_fonts_and_fixed_sizes(self):
        from ohscore.ui import theme
        try:
            self.assertEqual(theme.set_scale(1.3), 1.3)
            self.assertEqual(theme.font(10).pixelSize(), 13)
            self.assertEqual(theme.px(34), 44)
            self.assertEqual(theme.caps(10).pixelSize(), 13)
            self.assertIn("font-size: 14px", theme.stylesheet())      # the table headers: 13 x 1.3 x 0.85
            self.assertEqual(theme.set_scale(1.2), 1.15)              # snapped to a step
            self.assertEqual(theme.font(20).pixelSize(), 23)
        finally:
            theme.set_scale(1.0)
        self.assertEqual(theme.font(10).pixelSize(), 10)
        self.assertEqual(theme.px(34), 34)

    def test_a_rebuild_keeps_the_layout_default_or_dragged(self):
        def shares(win):
            self.app.processEvents()
            return [s.sizes()[i] / sum(s.sizes()) for s, i in ((win.split_side, 1), (win.split_main, 0),
                                                              (win.split_low, 0))]
        win, bridge, radio = self.window()
        for _ in range(5):
            self.app.processEvents()
        before = shares(win)
        win.set_theme("light")
        for a, b in zip(shares(win), before):
            self.assertAlmostEqual(a, b, delta=0.01)       # the default again, not Qt's stretch factors
        win.split_low.setSizes([300, sum(win.split_low.sizes()) - 300])
        win.split_low.splitterMoved.emit(300, 1)
        dragged = shares(win)
        win.set_theme("dark")
        for a, b in zip(shares(win), dragged):
            self.assertAlmostEqual(a, b, delta=0.01)

    def test_text_size_130_from_settings_applies_at_once_and_survives_a_restart(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from ohscore.ui import theme
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui.settings import SettingsDialog
        from ohscore.ui.window import BaseWindow
        # A screen with room for 130 %'s least window (1332 x 780): the
        # offscreen platform's is 800 x 800, where Settings greys it.
        BaseWindow.SCREEN_ROOM = (1920, 1040)
        self.addCleanup(setattr, BaseWindow, "SCREEN_ROOM", None)
        win, bridge, radio = self.window()
        before = win.panel_title.font().pixelSize()
        d = SettingsDialog(bridge, win.prefs, win)
        d.show_page("page_display")
        ts = d.pref_widgets["textScale"]
        self.assertEqual([lab for _v, lab in ts.options], ["100 %", "115 %", "130 %"])
        QTest.mouseClick(ts, Qt.MouseButton.LeftButton, pos=ts._cell(2).center().toPoint())
        self.assertEqual(ts.value, "1.3")
        d.save()
        win.apply_prefs(d.restart_needed)                 # as open_settings does when Save closes it
        self.app.processEvents()
        self.assertEqual(theme.scale(), 1.3)
        # The window was rebuilt at the new size: its widgets are new ones.
        self.assertEqual(win.panel_title.font().pixelSize(), round(before * 1.3))
        self.assertEqual(self.app.font().pixelSize(), 17)  # 13 px x 1.3
        win.close()
        bridge.stop()
        self.wins.clear()
        theme.set_scale(1.0)                               # a new process starts at 100 %
        self.assertEqual(Prefs(config.CONFIG)["textScale"], 1.3)
        win2, _b2, _r2 = self.window()
        self.assertEqual(theme.scale(), 1.3)
        self.assertEqual(win2.panel_title.font().pixelSize(), round(before * 1.3))


class TxStateRules(unittest.TestCase):
    """The classifier's rules on hand-made states; TxStateLive checks it
    against real runs on the simulator."""

    def test_the_order_of_the_rules(self):
        from ohscore.config import RECEIVE_ONLY_REFUSAL
        from ohscore.ui.txstate import HERE, NEVER, OK, SETUP, classify
        run = {"running": True, "canTx": True, "txBlocked": ""}
        self.assertEqual(classify(run, False).kind, OK)
        self.assertEqual(classify(run, True, licence_why="tick it").kind, SETUP)
        self.assertEqual(classify(run, True, licence_why="tick it").why, "tick it")
        # Receive-only wins over the licence: no tick box makes it transmit.
        self.assertEqual(classify(run, True, receive_only=True), classify({}, False, receive_only=True))
        self.assertEqual(classify({}, False, receive_only=True).why, RECEIVE_ONLY_REFUSAL)
        self.assertEqual(classify({**run, "canTx": False}, True).kind, NEVER)
        playing = {**run, "canTx": False, "playing": True, "txBlocked": "Playing a recording: no transmitter"}
        self.assertEqual(classify(playing, False).kind, HERE)        # back to the radio and it can
        self.assertEqual(classify({**run, "txBlocked": "Not in this segment"}, False).why, "Not in this segment")
        self.assertEqual(classify({"running": False, "error": "No Pluto"}, False).why, "No Pluto")

    def test_a_card_never_collapses_over_the_air_or_a_warning(self):
        from ohscore.ui.txstate import HERE, NEVER, OK, SETUP, TxState, may_collapse
        for kind in (NEVER, SETUP):
            self.assertTrue(may_collapse(TxState(kind), {}, on_air=False))
            self.assertFalse(may_collapse(TxState(kind), {}, on_air=True))    # e.g. an IC-9700 keyed by hand
            self.assertFalse(may_collapse(TxState(kind), {"keyed": True}, on_air=False))
            self.assertFalse(may_collapse(TxState(kind), {"txWarning": {"text": "aimed where NB would not"}},
                                          on_air=False))
        for kind in (OK, HERE):
            self.assertFalse(may_collapse(TxState(kind), {}, on_air=False))

    def test_no_licence_class_alone_lets_the_card_shrink(self):
        # Brian's call, 17/10/2026: the "choose a licence class" reminder is
        # setup, not danger, so it does not hold the card open; a real
        # warning beside it still would, and the air always does.
        from ohscore.ui.txstate import NEVER, SETUP, TxState, may_collapse
        noclass = {"txWarning": {"key": "licence", "level": "warn", "text": "No licence class is set"}}
        for kind in (NEVER, SETUP):
            self.assertTrue(may_collapse(TxState(kind), noclass, on_air=False))
            self.assertFalse(may_collapse(TxState(kind), noclass, on_air=True))
            self.assertFalse(may_collapse(TxState(kind), {"txWarning": {"key": "level", "level": "warn",
                                                                          "text": "over the beacon"}},
                                          on_air=False))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class TxStateLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridges = []

    def tearDown(self):
        for b in self.bridges:
            b.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bridge(self, start=True, licence=False, device=None, **over):
        from helpers import make_radio
        from ohscore.ui.bridge import Bridge
        from ohsnb.ui.face import Qo100Face
        radio = make_radio(self.tmp, device=device, **over)
        b = Bridge(radio, face=Qo100Face())
        b.licence_ok = licence
        if start:
            self.assertEqual(b.start(), "")
            self.bridges.append(b)
            b.st.update(radio.state())
        return b

    def test_the_simulator_is_ok(self):
        from ohscore.ui.txstate import OK, of_bridge
        self.assertEqual(of_bridge(self.bridge(vfo=10_489_700_000.0, mode="usb")).kind, OK)

    def test_receive_only_is_never_before_and_after_it_starts(self):
        from ohscore.config import RECEIVE_ONLY, RECEIVE_ONLY_REFUSAL
        from ohscore.ui.txstate import NEVER, of_bridge
        b = self.bridge(start=False, **{RECEIVE_ONLY: True})
        self.assertEqual(of_bridge(b).kind, NEVER)
        b.start()
        self.bridges.append(b)
        b.st.update(b.radio.state())
        self.assertFalse(b.st["canTx"])
        self.assertEqual(of_bridge(b).kind, NEVER)
        self.assertEqual(of_bridge(b).why, RECEIVE_ONLY_REFUSAL)

    def test_a_receive_only_device_is_never(self):
        # As a SoapySDR: a device that cannot transmit (SoapyDevice.can_tx
        # is False), here the simulator saying so, so no SDR is needed.
        from ohscore.devices.soapy import SoapyDevice
        from ohscore.ui.txstate import NEVER, of_bridge
        from ohsnb.devices.sim import SimDevice

        class ReceiveOnlySim(SimDevice):
            can_tx = SoapyDevice.can_tx
        self.assertFalse(ReceiveOnlySim.can_tx)
        b = self.bridge(device=ReceiveOnlySim, licence=True)
        self.assertEqual(of_bridge(b).kind, NEVER)
        self.assertEqual(of_bridge(b).why, "This device is receive-only")

    def test_a_radio_without_the_licence_acknowledged_needs_setting_up(self):
        from helpers import RadiatingSim
        from ohscore.ui.bridge import LICENCE_SENTENCE
        from ohscore.ui.txstate import OK, SETUP, of_bridge
        from ohsnb.devices.sim import SimDevice
        # A Pluto chosen in Settings, before it is open: judged a radio.
        from helpers import sim_cfg
        from ohscore.audio import NullAudio
        from ohscore.ui.bridge import Bridge
        from ohsnb.radio import Radio
        from ohsnb.ui.face import Qo100Face
        pluto = Radio(sim_cfg(device="pluto"), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))
        self.assertEqual(of_bridge(Bridge(pluto, face=Qo100Face())).kind, SETUP)

        class Radiating(RadiatingSim, SimDevice):
            pass
        b = self.bridge(device=Radiating)                  # running, and radiating as a radio does
        st = of_bridge(b)
        self.assertEqual((st.kind, st.why), (SETUP, LICENCE_SENTENCE))
        b.licence_ok = True
        self.assertEqual(of_bridge(b).kind, OK)

    def test_a_refused_segment_is_here_with_the_engines_sentence(self):
        from ohscore.ui.txstate import HERE, of_bridge
        b = self.bridge(vfo=10_489_545_000.0, mode="usb")       # SSB in the narrow digimodes segment
        st = of_bridge(b)
        self.assertEqual(st.kind, HERE)
        self.assertEqual(st.why, b.can_key())
        self.assertIn("not allowed in the narrow digimodes", st.why)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class ModeWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def test_the_mode_button_shows_the_mode_and_picks_from_its_menu(self):
        from ohscore.modegroups import label
        from ohscore.ui.modegrid import ModeMenuButton
        from ohsnb import state as nb
        b = ModeMenuButton(nb.MODES)
        b.set_mode("q65")
        self.assertTrue(b.text().startswith("Q65"))
        b.set_caps({"freedv": {"missing": "FreeDV needs codec2"}})
        b.menu_.aboutToShow.emit()
        acts = {a.text(): a for a in b.menu_.actions() if a.data()}
        # Every mode, by group (WP2 grouped the menu; the headings are not
        # modes and cannot be picked).
        from ohscore.padactions import mode_order
        self.assertEqual(list(acts), [label(m) for m in mode_order(nb.MODES)])
        self.assertEqual([a.text() for a in b.menu_.actions() if not a.data()], ["Voice", "Digital", "Pictures & data"])
        self.assertTrue(acts["Q65"].isChecked())
        self.assertEqual(acts["FreeDV"].toolTip(), "FreeDV needs codec2")
        got = []
        b.picked.connect(got.append)
        acts["JS8"].trigger()
        self.assertEqual(got, ["js8"])

    def test_the_grid_takes_a_form_and_stays_the_grid(self):
        from ohscore.ui.modegrid import ModeGrid
        from ohsnb import state as nb
        g = ModeGrid(nb.MODES)
        cells = dict(g.cells)
        g.set_form("compact")
        self.assertEqual(g.form, "compact")
        g.set_form("sideways")                  # not a form: ignored
        self.assertEqual(g.form, "compact")
        self.assertEqual(g.cells, cells)        # the same cells: nothing rebuilt

    def test_each_mode_cell_tells_a_screen_reader_its_mode(self):
        from ohscore.ui.modegrid import ModeGrid
        from ohsnb import state as nb
        g = ModeGrid(nb.MODES)
        g.show()
        self.app.processEvents()
        self.assertEqual(g.cells["q65"].accessibleName(), "Q65")
        self.assertEqual(g.cells["hsmodem"].accessibleName(), "HSmodem")
        g.close()


if __name__ == "__main__":
    unittest.main()
