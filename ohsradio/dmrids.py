"""Callsigns and names for DMR IDs, and names for talkgroups (28/10/2026;
docs/SERVER-API.md "DMR", "Callsigns and names").

A DMR call carries only numbers: the caller's 24-bit radio ID and the
talkgroup (or radio) it is to. Most hams' radios are registered with
radioid.net, which publishes every ID's callsign, first name, city, state
and country, and Brandmeister publishes the names of its talkgroups. This
module fetches both in the background, keeps a compact copy in the app's
data folder, and names the IDs in a DMR session's meta and results
(`srcCallsign`, `srcName`, `srcCountry`, `dstName`: annotate()).

Brian's rule for anything that reaches the internet: **offline, everything
is exactly as before**. No route, a refusal, a timeout, a broken file or
the `dmrIdLookup` setting off all end the same way - bare IDs, as before
this module, nothing on any listener's screen, one log line per cause. So:

- **Never on a path anything waits for.** One daemon thread at the lowest
  priority, started only for the program an operator runs (Radio's
  `persist`; a test's throw-away radio starts none), idle for
  STARTUP_DELAY_S after start, then waking every CHECK_S. A lookup is a
  primary-key read of a small local database and never waits for a fetch:
  the swap that replaces the database holds the lookup lock only for a
  close, a rename and an open.
- **Weekly, conditional.** Each source is asked again REFRESH_S after it
  was last asked, with If-None-Match / If-Modified-Since when we hold a
  copy, so most weekly looks cost the server a 304 (radioid.net sends
  both; Brandmeister's API sends neither, but its list is about 17 kB
  gzipped, and an unchanged one is not rewritten).
- **Silent, indefinite backoff.** Any failure puts that source in backoff,
  BACKOFF_BASE_S doubling to BACKOFF_MAX_S, kept on disk so a restart
  cannot undo it, and retried for ever at that pace: never a retry storm,
  never a message to anyone but the log (INFO the first time for a cause,
  then DEBUG).
- **Atomic.** A fetch is parsed into a new file beside the live one and
  renamed over it only once it is whole and holds at least one entry; a
  download cut short (fewer bytes than Content-Length, a parse error)
  leaves the old copy in use and the part file deleted.
- **The setting off** means no traffic at all and no names added: clients
  see bare IDs, as before. The copy on disk is kept for when it is on again.

**The licence** (decided 28/10/2026, from radioid.net's API and data-use
policy, radioid.net/api_use_policy): it forbids mirroring or republishing
RadioID "as a public feed, bulk export, reusable database, competing
directory, or commercial data service without written permission",
whether from the API, the static dumps or scraping. So no copy of either
list is ever bundled with Radio or kept in its repository; each controller
(or desktop) fetches its own at run time and keeps it in its own data
folder, serves only the per-ID answers its own sessions need, and never
offers the list itself on any route. Brandmeister states no redistribution
terms for its talkgroup list, so it is treated the same way.

**What goes out.** One GET of `https://radioid.net/static/user.csv`
(about 17 MB, updated daily; a week's 304 costs a few hundred bytes) and
one of `https://api.brandmeister.network/v2/talkgroup` a week, with
User-Agent "OpenHamShack-Radio/<version>" and nothing else about the
station: no cookies (the opener has no cookie handler), no query string,
no callsign or locator. radioid.net's policy says an automated client
"should" also give a contact address; Brian's rule for every online
feature is that the User-Agent carries no personal data, and Radio has no
contact address that is not someone's, so it gives none.

**Privacy.** The list is personal data about real people. Nothing here
logs a name, callsign or ID - only counts and causes - and the repository
and its tests use only country code 999's IDs (no country's), as the DMR
simulator does.

**Storage.** Users: SQLite (`dmrids/users.sqlite`), one row per ID keyed
by the ID itself (an INTEGER PRIMARY KEY is SQLite's row id, so the key
costs nothing extra), with the country as a number into a small table of
names: 12 MB for a synthetic list shaped like radioid.net's (300,000
IDs, an 18.6 MB CSV; theirs was 17 MB on 28/10/2026), built in 0.7 s on
a desktop, a lookup about 10 us. Talkgroups: a few thousand short names,
kept as JSON (`dmrids/talkgroups.json`) and held in memory. `dmrids/state.json`
holds each source's ETag, Last-Modified, last look and backoff.
"""
from __future__ import annotations

