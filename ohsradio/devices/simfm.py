"""Broadcast FM stations on the simulated air: shack_sdr's own FM stereo and
RDS test transmitter (`_native.testsig_wfm`, ohs-libs rust/shack_sdr
`wfm::tx`), each a loop placed on its frequency by the simulator's
synthesis bank - so stereo, RDS and the band scanner can be heard end to
end with no radio, in the band simulator (sim.py puts BAND on Band II) and
in the tests (tests/listen_helpers.py, tests/test_ham_bandscan.py).

**Made at the channel rate, placed by the bank.** A station is the BS.450
multiplex (pilot, L-R, RDS from real groups) at the rate of the bank's
wide FM channel (240 kS/s at 1.2 and 2.4 MS/s), and the synthesis bank
(ohscore/dsp/bank.py Source) puts it on its frequency at the simulator's
rate, as every other simulated station is put on the air. Made straight at
2.4 MS/s instead, a 3 s loop is 58 MB a station; at 240 kS/s it is 5.8 MB
and 0.17 s of one core to make, once per process.

**The loop's seam** restarts the transmitter's RDS groups and its tones
once every LOOP_S: the receiver loses RDS sync there for a few groups,
which a real station never asks of it, and is otherwise unbroken. 3 s
holds a programme service name twice and the radiotext once over, which is
what the band scan waits for (measured with shack_sdr 0.2.0, 72ced6a).

The stations in BAND are fictional: names and PI codes made up for the
simulator, on frequencies chosen to exercise the scanner - one programme
on two frequencies (its alternative, weaker), a mono station, a stereo one
with no RDS at all.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from ohscore.dsp.bank import Source

LOOP_S = 3.0
CHANNEL_RATE = 240_000.0        # the bank's wide FM channel; what the transmitter makes
CUTOFF = 110_000.0              # the station's filter in the bank: its 180 kHz channel with RDS and room
EDGE = 120_000.0                # a station this near the edge of the span is not drawn


@dataclass
class FmStation:
    """One transmitter: `hz`, carrier `level_db` dBFS, RDS (`pi` None: none),
    stereo with a `left_hz` tone in L and `right_hz` in R (0: silent)."""
    hz: float
    level_db: float = -40.0
    pi: int | None = None
    ps: str = ""
    rt: str = ""
    pty: int = 0
    stereo: bool = True
    left_hz: float = 1000.0
    right_hz: float = 0.0
    seed: int = 1
    # Made on first use; per simulator rate (the bank's channel rate there).
    _loops: dict = field(default_factory=dict, repr=False)

    def loop(self, rate: float) -> np.ndarray | None:
        """The station at `rate`, unit RMS times its level; None without shack_sdr."""
        z = self._loops.get(rate)
        if z is not None:
            return z
        from ohscore import sdr
        m = sdr.load()
        if m is None:
            return None
        kw = {"pi": self.pi} if self.pi is not None else {"pi": None}
        if self.pi is not None:
            kw.update(ps=f"{self.ps:<8.8}", rt=self.rt or "", pty=int(self.pty))
        raw = m._native.testsig_wfm(seconds=LOOP_S, rate=float(rate), left_hz=float(self.left_hz),
                                    right_hz=float(self.right_hz), pilot=bool(self.stereo), seed=int(self.seed),
                                    **kw)
        z = np.frombuffer(raw, np.complex64)
        z = (z / np.sqrt(np.mean(np.abs(z) ** 2)) * np.float32(10 ** (self.level_db / 20))).astype(np.complex64)
        self._loops[rate] = z
        return z


# The simulator's Band II (sim.py): fictional stations, see the docstring.
# Levels are carrier dBFS; the simulator's floor is -112 dBFS/Hz, about -60
# dBFS in a 180 kHz channel, so the weakest here is 13 dB over it - enough
# for RDS (shack_sdr reads PS down to 10 dB) and for the scan (10 dB).
BAND = (
    FmStation(88_600_000.0, -38.0, 0xC201, "SIM ONE", "Sim One: a tone of 1 kHz left, 1.5 kHz right", 10,
              True, 1000.0, 1500.0, seed=1),
    FmStation(91_300_000.0, -47.0, 0xC201, "SIM ONE", "Sim One: a tone of 1 kHz left, 1.5 kHz right", 10,
              True, 1000.0, 1500.0, seed=2),
    FmStation(93_500_000.0, -44.0, 0xC3B4, "SIMNEWS", "The news, read by nobody", 1, False, 700.0, 0.0, seed=3),
    FmStation(97_700_000.0, -46.0, None, stereo=True, left_hz=440.0, right_hz=880.0, seed=4),
    FmStation(100_400_000.0, -41.0, 0xC5C1, "CLASSIC", "A quiet piece in A", 14, True, 440.0, 440.0, seed=5),
    FmStation(104_900_000.0, -44.0, 0xC6D2, "SIMROCK", "Loud, in stereo", 11, True, 2000.0, 500.0, seed=6),
)


class FmBand:
    """Stations for a simulator to add to what it receives (sim.py
    _generate): `feeds()` gives the synthesis bank its sources for one
    render, made on a worker for a simulator in real time (it must not
    stall its receive thread) and at once otherwise."""

    def __init__(self, stations=BAND):
        self.stations = list(stations)
        self._src: dict[int, Source] = {}
        self._k: dict[int, int] = {}
        self._geo = None
        self._making: set[int] = set()
        self._lock = threading.Lock()

    def _rate(self, geo) -> tuple[int, float]:
        d = geo.decimation_for(CHANNEL_RATE)
        return d, geo.fs / d

    def feeds(self, geo, rx_if: float, m: int, background: bool) -> list:
        """The (Source, samples) pairs for an m-frame render at receiver
        centre `rx_if`. Every station's own clock advances whether or not it
        is in view, so one that comes into view is where it would be."""
        if geo is not self._geo:
            self._geo, self._src, self._k = geo, {}, {}
        d, rate = self._rate(geo)
        out = []
        for i, st in enumerate(self.stations):
            src = self._src.get(i)
            if src is None:
                src = self._src[i] = Source(geo, d, cutoff=CUTOFF)
                self._k[i] = 0
            n = m * src.hop
            k = self._k[i]
            self._k[i] = k + n
            off = st.hz - rx_if
            if abs(off) > geo.fs / 2 - EDGE:
                continue
            z = st._loops.get(rate)
            if z is None:
                self._make(st, i, rate, background)
                z = st._loops.get(rate)
                if z is None:
                    continue
            src.freq = off
            idx = (k + np.arange(n)) % len(z)
            out.append((src, z[idx]))
        return out

    def _make(self, st: FmStation, i: int, rate: float, background: bool) -> None:
        if not background:
            st.loop(rate)
            return
        with self._lock:
            if i in self._making:
                return
            self._making.add(i)

        def run():
            try:
                st.loop(rate)
            except Exception:  # noqa: BLE001 - a broken model costs the simulated station, never the simulator
                pass
            with self._lock:
                self._making.discard(i)
        threading.Thread(target=run, name="sim-fm", daemon=True).start()
