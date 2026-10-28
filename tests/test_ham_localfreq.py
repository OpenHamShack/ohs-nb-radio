"""Local frequencies (ohsradio/localfreq.py, docs/SERVER-API.md "Local
frequencies"): what is near the station by distance from its locator,
filtered by radius and category; the NCDXF beacon on each band at a given
UTC; the operator's own list, checked field by field; the bundled files
and the builders that make them; and Refresh, fed from the fixture files
in tests/data/localfreq instead of the network."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import calendar
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from ham_helpers import close, make_radio
from ohsradio import localfreq as lf

FIX = Path(__file__).resolve().parent / "data" / "localfreq"
MODES = ("am", "fm", "usb", "lsb", "cw", "wfm")
GLASGOW = "IO75TU"          # 55.854 N 4.292 W


def utc(s: str) -> float:
    return float(calendar.timegm(tuple(int(x) for x in s.replace("T", "-").replace(":", "-").split("-")) + (0, 0, 0)))


def toy(folder: Path, name: str, entries: list, source: str, **more) -> None:
    data = {"schema": 1, "source": source, "attribution": {"source": source.upper(), "text": f"from {source}",
                                                           "licence": "test", "url": "https://example.org/"},
            "entries": entries, **more}
    lf.write_file(folder / name, data)


class Toys(unittest.TestCase):
    """A bundled folder of tiny sources, so distances are known exactly."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.bundled, self.data = root / "bundled", root / "data"
        self.bundled.mkdir()
        self.data.mkdir()
        # Points due north of 0,0 at known distances (111.195 km a degree).
        toy(self.bundled, "ourairports.json.gz", [
            {"ref": "NEAR", "name": "Near Field", "lat": 0.1, "lon": 0.0, "freqs": [[118_500_000, "TWR"]]},
            {"ref": "MID", "name": "Middle Field", "lat": 0.5, "lon": 0.0, "freqs": [[119_000_000, "APP"]]},
            {"ref": "FAR", "name": "Far Field", "lat": 2.0, "lon": 0.0, "freqs": [[120_000_000, "TWR"]]},
            {"ref": "CTL", "name": "Control", "category": "enroute", "lat": 0.0, "lon": 0.3,
             "freqs": [[126_300_000, "CNTR"]]},
            {"name": "broken", "lat": 0.0, "lon": 0.0},                      # no frequency: skipped
        ], "ourairports", defaults={"category": "airband", "mode": "am", "step": 25000})
        toy(self.bundled, "itu-marine.json", [{"ref": "16", "name": "Marine Ch 16", "freqHz": 156_800_000}],
            "itu-marine", defaults={"category": "marine", "mode": "fm", "step": 25000})
        toy(self.bundled, "hmcg.json", [{"ref": "a", "name": "Coastguard aerial", "lat": -0.2, "lon": 0.0,
                                         "freqHz": 160_825_000}],
            "hmcg", defaults={"category": "marine", "mode": "fm", "step": 25000})
        toy(self.bundled, "channels.json", [{"ref": "pmr1", "category": "pmr", "name": "PMR446 Ch 1",
                                             "freqHz": 446_006_250, "step": 12500}], "channels",
            defaults={"mode": "fm"})
        self.lf = lf.LocalFrequencies(self.data, self.bundled, clock=lambda: utc("2026-10-23T12:00:00"))

    def names(self, out):
        return [e["name"] for e in out["entries"]]

    def test_the_radius_keeps_only_what_is_inside_it(self):
        out = self.lf.listing("JJ00AA", 60)        # JJ00aa's centre: 0.0208 N 0.0417 E
        names = self.names(out)
        self.assertIn("Near Field", names)
        self.assertIn("Middle Field", names)       # 55 km
        self.assertNotIn("Far Field", names)       # 222 km
        self.assertIn("Coastguard aerial", names)  # 25 km south
        self.assertNotIn("broken", names)
        wider = self.names(self.lf.listing("JJ00AA", 300))
        self.assertIn("Far Field", wider)
        self.assertEqual(out["radiusKm"], 60)

    def test_nearest_first_and_tables_after_within_each_category(self):
        out = self.lf.listing("JJ00AA", 300)
        cats = [e["category"] for e in out["entries"]]
        self.assertEqual(cats, sorted(cats, key=lf.CATEGORIES.index))
        air = [e for e in out["entries"] if e["category"] == "airband"]
        self.assertEqual([e["name"] for e in air], ["Near Field", "Middle Field", "Far Field"])
        d = [e["distanceKm"] for e in air]
        self.assertEqual(d, sorted(d))
        self.assertAlmostEqual(air[0]["distanceKm"], 9.9, delta=0.1)   # 8.80 km north, 4.63 km west
        self.assertEqual(air[0]["bearingDeg"], 332)            # north-north-west
        marine = [e for e in out["entries"] if e["category"] == "marine"]
        # The positioned aerial first, then the channel table with no distance.
        self.assertEqual([e["name"] for e in marine], ["Coastguard aerial", "Marine Ch 16"])
        self.assertIn("distanceKm", marine[0])
        self.assertNotIn("distanceKm", marine[1])

    def test_category_filter(self):
        out = self.lf.listing("JJ00AA", 300, "enroute")
        self.assertEqual(self.names(out), ["Control"])
        self.assertEqual(out["entries"][0]["mode"], "am")
        self.assertEqual(out["entries"][0]["sub"], "CNTR")
        self.assertEqual(self.names(self.lf.listing("JJ00AA", 300, "pmr")), ["PMR446 Ch 1"])

    def test_entry_shape(self):
        e = next(e for e in self.lf.listing("JJ00AA", 60)["entries"] if e["name"] == "Near Field")
        self.assertEqual(e, {"id": "ourairports:NEAR:118500000", "category": "airband", "name": "Near Field",
                             "sub": "TWR", "freqHz": 118_500_000, "mode": "am", "step": 25000, "source": "ourairports",
                             "distanceKm": e["distanceKm"], "bearingDeg": e["bearingDeg"]})

    def test_attributions_name_only_the_sources_listed(self):
        out = self.lf.listing("JJ00AA", 300, "pmr")
        self.assertEqual([a["source"] for a in out["attributions"]], ["CHANNELS"])
        out = self.lf.listing("JJ00AA", 300)
        self.assertEqual({a["source"] for a in out["attributions"]}, {"OURAIRPORTS", "ITU-MARINE", "HMCG", "CHANNELS"})
        for a in out["attributions"]:
            self.assertEqual(set(a), {"source", "text", "licence", "url"})

    def test_without_a_locator_only_the_tables_and_says_why(self):
        out = self.lf.listing("", 100)
        self.assertEqual(sorted(self.names(out)), ["Marine Ch 16", "PMR446 Ch 1"])
        self.assertIn("locator", out["why"])
        self.assertEqual(out["locator"], "")

    def test_a_malformed_file_is_skipped_not_fatal(self):
        (self.bundled / "channels.json").write_text("{not json")
        out = self.lf.listing("JJ00AA", 60)
        self.assertNotIn("PMR446 Ch 1", self.names(out))
        self.assertIn("Near Field", self.names(out))


