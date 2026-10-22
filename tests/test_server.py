"""The store form's API (ohscore/server, docs/SERVER-API.md) over a real
QO-100 NB engine on the simulator, through real HTTP on loopback: who may
ask (only what the proxy vouches for with this app's secret), what each
level may do, the transmit lease, the broker's say before every key-up,
and the streams. Transmit goes only into the simulator; the broker is a
fake that answers as the edition's does (CONTROLLER-CONTRACT 7)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import http.client
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest

import helpers
from ohscore.server import shack
from ohscore.server.app import Server, spectrum_item
from ohscore.server.audio import StreamAudio
from ohsnb import server as nb_server

SECRET = "test-proxy-secret"


class FakeBroker:
    """The edition's broker, as far as one app sees it: claims, modes,
    on air, heartbeats, and the knobs a test needs (refuse on air, take a
    claim back)."""

    def __init__(self):
        self.calls = []
        self.claims = {}
        self.refuse_onair = None
        self.n = 0
        self.grace = False          # just restarted: only {"reclaim": true} is granted
        self.refuse_next = []       # (status, answer) for the next claims, first first
        self.down = False           # the controller cannot be reached
        self.release_requested = None

    def restart(self):
        """The edition's broker restarting (a platform update): every claim
        is gone, and for its grace only re-claims are granted."""
        self.claims.clear()
        self.grace = True

    def __call__(self, method, path, body=None, headers=None):
        if self.down:
            raise OSError("connection refused")
        self.calls.append((method, path, body, dict(headers or {})))
        if method == "POST" and path == "/broker/claims":
            if self.refuse_next:
                return self.refuse_next.pop(0)
            if self.grace and not body.get("reclaim"):
                return 503, {"error": "The station has just restarted", "code": "broker_restarting",
                             "retryAfter": 15}
            self.n += 1
            cid = f"cl_{self.n}"
            self.claims[cid] = {"device": body["device"], "mode": body["mode"], "onAir": False}
            return 201, {"claimId": cid, "device": body["device"], "mode": body["mode"],
                         "lease": {"seconds": 10, "heartbeatEvery": 2}, "access": {"reach": "network",
                                                                                  "address": "192.168.2.1"}}
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[1] == "claims":
            c = self.claims.get(parts[2])
            if c is None:
                return 404, {"error": "no such claim", "code": "not_found"}
            if method == "DELETE":
                self.claims.pop(parts[2])
                return 200, {"released": True}
            what = parts[3]
            if what == "mode":
                c["mode"] = body["mode"]
                return 200, {"mode": body["mode"]}
            if what == "onair":
                if body.get("on") and self.refuse_onair:
                    return 403, {"error": self.refuse_onair, "code": "licence_refused"}
                c["onAir"] = bool(body.get("on"))
                return 200, {"onAir": c["onAir"], "lease": {"seconds": 6, "heartbeatEvery": 2}}
            if what == "heartbeat":
                return 200, {"state": "granted", "leaseSeconds": 10,
                             "releaseRequested": self.release_requested or False}
        return 404, {"error": "unknown", "code": "not_found"}

    def paths(self):
        return [(m, p.split("/")[-1] if p.count("/") > 2 else p) for m, p, _b, _h in self.calls]

    def claim_bodies(self):
        return [b for m, p, b, _h in self.calls if m == "POST" and p == "/broker/claims"]


class ServerTest(unittest.TestCase):
    broker = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = StreamAudio(realtime=False)
        cfg = helpers.sim_cfg(callsign="GM4BRI", licenceClass="full")
        from ohsnb.radio import Radio
        self.radio = Radio(cfg, persist=False, data_dir=self.tmp.name, audio=self.audio)
        self.fake = FakeBroker() if self.broker else None
        bc = shack.BrokerClient(self.fake) if self.fake else None
        self.now = [1000.0]
        info = nb_server.info("9.9.9")
        if self.broker:
            # The simulator stands in for the Pluto the broker lends.
            info.device_for = lambda dev: "pluto-1"
        self.srv = Server(self.radio, info, self.audio, secret=SECRET, broker=bc,
                          clock=lambda: self.now[0])
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="transmit", secret=SECRET, user="brian", transmit=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json"}
        if secret is not None:
            h[shack.SHACK_SECRET_HEADER] = secret
        if level is not None:
            h.update({"X-OpenHamShack-User": user, "X-OpenHamShack-Level": level,
                      "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        if transmit is not None:        # CONTROLLER-CONTRACT 5.5; absent: an older controller
            h["X-OpenHamShack-Transmit"] = transmit
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def cw(self):
        s, a = self.req("POST", "/api/set", {"mode": "cw", "vfo": 10_489_520_000.0}, level="control")
        self.assertEqual(s, 200, a)

    def wait(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False


class WhoMayAsk(ServerTest):
    def test_nothing_without_the_proxy_secret(self):
        for secret in (None, "wrong", ""):
            s, a = self.req("GET", "/api/status", secret=secret)
            self.assertEqual((s, a["code"]), (401, "proxy_required"))
        # Forged identity headers without the secret change nothing.
        s, _a = self.req("POST", "/api/ptt", {"on": True, "remote": "x"}, secret=None)
        self.assertEqual(s, 401)
        self.assertFalse(self.radio.state()["keyed"])

    def test_no_secret_configured_is_a_locked_app(self):
        self.srv.secret = ""
        s, a = self.req("GET", "/api/status")
        self.assertEqual((s, a["code"]), (401, "proxy_required"))

    def test_levels(self):
        self.assertEqual(self.req("GET", "/api/status", level="view")[0], 200)
        s, a = self.req("POST", "/api/set", {"mode": "cw"}, level="view")
        self.assertEqual((s, a["code"], a["needs"]), (403, "level_too_low", "control"))
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "r1"}, level="control")
        self.assertEqual((s, a["needs"]), (403, "transmit"))
        self.assertFalse(self.radio.state()["keyed"])
        # Settings-only keys need transmit even through /api/set.
        s, a = self.req("POST", "/api/set", {"txGainCeiling": -20.0}, level="control")
        self.assertEqual((s, a["needs"]), (403, "transmit"))

    def test_the_profile_is_the_controllers(self):
        s, a = self.req("POST", "/api/set", {"licenceClass": "foundation"})
        self.assertEqual(s, 400)
        self.assertIn("station profile", a["error"])

    def test_platform_calls_reach_only_their_routes(self):
        self.assertEqual(self.req("GET", "/api/shack/busy", level="none")[1], {"busy": False, "why": ""})
        self.assertEqual(self.req("GET", "/api/status", level="none")[0], 403)

    def test_status_page_needs_nothing_from_outside(self):
        s, page = self.req("GET", "/", level="view")
        self.assertEqual(s, 200)
        text = page.decode()
        self.assertIn("QO-100 NB", text)
        self.assertNotIn("http", text.replace('content="width', ""))      # no external references


class OverpowerWatch(ServerTest):
    """GET api/overpower (view) and POST api/overpower/capture (control):
    the watch's list over the wire; the capture saves receive IQ only."""

    def test_the_list_and_the_station_over_the_beacon(self):
        self.radio.dev.add_station("carrier", 10_489_812_345.0, -33.0)
        end = time.monotonic() + 60
        ops = []
        while time.monotonic() < end and not ops:
            self.radio.heartbeat()
            s, v = self.req("GET", "/api/overpower", level="view")
            self.assertEqual(s, 200, v)
            ops = [e for e in v["events"] if e["kind"] == "overpower"]
            time.sleep(0.1)
        self.assertEqual(v["state"], "running")
        self.assertEqual(len(ops), 1, v)
        self.assertAlmostEqual(ops[0]["freq"], 10_489_812_345.0, delta=100.0)

    def test_capture_needs_control_and_capture_turned_on(self):
        s, a = self.req("POST", "/api/overpower/capture", level="view")
        self.assertEqual((s, a["needs"]), (403, "control"))
        s, a = self.req("POST", "/api/overpower/capture", level="control")
        self.assertEqual((s, a["code"]), (409, "nothing_to_save"))
        self.assertFalse(self.radio.state()["keyed"])


