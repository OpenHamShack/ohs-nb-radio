"""Wide FM for broadcast listening (87.5-108 MHz): mono for now, at 48 kHz.

Why numpy here and not shack_sdr's Rust (RADIO-SDR-PLAN §0): every
demodulator Radio runs today - SSB, CW and AM (demod.py), narrowband FM
(fm.py) - is numpy in ohscore on the engine's receive thread, fed from the
one filter bank. WFM is one more of those, so it lives beside them and
takes its channel from the same bank. M3 moves the bank and the broadcast
demodulators (this, stereo, RDS) into shack_sdr together, when the audio
contract becomes 48 kHz stereo; this module is what that port has to
match. The 48 kHz half of that contract came first (23/10/2026, Engine
OUT_RATE): Radio plays at 48 kHz, so this already gives the full 15 kHz.

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
  the composite straight down to 48 kHz. That lowpass is this module's own
  (`mono_lowpass`), not multirate's general one: flat to 15 kHz, the mono
  band, and 90 dB down from 18.5 kHz, so the 19 kHz pilot is gone and
  nothing from L-R (23-53 kHz) or RDS (57 kHz) folds below 24 kHz.
  Until 23/10/2026 this went to 12 kHz and was flat to about 5 kHz.
- **DC:** a 20 Hz high-pass at the audio rate, so a dial a few kHz off
  the station does not put a DC step on every retune; music keeps its
  bass. A one-pole DC blocker (`DcBlocker`), not the FIR it was at 12 kHz:
  at 48 kHz a 20 Hz FIR needs 3,500 taps and cost as much as the whole
  demodulator before it (0.9 % of a 6900HX core against 0.1 %).
- **The decoders' 12 kHz:** every decoder and the engine's timing take
  12 kHz mono (Engine docstring), so `for_decoders` brings the heard audio
  down by 4 with multirate's lowpass (flat to 5 kHz), as it was before.
- **Stereo plugs in at `stereo`**: a callable taking the composite at the
  channel rate, as `composite()` gives it, and returning (n, 2) float32 L
  and R at AUDIO_RATE, de-emphasised, at LEVEL for full deviation, with
  `pilot` saying whether it locked. While it is None, or has no pilot, the
  mono path here is what is heard; `channels` says which.

**Since 23/10/2026 Radio hears shack_sdr's receiver instead** (`StereoWfm`,
chosen by `make_demod`): ohs-libs' `wfm.Receiver` takes the same channel
IQ and gives 48 kHz stereo with blend and RDS, all in Rust off the GIL, and
was measured against this module's numbers (README "Broadcast FM"). The
pilot PLL and RDS are loops with memory, so unlike this module it needs
`reset()` on every retune. This module stays as the fallback for an
installation without the shack-sdr wheel (a package built for no platform
in particular), where wide FM is still mono and has no RDS, rather than
no wide FM at all; `stereo` above is how the receiver was first meant to
plug in, kept because nothing else needs changing for it.

No squelch: a broadcast listener wants the station, and the noise
between stations is how an operator knows the dial is between stations.
"""
from __future__ import annotations

import math

import numpy as np

from ..i18n.text import _
from .fir import kaiser_taps, lowpass
from .multirate import Decimator

WFM_RATE = 240_000.0        # the least channel rate that holds the 180 kHz channel with room for its skirts
HALF_WIDTH = 90_000.0       # the channel filter's -6 dB edge, either side of the dial (Carson)
DEVIATION = 75_000.0        # broadcast peak deviation: the composite's full scale
AUDIO_RATE = 48_000.0      # what is heard (the engine's OUT_RATE in Radio)
DECODE_RATE = 12_000.0     # what the decoders get (the engine's AUDIO_RATE)
MONO_PASS = 15_000.0       # the mono (L+R) band: flat to here
MONO_STOP = 18_500.0       # stopband from here: below the 19 kHz pilot
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


def mono_lowpass(rate: float, atten_db: float = 90.0) -> np.ndarray:
    """The mono band's lowpass at the channel rate `rate`: flat to
    MONO_PASS, `atten_db` down from MONO_STOP, unity at DC."""
    n = kaiser_taps(MONO_STOP - MONO_PASS, rate, atten_db)
    return lowpass((MONO_PASS + MONO_STOP) / 2, rate, n, atten_db)


