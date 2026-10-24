"""Timeshift on the controller (Brian, 24/10/2026, for the TV's DAB Radio):
while a broadcast station plays (Engine.broadcast_station: Radio's DAB
station, or wide FM), the last `timeshiftMinutes` of what it played are
kept on disk, so a client can listen from behind live (api/audio/rx
`?behind=`) and a recording can begin in the past (api/recordings/start
`fromSecondsAgo`, `fromItemStart`, `lastMinutes`; recording.py).

**What is kept** is the receive audio the listeners and recordings get
(StreamAudio's blocks, tapped like a recording), always as two channels
at the app's rate (48 kHz for Radio): a broadcast station's recording is
stereo (recording.py), and one shape makes every reader the same.

**One station's, and nothing across a restart.** The buffer starts when a
station starts playing and is cleared when it changes (another DAB
service or block, another wide FM frequency), when it stops, when the
radio stops, and when this app starts: the folder is emptied then, since
an hour of a station from before a restart is not what anybody means by
"behind live", and the time each sample was played is known only from
when the buffer began (t0 + samples / rate). A timeshifted stream or a
recording still reading from the past when the buffer is cleared ends
its reading there.

**On disk, compressed, in chunks** of CHUNK_S under the data folder's
`timeshift`: each chunk a file, the oldest deleted once the buffer holds
more than its length, or more bytes than the same audio as raw PCM would
take (11.5 MB a minute at 48 kHz stereo), or the disk's free space falls
below the recordings' floor (the buffer stops then, with the reason in
status). The codec is ours (`encode`/`decode`): a second-order fixed
predictor on the left channel and on left minus right, zigzagged into
three byte planes, then zlib - lossless, and in numpy and the standard
library both ways. FLAC was the first choice and is what a recording is
(shack_rec), but this app has only shack_rec's FLAC *encoder*: a stream
from behind live and a recording from the past both need the audio back
as PCM, and a FLAC decoder's Rice and LPC loops are per sample in Python.
Measured on shack (24/10/2026) at 48 kHz stereo, per second of audio:
encoding 1-4 ms and decoding 1-2 ms, against shack_rec's FLAC encoder's
28-48 ms; on band-limited noise ("music") 40 % of the raw size, a mono
station in stereo 20 %, the simulator's tones 2 %, white noise 96 %
(FLAC: 13 % tones, 86 % noise).

**The audio thread only hands a block over** (`_tap`): a reference to the
block's bytes into a list, and the forwarding a recording that started in
the past needs once it has caught up. Encoding and the disk are the
writer thread's. If the writer falls more than QUEUE_S behind (a stalled
disk) the buffer starts again rather than holding a gap it cannot place
in time. `tap_cost()` is the audio thread's time in the tap, per second
of audio (tests/test_timeshift.py measures it: about 40 us a second on shack).
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..i18n.text import _

log = logging.getLogger("ohscore.server")

CHANNELS = 2
CHUNK_S = 2.0            # audio a chunk file holds: the finest the buffer is trimmed by
QUEUE_S = 4.0            # audio the writer may fall behind before the buffer starts again
POLL_S = 0.5             # how often the station and the settings are looked at
ZLEVEL = 1               # zlib's fastest: 6 saves 3-5 % more for four times the time
SUFFIX = ".ohsts"


# ------------------------------------------------------------------ codec
def encode(pcm: np.ndarray) -> bytes:
    """(n, 2) int16 to bytes: see the module docstring."""
    a = np.asarray(pcm, np.int32)
    out = []
    for c in (a[:, 0], a[:, 0] - a[:, 1]):
        r = np.diff(c, n=2, prepend=[0, 0])                  # |r| < 2**18 for int16 audio
        z = ((r << 1) ^ (r >> 31)).astype(np.uint32)         # zigzag: small magnitudes, small numbers
        out.append(np.stack([(z >> (8 * i)) & 0xFF for i in range(3)]).astype(np.uint8).tobytes())
    return zlib.compress(b"".join(out), ZLEVEL)


def decode(data: bytes, n: int) -> np.ndarray:
    """encode()'s bytes back to (n, 2) int16, exactly."""
    planes = np.frombuffer(zlib.decompress(data), np.uint8).reshape(2, 3, n).astype(np.uint32)
    out = []
    for p in planes:
        z = p[0] | (p[1] << 8) | (p[2] << 16)
        r = (z >> 1).astype(np.int64) ^ -(z & 1).astype(np.int64)
        out.append(np.cumsum(np.cumsum(r)))
    left, side = out
    return np.stack([left, left - side], axis=1).astype(np.int16)