import csv
import gzip
import http.client
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ohsradio.dmrids")

USERS_URL = "https://radioid.net/static/user.csv"
TALKGROUPS_URL = "https://api.brandmeister.network/v2/talkgroup"
FOLDER = "dmrids"                 # in the app's data folder
USERS_DB = "users.sqlite"
TALKGROUPS_FILE = "talkgroups.json"
STATE_FILE = "state.json"

STARTUP_DELAY_S = 180.0
CHECK_S = 3600.0
REFRESH_S = 7 * 86_400.0
HTTP_TIMEOUT_S = 30.0             # per socket operation, not for the whole 17 MB
BACKOFF_BASE_S = 3600.0
BACKOFF_MAX_S = 86_400.0          # then once a day, for ever
MAX_USERS_BYTES = 256 << 20       # radioid.net's was 17 MB (28/10/2026)
MAX_TALKGROUPS_BYTES = 16 << 20
BATCH = 5000

MAX_ID = (1 << 24) - 1
# A field longer than this is not a callsign, name or place: cut, so one
# bad row cannot bloat the database.
FIELD_MAX = 64
# A talker alias's first word is taken as the caller's callsign when it
# looks like one: letters and digits (and a / for a portable prefix or
# suffix), at least one of each.
_CALLSIGN = re.compile(r"^(?=[A-Z0-9/]*[0-9])(?=[A-Z0-9/]*[A-Z])[A-Z0-9/]{3,12}$")

VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def user_agent() -> str:
    """The program and its version, nothing else (module docstring)."""
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        version = "0"
    return f"OpenHamShack-Radio/{version}"


class FetchFailed(Exception):
    """The source did not give a usable answer: no route, a timeout, an
    HTTP error, a short or unreadable file. Backoff, and the copy we hold
    stands."""


def _now_iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v) -> str | None:
    s = str(v or "").strip()
    return s[:FIELD_MAX] if s else None


class _Counted(io.RawIOBase):
    """A response read through a byte count, refused past `limit`."""

    def __init__(self, raw, limit: int):
        self.raw, self.limit, self.n = raw, limit, 0

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self.raw.read(len(b))
        self.n += len(data)
        if self.n > self.limit:
            raise FetchFailed("file too large")
        b[:len(data)] = data
        return len(data)


