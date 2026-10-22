"""FFT overlap-save filter bank: every narrow channel the engine needs from
one forward FFT of the wideband stream, and the inverse (synthesis) for the
transmitter and the simulator.

Why this and not an NCO + polyphase decimator per channel: the receiver runs
five or six channels at once (VFO audio, zoom scope, two beacon trackers,
the beacon search, the TX monitor) off a 1.2 MS/s stream on a Raspberry Pi.
An NCO per channel costs a complex exp and multiply per wideband sample per
channel before any filtering. Here the wideband stream is FFT'd once per
frame; each channel then costs a slice of bins, a multiply by its filter and
a *small* inverse FFT at its own output rate - the decimation is free, and
the channel filter can be thousands of taps long at no extra cost.

Geometry (for fs = 1.2 MS/s): N = fs/50 = 24000-point frames (20 ms), hop
L = 3N/4 = 18000, overlap V = N/4 = 6000, so channel filters may be up to
V+1 = 6001 taps at fs (~1 kHz transition). A channel decimates by any D
dividing both N and L: D = 5, 6, 10, 20, 50, 100, 300 give 240, 200, 120, 60,
24, 12 and 4 kHz output.

Frequency placement is to the nearest bin (fs/N = 50 Hz); the residual is a
cheap NCO at the channel's output rate. Phase is carried frame to frame so a
channel behaves like a continuous-phase mixer even while its frequency moves
(beacon lock nudges the VFO channel every half second).
"""
from __future__ import annotations

import math

import numpy as np

from .fir import kaiser_beta

TWO_PI = 2 * math.pi


class Geometry:
    def __init__(self, fs: float):
        self.fs = float(fs)
        self.N = int(round(fs / 50.0))
        if self.N % 4 or abs(self.N * 50.0 - fs) > 1e-6:
            raise ValueError(f"sample rate {fs} must be a multiple of 200 Hz")
        self.L = 3 * self.N // 4
        self.V = self.N - self.L
        self.df = self.fs / self.N

    def decimations(self) -> list[int]:
        return [d for d in range(1, self.L + 1) if self.N % d == 0 and self.L % d == 0]

    def decimation_for(self, rate: float) -> int:
        """Largest D whose output rate fs/D is at least `rate`."""
        best = 1
        for d in self.decimations():
            if self.fs / d >= rate - 1e-9:
                best = d
        return best

    def filter_response(self, d: int, cutoff_hz: float, atten_db: float = 80.0) -> np.ndarray:
        """Frequency response, in FFT bin order, of a V+1-tap Kaiser lowpass at
        fs, restricted to the N/D bins a channel of decimation D keeps. Unity
        at DC; the analysis side scales it by 1/D (a small inverse FFT over N/D
        bins), the synthesis side by D (zero-stuffing spreads the energy)."""
        ntaps = self.V + 1
        n = np.arange(ntaps) - (ntaps - 1) / 2.0
        h = 2 * cutoff_hz / self.fs * np.sinc(2 * cutoff_hz / self.fs * n) * np.kaiser(ntaps, kaiser_beta(atten_db))
        h /= h.sum()
        H = np.fft.fft(h, self.N)
        nd = self.N // d
        idx = np.fft.fftfreq(nd, 1.0 / nd).astype(int) % self.N
        return H[idx]


def default_cutoff(rate: float) -> float:
    # Keep the -6 dB point a ~1 kHz transition inside the output Nyquist so
    # what aliases back is already 80 dB down; at the 4 kHz beacon rate that
    # leaves +-1.5 kHz, ample for a beacon.
    return max(rate * 0.5 - 600.0, rate * 0.3) if rate <= 24_000 else rate * 0.42


