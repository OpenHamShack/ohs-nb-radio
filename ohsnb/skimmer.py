"""The band skimmer, run in the background (ohsnb/dsp/skim.py does the work).

Every signal on the transponder, listed and named while the radio runs,
whatever the dial is tuned to: SSB voices with their dial measured by
auto-tune, CW, carriers and data signals, the beacons, the FT8/FT4/Q65/
JS8 calling windows (with the calls the operator's own decoder has heard
there, when it is running), and the signals docs/qo100-unidentified-
signals.md names. Built the way the beacons' receivers are (beaconrx.py,
beacontext.py): the receive thread only hands each block's spectra - the
bank's, by reference, no copy - and where the transponder sits in them to a
queue; a worker thread does everything else, publishes the list on the
"skim" feed once a second and keeps the skim* status keys. A slow worker
drops blocks (skimDropped); it never holds up receive.

Its CPU is a budget, skimBudget per cent of one core: the worker charges
what it uses against the signal it has heard, and the costly part - a look
at a voice to measure its dial - waits while the account is spent. A slow
machine gets fewer looks a minute, not a slower receiver (skim.py).

    sk = BandSkimmer(radio); sk.start()
    sk.feed(X, starts)            # on the receive thread, once per block
    sk.heard(ev)                  # a decoder event (Radio._emit_event)
    sk.stop()
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time

from . import bandplan
from .dsp import skim

log = logging.getLogger("ohsnb.skimmer")

QUEUE_BLOCKS = 64              # ~3 s of receive blocks before any are dropped
PUBLISH_S = 1.0                # the list, this often (signal seconds)
CALLS_S = 120.0                # a call decoded in a calling window is shown this long


class BandSkimmer:
    def __init__(self, radio):
        self.radio = radio
        self.core = skim.Skimmer(radio.geo, budget=float(radio.st["skimBudget"]) / 100.0)
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.dropped = 0
        self.calls: collections.deque = collections.deque(maxlen=400)   # (t, f, call, mode)
        self.next_pub = 0.0

    # -- receive thread ------------------------------------------------------
    def feed(self, X, starts) -> None:
        try:
            self.q.put_nowait((X, starts, self.radio._off(bandplan.DL_LO)))
        except queue.Full:
            self.dropped += 1

    def set_budget(self, pct: float) -> None:
        self.core.budget = float(pct) / 100.0

    # -- the decode thread ---------------------------------------------------
    def heard(self, ev: dict) -> None:
        """A decoder event: an FT8/FT4/Q65/JS8 decode with a call is put on
        the calling window it was heard in (deque.append is atomic)."""
        call = ev.get("call")
        if not call or "df" not in ev or ev.get("mode") not in ("ft8", "ft4", "q65", "js8"):
            return
        try:
            f = float(ev["dial"]) + float(ev["df"])
        except (KeyError, TypeError, ValueError):
            return
        self.calls.append((float(ev.get("t") or time.time()), f, str(call), ev["mode"]))

    # -- worker ----------------------------------------------------------------
    def start(self) -> None:
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=f"{self.radio.THREAD_PREFIX}-skim", daemon=True)
        self.thread.start()
        self.radio._status(skimState="running", skimSignals=0, skimExact=0, skimCpu=0.0, skimLevel=0,
                           skimLooks=0.0, skimDropped=0)

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None
        self.radio._status(skimState="off")
        self.radio._publish("skim", {"t": time.time(), "entries": []})

    def _loop(self) -> None:
        while not self.stop_ev.is_set():
            item = self.q.get()
            if item is None:
                break
            X, starts, base = item
            try:
                self.core.push(X, starts, base)
            except Exception:  # noqa: BLE001 - the skimmer must never take the radio with it
                log.exception("band skimmer failed")
                self.radio._status(skimState="error")
                return
            if self.core.t >= self.next_pub:
                self.next_pub = self.core.t + PUBLISH_S
                self._publish()

    def _publish(self) -> None:
        core = self.core
        now = time.time()
        entries = core.entries(wall=now)
        recent = [c for c in list(self.calls) if now - c[0] <= CALLS_S]
        for e in entries:
            if e["kind"] == "digital":
                # Newest first, each call once.
                seen, calls = set(), []
                for _t, f, call, _mode in reversed(recent):
                    if e["lo"] <= f <= e["hi"] and call not in seen:
                        seen.add(call)
                        calls.append(call)
                e["calls"] = calls[:12]
        self.radio._publish("skim", {"t": now, "entries": entries})
        active = [e for e in entries if e["active"]]
        self.radio._status(skimSignals=len(active), skimExact=sum(1 for e in active if e["kind"] == "ssb" and e["exact"]),
                           skimCpu=round(100.0 * core.cpu(), 2), skimLevel=core.level,
                           skimLooks=core.looks_per_minute(), skimDropped=self.dropped)


__all__ = ["BandSkimmer"]
