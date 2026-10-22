"""Radio's CW skimmer (ohsradio/cwskim.py, ohs-libs shack_cw.skim): every CW
signal in the dial's band's CW segment decoded at once, on the band
simulator. Off by default; its output only on the cwskim/cwspot feeds and
GET api/cwskim, never on `events`; it follows the dial's band, never
retunes, says when the segment is outside the receiver's span; a worker
that dies leaves receive running and comes back; and nothing it runs can
key. The worker is a thread here (Radio.CWSKIM_MODE) except where a test
says otherwise: the child process is shack_cw.skim.runner's own tests'."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import ham_helpers
from ohscore import shacklibs
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio, USABLE
from test_server import SECRET, FakeBroker

shacklibs.cw()
import shack_cw.skim.runner as skim_runner  # noqa: E402  after shacklibs puts the vendored wheel on the path

ROOT = Path(__file__).resolve().parent.parent


def radio(**over):
    r = ham_helpers.make_radio(**{"vfo": 14_025_000.0, "mode": "cw", **over})
    r.CWSKIM_MODE = "thread"
    return r


def wait(r, cond, secs=60.0, feeds=()):
    got = {f.kind: [] for f in feeds}
    end = time.monotonic() + secs
    while time.monotonic() < end:
        part = ham_helpers.pump(r, 0.2, feeds=feeds)
        for k, v in part.items():
            got[k] += v
        if cond(got):
            return got
    cw = r.cwskim
    raise AssertionError(f"not within {secs} s: {r.state().get('cwSkimState')} {r.state().get('cwSkimWhy')} "
                         f"(span {r.wide_span()}, vfo {r.st['vfo']}, worker {cw.runner.state if cw else None})")


class Off(unittest.TestCase):
    def test_off_by_default_and_nothing_runs(self):
        r = radio()
        self.addCleanup(ham_helpers.close, r)
        spec = r.STATE.spec["cwSkim"]
        self.assertIs(r.st["cwSkim"], False)
        self.assertFalse(spec.get("auth"))
        sk = r.subscribe("cwskim")
        r.start()
        ham_helpers.pump(r, 3.0)
        self.assertIsNone(r.cwskim)
        self.assertEqual([i for i in sk.drain() if i.get("state") != "off"], [])
        v = r.cwskim_view()
        self.assertEqual((v["state"], v["channels"], v["spots"] if "spots" in v else []), ("off", [], []))
        self.assertEqual(r.state()["cwSkimState"], "off")

    def test_settings_are_control_keys_within_limits(self):
        r = radio()
        self.addCleanup(ham_helpers.close, r)
        self.assertEqual(r.set(cwSkimMax=256, cwSkimSquelch=10.0), {"cwSkimMax": 256, "cwSkimSquelch": 10.0})
        with self.assertRaises(ValueError):
            r.set(cwSkimMax=257)
        with self.assertRaises(ValueError):
            r.set(cwSkimSquelch=2.0)


class Skimming(unittest.TestCase):
    def setUp(self):
        self.r = radio(cwSkim=True)
        self.addCleanup(ham_helpers.close, self.r)
        self.feeds = [self.r.subscribe(k) for k in ("cwskim", "cwspot", "events")]
        self.r.start()

    def test_the_segment_is_decoded_and_spotted(self):
        got = wait(self.r, lambda g: any(x["spot"]["status"] == "valid" for x in g["cwspot"]), 90, self.feeds)
        item = got["cwskim"][-1]
        self.assertEqual(item["state"], "running")
        self.assertEqual((item["band"], item["segment"]["lo"], item["segment"]["hi"]), ("20m", 14_000_000.0,
                                                                                     14_070_000.0))
        self.assertEqual(item["segment"]["plan"], "rsgb-2026")
        self.assertTrue(item["channels"])
        ch = item["channels"][0]
        self.assertTrue({"id", "f", "dial", "wpm", "snr", "text", "first", "active", "decoding"} <= set(ch))
        self.assertAlmostEqual(ch["dial"], ch["f"] - self.r.st["cwPitch"], delta=1.0)
        spot = next(x["spot"] for x in got["cwspot"] if x["spot"]["status"] == "valid")
        self.assertTrue({"id", "call", "f", "dial", "mode", "wpm", "snr", "kind", "status", "hits", "first",
                         "last", "band", "channel", "country", "dxcc", "continent"} <= set(spot))
        self.assertEqual((spot["mode"], spot["band"]), ("cw", "20m"))
        self.assertIsNotNone(spot["country"])
        revs = [x["rev"] for x in got["cwspot"]]
        self.assertEqual(revs, list(range(1, len(revs) + 1)))
        # Never on events: a client's CW strip shows only the dial's decoder.
        self.assertFalse([e for e in got["events"] if "channels" in e or "spot" in e or "spotsRev" in e])
        st = self.r.state()
        self.assertEqual(st["cwSkimState"], "running")
        self.assertGreater(st["cwSkimChannels"], 0)
        v = self.r.cwskim_view()
        self.assertIn(spot["call"], [s["call"] for s in v["spots"]])
        self.assertEqual(v["spotsRev"], self.r.cwskim.rev)

    def test_it_follows_the_dials_band_and_never_retunes(self):
        wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["band"] == "20m", 30, self.feeds)
        self.r.set(vfo=7_025_000.0)
        got = wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["band"] == "40m", 30, self.feeds)
        seg = got["cwskim"][-1]["segment"]
        self.assertEqual((seg["lo"], seg["hi"]), (7_000_000.0, 7_040_000.0))
        # 40 m's segment comes at another rate (60 kS/s here): still skimmed.
        wait(self.r, lambda g: self.r.state()["cwSkimChannels"] > 0 and self.r.state()["cwSkimState"] == "running",
             30, self.feeds)
        self.assertEqual(self.r.st["vfo"], 7_025_000.0)

    def test_outside_and_partial(self):
        # 10 m is wider than the span: the receiver follows the dial
        # (ohsradio.radio.plan_centre), and the skimmer never moves it back.
        self.r.set(vfo=29_600_000.0, mode="usb")
        got = wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "outside", 30, self.feeds)
        item = got["cwskim"][-1]
        self.assertEqual(item["channels"], [])
        self.assertIn("28.000-28.070", item["why"])
        self.assertEqual(self.r.st["vfo"], 29_600_000.0)
        # A dial that puts the span's lower edge inside the segment.
        fs = self.r.geo.fs
        centre = 28_040_000.0 + USABLE * fs / 2
        self.r.set(vfo=centre + fs / 8)
        got = wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "partial", 30, self.feeds)
        cover = got["cwskim"][-1]["cover"]
        self.assertGreater(cover["lo"], 28_000_000.0)
        self.assertEqual(cover["hi"], 28_070_000.0)

    def test_a_worker_that_dies_leaves_receive_running_and_comes_back(self):
        old = skim_runner.BACKOFF
        skim_runner.BACKOFF = (0.5,)
        self.addCleanup(setattr, skim_runner, "BACKOFF", old)
        wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "running", 30, self.feeds)
        self.r.cwskim.runner.crash_for_test()
        wait(self.r, lambda g: self.r.state()["cwSkimState"] == "error", 30, self.feeds)
        self.assertTrue(self.r.state()["cwSkimWhy"])
        before = self.r.rx_samples
        wait(self.r, lambda g: self.r.state()["cwSkimState"] == "running", 30, self.feeds)
        self.assertGreater(self.r.rx_samples, before)
        self.assertTrue(self.r.running)
        self.assertEqual(self.r.cwskim.runner.restarts, 1)

    def test_a_radio_restart_takes_it_down_and_back(self):
        # A lost broker claim (a platform update) stops the radio and the
        # reclaim starts it again (GUIDE §5): the skimmer holds no device of
        # its own, so it goes with the radio and comes back with it.
        wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "running", 30, self.feeds)
        self.r.stop()
        self.assertIsNone(self.r.cwskim)
        self.assertEqual(self.r.state()["cwSkimState"], "off")
        self.r.start()
        wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "running", 30, self.feeds)
        self.assertIs(self.r.st["cwSkim"], True)

    def test_switched_off_it_stops_and_says_so(self):
        wait(self.r, lambda g: g["cwskim"], 30, self.feeds)
        self.r.set(cwSkim=False)
        got = wait(self.r, lambda g: g["cwskim"] and g["cwskim"][-1]["state"] == "off", 30, self.feeds)
        self.assertEqual(got["cwskim"][-1]["channels"], [])
        self.assertIsNone(self.r.cwskim)
        self.assertEqual(self.r.state()["cwSkimState"], "off")


class OverTheApi(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "callsign": "GM4BRI", "licenceClass": "full", "vfo": 14_025_000.0, "mode": "cw"}
        self.audio = StreamAudio(realtime=False)
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio)
        self.radio.CWSKIM_MODE = "thread"
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET,
                          broker=shack.BrokerClient(FakeBroker()))
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="view"):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
             "X-OpenHamShack-Level": level, "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        res = c.getresponse()
        out = res.status, json.loads(res.read())
        c.close()
        return out

    def test_api_cwskim_at_view_level_and_switched_on_at_control(self):
        s, v = self.req("GET", "/api/cwskim")
        self.assertEqual((s, v["state"], v["spots"]), (200, "off", []))
        s, _a = self.req("POST", "/api/set", {"cwSkim": True}, level="view")
        self.assertEqual(s, 403)
        s, a = self.req("POST", "/api/set", {"cwSkim": True}, level="control")
        self.assertEqual(s, 200, a)
        end = time.monotonic() + 90
        while time.monotonic() < end:
            self.radio.heartbeat()
            s, v = self.req("GET", "/api/cwskim")
            if v["spots"]:
                break
            time.sleep(0.2)
        self.assertEqual(v["state"], "running")
        self.assertTrue(v["spots"] and v["channels"])
        self.assertEqual(v["segment"]["lo"], 14_000_000.0)
        self.assertNotIn("cwskim", ham_server_default_kinds())


def ham_server_default_kinds():
    from ohscore.server.app import FEED_KINDS_DEFAULT
    return FEED_KINDS_DEFAULT


class NothingThatCanKey(unittest.TestCase):
    def test_the_workers_imports(self):
        # What the skimmer's worker process loads: the runner, and the
        # country lookup it is handed by name. A clean interpreter imports
        # them and lists what came with them: no app, no engine, no rig, no
        # device, no sound.
        code = ("import sys; sys.path.insert(0, %r); from ohscore import shacklibs; shacklibs.cw(); "
                "import shack_cw.skim.runner as r; f = r._factory(('ohscore.dxcc:skim_lookup', [None])); "
                "assert f('DL1ABC')['country'] == 'Fed. Rep. of Germany', f('DL1ABC'); "
                "print(' '.join(sorted(sys.modules)))" % str(ROOT))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        mods = set(out.stdout.split())
        for bad in ("ohsradio", "ohsnb", "ohscore.engine", "ohscore.rig", "ohscore.devices", "ohscore.audio",
                    "ohscore.txguard", "ohscore.keyer", "sounddevice", "serial", "SoapySDR", "iio", "PyQt6"):
            self.assertFalse([m for m in mods if m == bad or m.startswith(bad + ".")], bad)


if __name__ == "__main__":
    unittest.main()
