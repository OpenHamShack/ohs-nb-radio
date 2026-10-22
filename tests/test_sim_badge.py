"""The SIMULATOR badge: the engine says why the open device is the
simulator (simWhy, simFallback), and both apps' windows show a badge for
it that a real radio takes away. Users on Windows and macOS spent
evenings on the simulated band believing their radio was connected; these
check the engine's account of each way the simulator gets chosen, and
that the window shows it, by running the engine and the window."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import make_radio, sim_cfg
from ohscore.audio import NullAudio
from ohscore.config import override_device
from ohsnb import config as nb_config
from ohsnb.devices.sim import SimDevice
from ohsnb.radio import Radio


class PosingAsPluto(SimDevice):
    """The simulator's signal under a real radio's name: what the engine
    judges by is the device it opened, not the `device` setting."""
    kind = "pluto"


def radio_from(cfg, tmp, device=None, persist=False, conf_path=None):
    return Radio(cfg, persist=persist, data_dir=tmp, conf_path=conf_path, audio=NullAudio(realtime=False),
                 device=device)


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def started(self, r):
        self.radios.append(r)
        r.start()
        return r

    def test_simulator_chosen_in_settings_says_so(self):
        r = self.started(make_radio(self.tmp))
        st = r.state()
        self.assertFalse(st["simFallback"])
        self.assertIn("Settings › Radio", st["simWhy"])

    def test_real_radio_has_no_reason(self):
        r = self.started(radio_from(sim_cfg(), self.tmp, device=PosingAsPluto(sim_cfg())))
        self.assertEqual(r.state()["simWhy"], "")
        self.assertFalse(r.state()["simFallback"])

    def test_unknown_saved_radio_falls_back_and_warns(self):
        notes = []
        raw = dict(sim_cfg(), device="hl2")       # HAM's radio, hand-copied into NB's file
        cfg = nb_config.clean(raw, notes)
        self.assertEqual(cfg["device"], "sim")
        r = radio_from(cfg, self.tmp)
        toasts = r.subscribe("toast", 16)
        self.started(r)
        st = r.state()
        self.assertTrue(st["simFallback"])
        self.assertIn("'hl2'", st["simWhy"])
        self.assertIn("standing in", st["simWhy"])
        said = [t for t in toasts.drain() if t["level"] == "warn"]
        self.assertTrue(any("'hl2'" in t["text"] for t in said))

    def test_unreadable_file_falls_back_and_the_reason_is_never_saved(self):
        conf = Path(self.tmp) / "config.json"
        conf.write_text("{ not json", encoding="utf-8")
        # cfg=None: the engine loads the file itself, as a Radio built
        # without a config does.
        r = Radio(None, persist=True, data_dir=self.tmp, conf_path=conf, audio=NullAudio(realtime=False))
        r.cfg.update(simRealtime=False, simSignals=False)
        self.started(r)
        self.assertTrue(r.state()["simFallback"])
        self.assertIn("could not be read", r.state()["simWhy"])
        r.set(volume=0.3)
        r.stop()
        saved = json.loads(conf.read_text(encoding="utf-8"))
        self.assertNotIn("_deviceWhy", saved)
        self.assertEqual(saved["volume"], 0.3)

    def test_command_line_override_says_it_is_for_this_run(self):
        cfg = sim_cfg(device="pluto")
        override_device(cfg, "sim")
        r = self.started(radio_from(cfg, self.tmp))
        st = r.state()
        self.assertFalse(st["simFallback"])
        self.assertIn("--device sim", st["simWhy"])

    def test_choosing_a_radio_in_settings_ends_the_fallback(self):
        cfg = nb_config.clean(dict(sim_cfg(), device="bogus"), [])
        r = self.started(radio_from(cfg, self.tmp))
        self.assertTrue(r.state()["simFallback"])
        # The operator picks a radio, then (say) goes back to the simulator:
        # either way it is now their choice, not a stand-in.
        r.set(authorise=True, device="pluto")
        r.set(authorise=True, device="sim")
        r.stop()
        r.start()
        self.assertFalse(r.state()["simFallback"])
        self.assertIn("Settings › Radio", r.state()["simWhy"])

    def test_nothing_open_is_no_simulator(self):
        r = self.started(make_radio(self.tmp))
        r.stop()
        self.assertEqual(r.state()["simWhy"], "")
        self.radios.remove(r)

    def test_ham_engine_says_the_same(self):
        from ham_helpers import close, make_radio as ham_radio
        r = ham_radio()
        try:
            r.start()
            self.assertFalse(r.state()["simFallback"])
            self.assertIn("Settings › Radio", r.state()["simWhy"])
        finally:
            close(r)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class NbWindow(unittest.TestCase):
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
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def until(self, cond, timeout=5.0):
        """Pump Qt until cond() holds, bounded. The engine's state change
        reaches the badge through a queued signal plus a poll, so one
        processEvents() beat it on a loaded machine (2 in 3 on the Mac)."""
        import time
        end = time.monotonic() + timeout
        while not cond() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def window(self, radio):
        from ohscore.ui.prefs import Prefs
        from ohsnb.ui import build
        prefs = Prefs(nb_config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.app.processEvents()
        return win, bridge

    def test_badge_shows_on_the_simulator_with_the_reason(self):
        win, _bridge = self.window(make_radio(self.tmp))
        badge = win.sim_badge
        self.assertTrue(badge.isVisible())
        self.assertIn("Settings › Radio", badge.toolTip())
        self.assertGreater(badge.width(), 60)

    def test_fallback_badge_says_standing_in(self):
        cfg = nb_config.clean(dict(sim_cfg(), device="bogus"), [])
        win, _bridge = self.window(radio_from(cfg, self.tmp))
        self.assertTrue(win.sim_badge.isVisible())
        self.assertIn("standing in", win.sim_badge.toolTip())
        self.assertIn("&#x27;bogus&#x27;", win.sim_badge.toolTip())     # escaped for the rich-text tip

    def test_no_badge_on_a_real_radio(self):
        win, _bridge = self.window(radio_from(sim_cfg(), self.tmp, device=PosingAsPluto(sim_cfg())))
        self.assertFalse(win.sim_badge.isVisible())

    def test_badge_follows_a_restart_onto_a_real_radio_and_back(self):
        # What a Settings save that changes the radio does: bridge.restart().
        radio = make_radio(self.tmp)
        win, bridge = self.window(radio)
        self.assertTrue(win.sim_badge.isVisible())
        radio._inj_device = PosingAsPluto(sim_cfg())
        self.assertEqual(bridge.restart(), "")
        self.until(lambda: not win.sim_badge.isVisible())
        self.assertFalse(win.sim_badge.isVisible())
        radio._inj_device = None
        self.assertEqual(bridge.restart(), "")
        self.until(lambda: win.sim_badge.isVisible())
        self.assertTrue(win.sim_badge.isVisible())


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class HamWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        from ohsradio.ui import make_app
        cls.app = qt_app(make_app)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ui.json")
        self.wins = []

    def tearDown(self):
        for win, bridge in self.wins:
            win.close()
            bridge.stop()
        self.app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def window(self, device=None):
        from ohscore.ui.prefs import Prefs
        from ohsradio import config
        from ohsradio.radio import Radio as HamRadio
        from ohsradio.ui import build
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "callsign": "GM4BRI", "licenceClass": "foundation"}
        radio = HamRadio(cfg, persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False),
                         device=device(dict(cfg)) if device else None)
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        self.app.processEvents()
        return win

    def test_badge_on_the_band_simulator(self):
        win = self.window()
        self.assertTrue(win.sim_badge.isVisible())
        self.assertIn("Settings › Radio", win.sim_badge.toolTip())

    def test_no_badge_on_a_real_radio(self):
        from ohsradio.devices.sim import HamSim
        win = self.window(device=type("Hl2", (HamSim,), {"kind": "hl2"}))
        self.assertFalse(win.sim_badge.isVisible())


if __name__ == "__main__":
    unittest.main()
