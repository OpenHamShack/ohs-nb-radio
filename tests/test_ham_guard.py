"""The transmit guard: the UK licence (always enforced) and the RSGB band
plan (warn / enforce / off; beacons and satellites always refused).

Two kinds of test, as the design asks (DESIGN-HAM 8.1): tables generated
from the licence data - for every class and every allocation edge, a
signal just inside passes at the limit and just outside fails - and
hand-written cases quoted from the Ofcom schedule, so a typo in the data
would have to be repeated here to go unnoticed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohsradio import guard
from ohsradio.licences import ofcom


def lic(cls, lo, hi=None, w=None, **kw):
    return guard.licence_check(cls, lo, lo if hi is None else hi, w, **kw)


class Generated(unittest.TestCase):
    def _covered(self, cls, f):
        return any(cls in r[2] and r[0] <= f <= r[1] for r in ofcom.ALLOCATIONS)

    def test_every_edge_of_every_class(self):
        n = 0
        for lo, hi, limits, _note, _src in ofcom.ALLOCATIONS:
            for cls in ofcom.CLASSES:
                if cls not in limits:
                    continue
                w, kind = limits[cls]
                pep = guard.max_pep_for(kind, w, 0.0)
                for a, b in ((lo, lo + 100), (hi - 100, hi)):
                    v = lic(cls, a, b, pep * 0.999)
                    self.assertEqual(v.refused, "", (cls, a, b))
                    n += 1
                    # Over the limit: an estimate warns, a measurement refuses.
                    over = lic(cls, a, b, pep * 1.01)
                    self.assertEqual(over.refused, "", (cls, a, b))
                    self.assertIn("maximum", over.warning, (cls, a, b))
                    self.assertIn("estimate", over.warning, (cls, a, b))
                    self.assertIn("maximum", lic(cls, a, b, pep * 1.01, measured=True).refused, (cls, a, b))
                for f in (lo - 200, hi + 200):
                    if not self._covered(cls, f) and not (5_250_000 <= f <= 5_450_000):
                        self.assertTrue(lic(cls, f - 50, f + 50, 0.001).refused, (cls, f))
        self.assertGreater(n, 200)

    def test_class_order_never_loosens(self):
        # Wherever Foundation may transmit, Intermediate may, at no less power;
        # likewise Intermediate -> Full.
        for lo, hi, limits, _n, _s in ofcom.ALLOCATIONS:
            for a, b in (("foundation", "intermediate"), ("intermediate", "full")):
                if a in limits:
                    self.assertIn(b, limits, (lo, a))
                    self.assertGreaterEqual(limits[b][0], limits[a][0] if limits[b][1] == limits[a][1] else 0)


class QuotedFromTheSchedule(unittest.TestCase):
    """Each case quotes Ofcom OFW611 Schedule 1 (Tables A/B/C, Note G)."""

    def test_intermediate_32w_on_1850_2000(self):
        self.assertEqual(lic("intermediate", 1_900_000, 1_902_700, 30.0).refused, "")
        v = lic("intermediate", 1_900_000, 1_902_700, 40.0)
        self.assertEqual(v.refused, "")
        self.assertIn("32 W PEP maximum on 1850-2000 kHz", v.warning)
        self.assertIn("Intermediate licence", v.warning)
        self.assertIn("estimate is 40 W", v.warning)
        m = lic("intermediate", 1_900_000, 1_902_700, 40.0, measured=True)
        self.assertIn("32 W PEP maximum on 1850-2000 kHz", m.refused)
        self.assertIn("measured 40 W", m.refused)

    def test_lsb_below_1850_is_judged_by_both_rows(self):
        # An LSB signal straddling 1850 kHz: the tighter 32 W row applies.
        self.assertIn("32 W", lic("full", 1_848_000, 1_851_000, 100.0).warning)
        self.assertIn("32 W", lic("full", 1_848_000, 1_851_000, 100.0, measured=True).refused)
        self.assertEqual(lic("full", 1_846_000, 1_849_000, 100.0).warning, "")
        self.assertEqual(lic("full", 1_846_000, 1_849_000, 100.0, measured=True).refused, "")

    def test_full_1000w_primary_and_400w_secondary(self):
        self.assertEqual(lic("full", 14_200_000, 14_202_700, 1000.0).refused, "")
        self.assertIn("1000 W", lic("full", 14_200_000, 14_202_700, 1100.0, measured=True).refused)
        self.assertIn("400 W PEP maximum on 10100-10150 kHz",
                      lic("full", 10_120_000, 10_120_100, 500.0, measured=True).refused)

    def test_foundation_25w_and_no_23cm(self):
        self.assertEqual(lic("foundation", 145_500_000, 145_500_000, 25.0).refused, "")
        self.assertIn("25 W", lic("foundation", 145_500_000, 145_500_000, 26.0).warning)
        self.assertIn("25 W", lic("foundation", 145_500_000, 145_500_000, 26.0, measured=True).refused)
        self.assertIn("Foundation licence", lic("foundation", 1_297_500_000, None, 1.0).refused)
        self.assertIn("not available", lic("foundation", 1_297_500_000, None, 1.0).refused)
        self.assertEqual(lic("intermediate", 1_297_500_000, None, 1.0).refused, "")

    def test_foundation_2_4ghz_2w(self):
        self.assertEqual(lic("foundation", 2_401_000_000, None, 2.0).refused, "")
        self.assertIn("2.0 W", lic("foundation", 2_401_000_000, None, 3.0, measured=True).refused)

    def test_sixty_metres(self):
        self.assertIn("only to Full", lic("intermediate", 5_357_500, 5_357_550, 1.0).refused)
        self.assertEqual(lic("full", 5_357_500, 5_357_550, 100.0).refused, "")
        # FT8 on the 5357 kHz dial with its tone above 1 kHz leaves the
        # segment that ends at 5358 kHz (RSGB 2026 note 2).
        self.assertIn("eleven UK segments", lic("full", 5_358_500, 5_358_550, 10.0).refused)
        self.assertIn("100 W PEP", lic("full", 5_357_500, 5_357_550, 120.0).warning)
        self.assertIn("100 W PEP", lic("full", 5_357_500, 5_357_550, 120.0, measured=True).refused)
        self.assertIn("EIRP", lic("full", 5_357_500, 5_357_550, 100.0, ant_gain_dbi=6.0).warning)
        self.assertIn("EIRP", lic("full", 5_357_500, 5_357_550, 100.0, ant_gain_dbi=6.0, measured=True).refused)
        # Frequency rules stay hard whatever the power says.
        self.assertIn("eleven UK segments", lic("full", 5_358_500, 5_358_550, 0.001).refused)
        self.assertIn("6 kHz", lic("full", 5_362_000, 5_369_000, 10.0).refused)

    def test_430_mhz_is_erp(self):
        # 40 W ERP: with a 10 dBi antenna, 40 W ERP is 6.6 W PEP at the antenna.
        self.assertEqual(lic("full", 430_500_000, None, 6.5, ant_gain_dbi=10.0).refused, "")
        v = lic("full", 430_500_000, None, 7.0, ant_gain_dbi=10.0)
        self.assertIn("40 W ERP maximum", v.warning)
        self.assertIn("40 W ERP maximum", lic("full", 430_500_000, None, 7.0, ant_gain_dbi=10.0, measured=True).refused)
        self.assertEqual(lic("full", 432_200_000, None, 300.0, ant_gain_dbi=10.0).refused, "")

    def test_charing_cross(self):
        self.assertEqual(lic("full", 431_500_000, None, 1.0).refused, "")
        for cls in ofcom.CLASSES:
            v = lic(cls, 431_500_000, None, 1.0, near_london=True)
            self.assertIn("Charing Cross", v.refused, cls)
            self.assertIn("Schedule 1", v.refused, cls)
        # Only 431-432 MHz: either side is unaffected, and a signal whose
        # edge reaches into it is refused.
        self.assertEqual(lic("full", 430_990_000, 430_999_000, 1.0, near_london=True).refused, "")
        self.assertEqual(lic("full", 432_001_000, 432_010_000, 1.0, near_london=True).refused, "")
        self.assertIn("Charing Cross", lic("full", 431_994_500, 432_005_500, 1.0, near_london=True).refused)

    def test_gaps_and_innovation_bands(self):
        self.assertIn("not in the UK amateur licence", lic("full", 2_360_000_000, None, 1.0).refused)
        self.assertIn("not in the UK amateur licence", lic("full", 3_420_000_000, None, 1.0).refused)
        self.assertIn("Notice of Variation", lic("full", 146_500_000, None, 1.0).refused)
        self.assertIn("Notice of Variation", lic("full", 70_600_000, None, 1.0).refused)

    def test_band_edges(self):
        self.assertEqual(lic("full", 14_347_000, 14_349_700, 10.0).refused, "")
        self.assertIn("leave the allocation", lic("full", 14_348_000, 14_350_700, 10.0).refused)
        self.assertIn("not an amateur band", lic("full", 100_000_000, None, 1.0).refused)


class Plan(unittest.TestCase):
    def test_beacons_and_satellites_refused_even_with_the_plan_guard_off(self):
        for f in (14_100_000, 28_200_000, 144_450_000, 432_450_000, 1_296_900_000):
            self.assertIn("beacons", guard.plan_check("cw", f, f + 100, "off").refused, f)
        for f in (145_900_000, 436_000_000, 29_400_000):
            self.assertIn("satellites", guard.plan_check("fm", f - 5000, f + 5000, "off").refused, f)

    def test_ssb_reaching_the_ibp_slot_is_refused(self):
        # USB dialled at 14.0985 puts speech on 14.0988-14.1012.
        self.assertTrue(guard.plan_check("usb", 14_098_800, 14_101_200, "warn").refused)

    def test_warn_enforce_off(self):
        w = guard.plan_check("usb", 14_030_000, 14_032_700, "warn")
        self.assertEqual(w.refused, "")
        self.assertIn("SSB is not what the CW segment", w.warning)
        self.assertIn("SSB is not what", guard.plan_check("usb", 14_030_000, 14_032_700, "enforce").refused)
        o = guard.plan_check("usb", 14_030_000, 14_032_700, "off")
        self.assertEqual((o.refused, o.warning), ("", ""))

    def test_ft8_on_its_dial_is_fine_and_its_width_is_the_signal(self):
        v = guard.plan_check("ft8", 14_074_200, 14_077_000, "enforce", width=50.0)
        self.assertEqual((v.refused, v.warning), ("", ""))
        self.assertIn("500 Hz", guard.plan_check("ft8", 14_074_200, 14_077_000, "warn").warning)

    def test_fm_on_hf_below_29mhz_warns(self):
        self.assertIn("FM is not what", guard.plan_check("fm", 28_500_000 - 5500, 28_500_000 + 5500, "warn").warning)
        self.assertEqual(guard.plan_check("fm", 29_600_000 - 5500, 29_600_000 + 5500, "warn").warning, "")

    def test_repeater_output_is_not_for_transmitting(self):
        v = guard.plan_check("fm", 145_650_000 - 5500, 145_650_000 + 5500, "warn")
        self.assertIn("not for transmitting", v.warning)
        self.assertEqual(guard.plan_check("fm", 145_050_000 - 5500, 145_050_000 + 5500, "warn").warning, "")


class PowerHelpers(unittest.TestCase):
    def test_max_drive(self):
        self.assertAlmostEqual(guard.max_drive(25.0, 100.0), 0.5)
        self.assertEqual(guard.max_drive(25.0, 5.0), 1.0)

    def test_units(self):
        self.assertEqual(guard.watts(0.0045), "4.5 mW")
        self.assertEqual(guard.span(1_850_000, 2_000_000), "1850-2000 kHz")
        self.assertEqual(guard.span(430e6, 431e6), "430.0-431.0 MHz")


if __name__ == "__main__":
    unittest.main()
