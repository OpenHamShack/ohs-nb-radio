"""Radio's ui/2 screens (openhamshack docs/contract/SCREENS.md, step 5 of
§16): ui/v2/app, ui/v2/status, ui/v2/screen, ui/v2/live, ui/v2/poll and
ui/v2/hold over real HTTP and WebSocket on loopback, on the RSPdx-shaped
simulator. A client is played as a renderer plays it: it reads the
document, runs its holds and presses its actions (placeholders and item
fields filled in), and applies the live frames to the document's state
with shack_ui's reference applier, the one the contract's vectors pin.

- **Every document** a launcher entry opens, on every form it is offered
  to, passes the contract's rules (shack_ui check(), which the vectors
  hold every renderer to) and the schema the wheel carries; keeps to the client's icon set; places nothing that keys; and
  every call it makes reaches a route at the level it declares, refused
  one level lower.
- **The request:** ETag and 304, 406 for another ui major, 404 for an
  unknown screen and for NB, which serves none; X-Forwarded-Prefix never
  makes a path absolute; the document's level is the proxy's.
- **Aircraft, end to end:** the hold starts ADS-B, the socket's hello is
  the document's rev, the snap and frames bring the simulator's aircraft
  with growing trails, selecting one sends that client its photo, and
  the hold's stop gives the receiver back.
- **Home, FM and DAB:** the dial, mode and volume; the band scan's
  stations arrive over the socket and a tile tunes or plays; the DAB
  station is the client's (presence ends it).
- **Ships, APRS and Sondes:** what the tables hold arrives as items with
  the fields the templates name, and the holds start their sessions.
- **DMR:** the hold starts a session on the channel, two clients share
  it, it stops when the last lets go or its presence goes, and the calls
  and slots arrive over the socket.
- **Weather Sats:** polled, no socket and no hold; the passes arrive with
  their own record or skip action, which works.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import http.client
import json
import os
import socket
import struct
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote, urlencode

from ohscore import sdr, shacklibs
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsnb import server as nb_server
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from ham_helpers import pump
from listen_helpers import ListeningSim
from test_server import SECRET

ui = shacklibs.ui()
HOME = 145_500_000.0
LOWER = {"control": "view", "view": "none"}
TV = "tv-lounge"


def cfg_for(**over):
    return {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
            "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
            "locator": "IO75RL", **over}


def serve(test, stations=(), fm_and_dab=False, device=True, **over):
    """A Radio on the simulator behind the store server; (radio, server, port)."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    cfg = cfg_for(**over)
    audio = StreamAudio(realtime=False)
    kw = {}
    if device:
        dev = ListeningSim(dict(cfg), 2_400_000.0, list(stations))
        if fm_and_dab:
            from test_ham_bandscan import on_air
            on_air(dev)
        kw["device"] = dev
    radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, **kw)
    srv = Server(radio, ham_server.info("9.9.9"), audio, secret=SECRET)
    port = srv.serve("127.0.0.1", 0).server_address[1]
    test.addCleanup(srv.shutdown)
    test.assertEqual(srv.start_radio(), "")
    return radio, srv, port


def headers(level="control", client=TV, form="tv", extra=None):
    return {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
            "X-OpenHamShack-Device": "dev_TV", "X-OpenHamShack-Auth": "device", "X-OpenHamShack-UI": "2.0",
            "X-OpenHamShack-Form": f"{form}; w=960; h=540", "X-OpenHamShack-Client": client, **(extra or {})}


def fill(value, item=None, client=TV, val=None):
    """An action's body or params as a renderer sends it: $client, $value
    and {"$": field} of the item filled in (SCREENS.md §5.2)."""
    if value == "$client":
        return client
    if value == "$value":
        return val
    if isinstance(value, dict):
        if set(value) == {"$"}:
            return (item or {}).get(value["$"])
        return {k: fill(v, item, client, val) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, item, client, val) for v in value]
    return value


def calls(obj):
    """Every call action anywhere in a document (holds, keys, templates,
    banners' remedies), each once."""
    if isinstance(obj, dict):
        if obj.get("do") == "call":
            yield obj
        for v in obj.values():
            yield from calls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from calls(v)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def part(doc, pid):
    (got,) = [p for p, _w, _t in ui.iter_parts(doc["root"]) if p.get("id") == pid]
    return got


