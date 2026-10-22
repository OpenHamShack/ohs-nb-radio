#!/usr/bin/env python3
"""Rebuild ohscore/dsp/nr_tables.npz from WDSP's calculus.c.

    tools/nr-tables.py <path to WDSP's Source/calculus.c>

The noise reduction (ohscore/dsp/nr.py) uses WDSP's default gain method,
which reads its gain from two 241 x 241 tables (GG and GGS) that Warren
Pratt computed offline and ships as C source in calculus.c (3 MB of
text). Neither is a closed form that could be computed at import instead:
compared on the development machine (05/10/2026), GG departs from the textbook MMSE-LSA
gain by a factor of hundreds where gamma is high and xi low, and GGS from
the textbook speech-presence factor by up to 0.5, so the only
faithful copy is his numbers. They are stored as float32: the lookup
interpolates bilinearly on a 0.25 dB grid, and float32's 1e-7 error is
far below anything that grid resolves.

WDSP 2.10 (TAPR/OpenHPSDR-wdsp b02d5bac) was the source of the tables
shipped; GPL-2.0-or-later, see packaging/copyright.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent.parent / "ohscore" / "dsp" / "nr_tables.npz"


def table(src: str, name: str) -> np.ndarray:
    m = re.search(r"double\s+" + name + r"\s*\[\s*241\s*\*\s*241\s*\]\s*=\s*\{(.*?)\};", src, re.S)
    if m is None:
        raise SystemExit(f"{name} not found")
    vals = [float(v) for v in m.group(1).split(",") if v.strip()]
    if len(vals) != 241 * 241:
        raise SystemExit(f"{name}: {len(vals)} values, expected {241 * 241}")
    # WDSP indexes type[241 * n_xi + n_gamma]: rows are xi, columns gamma.
    return np.array(vals).reshape(241, 241).astype(np.float32)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1]).read_text()
    np.savez_compressed(OUT, GG=table(src, "GG"), GGS=table(src, "GGS"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
