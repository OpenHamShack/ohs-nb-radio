"""Recordings on the controller (Brian, 12/10/2026): receive audio and IQ,
made and kept by the store form, not by the device that asked.

The rules - one of each kind at a time, the disk-use limit and the
free-space floor, the API's shape - are ohs-libs' shack_rec, which Icom and
Flex share (its README is the contract). What is NB and Radio's own:

- **Audio** is StreamAudio's blocks (s16le at the engine's OUT_RATE: 48
  kHz for Radio, 12 kHz for QO-100 NB), the ones api/audio/rx sends:
  demodulated, after the engine's noise reduction when it is on. Encoded
  as FLAC (shack_rec.flac says why). Stereo when the mode is making stereo
  as the recording starts (Radio's wide FM with a station's pilot, or
  DAB), mono otherwise, and that channel count holds for the whole file: a
  FLAC stream's channel count is in its header, so a later mode change is
  converted to it (StreamAudio.play), never a second format in one file.
- **A broadcast station is recorded as itself** (24/10/2026, for the TV's
  DAB Radio): while Radio plays a DAB station or a wide FM one
  (Engine.broadcast_station) the recording's `mode` is "DAB", "DAB+" or
  "WFM", its `freqHz` the block's centre or the dial, the sidecar's
  `broadcast` says which station (name, SId or PI, ensemble, programme
  type, the text and DL Plus as it started), `changes` carries what the
  station said as it changed (a small "now playing" history), and the
  file is named after it (host.recording_name). Always stereo: a
  station's stereo is known only once its pilot or its first audio frame
  is heard, and a file's channel count is fixed at its start, so a
  recording begun in that first moment was mono for good. A mono station
  in a stereo FLAC costs almost nothing (FLAC codes the second channel as
  the difference). Before this a DAB recording was named after the dial
  and the operator's mode from before DAB took the receiver
  ("...-218.640000MHz-FM").
- **From the past** (24/10/2026; timeshift.py, SERVER-API "Timeshift"):
  while a broadcast station plays, an audio recording may start in the
  timeshift (`fromSecondsAgo`, `fromItemStart`, `lastMinutes`, or the
  `recordLeadSeconds` setting when nothing is said). The timeshift then
  feeds it - the past as fast as the recorder's queue takes it, then the
  live blocks that came meanwhile, then each live block as it is played -
  instead of its own tap on the audio, so the join loses and repeats
  nothing. Its start time and name are when its first sample was played.
- **IQ** is the engine's own SigMF recorder (ohscore/sigmf.py, which the
  desktop app has used since 05/10): the device's stream before the
  engine touches it, ci16, playable again through the "file" device and
  read by ohsnb's analysis tools. Only its folder and its length are set
  here: the length is the shorter of RECORDINGS_IQ_MAX_MINUTES and what
  the limit and the free space allow at the engine's sample rate, so a
  recording can never be the thing that fills the disk.
- **Receive only.** Nothing here keys, claims or retunes anything. The
  engine stopping (a person's stop, a hand-over, a lost claim) ends an IQ
  recording by itself; audio carries on, silent, until stopped or limited.

Where: the module's data volume, `/data/recordings` (OHS_NB_DATA/OHS_RADIO_DATA
is /data in the store image), which survives updates.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from pathlib import Path

from .. import host, shacklibs, sigmf
from ..i18n.text import _
from .timeshift import Gone

log = logging.getLogger("ohscore.server")

LIMIT_GB = 10            # IQ is 290 MB a minute at 1.2 MS/s: room for half an hour of it
NOTE_EVERY_S = 0.5       # how often the audio recording's frequency and mode are looked at


class _IqHandle:
    """The engine's SigMF recorder, as shack_rec.Recordings holds a recording."""

    kind = "iq"

    def __init__(self, radio, rec: sigmf.Recorder, max_seconds: float, max_bytes: int):
        self.radio, self.rec = radio, rec
        self.id = rec.data_path.name[:-len(sigmf.DATA_SUFFIX)]
        self.done = rec.done
        self.max_seconds, self.max_bytes = max_seconds, max_bytes

    @property
    def reason(self) -> str:
        return _("the time limit") if self.rec.reason == "time limit" else self.rec.reason

    @property
    def error(self) -> str:
        return self.rec.error

    @property
    def nbytes(self) -> int:
        return self.rec.nbytes

    def close(self, reason: str = "") -> None:
        if self.radio.rec is self.rec:
            self.radio._rec_end(self.rec, reason)
        else:
            self.rec.close(reason)

    def status(self) -> dict:
        r = self.rec
        caps = r.captures
        return {"id": self.id, "kind": "iq", "format": "sigmf-" + sigmf.DATATYPE,
                "startUtc": sigmf.iso_utc(r.t_start)[:19] + "Z" if r.t_start else None,
                "seconds": round(r.seconds, 1), "bytes": r.nbytes, "maxSeconds": round(self.max_seconds),
                "maxBytes": self.max_bytes, "droppedSeconds": round(r.dropped / r.fs, 1),
                "sampleRate": r.fs, "freqHz": caps[-1]["core:frequency"] if caps else None,
                "mode": str(r.meta.get("openhamshack:receive", {}).get("mode") or "").upper() or None}


