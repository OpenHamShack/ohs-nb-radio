"""OpenHamShack HAM: the drive into a transverter is held under its most drive
on every path, not only the obvious one (a review of merge 28ef08c,
07/10/2026). Each test here is one way the first version let a radio's
full output reach a transverter's input, or judged the wrong figure:

- a split transmit dial in a transverter's band while the receive dial
  is on HF: the slider's ceiling came from the receive dial;
- Settings changing the converter between key-up and the device keying;
- the cap worked from the device's nominal output when the operator had
  measured more;
- a Tune carrier judged at the operator's full drive, an over judged at
  the previous request's;
- an output nobody knows, an HL2's PA that is on whatever the saved
  setting says, and an estimate that reads milliwatts while the
  transverter puts out watts.

TxOnlyTransverter runs the same paths through a TX-only converter
(07/10/2026), which the receive side never sees.

They run on the band simulator dressed as the radio in question and
record what the device was told; nothing here touches real hardware."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time
import unittest

import numpy as np

from ham_helpers import close, pump
from ohscore import converters as cv
from ohscore.audio import NullAudio
from ohscore.engine import TxRefused
from ohsradio import xvtr
from ohsradio.devices.sim import HamSim
from ohsradio.radio import Radio


def conv(title, lo_mhz, rxtx=True, drive=0.0):
    return {"title": title, "type": "down", "rxtx": rxtx, "rxOffset": lo_mhz * 1e6, "txOffset": lo_mhz * 1e6,
            "inverted": False, "maxDriveDbm": drive}


XV2 = conv("144 MHz (28 MHz IF)", 116)                    # 0 dBm: an Elecraft XV144's figure
XV23 = conv("1296 MHz (144 MHz IF)", 1152, drive=-10.0)    # -10 dBm: a Pluto-driven 23 cm transverter
CAP_5W_0DBM = (1e-3 / 5.0) ** 0.5                          # 5 W into 0 dBm: drive 1.41 %


class Recording(HamSim):
    """The simulator, recording every drive it is given while its
    transmitter runs and how many times it was started."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.on_air_drives: list[float] = []
        self.starts = 0

    def tx_start(self) -> None:
        self.starts += 1
        super().tx_start()

    def set_drive(self, x: float) -> None:
        if self.tx_active:
            self.on_air_drives.append(float(x))
        super().set_drive(x)


class Hl2(Recording):
    """With the Hermes-Lite 2's reach (to 38.4 MHz) and its 5 W PA."""
    kind = "hl2"
    rx_range = (0.0, 38.4e6)
    tx_range = (0.0, 38.4e6)
    pa = False


class NoFigure(Recording):
    """A transmitting device that does not say what it puts out."""
    kind = "soapy"

    def tx_full_w(self, hz: float) -> float:
        return 0.0


def radio(dev_cls=Recording, **over):
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "callsign": "GM4BRI", "licenceClass": "full", "simSignals": False}
    cfg.update(over)
    tmp = tempfile.TemporaryDirectory()
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=NullAudio(realtime=False),
              device=dev_cls(dict(Radio.CONFIG.clean(cfg)), 192_000.0))
    r._tmp = tmp
    return r


def on_air(r):
    return r.state()["seqState"] == "tx" and r.dev.tx_active


