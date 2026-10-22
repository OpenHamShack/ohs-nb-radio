"""The simulator's middle beacon: real AO-40 blocks of text, so beacon lock
has the same BPSK to follow and the middle beacon's text view can be
built, shown and tested end to end with no dish.

It is laid out the way DK0SB's is on the air (ohsnb/dsp/ao40.py, measured
on Brian's recording of 07/10): an uncoded block, its fill, a 5200-symbol
stretch where DK0SB sends an AO-40 FEC frame, the fill again - one block
every 25.4 s, types K, L, M, N in turn. The FEC frame is a stand-in of
random symbols (nothing here decodes FEC), which also gives the decoder
the real beacon's 13 s of non-text to sit through without a false block.

What the blocks say is the simulator's own and says so: the real text is
DK0SB's, and a screenshot of the simulator must not pass for a recording.
"""
from __future__ import annotations

import numpy as np

from ohscore.devices import simsignals as sg

from ..dsp import ao40

BLOCKS = [
    ("K", ["OPENHAMSHACK NB SIMULATOR - not DK0SB"]),
    ("L", ["OPENHAMSHACK NB SIMULATOR - not DK0SB",
           "This is the simulated transponder's middle beacon. The real one",
           "sends DK0SB's text in these same AO-40 blocks: K, L, M and N,",
           "one every 25 seconds, each eight lines of 64 characters.",
           "",
           "QO-100 NB: 10489.500-10490.000 MHz down, 2400.000-2400.500 up.",
           "Keep your downlink below the beacon."]),
    ("M", ["OPENHAMSHACK NB SIMULATOR - not DK0SB",
           "Beacons: lower 10489.500 (CW, F1A), middle 10489.750 (400 bit/s",
           "BPSK, this one), multimedia 10489.995 (8APSK), upper 10490.000.",
           "",
           "Beacon lock follows this beacon by default; its text decodes",
           "once beacon lock has the receive error within a few hundred Hz."]),
    ("N", ["OPENHAMSHACK NB SIMULATOR - not DK0SB",
           "Emergency frequency: downlink 10489.860 MHz, uplink 2400.360 MHz.",
           "SSB, 2.7 kHz at most. Monitor it; keep it clear for emergencies."]),
]


def blocks() -> list[bytes]:
    return [ao40.block_text(kind, lines) for kind, lines in BLOCKS]


_TEMPLATE: np.ndarray | None = None


def template() -> np.ndarray:
    """The beacon's 12 kHz complex baseband loop (~102 s), RMS 1. Always the
    same (its own fixed generator for the FEC stand-in), so it is made once
    per process and shared: every simulator in a test run would otherwise
    build its own 10 MB copy."""
    global _TEMPLATE
    if _TEMPLATE is None:
        rng = np.random.default_rng(400)
        parts = []
        for b in blocks():
            parts.append(ao40.frame_bits(b))
            parts.append(rng.integers(0, 2, ao40.FEC_SYMBOLS).astype(np.uint8))
            parts.append(np.unpackbits(np.frombuffer(ao40.FILL_BYTES, np.uint8)))
        _TEMPLATE = ao40.modulate_bits(np.concatenate(parts), sg.RATE)
        _TEMPLATE.setflags(write=False)
    return _TEMPLATE


__all__ = ["BLOCKS", "blocks", "template"]
