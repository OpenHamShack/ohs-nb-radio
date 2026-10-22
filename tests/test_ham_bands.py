"""OpenHamShack HAM's band table, UK repeater channels and band stacks."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohsradio import bands


class Bands(unittest.TestCase):
    def test_bands_are_in_order_and_do_not_overlap(self):
        for a, b in zip(bands.BANDS, bands.BANDS[1:]):
            self.assertLess(a.hi, b.lo, (a.name, b.name))

    def test_every_register_and_dial_is_inside_its_band(self):
        for b in bands.BANDS:
            for f, mode in b.stack:
                self.assertTrue(b.lo <= f <= b.hi, (b.name, f))
            for f in (b.ft8, b.ft4, b.wspr):
                if f:
                    self.assertTrue(b.lo <= f <= b.hi, (b.name, f))

    def test_band_at(self):
        self.assertEqual(bands.band_at(14_074_000).name, "20m")
        self.assertEqual(bands.band_at(433_500_000).name, "70cm")
        self.assertIsNone(bands.band_at(100_000_000))

    def test_sideband_convention(self):
        self.assertEqual(bands.natural_sideband(7_100_000), "lsb")
        self.assertEqual(bands.natural_sideband(14_200_000), "usb")

    def test_six_metres_is_deferred_with_the_reason(self):
        self.assertIn("38.4 MHz", bands.BY_NAME["6m"].deferred)


class Repeaters(unittest.TestCase):
    def test_uk_channel_names(self):
        self.assertEqual(bands.channel_name(145_600_000), "RV48")
        self.assertEqual(bands.channel_name(145_787_500), "RV63")
        self.assertEqual(bands.channel_name(145_500_000), "V40")
        self.assertEqual(bands.channel_name(145_200_000), "V16")
        self.assertEqual(bands.channel_name(433_025_000), "RB1")
        self.assertEqual(bands.channel_name(433_500_000), "U280")
        self.assertEqual(bands.channel_name(1_297_000_000), "RM0")
        self.assertEqual(bands.channel_name(29_650_000), "RH4")
        self.assertEqual(bands.channel_name(144_300_000), "")

    def test_uk_shifts_by_scheme(self):
        # bandplan-r1-uk.md section 3: 2 m -600 kHz; 70 cm RB +1.6 MHz (the
        # reverse of IARU R1), RU +7.6 MHz, DV -9 MHz; 23 cm -6 MHz; 10 m -100 kHz.
        self.assertEqual(bands.auto_shift(145_650_000), -600_000)
        self.assertEqual(bands.auto_shift(433_200_000), +1_600_000)
        self.assertEqual(bands.auto_shift(430_900_000), +7_600_000)
        self.assertEqual(bands.auto_shift(439_500_000), -9_000_000)
        self.assertEqual(bands.auto_shift(1_297_100_000), -6_000_000)
        self.assertEqual(bands.auto_shift(29_660_000), -100_000)
        self.assertEqual(bands.auto_shift(145_500_000), 0.0)
        self.assertEqual(bands.auto_shift(145_606_000), 0.0)        # between channels


class Stacks(unittest.TestCase):
    def test_clean_keeps_good_registers_and_drops_the_rest(self):
        raw = {"20m": {"i": 4, "regs": [{"vfo": 14_074_000, "mode": "ft8"}, {"vfo": "x"}, {"mode": "usb"},
                                       {"vfo": 14_200_000, "mode": "usb", "filterHi": 2800.0}]},
               "nowhere": {"i": 0, "regs": [{"vfo": 1.0, "mode": "usb"}]},
               "2m": {"i": 0, "regs": [{"vfo": 433_000_000, "mode": "fm"}]}}
        out = bands.clean_stacks(raw)
        self.assertEqual(list(out), ["20m"])
        self.assertEqual(out["20m"]["regs"], [{"vfo": 14_074_000.0, "mode": "ft8"}])
        self.assertEqual(out["20m"]["i"], 0)

    def test_seed(self):
        self.assertEqual(bands.seed_stack(bands.BY_NAME["20m"])[0], {"vfo": 14_074_000.0, "mode": "ft8"})


if __name__ == "__main__":
    unittest.main()
