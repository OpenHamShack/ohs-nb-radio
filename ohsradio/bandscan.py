"""The weekly band scan: Radio's own list of the FM and DAB stations it can
hear, made at night while nobody is using the radio (Brian, 23/10/2026).

    scanner = radio.bandscan            # made with the Radio
    scanner.tick()                      # the supervisor, ten times a second: the nightly attempt
    scanner.scan_now("fm" | "dab" | "both")   # POST api/scan; raises Refused with the sentence
    scanner.view("fm") / view("dab")    # GET api/fm/stations, api/dab/stations

**When.** Once a night, at the first tick after `scanHour` o'clock local
time (03:00 by default) and within the hour after it, each band whose last
good scan is more than `scanEveryDays` (7) old is scanned - if Radio is
idle then. Idle is all of: nobody listening (no `api/audio/rx` client; on
the desktop, no broadcast station playing unmuted), nobody has changed
anything for `scanIdleMinutes` (30), not transmitting nor automatic
transmit armed, not recording (IQ or audio) nor playing a recording, no
decoder session, the CW skimmer off, and the receiver not held (`rxOwner`).
Busy, the night is skipped, its reason kept as the band's status, and the
next night tries again. A radio that is stopped at that hour is simply not
asked. "Scan now" (`scan_now`) needs only the hard half of that: nobody
listening or tuning is no reason to refuse someone who asks.

**A week is the same night a week later.** A scan that finished at 03:01
is 6 days 23 h 59 min old at the next week's 03:00, so the age is judged
with SLACK_S of slack; strictly more than seven days would skip to the
eighth night every time.

**How.** The scanner takes the receiver through the engine's receiver
holding (Engine.hold_receiver, as DAB does), as a hold that *gives way*
and moves only the receiver's centre, never the dial: the operator's dial
stays on show, the transmit guard goes on judging it, and a key-up that
ends the scan keys where they left it. The dial, mode, repeater settings,
RIT, gain mode, gain, the RSP's LNA state, the antenna, the de-emphasis
and the sample rate are kept all the same, and the receiver's centre, and
the
moment anyone does anything with the radio - a set() that changes
anything, a key-up, a decoder, a recording, a listener connecting
(Engine.client_activity) - the hold gives way on that caller's thread:
everything is put back before what they asked for happens, and the scan
ends as `aborted`, its old list kept. Nothing here keys: the hold refuses
no key-up, it is ended by it.

**The sample rate is never changed.** Changing it reopens the radio (the
`sampleRate` setting restarts it), which on a controller gives the broker's
claim back and takes it again - the DAB session's finding, and true of the
RSPdx, whose only rate in Radio is 2.4 MS/s anyway. So the scan hops at the
rate the radio runs at:

- **FM:** 87.5-108 MHz on the 100 kHz grid, each hop's centre half-way
  between two channels (the receiver's DC spur on no station), listening
  FM_LISTEN_S and handing the capture to shack_sdr's `wfm.scan_band`,
  which decodes every carrier at once. A hop keeps the stations within
  `fm_reach(fs)` of its centre, what scan_band was measured to find on
  the test transmitter (fs/2 - 250 kHz: +-0.95 MHz at 2.4 MS/s, eleven
  hops; +-0.35 MHz at 1.2 MS/s, twenty-six).
- **DAB:** each Band III block (5A-13F, EN 300 401's table as shack_sdr
  holds it), the receiver's centre on the block's unused middle carrier,
  DAB_FIRST_S of IQ to `dab.survey`, and DAB_MORE_S more for a block that
  synced but whose list was not complete. Needs 2.048 MS/s or more.

**Merged by programme.** FM stations with the same PI are one programme:
the strongest frequency is its `best`, the rest its `alts`; one without RDS
is listed by its frequency alone. DAB is listed per ensemble with its
block and services.

**Kept** in Radio's data folder (`bandscan/fm.json`, `bandscan/dab.json`),
so the lists and the schedule survive a restart; `stationsAt` in the state
and a `stations` item on the feed of that name say when a list changed,
and `bandScan` in the state is the scan's progress ({} while none runs).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.bandscan")

BANDS = ("fm", "dab")
SID = "bandscan"                      # the hold's session id (rxOwner.session)
FM_LO, FM_HI, FM_GRID = 87_500_000, 108_000_000, 100_000
FM_LISTEN_S = 3.0                     # a programme service name twice and a radiotext, at a good signal
FM_BUDGET_S = 3.0                     # scan_band's wall-clock budget per hop
FM_EDGE_HZ = 250_000.0                # fm_reach: measured, see the docstring
DAB_RATE = 2_048_000.0
DAB_FIRST_S = 1.2                     # FIC read 0.15-0.2 s in, list complete 0.7-0.8 s (shack_sdr README)
DAB_MORE_S = 1.2
WINDOW_S = 3600.0                     # the nightly attempt's window after scanHour
SLACK_S = 2 * 3600.0                  # "a week" is the same night a week later (docstring)
STALL_S = 20.0                        # wall clock with no samples at all: the receiver has stopped (_capture)
# What a scan keeps and puts back, beyond what any hold does (Radio's
# HOLD_PRIOR: the dial, mode and repeater offset). Only keys the radio has.
KEEP = ("rptShift", "rptReverse", "rit", "ritOn", "rxGainMode", "rxGain", "sdrplayLna", "hl2Lna", "soapyAntenna",
        "sampleRate", "wfmDeemphasis")


class Refused(ValueError):
    """A scan that cannot start now: `code` and the sentence."""

    def __init__(self, code: str, sentence: str):
        super().__init__(sentence)
        self.code = code


class _Aborted(Exception):
    pass


def fm_reach(fs: float) -> float:
    """How far from a hop's centre scan_band finds stations at `fs`."""
    return fs / 2 - FM_EDGE_HZ


