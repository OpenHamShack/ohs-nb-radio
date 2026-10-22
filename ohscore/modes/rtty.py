"""RTTY: 45.45 baud, 170 Hz shift, 5-bit ITA2 (Baudot-Murray) with a LTRS/FIGS
shift state, 1.5 stop bits. 12 kHz mono float32 audio, same as every other
mode here.

This is the transmit half, and the code table both halves agree on.
Receive is shack_sdr's Rust decoder since Radio's SDR milestone 1
(modes/sdrmode.py): the Python decoder that lived here was removed once
its scores on a synthetic sweep were captured as the golden numbers the
Rust one must never fall below (ohs-libs shack_sdr testdata/rtty/
golden.json). The notes below on why a receiver needs a squelch, LTRS at
the start and unshift-on-space are the reasons the encoder is written as
it is, and why the Rust decoder does what this one did.

RTTY is asynchronous, character by character, which is the one thing that
makes it more forgiving than it looks: every character carries its own
start bit, so the decoder only has to find *that* character's edge and can
re-synchronise from scratch for the next one. It never has to track phase
or baud rate across a whole transmission the way PSK or FT8 do.

The flip side is that a start-stop decoder will find "characters" in pure
noise: any space-going edge followed, 6.5 bits later, by something that
reads as mark is a frame. Unsquelched, that printed a steady stream of
garbage, and - worse than the garbage itself - left the shift state wherever
the last noise FIGS or LTRS put it, so our own transmission, arriving into a
decoder sitting in FIGS, read "CQ CQ DE" as ":1 :1 $3". Three things now
stop that, each the convention real RTTY software follows:

- the decoder only accepts a frame whose bits look like a two-tone FSK
  signal rather than noise (a squelch on the frame's own mark/space contrast);
- every transmission opens with LTRS, so the far decoder's shift state is
  set by us, not by whatever it heard before (fldigi sends a run of LTRS
  before the first character for the same reason);
- unshift-on-space (USOS) on both sides: a space returns to letters, so a
  missed FIGS/LTRS costs one word, not the rest of the over.
"""

from __future__ import annotations

import numpy as np

FS = 12_000.0

# ITA2 / CCITT No.2 letters (the "Baudot-Murray" code every RTTY station on
# the air actually uses -- plain 5-bit Baudot is a different, older code and
# would not interoperate), with the US-TTY figures case that amateur RTTY
# uses in place of ITA2's own (ITU-T S.1): D=$, F=!, G=&, H=#, J=', S=BELL,
# V=;, Z=". That is fldigi's and MMTTY's default table, so it is what the
# stations we work will print. Bits are written b1..b5 in transmission
# order, 1=mark. LTRS and FIGS are shift codes: everything after one is read
# from the other table until the next shift. Codes with no figure meaning
# repeat the letter meaning (SPACE, CR, LF, LTRS, FIGS, blank) since both
# tables need an entry for them.
_ROWS = [
    ("00000", None, None), ("00100", " ", " "), ("00010", "\r", "\r"), ("01000", "\n", "\n"),
    ("11111", "LTRS", "LTRS"), ("11011", "FIGS", "FIGS"),
    ("11000", "A", "-"), ("10011", "B", "?"), ("01110", "C", ":"), ("10010", "D", "$"),
    ("10000", "E", "3"), ("10110", "F", "!"), ("01011", "G", "&"), ("00101", "H", "#"),
    ("01100", "I", "8"), ("11010", "J", "'"), ("11110", "K", "("), ("01001", "L", ")"),
    ("00111", "M", "."), ("00110", "N", ","), ("00011", "O", "9"), ("01101", "P", "0"),
    ("11101", "Q", "1"), ("01010", "R", "4"), ("10100", "S", "\a"), ("00001", "T", "5"),
    ("11100", "U", "7"), ("01111", "V", ";"), ("11001", "W", "2"), ("10111", "X", "/"),
    ("10101", "Y", "6"), ("10001", "Z", '"'),
]
CODE_TO_LETTER = {c: l for c, l, f in _ROWS}
CODE_TO_FIGURE = {c: (f if f is not None else l) for c, l, f in _ROWS}
LETTER_TO_CODE = {l: c for c, l, f in _ROWS if l}
FIGURE_TO_CODE = {f: c for c, l, f in _ROWS if f}
LTRS, FIGS = "11111", "11011"
SPACE, CR, LF = "00100", "00010", "01000"


