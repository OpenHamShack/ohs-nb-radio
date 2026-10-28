"""Radio's store form serving local frequencies (docs/SERVER-API.md "Local
frequencies"): reading at View, the operator's own list at Control,
Refresh only for the controller's administrator, the openAIP key kept out
of api/set and api/state, and NB answering 404. Real HTTP on loopback over
Radio's simulator; Refresh reads tests/data/localfreq, never the network."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import os
import tempfile
import unittest
from unittest import mock

from ohscore.server import shack
from ohscore.server.app import OPENAIP_KEY_ENV, Server
from ohscore.server.audio import StreamAudio
from ohsradio import localfreq as lf
from ohsradio import server as ham_server
from ohsradio.radio import Radio
from test_ham_localfreq import fixture_fetch
from test_server import SECRET

GLASGOW = "IO75TU"


class LocalFrequenciesApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = tmp.name
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "callsign": "GM4BRI",
               "licenceClass": "full", "locator": GLASGOW, "localRadiusKm": 50}
        audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), audio, secret=SECRET)
        self.calls = []
        self.srv.localfreq_fetch = fixture_fetch(self.calls)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)

    def req(self, method, path, body=None, level="view", admin=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
             "X-OpenHamShack-Level": level, "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"}
        if admin:
            h["X-OpenHamShack-Admin"] = "1"
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_the_listing_at_view_level(self):
        s, a = self.req("GET", "/api/local-frequencies")
        self.assertEqual(s, 200, a)
        self.assertEqual((a["locator"], a["radiusKm"]), (GLASGOW, 50))
        self.assertEqual(set(a), {"locator", "radiusKm", "generatedAt", "attributions", "entries", "ncdxf"})
        e = next(e for e in a["entries"] if e["name"] == "Glasgow Airport")
        self.assertEqual(e["category"], "airband")
        self.assertLessEqual(set(e), {"id", "category", "name", "sub", "freqHz", "mode", "step", "distanceKm",
                                      "bearingDeg", "source"})
        self.assertEqual(set(a["ncdxf"]["now"]), {"14100000", "18110000", "21150000", "24930000", "28200000"})
        self.assertTrue(all(set(x) == {"source", "text", "licence", "url"} for x in a["attributions"]))

    def test_radius_and_category_in_the_query(self):
        s, a = self.req("GET", "/api/local-frequencies?radiusKm=150&category=marine")
        self.assertEqual(s, 200, a)
        self.assertEqual(a["radiusKm"], 150)
        self.assertEqual({e["category"] for e in a["entries"]}, {"marine"})
        self.assertTrue(all(e["distanceKm"] <= 150 for e in a["entries"] if "distanceKm" in e))
        for bad, code in (("radiusKm=0", "bad_radius"), ("radiusKm=x", "bad_radius"), ("radiusKm=5000", "bad_radius"),
                          ("category=tv", "bad_category")):
            s, a = self.req("GET", f"/api/local-frequencies?{bad}")
            self.assertEqual((s, a["code"]), (400, code), bad)

    def test_my_frequencies_need_control(self):
        body = {"name": "GB3GA", "freqHz": 145_712_500, "mode": "fm", "category": "repeater", "locator": "IO75TU"}
        s, a = self.req("POST", "/api/local-frequencies/mine", body, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))
        s, e = self.req("POST", "/api/local-frequencies/mine", body, level="control")
        self.assertEqual(s, 201, e)
        s, a = self.req("GET", "/api/local-frequencies?category=mine")
        self.assertEqual([x["id"] for x in a["entries"]], [f"mine:{e['id']}"])
        self.assertEqual(a["entries"][0]["distanceKm"], 0.0)
        s, a = self.req("PUT", f"/api/local-frequencies/mine/{e['id']}", {"sub": "Glasgow"}, level="view")
        self.assertEqual(s, 403)
        s, a = self.req("PUT", f"/api/local-frequencies/mine/{e['id']}", {"sub": "Glasgow"}, level="control")
        self.assertEqual((s, a["sub"], a["name"]), (200, "Glasgow", "GB3GA"))
        s, a = self.req("PUT", "/api/local-frequencies/mine/nope", {"sub": "x"}, level="control")
        self.assertEqual((s, a["code"]), (404, "unknown_entry"))
        s, a = self.req("DELETE", f"/api/local-frequencies/mine/{e['id']}", level="view")
        self.assertEqual(s, 403)
        s, a = self.req("DELETE", f"/api/local-frequencies/mine/{e['id']}", level="control")
        self.assertEqual((s, a), (200, {"deleted": e["id"]}))
        s, a = self.req("DELETE", f"/api/local-frequencies/mine/{e['id']}", level="control")
        self.assertEqual((s, a["code"]), (404, "unknown_entry"))
        # Kept in the data folder, not the settings.
        self.assertTrue(os.path.exists(os.path.join(self.data, "local-frequencies-mine.json")))

    def test_a_bad_field_says_which(self):
        s, a = self.req("POST", "/api/local-frequencies/mine", {"name": "X", "freqHz": 145_500_000, "mode": "fm",
                                                                 "callsignOfOwner": "M0ABC"}, level="control")
        self.assertEqual((s, a["code"], a["field"]), (400, "bad_field", "callsignOfOwner"))
        s, a = self.req("POST", "/api/local-frequencies/mine", {"name": "X", "freqHz": 145_500_000, "mode": "xyz"},
                        level="control")
        self.assertEqual((s, a["field"]), (400, "mode"))

    def test_refresh_is_for_the_administrator(self):
        s, a = self.req("POST", "/api/local-frequencies/refresh", level="view", admin=True)
        self.assertEqual(s, 403)
        s, a = self.req("POST", "/api/local-frequencies/refresh", level="transmit")
        self.assertEqual((s, a["code"]), (403, "not_admin"))
        self.assertEqual(self.calls, [])
        with mock.patch.dict(os.environ, {OPENAIP_KEY_ENV: "module-key"}):
            s, a = self.req("POST", "/api/local-frequencies/refresh", level="control", admin=True)
        self.assertEqual(s, 200, a)
        self.assertEqual({r["source"]: r["ok"] for r in a["results"]},
                         {"ourairports": True, "osm-marine": True, "openaip": True, "ofcom-dab": True})
        self.assertTrue([c for c in self.calls if c[1].get("x-openaip-api-key") == "module-key"])
        self.assertEqual([x["source"] for x in a["sources"]], list(lf.SOURCES))
        s, a = self.req("GET", "/api/local-frequencies?radiusKm=100&category=enroute")
        self.assertIn("SCOTTISH TMA", {e["name"] for e in a["entries"]})

    def test_the_openaip_key_never_goes_through_api_set(self):
        s, a = self.req("POST", "/api/set", {"openAipKey": "x"}, level="transmit")
        self.assertEqual(s, 400)
        self.assertIn("openAipKey", a["error"])
        self.assertEqual(self.radio.state()["openAipKey"], "")
        s, a = self.req("POST", "/api/set", {"localRadiusKm": 75}, level="control")
        self.assertEqual(s, 200, a)
        s, a = self.req("GET", "/api/local-frequencies")
        self.assertEqual(a["radiusKm"], 75)


    def test_the_dial_label_in_state_and_status(self):
        """docs/SERVER-API.md "The dial label": api/state and api/status
        carry dialLabel, null off any entry, and it changes as the dial
        moves onto, along and off one."""
        s, a = self.req("POST", "/api/set", {"changes": {"vfo": 145_712_500, "mode": "fm"}}, level="control")
        self.assertEqual(s, 200, a)
        for path in ("/api/state", "/api/status"):
            s, a = self.req("GET", path)
            self.assertIn("dialLabel", a, path)
            self.assertIsNone(a["dialLabel"], path)
        s, e = self.req("POST", "/api/local-frequencies/mine", {"name": "Repeater One", "freqHz": 145_712_500,
                                                                 "mode": "fm", "category": "repeater"},
                        level="control")
        self.assertEqual(s, 201, e)
        for path in ("/api/state", "/api/status"):
            s, a = self.req("GET", path)
            self.assertEqual(a["dialLabel"]["text"], "Repeater One · FM", path)
            self.assertEqual(a["dialLabel"]["id"], f"mine:{e['id']}", path)
        self.req("POST", "/api/set", {"changes": {"vfo": 145_725_000}}, level="control")
        s, a = self.req("GET", "/api/status")
        self.assertIsNone(a["dialLabel"])
        # Onto a bundled channel: the marine table's calling channel.
        self.req("POST", "/api/set", {"changes": {"vfo": 156_800_000}}, level="control")
        s, a = self.req("GET", "/api/status")
        self.assertEqual((a["dialLabel"]["kind"], a["dialLabel"]["freqHz"]), ("marine", 156_800_000))


class NotOnNb(unittest.TestCase):
    def test_nb_has_none(self):
        from ohsnb import server as nb_server
        from ohsnb.radio import Radio as NbRadio
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        audio = StreamAudio(realtime=False)
        r = NbRadio({"device": "sim", "audioBackend": "null", "simRealtime": False}, persist=False,
                    data_dir=tmp.name, audio=audio)
        srv = Server(r, nb_server.info("9.9.9"), audio, secret=SECRET)
        port = srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(srv.shutdown)
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.request("GET", "/api/local-frequencies", None, {shack.SHACK_SECRET_HEADER: SECRET,
                                                          "X-OpenHamShack-User": "b", "X-OpenHamShack-Level": "view"})
        r2 = c.getresponse()
        self.assertEqual((r2.status, json.loads(r2.read())["code"]), (404, "not_found"))
        c.close()


if __name__ == "__main__":
    unittest.main()
