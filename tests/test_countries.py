"""Where the station is (ohscore/countries.py): from the callsign by
default, the prefix's country for a call signed abroad, the IARU region
from cty.dat's continent with the Radio Regulations' exceptions, and the
QO-100 footprint."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore import countries, licences


class FromTheCallsign(unittest.TestCase):
    def test_uk_calls_are_ofcom_and_region_1(self):
        for call, where in (("GM4BRI", "Scotland"), ("M0XYZ", "England"), ("2E0ABC", "England"),
                            ("GW4ABC", "Wales"), ("GI4ABC", "Northern Ireland"), ("GD4ABC", "Isle of Man"),
                            ("GJ4ABC", "Jersey"), ("GU4ABC", "Guernsey"), ("GM4BRI/P", "Scotland")):
            s = countries.station(call)
            self.assertEqual((s.entity, s.region, s.regime, s.source), (where, 1, "ofcom-2024", "callsign"), call)
            self.assertEqual(s.country.plan, "rsgb-2026")
            self.assertFalse(s.visiting)

    def test_a_prefix_moves_the_station(self):
        s = countries.station("EA8/GM4BRI/P")
        self.assertEqual((s.entity, s.region, s.regime), ("Canary Islands", 1, "setid-2026"))
        self.assertEqual(s.home_entity, "Scotland")
        self.assertEqual(s.home_country.iso, "GB")
        self.assertTrue(s.visiting)
        self.assertEqual(countries.station("G4ABC/EA8").entity, "Canary Islands")
        self.assertEqual(countries.station("VE3/W1AW").entity, "Canada")

    def test_at_sea_is_no_country(self):
        s = countries.station("GM4BRI/MM")
        self.assertTrue(s.at_sea)
        self.assertEqual((s.entity, s.regime), ("", ""))
        self.assertEqual(s.home_entity, "Scotland")

    def test_nothing_known(self):
        for call in ("", "NOCALL", "IO86"):
            s = countries.station(call)
            self.assertEqual((s.entity, s.region, s.source), ("", None, ""), call)

    def test_the_setting_wins(self):
        s = countries.station("GM4BRI", override="EA8")
        self.assertEqual((s.entity, s.source, s.regime), ("Canary Islands", "setting", "setid-2026"))
        self.assertEqual(countries.station("", override="GM").regime, "ofcom-2024")
        self.assertIn("not in this cty.dat", countries.station("GM4BRI", override="QQ9").notes[0])

    def test_the_choices_are_every_entity(self):
        ents = dict(countries.entities())
        self.assertEqual(ents["GM"], "Scotland")
        self.assertEqual(ents["K"], "United States")
        self.assertGreater(len(ents), 300)


class WrittenCountries(unittest.TestCase):
    """The fifteen countries researched on 08/10/2026 (docs/ham/countries/)."""

    CALLS = {"EI2ABC": "comreg-2023", "DL1ABC": "bnetza-2024", "PA3ABC": "rdi-2024", "ON4ABC": "bipt-2019",
             "F4ABC": "arcep-2019", "TK5ABC": "arcep-2019", "EA4ABC": "setid-2026", "EA6ABC": "setid-2026",
             "I1ABC": "mimit-2022", "IT9ABC": "mimit-2022", "LA1ABC": "nkom-2026", "SM5ABC": "pts-2025",
             "OZ1ABC": "digst-2026", "OH2ABC": "traficom-2026", "OH0ABC": "traficom-2026", "W1AW": "fcc-2026",
             "KL7ABC": "fcc-2026", "KH6ABC": "fcc-2026", "VE3ABC": "ised-2022", "VK2ABC": "acma-2023",
             "ZL1ABC": "rsm-2025", "ZL7ABC": "rsm-2025"}

    def test_each_call_finds_its_licence(self):
        for call, rid in self.CALLS.items():
            inf = countries.in_force({"callsign": call})
            self.assertEqual((inf.regime_id, inf.why_none), (rid, ""), call)

    def test_entities_the_research_did_not_cover_stay_unwritten(self):
        # The Faroes and Greenland have their own rules; Svalbard's 2-32 GHz
        # exclusion was not encoded; Guam is Region 3 and US territories
        # there are not mapped yet.
        for call in ("OY1ABC", "OX3ABC", "JW1ABC", "KH2ABC", "FG5ABC"):
            self.assertEqual(countries.station(call).regime, "", call)

    def test_the_tables_agree(self):
        for c in countries.WRITTEN:
            for rid in c.regimes:
                lic = licences.get(rid)
                self.assertIsNotNone(lic, rid)
                self.assertIn(c.iso, lic.COUNTRY, rid)
        self.assertEqual({r for c in countries.WRITTEN for r in c.regimes}, set(licences.REGIMES))

    def test_region_comes_with_the_country(self):
        for call, region in (("W1AW", 2), ("KH6ABC", 2), ("VE3ABC", 2), ("VK2ABC", 3), ("ZL1ABC", 3),
                             ("FR5ABC", 1), ("EA8ABC", 1)):
            self.assertEqual(countries.station(call).region, region, call)


class Regions(unittest.TestCase):
    def test_continents_and_their_exceptions(self):
        for call, region in (("DL1ABC", 1), ("ZS1ABC", 1), ("W1AW", 2), ("PY1ABC", 2), ("OX3ABC", 2),
                             ("VK2ABC", 3), ("JA1ABC", 3), ("VU2ABC", 3), ("ZL1ABC", 3),
                             # Asia in Region 1: the Middle East west of line A, the former USSR, Mongolia.
                             ("4X1AB", 1), ("HZ1AB", 1), ("A61AB", 1), ("UA9ABC", 1), ("UN7ABC", 1), ("JT1AB", 1),
                             ("TA2ABC", 1), ("5B4AB", 1),
                             # ...and Iran east of it, in Region 3.
                             ("EP2ABC", 3),
                             # Hawaii is Region 2; Guam Region 3.
                             ("KH6ABC", 2), ("KH2ABC", 3),
                             # An African island east of 60°E.
                             ("3B9ABC", 3)):
            self.assertEqual(countries.station(call).region, region, call)


class LicenceInForce(unittest.TestCase):
    """countries.in_force: which licence the transmit guard applies, or
    the sentence that keeps transmit locked."""

    def test_a_uk_call_gets_ofcom(self):
        inf = countries.in_force({"callsign": "GM4BRI", "licenceClass": "full"})
        self.assertIs(inf.regime, licences.ofcom)
        self.assertEqual((inf.regime_id, inf.cls, inf.why_none), ("ofcom-2024", "full", ""))
        info = inf.info()
        self.assertEqual((info["iso"], info["region"], info["regime"]), ("GB", 1, "ofcom-2024"))
        self.assertEqual(info["conditions"][0]["key"], "nearLondon")

    def test_nothing_known_or_at_sea_locks_transmit(self):
        self.assertEqual(countries.in_force({}).why_none, countries.NO_COUNTRY)
        self.assertEqual(countries.in_force({"callsign": "GM4BRI/MM"}).why_none, countries.AT_SEA)

    def test_a_country_not_written_says_so_and_how_to_unlock(self):
        inf = countries.in_force({"callsign": "ZS1ABC"})
        self.assertIsNone(inf.regime)
        self.assertEqual(inf.why_none, countries.NO_REGIME_IN.format(country="South Africa"))

    def test_abroad_under_cept_the_home_licence_is_mentioned(self):
        inf = countries.in_force({"callsign": "ZS/GM4BRI", "licenceClass": "full"})
        self.assertIsNone(inf.regime)
        self.assertTrue(any("CEPT" in n for n in inf.notes), inf.notes)
        self.assertTrue(any("South Africa's rules apply" in n for n in inf.notes), inf.notes)

    def test_a_chosen_regime_and_the_operators_own(self):
        inf = countries.in_force({"callsign": "ZS1ABC", "licence": "ofcom-2024", "licenceClass": "full"})
        self.assertIs(inf.regime, licences.ofcom)
        self.assertTrue(any("because you chose it" in n for n in inf.notes), inf.notes)
        self.assertEqual(countries.in_force({"licence": "nosuch-1999"}).why_none,
                         countries.UNKNOWN_REGIME.format(regime="nosuch-1999"))
        self.assertEqual(countries.in_force({"licence": "custom"}).why_none, countries.NO_SEGMENTS)
        seg = licences.clean_custom([{"lo": 7.0e6, "hi": 7.2e6, "watts": 100, "unit": "PEP"}])
        inf = countries.in_force({"licence": "custom", "customLicence": seg, "callsign": "ZS1ABC"})
        self.assertEqual((inf.regime.ID, inf.cls), ("custom", "own"))
        self.assertIn("South Africa", inf.regime.TITLE)

    def test_qo100_note(self):
        self.assertEqual(countries.qo100_note({"callsign": "GM4BRI"}), "")
        self.assertIn("below the horizon", countries.qo100_note({"callsign": "W1AW"}))
        self.assertEqual(countries.qo100_note({}), "")


class Qo100(unittest.TestCase):
    def test_elevation(self):
        # Directly below the satellite it is overhead; far west it has set.
        self.assertAlmostEqual(countries.geo_elevation(0.0, 26.0), 90.0, places=3)
        uk = countries.geo_elevation(56.8, -4.2)
        self.assertTrue(15 < uk < 25, uk)
        self.assertLess(countries.geo_elevation(37.6, -91.9), 0)            # the USA
        self.assertLess(countries.geo_elevation(-23.7, 132.3), 0)           # Australia
        self.assertGreater(countries.geo_elevation(22.5, 77.6), 20)         # India

    def test_locator(self):
        lat, lon = countries.locator_position("IO86ha")
        self.assertAlmostEqual(lat, 56.0 + 1 / 48, places=3)
        self.assertAlmostEqual(lon, -4.0 + 7 / 12 + 1 / 24, places=3)
        self.assertEqual(countries.locator_position("IO86"), (56.5, -3.0))
        for bad in ("", "IO8", "ZZ99", "IO86zz"):
            self.assertIsNone(countries.locator_position(bad), bad)


if __name__ == "__main__":
    unittest.main()
