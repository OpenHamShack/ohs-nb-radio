"""Orbital elements for Radio's weather satellites (docs/SERVER-API.md
"Weather satellites"): where the two-line element sets the pass
prediction (wxsat_orbit.py) runs on come from, and how old they are.

Three sources, each satellite taking the first that has it:

1. **operator** - the `wxsatTle` setting: element sets the operator
   pasted (a satellite whose sets Celestrak has not caught up with after a
   manoeuvre, or a station with no internet that copies them by hand).
   Lines may be separated by line breaks or "|" - an app setting reaches a
   store container one variable per line, so the stored form must be able
   to have none. A set is matched to its satellite by the NORAD number in
   its lines, never by the name line, which every source spells its own
   way ("METEOR-M2 3", "METEOR-M 2-3").
2. **celestrak** - Celestrak's GP data for its "weather" group, fetched in
   the background once a day while `wxsatOnlineTle` is on (the default),
   kept in the data folder (`wxsat/celestrak.txt`), so a station that goes
   offline keeps the last sets it had.
3. **bundled** - ohsradio/data/wxsat/tle.txt, checked into the repository,
   so a station that has never been online still predicts passes. Between
   the cache and the bundle the one with the newer epoch wins: an update
   can bring a newer bundle than an old cache.

Brian's rule for anything that reaches the internet (dmrids.py says it at
length): offline everything works as before. So, as there: one daemon
thread at the lowest priority, started only for the program an operator
runs (a test's radio starts none and is given no way out), a fetch never on
any path a client waits for, silent indefinite backoff on any failure (one
log line per cause), a file written whole and renamed into place, and the
setting off meaning no traffic at all. The cache is still used then: it is
data already on disk, and better than the bundle once the bundle ages.

**Age is the elements' epoch, not when they were fetched** (decided for
this feature): an element set's accuracy decays from its epoch, whatever
day it was downloaded - Celestrak can serve a set days old for a
satellite it has not re-tracked, and a pasted set has no fetch time at
all. `ageDays` is the age of the oldest set in use and `stale` is true past
STALE_DAYS (14): Meteor's along-track error then grows to tens of
seconds, still inside a pass recorded from horizon to horizon, but worth
saying. `fetchedUtc` reports when the source in use was fetched (the
bundle's date line for the bundle, null for the operator's), for a person
to read beside it.

**What goes out**: one GET a day of CELESTRAK_URL (about 15 kB) with
User-Agent "OpenHamShack-Radio/<version>" and nothing about the station.
Celestrak asks clients not to fetch a group more than once per update
(every two hours at most); once a day is well inside that.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ohsradio.wxsat")

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"
BUNDLED = Path(__file__).resolve().parent / "data" / "wxsat" / "tle.txt"
CACHE_FILE = "celestrak.txt"
STATE_FILE = "tle-state.json"
STALE_DAYS = 14.0
STARTUP_DELAY_S = 120.0
CHECK_S = 3600.0
REFRESH_S = 86_400.0              # once a day
BACKOFF_BASE_S = 3600.0
BACKOFF_MAX_S = 86_400.0
HTTP_TIMEOUT_S = 30.0
MAX_BYTES = 1 << 20               # the weather group was 15 kB (29/10/2026)

_FETCHED = re.compile(r"^#\s*fetched\s+(\S+)", re.IGNORECASE)


class FetchFailed(Exception):
    """No usable answer: no route, a timeout, an HTTP error, a file with
    none of our satellites in it. Backoff; the copy held stands."""


def _checksum_ok(line: str) -> bool:
    """A TLE line's last digit: the sum of its digits, a '-' counting 1,
    modulo 10."""
    if len(line) < 69 or not line[68].isdigit():
        return False
    total = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68])
    return total % 10 == int(line[68])


def parse(text: str) -> dict[int, dict]:
    """{NORAD number: {"name", "l1", "l2", "epoch"}} from TLE text: lines
    separated by line breaks or "|", a name line optional before each pair.
    A pair whose checksums fail, or whose two lines name different
    satellites, is left out rather than guessed at."""
    lines = [ln.rstrip() for ln in re.split(r"[\r\n|]+", text or "") if ln.strip() and not ln.lstrip().startswith("#")]
    out: dict[int, dict] = {}
    for i, l1 in enumerate(lines):
        l1 = l1.strip()
        if not l1.startswith("1 ") or i + 1 >= len(lines):
            continue
        l2 = lines[i + 1].strip()
        if not l2.startswith("2 ") or not (_checksum_ok(l1) and _checksum_ok(l2)):
            continue
        try:
            n1, n2 = int(l1[2:7]), int(l2[2:7])
        except ValueError:
            continue
        if n1 != n2:
            continue
        name = lines[i - 1].strip() if i > 0 and not lines[i - 1].lstrip().startswith(("1 ", "2 ")) else ""
        out[n1] = {"name": name, "l1": l1, "l2": l2, "epoch": epoch(l1)}
    return out


def epoch(l1: str) -> float:
    """A line 1's epoch as Unix time (UTC): columns 19-32, two-digit year
    (57-99 the 1900s, as the format defines) and fractional day of year."""
    yy = int(l1[18:20])
    day = float(l1[20:32])
    year = 1900 + yy if yy >= 57 else 2000 + yy
    return datetime(year, 1, 1, tzinfo=timezone.utc).timestamp() + (day - 1.0) * 86_400.0


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str) -> float | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def default_fetch(url: str) -> bytes:
    """One GET, as the module docstring says; raises FetchFailed."""
    from .dmrids import user_agent
    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise FetchFailed(f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchFailed(getattr(e, "reason", None) and str(e.reason) or e.__class__.__name__) from None
    if len(body) > MAX_BYTES:
        raise FetchFailed("too large")
    return body


class TleStore:
    """The three sources and the fetcher (module docstring). `fetch` is
    url -> bytes (default_fetch for the program an operator runs; None, as
    every test radio has, means nothing ever goes out); `enabled` reads
    wxsatOnlineTle; `clock` is Unix time."""

    def __init__(self, folder, enabled=lambda: True, clock=time.time, fetch=None, bundled: Path = BUNDLED,
                 url: str = CELESTRAK_URL):
        self.dir = Path(folder)
        self.enabled = enabled
        self.clock = clock
        self.fetch = fetch
        self.url = url
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.stop_ev = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.logged: set = set()
        self.state: dict = {}
        self.bundled_sets: dict[int, dict] = {}
        self.bundled_at: float | None = None
        self.cached: dict[int, dict] = {}
        self._load(Path(bundled))

    # ------------------------------------------------------------ disk
    def _load(self, bundled: Path) -> None:
        try:
            text = bundled.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self.bundled_sets = parse(text)
        for line in text.splitlines():
            m = _FETCHED.match(line.strip())
            if m:
                self.bundled_at = _parse_iso(m.group(1))
                break
        try:
            self.state = json.loads((self.dir / STATE_FILE).read_text(encoding="utf-8"))
            if not isinstance(self.state, dict):
                self.state = {}
        except (OSError, ValueError):
            self.state = {}
        try:
            self.cached = parse((self.dir / CACHE_FILE).read_text(encoding="utf-8"))
        except OSError:
            self.cached = {}

    def _save_state(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / (STATE_FILE + ".tmp")
            tmp.write_text(json.dumps(self.state), encoding="utf-8")
            os.replace(tmp, self.dir / STATE_FILE)
        except OSError as e:
            log.log(self._level(("disk", str(e))), "weather satellites: could not keep the TLE fetch state: %s", e)

    # ------------------------------------------------------------ which sets
    def elements(self, norads, operator_text: str = "") -> dict[int, dict]:
        """{NORAD: set} for each satellite asked for that any source has,
        each set with its `source` and the `fetchedUtc` (Unix time or None)
        of that source."""
        mine = parse(operator_text)
        with self.lock:
            cached, fetched = dict(self.cached), self.state.get("fetchedUtc")
        out = {}
        for n in norads:
            if n in mine:
                out[n] = dict(mine[n], source="operator", fetchedUtc=None)
                continue
            c, b = cached.get(n), self.bundled_sets.get(n)
            if c is not None and (b is None or c["epoch"] >= b["epoch"]):
                out[n] = dict(c, source="celestrak", fetchedUtc=fetched)
            elif b is not None:
                out[n] = dict(b, source="bundled", fetchedUtc=self.bundled_at)
        return out

    def view(self, sets: dict[int, dict], now: float) -> dict:
        """The contract's `tle` object for the sets in use: one source (the
        operator's if any set is theirs, else Celestrak's if any is, else
        the bundle's), and the age of the oldest epoch among them."""
        if not sets:
            return {"source": None, "fetchedUtc": None, "ageDays": None, "stale": True}
        sources = {s["source"] for s in sets.values()}
        source = next(x for x in ("operator", "celestrak", "bundled") if x in sources)
        fetched = max((s["fetchedUtc"] for s in sets.values() if s["source"] == source and s["fetchedUtc"]),
                      default=None)
        age = (now - min(s["epoch"] for s in sets.values())) / 86_400.0
        return {"source": source, "fetchedUtc": iso(fetched), "ageDays": round(age, 2), "stale": age > STALE_DAYS}

    # ------------------------------------------------------------ the thread
    def start(self) -> None:
        if self.thread is None and self.fetch is not None:
            self.thread = threading.Thread(target=self._loop, name="radio-wxsat-tle", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        self.wake.set()

    def nudge(self) -> None:
        """The setting was turned on: look now rather than within the hour."""
        self.wake.set()

    def _loop(self) -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (AttributeError, OSError):
            pass
        if self.stop_ev.wait(STARTUP_DELAY_S):
            return
        while not self.stop_ev.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001  a bug here must never reach a client, nor end the thread
                log.warning("weather satellites: the TLE look failed", exc_info=True)
            self.wake.wait(CHECK_S)
            self.wake.clear()

    def _level(self, cause) -> int:
        if cause in self.logged:
            return logging.DEBUG
        self.logged.add(cause)
        return logging.INFO

    def run_once(self, norads=(57166, 59051)) -> str:
        """One look at Celestrak: "fetched", "fresh", "backoff", "failed"
        or "off" (the setting off, or no way out). Never raises for a
        network or file fault."""
        if self.fetch is None or not self.enabled():
            return "off"
        with self.run_lock:
            now = self.clock()
            if float(self.state.get("until", 0.0)) > now:
                return "backoff"
            if self.cached and now - float(self.state.get("checkedAt", 0.0)) < REFRESH_S:
                return "fresh"
            try:
                body = self.fetch(self.url)
                text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
                got = parse(text)
                ours = {n: got[n] for n in norads if n in got}
                if not ours:
                    raise FetchFailed("none of the weather satellites in the answer")
                self.dir.mkdir(parents=True, exist_ok=True)
                tmp = self.dir / (CACHE_FILE + ".tmp")
                tmp.write_text("".join(f"{s['name']}\n{s['l1']}\n{s['l2']}\n" for s in ours.values()),
                               encoding="utf-8")
                os.replace(tmp, self.dir / CACHE_FILE)
            except (FetchFailed, OSError) as e:
                fails = int(self.state.get("failures", 0)) + 1
                wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** min(fails - 1, 30))
                self.state.update(failures=fails, until=now + wait)
                self._save_state()
                log.log(self._level(str(e)), "weather satellites: TLEs not fetched (%s); next try in %.0f min",
                        e, wait / 60)
                return "failed"
            with self.lock:
                self.cached = ours
            self.state = {"fetchedUtc": now, "checkedAt": now}
            self._save_state()
            log.info("weather satellites: %d element sets fetched from Celestrak", len(ours))
            return "fetched"
