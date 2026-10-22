"""Morse keying envelopes: used by the simulator's beacons and CW stations,
and as the CW transmit fallback when ohscore.modes has no CW encoder.

They moved to ohs-libs' shack_cw.morse (10/10/2026) with the CW decoder,
so one alphabet serves the keyer, the simulator and the decoder; this
module keeps the names everything here imports. The one difference from
the copy that was here: its table lacked @ ( ) ' and ", which were dropped
from a message, and are now sent.
"""
from __future__ import annotations

from .. import shacklibs

_morse = shacklibs.cw().morse

CODE = _morse.MORSE
runs = _morse.runs
envelope = _morse.envelope
envelope_of = _morse.envelope_of
