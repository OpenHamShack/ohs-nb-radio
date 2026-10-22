"""The IC-9700 setup assistant (ohsnb/rigsetup.py), end to end: the real
Radio on the simulated transponder, the real CI-V driver over TCP to the
emulated radio (ohscore/rig/civsim.py), the level set's tone to a NullAudio
sound device whose latest level the emulator's modulator model hears.
Finding the radio, the check and its plan, apply then restore back to the
very values the radio had, a refusal while it transmits, the level set
converging, Halt ending it, and the menu writes refused to anything but
the confirmed apply. No serial port, sound card or radio is opened.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from helpers import rig_conv, sim_cfg
from ohscore.audio import NullAudio
from ohscore.converters import Converter
from ohscore.engine import TxRefused
from ohscore.rig import ForbiddenCommand, RigError, civ
from ohscore.rig.civsim import CivSim
from ohsnb import bandplan, rigsetup
from ohsnb.devices.sim import SimDevice
from ohsnb.extrig import UplinkPlan
from ohsnb.radio import Radio
from ohsnb.rigsetup import RigSetup, find_codec

LO = 1_104_000_000.0
FT8_DIAL = 10_489_540_000.0
DEVICE = "IC-9700 USB Audio CODEC"
ON, OFF = bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])
TWO_M = 145_500_000


def wait_for(cond, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Codec(unittest.TestCase):
    def test_the_9700s_sound_device_is_found_by_name_on_each_system(self):
        windows = ["Microsoft Sound Mapper - Output", "Speakers (Realtek(R) Audio)", "Speakers (2- USB Audio CODEC )"]
        linux = ["HDA Intel PCH: ALC257 Analog (hw:0,0)", "pulse", "default", "USB Audio CODEC: - (hw:2,0)"]
        mac = ["MacBook Air Speakers", "USB AUDIO  CODEC"]
        self.assertEqual(find_codec(windows), ["Speakers (2- USB Audio CODEC )"])
        self.assertEqual(find_codec(linux), ["USB Audio CODEC: - (hw:2,0)"])
        self.assertEqual(find_codec(mac), ["USB AUDIO  CODEC"])
        self.assertEqual(find_codec(["Speakers (Realtek(R) Audio)"]), [])
        # Ray's PC (12/10/2026): two radios, and the 9700's renamed, so MME
        # cut it at 31 characters, inside "CODEC". Both are found; which is
        # the radio's is not a question of names (detect, usbpair).
        ray = ["Speakers / Headphones (Realtek ", "Speakers (2- USB AUDIO  CODEC)", "IC9700 Speakers (USB Audio CODE",
               "CABLE Input (VB-Audio Virtual C"]
        self.assertEqual(find_codec(ray), ["Speakers (2- USB AUDIO  CODEC)", "IC9700 Speakers (USB Audio CODE"])
        # Two on Linux (the raw device and a server's name for it): hw first.
        self.assertEqual(find_codec(["USB Audio CODEC Analog Stereo", "USB Audio CODEC: - (hw:2,0)"])[0],
                         "USB Audio CODEC: - (hw:2,0)")


class Base(unittest.TestCase):
    link = "civ"           # "sdr": NB has no link running, the assistant is alone on the port

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plan = UplinkPlan(Converter.from_dict(rig_conv(LO)["converters"][-1]))
        self.start_if = int(self.plan.rig_hz(bandplan.ul(FT8_DIAL)))
        self.civ = CivSim(freq=self.start_if).start()
        self.addCleanup(self.civ.stop)
        cfg = sim_cfg(txRadio=self.link, **rig_conv(LO), vfo=FT8_DIAL, mode="usb", simRealtime=True, rigPollMs=50,
                      callsign="GM4BRI", licenceClass="full", watchdogSec=10.0, rigCatPtt=True,
                      rigTxAudioOut=DEVICE, rigPttDelayMs=100, rigPttTailMs=50, civPort=self.civ.url)
        self.audio = NullAudio(realtime=True)
        self.r = Radio(cfg, persist=False, data_dir=self.tmp, audio=self.audio, device=SimDevice(dict(cfg)))
        self.r.start()
        self.addCleanup(self.r.stop)

    def settled(self):
        def ok():
            s = self.r.state()
            want = int(round(self.plan.rig_hz(bandplan.ul(s["txDial"]) + s["rigTxCorr"])))
            return s["rigLink"] == "ok" and self.civ.freq == want
        return wait_for(ok)

    def radio_as_found(self):
        """Ray's radio before the assistant: everything the check looks at
        wrong - 2 m on MAIN, 23 cm on SUB and selected, satellite mode on,
        DATA MOD from the microphone, USB MOD Level near the bottom."""
        c = self.civ
        with c.lock:
            c.freq, c.sub_freq, c.selected = TWO_M, self.start_if, "sub"
            c.satellite, c.mod_data, c.usb_mod = True, "mic", 10

    def snapshot(self):
        c = self.civ
        with c.lock:
            return {"mod_data": c.mod_data, "mod_plain": c.mod_plain, "usb_mod": c.usb_mod, "satellite": c.satellite,
                    "selected": c.selected, "main_band": rigsetup._band_of(c.freq),
                    "sub_band": rigsetup._band_of(c.sub_freq), "main": c.freq, "sub": c.sub_freq}


class Detect(Base):
    link = "sdr"

    def test_finds_the_address_and_the_sound_device_reading_only(self):
        self.civ.stop()
        self.civ = CivSim(address=0x94).start()
        self.addCleanup(self.civ.stop)
        s = RigSetup(self.r, {"civPort": self.civ.url})
        with mock.patch.object(RigSetup, "outputs", lambda _self: ["Speakers (Realtek(R) Audio)",
                                                                   "Speakers (2- USB Audio CODEC )"]):
            found = s.detect()
        # One CODEC is the radio's whatever its name; the baud rate is the one it answered at.
        codec = "Speakers (2- USB Audio CODEC )"
        self.assertEqual(found, {"address": 0x94, "id": 0x94, "baud": 115200, "audio": [codec], "pick": codec})
        self.assertEqual(set(self.civ.received), {bytes([0x19, 0x00])})

    def test_nothing_on_the_port_is_said_plainly(self):
        s = RigSetup(self.r, {"civPort": ""})
        with self.assertRaises(RigError):
            s.detect()


class CheckAndApply(Base):
    def test_the_check_reads_and_plans_and_changes_nothing(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        before = self.snapshot()
        s = RigSetup(self.r)
        reading = s.read()
        self.assertEqual({k: reading[k] for k in ("dataMod", "usbMod", "satellite", "selected", "tx")},
                         {"dataMod": "mic", "usbMod": 10, "satellite": True, "selected": "sub", "tx": False})
        rows = {row["key"]: row for row in s.plan(reading)}
        self.assertEqual((rows["dataMod"]["now"], rows["dataMod"]["will"]), ("MIC", "USB"))
        self.assertEqual((rows["usbMod"]["now"], rows["usbMod"]["will"]), ("4 %", "50 %"))
        self.assertEqual(rows["satellite"]["writes"], [bytes([0x16, 0x5A, 0x00])])
        self.assertEqual(rows["band"]["writes"], [bytes([0x07, 0xB0])])
        self.assertEqual(rows["selected"]["writes"], [bytes([0x07, 0xD0])])
        self.assertEqual(self.civ.menu_writes, [])
        self.assertEqual(self.snapshot()["satellite"], before["satellite"])
        self.assertEqual(self.civ.ptt_commands(), [])
        # The link was paused for the read and is polling again.
        n = len(self.civ.received)
        self.assertTrue(wait_for(lambda: len(self.civ.received) > n + 3 and self.r.state()["rigLink"] == "ok"))
        self.assertFalse(self.r.rig_setup_busy)

    def test_a_sane_radio_needs_nothing(self):
        self.assertTrue(self.settled())
        s = RigSetup(self.r)
        rows = s.plan(s.read())
        self.assertEqual([row["key"] for row in rows if row["writes"]], [])
        self.assertIn("Nothing to change", s.apply(rows)[0])
        self.assertEqual(self.civ.menu_writes, [])

    def test_apply_then_restore_leaves_the_radio_as_it_was(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        before = self.snapshot()
        s = RigSetup(self.r)
        rows = s.plan(s.read())
        said = s.apply(rows)
        self.assertEqual(len(said), 5, said)
        after = self.snapshot()
        self.assertEqual((after["mod_data"], after["usb_mod"], after["satellite"], after["selected"],
                          after["main_band"], after["sub_band"]), ("usb", 128, False, "main", "23cm", "2m"))
        saved = self.r.state()["rigSetupSaved"]
        self.assertEqual({k: saved[k] for k in ("dataMod", "usbMod", "satellite", "selected", "exchanged")},
                         {"dataMod": "mic", "usbMod": 10, "satellite": True, "selected": "sub", "exchanged": True})
        # NB follows the radio again: the link is back and tuning 23 cm on MAIN.
        self.assertTrue(self.settled())
        # A second check finds nothing left to do, and a second apply saves nothing over the originals.
        self.assertEqual([row for row in s.plan(s.read()) if row["writes"]], [])
        s.restore()
        back = self.snapshot()
        for k in ("mod_data", "mod_plain", "usb_mod", "satellite", "selected", "main_band", "sub_band", "main"):
            self.assertEqual(back[k], before[k], k)
        self.assertEqual(self.r.state()["rigSetupSaved"], {})
        self.assertIn("Nothing to restore", s.restore()[0])
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_a_changed_radio_is_not_applied_from_an_old_check(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        s = RigSetup(self.r)
        rows = s.plan(s.read())
        self.civ.mod_data = "usb"                      # changed on the radio since
        with self.assertRaises(RigError) as cm:
            s.apply(rows)
        self.assertIn("check again", str(cm.exception))
        self.assertEqual(self.civ.menu_writes, [])

    def test_only_the_ticked_rows_are_applied(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        s = RigSetup(self.r)
        s.apply(s.plan(s.read()), keys={"dataMod"})
        self.assertEqual(self.civ.menu_writes, [bytes([0x1A, 0x05, 0x01, 0x16, 0x03])])
        self.assertTrue(self.civ.satellite)
        self.assertEqual(self.r.state()["rigSetupSaved"], {"dataMod": "mic", "port": self.civ.url})

    def test_nb_will_not_key_the_radio_while_the_assistant_has_it(self):
        self.assertTrue(self.settled())
        self.r.set(mode="cw")                          # a CW line: rendered here without an FT8 encoder
        self.assertTrue(wait_for(lambda: self.civ.data and self.r.ext.link.mod_input is not None))
        self.r.rig_setup_busy = True
        with self.assertRaises(TxRefused) as cm:
            self.r.send("cw", text="TEST")
        self.assertIn("setup assistant", str(cm.exception))
        self.r.rig_setup_busy = False
        self.assertEqual(self.civ.ptt_commands(), [])


class Exact(Base):
    """With no link running every value comes back exactly, frequencies
    included (with one, NB itself retunes 23 cm while it is on MAIN)."""
    link = "sdr"

    def test_restore_is_exact(self):
        self.radio_as_found()
        before = self.snapshot()
        s = RigSetup(self.r)
        s.apply(s.plan(s.read()))
        self.assertNotEqual(self.snapshot(), before)
        s.restore()
        self.assertEqual(self.snapshot(), before)


class WhileTransmitting(Base):
    def test_nothing_is_changed_while_the_radio_transmits(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        s = RigSetup(self.r)
        rows = s.plan(s.read())
        self.civ.key(True)                            # keyed by hand on the radio
        with self.assertRaises(RigError) as cm:
            s.apply(rows)
        self.assertIn("transmitting", str(cm.exception))
        self.assertEqual(self.civ.menu_writes, [])
        self.assertEqual(self.r.state()["rigSetupSaved"], {})
        self.civ.key(False)
        s.apply(rows, keys={"satellite"})
        self.civ.key(True)
        with self.assertRaises(RigError):
            s.restore()
        self.assertFalse(self.civ.satellite)            # not put back while it transmits
        self.civ.key(False)
        s.restore()
        self.assertTrue(self.civ.satellite)

    def test_nothing_starts_while_nb_transmits(self):
        self.r.st["keyed"] = True
        try:
            with self.assertRaises(RigError):
                RigSetup(self.r).read()
        finally:
            self.r.st["keyed"] = False
        self.assertNotIn(bytes([0x16, 0x5A]), self.civ.received)


class StrayWrites(Base):
    def test_the_assistants_permit_allows_nothing_outside_its_apply(self):
        self.assertTrue(self.settled())
        self.radio_as_found()
        s = RigSetup(self.r)
        s.apply(s.plan(s.read()), keys={"dataMod"})
        writes = list(self.civ.menu_writes)
        rig = civ.CivRig(self.civ.url)
        rig.open()
        self.addCleanup(rig.close)
        for body in (civ.set_data_mod("mic"), civ.set_usb_mod_level(255), civ.set_satellite(False),
                     civ.EXCHANGE_BANDS, bytes([0x14, 0x0A, 0x02, 0x55])):
            with self.assertRaises(ForbiddenCommand):
                rig.setup_write(body, s.permit)
        # Armed by another thread for a write: still nothing here.
        t = threading.Thread(target=lambda: s.permit.arm([civ.set_data_mod("mic")]))
        t.start()
        t.join()
        with self.assertRaises(ForbiddenCommand):
            rig.setup_write(civ.set_data_mod("mic"), s.permit)
        time.sleep(0.05)
        self.assertEqual(self.civ.menu_writes, writes)
        self.assertEqual(self.civ.mod_data, "usb")


class LevelSet(Base):
    # How long after it is played a sample reaches the radio, beyond NB's
    # own queue: the card's buffer (PortAudio's default low latency under
    # Windows MME, which PyAudio asks for, is 90 ms).
    card_s = 0.09

    def setUp(self):
        super().setUp()

        def drive():
            # The level reaching the radio's USB input now: the audio the
            # sound device is playing now - written card_s and NB's queue
            # ago - not the audio NB wrote last.
            outs = self.audio.tx_outs
            # Only this radio's own CODEC reaches its modulator.
            if not outs or outs[-1].closed_at is not None or outs[-1].device != DEVICE:
                return None
            at = time.monotonic() - self.card_s
            playing = [a for start, a in list(outs[-1].chunks) if start <= at]
            if not playing:
                return None
            peak = float(np.max(np.abs(playing[-1])))
            return 20 * np.log10(peak) if peak > 0 else None
        self.civ.drive = drive

    def ready(self):
        self.assertTrue(self.settled())
        self.r.set(mode="ft8")
        self.assertTrue(wait_for(lambda: self.civ.data and self.r.ext.link.mod_input is not None))
        self.r.set(rigTxAudioDb=-20.0)

    def levels(self, out):
        return [s["level"] for s in out["steps"]]

    def test_it_will_not_transmit_without_the_dummy_load_tick(self):
        self.ready()
        with self.assertRaises(RigError):
            RigSetup(self.r).level_set(False)
        with self.assertRaises(RigError):
            RigSetup(self.r).level_set("yes")
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_climbs_until_the_power_stops_rising_and_keeps_the_knee(self):
        self.ready()
        t0 = time.monotonic()
        with self.assertLogs("ohsnb.rigsetup", "INFO") as logs:
            out = RigSetup(self.r).level_set(True)
        took = time.monotonic() - t0
        self.assertEqual(out["result"], "set", out["text"])
        # The plain emulator: full power from -10.6 dB of NB's level on a
        # 0.9 tone at USB MOD 50 % (ALC_KNEE); -10 makes it all, -4 is flat.
        # ...and a probe half a step under -10, which makes too little.
        self.assertEqual(self.levels(out), [-40.0, -34.0, -28.0, -22.0, -16.0, -10.0, -4.0, -13.0])
        self.assertEqual(out["level"], -10.0)
        self.assertEqual(self.r.state()["rigTxAudioDb"], -10.0)
        self.assertIn("left as it is", out["text"])
        self.assertEqual((out["usbMod"], out["rfPower"]), (128, 255))
        self.assertLess(took, rigsetup.MAX_S + 1.0)
        self.assertTrue(wait_for(lambda: not self.civ.tx and not self.r.state()["keyed"], timeout=3))
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])
        # It went out as a CAT over does: to the 9700's sound device, in USB-D.
        self.assertEqual(self.audio.tx_outs[-1].device, DEVICE)
        self.assertTrue(self.civ.data)
        self.assertEqual(self.civ.menu_writes, [])
        # Every reading is in NB's log, so a remote operator can send it.
        for s in out["steps"]:
            self.assertTrue(any(f"{s['level']:.0f} dB: Po {s['po']}, ALC {s['alc']}" in line for line in logs.output),
                            s)
        self.assertTrue(any("RF POWER 100 %" in line for line in logs.output))

    def test_the_9700_as_measured_at_half_power(self):
        """Brian's 9700 on 2 m (civsim real_9700, RF POWER 50 %, the ALC
        reading with any audio): the first level set's criterion would have
        stopped at the bottom."""
        self.ready()
        self.civ.real_9700(rf_power=128, alc_any_audio=True)
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "set", out["text"])
        self.assertGreater(out["steps"][0]["alc"], 20)            # "the ALC moves" at -40 dB
        # Climb to flat (-16), then a probe half a step under -22.
        self.assertEqual(self.levels(out), [-40.0, -34.0, -28.0, -22.0, -16.0, -25.0])
        self.assertTrue(out["steps"][-1]["refine"])
        self.assertEqual(out["level"], -25.0)
        self.assertEqual(self.civ.rf_power, 128)
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])

    def test_rays_9700_on_23cm_keeps_the_knee_not_a_third_less_power(self):
        """Ray's 9700 measured (12/10/2026, 23 cm, RF POWER 59, dummy load):
        Po 14, 28, 49, 74, 75, 76 at -40 .. -20 dBFS, the ALC at its keyed
        5 until the knee. The standalone diagnostic kept 3 dB under the
        knee, Po 49 of 75; NB keeps the knee, where the ALC is just
        leaving 5."""
        self.ready()
        self.civ.real_9700(rf_power=59)
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "set", out["text"])
        self.assertEqual(self.levels(out), [-40.0, -34.0, -28.0, -22.0, -31.0])
        self.assertEqual(out["level"], -31.0)
        kept = out["steps"][-1]
        self.assertGreaterEqual(kept["po"], rigsetup.KNEE_FRAC * max(s["po"] for s in out["steps"]))
        self.assertLess(kept["alc"], 20)
        self.assertIn("the ALC read", out["text"])

    def test_rays_case_flat_from_the_bottom_is_said_and_his_level_kept(self):
        """RF POWER so low that the knee is under NB's range (the 9700 holds
        its power with the ALC; Brian's 2 m measurement at 5 %). The first
        level set said "the ALC moves even at -40 dB: use Check and set to
        put USB MOD at 50 %", which it was."""
        self.ready()
        self.civ.real_9700(rf_power=5)
        self.civ.meter_attack_s, self.civ.meter_release_s = 0.03, 1.0
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "advice", out["text"])
        self.assertEqual(self.levels(out), [-40.0, -34.0])
        self.assertIn("already flat", out["text"])
        self.assertIn("RF POWER is 2 %", out["text"])
        self.assertIn("turn RF POWER up to 50 %", out["text"])
        self.assertNotIn("Check and set", out["text"])
        self.assertEqual(self.r.state()["rigTxAudioDb"], -20.0)    # his level, kept
        self.assertEqual(self.civ.rf_power, 5)                       # read, never written
        self.assertIn(bytes([0x14, 0x0A]), self.civ.received)
        self.assertEqual(self.civ.menu_writes, [])
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])

    def test_a_po_drop_out_is_passed_over_not_taken_for_the_knee(self):
        self.ready()
        self.civ.real_9700(rf_power=128)

        def progress(step):
            if step["level"] == -40.0:
                self.civ.po_dropouts = [3, 3]          # both of the next step's reads
        out = RigSetup(self.r).level_set(True, progress=progress)
        self.assertEqual(out["result"], "set", out["text"])
        self.assertTrue(out["steps"][1]["dropout"])
        self.assertEqual(out["level"], -25.0)

    def test_the_alc_is_a_ceiling(self):
        self.ready()
        self.civ.real_9700(rf_power=128)
        self.civ.alc_offset = 110                       # the knee's level reads above the zone
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "set", out["text"])
        at = {s["level"]: s for s in out["steps"]}
        flat = max(s["po"] for s in out["steps"])
        full = [s for s in out["steps"] if s["po"] >= rigsetup.KNEE_FRAC * flat]
        # Every level making nearly full power read past the zone's top:
        # the one under the lowest of them is kept instead.
        self.assertTrue(all(s["alc"] > rigsetup.ALC_ZONE for s in full))
        self.assertLess(out["level"], min(s["level"] for s in full))
        self.assertLessEqual(at[out["level"]]["alc"], rigsetup.ALC_ZONE)

    def test_an_extreme_usb_mod_level_is_named_and_left_alone(self):
        self.ready()
        self.civ.usb_mod = 255                          # 100 %: NB's level is set lower, and the radio named
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "set", out["text"])
        self.assertIn("at an extreme", out["text"])
        self.assertEqual(self.civ.usb_mod, 255)
        self.assertEqual(self.civ.menu_writes, [])

    def hot(self):
        drive = self.civ.drive
        self.civ.drive = lambda: None if (d := drive()) is None else d + 40.0    # far too hot a path

    def test_too_hot_at_a_usual_usb_mod_level_says_turn_it_down_by_hand(self):
        self.ready()
        self.hot()
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "advice", out["text"])
        self.assertEqual(self.levels(out), [-40.0, -34.0])
        # 50 % is in the usual range, which Check and set leaves alone: the
        # first advice told Ray to "use Check and set to put it at 50 %".
        self.assertIn("turn it down on the radio", out["text"])
        self.assertNotIn("Check and set to put it", out["text"])
        self.assertEqual(self.r.state()["rigTxAudioDb"], -20.0)
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])

    def test_too_hot_at_a_high_usb_mod_level_offers_check_and_set(self):
        self.ready()
        self.hot()
        self.civ.usb_mod = 230                          # 90 %
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "advice", out["text"])
        self.assertIn("use Check and set to put it at 50 %", out["text"])

    # Ray's PC (12/10/2026): two radios, so two USB Audio CODECs, and the
    # name match took the other radio's.
    OTHER_CODEC = "Speakers (2- USB AUDIO  CODEC)"

    def second_radio(self):
        """The other radio on the PC: its own CI-V (never NB's link) and
        its own CODEC, which is all a tone into the wrong device reaches."""
        other = CivSim(freq=145_500_000).start()
        self.addCleanup(other.stop)
        return other

    def test_the_other_radios_codec_gives_no_power_and_says_so(self):
        self.ready()
        other = self.second_radio()
        self.r.set(authorise=True, rigTxAudioOut=self.OTHER_CODEC)
        out = RigSetup(self.r).level_set(True)
        self.assertEqual(out["result"], "advice", out["text"])
        self.assertTrue(out["noAudio"])
        self.assertEqual(max(s["po"] for s in out["steps"]), 0)
        self.assertEqual(out["steps"][-1]["level"], 0.0)            # up to the top: not a level problem
        self.assertIn("audio is not reaching it", out["text"])
        self.assertIn(self.OTHER_CODEC, out["text"])
        self.assertEqual(self.r.state()["rigTxAudioDb"], -20.0)
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])
        self.assertEqual(other.received, [])                         # the other radio was never touched

    def test_which_codec_finds_the_radios_by_its_power(self):
        self.ready()
        self.second_radio()
        self.r.set(authorise=True, rigTxAudioOut=self.OTHER_CODEC)
        with self.assertRaises(RigError):
            RigSetup(self.r).which_codec(False, [self.OTHER_CODEC, DEVICE])
        self.assertEqual(self.civ.ptt_commands(), [])
        out = RigSetup(self.r).which_codec(True, [self.OTHER_CODEC, DEVICE])
        self.assertEqual(out["radio"], DEVICE)
        self.assertEqual(out["po"][self.OTHER_CODEC], 0)
        self.assertGreater(out["po"][DEVICE], rigsetup.PO_NONE)
        self.assertEqual([o.device for o in self.audio.tx_outs[-2:]], [self.OTHER_CODEC, DEVICE])
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF, ON, OFF])
        self.assertEqual(self.r.state()["rigTxAudioOut"], self.OTHER_CODEC)   # chosen by the window, saved by you
        self.assertEqual(self.civ.menu_writes, [])

    def test_find_with_two_codecs_chooses_none_unless_usb_says(self):
        self.assertTrue(self.settled())
        names = ["Speakers / Headphones (Realtek ", self.OTHER_CODEC, "IC9700 Speakers (USB Audio CODE"]
        with mock.patch.object(RigSetup, "outputs", lambda _s: names):
            out = RigSetup(self.r).detect()
            self.assertEqual(out["audio"], [self.OTHER_CODEC, "IC9700 Speakers (USB Audio CODE"])
            self.assertIsNone(out["pick"])                           # a socket port has no USB place
            with mock.patch.object(rigsetup.usbpair, "radio_codec", lambda port, codecs: codecs[1]):
                self.assertEqual(RigSetup(self.r).detect()["pick"], "IC9700 Speakers (USB Audio CODE")
        self.assertEqual((out["address"], out["baud"]), (0xA2, 115200))

    def test_halt_ends_it_at_once_and_stores_nothing(self):
        self.ready()
        steps = []

        def progress(step):
            steps.append(step)
            if len(steps) == 2:
                self.r.halt()
        t0 = time.monotonic()
        out = RigSetup(self.r).level_set(True, progress=progress)
        self.assertEqual(out["result"], "aborted")
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertEqual(self.r.state()["rigTxAudioDb"], -20.0)
        self.assertTrue(wait_for(lambda: not self.civ.tx, timeout=2))
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF])

    def test_a_voice_mode_is_refused_before_anything_is_keyed(self):
        self.assertTrue(self.settled())
        with self.assertRaises(RigError) as cm:
            RigSetup(self.r).level_set(True)
        self.assertIn("digital mode", str(cm.exception))
        self.assertEqual(self.civ.ptt_commands(), [])


if __name__ == "__main__":
    unittest.main()
