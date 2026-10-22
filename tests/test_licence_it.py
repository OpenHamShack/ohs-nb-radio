"""Italy's licence (ohscore/licences/mimit.py) as the guard reads it, each
check against docs/ham/countries/it.md: one power for class A, the
narrower Italian allocation, satellite-only rows, the 2026 experiments,
class N with nothing yet, and no QO-100 uplink while its status is
unconfirmed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import mimit
from ohsradio import guard

TODAY = "2026-10-08"


def check(cls, lo, hi=None, w=None, gain=0.0, **kw):
    kw.setdefault("today", TODAY)
    return guard.licence_check(cls, lo, lo if hi is None else hi, w, gain, lic=mimit, **kw)


class Italy(unittest.TestCase):
    def ok(self, v):
        self.assertEqual((v.refused, v.warning), ("", ""))

    def test_validates(self):
        self.assertEqual(licences.validate(mimit), [])

    def test_class_a_500w_pep(self):
        # it.md s.3: A26 Art. 15, 500 W PEP on every band the PNRF gives.
        for lo in (1_840_000, 3_700_000, 14_200_000, 50_150_000, 144_300_000, 432_200_000, 1_296_200_000,
                   2_320_200_000, 2_410_000_000, 5_760_200_000, 10_368_200_000):
            self.ok(check("it_a", lo, lo + 2700, 500.0, mode="usb"))
            self.assertIn("500 W PEP maximum", check("it_a", lo, lo + 2700, 600.0, mode="usb").warning)

    def test_eirp_rows(self):
        # it.md s.3: 2200 m and 630 m 1 W EIRP (PNRF notes 8, 16); 60 m 15 W EIRP (note 32B).
        self.ok(check("it_a", 136_000, 136_100, 1.0, mode="cw"))
        self.assertIn("1.0 W EIRP", check("it_a", 475_000, 475_100, 2.0, mode="cw").warning)
        self.ok(check("it_a", 5_360_000, 5_362_700, 15.0, mode="usb"))
        self.assertIn("15 W EIRP", check("it_a", 5_360_000, 5_362_700, 15.0, 3.0, mode="usb").warning)

    def test_narrower_than_iaru(self):
        # it.md s.3.2: 434-435, 438-440, 1245-1267, 1298-1300, 5670-5760, 5770-5830 MHz, 10.0-10.3 GHz refused.
        for lo, words in ((434_500_000, "434-435 MHz"), (439_000_000, "438-440 MHz"), (1_250_000_000, "1245-1267"),
                          (1_299_000_000, "1298-1300"), (5_700_000_000, "5670-5760"), (5_800_000_000, "5770-5830"),
                          (10_100_000_000, "10.0-10.3 GHz"), (5_300_000, "5351.5-5366.5 kHz")):
            self.assertIn(words, check("it_a", lo, None, 1.0).refused)
        # 2 m-70 cm, 6 m-2 m: not amateur bands.
        self.assertTrue(check("it_a", 146_500_000, None, 1.0).refused)

    def test_satellite_only_rows(self):
        # it.md s.3: 145.8-146.0 MHz satellite contacts only (note 69); 1267-1270 and 5650-5670 MHz
        # Earth to space only: OpenHamShack HAM refuses all three.
        for lo in (145_900_000, 1_268_000_000, 5_660_000_000):
            self.assertIn("amateur-satellite service only", check("it_a", lo, lo + 2700, 1.0).refused)
        # ... and NB's uplink check allows them to class A.
        self.assertTrue(licences.satellite_uplink(mimit, "it_a", 145.9e6, 145.91e6, today=TODAY)[0])
        self.assertTrue(licences.satellite_uplink(mimit, "it_a", 1268e6, 1268.1e6, today=TODAY)[0])

    def test_experiments_2026(self):
        # it.md s.3 temporary table: 1810-1830 kHz and 40.660-40.700 MHz at 10 W, to 31 Dec 2026, with logging.
        self.assertIn("ARI's portal", check("it_a", 1_820_000, 1_820_100, 5.0, mode="cw").refused)
        on = {"ariExperiment160m": True, "ariExperiment8m": True}
        self.ok(check("it_a", 1_820_000, 1_820_100, 10.0, mode="cw", conditions=on))
        self.assertIn("10 W PEP", check("it_a", 1_820_000, 1_820_100, 20.0, mode="cw", conditions=on).warning)
        self.assertIn("ARI's portal", check("it_a", 40_680_000, 40_682_700, 5.0).refused)
        self.ok(check("it_a", 40_680_000, 40_682_700, 10.0, conditions=on))
        # Not after 31 Dec 2026.
        self.assertTrue(check("it_a", 1_820_000, 1_820_100, 5.0, conditions=on, today="2027-01-01").refused)
        # 4 m: three single channels whose placement is not stated - unconfirmed, refused.
        self.assertIn("unconfirmed", check("it_a", 70_100_000, 70_102_700, 1.0).refused)
        self.assertTrue(check("it_a", 70_150_000, None, 1.0).refused)

    def test_class_n_has_nothing_yet(self):
        # it.md s.2, s.8: class N's bands and power are unpublished.
        for lo in (3_700_000, 14_200_000, 144_300_000, 432_200_000):
            self.assertIn("Class N", check("it_n", lo, lo + 2700, 1.0).refused)
        self.assertFalse(licences.satellite_uplink(mimit, "it_n", 2400.05e6, 2400.3e6, today=TODAY)[0])

    def test_qo100(self):
        # it.md s.4: amateur-satellite only in 2440-2450 MHz; QO-100's 2400 MHz uplink is
        # [UNCONFIRMED], so refused for both classes - while terrestrial 2400-2440 MHz is allowed.
        self.assertFalse(licences.satellite_uplink(mimit, "it_a", 2400.05e6, 2400.3e6, today=TODAY)[0])
        self.ok(check("it_a", 2_400_100_000, 2_400_102_700, 500.0, mode="usb"))
        self.assertTrue(licences.satellite_uplink(mimit, "it_a", 2441e6, 2442e6, today=TODAY)[0])

    def test_cept(self):
        # it.md s.5: class A is T/R 61-01; visitors get class A; a CEPT Novice gets nothing.
        self.assertEqual(mimit.CEPT_VISITOR, {"T/R 61-01": "it_a"})
        self.assertNotIn("ECC/REC (05)06", mimit.CEPT)


if __name__ == "__main__":
    unittest.main()