class Ncdxf(unittest.TestCase):
    """The beacon on each band at known UTC times, from the bundled table."""

    def setUp(self):
        self.table = lf.read_file(lf.BUNDLED / "ncdxf.json")

    def at(self, s):
        return {f: v["call"] for f, v in lf.ncdxf_now(self.table, utc(s)).items()}

    def test_the_top_of_the_cycle(self):
        self.assertEqual(self.at("2026-10-23T00:00:00"), {"14100000": "4U1UN", "18110000": "YV5B",
                                                          "21150000": "OA4B", "24930000": "LU4AA",
                                                          "28200000": "CS3B"})

    def test_ten_seconds_on_each_beacon_moves_up_a_band(self):
        self.assertEqual(self.at("2026-10-23T00:00:10")["14100000"], "VE8AT")
        self.assertEqual(self.at("2026-10-23T00:00:10")["18110000"], "4U1UN")
        self.assertEqual(self.at("2026-10-23T00:00:19")["18110000"], "4U1UN")
        self.assertEqual(self.at("2026-10-23T00:00:40")["28200000"], "4U1UN")

    def test_later_in_the_day(self):
        # 12:01:30 is 43290 s, 90 s into a cycle: slot 9.
        got = self.at("2026-10-23T12:01:30")
        self.assertEqual(got["14100000"], "4S7B")
        self.assertEqual(got["21150000"], "RR9O")
        # The last slot of a cycle, then the next cycle's first.
        self.assertEqual(self.at("2026-10-23T12:02:59")["14100000"], "YV5B")
        self.assertEqual(self.at("2026-10-23T12:03:00")["14100000"], "4U1UN")

    def test_the_view(self):
        v = lf.ncdxf_view(self.table, utc("2026-10-23T00:00:04"))
        self.assertEqual(v["cycleSeconds"], 180)
        self.assertEqual(len(v["schedule"]), 18)
        self.assertEqual(v["schedule"][0], {"slot": 0, "call": "4U1UN", "location": "United Nations, New York"})
        self.assertEqual(v["nextChangeS"], 6.0)
        self.assertEqual(v["frequencies"], [14_100_000, 18_110_000, 21_150_000, 24_930_000, 28_200_000])


