import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
# The band plans as data (ohsradio/plans): every registered plan is
# well-formed, the three IARU regional plans say what their documents say,
# and choose() picks the plan in force in the order it promises.
#
# The spot checks quote the row of docs/ham/bandplan-iaru-regions.md they
# come from (that document gives each row's source page), so a typo in a
# plan module would have to be repeated here to go unnoticed.
import unittest

from ohsradio import guard, plans
from ohsradio.plans import base, iaru_r1, iaru_r2, iaru_r3, rsgb_2026

REGIONAL = (iaru_r1, iaru_r2, iaru_r3)


def check(plan, mode, lo, hi=None, g="warn", width=None):
    return guard.plan_check(mode, lo, lo if hi is None else hi, g, plan=plan, width=width)


def fine(v) -> bool:
    return not v.refused and not v.warning


class EveryPlan(unittest.TestCase):
    def test_every_registered_plan_validates(self):
        for pid, plan in plans.PLANS.items():
            self.assertEqual(plan.ID, pid)
            self.assertEqual(base.validate(plan), [], pid)

    def test_regional_plans_are_registered_by_region(self):
        for n, plan in zip((1, 2, 3), REGIONAL):
            self.assertEqual(plans.REGIONAL[n], plan.ID)
            self.assertIs(plans.get(plans.for_region(n)), plan)
            self.assertEqual(plan.REGION, n)
            self.assertEqual(plan.COUNTRY, ())

    def test_reserved_segments_are_refused_with_the_guard_off(self):
        # Generated: the middle of every beacon and satellite segment of
        # every plan is refused whatever the plan guard says; the middle of
        # every repeater output is "not for transmitting" but not refused.
        for plan in plans.PLANS.values():
            for s in plan.SEGMENTS:
                f = (s.lo + s.hi) / 2
                if s.refused:
                    self.assertTrue(check(plan, "cw", f, f, "off").refused, (plan.ID, s.label))
                elif s.kind == "output":
                    v = check(plan, "fm", f, f, "warn")
                    self.assertEqual(v.refused, "", (plan.ID, s.label))
                    self.assertIn("not for transmitting", v.warning, (plan.ID, s.label))

    def test_ibp_beacons_sit_in_refused_segments(self):
        for plan in plans.PLANS.values():
            self.assertEqual(len(plan.IBP), 5, plan.ID)
            for f in plan.IBP:
                self.assertTrue(check(plan, "cw", f, f + 50, "off").refused, (plan.ID, f))

    def test_centres_are_inside_a_segment_that_is_not_refused(self):
        for plan in REGIONAL:
            for f, label, _mode in plan.CENTRES:
                s = plan.segment_at(f)
                self.assertIsNotNone(s, (plan.ID, f, label))
                self.assertFalse(s.refused, (plan.ID, f, label))


