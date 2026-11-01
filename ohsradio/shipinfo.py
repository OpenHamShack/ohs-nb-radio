"""More about each ship on AIS's map: a few facts and a photo (Brian,
01/11/2026; docs/SERVER-API.md "AIS", "Ship details and photos"). The
ships' twin of aircraftinfo.py, on its Lookup (cache, queue, worker,
backoff), with what differs said here.

A ship's AIS says its name, callsign, type and size, and (class A) its
IMO number. Wikidata knows more about the notable ones - ferries, cargo
ships, warships, tall ships - by that IMO number (P458) or its MMSI
(P587): its builder (P176), when it was built (P571, else entering
service, P729), its operator (P137), gross tonnage (P1093), home port
(P504), its own name (the item's label, which a screen shows when it is
not the AIS name), and a picture on Wikimedia Commons (P18). Commons'
API gives that file's author and licence (`extmetadata` Artist,
LicenseShortName) and a thumbnail at least 640 pixels wide (Commons
rounds up to a standard size: 960 for a photo, 86 kB as JPEG).

**One request a ship, on the query service.** Each ship is one SPARQL
query to query.wikidata.org: the IMO (or MMSI) in, the item and every
fact's label out. The alternative, the search API and then the entity,
is two requests, and the entity's builder or port comes back as another
item's id, a third request each for a name. A ship with a picture costs
two more (Commons' file details, then the thumbnail). Every request of
the three waits RATE_S (2 s) after the one before, ships or not, one at
a time, so Radio never asks Wikimedia more than once in two seconds -
politer than its policy asks of a bot (no parallel requests) - and the
User-Agent names the program, its version and the project's address,
as Wikimedia's policy requires (wikimedia_agent()).

**Every ship heard, in the background.** The screen and the API ask
`info(vessel)` for every ship they show; a miss is queued, never waited
for. The key is "imo:<7 digits>" when the ship has sent a valid IMO
number (its check digit right; class A ships send 0 or nonsense often),
else "mmsi:<9 digits>" for a ship's own MMSI (first digit 2-7). Base
stations, aids to navigation, SARTs and SAR aircraft are never asked
about. Lifetimes: a hit OK_TTL_S (30 days), a miss UNKNOWN_TTL_S (7
days: Wikidata grows, but a fishing boat will not be in it next week),
a failure ERROR_RETRY_S (aircraftinfo's 10 minutes), and the same
backoff across the source after a failure, so a box with no route out
makes one request in 30 minutes at most once it has noticed.

**The picture is fetched, kept and served by Radio**, unlike
Planespotters' (aircraftinfo.py): Commons' licences (CC BY, CC BY-SA,
public domain) allow redistribution with attribution, which the credit
gives ("Jane Smith · CC BY-SA 4.0", the author's HTML stripped, with the
file's Commons page as the link, a QR code on a TV). So the screen's
`src` is a path on the box (GET api/ais/vessels/<mmsi>/photo), which
every client may load (SCREENS.md §9: box images by relative path), not
an absolute address on a host no client's allow-list has. The thumbnail
is stored beside the cache (photos/<key>.jpg|.png), at most
PHOTO_MAX_BYTES (the client's own cap for a picture) and MAX_PHOTOS of
them, oldest first out; a photo file goes when its entry does.

**What goes out:** to query.wikidata.org, the IMO or MMSI in a query;
to commons.wikimedia.org, the picture's file name; to its image host
(thumb. or upload.wikimedia.org), the thumbnail's address as Commons gave
it. No
cookies, no Referer, nothing about the station. Setting
`aisShipLookup` (default on) off: no request, and `null` even for what
is cached, as aircraft's.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .aircraftinfo import CONTACT_URL, Lookup
from .flightroutes import FetchFailed, user_agent

log = logging.getLogger("ohsradio.shipinfo")

SPARQL_URL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Where Commons' thumbnails live: upload.wikimedia.org until 2026, and
# thumb.wikimedia.org in its imageinfo answers since (seen 01/11/2026).
# A thumbnail anywhere else is not Commons' and is not fetched.
UPLOAD_PREFIXES = ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
COMMONS_PAGE_PREFIX = "https://commons.wikimedia.org/"

RATE_S = 2.0                       # between any two requests to Wikimedia (module docstring)
HTTP_TIMEOUT_S = 15.0              # the query service is slower than adsbdb
MAX_BYTES = 256 << 10              # a ship's query or file answer is a few kB
OK_TTL_S = 30 * 86_400.0
UNKNOWN_TTL_S = 7 * 86_400.0
MAX_ENTRIES = 5000                 # at ~400 bytes each, 2 MB
THUMB_WIDTH = 640
PHOTO_MAX_BYTES = 600_000          # SCREENS.md §9's cap on a picture a client loads
MAX_PHOTOS = 300                   # at ~80 kB each, ~25 MB
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
CREDIT_MAX = 80                    # the author's name, as shown

_KEY = re.compile(r"^(imo:\d{7}|mmsi:[2-7]\d{8})$")

QUERY = """SELECT ?item ?itemLabel ?builderLabel ?inception ?service ?operatorLabel ?gt ?homeLabel ?image WHERE {
  ?item wdt:%(prop)s "%(value)s" .
  OPTIONAL { ?item wdt:P176 ?builder . }
  OPTIONAL { ?item wdt:P571 ?inception . }
  OPTIONAL { ?item wdt:P729 ?service . }
  OPTIONAL { ?item wdt:P137 ?operator . }
  OPTIONAL { ?item wdt:P1093 ?gt . }
  OPTIONAL { ?item wdt:P504 ?home . }
  OPTIONAL { ?item wdt:P18 ?image . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". }
} LIMIT 50"""


def wikimedia_agent() -> str:
    """Wikimedia's User-Agent policy: the program, its version and a way
    to reach whoever runs it - the project's address, never the
    operator's - then the library."""
    return f"{user_agent()} (+{CONTACT_URL}) Python-urllib"


def imo_ok(imo) -> bool:
    """A real IMO ship number: seven digits whose last is the check digit
    (the first six weighted 7 down to 2, summed, mod 10)."""
    try:
        n = int(imo)
    except (TypeError, ValueError):
        return False
    if not 1_000_000 <= n <= 9_999_999:
        return False
    d = f"{n:07d}"
    return sum(int(c) * w for c, w in zip(d[:6], range(7, 1, -1))) % 10 == int(d[6])


def key_for(v: dict) -> str | None:
    """The cache key for a vessel from the AIS table (module docstring),
    or None for a station never asked about."""
    if v.get("class") not in ("A", "B"):
        return None
    if imo_ok(v.get("imo")):
        return f"imo:{int(v['imo']):07d}"
    try:
        mmsi = int(v.get("mmsi"))
    except (TypeError, ValueError):
        return None
    return f"mmsi:{mmsi}" if 200_000_000 <= mmsi < 800_000_000 else None


def clean_key(key) -> str | None:
    k = str(key or "")
    return k if _KEY.match(k) else None


def _photo_name(key: str, ext: str) -> str:
    return key.replace(":", "-") + ext


def plain(html_text) -> str | None:
    """Commons' Artist (HTML: often a link to the user's page, sometimes a
    table) as one plain line, cut to CREDIT_MAX."""
    if not isinstance(html_text, str):
        return None
    t = re.sub(r"<[^>]+>", " ", html_text)
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    if len(t) > CREDIT_MAX:
        t = t[:CREDIT_MAX - 1].rstrip() + "…"
    return t or None


def _year(v) -> str | None:
    m = re.match(r"^\+?(\d{4})-", v or "")
    return m[1] if m else None


def is_name(label: str) -> bool:
    """False for a Wikidata label that is only "IMO 9370288": not a name."""
    return not re.fullmatch(r"(?i)IMO\s*\d{7}", label.strip())


def parse_query(data) -> dict | None:
    """The query service's answer as the facts (no photo yet) and the
    picture's Commons file name under "_file"; None for no such ship.
    Each OPTIONAL multiplies rows, so each fact is its first value among
    the first item's rows."""
    rows = (data.get("results") or {}).get("bindings") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    item = (rows[0].get("item") or {}).get("value")
    if not isinstance(item, str):
        return None
    rows = [r for r in rows if (r.get("item") or {}).get("value") == item]

    def first(name):
        for r in rows:
            v = (r.get(name) or {}).get("value")
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    qid = item.rsplit("/", 1)[-1]
    label = first("itemLabel")
    gt = first("gt")
    try:
        gt = int(round(float(gt))) if gt is not None else None
    except ValueError:
        gt = None
    image = first("image")
    file = urllib.parse.unquote(image.rsplit("/", 1)[-1]) if image and "/Special:FilePath/" in image else None
    # Many Wikidata ships are labelled only "IMO 9370288" (or by their
    # Q-number): not a name, so the card would show it as one.
    if label and (label == qid or not is_name(label)):
        label = None
    return {"qid": qid, "label": label, "builder": first("builderLabel"),
            "built": _year(first("inception")) or _year(first("service")), "operator": first("operatorLabel"),
            "grossTonnage": gt, "homePort": first("homeLabel"), "_file": file}


def parse_imageinfo(data) -> dict | None:
    """Commons' imageinfo (formatversion 2) as {"thumb", "width", "height",
    "page", "artist", "licence"}; None for a missing file or one with no
    thumbnail."""
    pages = (data.get("query") or {}).get("pages") if isinstance(data, dict) else None
    page = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else None
    info = (page.get("imageinfo") or [None])[0] if page and not page.get("missing") else None
    if not isinstance(info, dict):
        return None
    meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}

    def m(k):
        x = meta.get(k)
        return x.get("value") if isinstance(x, dict) else None

    thumb, link = info.get("thumburl"), info.get("descriptionurl")
    if not (isinstance(thumb, str) and isinstance(link, str)):
        return None
    lic = m("LicenseShortName")
    return {"thumb": thumb, "width": info.get("thumbwidth") if isinstance(info.get("thumbwidth"), int) else None,
            "height": info.get("thumbheight") if isinstance(info.get("thumbheight"), int) else None,
            "page": link, "artist": plain(m("Artist")), "licence": plain(lic) if lic else None}


