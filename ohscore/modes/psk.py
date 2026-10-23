"""PSK31/63/125: BPSK, differential encoding, Varicode framing, 12 kHz mono
float32 audio.

Three design choices worth writing down because they are not obvious from
the wire format alone:

- **Differential, not absolute, phase.** A varicode data bit of 0 flips the
  carrier phase 180 deg; a 1 leaves it alone. This is what real PSK31 does,
  and it is why: a receiver that only has to notice "did the phase change
  since last symbol" never needs to know the carrier's absolute phase
  reference, which an AFC/costas loop can otherwise get wrong by exactly
  180 deg and never find out. Idle (nothing to send) is a continuous run of
  0 bits -- the characteristic PSK31 "warble" -- for the same reason DESIGN
  asks for it: it gives a receiver something to lock timing/AFC to even
  between characters.
- **Varicode terminates on "00".** Every code is built with no internal
  "00" and always ends in a 1 bit, so two bits of 0 can only ever mean "end
  of character" and a receiver never needs a bit-count or a framing field.
- **This module's varicode table is the real G3PLX one, byte for byte.**
  Earlier revisions of this module shipped a self-generated table (same
  shape -- short codes, no "00", ends in 1 -- but different bit patterns)
  rather than risk reproducing 128 published patterns wrong from memory;
  that proved the framing and demod end to end but could not talk to a
  real PSK31 station. The table below is instead transcribed from
  fldigi's src/psk/pskvaricode.cxx (`varicodetab1`, fldigi 4.2.13, the
  same file Debian ships: see sources.debian.org/src/fldigi), which is
  itself the code originally published by Peter Martinez, G3PLX, for
  codes 0-127; cross-checked against Wikipedia's "Varicode" article,
  which independently confirms e='11', a='1011', z='111010101'. Entries
  128-255 are fldigi's own extension for 8-bit text, beyond the original
  G3PLX 128-code set -- included for the extra range, but an operator
  relying on interop with a plain-G3PLX decoder should stay inside 0-127.

QPSK31 (and the FEC/pskr/8psk/16psk variants fldigi's tx_bit() also
handles) is out of scope here: those use a convolutional encoder/
interleaver ahead of the symbol mapper and a different, non-differential
tx_symbol() path (see fldigi's psk::tx_bit, the `_qpsk`/`_pskr`/`_xpsk`
branches), not just a wider constellation on top of the same bit stream.
Everything here is the plain differential-BPSK branch only.
"""

from __future__ import annotations

import numpy as np
from typing import Callable

FS = 12_000.0

