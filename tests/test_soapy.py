"""The SoapySDR receiver (ohscore/devices/soapy.py) against a stand-in for
the SoapySDR module that behaves as SoapySDRPlay3 does with an RSPdx: three
antenna inputs, and a setAntenna that ignores a name it does not know (so
the device must check the name itself, or a typo listens to Antenna A)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import sys
import types
import unittest
from unittest import mock


from ohscore.devices.base import DeviceError
from ohscore.devices.soapy import SoapyDevice

RX = 1


class FakeRsp:
    """One RSPdx as SoapySDRPlay3 0.5.2 presents it."""

    made: list["FakeRsp"] = []

    def __init__(self, args):
        self.args = args
        self.antenna = "Antenna A"
        self.rate = 2_000_000.0
        self.calls = []
        self.active = False
        FakeRsp.made.append(self)

    def listAntennas(self, direction, ch):
        return ("Antenna A", "Antenna B", "Antenna C")

    def setAntenna(self, direction, ch, name):
        self.calls.append(("setAntenna", name))
        if name in self.listAntennas(direction, ch):
            self.antenna = name

    def getAntenna(self, direction, ch):
        return self.antenna

    def setSampleRate(self, direction, ch, rate):
        # 1.2 MS/s is not one of its rates: the driver warns and keeps 2 MS/s.
        if rate > 2_000_000 or rate in (62_500, 125_000, 250_000, 500_000, 1_000_000, 2_000_000):
            self.rate = float(rate)

    def getSampleRate(self, direction, ch):
        return self.rate

    def setGainMode(self, direction, ch, automatic):
        self.calls.append(("setGainMode", automatic))

    def setGain(self, direction, ch, db):
        self.calls.append(("setGain", db))

    def setupStream(self, direction, fmt):
        return "stream"

    def activateStream(self, stream):
        self.active = True

    def deactivateStream(self, stream):
        self.active = False

    def closeStream(self, stream):
        pass

    def getDriverKey(self):
        return "SDRplay"

    def getHardwareKey(self):
        return "RSPdx"


def fake_soapysdr():
    m = types.ModuleType("SoapySDR")
    m.Device = FakeRsp
    m.SOAPY_SDR_RX = RX
    m.SOAPY_SDR_CF32 = "CF32"
    m.SOAPY_SDR_OVERFLOW = -4
    return m


class Antenna(unittest.TestCase):
    def setUp(self):
        FakeRsp.made.clear()
        p = mock.patch.dict(sys.modules, {"SoapySDR": fake_soapysdr()})
        p.start()
        self.addCleanup(p.stop)

    def open(self, **cfg):
        dev = SoapyDevice("driver=sdrplay", 2_400_000.0, cfg)
        dev.open()
        self.addCleanup(dev.close)
        return dev

    def test_the_configured_input_is_selected_and_reported(self):
        dev = self.open(soapyAntenna="Antenna C")
        rsp = FakeRsp.made[-1]
        self.assertEqual(rsp.antenna, "Antenna C")
        # Chosen before the stream starts, so no block comes from the wrong input.
        self.assertTrue(rsp.active)
        st = dev.status()
        self.assertEqual(st["antenna"], "Antenna C")
        self.assertEqual(st["antennas"], ["Antenna A", "Antenna B", "Antenna C"])
        self.assertEqual(st["hardware"], "RSPdx")
        self.assertEqual(st["tx"], "receive only")

    def test_an_unknown_name_is_refused_not_ignored(self):
        with self.assertRaises(DeviceError) as e:
            self.open(soapyAntenna="Antenna D")
        self.assertIn("Antenna D", str(e.exception))
        self.assertIn("Antenna A, Antenna B, Antenna C", str(e.exception))
        rsp = FakeRsp.made[-1]
        self.assertNotIn(("setAntenna", "Antenna D"), rsp.calls)
        self.assertFalse(rsp.active)

    def test_empty_leaves_the_drivers_default(self):
        dev = self.open(soapyAntenna="")
        rsp = FakeRsp.made[-1]
        self.assertFalse([c for c in rsp.calls if c[0] == "setAntenna"])
        self.assertEqual(dev.status()["antenna"], "Antenna A")

    def test_agc_by_default_as_the_other_radios(self):
        self.open()
        self.assertIn(("setGainMode", True), FakeRsp.made[-1].calls)

    def test_a_rate_the_driver_cannot_do_is_said(self):
        dev = SoapyDevice("driver=sdrplay", 1_200_000.0, {})
        with self.assertRaisesRegex(DeviceError, "runs at 2000000 S/s, not 1200000"):
            dev.open()

    def test_it_cannot_transmit(self):
        dev = self.open(soapyAntenna="Antenna C")
        self.assertFalse(dev.can_tx)
        with self.assertRaises(DeviceError):
            dev.tx_start()
        with self.assertRaises(DeviceError):
            dev.set_tx_freq(3.65e6)


if __name__ == "__main__":
    unittest.main()