@functools.cache
def _named(rec):
    """shack_rec's Recordings (`rec` is the loaded shack_rec), naming an
    audio recording as this app names its IQ ones (host.recording_name),
    which shack_rec's own new_id cannot: it takes only the dial and the
    mode, and squeezes the app's name to letters and digits. A subclass
    made once per loaded shack_rec, because the library is loaded at run
    time (shacklibs.rec)."""

    class NamedRecordings(rec.Recordings):
        def __init__(self, *args, namer, **kw):
            super().__init__(*args, **kw)
            self.namer = namer                    # (t, meta) -> base name
            self._starting = threading.local()    # the start_audio on this thread: its meta and start time
            # A recording from the timeshift began in the past: its name
            # and startUtc are when its first sample was played. Both are
            # read from `wall` on the starting thread only (the end time is
            # the writer thread's, and stays the real clock).
            real = self.wall
            self.wall = lambda: getattr(self._starting, "utc", None) or real()

        def start_audio(self, rate: int, channels: int, meta: dict, utc: float | None = None):
            self._starting.meta, self._starting.utc = meta, utc
            try:
                return super().start_audio(rate, channels, meta)
            finally:
                self._starting.meta = self._starting.utc = None

        def new_id(self, freq_hz=None, mode=None) -> str:
            meta = getattr(self._starting, "meta", None)
            if meta is None:
                return super().new_id(freq_hz, mode)
            name = self.namer(self.wall(), meta)
            folder = self.store.folder
            for i in range(1, 1000):
                rid = name if i == 1 else f"{name}-{i}"
                if not any((folder / (rid + suffix)).exists() for suffix in rec.store.LAYOUT):
                    return rid
            raise rec.Refused(409, "name_taken", _("Too many recordings started in the same second."))

    return NamedRecordings


