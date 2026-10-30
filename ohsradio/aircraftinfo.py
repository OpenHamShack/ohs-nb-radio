"""More about each aircraft on ADS-B's map: its details and a photo
(Brian, 30/10/2026; docs/SERVER-API.md "ADS-B", "Aircraft details and
photos").

A Mode S address says nothing about the airframe behind it. Two free
public lookups do, by that address, with no key:

- **adsbdb** (`GET https://api.adsbdb.com/v0/aircraft/<hex>`, the same
  service flightroutes.py asks for routes): registration, type, maker,
  registered owner and its country. Handed out as an aircraft's `info`,
  with the airline from flightroutes.py's callsign answer added by the
  caller.
- **Planespotters** (`GET https://api.planespotters.net/pub/photos/hex/
  <hex>`): one photo's address, its photographer and its page. Handed out
  as an aircraft's `photo`.

Brian's rule for anything that reaches the internet holds as in
flightroutes.py: **offline, nothing changes.** No route out, a timeout, a
server error, or the setting off all end in `info`/`photo` `null`, one
debug log line per cause, never the address. So, as there: never on a
path anything waits for (a daemon thread per source, started only for the
program an operator runs, pulling from a bounded queue; `info()` and
`photo()` read the cache and queue a miss, never block), at most one
request a second per source, a cache file written whole or not at all.
What differs:

- **Backoff across the whole source.** After a failure the worker waits
  BACKOFF_MIN_S before its next request of any address, doubling to
  BACKOFF_MAX_S while failures go on, and back to the plain rate after a
  success. flightroutes.py's per-callsign retry alone would still ask once
  a second for every new aircraft while the host is down or refusing us; a
  busy map would keep that up all day.
- **Lifetimes.** adsbdb's details: a hit INFO_OK_TTL_S (30 days: an
  airframe's registration and type almost never change), a miss
  INFO_UNKNOWN_TTL_S (1 day: new airframes are added). Planespotters'
  answer: PHOTO_TTL_S (24 hours) for a hit and a miss alike, because
  their terms allow the API's JSON to be kept for at most 24 hours. An
  entry past its life is dropped from the file on the next save, not only
  ignored, for the same reason.
- **Two settings,** because the two reach different places:
  `adsbAircraftLookup` (only Radio talks to adsbdb) and `adsbPhotoLookup`
  (a screen then fetches the picture itself, below). Off means no request
  and `null`, even for what is cached, as `adsbRouteLookup`.

**The photo is never fetched, kept or served by Radio.** Planespotters'
Photo API terms (read 30/10/2026, planespotters.net/photo/api): image
binaries "must be fetched straight from the thumbnail / thumbnail_large
URLs we return, by the same browser or device that displays them"; "what
is not permitted is writing it to storage, keeping it after it stops
being displayed, re-hosting it, or passing it on to any other client";
"Proxying, rewriting, or hot-link-protection bypassing is not permitted";
but "You may call the API from your own backend and pass the results to
your own website or app, as long as the URLs reach the viewer unchanged".
So Radio asks the API and hands the screen `photo.src`, the
`thumbnail_large` address exactly as returned, with the credit and the
link to the photo's page (also unchanged; the terms require both to be
shown, and on a TV the link as an NFC tag or QR code - shown text is not
enough). The screen loads the picture from Planespotters itself. The
brief's `GET api/adsb/aircraft/<icao>/photo` image proxy was not built
for this reason, and answers 404 like any Radio without one.

**What goes out.** adsbdb: one GET per new address, the address in the
path, User-Agent flightroutes.user_agent() ("OpenHamShack-Radio/<version>")
and nothing else. Planespotters: the same, but its terms require a
non-browser client's User-Agent to carry "a contact URL or email" and
reject bare ones, so it says "OpenHamShack-Radio/<version>
(+https://openhamshack.com/)" - the project's address, never the
operator's, so still nothing about whoever runs the station. No cookies,
no Origin or Referer, no query string.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .flightroutes import FetchFailed, user_agent

log = logging.getLogger("ohsradio.aircraftinfo")

ADSBDB_URL = "https://api.adsbdb.com"
PLANESPOTTERS_URL = "https://api.planespotters.net"
CONTACT_URL = "https://openhamshack.com/"      # Planespotters' terms: a contact URL in the User-Agent

RATE_S = 1.0                       # per source: at most one request a second
QUEUE_MAX = 64
HTTP_TIMEOUT_S = 10.0
MAX_BYTES = 1 << 20                # both answers are well under 2 kB
INFO_OK_TTL_S = 30 * 86_400.0
INFO_UNKNOWN_TTL_S = 1 * 86_400.0
PHOTO_TTL_S = 24 * 3600.0          # Planespotters' terms: JSON kept 24 hours at most
ERROR_RETRY_S = 600.0              # one address that failed, asked again after
BACKOFF_MIN_S = 30.0               # the whole source, after a failure (module docstring)
BACKOFF_MAX_S = 1800.0
MAX_ENTRIES = 20000                # info's file at ~250 bytes each: 5 MB at most

# A real ICAO address: six hex digits. An anonymous or TIS-B address ("~"
# first, adsb.py) is nobody's airframe and is never asked about.
_ICAO = re.compile(r"^[0-9A-F]{6}$")


def planespotters_agent() -> str:
    """flightroutes.user_agent() with the project's contact address, which
    Planespotters' terms require of a non-browser client (module docstring)."""
    return f"{user_agent()} (+{CONTACT_URL})"


