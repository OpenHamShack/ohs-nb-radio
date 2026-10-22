"""Belgium's licence (ohscore/licences/bipt.py) as the guard and OpenHamShack NB's
satellite check read it, against docs/ham/countries/be.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import bipt
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, **kw):
    return guard.licence_check(cls, lo, hi, w, lic=bipt, region=1, today="2026-10-08", **kw)


class Belgium(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(bipt), [])

    def test_rows_with_a_stated_reference(self):
        # s.3: 2200 m 1 W e.u.v. (ERP), class A only.
        self.assertEqual(check("be_a", 136_000, 136_100, 1.0, ant_gain_dbi=2.15, mode="cw").warning, "")
        self.assertIn("ERP", check("be_a", 136_000, 136_100, 1.5, ant_gain_dbi=2.15, mode="cw").warning)
        # s.3: 630 m 5 W e.i.u.v. (EIRP).
        self.assertEqual(check("be_a", 475_000, 475_050, 5.0, mode="ft8").warning, "")
        self.assertIn("5.0 W EIRP", check("be_a", 475_000, 475_050, 6.0, mode="ft8").warning)
        # s.3.1: 60 m class A, encoded as the stricter 15 W EIRP.
        self.assertEqual(check("be_a", 5_354_000, 5_356_700, 15.0, mode="usb").warning, "")
        self.assertIn("15 W EIRP", check("be_a", 5_354_000, 5_356_700, 16.0, mode="usb").warning)
        for cls in ("be_b", "be_c"):
            self.assertTrue(check(cls, 5_354_000, 5_356_700, 1.0, mode="usb").refused)
            self.assertTrue(check(cls, 136_000, 136_100, 0.1, mode="cw").refused)

    def test_six_hundred_metres_is_a1a_only(self):
        # s.3: 501-504 kHz, A1A only, note (6) 100 Hz.
        self.assertEqual(check("be_a", 502_000, 502_050, 1.0, mode="cw").refused, "")
        self.assertIn("FT8 is not permitted", check("be_a", 502_000, 502_050, 1.0, mode="ft8").refused)

    def test_plain_watt_rows_are_refused_as_unconfirmed(self):
        # s.3 and s.8: power reference for plain "W" cells UNCONFIRMED.
        for cls, lo in (("be_a", 14_200_000), ("be_b", 3_700_000), ("be_c", 7_100_000), ("be_a", 145_500_000),
                        ("be_b", 433_500_000), ("be_a", 1_296_200_000), ("be_a", 2_320_200_000)):
            self.assertIn("unconfirmed", check(cls, lo, lo + 2700, 1.0).refused, (cls, lo))

    def test_four_metres(self):
        # s.3.1: 69.950 MHz channel, bandwidth 10 kHz or 10 Hz UNCONFIRMED.
        self.assertIn("unconfirmed", check("be_a", 69_949_000, 69_951_000, 1.0).refused)
        # s.3.2: 70.0-70.1125 and 70.4125-70.5 MHz not allowed.
        self.assertIn("69.950 MHz", check("be_a", 70_050_000, 70_052_700, 1.0).refused)
        self.assertIn("69.950 MHz", check("be_a", 70_450_000, 70_452_700, 1.0).refused)

    def test_gaps_are_refused(self):
        for cls in bipt.CLASSES:
            # s.3.2: 8 m only by permit (secondary source): refused.
            self.assertIn("BIPT", check(cls, 40_670_000, 40_672_700, 1.0).refused)
            # s.3.2: 60 m outside the WRC-15 band; no 9 cm.
            self.assertTrue(check(cls, 5_300_000, 5_302_700, 1.0).refused)
            self.assertTrue(check(cls, 3_400_100_000, 3_400_102_700, 1.0).refused)
        # s.3.2: class C has no 160 m, 17 m, 12 m or 6 m; class B no 23 cm.
        for lo in (1_830_000, 18_100_000, 24_900_000, 50_150_000):
            self.assertIn("not available", check("be_c", lo, lo + 500, 1.0).refused)
        self.assertIn("not available", check("be_b", 1_296_200_000, 1_296_202_700, 1.0).refused)

    def test_qo100_uplink(self):
        # s.4: class A has 2300-2450 MHz (200 W, reference UNCONFIRMED): refused until confirmed.
        self.assertFalse(licences.satellite_uplink(bipt, "be_a", *QO100)[0])
        # s.4 and README.md point 6: B and C have no 13 cm.
        self.assertFalse(licences.satellite_uplink(bipt, "be_b", *QO100)[0])
        self.assertFalse(licences.satellite_uplink(bipt, "be_c", *QO100)[0])

    def test_cept(self):
        # s.5: A is T/R 61-01, B is (05)06, C is in neither.
        self.assertIn("Class A class", licences.cept_suggestion(bipt, "be_a", bipt))
        self.assertIn("Class B class", licences.cept_suggestion(bipt, "be_b", bipt))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(bipt, "be_c", bipt))


if __name__ == "__main__":
    unittest.main()
