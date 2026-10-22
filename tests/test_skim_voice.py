import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The skimmer's "SSB" against "SSB?" (ohsnb/dsp/skim.py ssb_label): the
label says whether speech was heard, not whether the dial is confirmed.

On Brian's evening of 17/10/2026 the band list said "SSB?" against every
voice on the band - five recordings, 13 minutes, 124 SSB tracks, not one
labelled "SSB" - because the label meant "two looks agreed on the carrier
within 10 Hz", which real QO-100 voices rarely gave in time. The
excerpt here is one of those voices: 4 s of a USB station at 10489.7698
(rec 15:41:45Z, its lower edge at 10489.7701), as the skimmer's own voice
look hears it (12 kHz, centred LOW_CUT under the voice's edge). Auto-tune
hears speech in it (160 voiced frames, a moving pitch) and refuses only on
where the carrier is: the station's low cut is ~100 Hz, nearer than the
edge rule allows. That station is SSB, and is now listed as SSB; its dial
stays unmeasured, which `exact`/`measured` and the note say.

The guards are tested beside it: speech heard where the band plan has no
SSB never makes "SSB" (the FT8 window's pile passed auto-tune's voice
tests on 17/10), the mixed segment needs two looks hearing speech, and a
data refusal starts the count again."""
import types
import unittest
from pathlib import Path

import numpy as np

from helpers import sim_cfg
from ohscore.dsp import autotune
from ohsnb.devices.sim import SimDevice
from ohsnb.dsp import skim
from ohsnb.ui import skimview

EXCERPT = Path(__file__).parent / "data" / "qo100-usb-voice-17oct.npz"
SSB_ONLY = 10_489_770_100.0      # the excerpt's own place: the SSB-only segment
MIXED = 10_489_900_000.0         # mixed modes: data allowed
NARROW_DIGI = 10_489_570_000.0   # narrow digimodes, clear of the calling windows: no SSB


def real_voice() -> autotune.Tune:
    z = np.load(EXCERPT)
    iq = (z["iq"][:, 0] + 1j * z["iq"][:, 1]).astype(np.complex64) / 32768.0
    return autotune.listen(iq, "usb", float(z["rate"]), most=autotune.CAPTURE_SECONDS)


class Labels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = real_voice()
        cls.geo = SimDevice(sim_cfg()).geo

    def look(self, sk, tr, r):
        """One voice look's result handed to the skimmer, as _listen does."""
        sk._voice(types.SimpleNamespace(track=tr, centre=tr.lo - autotune.LOW_CUT), r)

    def track(self, sk, lo):
        tr = skim.Track(1, lo, lo + 2_400.0, 20.0, 0.0, 0.0)
        sk.tracks = [tr]
        sk._name(tr)
        return tr

    def entry(self, sk):
        return [e for e in sk.entries() if e["id"] == 1][0]

    def test_the_excerpt_is_speech_auto_tune_cannot_place(self):
        r = self.voice
        self.assertFalse(r.ok, r)
        self.assertIn("voice's edge", r.why)
        self.assertTrue(skim.heard_speech(r))

    def test_a_real_voice_auto_tune_refuses_is_ssb_with_its_dial_unmeasured(self):
        sk = skim.Skimmer(self.geo, budget=1.0)
        tr = self.track(sk, SSB_ONLY)
        self.assertEqual(self.entry(sk)["label"], "SSB?")     # the spectrum's guess, nothing heard yet
        self.look(sk, tr, self.voice)
        e = self.entry(sk)
        self.assertEqual((e["kind"], e["label"], e["voice"]), ("ssb", "SSB", True), e)
        self.assertFalse(e["exact"])
        self.assertEqual(e["measured"], "")
        self.assertEqual(skimview.short_text(e), "SSB")
        self.assertEqual(skimview.colour_of(e), "warn")      # the dial is still a guess
        self.assertIn("dial not measured yet", skimview.note_text(e))

    def test_where_data_is_allowed_it_takes_two_looks_hearing_speech(self):
        sk = skim.Skimmer(self.geo, budget=1.0)
        tr = self.track(sk, MIXED)
        self.look(sk, tr, self.voice)
        self.assertEqual(self.entry(sk)["label"], "SSB?")
        self.look(sk, tr, self.voice)
        self.assertEqual(self.entry(sk)["label"], "SSB")

    def test_speech_heard_where_the_band_plan_has_no_ssb_is_not_ssb(self):
        sk = skim.Skimmer(self.geo, budget=1.0)
        tr = self.track(sk, NARROW_DIGI)
        for _ in range(3):
            self.look(sk, tr, self.voice)
        e = self.entry(sk)
        self.assertNotEqual(e["label"], "SSB", e)
        self.assertFalse(e["voice"])

    def test_a_data_refusal_starts_the_count_again(self):
        sk = skim.Skimmer(self.geo, budget=1.0)
        tr = self.track(sk, MIXED)
        data = autotune.Tune(False, why="its level holds steady (within 0.9 dB) - a beacon or a data mode, "
                                        "not speech")
        self.look(sk, tr, self.voice)
        self.look(sk, tr, data)
        self.assertEqual(self.entry(sk)["kind"], "data")
        tr.kind = "signal"                                    # as _name does when it is looked at afresh
        self.look(sk, tr, self.voice)
        self.assertEqual(self.entry(sk)["label"], "SSB?")

    def test_a_refusal_that_heard_nothing_leaves_the_guess(self):
        sk = skim.Skimmer(self.geo, budget=1.0)
        tr = self.track(sk, SSB_ONLY)
        self.look(sk, tr, autotune.Tune(False, why="nothing near the dial stands above the noise"))
        e = self.entry(sk)
        self.assertEqual((e["label"], e["voice"]), ("SSB?", False))


if __name__ == "__main__":
    unittest.main()
