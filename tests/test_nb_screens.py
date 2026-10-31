"""QO-100 NB's ui/2 screens (ohsnb/screens.py, ohscore/server/uiv2.py;
openhamshack docs/contract/SCREENS.md) over a real NB engine on the
simulator, through real HTTP and WebSocket on loopback: what a client
fetches, what it holds after the live socket's snap and each frame (shack_ui's
reference applier, as a renderer would hold it), the receiver hold, and
the transmit rules. Nothing here keys: transmit is only looked at in the
documents, and the engine is checked never to have keyed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import http.client
import json
import os
import queue
import socket
import struct
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import helpers
from ohscore import shacklibs
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsnb import screens
from ohsnb import server as nb_server

SECRET = "test-proxy-secret"
ui = shacklibs.ui()
KEY_ROUTES = ("api/ptt", "api/ptt/heartbeat", "api/autotx", "api/audio/tx")


def headers(level="control", form="tv", transmit=None, client="tv-1", ui_version="2.0"):
    h = {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
         "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Form": f"{form}; w=960; h=540",
         "X-OpenHamShack-Client": client}
    if ui_version is not None:
        h["X-OpenHamShack-UI"] = ui_version
    if transmit is not None:
        h["X-OpenHamShack-Transmit"] = transmit
    return h


class Live:
    """A client's live socket: text frames read on a thread into a queue."""

    def __init__(self, port, path, hdrs):
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        extra = "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n").encode())
        self.s, self.f = s, s.makefile("rb")
        self.status = self.f.readline()
        while self.f.readline() not in (b"\r\n", b""):
            pass
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                b0, b1 = self.f.read(2)
                n = b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", self.f.read(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", self.f.read(8))[0]
                data = self.f.read(n)
                if b0 & 0x0F == 0x8:
                    self.q.put(None)
                    return
                self.q.put(json.loads(data))
        except (OSError, ValueError):
            self.q.put(None)

    def send(self, msg):
        data = json.dumps(msg).encode()
        mask = os.urandom(4)
        self.s.sendall(struct.pack("!BB", 0x81, 0x80 | len(data)) + mask
                       + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def next(self, timeout=5.0):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.s.close()


class ScreensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = StreamAudio(realtime=False)
        from ohsnb.radio import Radio
        self.radio = Radio(helpers.sim_cfg(callsign="GM4BRI", licenceClass="full"), persist=False,
                           data_dir=self.tmp.name, audio=self.audio)
        self.srv = Server(self.radio, nb_server.info("9.9.9"), self.audio, secret=SECRET)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")
        self.sockets: list[Live] = []
        self.addCleanup(lambda: [s.close() for s in self.sockets])

    def req(self, method, path, body=None, **kw):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = headers(**{k: v for k, v in kw.items() if k != "extra"}) | kw.get("extra", {})
        if body is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw), dict(r.getheaders())
        except ValueError:
            return r.status, raw, dict(r.getheaders())

    def doc(self, sid, **kw):
        s, d, _h = self.req("GET", f"/ui/v2/screen/{sid}", **kw)
        self.assertEqual(s, 200, d)
        return d

    def live(self, sid, **kw):
        c = Live(self.port, f"/ui/v2/live/{sid}", headers(**kw))
        self.sockets.append(c)
        self.assertIn(b"101", c.status)
        return c

    def follow(self, sid, **kw):
        """A client of `sid`: its document, its socket, and the state it
        holds after the snap."""
        d = self.doc(sid, **kw)
        c = self.live(sid, **kw)
        hello = c.next()
        self.assertEqual(hello["t"], "hello")
        start = ui.state_from_document(d)
        snap = c.next()
        self.assertEqual(snap["t"], "snap")
        return d, c, hello, start, ui.apply_frame(start, snap, start)

    def until(self, c, state, start, cond, timeout=8.0):
        """Apply frames until cond(state) or the time is up."""
        end = time.monotonic() + timeout
        while not cond(state) and time.monotonic() < end:
            f = c.next(timeout=max(0.05, end - time.monotonic()))
            if f is None:
                break
            if f.get("t") in ("p", "snap"):
                state = ui.apply_frame(state, f, start)
        return state

    def set(self, body):
        s, a, _h = self.req("POST", "/api/set", body, level="control")
        self.assertEqual(s, 200, a)


def part(state, pid):
    return state["parts"][pid]


