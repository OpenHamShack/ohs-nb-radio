"""Ireland's licence (ohscore/licences/comreg.py) as the guard and OpenHamShack
NB's satellite check read it, against docs/ham/countries/ie.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import comreg
from ohsradio import guard

CLASSES = ("cept1", "cept2")
QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, **kw):
    return guard.licence_check(cls, lo, hi, w, lic=comreg, region=1, today="2026-10-08", **kw)


class Ireland(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(comreg), [])

    def test_both_classes_share_one_table(self):
        # ie.md s.2: "Both classes have exactly the same bands and powers".
        for cls in CLASSES:
            with self.subTest(cls=cls):
                # s.3: 20 m 400 W (26 dBW) PEP.
                v = check(cls, 14_200_000, 14_202_700, 400.0, mode="usb")
                self.assertEqual((v.refused, v.warning), ("", ""))
                self.assertIn("400 W PEP maximum", check(cls, 14_200_000, 14_202_700, 500.0, mode="usb").warning)
                # s.3: 1850-2000 kHz is 10 W PEP.
                self.assertEqual(check(cls, 1_900_000, 1_902_700, 10.0, mode="lsb").warning, "")
                self.assertIn("10 W PEP", check(cls, 1_900_000, 1_902_700, 11.0, mode="lsb").warning)
                # s.3: 430-432 MHz 50 W, 432-440 MHz 400 W.
                self.assertIn("50 W PEP", check(cls, 431_000_000, 431_012_500, 60.0, mode="fm").warning)
                self.assertEqual(check(cls, 433_500_000, 433_512_500, 400.0, mode="fm").warning, "")
                # s.3: 8 m (30-49 MHz) and 5 m (54-69.9 MHz) at 50 W PEP; 4 m 50 W fixed.
                self.assertEqual(check(cls, 41_500_000, 41_512_500, 50.0, mode="fm").refused, "")
                self.assertEqual(check(cls, 58_500_000, 58_512_500, 50.0, mode="fm").warning, "")
                self.assertIn("50 W PEP", check(cls, 70_450_000, 70_462_500, 51.0, mode="fm").warning)
                # s.3: 2200 m 1 W EIRP; 0.5 W into a 0 dBi antenna is 0.5 W EIRP, 2 W is over.
                self.assertEqual(check(cls, 136_000, 136_100, 0.5, ant_gain_dbi=0.0, mode="cw").warning, "")
                self.assertIn("EIRP", check(cls, 136_000, 136_100, 2.0, mode="cw").warning)
                # s.3: 23 cm and 13 cm (2300-2400) 158 W PEP.
                self.assertEqual(check(cls, 1_296_200_000, 1_296_202_700, 158.0, mode="usb").warning, "")
                self.assertEqual(check(cls, 2_320_200_000, 2_320_202_700, 158.0, mode="usb").warning, "")

    def test_gaps_are_refused(self):
        for cls in CLASSES:
            # s.3.2: 52-54 MHz, 70.5-144 MHz and 146-430 MHz are not in the licence.
            self.assertTrue(check(cls, 53_000_000, 53_012_500, 1.0).refused)
            self.assertTrue(check(cls, 146_500_000, 146_512_500, 1.0).refused)
            # s.3.2: no 9 cm allocation at all.
            self.assertTrue(check(cls, 3_400_100_000, 3_400_102_700, 1.0).refused)
            # s.3: 10.270-10.300 GHz excluded.
            self.assertIn("10.270-10.300 GHz", check(cls, 10_280e6, 10_280.1e6, 1.0).refused)
            # s.3 and s.8: 1300-1304 MHz printed as "0W (0 dBW)": refused.
            self.assertIn("1300-1304 MHz", check(cls, 1_302e6, 1_302.0125e6, 1.0).refused)

    def test_sixty_metres(self):
        for cls in CLASSES:
            # s.3.1: WRC-15 band 5351.5-5366.5 kHz at 15 W EIRP.
            self.assertEqual(check(cls, 5_354_000, 5_356_700, 15.0, mode="usb").warning, "")
            self.assertIn("15 W EIRP", check(cls, 5_354_000, 5_356_700, 16.0, mode="usb").warning)
            # s.3.1, s.8: the spot frequencies (carrier or centre UNCONFIRMED) are refused.
            self.assertIn("spot frequencies", check(cls, 5_400_000, 5_402_700, 1.0, mode="usb").refused)
            self.assertIn("spot frequencies", check(cls, 5_280_000, 5_282_700, 1.0, mode="usb").refused)

    def test_thirty_metres_emissions(self):
        for cls in CLASSES:
            # s.3.1: 10100-10130 kHz "Morse Only".
            self.assertEqual(check(cls, 10_110_000, 10_110_100, 400.0, mode="cw").refused, "")
            self.assertIn("FT8 is not permitted", check(cls, 10_120_000, 10_120_050, 10.0, mode="ft8").refused)
            # s.3.1: 10130-10150 kHz narrowband digimodes up to 500 Hz; no SSB.
            self.assertEqual(check(cls, 10_136_000, 10_136_050, 10.0, mode="ft8").refused, "")
            self.assertIn("USB is not permitted", check(cls, 10_140_000, 10_142_700, 10.0, mode="usb").refused)
            self.assertIn("500 Hz", check(cls, 10_140_000, 10_141_000, 10.0, mode="rtty").refused)

    def test_thirteen_cm_satellite_band_needs_the_permit(self):
        for cls in CLASSES:
            # s.4: 2400-2450 MHz only by individual application, satellite only:
            # OpenHamShack HAM refuses it whether or not the permit is held.
            self.assertTrue(check(cls, 2_400_100_000, 2_400_102_700, 1.0).refused)
            self.assertTrue(check(cls, 2_400_100_000, 2_400_102_700, 1.0,
                                  conditions={"holdsComRegSatellitePermit": True}).refused)

    def test_qo100_uplink(self):
        # README.md point 6 / ie.md s.4: individual authorisation, satellite only, 25 W PEP.
        for cls in CLASSES:
            # Without the authorisation (the default): refused, naming ComReg.
            allowed, _, why = licences.satellite_uplink(comreg, cls, *QO100)
            self.assertFalse(allowed, cls)
            self.assertIn("ComReg", why)
            # With it: allowed at 25 W PEP.
            allowed, limit, _ = licences.satellite_uplink(comreg, cls, *QO100,
                                                          conditions={"holdsComRegSatellitePermit": True})
            self.assertTrue(allowed, cls)
            self.assertEqual(limit, (25.0, "PEP"))

    def test_cept(self):
        # s.5: both classes are T/R 61-01 licences; (05)06 not implemented.
        self.assertEqual(set(comreg.CEPT), {"T/R 61-01"})
        self.assertEqual(set(comreg.CEPT["T/R 61-01"]), set(CLASSES))


if __name__ == "__main__":
    unittest.main()
