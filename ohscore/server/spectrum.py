"""spectrum/1 on api/spectrum/v1 (CLIENT-UI-PLAN.md §2, docs/SERVER-API.md
"spectrum/1"): one waterfall feed shape for every OpenHamShack app.

The rows are the engine's own `wide` and `zoom` feeds, the same items
api/events sends as base64 JSON (which stays, unchanged, for the clients
that read it: §2.5). Nothing upstream of Engine.subscribe changes for a
client - not the FFT size, rate or averaging - so a viewer can never cost
the receiver resolution or SNR; each client is cropped, decimated and
quantised on top of the shared feed by ohs-libs' shack_spectrum, the
reference encoder every client's decoder is tested against. It is not
reimplemented here, so a fix there reaches this app by a re-vendor.

Per socket: a reader thread (subscribe messages in, pings answered by
ws.Socket), the handler's own thread draining the engine feeds, and a
writer thread, so that a client whose socket has stopped draining never
holds up the loop. Rows go through shack_spectrum's LatestWins - one
pending row per stream, replaced rather than queued, and `gap` on the row
after a replaced one - because a queue on a slow Fire TV or tunnel means
watching the past. Text frames (stream, levels, overlay) are queued in
order with the rows: a levels message must reach the client before the
first row quantised with it.

Caps the client cannot raise (§2.4): 25 rows a second and 2048 columns a
stream, for every client. The plan's lower caps for a TV (15 fps) and a
tunnel client (4 fps, 512 columns) are not applied: the identity headers
(shack.shack_identity) say who and at what level, but not what kind of
device or over which path, and guessing would throttle the wrong people.
"""
from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
from collections import deque

from .. import shacklibs
from ..i18n.text import _

log = logging.getLogger("ohscore.server.spectrum")

# spectrum/1 stream -> the engine feed it is made from. Flex's pan-<id>
# and Icom's receiver-<n> are other apps' streams.
STREAMS = {"main": "wide", "zoom": "zoom"}
MAX_FPS = 25.0
MAX_COLS = 2048
MAX_CLIENTS = 8
# noiseDb/peakDb for the client's display auto-levels (§2.3, §4.2): about
# once a second, only when the socket is idle, so they never pile up
# behind a stalled client.
LEVELS_EVERY_S = 1.0
# Hann window's equivalent noise bandwidth, in bins: the RBW a scope shows.
HANN_ENBW = 1.5
# Each connection's own subscription to an engine feed: deep enough that
# a loop a few polls late loses nothing (LatestWins, not the feed, is
# what drops rows for a slow client), and no deeper.
FEED_DEPTH = 16
POLL_S = 0.02