class SplitIntoTheTransverter(unittest.TestCase):
    """Finding 1: receive on 20 m, transmit split on 144.3 MHz through a
    28 MHz-IF transverter that takes 0 dBm, on a 5 W HL2."""

    def setUp(self):
        self.r = radio(Hl2, hl2Pa=False, vfo=14_200_000.0, mode="usb", drive=0.01,
                       converters=[XV2], bandConverters={"2m": XV2["title"]})
        self.r.start()
        self.addCleanup(close, self.r)
        self.r.set(split=True, txVfo=144_300_000.0)

    def test_the_slider_s_ceiling_is_the_transmit_dial_s_transverter(self):
        st = self.r.state()
        self.assertEqual(st["band"], "20m")                    # the receive dial is still on 20 m
        self.assertEqual(st["txBlocked"], "")
        self.assertLessEqual(st["maxDrive"], CAP_5W_0DBM)

    def test_raising_drive_mid_over_never_reaches_the_transverter(self):
        r = self.r
        r.ptt(True)
        try:
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            try:
                r.set(drive=1.0)
            except ValueError as e:
                self.assertIn("Drive cannot exceed", str(e))
            pump(r, 0.3)
            self.assertLessEqual(max(r.dev.on_air_drives), CAP_5W_0DBM + 1e-9)
        finally:
            r.ptt(False)

    def test_the_drive_follows_the_split_into_the_transverter_s_band(self):
        # Split switched on with drive already high (20 m's own): the drive
        # comes down to the transverter's cap rather than standing above it.
        r = self.r
        r.set(split=False)
        r.set(drive=0.8)
        r.set(split=True)
        self.assertLessEqual(r.state()["drive"], CAP_5W_0DBM)


class TheDeviceBoundary(unittest.TestCase):
    """Whatever the state holds - a path nobody has thought of yet - the
    device is never given more than the converter of the over takes."""

    def test_a_drive_that_reaches_the_state_unchecked_is_clamped_at_the_device(self):
        r = radio(Hl2, hl2Pa=False, vfo=144_300_000.0, mode="usb", drive=0.01,
                  converters=[XV2], bandConverters={"2m": XV2["title"]})
        r.start()
        try:
            r.ptt(True)
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            with r.lock:
                r.st["drive"] = 1.0                 # past every check set() makes,
                r.st["maxDrive"] = 1.0              # and past a slider ceiling worked out wrong
            r._after_set({"drive": 1.0})
            pump(r, 0.2)
            self.assertLessEqual(max(r.dev.on_air_drives), CAP_5W_0DBM + 1e-9)
        finally:
            r.ptt(False)
            close(r)


class ConverterChangedBeforeTheDeviceKeys(unittest.TestCase):
    """Finding 2: an over keyed and waiting for its slot (FT8), then
    Settings point its band at a receive-only converter. The over must
    not go out through it."""

    def test_a_waiting_over_does_not_transmit_through_a_new_rx_only_converter(self):
        r = radio(vfo=144_174_000.0, mode="usb", drive=0.1)
        r.start()
        try:
            self.assertEqual(r.state()["txBlocked"], "")
            r._key({"source": "send:ft8", "mode": "usb", "audio": np.zeros(24_000, np.float32),
                    "start_at": time.time() + 0.6})
            rx_only = dict(XV2, rxtx=False)
            r.set(authorise=True, converters=[rx_only], bandConverters={"2m": rx_only["title"]})
            pump(r, 2.0, until=lambda: r.dev.starts > 0)
            self.assertEqual(r.dev.starts, 0)
            self.assertFalse(r.state()["keyed"])
        finally:
            close(r)

    def test_a_waiting_over_does_not_go_out_at_a_drive_the_new_converter_cannot_take(self):
        # Direct on 2 m at 50 % (a few mW from the simulator there), then a
        # 0 dBm transverter set for 2 m while the over waits: the radio's
        # output at the 28 MHz IF is 5 W, and 50 % of it is 31 dBm.
        r = radio(vfo=144_174_000.0, mode="usb", drive=0.5)
        r.start()
        try:
            self.assertEqual(r.state()["txBlocked"], "")
            r._key({"source": "send:ft8", "mode": "usb", "audio": np.zeros(24_000, np.float32),
                    "start_at": time.time() + 0.6})
            r.set(authorise=True, converters=[XV2], bandConverters={"2m": XV2["title"]})
            pump(r, 2.0, until=lambda: r.dev.starts > 0)
            self.assertTrue(not r.dev.on_air_drives or max(r.dev.on_air_drives) <= CAP_5W_0DBM + 1e-9,
                            r.dev.on_air_drives)
        finally:
            close(r)


