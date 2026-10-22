"""Auto-tune on real QO-100 voices: 12 s excerpts of the receive channel
from a recording Brian made on 17/10/2026 while auto-tune refused most of
what he pressed it on (tests/data/autotune/, cut by
tools/autotune_replay.py excerpt from openhamshack-nb-20261017-155205Z).

Each station's carrier was measured from tens of seconds of its own
speech (tools/autotune_replay.py label: one offset clearly ahead in the
pitch harmonics' vote over a whole over, both halves agreeing), and for
two of them confirmed by the carrier itself leaking a few hertz from
there. Every excerpt is 100 Hz below that carrier, where an operator who
clicked near the station would start.

The stations are the kinds that failed: voices starting 70-90 Hz over
their carrier (an IC-9700 on its widest filter passes from 100 Hz), one
with its leaked carrier just under the voice, beside a 300 Hz transmitter
with a leaked carrier and one with neither, which must still land."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest
from pathlib import Path

import numpy as np

from ohscore.dsp import autotune as at

DATA = Path(__file__).resolve().parent / "data" / "autotune"
CARRIER = 100.0        # every excerpt's dial is this far under the station's carrier
RIGHT_HZ = 15.0        # within the ear's tolerance: the voice sounds right


def excerpt(name: str) -> np.ndarray:
    z = np.load(DATA / f"{name}.npz")
    return (z["iq16"][:, 0] + 1j * z["iq16"][:, 1]).astype(np.complex64) * np.float32(z["scale"])


class RealVoices(unittest.TestCase):
    def assertLands(self, r):
        self.assertTrue(r.ok, r.why)
        self.assertLess(abs(r.offset - CARRIER), RIGHT_HZ, f"landed {r.offset - CARRIER:+.0f} Hz from the carrier")

    def test_the_edge_is_the_voice_not_its_leaked_carrier(self):
        # The station Brian pressed auto-tune on twice at 16:51 BST: its
        # carrier leaks a few hertz from where it should be, 70-90 Hz under
        # a voice that starts low. The voice's edge used to be found on the
        # carrier itself, which put the carrier out of the harmonics' search
        # and refused every listen.
        c0, band, why = at.coarse(excerpt("qo100-20261017-817081-leak-low-cut")[:int(4 * at.RATE)], "usb")
        self.assertEqual(why, "")
        edge = c0 + at.LOW_CUT
        self.assertGreater(edge - CARRIER, 50.0)
        self.assertLess(edge - CARRIER, 120.0)

    def test_a_low_cut_voice_with_its_carrier_leaking_lands(self):
        self.assertLands(at.listen(excerpt("qo100-20261017-817081-leak-low-cut"), "usb"))

    def test_a_low_cut_voice_the_comb_is_sure_of_lands(self):
        # Refused before for putting the carrier 70-80 Hz from the voice's
        # edge (MIN_EDGE_GAP): no other offset came near, and both halves
        # agreed.
        r = at.listen(excerpt("qo100-20261017-799990-low-cut"), "usb")
        self.assertLands(r)
        self.assertTrue(r.details.get("near_answer"))

    def test_a_low_cut_voice_is_never_landed_a_pitch_low(self):
        # Landed 142 Hz low before: the edge chose the offset a pitch under
        # the true one because the true one was "too near". Now it may
        # refuse, but its first guess is the station.
        r = at.listen(excerpt("qo100-20261017-799990-low-cut-b"), "usb")
        if r.ok:
            self.assertLands(r)
        else:
            self.assertLess(abs(r.details["guesses"][0] - CARRIER), RIGHT_HZ, r.why)

    def test_a_300_hz_transmitter_with_a_leaked_carrier_lands(self):
        self.assertLands(at.listen(excerpt("qo100-20261017-829167-leak"), "usb"))

    def test_a_300_hz_transmitter_without_one_lands(self):
        self.assertLands(at.listen(excerpt("qo100-20261017-835059-high-cut"), "usb"))


if __name__ == "__main__":
    unittest.main()
