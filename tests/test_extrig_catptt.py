"""CAT PTT for digital modes (ohsnb/extrig.py CatPtt, Brian 12/10/2026):
NB keys an IC-9700 for its own digital overs, end to end - the real
Radio on the simulated transponder, the real CI-V (or rigctld) driver
over TCP to the emulated radio, the over's audio to a NullAudio sound
device that keeps it with its play times. The emulators log every PTT
command with the time it was obeyed, so the order "key, delay, audio,
tail, unkey" is measured on one clock, not inferred.

FT8's encoder (ohsdigi) is not built everywhere the suite runs, so an FT8
over here is a 1500 Hz tone of the length the test wants, rendered in
place of the message; everything after the rendering is the real path.
No serial port, sound card or radio is opened.
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
from ohscore.audio import RATE, NullAudio
from ohscore.converters import Converter
from ohscore.engine import TxRefused
from ohscore.rig import ForbiddenCommand
from ohscore.rig.civsim import CivSim
from ohscore.rig.rigctlsim import RigctldSim
from ohsnb import bandplan
from ohsnb.devices.sim import SimDevice
from ohsnb.extrig import UplinkPlan
from ohsnb.radio import Radio

LO = 1_104_000_000.0                 # a low-side 23 cm upconverter, as in test_extrig
FT8_DIAL = 10_489_540_000.0          # the narrow digimodes segment
DEVICE = "IC-9700 USB Audio CODEC"
DELAY, TAIL = 0.1, 0.05              # rigPttDelayMs, rigPttTailMs in seconds
ON, OFF = bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])


def wait_for(cond, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def soon(now, mode, period=None):
    # The over starts a moment from now rather than on a real slot, so the
    # early key (rigPttDelayMs before it) is exercised without waiting 15 s.
    return now + 0.3


class Cat(unittest.TestCase):
    link = "civ"
    lo = LO
    side = "low"
    cfg_over: dict = {}
    tone_s = 1.5

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch("ohscore.engine.slot_start", soon)
        p.start()
        self.addCleanup(p.stop)
        self.plan = UplinkPlan(Converter.from_dict(rig_conv(self.lo, self.side)["converters"][-1]))
        start_if = int(self.plan.rig_hz(bandplan.ul(FT8_DIAL)))
        if self.link == "civ":
            self.civ = CivSim(freq=start_if).start()
            link = {"civPort": self.civ.url}
        else:
            self.civ = RigctldSim(freq=start_if).start()
            link = {"rigctldHost": self.civ.host, "rigctldPort": self.civ.port}
        self.addCleanup(self.civ.stop)
        cfg = sim_cfg(txRadio=self.link, **rig_conv(self.lo, self.side), vfo=FT8_DIAL, mode="usb",
                      simRealtime=True, rigPollMs=50, callsign="GM4BRI", licenceClass="full", watchdogSec=10.0,
                      rigCatPtt=True, rigTxAudioOut=DEVICE, rigPttDelayMs=int(DELAY * 1000),
                      rigPttTailMs=int(TAIL * 1000), **link)
        cfg.update(self.cfg_over)
        self.dev = SimDevice(dict(cfg))
        self.audio = NullAudio(realtime=True)
        self.r = Radio(cfg, persist=False, data_dir=self.tmp, audio=self.audio, device=self.dev)
        real = self.r._render

        def render(mode, msg):
            if mode in ("ft8", "ft4", "q65") and self.tone_s:
                t = np.arange(int(self.tone_s * RATE)) / RATE
                return (0.5 * np.sin(2 * np.pi * 1500.0 * t)).astype(np.float32)
            return real(mode, msg)
        self.r._render = render
        self.toasts = self.r.subscribe("toast", 256)
        self.r.start()
        self.addCleanup(self.r.stop)

    # -------------------------------------------------------------- helpers
    def st(self):
        return self.r.state()

    def toast_texts(self):
        return [t["text"] for t in self.toasts.drain()]

    def ptt(self):
        """The PTT commands the radio received, as CI-V bodies or rigctld lines."""
        return self.civ.ptt_commands()

    def rig_tx(self) -> bool:
        return self.civ.tx if self.link == "civ" else self.civ.ptt

    def settled(self):
        def ok():
            s = self.st()
            want = int(round(self.plan.rig_hz(bandplan.ul(s["txDial"]) + s["rigTxCorr"])))
            return s["rigLink"] == "ok" and self.civ.freq == want
        return wait_for(ok)

    def ft8(self, mode="ft8"):
        self.assertTrue(self.settled())
        self.r.set(mode=mode)
        if self.link == "civ":
            self.assertTrue(wait_for(lambda: self.civ.data and self.civ.mode == self.plan.on_air_mode("usb")))
            # The MOD Input menu has been read, so the guard has its answer.
            self.assertTrue(wait_for(lambda: self.r.ext.link.mod_input is not None))

    def sink(self):
        return self.audio.tx_outs[-1]

    def on_air(self):
        return wait_for(lambda: self.rig_tx() and self.st()["keyed"])


class Over(Cat):
    def test_an_armed_digital_over_keys_waits_sends_and_unkeys(self):
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.assertTrue(wait_for(lambda: not self.st()["keyed"], timeout=6))
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        self.assertEqual(self.ptt(), [ON, OFF])
        (t_on, a), (t_off, b) = self.civ.tx_log
        self.assertEqual((a, b), (True, False))
        out = self.sink()
        self.assertEqual(out.device, DEVICE)
        # Key, then the PA delay, then audio.
        self.assertGreaterEqual(out.first_sound() - t_on, DELAY - 0.01)
        # All of it went, at the level set (-10 dB of the tone's 0.5).
        self.assertGreaterEqual(len(out.samples()), int(self.tone_s * RATE))
        self.assertAlmostEqual(float(np.max(np.abs(out.samples()))), 0.5 * 10 ** (-10 / 20), places=3)
        # Audio played out and stopped, then the tail, then unkey.
        last_t, last_a = out.chunks[-1]
        self.assertLessEqual(last_t + len(last_a) / RATE, t_off)
        self.assertLessEqual(out.closed_at, t_off)
        self.assertGreaterEqual(t_off - out.closed_at, TAIL - 0.01)
        # The PTT key went out after the data mode, never before.
        received = self.civ.received
        self.assertLess(received.index(bytes([0x1A, 0x06, 0x01, 0x01])), received.index(ON))
        self.assertFalse(self.st()["rigCatKeyed"])

    def test_a_real_ft4_message_goes_whole(self):
        from ohscore.modes import ft8
        if not ft8.CAN_ENCODE.get("ft4"):
            self.skipTest("no FT4 encoder here (ohsdigi: tools/build-ohsdigi.sh)")
        self.tone_s = 0                                  # the real encoder
        self.ft8("ft4")
        self.r.send("ft4", text="CQ GM4BRI IO75", freq=1500.0)
        self.assertTrue(self.on_air())
        self.assertTrue(wait_for(lambda: not self.st()["keyed"] and not self.rig_tx(), timeout=10))
        self.assertEqual(self.ptt(), [ON, OFF])
        # FT4's 5.04 s, all of it, through the radio's sound device.
        self.assertGreaterEqual(len(self.sink().samples()), int(5.0 * RATE))

    def test_a_psk_line_and_a_cw_line_go_the_same_way(self):
        self.assertTrue(self.settled())
        for mode in ("psk31", "cw"):
            self.r.set(mode=mode)
            self.assertTrue(wait_for(lambda: self.civ.data))
            n = len(self.ptt())
            self.r.send(mode, text="TEST")
            self.assertTrue(self.on_air())
            self.assertTrue(wait_for(lambda: not self.st()["keyed"] and not self.rig_tx(), timeout=10))
            self.assertEqual(self.ptt()[n:], [ON, OFF])

    def test_halt_mid_over_unkeys_at_once(self):
        self.tone_s = 8.0
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        time.sleep(0.5)
        t = time.monotonic()
        self.r.halt()
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        self.assertLess(self.civ.tx_log[-1][0] - t, 0.5)          # no tail, no drain
        self.assertEqual(self.ptt(), [ON, OFF])
        self.assertLess(len(self.sink().samples()), 4 * RATE)

    def test_a_mode_change_mid_over_unkeys(self):
        self.tone_s = 8.0
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.r.set(mode="psk31")
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        self.assertEqual(self.ptt(), [ON, OFF])

    def test_switching_cat_ptt_off_mid_over_unkeys(self):
        self.tone_s = 8.0
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.r.set(authorise=True, rigCatPtt=False)
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        self.assertEqual(self.ptt(), [ON, OFF])

    def test_app_exit_mid_over_unkeys_before_the_link_goes(self):
        self.tone_s = 8.0
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.r.stop()
        self.assertFalse(self.rig_tx())
        self.assertEqual(self.ptt(), [ON, OFF])

    def test_the_watchdog_still_applies(self):
        self.tone_s = 8.0
        self.ft8()
        self.r.set(authorise=True, watchdogSec=1.0)
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=4))
        self.assertEqual(self.ptt(), [ON, OFF])
        self.assertTrue(any("watchdog" in t for t in self.toast_texts()))


class Never(Cat):
    def tearDown(self):
        self.assertEqual(self.ptt(), [], "NB keyed the radio")

    def test_voice_is_never_keyed(self):
        self.assertTrue(self.settled())
        with self.assertRaises(TxRefused) as cm:
            self.r.ptt(True)
        self.assertIn("for voice, key it on the radio", str(cm.exception))
        # Nor PTT in a digital mode: that sends the microphone.
        self.r.set(mode="ft8")
        with self.assertRaises(TxRefused) as cm:
            self.r.ptt(True)
        self.assertIn("only for its own digital messages", str(cm.exception))
        self.assertEqual(self.audio.tx_outs, [])

    def test_a_stray_ptt_call_is_refused_even_mid_over(self):
        self.ft8()
        ext = self.r.ext
        with self.assertRaises(ForbiddenCommand):
            ext.link.ptt(True, ext.cat.permit)              # not armed
        with self.assertRaises(ForbiddenCommand):
            ext.link.rig.set_ptt(True)                      # no permit at all
        # Armed by the over's own transmit thread, it is still refused from
        # any other: start an over and try from here while it is on the air.
        self.tone_s = 4.0
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.assertTrue(ext.cat.permit.armed)
        with self.assertRaises(ForbiddenCommand):
            ext.link.ptt(True, ext.cat.permit)
        self.r.halt()
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        # This class's tearDown wants no PTT at all; the over's own two
        # are the path's, and nothing else went out.
        self.assertEqual(self.ptt(), [ON, OFF])
        self.civ.received[:] = [b for b in self.civ.received if b not in (ON, OFF)]


class SettingOff(Cat):
    cfg_over = {"rigCatPtt": False}

    def test_with_the_setting_off_nothing_keys_and_the_mode_is_left(self):
        self.assertTrue(self.settled())
        self.r.set(mode="ft8")
        with self.assertRaises(TxRefused) as cm:
            self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertIn("key it on the radio", str(cm.exception))
        time.sleep(1.2)
        self.assertEqual(self.ptt(), [])
        self.assertEqual(self.civ.data_sets, [])
        self.assertEqual(self.civ.mode_sets, [])
        self.assertEqual(self.audio.tx_outs, [])


class LinkLoss(Cat):
    def test_a_lost_link_unkeys_warns_and_unkeys_the_radio_when_it_returns(self):
        self.tone_s = 10.0
        self.ft8()
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.civ.stall(True)                        # the cable pulled
        self.assertTrue(wait_for(lambda: not self.st()["keyed"], timeout=5))
        # NB's own unkey cannot reach it either: it says so, and owes one.
        self.assertTrue(wait_for(lambda: self.r.ext.cat.owed, timeout=5))
        texts = self.toast_texts()
        self.assertTrue(any("cannot confirm" in t for t in texts), texts)
        self.assertTrue(any("Could not unkey" in t for t in texts), texts)
        self.assertTrue(self.civ.tx)                # the radio never heard an unkey
        self.civ.stall(False)
        self.assertTrue(wait_for(lambda: not self.civ.tx, timeout=10))
        self.assertTrue(wait_for(lambda: any("link is back" in t for t in self.toast_texts()), timeout=3))
        self.assertEqual(self.ptt()[0], ON)
        self.assertEqual(self.ptt()[-1], OFF)


class OverLog(Cat):
    """The lines a remote operator's log needs to say what an over did:
    what was sent, when against its slot, through which sound device at
    which level, how it ended, and what came back down."""

    def logged(self, act, level="INFO", until="over end:"):
        with self.assertLogs(None, level) as cm:
            act()
            self.assertTrue(wait_for(lambda: any(until in m for m in cm.output), timeout=10))
        return "\n".join(cm.output)

    def test_a_normal_over_logs_start_and_end(self):
        self.ft8()

        def over():
            self.r.send("ft8", text="CQ GM4BRI IO75", freq=1500.0)
            self.assertTrue(self.on_air())
        text = self.logged(over, until="link reports receiving")
        # Keyed the PTT delay (0.1 s) before the slot start; audio from it.
        self.assertRegex(text, r"over start: ft8 'CQ GM4BRI IO75' at 1500 Hz \(send:ft8\); "
                               r"keyed at slot -0\.\d\d s, audio from slot [+-]0\.0\d s; "
                               r"IC-9700 by CAT, audio to .*IC-9700 USB Audio CODEC.* at -10\.0 dB, "
                               r"PTT delay 100 ms, tail 50 ms")
        self.assertRegex(text, r"INFO:ohsnb\.radio:over end: ft8 after 1\.\d s on air, ended normal, TX audio underruns 0")
        # The radio's confirmations, timed from NB's commands: the read-back
        # straight after each, and the link poll's rigKeyed.
        self.assertRegex(text, r"IC-9700 keyed by CAT for a ft8 over: it read back transmitting \d+ ms after")
        self.assertRegex(text, r"IC-9700 link reports transmitting \(rigKeyed\), \d+ ms after NB's CAT command")
        self.assertRegex(text, r"IC-9700 unkeyed by CAT: it read back receiving \d+ ms after")
        self.assertRegex(text, r"IC-9700 link reports receiving \(rigKeyed\), \d+ ms after NB's CAT command")

    def test_a_halt_says_halt(self):
        self.tone_s = 8.0
        self.ft8()

        def over():
            self.r.send("ft8", text="CQ GM4BRI IO75")
            self.assertTrue(self.on_air())
            time.sleep(0.3)
            self.r.halt()
        self.assertRegex(self.logged(over), r"over end: ft8 after 0\.\d s on air, ended halt")

    def test_a_lost_link_is_a_warning(self):
        self.tone_s = 10.0
        self.ft8()

        def over():
            self.r.send("ft8", text="CQ GM4BRI IO75")
            self.assertTrue(self.on_air())
            self.civ.stall(True)
        text = self.logged(over)
        self.assertRegex(text, r"WARNING:ohsnb\.radio:over end: ft8 after [\d.]+ s on air, ended link lost")
        self.assertRegex(text, r"WARNING:ohscore\.rig:rig link lost: CI-V \S+ at \d+ baud, address A2h, "
                               r"no answer for [\d.]+ s: ")
        with self.assertLogs("ohscore.rig", "INFO") as cm:
            self.civ.stall(False)
            ok = wait_for(lambda: any("rig link up" in m for m in cm.output), timeout=10)
        self.assertTrue(ok, cm.output)
        self.assertRegex("\n".join(cm.output), r"rig link up: CI-V \S+ at \d+ baud, address A2h \(was lost: ")


class Refusals(Cat):
    def tearDown(self):
        self.assertEqual(self.ptt(), [])

    def test_mod_input_not_usb_refuses_with_the_menu_to_change(self):
        self.civ.mod_data = "mic"
        self.ft8()
        self.assertTrue(wait_for(lambda: (self.r.ext.link.mod_input or {}).get("data") == "mic", timeout=8))
        with self.assertRaises(TxRefused) as cm:
            self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertIn("DATA MOD", str(cm.exception))

    def test_no_sound_device_refuses(self):
        self.ft8()
        self.r.set(authorise=True, rigTxAudioOut="")
        with self.assertRaises(TxRefused) as cm:
            self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertIn("sound device", str(cm.exception))

    def test_a_beacon_is_refused(self):
        self.assertTrue(self.settled())
        self.r.set(mode="ft8", vfo=10_489_748_000.0)
        self.assertTrue(self.settled())
        with self.assertRaises(TxRefused):
            self.r.send("ft8", text="CQ GM4BRI IO75")


class DataMode(Cat):
    def tearDown(self):
        self.assertEqual(self.ptt(), [])

    def test_ft8_puts_it_in_usb_d_and_ssb_puts_it_back(self):
        self.ft8()
        self.assertEqual(self.civ.mode, "usb")
        self.r.set(mode="usb")
        self.assertTrue(wait_for(lambda: not self.civ.data))
        self.assertEqual(self.civ.mode, "usb")

    def test_a_change_on_the_radio_is_left_until_the_next_key_up(self):
        self.ft8()
        self.civ.set_mode("usb", data=False)        # Ray, on the radio
        time.sleep(1.5)
        self.assertFalse(self.civ.data)             # not fought between overs
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(wait_for(lambda: self.civ.tx, timeout=3))
        self.assertTrue(self.civ.data)              # re-asserted before keying
        self.r.halt()
        self.assertTrue(wait_for(lambda: not self.civ.tx, timeout=2))
        self.assertTrue(any("put it back in USB-D" in t for t in self.toast_texts()))
        self.civ.received[:] = [b for b in self.civ.received if b not in (ON, OFF)]
        self.civ.ptt_commands = lambda: []


class HighSide(Cat):
    """An inverting upconverter: USB on air is LSB on the radio."""
    lo = 3_696_200_000.0
    side = "high"

    def test_inverted_means_lsb_d_on_the_radio(self):
        self.ft8()
        self.assertEqual(self.civ.mode, "lsb")
        self.assertTrue(self.civ.data)


class Rigctld(Over):
    """The same over through rigctld: T 1, T 0, M PKTUSB."""
    link = "rigctld"

    def ptt(self):
        return [{"T 1": ON, "T 0": OFF}[ln] for ln in self.civ.ptt_commands()]

    def test_an_armed_digital_over_keys_waits_sends_and_unkeys(self):
        self.ft8()
        self.assertTrue(wait_for(lambda: self.civ.mode == "PKTUSB"))
        self.r.send("ft8", text="CQ GM4BRI IO75")
        self.assertTrue(self.on_air())
        self.assertTrue(wait_for(lambda: not self.st()["keyed"] and not self.civ.ptt, timeout=6))
        self.assertEqual(self.civ.ptt_commands(), ["T 1", "T 0"])
        (t_on, _), (t_off, _) = self.civ.tx_log
        out = self.sink()
        self.assertGreaterEqual(out.first_sound() - t_on, DELAY - 0.01)
        self.assertGreaterEqual(t_off - out.closed_at, TAIL - 0.01)

    def test_a_psk_line_and_a_cw_line_go_the_same_way(self):
        self.skipTest("the CI-V class covers it; rigctld adds nothing per mode")


if __name__ == "__main__":
    unittest.main()
