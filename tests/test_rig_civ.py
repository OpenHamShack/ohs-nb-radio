"""The CI-V driver (ohscore/rig/civ.py) against the IC-9700 emulator
(ohscore/rig/civsim.py), over a real TCP socket on 127.0.0.1 - the same
socket:// path a network serial port takes, so the driver's own open,
framing and parsing run. No serial port is ever opened here.

Byte layouts are computed in the test from docs/ic9700-research.md's own
words (frame FE FE <to> <from> <cmd> ... FD; frequency as five BCD bytes,
least significant pair first, high nibble the more significant digit),
not from the driver's helpers - otherwise a misread encoding would agree
with itself. What no test here can settle (the emulator was written from
the same pages) is listed in the research note as [unverified].
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import socket
import sys
import threading
import time
import unittest
from unittest import mock

from ohscore.rig import ForbiddenCommand, PttPermit, RigError, RigTimeout, civ
from ohscore.rig.civsim import CivSim
from ohscore.rig.link import RigLink

# Every command the driver may send, spelled out from the research note.
DOCUMENTED = {bytes([0x03]), bytes([0x04]), bytes([0x1A, 0x06]), bytes([0x1C, 0x00]),
              bytes([0x06, 0x00]), bytes([0x06, 0x01]),     # set mode: LSB, USB, filter byte omitted
              bytes([0x1A, 0x05, 0x01, 0x15]), bytes([0x1A, 0x05, 0x01, 0x16]),   # read MOD Input
              bytes([0x1A, 0x06, 0x00, 0x00]), bytes([0x1A, 0x06, 0x01, 0x01]),   # DATA off; on, FIL1
              bytes([0x1A, 0x06, 0x01, 0x02]), bytes([0x1A, 0x06, 0x01, 0x03])}   # on, FIL2/3


def bcd_by_hand(hz: int) -> bytes:
    digits = f"{hz:010d}"                    # ten digits, most significant first
    pairs = [digits[i:i + 2] for i in range(0, 10, 2)]
    return bytes(int(p[0]) << 4 | int(p[1]) for p in reversed(pairs))


def wait_for(cond, timeout=3.0, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Encoding(unittest.TestCase):
    def test_frequency_bcd_matches_the_documented_layout(self):
        for hz in (1_268_123_456, 1_296_200_000, 145_225_125, 432_000_001):
            self.assertEqual(civ.to_bcd(hz), bcd_by_hand(hz))
            self.assertEqual(civ.from_bcd(bcd_by_hand(hz)), hz)
        self.assertEqual(civ.to_bcd(1_268_123_456).hex(" "), "56 34 12 68 12")

    def test_reader_keeps_only_frames_to_us_and_drops_collisions(self):
        r = civ.FrameReader()
        me, radio = 0xE0, 0xA2
        echo = bytes([0xFE, 0xFE, radio, me, 0x03, 0xFD])
        jam = bytes([0xFE, 0xFE, me, radio, 0xFC, 0xFC, 0xFD])
        bcast = bytes([0xFE, 0xFE, 0x00, radio, 0x00]) + bcd_by_hand(1_296_000_000) + b"\xfd"
        reply = bytes([0xFE, 0xFE, me, radio, 0x03]) + bcd_by_hand(1_296_100_000) + b"\xfd"
        frames = r.feed(b"\x00\x13" + echo + jam + bcast + reply[:5])
        frames += r.feed(reply[5:])
        self.assertEqual([(t, f) for t, f, _ in frames], [(radio, me), (0x00, radio), (me, radio)])
        self.assertEqual(frames[-1][2], b"\x03" + bcd_by_hand(1_296_100_000))


class Driver(unittest.TestCase):
    sim_kw: dict = {}

    def setUp(self):
        self.sim = CivSim(**self.sim_kw).start()
        self.addCleanup(self.sim.stop)
        self.rig = civ.CivRig(self.sim.url)
        self.rig.open()
        self.addCleanup(self.rig.close)
        # The emulator announces only to connections it has accepted.
        self.assertTrue(wait_for(lambda: self.sim.conns))

    def tearDown(self):
        # Whatever a test did, nothing that could key the radio went out.
        self.assertEqual(self.sim.ptt_commands(), [])

    def test_reads_and_sets_the_frequency(self):
        self.assertEqual(self.rig.read_freq(), 1_268_200_000)
        self.rig.set_freq(1_268_250_123)
        self.assertEqual(self.sim.freq, 1_268_250_123)
        self.assertEqual(self.sim.received[-1], bytes([0x05]) + bcd_by_hand(1_268_250_123))
        self.assertEqual(self.rig.read_freq(), 1_268_250_123)

    def test_a_frequency_the_radio_refuses_is_an_error_that_says_so(self):
        with self.assertRaises(RigError) as cm:
            self.rig.set_freq(1_310_000_000)       # above the EUR 23 cm range
        self.assertIn("NG", str(cm.exception))
        self.assertEqual(self.sim.freq, 1_268_200_000)

    def test_transmit_state_is_read_without_a_data_byte(self):
        self.assertFalse(self.rig.read_tx())
        self.sim.key(True)
        self.assertTrue(self.rig.read_tx())
        self.sim.key(False)
        self.assertFalse(self.rig.read_tx())
        self.assertTrue(all(b == bytes([0x1C, 0x00]) for b in self.sim.received if b[:1] == b"\x1c"))

    def test_mode_and_data_mode(self):
        self.assertEqual(self.rig.read_mode(), ("usb", False))
        self.sim.set_mode("cw")
        self.assertEqual(self.rig.read_mode(), ("cw", False))
        self.sim.set_mode("usb", data=True)
        self.assertEqual(self.rig.read_mode(), ("usb", True))
        self.sim.set_mode("lsb")
        self.assertEqual(self.rig.read_mode()[0], "lsb")

    def test_set_ssb_is_command_06_with_the_mode_byte_only(self):
        self.sim.set_mode("fm")
        self.rig.set_ssb("usb")
        self.assertEqual(self.sim.received[-1], bytes([0x06, 0x01]))
        self.assertEqual(self.rig.read_mode()[0], "usb")
        self.rig.set_ssb("lsb")
        self.assertEqual(self.sim.received[-1], bytes([0x06, 0x00]))
        self.assertEqual(self.sim.mode, "lsb")
        for other in ("fm", "am", "cw", "dv"):
            with self.assertRaises(ValueError):
                self.rig.set_ssb(other)
        self.assertEqual(self.sim.mode_sets, ["usb", "lsb"])

    def test_knob_is_announced_by_transceive(self):
        self.sim.turn(1_268_300_000)
        self.assertEqual(self.rig.read_freq(), 1_268_300_000)
        self.assertEqual(self.rig.pushed(), [1_268_300_000])

    def test_a_silent_radio_times_out_with_a_sentence(self):
        self.sim.stall(True)
        with self.assertRaises(RigTimeout) as cm:
            self.rig.read_freq()
        self.assertIn("A2h", str(cm.exception))
        # One retry, as the driver's docstring says: two frames went out.
        self.assertEqual(self.sim.received[-2:], [bytes([0x03])] * 2)

    def test_only_documented_commands_go_out(self):
        self.rig.read_freq()
        self.rig.read_tx()
        self.rig.read_mode()
        self.rig.set_freq(1_268_000_000)
        self.rig.set_ssb("usb")
        for body in self.sim.received:
            self.assertTrue(body in DOCUMENTED or (body[:1] == b"\x05" and len(body) == 6), body.hex(" "))


class EchoAndNoise(Driver):
    """The same, with the radio echoing every frame (CI-V USB Echo Back ON,
    or the REMOTE jack's single wire) and a jammed frame before every
    answer."""
    sim_kw = {"echo": True, "noise": True}


class Whitelist(unittest.TestCase):
    def test_commands_that_transmit_or_change_power_are_refused_before_sending(self):
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        rig = civ.CivRig(sim.url)
        rig.open()
        self.addCleanup(rig.close)
        forbidden = [bytes([0x1C, 0x00, 0x01]),          # PTT on, without the permit
                     bytes([0x1C, 0x00, 0x00]),          # PTT off, without the permit
                     bytes([0x1A, 0x05, 0x01, 0x16, 0x03]),   # a menu write: DATA MOD = USB
                     bytes([0x1A, 0x06, 0x01, 0x00]),    # DATA on with no filter
                     bytes([0x1A, 0x06, 0x02, 0x01]),    # DATA2: not the 9700's
                     bytes([0x17]) + b"CQ",              # send CW
                     bytes([0x28, 0x00, 0x01]),          # transmit voice memory 1
                     bytes([0x14, 0x0A, 0x02, 0x55]),    # RF power
                     bytes([0x16, 0x5A, 0x01]),          # satellite mode on
                     bytes([0x07, 0xD1]),                # select SUB
                     bytes([0x06, 0x05]),                # mode FM: only LSB and USB may be set
                     bytes([0x06, 0x01, 0x02])]          # USB with a filter byte
        for body in forbidden:
            with self.assertRaises(ForbiddenCommand):
                rig._transact(body, None)
        time.sleep(0.1)
        self.assertEqual(sim.received, [])
        self.assertEqual(sim.ptt_commands(), [])

    def test_the_emulator_catches_a_ptt_command_when_one_is_sent(self):
        # The no-PTT checks above are only worth something if a PTT command
        # would be seen: sent by hand, bypassing the driver, it is - and it
        # keys the emulated radio, as it would the real one.
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        s = socket.create_connection((sim.host, sim.port))
        self.addCleanup(s.close)
        s.sendall(bytes([0xFE, 0xFE, 0xA2, 0xE0, 0x1C, 0x00, 0x01, 0xFD]))
        self.assertTrue(wait_for(lambda: sim.ptt_commands()))
        self.assertTrue(sim.tx)


class NoPttEver(unittest.TestCase):
    """A whole session the way OpenHamShack NB runs one - the link polling, the
    owner retuning, the operator turning the knob and keying the radio,
    the radio going silent and coming back - and not one command that
    could key it."""

    def test_a_polled_session_never_sends_a_ptt_command(self):
        sim = CivSim().start()
        self.addCleanup(sim.stop)
        target = {"f": 1_268_210_000}
        reports = []

        def report(r):
            # As OpenHamShack NB does: a knob move becomes the new wish at once.
            if r["moved"]:
                target["f"] = r["freq"]
            reports.append(r)
        link = RigLink(lambda: civ.CivRig(sim.url), lambda: target["f"], report, poll_s=0.02,
                       lost_after=0.3, retry_s=0.1)
        link.start()
        self.addCleanup(link.stop)
        self.assertTrue(wait_for(lambda: sim.freq == 1_268_210_000))
        sim.turn(1_268_400_000)
        self.assertTrue(wait_for(lambda: any(r["moved"] for r in reports)))
        self.assertEqual(target["f"], 1_268_400_000)
        sim.key(True)
        self.assertTrue(wait_for(lambda: reports[-1]["keyed"]))
        target["f"] = 1_268_500_000                 # not written while keyed
        time.sleep(0.2)
        self.assertEqual(sim.freq, 1_268_400_000)
        sim.key(False)
        self.assertTrue(wait_for(lambda: sim.freq == 1_268_500_000))
        sim.stall(True)
        self.assertTrue(wait_for(lambda: reports[-1]["link"] == "lost", timeout=3))
        sim.stall(False)
        self.assertTrue(wait_for(lambda: reports[-1]["link"] == "ok", timeout=3))
        self.assertEqual(sim.ptt_commands(), [])
        self.assertEqual({b for b in sim.received if b[:1] != b"\x05"} - DOCUMENTED, set())


class PttUnderPermit(unittest.TestCase):
    """CAT PTT (12/10/2026): the two PTT commands go out only under the
    digital over's permit - keying only while it is armed, on the thread
    that armed it; unkeying with the permit from anywhere - and every
    other way of asking is refused before a byte is sent."""

    def setUp(self):
        self.sim = CivSim().start()
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

    def test_no_permit_no_ptt(self):
        self.refused(lambda: self.rig.set_ptt(True))
        self.refused(lambda: self.rig.set_ptt(False))
        self.refused(lambda: self.rig.set_ptt(True, object()))
        self.refused(lambda: self.rig._transact(bytes([0x1C, 0x00, 0x01]), None))
        self.assertFalse(self.sim.tx)
        self.assertEqual(self.sim.ptt_commands(), [])

    def test_an_unarmed_permit_unkeys_but_never_keys(self):
        permit = PttPermit("test")
        self.refused(lambda: self.rig.set_ptt(True, permit))
        self.rig.set_ptt(False, permit)
        self.assertEqual(self.sim.ptt_commands(), [bytes([0x1C, 0x00, 0x00])])
        self.assertFalse(self.sim.tx)

    def test_armed_on_another_thread_is_refused_here(self):
        permit = PttPermit("test")
        t = threading.Thread(target=permit.arm)
        t.start()
        t.join()
        self.assertTrue(permit.armed)
        self.refused(lambda: self.rig.set_ptt(True, permit))
        self.assertFalse(self.sim.tx)

    def test_armed_on_this_thread_keys_and_reads_back(self):
        permit = PttPermit("test")
        permit.arm()
        self.rig.set_ptt(True, permit)
        self.assertTrue(self.sim.tx)
        self.assertTrue(self.rig.read_tx())
        self.rig.set_ptt(False, permit)
        self.assertFalse(self.rig.read_tx())
        self.assertEqual(self.sim.ptt_commands(), [bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])])
        permit.disarm()
        self.refused(lambda: self.rig.set_ptt(True, permit))

    def test_through_the_link_too(self):
        link = RigLink(lambda: civ.CivRig(self.sim.url), lambda: None, lambda r: None, poll_s=0.02)
        link.start()
        self.addCleanup(link.stop)
        self.assertTrue(wait_for(lambda: link.state == "ok"))
        permit = PttPermit("test")
        with self.assertRaises(ForbiddenCommand):
            link.ptt(True, permit)
        permit.arm()
        self.assertTrue(link.ptt(True, permit))
        self.assertFalse(link.ptt(False, permit))
        self.assertEqual([on for _, on in self.sim.tx_log], [True, False])


class DataMode(Driver):
    """The data variant NB puts the radio in for its digital modes, and the
    MOD Input reads (CIV p.7 and p.17)."""

    def test_usb_d_is_06_then_1a_06_with_the_radios_own_filter(self):
        self.sim.set_mode("fm")
        self.rig.set_data_mode("usb", True)
        self.assertEqual(self.rig.read_mode(), ("usb", True))
        sets = [b for b in self.sim.received if b[:1] == b"\x06" or (b[:2] == b"\x1a\x06" and len(b) > 2)]
        # The sim reports FIL1 for every mode, so the filter written is 01.
        self.assertEqual(sets, [bytes([0x06, 0x01]), bytes([0x1A, 0x06, 0x01, 0x01])])
        self.rig.set_data_mode("usb", False)
        self.assertEqual(self.rig.read_mode(), ("usb", False))
        self.assertIn(bytes([0x1A, 0x06, 0x00, 0x00]), self.sim.received)
        self.assertEqual(self.sim.mode_sets, ["usb"])          # already USB: 06 not sent again
        with self.assertRaises(ValueError):
            self.rig.set_data_mode("fm", True)

    def test_lsb_d(self):
        self.rig.set_data_mode("lsb", True)
        self.assertEqual(self.rig.read_mode(), ("lsb", True))

    def test_mod_input_is_read_with_no_value_byte(self):
        self.assertEqual(self.rig.read_mod_input(), {"plain": "mic", "data": "usb"})
        self.sim.mod_data = "acc"
        self.sim.mod_plain = "mic,usb"
        self.assertEqual(self.rig.read_mod_input(), {"plain": "mic,usb", "data": "acc"})
        self.assertIn(bytes([0x1A, 0x05, 0x01, 0x15]), self.sim.received)
        self.assertIn(bytes([0x1A, 0x05, 0x01, 0x16]), self.sim.received)
        self.assertEqual(self.sim.menu_writes, [])


class NoPyserial(unittest.TestCase):
    def test_a_serial_port_without_pyserial_says_what_to_install(self):
        with mock.patch.dict(sys.modules, {"serial": None}):
            with self.assertRaises(RigError) as cm:
                civ.CivRig("/dev/ttyUSB0").open()
        self.assertIn("pyserial", str(cm.exception))

    def test_no_port_set_says_where_to_set_it(self):
        with self.assertRaises(RigError) as cm:
            civ.CivRig("").open()
        self.assertIn("Settings", str(cm.exception))

    def test_nothing_listening_is_an_error_not_a_hang(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        t = time.monotonic()
        with self.assertRaises(RigError):
            civ.CivRig(f"socket://127.0.0.1:{port}").open()
        self.assertLess(time.monotonic() - t, 3.0)



class TxStateSim(CivSim):
    """The emulator, noting for every command whether it arrived while the
    radio was transmitting."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.heard: list[tuple[bool, bytes]] = []

    def _answer(self, body):
        self.heard.append((self.tx, body))
        return super()._answer(body)

    def written_keyed(self) -> list[bytes]:
        """Frequency, mode and DATA mode writes that reached it keyed."""
        return [b for tx, b in self.heard if tx and (b[:1] in (b"\x05", b"\x06")
                                                     or (b[:2] == b"\x1a\x06" and len(b) > 2))]


class NoWriteOnceKeyed(unittest.TestCase):
    """PTT pressed between a poll's transmit-state read and the write the
    same cycle then makes (link.py, "Writes while transmitting"; 18/10/2026,
    Ray's chopped IC-9700 downlink). Each test keys the emulator from the
    callback the cycle consults just before that write, which is the
    narrowest real window there is: the read said receive, the radio is
    now transmitting, and nothing may be written until it unkeys."""

    def setUp(self):
        self.sim = TxStateSim(freq=1_268_210_000).start()
        self.addCleanup(self.sim.stop)
        self.press = False            # key the radio from the next callback that sees this

    def link(self, want=None, report=None, want_mode=None):
        link = RigLink(lambda: civ.CivRig(self.sim.url), want or (lambda: None), report or (lambda r: None),
                       poll_s=0.02, mode_every_s=0.05, want_mode=want_mode)
        link.start()
        self.addCleanup(link.stop)
        self.assertTrue(wait_for(lambda: link.state == "ok"))
        return link

    def pressed(self) -> bool:
        if self.press:
            self.press = False
            self.sim.key(True)
            return True
        return False

    def released_then(self, cond):
        time.sleep(0.3)
        self.assertTrue(self.sim.tx)
        self.assertEqual(self.sim.written_keyed(), [])
        self.sim.key(False)
        self.assertTrue(wait_for(cond), "the write was lost instead of waiting for the unkey")

    def test_a_retune(self):
        target = {"f": 1_268_210_000}

        def want():
            if self.pressed():
                target["f"] = 1_268_220_000
            return target["f"]
        self.link(want=want)
        self.press = True
        self.released_then(lambda: self.sim.freq == 1_268_220_000)

    def test_a_data_mode_request(self):
        holder = {}

        def report(r):
            if self.pressed():
                holder["link"].request_data_mode("usb", True)
        holder["link"] = self.link(report=report)
        self.press = True
        self.released_then(lambda: self.sim.data)

    def test_leaving_fm(self):
        self.sim.set_mode("fm")

        def want_mode(mode):
            self.pressed()
            return "usb" if mode == "fm" else None
        self.press = True
        self.link(want_mode=want_mode)
        self.released_then(lambda: self.sim.mode == "usb")


if __name__ == "__main__":
    unittest.main()
