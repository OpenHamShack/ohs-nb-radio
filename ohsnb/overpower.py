"""The over-power and LEILA watch, run in the background (ohsnb/dsp/overpower.py
does the judging).

While the radio runs, every signal on the transponder with more power than
the middle beacon (AMSAT-DL's licence condition), and every sounding of
AMSAT-DL's LEILA siren, which marks one: when, where, by how much, and the
callsign when the operator's own decoder heard exactly one station there.
Built the way the band skimmer is (skimmer.py): the receive thread hands
each block - the wideband samples and the bank's spectra, by reference -
to a queue; a worker thread does the rest, publishes the list on the
"overpower" feed and keeps the op* status keys. A slow worker drops blocks
(opDropped); it never holds up receive.

Evidence capture (`leilaCapture`, off by default): while it is on, the
worker keeps the last CAPTURE_S of receive IQ in a ring, as ci16 (4 bytes a
sample: 96 MB at 1.2 MS/s, CAPTURE_MAX_BYTES at most), and saves it as a
SigMF recording when a siren ends - its whole over and the siren after it -
or when the operator asks (capture_now: "I heard one and nothing fired").
Nothing is kept while it is off. Receive only: nothing here keys.

    w = OverpowerWatch(radio); w.start()
    w.feed(x, X, starts)       # on the receive thread, once per block
    w.heard(ev)                # a decoder event (Radio._emit_event)
    w.view()                   # the list and state (the server's api/overpower)
    w.stop()
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time

import numpy as np

from ohscore import sigmf
from ohscore.i18n.text import _

from .dsp import overpower

log = logging.getLogger("ohsnb.overpower")

QUEUE_BLOCKS = 48              # ~3.6 s of receive blocks before any are dropped
PUBLISH_S = 1.0                # the list at least this often while anything is active
CALLS_S = 120.0                # decodes kept for naming a station
CALL_SLOT_S = 20.0             # a siren names the station decoded in the slot before it
CAPTURE_S = 20.0               # seconds of IQ the evidence ring holds ...
CAPTURE_MAX_BYTES = 100_000_000    # ... and never more than this
CAPTURE_WAIT_S = 10.0          # a siren still sounding this long after it was found is saved anyway


class OverpowerWatch:
    def __init__(self, radio):
        self.radio = radio
        self.det = overpower.Detector(radio.geo)
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self.dropped = 0
        self.calls: collections.deque = collections.deque(maxlen=400)   # (t, f, call)
        self.list: list[dict] = []
        self.next_pub = 0.0
        self.cpu = 0.0
        self.cpu_t0 = (time.monotonic(), 0.0)
        # Evidence capture: the ring (bytes, centre, utc, rxCorr) while
        # leilaCapture is on; the sirens already saved; the one waiting to
        # end; and a save the operator asked for.
        self.ring: collections.deque = collections.deque()
        self.ring_bytes = 0
        self.saved: set[int] = set()
        self.saved_names: dict[int, str] = {}
        self.pending: tuple[int, float] | None = None
        self.want_now = False
        self.last_capture = ""

    # -- receive thread ------------------------------------------------------
    def feed(self, x, X, starts) -> None:
        r = self.radio
        s = r.st
        beacon_ok = s["rxLock"] == "locked" or s["beaconMode"] != "auto"
        item = (x, X, starts, r._dial_at(0.0), time.time(), beacon_ok, r._rec_centre(), float(s["rxCorr"]),
                bool(s["leilaCapture"]))
        try:
            self.q.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    # -- the decode thread ---------------------------------------------------
    def heard(self, ev: dict) -> None:
        call = ev.get("call")
        if not call or "df" not in ev:
            return
        try:
            f = float(ev["dial"]) + float(ev["df"])
        except (KeyError, TypeError, ValueError):
            return
        self.calls.append((float(ev.get("t") or time.time()), f, str(call)))

    # -- any thread ----------------------------------------------------------
    def view(self) -> dict:
        with self.lock:
            events = [dict(e) for e in self.list]
        st = self.radio.st
        return {"state": st.get("opState", "off"), "beacon": st.get("opBeacon", ""),
                "marginDb": overpower.MARGIN_DB, "capture": bool(st.get("leilaCapture")),
                "lastCapture": self.last_capture, "events": events}

    def capture_now(self) -> None:
        """Save the ring now (the operator heard a siren). Raises ValueError
        with a sentence when there is nothing to save."""
        if not self.radio.st.get("leilaCapture"):
            raise ValueError(_("Turn on LEILA evidence capture first: nothing is kept until it is on"))
        if not self.ring:
            raise ValueError(_("Nothing has been kept yet: capture has only just been turned on"))
        self.want_now = True

    # -- worker ----------------------------------------------------------------
    def start(self) -> None:
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=f"{self.radio.THREAD_PREFIX}-overpower", daemon=True)
        self.thread.start()
        self.radio._status(opState="running", opActive=0, opLeila=0, opCpu=0.0, opDropped=0, opBeacon="")
        self.radio._publish("overpower", {"t": time.time(), "events": [], "beacon": ""})

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.thread = None
        self.ring.clear()
        self.ring_bytes = 0
        self.radio._status(opState="off", opActive=0)
        self.radio._publish("overpower", {"t": time.time(), "events": []})

    def _loop(self) -> None:
        while not self.stop_ev.is_set():
            item = self.q.get()
            if item is None:
                break
            # Whatever else is waiting goes in with it: the spectral lines'
            # Scope copies its whole buffer on every call, so one call per
            # batch, not per 75 ms block.
            batch = [item]
            while len(batch) < QUEUE_BLOCKS:
                try:
                    nxt = self.q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    self.stop_ev.set()
                    break
                batch.append(nxt)
            c0 = time.thread_time()
            try:
                changed = self._take(batch)
            except Exception:  # noqa: BLE001 - the watch must never take the radio with it
                log.exception("over-power watch failed")
                self.radio._status(opState="error")
                return
            self.cpu += time.thread_time() - c0
            now = time.time()
            if changed or (now >= self.next_pub and any(e["active"] for e in self.list)):
                self._publish(now)
            elif now >= self.next_pub:
                self._status(now)
            self._capture(now)

    def _take(self, batch: list) -> bool:
        d = self.det
        x = batch[0][0] if len(batch) == 1 else np.concatenate([b[0] for b in batch])
        _x, _X, _s, base, wall, beacon_ok, _c, _corr, _cap = batch[-1]
        changed = d.lines(x, base, beacon_ok, wall)
        for _x, X, starts, base, *_rest in batch:
            changed |= d.spectra(X, starts, base)
        for b in batch:
            if b[8]:
                self._keep(b)
            elif self.ring:
                self.ring.clear()
                self.ring_bytes = 0
        return changed

    # -- the list --------------------------------------------------------------
    def _named(self, e: dict) -> str | None:
        """The callsign the operator's decoder heard there, when exactly one:
        during an over-power event; in the slot before a siren (LEILA
        sounds after the over)."""
        if e["kind"] == "leila":
            t0, t1 = e["start"] - CALL_SLOT_S, e["start"]
        else:
            t0, t1 = e["start"] - 15.0, e["end"] + 15.0
        lo, hi = e["lo"] - 25.0, e["hi"] + 25.0
        calls = {c for t, f, c in list(self.calls) if t0 <= t <= t1 and lo <= f <= hi}
        return calls.pop() if len(calls) == 1 else None

    def _publish(self, now: float) -> None:
        self.next_pub = now + PUBLISH_S
        events = self.det.events()
        for e in events:
            e["call"] = self._named(e)
            if e["kind"] == "leila" and e["id"] in self.saved:
                e["capture"] = self.saved_names.get(e["id"])
        with self.lock:
            self.list = events
        self.radio._publish("overpower", {"t": now, "events": events, "beacon": self.det.beacon})
        self._status(now)

    def _status(self, now: float) -> None:
        m0, c0 = self.cpu_t0
        mono = time.monotonic()
        if mono - m0 >= 10.0:
            self.radio._status(opCpu=round(100.0 * (self.cpu - c0) / (mono - m0), 2))
            self.cpu_t0 = (mono, self.cpu)
        ev = self.list
        self.radio._status(opActive=sum(1 for e in ev if e["active"] and e["kind"] == "overpower"),
                           opLeila=sum(1 for e in ev if e["kind"] == "leila"), opDropped=self.dropped,
                           opBeacon=self.det.beacon)

    # -- evidence capture ------------------------------------------------------
    def _keep(self, b) -> None:
        x, centre, corr = b[0], b[6], b[7]
        data, _clipped = sigmf.to_ci16(x)
        self.ring.append((data, centre, b[4] - len(x) / self.radio.geo.fs, corr))
        self.ring_bytes += len(data)
        cap = min(CAPTURE_MAX_BYTES, CAPTURE_S * self.radio.geo.fs * sigmf.BYTES_PER_SAMPLE)
        while self.ring and self.ring_bytes > cap:
            self.ring_bytes -= len(self.ring.popleft()[0])

    def _capture(self, now: float) -> None:
        if not self.ring:
            self.pending = None
            self.want_now = False
            return
        if self.want_now:
            self.want_now = False
            self._save(None)
            return
        sirens = [e for e in self.list if e["kind"] == "leila" and e["id"] not in self.saved]
        for e in sirens:
            if self.pending is None:
                self.pending = (e["id"], now)
        if self.pending is not None:
            sid, since = self.pending
            e = next((e for e in self.list if e["id"] == sid), None)
            if e is None or not e["active"] or now - since >= CAPTURE_WAIT_S:
                self.pending = None
                self.saved.add(sid)
                self._save(e)

    def _save(self, siren: dict | None) -> None:
        """The ring as a SigMF recording in the Recordings folder, named
        ...-LEILA. Written by the recorder's own thread: the worker only
        hands it the ring's blocks, already encoded."""
        r = self.radio
        s = r.state()
        blocks = list(self.ring)
        try:
            folder = r.recordings_dir()
            folder.mkdir(parents=True, exist_ok=True)
            base = sigmf.new_base(folder, r.CONFIG.app.name, blocks[0][2], s["rxDial"], "leila")
            meta = r._rec_meta(s)
            seconds = self.ring_bytes / sigmf.BYTES_PER_SAMPLE / r.geo.fs
            meta["core:description"] = (
                f"LEILA siren at {siren['freq'] / 1e6:.6f} MHz and the {seconds:.0f} s before it, kept by "
                f"{meta['core:recorder']}'s evidence capture" if siren is not None else
                f"The last {seconds:.0f} s, saved by hand from {meta['core:recorder']}'s LEILA evidence capture")
            # What the watch saw: after the receive chain's mirroring (for an
            # inverting converter) and its noise blanker, if on - so not the
            # device's own stream, as a recording is.
            meta["openhamshack:inverted"] = False
            meta["openhamshack:capture"] = "leila: receive IQ after mirroring and the noise blanker"
            if siren is not None:
                meta["openhamshack:leila"] = siren
            rec = sigmf.Recorder(base, r.geo.fs, meta, queue_s=CAPTURE_S + 5.0).start()
        except OSError as e:
            r.toast(_("LEILA evidence not saved: {error}").format(error=e), "warn")
            return
        for data, centre, utc, corr in blocks:
            rec.push(data, centre, utc, track={"rxCorr": corr})
        rec.close("LEILA evidence capture")
        self.last_capture = rec.data_path.name
        if siren is not None:
            self.saved_names[siren["id"]] = rec.data_path.name
        r._status(opCapture=rec.data_path.name)
        r.toast(_("LEILA evidence saved: {name} ({seconds:.0f} s of receive IQ, in Recordings)").format(
            name=rec.data_path.stem, seconds=sum(len(b[0]) for b in blocks) / sigmf.BYTES_PER_SAMPLE / r.geo.fs),
            "info")
        log.info("LEILA evidence saved to %s", rec.data_path)


__all__ = ["OverpowerWatch"]