class PadThroughThePlatform(ServerTest):
    """The controller's input host sends the front app's pad presses
    (CONTROLLER-PAD.md 6.1); PTT is never one of them."""

    def test_actions_levels_and_no_ptt(self):
        v = self.radio.state()["vfo"]
        s, faces = self.req("POST", "/api/shack/pad/action", {"action": "tune", "kind": "turn", "step": 2},
                            level="control")
        self.assertEqual(s, 200)
        self.assertEqual(self.radio.state()["vfo"], v + 200)
        self.assertIn("onAir", faces)
        s, a = self.req("POST", "/api/shack/pad/action", {"action": "power", "kind": "turn", "step": 1},
                        level="control")
        self.assertEqual((s, a["needs"]), (403, "transmit"))
        s, _a = self.req("POST", "/api/shack/pad/action", {"action": "ptt"})
        self.assertEqual(s, 400)
        self.assertFalse(self.radio.state()["keyed"])


class Lease(ServerTest):
    def test_key_hold_and_lose_the_remote(self):
        self.cw()
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertTrue(a["onAir"], a["txError"])
        self.assertEqual(a["tx"]["remote"]["id"], "phone-1")
        s, a = self.req("POST", "/api/ptt/heartbeat", {"remote": "phone-2"})
        self.assertEqual((s, a["error"]), (409, "transmit is held by another remote"))
        self.assertEqual(self.req("POST", "/api/ptt/heartbeat", {"remote": "phone-1"})[0], 200)
        self.now[0] += 5.5                   # the remote goes quiet
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"]))
        s, a = self.req("GET", "/api/status")
        self.assertIn("remote controller lost", a["txError"])
        s, a = self.req("POST", "/api/ptt/heartbeat", {"remote": "phone-1"})
        self.assertEqual((s, a["onAir"]), (409, False))

    def test_unkey_and_halt(self):
        self.cw()
        self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        s, a = self.req("POST", "/api/ptt", {"on": False})
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"]))
        self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        s, a = self.req("POST", "/api/halt", level="control")
        self.assertFalse(self.radio.state()["keyed"])

    def test_a_refusal_is_200_with_the_reason(self):
        # USB in the CW-only segment: the band plan refuses (the dataset).
        self.req("POST", "/api/set", {"mode": "usb", "vfo": 10_489_520_000.0}, level="control")
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertEqual((s, a["onAir"]), (200, False))
        self.assertTrue(a["txError"])

    def test_bad_remote(self):
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "no spaces allowed"})
        self.assertEqual(s, 400)