# Transcribed verbatim from fldigi's varicodetab1 (src/psk/pskvaricode.cxx);
# see the module docstring for provenance. Index == ASCII/Latin-1 code point.
_VARICODETAB1 = (
    "1010101011", "1011011011", "1011101101", "1101110111", "1011101011",  # 0-4
    "1101011111", "1011101111", "1011111101", "1011111111", "11101111",  # 5-9
    "11101", "1101101111", "1011011101", "11111", "1101110101",  # 10-14
    "1110101011", "1011110111", "1011110101", "1110101101", "1110101111",  # 15-19
    "1101011011", "1101101011", "1101101101", "1101010111", "1101111011",  # 20-24
    "1101111101", "1110110111", "1101010101", "1101011101", "1110111011",  # 25-29
    "1011111011", "1101111111", "1", "111111111", "101011111",  # 30-34
    "111110101", "111011011", "1011010101", "1010111011", "101111111",  # 35-39
    "11111011", "11110111", "101101111", "111011111", "1110101",  # 40-44
    "110101", "1010111", "110101111", "10110111", "10111101",  # 45-49
    "11101101", "11111111", "101110111", "101011011", "101101011",  # 50-54
    "110101101", "110101011", "110110111", "11110101", "110111101",  # 55-59
    "111101101", "1010101", "111010111", "1010101111", "1010111101",  # 60-64
    "1111101", "11101011", "10101101", "10110101", "1110111",  # 65-69
    "11011011", "11111101", "101010101", "1111111", "111111101",  # 70-74
    "101111101", "11010111", "10111011", "11011101", "10101011",  # 75-79
    "11010101", "111011101", "10101111", "1101111", "1101101",  # 80-84
    "101010111", "110110101", "101011101", "101110101", "101111011",  # 85-89
    "1010101101", "111110111", "111101111", "111111011", "1010111111",  # 90-94
    "101101101", "1011011111", "1011", "1011111", "101111",  # 95-99
    "101101", "11", "111101", "1011011", "101011",  # 100-104
    "1101", "111101011", "10111111", "11011", "111011",  # 105-109
    "1111", "111", "111111", "110111111", "10101",  # 110-114
    "10111", "101", "110111", "1111011", "1101011",  # 115-119
    "11011111", "1011101", "111010101", "1010110111", "110111011",  # 120-124
    "1010110101", "1011010111", "1110110101",  # 125-127
    "1110111101", "1110111111", "1111010101", "1111010111", "1111011011",  # 128-132
    "1111011101", "1111011111", "1111101011", "1111101101", "1111101111",  # 133-137
    "1111110101", "1111110111", "1111111011", "1111111101", "1111111111",  # 138-142
    "10101010101", "10101010111", "10101011011", "10101011101", "10101011111",  # 143-147
    "10101101011", "10101101101", "10101101111", "10101110101", "10101110111",  # 148-152
    "10101111011", "10101111101", "10101111111", "10110101011", "10110101101",  # 153-157
    "10110101111", "10110110101", "10110110111", "10110111011", "10110111101",  # 158-162
    "10110111111", "10111010101", "10111010111", "10111011011", "10111011101",  # 163-167
    "10111011111", "10111101011", "10111101101", "10111101111", "10111110101",  # 168-172
    "10111110111", "10111111011", "10111111101", "10111111111", "11010101011",  # 173-177
    "11010101101", "11010101111", "11010110101", "11010110111", "11010111011",  # 178-182
    "11010111101", "11010111111", "11011010101", "11011010111", "11011011011",  # 183-187
    "11011011101", "11011011111", "11011101011", "11011101101", "11011101111",  # 188-192
    "11011110101", "11011110111", "11011111011", "11011111101", "11011111111",  # 193-197
    "11101010101", "11101010111", "11101011011", "11101011101", "11101011111",  # 198-202
    "11101101011", "11101101101", "11101101111", "11101110101", "11101110111",  # 203-207
    "11101111011", "11101111101", "11101111111", "11110101011", "11110101101",  # 208-212
    "11110101111", "11110110101", "11110110111", "11110111011", "11110111101",  # 213-217
    "11110111111", "11111010101", "11111010111", "11111011011", "11111011101",  # 218-222
    "11111011111", "11111101011", "11111101101", "11111101111", "11111110101",  # 223-227
    "11111110111", "11111111011", "11111111101", "11111111111", "101010101011",  # 228-232
    "101010101101", "101010101111", "101010110101", "101010110111", "101010111011",  # 233-237
    "101010111101", "101010111111", "101011010101", "101011010111", "101011011011",  # 238-242
    "101011011101", "101011011111", "101011101011", "101011101101", "101011101111",  # 243-247
    "101011110101", "101011110111", "101011111011", "101011111101", "101011111111",  # 248-252
    "101101010101", "101101010111", "101101011011",  # 253-255
)
assert len(_VARICODETAB1) == 256

VARICODE = {chr(i): code for i, code in enumerate(_VARICODETAB1)}
REVERSE_VARICODE = {v: k for k, v in VARICODE.items()}


def _text_to_bits(text: str) -> str:
    out = []
    for ch in text:
        code = VARICODE.get(ch)
        if code:
            out.append(code)
            out.append("00")
    return "".join(out)


BAUDS = {"psk31": 31.25, "psk63": 62.5, "psk125": 125.0}


