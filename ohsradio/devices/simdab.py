"""A DAB ensemble on the simulated air: shack_sdr's own DAB transmitter
model (`_native.testsig_dab`, ohs-libs rust/shack_sdr `dab::tx`), replayed
as a loop on one Band III block, so a DAB session can be heard end to end
with no radio - in the band simulator (sim.py puts one on 11D) and in the
listening tests (tests/listen_helpers.py).

What is on it is the transmitter model's test ensemble, "Shack Test Mux"
(C1CE): "Shack MP2 Tone" (C221, old DAB, MPEG Layer II, a 1 kHz tone on the
left and 1.5 kHz on the right, with programme text) and "Shack DAB+ Data"
(C3A7, DAB+, which plays only where faad2 is installed). Two transmitters
send it, as in a single-frequency network: their TII codes are two real
Sound Digital sites' (SITES), and the model's EId, C1CE, happens to be
Sound Digital's too, so the transmitter lookup (ohsradio/dabtx.py) names
them from the bundled Ofcom list - Crystal Palace, and Wrotham 8 dB down.
With a shack_sdr that has it, the ensemble is the model's showcase
(`testsig_dab(showcase_mjd=)`): the same two services, and everything
DAB's data side shows - a slide in each service's X-PAD, a programme type
and language for each, DL Plus on C221, and an SPI service whose logos
and programme guide (today's, UTC) come a few seconds after a service
starts playing.

**Made once, then replayed.** The model builds every layer from the audio
up to OFDM and costs about 0.1 s of CPU per 96 ms frame, so it cannot run
live beside the simulator: LOOP_FRAMES frames are made once per process
(about 2.5 s, on a worker thread for a simulator running in real time) at
DAB's own 2.048 MS/s and brought to the simulator's rate by an FFT
resampler. The loop is exactly LOOP_FRAMES frames long - the model's
lead-in is cut off, so the loop starts on a frame's null symbol - and an
FFT treats its input as periodic, so the resampled loop joins itself with
no seam beyond the one the model's counters make (each pass restarts the
CIF counter and the programme text): the session resyncs there once a
pass, which a real receiver never asks of it, and is otherwise unbroken.
24 frames (2.3 s) is long enough for the programme text to complete
within the second pass (measured with shack_sdr 0.2.0, a45dab2).

Why not a recorded fixture: 2.3 s of IQ is 19 MB as complex64 and still
5 MB as 8-bit, for a signal the wheel the app already vendors can make in
the time a test takes to start.
"""
from __future__ import annotations

import threading
import time

import numpy as np

LOOP_FRAMES = 24
# (TII main, sub, delay us, gain dB) of each transmitter: Sound Digital's
# Crystal Palace and Wrotham (Ofcom's list). A shack_sdr before TII takes
# no `sites`, and gets one transmitter with no TII.
SITES = [(11, 1, 0.0, 0.0), (1, 7, 60.0, -8.0)]
FRAME_S = 0.096                 # DAB mode I: one transmission frame
DAB_RATE = 2_048_000.0          # the rate the model makes, DAB's elementary rate
HALF_WIDTH = 768_000.0          # half the 1.536 MHz block

_lock = threading.Lock()
_base: np.ndarray | None = None
_at_rate: dict[float, np.ndarray] = {}
_mjd: int | None = None          # the day the cached loop's EPG was built for


def available() -> bool:
    """Whether this installation can make the signal (shack_sdr's wheel)."""
    from ohscore import sdr
    return sdr.load() is not None


def built_mjd() -> int | None:
    """The MJD `loop()` baked into the cached ensemble's SPI schedule
    (None before any `loop()` has built one). The schedule is for this one
    calendar day, fixed at build time from the wall clock, so a caller
    that will later ask "what is on now" against real wall-clock time
    (ohscore.dabpics.DabPictures's default clock) needs to know which day
    that is - a long test still running past midnight otherwise finds the
    schedule a day behind (test_ham_dab_pictures.py OverTheApi, 29/10)."""
    return _mjd


