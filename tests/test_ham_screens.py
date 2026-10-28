"""Radio's ui/1 screens (CLIENT-UI-PLAN.md §5, step 1b): ui/v1/app and
ui/v1/screen/<id> over real HTTP on loopback, each document validated with
ohs-libs shack_ui against the pinned schema, then every action it declares
pressed as a client would press it, on the RSPdx-shaped simulator with an
FM band, a DAB ensemble and the Clyde's ships on the air.

- **The descriptor** names the four screens, its entries open them, and
  every one is served.
- **Every post action** reaches an existing route at the level it
  declares: it works at that level and is refused one level lower, so a
  screen can never ask for less than the route needs. None transmits.
- **home:** the volume, the mode, a frequency and a band step change the
  radio; DAB, FM and Ships open their screens.
- **dab:** Scan now fills the station list; a station's tile plays it, the
  feed says what plays, another tile changes it, Stop gives the receiver
  back exactly.
- **fm:** Scan now fills the list; a tile tunes the station in wide FM;
  tune by frequency tunes.
- **ships:** the map component's session path starts AIS, the ships come
  in, the screen then lists them nearest first, and closing gives the
  receiver back.
- **The request:** X-Forwarded-Prefix never makes a path absolute;
  components the client lacks are left out for their fallback; ETag and
  304; 406 for a ui/2-only client; 404 for an unknown screen and for NB,
  which serves none.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import unittest

from ohscore import sdr, shacklibs
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsnb import server as nb_server
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from ham_helpers import pump
from listen_helpers import ListeningSim
from test_ham_ais import has_ais, named, quick_fleet
from test_ham_bandscan import on_air, scanned
from test_server import SECRET

HOME = 145_500_000.0
LOWER = {"control": "view", "view": "none"}


def serve(test, stations=(), fm_and_dab=False):
    """A Radio on the RSPdx-shaped simulator behind the store server, as
    the AIS and DAB API tests make one; (radio, server, port)."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": HOME, "mode": "fm",
           "locator": "IO75RL"}
    audio = StreamAudio(realtime=False)
    dev = ListeningSim(dict(cfg), 2_400_000.0, list(stations))
    if fm_and_dab:
        on_air(dev)
    radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, device=dev)
    srv = Server(radio, ham_server.info("9.9.9"), audio, secret=SECRET)
    port = srv.serve("127.0.0.1", 0).server_address[1]
    test.addCleanup(srv.shutdown)
    test.assertEqual(srv.start_radio(), "")
    return radio, srv, port


def walk(node):
    """Every node of a document, fallbacks included, depth first."""
    yield node
    if isinstance(node.get("fallback"), dict):
        yield from walk(node["fallback"])
    for c in node.get("children") or []:
        yield from walk(c)


def actions(doc):
    out = []
    for n in walk(doc["root"]):
        a = n.get("action")
        while a is not None:
            out.append((n, a))
            a = a.get("action") if a.get("do") == "confirm" else None
    return out


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def with_value(body, value):
    if body == "$value":
        return value
    if isinstance(body, dict):
        return {k: with_value(v, value) for k, v in body.items()}
    if isinstance(body, list):
        return [with_value(v, value) for v in body]
    return body


class Client:
    """A ui/1 client over loopback, signed in by the controller's proxy."""

    def __init__(self, test, port):
        self.t, self.port = test, port

    def req(self, method, path, body=None, level="control", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
             "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
             "X-OpenHamShack-Device": "dev_TV", "X-OpenHamShack-Auth": "device", **(headers or {})}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if raw else None), dict(r.getheaders())

    def screen(self, sid, headers=None):
        s, doc, _ = self.req("GET", f"/ui/v1/screen/{sid}", level="view",
                             headers={"X-OpenHamShack-UI": "1.0", **(headers or {})})
        self.t.assertEqual(s, 200, doc)
        shacklibs.ui().validate(doc)
        self.t.assertEqual(doc["screen"], sid)
        return doc

    def press(self, action, value=None, expect=(200, 201, 202)):
        """A post action as the renderer sends it: its body with $value
        filled in, to its path under the base, at its declared level - and
        first one level lower, which the route must refuse."""
        t = self.t
        t.assertEqual(action["do"], "post")
        t.assertIn(action["level"], ("view", "control"))
        t.assertFalse(action["path"].startswith("/"), action)
        body = with_value(action.get("body"), value)
        s, a, _ = self.req("POST", "/" + action["path"], body, level=LOWER[action["level"]])
        t.assertEqual((s, a["code"]), (403, "level_too_low"), (action, a))
        s, a, _ = self.req("POST", "/" + action["path"], body, level=action["level"])
        t.assertIn(s, expect, (action, a))
        return s, a


