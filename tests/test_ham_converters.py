"""OpenHamShack HAM through transverters and converters (ohsradio/xvtr.py) on the
band simulator, which puts the same converter in front of itself: the
licence and band-plan guard judge the on-air dial and never the IF, a
band the radio cannot reach is offered through a converter, the drive
into a transverter is held under its most drive, an inverting converter's
mirror is undone, and the sequencer is told which converter an over uses.
Nothing here touches real hardware."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import unittest

import numpy as np

from ham_helpers import close, make_radio, pump
from ohscore.audio import NullAudio
from ohscore.engine import TxRefused
from ohsradio import xvtr
from ohsradio.devices.sim import HamSim
from ohsradio.radio import Radio


def conv(title, lo_mhz, rxtx=True, drive=0.0, inverted=False, typ="down"):
    return {"title": title, "type": typ, "rxtx": rxtx, "rxOffset": lo_mhz * 1e6, "txOffset": lo_mhz * 1e6,
            "inverted": inverted, "maxDriveDbm": drive}


XV23 = conv("1296 MHz (144 MHz IF)", 1152)
XV2 = conv("144 MHz (28 MHz IF)", 116)
XV6 = conv("50 MHz (28 MHz IF)", 22)
# A high-side 23 cm transverter on a 2 m IF: 1296.2 MHz comes out at 1440.2 - 1296.2 = 144.0 MHz, mirrored.
XV23_HIGH = conv("1296 high-side", 1440.2, inverted=True)


class Hl2Sim(HamSim):
    """The simulator with the Hermes-Lite 2's reach: receive and transmit
    up to 38.4 MHz only, so 2 m exists for it only through a transverter."""
    kind = "hl2"
    rx_range = (0.0, 38.4e6)
    tx_range = (0.0, 38.4e6)
    pa = True


def hl2_radio(**over):
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "callsign": "GM4BRI", "licenceClass": "full", "simSignals": False}
    cfg.update(over)
    tmp = tempfile.TemporaryDirectory()
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=NullAudio(realtime=False),
              device=Hl2Sim(dict(Radio.CONFIG.clean(cfg)), 192_000.0))
    r._tmp = tmp
    return r


class Guard(unittest.TestCase):
    """The guard judges the dial: 1296.2 MHz through a 2 m IF is 23 cm to
    the licence, whatever the radio itself is tuned to."""

    def setUp(self):
        self.r = make_radio(simSignals=False, converters=[XV23], bandConverters={"23cm": XV23["title"]},
                            vfo=1_296_200_000.0, mode="usb")
        self.r.start()
        self.addCleanup(close, self.r)

    def test_foundation_is_refused_23cm_though_the_if_is_on_2m(self):
        st = self.r.state()
        self.assertEqual(st["band"], "23cm")
        self.assertAlmostEqual(st["radioFreq"], 144_200_000.0)
        self.assertEqual(st["converter"], XV23["title"])
        self.assertIn("Foundation licence: 1270.0-1325.0 MHz is not available", st["licenceInfo"]["why"])
        with self.assertRaises(TxRefused) as cm:
            self.r.ptt(True)
        self.assertIn("1270.0-1325.0 MHz is not available", str(cm.exception))
        # The same IF dialled directly on 2 m is fine for Foundation: the IF was never judged.
        self.r.set(vfo=144_200_000.0)
        self.assertEqual(self.r.state()["txBlocked"], "")

    def test_intermediate_keys_23cm_through_it_and_the_device_is_on_the_if(self):
        self.r.set(authorise=True, licenceClass="intermediate", drive=0.5)
        self.r.ptt(True)
        try:
            pump(self.r, 2, until=lambda: self.r.dev.tx_lo is not None and self.r.state()["seqState"] == "tx")
            self.assertEqual(self.r.state()["txBlocked"], "")
            # The device was tuned to the IF; the simulator (the transverter) put it back on 23 cm.
            self.assertTrue(140e6 < self.r.dev.tx_radio < 146e6)
            self.assertTrue(1_290e6 < self.r.dev.tx_lo < 1_297e6)
            self.assertEqual(self.r.seq.converter.title, XV23["title"])         # the sequencer's hook
        finally:
            self.r.ptt(False)

    def test_the_band_plan_judges_the_dial_too(self):
        # 1296.0 MHz is 23 cm's beacon sub-band territory, refused whatever the IF (and 144.0 is not a beacon).
        self.r.set(authorise=True, licenceClass="full", vfo=1_296_820_000.0, mode="usb")
        self.assertIn("beacon", self.r.state()["txBlocked"].lower())


class Reach(unittest.TestCase):
    def test_2m_on_an_hl2_only_through_a_28_mhz_transverter(self):
        r = hl2_radio(vfo=14_200_000.0, hl2Pa=False)
        r.start()
        try:
            with self.assertRaisesRegex(ValueError, "receives"):
                r.set(vfo=144_300_000.0)
            r.stop()
            r.set(authorise=True, converters=[XV2], bandConverters={"2m": XV2["title"]})
            r.start()
            r.set(vfo=144_300_000.0, mode="usb")
            st = r.state()
            self.assertEqual(st["band"], "2m")
            self.assertAlmostEqual(st["radioFreq"], 28_300_000.0)
            pump(r, 1, until=lambda: r.dev.rx_if > 144e6)
            self.assertTrue(143e6 < r.dev.rx_if < 146e6)      # the simulated air is 2 m
            self.assertTrue(27e6 < r.rx_if < 30e6)            # the radio is on 28 MHz
        finally:
            close(r)

    def test_6m_is_offered_through_a_converter_and_not_without(self):
        r = make_radio(simSignals=False)
        try:
            with self.assertRaisesRegex(ValueError, "6 m has no radio here"):
                r.band("6m")
            r.set(authorise=True, converters=[XV6], bandConverters={"6m": XV6["title"]})
            r.band("6m")
            self.assertEqual(r.state()["band"], "6m")
            self.assertEqual(r.state()["licenceInfo"]["deferred"], "")
        finally:
            close(r)


class Drive(unittest.TestCase):
    def test_the_drive_into_a_transverter_is_held_under_its_most_drive(self):
        # 2 m through a 28 MHz IF: the simulator gives 5 W at 28 MHz, the transverter takes 0 dBm.
        r = make_radio(simSignals=False, converters=[XV2], bandConverters={"2m": XV2["title"]},
                       vfo=144_300_000.0, mode="usb", drive=0.5)
        r.start()
        try:
            cap = (1e-3 / 5.0) ** 0.5
            self.assertAlmostEqual(r.state()["maxDrive"], cap, places=4)
            # A stored drive above it is refused at key-up, with the numbers...
            self.assertIn("most drive", r.state()["txBlocked"])
            with self.assertRaisesRegex(ValueError, "Drive cannot exceed"):
                r.set(drive=0.2)
            r.set(drive=0.01)
            self.assertEqual(r.state()["txBlocked"], "")
            # ...and the slider cannot pass it.
            r.set(vfo=14_200_000.0)                                 # off the transverter: the band's own ceiling
            self.assertEqual(r.state()["maxDrive"], 1.0)
        finally:
            close(r)

    def test_a_transmitting_converter_without_its_most_drive_refuses_to_key(self):
        no_drive = dict(XV2, maxDriveDbm=None)
        r = make_radio(simSignals=False)
        try:
            with self.assertRaisesRegex(ValueError, "most drive"):
                r.set(authorise=True, converters=[no_drive], bandConverters={"2m": no_drive["title"]})
            # A hand-edited file can still hold one: it receives and refuses to key.
            st = dict(r.state(), converters=[no_drive], bandConverters={"2m": no_drive["title"]})
            self.assertIn("most drive", xvtr.tx_problem(st, "2m", "sim", True))
        finally:
            close(r)

    def test_receive_only_and_missing_converters_refuse_to_key(self):
        rx_only = dict(XV2, rxtx=False)
        st = {"converters": [rx_only], "bandConverters": {"2m": rx_only["title"], "70cm": "Gone"}}
        self.assertIn("receive only", xvtr.tx_problem(st, "2m", "sim", True))
        self.assertIn("not in the converter list", xvtr.tx_problem(st, "70cm", "sim", True))
        with self.assertRaisesRegex(ValueError, "not in the converter list"):
            xvtr.check(st)

    def test_an_hl2_with_its_pa_on_will_not_drive_a_0_dbm_transverter(self):
        st = {"converters": [XV2], "bandConverters": {"2m": XV2["title"]}}
        self.assertIn("power amplifier", xvtr.tx_problem(st, "2m", "hl2", True))
        self.assertEqual(xvtr.tx_problem(st, "2m", "hl2", False), "")
        self.assertEqual(xvtr.tx_problem(dict(st, converters=[dict(XV2, maxDriveDbm=10.0)]), "2m", "hl2", True), "")


class TxOnly(unittest.TestCase):
    """A TX-only converter (Ray's station, 07/10/2026: transmit through an
    upconverter, receive on something else) is in the band's transmit path
    and never its receive path: the band is received directly."""

    UP2 = {"title": "2 m upconverter", "type": "down", "use": "tx", "txOffset": 116e6, "maxDriveDbm": 0.0}

    def test_the_band_is_received_directly_and_transmitted_through_it(self):
        r = make_radio(simSignals=False, converters=[self.UP2], bandConverters={"2m": self.UP2["title"]},
                       vfo=144_300_000.0, mode="usb", drive=0.01)
        r.start()
        try:
            st = r.state()
            self.assertEqual((st["converter"], st["radioFreq"]), ("", 144_300_000.0))
            pump(r, 1, until=lambda: r.dev.rx_if > 144e6)
            self.assertTrue(143e6 < r.rx_if < 146e6)               # the radio itself is on 2 m
            self.assertIsNone(r.dev.rx_conv)
            self.assertLessEqual(st["maxDrive"], (1e-3 / 5.0) ** 0.5)
            r.ptt(True)
            pump(r, 2, until=lambda: r.dev.tx_lo is not None and r.state()["seqState"] == "tx")
            self.assertTrue(27e6 < r.dev.tx_radio < 30e6)          # but transmits on the IF
            self.assertEqual(r.tx_conv.title, self.UP2["title"])
        finally:
            r.ptt(False)
            close(r)

    def test_it_needs_its_most_drive_like_an_rx_tx_one(self):
        no_drive = dict(self.UP2, maxDriveDbm=None)
        with self.assertRaisesRegex(ValueError, r"transmits \(TX only\), so it needs its most drive"):
            xvtr.check({"converters": [no_drive], "bandConverters": {"2m": no_drive["title"]}})


class Inverted(unittest.TestCase):
    """Through a high-side transverter the simulator mirrors both ways; a
    1 kHz USB tone keyed on the dial must still come down 1 kHz *above* it."""

    def tone(self, n):
        t = np.arange(n) / 12000.0
        return (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)

    def test_a_usb_tone_lands_above_the_dial(self):
        dial = 1_296_200_000.0
        for c in (XV23, XV23_HIGH):
            with self.subTest(c["title"]):
                r = make_radio(audio_source=self.tone, simSignals=False, converters=[c],
                               bandConverters={"23cm": c["title"]}, vfo=dial, mode="usb", drive=1.0)
                r.set(authorise=True, licenceClass="full")
                zoom = r.subscribe("zoom", 256)
                r.start()
                try:
                    self.assertEqual(r.rx_invert, c["inverted"])
                    r.ptt(True)
                    got = pump(r, 3, feeds=(zoom,))["zoom"][-5:]
                    r.ptt(False)
                    _, start, bin_hz, db = got[-1][:4]
                    peak = start + float(np.argmax(db)) * bin_hz
                    self.assertAlmostEqual(peak - dial, 1000.0, delta=3 * bin_hz)
                finally:
                    close(r)


if __name__ == "__main__":
    unittest.main()
