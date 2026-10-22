"""Finland's licence (ohscore/licences/traficom.py) as the guard and OpenHamShack
NB's satellite check read it, against docs/ham/countries/fi.md."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import licences
from ohscore.licences import traficom
from ohsradio import guard

QO100 = (2_400_050_000.0, 2_400_300_000.0)
# The station has answered every location question with "no".
CLEAR = {"inFinnish4mExcludedArea": False, "nearFinnishBorder4m": False, "inTohmajarvi6mArea": False}


def check(cls, lo, hi, w, **kw):
    return guard.licence_check(cls, lo, hi, w, lic=traficom, region=1, today="2026-10-08", **kw)


class Finland(unittest.TestCase):
    def test_validates(self):
        self.assertEqual(licences.validate(traficom), [])

    def test_hf(self):
        # s.3: HF perus 120 W, yleis 1500 W (PEP with suppressed carrier, else carrier).
        self.assertEqual(check("perus", 14_200_000, 14_202_700, 120.0, mode="usb").warning, "")
        self.assertIn("120 W PEP", check("perus", 14_200_000, 14_202_700, 130.0, mode="usb").warning)
        self.assertIn("120 W carrier", check("perus", 14_020_000, 14_020_100, 130.0, mode="cw").warning)
        self.assertEqual(check("yleis", 14_200_000, 14_202_700, 1500.0, mode="usb").warning, "")
        # s.3: 1850-2000 kHz both classes 15 W carrier / 60 W PEP.
        self.assertEqual(check("yleis", 1_900_000, 1_902_700, 60.0, mode="lsb").warning, "")
        self.assertIn("15 W carrier", check("yleis", 1_900_000, 1_900_100, 20.0, mode="cw").warning)
        # s.3: 60 m 15 W EIRP; 630 m 1 W EIRP.
        self.assertIn("15 W EIRP", check("perus", 5_354_000, 5_356_700, 16.0, mode="usb").warning)
        self.assertIn("1.0 W EIRP", check("yleis", 475_000, 475_100, 2.0, mode="cw").warning)

    def test_vhf_carrier_and_pep(self):
        # s.3: 6 m perus 30 W carrier / 120 W PEP, yleis 150 / 200 W.
        self.assertEqual(check("perus", 50_150_000, 50_152_700, 120.0, mode="usb", conditions=CLEAR).warning, "")
        self.assertIn("30 W carrier", check("perus", 51_510_000, 51_522_000, 31.0, mode="fm",
                                            conditions=CLEAR).warning)
        self.assertIn("200 W PEP", check("yleis", 50_150_000, 50_152_700, 210.0, mode="usb",
                                         conditions=CLEAR).warning)
        # s.3: 2 m yleis 150 W carrier / 600 W PEP.
        self.assertEqual(check("yleis", 144_300_000, 144_302_700, 600.0, mode="usb").warning, "")
        self.assertIn("150 W carrier", check("yleis", 145_500_000, 145_512_500, 160.0, mode="fm").warning)
        # s.3.1: digital via SSB takes the carrier figure (the stricter reading; UNCONFIRMED).
        self.assertIn("150 W carrier", check("yleis", 144_300_000, 144_300_050, 160.0, mode="ft8").warning)
        # The mode not known: the strictest (carrier) applies.
        self.assertIn("30 W carrier", check("perus", 144_300_000, 144_302_700, 40.0).warning)

    def test_weak_signal_bonus(self):
        # s.3.1: yleis 600 W carrier for CW and digital in 144.000-144.150 and 432.000-432.150 MHz.
        self.assertEqual(check("yleis", 144_050_000, 144_050_100, 600.0, mode="cw").warning, "")
        self.assertEqual(check("yleis", 432_100_000, 432_100_050, 600.0, mode="ft8").warning, "")
        self.assertIn("600 W carrier", check("yleis", 144_050_000, 144_050_100, 650.0, mode="cw").warning)
        # Not for perus, and not above 144.150 MHz.
        self.assertIn("30 W carrier", check("perus", 144_050_000, 144_050_100, 40.0, mode="cw").warning)
        self.assertIn("150 W carrier", check("yleis", 144_200_000, 144_200_100, 160.0, mode="cw").warning)

    def test_four_metres(self):
        # s.3.1: 4 m refused in 13 eastern municipalities: the default until answered.
        self.assertIn("Lieksa", check("perus", 70_100_000, 70_102_700, 1.0, mode="usb").refused)
        ok = dict(CLEAR)
        # s.3: 70.050-70.250 perus 30 W, yleis 100 W; 70.250-70.300 25 W.
        self.assertEqual(check("yleis", 70_100_000, 70_102_700, 100.0, mode="usb", conditions=ok).warning, "")
        self.assertIn("30 W PEP", check("perus", 70_100_000, 70_102_700, 31.0, mode="usb", conditions=ok).warning)
        self.assertIn("25 W PEP", check("yleis", 70_260_000, 70_262_700, 26.0, mode="usb", conditions=ok).warning)
        # s.3.1 (b), (c): within 50 km of the Russian or Norwegian border, 25 W.
        near = dict(CLEAR, nearFinnishBorder4m=True)
        self.assertIn("25 W PEP", check("yleis", 70_100_000, 70_102_700, 50.0, mode="usb", conditions=near).warning)
        # s.3: 70.000-70.050 beacons only; nothing above 70.300.
        self.assertIn("beacons only", check("yleis", 70_020_000, 70_020_100, 1.0, conditions=ok).refused)
        self.assertIn("70.300", check("yleis", 70_400_000, 70_402_700, 1.0, conditions=ok).refused)

    def test_six_metres_tohmajarvi(self):
        # s.3.1 (F4): no 6 m TX in part of Tohmajärvi: refused until answered.
        self.assertIn("Tohmajärvi", check("yleis", 50_150_000, 50_152_700, 1.0, mode="usb").refused)

    def test_bandwidths_are_law(self):
        # s.3.1: F2 § 16, 8 kHz below 30 MHz, 18 kHz 50-146 MHz, 1 kHz on 30 m and 630 m.
        self.assertIn("1000 Hz", check("yleis", 10_140_000, 10_142_700, 10.0, mode="usb").refused)
        self.assertIn("8000 Hz", check("yleis", 7_100_000, 7_110_000, 10.0, mode="am").refused)
        self.assertIn("18000 Hz", check("yleis", 145_500_000, 145_520_000, 10.0, mode="fm").refused)

    def test_gaps_and_satellite_only(self):
        for cls in traficom.CLASSES:
            # s.3.1: 23 cm only by separate licence.
            self.assertIn("separate", check(cls, 1_296_200_000, 1_296_202_700, 1.0).refused)
            # s.3.2: 430-432 MHz is not amateur; 438.0625-438.1625 repeater outputs only.
            self.assertIn("430-432 MHz", check(cls, 431_000_000, 431_012_500, 1.0).refused)
            self.assertIn("repeater", check(cls, 438_100_000, 438_112_500, 1.0).refused)
            # s.3.1: 435-436 MHz amateur-satellite only.
            self.assertIn("amateur-satellite service only", check(cls, 435_500_000, 435_502_700, 1.0).refused)
            # s.3.2: 9 cm ends at 3408 MHz; 10.280-10.368 GHz is a gap.
            self.assertTrue(check(cls, 3_409_000_000, 3_409_002_700, 1.0).refused)
            self.assertTrue(check(cls, 10_300_000_000, 10_300_002_700, 1.0).refused)

    def test_qo100_uplink(self):
        # s.4 and README.md point 6: perus 30 W carrier / 120 W PEP; yleis 150 W / 600 W PEP.
        self.assertEqual(licences.satellite_uplink(traficom, "perus", *QO100)[:2], (True, (30.0, "carrier")))
        self.assertEqual(licences.satellite_uplink(traficom, "yleis", *QO100)[:2], (True, (150.0, "carrier")))
        # s.4: 435-436 MHz is satellite only and an uplink there is allowed.
        self.assertTrue(licences.satellite_uplink(traficom, "perus", 435.5e6, 435.6e6)[0])
        # s.4: 5830-5850 MHz downlink only.
        self.assertFalse(licences.satellite_uplink(traficom, "yleis", 5_835e6, 5_836e6)[0])

    def test_cept(self):
        # s.5: general class is HAREC / T/R 61-01; basic class CEPT use UNCONFIRMED;
        # CEPT Novice visitors held to the basic class.
        self.assertIn("rules of the country you are in", licences.cept_suggestion(traficom, "yleis", traficom))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(traficom, "perus", traficom))
        self.assertEqual(traficom.CEPT_VISITOR, {"ECC/REC (05)06": "perus"})


if __name__ == "__main__":
    unittest.main()
