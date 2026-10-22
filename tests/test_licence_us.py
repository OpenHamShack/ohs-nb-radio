"""The United States licence regime (ohscore/licences/fcc.py) against its
research, docs/ham/countries/us.md: each class's rows and limits, the
Region 3 differences, 60 m, the location and notification conditions, and
the 13 cm satellite uplink."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import fcc
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)
# Every condition answered the permissive way, for checks that are not about them.
CLEAR = {"utcNotified2200m": True, "utcNotified630m": True, "alaskaNearRussia": False, "northOfLineA": False,
         "inUs270Area": False, "inWhiteSandsBox": False, "nearWhiteSands": False, "inColoradoWyomingBox": False}


def check(cls, lo, hi, w, gain=0.0, mode=None, conditions=None, region=2, today="2026-10-08"):
    return guard.licence_check(cls, lo, hi, w, gain, lic=fcc, mode=mode,
                               conditions=CLEAR if conditions is None else conditions, region=region, today=today)


class Shape(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(fcc), [])
        self.assertEqual(fcc.CLASSES, ("novice", "technician", "general", "advanced", "extra"))


class HfClassSubBands(unittest.TestCase):
    """us.md s.3.1: the class boundaries inside HF bands are law."""

    def test_extra_only_edges(self):
        # 3500-3525 kHz: Extra only.
        self.assertEqual(check("extra", 3_510_000, 3_510_100, 1500.0, mode="cw").refused, "")
        self.assertIn("General licence", check("general", 3_510_000, 3_510_100, 10.0, mode="cw").refused)
        # 14150-14175 kHz: Extra only; 14175-14225 Advanced and Extra.
        self.assertTrue(check("advanced", 14_160_000, 14_162_700, 10.0, mode="usb").refused)
        self.assertEqual(check("advanced", 14_200_000, 14_202_700, 1500.0, mode="usb").refused, "")
        self.assertTrue(check("general", 14_200_000, 14_202_700, 10.0, mode="usb").refused)
        self.assertEqual(check("general", 14_250_000, 14_252_700, 1500.0, mode="usb").refused, "")

    def test_general_at_and_over_1500_w(self):
        # 14025-14150 kHz G/A/E at the 1500 W PEP default (97.313(b)).
        v = check("general", 14_074_000, 14_074_050, 1500.0, mode="ft8")
        self.assertEqual((v.refused, v.warning), ("", ""))
        self.assertIn("1500 W PEP maximum", check("general", 14_074_000, 14_074_050, 1600.0, mode="ft8").warning)

    def test_novice_and_technician_cw_segments(self):
        # 3525-3600, 7025-7125, 21025-21200 kHz: N/T CW only, 200 W PEP.
        for cls in ("novice", "technician"):
            v = check(cls, 7_030_000, 7_030_100, 200.0, mode="cw")
            self.assertEqual((v.refused, v.warning), ("", ""), cls)
            self.assertIn("200 W PEP maximum", check(cls, 21_050_000, 21_050_100, 250.0, mode="cw").warning)
            self.assertIn("not permitted", check(cls, 3_573_000, 3_573_050, 10.0, mode="ft8").refused)
            # No 20 m at all.
            self.assertTrue(check(cls, 14_030_000, 14_030_100, 10.0, mode="cw").refused)

    def test_technician_10_m(self):
        # 28000-28500 kHz N/T 200 W; RTTY/data on 28.0-28.3, CW or SSB on 28.3-28.5.
        self.assertEqual(check("technician", 28_074_000, 28_074_050, 200.0, mode="ft8").refused, "")
        self.assertEqual(check("technician", 28_400_000, 28_402_700, 200.0, mode="usb").refused, "")
        self.assertIn("not permitted", check("technician", 28_400_000, 28_410_000, 10.0, mode="fm").refused)
        self.assertTrue(check("technician", 28_600_000, 28_602_700, 10.0, mode="usb").refused)

    def test_30_m_is_200_w_and_no_phone(self):
        # 10100-10150 kHz G/A/E 200 W PEP (97.313(c)(1)); entire band RTTY/data, no phone.
        self.assertEqual(check("extra", 10_136_000, 10_136_050, 200.0, mode="ft8").warning, "")
        self.assertIn("200 W PEP", check("extra", 10_136_000, 10_136_050, 300.0, mode="ft8").warning)
        self.assertIn("not permitted", check("extra", 10_120_000, 10_122_700, 10.0, mode="usb").refused)

    def test_data_segments_are_2_8_khz(self):
        # s.4: HF RTTY/data authorised bandwidth 2.8 kHz; phone not in the data segments.
        self.assertIn("2800 Hz", check("extra", 14_070_000, 14_073_500, 10.0, mode="ft8").refused)
        self.assertIn("not permitted", check("extra", 14_100_000, 14_102_700, 10.0, mode="usb").refused)
        self.assertIn("not permitted", check("extra", 14_300_000, 14_300_050, 10.0, mode="ft8").refused)

    def test_vhf_cw_only_segments(self):
        # s.4: 50.0-50.1 and 144.0-144.1 MHz CW only.
        self.assertIn("not permitted", check("technician", 50_050_000, 50_052_700, 10.0, mode="usb").refused)
        self.assertEqual(check("technician", 50_050_000, 50_050_100, 10.0, mode="cw").refused, "")


class Region3(unittest.TestCase):
    """us.md s.3.1-3.2: the Region 3 column."""

    def test_75_m_ends_at_3900(self):
        self.assertEqual(check("general", 3_950_000, 3_952_700, 100.0, mode="lsb", region=2).refused, "")
        self.assertTrue(check("general", 3_950_000, 3_952_700, 100.0, mode="lsb", region=3).refused)
        self.assertEqual(check("general", 3_850_000, 3_852_700, 100.0, mode="lsb", region=3).refused, "")

    def test_40_m_ends_at_7200_and_200_w_on_7050_7075(self):
        self.assertTrue(check("general", 7_250_000, 7_252_700, 100.0, mode="lsb", region=3).refused)
        self.assertEqual(check("general", 7_060_000, 7_060_100, 1500.0, mode="cw", region=2).warning, "")
        self.assertIn("200 W PEP", check("general", 7_060_000, 7_060_100, 1500.0, mode="cw", region=3).warning)

    def test_no_220_420_440_or_33_cm_in_region_3(self):
        for f in (223.5e6, 425e6, 445e6, 915e6, 5_870e6):
            self.assertEqual(check("technician", f, f, 10.0, region=2).refused, "", f)
            self.assertTrue(check("technician", f, f, 10.0, region=3).refused, f)


class SixtyMetres(unittest.TestCase):
    """us.md s.3.3, in force from 13 Feb 2026."""

    # ERP is relative to a half-wave dipole: a 2.15 dBi antenna makes ERP equal to PEP.
    def test_channels_at_100_w_erp(self):
        v = check("general", 5_330_600, 5_333_400, 100.0, 2.15, mode="usb")
        self.assertEqual((v.refused, v.warning), ("", ""))
        self.assertIn("100 W ERP", check("general", 5_330_600, 5_333_400, 110.0, 2.15, mode="usb").warning)

    def test_band_at_9_15_w_erp(self):
        self.assertEqual(check("extra", 5_357_000, 5_357_050, 9.1, 2.15, mode="ft8").warning, "")
        self.assertIn("W ERP maximum on 60 m (5351.5-5366.5 kHz)",
                      check("extra", 5_357_000, 5_357_050, 10.0, 2.15, mode="ft8").warning)

    def test_who_and_where(self):
        self.assertIn("open only to", check("technician", 5_357_000, 5_357_050, 1.0).refused)
        self.assertIn("5332, 5348, 5373 and 5405 kHz", check("extra", 5_340_000, 5_340_050, 1.0).refused)
        # The old channel 3 is gone: 5358.5 kHz centre is now in the 9.15 W band.
        self.assertIn("ERP maximum on 60 m (5351.5", check("extra", 5_357_100, 5_359_900, 50.0, mode="usb").warning)


class ConditionsAndGaps(unittest.TestCase):
    """us.md s.3.2 gaps and s.3.4."""

    def test_2200_and_630_m_need_utc_notification(self):
        self.assertIn("Utilities Telecom Council", check("general", 136_000, 136_100, 1.0, conditions={}).refused)
        self.assertEqual(check("general", 136_000, 136_100, 1.0).refused, "")
        # 1 W EIRP on 2200 m.
        self.assertIn("1.0 W EIRP", check("general", 136_000, 136_100, 2.0).warning)

    def test_630_m_alaska(self):
        # 5 W EIRP; 1 W EIRP in Alaska within 800 km of Russia, the default answer.
        self.assertEqual(check("general", 475_000, 475_100, 5.0).warning, "")
        self.assertIn("5.0 W EIRP", check("general", 475_000, 475_100, 6.0).warning)
        near = {**CLEAR, "alaskaNearRussia": True}
        self.assertIn("1.0 W EIRP", check("general", 475_000, 475_100, 2.0, conditions=near).warning)
        self.assertIn("Novice licence", check("novice", 475_000, 475_100, 1.0).refused)

    def test_line_a(self):
        self.assertIn("Line A", check("technician", 425e6, 425e6, 10.0, conditions={}).refused)
        self.assertEqual(check("technician", 425e6, 425e6, 10.0).refused, "")

    def test_us270_radar_areas(self):
        # 50 W PEP in US270 areas, the default answer; 1500 W PEP otherwise.
        self.assertIn("50 W PEP", check("technician", 432.1e6, 432.1e6, 100.0, conditions={}).warning)
        self.assertEqual(check("technician", 432.1e6, 432.1e6, 1500.0).warning, "")

    def test_33_cm_white_sands_and_colorado_wyoming(self):
        self.assertIn("White Sands", check("technician", 915e6, 915e6, 1.0, conditions={}).refused)
        self.assertIn("50 W PEP", check("technician", 915e6, 915e6, 100.0,
                                        conditions={**CLEAR, "nearWhiteSands": True}).warning)
        self.assertIn("Colorado/Wyoming", check("technician", 904.5e6, 904.5e6, 1.0,
                                                conditions={**CLEAR, "inColoradoWyomingBox": True}).refused)
        self.assertEqual(check("technician", 904.5e6, 904.5e6, 1.0).refused, "")

    def test_refused_gaps(self):
        for f, words in ((219.5e6, "219-220 MHz"), (2_350e6, "2310-2390 MHz"), (3_400e6, "US103"),
                         (3_475e6, "14 April 2022")):
            self.assertIn(words, check("extra", f, f, 1.0).refused)

    def test_novice_vhf(self):
        # Novice: 222-225 MHz at 25 W PEP and 1270-1295 MHz at 5 W PEP only.
        self.assertEqual(check("novice", 223.5e6, 223.5e6, 25.0).warning, "")
        self.assertIn("25 W PEP", check("novice", 223.5e6, 223.5e6, 30.0).warning)
        self.assertIn("5.0 W PEP", check("novice", 1_294.5e6, 1_294.5e6, 6.0).warning)
        self.assertTrue(check("novice", 1_296.1e6, 1_296.1e6, 1.0).refused)
        self.assertTrue(check("novice", 145e6, 145e6, 1.0).refused)


class Satellite(unittest.TestCase):
    """us.md s.6: 2400-2450 MHz is amateur-satellite (RR 5.282); Novice has no 13 cm."""

    def test_qo100_uplink_by_class(self):
        for cls in ("technician", "general", "advanced", "extra"):
            allowed, limit, _ = licences.satellite_uplink(fcc, cls, *QO100)
            self.assertEqual((allowed, limit), (True, (1500.0, "PEP")), cls)
        self.assertFalse(licences.satellite_uplink(fcc, "novice", *QO100)[0])

    def test_downlink_only_bands_are_no_uplink(self):
        # 97.207(c) space-station bands are "down"; 1260-1270 MHz is Earth-to-space.
        self.assertFalse(licences.satellite_uplink(fcc, "extra", 145.9e6, 145.95e6)[0])
        self.assertTrue(licences.satellite_uplink(fcc, "extra", 1_265e6, 1_266e6)[0])

    def test_cept(self):
        # s.8: a CEPT visitor has Extra privileges.
        self.assertEqual(fcc.CEPT_VISITOR["T/R 61-01"], "extra")
        self.assertIn("advanced", fcc.CEPT["T/R 61-01"])


if __name__ == "__main__":
    unittest.main()