class MeasuredOutput(unittest.TestCase):
    """Finding 3: a Pluto measured at +9 dBm (8 mW) into a -10 dBm 23 cm
    transverter. The cap must use the 8 mW, not the nominal 4.5 mW."""

    def test_the_cap_uses_the_measured_output_when_it_is_higher(self):
        r = radio(vfo=1_296_200_000.0, mode="usb", drive=0.01, converters=[XV23],
                  bandConverters={"23cm": XV23["title"]}, bandPower={"23cm": {"devW": 0.008}})
        r.start()
        try:
            want = (1e-4 / 0.008) ** 0.5
            self.assertLessEqual(r.state()["maxDrive"], want)
            self.assertAlmostEqual(r.state()["maxDrive"], want, places=3)
        finally:
            close(r)

    def test_a_measured_figure_lower_than_nominal_does_not_loosen_it(self):
        r = radio(vfo=1_296_200_000.0, mode="usb", drive=0.01, converters=[XV23],
                  bandConverters={"23cm": XV23["title"]}, bandPower={"23cm": {"devW": 0.001}})
        r.start()
        try:
            self.assertAlmostEqual(r.state()["maxDrive"], (1e-4 / 0.0045) ** 0.5, places=3)
        finally:
            close(r)


class TheRequestBeingKeyed(unittest.TestCase):
    """Finding 4: key-up judges the request being keyed, at its own drive."""

    def test_drive_moved_during_tune_keeps_the_tune_share(self):
        # Tune is a quarter of the drive. Moving the slider mid-tune used to
        # send the device the whole new drive: a 20 % carrier became 80 %.
        r = radio(vfo=144_300_000.0, mode="usb", drive=0.4, tuneDrive=0.25)
        r.start()
        try:
            r.tune(True)
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            r.set(drive=0.8)
            pump(r, 0.2)
            self.assertAlmostEqual(r.dev.on_air_drives[-1], 0.2)
            self.assertLessEqual(max(r.dev.on_air_drives), 0.2 + 1e-9)
        finally:
            r.tune(False)
            close(r)

    def test_tune_is_judged_at_its_own_share_of_drive(self):
        # A stored drive of 4 % (above the 1.4 % cap) and a Tune at a quarter
        # of it: the carrier is 1 %, under the cap, and may go.
        r = radio(Hl2, hl2Pa=False, vfo=144_300_000.0, mode="usb", drive=0.04, tuneDrive=0.25,
                  converters=[XV2], bandConverters={"2m": XV2["title"]})
        r.start()
        try:
            self.assertIn("most drive", r.state()["txBlocked"])        # a normal over is refused
            r.tune(True)
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            self.assertLessEqual(max(r.dev.on_air_drives), CAP_5W_0DBM + 1e-9)
        finally:
            r.tune(False)
            close(r)

    def test_an_over_is_not_judged_at_the_previous_tune_s_drive(self):
        r = radio(Hl2, hl2Pa=False, vfo=144_300_000.0, mode="usb", drive=0.04, tuneDrive=0.25,
                  converters=[XV2], bandConverters={"2m": XV2["title"]})
        r.start()
        try:
            r.tx_req = {"source": "tune", "mode": "cw", "audio": None, "tune": True}   # the last over's
            with self.assertRaisesRegex(TxRefused, "most drive"):
                r.ptt(True)
            self.assertEqual(r.dev.starts, 0)
        finally:
            close(r)