class Documents(ScreensTest):
    def test_the_descriptor_names_the_launcher_tiles_and_every_one_opens(self):
        s, d, _h = self.req("GET", "/ui/v2/app", level="view")
        self.assertEqual(s, 200, d)
        self.assertEqual(d["app"], "shack-qo100nb")
        self.assertEqual([e["id"] for e in d["entries"]], ["qo100nb", "signals", "beacon"])
        for e in d["entries"]:
            self.assertEqual(self.doc(e["screen"], level="view")["screen"], e["screen"])

    def test_every_screen_in_every_form_and_level_passes_the_validator_and_schema(self):
        for sid in screens.SCREENS:
            for form in ("tv", "phone", "tablet"):
                for level in ("view", "control", "transmit"):
                    d = self.doc(sid, form=form, level=level)
                    self.assertEqual(ui.check(d), [], (sid, form, level))
                    self.assertEqual(ui.schema_errors(d), [], (sid, form, level))
                    self.assertEqual((d["form"], d["level"]), (form, level))
                    ui.state_from_document(d)        # and a renderer can hold it

    def test_a_client_with_the_document_gets_304_and_another_major_406(self):
        s, d, h = self.req("GET", "/ui/v2/screen/nb/home")
        s2, _b, _h2 = self.req("GET", "/ui/v2/screen/nb/home", extra={"If-None-Match": h["ETag"]})
        self.assertEqual((s, s2), (200, 304))
        s3, b, _h3 = self.req("GET", "/ui/v2/screen/nb/home", ui_version="3.0")
        self.assertEqual((s3, b["code"]), (406, "ui_unsupported"))
        s4, b4, _h4 = self.req("GET", "/ui/v2/screen/nb/nothing")
        self.assertEqual((s4, b4["code"]), (404, "unknown_screen"))

    def test_the_document_holds_no_live_value_so_its_rev_survives_tuning(self):
        rev = self.doc("nb/home")["rev"]
        self.set({"vfo": 10_489_600_000.0})
        self.assertEqual(self.doc("nb/home")["rev"], rev)

    def test_only_through_the_proxy(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/ui/v2/screen/nb/home")
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 401)

    def test_tile_status_says_mode_and_lock(self):
        s, d, _h = self.req("GET", "/ui/v2/status", level="view")
        self.assertEqual(s, 200, d)
        self.assertEqual(set(d["entries"]), {"qo100nb", "signals", "beacon"})
        self.assertIn(self.radio.state()["mode"].upper(), d["entries"]["qo100nb"]["status"])


