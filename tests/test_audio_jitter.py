"""Receive playback's jitter buffer (ohscore/audio.py PortAudio): after a
hiccup it must come back with its cushion, or ordinary block-to-block
jitter keeps underrunning it. Simulated time, no threads and no sound
card: 75 ms receive blocks (the engine's at any rate) arrive with jitter
and the card's callback takes 20 ms every 20 ms, in the order a clock
would put them; pyaudio is a stand-in that only hands back the callback."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import sys
import types
import unittest
from unittest import mock

import numpy as np

from ohscore import audio as au


class _Stream:
    def __init__(self, kw, made):
        made.append(kw.get("stream_callback"))

    def start_stream(self):
        pass

    def stop_stream(self):
        pass

    def close(self):
        pass


def _pyaudio(made):
    class PyAudio:
        def get_device_count(self):
            return 0

        def get_default_output_device_info(self):
            return {"index": 0, "defaultSampleRate": 48000.0}

        def is_format_supported(self, rate, **_kw):
            return rate == 48_000

        def open(self, **kw):
            return _Stream(kw, made)

        def terminate(self):
            pass
    return types.SimpleNamespace(PyAudio=PyAudio, paFloat32=1, paContinue=0)


def underruns(jitter_ms: float, late_ms: float = 0.0, seconds: float = 60.0, seed: int = 1) -> int:
    """Underruns in `seconds` of blocks each delayed by |N(0, jitter)|,
    and one (the 200th) `late_ms` later still."""
    made = []
    with mock.patch.dict(sys.modules, {"pyaudio": _pyaudio(made)}):
        pa = au.PortAudio()
        pa.start()
        cb = made[0]
        rng = np.random.default_rng(seed)
        events = [(k * 0.075 + abs(rng.normal(0, jitter_ms / 1000)) + (late_ms / 1000 if k == 200 else 0), 1)
                  for k in range(int(seconds / 0.075))]
        events += [(j * 0.02, 0) for j in range(int(seconds / 0.02))]
        block = np.zeros(900, np.float32)
        for _t, is_block in sorted(events):
            if is_block:
                pa.play(block)
            else:
                cb(None, 960, None, 0)
        pa.stop()
        return pa.underruns


class JitterBuffer(unittest.TestCase):
    def test_ordinary_jitter_does_not_underrun(self):
        # Resuming at half the target - less than one block - underran 2
        # times a minute at 20-30 ms of jitter (before 17/10/2026).
        for j in (10, 20, 30):
            self.assertEqual(underruns(j), 0, f"{j} ms of jitter")

    def test_one_late_block_is_one_gap_not_a_run_of_them(self):
        self.assertLessEqual(underruns(20, late_ms=100), 1)

    def test_steady_blocks_never_underrun(self):
        self.assertEqual(underruns(0), 0)


if __name__ == "__main__":
    unittest.main()
