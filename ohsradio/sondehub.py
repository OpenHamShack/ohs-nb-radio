"""SondeHub for Radio's radiosondes (29/10/2026; docs/SERVER-API.md
"Radiosondes"): the telemetry upload, the launch sites, and Tawhiri's
burst and landing predictions.

    hub = SondeHub(folder, upload_on=..., online_on=..., station=...)
    hub.add(reading)          # a decoded frame (sonde.reading), queued for upload
    hub.predict(sonde)        # ask Tawhiri about a sonde in flight, in the background
    hub.prediction(serial)    # the last answer, or None
    hub.launches(lat, lon)    # upcoming launches near a place, from the cached site list
    hub.view()                # {"enabled", "lastUploadUtc", "error"}
    hub.step(now)             # one turn of the background thread (a test calls it)

Brian's rule for anything that reaches the internet: **offline, nothing
changes** (flightroutes.py, dmrids.py). Radio decodes, lists, maps and
predicts radiosondes with no route out; SondeHub only adds to that. No
route out, a timeout, a server error or the setting off all end the same
way: nothing on the operator's screen, at most one log line per cause, and
the next try later. `error` in `view()` says only what the operator can
act on: SondeHub refusing what was sent (a 4xx), or no callsign or
locator to send it under - never "offline".

**The upload** is the one radiosonde_auto_rx makes (its sondehub.py, v1.9.0,
GPL-3, read and followed field for field): a list of telemetry objects in
SondeHub's "universal" format, gzip-compressed JSON, PUT to
https://api.v2.sondehub.org/sondes/telemetry every UPLOAD_EVERY_S seconds
(auto_rx's default sondehub_upload_rate), with the station's details in
each object. The station itself is PUT to /listeners every
LISTENER_EVERY_S (auto_rx's six hours) while frames are being sent, so the
station shows on SondeHub's map. The setting `sondeHubUpload` (on by
default, as auto_rx asks every station to leave it) off means no traffic
at all and the queue emptied.

**Where the station is said to be: only the centre of its 6-character
Maidenhead locator** (Brian, 29/10/2026), never the profile's own
position: IO75RL is sent as 55.4792 N, 4.5417 W wherever in its 5 by 9 km
the station stands. An 8-character locator is cut to 6 first; a
4-character one is sent as its square's centre, coarser still. The
altitude sent is 0: SondeHub's format wants three numbers, and a real
height would say more than the locator does.

**Launches** are SondeHub's public site list (GET /sites: every launch
site with its daily UTC launch times, usual radiosonde type and
frequency, and typical ascent, burst and descent), fetched at most once a
day, kept in the data folder and read from there, so a restart or an
offline day still lists what was last known. `[]` when it has never been
fetched.

**Predictions** are SondeHub's Tawhiri instance (GET /tawhiri), the same
predictor the SondeHub tracker draws with: from where the sonde is now,
its climb, and a burst altitude (the nearest site's typical burst, else
BURST_DEFAULT_M), the ascent ends at the predicted burst and the descent
at the predicted landing. Its answer is `{"prediction": [{"stage":
"ascent", "trajectory": [{"altitude", "datetime", "latitude",
"longitude"}...]}, {"stage": "descent", ...}], "request", "metadata",
"warnings"}` with longitudes 0-360 (checked against the live service,
29/10/2026). Asked at most once a PREDICT_EVERY_S per sonde, only for
the sonde being decoded, in the background; sonde.py's ballistic estimate
stands until (or unless) an answer comes.

**What goes out**: the decoded frames (what the sonde itself broadcast),
the station's callsign and locator centre, and the User-Agent
"OpenHamShack-Radio/<version>"; to Tawhiri, a sonde's position, climb and
time; to /sites, nothing. No cookies, no station position beyond the
locator.

**Nothing here blocks a caller.** `add`, `predict` and `launches` read or
append under a lock; the network is touched only by `step`, on one
daemon thread started for the program an operator runs (`start`), never
by a test's throw-away radio.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path

from ohscore.countries import distance_bearing, locator_position

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.sondehub")

BASE_URL = "https://api.v2.sondehub.org"
UPLOAD_EVERY_S = 15.0           # auto_rx's sondehub_upload_rate default
LISTENER_EVERY_S = 6 * 3600.0   # auto_rx's user_position_update_rate, hours
HTTP_TIMEOUT_S = 20.0
QUEUE_MAX = 600                 # ten minutes of one frame a second: more is dropped, oldest first
SITES_EVERY_S = 24 * 3600.0
SITES_RETRY_S = 3600.0
PREDICT_EVERY_S = 60.0
PREDICT_RETRY_S = 300.0
MAX_BYTES = 8 << 20             # /sites is about 300 kB uncompressed
LAUNCH_RADIUS_KM = 400.0
LAUNCH_HOURS = 24.0
BURST_DEFAULT_M = 26_000.0      # a typical 400 MHz synoptic flight's burst
DESCENT_DEFAULT_MS = 5.0        # a typical parachute's descent at sea level
SITE_NEAR_KM = 50.0             # a sonde first heard this close to a site came from it

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"

# WMO radiosonde type codes (BUFR table 0 02 011) SondeHub's sites list
# carries, as names for a client. Only the one every UK site uses and that
# its own listing pairs with a 400 MHz frequency is named; any other code
# is passed on as "WMO <code>" rather than guessed.
WMO_TYPES = {"41": "RS41"}


class Unusable(ValueError):
    """An answer that is not what was asked for (too long, not the shape):
    handled as offline is, never shown."""


def user_agent() -> str:
    """The program and its version, nothing else (as flightroutes.py)."""
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        version = "0"
    return f"OpenHamShack-Radio/{version}"


def version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "0"


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def station_position(locator: str) -> tuple[float, float] | None:
    """Where the station is said to be (module docstring): the centre of
    the first six characters of its locator, or of a four-character one.
    countries.locator_position gives a square's centre, not its corner."""
    loc = (locator or "").strip()
    if len(loc) >= 6:
        loc = loc[:6]
    elif len(loc) != 4:
        return None
    pos = locator_position(loc)
    if pos is None:
        return None
    return round(pos[0], 4), round(pos[1], 4)


