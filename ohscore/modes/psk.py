"""PSK31/63/125: BPSK, differential encoding, Varicode framing, 12 kHz mono
float32 audio.

This is the transmit half, the Varicode table and the carrier browser
(find_carriers). Receive is shack_sdr's Rust `psk` decoder since Radio's
SDR milestone 2 (modes/sdrmode.py PskDecoder), which hears several
stations at once: the Python decoder that lived here was removed once its
scores on a synthetic sweep were captured as the golden numbers the Rust
one must never fall below (ohs-libs shack_sdr testdata/psk/golden.json,
from this module at 27d591b). Its notes on why a receiver
mixes with a phase-continuous NCO, why the coarse AFC works on a wide
branch and why idle zeros are not counted in pairs went with it into the
Rust decoder's own comments (src/psk/mod.rs).

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