def _text_to_codes(text: str) -> list[str]:
    """Letters and figures each have their own code space; this inserts a
    shift code whenever the next character isn't in the table the line is
    currently shifted to, mirroring what a real Baudot teleprinter did.

    Unshift-on-space: a space puts the receiver back in letters (every
    receiver we work does it, shack_sdr's included), so a figure after a
    space needs its FIGS again.
    A newline goes as CR LF, the teleprinter's carriage return and line
    feed; a bare CR in the text is dropped so CR LF is not doubled."""
    out: list[str] = []
    shifted_to_figs = False
    for ch in text.upper():
        if ch == "\r":
            continue
        if ch == "\n":
            out += [CR, LF]
            continue
        if ch in LETTER_TO_CODE and (ch not in FIGURE_TO_CODE or not shifted_to_figs):
            if shifted_to_figs:
                out.append(LTRS)
                shifted_to_figs = False
            out.append(LETTER_TO_CODE[ch])
            if ch == " ":
                shifted_to_figs = False
        elif ch in FIGURE_TO_CODE:
            if not shifted_to_figs:
                out.append(FIGS)
                shifted_to_figs = True
            out.append(FIGURE_TO_CODE[ch])
            if ch == " ":
                shifted_to_figs = False
        # anything else (an unmappable character) is dropped, same policy as cw.py.
    return out


class Encoder:
    """render(text=, baud=45.45, shift=170.0, center=1000.0, preamble=0.2, postamble=0.1).

    preamble/postamble are seconds of steady mark (the idle line) before the
    first character and after the last."""

    # LTRS characters sent ahead of the text. Two, not one: if the far
    # decoder takes the first as the tail of something it was already
    # mis-framing, the second still lands cleanly, and LTRS is all mark so a
    # mis-framed one prints nothing.
    LEAD_LTRS = 2

    def render(self, text: str = "", **opts) -> np.ndarray:
        codes = _text_to_codes(text)
        if codes:
            codes = [LTRS] * self.LEAD_LTRS + codes
        return self.render_codes(codes, **opts)

    def render_codes(self, codes: list[str], baud: float = 45.45, shift: float = 170.0,
                     center: float = 1000.0, preamble: float = 0.2, postamble: float = 0.1,
                     **_opts) -> np.ndarray:
        """Exactly these 5-bit codes, framed, with no shift codes added."""
        mark_f = center + shift / 2
        space_f = center - shift / 2
        bit_s = 1.0 / baud
        # Render as one continuous-phase FSK carrier: phase accumulates by each
        # bit's own frequency for its own duration, never resetting, which is
        # what keeps a real FSK tone glitch-free at the bit transitions (no
        # amplitude step, only a frequency step -- the audible "no clicks"
        # that raised-cosine edges gave the CW encoder, FSK gets for free from
        # always having full amplitude).
        segments = []
        if codes:
            segments.append((mark_f, preamble))
        for code in codes:
            segments.append((space_f, bit_s))                    # start bit
            for b in code:
                segments.append((mark_f, bit_s) if b == "1" else (space_f, bit_s))
            segments.append((mark_f, 1.5 * bit_s))                # stop bit(s)
        if codes:
            # Idle mark after the last character: a short stretch of the
            # idle line, so a far decoder reads the last stop bit against
            # steady mark rather than against the carrier dropping on its
            # edge - about four and a half bits at 45.45 Bd, never under two.
            # It was briefly half a second, as a workaround: the
            # engine called tx_stop, which empties the device's queue (up to
            # ~225 ms in the simulator), straight after the last block, and
            # the "K" of "PSE K" was cut off mid-frame. The engine now lets
            # the queue go out before stopping (Engine._tx_drain), and the
            # echo keeps its last character with no idle at all, so the
            # tail is back to what RTTY practice wants rather than what the
            # transmitter needed.
            segments.append((mark_f, max(postamble, 2 * bit_s)))

        # Each segment ends at the rounded *cumulative* time, so 1.5-bit stop
        # bits and 264-sample bits never accumulate rounding drift.
        out = []
        phase = 0.0
        t_end = 0.0
        pos = 0
        for freq, dur in segments:
            t_end += dur
            end = int(round(t_end * FS))
            n = end - pos
            if n <= 0:
                continue
            out.append(np.sin(2 * np.pi * freq * np.arange(n) / FS + phase).astype(np.float32))
            phase = (phase + 2 * np.pi * freq * n / FS) % (2 * np.pi)
            pos = end
        if not out:
            return np.zeros(1, np.float32)
        return np.concatenate(out)