class Encoder:
    """render(text=, variant="psk31", center=1000.0, preamble=2.0, postamble=1.0).

    preamble/postamble are seconds of idle (continuous phase reversal) sent
    before and after the text -- real PSK31 practice, so a receiver gets a
    clean run to find AFC lock and symbol timing on before the message, and
    the last character isn't clipped by TX dropping the carrier the instant
    the text ends."""

    def render(self, text: str = "", variant: str = "psk31", center: float = 1000.0,
               preamble: float = 3.0, postamble: float = 1.0, **_opts) -> np.ndarray:
        baud = BAUDS[variant]
        t_samples = FS / baud
        if abs(t_samples - round(t_samples)) > 1e-6:
            raise ValueError(f"{FS} Hz / {baud} baud is not an integer symbol length")
        t_n = int(round(t_samples))

        # Varicode's "00" terminator is matched two bits at a time starting
        # from an empty buffer; an *odd* number of idle bits before the text
        # starts leaves one unpaired 0 sitting in that buffer right when the
        # first real character begins, and if that character's own code
        # starts with 0 (about half of them do) its leading bit gets eaten
        # by what looks like one more idle terminator -- same ambiguity a
        # real PSK31 receiver has on an idle run of unlucky length, except
        # here we choose how much idle to send, so there's no reason not to
        # always send an even amount and hand the receiver a clean boundary.
        n_pre = int(round(preamble * baud)) // 2 * 2
        n_post = int(round(postamble * baud)) // 2 * 2
        bits = ("0" * n_pre) + _text_to_bits(text) + ("0" * n_post)
        if not bits:
            return np.zeros(0, dtype=np.float32)

        state = 1.0
        nrz = np.empty(len(bits), dtype=np.float64)
        for i, b in enumerate(bits):
            if b == "0":
                state = -state
            nrz[i] = state

        # Shape the symbol-rate square wave with a Hann-ish smoothing filter
        # about one symbol wide: this is what "raised-cosine shaped TX" buys
        # here -- phase reversals ease in and out over roughly a symbol
        # instead of stepping instantly, which is what keeps PSK31's
        # notoriously narrow spectrum narrow (a hard phase step splatters
        # energy across many kHz; ask any PSK31 op about "LIDs" doing this).
        rect = np.repeat(nrz, t_n)
        kernel = 0.5 - 0.5 * np.cos(2 * np.pi * (np.arange(t_n) + 0.5) / t_n)
        kernel /= kernel.sum()
        shaped = np.convolve(rect, kernel, mode="same")

        n = len(shaped)
        carrier = np.cos(2 * np.pi * center * np.arange(n) / FS)
        audio = (shaped * carrier).astype(np.float32)
        peak = float(np.max(np.abs(audio))) or 1.0
        return (audio / peak * 0.95).astype(np.float32)


