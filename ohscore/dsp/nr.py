"""Receive noise reduction: WDSP's "NR2" (EMNR), ported to numpy.

Port of emnr.c from WDSP 2.10 (TAPR/OpenHPSDR-wdsp b02d5bac), the DSP
library behind Thetis, piHPSDR and linHPSDR:
    Copyright (C) 2015, 2025, 2026 Warren Pratt, NR0V
    WDSP is free software under the GNU General Public License, version 2
    or (at your option) any later version; this file is under version 3 or
    later, as is the rest of OpenHamShack (packaging/copyright and
    packaging/windows/THIRD-PARTY.txt carry the notice).
The gain tables in nr_tables.npz are WDSP's GG and GGS (calculus.c,
Copyright (C) 2026 Warren Pratt), extracted by tools/nr-tables.py.

What it is: short-time spectral noise reduction. Each frame of audio is
windowed and transformed; every bin gets a gain from its a-posteriori SNR
(this frame's power over the noise estimate) and a decision-directed
a-priori SNR (Ephraim & Malah); the gains are smoothed across frequency
when the frame looks like noise, and the frame is transformed back and
overlap-added. The options WDSP offers are fixed here at WDSP's own
defaults (RXA.c's create_emnr call, and what Thetis's NR2 shows first):

- gain method 2 ("Gamma"): the gain is read from WDSP's precomputed
  tables, GG(gamma, xi) times the speech-presence factor GGS(gamma, xi/(1-q)),
  interpolated bilinearly on a 0.25 dB grid. Methods 0/1 compute the
  MMSE-STSA/LSA gains in closed form per bin (Bessel functions, E1) and
  method 3 needs a trained table; neither is the default.
- noise estimator 0: Martin's optimal-smoothing minimum statistics (OSMS)
  - smoothed periodogram, bias-compensated minimum over ~1.5 s in U
  sub-windows of V frames, with the noise-slope limit that lets it rise.
- artifact elimination (aepf) on: the musical-noise smoothing. When a
  frame's gains say it is mostly noise (zeta below 0.75), the gain curve is
  averaged across up to 2*psi+1 = 41 neighbouring bins, so isolated bins
  that poke above the estimate ("musical" tones) are pulled down to their
  neighbours instead of chirping.
- WDSP's post2 (comfort noise added back) is off by default there and is
  not ported.

Framing: WDSP runs 4096-point frames, 4x overlap, at Thetis's 48 kHz - 85 ms
frames, 11.7 Hz bins. Here audio is 12 kHz and arrives in multiples of 180
samples (the filter bank's 15 ms hops, 900 per 75 ms block), so the frame
is 720 samples with 4x overlap (hop 180): every block is a whole number of
hops, which keeps the added latency at its minimum, fsize - hop = 540
samples (45 ms). 1024-point frames (WDSP's 11.7 Hz bins exactly) would
need a hop that does not divide the block, and so 85 ms of latency; on
the tests' speech in noise (tests/test_nr.py) they measured within 0.3 dB
of 720's segmental SNR, so the shorter delay won. WDSP's time constants are all written as "per 128
samples at 8 kHz" and converted with the hop and rate, so they mean the
same seconds here.

Strength (the one control besides on/off, 0-100 %) is an attenuation
limit: the gain applied is floor + (1 - floor) * WDSP's gain, with the
floor 0 dB at 0 % (exactly transparent) falling 0.4 dB per percent to
-40 dB at 100 %. It is applied after the estimator, so the noise estimate
and the decision-directed recursion are WDSP's whatever the strength; only
how far a noise bin is pulled down changes. Why that and not WDSP's own
knobs: over-subtraction or a different q change what is judged speech,
and at low settings start eating weak syllables; a floor only ever leaves
more of the original, so turning it down can never make speech worse.
40 dB because WDSP's gains seldom go lower in practice (on noise alone,
gamma near 1 and xi near -22 dB, the tables give about -33 dB), so 100 %
is WDSP as it stands, and dB-linear because that is how loudness
is heard: each 10 % takes the same 4 dB more off the noise.

No per-sample Python loop: the transforms of every frame in a block are
one numpy call each way; the recursions (noise estimate, decision-directed
SNR) run once per frame, 67 times a second, each a few dozen numpy
operations over the 361 bins.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

RATE = 12_000.0
# Modes whose audio is listened to rather than decoded. In every other mode
# NR is bypassed (exactly), whatever its switch says: an operator listening
# to FT8 or PSK wants to hear what the decoder hears.
NR_MODES = frozenset({"usb", "lsb", "cw", "am", "fm"})

_TABLES = Path(__file__).with_name("nr_tables.npz")
_GG = _GGS = None


def _tables():
    global _GG, _GGS
    if _GG is None:
        # Flat: one np.take per corner is the cheapest gather numpy has,
        # and the lookups were nearly half the processor's time.
        with np.load(_TABLES) as t:
            _GG, _GGS = t["GG"].astype(np.float64).ravel(), t["GGS"].astype(np.float64).ravel()
    return _GG, _GGS


def _grid(v: np.ndarray):
    """Position on WDSP's getKey grid: 0.001..1000 (-30..+30 dB), 4 points
    per dB, clamped at the edges; returns (lower index, fraction). Clamping
    the lower index at 239 (WDSP clamps both to 240 at the top) gives the
    same value with the fraction at 1, without a special case."""
    pos = np.clip(40.0 * np.log10(np.maximum(v, 1e-300)) + 120.0, 0.0, 240.0)
    i = np.minimum(pos.astype(np.int64), 239)
    return i, pos - i


def _lookup(T: np.ndarray, g: tuple, x: tuple) -> np.ndarray:
    """WDSP's getKey: bilinear interpolation in the 241 x 241 table T
    (rows xi, columns gamma) at grid positions g (gamma) and x (xi)."""
    g1, dg = g
    x1, dx = x
    k = x1 * 241 + g1
    a, b = np.take(T, k), np.take(T, k + 1)
    c, d = np.take(T, k + 241), np.take(T, k + 242)
    return (1 - dx) * (a + dg * (b - a)) + dx * (c + dg * (d - c))


def _interp_m(x: float) -> float:
    """WDSP's interpM over its M(D) table (Martin's bias correction), log-x."""
    D = [1.0, 2.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0, 40.0, 60.0, 80.0, 120.0, 140.0, 160.0, 180.0, 220.0, 260.0,
         300.0]
    M = [0.000, 0.260, 0.480, 0.580, 0.610, 0.668, 0.705, 0.762, 0.800, 0.841, 0.865, 0.890, 0.900, 0.910, 0.920,
         0.930, 0.935, 0.940]
    if x <= D[0]:
        return M[0]
    if x >= D[-1]:
        return M[-1]
    i = next(i for i in range(1, len(D)) if x <= D[i])
    f = (math.log10(x) - math.log10(D[i - 1])) / (math.log10(D[i]) - math.log10(D[i - 1]))
    return M[i - 1] + f * (M[i] - M[i - 1])


def strength_floor(strength: float) -> float:
    """The gain floor for a strength in percent (see the module docstring)."""
    s = min(100.0, max(0.0, float(strength))) / 100.0
    return 10.0 ** (-40.0 * s / 20.0)


class Emnr:
    """The processor: audio in, audio out, `latency` samples later.

    `quantum` is the length every call's input is a multiple of; the
    latency is the least that lets every call return as many samples as it
    was given (fsize minus the largest hop multiple both share)."""

    def __init__(self, rate: float = RATE, fsize: int = 720, ovrlp: int = 4, quantum: int = 180):
        self.rate, self.fsize, self.ovrlp = float(rate), int(fsize), int(ovrlp)
        self.incr = self.fsize // self.ovrlp
        self.msize = self.fsize // 2 + 1
        self.latency = self.fsize - math.gcd(int(quantum), self.incr)
        self.floor = 0.0
        self.GG, self.GGS = _tables()
        # sqrt-Hamming at both ends, as WDSP; periodic, so the squared
        # windows at hop N/4 sum to exactly 4 * 0.54 and the reconstruction
        # is exact (WDSP's own normalisation is within 4 % of it, which
        # matters there only to the overall gain).
        n = np.arange(self.fsize)
        self.window = np.sqrt(0.54 - 0.46 * np.cos(2 * np.pi * n / self.fsize))
        self.ola_gain = 1.0 / (self.ovrlp * 0.54)
        self.hist = np.zeros(self.fsize - self.incr)        # input not yet consumed by a whole frame
        self.acc = np.zeros(self.fsize - self.incr)          # overlap-add: the hops still being summed
        self.out = np.zeros(self.latency - (self.fsize - self.incr))  # output FIFO, primed to the latency
        self.frames = 0
        self._init_constants()
        self.ready = False

    # ------------------------------------------------------------ set-up
    def _tc(self, per128_at_8k: float) -> float:
        """WDSP writes its smoothing constants as the factor per 128 samples
        at 8 kHz; this is the same time constant per hop at our rate."""
        tau = -128.0 / 8000.0 / math.log(per128_at_8k)
        return math.exp(-self.incr / self.rate / tau)

    def _init_constants(self):
        r, incr = self.rate, self.incr
        # Gain (calc_emnr's g.*).
        self.alpha = self._tc(0.985)            # decision-directed a-priori SNR smoothing
        self.eps_floor = 1.0e-300
        self.gamma_max = 40.0
        self.q = 0.2                            # a-priori probability of speech absence
        # Minimum statistics (np.*).
        self.alphaCsmooth = self._tc(0.7)
        self.alphaMax = self._tc(0.96)
        self.alphaCmin = self._tc(0.7)
        self.alphaMin_max = self._tc(0.3)
        self.snrq = -incr / (0.064 * r)
        self.betamax = self._tc(0.8)
        self.invQeqMax = 0.5
        self.av = 2.12
        Dtime = 8.0 * 12.0 * 128.0 / 8000.0     # 1.536 s minimum-search window
        U = 8
        V = max(4, int(0.5 + Dtime * r / (U * incr)))
        U = max(1, int(0.5 + Dtime * r / (V * incr)))
        self.U, self.V, self.D = U, V, U * V
        self.MofD, self.MofV = _interp_m(self.D), _interp_m(self.V)
        self.invQbar_points = (0.03, 0.05, 0.06)
        span = 12.0 * 128 / 8000
        self.nsmax = [10.0 ** (10 * math.log10(f) / span / 10.0 * V * incr / r) for f in (8.0, 4.0, 2.0, 1.2)]
        # Artifact elimination (ae.*).
        self.zetaThresh = 0.75
        self.psi = 20.0

    def _init_state(self, ly: np.ndarray):
        """WDSP starts every estimate at 0.5 - a level that suits its own
        audio scale and nothing else. The NR here sees audio at whatever
        level the receiver hands it (before the AGC), so the estimates
        start from the first whole frame's periodogram, smoothed across
        frequency so one frame's chance dips and peaks do not seed it."""
        k = 9
        c = np.concatenate([[0.0], np.cumsum(ly)])
        i = np.arange(self.msize)
        lo, hi = np.maximum(0, i - k), np.minimum(self.msize, i + k + 1)
        start = np.maximum((c[hi] - c[lo]) / (hi - lo), 1e-30)
        m = self.msize
        self.p = start.copy()
        self.sigma2N = start.copy()
        self.pbar = start.copy()
        self.p2bar = start * start
        self.pmin_u = start.copy()
        self.actmin = np.full(m, 1e300)
        self.actmin_sub = np.full(m, 1e300)
        self.actminbuff = np.full((self.U, m), 1e300)
        self.lmin_flag = np.zeros(m, bool)
        self.alphaC = 1.0
        self.subwc = self.V
        self.amb_idx = 0
        self.prev_mask = np.ones(m)
        self.prev_gamma = np.ones(m)
        self.ready = True

    # ------------------------------------------------------------ per frame
    def _noise(self, ly: np.ndarray) -> np.ndarray:
        """LambdaD: Martin's minimum statistics, one frame. Returns the
        noise power estimate per bin."""
        p, sigma2N = self.p, self.sigma2N
        f0 = p / sigma2N - 1.0
        alphaOptHat = 1.0 / (1.0 + f0 * f0)
        snr = p.sum() / sigma2N.sum()
        alphaMin = min(self.alphaMin_max, snr ** self.snrq)
        alphaOptHat = np.maximum(alphaOptHat, alphaMin)
        f1 = p.sum() / ly.sum() - 1.0
        alphaCtilda = 1.0 / (1.0 + f1 * f1)
        self.alphaC = self.alphaCsmooth * self.alphaC + (1.0 - self.alphaCsmooth) * max(alphaCtilda, self.alphaCmin)
        alphaHat = self.alphaMax * self.alphaC * alphaOptHat
        p = alphaHat * p + (1.0 - alphaHat) * ly
        self.p = p
        beta = np.minimum(self.betamax, alphaHat * alphaHat)
        self.pbar = beta * self.pbar + (1.0 - beta) * p
        self.p2bar = beta * self.p2bar + (1.0 - beta) * p * p
        varHat = self.p2bar - self.pbar * self.pbar
        # varHat is >= 0 in exact arithmetic; rounding can take it a hair
        # below, where WDSP's 1/invQeq would go negative.
        invQeq = np.clip(varHat / (2.0 * sigma2N * sigma2N), 1e-12, self.invQeqMax)
        Qeq = 1.0 / invQeq
        invQbar = float(invQeq.mean())
        bc = 1.0 + self.av * math.sqrt(invQbar)
        bmin = 1.0 + 2.0 * (self.D - 1.0) / ((Qeq - 2.0 * self.MofD) / (1.0 - self.MofD))
        bmin_sub = 1.0 + 2.0 * (self.V - 1.0) / ((Qeq - 2.0 * self.MofV) / (1.0 - self.MofV))
        cand = p * bmin * bc
        k_mod = cand < self.actmin
        self.actmin = np.where(k_mod, cand, self.actmin)
        self.actmin_sub = np.where(k_mod, p * bmin_sub * bc, self.actmin_sub)
        if self.subwc == self.V:
            if invQbar < self.invQbar_points[0]:
                nsm = self.nsmax[0]
            elif invQbar < self.invQbar_points[1]:
                nsm = self.nsmax[1]
            elif invQbar < self.invQbar_points[2]:
                nsm = self.nsmax[2]
            else:
                nsm = self.nsmax[3]
            self.actminbuff[self.amb_idx] = self.actmin
            pmin_u = self.actminbuff.min(axis=0)
            # lmin_flag is cleared where this frame found a new minimum.
            flag = self.lmin_flag & ~k_mod
            rise = flag & (self.actmin_sub < nsm * pmin_u) & (self.actmin_sub > pmin_u)
            pmin_u = np.where(rise, self.actmin_sub, pmin_u)
            self.actminbuff[:, rise] = self.actmin_sub[rise]
            self.pmin_u = pmin_u
            self.lmin_flag[:] = False
            self.actmin[:] = 1e300
            self.actmin_sub[:] = 1e300
            self.amb_idx = (self.amb_idx + 1) % self.U
            self.subwc = 1
        else:
            if self.subwc > 1:
                self.lmin_flag |= k_mod
                self.sigma2N = np.where(k_mod, np.minimum(self.actmin_sub, self.pmin_u), self.sigma2N)
                self.pmin_u = np.where(k_mod, self.sigma2N, self.pmin_u)
            self.subwc += 1
        return self.sigma2N

    def _gain(self, ly: np.ndarray) -> np.ndarray:
        """calc_gain, method 2, then aepf: the gain per bin for one frame."""
        ld = self._noise(ly)
        gamma = np.minimum(ly / ld, self.gamma_max)
        eps_hat = (self.alpha * self.prev_mask * self.prev_mask * self.prev_gamma
                   + (1.0 - self.alpha) * np.maximum(gamma - 1.0, self.eps_floor))
        g = _grid(gamma)
        mask = _lookup(self.GG, g, _grid(eps_hat)) * _lookup(self.GGS, g, _grid(eps_hat / (1.0 - self.q)))
        self.prev_gamma = gamma
        self.prev_mask = mask
        # aepf: when little of the frame's power survives the gains, it is
        # noise, and the gain curve is smoothed across frequency, more the
        # less survives - musical noise is isolated bins, and averaging
        # them with their neighbours removes it.
        zeta = float((mask * mask * ly).sum() / ly.sum())
        if zeta < self.zetaThresh:
            n = int(0.5 + self.psi * (1.0 - zeta / self.zetaThresh))
            if n:
                k = np.arange(self.msize)
                h = np.minimum(np.minimum(k, self.msize - 1 - k), n)   # windows shrink at the edges, as WDSP's
                c = np.concatenate([[0.0], np.cumsum(mask)])
                mask = (c[k + h + 1] - c[k - h]) / (2 * h + 1)
        return mask

    # ------------------------------------------------------------ stream
    def process(self, x: np.ndarray) -> np.ndarray:
        """`x` (any length; a multiple of the quantum keeps the latency
        exact) -> as many samples out, `latency` samples behind."""
        n = len(x)
        buf = np.concatenate([self.hist, np.asarray(x, np.float64)])
        nf = (len(buf) - (self.fsize - self.incr)) // self.incr
        if nf > 0:
            starts = np.arange(nf) * self.incr
            frames = np.lib.stride_tricks.sliding_window_view(buf, self.fsize)[starts]
            Y = np.fft.rfft(frames * self.window, axis=1)
            P = Y.real ** 2 + Y.imag ** 2 + 1e-30
            G = np.ones((nf, self.msize))
            floor = self.floor
            for j in range(nf):
                # Frames that still hold the zeros this started from would
                # seed the estimate with silence; they pass unchanged (only
                # the latency's worth of start-up output comes from them).
                if self.frames + j < self.ovrlp - 1:
                    continue
                if not self.ready:
                    self._init_state(P[j])
                g = self._gain(P[j])
                G[j] = floor + (1.0 - floor) * g if floor > 0.0 else g
            self.frames += nf
            y = np.fft.irfft(Y * G, self.fsize, axis=1) * (self.window * self.ola_gain)
            # Overlap-add: frame j's quarter p lands on output hop j + p.
            q = self.ovrlp
            parts = y.reshape(nf, q, self.incr)
            acc = np.zeros((nf + q - 1, self.incr))
            acc[:q - 1] = self.acc.reshape(q - 1, self.incr)
            for p in range(q):
                acc[p:p + nf] += parts[:, p]
            done = acc[:nf].ravel()
            self.acc = acc[nf:].ravel()
            self.out = np.concatenate([self.out, done])
            self.hist = buf[nf * self.incr:]
        else:
            self.hist = buf
        if len(self.out) < n:
            # Called with a length that is not a multiple of the quantum:
            # the stream slips by the shortfall rather than stall.
            self.out = np.concatenate([np.zeros(n - len(self.out)), self.out])
        y, self.out = self.out[:n], self.out[n:]
        return y


