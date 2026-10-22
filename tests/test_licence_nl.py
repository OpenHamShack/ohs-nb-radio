"""The Netherlands' registration (ohscore/licences/rdi.py) as the guard and
OpenHamShack NB's satellite check read it, against docs/ham/countries/nl.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import rdi
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, **kw):
    return guard.licence_check(cls, lo, hi, w, lic=rdi, region=1, today="2026-10-08", **kw)


class Netherlands(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(rdi), [])

    def test_class_f(self):
        # s.3 row 10: 20 m 400 W PEP.
        self.assertEqual(check("nl_f", 14_200_000, 14_202_700, 400.0, mode="usb").warning, "")
        self.assertIn("400 W PEP maximum", check("nl_f", 14_200_000, 14_202_700, 450.0, mode="usb").warning)
        # s.3 row 6: 60 m 15 W EIRP.
        self.assertEqual(check("nl_f", 5_354_000, 5_356_700, 15.0, mode="usb").warning, "")
        self.assertIn("15 W EIRP", check("nl_f", 5_354_000, 5_356_700, 16.0, mode="usb").warning)
        # s.3 rows 15-16: 6 m 120 W to 50.5 MHz, 30 W above.
        self.assertEqual(check("nl_f", 50_150_000, 50_152_700, 120.0, mode="usb").warning, "")
        self.assertIn("30 W PEP", check("nl_f", 51_500_000, 51_512_500, 31.0, mode="fm").warning)
        # s.3 row 17: 4 m F only, 50 W PEP.
        self.assertIn("50 W PEP", check("nl_f", 70_200_000, 70_202_700, 51.0, mode="usb").warning)
        # s.3 rows 21-22: 23 cm and 13 cm 120 W PEP.
        self.assertEqual(check("nl_f", 1_296_200_000, 1_296_202_700, 120.0, mode="usb").warning, "")
        self.assertIn("120 W PEP", check("nl_f", 2_320_200_000, 2_320_202_700, 130.0, mode="usb").warning)

    def test_class_n(self):
        # s.3 rows 39-44: N 40/20/10 m 100 W, 2 m and 70 cm 25 W PEP.
        self.assertEqual(check("nl_n", 7_100_000, 7_102_700, 100.0, mode="lsb").warning, "")
        self.assertIn("100 W PEP", check("nl_n", 14_200_000, 14_202_700, 110.0, mode="usb").warning)
        self.assertEqual(check("nl_n", 145_500_000, 145_512_500, 25.0, mode="fm").warning, "")
        self.assertIn("25 W PEP", check("nl_n", 438_000_000, 438_012_500, 26.0, mode="fm").warning)
        # s.3.2: N has no 160/80/60/30/17/15/12 m, no 6 m, 4 m, 23 cm or above.
        for lo in (1_830_000, 3_700_000, 5_354_000, 10_120_000, 18_100_000, 21_200_000, 24_900_000,
                   50_150_000, 70_200_000, 1_296_200_000, 2_320_200_000):
            self.assertTrue(check("nl_n", lo, lo + 500, 1.0).refused, lo)

    def test_emissions(self):
        # s.3 row 1: 2200 m A1A only; row 2: 630 m telegraphy only.
        self.assertEqual(check("nl_f", 136_000, 136_100, 1.0, mode="cw").refused, "")
        self.assertIn("WSPR is not permitted", check("nl_f", 136_000, 136_006, 1.0, mode="wspr").refused)
        self.assertIn("FT8 is not permitted", check("nl_f", 475_000, 475_050, 1.0, mode="ft8").refused)
        # s.3.1: 10.140-10.150 MHz at most 500 Hz; 10.100-10.140 no limit in law.
        self.assertIn("500 Hz", check("nl_f", 10_142_000, 10_143_000, 1.0, mode="rtty").refused)
        self.assertEqual(check("nl_f", 10_120_000, 10_121_000, 1.0, mode="rtty").refused, "")

    def test_gaps_are_refused(self):
        for cls in rdi.CLASSES:
            # s.3.2: 1880-2000 kHz, 60 m outside the WRC-15 band, 2300-2320, 3410-5650 MHz.
            self.assertIn("1880 kHz", check(cls, 1_900_000, 1_902_700, 1.0).refused)
            self.assertTrue(check(cls, 5_300_000, 5_302_700, 1.0).refused)
            self.assertIn("2320 MHz", check(cls, 2_310_000_000, 2_310_002_700, 1.0).refused)
            self.assertTrue(check(cls, 3_450_000_000, 3_450_002_700, 1.0).refused)

    def test_thirteen_cm_satellite_only(self):
        # s.3.1: 2400-2450 MHz Earth to space satellite only: no terrestrial use.
        self.assertIn("amateur-satellite service only", check("nl_f", 2_400_100_000, 2_400_102_700, 1.0).refused)

    def test_qo100_uplink(self):
        # s.4 and README.md point 6: F 120 W PEP, satellite uplink only; N none.
        self.assertEqual(licences.satellite_uplink(rdi, "nl_f", *QO100)[:2], (True, (120.0, "PEP")))
        self.assertFalse(licences.satellite_uplink(rdi, "nl_n", *QO100)[0])
        # s.4: no other satellite provision in law.
        self.assertFalse(licences.satellite_uplink(rdi, "nl_f", 145.85e6, 145.9e6)[0])

    def test_cept(self):
        # s.5: F is the T/R 61-01 licence, N the (05)06 novice; a (05)06 visitor has N.
        self.assertIn("rules of the country you are in", licences.cept_suggestion(rdi, "nl_f", rdi))
        self.assertIn("N class", licences.cept_suggestion(rdi, "nl_n", rdi))


if __name__ == "__main__":
    unittest.main()