def audio_taps(m: int, tau_us: float, rate: float) -> np.ndarray:
    """De-emphasis then the mono lowpass, as one filter at `rate`, padded
    so the Decimator's frames step by whole output samples (`m` of them)."""
    h = np.convolve(mono_lowpass(rate), deemphasis_taps(tau_us, rate))
    pad = (-(len(h) - 1)) % m
    return np.concatenate([h, np.zeros(pad)])


def can_receive(channel_rate: float) -> bool:
    """Whether a channel at `channel_rate` S/s holds a WFM station and
    divides down to the audio rate."""
    m = channel_rate / AUDIO_RATE
    return channel_rate >= WFM_RATE - 1e-6 and abs(m - round(m)) < 1e-9


class DcBlocker:
    """y[n] = x[n] - x[n-1] + a y[n-1], its corner at `corner` Hz: a
    recursion numpy has no loop-free form of, so each run of at most CHUNK
    samples is solved in closed form, y = a^n (y0 + cumsum(d[k] a^-k)).
    a^-CHUNK stays near e^10 at 20 Hz and 48 kHz, which float64 carries
    with digits to spare."""

    CHUNK = 4096

    def __init__(self, corner: float, rate: float):
        self.a = math.exp(-2 * math.pi * corner / rate)
        k = np.arange(self.CHUNK + 1, dtype=np.float64)
        self.up, self.down = self.a ** k, self.a ** -k
        self.x1 = 0.0
        self.y1 = 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float64)
        out = np.empty(len(x), np.float32)
        for i in range(0, len(x), self.CHUNK):
            c = x[i:i + self.CHUNK]
            m = len(c)
            d = np.diff(c, prepend=self.x1)
            # y[j] = a^(j+1) y1 + sum_{k<=j} a^(j-k) d[k]
            y = self.up[1:m + 1] * self.y1 + self.up[:m] * np.cumsum(d * self.down[:m])
            out[i:i + m] = y
            self.x1, self.y1 = float(c[-1]), float(y[-1])
        return out


