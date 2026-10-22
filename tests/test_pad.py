"""The AKP03E and USB keypads in both apps (CONTROLLER-PAD.md; BETA-PLAN
architecture change 6): the declared actions and default layouts are
valid, the actions do what they say on a simulator radio, and on the
desktop a pad keys only through the transmit lease and unkeys when it is
unplugged. The pad is shack_pad's FakeHid, as in ohs-libs' own tests: no
real pad, and nothing keys outside the simulator."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ham_helpers
import helpers
from ohscore import shacklibs

ROOT = Path(__file__).resolve().parent.parent
# The real home, not the scratch one scratch_home moved HOME to.
SCHEMAS = Path(os.environ.get("OHSTEST_REAL_HOME", str(Path.home()))) / "ohs-libs" / "spec" / "schemas"


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class Declarations(unittest.TestCase):
    def test_each_app_declares_valid_actions_and_layouts(self):
        shacklibs.pad()
        from shack_pad import actions, mapping
        from shack_pad.drivers import by_model
        for pkg, kind in (("ohsnb", "qo100nb"), ("ohsradio", "radio")):
            decl = json.loads((ROOT / pkg / "pad-actions.json").read_text())
            layout = json.loads((ROOT / pkg / "pad-layout.json").read_text())
            self.assertEqual(decl["app"], kind)
            actions.validate(decl)
            acts, notes = actions.load(decl)
            self.assertEqual(notes, [])
            ptt = acts["ptt"]
            self.assertTrue(ptt.tx and ptt.hold)
            # Only ptt keys; power changes what goes on air.
            self.assertEqual({a for a, x in acts.items() if x.tx}, {"ptt"})
            for model in ("ajazz-akp03e", "keypad"):
                _pages, notes = mapping.resolve(by_model(model), layout, None, acts)
                self.assertEqual(notes, [], (pkg, model))
            self.assertEqual(layout["ajazz-akp03e"]["K1"], {"press": "ptt"})
            self.assertEqual(layout["keypad"]["KPENTER"], {"press": "ptt"})

    @unittest.skipUnless(SCHEMAS.is_dir(), "ohs-libs' schemas are not checked out here")
    def test_against_the_json_schemas(self):
        import jsonschema
        for pkg in ("ohsnb", "ohsradio"):
            for name in ("pad-actions", "pad-layout"):
                schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
                jsonschema.validate(json.loads((ROOT / pkg / f"{name}.json").read_text()), schema)


class Actions(unittest.TestCase):
    def test_nb_tune_step_mode_volume_power(self):
        with tempfile.TemporaryDirectory() as d:
            r = helpers.make_radio(d)
            pa = r.pad_actions()
            v = r.state()["vfo"]
            pa.perform("tune", "turn", 3)
            self.assertEqual(r.state()["vfo"], v + 300)
            pa.perform("step")
            pa.perform("tune", "turn", -1)
            self.assertEqual(r.state()["vfo"], v + 300 - 1000)
            mode = r.state()["mode"]
            pa.perform("mode:next")
            self.assertNotEqual(r.state()["mode"], mode)
            vol = r.state()["volume"]
            pa.perform("volume", "turn", 2)
            self.assertAlmostEqual(r.state()["volume"], min(1.0, vol + 0.1))
            g = r.state()["txGain"]
            pa.perform("power", "turn", -2)
            self.assertEqual(r.state()["txGain"], g - 2)
            pa.perform("mute")
            self.assertTrue(r.state()["mute"])
            self.assertEqual(pa.faces()["faces"]["mute"]["l2"], "ON")
            pa.perform("no-such-action")       # a layout naming an unknown action does nothing

    def test_the_record_key_goes_amber_while_recording(self):
        with tempfile.TemporaryDirectory() as d:
            r = helpers.make_radio(d, mode="usb", simSignals=False)
            r.start()
            try:
                pa = r.pad_actions()
                self.assertEqual(pa.faces()["faces"]["record"]["tone"], "")
                pa.perform("record")
                face = pa.faces()
                self.assertEqual(face["faces"]["record"]["tone"], "warn")      # amber: red is the air's
                self.assertEqual(face["faces"]["record"]["l1"], "REC")
                self.assertFalse(face["onAir"])
                pa.perform("record")
                self.assertEqual(pa.faces()["faces"]["record"]["tone"], "")
            finally:
                r.stop()

    def test_halt_is_dimmed_when_this_run_cannot_transmit_and_still_halts(self):
        from ohscore.config import receive_only
        with tempfile.TemporaryDirectory() as d:
            r = helpers.make_radio(d, mode="usb", simSignals=False)
            r.start()
            try:
                self.assertEqual(r.pad_actions().faces()["faces"]["halt"]["tone"], "")
            finally:
                r.stop()
            over = {"mode": "usb", "simSignals": False}
            receive_only(over)
            r = helpers.make_radio(d, **over)
            r.start()
            try:
                pa = r.pad_actions()
                face = pa.faces()["faces"]["halt"]
                self.assertEqual((face["l1"], face["l2"], face["tone"]), ("HALT", "TX", "disabled"))
                with mock.patch.object(r, "halt", wraps=r.halt) as halt:
                    pa.perform("halt")
                halt.assert_called_once()
            finally:
                r.stop()

    def test_nb_noise_reduction_filter_and_beacon_hold(self):
        with tempfile.TemporaryDirectory() as d:
            r = helpers.make_radio(d, mode="usb")
            pa = r.pad_actions()
            nr = bool(r.state()["nr"])
            pa.perform("nr")
            self.assertEqual(r.state()["nr"], not nr)
            hi = r.state()["filterHi"]
            pa.perform("filter", "turn", -2)
            self.assertEqual(r.state()["filterHi"], hi - 200)
            pa.perform("filter", "turn", 500)                  # far past the top: stops at it
            self.assertEqual(r.state()["filterHi"], r.STATE.spec["filterHi"]["max"])
            r.set(mode="cw")
            w = r.state()["cwWidth"]
            pa.perform("filter", "turn", 1)
            self.assertEqual(r.state()["cwWidth"], w + 50)
            r.set(mode="ft8")
            with self.assertRaisesRegex(ValueError, "fixed in FT8"):
                pa.perform("filter", "turn", 1)
            self.assertEqual(r.state()["beaconMode"], "auto")
            pa.perform("beacon-hold")
            self.assertEqual(r.state()["beaconMode"], "hold")
            self.assertEqual(pa.faces()["faces"]["beacon-hold"]["l2"], "HOLD")
            pa.perform("beacon-hold")
            self.assertEqual(r.state()["beaconMode"], "auto")

    def test_radio_band_next_and_drive(self):
        r = ham_helpers.make_radio()
        self.addCleanup(ham_helpers.close, r)
        pa = r.pad_actions()
        r.start()
        ham_helpers.pump(r, 0.2)
        before = r.state()["band"]
        pa.perform("band:next")
        ham_helpers.pump(r, 0.2)
        self.assertNotEqual(r.state()["band"], before)
        pa.perform("power", "turn", 50)
        self.assertLessEqual(r.state()["drive"], 1.0)


class Remap(unittest.TestCase):
    """ohscore/padmap.py, the editor's rules without a window: the app's
    layout until the operator changes something, PTT on one picture key at
    most, and a stored map that this version cannot use falls back control
    by control instead of misfiring or stopping the pad."""

    def setUp(self):
        shacklibs.pad()

    def pm(self, maps=None, pkg="ohsnb"):
        from ohscore.padmap import PadMap
        return PadMap(ROOT / pkg, maps or {})

    def test_nothing_stored_is_the_apps_layout_and_stores_nothing(self):
        pm = self.pm()
        self.assertEqual(pm.current("K1", "press"), "ptt")
        self.assertEqual(pm.current("D2", "turn"), "tune")
        self.assertEqual(pm.current("D3", "press"), "none")
        self.assertEqual(pm.ptt_key(), "K1")
        self.assertTrue(pm.is_default())
        self.assertIsNone(pm.entry())
        self.assertFalse(pm.changed())
        self.assertEqual(len(pm.rows()), 6 + 3 + 3 * 2)

    def test_each_row_offers_only_what_that_control_can_run(self):
        pm = self.pm()
        keys = pm.choices("K3", "press")
        self.assertEqual(keys[0], "none")
        self.assertIn("ptt", keys)
        self.assertIn("beacon-hold", keys)
        self.assertIn("tune:up", keys)                       # a knob's job, one step a press
        self.assertNotIn("tune", keys)
        for cid in ("B1", "D1"):
            self.assertNotIn("ptt", pm.choices(cid, "press"))  # PTT only where ON AIR can show
        turns = pm.choices("D1", "turn")
        self.assertEqual(turns[0], "none-turn")
        self.assertEqual(set(turns), {"none-turn", "tune", "channel", "volume", "filter", "power"})
        ham = self.pm(pkg="ohsradio")
        self.assertIn("band", ham.choices("D1", "turn"))
        self.assertIn("band:next", ham.choices("K2", "press"))
        self.assertNotIn("beacon-hold", ham.choices("K2", "press"))   # NB's beacon lock
        self.assertNotIn("auto-tune", ham.choices("K2", "press"))

    def test_ptt_moves_rather_than_doubles_and_can_be_nowhere(self):
        pm = self.pm()
        pm.set("K3", "press", "ptt")
        self.assertEqual(pm.ptt_key(), "K3")
        self.assertEqual(pm.current("K1", "press"), "none")
        self.assertTrue(pm.changed())
        pm.set("K3", "press", "mute")
        self.assertIsNone(pm.ptt_key())
        with self.assertRaises(ValueError):
            pm.set("B1", "press", "ptt")
        with self.assertRaises(ValueError):
            pm.set("D1", "turn", "mute")                     # a press on a turn
        pm.reset()
        self.assertEqual(pm.ptt_key(), "K1")
        self.assertIsNone(pm.entry())

    def test_choosing_the_defaults_again_stores_nothing(self):
        pm = self.pm()
        pm.set("K2", "press", "record")
        self.assertIsNotNone(pm.entry())
        pm.set("K2", "press", "mute")
        self.assertIsNone(pm.entry())

    def test_a_bad_stored_map_falls_back_control_by_control(self):
        maps = {"qo100nb": {"ajazz-akp03e": {"pages": [{
            "K1": {"press": "none"},
            "B1": {"press": "ptt"},                          # not a picture key: B1 keeps its default
            "K2": {"press": "warp-drive"},                   # an action this version does not have
            "K4": "junk", "Z9": {"press": "mute"},
            "D1": {"turn": "mute", "press": "nr"},           # a press on a turn: that half falls back
        }]}}, "radio": "not a dict"}
        pm = self.pm(maps)
        self.assertEqual(pm.current("B1", "press"), "step")
        self.assertIsNone(pm.ptt_key())
        self.assertEqual(pm.current("K2", "press"), "mute")
        self.assertEqual(pm.current("K4", "press"), "mode:next")
        self.assertEqual(pm.current("D1", "turn"), "volume")
        self.assertEqual(pm.current("D1", "press"), "nr")
        for junk in ({"qo100nb": "x"}, {"qo100nb": {"ajazz-akp03e": {"pages": "x"}}}, "x", None):
            self.assertEqual(self.pm(junk).ptt_key(), "K1", junk)

    def test_store_writes_this_entry_only_and_none_resets(self):
        from ohscore import padmap
        with tempfile.TemporaryDirectory() as d:
            r = helpers.make_radio(d)
            self.addCleanup(lambda: r.station.close())
            prof = r.station.profile
            padmap.store(prof, "radio", {"pages": [{"K2": {"press": "record"}}]})
            pm = self.pm(prof.get().get("controllerMaps"))
            pm.set("K5", "press", "nr")
            padmap.store(prof, pm.kind, pm.entry())
            again = self.pm(prof.get().get("controllerMaps"))
            self.assertEqual(again.current("K5", "press"), "nr")
            again.reset()
            padmap.store(prof, again.kind, again.entry())
            maps = prof.get()["controllerMaps"]
            self.assertTrue(self.pm(maps).is_default())       # reset survives a re-read
            self.assertEqual(maps["radio"]["ajazz-akp03e"], {"pages": [{"K2": {"press": "record"}}]})


class DesktopPad(unittest.TestCase):
    """The window's PadLink with a fake AKP03E: K1 held is PTT through
    the lease once the operator has allowed the pad to transmit; unplugged
    while keyed, the transmission stops, and a pad that comes back does
    not key again."""

    ALLOWED = True

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        shacklibs.pad()
        from shack_pad.drivers.ajazz import AKP03E
        from shack_pad.fake import FakeHid
        from PyQt6.QtWidgets import QWidget
        from ohscore.ui.padlink import PadLink
        from ohscore.ui.prefs import Prefs
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.radio = helpers.make_radio(self.tmp.name, callsign="GM4BRI", licenceClass="full", mode="cw",
                                        vfo=10_489_520_000.0)
        self.radio.start()
        self.addCleanup(lambda: self.radio.station.close())
        self.addCleanup(self.radio.stop)
        self.fakes = []
        self.prefs = Prefs(Path(self.tmp.name) / "ui.json")
        if self.ALLOWED:
            self.prefs["padTransmit"] = True

        def open_device():
            f = FakeHid()
            self.fakes.append(f)
            return AKP03E(f)
        self.win = QWidget()
        self.addCleanup(self.win.close)
        self.link = PadLink(self.win, self.radio, "qo100nb", "QO-100 NB", ROOT / "ohsnb", prefs=self.prefs,
                            open_device=open_device)
        self.addCleanup(self.link.close)
        self.assertTrue(wait(lambda: self.fakes and self.link.pad.serving()))

    def press(self, code, state):
        from shack_pad.fake import akp03e_report
        self.fakes[-1].push(akp03e_report(code, state))

    def keyed(self):
        helpers.run_sim(self.radio, 0.05)
        return self.radio.state()["keyed"]

    def k1(self):
        return self.link.host.faces("ajazz-akp03e")["K1"]

    def test_k1_held_is_ptt_through_the_lease(self):
        self.press(0x01, 1)
        self.assertTrue(wait(self.keyed))
        self.assertEqual(self.link.lease.holder is not None, True)
        self.press(0x01, 0)
        self.assertTrue(wait(lambda: not self.keyed()))

    def test_unplugged_while_keyed_unkeys_and_the_pad_coming_back_does_not_key(self):
        self.press(0x01, 1)
        self.assertTrue(wait(self.keyed))
        gone = self.fakes[-1]
        gone.unplug()
        # Unkeyed by the pad going (PadTx.abort), well inside the lease's 5 s.
        self.assertTrue(wait(lambda: not self.keyed(), timeout=2.0))
        self.assertIsNone(self.link.lease.holder)
        # The pad is looked for again and opened; K1 was down when it went,
        # and nothing remembers that.
        self.assertTrue(wait(lambda: self.fakes[-1] is not gone and self.link.pad.serving(), timeout=5.0))
        time.sleep(0.3)
        self.assertFalse(self.keyed())

    def test_a_refused_key_up_does_not_key(self):
        self.radio.set(mode="usb")              # USB in the CW-only segment: the band plan refuses
        self.press(0x01, 1)
        time.sleep(0.5)
        self.assertFalse(self.keyed())
        self.press(0x01, 0)

    def test_the_test_mode_never_keys_or_tunes_and_reports_every_event(self):
        seen = []
        self.link.add_listener(lambda model, ev: seen.append(ev))
        vfo = self.radio.state()["vfo"]
        self.link.start_test()
        self.press(0x01, 1)
        self.press(0x91, 0)                     # D2 one detent: tune, were it not a test
        self.assertTrue(wait(lambda: len(seen) >= 2))
        time.sleep(0.3)
        self.assertFalse(self.keyed())
        self.assertEqual(self.radio.state()["vfo"], vfo)
        self.assertEqual(seen[:2], [("press", "K1", 0), ("turn", "D2", 1)])
        self.assertEqual(self.k1().tone, "active")
        self.press(0x01, 0)
        self.link.stop_test()

    def remap(self, **binds):
        from ohscore.padmap import PadMap
        pm = PadMap(ROOT / "ohsnb", self.link.host.maps)
        for spec, aid in binds.items():
            cid, _sep, slot = spec.partition("_")
            pm.set(cid, slot or "press", aid)
        self.link.apply_map(pm)
        return pm

    def face(self, cid):
        return self.link.host.faces("ajazz-akp03e")[cid]

    def test_a_remapped_pad_runs_the_new_actions_and_draws_them(self):
        self.remap(K3="ptt", K1="nr", D2_turn="volume")
        self.assertEqual(self.face("K1").l1, "NR")
        self.assertIn(self.face("K3").l1, ("PTT",))
        nr, vfo, vol = self.radio.state()["nr"], self.radio.state()["vfo"], self.radio.state()["volume"]
        self.press(0x01, 1)
        self.press(0x01, 0)
        self.assertTrue(wait(lambda: self.radio.state()["nr"] != nr))
        self.assertFalse(self.keyed())                     # K1 no longer transmits
        self.press(0x90, 0)                                 # D2 down one: volume now, not tuning
        self.assertTrue(wait(lambda: self.radio.state()["volume"] != vol))
        self.assertEqual(self.radio.state()["vfo"], vfo)
        self.press(0x03, 1)
        self.assertTrue(wait(self.keyed))
        self.press(0x03, 0)
        self.assertTrue(wait(lambda: not self.keyed()))

    def test_ptt_on_no_key_keys_nothing(self):
        self.remap(K1="mute")
        for code in (1, 2, 3, 4, 5, 6):
            self.press(code, 1)
            self.press(code, 0)
        time.sleep(0.4)
        self.assertFalse(self.keyed())
        self.assertIsNone(self.link.lease.holder)

    def test_the_ptt_key_cannot_move_while_on_the_air(self):
        self.press(0x01, 1)
        self.assertTrue(wait(self.keyed))
        with self.assertRaisesRegex(ValueError, "on the air"):
            self.remap(K3="ptt")
        self.assertEqual(self.link.host.binding("ajazz-akp03e", "K1", "press")[1], "ptt")
        self.press(0x01, 0)                                 # and K1 still stops it
        self.assertTrue(wait(lambda: not self.keyed()))
        self.remap(K3="ptt")                                # off the air it can

    def test_unplugged_while_keyed_on_a_moved_ptt_unkeys(self):
        self.remap(K6="ptt")
        self.press(0x06, 1)
        self.assertTrue(wait(self.keyed))
        self.fakes[-1].unplug()
        self.assertTrue(wait(lambda: not self.keyed(), timeout=2.0))
        self.assertIsNone(self.link.lease.holder)

    def test_the_mapping_survives_a_restart_and_reset_brings_back_the_layout(self):
        from ohscore.padmap import PadMap
        from ohscore.ui.padlink import PadLink
        self.remap(K2="record")
        self.link.close()
        link = PadLink(self.win, self.radio, "qo100nb", "QO-100 NB", ROOT / "ohsnb", prefs=self.prefs,
                       open_device=lambda: (_ for _ in ()).throw(OSError("no pad")))
        self.addCleanup(link.close)
        self.assertEqual(link.host.binding("ajazz-akp03e", "K2", "press")[1], "record")
        pm = PadMap(ROOT / "ohsnb", link.host.maps)
        pm.reset()
        link.apply_map(pm)
        self.assertEqual(link.host.binding("ajazz-akp03e", "K2", "press")[1], "mute")
        self.assertTrue(PadMap(ROOT / "ohsnb", self.radio.station.profile.get().get("controllerMaps")).is_default())

    def test_status_and_report_say_what_is_there_and_nothing_private(self):
        st = self.link.status()
        self.assertEqual(st["state"], "serving")
        self.assertEqual(st["name"], "Ajazz AKP03E")
        self.assertTrue(st["transmit"])
        text = self.link.report()
        self.assertIn("OpenHamShack controller report", text)
        self.assertIn("app: QO-100 NB", text)
        self.assertIn("pad state: serving", text)
        self.assertIn("pad may transmit: yes", text)
        self.assertNotIn("GM4BRI", text)


class DesktopPadOffByDefault(DesktopPad):
    """A fresh ui.json: the pad tunes, mutes and changes mode from the
    first plug-in, but K1 keys nothing and says so on the key."""

    ALLOWED = False

    def test_k1_held_is_ptt_through_the_lease(self):
        self.assertEqual((self.k1().l1, self.k1().l2), ("PTT", "off"))
        self.press(0x01, 1)
        time.sleep(0.5)
        self.assertFalse(self.keyed())
        self.assertIsNone(self.link.lease.holder)
        self.assertEqual(self.k1().tone, "warn")           # the refusal, on the key
        self.press(0x01, 0)
        vfo = self.radio.state()["vfo"]
        self.press(0x91, 0)
        self.assertTrue(wait(lambda: self.radio.state()["vfo"] != vfo))

    def test_unplugged_while_keyed_unkeys_and_the_pad_coming_back_does_not_key(self):
        self.skipTest("an unallowed pad cannot key")

    def test_a_remapped_pad_runs_the_new_actions_and_draws_them(self):
        # PTT moved to K3 is still PTT off: the gate goes with the action,
        # not with the key.
        self.remap(K3="ptt")
        self.assertEqual((self.face("K3").l1, self.face("K3").l2), ("PTT", "off"))
        self.assertEqual(self.face("K1").l1, "")            # nothing on K1 now
        self.press(0x03, 1)
        time.sleep(0.5)
        self.assertFalse(self.keyed())
        self.assertIsNone(self.link.lease.holder)
        self.press(0x03, 0)

    def test_the_ptt_key_cannot_move_while_on_the_air(self):
        self.skipTest("an unallowed pad cannot key")

    def test_unplugged_while_keyed_on_a_moved_ptt_unkeys(self):
        self.skipTest("an unallowed pad cannot key")

    def test_the_test_mode_never_keys_or_tunes_and_reports_every_event(self):
        self.skipTest("the same as for an allowed pad")

    def test_status_and_report_say_what_is_there_and_nothing_private(self):
        self.assertFalse(self.link.status()["transmit"])
        self.assertIn("pad may transmit: no", self.link.report())


class ControlPadPage(unittest.TestCase):
    """Settings › Control pad, as an operator uses it: it says the pad is
    connected, the test lists what the pad sends, the report reaches the
    clipboard, and Save is what lets the pad transmit."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsnb.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        shacklibs.pad()
        from shack_pad.drivers.ajazz import AKP03E
        from shack_pad.fake import FakeHid
        from ohscore.ui import padlink
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        from ohsnb.ui import build
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["OHS_NB_UI_CONF"] = os.path.join(tmp.name, "ui.json")
        self.addCleanup(os.environ.pop, "OHS_NB_UI_CONF", None)
        self.radio = helpers.make_radio(tmp.name, callsign="GM4BRI", licenceClass="full", mode="cw",
                                        vfo=10_489_520_000.0)
        self.addCleanup(lambda: self.radio.station.close())
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        self.win, self.bridge = build(self.radio, prefs)
        self.addCleanup(self.bridge.stop)
        self.addCleanup(self.win.close)
        self.fakes = []

        def open_device():
            self.fakes.append(FakeHid())
            return AKP03E(self.fakes[-1])
        self.link = padlink.PadLink(self.win, self.radio, "qo100nb", "QO-100 NB", ROOT / "ohsnb",
                                    prefs=self.win.prefs, open_device=open_device)
        padlink._current = self.link
        self.addCleanup(self.link.close)
        self.assertTrue(self.wait(lambda: self.fakes and self.link.pad.serving()))

    def wait(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def dialog(self):
        from ohscore.ui.padpage import PadPage
        from ohsnb.ui.settings import SettingsDialog
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(self.bridge, self.win.prefs, self.win, page=titles.index("Control pad"))
        self.addCleanup(d.close)
        page = d.stack.currentWidget().findChild(PadPage)
        self.assertIsNotNone(page)
        return d, page

    def test_it_says_connected_tests_and_copies_the_report(self):
        from shack_pad.fake import akp03e_report
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtWidgets import QLabel
        d, page = self.dialog()
        page.refresh()
        self.assertIn("Connected: Ajazz AKP03E", page.state.text())
        # The system's device path is not on the page (a Mac's read
        # "DevSrvsID:4295056854", finding 15); it is in the tooltip and the report.
        path = self.link.status()["path"]
        self.assertTrue(path)
        texts = [w.text() for w in page.findChildren(QLabel)]
        self.assertFalse([t for t in texts if path in t], texts)
        self.assertIn(path, page.state.toolTip())
        self.assertFalse(page.transmit.on)
        page.toggle_test()
        self.assertTrue(self.link.testing())
        self.fakes[-1].push(akp03e_report(0x02, 1), akp03e_report(0x60, 0))
        self.assertTrue(self.wait(lambda: page.events.count() >= 2))
        rows = [page.events.item(i).text() for i in range(page.events.count())]
        self.assertEqual(rows, ["D3 turned -1", "K2 pressed"])
        page.toggle_test()
        self.assertFalse(self.link.testing())
        page.copy_report()
        self.assertTrue(self.wait(lambda: "OpenHamShack controller report" in QGuiApplication.clipboard().text()))
        self.assertIn("pad state: serving", QGuiApplication.clipboard().text())
        d.reject()

    def test_save_lets_the_pad_transmit_and_cancel_does_not(self):
        from ohscore.ui.prefs import Prefs
        from ohsnb import config
        d, page = self.dialog()
        page.transmit.set_on(True)
        d.reject()
        self.assertFalse(self.link.may_transmit())
        d, page = self.dialog()
        page.transmit.set_on(True)
        d.save()
        self.assertTrue(self.link.may_transmit())
        self.assertTrue(Prefs(config.CONFIG)["padTransmit"])     # on disk, not only in memory

    def choose(self, page, cid, slot, aid):
        box = page.map_rows[(cid, slot)]
        i = box.findData(aid)
        self.assertGreaterEqual(i, 0, (cid, slot, aid))
        box.setCurrentIndex(i)
        box.activated.emit(i)

    def test_the_keys_editor_saves_with_save_and_not_with_cancel(self):
        d, page = self.dialog()
        box = page.map_rows[("K1", "press")]
        self.assertEqual(box.currentData(), "ptt")
        self.assertEqual(box.itemText(0), "Nothing")
        self.assertIn("PTT is K1", page.map_note.text())
        self.assertFalse(page.reset_btn.isEnabled())
        self.assertNotIn("ptt", [page.map_rows[("B1", "press")].itemData(i)
                                 for i in range(page.map_rows[("B1", "press")].count())])
        self.choose(page, "K4", "press", "ptt")
        self.assertEqual(box.currentData(), "none")             # moved, not doubled
        self.assertIn("PTT is K4", page.map_note.text())
        d.reject()
        self.assertEqual(self.link.host.binding("ajazz-akp03e", "K1", "press")[1], "ptt")

        d, page = self.dialog()
        self.assertEqual(page.map_rows[("K1", "press")].currentData(), "ptt")   # Cancel kept nothing
        self.choose(page, "K4", "press", "ptt")
        self.choose(page, "D3", "turn", "filter")
        d.save()
        host = self.link.host
        self.assertEqual(host.binding("ajazz-akp03e", "K4", "press")[1], "ptt")
        self.assertEqual(host.binding("ajazz-akp03e", "D3", "turn")[1], "filter")
        self.assertEqual(host.faces("ajazz-akp03e")["K4"].l1, "PTT")
        self.assertEqual(host.faces("ajazz-akp03e")["K1"].l1, "")

        d, page = self.dialog()
        self.assertEqual(page.map_rows[("K4", "press")].currentData(), "ptt")   # read back from the profile
        self.assertTrue(page.reset_btn.isEnabled())
        page.reset_map()
        self.assertEqual(page.map_rows[("K1", "press")].currentData(), "ptt")
        self.choose(page, "K1", "press", "none")
        self.assertIn("cannot transmit", page.map_note.text())
        page.reset_map()
        d.save()
        self.assertEqual(host.binding("ajazz-akp03e", "K1", "press")[1], "ptt")
        self.assertEqual(host.binding("ajazz-akp03e", "D3", "turn")[1], "channel")


class PadStaysAwake(unittest.TestCase):
    """Ray's AKP03E flickered on every key under NB 0.1.20 on Windows: it
    dropped its host every 39 s for want of a keep-alive, and each drop
    blanked and re-woke the whole pad (ohs-libs shack_pad drivers/ajazz.py).
    Here a fake pad that drops after a short silence, a driver whose
    keep-alive is as much shorter, and each app's own PadLink: receiving
    with the frequency moving and Settings › Control pad open, the pad
    stays connected and hears nothing but keep-alives - no key drawn
    again, no clear, no brightness."""

    SILENCE = 1.2       # the real pad: about 39 s
    EVERY = 0.4         # the real driver: 10 s

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def run_app(self, radio, kind, name, pkg, pump):
        shacklibs.pad()
        from shack_pad.drivers.ajazz import AKP03E
        from shack_pad.fake import FakeHid
        from PyQt6.QtWidgets import QWidget
        from ohscore.ui.padlink import PadLink
        from ohscore.ui.padpage import PadPage
        from ohscore.ui.prefs import Prefs
        silence = self.SILENCE

        class Forgetful(FakeHid):
            """Drops its host after `silence` seconds with no CONNECT. Only
            the keep-alive counts: whether a picture does on the real pad
            is not known."""
            def __init__(self):
                super().__init__()
                self.heard = time.monotonic()

            def write(self, data):
                super().write(data)
                if data[6:13] == b"CONNECT":
                    self.heard = time.monotonic()

            def read(self, timeout):
                if time.monotonic() - self.heard > silence:
                    self.unplug()
                return super().read(timeout)

        class Quick(AKP03E):
            keep_alive_every = self.EVERY

        fakes = []

        def open_device():
            fakes.append(Forgetful())
            return Quick(fakes[-1])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        prefs = Prefs(Path(tmp.name) / "ui.json")
        win = QWidget()
        self.addCleanup(win.close)
        link = PadLink(win, radio, kind, name, ROOT / pkg, prefs=prefs, open_device=open_device)
        self.addCleanup(link.close)
        self.assertTrue(wait(lambda: fakes and link.pad.serving()))
        # The first drawing: all six keys, then whatever a moment's settling
        # brings. Keys are drawn with Pillow; without it (ohs-dev's system
        # Python, and a .deb install without python3-pil) none are, and this
        # waited for six pictures that never came - the "failure on ohs-dev"
        # that passed on the Mac, whose bundle has Pillow (17/10/2026). What
        # the test is for, the pad staying awake on keep-alives alone, holds
        # either way: then the start-up's last word (STP) is the mark.
        from shack_pad.faces import have_pillow
        if have_pillow():
            self.assertTrue(wait(lambda: sum(w[6:9] == b"BAT" for w in fakes[0].writes) >= 6))
        else:
            self.assertTrue(wait(lambda: any(w[6:9] == b"STP" for w in fakes[0].writes)))
        pump(0.6)
        start = len(fakes[0].writes)
        page = PadPage(prefs, name, pkg, radio=radio)
        self.addCleanup(page.stop)
        end = time.monotonic() + 3 * self.SILENCE
        while time.monotonic() < end:
            radio.set(vfo=radio.state()["vfo"] + 10)
            self.app.processEvents()
            pump(0.05)
        self.assertEqual(len(fakes), 1, "the pad dropped and was woken again")
        verbs = [w[6:13].rstrip(b"\0") for w in fakes[0].writes[start:] if w[1:6] == b"CRT\0\0"]
        self.assertEqual(set(verbs), {b"CONNECT"})
        self.assertGreaterEqual(len(verbs), 6)

    def test_nb(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        radio = helpers.make_radio(tmp.name, callsign="GM4BRI", licenceClass="full", mode="usb",
                                   vfo=10_489_750_000.0)
        radio.start()
        self.addCleanup(lambda: radio.station.close())
        self.addCleanup(radio.stop)
        self.run_app(radio, "qo100nb", "QO-100 NB", "ohsnb", lambda s: helpers.run_sim(radio, s))

    def test_radio(self):
        radio = ham_helpers.make_radio()
        self.addCleanup(ham_helpers.close, radio)
        radio.start()
        self.run_app(radio, "radio", "Radio", "ohsradio", lambda s: ham_helpers.pump(radio, s))


class CommandLineReport(unittest.TestCase):
    def test_pad_report_runs_without_a_window_or_radio(self):
        import subprocess
        import sys
        for pkg, name in (("ohsnb", "OpenHamShack QO-100 NB"), ("ohsradio", "OpenHamShack Radio")):
            res = subprocess.run([sys.executable, "-m", pkg, "--pad-report"], cwd=ROOT, capture_output=True,
                                 text=True, timeout=120)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(res.stdout.startswith("OpenHamShack controller report"), res.stdout)
            self.assertIn(f"app: {name}", res.stdout)
            self.assertIn("problems:", res.stdout)


if __name__ == "__main__":
    unittest.main()
