"""Recordings on the controller through the store form's API
(ohscore/server/recording.py, docs/SERVER-API.md "Recordings"): receive
audio as FLAC and the IQ as SigMF, on a real QO-100 NB engine on the
simulator over real HTTP. Receive only: nothing here keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
from collections import namedtuple
from pathlib import Path
from unittest import mock

from ohscore import shacklibs, sigmf
from ohscore.server import shack
from test_server import SECRET, ServerTest

Usage = namedtuple("Usage", "total used free")
GB = 1_000_000_000


class Recordings(ServerTest):
    def raw(self, method, path, headers=None, level="view"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
             "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device", **(headers or {})}
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def record(self, kind, seconds=1.0):
        s, a = self.req("POST", "/api/recordings/start", {"kind": kind}, level="control")
        self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: any(x["kind"] == kind and x["seconds"] >= seconds
                                              for x in self.req("GET", "/api/recordings/status")[1]["active"]),
                                  timeout=30))
        s, a = self.req("POST", "/api/recordings/stop", {"kind": kind}, level="control")
        self.assertEqual(s, 200, a)
        self.assertEqual(a["recording"], False)
        self.assertEqual([x["kind"] for x in a["stopped"]], [kind])
        (e,) = [x for x in self.req("GET", "/api/recordings")[1]["recordings"] if x["id"] == a["stopped"][0]["id"]]
        return e

    def test_audio_is_recorded_listed_downloaded_with_ranges_and_deleted(self):
        s, a = self.req("POST", "/api/set", {"mode": "usb", "vfo": 10_489_750_000.0}, level="control")
        self.assertEqual(s, 200, a)
        self.assertEqual(self.req("GET", "/api/status")[1]["recordings"], {"kinds": ["audio", "iq"], "active": []})
        e = self.record("audio")
        self.assertEqual((e["kind"], e["format"], e["mode"], e["station"]), ("audio", "flac", "USB", "GM4BRI"))
        self.assertAlmostEqual(e["freqHz"], self.radio.state()["rxDial"], delta=1)
        self.assertEqual((e["sampleRate"], e["channels"], e["complete"]), (12_000, 1, True))
        self.assertGreater(e["seconds"], 0.9)          # status rounds to 0.1 s
        # On the data volume's recordings folder, beside nothing else.
        self.assertEqual(Path(self.radio.recordings_dir(), e["parts"]["data"]["name"]).stat().st_size,
                         e["parts"]["data"]["bytes"])

        q = f"/api/recordings/file?id={e['id']}&part=data"
        s, h, body = self.raw("GET", q)
        self.assertEqual((s, h["Content-Type"], h["Accept-Ranges"]), (200, "audio/flac", "bytes"))
        self.assertTrue(body.startswith(b"fLaC"))
        self.assertTrue(h["Content-Disposition"].startswith("inline"))
        size = len(body)
        s, h, part = self.raw("GET", q, {"Range": "bytes=100-199"})
        self.assertEqual((s, h["Content-Range"], part), (206, f"bytes 100-199/{size}", body[100:200]))
        s, h, part = self.raw("GET", q, {"Range": "bytes=-10"})
        self.assertEqual((s, part), (206, body[-10:]))
        s, h, _b = self.raw("GET", q, {"Range": f"bytes={size}-"})
        self.assertEqual((s, h["Content-Range"]), (416, f"bytes */{size}"))
        s, h, _b = self.raw("GET", q + "&download=1")
        self.assertTrue(h["Content-Disposition"].startswith("attachment"))

        s, _h, meta = self.raw("GET", f"/api/recordings/file?id={e['id']}&part=meta")
        side = json.loads(meta)
        self.assertEqual((side["station"], side["mode"], side["radio"], side["appName"]),
                         ("GM4BRI", "USB", "sim", "QO-100 NB"))
        self.assertEqual(side["changes"][0]["t"], 0.0)
        self.assertTrue(side["startUtc"].endswith("Z"))

        s, a = self.req("POST", "/api/recordings/delete", {"id": e["id"]}, level="control")
        self.assertEqual((s, a["deleted"]["id"]), (200, e["id"]))
        self.assertEqual(self.req("GET", "/api/recordings")[1]["recordings"], [])
        self.assertEqual(self.raw("GET", q)[0], 404)

    def test_iq_is_sigmf_the_engine_can_play_again(self):
        e = self.record("iq", seconds=0.5)
        self.assertEqual((e["kind"], e["format"], e["station"]), ("iq", "sigmf-ci16_le", "GM4BRI"))
        self.assertEqual(e["sampleRate"], self.radio.state()["fs"])
        self.assertEqual(e["parts"]["data"]["type"], "application/octet-stream")
        path = Path(self.radio.recordings_dir(), e["parts"]["data"]["name"])
        meta = sigmf.read_meta(path)                                  # strict: valid SigMF
        self.assertTrue(meta["global"]["openhamshack:complete"])
        # The engine's own playback device opens it, as the desktop's does.
        from ohscore.devices.filedev import FileDevice
        dev = FileDevice(path)
        self.assertGreater(dev.length_s, 0.4)

    def test_starting_and_deleting_need_control_and_listing_view(self):
        for path, body in (("/api/recordings/start", {"kind": "audio"}), ("/api/recordings/stop", {}),
                           ("/api/recordings/delete", {"id": "x"})):
            s, a = self.req("POST", path, body, level="view")
            self.assertEqual((s, a["code"], a["needs"]), (403, "level_too_low", "control"), path)
        self.assertEqual(self.req("GET", "/api/recordings", level="view")[0], 200)
        self.assertEqual(self.req("GET", "/api/recordings/status", level="view")[0], 200)

    def test_refusals(self):
        s, a = self.req("POST", "/api/recordings/start", {"kind": "video"}, level="control")
        self.assertEqual((s, a["code"]), (400, "bad_kind"))
        self.assertEqual(self.req("POST", "/api/recordings/start", {"kind": "audio"}, level="control")[0], 200)
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio"}, level="control")
        self.assertEqual((s, a["code"]), (409, "already_recording"))
        running = self.req("GET", "/api/recordings/status")[1]["active"][0]["id"]
        s, a = self.req("POST", "/api/recordings/delete", {"id": running}, level="control")
        self.assertEqual((s, a["code"]), (409, "recording_active"))
        for rid in ("../config.json", "nope"):
            s, _h, _b = self.raw("GET", f"/api/recordings/file?id={rid}")
            self.assertEqual(s, 404)
        self.req("POST", "/api/stop", level="control")
        # The radio stopping ends the audio recording too.
        self.assertTrue(self.wait(lambda: not self.req("GET", "/api/recordings/status")[1]["recording"]))
        self.assertEqual(self.req("GET", "/api/recordings/status")[1]["last"]["stopped"], "the radio stopped")
        s, a = self.req("POST", "/api/recordings/start", {"kind": "iq"}, level="control")
        self.assertEqual((s, a["code"]), (409, "not_running"))

    def test_below_the_free_space_floor_nothing_starts(self):
        self.srv.recordings.rec.store.disk_usage = lambda p: Usage(100 * GB, 99 * GB, GB)
        for kind in ("audio", "iq"):
            s, a = self.req("POST", "/api/recordings/start", {"kind": kind}, level="control")
            self.assertEqual((s, a["code"]), (507, "low_disk"), kind)
        self.assertFalse(self.radio.state()["recording"])

    def test_past_the_limit_the_oldest_goes(self):
        first = self.record("audio", seconds=0.5)
        self.srv.recordings.rec.store.limit_bytes = first["bytes"] + 1      # room for one
        second = self.record("audio", seconds=0.5)
        ids = [x["id"] for x in self.req("GET", "/api/recordings")[1]["recordings"]]
        self.assertEqual(ids, [second["id"]])

    def test_the_status_page_records_plays_and_lists_under_the_prefix(self):
        self.record("audio", seconds=0.3)
        s, h, body = self.raw("GET", "/", {"X-Forwarded-Prefix": "/shack-qo100nb"})
        page = body.decode()
        self.assertEqual(s, 200)
        self.assertIn("<base href='/shack-qo100nb/'>", page)
        self.assertIn("<audio controls preload=none src='api/recordings/file?id=", page)
        self.assertIn("data-start=iq", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        # A prefix that is not a plain path is not echoed into the page.
        s, h, body = self.raw("GET", "/", {"X-Forwarded-Prefix": "/x'><script>"})
        self.assertIn("<base href='/'>", body.decode())


class WithoutShackRec(Recordings):
    """A desktop build run with --server: its bundle has no shack_rec
    (packaging/shack_vendor.py), which until 17/10/2026 stopped the server
    at start-up (SharedLibraryMissing from ServerRecordings). Now the radio
    is served and recording is refused, saying why."""

    def setUp(self):
        missing = shacklibs.SharedLibraryMissing("shack_rec is not installed and not in /x/vendor")
        p = mock.patch.object(shacklibs, "rec", side_effect=missing)
        p.start()
        self.addCleanup(p.stop)
        with self.assertLogs("ohscore.server", "WARNING") as cm:
            super().setUp()
        self.assertIn("recordings are off: shack_rec is not installed", " ".join(cm.output))

    def test_the_radio_runs_and_recording_is_refused_with_the_reason(self):
        self.assertTrue(self.radio.state()["running"])
        why = "Recording is not available in this installation: shack_rec is not installed and not in /x/vendor"
        self.assertEqual(self.req("GET", "/api/status")[1]["recordings"],
                         {"kinds": [], "active": [], "unavailable": why})
        s, a = self.req("GET", "/api/recordings")
        self.assertEqual((s, a["recordings"], a["recording"], a["unavailable"]), (200, [], False, why))
        for path, body in (("/api/recordings/start", {"kind": "audio"}), ("/api/recordings/delete", {"id": "x"})):
            s, a = self.req("POST", path, body, level="control")
            self.assertEqual((s, a["code"], a["error"]), (503, "recordings_unavailable", why), path)
        s, a = self.req("POST", "/api/recordings/stop", {}, level="control")
        self.assertEqual((s, a["stopped"]), (200, []))
        self.assertEqual(self.raw("GET", "/api/recordings/file?id=x")[0], 503)
        s, _h, body = self.raw("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn(why, body.decode())
        self.assertNotIn("data-start", body.decode())


# The parent's tests all record; here there is nothing to record with.
for _name in [n for n in vars(Recordings) if n.startswith("test_")]:
    setattr(WithoutShackRec, _name, None)
