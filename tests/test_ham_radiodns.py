"""DAB logos from RadioDNS (ohsradio/radiodns.py, 24/10/2026), against a
fake DNS server and a fake broadcaster on local sockets: nothing here can
reach the real internet (scratch_home.py points the resolver at a closed
port too, for anything that forgets).

- **A full fill:** a stored station list's services are named, their
  CNAME and SRV asked for, the broadcaster's SI.xml fetched once for all
  of its services, and each one's square and wide logo (nearest 128x128
  and 320x240) put in the store as `radiodns`; a service RadioDNS does not
  know gets none. The requests carry only "OpenHamShack-Radio/<version>"
  and no cookie, though the broadcaster sets one.
- **The air wins:** a variant heard over the air is never fetched, and one
  heard after a fetch replaces it.
- **Kept:** the fetched logos and the record of what was looked at survive
  a restart, so the next run within the week asks nothing.
- **Offline:** a resolver that never answers costs one bounded wait, then
  backoff, and the next run asks nothing; with no answer at all nothing in
  the store changes.
- **Backoff** doubles per host to its cap, and a failing broadcaster backs
  off without stopping the others.
- **The setting off:** no query and no request at all, and the fetched
  logos are hidden; on again, they are back.
- **Over the API:** api/dab/stations carries `logoSource` and the logo's URL
  under the request's prefix, api/dab/logos serves the fetched picture, and
  api/set radioDnsLogos=false takes both away.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import http.server
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ohscore.dabpics import DabPictures
from ohsradio import radiodns
from ohsradio.radiodns import RadioDns

PNG_128 = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 128, 128) + bytes(20)
PNG_320 = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 320, 240) + bytes(30)
PNG_AIR = b"\x89PNG\r\n\x1a\n" + bytes(40)

# The box's real Ayr ensemble (11B, C19B), two of its services: Clyde 1
# Ayrshire is in Planet Radio's SPI, Now Ayrshire in nobody's.
STATIONS = [{"block": "11B", "id": "C19B", "label": "Ayr", "country": "GB", "ecc": "E1", "services": [
    {"sid": "CCB1", "label": "Clyde 1 Ayrshire", "kind": "dab+"},
    {"sid": "C24A", "label": "Now Ayrshire", "kind": "dab+"}]},
    # The same service again in another ensemble, and an older list's
    # entry with no ECC (only the country): looked up once, and by the
    # country's ECC.
    {"block": "11C", "id": "C182", "label": "Glasgow", "country": "GB", "services": [
        {"sid": "CCB1", "label": "Clyde 1 Ayrshire", "kind": "dab+"},
        {"sid": "C3A4", "label": "Clyde 1", "kind": "dab+"}]}]


def si_xml(port):
    base = f"http://localhost:{port}/cdn"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<serviceInformation xmlns="http://www.worlddab.org/schemas/spi/31">
 <services>
  <serviceProvider><mediaDescription>
   <multimedia width="128" height="128" mimeValue="image/png" url="{base}/provider.png"/>
  </mediaDescription></serviceProvider>
  <service>
   <mediumName>Clyde 1 Ayrshire</mediumName>
   <mediaDescription><multimedia type="logo_colour_square" url="{base}/1077-32.png"/></mediaDescription>
   <mediaDescription><multimedia type="logo_colour_rectangle" url="{base}/1077-112.png"/></mediaDescription>
   <mediaDescription><multimedia width="128" height="128" mimeValue="image/png" type="logo_unrestricted"
     url="{base}/1077-128.png?ver=1"/></mediaDescription>
   <mediaDescription><multimedia width="320" height="240" mimeValue="image/png" type="logo_unrestricted"
     url="{base}/1077-320.png?ver=1"/></mediaDescription>
   <mediaDescription><multimedia width="600" height="600" mimeValue="image/png" type="logo_unrestricted"
     url="{base}/1077-600.png"/></mediaDescription>
   <bearer id="fm:ce1.ccb1.09670" cost="30"/>
   <bearer id="dab:ce1.c19b.ccb1.0" cost="40"/>
  </service>
  <service>
   <mediumName>Clyde 1</mediumName>
   <mediaDescription><multimedia width="128" height="128" type="logo_unrestricted" url="{base}/c1-128.png"/>
   </mediaDescription>
   <bearer id="dab:ce1.c181.c3a4.0" cost="40"/>
  </service>
 </services>
</serviceInformation>""".encode()


