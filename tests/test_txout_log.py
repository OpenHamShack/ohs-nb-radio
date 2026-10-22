"""The transmit audio output's log lines (ohscore/audio.py PortAudioTxOut):
when an over opens the radio's sound device the log says which card,
through which host API, at what rate and buffer; when it cannot open, why;
and an over's underruns - the card asking for audio mid-over when there
was none, a gap the radio sends as silence - are counted for the over's
end line.

pyaudio is a fake module with one USB CODEC output here: no sound card is
opened, and the card's callback is called by the test as the card would."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import sys
import types
import unittest
from unittest import mock

import numpy as np

from ohscore import audio as au

CODEC = "USB Audio CODEC"


class FakeStream:
    def __init__(self, kw):
        self.kw = kw
        self.callback = kw.get("stream_callback")

    def start_stream(self):
        pass

    def stop_stream(self):
        pass

    def close(self):
        pass

    def get_output_latency(self):
        return 0.045


class FakePyAudio:
    """One default output and the radio's CODEC, both on ALSA."""

    def __init__(self):
        self.streams = []
        self.devices = [{"name": "default", "maxOutputChannels": 2, "maxInputChannels": 2, "hostApi": 0,
                         "defaultSampleRate": 48000.0},
                        {"name": CODEC, "maxOutputChannels": 2, "maxInputChannels": 2, "hostApi": 0,
                         "defaultSampleRate": 48000.0}]

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, i):
        return dict(self.devices[i], index=i)

    def get_default_output_device_info(self):
        return self.get_device_info_by_index(0)

    def get_host_api_info_by_index(self, i):
        return {"name": "ALSA"}

    def get_default_host_api_info(self):
        return {"index": 0, "name": "ALSA"}

    def is_format_supported(self, rate, **kw):
        return rate == 48_000

    def open(self, **kw):
        s = FakeStream(kw)
        self.streams.append(s)
        return s

    def terminate(self):
        pass


class TxOutLog(unittest.TestCase):
    def setUp(self):
        made = []

        def factory():
            pa = FakePyAudio()
            made.append(pa)
            return pa
        mod = types.SimpleNamespace(PyAudio=factory, paFloat32=1, paContinue=0, paWASAPI=13)
        patch = mock.patch.dict(sys.modules, {"pyaudio": mod})
        patch.start()
        self.addCleanup(patch.stop)
        self.pa = au.PortAudio()
        self.pa.start()
        self.addCleanup(self.pa.stop)
        self.fake = made[0]

    def test_opening_says_which_card_and_how(self):
        with self.assertLogs("ohsnb.audio", "INFO") as cm:
            out = self.pa.open_tx_out(CODEC, 0.5)
        self.addCleanup(out.tx_stop)
        self.assertIn(f"TX audio out opened: '{CODEC}' (ALSA, 48000 Hz, buffer 20 ms, latency 45 ms)",
                      "\n".join(cm.output))

    def test_a_missing_card_is_a_warning_naming_what_there_is(self):
        with self.assertLogs("ohsnb.audio", "WARNING") as cm, self.assertRaises(ValueError):
            self.pa.open_tx_out("IC-9700 CODEC", 0.5)
        self.assertIn(f"TX audio out 'IC-9700 CODEC': no such output device (outputs: 'default', '{CODEC}')",
                      "\n".join(cm.output))

    def test_underruns_count_mid_over_only(self):
        out = self.pa.open_tx_out(CODEC, 0.5)
        self.addCleanup(out.tx_stop)
        cb = self.fake.streams[-1].callback
        frames = out.frames
        cb(None, frames, None, None)                     # before the first write: not an underrun
        self.assertEqual(out.underruns, 0)
        out.write(np.zeros(1200, np.float32))            # 100 ms at 12 kHz
        cb(None, frames, None, None)
        self.assertEqual(out.underruns, 0)
        out.ring.discard(len(out.ring))                  # played out, and the next block is late:
        cb(None, frames, None, None)                     # a gap on air
        self.assertEqual(out.underruns, 1)
        out.tx_finish()                                  # draining: an empty ring is the end, not a gap
        cb(None, frames, None, None)
        self.assertEqual(out.underruns, 1)


if __name__ == "__main__":
    unittest.main()