class Mine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / lf.MINE_FILE
        self.store = lf.MineStore(self.path)

    def add(self, **kw):
        body = {"name": "GB3GA", "freqHz": 145_712_500, "mode": "fm", "category": "repeater", **kw}
        return self.store.add(body, MODES)

    def test_add_edit_delete_and_it_is_kept_on_disk(self):
        e = self.add(locator="io75tu", sub="Glasgow 2 m", notes="CTCSS 103.5")
        self.assertEqual(e["locator"], "IO75TU")
        self.assertTrue(e["id"].startswith("m"))
        again = lf.MineStore(self.path).entries()
        self.assertEqual(again, [e])
        ed = self.store.update(e["id"], {"notes": "CTCSS 103.5 Hz"}, MODES)
        self.assertEqual(ed["notes"], "CTCSS 103.5 Hz")
        self.assertEqual(ed["name"], "GB3GA")                    # unchanged fields kept
        self.assertIsNone(self.store.update("nope", {"name": "x"}, MODES))
        self.assertTrue(self.store.delete(e["id"]))
        self.assertFalse(self.store.delete(e["id"]))
        self.assertEqual(lf.MineStore(self.path).entries(), [])

    def test_validation(self):
        bad = [({"name": ""}, "name"), ({"name": "x" * 61}, "name"), ({"name": "a\nb"}, "name"),
               ({"freqHz": "145.7"}, "freqHz"), ({"freqHz": True}, "freqHz"), ({"freqHz": 5}, "freqHz"),
               ({"freqHz": 145_712_500.5}, "freqHz"), ({"mode": "smoke"}, "mode"), ({"locator": "ZZ99"}, "locator"),
               ({"category": "<b>"}, "category"), ({"notes": "n" * 301}, "notes"),
               ({"operator": "Brian"}, "operator"), ({"owner": "x"}, "owner")]
        for change, field in bad:
            with self.subTest(change=change):
                with self.assertRaises(lf.Invalid) as cm:
                    self.add(**change)
                self.assertEqual(cm.exception.field, field)
        self.assertEqual(self.store.entries(), [])

    def test_a_category_is_optional_and_lower_case(self):
        e = self.store.add({"name": "Net", "freqHz": 3_700_000, "mode": "LSB"}, MODES)
        self.assertEqual((e["category"], e["mode"]), ("other", "lsb"))
        self.assertEqual(self.add(category="Club Net")["category"], "club net")

    def test_listed_under_mine_whatever_the_radius(self):
        folder = self.path.parent
        lfq = lf.LocalFrequencies(folder, folder / "none")
        self.add(locator="IO91WM", sub="far away")
        self.add(name="Simplex", freqHz=145_500_000)
        out = lfq.listing(GLASGOW, 50)
        mine = [e for e in out["entries"] if e["category"] == "mine"]
        self.assertEqual([e["name"] for e in mine], ["GB3GA", "Simplex"])     # positioned first
        self.assertGreater(mine[0]["distanceKm"], 500)
        self.assertEqual(mine[0]["source"], "mine")
        self.assertEqual(mine[0]["userCategory"], "repeater")
        self.assertNotIn("distanceKm", mine[1])
        self.assertEqual([e["name"] for e in lfq.listing(GLASGOW, 50, "mine")["entries"]], ["GB3GA", "Simplex"])
        self.assertEqual(lfq.listing(GLASGOW, 50, "pmr")["entries"], [])


