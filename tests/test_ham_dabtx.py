"""DAB transmitters (ohsradio/dabtx.py, docs/SERVER-API.md "DAB (Radio)",
"Transmitters heard"): the decoder's TII codes named as sites from
Ofcom's list, with distance and bearing from the station's locator; the
builder on a real extract of Ofcom's file (tests/data/dabtx, its own rows
untouched); the bundled list; and Refresh, from the fixture instead of
the network."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import tempfile
import unittest
from pathlib import Path

from ohsradio import dabtx

FIX = Path(__file__).resolve().parent / "data" / "dabtx"
ASHFORD = "JO01HD"          # 51.146 N 0.625 E: Charing Hill is about 15 km to the north-east


def fixture_list(folder: Path) -> dabtx.Transmitters:
    data = dabtx.build_ofcom((FIX / "txparamsdab.csv").read_bytes(), "2026-10-24")
    dabtx.write_file(folder / dabtx.FILE, data)
    return dabtx.Transmitters(None, bundled=folder)


def meta(eid="CE15", block="12B", tii=((1, 3, -1.0, 1.0),)):
    return {"ensemble": {"id": eid, "label": "BBC National DAB"} if eid else None, "block": block,
            "tii": [{"main": m, "sub": s, "levelDb": l, "confidence": c} for m, s, l, c in tii]}


class Builder(unittest.TestCase):
    def test_ofcoms_hex_codes_and_erp_become_numbers(self):
        data = dabtx.build_ofcom((FIX / "txparamsdab.csv").read_bytes(), "2026-10-24")
        rows = {(r[0], r[5]): dict(zip(dabtx.FIELDS, r)) for r in data["rows"]}
        durris = rows[("C19A", "Durris")]
        # "3E"/"07" in hex, "2.000,000" kW.
        self.assertEqual((durris["main"], durris["sub"], durris["erpKw"], durris["block"]), (62, 7, 2.0, "11C"))
        self.assertEqual(rows[("C181", "Crystal Palace")]["erpKw"], 6.16)
        # Latin-1 in Ofcom's file reads as the letters it is.
        self.assertIn(("C19E", "Fàire Mhòr"), rows)
        # A row with no TII is left out and counted; one with no EId stays.
        self.assertFalse([k for k in rows if "Stewart Park" in k[1]])
        self.assertEqual(data["skipped"], 1)
        self.assertIn((None, "Alton Greenwood Farm"), rows)
        self.assertEqual(data["attribution"]["licence"], "Open Government Licence v3.0")

    def test_the_file_round_trips_and_a_wrong_one_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            data = dabtx.build_ofcom((FIX / "txparamsdab.csv").read_bytes(), "2026-10-24")
            dabtx.write_file(Path(d) / "x.json", data)
            self.assertEqual(dabtx.read_file(Path(d) / "x.json"), data)
            (Path(d) / "y.json").write_text(json.dumps({"schema": 1, "entries": []}))
            with self.assertRaises(ValueError):
                dabtx.read_file(Path(d) / "y.json")


class Naming(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tx = fixture_list(Path(tmp.name))

    def test_a_code_is_its_site_with_distance_bearing_and_erp(self):
        [t] = self.tx.describe(meta(), ASHFORD)
        self.assertEqual((t["site"], t["ensemble"], t["match"], t["erpKw"]), ("Charing Hill", "BBC National DAB", "eid", 2.0))
        self.assertTrue(10 < t["distanceKm"] < 20, t)
        self.assertTrue(20 < t["bearingDeg"] < 70, t)
        self.assertEqual((t["main"], t["sub"], t["levelDb"], t["confidence"]), (1, 3, -1.0, 1.0))

    def test_strongest_first_as_heard_and_an_unknown_code_has_no_site(self):
        out = self.tx.describe(meta(tii=((1, 2, -0.5, 1.0), (1, 3, -9.0, 0.6), (5, 5, -20.0, 0.3))), ASHFORD)
        self.assertEqual([t["site"] for t in out], ["Dover", "Charing Hill", None])
        self.assertIsNone(out[2]["distanceKm"])

    def test_the_block_finds_what_the_ensemble_id_does_not(self):
        # An ensemble whose id Ofcom's sheet does not have (yet): the same
        # code on the same block, nearest the station.
        [t] = self.tx.describe(meta(eid="C0DE", block="12B"), ASHFORD)
        self.assertEqual((t["site"], t["match"]), ("Charing Hill", "block"))
        [t] = self.tx.describe(meta(eid=None, block="8A", tii=((12, 14, 0.0, 1.0),)), ASHFORD)
        self.assertEqual((t["site"], t["match"]), ("Alton Greenwood Farm", "block"))
        [t] = self.tx.describe(meta(eid="C0DE", block="5A"), ASHFORD)
        self.assertIsNone(t["site"])

    def test_without_a_locator_the_site_has_no_distance(self):
        [t] = self.tx.describe(meta(), "")
        self.assertEqual(t["site"], "Charing Hill")
        self.assertIsNone(t["distanceKm"])
        self.assertIsNone(t["bearingDeg"])

    def test_nothing_heard_is_an_empty_list(self):
        self.assertEqual(self.tx.describe({"tii": []}, ASHFORD), [])
        self.assertEqual(self.tx.describe({}, ASHFORD), [])


class Bundled(unittest.TestCase):
    def test_the_release_carries_the_uk_list_and_its_licence(self):
        tx = dabtx.Transmitters(None)
        about = tx.about()
        self.assertEqual(about["source"], "ofcom")
        self.assertGreater(about["transmitters"], 1000)
        self.assertIn("Open Government Licence", about["attribution"]["text"])
        notice = (dabtx.BUNDLED / "ofcom-dab.LICENCE.txt").read_text()
        self.assertIn("Open Government Licence v3.0", notice)
        # Crystal Palace sends 11/1 for Digital One (C181, 11D) and for
        # Sound Digital (C1CE, 11A): the ensemble id tells them apart.
        [bbc] = tx.describe(meta(eid="C181", block="11D", tii=((11, 1, 0.0, 1.0),)), "IO91WK")
        self.assertEqual((bbc["site"], bbc["ensemble"]), ("Crystal Palace", "D1 National"))
        self.assertLess(bbc["distanceKm"], 30)


def ofcom_fetch(calls, fail=False):
    def fetch(url, headers=None, data=None):
        calls.append(url)
        if fail:
            raise OSError("ofcom unreachable")
        assert url == dabtx.OFCOM_URL, url
        return (FIX / "txparamsdab.csv").read_bytes()
    return fetch


class Refresh(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.tx = dabtx.Transmitters(self.data)

    def test_a_fresh_copy_replaces_the_bundled_one(self):
        before = self.tx.about()["transmitters"]
        calls = []
        res = self.tx.refresh(ofcom_fetch(calls), clock=lambda: 1792800000.0)
        self.assertEqual(calls, [dabtx.OFCOM_URL])
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["entries"], 7)
        self.assertEqual(self.tx.about()["transmitters"], 7)
        self.assertNotEqual(before, 7)
        self.assertTrue((self.data / "dabtx" / dabtx.FILE).exists())

    def test_a_failed_refresh_keeps_the_bundled_list(self):
        res = self.tx.refresh(ofcom_fetch([], fail=True))
        self.assertFalse(res["ok"])
        self.assertIn("unreachable", res["why"])
        self.assertGreater(self.tx.about()["transmitters"], 1000)

    def test_an_unreadable_refreshed_copy_is_passed_over(self):
        (self.data / "dabtx").mkdir()
        (self.data / "dabtx" / dabtx.FILE).write_text("{not json")
        self.assertGreater(self.tx.about()["transmitters"], 1000)


if __name__ == "__main__":
    unittest.main()
