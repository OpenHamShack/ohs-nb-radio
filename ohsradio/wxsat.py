"""Weather satellites: Radio predicts the Meteor-M LRPT passes over the
station and records each one as IQ, by itself (Brian, 29/10/2026;
docs/SERVER-API.md "Weather satellites"): prediction, the plan for each
pass and the recording here; decoding the recording into pictures after
LOS, with SatDump, in wxsat_decode.py.

    ws = radio.wxsat                     # made with the Radio
    ws.tick()                            # the supervisor, ten times a second
    ws.passes_view(hours)                # GET api/wxsat/passes
    ws.status_view()                     # GET api/wxsat/status
    ws.force(pass_id)                    # POST api/wxsat/passes/<id>/record; raises Refused
    ws.skip(pass_id)                     # DELETE api/wxsat/passes/<id>/record
    ws.images_view()                     # GET api/wxsat/images (wxsat_decode.py)
    ws.composite_view(kind, hours)       # GET api/wxsat/composite
    ws.image_file(id, product, thumb, ext)  # GET api/wxsat/images/<id>/<product>.<ext>

**The satellites** (SATELLITES): Meteor-M N2-3 on 137.100 MHz and N2-4 on
137.900 MHz, LRPT, as WMO OSCAR lists them on 29/10/2026 (N2-4 moved
between the two while it was commissioned in 2024; a satellite that moves
again is a one-line change here). Which are wanted is the
`wxsatSatellites` setting, a comma-separated list of their ids. Element
sets come from wxsat_tle.py, positions from wxsat_orbit.py, the station
from the `locator` setting (the station profile's), as AIS measures from.

**The plan for each pass**, as GET api/wxsat/passes reports it:

- `record` - it will be recorded (wxsatAuto on, the satellite enabled, the
  highest elevation at least `wxsatMinElevDeg`), or a client forced it.
- `skip-disabled` - the satellite is switched off, automatic recording is
  off, or a client skipped this pass (DELETE): `why` says which. The
  contract has no plain "skip", so the operator's skip is this one with
  its own sentence.
- `skip-low` - never higher than wxsatMinElevDeg: too little of it would
  be heard to make a picture.
- `skip-busy` / `skip-conflict` - decided at AOS (below), and kept.
- `recording`, then `done` or `failed`; `missed` for a pass that should have
  been recorded and was not (Radio not running then).
- `decoding` - recorded, and SatDump is decoding it or it waits its turn
  (wxsat_decode.py, one pass at a time); then `done` with its `imageId`,
  or `failed` with why (no lock, too short, SatDump's own failure). A
  form without SatDump (the desktop) leaves a recorded pass `done` with no
  imageId, as before the decoder existed. A Radio restarted while a pass
  was `decoding` decodes it again (resume_decoding).

**At AOS - who has the receiver.** A pass is station-scoped work, like a
scheduled recording or the nightly band scan, so it never takes the
receiver from anything else station-scoped and never from transmit:

- **skip-conflict**, never preempted: transmitting, the transmit lease or
  automatic transmit armed, an IQ or audio recording being made, a
  recording playing, the band scan, background decoder sessions (they pin
  the span), the CW skimmer, another pass.
- **skip-busy**, left alone: a client-scoped hold - a DAB station playing,
  the AIS or ADS-B map open - or someone listening to the radio. A person
  is using it; Radio does not pull it out from under them automatically.
  Forcing the pass (POST) is the one way to end those: the server ends
  every client-scoped hold through the same path a client's leaving takes
  (Server.end_client_holds, beside Server.client_gone), then the pass is
  recorded.

**The recording.** The receiver is held as AIS holds it
(Engine.hold_receiver; `rxOwner` says so; a tune or a key-up is refused
with a sentence while it holds): the dial and the receiver's centre on the
satellite's nominal frequency, from AOS to LOS, with the antenna the pass
wants (`wxsatAntenna`, else the operator's labels: antenna()). At LOS -
not before - the hold is released, which puts back the dial, mode,
repeater offset and the antenna from before (the hold's `keep`). Nothing
is retuned for Doppler: +-3.4 kHz at 137 MHz is well inside what is
recorded, and following it is the decoder's job, which has the
recording's track of positions to do it with.

The device's own samples (the hold's `feed`) are shifted so the
satellite's frequency is at 0 Hz in the file - the hardware may not sit
exactly there - and decimated by the whole number that brings the rate to
MAX_RATE (1 MS/s) or below: 800 kS/s from the RSPdx's 2.4 MS/s, 1 MS/s
from a 2 MS/s device, as it is from a 1 MS/s one. A whole-number ratio is
ohscore/dsp/multirate.py's decimator, written for exactly this (a Pluto's
receive stream) and measured to 85 dB; a fractional one to exactly 1 MS/s
would be a second resampler for no gain - LRPT is 120 kHz wide and any of
these rates holds it with the Doppler and the tuning error to spare. The
rate is in the file; nothing should assume 1 MS/s.

It is written as the engine's IQ recordings are (ohscore/sigmf.py): SigMF,
ci16_le (complex int16, "cs16" in SoapySDR's words), in Radio's recordings
folder, named as they are (host.recording_name: `...-137.100MHz-Meteor-M-
N2-3-LRPT`), with the engine's own global metadata (_rec_meta: the app,
the device, gain, the station) and `openhamshack:service` naming the
satellite, plus `openhamshack:wxsat` for the decoder: the pass, the
element set it was predicted from, and the decimation.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from pathlib import Path

import numpy as np

from ohscore import sigmf
from ohscore.antennas import parse_labels
from ohscore.countries import locator_position
from ohscore.decoders import Refused, sessions_text
from ohscore.dsp.multirate import Decimator

from ohsradio import wxsat_decode, wxsat_orbit, wxsat_tle
from ohsradio.i18n import _

log = logging.getLogger("ohsradio.wxsat")

SID = "wxsat"                      # the hold's session id (rxOwner.session)
SATELLITES = (
    {"id": "meteor-m2-3", "name": "Meteor-M N2-3", "norad": 57166, "freqHz": 137_100_000, "mode": "LRPT"},
    {"id": "meteor-m2-4", "name": "Meteor-M N2-4", "norad": 59051, "freqHz": 137_900_000, "mode": "LRPT"},
)
BY_ID = {s["id"]: s for s in SATELLITES}
MAX_RATE = 1_000_000.0
MIN_RATE = 250_000.0               # LRPT's 120 kHz, the Doppler and the decimator's edge
TRACK_STEP_S = 10.0
PAST_S = 3600.0                    # how long an ended pass stays in the list
LATE_S = 30.0                      # a pass with less left than this is not started
RECOMPUTE_S = 600.0                # the predicted list is made again this often
KEEP_MARKS_S = 7 * 86_400.0
MATCH_S = 300.0                    # the same pass, though a newer element set moved its AOS
# Holds a person made through a client (Server.end_client_holds ends them):
# the decoder name a DAB station holds under, and the three maps.
CLIENT_SCOPED = ("dab", "ais", "adsb", "aprs")
LIVE = ("recording", "decoding", "done", "failed", "missed", "skip-busy", "skip-conflict")
# A 2 m antenna's label, for antenna(): "2 m", "2m", "VHF", a 2 m or 137
# MHz frequency, a dual-band, or a Diamond X-series vertical's model number
# (X30 ... X7000: every one is 2 m and 70 cm). Matched case-blind.
_TWO_METRE = re.compile(r"\b2\s?m\b|\bvhf\b|\b1(37|4[4-8])(\.\d+)?\s?mhz\b|dual[- ]?band|\bx\d{2,4}\b", re.I)


def _iso(t: float | None) -> str | None:
    return wxsat_tle.iso(t)


class WxSat:
    """The passes, their plans and the recording (module docstring). `clock`
    is Unix time (a test's fake clock)."""
    THUMB_W = wxsat_decode.THUMB_W
    PROJECTED_KINDS = wxsat_decode.PROJECTED_KINDS
    CONTENT_TYPES = wxsat_decode.CONTENT_TYPES

    def __init__(self, radio, clock=time.time, fetch=None, folder: Path | None = None):
        self.radio = radio
        self.clock = clock
        self.dir = Path(folder) if folder is not None else Path(radio.data_dir) / "wxsat"
        self.tle = wxsat_tle.TleStore(self.dir, lambda: bool(radio.st.get("wxsatOnlineTle", True)), clock=clock,
                                      fetch=fetch)
        self.lock = threading.RLock()
        self.job: dict | None = None
        # The server's reasons the receiver is in use, which only it knows
        # (transmit lease, automatic transmit, an audio recording, listeners):
        # callables giving (plan, why) or None. The desktop has none.
        self.probes: list = []
        # Set by the server: ends every client-scoped hold (DAB, AIS, ADS-B,
        # a listen) the way a client's leaving does. None: nothing can.
        self.end_client_holds = None
        # Set by the server: the bytes a recording may take now under the
        # recordings' disk limit and free-space floor (shack_rec's prepare,
        # which makes room by pruning the oldest first), raising with the
        # sentence when there is none. None: only the pass's length limits it.
        self.room = None
        # Set by the server: the recordings' {"limitBytes", "freeBytes",
        # "floorBytes"}, which the pictures obey too (wxsat_decode.py).
        self.disk = None
        self.decoder = wxsat_decode.Decoder(self.dir, self._decoded, disk=lambda: self.disk() if self.disk else None)
        self.marks: dict[str, dict] = self._load_marks()
        self._cache: dict | None = None
        self.error: str | None = None

    # ------------------------------------------------------------ disk
    def _marks_path(self) -> Path:
        return self.dir / "passes.json"

    def _load_marks(self) -> dict:
        try:
            got = json.loads(self._marks_path().read_text(encoding="utf-8"))
            return {k: v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_marks(self) -> None:
        now = self.clock()
        self.marks = {k: v for k, v in self.marks.items() if float(v.get("los", 0)) > now - KEEP_MARKS_S}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self._marks_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(self.marks, indent=1), encoding="utf-8")
            os.replace(tmp, self._marks_path())
        except OSError:
            log.warning("weather satellites: could not keep the pass plans", exc_info=True)

    # ------------------------------------------------------------ settings
    def station(self) -> tuple[float, float] | None:
        return locator_position(str(self.radio.st.get("locator") or ""))

    def enabled_sats(self) -> set[str]:
        raw = str(self.radio.st.get("wxsatSatellites", "") or "")
        return {s.strip() for s in raw.split(",") if s.strip() in BY_ID}

    def antenna(self) -> str:
        """The receiver input a pass is recorded on: `wxsatAntenna` (an input
        name, or one of the operator's labels for one), else the input whose
        label says 2 m (_TWO_METRE), else '' - the operator's own, unchanged.
        Only inputs the open device has."""
        r = self.radio
        dev = getattr(r, "dev", None)
        try:
            inputs = list(getattr(dev, "antennas", None) or [])
        except Exception:  # noqa: BLE001 - a device that cannot list them has none to choose
            inputs = []
        labels = parse_labels(str(r.st.get("soapyAntennaLabels", "") or ""))
        want = str(r.st.get("wxsatAntenna", "") or "").strip()
        if want:
            if want in inputs:
                return want
            for name, label in labels.items():
                if label.strip().lower() == want.lower() and name in inputs:
                    return name
            return ""
        for name in inputs:
            if _TWO_METRE.search(labels.get(name, "")):
                return name
        return ""

    # ------------------------------------------------------------ prediction
    def _sets(self) -> dict[int, dict]:
        return self.tle.elements([s["norad"] for s in SATELLITES], str(self.radio.st.get("wxsatTle", "") or ""))

    def _predict(self, now: float, hours: float) -> tuple[list[dict], dict]:
        """(passes from PAST_S ago to `hours` ahead, the element sets used),
        made again when the sets, the station or the window changed, and
        every RECOMPUTE_S."""
        stn = self.station()
        sets = self._sets()
        key = (stn, tuple(sorted((n, s["l1"], s["l2"]) for n, s in sets.items())))
        c = self._cache
        if c is not None and c["key"] == key and c["start"] <= now - PAST_S and c["end"] >= now + hours * 3600 \
                and now - c["made"] < RECOMPUTE_S:
            return c["passes"], sets
        out = []
        self.error = None
        if stn is not None:
            start, end = now - PAST_S, now + max(hours, 48.0) * 3600.0
            for sat in SATELLITES:
                s = sets.get(sat["norad"])
                if s is None:
                    continue
                try:
                    orb = wxsat_orbit.Orbit(s["l1"], s["l2"])
                    found = wxsat_orbit.passes(orb, stn[0], stn[1], start, end)
                except ImportError as e:
                    # No sgp4 (a desktop package carries none): no passes, and why.
                    self.error = str(e)
                    break
                for p in found:
                    out.append(dict(p, sat=sat, orbit=orb, tle=s,
                                    id=f"{sat['id']}-{time.strftime('%Y%m%dT%H%MZ', time.gmtime(p['aos']))}"))
            out.sort(key=lambda p: p["aos"])
            self._cache = {"key": key, "start": start, "end": end, "made": now, "passes": out}
        else:
            self._cache = None
        return out, sets

    def _mark(self, p: dict) -> dict | None:
        m = self.marks.get(p["id"])
        if m is not None:
            return m
        for m in self.marks.values():
            if m.get("sat") == p["sat"]["id"] and abs(float(m.get("aos", 0)) - p["aos"]) < MATCH_S:
                return m
        return None

    def _mark_for(self, p: dict) -> dict:
        m = self._mark(p)
        if m is None:
            m = self.marks[p["id"]] = {}
        m.update(sat=p["sat"]["id"], aos=p["aos"], los=p["los"])
        return m

    def plan(self, p: dict, now: float) -> tuple[str, str | None]:
        """(plan, why) for pass `p` now (module docstring)."""
        m = self._mark(p) or {}
        if m.get("plan") in LIVE:
            return m["plan"], m.get("why")
        if m.get("skipped"):
            return "skip-disabled", _("Skipped by hand")
        st = self.radio.st
        if not m.get("forced"):
            if p["sat"]["id"] not in self.enabled_sats():
                return "skip-disabled", _("{sat} is switched off in the weather satellite settings").format(
                    sat=p["sat"]["name"])
            if not st.get("wxsatAuto", True):
                return "skip-disabled", _("Automatic recording of weather satellites is off")
            low = int(st.get("wxsatMinElevDeg", 15))
            if p["maxEl"] < low:
                return "skip-low", _("It rises only to {el:.0f}°, below the {low}° minimum").format(
                    el=p["maxEl"], low=low)
        if p["los"] <= now:
            return "missed", _("Radio was not running for this pass")
        return "record", None

    def _pass_view(self, p: dict, now: float) -> dict:
        plan, why = self.plan(p, now)
        m = self._mark(p) or {}
        sat = p["sat"]
        return {"id": p["id"], "sat": sat["name"], "freqHz": sat["freqHz"], "mode": sat["mode"],
                "aos": _iso(p["aos"]), "tca": _iso(p["tca"]), "los": _iso(p["los"]),
                "maxElDeg": round(p["maxEl"], 1), "aosAzDeg": round(p["aosAz"], 1), "losAzDeg": round(p["losAz"], 1),
                "track": [{"t": _iso(t), "az": round(az, 1), "el": round(el, 1) + 0.0}     # never "-0.0" at AOS
                          for t, az, el in wxsat_orbit.track(p["orbit"], *self.station(), p["aos"], p["los"],
                                                              TRACK_STEP_S)],
                "plan": plan, "why": why, "imageId": m.get("imageId")}

    def passes_view(self, hours: float = 48.0) -> dict:
        now = self.clock()
        with self.lock:
            found, sets = self._predict(now, hours)
            stn = self.station()
            rows = [self._pass_view(p, now) for p in found if p["los"] > now - PAST_S and p["aos"] < now + hours * 3600]
        return {"station": {"lat": round(stn[0], 5) if stn else None, "lon": round(stn[1], 5) if stn else None},
                "tle": self.tle.view(sets, now),
                "minElevDeg": int(self.radio.st.get("wxsatMinElevDeg", 15)),
                "passes": rows}

    def _find(self, pass_id: str, now: float) -> dict | None:
        found, _sets = self._predict(now, 48.0)
        return next((p for p in found if p["id"] == pass_id), None)

    # ------------------------------------------------------------ who has the receiver
    def busy(self) -> tuple[str, str] | None:
        """("skip-conflict" | "skip-busy", why) while something else has
        the receiver; None while it is free (module docstring)."""
        r = self.radio
        st = r.st
        if self.job is not None:
            return "skip-conflict", _("Another weather satellite pass is being recorded")
        tx = getattr(r, "tx_thread", None)
        if st.get("keyed") or (tx is not None and tx.is_alive()):
            return "skip-conflict", _("Radio is transmitting")
        busy = None
        for probe in list(self.probes):
            try:
                got = probe()
            except Exception:  # noqa: BLE001 - a probe that fails says nothing
                got = None
            if got and got[0] == "skip-conflict":
                return got
            busy = busy or got
        if getattr(r, "rec", None) is not None:
            return "skip-conflict", _("An IQ recording is being made")
        if getattr(r, "play", None) is not None:
            return "skip-conflict", _("A recording is playing")
        scan = getattr(r, "bandscan", None)
        h = r.held
        if (scan is not None and scan.thread is not None and scan.thread.is_alive()) or \
                (h is not None and h.get("by") == "scan"):
            return "skip-conflict", _("The band scan has the receiver")
        if h is not None and h.get("by") not in CLIENT_SCOPED:
            return "skip-conflict", _("{what} has the receiver").format(what=h.get("block") or h.get("by"))
        pinning = r.decoders.pinned_by() if getattr(r, "PINS_SPAN", False) else []
        if pinning:
            return "skip-conflict", _("Background decoders hold the receiver: {sessions}").format(
                sessions=sessions_text(pinning))
        if st.get("cwSkim"):
            return "skip-conflict", _("The CW skimmer is running")
        if h is not None:
            return "skip-busy", {"dab": _("A DAB station is playing"),
                                 "ais": _("The ship map (AIS) is open"),
                                 "adsb": _("The aircraft map (ADS-B) is open")}[h["by"]]
        return busy

    # ------------------------------------------------------------ what a client asks
    def force(self, pass_id: str) -> dict:
        """Record pass `pass_id` whatever its plan; one already in the sky
        starts now, ending client-scoped holds first. Raises Refused
        (code, sentence) when it cannot: unknown or over, or the receiver
        is held by something a pass never preempts."""
        with self.lock:
            now = self.clock()
            p = self._find(pass_id, now)
            if p is None:
                raise Refused("unknown_pass", _("There is no pass {id}").format(id=pass_id))
            if p["los"] - LATE_S <= now:
                raise Refused("pass_over", _("That pass is over"))
            if self.job is not None and self.job["pass"]["id"] == p["id"]:
                return self._pass_view(p, now)
            verdict = self.busy()
            if verdict is not None and verdict[0] == "skip-conflict":
                raise Refused("receiver_busy", verdict[1])
            m = self._mark_for(p)
            m.pop("skipped", None)
            if m.get("plan") in ("skip-busy", "skip-conflict"):
                m.pop("plan", None)
                m.pop("why", None)
            m["forced"] = True
            if p["aos"] <= now:
                self._start(p, forced=True)
                if self.job is None:
                    why = m.get("why") or _("The receiver could not be taken")
                    m.pop("plan", None)
                    self._save_marks()
                    raise Refused("receiver_busy", why)
            self._save_marks()
            return self._pass_view(p, now)

    def skip(self, pass_id: str) -> dict:
        """Skip pass `pass_id`; one being recorded stops now, the receiver
        given back as it was."""
        with self.lock:
            now = self.clock()
            p = self._find(pass_id, now)
            if p is None:
                raise Refused("unknown_pass", _("There is no pass {id}").format(id=pass_id))
            if self.job is not None and self.job["pass"]["id"] == p["id"]:
                self._finish("skip-disabled", _("Skipped by hand"))
            m = self._mark_for(p)
            m["skipped"] = True
            m.pop("forced", None)
            if m.get("plan") in ("skip-busy", "skip-conflict", "missed"):
                m.pop("plan", None)
                m.pop("why", None)
            self._save_marks()
            return self._pass_view(p, now)

    # ------------------------------------------------------------ the supervisor
    def due(self, now: float | None = None, ahead_s: float = 60.0) -> bool:
        """Whether a pass is being recorded, or one to record rises within
        `ahead_s`: the server keeps (or takes back) the radio for it."""
        now = self.clock() if now is None else now
        with self.lock:
            if self.job is not None:
                return True
            try:
                found, _sets = self._predict(now, 1.0)
            except Exception:  # noqa: BLE001 - a prediction that fails keeps nothing awake
                return False
            return any(p["aos"] - ahead_s <= now < p["los"] - LATE_S and self.plan(p, now)[0] == "record"
                       for p in found)

    def tick(self) -> None:
        """Ten times a second while the radio runs: start a pass at AOS,
        end it at LOS."""
        r = self.radio
        with self.lock:
            now = self.clock()
            job = self.job
            if job is not None:
                held = r.held
                if not r.running:
                    self._finish("failed", _("The radio stopped during the pass"))
                elif held is None or held.get("session") != SID:
                    self._finish("failed", _("The receiver was taken back during the pass"))
                elif job["rec"].closing:
                    rec = job["rec"]
                    self._finish("failed", rec.error or (_("The recordings' disk limit stopped it before LOS")
                                                         if rec.reason == "time limit" else
                                                         _("The recording stopped early")))
                elif now >= job["pass"]["los"]:
                    self._finish("done", None)
                return
            if not r.running or self.station() is None:
                return
            found, _sets = self._predict(now, 1.0)
            for p in found:
                if not (p["aos"] <= now < p["los"] - LATE_S):
                    continue
                if self.plan(p, now)[0] != "record":
                    continue
                self._start(p, forced=bool((self._mark(p) or {}).get("forced")))
                break

    def _start(self, p: dict, forced: bool) -> None:
        """Take the receiver for pass `p` and start its recording, or mark
        why not (called under the lock)."""
        r = self.radio
        m = self._mark_for(p)
        verdict = self.busy()
        if verdict is not None and verdict[0] == "skip-busy" and forced and self.end_client_holds is not None:
            try:
                ended = self.end_client_holds(_("A weather satellite pass was recorded by hand"))
                log.info("weather satellites: %s forced: ended %s", p["id"], ", ".join(ended) or "nothing")
            except Exception:  # noqa: BLE001 - what could not be ended is judged again below
                log.warning("weather satellites: ending client holds failed", exc_info=True)
            verdict = self.busy()
            # Someone still listening is no reason to refuse a pass forced by hand.
            if verdict is not None and verdict[0] == "skip-busy" and r.held is None:
                verdict = None
        if verdict is not None:
            m.update(plan=verdict[0], why=verdict[1])
            self._save_marks()
            log.info("weather satellites: %s not recorded (%s): %s", p["id"], verdict[0], verdict[1])
            return
        sat = p["sat"]
        freq = float(sat["freqHz"])
        try:
            r.hold_receiver(SID, "wxsat", freq, sat["name"], MIN_RATE, feed=self._feed, keep=("soapyAntenna",),
                            texts=self.texts(sat["name"]))
        except Refused as e:
            m.update(plan="skip-conflict", why=str(e))
            self._save_marks()
            return
        ant = self.antenna()
        if ant and ant != r.st.get("soapyAntenna"):
            try:
                r.set(soapyAntenna=ant)
            except ValueError as e:
                log.warning("weather satellites: antenna %s not taken: %s", ant, e)
        fs = float(r.geo.fs)
        dec = max(1, math.ceil(fs / MAX_RATE - 1e-9))
        out_fs = fs / dec
        now_real = time.time()
        limit_s = max(60.0, p["los"] - self.clock() + 60.0)
        if self.room is not None:
            # The same disk rules as every recording here: a pass is 12-15
            # minutes, about 3 GB at 800 kS/s, and must never be what fills
            # the disk. What does not fit is cut short, and says so at LOS.
            try:
                limit_s = min(limit_s, float(self.room()) / sigmf.bytes_per_second(out_fs))
            except Exception as e:  # noqa: BLE001 - shack_rec's Refused (no room) and anything else alike
                r.release_receiver(SID)
                m.update(plan="failed", why=_("Could not record: {error}").format(error=getattr(e, "text", None) or e))
                self._save_marks()
                log.warning("weather satellites: %s not recorded: %s", p["id"], e)
                return
        station = {"kind": "wxsat", "mode": sat["mode"], "label": sat["name"], "freqHz": freq,
                   "satellite": sat["name"], "norad": sat["norad"], "passId": p["id"]}
        try:
            meta = r._rec_meta(r.state(), station)
            meta["openhamshack:wxsat"] = {
                "passId": p["id"], "satellite": sat["name"], "norad": sat["norad"], "nominalHz": freq,
                "aos": _iso(p["aos"]), "tca": _iso(p["tca"]), "los": _iso(p["los"]),
                "maxElDeg": round(p["maxEl"], 2), "tle": [p["tle"]["name"], p["tle"]["l1"], p["tle"]["l2"]],
                "tleSource": p["tle"]["source"], "deviceRate": fs, "decimation": dec,
                "antenna": r.st.get("soapyAntenna") or None, "forced": forced}
            base = sigmf.new_base(r.recordings_dir(), r.CONFIG.app.name, now_real, freq, sat["mode"], station)
            rec = sigmf.Recorder(base, out_fs, meta, limit_s=max(1.0, limit_s)).start()
        except (OSError, ValueError) as e:
            r.release_receiver(SID)
            m.update(plan="failed", why=_("Could not record: {error}").format(error=e))
            self._save_marks()
            log.warning("weather satellites: %s not recorded: %s", p["id"], e)
            return
        self.job = {"pass": p, "rec": rec, "dec": Decimator(dec) if dec > 1 else None, "fs": fs, "phase": 0.0,
                    "freq": freq, "started": self.clock()}
        m.update(plan="recording", why=None, file=rec.data_path.name)
        self._save_marks()
        log.info("weather satellites: recording %s on %.3f MHz at %.0f S/s to %s", p["id"], freq / 1e6, out_fs,
                 rec.data_path.name)

    # ------------------------------------------------------------ decoding (wxsat_decode.py)
    def _decode_job(self, pass_id: str, m: dict, data: Path) -> dict:
        """What the decoder needs, from the recording's own metadata (the
        rate it was made at, the element set the pass was predicted from)
        so a pass resumed after a restart is decoded exactly as it would
        have been."""
        meta = json.loads(sigmf.paths(data)[1].read_text(encoding="utf-8"))["global"]
        wx = meta.get("openhamshack:wxsat") or {}
        return {"passId": pass_id, "sat": wx.get("satellite") or BY_ID.get(m.get("sat"), {}).get("name", ""),
                "aos": wx.get("aos") or _iso(m.get("aos")), "maxElDeg": round(float(wx.get("maxElDeg") or 0.0), 1),
                "data": str(data), "rate": float(meta["core:sample_rate"]), "tle": list(wx.get("tle") or [])}

    def resume_decoding(self) -> None:
        """Radio started: decode again every pass left `decoding` when it
        last stopped, failed with why when its recording is gone."""
        with self.lock:
            for pid, m in sorted(self.marks.items(), key=lambda kv: float(kv[1].get("los", 0))):
                if m.get("plan") != "decoding":
                    continue
                data = self.radio.recordings_dir() / str(m.get("file") or "")
                try:
                    job = self._decode_job(pid, m, data) if m.get("file") and data.is_file() else None
                except (OSError, ValueError, KeyError):
                    job = None
                if job is None:
                    m.update(plan="failed", why=_("The recording was deleted before it could be decoded"))
                elif not self.decoder.available():
                    m.update(plan="done", why=None)
                else:
                    self.decoder.submit(job)
            self._save_marks()

    def _decoded(self, job: dict, plan: str, why: str | None, image_id: str | None) -> None:
        """The decoder's thread: a pass decoded, or why not."""
        with self.lock:
            m = self.marks.get(job["passId"])
            if m is None:           # kept a week: only a decode a week late finds none
                return
            m.update(plan=plan, why=why)
            if image_id:
                m["imageId"] = image_id
            self._save_marks()
        log.info("weather satellites: %s decoded: %s (%s)", job["passId"], plan, why or image_id)

    def images_view(self) -> list[dict]:
        return self.decoder.images.listing()

    def composite_view(self, kind: str, hours: float) -> dict:
        since = _iso(self.clock() - hours * 3600.0)
        return {"frames": self.decoder.images.composite(kind, since)}

    def image_file(self, image_id: str, product: str, thumb: bool, ext: str = "jpg") -> bytes | None:
        return self.decoder.images.file(image_id, product, thumb, ext)

    def radio_stopped(self) -> None:
        """The radio is stopping: a pass being recorded ends here, with the
        receiver given back while the radio still runs (Radio.stop)."""
        with self.lock:
            if self.job is not None:
                self._finish("failed", _("The radio stopped during the pass"))

    def _finish(self, plan: str, why: str | None) -> None:
        """End the recording and give the receiver back - the dial, mode
        and antenna from before (called under the lock)."""
        job, self.job = self.job, None
        if job is None:
            return
        rec = job["rec"]
        rec.close(why or "")
        h = self.radio.held
        if h is not None and h.get("session") == SID:
            self.radio.release_receiver(SID)
        rec.wait(10.0)
        if plan == "done" and (rec.error or rec.written == 0):
            plan, why = "failed", rec.error or _("Nothing was received")
        m = self._mark_for(job["pass"])
        m.update(plan=plan, why=why, file=rec.data_path.name, seconds=round(rec.seconds, 1))
        if plan == "done" and self.decoder.available():
            try:
                self.decoder.submit(self._decode_job(job["pass"]["id"], m, rec.data_path))
                m["plan"] = "decoding"
            except (OSError, ValueError, KeyError) as e:
                log.warning("weather satellites: %s cannot be decoded: %s", job["pass"]["id"], e)
                m.update(plan="failed", why=_("The recording's metadata could not be read: {error}").format(error=e))
        self._save_marks()
        log.info("weather satellites: %s %s (%s): %.0f s in %s", job["pass"]["id"], plan, why or "-", rec.seconds,
                 rec.data_path.name)

    def _feed(self, raw, settled: bool) -> None:
        """The receive thread, once per block, while the pass holds the
        receiver: the satellite's frequency to 0 Hz, decimated, to the file."""
        job = self.job
        r = self.radio
        if job is None or not settled or r.centre is None:
            return
        x = np.asarray(raw, np.complex64)
        n = len(x)
        fs = job["fs"]
        off = job["freq"] - float(r.centre)
        if off:
            step = -2.0 * math.pi * off / fs
            ph = job["phase"] + step * np.arange(n)
            x = x * np.exp(1j * ph).astype(np.complex64)
            job["phase"] = float((job["phase"] + step * n) % (2.0 * math.pi))
        y = job["dec"](x) if job["dec"] is not None else x
        if not len(y):
            return
        dev = float(r.rx_if) + off if getattr(r, "rx_if", None) is not None else job["freq"]
        job["rec"].push(y, (dev, job["freq"]), time.time() - n / fs)

    # ------------------------------------------------------------ views
    def texts(self, name: str) -> dict:
        return {"tune": _("The receiver is recording a {sat} pass: skip the pass to tune or change mode").format(
                    sat=name),
                "transmit": _("The receiver is recording a {sat} pass: skip the pass to transmit").format(sat=name),
                "on_air": _("Not while transmitting: a weather satellite pass takes the receiver to 137 MHz"),
                "busy": _("A {sat} pass has the receiver: skip it first").format(sat=name)}

    def status_view(self) -> dict:
        """GET api/wxsat/status. A pass recording wins; else the pass
        SatDump is decoding (`decoding`, `etaS` null: SatDump says nothing
        while it works that would make one honest); else the next pass.
        snrDb, lockPct and lines stay null: SatDump's CLI reports them only
        in its log as it goes, and the pass's result is the picture."""
        now = self.clock()
        out = {"state": "idle", "passId": None, "sat": None, "freqHz": None, "az": None, "el": None,
               "snrDb": None, "lockPct": None, "lines": None, "etaS": None, "text": _("No pass is planned")}
        with self.lock:
            job = self.job
            stn = self.station()
            if job is not None and stn is not None:
                p = job["pass"]
                az, el = p["orbit"].look(now, *stn)
                out.update(state="recording", passId=p["id"], sat=p["sat"]["name"], freqHz=p["sat"]["freqHz"],
                           az=round(az, 1), el=round(el, 1), etaS=max(0, round(p["los"] - now)),
                           text=_("Recording {sat} until {los} UTC").format(
                               sat=p["sat"]["name"], los=time.strftime("%H:%M", time.gmtime(p["los"]))))
                return out
            cur = self.decoder.current
            if cur is not None:
                out.update(state="decoding", passId=cur["passId"], sat=cur["sat"],
                           freqHz=next((s["freqHz"] for s in SATELLITES if s["name"] == cur["sat"]), None),
                           text=_("Decoding the {sat} pass of {aos} UTC").format(
                               sat=cur["sat"], aos=str(cur["aos"])[11:16]))
                return out
            if self.error:
                out["text"] = _("Passes cannot be predicted: {error}").format(error=self.error)
                return out
            if stn is None:
                out["text"] = _("Set the station's locator to predict passes")
                return out
            found, _sets = self._predict(now, 48.0)
            nxt = next((p for p in found if p["los"] - LATE_S > now and self.plan(p, now)[0] == "record"), None)
        if nxt is not None:
            az, el = nxt["orbit"].look(now, *stn)
            out.update(state="waiting", passId=nxt["id"], sat=nxt["sat"]["name"], freqHz=nxt["sat"]["freqHz"],
                       az=round(az, 1), el=round(el, 1), etaS=max(0, round(nxt["aos"] - now)),
                       text=_("Next: {sat} at {aos} UTC").format(
                           sat=nxt["sat"]["name"], aos=time.strftime("%H:%M", time.gmtime(nxt["aos"]))))
        return out
