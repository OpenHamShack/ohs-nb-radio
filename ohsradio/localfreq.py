"""Local frequencies: what there is to listen to near the station
(Brian, 23/10/2026; docs/SERVER-API.md "Local frequencies").

From the station's Maidenhead locator (the station profile on a
controller, Radio's own Station settings on a desktop: both arrive as the
engine's `locator` setting, ohscore/station.py) this lists the listening
frequencies within a radius, nearest first: airfields and area control,
coast stations, marinas and port operations, and the fixed channel
tables (marine VHF, PMR446, CB, LPD433, the NCDXF beacons), plus the
operator's own list ("my frequencies").

Where the data comes from, and why it is kept the way it is:

- Every source is a file of its own in ohsradio/data/localfreq/, with its
  own licence notice beside it (`<file>.LICENCE.txt`) and its attribution
  inside it, because the licences differ and cannot be mixed: OurAirports
  is public domain, openAIP CC BY-NC 4.0, HM Coastguard's channels the
  Open Government Licence, the OpenStreetMap extract the ODbL (a derived
  database, so that file is published under the ODbL itself). The
  listing carries every attribution, so a client shows them.
- The bundled files are snapshots made by tools/localfreq-build.py with
  the same builders as Refresh below; each records its date and URLs.
- Refresh (an administrator's action, never at start-up and never
  required: a controller may have no route out) downloads newer copies
  into the data folder. OurAirports is the world, so a fresh copy
  replaces the bundled one; OpenStreetMap and openAIP are fetched around
  the station, so a fresh copy is added to the bundled area rather than
  replacing it (a station that later widens its radius keeps what the
  release carried).
- "My frequencies" is data, not settings: it lives in its own file in the
  data folder (the station's backups carry it), is edited through the API
  at Control level so Remote can add a repeater from a TV, and holds no
  personal fields - a field that is not in MINE_FIELDS is refused rather
  than stored, so a person's name cannot creep in as "notes2".

Nothing here transmits or touches a radio: a client tunes by setting the
dial, mode and step it is given.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import io
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from pathlib import Path

from ohscore.countries import distance_bearing, locator_position

from ohsradio import bands
from ohsradio.i18n import _

log = logging.getLogger("ohsradio.localfreq")

BUNDLED = Path(__file__).resolve().parent / "data" / "localfreq"
REFRESHED = "localfreq"                 # the folder in the data folder Refresh writes to
MINE_FILE = "local-frequencies-mine.json"

# Listing order: categories in this order, nearest first inside each.
CATEGORIES = ("airband", "enroute", "marine", "pmr", "cb", "lpd", "beacon", "mine")
# Each source's file, in the order they are read. `merge` sources add a
# refreshed copy to the bundled one (fetched around the station); the
# others are replaced by it (fetched whole).
SOURCES = {
    "ourairports": {"file": "ourairports.json.gz", "merge": False, "refresh": True},
    "openaip": {"file": "openaip.json", "merge": True, "refresh": True},
    "itu-marine": {"file": "itu-marine.json", "merge": False, "refresh": False},
    "hmcg": {"file": "hmcg.json", "merge": False, "refresh": False},
    "osm-marine": {"file": "osm-marine.json", "merge": True, "refresh": True},
    "channels": {"file": "channels.json", "merge": False, "refresh": False},
    "ncdxf": {"file": "ncdxf.json", "merge": False, "refresh": False},
}

DEFAULT_RADIUS_KM = 100
RADIUS_MIN_KM, RADIUS_MAX_KM = 1, 2000

OURAIRPORTS_URLS = ("https://davidmegginson.github.io/ourairports-data/airports.csv",
                    "https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OPENAIP_URL = "https://api.core.openaip.net/api/airspaces"
# Overpass asks for a User-Agent that names the program (406 without one);
# it names the program and its site, never a person.
USER_AGENT = "OpenHamShack-Radio-localfreq/1 (+https://openhamshack.com/)"

ATTRIBUTION = {
    "ourairports": {"source": "OurAirports", "licence": "Public domain",
                    "text": "Airfield frequencies from OurAirports (public domain)",
                    "url": "https://ourairports.com/data/"},
    "openaip": {"source": "openAIP", "licence": "CC BY-NC 4.0",
                "text": "Contains data from openAIP (www.openaip.net), CC BY-NC 4.0",
                "url": "https://www.openaip.net/"},
    "osm-marine": {"source": "OpenStreetMap", "licence": "ODbL 1.0",
                   "text": "Contains information from OpenStreetMap, which is made available here under the Open "
                           "Database License (ODbL)",
                   "url": "https://www.openstreetmap.org/copyright"},
}


# ---------------------------------------------------------------- geometry
def point_in_polygon(lat: float, lon: float, ring: list) -> bool:
    """Ray casting on latitude and longitude: good enough for an airspace
    a few hundred km across, which is all openAIP has near a station."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def place_of(entry: dict, here: tuple[float, float]) -> tuple[float, float] | None:
    """(distance km, bearing) from `here` to an entry: its point, or for
    an area 0 km inside it and else its nearest corner, the bearing to its
    middle. None for an entry with no position (a channel table)."""
    if entry.get("area"):
        ring = entry["area"]
        clat = sum(p[0] for p in ring) / len(ring)
        clon = sum(p[1] for p in ring) / len(ring)
        brg = distance_bearing(here[0], here[1], clat, clon)[1]
        if point_in_polygon(here[0], here[1], ring):
            return 0.0, brg
        return min(distance_bearing(here[0], here[1], p[0], p[1])[0] for p in ring), brg
    if entry.get("lat") is None or entry.get("lon") is None:
        return None
    return distance_bearing(here[0], here[1], float(entry["lat"]), float(entry["lon"]))


