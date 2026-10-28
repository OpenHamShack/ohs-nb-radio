"""The map a client draws ships on (Brian, 28/10/2026; docs/SERVER-API.md
"Map"): land that is always there, bundled, and OpenStreetMap's own map
pictures when the controller has internet - fetched and cached here, so a
TV never touches the internet.

    land = Land.load()                          # the bundled data, read once
    land.geojson((w, s, e, n), detail="auto")    # GET api/map/land
    tiles = TileCache(folder, enabled, cap_mb, fetch=None)
    tiles.get(z, x, y) -> (png, max_age) | None # GET api/map/tiles/{z}/{x}/{y}.png
    info(...)                                   # GET api/map/info

**Land** is OpenStreetMap's land polygons for Great Britain, Ireland and
their islands (data/mapland, made by tools/mapland-build.py, which says why
OSM's rather than Natural Earth's and what detail): two levels of polygons
cut into cells at build time, so a bounding box is answered with the cells
it touches and the server does no geometry. A client fills them and never
strokes them (the cut edges would show).

**Tiles: the OSM Foundation's tile policy**
(operations.osmfoundation.org/policies/tiles, read 28/10/2026). It does not
forbid a caching proxy - "we generally do not recommend" one, and one must
identify itself and honour the caching headers - and it forbids bulk and
offline downloading. So:

- **Only what a client asks for.** A tile is fetched when a client asks for
  it, never before: no margin around the view, no zoom levels ahead, no
  area kept for offline use. The policy defines bulk as "any pre-emptive
  fetching of tiles other than those a user is actively viewing", so
  Brian's "plus a small margin" was left out.
- **One clear User-Agent**, "OpenHamShack-Radio/<version>
  (+https://openhamshack.com)": the program and where to find it, nothing
  about the station. No cookies, no Referer (we are not a browser), never a
  no-cache header; `https://tile.openstreetmap.org/{z}/{x}/{y}.png` exactly,
  as the policy names it.
- **The caching headers honoured.** A tile is fresh for its `max-age` less
  its `Age` - but at least MIN_FRESH_S, because the tile servers' CDN often
  answers with an Age past the max-age (28/10/2026: max-age 94655, age
  402958), which read literally would revalidate every tile on every look.
  Stale, it is served while it is revalidated in the background within
  `stale-while-revalidate`, and revalidated with If-None-Match and
  If-Modified-Since (a 304 costs the servers nothing). When the fetch
  fails it is served within `stale-if-error` (RFC 5861), else not at all.
- **Two fetches at a time, and backoff.** A failure (no route, a timeout,
  a server error) stops all fetching for BACKOFF_FIRST_S, doubling to
  BACKOFF_MAX_S: offline, a map costs one failed attempt every so often,
  never one per tile. A 4xx for one tile marks that tile alone.
- **A size cap** (`mapTileCacheMb`): the least recently shown tiles go
  first.
- **The setting off** (`mapOnlineTiles`) means no traffic at all and no
  tile served, cached or not: the land map alone, as offline.
- **Attribution**: "(c) OpenStreetMap contributors", in api/map/info for
  every client to draw whenever a tile shows - and the land map is OSM's
  too, so whenever the map shows at all.

The route answers 404 when there is no tile to give, and the client draws
the bundled land instead. A request waits up to TILE_WAIT_S for a tile
being fetched, so a client with internet gets its map in one request.

Nothing here runs for a test's throw-away radio: it has no fetcher unless a
test gives it one, so no test can ask the real internet.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

log = logging.getLogger("ohsradio.mapdata")

DATA = Path(__file__).resolve().parent / "data" / "mapland"
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = {"text": "© OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright"}
# The fine level answers views up to this many degrees across (either way);
# wider ones get the coarse level. At 2.5 degrees the fine level is about
# 25,000 points, a few hundred kB of GeoJSON - what a TV parses in well
# under a second.
FINE_MAX_SPAN_DEG = 2.5
MAX_ZOOM = 18
TILE_WAIT_S = 4.0
HTTP_TIMEOUT_S = 8.0
FETCHERS = 2
MIN_FRESH_S = 86_400.0
BACKOFF_FIRST_S = 60.0
BACKOFF_MAX_S = 3600.0
# A tile the server refused (404, 403) is not asked for again for this long.
REFUSED_S = 86_400.0
MAX_TILE_BYTES = 1 << 20
INDEX_SAVE_S = 30.0


def user_agent() -> str:
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        version = "0"
    return f"OpenHamShack-Radio/{version} (+https://openhamshack.com)"


# ---------------------------------------------------------------- land
class Land:
    """The bundled land polygons (module docstring)."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.scale = float(doc["scale"])
        self.bounds = tuple(doc["bounds"])
        self.levels = doc["levels"]

    _loaded: "Land | None" = None
    _lock = threading.Lock()

    @classmethod
    def load(cls) -> "Land | None":
        """The data, read once (about 0.2 s); None when the file is missing
        or broken - the map then has no land, and says so in api/map/info."""
        with cls._lock:
            if cls._loaded is None:
                try:
                    raw = gzip.decompress((DATA / "land.json.gz").read_bytes())
                    cls._loaded = cls(json.loads(raw))
                except (OSError, ValueError, KeyError) as e:
                    log.warning("no bundled land for the map: %s", e)
                    return None
            return cls._loaded

    def info(self) -> dict:
        d = self.doc
        return {"source": d["source"], "date": d["date"], "licence": d["licence"], "bounds": list(self.bounds),
                "levels": {name: {"toleranceDeg": lv["toleranceDeg"], "cellDeg": lv["cell"],
                                  "maxSpanDeg": FINE_MAX_SPAN_DEG if name == "fine" else 360.0}
                           for name, lv in self.levels.items()}}

    def choose(self, bbox: tuple, detail: str) -> str:
        if detail in self.levels:
            return detail
        w, s, e, n = bbox
        return "fine" if max(e - w, n - s) <= FINE_MAX_SPAN_DEG else "coarse"

    def polygons(self, bbox: tuple, detail: str = "auto") -> tuple[str, list]:
        """(level, polygons) of every cell the box (west, south, east,
        north, degrees) touches: each polygon a list of rings, each ring
        the cell's delta-coded integers (tools/mapland-build.py)."""
        level = self.choose(bbox, detail)
        lv = self.levels[level]
        cell = float(lv["cell"])
        w0, s0 = self.bounds[0], self.bounds[1]
        w, s, e, n = bbox
        out = []
        i0, i1 = math.floor((w - w0) / cell), math.floor((e - w0) / cell)
        j0, j1 = math.floor((s - s0) / cell), math.floor((n - s0) / cell)
        q = 1 / self.scale
        for i in range(max(i0, 0), i1 + 1):
            for j in range(max(j0, 0), j1 + 1):
                key = f"{round((w0 + i * cell) * q)},{round((s0 + j * cell) * q)}"
                out.extend(lv["cells"].get(key, ()))
        return level, out

    def ring_coords(self, ring: list) -> list:
        """A delta-coded ring as [[lon, lat], ...] degrees, closed."""
        sc = self.scale
        x, y = ring[0], ring[1]
        pts = [[round(x * sc, 4), round(y * sc, 4)]]
        for k in range(2, len(ring), 2):
            x += ring[k]
            y += ring[k + 1]
            pts.append([round(x * sc, 4), round(y * sc, 4)])
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return pts

    def geojson(self, bbox: tuple, detail: str = "auto") -> dict:
        level, polys = self.polygons(bbox, detail)
        coords = [[self.ring_coords(r) for r in p] for p in polys]
        return {"type": "FeatureCollection", "detail": level, "attribution": ATTRIBUTION,
                "features": [{"type": "Feature", "properties": {"kind": "land"},
                              "geometry": {"type": "MultiPolygon", "coordinates": coords}}] if coords else []}

    def compact(self, bbox: tuple, detail: str = "auto") -> dict:
        level, polys = self.polygons(bbox, detail)
        return {"detail": level, "scale": self.scale, "attribution": ATTRIBUTION, "polygons": polys}