def find(doc, pred):
    return [(n, a) for n, a in actions(doc) if pred(n, a)]


def one(doc, label):
    got = [a for n, a in actions(doc) if n.get("label") == label]
    if len(got) != 1:
        raise AssertionError(f"{len(got)} actions labelled {label!r}")
    return got[0]


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class TheScreens(unittest.TestCase):
    def setUp(self):
        self.radio, self.srv, port = serve(self, fm_and_dab=True)
        sc = self.radio.bandscan
        # Two FM stations and the one DAB block: seconds, not minutes.
        sc.fm_lo, sc.fm_hi = 87_500_000, 95_000_000
        sc.dab_blocks = ["11C", "11D"]
        self.c = Client(self, port)

    def wait(self, cond, timeout=120.0):
        pump(self.radio, timeout, until=cond)
        self.assertTrue(cond())

    def test_the_descriptor_and_every_screen_it_names(self):
        s, app, h = self.c.req("GET", "/ui/v1/app", level="view")
        self.assertEqual(s, 200)
        self.assertEqual((app["ui"], app["kind"], app["app"], app["spectrum"], app["overlay"]),
                         ("1.0", "radio", "shack-radio", 1, 1))
        self.assertEqual(app["screens"], ["radio/home", "radio/dab", "radio/fm", "radio/ships"])
        self.assertEqual([e["id"] for e in app["entries"]], ["radio", "dab", "fm", "ships"])
        self.assertEqual({e["screen"] for e in app["entries"]}, set(app["screens"]))
        self.assertTrue(all(src["src"].startswith("get:api/") for src in app["data"].values()))
        for sid in app["screens"]:
            doc = self.c.screen(sid)
            for _n, a in actions(doc):
                self.assertNotEqual(a.get("level"), "transmit")
            # Nothing that keys is ever placed: these screens only receive.
            self.assertFalse([n for n in walk(doc["root"]) if n.get("name") in ("ptt", "enableTx")])

    def test_home(self):
        doc = self.c.screen("radio/home")
        self.assertEqual(set(doc["data"]), {"state", "meter"})
        self.c.press(one(doc, "Volume"), 0.25)
        self.assertEqual(self.radio.state()["volume"], 0.25)
        self.c.press(one(doc, "Mode"), "am")
        self.assertEqual(self.radio.state()["mode"], "am")
        self.c.press(one(doc, "Frequency"), 145_600_000)
        self.assertEqual(self.radio.state()["vfo"], 145_600_000)
        band = self.radio.state()["band"]
        self.c.press(one(doc, "Band up"))
        self.assertNotEqual(self.radio.state()["band"], band)
        self.c.press(one(doc, "Start the radio"))
        self.assertTrue(self.radio.state()["running"])
        opens = {a["screen"] for _n, a in actions(doc) if a["do"] == "open"}
        self.assertEqual(opens, {"radio/dab", "radio/fm", "radio/ships"})
        self.assertEqual(one(doc, "Mute"), {"do": "native", "verb": "audio.mute"})

    def test_dab(self):
        doc = self.c.screen("radio/dab")
        self.assertEqual(doc["data"]["dab"], {"src": "get:ui/v1/data/dab", "poll": 1})
        s, now, _ = self.c.req("GET", "/ui/v1/data/dab", level="view")
        self.assertEqual((s, now["playing"], now["title"]), (200, False, "Not playing"))
        # Nothing scanned yet: the empty list offers the scan.
        (empty,) = [n for n in walk(doc["root"]) if n["c"] == "empty" and "action" in n]
        s, a = self.c.press(empty["action"])
        self.assertEqual(a["bands"], ["dab"])
        self.assertTrue(scanned(self.radio))
        doc = self.c.screen("radio/dab")
        tiles = find(doc, lambda n, a: n["c"] == "card")
        self.assertEqual([a["body"]["params"]["service"] for _n, a in tiles], ["C221", "C3A7"])
        self.c.press(tiles[0][1])
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "dab")
        # Everything comes off air within a second or two of sync: the
        # station's name, the ensemble's, the programme text.
        self.wait(lambda: (lambda d: d["dls"] and d["title"] != "11D" and "Mux" in (d["ensemble"] or ""))(
            self.c.req("GET", "/ui/v1/data/dab", level="view")[1]))
        s, now, _ = self.c.req("GET", "/ui/v1/data/dab", level="view")
        self.assertEqual((now["playing"], now["service"], now["title"], now["block"]),
                         (True, "C221", "Shack MP2 Tone", "11D"))
        self.assertEqual(now["dls"], "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right")
        self.assertEqual(now["ensemble"], "Shack Test Mux · 11D")
        self.assertTrue(now["detail"].startswith("DAB · 128 kb/s"), now["detail"])
        # The picture is a path under the app's base, never absolute.
        self.wait(lambda: self.c.req("GET", "/ui/v1/data/dab", level="view")[1]["imagePath"])
        self.assertTrue(self.c.req("GET", "/ui/v1/data/dab", level="view")[1]["imagePath"].startswith("api/dab/"))
        # The other tile: the same session, the other station, live.
        sess = now["session"]
        self.c.press(tiles[1][1])
        s, now, _ = self.c.req("GET", "/ui/v1/data/dab", level="view")
        self.assertEqual((now["session"], now["service"]), (sess, "C3A7"))
        # Stop: the receiver is the operator's again, exactly as it was.
        self.c.press(one(doc, "Stop"))
        st = self.radio.state()
        self.assertEqual((st["rxOwner"], st["vfo"], st["mode"]), ({}, HOME, "fm"))
        self.assertFalse(self.c.req("GET", "/ui/v1/data/dab", level="view")[1]["playing"])

    def test_fm(self):
        doc = self.c.screen("radio/fm")
        (empty,) = [n for n in walk(doc["root"]) if n["c"] == "empty" and "action" in n]
        s, a = self.c.press(empty["action"])
        self.assertEqual(a["bands"], ["fm"])
        self.assertTrue(scanned(self.radio))
        doc = self.c.screen("radio/fm")
        (tabs,) = [n for n in walk(doc["root"]) if n["c"] == "tabs"]
        by_freq, by_name = tabs["children"]
        tunes = [n["action"]["body"]["changes"] for n in walk(by_freq) if n["c"] == "card"]
        self.assertEqual(tunes, [{"vfo": 88_600_000, "mode": "wfm"}, {"vfo": 93_500_000, "mode": "wfm"}])
        names = [n["children"][0]["text"] for n in walk(by_name) if n["c"] == "card"]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.c.press(next(n["action"] for n in walk(by_freq) if n["c"] == "card"))
        st = self.radio.state()
        self.assertEqual((st["vfo"], st["mode"]), (88_600_000, "wfm"))
        self.c.press(one(doc, "Tune by frequency"), 93_500_000)
        self.assertEqual(self.radio.state()["vfo"], 93_500_000)

    def test_the_request(self):
        # Behind the controller's prefix: still nothing absolute.
        for sid in ("radio/home", "radio/dab", "radio/fm", "radio/ships"):
            doc = self.c.screen(sid, {"X-Forwarded-Prefix": "/apps/radio"})
            self.assertFalse([s for s in strings(doc) if s.startswith("/") or "://" in s], sid)
        # A client without the map's ais layer or the waterfall gets the
        # fallback in their place, and one with them the native component.
        bare = self.c.screen("radio/ships", {"X-OpenHamShack-Components": "audio/1"})
        self.assertFalse([n for n in walk(bare["root"]) if n["c"] == "native"])
        full = self.c.screen("radio/ships", {"X-OpenHamShack-Components": "map.ais/1, waterfall/1, audio/1"})
        (themap,) = [n for n in walk(full["root"]) if n.get("name") == "map"]
        self.assertEqual(themap["props"]["layers"], ["ais"])
        self.assertIn("fallback", themap)
        home = self.c.screen("radio/home", {"X-OpenHamShack-Components": "map.ais/1"})
        self.assertFalse([n for n in walk(home["root"]) if n.get("name") in ("waterfall", "audio")])
        # The rev is the ETag, and a client that has it gets 304.
        s, doc, h = self.c.req("GET", "/ui/v1/screen/radio/fm", level="view")
        self.assertEqual(h["ETag"], f'"{doc["rev"]}"')
        s, body, _ = self.c.req("GET", "/ui/v1/screen/radio/fm", level="view", headers={"If-None-Match": h["ETag"]})
        self.assertEqual((s, body), (304, None))
        s, a, _ = self.c.req("GET", "/ui/v1/screen/radio/fm", level="view", headers={"X-OpenHamShack-UI": "2.0"})
        self.assertEqual((s, a["code"], a["ui"]), (406, "ui_unsupported", ["1.0"]))
        s, a, _ = self.c.req("GET", "/ui/v1/screen/radio/nothing", level="view")
        self.assertEqual((s, a["code"]), (404, "unknown_screen"))
        s, a, _ = self.c.req("GET", "/ui/v1/app", level="none")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))

    def test_nb_serves_no_screens(self):
        srv = Server(self.radio, nb_server.info("9.9.9"), StreamAudio(realtime=False), secret=SECRET)
        port = srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(srv.shutdown)
        s, a, _ = Client(self, port).req("GET", "/ui/v1/app", level="view")
        self.assertEqual((s, a["code"]), (404, "not_found"))


