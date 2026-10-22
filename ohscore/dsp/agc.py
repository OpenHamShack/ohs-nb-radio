"""Block-vectorised gain control: the receiver AGC, the speech compressor
and the transmit ALC are the same peak-follower with different numbers.

The envelope is the per-chunk peak (2.5 ms chunks at 12 kHz), held for a
hang time and then decaying at a fixed dB/s - instant attack, slow decay.
"Peak held then decaying linearly in dB" is a running maximum of
(peak_j - decay * (i - j - hang)), which splits into a sliding maximum over
the hang window and a cumulative maximum - both numpy primitives - so there is
no loop over samples or even over chunks.
"""
from __future__ import annotations

import numpy as np

PRESETS = {  # name: (hang seconds, decay dB/s)
    "fast": (0.05, 60.0),
    "medium": (0.25, 20.0),
    "slow": (1.0, 8.0),
}


class PeakGain:
    def __init__(self, rate: float, target: float = 0.25, max_gain_db: float = 90.0, min_gain_db: float = -60.0,
                 hang: float = 0.25, decay_db_s: float = 20.0, chunk: int = 30):
        self.rate, self.chunk = rate, chunk
        self.target_db = 20 * np.log10(target)
        self.max_gain_db, self.min_gain_db = max_gain_db, min_gain_db
        self.set_timing(hang, decay_db_s)
        self.tail = np.full(self.h, -200.0)
        self.C = -np.inf      # max over older chunks of (p_j + j*delta), j relative to tail start
        self.last_gain_db = 0.0
        self.env_db = -200.0

    def set_timing(self, hang: float, decay_db_s: float):
        self.h = max(0, int(round(hang * self.rate / self.chunk)))
        self.delta = decay_db_s * self.chunk / self.rate
        old = getattr(self, "tail", None)
        if old is not None:
            t = np.full(self.h, -200.0)
            k = min(len(old), self.h)
            if k:
                t[-k:] = old[-k:]
            self.tail = t

    def gains_db(self, mag: np.ndarray) -> np.ndarray:
        """Per-chunk gain (dB) for a block of magnitudes."""
        n = len(mag)
        starts = np.arange(0, n, self.chunk)
        p = 20 * np.log10(np.maximum.reduceat(mag, starts) + 1e-12)
        h, d = self.h, self.delta
        P = np.concatenate([self.tail, p])
        t0 = len(self.tail)
        i = np.arange(t0, len(P))
        # Within the hang window: plain sliding maximum.
        padded = np.concatenate([np.full(h, -np.inf), P])
        A = np.lib.stride_tricks.sliding_window_view(padded, h + 1).max(axis=1)[t0:]
        # Beyond it: max over j <= i-h-1 of (P_j + j d) - (i-h) d.
        q = np.maximum.accumulate(np.concatenate([[self.C], P + np.arange(len(P)) * d]))
        jmax = i - h - 1                       # index into P; q[jmax+1] covers P[..jmax] and C
        B = q[np.clip(jmax + 1, 0, None)] - (i - h) * d
        env = np.maximum(A, B)
        g = np.clip(self.target_db - env, self.min_gain_db, self.max_gain_db)
        # Carry state: keep the last h peaks, fold older ones into C.
        s = len(P) - h
        if s > 0:
            older = (P[:s] + np.arange(s) * d).max()
            self.C = max(self.C, older) - s * d
        self.tail = P[s:] if h else np.zeros(0)
        self.env_db = float(env[-1]) if len(env) else self.env_db
        return g

    def __call__(self, x: np.ndarray, mag: np.ndarray | None = None) -> np.ndarray:
        """Apply the gain to x (real or complex). Within a chunk the gain is
        the lower of the chunk's own (so a peak never overshoots) and a ramp
        between chunk centres (so decay is smooth, not stepped)."""
        n = len(x)
        if n == 0:
            return x
        if mag is None:
            mag = np.abs(x)
        g = self.gains_db(mag)
        step = np.repeat(g, self.chunk)[:n]
        centres = np.arange(len(g)) * self.chunk + self.chunk / 2
        ramp = np.interp(np.arange(n), np.concatenate([[-self.chunk / 2], centres]),
                         np.concatenate([[self.last_gain_db], g]))
        gd = np.minimum(step, ramp)
        self.last_gain_db = float(g[-1])
        # Kept for the receive noise reduction, which works on the audio as
        # it was before this gain (ohscore/dsp/nr.py says why).
        self.gain = 10 ** (gd / 20)
        return (x * self.gain).astype(x.dtype)


class Agc(PeakGain):
    def __init__(self, rate: float, preset: str = "medium"):
        hang, decay = PRESETS.get(preset, PRESETS["medium"])
        super().__init__(rate, target=0.3, max_gain_db=100.0, min_gain_db=-40.0, hang=hang, decay_db_s=decay)

    def set_preset(self, preset: str):
        hang, decay = PRESETS.get(preset, PRESETS["medium"])
        self.set_timing(hang, decay)