def parse_bbox(text: str | None) -> tuple | None:
    """"w,s,e,n" in degrees, west below east, south below north, inside
    the world; None for anything else."""
    try:
        w, s, e, n = (float(v) for v in str(text).split(","))
    except (TypeError, ValueError):
        return None
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        return None
    return w, s, e, n


def point_on_land(land: Land, lat: float, lon: float) -> bool:
    """Whether the fine level puts a point on land (even-odd rule over the
    point's cell): what the simulator's ships are checked against."""
    _, polys = land.polygons((lon, lat, lon, lat), "fine")
    inside = False
    for p in polys:
        for r in p:
            pts = land.ring_coords(r)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                    inside = not inside
    return inside


# ---------------------------------------------------------------- tiles
def _now() -> float:
    return time.time()


def default_fetch(url: str, headers: dict) -> tuple[int, dict, bytes]:
    """One GET: (status, headers lower-cased, body). 304 and 4xx/5xx come
    back as statuses; no route or a timeout raises OSError."""
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener()   # no cookie handler: nothing kept between requests
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT_S) as r:
            body = r.read(MAX_TILE_BYTES + 1)
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, b""


def _cache_control(h: dict) -> dict:
    out = {}
    for part in (h.get("cache-control") or "").split(","):
        k, _, v = part.strip().partition("=")
        if k:
            try:
                out[k.lower()] = int(v) if v else 0
            except ValueError:
                out[k.lower()] = 0
    return out


