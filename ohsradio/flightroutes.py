"""Flight routes for ADS-B's aircraft (29/10/2026; docs/SERVER-API.md
"ADS-B", "Flight routes").

An aircraft's Mode S identification message carries a callsign (an
airline's flight number, "BAW90", or a GA aircraft's own registration,
"G-ABCD"), nothing about where it is going. adsbdb.com publishes a free
lookup from an airline callsign to the route it flies, built from
schedule data, no key needed. This module asks it, by callsign, once,
in the background, and gives the answer to `api/adsb/aircraft` and
`api/adsb/aircraft/{icao}` as each entry's `route`.

Brian's rule for anything that reaches the internet: **offline, nothing
changes**. No route out, a timeout, a server error, an unknown callsign,
or the `adsbRouteLookup` setting off all end the same way - `"route":
null`, nothing on any listener's screen, one log line per cause (never
the callsign: a GA registration is somebody's, and the module docstrings
for dmrids.py and radiodns.py draw the same line). So:

- **Never on a path anything waits for.** One daemon thread, started only
  for the program an operator runs (Radio's `persist`; a test's
  throw-away radio starts none), pulling one callsign at a time from a
  bounded queue. `lookup()` itself never blocks: it reads the cache (a
  dict behind a lock) and, for a callsign neither cached nor already
  queued, enqueues it and answers `None` for this call - the next look
  (the aircraft is still on the map; a client polls or holds a live feed)
  gets the answer once the fetch lands.
- **At most one request a second**, queue bounded (QUEUE_MAX): a fast
  scan across a busy map's aircraft asks adsbdb for each only once and
  never bursts it.
- **Cached, with different lives for different answers.** A route found:
  POSITIVE_TTL_S (7 days - callsigns are reused by the same route for
  months, VERSION-API.md's AIRLINE_TTL_S has no match here, there is only
  one timer). An airline callsign adsbdb does not know: NEGATIVE_TTL_S (1
  day - new routes appear in its data; worth asking again, not every
  time this aircraft is seen). A failure (no route out, a timeout, a
  5xx): ERROR_RETRY_S (10 minutes), so a flaky host is asked again soon
  without a retry storm while it stays down.
- **Skips what cannot be a flight number.** Empty, or shaped like a
  registration (a hyphen, as the UK/EU/most of the world's "G-ABCD"; or a
  US N-number, "N12345"): neither is in adsbdb's callsign table, and
  asking wastes the one request a second on an answer that is always
  "unknown". A GA aircraft that happens to fly a route under charter still
  shows no route; no source tells us: it is not registered as an airline.
- **Survives a restart.** The cache is a JSON file in the app's data
  folder, written to a temp file and renamed over the old one only once
  it is whole (as dmrids.py, radiodns.py): a write cut short by a crash
  or a power loss leaves the previous cache in place, never a half file.
- **The setting off** means no traffic at all and no routes shown: every
  `lookup()` answers `None` without even reading the cache, as
  `dmrIdLookup` off hides names it already holds (dmrids.py). The cache
  itself is kept on disk so switching the setting back on serves it at
  once, not after a week of re-asking.

**What goes out.** One GET of `https://api.adsbdb.com/v0/callsign/<cs>`
per new callsign, User-Agent "OpenHamShack-Radio/<version>" and nothing
else: no cookies (the opener has no cookie handler), no query string, no
callsign beyond the one in the path, no station details. adsbdb needs no
key and states no contact-address request (unlike radioid.net's), so none
is given, matching Brian's rule that the User-Agent carries no personal
data.

**The shape** `lookup()` hands back (the TV client's agreed contract):
`{"from": "GLA", "to": "LGW", "fromName": "Glasgow", "toName": "London
Gatwick", "fromIcao": "EGPF", "toIcao": "EGKK", "source": "adsbdb"}` or
`None`. `from`/`to` are the airport's IATA code where adsbdb gives one,
else its ICAO code (small airports often have no IATA); `fromIcao`/
`toIcao` are always the ICAO code. A route missing either end's code
(adsbdb occasionally has a half-filled record) counts as "no route
known", not a wrong one: it is dropped rather than shown with a blank.
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

log = logging.getLogger("ohsradio.flightroutes")

BASE_URL = "https://api.adsbdb.com"
FOLDER = "flightroutes"           # in the app's data folder
CACHE_FILE = "cache.json"

STARTUP_DELAY_S = 0.0              # a lookup only ever follows an operator opening the map
RATE_S = 1.0                       # at most one request a second
QUEUE_MAX = 64
HTTP_TIMEOUT_S = 10.0
MAX_BYTES = 1 << 20                # adsbdb's answers are a few hundred bytes
POSITIVE_TTL_S = 7 * 86_400.0
NEGATIVE_TTL_S = 1 * 86_400.0
ERROR_RETRY_S = 600.0
MAX_ENTRIES = 4000                 # pruned oldest-first on save; far more than a map ever asks about in a week

# A callsign that cannot be an airline flight number: empty, or shaped
# like a registration. Most of the world's aircraft registrations carry a
# hyphen ("G-ABCD", "D-EFGH", "F-ABCD"); the US and a few others have none
# ("N12345", "N1A"). Neither is in adsbdb's callsign table.
_CALLSIGN = re.compile(r"^[A-Z0-9]{2,8}$")
_US_REG = re.compile(r"^N[0-9]{1,5}[A-Z]{0,2}$")

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def user_agent() -> str:
    """The program and its version, nothing else (module docstring)."""
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        version = "0"
    return f"OpenHamShack-Radio/{version}"


def clean_callsign(callsign) -> str | None:
    """The callsign upper-cased and stripped, or None when it is empty or
    looks like a registration rather than a flight number."""
    cs = str(callsign or "").strip().upper()
    if not cs or "-" in cs or _US_REG.match(cs) or not _CALLSIGN.match(cs):
        return None
    return cs


class FetchFailed(Exception):
    """adsbdb did not give a usable answer: no route, a timeout, a server
    error, or a body that was not its JSON shape. Retried after
    ERROR_RETRY_S; the cache (if any) stands."""


def _parse_route(data, callsign: str) -> dict | None:
    """adsbdb's `{"response": {"flightroute": {...}}}`, or None for its
    `{"response": "unknown callsign"}` (or any shape that is not a route:
    treated the same as unknown, never an error)."""
    resp = data.get("response") if isinstance(data, dict) else None
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    origin = fr.get("origin") if isinstance(fr, dict) else None
    dest = fr.get("destination") if isinstance(fr, dict) else None
    if not isinstance(origin, dict) or not isinstance(dest, dict):
        return None

    def code(ap: dict) -> str | None:
        return ap.get("iata_code") or ap.get("icao_code") or None

    out = {"from": code(origin), "to": code(dest),
           "fromName": origin.get("name") or None, "toName": dest.get("name") or None,
           "fromIcao": origin.get("icao_code") or None, "toIcao": dest.get("icao_code") or None,
           "source": "adsbdb"}
    if out["from"] is None or out["to"] is None:
        return None
    return out


class FlightRoutes:
    """The cache, its queue and its fetcher (module docstring).

        routes = FlightRoutes(folder, enabled=lambda: True)
        routes.lookup("BAW90") -> {"from", "to", "fromName", "toName",
                                   "fromIcao", "toIcao", "source"} | None
        routes.start() / routes.stop()
    """

    def __init__(self, folder, enabled=lambda: True, clock=time.time, base_url: str | None = None,
                 timeout: float = HTTP_TIMEOUT_S):
        self.dir = Path(folder)
        self.enabled = enabled
        self.clock = clock
        # $OHS_FLIGHTROUTES_BASE puts the lookup on another server (tests/
        # scratch_home.py: a closed local port, so no test can reach the
        # real internet); a URL given here wins.
        env = os.environ.get("OHS_FLIGHTROUTES_BASE", "").rstrip("/")
        self.base_url = base_url or (env if env else BASE_URL)
        self.timeout = timeout
        self.lock = threading.Lock()         # the cache dict and its file
        self.cache: dict[str, dict] = {}
        self.queued: set[str] = set()
        self.queue: "queue.Queue[str | None]" = queue.Queue(maxsize=QUEUE_MAX)
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self._last_request = 0.0             # time.monotonic() of the last GET, for the rate limit
        self._load()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name="flightroutes", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        try:
            self.queue.put_nowait(None)      # wake a blocked get()
        except queue.Full:
            pass
        if self.thread is not None:
            self.thread.join(timeout=5.0)
            self.thread = None

    # ------------------------------------------------------------ lookup
    def lookup(self, callsign) -> dict | None:
        """The cached route for `callsign`, or None while it is unknown,
        not yet looked up, failed, or the setting is off. Queues a fetch
        the first time a callsign worth asking about is seen; never
        blocks on one."""
        if not self.enabled():
            return None
        cs = clean_callsign(callsign)
        if cs is None:
            return None
        now = self.clock()
        with self.lock:
            ent = self.cache.get(cs)
        if ent is not None:
            age = now - ent["at"]
            if ent["status"] == "ok" and age < POSITIVE_TTL_S:
                return ent["route"]
            if ent["status"] == "unknown" and age < NEGATIVE_TTL_S:
                return None
            if ent["status"] == "error" and age < ERROR_RETRY_S:
                return None
        self._enqueue(cs)
        return None

    def _enqueue(self, cs: str) -> None:
        with self.lock:
            if cs in self.queued:
                return
            self.queued.add(cs)
        try:
            self.queue.put_nowait(cs)
        except queue.Full:
            with self.lock:
                self.queued.discard(cs)
            log.debug("flight-route queue full: dropping a lookup")

    # ------------------------------------------------------------ the worker
    def _run(self) -> None:
        while not self.stop_ev.is_set():
            try:
                cs = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if cs is None:
                continue
            with self.lock:
                self.queued.discard(cs)
            self._throttle()
            if self.stop_ev.is_set():
                break
            self._fetch_and_store(cs)

    def _throttle(self) -> None:
        wait = self._last_request + RATE_S - time.monotonic()
        if wait > 0:
            self.stop_ev.wait(wait)
        self._last_request = time.monotonic()

    def _fetch_and_store(self, cs: str) -> None:
        try:
            route = self._fetch(cs)
            status = "ok" if route is not None else "unknown"
        except FetchFailed as e:
            status, route = "error", None
            log.debug("flight-route lookup failed, retrying in %ds (%s)", int(ERROR_RETRY_S), e)
        with self.lock:
            self.cache[cs] = {"status": status, "route": route, "at": self.clock()}
            self._prune()
            self._save()

    def _fetch(self, cs: str) -> dict | None:
        url = f"{self.base_url}/v0/callsign/{urllib.parse.quote(cs, safe='')}"
        req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None           # adsbdb's "unknown callsign" (29/10/2026)
            raise FetchFailed(f"http {e.code}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise FetchFailed(str(e)) from e
        if len(raw) > MAX_BYTES:
            raise FetchFailed("answer too large")
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise FetchFailed(f"bad json: {e}") from e
        return _parse_route(data, cs)

    # ------------------------------------------------------------ storage
    def _prune(self) -> None:
        if len(self.cache) <= MAX_ENTRIES:
            return
        oldest = sorted(self.cache.items(), key=lambda kv: kv[1]["at"])
        for cs, _ent in oldest[:len(self.cache) - MAX_ENTRIES]:
            self.cache.pop(cs, None)

    def _save(self) -> None:
        """Called holding `self.lock`: a whole file or none, as dmrids.py
        and radiodns.py write their state - a crash mid-write leaves the
        previous cache in place."""
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f"{CACHE_FILE}.part"
            tmp.write_text(json.dumps(self.cache))
            tmp.replace(self.dir / CACHE_FILE)
        except OSError as e:
            log.debug("could not save the flight-route cache: %s", e)

    def _load(self) -> None:
        try:
            raw = (self.dir / CACHE_FILE).read_text()
            data = json.loads(raw)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for cs, ent in data.items():
            if (isinstance(ent, dict) and ent.get("status") in ("ok", "unknown", "error")
                    and isinstance(ent.get("at"), (int, float))):
                self.cache[cs] = {"status": ent["status"], "route": ent.get("route"), "at": float(ent["at"])}