@dataclass
class _Chunk:
    index: int               # its first sample, counted from the buffer's start
    n: int
    path: Path
    nbytes: int


def station_key(st: dict | None):
    """What makes two moments the same station: DAB's block and service,
    wide FM's frequency. Not the names, which arrive after it starts."""
    if not st:
        return None
    if st.get("kind") == "dab":
        return ("dab", st.get("block"), st.get("sid"))
    return (st.get("kind"), round(float(st.get("freqHz") or 0)))


class Gone(Exception):
    """What was being read is no longer in the buffer: cleared (another
    station) or trimmed past."""


class _Follower:
    """A recording fed from the buffer: the past first, then live blocks
    as the tap hands them over."""

    def __init__(self, push):
        self.push = push
        self.q: deque = deque()          # live blocks that arrived while the past was being sent
        self.direct = False              # caught up: the tap pushes straight through
        self.gone = False


class Timeshift:
    def __init__(self, radio, audio, folder: Path, *, floor_bytes: int = 2_000_000_000,
                 disk_usage=shutil.disk_usage, wall=time.time):
        self.radio, self.audio = radio, audio
        self.folder = Path(folder)
        self.floor_bytes = int(floor_bytes)
        self.disk_usage = disk_usage
        self.wall = wall
        self.cond = threading.Condition()
        self.rate = int(getattr(audio, "out_rate", 48_000))
        self.gen = 0                     # bumps every time the buffer starts again
        self.key = None
        self.station: dict | None = None
        self.chunks: deque[_Chunk] = deque()
        self.nbytes = 0                  # the chunks' bytes on disk
        self.doomed: list[Path] = []     # chunk files to delete, outside the lock
        self.pending: list[np.ndarray] = []
        self.pending_n = 0
        self.flushing: tuple[int, np.ndarray] | None = None   # taken from pending, not yet a chunk
        self.total = 0                   # samples a channel since the buffer began
        self.base = 0                    # the first sample still kept
        self.t0: float | None = None     # UTC of sample 0
        self.buffering = False
        self.overflow = False
        self.cap_s = 0.0
        self.why = ""
        self.item: dict | None = None    # DL Plus's item now: {"index" (None: began before the buffer), "title", "artist"}
        self.item_seen = False           # whether this buffer has heard any item
        self.followers: list[_Follower] = []
        self.untap = None
        self._cost = [0.0, 0]            # seconds in _tap, samples through it
        self._clear_folder()

    # ---------------------------------------------------------------- audio thread
    def _tap(self, pcm: bytes) -> None:
        t = time.perf_counter()
        a = np.frombuffer(pcm, "<i2").reshape(-1, CHANNELS)
        n = len(a)
        with self.cond:
            if self.buffering:
                if self.t0 is None:
                    self.t0 = self.wall() - n / self.rate
                if (self.pending_n + n) > QUEUE_S * self.rate:
                    self.overflow = True
                else:
                    self.pending.append(a)
                    self.pending_n += n
                    self.total += n
                    self.cond.notify_all()
            for f in self.followers:
                if f.direct:
                    if not f.push(pcm):
                        f.gone = True
                else:
                    f.q.append(pcm)
            if any(f.gone for f in self.followers):
                self.followers = [f for f in self.followers if not f.gone]
        self._cost[0] += time.perf_counter() - t
        self._cost[1] += n

    def tap_cost(self) -> float:
        """The audio thread's seconds in the tap per second of audio."""
        s, n = self._cost
        return s / (n / self.rate) if n else 0.0

    def _tapped(self, want: bool) -> None:
        """Called under the lock: tapped while buffering or feeding a recording."""
        if want and self.untap is None:
            self.untap = self.audio.tap(self._tap, CHANNELS)
        elif not want and self.untap is not None:
            self.untap()
            self.untap = None

    # ---------------------------------------------------------------- writer thread
    def run(self, stop: threading.Event) -> None:
        """The writer: the station and the settings every POLL_S, and each
        CHUNK_S of audio encoded to disk. Until `stop` is set."""
        next_poll = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_poll or self.overflow:
                next_poll = now + POLL_S
                try:
                    self._watch()
                except Exception:  # noqa: BLE001 - the buffer is never worth the server
                    log.warning("timeshift: looking at the station failed", exc_info=True)
            with self.cond:
                if self.pending_n < CHUNK_S * self.rate and not self.overflow:
                    self.cond.wait(min(POLL_S, max(0.01, next_poll - time.monotonic())))
            self._flush()
            self._delete()
        with self.cond:
            self._stop_buffer("")
            self.followers = []
            self._tapped(False)
        self._delete()

    def _delete(self) -> None:
        """Chunk files cleared or trimmed, deleted here rather than under the
        lock: clearing an hour is some 1800 files, and the audio thread
        must never wait for that."""
        with self.cond:
            doomed, self.doomed = self.doomed, []
        for p in doomed:
            p.unlink(missing_ok=True)

    def _watch(self) -> None:
        minutes = float(self.radio.st.get("timeshiftMinutes") or 0)
        running = bool(self.radio.state().get("running"))
        st = self.radio.broadcast_station() if minutes > 0 and running else None
        key = station_key(st)
        with self.cond:
            self.cap_s = minutes * 60.0
            if self.overflow:
                log.warning("timeshift: the writer fell %g s behind; starting the buffer again", QUEUE_S)
                self._stop_buffer("")
            if key != self.key or (st is not None and not self.buffering and not self.why):
                self._stop_buffer("")
                if st is not None:
                    self._start_buffer(st, key)
            elif st is not None:
                self.station = st
                self._note_item(st)
            self._trim()

    def _start_buffer(self, st: dict, key) -> None:
        self.gen += 1
        self.key, self.station = key, st
        self.rate = int(getattr(self.audio, "out_rate", self.rate))
        self.total = self.base = 0
        self.t0 = None
        self.buffering, self.overflow, self.why = True, False, ""
        # What is on as the buffer begins began before it: its start is not here.
        self.item = {"index": None, "title": st.get("title"), "artist": st.get("artist")} \
            if st.get("title") or st.get("artist") else None
        self.item_seen = self.item is not None
        self._tapped(True)
        log.info("timeshift: keeping %s (%s)", st.get("label") or key, f"{self.cap_s / 60:g} minutes")

    def _stop_buffer(self, why: str) -> None:
        """Clear the buffer (under the lock). Readers of it see Gone."""
        if self.buffering or self.chunks:
            self.gen += 1
        self.buffering, self.overflow, self.why = False, False, why
        self.key = None if not why else self.key
        self.station = None if not why else self.station
        self.doomed += [c.path for c in self.chunks]
        self.chunks.clear()
        self.nbytes = 0
        self.pending, self.pending_n, self.flushing = [], 0, None
        self.total = self.base = 0
        self.t0, self.item = None, None
        self._tapped(bool(self.followers))
        self.cond.notify_all()

    def _note_item(self, st: dict) -> None:
        """DL Plus's item changing is an item starting, here (to POLL_S).
        The first item heard after tuning in is not: DL Plus comes a few
        seconds after the sound, so that item was on before the buffer."""
        now = (st.get("title"), st.get("artist"))
        was = (self.item or {}).get("title"), (self.item or {}).get("artist")
        if now != was:
            self.item = {"index": self.total if self.item_seen else None, "title": now[0], "artist": now[1]} \
                if any(now) else None
            self.item_seen = self.item_seen or any(now)

    def _flush(self) -> None:
        with self.cond:
            if not self.pending_n or (self.pending_n < CHUNK_S * self.rate and self.buffering):
                return
            gen, index = self.gen, self.total - self.pending_n
            pcm = np.concatenate(self.pending)
            self.pending, self.pending_n = [], 0
            self.flushing = (index, pcm)
        data = encode(pcm)
        path = self.folder / f"{gen}-{index}{SUFFIX}"
        try:
            if self.disk_usage(self.folder).free - len(data) < self.floor_bytes:
                raise OSError(_("not enough free disk space"))
            path.write_bytes(data)
        except OSError as e:
            with self.cond:
                if self.gen == gen:
                    why = _("Timeshift stopped: {error}").format(error=e.strerror or str(e))
                    log.warning("%s", why)
                    self._stop_buffer(why)
            return
        with self.cond:
            if self.gen != gen:
                self.doomed.append(path)              # cleared meanwhile
                return
            self.chunks.append(_Chunk(index, len(pcm), path, len(data)))
            self.nbytes += len(data)
            self.flushing = None
            self._trim()
            self.cond.notify_all()

    def _trim(self) -> None:
        """The oldest chunks go while the rest still hold the buffer's
        length, and while it holds more bytes than raw PCM would."""
        cap_n = self.cap_s * self.rate
        cap_bytes = cap_n * CHANNELS * 2
        while self.chunks:
            c = self.chunks[0]
            left = self.total - (c.index + c.n)
            if left < cap_n and self.nbytes <= cap_bytes:
                break
            self.chunks.popleft()
            self.nbytes -= c.nbytes
            self.doomed.append(c.path)
            self.base = c.index + c.n

    def _clear_folder(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            for p in self.folder.glob("*" + SUFFIX):
                p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("timeshift: cannot use %s: %s", self.folder, e)

    # ---------------------------------------------------------------- readers
    def status(self) -> dict:
        """api/status `timeshift`."""
        with self.cond:
            length = (self.total - self.base) / self.rate if self.buffering else 0.0
            item = self.item
            out = {"available": self.buffering and length > 0, "startUtc": self._iso(self.base) if length else None,
                   "lengthS": round(length, 1), "capS": round(self.cap_s), "station": self.station,
                   "itemStartUtc": None, "itemStartInBuffer": False}
            if item and length:
                # An item on since before the buffer (the first one heard
                # after tuning in, or one longer than the buffer) starts, as
                # far as anyone can go back, at the buffer's start: a client
                # can still offer "from the start of this song" (ohs-box,
                # 24/10/2026: STV Radio showed none for minutes otherwise).
                inside = item["index"] is not None and item["index"] >= self.base
                out["itemStartUtc"] = self._iso(item["index"] if inside else self.base)
                out["itemStartInBuffer"] = inside
            if self.why:
                out["why"] = self.why
            return out

    def _iso(self, index: int) -> str | None:
        if self.t0 is None:
            return None
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t0 + index / self.rate))

    def utc(self, index: int) -> float | None:
        with self.cond:
            return None if self.t0 is None else self.t0 + index / self.rate

    def position(self, seconds_ago: float) -> tuple[int, int, float]:
        """(gen, index, seconds actually behind) for `seconds_ago` clamped to
        what is kept; Gone when nothing is."""
        with self.cond:
            if not self.buffering or self.total <= self.base:
                raise Gone()
            back = int(round(min(max(0.0, float(seconds_ago)), (self.total - self.base) / self.rate) * self.rate))
            return self.gen, self.total - back, back / self.rate

    def item_start(self) -> tuple[int, int, float, str]:
        """(gen, index, seconds behind, why) of the current DL Plus item's
        start: why "" when found, else the sentence saying what was used
        instead (the buffer's start, or now)."""
        with self.cond:
            item = self.item
            if not self.buffering or self.total <= self.base:
                raise Gone()
            if item is None:
                return self.gen, self.total, 0.0, _("The station has sent no item (DL Plus) to start from: "
                                                    "recording from now")
            if item["index"] is None or item["index"] < self.base:
                return self.gen, self.base, (self.total - self.base) / self.rate, _(
                    "This item began before the timeshift buffer: recording from the buffer's start")
            return self.gen, item["index"], (self.total - item["index"]) / self.rate, ""

    def read(self, gen: int, index: int, n: int, timeout: float = 1.0) -> np.ndarray:
        """Up to `n` samples from `index` of buffer `gen`, waiting up to
        `timeout` for any (an empty array then). Raises Gone."""
        end = time.monotonic() + timeout
        with self.cond:
            while True:
                if self.gen != gen or index < self.base:
                    raise Gone()
                if index < self.total:
                    break
                left = end - time.monotonic()
                if left <= 0:
                    return np.zeros((0, CHANNELS), np.int16)
                self.cond.wait(left)
            chunk = next((c for c in self.chunks if c.index <= index < c.index + c.n), None)
            if chunk is None:
                # Not on disk yet: being encoded, or still pending.
                parts, at = [], self.total - self.pending_n
                if self.flushing is not None:
                    parts.append(self.flushing)
                parts.append((at, np.concatenate(self.pending) if self.pending else np.zeros((0, 2), np.int16)))
                for i0, pcm in parts:
                    if i0 <= index < i0 + len(pcm):
                        return pcm[index - i0:index - i0 + n].copy()
                raise Gone()
        try:
            pcm = decode(chunk.path.read_bytes(), chunk.n)
        except (OSError, ValueError, zlib.error):
            raise Gone() from None                      # trimmed or cleared as it was read
        return pcm[index - chunk.index:index - chunk.index + n]

    # ---------------------------------------------------------------- recordings from the past
    def follow(self, gen: int, index: int, push, *, until_now: bool = False, room=None, on_end=None) -> _Follower:
        """Feed `push` (a recording's) from sample `index` of buffer `gen`:
        the past on a thread of its own, as fast as `room()` allows (the
        recorder's queue must not overflow), then - unless `until_now` -
        every live block, for as long as `push` returns True. `on_end(why)`
        is called once the past has been sent with `until_now` (why: "", or
        the sentence saying why not all of it was). Returns the handle for
        unfollow(); raises Gone."""
        f = _Follower(push)
        with self.cond:
            if self.gen != gen or index < self.base:
                raise Gone()
            stop_at = self.total
            if not until_now:
                self.followers.append(f)
                self._tapped(True)
        t = threading.Thread(target=self._feed, args=(f, gen, index, stop_at, until_now, room, on_end),
                             name="server-timeshift-feed", daemon=True)
        t.start()
        return f

    def _feed(self, f: _Follower, gen: int, index: int, stop_at: int, until_now: bool, room, on_end) -> None:
        why = ""
        step = int(self.rate * 0.5)
        try:
            while index < stop_at and not f.gone:
                while room is not None and not room():
                    if f.gone:
                        return
                    time.sleep(0.02)
                pcm = self.read(gen, index, min(step, stop_at - index), timeout=2.0)
                if not len(pcm):
                    continue
                if not f.push(pcm.tobytes()):
                    f.gone = True
                    break
                index += len(pcm)
        except Gone:
            why = _("the timeshift buffer was cleared while it was being read")
            log.info("timeshift: %s", why)
        if until_now:
            if on_end is not None:
                on_end(why)
            return
        # Caught up: what arrived meanwhile, then straight through.
        while not f.gone:
            with self.cond:
                if not f.q:
                    f.direct = True
                    return
                blocks = list(f.q)
                f.q.clear()
            for b in blocks:
                while room is not None and not room() and not f.gone:
                    time.sleep(0.02)
                if not f.push(b):
                    f.gone = True
                    break

    def unfollow(self, f: _Follower) -> None:
        """follow()'s feeding ends (the recording closed)."""
        with self.cond:
            f.gone = True
            self.followers = [x for x in self.followers if not x.gone]
            self._tapped(self.buffering or bool(self.followers))