class DialLabel(unittest.TestCase):
    """What the dial is on (LocalFrequencies.dial_label, docs/SERVER-API.md
    "The dial label"), over Toys' tiny sources and the operator's own
    entries. Station JJ00AA, 2.3 km from the equator and the meridian."""

    HERE = "JJ00AA"

    def setUp(self):
        Toys.setUp(self)
        # An 8.33 kHz channel and its neighbour, so a step tighter than the
        # bandwidth is exercised; Near Field is 10 km away, Far Field 220.
        toy(self.bundled, "ourairports.json.gz", [
            {"ref": "NEAR", "name": "Near Field", "lat": 0.1, "lon": 0.0,
             "freqs": [[118_500_000, "TWR", 8333], [118_508_333, "GND", 8333]]},
            {"ref": "FAR", "name": "Far Field", "lat": 2.0, "lon": 0.0, "freqs": [[120_000_000, "TWR"]]},
        ], "ourairports", defaults={"category": "airband", "mode": "am", "step": 25000})

    def label(self, hz, mode="fm", bw=12_500, loc=HERE, radius=100):
        return self.lf.dial_label(hz, mode, bw, loc, radius)

    def mine(self, **kw):
        return self.lf.mine.add({"mode": "fm", **kw}, MODES)

    def test_an_exact_match_says_what_the_entry_holds(self):
        got = self.label(118_500_000, "am", 8_000)
        self.assertEqual((got["kind"], got["name"], got["sub"], got["source"]), ("airband", "Near Field", "TWR",
                                                                                 "ourairports"))
        self.assertEqual(got["text"], "Near Field · TWR · AM")
        self.assertEqual(got["id"], "ourairports:NEAR:118500000")
        self.assertEqual((got["distanceKm"], got["bearingDeg"]), (9.9, 332))
        # Nothing a bundled entry does not hold is made up.
        for k in ("callsign", "place", "cc", "ctcss", "network", "rxOffsetHz"):
            self.assertIsNone(got[k], k)

    def test_within_the_bandwidth_or_the_step_whichever_is_tighter(self):
        # AM's 8 kHz: 4 kHz either side, inside the 8.33 kHz step.
        self.assertEqual(self.label(118_503_900, "am", 8_000)["sub"], "TWR")
        self.assertIsNone(self.label(118_504_100, "am", 8_000))
        # The neighbouring channel is nearer: it, not the one below.
        self.assertEqual(self.label(118_506_000, "am", 8_000)["sub"], "GND")
        # Wide FM's 180 kHz would reach a channel 12 kHz away; PMR446's
        # 12.5 kHz step keeps the label to the channel it is on.
        self.assertEqual(self.label(446_006_250 + 12_000, "wfm", 180_000)["name"], "PMR446 Ch 1")
        self.assertIsNone(self.label(446_006_250 + 13_000, "wfm", 180_000))
        # A narrow CW filter names only what it is on.
        self.assertIsNone(self.label(118_500_400, "cw", 500))

    def test_nothing_near_is_null(self):
        self.assertIsNone(self.label(145_000_000))
        # No bandwidth: only an exact dial.
        self.assertIsNotNone(self.label(118_500_000, "am", 0))
        self.assertIsNone(self.label(118_500_001, "am", 0))

    def test_a_positioned_entry_counts_only_within_the_radius(self):
        self.assertIsNone(self.label(120_000_000, "am", 8_000, radius=100))
        self.assertEqual(self.label(120_000_000, "am", 8_000, radius=300)["name"], "Far Field")

    def test_without_a_locator_the_tables_and_mine_still_answer(self):
        self.assertIsNone(self.label(118_500_000, "am", 8_000, loc=""))
        self.assertEqual(self.label(446_006_250, loc="")["name"], "PMR446 Ch 1")
        self.mine(name="Hilltop", freqHz=145_600_000, category="repeater", locator="JJ00AB")
        got = self.label(145_600_000, loc="")
        self.assertEqual(got["name"], "Hilltop")
        self.assertIsNone(got["distanceKm"])

    def test_offline_with_no_data_at_all(self):
        empty = Path(self.data) / "nothing-bundled"
        bare = lf.LocalFrequencies(self.data / "bare", empty)
        self.assertIsNone(bare.dial_label(446_006_250, "fm", 12_500, ""))
        self.assertIsNone(bare.dial_label(446_006_250, "fm", 12_500, self.HERE))
        # A broken list of the operator's own is no list, not an error.
        (self.data / "bare").mkdir()
        (self.data / "bare" / lf.MINE_FILE).write_text("{not json", encoding="utf-8")
        self.assertIsNone(bare.dial_label(446_006_250, "fm", 12_500, self.HERE))

    def test_the_operators_own_first_a_repeater_before_the_rest(self):
        self.assertEqual(self.label(446_006_250)["kind"], "pmr")
        # The operator's entry wins though the bundled channel is nearer.
        self.mine(name="Club Net", freqHz=446_010_000, category="net", sub="Tuesdays")
        got = self.label(446_006_250)
        self.assertEqual((got["kind"], got["name"], got["source"]), ("mine", "Club Net", "mine"))
        self.assertEqual(got["text"], "Club Net · Tuesdays · FM")
        self.assertIsNone(got["callsign"])
        # A repeater of theirs wins over another of theirs, nearer or not.
        self.mine(name="Repeater One", freqHz=446_000_000, category="repeater")
        self.assertEqual(self.label(446_006_250)["name"], "Repeater One")
        # Inside one rank the nearest in frequency.
        self.mine(name="Repeater Two", freqHz=446_005_000, category="repeater")
        self.assertEqual(self.label(446_006_250)["name"], "Repeater Two")
        self.assertEqual(self.label(446_001_000)["name"], "Repeater One")

    def test_a_repeater_label_and_its_input(self):
        e = self.mine(name="Repeater One", freqHz=145_712_500, category="repeater", sub="Hilltop",
                      locator="JJ00AB", notes="CTCSS 103.5 CC1")
        got = self.label(145_712_500)
        self.assertEqual((got["kind"], got["callsign"], got["place"], got["mode"]),
                         ("repeater", "Repeater One", "Hilltop", "fm"))
        self.assertEqual(got["text"], "Repeater One · Hilltop · FM")
        self.assertEqual(got["id"], f"mine:{e['id']}")
        # The UK's 2 m pairs: it listens 600 kHz below.
        self.assertEqual(got["rxOffsetHz"], -600_000)
        self.assertIsNotNone(got["distanceKm"])
        # Notes are free text: no tone or colour code is read out of them.
        self.assertEqual((got["ctcss"], got["cc"], got["network"]), (None, None, None))
        # Off the repeater pairs (a 2 m simplex frequency), no input known.
        self.mine(name="Odd One", freqHz=145_500_000, category="repeater")
        self.assertIsNone(self.label(145_500_000)["rxOffsetHz"])
        # The plan in force's pairs when given: none here.
        self.assertIsNone(self.lf.dial_label(145_712_500, "fm", 12_500, self.HERE, 100, [])["rxOffsetHz"])
        # Only a repeater has an input.
        self.mine(name="Calling", freqHz=433_500_000, category="simplex")
        self.assertIsNone(self.label(433_500_000)["rxOffsetHz"])

    def test_an_edit_is_seen_at_once_and_says_so(self):
        told = []
        self.lf.mine.on_change = lambda: told.append(1)
        e = self.mine(name="Repeater One", freqHz=145_712_500, category="repeater")
        self.assertEqual(self.label(145_712_500)["name"], "Repeater One")
        self.lf.mine.update(e["id"], {"name": "Repeater Renamed"}, MODES)
        self.assertEqual(self.label(145_712_500)["name"], "Repeater Renamed")
        self.lf.mine.delete(e["id"])
        self.assertIsNone(self.label(145_712_500))
        self.assertEqual(len(told), 3)
        # Written by something else (a restore): read again by its stamp.
        other = lf.MineStore(self.lf.mine.path)
        other.add({"name": "Restored", "freqHz": 145_712_500, "mode": "fm"}, MODES)
        self.assertEqual(self.label(145_712_500)["name"], "Restored")


