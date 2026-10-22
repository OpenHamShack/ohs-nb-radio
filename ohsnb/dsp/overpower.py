"""Over-power signals and AMSAT-DL's LEILA siren, found as they happen.

One definition, shared by the live watch (ohsnb/overpower.py runs it on a
worker thread of the radio) and the offline analyser (ohsnb/analyse_power.py
runs the same pieces over a recording): a recording analysed afterwards
reads as the live watch showed it.

**Over-power**: a downlink with more power in a beacon-wide slice
(RBW_HZ) than the middle beacon has in its own, by at least MARGIN_DB,
outside the beacons' guard zones, both measured on the same spectral
line. AMSAT-DL's rule is "keep your signal below the beacon level"
(docs/qo100-research.md section 9). Until 17/10/2026 this compared the
strongest 15 Hz bin of each signal with the beacon's: on Brian's two
recordings of real LEILA sirens every ordinary FT8 caller in the 7P8GE
pile-up read 15-24 dB "over" by that measure, because an FT8 tone puts all
its power in one bin and the 400 bd BPSK beacon spreads over ~600 Hz.
Power against power, in the same bandwidth, does not depend on how narrow
either signal is.

**LEILA**: AMSAT-DL's ground station marks an over-power signal with a
siren. Measured on real ones (17/10/2026, section 9): two steady tones
205-213 Hz apart, alternating every 200 ms (a 400 ms cycle), switched hard,
for 3-6 s, at about 2 dB more power than the beacon - placed where the
offender transmits, and heard in the FT8 slot after its over. `Siren` looks
for exactly that pattern across the whole transponder: two bins SIREN_
SPACING apart whose power each swings at 2.5 Hz, in antiphase. It needs no
over-power event first, so it finds the siren whoever it is aimed at. Six
sirens from one evening are all the evidence there is: what LEILA's
threshold is (the pile-up was full of stations over the beacon and only six
were marked in 13 minutes) remains unknown, so the UI still says "LEILA?" -
see the docs.

No threads and no engine here.
"""
from __future__ import annotations

import time

import numpy as np

from ohscore.dsp.bank import Geometry
from ohscore.dsp.spectrum import Scope, wide_nfft

from .. import bandplan

MARGIN_DB = 3.0        # over the middle beacon's power, in the same bandwidth, to count as "over-power"
RBW_HZ = 1_000.0       # the bandwidth compared: the middle beacon's 400 bd BPSK, all but its skirts
MIN_DURATION_S = 2.0   # shorter than this is a single noisy line, not an event
NFFT_BINS = 8_192      # over the transponder: ~61 Hz bins, fine enough to add up an RBW_HZ slice. It was
                       # 32 768 (15 Hz) while single bins were compared, and that FFT alone was 4 % of a
                       # core for the live watch
AVG = 16
FPS = 1.0              # one spectral line a second: fine enough for "how long" to mean something
BEACON_WINDOW_HZ = 1_500.0    # the middle beacon's own BPSK bandwidth, +-, read as its instantaneous level
GUARD_HZ = 1_500.0            # excluded around each of the three beacons' own reference frequencies
MATCH_HZ = 400.0       # how close two lines' hits must be in frequency to be judged the same signal
GAP_LINES = 2          # lines a signal may go undetected for (a fade) before its event is closed

BEACON_SNR_DB = 10.0   # the beacon's slice must stand this far over the transponder's median slice, or there
                       # is no beacon to compare with (a dish off the satellite) and nothing is judged
KEEP_S = 30 * 60.0     # ended events are kept this long

# LEILA's siren, as measured (module docstring; docs/qo100-research.md section 9).
SIREN_SPACING_HZ = (150.0, 260.0)   # the two tones: 205-206 Hz apart both times
SIREN_CYCLE_HZ = 2.5     # one cycle = both tones, 200 ms each
SIREN_WINDOW_S = 2.0     # five cycles looked at at once: a 3 s siren is still seen whole twice
SIREN_EVERY_S = 0.25
SIREN_DEPTH = 0.45       # each tone's power swing at the cycle rate over its mean: 0.64 for a hard on/off
                         # tone (0.57-0.65 measured), ~0.1 for noise or an FT8 signal