class Live:
    """A ui/2 live socket as a client holds one: the document's state, and
    each frame applied to it with the reference applier."""

    def __init__(self, c, doc, client=TV, level="control"):
        self.c, self.doc = c, doc
        self.start = ui.state_from_document(doc)
        self.state = self.start
        h = headers(level, client, doc["form"])
        self.s = socket.create_connection(("127.0.0.1", c.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        lines = "".join(f"{k}: {v}\r\n" for k, v in h.items())
        self.s.sendall((f"GET /{doc['live']['path']} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                        f"{lines}\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self.buf += self.s.recv(4096)
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        assert b" 101 " in head.split(b"\r\n")[0], head
        self.hello = self.recv()
        self.send({"t": "hello", "maxHz": 20, "client": client})

    def _fill(self, n):
        # A plain buffer, not makefile(): a file object is unusable after
        # one timeout, and until() waits with short ones. What arrived
        # before a timeout stays here for the next call.
        while len(self.buf) < n:
            got = self.s.recv(65536)
            if not got:
                raise ConnectionError("closed")
            self.buf += got

    def recv(self):
        """The next text frame, as JSON."""
        while True:
            self._fill(2)
            n, off = self.buf[1] & 0x7F, 2
            if n == 126:
                self._fill(4)
                n, off = struct.unpack("!H", self.buf[2:4])[0], 4
            elif n == 127:
                self._fill(10)
                n, off = struct.unpack("!Q", self.buf[2:10])[0], 10
            self._fill(off + n)
            op, data, self.buf = self.buf[0] & 0x0F, self.buf[off:off + n], self.buf[off + n:]
            if op == 0x1:
                return json.loads(data)

    def send(self, msg):
        data = json.dumps(msg).encode()
        mask = os.urandom(4)
        head = struct.pack("!BB", 0x81, 0x80 | len(data)) if len(data) < 126 else \
            struct.pack("!BBH", 0x81, 0x80 | 126, len(data))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def until(self, cond, timeout=60.0, radio=None):
        """Frames applied until cond(state); the state then."""
        end = time.monotonic() + timeout
        self.s.settimeout(0.2)
        while time.monotonic() < end:
            if cond(self.state):
                return self.state
            if radio is not None:
                radio.heartbeat()
            try:
                frame = self.recv()
            except (socket.timeout, TimeoutError):
                continue
            if frame.get("t") in ("snap", "p"):
                self.state = ui.apply_frame(self.state, frame, self.start)
        raise AssertionError(f"not reached in {timeout} s: {json.dumps(ui.public_state(self.state))[:2000]}")

    def items(self, coll):
        c = self.state["collections"].get(coll) or {"items": {}}
        return {k: c["items"][k] for k in ui.drawn_keys(self.state, coll)}

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class Client:
    """A ui/2 client over loopback, signed in by the controller's proxy."""

    def __init__(self, test, port, client=TV):
        self.t, self.port, self.client = test, port, client

    def req(self, method, path, body=None, level="control", extra=None, form="tv"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Content-Type": "application/json", **headers(level, self.client, form, extra)}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if raw else None), dict(r.getheaders())

    def screen(self, sid, params=None, form="tv", level="control", extra=None):
        q = f"?{urlencode(params)}" if params else ""
        s, doc, _h = self.req("GET", f"/ui/v2/screen/{sid}{q}", level=level, form=form, extra=extra)
        self.t.assertEqual(s, 200, doc)
        self.t.assertEqual(ui.check(doc), [])
        self.t.assertEqual(ui.schema_errors(doc), [])
        self.t.assertEqual((doc["screen"], doc["form"], doc["level"]), (sid, form, level))
        return doc

    def press(self, action, item=None, value=None, expect=(200, 201, 202), lower=True):
        """A call as the renderer makes it, at its declared level - and
        first one level lower, which the route must refuse."""
        t = self.t
        t.assertEqual(action["do"], "call")
        t.assertIn(action["level"], ("view", "control"))
        path = action["path"].replace("{$client}", quote(self.client))
        t.assertFalse(path.startswith("/"), action)
        body = fill(action.get("body"), item, self.client, value)
        if lower:
            s, a, _h = self.req(action["method"], "/" + path, body, level=LOWER[action["level"]])
            t.assertEqual((s, (a or {}).get("code")), (403, "level_too_low"), (action, a))
        s, a, _h = self.req(action["method"], "/" + path, body, level=action["level"])
        t.assertIn(s, expect, (action, a))
        return s, a

    def hold(self, doc, name, verb="start", **kw):
        (h,) = [h for h in doc.get("holds") or [] if h["name"] == name]
        return self.press(h[verb], **kw)

    def live(self, doc, **kw):
        lv = Live(self, doc, client=kw.pop("client", self.client), **kw)
        self.t.addCleanup(lv.close)
        self.t.assertEqual(lv.hello["t"], "hello")
        self.t.assertEqual(lv.hello["rev"], doc["rev"])
        return lv


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheDocuments(unittest.TestCase):
    def setUp(self):
        self.radio, self.srv, port = serve(self)
        self.c = Client(self, port)

    def test_every_entry_opens_a_valid_screen_on_every_form_it_is_offered_to(self):
        s, app, _h = self.c.req("GET", "/ui/v2/app", level="view")
        self.assertEqual(s, 200)
        self.assertEqual((app["ui"], app["app"], app["kind"], app["minClient"]), ("2.0", "shack-radio", "radio", "2.0"))
        self.assertEqual([e["id"] for e in app["entries"]],
                         ["radio", "dab", "fm", "ships", "aircraft", "wxsat", "aprs", "sonde", "dmr"])
        icons = ui.icon_names()
        opened = []
        for e in app["entries"]:
            self.assertIn(e["icon"], icons)
            for form in e["forms"]:
                doc = self.c.screen(e["screen"], form=form)
                opened.append(doc)
                used = {p["name"] for p, _w, _t in ui.iter_parts(doc["root"]) if isinstance(p.get("name"), str)
                        and p.get("type") == "icon"} | {p["icon"] for p, _w, _t in ui.iter_parts(doc["root"])
                                                         if isinstance(p.get("icon"), str)}
                self.assertLessEqual(used, icons, e["screen"])
                # Receive only: nothing that keys, and no call above control.
                self.assertFalse([p for p, _w, _t in ui.iter_parts(doc["root"]) if p.get("type") in ("ptt", "txArm")])
                for a in calls(doc):
                    self.assertIn(a["level"], ("view", "control"), a)
                    self.assertFalse(a.get("tx"), a)
        # Also those opened from inside one: a DMR channel and a picture.
        opened.append(self.c.screen("radio/dmr", {"f": "439612500"}))
        opened.append(self.c.screen("radio/wxsat/viewer", {"image": "none"}))
        # Every map holds its receiver session under presence's name.
        holds = {d["screen"]: [h["name"] for h in d.get("holds") or []] for d in opened}
        self.assertEqual({k: v for k, v in holds.items() if v},
                         {"radio/ships": ["ais"], "radio/aircraft": ["adsb"], "radio/aprs": ["aprs"],
                          "radio/sonde": ["sonde"], "radio/dmr": ["dmr"]})
        # Weather Sats is polled and holds nothing; every other screen with
        # data has a socket.
        wx = next(d for d in opened if d["screen"] == "radio/wxsat")
        self.assertEqual((wx.get("live"), wx["poll"]["path"]), (None, "ui/v2/poll/radio/wxsat"))

    def test_every_hold_reaches_its_route_at_its_level(self):
        for sid, name in (("radio/ships", "ais"), ("radio/aircraft", "adsb"), ("radio/aprs", "aprs"),
                          ("radio/sonde", "sonde")):
            doc = self.c.screen(sid)
            (h,) = doc["holds"]
            self.assertEqual(h["start"]["timeoutS"], 30)
            # The stop first (nothing to stop yet answers 200): the start
            # would take the receiver from the next map's test.
            self.c.hold(doc, name, "stop")
            s, a, _h = self.c.req("POST", "/" + h["start"]["path"], fill(h["start"]["body"]), level="view")
            self.assertEqual((s, a["code"]), (403, "level_too_low"))

    def test_the_request(self):
        for sid in ("radio/home", "radio/aircraft", "radio/wxsat", "radio/dab"):
            doc = self.c.screen(sid, extra={"X-Forwarded-Prefix": "/apps/radio"})
            self.assertFalse([s for s in strings(doc) if s.startswith("/") or s.startswith("http")], sid)
        # The level is the proxy's: a view-level device is told so in the document.
        self.assertEqual(self.c.screen("radio/home", level="view")["level"], "view")
        s, doc, h = self.c.req("GET", "/ui/v2/screen/radio/fm", level="view")
        self.assertEqual(h["ETag"], f'"{doc["rev"]}"')
        s, body, _h = self.c.req("GET", "/ui/v2/screen/radio/fm", level="view", extra={"If-None-Match": h["ETag"]})
        self.assertEqual((s, body), (304, None))
        s, a, _h = self.c.req("GET", "/ui/v2/screen/radio/fm", level="view", extra={"X-OpenHamShack-UI": "3.0"})
        self.assertEqual((s, a["code"], a["ui"]), (406, "ui_unsupported", ["2.0"]))
        s, a, _h = self.c.req("GET", "/ui/v2/screen/radio/nothing", level="view")
        self.assertEqual((s, a["code"]), (404, "unknown_screen"))
        s, a, _h = self.c.req("GET", "/ui/v2/live/radio/wxsat", level="view")
        self.assertEqual((s, a["code"]), (404, "unknown_screen"))
        s, a, _h = self.c.req("GET", "/ui/v2/app", level="none")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))
        s, a, _h = self.c.req("DELETE", "/ui/v2/hold/dmr?f=439612500", level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))

    def test_a_key_a_remote_may_lack_is_never_the_only_way(self):
        # SCREENS §8.2: a Siri Remote has no chUp/chDown/rew/ff/info and
        # neither remote has digits, so whatever those keys do must also be
        # a focusable part on the screen (the Apple TV renderer found the
        # maps' zoom reachable by keys alone). The home screen's band keys
        # step through the band plan; their on-screen route is the Bands
        # panel, which tunes any band directly.
        optional = {"chUp", "chDown", "rew", "ff", "info", *"0123456789"}

        def strip(a):
            return {k: v for k, v in a.items() if k not in ("hint", "label")} if isinstance(a, dict) else a

        def walk(node, keyed, actions):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "keys" and isinstance(v, dict):
                        keyed += [(name, strip(a)) for name, a in v.items() if name in optional]
                    else:
                        if isinstance(v, dict) and "do" in v:
                            actions.append(strip(v))
                        walk(v, keyed, actions)
            elif isinstance(node, list):
                for v in node:
                    if isinstance(v, dict) and "do" in v:
                        actions.append(strip(v))
                    walk(v, keyed, actions)

        for sid in ("radio/home", "radio/fm", "radio/dab", "radio/ships", "radio/aircraft", "radio/aprs",
                    "radio/sonde", "radio/dmr", "radio/wxsat"):
            doc = self.c.screen(sid)
            keyed, actions = [], []
            walk(doc, keyed, actions)
            for name, a in keyed:
                if sid in ("radio/home", "radio/fm") and a.get("body", {}).get("action") == "band":
                    self.assertTrue(any(x == {"do": "show", "part": "bands"}
                                        for x in actions), sid)
                    continue
                self.assertIn(a, actions, f"{sid}: {name} has no on-screen route")

    def test_nb_serves_its_own_screens_not_radios(self):
        # QO-100 NB has screens of its own (ohsnb/screens.py, its tests in
        # test_nb_screens.py); none of Radio's reach it.
        srv = Server(self.radio, nb_server.info("9.9.9"), StreamAudio(realtime=False), secret=SECRET)
        port = srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(srv.shutdown)
        s, a, _h = Client(self, port).req("GET", "/ui/v2/app", level="view")
        self.assertEqual((s, a["app"]), (200, "shack-qo100nb"))
        s, a, _h = Client(self, port).req("GET", "/ui/v2/screen/radio/fm", level="view")
        self.assertEqual((s, a["code"]), (404, "unknown_screen"))

    def test_status_says_what_each_tile_is_doing(self):
        s, st, _h = self.c.req("GET", "/ui/v2/status", level="view")
        self.assertEqual(st["entries"]["radio"]["tone"], "good")
        self.assertIn("MHz", st["entries"]["radio"]["status"])
        self.c.req("POST", "/api/stop")
        st = self.c.req("GET", "/ui/v2/status", level="view")[1]
        self.assertEqual(st["entries"]["radio"], {"status": "Stopped", "tone": "muted"})


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class Home(unittest.TestCase):
    def setUp(self):
        self.radio, self.srv, port = serve(self)
        self.c = Client(self, port)

    def test_the_dial_mode_and_volume_follow_the_radio_and_tune_it(self):
        doc = self.c.screen("radio/home")
        lv = self.c.live(doc)
        st = lv.until(lambda st: st["parts"]["dial"].get("value") == HOME, radio=self.radio)
        # The band and its range, as the TV's readout says them.
        self.assertEqual((st["parts"]["bandLine"]["value"], st["parts"]["bandRange"]["value"]),
                         ("2 m · FM simplex", "144 – 146 MHz"))
        self.c.press(part(doc, "dial")["action"], value=145_600_000)
        self.c.press(part(doc, "mode")["action"], value="am")
        self.c.press(part(doc, "volume")["action"], value=0.25)
        st = lv.until(lambda st: st["parts"]["dial"]["value"] == 145_600_000
                      and st["parts"]["mode"]["value"] == "am" and st["parts"]["volume"]["value"] == 0.25,
                      radio=self.radio)
        self.assertEqual(st["parts"]["running"]["tone"], "good")
        self.assertTrue(st["parts"]["rxOwner"]["hidden"])
        # The S-meter always has a number, so it is always drawn.
        self.assertIsInstance(st["parts"]["smeter"]["value"], (int, float))
        band = self.radio.state()["band"]
        self.c.press(doc["keys"]["chUp"])
        self.assertNotEqual(self.radio.state()["band"], band)
        # A tap on the waterfall tunes to the frequency under the finger.
        self.c.press(part(doc, "scope")["tap"] | {"body": {"changes": {"vfo": 145_700_000}}})
        self.assertEqual(self.radio.state()["vfo"], 145_700_000)

    def test_the_step_the_phone_s_tuning_and_the_bands(self):
        doc = self.c.screen("radio/home", form="phone")
        lv = self.c.live(doc)
        lv.until(lambda st: st["parts"]["stepText"].get("value") == "100 Hz", radio=self.radio)
        # ▶ on the step control, then ▶ beside the dial tunes up by it.
        larger = next(p for p, _w, _t in ui.iter_parts(doc["root"]) if p.get("label") == "Larger step")
        up = next(p for p, _w, _t in ui.iter_parts(doc["root"]) if p.get("label") == "Tune up")
        self.c.press(larger["action"])
        st = lv.until(lambda st: st["parts"]["stepText"]["value"] == "1 kHz", radio=self.radio)
        self.assertEqual(st["parts"]["dial"]["step"], 1000)
        self.c.press(up["action"])
        self.assertEqual(self.radio.state()["vfo"], HOME + 1000)
        # A band from the Bands panel: its spot, dial and mode in one set.
        st = lv.until(lambda st: "70cm" in st["collections"]["bands"]["items"], radio=self.radio)
        b = st["collections"]["bands"]["items"]["70cm"]
        self.assertEqual((b["label"], b["rangeText"]), ("70 cm", "430 – 440 MHz"))
        (call, hide) = part(doc, "bandList")["onActivate"]["actions"]
        self.c.press(call, item=b)
        self.assertEqual((self.radio.state()["band"], self.radio.state()["vfo"]), ("70cm", b["vfo"]))
        self.assertEqual(hide, {"do": "hide", "part": "bands"})


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class FmAndDab(unittest.TestCase):
    def setUp(self):
        self.radio, self.srv, port = serve(self, fm_and_dab=True)
        sc = self.radio.bandscan
        # Two FM stations and the one DAB block: seconds, not minutes.
        sc.fm_lo, sc.fm_hi = 87_500_000, 95_000_000
        sc.dab_blocks = ["11C", "11D"]
        self.c = Client(self, port)

    def test_fm_lists_the_scan_and_a_row_tunes_it(self):
        from test_ham_bandscan import scanned
        doc = self.c.screen("radio/fm")
        lv = self.c.live(doc)
        empty = part(doc, "byFreqList")["empty"]
        s, a = self.c.press(empty["action"])
        self.assertEqual(a["bands"], ["fm"])
        self.assertTrue(scanned(self.radio))
        lv.until(lambda st: len(ui.drawn_keys(st, "byFreq")) == 2, radio=self.radio)
        rows = lv.items("byFreq")
        self.assertEqual([r["hz"] for r in rows.values()], [88_600_000, 93_500_000])
        names = [r["name"] for r in lv.items("byName").values()]
        self.assertEqual(names, sorted(names, key=str.lower))
        first = next(iter(rows.values()))
        self.c.press(part(doc, "byFreqList")["onActivate"], item=first)
        st = self.radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (88_600_000, "wfm"))
        self.c.press(part(doc, "dial")["action"], value=93_500_000)
        self.assertEqual(self.radio.state()["vfo"], 93_500_000)

    def test_dab_plays_a_tile_for_this_client_and_stop_gives_the_receiver_back(self):
        from test_ham_bandscan import scanned
        doc = self.c.screen("radio/dab")
        lv = self.c.live(doc)
        s, a = self.c.press(part(doc, "stationGrid")["empty"]["action"])
        self.assertEqual(a["bands"], ["dab"])
        self.assertTrue(scanned(self.radio))
        lv.until(lambda st: len(ui.drawn_keys(st, "stations")) == 2, radio=self.radio)
        tiles = lv.items("stations")
        self.assertEqual(sorted(t["sid"] for t in tiles.values()), ["C221", "C3A7"])
        tile = part(doc, "stationGrid")["template"]
        c221 = next(t for t in tiles.values() if t["sid"] == "C221")
        self.c.press(tile["action"], item=c221)
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "dab")
        st = lv.until(lambda st: st["parts"]["service"]["value"] == "Shack MP2 Tone" and st["parts"]["dls"]["value"]
                      and any(t["playing"] for t in st["collections"]["stations"]["items"].values()),
                      timeout=120, radio=self.radio)
        self.assertEqual(st["parts"]["ensemble"]["value"], "Shack Test Mux · 11D")
        # The station is this client's: its presence going ends it, and
        # closes its socket as it closes its other streams.
        self.srv.client_gone(TV, "expired")
        self.assertEqual(self.radio.state()["rxOwner"], {})
        with self.assertRaises((ConnectionError, OSError)):
            lv.until(lambda st: False, timeout=10)
        self.c.press(tile["action"], item=c221)
        lv = self.c.live(doc)
        lv.until(lambda st: st["parts"]["service"]["value"] == "Shack MP2 Tone", timeout=60, radio=self.radio)
        self.c.press(doc["keys"]["play"])
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, HOME, "fm"))
        lv.until(lambda st: st["parts"]["service"]["value"] == "Not playing", radio=self.radio)


