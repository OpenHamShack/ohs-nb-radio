"""The voice keyer (ohscore/keyer.py, Engine.send_voice), run on the
simulators of both apps: a memory goes out through the same voice chain as
the microphone (what reaches the modulator's output is what PTT would have
sent with the recording spoken into the mic), every transmit guard still
refuses it where it refuses PTT, the over ends by itself, and a CQ loop
stops for PTT, Escape and a retune. Also the slots' files: recording from
the microphone, importing a WAV, a preview that never keys."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import time
import unittest
import wave
from pathlib import Path

import numpy as np

import ham_helpers
from helpers import make_radio, run_sim
from ohscore import keyer
from ohscore.engine import TxRefused

RATE = 12_000


def tone(seconds, hz=800.0, level=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    # A syllabic envelope, as speech has, so nothing mistakes it for dead air.
    return (level * (0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 2.0 * t))) * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def quantised(x):
    """What a 16-bit WAV gives back."""
    return (np.clip(np.round(np.asarray(x, np.float64) * 32768.0), -32768, 32767) / 32768.0).astype(np.float32)


def mic_then_silence(audio):
    """A NullAudio source that is `audio` and then silence."""
    pos = [0]

    def src(n):
        a = audio[pos[0]:pos[0] + n]
        pos[0] += n
        return np.concatenate([a, np.zeros(n - len(a), np.float32)]) if len(a) < n else a
    return src


def capture_tx(radio):
    """Every block of baseband the engine hands the device, after the whole
    transmit chain (mic gain, compressor, filter, modulator)."""
    got = []
    orig = radio._tx_sent

    def sent(dev, bb):
        got.append(np.array(bb, copy=True))
        orig(dev, bb)
    radio._tx_sent = sent
    return got


def wait(radio, until, seconds=20.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        radio.heartbeat()
        if until():
            return True
        time.sleep(0.01)
    return until()


def block(radio):
    """12 kHz audio samples per transmit block."""
    return radio.BLOCK_HOPS * (radio.geo.L // radio.geo.decimation_for(RATE))


def tx_idle(radio):
    return not radio.state()["keyed"] and not (radio.tx_thread and radio.tx_thread.is_alive())


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_slot_round_trips_and_keeps_its_name(self):
        s = keyer.VoiceSlots(self.tmp / "keyer")
        self.assertEqual(s.seconds(0), 0.0)
        with self.assertRaisesRegex(ValueError, "empty"):
            s.load(0)
        a = tone(1.5)
        self.assertAlmostEqual(s.store(2, a), 1.5)
        s.rename(2, "  CQ   contest  ")
        again = keyer.VoiceSlots(self.tmp / "keyer")          # as the next run sees it
        self.assertEqual(again.label(2), "CQ contest")
        self.assertEqual(again.label(0), "Memory 1")
        np.testing.assert_array_equal(again.load(2), quantised(a))
        self.assertEqual([x["seconds"] for x in again.listing()], [0, 0, 1.5, 0, 0, 0])
        again.clear(2)
        self.assertEqual(again.seconds(2), 0.0)
        with self.assertRaisesRegex(ValueError, "no voice memory 7"):
            again.load(6)

    def write(self, name, data: bytes, rate, channels, width):
        p = self.tmp / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.setframerate(rate)
            w.writeframes(data)
        return p

    def test_a_48k_stereo_wav_is_imported_as_12k_mono_at_the_same_pitch(self):
        t = np.arange(48_000 * 2) / 48_000
        left = 0.5 * np.sin(2 * np.pi * 1000 * t)
        st = np.stack([left, left], axis=1).reshape(-1)
        p = self.write("cq.wav", (st * 32767).astype("<i2").tobytes(), 48_000, 2, 2)
        x = keyer.read_wav(p)
        self.assertAlmostEqual(len(x) / RATE, 2.0, delta=0.02)
        spec = np.abs(np.fft.rfft(x[1000:-1000]))
        peak = np.fft.rfftfreq(len(x) - 2000, 1 / RATE)[np.argmax(spec)]
        self.assertAlmostEqual(peak, 1000.0, delta=2.0)
        self.assertAlmostEqual(float(np.max(np.abs(x[1000:-1000]))), 0.5, delta=0.02)

    def test_what_cannot_be_a_memory_is_refused_with_a_reason(self):
        p = self.tmp / "float.wav"
        # A WAVE_FORMAT_IEEE_FLOAT header: the wave module reads PCM only.
        data = np.zeros(100, "<f4").tobytes()
        hdr = (b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
               + (3).to_bytes(2, "little") + (1).to_bytes(2, "little") + (12000).to_bytes(4, "little")
               + (48000).to_bytes(4, "little") + (4).to_bytes(2, "little") + (32).to_bytes(2, "little")
               + b"data" + len(data).to_bytes(4, "little"))
        p.write_bytes(hdr + data)
        with self.assertRaisesRegex(ValueError, "16-bit PCM WAV"):
            keyer.read_wav(p)
        long = self.write("long.wav", bytes(2 * 8000 * 200), 8000, 1, 2)
        with self.assertRaisesRegex(ValueError, "at most 120 s"):
            keyer.read_wav(long)
        with self.assertRaisesRegex(ValueError, "Nothing was recorded"):
            keyer.VoiceSlots(self.tmp / "k").store(0, np.zeros(100, np.float32))


class NbRadios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, audio=None, data=None, **over):
        over.setdefault("vfo", 10_489_700_000.0)
        over.setdefault("mode", "usb")
        # A known licence (QO-100 allowed under Ofcom Full): otherwise the
        # "licence" standing warning (no class set) outranks the keyer's
        # own "info"-level one on the transmit card.
        over.setdefault("callsign", "GM4BRI")
        over.setdefault("licenceClass", "full")
        r = make_radio(data or tempfile.mkdtemp(dir=self.tmp), audio_source=audio, **over)
        self.radios.append(r)
        r.start()
        run_sim(r, 0.2)
        return r


class SentLikeTheMicrophone(NbRadios):
    def test_a_memory_leaves_the_chain_exactly_as_the_same_words_into_the_mic(self):
        rec = tone(1.2)
        # PTT, with the recording spoken into the microphone.
        a = self.radio(audio=mic_then_silence(quantised(rec)), micGain=6.0, compressor=10.0)
        n = block(a)
        blocks = -(-len(rec) // n)
        got_ptt = capture_tx(a)
        a.ptt(True)
        self.assertTrue(wait(a, lambda: len(got_ptt) > blocks))
        a.ptt(False)
        self.assertTrue(wait(a, lambda: tx_idle(a)))
        # The memory, in a radio of its own (the compressor has a memory).
        b = self.radio(micGain=6.0, compressor=10.0)
        b.keyer.slots.store(0, rec)
        got_mem = capture_tx(b)
        sources = []
        orig = b._status

        def status(**kv):
            if "txSource" in kv:
                sources.append(kv["txSource"])
            orig(**kv)
        b._status = status
        b.send_voice(0)
        self.assertEqual(b.state()["txWarning"]["text"], "Sending voice memory 1: Memory 1")
        self.assertTrue(wait(b, lambda: tx_idle(b)))          # it unkeys by itself, at the end
        self.assertEqual(sources[:2], ["voice:1", ""])
        self.assertEqual(b.state()["txWarning"], {})
        # Exactly the recording's blocks (the last padded with silence)...
        self.assertEqual(len(got_mem), blocks)
        mem = np.concatenate(got_mem)
        ptt = np.concatenate(got_ptt[:blocks])
        self.assertGreater(float(np.max(np.abs(mem))), 0.05)
        # ... and each the same as PTT's, sample for sample.
        np.testing.assert_allclose(mem, ptt, rtol=0, atol=1e-6)

    def test_mic_gain_still_applies_to_a_memory(self):
        # The stored recording is the raw microphone: the operator's mic
        # gain acts on it as on live speech.
        peaks = []
        for gain in (-10.0, 0.0):
            r = self.radio(micGain=gain, compressor=0.0)
            r.keyer.slots.store(0, tone(0.8, level=0.1))
            got = capture_tx(r)
            r.send_voice(0)
            self.assertTrue(wait(r, lambda: tx_idle(r)))
            peaks.append(float(np.max(np.abs(np.concatenate(got)))))
        self.assertGreater(peaks[1], peaks[0] * 2)

    def test_the_guard_refuses_a_memory_where_it_refuses_ptt(self):
        r = self.radio()
        r.keyer.slots.store(0, tone(0.5))
        for changes, why in (({"vfo": 10_489_748_000.0}, "middle beacon"),
                             # 10kHz above DL_HI: outside the transponder, but its uplink
                             # (2400.51 MHz) is still inside Ofcom Full's satellite row, so
                             # this exercises the bandplan refusal rather than the licence one.
                             ({"vfo": 10_490_010_000.0}, "outside"),
                             ({"vfo": 10_489_700_000.0, "mode": "am"}, "receive-only")):
            r.set(**changes)
            with self.assertRaisesRegex(TxRefused, why):
                r.ptt(True)
            with self.assertRaisesRegex(TxRefused, why):
                r.send_voice(0)
            self.assertFalse(r.state()["keyed"])
            self.assertEqual(r.state()["txWarning"], {})

    def test_not_in_a_mode_without_a_voice_chain_and_not_over_the_time_out(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.keyer.slots.store(0, tone(12.0))
        with self.assertRaisesRegex(ValueError, "voice modes"):
            r.send_voice(0)
        r.set(mode="usb", vfo=10_489_700_000.0)
        with self.assertRaisesRegex(ValueError, "empty"):
            r.send_voice(1)
        r.set(authorise=True, txTimeoutSec=10.0)
        with self.assertRaisesRegex(TxRefused, "longer than the transmit time-out"):
            r.send_voice(0)
        self.assertFalse(r.state()["keyed"])


class Loop(NbRadios):
    def looping_radio(self, interval=1.0):
        r = self.radio(keyerRepeat=True, keyerRepeatSec=interval)
        r.keyer.slots.store(1, tone(0.4))
        sources = []
        orig = r._status

        def status(**kv):
            if kv.get("txSource"):
                sources.append(kv["txSource"])
            orig(**kv)
        r._status = status
        return r, sources

    def first_wait(self, r):
        r.send_voice(1)
        self.assertTrue(wait(r, lambda: r.keyer.due(time.monotonic()) is not None))
        self.assertRegex(r.state()["txWarning"]["text"], r"Voice memory 2 again in \d s")

    def test_it_goes_round_until_ptt(self):
        r, sources = self.looping_radio()
        self.first_wait(r)
        # Round again by itself, on the supervisor's clock.
        self.assertTrue(wait(r, lambda: len(sources) >= 2, 10))
        self.assertEqual(sources[:2], ["voice:2", "voice:2"])
        self.assertTrue(wait(r, lambda: r.keyer.due(time.monotonic()) is not None))
        r.ptt(True)                         # the operator answers
        self.assertFalse(r.keyer.looping())
        self.assertTrue(wait(r, lambda: r.state()["txSource"] == "ptt"))
        r.ptt(False)
        self.assertTrue(wait(r, lambda: tx_idle(r)))
        n = len(sources)
        run_sim(r, 0.5)
        time.sleep(1.5)
        r.heartbeat()
        self.assertEqual(len(sources), n)   # nothing more from the keyer
        self.assertNotIn("keyer", r.tx_warnings)

    def test_escape_stops_it_while_waiting_and_while_sending(self):
        r, sources = self.looping_radio()
        self.first_wait(r)
        r.halt()
        self.assertFalse(r.keyer.looping())
        self.assertEqual(r.state()["txWarning"], {})
        time.sleep(1.5)
        r.heartbeat()
        self.assertEqual(sources, ["voice:2"])
        # Halted on the air: no next round either.
        r.keyer.slots.store(1, tone(5.0))
        r.send_voice(1)
        self.assertTrue(r.state()["keyed"])
        r.halt()
        self.assertTrue(wait(r, lambda: tx_idle(r)))
        time.sleep(1.5)
        r.heartbeat()
        self.assertEqual(sources, ["voice:2", "voice:2"])
        self.assertFalse(r.keyer.looping())

    def test_a_retune_stops_it(self):
        r, sources = self.looping_radio()
        self.first_wait(r)
        r.set(vfo=10_489_701_000.0)          # a click on the scope, a memory, auto-tune
        self.assertFalse(r.keyer.looping())
        self.assertEqual(r.state()["txWarning"], {})
        r.set(keyerRepeat=True)
        r.send_voice(1)
        r.set(volume=0.2)                    # not everything is a retune
        self.assertTrue(r.keyer.looping())
        r.set(keyerRepeat=False)             # turning repeat off ends it too
        self.assertFalse(r.keyer.looping())

    def test_a_window_that_stops_responding_stops_the_loop(self):
        r, sources = self.looping_radio(interval=4.0)
        r.send_voice(1)
        self.assertTrue(wait(r, lambda: r.keyer.due(time.monotonic()) is not None))
        # No heartbeat from here: by the time the next round is due the
        # watchdog (2 s) has long run out, and it must not go out.
        time.sleep(5.0)
        self.assertEqual(sources, ["voice:2"])
        self.assertFalse(r.keyer.looping())


class RecordAndPreview(NbRadios):
    def test_recording_takes_the_microphone_and_ptt_takes_it_back(self):
        speech = tone(3.0, hz=600.0)
        r = self.radio(audio=mic_then_silence(speech))
        r.keyer.record(3, max_seconds=1.0)
        self.assertTrue(wait(r, lambda: r.keyer.recording() is None))
        self.assertIn("Recorded Memory 4: 1.0 s", r.keyer.stop_recording())
        np.testing.assert_allclose(r.keyer.slots.load(3), quantised(speech[:RATE]), atol=1e-6)
        self.assertFalse(r.state()["keyed"])

    def test_not_while_transmitting_and_a_key_up_ends_a_recording(self):
        r = self.radio(audio=lambda n: tone(n / RATE))
        r.ptt(True)
        with self.assertRaisesRegex(ValueError, "Not while transmitting"):
            r.keyer.record(0)
        r.ptt(False)
        self.assertTrue(wait(r, lambda: tx_idle(r)))

        class Slow:
            """A microphone in real time, so the recording is still going."""
            name = "slow"

            def __init__(self, inner):
                self.inner = inner

            def read_mic(self, n):
                time.sleep(n / RATE)
                return np.full(n, 0.2, np.float32)

            def __getattr__(self, k):
                return getattr(self.inner, k)
        r.audio = Slow(r.audio)
        r.keyer.record(0)
        time.sleep(0.4)
        r.ptt(True)                          # PTT in the middle of it
        self.assertIsNone(r.keyer.recording())
        self.assertIn("Recorded", r.keyer.rec_result)
        r.ptt(False)
        self.assertTrue(wait(r, lambda: tx_idle(r)))

    def test_preview_plays_to_the_speaker_and_never_keys(self):
        r = self.radio()
        played = []
        r.audio.monitor = lambda a: played.append(np.array(a))
        keyed = []
        orig = r._key
        r._key = lambda req: (keyed.append(req), orig(req))
        rec = tone(0.6)
        r.keyer.slots.store(0, rec)
        secs = r.keyer.preview(0)
        self.assertAlmostEqual(secs, 0.6, places=3)
        self.assertTrue(wait(r, lambda: r.keyer.previewing() is None))
        self.assertEqual(keyed, [])
        self.assertFalse(r.state()["keyed"])
        np.testing.assert_allclose(np.concatenate(played), 0.8 * quantised(rec), atol=1e-6)


class Ham(unittest.TestCase):
    def tearDown(self):
        ham_helpers.close(self.r)

    def test_no_licence_class_refuses_a_memory_as_it_refuses_ptt(self):
        self.r = ham_helpers.make_radio(licenceClass="")
        self.r.start()
        self.r.keyer.slots.store(0, tone(0.5))
        self.r.set(mode="usb", vfo=145_650_000.0)
        with self.assertRaisesRegex(TxRefused, "No licence class chosen"):
            self.r.ptt(True)
        with self.assertRaisesRegex(TxRefused, "No licence class chosen"):
            self.r.send_voice(0)
        self.assertFalse(self.r.state()["keyed"])
        # Outside the licence (the UK 2 m band ends at 146 MHz): refused the same way too.
        self.r.set(authorise=True, licenceClass="full")
        self.r.set(vfo=146_500_000.0)
        with self.assertRaises(TxRefused) as ptt:
            self.r.ptt(True)
        with self.assertRaises(TxRefused) as mem:
            self.r.send_voice(0)
        self.assertEqual(str(mem.exception), str(ptt.exception))

    def test_fm_memory_is_the_mic_chain_with_its_ctcss(self):
        rec = tone(1.0, hz=700.0)
        out = []
        for use_ptt in (True, False):
            self.r = r = ham_helpers.make_radio(audio_source=mic_then_silence(quantised(rec)) if use_ptt else None,
                                                ctcssTx=88.5)
            r.set(authorise=True, licenceClass="full")
            r.start()
            r.set(mode="fm", vfo=145_500_000.0, rptShift="simplex")
            got = capture_tx(r)
            blocks = -(-len(rec) // block(r))
            if use_ptt:
                r.ptt(True)
                self.assertTrue(wait(r, lambda: len(got) > blocks))
                r.ptt(False)
            else:
                r.keyer.slots.store(0, rec)
                r.send_voice(0)
            self.assertTrue(wait(r, lambda: tx_idle(r)))
            out.append(np.concatenate(got[:blocks]))
            if use_ptt is False:
                self.assertEqual(len(got), blocks)
            ham_helpers.close(r)
        ptt, mem = out
        self.assertGreater(float(np.max(np.abs(mem))), 0.05)
        np.testing.assert_allclose(mem, ptt, rtol=0, atol=1e-5)
        self.r = ham_helpers.make_radio()          # for tearDown


if __name__ == "__main__":
    unittest.main()