SIREN_CORR = -0.7        # the two tones' power series' correlation, at most (see Siren._look)
SIREN_MIN_LOOKS = 3      # looks in a row (0.5 s) before a siren is reported
SIREN_ANTI_DEG = 50.0    # the two tones' swings must be in antiphase, within this
SIREN_SNR_DB = 8.0       # each tone, while on, over the floor around it
SIREN_MATCH_HZ = 100.0   # detections this close are the same siren
SIREN_GAP_S = 1.0        # unseen this long and it has ended
SIREN_AFTER_S = 20.0     # a siren this soon after an over-power event ended is taken to be about it
SIREN_BEACON_HZ = 1_300.0    # the middle beacon's power, for the siren's level: +-this around it


def line_hits(freqs: np.ndarray, db: np.ndarray, ref_db: float, exclude: list[tuple[float, float]],
              margin_db: float) -> list[tuple[float, float, float]]:
    """Contiguous runs of `freqs` (already restricted to the span of
    interest) where db is more than margin_db over ref_db, with the
    exclusion windows removed first: [(f_lo, f_hi, max_excess_db)]."""
    excess = db - ref_db
    over = excess > margin_db
    for lo, hi in exclude:
        over &= ~((freqs >= lo) & (freqs <= hi))
    runs = []
    start = None
    for i, v in enumerate(np.append(over, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((float(freqs[start]), float(freqs[i - 1]), float(excess[start:i].max())))
            start = None
    return runs


def beacon_guards() -> list[tuple[float, float]]:
    return [(b["ref"] - GUARD_HZ, b["ref"] + GUARD_HZ) for b in bandplan.BEACONS.values()]


class Tracker:
    """Hits on successive spectral lines, joined into events by frequency
    (a signal does not jump bands between one line and the next): each
    open event remembers its frequency range (widened to whichever line's
    hit was widest) and the line it was last seen on, and is closed once
    unseen for more than GAP_LINES lines running - a Rician fade across a
    weak excess should not split one event into several."""

    def __init__(self):
        self.open: list[dict] = []
        self.closed: list[dict] = []

    def add_line(self, hits: list[tuple[float, float, float]], t: float) -> None:
        used = [False] * len(hits)
        for ev in self.open:
            best, best_i = None, -1
            for i, (lo, hi, exc) in enumerate(hits):
                if used[i]:
                    continue
                if lo <= ev["f_hi"] + MATCH_HZ and hi >= ev["f_lo"] - MATCH_HZ:
                    if best is None or exc > best[2]:
                        best, best_i = (lo, hi, exc), i
            if best is not None:
                used[best_i] = True
                ev["f_lo"], ev["f_hi"] = min(ev["f_lo"], best[0]), max(ev["f_hi"], best[1])
                ev["max_excess_db"] = max(ev["max_excess_db"], best[2])
                ev["now_lo"], ev["now_hi"] = best[0], best[1]
                ev["t_last"] = t
                ev["misses"] = 0
            else:
                ev["misses"] += 1
        # An event unseen for more than GAP_LINES lines moves to `closed`
        # and leaves `open` - both halves matter. The first version filtered
        # with `misses <= GAP_LINES or self._close(e) is None`, and since
        # _close returned None that kept every closed event in `open` too:
        # it was appended to `closed` again on every later line (127,029
        # "events" from 10 minutes of the real 07/10/2026 recording, most
        # of them copies), stayed matchable so the next station near its
        # frequency revived it (one 599 s, 1.3 kHz-wide "event" spanning
        # every FT8 signal of the slice), and the LEILA check then read
        # each copy's whole span of IQ - the ~58 GB that OOM-killed the
        # 3-hour --extended run twice. Synthetic tests never hit it: a
        # signal that never goes away is never closed.
        still_open = []
        for e in self.open:
            if e["misses"] <= GAP_LINES:
                still_open.append(e)
            else:
                self.closed.append(e)
        self.open = still_open
        for i, (lo, hi, exc) in enumerate(hits):
            if not used[i]:
                self.open.append({"f_lo": lo, "f_hi": hi, "now_lo": lo, "now_hi": hi, "max_excess_db": exc,
                                  "t_start": t, "t_last": t, "misses": 0})

    def finish(self) -> list[dict]:
        for ev in self.open:
            self.closed.append(ev)
        self.open = []
        return self.closed


def judge_line(freqs: np.ndarray, db: np.ndarray, bin_hz: float, margin_db: float = MARGIN_DB,
               guards: list[tuple[float, float]] | None = None) -> tuple[str, list[tuple[float, float, float]]]:
    """One spectral line (dB per bin at `freqs`, dial Hz) judged against
    the middle beacon: ("ok", [(f_lo, f_hi, excess_db)]) for each signal
    with more power in an RBW_HZ slice than the beacon has in its own by
    margin_db, f_lo-f_hi being where its own bins are (within 20 dB of its
    peak); or ("none" | "weak", []) when there is no beacon on the line to
    compare with."""
    in_dl = (freqs >= bandplan.DL_LO) & (freqs <= bandplan.DL_HI)
    mid = bandplan.BEACONS["middle"]["ref"]
    near_mid = np.abs(freqs - mid) <= BEACON_WINDOW_HZ
    if not near_mid.any() or not in_dl.any():
        return "none", []
    # Power in an RBW_HZ slice centred on each bin: a running sum of the
    # line's linear power (cumsum: one pass, whatever the width).
    k = max(1, int(round(RBW_HZ / bin_hz)))
    lin = np.power(10.0, db.astype(np.float64) / 10.0)
    c = np.concatenate([[0.0], np.cumsum(lin)])
    half = k // 2
    lo_i = np.clip(np.arange(len(lin)) - half, 0, len(lin))
    hi_i = np.clip(np.arange(len(lin)) - half + k, 0, len(lin))
    slice_db = 10.0 * np.log10(np.maximum(c[hi_i] - c[lo_i], 1e-30))
    ref = float(slice_db[near_mid].max())
    if ref - float(np.median(slice_db[in_dl])) < BEACON_SNR_DB:
        return "weak", []
    runs = line_hits(freqs[in_dl], slice_db[in_dl], ref, guards if guards is not None else beacon_guards(),
                     margin_db)
    out = []
    f_dl, db_dl = freqs[in_dl], db[in_dl]
    for lo, hi, exc in runs:
        # A slice is over wherever the signal is anywhere in it, so the run
        # is RBW_HZ wider than the signal: its own bins say where it is.
        m = (f_dl >= lo) & (f_dl <= hi)
        sub_f, sub_db = f_dl[m], db_dl[m]
        own = sub_f[sub_db >= sub_db.max() - 20.0]
        out.append((float(own.min()), float(own.max()), exc))
    return "ok", out


class Siren:
    """LEILA's siren (the module docstring) in the filter bank's spectra.

        s = Siren(geo)
        s.push(X, starts, base)     # every block, in order; base = the dial at the stream's DC
        s.sirens                    # [event dict], oldest first: open and ended

    Each frame's bins over the transponder (or `span`, dial Hz) are
    Hann-windowed in the frequency domain (three neighbouring bins, as the
    band skimmer does: no second FFT) and their power kept for
    SIREN_WINDOW_S; every SIREN_EVERY_S the window is asked, for every bin
    at once, how much of its power swings at SIREN_CYCLE_HZ and in which
    phase - one complex dot product per bin. A siren is a pair of peak
    bins SIREN_SPACING_HZ apart, both swinging deeply, in antiphase. At
    1.2 MS/s that is ~10 000 bins x 133 frames, a few milliseconds each
    time."""

    def __init__(self, geo: Geometry, span: tuple[float, float] | None = None, keep_s: float = KEEP_S):
        self.geo = geo
        self.span = span or (bandplan.DL_LO, bandplan.DL_HI)
        self.keep_s = keep_s
        self.df = geo.fs / geo.N
        self.frame_s = geo.L / geo.fs
        self.nbins = int(np.ceil((self.span[1] - self.span[0]) / self.df)) + 4
        self.depth_frames = int(round(SIREN_WINDOW_S / self.frame_s))
        self.ring = np.zeros((self.depth_frames, self.nbins), np.float32)
        self.times = np.zeros(self.depth_frames)
        self.filled = 0
        self.pos = 0
        self.k0: int | None = None
        self.next_look = 0.0
        self.sirens: list[dict] = []
        self.guards = beacon_guards()
        self.level_db: float | None = None

    def push(self, X: np.ndarray, starts: np.ndarray, base: float) -> bool:
        """Returns whether a siren started, moved on or ended."""
        if X.shape[0] == 0:
            return False
        N = self.geo.N
        k0 = int(np.floor((self.span[0] - base) / self.df)) - 2
        if self.k0 is not None and k0 != self.k0:
            # Beacon lock moved rxCorr across a bin: the kept power moves
            # with it rather than being thrown away.
            dk = k0 - self.k0
            self.ring = np.roll(self.ring, -dk, axis=1)
            if dk > 0:
                self.ring[:, -dk:] = 0.0
            else:
                self.ring[:, :-dk] = 0.0
        self.k0 = k0
        idx = (np.arange(k0 - 1, k0 + self.nbins + 1)) % N
        Y = X[:, idx]
        H = Y[:, 1:-1] - 0.5 * (Y[:, :-2] + Y[:, 2:])
        P = (H.real ** 2 + H.imag ** 2).astype(np.float32)
        t = (starts + N / 2) / self.geo.fs
        changed = False
        rows = (self.pos + np.arange(len(P))) % self.depth_frames
        self.ring[rows] = P[-self.depth_frames:] if len(P) > self.depth_frames else P
        self.times[rows] = t[-self.depth_frames:] if len(t) > self.depth_frames else t
        self.pos = int((self.pos + len(P)) % self.depth_frames)
        self.filled = min(self.filled + len(P), self.depth_frames)
        now = float(t[-1])
        if self.filled == self.depth_frames and now >= self.next_look:
            self.next_look = now + SIREN_EVERY_S
            changed = self._look(now, base)
        return changed

    def _look(self, now: float, base: float) -> bool:
        P, t = self.ring, self.times
        mean = P.mean(axis=0)
        ph = np.exp(-2j * np.pi * SIREN_CYCLE_HZ * t).astype(np.complex64)
        A = ph @ P / len(t)
        depth = np.abs(A) / np.maximum(mean, 1e-30)
        freqs = base + (self.k0 + np.arange(self.nbins)) * self.df
        # The floor around each bin: the 20th percentile of 200-bin (10 kHz)
        # blocks, as the band skimmer measures it (the transponder's floor is
        # not flat over 500 kHz).
        nb = -(-self.nbins // 200)
        # (The short last block is padded with copies of itself's end.)
        padded = np.concatenate([mean, np.full(nb * 200 - self.nbins, mean[-1], mean.dtype)])
        floor = np.repeat(np.percentile(padded.reshape(nb, 200), 20, axis=1), 200)[: self.nbins]
        on = 2.0 * mean     # a tone on half the time
        cand = (depth >= SIREN_DEPTH) & (on >= floor * 10 ** (SIREN_SNR_DB / 10.0))
        cand[0] = cand[-1] = False
        # Peaks of the swinging power, not of the power: a siren tone beside a
        # steady station (on 17/10 the lower tone sat 50 Hz from an FT8
        # signal 5 dB stronger) is a peak only of what swings.
        swing = np.abs(A)
        cand &= (swing >= np.roll(swing, 1)) & (swing >= np.roll(swing, -1))
        for lo, hi in self.guards:
            cand &= ~((freqs >= lo - self.df) & (freqs <= hi + self.df))
        ks = np.flatnonzero(cand)
        found = []
        dmin, dmax = SIREN_SPACING_HZ[0] / self.df, SIREN_SPACING_HZ[1] / self.df
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if b - a > dmax + 1:
                    break
                if b - a < dmin - 1:
                    continue
                dphi = abs(np.angle(A[a] * np.conj(A[b]), deg=True))
                if abs(dphi - 180.0) > SIREN_ANTI_DEG:
                    continue
                fa, fb = self._refine(swing, a, freqs), self._refine(swing, b, freqs)
                if not (SIREN_SPACING_HZ[0] <= fb - fa <= SIREN_SPACING_HZ[1]):
                    continue
                # The two tones take turns: while one is on the other is off, so
                # their power series are strongly anticorrelated. Measured -0.85
                # to -0.96 on the three real sirens; a voice's harmonics or two
                # stations that happen to swing in antiphase for a moment are
                # near 0 (the replay of 17/10/2026's recordings: 700 pairs
                # passed the depth and phase tests, none of them this one).
                pa, pb_ = P[:, a] - P[:, a].mean(), P[:, b] - P[:, b].mean()
                corr = float((pa * pb_).sum() / np.sqrt((pa * pa).sum() * (pb_ * pb_).sum() + 1e-30))
                if corr > SIREN_CORR:
                    continue
                lvl = self._level(mean, floor, a, b, freqs)
                found.append((fa, fb, lvl))
        return self._track(found, now)

    def _refine(self, mean: np.ndarray, k: int, freqs: np.ndarray) -> float:
        """A tone's frequency to a few Hz: the parabola through its bin and
        the two beside it, in dB."""
        y0, y1, y2 = 10 * np.log10(np.maximum(mean[k - 1:k + 2], 1e-30))
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den < 0 else 0.0
        return float(freqs[k] + max(-0.5, min(0.5, d)) * self.df)

    def _level(self, mean, floor, a, b, freqs) -> float | None:
        """The siren's power over the middle beacon's, dB, both from the same
        window of the same spectra (the Hann weighting cancels)."""
        mid = bandplan.BEACONS["middle"]["ref"]
        m = np.abs(freqs - mid) <= SIREN_BEACON_HZ
        if not m.any():
            return None
        pb = float((mean[m] - floor[m]).clip(0).sum())
        ps = float(sum((mean[k - 1:k + 2] - floor[k - 1:k + 2]).clip(0).sum() for k in (a, b)))
        if pb <= 0 or ps <= 0:
            return None
        return 10.0 * np.log10(ps / pb)

    def _track(self, found: list, now: float) -> bool:
        changed = False
        for fa, fb, lvl in found:
            mid = (fa + fb) / 2.0
            ev = next((e for e in self.sirens if e["open"] and abs(e["freq"] - mid) <= SIREN_MATCH_HZ), None)
            if ev is None:
                ev = {"open": True, "t_start": now - SIREN_WINDOW_S / 2, "levels": [], "freq": mid}
                self.sirens.append(ev)
            if ev.get("looks", 0) + 1 == SIREN_MIN_LOOKS:
                changed = True
            ev.update(t_last=now, freq=mid, lo=fa, hi=fb, looks=ev.get("looks", 0) + 1)
            if lvl is not None:
                ev["levels"].append(lvl)
        for ev in self.sirens:
            if ev["open"] and now - ev["t_last"] > SIREN_GAP_S:
                ev["open"] = False
                ev["t_end"] = ev["t_last"] - SIREN_WINDOW_S / 2
                changed |= ev["looks"] >= SIREN_MIN_LOOKS
        cut = now - self.keep_s
        # A pattern seen fewer than SIREN_MIN_LOOKS times running is dropped.
        self.sirens = [e for e in self.sirens if e["open"] or (e["looks"] >= SIREN_MIN_LOOKS and e["t_end"] >= cut)]
        return changed

    @staticmethod
    def level_of(ev: dict) -> float | None:
        return round(float(np.median(ev["levels"])), 1) if ev["levels"] else None


class Detector:
    """The live watch's arithmetic: over-power from spectral lines of the
    wideband stream (as the wide scope gets it, but always with the
    analyser's own Scope, so its numbers never depend on the operator's
    scope settings), and LEILA's siren from the filter bank's spectra.

        d = Detector(geo)
        d.lines(x, base, beacon_ok)      # wideband samples, in order
        d.spectra(X, starts, base)       # each block's spectra
        d.events(now)                    # [event dict], open first then newest first

    `base` is the downlink at the stream's DC (Radio._dial_at(0)), so
    frequencies are dial frequencies with rxCorr taken out, beacons on
    their nominal marks. `beacon_ok` says beacon lock trusts where the
    beacon is; without it no line is judged (an unlocked "beacon" is
    whatever is there). Both return whether the list changed. Times in
    events are Unix seconds, from `clock` (the stream's own time mapped
    through the last block's arrival)."""

    def __init__(self, geo: Geometry, margin_db: float = MARGIN_DB, min_duration_s: float = MIN_DURATION_S):
        self.geo = geo
        self.margin_db = margin_db
        self.min_duration_s = min_duration_s
        span = bandplan.DL_HI - bandplan.DL_LO
        self.nfft = wide_nfft(NFFT_BINS, geo.fs, span)
        self.scope = Scope(geo.fs, self.nfft, fps=FPS, avg=AVG)
        self.offsets = (np.arange(self.nfft) - self.nfft // 2) * self.scope.bin_hz
        self.tracker = Tracker()
        self.siren = Siren(geo)
        self.guards = beacon_guards()
        self.n = 0                    # samples taken
        self.wall_end = 0.0           # Unix time of the last sample taken
        self.next_id = 1
        self.done: list[dict] = []    # ended over-power events, oldest first
        self.beacon = "none"          # ok, unlocked, weak, none: whether the last line could be judged

    def lines(self, x: np.ndarray, base: float, beacon_ok: bool, wall_end: float | None = None) -> bool:
        self.n += len(x)
        self.wall_end = time.time() if wall_end is None else wall_end
        changed = False
        for end, db in self.scope.process(x):
            changed |= self._line(end / self.geo.fs, db, base, beacon_ok)
        return changed

    def spectra(self, X: np.ndarray, starts: np.ndarray, base: float) -> bool:
        return self.siren.push(X, starts, base)

    def wall(self, t: float) -> float:
        return self.wall_end - (self.n / self.geo.fs - t)

    def _line(self, t: float, db: np.ndarray, base: float, beacon_ok: bool) -> bool:
        hits: list = []
        if not beacon_ok:
            self.beacon = "unlocked"
        else:
            self.beacon, hits = judge_line(base + self.offsets, db, self.scope.bin_hz, self.margin_db, self.guards)
        was_open = len(self.tracker.open)
        self.tracker.add_line(hits, t)
        changed = bool(hits) or was_open != len(self.tracker.open) or bool(self.tracker.closed)
        for e in self.tracker.open:
            if "id" not in e:
                e["id"] = self.next_id
                self.next_id += 1
        for e in self.tracker.closed:
            if e["t_last"] - e["t_start"] >= self.min_duration_s:
                e["wall_start"], e["wall_end"] = self.wall(e["t_start"]), self.wall(e["t_last"])
                self.done.append(e)
        self.tracker.closed = []
        cut = self.wall_end - KEEP_S
        while self.done and self.done[0]["wall_end"] < cut:
            self.done.pop(0)
        return changed

    # ------------------------------------------------------------ the list
    def events(self) -> list[dict]:
        """Over-power events at least min_duration_s long and LEILA sirens,
        the open ones first, then the ended ones newest first, as plain
        dicts (ENGINE-API `overpower`). An over-power event a siren landed
        on (during it or within SIREN_AFTER_S after: LEILA sounds in the
        FT8 slot after the over) carries `leila` true and the siren's id."""
        sirens = []
        for s in self.siren.sirens:
            if s["looks"] < SIREN_MIN_LOOKS:
                continue
            if "id" not in s:
                s["id"] = self.next_id
                self.next_id += 1
            start, end = self.wall(s["t_start"]), self.wall(s["t_last"] if s["open"] else s["t_end"])
            sirens.append({"kind": "leila", "id": s["id"], "start": round(start, 1), "end": round(end, 1),
                           "active": s["open"], "freq": round(s["freq"], 1), "lo": round(s["lo"], 1),
                           "hi": round(s["hi"], 1), "width": round(s["hi"] - s["lo"], 1),
                           "levelDb": Siren.level_of(s), "leila": True, "on": None})
        ops = []
        for e, active in [(e, True) for e in self.tracker.open
                          if e["t_last"] - e["t_start"] >= self.min_duration_s] + \
                         [(e, False) for e in reversed(self.done)]:
            start = self.wall(e["t_start"]) if active else e["wall_start"]
            end = self.wall(e["t_last"]) if active else e["wall_end"]
            lo, hi = e["f_lo"], e["f_hi"]
            hit = next((s for s in sirens if s["hi"] >= lo - SIREN_MATCH_HZ and s["lo"] <= hi + SIREN_MATCH_HZ
                        and start - 1.0 <= s["start"] <= end + SIREN_AFTER_S), None)
            if hit is not None and hit["on"] is None:
                hit["on"] = e["id"]
            ops.append({"kind": "overpower", "id": e["id"], "start": round(start, 1), "end": round(end, 1),
                        "active": active, "freq": round((lo + hi) / 2.0, 1), "lo": round(lo, 1),
                        "hi": round(hi, 1), "width": round(hi - lo, 1), "excessDb": round(e["max_excess_db"], 1),
                        "leila": hit is not None, "siren": hit["id"] if hit else None})
        both = ops + sirens
        return sorted(both, key=lambda e: (not e["active"], -e["start"]))


__all__ = ["Detector", "Siren", "Tracker", "judge_line", "line_hits", "MARGIN_DB"]
