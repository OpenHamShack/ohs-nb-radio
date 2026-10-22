"""Repeater pairs by plan and country (ohsradio/plans/repeaters.py): "auto"
shifts the transmit dial the way the plan or country in force pairs its
repeaters, never the UK's everywhere; a band arrival sets that plan's
usual split; and where nothing is known, auto is simplex."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest
from unittest import mock

from ham_helpers import close, make_radio
from ohsradio import bands
from ohsradio.plans import iaru_r1, iaru_r2, iaru_r3, repeaters, rsgb_2026


class Tables(unittest.TestCase):
    def test_every_plans_schemes_are_sound(self):
        for p in (rsgb_2026, iaru_r1, iaru_r2):
            self.assertEqual(repeaters.validate(p.REPEATERS, p.ID), [], p.ID)
        for iso, entry in repeaters.BY_COUNTRY.items():
            self.assertEqual(repeaters.validate(entry["schemes"], iso), [], iso)
            self.assertTrue(entry.get("src"), iso)

    def test_validation_catches_a_bad_scheme(self):
        bad = [bands.RepeaterScheme("", 145_600_000, 145_700_000, -600_000, 30_000, 0),
               bands.RepeaterScheme("", 145_650_000, 145_800_000, 0.0, 0, 0)]
        problems = " | ".join(repeaters.validate(bad, "toy"))
        for words in ("does not divide", "no shift", "overlap"):
            self.assertIn(words, problems)

    def test_the_direction_is_the_plans(self):
        # 438.700 MHz: an R1 7.6 MHz output (input below); not a UK output.
        self.assertEqual(bands.auto_shift(438_700_000, iaru_r1.REPEATERS), -7_600_000)
        self.assertEqual(bands.auto_shift(438_700_000, rsgb_2026.REPEATERS), 0.0)
        # 433.200 MHz: a UK RB output (input 1.6 MHz up); R1 has no output there.
        self.assertEqual(bands.auto_shift(433_200_000, rsgb_2026.REPEATERS), +1_600_000)
        self.assertEqual(bands.auto_shift(433_200_000, iaru_r1.REPEATERS), 0.0)
        # A range with no channel spacing: anywhere in it.
        self.assertEqual(bands.auto_shift(146_745_000, iaru_r2.REPEATERS), -600_000)
        # R3 prints no repeater pairs at all.
        self.assertEqual(getattr(iaru_r3, "REPEATERS", []), [])

    def test_channel_names_only_where_the_plan_uses_them(self):
        self.assertEqual(bands.channel_name(145_650_000, iaru_r1.REPEATERS, []), "RV52")
        self.assertEqual(bands.channel_name(438_700_000, iaru_r1.REPEATERS, []), "")
        self.assertEqual(bands.channel_name(1_242_050_000, iaru_r1.REPEATERS, []), "RS2")

    def test_a_countrys_pairs_win_over_the_regional_plan(self):
        de_like = {"schemes": [bands.RepeaterScheme("", 438_650_000, 439_425_000, -7_600_000, 25_000, 0)],
                   "offsets": {"70cm": 7_600_000}, "src": "made up"}
        with mock.patch.dict(repeaters.BY_COUNTRY, {"ZZ": de_like}):
            self.assertEqual(repeaters.for_station(iaru_r1, "ZZ")[0], de_like["schemes"])
            # The operator chose a plan: its pairs, not the country's.
            self.assertEqual(repeaters.for_station(iaru_r1, "ZZ", chosen=True)[0], iaru_r1.REPEATERS)
        # A country's own national plan carries its pairs.
        self.assertEqual(repeaters.for_station(rsgb_2026, "GB")[0], rsgb_2026.REPEATERS)


class InTheEngine(unittest.TestCase):
    def test_uk_station_gets_uk_pairs(self):
        r = make_radio(mode="fm", vfo=433_200_000.0)
        self.addCleanup(close, r)
        r.start()
        st = r.state()
        self.assertEqual((st["shift"], st["channel"]), (1_600_000, "RB8"))

    def test_a_region_1_station_with_no_national_plan_gets_r1_pairs(self):
        r = make_radio(callsign="ZS1ABC", mode="fm", vfo=438_700_000.0)
        self.addCleanup(close, r)
        r.start()
        self.assertEqual(r.state()["shift"], -7_600_000)
        # Arriving back in 70 cm from 2 m sets R1's 70 cm split for - and +.
        r.set(vfo=145_500_000.0)
        r.set(vfo=438_700_000.0)
        self.assertEqual(r.state()["rptOffsetHz"], 7_600_000)


if __name__ == "__main__":
    unittest.main()
