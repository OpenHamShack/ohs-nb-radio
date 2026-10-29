"""Client presence in Radio (CLIENT-UI-PLAN 7.2-7.4; SERVER-API "Client
presence"): what a client started ends when the platform says it has
gone, and the radio goes back to the station when nobody is using it.

Radio's real server on the RSPdx-shaped simulator (listen_helpers), the
broker the in-process fake test_server.py uses, and a fake controller
speaking the presence service over real HTTP: the services map, `GET
presence` and the `presence/events` stream, under the app token, as the
platform's (dock360 f7b879d) does. A test plays the platform's part by
pushing `arrived` and `gone` events and changing who is listed.

- **Goodbye ends a client's DAB at once,** the receiver back on the dial
  and mode from before, the client's audio stream closed - and, nothing
  else holding the radio, the broker's claim released; the next client
  to arrive takes it again.
- **The same for AIS,** and a present client with "ais" in its holds
  keeps the map running without renewing AIS's own lease.
- **Station-scoped work survives:** a background decoder session keeps
  running, and keeps the radio claimed.
- **A controller restart** sends no `gone`: the reconcile after the stream
  comes back finds the client missing and, once a lease has passed
  without it returning, ends what it held.
- **Clients without presence are left alone:** a DAB station started with
  no client id, or by a client the platform has never listed, survives
  every presence event and reconcile.
- **Without the service** (an older controller) nothing is watched.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import queue
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from ohscore import sdr
from ohscore.server import presence
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import ais as aismod
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from listen_helpers import ListeningSim
from test_server import SECRET, FakeBroker

APP_TOKEN = "app-token-radio"
BLOCK, CENTRE, MP2 = "11D", 222_064_000.0, "C221"
HOME = 145_500_000.0


class FakePresence:
    """The controller's presence service as an app sees it: the services
    map, the list and the event stream, refusing anything without the app
    token. `push` sends an event to every open stream; `restart` forgets
    everyone and drops the streams, as a platform restart does."""

    def __init__(self, services=None):
        self.services = {"broker": 1, "presence": 1} if services is None else services
        self.clients: dict[str, dict] = {}
        self.streams: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.connects = 0
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.headers.get("Authorization") != f"Bearer {APP_TOKEN}":
                    self._json(401, {"error": "no token", "code": "unauthorized"})
                    return
                path = self.path.rstrip("/")
                if path == "/api/shack/v1":
                    self._json(200, {"services": fake.services, "controllerId": "c-test", "time": "now"})
                elif path == "/api/shack/v1/presence":
                    with fake.lock:
                        self._json(200, {"clients": list(fake.clients.values())})
                elif path == "/api/shack/v1/presence/events":
                    q = queue.Queue()
                    with fake.lock:
                        fake.streams.append(q)
                        fake.connects += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    try:
                        self.wfile.write(b": connected\n\n")
                        self.wfile.flush()
                        while True:
                            try:
                                item = q.get(timeout=0.5)
                            except queue.Empty:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                                continue
                            if item is None:
                                return
                            name, data = item
                            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                            self.wfile.flush()
                    except OSError:
                        pass
                    finally:
                        with fake.lock:
                            if q in fake.streams:
                                fake.streams.remove(q)
                else:
                    self._json(404, {"error": "not here", "code": "not_found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/api/shack/v1"

    def close(self):
        self.restart()
        self.httpd.shutdown()
        self.httpd.server_close()

    def push(self, name: str, data: dict) -> None:
        with self.lock:
            if name in ("arrived", "moved"):
                self.clients[data["client"]] = data
            elif name == "gone":
                self.clients.pop(data["client"], None)
            for q in self.streams:
                q.put((name, data))

    def arrive(self, client: str, holds=(), app="shack-radio") -> None:
        self.push("arrived", {"client": client, "app": app, "screen": "radio", "holds": list(holds)})

    def restart(self) -> None:
        with self.lock:
            self.clients.clear()
            for q in self.streams:
                q.put(None)

    def listening(self) -> int:
        with self.lock:
            return len(self.streams)


def wait(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def has_ais() -> bool:
    m = sdr.load()
    return m is not None and any(e["id"] == "ais" for e in m.catalogue())


class Base(unittest.TestCase):
    services = None

    def setUp(self):
        from ohsradio.devices.simdab import DabEnsemble
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
               "locator": "IO75RL"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio,
                           device=ListeningSim(dict(cfg), 2_400_000.0, [DabEnsemble(BLOCK, level_db=-30.0)]))
        self.fake = FakePresence(self.services)
        self.addCleanup(self.fake.close)
        self.broker = FakeBroker()
        info = ham_server.info("9.9.9")
        info.device_for = lambda dev: "sdrplay-1"     # the simulator stands in for the RSP the broker lends
        self.srv = Server(self.radio, info, self.audio, secret=SECRET, broker=shack.BrokerClient(self.broker))
        self.now = [1000.0]
        self.srv.presence = presence.PresenceWatch(
            info.app_id, shack.shack_http(self.fake.base, APP_TOKEN),
            presence.events_opener(self.fake.base, APP_TOKEN, timeout=5.0),
            on_gone=self.srv.client_gone, on_arrive=self.srv.client_arrived, clock=lambda: self.now[0])
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

    def status(self):
        return self.req("GET", "/api/status", level="view")[1]

    def claimed(self) -> bool:
        return bool(self.broker.claims)

    def listen(self, client=None):
        """An open api/audio/rx; a thread reads it and sets `ended` at EOF."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("GET", "/api/audio/rx" + (f"?client={client}" if client else ""),
                  headers={shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "b",
                           "X-OpenHamShack-Level": "view"})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        ended = threading.Event()

        def drain():
            try:
                while r.read(4096):
                    pass
            except OSError:
                pass
            ended.set()
            c.close()
        threading.Thread(target=drain, daemon=True).start()
        self.addCleanup(c.close)
        return ended

    def following(self):
        """The watch has the stream open and has listed who is here."""
        self.assertTrue(wait(lambda: self.srv.presence.connected and self.fake.listening() >= 1),
                        "the presence stream never opened")

    def start_dab(self, client=None):
        body = {"decoder": "dab", "freqHz": CENTRE, "params": {"block": BLOCK, "service": MP2}}
        if client:
            body["client"] = client
        s, a = self.req("POST", "/api/decoders/sessions", body)
        self.assertEqual(s, 201, a)
        self.assertEqual(self.status()["rxOwner"]["session"], a["id"])
        return a["id"]


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Goodbye(Base):
    def test_goodbye_ends_the_clients_dab_at_once_and_gives_the_radio_back(self):
        self.following()
        self.fake.arrive("tv-lounge", ["dab", "audio"])
        self.assertTrue(wait(lambda: self.status()["presence"]["clients"] == ["tv-lounge"]))
        self.start_dab("tv-lounge")
        ended = self.listen("tv-lounge")
        self.assertTrue(wait(lambda: self.status()["audio"]["listeners"] == 1))
        self.assertTrue(self.claimed())

        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        # At once: no linger, the dial and mode from before, the stream shut.
        self.assertTrue(wait(lambda: self.radio.state()["rxOwner"] == {}, 5))
        st = self.radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (HOME, "fm"))
        self.assertTrue(ended.wait(5), "the client's audio stream was left open")
        # Nothing else holds the radio: the engine stops and the claim goes.
        self.assertTrue(wait(lambda: not self.claimed(), 10), self.broker.calls[-3:])
        self.assertEqual(self.broker.paths()[-1][0], "DELETE")
        a = self.status()
        self.assertFalse(a["running"])
        self.assertTrue(a["presence"]["released"])
        self.assertEqual(a["radioError"], "")

        # The next client to open Radio takes it again, receive only.
        self.fake.arrive("phone-2")
        self.assertTrue(wait(lambda: self.claimed() and self.status()["running"], 10))
        self.assertEqual(self.broker.claim_bodies()[-1]["mode"], "rx")
        self.assertFalse(self.status()["presence"]["released"])

    def test_another_clients_stream_keeps_the_radio(self):
        # The DAB station is the gone client's alone and ends; the phone,
        # also present, is still listening, so the radio stays claimed.
        self.following()
        self.fake.arrive("tv-lounge", ["dab"])
        self.fake.arrive("phone-2", ["audio"])
        self.start_dab("tv-lounge")
        phone = self.listen("phone-2")
        self.assertTrue(wait(lambda: self.status()["audio"]["listeners"] == 1))
        self.fake.push("gone", {"client": "tv-lounge", "why": "expired"})
        self.assertTrue(wait(lambda: self.radio.state()["rxOwner"] == {}, 5))
        time.sleep(1.5)                                  # a presence tick or so
        self.assertTrue(self.claimed())
        self.assertTrue(self.status()["running"])
        self.assertFalse(phone.is_set())

    def test_a_background_decoder_survives_and_keeps_the_radio(self):
        # Station-scoped (CLIENT-UI-PLAN 7.3): a saved background session,
        # even one a client started, is never ended by presence.
        self.following()
        self.fake.arrive("tv-lounge", ["audio"])
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "rtty", "freqHz": HOME + 10_000,
                                                            "params": {}, "client": "tv-lounge"})
        self.assertEqual(s, 201, a)
        ended = self.listen("tv-lounge")
        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        self.assertTrue(ended.wait(5))
        time.sleep(1.5)
        self.assertEqual([x["id"] for x in self.radio.decoders.sessions() if x["id"] != "vfo"], [a["id"]])
        self.assertTrue(self.claimed())
        self.assertTrue(self.status()["running"])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Shutdown(unittest.TestCase):
    def test_a_stream_closed_by_stop_logs_no_traceback(self):
        # beta.18's post-install check failed on this: beta.17's watch logged
        # an AttributeError from http.client when shutdown closed its stream
        # under the reading thread. Here the read fails the same way, after
        # the stop, every time.
        w = presence.PresenceWatch("shack-radio", lambda *a, **k: None, lambda: None,
                                   on_gone=lambda *a: None, on_arrive=lambda *a: None)
        stop = threading.Event()
        w.check_service = lambda: True

        def follow(stop_ev):
            stop_ev.set()
            raise AttributeError("'NoneType' object has no attribute 'peek'")
        w.follow = follow
        with self.assertNoLogs("ohscore.server.presence", level="ERROR"):
            w.run(stop)

    def test_a_failure_while_running_is_still_logged(self):
        w = presence.PresenceWatch("shack-radio", lambda *a, **k: None, lambda: None,
                                   on_gone=lambda *a: None, on_arrive=lambda *a: None)
        stop = threading.Event()
        w.check_service = lambda: True
        calls = []

        def follow(stop_ev):
            calls.append(1)
            if len(calls) > 1:
                stop_ev.set()
                return
            raise AttributeError("a real fault")
        w.follow = follow
        with self.assertLogs("ohscore.server.presence", level="ERROR"):
            w.run(stop)


