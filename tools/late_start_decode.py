#!/usr/bin/env python3
"""Does an FT8 over that starts late, with the symbols already past dropped
(the waveform's tail, aligned to the slot), still decode? ohsdigi encodes
(the same encoder the engine renders with) and ohsdigi decodes (NB's own
decoder, a port of jt9), over white noise at a few SNRs. Usage:

    tools/late_start_decode.py [trials] [ap]

Needs ohsdigi (tools/build-ohsdigi.sh --host --install). "ap": the station
being called decodes with its own call known (WSJT-X's a-priori passes,
on by default there), at depth 3; without it, depths 1 (NB's) and 3.
Takes some minutes: every cell is `trials` full decodes."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
trials = int(sys.argv[1]) if len(sys.argv) > 1 else 10
# "ap": the realistic case for an answer - the station we call is decoding
# with its own call known (WSJT-X's a-priori passes), depth 3.
AP = "ap" in sys.argv[2:]
from ohscore import ohsdigi  # noqa: E402
from ohscore import modes_glue  # noqa: E402

FS = 12000
TEXT = "DL1ABC GM4BRI IO75" if AP else "GM4BRI DL1ABC R-08"
wave = np.asarray(modes_glue.encoder("ft8").render(text=TEXT, freq=1500.0), np.float64)
p_sig = float(np.mean(wave ** 2))


def slot_audio(start_into_slot, snr, rng):
    """15 s at 12 kHz: noise, plus the waveform's tail from the point that
    a start `start_into_slot` s into the slot reaches, placed there."""
    buf = np.zeros(15 * FS)
    nominal = int(0.5 * FS)
    at = int(round(start_into_slot * FS))
    skip = max(0, at - nominal)
    tail = wave[skip:]
    buf[at:at + len(tail)] += tail[:len(buf) - at]
    sigma = np.sqrt(p_sig / (10 ** (snr / 10)) * (FS / 2) / 2500)
    buf += rng.standard_normal(len(buf)) * sigma
    buf *= 3000 / (np.max(np.abs(buf)) + 1e-9)
    return buf.astype(np.int16)


print(f"message {TEXT!r}; {trials} noise draws per cell; cells: decodes/trials")
for depth in ((3,) if AP else (1, 3)):
    print((f"depth {depth} (NB's)" if depth == 1 else f"depth {depth} (WSJT-X Deep)") + (", AP: decoder's own call known" if AP else ""))
    snrs = (-6, -10, -14, -18)
    print("start s  " + "  ".join(f"{s:>5} dB" for s in snrs))
    for start in ((4.0, 4.5, 5.0, 5.5, 6.0, 6.5) if AP else (0.5, 2.0, 3.0, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5)):
        row = []
        for snr in snrs:
            ok = 0
            for t in range(trials):
                rng = np.random.default_rng(1000 * t + int(start * 10) + 7 * (snr + 40))
                got = ohsdigi.ft8_decode(slot_audio(start, snr, rng).tobytes(), depth=depth, threads=2,
                                         **({"mycall": "DL1ABC"} if AP else {}))
                ok += any(d.get("text", d.get("message", "")).strip() == TEXT for d in got)
            row.append(f"{ok:>3}/{trials:<4}")
        print(f"{start:>6.1f}   " + "  ".join(row), flush=True)
print("DONE")