class WfmDemod:
    """Complex channel at `rate` (>= WFM_RATE, a multiple of 48 kHz) in,
    48 kHz audio out (float32, a full-deviation tone at LEVEL; mono (n,),
    or (n, 2) when a stereo decoder is plugged in and has the pilot), plus
    the channel's power in dBFS for the S-meter."""

    stereo = None              # the module docstring's stereo hook

    def __init__(self, rate: float, tau_us: float = 50.0):
        if not can_receive(rate):
            raise ValueError(_("Wide FM needs a channel of at least {least:g} S/s in whole multiples of "
                               "{audio:g} S/s; {rate:g} S/s was given").format(least=WFM_RATE, audio=AUDIO_RATE,
                                                                               rate=rate))
        self.rate = float(rate)
        self.m = int(round(rate / AUDIO_RATE))
        self.prev = np.complex64(1.0)
        self.scale = np.float32(rate / (2 * np.pi) / DEVIATION)
        self.dc = DcBlocker(20.0, AUDIO_RATE)
        self.decode_down = Decimator(int(AUDIO_RATE // DECODE_RATE))
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

    def __call__(self, x: np.ndarray, t0: float | None = None) -> tuple[np.ndarray, float]:
        # t0 (the block's UTC) is StereoWfm's, for RDS times; nothing here needs it.
        x = np.asarray(x, np.complex64)
        if not len(x):
            return np.zeros(0, np.float32), -200.0
        p = float(np.mean(np.abs(x) ** 2))
        mpx = self.composite(x)
        level = 10 * math.log10(p + 1e-20)
        st = self.stereo
        if st is not None:
            lr = st(mpx)
            if getattr(st, "pilot", False):
                return np.asarray(lr, np.float32), level
        y = self.down(mpx.astype(np.complex64)).real
        y = self.dc(y)
        return (y * np.float32(LEVEL)).astype(np.float32), level

    @property
    def channels(self) -> int:
        """2 while a stereo decoder hears the pilot, else 1."""
        st = self.stereo
        return 2 if st is not None and getattr(st, "pilot", False) else 1

    def for_decoders(self, heard: np.ndarray) -> np.ndarray:
        """What this block's heard audio gives the decoders: 12 kHz mono."""
        a = np.asarray(heard, np.float32)
        if a.ndim == 2:
            a = a.mean(axis=1, dtype=np.float32)
        return self.decode_down(a.astype(np.complex64)).real.astype(np.float32)

    def reset(self) -> None:
        """A retune: nothing here remembers the last station."""

    def rds(self) -> None:
        """No RDS without shack_sdr."""
        return None

    @property
    def stereo_on(self) -> bool:
        return self.channels == 2


class StereoWfm:
    """shack_sdr's broadcast FM receiver (`wfm.Receiver`) behind WfmDemod's
    interface: channel IQ at `rate` in, 48 kHz audio out - (n, 2) while the
    station is heard in stereo, else mono (n,), so a mono station plays and
    records exactly as WfmDemod's did - with its level for the S-meter,
    plus RDS and the stereo state."""

    def __init__(self, m, rate: float, tau_us: float = 50.0):
        if not can_receive(rate):
            raise ValueError(_("Wide FM needs a channel of at least {least:g} S/s in whole multiples of "
                               "{audio:g} S/s; {rate:g} S/s was given").format(least=WFM_RATE, audio=AUDIO_RATE,
                                                                               rate=rate))
        self.rate = float(rate)
        self.tau_us = float(tau_us)
        self.rx = m.wfm.Receiver(rate=self.rate, deemphasis_us=self.tau_us, audio_rate=int(AUDIO_RATE), channels=2)
        self.decode_down = Decimator(int(AUDIO_RATE // DECODE_RATE))
        self.stereo_on = False

    def set_deemphasis(self, tau_us: float) -> None:
        tau_us = float(tau_us)
        if tau_us != self.tau_us:
            self.tau_us = tau_us
            self.rx.set_deemphasis(tau_us)

    def reset(self) -> None:
        self.rx.reset()
        self.stereo_on = False

    def __call__(self, x: np.ndarray, t0: float | None = None) -> tuple[np.ndarray, float]:
        x = np.asarray(x, np.complex64)
        if not len(x):
            return np.zeros(0, np.float32), -200.0
        level = 10 * math.log10(float(np.mean(np.abs(x) ** 2)) + 1e-20)
        lr = self.rx.process(x, t0)
        # The receiver's own flag (pilot held 150 ms, its hysteresis), not
        # the blend: a station blended to mono on a weak signal is still a
        # stereo station, and the badge and api/status say so.
        self.stereo_on = bool(self.rx.status().get("stereo"))
        if self.stereo_on:
            return np.ascontiguousarray(lr, np.float32), level
        # Without the pilot the matrix gives L = R: the mono path's shape.
        return np.ascontiguousarray(lr[:, 0], np.float32), level

    @property
    def channels(self) -> int:
        return 2 if self.stereo_on else 1

    def rds(self) -> dict | None:
        """The receiver's RDS (shack_sdr README), or None until it has
        decoded a programme identification: a stereo flag alone is not RDS."""
        d = self.rx.rds()
        if d.get("pi") is None:
            return None
        return d

    def status(self) -> dict:
        return self.rx.status()

    def for_decoders(self, heard: np.ndarray) -> np.ndarray:
        a = np.asarray(heard, np.float32)
        if a.ndim == 2:
            a = a.mean(axis=1, dtype=np.float32)
        return self.decode_down(a.astype(np.complex64)).real.astype(np.float32)


def make_demod(rate: float, tau_us: float = 50.0):
    """The wide FM demodulator Radio uses: shack_sdr's stereo receiver with
    RDS where this installation has the wheel, else WfmDemod (mono)."""
    from .. import sdr
    m = sdr.load()
    if m is not None and getattr(m, "wfm", None) is not None:
        return StereoWfm(m, rate, tau_us)
    return WfmDemod(rate, tau_us)