def clean_icao(icao) -> str | None:
    h = str(icao or "").strip().upper()
    return h if _ICAO.match(h) else None


def _text(v) -> str | None:
    v = v.strip() if isinstance(v, str) else None
    return v or None


def parse_info(data) -> dict | None:
    """adsbdb's `{"response": {"aircraft": {...}}}` as the API's `info`
    (without the airline, which the caller adds), or None for anything that
    is not an aircraft record (its `{"response": "unknown aircraft"}`)."""
    resp = data.get("response") if isinstance(data, dict) else None
    a = resp.get("aircraft") if isinstance(resp, dict) else None
    if not isinstance(a, dict):
        return None
    out = {"registration": _text(a.get("registration")), "typeCode": _text(a.get("icao_type")),
           "type": _text(a.get("type")), "manufacturer": _text(a.get("manufacturer")),
           "owner": _text(a.get("registered_owner")), "country": _text(a.get("registered_owner_country_name"))}
    # A record with neither registration nor type tells a screen nothing.
    if out["registration"] is None and out["typeCode"] is None and out["type"] is None:
        return None
    return out


def parse_photo(data) -> dict | None:
    """Planespotters' `{"photos": [{"thumbnail_large": {"src", "size"},
    "link", "photographer"}]}` as the API's `photo`, or None for no photo.
    The addresses go out exactly as they came (the terms), so the only
    check is that they are https - anything else is not theirs."""
    photos = data.get("photos") if isinstance(data, dict) else None
    p = photos[0] if isinstance(photos, list) and photos and isinstance(photos[0], dict) else None
    if p is None:
        return None
    img = p.get("thumbnail_large") if isinstance(p.get("thumbnail_large"), dict) else p.get("thumbnail")
    src = img.get("src") if isinstance(img, dict) else None
    link = p.get("link")
    if not (isinstance(src, str) and src.startswith("https://") and isinstance(link, str)
            and link.startswith("https://")):
        return None
    size = img.get("size") if isinstance(img.get("size"), dict) else {}
    who = _text(p.get("photographer"))
    return {"src": src, "width": size.get("width") if isinstance(size.get("width"), int) else None,
            "height": size.get("height") if isinstance(size.get("height"), int) else None,
            "credit": f"© {who}" if who else "© Planespotters.net", "link": link}