class Broker(ServerTest):
    broker = True

    def test_receive_claim_at_start_and_where_the_radio_is(self):
        first = self.fake.calls[0]
        self.assertEqual((first[0], first[1], first[2]["device"], first[2]["mode"]),
                         ("POST", "/broker/claims", "pluto-1", "rx"))
        self.assertEqual(self.radio.state()["plutoUri"], "ip:192.168.2.1")

    def test_key_up_asks_the_broker_first_and_unkey_tells_it_after(self):
        self.cw()
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertTrue(a["onAir"], a["txError"])
        onair = [c for c in self.fake.calls if c[1].endswith("/onair")][0]
        self.assertTrue(onair[2]["on"])
        self.assertEqual(onair[3][shack.SHACK_ACTING_HEADER], "dev_TEST")
        # The uplink, not the downlink dial: 10489.520 down is 2400.020 up.
        self.assertAlmostEqual(onair[2]["freqHz"] / 1e6, 2400.02, places=2)
        self.assertEqual(onair[2]["chain"], ["pluto-1"])
        self.req("POST", "/api/ptt", {"on": False})
        self.assertTrue(self.wait(lambda: any(c[1].endswith("/onair") and not c[2]["on"] for c in self.fake.calls)))
        claim = next(iter(self.fake.claims.values()))
        self.assertEqual((claim["mode"], claim["onAir"]), ("rx", False))

    def test_broker_refusal_means_no_key_up(self):
        self.cw()
        self.fake.refuse_onair = "The station licence does not allow this."
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertEqual((a["onAir"], a["txError"]), (False, "The station licence does not allow this."))
        self.assertFalse(self.radio.state()["keyed"])

    def beat_now(self, silent_for=0.0):
        """Make the claim's heartbeat due on the broker loop's next pass,
        as if the broker had last answered `silent_for` seconds ago."""
        with self.srv.broker.lock:
            c = self.srv.broker.claims["pluto-1"]
            c["beat"] = -1e9
            c["ok"] -= silent_for

    def count_stops(self):
        stops = []
        real = self.radio.stop
        self.radio.stop = lambda *a, **k: (stops.append(1), real(*a, **k))[1]
        return stops

    def test_a_claim_taken_back_unkeys_stops_and_is_reclaimed_for_receive(self):
        self.cw()
        self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertTrue(self.radio.state()["keyed"])
        stops = self.count_stops()
        self.fake.claims.clear()              # the admin's "Stop all transmitting"
        self.beat_now()
        self.assertTrue(self.wait(lambda: self.fake.claim_bodies()[-1]["reclaim"]
                                  and self.radio.state()["running"]))
        # RF off and the engine stopped before anything else; then back,
        # receiving only: a lost claim never resumes a transmission.
        self.assertEqual(len(stops), 1)
        self.assertFalse(self.radio.state()["keyed"])
        self.assertEqual([c["mode"] for c in self.fake.claims.values()], ["rx"])
        s, a = self.req("GET", "/api/status")
        self.assertIn("pluto-1", a["txError"])
        self.assertEqual((a["radioError"], a["reconnecting"], a["onAir"]), ("", False, False))

    def test_a_broker_restart_is_reclaimed_after_its_retry_after(self):
        # ohs-box 10/10: a platform update restarted the broker, the
        # heartbeat met 404, and NB stayed stopped for hours.
        self.fake.restart()
        self.fake.refuse_next = [(503, {"error": "restarting", "code": "broker_restarting", "retryAfter": 5})]
        self.beat_now()
        self.assertTrue(self.wait(lambda: len(self.fake.claim_bodies()) == 2 and self.srv.status()["reconnecting"]))
        st = self.srv.status()
        self.assertEqual((st["running"], st["radioError"]), (False, "Reconnecting to the station…"))
        # Not before the broker's retryAfter...
        time.sleep(1.2)
        self.assertEqual(len(self.fake.claim_bodies()), 2)
        self.assertFalse(self.radio.state()["running"])
        # ...and then the claim is re-taken during the grace, and the radio runs.
        self.now[0] += 5
        self.assertTrue(self.wait(lambda: self.radio.state()["running"] and self.srv.reclaim is None))
        self.assertEqual(len(self.fake.claim_bodies()), 3)
        self.assertTrue(self.fake.claim_bodies()[-1]["reclaim"])
        st = self.srv.status()
        self.assertEqual((st["reconnecting"], st["radioError"]), (False, ""))
        self.assertTrue(self.srv.wanted)

    def test_an_unreachable_controller_is_reclaimed_when_it_answers(self):
        self.fake.down = True
        self.beat_now(silent_for=60)
        self.assertTrue(self.wait(lambda: self.srv.status()["reconnecting"]))
        self.assertFalse(self.radio.state()["running"])
        # Backing off while it is down: each try doubles the wait.
        for _n in range(3):
            self.now[0] += 30
            time.sleep(0.6)
        self.assertGreater(self.srv.reclaim["delay"], 1.0)
        self.assertFalse(self.radio.state()["running"])
        self.fake.down = False
        self.now[0] += 30
        self.assertTrue(self.wait(lambda: self.radio.state()["running"] and self.srv.reclaim is None))
        self.assertTrue(self.fake.claim_bodies()[-1]["reclaim"])
        self.assertFalse(self.srv.status()["reconnecting"])

    def test_another_app_holding_it_ends_the_reconnection(self):
        self.fake.restart()
        self.fake.refuse_next = [(409, {"error": "QO-100 WB has the Pluto (receiving).", "code": "device_held"})]
        self.beat_now()
        self.assertTrue(self.wait(lambda: self.srv.status()["radioError"] == "QO-100 WB has the Pluto (receiving)."))
        st = self.srv.status()
        self.assertEqual((st["reconnecting"], st["running"]), (False, False))
        self.assertTrue(self.srv.wanted)        # run.py's plain retry carries on, as at start-up

    def test_a_person_stopping_it_ends_the_reconnection(self):
        self.fake.down = True
        self.beat_now(silent_for=60)
        self.assertTrue(self.wait(lambda: self.srv.status()["reconnecting"]))
        self.fake.down = False
        self.req("POST", "/api/stop", level="control")
        self.assertTrue(self.wait(lambda: self.srv.reclaim is None))
        n = len(self.fake.claim_bodies())
        self.now[0] += 60
        time.sleep(1.2)
        self.assertEqual(len(self.fake.claim_bodies()), n)
        self.assertFalse(self.radio.state()["running"])

    def test_a_release_requested_on_the_heartbeat_is_a_hand_over(self):
        self.fake.release_requested = {"for": "shack-atv", "deadlineSeconds": 60, "stop": False}
        self.beat_now()
        self.assertTrue(self.wait(lambda: not self.radio.state()["running"] and not self.fake.claims))
        self.assertFalse(self.srv.wanted)
        self.assertEqual(self.fake.claims, {})
        n = len(self.fake.claim_bodies())
        self.now[0] += 60
        time.sleep(1.2)
        self.assertEqual(len(self.fake.claim_bodies()), n)
        st = self.srv.status()
        self.assertEqual((st["running"], st["reconnecting"], st["radioError"]),
                         (False, False, "The radio was handed to another app"))

    def test_release_request(self):
        self.cw()
        self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        s, a = self.req("POST", "/api/shack/release", {"device": "pluto-1"}, level="none")
        self.assertEqual((s, a), (409, {"onAir": True}))
        self.req("POST", "/api/ptt", {"on": False})
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"]))
        s, a = self.req("POST", "/api/shack/release", {"device": "pluto-1"}, level="none")
        self.assertEqual(s, 202)
        self.assertFalse(self.radio.state()["running"])
        self.assertEqual(self.fake.claims, {})



