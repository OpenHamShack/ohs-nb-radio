"""The Australian licence regime (ohscore/licences/acma.py) against its
research, docs/ham/countries/au.md: the three tables' bands, the pX/pY
split by emission mode, the bandwidth limits, 60 m, the Radio Quiet Zone
and 3.4 GHz exclusions, and the 13 cm satellite uplink."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import acma
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)
CLEAR = {"inWaQuietZone": False, "inAu34GhzExcludedArea": False}


def check(cls, lo, hi, w, gain=0.0, mode=None, conditions=None):
    return guard.licence_check(cls, lo, hi, w, gain, lic=acma, mode=mode,
                               conditions=CLEAR if conditions is None else conditions, region=3,
                               today="2026-10-08")


class Shape(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(acma), [])
        self.assertEqual(acma.EDGES, "lower-open")


class Foundation(unittest.TestCase):
    """au.md s.3 Table A: 80 m (3.5-3.7), 40 m, 15 m, 10 m, 2 m, 70 cm at 10 W pX, any mode."""

    def test_bands_at_10_w(self):
        for lo, hi, mode in ((3_573_000, 3_573_050, "ft8"), (7_150_000, 7_152_700, "lsb"),
                             (21_074_000, 21_074_050, "ft8"), (146_500_000, 146_516_000, "fm"),
                             (439_000_000, 439_016_000, "fm")):
            v = check("au_foundation", lo, hi, 10.0, mode=mode)
            self.assertEqual((v.refused, v.warning), ("", ""), lo)
        self.assertIn("10 W PEP", check("au_foundation", 7_150_000, 7_152_700, 12.0, mode="lsb").warning)

    def test_no_160_30_20_17_12_6_m_or_23_cm(self):
        for f in (1_840_000, 10_136_000, 14_074_000, 18_100_000, 24_915_000, 50_313_000, 1_296_100_000):
            self.assertTrue(check("au_foundation", f, f + 50, 1.0, mode="ft8").refused, f)


class StandardAndAdvanced(unittest.TestCase):
    """au.md s.3: pX for J3E/R3E (and C3F), pY in any other case."""

    def test_standard_ssb_and_other(self):
        v = check("au_standard", 14_200_000, 14_202_700, 100.0, mode="usb")
        self.assertEqual((v.refused, v.warning), ("", ""))
        self.assertIn("100 W PEP", check("au_standard", 14_200_000, 14_202_700, 120.0, mode="usb").warning)
        # FT8 is J2D, not J3E: the 30 W pY figure.
        self.assertEqual(check("au_standard", 14_074_000, 14_074_050, 30.0, mode="ft8").warning, "")
        self.assertIn("30 W mean", check("au_standard", 14_074_000, 14_074_050, 40.0, mode="ft8").warning)

    def test_advanced_ssb_and_other(self):
        self.assertEqual(check("au_advanced", 3_790_000, 3_792_700, 400.0, mode="lsb").warning, "")
        self.assertIn("120 W mean", check("au_advanced", 146_500_000, 146_516_000, 150.0, mode="fm").warning)

    def test_standard_has_no_advanced_only_bands(self):
        # Advanced only: 160 m, 3.776-3.8, 30 m, 17 m, 12 m, 2300-2302, 3.3-3.6 GHz, 10 GHz and up.
        for f in (1_840_000, 3_790_000, 10_136_000, 18_100_000, 24_915_000, 2_301e6, 3_350e6, 10_368e6):
            self.assertTrue(check("au_standard", f, f + 50, 1.0, mode="cw").refused, f)
            self.assertEqual(check("au_advanced", f, f + 50, 1.0, mode="cw").refused, "", f)

    def test_2200_and_630_m_are_eirp_advanced_only(self):
        self.assertEqual(check("au_advanced", 136_000, 136_050, 1.0, mode="cw").warning, "")
        self.assertIn("1.0 W EIRP", check("au_advanced", 136_000, 136_050, 2.0, mode="cw").warning)
        self.assertIn("5.0 W EIRP", check("au_advanced", 475_000, 475_050, 6.0, mode="cw").warning)
        self.assertTrue(check("au_standard", 475_000, 475_050, 1.0, mode="cw").refused)

    def test_gaps(self):
        # s.3 gaps: 1.875-2.0, 3.7-3.776, 3.8-4.0, above 7.3 MHz.
        for f in (1_900_000, 3_750_000, 3_850_000, 7_350_000):
            self.assertTrue(check("au_advanced", f, f + 50, 1.0, mode="cw").refused, f)


class Bandwidth(unittest.TestCase):
    """au.md s.4: hard caps and the PSD rule (held to its threshold)."""

    def test_hard_caps(self):
        self.assertIn("8000 Hz", check("au_advanced", 7_150_000, 7_166_000, 1.0, mode="fm").refused)
        # 630 m: 3 kHz at most (2200 m's 2.1 kHz is the whole band's width).
        self.assertIn("3000 Hz", check("au_advanced", 473_000, 477_000, 0.5, mode="usb").refused)
        self.assertIn("100000 Hz", check("au_standard", 51_000_000, 51_200_000, 1.0, mode="fm").refused)

    def test_psd_bands_held_to_8_and_16_khz(self):
        self.assertIn("8000 Hz", check("au_advanced", 14_200_000, 14_216_000, 0.1, mode="fm").refused)
        self.assertEqual(check("au_advanced", 29_600_000, 29_616_000, 100.0, mode="fm").refused, "")

    def test_no_limit_from_52_mhz(self):
        self.assertEqual(check("au_advanced", 1_245_000_000, 1_253_000_000, 1.0, mode="sstv").refused, "")


class RefusedAndConditions(unittest.TestCase):
    def test_60_m_not_authorised(self):
        self.assertIn("60 m is not in", check("au_advanced", 5_357_000, 5_357_050, 1.0).refused)

    def test_radio_quiet_zone_refuses_everything_by_default(self):
        # s.3: no operation within 150 km of 26.704167 S, 116.658889 E; default refuses.
        self.assertIn("Radio Quiet Zone", check("au_foundation", 146.5e6, 146.5e6, 1.0, conditions={}).refused)
        self.assertEqual(check("au_foundation", 146.5e6, 146.5e6, 1.0).refused, "")

    def test_3_4_ghz_excluded_areas(self):
        self.assertIn("HCIS", check("au_advanced", 3_456e6, 3_456e6, 1.0,
                                    conditions={"inWaQuietZone": False}).refused)
        self.assertEqual(check("au_advanced", 3_456e6, 3_456e6, 1.0).refused, "")


class Satellite(unittest.TestCase):
    """au.md s.6: 2400-2450 MHz amateur-satellite by RR 5.282; Standard and Advanced, not Foundation."""

    def test_qo100_uplink_by_class(self):
        self.assertFalse(licences.satellite_uplink(acma, "au_foundation", *QO100, conditions=CLEAR)[0])
        for cls, w in (("au_standard", 30.0), ("au_advanced", 120.0)):
            allowed, limit, _ = licences.satellite_uplink(acma, cls, *QO100, conditions=CLEAR)
            self.assertEqual((allowed, limit), (True, (w, "mean")), cls)

    def test_quiet_zone_default_refuses_the_uplink(self):
        self.assertFalse(licences.satellite_uplink(acma, "au_advanced", *QO100)[0])

    def test_5830_downlink_only(self):
        self.assertFalse(licences.satellite_uplink(acma, "au_advanced", 5_835e6, 5_836e6, conditions=CLEAR)[0])

    def test_cept(self):
        # s.8: only Advanced is the CEPT licence; a CEPT visitor is Advanced.
        self.assertEqual(acma.CEPT_VISITOR, {"T/R 61-01": "au_advanced"})
        self.assertIn("not a CEPT licence", licences.cept_suggestion(acma, "au_standard", None))


if __name__ == "__main__":
    unittest.main()
