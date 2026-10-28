#!/usr/bin/env python3
"""Was anything on the channel? tools/capture-and-test.sh asks this of a
dmr capture before it believes the decoder test: GB7IR was silent for the
whole of the first real capture (28/10/2026) and dmr_real's "no DMR sync
at all" read as a decoder failure.

    python3 tools/iq_activity.py <file.sigmf-meta> <channelHz>

prints "<active> <seconds>": how many whole seconds of the capture had
traffic in +-6 kHz of the channel. Each second's power there (a few FFTs
spread over the second, averaged) counts as active when it is 6 dB over
the 10th percentile of all the seconds - the channel's own quiet - or
10 dB over the same width 25-50 kHz either side, so a channel busy for
the whole capture, whose 10th percentile is itself traffic, still counts.
ci16_le or cf32_le, as Radio records them.
"""
import json
import sys
from pathlib import Path

import numpy as np

HALF = 6_000.0
NFFT = 4096
PER_SECOND = 16       # FFTs a second: enough to see a 30 ms DMR burst, cheap on 10 minutes at 6 MS/s


def seconds_power(meta_path: Path, channel: float):
    meta = json.loads(meta_path.read_text())
    rate = float(meta["global"]["core:sample_rate"])
    dtype = meta["global"]["core:datatype"]
    centre = float(meta["captures"][0]["core:frequency"])
    raw = np.memmap(meta_path.with_suffix(".sigmf-data"), dtype=np.int16 if dtype == "ci16_le" else np.float32,
                    mode="r")
    n = len(raw) // 2
    freqs = np.fft.fftfreq(NFFT, 1 / rate)
    off = channel - centre
    inside = np.abs(freqs - off) <= HALF
    beside = (np.abs(freqs - off) >= 25_000) & (np.abs(freqs - off) <= 50_000)
    win = np.hanning(NFFT)
    out = []
    for s in range(int(n // rate)):
        starts = np.linspace(s * rate, (s + 1) * rate - NFFT, PER_SECOND).astype(int)
        p = np.zeros(NFFT)
        for a in starts:
            iq = raw[2 * a:2 * (a + NFFT)].astype(np.float32)
            p += np.abs(np.fft.fft((iq[0::2] + 1j * iq[1::2]) * win)) ** 2
        pin = p[inside].mean() if inside.any() else 0.0
        pbeside = p[beside].mean() if beside.any() else np.inf
        out.append((pin, pbeside))
    return out


def main(argv):
    secs = seconds_power(Path(argv[0]), float(argv[1]))
    if not secs:
        print(0, 0)
        return 0
    pin = np.array([a for a, _ in secs])
    floor = np.percentile(pin, 10)
    active = sum(1 for a, b in secs if a > floor * 10 ** 0.6 or a > b * 10)
    print(active, len(secs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
