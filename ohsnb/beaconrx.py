"""The multimedia beacon, received in the background (docs/hsmodem-research.md).

AMSAT-DL's High-Speed Multimedia Beacon sits at 10489.995 MHz, inside the
500 kHz the receiver always covers, so it is decoded from the wideband IQ
through a channel of its own - whatever the dial is tuned to and whatever
the mode. The receive thread only cuts the channel (one small inverse FFT
a frame, from the spectrum every channel shares) and hands it to a queue;
a worker thread runs ohsdigi's HSmodem receiver on it (Rust, the GIL
released) and the content layer (ohscore/modes/hsmodem.py), publishes
what arrives on the "mmb" feed, and keeps the mmb* status keys. A slow
worker drops channel blocks; it never holds up receive.

Received files go to <data folder>/mmbeacon/.

    rx = BeaconRx(radio); rx.start()
    rx.feed(X, starts)            # on the receive thread, once per block
    rx.stop()
"""
from __future__ import annotations

import logging
import queue
import threading
import time

import numpy as np

from ohscore.dsp.bank import Channel
from ohscore.modes import hsmodem

from . import bandplan

log = logging.getLogger("ohsnb.beaconrx")

DL = bandplan.BEACONS["mm"]["dl"]
CHANNEL_RATE = 12_000.0        # what the channel asks for; the receiver resamples to 9600
CUTOFF = 2_400.0               # the beacon is +-1.44 kHz; the rest is room for the frequency search
QUEUE_BLOCKS = 64              # ~1.5 s of channel blocks before any are dropped
# A receive correction that jumps (beacon lock arriving, click-to-lock, a
# hand-set rxCorr) moves the beacon inside its channel at once by that much;
# the HSmodem loops follow ~20 Hz, so beyond this they start again.
RETUNE_HZ = 40.0
RESET = object()               # the worker's cue to start acquiring again


class BeaconRx:
    def __init__(self, radio):
        self.radio = radio
        geo = radio.geo
        self.ch = Channel(geo, geo.decimation_for(CHANNEL_RATE), cutoff=CUTOFF)
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.rx: hsmodem.BeaconReceiver | None = None
        self.dropped = 0
        self.cpu = 0.0            # worker CPU, as a fraction of one core
        self.corr_ref = float(radio.st["rxCorr"])

    # -- receive thread ------------------------------------------------------
    def feed(self, X, starts) -> None:
        # Small changes of rxCorr (beacon lock following the LNB, a few
        # hertz at a time) the carrier loop follows; a jump restarts it.
        corr = float(self.radio.st["rxCorr"])
        if abs(corr - self.corr_ref) > RETUNE_HZ:
            self.corr_ref = corr
            try:
                self.q.put_nowait(RESET)
            except queue.Full:
                pass
        self.ch.set_freq(self.radio._off(DL))
        y = self.ch.take(X, starts)
        if not len(y):
            return
        try:
            self.q.put_nowait(y)
        except queue.Full:
            self.dropped += 1

    # -- worker ----------------------------------------------------------------
    def start(self) -> None:
        folder = self.radio.data_dir / "mmbeacon"
        self.rx = hsmodem.BeaconReceiver(self.ch.rate, self._event, folder)
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=f"{self.radio.THREAD_PREFIX}-mmbeacon", daemon=True)
        self.thread.start()
        self.radio._status(mmbState="searching")

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None
        self.radio._status(mmbState="off")

    def _loop(self) -> None:
        signal_s = 0.0
        t_cpu = 0.0
        while not self.stop_ev.is_set():
            y = self.q.get()
            if y is None:
                break
            if y is RESET:
                self.rx.rx.reset()
                continue
            t0 = time.thread_time()
            try:
                self.rx.feed_iq(y)
            except Exception:  # noqa: BLE001 - the beacon must never take the radio with it
                log.exception("multimedia beacon receiver failed")
                self.radio._status(mmbState="error")
                return
            t_cpu += time.thread_time() - t0
            signal_s += len(y) / self.ch.rate
            if signal_s >= 1.0:
                self.cpu = t_cpu / signal_s
                signal_s = t_cpu = 0.0

    def _event(self, ev: dict) -> None:
        kind = ev.get("kind")
        if kind == "stats":
            st = "receiving" if ev["sync"] else "searching"
            self.radio._status(mmbState=st, mmbMer=float(ev["mer"]), mmbFrames=int(ev["ok"]),
                               mmbLost=int(ev["failed"]), mmbLast=float(ev["last"]), mmbFreq=float(ev["freq"]),
                               mmbCpu=round(100.0 * self.cpu, 2))
        elif kind == "frame":
            return              # counted in the stats; not news for the UI
        if kind in ("image", "bulletin", "file"):
            log.info("multimedia beacon: received %s (%d bytes)%s", ev.get("name"), len(ev.get("data", b"")),
                     f" -> {ev['path']}" if ev.get("path") else "")
        ev = dict(ev)
        ev["t"] = time.time()
        if isinstance(ev.get("values"), np.ndarray):
            ev["values"] = ev["values"].astype(np.uint8)
        self.radio._publish("mmb", ev)
