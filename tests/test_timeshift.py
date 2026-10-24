"""The timeshift (ohscore/server/timeshift.py; docs/SERVER-API.md
"Timeshift"): a broadcast station's last minutes kept on disk, compressed,
to listen behind live and to record from the past.

- **Here, on its own,** fed known audio through the same tap a recording
  uses, with a stand-in radio whose station and settings a test sets: the
  codec gives back exactly what it was given; the buffer keeps its length
  and never more bytes than raw PCM, on disk under its folder; another
  station or none clears it; what is read back from any point is the
  audio that was played there, across chunks on disk and what is not
  written yet; the item start follows DL Plus; a recording fed from the
  past gets the past and then the live audio with nothing lost or
  repeated at the join; and the audio thread's cost is measured.
- **End to end** on the simulator over HTTP: api/audio/rx?behind= is the
  wide FM station's own audio from that long ago; recordings start from
  the past (fromSecondsAgo, the default lead, lastMinutes, fromItemStart)
  with exactly the audio played then; DAB changing station clears it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from collections import namedtuple
from pathlib import Path

import numpy as np

from ohscore import sdr
from ohscore.server import shack, timeshift
from ohscore.server.audio import StreamAudio
from ohscore.server.timeshift import Gone, Timeshift

RATE = 48_000
Usage = namedtuple("Usage", "total used free")


class FakeRadio:
    """What the timeshift reads of a radio: its settings, whether it runs,
    and the station."""

    def __init__(self):
        self.st = {"timeshiftMinutes": 1, "running": True}
        self.station = {"kind": "wfm", "mode": "WFM", "label": "SIM ONE", "freqHz": 88_600_000.0}

    def state(self):
        return dict(self.st)

    def broadcast_station(self):
        return dict(self.station) if self.station else None


def noise(n, seed):
    """Stereo audio no two windows of which are alike, so a position in
    it is found exactly."""
    return np.random.default_rng(seed).integers(-2000, 2000, (n, 2)).astype(np.int16)


class Codec(unittest.TestCase):
    def test_it_gives_back_exactly_what_it_was_given(self):
        rng = np.random.default_rng(3)
        t = np.arange(96_000) / RATE
        cases = {
            "tones": (np.stack([np.sin(2e3 * np.pi * t), np.sin(3e3 * np.pi * t)], 1) * 8000).astype(np.int16),
            "full-scale noise": rng.integers(-32768, 32768, (96_000, 2)).astype(np.int16),
            "the extremes": np.array([[32767, -32768], [-32768, 32767]] * 500, np.int16),
            "mono in stereo": np.repeat(rng.integers(-9000, 9000, (96_000, 1)), 2, axis=1).astype(np.int16),
            "one sample": np.array([[5, -5]], np.int16),
        }
        for name, pcm in cases.items():
            np.testing.assert_array_equal(timeshift.decode(timeshift.encode(pcm), len(pcm)), pcm, name)
        # A mono station in stereo costs little more than mono: left minus right is nothing.
        mono = cases["mono in stereo"]
        self.assertLess(len(timeshift.encode(mono)), 0.7 * mono.nbytes)


class Buffer(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.radio = FakeRadio()
        self.audio = StreamAudio(realtime=False)
        self.audio.out_rate = RATE
        self.folder = self.tmp / "timeshift"
        self.folder.mkdir()
        (self.folder / "1-0.ohsts").write_bytes(b"left over from before a restart")
        self.ts = Timeshift(self.radio, self.audio, self.folder,
                            disk_usage=lambda p: Usage(100e9, 1e9, 99e9))
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.ts.run, args=(self.stop,), daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.stop.set)
        self.played = np.zeros((0, 2), np.int16)

    def until(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def play(self, seconds, seed=1, block=4800):
        """Play `seconds` of known audio, as the engine does: block by block,
        never so far ahead of the writer that it starts again (the engine
        plays in real time; QUEUE_S is seconds of it)."""
        pcm = noise(int(seconds * RATE), seed)
        for i in range(0, len(pcm), block):
            self.until(lambda: self.ts.pending_n < 1.5 * timeshift.CHUNK_S * RATE)
            self.audio.play(pcm[i:i + block].astype(np.float32) / 32767.0)
        # As the tap gets it: float back to int16 (StreamAudio.play).
        self.played = np.concatenate([self.played, (np.clip(pcm / 32767.0, -1, 1) * 32767.0).astype("<i2")])

    def buffering(self):
        """Until the buffer holds the stand-in's station now."""
        self.assertTrue(self.until(lambda: self.ts.buffering
                                   and self.ts.key == timeshift.station_key(self.radio.station)))

    def test_it_starts_empty_and_keeps_only_its_length(self):
        self.assertEqual(list(self.folder.iterdir()), [])            # nothing survives a restart
        self.radio.st["timeshiftMinutes"] = 0.1                        # 6 s, for the test
        self.buffering()
        self.assertTrue(self.until(lambda: self.ts.status()["capS"] == 6))
        self.play(20)
        self.assertTrue(self.until(lambda: self.ts.pending_n < timeshift.CHUNK_S * RATE))
        st = self.ts.status()
        self.assertTrue(st["available"])
        self.assertGreaterEqual(st["lengthS"], 6.0)
        self.assertLessEqual(st["lengthS"], 6.0 + 2 * timeshift.CHUNK_S)
        self.assertEqual((st["capS"], st["station"]["label"]), (6, "SIM ONE"))
        files = list(self.folder.glob("*.ohsts"))
        self.assertLessEqual(len(files), 6 / timeshift.CHUNK_S + 2)
        # What is kept is the newest: the last sample read back is the last played.
        gen, index, ago = self.ts.position(1.0)
        self.assertAlmostEqual(ago, 1.0)
        np.testing.assert_array_equal(self.ts.read(gen, index, RATE), self.played[-RATE:])

    def test_never_more_bytes_than_raw_audio(self):
        # Full-scale noise is the one thing the codec makes bigger than raw.
        self.radio.st["timeshiftMinutes"] = 0.1
        self.buffering()
        self.assertTrue(self.until(lambda: self.ts.status()["capS"] == 6))
        pcm = np.random.default_rng(9).integers(-32768, 32768, (12 * RATE, 2)).astype(np.int16)
        for i in range(0, len(pcm), 4800):
            self.until(lambda: self.ts.pending_n < 1.5 * timeshift.CHUNK_S * RATE)
            self.audio.play(pcm[i:i + 4800].astype(np.float32) / 32767.0)
        self.assertTrue(self.until(lambda: self.ts.pending_n < timeshift.CHUNK_S * RATE))
        held = sum(p.stat().st_size for p in self.folder.glob("*.ohsts"))
        self.assertLessEqual(held, 0.1 * 60 * RATE * 4)
        self.assertGreater(self.ts.status()["lengthS"], 0)

    def test_read_back_from_anywhere_is_what_was_played_there(self):
        self.buffering()
        self.play(7.3)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 7.29))
        gen, index, ago = self.ts.position(7.0)
        got = []
        while index < self.ts.total:
            pcm = self.ts.read(gen, index, 10_000)          # across chunks, the one encoding, and pending
            got.append(pcm)
            index += len(pcm)
        got = np.concatenate(got)
        np.testing.assert_array_equal(got, self.played[-len(got):])
        self.assertEqual(len(got), 7 * RATE)
        # More than is kept is what is kept, and the position says so.
        _g, _i, ago = self.ts.position(3600)
        self.assertAlmostEqual(ago, 7.3, places=2)

    def test_another_station_or_none_clears_it(self):
        self.buffering()
        self.play(5)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 4.9))
        gen, index, _ago = self.ts.position(4)
        self.radio.station = {"kind": "wfm", "mode": "WFM", "label": "SIMNEWS", "freqHz": 93_500_000.0}
        self.assertTrue(self.until(lambda: self.ts.gen > gen + 1 and self.ts.buffering))
        self.assertEqual(self.ts.status()["lengthS"], 0.0)
        self.assertTrue(self.until(lambda: not list(self.folder.glob("*.ohsts"))))
        self.assertEqual(self.ts.status()["station"]["label"], "SIMNEWS")
        with self.assertRaises(Gone):
            self.ts.read(gen, index, 100)
        # The name arriving later is the same station: kept.
        self.play(3, seed=2)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 2.9))
        gen = self.ts.gen
        self.radio.station = dict(self.radio.station, rt="The news, read by nobody")
        time.sleep(3 * timeshift.POLL_S)
        self.assertEqual(self.ts.gen, gen)
        # Off, and stopped: cleared and untapped.
        for change in ({"running": False}, {"timeshiftMinutes": 0}):
            self.radio.st.update(change)
            self.assertTrue(self.until(lambda: not self.ts.buffering and self.ts.untap is None))
            self.assertFalse(self.ts.status()["available"])
            self.radio.st.update({"running": True, "timeshiftMinutes": 1})
            self.buffering()
        self.radio.station = None
        self.assertTrue(self.until(lambda: not self.ts.buffering and self.ts.untap is None))

    def test_a_writer_left_behind_starts_again_rather_than_keep_a_gap(self):
        self.buffering()
        gen = self.ts.gen
        stall = threading.Event()

        def stalled_disk(p):                 # the writer stuck on a slow disk
            stall.wait(10)
            return Usage(100e9, 1e9, 99e9)
        self.ts.disk_usage = stalled_disk
        pcm = noise(int((timeshift.QUEUE_S + timeshift.CHUNK_S + 1) * RATE), 7)
        for i in range(0, len(pcm), 4800):
            self.audio.play(pcm[i:i + 4800].astype(np.float32) / 32767.0)
        self.assertTrue(self.ts.overflow)
        stall.set()
        self.assertTrue(self.until(lambda: self.ts.gen > gen and not self.ts.overflow and self.ts.buffering))
        self.assertEqual(self.ts.status()["lengthS"], 0.0)

    def test_low_disk_stops_it_and_says_why(self):
        self.ts.disk_usage = lambda p: Usage(100e9, 99e9, 1e9)
        self.buffering()
        self.play(3)
        self.assertTrue(self.until(lambda: "why" in self.ts.status()))
        st = self.ts.status()
        self.assertFalse(st["available"])
        self.assertIn("not enough free disk space", st["why"])
        self.assertTrue(self.until(lambda: not list(self.folder.glob("*.ohsts"))))

    def test_the_item_start_follows_dl_plus(self):
        self.radio.station = {"kind": "dab", "mode": "DAB", "label": "Shack MP2 Tone", "block": "11D",
                              "sid": "C221", "freqHz": 222_064_000.0, "title": "First", "artist": "A"}
        self.buffering()
        self.play(2)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 1.9))
        # On since before the buffer began: its start is not here.
        _gen, index, ago, why = self.ts.item_start()
        self.assertEqual(index, self.ts.base)
        self.assertIn("began before the timeshift buffer", why)
        # Status offers it from as far back as is kept, and says so.
        st = self.ts.status()
        self.assertEqual((st["itemStartUtc"], st["itemStartInBuffer"]), (st["startUtc"], False))
        self.radio.station = dict(self.radio.station, title="Second", artist="B")
        self.assertTrue(self.until(lambda: (self.ts.item or {}).get("title") == "Second"))
        at = self.ts.item["index"]
        self.play(3, seed=4)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 4.9))
        _gen, index, ago, why = self.ts.item_start()
        self.assertEqual((index, why), (at, ""))
        self.assertAlmostEqual(ago, 3.0, delta=0.01)
        self.assertIsNotNone(self.ts.status()["itemStartUtc"])
        self.assertTrue(self.ts.status()["itemStartInBuffer"])
        self.radio.station = dict(self.radio.station, title=None, artist=None)
        self.assertTrue(self.until(lambda: self.ts.item is None))
        self.assertIn("no item", self.ts.item_start()[3])

    def test_the_first_item_heard_after_tuning_in_began_before(self):
        # DL Plus comes a few seconds after the sound starts.
        self.radio.station = {"kind": "dab", "mode": "DAB", "label": "Shack MP2 Tone", "block": "11D",
                              "sid": "C221", "freqHz": 222_064_000.0, "title": None, "artist": None}
        self.buffering()
        self.play(1)
        self.radio.station = dict(self.radio.station, title="First", artist="A")
        self.assertTrue(self.until(lambda: self.ts.item is not None))
        self.assertIsNone(self.ts.item["index"])
        self.assertIn("began before the timeshift buffer", self.ts.item_start()[3])

    def test_a_follower_gets_the_past_then_live_with_nothing_lost_at_the_join(self):
        self.buffering()
        self.play(4)
        self.assertTrue(self.until(lambda: self.ts.status()["lengthS"] >= 3.9))
        got, lock = [], threading.Lock()

        def push(pcm):
            with lock:
                got.append(np.frombuffer(pcm, "<i2").reshape(-1, 2).copy())
            return True
        gen, index, _ago = self.ts.position(3.0)
        start = len(self.played) - 3 * RATE
        f = self.ts.follow(gen, index, push)
        self.play(2, seed=5)                 # live, while the past is still being sent
        self.assertTrue(self.until(lambda: f.direct))
        self.play(1, seed=6)
        with lock:
            out = np.concatenate(got)
        np.testing.assert_array_equal(out, self.played[start:])
        self.ts.unfollow(f)
        # Until now only: the past, then on_end.
        ended = []
        gen, index, _ago = self.ts.position(2.0)
        got.clear()
        self.ts.follow(gen, index, push, until_now=True, on_end=ended.append)
        self.assertTrue(self.until(lambda: ended))
        self.assertEqual(ended, [""])
        np.testing.assert_array_equal(np.concatenate(got), self.played[-2 * RATE:])

    def test_the_audio_thread_pays_almost_nothing(self):
        self.radio.st["timeshiftMinutes"] = 0.2
        self.buffering()
        self.play(30)
        cost = self.ts.tap_cost()
        # Measured on shack, 24/10/2026: about 40 us per second of audio
        # (0.004 % of the audio thread). The bound is 1 %, for a loaded VM.
        print(f"\ntimeshift tap: {cost * 1e6:.1f} us per second of audio")
        self.assertLess(cost, 0.01)


