"""The window with an IC-9700 as the transmitter: Settings > Transmitter
and the transmit card, against the CI-V emulator over TCP, on Qt's
offscreen platform. Behaviour only: what the widgets show and what the
engine and the emulated radio were told. No serial port is opened."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import socket
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import rig_conv
from ohscore.rig.civsim import CivSim
from ohsnb import bandplan

from test_ui_window import WindowCase

LO = 1_104_000_000.0


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class TransmitterSettings(WindowCase):
    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=1_296_200_000).start()
        self.addCleanup(self.civ.stop)

    def dialog(self, **over):
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(**over)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Transmitter"))
        self.addCleanup(d.close)
        return d, radio

    def test_no_upconverter_is_chosen_at_first_and_the_address_is_in_hex(self):
        d, _ = self.dialog()
        self.assertEqual(d.conv_combos["rigTxConverter"].currentData(), "")
        self.assertEqual(d.fields["civAddress"].w.text(), "A2")
        self.assertEqual(d.fields["civAddress"].get(), 0xA2)

    def test_test_connection_reads_the_radio_with_the_settings_as_typed(self):
        d, _ = self.dialog()
        d.fields["txRadio"].w.set_value("civ")
        d.fields["civPort"].w.setText(self.civ.url)
        d.test_rig()
        self.assertIn("1296.200000 MHz", d.rig_result.text())
        self.assertEqual(self.civ.received, [bytes([0x03])])
        d.fields["civPort"].w.setText(f"socket://127.0.0.1:{free_port()}")
        d.test_rig()
        self.assertIn("Could not connect", d.rig_result.text())
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_saving_the_9700_without_an_lo_is_refused_and_says_why(self):
        d, radio = self.dialog()
        d.fields["txRadio"].w.set_value("civ")
        d.fields["civPort"].w.setText(self.civ.url)
        d.save()
        self.assertIn("local oscillator", d.error.text())
        self.assertEqual(radio.state()["txRadio"], "sdr")
        d.conv_editor.add_pack("qo100")
        cb = d.conv_combos["rigTxConverter"]
        cb.setCurrentIndex(cb.findData("QO-100 uplink: 1296 MHz IF (LO 1104)"))
        d.save()
        self.assertEqual(radio.state()["txRadio"], "civ")
        self.assertEqual(radio.state()["rigTxConverter"], "QO-100 uplink: 1296 MHz IF (LO 1104)")


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class TransmitCard(WindowCase):
    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=1_296_190_000).start()
        self.addCleanup(self.civ.stop)

    def tearDown(self):
        self.assertEqual(self.civ.ptt_commands(), [])
        super().tearDown()

    def test_the_card_shows_the_radio_its_transmissions_and_where_it_is_aimed(self):
        win, bridge, radio = self.window(txRadio="civ", civPort=self.civ.url, **rig_conv(LO), rigPollMs=50)
        card = win.txcard
        self.assertTrue(self.run_for(radio, until=lambda: "1296.200000" in card.rig.text(), timeout=10))
        self.assertFalse(card.power.isVisible())
        self.assertIn("RX", card.rig.text())
        self.assertIn("9700", win.readout.bridge.face.secondary(bridge.st)[0])
        self.civ.key(True)
        self.assertTrue(self.run_for(radio, until=lambda: card.rig.text().endswith("TX"), timeout=5))
        self.civ.key(False)
        self.assertTrue(self.run_for(radio, until=lambda: card.rig.text().endswith("RX"), timeout=5))
        # Aimed into the middle beacon: the card says so, and says it is advice.
        self.civ.turn(int(bandplan.ul(10_489_748_000.0) - LO))
        self.assertTrue(self.run_for(radio, until=lambda: card.rig_warn.isVisible(), timeout=5))
        self.assertIn("beacon", card.rig_warn.text())
        self.assertIn("cannot stop the radio transmitting", card.rig_warn.text())
        # NB's own PTT stays off the air.
        QTest.mousePress(win.ptt, Qt.MouseButton.LeftButton)
        self.run_for(radio, 0.3)
        self.assertFalse(radio.state()["keyed"])
        QTest.mouseRelease(win.ptt, Qt.MouseButton.LeftButton)
        self.assertFalse(radio.dev.tx_active)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class CatPttWindow(WindowCase):
    """CAT PTT for digital modes (12/10/2026): the Transmitter page in both
    states, and the FT8 panel's Enable TX switched off mid-over."""

    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=int(bandplan.ul(10_489_540_000.0) - LO)).start()
        self.addCleanup(self.civ.stop)

    def test_the_transmitter_page_says_what_nb_does_in_each_state_and_keeps_the_device(self):
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(rigTxAudioOut="IC-9700 USB CODEC")
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Transmitter"))
        self.addCleanup(d.close)
        self.assertIn("never keys the IC-9700", d.keys_note.text())
        QTest.mouseClick(d.fields["rigCatPtt"].w, Qt.MouseButton.LeftButton)
        self.assertIn("keys the IC-9700 by CAT for its own digital-mode overs", d.keys_note.text())
        self.assertIn("For voice you still key the radio yourself", d.keys_note.text())
        # A device not plugged in now is kept, and said to be missing.
        self.assertEqual(d.rig_audio.currentData(), "IC-9700 USB CODEC")
        self.assertIn("not connected", d.rig_audio.currentText())
        d.save()
        self.assertTrue(radio.state()["rigCatPtt"])
        self.assertEqual(radio.state()["rigTxAudioOut"], "IC-9700 USB CODEC")
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_enable_tx_off_mid_over_unkeys_the_9700(self):
        import numpy as np
        from unittest import mock
        from ohscore.ui.panels.ft8 import Ft8Panel
        p = mock.patch("ohscore.engine.slot_start", lambda now, mode, period=None: now)
        p.start()
        self.addCleanup(p.stop)
        win, bridge, radio = self.window(txRadio="civ", civPort=self.civ.url, **rig_conv(LO), rigPollMs=50,
                                         mode="ft8", vfo=10_489_540_000.0, callsign="GM4BRI", licenceClass="full",
                                         rigCatPtt=True, rigTxAudioOut="IC-9700 USB CODEC")
        radio.audio.realtime = True          # the over takes its real length
        radio._render = lambda mode, msg: (0.5 * np.sin(2 * np.pi * 1500 * np.arange(8 * 12000) / 12000)
                                           ).astype(np.float32)
        self.assertTrue(self.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5))
        self.assertTrue(self.run_for(radio, until=lambda: self.civ.data and radio.ext.link.mod_input,
                                     timeout=10))
        panel = win.panel
        # The over is the test's own send. The panel's scheduler would also
        # try to start one whenever the wall clock is inside its slot's
        # window, be refused while this one is on the air, and switch Enable
        # TX off itself (the safe answer) - so the click below turned it back
        # ON and the test failed about two runs in five, by the time of day.
        quiet = mock.patch.object(panel, "tick", lambda dt: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        panel.set_tx_enabled(True)
        radio.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.run_for(radio, until=lambda: self.civ.tx, timeout=5))
        # The window has heard it is on the air (its state arrives by feed).
        self.assertTrue(self.run_for(radio, until=lambda: panel.st("keyed"), timeout=2))
        QTest.mouseClick(panel.enable, Qt.MouseButton.LeftButton)          # Enable TX off
        self.assertFalse(panel.tx_enabled)
        self.assertTrue(self.run_for(radio, until=lambda: not self.civ.tx, timeout=2))
        self.assertEqual(self.civ.ptt_commands(), [bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])])


