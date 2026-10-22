"""RTTY: 45.45 baud, 170 Hz shift, 5-bit ITA2 (Baudot-Murray) with a LTRS/FIGS
shift state, 1.5 stop bits. 12 kHz mono float32 audio, same as every other
mode here.

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
from typing import Callable

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

# The decoder prints what a teleprinter would have put on the paper. CR and
# LF arrive as a pair (CR LF, or CR CR LF from older habits) and become one
# line break: LF is the newline, CR prints nothing. BELL rang the bell and
# printed nothing, and blank (00000) did nothing at all, so neither is shown:
# handed to the terminal as raw control codes they drew as an empty box.
_SILENT = {"\r", "\a", None}


def _text_to_codes(text: str) -> list[str]:
    """Letters and figures each have their own code space; this inserts a
    shift code whenever the next character isn't in the table the line is
    currently shifted to, mirroring what a real Baudot teleprinter did.

    Unshift-on-space: a space puts the receiver back in letters (see
    Decoder._on_code), so a figure after a space needs its FIGS again.
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


class Decoder:
    """Async start-stop decode. Mark/space energy is measured with two
    vectorised Goertzels per quarter-bit interval (one matmul each per
    feed() call covering the whole new block); only the resulting sparse
    per-quarter-bit series is walked by a Python loop to find start
    edges and read bits -- a few hundred iterations per second, not
    a per-sample loop.

    `squelch` is the minimum mean mark/space contrast, 0..1, a frame must
    show to be printed when nothing has been copied for a while; `hold`
    the lower one that applies for HOLD_S after a frame that passed (see
    _frame)."""

    # Per bit: (|mark| - |space|) / (|mark| + |space|), summed over the bit's
    # two middle quarters, is near +-1 for a clean FSK bit and spread around
    # +-0.3 for noise (two Rayleigh magnitudes). A frame's mean over its seven
    # bits (start and stop counted with their expected sign) is what the
    # squelch compares. Measured (600 s of noise, the message at 0-40 Hz off
    # tune, tests/test_modes_rtty.py keeps the figures honest):
    #   noise frames above 0.35: 5 a minute; above 0.40: 0.8; above 0.45: none
    #   a signal's 10th percentile: 0.58 at 0 dB SNR (3 kHz), 0.46 at -3 dB,
    #   0.51 at 0 dB but 25 Hz off tune (the leak between 66-sample bins).
    # So a frame opens the squelch at 0.45 - noise effectively never does -
    # and while copy is running the bar drops to 0.35 for a second and a
    # half, so one weak frame inside a message is still printed. Ending an
    # over then costs, on average, a tenth of a garbage character.
    SQUELCH = 0.45
    HOLD = 0.35
    HOLD_S = 1.5
    ENVELOPE = 0.4

    def __init__(self, emit: Callable[[dict], None], baud: float = 45.45, shift: float = 170.0,
                 center: float = 1000.0, squelch: float | None = None, hold: float | None = None, **_opts):
        self.emit = emit
        self.baud = baud
        self.center = center
        self.squelch = self.SQUELCH if squelch is None else float(squelch)
        self.hold = min(self.squelch, self.HOLD if hold is None else float(hold))
        self._hold_q = int(round(self.HOLD_S * baud * 4))   # HOLD_S in quarter-bits
        mark_f = center + shift / 2
        space_f = center - shift / 2
        self.frame_len = max(1, int(round(FS / baud / 4)))  # one quarter of a bit interval
        n = np.arange(self.frame_len)
        self._basis_mark = np.exp(-2j * np.pi * mark_f * n / FS)
        self._basis_space = np.exp(-2j * np.pi * space_f * n / FS)
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.float32)
        self._mark = np.zeros(0, dtype=np.float64)   # |Goertzel| at mark, one per quarter-bit
        self._space = np.zeros(0, dtype=np.float64)  # and at space
        self._scan = 1            # index into the series: search for the next start edge from here
        self._base = 0            # quarters trimmed off the front so far (absolute = base + index)
        self._open_until = -1     # absolute quarter until which the lower `hold` bar applies
        self._shifted_to_figs = False
        self._text = ""

    def feed(self, audio: np.ndarray, t: float) -> None:
        buf = np.concatenate([self._buf, audio.astype(np.float32)])
        n_frames = len(buf) // self.frame_len
        if n_frames:
            used = n_frames * self.frame_len
            self._buf = buf[used:]
            frames = buf[:used].reshape(n_frames, self.frame_len).astype(np.complex128)
            self._mark = np.concatenate([self._mark, np.abs(frames @ self._basis_mark)])
            self._space = np.concatenate([self._space, np.abs(frames @ self._basis_space)])
        else:
            self._buf = buf

        pol = self._mark - self._space
        # A frame is start + 5 data + 1.5 stop bits, 4 quarter-bits each; the
        # stop bit is read in its first bit, so 7 bits of quarters are needed.
        NEEDED = 7 * 4
        while True:
            # The next mark->space edge: a quarter that reads space after one
            # that read mark. Only edges, not every space quarter: after a
            # rejected candidate the rest of that space run is the same
            # (non-)start bit, and trying each of its quarters in turn was
            # how noise got several chances at every dip.
            seg = pol[self._scan - 1:]
            edges = np.where((seg[1:] < 0) & (seg[:-1] >= 0))[0]
            if len(edges) == 0:
                self._scan = max(1, len(pol) - 1)
                break
            j = self._scan + int(edges[0])
            if j + NEEDED > len(pol):
                self._scan = j  # wait for more data; re-examine this same edge next time
                break
            code = self._frame(j)
            if code is None:
                self._scan = j + 1
                continue
            self._on_code(code)
            # Resume inside the stop bit: the earliest the next start edge can be.
            self._scan = j + 6 * 4 + 2

        # Trim what can never be touched again (keep a small margin so a
        # partially-matched search at the tail isn't thrown away).
        if self._scan > 256:
            drop = self._scan - 32
            self._mark = self._mark[drop:]
            self._space = self._space[drop:]
            self._scan -= drop
            self._base += drop

    def _frame(self, j: int) -> str | None:
        """The five data bits of a frame whose start edge is quarter `j`, or
        None if it is not a frame worth printing.

        Quarter j is the first to read space, so the true edge lies within
        half a quarter of j's start; bit k then certainly covers quarters
        j+4k+1 and j+4k+2, and those two are what it is read from. Reading
        one quarter (the old way) threw away half of every bit's energy for
        nothing; reading all four would let a neighbour's bit leak in."""
        idx = j + 4 * np.arange(7)[:, None] + np.array([1, 2])[None, :]
        m = self._mark[idx].sum(axis=1)
        s = self._space[idx].sum(axis=1)
        d = m - s
        if d[0] >= 0 or d[6] <= 0:
            return None      # no start bit, or no stop bit: not a frame
        contrast = np.abs(d) / np.maximum(m + s, 1e-12)
        bar = self.hold if self._base + j <= self._open_until else self.squelch
        if contrast.mean() < bar:
            return None      # bits that look like noise, not a two-tone signal
        e = m + s
        if e.min() < self.ENVELOPE * e.max():
            return None      # not constant-envelope: noise at one end, a signal at the other
        self._open_until = self._base + j + self._hold_q
        return "".join("1" if x > 0 else "0" for x in d[1:6])

    def _on_code(self, code: str) -> None:
        if code == LTRS:
            self._shifted_to_figs = False
            return
        if code == FIGS:
            self._shifted_to_figs = True
            return
        ch = (CODE_TO_FIGURE if self._shifted_to_figs else CODE_TO_LETTER).get(code)
        if code == SPACE:
            # Unshift-on-space (fldigi's and MMTTY's default, and what our
            # encoder assumes): a space returns to letters, so a lost LTRS
            # garbles one group of figures rather than everything after it.
            self._shifted_to_figs = False
        if ch in _SILENT:
            return
        self._text += ch
        self.emit({"mode": "rtty", "text": ch, "center": self.center})

    @property
    def text(self) -> str:
        return self._text