class Analysis:
    """The forward half: buffers the wideband stream and FFTs whole frames.
    `push(x)` returns the spectra of every frame completed by x (m x N) and
    the global index of each frame's first sample; channels consume them."""

    def __init__(self, geo: Geometry):
        self.g = geo
        self.buf = np.zeros(geo.V, np.complex64)   # starts with V samples of silence
        self.base = -geo.V                           # global index of buf[0]

    def push(self, x: np.ndarray):
        g = self.g
        self.buf = np.concatenate([self.buf, np.asarray(x, np.complex64)])
        m = (len(self.buf) - g.V) // g.L
        if m <= 0:
            return np.zeros((0, g.N), np.complex64), np.zeros(0, np.int64)
        frames = np.lib.stride_tricks.sliding_window_view(self.buf[: m * g.L + g.V], g.N)[:: g.L]
        X = np.fft.fft(frames, axis=1)
        starts = self.base + np.arange(m, dtype=np.int64) * g.L
        self.buf = self.buf[m * g.L:]
        self.base += m * g.L
        return X.astype(np.complex64, copy=False), starts


class Channel:
    """One output channel of the analysis bank: centre `freq` Hz relative to
    the wideband stream's DC, decimation `d`, lowpass `cutoff` Hz."""

    def __init__(self, geo: Geometry, d: int, freq: float = 0.0, cutoff: float | None = None):
        if geo.N % d or geo.L % d:
            raise ValueError(f"decimation {d} does not divide the frame geometry")
        self.g, self.d = geo, d
        self.rate = geo.fs / d
        self.nd = geo.N // d
        self.keep0 = geo.V // d
        self.freq = float(freq)
        self.cutoff = cutoff if cutoff is not None else default_cutoff(self.rate)
        self.H = (geo.filter_response(d, self.cutoff) / d).astype(np.complex64)
        self.off = np.fft.fftfreq(self.nd, 1.0 / self.nd).astype(np.int64)
        self.psi = 0.0     # LO phase at the first kept sample of the next frame
        self.j = np.arange(geo.L // d)

    def set_freq(self, f: float):
        self.freq = float(f)

    def _ramp(self, r: float) -> np.ndarray:
        if getattr(self, "_ramp_r", None) != r:
            self._ramp_r = r
            self._ramp_v = np.exp(-1j * TWO_PI * r * self.d / self.g.fs * self.j).astype(np.complex64)
        return self._ramp_v

    def take(self, X: np.ndarray, starts: np.ndarray) -> np.ndarray:
        g = self.g
        m = X.shape[0]
        if m == 0:
            return np.zeros(0, np.complex64)
        k = int(round(self.freq / g.df))
        r = self.freq - k * g.df
        idx = (k + self.off) % g.N
        y = np.fft.ifft(X[:, idx] * self.H, axis=1)[:, self.keep0:]
        # Per frame: e^{-j(psi_m - 2 pi k V/N + 2 pi r j D/fs)} - see the
        # module docstring; psi advances by 2 pi f L/fs per frame.
        psis = self.psi + TWO_PI * self.freq * g.L / g.fs * np.arange(m)
        # The channel filter is linear phase, V/2 samples of delay, and it
        # works on the signal shifted to bin k, before the residual r is
        # taken out - so whatever it passes comes out turned by 2 pi r V/2
        # /fs that a mixer-then-filter would not turn it by. Constant while
        # r is, it is invisible; when the frequency crosses a bin boundary r
        # jumps by fs/N and the output's phase by pi/4 (at V = N/4). Beacon
        # lock nudges channels across boundaries; the multimedia beacon's
        # carrier loop lost two frames to each such jump.
        base = psis - TWO_PI * ((k * g.V) % g.N) / g.N - TWO_PI * r * (g.V / 2) / g.fs
        # exp(a + b) = exp(a) exp(b): m + n complex exps instead of m x n.
        y = y * np.exp(-1j * base)[:, None].astype(np.complex64) * self._ramp(r)[None, :]
        self.advance(m)
        return y.reshape(-1).astype(np.complex64)

    def advance(self, m: int) -> None:
        """Move the LO phase on by m frames at the current frequency, as
        take() does after producing them - and nothing else. Split out so
        ohsnb.analyse can start a channel part way through a recording
        (one time slice of a parallel --analyse) with exactly the phase a
        channel that had processed every earlier frame would have: the
        output's phase depends on the whole frequency history, so a slice
        that only warmed up on recent samples would come out rotated by
        an arbitrary angle, and the SSB audio a decoder hears would not be
        the same waveform. Replaying this one line per earlier block is
        cheap; replaying it with different arithmetic would not be exact,
        hence one method both paths call."""
        self.psi = float((self.psi + TWO_PI * self.freq * self.g.L / self.g.fs * m) % TWO_PI)


class Source:
    """One low-rate stream to be placed in the wideband output by `Synthesis`:
    decimation `d` (its rate is fs/d), centre `freq` Hz from DC, linear `gain`."""

    def __init__(self, geo: Geometry, d: int, freq: float = 0.0, cutoff: float | None = None, gain: float = 1.0):
        if geo.N % d or geo.L % d:
            raise ValueError(f"decimation {d} does not divide the frame geometry")
        self.g, self.d = geo, d
        self.rate = geo.fs / d
        self.nd, self.hop = geo.N // d, geo.L // d
        self.freq, self.gain = float(freq), gain
        cutoff = cutoff if cutoff is not None else default_cutoff(self.rate)
        self.H = (geo.filter_response(d, cutoff) * d).astype(np.complex64)
        self.off = np.fft.fftfreq(self.nd, 1.0 / self.nd).astype(np.int64)
        self.hist = np.zeros(self.nd - self.hop, np.complex64)
        self.psi = 0.0
        self.jj = np.arange(self.nd) * d - geo.V     # sample offsets from frame's first output sample

    def spectra(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """FFTs of the m frames covering x (len m*hop), already placed:
        returns (bin indices, m x nd spectra) to be added to the wideband
        frame spectra."""
        g = self.g
        x = np.asarray(x, np.complex64)
        m = len(x) // self.hop
        buf = np.concatenate([self.hist, x[: m * self.hop]])
        self.hist = buf[len(buf) - (self.nd - self.hop):]
        frames = np.lib.stride_tricks.sliding_window_view(buf, self.nd)[:: self.hop][:m]
        k = int(round(self.freq / g.df))
        r = self.freq - k * g.df
        psis = self.psi + TWO_PI * self.freq * g.L / g.fs * np.arange(m)
        # As in Channel.take: the residual r is put in before the V/2-sample
        # filter, which turns it by 2 pi r V/2 /fs; undone here, or a source
        # crossing a bin boundary (the simulator's drifting stations, our
        # own transmitter as TX lock moves it) jumps pi/4 in phase.
        base = psis - TWO_PI * ((k * g.V) % g.N) / g.N + TWO_PI * r * (g.V / 2) / g.fs
        if getattr(self, "_ramp_r", None) != r:
            self._ramp_r = r
            self._ramp_v = np.exp(1j * TWO_PI * r / g.fs * self.jj).astype(np.complex64)
        rot = np.exp(1j * base)[:, None].astype(np.complex64) * self._ramp_v[None, :]
        F = np.fft.fft(frames * rot, axis=1) * (self.H * self.gain)
        self.psi = float((self.psi + TWO_PI * self.freq * g.L / g.fs * m) % TWO_PI)
        return (k + self.off) % g.N, F


class Synthesis:
    """The inverse half: low-rate sources in, one wideband stream out. Each
    `render` produces m*L samples from m*hop new samples per source, plus an
    optional wideband spectrum to add per frame (the simulator's noise)."""

    def __init__(self, geo: Geometry):
        self.g = geo

    def render(self, m: int, feeds: list[tuple[Source, np.ndarray]], extra: np.ndarray | None = None) -> np.ndarray:
        g = self.g
        S = np.zeros((m, g.N), np.complex64) if extra is None else extra
        for src, x in feeds:
            idx, F = src.spectra(x)
            S[:, idx] += F
        y = np.fft.ifft(S, axis=1)[:, g.V:]
        return y.reshape(-1).astype(np.complex64)
