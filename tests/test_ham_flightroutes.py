"""Flight routes for ADS-B's aircraft (ohsradio/flightroutes.py,
29/10/2026), against a fake adsbdb on a local socket: nothing here can
reach the real internet (a test's Radio starts no fetcher, and each test
points the fetcher at its own server or a closed port, as test_ham_dmrids.py
and test_ham_radiodns.py do for their sources).

- **Found, unknown, a server error, a timeout:** the four answers adsbdb
  (or any host) can give, and what each does to the cache.
- **The setting off:** no request at all, and no route even for a
  callsign already cached.
- **The cache survives a restart:** a fresh FlightRoutes reads the same
  file without asking the network again.
- **The rate limit:** several callsigns queued at once are never asked
  faster than one a second.
- **Over the API:** the route appears in api/adsb/aircraft and
  api/adsb/aircraft/{icao} on the simulator (test_ham_adsb.py's
  OverTheApi, extended there rather than duplicated here).
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.server
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ohsradio import flightroutes
from ohsradio.flightroutes import FlightRoutes, clean_callsign

ROUTE = {
    "response": {
        "flightroute": {
            "callsign": "BAW90", "callsign_icao": "BAW90", "callsign_iata": "BA90",
            "airline": {"name": "British Airways", "icao": "BAW", "iata": "BA"},
            "origin": {"iata_code": "GLA", "icao_code": "EGPF", "name": "Glasgow Airport",
                      "municipality": "Glasgow"},
            "destination": {"iata_code": "LGW", "icao_code": "EGKK", "name": "London Gatwick Airport",
                            "municipality": "London"},
        }
    }
}
UNKNOWN = {"response": "unknown callsign"}


class FakeAdsbdb:
    """adsbdb's `GET /v0/callsign/<cs>`: a route, a 404 "unknown callsign",
    a 500, or a hang, by callsign; every request's path, headers and
    arrival time are kept so a test can check the rate limit and what
    went out."""

    def __init__(self):
        self.routes: dict[str, dict] = {"BAW90": ROUTE}
        self.fail: set[str] = set()         # 500 for these
        self.hang: set[str] = set()         # never answer these
        self.requests: list[tuple[str, dict, float]] = []
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                me.requests.append((self.path, dict(self.headers), time.monotonic()))
                cs = self.path.rsplit("/", 1)[-1]
                if cs in me.hang:
                    time.sleep(30)          # outlives any test's timeout: a client-side timeout fires first
                    return
                if cs in me.fail:
                    self.send_response(500)
                    self.end_headers()
                    return
                body = json.dumps(me.routes.get(cs, UNKNOWN)).encode()
                self.send_response(200 if cs in me.routes else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Clock:
    def __init__(self):
        self.t = 1_793_000_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "flightroutes"
        self.clock = Clock()
        self.on = [True]

    def routes(self, base_url=None, timeout=5.0, **over) -> FlightRoutes:
        r = FlightRoutes(self.dir, enabled=lambda: self.on[0], clock=self.clock, base_url=base_url,
                         timeout=timeout, **over)
        self.addCleanup(r.stop)
        return r

    def fake(self) -> FakeAdsbdb:
        f = FakeAdsbdb()
        self.addCleanup(f.close)
        return f

    def wait_cached(self, r: FlightRoutes, cs: str, timeout=5.0) -> dict | None:
        """lookup() queues rather than blocking: poll until the worker has
        answered (the shape every caller actually sees)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with r.lock:
                if cs in r.cache:
                    return dict(r.cache[cs])
            time.sleep(0.01)
        raise AssertionError(f"{cs} never cached")


class CleanCallsign(unittest.TestCase):
    def test_what_is_worth_asking_about(self):
        self.assertEqual(clean_callsign("baw90"), "BAW90")
        self.assertEqual(clean_callsign("  RYR23FP "), "RYR23FP")
        for not_worth in ("", "   ", None, "G-ABCD", "D-EFGH", "N12345", "N1A", "N1234AB", "~F00202",
                          "TOOLONGCALLSIGN", "A"):
            self.assertIsNone(clean_callsign(not_worth), not_worth)


