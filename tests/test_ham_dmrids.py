"""DMR callsigns and names (ohsradio/dmrids.py, 28/10/2026), against a fake
radioid.net and a fake Brandmeister on a local socket: nothing here can
reach the real internet (a test's Radio starts no fetcher, and each test
points the fetcher at its own server or a closed port).

Every ID is under country code 999 (no country's) and every listed
callsign starts Q, which no country issues: the list is personal data, and
this repository is public.

- **Offline, nothing yet:** no list, no error, bare IDs; a source that
  cannot be reached costs one bounded attempt, then backoff that survives
  a restart, and the next look asks nothing.
- **A fetch:** both lists parsed into the index; lookups, the talkgroup
  names and `view()`; the requests say only "OpenHamShack-Radio/<version>",
  and carry no cookie although the server sets one.
- **Weekly and conditional:** nothing is asked within the week; after it,
  the users list is asked with If-None-Match and If-Modified-Since and a
  304 keeps the copy; the talkgroups, with no validators, are fetched and
  not rewritten when unchanged.
- **The swap:** a changed list replaces the old one while lookups run
  without pause, each seeing the old entry or the new one, never neither;
  a download cut short or a list with no rows leaves the old one serving
  and no part file behind.
- **The setting off:** no request at all and bare IDs; on again, names.
- **Names in a session:** the band simulator's repeater decoded by a `dmr`
  session, its calls and messages and its slots' meta named from the list,
  the talker alias winning over the list's callsign.
- **Over the API:** api/status `dmrIds`, and api/set dmrIdLookup=false.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import gzip
import http.server
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ohsradio import dmrids
from ohsradio.dmrids import DmrIds, annotate

HEADER = "RADIO_ID,CALLSIGN,FIRST_NAME,LAST_NAME,CITY,STATE,COUNTRY\r\n"
# The simulator's callers: 9990001 sends the alias "MX0TST Test" but the
# list gives another callsign (the alias must win, and the list's name for
# somebody else must not be added); 9990002's alias "MX0ABC" agrees with the
# list (its name is added); 9990003 sends none (the list names it).
ROWS = [(9990001, "Q9AAA", "Alpha", "Surname", "Testville", "Teststate", "Testland"),
        (9990002, "MX0ABC", "Bravo", "Surname", "Testville", "", "Testland"),
        (9990003, "q9ccc", "Charlie", "", "Othertown", "", "Otherland"),
        # Rows the parser must drop: no callsign, an ID past 24 bits, not a number.
        (9990004, "", "Nobody", "", "", "", ""),
        (99999999, "Q9BIG", "Big", "", "", "", ""),
        ("abc", "Q9BAD", "Bad", "", "", "", "")]
TALKGROUPS = {"99": "Test Ninety-Nine", "98": "Test Ninety-Eight", "x": "Not a number", "97": ""}


def csv_of(rows) -> bytes:
    return (HEADER + "".join(",".join(str(c) for c in r) + "\r\n" for r in rows)).encode()


def many(n, call="Q9M{:04d}"):
    """n rows under 999, for the swap test."""
    return [(9_990_000 + i, call.format(i), "Name", "", "Town", "", "Testland") for i in range(1, n + 1)]


class FakeSources:
    """radioid.net's user.csv (ETag and Last-Modified, 304 on a match) and
    Brandmeister's talkgroup list (gzip, no validators), on one port."""

    def __init__(self):
        self.users = csv_of(ROWS)
        self.etag = '"v1"'
        self.talkgroups = json.dumps(TALKGROUPS).encode()
        self.requests: list[tuple[str, dict]] = []
        self.full = {"/user.csv": 0, "/talkgroup": 0}
        self.cut_short = False
        self.fail = False
        me = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                me.requests.append((self.path, dict(self.headers)))
                if me.fail:
                    self.send_response(503)
                    self.end_headers()
                    return
                if self.path == "/user.csv":
                    if self.headers.get("If-None-Match") == me.etag:
                        self.send_response(304)
                        self.end_headers()
                        return
                    me.full[self.path] += 1
                    body = me.users
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("ETag", me.etag)
                    self.send_header("Last-Modified", "Wed, 28 Oct 2026 05:01:53 GMT")
                    self.send_header("Set-Cookie", "tracker=1")
                    self.send_header("Content-Length", str(len(body) * (2 if me.cut_short else 1)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/talkgroup":
                    me.full[self.path] += 1
                    body = gzip.compress(me.talkgroups)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Encoding", "gzip")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def urls(self) -> dict:
        return {"users_url": f"http://127.0.0.1:{self.port}/user.csv",
                "talkgroups_url": f"http://127.0.0.1:{self.port}/talkgroup"}

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
        self.dir = Path(self.tmp.name) / "dmrids"
        self.clock = Clock()
        self.on = [True]

    def ids(self, **urls) -> DmrIds:
        ids = DmrIds(self.dir, enabled=lambda: self.on[0], clock=self.clock, timeout=5.0, **urls)
        self.addCleanup(ids.close)
        return ids

    def fake(self) -> FakeSources:
        f = FakeSources()
        self.addCleanup(f.close)
        return f


class Offline(Base):
    def test_no_list_yet_is_bare_ids_and_no_error(self):
        ids = self.ids()
        self.assertIsNone(ids.user(9990001))
        self.assertIsNone(ids.talkgroup(99))
        self.assertEqual(ids.view(), {"available": False, "count": 0, "updatedUtc": None, "source": None,
                                      "talkgroups": 0})
        slot = {"slot": 1, "src": 9990001, "dst": 99, "callType": "group", "alias": None}
        self.assertEqual(annotate(slot, ids), slot)
        # The defaults, under scratch_home, are a closed local port: a
        # look fails at once, quietly, and changes nothing.
        self.assertTrue(all(u.startswith("http://127.0.0.1:9/") for u in ids.urls.values()), ids.urls)
        self.assertEqual(ids.run_once(), {"users": "failed", "talkgroups": "failed"})
        self.assertEqual(annotate(slot, ids), slot)

    def test_unreachable_sources_back_off_and_stay_backed_off_after_a_restart(self):
        port = closed_port()
        urls = {"users_url": f"http://127.0.0.1:{port}/user.csv",
                "talkgroups_url": f"http://127.0.0.1:{port}/talkgroup"}
        ids = self.ids(**urls)
        t0 = time.monotonic()
        self.assertEqual(ids.run_once(), {"users": "failed", "talkgroups": "failed"})
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertFalse(ids.view()["available"])
        # The next look within the backoff asks nothing.
        self.assertEqual(ids.run_once(), {"users": "backoff", "talkgroups": "backoff"})
        again = self.ids(**urls)
        self.assertEqual(again.run_once(), {"users": "backoff", "talkgroups": "backoff"})
        # Each failure doubles the wait, to a day at most, and never gives up.
        for _ in range(12):
            self.clock.t += dmrids.BACKOFF_MAX_S + 1
            self.assertEqual(again.run_once(), {"users": "failed", "talkgroups": "failed"})
        waits = again.state["users"]["until"] - self.clock.t
        self.assertEqual(waits, dmrids.BACKOFF_MAX_S)

    def test_a_server_error_is_a_failure_too(self):
        f = self.fake()
        f.fail = True
        ids = self.ids(**f.urls())
        self.assertEqual(ids.run_once(), {"users": "failed", "talkgroups": "failed"})
        self.assertIsNone(ids.user(9990001))


class Fetching(Base):
    def test_both_lists_fetched_and_looked_up(self):
        f = self.fake()
        seen = []
        ids = self.ids(**f.urls())
        ids.on_change = seen.append
        self.assertEqual(ids.run_once(), {"users": "fetched", "talkgroups": "fetched"})
        self.assertEqual(ids.user(9990001), {"callsign": "Q9AAA", "name": "Alpha", "city": "Testville",
                                             "state": "Teststate", "country": "Testland"})
        self.assertEqual(ids.user(9990003)["callsign"], "Q9CCC")      # upper case
        self.assertIsNone(ids.user(9990002 + 100))
        for dropped in (9990004, 99999999):
            self.assertIsNone(ids.user(dropped))
        self.assertEqual((ids.talkgroup(99), ids.talkgroup(97), ids.talkgroup(12345)),
                         ("Test Ninety-Nine", None, None))
        view = ids.view()
        self.assertEqual((view["available"], view["count"], view["source"], view["talkgroups"]),
                         (True, 3, "radioid.net", 2))
        self.assertRegex(view["updatedUtc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(seen, [view])
        # What went out: the program and its version, and nothing else.
        for path, h in f.requests:
            self.assertEqual(h["User-Agent"], dmrids.user_agent())
            self.assertRegex(h["User-Agent"], r"^OpenHamShack-Radio/[^ ]+$")
            self.assertNotIn("Cookie", h)
            self.assertNotIn("If-None-Match", h)              # nothing held yet: not conditional
        # Kept: a restart reads the copy without asking.
        f.requests.clear()
        again = self.ids(**f.urls())
        self.assertEqual(again.user(9990002)["name"], "Bravo")
        self.assertEqual(again.talkgroup(98), "Test Ninety-Eight")
        self.assertEqual(again.run_once(), {"users": "fresh", "talkgroups": "fresh"})
        self.assertEqual(f.requests, [])

    def test_weekly_looks_are_conditional_and_a_304_keeps_the_copy(self):
        f = self.fake()
        ids = self.ids(**f.urls())
        ids.run_once()
        self.clock.t += dmrids.REFRESH_S - 60
        self.assertEqual(ids.run_once(), {"users": "fresh", "talkgroups": "fresh"})
        self.clock.t += 120
        f.requests.clear()
        self.assertEqual(ids.run_once(), {"users": "unchanged", "talkgroups": "unchanged"})
        users = dict(f.requests)["/user.csv"]
        self.assertEqual((users["If-None-Match"], users["If-Modified-Since"]),
                         ('"v1"', "Wed, 28 Oct 2026 05:01:53 GMT"))
        self.assertEqual(f.full, {"/user.csv": 1, "/talkgroup": 2})
        self.assertEqual(ids.user(9990001)["callsign"], "Q9AAA")
        # Asked again only a week after this look.
        self.clock.t += 3600
        self.assertEqual(ids.run_once(), {"users": "fresh", "talkgroups": "fresh"})

    def test_a_changed_list_swaps_in_while_lookups_run(self):
        f = self.fake()
        f.users = csv_of(many(4000))
        ids = self.ids(**f.urls())
        ids.run_once()
        self.assertEqual(ids.view()["count"], 4000)
        f.users, f.etag = csv_of(many(4000, call="Q8N{:04d}")), '"v2"'
        self.clock.t += dmrids.REFRESH_S + 1
        bad, seen, stop = [], set(), threading.Event()

        def look():
            while not stop.is_set():
                for rid in (9990001, 9992000, 9994000):
                    try:
                        got = ids.user(rid)
                    except Exception as e:  # noqa: BLE001 - what the test is looking for
                        bad.append(repr(e))
                        continue
                    if got is None:
                        bad.append(f"{rid}: none")
                    else:
                        seen.add(got["callsign"][:3])

        t = threading.Thread(target=look)
        t.start()
        try:
            self.assertEqual(ids.run_once()["users"], "fetched")
            time.sleep(0.05)
        finally:
            stop.set()
            t.join()
        self.assertEqual(bad, [])
        self.assertIn("Q8N", seen)
        self.assertEqual(ids.user(9994000)["callsign"], "Q8N4000")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["state.json", "talkgroups.json",
                                                                       "users.sqlite"])

    def test_a_download_cut_short_or_empty_leaves_the_old_list(self):
        f = self.fake()
        ids = self.ids(**f.urls())
        ids.run_once()
        f.users, f.etag, f.cut_short = csv_of(many(10)), '"v2"', True
        self.clock.t += dmrids.REFRESH_S + 1
        self.assertEqual(ids.run_once()["users"], "failed")
        self.assertEqual((ids.user(9990001)["callsign"], ids.view()["count"]), ("Q9AAA", 3))
        self.assertFalse(any(p.name.endswith(".part") for p in self.dir.iterdir()))
        # A header and no rows: the same.
        f.cut_short, f.users, f.etag = False, csv_of([]), '"v3"'
        self.clock.t += dmrids.BACKOFF_MAX_S + 1
        self.assertEqual(ids.run_once()["users"], "failed")
        self.assertEqual(ids.user(9990001)["callsign"], "Q9AAA")
        # Not radioid.net's list at all: the same.
        f.users, f.etag = b"<html>maintenance</html>\n", '"v4"'
        self.clock.t += dmrids.BACKOFF_MAX_S + 1
        self.assertEqual(ids.run_once()["users"], "failed")
        self.assertEqual(ids.user(9990001)["callsign"], "Q9AAA")

    def test_the_setting_off_asks_nothing_and_names_nothing(self):
        f = self.fake()
        ids = self.ids(**f.urls())
        self.on[0] = False
        self.assertEqual(ids.run_once(), {"users": "off", "talkgroups": "off"})
        self.assertEqual(f.requests, [])
        self.on[0] = True
        ids.run_once()
        self.on[0] = False
        self.assertIsNone(ids.user(9990001))
        self.assertFalse(ids.view()["available"])
        slot = {"slot": 2, "src": 9990003, "dst": 98, "callType": "group"}
        self.assertEqual(annotate(slot, ids), slot)
        self.on[0] = True
        self.assertEqual(annotate(slot, ids)["srcCallsign"], "Q9CCC")


class Naming(Base):
    def setUp(self):
        super().setUp()
        f = self.fake()
        self.list = self.ids(**f.urls())
        self.list.run_once()

    def test_the_list_names_a_caller_without_an_alias(self):
        got = annotate({"src": 9990003, "dst": 98, "callType": "group", "alias": None}, self.list)
        self.assertEqual({k: got.get(k) for k in ("srcCallsign", "srcName", "srcCountry", "dstName")},
                         {"srcCallsign": "Q9CCC", "srcName": "Charlie", "srcCountry": "Otherland",
                          "dstName": "Test Ninety-Eight"})

    def test_the_talker_alias_wins_over_the_list(self):
        got = annotate({"src": 9990001, "dst": 99, "callType": "group", "alias": "MX0TST Test"}, self.list)
        self.assertEqual(got["srcCallsign"], "MX0TST")
        # The list's name and country are someone else's: not added.
        self.assertNotIn("srcName", got)
        self.assertNotIn("srcCountry", got)
        agree = annotate({"src": 9990002, "dst": 9990001, "callType": "private", "alias": "mx0abc"}, self.list)
        self.assertEqual((agree["srcCallsign"], agree["srcName"], agree["srcCountry"]),
                         ("MX0ABC", "Bravo", "Testland"))
        self.assertNotIn("dstName", agree)          # a private call's dst is a radio, not a talkgroup
        # An alias with no callsign in it leaves the list's standing.
        loose = annotate({"src": 9990003, "alias": "Charlie's handheld"}, self.list)
        self.assertEqual(loose["srcCallsign"], "Q9CCC")

    def test_messages_name_their_talkgroup_by_the_group_flag(self):
        got = annotate({"src": 9990002, "dst": 99, "group": True, "text": "hi"}, self.list)
        self.assertEqual((got["srcCallsign"], got["dstName"]), ("MX0ABC", "Test Ninety-Nine"))
        self.assertNotIn("dstName", annotate({"src": 9990002, "dst": 99, "group": False}, self.list))


def has_dmr() -> bool:
    from ohscore import sdr
    m = sdr.load()
    return m is not None and any(e["id"] == "dmr" for e in m.catalogue())


@unittest.skipUnless(has_dmr(), "no shack_sdr with DMR for this machine")
class InASession(unittest.TestCase):
    """The band simulator's repeater (ohsradio/devices/simdmr.py), named
    from the fake list through the radio's own DmrIds."""

    def test_calls_messages_and_meta_are_named(self):
        from ham_helpers import close, pump
        from listen_helpers import TapAudio
        from ohsradio.devices import simdmr
        from ohsradio.radio import Radio
        tmp = tempfile.TemporaryDirectory()
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": simdmr.FREQ, "mode": "fm"}
        r = Radio(cfg, persist=False, data_dir=tmp.name, audio=TapAudio())
        r._tmp = tmp
        self.addCleanup(close, r)
        self.addCleanup(r.dmr_ids.close)
        self.assertFalse(r.st["dmrIds"]["available"])
        f = FakeSources()
        self.addCleanup(f.close)
        r.dmr_ids.urls = {"users": f.urls()["users_url"], "talkgroups": f.urls()["talkgroups_url"]}
        r.dmr_ids.run_once()
        self.assertEqual((r.st["dmrIds"]["available"], r.st["dmrIds"]["count"]), (True, 3))
        feed = r.subscribe("decoders", 20_000)
        r.start()
        sid = r.decoders.start("dmr", simdmr.FREQ)["id"]
        got = pump(r, 90, feeds=[feed],
                   until=lambda: len([x for x in r.decoders.session(sid)["results"]
                                      if x.get("frame") in ("call_end", "sms")]) >= 4)["decoders"]
        ends = {(i["fields"]["slot"], i["fields"]["src"]): i["fields"] for i in got
                if i.get("session") == sid and i.get("frame") == "call_end"}
        tg, private, secret = ends[1, 9990001], ends[2, 9990002], ends[2, 9990003]
        self.assertEqual((tg["srcCallsign"], tg["dstName"]), ("MX0TST", "Test Ninety-Nine"))
        self.assertNotIn("srcName", tg)                 # the alias won; the list's name is another's
        self.assertEqual((private["srcCallsign"], private["srcName"]), ("MX0ABC", "Bravo"))
        self.assertEqual((secret["srcCallsign"], secret["srcName"], secret["srcCountry"], secret["dstName"]),
                         ("Q9CCC", "Charlie", "Otherland", "Test Ninety-Eight"))
        # The kept results are the named ones too.
        kept = [x["fields"] for x in r.decoders.session(sid)["results"] if x.get("frame") == "sms"]
        self.assertEqual(kept[0]["srcCallsign"], "MX0ABC")
        # And the slots' meta.
        slots = {s["slot"]: s for s in r.decoders.session(sid)["meta"]["slots"]}
        self.assertTrue(all(s.get("srcCallsign") for s in slots.values()), slots)
        # Off: bare IDs at once, and the status says so.
        r.set(dmrIdLookup=False)
        self.assertFalse(r.st["dmrIds"]["available"])
        slots = r.decoders.session(sid)["meta"]["slots"]
        self.assertFalse(any("srcCallsign" in s or "dstName" in s for s in slots), slots)


class OverTheApi(unittest.TestCase):
    def test_status_carries_dmr_ids_and_the_setting_turns_it_off(self):
        import test_server
        from ohscore.server.app import Server
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.radio import Radio
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        audio = StreamAudio(realtime=False)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "callsign": "GM4BRI",
               "licenceClass": "full", "vfo": 14_070_000.0, "mode": "usb"}
        radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
        self.addCleanup(radio.dmr_ids.close)
        srv = Server(radio, ham_server.info("9.9.9"), audio, secret=test_server.SECRET)
        test = test_server.ServerTest()
        test.port = srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(srv.shutdown)
        self.assertEqual(srv.start_radio(), "")
        status = test.req("GET", "/api/status", level="view")[1]
        self.assertEqual(status["dmrIds"], {"available": False, "count": 0, "updatedUtc": None, "source": None,
                                            "talkgroups": 0})
        f = FakeSources()
        self.addCleanup(f.close)
        radio.dmr_ids.urls = {"users": f.urls()["users_url"], "talkgroups": f.urls()["talkgroups_url"]}
        radio.dmr_ids.run_once()
        got = test.req("GET", "/api/status", level="view")[1]["dmrIds"]
        self.assertEqual((got["available"], got["count"], got["source"], got["talkgroups"]),
                         (True, 3, "radioid.net", 2))
        s, _ = test.req("POST", "/api/set", {"dmrIdLookup": False}, level="control")
        self.assertEqual(s, 200)
        self.assertFalse(test.req("GET", "/api/status", level="view")[1]["dmrIds"]["available"])


if __name__ == "__main__":
    unittest.main()
