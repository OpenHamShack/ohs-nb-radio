"""The Canadian licence regime (ohscore/licences/ised.py) against its
research, docs/ham/countries/ca.md: HF access by qualification, the
mode-dependent transmitter limits, bandwidths, 60 m, the refused and
unconfirmed rows, and the 13 cm satellite uplink."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import ised
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, gain=0.0, mode=None):
    return guard.licence_check(cls, lo, hi, w, gain, lic=ised, mode=mode, region=2, today="2026-10-08")


class Shape(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(ised), [])


class HfAccess(unittest.TestCase):
    """ca.md s.2-3: below 30 MHz needs "B and 5, B/H, B and A"."""

    def test_basic_alone_has_no_hf_not_even_10_m(self):
        for f in (1_840_000, 3_573_000, 7_074_000, 14_074_000, 28_074_000):
            self.assertIn("Basic licence", check("ca_basic", f, f + 50, 1.0, mode="ft8").refused, f)
        self.assertEqual(check("ca_basic", 50_313_000, 50_313_050, 1.0, mode="ft8").refused, "")

    def test_hf_classes_have_hf(self):
        for cls in ("ca_basic_hf", "ca_advanced"):
            self.assertEqual(check(cls, 14_074_000, 14_074_050, 1.0, mode="ft8").refused, "", cls)
            self.assertEqual(check(cls, 28_074_000, 28_074_050, 1.0, mode="ft8").refused, "", cls)


class Power(unittest.TestCase):
    """ca.md s.3, R4 s.10.2-10.3: SSB 560 / 2250 W PEP; any other emission 190 / 750 W carrier."""

    def test_basic_ssb_and_other(self):
        v = check("ca_basic", 144_200_000, 144_202_700, 560.0, mode="usb")
        self.assertEqual((v.refused, v.warning), ("", ""))
        self.assertIn("560 W PEP", check("ca_basic", 144_200_000, 144_202_700, 600.0, mode="usb").warning)
        self.assertEqual(check("ca_basic", 146_520_000, 146_530_000, 190.0, mode="fm").warning, "")
        self.assertIn("190 W carrier", check("ca_basic", 146_520_000, 146_530_000, 200.0, mode="fm").warning)

    def test_advanced_ssb_and_other(self):
        self.assertEqual(check("ca_advanced", 14_200_000, 14_202_700, 2250.0, mode="usb").warning, "")
        self.assertIn("2250 W PEP", check("ca_advanced", 14_200_000, 14_202_700, 2300.0, mode="usb").warning)
        self.assertIn("750 W carrier", check("ca_advanced", 14_030_000, 14_030_100, 800.0, mode="cw").warning)

    def test_data_is_held_to_the_carrier_figure(self):
        # s.11 item 4: J2D as "single sideband" is an unconfirmed reading; the stricter applies.
        self.assertIn("190 W carrier", check("ca_basic_hf", 14_074_000, 14_074_050, 300.0, mode="ft8").warning)
        # Mode unknown: the strictest of the two.
        self.assertIn("190 W carrier", check("ca_basic", 144_200_000, 144_202_700, 300.0).warning)

    def test_2200_m_one_watt_eirp(self):
        # Item 1: Pb and 1 W EIRP; Basic alone has none.
        self.assertEqual(check("ca_basic_hf", 136_000, 136_050, 1.0, mode="cw").refused, "")
        self.assertIn("1.0 W EIRP", check("ca_basic_hf", 136_000, 136_050, 2.0, mode="cw").warning)
        self.assertTrue(check("ca_basic", 136_000, 136_050, 1.0, mode="cw").refused)

    def test_630_m_is_1_w_not_5(self):
        # s.11 item 1: 5 W EIRP is UNCONFIRMED; 1 W EIRP encoded.
        self.assertIn("1.0 W EIRP", check("ca_advanced", 475_000, 475_100, 3.0, mode="cw").warning)


class Bandwidth(unittest.TestCase):
    """ca.md s.4: R4 column II maximum bandwidths."""

    def test_30_m_is_1_khz(self):
        self.assertEqual(check("ca_advanced", 10_136_000, 10_136_050, 1.0, mode="ft8").refused, "")
        self.assertIn("1000 Hz", check("ca_advanced", 10_120_000, 10_122_700, 1.0, mode="usb").refused)

    def test_hf_6_khz_and_10_m_20_khz(self):
        self.assertEqual(check("ca_advanced", 3_885_000, 3_891_000, 1.0, mode="am").refused, "")
        self.assertIn("6000 Hz", check("ca_advanced", 3_885_000, 3_895_000, 1.0, mode="fm").refused)
        self.assertEqual(check("ca_advanced", 29_600_000, 29_616_000, 1.0, mode="fm").refused, "")

    def test_70_cm_12_mhz(self):
        # Item 22: a 2 MHz-wide signal is inside 12 MHz.
        self.assertEqual(check("ca_basic", 437_000_000, 439_000_000, 1.0, mode="sstv").refused, "")


class SixtyMetres(unittest.TestCase):
    """ca.md s.3: four channels and 5351.5-5366.5 kHz, 100 W ERP, 2.8 kHz."""

    def test_channel_and_band(self):
        # 2.15 dBi is a dipole: ERP equals PEP.
        self.assertEqual(check("ca_basic_hf", 5_330_600, 5_333_400, 100.0, 2.15).refused, "")
        self.assertEqual(check("ca_basic_hf", 5_330_600, 5_333_400, 100.0, 2.15).warning, "")
        self.assertIn("100 W ERP", check("ca_advanced", 5_357_000, 5_357_050, 120.0, 2.15).warning)

    def test_who_and_where(self):
        self.assertIn("open only to", check("ca_basic", 5_357_000, 5_357_050, 1.0).refused)
        self.assertIn("5332, 5348, 5373 and 5405 kHz", check("ca_advanced", 5_360_000, 5_368_000, 1.0).refused)
        self.assertIn("2.8 kHz", check("ca_advanced", 5_355_000, 5_360_000, 1.0).refused)


class RefusedAndUnconfirmed(unittest.TestCase):
    def test_220_222_mhz_disaster_relief_only(self):
        # Item 20, C11: exceptional circumstances only.
        self.assertIn("disaster", check("ca_advanced", 221e6, 221e6, 1.0).refused)

    def test_219_and_222_are_open(self):
        self.assertEqual(check("ca_basic", 219.5e6, 219.5e6, 1.0).refused, "")
        self.assertEqual(check("ca_basic", 223.5e6, 223.5e6, 1.0).refused, "")

    def test_5850_5925_is_unconfirmed(self):
        # s.3 5 cm: the effect of SMSE-012-22 is UNCONFIRMED.
        self.assertIn("unconfirmed", check("ca_advanced", 5_870e6, 5_870e6, 1.0).refused.lower())
        self.assertEqual(check("ca_advanced", 5_760.1e6, 5_760.1e6, 1.0).refused, "")

    def test_nothing_above_250_ghz(self):
        self.assertTrue(check("ca_advanced", 400e9, 400e9, 1.0).refused)


class Satellite(unittest.TestCase):
    """ca.md s.6: 2400-2450 MHz amateur-satellite (5.282); every class holds 2300-2450 MHz."""

    def test_qo100_uplink_by_class(self):
        for cls, w in (("ca_basic", 190.0), ("ca_basic_hf", 190.0), ("ca_advanced", 750.0)):
            allowed, limit, _ = licences.satellite_uplink(ised, cls, *QO100)
            self.assertEqual((allowed, limit), (True, (w, "carrier")), cls)

    def test_1260_up_only_and_no_5830_downlink_uplink(self):
        self.assertTrue(licences.satellite_uplink(ised, "ca_basic", 1_265e6, 1_266e6)[0])
        self.assertFalse(licences.satellite_uplink(ised, "ca_advanced", 5_835e6, 5_836e6)[0])

    def test_cept(self):
        # s.8: only Basic + Advanced is the CEPT licence; a CEPT visitor gets Basic + Advanced.
        self.assertEqual(ised.CEPT, {"T/R 61-01": ("ca_advanced",)})
        self.assertIn("not a CEPT licence", licences.cept_suggestion(ised, "ca_basic_hf", None))


if __name__ == "__main__":
    unittest.main()