class Q65UnderTheLease(ServerTest):
    """Q65 transmit stays off the air unless the lease and the broker both
    allow it, as every other key-up does. Here Q65 is keyed with /api/ptt
    (automatic transmit's rendered overs take the same key-up path, and
    are tested in test_server_autotx.py), and that must still go through
    the broker's claim and on-air answer first and end when the remote goes
    quiet. Held as a test because ohsdigi 0.2.0 made Q65 an available mode
    in the store image, where before it was greyed out for want of an
    encoder. Into the simulator only; the broker is the fake."""
    broker = True

    def setUp(self):
        from ohscore.modes import q65
        if not q65.CAN_ENCODE:
            self.skipTest("ohsdigi with Q65 is not built here (tools/build-ohsdigi.sh)")
        super().setUp()
        s, a = self.req("POST", "/api/set", {"mode": "q65", "vfo": 10_489_541_000.0}, level="control")
        self.assertEqual(s, 200, a)
        self.assertEqual(self.radio.state()["mode"], "q65")

    def test_broker_refusal_means_no_key_up(self):
        self.fake.refuse_onair = "The station licence does not allow this."
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertEqual((a["onAir"], a["txError"]), (False, "The station licence does not allow this."))
        self.assertFalse(self.radio.state()["keyed"])
        self.assertIsNone(a["tx"]["remote"])

    def test_keyed_only_after_the_broker_and_unkeyed_when_the_remote_goes_quiet(self):
        keyed_at_onair = []
        real_on_air = self.srv.broker.on_air

        def on_air(*args, **kw):
            keyed_at_onair.append(self.radio.state()["keyed"])
            return real_on_air(*args, **kw)
        self.srv.broker.on_air = on_air
        s, a = self.req("POST", "/api/ptt", {"on": True, "remote": "phone-1"})
        self.assertTrue(a["onAir"], a["txError"])
        self.assertEqual(keyed_at_onair, [False])      # asked before any RF
        claim = next(iter(self.fake.claims.values()))
        self.assertEqual((claim["mode"], claim["onAir"]), ("tx", True))
        s, a = self.req("POST", "/api/ptt/heartbeat", {"remote": "phone-2"})
        self.assertEqual(s, 409)
        self.now[0] += 5.5
        self.assertTrue(self.wait(lambda: not self.radio.state()["keyed"]))
        self.assertTrue(self.wait(lambda: claim["onAir"] is False and claim["mode"] == "rx"))


