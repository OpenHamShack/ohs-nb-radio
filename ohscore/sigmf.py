"""Receive IQ recordings in SigMF (https://sigmf.org), written and read.

Why: testers hear things nobody else can (Ray on real QO-100, 05/10/2026),
and a sentence about it is not a signal. A recording of the receive IQ,
exactly as the engine got it, can be looked at in any SigMF tool (inspectrum,
GNU Radio, SigMF's own Python library) or played back through the whole
receiver by the "file" device (ohscore/devices/filedev.py). SigMF rather than
a WAV or a bare .cfile because the metadata travels with the samples in a
documented format: sample rate, centre frequency, when, and - in our own
`openhamshack:` namespace - everything else needed to analyse a recording
without asking the sender (converter, rxCorr and beacon lock, gain, device
and firmware, app and version, OS).

What is recorded: the device's IQ after any software decimation (a Pluto
whose firmware refuses the FIR is decimated in pluto.py, so the file is at
the engine's rate either way), before the engine mirrors it for an
inverting converter and before the noise blanker - the device's stream,
so the playback device can stand in for the device. `openhamshack:inverted`
says when the spectrum in the file is mirrored relative to the air.
Transmit IQ is never recorded; while keyed the receive stream carries on
and an annotation says so.

Format decisions:

- **ci16_le**, not cf32: half the size (1.2 MS/s is 4.8 MB/s, about 290
  MB a minute) for no loss that matters. Full scale is 32768: the engine's
  1.0 (a Pluto's 12-bit sample / 2048) becomes the Pluto's own sample
  shifted left four bits, so an undecimated Pluto recording is exact, and
  software decimation's extra resolution keeps four more bits. Values past
  full scale are clipped and counted (`openhamshack:clipped`).
- **Captures** start at each retune (NB re-centres the hardware as rxCorr
  moves; HAM changes band) and at each gap: samples dropped by a slow disk,
  samples the receive stream never delivered (`openhamshack:rx_lost_samples`,
  counted apart from the disk's), or a device reconnect. A capture after a gap carries its own
  `core:datetime`, and `openhamshack:gap_samples` says how long the gap was,
  so the timeline (FT8 slots) is still known across it.
- **Annotations** mark how the app's watched status changed (transmitting,
  beacon lock, which beacon...), as segments; continuously moving values
  (rxCorr) go in `openhamshack:track` at most once a second.

The writer runs on its own thread behind a bounded queue (QUEUE_S seconds
of samples). The receive thread only appends a reference to the block; a
disk that cannot keep up makes blocks be dropped and counted
(`openhamshack:dropped_samples`), never makes receive wait - the same rule as
the feeds. The .sigmf-meta is written when the recording starts, every
META_EVERY seconds while it runs and when it ends, each time whole and
renamed into place, so a crash still leaves a file that describes what
was written.

Never imports Qt: the engine records, the window only asks it to.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from . import host
from .i18n.text import _

log = logging.getLogger("ohscore.sigmf")

SIGMF_VERSION = "1.2.0"
DATATYPE = "ci16_le"
SCALE = 32768.0              # ci16 value / SCALE = the engine's sample (full scale 1.0)
BYTES_PER_SAMPLE = 4         # ci16: two int16
QUEUE_S = 2.0                # seconds of samples the writer may fall behind before blocks are dropped
META_EVERY = 10.0            # s between rewrites of the .sigmf-meta while recording
TRACK_EVERY = 1.0            # s between points of a tracked value (rxCorr)
GAP_S = 1.0                  # a block arriving this much later than the samples imply starts a new capture
EXT = {"name": "openhamshack", "version": "1.0.0", "optional": True}
DATA_SUFFIX, META_SUFFIX = ".sigmf-data", ".sigmf-meta"


def bytes_per_second(fs: float) -> float:
    return fs * BYTES_PER_SAMPLE


def size_text(n: float) -> str:
    """Bytes as the operator reads them: MB below a gigabyte, GB above."""
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e3:.0f} kB"


def cost_sentence(fs: float) -> str:
    """What a recording costs at sample rate `fs`, said before it starts."""
    rate = bytes_per_second(fs)
    return (f"At {fs / 1e6:g} MS/s a recording takes about {rate / 1e6:.1f} MB a second, "
            f"{size_text(rate * 60)} a minute.")


def iso_utc(t: float) -> str:
    """SigMF's core:datetime: ISO 8601 in UTC with a Z, to the microsecond."""
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(text: str) -> float:
    return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def paths(base: Path) -> tuple[Path, Path]:
    """(data, meta) for a recording's base path; `base` may name either file."""
    base = Path(base)
    if base.name.endswith((DATA_SUFFIX, META_SUFFIX)):
        base = base.with_name(base.name.rsplit(".", 1)[0])
    return base.with_name(base.name + DATA_SUFFIX), base.with_name(base.name + META_SUFFIX)


