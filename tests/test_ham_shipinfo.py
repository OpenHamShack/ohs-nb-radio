"""Ship details and photos for AIS's map (ohsradio/shipinfo.py,
01/11/2026), against a fake Wikidata query service, Commons API and image
host on one local socket: nothing here can reach the real internet
(scratch_home.py points all three at a closed port, and each test at its
own server).

- **Facts:** by IMO when the ship sent a valid one, else by MMSI; never
  for a base station, aid to navigation or beacon; `{}` for a ship
  Wikidata does not know; a month for a hit, a week for a miss, `null`
  and asked again after a failure or offline.
- **Photos:** the thumbnail fetched once, kept and served from the box,
  with the author (HTML stripped) and licence as the credit and the
  Commons page as the link; none from a host that is not Commons', too
  large, or not a picture; the folder capped, and emptied with its entries.
- **What goes out:** one request at a time, RATE_S apart; a User-Agent
  naming the program and the project's address; no cookies or Referer.
- **The setting off:** no request, `null` even for what is cached.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import copy
import http.server
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

from ohsradio import aircraftinfo, flightroutes, shipinfo
from ohsradio.shipinfo import ShipInfo

from test_ham_flightroutes import Clock, closed_port

# Shaped as the real answers for MV Loch Seaforth (IMO 9665437), 01/11/2026,
# trimmed; the picture is a few bytes standing in for its 86 kB JPEG.
FILE = "Loch Seaforth At Stornoway At Night, 21 February 2015.jpg"
SPARQL = {"head": {"vars": ["item", "itemLabel", "builderLabel", "inception", "service", "operatorLabel", "gt",
                            "homeLabel", "image"]},
          "results": {"bindings": [
              {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q11713805"},
               "itemLabel": {"xml:lang": "en", "type": "literal", "value": "MV Loch Seaforth"},
               "builderLabel": {"type": "literal", "value": "Flensburger Schiffbau-Gesellschaft"},
               "service": {"type": "literal", "value": "2015-02-10T00:00:00Z"},
               "operatorLabel": {"type": "literal", "value": "Caledonian MacBrayne"},
               "gt": {"type": "literal", "value": "8680"},
               "homeLabel": {"type": "literal", "value": "Stornoway"},
               "image": {"type": "uri", "value": "http://commons.wikimedia.org/wiki/Special:FilePath/"
                                                 + urllib.parse.quote(FILE)}},
              # A second operator: OPTIONALs multiply rows; the first wins.
              {"item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q11713805"},
               "operatorLabel": {"type": "literal", "value": "CMAL"}}]}}
NO_ROWS = {"head": {"vars": ["item"]}, "results": {"bindings": []}}
JPEG = b"\xff\xd8\xff\xe0 not really a picture"


def imageinfo(base: str, artist: str = '<a href="//commons.wikimedia.org/wiki/User:Mn28" title="User:Mn28">Mn28</a>',
              thumb: str | None = None) -> dict:
    return {"batchcomplete": True, "query": {"pages": [{
        "title": f"File:{FILE}", "imageinfo": [{
            "thumburl": thumb or f"{base}/wikipedia/commons/thumb/8/87/x.jpg/960px-x.jpg?utm_source=commons",
            "thumbwidth": 640, "thumbheight": 426,
            "descriptionurl": f"{base}/wiki/File:Loch_Seaforth.jpg",
            "extmetadata": {"Artist": {"value": artist, "source": "commons-desc-page"},
                            "LicenseShortName": {"value": "CC BY-SA 3.0", "source": "commons-desc-page"}}}]}]}}


class FakeWikimedia:
    """The query service (`GET /sparql?query=`: a ship by its IMO or MMSI
    in `ships`, else no rows), Commons' API (`GET /w/api.php`) and its
    image host (`GET /wikipedia/...`). `fail` answers 500 to any query
    naming it. Every request's path and headers are kept."""

    def __init__(self):
        self.ships = {"9665437": SPARQL}
        self.info: dict | None = None          # imageinfo's answer; the default built from base_url
        self.picture = (JPEG, "image/jpeg")
        self.fail: set[str] = set()
        self.requests: list[tuple[str, dict, float]] = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, status, body: bytes, ctype="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                me.requests.append((self.path, dict(self.headers), time.monotonic()))
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/sparql":
                    text = q["query"][0]
                    if any(f'"{x}"' in text for x in me.fail):
                        return self.send(500, b"{}")
                    hit = next((a for k, a in me.ships.items() if f'"{k}"' in text), NO_ROWS)
                    return self.send(200, json.dumps(hit).encode(), "application/sparql-results+json")
                if u.path == "/w/api.php":
                    return self.send(200, json.dumps(me.info or imageinfo(me.base_url())).encode())
                if u.path.startswith("/wikipedia/"):
                    return self.send(200, me.picture[0], me.picture[1])
                self.send(404, b"{}")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def paths(self, prefix: str) -> list[str]:
        return [p for p, _h, _t in self.requests if p.startswith(prefix)]

    def queries(self) -> list[str]:
        return [urllib.parse.parse_qs(urllib.parse.urlsplit(p).query)["query"][0] for p in self.paths("/sparql")]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


