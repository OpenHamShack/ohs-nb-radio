"""The ship map's map (28/10/2026; ohsradio/mapdata.py): the bundled land,
and OpenStreetMap tiles fetched, cached and served by Radio itself under
the OSM tile policy - checked against a fake tile server, so no test ever
asks the internet.

- **Land:** a box gets the cells it touches, at the level its size asks
  for, as GeoJSON or the compact form; islands and sea where they are.
- **Tiles:** only what is asked for is fetched, with the program's own
  User-Agent; a fresh tile is served from the disk; a stale one is
  revalidated with If-None-Match and If-Modified-Since; offline, a failure
  backs off instead of asking per tile, and a tile is served stale only
  within stale-if-error; the size cap; the setting off means no traffic
  and no tile.
- **Over the API:** api/map/info, api/map/land, api/map/tiles/... (404
  when there is nothing, so the client draws the land), with no absolute
  URL anywhere.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import gzip
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import mapdata
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from test_server import SECRET

PNG = b"\x89PNG\r\n\x1a\n" + b"tile" * 40


class FakeOsm:
    """A tile server that records every request and answers as told."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.down = False
        self.headers = {"cache-control": "max-age=172800, stale-while-revalidate=604800, stale-if-error=604800",
                        "etag": '"abc"', "last-modified": "Tue, 27 Oct 2026 10:00:00 GMT"}

    def __call__(self, url, headers):
        with self.lock:
            self.calls.append((url, dict(headers)))
        if self.down:
            raise OSError("no route to host")
        if headers.get("If-None-Match") == '"abc"':
            return 304, dict(self.headers), b""
        if url.endswith("/0/0/0.png"):
            return 404, {}, b""
        return 200, dict(self.headers), PNG


class Land(unittest.TestCase):
    def setUp(self):
        self.land = mapdata.Land.load()
        self.assertIsNotNone(self.land)

    def test_a_small_box_gets_the_fine_level_and_a_large_one_the_coarse(self):
        clyde = (-5.4, 55.3, -4.5, 55.9)
        g = self.land.geojson(clyde)
        self.assertEqual((g["type"], g["detail"]), ("FeatureCollection", "fine"))
        self.assertEqual(g["attribution"]["text"], "© OpenStreetMap contributors")
        polys = g["features"][0]["geometry"]["coordinates"]
        self.assertGreater(sum(len(r) for p in polys for r in p), 2000)
        ring = polys[0][0]
        self.assertEqual(ring[0], ring[-1])                     # closed, as GeoJSON wants
        uk = self.land.geojson((-11.0, 49.0, 2.5, 61.0))
        self.assertEqual(uk["detail"], "coarse")
        self.assertEqual(self.land.geojson(clyde, "coarse")["detail"], "coarse")
        c = self.land.compact(clyde)
        self.assertEqual((c["detail"], c["scale"]), ("fine", 1e-4))
        self.assertEqual(len(c["polygons"]), len(polys))

    def test_land_and_sea_are_where_they_are(self):
        for lat, lon in [(55.58, -5.25), (55.77, -4.925), (55.83, -4.37), (53.35, -6.26)]:   # Arran, Great Cumbrae, Glasgow, Dublin
            self.assertTrue(mapdata.point_on_land(self.land, lat, lon), (lat, lon))
        for lat, lon in [(55.50, -4.90), (55.65, -4.97), (54.0, -5.0)]:                     # the firth, the Irish Sea
            self.assertFalse(mapdata.point_on_land(self.land, lat, lon), (lat, lon))

    def test_a_box_outside_the_data_is_empty_and_a_bad_one_is_refused(self):
        self.assertEqual(self.land.geojson((10.0, 40.0, 11.0, 41.0))["features"], [])
        for bad in ("", "1,2,3", "2,0,1,1", "a,b,c,d", "-200,0,0,1"):
            self.assertIsNone(mapdata.parse_bbox(bad), bad)
        self.assertEqual(mapdata.parse_bbox("-5.4,55.3,-4.5,55.9"), (-5.4, 55.3, -4.5, 55.9))