class Streams(ServerTest):
    def ws(self, path):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                   f"{shack.SHACK_SECRET_HEADER}: {SECRET}\r\nX-OpenHamShack-User: brian\r\n"
                   f"X-OpenHamShack-Level: transmit\r\nX-OpenHamShack-Device: dev_TEST\r\n\r\n").encode())
        f = s.makefile("rb")
        line = f.readline()
        self.assertIn(b"101", line)
        while f.readline() not in (b"\r\n", b""):
            pass
        return s, f

    @staticmethod
    def frame(f):
        b0, b1 = f.read(2)
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", f.read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", f.read(8))[0]
        return b0 & 0x0F, f.read(n)

    def test_events_carry_the_engines_feeds(self):
        s, f = self.ws("/api/events?kinds=state,meter")
        op, data = self.frame(f)
        hello = json.loads(data)
        self.assertEqual((hello["kind"], hello["status"]["app"]), ("hello", "shack-qo100nb"))
        self.req("POST", "/api/set", {"mode": "cw"}, level="control")
        kinds = set()
        end = time.monotonic() + 10
        while time.monotonic() < end and not {"state", "meter"} <= kinds:
            kinds.add(json.loads(self.frame(f)[1])["kind"])
        self.assertLessEqual({"state", "meter"}, kinds)
        s.close()

    def _state_msgs(self, f, until, secs=10):
        """State messages read until `until(msgs)`; None after `secs`."""
        msgs = []
        end = time.monotonic() + secs
        while time.monotonic() < end:
            m = json.loads(self.frame(f)[1])
            if m["kind"] == "state":
                msgs.append(m)
                if until(msgs):
                    return msgs
        return None

    def test_events_a_normal_client_gets_diffs_and_no_snapshot(self):
        s, f = self.ws("/api/events?kinds=state")
        self.frame(f)
        self.req("POST", "/api/set", {"mode": "cw"}, level="control")
        msgs = self._state_msgs(f, lambda ms: any(m["changes"].get("mode") == "cw" for m in ms))
        self.assertIsNotNone(msgs)
        self.assertFalse(any(m.get("full") for m in msgs))
        s.close()

    def test_events_a_client_that_missed_state_changes_is_sent_the_whole_state(self):
        # Hold the state feed's drain, as a stalled connection would, change
        # a value, then overflow the 256 feed so the diff carrying it is
        # dropped for good; on release the client must end with the value.
        gate = threading.Event()
        feeds = []
        real_sub = self.radio.subscribe

        def sub(kind, n=64):
            fd = real_sub(kind, n)
            if kind == "state":
                real_drain = fd.drain
                fd.drain = lambda *a, **k: real_drain(*a, **k) if gate.is_set() else []
                feeds.append(fd)
            return fd
        self.radio.subscribe = sub
        s, f = self.ws("/api/events?kinds=state")
        self.frame(f)
        self.assertEqual(len(feeds), 1)
        self.req("POST", "/api/set", {"mode": "cw"}, level="control")
        for i in range(400):
            self.radio._publish("state", {"changes": {"filler": i}})
        self.assertGreater(feeds[0].dropped, 0)
        gate.set()
        msgs = self._state_msgs(f, lambda ms: any(m.get("full") for m in ms))
        self.assertIsNotNone(msgs)
        full = [m for m in msgs if m.get("full")][0]
        self.assertEqual(full["changes"]["mode"], "cw")
        self.assertEqual(full["changes"]["mode"], self.radio.state()["mode"])
        self.assertGreaterEqual(len(full["changes"]), len(self.radio.state()) - 5)
        s.close()

    def test_receive_audio_is_announced_pcm(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/audio/rx", headers={shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "b",
                                                   "X-OpenHamShack-Level": "view"})
        r = c.getresponse()
        self.assertEqual(r.getheader("Content-Type"), "audio/L16; rate=12000; channels=1")
        self.assertEqual(json.loads(r.getheader("X-Audio-Format"))["encoding"], "s16le")
        data = r.read(4800)
        self.assertEqual(len(data), 4800)
        c.close()

    def test_a_gone_listener_is_dropped_while_the_radio_is_silent(self):
        # ohs-box 10/10: the radio stopped, a TV reconnecting every ~7 s,
        # and status counted 20 listeners: with nothing to send, the
        # handler never wrote, so never learnt the client had gone.
        self.radio.stop()
        for _n in range(3):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
            s.sendall((f"GET /api/audio/rx HTTP/1.1\r\nHost: x\r\n{shack.SHACK_SECRET_HEADER}: {SECRET}\r\n"
                       "X-OpenHamShack-User: b\r\nX-OpenHamShack-Level: view\r\n\r\n").encode())
            f = s.makefile("rb")
            self.assertIn(b"200", f.readline())
            while f.readline() not in (b"\r\n", b""):
                pass
            # Silence, in real time, rather than nothing.
            self.assertEqual(f.read(2400), bytes(2400))
            f.close()
            s.close()
        self.assertTrue(self.wait(lambda: self.audio.listeners() == 0, timeout=8), self.audio.listeners())

    def test_remote_microphone_needs_transmit_and_feeds_the_mic(self):
        s, f = self.ws("/api/audio/tx")
        json.loads(self.frame(f)[1])
        pcm = (struct.pack("<h", 8000) * 1200)
        mask = os.urandom(4)
        payload = bytes(c ^ mask[i % 4] for i, c in enumerate(pcm))
        s.sendall(struct.pack("!BBH", 0x82, 0x80 | 126, len(pcm)) + mask + payload)
        self.assertTrue(self.wait(lambda: len(self.audio.mic) >= 1200))
        s.close()

    def test_spectrum_items_are_compact(self):
        import numpy as np
        item = spectrum_item("wide", (1.0, 10_489_500_000.0, 100.0, np.array([-100.0, -50.25, 0.0])))
        back = np.frombuffer(base64.b64decode(item["cdb"]), "<i2") / 100.0
        self.assertEqual(list(back), [-100.0, -50.25, 0.0])


