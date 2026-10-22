"""The band skimmer: every signal on the narrowband transponder, found,
followed and named, continuously, from the wide receive IQ.

No threads and no engine here (ohsnb/skimmer.py runs it on a worker thread
of its own); it is fed the filter bank's spectra, the same ones every
channel is cut from (ohscore/dsp/bank.py), and keeps a list of signals.
tools/skimmer_eval.py runs exactly this over recordings.

Three layers, cheapest first:

1. **A band spectrum, every second.** The bank's forward FFT already
   exists for every frame (24 000 points at 1.2 MS/s: 50 Hz bins); the
   transponder's 10 000 of them are windowed in the frequency domain
   (Hann is three neighbouring bins, so no second FFT) and their power
   summed. One line a second, the last four averaged, against a noise
   floor measured in 10 kHz blocks (the transponder's floor is not flat
   over 500 kHz - analyse.py's OUTSIDE_GUARD comment): runs over it are
   signals, by the same run-finder auto-tune and the band census use
   (ohscore.dsp.autotune.occupied).

2. **Tracks.** A run is matched to the signal it continues (by overlap),
   so a station keeps its identity, its answer and its age between lines.
   A track not seen for QUIET_S is quiet (an SSB QSO between overs), and
   after FORGET_S it is forgotten.

3. **Looks.** What the spectrum cannot say, a short listen does, on a
   channel cut from the same spectra (cheap: a few hundred bins, a small
   inverse FFT a frame):
   - anything voice-wide: auto-tune's own Listener (ohscore/dsp/autotune.py,
     "listen until sure"), unchanged, on a 12 kHz channel placed at the
     carrier the spectrum suggests - the place a right-click would put the
     dial (Engine._carrier_near). Its answer is the station's dial to a
     few hertz; a refusal says why (not a voice: a data mode; between
     overs: try again later);
   - anything narrow: two seconds at 4 kHz, whose keying tells CW from
     a carrier or a data mode.
   Names that need no listening come first: the beacons and AMSAT-DL's
   own slots by the band plan, the signals in docs/qo100-unidentified-
   signals.md by their frequency (KNOWN), and the FT8/FT4/Q65/JS8 calling
   windows as one entry each, however many signals are in them.

CPU. A look at a voice costs the most by far: auto-tune's harmonic comb
is a frames x bins x 640-F0 matrix product, ~0.4 s of one core per 4 s
captured on the development host with Debian's reference BLAS (PERF.md
has the measurements). So looks are paid for out of a budget, a share of
one core (`budget`): CPU time used is charged against signal time heard,
and a look starts only while the account is in credit. A slower machine
gets fewer looks a minute, never a starved receiver; when even the
spectrum alone costs more than half the budget, it uses every second
frame, then every fourth (`level`). Signals are still listed and named
by the spectrum at any level - only the exact SSB dials come slower.

Frequencies are downlink Hz (`dl`), as the dial is: the caller passes,
with each block, where the transponder's bottom edge sits in the IQ
(Radio._off(DL_LO), so rxCorr is in it), and everything is placed from
that. A jump in it of more than JUMP_HZ (beacon lock's first fix, a
click-to-lock) moves every signal at once, so the tracks start again.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ohscore.dsp import autotune
from ohscore.dsp.bank import Channel

from .. import bandplan

# --------------------------------------------------------------- spectrum
EDGE_HZ = 2_000.0          # the band spectrum reaches this far past the transponder's edges
LINE_S = 1.0               # one band-spectrum line per second of signal
AVG_LINES = 4              # signals are found on the mean of the last four (4 s, what auto-tune hears)
FLOOR_BLOCK_HZ = 10_000.0  # the noise floor is measured per block this wide ...
FLOOR_PCT = 10             # ... as this percentile: 4 s of 50 Hz bins vary by ~0.3 dB, and a busy
                           # segment's 20th percentile (auto-tune's) can be someone's voice
RISE_DB = 3.0              # a run is the bins standing this far over the floor ...
DETECT_DB = 6.0            # ... whose strongest stands at least this far over it
BRIDGE_HZ = 200.0          # gaps this narrow inside one signal are not two signals (between formants)
# A run wider than this is several signals side by side (an evening's SSB
# segment, stations 2.5-3 kHz apart, bridges into one run tens of kHz
# wide); it is cut at its deepest valleys until no piece is.
SPLIT_HZ = 3_300.0
NOW_DB = 3.0               # a voice is looked at only while its band stands this far up in the latest second
# ------------------------------------------------------------------ tracks
QUIET_S = 20.0             # not seen this long: quiet (shown, greyed)
FORGET_S = 120.0           # not seen this long: forgotten
JUMP_HZ = 300.0            # a step in the receive correction this big starts the tracks again
MERGE_HZ = 60.0            # two SSB tracks whose dials are this close are one QSO
# Widths, as the 50 Hz bins measure them (a bare carrier shows 100-150 Hz).
NARROW_HZ = 300.0          # up to here: a narrow look (CW, carrier, PSK)
VOICE_HZ = 500.0           # from here: a voice look (auto-tune); autotune.MIN_WIDTH decides
# ------------------------------------------------------------------- looks
VOICE_RATE = autotune.RATE
NARROW_RATE = 4_000.0
NARROW_S = 2.0
MAX_LOOKS = 3              # listening at once
RETRY_S = (20.0, 40.0, 80.0, 160.0)   # a voice refused for want of speech: again after these
RECHECK_S = 300.0          # a confirmed voice: checked again this often (stations change)
CONFIRM_HZ = 10.0          # two looks' answers this close confirm a dial ...
CONFIRM_S = 600.0          # ... if the earlier is no older than this
ONCE_S = 120.0             # an unconfirmed answer is forgotten after this
# A dial stays a track's only while the track's occupied band starts
# where a voice on that dial could: 100-650 Hz over the carrier as
# transmitters cut it, with room for the 50 Hz bins and a weak voice's
# lost bottom. On the 3 h recording, without this a dial outlived its
# station and was listed hundreds of hertz under the next one's voice.
DIAL_BELOW = (-100.0, 800.0)
DATA_RECHECK_S = 300.0     # a signal judged not a voice: looked at again this often
# Looks that must hear speech before a signal is called "SSB" without a
# measured dial (ssb_label), outside the SSB-only segments. Auto-tune's
# voice tests alone (voiced frames, a moving pitch) passed on about one 4 s
# look in ten at data on 17/10 - SSTV, KG-STV, the multimedia beacon, the
# FT8 window's pile - and on a real voice on nearly every look. Inside an
# SSB-only segment the band plan already says voice, and one look hearing
# speech settles it; in the mixed and emergency segments, where data is
# allowed, it takes two. A data refusal in between starts the count again.
SPEECH_LOOKS = 2
# ------------------------------------------------------------------ budget
BUDGET = 0.10              # share of one core (Skimmer.budget; the skimBudget setting)
BURST_S = 10.0             # the account may hold this many seconds of budget unspent
LEVELS = (1, 2, 4)         # spectrum frames used: every one, every second, every fourth

# Signals the band plan names by where they are: AMSAT-DL's own slots.
FIXED = {"lower beacon": ("beacon", "Lower beacon (CW)", "cw"),
         "middle beacon": ("beacon", "Middle beacon (400 Bd BPSK)", "usb"),
         "AMSAT-DL broadcast": ("beacon", "AMSAT-DL broadcast", "usb"),
         "multimedia beacon": ("beacon", "Multimedia beacon (HSmodem)", "usb"),
         "upper beacon": ("beacon", "Upper beacon (CW)", "cw")}

# Signals seen on the transponder that the skimmer names rather than decodes, by where
# they are (docs/qo100-unidentified-signals.md, from the 3 h recording of
# 07/10/2026): (centre, +-Hz, widest, label, mode, dial or None). The
# frequencies are the downlink's, so they are only right once beacon lock
# is - as every frequency on the scope is. KG-STV is received by
# ohsnb/kgstvrx.py on its own channel; here it is only named.
KNOWN = [
    # KG-STV is 1200 Bd MSK: a 1.8 kHz main lobe, but a strong one's
    # sidelobes stand over the floor further out - the simulator's station
    # (beacon level - 6 dB, kgsim.py) measures 2.65 kHz - so 3 kHz, not 2.6.
    (10_489_626_400.0, 700.0, 3_000.0, "KG-STV picture", "usb", 10_489_624_900.0),
    (10_489_636_650.0, 1_400.0, 3_200.0, "ARQ data link (VARA HF?)", "usb", None),
    (10_489_645_800.0, 800.0, 2_000.0, "Unidentified multicarrier (on the hour)", "usb", None),
    (10_489_597_000.0, 800.0, 2_600.0, "Unidentified burst (every ~10 min)", "usb", None),
]

# The calling windows of the slot and keyboard modes: everything in one is
# one entry, counted, not one entry per FT8 signal. (dial, audio lo, audio
# hi, label, mode). The dials are bandplan.PRESETS'; the audio spans are
# where each mode's programs put their signals.
WINDOWS = [
    (10_489_540_000.0, 150.0, 3_100.0, "FT8", "ft8"),
    (10_489_870_000.0, 150.0, 3_100.0, "FT4/FT8 (contest)", "ft8"),
    (10_489_545_000.0, 3_100.0, 3_400.0, "Q65", "q65"),     # 10489.548 1st-3rd kHz is JS8's
    (10_489_548_000.0, 400.0, 2_600.0, "JS8", "js8"),
]


def _preset_ok() -> None:
    names = {p["dl"] for p in bandplan.PRESETS}
    for w in WINDOWS:
        assert w[0] in names, w


_preset_ok()


@dataclass
class Track:
    """One signal, as it has been seen and what has been learnt of it."""
    id: int
    lo: float                      # downlink Hz, as last seen
    hi: float
    snr: float                     # strongest bin over the floor, dB
    first: float                   # stream seconds
    last: float
    kind: str = "signal"           # signal, ssb, cw, carrier, data, beacon, known
    label: str = ""
    mode: str = ""                 # what to tune it in
    dial: float | None = None      # where to put the dial (SSB: the suppressed carrier)
    exact: bool = False            # dial measured (auto-tune answered), not guessed
    why: str = ""                  # the last look's refusal, if it refused
    looked: float = -1e9           # when the last look ended
    looks: int = 0
    refusals: int = 0
    due: float = 0.0               # when it may be looked at next
    now_db: float = 0.0            # its band over the floor in the latest second alone
    history: list = field(default_factory=list)   # (t, dial) of every answer
    freq: float | None = None      # a narrow look's measurement of where it is, Hz
    once: float | None = None      # a voice's dial as one look answered it, not yet confirmed
    speech: int = 0                # looks that heard speech in it, whether or not they placed the carrier
    ssb_only: bool = False         # it sits in one of the band plan's SSB-only segments

    @property
    def voice(self) -> bool:
        return self.speech >= (1 if self.ssb_only else SPEECH_LOOKS)

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def centre(self) -> float:
        return 0.5 * (self.lo + self.hi)


class _Look:
    """One listen in progress: a channel off the shared spectra, and what
    it has heard."""

    def __init__(self, geo, track: Track, kind: str, centre: float, base: float, t: float,
                 listen: float = autotune.CAPTURE_SECONDS):
        self.track, self.kind, self.centre, self.t0 = track, kind, float(centre), t
        rate = VOICE_RATE if kind == "voice" else NARROW_RATE
        cutoff = None if kind == "voice" else 1_200.0
        self.ch = Channel(geo, geo.decimation_for(rate), freq=self._off(base), cutoff=cutoff)
        self.rate = self.ch.rate
        self.chunks: list[np.ndarray] = []
        self.n = 0
        self.listener = autotune.Listener("usb", self.rate, most=listen) if kind == "voice" else None

    def _off(self, base: float) -> float:
        return base + (self.centre - bandplan.DL_LO)

    def feed(self, X, starts, base: float) -> None:
        self.ch.set_freq(self._off(base))
        y = self.ch.take(X, starts)
        if len(y):
            self.chunks.append(y)
            self.n += len(y)


class Skimmer:
    """See the module's docstring.

        sk = Skimmer(geo)
        sk.push(X, starts, base)      # every receive block: base = Radio._off(DL_LO)
        sk.entries()                  # the list, as the "skim" feed carries it

    `clock` is the CPU clock the budget charges (time.thread_time: the
    calling thread's own CPU)."""

    def __init__(self, geo, budget: float = BUDGET, clock=time.thread_time, max_looks: int = MAX_LOOKS,
                 listen: float = autotune.CAPTURE_SECONDS):
        self.geo = geo
        self.listen = float(listen)
        self.budget = float(budget)
        self.clock = clock
        self.max_looks = max_looks
        df = geo.df
        self.df = df
        self.nb = int(round((bandplan.DL_HI - bandplan.DL_LO + 2 * EDGE_HZ) / df)) + 1
        self.f = bandplan.DL_LO - EDGE_HZ + np.arange(self.nb) * df     # downlink Hz of each bin
        self.acc = np.zeros(self.nb)
        self.acc_n = 0
        self.lines: list[np.ndarray] = []
        self.line_due: float | None = None
        self.frame = 0                   # frames seen (the level's stride counts them)
        self.level = 0
        self.tracks: list[Track] = []
        self.next_id = 1
        self.looks: list[_Look] = []
        self.base: float | None = None
        self.next_start: int | None = None
        self.t = 0.0                     # stream seconds, the latest block's end
        self.credit = 0.0                # CPU seconds the budget has to spend
        self.spent_fixed = 0.0           # CPU seconds this line on the spectrum and channels
        self.spent_looks = 0.0
        self.cpu_hist: list[tuple[float, float, float]] = []   # (t, fixed, looks) per line
        self.looks_done: list[float] = []                     # when each look ended
        self.gaps = 0                    # blocks that did not follow on (dropped upstream)
        self.floor_db = np.zeros(self.nb)
        self.on_look = None              # called with each voice look's outcome (tools/skimmer_eval.py)

    # ------------------------------------------------------------ the feed
    def push(self, X: np.ndarray, starts: np.ndarray, base: float) -> None:
        """One receive block: the bank's spectra X (frames x N), each
        frame's first sample index, and where DL_LO sits in the IQ (Hz from
        DC) for this block."""
        if X.shape[0] == 0:
            return
        c0 = self.clock()
        g = self.geo
        if self.next_start is not None and int(starts[0]) != self.next_start:
            # Blocks were dropped before they reached us: a channel cannot
            # continue across the hole, so the looks start again.
            self.gaps += 1
            self.looks = []
        self.next_start = int(starts[-1]) + g.L
        if self.base is not None and abs(base - self.base) > JUMP_HZ:
            self._restart()
        self.base = float(base)
        t_end = float(starts[-1] + g.L) / g.fs
        if self.line_due is None:
            self.line_due = t_end + LINE_S
        self.t = t_end
        # The band spectrum: this block's frames (every one, or every
        # second or fourth at a lower level), Hann-windowed in the
        # frequency domain.
        stride = LEVELS[self.level]
        take = (self.frame + np.arange(X.shape[0])) % stride == 0
        self.frame += X.shape[0]
        if take.any():
            k0 = int(round((base - EDGE_HZ) / g.df))
            idx = (k0 - 1 + np.arange(self.nb + 2)) % g.N
            S = X[np.flatnonzero(take)[:, None], idx[None, :]]
            W = 0.5 * S[:, 1:-1] - 0.25 * (S[:, :-2] + S[:, 2:])
            self.acc += (W.real ** 2 + W.imag ** 2).sum(axis=0)
            self.acc_n += int(take.sum())
        for lk in self.looks:
            lk.feed(X, starts, base)
        self.spent_fixed += self.clock() - c0
        c1 = self.clock()
        self._listen()
        self.spent_looks += self.clock() - c1
        if t_end >= self.line_due:
            self.line_due += LINE_S
            if t_end > self.line_due + 5 * LINE_S:      # a long gap: no catching up line by line
                self.line_due = t_end + LINE_S
            c2 = self.clock()
            self._line()
            self.spent_fixed += self.clock() - c2
            self._account()

    def _restart(self) -> None:
        self.tracks = []
        self.looks = []
        self.lines = []
        self.acc[:] = 0.0
        self.acc_n = 0

    # -------------------------------------------------------------- budget
    def _account(self) -> None:
        """Charge this line's CPU against the budget, and choose the level."""
        fixed, looks = self.spent_fixed, self.spent_looks
        self.spent_fixed = self.spent_looks = 0.0
        self.cpu_hist.append((self.t, fixed, looks))
        del self.cpu_hist[:-30]
        self.credit = min(self.credit + self.budget * LINE_S - fixed - looks, self.budget * BURST_S)
        # The spectrum's own share, over the last 10 lines, at this level:
        # over half the budget and it thins; under a sixth and it thickens.
        recent = self.cpu_hist[-10:]
        if len(recent) >= 10:
            share = sum(h[1] for h in recent) / (len(recent) * LINE_S)
            if share > 0.5 * self.budget and self.level < len(LEVELS) - 1:
                self.level += 1
                self.cpu_hist.clear()
            elif share < self.budget / 6 and self.level > 0:
                self.level -= 1
                self.cpu_hist.clear()

    def cpu(self) -> float:
        """The skimmer's share of one core over the last lines (0..1)."""
        h = self.cpu_hist[-10:]
        return sum(a + b for _, a, b in h) / (len(h) * LINE_S) if h else 0.0

    def looks_per_minute(self) -> float:
        self.looks_done = [t for t in self.looks_done if t > self.t - 60.0]
        return float(len(self.looks_done))

    # ------------------------------------------------------- the spectrum
    def _line(self) -> None:
        if not self.acc_n:
            return
        self.lines.append(self.acc / self.acc_n)
        del self.lines[:-AVG_LINES]
        self.acc = np.zeros(self.nb)
        self.acc_n = 0
        P = np.mean(self.lines, axis=0)
        floor = self._floor(P)
        self.floor_db = 10 * np.log10(floor + 1e-30)
        runs = []
        inside = (self.f >= bandplan.DL_LO - 50.0) & (self.f <= bandplan.DL_HI + 50.0)
        f, p, fl = self.f[inside], P[inside], floor[inside]
        # autotune.occupied takes one floor; ours varies along the band, so
        # the spectrum is divided by it first and the floor is then 1.
        ratio = p / fl
        for lo, hi in autotune.occupied(f, ratio, 1.0, rise_db=RISE_DB, bridge_hz=BRIDGE_HZ):
            for a, b in split_run(f, ratio, lo, hi):
                sel = (f >= a) & (f <= b)
                snr = float(10 * np.log10(ratio[sel].max()))
                if snr >= DETECT_DB:
                    runs.append((a, b, snr))
        self._match(runs)
        # How far each track's band stands up in the latest second alone:
        # a voice is looked at while it is talking, not between overs.
        now = self.lines[-1]
        for tr in self.tracks:
            sel = (self.f >= tr.lo) & (self.f <= tr.hi)
            if sel.any():
                tr.now_db = float(10 * np.log10(now[sel].mean() / floor[sel].mean()))
        self._schedule()

    def _floor(self, P: np.ndarray) -> np.ndarray:
        # Blocks from the transponder's bottom edge to its top: outside it
        # the noise is the LNB's alone, several dB lower, and a block
        # straddling the edge put the floor under the transponder's own
        # noise there - which then showed as "signals" kilohertz wide.
        n = max(8, int(round(FLOOR_BLOCK_HZ / self.df)))
        first = int(round(EDGE_HZ / self.df))
        last = self.nb - first
        edges = list(range(first, last, n))
        cen, val = [], []
        for a in edges:
            b = min(last, a + n)
            if b - a < n // 2:
                continue
            cen.append(0.5 * (a + b - 1))
            val.append(np.percentile(P[a:b], FLOOR_PCT))
        val = np.asarray(val)
        # A block wall to wall with signals (an evening's SSB segment) reads
        # high; its neighbours' floors keep it honest.
        lowest = np.minimum(val, np.minimum(np.r_[val[1:], val[-1]], np.r_[val[0], val[:-1]]) * 1.26)
        return np.interp(np.arange(self.nb), cen, lowest)

    # ------------------------------------------------------------ tracks
    def _match(self, runs: list[tuple[float, float, float]]) -> None:
        t = self.t
        # One run to a track, largest overlaps first: a track that took
        # every run it touched grew over its neighbours, line by line, into
        # one "signal" kilohertz wide.
        pairs = []
        for i, (lo, hi, _snr) in enumerate(runs):
            for tr in self.tracks:
                ov = min(hi, tr.hi) - max(lo, tr.lo)
                # Narrow signals move by a bin between lines: a near miss
                # is the same one.
                if ov > (-50.0 if (hi - lo < NARROW_HZ and tr.width < NARROW_HZ) else 0.0):
                    pairs.append((ov, i, tr))
        pairs.sort(key=lambda x: -x[0])
        claimed: dict[int, list] = {}
        used: set[int] = set()
        for _ov, i, tr in pairs:
            if i in used or tr.id in claimed:
                continue
            used.add(i)
            claimed[tr.id] = [runs[i]]
        fresh = [r for i, r in enumerate(runs) if i not in used]
        for tr in self.tracks:
            got = claimed.get(tr.id)
            if not got:
                continue
            tr.lo = min(r[0] for r in got)
            tr.hi = max(r[1] for r in got)
            tr.snr = max(r[2] for r in got)
            tr.last = t
            self._name(tr)
        for lo, hi, snr in fresh:
            tr = Track(self.next_id, lo, hi, snr, t, t)
            self.next_id += 1
            self._name(tr)
            self.tracks.append(tr)
        # A track this line's runs did not claim, overlapping one they did,
        # is the same signal seen differently (a voice found as two runs,
        # then as one): it goes, and what it had learnt goes to the other.
        seen = [tr for tr in self.tracks if tr.last == t]
        keep = []
        for tr in self.tracks:
            if tr.last != t:
                over = next((o for o in seen if min(o.hi, tr.hi) - max(o.lo, tr.lo) > 0), None)
                if over is not None:
                    if tr.exact and not over.exact and tr.kind == "ssb":
                        self._inherit(over, tr)
                    self.looks = [lk for lk in self.looks if lk.track is not tr]
                    continue
            keep.append(tr)
        self.tracks = [tr for tr in keep if t - tr.last < FORGET_S]
        self._merge()

    @staticmethod
    def _inherit(to: Track, frm: Track) -> None:
        for k in ("kind", "label", "mode", "dial", "exact", "why", "looked", "looks", "refusals", "due", "speech", "ssb_only"):
            setattr(to, k, getattr(frm, k))
        to.history = list(frm.history)
        to.first = min(to.first, frm.first)

    def _merge(self) -> None:
        """One QSO answered twice (its two stations a few hertz apart, or
        one voice found as two runs) is one entry: the older keeps it."""
        keep: list[Track] = []
        for tr in sorted(self.tracks, key=lambda x: x.first):
            if tr.exact and tr.dial is not None:
                same = next((k for k in keep if k.exact and k.dial is not None and abs(k.dial - tr.dial) <= MERGE_HZ),
                            None)
                if same is not None:
                    same.lo, same.hi = min(same.lo, tr.lo), max(same.hi, tr.hi)
                    same.last = max(same.last, tr.last)
                    self.looks = [lk for lk in self.looks if lk.track is not tr]
                    continue
            keep.append(tr)
        self.tracks = keep

    def _name(self, tr: Track) -> None:
        """What the band plan and the known list call it, before any look."""
        c = tr.centre
        seg = bandplan.segment_at(min(max(c, bandplan.DL_LO), bandplan.DL_HI))
        if seg is not None and not seg["tx"] and seg["label"] in FIXED:
            tr.kind, tr.label, tr.mode = FIXED[seg["label"]]
            tr.dial = None
            return
        for cen, tol, widest, label, mode, dial in KNOWN:
            if abs(c - cen) <= tol and tr.width <= widest and tr.width >= NARROW_HZ:
                tr.kind, tr.label, tr.mode, tr.dial, tr.exact = "known", label, mode, dial, dial is not None
                return
        if tr.kind == "known":            # it moved off what it was taken for
            tr.kind, tr.label, tr.dial, tr.exact = "signal", "", None, False
        if tr.kind in ("cw", "carrier") and tr.width >= VOICE_HZ or tr.kind == "data" and tr.label == "Data (narrow)" \
                and tr.width >= VOICE_HZ:
            # Judged narrow, now voice-wide: something else is there (a
            # station came up beside it, or on it). Looked at afresh.
            tr.kind, tr.label, tr.dial, tr.exact, tr.due = "signal", "", None, False, self.t
        if tr.kind == "ssb" and (tr.exact or tr.once is not None):
            ref = tr.dial if tr.exact else tr.once
            stale = tr.once is not None and not tr.exact and self.t - tr.history[-1][0] > ONCE_S
            if stale or not (DIAL_BELOW[0] <= tr.lo - ref <= DIAL_BELOW[1]):
                tr.exact, tr.once = False, None
                tr.label = ssb_label(tr)
                tr.due = min(tr.due, self.t)
        if tr.kind in ("signal", "ssb") and tr.width >= VOICE_HZ and not tr.exact:
            # Until a look says otherwise: a voice, its carrier where a
            # transmitter's low cut puts it under the occupied band - or
            # where one look's answer put it, which is better than that.
            tr.mode = "usb"
            tr.dial = tr.once if tr.once is not None else tr.lo - autotune.LOW_CUT
            if tr.kind == "signal" and seg is not None and seg["modes"] == ["ssb"]:
                tr.kind = "ssb"     # the band plan's SSB segments: a voice until shown otherwise
                tr.label = ssb_label(tr)

    def window_of(self, tr: Track):
        for w in WINDOWS:
            dial, a, b = w[0], w[1], w[2]
            if dial + a <= tr.centre <= dial + b and tr.width <= b - a + 200.0:
                return w
        return None

    # ------------------------------------------------------------- looks
    def _schedule(self) -> None:
        if len(self.looks) >= self.max_looks or self.credit < 0.0:
            return
        busy = {lk.track.id for lk in self.looks}
        cands = []
        for tr in self.tracks:
            if tr.id in busy or tr.kind in ("beacon", "known") or self.t - tr.last > 2 * LINE_S:
                continue                          # named already, or not on now
            if self.window_of(tr) is not None or tr.due > self.t:
                continue
            kind = "voice" if tr.width >= VOICE_HZ else "narrow"
            if kind == "voice" and tr.now_db < NOW_DB:
                continue
            # Never looked at first, then the longest waiting.
            cands.append((tr.looks > 0, tr.due, kind, tr))
        cands.sort(key=lambda c: c[:2])
        for _, _, kind, tr in cands[:self.max_looks - len(self.looks)]:
            centre = (tr.lo - autotune.LOW_CUT) if kind == "voice" else tr.centre
            self.looks.append(_Look(self.geo, tr, kind, centre, self.base, self.t, self.listen))
            if self.credit < 0.0:
                break

    def _listen(self) -> None:
        done = []
        for lk in self.looks:
            if lk.kind == "voice":
                lis = lk.listener
                if not lis.due(lk.n):
                    continue
                iq = np.concatenate(lk.chunks) if len(lk.chunks) > 1 else lk.chunks[0]
                lk.chunks = [iq]
                r = lis.look(iq)
                if r is not None:
                    self._voice(lk, r)
                    done.append(lk)
            elif lk.n >= NARROW_S * lk.rate:
                self._narrow(lk, np.concatenate(lk.chunks))
                done.append(lk)
        if done:
            self.looks = [lk for lk in self.looks if lk not in done]
            self.looks_done.extend(self.t for _ in done)

    def _voice(self, lk: _Look, r) -> None:
        tr = lk.track
        tr.looks += 1
        tr.looked = self.t
        if self.on_look is not None:
            self.on_look({"t": self.t, "id": tr.id, "centre": lk.centre, "ok": bool(r.ok),
                          "dial": lk.centre + r.offset if r.ok else None, "why": r.why})
        # Speech heard counts only where the band plan has SSB: on 17/10
        # the FT8 calling window's pile of signals, taken as one track
        # wider than the window, passed auto-tune's voice tests (many
        # tones, moving), and so did a CW-segment signal.
        seg = bandplan.segment_at(min(max(tr.centre, bandplan.DL_LO), bandplan.DL_HI))
        if heard_speech(r) and seg is not None and "ssb" in seg["modes"]:
            tr.speech += 1
            tr.ssb_only = seg["modes"] == ["ssb"]
        if r.ok:
            dial = lk.centre + r.offset
            tr.kind, tr.mode, tr.why = "ssb", "usb", ""
            tr.refusals = 0
            # Confirmed only when another look, at other speech, lands within
            # CONFIRM_HZ of it. On the labelled real voices (c3) one look's
            # answer was a pitch or so off nearly as often as it was right
            # (auto-tune's own figures: 85 right, 77 wrong); its wrong
            # answers wander from look to look, its right ones do not.
            agree = [d for t, d in tr.history if self.t - t <= CONFIRM_S and abs(d - dial) <= CONFIRM_HZ]
            tr.history.append((self.t, dial))
            del tr.history[:-8]
            if agree:
                tr.dial, tr.exact, tr.once, tr.label = float(np.mean(agree + [dial])), True, None, "SSB"
                tr.due = self.t + RECHECK_S
            elif not tr.exact:
                tr.dial, tr.once = dial, dial
                tr.label = ssb_label(tr)
                tr.due = self.t + RETRY_S[0]
            else:
                tr.due = self.t + RETRY_S[0]     # a confirmed station disagreeing: its QSO partner, or a new one
            return
        tr.why = r.why
        what = refusal_kind(r)
        if what == "data":
            # Not a voice by auto-tune's own tests (steady level, a few
            # tones, an even comb): a data signal, not looked at as a
            # voice again for a while.
            if not tr.exact:
                tr.kind, tr.label, tr.dial, tr.mode = "data", data_label(tr.width), None, "usb"
                tr.speech = 0
            tr.due = self.t + DATA_RECHECK_S
            return
        if what == "narrow":
            tr.due = self.t + RETRY_S[0]        # the spectrum will make a narrow look of it
            return
        # A voice, or something like one, that did not settle: between
        # overs, two stations taking turns, a weak one. Its spectrum guess
        # stands until a later look answers; each try waits longer.
        if not tr.exact and tr.kind == "signal":
            tr.kind = "ssb"
        if tr.kind == "ssb":
            tr.label = ssb_label(tr)
        tr.refusals += 1
        tr.due = self.t + RETRY_S[min(tr.refusals, len(RETRY_S)) - 1]

    def _narrow(self, lk: _Look, y: np.ndarray) -> None:
        tr = lk.track
        tr.looks += 1
        tr.looked = self.t
        kind, f, why = judge_narrow(y, lk.rate)
        tr.why = why
        tr.due = self.t + DATA_RECHECK_S
        if kind is None:
            return
        tr.kind = kind
        tr.mode = "cw" if kind == "cw" else "usb"
        tr.label = {"cw": "CW", "carrier": "Carrier", "data": "Data (narrow)"}[kind]
        tr.dial = None
        # The signal's own frequency, to a hertz or two (the 50 Hz bins
        # place it to 50): what a click on it should tune to.
        tr.freq = None if f is None else lk.centre + f

    # ------------------------------------------------------------ output
    def entries(self, wall: float | None = None) -> list[dict]:
        """The list: one dict per signal, and one per busy calling window,
        in frequency order. `wall` is the wall-clock time of the latest
        block (the feed's times are UNIX seconds); stream seconds if None."""
        off = 0.0 if wall is None else wall - self.t
        out, groups, beacons = [], {}, {}
        for tr in self.tracks:
            if tr.kind == "beacon":
                # One entry per beacon however many runs its tones make.
                b = beacons.get(tr.label)
                if b is None:
                    beacons[tr.label] = tr
                else:
                    beacons[tr.label] = Track(b.id, min(b.lo, tr.lo), max(b.hi, tr.hi), max(b.snr, tr.snr),
                                              min(b.first, tr.first), max(b.last, tr.last), "beacon", b.label,
                                              b.mode)
                continue
            w = self.window_of(tr)
            if w is not None:
                if self.t - tr.last < QUIET_S:
                    g = groups.setdefault(w, {"n": 0, "snr": -99.0, "first": tr.first, "last": tr.last})
                    g["n"] += 1
                    g["snr"] = max(g["snr"], tr.snr)
                    g["first"], g["last"] = min(g["first"], tr.first), max(g["last"], tr.last)
                continue
            if tr.kind == "signal" and tr.width < VOICE_HZ and not tr.looks:
                continue                     # not yet looked at: nothing worth listing yet
            f = tr.dial if tr.dial is not None else tr.centre
            if tr.dial is None and tr.freq is not None and tr.lo - 50.0 <= tr.freq <= tr.hi + 50.0:
                f = tr.freq
            out.append({"id": tr.id, "f": round(f, 1), "lo": round(tr.lo, 1), "hi": round(tr.hi, 1),
                        "kind": tr.kind, "label": tr.label or kind_label(tr), "mode": tr.mode or "usb",
                        "dial": None if tr.dial is None else round(tr.dial, 1), "exact": bool(tr.exact),
                        "measured": ("twice" if tr.exact else "once" if tr.once is not None else "")
                        if tr.kind == "ssb" else "",
                        "voice": bool(tr.voice) if tr.kind == "ssb" else False,
                        "why": tr.why, "snr": round(tr.snr, 1), "first": round(tr.first + off, 1),
                        "last": round(tr.last + off, 1), "active": self.t - tr.last < QUIET_S,
                        "looks": tr.looks, "count": 1})
        for tr in beacons.values():
            out.append({"id": tr.id, "f": round(tr.centre, 1), "lo": round(tr.lo, 1), "hi": round(tr.hi, 1),
                        "kind": "beacon", "label": tr.label, "mode": tr.mode, "dial": None, "exact": False, "measured": "",
                        "why": "", "snr": round(tr.snr, 1), "first": round(tr.first + off, 1),
                        "last": round(tr.last + off, 1), "active": self.t - tr.last < QUIET_S, "looks": 0,
                        "count": 1})
        for (dial, a, b, label, mode), g in groups.items():
            out.append({"id": -int(dial // 1000), "f": dial, "lo": dial + a, "hi": dial + b, "kind": "digital",
                        "label": label, "mode": mode, "dial": dial, "exact": True, "measured": "", "why": "",
                        "snr": round(g["snr"], 1), "first": round(g["first"] + off, 1),
                        "last": round(g["last"] + off, 1), "active": True, "looks": 0, "count": g["n"]})
        out.sort(key=lambda e: e["f"])
        return out


def split_run(f: np.ndarray, ratio: np.ndarray, lo: float, hi: float) -> list[tuple[float, float]]:
    """[lo, hi] cut at its deepest valleys (of the spectrum over the floor,
    smoothed over 150 Hz) until no piece is wider than SPLIT_HZ. Each cut
    leaves 300 Hz at least on either side, and the valley's bins go to
    neither piece."""
    if hi - lo <= SPLIT_HZ:
        return [(lo, hi)]
    sel = np.flatnonzero((f >= lo) & (f <= hi))
    df = float(f[1] - f[0])
    r = np.convolve(ratio[sel], np.ones(3) / 3, mode="same")
    edge = int(round(300.0 / df))
    if len(sel) <= 2 * edge + 1:
        return [(lo, hi)]
    k = edge + int(np.argmin(r[edge:len(sel) - edge]))
    a, b = float(f[sel[k]]) - df / 2, float(f[sel[k]]) + df / 2
    return split_run(f, ratio, lo, a) + split_run(f, ratio, b, hi)


def kind_label(tr: Track) -> str:
    if tr.kind == "ssb":
        return ssb_label(tr)
    if tr.width >= VOICE_HZ:
        return "Signal"
    return "Signal (narrow)"


def ssb_label(tr: Track) -> str:
    """"SSB" once speech has been heard in it, "SSB?" while it is only
    voice-shaped on the spectrum. Up to 17/10/2026 the question mark meant
    "its carrier is not confirmed" instead (two looks agreeing within
    CONFIRM_HZ), so on Brian's evening of 17/10 nearly every voice on the
    band was "SSB?" - in five recordings, 13 minutes, not one track was
    confirmed - and he read it as NB doubting they were SSB at all. Whether
    the dial is measured is a separate question with its own answer (the
    entry's `exact` and `measured`, and the note under the list), so the
    label only says what the signal is. USB is taken as read: on QO-100
    SSB is all but always USB, and the skimmer only ever looks in USB."""
    return "SSB" if tr.exact or tr.voice else "SSB?"


def heard_speech(r) -> bool:
    """Whether an auto-tune look heard a voice, answer or not. Its tests
    come in order (autotune.judge): enough voiced frames (MIN_VOICED), then
    a pitch that moves as speech does (MIN_PITCH_SPREAD, which is what
    turns away an evenly spaced data comb), and only then the ones about
    *where* the carrier is - frames agreeing, halves agreeing, a rival
    offset, the voice's edge. A refusal by one of those last ones has
    already passed the first two: it heard speech and could not place it.
    The coarse refusals (nothing there, too narrow, too steady, too wide)
    come with no frames at all."""
    if r.ok:
        return True
    d = r.details or {}
    return (refusal_kind(r) == "voice" and d.get("voiced", 0) >= autotune.MIN_VOICED
            and d.get("spread", 0.0) >= autotune.MIN_PITCH_SPREAD)


def data_label(width: float) -> str:
    return "Data" if width >= VOICE_HZ else "Data (narrow)"


# Auto-tune's refusals, by what they say about the signal. They are its own
# sentences (ohscore/dsp/autotune.py), matched by their stable words; a
# refusal not listed counts as a voice that did not settle, which only
# means it is tried again later.
_DATA_WORDS = ("steady tones", "holds steady", "evenly spaced", "wider than SSB")
_NARROW_WORDS = ("a carrier, CW or a data mode",)


def refusal_kind(r) -> str:
    """"data", "narrow" or "voice" (try again) for an auto-tune refusal."""
    why = r.why or ""
    if any(w in why for w in _DATA_WORDS):
        return "data"
    if any(w in why for w in _NARROW_WORDS):
        return "narrow"
    return "voice"


def judge_narrow(y: np.ndarray, rate: float) -> tuple[str | None, float | None, str]:
    """(kind, frequency Hz from the channel's centre, why) for two seconds of
    a narrow signal: "cw" when it is keyed (its level goes on and off in
    dits and dahs), "carrier" when it holds steady and is a line, "data"
    when it holds steady and is not (PSK, RTTY, MFSK keep a level up while
    sending), None when nothing stands out.

    The level is the power within 60 Hz of the strongest line, in 8 ms
    frames. Keyed: its 90th percentile stands 10 dB over its 10th and the
    gaps below half of it last 24 ms and more in the median - CW's gaps are
    a dit long (50 ms at 24 wpm); PSK31's dips at a phase reversal are
    shorter than 16 ms, so it never looks keyed."""
    n = len(y)
    if n < 2048:
        return None, None, "too little heard"
    nfft = 1 << int(np.ceil(np.log2(n)))
    S = np.abs(np.fft.fft(y * np.hanning(n), nfft)) ** 2
    fr = np.fft.fftfreq(nfft, 1 / rate)
    use = np.abs(fr) <= 400.0
    # Smoothed over 4 Hz before anything is judged: one bin of noise alone
    # stands 10 dB over the median somewhere among a thousand.
    k = max(1, int(round(4.0 / (rate / nfft))))
    sm = np.convolve(S, np.ones(k) / k, mode="same")
    i = int(np.flatnonzero(use)[np.argmax(sm[use])])
    if 10 * np.log10(sm[i] / (float(np.median(sm[use])) + 1e-30)) < 10.0:
        return None, None, "nothing stands out in the channel"
    i = max(range(max(0, i - k), min(nfft, i + k + 1)), key=lambda j: S[j])   # the line's own bin
    f0 = float(fr[i])
    hot = (sm >= sm[i] / 10.0) & (np.abs(fr - f0) <= 300.0)
    width = float(np.ptp(fr[hot])) if hot.sum() > 1 else 0.0
    # The level around the line, frame by frame.
    t = np.arange(n) / rate
    z = y * np.exp(-2j * np.pi * f0 * t)
    Z = np.fft.fft(z)
    fz = np.fft.fftfreq(n, 1 / rate)
    z = np.fft.ifft(np.where(np.abs(fz) <= 60.0, Z, 0))
    hop = max(1, int(round(0.008 * rate)))
    m = n // hop
    lev = (np.abs(z[:m * hop]) ** 2).reshape(m, hop).mean(axis=1)
    p10, p90 = np.percentile(lev, 10), np.percentile(lev, 90)
    swing = 10 * np.log10(p90 / max(p10, 1e-30))
    if swing >= 10.0:
        on = lev > 0.5 * p90
        gaps, run = [], 0
        for v in on:
            if not v:
                run += 1
            elif run:
                gaps.append(run)
                run = 0
        gap_s = float(np.median(gaps)) * hop / rate if gaps else 0.0
        if gap_s >= 0.024 and 0.1 <= on.mean() <= 0.95:
            return "cw", f0, ""
        return "data", f0, f"its level swings {swing:.0f} dB but not in Morse's dits and dahs"
    if width <= 12.0:
        return "carrier", f0, ""
    return "data", f0, ""


__all__ = ["Skimmer", "Track", "KNOWN", "WINDOWS", "FIXED", "judge_narrow", "refusal_kind"]
