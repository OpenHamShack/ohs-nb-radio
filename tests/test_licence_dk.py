"""Denmark's rules (ohscore/licences/digst.py) as the guard reads them,
each check against docs/ham/countries/dk.md: three categories, the wide
60 m, the legal spectral widths, the 23 cm changes of 2029 and the QO-100
uplink at 250 W (A) and 100 W (B)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import digst
from ohsradio import guard

TODAY = "2026-10-08"


def check(cls, lo, hi=None, w=None, gain=0.0, **kw):
    kw.setdefault("today", TODAY)
    return guard.licence_check(cls, lo, lo if hi is None else hi, w, gain, lic=digst, **kw)


class Denmark(unittest.TestCase):
    def ok(self, v):
        self.assertEqual((v.refused, v.warning), ("", ""))

    def test_validates(self):
        self.assertEqual(licences.validate(digst), [])

    def test_hf_a_and_b(self):
        # dk.md s.3: HF A 1000 W, B 100 W PEP; D nothing below 28 MHz.
        self.ok(check("dk_a", 14_200_000, 14_202_700, 1000.0, mode="usb"))
        self.assertIn("1000 W PEP", check("dk_a", 14_200_000, 14_202_700, 1100.0, mode="usb").warning)
        self.ok(check("dk_b", 14_200_000, 14_202_700, 100.0, mode="usb"))
        self.assertIn("100 W PEP", check("dk_b", 14_200_000, 14_202_700, 110.0, mode="usb").warning)
        self.assertIn("Category D", check("dk_d", 14_200_000, 14_202_700, 1.0).refused)
        # dk.md s.3.1: 1850-2000 kHz 10 W for A and B.
        self.assertIn("10 W PEP", check("dk_a", 1_900_000, 1_902_700, 20.0, mode="lsb").warning)

    def test_60m_is_wide(self):
        # dk.md s.3.1: 5250-5450 kHz, A 1000 W PEP, B 100 W, no channels.
        self.ok(check("dk_a", 5_260_000, 5_262_700, 1000.0, mode="usb"))
        self.ok(check("dk_b", 5_440_000, 5_442_700, 100.0, mode="usb"))
        self.assertTrue(check("dk_a", 5_460_000, None, 1.0).refused)

    def test_vhf_uhf_and_d(self):
        # dk.md s.3: 10 m, 6 m, 2 m, 70 cm: A 1000, B 100, D 50 W; 4 m 25 W for all.
        for lo in (28_500_000, 50_150_000, 144_300_000, 432_200_000):
            self.ok(check("dk_d", lo, lo + 2700, 50.0, mode="usb"))
            self.assertIn("50 W PEP", check("dk_d", lo, lo + 2700, 60.0, mode="usb").warning)
            self.ok(check("dk_a", lo, lo + 2700, 1000.0, mode="usb"))
        self.ok(check("dk_d", 69_890_000, 69_892_700, 25.0, mode="usb"))
        self.assertIn("25 W PEP", check("dk_a", 70_200_000, 70_202_700, 30.0, mode="usb").warning)
        # D: nothing above 1300 MHz.
        self.assertIn("Category D", check("dk_d", 2_400_100_000, 2_400_102_700, 1.0).refused)

    def test_lf_is_held_as_eirp(self):
        # dk.md s.3: 135.7 kHz 1 W "ERP" (PEP x efficiency), A and B; D none.
        self.ok(check("dk_a", 136_000, 136_100, 1.0, mode="cw"))
        self.assertIn("EIRP", check("dk_b", 136_000, 136_100, 2.0, mode="cw").warning)
        self.assertTrue(check("dk_d", 136_000, 136_100, 0.1).refused)

    def test_spectral_width_is_law(self):
        # dk.md s.3.1 (pkt. 3.2): 2.1 kHz below 1810 kHz, 8 kHz to 30 MHz, 16 kHz on 50-146 MHz.
        self.assertIn("2100 Hz", check("dk_a", 475_000, 478_000, 1.0, mode="usb").refused)
        self.ok(check("dk_a", 3_700_000, 3_706_000, 100.0, mode="am"))
        self.assertIn("8000 Hz", check("dk_a", 3_700_000, 3_710_000, 1.0, mode="am").refused)
        self.ok(check("dk_a", 145_500_000, 145_512_500, 1.0, mode="fm"))
        self.assertIn("16000 Hz", check("dk_a", 145_500_000, 145_525_000, 1.0, mode="fm").refused)

    def test_gaps(self):
        # dk.md s.3.2: 430-432, 438-440, 2300-2400 MHz not amateur.
        self.assertIn("430-432 MHz", check("dk_a", 431_000_000, None, 1.0).refused)
        self.assertIn("438-440 MHz", check("dk_a", 439_000_000, None, 1.0).refused)
        self.assertIn("2300-2400 MHz", check("dk_a", 2_320_200_000, None, 1.0).refused)

    def test_23cm_and_2029(self):
        # dk.md s.3: 1240-1298 MHz A 250, B 100, D 50 W now.
        self.ok(check("dk_a", 1_270_000_000, 1_270_012_500, 250.0, mode="fm"))
        self.ok(check("dk_b", 1_296_200_000, 1_296_202_700, 100.0, mode="usb"))
        # From 1 Jan 2029: 1258-1296 MHz withdrawn; 1296-1298 MHz 50 W.
        later = "2029-01-01"
        self.assertTrue(check("dk_a", 1_270_000_000, 1_270_012_500, 1.0, mode="fm", today=later).refused)
        self.assertIn("50 W PEP", check("dk_a", 1_296_200_000, 1_296_202_700, 100.0, mode="usb", today=later).warning)
        self.ok(check("dk_a", 1_250_000_000, 1_250_012_500, 250.0, mode="fm", today=later))
        # 1298-1300 MHz: 160 W (500 W only with conditions OpenHamShack cannot see).
        self.ok(check("dk_a", 1_299_000_000, 1_299_012_500, 160.0, mode="fm"))
        self.assertIn("160 W PEP", check("dk_a", 1_299_000_000, 1_299_012_500, 200.0, mode="fm").warning)

    def test_qo100(self):
        # dk.md s.4: 2400-2450 MHz amateur and amateur-satellite: A 250 W, B 100 W, D none.
        self.assertEqual(licences.satellite_uplink(digst, "dk_a", 2400.05e6, 2400.3e6, today=TODAY)[:2],
                         (True, (250.0, "PEP")))
        self.assertEqual(licences.satellite_uplink(digst, "dk_b", 2400.05e6, 2400.3e6, today=TODAY)[:2],
                         (True, (100.0, "PEP")))
        self.assertFalse(licences.satellite_uplink(digst, "dk_d", 2400.05e6, 2400.3e6, today=TODAY)[0])

    def test_cept(self):
        # dk.md s.5: A is T/R 61-01, B the CEPT Novice, D national only.
        self.assertEqual(digst.CEPT["ECC/REC (05)06"], ("dk_b",))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(digst, "dk_d", None))
        self.assertIn("CEPT licence (T/R 61-01)", licences.cept_suggestion(digst, "dk_a", None))


if __name__ == "__main__":
    unittest.main()
