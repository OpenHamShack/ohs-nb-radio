"""Spain's licence (ohscore/licences/setid.py) as the guard reads it, each
check against docs/ham/countries/es.md: the halved secondary figures, the
dated resolutions, the special-authorisation bands, 23 cm under
ECC/DEC/(25)01 and the QO-100 uplink."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import setid
from ohsradio import guard

TODAY = "2026-10-08"
C = "autorizacion"


def check(lo, hi=None, w=None, gain=0.0, **kw):
    kw.setdefault("today", TODAY)
    return guard.licence_check(C, lo, lo if hi is None else hi, w, gain, lic=setid, **kw)


class Spain(unittest.TestCase):
    def ok(self, v):
        self.assertEqual((v.refused, v.warning), ("", ""))

    def test_validates(self):
        self.assertEqual(licences.validate(setid), [])

    def test_primary_hf_and_vhf(self):
        # es.md s.3: 1.8-28 MHz 1000 W PEP where primary (B1 p.21).
        self.ok(check(14_200_000, 14_202_700, 1000.0, mode="usb"))
        self.assertIn("1000 W PEP maximum", check(14_200_000, 14_202_700, 1100.0, mode="usb").warning)
        # es.md s.3: 144-146 MHz 600 W PEP; 430-440 MHz 300 W PEP.
        self.ok(check(144_300_000, 144_302_700, 600.0, mode="usb"))
        self.assertTrue(check(144_300_000, 144_302_700, 700.0, mode="usb").warning)
        self.ok(check(432_200_000, 432_202_700, 300.0, mode="usb"))
        self.assertTrue(check(432_200_000, 432_202_700, 310.0, mode="usb").warning)

    def test_secondary_bands_are_halved(self):
        # es.md s.3: 160 m 1810-1830 secondary, 500 W PEP [derived]; 1830-1850 primary 1000 W.
        self.ok(check(1_820_000, 1_820_100, 500.0, mode="cw"))
        self.assertTrue(check(1_820_000, 1_820_100, 600.0, mode="cw").warning)
        self.ok(check(1_840_000, 1_840_100, 1000.0, mode="cw"))
        # es.md s.3: 30 m 500 W PEP [derived].
        self.ok(check(10_120_000, 10_120_100, 500.0, mode="cw"))
        self.assertTrue(check(10_120_000, 10_120_100, 510.0, mode="cw").warning)
        # es.md s.3 and s.8: 6 m and 4 m 300 W PEP [derived], not URE's 600 W.
        self.ok(check(50_150_000, 50_152_700, 300.0, mode="usb"))
        self.assertTrue(check(50_150_000, 50_152_700, 600.0, mode="usb").warning)
        self.ok(check(70_200_000, 70_202_700, 300.0, mode="usb"))
        # es.md s.3: 3 cm 500 W EIRP [derived]; 10 W with 20 dBi is 1000 W EIRP.
        self.ok(check(10_368_100_000, 10_368_102_700, 5.0, 20.0, mode="usb"))
        self.assertIn("500 W EIRP", check(10_368_100_000, 10_368_102_700, 10.0, 20.0, mode="usb").warning)

    def test_lf_and_60m_are_eirp(self):
        # es.md s.3: 2200 m and 630 m 1 W EIRP; 60 m 5351.5-5366.5 kHz 15 W EIRP.
        self.ok(check(475_000, 475_100, 1.0, mode="cw"))
        self.ok(check(5_360_000, 5_362_700, 15.0, mode="usb"))
        self.assertIn("15 W EIRP", check(5_360_000, 5_362_700, 16.0, mode="usb").warning)

    def test_gaps(self):
        # es.md s.3.2: not permitted - 60 m outside the WRC-15 band, 4 m outside 70.15-70.25, 3.4 GHz, 2 m-70 cm gap.
        self.assertIn("5351.5-5366.5 kHz", check(5_300_000, 5_302_700, 10.0).refused)
        self.assertIn("70.150-70.250 MHz", check(70_400_000, 70_402_700, 10.0).refused)
        self.assertIn("3.4 GHz", check(3_400_100_000, None, 1.0).refused)
        self.assertTrue(check(146_500_000, None, 1.0).refused)
        self.assertTrue(check(5_850_100_000, None, 1.0).refused)

    def test_160m_contest_resolution(self):
        # es.md s.3 temporary table: 1850-2000 kHz for contests only, 2026, 1000 W PEP (S2).
        self.assertIn("contests only", check(1_900_000, 1_902_700, 100.0).refused)
        self.ok(check(1_900_000, 1_902_700, 1000.0, conditions={"inContest": True}))
        # Not after 31 Dec 2026.
        self.assertTrue(check(1_900_000, 1_902_700, 100.0, conditions={"inContest": True},
                              today="2027-01-01").refused)

    def test_8m_resolution(self):
        # es.md s.3 temporary table: 40.650-40.750 MHz 100 W PEP, fixed stations, prior notice (S3).
        self.assertIn("Jefatura Provincial", check(40_700_000, 40_702_700, 50.0).refused)
        self.ok(check(40_700_000, 40_702_700, 100.0, conditions={"notified8m": True}))
        self.assertTrue(check(40_700_000, 40_702_700, 110.0, conditions={"notified8m": True}).warning)
        # 18 months from signing (13 Oct 2025) [derived]: gone after 13 Apr 2027.
        self.assertTrue(check(40_700_000, 40_702_700, 50.0, conditions={"notified8m": True},
                              today="2027-04-14").refused)

    def test_23cm_under_ecc_25_01(self):
        # es.md s.3: 1240-1258 MHz 500 W EIRP [derived].
        self.ok(check(1_250_000_000, 1_250_002_700, 500.0, mode="usb"))
        # es.md s.3.1: 1258-1296 MHz -17 dBW EIRP (20 mW).
        self.ok(check(1_270_000_000, 1_270_012_500, 0.019, mode="fm"))
        self.assertIn("EIRP", check(1_270_000_000, 1_270_012_500, 0.5, mode="fm").warning)
        # es.md s.3.1: 1296-1298 MHz 17 dBW (50 W) transmitter power.
        self.ok(check(1_296_200_000, 1_296_202_700, 50.0, mode="usb"))
        self.assertIn("50 W PEP", check(1_296_200_000, 1_296_202_700, 60.0, mode="usb").warning)
        # ... and the 500 W EIRP cap still applies: 50 W with 15 dBi is 1581 W EIRP.
        self.assertIn("500 W EIRP", check(1_296_200_000, 1_296_202_700, 50.0, 15.0, mode="usb").warning)
        # es.md s.3.1: 1298-1300 MHz 22 dBW (158 W).
        self.ok(check(1_299_000_000, 1_299_012_500, 158.0, mode="fm"))
        self.assertTrue(check(1_299_000_000, 1_299_012_500, 170.0, mode="fm").warning)
        # es.md s.3.1: wideband (> 150 kHz) is -17 dBW/MHz: refused on 1296-1300.
        self.assertIn("150000 Hz", check(1_298_000_000, 1_300_000_000, 1.0, mode="fm").refused)
        # UN-122 in force from 18 Jul 2026: before that there is no row here.
        self.assertTrue(check(1_296_200_000, 1_296_202_700, 1.0, today="2026-07-17").refused)

    def test_special_authorisation_bands(self):
        # es.md s.3 (B2, DA2): 2316-2332 MHz free, 500 W EIRP [derived].
        self.ok(check(2_320_200_000, 2_320_202_700, 500.0, mode="usb"))
        # 2300-2316 and 2332-2450 MHz need a special authorisation.
        self.assertIn("special authorisation", check(2_305_000_000, None, 1.0).refused)
        self.assertIn("special authorisation", check(2_340_000_000, None, 1.0).refused)
        self.ok(check(2_340_000_000, 2_340_002_700, 500.0, conditions={"holdsSa2332": True}))
        self.ok(check(2_305_000_000, 2_305_002_700, 1.0, conditions={"holdsSa2300": True}))
        # 6 cm: 5700-5720 and 5760-5762 free; the rest needs authorisation.
        self.ok(check(5_760_100_000, 5_760_102_700, 1.0, mode="usb"))
        self.ok(check(5_710_000_000, 5_710_002_700, 1.0))
        for f, key in ((5_660_000_000, "holdsSa5650"), (5_740_000_000, "holdsSa5720"), (5_800_000_000, "holdsSa5762")):
            self.assertIn("special authorisation", check(f, None, 1.0).refused)
            self.ok(check(f, f + 2700, 1.0, conditions={key: True}))

    def test_qo100(self):
        # es.md s.4 (S1): 2400-2410 MHz to QO-100 only - OpenHamShack HAM refuses it as terrestrial.
        self.assertIn("amateur-satellite service only", check(2_400_100_000, 2_400_102_700, 1.0).refused)
        # NB's uplink: allowed at 1500 W EIRP while S1 is valid (to 26 Dec 2026), not after.
        allowed, lim, _ = licences.satellite_uplink(setid, C, 2400.050e6, 2400.300e6, today=TODAY)
        self.assertTrue(allowed)
        self.assertEqual(lim, (1500.0, "EIRP"))
        self.assertFalse(licences.satellite_uplink(setid, C, 2400.050e6, 2400.300e6, today="2026-12-27")[0])
        # es.md s.4: the rest of 2400-2450 MHz needs the special authorisation (DA2).
        self.assertFalse(licences.satellite_uplink(setid, C, 2420e6, 2421e6, today=TODAY)[0])
        self.assertTrue(licences.satellite_uplink(setid, C, 2420e6, 2421e6, conditions={"holdsSa2410": True},
                                                  today=TODAY)[0])
        self.assertIn("special authorisation", check(2_420_000_000, None, 1.0).refused)

    def test_cept(self):
        # es.md s.5: the authorisation is a CEPT licence; a T/R 61-01 visitor gets it.
        self.assertEqual(setid.CEPT_VISITOR, {"T/R 61-01": C})
        self.assertIn(C, setid.CEPT["T/R 61-01"])
        self.assertNotIn("ECC/REC (05)06", setid.CEPT_VISITOR)


if __name__ == "__main__":
    unittest.main()
