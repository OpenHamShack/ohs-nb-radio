"""Ships on a map (28/10/2026): Radio's AIS session, the vessel table, and
their routes.

On the RSPdx-shaped simulator (listen_helpers) with simulated ships in the
Firth of Clyde (ohsradio/devices/simais.py), whose bursts shack_sdr's own
AIS transmitter keys, end to end:

- **A client opening the map starts AIS:** the receiver goes to 162.000
  MHz and says so (`rxOwner`), the ships come in with their names,
  positions, types and distance and bearing from the station, and each
  message's NMEA sentence goes out on the `ais` feed.
- **It stops when nobody looks:** after the last client leaves, or stops
  renewing, and the linger; the receiver comes back exactly as it was.
- **Refusals** with their sentences: tuning, keying or DAB while AIS holds
  the receiver; AIS while DAB does, while background decoders pin the
  span (unless told to stop them), with the radio stopped, with no name.
- **Gain and notches:** the operator's gain stands, the DAB notch is out.
- **The table:** merged message types, expiry after aisKeepMinutes,
  `since`, the track, and a restart that keeps it.
- **Over the API:** api/ais/session, api/ais/vessels[/{mmsi}], and the
  levels they need.
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
from ohscore.decoders import Refused
from ohscore.engine import ReceiverHeld, TxRefused
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import ais as aismod
from ohsradio import bcastgain, mapdata, notch
from ohsradio import server as ham_server
from ohsradio.devices import simais
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, make_listener
from test_server import SECRET

HOME = 145_500_000.0


def quick_fleet(level_db=-40.0):
    """The simulated fleet, every ship sending each second and its static
    data every other slot, so a test sees names within seconds."""
    ships = [simais.Ship(s.mmsi, s.name, s.kind, s.a, s.b, s.knots, ship_type=s.ship_type, status=s.status,
                         callsign=s.callsign, dims=s.dims, destination=s.destination, every_s=1.0, static_s=2.0,
                         phase_s=s.phase_s / 5) for s in simais.FLEET]
    return simais.AisFleet(ships, level_db=level_db)


class Damaged:
    """A ship whose every burst loses 2 ms in its middle, on channel A."""

    def __init__(self):
        self.made = {}

    def iq(self, t, rx_if):
        import numpy as np
        from shack_sdr import _native
        fs = 1.0 / float(t[1] - t[0])
        if fs not in self.made:
            z = np.frombuffer(_native.testsig_ais(
                [{"t": 0.01, "channel": "A", "fields": {"type": 1, "mmsi": 235777777, "lat": 33_300_000,
                                                         "lon": -2_940_000}, "level_db": -40.0}],
                rate=fs, duration_s=0.5, centre_hz=simais.CENTRE_HZ - rx_if), np.complex64).copy()
            mid = int(0.02 * fs)
            z[mid:mid + int(0.002 * fs)] = 0
            self.made[fs] = z
        z = self.made[fs]
        k = np.round(t * fs).astype(np.int64) % len(z)
        return z[k]


def has_ais() -> bool:
    m = sdr.load()
    return m is not None and any(e["id"] == "ais" for e in m.catalogue())


def wait(radio, cond, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        radio.heartbeat()
        if cond():
            return True
        time.sleep(0.02)
    return False


def named(radio, n=6):
    v = radio.ais.table.view()["vessels"]
    return len(v) >= n and all(x.get("name") for x in v) and \
        sum(1 for x in v if x.get("lat") is not None) >= n


@unittest.skipUnless(has_ais(), "no shack_sdr with AIS for this machine")
class OnTheSimulator(unittest.TestCase):
    def radio(self, stations=None, **over):
        cfg = {"vfo": HOME, "mode": "fm", "locator": "IO75RL", **over}
        r, audio, dev = make_listener([quick_fleet()] if stations is None else stations, **cfg)
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r

    def test_ships_come_in_while_a_client_has_the_map_open(self):
        r = self.radio()
        feed = r.subscribe("ais", 512)
        view = r.ais.join("tv-lounge")
        self.assertEqual((view["state"], view["clients"]), ("running", 1))
        st = r.state()
        own = st["rxOwner"]
        self.assertEqual((own["by"], own["session"], own["freqHz"]), ("ais", "ais", 162_000_000.0))
        self.assertEqual(own["prior"], {"vfo": HOME, "mode": "fm", "rptOffsetHz": 600_000.0,
                                        "rxGainMode": "slow_attack", "rxGain": 40.0, "sdrplayLna": 4})
        self.assertIn("AIS", own["text"])
        self.assertEqual(st["vfo"], 162_000_000.0)
        self.assertEqual(st["ais"]["state"], "running")
        self.assertTrue(wait(r, lambda: named(r)), r.ais.table.view())
        self.assertEqual(r.centre, 162_000_000.0)
        got = {v["mmsi"]: v for v in r.ais.table.view()["vessels"]}
        ferry = got[235999001]
        self.assertEqual((ferry["name"], ferry["callsign"], ferry["class"], ferry["shipType"],
                          ferry["shipTypeText"], ferry["destination"], ferry["length"], ferry["beam"]),
                         ("CLYDE SPIRIT", "MCLY1", "A", 60, "Passenger", "BRODICK", 90, 16))
        # Where the simulator put it, on its route between Ardrossan and Brodick.
        self.assertTrue(55.57 <= ferry["lat"] <= 55.64 and -5.13 <= ferry["lon"] <= -4.83, ferry)
        self.assertEqual(ferry["navStatusText"], "Under way using engine")
        self.assertEqual(ferry["speed"], 16.0)
        # Distance and bearing from IO75RL's centre.
        from ohscore.countries import distance_bearing, locator_position
        km, brg = distance_bearing(*locator_position("IO75RL"), ferry["lat"], ferry["lon"])
        self.assertAlmostEqual(ferry["distanceKm"], km, delta=0.05)
        self.assertAlmostEqual(ferry["bearingDeg"], brg, delta=0.2)
        self.assertEqual((got[235999004]["class"], got[235999004]["name"]), ("B", "SEA HAWK"))
        self.assertEqual((got[992359006]["class"], got[992359006]["name"]), ("aton", "LADY ISLE"))
        self.assertEqual(got[235999003]["navStatusText"], "Engaged in fishing")
        self.assertEqual(got[235999005]["navStatusText"], "Moored")
        for v in got.values():
            self.assertGreater(v["snrDb"], 10)
            self.assertIn(v["channel"], ("A", "B"))
        # The feed: each message's sentences, and each vessel as it changed.
        items = feed.drain()
        kinds = {i["type"] for i in items}
        self.assertTrue({"session", "nmea", "vessel"} <= kinds, kinds)
        nmea = [i for i in items if i["type"] == "nmea"]
        self.assertTrue(all(s.startswith("!AIVDM,") for i in nmea for s in i["sentences"]))
        self.assertEqual({i["channel"] for i in nmea}, {"A", "B"})
        view = r.ais.view()
        self.assertEqual(view["channelA"] + view["channelB"], view["frames"])
        self.assertGreater(view["frames"], 6)

    def test_damaged_bursts_are_counted(self):
        # A burst with its middle wiped out: its CRC fails on every slicer,
        # and the session's `damaged` says so (beta.13 read the counters
        # from the wrong key and always said 0).
        r = self.radio(stations=[quick_fleet(), Damaged()])
        r.ais.join("tv-1")
        self.assertTrue(wait(r, lambda: r.ais.view()["damaged"] > 0, 30), r.ais.view())
        self.assertNotIn(235777777, {v["mmsi"] for v in r.ais.table.view()["vessels"]})
        self.assertIn("implausible", r.ais.view())

    def test_it_stops_after_the_last_client_and_gives_the_receiver_back(self):
        r = self.radio()
        centre_before = r.centre
        with mock.patch.object(aismod, "LINGER_S", 0.5):
            r.ais.join("tv-1")
            r.ais.join("phone-2")
            r.ais.leave("tv-1")
            time.sleep(0.8)
            r.ais.tick()
            self.assertEqual(r.ais.state, "running")         # phone-2 still looks
            r.ais.leave("phone-2")
            self.assertIsNotNone(r.ais.view()["endsInS"])
            self.assertTrue(wait(r, lambda: r.ais.state == "idle", 10))
        st = r.state()
        self.assertEqual(st["rxOwner"], {})
        self.assertEqual((st["vfo"], st["mode"], st["rptOffsetHz"]), (HOME, "fm", 600_000.0))
        self.assertTrue(wait(r, lambda: r.centre == centre_before, 10), (r.centre, centre_before))
        self.assertEqual((st["ais"]["state"], st["ais"]["why"]), ("idle", "idle"))
        r.set(vfo=HOME + 25_000)                              # the operator's again

    def test_a_client_that_stops_renewing_lets_it_go(self):
        r = self.radio()
        with mock.patch.object(aismod, "CLIENT_LEASE_S", 0.3), mock.patch.object(aismod, "LINGER_S", 0.3):
            r.ais.join("tv-1")
            self.assertTrue(wait(r, lambda: r.ais.state == "idle", 10))
        self.assertEqual(r.state()["rxOwner"], {})

    def test_while_ais_holds_the_receiver_tuning_keying_and_dab_are_refused(self):
        r = self.radio(receive_only=False)
        r.ais.join("tv-1")
        with self.assertRaises(ReceiverHeld) as e:
            r.set(vfo=HOME)
        self.assertIn("AIS", str(e.exception))
        with self.assertRaises(TxRefused) as e:
            r.ptt(True)
        self.assertIn("AIS", str(e.exception))
        with self.assertRaises(Refused) as e:
            r.decoders.start("dab", 222_064_000.0, {"service": "C221"})
        self.assertEqual(e.exception.code, "receiver_busy")
        self.assertEqual(str(e.exception), "AIS has the receiver for the ship map: stop AIS first")
        r.ais.end("stopped")
        self.assertEqual(r.state()["rxOwner"], {})
        r.set(vfo=HOME + 12_500)

    def test_refusals_when_it_cannot_start(self):
        r = self.radio()
        with self.assertRaises(Refused) as e:
            r.ais.join("")
        self.assertEqual(e.exception.code, "bad_client")
        # Background decoders pin the span: refused, unless told to stop them.
        r.decoders.start("rtty", HOME + 10_000, {})
        with self.assertRaises(Refused) as e:
            r.ais.join("tv-1")
        self.assertEqual(e.exception.code, "span_pinned")
        self.assertIn("162 MHz", str(e.exception))
        self.assertEqual(r.state()["rxOwner"], {})
        r.ais.join("tv-1", drop_sessions=True)
        self.assertEqual(r.decoders.background(), [])
        self.assertEqual(r.state()["rxOwner"]["by"], "ais")
        r.ais.end("stopped")
        r.stop()
        with self.assertRaises(Refused) as e:
            r.ais.join("tv-1")
        self.assertEqual(e.exception.code, "not_running")

    def test_the_radio_stopping_ends_it(self):
        r = self.radio()
        r.ais.join("tv-1")
        r.stop()
        self.assertEqual((r.ais.state, r.ais.why), ("idle", "radio_stopped"))
        self.assertEqual(r.state()["vfo"], HOME)

    def test_it_runs_at_agc_not_the_operators_gain_and_the_dab_notch_stays_out(self):
        r = self.radio(rxGainMode="manual", rxGain=52.0)
        r.ais.join("tv-1")
        self.assertEqual(r.state()["rxGainMode"], "slow_attack")        # aisGain "auto"
        self.assertEqual(r._dab_held(), "ais")
        self.assertFalse(notch.wanted("auto", "auto", 160.8e6, 163.2e6, dab_held=r._dab_held(),
                                      overload_in=True)["dab_notch"])
        a = notch.DabAuto()
        a.inn = True
        self.assertTrue(a.tick(0.0, True, 160.8e6, 163.2e6, "ais"))
        self.assertFalse(a.inn)
        self.assertIn("AIS", a.text())
        self.assertEqual(r._broadcast_key(), ("ais", "ais"))

    def test_routes_of_the_simulated_ships_lie_on_water(self):
        land = mapdata.Land.load()
        self.assertIsNotNone(land)
        for s in simais.FLEET:
            if s.kind == "aton":
                continue
            for i in range(201):
                f = i / 200
                lat, lon = s.a[0] + (s.b[0] - s.a[0]) * f, s.a[1] + (s.b[1] - s.a[1]) * f
                self.assertFalse(mapdata.point_on_land(land, lat, lon), (s.name, lat, lon))


class BroadcastGainFromTheOperator(unittest.TestCase):
    def test_ais_starts_at_the_operators_gain_and_steps_only_on_overload(self):
        p = bcastgain.Policy()
        p.begin(("ais", "ais"), 0.0, "db", None, 52.0, True, from_operator=True)
        self.assertEqual(p.gain, 52.0)                       # not broadcast's 30
        d = bcastgain.Policy()
        d.begin(("dab", "x"), 0.0, "db", None, 52.0, True)
        self.assertEqual(d.gain, 30.0)
        t = 2.0
        for _ in range(bcastgain.DEBOUNCE):
            p.tick(t, True)
            t += bcastgain.WINDOW_S
            p.tick(t, False)
        self.assertLess(p.gain, 52.0)


class TheTable(unittest.TestCase):
    def table(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = aismod.VesselTable(Path(tmp.name) / "ais" / "vessels.json")
        t.set_station("IO75RL")
        return t

    def test_message_types_merge_into_one_vessel(self):
        t = self.table()
        t.heard({"type": 1, "mmsi": 235000001, "lat": 55.5, "lon": -4.9, "speed": 12.3, "course": 271.0,
                 "heading": 270.0, "navStatus": 0, "turn": 0.0, "channel": "A", "snrDb": 20.0}, 1000.0)
        v = t.heard({"type": 5, "mmsi": 235000001, "shipName": "MV TEST", "callsign": "MABC1", "imo": 9000001,
                     "shipType": 80, "toBow": 100, "toStern": 30, "toPort": 10, "toStarboard": 12,
                     "destination": "GLASGOW", "draught": 7.5, "etaMonth": 10, "etaDay": 29, "etaHour": 6,
                     "etaMinute": 45, "channel": "B"}, 1001.0)
        self.assertEqual((v["name"], v["callsign"], v["imo"], v["shipTypeText"], v["length"], v["beam"],
                          v["destination"], v["draught"], v["eta"], v["messages"], v["lat"], v["speed"]),
                         ("MV TEST", "MABC1", 9000001, "Tanker", 130, 22, "GLASGOW", 7.5, "10-29 06:45", 2, 55.5,
                          12.3))
        self.assertEqual(v["lastHeard"], "1970-01-01T00:16:41Z")
        self.assertIsNotNone(v["distanceKm"])

    def test_since_and_expiry(self):
        t = self.table()
        t.heard({"type": 1, "mmsi": 1, "lat": 55.0, "lon": -5.0}, 1000.0)
        rev = t.view()["rev"]
        t.heard({"type": 1, "mmsi": 2, "lat": 55.1, "lon": -5.0}, 1100.0)
        d = t.view(rev)
        self.assertEqual(([v["mmsi"] for v in d["vessels"]], d["removed"], d["full"]), ([2], [], False))
        self.assertEqual(t.expire(1000.0 + 3600.0 + 50, 3600.0), [1])
        d = t.view(rev)
        self.assertEqual((sorted(v["mmsi"] for v in d["vessels"]), d["removed"]), ([2], [1]))
        self.assertTrue(t.view(t.rev + 5)["full"])            # a rev from before a restart: everything

    def test_the_track_thins_and_the_table_survives_a_restart(self):
        t = self.table()
        for i in range(10):
            # 10 m apart, 5 s apart: one point, until a minute or 25 m has gone by.
            t.heard({"type": 1, "mmsi": 7, "lat": 55.0 + i * 0.00009, "lon": -5.0, "speed": 5.0}, 1000.0 + 5 * i)
        t.heard({"type": 1, "mmsi": 7, "lat": 55.01, "lon": -5.0}, 1100.0)
        tr = t.vessel(7)["track"]
        self.assertEqual(len(tr), 5)          # the first, then every 30 m (3 x 10 m), and the jump
        self.assertEqual(tr[-1]["lat"], 55.01)
        t.save(force=True)
        again = aismod.VesselTable(t.path)
        self.assertEqual(again.vessel(7)["track"], tr)
        self.assertEqual(again.rev, t.rev)

    def test_an_implausible_frame_never_enters_the_table(self):
        t = self.table()
        self.assertIsNone(t.heard({"type": 1, "mmsi": 2906440, "lat": 10.0, "lon": 120.0, "plausible": False,
                                   "implausible": "mmsi"}, 1000.0))
        self.assertEqual((len(t), t.rev), (0, 0))

    def test_a_position_that_could_not_follow_the_last_is_set_aside_until_another_agrees(self):
        t = self.table()
        t.heard({"type": 1, "mmsi": 9, "lat": 55.50, "lon": -4.90, "plausible": True}, 1000.0)
        # 30 s later, 50 km away: no ship does that.
        v = t.heard({"type": 1, "mmsi": 9, "lat": 55.95, "lon": -4.90, "plausible": True}, 1030.0)
        self.assertEqual((v["lat"], v["jumps"]), (55.50, 1))
        # 10 s on, near where it was: believed, and the outlier forgotten.
        v = t.heard({"type": 1, "mmsi": 9, "lat": 55.501, "lon": -4.90, "plausible": True}, 1040.0)
        self.assertEqual(v["lat"], 55.501)
        self.assertNotIn("pendingPos", v)
        # A first fix that was the wrong one: two agreeing new ones win.
        t.heard({"type": 1, "mmsi": 9, "lat": 56.40, "lon": -4.90, "plausible": True}, 1050.0)
        v = t.heard({"type": 1, "mmsi": 9, "lat": 56.401, "lon": -4.90, "plausible": True}, 1060.0)
        self.assertEqual(v["lat"], 56.401)

    def test_a_table_saved_by_the_scrambling_decoder_is_dropped(self):
        t = self.table()
        t.path.parent.mkdir(parents=True, exist_ok=True)
        t.path.write_text(json.dumps({"schema": 1, "rev": 5, "vessels": [{"mmsi": 2906440, "rev": 5}], "tracks": {}}))
        self.assertEqual(len(aismod.VesselTable(t.path)), 0)

    def test_texts(self):
        self.assertEqual(aismod.ship_type_text(52), "Tug")
        self.assertEqual(aismod.ship_type_text(69), "Passenger")
        self.assertIsNone(aismod.ship_type_text(0))
        self.assertEqual(aismod.nav_status_text(1), "At anchor")
        self.assertIsNone(aismod.nav_status_text(15))
        self.assertEqual(aismod.station_class(1, 972000001), "sart")


@unittest.skipUnless(has_ais(), "no shack_sdr with AIS for this machine")
class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
               "locator": "IO75RL"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [quick_fleet()]))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

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

    def test_the_session_and_the_vessels(self):
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-1"}, level="view")
        self.assertEqual(s, 403, a)
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-1"})
        self.assertEqual((s, a["state"], a["leaseS"]), (200, "running", aismod.CLIENT_LEASE_S))
        s, a = self.req("POST", "/api/set", {"vfo": HOME})
        self.assertEqual((s, a["code"]), (409, "receiver_busy"), a)
        self.assertTrue(wait(self.radio, lambda: named(self.radio)))
        s, a = self.req("GET", "/api/ais/vessels", level="view")
        self.assertEqual(s, 200)
        self.assertTrue(a["full"])
        self.assertEqual(a["station"]["locator"], "IO75RL")
        self.assertAlmostEqual(a["station"]["lat"], 55.479, places=2)
        self.assertEqual(a["keepMinutes"], 60)
        self.assertEqual(a["session"]["state"], "running")
        # Nearest first.
        km = [v["distanceKm"] for v in a["vessels"] if v.get("distanceKm") is not None]
        self.assertEqual(km, sorted(km))
        rev = a["rev"]
        s, b = self.req("GET", f"/api/ais/vessels?since={rev}", level="view")
        self.assertFalse(b["full"])
        self.assertTrue(all(v["rev"] > rev for v in b["vessels"]))
        s, v = self.req("GET", "/api/ais/vessels/235999001", level="view")
        self.assertEqual((s, v["name"]), (200, "CLYDE SPIRIT"))
        self.assertGreaterEqual(len(v["track"]), 1)
        self.assertEqual(set(v["track"][0]), {"t", "lat", "lon", "speed", "course"})
        s, e = self.req("GET", "/api/ais/vessels/123456789", level="view")
        self.assertEqual((s, e["code"]), (404, "unknown_vessel"))
        s, e = self.req("GET", "/api/ais/vessels/ship", level="view")
        self.assertEqual(s, 400)
        s, a = self.req("GET", "/api/ais/session", level="view")
        self.assertEqual(a["clients"], 1)
        s, a = self.req("DELETE", "/api/ais/session?client=tv-1")
        self.assertEqual((s, a["clients"]), (200, 0))
        s, a = self.req("DELETE", "/api/ais/session?all=1")
        self.assertEqual((s, a["state"], a["why"]), (200, "idle", "stopped"))
        self.assertEqual(self.radio.state()["rxOwner"], {})

    def test_refusals_come_as_sentences_with_codes(self):
        s, a = self.req("POST", "/api/ais/session", {})
        self.assertEqual((s, a["code"]), (400, "bad_client"))
        self.radio.decoders.start("rtty", HOME + 10_000, {})
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-1"})
        self.assertEqual((s, a["code"]), (409, "span_pinned"))
        self.assertEqual(len(a["sessions"]), 1)
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-1", "dropSessions": True})
        self.assertEqual(s, 200, a)


if __name__ == "__main__":
    unittest.main()