# ---------------------------------------------------------------- NCDXF
def ncdxf_now(table: dict, t: float) -> dict:
    """Which beacon is on each band at UTC `t` (seconds since the epoch).

    The International Beacon Project's schedule: each of the 18 beacons
    sends for 10 s on 14.100 MHz, then moves up to 18.110, 21.150, 24.930
    and 28.200, so the whole cycle is 3 minutes from 00:00:00 UTC and on
    band b slot s carries beacon (s - b) mod 18 (4U1UN on 14.100 at the top
    of every third minute, YV5B on 18.110 then)."""
    beacons = table["beacons"]
    slot_s, freqs = int(table.get("slotSeconds", 10)), table["frequencies"]
    n = len(beacons)
    slot = int(t // slot_s) % n
    now = {}
    for b, f in enumerate(freqs):
        bc = beacons[(slot - b) % n]
        now[str(int(f))] = {"call": bc["call"], "location": bc["location"]}
    return now


def ncdxf_view(table: dict, t: float) -> dict:
    slot_s = int(table.get("slotSeconds", 10))
    return {"now": ncdxf_now(table, t), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
            "nextChangeS": round(slot_s - (t % slot_s), 1), "slotSeconds": slot_s,
            "cycleSeconds": slot_s * len(table["beacons"]), "frequencies": [int(f) for f in table["frequencies"]],
            "schedule": [{"slot": i, "call": b["call"], "location": b["location"]}
                         for i, b in enumerate(table["beacons"])],
            "credit": table.get("credit", "")}


# ---------------------------------------------------------------- reading the files
def read_file(path: Path) -> dict:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError(_("{name}: not a local-frequencies file").format(name=path.name))
    return data


def expand(data: dict) -> list[dict]:
    """A file's entries, one per frequency. An entry may carry `freqs`
    ([[hz, sub, step?], ...]) for one place with several, and the file
    `defaults` for what most entries share (category, mode, step), which
    keeps the bundled airfields to a few hundred kB. A malformed entry is
    skipped and counted, never the whole file."""
    src = data.get("source", "")
    dflt = data.get("defaults") or {}
    out, bad = [], 0
    for e in data["entries"]:
        try:
            base = {**dflt, **{k: v for k, v in e.items() if k != "freqs"}}
            rows = e.get("freqs") or [[e["freqHz"], e.get("sub", ""), e.get("step")]]
            for row in rows:
                hz = int(row[0])
                sub = str(row[1]) if len(row) > 1 and row[1] is not None else str(base.get("sub", ""))
                step = row[2] if len(row) > 2 and row[2] is not None else base.get("step")
                cat = base["category"]
                if cat not in CATEGORIES or hz <= 0 or not base.get("name"):
                    raise ValueError(cat)
                item = {"category": cat, "name": str(base["name"]), "sub": sub, "freqHz": hz,
                        "mode": str(base.get("mode", "fm")), "source": src, "ref": str(base.get("ref", ""))}
                if step:
                    item["step"] = int(step)
                if base.get("area"):
                    item["area"] = [(float(p[0]), float(p[1])) for p in base["area"]]
                elif base.get("lat") is not None:
                    item["lat"], item["lon"] = float(base["lat"]), float(base["lon"])
                out.append(item)
        except (KeyError, TypeError, ValueError, IndexError):
            bad += 1
    if bad:
        log.warning("%s: %d malformed entries skipped", src, bad)
    return out


def attribution_of(data: dict) -> dict:
    a = data.get("attribution") or {}
    return {"source": str(a.get("source", "")), "text": str(a.get("text", "")), "licence": str(a.get("licence", "")),
            "url": str(a.get("url", ""))}


# ---------------------------------------------------------------- my frequencies
MINE_FIELDS = ("name", "freqHz", "mode", "category", "locator", "sub", "notes")
MINE_MAX = 500
NAME_MAX, SUB_MAX, NOTES_MAX, CATEGORY_MAX = 60, 60, 300, 30
FREQ_MIN, FREQ_MAX = 10_000, 10_000_000_000
CATEGORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class Invalid(ValueError):
    """A my-frequencies entry the API refuses (400), with the field."""

    def __init__(self, text: str, field: str = ""):
        super().__init__(text)
        self.field = field


def norm_locator(loc: str) -> str:
    """IO75rl -> IO75RL, as the station profile writes it (SERVICES.md 2.1)."""
    return (loc or "").strip().upper()


def _text(v, field: str, most: int, need: bool) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise Invalid(_("{field} must be text").format(field=field), field)
    v = v.strip()
    if need and not v:
        raise Invalid(_("{field} is needed").format(field=field), field)
    if len(v) > most:
        raise Invalid(_("{field} may be at most {n} characters").format(field=field, n=most), field)
    if CONTROL_RE.search(v):
        raise Invalid(_("{field} may not hold line breaks or control characters").format(field=field), field)
    return v


def clean_mine(body: dict, modes, old: dict | None = None) -> dict:
    """One my-frequencies entry from a request: every field checked, the
    unknown refused. `old` is the entry being edited (PUT may give only
    what changes)."""
    if not isinstance(body, dict):
        raise Invalid(_("Send a JSON object"))
    extra = sorted(k for k in body if k not in MINE_FIELDS and k != "id")
    if extra:
        raise Invalid(_("Not a field of my frequencies: {fields}").format(fields=", ".join(extra)), extra[0])
    b = {**(old or {}), **body}
    e = {"name": _text(b.get("name"), "name", NAME_MAX, True)}
    f = b.get("freqHz")
    if isinstance(f, bool) or not isinstance(f, (int, float)) or (isinstance(f, float) and not f.is_integer()):
        raise Invalid(_("freqHz must be a whole number of hertz"), "freqHz")
    if not FREQ_MIN <= int(f) <= FREQ_MAX:
        raise Invalid(_("freqHz must be between 10 kHz and 10 GHz"), "freqHz")
    e["freqHz"] = int(f)
    mode = b.get("mode")
    if not isinstance(mode, str) or mode.strip().lower() not in modes:
        raise Invalid(_("mode must be one of {modes}").format(modes=", ".join(modes)), "mode")
    e["mode"] = mode.strip().lower()
    cat = _text(b.get("category") or "other", "category", CATEGORY_MAX, True)
    if not CATEGORY_RE.match(cat):
        raise Invalid(_("category may hold letters, digits, spaces, '-' and '_'"), "category")
    e["category"] = cat.lower()
    loc = _text(b.get("locator"), "locator", 8, False)
    if loc:
        if locator_position(loc) is None:
            raise Invalid(_("locator must be a Maidenhead locator of 4, 6 or 8 characters"), "locator")
        loc = norm_locator(loc)
    e["locator"] = loc
    e["sub"] = _text(b.get("sub"), "sub", SUB_MAX, False)
    e["notes"] = _text(b.get("notes"), "notes", NOTES_MAX, False)
    return e


class MineStore:
    """The operator's own list, one JSON file in the data folder. Written
    whole and atomically (a temporary file renamed over it), under a lock:
    two Remotes editing at once each see the other's change afterwards."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        # The file as last read, by its stamp: the dial label asks on
        # every change of the dial, and a stat is all that costs while the
        # file stands still. The stamp has the inode and size beside the
        # time because a write is a rename over the file, and two inside
        # one tick of the file system's clock would otherwise look alike.
        self._seen: tuple | None = None
        self._rows: list[dict] = []
        # Called (no arguments, outside the lock) after every change, so
        # Radio's dial label follows an entry added on the dial at once
        # rather than at the next turn of it.
        self.on_change = None

    def entries(self) -> list[dict]:
        with self.lock:
            return [dict(e) for e in self._read()]

    def _read(self) -> list[dict]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return []
        except OSError as e:
            log.warning("my frequencies unreadable, listed as empty: %s", e)
            return []
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        if stamp == self._seen:
            return self._rows
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            log.warning("my frequencies unreadable, listed as empty: %s", e)
            return []
        self._rows = [e for e in data.get("entries", []) if isinstance(e, dict) and e.get("id")]
        self._seen = stamp
        return self._rows

    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001  the edit is saved whatever a listener does
                log.exception("my frequencies listener")

    def _write(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": 1, "entries": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, body: dict, modes) -> dict:
        e = clean_mine(body, modes)
        with self.lock:
            entries = list(self._read())
            if len(entries) >= MINE_MAX:
                raise Invalid(_("My frequencies holds at most {n} entries").format(n=MINE_MAX))
            e = {"id": "m" + secrets.token_hex(4), **e}
            entries.append(e)
            self._write(entries)
        self._changed()
        return e

    def update(self, eid: str, body: dict, modes) -> dict | None:
        with self.lock:
            entries = list(self._read())
            for i, old in enumerate(entries):
                if old["id"] == eid:
                    e = {"id": eid, **clean_mine(body, modes, {k: v for k, v in old.items() if k != "id"})}
                    entries[i] = e
                    self._write(entries)
                    break
            else:
                return None
        self._changed()
        return e

    def delete(self, eid: str) -> bool:
        with self.lock:
            entries = self._read()
            keep = [e for e in entries if e["id"] != eid]
            if len(keep) == len(entries):
                return False
            self._write(keep)
        self._changed()
        return True


# ---------------------------------------------------------------- the dial label
# The bundled entries sorted by frequency, per set of files (LocalFrequencies._dial_rows).
_DIAL_INDEX: dict[tuple, tuple] = {}
_DIAL_LOCK = threading.Lock()


def _label(src: str, e: dict, place: tuple | None, eid: str, repeaters=None) -> dict:
    """The dial label for one matched entry (docs/SERVER-API.md "The dial
    label").

    Only what the entry really holds is said. The operator's entries have
    no callsign, place, colour code, network or CTCSS field (MINE_FIELDS):
    a repeater's name is taken as its callsign, its `sub` as the place,
    and the rest stay null rather than being read out of free-text notes,
    where "CC1" or "103.5" might mean anything."""
    mine = src == "mine"
    kind = ("repeater" if e.get("category") == "repeater" else "mine") if mine else e["category"]
    sub = e.get("sub", "") or ""
    mode = e.get("mode", "") or ""
    rx_offset = None
    if kind == "repeater":
        # Its input from the plan in force's repeater pairs, the same
        # table the dial's own "auto" shift reads (bands.auto_shift): a
        # second idea of where repeaters listen would disagree with it.
        sh = bands.auto_shift(e["freqHz"], repeaters)
        rx_offset = int(round(sh)) if sh else None
    out = {"kind": kind, "name": e["name"], "callsign": e["name"] if kind == "repeater" else None,
           "place": (sub or None) if mine else None, "sub": sub, "mode": mode,
           "cc": None, "ctcss": None, "network": None, "distanceKm": None, "bearingDeg": None,
           "freqHz": int(e["freqHz"]), "rxOffsetHz": rx_offset, "source": src,
           "id": eid}
    if place is not None:
        out["distanceKm"] = round(place[0], 1)
        out["bearingDeg"] = round(place[1])
    # "GB7IR · Irvine · DMR": name, place (or what the entry says under its
    # name), mode, each only when there is one. A colour code and network
    # would follow the mode once an entry can hold them.
    out["text"] = " · ".join(p for p in (out["name"], sub, mode.upper()) if p)
    return out


# ---------------------------------------------------------------- the listing
class LocalFrequencies:
    """The sources read once (and again when a file changes), the
    operator's list, and the listing. `data_dir` is Radio's data folder
    (the store form's /data); `bundled` the release's folder."""

    # What the store form's server reads from here, so ohscore never
    # imports this app's package (NB's image has none).
    CATEGORIES = CATEGORIES
    RADIUS_MIN_KM, RADIUS_MAX_KM = RADIUS_MIN_KM, RADIUS_MAX_KM
    Invalid = Invalid

    @staticmethod
    def http_fetch(url, headers=None, data=None):
        return http_fetch(url, headers, data)

    def __init__(self, data_dir: Path, bundled: Path = BUNDLED, clock=time.time):
        self.data_dir = Path(data_dir)
        self.bundled = Path(bundled)
        self.clock = clock
        self.mine = MineStore(self.data_dir / MINE_FILE)
        self._cache: dict[str, tuple] = {}       # source -> (stamp, entries, attribution, data)
        self._lock = threading.Lock()
        self.refreshing = threading.Lock()

    def refreshed_dir(self) -> Path:
        return self.data_dir / REFRESHED

    def _paths(self, source: str) -> list[Path]:
        """The files a source is read from, bundled first: a merged source
        reads both, a replaced one only the refreshed copy when it reads."""
        name = SOURCES[source]["file"]
        fresh = self.refreshed_dir() / name
        bundled = self.bundled / name
        if SOURCES[source]["merge"]:
            return [p for p in (bundled, fresh) if p.exists()]
        if fresh.exists():
            try:
                read_file(fresh)
                return [fresh]
            except (OSError, ValueError) as e:
                log.warning("refreshed %s unreadable, using the bundled copy: %s", source, e)
        return [bundled] if bundled.exists() else []

    def source(self, source: str) -> tuple[list[dict], dict, dict]:
        """(entries, attribution, the newest file's data) for a source."""
        paths = self._paths(source)
        stamp = tuple((str(p), p.stat().st_mtime_ns) for p in paths)
        with self._lock:
            hit = self._cache.get(source)
            if hit is not None and hit[0] == stamp:
                return hit[1], hit[2], hit[3]
        entries: dict[tuple, dict] = {}
        data: dict = {}
        for p in paths:
            try:
                data = read_file(p)
            except (OSError, ValueError) as e:
                log.warning("%s: %s", p, e)
                continue
            for e in expand(data):
                # A refreshed copy of a merged source wins over the bundled
                # one for the same place and frequency.
                entries[(e["ref"] or e["name"], e["freqHz"], e.get("sub", ""))] = e
        out = list(entries.values())
        attr = attribution_of(data) if data else {}
        with self._lock:
            self._cache[source] = (stamp, out, attr, data)
        return out, attr, data

    def listing(self, locator: str, radius_km: float | None = None, category: str | None = None,
                modes=None) -> dict:
        radius = float(radius_km if radius_km is not None else DEFAULT_RADIUS_KM)
        here = locator_position(locator or "")
        now = self.clock()
        rows: list[tuple] = []
        attributions = []
        ncdxf = None
        for order, src in enumerate(SOURCES):
            entries, attr, data = self.source(src)
            if src == "ncdxf" and data.get("beacons"):
                ncdxf = ncdxf_view(data, now)
            used = False
            for i, e in enumerate(entries):
                if category and e["category"] != category:
                    continue
                item = {"id": f"{src}:{e['ref'] or i}:{e['freqHz']}", "category": e["category"], "name": e["name"],
                        "sub": e.get("sub", ""), "freqHz": e["freqHz"], "mode": e["mode"], "source": src}
                if e.get("step"):
                    item["step"] = e["step"]
                if src == "ncdxf" and ncdxf is not None:
                    on = ncdxf["now"].get(str(e["freqHz"]))
                    if on:
                        item["sub"] = _("now {call}, {location}").format(**on)
                place = None
                if e.get("area") or e.get("lat") is not None:
                    if here is None:
                        continue
                    place = place_of(e, here)
                    if place[0] > radius:
                        continue
                    item["distanceKm"] = round(place[0], 1)
                    item["bearingDeg"] = round(place[1])
                used = True
                rows.append((CATEGORIES.index(e["category"]), place is None,
                             place[0] if place else order * 100000 + i, item))
            if used and attr.get("text"):
                attributions.append(attr)
        if not category or category == "mine":
            for i, m in enumerate(self.mine.entries()):
                item = {"id": f"mine:{m['id']}", "category": "mine", "name": m["name"], "sub": m.get("sub", ""),
                        "freqHz": m["freqHz"], "mode": m["mode"], "source": "mine",
                        "userCategory": m.get("category", ""), "notes": m.get("notes", ""),
                        "locator": m.get("locator", "")}
                place = None
                pos = locator_position(m.get("locator", "")) if m.get("locator") else None
                if pos is not None and here is not None:
                    place = distance_bearing(here[0], here[1], pos[0], pos[1])
                    item["distanceKm"] = round(place[0], 1)
                    item["bearingDeg"] = round(place[1])
                # The operator's own are listed whatever the radius: they
                # chose them, perhaps for where they are going.
                rows.append((CATEGORIES.index("mine"), place is None, place[0] if place else i, item))
        rows.sort(key=lambda r: r[:3])
        out = {"locator": norm_locator(locator) if here is not None else (locator or "").strip(),
               "radiusKm": radius, "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
               "attributions": attributions, "entries": [r[3] for r in rows], "ncdxf": ncdxf}
        if here is None:
            out["why"] = _("Set the station's locator to list what is near it; only the channel tables and your own "
                           "frequencies are listed without it.")
        return out

    def sources_view(self) -> list[dict]:
        """What each source holds now (Settings shows it; refresh answers
        it): its date, coverage and entries."""
        out = []
        for src in SOURCES:
            entries, attr, data = self.source(src)
            out.append({"source": src, "entries": len(entries), "fetched": data.get("fetched", ""),
                        "coverage": data.get("coverage", ""), "attribution": attr,
                        "refreshable": SOURCES[src]["refresh"]})
        return out

    # ------------------------------------------------------------ the dial label
    def _dial_rows(self) -> tuple[list[int], list[tuple]]:
        """Every bundled or refreshed entry sorted by frequency, as
        (frequencies, (source, index in its source, entry)) for bisect.

        Kept per process, by the files' stamps, not per instance: the
        label is asked for on every change of the dial, the airfields are
        some 27,000 entries, and every Radio a process makes (the tests
        make hundreds) reads the same release's files."""
        paths = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                      for src in SOURCES for p in self._paths(src))
        with _DIAL_LOCK:
            hit = _DIAL_INDEX.get(paths)
        if hit is not None:
            return hit
        rows = sorted(((e["freqHz"], src, i, e) for src in SOURCES for i, e in enumerate(self.source(src)[0])),
                      key=lambda r: r[0])
        built = ([r[0] for r in rows], [r[1:] for r in rows])
        with _DIAL_LOCK:
            if len(_DIAL_INDEX) >= 4:            # a refresh, or a test's toy folders: keep only the newest few
                _DIAL_INDEX.clear()
            _DIAL_INDEX[paths] = built
        return built

    def dial_label(self, vfo_hz: float, mode: str, bandwidth_hz: float, locator: str,
                   radius_km: float | None = None, repeaters=None) -> dict | None:
        """What the dial is on, if it is on something Radio knows: the
        operator's own entries and the bundled lists (docs/SERVER-API.md
        "The dial label"); None when nothing is within reach.

        An entry is matched when the dial is within half the receive
        bandwidth of it, or within its own channel step where that is
        tighter (an 8.33 kHz airband channel next to the one the operator
        means). Of several, the operator's own come first - a repeater
        among them before anything else they entered - then the bundled
        lists; inside each, the nearest in frequency, then the nearest on
        the ground, then those with no position. A bundled entry with a
        position counts only within `radius_km` of the station, and not at
        all without a locator, exactly as the listing does; the operator's
        own count wherever they are. `mode` is the dial's: it decides
        nothing here beyond the bandwidth it was given with, so the label
        names a repeater however the operator is listening to it.
        `repeaters` are the plan in force's schemes (bands.RepeaterScheme)
        for a repeater's input; the UK's when not given.

        Reads nothing but stats once the files are in memory: the operator's
        list is kept by its stamp (MineStore) and the bundled ones here."""
        vfo = float(vfo_hz)
        half = max(0.0, float(bandwidth_hz or 0.0)) / 2.0
        here = locator_position(locator or "")
        radius = float(radius_km if radius_km is not None else DEFAULT_RADIUS_KM)
        far = float("inf")
        best: tuple | None = None
        for i, m in enumerate(self.mine.entries()):
            off = abs(m["freqHz"] - vfo)
            if off > half:
                continue
            place = None
            pos = locator_position(m.get("locator", "")) if m.get("locator") else None
            if pos is not None and here is not None:
                place = distance_bearing(here[0], here[1], pos[0], pos[1])
            rank = 0 if m.get("category") == "repeater" else 1
            cand = (rank, off, place[0] if place else far, i, ("mine", m, place, f"mine:{m['id']}"))
            best = cand if best is None or cand[:4] < best[:4] else best
        if best is None or best[0] > 1:
            freqs, rows = self._dial_rows()
            lo, hi = bisect.bisect_left(freqs, vfo - half), bisect.bisect_right(freqs, vfo + half)
            for k in range(lo, hi):
                src, i, e = rows[k]
                off = abs(e["freqHz"] - vfo)
                if off > (min(half, e["step"]) if e.get("step") else half):
                    continue
                place = None
                if e.get("area") or e.get("lat") is not None:
                    if here is None:
                        continue
                    place = place_of(e, here)
                    if place[0] > radius:
                        continue
                cand = (2, off, place[0] if place else far, k, (src, e, place, f"{src}:{e['ref'] or i}:{e['freqHz']}"))
                best = cand if best is None or cand[:4] < best[:4] else best
        if best is None:
            return None
        src, e, place, eid = best[4]
        return _label(src, e, place, eid, repeaters)

    # ------------------------------------------------------------ refresh
    def refresh(self, fetch, locator: str, radius_km: float, openaip_key: str = "") -> dict:
        """Download newer copies of the refreshable sources into the data
        folder (an administrator's action). `fetch(url, headers=None,
        data=None) -> bytes` is the network, a test's fixture reader in
        the tests. Each source succeeds or fails alone and the bundled copy
        stays in use for one that fails."""
        if not self.refreshing.acquire(blocking=False):
            raise RuntimeError(_("A refresh is already running"))
        try:
            here = locator_position(locator or "")
            dest = self.refreshed_dir()
            dest.mkdir(parents=True, exist_ok=True)
            fetched = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
            results = []
            for src in ("ourairports", "osm-marine", "openaip"):
                res = {"source": src, "ok": False, "entries": 0, "why": ""}
                try:
                    if src == "ourairports":
                        data = build_ourairports(fetch(OURAIRPORTS_URLS[0]).decode("utf-8"),
                                                 fetch(OURAIRPORTS_URLS[1]).decode("utf-8"), fetched)
                    elif here is None:
                        res["why"] = _("No station locator: nothing to fetch around")
                        results.append(res)
                        continue
                    elif src == "osm-marine":
                        q = overpass_query_around(here[0], here[1], radius_km)
                        raw = fetch(OVERPASS_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                                    ("data=" + _quote(q)).encode())
                        data = build_osm_marine(json.loads(raw), fetched,
                                                f"{radius_km:g} km around {locator.upper()}")
                    else:
                        if not openaip_key:
                            res["why"] = _("No openAIP API key is set")
                            results.append(res)
                            continue
                        items = fetch_openaip(fetch, openaip_key, here, radius_km)
                        data = build_openaip(items, fetched, f"{radius_km:g} km around {locator.upper()}")
                    write_file(dest / SOURCES[src]["file"], data)
                    res.update(ok=True, entries=len(expand(data)), fetched=fetched)
                except Exception as e:  # noqa: BLE001  one source's failure must not stop the others
                    log.warning("refresh %s: %s", src, e)
                    res["why"] = str(e) or e.__class__.__name__
                results.append(res)
            return {"refreshedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())),
                    "results": results, "sources": self.sources_view()}
        finally:
            self.refreshing.release()


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def write_file(path: Path, data: dict) -> None:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if path.suffix == ".gz":
        raw = gzip.compress(raw, mtime=0)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)


def http_fetch(url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 60.0) -> bytes:
    """The real network for Refresh and the build script."""
    import urllib.request
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310  fixed https URLs
        return r.read()


# ---------------------------------------------------------------- builders (Refresh and tools/)
def eight33(mhz: float) -> tuple[int, int]:
    """(Hz, step) for an airband frequency as published. A 8.33 kHz
    channel is published by its name, not its frequency: in each 25 kHz
    block the names .xx5, .x10 and .x15 are the channels at 0, 8.33 and
    16.67 kHz into the block (ICAO Annex 10; 118.005 is 118.000 MHz,
    118.010 is 118.00833). A name ending 0 or 25/50/75 is a 25 kHz channel."""
    khz = round(mhz * 1000.0, 3)
    if abs(khz - round(khz)) > 1e-6:
        return int(round(mhz * 1e6)), 8333            # published as the frequency itself
    k = int(round(khz))
    block, into = divmod(k, 25)
    if 118000 <= k < 137000 and into in (5, 10, 15):
        return block * 25000 + {5: 0, 10: 8333, 15: 16667}[into], 8333
    return k * 1000, 25000


ENROUTE_TYPES = ("CNTR", "ACC", "CTR", "FIR")


def build_ourairports(airports_csv: str, freqs_csv: str, fetched: str) -> dict:
    """The airfields that publish a frequency on VHF (118-137 MHz) or UHF
    (225-400 MHz) airband, closed ones dropped. Area control a field
    lists (CNTR, ACC) goes under enroute."""
    airports = {}
    for r in csv.DictReader(io.StringIO(airports_csv)):
        if r.get("type") == "closed":
            continue
        try:
            airports[r["id"]] = (r["ident"], r["name"], round(float(r["latitude_deg"]), 4),
                                 round(float(r["longitude_deg"]), 4))
        except (KeyError, ValueError):
            continue
    by: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(freqs_csv)):
        a = airports.get(r.get("airport_ref", ""))
        if a is None:
            continue
        try:
            mhz = float(r["frequency_mhz"])
        except (KeyError, ValueError):
            continue
        if not (118.0 <= mhz <= 137.0 or 225.0 <= mhz <= 400.0):
            continue
        hz, step = eight33(mhz) if mhz < 200 else (int(round(mhz * 1e6)), 25000)
        kind = (r.get("type") or "").strip().upper()
        desc = (r.get("description") or "").strip()
        sub = kind if not desc or desc.upper() == kind else f"{kind} {desc}"
        cat = "enroute" if kind in ENROUTE_TYPES else "airband"
        key = (a[0], cat)
        e = by.setdefault(key, {"ref": a[0], "name": a[1], "lat": a[2], "lon": a[3], "freqs": []})
        if cat != "airband":
            e["category"] = cat
        if not any(f[0] == hz and f[1] == sub for f in e["freqs"]):
            e["freqs"].append([hz, sub[:60]] + ([] if step == 25000 else [step]))
    return {"schema": 1, "source": "ourairports", "attribution": ATTRIBUTION["ourairports"],
            "fetched": fetched, "from": list(OURAIRPORTS_URLS), "coverage": "worldwide",
            "defaults": {"category": "airband", "mode": "am", "step": 25000},
            "entries": sorted(by.values(), key=lambda e: (e["ref"], e.get("category", "")))}


# OpenStreetMap / OpenSeaMap tags that carry a marine VHF working channel.
OSM_VHF_KEYS = ("vhf", "contact:vhf", "vhf_channel", "communication:vhf", "communication:VHF",
                "waterway:vhf_channel", "seamark:radio_station:channel", "seamark:radio_station:frequency",
                "seamark:calling-in_point:channel", "seamark:signal_station_traffic:channel",
                "seamark:pilot_boarding:channel")


def overpass_selectors(scope: str) -> str:
    return "".join(f'  nwr{scope}["{k}"];\n' for k in OSM_VHF_KEYS)


def overpass_query_area(isos: tuple[str, ...]) -> str:
    areas = " ".join(f'area["ISO3166-1"="{i}"][admin_level=2];' for i in isos)
    return f"[out:json][timeout:300];\n({areas})->.a;\n(\n{overpass_selectors('(area.a)')});\nout center tags;\n"


def overpass_query_around(lat: float, lon: float, radius_km: float) -> str:
    m = int(max(1.0, min(float(radius_km), RADIUS_MAX_KM)) * 1000)
    return (f"[out:json][timeout:120];\n(\n{overpass_selectors(f'(around:{m},{lat:.5f},{lon:.5f})')});\n"
            f"out center tags;\n")


def marine_channel_hz(ch: str) -> tuple[int, str] | None:
    """(Hz a listener hears, note) for a marine VHF channel as tagged: the
    coast station's side of a duplex channel, the one frequency of a
    simplex one (ITU RR Appendix 18). None for anything else."""
    ch = ch.strip().upper()
    if ch in UK_PRIVATE:
        return UK_PRIVATE[ch], f"Ch {ch}"
    m = re.fullmatch(r"0*(\d{1,2})([AB]?)", ch)
    if not m:
        return None
    n, ab = int(m.group(1)), m.group(2)
    if 1 <= n <= 28:
        ship = 156_000_000 + 50_000 * n
    elif 60 <= n <= 88:
        ship = 156_025_000 + 50_000 * (n - 60)
    else:
        return None
    duplex = n in DUPLEX and ab != "A"
    if ab == "B":
        return ship + 4_600_000, f"Ch {n}B"
    return (ship + 4_600_000 if duplex else ship), f"Ch {n:02d}{ab}"


# The UK's channels for marinas and yacht clubs beside Appendix 18 (Ofcom):
# M is also written 37 or 37A.
UK_PRIVATE = {"M": 157_850_000, "M1": 157_850_000, "37A": 157_850_000, "M2": 161_425_000}

# Duplex channels of Appendix 18 (the coast station sends 4.6 MHz above the
# ship); the rest are simplex on the ship frequency.
DUPLEX = frozenset([1, 2, 3, 4, 5, 7, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 60, 61, 62, 63, 64, 65, 66, 78,
                    79, 80, 81, 82, 83, 84, 85, 86])


def parse_vhf(value: str) -> list[tuple[int, str]]:
    """Every marine channel or frequency in a tag's value ("12;16",
    "VHF 72/16", "156.800"): (Hz, note). Airband and junk dropped."""
    out = []
    for part in re.split(r"[;,/&]|\band\b|\s-\s|-(?=\d)", value):
        part = part.strip()
        part = re.sub(r"^(VHF|CH|CHANNEL)\s*:?\s*", "", part, flags=re.I).strip()
        part = re.sub(r"\s*\(.*\)$", "", part)
        if not part:
            continue
        if re.fullmatch(r"\d{3}\.\d{1,4}", part):
            hz = int(round(float(part) * 1e6))
            if 156_000_000 <= hz <= 163_000_000:
                out.append((hz, ""))
            continue
        got = marine_channel_hz(part)
        if got:
            out.append(got)
    seen, uniq = set(), []
    for hz, note in out:
        if hz not in seen:
            seen.add(hz)
            uniq.append((hz, note))
    return uniq


def osm_label(tags: dict) -> str:
    for k in ("name", "seamark:name", "seamark:radio_station:name", "operator"):
        if tags.get(k):
            return tags[k]
    kind = tags.get("seamark:type") or tags.get("leisure") or tags.get("amenity") or tags.get("waterway") or ""
    return {"harbour": "Harbour", "marina": "Marina", "calling-in_point": "Calling-in point",
            "signal_station_traffic": "Traffic signal station", "pilot_boarding": "Pilot boarding",
            "radio_station": "Radio station", "harbourmaster": "Harbour master", "lock_gate": "Lock",
            "dock": "Dock"}.get(kind, "")


def osm_kind(tags: dict) -> str:
    if tags.get("leisure") == "marina" or tags.get("seamark:harbour:category") == "marina":
        return "marina"
    if tags.get("seamark:type") == "calling-in_point":
        return "calling-in point"
    if tags.get("seamark:type") == "pilot_boarding":
        return "pilots"
    if tags.get("seamark:type") == "signal_station_traffic" or tags.get("waterway") in ("lock_gate", "dock"):
        return tags.get("seamark:signal_station_traffic:category") or tags.get("waterway") or "traffic"
    if tags.get("seamark:type") == "harbour" or tags.get("harbour") == "yes" or tags.get("amenity") == "harbourmaster":
        return "port operations"
    if any(k.startswith("seamark:radio_station") for k in tags):
        return "radio station"
    return "marine"


def build_osm_marine(overpass: dict, fetched: str, coverage: str) -> dict:
    """Marinas, harbours, locks and coast radio from an Overpass answer:
    one entry per place with its working channels. Unnamed places get
    their kind as the name; places with no channel a listener can tune are
    dropped. Only map features: no tag that names a person is read."""
    out = []
    for el in overpass.get("elements", []):
        tags = el.get("tags") or {}
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        freqs = []
        for k in OSM_VHF_KEYS:
            if tags.get(k):
                for hz, note in parse_vhf(tags[k]):
                    if hz not in [f[0] for f in freqs]:
                        freqs.append([hz, note])
        name = osm_label(tags)
        if not freqs or not name:
            continue
        kind = osm_kind(tags)
        out.append({"ref": f"{el['type'][0]}{el['id']}", "name": name[:60], "lat": round(float(lat), 5),
                    "lon": round(float(lon), 5),
                    "freqs": [[hz, f"{kind} {note}".strip()] for hz, note in freqs]})
    out.sort(key=lambda e: e["ref"])
    return {"schema": 1, "source": "osm-marine", "attribution": ATTRIBUTION["osm-marine"], "fetched": fetched,
            "from": [OVERPASS_URL], "coverage": coverage, "licence": "ODbL-1.0",
            "osmBase": (overpass.get("osm3s") or {}).get("timestamp_osm_base", ""),
            "defaults": {"category": "marine", "mode": "fm", "step": 25000}, "entries": out}


# openAIP airspace types (its API's enum) that a listener hears as area
# or approach control; the rest (danger areas, gliding sectors) have no
# useful frequency or are already an airfield's.
OPENAIP_TYPES = {4: "CTR", 5: "TMZ", 6: "RMZ", 7: "TMA", 10: "FIR", 11: "UIR", 13: "ATZ", 14: "MATZ", 23: "TIZ",
                 24: "TIA", 26: "CTA", 27: "ACC sector", 33: "FIS sector", 36: "MCTR"}
AREA_POINTS = 32


def fetch_openaip(fetch, key: str, here: tuple[float, float], radius_km: float) -> list[dict]:
    """Every airspace within the radius that openAIP's API has, paged.
    The key goes in its own header, never a URL (logs keep URLs)."""
    items, page = [], 1
    while page <= 50:
        q = (f"{OPENAIP_URL}?pos={here[0]:.5f},{here[1]:.5f}&dist={int(radius_km * 1000)}&limit=1000&page={page}"
             + "".join(f"&type={t}" for t in sorted(OPENAIP_TYPES)))
        ans = json.loads(fetch(q, {"x-openaip-api-key": key, "Accept": "application/json"}))
        items += ans.get("items", [])
        if page >= int(ans.get("totalPages") or 1):
            break
        page += 1
    return items


def simplify(ring: list, most: int = AREA_POINTS) -> list:
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) <= most:
        return ring
    k = math.ceil(len(ring) / most)
    return ring[::k]


