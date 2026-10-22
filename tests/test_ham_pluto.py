"""The Pluto on the amateur bands: its tuning range as OpenHamShack HAM sees it,
and the sentence when its firmware identity keeps it off 2 m. A fake IIO
channel, no radio, nothing transmitted."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import errno
import unittest

from ham_helpers import close, make_radio
from ohscore.devices import pluto
from ohscore.devices.base import DeviceError


class Lo:
    """An LO channel that refuses what an AD9363's driver refuses."""

    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi
        outer = self

        class A:
            @property
            def value(self):
                return "0"

            @value.setter
            def value(self, v):
                if not outer.lo <= int(v) <= outer.hi:
                    raise OSError(errno.EINVAL, "Invalid argument")
        self.attrs = {"frequency": A()}


class Identity(unittest.TestCase):
    def test_ad9363_firmware_explains_itself_on_2m(self):
        d = pluto.PlutoDevice()
        d.rx_lo_ch = Lo(325e6, 3.8e9)
        with self.assertRaisesRegex(DeviceError, "AD9363"):
            d.set_rx_if(145_500_000.0)
        d.set_rx_if(433_500_000.0)                      # inside: fine

    def test_ranges_and_power_figure(self):
        d = pluto.PlutoDevice()
        self.assertEqual(d.rx_range, (70e6, 6e9))
        self.assertLess(d.tx_full_w(145e6), 0.01)       # milliwatts: every real QSO needs a PA


class Reach(unittest.TestCase):
    def test_a_band_the_device_cannot_tune_is_refused_with_its_range(self):
        r = make_radio()
        try:
            r.start()
            r.dev.rx_range = (70e6, 6e9)                # as a Pluto
            with self.assertRaisesRegex(ValueError, "receives 70.0-6000.0 MHz"):
                r.band("20m")
            r.band("70cm")
            self.assertEqual(r.state()["band"], "70cm")
        finally:
            close(r)

    def test_transmit_outside_the_devices_range_is_refused(self):
        r = make_radio()
        try:
            r.set(authorise=True, licenceClass="full")
            r.start()
            r.dev.tx_range = (46.875e6, 6e9)
            r.set(vfo=14_200_000.0, mode="usb")
            self.assertIn("cannot transmit on 14.2", r.state()["txBlocked"])
        finally:
            close(r)


if __name__ == "__main__":
    unittest.main()