class WithoutPresence(Base):
    def test_a_station_started_with_no_client_id_survives(self):
        self.following()
        sid = self.start_dab()                           # an older client: no id
        self.fake.arrive("tv-lounge", ["audio"])
        ended = self.listen("tv-lounge")
        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        self.assertTrue(ended.wait(5))
        time.sleep(1.5)
        self.assertEqual(self.radio.state()["rxOwner"]["session"], sid)
        self.assertTrue(self.claimed())

    def test_a_client_the_platform_never_listed_is_never_judged(self):
        # It names itself, but has no presence (an older Remote on a new
        # controller): neither a gone for its id nor a reconcile ends it.
        self.following()
        sid = self.start_dab("old-tv")
        self.fake.push("gone", {"client": "old-tv", "why": "expired"})
        self.fake.restart()
        self.assertTrue(wait(lambda: self.fake.connects >= 2 and self.srv.presence.connected, 10))
        self.now[0] += presence.LEASE_S + 1
        time.sleep(1.5)
        self.assertEqual(self.radio.state()["rxOwner"]["session"], sid)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Restart(Base):
    def test_a_client_missing_after_a_controller_restart_is_gone_a_lease_later(self):
        self.following()
        self.fake.arrive("tv-lounge", ["dab"])
        self.start_dab("tv-lounge")
        # The controller restarts: the stream drops, nobody is listed, and
        # no gone is ever sent.
        self.fake.restart()
        self.assertTrue(wait(lambda: self.fake.connects >= 2 and self.srv.presence.connected, 10))
        time.sleep(1.5)
        # Within a lease a client still there comes back: nothing ended yet.
        self.assertNotEqual(self.radio.state()["rxOwner"], {})
        self.now[0] += presence.LEASE_S + 1
        self.assertTrue(wait(lambda: self.radio.state()["rxOwner"] == {}, 5))
        self.assertEqual(self.radio.state()["vfo"], HOME)

    def test_a_client_that_comes_back_in_time_keeps_its_station(self):
        self.following()
        self.fake.arrive("tv-lounge", ["dab"])
        sid = self.start_dab("tv-lounge")
        self.fake.restart()
        self.assertTrue(wait(lambda: self.fake.connects >= 2 and self.srv.presence.connected, 10))
        self.fake.arrive("tv-lounge", ["dab"])
        self.assertTrue(wait(lambda: self.status()["presence"]["clients"] == ["tv-lounge"]))
        self.now[0] += presence.LEASE_S + 1
        time.sleep(1.5)
        self.assertEqual(self.radio.state()["rxOwner"]["session"], sid)


