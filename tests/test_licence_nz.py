"""The New Zealand licence regime (ohscore/licences/rsm.py) against its
research, docs/ham/countries/nz.md: the GURL's bands and dBW limits, the
new-holder 5-25 MHz rule, the dated 9 cm GUSLs, the refused gaps, and the
13 cm satellite uplink."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import rsm
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)


def check(cls, lo, hi, w, gain=0.0, mode=None, today="2026-10-08"):
    return guard.licence_check(cls, lo, hi, w, gain, lic=rsm, mode=mode, region=3, today=today)


class Shape(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(rsm), [])


class Power(unittest.TestCase):
    """nz.md s.3: 30 dBW (1000 W) PEP at the transmitter; SC8 rows e.i.r.p."""

    def test_30_dbw_pep(self):
        for cls in rsm.CLASSES:
            v = check(cls, 3_573_000, 3_573_050, 1000.0, mode="ft8")
            self.assertEqual((v.refused, v.warning), ("", ""), cls)
            self.assertIn("1000 W PEP", check(cls, 144_174_000, 144_174_050, 1100.0, mode="ft8").warning)

    def test_eirp_rows(self):
        # 630 m 14 dBW (25.1 W) e.i.r.p.; 33 cm 14 dBW e.i.r.p.; 2200 m 7 dBW (5.0 W).
        self.assertEqual(check("nz_gaoc", 475_000, 475_050, 25.0, mode="cw").warning, "")
        self.assertIn("W EIRP", check("nz_gaoc", 475_000, 475_050, 26.0, mode="cw").warning)
        self.assertIn("W EIRP", check("nz_gaoc", 925_200_000, 925_202_700, 30.0, mode="usb").warning)
        self.assertIn("W EIRP", check("nz_gaoc", 160_000, 160_050, 6.0, mode="cw").warning)

    def test_60_m_is_a_band_at_11_8_dbw_eirp(self):
        # 5351.5-5366.5 kHz, not channelised, 11.8 dBW (15.1 W) e.i.r.p.
        self.assertEqual(check("nz_gaoc", 5_357_000, 5_357_050, 15.0, mode="ft8").warning, "")
        self.assertIn("W EIRP", check("nz_gaoc", 5_357_000, 5_357_050, 16.0, mode="ft8").warning)


class NewHolders(unittest.TestCase):
    """G25 cl. 7(3): no 5-25 MHz in the first 3 months or before 50 contacts."""

    def test_no_5_to_25_mhz(self):
        for f in (5_357_000, 7_074_000, 10_136_000, 14_074_000, 18_100_000, 21_074_000, 24_915_000):
            self.assertTrue(check("nz_gaoc_new", f, f + 50, 1.0, mode="ft8").refused, f)
            self.assertEqual(check("nz_gaoc", f, f + 50, 1.0, mode="ft8").refused, "", f)

    def test_160_80_10_m_and_up_stay_open(self):
        for f in (1_840_000, 3_573_000, 28_074_000, 50_313_000, 144_174_000):
            self.assertEqual(check("nz_gaoc_new", f, f + 50, 1.0, mode="ft8").refused, "", f)

    def test_visitors_are_not_held_by_it(self):
        self.assertEqual(check("nz_visitor_cept", 14_074_000, 14_074_050, 1.0, mode="ft8").refused, "")


class Edges(unittest.TestCase):
    """nz.md s.3 gaps."""

    def test_refused_gaps(self):
        for f, words in ((1_960_000, "1950 kHz"), (3_950_000, "3900 kHz"), (2_350e6, "2396 MHz"),
                         (618e6, "614-622 MHz"), (27_100_000, "telemetry"), (5_321_000, "AREC"),
                         (3_450e6, "3410-3500")):
            self.assertIn(words, check("nz_gaoc", f, f + 50, 1.0).refused, f)

    def test_no_902_to_915_or_70_cm_above_440(self):
        self.assertTrue(check("nz_gaoc", 905e6, 905e6, 1.0).refused)
        self.assertEqual(check("nz_gaoc", 920e6, 920e6, 1.0).refused, "")
        self.assertTrue(check("nz_gaoc", 445e6, 445e6, 1.0).refused)


class Dated9cm(unittest.TestCase):
    """nz.md s.3: 3300-3400 MHz to 2033-06-30; 3400-3410 MHz 2026-07-01 to 2027-06-30 only."""

    def test_3400_3410(self):
        self.assertEqual(check("nz_gaoc", 3_405e6, 3_405e6, 1.0, today="2026-10-08").refused, "")
        self.assertTrue(check("nz_gaoc", 3_405e6, 3_405e6, 1.0, today="2027-07-01").refused)
        self.assertTrue(check("nz_gaoc", 3_405e6, 3_405e6, 1.0, today="2026-06-30").refused)

    def test_3300_3400(self):
        self.assertEqual(check("nz_gaoc", 3_350e6, 3_350e6, 1.0, today="2033-06-30").refused, "")
        self.assertTrue(check("nz_gaoc", 3_350e6, 3_350e6, 1.0, today="2033-07-01").refused)


class Satellite(unittest.TestCase):
    """nz.md s.6: 2400-2450 MHz SC5/SC6 for every class."""

    def test_qo100_uplink_by_class(self):
        for cls in rsm.CLASSES:
            allowed, limit, _ = licences.satellite_uplink(rsm, cls, *QO100)
            self.assertEqual((allowed, limit), (True, (1000.0, "PEP")), cls)

    def test_directions(self):
        self.assertTrue(licences.satellite_uplink(rsm, "nz_gaoc", 1_265e6, 1_266e6)[0])
        self.assertFalse(licences.satellite_uplink(rsm, "nz_gaoc", 5_835e6, 5_836e6)[0])
        # 2396-2400 MHz has no satellite permission.
        self.assertFalse(licences.satellite_uplink(rsm, "nz_gaoc", 2_397e6, 2_398e6)[0])

    def test_cept(self):
        # s.8: the GAOC is the CEPT licence; a T/R 61-01 or 61-02 visitor is the visiting class.
        self.assertEqual(rsm.CEPT_VISITOR["T/R 61-02"], "nz_visitor_cept")
        self.assertIn("nz_gaoc", rsm.CEPT["T/R 61-01"])


if __name__ == "__main__":
    unittest.main()