class Decoder:
    """Differential BPSK receiver, built the way fldigi's is rather than the
    way the first version of this module was:

    1. **Mix to baseband with a phase-continuous NCO** -- the phase is an
       accumulator, advanced by `freq * n` for each chunk, so the AFC can
       change `freq` without moving the phase of anything already mixed.
    2. **Matched filter, then decimate** to 24 samples a symbol. The filter is
       the transmit pulse itself (one symbol of rectangle convolved with one
       symbol of Hann -- exactly what Encoder.render shapes with), with a
       zero-forcing correction folded in (see __init__), about 2 baud wide:
       everything else in a 3 kHz passband is thrown away before any
       decision is made.
    3. **AFC in two parts.** A coarse one (_acquire) squares a wider branch
       of the baseband -- z^2 removes the +-180 deg data, leaving a tone at
       twice the offset -- and FFTs a second of it: wide capture range, high
       processing gain, used to get onto a signal. A fine one (in _decide)
       nudges the NCO by the doubled phase change between symbols, at a low
       gain, to follow drift once on it.
    4. **Symbol timing from the envelope.** Each symbol's |z| is accumulated
       into a 24-bin histogram indexed by absolute sample position modulo a
       symbol; idle reversals dip to zero at symbol boundaries, so the
       circular centroid of that histogram is the symbol centre. It is
       re-estimated every symbol, which tracks a sound card whose clock is
       not quite 12 kHz as well as finding the timing in the first place;
       runs of unreversed symbols add a flat floor that does not bias it.
    5. **Differential detection** at the chosen sample: a 0 bit is a phase
       reversal since the previous symbol, which needs no carrier phase.

    A squelch -- the smoothed mean of cos(2 * phase change), 1 for a clean
    BPSK signal and 0 for noise (fldigi's "quality" metric) -- decides
    whether decoded characters are emitted, so noise between overs does not
    print a stream of garbage; everything else runs regardless so the loops
    are already settled when a signal appears.

    Why the rewrite: the previous decoder mixed each block with
    `exp(-2j*pi*freq*n/FS)` using the *absolute* sample count n, so every AFC
    step, however small, rotated the constellation by 2*pi*dfreq*n/FS -- an
    angle that grows with time since reset. Clean audio never moved the AFC,
    so loopback tests passed; with noise the AFC jittered by hundredths of a
    hertz, which after ten seconds is tens of degrees at every block edge,
    and copy fell apart at an SNR any PSK31 receiver copies perfectly. It
    also took its frequency and timing once, from the first 1.5 s it was
    fed, and never again: a decoder started on noise (the engine creates it
    when the mode is selected, long before our own echo comes back) was
    locked to nothing for ever. And it counted idle zeros in pairs, so an
    odd-length preamble ate the first character's leading bit.

    Measured (tests/test_modes_psk.py has the cases): complete copy of a
    28-character message at 10 dB SNR in the symbol bandwidth (-10 dB in
    3 kHz) on frequency, 10 Hz off, and drifting; within 1-2 dB of the
    DBPSK bit-error-rate bound below that.

    Nothing here loops per audio sample: work is done in whole-symbol
    chunks with numpy, and the Python loop runs once per symbol (31-125 per
    second)."""

    SPS = 24             # decimated samples per symbol
    ACQ_SYMS = 32        # coarse AFC looks at this many symbols (1 s at PSK31)...
    ACQ_EVERY = 8        # ...every this many
    ACQ_PROMINENCE = 20.0  # spectral peak over median before it is believed (13 dB)
    AFC_GAIN = 0.08      # fine AFC, per symbol
    LOST_SYMS = 32       # symbols below the squelch before the coarse AFC may take over again
    SQUELCH = 0.3        # quality below which characters are not emitted

    def __init__(self, emit: Callable[[dict], None], variant: str = "psk31", center: float = 1000.0,
                 afc_range: float = 15.0, **_opts):
        self.emit = emit
        self.variant = variant
        self.baud = BAUDS[variant]
        self.center0 = center
        self.afc_range = afc_range
        self.t_n = int(round(FS / self.baud))
        self.dec = self.t_n // self.SPS
        hann = 0.5 - 0.5 * np.cos(2 * np.pi * (np.arange(self.t_n) + 0.5) / self.t_n)
        pulse = np.convolve(np.ones(self.t_n), hann / hann.sum())
        # The matched filter alone leaves 13 % of each neighbouring symbol at
        # the sampling instant (the pulse is two symbols long, so pulse *
        # pulse is four), which closes the eye of idle reversals by a quarter
        # -- 2.6 dB lost on exactly the pattern a weak signal is acquired on.
        # A five-tap zero-forcing correction folded into the same FIR (taps
        # a symbol apart, solved from the pulse's own autocorrelation) takes
        # the ISI to 0.2 % for about 0.15 dB of noise bandwidth.
        # Autocorrelation at 0 and 1 symbol; at 2 and beyond it is exactly 0
        # (the pulse is shorter than two symbols).
        r = [float(np.dot(pulse[m * self.t_n:], pulse[:len(pulse) - m * self.t_n])) for m in range(2)]
        K = 2
        G = np.array([[r[abs(i - j)] if abs(i - j) < 2 else 0.0 for j in range(2 * K + 1)]
                      for i in range(2 * K + 1)])
        c = np.linalg.solve(G, np.eye(2 * K + 1)[K])
        h = np.zeros(len(pulse) + 2 * K * self.t_n)
        for j, cj in enumerate(c):
            h[j * self.t_n:j * self.t_n + len(pulse)] += cj * pulse
        self._h = h / h.sum()
        # The AFC's own, wider filter: flat to well past +-(afc_range + baud/2)
        # and symmetric about the NCO, so that a signal sitting off-centre
        # keeps both of its sidebands. See _acquire for why the matched filter
        # cannot be used there.
        n = np.arange(len(h)) - (len(h) - 1) / 2   # same length as _h: one sliding window serves both
        cut = 2.5 * self.baud / FS
        w = 2 * cut * np.sinc(2 * cut * n) * np.hamming(len(h))
        self._h_afc = w / w.sum()
        self.reset()

    def reset(self) -> None:
        self._raw = np.zeros(0, dtype=np.float64)        # audio not yet a whole symbol
        self._phase = 0.0                                # NCO phase, cycles
        self._freq = self.center0
        self._hist = np.zeros(len(self._h) - 1, dtype=np.complex128)  # filter memory
        self._z = np.zeros(0, dtype=np.complex128)       # decimated baseband, matched-filtered
        self._w = np.zeros(0, dtype=np.complex128)       # decimated baseband, AFC branch
        self._wf = np.zeros(0)                           # the NCO frequency each _w sample was mixed at
        self._z0 = 0                                     # absolute index of _z[0]
        self._next = float(self.SPS)                     # absolute index of the next symbol centre
        self._env = np.zeros(self.SPS)
        self._n_sym = 0
        self._chunks = 0
        self._locked = False      # the coarse AFC has seen a carrier and put us on it
        self._lost = 0            # consecutive symbols with quality below the squelch
        self._q = 0.0
        self._prev = 0j
        self._bits = ""
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    @property
    def freq(self) -> float:
        return self._freq

    @property
    def quality(self) -> float:
        return self._q

    def feed(self, audio: np.ndarray, t: float) -> None:
        self._raw = np.concatenate([self._raw, np.asarray(audio, dtype=np.float64)])
        n = len(self._raw) // self.t_n
        for k in range(n):
            self._chunk(self._raw[k * self.t_n:(k + 1) * self.t_n])
        self._raw = self._raw[n * self.t_n:]

    def _chunk(self, x: np.ndarray) -> None:
        """One symbol's worth of audio: mix, filter, decimate, AFC, then
        whatever symbol decisions the new samples complete."""
        ph = self._phase + self._freq * np.arange(len(x)) / FS
        self._phase = (self._phase + self._freq * len(x) / FS) % 1.0
        buf = np.concatenate([self._hist, x * np.exp(-2j * np.pi * ph)])
        self._hist = buf[len(x):]
        L = len(self._h)
        win = np.lib.stride_tricks.sliding_window_view(buf, L)[self.dec - 1::self.dec]
        y = win @ self._h
        self._z = np.concatenate([self._z, y])
        keep = self.ACQ_SYMS * self.SPS
        self._w = np.concatenate([self._w, win @ self._h_afc])[-keep:]
        self._wf = np.concatenate([self._wf, np.full(len(y), self._freq)])[-keep:]
        self._chunks += 1
        if self._chunks % self.ACQ_EVERY == 0 and len(self._w) >= keep:
            self._acquire()
        self._symbols()

    def _acquire(self) -> None:
        """Coarse AFC: where is the carrier, to a quarter of a hertz, over the
        last ACQ_SYMS symbols? Squaring the wide branch removes the BPSK
        data and leaves a tone at twice the offset; an FFT of a second of it
        has enough processing gain to find that tone at an SNR
        where the per-symbol loop below cannot yet be trusted, and a capture
        range of the whole AFC window.

        It only moves the NCO when nothing else has the signal: before the
        first lock, or after the fine loop has been incoherent for LOST_SYMS
        symbols. Allowed to overrule a working fine loop it does harm, because
        it measures the past: when the transmitting station's TX lock stepped
        its frequency 6 Hz mid-preamble (our own echo through the simulator
        does exactly that), the fine loop followed within half a second and
        this pulled it back to where the signal *had* been, three times.

        On the wide branch, not the matched filter: PSK31 idle is two tones
        at carrier +-baud/2, and with the carrier 10 Hz off-centre the matched
        filter (about +-1 baud wide) passes one of them far more than the
        other, so a squaring estimator behind it finds that sideband --
        15.6 Hz out, which differential detection cannot even notice (half a
        turn per symbol looks like a lock) and which inverts every bit.
        Measured, not theorised: the first cut of this loop did exactly that
        with a 10 Hz offset."""
        # (No mean removal: when we are already on frequency the tone *is*
        # the mean, and subtracting it once made this jump 15 Hz away to a
        # sideband of the idle pattern.)
        # The NCO has moved while this buffer filled (the fine loop follows
        # drift, and a jump moves it at once), so a tone that sat still in
        # the air is smeared across it. Re-mix every sample to the current
        # NCO frequency first -- a running phase of (now - then) -- and the
        # buffer reads as if it had been taken at one frequency. Without
        # this, the estimate after the transmitting station's own TX lock
        # stepped its frequency mid-preamble landed 5 Hz wrong, twice.
        rate = self.SPS * self.baud
        corr = np.cumsum(self._freq - self._wf) / rate
        sq = (self._w * np.exp(-2j * np.pi * corr)) ** 2
        nfft = 4 * len(sq)
        spec = np.abs(np.fft.fft(sq * np.hanning(len(sq)), nfft)) ** 2
        f2 = np.fft.fftfreq(nfft, 1.0 / rate) / 2               # offset each bin means
        lo, hi = self.center0 - self.afc_range, self.center0 + self.afc_range
        band = np.abs(f2) <= self.afc_range + 2.0
        k = int(np.argmax(np.where(band, spec, 0.0)))
        if spec[k] < self.ACQ_PROMINENCE * float(np.median(spec[band])):
            if self._q < self.SQUELCH:
                self._locked = False       # no carrier here any more
            return
        if self._locked and self._lost < self.LOST_SYMS:
            return
        self._locked = True
        # Parabolic interpolation between bins (on log power): a jump that
        # lands within a fraction of a bin leaves the fine loop nothing to do.
        a, b, c = (np.log(spec[(k + m) % nfft] + 1e-30) for m in (-1, 0, 1))
        frac = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) < 0 else 0.0
        offset = (f2[k] + frac * rate / nfft / 2)
        new = float(np.clip(self._freq + offset, lo, hi))
        if abs(new - self._freq) > self.baud / 10:
            self._freq = new
            # Every decision so far was made off frequency: forget them, and
            # the quality they earned, rather than print what they spelt.
            self._bits = ""
            self._q = 0.0
            self._lost = 0

    def _symbols(self) -> None:
        half = self.SPS // 2
        bins = np.arange(self.SPS)
        rot = np.exp(2j * np.pi * bins / self.SPS)
        while True:
            c = int(round(self._next))
            i = c - self._z0
            if i + half > len(self._z):
                break
            w = self._z[i - half:i + half]
            idx = (np.arange(c - half, c + half)) % self.SPS
            a = max(1.0 / (self._n_sym + 1), 1.0 / 16)
            self._env[idx] = (1 - a) * self._env[idx] + a * np.abs(w)
            tau = (np.angle(np.sum(self._env * rot)) / (2 * np.pi) * self.SPS) % self.SPS
            err = (tau - self._next % self.SPS + half) % self.SPS - half
            z = self._z[i]
            self._next += self.SPS + 0.5 * err
            self._n_sym += 1
            self._decide(z)
        keep = int(round(self._next)) - half - self._z0 - 1
        if keep > 0:
            self._z = self._z[keep:]
            self._z0 += keep

    def _decide(self, z: complex) -> None:
        d = z * np.conj(self._prev)
        self._prev = z
        mag = abs(d)
        if mag > 0:
            c2 = complex(d * d) / (mag * mag)
            self._q = 0.95 * self._q + 0.05 * c2.real
            self._lost = self._lost + 1 if self._q < self.SQUELCH else 0
            # Fine AFC: the phase change between symbols, doubled to remove
            # the data, is 4*pi*offset*T. Per symbol, at a low gain -- a time
            # constant of ~12 symbols -- because each estimate is as noisy as
            # the symbol itself, and an AFC that follows the noise rotates
            # the constellation by its own jitter (a 2.7 Hz rms wobble at
            # 10 dB, measured, with the faster wide-band loop this replaced).
            # Its range is +-baud/4; _acquire handles anything further out,
            # and until it has, this loop stays still: outside its range it
            # walks the wrong way (measured), and it would smear the very
            # buffer _acquire is about to measure.
            err = np.angle(c2) / (4 * np.pi) * self.baud if self._locked else 0.0
            self._freq = float(np.clip(self._freq + self.AFC_GAIN * err,
                                       self.center0 - self.afc_range, self.center0 + self.afc_range))
        bit = "1" if d.real >= 0 else "0"
        if bit == "0" and not self._bits:
            # Every varicode character starts with a 1, so zeros before one
            # are idle, whatever their number. Counting them in pairs instead
            # (the earlier rule) made the first character after an odd-length
            # idle run -- which is any real station's preamble half the time --
            # lose its leading bit and decode as something else.
            return
        self._bits += bit
        if self._bits.endswith("00"):
            code = self._bits[:-2]
            self._bits = ""
            ch = REVERSE_VARICODE.get(code) if code else None
            if ch and self._locked and self._q >= self.SQUELCH:
                self._text += ch
                self.emit({"mode": self.variant, "center": self._freq, "df": self._freq,
                           "snr": round(self._snr_db(), 1), "text": ch})
        elif len(self._bits) > 24:
            # Runaway: no terminator in 24 bits cannot be a character (the
            # table tops out well short of that) -- noise; drop it.
            self._bits = ""

    def _snr_db(self) -> float:
        """Rough SNR in the symbol-rate bandwidth from the phase scatter:
        for Gaussian phase noise E[cos 2x] = exp(-2 var), and the variance of
        a phase *difference* is about 1/(Es/N0)."""
        q = min(max(self._q, 1e-3), 0.999)
        return 10 * np.log10(1.0 / (-0.5 * np.log(q)))


