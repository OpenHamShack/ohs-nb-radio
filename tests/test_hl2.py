"""The Hermes-Lite 2 driver (ohscore/devices/hl2.py) against the emulator
(ohscore/devices/hl2sim.py), over real UDP on 127.0.0.1.

Behaviour only. Register values are checked against encodings computed
here, in the test, from docs/ham/hl2-research.md's own words (rate bits
25:24, LNA byte ((dB+12)&0x3F)|0x40, Quisk's OC map, drive in bits
31:28), not against the driver's helper functions - otherwise a misread
encoding would agree with itself. What no test here can settle (the TX
I/Q order, the power calibration) is listed in hl2.py's docstring: the
emulator was written from the same documents as the driver.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import math
import socket
import sys
import time
import unittest
from unittest import mock

import numpy as np

from ohscore.devices import DeviceError
from ohscore.devices import hl2
from ohscore.devices.hl2sim import HL2Sim, temp_raw

RATE_BITS = {48_000: 0, 96_000: 1, 192_000: 2, 384_000: 3}
QUISK_OC = {"160m": (1.85e6, 0x01), "80m": (3.6e6, 0x42), "60m": (5.36e6, 0x44), "40m": (7.1e6, 0x44),
            "30m": (10.12e6, 0x48), "20m": (14.1e6, 0x48), "17m": (18.1e6, 0x50), "15m": (21.2e6, 0x50),
            "12m": (24.93e6, 0x60), "10m": (28.5e6, 0x60)}


def wait_for(cond, timeout=2.0, step=0.005):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def finish(d: hl2.HL2Device, timeout: float = 1.0) -> bool:
    """What the engine does at a normal end of an over (Engine._tx_drain)."""
    d.tx_finish()
    return wait_for(lambda: d.tx_queued() <= 0, timeout, 0.002)


def peak_hz(x: np.ndarray, fs: float) -> float:
    w = np.hanning(len(x))
    f = np.fft.fftfreq(len(x), 1 / fs)
    return float(f[np.argmax(np.abs(np.fft.fft(x * w)))])


class SimCase(unittest.TestCase):
    """An emulator per test, and a driver opened on it."""
    sim_kw: dict = {}

    def setUp(self):
        self.sim = HL2Sim(**{"watchdog_s": 1.0, **self.sim_kw}).start()
        self.addCleanup(self.sim.stop)
        self.devs = []

    def tearDown(self):
        for d in self.devs:
            d.close()

    def open(self, fs=192_000, **cfg) -> hl2.HL2Device:
        d = hl2.HL2Device(self.sim.address, fs, cfg)
        self.devs.append(d)
        d.open()
        return d

    def reg(self, addr):
        return self.sim.regs.get(addr)

    def settle(self):
        # Every register in the rotation is resent within 3 EP2 datagrams (~8 ms).
        n = self.sim.ep2_datagrams
        self.assertTrue(wait_for(lambda: self.sim.ep2_datagrams >= n + 6))


class Discovery(SimCase):
    def test_direct_probe_finds_the_emulator(self):
        found = hl2.discover(1.0, self.sim.address, broadcast=False)
        self.assertEqual(len(found), 1)
        d = found[0]
        self.assertEqual((d["ip"], d["port"]), ("127.0.0.1", self.sim.port))
        self.assertEqual(d["board"], 0x06)
        self.assertEqual((d["gatewareMajor"], d["gatewareMinor"], d["gateware"]), (74, 2, "74.2"))
        self.assertEqual(d["receivers"], 4)
        self.assertEqual(d["problem"], "")
        self.assertFalse(d["busy"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "loopback broadcast (127.255.255.255) is Linux's")
    def test_broadcast_finds_the_emulator(self):
        # The real path with an empty address: a broadcast to port 1024 on
        # every interface. Pointed at the loopback broadcast address and the
        # emulator's port instead, so the test never sends onto a real LAN.
        sim = HL2Sim(host="0.0.0.0").start()
        self.addCleanup(sim.stop)
        with mock.patch.object(hl2, "_broadcast_addresses", lambda: ["127.255.255.255"]), \
                mock.patch.object(hl2, "PORT", sim.port):
            found = hl2.discover(1.0)
        self.assertEqual([(d["ip"], d["port"], d["problem"]) for d in found], [("127.0.0.1", sim.port, "")])

    def test_nothing_there_is_an_empty_list_not_an_error(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertEqual(hl2.discover(0.2, f"127.0.0.1:{port}", broadcast=False), [])

    def test_open_with_nothing_there_says_what_to_check(self):
        d = hl2.HL2Device("127.0.0.1:9", 192_000, {"hl2DiscoverTimeout": 0.2})
        with self.assertRaises(DeviceError) as e:
            d.open()
        self.assertIn("1024", str(e.exception))
        self.assertIn("firewall", str(e.exception))


class Rejections(unittest.TestCase):
    def _refused(self, **kw) -> str:
        with HL2Sim(**kw) as sim:
            d = hl2.HL2Device(sim.address, 192_000, {})
            with self.assertRaises(DeviceError) as e:
                d.open()
            self.assertFalse(sim.streaming)
            return str(e.exception)

    def test_old_gateware_is_named_with_the_minimum(self):
        msg = self._refused(gateware=(71, 3))
        self.assertIn("71.3", msg)
        self.assertIn("72.8", msg)

    def test_other_board_is_refused(self):
        msg = self._refused(board=0x01)
        self.assertIn("0x01", msg)
        self.assertIn("Hermes-Lite 2", msg)

    def test_unsupported_rate_is_refused(self):
        with HL2Sim() as sim:
            with self.assertRaises(DeviceError):
                hl2.HL2Device(sim.address, 1_200_000, {}).open()


class Receive(SimCase):
    sim_kw = {"tone_hz": 14_074_000.0, "tone_level": 0.1}

    def test_tone_lands_at_its_offset_from_the_centre(self):
        d = self.open(192_000)
        d.set_rx_if(14_000_000.0)
        self.settle()
        d.read(int(0.05 * 192_000))                 # anything from before the tune
        x = d.read(int(0.2 * 192_000))
        self.assertEqual(x.dtype, np.complex64)
        self.assertAlmostEqual(peak_hz(x, 192_000), 74_000.0, delta=10)
        self.assertAlmostEqual(float(np.abs(x).mean()), 0.1, delta=0.01)    # full scale is +-1
        d.set_rx_if(14_100_000.0)                   # now 26 kHz below the centre
        self.settle()
        d.read(int(0.05 * 192_000))
        self.assertAlmostEqual(peak_hz(d.read(int(0.2 * 192_000)), 192_000), -26_000.0, delta=10)

    def test_each_rate_streams_at_its_rate(self):
        for fs in (48_000, 384_000):
            with self.subTest(fs=fs):
                d = self.open(fs)
                self.assertEqual((self.reg(hl2.R_CONFIG) >> 24) & 3, RATE_BITS[fs])
                d.read(int(0.05 * fs))
                t0, n0 = time.monotonic(), d.samples
                time.sleep(0.5)
                rate = (d.samples - n0) / (time.monotonic() - t0)
                self.assertAlmostEqual(rate / fs, 1.0, delta=0.06)
                self.assertEqual(d.overruns, 0)
                d.close()

    def test_lost_datagrams_are_counted_and_zero_filled(self):
        d = self.open(192_000)
        d.set_rx_if(14_070_000.0)
        self.settle()
        d.read(int(0.1 * 192_000))                  # the backlog from before the tune
        self.sim.drop_every(10)
        t0 = time.monotonic()
        x = d.read(int(0.6 * 192_000))
        elapsed = time.monotonic() - t0
        self.sim.drop_every(0)
        # Zero-filled runs of exactly one datagram, about one in ten.
        z = np.abs(x) == 0
        d_ = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
        starts, ends = np.flatnonzero(d_ == 1), np.flatnonzero(d_ == -1)
        inner = (starts > 0) & (ends < len(x))          # a run cut by the read's edges is shorter
        runs = (ends - starts)[inner]
        self.assertTrue(len(runs) > 0)
        self.assertTrue(np.all(runs == 126), runs[:10])
        self.assertGreater(d.overruns, 0.6 * 192_000 / 126 / 10 * 0.7)
        # Timing stays true: the samples (zeros included) match elapsed time...
        self.assertAlmostEqual(len(x) / 192_000, elapsed, delta=0.08)
        # ...and the tone keeps its phase across each gap (the radio's clock ran on).
        k = np.arange(len(x))
        ref = np.exp(2j * np.pi * 4_000 / 192_000 * k)      # the 14.074 MHz tone, 4 kHz above
        rot = x[~z] * np.conj(ref[~z])
        self.assertGreater(float(np.abs(np.mean(rot / np.abs(rot)))), 0.999)   # one phase throughout
        # The emulator's sequence count and the driver's sample count agree.
        self.assertTrue(wait_for(lambda: abs(d.samples - self.sim.seq * 126) <= 126 * d.batch * 2))

    def test_a_short_stall_is_bridged(self):
        d = self.open(192_000)
        d.read(1000)
        self.sim.stall(0.3)
        x = d.read(int(0.6 * 192_000))
        self.assertGreater(d.overruns, 0.25 * 192_000 / 126)
        self.assertGreater(int(np.sum(np.abs(x) == 0)), 0.25 * 192_000)
        self.assertEqual(self.sim.watchdog_fired, 0)


class Registers(SimCase):
    def test_config_rx_frequency_lna_and_buffer(self):
        d = self.open(96_000, hl2Lna=20.0)
        d.set_rx_if(14_074_000.0)
        self.settle()
        r0 = self.reg(0x00)
        self.assertEqual((r0 >> 24) & 3, 1)                       # 96 kS/s
        self.assertEqual((r0 >> 17) & 0x7F, 0x48)                 # 20 m: 30/20 m LPF + HPF
        self.assertEqual((r0 >> 3) & 0xF, 0)                      # one receiver
        self.assertEqual((r0 >> 11) & 1, 0)                       # never band volts (it bypasses the thermal trip)
        self.assertEqual(self.reg(0x02), 14_074_000)
        self.assertEqual(self.reg(0x0A) & 0xFF, ((20 + 12) & 0x3F) | 0x40)
        self.assertEqual(self.reg(0x09) >> 19 & 1, 1)             # PA enabled
        hang, lat = (self.reg(0x17) >> 8) & 0x1F, self.reg(0x17) & 0x7F
        self.assertEqual((hang, lat), (12, 20))
        self.assertNotEqual(hang, 31)
        self.assertEqual(self.reg(0x39) >> 24 & 0xF, 0x8)         # watchdog enabled, never 0x9
        self.assertTrue(all(c & 0x80 == 0 for c in self.sim.start_cmds))   # start never disables it
        d.set_lna(-12)
        self.settle()
        self.assertEqual(self.reg(0x0A) & 0xFF, 0x40)

    def test_lna_change_reaches_a_streaming_radio_without_a_restart(self):
        d = self.open(hl2Lna=20.0)
        d.set_rx_if(14_100_000.0)                                  # the emulator's tone at DC
        self.settle()
        d.read(int(0.05 * 192_000))
        before = float(np.sqrt(np.mean(np.abs(d.read(int(0.1 * 192_000))) ** 2)))
        starts, n = len(self.sim.start_cmds), self.sim.ep2_datagrams
        d.set_lna(32)
        # Next C&C frame, not the next pass of the rotation (three datagrams):
        # the datagram already being built when set_lna ran may miss it, the
        # one after may not.
        self.assertTrue(wait_for(lambda: self.sim.ep2_datagrams >= n + 2))
        self.assertEqual(self.sim.lna_db, 32.0)
        self.assertEqual(self.reg(0x0A) & 0xFF, ((32 + 12) & 0x3F) | 0x40)
        self.assertEqual(len(self.sim.start_cmds), starts)          # never stopped and started again
        d.read(int(0.05 * 192_000))
        after = float(np.sqrt(np.mean(np.abs(d.read(int(0.1 * 192_000))) ** 2)))
        self.assertAlmostEqual(20 * math.log10(after / before), 12.0, delta=1.0)

    def test_filter_bits_follow_the_band(self):
        d = self.open()
        for band, (f, bits) in QUISK_OC.items():
            with self.subTest(band=band):
                d.set_rx_if(f)
                self.settle()
                self.assertEqual((self.reg(0x00) >> 17) & 0x7F, bits)
                self.assertEqual(self.reg(0x02), int(f))

    def test_keyed_the_tx_frequency_chooses_the_filter(self):
        d = self.open()
        d.set_rx_if(14_100_000.0)
        d.set_tx_freq(7_100_000.0)
        self.settle()
        self.assertEqual((self.reg(0x00) >> 17) & 0x7F, 0x48)
        self.assertEqual(self.reg(0x01), 7_100_000)
        d.tx_start()
        self.settle()
        self.assertEqual((self.reg(0x00) >> 17) & 0x7F, 0x44)
        self.assertEqual(self.reg(0x02), 14_100_000)            # RX1 untouched by TX
        d.tx_stop()
        self.settle()
        self.assertEqual((self.reg(0x00) >> 17) & 0x7F, 0x48)


class Transmit(SimCase):
    def tone(self, fs, secs, f=5_000.0, amp=0.5):
        n = np.arange(int(fs * secs))
        return (amp * np.exp(2j * np.pi * f * n / fs)).astype(np.complex64)

    def test_mox_only_between_start_and_stop(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        time.sleep(0.1)
        self.assertEqual(self.sim.mox_frames, 0)
        d.tx_start()
        d.set_drive(1.0)
        for _ in range(4):
            d.write(self.tone(192_000, 0.075))
        self.assertTrue(self.sim.mox)
        d.tx_stop()
        self.assertFalse(self.sim.mox)
        n = self.sim.mox_frames
        time.sleep(0.1)
        self.assertEqual(self.sim.mox_frames, n)
        self.assertEqual([on for _, on in self.sim.mox_events], [True, False])
        with self.assertRaises(DeviceError):
            d.write(self.tone(192_000, 0.01))

    def test_iq_arrives_at_48k_with_its_tone_and_amplitude(self):
        for fs in (192_000, 48_000):
            with self.subTest(fs=fs):
                self.sim.clear_tx()
                d = self.open(fs)
                d.set_tx_freq(14_070_000.0)
                d.tx_start()
                d.set_drive(1.0)
                t0 = time.monotonic()
                for _ in range(8):
                    d.write(self.tone(fs, 0.075, f=-3_000.0 if fs == 48_000 else 5_000.0))
                took = time.monotonic() - t0
                self.assertTrue(finish(d))
                d.tx_stop()
                tx = self.sim.tx_iq()
                # 48 kS/s, nothing lost (a datagram or two of zeros before the
                # first write; zeros after the last, while the radio's buffer
                # runs out)
                end = int(np.flatnonzero(np.abs(tx) > 0.01)[-1]) + 1
                self.assertAlmostEqual(end, 0.6 * 48_000, delta=4 * 126)
                body = tx[4800:-4800]
                self.assertAlmostEqual(peak_hz(body, 48_000), -3_000.0 if fs == 48_000 else 5_000.0, delta=10)
                self.assertAlmostEqual(float(np.abs(body).mean()), 0.5, delta=0.01)
                self.assertGreater(took, 0.6 - 0.1)       # write() paces the caller to real time
                self.assertEqual(d.tx_underruns, 0)
                d.close()

    def test_a_finished_over_keeps_mox_and_drive_until_the_radio_has_sent_it(self):
        # write() returns with up to 40 ms still queued here; the HL2's own
        # buffer holds 20 ms more. A normal end must get all of it on air
        # at the drive it was sent at.
        d = self.open(48_000)
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(1.0)
        self.settle()
        for _ in range(4):
            d.write(self.tone(48_000, 0.075))
        self.assertGreater(d.tx_queued(), 0.02)
        self.assertLessEqual(d.tx_queued(), hl2.TX_HIGH_WATER + d.tx_latency_ms / 1000 + 0.01)
        self.assertTrue(finish(d))
        d.set_drive(0.0)
        d.tx_stop()
        chunks = self.sim.tx_chunks()
        real = [(t, step) for t, step, iq in chunks if np.abs(iq).max() > 0.01]
        sent = sum(int((np.abs(iq) > 0.01).sum()) for _, _, iq in chunks)
        self.assertEqual(sent, 4 * 3600)                              # every written sample arrived
        self.assertEqual({step for _, step in real}, {15})           # all of them at full drive
        t_off = [t for t, on in self.sim.mox_events if not on][-1]
        self.assertGreaterEqual(t_off - real[-1][0], 0.8 * d.tx_latency_ms / 1000)   # the radio's buffer ran out
        self.assertEqual(d.tx_underruns, 0)                          # the queue running dry was the end, not a fault

    def test_tx_stop_alone_drops_the_queue(self):
        # The emergency path: Escape, the watchdog, a trip. What is queued
        # here never reaches the radio.
        d = self.open(48_000)
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(1.0)
        for _ in range(4):
            d.write(self.tone(48_000, 0.075))
        held = d.tx_queued() - d.tx_latency_ms / 1000
        self.assertGreater(held, 0.01)
        d.tx_stop()
        self.assertEqual(d.tx_queued(), 0.0)
        sent = int((np.abs(self.sim.tx_iq()) > 0.01).sum())
        self.assertLess(sent, 4 * 3600 - 0.5 * held * 48_000)

    def test_drive_uses_the_register_then_iq_scaling(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        # (drive, register step from the research: 16 steps over the top 7.5 dB)
        for x, step in ((1.0, 15), (10 ** (-3 / 20), 9), (10 ** (-7.5 / 20), 0), (0.1, 0), (0.0, 0)):
            with self.subTest(drive=x):
                d.set_drive(x)
                self.sim.clear_tx()
                for _ in range(3):
                    d.write(self.tone(192_000, 0.075, amp=1.0))
                self.settle()
                self.assertEqual(self.reg(0x09) >> 28, step)
                sent = self.sim.tx_iq()
                if x == 0.0:
                    # The tail only: the head can hold a datagram built at
                    # the previous drive while it changed (see the next test).
                    self.assertEqual(float(np.abs(sent[-4000:]).max()), 0.0)
                    continue
                # Only the tone's own samples. If this thread is descheduled
                # for more than the 40 ms write() leaves queued (the nightly
                # runs every suite at once on a loaded VM), the driver pads
                # the starved datagrams with exact zeros - an underrun, which
                # is what the hardware would get too, not a drive error - and
                # a plain mean over a window holding them read 0.6952 for
                # 0.7079 there. The tone has constant modulus, so none of its
                # own samples rounds to zero at any drive tested here.
                body = sent[np.abs(sent) > 0][-4000:]
                self.assertEqual(len(body), 4000)
                gain = 10 ** ((-7.5 + 0.5 * step) / 20)
                # register gain x IQ amplitude = the drive asked for
                self.assertAlmostEqual(gain * float(np.abs(body).mean()), x, delta=0.01)
        d.tx_stop()
        self.settle()
        self.assertEqual(self.reg(0x09) >> 28, 0)

    def test_drive_is_monotonic_and_continuous(self):
        xs = np.linspace(0, 1, 2001)
        eff = [hl2.step_gain(s) * k for s, k in (hl2.drive_split(x) for x in xs)]
        np.testing.assert_allclose(eff, xs, atol=1e-9)

    def test_set_drive_zero_silences_what_is_queued(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(1.0)
        d.write(self.tone(192_000, 0.075))          # returns with up to 40 ms still queued
        d.set_drive(0.0)
        time.sleep(0.01)                            # a datagram being built as it changed
        self.sim.clear_tx()
        time.sleep(0.05)
        sent = self.sim.tx_iq()
        self.assertGreater(len(sent), 0)
        self.assertEqual(float(np.abs(sent).max()), 0.0)
        d.tx_stop()

    def test_tx_latency_is_plausible(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(0.5)
        d.write(self.tone(192_000, 0.075))
        lat = d.tx_latency()
        self.assertGreater(lat, 0.02)                 # at least the radio's own 20 ms buffer
        self.assertLess(lat, 0.12)
        d.tx_stop()

    def test_tx_range_and_power(self):
        d = hl2.HL2Device("", 192_000, {})
        self.assertEqual(d.rx_range, (0.0, 38.4e6))
        self.assertEqual(d.tx_range, (1.8e6, 30e6))
        self.assertAlmostEqual(d.tx_full_w(14e6), 5.0)
        self.assertEqual(d.tx_full_w(50e6), 0.0)
        with self.assertRaises(DeviceError):
            d.set_tx_freq(50.3e6)


class Safety(SimCase):
    sim_kw = {"watchdog_s": 0.3}

    def test_close_clears_mox_and_stops_streaming(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(1.0)
        d.write(np.zeros(9600, np.complex64))
        self.assertTrue(self.sim.mox)
        d.close()
        self.assertTrue(wait_for(lambda: not self.sim.mox and not self.sim.streaming, 1.0))
        self.assertEqual(self.sim.start_cmds[-1] & 1, 0)
        self.assertEqual(self.sim.watchdog_fired, 0)        # stopped by us, not by the watchdog
        d.close()                                          # twice is fine
        with self.assertRaises(DeviceError):
            d.read(10)

    def test_a_dying_socket_thread_unkeys_and_read_raises(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        d.tx_start()
        d.set_drive(1.0)
        d.write(np.zeros(9600, np.complex64))
        self.assertTrue(self.sim.mox)

        def boom(*a):
            raise RuntimeError("injected")
        d._unpack = boom
        self.assertTrue(wait_for(lambda: not self.sim.mox, 1.0))
        self.assertFalse(d.mox)
        with self.assertRaises(DeviceError) as e:
            for _ in range(20):
                d.read(19_200)
        self.assertIn("injected", str(e.exception))
        self.assertTrue(wait_for(lambda: not self.sim.streaming, 1.0))
        # The engine's reconnect: close and open again, unkeyed.
        del d._unpack
        d.close()
        d.open()
        self.assertFalse(d.mox)
        self.assertEqual(len(d.read(1000)), 1000)

    def test_a_silent_radio_makes_read_raise(self):
        d = self.open(192_000, hl2StreamTimeout=0.3)
        d.read(1000)
        self.sim.stall(5.0)
        with self.assertRaises(DeviceError) as e:
            for _ in range(50):
                d.read(19_200)
        self.assertIn("stopped sending", str(e.exception))

    def test_ep2_from_the_driver_keeps_the_watchdog_quiet(self):
        d = self.open(48_000)
        time.sleep(1.0)                 # three watchdog periods
        self.assertTrue(self.sim.streaming)
        self.assertEqual(self.sim.watchdog_fired, 0)
        self.assertEqual(self.sim.ep2_seq_gaps, 0)
        d.read(1000)

    def test_emulator_watchdog_stops_streaming_without_ep2(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(s.close)
        s.settimeout(0.5)
        s.sendto(b"\xef\xfe\x04\x01" + bytes(60), ("127.0.0.1", self.sim.port))
        data, _ = s.recvfrom(2048)
        self.assertEqual(data[:4], b"\xef\xfe\x01\x06")
        self.assertEqual(len(data), 1032)
        self.assertTrue(wait_for(lambda: self.sim.watchdog_fired == 1, 1.5))
        self.assertFalse(self.sim.streaming)


class Telemetry(SimCase):
    def test_temperature_current_and_flags(self):
        d = self.open()
        raw_t = temp_raw(42.0)
        self.sim.set_telemetry(temp_c=42.0, current_a=0.5)
        self.assertTrue(wait_for(lambda: abs(d.telemetry().get("temp", 0) - 42.0) < 0.1))
        tel = d.telemetry()
        self.assertAlmostEqual(tel["temp"], (3.26 * raw_t / 4096 - 0.5) / 0.01, places=6)
        self.assertAlmostEqual(tel["current"], 0.5, delta=0.01)
        self.assertFalse(tel["tx_inhibit"] or tel["fifo_underflow"] or tel["fifo_overflow"])
        self.sim.tx_inhibit = True
        self.sim.fifo = "under"
        self.assertTrue(wait_for(lambda: d.telemetry()["tx_inhibit"] and d.telemetry()["fifo_underflow"]))
        self.sim.fifo = "over"
        self.assertTrue(wait_for(lambda: d.telemetry()["fifo_overflow"]))

    def test_forward_and_reverse_swap_when_reverse_reads_higher(self):
        d = self.open()
        self.sim.set_telemetry(fwd_raw=500, rev_raw=3382)
        self.assertTrue(wait_for(lambda: d.telemetry().get("fwd", 0) > 1))
        tel = d.telemetry()
        self.assertAlmostEqual(tel["fwd"], 4.98, delta=0.01)       # Quisk's 3382 -> 4.98 W point
        self.assertLess(tel["rev"], tel["fwd"])
        self.assertFalse(tel["calibrated"])

    def test_swr_from_a_simulated_antenna(self):
        d = self.open()
        d.set_tx_freq(14_070_000.0)
        n = np.arange(int(0.075 * 192_000))
        tone = (0.9 * np.exp(2j * np.pi * 3_000 * n / 192_000)).astype(np.complex64)
        for want in (3.0, 1.5):
            with self.subTest(swr=want):
                self.sim.set_telemetry(swr=want)
                d.tx_start()
                d.set_drive(1.0)
                for _ in range(3):
                    d.write(tone)
                tel = d.telemetry()
                d.tx_stop()
                self.assertAlmostEqual(tel["fwd"], 5.0 * 0.81, delta=0.1)
                g = math.sqrt(tel["rev"] / tel["fwd"])
                self.assertAlmostEqual((1 + g) / (1 - g), want, delta=0.1)
                self.assertAlmostEqual(tel["swr"], want, delta=0.1)
        self.assertTrue(wait_for(lambda: d.telemetry()["fwd"] == 0.0))
        self.assertIsNone(d.telemetry()["swr"])


if __name__ == "__main__":
    unittest.main()
