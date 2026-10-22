"""The CI-V driver's setup-assistant commands (ohscore/rig/civ.py, for
ohsnb/rigsetup.py, 12/10/2026) against the IC-9700 emulator over TCP: the
reads, the menu and band writes behind a SetupPermit naming each exact
body, the address search, and the link letting go of the port.

Byte layouts are spelled out here from the CI-V reference's pages (cited
per line), not from the driver's helpers, so a misread layout cannot
agree with itself; what the emulator and driver share a reading of is
[unverified] in docs/ic9700-research.md.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import threading
import time
import unittest
from unittest import mock

from ohscore.rig import ForbiddenCommand, RigError, SetupPermit, civ
from ohscore.rig.civsim import CivSim
from ohscore.rig.link import RigLink

DATA_MOD_USB = bytes([0x1A, 0x05, 0x01, 0x16, 0x03])           # CIV p.7: 0116, 03 = USB
USB_MOD_50 = bytes([0x1A, 0x05, 0x01, 0x13, 0x01, 0x28])       # CIV p.7: 0113, 0128 of 0255
SAT_OFF, SAT_ON = bytes([0x16, 0x5A, 0x00]), bytes([0x16, 0x5A, 0x01])   # CIV p.5
EXCHANGE, SEL_MAIN, SEL_SUB = bytes([0x07, 0xB0]), bytes([0x07, 0xD0]), bytes([0x07, 0xD1])   # CIV p.4


def wait_for(cond, timeout=3.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Case(unittest.TestCase):
    sim_kw: dict = {}

    def setUp(self):
        self.sim = CivSim(**self.sim_kw).start()
        self.addCleanup(self.sim.stop)
        self.rig = civ.CivRig(self.sim.url)
        self.rig.open()
        self.addCleanup(self.rig.close)

    def refused(self, fn):
        before = list(self.sim.received)
        with self.assertRaises(ForbiddenCommand):
            fn()
        time.sleep(0.05)
        self.assertEqual(self.sim.received, before)


class Reads(Case):
    def test_levels_are_four_bcd_digits_in_two_bytes(self):
        self.assertEqual(civ.level_bcd(128), bytes([0x01, 0x28]))
        self.assertEqual(civ.level_bcd(255), bytes([0x02, 0x55]))
        self.assertEqual(civ.from_level(bytes([0x02, 0x13])), 213)
        with self.assertRaises(ValueError):
            civ.level_bcd(256)

    def test_each_read_reads_and_changes_nothing(self):
        self.sim.usb_mod, self.sim.satellite, self.sim.selected = 200, True, "sub"
        self.sim.rf_power = 13
        self.assertEqual(self.rig.read_id(), 0xA2)
        self.assertEqual(self.rig.read_usb_mod_level(), 200)
        self.assertEqual(self.rig.read_rf_power(), 13)
        self.assertTrue(self.rig.read_satellite())
        self.assertEqual(self.rig.read_selected(), "sub")
        with self.assertRaises(RigError):                 # CIV p.23: 25 is FA in satellite mode
            self.rig.read_main_freq()
        self.sim.satellite = False
        self.assertEqual(self.rig.read_main_freq(), 1_268_200_000)
        self.assertEqual(self.rig.read_freq(), 145_500_000)      # 03 reads the selected band: SUB
        self.assertEqual((self.rig.read_meter("po"), self.rig.read_meter("alc")), (0, 0))   # on receive
        self.assertEqual(self.sim.menu_writes, [])
        self.assertEqual((self.sim.usb_mod, self.sim.selected, self.sim.rf_power), (200, "sub", 13))
        self.assertEqual(self.sim.ptt_commands(), [])
        for body in (bytes([0x19, 0x00]), bytes([0x1A, 0x05, 0x01, 0x13]), bytes([0x16, 0x5A]),
                     bytes([0x07, 0xD2]), bytes([0x25, 0x00]), bytes([0x15, 0x11]), bytes([0x15, 0x13]),
                     bytes([0x14, 0x0A])):
            self.assertIn(body, self.sim.received)

    def test_the_meters_follow_the_drive_while_transmitting(self):
        drive = {"db": -30.0}
        self.sim.drive = lambda: drive["db"]
        self.sim.key(True)
        self.assertEqual(self.rig.read_meter("alc"), 0)
        low_po = self.rig.read_meter("po")
        self.assertGreater(low_po, 0)
        drive["db"] = -6.0
        self.assertGreater(self.rig.read_meter("alc"), 0)
        self.assertGreater(self.rig.read_meter("po"), low_po)


    def test_rays_9700_alc_flat_until_the_knee(self):
        """Ray's 9700 on 23 cm at RF POWER 59 (12/10/2026): ALC 5 (its keyed
        baseline) until Po stops rising near -31 dBFS, then climbing."""
        drive = {"db": None}
        self.sim.drive = lambda: drive["db"]
        self.sim.real_9700(rf_power=59)
        self.sim.key(True)
        got = {}
        for db in (-40.0, -34.0, -31.0, -28.0, -20.0):
            drive["db"] = db
            got[db] = (self.rig.read_meter("po"), self.rig.read_meter("alc"))
        self.assertEqual([got[db][1] for db in (-40.0, -34.0)], [5, 5])
        self.assertGreater(got[-28.0][1], 30)
        self.assertGreater(got[-20.0][1], 90)
        self.assertLess(got[-40.0][0], got[-34.0][0])
        self.assertEqual(got[-28.0][0], got[-20.0][0])                    # flat past the knee

    def test_the_9700_as_measured(self):
        """The emulator's real_9700() (civsim.py), shaped like Brian's 9700
        on 12/10/2026: the ALC reads with any audio and more at a lower RF
        POWER; Po rises with the level, then stays at the setting - from
        the very bottom at 5 %."""
        drive = {"db": None}
        self.sim.drive = lambda: drive["db"]
        self.sim.real_9700(rf_power=128, alc_any_audio=True)
        self.sim.key(True)
        self.assertEqual((self.rig.read_meter("alc"), self.rig.read_meter("po")), (5, 0))   # keyed, no audio
        drive["db"] = -40.0
        self.assertGreater(self.rig.read_meter("alc"), 20)                 # "moves" at -40 dBFS
        po = []
        for db in (-40.0, -34.0, -28.0, -22.0, -16.0, -10.0):
            drive["db"] = db
            po.append(self.rig.read_meter("po"))
        self.assertEqual(po, sorted(po))
        self.assertLess(po[0], po[2] / 2)                                  # rising below the knee...
        self.assertEqual(po[-1], po[-2])                                   # ...flat above it
        self.assertEqual(po[-1], 143)                                      # 50 %: CIV p.4's 0143
        drive["db"] = -34.0
        alc_half = self.rig.read_meter("alc")
        self.sim.rf_power = 5                                              # 2 %: the knee under -40 dBFS
        self.assertGreater(self.rig.read_meter("alc"), alc_half)
        flat = []
        for db in (-40.0, -34.0, -28.0):
            drive["db"] = db
            flat.append(self.rig.read_meter("po"))
        self.assertLessEqual(max(flat) - min(flat), 1)
        # A drop-out, then the model again.
        self.sim.po_dropouts = [3]
        self.assertEqual(self.rig.read_meter("po"), 3)
        self.assertEqual(self.rig.read_meter("po"), flat[-1])
        # A slow fall: the ALC still reads high just after the audio stops.
        self.sim.meter_attack_s, self.sim.meter_release_s = 0.02, 1.0
        high = self.rig.read_meter("alc")
        drive["db"] = None
        time.sleep(0.3)
        self.assertGreater(self.rig.read_meter("alc"), high // 2)
        time.sleep(1.5)
        self.assertLess(self.rig.read_meter("alc"), high // 4)


class SetupWrites(Case):
    """A write goes out only when a SetupPermit names that exact body, armed
    on this thread; the shapes no permit can widen."""

    def test_no_permit_no_write(self):
        for body in (DATA_MOD_USB, USB_MOD_50, SAT_OFF, EXCHANGE, SEL_MAIN):
            self.refused(lambda b=body: self.rig.setup_write(b, None))
            self.refused(lambda b=body: self.rig._transact(b, None))
            self.refused(lambda b=body: self.rig.setup_write(b, object()))
        self.assertEqual(self.sim.menu_writes, [])

    def test_a_permit_allows_only_what_it_names_and_only_while_armed(self):
        permit = SetupPermit("test")
        self.refused(lambda: self.rig.setup_write(DATA_MOD_USB, permit))      # not armed
        permit.arm([DATA_MOD_USB])
        # A stray write while the permit is armed: another value, another item.
        self.refused(lambda: self.rig.setup_write(bytes([0x1A, 0x05, 0x01, 0x16, 0x00]), permit))
        self.refused(lambda: self.rig.setup_write(SAT_ON, permit))
        self.sim.mod_data = "mic"
        self.rig.setup_write(DATA_MOD_USB, permit)
        self.assertEqual(self.sim.mod_data, "usb")
        permit.disarm()
        self.refused(lambda: self.rig.setup_write(DATA_MOD_USB, permit))
        self.assertEqual(self.sim.menu_writes, [DATA_MOD_USB])

    def test_armed_on_another_thread_is_refused_here(self):
        permit = SetupPermit("test")
        t = threading.Thread(target=lambda: permit.arm([SAT_OFF]))
        t.start()
        t.join()
        self.sim.satellite = True
        self.refused(lambda: self.rig.setup_write(SAT_OFF, permit))
        self.assertTrue(self.sim.satellite)

    def test_no_permit_can_name_a_write_outside_the_setup_shapes(self):
        rf_power = bytes([0x14, 0x0A, 0x02, 0x55])
        others = [rf_power, bytes([0x1A, 0x05, 0x01, 0x15, 0x03]),    # DATA OFF MOD: not the assistant's
                  bytes([0x1A, 0x05, 0x01, 0x16, 0x06]),              # no such MOD Input
                  bytes([0x1A, 0x05, 0x01, 0x13, 0x02, 0x56]),        # 256: past the top
                  bytes([0x1C, 0x00, 0x01]), bytes([0x07, 0x00])]     # PTT; VFO A
        permit = SetupPermit("test")
        permit.arm(others)
        for body in others:
            self.refused(lambda b=body: self.rig.setup_write(b, permit))
        self.assertEqual(self.sim.ptt_commands(), [])

    def test_each_documented_write_does_what_it_says(self):
        permit = SetupPermit("test")
        permit.arm([USB_MOD_50, SAT_OFF, SAT_ON, EXCHANGE, SEL_SUB, SEL_MAIN])
        self.sim.usb_mod, self.sim.satellite = 10, True
        self.rig.setup_write(USB_MOD_50, permit)
        self.rig.setup_write(SAT_OFF, permit)
        self.assertEqual((self.sim.usb_mod, self.sim.satellite), (128, False))
        main, sub = self.sim.freq, self.sim.sub_freq
        self.rig.setup_write(EXCHANGE, permit)
        self.assertEqual((self.sim.freq, self.sim.sub_freq), (sub, main))
        self.rig.setup_write(SEL_SUB, permit)
        self.assertEqual(self.rig.read_selected(), "sub")
        self.rig.setup_write(SEL_MAIN, permit)
        self.assertEqual(self.rig.read_selected(), "main")
        self.assertEqual(civ.set_usb_mod_level(128), USB_MOD_50)
        self.assertEqual(civ.set_data_mod("usb"), DATA_MOD_USB)


class FindAddress(unittest.TestCase):
    def test_a_radio_at_19200_baud_is_found_reading_only(self):
        """Ray's 9700 answered only at 19200 (12/10/2026) while NB asked at
        115200. A serial port at the wrong rate hears garbage and answers
        nothing: modelled here by a radio that stays silent unless the port
        was opened at 19200."""
        radio = CivSim().start()
        silent = CivSim().start()
        silent.stall(True)
        self.addCleanup(radio.stop)
        self.addCleanup(silent.stop)
        rates = []
        real_open = civ.open_port

        def open_port(port, baud, timeout):
            rates.append(int(baud))
            return real_open(radio.url if int(baud) == 19200 else silent.url, baud, timeout)
        with mock.patch.object(civ, "open_port", open_port):
            self.assertEqual(civ.find_radio("COM4", 115200), (0xA2, 0xA2, 19200))
        self.assertEqual(rates[:2], [115200, 19200])                # the setting first, then the usual rate
        self.assertEqual(radio.received, [bytes([0x19, 0x00])])
        self.assertEqual(radio.ptt_commands(), [])

    def test_the_default_answers_first(self):
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        self.assertEqual(civ.find_address(sim.url), (0xA2, 0xA2))
        self.assertEqual(sim.received, [bytes([0x19, 0x00])])

    def test_another_address_is_found_by_the_sweep_reading_only(self):
        sim = CivSim(address=0x94).start()
        self.addCleanup(sim.stop)
        self.assertEqual(civ.find_address(sim.url, sweep_timeout=0.01), (0x94, 0x94))
        self.assertEqual(set(sim.received), {bytes([0x19, 0x00])})

    def test_nothing_answering_is_none_and_cancel_stops_the_sweep(self):
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        sim.stall(True)
        self.assertIsNone(civ.find_address(sim.url, sweep_timeout=0.002))
        n = len(sim.received)
        asked = []
        self.assertIsNone(civ.find_address(sim.url, sweep_timeout=0.002, cancel=lambda: asked.append(1) or len(asked) > 3))
        self.assertLessEqual(len(sim.received) - n, 4)


class LinkPause(unittest.TestCase):
    def test_a_paused_link_lets_go_of_the_port_and_comes_back(self):
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        link = RigLink(lambda: civ.CivRig(sim.url), lambda: None, lambda r: None, poll_s=0.02)
        link.start()
        self.addCleanup(link.stop)
        self.assertTrue(wait_for(lambda: link.state == "ok"))
        link.pause()
        self.assertIsNone(link.rig)
        self.assertTrue(wait_for(lambda: not sim.conns))
        n = len(sim.received)
        time.sleep(0.2)
        self.assertEqual(len(sim.received), n)
        with self.assertRaises(RigError):
            link.read_meters()
        link.resume()
        self.assertTrue(wait_for(lambda: len(sim.received) > n and link.rig is not None))
        self.assertEqual(link.read_meters(), {"alc": 0, "po": 0})


if __name__ == "__main__":
    unittest.main()
