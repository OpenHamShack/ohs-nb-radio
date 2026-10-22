"""Licence regimes as data (ohscore/licences/, docs/ham/adding-a-country.md):
every written regime passes the shared validation, the validation catches
what would make the guard give two answers or none, and the guard reads
every optional table a country module may have - checked here with small
made-up regimes, which say nothing about any real country."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import copy
import unittest
from types import SimpleNamespace

from ohscore import licences
from ohscore.licences import ofcom
from ohsradio import guard


def toy(**over):
    """A minimal sound regime: two classes on two made-up bands."""
    base = dict(
        ID="toy-2026", TITLE="Toy licence", SHORT="Toy", AUTHORITY="Toy Authority", COUNTRY=("ZZ",),
        SOURCE={"title": "Toy rules", "url": "https://example.invalid/toy.pdf", "version": "1",
                "date": "2026-01-01", "checked": "2026-10-08"},
        CLASSES=("basic", "advanced"), CLASS_NAME={"basic": "Basic", "advanced": "Advanced"},
        ALLOCATIONS=[(7_000_000.0, 7_200_000.0, {"basic": (10.0, "PEP"), "advanced": (400.0, "PEP")}, "", "p.1"),
                     (2_400_000_000.0, 2_450_000_000.0, {"advanced": (5.0, "EIRP")}, "", "p.2")])
    base.update(over)
    return SimpleNamespace(**base)


class EveryWrittenRegime(unittest.TestCase):
    def test_validates(self):
        for rid, lic in licences.REGIMES.items():
            self.assertEqual(licences.validate(lic), [], rid)
            self.assertEqual(lic.ID, rid)

    def test_class_ids_cover_every_regime(self):
        ids = licences.all_class_ids()
        for lic in licences.REGIMES.values():
            for c in lic.CLASSES:
                self.assertIn(c, ids)

    def test_the_old_import_path_still_works(self):
        from ohsradio.licences import ofcom as old
        self.assertIs(old, ofcom)


class Validation(unittest.TestCase):
    def test_a_sound_toy_passes(self):
        self.assertEqual(licences.validate(toy()), [])

    def problems(self, **over):
        return " | ".join(licences.validate(toy(**over)))

    def test_overlapping_rows_are_two_answers(self):
        rows = toy().ALLOCATIONS + [(7_100_000.0, 7_300_000.0, {"basic": (5.0, "PEP")}, "", "p.3")]
        self.assertIn("overlap", self.problems(ALLOCATIONS=rows))

    def test_units_must_be_declared(self):
        rows = [(7_000_000.0, 7_200_000.0, {"basic": (10.0, "watts")}, "", "p.1")]
        self.assertIn("unit", self.problems(ALLOCATIONS=rows))
        rows = [(7_000_000.0, 7_200_000.0, {"basic": 10.0}, "", "p.1")]
        self.assertIn("(watts, unit)", self.problems(ALLOCATIONS=rows))

    def test_source_and_dates(self):
        self.assertIn("no url", self.problems(SOURCE={**toy().SOURCE, "url": ""}))
        self.assertIn("ISO date", self.problems(SOURCE={**toy().SOURCE, "date": "1 Jan 2026"}))
        rows = [(7_000_000.0, 7_200_000.0, {"basic": (10.0, "PEP")}, "", "")]
        self.assertIn("no source", self.problems(ALLOCATIONS=rows))

    def test_unknown_class_and_empty_row(self):
        rows = [(7_000_000.0, 7_200_000.0, {"expert": (10.0, "PEP")}, "", "p.1")]
        self.assertIn("not one of CLASSES", self.problems(ALLOCATIONS=rows))
        rows = [(7_000_000.0, 7_200_000.0, {}, "", "p.1")]
        self.assertIn("no class may use it", self.problems(ALLOCATIONS=rows))

    def test_refused_inside_an_allocation_contradicts_it(self):
        self.assertIn("refused and allowed", self.problems(REFUSED=[(7_100_000.0, 7_150_000.0, "No.", "p.4")]))

    def test_satellite_outside_the_allocations(self):
        self.assertIn("outside the allocations", self.problems(SATELLITE=[(144e6, 146e6, "both", "p.5")]))
        self.assertIn("direction", self.problems(SATELLITE=[(2400e6, 2450e6, "sideways", "p.5")]))

    def test_channelled_segments_must_lie_inside(self):
        ch = {"lo": 5_250_000.0, "hi": 5_450_000.0, "label": "60 m", "where": "the toy channels",
              "segments": [(5_200_000.0, 5_260_000.0)], "limits": {"advanced": ((15.0, "EIRP"),)},
              "max_bw": 2800.0, "src": "p.6"}
        self.assertIn("not inside", self.problems(CHANNELLED=[ch]))

    def test_emissions_modes_and_cept(self):
        em = [(7_000_000.0, 7_050_000.0, {"basic": frozenset({"morse"})}, None, "", "p.7")]
        self.assertIn("mode classes", self.problems(EMISSIONS=em))
        self.assertIn("recommendation", self.problems(CEPT={"T/R 99": ("advanced",)}, CEPT_SRC="x"))
        self.assertIn("CEPT_SRC", self.problems(CEPT={"T/R 61-01": ("advanced",)}))


class GuardReadsEveryTable(unittest.TestCase):
    def lic(self, cls, lo, hi=None, w=None, regime=None, **kw):
        return guard.licence_check(cls, lo, lo if hi is None else hi, w, lic=regime or toy(), **kw)

    def test_rows_and_units(self):
        self.assertEqual(self.lic("basic", 7_100_000, 7_102_700, 9.0).refused, "")
        self.assertIn("Basic licence: 10 W PEP maximum", self.lic("basic", 7_100_000, 7_102_700, 11.0).warning)
        self.assertIn("Basic licence", self.lic("basic", 2_401_000_000, None, 1.0).refused)
        # 5 W EIRP with a 10 dBi antenna is 0.5 W PEP at the antenna.
        self.assertEqual(self.lic("advanced", 2_401_000_000, None, 0.49, ant_gain_dbi=10.0).refused, "")
        self.assertIn("5.0 W EIRP", self.lic("advanced", 2_401_000_000, None, 0.6, ant_gain_dbi=10.0,
                                             measured=True).refused)

    def test_a_mean_limit_is_judged_on_pep(self):
        r = toy(ALLOCATIONS=[(7_000_000.0, 7_200_000.0, {"basic": (10.0, "mean")}, "", "p.1")])
        self.assertIn("10 W mean maximum", self.lic("basic", 7_100_000, 7_102_700, 11.0, regime=r,
                                                    measured=True).refused)

    def test_emissions(self):
        r = toy(EMISSIONS=[(7_000_000.0, 7_050_000.0, {"basic": frozenset({"cw", "digi"})}, 500.0, "", "p.7")])
        self.assertEqual(self.lic("basic", 7_030_000, 7_030_100, 1.0, regime=r, mode="cw").refused, "")
        self.assertIn("USB is not permitted", self.lic("basic", 7_030_000, 7_032_700, 1.0, regime=r,
                                                      mode="usb").refused)
        self.assertIn("up to 500 Hz", self.lic("basic", 7_030_000, 7_031_000, 1.0, regime=r, mode="cw").refused)
        # The advanced class is not in the row: not restricted by it.
        self.assertEqual(self.lic("advanced", 7_030_000, 7_032_700, 1.0, regime=r, mode="usb").refused, "")

    def test_refused_conditions_and_channels(self):
        r = toy(REFUSED=[(7_200_000.0, 7_300_000.0, "7.2-7.3 MHz needs a special permit.", "p.4")],
                CONDITIONS=[{"key": "nearAirport", "lo": 7_150_000.0, "hi": 7_200_000.0, "label": "Near an airport",
                             "refuse": "Not near the airport.", "src": "p.8"}],
                CHANNELLED=[{"lo": 5_250_000.0, "hi": 5_450_000.0, "label": "60 m", "where": "the toy channels",
                             "segments": [(5_351_500.0, 5_366_500.0)], "limits": {"advanced": ((15.0, "EIRP"),)},
                             "max_bw": 2800.0, "src": "p.6"}])
        self.assertEqual(self.lic("advanced", 7_250_000, None, 1.0, regime=r).refused,
                         "7.2-7.3 MHz needs a special permit.")
        self.assertEqual(self.lic("basic", 7_160_000, None, 1.0, regime=r).refused, "")
        self.assertEqual(self.lic("basic", 7_160_000, None, 1.0, regime=r, conditions={"nearAirport": True}).refused,
                         "Not near the airport.")
        self.assertIn("open only to Advanced", self.lic("basic", 5_360_000, 5_360_050, 1.0, regime=r).refused)
        self.assertIn("one of the toy channels", self.lic("advanced", 5_370_000, 5_370_050, 1.0, regime=r).refused)
        self.assertIn("2.8 kHz", self.lic("advanced", 5_355_000, 5_360_000, 1.0, regime=r).refused)
        self.assertIn("15 W EIRP", self.lic("advanced", 5_360_000, 5_360_050, 20.0, regime=r).warning)

    def test_limits_that_depend_on_the_mode(self):
        # Shaped like Canada's Basic: one figure for SSB-type emissions,
        # another (carrier) for the rest. Made-up numbers.
        Limit = licences.Limit
        lim = (Limit(500.0, "PEP", frozenset({"ssb", "digi"})),
               Limit(150.0, "carrier", frozenset({"cw", "am", "fm", "dv", "image"})))
        r = toy(ALLOCATIONS=[(7_000_000.0, 7_200_000.0, {"basic": lim}, "", "p.1")])
        self.assertEqual(licences.validate(r), [])
        self.assertEqual(self.lic("basic", 7_100_000, 7_102_700, 400.0, regime=r, mode="usb").warning, "")
        self.assertIn("150 W carrier", self.lic("basic", 7_100_000, 7_100_100, 400.0, regime=r, mode="cw").warning)
        # The mode not known: the strictest applies.
        self.assertIn("150 W carrier", self.lic("basic", 7_100_000, 7_102_700, 400.0, regime=r).warning)
        # A mode left without any limit is a data error.
        half = toy(ALLOCATIONS=[(7_000_000.0, 7_200_000.0, {"basic": lim[:1]}, "", "p.1")])
        self.assertIn("no limit", " ".join(licences.validate(half)))

    def test_rows_by_date_region_and_confirmation(self):
        rows = [(3_400_000_000.0, 3_410_000_000.0, {"advanced": (10.0, "PEP")}, "", "p.9",
                 {"valid_from": "2026-07-01", "valid_to": "2027-06-30"}),
                (7_000_000.0, 7_100_000.0, {"basic": (10.0, "PEP")}, "", "p.1", {"regions": (2,)}),
                (7_000_000.0, 7_050_000.0, {"basic": (10.0, "PEP")}, "", "p.1", {"regions": (3,)}),
                (10_100_000.0, 10_150_000.0, {"basic": (10.0, "PEP")}, "", "p.2", {"unconfirmed": True})]
        r = toy(ALLOCATIONS=rows)
        self.assertEqual(licences.validate(r), [])        # region 2 and 3 rows may overlap
        self.assertEqual(self.lic("advanced", 3_405e6, None, 1.0, regime=r, today="2026-10-08").refused, "")
        self.assertTrue(self.lic("advanced", 3_405e6, None, 1.0, regime=r, today="2027-07-01").refused)
        self.assertEqual(self.lic("basic", 7_075_000, None, 1.0, regime=r, region=2).refused, "")
        self.assertTrue(self.lic("basic", 7_075_000, None, 1.0, regime=r, region=3).refused)
        self.assertIn("unconfirmed", self.lic("basic", 10_120_000, None, 1.0, regime=r).refused)
        clash = toy(ALLOCATIONS=rows[1:2] + [(7_000_000.0, 7_050_000.0, {"basic": (10.0, "PEP")}, "", "p.1")])
        self.assertIn("overlap", " ".join(licences.validate(clash)))

    def test_conditions_default_to_their_restrictive_answer(self):
        Limit = licences.Limit
        r = toy(CONDITIONS=[
            {"key": "outsideExclusion", "lo": 2_400_000_000.0, "hi": 2_450_000_000.0, "default": False,
             "when": False, "label": "Station is outside the excluded areas", "refuse": "Excluded area.",
             "src": "p.10"},
            {"key": "nearRadar", "lo": 7_000_000.0, "hi": 7_200_000.0, "default": True,
             "label": "Station is near a radar", "limit": Limit(5.0, "PEP"), "src": "p.11"}])
        self.assertEqual(licences.validate(r), [])
        self.assertEqual(self.lic("advanced", 2_401e6, None, 0.1, regime=r).refused, "Excluded area.")
        self.assertEqual(self.lic("advanced", 2_401e6, None, 0.1, regime=r,
                                  conditions={"outsideExclusion": True}).refused, "")
        v = self.lic("advanced", 7_100_000, 7_102_700, 6.0, regime=r)
        self.assertIn("5.0 W PEP maximum (Station is near a radar)", v.warning)
        self.assertEqual(self.lic("advanced", 7_100_000, 7_102_700, 6.0, regime=r,
                                  conditions={"nearRadar": False}).warning, "")

    def test_no_regime_and_a_class_from_another_regime(self):
        v = guard.licence_check("full", 14_100_000, 14_102_700, None, lic=None, no_regime="Not here.")
        self.assertEqual(v.refused, "Not here.")
        self.assertEqual(guard.licence_check("full", 14_100_000, 14_102_700, None, lic=None).refused,
                         guard.NO_REGIME)
        self.assertIn("different licence than Toy", self.lic("full", 7_100_000).refused)


class TheOperatorsOwnLicence(unittest.TestCase):
    SEGS = [{"lo": 144e6, "hi": 146e6, "watts": 50.0, "unit": "PEP"},
            {"lo": 2400e6, "hi": 2450e6, "watts": 10.0, "unit": "EIRP", "satellite": True, "note": "QO-100"}]

    def test_clean_and_validate(self):
        segs = licences.clean_custom(copy.deepcopy(self.SEGS))
        self.assertEqual(licences.validate(licences.custom(segs), custom_regime=True), [])
        for bad, why in (([{"lo": 146e6, "hi": 144e6, "watts": 5}], "lower edge"),
                         ([{"lo": 144e6, "hi": 146e6, "watts": 0}], "above 0 W"),
                         ([{"lo": 144e6, "hi": 146e6, "watts": 5, "unit": "W"}], "one of PEP"),
                         ([{"lo": 144e6, "hi": 146e6}], "needs a lower edge"),
                         (self.SEGS + [{"lo": 145e6, "hi": 147e6, "watts": 5}], "overlap")):
            with self.assertRaisesRegex(ValueError, why):
                licences.clean_custom(copy.deepcopy(bad))

    def test_the_guard_enforces_it(self):
        own = licences.custom(licences.clean_custom(copy.deepcopy(self.SEGS)), "Spain")
        ok = guard.licence_check(licences.CUSTOM_CLASS, 145_500_000, 145_500_000, 40.0, lic=own)
        self.assertEqual((ok.refused, ok.limit_w), ("", 50.0))
        self.assertIn("Your licence: 50 W PEP maximum",
                      guard.licence_check("own", 145.5e6, 145.5e6, 60.0, lic=own, measured=True).refused)
        self.assertIn("outside every segment of your own licence", guard.licence_check("own", 14.1e6, 14.1e6, 1.0, lic=own).refused)
        allowed, limit, _ = licences.satellite_uplink(own, "own", 2400.05e6, 2400.3e6)
        self.assertEqual((allowed, limit), (True, (10.0, "EIRP")))
        self.assertFalse(licences.satellite_uplink(own, "own", 145.8e6, 145.9e6)[0])


class SatelliteAndCept(unittest.TestCase):
    QO100 = (2_400_050_000.0, 2_400_300_000.0)

    def test_ofcom_qo100_uplink_by_class(self):
        for cls, w in (("foundation", 2.0), ("intermediate", 100.0), ("full", 400.0)):
            allowed, limit, why = licences.satellite_uplink(ofcom, cls, *self.QO100)
            self.assertTrue(allowed, cls)
            self.assertEqual(limit, (w, "PEP"), cls)
        # Earth-to-space only on 1260-1270 MHz, and not for Foundation.
        self.assertTrue(licences.satellite_uplink(ofcom, "full", 1_265e6, 1_266e6)[0])
        self.assertFalse(licences.satellite_uplink(ofcom, "foundation", 1_265e6, 1_266e6)[0])
        # Space to Earth only: no uplink.
        self.assertFalse(licences.satellite_uplink(ofcom, "full", 5_835e6, 5_836e6)[0])

    def test_satellite_only_rows(self):
        rows = [(2_400_000_000.0, 2_450_000_000.0, {"advanced": (5.0, "EIRP")}, "", "p.2",
                 {"satellite_only": True})]
        r = toy(ALLOCATIONS=rows, SATELLITE=[(2_400e6, 2_450e6, "both", "p.2")])
        self.assertEqual(licences.validate(r), [])
        self.assertIn("satellite service only", guard.licence_check("advanced", 2_401e6, 2_401e6, 0.1, lic=r).refused)
        self.assertTrue(licences.satellite_uplink(r, "advanced", *self.QO100)[0])
        self.assertFalse(licences.satellite_uplink(r, "basic", *self.QO100)[0])
        self.assertIn("no SATELLITE entry", " ".join(licences.validate(toy(ALLOCATIONS=rows))))

    def test_a_permit_condition_governs_the_uplink(self):
        # Shaped like Ireland's 13 cm (a separate permit) and Sweden's
        # QO-100 (100 mW without one). Made-up figures.
        Limit = licences.Limit
        sat = [(2_400e6, 2_450e6, "both", "p.2")]
        permit = toy(SATELLITE=sat, CONDITIONS=[
            {"key": "holdsPermit", "lo": 2_400e6, "hi": 2_450e6, "default": False, "when": False,
             "label": "I hold the 13 cm permit", "refuse": "Needs the permit.", "src": "p.3"}])
        self.assertEqual(licences.satellite_uplink(permit, "advanced", *self.QO100), (False, None, "Needs the permit."))
        self.assertTrue(licences.satellite_uplink(permit, "advanced", *self.QO100, {"holdsPermit": True})[0])
        low = toy(SATELLITE=sat, CONDITIONS=[
            {"key": "holdsPermit", "lo": 2_400e6, "hi": 2_450e6, "default": False, "when": False,
             "label": "I hold the permit", "limit": Limit(0.1, "PEP"), "src": "p.3"}])
        allowed, limit, _why = licences.satellite_uplink(low, "advanced", *self.QO100)
        self.assertEqual((allowed, limit), (True, (0.1, "PEP")))

    def test_a_regime_without_a_satellite_table_says_nothing(self):
        allowed, limit, why = licences.satellite_uplink(toy(), "advanced", *self.QO100)
        self.assertIsNone(allowed)
        self.assertIn("says nothing", why)

    def test_cept_sentences(self):
        visited = toy(CEPT_VISITOR={"T/R 61-01": "advanced"})
        self.assertIn("Advanced class", licences.cept_suggestion(ofcom, "full", visited))
        self.assertIn("rules of the country you are in", licences.cept_suggestion(ofcom, "full", toy()))
        self.assertIn("not a CEPT licence", licences.cept_suggestion(ofcom, "foundation", toy()))


if __name__ == "__main__":
    unittest.main()
