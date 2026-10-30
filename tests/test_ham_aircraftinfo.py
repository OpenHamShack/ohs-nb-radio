"""Aircraft details and photos for ADS-B's map (ohsradio/aircraftinfo.py,
30/10/2026), against a fake adsbdb and a fake Planespotters on a local
socket: nothing here can reach the real internet (scratch_home.py points
both at a closed port, and each test at its own server).

- **Details:** found (the API's `info` shape, the airline added), unknown
  (`{}`, or just the airline), failed (`null`, asked again later), and
  their lifetimes - a month for a hit, a day for a miss.
- **Photos:** the address, credit and link exactly as Planespotters gave
  them (its terms), `null` for none, and kept no longer than 24 hours -
  dropped from the file, not only ignored.
- **What goes out:** the address in the path; adsbdb's User-Agent is
  flightroutes'; Planespotters' adds the project's contact address its
  terms require, and nothing about the station.
- **Backoff:** after a failure the next request of any address waits.
- **The settings off:** no request, `null` even for what is cached.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.server
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ohsradio import aircraftinfo, flightroutes
from ohsradio.aircraftinfo import AircraftInfo

from test_ham_flightroutes import Clock, closed_port

# Shaped as the real answers for 4CA264 (EI-DHH), 30/10/2026.
ADSBDB = {"response": {"aircraft": {
    "type": "737NG 8AS/W", "icao_type": "B738", "manufacturer": "Boeing", "mode_s": "4CA264",
    "registration": "EI-DHH", "registered_owner_country_iso_name": "IE",
    "registered_owner_country_name": "Ireland", "registered_owner_operator_flag_code": "RYR",
    "registered_owner": "Ryanair", "url_photo": "https://image.airport-data.com/aircraft/001449477.jpg"}}}
PHOTO = {"photos": [{
    "id": "1817303",
    "thumbnail": {"src": "https://t.plnspttrs.net/45131/1817303_22af4fc96d_t.jpg",
                  "size": {"width": 200, "height": 135}},
    "thumbnail_large": {"src": "https://t.plnspttrs.net/45131/1817303_22af4fc96d_280.jpg",
                        "size": {"width": 416, "height": 280}},
    "link": "https://www.planespotters.net/photo/1817303/ei-dhh-ryanair-boeing-737-8as-wl?utm_source=api",
    "photographer": "Björn Huke"}]}
RYANAIR = {"name": "Ryanair", "icao": "RYR", "iata": "FR"}


class FakeSources:
    """adsbdb's `GET /v0/aircraft/<hex>` (an aircraft, or 404 "unknown
    aircraft") and Planespotters' `GET /pub/photos/hex/<hex>` (a photo, or
    an empty list), on one local server; `fail` answers 500 for any
    address in it. Every request's path and headers are kept."""

    def __init__(self):
        self.aircraft = {"4CA264": ADSBDB}
        self.photos = {"4CA264": PHOTO}
        self.fail: set[str] = set()
        self.requests: list[tuple[str, dict, float]] = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                me.requests.append((self.path, dict(self.headers), time.monotonic()))
                hexa = self.path.rsplit("/", 1)[-1]
                if hexa in me.fail:
                    self.send_response(500)
                    self.end_headers()
                    return
                if self.path.startswith("/v0/aircraft/"):
                    known = hexa in me.aircraft
                    status, body = (200, me.aircraft[hexa]) if known else (404, {"response": "unknown aircraft"})
                elif self.path.startswith("/pub/photos/hex/"):
                    status, body = 200, me.photos.get(hexa, {"photos": []})
                else:
                    status, body = 404, {}
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def paths(self, prefix: str) -> list[str]:
        return [p for p, _h, _t in self.requests if p.startswith(prefix)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "aircraftinfo"
        self.clock = Clock()
        self.info_on = [True]
        self.photo_on = [True]
        self.src = FakeSources()
        self.addCleanup(self.src.close)

    def make(self, url=None, timeout=5.0) -> AircraftInfo:
        url = url or self.src.base_url()
        ai = AircraftInfo(self.dir, lambda: self.info_on[0], lambda: self.photo_on[0], clock=self.clock,
                          adsbdb_url=url, planespotters_url=url, timeout=timeout)
        for lk in (ai.infos, ai.photos):
            lk.rate_s = 0.05                # the rate is its own test, below
        self.addCleanup(ai.stop)
        return ai

    def until(self, fn, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = fn()
            if got is not None:
                return got
            time.sleep(0.01)
        raise AssertionError("never answered")


class Details(Base):
    def test_a_known_aircraft_with_its_airline(self):
        ai = self.make()
        ai.start()
        self.assertIsNone(ai.info("4ca264", RYANAIR))      # not yet: queued, never waited for
        info = self.until(lambda: ai.info("4CA264", RYANAIR))
        self.assertEqual(info, {"registration": "EI-DHH", "typeCode": "B738", "type": "737NG 8AS/W",
                                "manufacturer": "Boeing", "owner": "Ryanair", "country": "Ireland",
                                "airline": RYANAIR, "source": "adsbdb"})
        self.assertIsNone(ai.info("4CA264")["airline"])    # a GA or military callsign: no airline
        path, headers, _t = self.src.requests[0]
        self.assertEqual(path, "/v0/aircraft/4CA264")
        self.assertEqual(headers["User-Agent"], flightroutes.user_agent())
        self.assertNotIn("Cookie", headers)

    def test_an_unknown_aircraft_is_empty_not_null_and_asked_again_after_a_day(self):
        ai = self.make()
        ai.start()
        self.assertEqual(self.until(lambda: ai.info("ABC123")), {})
        # Who flies it is still worth saying when the airframe is unknown.
        self.assertEqual(ai.info("ABC123", RYANAIR), {"airline": RYANAIR, "source": "adsbdb"})
        n = len(self.src.paths("/v0/"))
        self.clock.t += aircraftinfo.INFO_UNKNOWN_TTL_S - 60
        self.assertEqual(ai.info("ABC123"), {})
        time.sleep(0.1)
        self.assertEqual(len(self.src.paths("/v0/")), n)
        self.clock.t += 120
        self.assertIsNone(ai.info("ABC123"))                # stale: asked again
        self.assertEqual(self.until(lambda: ai.info("ABC123")), {})
        self.assertEqual(len(self.src.paths("/v0/")), n + 1)

    def test_a_hit_lasts_a_month(self):
        ai = self.make()
        ai.start()
        self.until(lambda: ai.info("4CA264"))
        self.clock.t += aircraftinfo.INFO_OK_TTL_S - 60
        self.assertEqual(ai.info("4CA264")["registration"], "EI-DHH")
        self.clock.t += 120
        self.assertIsNone(ai.info("4CA264"))

    def test_a_failure_is_null_then_asked_again(self):
        self.src.fail.add("4CA264")
        ai = self.make()
        ai.infos.backoff_min_s = 0.0
        ai.start()
        ai.info("4CA264")
        self.until(lambda: ai.infos.cache.get("4CA264"))
        self.assertEqual(ai.infos.cache["4CA264"]["status"], "error")
        self.assertIsNone(ai.info("4CA264"))
        self.src.fail.clear()
        self.clock.t += aircraftinfo.ERROR_RETRY_S + 1
        self.assertEqual(self.until(lambda: ai.info("4CA264"))["typeCode"], "B738")

    def test_offline_is_null(self):
        ai = self.make(f"http://127.0.0.1:{closed_port()}", timeout=2.0)
        ai.start()
        ai.info("4CA264")
        ai.photo("4CA264")
        self.until(lambda: ai.infos.cache.get("4CA264") and ai.photos.cache.get("4CA264"))
        self.assertEqual((ai.info("4CA264"), ai.photo("4CA264")), (None, None))

    def test_not_an_icao_address_is_never_asked(self):
        ai = self.make()
        ai.start()
        for not_one in ("~F00202", "", None, "XYZ123", "4CA2641"):
            self.assertIsNone(ai.info(not_one))
            self.assertIsNone(ai.photo(not_one))
        time.sleep(0.2)
        self.assertEqual(self.src.requests, [])


class Photos(Base):
    def test_the_addresses_exactly_as_given_with_the_credit(self):
        ai = self.make()
        ai.start()
        self.assertIsNone(ai.photo("4CA264"))
        p = self.until(lambda: ai.photo("4CA264"))
        self.assertEqual(p, {"src": PHOTO["photos"][0]["thumbnail_large"]["src"], "width": 416, "height": 280,
                             "credit": "© Björn Huke", "link": PHOTO["photos"][0]["link"]})
        path, headers, _t = self.src.requests[0]
        self.assertEqual(path, "/pub/photos/hex/4CA264")
        self.assertEqual(headers["User-Agent"], f"{flightroutes.user_agent()} (+https://openhamshack.com/)")
        self.assertNotIn("Referer", headers)
        self.assertNotIn("Origin", headers)

    def test_no_photo_is_null(self):
        ai = self.make()
        ai.start()
        ai.photo("ABC123")
        self.until(lambda: ai.photos.cache.get("ABC123"))
        self.assertIsNone(ai.photo("ABC123"))

    def test_a_photo_that_is_not_https_is_not_shown(self):
        bad = json.loads(json.dumps(PHOTO))
        bad["photos"][0]["thumbnail_large"]["src"] = "http://elsewhere.example/x.jpg"
        self.src.photos["ABC123"] = bad
        ai = self.make()
        ai.start()
        ai.photo("ABC123")
        self.until(lambda: ai.photos.cache.get("ABC123"))
        self.assertIsNone(ai.photo("ABC123"))

    def test_kept_24_hours_at_most_even_on_disk(self):
        ai = self.make()
        ai.start()
        self.until(lambda: ai.photo("4CA264"))
        self.assertIn("4CA264", json.loads((self.dir / "photos.json").read_text()))
        # A day on, the next save (another aircraft's answer) drops it from
        # the file, not only from what is shown...
        self.clock.t += aircraftinfo.PHOTO_TTL_S + 1
        ai.photo("ABC123")
        self.until(lambda: ai.photos.cache.get("ABC123"))
        self.assertEqual(list(json.loads((self.dir / "photos.json").read_text())), ["ABC123"])
        # ...and a restart never reads one older than that back.
        self.clock.t += aircraftinfo.PHOTO_TTL_S + 1
        self.assertEqual(self.make().photos.cache, {})


class Survives(Base):
    def test_a_restart_reads_the_files_without_asking(self):
        ai = self.make()
        ai.start()
        self.until(lambda: ai.info("4CA264") and ai.photo("4CA264"))
        ai.stop()
        self.src.requests.clear()
        again = self.make()
        self.assertEqual(again.info("4CA264")["registration"], "EI-DHH")
        self.assertEqual(again.photo("4CA264")["credit"], "© Björn Huke")
        self.assertEqual(self.src.requests, [])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["info.json", "photos.json"])


class SettingsOff(Base):
    def test_each_off_asks_nothing_and_hides_its_cache(self):
        ai = self.make()
        ai.start()
        self.until(lambda: ai.info("4CA264") and ai.photo("4CA264"))
        n = len(self.src.requests)
        self.info_on[0] = False
        self.assertIsNone(ai.info("4CA264", RYANAIR))
        self.assertIsNotNone(ai.photo("4CA264"))           # the other setting, still on
        self.photo_on[0] = False
        self.assertIsNone(ai.photo("4CA264"))
        ai.info("ABC123")
        ai.photo("ABC123")
        time.sleep(0.2)
        self.assertEqual(len(self.src.requests), n)


class RateAndBackoff(Base):
    def test_one_a_second_per_source(self):
        ai = self.make()
        ai.infos.rate_s = aircraftinfo.RATE_S
        ai.start()
        for h in ("AAAAA1", "AAAAA2", "AAAAA3"):
            ai.info(h)
        for h in ("AAAAA1", "AAAAA2", "AAAAA3"):
            self.until(lambda h=h: ai.infos.cache.get(h), timeout=10.0)
        times = [t for p, _h, t in self.src.requests if p.startswith("/v0/")]
        self.assertEqual(len(times), 3)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, aircraftinfo.RATE_S - 0.05)

    def test_after_a_failure_the_whole_source_waits_and_the_wait_grows(self):
        self.src.fail.update({"BAD001", "BAD002"})
        ai = self.make()
        ai.infos.backoff_min_s, ai.infos.backoff_max_s = 0.6, 1.0
        ai.start()
        for h in ("BAD001", "BAD002", "4CA264"):
            ai.info(h)
        self.until(lambda: ai.info("4CA264"), timeout=10.0)
        times = [t for p, _h, t in self.src.requests if p.startswith("/v0/")]
        self.assertEqual(len(times), 3)
        self.assertGreaterEqual(times[1] - times[0], 0.6 - 0.05)    # the first wait
        self.assertGreaterEqual(times[2] - times[1], 1.0 - 0.05)    # doubled, to the cap
        self.assertEqual(ai.infos.backoff_s, 0.0)                    # a success ends it


if __name__ == "__main__":
    unittest.main()
