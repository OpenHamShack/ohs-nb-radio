"""OpenHamShack HAM's engine on a Hermes-Lite 2 - the emulated one
(ohscore/devices/hl2sim.py) speaking the real protocol on 127.0.0.1. The
engine's side of the bargain: HF receive lands where it should, the
transmit signal sits on the HL2's NCO (inside its +-20 kHz TX path, not a
quarter of the rate away as on a Pluto), MOX only while keyed, the SWR
and TX-inhibit trips, and a clean stop. No hardware anywhere."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time
import unittest

import numpy as np

from ohscore.audio import NullAudio
from ohscore.devices import hl2
from ohscore.devices.hl2sim import HL2Sim
from ohsradio.radio import Radio


def heartbeat_for(radio, seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        radio.heartbeat()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


class Hl2Engine(unittest.TestCase):
    def setUp(self):
        self.sim = HL2Sim(tone_hz=14_080_000.0, tone_level=0.05, watchdog_s=1.0).start()
        self.addCleanup(self.sim.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {"device": "hl2", "hl2Address": self.sim.address, "hl2Rate": 192_000, "audioBackend": "null",
               "vfo": 14_074_000.0, "mode": "usb", "drive": 0.5, "callsign": "GM4BRI"}  # a UK station: Ofcom
        self.r = Radio(cfg, persist=False, data_dir=self.tmp.name, audio=NullAudio(realtime=True))
        self.r.set(authorise=True, licenceClass="full")
        self.addCleanup(self.r.stop)

    def test_receives_hf_at_the_right_frequency(self):
        wide = self.r.subscribe("wide", 256)
        self.r.start()
        self.assertEqual(self.r.dev.fs, 192_000.0)
        lines = []
        heartbeat_for(self.r, 6, until=lambda: len(lines.__iadd__(wide.drain()) or lines) > 8)
        t, start, bin_hz, db = lines[-1]
        peak = start + bin_hz * int(np.argmax(db))
        self.assertLess(abs(peak - 14_080_000.0), 2 * bin_hz)

    def test_cw_key_up_puts_the_tone_on_the_nco_and_mox_only_while_keyed(self):
        self.r.set(vfo=14_060_000.0, mode="cw")
        self.r.start()
        heartbeat_for(self.r, 0.5)
        self.assertFalse(self.sim.mox)
        self.sim.clear_tx()
        self.r.ptt(True)
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: self.sim.mox))
        heartbeat_for(self.r, 1.0)
        self.assertEqual(self.sim.regs.get(hl2.R_TX_FREQ), 14_060_000)       # the NCO on the dial
        iq = self.sim.tx_iq()
        self.r.ptt(False)
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: not self.sim.mox))
        self.assertGreater(len(iq), 24_000)
        seg = iq[-24_000:]
        f = np.fft.fftfreq(len(seg), 1 / 48_000.0)
        self.assertAlmostEqual(float(f[np.argmax(np.abs(np.fft.fft(seg * np.hanning(len(seg)))))]), 700.0, delta=5)

    def test_high_swr_unkeys(self):
        self.sim.set_telemetry(swr=4.0)
        self.r.set(vfo=14_060_000.0, mode="cw", drive=1.0)
        self.r.start()
        heartbeat_for(self.r, 0.3)
        self.r.ptt(True)
        self.assertTrue(heartbeat_for(self.r, 5, until=lambda: not self.r.state()["keyed"]))
        self.assertTrue(self.r.state()["swrTripped"])
        self.assertTrue(heartbeat_for(self.r, 2, until=lambda: not self.sim.mox))

    def test_tx_inhibit_unkeys(self):
        self.r.set(vfo=14_060_000.0, mode="cw")
        self.r.start()
        heartbeat_for(self.r, 0.3)
        self.r.ptt(True)
        heartbeat_for(self.r, 0.5)
        self.sim.tx_inhibit = True
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: not self.r.state()["keyed"]))

    def test_licence_holds_hl2_power_on_160m_secondary(self):
        # Intermediate, 1850-2000 kHz: 32 W PEP; the barefoot HL2 (5 W) is under it.
        self.r.set(authorise=True, licenceClass="intermediate")
        self.r.set(vfo=1_900_000.0, mode="lsb", drive=1.0)
        self.assertEqual(self.r.state()["licenceInfo"]["limitW"], 32.0)
        self.assertAlmostEqual(self.r.state()["maxDrive"], 1.0)

    def test_measured_forward_power_is_held_to_the_licence(self):
        # Full licence on 60 m: 100 W PEP but at most 200 W EIRP. With a
        # 20 dBi antenna the power chain estimates 5 W x 0.25 = 1.25 W PEP,
        # 125 W EIRP: no warning. The radio then reports 5 W forward - 500 W
        # EIRP - and the measurement wins: the over is unkeyed.
        from ohscore.devices.hl2sim import power_raw
        self.r.set(authorise=True, bandPower={"60m": {"antGainDbi": 20.0}})
        self.r.set(vfo=5_355_000.0, mode="cw", drive=0.5)
        self.assertEqual(self.r.state()["licenceInfo"]["powerWarning"], "")
        self.assertTrue(self.r.state()["licenceInfo"]["measured"])
        toasts = self.r.subscribe("toast", 64)
        self.r.start()
        heartbeat_for(self.r, 0.3)
        self.r.ptt(True)
        self.assertTrue(heartbeat_for(self.r, 0.5, until=lambda: self.r.state()["keyed"]))
        self.sim.set_telemetry(fwd_raw=power_raw(5.0), rev_raw=0)
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: not self.r.state()["keyed"]))
        said = [t["text"] for t in toasts.drain()]
        self.assertTrue(any("200 W EIRP maximum on 60 m" in t and "measured" in t for t in said), said)

    def test_measured_forward_power_under_the_licence_keeps_keyed(self):
        from ohscore.devices.hl2sim import power_raw
        self.r.set(vfo=5_355_000.0, mode="cw", drive=0.5)
        self.r.start()
        heartbeat_for(self.r, 0.3)
        self.r.ptt(True)
        self.sim.set_telemetry(fwd_raw=power_raw(5.0), rev_raw=0)   # 5 W EIRP with a 0 dBi antenna
        heartbeat_for(self.r, 1.5)
        self.assertTrue(self.r.state()["keyed"])
        self.assertGreater(self.r.state()["fwdW"], 4.0)
        self.r.ptt(False)

    def test_hl2_receiver_gain_is_applied_to_the_running_radio(self):
        self.r.set(vfo=14_079_000.0, mode="usb", hl2Lna=20.0)         # the emulator's tone 1 kHz up, in the passband
        meter = self.r.subscribe("meter", 256)
        self.r.start()
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: self.sim.lna_db == 20.0))
        dev, starts, finds = self.r.dev, len(self.sim.start_cmds), self.sim.discovery_requests
        heartbeat_for(self.r, 1.0)
        before = [m["rx"] for m in meter.drain()][-3:]
        self.r.set(hl2Lna=32.0)
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: self.sim.lna_db == 32.0))
        meter.drain()
        heartbeat_for(self.r, 1.0)
        after = [m["rx"] for m in meter.drain()][-3:]
        # The same radio, never rediscovered, stopped or started: a live change, not a reopen.
        self.assertIs(self.r.dev, dev)
        self.assertEqual((len(self.sim.start_cmds), self.sim.discovery_requests), (starts, finds))
        self.assertTrue(before and after)
        self.assertAlmostEqual(sum(after) / len(after) - sum(before) / len(before), 12.0, delta=2.0)

    def test_two_metres_is_out_of_its_reach(self):
        self.r.start()
        with self.assertRaisesRegex(ValueError, "receives"):
            self.r.band("2m")

    def test_stop_leaves_it_unkeyed_and_quiet(self):
        self.r.set(vfo=14_060_000.0, mode="cw")
        self.r.start()
        heartbeat_for(self.r, 0.3)
        self.r.ptt(True)
        heartbeat_for(self.r, 0.5, until=lambda: self.sim.mox)
        self.r.stop()
        self.assertTrue(heartbeat_for(self.r, 3, until=lambda: not self.sim.mox and not self.sim.streaming))


if __name__ == "__main__":
    unittest.main()