def find_carriers(audio: np.ndarray, fs: float = FS, min_hz: float = 200.0,
                   max_hz: float = 3000.0, n_peaks: int = 12) -> list[float]:
    """A console "signal browser": narrow, FFT-domain peak-pick over an audio
    block, returning candidate PSK carrier frequencies loudest-first. PSK31's
    whole ~60 Hz signal sits in 2-3 FFT bins at typical block lengths, which
    is exactly what distinguishes it from SSB/noise in this simple a scan;
    getting choosy about shape is unnecessary when the caller already knows
    it's listing candidates for a human to click on, not auto-classifying."""
    n = len(audio)
    if n < 256:
        return []
    window = np.hanning(n)
    spec = np.abs(np.fft.rfft(audio * window))
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    lo = np.searchsorted(freqs, min_hz)
    hi = np.searchsorted(freqs, max_hz)
    band = spec[lo:hi]
    if len(band) < 3:
        return []
    floor = float(np.median(band))
    peaks = []
    for i in range(1, len(band) - 1):
        if band[i] > band[i - 1] and band[i] >= band[i + 1] and band[i] > 4 * (floor + 1e-9):
            peaks.append((float(band[i]), float(freqs[lo + i])))
    peaks.sort(reverse=True)
    return [f for _, f in peaks[:n_peaks]]