@unittest.skipUnless(os.path.isdir("/proc/self/fd"), "counts open files through /proc")
class OpenFiles(ServerTest):
    """Every connection is a thread of its own, and the station store
    opens a SQLite connection per thread. Before 10/10/2026 none of those
    was ever closed: a Remote polling /api/status leaked two fds a request
    (the database and its WAL) until the server stopped on "Too many open
    files" after about 40 minutes."""

    def store_fds(self) -> int:
        path = os.path.realpath(self.radio.station.store.path)
        n = 0
        for fd in os.listdir("/proc/self/fd"):
            try:
                if os.readlink(f"/proc/self/fd/{fd}").startswith(path):
                    n += 1
            except OSError:         # closed between the listing and the look
                pass
        return n

    def test_many_requests_do_not_grow_the_open_files(self):
        # The routes that read the store (status and the page read the
        # shared log's count, /api/log its contacts), each on a new
        # connection as a polling client makes them.
        for path in ("/api/status", "/", "/api/log"):
            self.assertEqual(self.req("GET", path, level="view")[0], 200)
        before = self.store_fds()
        for i in range(150):
            path = ("/api/status", "/", "/api/log")[i % 3]
            self.assertEqual(self.req("GET", path, level="view")[0], 200)
        # The handler thread closes its connection after the response is
        # sent, so the last one may still be on its way out.
        self.assertTrue(self.wait(lambda: self.store_fds() <= before + 3),
                        f"{self.store_fds()} store files open after 150 requests, {before} before")


class NoServerInTheDesktopApp(unittest.TestCase):
    """GUIDE section 1: no servers inside the desktop apps. The window's
    import graph must not reach ohscore.server at all."""

    def test_windows_do_not_load_the_server(self):
        import subprocess
        import sys
        code = ("import sys, ohsnb.ui, ohsradio.ui, ohsnb.radio, ohsradio.radio; "
                "print(sorted(m for m in sys.modules if m.startswith(('ohscore.server', 'ohsnb.server', 'ohsradio.server'))))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