class DmrIds:
    """The two lists, their fetcher and their lookups.

        ids = DmrIds(folder, enabled=lambda: True)
        ids.user(9990001) -> {"callsign", "name", "city", "state", "country"} | None
        ids.talkgroup(91) -> "World-wide" | None
        ids.view() -> {"available", "count", "updatedUtc", "source", "talkgroups"}
        ids.run_once()       # a look at both sources (the thread's work)
    """

    def __init__(self, folder, enabled=lambda: True, clock=time.time, users_url: str = USERS_URL,
                 talkgroups_url: str = TALKGROUPS_URL, on_change=None, timeout: float = HTTP_TIMEOUT_S):
        self.dir = Path(folder)
        self.enabled = enabled
        self.clock = clock
        # $OHS_DMRIDS_BASE puts both default sources on another server
        # (tests/scratch_home.py: a closed local port, so no test can reach
        # the real lists); a URL given here wins.
        base = os.environ.get("OHS_DMRIDS_BASE", "").rstrip("/")
        if base and users_url == USERS_URL:
            users_url = base + "/static/user.csv"
        if base and talkgroups_url == TALKGROUPS_URL:
            talkgroups_url = base + "/v2/talkgroup"
        self.urls = {"users": users_url, "talkgroups": talkgroups_url}
        self.on_change = on_change
        self.timeout = timeout
        self.lock = threading.Lock()          # the lookups and the swap
        self.run_lock = threading.Lock()      # one run at a time
        self.stop_ev = threading.Event()
        self.wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.logged: set = set()
        self.state: dict[str, dict] = {"users": {}, "talkgroups": {}}
        self.db: sqlite3.Connection | None = None
        self.users_meta: dict = {}
        self.tgs: dict[int, str] = {}
        self._load()

    # ------------------------------------------------------------ disk
    @property
    def users_path(self) -> Path:
        return self.dir / USERS_DB

    def _load(self) -> None:
        try:
            got = json.loads((self.dir / STATE_FILE).read_text())
            if isinstance(got, dict):
                for k in self.state:
                    if isinstance(got.get(k), dict):
                        self.state[k] = got[k]
        except (OSError, ValueError):
            pass
        try:
            got = json.loads((self.dir / TALKGROUPS_FILE).read_text())
            self.tgs = {int(k): str(v) for k, v in (got.get("names") or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            self.tgs = {}
        with self.lock:
            self._open()

    def _open(self) -> None:
        """Open the users database read-only, if there is one (under the lock)."""
        self.db, self.users_meta = None, {}
        if not self.users_path.exists():
            return
        try:
            db = sqlite3.connect(f"{self.users_path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
            self.users_meta = dict(db.execute("SELECT k, v FROM meta").fetchall())
            self.db = db
        except sqlite3.Error as e:
            # A file that is not ours or is damaged: as if there were none,
            # and the next fetch replaces it.
            log.log(self._level(("open", str(e))), "DMR IDs: the users file could not be read (%s)", e)

    def _save_state(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / ("." + STATE_FILE + ".part")
            tmp.write_text(json.dumps(self.state, separators=(",", ":")))
            os.replace(tmp, self.dir / STATE_FILE)
        except OSError as e:
            log.log(self._level(("disk", str(e))), "DMR IDs: could not keep the fetch state: %s", e)

    # ------------------------------------------------------------ lookups
    def user(self, rid) -> dict | None:
        """What the users list says of a radio ID, or None (unknown, no
        list, or the setting off)."""
        if not self.enabled():
            return None
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return None
        if not 0 < rid <= MAX_ID:
            return None
        with self.lock:
            if self.db is None:
                return None
            try:
                row = self.db.execute("SELECT u.c, u.n, u.ci, u.s, co.name FROM u LEFT JOIN co ON co.id = u.co "
                                      "WHERE u.id = ?", (rid,)).fetchone()
            except sqlite3.Error:
                return None
        if row is None:
            return None
        return {"callsign": row[0], "name": row[1], "city": row[2], "state": row[3], "country": row[4]}

    def talkgroup(self, tg) -> str | None:
        """A talkgroup's name, or None."""
        if not self.enabled():
            return None
        try:
            return self.tgs.get(int(tg))
        except (TypeError, ValueError):
            return None

    def view(self) -> dict:
        """`dmrIds` in api/status and api/state: whether names are being
        added, how many IDs the users list holds, when it was fetched, and
        where from."""
        with self.lock:
            have = self.db is not None
            meta = dict(self.users_meta)
        on = bool(self.enabled())
        try:
            count = int(meta.get("count", 0)) if have else 0
        except ValueError:
            count = 0
        return {"available": on and have and count > 0, "count": count,
                "updatedUtc": meta.get("updatedUtc") if have else None,
                "source": meta.get("source") if have else None,
                "talkgroups": len(self.tgs)}

    # ------------------------------------------------------------ the thread
    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="radio-dmrids", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        self.wake.set()

    def nudge(self) -> None:
        """The setting was turned on: look now rather than within the hour."""
        self.wake.set()

    def close(self) -> None:
        self.stop()
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None

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
            except Exception:  # noqa: BLE001  a bug here must never reach a listener, nor end the thread
                log.warning("DMR IDs: the look failed", exc_info=True)
            self.wake.wait(CHECK_S)
            self.wake.clear()

    # ------------------------------------------------------------ logging and backoff
    def _level(self, cause) -> int:
        """INFO the first time for a cause, then DEBUG: an offline station
        would otherwise log the same line every day."""
        if cause in self.logged:
            return logging.DEBUG
        self.logged.add(cause)
        return logging.INFO

    def _failed(self, src: str, why: str) -> None:
        s = self.state[src]
        s["failures"] = int(s.get("failures", 0)) + 1
        wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** min(s["failures"] - 1, 30))
        s["until"] = self.clock() + wait
        log.log(self._level((src, why)), "DMR IDs: the %s list was not fetched (%s); next try in %.0f min",
                src, why, wait / 60)

    def _worked(self, src: str) -> None:
        s = self.state[src]
        s.pop("failures", None)
        s.pop("until", None)
        s["checkedAt"] = self.clock()

    def _held(self, src: str) -> bool:
        """Whether we hold a usable copy of a source (a damaged users file
        that would not open counts as none)."""
        if src == "users":
            with self.lock:
                return self.db is not None
        return bool(self.tgs)

    def _due(self, src: str) -> bool:
        s = self.state[src]
        now = self.clock()
        if float(s.get("until", 0.0)) > now:
            return False
        return not self._held(src) or now - float(s.get("checkedAt", 0.0)) >= REFRESH_S

    # ------------------------------------------------------------ a run
    def run_once(self) -> dict:
        """A look at each due source; returns what happened to each
        (`fetched`, `unchanged`, `failed`, `backoff`, `fresh` or `off`), for
        tests. Never raises for a network or file fault."""
        out = {}
        if not self.enabled():
            return {"users": "off", "talkgroups": "off"}
        with self.run_lock:
            for src in ("users", "talkgroups"):
                if self.stop_ev.is_set() or not self.enabled():
                    out[src] = "off"
                    continue
                s = self.state[src]
                if float(s.get("until", 0.0)) > self.clock():
                    out[src] = "backoff"
                    continue
                if not self._due(src):
                    out[src] = "fresh"
                    continue
                try:
                    out[src] = self._fetch(src)
                    self._worked(src)
                except FetchFailed as e:
                    if self.stop_ev.is_set():
                        out[src] = "off"      # the app is stopping: no fault, no backoff
                        continue
                    self._failed(src, str(e))
                    out[src] = "failed"
                self._save_state()
        if "fetched" in out.values() and self.on_change is not None:
            try:
                self.on_change(self.view())
            except Exception:  # noqa: BLE001 - the status is a courtesy
                log.warning("DMR IDs: status update failed", exc_info=True)
        return out

    def _request(self, src: str):
        s = self.state[src]
        held = self._held(src)
        headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip"}
        if held and s.get("etag"):
            headers["If-None-Match"] = s["etag"]
        if held and s.get("lastModified"):
            headers["If-Modified-Since"] = s["lastModified"]
        req = urllib.request.Request(self.urls[src], headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 304 and held:
                return None
            raise FetchFailed(f"HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            raise FetchFailed(getattr(e, "reason", None) and str(e.reason) or e.__class__.__name__) from None
        return resp

    def _fetch(self, src: str) -> str:
        resp = self._request(src)
        if resp is None:
            return "unchanged"
        with resp:
            h = resp.headers
            length = h.get("Content-Length")
            limit = MAX_USERS_BYTES if src == "users" else MAX_TALKGROUPS_BYTES
            raw = _Counted(resp, limit)
            body = gzip.GzipFile(fileobj=io.BufferedReader(raw)) if \
                (h.get("Content-Encoding") or "").lower() == "gzip" else io.BufferedReader(raw)
            try:
                if src == "users":
                    changed = self._take_users(body, raw, length)
                else:
                    changed = self._take_talkgroups(body, raw, length)
            except (OSError, EOFError, ValueError, csv.Error, sqlite3.Error, http.client.HTTPException) as e:
                raise FetchFailed(f"{e.__class__.__name__}: {e}"[:200]) from None
        s = self.state[src]
        s["etag"], s["lastModified"] = h.get("ETag"), h.get("Last-Modified")
        return "fetched" if changed else "unchanged"

    @staticmethod
    def _whole(raw: _Counted, length) -> None:
        try:
            want = int(length) if length is not None else None
        except ValueError:
            want = None
        if want is not None and raw.n != want:
            raise FetchFailed(f"cut short ({raw.n} of {want} bytes)")

    def _take_users(self, body, raw: _Counted, length) -> bool:
        """Parse radioid.net's user.csv into a new database and swap it in."""
        self.dir.mkdir(parents=True, exist_ok=True)
        part = self.dir / (USERS_DB + ".part")
        part.unlink(missing_ok=True)
        db = sqlite3.connect(part)
        try:
            db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"
                             "CREATE TABLE u(id INTEGER PRIMARY KEY, c TEXT, n TEXT, ci TEXT, s TEXT, co INTEGER);"
                             "CREATE TABLE co(id INTEGER PRIMARY KEY, name TEXT);"
                             "CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);")
            rows = csv.reader(io.TextIOWrapper(body, encoding="utf-8", errors="replace", newline=""))
            head = [c.strip().upper() for c in next(rows, [])]
            if "RADIO_ID" not in head or "CALLSIGN" not in head:
                raise FetchFailed("not radioid.net's user list")
            col = {k: head.index(k) if k in head else None
                   for k in ("RADIO_ID", "CALLSIGN", "FIRST_NAME", "CITY", "STATE", "COUNTRY")}
            countries: dict[str, int] = {}

            def cell(r, k):
                i = col[k]
                return _clean(r[i]) if i is not None and i < len(r) else None

            batch, n = [], 0
            for r in rows:
                try:
                    rid = int(r[col["RADIO_ID"]])
                except (ValueError, IndexError):
                    continue
                call = cell(r, "CALLSIGN")
                if not 0 < rid <= MAX_ID or call is None:
                    continue
                country = cell(r, "COUNTRY")
                cid = None
                if country is not None:
                    cid = countries.setdefault(country, len(countries) + 1)
                batch.append((rid, call.upper(), cell(r, "FIRST_NAME"), cell(r, "CITY"), cell(r, "STATE"), cid))
                if len(batch) >= BATCH:
                    db.executemany("INSERT OR REPLACE INTO u VALUES (?,?,?,?,?,?)", batch)
                    n += len(batch)
                    batch = []
                if self.stop_ev.is_set():
                    raise FetchFailed("stopping")
            db.executemany("INSERT OR REPLACE INTO u VALUES (?,?,?,?,?,?)", batch)
            self._whole(raw, length)
            count = db.execute("SELECT COUNT(*) FROM u").fetchone()[0]
            if not count:
                # A file with a header and nothing else is no reason to
                # forget every name we knew.
                raise FetchFailed("the list was empty")
            db.executemany("INSERT INTO co VALUES (?,?)", [(i, name) for name, i in countries.items()])
            db.executemany("INSERT INTO meta VALUES (?,?)", [
                ("count", str(count)), ("updatedUtc", _now_iso(self.clock())), ("source", "radioid.net")])
            db.commit()
            db.close()
            db = None
            self._swap(part)
            log.info("DMR IDs: %d radio IDs fetched", count)
            return True
        finally:
            if db is not None:
                db.close()
            part.unlink(missing_ok=True)

    def _swap(self, part: Path) -> None:
        """The new users database in place of the old. Under the lookup
        lock: a lookup sees the old file or the new one, never a half. The
        reader is closed first because Windows cannot rename over an open
        file (POSIX could, but one path for both is simpler to trust).
        The build ran with synchronous off, so the file is flushed first:
        a power cut after the rename must not leave a half-written list
        under the live name."""
        with open(part, "rb+") as fh:
            os.fsync(fh.fileno())
        with self.lock:
            if self.db is not None:
                self.db.close()
                self.db = None
            try:
                os.replace(part, self.users_path)
            finally:
                self._open()

    def _take_talkgroups(self, body, raw: _Counted, length) -> bool:
        """Brandmeister's {"91": "World-wide", ...}: kept if it changed."""
        data = body.read()
        self._whole(raw, length)
        got = json.loads(data.decode("utf-8", "replace"))
        if not isinstance(got, dict):
            raise FetchFailed("not a talkgroup list")
        names = {}
        for k, v in got.items():
            try:
                tg = int(k)
            except (TypeError, ValueError):
                continue
            name = _clean(v)
            if 0 < tg <= MAX_ID and name is not None:
                names[tg] = name
        if not names:
            raise FetchFailed("the list was empty")
        if names == self.tgs:
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (TALKGROUPS_FILE + ".part")
        tmp.write_text(json.dumps({"source": "brandmeister.network", "updatedUtc": _now_iso(self.clock()),
                                   "names": {str(k): v for k, v in sorted(names.items())}},
                                  separators=(",", ":"), ensure_ascii=False))
        os.replace(tmp, self.dir / TALKGROUPS_FILE)
        self.tgs = names
        log.info("DMR IDs: %d talkgroup names fetched", len(names))
        return True


# ---------------------------------------------------------------- naming
def alias_callsign(alias) -> str | None:
    """The callsign a talker alias starts with ("MX0TST Test" -> "MX0TST"),
    or None when its first word does not look like one."""
    words = str(alias or "").split()
    if not words:
        return None
    w = words[0].upper()
    return w if _CALLSIGN.match(w) else None


def annotate(fields: dict, ids: DmrIds | None) -> dict:
    """A DMR slot (meta) or result (frame fields) with its IDs named, where
    known: `srcCallsign`, `srcName` and `srcCountry` for `src`, `dstName`
    for a talkgroup `dst`. The setting off: the fields exactly as they
    were before this module. No list yet (offline): only what the stream
    itself says, a callsign at the start of the talker alias.

    **The talker alias wins.** It is what the caller's own radio says now,
    where the list says who registered the ID - someone else's radio, or a
    club's, sends its own alias. So a callsign at the start of the alias is
    `srcCallsign`, and the list's name and country are added only when the
    list gives that ID the same callsign (they would otherwise describe
    the ID's owner, not the caller). An alias with no callsign in it
    ("Bob's handheld") leaves the list's callsign standing."""
    if ids is None or not ids.enabled():
        return fields
    out = dict(fields)
    src = fields.get("src")
    entry = ids.user(src) if src is not None else None
    from_alias = alias_callsign(fields.get("alias"))
    if from_alias is not None:
        out["srcCallsign"] = from_alias
        if entry is not None and (entry.get("callsign") or "").upper() == from_alias:
            _person(out, entry)
    elif entry is not None and entry.get("callsign"):
        out["srcCallsign"] = entry["callsign"]
        _person(out, entry)
    dst = fields.get("dst")
    group = fields.get("callType") == "group" if "callType" in fields else bool(fields.get("group"))
    if dst is not None and group:
        name = ids.talkgroup(dst)
        if name is not None:
            out["dstName"] = name
    return out


def _person(out: dict, entry: dict) -> None:
    if entry.get("name"):
        out["srcName"] = entry["name"]
    if entry.get("country"):
        out["srcCountry"] = entry["country"]
