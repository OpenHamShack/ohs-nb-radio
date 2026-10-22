"""The IC-9700 diagnostic (ohsnb/rigdiag.py), end to end: the real Radio
on the simulated transponder, the real CI-V driver over TCP to the
emulated radio (ohscore/rig/civsim.py) shaped as Brian's 9700 measured,
the tone to a NullAudio sound device. What it reads and reports, that it
never keys without the tick and the confirmation, never writes RF POWER
or anything else, stops on Halt, and that the command line will not key
without the operator's promise. No serial port, sound card or radio is
opened.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

import test_rigsetup as rs
from ohscore.rig import RigError, civ
from ohscore.rig.civsim import CivSim
from ohsnb import rigdiag
from ohsnb.rigdiag import RigDiagnostic

ON, OFF = rs.ON, rs.OFF


class Case(rs.Base):
    def setUp(self):
        super().setUp()

        def drive():
            # The audio the sound device is playing now (test_rigsetup.LevelSet).
            outs = self.audio.tx_outs
            # Only this radio's own CODEC reaches its modulator.
            if not outs or outs[-1].closed_at is not None or outs[-1].device != rs.DEVICE:
                return None
            at = time.monotonic() - 0.09
            playing = [a for start, a in list(outs[-1].chunks) if start <= at]
            if not playing:
                return None
            peak = float(np.max(np.abs(playing[-1])))
            return 20 * np.log10(peak) if peak > 0 else None
        self.civ.drive = drive

    def ready(self):
        self.assertTrue(self.settled())
        self.r.set(mode="ft8")
        self.assertTrue(rs.wait_for(lambda: self.civ.data and self.r.ext.link.mod_input is not None))

    def writes(self):
        """Every body the radio received that changes a setting. Not the
        reads, PTT, or what NB's CAT path sends in normal running whenever
        a digital mode is chosen (the dial's frequency, USB-D: extrig.py)."""
        ok = {civ.READ_FREQ, civ.READ_MODE, civ.READ_DATA, civ.READ_TX, civ.READ_MOD_PLAIN, civ.READ_MOD_DATA,
              civ.READ_ID, civ.READ_PO, civ.READ_ALC, civ.READ_SAT, civ.READ_SELECTED, civ.READ_MAIN_FREQ,
              civ.READ_USB_MOD, civ.READ_RF_POWER, ON, OFF, civ.DATA_OFF, civ.data_on(1), civ.data_on(2),
              civ.data_on(3), *civ.SET_SSB.values()}
        return [b for b in self.civ.received if b not in ok and b[0] != civ.C_SET_FREQ]


class ReadOnly(Case):
    def test_reads_everything_and_changes_nothing(self):
        self.ready()
        self.civ.real_9700(rf_power=13)
        before = list(self.civ.received)
        real_open = civ.open_port

        def open_port(port, baud, timeout):
            # The by-id port fails to open as it does with pyserial
            # installed, quoting the path whole - whether or not this
            # Python has pyserial (the development machine's python3 does not, and
            # there the error named no port, so the serial number in it
            # went unnoticed until the build venv ran this).
            if port.startswith("socket://"):
                return real_open(port, baud, timeout)
            raise RigError(f"Could not open {port}: [Errno 2] could not open port {port}: [Errno 2] No such file "
                           f"or directory: '{port}'. Is the IC-9700 switched on and connected by USB, and is no "
                           "other program using that port?")
        with mock.patch.object(civ, "open_port", open_port):
            out = RigDiagnostic(self.r).read_only(ports=lambda: [("/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_"
                                                                  "to_UART_Bridge_Controller_IC-9700_13003524_A-if00"
                                                                  "-port0", "IC-9700 USB VID:PID=10C4:EA60 "
                                                                  "SER=IC-9700_13003524_A LOCATION=1-1.2:1.0")])
        text = RigDiagnostic.report(out)
        self.assertEqual(out["facts"]["answered"]["address"], 0xA2)
        self.assertEqual(out["facts"]["rfPower"], 13)
        self.assertEqual(out["facts"]["usbMod"], 128)
        for want in ("answers at A2h", "RF POWER (14 0A): 13 (5 %)", "USB MOD Level (1A 05 01 13): 128 (50 %)",
                     "DATA MOD USB", "Satellite mode (16 5A): off", "20 frequency reads", "Meters on receive",
                     "IC-9700 sound device chosen in NB: IC-9700 USB Audio CODEC", "rigCatPtt: True",
                     "rigTxAudioDb: -10.0", "rigPttDelayMs: 100", "Upconverter:", "OpenHamShack QO-100 NB",
                     "OS: "):
            self.assertIn(want, text)
        self.assertIn("would not open (Could not open /dev/serial/by-id/", text)
        # Nothing that identifies the station or the radio.
        self.assertNotIn("GM4BRI", text)
        self.assertNotIn("13003524", text)
        self.assertNotIn(self.r.st.get("locator") or "IO75", text)
        # Reads only, the link given back, no PTT.
        self.assertGreater(len(self.civ.received), len(before))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.civ.ptt_commands(), [])
        self.assertEqual(self.civ.rf_power, 13)
        self.assertTrue(rs.wait_for(lambda: self.r.state()["rigLink"] == "ok"))

    def test_no_radio_is_a_finding_not_a_failure(self):
        self.ready()
        self.civ.stall(True)
        out = RigDiagnostic(self.r).read_only(ports=lambda: [])
        text = RigDiagnostic.report(out)
        self.assertIn("No IC-9700 answered", text)
        self.assertNotIn("answered", out["facts"])

    def test_serials_come_out_of_port_names(self):
        self.assertEqual(rigdiag.scrub("/dev/serial/by-id/usb-Silicon_Labs_IC-9700_13003524_A-if00-port0"),
                         "/dev/serial/by-id/usb-Silicon_Labs_IC-9700_<serial>_A-if00-port0")
        self.assertEqual(rigdiag.scrub("USB VID:PID=10C4:EA60 SER=0123ABCD LOCATION=1-2"),
                         "USB VID:PID=10C4:EA60 SER=<serial> LOCATION=1-2")
        self.assertEqual(rigdiag.scrub("COM5"), "COM5")