class Tiles(unittest.TestCase):
    def cache(self, enabled=True, cap=200, fetch=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.osm = fetch if fetch is not None else FakeOsm()
        self.on = {"v": enabled}
        return mapdata.TileCache(Path(tmp.name), lambda: self.on["v"], lambda: cap, fetch=self.osm)

    def test_a_tile_is_fetched_once_as_the_policy_asks_and_then_served_from_disk(self):
        c = self.cache()
        png, max_age = c.get(10, 498, 317)
        self.assertEqual(png, PNG)
        self.assertGreater(max_age, 0)
        self.assertEqual(len(self.osm.calls), 1)
        url, h = self.osm.calls[0]
        self.assertEqual(url, "https://tile.openstreetmap.org/10/498/317.png")
        self.assertRegex(h["User-Agent"], r"^OpenHamShack-Radio/\S+ \(\+https://openhamshack\.com\)$")
        self.assertEqual(set(h), {"User-Agent"})                # no cookies, no Referer, no no-cache
        self.assertEqual(c.get(10, 498, 317)[0], PNG)
        self.assertEqual(len(self.osm.calls), 1)                # fresh: from the disk
        # Nothing but what was asked for: no neighbours, no other zooms.
        self.assertEqual([u for u, _ in self.osm.calls], ["https://tile.openstreetmap.org/10/498/317.png"])

    def test_a_stale_tile_is_revalidated_conditionally(self):
        c = self.cache()
        c.get(12, 1990, 1270)
        now = time.time()
        with mock.patch.object(mapdata, "_now", lambda: now + 3 * 86_400):
            self.assertEqual(c.get(12, 1990, 1270)[0], PNG)     # stale but within stale-while-revalidate
            for _ in range(100):
                if len(self.osm.calls) == 2 and not c.pending:
                    break
                time.sleep(0.02)
        url, h = self.osm.calls[1]
        self.assertEqual((h.get("If-None-Match"), h.get("If-Modified-Since")),
                         ('"abc"', "Tue, 27 Oct 2026 10:00:00 GMT"))
        self.assertGreater(c.index["12/1990/1270.png"]["fresh"], now + 3 * 86_400)   # the 304 made it fresh

    def test_offline_it_backs_off_and_serves_stale_only_within_stale_if_error(self):
        c = self.cache()
        c.get(9, 249, 158)
        self.osm.down = True
        now = time.time()
        with mock.patch.object(mapdata, "_now", lambda: now + 10 * 86_400):
            # Past fresh (2 days) and both stale allowances (7 more): a
            # fetch, which fails, and nothing to serve.
            self.assertIsNone(c.get(9, 249, 158))
            n = len(self.osm.calls)
            for y in range(150, 160):
                self.assertIsNone(c.get(9, 250, y))             # backing off: not one request per tile
            self.assertEqual(len(self.osm.calls), n)
            self.assertFalse(c.stats()["online"])
        # A server that allows an hour of stale-while-revalidate and a week
        # of stale-if-error: three days on, the fetch fails and the tile is
        # still served; ten days on, it is not.
        c2 = self.cache()
        self.osm.headers["cache-control"] = "max-age=172800, stale-while-revalidate=3600, stale-if-error=604800"
        c2.get(9, 249, 158)
        self.osm.down = True
        with mock.patch.object(mapdata, "_now", lambda: now + 3 * 86_400):
            self.assertEqual(c2.get(9, 249, 158)[0], PNG)
        c2.backoff_until = 0.0
        with mock.patch.object(mapdata, "_now", lambda: now + 10 * 86_400):
            self.assertIsNone(c2.get(9, 249, 158))

    def test_a_refused_tile_is_not_asked_again_and_the_cap_holds(self):
        c = self.cache(cap=1)
        self.assertIsNone(c.get(0, 0, 0))
        self.assertIsNone(c.get(0, 0, 0))
        self.assertEqual(len(self.osm.calls), 1)
        big = b"\x89PNG\r\n\x1a\n" + bytes(300_000)
        osm = self.osm
        c.fetch = lambda url, h: (osm.calls.append((url, h)), (200, dict(osm.headers), big))[1]
        for x in range(6):
            c.get(5, x, 10)
        size = sum(v.get("size", 0) for v in c.index.values())
        self.assertLessEqual(size, 1_000_000)
        self.assertIn("5/5/10.png", c.index)                    # the newest kept, the oldest gone
        self.assertNotIn("5/0/10.png", c.index)

    def test_the_setting_off_means_no_traffic_and_no_tile(self):
        c = self.cache()
        c.get(10, 498, 317)
        self.on["v"] = False
        self.assertIsNone(c.get(10, 498, 317))
        self.assertIsNone(c.get(10, 499, 317))
        self.assertEqual(len(self.osm.calls), 1)
        self.assertFalse(c.stats()["online"])

    def test_no_fetcher_is_offline(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = mapdata.TileCache(Path(tmp.name), lambda: True, lambda: 200, fetch=None)
        self.assertIsNone(c.get(10, 498, 317))
        self.assertFalse(c.stats()["online"])

    def test_bad_coordinates_are_no_tile(self):
        c = self.cache()
        for z, x, y in [(19, 0, 0), (2, 4, 0), (2, 0, -1)]:
            self.assertIsNone(c.get(z, x, y))
        self.assertEqual(self.osm.calls, [])


class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simSignals": False,
               "callsign": "GM4BRI", "licenceClass": "full", "locator": "IO75RL"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio)
        self.osm = FakeOsm()
        self.radio.map_tiles.fetch = self.osm
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)

    def req(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("GET", path, None, {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "tv",
                                      "X-OpenHamShack-Level": "view", "X-Forwarded-Prefix": "/apps/radio",
                                      **(headers or {})})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), raw

    def test_info(self):
        s, h, raw = self.req("/api/map/info")
        a = json.loads(raw)
        self.assertEqual(s, 200)
        self.assertEqual(a["attribution"][0]["text"], "© OpenStreetMap contributors")
        self.assertEqual(a["bounds"], [-11.0, 49.0, 2.5, 61.0])
        self.assertEqual(set(a["land"]["levels"]), {"fine", "coarse"})
        self.assertEqual(a["tiles"]["url"], "api/map/tiles/{z}/{x}/{y}.png")    # relative, never absolute
        self.assertTrue(a["tiles"]["enabled"] and a["tiles"]["online"])
        self.assertEqual(a["station"]["locator"], "IO75RL")
        self.assertNotIn("http://", raw.decode().replace("https://www.openstreetmap.org/copyright", ""))

    def test_land_as_geojson_compact_and_gzipped(self):
        s, h, raw = self.req("/api/map/land?bbox=-5.4,55.3,-4.5,55.9")
        self.assertEqual((s, h["content-type"]), (200, "application/geo+json"))
        g = json.loads(raw)
        self.assertEqual((g["type"], g["detail"]), ("FeatureCollection", "fine"))
        s, h, raw = self.req("/api/map/land?bbox=-5.4,55.3,-4.5,55.9&format=compact",
                             {"Accept-Encoding": "gzip"})
        self.assertEqual(h["content-encoding"], "gzip")
        c = json.loads(gzip.decompress(raw))
        self.assertEqual(len(c["polygons"]), len(g["features"][0]["geometry"]["coordinates"]))
        s, h, raw = self.req("/api/map/land?bbox=1,2")
        self.assertEqual((s, json.loads(raw)["code"]), (400, "bad_params"))

    def test_tiles_and_404_when_there_is_none(self):
        s, h, raw = self.req("/api/map/tiles/10/498/317.png")
        self.assertEqual((s, h["content-type"], raw), (200, "image/png", PNG))
        self.assertRegex(h["cache-control"], r"^max-age=\d+$")
        self.radio.st["mapOnlineTiles"] = False
        s, h, raw = self.req("/api/map/tiles/10/498/317.png")
        self.assertEqual((s, json.loads(raw)["code"]), (404, "no_tile"))
        s, h, raw = self.req("/api/map/tiles/10/498/x.png")
        self.assertEqual(s, 404)


if __name__ == "__main__":
    unittest.main()
