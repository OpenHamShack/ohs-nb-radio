"""Sending JS8 (Brian, 17/10/2026): one frame per over through the
engine's send(), so through the same guard as FT8, on the simulator.

The waveform is ohsdigi's js8_encode_audio, which rust/ohsdigi/tests/
js8_golden.rs holds to JS8Call's own tones (testdata/js8/genjs8.txt);
here the app's encoder is held to the same reference and to ohsdigi's own
decoder. Keying is only ever the simulator's (Device.radiates is false),
as test_receive_only's and test_radio's are."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, noise_audio, run_sim
from ohscore.config import RECEIVE_ONLY_REFUSAL, receive_only
from ohscore.engine import TxRefused
from ohscore.modes import js8

LB = js8._OHSDIGI_JS8
HAVE_ENCODER = js8.CAN_ENCODE
GENJS8 = Path(__file__).resolve().parent.parent / "rust" / "ohsdigi" / "testdata" / "js8" / "genjs8.txt"
JS8_DL = 10_489_548_000.0


@unittest.skipUnless(HAVE_ENCODER, "ohsdigi with JS8 is not built here")
class Encoder(unittest.TestCase):
    def test_tones_are_js8calls_for_its_reference_frames(self):
        n = 0
        for line in GENJS8.read_text().splitlines():
            frame, i3, icos, want = line.split()[:4]
            if icos != "1":                 # genjs8's Normal rows (icos 1); the others are Fast's
                continue
            got = "".join(str(t) for t in LB.js8_tones(frame, int(i3), "normal"))
            self.assertEqual(got, want, frame)
            n += 1
        self.assertGreater(n, 50)

    def test_render_is_ohsdigis_waveform_for_each_frame(self):
        text = "G4XYZ HELLO FROM BERLIN TNX FOR THE QSO"
        fr = js8.frames(text, "GM4BRI", "IO75RL")
        self.assertEqual(fr, [(f, int(i)) for f, i in LB.js8_frames(text, "GM4BRI", "IO75")])
        enc = js8.Encoder()
        for part, (frame, i3) in enumerate(fr):
            got = enc.render(text=text, offset=1450.0, part=part, callsign="GM4BRI", locator="IO75RL")
            ref = np.frombuffer(LB.js8_encode_audio(frame, i3, "normal", 1450.0), "<f4")
            self.assertEqual(len(got), len(ref))
            self.assertLess(float(np.max(np.abs(got - ref / np.max(np.abs(ref)) * 0.95))), 1e-6)
        with self.assertRaises(ValueError):
            enc.render(text=text, part=len(fr), callsign="GM4BRI")

    def test_what_it_sends_decodes_as_the_frame_it_meant(self):
        audio = js8.Encoder().render(text="CQ CQ CQ", offset=1200.0, callsign="GM4BRI", locator="IO75")
        period = np.zeros(int(15 * 12000), np.float32)
        start = int(0.5 * 12000)                # where the engine starts it (SLOT_LEAD)
        period[start:start + len(audio)] = audio * 0.3
        period += np.random.default_rng(3).standard_normal(len(period)).astype(np.float32) * 0.05
        got = LB.js8_decode((np.clip(period, -1, 1) * 32767).astype("<i2").tobytes(), "normal")
        self.assertEqual([d["frame"] for d in got], [js8.frames("CQ CQ CQ", "GM4BRI")[0][0]])
        self.assertLess(abs(got[0]["freq"] - 1200.0), 3.0)
        self.assertLess(abs(got[0]["dt"]), 0.2)
        self.assertEqual(LB.js8_unpack(got[0]["frame"], got[0]["i3bit"])["text"].strip(),
                         "GM4BRI: @ALLCALL CQ CQ CQ")

    def test_every_message_names_the_sender(self):
        # Free text carries no callsign in JS8; it is identified here.
        fr = js8.frames("hello world", "GM4BRI")
        text = "".join(LB.js8_unpack(f, i)["text"] for f, i in fr)
        self.assertEqual(" ".join(text.split()), "HELLO WORLD DE GM4BRI")
        with self.assertRaises(ValueError):
            js8.frames("CQ CQ CQ", "")
        with self.assertRaises(ValueError):
            js8.frames("   ", "GM4BRI")


@unittest.skipUnless(HAVE_ENCODER, "ohsdigi with JS8 is not built here")
class Guard(unittest.TestCase):
    """A JS8 over goes through the engine's guard like any other."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def radio(self, **over):
        cfg = dict(mode="js8", vfo=JS8_DL, callsign="GM4BRI", locator="IO75RL")
        cfg.update(over)
        r = make_radio(self.tmp, audio_source=noise_audio(), **cfg)
        self.radios.append(r)
        r.start()
        run_sim(r, 0.2)
        return r

    def test_a_frame_keys_the_simulator_on_the_next_period(self):
        r = self.radio()
        r.send("js8", text="CQ CQ CQ", part=0, freq=1500.0)
        st = r.state()
        self.assertTrue(st["keyed"])
        start = float(st["txStartAt"])
        # On a period boundary + 0.5 s, as JS8Call's modulator starts it.
        self.assertAlmostEqual((start - 0.5) / 15.0, round((start - 0.5) / 15.0), places=6)
        r.halt()
        run_sim(r, 0.3, until=lambda: not r.state()["keyed"])
        self.assertFalse(r.state()["keyed"])

    def test_refused_under_receive_only(self):
        over = {}
        receive_only(over)
        r = self.radio(**over)
        with self.assertRaisesRegex(TxRefused, "^" + RECEIVE_ONLY_REFUSAL.split(" (")[0]):
            r.send("js8", text="CQ CQ CQ", part=0)
        self.assertFalse(r.state()["keyed"])

    def test_refused_outside_the_digimode_segments(self):
        r = self.radio(vfo=10_489_700_000.0)            # SSB only
        with self.assertRaisesRegex(TxRefused, "not allowed"):
            r.send("js8", text="CQ CQ CQ", part=0)
        r.set(vfo=10_489_748_000.0)                     # the middle beacon
        with self.assertRaisesRegex(TxRefused, "middle beacon"):
            r.send("js8", text="CQ CQ CQ", part=0)
        self.assertFalse(r.state()["keyed"])

    def test_refused_without_a_callsign(self):
        r = self.radio(callsign="")
        with self.assertRaisesRegex(TxRefused, "callsign"):
            r.send("js8", text="CQ CQ CQ", part=0)
        self.assertFalse(r.state()["keyed"])

    def test_sent_under_the_stations_own_call_whatever_is_asked(self):
        # A caller's callsign is not the one sent.
        r = self.radio()
        audio = r._render("js8", {"text": "CQ CQ CQ", "part": 0, "callsign": "N0CALL", "offset": 1500.0})
        ref = js8.Encoder().render(text="CQ CQ CQ", offset=1500.0, callsign="GM4BRI", locator="IO75")
        self.assertTrue(np.allclose(audio, ref))
        self.assertTrue(math.isfinite(float(np.max(audio))))


if __name__ == "__main__":
    unittest.main()
