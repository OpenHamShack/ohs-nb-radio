"""`python3 -m ohsnb --analyse --jobs N`: the same report as a single pass,
from N worker processes.

Until 08/10 every section ran one after another on one core, each reading
the whole file: a 3-hour, 53 GB recording took most of a day with fifteen
cores of the machine idle. Two levels of parallelism, both kept exact - a
parallel report that merely resembled the single-process one would be a
second analysis to argue with, not a faster first one:

1. **Sections side by side.** After the beacon tracker (which everything
   else needs: rx_corr_est, and its history for _rx_corr_at), every
   section is an independent pass over the file. Each worker opens its
   own read-only memmap of the recording (ohsnb.analyse._raw_iq) rather
   than being sent IQ: the page cache is shared between processes, the
   pickled arguments stay a few hundred kB, and nothing is copied.

2. **Time slices within a section.** A slice reads its own stretch of the
   file, and must produce exactly what a whole-file pass produces there.
   How each section manages that:

   - levels: per-block sums kept separate and added in file order by the
     parent (float addition is not associative).
   - wide spectrum, over-power lines, census: each spectral line depends
     only on the samples it covers; a slice rebuilds the Scope's buffer
     and next-line time (ohsnb.analyse._scope_at) and computes exactly the
     lines that end inside it. Over-power's event tracker IS sequential
     (whether a line's hit joins an open event depends on every line
     before it), so it is never sliced: slices return their lines' hits,
     and the parent runs the tracker once over all of them in order -
     a few list operations per line. Events that span a slice boundary
     are therefore joined exactly as a single pass joins them, with no
     stitching heuristic. The LEILA checks are then one task per batch
     of events.
   - FT8, FT4, Q65, JS8: a slot's decode depends only on the audio
     placed in it. A slice reproduces the channel audio exactly (filter
     bank buffer and LO phase rebuilt, demodulator warmed up - see
     ohsnb.analyse's WARM_CHUNKS comment), timestamps it from the same
     sample count, and reports only the slots whose start falls in its
     own half-open range of UTC slot starts; neighbouring slices share
     the boundary value, so every slot belongs to exactly one.
   - PSK31: decoded per window_s window of one continuous audio stream,
     each window on its own; a slice owns a range of whole windows.
   - SSB at scale: each 10-minute window already reads only its own IQ.

   Left whole, on purpose:
   - the beacon tracker: lock/search state carried from every earlier
     update, with hysteresis - no exact way to start one mid-file;
   - the multimedia beacon: the HSmodem receiver's AFC and frame sync,
     and files assembled from blocks over minutes, carry across any cut;
   - the SSB scan (one 10 s window and three short captures).
   A recording with a capture segment the loops skip (no frequency)
   leaves every sliced section whole too (ohsnb.analyse._chunk_grid).

Nothing here imports Qt, and the workers are started with "spawn" on every
platform (the default on Windows and macOS, chosen on Linux too so the
three behave alike): each worker imports this module afresh and gets its
context from the pool's initializer, never from inherited globals.
"""
from __future__ import annotations

import bisect
import math
import multiprocessing
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from pathlib import Path

from ohscore.dsp.bank import Geometry
from ohscore.engine import AUDIO_RATE

from ohsnb.i18n import _, ngettext

from . import analyse as A

# Shortest slice cut, per kind of section. A spectrum slice costs only one
# Scope buffer of overlap, so it can be short; a decoding slice repeats
# WARM_CHUNKS seconds of channel work and up to a slot's decode either
# side, so it is kept long enough for that to be noise.
SCOPE_SLICE_S = 60.0
CHANNEL_SLICE_S = 240.0
SLOT_MARGIN_S = 1.0           # audio fed either side of a slice's own slots
AUDIO_FS = 12_000.0           # the decoders' own sample rate (ohscore.modes.ft8.FS and the rest)
DECODES_PER_WORKER = 2        # each worker's jt9/q65code/js8 runs in flight (analyse.MAX_CONCURRENT_DECODES)