class Lookup:
    """One source's cache, queue, worker and backoff, by ICAO address
    (module docstring). `fetch(icao)` answers the value, None for "this
    source does not know it", or raises FetchFailed. `ttl` maps "ok" and
    "unknown" to their lifetimes.

        lk.get("4CA264") -> ("ok", value) | ("unknown", None) | None
    """

    def __init__(self, name: str, path: Path, enabled, fetch, ttl: dict, clock=time.time):
        self.name = name
        self.path = Path(path)
        self.enabled = enabled
        self.fetch = fetch
        self.ttl = {**ttl, "error": ERROR_RETRY_S}
        self.clock = clock
        self.lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        self.queued: set[str] = set()
        self.queue: "queue.Queue[str | None]" = queue.Queue(maxsize=QUEUE_MAX)
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self.rate_s = RATE_S
        self.backoff_min_s = BACKOFF_MIN_S
        self.backoff_max_s = BACKOFF_MAX_S
        self.backoff_s = 0.0                 # the wait before the next request; 0 while all is well
        self._last_request = 0.0
        self._load()

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name=f"aircraftinfo-{self.name}", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            self.thread = None

    def get(self, icao) -> tuple[str, object] | None:
        """The cached answer, or None while there is none worth using (not
        yet asked, failed lately, stale, or the setting off); queues a
        request for a miss, never blocks on one."""
        if not self.enabled():
            return None
        h = clean_icao(icao)
        if h is None:
            return None
        with self.lock:
            ent = self.cache.get(h)
        if ent is not None and self.clock() - ent["at"] < self.ttl[ent["status"]]:
            return None if ent["status"] == "error" else (ent["status"], ent["value"])
        self._enqueue(h)
        return None

    def _enqueue(self, h: str) -> None:
        with self.lock:
            if h in self.queued:
                return
            self.queued.add(h)
        try:
            self.queue.put_nowait(h)
        except queue.Full:
            with self.lock:
                self.queued.discard(h)

    def _run(self) -> None:
        while not self.stop_ev.is_set():
            try:
                h = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if h is None:
                continue
            with self.lock:
                self.queued.discard(h)
            wait = max(self._last_request + self.rate_s, self._last_request + self.backoff_s) - time.monotonic()
            if wait > 0 and self.stop_ev.wait(wait):
                break
            self._last_request = time.monotonic()
            self._fetch_and_store(h)

    def _fetch_and_store(self, h: str) -> None:
        try:
            value = self.fetch(h)
            status = "ok" if value is not None else "unknown"
            self.backoff_s = 0.0
        except FetchFailed as e:
            status, value = "error", None
            self.backoff_s = min(self.backoff_max_s, max(self.backoff_min_s, self.backoff_s * 2))
            log.debug("%s lookup failed, waiting %ds before the next (%s)", self.name, int(self.backoff_s), e)
        with self.lock:
            self.cache[h] = {"status": status, "value": value, "at": self.clock()}
            self._save()

    def _save(self) -> None:
        """Called holding `self.lock`. Stale entries go first (Planespotters'
        terms limit how long its answers may be kept, not only used), then
        the oldest past MAX_ENTRIES; then a whole file or none."""
        now = self.clock()
        for h in [h for h, e in self.cache.items() if now - e["at"] >= self.ttl[e["status"]]]:
            del self.cache[h]
        if len(self.cache) > MAX_ENTRIES:
            for h, _e in sorted(self.cache.items(), key=lambda kv: kv[1]["at"])[:len(self.cache) - MAX_ENTRIES]:
                del self.cache[h]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".part")
            tmp.write_text(json.dumps(self.cache))
            tmp.replace(self.path)
        except OSError as e:
            log.debug("could not save the %s cache: %s", self.name, e)

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        now = self.clock()
        for h, ent in data.items():
            if (clean_icao(h) == h and isinstance(ent, dict) and ent.get("status") in self.ttl
                    and isinstance(ent.get("at"), (int, float)) and now - ent["at"] < self.ttl[ent["status"]]):
                self.cache[h] = {"status": ent["status"], "value": ent.get("value"), "at": float(ent["at"])}