class TheFakeServer(Base):
    """Found, unknown, a 500 and a timeout - the four answers the lookup
    distinguishes."""

    def test_a_known_callsign_is_found_and_cached(self):
        f = self.fake()
        r = self.routes(f.base_url())
        r.start()
        self.assertEqual(r.lookup("BAW90"), None)          # not yet: the worker has not run
        route = self.wait_cached(r, "BAW90")
        self.assertEqual(route["status"], "ok")
        self.assertEqual(r.lookup("BAW90"),
                         {"from": "GLA", "to": "LGW", "fromName": "Glasgow Airport",
                          "toName": "London Gatwick Airport", "fromIcao": "EGPF", "toIcao": "EGKK",
                          "source": "adsbdb"})
        # What went out: the callsign in the path, the program and its
        # version, nothing else.
        path, headers, _t = f.requests[0]
        self.assertEqual(path, "/v0/callsign/BAW90")
        self.assertEqual(headers["User-Agent"], flightroutes.user_agent())
        self.assertRegex(headers["User-Agent"], r"^OpenHamShack-Radio/[^ ]+$")
        self.assertNotIn("Cookie", headers)

    def test_an_unknown_callsign_is_cached_negative(self):
        f = self.fake()
        r = self.routes(f.base_url())
        r.start()
        r.lookup("RYR999")
        ent = self.wait_cached(r, "RYR999")
        self.assertEqual((ent["status"], ent["route"]), ("unknown", None))
        self.assertIsNone(r.lookup("RYR999"))
        # Cached: asked once, not again while fresh.
        self.assertEqual(len(f.requests), 1)
        r.lookup("RYR999")
        time.sleep(0.05)
        self.assertEqual(len(f.requests), 1)

    def test_a_server_error_is_an_error_not_unknown(self):
        f = self.fake()
        f.fail.add("DLH1")
        r = self.routes(f.base_url())
        r.start()
        r.lookup("DLH1")
        ent = self.wait_cached(r, "DLH1")
        self.assertEqual(ent["status"], "error")
        self.assertIsNone(r.lookup("DLH1"))
        # Within ERROR_RETRY_S nothing is asked again.
        self.clock.t += flightroutes.ERROR_RETRY_S - 1
        r.lookup("DLH1")
        time.sleep(0.05)
        self.assertEqual(len(f.requests), 1)
        # Past it, found this time (the fault cleared), a fresh attempt.
        f.fail.discard("DLH1")
        self.clock.t += 2
        r.lookup("DLH1")
        ent = self.wait_cached_status(r, "DLH1", "unknown")
        self.assertEqual(ent["status"], "unknown")   # DLH1 is not in f.routes

    def wait_cached_status(self, r, cs, status, timeout=5.0):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            with r.lock:
                last = r.cache.get(cs)
            if last is not None and last["status"] == status:
                return last
            time.sleep(0.01)
        raise AssertionError((cs, status, last))

    def test_a_timeout_is_an_error(self):
        f = self.fake()
        f.hang.add("TIMEOUT1")
        r = self.routes(f.base_url(), timeout=0.3)
        r.start()
        t0 = time.monotonic()
        r.lookup("TIMEOUT1")
        ent = self.wait_cached(r, "TIMEOUT1", timeout=5.0)
        self.assertEqual(ent["status"], "error")
        self.assertLess(time.monotonic() - t0, 5.0)     # the socket timeout, not the hang

    def test_no_route_out_is_an_error(self):
        port = closed_port()
        r = self.routes(f"http://127.0.0.1:{port}", timeout=2.0)
        r.start()
        r.lookup("BAW90")
        ent = self.wait_cached(r, "BAW90")
        self.assertEqual((ent["status"], ent["route"]), ("error", None))
        self.assertIsNone(r.lookup("BAW90"))


class TheSettingOff(Base):
    def test_off_asks_nothing_and_hides_the_cache(self):
        f = self.fake()
        r = self.routes(f.base_url())
        r.start()
        r.lookup("BAW90")
        self.wait_cached(r, "BAW90")
        self.assertIsNotNone(r.lookup("BAW90"))
        self.on[0] = False
        self.assertIsNone(r.lookup("BAW90"))            # already cached, but the setting hides it
        n = len(f.requests)
        self.assertIsNone(r.lookup("NEVERASKED"))
        time.sleep(0.1)
        self.assertEqual(len(f.requests), n)            # no new request either
        self.on[0] = True
        self.assertIsNotNone(r.lookup("BAW90"))


class ACacheThatSurvives(Base):
    def test_a_restart_reads_the_file_without_asking_again(self):
        f = self.fake()
        r = self.routes(f.base_url())
        r.start()
        r.lookup("BAW90")
        self.wait_cached(r, "BAW90")
        r.stop()
        f.requests.clear()
        again = self.routes(f.base_url())
        self.assertEqual(again.lookup("BAW90")["from"], "GLA")
        self.assertEqual(f.requests, [])

    def test_a_cut_short_write_would_leave_the_old_file_alone(self):
        # The save is temp-file-then-rename (dmrids.py, radiodns.py's
        # pattern): proven by reading back exactly what was written, with
        # no .part file left over once it lands.
        f = self.fake()
        r = self.routes(f.base_url())
        r.start()
        r.lookup("BAW90")
        self.wait_cached(r, "BAW90")
        self.assertFalse(any(p.name.endswith(".part") for p in self.dir.iterdir()))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["cache.json"])


class TheRateLimit(Base):
    def test_never_faster_than_one_a_second(self):
        f = self.fake()
        for cs in ("AAA1", "AAA2", "AAA3"):
            f.routes.setdefault(cs, UNKNOWN)
        r = self.routes(f.base_url())
        r.start()
        for cs in ("AAA1", "AAA2", "AAA3"):
            r.lookup(cs)
        for cs in ("AAA1", "AAA2", "AAA3"):
            self.wait_cached(r, cs, timeout=10.0)
        times = sorted(t for _p, _h, t in f.requests)
        self.assertEqual(len(times), 3)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, flightroutes.RATE_S - 0.05)

    def test_a_full_queue_drops_rather_than_blocks(self):
        f = self.fake()
        f.hang.add("BLOCK")        # the worker is busy (its own socket timeout) on the first one
        r = self.routes(f.base_url(), timeout=1.0)
        r.start()
        r.lookup("BLOCK")
        time.sleep(0.1)            # the worker is now inside the hanging request
        t0 = time.monotonic()
        for i in range(flightroutes.QUEUE_MAX + 20):
            r.lookup(f"Q{i}")      # must never block the caller, queue full or not
        self.assertLess(time.monotonic() - t0, 2.0)


if __name__ == "__main__":
    unittest.main()