def credit(artist: str | None, licence: str | None) -> str:
    """What the screen prints under the picture: author and licence, as
    Commons' licences ask; "Wikimedia Commons" where it says neither."""
    # Commons often names a photographer by their user page, "User:Dave
    # souza": the person's name is what the credit is for. Done here, not
    # in plain(), so entries already cached read the same.
    if artist:
        artist = re.sub(r"(?i)^user:\s*", "", artist).strip() or None
    return " · ".join(x for x in (artist, licence) if x) or "Wikimedia Commons"


class ShipInfo:
    """Facts and photos by IMO or MMSI (module docstring).

        si = ShipInfo(folder, enabled=...)
        si.info(vessel)     -> {facts..., "photo": {...} | None} | {} | None
        si.photo(vessel)    -> (bytes, content type) | None
        si.start() / si.stop()
    """

    def __init__(self, folder, enabled=lambda: True, clock=time.time, base_url: str | None = None,
                 timeout: float = HTTP_TIMEOUT_S):
        self.folder = Path(folder)
        self.photos_dir = self.folder / "photos"
        # Tests point all three hosts at one fake (tests/scratch_home.py:
        # a closed local port; each test its own server).
        base = (base_url or os.environ.get("OHS_WIKIMEDIA_BASE", "")).rstrip("/")
        self.sparql_url = f"{base}/sparql" if base else SPARQL_URL
        self.commons_api = f"{base}/w/api.php" if base else COMMONS_API
        self.upload_prefixes = (f"{base}/",) if base else UPLOAD_PREFIXES
        self.page_prefix = f"{base}/" if base else COMMONS_PAGE_PREFIX
        self.timeout = timeout
        self.rate_s = RATE_S
        self.max_photos = MAX_PHOTOS
        self._last_request = 0.0
        self._photo_lock = threading.Lock()
        self.lookup = Lookup("wikidata", self.folder / "ships.json", enabled, self._fetch,
                             {"ok": OK_TTL_S, "unknown": UNKNOWN_TTL_S}, clock, clean=clean_key,
                             on_drop=self._dropped, thread_name="shipinfo")
        # Requests are spaced by _paced(), each one; the Lookup's own
        # per-key rate would only add to it. Its backoff still applies.
        self.lookup.rate_s = 0.0
        self.lookup.max_entries = MAX_ENTRIES
        self._sweep()

    def start(self) -> None:
        self.lookup.start()

    def stop(self) -> None:
        self.lookup.stop()

    # -- what callers ask -------------------------------------------------
    def info(self, v: dict) -> dict | None:
        """A vessel's details: None until Wikidata has answered (or the
        setting is off, or it failed, or the station is not a ship); `{}`
        when Wikidata has no such ship. `photo` is the credit and link,
        or None; its bytes are photo()'s."""
        key = key_for(v)
        got = self.lookup.get(key) if key else None
        if got is None:
            return None
        status, value = got
        if status != "ok":
            return {}
        out = {k: x for k, x in value.items() if k != "photo"}
        ph = value.get("photo")
        if ph and (self.photos_dir / ph["name"]).exists():
            out["photo"] = {"credit": credit(ph.get("artist"), ph.get("licence")), "link": ph["page"],
                            "width": ph.get("width"), "height": ph.get("height")}
        else:
            out["photo"] = None
        return out | {"source": "wikidata"}

    def photo(self, v: dict) -> tuple[bytes, str] | None:
        """The stored thumbnail for GET api/ais/vessels/<mmsi>/photo."""
        key = key_for(v)
        got = self.lookup.get(key) if key else None
        ph = got[1].get("photo") if got and got[0] == "ok" else None
        if not ph:
            return None
        try:
            return (self.photos_dir / ph["name"]).read_bytes(), ph["type"]
        except OSError:
            return None

    # -- the worker ---------------------------------------------------------
    def _paced(self) -> None:
        """Wait until RATE_S after the last request of any kind; FetchFailed
        if Radio is stopping meanwhile."""
        wait = self._last_request + self.rate_s - time.monotonic()
        if wait > 0 and self.lookup.stop_ev.wait(wait):
            raise FetchFailed("stopping")
        self._last_request = time.monotonic()

    def _get(self, url: str, limit: int) -> tuple[bytes, str]:
        self._paced()
        req = urllib.request.Request(url, headers={"User-Agent": wikimedia_agent(),
                                                   "Accept": "application/sparql-results+json, application/json, "
                                                             "image/jpeg, image/png"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(limit + 1)
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        except urllib.error.HTTPError as e:
            raise FetchFailed(f"http {e.code}") from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise FetchFailed(str(e)) from e
        if len(raw) > limit:
            raise FetchFailed("answer too large")
        return raw, ctype

    def _json(self, url: str):
        raw, _t = self._get(url, MAX_BYTES)
        try:
            return json.loads(raw)
        except ValueError as e:
            raise FetchFailed(f"bad json: {e}") from e

    def _fetch(self, key: str) -> dict | None:
        prop, value = ("P458", key[4:]) if key.startswith("imo:") else ("P587", key[5:])
        q = urllib.parse.urlencode({"query": QUERY % {"prop": prop, "value": value}, "format": "json"})
        facts = parse_query(self._json(f"{self.sparql_url}?{q}"))
        if facts is None:
            return None
        file = facts.pop("_file")
        facts["photo"] = self._fetch_photo(key, file) if file else None
        return facts

    def _fetch_photo(self, key: str, file: str) -> dict | None:
        """The picture's details and its thumbnail, stored; None for one
        Commons cannot give or that is not a small JPEG or PNG. A failed
        request fails the whole ship, which is asked again later."""
        q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": "2",
                                    "prop": "imageinfo", "iiprop": "url|extmetadata",
                                    "iiextmetadatafilter": "Artist|LicenseShortName",
                                    "iiurlwidth": str(THUMB_WIDTH), "titles": f"File:{file}"})
        info = parse_imageinfo(self._json(f"{self.commons_api}?{q}"))
        if info is None or not info["thumb"].startswith(self.upload_prefixes) \
                or not info["page"].startswith(self.page_prefix):
            return None
        try:
            raw, ctype = self._get(info["thumb"], PHOTO_MAX_BYTES)
        except FetchFailed as e:
            if str(e) == "answer too large":
                return None
            raise
        ext = PHOTO_TYPES.get(ctype)
        if ext is None:
            return None
        name = _photo_name(key, ext)
        try:
            self.photos_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.photos_dir / (name + ".part")
            tmp.write_bytes(raw)
            tmp.replace(self.photos_dir / name)
        except OSError as e:
            log.debug("could not keep a ship's photo: %s", e)
            return None
        self._trim_photos()
        return {"name": name, "type": ctype, "page": info["page"], "artist": info["artist"],
                "licence": info["licence"], "width": info["width"], "height": info["height"]}

    # -- the photo folder -----------------------------------------------------
    def _dropped(self, key: str, ent: dict) -> None:
        """Lookup's on_drop: an entry gone from the cache takes its photo."""
        ph = (ent.get("value") or {}).get("photo") if isinstance(ent.get("value"), dict) else None
        if ph and ph.get("name"):
            try:
                (self.photos_dir / ph["name"]).unlink()
            except OSError:
                pass

    def _trim_photos(self) -> None:
        """At most max_photos files, the oldest first out. The entry keeps
        its facts and shows no photo until it is looked up again."""
        with self._photo_lock:
            try:
                files = sorted((p for p in self.photos_dir.iterdir() if p.suffix in (".jpg", ".png")),
                               key=lambda p: p.stat().st_mtime)
            except OSError:
                return
            for p in files[:max(0, len(files) - self.max_photos)]:
                try:
                    p.unlink()
                except OSError:
                    pass

    def _sweep(self) -> None:
        """At start: photo files no cache entry names (left by a crash
        between writing a photo and its entry, or an entry read back
        stale) are deleted, so the folder never grows past the cache."""
        named = {(e.get("value") or {}).get("photo", {}).get("name")
                 for e in self.lookup.cache.values()
                 if isinstance(e.get("value"), dict) and isinstance(e["value"].get("photo"), dict)}
        try:
            for p in self.photos_dir.iterdir():
                if p.name not in named:
                    p.unlink()
        except OSError:
            pass

