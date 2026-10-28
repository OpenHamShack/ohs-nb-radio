"""Aircraft on a map (28/10/2026): Radio's ADS-B session, the aircraft
table, and their routes.

On the RSPdx-shaped simulator (listen_helpers) with simulated aircraft
around Prestwick (ohsradio/devices/simadsb.py), whose replies shack_sdr's
own Mode S transmitter keys, end to end:

- **A client opening the map starts ADS-B:** the radio is reopened at 6
  MS/s (an RSP's 1.536 MHz filter at 2.4 cuts Mode S away), the receiver
  goes to 1090.000 MHz exactly and says so (`rxOwner`), and the aircraft
  come in - only once the decoder has seen each one's position twice -
  with callsigns, altitudes, speeds and distance and bearing from the
  station.
- **It stops when nobody looks,** and the radio is back at the operator's
  rate with the receiver as it was.
- **A recording made while it holds** (api/recordings/start) is at its
  rate and centre.
- **Refusals** with their sentences, as AIS's.
- **Gain and notches:** the operator's gain stands; both notches out
  whatever their settings.
- **The table:** merging, the track, expiry after adsbKeepMinutes, `since`.
- **Over the API:** api/adsb/session, api/adsb/aircraft[/{icao}].
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ohscore import sdr
from ohscore.decoders import Refused
from ohscore.devices import DeviceError
from ohscore.devices.sdrsource import SdrplayDevice
from ohscore.engine import ReceiverHeld, TxRefused
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import adsb as adsbmod
from ohsradio import notch
from ohsradio import server as ham_server
from ohsradio.devices import simadsb
from ohsradio.radio import Radio

from listen_helpers import ListeningSim, make_listener
from test_server import SECRET

HOME = 145_500_000.0


def has_adsb() -> bool:
    m = sdr.load()
    return m is not None and any(e["id"] == "adsb" for e in m.catalogue())


def wait(radio, cond, timeout=90.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        radio.heartbeat()
        if cond():
            return True
        time.sleep(0.02)
    return False


def air(*callsigns):
    """The simulated fleet, or the named ones of it."""
    fleet = [a for a in simadsb.FLEET if not callsigns or a.callsign in callsigns]
    return simadsb.AdsbAir(fleet)


def shown(radio, n):
    a = radio.adsb.table.view()["aircraft"]
    return len(a) >= n and all(x.get("callsign") for x in a)


@unittest.skipUnless(has_adsb(), "no shack_sdr with ADS-B for this machine")
class OnTheSimulator(unittest.TestCase):
    def radio(self, stations=None, **over):
        # The operator's rate is the receiver's own, 2.4 MS/s, as an RSP's is.
        cfg = {"vfo": HOME, "mode": "fm", "locator": "IO75RL", "sampleRate": 2_400_000, **over}
        r, audio, dev = make_listener([air()] if stations is None else stations, **cfg)
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r

    def test_aircraft_come_in_at_6_ms_while_a_client_has_the_map_open(self):
        r = self.radio()
        self.assertEqual(r.geo.fs, 2_400_000.0)
        feed = r.subscribe("adsb", 512)
        view = r.adsb.join("tv-lounge")
        self.assertEqual((view["state"], view["clients"], view["rateHz"]), ("running", 1, 6_000_000.0))
        st = r.state()
        own = st["rxOwner"]
        self.assertEqual((own["by"], own["session"], own["freqHz"]), ("adsb", "adsb", 1_090_000_000.0))
        self.assertEqual(own["prior"], {"vfo": HOME, "mode": "fm", "rptOffsetHz": 600_000.0})
        self.assertIn("ADS-B", own["text"])
        # Reopened at 6 MS/s, the operator's setting untouched.
        self.assertEqual((r.geo.fs, r.dev.fs, st["sampleRate"]), (6_000_000.0, 6_000_000.0, 2_400_000))
        self.assertTrue(wait(r, lambda: shown(r, 6)), (r.adsb.table.view(), r.adsb.view()))
        # 1090.000 exactly at the centre: no dial offset.
        self.assertEqual(r.centre, 1_090_000_000.0)
        got = {a["callsign"]: a for a in r.adsb.table.view()["aircraft"]}
        self.assertEqual(sorted(got), ["SIM101", "SIM202", "SIM303", "SIM404", "SIM505", "SIM606"])
        high = got["SIM202"]
        self.assertEqual((high["icao"], high["altBaro"], high["category"], high["categoryText"], high["onGround"]),
                         ("F00202", 37000, "A5", "Heavy aircraft", False))
        self.assertAlmostEqual(high["groundSpeed"], 460, delta=2)
        self.assertEqual(high["altGeo"], 37175)
        # Where the simulator put it, on its route across Ayrshire.
        self.assertTrue(55.39 <= high["lat"] <= 55.66 and -5.41 <= high["lon"] <= -3.89, high)
        from ohscore.countries import distance_bearing, locator_position
        km, brg = distance_bearing(*locator_position("IO75RL"), high["lat"], high["lon"])
        self.assertAlmostEqual(high["distanceKm"], km, delta=0.05)
        self.assertAlmostEqual(high["bearingDeg"], brg, delta=0.2)
        taxi = got["SIM606"]
        self.assertEqual((taxi["onGround"], taxi["altBaro"]), (True, None))
        self.assertLess(taxi["distanceKm"], 5)
        approach = got["SIM101"]
        self.assertLess(approach["verticalRate"], 0)
        self.assertEqual(approach["verticalRateSource"], "baro")
        # Nearer is louder, as the simulator sets it.
        self.assertGreater(got["SIM606"]["rssiDb"], got["SIM202"]["rssiDb"])
        for a in got.values():
            self.assertTrue(-40 < a["rssiDb"] < 0, a)
            self.assertGreaterEqual(a["messages"], 4)
            self.assertIsNotNone(a["lastHeard"])
        # The feed: each aircraft as it changed, and the session.
        items = feed.drain()
        self.assertTrue({"session", "aircraft"} <= {i["type"] for i in items})
        self.assertGreater(r.adsb.view()["df17"], 20)

    def test_it_stops_after_the_last_client_and_gives_the_radio_back_at_its_rate(self):
        r = self.radio(stations=[air("SIM202")])
        centre_before = r.centre
        with mock.patch.object(adsbmod, "LINGER_S", 0.5):
            r.adsb.join("tv-1")
            self.assertEqual(r.geo.fs, 6_000_000.0)
            r.adsb.leave("tv-1")
            self.assertTrue(wait(r, lambda: r.adsb.state == "idle", 20))
        self.assertTrue(wait(r, lambda: r.running and r.geo.fs == 2_400_000.0 and r.rate_override is None, 30))
        st = r.state()
        self.assertEqual(st["rxOwner"], {})
        self.assertEqual((st["vfo"], st["mode"], st["rptOffsetHz"], st["sampleRate"]), (HOME, "fm", 600_000.0,
                                                                                         2_400_000))
        self.assertTrue(wait(r, lambda: r.centre == centre_before, 10), (r.centre, centre_before))
        self.assertEqual((st["adsb"]["state"], st["adsb"]["why"]), ("idle", "idle"))
        r.set(vfo=HOME + 25_000)                              # the operator's again
        # And again: a second session reopens it once more.
        r.adsb.join("tv-2")
        self.assertEqual(r.geo.fs, 6_000_000.0)
        r.adsb.end("stopped")
        self.assertTrue(wait(r, lambda: r.running and r.geo.fs == 2_400_000.0, 30))

    def test_the_radio_stopping_ends_it_and_it_starts_again_at_the_operators_rate(self):
        r = self.radio(stations=[air("SIM202")])
        r.adsb.join("tv-1")
        r.stop()
        self.assertEqual((r.adsb.state, r.adsb.why), ("idle", "radio_stopped"))
        self.assertEqual(r.state()["vfo"], HOME)
        self.assertIsNone(r.rate_override)
        r.start()
        self.assertEqual(r.geo.fs, 2_400_000.0)

    def test_while_adsb_holds_the_receiver_tuning_keying_and_ais_are_refused(self):
        r = self.radio(stations=[air("SIM202")], receive_only=False)
        r.adsb.join("tv-1")
        with self.assertRaises(ReceiverHeld) as e:
            r.set(vfo=HOME)
        self.assertIn("ADS-B", str(e.exception))
        with self.assertRaises(TxRefused) as e:
            r.ptt(True)
        self.assertIn("ADS-B", str(e.exception))
        with self.assertRaises(Refused) as e:
            r.ais.join("tv-2")
        self.assertEqual(e.exception.code, "receiver_busy")
        self.assertEqual(str(e.exception), "ADS-B has the receiver for the aircraft map: stop ADS-B first")
        r.adsb.end("stopped")
        self.assertEqual(r.state()["rxOwner"], {})

    def test_refusals_when_it_cannot_start(self):
        r = self.radio(stations=[air("SIM202")])
        with self.assertRaises(Refused) as e:
            r.adsb.join("")
        self.assertEqual(e.exception.code, "bad_client")
        r.decoders.start("rtty", HOME + 10_000, {})
        with self.assertRaises(Refused) as e:
            r.adsb.join("tv-1")
        self.assertEqual(e.exception.code, "span_pinned")
        self.assertIn("1090 MHz", str(e.exception))
        # Refused before the radio is reopened for nothing.
        self.assertEqual((r.geo.fs, r.state()["rxOwner"]), (2_400_000.0, {}))
        r.ais.join("tv-0", drop_sessions=True)
        with self.assertRaises(Refused) as e:
            r.adsb.join("tv-1")
        self.assertEqual(e.exception.code, "receiver_busy")
        self.assertEqual(r.geo.fs, 2_400_000.0)
        r.ais.end("stopped")
        r.stop()
        with self.assertRaises(Refused) as e:
            r.adsb.join("tv-1")
        self.assertEqual(e.exception.code, "not_running")

    def test_it_is_never_a_decoders_session(self):
        # The aircraft map's alone: as a Decoders session it would get the
        # dial's rate or a channel and hear nothing.
        r = self.radio(stations=[])
        self.assertNotIn("adsb", [e["id"] for e in r.decoders.catalogue()])
        with self.assertRaises(Refused) as e:
            r.decoders.start("adsb", 1_090_000_000.0, {})
        self.assertEqual(e.exception.code, "unknown_decoder")

    def test_the_operators_gain_stands_and_both_notches_stay_out(self):
        r = self.radio(stations=[air("SIM202")], rxGainMode="manual", rxGain=52.0, dabNotch="on", rfNotch="on")
        r.adsb.join("tv-1")
        self.assertEqual(r._dab_held(), "adsb")
        self.assertEqual(r._broadcast_key(), ("adsb", "adsb"))
        a = notch.DabAuto()
        a.inn = True
        self.assertTrue(a.tick(0.0, True, 1087e6, 1093e6, "adsb"))
        self.assertIn("ADS-B", a.text())
        # The settings say on; ADS-B takes both out.
        self.assertTrue(wait(r, lambda: r._broadcast_key() == ("adsb", "adsb") and r.bgain.wanted == ("manual", 52.0), 10))
        if hasattr(r.dev, "notches") and r.dev.notches():
            self.assertTrue(wait(r, lambda: not any(getattr(r.dev, "notch_want", {}).values()), 10))


@unittest.skipUnless(has_adsb(), "no shack_sdr with ADS-B for this machine")
class Reopening(unittest.TestCase):
    """What the first session on ohs-box (beta.15, 28/10/2026) found: the
    reopen at the operator's rate straight after 6 MS/s met "No SDRplay RSP
    was found" while the API was still releasing it, an old receive thread
    then read a device that had never opened, and the process died."""

    def radio(self, **over):
        cfg = {"vfo": HOME, "mode": "fm", "locator": "IO75RL", "sampleRate": 2_400_000, **over}
        r, _audio, _dev = make_listener([air("SIM202")], **cfg)
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        r.start()
        return r

    def flaky(self, fails: dict):
        """ListeningSim.open failing as an RSP not yet released does, as
        many times as `fails` says for the rate it is opened at."""
        real = ListeningSim.open

        def open_(dev):
            if fails.get(dev.fs, 0) > 0:
                fails[dev.fs] -= 1
                raise DeviceError("No SDRplay RSP was found (serial 191101D142)")
            return real(dev)
        return mock.patch.object(ListeningSim, "open", open_)

    def test_a_reopen_that_finds_no_device_tries_again(self):
        r = self.radio()
        fails = {6_000_000.0: 1, 2_400_000.0: 2}
        with self.flaky(fails), mock.patch.object(Radio, "REOPEN_WAITS_S", (0.05, 0.1, 0.2)):
            r.adsb.join("tv-1")
            self.assertEqual((r.running, r.geo.fs, r.adsb.state), (True, 6_000_000.0, "running"))
            r.adsb.end("stopped")
            self.assertTrue(wait(r, lambda: r.running and r.geo.fs == 2_400_000.0 and not r.restarting, 30))
        self.assertEqual(fails, {6_000_000.0: 0, 2_400_000.0: 0})
        self.assertEqual(r.state()["rxOwner"], {})

    def test_one_that_never_opens_is_refused_and_the_radio_is_back_at_its_rate(self):
        r = self.radio()
        with self.flaky({6_000_000.0: 99}), mock.patch.object(Radio, "REOPEN_WAITS_S", (0.05, 0.1)):
            with self.assertRaises(Refused) as e:
                r.adsb.join("tv-1")
        self.assertEqual(e.exception.code, "device_error")
        self.assertIn("6 MS/s", str(e.exception))
        self.assertEqual((r.running, r.geo.fs, r.adsb.state, r.state()["rxOwner"]), (True, 2_400_000.0, "idle", {}))

    def test_a_receive_thread_that_outlives_its_run_never_joins_the_next(self):
        # A read that blocks past stop()'s three-second join, as an RSP's can
        # while the API releases it.
        r = self.radio()
        gate, blocked = threading.Event(), threading.Event()
        dev = r.dev
        real_read = type(dev).read

        def read(d, n):
            if d is dev and not gate.is_set():
                blocked.set()
                gate.wait(20)
            return real_read(d, n)

        with mock.patch.object(ListeningSim, "read", read):
            self.assertTrue(blocked.wait(10))
            old = [t for t in r.threads if t.name.endswith("-rx")]
            r.stop()
            r.start()
            gate.set()
            for t in old:
                t.join(5)
                self.assertFalse(t.is_alive(), "the old run's receive thread carried on")
        alive = [t for t in threading.enumerate() if t.name == old[0].name]
        self.assertEqual(len(alive), 1)
        self.assertTrue(wait(r, lambda: r.running and r.rx_samples > 0, 10))

    def test_a_read_on_a_closed_device_is_a_sentence_not_a_crash(self):
        dev = SdrplayDevice({}, 2_400_000.0)
        with self.assertRaises(DeviceError) as e:
            dev.read(1024)
        self.assertIn("closed", str(e.exception))

    def test_when_the_post_answers_the_device_is_at_1090(self):
        r = self.radio(vfo=430_162_500.0)
        r.adsb.join("tv-1")
        ds = r.state()["deviceStatus"]
        self.assertEqual((ds.get("rxLo", ds.get("rxIf")), ds["fs"]), (1_090_000_000.0, 6_000_000.0))
        self.assertEqual((r.dev.rx_if, r.geo.fs), (1_090_000_000.0, 6_000_000.0))

    def test_a_recording_is_named_and_described_as_what_is_held(self):
        r = self.radio()
        for join, end, mode in ((r.adsb.join, r.adsb.end, "ADS-B"), (r.ais.join, r.ais.end, "AIS")):
            join("tv-1")
            path = r.start_recording(folder=Path(r._tmp.name) / "rec")
            self.assertTrue(wait(r, lambda: r.rec is not None and r.rec.written > 0, 10))
            r.stop_recording()
            meta = path.with_suffix(".sigmf-meta") if path.suffix == ".sigmf-data" else \
                Path(str(path) + ".sigmf-meta")
            self.assertTrue(wait(r, lambda: meta.exists() and not r.rec_closing, 10), meta)
            g = json.loads(meta.read_text())["global"]
            self.assertTrue(meta.name.endswith(f"MHz-{mode}.sigmf-meta"), meta.name)
            self.assertIn(f"MHz {mode}", g["core:description"])
            self.assertEqual(g["openhamshack:receive"]["mode"], mode.lower())
            self.assertEqual(g["openhamshack:service"]["kind"], mode.lower().replace("-", ""))
            self.assertNotIn("openhamshack:broadcast", g)
            end("stopped")
            self.assertTrue(wait(r, lambda: r.running and r.geo.fs == 2_400_000.0 and not r.restarting, 30))


@unittest.skipUnless(has_adsb(), "no shack_sdr with ADS-B for this machine")
class OtherReceivers(unittest.TestCase):
    def test_a_receiver_that_is_no_rsp_runs_at_2_4_and_is_not_reopened(self):
        r, _audio, dev = make_listener([air("SIM202")], vfo=HOME, mode="fm", locator="IO75RL")
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        dev.kind = "rtlsdr"
        r.start()
        before = r.dev
        r.adsb.join("tv-1")
        self.assertIs(r.dev, before)
        self.assertEqual((r.geo.fs, r.adsb.view()["rateHz"]), (2_400_000.0, 2_400_000.0))
        self.assertTrue(wait(r, lambda: shown(r, 1)), r.adsb.view())
        r.adsb.end("stopped")
        self.assertIs(r.dev, before)

    def test_one_at_1_2_ms_is_reopened_at_2_4(self):
        r, _audio, dev = make_listener([air("SIM202")], fs=1_200_000.0, vfo=HOME, mode="fm", locator="IO75RL",
                                       sampleRate=1_200_000)
        self.addCleanup(r._tmp.cleanup)
        self.addCleanup(r.stop)
        dev.kind = "rtlsdr"
        r.start()
        self.assertEqual(r.geo.fs, 1_200_000.0)
        r.adsb.join("tv-1")
        self.assertEqual(r.geo.fs, 2_400_000.0)
        r.adsb.end("stopped")
        self.assertTrue(wait(r, lambda: r.running and r.geo.fs == 1_200_000.0, 30))


class TheTable(unittest.TestCase):
    def frame(self, **over):
        f = {"icao": "F00202", "callsign": "SIM202", "category": "A5", "lat": 55.5, "lon": -4.9, "posT": 1000.0,
             "altBaro": 37000, "altGeo": 37175, "gs": 460.0, "track": 270.0, "vrate": 0, "vrateSource": "baro",
             "onGround": False, "squawk": "7700", "emergency": "general", "messages": 12, "rssiDb": -35.2,
             "firstT": 990.0}
        f.update(over)
        return f

    def test_a_frame_becomes_an_aircraft(self):
        t = adsbmod.AircraftTable()
        t.set_station("IO75RL")
        v = t.heard(self.frame(), 1000.5)
        self.assertEqual((v["icao"], v["callsign"], v["groundSpeed"], v["verticalRate"], v["verticalRateSource"],
                          v["categoryText"], v["emergencyText"], v["messages"], v["firstHeard"], v["positionAt"]),
                         ("F00202", "SIM202", 460.0, 0, "baro", "Heavy aircraft", "Emergency", 12,
                          "1970-01-01T00:16:30Z", "1970-01-01T00:16:40Z"))
        self.assertNotIn("posT", v)
        self.assertIsNotNone(v["distanceKm"])

    def test_the_track_since_and_expiry(self):
        t = adsbmod.AircraftTable()
        for i in range(11):
            # 120 m apart, a second apart: a point every 500 m or 10 s (0, 5, 10).
            t.heard(self.frame(lat=55.5 + i * 0.00108, posT=1000.0 + i), 1000.0 + i)
        tr = t.aircraft("F00202")["track"]
        self.assertEqual(len(tr), 3)
        self.assertEqual(set(tr[0]), {"t", "lat", "lon", "altBaro", "groundSpeed", "track"})
        rev = t.view()["rev"]
        t.heard(self.frame(icao="F00303", callsign="SIM303"), 1100.0)
        d = t.view(rev)
        self.assertEqual(([a["icao"] for a in d["aircraft"]], d["full"]), (["F00303"], False))
        self.assertEqual(t.expire(1000.0 + 300.0 + 20, 300.0), ["F00202"])
        self.assertEqual(t.view(rev)["removed"], ["F00202"])
        self.assertTrue(t.view(t.rev + 5)["full"])
        self.assertIsNone(t.aircraft("F00202"))


@unittest.skipUnless(has_adsb(), "no shack_sdr with ADS-B for this machine")
class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
               "locator": "IO75RL", "sampleRate": 2_400_000}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [air("SIM202", "SIM303")]))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def test_the_session_and_the_aircraft(self):
        s, a = self.req("POST", "/api/adsb/session", {"client": "tv-1"}, level="view")
        self.assertEqual(s, 403, a)
        s, a = self.req("POST", "/api/adsb/session", {"client": "tv-1"})
        self.assertEqual((s, a["state"], a["leaseS"], a["rateHz"]), (200, "running", adsbmod.CLIENT_LEASE_S,
                                                                     6_000_000.0))
        s, a = self.req("POST", "/api/set", {"vfo": HOME})
        self.assertEqual((s, a["code"]), (409, "receiver_busy"), a)
        self.assertTrue(wait(self.radio, lambda: shown(self.radio, 2)))
        s, a = self.req("GET", "/api/adsb/aircraft", level="view")
        self.assertEqual(s, 200)
        self.assertTrue(a["full"])
        self.assertEqual((a["station"]["locator"], a["keepMinutes"], a["session"]["state"]), ("IO75RL", 5, "running"))
        km = [v["distanceKm"] for v in a["aircraft"]]
        self.assertEqual(km, sorted(km))
        rev = a["rev"]
        s, b = self.req("GET", f"/api/adsb/aircraft?since={rev}", level="view")
        self.assertFalse(b["full"])
        s, v = self.req("GET", "/api/adsb/aircraft/f00202", level="view")
        self.assertEqual((s, v["callsign"]), (200, "SIM202"))
        self.assertGreaterEqual(len(v["track"]), 1)
        s, e = self.req("GET", "/api/adsb/aircraft/ABCDEF", level="view")
        self.assertEqual((s, e["code"]), (404, "unknown_aircraft"))
        s, e = self.req("GET", "/api/adsb/aircraft/plane", level="view")
        self.assertEqual((s, e["code"]), (400, "bad_params"))
        s, a = self.req("GET", "/api/state", level="view")
        self.assertEqual(a["adsb"]["state"], "running")
        s, a = self.req("GET", "/api/status", level="view")
        self.assertEqual((a["adsb"]["state"], a["ais"]["state"]), ("running", "idle"))
        s, a = self.req("DELETE", "/api/adsb/session?client=tv-1")
        self.assertEqual((s, a["clients"]), (200, 0))
        s, a = self.req("DELETE", "/api/adsb/session?all=1")
        self.assertEqual((s, a["state"], a["why"]), (200, "idle", "stopped"))
        self.assertEqual(self.radio.state()["rxOwner"], {})

    def test_a_recording_while_it_holds_is_at_its_rate_and_centre(self):
        s, a = self.req("POST", "/api/adsb/session", {"client": "tv-1"})
        self.assertEqual(s, 200, a)
        s, a = self.req("POST", "/api/recordings/start", {"kind": "iq"})
        self.assertEqual(s, 200, a)
        self.assertTrue(wait(self.radio, lambda: self.radio.rx_samples > 6_000_000 * 0.5, 30))
        s, a = self.req("POST", "/api/recordings/stop", {"kind": "iq"})
        self.assertEqual(s, 200, a)
        self.assertTrue(wait(self.radio, lambda: list(self.radio.recordings_dir().rglob("*.sigmf-meta")), 20))
        meta = json.loads(next(self.radio.recordings_dir().rglob("*.sigmf-meta")).read_text())
        g = meta["global"]
        self.assertEqual(g["core:sample_rate"], 6_000_000.0)
        dev = g["openhamshack:device"]
        self.assertEqual(dev.get("rxLo", dev.get("rxIf")), 1_090_000_000.0)
        self.assertEqual(meta["captures"][0]["core:frequency"], 1_090_000_000.0)
        # Still holding, still at its rate: a recording changes neither.
        self.assertEqual((self.radio.adsb.state, self.radio.geo.fs), ("running", 6_000_000.0))

    def test_refusals_come_as_sentences_with_codes(self):
        s, a = self.req("POST", "/api/adsb/session", {})
        self.assertEqual((s, a["code"]), (400, "bad_client"))
        self.radio.decoders.start("rtty", HOME + 10_000, {})
        s, a = self.req("POST", "/api/adsb/session", {"client": "tv-1"})
        self.assertEqual((s, a["code"]), (409, "span_pinned"))
        s, a = self.req("POST", "/api/adsb/session", {"client": "tv-1", "dropSessions": True})
        self.assertEqual(s, 200, a)


if __name__ == "__main__":
    unittest.main()