def new_base(folder: Path, app: str, t: float, dial_hz: float, mode: str, station: dict | None = None) -> Path:
    """A fresh base path in `folder`: app, UTC start, dial and mode (or the
    broadcast `station`: host.recording_name), so a folder of recordings
    sorts by time and says what each is at a glance. Never one that exists
    (two in the same second get -2, -3...)."""
    name = host.recording_name(app, t, dial_hz, mode, station, iq=True)
    folder = Path(folder)
    for i in range(1, 1000):
        base = folder / (name if i == 1 else f"{name}-{i}")
        if not any(p.exists() for p in paths(base)):
            return base
    raise OSError(f"Too many recordings named {name} in {folder}")


def _write_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
        f.write("\n")
    os.replace(tmp, path)


def to_ci16(x: np.ndarray) -> tuple[bytes, int]:
    """complex64 at full scale 1.0 to interleaved little-endian int16, and
    how many values were clipped."""
    v = np.ascontiguousarray(x, np.complex64).view(np.float32) * np.float32(SCALE)
    clipped = int(np.count_nonzero((v > 32767.0) | (v < -32768.0)))
    if clipped:
        np.clip(v, -32768.0, 32767.0, out=v)
    return np.rint(v).astype("<i2").tobytes(), clipped


def _samples(x) -> int:
    """Samples in a block: complex64, or bytes already in the file's own
    ci16 (Recorder.push)."""
    return len(x) // BYTES_PER_SAMPLE if isinstance(x, bytes) else len(x)


