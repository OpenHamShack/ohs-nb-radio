"""Radio's CW decoder never reads keying inside out; NB's still does.

QO-100's F1A beacons are heard inside out at the old bookmark, and NB's
decoder turns them over (shack_cw Decoder stage 5). Radio has no F1A
signals, and on 17 m an NCDXF beacon's fading 1 s dashes turned the
decoder over for the next station ("CS3B" read "I*ETV T", ohs-libs
shack_cw.corpus), so Radio builds its decoder with polarity=False
(Engine.CW_POLARITY). Each app's own engine builds the decoder here, in CW
mode, and it is fed the beacon at the old bookmark.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib
import tempfile
import unittest

import ham_helpers
import helpers
from ohscore import shacklibs

shacklibs.cw()
bench = importlib.import_module("shack_cw.bench")


def bookmark_audio():
    """QO-100's lower beacon heard at the old bookmark (its space tone on
    the 700 Hz pitch), 15 dB over the noise, as 12 kHz receiver audio."""
    import numpy as np
    z = bench.render(bench.beacon_runs(2), np.random.default_rng(0), 15.0, f1a=True,
                     space_hz=bench.PITCH, mark_hz=bench.PITCH + 400)
    return np.concatenate(list(bench.demodulate(z)))


def decoder_of(radio):
    """The decoder the engine built for CW, taken off the engine so the
    simulator's audio does not reach it while the test feeds its own."""
    radio.start()
    try:
        ham_helpers.pump(radio, 5.0, until=lambda: radio.decoder is not None)
        dec = radio.decoder
    finally:
        radio.stop()
    dec.reset()
    return dec


def heard(dec) -> str:
    audio = bookmark_audio()
    for i in range(0, len(audio), 900):
        dec.feed(audio[i:i + 900], 0.0)
    return dec.text


class CwPolarityTests(unittest.TestCase):
    def test_radio_does_not_turn_keying_over(self):
        r = ham_helpers.make_radio(mode="cw")
        try:
            dec = decoder_of(r)
        finally:
            r._tmp.cleanup()
        self.assertIsNotNone(dec)
        self.assertNotIn("QO100", heard(dec).replace(" ", ""))

    def test_nb_still_reads_the_beacon_at_the_old_bookmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = helpers.make_radio(tmp, mode="cw")
            dec = decoder_of(r)
        self.assertIsNotNone(dec)
        self.assertIn("QO100", heard(dec).replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