class LiveState(ScreensTest):
    def test_the_snap_shows_the_dial_and_mode_and_a_tune_patches_the_dial(self):
        d, c, hello, start, st = self.follow("nb/home")
        self.assertEqual(hello["rev"], d["rev"])
        self.assertEqual(part(st, "dial")["value"], self.radio.state()["vfo"])
        self.assertEqual(part(st, "mode")["value"], self.radio.state()["mode"])
        self.assertEqual(part(st, "stRadio")["value"], "Running · sim")    # words, never a dict
        self.set({"vfo": 10_489_612_300.0})
        st = self.until(c, st, start, lambda s: part(s, "dial")["value"] == 10_489_612_300.0)
        self.assertEqual(part(st, "dial")["value"], 10_489_612_300.0)

    def test_each_form_and_level_hears_its_own_documents_rev(self):
        """A channel's hello carries one rev; a client whose document's rev
        differs would refetch it for ever (screens.py: Variants)."""
        a, ca, ha, _s, _st = self.follow("nb/home", form="tv", level="view")
        b, cb, hb, _s2, st_b = self.follow("nb/home", form="phone", level="transmit", client="phone-1")
        self.assertNotEqual(a["rev"], b["rev"])
        self.assertEqual((ha["rev"], hb["rev"]), (a["rev"], b["rev"]))
        # and a variant made late is as current as the first
        self.assertEqual(part(st_b, "dial")["value"], self.radio.state()["vfo"])

    def test_a_tap_lands_the_signal_where_the_mode_listens(self):
        d, c, _h, start, st = self.follow("nb/home")
        self.set({"mode": "cw", "cwPitch": 600.0})
        st = self.until(c, st, start, lambda s: part(s, "scope")["tap"]["offsetHz"] == -600)
        self.assertEqual(part(st, "scope")["tap"]["offsetHz"], -600)
        self.set({"mode": "ft8"})
        st = self.until(c, st, start, lambda s: part(s, "scope")["tap"]["offsetHz"] == -1500)
        self.assertEqual(part(st, "zoom")["tap"]["offsetHz"], -1500)

    def test_slot_decodes_become_list_rows_newest_first(self):
        self.set({"mode": "ft8"})
        _d, c, _h, start, st = self.follow("nb/home")
        now = time.time()
        for i, text in enumerate(("CQ DL1ABC JO62", "GM4BRI DL1ABC -12", "CQ G4XYZ IO91")):
            self.radio._emit_event({"mode": "ft8", "slot": now + i * 15, "snr": -10 + i, "dt": 0.1, "df": 1200,
                                    "text": text})
        st = self.until(c, st, start, lambda s: len(ui.drawn_keys(s, "decodes")) == 3)
        rows = [st["collections"]["decodes"]["items"][k] for k in ui.drawn_keys(st, "decodes")]
        self.assertEqual([r["text"] for r in rows], ["CQ G4XYZ IO91", "GM4BRI DL1ABC -12", "CQ DL1ABC JO62"])
        self.assertEqual(rows[1]["tone"], "accent")         # addressed to the station
        self.assertTrue(part(st, "rxText").get("hidden"))

    def test_cw_text_runs_on_and_shows_in_place_of_the_list(self):
        self.set({"mode": "cw"})
        _d, c, _h, start, st = self.follow("nb/home")
        for chunk in ("CQ CQ DE ", "GM4BRI ", "K"):
            self.radio._emit_event({"mode": "cw", "text": chunk})
        st = self.until(c, st, start, lambda s: part(s, "rxText").get("value") == "CQ CQ DE GM4BRI K")
        self.assertEqual(part(st, "rxText")["value"], "CQ CQ DE GM4BRI K")
        self.assertFalse(part(st, "rxText").get("hidden"))
        self.assertTrue(part(st, "decodeList").get("hidden"))

    def test_a_skimmed_signal_is_a_row_whose_ok_tunes_to_it(self):
        # The simulator's own skimmer would publish its list over this one.
        self.set({"skimDecode": False})
        _d, c, _h, start, st = self.follow("nb/signals")
        self.radio._publish("skim", {"t": time.time(), "entries": [
            {"id": 7, "f": 10_489_640_000.0, "lo": 10_489_639_000.0, "hi": 10_489_642_000.0, "kind": "ssb",
             "label": "SSB", "mode": "usb", "dial": 10_489_639_700.0, "exact": "twice", "snr": 18.0,
             "active": True, "last": time.time()}]})
        st = self.until(c, st, start, lambda s: ui.drawn_keys(s, "signals") == ["7"])
        row = st["collections"]["signals"]["items"]["7"]
        self.assertEqual(row["label"], "SSB")
        # OK on the row runs the item's own action, as a renderer would.
        a = row["action"]
        self.assertEqual((a["do"], a["level"]), ("call", "control"))
        s, ans, _h2 = self.req(a["method"], "/" + a["path"], a["body"], level=a["level"])
        self.assertEqual(s, 200, ans)
        self.assertEqual((self.radio.state()["vfo"], self.radio.state()["mode"]), (10_489_639_700.0, "usb"))

    def test_nothing_drains_the_engines_feeds_once_no_screen_is_open(self):
        """The watchdog counts a drained feed as the UI alive (screens.py):
        with the last socket gone, NB's subscriptions are left undrained."""
        _d, c, _h, _s, _st = self.follow("nb/home")
        feeds = self.srv.info.screens.follower.feeds
        self.assertTrue(feeds)

        def drained():
            return max(f.last_drain for f in feeds.values())
        first = drained()
        end = time.monotonic() + 5
        while drained() == first and time.monotonic() < end:
            time.sleep(0.05)
        self.assertGreater(drained(), first)            # followed while watched
        c.close()
        time.sleep(1.5)                                  # the pump notices the socket gone
        settled = drained()
        time.sleep(2.0)
        self.assertEqual(drained(), settled)
        self.assertFalse(self.radio.state()["keyed"])


