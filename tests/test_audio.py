"""ohscore/audio.py's own behaviour, and the Settings audio test's choice
between riding the engine's running stream and opening its own - without a
real sound card. DESIGN.md: the engine never imports Qt, so these run
without PyQt6 too."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore.audio import PortAudio, Ring, _rms_db


class RmsDb(unittest.TestCase):
    def test_full_scale_tone_is_near_zero_dbfs(self):
        t = np.arange(4800) / 48000.0
        x = np.sin(2 * np.pi * 700 * t).astype(np.float32)
        self.assertAlmostEqual(_rms_db(x), -3.0, delta=0.3)   # RMS of a full-scale sine is -3 dBFS

    def test_silence_is_far_below_the_meter_floor(self):
        self.assertLess(_rms_db(np.zeros(100, np.float32)), -100.0)

    def test_empty_chunk_does_not_crash_or_divide_by_zero(self):
        self.assertLess(_rms_db(np.zeros(0, np.float32)), -100.0)

    def test_quieter_signal_reads_a_lower_level(self):
        t = np.arange(4800) / 48000.0
        loud = np.sin(2 * np.pi * 700 * t).astype(np.float32)
        quiet = (0.1 * loud).astype(np.float32)
        self.assertLess(_rms_db(quiet), _rms_db(loud))


class MicLevelStaysLiveBetweenTransmissions(unittest.TestCase):
    """The mic meter used to freeze between transmissions because only the
    TX thread's read_mic() updated it. _on_mic() is what the card's own
    callback feeds on every chunk, transmitting or not."""

    def test_on_mic_updates_the_level_without_anything_reading_it_back(self):
        pa = PortAudio()               # __init__ never opens a real stream
        pa.mic_ring = Ring(48_000)
        self.assertEqual(pa.mic_level(), -120.0)
        t = np.arange(960) / 48000.0
        loud = np.sin(2 * np.pi * 700 * t).astype(np.float32)
        pa._on_mic(loud)
        self.assertGreater(pa.mic_level(), -6.0)       # near full scale, and nobody called read_mic()
        self.assertEqual(len(pa.mic_ring), len(loud))  # the ring still received it, for when TX does read


if __name__ == "__main__":
    unittest.main()