@unittest.skipUnless(has_ais(), "no shack_sdr with AIS for this machine")
class Ais(Base):
    def test_goodbye_ends_the_ship_map_at_once(self):
        self.following()
        self.fake.arrive("tv-lounge", ["ais"])
        s, a = self.req("POST", "/api/ais/session", {"client": "tv-lounge"})
        self.assertEqual((s, a["state"], a["lingerS"]), (200, "running", 0.0), a)
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "ais")
        self.fake.push("gone", {"client": "tv-lounge", "why": "goodbye"})
        self.assertTrue(wait(lambda: self.radio.ais.state == "idle", 5))
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, HOME, "fm"))
        self.assertTrue(wait(lambda: not self.claimed(), 10))

    def test_presence_renews_the_map_for_a_present_client(self):
        # A present client with "ais" in its holds need not renew AIS's own
        # lease (7.2); one without presence still must.
        self.following()
        self.fake.arrive("tv-lounge", ["ais"])
        self.assertTrue(wait(lambda: self.status()["presence"]["clients"] == ["tv-lounge"]))
        with mock.patch.object(aismod, "CLIENT_LEASE_S", 0.3):
            self.req("POST", "/api/ais/session", {"client": "tv-lounge"})
            self.req("POST", "/api/ais/session", {"client": "old-tv"})
            self.assertTrue(wait(lambda: self.radio.ais.view()["clients"] == 1, 5))
            time.sleep(1.0)
            self.assertEqual((self.radio.ais.state, list(self.radio.ais.clients)), ("running", ["tv-lounge"]))


