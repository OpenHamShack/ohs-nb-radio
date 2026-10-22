"""TX lock on an IC-9700 keyed by CAT PTT for NB's own digital overs
(ohsnb/radio.py _rig_keyed/_rig_unkeyed, Ray 12/10/2026): his FT8 landed
+840 Hz off over after over, and TX lock went "searching" -> "idle" each
time, never found, never corrected - it only ever corrected from a CW
carrier, and looked for a digital over by the edge of the SSB passband.

End to end here: the real Radio on the simulated transponder, the real
CI-V driver over TCP to the emulated 9700, and the emulated 9700
transmitting what its USB sound device is playing - NB's own FT8 or FT4
audio, as it plays - through the simulated upconverter and transponder,
landing `ul_err` off where it is aimed. So where NB finds it, and whether
the next over goes where it should, is measured against the emulator's
own frequency, not against what NB believes.

FT8/FT4 come from the real encoder when ohsdigi is built here, else from
an FT8- or FT4-shaped stand-in (the same tone spacing and symbol length,
random symbols). No serial port, sound card or radio is opened.
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
from ohscore.dsp.bank import Geometry
from ohscore.modes import ft8 as ft8mod
from ohscore.rig.civsim import CivSim
from ohsnb import bandplan
from ohsnb.devices.sim import SimDevice
from ohsnb.dsp.lock import TxMonitor
from ohsnb.extrig import UplinkPlan
from ohsnb.radio import RIG_RX_MOVE_HZ, RIG_STEP_MAX_HZ, Radio

LO = 1_104_000_000.0                 # Ray's upconverter: 1296 MHz IF, low side
FT8_DIAL = 10_489_540_000.0
DEVICE = "IC-9700 USB Audio CODEC"
OFFSET = 1500.0                      # ft8TxOffset, as Ray has it
# (tone spacing Hz, symbol s, symbols, tones) - the stand-in's shape
SHAPE = {"ft8": (6.25, 0.16, 79, 8), "ft4": (20.833, 0.048, 105, 4)}
LENGTH = {"ft8": 12.6, "ft4": 5.0}   # s: an over of each, whole


def wait_for(cond, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def soon(now, mode, period=None):
    # A moment from now rather than on a real slot: the test does not wait
    # for the next 15 s boundary, and nothing about the lock depends on it.
    return now + 0.3


def stand_in(mode: str, freq: float, seed: int = 3) -> np.ndarray:
    """An FT8/FT4-shaped over: continuous-phase FSK at the mode's spacing
    and symbol rate, random symbols, starting at `freq`."""
    df, ts, n, tones = SHAPE[mode]
    rng = np.random.default_rng(seed)
    f = freq + df * np.repeat(rng.integers(0, tones, n), int(round(ts * RATE)))
    return (0.5 * np.sin(2 * np.pi * np.cumsum(f) / RATE)).astype(np.float32)


class RadioCard(NullAudio):
    """The 9700's USB sound device: keeps what NB writes to it, and gives
    it to the emulated radio's modulator as it plays (from each chunk's
    play time on), so the emulated uplink carries NB's audio at the time
    a real sound card would have played it."""

    def __init__(self):
        super().__init__(realtime=True)
        self.lock = threading.Lock()
        self.queue: list[tuple[float, np.ndarray]] = []

    def open_tx_out(self, device, gain=1.0):
        out = super().open_tx_out(device, gain)
        write = out.write

        def keep(audio):
            n = len(out.chunks)
            write(audio)
            with self.lock:
                self.queue.extend(out.chunks[n:])
        out.write = keep
        return out

    def pull(self, n: int) -> np.ndarray:
        out = np.zeros(n, np.float32)
        i = 0
        now = time.monotonic()
        with self.lock:
            while i < n and self.queue and self.queue[0][0] <= now:
                t, a = self.queue[0]
                c = min(len(a), n - i)
                out[i:i + c] = a[:c]
                if c == len(a):
                    self.queue.pop(0)
                else:
                    self.queue[0] = (t, a[c:])
                i += c
        return out


class CatLock(unittest.TestCase):
    ul_err = 840.0          # Ray's: where the 9700 + upconverter really lands, relative to where it is aimed
    level_db = -8.0         # its downlink relative to the beacon
    mode = "ft8"
    extra_cfg: dict = {}

    @classmethod
    def setUpClass(cls):
        # RIG_RX_SETTLED_S of steady beacon lock before an over corrects:
        # the simulator's lock is steady from the start, and the tests
        # need not wait 30 s for it (Disagreeing tests the wait itself).
        cls.settled = mock.patch("ohsnb.radio.RIG_RX_SETTLED_S", 0.0)
        cls.settled.start()

    @classmethod
    def tearDownClass(cls):
        cls.settled.stop()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch("ohscore.engine.slot_start", soon)
        p.start()
        self.addCleanup(p.stop)
        self.plan = UplinkPlan(Converter.from_dict(rig_conv(LO, "low")["converters"][-1]))
        self.civ = CivSim(freq=int(self.plan.rig_hz(bandplan.ul(FT8_DIAL)))).start()
        self.addCleanup(self.civ.stop)
        cfg = sim_cfg(txRadio="civ", **rig_conv(LO, "low"), vfo=FT8_DIAL, mode="usb", simRealtime=True,
                      rigPollMs=50, callsign="GM4BRI", licenceClass="full", watchdogSec=10.0, rigCatPtt=True,
                      rigTxAudioOut=DEVICE, rigPttDelayMs=100, rigPttTailMs=50, civPort=self.civ.url,
                      **self.extra_cfg)
        self.dev = SimDevice(dict(cfg))
        self.card = RadioCard()
        self.dev.attach_external(self._uplink, audio=self.card.pull)
        self.r = Radio(cfg, persist=False, data_dir=self.tmp, audio=self.card, device=self.dev)
        if not ft8mod.CAN_ENCODE.get(self.mode):
            real = self.r._render
            self.r._render = lambda mode, msg: (stand_in(mode, float(msg.get("freq", OFFSET)))
                                                if mode in SHAPE else real(mode, msg))
        self.toasts = self.r.subscribe("toast", 256)
        self.r.start()
        self.addCleanup(self.r.stop)

    def _uplink(self):
        if not self.civ.tx:
            return None
        return self.plan.ul_of(self.civ.freq) + self.ul_err, "audio", self.level_db

    def st(self):
        return self.r.state()

    def landing_error(self) -> float:
        """Where the emulated 9700's signal really lands, relative to NB's
        transmit dial (the radio's carrier; the audio offset is on top of
        both): the truth TX lock should drive to zero."""
        s = self.st()
        return self.plan.ul_of(self.civ.freq) + self.ul_err - bandplan.ul(s["txDial"])

    def ready(self):
        def tuned():
            s = self.st()
            want = int(round(self.plan.rig_hz(bandplan.ul(s["txDial"]) + s["rigTxCorr"])))
            return s["rigLink"] == "ok" and self.civ.freq == want
        self.assertTrue(wait_for(tuned))
        self.assertTrue(wait_for(lambda: self.st()["rxLock"] == "locked", timeout=20))
        self.r.set(mode=self.mode)
        self.assertTrue(wait_for(lambda: self.civ.data and self.r.ext.link.mod_input is not None))
        self.assertTrue(wait_for(tuned))
        time.sleep(1.0)                     # the monitor learns the band unkeyed

    def over(self) -> list[dict]:
        """One CAT over of the mode at OFFSET; the status as it went, sampled."""
        seen = []
        self.r.send(self.mode, text="CQ GM4BRI IO75", freq=OFFSET)
        self.assertTrue(wait_for(lambda: self.civ.tx and self.st()["rigKeyed"], timeout=4))
        while self.civ.tx or self.st()["keyed"]:
            self.r.heartbeat()              # the window, alive: a whole FT8 over outlasts the watchdog
            seen.append(self.st())
            time.sleep(0.1)
            self.assertLess(len(seen), 250, "the over never ended")
        self.assertTrue(wait_for(lambda: not self.st()["rigKeyed"], timeout=3))
        # The whole over went, not a watchdog's or a guard's first seconds.
        self.assertGreaterEqual(len(self.card.tx_outs[-1].samples()) / RATE, LENGTH[self.mode])
        return seen

    def corrected(self, before: float) -> bool:
        """The correction has been applied and the radio retuned to it."""
        def ok():
            s = self.st()
            want = int(round(self.plan.rig_hz(bandplan.ul(s["txDial"]) + s["rigTxCorr"])))
            return s["rigTxCorr"] != before and self.civ.freq == want
        return wait_for(ok, timeout=4)

    def test_lands_off_is_found_corrected_and_locks_on_the_next_over(self):
        self.ready()
        self.assertFalse(self.st()["rigTxCorrTrusted"])
        self.assertAlmostEqual(self.landing_error(), self.ul_err, delta=1.0)
        seen = self.over()
        # Found where it really went: LANDED, the error and the level.
        found = [s for s in seen if s["txLockState"] in ("landed", "locked")]
        self.assertTrue(found, "TX lock never found the over: " + repr({s["txLockState"] for s in seen}))
        self.assertEqual(found[-1]["txLockState"], "landed")
        self.assertAlmostEqual(found[-1]["txErr"], self.ul_err, delta=15.0)
        self.assertAlmostEqual(found[-1]["ownDl"] - found[-1]["txDial"], self.ul_err, delta=15.0)
        self.assertAlmostEqual(found[-1]["vsBeacon"], self.level_db, delta=3.0)
        # Corrected between overs, through the 9700's frequency, and trusted.
        self.assertTrue(self.corrected(0.0))
        s = self.st()
        self.assertAlmostEqual(s["rigTxCorr"], -self.ul_err, delta=15.0)
        self.assertTrue(s["rigTxCorrTrusted"])
        self.assertAlmostEqual(self.landing_error(), 0.0, delta=15.0)
        self.assertTrue(any("corrected for the next over" in t["text"] for t in self.toasts.drain()))
        self.assertEqual(s["txCorr"], 0.0)          # the Pluto's correction is not the 9700's
        # The next over goes where the dial says: TX LOCKED.
        time.sleep(0.5)
        seen = self.over()
        locked = [s for s in seen if s["txLockState"] == "locked"]
        self.assertTrue(locked, "not locked on the second over: " + repr({s["txLockState"] for s in seen}))
        self.assertLess(abs(locked[-1]["txErr"]), 25.0)
        self.assertLess(abs(locked[-1]["ownDl"] - locked[-1]["txDial"]), 25.0)
        self.assertLess(abs(self.landing_error()), 15.0)
        # Every key-up and unkey was NB's own CAT PTT, one pair per over.
        on, off = bytes([0x1C, 0x00, 0x01]), bytes([0x1C, 0x00, 0x00])
        self.assertEqual(self.civ.ptt_commands(), [on, off, on, off])


class CatLockFt4(CatLock):
    mode = "ft4"


class CatLockFar(CatLock):
    """5 kHz off: one over moves it RIG_STEP_MAX_HZ, no more."""
    mode = "ft4"
    ul_err = 5_000.0
    extra_cfg = {"rigTxCorrMaxHz": 10_000.0}        # the default would refuse 5 kHz outright

    def test_lands_off_is_found_corrected_and_locks_on_the_next_over(self):
        self.ready()
        seen = self.over()
        found = [s for s in seen if s["txLockState"] == "landed"]
        self.assertTrue(found)
        self.assertAlmostEqual(found[-1]["txErr"], self.ul_err, delta=15.0)
        self.assertTrue(self.corrected(0.0))
        self.assertAlmostEqual(self.st()["rigTxCorr"], -RIG_STEP_MAX_HZ, delta=0.01)
        self.assertAlmostEqual(self.landing_error(), self.ul_err - RIG_STEP_MAX_HZ, delta=1.0)
        self.assertTrue(any("the most one over moves it" in t["text"] for t in self.toasts.drain()))


class NotFollowing(CatLock):
    """Ray, 13/10/2026 (0.1.18): the downlink TX lock found did not move
    when the 9700 did, and each over's error was added to the last -
    -827, -1760, -1761, -1093 Hz - until rigTxCorr was +5441 Hz and went on
    air. Here the emulated 9700 obeys every frequency NB writes but keeps
    transmitting where it was at the first over, so each correction is
    written and none shows on the downlink. Up to 0.1.18 rigTxCorr went
    -840, -1680, -2520; now the second over sees the first correction did
    not take effect, puts it back and stops."""
    mode = "ft4"

    def _uplink(self):
        if not self.civ.tx:
            return None
        if getattr(self, "stuck", None) is None:
            self.stuck = self.civ.freq
        return self.plan.ul_of(self.stuck) + self.ul_err, "audio", self.level_db

    def test_lands_off_is_found_corrected_and_locks_on_the_next_over(self):
        self.ready()
        self.over()
        self.assertTrue(self.corrected(0.0))
        first = self.st()["rigTxCorr"]
        self.assertAlmostEqual(first, -self.ul_err, delta=15.0)
        self.assertNotEqual(self.civ.freq, self.stuck)      # written to the radio...
        time.sleep(0.5)
        self.over()                                         # ...and not seen on the downlink
        self.assertTrue(self.corrected(first))
        s = self.st()
        self.assertEqual(s["rigTxCorr"], 0.0)
        self.assertIn("TX lock stopped correcting", (s["txWarning"] or {}).get("text", ""))
        self.assertTrue(any("TX lock stopped correcting" in t["text"] for t in self.toasts.drain()))
        time.sleep(0.5)
        self.over()                                         # held: no third step
        time.sleep(0.5)
        self.assertEqual(self.st()["rigTxCorr"], 0.0)
        # Off and on again lifts the hold.
        self.r.set(txLock=False)
        self.r.set(txLock=True)
        self.assertNotIn("TX lock stopped", (self.st()["txWarning"] or {}).get("text", ""))


class StoredBeyondTheLimit(CatLock):
    """A rigTxCorr 0.1.18 ran up and saved (+5441 Hz, Ray) is not used:
    it goes back to 0 at start, and the radio is tuned without it."""
    extra_cfg = {"rigTxCorr": 5441.1, "rigTxCorrTrusted": True}

    def test_lands_off_is_found_corrected_and_locks_on_the_next_over(self):
        s = self.st()
        self.assertEqual(s["rigTxCorr"], 0.0)
        self.assertFalse(s["rigTxCorrTrusted"])
        want = int(round(self.plan.rig_hz(bandplan.ul(s["txDial"]))))
        self.assertTrue(wait_for(lambda: self.civ.freq == want))
        self.assertTrue(any("reset to 0" in t["text"] for t in self.toasts.drain()))


class Disagreeing(unittest.TestCase):
    """An over whose measurements do not agree corrects nothing: the
    decision at the end of an over, fed measurements directly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cfg = sim_cfg(txRadio="civ", **rig_conv(LO, "low"), vfo=FT8_DIAL, civPort="tcp://127.0.0.1:9")
        self.r = Radio(cfg, persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False),
                       device=SimDevice(dict(cfg)))
        # Not started: only the monitor the decision tells the over ended.
        self.r.geo = Geometry(1_200_000.0)
        self.r.monitor = TxMonitor(self.r.geo)
        self.r._derive()                    # the dials (txDial) from vfo, as start() would
        self.steady()

    def steady(self, since=60.0):
        """Beacon lock in Auto, locked on the middle beacon for `since` s."""
        self.r.st["beaconMode"] = "auto"
        self.r._status(rxLock="locked", beaconUsed="middle")
        self.r.rx_steady_since = time.monotonic() - since

    def end_over(self, errs, how="spectrum", rig_hz=None, rx_move=0.0):
        """An over: keyed with the receive reference as it is, these
        measurements (against the dial, the radio where rigTxCorr puts it
        unless `rig_hz` says otherwise), rxCorr moved by rx_move, unkeyed."""
        r = self.r
        r.rig_rx = (r.rx_steady_since, r.st["rxCorr"])
        r.rig_rx_t0 = time.monotonic()
        corr = r.st["rigTxCorr"]
        r.rig_over = [(how, e, e - corr, f) for e, f in zip(errs, rig_hz or [None] * len(errs))]
        r.st["rxCorr"] += rx_move
        r._rig_unkeyed(apply=True)
        return r.state()

    def test_rays_overs_of_13_october_stop_after_one_step(self):
        # His four overs, as measured: the error did not change when the
        # correction did. 0.1.18 ended at +5441 Hz.
        s = self.end_over([-827.0, -826.0])
        self.assertAlmostEqual(s["rigTxCorr"], 827.0, delta=1.0)
        s = self.end_over([-1760.0] * 11 + [-1500.0])
        self.assertEqual(s["rigTxCorr"], 0.0)               # the unseen step undone
        self.assertTrue(self.r.rig_held)
        for errs in ([-1761.0] * 9, [-1093.0, -1093.0]):
            s = self.end_over(errs)
            self.assertEqual(s["rigTxCorr"], 0.0)
        self.assertIn("TX lock stopped correcting", s["txWarning"]["text"])

    def test_a_correction_that_shows_is_followed_by_small_ones(self):
        # A good evening (13/10, 22:32-22:53): within +-20 Hz, over after over.
        s = self.end_over([840.0, 841.0, 839.0])
        self.assertAlmostEqual(s["rigTxCorr"], -840.0, delta=1.0)
        for e in (16.0, -18.0, 19.0, -9.0, 4.0):
            s = self.end_over([e, e + 1.0, e - 1.0])
            self.assertFalse(self.r.rig_held)
        self.assertLess(abs(s["rigTxCorr"] + 840.0), 25.0)

    def test_beyond_the_limit_is_shown_not_corrected(self):
        s = self.end_over([1500.0, 1501.0, 1499.0])         # the default limit is 1 kHz
        self.assertEqual(s["rigTxCorr"], 0.0)
        self.assertIn("more than the 1000 Hz", s["txWarning"]["text"])
        self.r.set(rigTxCorrMaxHz=2000.0)
        s = self.end_over([1500.0, 1501.0, 1499.0])
        self.assertAlmostEqual(s["rigTxCorr"], -1500.0, delta=1.0)
        self.assertNotIn("more than the", (s["txWarning"] or {}).get("text", ""))

    def test_a_radio_that_moved_during_the_over_corrects_nothing(self):
        # Its knob turned mid-over (SHACK-XW21).
        s = self.end_over([300.0, 302.0, 301.0], rig_hz=[1_296_040_000.0, 1_296_040_000.0, 1_296_041_000.0])
        self.assertEqual(s["rigTxCorr"], 0.0)

    def test_an_unsteady_receive_reference_corrects_nothing(self):
        self.steady(since=5.0)                              # locked, but only just
        self.assertEqual(self.end_over([300.0, 301.0])["rigTxCorr"], 0.0)
        self.steady()
        self.assertEqual(self.end_over([300.0, 301.0], rx_move=RIG_RX_MOVE_HZ + 20.0)["rigTxCorr"], 0.0)
        self.r._status(beaconUsed="")                       # coasting: the beacon rejected
        self.assertEqual(self.end_over([300.0, 301.0])["rigTxCorr"], 0.0)
        self.steady()
        self.r.st["beaconMode"] = "hold"
        self.assertEqual(self.end_over([300.0, 301.0])["rigTxCorr"], 0.0)
        self.steady()
        self.assertAlmostEqual(self.end_over([300.0, 301.0])["rigTxCorr"], -300.5, delta=0.1)

    def test_changing_the_receive_reference_by_hand_restarts_the_clock(self):
        self.r.set(rxCorr=self.r.st["rxCorr"] + 400.0)
        self.assertIsNone(self.r.rx_steady_since)
        self.assertEqual(self.end_over([300.0, 301.0])["rigTxCorr"], 0.0)

    def test_scattered_measurements_correct_nothing(self):
        s = self.end_over([840.0, -1200.0, 3100.0, 20.0])
        self.assertEqual(s["rigTxCorr"], 0.0)
        self.assertFalse(s["rigTxCorrTrusted"])

    def test_one_stray_among_agreeing_ones_is_ignored(self):
        s = self.end_over([838.0, 842.0, 5600.0, 841.0, 839.0])
        self.assertAlmostEqual(s["rigTxCorr"], -840.0, delta=1.5)
        self.assertTrue(s["rigTxCorrTrusted"])

    def test_one_find_alone_corrects_nothing(self):
        # A short line whose signal never came down can still turn up one
        # "confident" find in noise.
        s = self.end_over([1730.0])
        self.assertEqual(s["rigTxCorr"], 0.0)

    def test_a_find_on_a_beacon_is_never_ours(self):
        # 40 kHz below the FT8 dial is the lower beacon: a CAT over whose
        # signal never came down matched it there, alike each time. (No
        # over in flight here, so what is judged is a carrier at the dial.)
        for e in (-39_985.0, -39_988.0, -39_990.0):
            self.r._rig_measure({"how": "spectrum", "err": e}, {}, None)
        self.assertNotEqual(self.r.state()["txLockState"], "landed")
        self.r._rig_unkeyed(apply=True)
        self.assertEqual(self.r.state()["rigTxCorr"], 0.0)

    def test_the_band_edge_of_an_unknown_signal_never_corrects(self):
        s = self.end_over([700.0, 705.0, 702.0], how="band")
        self.assertEqual(s["rigTxCorr"], 0.0)


if __name__ == "__main__":
    unittest.main()