# What one worker may use, for default_jobs. Measured 08/10 on the
# 16-minute 07/10/2026 CW recording, --extended --jobs 8 (RssAnon, the
# heap - never the recording's own page cache, which is reclaimable): six
# workers peaked at 229 MB, two at 822 and 875 MB (which tasks was not
# recorded - most likely the 80k-point spectra of over-power or census),
# the parent at 96 MB, each jt9 at ~90 MB; 2.2 GB for the whole tree at
# its peak. A single-process run of the same file peaks at 1.1 GB on its
# own. 800 MB a worker, with 1 GB kept back for the parent and everything
# else, is far above the average and lets two workers hit the worst case
# at once with room left: an 8 GB laptop with ~5 GB available gets five
# workers - the machine the old leaky version OOM-killed is the one this
# must stay safe on.
WORKER_BUDGET = 800 * 2**20
PARENT_RESERVE = 1024 * 2**20
MAX_DEFAULT_JOBS = 12         # more than the sections can keep busy on a typical recording


# ------------------------------------------------------------- how many
def _available_memory() -> int | None:
    """Bytes of memory free for new work, or None if this platform will
    not say. Linux: MemAvailable (free plus reclaimable cache - the
    recording's own page cache is reclaimable and must not count against
    us). Windows: GlobalMemoryStatusEx's available physical memory. macOS
    has no cheap equivalent without a dependency: half the physical
    memory stands in for it."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
            return None
        if sys.platform == "win32":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MemStatus()
            st.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullAvailPhys)
            return None
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) // 2
    except (OSError, ValueError, AttributeError):
        return None


def default_jobs() -> int:
    """One worker per core less one (the parent, and the decoders'
    subprocesses, need some), at most MAX_DEFAULT_JOBS, and no more than
    available memory allows at WORKER_BUDGET each - 2 if the memory cannot
    be read at all. Never less than 1."""
    cpus = os.cpu_count() or 1
    by_cpu = max(1, min(cpus - 1, MAX_DEFAULT_JOBS))
    avail = _available_memory()
    by_mem = 2 if avail is None else max(1, int((avail - PARENT_RESERVE) // WORKER_BUDGET))
    return max(1, min(by_cpu, by_mem))


# ------------------------------------------------------------- the worker
_W: dict = {}


def _init(ctx: dict) -> None:
    """Pool initializer: open this worker's own memmap of the recording.
    Lowers the decoders' in-flight limit for the whole process (see
    analyse._wait_for_room)."""
    _W.clear()
    _W.update(ctx)
    view, scale, _n = A._raw_iq(Path(ctx["data_path"]), ctx["datatype"], ctx["scale_override"])
    _W["view"], _W["scale"] = view, scale
    A.MAX_CONCURRENT_DECODES = ctx["decodes"]


def _hist(corr) -> list[dict]:
    """A beacon history _rx_corr_at answers exactly as it does from the
    tracker's full one: it only ever looks at the locked entries' t and
    rxCorr, so those are all that is sent."""
    times, corrs = corr
    return [{"t": t, "state": "locked", "rxCorr": c} for t, c in zip(times, corrs)]


def _task(kind: str, label: str, kw: dict):
    t0 = time.monotonic()
    if _W.get("verbose"):
        print(f"[{time.time() - _W['t0_wall']:7.1f} s] {label}: started", file=sys.stderr, flush=True)
    w = _W
    view, scale, n, fs, caps, info = w["view"], w["scale"], w["n"], w["fs"], w["caps"], w["info"]
    if kind == "tracker":
        out = A._run_beacon_tracker(view, scale, n, fs, caps, info, kw["rx_corr0"])
    elif kind == "levels":
        out = A._level_part(view, n, w["full_scale"], kw["lo"], kw["hi"])
    elif kind == "wide":
        out = A._wide_lines(view, scale, n, fs, kw["width"], kw["lo"], kw["hi"])
    elif kind == "ft8":
        out = A._ft8_decode_raw(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]), w["start_utc"],
                                kw["part"])
    elif kind == "scan_ssb":
        out = A._scan_ssb(view, scale, n, fs, kw["dc"])
    elif kind == "mmb":
        from . import analyse_mmb
        out = analyse_mmb.mmb_report(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]), kw["out_dir"])
    elif kind == "op_lines":
        from . import analyse_power
        out = analyse_power._lines(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]),
                                   k_lo=kw["k_lo"], k_hi=kw["k_hi"])
    elif kind == "op_leila":
        from . import analyse_power
        hist = _hist(kw["corr"])
        out = [analyse_power._entry(view, scale, fs, caps, info, kw["rx"], hist, e) for e in kw["events"]]
    elif kind == "ssb_scale":
        from . import analyse_ssb
        out = analyse_ssb._attempts(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]),
                                    i_lo=kw["i_lo"], i_hi=kw["i_hi"])
    elif kind == "slotted":
        from . import analyse_digital
        out = analyse_digital._slotted_events(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]),
                                              w["start_utc"], kw["mode"], kw["part"])
    elif kind == "psk":
        from . import analyse_digital
        out = analyse_digital._psk_segment(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]),
                                           kw["si"], kw["window_s"], kw["part"])
    elif kind == "census":
        from . import analyse_census
        out = analyse_census._tally(view, scale, n, fs, caps, info, kw["rx"], _hist(kw["corr"]),
                                    k_lo=kw["k_lo"], k_hi=kw["k_hi"])
    else:
        raise ValueError(_("unknown analysis task {kind}").format(kind=repr(kind)))
    return out, time.monotonic() - t0


# ------------------------------------------------------------- planning
def _split(count: int, parts: int) -> list[tuple[int, int]]:
    """count items into `parts` contiguous, near-equal, non-empty ranges."""
    parts = max(1, min(parts, count))
    bounds = [round(i * count / parts) for i in range(parts + 1)]
    return [(lo, hi) for lo, hi in zip(bounds, bounds[1:]) if hi > lo]


def _how_many(duration_s: float, min_s: float, jobs: int) -> int:
    return max(1, min(jobs, int(duration_s // min_s))) if min_s > 0 else jobs


def _audio_times(grid: list, fs: float, start_utc: float) -> list[float]:
    """The decoders' timestamp of each grid block's first audio sample in a
    whole-file pass (ohsnb.analyse._audio_fed_before), plus one past the
    end."""
    geo = Geometry(fs)
    per = geo.L // geo.decimation_for(AUDIO_RATE)
    starts = [a for a, _b, _dc in grid] + ([grid[-1][1]] if grid else [0])
    return [start_utc + (a // geo.L) * per / AUDIO_FS for a in starts]


def _slot_parts(grid: list, fs: float, start_utc: float, period_s: float, slices: int) -> list[dict | None]:
    """Parts (see ohsnb.analyse._ft8_decode_raw) cutting a slotted mode's
    decode into `slices` at slot boundaries; [None] for no cut. Each cut
    leaves at least one whole slot either side, so a slice is never just
    its own margins."""
    T = _audio_times(grid, fs, start_utc)
    t_end = T[-1]
    cuts: list[float] = []
    for j in range(1, slices):
        u = math.floor((start_utc + (t_end - start_utc) * j / slices) / period_s) * period_s
        if u - period_s < (cuts[-1] if cuts else start_utc) or u + period_s > t_end:
            continue
        cuts.append(u)
    if not cuts:
        return [None]
    bounds = [-math.inf] + cuts + [math.inf]
    parts = []
    for u_lo, u_hi in zip(bounds, bounds[1:]):
        lo = 0 if u_lo == -math.inf else max(0, bisect.bisect_right(T, u_lo - SLOT_MARGIN_S) - 1)
        hi = len(grid) if u_hi == math.inf else min(len(grid), bisect.bisect_left(T, u_hi + SLOT_MARGIN_S))
        parts.append({"warm": max(0, lo - A.WARM_CHUNKS), "lo": lo, "hi": hi, "own": (u_lo, u_hi),
                      "last": u_hi == math.inf})
    return parts


def _psk_parts(grid: list, fs: float, window_s: float, slices: int) -> list[dict | None]:
    """Parts for one PSK31 segment: whole windows per slice (see
    analyse_digital._psk_segment); [None] for a recording with fewer than
    two whole windows, which is decoded whole."""
    if not grid:
        return [None]
    win_n = int(window_s * AUDIO_FS)
    fed = [A._audio_fed_before(fs, a) for a, _b, _dc in grid]
    nwin = A._audio_fed_before(fs, grid[-1][1]) // win_n
    if nwin < 2 or slices < 2:
        return [None]
    parts = []
    for w0, w1 in _split(nwin, slices):
        lo = max(0, bisect.bisect_right(fed, w0 * win_n) - 1)
        hi = min(len(grid), bisect.bisect_left(fed, w1 * win_n) + 1)
        parts.append({"warm": max(0, lo - A.WARM_CHUNKS), "lo": lo, "hi": hi, "w0": w0, "w1": w1})
    return parts


# ------------------------------------------------------------- the run
class _Pool:
    """The executor, every outstanding task's label, and progress lines as
    they finish."""

    def __init__(self, ex: ProcessPoolExecutor, say, jobs: int):
        self.ex, self.say, self.jobs = ex, say, jobs
        self.pending: dict[Future, str] = {}
        self.submitted = 0
        self.finished = 0

    def submit(self, kind: str, label: str, **kw) -> Future:
        f = self.ex.submit(_task, kind, label, kw)
        self.pending[f] = label
        self.submitted += 1
        return f

    def until(self, futures) -> None:
        """Report completions until every one of `futures` is done (all
        outstanding work when `futures` is None). A worker's exception is
        raised here, as the single-process run would have raised it."""
        def outstanding():
            return [f for f in (self.pending if futures is None else futures) if f in self.pending]
        while outstanding():
            done, _pending = wait(list(self.pending), return_when=FIRST_COMPLETED)
            for f in done:
                label = self.pending.pop(f)
                _out, secs = f.result()
                self.finished += 1
                self.say(_("{label}: done in {secs:.1f} s ({finished}/{submitted} tasks)").format(
                    label=label, secs=secs, finished=self.finished, submitted=self.submitted))


def _result(f: Future):
    return f.result()[0]


def compute(*, data_path: Path, info: dict, n: int, full_scale: int, start_utc: float, dc0, qo100: bool,
            span, want: dict, out_dir: Path, jobs: int, say, slice_s: float | None = None,
            verbose: bool = False, t0_wall: float | None = None) -> dict:
    """What ohsnb.analyse._compute_serial returns, from `jobs` workers.
    `verbose`: workers print a line to stderr as each task starts, timed
    from `t0_wall` (time.time()) like the parent's own lines."""
    t0_wall = time.time() if t0_wall is None else t0_wall
    fs = info["fs"]
    caps = info["captures"]
    duration = n / fs
    grid, contiguous = A._chunk_grid(caps, info, n, fs)
    scope_slices = _how_many(duration, SCOPE_SLICE_S if slice_s is None else slice_s, jobs)
    chan_slices = _how_many(duration, CHANNEL_SLICE_S if slice_s is None else slice_s, jobs)
    if not contiguous:
        say(_("a capture segment has no frequency: every section runs whole, unsliced"))
        scope_slices = chan_slices = 1
    ctx = {"data_path": str(data_path), "datatype": info["datatype"], "scale_override": info.get("scale"),
           "n": n, "fs": fs, "caps": caps, "info": info, "start_utc": start_utc, "full_scale": full_scale,
           "decodes": DECODES_PER_WORKER, "verbose": verbose, "t0_wall": t0_wall}
    run_qo100 = bool(qo100 and dc0 is not None)
    width = span[1] - span[0]
    mp = multiprocessing.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=jobs, mp_context=mp, initializer=_init, initargs=(ctx,))
    pool = _Pool(ex, say, jobs)
    try:
        out = _run(pool, grid, fs, n, info, full_scale, start_utc, dc0, run_qo100, span, width, want, out_dir,
                   scope_slices, chan_slices)
    except BaseException:
        # A failed task, or Ctrl-C: drop what has not started rather than
        # wait for hours of queued slices to run to no purpose.
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return out


