"""CW (Morse) encoder and decoder, 12 kHz mono float32 audio.

The encoder is the easy half: build an element timeline (dit/dah/gap) from
the WPM and Farnsworth spacing, then paint a tone with raised-cosine edges
onto it. The decoder is the interesting half, and it is no longer here: it
began in this file and moved to ohs-libs' shack_cw (10/10/2026), with the
Morse tables and tools/cw_bench.py's cases, so that OpenHamShack Icom and
Flex run the same decoder as NB and Radio (GUIDE: shared components, one of
each). shack_cw.decoder's docstring has the how and the why.

What stays is NB's side of it: the mode decoders' interface, feed(audio, t)
at the engine's 12 kHz, over the shared decoder's feed(samples, rate).
"""

from __future__ import annotations

import numpy as np

from .. import shacklibs

_cw = shacklibs.cw()

FS = 12_000.0

# The tables are the shared ones (shack_cw.morse); the names stay so
# nothing that imported them from here has to change.
MORSE = _cw.MORSE
PROSIGNS = _cw.PROSIGNS
CODE_TO_CHAR = _cw.CODE_TO_CHAR
CODE_TO_PROSIGN = _cw.CODE_TO_PROSIGN
_text_to_codes = _cw.text_to_codes


class Encoder:
    """render(text=, wpm=20, farnsworth=None, freq=700.0, edge_ms=5.0)."""

    def render(self, text: str = "", wpm: float = 20.0, farnsworth: float | None = None,
               freq: float = 700.0, edge_ms: float = 5.0, **_opts) -> np.ndarray:
        dit = 1.2 / wpm  # PARIS standard: a 50-dit word in 60/wpm seconds.
        dah = 3 * dit
        intra = dit  # gap between elements of the same letter never slows with Farnsworth.
        # Farnsworth keeps element speed at `wpm` (so it still sounds like real CW)
        # but opens out the gaps between letters and words to a slower effective
        # speed -- that's the whole point, giving a learner's ear more processing
        # time without the dits and dahs themselves dragging.
        space_wpm = farnsworth if farnsworth and farnsworth < wpm else wpm
        fdit = 1.2 / space_wpm
        inter = 3 * fdit
        word = 7 * fdit

        codes = _text_to_codes(text)
        timeline: list[tuple[bool, float]] = []  # (tone_on, duration)
        for idx, code in enumerate(codes):
            if code == " ":
                continue  # the gap itself is emitted below, by the letter before it
            for j, sym in enumerate(code):
                if j:
                    timeline.append((False, intra))
                timeline.append((True, dah if sym == "-" else dit))
            if idx + 1 < len(codes):
                # A word space immediately follows iff the *next* token is one;
                # looking ahead here (rather than reacting to the space token
                # when we reach it) means there is always a mark, not a gap,
                # at the end of the timeline list to extend -- extending the
                # wrong element silently ate the last letter's final dah.
                timeline.append((False, word if codes[idx + 1] == " " else inter))

        edge = edge_ms / 1000.0
        n_total = int(round(sum(d for _, d in timeline) * FS)) or 1
        out = np.zeros(n_total, dtype=np.float32)
        t_phase = 0.0  # running phase in seconds, so the tone itself stays continuous
        pos = 0
        for on, dur in timeline:
            n = int(round(dur * FS))
            if on and n > 0:
                t = (np.arange(n) / FS) + t_phase
                env = np.ones(n, dtype=np.float64)
                e_n = min(int(edge * FS), n // 2)
                if e_n > 0:
                    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(e_n) / e_n)
                    env[:e_n] = ramp
                    env[-e_n:] = ramp[::-1]
                out[pos:pos + n] = (np.sin(2 * np.pi * freq * t) * env).astype(np.float32)
            t_phase += dur
            pos += n
        return out[:n_total]



class Decoder(_cw.Decoder):
    """shack_cw's decoder with NB's mode-decoder interface: feed(audio, t)
    with the engine's 12 kHz audio, events to the `emit` it was made with.
    `t` was never used (the decoder times everything by samples)."""

    def feed(self, audio: np.ndarray, t: float) -> None:
        super().feed(audio, FS)
