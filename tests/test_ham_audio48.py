"""Radio's receive audio at 48 kHz (23/10/2026, Engine.OUT_RATE): what the
sound card, api/audio/rx and the recordings get, and what stays at 12 kHz.

- **Heard:** every mode at 48 kHz, mono; wide FM flat to 15 kHz; stereo
  while shack_sdr's receiver has a station's pilot (simfm.py's stereo
  station: a tone in L, silence in R).
- **Not changed:** the decoders get the same 12 kHz audio as before, FT8
  decodes from the simulated band, and a voice over still takes 12 kHz
  microphone blocks and gives the monitor 12 kHz.
- **The sound card:** opened in stereo where it can be, a mono block on
  both sides, a stereo block kept apart, the transmit monitor on both, and
  no resampling when the card runs at 48 kHz.
- **The store form:** api/audio/rx announces 48 kHz, mono unless asked
  `?channels=2` (installed Remote builds play one channel only); in a mono
  mode two channels are the same audio on both sides; status and the
  microphone's format; and recordings at 48 kHz with the channel count
  they were made with.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import http.client
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore import audio as au
from ohscore.engine import AUDIO_RATE
from ohscore.server import shack
from ohscore.server.app import Server
from ohscore.server.audio import StreamAudio
from ohsradio import server as ham_server
from ohsradio.radio import Radio

from ham_helpers import close, make_radio, pump
from listen_helpers import ListeningSim, Station, TapAudio, make_listener, peak_hz
from helpers import run_sim
from test_server import SECRET

BROADCAST = 97_700_000.0


def stereo_on_air(dev):
    """A stereo station in place of the mono one on BROADCAST: shack_sdr's
    test transmitter with its pilot, 1 kHz in L and nothing in R, so a test
    can tell the two sides apart. Until 23/10/2026 a stand-in decoder at
    WfmDemod's stereo hook did this; the real receiver needs a real pilot."""
    from ohsradio.devices.simfm import FmBand, FmStation
    dev.stations = []
    dev.fm = FmBand([FmStation(BROADCAST, -20.0, None, stereo=True, left_hz=1000.0, right_hz=0.0)])


def rms(a) -> float:
    return float(np.sqrt(np.mean(np.asarray(a, np.float64) ** 2)))


class Radio12(Radio):
    """Radio as it was before 23/10/2026: receive audio played at 12 kHz."""
    OUT_RATE = AUDIO_RATE