class Region1(unittest.TestCase):
    p = iaru_r1

    def test_ibp_slot_is_refused(self):
        # §3.1 20 m: "14099 | 14101 | ... | beacon | International Beacon
        # Project - Beacons exclusively"
        self.assertTrue(check(self.p, "cw", 14_100_000, 14_100_100, "off").refused)
        self.assertTrue(check(self.p, "usb", 14_098_800, 14_101_200, "warn").refused)

    def test_ssb_in_the_cw_segment_warns(self):
        # §3.1 40 m: "7000 | 7040 | 200 | cw | | CW"
        v = check(self.p, "lsb", 7_012_300, 7_015_000)
        self.assertEqual(v.refused, "")
        self.assertIn("SSB is not what", v.warning)
        self.assertIn("SSB is not what", check(self.p, "lsb", 7_012_300, 7_015_000, "enforce").refused)
        self.assertTrue(fine(check(self.p, "lsb", 7_012_300, 7_015_000, "off")))

    def test_ft8_on_its_dial_is_fine(self):
        # §3.1 40 m: "7060 | 7100 | 2700 | all modes" (all modes includes
        # digimodes, §2); WSJT-X's 7074 dial.
        self.assertTrue(fine(check(self.p, "ft8", 7_074_200, 7_077_000, "enforce", width=50.0)))

    def test_ssb_is_not_for_21110_21120(self):
        # §3.1 15 m: "21110 | 21120 | 2700 | cw, digi, dv, image (not SSB)"
        self.assertIn("SSB is not what", check(self.p, "usb", 21_110_300, 21_112_700).warning)
        self.assertTrue(fine(check(self.p, "ft8", 21_114_000, 21_114_050)))

    def test_not_ssb_means_not_am_either(self):
        # §3.1 15 m: 21110-21120 "cw, digi, dv, image (not SSB)".
        self.assertIn("AM is not what", check(self.p, "am", 21_112_000, 21_118_000).warning)

    def test_aprs_on_its_centre_is_fine(self):
        # §3.2 2 m: 144.800 APRS, which is FM AFSK.
        self.assertTrue(fine(check(self.p, "fm", 144_794_000, 144_806_000, "enforce")))

    def test_60m_weak_signal_slot_is_20_hz(self):
        # §3.1 60 m: "5366.0 | 5366.5 | 20 | digi | | 'Weak signal narrow
        # band modes', printed '20 (!)'"
        self.assertTrue(fine(check(self.p, "wspr", 5_366_200, 5_366_206, width=6.0)))
        self.assertIn("20 Hz", check(self.p, "ft8", 5_366_100, 5_366_150, width=50.0).warning)

    def test_10m_guard_channel_is_refused(self):
        # §3.1 10 m: "29510 | 29520 | (none) | (none) | guard | 'Guard Channel'"
        self.assertTrue(check(self.p, "fm", 29_515_000, 29_515_000, "off").refused)

    def test_10m_satellite_links_are_shared(self):
        # §3.1 10 m: "29300 | 29510 | ... | 'Satellite Links'", listed as
        # shared in §6 point 5 ("R1/R3 29300-29510").
        self.assertTrue(fine(check(self.p, "usb", 29_400_300, 29_402_700, "enforce")))

    def test_21mhz_satellite_uplink_is_shared(self):
        # §3.1 15 m: 21125-21450 "on a non-exclusive basis".
        self.assertTrue(fine(check(self.p, "usb", 21_400_300, 21_402_700, "enforce")))

    def test_1850_2000_is_left_to_a_national_plan(self):
        # §3.1 160 m: "The 1850-2000 part is not allocated in most of R1".
        self.assertIsNone(self.p.segment_at(1_900_000))
        self.assertIsNotNone(self.p.segment_at(1_845_000))

    def test_4m_and_9cm_are_left_to_a_national_plan(self):
        # §3.3 "The code should offer this band only when the country's own
        # plan says so"; §3.8 "This band is national only in R1".
        self.assertEqual(self.p.overlapping(70_000_000, 70_500_000), [])
        self.assertEqual(self.p.overlapping(3_400_000_000, 3_475_000_000), [])

    def test_2m_beacons_and_satellites_refused(self):
        # §3.4: "144.400 | 144.490 | ... | beacon | 'Beacons exclusive'";
        # "145.806 | 146.000 | ... | satellite | 'Satellite exclusive'".
        self.assertTrue(check(self.p, "cw", 144_450_000, 144_450_100, "off").refused)
        self.assertTrue(check(self.p, "fm", 145_900_000 - 5000, 145_900_000 + 5000, "off").refused)

    def test_no_transmission_below_144_0025(self):
        # §3.4 footnote r / §6 point 3: "No transmission shall be made below
        # 144,0025 MHz"; the rest of 144.000-144.025 is shared.
        self.assertTrue(check(self.p, "cw", 144_001_000, 144_001_100, "off").refused)
        self.assertEqual(check(self.p, "cw", 144_010_000, 144_010_100, "off").refused, "")

    def test_2m_repeater_output_warns(self):
        # §3.4: "145.575 | 145.7935 | 12 kHz | fm, dv | output | 'Repeater
        # Output exclusive'"
        v = check(self.p, "fm", 145_650_000 - 5500, 145_650_000 + 5500)
        self.assertEqual(v.refused, "")
        self.assertIn("not for transmitting", v.warning)
        self.assertTrue(fine(check(self.p, "fm", 145_050_000 - 5500, 145_050_000 + 5500)))

    def test_6m_wideband_note_e_as_read(self):
        # §3.2 note (e): "maximum 200 kHz in a segment printed '50.9-50.2'
        # (as printed; probably 50.9-51.2)".
        self.assertEqual(self.p.segment_at(51_000_000).max_bw, 200_000)