SEAFORTH = {"mmsi": 235_103_359, "class": "A", "imo": 9665437, "name": "LOCH SEAFORTH"}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "shipinfo"
        self.clock = Clock()
        self.on = [True]
        self.src = FakeWikimedia()
        self.addCleanup(self.src.close)

    def make(self, url=None, timeout=5.0) -> ShipInfo:
        si = ShipInfo(self.dir, lambda: self.on[0], clock=self.clock, base_url=url or self.src.base_url(),
                      timeout=timeout)
        si.rate_s = 0.02                    # the rate is its own test, below
        self.addCleanup(si.stop)
        return si

    def until(self, fn, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = fn()
            if got is not None:
                return got
            time.sleep(0.01)
        raise AssertionError("never answered")

    def settled(self, si, key):
        """Until the worker has stored `key`'s answer, file and all."""
        self.until(lambda: si.lookup.cache.get(key) and key in (self.dir / "ships.json").read_text() or None)


class Facts(Base):
    def test_a_known_ship_by_its_imo_with_its_photo(self):
        si = self.make()
        si.start()
        self.assertIsNone(si.info(SEAFORTH))          # not yet: queued, never waited for
        got = self.until(lambda: si.info(SEAFORTH))
        self.assertEqual(got, {
            "qid": "Q11713805", "label": "MV Loch Seaforth", "builder": "Flensburger Schiffbau-Gesellschaft",
            "built": "2015", "operator": "Caledonian MacBrayne", "grossTonnage": 8680, "homePort": "Stornoway",
            "photo": {"credit": "Mn28 · CC BY-SA 3.0", "link": f"{self.src.base_url()}/wiki/File:Loch_Seaforth.jpg",
                      "width": 640, "height": 426},
            "source": "wikidata"})
        self.assertEqual(si.photo(SEAFORTH), (JPEG, "image/jpeg"))
        # One query naming the IMO, Commons asked for that file at ~640 px, then the picture.
        self.assertEqual(len(self.src.queries()), 1)
        self.assertIn('wdt:P458 "9665437"', self.src.queries()[0])
        api = urllib.parse.parse_qs(urllib.parse.urlsplit(self.src.paths("/w/api.php")[0]).query)
        self.assertEqual((api["titles"], api["iiurlwidth"]), ([f"File:{FILE}"], ["640"]))
        self.assertEqual(len(self.src.paths("/wikipedia/")), 1)
        for _p, headers, _t in self.src.requests:
            self.assertEqual(headers["User-Agent"],
                             f"{flightroutes.user_agent()} (+https://openhamshack.com/) Python-urllib")
            self.assertNotIn("Cookie", headers)
            self.assertNotIn("Referer", headers)

    def test_a_label_that_is_only_an_imo_number_is_no_name(self):
        d = copy.deepcopy(SPARQL)
        d["results"]["bindings"][0]["itemLabel"]["value"] = "IMO 9370288"
        self.assertIsNone(shipinfo.parse_query(d)["label"])
        self.assertEqual(shipinfo.parse_query(SPARQL)["label"], "MV Loch Seaforth")

    def test_a_credit_names_the_person_not_their_user_page(self):
        self.assertEqual(shipinfo.credit("User:Dave souza", "CC BY-SA 2.5"), "Dave souza · CC BY-SA 2.5")
        self.assertEqual(shipinfo.credit("Marc Ryckaert", "CC BY-SA 4.0"), "Marc Ryckaert · CC BY-SA 4.0")

    def test_without_a_valid_imo_by_mmsi(self):
        si = self.make()
        si.start()
        for imo in (None, 0, 9665438, 123):          # 9665438: the check digit is wrong
            v = {"mmsi": 235_000_001, "class": "B", "imo": imo}
            self.assertEqual(self.until(lambda v=v: si.info(v)), {})
        self.assertEqual(len(self.src.queries()), 1)  # all four the one MMSI
        self.assertIn('wdt:P587 "235000001"', self.src.queries()[0])

    def test_stations_that_are_not_ships_are_never_asked_about(self):
        si = self.make()
        si.start()
        for v in ({"mmsi": 2_320_123, "class": "base"}, {"mmsi": 992_351_234, "class": "aton"},
                  {"mmsi": 970_123_456, "class": "sart"}, {"mmsi": 111_232_123, "class": "sar"},
                  {"mmsi": 970_123_456, "class": "A"},     # a SART heard as class A: not a ship's MMSI
                  {"mmsi": None, "class": "A"}):
            self.assertIsNone(si.info(v))
            self.assertIsNone(si.photo(v))
        time.sleep(0.2)
        self.assertEqual(self.src.requests, [])

    def test_an_unknown_ship_is_empty_and_asked_again_after_a_week(self):
        si = self.make()
        si.start()
        v = {"mmsi": 235_000_002, "class": "A"}
        self.assertEqual(self.until(lambda: si.info(v)), {})
        self.clock.t += shipinfo.UNKNOWN_TTL_S - 60
        self.assertEqual(si.info(v), {})
        time.sleep(0.1)
        self.assertEqual(len(self.src.queries()), 1)
        self.clock.t += 120
        self.assertIsNone(si.info(v))                 # stale: asked again
        self.assertEqual(self.until(lambda: si.info(v)), {})
        self.assertEqual(len(self.src.queries()), 2)

    def test_a_hit_lasts_a_month(self):
        si = self.make()
        si.start()
        self.until(lambda: si.info(SEAFORTH))
        self.clock.t += shipinfo.OK_TTL_S - 60
        self.assertEqual(si.info(SEAFORTH)["builder"], "Flensburger Schiffbau-Gesellschaft")
        self.clock.t += 120
        self.assertIsNone(si.info(SEAFORTH))

    def test_a_failure_is_null_then_asked_again(self):
        self.src.fail.add("9665437")
        si = self.make()
        si.lookup.backoff_min_s = 0.0
        si.start()
        si.info(SEAFORTH)
        self.until(lambda: si.lookup.cache.get("imo:9665437"))
        self.assertEqual(si.lookup.cache["imo:9665437"]["status"], "error")
        self.assertIsNone(si.info(SEAFORTH))
        self.src.fail.clear()
        self.clock.t += aircraftinfo.ERROR_RETRY_S + 1
        self.assertEqual(self.until(lambda: si.info(SEAFORTH))["qid"], "Q11713805")

    def test_offline_is_null(self):
        si = self.make(f"http://127.0.0.1:{closed_port()}", timeout=2.0)
        si.start()
        si.info(SEAFORTH)
        self.until(lambda: si.lookup.cache.get("imo:9665437"))
        self.assertEqual((si.info(SEAFORTH), si.photo(SEAFORTH)), (None, None))


class Photos(Base):
    def test_the_authors_html_is_stripped_and_a_missing_one_named_by_commons(self):
        self.src.info = imageinfo(self.src.base_url(), artist='<bdi><a href="x">Jane&nbsp;Smith</a>\n</bdi>')
        si = self.make()
        si.start()
        self.assertEqual(self.until(lambda: si.info(SEAFORTH))["photo"]["credit"], "Jane Smith · CC BY-SA 3.0")
        self.assertEqual(shipinfo.credit(None, None), "Wikimedia Commons")

    def test_no_photo_from_another_host_too_large_or_not_a_picture(self):
        for case in ("host", "large", "type"):
            with self.subTest(case):
                self.src.info = imageinfo(self.src.base_url(), thumb="https://elsewhere.example/x.jpg") \
                    if case == "host" else None
                self.src.picture = (b"x" * (shipinfo.PHOTO_MAX_BYTES + 1), "image/jpeg") if case == "large" \
                    else (b"<html>", "text/html") if case == "type" else (JPEG, "image/jpeg")
                si = ShipInfo(self.dir / case, lambda: True, clock=self.clock, base_url=self.src.base_url())
                si.rate_s = 0.02
                self.addCleanup(si.stop)
                si.start()
                got = self.until(lambda: si.info(SEAFORTH))
                self.assertEqual(got["operator"], "Caledonian MacBrayne")     # the facts stand
                self.assertIsNone(got["photo"])
                self.assertIsNone(si.photo(SEAFORTH))
                self.assertFalse((self.dir / case / "photos").exists() and any((self.dir / case / "photos").iterdir()))

    def test_the_folder_is_capped_oldest_first(self):
        for n in range(3):
            self.src.ships[f"23500001{n}"] = SPARQL
        si = self.make()
        si.max_photos = 2
        si.start()
        ships = [{"mmsi": 235_000_010 + n, "class": "B"} for n in range(3)]
        for v in ships:
            self.until(lambda v=v: si.info(v))
            time.sleep(0.02)                          # distinct file times
        self.assertEqual(sorted(p.name for p in (self.dir / "photos").iterdir()),
                         ["mmsi-235000011.jpg", "mmsi-235000012.jpg"])
        self.assertIsNone(si.info(ships[0])["photo"])                 # its facts, no picture
        self.assertIsNone(si.photo(ships[0]))
        self.assertEqual(si.photo(ships[2]), (JPEG, "image/jpeg"))

    def test_a_stale_entry_takes_its_photo_with_it(self):
        si = self.make()
        si.start()
        self.until(lambda: si.photo(SEAFORTH))
        self.assertEqual([p.name for p in (self.dir / "photos").iterdir()], ["imo-9665437.jpg"])
        # A month on, the next save (another ship's answer) drops the entry and its file.
        self.clock.t += shipinfo.OK_TTL_S + 1
        v = {"mmsi": 235_000_003, "class": "A"}
        si.info(v)
        self.settled(si, "mmsi:235000003")
        self.assertEqual(list((self.dir / "photos").iterdir()), [])


class Survives(Base):
    def test_a_restart_reads_the_cache_and_the_photo_without_asking(self):
        si = self.make()
        si.start()
        self.until(lambda: si.photo(SEAFORTH))
        si.stop()
        self.src.requests.clear()
        again = self.make()
        self.assertEqual(again.info(SEAFORTH)["photo"]["credit"], "Mn28 · CC BY-SA 3.0")
        self.assertEqual(again.photo(SEAFORTH), (JPEG, "image/jpeg"))
        self.assertEqual(self.src.requests, [])

    def test_a_photo_no_entry_names_is_swept_at_start(self):
        (self.dir / "photos").mkdir(parents=True)
        (self.dir / "photos" / "imo-1234567.jpg").write_bytes(JPEG)
        (self.dir / "photos" / "x.jpg.part").write_bytes(JPEG)
        self.make()
        self.assertEqual(list((self.dir / "photos").iterdir()), [])


class SettingOff(Base):
    def test_off_asks_nothing_and_hides_the_cache(self):
        si = self.make()
        si.start()
        self.until(lambda: si.photo(SEAFORTH))
        n = len(self.src.requests)
        self.on[0] = False
        self.assertIsNone(si.info(SEAFORTH))
        self.assertIsNone(si.photo(SEAFORTH))
        si.info({"mmsi": 235_000_004, "class": "A"})
        time.sleep(0.2)
        self.assertEqual(len(self.src.requests), n)


class Rate(Base):
    def test_every_request_waits_for_the_one_before(self):
        self.assertGreaterEqual(shipinfo.RATE_S, 2.0)        # Brian's floor (module docstring)
        si = self.make()
        si.rate_s = 0.3
        si.start()
        si.info(SEAFORTH)                                     # three requests: query, file, picture
        si.info({"mmsi": 235_000_005, "class": "A"})          # and a fourth
        self.until(lambda: si.photo(SEAFORTH), timeout=10.0)
        self.until(lambda: si.info({"mmsi": 235_000_005, "class": "A"}), timeout=10.0)
        times = sorted(t for _p, _h, t in self.src.requests)
        self.assertEqual(len(times), 4)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, 0.3 - 0.05)


if __name__ == "__main__":
    unittest.main()