class Shared:
    """What every client of one server shares: the client count, and per
    stream the levels window and the description with its rev. One window
    per stream, not per client, so every client quantises alike and a
    window move is one event (§2.3). Each connection drains its own feed,
    so the same engine row reaches here once per client; it is applied
    once, by capture time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = 0
        self.streams: dict[str, dict] = {s: {"window": None, "gen": 0, "t": None, "desc": None, "rev": 0}
                                         for s in STREAMS}

    def join(self) -> bool:
        with self.lock:
            if self.clients >= MAX_CLIENTS:
                return False
            self.clients += 1
            return True

    def leave(self) -> None:
        with self.lock:
            self.clients -= 1

    def update(self, stream: str, item, extra: dict) -> dict:
        """Take one engine row for `stream`; the stream's shared state
        (window, gen counting window moves, desc and its rev)."""
        sp = shacklibs.spectrum()
        t, start, bin_hz, db = item
        s = self.streams[stream]
        with self.lock:
            if s["t"] is not None and t <= s["t"]:
                return s
            s["t"] = t
            if s["window"] is None:
                s["window"] = sp.LevelsWindow()
            if s["window"].update(db, int(t * 1000)):
                s["gen"] += 1
            n = len(db)
            dc = getattr(item, "dc_bins", None)
            d = s["desc"]
            # The description moves (a new rev, streamChanged on the next
            # row) when the bins change, or the span by a whole bin or
            # more: each row carries its own loHz, so the tracking's
            # sub-bin corrections in NB never churn rev at frame rate.
            same = (d is not None and d["srcBins"] == n and d["binHz"] == float(bin_hz)
                    and abs(d["loHz"] - float(start)) < float(bin_hz)
                    and d.get("dcBins") == ([int(dc[0]), int(dc[1])] if dc is not None else None)
                    and all(d.get(k) == v for k, v in extra.items()))
            if not same:
                s["rev"] += 1
                span = n * float(bin_hz)
                d = {"type": "stream", "stream": stream, "rev": s["rev"], "centreHz": float(start) + span / 2,
                     "spanHz": span, "loHz": float(start), "hiHz": float(start) + span, "binHz": float(bin_hz),
                     "rbwHz": HANN_ENBW * float(bin_hz), "srcBins": n, "units": "dB", "calibrated": False,
                     **extra}
                if dc is not None:
                    d["dcBins"] = [int(dc[0]), int(dc[1])]
                s["desc"] = d
            return s


def _bad(code: str, text: str, stream: str | None = None) -> dict:
    msg = {"type": "error", "code": code, "message": text}
    if stream is not None:
        msg["stream"] = stream
    return msg


def parse_subscribe(msg) -> tuple[dict | None, dict | None]:
    """(the subscription, None) or (None, an error message) for a client's
    text frame, by spectrum.schema.json's subscribe. Out-of-range numbers
    are clamped to the caps, not refused (§2.4: caps the client cannot
    raise, so asking for more is not an error)."""
    if not isinstance(msg, dict) or msg.get("type") != "subscribe":
        return None, _bad("bad_message", _("Only subscribe messages are understood here."))
    stream = msg.get("stream")
    if stream not in STREAMS:
        return None, _bad("unknown_stream", _("There is no stream {name}; the streams are {names}.").format(
            name=repr(stream), names=", ".join(STREAMS)), stream if isinstance(stream, str) else None)

    def num(k, lo=0.0):
        v = msg.get(k)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo:
            raise ValueError(k)
        return v
    try:
        cols, fps, lo, hi = num("cols", 1), num("fps"), num("loHz"), num("hiHz")
        if cols is None or int(cols) != cols:
            raise ValueError("cols")
        if fps == 0:
            raise ValueError("fps")
    except ValueError as e:
        return None, _bad("bad_subscribe", _("{field} is missing or not a number this subscribe allows.").format(
            field=str(e)), stream)
    reduce = msg.get("reduce", "peak")
    depth = msg.get("depth", 8)
    if reduce not in ("peak", "mean") or depth not in (8, 16) or isinstance(depth, bool):
        return None, _bad("bad_subscribe", _("reduce is peak or mean, and depth 8 or 16."), stream)
    if lo is not None and hi is not None and hi <= lo:
        return None, _bad("bad_subscribe", _("hiHz must be above loHz."), stream)
    return {"stream": stream, "cols": min(int(cols), MAX_COLS), "fps": min(fps or MAX_FPS, MAX_FPS),
            "loHz": lo, "hiHz": hi, "reduce": reduce, "depth": depth}, None


class Session:
    """One api/spectrum/v1 socket. `overlay` is the app's overlay/1 source
    (overlay.Overlay), sent on the same socket (§3.1)."""

    def __init__(self, radio, sock, shared: Shared, overlay=None, clock=time.monotonic):
        self.radio, self.sock, self.shared, self.overlay, self.clock = radio, sock, shared, overlay, clock
        self.sp = shacklibs.spectrum()
        self.gone = threading.Event()
        self.inbox: queue.Queue = queue.Queue()
        self.cond = threading.Condition()
        self.out: deque = deque()               # (opcode, payload), in order
        self.inflight = False                   # the writer holds frames not yet on the socket
        self.lw = self.sp.LatestWins(self._enqueue_row)
        self.subs: dict[str, dict] = {}
        self.index: dict[str, int] = {}         # stream -> its index: order of stream messages here
        self.rev_sent: dict[str, int] = {}
        self.gen_seen: dict[str, int] = {}
        self.last_row_t: dict[str, float] = {}
        self.levels_at: dict[str, float] = {}
        # Flags owed to the next row that is actually written: a flagged
        # row replaced while pending must not lose them.
        self.owed: dict[str, set] = {s: set() for s in STREAMS}
        self.ov_rev = 0
        self.ov_sent: dict[str, dict] | None = None
        self.ov_range: tuple | None = None
        self.ov_at = 0.0

    # ------------------------------------------------------------ writing
    def _enqueue_row(self, _client, payload: bytes) -> None:
        # Called by LatestWins under self.cond. Byte 3 is the flags, 4-5
        # the stream index (CLIENT-UI-PLAN §2.3): what this row carries is
        # no longer owed.
        idx = payload[4] | (payload[5] << 8)
        stream = next((s for s, i in self.index.items() if i == idx), None)
        if stream is not None:
            if payload[3] & 0x02:
                self.owed[stream].discard("levels")
            if payload[3] & 0x04:
                self.owed[stream].discard("stream")
            if payload[3] & 0x08:
                self.owed[stream].discard("gap")
        self.out.append((0x2, payload))
        self.cond.notify()

    def _text(self, msg: dict) -> None:
        with self.cond:
            self.out.append((0x1, json.dumps(msg, separators=(",", ":")).encode()))
            self.cond.notify()

    def _writer(self) -> None:
        try:
            while not self.gone.is_set():
                with self.cond:
                    while not self.out and not self.gone.is_set():
                        self.cond.wait(0.5)
                    batch = list(self.out)
                    self.out.clear()
                    self.inflight = bool(batch)
                for op, data in batch:
                    if op == 0x2:
                        self.sock.send_binary(data)
                    else:
                        self.sock.send_text(data.decode())
                with self.cond:
                    if not self.out:
                        # Everything is on the socket: LatestWins may send
                        # what it kept back (which lands in self.out).
                        self.lw.drained(self)
                    self.inflight = bool(self.out)
        except (OSError, ConnectionError):
            pass
        self.gone.set()

    def _idle(self) -> bool:
        with self.cond:
            return not self.out and not self.inflight

    # ------------------------------------------------------------ reading
    def _reader(self) -> None:
        try:
            while True:
                fr = self.sock.recv()
                if fr is None:
                    break
                op, data = fr
                if op == 0x1:
                    try:
                        self.inbox.put(json.loads(data))
                    except ValueError:
                        self.inbox.put(None)
        except (OSError, ConnectionError):
            pass
        self.gone.set()

    # ------------------------------------------------------------ the loop
    def run(self) -> None:
        feeds = {s: self.radio.subscribe(k, FEED_DEPTH) for s, k in STREAMS.items()}
        threading.Thread(target=self._reader, daemon=True, name="spectrum-read").start()
        writer = threading.Thread(target=self._writer, daemon=True, name="spectrum-write")
        writer.start()
        try:
            # What is already known is described at once (§2.1: on connect).
            for s in STREAMS:
                if self.shared.streams[s]["desc"] is not None:
                    self._describe(s, self.shared.streams[s])
            dropped = {s: 0 for s in feeds}
            while not self.gone.wait(POLL_S):
                self._take_messages()
                for s, f in feeds.items():
                    # Every row, in order: the fps ceiling and LatestWins
                    # decide what goes, so a replaced one is a `gap`. Rows
                    # the feed itself dropped (this loop fell behind) are a
                    # gap too, owed to the next row written.
                    items = f.drain()
                    if f.dropped != dropped[s]:
                        dropped[s] = f.dropped
                        if s in self.subs:
                            with self.cond:
                                self.owed[s].add("gap")
                    for item in items:
                        self._row(s, item)
                self._overlay_tick()
        finally:
            for f in feeds.values():
                self.radio.unsubscribe(f)
            self.gone.set()
            with self.cond:
                self.cond.notify_all()
                self.lw.forget(self)
            writer.join(2.0)

    def _take_messages(self) -> None:
        while True:
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                return
            sub, err = parse_subscribe(msg)
            if err is not None:
                self._text(err)
                continue
            s = sub["stream"]
            self.subs[s] = sub
            # A new subscription quantises from now on: the client needs
            # this stream's window for its depth before the next row.
            self.gen_seen.pop(s, None)
            self.ov_range = None        # a snapshot comes on subscribe (§3.1)

    def _extra(self, stream: str) -> dict:
        st = self.radio.state()
        extra = {"rate": float(st.get("scopeFps") or MAX_FPS),
                 "label": _("Wide") if stream == "main" else _("Zoom")}
        span = st.get("span") or {}
        if stream == "main" and span.get("pinned"):
            extra["pinned"] = {"by": list(span.get("by") or [])}
        return extra

    def _describe(self, stream: str, s: dict) -> None:
        if stream not in self.index:
            self.index[stream] = len(self.index)
        self.rev_sent[stream] = s["desc"]["rev"]
        self._text(dict(s["desc"]))

    def _row(self, stream: str, item) -> None:
        s = self.shared.update(stream, item, self._extra(stream))
        if s["desc"] is None or s["window"] is None:
            return
        changed = self.rev_sent.get(stream) != s["desc"]["rev"]
        if changed:
            self._describe(stream, s)
            if stream in self.subs:
                self.owed[stream].add("stream")
        sub = self.subs.get(stream)
        if sub is None:
            return
        t = float(item[0])
        now = self.clock()
        win = s["window"]
        with self.cond:
            if self.gen_seen.get(stream) != s["gen"]:
                self.gen_seen[stream] = s["gen"]
                self.levels_at[stream] = now
                self.out.append((0x1, json.dumps(win.message(stream, sub["depth"]), separators=(",", ":")).encode()))
                self.owed[stream].add("levels")
        if now - self.levels_at.get(stream, 0.0) >= LEVELS_EVERY_S and self._idle():
            self.levels_at[stream] = now
            self._text(win.message(stream, sub["depth"]))
        # fps is a ceiling on capture time, with a little slack so a client
        # asking for the source's own rate gets every row despite jitter.
        last = self.last_row_t.get(stream)
        if last is not None and t - last < 0.9 / sub["fps"]:
            return
        self.last_row_t[stream] = t
        _t, start, bin_hz, db = item
        lo, col_hz, cols = self.sp.reduce(db, float(start), float(bin_hz), sub["cols"], sub["loHz"], sub["hiHz"],
                                          sub["reduce"])
        values = self.sp.quantise(cols, win.floor, win.step(sub["depth"]), sub["depth"])
        with self.cond:
            owed = self.owed[stream]
            row = self.sp.Row(self.index[stream], 0, int(t * 1000), float(lo), float(col_hz), values,
                              levels_changed="levels" in owed, stream_changed="stream" in owed,
                              gap="gap" in owed)
            self.lw.offer(self, row)

    # ------------------------------------------------------------ overlay/1
    def view_range(self) -> tuple[float, float] | None:
        """What this client has subscribed to see: the union over its
        streams of each crop, or the stream's whole span where it gave
        none. None before any subscribed stream is described."""
        lo = hi = None
        for s, sub in self.subs.items():
            d = self.shared.streams[s]["desc"]
            if d is None:
                continue
            a = max(sub["loHz"], d["loHz"]) if sub["loHz"] is not None else d["loHz"]
            b = min(sub["hiHz"], d["hiHz"]) if sub["hiHz"] is not None else d["hiHz"]
            lo = a if lo is None else min(lo, a)
            hi = b if hi is None else max(hi, b)
        return None if lo is None or hi <= lo else (lo, hi)

    def _overlay_tick(self) -> None:
        if self.overlay is None:
            return
        now = self.clock()
        if now - self.ov_at < self.overlay.EVERY_S and self.ov_range is not None:
            return
        rng = self.view_range()
        if rng is None:
            return
        self.ov_at = now
        items = {i["id"]: i for i in self.overlay.items(*rng)}
        if self.ov_range is None or self.ov_sent is None or not self._same_range(rng):
            self.ov_range = rng
            self.ov_sent = items
            self.ov_rev += 1
            self._text({"type": "overlay", "rev": self.ov_rev, "op": "snapshot", "items": list(items.values())})
            return
        up = [i for k, i in items.items() if self.ov_sent.get(k) != i]
        gone = [{"id": k} for k in self.ov_sent if k not in items]
        self.ov_sent = items
        if up:
            self.ov_rev += 1
            self._text({"type": "overlay", "rev": self.ov_rev, "op": "upsert", "items": up})
        if gone:
            self.ov_rev += 1
            self._text({"type": "overlay", "rev": self.ov_rev, "op": "remove", "items": gone})

    def _same_range(self, rng) -> bool:
        # Any change of the view is a new snapshot for the new range (with
        # its own margin); only changes inside one view are diffed.
        a, b = self.ov_range
        return abs(rng[0] - a) < 1e-3 and abs(rng[1] - b) < 1e-3
