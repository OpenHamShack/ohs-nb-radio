"""An IC-9700 as OpenHamShack NB's uplink transmitter (ohsnb/extrig.py), end to
end: the real Radio on the simulated transponder, the real CI-V (or
rigctld) driver talking over TCP to the emulated radio, and the emulated
radio's own transmissions put through the simulated transponder by the
frequency and transmit state the emulator holds - so what NB sees on its
scope is where the "radio" really sent it, not what NB thinks it sent.

Every test ends by checking that nothing that could key the radio was
sent to it. No serial port or real radio is opened.
"""
from __future__ import annotations
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import shutil
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from helpers import rig_conv, sim_cfg
from ohscore.audio import NullAudio
from ohscore.engine import TxRefused
from ohscore.rig.civsim import CivSim
from ohscore.rig.rigctlsim import RigctldSim
from ohsnb import bandplan
from ohsnb.devices.sim import SimDevice
from ohscore.converters import Converter
from ohsnb.extrig import UplinkPlan
from ohsnb.radio import Radio

# DXPatrol MK4's LO for its 1296 MHz IF (docs/ic9700-research.md): a real
# low-side 23 cm upconverter, so the IFs in these tests are ones Ray's
# kind of setup produces.
LO = 1_104_000_000.0
VFO = 10_489_700_000.0


class RecAudio(NullAudio):
    """Records when receive audio was played and how loud."""

    def __init__(self):
        super().__init__(realtime=False)
        self.log: list[tuple[float, float]] = []

    def play(self, audio):
        super().play(audio)
        a = np.asarray(audio, np.float64)
        self.log.append((time.monotonic(), float(np.sqrt(np.mean(a * a))) if len(a) else 0.0))

    def rms_between(self, t0: float, t1: float) -> list[float]:
        return [r for t, r in list(self.log) if t0 <= t <= t1]


