#!/usr/bin/env python3
"""Character error rate of the CW decoder, heard through NB's own receiver.

    tools/cw_bench.py [--seeds 3] [--snr 0,3,6,9,12,15] [--only beacon,...]
    tools/cw_bench.py --recording BEACON.npy   # complex 12 kHz, space tone at 0 Hz
    tools/cw_bench.py --corpus MANIFEST.json [--dir ~/build/cw-corpus] [--show]

The decoder and the bench moved to ohs-libs' shack_cw (10/10/2026); its
docstring (shack_cw/bench.py) describes every case. This runs the same
cases through ohscore.dsp.demod.Demod - the CW filter and medium AGC the
engine really uses, in its 75 ms blocks - rather than the bench's copy
of it, so a change to NB's receiver that moves the decoder's numbers shows
here. The two print the same table today, decode for decode.

--corpus scores the decoder on recordings of the real bands the same way
(shack_cw.corpus; ohs-libs python/shack_cw/tools/cw_corpus.py records
them), each target through a Demod with the filter width it asks for -
Brian's 20 m report of 13/10/2026 was Radio with a wide CW filter.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib  # noqa: E402

from ohscore import shacklibs  # noqa: E402
from ohscore.dsp.demod import Demod  # noqa: E402

shacklibs.cw()       # installed, else the pinned wheel onto the path
bench = importlib.import_module("shack_cw.bench")


def nb_receiver(rate: float, pitch: float, width: float = 500.0):
    """NB's demodulator as the engine configures it for CW (by default: a
    500 Hz filter round the pitch, medium AGC)."""
    d = Demod(rate)
    d.configure("cw", pitch - width / 2, pitch + width / 2, "medium", 0.0)
    return lambda iq: d(iq)[0]


def run_case(name: str, snr: float, seed: int, decoder=None):
    return bench.run_case(name, snr, seed, decoder, receiver=nb_receiver)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--corpus" in argv:
        i = argv.index("--corpus")
        corpus = importlib.import_module("shack_cw.corpus")
        return corpus.main(argv[:i] + argv[i + 1:], receiver=nb_receiver)
    return bench.main(argv, receiver=nb_receiver)


if __name__ == "__main__":
    raise SystemExit(main())
