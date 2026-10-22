"""Norway's licence (ohscore/licences/nkom.py) as the guard reads it, each
check against docs/ham/countries/no.md: the two classes' tables, the
legal bandwidths, the 23 cm change on 1 January 2028 and the QO-100
uplink for both classes."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import nkom
from ohsradio import guard

TODAY = "2026-10-08"


def check(cls, lo, hi=None, w=None, gain=0.0, **kw):
    kw.setdefault("today", TODAY)
    return guard.licence_check(cls, lo, lo if hi is None else hi, w, gain, lic=nkom, **kw)


class Norway(unittest.TestCase):
    def ok(self, v):
        self.assertEqual((v.refused, v.warning), ("", ""))

    def test_validates(self):
        self.assertEqual(licences.validate(nkom), [])

    def test_full(self):
        # no.md s.3: HF 1000 W PEP; 2 m and 70 cm 300 W; 13 cm 100 W.
        self.ok(check("no_full", 14_200_000, 14_202_700, 1000.0, mode="usb"))
        self.assertIn("1000 W PEP maximum", check("no_full", 14_200_000, 14_202_700, 1100.0, mode="usb").warning)
        self.ok(check("no_full", 144_300_000, 144_302_700, 300.0, mode="usb"))
        self.assertTrue(check("no_full", 144_300_000, 144_302_700, 400.0, mode="usb").warning)
        self.ok(check("no_full", 2_320_200_000, 2_320_202_700, 100.0, mode="usb"))
        # no.md s.3: 1850-2000 kHz 10 W mean; 60 m 5260-5410 kHz 100 W; 24740-24890 kHz 1000 W.
        self.ok(check("no_full", 1_900_000, 1_902_700, 10.0, mode="usb"))
        self.assertIn("10 W mean", check("no_full", 1_900_000, 1_902_700, 20.0, mode="usb").warning)
        self.ok(check("no_full", 5_300_000, 5_302_700, 100.0, mode="usb"))
        self.ok(check("no_full", 24_800_000, 24_802_700, 1000.0, mode="usb"))
        # no.md s.3: 4 m 69.9-70.5 MHz 100 W.
        self.ok(check("no_full", 70_200_000, 70_202_700, 100.0, mode="usb"))

    def test_lf_two_caps(self):
        # no.md s.3: 2200 m 200 W PEP and 1 W EIRP at once.
        self.ok(check("no_full", 136_000, 136_100, 1.0, mode="cw"))
        self.assertIn("1.0 W EIRP", check("no_full", 136_000, 136_100, 5.0, mode="cw").warning)

    def test_begrenset(self):
        # no.md s.3: 10 W PEP on its HF, 6 m, 2 m, 70 cm rows; 5 W on 13 cm; 1 W on 3 cm.
        self.ok(check("no_begrenset", 7_100_000, 7_102_700, 10.0, mode="usb"))
        self.assertIn("10 W PEP maximum", check("no_begrenset", 7_100_000, 7_102_700, 11.0, mode="usb").warning)
        self.ok(check("no_begrenset", 432_200_000, 432_202_700, 10.0, mode="usb"))
        self.ok(check("no_begrenset", 2_320_200_000, 2_320_202_700, 5.0, mode="usb"))
        self.assertTrue(check("no_begrenset", 2_320_200_000, 2_320_202_700, 6.0, mode="usb").warning)
        self.ok(check("no_begrenset", 10_368_200_000, 10_368_202_700, 1.0, mode="usb"))
        # no.md s.3.2: no 160 m, 60 m, 30 m, 12 m, 4 m, 23 cm, 9 cm, 6 cm, LF/MF.
        for lo in (1_840_000, 5_300_000, 10_120_000, 24_900_000, 70_200_000, 1_296_200_000, 3_400_100_000,
                   5_760_200_000, 475_000):
            self.assertIn("Restricted (begrenset) licence", check("no_begrenset", lo, lo + 100, 1.0).refused)

    def test_bandwidth_is_law(self):
        # no.md s.3: 6 kHz on most HF, 1 kHz on 30 m, 30 kHz on 70 cm but 200 kHz in 433.6-434.0 MHz.
        self.assertIn("6000 Hz", check("no_full", 14_200_000, 14_210_000, 1.0, mode="am").refused)
        self.assertIn("1000 Hz", check("no_full", 10_120_000, 10_122_700, 1.0, mode="usb").refused)
        self.ok(check("no_full", 10_120_000, 10_120_100, 1.0, mode="cw"))
        self.assertIn("30000 Hz", check("no_begrenset", 435_000_000, 435_100_000, 1.0, mode="hsmodem").refused)
        self.ok(check("no_begrenset", 433_700_000, 433_850_000, 1.0, mode="hsmodem"))

    def test_gaps(self):
        # no.md s.3.2: 430-432, 438-440 MHz and 10.00-10.25 GHz are not amateur; nor 3800-5260 kHz.
        self.assertIn("430-432 MHz", check("no_full", 431_000_000, None, 1.0).refused)
        self.assertIn("438-440 MHz", check("no_full", 439_000_000, None, 1.0).refused)
        self.assertIn("10.00-10.25 GHz", check("no_full", 10_100_000_000, None, 1.0).refused)
        self.assertTrue(check("no_full", 4_000_000, None, 1.0).refused)

    def test_23cm_changes_in_2028(self):
        # no.md s.3.1: to 31 Dec 2027, 1240-1300 MHz at 300 W.
        self.ok(check("no_full", 1_270_000_000, 1_270_012_500, 300.0, mode="fm"))
        # From 1 Jan 2028: 1258-1296 MHz 20 mW EIRP, 1296-1298 MHz 50 W, 1298-1300 158 W, 1240-1258 300 W.
        later = "2028-01-01"
        self.assertIn("EIRP", check("no_full", 1_270_000_000, 1_270_012_500, 1.0, mode="fm", today=later).warning)
        self.ok(check("no_full", 1_270_000_000, 1_270_012_500, 0.02, mode="fm", today=later))
        self.assertIn("50 W PEP", check("no_full", 1_296_200_000, 1_296_202_700, 60.0, mode="usb", today=later).warning)
        self.ok(check("no_full", 1_299_000_000, 1_299_012_500, 158.0, mode="fm", today=later))
        self.ok(check("no_full", 1_250_000_000, 1_250_012_500, 300.0, mode="fm", today=later))
        # Wider than 150 kHz on 1258-1300 MHz: refused (the stricter reading, now and from 2028).
        self.assertIn("150000 Hz", check("no_full", 1_280_000_000, 1_282_000_000, 1.0, mode="fm").refused)

    def test_qo100(self):
        # no.md s.4: QO-100 uplink inside 2300-2450 MHz: full 100 W PEP, begrenset 5 W PEP.
        self.assertEqual(licences.satellite_uplink(nkom, "no_full", 2400.05e6, 2400.3e6, today=TODAY)[:2],
                         (True, (100.0, "PEP")))
        self.assertEqual(licences.satellite_uplink(nkom, "no_begrenset", 2400.05e6, 2400.3e6, today=TODAY)[:2],
                         (True, (5.0, "PEP")))

    def test_cept(self):
        # no.md s.5: Full is the CEPT licence; begrenset is national only; no CEPT Novice.
        self.assertEqual(nkom.CEPT["T/R 61-01"], ("no_full",))
        self.assertEqual(nkom.CEPT_VISITOR, {"T/R 61-01": "no_full"})
        self.assertIn("not a CEPT licence", licences.cept_suggestion(nkom, "no_begrenset", None))


if __name__ == "__main__":
    unittest.main()