def _get_json(url: str, agent: str, timeout: float) -> object | None:
    """The JSON at `url`; None for a 404 (both sources' "not known");
    FetchFailed for anything else that is not a whole JSON answer."""
    req = urllib.request.Request(url, headers={"User-Agent": agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise FetchFailed(f"http {e.code}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise FetchFailed(str(e)) from e
    if len(raw) > MAX_BYTES:
        raise FetchFailed("answer too large")
    try:
        return json.loads(raw)
    except ValueError as e:
        raise FetchFailed(f"bad json: {e}") from e


class AircraftInfo:
    """Both sources (module docstring).

        ai = AircraftInfo(folder, info_enabled=..., photo_enabled=...)
        ai.info("4CA264", airline) -> {...} | {} | None
        ai.photo("4CA264")         -> {"src", "width", "height", "credit", "link"} | None
        ai.start() / ai.stop()
    """

    def __init__(self, folder, info_enabled=lambda: True, photo_enabled=lambda: True, clock=time.time,
                 adsbdb_url: str | None = None, planespotters_url: str | None = None,
                 timeout: float = HTTP_TIMEOUT_S):
        folder = Path(folder)
        # Tests point both elsewhere (tests/scratch_home.py: closed local
        # ports). adsbdb is the host flightroutes.py asks, so it follows
        # the same variable; a URL given here wins.
        self.adsbdb_url = adsbdb_url or os.environ.get("OHS_FLIGHTROUTES_BASE", "").rstrip("/") or ADSBDB_URL
        self.planespotters_url = (planespotters_url or os.environ.get("OHS_PLANESPOTTERS_BASE", "").rstrip("/")
                                  or PLANESPOTTERS_URL)
        self.timeout = timeout
        self.infos = Lookup("adsbdb", folder / "info.json", info_enabled, self._fetch_info,
                            {"ok": INFO_OK_TTL_S, "unknown": INFO_UNKNOWN_TTL_S}, clock)
        self.photos = Lookup("planespotters", folder / "photos.json", photo_enabled, self._fetch_photo,
                             {"ok": PHOTO_TTL_S, "unknown": PHOTO_TTL_S}, clock)

    def start(self) -> None:
        self.infos.start()
        self.photos.start()

    def stop(self) -> None:
        self.infos.stop()
        self.photos.stop()

    def info(self, icao, airline: dict | None = None) -> dict | None:
        """The aircraft's details: None until adsbdb has answered (or the
        setting is off, or it failed); `{}` when it knows nothing of this
        address and no airline is known either. The airline (from the
        callsign, flightroutes.py) rides on whatever adsbdb said, so an
        airframe adsbdb has never heard of still names who is flying it."""
        got = self.infos.get(icao)
        if got is None:
            return None
        status, value = got
        if status == "ok":
            return {**value, "airline": airline, "source": "adsbdb"}
        return {"airline": airline, "source": "adsbdb"} if airline else {}

    def photo(self, icao) -> dict | None:
        got = self.photos.get(icao)
        return dict(got[1]) if got is not None and got[0] == "ok" else None

    def _fetch_info(self, h: str) -> dict | None:
        data = _get_json(f"{self.adsbdb_url}/v0/aircraft/{urllib.parse.quote(h)}", user_agent(), self.timeout)
        return parse_info(data) if data is not None else None

    def _fetch_photo(self, h: str) -> dict | None:
        data = _get_json(f"{self.planespotters_url}/pub/photos/hex/{urllib.parse.quote(h)}",
                         planespotters_agent(), self.timeout)
        return parse_photo(data) if data is not None else None