# ---------------------------------------------------------------- fakes
def _name(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.rstrip(".").split(".")) + b"\x00"


class FakeDns:
    """A UDP resolver answering from `records`: {(name, type): [rdata]},
    a CNAME's rdata a name, an SRV's (priority, weight, port, target).
    A name it has nothing for is NXDOMAIN. `silent` answers nothing."""

    def __init__(self, records, silent=False):
        self.records = records
        self.silent = silent
        self.asked = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.addr = self.sock.getsockname()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(2)
        self.sock.close()

    def _serve(self):
        while not self.stop.is_set():
            try:
                q, peer = self.sock.recvfrom(512)
            except OSError:
                continue
            off, labels = 12, []
            while q[off]:
                labels.append(q[off + 1:off + 1 + q[off]].decode())
                off += 1 + q[off]
            qtype = struct.unpack(">H", q[off + 1:off + 3])[0]
            name = ".".join(labels)
            self.asked.append((name, qtype))
            if self.silent:
                continue
            got = self.records.get((name, qtype))
            if got is None:
                self.sock.sendto(q[:2] + struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0) + q[12:off + 5], peer)
                continue
            ans = b""
            for r in got:
                rdata = _name(r) if qtype == radiodns.T_CNAME else struct.pack(">HHH", *r[:3]) + _name(r[3])
                ans += b"\xc0\x0c" + struct.pack(">HHIH", qtype, 1, 300, len(rdata)) + rdata
            self.sock.sendto(q[:2] + struct.pack(">HHHHH", 0x8180, 1, len(got), 0, 0) + q[12:off + 5] + ans, peer)