class Decodes(ScreensTest):
    """The decode lists the parity check found wanting (31/10/2026): times
    formatted and grouped by slot, DT, audio frequency and dB, the CQ and
    own-call tones, a full-screen list, and clearing."""

    def emit(self, slot, snr, dt, df, text, **kw):
        self.radio._emit_event({"mode": "ft8", "slot": slot, "snr": snr, "dt": dt, "df": df, "text": text} | kw)

    def rows(self, st):
        return [st["collections"]["decodes"]["items"][k] for k in ui.drawn_keys(st, "decodes")]

    def test_rows_are_grouped_under_one_header_per_slot_newest_slot_first(self):
        self.set({"mode": "ft8"})
        slot = 1_793_446_215.0              # 2026-10-31 11:30:15 UTC
        clients = [self.follow(sid) for sid in ("nb/home", "nb/decodes")]
        self.emit(slot, 4, 0.2, 1200, "CQ PA3QOS JO22", country="Netherlands")
        self.emit(slot, -3, -0.1, 950, "G4XYZ EA4QRP IN80")
        self.emit(slot + 15, 6, 0.0, 1510, "GM4BRI DL1ABC -12")
        for _d, c, _h, start, st in clients:
            st = self.until(c, st, start, lambda s: len(ui.drawn_keys(s, "decodes")) == 3)
            rows = self.rows(st)
            self.assertEqual([r["text"] for r in rows], ["GM4BRI DL1ABC -12", "CQ PA3QOS JO22", "G4XYZ EA4QRP IN80"])
            self.assertEqual([r.get("slotHead") for r in rows], ["11:30:30", "11:30:15", None])
            first = rows[1]
            self.assertEqual((first["snrText"], first["dtText"], first["freqText"]), ("+4", "+0.2", "1200"))
            self.assertEqual(first["line2"], "Netherlands · +0.2 s · 1200 Hz")
            self.assertEqual([r.get("tone") for r in rows], ["accent", "info", None])     # own call, CQ, neither

    def test_a_change_to_a_voice_mode_clears_them_and_ft8_to_ft4_does_not(self):
        self.set({"mode": "ft8"})
        _d, c, _h, start, st = self.follow("nb/home")
        self.emit(time.time(), -5, 0.1, 1000, "CQ DL1ABC JO31")
        st = self.until(c, st, start, lambda s: len(ui.drawn_keys(s, "decodes")) == 1)
        self.set({"mode": "ft4"})
        st = self.until(c, st, start, lambda s: part(s, "mode")["value"] == "ft4")
        time.sleep(0.6)
        st = self.until(c, st, start, lambda s: False, timeout=0.6)
        self.assertEqual(len(ui.drawn_keys(st, "decodes")), 1)
        self.set({"mode": "usb"})
        st = self.until(c, st, start, lambda s: not ui.drawn_keys(s, "decodes"))
        self.assertEqual(ui.drawn_keys(st, "decodes"), [])

    def test_clear_empties_both_lists_and_a_view_only_device_cannot(self):
        self.set({"mode": "ft8"})
        _d, viewer, _h, vstart, vst = self.follow("nb/decodes", level="view", client="tv-2")
        _d2, c, _h2, start, st = self.follow("nb/home")
        self.emit(time.time(), -5, 0.1, 1000, "CQ DL1ABC JO31")
        st = self.until(c, st, start, lambda s: len(ui.drawn_keys(s, "decodes")) == 1)
        viewer.send({"t": "event", "name": "clearDecodes"})
        vst = self.until(viewer, vst, vstart, lambda s: len(ui.drawn_keys(s, "decodes")) == 1)
        time.sleep(1.0)
        vst = self.until(viewer, vst, vstart, lambda s: False, timeout=0.6)
        self.assertEqual(len(ui.drawn_keys(vst, "decodes")), 1)
        # The home document's own Clear button, sent as a renderer sends it.
        clear = next(p["action"] for p, _w, _c in ui.iter_parts(_d2["root"])
                     if p.get("type") == "button" and p.get("action", {}).get("do") == "send")
        c.send({"t": "event", "name": clear["name"]})
        vst = self.until(viewer, vst, vstart, lambda s: not ui.drawn_keys(s, "decodes"))
        st = self.until(c, st, start, lambda s: not ui.drawn_keys(s, "decodes"))
        self.assertEqual((ui.drawn_keys(st, "decodes"), ui.drawn_keys(vst, "decodes")), ([], []))


