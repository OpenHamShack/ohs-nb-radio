"""The parts of the scopes that are arithmetic rather than painting: the
pixel <-> frequency map and the waterfall's image ring buffer.

Kept free of widgets so they can be tested directly, and so the hot path is
plainly visible: one numpy resample and one LUT index per spectrum line, and
nothing at all per pixel in Python.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage, QPainter


class FreqMap:
    """Linear map between a frequency span [lo, hi] Hz and x in [x0, x0 + width]."""

    def __init__(self, lo: float, hi: float, width: float, x0: float = 0.0):
        self.set(lo, hi, width, x0)

    def set(self, lo: float, hi: float, width: float, x0: float = 0.0):
        if hi <= lo:
            hi = lo + 1.0
        self.lo, self.hi, self.width, self.x0 = float(lo), float(hi), max(1.0, float(width)), float(x0)

    @property
    def span(self) -> float:
        return self.hi - self.lo

    @property
    def hz_per_px(self) -> float:
        return self.span / self.width

    def x(self, f: float) -> float:
        return self.x0 + (f - self.lo) / self.span * self.width

    def f(self, x: float) -> float:
        return self.lo + (x - self.x0) / self.width * self.span

    def edges(self, n: int) -> np.ndarray:
        """Frequencies of the n+1 boundaries of n equal columns."""
        return self.lo + np.arange(n + 1, dtype=np.float64) * (self.span / n)


def resample(start: float, bin_hz: float, db: np.ndarray, lo: float, hi: float, n: int, fill: float) -> np.ndarray:
    """A spectrum line (bin i centred on start + i*bin_hz) as n columns over [lo, hi].

    Where a column covers several bins it takes their *maximum*, not the
    mean or a sample: on the wide view one pixel is ~280 Hz, and a CW signal
    or an FT8 tone is one bin - sampling would make it flicker in and out as
    the line's start drifts with rxCorr; averaging would bury it. Where a
    column is narrower than half a bin (zoomed in) it interpolates. Columns outside
    the line get `fill`.
    """
    db = np.asarray(db, np.float32)
    nb = len(db)
    span = hi - lo
    col_w = span / n
    out = np.full(n, fill, np.float32)
    if nb == 0:
        return out
    # Pool whenever a column is at least half a bin: at the default view a
    # column is ~1.07 bins, and interpolating there lands between bins and
    # shaves 10 dB off a one-bin carrier.
    if col_w >= 0.5 * bin_hz:
        fe = lo + np.arange(n + 1) * col_w
        idx = np.floor((fe - start) / bin_hz + 0.5).astype(np.int64)
        valid = (idx[1:] > 0) & (idx[:-1] < nb)
        i0 = np.clip(idx[:-1], 0, nb - 1)
        i1 = np.clip(idx[1:], 1, nb)
        i1 = np.maximum(i1, i0 + 1)
        # reduceat over ascending starts; each segment ends where the next begins,
        # which is exactly the column edge, so one call does every column.
        r = np.maximum.reduceat(db, i0)
        # reduceat's last segment runs to the end of db: clip it to the column.
        last = n - 1
        r[last] = db[i0[last]:i1[last]].max()
        out[valid] = r[valid]
        return out
    fc = lo + (np.arange(n) + 0.5) * col_w
    x = (fc - start) / bin_hz
    inside = (x >= -0.5) & (x <= nb - 0.5)
    out[inside] = np.interp(x[inside], np.arange(nb), db).astype(np.float32)
    return out


# The engine's scopes use a Hann window (ohscore/dsp/spectrum.py), whose
# equivalent noise bandwidth is 1.5 bins: the resolution bandwidth a line
# has before anything here widens it.
HANN_ENBW = 1.5


def rbw_line(db: np.ndarray, bin_hz: float, rbw_hz: float) -> tuple[np.ndarray, float]:
    """A spectrum line as a coarser analyser would draw it: (line, RBW Hz).

    Each bin becomes the power of the k = rbw_hz / bin_hz bins centred on
    it, summed and divided by the window's 1.5-bin noise bandwidth. That
    keeps the spectrum module's normalisation - a carrier still reads its
    own level, wherever it falls in the window - while anything wider than
    a bin gains what a wider filter would collect: white noise reads
    10 log10(k / 1.5) dB higher, a 1 kHz-wide PSK signal up to the same,
    a carrier nothing. So narrow and wide signals take the relative heights
    they have on an analyser with that RBW, which is how SDR Console's
    display differs from NB's fine bins (scope.py, DISPLAY_STYLES).

    Summed power rather than a mean of the dB values (which would read
    noise about 2.5 dB low and a carrier as an average with the floor), and
    a moving sum rather than k-bin blocks, so a carrier is a flat top k bins
    wide that cannot scallop as the line's start drifts with rxCorr. Under
    three bins nothing changes and the line is returned as it came: a
    carrier's main lobe is three bins, and a sum over fewer would read it
    low. The edges sum what is there, scaled up to k bins, so the ends of
    the view do not droop. `db` is never written to: the same array goes on
    to the window's receive SNR and the recorder."""
    db = np.asarray(db, np.float32)
    k = int(round(rbw_hz / bin_hz)) if bin_hz > 0 else 1
    n = len(db)
    if k < 3 or n == 0:
        return db, HANN_ENBW * bin_hz
    k = min(k, n)
    p = np.power(10.0, db.astype(np.float64) / 10.0)
    c = np.concatenate(([0.0], np.cumsum(p)))
    i = np.arange(n)
    lo = np.clip(i - k // 2, 0, n)
    hi = np.clip(i - k // 2 + k, 0, n)
    s = (c[hi] - c[lo]) * (k / np.maximum(1, hi - lo)) / HANN_ENBW
    return (10.0 * np.log10(np.maximum(s, 1e-20))).astype(np.float32), k * bin_hz


def hang_decay(level: np.ndarray, held: np.ndarray, held_t: np.ndarray, t: float, dt: float, hold: float,
               decay: float) -> None:
    """One step of a hang-and-decay trace, in place on `held`/`held_t`:
    each column rises at once to anything higher, stays `hold` seconds
    after it last rose, then falls at `decay` dB/s, never below `level`.
    The peak ghost's rule (ScopeView._update_peak) on a much shorter clock;
    it is what SDR Console's default "Hang & Decay" averaging is named for."""
    up = level >= held
    np.copyto(held, level, where=up)
    held_t[up] = t
    sink = (t - held_t) >= hold
    np.copyto(held, np.maximum(level, held - decay * dt), where=sink)


class Waterfall:
    """A QImage ring buffer, newest row on top.

    Each spectrum line becomes one row written into a numpy array that the
    QImage wraps (the image never owns or copies the memory). Painting is two
    blits - the rows from `head` to the bottom, then the rows above it - so
    history is never re-rendered, only moved when the view itself changes.
    """

    def __init__(self, width: int, height: int):
        self.lut = np.zeros(256, np.uint32)
        self.rows_total = 0
        self._alloc(max(1, width), max(1, height))

    def _alloc(self, w: int, h: int):
        self.w, self.h = w, h
        self.buf = np.zeros((h, w), np.uint32)
        self.buf[:] = self.blank()
        self.head = 0
        self.img = QImage(self.buf.data, w, h, w * 4, QImage.Format.Format_RGB32)

    def blank(self) -> int:
        """Rows with no history yet: the palette's floor colour, so a new
        or enlarged waterfall reads as "quiet", not as a black hole."""
        return int(self.lut[0]) if self.lut.any() else 0xFF06080C

    def set_lut(self, lut: np.ndarray):
        old_blank = self.blank()
        self.lut = lut
        self.buf[self.buf == old_blank] = self.blank()

    def resize(self, w: int, h: int):
        """New size; the old history is kept, stretched to the new width (a
        one-off cost when the operator resizes, never per frame)."""
        w, h = max(1, w), max(1, h)
        if (w, h) == (self.w, self.h):
            return
        old = self.ordered()
        self._alloc(w, h)
        cols = np.minimum((np.arange(w) * old.shape[1] / w).astype(np.int64), old.shape[1] - 1)
        rows = min(h, old.shape[0])
        self.buf[:rows] = old[:rows][:, cols]

    def ordered(self) -> np.ndarray:
        """The buffer with the newest row first (a copy)."""
        return np.concatenate([self.buf[self.head:], self.buf[:self.head]], axis=0)

    def remap(self, old_lo: float, old_hi: float, new_lo: float, new_hi: float, fill: int | None = None):
        """The view moved or zoomed: shift/stretch history so each column still
        shows the frequency it now stands for. Columns with no history take
        `fill` (the scope passes the colour its noise is drawn in), or the
        palette's floor colour without one."""
        w = self.w
        fc = new_lo + (np.arange(w) + 0.5) * (new_hi - new_lo) / w
        src = np.floor((fc - old_lo) / (old_hi - old_lo) * w).astype(np.int64)
        ok = (src >= 0) & (src < w)
        new = np.empty_like(self.buf)
        new[:, ok] = self.buf[:, src[ok]]
        new[:, ~ok] = self.lut[0] if fill is None else fill
        self.buf[:] = new

    def push_row(self, row_u32: np.ndarray):
        self.head = (self.head - 1) % self.h
        self.buf[self.head] = row_u32
        self.rows_total += 1

    def push_db(self, cols_db: np.ndarray, floor: float, rng: float):
        idx = np.clip((cols_db - floor) * (255.0 / max(1.0, rng)), 0, 255).astype(np.uint8)
        self.push_row(self.lut[idx])

    def draw(self, p: QPainter, target: QRectF):
        """Two blits; `target` is in logical pixels, the image in device pixels."""
        h = self.h
        top = h - self.head
        sy = target.height() / h
        if top > 0:
            p.drawImage(QRectF(target.x(), target.y(), target.width(), top * sy), self.img,
                        QRectF(0, self.head, self.w, top))
        if self.head > 0:
            p.drawImage(QRectF(target.x(), target.y() + top * sy, target.width(), self.head * sy), self.img,
                        QRectF(0, 0, self.w, self.head))


def running_max(a: np.ndarray, radius: int) -> np.ndarray:
    """out[i] = max(a[i - radius : i + radius + 1]), edges included, in
    O(n log radius) whole-array numpy steps: each pass doubles the width the
    running maximum covers, so 17 columns take five passes and no loop over
    columns."""
    n = len(a)
    width = 2 * radius + 1
    m = np.concatenate([np.full(radius, -np.inf, a.dtype), a, np.full(radius, -np.inf, a.dtype)])
    span = 1
    while span < width:
        step = min(span, width - span)
        m[:-step] = np.maximum(m[:-step], m[step:])
        span += step
    return m[:n]


def find_peaks(a: np.ndarray, threshold: float, radius: int = 8, most: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Columns of `a` that are the highest within `radius` columns either
    side and above `threshold`: (indices, sub-column offsets in -0.5..0.5
    from a parabola through the column and its neighbours). At most `most`,
    the strongest. Everything is whole-array: one running maximum, one
    comparison, one argpartition.

    The radius takes out the ripple on top of a wide signal (an SSB voice
    is all small maxima) before anything is counted, so a strong signal
    cannot crowd a weaker one out of the `most`."""
    n = len(a)
    if n < 3:
        return np.zeros(0, np.int64), np.zeros(0)
    peak = (a >= running_max(a, radius)) & (a > threshold)
    peak[0] = peak[-1] = False
    # A flat top would count every column of it; keep its first.
    peak[1:] &= a[1:] != a[:-1]
    idx = np.flatnonzero(peak)
    if len(idx) > most:
        idx = idx[np.argpartition(a[idx], -most)[-most:]]
    l, c, r = a[idx - 1].astype(np.float64), a[idx].astype(np.float64), a[idx + 1].astype(np.float64)
    den = l - 2 * c + r
    with np.errstate(divide="ignore", invalid="ignore"):
        off = np.where(den < 0, 0.5 * (l - r) / den, 0.0)
    return idx, np.clip(off, -0.5, 0.5)


class PeakMarkers:
    """The labelled peaks on a trace, kept steady.

    A set recomputed from scratch each time would flicker: two signals of
    about the same strength swap places in the top N, one on the threshold
    blinks in and out, and a label's text changes under the eye. So:

    - a marker already shown survives while its signal stays within
      `hyst` dB under the threshold, and is matched to its signal again by
      frequency even if that drifts a few columns;
    - a new signal takes a free place only if it is over the threshold,
      and takes a shown one's place only if it beats it by `displace` dB;
    - two maxima are one signal unless the trace dips at least `dip` dB
      below the weaker between them (SSB is one hump with many tops);
    - the scope calls update() a couple of times a second, not per line.
    """

    def __init__(self, hyst: float = 3.0, dip: float = 6.0, displace: float = 6.0):
        self.hyst, self.dip, self.displace = hyst, dip, displace
        self.marks: list[tuple[float, float]] = []        # (Hz, dB), strongest first

    def clear(self):
        self.marks = []

    def update(self, a: np.ndarray, col_hz: np.ndarray, floor: float, above: float, most: int,
               match_hz: float) -> list[tuple[float, float]]:
        """`a`: the trace; `col_hz`: each column's centre frequency (evenly
        spaced); `floor`: the noise floor; `above`: the threshold over it."""
        thr = floor + above
        idx, off = find_peaks(a, thr - self.hyst)
        if len(idx) == 0:
            self.marks = []
            return self.marks
        step = float(col_hz[1] - col_hz[0]) if len(col_hz) > 1 else 1.0
        f = col_hz[idx] + off * step
        lv = a[idx].astype(np.float64)
        order = np.argsort(-lv)
        idx, f, lv = idx[order], f[order], lv[order]
        used = np.zeros(len(idx), bool)
        kept: list[int] = []

        def same_signal(i: int, j: int) -> bool:
            lo, hi = sorted((int(idx[i]), int(idx[j])))
            return float(a[lo:hi + 1].min()) > min(lv[i], lv[j]) - self.dip

        # Shown markers first, each to the nearest unclaimed maximum.
        for mf, _mlv in self.marks:
            d = np.abs(f - mf)
            d[used] = np.inf
            j = int(np.argmin(d))
            if d[j] <= match_hz and not any(same_signal(j, k) for k in kept):
                used[j] = True
                kept.append(j)
        # Then new ones, strongest first, over the full threshold.
        for j in range(len(idx)):
            if used[j] or lv[j] <= thr or any(same_signal(j, k) for k in kept):
                continue
            if len(kept) >= most:
                weakest = min(kept, key=lambda k: lv[k])
                if lv[j] < lv[weakest] + self.displace:
                    continue
                kept.remove(weakest)
            used[j] = True
            kept.append(j)
        kept.sort(key=lambda k: -lv[k])
        self.marks = [(float(f[k]), float(lv[k])) for k in kept[:most]]
        return self.marks