def fm_hops(fs: float, lo: int = FM_LO, hi: int = FM_HI) -> list[tuple[float, list[int]]]:
    """[(centre, the grid channels it is responsible for)] covering lo..hi:
    runs of whole channels, the centre half-way between the middle two, the
    runs spread evenly so the last does not hang past `hi`."""
    grid = list(range(lo, hi + 1, FM_GRID))
    per = 2 * int((fm_reach(fs) - FM_GRID / 2) // FM_GRID + 1)     # channels either side, both sides
    per = max(2, min(per, len(grid)))
    n = math.ceil(len(grid) / per)
    out = []
    for k in range(n):
        start = round(k * (len(grid) - per) / (n - 1)) if n > 1 else 0
        run = grid[start:start + per]
        out.append(((run[0] + run[-1]) / 2.0, run))
    # Each channel to exactly one hop: overlapping runs give their shared
    # channels to the first.
    seen: set[int] = set()
    for _c, run in out:
        run[:] = [g for g in run if g not in seen]
        seen.update(run)
    return [(c, run) for c, run in out if run]


def merge_fm(found: list[dict]) -> list[dict]:
    """scan_band's stations (one per frequency) as programmes: merged by PI,
    the strongest frequency `best`, the others `alts` (strongest first);
    one without RDS stands alone. By the best frequency."""
    by_pi: dict[str, list[dict]] = {}
    alone = []
    for st in found:
        (by_pi.setdefault(st["pi"], []) if st.get("pi") else alone).append(st)

    def freq(st):
        return {"hz": int(st["hz"]), "level": round(float(st["levelDb"]), 1), "stereo": bool(st.get("stereo"))}

    out = []
    for pi, group in by_pi.items():
        group.sort(key=lambda s: -float(s["levelDb"]))
        best = group[0]

        def first(key):
            # The strongest frequency that has the field: a weak alternative
            # may have its PI and nothing else yet.
            return next((s[key] for s in group if s.get(key) is not None), None)
        pty = first("pty")
        out.append({"pi": pi, "ps": first("ps"), "pty": pty, "ptyName": first("ptyName"), "rt": first("rt"),
                    "best": freq(best), "alts": [freq(s) for s in group[1:]]})
    for st in alone:
        out.append({"pi": None, "ps": None, "pty": None, "ptyName": None, "rt": None, "best": freq(st), "alts": []})
    out.sort(key=lambda p: p["best"]["hz"])
    return out


def dab_ensemble(block: str, centre: float, meta: dict) -> dict:
    """A block's survey as the list keeps it."""
    ens = meta.get("ensemble") or {}
    services = [{"sid": s.get("sid"), "label": s.get("label"), "kind": s.get("kind"),
                 "bitrate": int(s["bitrate"]) if s.get("bitrate") is not None else None}
                for s in meta.get("services") or []]
    return {"block": block, "freqHz": int(centre), "id": ens.get("id"), "label": ens.get("label"),
            "services": services}


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BandScanner:
    """Radio's band scanner (module docstring). `clock` is epoch seconds (a
    test's fake clock) and `tz` the local time zone the nightly hour is in
    (None: the machine's)."""

    def __init__(self, radio, clock=time.time, tz=None, folder: Path | None = None):
        self.radio = radio
        self.clock = clock
        self.tz = tz
        self.folder = Path(folder) if folder is not None else Path(radio.data_dir) / "bandscan"
        self.lock = threading.Lock()            # the hold: a yield and the worker's own moves take turns
        self._tick_lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.aborted: str | None = None
        self.running_bands: tuple = ()
        self.last_activity: float | None = None
        # The server's own reasons to be busy (automatic transmit armed, an
        # audio recording) and its listener count; the desktop has neither.
        self.probes: list = []
        self.listeners = None
        self._cap = None
        self._got = threading.Event()
        self.records = {b: self._load(b) for b in BANDS}
        # FM's span limits, for a test that scans part of the band.
        self.fm_lo, self.fm_hi = FM_LO, FM_HI
        self.dab_blocks: list[str] | None = None

    # ------------------------------------------------------------ the lists
    def _path(self, band: str) -> Path:
        return self.folder / f"{band}.json"

    def _load(self, band: str) -> dict:
        rec = {"scannedAt": None, "status": "never", "statusText": "", "attempted": None,
               "stations" if band == "fm" else "ensembles": []}
        try:
            got = json.loads(self._path(band).read_text(encoding="utf-8"))
            if isinstance(got, dict):
                rec.update({k: got[k] for k in rec if k in got})
        except (OSError, ValueError):
            pass
        return rec

    def _store(self, band: str) -> None:
        """Written whole and renamed into place: a crash mid-write keeps the
        last list."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._path(band).with_suffix(".tmp")
            tmp.write_text(json.dumps(self.records[band], indent=1), encoding="utf-8")
            os.replace(tmp, self._path(band))
        except OSError:
            log.warning("could not keep the %s station list", band, exc_info=True)

    def _note(self, band: str, status: str, text: str = "", **more) -> None:
        rec = self.records[band]
        rec.update(status=status, statusText=text, **more)
        self._store(band)

    def view(self, band: str) -> dict:
        """GET api/fm/stations or api/dab/stations."""
        rec = self.records[band]
        key = "stations" if band == "fm" else "ensembles"
        status = "scanning" if band in self.running_bands else rec["status"]
        return {"scannedAt": _iso(rec["scannedAt"]), "nextDue": _iso(self.next_due(band)), "status": status,
                "statusText": self.status_text(band, status), key: list(rec[key])}

    def status_text(self, band: str, status: str) -> str:
        if status == "scanning":
            return _("Scanning now")
        if status == "ok":
            return ""
        if status == "never":
            return _("Not scanned yet")
        return self.records[band].get("statusText") or ""

    def stations_at(self) -> dict:
        return {b: _iso(self.records[b]["scannedAt"]) for b in BANDS}

    # ------------------------------------------------------------ when
    def _local(self, t: float) -> datetime:
        return datetime.fromtimestamp(t, self.tz) if self.tz is not None else datetime.fromtimestamp(t).astimezone()

    def _night(self, t: float) -> str | None:
        """Tonight's name (its date) while `t` is inside the nightly window."""
        loc = self._local(t)
        start = loc.replace(hour=int(self.radio.st["scanHour"]), minute=0, second=0, microsecond=0)
        if start <= loc < start + timedelta(seconds=WINDOW_S):
            return start.date().isoformat()
        return None

    def _due(self, band: str, now: float) -> bool:
        last = self.records[band]["scannedAt"]
        return last is None or now - float(last) > float(self.radio.st["scanEveryDays"]) * 86400 - SLACK_S

    def next_due(self, band: str, now: float | None = None) -> float | None:
        """When the next nightly attempt for `band` will be made (epoch), or
        None while automatic scans are off."""
        if not self.radio.st.get("scanAuto", True):
            return None
        now = self.clock() if now is None else now
        last = self.records[band]["scannedAt"]
        due = now if last is None else max(now, float(last) + float(self.radio.st["scanEveryDays"]) * 86400 - SLACK_S)
        loc = self._local(due)
        start = loc.replace(hour=int(self.radio.st["scanHour"]), minute=0, second=0, microsecond=0)
        if loc >= start + timedelta(seconds=WINDOW_S) or start.date().isoformat() == self.records[band]["attempted"]:
            start += timedelta(days=1)
        return max(start.timestamp(), due)

    def touch(self, what: str = "") -> None:
        """Engine.activity_hooks: someone did something with the radio."""
        self.last_activity = self.clock()

    def busy(self, idle: bool) -> str:
        """Why the receiver cannot be scanned now ("" if it can). `idle`
        adds the nightly rules: nobody listening, nothing done lately."""
        r = self.radio
        s = r.st
        if self.thread is not None and self.thread.is_alive():
            return _("A band scan is running already")
        if not r.running or r.dev is None:
            return _("The radio is not running")
        if s.get("keyed") or (r.tx_thread is not None and r.tx_thread.is_alive()):
            return _("Transmitting")
        if r.held is not None:
            return _("The receiver is in use: {text}").format(text=r._owner_view().get("text", ""))
        if r.rec is not None:
            return _("An IQ recording is being made")
        if r.play is not None:
            return _("A recording is playing")
        if r.decoders.fixed:
            return _("A decoder is running")
        if s.get("cwSkim"):
            return _("The CW skimmer is running")
        for probe in list(self.probes):
            why = probe()
            if why:
                return why
        if not idle:
            return ""
        n = self.listeners() if self.listeners is not None else 0
        if n:
            return _("Someone is listening")
        if self.listeners is None and s.get("mode") == "wfm" and not s.get("mute") and s.get("volume", 1.0) > 0:
            # The desktop: its speaker is a listener we cannot see. Playing
            # a broadcast station out loud at 03:00 is taken as somebody
            # listening to it; an amateur band's hiss is not.
            return _("A station is playing")
        last = self.last_activity
        quiet = float(s["scanIdleMinutes"]) * 60
        if last is not None and self.clock() - last < quiet:
            return _("The radio was used in the last {minutes:g} minutes").format(minutes=float(s["scanIdleMinutes"]))
        return ""

    def unsupported(self, band: str) -> str:
        """Why this radio cannot scan `band` at all ("" if it can)."""
        from ohscore import sdr
        r = self.radio
        if sdr.load() is None:
            return sdr.why()
        lo, hi = r.dev.rx_range if r.dev is not None else (0.0, 0.0)
        if band == "fm":
            if not (lo <= self.fm_lo and self.fm_hi <= hi):
                return _("The {device} does not receive the FM band").format(device=r._kind())
            return ""
        blocks = sdr.load().dab.BLOCKS
        if not (lo <= min(blocks.values()) - DAB_RATE / 2 and max(blocks.values()) + DAB_RATE / 2 <= hi):
            return _("The {device} does not receive Band III").format(device=r._kind())
        if float(r.geo.fs) < DAB_RATE:
            return r._rate_sentence(DAB_RATE, float(r.geo.fs))
        return ""

    def tick(self) -> None:
        """The nightly attempt (module docstring); cheap when there is none.
        One caller at a time: the supervisor's ticks and a caller's own
        must never both decide to start tonight's scan."""
        with self._tick_lock:
            self._tick()

    def _tick(self) -> None:
        s = self.radio.st
        if not s.get("scanAuto", True) or (self.thread is not None and self.thread.is_alive()):
            return
        now = self.clock()
        night = self._night(now)
        if night is None:
            return
        todo = [b for b in BANDS if self.records[b]["attempted"] != night and self._due(b, now)]
        if not todo:
            return
        for b in todo:
            self.records[b]["attempted"] = night
        why = self.busy(idle=True)
        if why:
            log.info("nightly band scan of %s skipped: %s", "+".join(todo), why)
            for b in todo:
                self._note(b, "busy", why)
            return
        go = []
        for b in todo:
            why = self.unsupported(b)
            if why:
                self._note(b, "unsupported", why)
            else:
                go.append(b)
        for b in todo:
            self._store(b)
        if go:
            log.info("nightly band scan of %s", "+".join(go))
            self._start(tuple(go))

    def scan_now(self, band: str) -> dict:
        """POST api/scan: `band` "fm", "dab" or "both". Raises Refused."""
        if band not in ("fm", "dab", "both"):
            raise Refused("bad_params", _("band must be fm, dab or both"))
        if not self.radio.running:
            raise Refused("not_running", _("Start the radio before scanning"))
        why = self.busy(idle=False)
        if why:
            raise Refused("receiver_busy", _("Not scanning now: {why}").format(why=why))
        want = BANDS if band == "both" else (band,)
        go = [b for b in want if not self.unsupported(b)]
        if not go:
            raise Refused("unsupported", self.unsupported(want[0]))
        self._start(tuple(go))
        return {"bands": list(go), "progress": self.radio.st.get("bandScan") or {}}

    # ------------------------------------------------------------ the scan
    def _start(self, bands: tuple) -> None:
        self.aborted = None
        self.running_bands = bands
        self._progress(bands[0], 0, "tuning", "")
        self.thread = threading.Thread(target=self._run, args=(bands,), name=f"{self.radio.THREAD_PREFIX}-bandscan",
                                       daemon=True)
        self.thread.start()

    def _progress(self, band: str, percent: float, phase: str, text: str, freq: float | None = None) -> None:
        self.radio._status(bandScan={"band": band, "percent": int(percent), "phase": phase, "freqHz": freq,
                                     "text": text})

    def _yield(self, why: str) -> None:
        """The hold gives way (Engine.preempt_receiver), on the caller's
        thread: everything put back before the caller goes on."""
        with self.lock:
            if self.aborted is None:
                self.aborted = why
                log.info("band scan gives the receiver back: %s", why)
            self.radio.release_receiver(SID)
        self._got.set()

    def _feed(self, raw: np.ndarray, settled: bool) -> None:
        """The receive thread, every block while the scan holds the receiver."""
        cap = self._cap
        if cap is None or not settled:
            return
        if abs(self.radio._dial_at(0.0) - cap["centre"]) > 1.0:
            return
        buf, k = cap["buf"], cap["n"]
        m = min(len(raw), len(buf) - k)
        buf[k:k + m] = raw[:m]
        cap["n"] = k + m
        if cap["n"] >= len(buf):
            self._cap = None
            self._got.set()

    def _tune(self, centre: float, label: str) -> None:
        with self.lock:
            if self.aborted is not None or not self.radio.move_hold(SID, centre, label):
                raise _Aborted()

    def _capture(self, seconds: float, centre: float) -> np.ndarray:
        n = int(seconds * float(self.radio.geo.fs))
        self._got.clear()
        cap = self._cap = {"buf": np.empty(n, np.complex64), "n": 0, "centre": float(centre)}
        # A guard, never a schedule: a capture fails only when no samples
        # have come for STALL_S. Its length in wall time is the radio's
        # business - a real one takes `seconds`, the simulator less, and a
        # simulator on a loaded machine (a test suite four wide) far more,
        # which a fixed allowance once mistook for a dead receiver.
        last, at = -1, time.monotonic()
        while not self._got.wait(0.5):
            if self.aborted is not None:
                break
            got = cap["n"]
            if got != last:
                last, at = got, time.monotonic()
            elif time.monotonic() - at > STALL_S:
                self._cap = None
                raise RuntimeError(_("The receiver stopped delivering samples"))
        self._cap = None
        if self.aborted is not None:
            raise _Aborted()
        return cap["buf"]

    def _run(self, bands: tuple) -> None:
        r = self.radio
        first = fm_hops(r.geo.fs, self.fm_lo, self.fm_hi)[0][0] if bands[0] == "fm" else \
            self._blocks()[0][1]
        try:
            r.hold_receiver(SID, "scan", first, self._label(bands[0]), 0.0, yields=self._yield, feed=self._feed,
                            keep=KEEP, dial=False)
        except Exception as e:  # noqa: BLE001 - decoders.Refused, ValueError: said as the band's status
            for b in bands:
                self._note(b, "failed", str(e))
            self.running_bands = ()
            r._status(bandScan={})
            return
        try:
            for b in bands:
                t0 = time.monotonic()
                try:
                    found = self._scan_fm() if b == "fm" else self._scan_dab()
                except _Aborted:
                    why = self.aborted or ""
                    self._note(b, "aborted", _("Stopped: the radio was wanted ({why})").format(why=why))
                    log.info("band scan of %s aborted: %s", b, why)
                    break
                except Exception as e:  # noqa: BLE001 - a failed scan keeps the last list
                    log.warning("band scan of %s failed", b, exc_info=True)
                    self._note(b, "failed", str(e))
                    continue
                key = "stations" if b == "fm" else "ensembles"
                self.records[b][key] = found
                self.records[b]["scannedAt"] = self.clock()
                self._note(b, "ok", "")
                log.info("band scan of %s: %d found in %.1f s", b, len(found), time.monotonic() - t0)
                r._status(stationsAt=self.stations_at())
                r._publish("stations", {"t": time.time(), "band": b, "scannedAt": _iso(self.records[b]["scannedAt"]),
                                        "count": len(found)})
        finally:
            with self.lock:
                r.release_receiver(SID)
            self.running_bands = ()
            r._status(bandScan={})

    @staticmethod
    def _label(band: str) -> str:
        return _("the FM band") if band == "fm" else _("Band III (DAB)")

    def _scan_fm(self) -> list[dict]:
        from ohscore import sdr
        wfm = sdr.load().wfm
        fs = float(self.radio.geo.fs)
        hops = fm_hops(fs, self.fm_lo, self.fm_hi)
        found: dict[int, dict] = {}
        for i, (centre, run) in enumerate(hops):
            self._progress("fm", 100 * i / len(hops), "listening",
                           _("FM: {mhz:.2f} MHz ({n} of {of})").format(mhz=centre / 1e6, n=i + 1, of=len(hops)),
                           centre)
            self._tune(centre, self._label("fm"))
            iq = self._capture(FM_LISTEN_S, centre)
            self._progress("fm", 100 * (i + 0.5) / len(hops), "decoding",
                           _("FM: {mhz:.2f} MHz ({n} of {of})").format(mhz=centre / 1e6, n=i + 1, of=len(hops)),
                           centre)
            mine = set(run)
            for st in wfm.scan_band(iq, rate=fs, center_hz=centre, budget_s=FM_BUDGET_S, threads=2, rt=True):
                hz = int(st["hz"])
                if hz in mine:
                    found[hz] = st
            del iq
        self._progress("fm", 100, "decoding", "")
        return merge_fm(list(found.values()))

    def _blocks(self) -> list[tuple[str, float]]:
        from ohscore import sdr
        blocks = sdr.load().dab.BLOCKS
        names = self.dab_blocks or list(blocks)
        return [(b, float(blocks[b])) for b in names]

    def _scan_dab(self) -> list[dict]:
        from ohscore import sdr
        dab = sdr.load().dab
        fs = float(self.radio.geo.fs)
        blocks = self._blocks()
        out = []
        for i, (name, centre) in enumerate(blocks):
            text = _("DAB: block {block} ({n} of {of})").format(block=name, n=i + 1, of=len(blocks))
            self._progress("dab", 100 * i / len(blocks), "listening", text, centre)
            self._tune(centre, self._label("dab"))
            iq = self._capture(DAB_FIRST_S, centre)
            got = dab.survey(iq, fs, give_up_s=1.0)
            meta = got.get("meta") or {}
            if meta.get("sync") and not meta.get("complete"):
                # Synced but the list is not whole yet: listen on.
                more = self._capture(DAB_MORE_S, centre)
                got = dab.survey(np.concatenate([iq, more]), fs, give_up_s=1.0)
                meta = got.get("meta") or {}
            if meta.get("ensemble"):
                out.append(dab_ensemble(name, centre, meta))
        self._progress("dab", 100, "decoding", "")
        return out