class Region2(unittest.TestCase):
    p = iaru_r2

    def test_40m_runs_to_7300(self):
        # §4.1 40 m: "7200 | 7300 | 2700 (*) | all modes". R1 stops at 7200
        # (§3.1 40 m, last row "7175 | 7200").
        self.assertIsNotNone(self.p.segment_at(7_250_000))
        self.assertIsNone(iaru_r1.segment_at(7_250_000))
        self.assertTrue(fine(check(self.p, "lsb", 7_247_300, 7_249_700, "enforce")))

    def test_80m_runs_to_4000(self):
        # §4.1 80 m: "3900 | 4000 | 2700 | all modes"; R1 ends at 3800.
        self.assertIsNotNone(self.p.segment_at(3_950_000))
        self.assertIsNone(iaru_r1.segment_at(3_950_000))

    def test_am_at_6khz_where_starred(self):
        # §4.1: '"(*)" means DSB AM is allowed at up to 6 kHz'; 80 m
        # "3875 | 3900 | 2700 (*)" with the 3885 AM centre, against
        # "3650 | 3700 | 2700 | all modes".
        self.assertTrue(fine(check(self.p, "am", 3_885_000 - 3000, 3_885_000 + 3000, "enforce")))
        self.assertIn("2700 Hz", check(self.p, "am", 3_675_000 - 3000, 3_675_000 + 3000).warning)

    def test_ibp_slot_is_refused(self):
        # §4.1 17 m: "18109 | 18111 | 200 | (none) | beacon | IBP (exclusive)"
        self.assertTrue(check(self.p, "cw", 18_110_000, 18_110_100, "off").refused)

    def test_10m_beacon_segment_is_refused_whole(self):
        # §4.1 10 m: "28190 | 28225 | 200 | (none) | beacon | 'Beacons, IBP
        # (exclusive) 28199-28201 kHz'"
        self.assertTrue(check(self.p, "cw", 28_195_000, 28_195_100, "off").refused)
        self.assertTrue(check(self.p, "cw", 28_220_000, 28_220_100, "off").refused)

    def test_10m_satellites_are_exclusive(self):
        # §6 point 5: "R2 | 29300-29510 kHz" in the satellite-only table.
        self.assertTrue(check(self.p, "usb", 29_400_300, 29_402_700, "off").refused)

    def test_6m_cw_and_beacons_stays_open_to_cw(self):
        # §4.2: "50.000 | 50.100 | 500 Hz | cw | beacon (shared)"; §6 point 4
        # "R2 50.000-50.100 is also the R2 CW segment, so it must not be refused".
        self.assertTrue(fine(check(self.p, "cw", 50_050_000, 50_050_100, "enforce", width=100.0)))
        self.assertIn("SSB is not what", check(self.p, "usb", 50_050_300, 50_052_700).warning)

    def test_2m_extents_differ_from_r1(self):
        # §4.3: "147.590 | 148.000 | 12 kHz | fm, dv | output"; R1's 2 m is
        # 144-146 (§0, "2 m | 144-146 | 144-148 | 144-148").
        self.assertIsNotNone(self.p.segment_at(147_800_000))
        self.assertIsNone(iaru_r1.segment_at(147_000_000))
        self.assertEqual(max(s.hi for s in iaru_r1.SEGMENTS if 144e6 <= s.lo < 148e6), 146_000_000)
        self.assertEqual(max(s.hi for s in self.p.SEGMENTS if 144e6 <= s.lo < 148e6), 148_000_000)

    def test_2m_fm_calling_is_fine(self):
        # §4.3: "146.390 | 146.600 | 12 kHz | fm, dv | | 146.520 FM calling"
        self.assertTrue(fine(check(self.p, "fm", 146_520_000 - 5500, 146_520_000 + 5500, "enforce",
                                   width=11_000.0)))

    def test_2m_guard_band_and_satellites_refused(self):
        # §4.3: "145.790 | 145.800 | - | (none) | guard | 'Guard band, no
        # transmission allowed'"; "145.800 | 146.000 | ... | 'Satellites (exclusive)'"
        self.assertTrue(check(self.p, "fm", 145_795_000, 145_795_000, "off").refused)
        self.assertTrue(check(self.p, "fm", 145_900_000, 145_900_000, "off").refused)

    def test_aprs_and_radio_astronomy(self):
        self.assertTrue(fine(check(self.p, "fm", 144_384_000, 144_396_000, "enforce")))
        for f in (3_335_000_000, 3_350_000_000):
            self.assertIn("keeps everyone off", check(self.p, "usb", f, f + 2700, "off").refused)

    def test_local_option_is_silent(self):
        # §4.3: "144.500 | 144.600 | - | - | | Local option"
        self.assertIsNone(self.p.segment_at(144_550_000))
        self.assertTrue(fine(check(self.p, "fm", 144_550_000 - 5500, 144_550_000 + 5500, "enforce")))

    def test_420_430_is_left_to_a_national_plan(self):
        # §6 point 1: "Footnote-only bands are offered only when a national
        # plan enables them: ... R2/R3 420-430 and 440-450 MHz."
        self.assertEqual(self.p.overlapping(420_000_000, 430_000_000 - 1), [])
        self.assertEqual(self.p.overlapping(440_000_000 + 1, 450_000_000), [])