class Bookmarks(ScreensTest):
    """The engine's memories as the old TV had them: a picker, CH+/CH-
    stepping them, ticks and names on the scope."""

    def marks(self):
        return sorted(self.radio.memories(), key=lambda m: m["dl"])

    def test_the_picker_lists_them_shows_the_one_the_radio_is_on_and_recalls(self):
        ft8 = next(m for m in self.marks() if m["name"] == "FT8")
        self.set({"vfo": ft8["dl"], "mode": ft8["mode"]})
        d, c, _h, start, st = self.follow("nb/home")
        st = self.until(c, st, start, lambda s: part(s, "bookmark").get("options") and
                        part(s, "bookmark").get("value") == "FT8")
        picker = part(st, "bookmark")
        self.assertEqual([o["value"] for o in picker["options"]], [m["name"] for m in self.marks()])
        # Choosing "Emergency" as a renderer would: the call with $value put in.
        a = next(p for p, _w, _x in ui.iter_parts(d["root"]) if p.get("id") == "bookmark")["action"]
        body = {k: ("Emergency" if v == "$value" else v) for k, v in a["body"].items()}
        s, ans, _h2 = self.req(a["method"], "/" + a["path"], body, level=a["level"])
        self.assertEqual(s, 200, ans)
        em = next(m for m in self.marks() if m["name"] == "Emergency")
        self.assertEqual(self.radio.state()["vfo"], em["dl"])
        st = self.until(c, st, start, lambda s: part(s, "bookmark").get("value") == "Emergency")
        self.assertEqual(part(st, "bookmark")["value"], "Emergency")
        # Off every bookmark it shows the nearest as "Near ...", never the first.
        self.set({"vfo": em["dl"] + 3000.0})
        st = self.until(c, st, start, lambda s: any(o["text"] == "Near Emergency"
                                                     for o in part(s, "bookmark").get("options") or []))
        self.assertEqual(part(st, "bookmark")["value"], "Emergency")

    def test_ch_up_and_down_step_through_them_and_stop_at_the_ends(self):
        marks = self.marks()
        d, c, _h, _s, _st = self.follow("nb/home")
        up, down = d["keys"]["chUp"], d["keys"]["chDown"]
        self.set({"vfo": marks[0]["dl"], "mode": marks[0]["mode"]})

        def press(key, want):
            c.send({"t": "event", "name": key["name"], "value": key["value"]})
            end = time.monotonic() + 5
            while self.radio.state()["vfo"] != want and time.monotonic() < end:
                time.sleep(0.05)
            self.assertEqual(self.radio.state()["vfo"], want)
        press(up, marks[1]["dl"])
        self.assertEqual(self.radio.state()["mode"], marks[1]["mode"])
        press(up, marks[2]["dl"])
        press(down, marks[1]["dl"])
        press(down, marks[0]["dl"])
        c.send({"t": "event", "name": "bookmark", "value": -1})     # the lowest: nowhere further
        time.sleep(1.0)
        self.assertEqual(self.radio.state()["vfo"], marks[0]["dl"])

    def test_a_view_only_device_cannot_tune_with_them(self):
        marks = self.marks()
        self.set({"vfo": marks[0]["dl"]})
        _d, c, _h, _s, _st = self.follow("nb/home", level="view")
        c.send({"t": "event", "name": "bookmark", "value": 1})
        time.sleep(1.0)
        self.assertEqual(self.radio.state()["vfo"], marks[0]["dl"])

    def test_the_scope_names_nbs_band_plan_bookmarks_and_beacons_and_each_tunes(self):
        s, ov, _h = self.req("GET", "/api/overlay/v1?loHz=10489500000&hiHz=10490000000", level="view")
        self.assertEqual(s, 200, ov)
        items = ov["items"]
        kinds = {}
        for i in items:
            kinds.setdefault(i["kind"], []).append(i)
        segs = {i["label"] for i in kinds["segment"]}
        self.assertIn("CW only", segs)
        self.assertNotIn("satellites", segs)            # the terrestrial plan's one segment, no longer
        self.assertIn("Emergency", {i["label"] for i in kinds["bookmark"]})
        self.assertEqual({i["label"] for i in kinds["beacon"]},
                         {"Lower beacon", "Middle beacon", "Multimedia beacon", "Upper beacon"})
        # A beacon's own preset is drawn once, as the beacon, with its tune.
        self.assertNotIn("Lower beacon", {i["label"] for i in kinds["bookmark"]})
        lower = next(i for i in kinds["beacon"] if i["id"] == "bcn:lower")
        self.assertIsNone(lower["readAtHzPerPx"])
        for item in (lower, next(i for i in kinds["bookmark"] if i["label"] == "Emergency")):
            a = item["actions"][0]
            self.assertEqual((a["level"], a.get("tx")), ("control", None))
            s2, ans, _h2 = self.req("POST", "/" + a["path"], a["body"], level=a["level"])
            self.assertEqual(s2, 200, ans)
            self.assertEqual(self.radio.state()["vfo"], a["body"]["changes"]["vfo"])

    def test_named_skimmer_signals_and_open_alerts_reach_the_scope(self):
        # What BandSkimmer last published, without running one (its own
        # list from the simulator's band would replace this one).
        sk = types.SimpleNamespace(last=None)
        sk.last = [{"id": 7, "f": 10_489_640_000.0, "lo": 10_489_639_000.0, "hi": 10_489_642_000.0, "kind": "ssb",
                    "label": "SSB", "mode": "usb", "dial": 10_489_639_700.0, "active": True},
                   {"id": 8, "f": 10_489_660_000.0, "kind": "signal", "label": "Signal", "active": True}]
        events = [{"id": 3, "kind": "overpower", "freq": 10_489_700_000.0, "excessDb": 2.5, "active": True}]
        with mock.patch.object(self.radio, "overpower_view", lambda: {"events": events}), \
                mock.patch.object(self.radio, "skim", sk):
            s, ov, _h = self.req("GET", "/api/overlay/v1?loHz=10489600000&hiHz=10489720000", level="view")
        self.assertEqual(s, 200, ov)
        by = {i["id"]: i for i in ov["items"]}
        self.assertEqual(by["sig:7"]["label"], "SSB")
        self.assertNotIn("sig:8", by)                  # a carrier not yet told apart is no label
        self.assertEqual(by["alert:3"]["label"], "+2.5 dB over the beacon")
        a = by["sig:7"]["actions"][0]
        s2, _a, _h2 = self.req("POST", "/" + a["path"], a["body"], level=a["level"])
        self.assertEqual((s2, self.radio.state()["vfo"]), (200, 10_489_639_700.0))