class Builders(unittest.TestCase):
    def test_833_channel_names_become_frequencies(self):
        self.assertEqual(lf.eight33(118.005), (118_000_000, 8333))
        self.assertEqual(lf.eight33(118.010), (118_008_333, 8333))
        self.assertEqual(lf.eight33(118.015), (118_016_667, 8333))
        self.assertEqual(lf.eight33(132.155), (132_150_000, 8333))
        self.assertEqual(lf.eight33(118.800), (118_800_000, 25000))
        self.assertEqual(lf.eight33(122.725), (122_725_000, 25000))
        self.assertEqual(lf.eight33(118.00833), (118_008_330, 8333))   # published as a frequency

    def test_marine_tag_values(self):
        self.assertEqual(lf.parse_vhf("12;16"), [(156_600_000, "Ch 12"), (156_800_000, "Ch 16")])
        self.assertEqual([h for h, _n in lf.parse_vhf("VHF 72/16")], [156_625_000, 156_800_000])
        self.assertEqual(lf.parse_vhf("74 (Humber Cruising)"), [(156_725_000, "Ch 74")])
        self.assertEqual(lf.parse_vhf("Ch 09"), [(156_450_000, "Ch 09")])
        # Duplex: the coast station's side; M is the UK marinas' channel.
        self.assertEqual(lf.parse_vhf("80"), [(161_625_000, "Ch 80")])
        self.assertEqual(lf.parse_vhf("M"), [(157_850_000, "Ch M")])
        self.assertEqual(lf.parse_vhf("156.800"), [(156_800_000, "")])
        for junk in ("126.7", "none", "*", "99", "135.480"):
            self.assertEqual(lf.parse_vhf(junk), [], junk)

    def test_ourairports(self):
        data = lf.build_ourairports((FIX / "airports.csv").read_text(), (FIX / "airport-frequencies.csv").read_text(),
                                    "2026-10-23")
        rows = lf.expand(data)
        refs = {r["ref"] for r in rows}
        self.assertEqual(refs, {"EGPF", "EGPK", "EGLL"})              # the closed field dropped
        egpf = [(r["category"], r["freqHz"], r["sub"]) for r in rows if r["ref"] == "EGPF"]
        self.assertIn(("airband", 118_800_000, "TWR Glasgow Tower"), egpf)
        self.assertIn(("enroute", 126_300_000, "CNTR SCOTTISH CONTROL"), egpf)
        self.assertEqual(len([e for e in egpf if e[1] == 118_800_000]), 1)  # the duplicate row once
        self.assertFalse([e for e in egpf if e[1] < 100_000_000])          # HF dropped
        tower = next(r for r in rows if r["freqHz"] == 118_800_000)
        self.assertEqual((tower["mode"], tower["step"]), ("am", 8333))
        self.assertEqual(data["attribution"]["licence"], "Public domain")

    def test_osm_marine(self):
        data = lf.build_osm_marine(json.loads((FIX / "overpass.json").read_text()), "2026-10-23", "test")
        rows = lf.expand(data)
        got = {(r["name"], r["freqHz"], r["sub"]) for r in rows}
        self.assertIn(("James Watt Dock Marina", 161_625_000, "marina Ch 80"), got)
        self.assertIn(("James Watt Dock Marina", 157_850_000, "marina Ch M"), got)
        self.assertIn(("Clyde Port Control", 156_600_000, "port operations Ch 12"), got)
        self.assertIn(("Calling-in point", 156_675_000, "calling-in point Ch 73"), got)
        self.assertFalse([r for r in rows if r["name"] == "Preston Airfield"])   # airband, not marine
        self.assertEqual({r["category"] for r in rows}, {"marine"})
        self.assertEqual(data["licence"], "ODbL-1.0")
        self.assertIn("Open Database License", data["attribution"]["text"])

    def test_openaip_and_inside_an_area_is_no_distance(self):
        data = lf.build_openaip(json.loads((FIX / "openaip.json").read_text())["items"], "2026-10-23", "test")
        rows = lf.expand(data)
        self.assertEqual([(r["name"], r["freqHz"], r["sub"]) for r in rows],
                         [("SCOTTISH TMA", 126_300_000, "SCOTTISH CONTROL")])   # UHF guard and the empty area dropped
        here = (55.85, -4.29)
        self.assertEqual(lf.place_of(rows[0], here)[0], 0.0)
        far = lf.place_of(rows[0], (51.5, -0.12))
        self.assertGreater(far[0], 300)
        self.assertEqual(data["attribution"]["text"], "Contains data from openAIP (www.openaip.net), CC BY-NC 4.0")