class FakeBroadcaster:
    """The broadcaster's SPI server and logo host in one, on localhost.
    `fail` maps a path to a status to answer it with."""

    def __init__(self):
        self.requests = []
        self.fail = {}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append((self.path, dict(self.headers)))
                path = self.path.split("?")[0]
                code = outer.fail.get(path)
                if code:
                    self.send_response(code)
                    self.end_headers()
                    return
                body = {"/radiodns/spi/3.1/SI.xml": si_xml(outer.port), "/cdn/1077-128.png": PNG_128,
                        "/cdn/1077-320.png": PNG_320, "/cdn/c1-128.png": PNG_128}.get(path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                # A cookie the fetcher must never send back.
                self.send_header("Set-Cookie", "track=abc123; Path=/")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def paths(self):
        return [p for p, _ in self.requests]


def records(port):
    return {("0.ccb1.c19b.ce1.dab.radiodns.org", radiodns.T_CNAME): ["planet.test"],
            ("0.c3a4.c182.ce1.dab.radiodns.org", radiodns.T_CNAME): ["planet.test"],
            ("_radiospi._tcp.planet.test", radiodns.T_SRV): [(0, 100, port, "localhost")]}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.web = FakeBroadcaster()
        self.addCleanup(self.web.close)
        self.dns = FakeDns(records(self.web.port))
        self.addCleanup(self.dns.close)
        self.clock = Clock()
        self.on = True
        self.pics = DabPictures(Path(self.tmp.name), clock=self.clock)

    def fetcher(self, pics=None, dns=None):
        dns = dns or self.dns
        return RadioDns(pics or self.pics, lambda: STATIONS, lambda: self.on, clock=self.clock,
                        resolvers=lambda: [dns.addr], pause_s=0)


class Names(unittest.TestCase):
    def test_a_service_is_named_from_its_ensemble_and_the_ecc(self):
        self.assertEqual(radiodns.fqdn("C224", "CE15", "E1", "GB"), "0.c224.ce15.ce1.dab.radiodns.org")
        # An older list: the country and the SId's first nibble give the ECC.
        self.assertEqual(radiodns.fqdn("C224", "CE15", None, "GB"), "0.c224.ce15.ce1.dab.radiodns.org")
        self.assertEqual(radiodns.fqdn("D224", "DE15", None, "DE"), "0.d224.de15.de0.dab.radiodns.org")
        self.assertEqual(radiodns.bearer("0.c224.ce15.ce1.dab.radiodns.org"), "dab:ce1.ce15.c224.0")
        # A data service's 32-bit SId, an unknown country, a junk id: no name.
        self.assertIsNone(radiodns.fqdn("E1C00001", "CE15", "E1", "GB"))
        self.assertIsNone(radiodns.fqdn("C224", "CE15", None, "XX"))
        self.assertIsNone(radiodns.fqdn("C2;4", "CE15", "E1", "GB"))

    def test_logos_are_chosen_as_over_the_air(self):
        doc = radiodns.parse_si(si_xml(1))
        pics = radiodns.find_service(doc, "dab:ce1.c19b.ccb1.0")
        got = {v: (p["width"], p["height"]) for v, p in radiodns.choose(pics).items()}
        self.assertEqual(got, {"square": (128, 128), "wide": (320, 240)})
        # Listed under another ensemble's EId: found by GCC and SId.
        self.assertIsNotNone(radiodns.find_service(doc, "dab:ce1.c182.c3a4.0"))
        self.assertIsNone(radiodns.find_service(doc, "dab:ce1.c19b.c24a.0"))

    def test_a_document_with_entities_is_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><serviceInformation>&a;</serviceInformation>'
        with self.assertRaises(ValueError):
            radiodns.parse_si(bomb)

    def test_the_user_agent_says_the_program_and_version_only(self):
        version = radiodns.VERSION_FILE.read_text().strip()
        self.assertEqual(radiodns.user_agent(), f"OpenHamShack-Radio/{version}")


class AFullFill(Base):
    def test_every_known_service_gets_its_logos_and_nothing_personal_goes_out(self):
        counts = self.fetcher().run_once()
        self.assertEqual((counts["due"], counts["found"], counts["stopped"]), (3, 2, None), counts)
        self.assertEqual(self.pics.logo("CCB1", "square"), (PNG_128, "image/png"))
        self.assertEqual(self.pics.logo("CCB1", "wide"), (PNG_320, "image/png"))
        self.assertEqual(self.pics.logo_paths("CCB1"), {
            "logoPath": "api/dab/logos/CCB1", "logoSource": "radiodns",
            "logoWidePath": "api/dab/logos/CCB1?variant=wide", "logoWideSource": "radiodns"})
        # Clyde 1 (listed under another EId) has a square one only.
        self.assertEqual(self.pics.logo_paths("C3A4"), {"logoPath": "api/dab/logos/C3A4", "logoSource": "radiodns"})
        # Now Ayrshire: RadioDNS does not know it.
        self.assertFalse(self.pics.has_logo("C24A"))
        self.assertIn(("0.c24a.c19b.ce1.dab.radiodns.org", radiodns.T_CNAME), self.dns.asked)
        # One SI.xml for the broadcaster's services, the chosen pictures, nothing else.
        self.assertEqual(sorted(self.web.paths()), ["/cdn/1077-128.png?ver=1", "/cdn/1077-320.png?ver=1",
                                                    "/cdn/c1-128.png", "/radiodns/spi/3.1/SI.xml"])
        version = radiodns.VERSION_FILE.read_text().strip()
        for _, headers in self.web.requests:
            lower = {k.lower(): v for k, v in headers.items()}
            self.assertEqual(lower["user-agent"], f"OpenHamShack-Radio/{version}")
            self.assertNotIn("cookie", lower)
            self.assertEqual(set(lower) - {"user-agent", "host", "accept-encoding", "connection"}, set(), lower)
        # A session's meta carries the source too.
        meta = self.pics.decorate({"services": [{"sid": "CCB1"}]})
        self.assertEqual(meta["services"][0]["logoSource"], "radiodns")

    def test_kept_across_a_restart_and_not_asked_again_within_the_week(self):
        self.fetcher().run_once()
        asked, fetched = len(self.dns.asked), len(self.web.requests)
        pics = DabPictures(Path(self.tmp.name), clock=self.clock)
        self.assertEqual(pics.logo("CCB1", "square"), (PNG_128, "image/png"))
        self.assertEqual(pics.logo_paths("CCB1")["logoWideSource"], "radiodns")
        again = self.fetcher(pics)
        self.assertEqual(again.due(), [])
        again.run_once()
        self.assertEqual((len(self.dns.asked), len(self.web.requests)), (asked, fetched))
        # A week on, it looks again; the pictures' URLs are the same, so
        # only the document is fetched.
        self.clock.t += radiodns.REFRESH_S + 1
        again.run_once()
        self.assertEqual(self.web.paths()[fetched:], ["/radiodns/spi/3.1/SI.xml"])


class TheAirWins(Base):
    def test_a_broadcast_variant_is_never_fetched_and_replaces_a_fetched_one(self):
        self.pics.take({"type": "frame", "frame": "logo", "t": 1.0, "raw": PNG_AIR,
                        "fields": {"sid": "CCB1", "variant": "square", "contentType": "image/png"}})
        self.fetcher().run_once()
        self.assertNotIn("/cdn/1077-128.png?ver=1", self.web.paths())
        self.assertEqual(self.pics.logo("CCB1", "square"), (PNG_AIR, "image/png"))
        self.assertEqual(self.pics.logo_paths("CCB1"), {
            "logoPath": "api/dab/logos/CCB1", "logoSource": "broadcast",
            "logoWidePath": "api/dab/logos/CCB1?variant=wide", "logoWideSource": "radiodns"})
        # The wide one now comes over the air: it replaces the fetched one,
        # whose file goes.
        fetched_file = Path(self.tmp.name) / "dab" / "CCB1-wide-radiodns.png"
        self.assertTrue(fetched_file.is_file())
        self.pics.take({"type": "frame", "frame": "logo", "t": 2.0, "raw": PNG_AIR + b"w",
                        "fields": {"sid": "CCB1", "variant": "wide", "contentType": "image/png"}})
        self.assertEqual(self.pics.logo("CCB1", "wide"), (PNG_AIR + b"w", "image/png"))
        self.assertEqual(self.pics.logo_paths("CCB1")["logoWideSource"], "broadcast")
        self.assertFalse(fetched_file.exists())
        # And a fetched one can never go back over it.
        self.assertFalse(self.pics.take_fetched("CCB1", "wide", PNG_320, "image/png", 320, 240, "http://x/y.png"))


class Offline(Base):
    def test_a_resolver_that_never_answers_costs_one_bounded_wait_then_backoff(self):
        dead = FakeDns({}, silent=True)
        self.addCleanup(dead.close)
        f = self.fetcher(dns=dead)
        t0 = time.monotonic()
        counts = f.run_once()
        took = time.monotonic() - t0
        self.assertEqual(counts["stopped"], "dns")
        self.assertLess(took, radiodns.DNS_TIMEOUT_S + 1.5, "one query's timeout, not one per service")
        self.assertEqual(len(dead.asked), 1)
        self.assertEqual(self.pics.logos, {})
        self.assertEqual(self.web.requests, [])
        # The next wake within the backoff asks nothing at all.
        self.assertEqual(f.run_once()["stopped"], "backoff")
        self.assertEqual(len(dead.asked), 1)

    def test_no_route_is_quick_and_changes_nothing(self):
        # scratch_home.py's resolver: a closed port, refused at once.
        f = RadioDns(self.pics, lambda: STATIONS, lambda: True, clock=self.clock, pause_s=0)
        t0 = time.monotonic()
        self.assertEqual(f.run_once()["stopped"], "dns")
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(self.pics.logo_paths("CCB1"), {})

    def test_starting_the_thread_waits_before_any_traffic(self):
        f = self.fetcher()
        t0 = time.monotonic()
        f.start()
        self.addCleanup(f.stop)
        self.assertLess(time.monotonic() - t0, 0.1)
        time.sleep(0.3)
        self.assertEqual((self.dns.asked, self.web.requests), ([], []))
        self.assertGreater(radiodns.STARTUP_DELAY_S, 30)


class Backoff(Base):
    def test_backoff_doubles_per_host_to_its_cap(self):
        f = self.fetcher()
        waits = []
        for _ in range(12):
            f._failed("dns", "timeout")
            waits.append(f.hosts["dns"]["until"] - self.clock.t)
        self.assertEqual(waits[:3], [radiodns.BACKOFF_BASE_S, 2 * radiodns.BACKOFF_BASE_S,
                                     4 * radiodns.BACKOFF_BASE_S])
        self.assertEqual(waits[-1], radiodns.BACKOFF_MAX_S)
        self.assertTrue(f.backing_off("dns"))
        self.assertFalse(f.backing_off("planet.test"))

    def test_a_failing_broadcaster_backs_off_and_is_tried_again_later(self):
        self.web.fail["/radiodns/spi/3.1/SI.xml"] = 503
        f = self.fetcher()
        f.run_once()
        key = f"localhost:{self.web.port}"
        self.assertTrue(f.backing_off(key))
        self.assertFalse(f.backing_off("dns"))
        self.assertEqual(self.web.paths(), ["/radiodns/spi/3.1/SI.xml"])
        # Its services were not marked looked-at; Now Ayrshire (a definite
        # "unknown") was.
        self.assertEqual(sorted(sid for sid, _ in f.due()), ["C3A4", "CCB1"])
        f.run_once()
        self.assertEqual(len(self.web.requests), 1, "nothing asked while backing off")
        del self.web.fail["/radiodns/spi/3.1/SI.xml"]
        self.clock.t += radiodns.BACKOFF_BASE_S + 1
        f.run_once()
        self.assertTrue(self.pics.has_logo("CCB1"))
        self.assertFalse(f.backing_off(key))


class TheSettingOff(Base):
    def test_off_means_no_traffic_and_no_fetched_logos(self):
        self.on = False
        f = self.fetcher()
        self.assertEqual(f.run_once()["stopped"], "off")
        self.assertEqual((self.dns.asked, self.web.requests), ([], []))
        # Fetched while on, hidden while off, back when on again.
        self.on = True
        f.run_once()
        self.pics.show_fetched = lambda: self.on
        self.assertTrue(self.pics.has_logo("CCB1"))
        self.on = False
        self.assertEqual((self.pics.has_logo("CCB1"), self.pics.logo_paths("CCB1"), self.pics.logo("CCB1")),
                         (False, {}, None))
        self.on = True
        self.assertEqual(self.pics.logo("CCB1"), (PNG_128, "image/png"))


class OverTheApi(Base):
    def test_the_station_list_and_the_logo_route_and_the_setting(self):
        from ohscore.server import shack
        from ohscore.server.app import Server
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.radio import Radio
        import test_server
        data = Path(self.tmp.name) / "radio"
        (data / "bandscan").mkdir(parents=True)
        (data / "bandscan" / "dab.json").write_text(json.dumps({"scannedAt": self.clock.t, "status": "ok",
                                                                "ensembles": STATIONS}))
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI"}
        audio = StreamAudio(realtime=False)
        radio = Radio(cfg, persist=False, data_dir=data, audio=audio)
        self.assertIsNone(radio.radiodns.thread, "a test's radio starts no fetcher")
        self.assertIs(radio.st["radioDnsLogos"], True)
        radio.radiodns.resolvers = lambda: [self.dns.addr]
        radio.radiodns.pause_s = 0
        self.assertEqual(radio.radiodns.run_once()["found"], 2)
        srv = Server(radio, ham_server.info("9.9.9"), audio, secret=test_server.SECRET)
        port = srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(srv.shutdown)

        def req(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            c.request(method, path, json.dumps(body) if body is not None else None,
                      {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: test_server.SECRET,
                       "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": "control",
                       "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device",
                       "X-Forwarded-Prefix": "/apps/radio"})
            r = c.getresponse()
            raw = r.read()
            c.close()
            return r.status, raw

        s, raw = req("GET", "/api/dab/stations")
        svc = {x["sid"]: x for e in json.loads(raw)["ensembles"] for x in e["services"]}
        self.assertEqual((svc["CCB1"]["logoSource"], svc["CCB1"]["logoUrl"], svc["CCB1"]["logoWideSource"]),
                         ("radiodns", "/apps/radio/api/dab/logos/CCB1", "radiodns"))
        self.assertNotIn("logoUrl", svc["C24A"])
        self.assertEqual(req("GET", "/api/dab/logos/CCB1"), (200, PNG_128))
        s, raw = req("POST", "/api/set", {"changes": {"radioDnsLogos": False}})
        self.assertEqual(s, 200, raw)
        deadline = time.monotonic() + 10
        while radio.st["radioDnsLogos"] and time.monotonic() < deadline:
            time.sleep(0.05)
        svc = {x["sid"]: x for e in json.loads(req("GET", "/api/dab/stations")[1])["ensembles"]
               for x in e["services"]}
        self.assertNotIn("logoUrl", svc["CCB1"])
        self.assertEqual(req("GET", "/api/dab/logos/CCB1")[0], 404)
        asked = len(self.dns.asked)
        self.clock.t += radiodns.REFRESH_S + 1
        radio.radiodns.run_once()
        self.assertEqual(len(self.dns.asked), asked, "off: nothing asked")


if __name__ == "__main__":
    unittest.main()