def build_openaip(items: list[dict], fetched: str, coverage: str) -> dict:
    """openAIP airspaces with frequencies: the outline thinned to 32
    corners (enough to say whether the station is inside, and how far the
    edge is), each frequency named as openAIP names it."""
    out = []
    for a in items:
        freqs = []
        for f in a.get("frequencies") or []:
            try:
                mhz = float(f["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 118.0 <= mhz <= 137.0:
                continue
            hz, step = eight33(mhz)
            freqs.append([hz, str(f.get("name") or "")[:60]] + ([step] if step != 25000 else []))
        geo = a.get("geometry") or {}
        try:
            ring = [[round(float(p[1]), 4), round(float(p[0]), 4)] for p in geo["coordinates"][0]]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if not freqs or len(ring) < 3:
            continue
        kind = OPENAIP_TYPES.get(int(a.get("type", -1)), "")
        out.append({"ref": str(a.get("_id", "")), "name": str(a.get("name", ""))[:60],
                    "sub": kind, "area": simplify(ring), "freqs": [[f[0], (f[1] or kind)] + f[2:] for f in freqs]})
    out.sort(key=lambda e: e["ref"])
    return {"schema": 1, "source": "openaip", "attribution": ATTRIBUTION["openaip"], "fetched": fetched,
            "from": [OPENAIP_URL], "coverage": coverage, "licence": "CC-BY-NC-4.0",
            "defaults": {"category": "enroute", "mode": "am", "step": 25000}, "entries": out}