class ServerRecordings:
    """The store form's recordings: shack_rec's Recordings, the audio tap
    and the engine's IQ recorder."""

    def __init__(self, radio, audio, info, folder: Path | None = None, limits=None, disk_usage=None,
                 timeshift=None):
        rec = shacklibs.rec()
        self.radio, self.audio, self.info = radio, audio, info
        if limits is None:
            limits = rec.Limits.from_env(os.environ, limit_bytes=LIMIT_GB * rec.GB)
        kw = {"disk_usage": disk_usage} if disk_usage is not None else {}
        # Named with the app's own name (openhamshack-radio), as its IQ
        # recordings and the desktop app's are; the module id (shack-radio)
        # stays the sidecar's `app`, which is shack_rec's: which module made it.
        app_id = getattr(getattr(radio, "CONFIG", None), "app", None)
        self.prefix = app_id.name if app_id is not None else info.app_id
        self.rec = _named(rec)(folder or radio.recordings_dir(), limits, app=info.app_id, kinds=("audio", "iq"),
                               namer=self._name, **kw)
        self.Refused = rec.Refused
        self._noting: threading.Thread | None = None
        self.timeshift = timeshift
        self._broadcasts: dict = {}         # metadata path -> ((mtime, size), broadcast): listing()'s

    # ---------------------------------------------------------------- start
    PAST = ("fromSecondsAgo", "fromItemStart", "lastMinutes")

    def start(self, kind: str, body: dict | None = None) -> dict:
        """Start recording `kind` (`body`: api/recordings/start's, for where
        an audio recording starts: PAST); raises shack_rec.Refused."""
        body = body or {}
        if kind not in ("audio", "iq"):
            self.rec.prepare(kind)                         # says why: bad_kind
        if not self.radio.state().get("running"):
            raise self.Refused(409, "not_running", _("Start the radio before recording"))
        if kind == "iq":
            if any(body.get(k) not in (None, False) for k in self.PAST):
                raise self.Refused(400, "bad_params", _("Only audio is kept in the timeshift: IQ records from now"))
            self._start_iq()
            return self.rec.status()
        past = self._start_audio(body)
        out = self.rec.status()
        if past is not None:
            out["timeshift"] = past
        return out

    def _name(self, t: float, meta: dict) -> str:
        return host.recording_name(self.prefix, t, meta.get("freqHz"), meta.get("mode"), meta.get("broadcast"))

    # What of a broadcast station's goes into `changes` as it changes: its
    # name and the text it sends, so the sidecar says what was on when.
    NOTED = ("label", "sid", "pi", "ensemble", "dls", "rt", "title", "artist")

    def _station(self) -> dict | None:
        fn = getattr(self.radio, "broadcast_station", None)
        return fn() if fn is not None else None

    def _facts(self, station: dict | None = None) -> dict:
        s = self.radio.state()
        if station:
            out = {"freqHz": round(float(station.get("freqHz") or s.get("rxDial") or 0)) or None,
                   "mode": station["mode"]}
            out.update((k, station[k]) for k in self.NOTED if station.get(k) is not None)
            return out
        # A session holding the receiver for something else (Radio's AIS,
        # ADS-B): its frequency and its name, not the operator's mode.
        held = getattr(self.radio, "held_service", None)
        held = held() if held is not None else None
        if held:
            return {"freqHz": round(float(held.get("freqHz") or 0)) or None, "mode": held["mode"]}
        return {"freqHz": round(float(s.get("rxDial") or 0)) or None, "mode": str(s.get("mode") or "").upper() or None}

    def _past(self, body: dict, station: dict | None):
        """Where an audio recording starts (api/recordings/start's PAST
        fields, or recordLeadSeconds): None for now, else {"gen", "index",
        "secondsAgo", "untilNow", "why"}, the buffer's position and what
        was used. Refused when the request cannot be done as asked."""
        ts = self.timeshift
        asked = {k: body[k] for k in self.PAST if body.get(k) not in (None, False)}
        if len(asked) > 1:
            raise self.Refused(400, "bad_params", _("Give one of fromSecondsAgo, fromItemStart and lastMinutes"))
        try:
            if "lastMinutes" in asked or "fromSecondsAgo" in asked:
                key = "lastMinutes" if "lastMinutes" in asked else "fromSecondsAgo"
                try:
                    want = float(asked[key]) * (60.0 if key == "lastMinutes" else 1.0)
                except (TypeError, ValueError):
                    want = -1.0
                if not want >= 0 or (key == "lastMinutes" and want <= 0):
                    raise self.Refused(400, "bad_params", _("{key} must be a positive number").format(key=key))
                if ts is None:
                    raise Gone()
                gen, index, ago = ts.position(want)
                why = "" if ago >= want - 0.05 else _(
                    "The timeshift holds {s:.0f} s: recording from its start").format(s=ago)
                return {"gen": gen, "index": index, "secondsAgo": ago, "untilNow": key == "lastMinutes", "why": why}
            if "fromItemStart" in asked:
                if ts is None:
                    raise Gone()
                gen, index, ago, why = ts.item_start()
                return {"gen": gen, "index": index, "secondsAgo": ago, "untilNow": False, "why": why}
        except Gone:
            raise self.Refused(409, "no_timeshift", _(
                "Nothing is kept to record from the past: the timeshift keeps a DAB or wide FM station while it "
                "plays")) from None
        # Nothing asked: while a broadcast station plays, its lead.
        lead = float(self.radio.st.get("recordLeadSeconds") or 0) if station else 0.0
        if lead <= 0 or ts is None:
            return None
        try:
            gen, index, ago = ts.position(lead)
        except Gone:
            return None
        return {"gen": gen, "index": index, "secondsAgo": ago, "untilNow": False, "why": ""}

    def _start_audio(self, body: dict | None = None) -> dict | None:
        s = self.radio.state()
        station = self._station()
        past = self._past(body or {}, station)
        facts = self._facts(station)
        meta = {"freqHz": facts["freqHz"], "mode": facts["mode"], "appName": self.info.name,
                "version": self.info.version, "station": s.get("callsign") or None, "radio": s.get("device"),
                "processing": {"nr": s.get("nr"), "nb": s.get("nb"), "agc": s.get("agc")}}
        if station:
            # Nested: `station` is already the operator's callsign, and the
            # sidecar's own `kind` is shack_rec's ("audio").
            meta["broadcast"] = dict(station)
        utc = None
        if past is not None:
            meta["fromSecondsAgo"] = round(past["secondsAgo"], 2)
            utc = self.timeshift.utc(past["index"])
        # From the timeshift it is the buffer's two channels; a broadcast
        # station's is stereo anyway (the module docstring).
        fmt = self.audio.rx_format(2 if station or past is not None else self.radio.audio_channels())
        r = self.rec.start_audio(fmt["rate"], fmt["channels"], meta, utc=utc)
        # The station as it starts, at 0 s: before any of the past is in.
        r.note(**facts)
        if past is not None:
            try:
                f = self.timeshift.follow(
                    past["gen"], past["index"], r.push, until_now=past["untilNow"],
                    # The recorder drops what does not fit its queue: the
                    # past is handed over no faster than it is written.
                    room=lambda: r.queued < r.cap // 2,
                    on_end=lambda why: r.close(why or _("the timeshift's minutes are all in it")))
                r.on_close(lambda: self.timeshift.unfollow(f))
            except Gone:                                    # cleared since: from now instead
                past = {**past, "secondsAgo": 0.0, "why": _("The timeshift was cleared as the recording "
                                                             "started: recording from now")}
                r.on_close(self.audio.tap(r.push, fmt["channels"]))
        else:
            r.on_close(self.audio.tap(r.push, fmt["channels"]))
        t = threading.Thread(target=self._note_loop, args=(r,), name="server-rec-note", daemon=True)
        t.start()
        if past is None:
            return None
        return {"fromSecondsAgo": round(past["secondsAgo"], 1), "startUtc": utc and time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(utc)), "untilNow": past["untilNow"], "why": past["why"]}

    def _note_loop(self, r) -> None:
        """Frequency and mode changes into the audio recording's sidecar.
        The radio stopping ends it: with the engine stopped nothing is
        played, and a recording that silently skipped the time the radio
        was off would put everything after it at the wrong time."""
        while not r.closing:
            if not self.radio.state().get("running"):
                r.close(_("the radio stopped"))
                break
            r.note(**self._facts(self._station()))
            r.done.wait(NOTE_EVERY_S)

    def _start_iq(self) -> None:
        budget = self.rec.prepare("iq")
        fs = float(self.radio.state().get("fs") or getattr(self.radio.geo, "fs", 0) or 0)
        seconds = budget["max_seconds"]
        if fs > 0:
            seconds = min(seconds, budget["max_bytes"] / sigmf.bytes_per_second(fs))
        try:
            self.radio.start_recording(limit_s=max(1.0, seconds), folder=self.rec.store.folder)
        except ValueError as e:
            raise self.Refused(409, "cannot_record", str(e)) from None
        rec = self.radio.rec
        self.rec.adopt("iq", _IqHandle(self.radio, rec, seconds, budget["max_bytes"]))

    # ---------------------------------------------------------------- the rest
    def stop(self, kind: str | None = None) -> list[dict]:
        return self.rec.stop(kind, wait=3.0)

    def status(self) -> dict:
        return self.rec.status()

    def summary(self) -> dict:
        """For api/status, polled often: no disk scan."""
        with self.rec.lock:
            active = sorted(self.rec.active)
        return {"kinds": list(self.rec.kinds), "active": active}

    def listing(self) -> dict:
        """shack_rec's listing, each entry with its `broadcast` (the station
        as the recording began; null for any other) so a client can show
        the station, mode, title and artist without fetching every
        sidecar. Only that object: never the sidecar's `changes`, which
        grow with the recording. shack_rec's own list keeps a fixed set of
        fields, so it is read here from each metadata file, once per
        version of the file."""
        out = self.rec.listing()
        folder = self.rec.store.folder
        for e in out.get("recordings") or []:
            meta = (e.get("parts") or {}).get("meta")
            e["broadcast"] = self._broadcast(folder / meta["name"], e["kind"]) if meta else None
        return out

    def _broadcast(self, path: Path, kind: str):
        try:
            st = path.stat()
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._broadcasts.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
        try:
            doc = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return None
        b = doc.get("broadcast") if kind == "audio" else (doc.get("global") or {}).get("openhamshack:broadcast")
        b = b if isinstance(b, dict) else None
        if len(self._broadcasts) > 2000:
            self._broadcasts.clear()
        self._broadcasts[path] = (key, b)
        return b

    def file(self, rid: str, part: str):
        return self.rec.file(rid, part)

    def delete(self, rid: str) -> dict:
        return self.rec.delete(rid)


