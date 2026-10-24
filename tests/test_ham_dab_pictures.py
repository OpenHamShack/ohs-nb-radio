"""DAB's pictures in Radio (24/10/2026): SlideShow's slides, SPI's station
logos and programme guide, all off air (the fetched ones are test_ham_radiodns.py).

- **The store** (ohscore/dabpics.py): a decoder's `slide`, `logo` and
  `schedule` frames are kept and come back without their bytes and with
  the path that serves them; the latest slide per service in memory; logos
  and schedules on disk, there again after a restart, within their caps; a
  session's meta gains each service's logo path and the slide's.
- **Paths become URLs per request** (server/app.py `with_urls`) under the
  request's X-Forwarded-Prefix, and only for the app's own routes.
- **End to end on the simulator,** whose ensemble is shack_sdr's showcase
  (a slide in each service's X-PAD, an SPI service with logos and a day's
  programmes): playing C221 over the API gives its slide on
  api/dab/slides/C221, its logo on api/dab/logos/C221, its guide on
  api/dab/schedule/C221, the programme type by name and now/next in the
  session's meta, logo URLs in api/dab/stations; and after a restart the
  logo is still served.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from ohscore import dabpics, sdr
from ohscore.dabpics import DabPictures
from ohscore.server import shack
from ohscore.server.app import Server, with_urls

PNG = b"\x89PNG\r\n\x1a\n" + bytes(40)


def frame(kind, t=1000.0, raw=None, **fields):
    return {"session": "ds_1", "rev": 1, "t": t, "type": "frame", "frame": kind, "fields": fields, "raw": raw}


class TheStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000.0
        self.pics = DabPictures(Path(self.tmp.name), clock=lambda: self.now)

    def test_a_slide_is_kept_and_handed_on_without_its_bytes(self):
        out = self.pics.take(frame("slide", raw=PNG, sid="C221", contentType="image/png", name="s.png", size=len(PNG)))
        self.assertNotIn("raw", out)
        self.assertEqual(out["fields"]["path"], "api/dab/slides/C221")
        self.assertEqual(self.pics.slide("C221"), (PNG, "image/png"))
        # The latest per service.
        self.pics.take(frame("slide", raw=PNG + b"2", sid="C221", contentType="image/png"))
        self.assertEqual(self.pics.slide("C221")[0], PNG + b"2")
        # Not a picture type SlideShow allows, or a bad service id: not kept.
        self.pics.take(frame("slide", raw=b"GIF89a", sid="C3A7", contentType="image/gif"))
        self.pics.take(frame("slide", raw=PNG, sid="../x", contentType="image/png"))
        self.assertIsNone(self.pics.slide("C3A7"))
        self.assertEqual(list(self.pics.slides), ["C221"])

    def test_slides_are_bounded_in_number(self):
        for i in range(dabpics.MAX_SLIDES + 5):
            self.pics.take(frame("slide", raw=PNG, sid=f"{0xC000 + i:04X}", contentType="image/png"))
        self.assertEqual(len(self.pics.slides), dabpics.MAX_SLIDES)
        self.assertIsNone(self.pics.slide("C000"), "the least recently changed went first")

    def test_logos_and_schedules_survive_a_restart(self):
        self.pics.take(frame("logo", raw=PNG, sid="C221", variant="square", contentType="image/png", width=128,
                             height=128))
        self.pics.take(frame("logo", raw=PNG + b"w", sid="C221", variant="wide", contentType="image/png", width=320,
                             height=240))
        progs = [{"name": "Breakfast", "start": "1970-01-01T00:00:00Z", "durationS": 3600, "description": None}]
        out = self.pics.take(frame("schedule", sid="C221", programmes=progs))
        self.assertEqual(out["fields"], {"sid": "C221", "programmes": 1, "path": "api/dab/schedule/C221"})
        again = DabPictures(Path(self.tmp.name), clock=lambda: self.now)
        self.assertEqual(again.logo("C221", "square"), (PNG, "image/png"))
        self.assertEqual(again.logo("C221", "wide"), (PNG + b"w", "image/png"))
        self.assertEqual(again.logo_paths("C221"), {"logoPath": "api/dab/logos/C221", "logoSource": "broadcast",
                                                    "logoWidePath": "api/dab/logos/C221?variant=wide",
                                                    "logoWideSource": "broadcast"})
        self.assertEqual(again.schedule("C221"), progs)
        self.assertEqual(again.schedule("C221", date="1970-01-02"), [])
        self.assertIsNone(again.slide("C221"), "a slide is what is on now: never kept past a restart")

    def test_a_missing_variant_falls_back_and_logos_are_bounded_on_disk(self):
        self.pics.take(frame("logo", raw=PNG, sid="C221", variant="wide", contentType="image/png"))
        self.assertEqual(self.pics.logo("C221", "square"), (PNG, "image/png"))
        with mock.patch.object(dabpics, "LOGO_FILES", 3):
            for i in range(6):
                self.now += 1
                self.pics.take(frame("logo", t=self.now, raw=PNG, sid=f"{0xD000 + i:04X}", variant="square",
                                     contentType="image/png"))
        files = sorted(p.name for p in (Path(self.tmp.name) / "dab").iterdir() if p.suffix == ".png")
        self.assertEqual(files, ["D003-square.png", "D004-square.png", "D005-square.png"])
        self.assertFalse(self.pics.has_logo("C221"))

    def test_old_programmes_are_dropped(self):
        old = {"name": "Old", "start": "1970-01-01T00:00:00Z", "durationS": 3600}
        new = {"name": "New", "start": "1970-01-03T00:00:00Z", "durationS": 3600}
        self.now = 2 * 86_400.0 + 10
        self.pics.take(frame("schedule", sid="C221", programmes=[old, new]))
        self.assertEqual([p["name"] for p in self.pics.schedule("C221")], ["New"])

    def test_a_meta_gains_logo_and_slide_paths(self):
        self.pics.take(frame("logo", raw=PNG, sid="C221", variant="square", contentType="image/png"))
        self.pics.take(frame("slide", raw=PNG, sid="C221", contentType="image/png", name="s.png"))
        meta = {"services": [{"sid": "C221"}, {"sid": "C3A7"}], "slide": {"sid": "C221", "name": "s.png"}}
        out = self.pics.decorate(meta)
        self.assertEqual(out["services"], [{"sid": "C221", "logoPath": "api/dab/logos/C221",
                                                "logoSource": "broadcast"}, {"sid": "C3A7"}])
        self.assertEqual(out["slide"]["path"], "api/dab/slides/C221")
        self.assertIsInstance(out["slide"]["rev"], int)
        self.assertNotIn("logoPath", meta["services"][0], "the meta given is not changed")


class NowAndNext(unittest.TestCase):
    """Now and next from the stored schedule (the tablet's 12B check: the
    guide on disk, Radio 4 playing, and now/next null for five minutes)."""

    PROGS = [
        {"name": "Selection of BBC World Service Programmes", "start": "2026-10-24T00:00:00Z", "durationS": 16200,
         "description": "BBC Radio 4 joins the BBC World Service."},
        {"name": "News Summary", "start": "2026-10-24T04:30:00Z", "durationS": 240, "description": None},
        {"name": "Farming Today", "start": "2026-10-24T04:34:00Z", "durationS": 900, "description": None},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from datetime import datetime, timezone
        self.now = datetime(2026, 10, 24, 3, 10, tzinfo=timezone.utc).timestamp()
        self.pics = DabPictures(Path(self.tmp.name), clock=lambda: self.now)
        self.pics.take(frame("schedule", t=self.now, sid="C224", programmes=self.PROGS))

    def test_the_meta_gains_now_and_next_by_the_clock_from_the_stored_schedule(self):
        meta = {"services": [{"sid": "C224", "now": None, "next": None}, {"sid": "C221", "now": None, "next": None}]}
        c224, c221 = self.pics.decorate(meta)["services"]
        self.assertEqual(c224["now"]["name"], "Selection of BBC World Service Programmes")
        self.assertEqual(c224["next"]["name"], "News Summary")
        self.assertIsNone(c221["now"], "no schedule: the decoder's (none) stands")
        # The clock passes a boundary: the same meta, decorated later.
        self.now += 80 * 60  # 04:30
        c224 = self.pics.decorate(meta)["services"][0]
        self.assertEqual((c224["now"]["name"], c224["next"]["name"]), ("News Summary", "Farming Today"))
        # After a restart, the same from disk.
        again = DabPictures(Path(self.tmp.name), clock=lambda: self.now)
        self.assertEqual(again.decorate(meta)["services"][0]["now"]["name"], "News Summary")

    def test_the_feed_is_sent_a_fresh_meta_when_now_or_next_changes(self):
        from ohscore.decoders import Decoders, _Fixed
        published = []
        meta = {"services": [{"sid": "C224", "now": None, "next": None}], "playing": "C224"}

        class Host:
            def poll(self, n):
                return []

            def status(self, sid):
                return {"meta": meta, "rev": 41, "state": "synced"}

        engine = type("E", (), {"dab_pictures": self.pics, "st": {}, "_publish": lambda e, k, it: published.append(it)})()
        d = Decoders(engine)
        d.host = Host()
        f = _Fixed("ds_1", "dab", 225_648_000.0, {}, "meta")
        f.held, f.host = True, Host()
        d.fixed["ds_1"] = f
        d.tick()
        self.assertEqual(published, [], "nothing changed yet")
        self.now += 80 * 60
        d._watch_due = 0.0
        d.tick()
        (it,) = published
        self.assertEqual((it["type"], it["refresh"], it["rev"]), ("meta", True, 41))
        self.assertEqual(it["fields"]["services"][0]["now"]["name"], "News Summary")
        self.assertEqual(list(f.results)[-1], it)
        d._watch_due = 0.0
        d.tick()
        self.assertEqual(len(published), 1, "sent once per change")


class Urls(unittest.TestCase):
    def test_paths_become_urls_under_the_prefix_and_nothing_else_changes(self):
        obj = {"services": [{"sid": "C221", "logoPath": "api/dab/logos/C221"}],
               "slide": {"path": "api/dab/slides/C221"}, "file": {"path": "/home/x/y.png"}, "n": 1}
        out = with_urls(obj, "/apps/radio/")
        self.assertEqual(out["services"][0]["logoUrl"], "/apps/radio/api/dab/logos/C221")
        self.assertEqual(out["slide"]["url"], "/apps/radio/api/dab/slides/C221")
        self.assertNotIn("url", out["file"], "a filesystem path is never a link")
        self.assertNotIn("logoUrl", obj["services"][0])
        same = {"a": [1, 2, {"b": "c"}]}
        self.assertIs(with_urls(same, "/"), same)


SECRET = "s" * 32


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class OverTheApi(unittest.TestCase):
    """The simulator's showcase ensemble, played over the API."""

    def setUp(self):
        from ohscore.server.audio import StreamAudio
        from ohsradio import server as ham_server
        from ohsradio.radio import Radio
        from listen_helpers import ListeningSim
        from ohsradio.devices import simdab
        from shack_sdr import _native
        try:
            _native.testsig_dab(1, showcase_mjd=61_337)
        except TypeError:
            self.skipTest("shack_sdr without the showcase ensemble")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
                    "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": 145_500_000.0,
                    "mode": "fm"}
        self.parts = (Radio, ham_server, StreamAudio, ListeningSim, simdab)
        self.boot()

    def boot(self):
        Radio, ham_server, StreamAudio, ListeningSim, simdab = self.parts
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(self.cfg, persist=False, data_dir=self.tmp.name, audio=self.audio,
                           device=ListeningSim(dict(self.cfg), 2_400_000.0, [simdab.DabEnsemble("11D", -30.0)]))
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.assertEqual(self.srv.start_radio(), "")

    def shutdown(self):
        self.srv.shutdown()

    def req(self, method, path, body=None, level="control", prefix=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"}
        if prefix:
            headers["X-Forwarded-Prefix"] = prefix
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        if raw:
            return r.status, data, r.getheader("Content-Type")
        return r.status, json.loads(data)

    def wait(self, cond, timeout=90.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.radio.heartbeat()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_slides_logos_and_the_guide_reach_a_client(self):
        self.addCleanup(lambda: self.shutdown())
        s, a = self.req("POST", "/api/decoders/sessions",
                        {"decoder": "dab", "freqHz": 222_064_000.0, "params": {"block": "11D", "service": "C221"}})
        self.assertEqual(s, 201, a)
        sid = a["id"]

        def meta():
            return self.req("GET", f"/api/decoders/sessions/{sid}", level="view", prefix="/apps/radio")[1].get("meta") or {}

        def c221(m):
            return next((x for x in m.get("services") or [] if x["sid"] == "C221"), {})
        self.assertTrue(self.wait(lambda: ((m := meta()).get("slide") or {}).get("url") and c221(m).get("logoUrl")
                                  and c221(m).get("now")), meta())
        m = meta()
        self.assertEqual(m["slide"]["url"], "/apps/radio/api/dab/slides/C221")
        self.assertEqual(m["slide"]["contentType"], "image/png")
        self.assertEqual(c221(m)["logoUrl"], "/apps/radio/api/dab/logos/C221")
        self.assertEqual(c221(m)["logoWideUrl"], "/apps/radio/api/dab/logos/C221?variant=wide")
        self.assertEqual(c221(m)["ptyName"], "Pop music")
        self.assertEqual(c221(m)["language"], "en")
        self.assertTrue(c221(m)["hasSlideshow"])
        self.assertTrue(c221(m)["now"]["name"].startswith("Shack MP2 Tone "))
        self.assertEqual(m["dlPlus"]["itemArtist"], "Shack MP2 Tone")
        # The pictures themselves.
        s, data, ctype = self.req("GET", "/api/dab/slides/C221", level="view", raw=True)
        self.assertEqual((s, ctype, data[:8]), (200, "image/png", b"\x89PNG\r\n\x1a\n"))
        s, data, ctype = self.req("GET", "/api/dab/logos/C221?variant=wide", level="view", raw=True)
        self.assertEqual((s, ctype, data[:4]), (200, "image/png", b"\x89PNG"))
        s, a = self.req("GET", "/api/dab/slides", level="view")
        self.assertEqual([x["sid"] for x in a["slides"]], ["C221"])
        self.assertEqual(a["slides"][0]["url"], "/api/dab/slides/C221")
        # The day's guide.
        s, a = self.req("GET", "/api/dab/schedule/C221", level="view")
        self.assertEqual(s, 200, a)
        self.assertEqual(len(a["programmes"]), 4)
        day = a["programmes"][0]["start"][:10]
        s, a = self.req("GET", f"/api/dab/schedule/C221?date={day}", level="view")
        self.assertEqual(len(a["programmes"]), 4)
        # Refusals.
        self.assertEqual(self.req("GET", "/api/dab/slides/ZZZZ", level="view")[1]["code"], "bad_params")
        self.assertEqual(self.req("GET", "/api/dab/slides/C3A8", level="view")[1]["code"], "no_slide")
        self.assertEqual(self.req("GET", "/api/dab/logos/C221?variant=tall", level="view")[1]["code"], "bad_params")
        self.assertEqual(self.req("GET", "/api/dab/schedule/C221?date=today", level="view")[1]["code"], "bad_params")
        # The station list: logo URLs beside each service the scan listed.
        from ohsradio.bandscan import dab_ensemble
        sc = self.radio.bandscan
        sc.records["dab"]["ensembles"] = [dab_ensemble("11D", 222_064_000.0, m)]
        s, a = self.req("GET", "/api/dab/stations", level="view", prefix="/apps/radio")
        (svc,) = [x for x in a["ensembles"][0]["services"] if x["sid"] == "C221"]
        self.assertEqual((svc["logoUrl"], svc["ptyName"], svc["pty"]), ("/apps/radio/api/dab/logos/C221", "Pop music", 10))
        # The decoder feed's items carry no bytes.
        kept = self.radio.decoders.session(sid)["results"]
        frames = [r for r in kept if r["type"] == "frame"]
        self.assertTrue(frames and all("raw" not in r for r in frames))
        self.assertIn("slide", {r["frame"] for r in frames})
        # After a restart, the logo is still served; the slide is not.
        self.req("DELETE", f"/api/decoders/sessions/{sid}")
        self.shutdown()
        self.boot()
        s, data, ctype = self.req("GET", "/api/dab/logos/C221", level="view", raw=True)
        self.assertEqual((s, ctype), (200, "image/png"))
        self.assertEqual(self.req("GET", "/api/dab/slides/C221", level="view")[1]["code"], "no_slide")
        self.assertEqual(len(self.req("GET", "/api/dab/schedule/C221", level="view")[1]["programmes"]), 4)


if __name__ == "__main__":
    unittest.main()