class TxOnlyTransverter(unittest.TestCase):
    """A TX-only converter (07/10/2026) is received around - the band is
    received directly - but transmitted through exactly like an RX/TX one.
    The receive side's lookup leaves it out, so each path above that
    capped an RX/TX transverter is run again here through a TX-only one
    on the same 5 W into 0 dBm."""

    UP2 = dict({k: v for k, v in XV2.items() if k != "rxtx"}, title="2 m upconverter", use="tx")

    def hl2(self, **over):
        cfg = dict(hl2Pa=False, vfo=14_200_000.0, mode="usb", drive=0.01, converters=[self.UP2],
                   bandConverters={"2m": self.UP2["title"]})
        cfg.update(over)
        r = radio(Hl2, **cfg)
        r.start()
        self.addCleanup(close, r)
        return r

    def test_split_onto_its_band_holds_the_slider_and_the_device(self):
        r = self.hl2()
        r.set(split=True, txVfo=144_300_000.0)
        st = r.state()
        self.assertEqual((st["band"], st["converter"]), ("20m", ""))
        self.assertEqual(st["txBlocked"], "")
        self.assertLessEqual(st["maxDrive"], CAP_5W_0DBM)
        r.ptt(True)
        try:
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            self.assertTrue(27e6 < r.dev.tx_radio < 30e6)                    # through it, on the IF
            with self.assertRaisesRegex(ValueError, "Drive cannot exceed"):
                r.set(drive=1.0)
            with r.lock:
                r.st["drive"] = r.st["maxDrive"] = 1.0                       # past every check set() makes
            r._after_set({"drive": 1.0})
            pump(r, 0.2)
            self.assertLessEqual(max(r.dev.on_air_drives), CAP_5W_0DBM + 1e-9)
        finally:
            r.ptt(False)

    def test_split_switched_on_brings_a_high_drive_down_to_its_cap(self):
        r = self.hl2(drive=0.8, split=False, txVfo=144_300_000.0)
        r.set(split=True)
        self.assertLessEqual(r.state()["drive"], CAP_5W_0DBM)

    def test_a_drive_moved_mid_tune_stays_under_its_cap(self):
        # Tune at a quarter of 4 % is 1 %, under the 1.41 % cap; the
        # slider moved during it must not take the carrier past the cap.
        r = self.hl2(drive=0.04, tuneDrive=0.25, split=True, txVfo=144_300_000.0)
        r.tune(True)
        try:
            pump(r, 3, until=lambda: on_air(r))
            self.assertTrue(on_air(r))
            self.assertAlmostEqual(r.dev.on_air_drives[-1], 0.01)
            r.set(drive=0.012)
            pump(r, 0.2)
            self.assertAlmostEqual(r.dev.on_air_drives[-1], 0.003)
            with r.lock:
                r.st["drive"] = r.st["maxDrive"] = 0.8
            r._after_set({"drive": 0.8})
            pump(r, 0.2)
            self.assertLessEqual(max(r.dev.on_air_drives), CAP_5W_0DBM + 1e-9)
        finally:
            r.tune(False)

    def test_a_waiting_over_is_judged_again_when_its_band_gets_one(self):
        # Direct on 2 m at 50 % while an FT8 over waits, then Settings put a
        # TX-only 0 dBm upconverter on 2 m: the device keys at its cap or not
        # at all, though the receiver never moves to it.
        r = radio(vfo=144_174_000.0, mode="usb", drive=0.5)
        r.start()
        try:
            r._key({"source": "send:ft8", "mode": "usb", "audio": np.zeros(24_000, np.float32),
                    "start_at": time.time() + 0.6})
            r.set(authorise=True, converters=[self.UP2], bandConverters={"2m": self.UP2["title"]})
            self.assertEqual(r.state()["converter"], "")
            pump(r, 2.0, until=lambda: r.dev.starts > 0)
            self.assertTrue(not r.dev.on_air_drives or max(r.dev.on_air_drives) <= CAP_5W_0DBM + 1e-9,
                            r.dev.on_air_drives)
        finally:
            close(r)

    def test_the_keying_recheck_refuses_when_the_converter_changed_under_the_over(self):
        # The converter picked at key-up is no longer the band's when the
        # device is about to key: refused, as for an RX/TX one.
        r = self.hl2(vfo=14_200_000.0, split=True, txVfo=144_300_000.0)
        r.tx_conv = None
        with self.assertRaisesRegex(TxRefused, "converter for the transmit dial changed"):
            r._judge_again({"source": "ptt", "mode": "usb"}, 144_300_000.0)
        r.tx_conv = r._conv_at(144_300_000.0)
        self.assertEqual(r.tx_conv.title, self.UP2["title"])
        self.assertIsNone(r._conv_at(144_300_000.0, rx=True))
        r._judge_again({"source": "ptt", "mode": "usb"}, 144_300_000.0)

    def test_without_its_most_drive_it_refuses_to_key(self):
        no_drive = dict(self.UP2, maxDriveDbm=None)
        r = radio(vfo=144_300_000.0, mode="usb", drive=0.01)
        try:
            with self.assertRaisesRegex(ValueError, "most drive"):
                r.set(authorise=True, converters=[no_drive], bandConverters={"2m": no_drive["title"]})
            st = dict(r.state(), converters=[no_drive], bandConverters={"2m": no_drive["title"]})
            self.assertIn("most drive", xvtr.tx_problem(st, "2m", "sim", True))
        finally:
            close(r)


