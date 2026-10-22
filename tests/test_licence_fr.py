"""France's licence (ohscore/licences/arcep.py) as the guard and OpenHamShack NB's
satellite check read it, against docs/ham/countries/fr.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import arcep
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, region=1, today="2026-10-08", **kw):
    return guard.licence_check(cls, lo, hi, w, lic=arcep, region=region, today=today, **kw)


class France(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(arcep), [])

    def test_harec(self):
        # s.3: HF 500 W PEP, 10 m 250 W, 50 MHz and up 120 W.
        self.assertEqual(check("harec", 14_200_000, 14_202_700, 500.0, mode="usb").warning, "")
        self.assertIn("500 W PEP maximum", check("harec", 14_200_000, 14_202_700, 550.0, mode="usb").warning)
        self.assertIn("250 W PEP", check("harec", 28_500_000, 28_502_700, 300.0, mode="usb").warning)
        self.assertEqual(check("harec", 144_300_000, 144_302_700, 120.0, mode="usb").warning, "")
        self.assertIn("120 W PEP", check("harec", 432_200_000, 432_202_700, 130.0, mode="usb").warning)
        # s.3: 2200 m and 630 m 1 W EIRP; 60 m 15 W EIRP.
        self.assertIn("1.0 W EIRP", check("harec", 475_000, 475_050, 2.0, mode="ft8").warning)
        self.assertEqual(check("harec", 5_354_000, 5_356_700, 15.0, mode="usb").warning, "")
        self.assertIn("15 W EIRP", check("harec", 5_354_000, 5_356_700, 16.0, mode="usb").warning)
        # s.3.1: 13 cm whole 2300-2450 MHz, no UK-style gaps.
        self.assertEqual(check("harec", 2_320_200_000, 2_320_202_700, 120.0, mode="usb").refused, "")

    def test_classe3(self):
        # s.3: class 3 144-146 MHz at 10 W PEP only.
        self.assertEqual(check("classe3", 145_500_000, 145_512_500, 10.0, mode="fm").warning, "")
        self.assertIn("10 W PEP", check("classe3", 145_500_000, 145_512_500, 11.0, mode="fm").warning)
        for lo in (3_700_000, 14_200_000, 50_150_000, 432_200_000, 2_400_100_000):
            self.assertTrue(check("classe3", lo, lo + 2700, 1.0).refused, lo)
        # s.3.1: class 3 only A1A, A2A, A3E, G3E, J3E, F3E: no data, no digital voice.
        self.assertEqual(check("classe3", 144_300_000, 144_302_700, 5.0, mode="usb").refused, "")
        self.assertIn("FT8 is not permitted", check("classe3", 144_174_000, 144_174_050, 5.0, mode="ft8").refused)
        self.assertIn("FREEDV is not permitted", check("classe3", 144_300_000, 144_301_250, 5.0,
                                                      mode="freedv").refused)
        self.assertEqual(check("harec", 144_174_000, 144_174_050, 5.0, mode="ft8").refused, "")

    def test_bandwidths_are_law(self):
        # s.3.1: 6 kHz below 28 MHz, 12 kHz 28-144 MHz, 20 kHz 144-225 MHz.
        self.assertIn("6000 Hz", check("harec", 7_100_000, 7_108_000, 10.0, mode="am").refused)
        self.assertEqual(check("harec", 7_100_000, 7_106_000, 10.0, mode="am").refused, "")
        self.assertIn("12000 Hz", check("harec", 29_600_000, 29_616_000, 10.0, mode="fm").refused)
        self.assertEqual(check("harec", 145_500_000, 145_516_000, 10.0, mode="fm").refused, "")

    def test_region_two_rows(self):
        # s.3: 1850-2000 kHz, 7200-7300 kHz and 146-148 MHz are Region 2 territories only.
        self.assertTrue(check("harec", 1_900_000, 1_902_700, 10.0, mode="lsb").refused)
        self.assertEqual(check("harec", 1_900_000, 1_902_700, 10.0, region=2, mode="lsb").refused, "")
        self.assertTrue(check("harec", 7_250_000, 7_252_700, 10.0, mode="lsb").refused)
        self.assertEqual(check("harec", 7_250_000, 7_252_700, 10.0, region=2, mode="lsb").refused, "")
        self.assertTrue(check("harec", 147_000_000, 147_012_500, 10.0, mode="fm").refused)
        self.assertEqual(check("harec", 147_000_000, 147_012_500, 10.0, region=2, mode="fm").refused, "")
        # s.3.2: no 3.4 GHz in Region 1.
        self.assertTrue(check("harec", 3_400_100_000, 3_400_102_700, 1.0).refused)

    def test_twenty_three_cm_from_2028(self):
        # s.3.1: until 27 June 2028, 120 W PEP over the whole band.
        self.assertEqual(check("harec", 1_270_000_000, 1_270_002_700, 100.0, mode="usb").warning, "")
        # From 27 June 2028 (TNRBF F53b, ECC/DEC/(25)01 Annex 1): 1258-1296 MHz -17 dBW EIRP,
        # 1296-1298 MHz 17 dBW (50 W).
        later = "2028-07-01"
        self.assertIn("EIRP", check("harec", 1_270_000_000, 1_270_002_700, 1.0, today=later, mode="usb").warning)
        self.assertIn("50 W PEP", check("harec", 1_296_200_000, 1_296_202_700, 60.0, today=later,
                                        mode="usb").warning)
        self.assertEqual(check("harec", 1_299_000_000, 1_299_002_700, 120.0, today=later, mode="usb").warning, "")
        # 1240-1258 MHz is unaffected.
        self.assertEqual(check("harec", 1_250_000_000, 1_250_002_700, 120.0, today=later, mode="usb").warning, "")

    def test_gaps_are_refused(self):
        for cls in arcep.CLASSES:
            # s.3.1: no 70 MHz; 60 m only the WRC-15 band.
            self.assertIn("70-70.5 MHz", check(cls, 70_200_000, 70_202_700, 1.0).refused)
            self.assertTrue(check(cls, 5_300_000, 5_302_700, 1.0).refused)

    def test_qo100_uplink(self):
        # s.4 and README.md point 6: harec 120 W PEP, no extra permission; classe3 none.
        self.assertEqual(licences.satellite_uplink(arcep, "harec", *QO100)[:2], (True, (120.0, "PEP")))
        self.assertFalse(licences.satellite_uplink(arcep, "classe3", *QO100)[0])
        # s.4: class 3 satellite only on 144-146 MHz.
        self.assertEqual(licences.satellite_uplink(arcep, "classe3", 145.85e6, 145.9e6)[:2], (True, (10.0, "PEP")))
        # s.4: 5830-5850 MHz space to Earth only.
        self.assertFalse(licences.satellite_uplink(arcep, "harec", 5_835e6, 5_836e6)[0])

    def test_cept(self):
        # s.5: HAREC is the CEPT licence; class 3 and (05)06 are not.
        self.assertIn("rules of the country you are in", licences.cept_suggestion(arcep, "harec", arcep))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(arcep, "classe3", arcep))


if __name__ == "__main__":
    unittest.main()