def has_adsb():
    from test_ham_adsb import has_adsb as has
    return has()


@unittest.skipUnless(has_adsb(), "no shack_sdr with ADS-B for this machine")
class Aircraft(unittest.TestCase):
    def setUp(self):
        from test_ham_adsb import air
        self.radio, self.srv, port = serve(self, [air("SIM202", "SIM303")], sampleRate=2_400_000)
        self.c = Client(self, port)

    def test_the_hold_the_socket_the_trails_and_the_photo(self):
        doc = self.c.screen("radio/aircraft")
        self.assertEqual(doc["collections"]["aircraft"]["items"], {})     # the socket fills it
        s, a = self.c.hold(doc, "adsb")
        self.assertEqual((a["state"], a["clients"]), ("running", 1))
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "adsb")
        lv = self.c.live(doc)
        lv.until(lambda st: {"F00202", "F00303"} <= set(ui.drawn_keys(st, "aircraft")), timeout=90, radio=self.radio)
        it = lv.items("aircraft")["F00202"]
        self.assertEqual((it["title"], it["label"]), ("SIM202", "SIM202"))
        self.assertTrue(it["tone"].startswith("band.") and it["sym"] in ("jet", "heavy", "light", "rotor", "other"))
        self.assertTrue(any(t.startswith("band:") for t in it["tags"]) and "airborne" in it["tags"])
        self.assertRegex(it["distText"], r"^[0-9.]+ nm · [0-9]+°$")    # nm at sea and in the air
        # Trails grow as the aircraft move, a point at a time.
        lv.until(lambda st: len(st["collections"]["aircraft"]["items"]["F00202"].get("trail") or []) >= 2,
                 timeout=90, radio=self.radio)
        self.assertEqual(lv.state["parts"]["status"]["tone"], "good")
        # Selecting one sends this client its photo (none here: no lookup).
        lv.send({"t": "select", "sel": "aircraft", "key": "F00202"})
        lv.until(lambda st: "photo" in st["collections"]["aircraft"]["items"]["F00202"], radio=self.radio)
        self.assertEqual(lv.state["collections"]["aircraft"]["items"]["F00202"]["photo"], {"src": None})
        # A photo found after the selection reaches this client, and only it.
        other = self.c.live(doc, client="phone-1")
        found = {"src": "https://t.plnspttrs.net/1/2_280.jpg", "credit": "© A Photographer",
                 "link": "https://www.planespotters.net/photo/1"}
        table = self.radio.adsb.table
        real = table.aircraft
        table.aircraft = lambda k: (real(k) or {}) | ({"photo": found} if k == "F00202" else {})
        st = lv.until(lambda st: st["collections"]["aircraft"]["items"]["F00202"]["photo"].get("src"),
                      radio=self.radio)
        self.assertEqual(st["collections"]["aircraft"]["items"]["F00202"]["photo"]["credit"], "© A Photographer")
        other.until(lambda st: "F00202" in st["collections"]["aircraft"]["items"], radio=self.radio)
        self.assertNotIn("photo", other.items("aircraft")["F00202"])
        table.aircraft = real
        # The hold's stop: nobody is left, and the receiver is the operator's.
        s, a = self.c.hold(doc, "adsb", "stop")
        self.assertEqual(a["clients"], 0)
        pump(self.radio, 10, until=lambda: self.radio.state()["rxOwner"] == {})
        self.assertEqual(self.radio.state()["rxOwner"], {})

    def test_a_count_reads_as_a_whole_number(self):
        from ohsradio.screens import traffic
        # The decoder sends 2034.0; the TV drew "2,034.0" (31/10/2026).
        self.assertEqual(traffic.aircraft_item({"icao": "406A93", "messages": 2034.0})["messagesText"], "2,034")
        self.assertIsNone(traffic.aircraft_item({"icao": "406A93"})["messagesText"])

    def test_altitude_reads_in_feet(self):
        from ohsradio.screens import traffic
        self.assertEqual(traffic.aircraft_item({"icao": "406A93", "altBaro": 33000})["sub"], "33,000 ft")
        self.assertEqual(traffic.aircraft_item({"icao": "406A93", "altBaro": 4500})["sub"], "4,500 ft")
        self.assertEqual(traffic.aircraft_item({"icao": "406A93", "onGround": True})["sub"], "Ground")

    def test_the_photo_follows_planespotters_terms(self):
        from ohsradio.screens import traffic
        icao = "F00202"
        self.radio.adsb.table.heard({"icao": icao, "callsign": "SIM202", "category": "A3", "lat": 55.5, "lon": -4.9,
                                     "posT": time.time(), "altBaro": 4000, "gs": 200.0, "track": 90.0,
                                     "onGround": False, "messages": 3, "firstT": time.time()}, time.time())
        a = self.radio.adsb.table.aircraft(icao)
        a["photo"] = {"src": "https://t.plnspttrs.net/1/2_280.jpg", "credit": "© A Photographer",
                      "link": "https://www.planespotters.net/photo/1"}
        self.radio.adsb.table.aircraft = lambda k: a if k == icao else None
        got = traffic.selected_fields(self.radio, icao)["photo"]
        self.assertEqual((got["src"], got["credit"], got["link"]), (a["photo"]["src"], "© A Photographer",
                                                                   "https://www.planespotters.net/photo/1"))
        # The details draw it with the credit and the link as a QR code.
        doc = self.c.screen("radio/aircraft")
        (img,) = [p for p, _w, _t in ui.iter_parts(doc["root"]) if p.get("type") == "image"]
        self.assertEqual((img["src"], img["credit"], img["link"], img["qr"]),
                         ({"$": "photo.src"}, {"$": "photo.credit"}, {"$": "photo.link"}, True))
        # And the document is valid with that item in it: the host is allowed.
        d = json.loads(json.dumps(doc))
        d["collections"]["aircraft"]["items"][icao] = {"photo": got}
        self.assertEqual(ui.check(d), [])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheOtherMaps(unittest.TestCase):
    """What the tables hold reaches the screens; no decoder is needed, so
    the tables are given what a decoder would have put there."""

    def setUp(self):
        self.radio, self.srv, port = serve(self)
        self.c = Client(self, port)

    def test_ships(self):
        t = time.time()
        self.radio.ais.table.heard({"type": 1, "mmsi": 235000001, "lat": 55.5, "lon": -4.9, "speed": 12.3,
                                    "course": 271.0, "heading": 270.0, "navStatus": 0, "turn": 0.0, "channel": "A",
                                    "snrDb": 20.0}, t)
        self.radio.ais.table.heard({"type": 5, "mmsi": 235000001, "shipName": "MV TEST", "callsign": "MABC1",
                                    "shipType": 80, "toBow": 100, "toStern": 30, "toPort": 10, "toStarboard": 12,
                                    "destination": "GLASGOW", "channel": "B"}, t + 1)
        doc = self.c.screen("radio/ships")
        lv = self.c.live(doc)
        lv.until(lambda st: "235000001" in st["collections"]["vessels"]["items"])
        v = lv.items("vessels")["235000001"]
        self.assertEqual((v["title"], v["sym"], v["tone"], v["destination"], v["rot"]),
                         ("MV TEST", "vessel", "ship.tanker", "GLASGOW", 270.0))
        self.assertEqual(v["tags"], ["type:tanker", "moving"])
        self.assertEqual(v["sizeText"], "130 × 22 m")
        self.assertEqual(v["speedText"], "12.3 kn")
        # A ship that moves gains a trail point.
        self.radio.ais.table.heard({"type": 1, "mmsi": 235000001, "lat": 55.51, "lon": -4.91, "speed": 12.3,
                                    "course": 271.0, "heading": 270.0, "navStatus": 0, "channel": "A"}, t + 20)
        lv.until(lambda st: len(st["collections"]["vessels"]["items"]["235000001"]["trail"]) == 2)

    def test_a_ships_flag_port_details_and_photo(self):
        from ohsradio.screens import traffic
        t = time.time()
        table = self.radio.ais.table
        table.heard({"type": 1, "mmsi": 235103359, "lat": 55.6, "lon": -5.0, "speed": 18.0, "channel": "A"}, t)
        table.heard({"type": 5, "mmsi": 235103359, "shipName": "LOCH SEAFORTH", "imo": 9665437, "shipType": 60,
                     "destination": "GBSTO", "channel": "B"}, t + 1)
        # Wikidata's answer as shipinfo.py gives it (test_ham_shipinfo.py
        # fetches it from a fake Wikimedia); here only what the screen does.
        details = {"qid": "Q11713805", "label": "MV Loch Seaforth", "builder": "Flensburger Schiffbau-Gesellschaft",
                   "built": "2015", "operator": "Caledonian MacBrayne", "grossTonnage": 8680,
                   "homePort": "Stornoway", "source": "wikidata",
                   "photo": {"credit": "Mn28 · CC BY-SA 3.0",
                             "link": "https://commons.wikimedia.org/wiki/File:Loch_Seaforth.jpg"}}
        found = [None]
        table.info_lookup = lambda v: json.loads(json.dumps(found[0])) if v["mmsi"] == 235103359 else None
        doc = self.c.screen("radio/ships")
        lv = self.c.live(doc)
        lv.until(lambda st: "235103359" in st["collections"]["vessels"]["items"])
        v = lv.items("vessels")["235103359"]
        # The flag and the port are in every item: bundled tables, no lookup.
        self.assertEqual((v["kindLine"], v["idLine"]), ("Passenger · 🇬🇧 United Kingdom", "235103359 · IMO 9665437"))
        self.assertEqual((v["destination"], v["destLine"], v["destCode"]), ("Stornoway", "→ Stornoway", "GBSTO"))
        # Selecting it before Wikidata has answered: no details, no photo.
        lv.send({"t": "select", "sel": "vessels", "key": "235103359"})
        lv.until(lambda st: "photo" in st["collections"]["vessels"]["items"]["235103359"], radio=self.radio)
        got = lv.items("vessels")["235103359"]
        self.assertEqual((got["photo"], got.get("aboutLine"), got.get("builtLine")), ({"src": None}, None, None))
        # The answer arriving reaches this client, and only it.
        other = self.c.live(doc, client="phone-1")
        found[0] = details
        st = lv.until(lambda st: st["collections"]["vessels"]["items"]["235103359"]["photo"].get("src"),
                      radio=self.radio)
        got = st["collections"]["vessels"]["items"]["235103359"]
        self.assertEqual(got["aboutLine"], "Caledonian MacBrayne")     # "MV Loch Seaforth" says no more than AIS
        self.assertEqual(got["builtLine"],
                         "Built 2015 by Flensburger Schiffbau-Gesellschaft · 8,680 GT · Home port Stornoway")
        self.assertEqual(got["photo"], {"src": "api/ais/vessels/235103359/photo", "credit": "Mn28 · CC BY-SA 3.0",
                                        "link": "https://commons.wikimedia.org/wiki/File:Loch_Seaforth.jpg",
                                        "alt": "Photo of MV Loch Seaforth"})
        other.until(lambda st: "235103359" in st["collections"]["vessels"]["items"], radio=self.radio)
        self.assertNotIn("photo", other.items("vessels")["235103359"])
        # The details draw the photo with its credit and the link as a QR
        # code, and the document is valid with the item in it: the picture
        # is a path on the box, which needs no allow-listed host.
        (img,) = [p for p, _w, _t in ui.iter_parts(part(doc, "details")) if p.get("type") == "image"]
        self.assertEqual((img["src"], img["credit"], img["link"], img["qr"]),
                         ({"$": "photo.src"}, {"$": "photo.credit"}, {"$": "photo.link"}, True))
        d = json.loads(json.dumps(doc))
        d["collections"]["vessels"]["items"]["235103359"] = got
        self.assertEqual(ui.check(d), [])
        # A name that does say more is shown: Wikidata's for a renamed ship.
        found[0] = dict(details, label="Isle of Lewis")
        self.assertEqual(traffic.selected_ship_fields(self.radio, "235103359")["aboutLine"],
                         "Isle of Lewis · Caledonian MacBrayne")

    def test_sondes(self):
        from ohsradio import sonde
        from test_ham_sonde import rs41_line
        now = time.time()
        self.radio.sonde.table.heard(sonde.reading(rs41_line(now), "RS41", 403_500_000.0, now), now)
        doc = self.c.screen("radio/sonde")
        lv = self.c.live(doc)
        lv.until(lambda st: "W1234567" in st["collections"]["sondes"]["items"])
        x = lv.items("sondes")["W1234567"]
        self.assertEqual((x["sym"], x["tone"], x["altText"], x["climbText"]), ("ascent", "sonde.ascent", "12,346 m",
                                                                               "+5.1 m/s"))
        self.assertEqual(x["kindText"], "RS41-SGP")
        # The selected sonde's readout: altitude, climb, temperature,
        # humidity, pressure and battery, from the same item.
        readout = part(doc, "readout")
        self.assertEqual((readout["for"], readout["slot"]), ("sondes", "bottom"))
        bound = {p["value"]["$"] for p, _w, _t in ui.iter_parts(readout) if isinstance(p.get("value"), dict)}
        self.assertLessEqual({"altText", "climbText", "tempText", "humidityText", "pressureText", "batteryText"},
                             bound)
        self.assertEqual((x["humidityText"], x["pressureText"], x["batteryText"]), ("30 %", "190.1 hPa", "2.7 V"))
        # The header's chip is one word, however long the session's sentence.
        self.assertIn(lv.state["parts"]["status"]["text"], ("Stopped", "Starting", "Receiving", "Scanning"))

    def test_a_refused_hold_offers_the_tv_s_remedy(self):
        from test_ham_ais import has_ais
        from ohsradio.devices import simaprs
        if not (has_ais() and simaprs.available()):
            self.skipTest("no AIS or APRS decoder for this machine")
        ships, aprs = self.c.screen("radio/ships"), self.c.screen("radio/aprs")
        self.c.hold(ships, "ais")
        s, a = self.c.hold(aprs, "aprs", expect=(409,))
        self.assertEqual(a["code"], "receiver_busy")
        (remedy,) = a["actions"]
        self.assertEqual((remedy["method"], remedy["path"], remedy["text"]),
                         ("DELETE", "api/ais/session?all=1", "Stop the ship map"))
        self.assertEqual(ui.check_action(remedy), [])
        # The banner's button, then the hold again, as the client does.
        self.c.press(remedy)
        pump(self.radio, 10, until=lambda: self.radio.state()["rxOwner"] == {})
        s, a = self.c.hold(aprs, "aprs")
        self.assertEqual(a["state"], "running")
        self.c.hold(aprs, "aprs", "stop")

    def test_aprs(self):
        from test_ham_aprs import CORPUS
        from ohsradio.devices import simaprs
        if not simaprs.available():
            self.skipTest("no shack_packet wheel for this machine")
        radio, srv, port = serve(self, [simaprs.AprsAir(beacons=CORPUS)])
        c = Client(self, port)
        doc = c.screen("radio/aprs")
        s, a = c.hold(doc, "aprs")
        self.assertEqual(a["state"], "running")
        lv = c.live(doc)
        lv.until(lambda st: "GM0ABC-9" in st["collections"]["stations"]["items"], timeout=90, radio=radio)
        x = lv.items("stations")["GM0ABC-9"]
        self.assertEqual((x["sym"], x["tone"], x["comment"]), ("car", "aprs.mobile", "Test position"))
        c.hold(doc, "aprs", "stop")
        pump(radio, 10, until=lambda: radio.state()["rxOwner"] == {})
        self.assertEqual(radio.state()["rxOwner"], {})


