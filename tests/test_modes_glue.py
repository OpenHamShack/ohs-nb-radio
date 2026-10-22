"""The adapter between the engine and ohscore.modes: it must bind to the real
registry (every mode it lists must come out with a decoder), route FreeDV by
waveform, and degrade - not raise - when a mode or the package is missing."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import sys
import unittest
from unittest import mock

import numpy as np

from ohscore import modes_glue
from ohscore.modes import MODES
from ohsnb import state


class RealRegistry(unittest.TestCase):
    def test_every_available_registry_mode_gets_a_decoder(self):
        """The failure this file once had: a registry shape the adapter did
        not recognise made every mode report 'no decoder' without an error."""
        names = [m for m in state.MODES if m not in modes_glue.NATIVE]
        info = modes_glue.available(names)
        for name in names:
            key = "freedv_700d" if name == "freedv" else name
            if MODES[key].available:
                self.assertTrue(info[name]["decode"], f"{name}: {info[name]['missing']}")
                self.assertEqual(info[name]["missing"], "")
                events = []
                self.assertIsNotNone(modes_glue.decoder(name, events.append, audio_out=lambda a: None)
                                     if name == "freedv" else modes_glue.decoder(name, events.append), name)

    def test_cw_encoder_takes_the_offset_by_any_name(self):
        enc = modes_glue.encoder("cw")
        audio = enc.render(text="E", offset=900.0, wpm=20)
        spec = np.abs(np.fft.rfft(audio))
        peak_hz = np.argmax(spec) * 12000 / len(audio)
        self.assertAlmostEqual(peak_hz, 900.0, delta=15)

    def test_sstv_picture_mode_travels_as_sstvMode(self):
        enc = modes_glue.encoder("sstv")
        img = np.zeros((16, 16, 3), np.uint8)
        robot = enc.render(image=img)                      # the encoder's default, Robot 36
        martin = enc.render(image=img, sstvMode="martinm1")
        # Martin M1 is ~114 s against Robot 36's ~36 s: the choice arrived.
        self.assertGreater(len(martin), 2.5 * len(robot))

    def test_decoder_events_are_tagged_with_the_engine_mode(self):
        events = []
        dec = modes_glue.decoder("cw", events.append)
        tone = modes_glue.encoder("cw").render(text="TEST TEST", freq=700.0, wpm=20)
        dec.feed(np.concatenate([tone, np.zeros(12000, np.float32)]), 0.0)
        self.assertTrue(events)
        self.assertTrue(all(e["mode"] == "cw" for e in events))

    def test_freedv_waveform_routes_to_its_registry_entry(self):
        waves = modes_glue.available(["freedv"])["freedv"]["waveforms"]
        self.assertIn("700d", waves)
        if MODES["freedv_700e"].available:
            self.skipTest("this libcodec2 opens 700E")
        info = modes_glue.available(["freedv"], freedv_mode="700e")["freedv"]
        self.assertFalse(info["decode"])
        self.assertTrue(info["missing"])
        self.assertIsNone(modes_glue.streamer("freedv", "700e"))

    def test_unknown_mode_is_a_sentence_not_an_error(self):
        info = modes_glue.available(["nosuchmode"])["nosuchmode"]
        self.assertFalse(info["decode"])
        self.assertIn("not built", info["missing"])


class Degrades(unittest.TestCase):
    def test_no_modes_package_at_all(self):
        with mock.patch.dict(sys.modules, {"ohscore.modes": None}):
            info = modes_glue.available(["ft8", "usb"])
            self.assertFalse(info["ft8"]["decode"])
            self.assertTrue(info["usb"]["decode"])
            self.assertIsNone(modes_glue.decoder("ft8", lambda e: None))

    def test_broken_decoder_does_not_raise(self):
        broken = mock.Mock(available=True, why="", make_decoder=mock.Mock(side_effect=RuntimeError("boom")))
        with mock.patch.dict(MODES, {"rtty": broken}):
            self.assertIsNone(modes_glue.decoder("rtty", lambda e: None))


if __name__ == "__main__":
    unittest.main()