class Bundled(unittest.TestCase):
    """The files a release carries: each parses, has its attribution and
    licence notice, and lists what it should."""

    def test_every_source_parses_with_its_notice(self):
        for src, spec in lf.SOURCES.items():
            with self.subTest(src=src):
                path = lf.BUNDLED / spec["file"]
                data = lf.read_file(path)
                self.assertEqual(data["source"], src)
                self.assertTrue(data.get("fetched"))
                notice = lf.BUNDLED / (spec["file"].split(".")[0] + ".LICENCE.txt")
                self.assertTrue(notice.read_text().strip())
                if src != "openaip":
                    self.assertTrue(lf.expand(data))

    def test_the_licences_as_shipped(self):
        attr = {s: lf.read_file(lf.BUNDLED / spec["file"])["attribution"] for s, spec in lf.SOURCES.items()}
        self.assertEqual(attr["openaip"]["text"], "Contains data from openAIP (www.openaip.net), CC BY-NC 4.0")
        self.assertEqual(attr["hmcg"]["text"],
                         "Contains public sector information licensed under the Open Government Licence v3.0")
        self.assertEqual(attr["osm-marine"]["text"], "Contains information from OpenStreetMap, which is made "
                                                     "available here under the Open Database License (ODbL)")
        self.assertIn("ODbL", (lf.BUNDLED / "osm-marine.LICENCE.txt").read_text())
        self.assertIn("CC BY-NC 4.0", (lf.BUNDLED / "openaip.LICENCE.txt").read_text())

    def test_the_fixed_tables(self):
        rows = lf.expand(lf.read_file(lf.BUNDLED / "channels.json"))
        by = {}
        for r in rows:
            by.setdefault(r["category"], []).append(r)
        self.assertEqual(len(by["pmr"]), 16)
        self.assertEqual((by["pmr"][0]["freqHz"], by["pmr"][-1]["freqHz"]), (446_006_250, 446_193_750))
        self.assertEqual(len(by["lpd"]), 69)
        self.assertEqual((by["lpd"][0]["freqHz"], by["lpd"][-1]["freqHz"]), (433_075_000, 434_775_000))
        self.assertEqual(len(by["cb"]), 80)
        cept = {r["name"]: r["freqHz"] for r in by["cb"]}
        self.assertEqual(cept["CB (CEPT) Ch 19"], 27_185_000)
        self.assertEqual(cept["CB (CEPT) Ch 23"], 27_255_000)
        self.assertEqual(cept["CB (CEPT) Ch 40"], 27_405_000)
        self.assertEqual(cept["CB (UK 27/81) Ch 40"], 27_991_250)
        marine = {r["name"]: r for r in lf.expand(lf.read_file(lf.BUNDLED / "itu-marine.json"))}
        self.assertEqual(marine["Marine Ch 16"]["freqHz"], 156_800_000)
        self.assertIn("distress", marine["Marine Ch 16"]["sub"])
        self.assertEqual(marine["Marine Ch 70"]["freqHz"], 156_525_000)
        self.assertEqual(marine["Marine Ch 26"]["freqHz"], 161_900_000)   # the coast station's side
        self.assertEqual(marine["Marine AIS 1 (Ch 87B)"]["freqHz"], 161_975_000)

    def test_a_real_station(self):
        # Glasgow: its own airport near, Prestwick's, the Clyde's coastguard.
        out = lf.LocalFrequencies(Path(tempfile.mkdtemp())).listing(GLASGOW, 100)
        names = {e["name"] for e in out["entries"]}
        self.assertIn("Glasgow Airport", names)
        self.assertIn("Glasgow Prestwick Airport", names)
        self.assertTrue([n for n in names if n.startswith("Belfast Coastguard")])
        self.assertIsNotNone(out["ncdxf"])