class Region3(unittest.TestCase):
    p = iaru_r3

    def test_ibp_guard_is_1_khz_each_side(self):
        # §5.1 20 m: "500 Hz guard band for beacons", width per side not
        # stated; the conservative R1/R2 +-1 kHz is encoded (§5.1, after
        # the table: "protecting +-1 kHz costs nothing").
        self.assertTrue(check(self.p, "cw", 14_100_000, 14_100_100, "off").refused)
        self.assertTrue(check(self.p, "usb", 14_100_300, 14_102_700, "off").refused)
        self.assertTrue(fine(check(self.p, "usb", 14_101_300, 14_103_700, "enforce")))

    def test_radio_astronomy_is_refused(self):
        # §5 9 cm and §6 always-refuse: 3345.8-3352.5 MHz, "no operation".
        v = check(self.p, "usb", 3_350_000_000, 3_350_002_700, "off")
        self.assertIn("keeps everyone off", v.refused)

    def test_ft8_on_its_dial_is_fine(self):
        # §5.1 20 m: "Digital dials: FT8 14074.0"; "14070 | 14110 | 500 |
        # cw, digi | | CW, narrowband".
        self.assertIn((14_074_000, "FT8", "ft8"), self.p.CENTRES)
        self.assertTrue(fine(check(self.p, "ft8", 14_074_200, 14_077_000, "enforce", width=50.0)))

    def test_ssb_in_the_cw_segment_warns(self):
        # §5.1 80 m: "3510 | 3535 | 200 | cw | | CW"
        self.assertIn("SSB is not what", check(self.p, "lsb", 3_520_300, 3_522_700).warning)

    def test_30m_starts_at_10110_as_printed(self):
        # §5.1 30 m: "10110 | 10130 | 200 | cw | | CW (lower edge 10110 as
        # printed; ... 10100-10110 is unplanned)"
        self.assertIsNone(self.p.segment_at(10_105_000))
        self.assertEqual(self.p.segment_at(10_115_000).modes, base.CW)

    def test_40m_ends_at_7200(self):
        # §5.1 40 m: "7200-7300: P1 states that this range 'is not allocated
        # to the amateur service in Region 3'".
        self.assertIsNone(self.p.segment_at(7_250_000))

    def test_80m_ends_at_3900(self):
        # §5.1 80 m: "The R3 allocation ends at 3900."
        self.assertIsNotNone(self.p.segment_at(3_850_000))
        self.assertIsNone(self.p.segment_at(3_950_000))

    def test_2m_is_all_modes_without_repeater_segments(self):
        # §5.3: "144.035 | 145.800 | 25 kHz | all | | All modes"; R1 keeps
        # 144.150-144.400 for CW, SSB and MGM (§3.4).
        self.assertTrue(fine(check(self.p, "fm", 144_300_000 - 5500, 144_300_000 + 5500, "enforce")))
        self.assertIn("FM is not what", check(iaru_r1, "fm", 144_300_000 - 5500, 144_300_000 + 5500).warning)

    def test_satellites_refused(self):
        # §5.4: "435.000 | 438.000 | - | all | satellite | 'Satellites - All
        # modes'"; §5.1 10 m "29300 | 29510 | ... | satellite"
        self.assertTrue(check(self.p, "fm", 436_000_000, 436_000_000, "off").refused)
        self.assertTrue(check(self.p, "usb", 29_400_300, 29_402_700, "off").refused)

    def test_6m_has_no_bandwidth_limit_above_50_5(self):
        # §5.2: "50.500 | 54.000 | none | all, incl. WB | | ... bandwidth limit
        # was removed at the 19th Conference (Nov 2024)"
        self.assertTrue(fine(check(self.p, "fm", 51_000_000 - 8000, 51_000_000 + 8000, "enforce")))

    def test_6m_beacons_refused_inside_the_cw_segment(self):
        # §5.2: "50.000 | 50.100 | 200 Hz | cw | | CW. International beacons
        # at 50.020-50.080 (kind beacon for that sub-range)"
        self.assertTrue(check(self.p, "cw", 50_050_000, 50_050_100, "off").refused)
        self.assertTrue(fine(check(self.p, "cw", 50_090_000, 50_090_100, "enforce", width=100.0)))


class Choose(unittest.TestCase):
    def test_explicit_setting_wins(self):
        self.assertEqual(plans.choose("iaru-r2", country_plan=rsgb_2026.ID, region=1), "iaru-r2")

    def test_country_plan_next(self):
        self.assertEqual(plans.choose(plans.AUTO, country_plan=rsgb_2026.ID, region=3), rsgb_2026.ID)

    def test_regime_plan_next(self):
        self.assertEqual(plans.choose(plans.AUTO, "", rsgb_2026.ID, 2), rsgb_2026.ID)

    def test_region_plan_next(self):
        for n, plan in zip((1, 2, 3), REGIONAL):
            self.assertEqual(plans.choose(plans.AUTO, region=n), plan.ID)

    def test_unknown_region_gets_region_1(self):
        self.assertEqual(plans.choose(plans.AUTO), iaru_r1.ID)
        self.assertEqual(plans.choose(plans.AUTO, region=None), iaru_r1.ID)
        self.assertEqual(plans.choose("", region=7), iaru_r1.ID)

    def test_a_setting_this_version_lacks_falls_through(self):
        self.assertEqual(plans.choose("iaru-r9-2031", region=2), iaru_r2.ID)


if __name__ == "__main__":
    unittest.main()