def block_12k(r):
    """12 kHz samples in one receive block (Engine._tx_loop's n)."""
    return r.BLOCK_HOPS * (r.geo.L // r.geo.decimation_for(AUDIO_RATE))


class Heard(unittest.TestCase):
    def test_every_mode_is_played_mono_at_48_khz(self):
        r, audio, _dev = make_listener([Station(7_150_000.0, "am")], vfo=7_150_000.0, mode="am")
        self.addCleanup(close, r)
        r.start()
        self.assertEqual(audio.out_rate, 48_000)
        for mode in ("am", "usb", "cw", "fm"):
            r.set(mode=mode)
            pump(r, 5, until=lambda: len(audio.chunks) > 6)
            pump(r, 0.2)
            audio.chunks = []
            pump(r, 10, until=lambda: len(audio.chunks) >= 4)
            for c in audio.chunks[1:]:
                self.assertEqual((c.ndim, len(c)), (1, 4 * block_12k(r)), mode)
        self.assertEqual(r.audio_channels(), 1)

    def test_wide_fm_is_heard_to_15_khz(self):
        # A 12 kHz tone, gently deviated so its pre-emphasis stays inside the
        # channel: at 12 kHz audio (before) it could not be heard at all.
        st = Station(BROADCAST, "wfm", tone=12_000.0)
        st.DEVIATION = {"wfm": 8_000.0}
        r, audio, _dev = make_listener([st], vfo=BROADCAST, mode="wfm")
        self.addCleanup(close, r)
        r.start()
        pump(r, 10, until=lambda: r._rx_settled())
        pump(r, 0.3)
        audio.take()
        pump(r, 30, until=lambda: sum(len(c) for c in audio.chunks) >= 48_000)
        self.assertAlmostEqual(peak_hz(audio.take()[4800:]), 12_000.0, delta=2)

    def test_stereo_reaches_the_sound_card_while_the_decoder_has_the_pilot(self):
        r, audio, dev = make_listener([Station(BROADCAST, "wfm")], vfo=BROADCAST, mode="wfm")
        self.addCleanup(close, r)
        stereo_on_air(dev)
        r.start()
        pump(r, 10, until=lambda: sum(len(c) for c in audio.chunks if c.ndim == 2) > 48_000)
        c = [c for c in audio.chunks if c.ndim == 2][-1]            # past the blend's first moments
        self.assertEqual(c.shape[1], 2)
        self.assertGreater(rms(c[:, 0]), 0.05)
        self.assertLess(rms(c[:, 1]), rms(c[:, 0]) / 30)          # R is the silent side
        self.assertEqual(r.audio_channels(), 2)
        r.set(mode="am")
        self.assertEqual(r.audio_channels(), 1)


class DecodersUnchanged(unittest.TestCase):
    def capture(self, cls, n_blocks=30):
        """The audio the engine hands its decoders, block by block."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "mode": "usb",
               "vfo": 14_074_000.0}
        r = cls(cfg, persist=False, data_dir=tmp.name, audio=au.NullAudio(realtime=False))
        got = []
        inner = r._demodulate

        def keep(*a):
            out = inner(*a)
            if len(got) < n_blocks:
                got.append(np.array(out[0]))
            return out
        r._demodulate = keep
        try:
            r.start()
            pump(r, 30, until=lambda: len(got) >= n_blocks)
        finally:
            r.stop()
        return got

    def test_the_decoders_get_the_same_12_khz_audio_whatever_is_heard(self):
        before, now = self.capture(Radio12), self.capture(Radio)
        self.assertEqual(len(before), len(now))
        for a, b in zip(before, now):
            self.assertEqual(len(b), len(a))
            np.testing.assert_array_equal(a, b)

    def test_wide_fm_gives_the_decoders_12_khz_too(self):
        r, _audio, _dev = make_listener([Station(BROADCAST, "wfm")], vfo=BROADCAST, mode="wfm")
        self.addCleanup(close, r)
        lens = []
        inner = r._demodulate
        r._demodulate = lambda *a: (lambda out: (lens.append(out[0].shape), out)[1])(inner(*a))
        r.start()
        pump(r, 10, until=lambda: len(lens) > 20)
        # Steady state: whole 12 kHz blocks, mono (the decimator's start-up
        # holds back a few samples of the first).
        self.assertTrue(all(s == (block_12k(r),) for s in lens[5:]), lens[5:])

    def test_ft8_decodes_from_the_simulated_band(self):
        from ohscore.devices.simcore import FT8Activity
        r = make_radio(simSignals=True, simSeed=7, mode="ft8", vfo=14_074_000.0, licenceClass="full")
        self.addCleanup(close, r)
        ev = r.subscribe("events", 500)
        r.start()
        if not r.state()["modes"]["ft8"]["decode"]:
            self.skipTest("FT8 decoder not available: " + r.state()["modes"]["ft8"]["missing"])
        self.assertEqual(r.audio.out_rate, 48_000)
        got = run_sim(r, 47.0, [ev])["events"]
        end = time.monotonic() + 15
        while time.monotonic() < end and not any(e.get("mode") == "ft8" and e.get("text") for e in got):
            got += pump(r, 0.5, feeds=[ev])["events"]
        texts = {e.get("text") for e in got if e.get("mode") == "ft8"}
        self.assertTrue(texts & set(FT8Activity.MESSAGES), texts)


class TransmitUnchanged(unittest.TestCase):
    def test_a_voice_over_takes_12_khz_from_the_microphone_and_gives_the_monitor_12_khz(self):
        t = [0]

        def mic(n):
            x = 0.3 * np.sin(2 * np.pi * 1000.0 * (t[0] + np.arange(n)) / AUDIO_RATE)
            t[0] += n
            return x.astype(np.float32)
        r = make_radio(audio_source=mic, licenceClass="full", mode="usb", vfo=14_200_000.0, monitor=True)
        self.addCleanup(close, r)
        asked, monitored = [], []
        a = r._inj_audio
        read = a.read_mic
        a.read_mic = lambda n: (asked.append(n), read(n))[1]
        a.monitor = lambda x: monitored.append(len(x))
        r.start()
        r.set(authorise=True)
        r.ptt(True)
        self.assertTrue(r.state()["keyed"], r.state().get("txBlocked"))
        pump(r, 10, until=lambda: len(asked) >= 6 and len(monitored) >= 6)
        r.ptt(False)
        n = block_12k(r)
        self.assertGreaterEqual(len(asked), 6)
        self.assertEqual(set(asked), {n})
        self.assertEqual(set(monitored), {n})
        self.assertEqual(r.audio.out_rate, 48_000)          # while receive is heard at 48


def _pyaudio(made, stereo=True, rates=(48_000,)):
    """A stand-in pyaudio: hands back each stream's callback and arguments."""
    class Stream:
        def __init__(self, kw):
            made.append(kw)

        def start_stream(self):
            pass

        def stop_stream(self):
            pass

        def close(self):
            pass

    class PyAudio:
        def get_device_count(self):
            return 0

        def get_default_output_device_info(self):
            return {"index": 0, "defaultSampleRate": 48000.0}

        def is_format_supported(self, rate, output_channels=1, **_kw):
            return rate in rates and (stereo or output_channels == 1)

        def open(self, **kw):
            return Stream(kw)

        def terminate(self):
            pass
    return types.SimpleNamespace(PyAudio=PyAudio, paFloat32=1, paContinue=0)


class SoundCard(unittest.TestCase):
    def card(self, stereo=True, rates=(48_000,)):
        made = []
        p = mock.patch.dict(sys.modules, {"pyaudio": _pyaudio(made, stereo, rates)})
        p.start()
        self.addCleanup(p.stop)
        pa = au.PortAudio()
        pa.set_out_rate(48_000)
        pa.start()
        self.addCleanup(pa.stop)
        cb = made[0]["stream_callback"]

        def take(frames):
            # The first call after the cushion fills only ends priming
            # (PortAudio.RESUME): it plays silence and reads nothing.
            if pa.priming:
                cb(None, 1, None, 0)
            out = np.frombuffer(cb(None, frames, None, 0)[0], np.float32)
            return out.reshape(frames, -1)
        return pa, made[0], take

    def test_a_stereo_card_is_opened_in_stereo_at_48_khz_with_nothing_resampled(self):
        pa, kw, take = self.card()
        self.assertEqual((kw["channels"], kw["rate"], pa.up), (2, 48_000, None))
        x = np.sin(np.arange(9600) * 0.1).astype(np.float32)
        pa.play(np.stack([x, -x], axis=1))
        out = take(9600)
        np.testing.assert_array_equal(out[:, 0], x)
        np.testing.assert_array_equal(out[:, 1], -x)

    def test_mono_is_played_on_both_sides(self):
        pa, _kw, take = self.card()
        x = np.linspace(-0.5, 0.5, 9600, dtype=np.float32)
        pa.play(x)
        out = take(9600)
        np.testing.assert_array_equal(out[:, 0], out[:, 1])
        self.assertGreater(float(np.abs(out).max()), 0.0)

    def test_the_transmit_monitor_is_heard_on_both_sides(self):
        pa, _kw, take = self.card()
        pa.monitor(np.full(1200, 0.25, np.float32))           # 100 ms at 12 kHz
        out = take(960)
        np.testing.assert_array_equal(out[:, 0], out[:, 1])
        self.assertGreater(float(out[200:, 0].mean()), 0.2)

    def test_a_mono_card_hears_stereo_averaged(self):
        pa, kw, take = self.card(stereo=False)
        self.assertEqual(kw["channels"], 1)
        pa.play(np.stack([np.full(9600, 0.4, np.float32), np.zeros(9600, np.float32)], axis=1))
        out = take(9600)
        self.assertEqual(out.shape[1], 1)
        self.assertAlmostEqual(float(out[-100:, 0].mean()), 0.2, places=5)

    def test_a_44_1_khz_card_is_resampled_per_channel(self):
        pa, kw, take = self.card(rates=(44_100,))
        self.assertEqual((kw["rate"], kw["channels"]), (44_100, 2))
        t = np.arange(48_000) / 48_000
        x = np.stack([np.sin(2 * np.pi * 1000 * t), np.sin(2 * np.pi * 3000 * t)], axis=1).astype(np.float32)
        # A tenth of a second played and one taken, as the card would; a
        # whole second at once is more than the ring keeps (PortAudio.MAX).
        out = []
        for k in range(10):
            pa.play(x[k * 4800:(k + 1) * 4800])
            out.append(take(4410))
        out = np.concatenate(out)[3000:]
        self.assertAlmostEqual(peak_hz(out[:, 0], 44_100.0), 1000.0, delta=1)
        self.assertAlmostEqual(peak_hz(out[:, 1], 44_100.0), 3000.0, delta=1)


def flac_rate_and_channels(path):
    """STREAMINFO's sample rate and channel count (FLAC format, section
    METADATA_BLOCK_STREAMINFO: 20 bits of rate, 3 of channels - 1)."""
    b = Path(path).read_bytes()
    assert b[:4] == b"fLaC"
    info = b[8:8 + 34]
    bits = int.from_bytes(info[10:13], "big")
    return bits >> 4, ((bits >> 1) & 0x7) + 1


class StoreForm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
               "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": BROADCAST, "mode": "wfm"}
        self.audio = StreamAudio(realtime=False)
        self.dev = ListeningSim(dict(cfg), 2_400_000.0, [Station(BROADCAST, "wfm")])
        self.radio = Radio(cfg, persist=False, data_dir=tmp.name, audio=self.audio, device=self.dev)
        self.srv = Server(self.radio, ham_server.info("9.9.9"), self.audio, secret=SECRET)
        httpd = self.srv.serve("127.0.0.1", 0)
        self.port = httpd.server_address[1]
        self.addCleanup(self.srv.shutdown)

    def start(self):
        self.assertEqual(self.srv.start_radio(), "")

    def req(self, method, path, body=None, level="control"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Content-Type": "application/json", shack.SHACK_SECRET_HEADER: SECRET,
                   "X-OpenHamShack-User": "brian", "X-OpenHamShack-Level": level,
                   "X-OpenHamShack-Device": "dev_TEST", "X-OpenHamShack-Auth": "device"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def listen(self, query="", nbytes=48_000):
        """(Content-Type, X-Audio-Format, `nbytes` of PCM as int16 frames)."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        c.request("GET", "/api/audio/rx" + query, headers={shack.SHACK_SECRET_HEADER: SECRET,
                                                           "X-OpenHamShack-User": "b", "X-OpenHamShack-Level": "view"})
        r = c.getresponse()
        if r.status != 200:
            body = json.loads(r.read())
            c.close()
            return r.status, body, None
        ct, fmt = r.getheader("Content-Type"), json.loads(r.getheader("X-Audio-Format"))
        data = r.read(nbytes)
        c.close()
        return ct, fmt, np.frombuffer(data, "<i2").reshape(-1, fmt["channels"])

    def test_a_listener_asking_nothing_gets_mono_at_48_khz(self):
        self.start()
        ct, fmt, pcm = self.listen()
        self.assertEqual(ct, "audio/L16; rate=48000; channels=1")
        self.assertEqual(fmt, {"encoding": "s16le", "rate": 48_000, "channels": 1})
        self.assertEqual(pcm.shape[1], 1)

    def test_before_the_radio_starts_the_format_is_already_48_khz(self):
        ct, fmt, pcm = self.listen(nbytes=4800)
        self.assertEqual((ct, fmt["rate"]), ("audio/L16; rate=48000; channels=1", 48_000))
        self.assertFalse(pcm.any())                 # silence while the radio is off

    def test_two_channels_in_a_mono_mode_are_the_same_audio_on_both_sides(self):
        self.start()
        ct, fmt, pcm = self.listen("?channels=2")
        self.assertEqual(ct, "audio/L16; rate=48000; channels=2")
        self.assertEqual((fmt["channels"], pcm.shape[1]), (2, 2))
        self.assertTrue(pcm.any())
        np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])

    def test_two_channels_in_stereo_keep_the_sides_apart_and_mono_is_their_average(self):
        stereo_on_air(self.dev)
        self.start()
        self.assertTrue(self.wait(lambda: self.req("GET", "/api/status", level="view")[1]["audio"]["stereo"]))
        _ct, _fmt, lr = self.listen("?channels=2", nbytes=96_000)
        lr = lr[-6000:]
        self.assertGreater(rms(lr[:, 0]), 1000.0)
        self.assertLess(rms(lr[:, 1]), rms(lr[:, 0]) / 30)
        _ct, fmt, m = self.listen(nbytes=48_000)
        self.assertEqual(fmt["channels"], 1)
        # Half of L (R is silence), so never as loud as L alone.
        self.assertLess(np.abs(m[-6000:].astype(int)).max(), np.abs(lr[:, 0].astype(int)).max() * 0.75)

    def test_a_channel_count_it_cannot_send_is_refused(self):
        for q in ("?channels=3", "?channels=0", "?channels=stereo"):
            status, body, _ = self.listen(q)
            self.assertEqual((status, body["code"]), (400, "bad_channels"), q)

    def test_status_gives_both_directions_formats(self):
        self.start()
        a = self.req("GET", "/api/status", level="view")[1]["audio"]
        self.assertEqual((a["encoding"], a["rate"], a["channels"], a["stereo"]), ("s16le", 48_000, 1, False))
        self.assertEqual(a["tx"], {"encoding": "s16le", "rate": 12_000, "channels": 1})

    def test_recordings_are_48_khz_with_the_channel_count_they_began_with(self):
        self.start()
        e = self.record()
        self.assertEqual((e["sampleRate"], e["channels"]), (48_000, 1))
        self.assertEqual(flac_rate_and_channels(Path(self.radio.recordings_dir(), e["parts"]["data"]["name"])),
                         (48_000, 1))
        stereo_on_air(self.dev)
        self.assertTrue(self.wait(lambda: self.radio.audio_channels() == 2))
        e = self.record()
        self.assertEqual((e["sampleRate"], e["channels"]), (48_000, 2))
        self.assertEqual(flac_rate_and_channels(Path(self.radio.recordings_dir(), e["parts"]["data"]["name"])),
                         (48_000, 2))

    def record(self, seconds=1.0):
        s, a = self.req("POST", "/api/recordings/start", {"kind": "audio"})
        self.assertEqual(s, 200, a)
        self.assertTrue(self.wait(lambda: any(x["kind"] == "audio" and x["seconds"] >= seconds for x in
                                              self.req("GET", "/api/recordings/status", level="view")[1]["active"]),
                                  timeout=30))
        s, a = self.req("POST", "/api/recordings/stop", {"kind": "audio"})
        self.assertEqual(s, 200, a)
        (e,) = [x for x in self.req("GET", "/api/recordings", level="view")[1]["recordings"]
                if x["id"] == a["stopped"][0]["id"]]
        return e

    def wait(self, cond, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            self.radio.heartbeat()
            time.sleep(0.02)
        return False


if __name__ == "__main__":
    unittest.main()
