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

import logging
import os
import threading
from pathlib import Path

from .. import shacklibs, sigmf
from ..i18n.text import _

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


class ServerRecordings:
    """The store form's recordings: shack_rec's Recordings, the audio tap
    and the engine's IQ recorder."""

    def __init__(self, radio, audio, info, folder: Path | None = None, limits=None, disk_usage=None):
        rec = shacklibs.rec()
        self.radio, self.audio, self.info = radio, audio, info
        if limits is None:
            limits = rec.Limits.from_env(os.environ, limit_bytes=LIMIT_GB * rec.GB)
        kw = {"disk_usage": disk_usage} if disk_usage is not None else {}
        self.rec = rec.Recordings(folder or radio.recordings_dir(), limits, app=info.app_id,
                                  kinds=("audio", "iq"), **kw)
        self.Refused = rec.Refused
        self._noting: threading.Thread | None = None

    # ---------------------------------------------------------------- start
    def start(self, kind: str) -> dict:
        """Start recording `kind`; raises shack_rec.Refused."""
        if kind not in ("audio", "iq"):
            self.rec.prepare(kind)                         # says why: bad_kind
        if not self.radio.state().get("running"):
            raise self.Refused(409, "not_running", _("Start the radio before recording"))
        if kind == "iq":
            self._start_iq()
        else:
            self._start_audio()
        return self.rec.status()

    def _facts(self) -> dict:
        s = self.radio.state()
        return {"freqHz": round(float(s.get("rxDial") or 0)) or None, "mode": str(s.get("mode") or "").upper() or None}

    def _start_audio(self) -> None:
        s = self.radio.state()
        meta = {**self._facts(), "appName": self.info.name, "version": self.info.version,
                "station": s.get("callsign") or None, "radio": s.get("device"),
                "processing": {"nr": s.get("nr"), "nb": s.get("nb"), "agc": s.get("agc")}}
        fmt = self.audio.rx_format(self.radio.audio_channels())
        r = self.rec.start_audio(fmt["rate"], fmt["channels"], meta)
        r.on_close(self.audio.tap(r.push, fmt["channels"]))
        t = threading.Thread(target=self._note_loop, args=(r,), name="server-rec-note", daemon=True)
        t.start()

    def _note_loop(self, r) -> None:
        """Frequency and mode changes into the audio recording's sidecar.
        The radio stopping ends it: with the engine stopped nothing is
        played, and a recording that silently skipped the time the radio
        was off would put everything after it at the wrong time."""
        while not r.closing:
            if not self.radio.state().get("running"):
                r.close(_("the radio stopped"))
                break
            r.note(**self._facts())
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
        return self.rec.listing()

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