class FailClosed(unittest.TestCase):
    def test_drive_cap_is_zero_when_the_output_is_unknown(self):
        c = cv.Converter.from_dict(XV2)
        self.assertEqual(cv.drive_cap(c, 0.0), 0.0)
        self.assertEqual(cv.drive_cap(c, float("nan")), 0.0)
        self.assertEqual(cv.drive_cap(cv.Converter.from_dict(dict(XV2, maxDriveDbm=None)), 5.0), 0.0)
        self.assertEqual(cv.drive_cap(None, 0.0), 1.0)                 # direct: nothing to protect

    def test_a_device_that_does_not_say_its_output_refuses_a_transverter(self):
        r = radio(NoFigure, vfo=144_300_000.0, mode="usb", drive=0.01,
                  converters=[XV2], bandConverters={"2m": XV2["title"]})
        r.start()
        try:
            self.assertIn("not known", r.state()["txBlocked"])
            with self.assertRaisesRegex(TxRefused, "not known"):
                r.ptt(True)
            # Entering the radio's measured output is the way out.
            r.set(authorise=True, bandPower={"2m": {"devW": 5.0}})
            self.assertEqual(r.state()["txBlocked"], "")
        finally:
            close(r)


class Hl2PaAsItIs(unittest.TestCase):
    def test_an_hl2_whose_pa_is_on_refuses_whatever_the_setting_says(self):
        # Settings saved PA off, but the radio has not restarted: its PA is on.
        class PaOn(Hl2):
            pa = True
        r = radio(PaOn, hl2Pa=False, vfo=144_300_000.0, mode="usb", drive=0.01,
                  converters=[XV2], bandConverters={"2m": XV2["title"]})
        r.start()
        try:
            self.assertIn("power amplifier", r.state()["txBlocked"])
        finally:
            close(r)


class EstimateThroughATransverter(unittest.TestCase):
    def test_no_transverter_output_entered_says_the_estimate_is_unknown(self):
        r = radio(vfo=1_296_200_000.0, mode="usb", drive=0.1, converters=[XV23],
                  bandConverters={"23cm": XV23["title"]})
        r.start()
        try:
            info = r.state()["licenceInfo"]
            self.assertIn("transverter output not entered", info.get("powerUnknown", ""))
            self.assertEqual(r.state()["txBlocked"], "")                   # it warns; it does not refuse
            r.set(authorise=True, bandPower={"23cm": {"paGainDb": 30.0}})
            self.assertEqual(r.state()["licenceInfo"].get("powerUnknown", ""), "")
        finally:
            close(r)


if __name__ == "__main__":
    unittest.main()