def wait_for(cond, timeout=8.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class Rig(unittest.TestCase):
    link = "civ"
    lo = LO
    side = "low"
    ul_err = 700.0          # where the 9700 + upconverter really lands, relative to where it is aimed
    level_db = -6.0         # its downlink relative to the beacon
    cfg_over: dict = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.plan = UplinkPlan(Converter.from_dict(rig_conv(self.lo, self.side)["converters"][-1]))
        start_if = int(self.plan.rig_hz(bandplan.ul(VFO)) - 10_000)
        if self.link == "civ":
            self.civ = CivSim(freq=start_if).start()
            self.addCleanup(self.civ.stop)
            link = {"civPort": self.civ.url}
        else:
            self.civ = RigctldSim(freq=start_if).start()
            self.addCleanup(self.civ.stop)
            link = {"rigctldHost": self.civ.host, "rigctldPort": self.civ.port}
        # callsign + licenceClass: a known licence (QO-100 allowed under
        # Ofcom Full), so the "licence" warning (no class set) never
        # stands here and competes with "rig-aim" or "level".
        cfg = sim_cfg(txRadio=self.link, **rig_conv(self.lo, self.side), vfo=VFO, mode="usb",
                      simRealtime=True, rigPollMs=50, callsign="GM4BRI", licenceClass="full", **link)
        cfg.update(self.cfg_over)
        self.dev = SimDevice(dict(cfg))
        self.dev.attach_external(self._uplink)
        self.audio = RecAudio()
        self.r = Radio(cfg, persist=False, data_dir=self.tmp, audio=self.audio, device=self.dev)
        self.toasts = self.r.subscribe("toast", 256)
        self.r.start()
        self.addCleanup(self.r.stop)

    def tearDown(self):
        self.assertEqual(self.civ.ptt_commands(), [], "a command that could key the radio was sent")

    # -- the emulated radio's RF, through the simulated transponder ---------
    def _rig_mode(self) -> str:
        m = self.civ.mode
        return m.lower() if isinstance(m, str) else m

    def _uplink(self):
        tx = self.civ.tx if self.link == "civ" else self.civ.ptt
        if not tx:
            return None
        kind = "carrier" if self._rig_mode() in ("cw", "cw-r") else "voice"
        return self.plan.ul_of(self.civ.freq) + self.ul_err, kind, self.level_db

    def key(self, on: bool):
        self.civ.key(on)

    def set_rig_mode(self, mode: str):
        if self.link == "civ":
            self.civ.set_mode(mode)
        else:
            self.civ.mode = mode.upper()

    def st(self):
        return self.r.state()

    def toast_texts(self):
        return [t["text"] for t in self.toasts.drain()]

    def settled(self):
        """The link is up and the radio is where NB's transmit dial says."""
        want = int(round(self.plan.rig_hz(bandplan.ul(self.st()["txDial"]) + self.st()["rigTxCorr"])))
        return wait_for(lambda: self.st()["rigLink"] == "ok" and self.civ.freq == want)


class Tuning(Rig):
    def test_nb_puts_the_9700_where_its_transmit_dial_is(self):
        self.assertTrue(self.settled())
        self.assertEqual(self.civ.freq, 1_296_200_000)        # 2400.2 MHz up = 1104 + 1296.2
        self.r.set(vfo=10_489_712_340.0)
        self.assertTrue(wait_for(lambda: self.civ.freq == 1_296_212_340))
        self.r.set(split=True, txVfo=10_489_800_000.0)
        self.assertTrue(wait_for(lambda: self.civ.freq == 1_296_300_000))
        self.assertEqual(self.st()["vfo"], 10_489_712_340.0)

    def test_turning_the_9700_moves_the_tx_marker_and_the_receive_dial(self):
        self.assertTrue(self.settled())
        self.civ.turn(1_296_205_000)
        self.assertTrue(wait_for(lambda: self.st()["txDial"] == VFO + 5000))
        self.assertEqual(self.st()["vfo"], VFO + 5000)
        self.assertFalse(self.st()["split"])
        time.sleep(0.3)
        self.assertEqual(self.civ.freq, 1_296_205_000)        # NB did not pull it back

    def test_the_mode_follows_the_9700s_sideband(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("cw")
        self.assertTrue(wait_for(lambda: self.st()["mode"] == "cw", timeout=4))
        self.set_rig_mode("lsb")
        self.assertTrue(wait_for(lambda: self.st()["mode"] == "lsb", timeout=4))
        self.r.set(mode="ft8")                                 # decoding the 9700's data: left alone
        self.set_rig_mode("usb")
        time.sleep(1.5)
        self.assertEqual(self.st()["mode"], "ft8")

    def test_fm_on_the_9700_is_switched_to_usb_and_said(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("fm")
        self.assertTrue(wait_for(lambda: self._rig_mode() == "usb", timeout=4))
        self.assertTrue(wait_for(lambda: self.st()["rigMode"] == "usb", timeout=4))
        self.assertTrue(any("was in FM" in t and "USB" in t for t in self.toast_texts()))
        self.assertEqual(self.st()["mode"], "usb")

    def test_fm_is_left_until_the_over_ends(self):
        self.assertTrue(self.settled())
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        self.set_rig_mode("fm")
        time.sleep(1.5)
        self.assertEqual(self._rig_mode(), "fm")
        self.key(False)
        self.assertTrue(wait_for(lambda: self._rig_mode() == "usb", timeout=4))

    def test_other_modes_are_never_changed(self):
        self.assertTrue(self.settled())
        for mode in ("am", "cw", "lsb"):
            self.set_rig_mode(mode)
            time.sleep(1.3)
            self.assertEqual(self._rig_mode(), mode)
        self.assertEqual(self.civ.mode_sets, [])

    def test_nb_will_not_key_its_own_transmitter_instead(self):
        self.assertTrue(self.settled())
        with self.assertRaises(TxRefused) as cm:
            self.r.ptt(True)
        self.assertIn("key it on the radio", str(cm.exception))
        self.assertFalse(self.dev.tx_active)

    def test_aiming_at_a_beacon_is_flagged_and_keying_there_warns(self):
        self.assertTrue(self.settled())
        self.civ.turn(int(self.plan.rig_hz(bandplan.ul(10_489_748_000.0))))
        self.assertTrue(wait_for(lambda: "beacon" in self.st()["rigTxBlocked"]))
        self.key(True)
        # The transmit card's standing warning while it transmits there,
        # not a toast; gone once the radio is back on receive.
        self.assertTrue(wait_for(lambda: "cannot unkey" in (self.st()["txWarning"].get("text") or "")))
        self.assertEqual(self.st()["txWarning"]["level"], "error")
        self.assertFalse(any("cannot unkey" in t for t in self.toast_texts()))
        self.key(False)
        self.assertTrue(wait_for(lambda: self.st()["txWarning"].get("key") != "rig-aim"))


class KnobOnlySplit(Rig):
    cfg_over = {"rigRxFollows": False}

    def test_with_follow_off_the_knob_drives_split(self):
        self.assertTrue(self.settled())
        self.civ.turn(1_296_230_000)
        self.assertTrue(wait_for(lambda: self.st()["txDial"] == VFO + 30_000))
        self.assertTrue(self.st()["split"])
        self.assertEqual(self.st()["vfo"], VFO)


class HighSide(Rig):
    """LO - IF = uplink: the spectrum is inverted."""
    lo = 3_696_200_000.0           # with a 23 cm IF: 3696.2 - 1296.0 = 2400.2 MHz
    side = "high"

    def test_inverted_mixing_runs_the_knob_backwards_and_swaps_sidebands(self):
        self.assertTrue(self.settled())
        self.assertEqual(self.civ.freq, 1_296_000_000)
        self.civ.turn(1_296_001_000)                           # knob up 1 kHz ...
        self.assertTrue(wait_for(lambda: self.st()["txDial"] == VFO - 1000))   # ... uplink down 1 kHz
        self.set_rig_mode("usb")
        self.assertTrue(wait_for(lambda: self.st()["rigMode"] == "lsb", timeout=4))
        self.assertEqual(self.st()["mode"], "lsb")

    def test_fm_goes_to_lsb_on_the_radio_which_is_usb_on_air(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("fm")
        self.assertTrue(wait_for(lambda: self._rig_mode() == "lsb", timeout=4))
        self.assertTrue(wait_for(lambda: self.st()["rigMode"] == "usb", timeout=4))


class FmLeftAlone(Rig):
    cfg_over = {"rigFmToSsb": False}

    def test_with_the_setting_off_fm_stays_and_is_warned_about(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("fm")
        self.assertTrue(wait_for(lambda: self.st()["rigMode"] == "fm", timeout=4))
        time.sleep(1.3)
        self.assertEqual(self.civ.mode_sets, [])
        self.assertIn("FM is not used", self.st()["rigTxBlocked"])


class TxLock(Rig):
    @classmethod
    def setUpClass(cls):
        # The simulator's beacon lock is steady from the start; the 30 s it
        # must hold before an over corrects (RIG_RX_SETTLED_S) is tested in
        # test_extrig_txlock.Disagreeing, not waited for here.
        cls.settled_patch = mock.patch("ohsnb.radio.RIG_RX_SETTLED_S", 0.0)
        cls.settled_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.settled_patch.stop()

    def over(self, seconds: float):
        n = len(self.civ.sets)
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        time.sleep(seconds)
        s = self.st()
        # Nothing was sent to the radio while it transmitted.
        self.assertEqual(len(self.civ.sets), n)
        self.key(False)
        self.assertTrue(wait_for(lambda: not self.st()["rigKeyed"]))
        return s

    def test_a_cw_carrier_lands_off_and_is_corrected_between_overs(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("cw")
        self.assertTrue(wait_for(lambda: self.st()["rigMode"] == "cw", timeout=4))
        self.assertTrue(wait_for(lambda: self.st()["rxLock"] == "locked", timeout=15))
        time.sleep(1.0)                                        # the monitor learns the band unkeyed
        before = self.civ.freq
        s = self.over(4.0)
        # Shown landing where it really went ...
        self.assertAlmostEqual(s["ownDl"] - s["txDial"], self.ul_err, delta=10.0)
        self.assertAlmostEqual(s["vsBeacon"], self.level_db, delta=2.0)
        # ... and corrected as soon as it was back on receive.
        self.assertTrue(wait_for(lambda: abs(self.st()["rigTxCorr"] + self.ul_err) < 10.0))
        self.assertTrue(wait_for(lambda: abs(self.civ.freq - (before - self.ul_err)) < 10))
        self.assertTrue(any("corrected for the next over" in t for t in self.toast_texts()))
        time.sleep(0.6)
        s = self.over(3.0)
        self.assertAlmostEqual(s["ownDl"], s["txDial"], delta=10.0)
        self.assertEqual(s["txLockState"], "locked")
        self.assertEqual(self.st()["txCorr"], 0.0)              # the Pluto's correction is untouched

    def test_speech_is_shown_where_it_landed_but_never_corrected(self):
        self.assertTrue(self.settled())
        self.assertTrue(wait_for(lambda: self.st()["rxLock"] == "locked", timeout=15))
        time.sleep(1.0)
        s = self.over(4.0)
        self.assertAlmostEqual(s["ownDl"] - s["txDial"], self.ul_err, delta=300.0)
        time.sleep(0.5)
        self.assertEqual(self.st()["rigTxCorr"], 0.0)


class OverTheBeacon(Rig):
    level_db = 4.0
    over = TxLock.over

    def test_the_9700_over_the_beacon_is_one_standing_warning(self):
        self.assertTrue(self.settled())
        self.assertTrue(wait_for(lambda: self.st()["rxLock"] == "locked", timeout=15))
        time.sleep(1.0)
        self.toast_texts()
        s = self.over(4.0)
        self.assertEqual(s["txWarning"].get("key"), "level", (s["vsBeacon"], s["rigTxBlocked"], s["mode"]))
        self.assertIn("reduce power on the IC-9700", s["txWarning"]["text"])
        # Kept after the over, in the past tense; never a toast.
        self.assertTrue(wait_for(lambda: "last over" in (self.st()["txWarning"].get("text") or "")))
        self.assertFalse(any("beacon" in t.lower() and "above" in t.lower() for t in self.toast_texts()))


class Audio(Rig):
    """Receive audio while the 9700 transmits (Settings > Transmitter)."""

    def played(self, t0, t1):
        return self.audio.rms_between(t0, t1)

    def test_muted_as_soon_as_it_transmits_and_back_after_its_downlink(self):
        self.assertTrue(self.settled())
        time.sleep(0.3)
        t_key = time.monotonic()
        self.key(True)
        self.assertTrue(wait_for(lambda: self.played(t_key, time.monotonic()) and
                                 self.played(t_key, time.monotonic())[-1] == 0.0, timeout=2))
        muted_at = next(t for t, r in self.audio.log if t >= t_key and r == 0.0)
        latency = muted_at - t_key
        # One poll (50 ms here) plus a receive block (75 ms) and the
        # transaction; the guide states the figure for the default poll.
        self.assertLess(latency, 0.35)
        time.sleep(0.5)
        self.assertTrue(all(r == 0.0 for r in self.played(muted_at, time.monotonic())))
        t_unkey = time.monotonic()
        self.key(False)
        # Still muted while the tail of his own downlink comes back ...
        time.sleep(0.2)
        self.assertTrue(all(r == 0.0 for r in self.played(t_unkey + 0.15, time.monotonic())))
        # ... then back.
        self.assertTrue(wait_for(lambda: any(r > 0 for r in self.played(t_unkey, time.monotonic())), timeout=2))
        self.assertFalse(self.st()["mute"])

    def test_the_operators_own_mute_is_left_as_it_was(self):
        self.assertTrue(self.settled())
        self.r.set(mute=True)
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        self.key(False)
        self.assertTrue(wait_for(lambda: not self.st()["rigKeyed"]))
        time.sleep(0.8)
        self.assertTrue(self.st()["mute"])
        t = time.monotonic()
        time.sleep(0.3)
        self.assertTrue(all(r == 0.0 for r in self.played(t, time.monotonic())))

    def test_a_lost_link_while_transmitting_restores_audio_and_says_so(self):
        self.assertTrue(self.settled())
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        self.civ.stall(True)
        self.assertTrue(wait_for(lambda: self.st()["rigLink"] == "lost", timeout=4))
        self.assertFalse(self.st()["rigKeyed"])
        t = time.monotonic()
        self.assertTrue(wait_for(lambda: any(r > 0 for r in self.played(t, time.monotonic())), timeout=1))
        self.assertTrue(any("Lost the IC-9700 link" in x for x in self.toast_texts()))
        self.civ.stall(False)
        self.assertTrue(wait_for(lambda: self.st()["rigLink"] == "ok", timeout=6))


class AudioLowered(Rig):
    cfg_over = {"rigAudio": "lower", "rigAudioLowerDb": 20.0}

    def test_lowered_by_the_set_amount(self):
        self.assertTrue(self.settled())
        t0 = time.monotonic()
        time.sleep(0.6)
        before = float(np.median(self.audio.rms_between(t0, time.monotonic())))
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        time.sleep(0.2)
        t1 = time.monotonic()
        time.sleep(0.6)
        during = float(np.median(self.audio.rms_between(t1, time.monotonic())))
        self.key(False)
        self.assertAlmostEqual(20 * np.log10(during / before), -20.0, delta=3.0)


class AudioKept(Rig):
    cfg_over = {"rigAudio": "keep"}

    def test_kept_playing(self):
        self.assertTrue(self.settled())
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        time.sleep(0.2)
        t = time.monotonic()
        time.sleep(0.4)
        self.assertTrue(all(r > 0 for r in self.audio.rms_between(t, time.monotonic())))
        self.key(False)


class ThroughRigctld(Rig):
    """The same radio through Hamlib's rigctld instead of direct CI-V."""
    link = "rigctld"

    def test_tunes_follows_and_sees_the_radio_transmit(self):
        self.assertTrue(self.settled())
        self.assertEqual(self.civ.freq, 1_296_200_000)
        self.civ.turn(1_296_204_000)
        self.assertTrue(wait_for(lambda: self.st()["txDial"] == VFO + 4000))
        self.key(True)
        self.assertTrue(wait_for(lambda: self.st()["rigKeyed"]))
        self.key(False)
        self.assertTrue(wait_for(lambda: not self.st()["rigKeyed"]))

    def test_fm_is_switched_through_rigctld_too(self):
        self.assertTrue(self.settled())
        self.set_rig_mode("fm")
        self.assertTrue(wait_for(lambda: self.civ.mode_sets == ["USB"], timeout=4))


class Settings(unittest.TestCase):
    """What Settings may save (Radio.set(authorise=True)); nothing started."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.r = Radio(sim_cfg(), persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False))

    def test_the_lo_has_no_default_and_is_required(self):
        self.assertEqual(self.r.state()["rigTxConverter"], "")
        with self.assertRaises(ValueError) as cm:
            self.r.set(authorise=True, txRadio="civ", civPort="COM5")
        self.assertIn("local oscillator", str(cm.exception))
        self.assertEqual(self.r.state()["txRadio"], "sdr")

    def test_an_lo_that_puts_the_if_outside_the_band_is_refused_with_the_numbers(self):
        with self.assertRaises(ValueError) as cm:
            # 1968 MHz is a 70 cm-IF LO: on 23 cm the IF would be 432 MHz.
            self.r.set(authorise=True, txRadio="civ", **rig_conv(1_968_000_000.0))
        msg = str(cm.exception)
        self.assertIn("432.000-432.500", msg)
        self.assertIn("23 cm range (1240-1300 MHz)", msg)
        self.r.set(authorise=True, txRadio="civ", **rig_conv(1_968_000_000.0), rigIfBand="70cm")
        self.assertEqual(self.r.state()["txRadio"], "civ")

    def test_high_side_is_checked_the_inverted_way(self):
        with self.assertRaises(ValueError):
            self.r.set(authorise=True, txRadio="civ", **rig_conv(1_104_000_000.0, "high"))
        self.r.set(authorise=True, txRadio="civ", **rig_conv(3_696_200_000.0, "high"))

    def test_choosing_the_9700_needs_settings_authority(self):
        with self.assertRaises(ValueError):
            self.r.set(txRadio="civ")

    def test_test_connection_reads_the_frequency_and_nothing_else(self):
        civ = CivSim(freq=1_296_123_456).start()
        self.addCleanup(civ.stop)
        text = self.r.test_rig({"txRadio": "civ", "civPort": civ.url})
        self.assertIn("1296.123456 MHz", text)
        self.assertEqual(civ.received, [bytes([0x03])])


if __name__ == "__main__":
    unittest.main()
