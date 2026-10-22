"""Narrowband FM for the amateur bands: demodulator with noise squelch,
CTCSS decoder, modulator with CTCSS and the 1750 Hz toneburst
(docs/ham/DESIGN-HAM.md section 5.3).

Rates. The receiver takes its FM channel from the filter bank at 24 kS/s
(a decimation every engine geometry has): an NBFM signal with 5 kHz
deviation is ~16 kHz wide, more than the 12 kHz audio channel holds, and
the squelch needs the discriminator's noise above the voice band. Audio
leaves at 12 kHz like every other mode. The transmitter likewise renders
its baseband at 24 kS/s.

Everything is vectorised over a block: the discriminator is
angle(x[n] conj(x[n-1])); de-emphasis is the one-pole lowpass's impulse
response as an FIR (an IIR would be a per-sample loop) and pre-emphasis
its exact two-tap inverse; the squelch decides per 10 ms block (a loop
over ~8 blocks, never over samples) with hysteresis, and ramps between
block decisions so it never clicks.

Emphasis: 6 dB/octave above 300 Hz (a 530 us time constant), the
land-mobile NBFM convention, normalised to unity at 1 kHz.

CTCSS. Tones in Hz. The IARU R1 standard set is the VHF Handbook's FM.24
table (35 tones); the common 50-tone set adds 15 more (a secondary source:
RadioReference's CTCSS page; TIA-603 itself was not read, and whether its
first extra tone is 69.3 or 69.4 Hz is unverified) - docs/ham/
bandplan-r1-uk.md section 5. Receive decodes all 50, so any repeater's
tone is recognised; transmit offers all 50. UK tone letters: ukrepeater.
net's tone image [U1]. The decoder is a bank of single-bin DFTs (Goertzel
filters, computed as one matrix product) over a Hann-windowed second of
the discriminator output decimated to 1200 S/s, evaluated every 0.25 s.
"""
from __future__ import annotations

import math

import numpy as np

from .fir import OlsFilter, kaiser_taps, lowpass
from .multirate import Decimator, Interpolator

IARU_R1 = (67.0, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8,
           123.0, 127.3, 131.8, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8, 179.9, 186.2, 203.5, 210.7, 218.1,
           225.7, 233.6, 241.8, 250.3)
EXTRA_50 = (69.3, 97.4, 136.5, 159.8, 165.5, 171.3, 177.3, 183.5, 189.9, 192.8, 196.6, 199.5, 206.5, 229.1, 254.1)
TONES = tuple(sorted(IARU_R1 + EXTRA_50))
UK_LETTERS = {67.0: "A", 71.9: "B", 77.0: "C", 82.5: "D", 88.5: "E", 94.8: "F", 103.5: "G", 110.9: "H", 118.8: "J"}

FM_RATE = 24_000.0
AUDIO_RATE = 12_000.0
EMPH_HZ = 300.0
TONEBURST_HZ = 1750.0


def tone_name(hz: float) -> str:
    """'G 103.5', '123.0', or 'off'."""
    if not hz:
        return "off"
    letter = UK_LETTERS.get(round(hz, 1))
    return f"{letter} {hz:.1f}" if letter else f"{hz:.1f}"


def _emph_a(rate: float) -> float:
    return math.exp(-2 * math.pi * EMPH_HZ / rate)


def _emph_norm(rate: float) -> float:
    """|pre-emphasis| at 1 kHz, to normalise it to unity there."""
    a = _emph_a(rate)
    w = 2 * math.pi * 1000.0 / rate
    return abs(1 - a * complex(math.cos(w), -math.sin(w))) / (1 - a)


def _real_fir(taps) -> OlsFilter:
    return OlsFilter(np.asarray(taps, np.float64).astype(np.complex128))