def has_dmr():
    from test_ham_dmr import has_dmr as has
    return has()


@unittest.skipUnless(has_dmr(), "no shack_sdr with DMR for this machine")
class Dmr(unittest.TestCase):
    def setUp(self):
        from test_ham_dmr import DMR_HZ
        self.hz = int(DMR_HZ)
        self.radio, self.srv, port = serve(self, device=False, simSignals=True, vfo=DMR_HZ)
        self.c = Client(self, port)
        self.other = Client(self, port, client="phone-1")

    def test_the_hold_is_shared_and_ends_with_the_last_client(self):
        doc = self.c.screen("radio/dmr", {"f": str(self.hz)})
        self.assertEqual(doc["live"]["path"], f"ui/v2/live/radio/dmr?f={self.hz}")
        s, a = self.c.hold(doc, "dmr")
        self.assertIn("id", a, a)
        sid = a["id"]
        v = self.radio.decoders.session(sid)
        self.assertEqual((a["held"], v["decoder"], v["freqHz"], v["listening"]), ("dmr", "dmr", self.hz, True))
        s, b = self.other.hold(doc, "dmr")
        self.assertEqual(b["id"], sid)                                   # one session for both
        lv = self.c.live(doc)
        st = lv.until(lambda st: st["parts"]["talker1"].get("value") or st["parts"]["talker2"].get("value"),
                      timeout=90, radio=self.radio)
        self.assertEqual(st["parts"]["listen"]["value"], "both")
        lv.until(lambda st: ui.drawn_keys(st, "calls"), timeout=120, radio=self.radio)
        # Hear one slot only: the slot param and listening, through the choice.
        self.c.press(part(doc, "listen")["action"], value="2")
        self.assertEqual(self.radio.decoders.session(sid)["params"]["slot"], "2")
        self.c.hold(doc, "dmr", "stop")
        self.assertIsNotNone(self.radio.decoders.session(sid))           # the phone still has it
        self.srv.client_gone("phone-1", "expired")                       # and goes
        self.assertIsNone(self.radio.decoders.session(sid))

    def test_the_chooser_lists_the_operators_repeaters(self):
        from ohsradio.state import MODES
        self.radio.localfreq.mine.add({"name": "GB7XX", "freqHz": 439_612_500, "mode": "fm",
                                       "category": "Repeater"}, MODES)
        doc = self.c.screen("radio/dmr")
        items = doc["collections"]["channels"]["items"]
        self.assertEqual([i["name"] for i in items.values()], ["The dial", "GB7XX"])
        act = part(doc, "channelList")["onActivate"]
        self.assertEqual(fill(act["params"], items["dial"]), {"f": self.hz})
        self.assertEqual(self.c.screen("radio/dmr", {"f": "439612500"})["title"], "GB7XX")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class WeatherSats(unittest.TestCase):
    def setUp(self):
        from test_ham_wxsat import BEFORE, fix
        self.radio, self.srv, port = serve(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = fix(self.radio, Path(tmp.name), BEFORE)
        self.c = Client(self, port)

    def test_pictures_open_on_mcir(self):
        from ohsradio.screens import wxsat
        im = {"id": "p", "aos": "2026-10-29T09:19:21Z", "products": [
            {"kind": k, "url": f"api/wxsat/images/p/{k}.jpg"} for k in ("ch1", "ir", "rgb", "mcir")]}
        self.assertEqual([x["kind"] for x in wxsat._products(im)], ["mcir", "rgb", "ir", "ch1"])
        self.assertEqual(wxsat.image_item(im, {})["thumb"], "api/wxsat/images/p/mcir.jpg?w=400")

    def test_polled_with_each_pass_s_own_action(self):
        doc = self.c.screen("radio/wxsat")
        self.assertNotIn("holds", doc)
        self.assertNotIn("live", doc)
        sockets = self.srv.ui_live.busy()
        s, ans, _h = self.c.req("GET", "/" + doc["poll"]["path"], level="view")
        self.assertEqual((s, ans["everyS"], ans["snap"]), (200, 10, True))
        self.assertEqual(ui.schema_errors(ans, "pollAnswer"), [])
        start = ui.state_from_document(doc)
        st = ui.apply_ops(start, ans["ops"])
        passes = {k: st["collections"]["passes"]["items"][k] for k in ui.drawn_keys(st, "passes")}
        self.assertTrue(passes)
        # Upcoming first, soonest first; then the day's past ones, newest first.
        whole = {x["id"]: x for x in self.radio.wxsat.passes_view(48, 24)["passes"]}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))
        los = [whole[k]["los"] for k in passes]
        coming = [x for x in los if x > now]
        self.assertTrue(coming and len(coming) < len(los))
        self.assertEqual(los[:len(coming)], coming)
        aos = [whole[k]["aos"] for k in passes]
        self.assertEqual(aos[:len(coming)], sorted(aos[:len(coming)]))
        self.assertEqual(aos[len(coming):], sorted(aos[len(coming):], reverse=True))
        key = next(k for k, p in passes.items() if p["planText"] == "Will record" and p.get("action"))
        first = passes[key]
        self.assertEqual(first["planText"], "Will record")
        self.assertEqual(ui.check_action(first["action"], data=True), [])
        self.assertEqual(first["action"]["method"], "DELETE")
        self.assertTrue(first["trail"] and first["countdown"]["countdown"]["to"])
        self.c.press(first["action"])
        again = self.c.req("GET", "/" + doc["poll"]["path"], level="view")[1]
        self.assertTrue(again["snap"])
        st = ui.apply_ops(start, again["ops"])
        again = st["collections"]["passes"]["items"][key]
        self.assertEqual((again["planText"], again["action"]["method"]), ("Skipped", "POST"))
        self.assertEqual(self.srv.ui_live.busy(), sockets)                 # still no socket
        self.assertEqual(self.radio.state()["rxOwner"], {})                # and nothing held


if __name__ == "__main__":
    unittest.main()
