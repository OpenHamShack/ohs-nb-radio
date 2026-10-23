"""Wide FM for broadcast listening (87.5-108 MHz): mono, at Radio's audio rate.

Why numpy here and not shack_sdr's Rust (RADIO-SDR-PLAN §0): every
demodulator Radio runs today - SSB, CW and AM (demod.py), narrowband FM
(fm.py) - is numpy in ohscore on the engine's receive thread, fed from the
one filter bank. WFM is one more of those, so it lives beside them and
takes its channel from the same bank. M3 moves the bank and the broadcast
demodulators (this, stereo, RDS) into shack_sdr together, when the audio
contract becomes 48 kHz stereo; this module is what that port has to
match.

The path, each step chosen to stay vectorised over a block:

- **Channel:** the bank's channel at the smallest decimation giving at
  least WFM_RATE (240 kS/s: D = 5 at 1.2 MS/s, D = 10 at 2.4), its lowpass
  at HALF_WIDTH (90 kHz) either side: Carson's rule for broadcast,
  2 x (75 kHz deviation + 15 kHz audio) = 180 kHz. The bank's filter is
  V+1 taps at the full rate, a ~1 kHz transition, so what the channel
  passes is what `passband()` reports and the scopes draw.
- **Discriminator:** angle(x[n] conj(x[n-1])), scaled so a full 75 kHz
  deviation is 1.0. That is the composite (MPX) signal - mono L+R to
  15 kHz, the 19 kHz pilot, L-R around 38 kHz, RDS at 57 kHz - and
  `composite()` hands it out at the channel rate, which is where stereo
  (a pilot PLL) and RDS will tap in later without touching the mono path.
- **De-emphasis and decimation in one filter:** the one-pole de-emphasis
  (50 us in Europe, 75 us in the Americas: the `wfmDeemphasis` setting) is
  its impulse response as an FIR, convolved into the decimator's lowpass,
  so one FFT overlap-save pass (multirate.Decimator) does both and takes
  the composite straight down to 12 kHz. The decimator's stopband starts
  at 0.58 of the audio rate, 90 dB down, so the pilot, L-R and RDS never
  fold into the audio. Mono audio is therefore flat to about 5 kHz: 12 kHz
  mono is the engine's audio contract everywhere (DESIGN.md), and the full
  15 kHz waits for M3's 48 kHz stereo.
- **DC:** a 20 Hz high-pass at the audio rate, so a dial a few kHz off
  the station does not put a DC step on every retune; music keeps its
  bass.

No squelch: a broadcast listener wants the station, and the noise
between stations is how an operator knows the dial is between stations.
"""
from __future__ import annotations

import math

import numpy as np

from ..i18n.text import _
from .fir import OlsFilter
from .fm import highpass
from .multirate import Decimator, design

WFM_RATE = 240_000.0        # the least channel rate that holds the 180 kHz channel with room for its skirts
HALF_WIDTH = 90_000.0       # the channel filter's -6 dB edge, either side of the dial (Carson)
DEVIATION = 75_000.0        # broadcast peak deviation: the composite's full scale
AUDIO_RATE = 12_000.0
DEEMPHASIS_US = (50.0, 75.0)
LEVEL = 0.5                 # full deviation comes out at this amplitude, as narrowband FM's does (fm.py)


def deemphasis_taps(tau_us: float, rate: float) -> np.ndarray:
    """The one-pole de-emphasis lowpass's impulse response at `rate`,
    unity at DC, long enough (12 time constants) that what is cut off is
    under -100 dB."""
    a = math.exp(-1.0 / (tau_us * 1e-6 * rate))
    k = np.arange(int(12 / (1 - a)))
    h = (1 - a) * a ** k
    return h / h.sum()


def audio_taps(m: int, tau_us: float, rate: float) -> np.ndarray:
    """De-emphasis then the ratio-m decimation lowpass, as one filter at
    `rate`, padded so the Decimator's frames step by whole output samples."""
    h = np.convolve(design(m), deemphasis_taps(tau_us, rate))
    pad = (-(len(h) - 1)) % m
    return np.concatenate([h, np.zeros(pad)])


def can_receive(channel_rate: float) -> bool:
    """Whether a channel at `channel_rate` S/s holds a WFM station and
    divides down to the audio rate."""
    m = channel_rate / AUDIO_RATE
    return channel_rate >= WFM_RATE - 1e-6 and abs(m - round(m)) < 1e-9


class WfmDemod:
    """Complex channel at `rate` (>= WFM_RATE, a multiple of 12 kHz) in,
    12 kHz mono audio out (float32, a full-deviation tone at LEVEL), plus
    the channel's power in dBFS for the S-meter."""

    def __init__(self, rate: float, tau_us: float = 50.0):
        if not can_receive(rate):
            raise ValueError(_("Wide FM needs a channel of at least {least:g} S/s in whole multiples of "
                               "{audio:g} S/s; {rate:g} S/s was given").format(least=WFM_RATE, audio=AUDIO_RATE,
                                                                               rate=rate))
        self.rate = float(rate)
        self.m = int(round(rate / AUDIO_RATE))
        self.prev = np.complex64(1.0)
        self.scale = np.float32(rate / (2 * np.pi) / DEVIATION)
        self.dc = OlsFilter(highpass(20.0, AUDIO_RATE, 40.0).astype(np.complex128))
        self.tau_us = None
        self.down: Decimator | None = None
        self.set_deemphasis(tau_us)

    def set_deemphasis(self, tau_us: float) -> None:
        tau_us = float(tau_us)
        if tau_us == self.tau_us:
            return
        # A new decimator starts with empty history: a few milliseconds of
        # silence at the change, which only ever happens when the operator
        # changes the setting.
        self.tau_us = tau_us
        self.down = Decimator(self.m, audio_taps(self.m, tau_us, self.rate))

    def composite(self, x: np.ndarray) -> np.ndarray:
        """The discriminator's output at the channel rate, deviation-
        normalised (75 kHz = 1.0): the MPX signal stereo and RDS start from."""
        x = np.asarray(x, np.complex64)
        if not len(x):
            return np.zeros(0, np.float32)
        prevs = np.concatenate([[self.prev], x[:-1]])
        self.prev = x[-1]
        return (np.angle(x * np.conj(prevs)).astype(np.float32) * self.scale).astype(np.float32)

    def __call__(self, x: np.ndarray) -> tuple[np.ndarray, float]:
        x = np.asarray(x, np.complex64)
        if not len(x):
            return np.zeros(0, np.float32), -200.0
        p = float(np.mean(np.abs(x) ** 2))
        mpx = self.composite(x)
        y = self.down(mpx.astype(np.complex64)).real
        y = self.dc(y.astype(np.complex64)).real
        return (y * np.float32(LEVEL)).astype(np.float32), 10 * math.log10(p + 1e-20)