class BookmarkSteps(unittest.TestCase):
    MARKS = [{"name": "A", "dl": 100.0, "mode": "cw"}, {"name": "B", "dl": 200.0, "mode": "usb"},
             {"name": "C", "dl": 300.0, "mode": "ft8"}]

    def test_the_one_under_the_dial_is_passed_over_and_the_ends_stop(self):
        self.assertEqual(screens.step_bookmark(self.MARKS, 210.0, 1)["name"], "C")
        self.assertEqual(screens.step_bookmark(self.MARKS, 210.0, -1)["name"], "A")
        self.assertIsNone(screens.step_bookmark(self.MARKS, 300.0, 1))
        self.assertEqual(screens.step_bookmark(self.MARKS, None, -1)["name"], "C")
        self.assertEqual(screens.current_bookmark(self.MARKS, 240.0, "usb")["name"], "B")
        self.assertIsNone(screens.current_bookmark(self.MARKS, 200.0, "lsb"))


class Words(unittest.TestCase):
    def test_a_decoder_that_cannot_run_is_unavailable_not_its_python_error(self):
        self.assertEqual(screens.decoder_word("unavailable: ohsdigi is not built (No module named x)", True),
                         "Unavailable")
        self.assertEqual(screens.decoder_word("receiving", True), "Receiving")
        self.assertEqual(screens.decoder_word("receiving", False), "Off")


