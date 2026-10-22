"""Transmit modulation at 12 kHz: audio in, complex USB baseband out.

Chain for voice: mic gain -> speech compressor (a levelling peak follower
allowed to lift quiet syllables by up to `compressor` dB) -> one-sided complex
bandpass 300-2700 Hz (the Hilbert transform and the 2.7 kHz occupied-width
limit in one FIR) -> ALC (peak follower that only ever reduces, so the
envelope never exceeds 0.9) -> a final per-sample scale that guarantees
|z| <= 1 for the DAC. Digital modes and CW skip the compressor - their
encoders already give a constant envelope, and compressing a keyed carrier
would only round its edges into clicks.

Why a complex FIR and not the Weaver method: at 12 kHz the 300-2700 Hz
filter is ~250 taps, which an FFT convolution does in a fraction of a
millisecond per block, and it gives the sideband rejection of the filter
(70 dB) rather than of an analogue-style phasing match.
"""
from __future__ import annotations

import numpy as np

from .agc import PeakGain
from .fir import OlsFilter, bandpass_complex, kaiser_taps

RATE = 12_000.0


class SsbMod:
    def __init__(self, rate: float = RATE):
        self.rate = rate
        self.edges = None
        self.filter: OlsFilter | None = None
        self.mic_gain = 1.0
        self.voice = True
        self.comp = PeakGain(rate, target=0.5, max_gain_db=6.0, min_gain_db=-30.0, hang=0.05, decay_db_s=30.0)
        self.alc = PeakGain(rate, target=0.9, max_gain_db=0.0, min_gain_db=-40.0, hang=0.02, decay_db_s=40.0)
        self.last_peak = 0.0

    def configure(self, lo: float = 300.0, hi: float = 2700.0, mic_gain_db: float = 0.0, compressor_db: float = 6.0,
                  voice: bool = True, sideband: str = "usb"):
        edges = (-hi, -lo) if sideband == "lsb" else (lo, hi)
        if edges != self.edges:
            n = kaiser_taps(120.0, self.rate, 70.0)
            taps = bandpass_complex(edges[0], edges[1], self.rate, n, 70.0)
            if self.filter is None:
                self.filter = OlsFilter(taps)
            else:
                self.filter.set_taps(taps)
            self.edges = edges
        self.mic_gain = 10 ** (mic_gain_db / 20)
        self.comp.max_gain_db = compressor_db
        self.voice = voice

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        a = np.asarray(audio, np.float32)
        if self.voice:
            a = a * self.mic_gain
            if self.comp.max_gain_db > 0:
                a = self.comp(a)
        # Real audio through a one-sided filter keeps only the positive
        # frequencies: half the power, so x2 restores the amplitude.
        z = self.filter(a.astype(np.complex64)) * 2.0
        z = self.alc(z)
        mag = np.abs(z)
        over = mag > 1.0
        if over.any():
            z[over] /= mag[over]
        self.last_peak = float(mag.max()) if len(mag) else 0.0
        return z.astype(np.complex64)


class AmMod:
    """AM (A3E, double sideband with full carrier) at 12 kHz for OpenHamShack Radio
    (NB keeps AM receive-only). Audio is band-limited to `lo`-`hi` Hz, levelled by
    the same ALC as SSB and clipped, so the modulation index never passes
    90 %: the envelope never reaches zero (it bottoms at 10 % of the
    carrier) and the carrier's power is (1 / 1.9)^2 = 28 % of the PEP, the
    usual quarter (design 5.4).

    The PEP sits at PEAK = half of full scale (-6 dBFS), the carrier at
    -11.6 dBFS. Until 06/10/2026 it sat at 0.95 of full scale, and AM was
    the one mode that sounded terrible on the air (Ray on 70 cm, a stock
    Pluto, heard by Brian on an IC-9700 - FM, USB and LSB from the same
    station were fine). Measured in software the AM was clean; what differs
    is where its information lives. An envelope detector hears the
    envelope, so any compression at the transmitter's top end goes straight
    into the audio, and AM drives the envelope to the top on every
    syllable. SSB shrugs the same compression off (a clipped SSB peak is an
    RF speech clipper) and FM has no envelope at all. Through a modelled
    soft saturation at full scale (Rapp, p = 2), a 1 kHz tone came out with
    THD+N -23 dB from AM against no measurable change on USB; an envelope
    clip at 0.7 of full scale took it to -14 dB. At -6 dBFS the same models
    give -45 dB and none. The price is 6 dB of AM PEP at a given Drive,
    which the power estimate (ohsradio/power.py) accounts for; an amplifier
    after the radio supplies the watts in AM as in any mode.

    The low edge matters more here than in SSB: whatever the filter passes
    below speech - DC from the mic, 50 Hz hum, handling rumble - modulates
    the carrier, and the ALC (which may lift by 12 dB) treats it as speech.
    Before it had one (until 05/10/2026), 50 Hz hum at -30 dBFS came out as
    a third of the transmitted audio power, and a DC offset of 0.05 moved
    the carrier 10 % and took the room for speech's downward peaks with it.
    Both edges are one FIR (lowpass(hi) - lowpass(lo), same length, so the
    difference is still linear phase) and DC is exactly zero."""

    INDEX = 0.9
    PEAK = 0.5          # the envelope's peak, of DAC full scale (docstring)

    def __init__(self, rate: float = RATE):
        self.rate = rate
        self.edges = None
        self.filter: OlsFilter | None = None
        self.mic_gain = 1.0
        self.alc = PeakGain(rate, target=0.9, max_gain_db=12.0, min_gain_db=-40.0, hang=0.05, decay_db_s=20.0)
        self.last_peak = 0.0
        self.voice = True

    def configure(self, hi: float = 2700.0, mic_gain_db: float = 0.0, voice: bool = True, lo: float = 300.0):
        if (lo, hi) != self.edges:
            from .fir import lowpass
            n = kaiser_taps(200.0, self.rate, 60.0)
            taps = (lowpass(hi, self.rate, n, 60.0) - lowpass(lo, self.rate, n, 60.0)).astype(np.complex128)
            if self.filter is None:
                self.filter = OlsFilter(taps)
            else:
                self.filter.set_taps(taps)
            self.edges = (lo, hi)
        self.mic_gain = 10 ** (mic_gain_db / 20)
        self.voice = voice

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        a = np.asarray(audio, np.float32) * np.float32(self.mic_gain if self.voice else 1.0)
        m = self.filter(a.astype(np.complex64)).real.astype(np.float32)
        if self.voice:
            m = self.alc(m)
        m = np.clip(m, -1.0, 1.0)
        z = self.PEAK / (1.0 + self.INDEX) * (1.0 + self.INDEX * m)
        # The transmit meter reads how much of AM's own room is used, as for
        # every other mode, not how far below full scale AM is held.
        self.last_peak = float(z.max()) / self.PEAK * 0.95 if len(z) else 0.0
        return z.astype(np.complex64)