def highpass(cut: float, rate: float, transition: float, atten: float = 50.0) -> np.ndarray:
    n = kaiser_taps(transition, rate, atten)
    h = -lowpass(cut, rate, n, atten)
    h[(n - 1) // 2] += 1.0
    return h


class CtcssDetector:
    """Which CTCSS tone, if any, is on a discriminator output (deviation-
    normalised audio). push() at any rate that is an integer multiple of
    1200 S/s; `tone` is 0.0 or the tone heard, updated every 0.25 s."""

    RATE = 1200.0
    WINDOW = 1.0
    EVERY = 0.25

    def __init__(self, in_rate: float = FM_RATE):
        self.m = int(round(in_rate / self.RATE))
        self.pre = Decimator(self.m) if self.m > 1 else None
        n = int(self.RATE * self.WINDOW)
        self.buf = np.zeros(n, np.float32)
        self.filled = 0
        self.since = 0
        w = np.hanning(n)
        t = np.arange(n) / self.RATE
        self.F = (np.exp(-2j * np.pi * np.outer(TONES, t)) * w).astype(np.complex64)
        self.norm = 2.0 / w.sum()
        self.tone = 0.0
        self.level = 0.0

    def reset(self):
        self.buf[:] = 0
        self.filled = 0
        self.tone = 0.0

    def push(self, x: np.ndarray) -> float:
        x = np.asarray(x, np.float32)
        y = self.pre(x.astype(np.complex64)).real if self.pre is not None else x
        k = len(y)
        if k >= len(self.buf):
            self.buf[:] = y[-len(self.buf):]
        elif k:
            self.buf = np.roll(self.buf, -k)
            self.buf[-k:] = y
        self.filled = min(len(self.buf), self.filled + k)
        self.since += k
        if self.since >= self.EVERY * self.RATE and self.filled >= len(self.buf):
            self.since = 0
            self.tone, self.level = self.decide(self.buf)
        return self.tone

    def amplitudes(self, buf: np.ndarray) -> np.ndarray:
        """Each tone's amplitude in the window, in the input's units."""
        b = buf - buf.mean()
        return np.abs(self.F @ b.astype(np.complex64)) * self.norm

    def decide(self, buf: np.ndarray) -> tuple[float, float]:
        a = self.amplitudes(buf)
        i = int(np.argmax(a))
        best = float(a[i])
        others = np.delete(a, [j for j in (i - 1, i, i + 1) if 0 <= j < len(a)])
        floor = float(np.median(others)) + 1e-9
        # A real tone stands 12 dB clear of the bank's median and is at least
        # 3 % of peak deviation (UK practice sends 10-15 %).
        if best > 0.03 and best > 4.0 * floor:
            return TONES[i], best
        return 0.0, best


class FmDemod:
    """24 kS/s complex in, 12 kHz audio out (float32, deviation-normalised:
    a full-deviation tone is amplitude 1), with noise squelch, optional
    tone squelch, and the CTCSS tone heard."""

    def __init__(self, rate: float = FM_RATE, deviation: float = 2500.0):
        self.rate = rate
        self.deviation = deviation
        self.prev = np.complex64(1.0)
        a = _emph_a(rate)
        k = np.arange(int(12 / (1 - a)))
        self.deemph = _real_fir((1 - a) * a ** k * _emph_norm(rate))
        self.hp_noise = _real_fir(highpass(6000.0, rate, 1500.0))
        self.hp_audio = _real_fir(highpass(300.0, AUDIO_RATE, 150.0))
        self.lp_audio = _real_fir(lowpass(3200.0, rate, kaiser_taps(800.0, rate, 50.0), 50.0))
        self.down = Decimator(int(round(rate / AUDIO_RATE)))
        self.ctcss = CtcssDetector(rate)
        self.block = int(rate * 0.010)
        self.noise_left = np.zeros(0, np.float32)
        self.sql_level = 0.5
        self.tone_sql = 0.0
        self.open = False
        self.gain_prev = 0.0
        self.noise = 0.0

    def configure(self, deviation: float, sql_level: float, tone_sql: float):
        self.deviation = float(deviation)
        self.sql_level = float(sql_level)
        self.tone_sql = float(tone_sql or 0.0)

    def threshold(self) -> tuple[float, float]:
        """(open below, close above) on the noise measure (rad/sample rms
        above 6 kHz): pure noise reads ~1.3; a clean carrier ~0."""
        t = 0.02 + 1.1 * (1.0 - self.sql_level)
        return t, t * 1.3

    def __call__(self, x: np.ndarray) -> tuple[np.ndarray, float]:
        x = np.asarray(x, np.complex64)
        if not len(x):
            return np.zeros(0, np.float32), -200.0
        p = float(np.mean(np.abs(x) ** 2))
        prevs = np.concatenate([[self.prev], x[:-1]])
        self.prev = x[-1]
        d = np.angle(x * np.conj(prevs)).astype(np.float32)          # rad/sample
        audio = d * np.float32(self.rate / (2 * np.pi) / self.deviation)
        # Squelch: noise above the voice band, per 10 ms block.
        hp = self.hp_noise(d).real
        blocks = np.concatenate([self.noise_left, hp])
        nb = len(blocks) // self.block
        self.noise_left = blocks[nb * self.block:]
        rms = np.sqrt(np.mean(blocks[:nb * self.block].reshape(nb, self.block) ** 2, axis=1)) if nb else np.zeros(0)
        t_open, t_close = self.threshold()
        gates = np.empty(len(rms))
        state = self.open
        for i, r in enumerate(rms):                       # ~8 blocks per call, not samples
            if self.sql_level <= 0.0:
                state = True
            elif state and r > t_close:
                state = False
            elif not state and r < t_open:
                state = True
            gates[i] = 1.0 if state else 0.0
        if len(rms):
            self.noise = float(rms[-1])
        self.open = state
        tone = self.ctcss.push(audio) if self.open else 0.0
        if not self.open:
            self.ctcss.reset()
        if self.tone_sql and abs(tone - self.tone_sql) > 0.05:
            gates[:] = 0.0
        # Audio: de-emphasis, 3.2 kHz lowpass, down to 12 kHz, CTCSS removed.
        y = self.lp_audio(self.deemph(audio).real).real
        y = self.down(y.astype(np.complex64)).real
        y = self.hp_audio(y).real.astype(np.float32)
        # Gate ramp between block decisions (12 kHz samples).
        n = len(y)
        if len(gates):
            pts = np.linspace(0, n, len(gates) + 1)
            g = np.interp(np.arange(n), pts, np.concatenate([[self.gain_prev], gates]))
            self.gain_prev = float(gates[-1])
        else:
            g = np.full(n, self.gain_prev)
        return (y * g * 0.5).astype(np.float32), 10 * math.log10(p + 1e-20)

    @property
    def tone(self) -> float:
        return self.ctcss.tone if self.open else 0.0


class FmMod:
    """12 kHz audio in, 24 kS/s constant-envelope baseband out. Voice is
    high-passed at 300 Hz (room for the CTCSS tone), pre-emphasised, clipped
    to full deviation and low-passed at 3 kHz; the CTCSS tone and a 1750 Hz
    toneburst are added after the clipper so they keep their level.
    `last_peak` is the modulation peak (deviation used, 0..1)."""

    def __init__(self, rate: float = FM_RATE):
        self.rate = rate
        self.up = Interpolator(int(round(rate / AUDIO_RATE)))
        a = _emph_a(rate)
        self.a = a
        self.pre_norm = 1.0 / ((1 - a) * _emph_norm(rate))
        self.hp = _real_fir(highpass(300.0, AUDIO_RATE, 150.0))
        self.lp = _real_fir(lowpass(3000.0, rate, kaiser_taps(600.0, rate, 50.0), 50.0))
        self.prev = 0.0
        self.phase = 0.0
        self.t = 0
        self.last_peak = 0.0
        self.configure()

    def configure(self, deviation: float = 2500.0, ctcss: float = 0.0, ctcss_level: float = 0.12,
                  mic_gain_db: float = 0.0, voice: bool = True):
        self.deviation = float(deviation)
        self.ctcss = float(ctcss or 0.0)
        self.ctcss_level = float(ctcss_level)
        self.mic_gain = 10 ** (mic_gain_db / 20)
        self.voice = voice
        self.burst_left = 0

    def toneburst(self, seconds: float):
        """Send 1750 Hz for `seconds` from the next block on."""
        self.burst_left = int(seconds * self.rate)

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        a = np.asarray(audio, np.float32)
        if self.voice:
            a = self.hp(a * np.float32(self.mic_gain)).real
        m = self.up(a.astype(np.complex64)).real
        if self.voice:
            prevs = np.concatenate([[self.prev], m[:-1]])
            self.prev = float(m[-1]) if len(m) else self.prev
            m = (m - self.a * prevs) * self.pre_norm
            m = np.clip(m * 1.5, -1.0, 1.0)
            m = self.lp(m).real
        # What the voice may use, so the tones keep their level within full deviation.
        room = 1.0 - (self.ctcss_level if self.ctcss else 0.0)
        m = np.clip(m, -1.0, 1.0) * room
        n = len(m)
        t = (self.t + np.arange(n)) / self.rate
        if self.ctcss:
            m = m + self.ctcss_level * np.sin(2 * np.pi * self.ctcss * t)
        if self.burst_left > 0:
            k = min(n, self.burst_left)
            m[:k] = 0.8 * room * np.sin(2 * np.pi * TONEBURST_HZ * t[:k]) + (
                self.ctcss_level * np.sin(2 * np.pi * self.ctcss * t[:k]) if self.ctcss else 0.0)
            self.burst_left -= k
        self.t += n
        self.last_peak = float(np.max(np.abs(m))) if n else 0.0
        ph = self.phase + 2 * np.pi * self.deviation / self.rate * np.cumsum(m)
        self.phase = float(ph[-1] % (2 * np.pi)) if n else self.phase
        return np.exp(1j * ph).astype(np.complex64)


def modulate(audio: np.ndarray, rate: float, deviation: float, ctcss: float = 0.0, ctcss_level: float = 0.12,
             phase0: float = 0.0) -> np.ndarray:
    """A whole FM signal at once (the simulators' stations): `audio` real at
    `rate`, deviation-normalised, plus a CTCSS tone; constant envelope."""
    m = np.clip(np.asarray(audio, np.float64), -1, 1) * (1 - (ctcss_level if ctcss else 0.0))
    if ctcss:
        m = m + ctcss_level * np.sin(2 * np.pi * ctcss * np.arange(len(m)) / rate)
    return np.exp(1j * (phase0 + 2 * np.pi * deviation / rate * np.cumsum(m))).astype(np.complex64)


def discriminate(x: np.ndarray, rate: float, deviation: float) -> np.ndarray:
    """Deviation-normalised instantaneous frequency of a block (no state)."""
    x = np.asarray(x, np.complex64)
    if len(x) < 2:
        return np.zeros(len(x), np.float32)
    d = np.angle(x[1:] * np.conj(x[:-1]))
    return np.concatenate([[d[0]], d]).astype(np.float32) * np.float32(rate / (2 * np.pi) / deviation)