def air_density(alt_m: float) -> float:
    """Air density at `alt_m`, kg/m3: NASA Glenn's simple atmosphere, the
    model SondeHub's own predictor (its predict.py get_density) uses."""
    a = float(alt_m)
    if a > 25000:
        temp = -131.21 + 0.00299 * a
        p = 2.488 * ((temp + 273.1) / 216.6) ** -11.388
    elif a > 11000:
        temp = -56.46
        p = 22.65 * pow(2.718281828459045, 1.73 - 0.000157 * a)
    else:
        temp = 15.04 - 0.00649 * a
        p = 101.29 * ((temp + 273.1) / 288.08) ** 5.256
    return p / (0.2869 * (temp + 273.1))


def sea_level_descent(rate_ms: float, alt_m: float) -> float:
    """The sea-level descent rate of a parachute falling at `rate_ms` at
    `alt_m` (drag balances weight, so speed goes as 1/sqrt(density)):
    what Tawhiri's descent_rate means. SondeHub's seaLevelDescentRate."""
    return abs(float(rate_ms)) * (air_density(alt_m) / 1.22) ** 0.5


def _lon180(lon: float) -> float:
    return ((float(lon) + 180.0) % 360.0) - 180.0


def parse_tawhiri(doc) -> dict | None:
    """Tawhiri's answer (module docstring) as {"burst": {lat, lon, altM,
    predicted}, "landing": {lat, lon, utc}}, either None when its stage
    is missing; None for an error or any shape that is not a prediction."""
    if not isinstance(doc, dict) or not isinstance(doc.get("prediction"), list):
        return None
    out = {"burst": None, "landing": None}
    for stage in doc["prediction"]:
        tr = stage.get("trajectory") if isinstance(stage, dict) else None
        if not tr or not isinstance(tr[-1], dict):
            continue
        p = tr[-1]
        try:
            lat, lon, alt = float(p["latitude"]), _lon180(p["longitude"]), float(p["altitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if stage.get("stage") == "ascent":
            out["burst"] = {"lat": round(lat, 5), "lon": round(lon, 5), "altM": round(alt), "predicted": True}
        elif stage.get("stage") == "descent":
            out["landing"] = {"lat": round(lat, 5), "lon": round(lon, 5), "utc": str(p.get("datetime") or "")
                              or None}
    if out["burst"] is None and out["landing"] is None:
        return None
    return out


def upcoming_launches(sites: dict, lat: float, lon: float, now: float, radius_km: float = LAUNCH_RADIUS_KM,
                      hours: float = LAUNCH_HOURS) -> list[dict]:
    """Every launch in the next `hours` from a site within `radius_km` of
    (lat, lon), soonest first. A site's `times` are daily UTC times
    ("H:MM:SS"); a site with none launches only now and then (a firing
    range) and is left out."""
    out = []
    day0 = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for sid, s in (sites or {}).items():
        if not isinstance(s, dict):
            continue
        try:
            slon, slat = float(s["position"][0]), float(s["position"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        km, brg = distance_bearing(lat, lon, slat, slon)
        if km > radius_km:
            continue
        types, freq = [], None
        for t in s.get("rs_types") or []:
            code, f = (t[0], t[1]) if isinstance(t, (list, tuple)) and len(t) >= 2 else (t, None)
            name = WMO_TYPES.get(str(code), f"WMO {code}")
            if name not in types:
                types.append(name)
            if freq is None and f is not None:
                try:
                    freq = round(float(f) * 1e6)
                except (TypeError, ValueError):
                    pass
        for hms in s.get("times") or []:
            try:
                h, m, sec = (int(x) for x in str(hms).split(":"))
            except ValueError:
                continue
            for d in (0, 1, 2):
                t = day0.timestamp() + d * 86400 + h * 3600 + m * 60 + sec
                if now <= t <= now + hours * 3600:
                    out.append({"site": str(s.get("station") or sid), "name": s.get("station_name") or str(sid),
                                "lat": slat, "lon": slon, "altM": s.get("alt"), "distanceKm": round(km, 1),
                                "bearingDeg": round(brg, 1), "utc": _iso(t), "types": types, "freqHz": freq,
                                "burstAltM": s.get("burst_altitude"), "ascentMs": s.get("ascent_rate"),
                                "descentMs": s.get("descent_rate")})
    out.sort(key=lambda v: (v["utc"], v["distanceKm"]))
    return out


def nearest_site(sites: dict, lat: float, lon: float, within_km: float = SITE_NEAR_KM) -> dict | None:
    best = None
    for s in (sites or {}).values():
        try:
            slon, slat = float(s["position"][0]), float(s["position"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        km, _b = distance_bearing(lat, lon, slat, slon)
        if km <= within_km and (best is None or km < best[0]):
            best = (km, s)
    return best[1] if best else None


class SondeHub:
    """The upload queue, the site list and the predictions (module
    docstring). `upload_on`, `online_on`: callables, the settings now;
    `station`: a callable giving (callsign, locator)."""

    def __init__(self, folder: Path | None, upload_on, online_on, station, base_url: str = BASE_URL,
                 opener=None):
        self.folder = folder
        self.upload_on = upload_on
        self.online_on = online_on
        self.station = station
        self.base_url = base_url.rstrip("/")
        # No cookie handler, no proxy surprises beyond the environment's.
        self.opener = opener or urllib.request.build_opener()
        self.lock = threading.Lock()
        self.queue: deque = deque(maxlen=QUEUE_MAX)
        self.subframes_sent: set[str] = set()
        self.last_upload: float | None = None
        self.uploaded_at = 0.0
        self.listener_at = 0.0
        self.error: str | None = None
        self.sites: dict = {}
        self.sites_at = 0.0
        self.sites_tried = 0.0
        self.sites_wanted = False
        self.predictions: dict[str, dict] = {}       # serial -> {"at", "result"}
        self.pending: dict[str, dict] = {}           # serial -> the Tawhiri query to make
        self.asked: dict[str, float] = {}            # serial -> when last asked (or failed)
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self._logged: set[str] = set()
        self._load_sites()

    # -- the thread ------------------------------------------------------------
    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="sondehub", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()

    def _run(self) -> None:
        while not self.stop_ev.wait(1.0):
            try:
                self.step(time.time())
            except Exception:  # noqa: BLE001 - a turn that fails costs that turn
                log.warning("SondeHub: a turn failed", exc_info=True)

    def step(self, now: float) -> None:
        """One turn: an upload when due, one prediction asked, the site
        list when wanted and stale. Each is a no-op offline or switched off."""
        if now - self.uploaded_at >= UPLOAD_EVERY_S:
            self.uploaded_at = now
            self.flush(now)
        with self.lock:
            serial, query = next(iter(self.pending.items()), (None, None))
            if serial is not None:
                del self.pending[serial]
        if serial is not None:
            self._predict_now(serial, query, now)
        if self.sites_wanted and self.online_on() and now - self.sites_at >= SITES_EVERY_S \
                and now - self.sites_tried >= SITES_RETRY_S:
            self.refresh_sites(now)

    def _quiet(self, key: str, msg: str, *args) -> None:
        """One log line per cause, not one per try (module docstring)."""
        if key not in self._logged:
            self._logged.add(key)
            log.info(msg, *args)

    def _request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None,
                 query: dict | None = None):
        url = self.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        h = {"User-Agent": user_agent(), "Accept-Encoding": "gzip", **(headers or {})}
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        with self.opener.open(req, timeout=HTTP_TIMEOUT_S) as r:
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise Unusable()
            # SondeHub's API gateway compresses whether asked or not.
            if r.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return r.status, raw

    # -- the upload ------------------------------------------------------------
    def add(self, reading: dict) -> None:
        """A decoded frame (sonde.reading's dict) to upload, if the setting
        is on and the frame is one auto_rx would send."""
        if not self.upload_on():
            return
        tel = self.telemetry(reading)
        if tel is not None:
            with self.lock:
                self.queue.append(tel)

    def telemetry(self, rd: dict) -> dict | None:
        """auto_rx's reformat_data: one object of SondeHub's universal
        format, without the station's fields (flush adds them)."""
        if rd.get("encrypted") or rd.get("lat") is None:
            return None
        out = {"datetime": rd["datetimeSh"], "manufacturer": rd["manufacturer"], "type": rd["shType"],
               "serial": rd["serial"], "frame": rd["frame"], "lat": rd["lat"], "lon": rd["lon"],
               "alt": rd["altM"]}
        if rd.get("shSubtype"):
            out["subtype"] = rd["shSubtype"]
        for mine, theirs in (("tempC", "temp"), ("humidity", "humidity"), ("pressureHpa", "pressure"),
                             ("climbMs", "vel_v"), ("velH", "vel_h"), ("headingDeg", "heading"),
                             ("sats", "sats"), ("batteryV", "batt"), ("burstTimer", "burst_timer"),
                             ("xdata", "xdata"), ("dfmcode", "dfmcode"), ("refPosition", "ref_position"),
                             ("refDatetime", "ref_datetime"), ("rs41Mainboard", "rs41_mainboard"),
                             ("rs41MainboardFw", "rs41_mainboard_fw")):
            if rd.get(mine) is not None:
                out[theirs] = rd[mine]
        if rd.get("freqHz"):
            out["frequency"] = round(rd["freqHz"] / 1e6, 4)
        if rd.get("txFreqHz"):
            out["tx_frequency"] = round(rd["txFreqHz"] / 1e6, 4)
        sub = rd.get("rs41Subframe")
        if sub and rd["serial"] not in self.subframes_sent:
            # auto_rx sends an RS41's calibration block once a flight.
            import base64
            import codecs
            try:
                out["rs41_subframe"] = base64.b64encode(codecs.decode(sub, "hex")).decode()
                self.subframes_sent.add(rd["serial"])
            except (ValueError, TypeError):
                pass
        return out

    def _who(self) -> tuple[str, list] | None:
        call, loc = self.station()
        call = str(call or "").strip().upper()
        pos = station_position(loc)
        if not call or pos is None:
            return None
        return call, [pos[0], pos[1], 0.0]

    def flush(self, now: float | None = None) -> bool:
        """Send what is queued, as one gzip-compressed PUT. True when sent
        (or nothing to send); False when it could not be, the frames then
        dropped: offline the queue would otherwise only grow, and a frame
        minutes late is of little use to SondeHub's map."""
        now = time.time() if now is None else now
        if not self.upload_on():
            with self.lock:
                self.queue.clear()
                self.error = None
            return True
        with self.lock:
            batch = list(self.queue)
            self.queue.clear()
        if not batch:
            return True
        who = self._who()
        if who is None:
            self.error = _("SondeHub needs your callsign and locator on the Station page")
            return False
        call, pos = who
        stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for t in batch:
            t.update({"software_name": "OpenHamShack-Radio", "software_version": version(),
                      "uploader_callsign": call, "uploader_position": pos, "uploader_antenna": "",
                      "time_received": stamp})
        body = gzip.compress(json.dumps(batch).encode("utf-8"))
        try:
            status, raw = self._request("PUT", "/sondes/telemetry", body,
                                        {"Content-Encoding": "gzip", "Content-Type": "application/json",
                                         "Date": formatdate(timeval=now, localtime=False, usegmt=True)})
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                self.error = _("SondeHub refused the upload ({status})").format(status=e.code)
                log.warning("SondeHub refused %d frames: HTTP %d", len(batch), e.code)
            else:
                self._quiet(f"http{e.code}", "SondeHub upload: HTTP %d (dropped, tried again later)", e.code)
            return False
        except (OSError, ValueError) as e:
            # No route out, a timeout, a refused connection: offline is not
            # an error to the operator (module docstring).
            self._quiet("offline", "SondeHub upload: not reachable (%s); radiosondes are decoded as before",
                        type(e).__name__)
            return False
        self.error = None
        self.last_upload = now
        self._logged.discard("offline")
        if status in (201, 202):
            # Accepted with remarks (auto_rx logs them; a DFM's z-check is routine).
            try:
                for err in json.loads(raw).get("errors") or []:
                    msg = str(err.get("error_message", ""))
                    (log.debug if "z-check" in msg else log.info)("SondeHub: %s", msg)
            except (ValueError, AttributeError):
                pass
        if now - self.listener_at >= LISTENER_EVERY_S:
            self.listener_at = now
            self._listener(call, pos, now)
        return True

    def _listener(self, call: str, pos: list, now: float) -> None:
        """The station on SondeHub's map (auto_rx's station_position_upload)."""
        doc = {"software_name": "OpenHamShack-Radio", "software_version": version(), "uploader_callsign": call,
               "uploader_position": pos, "uploader_antenna": "", "uploader_contact_email": "", "mobile": False}
        try:
            self._request("PUT", "/listeners", json.dumps(doc).encode("utf-8"),
                          {"Content-Type": "application/json",
                           "Date": formatdate(timeval=now, localtime=False, usegmt=True)})
        except (OSError, ValueError):
            pass

    def view(self) -> dict:
        return {"enabled": bool(self.upload_on()), "lastUploadUtc": _iso(self.last_upload),
                "error": self.error if self.upload_on() else None}

    # -- launch sites ------------------------------------------------------------
    def _sites_path(self) -> Path | None:
        return self.folder / "sites.json" if self.folder is not None else None

    def _load_sites(self) -> None:
        p = self._sites_path()
        if p is None:
            return
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError):
            return
        if isinstance(doc, dict) and isinstance(doc.get("sites"), dict):
            self.sites = doc["sites"]
            self.sites_at = float(doc.get("fetchedAt") or 0.0)

    def refresh_sites(self, now: float | None = None) -> bool:
        """Fetch /sites and keep it (temp file renamed over the old, as
        flightroutes.py). False, the old list kept, on any failure."""
        now = time.time() if now is None else now
        self.sites_tried = now
        try:
            _status, raw = self._request("GET", "/sites")
            sites = json.loads(raw)
            if not isinstance(sites, dict):
                raise Unusable()
        except (OSError, ValueError) as e:
            self._quiet("sites", "SondeHub sites: not fetched (%s); the last list stands", type(e).__name__)
            return False
        self.sites, self.sites_at = sites, now
        p = self._sites_path()
        if p is not None:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps({"fetchedAt": now, "sites": sites}, separators=(",", ":")))
                os.replace(tmp, p)
            except OSError as e:
                log.warning("could not keep SondeHub's site list: %s", e)
        return True

    def launches(self, lat: float | None, lon: float | None, now: float | None = None) -> list[dict]:
        """Upcoming launches near (lat, lon) from the list on hand; asks
        the thread for a fresher list when it is stale. `[]` offline with
        no list yet, or with the setting off."""
        if not self.online_on() or lat is None or lon is None:
            return []
        self.sites_wanted = True
        return upcoming_launches(self.sites, lat, lon, time.time() if now is None else now)

    def site_near(self, lat: float, lon: float) -> dict | None:
        return nearest_site(self.sites, lat, lon)

    # -- predictions ---------------------------------------------------------------
    def predict(self, serial: str, query: dict, now: float | None = None) -> None:
        """Ask Tawhiri (in the background) with `query` (its parameters)
        unless asked within PREDICT_EVERY_S."""
        if not self.online_on():
            return
        now = time.time() if now is None else now
        with self.lock:
            if now - self.asked.get(serial, -1e18) < PREDICT_EVERY_S:
                return
            self.asked[serial] = now
            self.pending[serial] = dict(query)

    def _predict_now(self, serial: str, query: dict, now: float) -> None:
        try:
            _status, raw = self._request("GET", "/tawhiri", query=query)
            result = parse_tawhiri(json.loads(raw))
        except urllib.error.HTTPError as e:
            self._quiet(f"tawhiri{e.code}", "Tawhiri: HTTP %d; the ballistic estimate stands", e.code)
            result = None
        except (OSError, ValueError) as e:
            self._quiet("tawhiri", "Tawhiri: not reachable (%s); the ballistic estimate stands", type(e).__name__)
            result = None
        with self.lock:
            if result is None:
                self.asked[serial] = now - PREDICT_EVERY_S + PREDICT_RETRY_S
                return
            self.predictions[serial] = {"at": now, "result": result}

    def prediction(self, serial: str, max_age: float | None = None, now: float | None = None) -> dict | None:
        """Tawhiri's last answer for `serial`; None when there is none, or
        (`max_age`) when it is older than that: a sonde's flight has moved
        on, and the ballistic estimate from where it is now is better."""
        now = time.time() if now is None else now
        with self.lock:
            p = self.predictions.get(serial)
            if p is None or (max_age is not None and now - p["at"] > max_age):
                return None
            return dict(p["result"])
