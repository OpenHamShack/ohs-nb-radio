"""Receive demodulation at the 12 kHz channel rate.

The VFO channel arrives from the filter bank already centred on the dial
frequency (the carrier for SSB, the zero-beat point for CW) and lowpassed to
about +-5 kHz. Selectivity is a second, sharp filter here: a complex one-sided
bandpass, so USB, LSB and CW are the same operation with different edges, and
the real part of what it passes is the audio (no product detector, no BFO
mixing - the passband already sits at audio frequency). There is no squelch:
QO-100 is a quiet linear transponder and an operator wants to hear the band.
"""
from __future__ import annotations

import numpy as np

from .agc import Agc
from .fir import OlsFilter, bandpass_complex, kaiser_taps, lowpass

RATE = 12_000.0
DIGITAL_FILTER = (100.0, 3200.0)


def passband(mode: str, lo: float, hi: float, cw_pitch: float, cw_width: float, am_width: float) -> tuple[float, float]:
    """The receive passband in Hz relative to the dial, for display and for
    the demodulator. Digital modes use a fixed wide filter: decoders want to
    see the whole 3 kHz audio window whatever the voice filter is set to."""
    if mode == "lsb":
        return -hi, -lo
    if mode == "cw":
        return cw_pitch - cw_width / 2, cw_pitch + cw_width / 2
    if mode == "am":
        return -am_width, am_width
    if mode == "fm":
        # A 12.5 kHz channel (OpenHamShack Radio's FM is demodulated by ohscore/dsp/fm.py,
        # not here; this is what the scopes draw).
        return -6250.0, 6250.0
    if mode in ("usb",):
        return lo, hi
    return DIGITAL_FILTER


class Demod:
    def __init__(self, rate: float = RATE):
        self.rate = rate
        self.mode = None
        self.edges = None
        self.filter: OlsFilter | None = None
        self.agc = Agc(rate)
        self.agc_on = True
        self.fixed_gain = 1.0
        self.dc = 0.0
        # What the last call multiplied its audio by (the AGC's per-sample
        # gain, or the fixed gain with AGC off): the noise reduction undoes
        # it to see the noise at a steady level.
        self.gain = None

    def configure(self, mode: str, lo: float, hi: float, agc: str = "medium", rf_gain_db: float = 0.0):
        if (mode, lo, hi) != (self.mode, *(self.edges or (None, None))):
            width = hi - lo
            # Transition ~1/8 of the width, between 40 and 200 Hz: a 100 Hz CW
            # filter needs a steep skirt; a 2.4 kHz SSB filter does not need
            # 2000 taps to have one.
            trans = min(200.0, max(40.0, width / 8))
            n = min(kaiser_taps(trans, self.rate, 70.0), 2047)
            if mode == "am":
                taps = lowpass(hi, self.rate, n, 70.0).astype(np.complex128)
            else:
                taps = bandpass_complex(lo, hi, self.rate, n, 70.0)
            if self.filter is None:
                self.filter = OlsFilter(taps)
            else:
                self.filter.set_taps(taps)
            self.mode, self.edges = mode, (lo, hi)
        self.agc_on = agc != "off"
        if self.agc_on:
            self.agc.set_preset(agc)
        self.fixed_gain = 10 ** (rf_gain_db / 20)

    def __call__(self, iq: np.ndarray) -> tuple[np.ndarray, float]:
        """Audio (float32) and the passband power in dBFS for the S-meter."""
        y = self.filter(iq)
        p = float(np.mean(np.abs(y) ** 2)) if len(y) else 0.0
        if self.mode == "am":
            env = np.abs(y)
            # Slow DC removal: carrier level tracked per block, not per sample.
            self.dc = 0.9 * self.dc + 0.1 * float(env.mean()) if len(env) else self.dc
            a = (env - self.dc).astype(np.float32)
        else:
            a = y.real.astype(np.float32)
        if self.agc_on:
            a = self.agc(a)
            self.gain = self.agc.gain
        else:
            a = a * self.fixed_gain
            self.gain = self.fixed_gain
        return a.astype(np.float32), 10 * np.log10(p + 1e-20)


class NoiseBlanker:
    """Impulse blanker on the wideband stream: zero samples far above the
    block's mean magnitude (and two either side, to take the whole pulse)."""

    def __init__(self, threshold: float = 8.0):
        self.threshold = threshold
        self.mean = None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        mag = np.abs(x)
        m = float(np.median(mag)) * 1.25 + 1e-12   # median: the pulses must not set their own threshold
        self.mean = m if self.mean is None else 0.8 * self.mean + 0.2 * m
        hit = mag > self.threshold * self.mean
        if not hit.any():
            return x
        hit = hit | np.roll(hit, 1) | np.roll(hit, -1) | np.roll(hit, 2) | np.roll(hit, -2)
        y = x.copy()
        y[hit] = 0
        return y