class NoiseReduction:
    """NR as the receive chain uses it: on/off, strength, the mode gate,
    and click-free switching.

    Off (or in a mode NR does not apply to) and settled, it is an exact
    bypass and costs nothing: the processor is dropped. Switched on, a
    fresh processor starts, and the output stays the untouched audio until
    the processor has filled its latency and had `warmup` seconds to find
    the noise; then it crossfades over `fade` seconds to the processed
    audio. Switched off, it crossfades back the same way. The two paths are
    45 ms apart in time (the processor's latency) and are crossfaded, not
    cut, so the switch is a short blend, never a step in the waveform.

    The processor works on the audio before the AGC: the caller passes the
    AGC's per-sample gain with the audio, the processor sees audio / gain,
    and its output is multiplied by the gain of its own (delayed) samples.
    After the AGC, the noise floor rises tens of dB in every pause as the
    AGC recovers and falls under every word; a minimum-statistics estimator
    follows the quiet end of that, so the noise between words - the part NR
    is for - came through unreduced. Nothing here touches the AGC itself.
    """

    def __init__(self, rate: float = RATE, fade: float = 0.05, warmup: float = 0.3):
        self.rate = rate
        self.fade_n = max(1, int(fade * rate))
        self.warmup_n = int(warmup * rate)
        self.on = False
        self.strength = 50.0
        self.mode = "usb"
        self.proc: Emnr | None = None
        self.mix = 0.0          # 0 = untouched audio, 1 = processed
        self.hold = 0           # samples left before a fade-in may start
        self.gain_fifo = np.zeros(0)

    @property
    def active(self) -> bool:
        return self.on and self.mode in NR_MODES

    def configure(self, on: bool, strength: float, mode: str) -> None:
        self.on, self.strength, self.mode = bool(on), float(strength), mode
        if self.proc is not None:
            self.proc.floor = strength_floor(self.strength)

    def __call__(self, audio: np.ndarray, gain=None) -> np.ndarray:
        """Audio as heard (float32, same length). `gain`: what the AGC (or
        the fixed gain with AGC off) multiplied this audio by - a per-sample
        array, a number, or None for 1."""
        n = len(audio)
        want = self.active
        if self.proc is None:
            if not want or n == 0:
                return audio
            self.proc = Emnr(self.rate)
            self.proc.floor = strength_floor(self.strength)
            self.hold = self.proc.latency + self.warmup_n
            self.gain_fifo = None
        g = np.ones(n) if gain is None else np.broadcast_to(np.asarray(gain, np.float64), (n,))
        if self.gain_fifo is None:
            self.gain_fifo = np.full(self.proc.latency, float(g[0]) if n else 1.0)
        dry = np.asarray(audio, np.float64)
        wet_pre = self.proc.process(dry / g)
        gq = np.concatenate([self.gain_fifo, g])
        wet = wet_pre * gq[:n]
        self.gain_fifo = gq[n:]
        t = np.arange(1, n + 1)
        if want:
            w = np.clip(self.mix + np.maximum(t - self.hold, 0) / self.fade_n, 0.0, 1.0)
            self.hold = max(0, self.hold - n)
        else:
            w = np.clip(self.mix - t / self.fade_n, 0.0, 1.0)
        self.mix = float(w[-1])
        if not want and self.mix == 0.0:
            self.proc = None
        if self.mix == 1.0 and w[0] == 1.0:
            return wet.astype(np.float32)
        s = 0.5 - 0.5 * np.cos(np.pi * w)          # raised-cosine: no corner at either end of the fade
        return (dry + s * (wet - dry)).astype(np.float32)