def _run(pool: _Pool, grid, fs, n, info, full_scale, start_utc, dc0, run_qo100, span, width, want, out_dir,
         scope_slices, chan_slices) -> dict:
    step = int(A.CHUNK_S * fs)
    # Phase 1: the tracker (whole - see the module docstring), and the two
    # sections that need nothing from it until their last line.
    tracker = pool.submit("tracker", "beacon tracker", rx_corr0=info["rx_corr0"] or 0.0) if run_qo100 else None
    nblocks = -(-n // A.LEVEL_STEP)
    parts = _split(nblocks, scope_slices)
    levels_f = [pool.submit("levels", f"levels {i + 1}/{len(parts)}", lo=lo * A.LEVEL_STEP,
                            hi=min(hi * A.LEVEL_STEP, n)) for i, (lo, hi) in enumerate(parts)]
    wide_f = []
    if dc0 is not None and fs > 0:
        nch = -(-n // step)
        parts = _split(nch, scope_slices)
        wide_f = [pool.submit("wide", f"wide spectrum {i + 1}/{len(parts)}", width=width,
                              lo=lo * step, hi=min(hi * step, n)) for i, (lo, hi) in enumerate(parts)]

    beacon_hist: list[dict] = []
    beacons: dict = {}
    rx = info["rx_corr0"] or 0.0
    if tracker is not None:
        pool.until([tracker])
        beacon_hist = _result(tracker)
        beacons, rx = A._beacons_from(beacon_hist, rx)
    corr_at = A._CorrAt(beacon_hist, rx)
    corr = (corr_at.times, corr_at.corrs)

    # Phase 2: everything else, each section cut as its own docstring says.
    ft8_f = []
    ssb_f = None
    ext_f: dict = {}
    # Submitted longest-first, as far as that is known: a section left
    # whole (PSK31 on a recording under two of its 10-minute windows, the
    # multimedia beacon) and the over-power lines (whose LEILA checks can
    # only start once every one is in) go to the front of the queue, not
    # behind dozens of short slices. Measured on the 16-minute 07/10 CW
    # recording at --jobs 8 it made no difference to the wall time (476 s
    # against 470 s, on a host already at load 20-36): the run was 87-89 %
    # of the ideal either way, its tasks summing to ~3,300 s. Kept because
    # the ordering is what matters on a recording where one whole task is
    # long against the rest.
    if run_qo100 and want["other_modes"]:
        from . import analyse_digital as D
        window_s = D.PSK_WINDOW_S
        ext_f["psk"] = []
        for si in range(len(D._PSK_SEGMENTS)):
            parts = _psk_parts(grid, fs, window_s, chan_slices)
            ext_f["psk"].append([pool.submit("psk", f"PSK31 segment {si + 1} {i + 1}/{len(parts)}", rx=rx,
                                             corr=corr, si=si, window_s=window_s, part=p)
                                 for i, p in enumerate(parts)])
    if run_qo100:
        from ohscore.modes import ft8 as ft8mod
        if want["mmb"]:
            ext_f["mmb"] = pool.submit("mmb", "multimedia beacon (whole)",
                                       rx=rx, corr=corr, out_dir=out_dir)
        if want["overpower"]:
            parts = _split(len(grid), scope_slices)
            ext_f["op_lines"] = [pool.submit("op_lines", f"over-power lines {i + 1}/{len(parts)}", rx=rx,
                                             corr=corr, k_lo=lo, k_hi=hi) for i, (lo, hi) in enumerate(parts)]
        if ft8mod.CAN_DECODE:
            parts = _slot_parts(grid, fs, start_utc, ft8mod.SLOT_S["ft8"], chan_slices)
            ft8_f = [pool.submit("ft8", f"FT8 {i + 1}/{len(parts)}", rx=rx, corr=corr, part=p)
                     for i, p in enumerate(parts)]
        ssb_f = pool.submit("scan_ssb", "SSB scan", dc=dc0 - rx)
        if want["ssb_scale"]:
            from . import analyse_ssb
            parts = _split(analyse_ssb._windows(n, fs), pool.jobs)
            ext_f["ssb_scale"] = [pool.submit("ssb_scale", f"SSB at scale {i + 1}/{len(parts)}", rx=rx, corr=corr,
                                              i_lo=lo, i_hi=hi) for i, (lo, hi) in enumerate(parts)]
        if want["other_modes"]:
            from . import analyse_digital as D
            for mode, spec in D._SLOTTED.items():
                if not spec["module"].CAN_DECODE:
                    continue
                parts = _slot_parts(grid, fs, start_utc, spec["period_s"], chan_slices)
                ext_f[mode] = [pool.submit("slotted", f"{mode.upper()} {i + 1}/{len(parts)}", rx=rx, corr=corr,
                                           mode=mode, part=p) for i, p in enumerate(parts)]
        if want["census"]:
            parts = _split(len(grid), scope_slices)
            ext_f["census"] = [pool.submit("census", f"census {i + 1}/{len(parts)}", rx=rx, corr=corr,
                                           k_lo=lo, k_hi=hi) for i, (lo, hi) in enumerate(parts)]

    # Phase 3: over-power's events join across every slice's lines, in
    # order, here; then their LEILA checks go back out, a batch a task.
    leila_f = []
    op_events: list[dict] = []
    if "op_lines" in ext_f:
        from . import analyse_power
        pool.until(ext_f["op_lines"])
        lines = [ln for f in ext_f["op_lines"] for ln in _result(f)]
        op_events = analyse_power._events_from_lines(lines)
        # The plural follows the events; the lines are many in any capture
        # worth slicing, so their count does not get a form of its own.
        pool.say(ngettext("over-power: {n} event across {lines} lines", "over-power: {n} events across {lines} lines",
                          len(op_events)).format(n=len(op_events), lines=len(lines)))
        for i, (lo, hi) in enumerate(_leila_batches(op_events, pool.jobs * 2)):
            leila_f.append(pool.submit("op_leila", f"over-power LEILA checks {lo + 1}-{hi} of {len(op_events)}",
                                       rx=rx, corr=corr, events=op_events[lo:hi]))
    pool.until(None)

    parts = [_result(f) for f in levels_f]
    levels = A._level_finish(parts or [(0, [], 0)], n, full_scale)
    wide = floor_db = rise_db = None
    if wide_f:
        lines = [ln for f in wide_f for ln in _result(f)]
        wide, floor_db, rise_db = A._wide_finish(lines, fs, width, dc0 - rx, span)
    ft8_report = None
    if ft8_f:
        events, pairs = [], []
        for f in ft8_f:
            ev, pr = _result(f)
            events += ev
            pairs += pr
        ft8_report = A._ft8_report(events, A._ft8_slots(events, pairs))
    ssb = _result(ssb_f) if ssb_f is not None else []
    ext: dict = {}
    if run_qo100:
        if "mmb" in ext_f:
            ext["mmb"] = _result(ext_f["mmb"])
        if "op_lines" in ext_f:
            from . import analyse_power
            ext["overpower"] = {"events": [e for f in leila_f for e in _result(f)],
                                "margin_db": analyse_power.MARGIN_DB}
        if "ssb_scale" in ext_f:
            from . import analyse_ssb
            ext["ssb_scale"] = analyse_ssb._summary([a for f in ext_f["ssb_scale"] for a in _result(f)])
        if want["other_modes"]:
            from . import analyse_digital as D
            om = {}
            for mode in D._SLOTTED:
                events = [e for f in ext_f[mode] for e in _result(f)] if mode in ext_f else None
                om[mode] = D._slotted_summary(mode, events, start_utc, D.BUCKET_S, n / fs)
            segs = [[w for f in seg for w in _result(f)] for seg in ext_f["psk"]]
            om["psk31"] = D._psk_summary(segs, n, fs, D.BUCKET_S)
            ext["other_modes"] = om
        if "census" in ext_f:
            from . import analyse_census as C
            nbuck = max(1, int(math.ceil((n / fs) / C.BUCKET_S)))
            sums = counts = None
            for f in ext_f["census"]:
                s, c = _result(f)
                if sums is None:
                    sums, counts = s, c
                else:
                    sums = [[x + y for x, y in zip(r1, r2)] for r1, r2 in zip(sums, s)]
                    counts = [[x + y for x, y in zip(r1, r2)] for r1, r2 in zip(counts, c)]
            ext["census"] = C._finish(sums, counts, C.BUCKET_S, nbuck)
    return {"levels": levels, "beacon_hist": beacon_hist, "beacons": beacons, "rx_corr_est": rx,
            "wide": wide, "floor_db": floor_db, "rise_db": rise_db, "ft8": ft8_report, "ssb": ssb, "ext": ext}


def _leila_batches(events: list[dict], batches: int) -> list[tuple[int, int]]:
    """Contiguous index ranges of `events` with roughly equal LEILA work
    each - proportional to an event's duration (_leila_check streams its
    whole span), plus a little per event for the set-up."""
    if not events:
        return []
    cost = [max(0.0, e["t_last"] - e["t_start"]) + 2.0 for e in events]
    total = sum(cost)
    per = total / max(1, min(batches, len(events)))
    out, lo, acc = [], 0, 0.0
    for i, c in enumerate(cost):
        acc += c
        if acc >= per and i + 1 < len(events):
            out.append((lo, i + 1))
            lo, acc = i + 1, 0.0
    out.append((lo, len(events)))
    return out
