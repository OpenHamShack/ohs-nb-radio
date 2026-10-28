"""api/decoders over a real HTTP server (docs/SERVER-API.md "Decoders";
RADIO-SDR-PLAN §4.4): Radio's store form on its band simulator, faster
than real time, with a fixed RTTY session copying the simulated 20 m RTTY
station. Levels (view reads, control starts and stops), every error code,
recovery by `rev`, the pinned span, the session limit, the codecs and their
rescan, the `decoder` events on api/events, and decoders in api/status.
Then milestone 2's: a PSK session's several channels (skipped while the
Rust PSK decoder is switched off, ohscore/sdr.py; then psk is not offered),
and an SSTV session's picture - its rows on api/events as base64, the PNG on
api/decoders/files. And `listen`: a DMR session on the simulated repeater
put on api/audio/rx in place of the demodulator, its levels and refusals."""
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


def _psk_air(text, centre, variant="psk31"):
    import numpy as np
    from ohscore.devices import simsignals as sg
    from ohscore.modes import psk
    a = psk.Encoder().render(text=text, variant=variant, center=centre)
    return sg.analytic(np.concatenate([np.zeros(12_000, np.float32), a, np.zeros(24_000, np.float32)]))


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class PskAndSstvApi(test_server.ServerTest):
    """PSK and SSTV sessions as a client drives them (SERVER-API "Decoders":
    psk's channels, sstv's rows and files)."""
    broker = False
    ws = test_server.Streams.ws
    frame = staticmethod(test_server.Streams.frame)
    DIAL = 14_230_000.0        # USB, inside the span around 14.070 MHz
    LEVEL = -56.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audio = StreamAudio(realtime=False)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 2, "simHourUtc": 14.0,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 14_070_000.0, "mode": "usb"}
        self.radio = Radio(cfg, persist=False, data_dir=self.tmp.name, audio=self.audio)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret="test-proxy-secret")
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def results(self, sid):
        s, a = self.req("GET", f"/api/decoders/sessions/{sid}", level="view")
        self.assertEqual(s, 200, a)
        return a

    def until(self, cond, timeout=90.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.radio.heartbeat()
            if cond():
                return True
            time.sleep(0.05)
        return False

    @unittest.skipUnless(sdr.PSK_ON_SHACK_SDR, "the Rust PSK decoder switched off (ohscore/sdr.py PSK_ON_SHACK_SDR)")
    def test_a_psk_session_copies_each_of_its_channels(self):
        self.radio.dev.add_station("a", self.DIAL, _psk_air("ALPHA DE G4AAA G4AAA ", 1000.0), self.LEVEL)
        self.radio.dev.add_station("b", self.DIAL, _psk_air("BRAVO DE M0BBB M0BBB ", 1900.0), self.LEVEL)
        s, sess = self.req("POST", "/api/decoders/sessions",
                           {"decoder": "psk", "freqHz": self.DIAL + 1000.0,
                            "params": {"baud": 31.25, "channels": "0,900"}}, level="control")
        self.assertEqual(s, 201, sess)
        self.assertEqual(sess["params"], {"baud": 31.25, "channels": "0,900"})

        def per_channel():
            out = {}
            for r in self.results(sess["id"])["results"]:
                if r["type"] == "text":
                    k = 900 if r["offsetHz"] > 450 else 0
                    out[k] = out.get(k, "") + r["text"]
            return out
        self.until(lambda: "G4AAA G4AAA" in per_channel().get(0, "") and "M0BBB M0BBB" in per_channel().get(900, ""))
        got = per_channel()
        self.assertIn("ALPHA DE G4AAA G4AAA", got.get(0, ""), got)
        self.assertIn("BRAVO DE M0BBB M0BBB", got.get(900, ""), got)
        meta = self.results(sess["id"])["meta"]
        self.assertEqual([c["offsetHz"] for c in meta["channels"]], [0.0, 900.0])
        # A waterfall click adds a third, live (POST .../{id} params).
        s, a = self.req("POST", f"/api/decoders/sessions/{sess['id']}", {"params": {"channels": "0,900,1500"}},
                        level="control")
        self.assertEqual((s, a["params"]["channels"]), (200, "0,900,1500"))
        s, a = self.req("POST", f"/api/decoders/sessions/{sess['id']}",
                        {"params": {"channels": ",".join(str(10 * k) for k in range(40))}}, level="control")
        self.assertEqual((s, a["code"]), (400, "bad_params"))

    def test_psk_is_not_offered_while_its_library_fix_is_parked(self):
        if sdr.PSK_ON_SHACK_SDR:
            self.skipTest("the Rust PSK decoder is switched on")
        s, a = self.req("GET", "/api/decoders", level="view")
        self.assertNotIn("psk", [d["id"] for d in a["decoders"]])
        s, a = self.req("POST", "/api/decoders/sessions", {"decoder": "psk", "freqHz": self.DIAL + 1000.0},
                        level="control")
        self.assertEqual((s, a["code"]), (404, "unknown_decoder"))
        s, a = self.req("POST", "/api/set", {"pskChannels": [1500]}, level="control")
        self.assertEqual(s, 400, a)

    def test_an_sstv_session_sends_rows_and_its_picture_is_a_file(self):
        import base64
        import numpy as np
        from shack_sdr import sstv
        from ohscore.devices import simsignals as sg
        audio, _sent = sstv.testsig("robot36", rate=12_000.0, lead_s=1.0, tail_s=2.0)
        self.radio.dev.add_station("sstv", self.DIAL,
                                   sg.analytic(np.concatenate([audio, np.zeros(len(audio), np.float32)])),
                                   self.LEVEL)
        s, files = self.req("GET", "/api/decoders/files", level="view")
        self.assertEqual((s, files), (200, {"files": []}))
        s, sess = self.req("POST", "/api/decoders/sessions",
                           {"decoder": "sstv", "freqHz": self.DIAL + 1900.0}, level="control")
        self.assertEqual((s, sess["panel"]), (201, "image"))
        sock, f = self.ws("/api/events?kinds=decoder")
        msgs = []
        try:
            json.loads(self.frame(f)[1])                        # hello
            end = time.monotonic() + 120
            while time.monotonic() < end and not any(m.get("event") == "done" for m in msgs):
                self.radio.heartbeat()
                msgs.append(json.loads(self.frame(f)[1]))
        finally:
            sock.close()
        mine = [m for m in msgs if m["session"] == sess["id"] and m["type"] == "image"]
        start = next(m for m in mine if m["event"] == "start")
        self.assertEqual((start["width"], start["height"]), (320, 240))
        rows = [m for m in mine if m["event"] == "lines"]
        self.assertTrue(rows)
        self.assertEqual(len(base64.b64decode(rows[0]["rgb"])) % (320 * 3), 0)
        done = next(m for m in mine if m["event"] == "done")
        self.assertNotIn("path", done)
        # The picture, on api/decoders/files, view level.
        s, files = self.req("GET", "/api/decoders/files", level="view")
        self.assertEqual(s, 200)
        self.assertEqual([x["name"] for x in files["files"]], [done["file"]])
        self.assertEqual(set(files["files"][0]), {"name", "session", "decoder", "t", "size"})
        self.assertEqual((files["files"][0]["session"], files["files"][0]["decoder"]), (sess["id"], "sstv"))
        s, png = self.req("GET", f"/api/decoders/files/{done['file']}", level="view")
        self.assertEqual(s, 200)
        self.assertEqual(sstv.png_rgb(png).shape, (240, 320, 3))
        self.assertEqual(len(png), files["files"][0]["size"])
        for bad in ("nothing.png", "..%2F..%2Fetc%2Fpasswd", ".hidden.png"):
            with self.subTest(bad=bad):
                s, a = self.req("GET", f"/api/decoders/files/{bad}", level="view")
                self.assertEqual((s, a["code"]), (404, "no_file"))
        # Still there to look at once the radio has stopped.
        self.radio.stop()
        s, files = self.req("GET", "/api/decoders/files", level="view")
        self.assertEqual([x["name"] for x in files["files"]], [done["file"]])
        s, png2 = self.req("GET", f"/api/decoders/files/{done['file']}?download=1", level="view")
        self.assertEqual((s, png2), (200, png))

    @unittest.skipUnless(sdr.load() is not None and any(e["id"] == "dmr" for e in sdr.load().catalogue()),
                         "no shack_sdr with DMR for this machine")
    def test_listen_puts_a_session_on_the_receive_audio(self):
        from ohsradio.devices import simdmr
        self.radio.set(vfo=simdmr.FREQ, mode="fm")
        s, dmr = self.req("POST", "/api/decoders/sessions", {"decoder": "dmr", "freqHz": simdmr.FREQ},
                          level="control")
        self.assertEqual(s, 201, dmr)
        self.assertEqual((dmr["panel"], dmr["listening"]), ("slots", False))
        path = f"/api/decoders/sessions/{dmr['id']}/listen"
        s, a = self.req("POST", path, {"listen": True}, level="view")
        self.assertEqual((s, a["needs"]), (403, "control"))
        s, a = self.req("POST", path, {"listen": "yes"}, level="control")
        self.assertEqual((s, a["code"]), (400, "bad_params"))
        s, a = self.req("POST", "/api/decoders/sessions/ds_none/listen", {"listen": True}, level="control")
        self.assertEqual((s, a["code"]), (404, "unknown_session"))
        s, rtty = self.req("POST", "/api/decoders/sessions", {"decoder": "rtty", "freqHz": simdmr.FREQ + 50_000},
                           level="control")
        s, a = self.req("POST", f"/api/decoders/sessions/{rtty['id']}/listen", {"listen": True}, level="control")
        self.assertEqual((s, a["code"]), (409, "no_audio"))
        s, a = self.req("POST", path, {"listen": True}, level="control")
        self.assertEqual((s, a["listening"]), (200, True))
        st = self.req("GET", "/api/status", level="view")[1]["decoders"]
        self.assertEqual(st["listening"], dmr["id"])
        s, sessions = self.req("GET", "/api/decoders", level="view")
        self.assertEqual({x["id"]: x["listening"] for x in sessions["sessions"]},
                         {dmr["id"]: True, rtty["id"]: False})
        s, a = self.req("POST", path, {"listen": False}, level="control")
        self.assertEqual((s, a["listening"]), (200, False))
        self.assertIsNone(self.req("GET", "/api/status", level="view")[1]["decoders"]["listening"])


if __name__ == "__main__":
    unittest.main()
