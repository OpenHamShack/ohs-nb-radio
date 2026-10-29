"""APRS stations on a map (29/10/2026): Radio's APRS receive, its station
table, and their routes.

On the RSPdx-shaped simulator (listen_helpers) with packets on 144.800 MHz
(ohsradio/devices/simaprs.py), each an AX.25 frame keyed as AFSK by
shack_packet's own modulator and FM-modulated, so everything below goes
through the real channeliser, demodulator and parser and is checked over
the HTTP API:

- **Published packets decode:** a plain position, one heard through a
  digipeater, Mic-E, a status, a weather report, a message (and its ack,
  which is not one), an object and an item - the APRS specification's
  examples as shack_packet's corpus has them, checked there against
  direwolf's decode_aprs - each in api/aprs/stations[/{call}] and
  api/aprs/messages with the values the specification says.
- **The session** holds the receiver on 144.800 FM and ends with the last
  client, its lease, or its presence, the dial, mode and repeater offset
  put back.
- **24 hours on disk:** a restart keeps the table; a day-old station goes.
- The simulator's own stations around Ayr come in as what they are.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ohscore import sdr
from ohscore.engine import ReceiverHeld, TxRefused
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import aprs as aprsmod
from ohsradio import server as ham_server
from ohsradio.devices import simaprs
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, make_listener
from test_server import SECRET

HOME = 145_500_000.0

# shack_packet's APRS corpus (ohs-libs python/shack_packet/tests/test_aprs.py,
# GPL-3.0-or-later like this repo), every line checked there against
# direwolf's decode_aprs; the Mic-E one is the APRS specification's own.
POSITION = "GM0ABC-9>APDW17,WIDE1-1,WIDE2-1:!5537.14N/00420.83W>Test position"
DIGIPEATED = "MM0XYZ>APDW17,GB7AY*,WIDE2-1:@092345z5537.14N/00420.83W-House"
MIC_E = 'M0ABC-9>TQPX2X,WIDE1-1:`(_fn"Oj/]"4-}Testing mic-E'
STATUS = "2E0TST-7>APDW12:>Monitoring 144.800 in Ayrshire"
WEATHER = "G0WX-13>APDW17:@092345z5537.14N/00420.83W_180/010g015t045r000p010P010h50b10132"
MESSAGE = "GM0ABC>APDW17::GM7XYZ   :Are you around this evening?{12"
ACK = "GM7XYZ>APDW17::GM0ABC   :ack12"
OBJECT = "GM0ABC>APDW17:;LEADHILLS*092345z5525.00N/00337.00WrSOTA GM/SS-176"
ITEM = "GM0ABC>APDW17:)AID#2!5537.14N/00420.83WA"
KILLED = "GM0ABC>APDW17:;LEADHILLS_092345z5525.00N/00337.00WrSOTA GM/SS-176"
CORPUS = [POSITION, DIGIPEATED, MIC_E, STATUS, WEATHER, MESSAGE, ACK, OBJECT, ITEM]
CALLS = {"GM0ABC-9", "MM0XYZ", "M0ABC-9", "2E0TST-7", "G0WX-13", "GM0ABC", "GM7XYZ", "LEADHILLS", "AID#2"}


def wait(cond, timeout=90.0, radio=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if radio is not None:
            radio.heartbeat()
        if cond():
            return True
        time.sleep(0.05)
    return False


def cfg_for(**over):
    return {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
            "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
            "locator": "IO75RL", **over}


class Served:
    """A Radio on the simulator with `air` on it, behind the HTTP server."""

    def __init__(self, test, data_dir, air):
        cfg = cfg_for()
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=data_dir, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [air] if air is not None else []))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        test.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def stations(self, query=""):
        s, a = self.req("GET", "/api/aprs/stations" + query, level="view")
        assert s == 200, a
        return a

    def shutdown(self):
        self.srv.shutdown()


@unittest.skipUnless(simaprs.available(), "no shack_packet wheel for this machine")
class PublishedPackets(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.air = simaprs.AprsAir(beacons=CORPUS)
        self.box = Served(self, self.dir, self.air)
        self.addCleanup(lambda: self.box and self.box.shutdown())

    def heard_everything(self):
        got = {v["call"] for v in self.box.stations()["stations"]}
        return CALLS <= got and self.box.req("GET", "/api/aprs/messages", level="view")[1]

    def test_each_kind_of_packet_decodes_off_the_air(self):
        box = self.box
        feed = box.radio.subscribe("aprs", 1024)
        s, a = box.req("POST", "/api/aprs/session", {"client": "tv-lounge"}, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"), a)
        s, a = box.req("POST", "/api/aprs/session", {"client": "tv-lounge"})
        self.assertEqual((s, a["state"], a["leaseS"], a["lingerS"]), (200, "running", 30.0, 0.0), a)
        st = box.req("GET", "/api/status", level="view")[1]
        own = st["rxOwner"]
        self.assertEqual((own["by"], own["freqHz"]), ("aprs", 144_800_000.0))
        self.assertEqual(own["prior"], {"vfo": HOME, "mode": "fm", "rptOffsetHz": 600_000.0})
        self.assertEqual((st["vfo"], st["mode"], st["aprs"]["state"]), (144_800_000.0, "fm", "running"))
        self.assertTrue(wait(self.heard_everything, radio=box.radio), box.stations())
        # The receiver's centre beside the channel, never on it.
        self.assertEqual(box.radio.centre, aprsmod.CENTRE_HZ)

        got = {v["call"]: v for v in box.stations()["stations"]}
        for v in got.values():
            self.assertEqual(v["source"], "rf")
            self.assertTrue(set(v) >= {"call", "kind", "symbol", "lat", "lon", "courseDeg", "speedKmh", "altM",
                                       "comment", "status", "lastHeard", "heardDirect", "via", "packets", "wx"}, v)
        # A plain position: 55 37.14 N, 4 20.83 W, a car.
        car = got["GM0ABC-9"]
        self.assertAlmostEqual(car["lat"], 55.619, places=5)
        self.assertAlmostEqual(car["lon"], -4.347167, places=5)
        self.assertEqual((car["symbol"], car["kind"], car["comment"], car["heardDirect"], car["via"]),
                         ({"table": "/", "code": ">"}, "mobile", "Test position", True, ["WIDE1-1", "WIDE2-1"]))
        self.assertIsNone(car["wx"])
        # Heard only through GB7AY: not direct.
        house = got["MM0XYZ"]
        self.assertEqual((house["kind"], house["comment"], house["heardDirect"], house["via"]),
                         ("station", "House", False, ["GB7AY*", "WIDE2-1"]))
        # Mic-E: half the position in the destination address.
        jeep = got["M0ABC-9"]
        self.assertAlmostEqual(jeep["lat"], 41.138, places=4)
        self.assertAlmostEqual(jeep["lon"], -12.129, places=4)
        self.assertEqual((jeep["courseDeg"], jeep["kind"], jeep["symbol"], jeep["comment"]),
                         (251.0, "mobile", {"table": "/", "code": "j"}, "Testing mic-E"))
        self.assertAlmostEqual(jeep["speedKmh"], 37.0, delta=0.1)       # 20 knots
        self.assertAlmostEqual(jeep["altM"], 22.0, delta=0.5)
        # A status, and no position.
        self.assertEqual((got["2E0TST-7"]["status"], got["2E0TST-7"]["lat"]),
                         ("Monitoring 144.800 in Ayrshire", None))
        # Weather, in the units a person reads: wind 10 mph, gust 15 mph,
        # 45 F, 50 %, 1013.2 hPa.
        wx = got["G0WX-13"]
        self.assertEqual(wx["kind"], "wx")
        self.assertEqual((wx["wx"]["windDirDeg"], wx["wx"]["windKmh"], wx["wx"]["gustKmh"], wx["wx"]["tempC"],
                          wx["wx"]["humidity"], wx["wx"]["pressureHpa"], wx["wx"]["rain1hMm"]),
                         (180.0, 16.1, 24.1, 7.2, 50.0, 1013.2, 0.0))
        self.assertIsNone(wx["courseDeg"])
        # An object and an item, placed by GM0ABC, which is listed too.
        obj = got["LEADHILLS"]
        self.assertEqual((obj["kind"], obj["owner"], obj["symbol"], obj["comment"]),
                         ("object", "GM0ABC", {"table": "/", "code": "r"}, "SOTA GM/SS-176"))
        self.assertAlmostEqual(obj["lat"], 55 + 25 / 60, places=5)
        self.assertAlmostEqual(obj["lon"], -(3 + 37 / 60), places=5)
        self.assertEqual((got["AID#2"]["kind"], got["AID#2"]["owner"]), ("item", "GM0ABC"))
        self.assertIsNone(got["GM0ABC"]["lat"])
        self.assertGreaterEqual(got["GM0ABC"]["packets"], 3)

        # The message once, however often it is heard; the ack is not one.
        s, msgs = box.req("GET", "/api/aprs/messages", level="view")
        self.assertEqual(s, 200)
        self.assertEqual([{k: m[k] for k in ("from", "to", "text", "id")} for m in msgs],
                         [{"from": "GM0ABC", "to": "GM7XYZ", "text": "Are you around this evening?", "id": "12"}])
        self.assertTrue(msgs[0]["t"].endswith("Z"))

        # One station, with its track and its packets as heard.
        s, one = box.req("GET", "/api/aprs/stations/m0abc-9", level="view")
        self.assertEqual((s, one["call"]), (200, "M0ABC-9"))
        self.assertEqual(set(one["track"][0]), {"t", "lat", "lon"})
        self.assertEqual(one["recent"][0]["raw"], MIC_E)
        self.assertEqual(one["recent"][0]["text"], "Testing mic-E")
        s, e = box.req("GET", "/api/aprs/stations/G9NONE", level="view")
        self.assertEqual((s, e["code"]), (404, "unknown_station"))

        # Keeping up: by rev, and by age in seconds.
        a = box.stations()
        self.assertTrue(a["full"])
        self.assertEqual(a["session"]["state"], "running")
        heard = [v["lastHeardTs"] for v in a["stations"]]
        self.assertEqual(heard, sorted(heard, reverse=True))               # newest first
        self.assertEqual({v["call"] for v in box.stations("?sinceS=3600")["stations"]}, CALLS)
        s, e = box.req("GET", "/api/aprs/stations?sinceS=soon", level="view")
        self.assertEqual((s, e["code"]), (400, "bad_params"))
        rev = a["rev"]
        # The object killed: it goes from the map, and `since` says so.
        self.air.beacons = [simaprs.fixed(KILLED)]
        self.assertTrue(wait(lambda: "LEADHILLS" in box.stations(f"?since={rev}")["removed"], radio=box.radio))
        b = box.stations(f"?since={rev}")
        self.assertFalse(b["full"])
        self.assertTrue(all(v["rev"] > rev for v in b["stations"]))
        self.assertNotIn("LEADHILLS", {v["call"] for v in box.stations()["stations"]})

        # The feed: every packet, each station as it changed, the message, the session.
        items = feed.drain()
        kinds = {i["type"] for i in items}
        self.assertTrue({"session", "packet", "station", "message", "removed"} <= kinds, kinds)
        self.assertIn(STATUS, {i["raw"] for i in items if i["type"] == "packet"})
        self.assertEqual(sum(1 for i in items if i["type"] == "message"), 1)

        # A restart keeps the day's table: a map opened after it is not empty.
        s, a = box.req("DELETE", "/api/aprs/session?all=1")
        self.assertEqual((s, a["state"], a["why"]), (200, "idle", "stopped"))
        before = {v["call"]: (v["lat"], v["lon"], v["kind"]) for v in box.stations()["stations"]}
        box.shutdown()
        box.radio.stop()
        self.box = Served(self, self.dir, None)
        again = self.box
        self.assertEqual({v["call"]: (v["lat"], v["lon"], v["kind"]) for v in again.stations()["stations"]}, before)
        self.assertEqual(again.req("GET", "/api/aprs/stations/M0ABC-9", level="view")[1]["recent"][0]["text"],
                         "Testing mic-E")
        self.assertEqual(len(again.req("GET", "/api/aprs/messages", level="view")[1]), 1)

    def test_a_day_is_kept_and_no_more(self):
        # The table as a day of listening left it: one station two hours old,
        # one 25 hours old.
        box = self.box
        box.shutdown()
        box.radio.stop()
        now = time.time()
        path = Path(self.dir) / "aprs" / "stations.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        def entry(call, age):
            return {"call": call, "kind": "station", "symbol": {"table": "/", "code": "-"}, "lat": 55.5,
                    "lon": -4.6, "courseDeg": None, "speedKmh": None, "altM": None, "comment": "", "status": "",
                    "lastHeard": aprsmod._iso(now - age), "lastHeardTs": now - age, "heardDirect": True,
                    "via": [], "packets": 1, "source": "rf", "wx": None, "rev": 1}
        path.write_text(json.dumps({"schema": 1, "rev": 2, "stations": [entry("GM0OLD", 2 * 3600),
                                                                         entry("GM0GONE", 25 * 3600)],
                                    "tracks": {}, "recent": {},
                                    "messages": [[now - 25 * 3600, "GM0GONE", "GM4BRI", "stale", None],
                                                 [now - 3600, "GM0OLD", "GM4BRI", "hello", "1"]]}))
        self.box = Served(self, self.dir, None)
        a = self.box.stations()
        self.assertEqual([v["call"] for v in a["stations"]], ["GM0OLD"])
        self.assertEqual(self.box.stations("?sinceS=3600")["stations"], [])
        self.assertEqual([v["call"] for v in self.box.stations("?sinceS=10800")["stations"]], ["GM0OLD"])
        self.assertEqual([m["text"] for m in self.box.req("GET", "/api/aprs/messages", level="view")[1]], ["hello"])


@unittest.skipUnless(simaprs.available(), "no shack_packet wheel for this machine")
class TheSession(unittest.TestCase):
    def radio(self, **over):
        r, audio, dev = make_listener([], **cfg_for(**over))
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r

    def test_the_last_client_leaving_gives_the_receiver_back_at_once(self):
        r = self.radio()
        centre_before = r.centre
        r.aprs.join("tv-1")
        r.aprs.join("phone-2")
        r.aprs.leave("tv-1")
        r.aprs.tick()
        self.assertEqual(r.aprs.state, "running")              # phone-2 still looks
        r.aprs.leave("phone-2")
        self.assertTrue(wait(lambda: r.aprs.state == "idle", 10, radio=r))
        st = r.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"], st["rptOffsetHz"]), ({}, HOME, "fm", 600_000.0))
        self.assertEqual((st["aprs"]["state"], st["aprs"]["why"]), ("idle", "idle"))
        self.assertTrue(wait(lambda: r.centre == centre_before, 10, radio=r), (r.centre, centre_before))
        r.set(vfo=HOME + 25_000)                              # the operator's again

    def test_a_client_that_stops_renewing_lets_it_go(self):
        r = self.radio(mode="usb", vfo=144_300_000.0)
        with mock.patch.object(aprsmod, "CLIENT_LEASE_S", 0.3):
            r.aprs.join("tv-1")
            self.assertEqual((r.state()["vfo"], r.state()["mode"]), (144_800_000.0, "fm"))
            self.assertTrue(wait(lambda: r.aprs.state == "idle", 10, radio=r))
        st = r.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, 144_300_000.0, "usb"))

    def test_while_aprs_holds_the_receiver_tuning_keying_and_other_holders_are_refused(self):
        from ohscore.decoders import Refused
        r = self.radio(receive_only=False)
        r.aprs.join("tv-1")
        with self.assertRaises(ReceiverHeld) as e:
            r.set(vfo=HOME)
        self.assertIn("APRS", str(e.exception))
        with self.assertRaises(TxRefused) as e:
            r.ptt(True)
        self.assertIn("APRS", str(e.exception))
        self.assertFalse(r.state()["keyed"])
        if sdr.load() is not None:
            with self.assertRaises(Refused) as e:
                r.ais.join("tv-1")
            self.assertEqual((e.exception.code, str(e.exception)),
                             ("receiver_busy", "APRS has the receiver for the station map: stop APRS first"))
        r.aprs.end("stopped")
        self.assertEqual(r.state()["rxOwner"], {})

    def test_refusals_when_it_cannot_start(self):
        from ohscore.decoders import Refused
        r = self.radio()
        with self.assertRaises(Refused) as e:
            r.aprs.join("")
        self.assertEqual(e.exception.code, "bad_client")
        if sdr.load() is not None:
            r.decoders.start("rtty", HOME + 10_000, {})
            with self.assertRaises(Refused) as e:
                r.aprs.join("tv-1")
            self.assertEqual(e.exception.code, "span_pinned")
            self.assertIn("144.800 MHz", str(e.exception))
            r.aprs.join("tv-1", drop_sessions=True)
            self.assertEqual(r.decoders.background(), [])
            r.aprs.end("stopped")
        r.stop()
        with self.assertRaises(Refused) as e:
            r.aprs.join("tv-1")
        self.assertEqual(e.exception.code, "not_running")

    def test_the_radio_stopping_ends_it(self):
        r = self.radio()
        r.aprs.join("tv-1")
        r.stop()
        self.assertEqual((r.aprs.state, r.aprs.why), ("idle", "radio_stopped"))
        self.assertEqual((r.state()["vfo"], r.state()["mode"]), (HOME, "fm"))


try:
    from test_ham_presence import Base as PresenceBase
except Exception:  # noqa: BLE001 - its own imports need shack_sdr; skipped below without it
    PresenceBase = unittest.TestCase


@unittest.skipUnless(simaprs.available() and sdr.available() and PresenceBase is not unittest.TestCase,
                     "no shack_packet or shack_sdr wheel for this machine")
class WithPresence(PresenceBase):
    def test_goodbye_ends_the_aprs_map_at_once(self):
        self.following()
        self.fake.arrive("tv-lounge", ["aprs"])
        s, a = self.req("POST", "/api/aprs/session", {"client": "tv-lounge"})
        self.assertEqual((s, a["state"]), (200, "running"), a)
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "aprs")
        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        self.assertTrue(wait(lambda: self.radio.aprs.state == "idle", 5))
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, 145_500_000.0, "fm"))

    def test_presence_renews_the_map_for_a_present_client(self):
        self.following()
        self.fake.arrive("tv-lounge", ["aprs"])
        self.assertTrue(wait(lambda: self.status()["presence"]["clients"] == ["tv-lounge"]))
        with mock.patch.object(aprsmod, "CLIENT_LEASE_S", 0.3):
            self.req("POST", "/api/aprs/session", {"client": "tv-lounge"})
            self.req("POST", "/api/aprs/session", {"client": "old-tv"})
            self.assertTrue(wait(lambda: self.radio.aprs.view()["clients"] == 1, 5))
            time.sleep(1.0)
            self.assertEqual((self.radio.aprs.state, list(self.radio.aprs.clients)), ("running", ["tv-lounge"]))


@unittest.skipUnless(simaprs.available(), "no shack_packet wheel for this machine")
class TheSimulatedStations(unittest.TestCase):
    def test_the_stations_around_ayr_come_in_as_what_they_are(self):
        r, audio, dev = make_listener([simaprs.AprsAir()], **cfg_for())
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        r.aprs.join("tv-1")
        want = {"MB7SIM": "digi", "GM0SIM": "station", "GM0SIM-9": "mobile", "GM1SIM-7": "mobile",
                "GM2SIM-13": "wx", "AYRSHOW": "object"}
        self.assertTrue(wait(lambda: want.items() <= {v["call"]: v["kind"] for v in
                                                      r.aprs.table.view()["stations"]}.items(), radio=r),
                        r.aprs.table.view())
        got = {v["call"]: v for v in r.aprs.table.view()["stations"]}
        # The Mic-E car between Ayr and Prestwick at 30 knots.
        car = got["GM0SIM-9"]
        self.assertTrue(55.459 <= car["lat"] <= 55.506 and -4.616 <= car["lon"] <= -4.604, car)
        self.assertAlmostEqual(car["speedKmh"], 55.6, delta=0.1)
        self.assertEqual(got["GM2SIM-13"]["wx"]["windKmh"], 24.1)        # 15 mph, as sent
        self.assertEqual(got["GM0SIM"]["status"], "Listening on 144.800 in Ayr")


if __name__ == "__main__":
    unittest.main()