class Recorder:
    """One recording. The engine's receive thread calls `push()` with each
    block; anything may call `close()`; the writer thread does the rest.

    `meta` is the global object's fields beyond those the recorder owns
    (core:datatype, sample rate, version, extensions, sha512 and the
    counters); `limit_s` stops the recording by itself after that many
    seconds of samples."""

    def __init__(self, base: Path, fs: float, meta: dict, limit_s: float | None = None,
                 queue_s: float = QUEUE_S):
        self.base = Path(base)
        self.data_path, self.meta_path = paths(self.base)
        self.fs = float(fs)
        self.meta = dict(meta)
        self.limit = int(round(limit_s * self.fs)) if limit_s else 0
        self.cap = int(queue_s * self.fs)
        self.cond = threading.Condition()
        self.q: deque = deque()
        self.queued = 0              # samples waiting in q
        # Counted on the receive thread (accepted, dropped) or the writer
        # (written, clipped); read by anyone for the status line.
        self.accepted = 0            # samples taken into the file's timeline
        self.written = 0
        self.dropped = 0             # lost here: the writer (the disk) more than queue_s behind
        self.drop_events = 0
        self.rx_lost = 0             # lost before they got here: the receive stream's gaps (push's rx_gap)
        self.rx_lost_events = 0
        self.clipped = 0
        self.closing = False
        self.reason = ""             # why it ended: "", "time limit", or an error sentence
        self.error = ""
        self.done = threading.Event()
        self.t_start = None          # UTC of the first sample
        # Metadata built on the receive thread, read by the writer under cond.
        self.captures: list[dict] = []
        self.annotations: list[dict] = []
        self.track: dict[str, list] = {}
        self.open_ann: dict[str, tuple[int, object]] = {}
        self.centre = None
        self.gap = 0                 # samples lost since the last block taken (dropped, or a gap in time)
        self.expect_utc = None       # where the next block should start if nothing was lost
        self.next_track = 0.0
        self.sha = hashlib.sha512()
        self.thread = threading.Thread(target=self._run, name="ohscore-rec", daemon=True)

    def start(self) -> "Recorder":
        self.base.parent.mkdir(parents=True, exist_ok=True)
        # Created here, on the caller's thread, so a folder that cannot be
        # written is a sentence at once rather than a recording that never was.
        self.f = open(self.data_path, "xb")
        self._write_meta()
        self.thread.start()
        return self

    # ------------------------------------------------------------ receive thread
    def push(self, x: np.ndarray, centre: tuple[float, float], utc: float, facts: dict | None = None,
             track: dict | None = None, rx_gap: int = 0) -> bool:
        """Take one receive block: complex64 at full scale 1.0, or `bytes`
        already in ci16 (to_ci16's - NB's LEILA capture keeps its ring that
        way, so 20 s of 1.2 MS/s fit in 96 MB and are written without being
        converted back). `centre` is (device Hz, on-air Hz) of the
        block's DC, `utc` when its first sample was received, `facts` the
        watched status values (annotated as they change), `track` the
        continuous ones; `rx_gap` the samples the receive stream lost just
        before this block (ohscore/rxprefetch.py), which `utc` already
        accounts for. Never blocks and never touches the disk. Returns
        False once the recording has ended (the time limit, or the writer
        failed): the caller stops calling."""
        if self.closing:
            return False
        n = _samples(x)
        if self.limit and self.accepted + n >= self.limit:
            x = x[:self.limit - self.accepted] if not isinstance(x, bytes) else \
                x[:(self.limit - self.accepted) * BYTES_PER_SAMPLE]
            n = _samples(x)
        if rx_gap > 0:
            # Lost before they reached the program: the receive stream's
            # gap, not the disk's. Counted apart, so the operator is told
            # which of the two to look at (17/10/2026: a stalled network
            # link to the Pluto was reported as "disk too slow").
            self.rx_lost += rx_gap
            self.rx_lost_events += 1
            self.gap += rx_gap
            if self.expect_utc is not None:
                self.expect_utc += rx_gap / self.fs
        if self.expect_utc is not None and utc - self.expect_utc > GAP_S:
            # A reconnect, or the engine stalled: real time passed with no samples.
            self.gap += int(round((utc - self.expect_utc) * self.fs))
        self.expect_utc = utc + n / self.fs
        with self.cond:
            if self.queued + n > self.cap:
                # The writer is behind by more than QUEUE_S: lose this block,
                # never wait for the disk. The file goes on from the next
                # block taken, as a new capture that says how much is missing.
                self.dropped += n
                self.drop_events += 1
                self.gap += n
                return True
            start = self.accepted
            if self.t_start is None:
                self.t_start = utc
            if self.centre != centre or self.gap or not self.captures:
                cap = {"core:sample_start": start, "core:frequency": round(float(centre[1]), 3),
                       "openhamshack:device_hz": round(float(centre[0]), 3)}
                if self.gap or not self.captures:
                    cap["core:datetime"] = iso_utc(utc)
                    cap["openhamshack:utc"] = round(utc, 6)
                if self.gap and self.captures:
                    cap["openhamshack:gap_samples"] = self.gap
                self.captures.append(cap)
                self.centre, self.gap = centre, 0
            for k, v in (facts or {}).items():
                was = self.open_ann.get(k)
                if was is None or was[1] != v:
                    if was is not None:
                        self._close_ann(k, start)
                    self.open_ann[k] = (start, v)
            t_rel = start / self.fs
            if track and t_rel >= self.next_track:
                self.next_track = t_rel + TRACK_EVERY
                for k, v in track.items():
                    pts = self.track.setdefault(k, [])
                    v = None if v is None else round(float(v), 3)
                    if v is not None and (not pts or pts[-1][1] != v):
                        pts.append([start, v])
            # The block is referenced, not copied: the engine never writes
            # into a block it has read, and every device hands over a new
            # array per read.
            self.q.append(x)
            self.queued += n
            self.accepted += n
            self.cond.notify()
        if self.limit and self.accepted >= self.limit:
            self.close("time limit")
            return False
        return True

    def _close_ann(self, key: str, end: int) -> None:
        start, v = self.open_ann.pop(key)
        if end <= start:
            return
        self.annotations.append({"core:sample_start": start, "core:sample_count": end - start,
                                 "core:label": f"{key}: {v}", "openhamshack:key": key, "openhamshack:value": v})

    # ------------------------------------------------------------ any thread
    def close(self, reason: str = "") -> None:
        """End the recording. Returns at once; the writer finishes what is
        queued and writes the final metadata (wait() for it)."""
        with self.cond:
            if not self.closing:
                self.closing = True
                self.reason = self.reason or reason
            self.cond.notify()

    def wait(self, timeout: float | None = None) -> bool:
        return self.done.wait(timeout)

    @property
    def seconds(self) -> float:
        return self.accepted / self.fs

    @property
    def nbytes(self) -> int:
        return self.written * BYTES_PER_SAMPLE

    # ------------------------------------------------------------ writer thread
    def _run(self) -> None:
        next_meta = time.monotonic() + META_EVERY
        try:
            while True:
                with self.cond:
                    while not self.q and not self.closing:
                        self.cond.wait(0.5)
                        if time.monotonic() >= next_meta:
                            break
                    x = self.q.popleft() if self.q else None
                    if x is None and self.closing:
                        break
                if x is not None:
                    self._write_block(x)
                    with self.cond:
                        self.queued -= _samples(x)
                if time.monotonic() >= next_meta:
                    next_meta = time.monotonic() + META_EVERY
                    self._write_meta()
        except OSError as e:
            # A full disk, a pulled USB stick: the recording ends with what
            # was written, and says why.
            self.error = f"Recording stopped: could not write {self.data_path.name} ({e})"
            log.warning("%s", self.error)
            with self.cond:
                self.closing = True
                self.reason = self.error
                self.q.clear()
                self.queued = 0
        finally:
            try:
                self.f.close()
            except OSError:
                pass
            try:
                self._write_meta(final=True)
            except OSError as e:
                self.error = self.error or f"Could not write {self.meta_path.name} ({e})"
                log.warning("writing %s failed: %s", self.meta_path, e)
            self.done.set()

    def _write_block(self, x) -> None:
        if isinstance(x, bytes):
            data, clipped = x, 0
        else:
            data, clipped = to_ci16(x)
        self.f.write(data)
        self.sha.update(data)
        self.written += _samples(x)
        self.clipped += clipped

    def _write_meta(self, final: bool = False) -> None:
        with self.cond:
            anns = list(self.annotations)
            if final:
                # Segments still open run to the end of what was written.
                end = self.accepted
                for k in list(self.open_ann):
                    self._close_ann(k, end)
                anns = list(self.annotations)
            caps = [dict(c) for c in self.captures]
            track = {k: list(v) for k, v in self.track.items()}
        anns.sort(key=lambda a: a["core:sample_start"])
        g = {"core:datatype": DATATYPE, "core:sample_rate": self.fs, "core:version": SIGMF_VERSION,
             "core:num_channels": 1, "core:extensions": [dict(EXT)]}
        g.update(self.meta)
        g.update({"openhamshack:scale": SCALE, "openhamshack:samples": self.written,
                  "openhamshack:seconds": round(self.written / self.fs, 3),
                  "openhamshack:dropped_samples": self.dropped, "openhamshack:dropped_blocks": self.drop_events,
                  "openhamshack:rx_lost_samples": self.rx_lost, "openhamshack:rx_lost_gaps": self.rx_lost_events,
                  "openhamshack:queue_s": self.cap / self.fs, "openhamshack:clipped": self.clipped,
                  "openhamshack:complete": bool(final), "openhamshack:stopped": self.reason or ("by the operator" if final
                                                                                    else "")})
        if track:
            g["openhamshack:track"] = track
        if final:
            g["core:sha512"] = self.sha.hexdigest()
        _write_json(self.meta_path, {"global": g, "captures": caps, "annotations": anns})