class ReceiverHold(ScreensTest):
    def hold(self, method="POST", **kw):
        path = "/ui/v2/hold/receiver" + ("?client=tv-1" if method == "DELETE" else "")
        return self.req(method, path, {"client": "tv-1"} if method == "POST" else None, **kw)

    def test_each_screen_that_listens_declares_it_and_it_starts_and_stops(self):
        for sid in ("nb/home", "nb/signals"):
            h = self.doc(sid)["holds"]
            self.assertEqual([x["name"] for x in h], ["receiver"])
            self.assertEqual(h[0]["start"]["path"], "ui/v2/hold/receiver")
        self.assertEqual(self.hold()[0], 200)
        self.assertEqual(self.hold("DELETE")[0], 200)
        self.assertTrue(self.radio.state()["running"])      # stopping a hold stops nothing

    def test_a_stopped_radio_refuses_with_a_remedy_that_works(self):
        self.req("POST", "/api/stop", {})
        s, b, _h = self.hold()
        self.assertEqual((s, b["code"]), (409, "receiver_stopped"))
        (remedy,) = b["actions"]
        self.assertEqual(ui.check_action(remedy, "remedy"), [])
        s2, _b2, _h2 = self.req(remedy["method"], "/" + remedy["path"], remedy["body"], level=remedy["level"])
        self.assertEqual(s2, 200)
        self.assertEqual(self.hold()[0], 200)

    def test_a_view_only_device_is_told_so(self):
        s, b, _h = self.hold(level="view")
        self.assertEqual((s, b["code"]), (403, "level_too_low"))


def _home_revs(test):
    return {f"{form}/{level}": test.doc("nb/home", form=form, level=level)["rev"]
            for form in ("tv", "phone", "tablet") for level in ("view", "control", "transmit")}


# nb/home's rev for each form and level with the switch on. First recorded
# before SCREENS_TRANSMIT existed (a7840e2), so that turning transmit off
# was shown to change nothing else; re-recorded when the parity fixes
# (bookmarks, grouped decodes, captions) changed the receive side on
# purpose (the bookmark picker's options are the simulator's memories,
# fixed with persist=False). The rev is a hash of the whole document: a change here must be
# one meant, and is recorded again with it.
HOME_REVS_TRANSMIT_ON = {
    "tv/view": "474e7bf8ad39", "tv/control": "34b95375bc9f", "tv/transmit": "c292221e574e",
    "phone/view": "82701570fe4b", "phone/control": "95021b439d26", "phone/transmit": "1712f17f52e0",
    "tablet/view": "be3249e5ab15", "tablet/control": "9d0349fa01c9", "tablet/transmit": "a76741cf2209",
}


class Transmit(ScreensTest):
    """Placed exactly as SCREENS.md section 7 says, with SCREENS_TRANSMIT on
    (it is off in the release; see ReceiveOnly); tested on the documents and
    the fakes only. Nothing keys."""

    def setUp(self):
        patch = mock.patch.object(screens, "SCREENS_TRANSMIT", True)
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()

    def test_with_the_switch_on_the_home_document_is_what_it_was_before_the_switch(self):
        self.assertEqual(_home_revs(self), HOME_REVS_TRANSMIT_ON)

    def actions(self, d):
        found = []

        def walk(v, where):
            if isinstance(v, dict):
                if "do" in v and isinstance(v.get("do"), str):
                    found.append((where, v))
                for k, x in v.items():
                    walk(x, f"{where}.{k}")
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    walk(x, f"{where}[{i}]")
        walk(d, "doc")
        return found

    def test_ptt_is_never_on_a_tv_and_txarm_is_digital(self):
        d = self.doc("nb/home", form="phone", level="transmit")
        parts = {p["id"]: p for p, _where, _ctx in ui.iter_parts(d["root"]) if "id" in p}
        ptt, arm = parts["ptt"], parts["txArm"]
        self.assertEqual((ptt["type"], ptt["key"], ptt["heartbeat"]), ("ptt", "api/ptt", "api/ptt/heartbeat"))
        self.assertNotIn("tv", ptt["forms"])
        self.assertEqual((arm["type"], arm["arm"], arm["digital"]), ("txArm", "api/autotx", True))
        for p in (ptt, arm):
            self.assertFalse({"action", "onHold", "onActivate", "tap"} & set(p))

    def test_every_transmit_setting_is_marked_and_leased_and_nothing_else_reaches_a_key_route(self):
        d = self.doc("nb/home", form="tablet", level="transmit")
        tx_keys = {"txGain", "micGain", "split", "cwWpm"}
        leased = 0
        for where, a in self.actions(d):
            path = str(a.get("path") or "").split("?")[0]
            self.assertNotIn(path, KEY_ROUTES, where)
            body = a.get("body") if isinstance(a.get("body"), dict) else {}
            if a.get("do") == "call" and set(body) & tx_keys:
                self.assertIs(a.get("tx"), True, where)
                self.assertIn(a.get("lease"), ("ptt", "txArm"), where)
                leased += 1
            elif a.get("do") == "call":
                self.assertNotEqual(a.get("level"), "transmit", where)
        self.assertEqual(leased, 4)

    def test_opening_and_using_every_screen_never_keys(self):
        for sid in screens.SCREENS:
            _d, c, _h, _s, _st = self.follow(sid, level="transmit", transmit="full", form="phone")
            c.close()
        s, _b, _h = self.req("POST", "/ui/v2/hold/receiver", {"client": "phone-1"}, level="transmit")
        self.assertEqual(s, 200)
        self.assertFalse(self.radio.state()["keyed"])
        self.assertIsNone(self.srv.lease)