class NoService(unittest.TestCase):
    def test_an_older_controller_is_not_followed(self):
        fake = FakePresence(services={"broker": 1})
        self.addCleanup(fake.close)
        gone = []
        w = presence.PresenceWatch("shack-radio", shack.shack_http(fake.base, APP_TOKEN),
                                   presence.events_opener(fake.base, APP_TOKEN), on_gone=lambda c, y: gone.append(c))
        stop = threading.Event()
        t = threading.Thread(target=w.run, args=(stop,), daemon=True)
        t.start()
        self.assertTrue(wait(lambda: w.available is False))
        stop.set()
        t.join(5)
        self.assertEqual((fake.connects, w.connected, w.view()["service"]), (0, False, False))
        self.assertFalse(w.governs("tv-lounge"))


class EventStream(unittest.TestCase):
    def test_events_are_read_as_the_platform_frames_them(self):
        lines = [b": connected\n", b"\n", b"event: gone\n", b'data: {"client":"tv-1","why":"goodbye"}\n', b"\n",
                 b": keepalive\n", b"\n", b"event: arrived\n", b'data: {"client":"tv-2",\n',
                 b'data: "app":"shack-radio"}\n', b"\n"]
        self.assertEqual(list(presence.sse_events(lines)),
                         [("gone", {"client": "tv-1", "why": "goodbye"}),
                          ("arrived", {"client": "tv-2", "app": "shack-radio"})])


if __name__ == "__main__":
    unittest.main()