def loop(fs: float) -> np.ndarray | None:
    """The ensemble's loop at `fs`, unit RMS, made on first use (blocks for
    a few seconds then; cached for the process). None without shack_sdr."""
    global _base, _mjd
    fs = float(fs)
    with _lock:
        if fs in _at_rate:
            return _at_rate[fs]
        if _base is None:
            from ohscore import sdr
            m = sdr.load()
            if m is None:
                return None
            from shack_sdr import _native
            mjd = int(time.time() // 86_400) + 40_587
            # The newest shack_sdr first; each older one lacks one more.
            for kw in ({"sites": SITES, "showcase_mjd": mjd}, {"sites": SITES}, {}):
                try:
                    raw = _native.testsig_dab(frames=LOOP_FRAMES, rate=DAB_RATE, **kw)
                    break
                except TypeError:
                    continue
            z = np.frombuffer(raw, np.complex64)
            per = int(round(FRAME_S * DAB_RATE))
            z = z[len(z) - LOOP_FRAMES * per:]          # the lead-in off: whole frames from a null symbol
            _base = (z / np.sqrt(np.mean(np.abs(z) ** 2))).astype(np.complex64)
            _mjd = mjd
        n = len(_base)
        m_len = int(round(n * fs / DAB_RATE))
        if m_len == n:
            out = _base
        else:
            # Periodic FFT resampling: the loop's spectrum, zero-padded (up)
            # or cut (down) about DC, and back. A rate below 2.048 MS/s
            # loses the block's edges, as such a receiver would.
            spec = np.fft.fft(_base)
            new = np.zeros(m_len, np.complex128)
            h = min(n, m_len) // 2
            new[:h] = spec[:h]
            new[-h:] = spec[-h:]
            out = (np.fft.ifft(new) * (m_len / n)).astype(np.complex64)
        _at_rate[fs] = out
        return out


class DabEnsemble:
    """The test ensemble on `block` at `level_db` dBFS (its RMS over the
    block's 1.536 MHz), for a simulator to add to what it receives."""

    def __init__(self, block: str = "11D", level_db: float = -35.0):
        from ohscore import sdr
        self.block = block
        self.centre = float(sdr.load().dab.block_centre(block))
        self.amp = np.float32(10 ** (level_db / 20))
        self.ready = threading.Event()
        self._loops: dict[float, np.ndarray] = {}
        self._making = False

    def in_view(self, rx_if: float, fs: float) -> bool:
        """Whether any of the block falls inside a receiver at `rx_if`, `fs`."""
        return abs(self.centre - rx_if) - HALF_WIDTH < fs / 2

    def prepare(self, fs: float, background: bool) -> None:
        """Make the loop for `fs` now, or on a worker (a simulator in real
        time must not stall its receive thread for the few seconds it takes)."""
        if fs in self._loops or self._making:
            return
        if not background:
            self._made(fs)
            return
        self._making = True
        threading.Thread(target=self._made, args=(fs,), name="sim-dab", daemon=True).start()

    def _made(self, fs: float) -> None:
        try:
            z = loop(fs)
        except Exception:  # noqa: BLE001 - a broken model costs the simulated block, never the simulator
            z = None
        if z is not None:
            self._loops[fs] = z
        self._making = False
        self.ready.set()

    def take(self, k: int, n: int, fs: float, rx_if: float) -> np.ndarray | None:
        """`n` samples from absolute sample `k` as a receiver centred at
        `rx_if` hears them, or None while the loop is not made yet. The
        offset's phase runs from sample 0, so consecutive calls join."""
        z = self._loops.get(float(fs))
        if z is None:
            return None
        idx = (k + np.arange(n)) % len(z)
        off = self.centre - rx_if
        rot = np.exp(2j * np.pi * off * ((k + np.arange(n, dtype=np.float64)) / fs)) if off else 1.0
        return (z[idx] * rot * self.amp).astype(np.complex64)

    # The listening tests' Station interface (tests/listen_helpers.py):
    # complex baseband at the receiver's centre over absolute times `t`.
    def iq(self, t: np.ndarray, rx_if: float) -> np.ndarray:
        fs = 1.0 / float(t[1] - t[0]) if len(t) > 1 else DAB_RATE
        fs = float(round(fs))
        self.prepare(fs, background=False)
        out = self.take(int(round(t[0] * fs)), len(t), fs, rx_if)
        return out if out is not None else np.zeros(len(t), np.complex64)