class ReceiveOnly(ScreensTest):
    """SCREENS_TRANSMIT is False in the release: Brian's decision (31/10/2026)
    that no transmit part reaches a renderer until the T-tests on a real
    radio. Every screen, every form and level, asked as a transmit-level
    client with the full transmit grant."""

    def docs(self):
        for sid in screens.SCREENS:
            for form in ("tv", "phone", "tablet"):
                for level in ("view", "control", "transmit"):
                    yield (sid, form, level), self.doc(sid, form=form, level=level, transmit="full")

    def test_the_switch_is_off(self):
        self.assertIs(screens.SCREENS_TRANSMIT, False)

    def test_no_screen_carries_a_transmit_part_or_leased_call(self):
        n = 0
        for key, d in self.docs():
            self.assertEqual(ui.check(d), [], key)
            self.assertEqual(ui.schema_errors(d), [], key)
            ui.state_from_document(d)
            for p, _where, _ctx in ui.iter_parts(d["root"]):
                self.assertNotIn(p.get("type"), ("ptt", "txArm"), key)
                self.assertNotIn(p.get("id"), screens.TX_IDS | {"tx", "ptt", "txArm"}, key)
            for panel in d.get("panels") or []:
                self.assertNotEqual(panel.get("id"), "tx", key)
            self.assertNotIn('"tx": true', json.dumps(d), key)
            self.assertNotIn('"lease"', json.dumps(d), key)
            self.assertNotIn("api/ptt", json.dumps(d), key)
            self.assertNotIn("api/autotx", json.dumps(d), key)
            self.assertNotIn("api/halt", json.dumps(d), key)
            n += 1
        self.assertEqual(n, len(screens.SCREENS) * 9)

    def test_the_status_still_says_receiving(self):
        d = self.doc("nb/home", level="transmit")
        ids = {p["id"] for p, _w, _c in ui.iter_parts(d["root"]) if "id" in p}
        self.assertIn("stTransmit", ids)

    def test_the_live_screen_keeps_running_when_a_transmit_setting_changes(self):
        """The follower once set txGain, split, cwWpm and txInfo; with their
        parts out of the document it must not name them, and a change to one
        (still a SHOWN state key) must not stop the screen following."""
        d, c, _hello, start, state = self.follow("nb/home", form="phone", level="transmit", transmit="full")
        self.assertEqual(part(state, "stTransmit")["value"], "Receiving")
        for pid in screens.TX_IDS:
            self.assertNotIn(pid, start["parts"])
        self.set({"txGain": -12.0})
        self.set({"split": True})
        self.set({"vfo": 10_489_700_000.0})
        state = self.until(c, state, start, lambda s: part(s, "dial")["value"] == 10_489_700_000.0)
        self.assertEqual(part(state, "dial")["value"], 10_489_700_000.0)
        self.assertFalse([k for k in state["parts"] if k in screens.TX_IDS])
        self.assertFalse(self.radio.state()["keyed"])


class Offsets(unittest.TestCase):
    def test_tap_offset_is_minus_where_the_mode_listens(self):
        self.assertEqual(screens.tap_offset({"mode": "cw", "cwPitch": 700}), -700)
        self.assertEqual(screens.tap_offset({"mode": "usb", "filterLo": 300, "filterHi": 2700}), -1500)
        self.assertEqual(screens.tap_offset({"mode": "lsb", "filterLo": 300, "filterHi": 2700}), 1500)
        self.assertEqual(screens.tap_offset({"mode": "ft8"}), -1500)
        self.assertEqual(screens.tap_offset({"mode": "psk31"}), -1000)


if __name__ == "__main__":
    unittest.main()
