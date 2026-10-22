"""Germany's licence (ohscore/licences/bnetza.py) as the guard and OpenHamShack
NB's satellite check read it, against docs/ham/countries/de.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import bnetza
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, **kw):
    return guard.licence_check(cls, lo, hi, w, lic=bnetza, region=1, today="2026-10-08", **kw)


class Germany(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(bnetza), [])

    def test_class_a(self):
        # s.3 row 10: 20 m 750 W PEP.
        self.assertEqual(check("de_a", 14_200_000, 14_202_700, 750.0, mode="usb").warning, "")
        self.assertIn("750 W PEP maximum", check("de_a", 14_200_000, 14_202_700, 800.0, mode="usb").warning)
        # s.3 row 7: 60 m 9.14 W ERP; 9 W into a dipole (2.15 dBi) is 9 W ERP.
        self.assertEqual(check("de_a", 5_354_000, 5_356_700, 9.0, ant_gain_dbi=2.15, mode="usb").warning, "")
        self.assertIn("ERP", check("de_a", 5_354_000, 5_356_700, 10.0, ant_gain_dbi=2.15, mode="usb").warning)
        # s.3 rows 4-5: 1850-1890 kHz 75 W, 1890-2000 kHz 10 W PEP (weekday figures).
        self.assertIn("75 W PEP", check("de_a", 1_860_000, 1_862_700, 100.0, mode="lsb").warning)
        self.assertIn("10 W PEP", check("de_a", 1_950_000, 1_952_700, 11.0, mode="lsb").warning)
        # s.3 row 15: 6 m 750 W below 50.4 MHz; row 16: 25 W above.
        self.assertEqual(check("de_a", 50_150_000, 50_152_700, 750.0, mode="usb").warning, "")
        self.assertIn("25 W PEP", check("de_a", 51_510_000, 51_522_000, 30.0, mode="fm").warning)
        # s.3 row 23: 13 cm 75 W PEP.
        self.assertIn("75 W PEP", check("de_a", 2_320_200_000, 2_320_202_700, 80.0, mode="usb").warning)

    def test_class_e(self):
        # s.3: class E 80 m 100 W PEP; no 40 m, 30 m, 20 m, 60 m or 6 m.
        self.assertEqual(check("de_e", 3_700_000, 3_702_700, 100.0, mode="lsb").warning, "")
        self.assertIn("100 W PEP", check("de_e", 3_700_000, 3_702_700, 110.0, mode="lsb").warning)
        for lo in (7_100_000, 10_120_000, 14_200_000, 5_354_000, 50_150_000):
            self.assertTrue(check("de_e", lo, lo + 500, 1.0).refused, lo)
        # s.3 rows 17 and 23: 2 m 75 W PEP; 13 cm 5 W PEP.
        self.assertEqual(check("de_e", 145_500_000, 145_512_500, 75.0, mode="fm").warning, "")
        self.assertIn("5.0 W PEP", check("de_e", 2_320_200_000, 2_320_202_700, 6.0, mode="usb").warning)

    def test_class_n(self):
        # s.3: class N only 10 m (10 W ERP), 2 m and 70 cm (6.1 W ERP).
        self.assertEqual(check("de_n", 28_500_000, 28_502_700, 6.0, ant_gain_dbi=2.15, mode="usb").warning, "")
        self.assertIn("10 W ERP", check("de_n", 28_500_000, 28_502_700, 11.0, ant_gain_dbi=2.15, mode="usb").warning)
        self.assertEqual(check("de_n", 145_500_000, 145_512_500, 6.0, ant_gain_dbi=2.15, mode="fm").warning, "")
        self.assertIn("6.1 W ERP", check("de_n", 433_500_000, 433_512_500, 7.0, ant_gain_dbi=2.15, mode="fm").warning)
        for lo in (3_700_000, 14_200_000, 21_200_000, 1_296_200_000, 2_400_100_000):
            self.assertTrue(check("de_n", lo, lo + 2700, 1.0).refused, lo)

    def test_galileo_segment_adds_an_erp_cap(self):
        for cls in ("de_a", "de_e"):
            # s.3.1, B11: 1247-1263 MHz at most 3.05 W ERP for every class.
            self.assertEqual(check(cls, 1_255_000_000, 1_255_012_500, 3.0, ant_gain_dbi=2.15, mode="fm").warning, "")
            self.assertIn("3.0 W ERP", check(cls, 1_255_000_000, 1_255_012_500, 3.5, ant_gain_dbi=2.15,
                                             mode="fm").warning)
        # Outside it the row's PEP alone applies (row 21: A 750 W).
        self.assertEqual(check("de_a", 1_296_200_000, 1_296_202_700, 100.0, ant_gain_dbi=20.0, mode="usb").warning, "")

    def test_bandwidths_are_law(self):
        # s.3.1: 30 m 800 Hz (B1) rules out SSB; HF 2.7 kHz (B3); 6 m 12 kHz (B16).
        self.assertIn("800 Hz", check("de_a", 10_140_000, 10_142_700, 10.0, mode="usb").refused)
        self.assertEqual(check("de_a", 10_136_000, 10_136_050, 10.0, mode="ft8").refused, "")
        self.assertIn("2700 Hz", check("de_a", 14_200_000, 14_206_000, 10.0, mode="am").refused)
        self.assertIn("12000 Hz", check("de_a", 51_500_000, 51_516_000, 10.0, mode="fm").refused)
        # B4: 10 m 7 kHz below 29 MHz, 40 kHz above.
        self.assertIn("7000 Hz", check("de_n", 28_500_000, 28_516_000, 1.0, mode="fm").refused)
        self.assertEqual(check("de_n", 29_600_000, 29_616_000, 1.0, ant_gain_dbi=2.15, mode="fm").refused, "")

    def test_gaps_are_refused(self):
        for cls in bnetza.CLASSES:
            # s.1, s.8: 70 MHz not permitted in 2026 (status after June 2026 UNCONFIRMED).
            self.assertIn("70-70.5 MHz", check(cls, 70_200_000, 70_202_700, 1.0).refused)
            # s.3.2: 60 m only the WRC-15 band; 13 cm starts at 2320 MHz; 2450-3400 MHz none.
            self.assertTrue(check(cls, 5_300_000, 5_302_700, 1.0).refused)
            self.assertIn("2320 MHz", check(cls, 2_310_000_000, 2_310_002_700, 1.0).refused)
            self.assertTrue(check(cls, 2_500_000_000, 2_500_002_700, 1.0).refused)

    def test_qo100_uplink(self):
        # s.4 and README.md point 6: A 75 W PEP, E 5 W PEP, N none.
        self.assertEqual(licences.satellite_uplink(bnetza, "de_a", *QO100)[:2], (True, (75.0, "PEP")))
        self.assertEqual(licences.satellite_uplink(bnetza, "de_e", *QO100)[:2], (True, (5.0, "PEP")))
        self.assertFalse(licences.satellite_uplink(bnetza, "de_n", *QO100)[0])
        # s.4: 1260-1270 MHz Earth to space only; 5830-5850 MHz space to Earth only.
        self.assertTrue(licences.satellite_uplink(bnetza, "de_a", 1_265e6, 1_266e6)[0])
        self.assertFalse(licences.satellite_uplink(bnetza, "de_a", 5_835e6, 5_836e6)[0])
        # s.4: class N may use satellites on 2 m within its limits.
        self.assertTrue(licences.satellite_uplink(bnetza, "de_n", 145.85e6, 145.9e6)[0])

    def test_cept(self):
        # s.5: T/R 61-01 visitors get class A, (05)06 visitors class E; N is in neither.
        self.assertIn("Class A", licences.cept_suggestion(bnetza, "de_a", bnetza))
        self.assertIn("Class E", licences.cept_suggestion(bnetza, "de_e", bnetza))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(bnetza, "de_n", bnetza))


if __name__ == "__main__":
    unittest.main()
