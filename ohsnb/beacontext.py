"""The middle beacon's text, received in the background (ohsnb/dsp/ao40.py).

The middle beacon (10489.750 MHz) is what beacon lock follows by default,
and it is also a 400 bit/s text beacon: AO-40 blocks "K", "L", "M", "N" of
eight 64-character lines from DK0SB, one about every 25 s, each block
coming round every ~100 s. Built the way the multimedia beacon's receiver
is (beaconrx.py): the receive thread cuts a 4 kHz channel at the beacon -
where beacon lock's rxCorr says it is, so the decoder only has the last few
hertz to find, and is told of each step rxCorr takes so that it never sees
one - and hands it to a queue; a worker thread demodulates it,
publishes each block on the "midtext" feed and keeps the midText* status
keys. A slow worker drops channel blocks; it never holds up receive.

The latest block of each type is kept in <data folder>/midbeacon/<type>.txt,
so the view has something to show before the next one comes round.

    rx = BeaconText(radio); rx.start()
    rx.feed(X, starts)            # on the receive thread, once per block
    rx.stop()
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from ohscore.dsp.bank import Channel

from . import bandplan
from .dsp import ao40

log = logging.getLogger("ohsnb.beacontext")

DL = bandplan.BEACONS["middle"]["dl"]
CHANNEL_RATE = 4_000.0         # 10 samples a bit; offered at 1.2 MS/s and 600 kS/s alike
CUTOFF = 1_200.0               # the beacon is +-~800 Hz (Manchester at 400 bit/s, low-passed at 560 Hz)
QUEUE_BLOCKS = 128             # ~2 s of channel blocks before any are dropped
# The channel follows rxCorr, as every channel does, and the decoder is
# told each step so that it takes it out of its own mixer (ao40.Receiver.
# retune). Only a jump this big - click-to-lock, a typed rxCorr, beacon
# lock's first fix - starts its carrier search again instead.
RETUNE_HZ = 300.0
RECEIVING_S = 60.0             # "receiving" while a block decoded this recently; "tracking" otherwise
RESET = object()


class BeaconText:
    def __init__(self, radio):
        self.radio = radio
        geo = radio.geo
        self.ch = Channel(geo, geo.decimation_for(CHANNEL_RATE), cutoff=CUTOFF)
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.rx: ao40.Receiver | None = None
        self.dropped = 0
        self.last = 0.0
        self.last_status = 0.0
        self.started = False             # the channel's first frequency is no step
        self.folder = radio.data_dir / "midbeacon"

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
            self.q.put_nowait(y)
        except queue.Full:
            self.dropped += 1

    # -- worker ----------------------------------------------------------------
    def start(self) -> None:
        self.rx = ao40.Receiver(self.ch.rate)
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=f"{self.radio.THREAD_PREFIX}-midtext", daemon=True)
        self.thread.start()
        self.radio._status(midTextState="searching", midTextFrames=0, midTextLost=0, midTextSnr=0.0,
                           midTextFreq=0.0)

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None
        self.radio._status(midTextState="off")

    def _loop(self) -> None:
        while not self.stop_ev.is_set():
            y = self.q.get()
            if y is None:
                break
            if y is RESET:
                self.rx.reset()
                continue
            if isinstance(y, tuple):
                self.rx.retune(y[1])
                continue
            try:
                events = self.rx.feed(y)
            except Exception:  # noqa: BLE001 - the beacon must never take the radio with it
                log.exception("middle beacon text receiver failed")
                self.radio._status(midTextState="error")
                return
            for ev in events:
                if ev["kind"] == "frame":
                    self._frame(ev)
            now = time.monotonic()
            if events or now - self.last_status >= 1.0:
                self.last_status = now
                self._stats()

    def _stats(self) -> None:
        rx = self.rx
        if rx.state == "searching":
            st = "searching"
        else:
            st = "receiving" if self.last and time.time() - self.last < RECEIVING_S else "tracking"
        self.radio._status(midTextState=st, midTextSnr=round(rx.snr_db, 1) if rx.state != "searching" else 0.0,
                           midTextFrames=rx.frames, midTextLost=rx.failed, midTextLast=self.last,
                           midTextFreq=round(rx.freq, 1) if rx.state != "searching" else 0.0)

    def _frame(self, ev: dict) -> None:
        self.last = time.time()
        out = {k: ev[k] for k in ("type", "lines", "text", "highlight", "repaired", "snr")}
        out["t"] = self.last
        self.radio._publish("midtext", out)
        if ev["repaired"]:
            log.info("middle beacon: block %s decoded after repairing one symbol", ev["type"])
        self._save(ev["type"], ev["text"])

    def _save(self, kind: str, text: str) -> None:
        if not kind.isalnum():
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / f"{kind}.txt").write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            log.warning("middle beacon: could not save block %s: %s", kind, e)


def saved_blocks(folder) -> dict[str, tuple[str, float]]:
    """What earlier sessions kept: {type: (text, mtime)}."""
    from pathlib import Path
    out = {}
    p = Path(folder)
    if not p.is_dir():
        return out
    for f in sorted(p.glob("*.txt")):
        try:
            out[f.stem] = (f.read_text(encoding="utf-8").rstrip("\n"), f.stat().st_mtime)
        except OSError:
            continue
    return out


__all__ = ["BeaconText", "saved_blocks", "DL"]
