"""The microphone is opened only while something needs it (Brian, 10/10/2026).

Starting the radio used to open the sound card's input with its output, so
on macOS the first launch asked for the microphone before the window was
up - the Radio dmg's install proof showed no window at all - and every
listener's "microphone in use" light stayed on. Now PortAudio.start()
opens the speakers only, and the microphone is opened for a voice over
(before the key-up, closed after it), a voice memory being recorded, and
Settings' microphone check, and for nothing else.

PortAudio is a fake pyaudio module here and the radio is the simulator:
no sound card is opened and nothing transmits."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import numpy as np

from helpers import run_sim, sim_cfg
from ohscore import audio as au
from ohscore.audio import NullAudio
from ohsnb.radio import Radio


class FakeStream:
    def __init__(self, kw):
        self.input = bool(kw.get("input"))
        self.started = self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class FakePyAudio:
    """Enough of pyaudio.PyAudio for PortAudio.start(): one default output
    that takes 48 kHz, and every stream it is asked for, recorded.
    `refuse_input` is a card (or a permission) that will not give a
    microphone."""
    refuse_input = False

    def __init__(self):
        self.streams = []

    def get_device_count(self):
        return 0

    def get_default_output_device_info(self):
        return {"index": 0, "defaultSampleRate": 48000.0}

    def is_format_supported(self, rate, **kw):
        return rate == 48_000

    def open(self, **kw):
        if kw.get("input") and self.refuse_input:
            raise OSError(-9986, "Internal PortAudio error")
        s = FakeStream(kw)
        self.streams.append(s)
        return s

    def terminate(self):
        pass


def fake_pyaudio(refuse_input=False):
    made = []

    def factory():
        pa = FakePyAudio()
        pa.refuse_input = refuse_input
        made.append(pa)
        return pa
    mod = types.SimpleNamespace(PyAudio=factory, paFloat32=1, paContinue=0, paWASAPI=13)
    return mod, made


class PortAudioOpensTheMicrophoneOnDemand(unittest.TestCase):
    def started(self, refuse_input=False):
        mod, made = fake_pyaudio(refuse_input)
        patch = mock.patch.dict(sys.modules, {"pyaudio": mod})
        patch.start()
        self.addCleanup(patch.stop)
        pa = au.PortAudio()
        pa.start()
        self.addCleanup(pa.stop)
        return pa, made[0].streams

    def test_start_opens_the_speakers_and_not_the_microphone(self):
        pa, streams = self.started()
        self.assertTrue(streams)
        self.assertFalse(any(s.input for s in streams))
        self.assertFalse(pa.mic_open())

    def test_the_microphone_is_shared_by_its_users_and_closed_by_the_last(self):
        pa, streams = self.started()
        self.assertEqual(pa.open_mic(), "")
        mics = [s for s in streams if s.input]
        self.assertEqual(len(mics), 1)
        self.assertTrue(mics[0].started)
        self.assertEqual(pa.open_mic(), "")             # a second user: the same stream
        self.assertEqual(len([s for s in streams if s.input]), 1)
        pa.close_mic()
        self.assertTrue(pa.mic_open())                  # one user still has it
        self.assertFalse(mics[0].closed)
        pa.close_mic()
        self.assertFalse(pa.mic_open())
        self.assertTrue(mics[0].closed)
        self.assertFalse(any(s.closed for s in streams if not s.input))   # the speakers play on

    def test_stopping_the_audio_closes_a_microphone_still_open(self):
        pa, streams = self.started()
        pa.open_mic()
        pa.stop()
        self.assertTrue(all(s.closed for s in streams))
        self.assertFalse(pa.mic_open())

    def test_nothing_heard_before_an_opening_is_read_after_it(self):
        pa, _ = self.started()
        pa.open_mic()
        pa._on_mic(np.full(4800, 0.5, np.float32))
        pa.close_mic()
        pa.open_mic()
        self.assertEqual(len(pa.mic_ring), 0)

    def test_a_microphone_that_will_not_open_is_a_sentence_and_the_speakers_carry_on(self):
        pa, streams = self.started(refuse_input=True)
        note = pa.open_mic()
        self.assertIn("No microphone", note)
        self.assertFalse(pa.mic_open())
        self.assertTrue(streams and all(s.started for s in streams))
        pa.close_mic()                                  # paired as callers do: no error, nothing to close


class CountingAudio(NullAudio):
    """The null backend, noting every open_mic/close_mic and whether the
    radio was on the air when the microphone was opened."""

    def __init__(self, **kw):
        super().__init__(realtime=False, **kw)
        self.events = []
        self.radio = None
        self.users = 0

    def open_mic(self):
        self.events.append(("open", bool(self.radio and self.radio.tx_on_air)))
        self.users += 1
        return ""

    def close_mic(self):
        self.events.append(("close", bool(self.radio and self.radio.tx_on_air)))
        self.users -= 1

    def opens(self):
        return [e for e in self.events if e[0] == "open"]


class TheRadioOpensItOnlyWhenNeeded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, **over):
        over.setdefault("vfo", 10_489_700_000.0)
        over.setdefault("mode", "usb")
        over.setdefault("callsign", "GM4BRI")
        over.setdefault("licenceClass", "full")
        a = CountingAudio()
        r = Radio(sim_cfg(**over), persist=False, data_dir=tempfile.mkdtemp(dir=self.tmp), audio=a)
        a.radio = r
        self.radios.append(r)
        r.start()
        run_sim(r, 0.2)
        return r, a

    def wait(self, r, until, seconds=20.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds:
            r.heartbeat()
            if until():
                return True
            time.sleep(0.01)
        return until()

    def idle(self, r):
        return not r.state()["keyed"] and not (r.tx_thread and r.tx_thread.is_alive())

    def test_starting_and_listening_never_open_it(self):
        r, a = self.radio()
        run_sim(r, 1.0)
        self.assertEqual(a.events, [])

    def test_a_voice_over_opens_it_before_the_key_up_and_closes_it_after(self):
        r, a = self.radio()
        r.ptt(True)
        self.assertTrue(self.wait(r, lambda: r.tx_on_air))
        self.assertEqual(a.events, [("open", False)])    # opened while still off the air
        r.ptt(False)
        self.assertTrue(self.wait(r, lambda: self.idle(r)))
        self.assertEqual([e[0] for e in a.events], ["open", "close"])
        self.assertEqual(a.users, 0)

    def test_a_cw_carrier_does_not_open_it(self):
        r, a = self.radio(mode="cw", vfo=10_489_520_000.0)     # the CW-only segment
        r.ptt(True)
        self.assertTrue(self.wait(r, lambda: r.tx_on_air))
        r.ptt(False)
        self.assertTrue(self.wait(r, lambda: self.idle(r)))
        self.assertEqual(a.events, [])

    def test_a_voice_memory_does_not_open_it(self):
        r, a = self.radio()
        t = np.arange(int(0.5 * au.RATE)) / au.RATE
        r.keyer.slots.store(0, (0.3 * np.sin(2 * np.pi * 700 * t)).astype(np.float32))
        r.send_voice(0)
        self.assertTrue(self.wait(r, lambda: r.tx_on_air))
        self.assertTrue(self.wait(r, lambda: self.idle(r)))
        self.assertEqual(a.events, [])

    def test_recording_a_voice_memory_holds_it_for_the_recording(self):
        r, a = self.radio()
        r.keyer.record(0, max_seconds=0.3)
        self.assertTrue(self.wait(r, lambda: r.keyer.recording() is None))
        r.keyer.stop_recording()
        self.assertEqual([e[0] for e in a.events], ["open", "close"])
        self.assertEqual(a.users, 0)

    def test_a_recording_without_a_microphone_is_refused_not_saved_silent(self):
        r, a = self.radio()
        a.open_mic = lambda: (CountingAudio.open_mic(a), "No microphone (denied)")[1]
        r.keyer.record(1, max_seconds=0.3)
        self.assertTrue(self.wait(r, lambda: r.keyer.recording() is None))
        self.assertIn("Not recorded: No microphone", r.keyer.stop_recording() or r.keyer.rec_result)
        self.assertEqual(a.users, 0)
        self.assertFalse(r.keyer.slots.path(1).exists())


if __name__ == "__main__":
    unittest.main()