def freshness(h: dict, now: float) -> tuple[float, float, float]:
    """(fresh until, serve-stale-while-revalidating until, serve-stale-on-
    error until), epoch seconds, from a response's headers."""
    cc = _cache_control(h)
    try:
        age = float(h.get("age") or 0)
    except ValueError:
        age = 0.0
    if "max-age" in cc:
        life = cc["max-age"] - age
    elif h.get("expires"):
        try:
            life = parsedate_to_datetime(h["expires"]).timestamp() - now
        except (TypeError, ValueError):
            life = 0.0
    else:
        # No headers to read: the policy's own floor.
        life = 7 * 86_400.0
    fresh = now + max(life, MIN_FRESH_S)
    return fresh, fresh + cc.get("stale-while-revalidate", 0), fresh + cc.get("stale-if-error", 0)


class TileCache:
    """OSM tiles fetched on request and kept on disk (module docstring).

    `enabled()` is read before every fetch and every answer (the
    `mapOnlineTiles` setting); `cap_mb()` the size cap. `fetch` is the one
    way out (default_fetch for the operator's program; None: never, as
    offline)."""

    def __init__(self, folder: Path, enabled, cap_mb, fetch=None):
        self.dir = Path(folder)
        self.enabled = enabled
        self.cap_mb = cap_mb
        self.fetch = fetch
        self.lock = threading.Lock()
        self.index: dict[str, dict] = {}
        self.dirty = False
        self.saved_at = 0.0
        self.pending: dict[str, threading.Event] = {}
        self.q: queue.Queue = queue.Queue()
        self.backoff_until = 0.0
        self.backoff_s = 0.0
        self.last_ok: float | None = None
        self.last_error: str | None = None
        self.requests = 0
        self.workers: list[threading.Thread] = []
        self._load()

    # -- the index -------------------------------------------------------
    def _load(self) -> None:
        try:
            self.index = json.loads((self.dir / "index.json").read_text())
        except (OSError, ValueError):
            self.index = {}
        # A tile whose file went is no tile.
        self.index = {k: v for k, v in self.index.items() if isinstance(v, dict) and (self.dir / k).exists()}

    def save(self, force: bool = False) -> None:
        with self.lock:
            if not self.dirty or (not force and _now() - self.saved_at < INDEX_SAVE_S):
                return
            data = json.dumps(self.index, separators=(",", ":"))
            self.dirty, self.saved_at = False, _now()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / "index.json.tmp"
            tmp.write_text(data)
            os.replace(tmp, self.dir / "index.json")
        except OSError as e:
            log.warning("map tiles: could not save the index: %s", e)

    def stats(self) -> dict:
        with self.lock:
            size = sum(int(v.get("size", 0)) for v in self.index.values())
            n = len(self.index)
        now = _now()
        # "Online": tiles may be fetched now - the setting on, a way out, not
        # backing off after a failure. Not a promise that the next one comes.
        online = self.fetch is not None and bool(self.enabled()) and now >= self.backoff_until
        return {"enabled": bool(self.enabled()), "online": online,
                "cached": n, "cachedMb": round(size / 1e6, 1), "capMb": int(self.cap_mb()),
                "backoffS": max(0, round(self.backoff_until - now)) if self.backoff_until > now else 0,
                "lastError": self.last_error}

    # -- answering ---------------------------------------------------------
    @staticmethod
    def key(z: int, x: int, y: int) -> str:
        return f"{z}/{x}/{y}.png"

    @staticmethod
    def valid(z: int, x: int, y: int) -> bool:
        return 0 <= z <= MAX_ZOOM and 0 <= x < (1 << z) and 0 <= y < (1 << z)

    def get(self, z: int, x: int, y: int, wait: float = TILE_WAIT_S) -> tuple[bytes, int] | None:
        """The tile's PNG and how long a client may keep it (seconds), or
        None (no tile: the client draws the land). May wait up to `wait`
        for a fetch."""
        if not self.valid(z, x, y) or not self.enabled():
            return None
        k = self.key(z, x, y)
        now = _now()
        with self.lock:
            meta = self.index.get(k)
            if meta is not None:
                meta["used"] = now
                self.dirty = True
        if meta is not None and meta.get("refused"):
            if now < meta["refused"]:
                return None
            meta = None
        if meta is not None:
            if now < meta["fresh"]:
                return self._read(k, meta, now)
            if now < meta["swr"]:
                self._queue(k)
                return self._read(k, meta, now)
        if not self._queue(k):
            # Offline (or the setting off, or no fetcher): only what the
            # stale-if-error allowance still covers.
            return self._read(k, meta, now) if meta is not None and now < meta["sie"] else None
        ev = self.pending.get(k)
        if ev is not None:
            ev.wait(wait)
        with self.lock:
            meta = self.index.get(k)
        now = _now()
        if meta is None or meta.get("refused"):
            return None
        if now < meta["fresh"] or now < meta["sie"]:
            return self._read(k, meta, now)
        return None

    def _read(self, k: str, meta: dict, now: float) -> tuple[bytes, int] | None:
        try:
            png = (self.dir / k).read_bytes()
        except OSError:
            with self.lock:
                self.index.pop(k, None)
                self.dirty = True
            return None
        return png, int(max(0.0, min(meta["fresh"] - now, 86_400.0)))

    # -- fetching ----------------------------------------------------------
    def _queue(self, k: str) -> bool:
        """Ask for tile `k`; False when nothing may be fetched now."""
        if self.fetch is None or not self.enabled() or _now() < self.backoff_until:
            return False
        with self.lock:
            if k not in self.pending:
                self.pending[k] = threading.Event()
                self.q.put(k)
            self._start_workers()
        return True

    def _start_workers(self) -> None:
        self.workers = [t for t in self.workers if t.is_alive()]
        while len(self.workers) < FETCHERS:
            t = threading.Thread(target=self._work, name="ohsradio-maptiles", daemon=True)
            t.start()
            self.workers.append(t)

    def _work(self) -> None:
        while True:
            try:
                k = self.q.get(timeout=30.0)
            except queue.Empty:
                return
            try:
                self._fetch_one(k)
            except Exception:  # noqa: BLE001 - one tile's fault never ends the worker
                log.exception("map tiles: fetching %s", k)
            finally:
                with self.lock:
                    ev = self.pending.pop(k, None)
                if ev is not None:
                    ev.set()

    def _fetch_one(self, k: str) -> None:
        if not self.enabled() or _now() < self.backoff_until or self.fetch is None:
            return
        z, x, rest = k.split("/")
        url = TILE_URL.format(z=z, x=x, y=rest[:-4])
        with self.lock:
            old = dict(self.index.get(k) or {})
        headers = {"User-Agent": user_agent()}
        if old.get("etag"):
            headers["If-None-Match"] = old["etag"]
        if old.get("lastModified"):
            headers["If-Modified-Since"] = old["lastModified"]
        self.requests += 1
        try:
            status, h, body = self.fetch(url, headers)
        except OSError as e:
            self._failed(f"{type(e).__name__}: {e}")
            return
        now = _now()
        if status == 304 and old.get("fresh") is not None:
            fresh, swr, sie = freshness(h, now)
            with self.lock:
                old.update(fresh=fresh, swr=swr, sie=sie, used=now)
                self.index[k] = old
                self.dirty = True
            self._ok()
            return
        if status == 200 and body and len(body) <= MAX_TILE_BYTES and body[:8] == b"\x89PNG\r\n\x1a\n":
            fresh, swr, sie = freshness(h, now)
            path = self.dir / k
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, path)
            with self.lock:
                self.index[k] = {"fresh": fresh, "swr": swr, "sie": sie, "used": now, "size": len(body),
                                 "etag": h.get("etag"), "lastModified": h.get("last-modified")}
                self.dirty = True
            self._ok()
            self._trim()
            return
        if 400 <= status < 500 and status != 429:
            with self.lock:
                self.index[k] = {"refused": now + REFUSED_S, "used": now, "size": 0}
                self.dirty = True
            log.info("map tiles: %s refused (%d)", url, status)
            return
        self._failed(f"HTTP {status}")

    def _ok(self) -> None:
        self.backoff_s = 0.0
        self.last_ok = _now()
        self.last_error = None

    def _failed(self, why: str) -> None:
        self.backoff_s = min(BACKOFF_MAX_S, self.backoff_s * 2 if self.backoff_s else BACKOFF_FIRST_S)
        self.backoff_until = _now() + self.backoff_s
        if self.last_error != why:
            log.info("map tiles: %s; no fetching for %.0f s", why, self.backoff_s)
        self.last_error = why

    def _trim(self) -> None:
        cap = max(1, int(self.cap_mb())) * 1_000_000
        with self.lock:
            total = sum(int(v.get("size", 0)) for v in self.index.values())
            if total <= cap:
                return
            gone = []
            for k, v in sorted(self.index.items(), key=lambda kv: kv[1].get("used", 0)):
                if total <= cap * 0.9:
                    break
                total -= int(v.get("size", 0))
                gone.append(k)
            for k in gone:
                self.index.pop(k, None)
            self.dirty = True
        for k in gone:
            try:
                (self.dir / k).unlink()
            except OSError:
                pass


def tile_of(lat: float, lon: float, z: int) -> tuple[int, int]:
    """The Web Mercator tile holding a point (the slippy-map formula)."""
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)
