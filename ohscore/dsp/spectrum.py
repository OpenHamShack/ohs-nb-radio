"""Scopes: averaged, windowed power spectra in dBFS.

Normalisation: a complex tone of amplitude A reads 20 log10 A dB at its
bin (window gain divided out), so the wide scope, the zoom scope and the
meters agree on levels. Noise reads lower per bin as bins get narrower, as on
any spectrum analyser.
"""
from __future__ import annotations

import numpy as np

from .fir import _good_size


class Line(tuple):
    """A spectrum feed item, (t, start_hz, bin_hz, db) as ever, so every
    consumer that unpacks four still does; `dc_bins` is (lo, hi), the bins
    of `db` (inclusive) the engine filled in over the receiver's DC spike
    for display, or None (Engine._dc_mask; SERVER-API `dcBins`)."""

    dc_bins = None

class Scope:
    """Lines at `fps` from a stream at `rate`. Each line averages `avg`
    Hann-windowed FFTs of size `nfft` with 50 % overlap, ending at the line's
    time. `process()` returns [(sample_index_of_line_end, power_db_shifted)]
    with DC in the middle (index nfft//2)."""

    def __init__(self, rate: float, nfft: int, fps: float, avg: int):
        self.rate = rate
        self.configure(nfft, fps, avg)
        self.n = 0                     # samples seen
        # The first line waits until the buffer holds `need` real samples.
        # It used to end at sample 0, which made it the FFT of the zeroed
        # buffer: a flat -200 dB line, published at every start and every
        # time the engine rebuilt a scope (a new zoom span, scopeFps or
        # averaging). The scopes take their noise floor from each line, so
        # that one line dragged their scale 100 dB down for seconds.
        self.next_line = float(self.need)

    def configure(self, nfft: int, fps: float, avg: int):
        self.nfft, self.fps, self.avg = int(nfft), float(fps), int(avg)
        self.win = np.hanning(self.nfft + 2)[1:-1].astype(np.float32)
        self.norm = float(self.win.sum()) ** 2
        self.need = self.nfft // 2 * (self.avg + 1)
        self.buf = np.zeros(self.need, np.complex64)

    @property
    def bin_hz(self) -> float:
        return self.rate / self.nfft

    def process(self, x: np.ndarray) -> list[tuple[int, np.ndarray]]:
        x = np.asarray(x, np.complex64)
        start = self.n
        self.n += len(x)
        joined = np.concatenate([self.buf, x])
        self.buf = joined[-self.need:]
        out = []
        period = self.rate / self.fps
        if self.next_line < start:
            self.next_line = float(start)
        while self.next_line <= self.n:
            end = int(self.next_line)          # exclusive: the line covers samples before `end`
            e = len(joined) - (self.n - end)   # joined[-1] is sample n-1
            if e < self.need:
                self.next_line += period
                continue
            seg = joined[e - self.need:e]
            frames = np.lib.stride_tricks.sliding_window_view(seg, self.nfft)[:: self.nfft // 2][: self.avg]
            P = (np.abs(np.fft.fft(frames * self.win, axis=1)) ** 2).mean(axis=0) / self.norm
            out.append((end, np.fft.fftshift(10 * np.log10(P + 1e-20)).astype(np.float32)))
            self.next_line += period
        return out


def wide_nfft(bins: int, fs: float, span: float) -> int:
    return _good_size(int(bins * fs / span))