def on_air_view(win) -> dict:
    """What the window shows about transmitting, read from its widgets."""
    label, sub = win.ptt.caption()
    return {"button": label, "sub": sub, "frame": win.glow.on, "header": "on air" in win.readout.title()}


def watch(case, win, radio, until, timeout):
    """Run the window until `until()`, sampling what it shows and the state
    it was showing, after every pass of the event loop."""
    seen = []

    def probe():
        st = dict(win.bridge.st)
        seen.append((on_air_view(win), st))
        return until()
    case.assertTrue(case.run_for(radio, until=probe, timeout=timeout))
    return seen


def armed_session(case, win, radio, start_in=1.5, tone_s=1.5):
    """One FT8 over sent with Enable TX on, due `start_in` s from now: the
    wait an FT8 over has for its slot, made short. The panel's own scheduler
    is held still (test_enable_tx_off_mid_over_unkeys_the_9700 says why)."""
    import numpy as np
    from unittest import mock
    from ohscore.ui.panels.ft8 import Ft8Panel
    p = mock.patch("ohscore.engine.slot_start", lambda now, mode, period=None: now + start_in)
    p.start()
    case.addCleanup(p.stop)
    radio.audio.realtime = True          # the over takes its real length
    radio._render = lambda mode, msg: (0.5 * np.sin(2 * np.pi * 1500 * np.arange(int(tone_s * 12000)) / 12000)
                                       ).astype(np.float32)
    case.assertTrue(case.run_for(radio, until=lambda: isinstance(win.panel, Ft8Panel), timeout=5))
    panel = win.panel
    quiet = mock.patch.object(panel, "tick", lambda dt: None)
    quiet.start()
    case.addCleanup(quiet.stop)
    panel.set_tx_enabled(True)
    return panel


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class OnAirFollowsTheOver(WindowCase):
    """ON AIR - the red frame, the big button, the downlink header's
    "● on air" - says the transmitter is radiating, nothing else (Ray,
    12/10/2026: with Enable TX on it showed through every receive slot
    while his IC-9700 sat in RX). Between overs the button reads ARMED,
    with when the next goes, and pressing it or Escape stops everything."""

    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=int(bandplan.ul(10_489_540_000.0) - LO)).start()
        self.addCleanup(self.civ.stop)

    def assert_session(self, seen, radiating):
        """Every sample: the frame and header showed on air exactly when
        `radiating(state)` said so, and the button never said ON AIR
        otherwise. And the session had both an armed wait and an over."""
        for view, st in seen:
            self.assertEqual(view["frame"], radiating(st), (view, st.get("keyed"), st.get("rigKeyed")))
            self.assertEqual(view["header"], radiating(st))
            if view["button"] == "ON AIR":
                self.assertTrue(radiating(st))
        waits = [v for v, st in seen if st.get("keyed") and not radiating(st)]
        self.assertTrue(waits, "never saw the over waiting for its slot")
        self.assertTrue(all(v["button"] == "ARMED" and not v["frame"] for v in waits))
        self.assertTrue(any(v["sub"].startswith("next over in") for v in waits))
        self.assertTrue(any(v["button"] == "ON AIR" for v, _st in seen), "never saw the over on the air")

    def test_cat_ptt_on_air_only_while_the_9700_is_keyed_and_armed_between_overs(self):
        win, bridge, radio = self.window(txRadio="civ", civPort=self.civ.url, **rig_conv(LO), rigPollMs=50,
                                         mode="ft8", vfo=10_489_540_000.0, callsign="GM4BRI", licenceClass="full",
                                         rigCatPtt=True, rigTxAudioOut="IC-9700 USB CODEC")
        panel = armed_session(self, win, radio)
        self.assertTrue(self.run_for(radio, until=lambda: self.civ.data and radio.ext.link.mod_input,
                                     timeout=10))
        # Enable TX on, nothing queued yet: armed, the radio untouched.
        self.assertTrue(self.run_for(radio, until=lambda: on_air_view(win)["button"] == "ARMED", timeout=3))
        self.assertFalse(on_air_view(win)["frame"])
        radio.send("ft8", text="CQ GM4BRI IO75")
        seen = watch(self, win, radio, timeout=15,
                     until=lambda: self.civ.ptt_commands()[-1:] == [bytes([0x1C, 0x00, 0x00])]
                     and not bridge.st.get("rigKeyed") and not bridge.st.get("keyed"))
        # rigKeyed is the radio's own word, read back from it.
        self.assert_session(seen, lambda st: bool(st.get("rigKeyed")))
        # The radio really was keyed for the over, and only once.
        self.assertEqual(self.civ.ptt_commands(), [bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])])
        # Between overs, Enable TX still on: ARMED, counting to our next slot.
        win._sync_ptt()
        view = on_air_view(win)
        self.assertEqual((view["button"], view["frame"], view["header"]), ("ARMED", False, False))
        self.assertTrue(view["sub"].startswith("next over in"))
        # Escape while armed is Halt: Enable TX off, and nothing keys.
        QTest.keyClick(win.readout, Qt.Key.Key_Escape)
        self.assertFalse(panel.tx_enabled)
        win._sync_ptt()
        self.assertNotEqual(on_air_view(win)["button"], "ARMED")
        self.assertEqual(len(self.civ.ptt_commands()), 2)

    def test_pressing_the_armed_button_halts_a_queued_over_before_it_keys(self):
        win, bridge, radio = self.window(txRadio="civ", civPort=self.civ.url, **rig_conv(LO), rigPollMs=50,
                                         mode="ft8", vfo=10_489_540_000.0, callsign="GM4BRI", licenceClass="full",
                                         rigCatPtt=True, rigTxAudioOut="IC-9700 USB CODEC")
        panel = armed_session(self, win, radio, start_in=4.0)
        self.assertTrue(self.run_for(radio, until=lambda: self.civ.data and radio.ext.link.mod_input,
                                     timeout=10))
        radio.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.run_for(radio, until=lambda: bridge.st.get("keyed"), timeout=2))
        self.assertEqual(on_air_view(win)["button"], "ARMED")
        QTest.mouseClick(win.ptt, Qt.MouseButton.LeftButton)
        self.assertFalse(panel.tx_enabled)
        self.assertTrue(self.run_for(radio, until=lambda: not radio.state()["keyed"], timeout=2))
        self.run_for(radio, sim_s=0.0, until=lambda: False, timeout=4.5)    # past when it was due
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_pluto_on_air_only_while_the_over_is_up_and_armed_while_it_waits(self):
        # The Pluto (here the simulator) is keyed by NB itself, at the
        # slot: the same wait, and the same rule - txOnAir, not keyed.
        win, bridge, radio = self.window(mode="ft8", vfo=10_489_540_000.0, callsign="GM4BRI", licenceClass="full")
        armed_session(self, win, radio)
        self.assertTrue(radio.state()["canTx"])
        self.assertTrue(bridge.send("ft8", text="CQ GM4BRI IO75"))
        went = []

        def done():
            went.append(bool(bridge.st.get("txOnAir")))
            return any(went) and not bridge.st.get("keyed")
        seen = watch(self, win, radio, timeout=15, until=done)
        self.assert_session(seen, lambda st: bool(st.get("keyed") and st.get("txOnAir")))


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class SetupAssistantWindow(WindowCase):
    """Settings > Transmitter > IC-9700 setup (ohsnb/ui/rigsetup.py): nothing
    on opening, Find filling the Settings fields, Check / Apply / Restore,
    and the level set's button held back until the dummy-load tick."""

    def setUp(self):
        super().setUp()
        self.civ = CivSim(address=0x94, freq=145_500_000).start()
        self.addCleanup(self.civ.stop)

    def tearDown(self):
        self.assertEqual(self.civ.ptt_commands(), [])
        super().tearDown()

    def assistant(self, **over):
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(**over)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Transmitter"))
        self.addCleanup(d.close)
        # Typed, not saved: the assistant works with the port as the page has it.
        d.fields["civPort"].w.setText(self.civ.url)
        a = d.open_rig_setup()
        self.addCleanup(a.close)
        return d, a, radio

    def finish(self, a, radio):
        self.assertTrue(self.run_for(radio, until=lambda: not a.busy, timeout=30))

    def test_opening_it_sends_nothing_and_find_fills_the_settings_in(self):
        from unittest import mock
        from ohsnb.rigsetup import RigSetup
        d, a, radio = self.assistant()
        self.run_for(radio, 0.3)
        self.assertEqual(self.civ.received, [])
        self.assertFalse(a.level_btn.isEnabled())
        with mock.patch.object(RigSetup, "outputs", lambda _s: ["Speakers (Realtek(R) Audio)",
                                                                "Speakers (2- USB Audio CODEC )"]):
            a.find()
            self.finish(a, radio)
        self.assertEqual(d.fields["civAddress"].w.text(), "94")
        self.assertEqual(d.rig_audio.currentData(), "Speakers (2- USB Audio CODEC )")
        self.assertIn("94h", a.find_out.text())
        self.assertEqual(set(self.civ.received), {bytes([0x19, 0x00])})
        d.save()
        self.assertEqual(radio.state()["civAddress"], 0x94)
        self.assertEqual(radio.state()["rigTxAudioOut"], "Speakers (2- USB Audio CODEC )")

    def test_two_codecs_and_nothing_to_tell_them_apart_chooses_neither(self):
        """Ray's PC (12/10/2026): two radios, two USB Audio CODECs; NB's
        name match chose the other radio's. Now it chooses none and says
        what to do."""
        from unittest import mock
        from ohsnb.rigsetup import RigSetup
        d, a, radio = self.assistant()
        before = d.rig_audio.currentData()
        names = ["Speakers / Headphones (Realtek ", "Speakers (2- USB AUDIO  CODEC)", "IC9700 Speakers (USB Audio CODE"]
        with mock.patch.object(RigSetup, "outputs", lambda _s: names):
            a.find()
            self.finish(a, radio)
        self.assertEqual(d.rig_audio.currentData(), before)
        self.assertIn("2 USB Audio CODEC sound devices", a.find_out.text())
        self.assertIn("chosen none", a.find_out.text())
        self.assertIn("Which sound device?", a.find_out.text())
        self.assertEqual(d.fields["civAddress"].w.text(), "94")

    def test_check_apply_and_restore(self):
        d, a, radio = self.assistant()
        d.fields["civAddress"].w.setText("94")
        self.civ.satellite, self.civ.mod_data = True, "mic"
        a.check()
        self.finish(a, radio)
        self.assertEqual(set(a.ticks), {"dataMod", "usbMod", "satellite", "band", "selected"})
        self.assertTrue(a.ticks["satellite"].isChecked())
        self.assertFalse(a.ticks["usbMod"].isEnabled())           # 50 %: left alone
        self.assertEqual(self.civ.menu_writes, [])
        a.ticks["dataMod"].setChecked(False)                        # leave DATA MOD as it is
        asked = []
        a._confirm = lambda title, text: asked.append(text) or True
        a.apply()
        self.finish(a, radio)
        self.assertIn("Satellite mode: on → off", asked[0])
        self.assertNotIn("DATA MOD", asked[0])
        self.assertFalse(self.civ.satellite)
        self.assertEqual(self.civ.mod_data, "mic")
        self.assertEqual(self.civ.menu_writes, [])                  # satellite mode is not a menu item
        self.assertIn("Satellite mode off", a.check_out.text())
        self.assertTrue(a.restore_btn.isEnabled())
        a.restore()
        self.finish(a, radio)
        self.assertTrue(self.civ.satellite)
        self.assertEqual(radio.state()["rigSetupSaved"], {})
        self.assertFalse(a.restore_btn.isEnabled())

    def test_the_level_set_waits_for_the_dummy_load_tick(self):
        d, a, radio = self.assistant()
        self.assertFalse(a.level_btn.isEnabled())
        a.level()                                                  # not ticked: nothing at all
        self.run_for(radio, 0.2)
        self.assertFalse(a.busy)
        a.dummy.setChecked(True)
        # Ticked, but the 9700 is not saved as the transmitter: said why,
        # above a button that stays off.
        self.assertFalse(a.level_btn.isEnabled())
        self.assertIn("Save Settings", a.needs_out.text())
        self.assertEqual(self.civ.received, [])

    def test_cat_ptt_off_and_no_digital_mode_are_put_right_from_the_assistant(self):
        """Until 12/10/2026 step 3 only said, in red, that CAT PTT was off
        or no digital mode chosen. Now it offers to put both right."""
        d, a, radio = self.assistant(txRadio="civ", civPort=self.civ.url, civAddress=0x94, **rig_conv(LO),
                                     mode="usb")
        self.assertEqual(radio.ext.kind, "civ")
        a.dummy.setChecked(True)
        self.assertFalse(a.level_btn.isEnabled())
        self.assertFalse(a.cat_btn.isHidden())
        self.assertFalse(a.ft8_btn.isHidden())
        self.assertIn("'Key the IC-9700 for digital modes' is off", a.needs_out.text())
        # Find filled the sound device in, unsaved: turning CAT PTT on saves it too.
        a.settings.rig_audio.addItem("Speakers (2- USB Audio CODEC )", "Speakers (2- USB Audio CODEC )")
        a.settings.rig_audio.setCurrentIndex(a.settings.rig_audio.count() - 1)
        asked = []
        a._confirm = lambda title, text: asked.append(text) or False
        a.cat_on()                                                 # declined: nothing changes
        self.assertFalse(radio.state()["rigCatPtt"])
        self.assertIn("Never for voice", asked[0])
        self.assertIn("USB Audio CODEC", asked[0])
        a._confirm = lambda title, text: True
        a.cat_on()
        self.assertTrue(radio.state()["rigCatPtt"])
        self.assertEqual(radio.state()["rigTxAudioOut"], "Speakers (2- USB Audio CODEC )")
        self.assertTrue(d.fields["rigCatPtt"].get())               # the Settings dialog will not save it off
        self.assertTrue(a.cat_btn.isHidden())
        a.choose_ft8()
        self.assertEqual(radio.state()["mode"], "ft8")
        self.assertTrue(a.needs_out.isHidden())
        self.assertTrue(a.level_btn.isEnabled())
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_readings_are_listed_when_no_level_was_set(self):
        d, a, radio = self.assistant()
        result = {"result": "advice", "text": "The IC-9700's power was already flat.", "usbMod": 128, "rfPower": 13,
                  "steps": [{"level": -40.0, "po": 20, "alc": 72}, {"level": -34.0, "po": 21, "alc": 152}]}
        a._done("level", result, None)
        text = a.level_out.text()
        self.assertIn("USB MOD Level 50 %, RF POWER 5 %", text)
        self.assertIn("-40 dB: Po 20, ALC 72", text)
        self.assertIn("-34 dB: Po 21, ALC 152", text)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class DiagnosticWindow(WindowCase):
    """Settings > Transmitter > IC-9700 diagnostic (ohsnb/ui/rigdiag.py):
    nothing on opening, the reads into the report, Copy and Save, and the
    keyed checks held back by the tick and then by a confirmation naming
    the band and power."""

    def setUp(self):
        super().setUp()
        self.civ = CivSim(freq=1_296_200_000).start()
        self.addCleanup(self.civ.stop)

    def tearDown(self):
        self.assertEqual(self.civ.ptt_commands(), [])
        super().tearDown()

    def window_of(self, **over):
        from ohsnb.ui.settings import SettingsDialog
        win, bridge, radio = self.window(**over)
        titles = [t for _i, t, _b in SettingsDialog.PAGES]
        d = SettingsDialog(bridge, win.prefs, win, page=titles.index("Transmitter"))
        self.addCleanup(d.close)
        d.fields["civPort"].w.setText(self.civ.url)
        w = d.open_rig_diagnostic()
        self.addCleanup(w.close)
        return d, w, radio

    def finish(self, w, radio):
        self.assertTrue(self.run_for(radio, until=lambda: not w.busy, timeout=40))

    def test_reads_then_copy_and_save(self):
        from unittest import mock
        from ohsnb import rigdiag
        d, w, radio = self.window_of()
        self.run_for(radio, 0.3)
        self.assertEqual(self.civ.received, [])
        self.assertFalse(w.keyed_btn.isEnabled())
        self.assertFalse(w.copy_btn.isEnabled())
        with mock.patch.object(rigdiag, "list_ports", lambda: []):
            w.run_reads()
            self.finish(w, radio)
        self.assertIn("answers at A2h", w.text.toPlainText())
        self.assertIn("RF POWER (14 0A): 255 (100 %)", w.text.toPlainText())
        w.copy()
        from PyQt6.QtGui import QGuiApplication
        self.assertIn("IC-9700 diagnostic", QGuiApplication.clipboard().text())
        path = Path(self.tmp) / "report.txt"
        w.save(str(path))
        self.assertEqual(path.read_text(encoding="utf-8"), w.report())
        self.assertNotIn("GM4BRI", w.report())
        self.assertEqual(self.civ.menu_writes, [])

    def test_keyed_needs_the_tick_then_a_confirmation_naming_band_and_power(self):
        d, w, radio = self.window_of(txRadio="civ", civPort=self.civ.url, **rig_conv(LO), mode="ft8",
                                     rigCatPtt=True, rigTxAudioOut="IC-9700 USB Audio CODEC", rigPollMs=50)
        self.assertTrue(self.run_for(radio, until=lambda: radio.state()["rigLink"] == "ok", timeout=10))
        self.assertFalse(w.keyed_btn.isEnabled())
        w.run_keyed()                                              # not ticked: nothing at all
        self.assertFalse(w.busy)
        w.dummy.setChecked(True)
        self.assertTrue(w.keyed_btn.isEnabled())
        asked = []
        w._confirm = lambda title, text: asked.append(text) or False
        w.run_keyed()
        self.finish(w, radio)
        self.assertEqual(len(asked), 1)
        self.assertIn("23 cm", asked[0])
        self.assertIn("RF POWER 100 %, about 10.0 W", asked[0])
        self.assertIn("dummy load", asked[0])
        self.assertIn("not run", w.state.text())


if __name__ == "__main__":
    unittest.main()