# ---------------------------------------------------------------- reading
DTYPES = {
    # SigMF datatype -> (numpy dtype of one component, scale to full scale 1.0)
    "ci16_le": ("<i2", 1 / SCALE), "ci16_be": (">i2", 1 / SCALE),
    "cf32_le": ("<f4", 1.0), "cf32_be": (">f4", 1.0),
    "ci8": ("i1", 1 / 128.0), "cu8": ("u1", 1 / 128.0),
}


def validate(meta: dict, strict: bool = True) -> list[str]:
    """What is wrong with a SigMF metadata object against the core rules
    this program relies on: [] if nothing. Checked when a recording is
    written (tests) and before one is played. `strict=False` lets pass a
    namespace used but not declared in core:extensions: a rule for writers,
    which files from other programs (and our own hand-made ones of
    07/10/2026) break without being any harder to play."""
    out = []
    if not isinstance(meta, dict):
        return ["the metadata is not a JSON object"]
    g, caps, anns = meta.get("global"), meta.get("captures"), meta.get("annotations")
    if not isinstance(g, dict):
        return ["there is no global object"]
    for k in ("core:datatype", "core:version"):
        if not isinstance(g.get(k), str) or not g.get(k):
            out.append(f"global {k} is missing")
    if "core:sample_rate" in g and not (isinstance(g["core:sample_rate"], (int, float))
                                        and g["core:sample_rate"] > 0):
        out.append("core:sample_rate must be a positive number")
    if not isinstance(caps, list):
        out.append("captures must be a list")
        caps = []
    if not isinstance(anns, list):
        out.append("annotations must be a list")
        anns = []
    starts = []
    for i, c in enumerate(caps):
        s = c.get("core:sample_start") if isinstance(c, dict) else None
        if not isinstance(s, int) or s < 0:
            out.append(f"capture {i} has no core:sample_start")
            continue
        starts.append(s)
        if "core:datetime" in c:
            try:
                parse_utc(c["core:datetime"])
            except (TypeError, ValueError):
                out.append(f"capture {i}'s core:datetime is not ISO 8601")
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        out.append("captures are not in order of core:sample_start")
    last = -1
    for i, a in enumerate(anns):
        s = a.get("core:sample_start") if isinstance(a, dict) else None
        if not isinstance(s, int) or s < 0:
            out.append(f"annotation {i} has no core:sample_start")
            continue
        if s < last:
            out.append("annotations are not in order of core:sample_start")
        last = s
    if not strict:
        return out
    # Every namespace used must be core or declared in core:extensions.
    declared = {"core"} | {e.get("name") for e in g.get("core:extensions", []) if isinstance(e, dict)}
    used = {k.split(":", 1)[0] for obj in [g, *caps, *anns] if isinstance(obj, dict) for k in obj}
    for ns in sorted(used - declared):
        out.append(f"namespace {ns!r} is used but not declared in core:extensions")
    return out


def read_meta(path: Path, strict: bool = True) -> dict:
    """The metadata of the recording at `path` (either file, or the base),
    checked (`strict`: as validate()); raises ValueError with a sentence."""
    _data, meta_path = paths(path)
    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(_("{file} is missing: a recording needs both its .sigmf-meta and its .sigmf-data").format(
            file=meta_path.name)) from None
    except (OSError, ValueError) as e:
        raise ValueError(_("{file} cannot be read ({error})").format(file=meta_path.name, error=e)) from None
    bad = validate(meta, strict)
    if bad:
        raise ValueError(_("{file} is not valid SigMF: {problems}").format(file=meta_path.name, problems="; ".join(bad)))
    return meta


def duration(meta: dict, nbytes: int) -> float:
    """Seconds of samples in a data file of `nbytes` under `meta`."""
    g = meta["global"]
    comp = np.dtype(DTYPES.get(g["core:datatype"], ("<i2", 0))[0]).itemsize
    fs = float(g.get("core:sample_rate") or 0)
    return nbytes / (2 * comp) / fs if fs > 0 else math.nan
