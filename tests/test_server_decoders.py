"""api/decoders over a real HTTP server (docs/SERVER-API.md "Decoders";
RADIO-SDR-PLAN §4.4): Radio's store form on its band simulator, faster
than real time, with a fixed RTTY session copying the simulated 20 m RTTY
station. Levels (view reads, control starts and stops), every error code,
recovery by `rev`, the pinned span, the session limit, the codecs and their
rescan, the `decoder` events on api/events, and decoders in api/status."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import tempfile
import time
import unittest

from ohscore import sdr
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio
import test_server  # its ServerTest's req and Streams' socket helpers, without collecting their tests here

RTTY_HZ = 14_091_750.0 + 1500.0          # seed 2's 20 m RTTY station (test_decoders.py)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class DecodersApi(test_server.ServerTest):
    broker = False
    ws = test_server.Streams.ws
    frame = staticmethod(test_server.Streams.frame)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = StreamAudio(realtime=False)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 2, "simHourUtc": 14.0,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 14_070_000.0, "mode": "usb",
               "decodersMax": 2}
        self.radio = Radio(cfg, persist=False, data_dir=self.tmp.name, audio=self.audio)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret="test-proxy-secret")
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def start(self, freq=RTTY_HZ, **body):
        return self.req("POST", "/api/decoders/sessions", {"decoder": "rtty", "freqHz": freq, **body},
                        level="control")

    def test_the_view_lists_decoders_codecs_limits_and_sessions(self):
        s, a = self.req("GET", "/api/decoders", level="view")
        self.assertEqual(s, 200, a)
        rtty = next(d for d in a["decoders"] if d["id"] == "rtty")
        self.assertEqual((rtty["engine"], rtty["panel"], rtty["fixed"]), ("shack_sdr", "text", True))
        self.assertEqual({c["id"] for c in a["codecs"]}, {"codec2", "faad2", "fdk-aac", "mbelib"})
        self.assertTrue(all(c["whyText"] for c in a["codecs"]))
        self.assertEqual(a["limits"], {"sessions": 2, "cpuMax": 0.25, "threads": 1})
        self.assertEqual(a["sessions"], [])
        st = self.req("GET", "/api/status", level="view")[1]["decoders"]
        self.assertEqual((st["available"], st["sessions"]), (True, 0))

    def test_view_reads_and_control_starts_and_stops(self):
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "rtty", "freqHz": RTTY_HZ}, level="view")
        self.assertEqual((s, a["code"], a["needs"]), (403, "level_too_low", "control"))
        s, sess = self.start()
        self.assertEqual(s, 201, sess)
        self.assertEqual((sess["decoder"], sess["freqHz"], sess["panel"]), ("rtty", RTTY_HZ, "text"))
        s, a = self.req("DELETE", f"/api/decoders/sessions/{sess['id']}", level="view")
        self.assertEqual((s, a["needs"]), (403, "control"))
        s, a = self.req("DELETE", f"/api/decoders/sessions/{sess['id']}", level="control")
        self.assertEqual((s, a), (200, {"stopped": True}))
        s, a = self.req("DELETE", f"/api/decoders/sessions/{sess['id']}", level="control")
        self.assertEqual((s, a["code"]), (404, "unknown_session"))

    def test_every_refusal_is_a_status_and_a_code(self):
        cases = [({"decoder": "nope", "freqHz": RTTY_HZ}, 404, "unknown_decoder"),
                 ({"decoder": "rtty", "freqHz": 7_050_000.0}, 409, "outside_span"),
                 ({"decoder": "rtty", "freqHz": RTTY_HZ, "params": {"baud": 46}}, 400, "bad_params"),
                 ({"decoder": "rtty", "freqHz": "fourteen"}, 400, "bad_params"),
                 ({"decoder": "ft8", "freqHz": RTTY_HZ}, 409, "decoder_unavailable")]
        for body, status, code in cases:
            with self.subTest(code=code, body=body):
                s, a = self.req("POST", "/api/decoders/sessions", body, level="control")
                self.assertEqual((s, a["code"]), (status, code), a)
                self.assertTrue(a["error"])
        self.assertEqual(self.start()[0], 201)
        self.assertEqual(self.start(RTTY_HZ + 2000.0)[0], 201)
        s, a = self.start(RTTY_HZ + 4000.0)
        self.assertEqual((s, a["code"]), (429, "too_many_sessions"))
        self.srv.stop_radio()
        s, a = self.start()
        self.assertEqual((s, a["code"]), (503, "not_running"))

    def test_results_and_recovery_by_rev(self):
        s, sess = self.start()
        sid = sess["id"]
        got = {}
        end = time.monotonic() + 60
        while time.monotonic() < end:
            self.radio.heartbeat()
            s, got = self.req("GET", f"/api/decoders/sessions/{sid}", level="view")
            self.assertEqual(s, 200, got)
            if "CQ TEST" in "".join(r.get("text", "") for r in got["results"]):
                break
            time.sleep(0.1)
        text = [r for r in got["results"] if r["type"] == "text"]
        self.assertIn("CQ TEST", "".join(r["text"] for r in text))
        mid = text[len(text) // 2]["rev"]
        s, later = self.req("GET", f"/api/decoders/sessions/{sid}?since={mid}", level="view")
        self.assertTrue(later["results"])
        self.assertTrue(all(r["rev"] > mid for r in later["results"]))
        self.assertEqual(self.req("GET", f"/api/decoders/sessions/{sid}?since=x", level="view")[0], 400)
        self.assertEqual(self.req("GET", "/api/decoders/sessions/ds_nope", level="view")[1]["code"], "unknown_session")

    def test_a_tune_out_of_the_span_is_refused_and_the_session_stays_in_it(self):
        # Radio pins its span for background sessions (SERVER-API "The
        # pinned span"; test_ham_span_pin): a session never goes outside.
        s, sess = self.start()
        s, a = self.req("POST", "/api/set", {"vfo": 7_050_000.0}, level="control")
        self.assertEqual((s, a["code"], [x["id"] for x in a["sessions"]]), (409, "span_pinned", [sess["id"]]))
        self.radio.heartbeat()
        self.assertNotEqual(self.req("GET", f"/api/decoders/sessions/{sess['id']}", level="view")[1]["state"],
                            "outside")

    def test_codecs_are_looked_for_again_on_request(self):
        self.assertEqual(self.req("POST", "/api/decoders/codecs/rescan", level="view")[0], 403)
        s, a = self.req("POST", "/api/decoders/codecs/rescan", level="control")
        self.assertEqual(s, 200)
        self.assertEqual(len(a["codecs"]), 4)

    def test_decoder_events_are_sent_when_asked_for(self):
        s, sess = self.start()
        sock, f = self.ws("/api/events?kinds=decoder")
        try:
            json.loads(self.frame(f)[1])                        # hello
            msgs = []
            end = time.monotonic() + 60
            while time.monotonic() < end and "CQ TEST" not in "".join(m.get("text", "") for m in msgs):
                self.radio.heartbeat()
                m = json.loads(self.frame(f)[1])
                self.assertEqual(m["kind"], "decoder")
                msgs.append(m)
        finally:
            sock.close()
        self.assertTrue(all(m["session"] == sess["id"] for m in msgs))
        self.assertIn("CQ TEST", "".join(m.get("text", "") for m in msgs))


if __name__ == "__main__":
    unittest.main()
