"""The simulator's KG-STV station: a real KG-STV transmission, so the
picture receiver (ohsnb/kgstvrx.py) and its view can be built, shown and
tested end to end with no dish.

It is sent the way DL4CQ's and DG8RP's were on Brian's recording of 07/10
(ohscore/dsp/kgstv.py): the 01 preamble, the callsign five times, the 300
blocks in order with the callsign after every tenth, the end frame -
MSK, uncoded, at 10489.6249 MHz USB. Then 15 s of nothing, and again.

What it sends is the simulator's own and says so: a test card (colour bars,
a grey ramp) from "OPENHAMSHACK-SIM", which no screenshot can pass off as a
picture somebody sent. Scale index 12 keeps it near the shortest a picture
can be (about 75 s: most of a frame is its sync and header).
"""
from __future__ import annotations

import numpy as np

from ohscore.devices import simsignals as sg

from ohscore.dsp import kgstv

CALL = "OPENHAMSHACK-SIM"
SCALE = 12
GAP_S = 15.0
BARS = [(235, 235, 235), (235, 235, 16), (16, 235, 235), (16, 235, 16), (235, 16, 235), (235, 16, 16),
        (16, 16, 235), (16, 16, 16)]


def card() -> np.ndarray:
    img = np.zeros((kgstv.HEIGHT, kgstv.WIDTH, 3), np.uint8)
    w = kgstv.WIDTH // len(BARS)
    for i, c in enumerate(BARS):
        img[:160, i * w:(i + 1) * w] = c
    img[160:200] = (np.arange(kgstv.WIDTH) * 255 // (kgstv.WIDTH - 1))[None, :, None]
    img[200:] = (30, 30, 60)
    return img


_TEMPLATE: np.ndarray | None = None


def template() -> np.ndarray:
    """The station's 12 kHz complex baseband loop (~90 s), the tones'
    centre at 0 Hz, unit amplitude while sending. Made once per process."""
    global _TEMPLATE
    if _TEMPLATE is None:
        x = kgstv.modulate(kgstv.transmission_bits(CALL, card(), sc=SCALE), sg.RATE)
        _TEMPLATE = np.concatenate([x, np.zeros(int(GAP_S * sg.RATE), np.complex64)])
        _TEMPLATE.setflags(write=False)
    return _TEMPLATE


__all__ = ["CALL", "SCALE", "card", "template"]