SECRET = "s" * 32
CENTRE, FM = 222_064_000.0, 88_600_000.0


def flac_pcm(path):
    """A FLAC file's samples, (n, 2) int16, through ffmpeg (the app has an
    encoder only)."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, "<i2").reshape(-1, 2)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class EndToEnd(unittest.TestCase):
    """On the simulator over HTTP. Every block the radio plays is also
    captured here, through the same kind of tap, so the audio a stream or
    a recording gives back is found in what was played, to the sample."""

    def setUp(self):
        from ohscore.server.app import Server
        from ohsradio import server as ham_server
        from ohsradio.devices import simdab
        from ohsradio.devices.simfm import FmBand, FmStation
        from ohsradio.radio import Radio
        from listen_helpers import ListeningSim
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": FM, "mode": "wfm"}
        self.audio = StreamAudio(realtime=False)
        dev = ListeningSim(dict(cfg), 2_400_000.0, [simdab.DabEnsemble("11D", -30.0)])
        # Weak enough that the receiver's noise is in every sample: no
        # stretch of the audio repeats, so each is found in one place.
        dev.fm = FmBand([FmStation(FM, -40.0, 0xC201, "SIM ONE", "Sim One: 1 kHz left, 1.5 right", 10,
                                   True, 1000.0, 1500.0)])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=dev)
        self.played, self.lock = [], threading.Lock()
        self.audio.tap(self._capture, 2)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        self.port = self.srv.serve("127.0.0.1", 0).server_address[1]
        self.addCleanup(self.srv.shutdown)
        self.assertEqual(self.srv.start_radio(), "")

    def _capture(self, pcm):
        with self.lock:
            self.played.append(pcm)

    def capture(self) -> np.ndarray:
        with self.lock:
            return np.frombuffer(b"".join(self.played), "<i2").reshape(-1, 2)

    def find(self, window, cap=None) -> int:
        """Where `window` (n, 2) was played, to the sample; it must be once."""
        cap = self.capture() if cap is None else cap
        hits = np.nonzero((cap[:len(cap) - len(window) + 1, 0] == window[0, 0])
                          & (cap[:len(cap) - len(window) + 1, 1] == window[0, 1]))[0]
        found = [int(i) for i in hits if np.array_equal(cap[i:i + len(window)], window)]
        self.assertEqual(len(found), 1, f"{len(found)} places")
        return found[0]

    def open(self, path, headers=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path, headers={shack.SHACK_SECRET_HEADER: SECRET, "X-OpenHamShack-User": "brian",
                                        "X-OpenHamShack-Level": level, **(headers or {})})
        return c, c.getresponse()

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        data = json.loads(r.read())
        c.close()
        return r.status, data

    def wait(self, cond, timeout=120.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.radio.heartbeat()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def kept(self, seconds):
        """Until the timeshift holds `seconds` of the station."""
        self.assertTrue(self.wait(lambda: self.req("GET", "/api/status", level="view")[1]["timeshift"]["lengthS"]
                                  >= seconds), self.req("GET", "/api/status", level="view")[1]["timeshift"])

    def wfm(self):
        self.assertTrue(self.wait(lambda: (self.radio.state().get("rds") or {}).get("ps")))

    def test_listening_behind_live_is_the_audio_played_that_long_ago(self):
        self.wfm()
        self.kept(8)
        st = self.req("GET", "/api/status", level="view")[1]["timeshift"]
        self.assertTrue(st["available"])
        self.assertEqual((st["capS"], st["station"]["label"], st["station"]["kind"]), (3600, "SIM ONE", "wfm"))
        live = len(self.capture())
        c, r = self.open("/api/audio/rx?behind=5&channels=2", level="view")
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "audio/L16; rate=48000; channels=2"))
        self.assertEqual(json.loads(r.getheader("X-Audio-Format")), {"encoding": "s16le", "rate": 48000, "channels": 2})
        self.assertAlmostEqual(json.loads(r.getheader("X-Timeshift"))["behindS"], 5.0, delta=0.01)
        t0 = time.monotonic()
        got = np.frombuffer(r.read(2 * RATE * 4), "<i2").reshape(-1, 2)
        took = time.monotonic() - t0
        c.close()
        at = self.find(got[:2400])
        # Five seconds before live as the request came (the simulator runs
        # faster than real time, so live moved on a little meanwhile).
        self.assertAlmostEqual((live - at) / RATE, 5.0, delta=0.5)
        np.testing.assert_array_equal(got, self.capture()[at:at + len(got)])       # whole, in order
        # Paced as it plays, a second ahead at most.
        self.assertGreater(took, 2.0 - Handler_ahead() - 0.2)
        # Mono is the average, as live.
        c, r = self.open("/api/audio/rx?behind=3", level="view")
        self.assertEqual(r.getheader("Content-Type"), "audio/L16; rate=48000; channels=1")
        mono = np.frombuffer(r.read(RATE * 2), "<i2")
        c.close()
        cap = self.capture()
        cap_mono = ((cap[:, 0].astype(np.int32) + cap[:, 1]) // 2).astype(np.int16)
        at = self.find(np.stack([mono[:2400], mono[:2400]], 1), np.stack([cap_mono, cap_mono], 1))
        np.testing.assert_array_equal(mono, cap_mono[at:at + len(mono)])
        # Further back than is kept: clamped to the oldest, and said.
        kept = self.req("GET", "/api/status", level="view")[1]["timeshift"]["lengthS"]
        c, r = self.open("/api/audio/rx?behind=99999", level="view")
        head = json.loads(r.getheader("X-Timeshift"))
        c.close()
        self.assertEqual(r.status, 200)
        self.assertTrue(head["clamped"])
        self.assertGreaterEqual(head["behindS"], kept - 0.5)
        self.assertLess(head["behindS"], 99999)
        c, r = self.open("/api/audio/rx?behind=2", level="view")
        self.assertFalse(json.loads(r.getheader("X-Timeshift"))["clamped"])
        c.close()
        # behind=0 is live; nonsense is refused.
        c, r = self.open("/api/audio/rx?behind=0", level="view")
        self.assertIsNone(r.getheader("X-Timeshift"))
        c.close()
        c, r = self.open("/api/audio/rx?behind=soon", level="view")
        self.assertEqual((r.status, json.loads(r.read())["code"]), (400, "bad_behind"))
        c.close()
        # No station: nothing kept, and a stream behind is refused.
        self.assertEqual(self.req("POST", "/api/set", {"mode": "fm", "vfo": 145_500_000.0})[0], 200)
        self.assertTrue(self.wait(lambda: not self.req("GET", "/api/status", level="view")[1]["timeshift"]["available"]))
        c, r = self.open("/api/audio/rx?behind=5", level="view")
        self.assertEqual((r.status, json.loads(r.read())["code"]), (409, "no_timeshift"))
        c.close()

    def recording(self, rid):
        listed = {x["id"]: x for x in self.req("GET", "/api/recordings", level="view")[1]["recordings"]}
        return listed[rid]

    def stop_and_read(self, rid, live):
        self.assertTrue(self.wait(lambda: self.recording(rid)["seconds"] or True))
        s, a = self.req("POST", "/api/recordings/stop", {"kind": "audio"})
        e = self.recording(rid)
        path = Path(self.radio.recordings_dir(), e["parts"]["data"]["name"])
        return e, flac_pcm(path)

    @unittest.skipUnless(shutil.which("ffmpeg"), "no ffmpeg to read FLAC back")
    def test_recordings_from_the_past_are_the_audio_played_then(self):
        self.wfm()
        self.kept(10)
        # fromSecondsAgo: the past, then on into live with nothing lost.
        live = len(self.capture())
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "fromSecondsAgo": 4})
        self.assertEqual(s, 200, a)
        self.assertAlmostEqual(a["timeshift"]["fromSecondsAgo"], 4.0, delta=0.1)
        self.assertEqual((a["timeshift"]["untilNow"], a["timeshift"]["why"]), (False, ""))
        rid = a["active"][0]["id"]
        self.assertTrue(self.wait(lambda: len(self.capture()) > live + 3 * RATE))
        e, pcm = self.stop_and_read(rid, live)
        at = self.find(pcm[:2400])
        self.assertAlmostEqual((live - at) / RATE, 4.0, delta=0.5)
        self.assertGreater(len(pcm), 6 * RATE)
        np.testing.assert_array_equal(pcm, self.capture()[at:at + len(pcm)])
        side = self.req("GET", f"/api/recordings/file?id={rid}&part=meta", level="view")
        self.assertAlmostEqual(side[1]["fromSecondsAgo"], 4.0, delta=0.1)
        self.assertEqual(side[1]["broadcast"]["label"], "SIM ONE")

        # The default lead, only while a station plays.
        self.assertEqual(self.req("POST", "/api/set", {"recordLeadSeconds": 2})[0], 200)
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio"})
        self.assertAlmostEqual(a["timeshift"]["fromSecondsAgo"], 2.0, delta=0.1)
        self.req("POST", "/api/recordings/stop", {})

        # lastMinutes: the last 0.1 minutes, a finished recording at once.
        live = len(self.capture())
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "lastMinutes": 0.1})
        self.assertEqual(s, 200, a)
        self.assertTrue(a["timeshift"]["untilNow"])
        rid = a["active"][0]["id"]
        self.assertTrue(self.wait(lambda: not self.req("GET", "/api/recordings/status")[1]["recording"]))
        e = self.recording(rid)
        self.assertEqual((e["seconds"], e["complete"], e["stopped"]), (6.0, True, "the timeshift's minutes are all in it"))
        pcm = flac_pcm(Path(self.radio.recordings_dir(), e["parts"]["data"]["name"]))
        at = self.find(pcm[:2400])
        self.assertAlmostEqual((live - at) / RATE, 6.0, delta=0.5)
        np.testing.assert_array_equal(pcm, self.capture()[at:at + 6 * RATE])

        # More than is kept: from the start of what is.
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "fromSecondsAgo": 3600})
        self.assertLess(a["timeshift"]["fromSecondsAgo"], 3600)
        self.assertIn("recording from its start", a["timeshift"]["why"])
        self.req("POST", "/api/recordings/stop", {})
        # Wide FM sends no DL Plus: from now, and it says so.
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "fromItemStart": True})
        self.assertEqual((s, a["timeshift"]["fromSecondsAgo"]), (200, 0.0))
        self.assertIn("no item", a["timeshift"]["why"])
        self.req("POST", "/api/recordings/stop", {})
        # Refusals.
        for body, code in (({"kind": "iq", "fromSecondsAgo": 5}, "bad_params"),
                           ({"kind": "audio", "fromSecondsAgo": 5, "lastMinutes": 1}, "bad_params"),
                           ({"kind": "audio", "fromSecondsAgo": -1}, "bad_params"),
                           ({"kind": "audio", "lastMinutes": "a while"}, "bad_params")):
            s, a = self.req("POST", "/api/recordings/start", body)
            self.assertEqual((s, a["code"]), (400, code), body)
        self.assertEqual(self.req("POST", "/api/set", {"mode": "fm", "vfo": 145_500_000.0})[0], 200)
        self.assertTrue(self.wait(lambda: not self.req("GET", "/api/status", level="view")[1]["timeshift"]["available"]))
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "fromSecondsAgo": 5})
        self.assertEqual((s, a["code"]), (409, "no_timeshift"))
        # And a plain one away from a station records from now, as always.
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio"})
        self.assertEqual(s, 200, a)
        self.assertNotIn("timeshift", a)
        self.req("POST", "/api/recordings/stop", {})

    def test_dab_a_station_change_clears_it_and_the_item_began_before_it(self):
        # From a mode with no station, so that stopping DAB leaves none.
        self.assertEqual(self.req("POST", "/api/set", {"mode": "fm", "vfo": 145_500_000.0})[0], 200)
        s, a = self.req("POST", "/api/decoders/sessions",
                        {"decoder": "dab", "freqHz": CENTRE, "params": {"block": "11D", "service": "C221"}})
        self.assertEqual(s, 201, a)
        sid = a["id"]
        self.assertTrue(self.wait(lambda: (self.radio.broadcast_station() or {}).get("title")))
        self.kept(4)
        st = self.req("GET", "/api/status", level="view")[1]["timeshift"]
        self.assertEqual((st["station"]["kind"], st["station"]["sid"], st["station"]["block"]), ("dab", "C221", "11D"))
        # The showcase's DL Plus item is on from before the buffer began.
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio", "fromItemStart": True})
        self.assertEqual(s, 200, a)
        self.assertIn("began before the timeshift buffer", a["timeshift"]["why"])
        self.assertGreater(a["timeshift"]["fromSecondsAgo"], 3.5)
        self.req("POST", "/api/recordings/stop", {})
        gen = self.srv.timeshift.gen
        # Another service on the block: another station, a new buffer.
        s, a = self.req("POST", f"/api/decoders/sessions/{sid}", {"params": {"service": "C3A7"}})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: self.srv.timeshift.gen > gen and
                                  (self.req("GET", "/api/status", level="view")[1]["timeshift"]["station"] or {})
                                  .get("sid") == "C3A7"))
        self.assertLess(self.req("GET", "/api/status", level="view")[1]["timeshift"]["lengthS"], 3.5)
        # DAB stopped: nothing kept.
        self.req("DELETE", f"/api/decoders/sessions/{sid}")
        self.assertTrue(self.wait(lambda: not self.req("GET", "/api/status", level="view")[1]["timeshift"]["available"]
                                  and not list((Path(self.radio.data_dir) / "timeshift").glob("*.ohsts"))))


def Handler_ahead():
    from ohscore.server.app import _Handler
    return _Handler.PACE_AHEAD_S


if __name__ == "__main__":
    unittest.main()
