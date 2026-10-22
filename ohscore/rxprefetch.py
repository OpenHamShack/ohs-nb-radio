"""The receive device read on a thread of its own, ahead of the DSP.

Why (17/10/2026, NB on an M4 Mac mini, a Pluto over Tailscale): every
window resize, theme toggle and dialog opened counted a receive overrun.
The cause is the GIL, not the DSP's cost. The receive thread used to
read the device and process the block itself, and while the window does a
second of Python work (a theme change rebuilds the whole window: 1.4-2.4 s
measured on ohs-dev with tools/rx_storm.py), a thread doing hundreds of
numpy calls per block gets a small share of the interpreter. Blocks then
take several times their length to process, nothing calls the Pluto's
refill() meanwhile, and once its four kernel buffers (300 ms) are full the
hardware loses samples: 0.45 s in one theme toggle there. PyQt6 holds the
GIL across each Qt call, so no switch interval fixes this (1 ms instead of
5 changed nothing measurable).

So the device is read here instead: a loop that does little more than
read() - which spends its time in the driver with the GIL released - and
appends each block to a queue of `depth_s` seconds. A starved DSP thread
now falls behind and catches up, the queue absorbing the difference, and
the device is still drained on time. When the queue is full anyway (the
DSP thread more than `depth_s` behind) the *oldest* block is dropped,
counted, and its length handed to the next as a gap: receive stays near
the present, as the feeds do (DESIGN.md "A Feed is a bounded, drop-oldest
queue"). In steady state the queue is empty, so this adds no latency.

It also tells, which nobody could before, when samples went missing
before they ever reached the program - a network link to the radio that
stalled, an overloaded USB bus. The radio's sample clock is the reference:
`lag` is how much later than its sample count says a block arrives. Jitter
moves it up and down; buffering upstream (kernel buffers, a TCP socket)
lets it rise for a while and come back; only samples lost upstream raise it
*for good*, since a radio never delivers faster than its rate. The minimum
of `lag` over the last `window_s` (longer than any buffering upstream can
hold) rising more than `tolerance_s` above the baseline is therefore a loss
of that much, and the next block carries it as its gap. The gap's place is
known to within `window_s`, its length to within the jitter. Slow drift
between the radio's crystal and the computer's clock (20 ppm is 72 ms an
hour) is followed rather than mistaken for loss.

Each block comes with the UTC of its first sample (`utc`), from the same
clock: where the radio's sample count, plus what was lost, puts it, at the
link's own delay. Not the time the DSP got round to it - a recording made
from a queue that has fallen behind would see time jump and mark a gap that
is not there (ohscore/sigmf.py, GAP_S) - and not each block's arrival
either, whose jitter and upstream stalls would mark one twice.

Only for devices that set `rx_prefetch` (a Pluto, a SoapySDR radio, the
simulator in real time): the faster-than-real-time simulator the tests use
has no deadline to protect and keeps its lock-step with transmit; a file
keeps its own clock; the Hermes-Lite 2 already reads on its own thread.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque


class Prefetch:
    def __init__(self, dev, n: int, fs: float, depth_s: float = 2.0, window_s: float = 3.0,
                 tolerance_s: float = 0.2, name: str = "rxread"):
        self.dev, self.n, self.fs = dev, int(n), float(fs)
        self.cap = max(2, int(math.ceil(depth_s * self.fs / self.n)))
        self.window = max(2, int(math.ceil(window_s * self.fs / self.n)))
        self.tolerance = float(tolerance_s)
        self.cond = threading.Condition()
        self.q: deque = deque()          # [block, utc, gap_samples]
        self.error: BaseException | None = None
        self.stopping = False
        # Samples lost, by where: the queue (the DSP thread fell more than
        # depth_s behind) or upstream (they never arrived).
        self.queue_lost = 0
        self.stream_lost = 0
        self.loss_events = 0
        self.max_behind = 0              # most blocks ever waiting
        # The block read() returned last: when it arrived, and the samples
        # missing just before it.
        self.utc: float | None = None
        self.gap = 0
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> "Prefetch":
        self.thread.start()
        return self

    def stop(self) -> None:
        with self.cond:
            self.stopping = True
            self.cond.notify_all()

    @property
    def lost(self) -> int:
        return self.queue_lost + self.stream_lost

    @property
    def behind_s(self) -> float:
        """Seconds of samples read from the device and not yet processed."""
        with self.cond:
            return sum(len(it[0]) for it in self.q) / self.fs

    # ------------------------------------------------------------ the reader
    def _run(self) -> None:
        t0 = None
        total = 0                        # samples the radio produced: read, plus lost upstream
        base = None                      # the lowest lag seen: the link's own delay
        recent: deque = deque(maxlen=self.window)
        while not self.stopping:
            try:
                x = self.dev.read(self.n)
            except BaseException as e:  # noqa: BLE001 - handed to the DSP thread, which reconnects
                with self.cond:
                    self.error = e
                    self.cond.notify_all()
                return
            now = time.monotonic()
            if t0 is None:
                t0 = now - len(x) / self.fs
                to_utc = time.time() - now
            total += len(x)
            lag = now - t0 - total / self.fs
            recent.append(lag)
            if base is None or lag < base:
                base = lag
            gap = 0
            if len(recent) == recent.maxlen:
                low = min(recent)
                rise = low - base
                if rise > self.tolerance:
                    gap = int(round(rise * self.fs))
                    total += gap
                    recent = deque((v - rise for v in recent), maxlen=self.window)
                    self.stream_lost += gap
                    self.loss_events += 1
                elif rise > 0:
                    # Clock drift, a few microseconds a second: followed.
                    base += 0.01 * rise
            utc = to_utc + t0 + base + (total - len(x)) / self.fs
            with self.cond:
                if len(self.q) >= self.cap:
                    old = self.q.popleft()
                    lost = len(old[0]) + old[2]
                    self.queue_lost += len(old[0])
                    self.loss_events += 1
                    if self.q:
                        self.q[0][2] += lost
                    else:
                        gap += lost
                self.q.append([x, utc, gap])
                self.max_behind = max(self.max_behind, len(self.q))
                self.cond.notify()

    # ------------------------------------------------------------ the DSP thread
    def read(self, timeout: float = 0.5):
        """The next block, or None after `timeout` with nothing to give
        (the caller checks its stop flag and asks again). Raises what the
        device raised, once the blocks read before it are used up."""
        with self.cond:
            if not self.q and self.error is None and not self.stopping:
                self.cond.wait(timeout)
            if self.q:
                x, self.utc, self.gap = self.q.popleft()
                return x
            if self.error is not None:
                raise self.error
            return None