class RecordingsRefused(Exception):
    """NoRecordings' refusal, shaped as shack_rec.Refused is (status, code,
    text) so the API answers it the same way."""

    def __init__(self, status: int, code: str, text: str):
        super().__init__(text)
        self.status, self.code, self.text = status, code, text


class NoRecordings:
    """The recordings API where shack_rec cannot be loaded: listing and
    status answer, empty, with `unavailable` saying why; starting, deleting
    and downloading are refused (503, recordings_unavailable).

    The store image always carries shack_rec. The desktop builds do not
    (packaging/shack_vendor.py's RUNTIME): Brian's rule is no servers
    inside the desktop apps, so `--server` from a .app or an installer is
    a developer's convenience, not a form we ship, and bundling a
    server-only library into every desktop install to serve it was the
    wrong trade. Until 17/10/2026 that run died at start-up with
    SharedLibraryMissing; now it serves the radio and says, once in the
    log and on every recordings answer, why it cannot record."""

    kinds: tuple = ()
    Refused = RecordingsRefused

    def __init__(self, why: str):
        self.why = _("Recording is not available in this installation: {why}").format(why=why)

    def _refuse(self, *_a, **_k):
        raise RecordingsRefused(503, "recordings_unavailable", self.why)

    start = file = delete = _refuse

    def stop(self, kind: str | None = None) -> list[dict]:
        return []

    def status(self) -> dict:
        return {"recording": False, "active": [], "kinds": [], "last": None, "unavailable": self.why}

    def summary(self) -> dict:
        return {"kinds": [], "active": [], "unavailable": self.why}

    def listing(self) -> dict:
        return {"recordings": [], **self.status()}


def server_recordings(radio, audio, info, **kw):
    """ServerRecordings, or NoRecordings when shack_rec is missing (see
    NoRecordings for when that is, and why it is not fatal)."""
    try:
        return ServerRecordings(radio, audio, info, **kw)
    except shacklibs.SharedLibraryMissing as exc:
        log.warning("recordings are off: %s; api/recordings refuses to record (recordings_unavailable)", exc)
        return NoRecordings(str(exc))
