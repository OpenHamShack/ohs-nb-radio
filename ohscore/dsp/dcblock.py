"""A very narrow DC blocker for a zero-IF receiver's IQ (Brian, 23/10/2026).

A direct-conversion receiver (an RSP, a Pluto, an RTL-SDR) puts its own DC
offset and LO leakage at 0 Hz of its baseband: a steady carrier at the
exact centre of every capture, on the trace and as a line down the
waterfall, that an operator reads as interference. SDRplay's own DC
correction (dcCal 4, trackTime 63) leaves it standing.

    blk = DcBlocker(fs, corner_hz=5.0)
    y = blk(x)               # x complex64, any block length; state carries across calls
    blk.reset()              # after a retune: the next block seeds the estimate

**First order, one pole.** The DC estimate follows the input,
m[n] = m[n-1] + mu (x[n] - m[n-1]), and the output is x[n] - m[n-1]: a
high-pass whose corner is mu fs / 2 pi. At the default 5 Hz:

- the time constant is 32 ms, so a residue that wanders with temperature,
  gain or a retune is followed within a tenth of a second;
- a signal 1 kHz from the centre is changed by 1 - 1000/sqrt(1000^2 + 5^2):
  0.0001 dB and 0.3 degrees, which no ear, decoder or scope can see; at
  100 Hz it is 0.01 dB. Only a carrier within a few hertz of the exact
  centre is touched, and Radio never puts the dial there (offset tuning,
  ohsradio/radio.py "the DC keep-out");
- a corner of 10 Hz or more would follow faster than the residue ever
  moves (over seconds) and notch more of a slow-fading carrier near the
  centre, for nothing; one below a hertz would leave the residue standing
  for seconds after each retune (reset() helps there, but not with drift).

**Vectorised exactly.** The recurrence is linear, so a block is computed
in closed form with a cumulative sum rather than a Python loop: m[n] =
r^(n+1) m0 + mu sum_k r^(n-k) x[k] with r = 1 - mu. The weights r^(-k) grow
as exp(mu k), so a block is cut into chunks of at most CHUNK_MU / mu
samples to keep them near 1. Any block length gives the same output as
one sample at a time (a test checks it), so the receive thread's block
size is free to change. It costs about 1 % of one 6900HX core at
2.4 MS/s (0.33 ms a 65536-sample block); the first, double-precision
form cost 8 %.
"""
from __future__ import annotations

import math

import numpy as np

CORNER_HZ = 5.0
# mu x chunk length: the largest growth exp(CHUNK_MU) a chunk's weights may
# reach (e^2 = 7.4: no precision lost in a double-precision sum).
CHUNK_MU = 2.0


class DcBlocker:
    def __init__(self, fs: float, corner_hz: float = CORNER_HZ):
        self.fs = float(fs)
        self.corner_hz = float(corner_hz)
        self.mu = min(1.0, 2 * math.pi * self.corner_hz / self.fs)
        self.r = 1.0 - self.mu
        self.m: complex | None = None
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.chunk = max(1, int(CHUNK_MU / self.mu))

    def reset(self) -> None:
        """Forget the estimate: the next block seeds it with its own mean
        (a retune moves a zero-IF receiver's DC at once)."""
        self.m = None

    @property
    def dc(self) -> complex:
        """The DC the blocker is taking out now (0 before the first block)."""
        return 0j if self.m is None else complex(self.m)

    def _weights(self, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        w = self._cache.get(n)
        if w is None:
            k = np.arange(n, dtype=np.float64)
            # r^-k inside the sum; r^(n+1), the decay of the estimate the
            # chunk starts from; and mu r^n, the sum's scale.
            w = ((self.r ** -k).astype(np.float32), (self.r ** (k + 1)).astype(np.float32),
                 (self.mu * self.r ** k).astype(np.float32))
            if len(self._cache) > 8:
                self._cache.clear()
            self._cache[n] = w
        return w

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.complex64)
        if len(x) == 0:
            return x
        if self.m is None:
            self.m = complex(np.mean(x, dtype=np.complex128))
        out = np.empty(len(x), np.complex64)
        for a in range(0, len(x), self.chunk):
            xs = x[a:a + self.chunk]
            n = len(xs)
            inv, decay, scale = self._weights(n)
            # m[n] for every n of the chunk (closed form, module docstring).
            # In single precision: the sum's rounding is multiplied by mu
            # (about 1e-5) on its way into the estimate, so it is far below
            # anything a receiver can show.
            m = np.cumsum(xs * inv)
            m *= scale
            m += decay * np.complex64(self.m)
            # Each sample loses the estimate from before it.
            o = out[a:a + n]
            o[0] = xs[0] - np.complex64(self.m)
            np.subtract(xs[1:], m[:-1], out=o[1:])
            self.m = complex(m[-1])
        return out
