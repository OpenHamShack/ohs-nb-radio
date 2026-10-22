"""Sweden's rules (ohscore/licences/pts.py) as the guard reads them, each
check against docs/ham/countries/se.md: PEP to the antenna system, the
160 m steps, the entry certificate's six bands and 2 m ERP, the 100 mW
13 cm and its QO-100 uplink, and the bands Sweden does not have."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import pts
from ohsradio import guard

TODAY = "2026-10-08"


def check(cls, lo, hi=None, w=None, gain=0.0, **kw):
    kw.setdefault("today", TODAY)
    return guard.licence_check(cls, lo, lo if hi is None else hi, w, gain, lic=pts, **kw)


class Sweden(unittest.TestCase):
    def ok(self, v):
        self.assertEqual((v.refused, v.warning), ("", ""))

    def test_validates(self):
        self.assertEqual(licences.validate(pts), [])

    def test_certifikat(self):
        # se.md s.3: 200 W PEP on most bands; 30 m 150 W.
        for lo in (3_700_000, 14_200_000, 50_150_000, 144_300_000, 432_200_000, 1_296_200_000, 5_760_200_000,
                   10_368_200_000):
            self.ok(check("certifikat", lo, lo + 2700, 200.0, mode="usb"))
            self.assertIn("200 W PEP maximum", check("certifikat", lo, lo + 2700, 250.0, mode="usb").warning)
        self.ok(check("certifikat", 10_120_000, 10_120_100, 150.0, mode="cw"))
        self.assertIn("150 W PEP", check("certifikat", 10_120_000, 10_120_100, 160.0, mode="cw").warning)

    def test_160m_steps(self):
        # se.md s.3.1: 1810-1850 200 W, 1850-1900 10 W, 1900-1950 100 W, 1950-2000 10 W PEP.
        self.ok(check("certifikat", 1_830_000, 1_830_100, 200.0, mode="cw"))
        self.assertIn("10 W PEP", check("certifikat", 1_870_000, 1_872_700, 20.0, mode="lsb").warning)
        self.ok(check("certifikat", 1_920_000, 1_922_700, 100.0, mode="lsb"))
        self.assertIn("10 W PEP", check("certifikat", 1_960_000, 1_962_700, 20.0, mode="lsb").warning)
        # A signal across a step is held to the lower figure.
        self.assertIn("10 W PEP", check("certifikat", 1_949_000, 1_951_000, 50.0, mode="lsb").warning)

    def test_eirp_and_erp_rows(self):
        # se.md s.3: 2200 m 1 W ERP; 60 m 15 W EIRP (5351.5-5366.5 kHz only).
        self.ok(check("certifikat", 136_000, 136_100, 1.0, 2.15, mode="cw"))
        self.assertIn("ERP", check("certifikat", 136_000, 136_100, 1.0, 5.0, mode="cw").warning)
        self.ok(check("certifikat", 5_360_000, 5_362_700, 15.0, mode="usb"))
        self.assertTrue(check("certifikat", 5_300_000, 5_302_700, 1.0).refused)

    def test_insteg(self):
        # se.md s.3: 25 W PEP on 40, 20, 15, 10 and 6 m; 25 W ERP on 2 m.
        for lo in (7_100_000, 14_200_000, 21_200_000, 28_500_000, 50_150_000):
            self.ok(check("insteg", lo, lo + 2700, 25.0, mode="usb"))
            self.assertIn("25 W PEP", check("insteg", lo, lo + 2700, 30.0, mode="usb").warning)
        # 25 W ERP: 25 W into a 2.15 dBi dipole passes; into 8.15 dBi (6 dBd) it is about 100 W ERP.
        self.ok(check("insteg", 145_500_000, 145_512_500, 25.0, 2.15, mode="fm"))
        self.assertIn("25 W ERP", check("insteg", 145_500_000, 145_512_500, 25.0, 8.15, mode="fm").warning)
        # se.md s.3.2: nothing else - no 160 m, 80 m, 30 m, 17 m, 12 m, 70 cm, 23 cm, 13 cm.
        for lo in (1_840_000, 3_700_000, 10_120_000, 18_100_000, 24_900_000, 432_200_000, 1_296_200_000,
                   2_400_100_000):
            self.assertIn("Entry certificate", check("insteg", lo, lo + 100, 1.0).refused)

    def test_bands_sweden_does_not_have(self):
        # se.md s.3.1-3.2: no 70 MHz, 430-432, 438-440, 2300-2400 MHz, 3.4 GHz.
        self.assertIn("70 MHz", check("certifikat", 70_200_000, None, 1.0).refused)
        self.assertIn("430-432 MHz", check("certifikat", 431_000_000, None, 1.0).refused)
        self.assertIn("438-440 MHz", check("certifikat", 439_000_000, None, 1.0).refused)
        self.assertIn("auctioned", check("certifikat", 2_320_200_000, None, 1.0).refused)
        self.assertIn("3.4 GHz", check("certifikat", 3_400_100_000, None, 1.0).refused)

    def test_13cm_and_qo100(self):
        # se.md s.3, s.4: 2400-2450 MHz 100 mW PEP, full certificate only; insteg none.
        self.ok(check("certifikat", 2_400_100_000, 2_400_102_700, 0.1, mode="usb"))
        self.assertIn("100 mW PEP", check("certifikat", 2_400_100_000, 2_400_102_700, 0.2, mode="usb").warning)
        self.assertEqual(licences.satellite_uplink(pts, "certifikat", 2400.05e6, 2400.3e6, today=TODAY)[:2],
                         (True, (0.1, "PEP")))
        self.assertFalse(licences.satellite_uplink(pts, "insteg", 2400.05e6, 2400.3e6, today=TODAY)[0])

    def test_cept(self):
        # se.md s.5: the full certificate is a CEPT licence; the entry certificate is not.
        self.assertEqual(pts.CEPT_VISITOR, {"T/R 61-01": "certifikat"})
        self.assertIn("not a CEPT licence", licences.cept_suggestion(pts, "insteg", None))


if __name__ == "__main__":
    unittest.main()
