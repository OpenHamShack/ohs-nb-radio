"""Integer-ratio decimation and interpolation of wideband IQ, by FFT.

Written for the Pluto whose firmware refuses the AD9361's x4 FIR
(devices/pluto.py): the radio then runs at M x the engine's rate and these
bring it down (receive) and back up (transmit), so nothing above the device
knows. They sit on the full hardware rate - 2.4 MS/s in, on a Pi - so cost
matters more than generality.

Both are overlap-save with the rate change done inside the FFT, which is
what makes them cheap:

- **Decimator**: forward FFT of a full-rate frame, multiply by the filter,
  then fold the spectrum M ways (sum its M sub-bands) and take an inverse FFT
  M times shorter. Folding in frequency is exactly "keep every M-th output"
  in time, so the outputs that would be thrown away are never computed.
- **Interpolator**: the spectrum of a zero-stuffed frame is the low-rate
  frame's spectrum repeated M times, so the forward FFT runs at the low rate
  and only the inverse runs at the full rate.

A direct polyphase form (one numpy pass per tap) was the other candidate,
not built: at 73-145 taps that is 73-145 passes over every block against the
FFT form's two transforms, and a BLAS product would need a taps-wide copy of
the signal.

The filter is one Kaiser lowpass shared by both directions: flat to
PASS x the low rate, PASS_ATTEN dB down from STOP x the low rate. A signal
anywhere in +-PASS*fs keeps its shape; what folds onto it on receive, and
the images of it on transmit, come from beyond STOP*fs, i.e. the stopband.
"""
from __future__ import annotations

import numpy as np

from .fir import _good_size, kaiser_taps, lowpass

PASS = 0.42          # of the low rate: flat to here (1.2 MS/s: +-504 kHz, the transponder and TX reach)
STOP = 0.58          # of the low rate: the stopband starts here (an alias of it lands at 0.42)
ATTEN_DB = 90.0      # Kaiser design target; measured >= 85 dB in tests/test_multirate.py


def design(m: int, atten_db: float = ATTEN_DB) -> np.ndarray:
    """The lowpass for a ratio-m rate change, at the high rate, unity DC
    gain, padded so (len - 1) is a multiple of m (the FFT frames then step by
    whole low-rate samples)."""
    lo = 1.0 / m                                   # the low rate, in units of the high rate
    n = kaiser_taps((STOP - PASS) * lo, 1.0, atten_db)
    h = lowpass((PASS + STOP) / 2 * lo, 1.0, n, atten_db)
    pad = (-(len(h) - 1)) % m
    return np.concatenate([h, np.zeros(pad)])


FRAME = 4096         # FFT length at the high rate (see _nfft)


def _nfft(p: int, m: int) -> int:
    # Measured on x86 at 2.4 MS/s: 2048-8192 cost the same within the
    # noise; 16384 and up cost ~1.5x (out of cache), and a Pi's caches are
    # smaller, so the low end of the flat region. At least 16x the filter
    # keeps the overlap waste to a few per cent. The length must be a
    # multiple of m with an FFT-friendly quotient.
    k = _good_size(max(FRAME // m, -(-16 * p // m)))
    return k * m


class Decimator:
    """Streaming lowpass + keep every m-th sample, complex64 in and out.
    Accepts any block length: a remainder shorter than m waits for the next
    call, so the output grid never slips and there is no seam at block
    boundaries."""

    def __init__(self, m: int, taps: np.ndarray | None = None):
        self.m = int(m)
        h = design(self.m) if taps is None else np.asarray(taps, np.float64)
        self.p = len(h)
        self.nfft = _nfft(self.p, self.m)
        self.k = self.nfft // self.m
        self.step = self.nfft - (self.p - 1)       # a multiple of m (design() pads for it)
        self.skip = (self.p - 1) // self.m
        # The forward FFT is taken with norm="forward" (it divides by nfft):
        # numpy 2.2's pocketfft runs an unscaled complex64 transform 5x
        # slower than a scaled one (measured: 2.9 ms against 0.5 ms for
        # 44 x 4096 points), so the scaling is undone here, once, along with
        # the fold's 1/m.
        self.H = (np.fft.fft(h, self.nfft) * (self.nfft / self.m)).astype(np.complex64)
        self.hist = np.zeros(self.p - 1, np.complex64)
        self.rem = np.zeros(0, np.complex64)
        self.delay = (self.p - 1) / 2              # group delay, in high-rate samples

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.complex64)
        if len(self.rem):
            x = np.concatenate([self.rem, x])
        use = len(x) - len(x) % self.m
        self.rem = x[use:].copy()
        x = x[:use]
        if use == 0:
            return np.zeros(0, np.complex64)
        buf = np.concatenate([self.hist, x])
        nblk = -(-use // self.step)
        need = (nblk - 1) * self.step + self.nfft
        if len(buf) < need:
            buf = np.concatenate([buf, np.zeros(need - len(buf), np.complex64)])
        frames = np.lib.stride_tricks.sliding_window_view(buf, self.nfft)[::self.step][:nblk]
        Y = np.fft.fft(frames, axis=1, norm="forward") * self.H
        fold = Y.reshape(nblk, self.m, self.k).sum(axis=1)
        y = np.fft.ifft(fold, axis=1)[:, self.skip:]
        out = y.reshape(-1)[:use // self.m].astype(np.complex64)
        self.hist = buf[use:use + self.p - 1].copy() if self.p > 1 else self.hist
        return out


class Interpolator:
    """Streaming zero-stuff by m + lowpass, complex64 in and out, unity
    gain: every input sample yields exactly m outputs, so block boundaries
    are invisible."""

    def __init__(self, m: int, taps: np.ndarray | None = None):
        self.m = int(m)
        h = design(self.m) if taps is None else np.asarray(taps, np.float64)
        self.p = len(h)
        self.nfft = _nfft(self.p, self.m)
        self.k = self.nfft // self.m
        self.lstep = (self.nfft - (self.p - 1)) // self.m     # low-rate samples per frame
        self.lhist = (self.p - 1) // self.m
        # x m restores the energy zero-stuffing removes, so a tone keeps its
        # amplitude; x k undoes the forward FFT's norm="forward" (see
        # Decimator for why it is scaled).
        self.H = (np.fft.fft(h, self.nfft) * (self.m * self.k)).astype(np.complex64)
        self.hist = np.zeros(self.lhist, np.complex64)
        self.delay = (self.p - 1) / 2              # group delay, in high-rate samples

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.complex64)
        n = len(x)
        if n == 0:
            return np.zeros(0, np.complex64)
        buf = np.concatenate([self.hist, x])
        nblk = -(-n // self.lstep)
        need = (nblk - 1) * self.lstep + self.k
        if len(buf) < need:
            buf = np.concatenate([buf, np.zeros(need - len(buf), np.complex64)])
        frames = np.lib.stride_tricks.sliding_window_view(buf, self.k)[::self.lstep][:nblk]
        X = np.fft.fft(frames, axis=1, norm="forward")
        Y = np.tile(X, (1, self.m)) * self.H
        y = np.fft.ifft(Y, axis=1)[:, self.p - 1:]
        out = y.reshape(-1)[:n * self.m].astype(np.complex64)
        if self.lhist:
            self.hist = np.concatenate([self.hist, x])[-self.lhist:]
        return out
