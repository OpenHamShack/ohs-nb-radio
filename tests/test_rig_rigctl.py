"""The rigctld driver (ohscore/rig/rigctl.py) against a fake rigctld
(ohscore/rig/rigctlsim.py) over TCP on 127.0.0.1, and RigLink's polling
decisions (ohscore/rig/link.py) on top of it.

The fake speaks rigctld(1)'s default protocol as the manual describes it
(docs/ic9700-research.md); the expected lines here are written out from
the manual, not taken from the driver.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import threading
import time
import unittest

from ohscore.rig import ForbiddenCommand, PttPermit, RigError, RigTimeout, probe
from ohscore.rig.link import RigLink
from ohscore.rig.rigctl import RigctldRig
from ohscore.rig.rigctlsim import RigctldSim


def wait_for(cond, timeout=3.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Driver(unittest.TestCase):
    vfo_mode = False

    def setUp(self):
        self.sim = RigctldSim(vfo_mode=self.vfo_mode).start()
        self.addCleanup(self.sim.stop)
        self.rig = RigctldRig(*self.sim.address)
        self.rig.open()
        self.addCleanup(self.rig.close)

    def tearDown(self):
        self.assertEqual(self.sim.ptt_commands(), [])

    def test_frequency_transmit_state_and_mode(self):
        self.assertEqual(self.rig.read_freq(), 1_268_200_000)
        self.rig.set_freq(1_268_250_000)
        self.assertEqual(self.sim.freq, 1_268_250_000)
        self.assertFalse(self.rig.read_tx())
        self.sim.key(True)
        self.assertTrue(self.rig.read_tx())
        self.assertEqual(self.rig.read_mode(), ("usb", False))
        self.sim.mode = "PKTUSB"
        self.assertEqual(self.rig.read_mode(), ("usb", True))
        self.sim.mode = "CW"
        self.assertEqual(self.rig.read_mode(), ("cw", False))

    def test_the_lines_sent_are_the_manuals(self):
        self.rig.read_freq()
        self.rig.set_freq(1_268_000_000)
        self.rig.read_tx()
        self.rig.read_mode()
        self.rig.set_ssb("usb")
        v = " currVFO" if self.vfo_mode else ""
        self.assertEqual(self.sim.lines, ["\\chk_vfo", f"f{v}", f"F{v} 1268000000", f"t{v}", f"m{v}", f"M{v} USB 0"])

    def test_set_ssb_reaches_usb_and_lsb_only(self):
        self.sim.mode = "FM"
        self.rig.set_ssb("lsb")
        self.assertEqual(self.rig.read_mode(), ("lsb", False))
        with self.assertRaises(ValueError):
            self.rig.set_ssb("fm")
        self.assertEqual(self.sim.mode_sets, ["LSB"])

    def test_a_silent_rigctld_times_out(self):
        self.sim.stall(True)
        with self.assertRaises(RigTimeout):
            self.rig.read_freq()


class VfoMode(Driver):
    """rigctld started with --vfo: every command carries currVFO."""
    vfo_mode = True


class Refusals(unittest.TestCase):
    def test_keying_and_power_commands_are_refused_before_sending(self):
        sim = RigctldSim().start()
        self.addCleanup(sim.stop)
        rig = RigctldRig(*sim.address)
        rig.open()
        self.addCleanup(rig.close)
        sent = list(sim.lines)
        for line in ("T 1", "T 0", "\\set_ptt 1", "L RFPOWER 0.5", "b CQ", "\\send_morse CQ",
                     "\\send_voice_mem 1", "\\halt", "M USB 2400", "M FM 0", "M PKTFM 0", "T 2", "T currVFO 1", "F 1268000000\nT 1"):
            with self.assertRaises(ForbiddenCommand):
                rig._ask(line)
        time.sleep(0.1)
        self.assertEqual(sim.lines, sent)

    def test_ptt_only_under_an_armed_permit_on_its_own_thread(self):
        # CAT PTT (12/10/2026): T 1 / T 0 exist, behind the permit.
        sim = RigctldSim().start()
        self.addCleanup(sim.stop)
        rig = RigctldRig(*sim.address)
        rig.open()
        self.addCleanup(rig.close)
        permit = PttPermit("test")
        for call in (lambda: rig.set_ptt(True), lambda: rig.set_ptt(False), lambda: rig.set_ptt(True, permit)):
            with self.assertRaises(ForbiddenCommand):
                call()
        t = threading.Thread(target=permit.arm)
        t.start()
        t.join()
        with self.assertRaises(ForbiddenCommand):
            rig.set_ptt(True, permit)                  # armed, but on another thread
        time.sleep(0.05)
        self.assertEqual(sim.ptt_commands(), [])
        permit.arm()
        rig.set_ptt(True, permit)
        self.assertTrue(rig.read_tx())
        rig.set_ptt(False, permit)
        self.assertFalse(rig.read_tx())
        self.assertEqual(sim.ptt_commands(), ["T 1", "T 0"])

    def test_data_mode_is_pktusb_and_back(self):
        sim = RigctldSim().start()
        self.addCleanup(sim.stop)
        rig = RigctldRig(*sim.address)
        rig.open()
        self.addCleanup(rig.close)
        rig.set_data_mode("usb", True)
        self.assertEqual(rig.read_mode(), ("usb", True))
        rig.set_data_mode("lsb", False)
        self.assertEqual(rig.read_mode(), ("lsb", False))
        self.assertEqual(sim.mode_sets, ["PKTUSB", "LSB"])
        self.assertIsNone(rig.read_mod_input())         # rigctld cannot say

    def test_no_rigctld_says_how_to_start_one(self):
        with self.assertRaises(RigError) as cm:
            probe("rigctld", {"rigctldHost": "127.0.0.1", "rigctldPort": 1})
        self.assertIn("rigctld -m 3081", str(cm.exception))

    def test_probe_reads_the_frequency_only(self):
        sim = RigctldSim().start()
        self.addCleanup(sim.stop)
        self.assertEqual(probe("rigctld", {"rigctldHost": sim.host, "rigctldPort": sim.port}), 1_268_200_000)
        self.assertTrue(wait_for(lambda: len(sim.lines) >= 2))
        self.assertEqual(sim.lines, ["\\chk_vfo", "f"])


class Link(unittest.TestCase):
    """RigLink's decisions, seen from its owner."""

    def setUp(self):
        self.sim = RigctldSim().start()
        self.addCleanup(self.sim.stop)
        self.reports: list[dict] = []
        self.target = {"f": None}

    def tearDown(self):
        self.assertEqual(self.sim.ptt_commands(), [])

    def link(self, **kw):
        lk = RigLink(lambda: RigctldRig(*self.sim.address), lambda: self.target["f"], self.reports.append,
                     poll_s=0.02, lost_after=0.3, retry_s=0.1, **kw)
        lk.start()
        self.addCleanup(lk.stop)
        return lk

    def test_our_own_write_is_not_a_knob_move_but_the_knob_is(self):
        self.link()
        self.target["f"] = 1_268_300_000
        self.assertTrue(wait_for(lambda: any(r.get("wrote") == 1_268_300_000 for r in self.reports)))
        time.sleep(0.1)
        self.assertFalse(any(r["moved"] for r in self.reports))
        self.target["f"] = None
        self.sim.turn(1_268_400_000)
        self.assertTrue(wait_for(lambda: any(r["moved"] and r["freq"] == 1_268_400_000 for r in self.reports)))

    def test_a_refused_frequency_is_not_retried_until_the_wish_changes(self):
        self.link()
        self.sim.vfo_mode = False
        orig = self.sim._answer

        def refuse(line):
            if line.startswith("F "):
                return "RPRT -9\n"
            return orig(line)
        self.sim._answer = refuse
        self.target["f"] = 1_268_300_000
        self.assertTrue(wait_for(lambda: any(r.get("refused") for r in self.reports)))
        time.sleep(0.2)
        self.assertEqual(sum(1 for ln in self.sim.lines if ln.startswith("F ")), 1)
        self.target["f"] = 1_268_310_000
        self.assertTrue(wait_for(lambda: sum(1 for ln in self.sim.lines if ln.startswith("F ")) == 2))

    def test_no_writes_while_the_radio_transmits(self):
        self.link()
        self.sim.key(True)
        self.assertTrue(wait_for(lambda: self.reports and self.reports[-1]["keyed"]))
        self.target["f"] = 1_268_300_000
        time.sleep(0.2)
        self.assertEqual(self.sim.sets, [])
        self.sim.key(False)
        self.assertTrue(wait_for(lambda: self.sim.sets == [1_268_300_000]))

    def test_want_mode_switches_the_rig_once_and_not_while_it_transmits(self):
        self.sim.mode = "FM"
        self.sim.key(True)
        self.link(mode_every_s=0.05, want_mode=lambda m: "usb" if m == "fm" else None)
        self.assertTrue(wait_for(lambda: self.reports and self.reports[-1]["keyed"]))
        time.sleep(0.2)
        self.assertEqual(self.sim.mode_sets, [])               # never mid-over
        self.sim.key(False)
        self.assertTrue(wait_for(lambda: self.sim.mode_sets == ["USB"]))
        self.assertTrue(any(r.get("mode_from") == "fm" and r.get("mode_to") == "usb" for r in self.reports))
        self.assertTrue(wait_for(lambda: self.reports[-1]["mode"] == "usb"))
        time.sleep(0.2)
        self.assertEqual(self.sim.mode_sets, ["USB"])

    def test_a_refused_mode_change_is_not_retried_until_the_mode_changes(self):
        orig = self.sim._answer

        def refuse(line):
            if line.startswith("M "):
                return "RPRT -9\n"
            return orig(line)
        self.sim._answer = refuse
        self.sim.mode = "FM"
        self.link(mode_every_s=0.05, want_mode=lambda m: "usb" if m == "fm" else None)
        self.assertTrue(wait_for(lambda: any(r.get("mode_refused") == "usb" for r in self.reports)))
        time.sleep(0.3)
        self.assertEqual(sum(1 for ln in self.sim.lines if ln.startswith("M ")), 1)
        self.sim.mode = "CW"
        self.assertTrue(wait_for(lambda: self.reports[-1]["mode"] == "cw"))
        self.sim.mode = "FM"
        self.assertTrue(wait_for(lambda: sum(1 for ln in self.sim.lines if ln.startswith("M ")) == 2))

    def test_a_lost_link_reports_not_transmitting_and_comes_back(self):
        self.link()
        self.sim.key(True)
        self.assertTrue(wait_for(lambda: self.reports and self.reports[-1]["keyed"]))
        self.sim.stall(True)
        self.assertTrue(wait_for(lambda: self.reports[-1]["link"] == "lost", timeout=3))
        self.assertFalse(self.reports[-1]["keyed"])
        self.sim.stall(False)
        self.assertTrue(wait_for(lambda: self.reports[-1]["link"] == "ok" and self.reports[-1]["keyed"], timeout=3))


if __name__ == "__main__":
    unittest.main()