class Keyed(Case):
    def test_never_keys_without_the_tick_and_the_confirmation(self):
        self.ready()
        d = RigDiagnostic(self.r)
        for tick, ok in ((False, True), (True, False), ("yes", True), (True, "yes")):
            with self.assertRaises(RigError):
                d.keyed(tick, ok)
        self.assertEqual(self.civ.ptt_commands(), [])

    def test_rays_case_sweeps_times_and_leaves_the_radio_as_it_was(self):
        """RF POWER very low (Ray drives an upconverter), a radio whose ALC
        reads high with any audio and holds the power to the setting (Brian's
        2 m measurement): the sweep shows Po flat from the bottom."""
        self.ready()
        self.civ.real_9700(rf_power=5, alc_any_audio=True)
        self.civ.meter_attack_s, self.civ.meter_release_s = 0.03, 1.0
        d = RigDiagnostic(self.r)
        plan = d.keyed_plan()
        self.assertEqual((plan["band"], plan["rfPower"]), ("23cm", 5))
        self.assertAlmostEqual(plan["watts"], 0.1 + 9.9 * 5 / 255)
        said = []
        out = d.keyed(True, True, progress=said.append)
        self.assertEqual(out["result"], "done")
        overs = out["facts"]["overs"]
        self.assertEqual([[s["level"] for s in o] for o in overs],
                         [[None], [-40.0, -34.0, -28.0, -22.0], [-16.0, -10.0, -10.0]])
        self.assertTrue(all(len(s["po"]) == rigdiag.SAMPLES for o in overs for s in o))
        self.assertLessEqual(max(overs[0][0]["po"]), 1)                        # keyed, no audio
        flat = [max(s["po"]) for s in overs[1]]
        self.assertLessEqual(max(flat) - min(flat), 2)                         # flat from the bottom
        self.assertTrue(all(min(s["alc"]) > 20 for s in overs[1]))             # ALC high with any audio
        # Timing: the audio starts the PTT delay after the key-up, Po after it.
        marks = out["facts"]["timing"]["marks"]
        self.assertGreaterEqual(marks["audio"] - marks["keyed"], 0.09)
        self.assertLess(marks["audioEnd"], marks["unkeyed"])
        text = RigDiagnostic.report(out)
        for want in ("RF POWER 5 (2 %)", "about 0.3 W", "no audio", "-40.0 dB", "PTT delay set to 100 ms",
                     "PTT tail set to 50 ms", "nothing was changed"):
            self.assertIn(want, text)
        self.assertNotIn("RECOMMEND", text)                                   # a 100 ms delay is enough
        self.assertEqual(len(said), 4)
        # Four overs, each keyed and unkeyed; nothing written, RF POWER as found.
        self.assertTrue(rs.wait_for(lambda: not self.civ.tx and not self.r.state()["keyed"], timeout=3))
        self.assertEqual(self.civ.ptt_commands(), [ON, OFF] * 4)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.civ.menu_writes, [])
        self.assertEqual(self.civ.rf_power, 5)
        self.assertEqual(out["facts"]["before"], out["facts"]["after"])
        self.assertEqual(self.r.state()["rigTxAudioDb"], -10.0)

    def test_rays_pc_two_codecs_and_the_tone_into_the_other_radios(self):
        """Ray's real report (12/10/2026): two radios, two USB Audio CODECs,
        NB set to the other radio's; keyed, ALC 5 and Po 0 at every level.
        The report now says so in words rather than leaving a level puzzle."""
        from unittest import mock
        from ohsnb.rigsetup import RigSetup
        self.ready()
        other_codec = "Speakers (2- USB AUDIO  CODEC)"
        other = CivSim(freq=145_500_000).start()
        self.addCleanup(other.stop)
        self.r.set(authorise=True, rigTxAudioOut=other_codec, rigPttDelayMs=20)      # Ray's, both
        names = ["Speakers / Headphones (Realtek ", other_codec, "IC9700 Speakers (USB Audio CODE"]
        d = RigDiagnostic(self.r)
        with mock.patch.object(RigSetup, "outputs", lambda _s: names):
            ro = d.read_only(ports=lambda: [])
        self.assertEqual(ro["facts"]["codecs"], [other_codec, "IC9700 Speakers (USB Audio CODE"])
        out = d.keyed(True, True)
        self.assertTrue(out["facts"]["noAudio"])
        text = RigDiagnostic.report(ro, out)
        self.assertIn("2 USB Audio CODEC outputs", text)
        self.assertIn("VERDICT: the radio was keyed but made no power at any level", text)
        self.assertIn(other_codec, text)
        self.assertIn("RECOMMEND: Delay before audio 80-100 ms", text)
        self.assertEqual(other.received, [])
        self.assertEqual(self.writes(), [])

    def test_halt_stops_it_at_once_and_starts_no_further_over(self):
        self.ready()
        d = RigDiagnostic(self.r)
        said = []

        def progress(text):
            said.append(text)
            if len(said) == 2:                  # the first tone over is starting: Halt in the middle of it
                threading.Timer(1.2, self.r.halt).start()
        t0 = time.monotonic()
        out = d.keyed(True, True, progress=progress)
        self.assertEqual(out["result"], "stopped")
        self.assertLess(time.monotonic() - t0, 8.0)
        self.assertIn("STOPPED", RigDiagnostic.report(out))
        self.assertTrue(rs.wait_for(lambda: not self.civ.tx and not self.r.state()["keyed"], timeout=3))
        self.assertLessEqual(len(self.civ.ptt_commands()), 4)                  # the no-audio over and this one
        self.assertEqual(self.civ.ptt_commands()[-1], OFF)
        self.assertEqual(self.writes(), [])

    def test_stop_between_overs_starts_no_further_over(self):
        self.ready()
        d = RigDiagnostic(self.r)
        said = []

        def progress(text):
            said.append(text)
            if len(said) == 1:
                d.cancel()                      # Stop as the first over begins
        out = d.keyed(True, True, progress=progress)
        self.assertEqual(out["result"], "stopped")
        self.assertEqual(len(said), 1)
        self.assertLessEqual(len(self.civ.ptt_commands()), 2)


class CommandLine(unittest.TestCase):
    def test_keyed_refuses_without_the_promise_before_opening_anything(self):
        from ohsnb import __main__ as cli
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "r.txt"
        opened = []
        orig = rigdiag.run_cli
        rigdiag.run_cli = lambda *a, **k: opened.append(a) or 0
        try:
            self.assertEqual(cli.main(["--rig-diagnostic", str(path), "--keyed"]), 2)
        finally:
            rigdiag.run_cli = orig
        self.assertEqual(opened, [])
        self.assertFalse(path.exists())
        # And run_cli itself refuses too, before calling the factory.
        made = []
        self.assertEqual(rigdiag.run_cli(lambda: made.append(1), str(path), keyed=True, promised=False,
                                         out=lambda _t: None), 2)
        self.assertEqual(made, [])


if __name__ == "__main__":
    unittest.main()
