"""KG-STV pictures, received in the background (ohscore/dsp/kgstv.py).

KG-STV is the digital picture mode QO-100's stations use at 10489.6249 MHz
USB: a 320x240 picture in about two minutes, one 16x16 block a frame, so a
picture builds wherever reception starts. Built the way the middle
beacon's text receiver is (beacontext.py): the receive thread cuts a
12 kHz channel at the tones' centre - where rxCorr says it is, so the
decoder only follows the sender's own error, and is told of each step
rxCorr takes - and hands it to a queue; a worker thread demodulates it,
puts pictures together, publishes them on the "kgstv" feed and keeps the
kgstv* status keys. A slow worker drops channel blocks; it never holds up
receive.

A finished picture (the sender's end frame, or 30 s with nothing) with at
least SAVE_BLOCKS blocks is saved as <data folder>/kgstv/<UTC>_<call>.png -
what KG-STV itself does, from its default of 50.

    rx = KgStvRx(radio); rx.start()
    rx.feed(X, starts)            # on the receive thread, once per block
    rx.stop()
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from pathlib import Path

import numpy as np

from ohscore.dsp.bank import Channel
from ohscore.modes.sstv import _write_png

from ohscore.dsp import kgstv

log = logging.getLogger("ohsnb.kgstvrx")

DIAL = 10_489_624_900.0        # USB dial where it is heard (07/10: VU2SAA, DL4CQ, DG8RP)
DL = DIAL + kgstv.CENTRE_HZ    # the tones' centre: 1200-1800 Hz audio
CHANNEL_RATE = 12_000.0        # 10 samples a bit at 1.2 MS/s and 600 kS/s alike
# The tones are +-300 Hz of the centre; the channel is wider so that a
# sender a few hundred hertz off is still in it, and no wider, because the
# discriminator takes all the noise it is given: on the 07/10 recording's
# four pictures 0.9 kHz decoded 1189 blocks of 1200, 1.2 and 1.5 kHz 1192,
# and the whole 12 kHz channel 858.
CUTOFF = 1_200.0
QUEUE_BLOCKS = 128             # ~2.5 s of channel blocks before any are dropped
RETUNE_HZ = 300.0              # a bigger rxCorr step (a typed one, a first fix) starts the receiver afresh
RECEIVING_S = 30.0             # "receiving" while a frame decoded this recently
SAVE_BLOCKS = 50
RESET = object()


def file_name(call: str, t: float) -> str:
    """<UTC>_<call>.png, the callsign made safe for any file system."""
    safe = re.sub(r"[^A-Za-z0-9-]+", "-", call.strip()).strip("-")[:24] or "no-call"
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime(t)) + f"_{safe}.png"


class KgStvRx:
    def __init__(self, radio):
        self.radio = radio
        geo = radio.geo
        self.ch = Channel(geo, geo.decimation_for(CHANNEL_RATE), cutoff=CUTOFF)
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.rx: kgstv.Receiver | None = None
        self.pics = kgstv.Pictures()
        self.dropped = 0
        self.last = 0.0
        self.last_status = 0.0
        self.started = False
        self.wall0: dict[int, float] = {}       # picture id -> when it started (Unix time)
        self.utc = time.time()                   # when the latest channel block was on the air
        self.folder = radio.data_dir / "kgstv"

    # -- receive thread ------------------------------------------------------
    def feed(self, X, starts) -> None:
        f = self.radio._off(DL)
        step = f - self.ch.freq
        if step:
            self.ch.set_freq(f)
            if self.started:
                try:
                    self.q.put_nowait(RESET if abs(step) > RETUNE_HZ else ("retune", step))
                except queue.Full:
                    self.dropped += 1
        self.started = True
        y = self.ch.take(X, starts)
        if not len(y):
            return
        try:
            self.q.put_nowait((y, self._utc()))
        except queue.Full:
            self.dropped += 1

    def _utc(self) -> float:
        """When the block just taken was on the air: a recording being played
        keeps its own clock, and its pictures belong to when they were sent
        (and are named so); a simulator faster than real time has its own.
        The engine's rule (Engine._audio_utc), without its epoch-following,
        which is the audio path's state, not this one's."""
        r = self.radio
        dev = r.dev
        if getattr(dev, "own_clock", False):
            return float(dev.utc_end)
        if getattr(dev, "realtime", True) is False and hasattr(dev, "t_epoch"):
            return float(dev.t_epoch + r.rx_samples / r.geo.fs)
        return time.time()

    # -- worker ----------------------------------------------------------------
    def start(self) -> None:
        self.rx = kgstv.Receiver(self.ch.rate)
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=f"{self.radio.THREAD_PREFIX}-kgstv", daemon=True)
        self.thread.start()
        self.radio._status(kgstvState="listening", kgstvFrames=0, kgstvLost=0, kgstvFreq=0.0)

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None
        # A picture still coming in when the radio stops is kept, as KG-STV
        # keeps one it timed out.
        if self.rx is not None:
            for ev in self.pics.tick(float("inf")):
                self._picture(ev)
        self.radio._status(kgstvState="off")

    def _loop(self) -> None:
        while not self.stop_ev.is_set():
            y = self.q.get()
            if y is None:
                break
            if y is RESET:
                self.rx.reset()
                continue
            if isinstance(y[0], str):           # ("retune", step)
                self.rx.retune(y[1])
                continue
            y, self.utc = y
            try:
                events = self.rx.feed(y)
                changes = []
                for ev in events:
                    changes += self.pics.frame(ev)
                changes += self.pics.tick(self.rx.samples / self.rx.rate)
            except Exception:  # noqa: BLE001 - a picture decoder must never take the radio with it
                log.exception("KG-STV receiver failed")
                self.radio._status(kgstvState="error")
                return
            if any(ev["kind"] == "frame" for ev in events):
                self.last = self.utc
            for ch in changes:
                self._picture(ch)
            now = time.monotonic()
            if events or now - self.last_status >= 1.0:
                self.last_status = now
                self._stats()

    def _stats(self) -> None:
        rx = self.rx
        st = "receiving" if self.last and self.utc - self.last < RECEIVING_S else "listening"
        self.radio._status(kgstvState=st, kgstvFrames=rx.frames, kgstvLost=rx.lost, kgstvLast=self.last,
                           kgstvFreq=round(rx.freq, 1) if st == "receiving" else 0.0,
                           kgstvCall=self.pics.call)

    def _picture(self, ev: dict) -> None:
        k = ev["kind"]
        now = self.utc
        if k == "start":
            self.wall0[ev["id"]] = now
            self.radio._publish("kgstv", {"kind": "start", "id": ev["id"], "call": ev["call"], "t": now})
        elif k == "block":
            self.radio._publish("kgstv", {"kind": "block", "id": ev["id"], "x": ev["x"], "y": ev["y"],
                                          "rgb": np.ascontiguousarray(ev["rgb"]).tobytes(), "call": ev["call"],
                                          "blocks": ev["blocks"], "mode": ev["mode"], "t": now})
        elif k == "done":
            t0 = self.wall0.pop(ev["id"], now)
            path = self._save(ev, t0) if ev["blocks"] >= SAVE_BLOCKS else ""
            self.radio._publish("kgstv", {"kind": "done", "id": ev["id"], "call": ev["call"], "why": ev["why"],
                                          "blocks": ev["blocks"], "bad": ev["bad"], "mode": ev["mode"],
                                          "path": path, "t": now})
            log.info("KG-STV picture from %s: %d blocks (%s)%s", ev["call"] or "no callsign", ev["blocks"],
                     ev["why"], f", saved {path}" if path else "")
        elif k == "call":
            self.radio._publish("kgstv", {"kind": "call", "call": ev["call"], "t": now})
        elif k == "text":
            self.radio._publish("kgstv", {"kind": "text", "text": ev["text"], "call": ev["call"], "t": now})

    def _save(self, ev: dict, t0: float) -> str:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            p = self.folder / file_name(ev["call"], t0)
            _write_png(p, ev["rgb"])
            return str(p)
        except OSError as e:
            log.warning("KG-STV: could not save a picture: %s", e)
            return ""


def saved_pictures(folder, limit: int = 60) -> list[tuple[str, float]]:
    """What earlier sessions kept, newest first: [(path, mtime)]."""
    p = Path(folder)
    if not p.is_dir():
        return []
    out = []
    for f in p.glob("*.png"):
        try:
            out.append((str(f), f.stat().st_mtime))
        except OSError:
            continue
    out.sort(key=lambda x: -x[1])
    return out[:limit]


__all__ = ["KgStvRx", "saved_pictures", "file_name", "DIAL", "DL"]
