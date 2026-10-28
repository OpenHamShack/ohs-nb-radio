"""A DMR repeater on the simulated air: shack_sdr's DMR test transmitter
(`_native.testsig_dmr`, ohs-libs rust/shack_sdr `dmr::tx`) playing its
showcase over and over on a 70 cm channel, so a DMR decoder session can be
seen end to end with no radio - both timeslots busy at once, talker alias,
an encrypted call and an SMS - in the band simulator (sim.py) and the
tests (tests/test_ham_dmr.py).

**The showcase** (shack_sdr README "DMR") is about 7.7 s of a repeater: on
slot 1 a talkgroup call with a talker alias, then an SMS; on slot 2,
overlapping it, a private call and then an encrypted one. Its IDs are
under country code 999, which no country has, and its callsigns are
fictional, as every simulated station's are.

**Made at the channel rate, placed by the bank**, as simfm.py's stations
are: the transmitter makes 48 kS/s, the synthesis bank puts it on its
frequency at the simulator's rate. The loop's seam falls on idle bursts,
so a receiver loses at most a burst there.

**No voice without mbelib.** The transmitter's voice frames are test
vectors, not speech: with mbelib installed they decode to a buzz, which
is what a session listened to plays. Calls, IDs, alias and the SMS need
nothing installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .simfm import FmBand

CHANNEL_RATE = 48_000.0
# A DMR channel is 12.5 kHz: the station's filter in the bank keeps its
# 4FSK (about +-5 kHz) with room.
CUTOFF = 7_000.0
EDGE = 10_000.0
# The simulator's repeater: a UK 70 cm DMR repeater channel (output
# 439.6125, input 9 MHz below); colour code 1.
FREQ = 439_612_500.0
COLOUR_CODE = 1


@dataclass
class DmrStation:
    """A DMR repeater: `hz`, carrier `level_db` dBFS, colour code `cc`."""
    hz: float
    level_db: float = -55.0
    cc: int = COLOUR_CODE
    seed: int = 1
    _loops: dict = field(default_factory=dict, repr=False)

    def loop(self, rate: float) -> np.ndarray | None:
        """The repeater at `rate`, unit RMS times its level; None without shack_sdr."""
        z = self._loops.get(rate)
        if z is not None:
            return z
        from ohscore import sdr
        m = sdr.load()
        if m is None or not hasattr(m._native, "testsig_dmr"):
            return None
        z = np.frombuffer(m._native.testsig_dmr(rate=float(rate), cc=int(self.cc), seed=int(self.seed)), np.complex64)
        z = (z / np.sqrt(np.mean(np.abs(z) ** 2)) * np.float32(10 ** (self.level_db / 20))).astype(np.complex64)
        self._loops[rate] = z
        return z


# -55 dBFS: the simulator's floor is -112 dBFS/Hz, -71 dBFS in 12.5 kHz,
# so 16 dB of C/N - comfortably decoded, as a local repeater is.
REPEATERS = (DmrStation(FREQ),)


class DmrBand(FmBand):
    """The DMR repeaters for a simulator (sim.py _generate), through
    simfm.py's machinery at DMR's channel rate."""

    channel_rate = CHANNEL_RATE
    cutoff = CUTOFF
    edge = EDGE
    thread_name = "sim-dmr"

    def __init__(self, stations=REPEATERS):
        super().__init__(stations)