def fixture_fetch(calls, fail=()):
    """The network as Refresh sees it, answered from tests/data/localfreq."""
    def fetch(url, headers=None, data=None):
        calls.append((url, dict(headers or {}), data))
        for part in fail:
            if part in url:
                raise OSError(f"{part} unreachable")
        if url.endswith("airports.csv"):
            return (FIX / "airports.csv").read_bytes()
        if url.endswith("airport-frequencies.csv"):
            return (FIX / "airport-frequencies.csv").read_bytes()
        if "overpass" in url:
            return (FIX / "overpass.json").read_bytes()
        if "openaip" in url:
            return (FIX / "openaip.json").read_bytes()
        if "ofcom" in url:
            # Radio's refresh brings the DAB transmitter list too (dabtx.py).
            return (FIX.parent / "dabtx" / "txparamsdab.csv").read_bytes()
        raise AssertionError(url)
    return fetch


class Refresh(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.lf = lf.LocalFrequencies(self.data)

    def test_refresh_writes_beside_the_bundled_copy(self):
        calls = []
        ans = self.lf.refresh(fixture_fetch(calls), GLASGOW, 100, "secret-key")
        res = {r["source"]: r for r in ans["results"]}
        self.assertTrue(all(r["ok"] for r in res.values()), res)
        self.assertEqual(res["ourairports"]["entries"], 5)
        for spec in ("ourairports.json.gz", "osm-marine.json", "openaip.json"):
            self.assertTrue((self.data / "localfreq" / spec).exists(), spec)
        names = {e["name"] for e in self.lf.listing(GLASGOW, 100)["entries"]}
        # OurAirports replaced whole: the fixture has two Glasgow fields
        # and no Edinburgh, which the bundled copy has.
        self.assertIn("Glasgow Airport", names)
        self.assertNotIn("Edinburgh Airport", names)
        # OpenStreetMap merged with the bundled area, openAIP filled.
        self.assertIn("James Watt Dock Marina", names)
        self.assertIn("SCOTTISH TMA", names)
        # The key went in its header, never the URL; Overpass got a query around the station.
        oa = [c for c in calls if "openaip" in c[0]]
        self.assertTrue(oa and all(c[1]["x-openaip-api-key"] == "secret-key" and "secret" not in c[0] for c in oa))
        q = next(c for c in calls if "overpass" in c[0])[2].decode()
        self.assertIn("around%3A100000%2C55.85", q)

    def test_no_key_skips_openaip_and_a_failure_stays_alone(self):
        calls = []
        ans = self.lf.refresh(fixture_fetch(calls, fail=("overpass",)), GLASGOW, 50, "")
        res = {r["source"]: r for r in ans["results"]}
        self.assertTrue(res["ourairports"]["ok"])
        self.assertFalse(res["osm-marine"]["ok"])
        self.assertIn("unreachable", res["osm-marine"]["why"])
        self.assertFalse(res["openaip"]["ok"])
        self.assertIn("key", res["openaip"]["why"])
        self.assertFalse([c for c in calls if "openaip" in c[0]])
        # The bundled marine extract is still listed.
        self.assertTrue([e for e in self.lf.listing(GLASGOW, 50, "marine")["entries"] if e["source"] == "osm-marine"])

    def test_a_broken_refreshed_copy_falls_back_to_the_bundled_one(self):
        (self.data / "localfreq").mkdir()
        (self.data / "localfreq" / "ourairports.json.gz").write_bytes(gzip.compress(b"{}"))
        names = {e["name"] for e in self.lf.listing(GLASGOW, 100, "airband")["entries"]}
        self.assertIn("Edinburgh Airport", names)

    def test_no_locator_fetches_nothing_around(self):
        calls = []
        ans = self.lf.refresh(fixture_fetch(calls), "", 100, "k")
        res = {r["source"]: r for r in ans["results"]}
        self.assertTrue(res["ourairports"]["ok"])
        self.assertFalse(res["osm-marine"]["ok"] or res["openaip"]["ok"])
        self.assertFalse([c for c in calls if "overpass" in c[0] or "openaip" in c[0]])

    def test_one_refresh_at_a_time(self):
        self.lf.refreshing.acquire()
        try:
            with self.assertRaises(RuntimeError):
                self.lf.refresh(fixture_fetch([]), GLASGOW, 100, "")
        finally:
            self.lf.refreshing.release()


class OnTheRadio(unittest.TestCase):
    """Radio reads the locator and radius from its settings."""

    def test_the_engine_uses_its_locator_and_radius(self):
        r = make_radio(locator="IO75TU", localRadiusKm=30)
        self.addCleanup(close, r)
        out = r.local_frequencies()
        self.assertEqual((out["locator"], out["radiusKm"]), ("IO75TU", 30))
        self.assertTrue(all(e.get("distanceKm", 0) <= 30 for e in out["entries"] if e["category"] != "mine"))
        self.assertEqual(r.local_frequencies(80)["radiusKm"], 80)

    def test_the_dial_label_follows_the_dial(self):
        """dialLabel in the state, as api/state and api/status carry it:
        it appears, changes and goes as the dial crosses an entry's edge
        (the FM passband, 6.25 kHz either side), and an entry added or
        deleted on the dial shows at once, without a turn of it."""
        r = make_radio(locator=GLASGOW)
        self.addCleanup(close, r)
        r.set(vfo=145_712_500, mode="fm")
        self.assertIsNone(r.state()["dialLabel"])
        e = r.localfreq.mine.add({"name": "Repeater One", "freqHz": 145_712_500, "mode": "fm",
                                  "category": "repeater", "sub": "Hilltop"}, MODES)
        got = r.state()["dialLabel"]
        self.assertEqual((got["kind"], got["text"]), ("repeater", "Repeater One · Hilltop · FM"))
        self.assertEqual(got["rxOffsetHz"], -600_000)          # the station country's (UK) 2 m pairs
        r.set(vfo=145_712_500 + 6_000)
        self.assertEqual(r.state()["dialLabel"]["name"], "Repeater One")
        r.set(vfo=145_712_500 + 7_000)
        self.assertIsNone(r.state()["dialLabel"])
        r.localfreq.mine.add({"name": "Repeater Two", "freqHz": 145_725_000, "mode": "fm",
                              "category": "repeater"}, MODES)
        self.assertEqual(r.state()["dialLabel"]["name"], "Repeater Two")
        r.set(vfo=145_718_000)
        self.assertEqual(r.state()["dialLabel"]["name"], "Repeater One")    # 5.5 kHz away; Two is 7
        r.localfreq.mine.delete(e["id"])
        self.assertIsNone(r.state()["dialLabel"])
        # A narrower passband narrows the reach: USB's is 300-2700 Hz.
        r.set(vfo=145_725_000 + 1_000, mode="usb")
        self.assertEqual(r.state()["dialLabel"]["name"], "Repeater Two")
        r.set(vfo=145_725_000 + 1_500)
        self.assertIsNone(r.state()["dialLabel"])


if __name__ == "__main__":
    unittest.main()