@unittest.skipUnless(has_ais(), "no shack_sdr with AIS for this machine")
class Ships(unittest.TestCase):
    def setUp(self):
        self.radio, self.srv, port = serve(self, [quick_fleet()])
        self.c = Client(self, port)

    def test_the_map_opens_ais_and_the_ships_are_listed_nearest_first(self):
        doc = self.c.screen("radio/ships", {"X-OpenHamShack-Components": "map.ais/1"})
        self.assertEqual(doc["data"]["ais"], {"src": "get:api/ais/vessels", "poll": 10})
        (themap,) = [n for n in walk(doc["root"]) if n.get("name") == "map"]
        p = themap["props"]
        # Every path the map component uses answers at view, as a TV's map would ask.
        for path in (p["info"], p["land"] + "?bbox=-5.5,55,-4.5,56&format=compact", p["ais"]["vessels"],
                     p["tiles"].format(z=0, x=0, y=0)):
            s, _a, _h = self.c.req("GET", "/" + path, level="view")
            self.assertIn(s, (200, 404), path)       # a tile may be 404 offline: the land is drawn instead
        # The session the component keeps: control, as POST api/ais/session is.
        s, a, _ = self.c.req("POST", "/" + p["ais"]["session"], {"client": "tv-lounge"}, level="view")
        self.assertEqual((s, a["code"]), (403, "level_too_low"))
        s, a, _ = self.c.req("POST", "/" + p["ais"]["session"], {"client": "tv-lounge"})
        self.assertEqual((s, a["state"]), (200, "running"))
        self.assertEqual(self.radio.state()["rxOwner"]["by"], "ais")
        pump(self.radio, 60, until=lambda: named(self.radio))
        self.assertTrue(named(self.radio))
        # Opened again, the sheet lists the ships heard, bound nearest first.
        doc = self.c.screen("radio/ships")
        rows = [n for n in walk(doc["root"]) if n["c"] == "card"]
        self.assertGreaterEqual(len(rows), 6)
        self.assertEqual(rows[0]["children"][0]["text"], {"bind": "ais.vessels.0.name"})
        self.assertEqual(rows[0]["action"], {"do": "local", "key": "map.ais.selected",
                                             "value": {"bind": "ais.vessels.0.mmsi"}})
        s, table, _ = self.c.req("GET", "/" + p["ais"]["vessels"], level="view")
        km = [v["distanceKm"] for v in table["vessels"] if v.get("distanceKm") is not None]
        self.assertEqual(km, sorted(km))
        # Closing the map: the component's DELETE, then nobody is left.
        s, a, _ = self.c.req("DELETE", "/" + p["ais"]["session"] + "?client=tv-lounge")
        self.assertEqual((s, a["clients"]), (200, 0))
        s, a, _ = self.c.req("DELETE", "/" + p["ais"]["session"] + "?all=1")
        self.assertEqual(self.radio.state()["rxOwner"], {})


if __name__ == "__main__":
    unittest.main()
