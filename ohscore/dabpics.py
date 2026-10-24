"""DAB's pictures and programme guide, as Radio keeps them: the slides
(SlideShow), the station logos and the schedules a DAB session's decoder
hands over (shack_sdr README "DAB": `frame` results `slide`, `logo` and
`schedule`, the picture's bytes in `raw`). Nothing here fetches anything:
a picture came off air, or was handed in by Radio's RadioDNS fetcher
(ohsradio/radiodns.py, `take_fetched`).

    pics = engine.dab_pictures
    pics.take(item)            # a decoder result; the item without its bytes
    pics.slide("C221")         # (bytes, content type) or None
    pics.logo("C221", "square")
    pics.schedule("C221", date="2026-10-24")
    pics.decorate(meta)        # a session's meta with logoPath / slidePath

**Slides are the latest per service, in memory.** A slide is what is on
air now; one kept past a restart would be a stale picture of a song long
over. At most MAX_SLIDES services' slides are held (the least recently
changed go), so a session that hops round every station cannot grow it.

**Logos and schedules are kept on disk** under the data folder's `dab`
folder, so the station list shows logos the morning after (a logo takes
minutes of SPI to arrive), and they survive restarts. A logo is a file
per service and variant (`square`, `wide`) beside `logos.json`, written
whole or not at all; at most LOGO_FILES files and LOGO_BYTES bytes, the
oldest going first. Schedules are one `schedules.json`, at most
MAX_SCHEDULES services, each programme ending more than a day ago
dropped.

**Paths, not URLs.** What this hands out are paths relative to the app
(`api/dab/logos/C221`); the server makes them URLs under the request's
X-Forwarded-Prefix (server/app.py `with_urls`), because only it knows
where the app is being served from.

**Two sources, the air first.** A logo is `broadcast` (from the
ensemble's SPI) or `radiodns` (fetched from the broadcaster's own server);
each path and URL handed out says which (`logoSource`, `logoWideSource`).
Per variant the air wins: a fetched logo never replaces a broadcast one,
and a broadcast one always replaces a fetched one. Fetched ones are the
first to go when the store is full, and while `show_fetched()` is false
(the radioDnsLogos setting off) they are kept but not shown, so the store
answers exactly as it did before there were any.

A logo is keyed by SId alone. SIds are unique within a country, and a
receiver hears one country's ensembles, so the ECC is not part of the key.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ohscore.dabpics")

SID_RE = re.compile(r"^[0-9A-F]{4}([0-9A-F]{4})?$")
VARIANTS = ("square", "wide")
TYPES = {"image/png": "png", "image/jpeg": "jpg"}
MAX_SLIDES = 32
MAX_SLIDE_BYTES = 460_800            # SlideShow's own limit (TS 101 499 §9.1)
# Room for a broadcast and a fetched pair for every service of a full
# station list (ohs-box's had 123 services, 24/10/2026): 256 until RadioDNS.
LOGO_FILES = 512
LOGO_BYTES = 24 << 20
MAX_SCHEDULES = 64
SCHEDULE_KEEP_S = 86_400.0


def sid_ok(sid) -> bool:
    return isinstance(sid, str) and bool(SID_RE.match(sid))


class DabPictures:
    def __init__(self, data_dir: Path | None, clock=time.time):
        self.dir = Path(data_dir) / "dab" if data_dir is not None else None
        self.clock = clock
        self.lock = threading.Lock()
        self.slides: collections.OrderedDict[str, dict] = collections.OrderedDict()
        self.logos: dict[str, dict[str, dict]] = {}
        self.schedules: dict[str, dict] = {}
        self.rev = 0
        # Whether fetched (RadioDNS) logos are shown; Radio gives it the
        # radioDnsLogos setting.
        self.show_fetched = lambda: True
        self._load()

    # ------------------------------------------------------------ disk
    def _load(self) -> None:
        if self.dir is None:
            return
        for name, into in (("logos.json", "logos"), ("schedules.json", "schedules")):
            try:
                data = json.loads((self.dir / name).read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                setattr(self, into, {k: v for k, v in data.items() if sid_ok(k) and isinstance(v, dict)})
        # Only logos whose file is still there.
        for sid in list(self.logos):
            self.logos[sid] = {v: e for v, e in self.logos[sid].items()
                               if v in VARIANTS and isinstance(e, dict) and (self.dir / str(e.get("file", ""))).is_file()}
            if not self.logos[sid]:
                del self.logos[sid]

    def _write(self, name: str, data: bytes) -> bool:
        """Whole or not at all: a temporary name, then a rename."""
        if self.dir is None:
            return False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f".{name}.part"
            tmp.write_bytes(data)
            os.replace(tmp, self.dir / name)
            return True
        except OSError as e:
            log.warning("could not keep %s: %s", name, e)
            return False

    def _save_index(self, name: str, obj: dict) -> None:
        self._write(name, json.dumps(obj, separators=(",", ":")).encode())

    def _prune_logos(self) -> None:
        """At most LOGO_FILES files and LOGO_BYTES bytes: fetched ones go
        first, then the oldest."""
        entries = sorted(((e.get("source") != "radiodns", e.get("t", 0.0), sid, v)
                          for sid, vs in self.logos.items() for v, e in vs.items()))
        total = sum(int(self.logos[sid][v].get("size", 0)) for _, _, sid, v in entries)
        while entries and (len(entries) > LOGO_FILES or total > LOGO_BYTES):
            _, _, sid, v = entries.pop(0)
            e = self.logos[sid].pop(v)
            total -= int(e.get("size", 0))
            if not self.logos[sid]:
                del self.logos[sid]
            try:
                (self.dir / e["file"]).unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ results
    def take(self, item: dict) -> dict:
        """A decoder result: a `slide`, `logo` or `schedule` frame is kept,
        and comes back without its bytes and with the path that serves it;
        anything else comes back as it was."""
        if item.get("type") != "frame" or item.get("frame") not in ("slide", "logo", "schedule"):
            return item
        fields = dict(item.get("fields") or {})
        raw = item.get("raw")
        out = {k: v for k, v in item.items() if k != "raw"}
        sid = fields.get("sid")
        if not sid_ok(sid):
            return out
        kind = item["frame"]
        t = float(item.get("t") or self.clock())
        with self.lock:
            self.rev += 1
            if kind == "slide":
                ctype = fields.get("contentType")
                if ctype not in TYPES or not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_SLIDE_BYTES:
                    return out
                self.slides.pop(sid, None)
                self.slides[sid] = {"fields": fields, "bytes": bytes(raw), "t": t, "rev": self.rev}
                while len(self.slides) > MAX_SLIDES:
                    self.slides.popitem(last=False)
                fields["path"] = self.slide_path(sid)
            elif kind == "logo":
                ctype, variant = fields.get("contentType"), fields.get("variant")
                if ctype not in TYPES or variant not in VARIANTS or not isinstance(raw, (bytes, bytearray)):
                    return out
                name = f"{sid}-{variant}.{TYPES[ctype]}"
                old = self.logos.get(sid, {}).get(variant)
                if self._write(name, bytes(raw)) or self.dir is None:
                    if old and old.get("file") != name and self.dir is not None:
                        try:
                            (self.dir / old["file"]).unlink()
                        except OSError:
                            pass
                    self.logos.setdefault(sid, {})[variant] = {
                        "file": name, "contentType": ctype, "width": fields.get("width"),
                        "height": fields.get("height"), "size": len(raw), "name": fields.get("name"), "t": t,
                        "source": "broadcast", **({"bytes": bytes(raw)} if self.dir is None else {})}
                    self._logos_changed()
                fields["path"] = self.logo_path(sid, variant)
            else:
                progs = [p for p in fields.get("programmes") or [] if isinstance(p, dict)]
                self.schedules[sid] = {"t": t, "programmes": progs}
                self._prune_schedules()
                self._save_index("schedules.json", self.schedules)
                fields.pop("programmes", None)
                fields["programmes"] = len(progs)
                fields["path"] = f"api/dab/schedule/{sid}"
        out["fields"] = fields
        return out

    def _logos_changed(self) -> None:
        """Under the lock, after a logo went in: the caps, then the index."""
        if self.dir is not None:
            self._prune_logos()
            self._save_index("logos.json", {s: {v: {k: x for k, x in e.items() if k != "bytes"}
                                                for v, e in vs.items()} for s, vs in self.logos.items()})

    def take_fetched(self, sid: str, variant: str, raw: bytes, ctype: str, width, height, url: str) -> bool:
        """A logo from RadioDNS. Refused (False) where the air has brought
        that variant: the broadcast one wins."""
        if not sid_ok(sid) or variant not in VARIANTS or ctype not in TYPES or not raw:
            return False
        with self.lock:
            old = self.logos.get(sid, {}).get(variant)
            if old is not None and old.get("source", "broadcast") != "radiodns":
                return False
            name = f"{sid}-{variant}-radiodns.{TYPES[ctype]}"
            if not (self._write(name, bytes(raw)) or self.dir is None):
                return False
            if old and old.get("file") != name and self.dir is not None:
                try:
                    (self.dir / old["file"]).unlink()
                except OSError:
                    pass
            self.rev += 1
            self.logos.setdefault(sid, {})[variant] = {
                "file": name, "contentType": ctype, "width": width, "height": height, "size": len(raw),
                "t": self.clock(), "source": "radiodns", "url": url,
                **({"bytes": bytes(raw)} if self.dir is None else {})}
            self._logos_changed()
            return sid in self.logos and variant in self.logos[sid]

    def has_broadcast(self, sid, variant: str) -> bool:
        with self.lock:
            e = (self.logos.get(sid) or {}).get(variant)
            return e is not None and e.get("source", "broadcast") != "radiodns"

    def fetched_url(self, sid, variant: str) -> str | None:
        """The URL a fetched logo of that variant came from, None without one."""
        with self.lock:
            e = (self.logos.get(sid) or {}).get(variant)
            return e.get("url") if e is not None and e.get("source") == "radiodns" else None

    def _shown(self, sid) -> dict:
        """Under the lock: a service's logos as they may be shown now."""
        vs = self.logos.get(sid) or {}
        if vs and not self.show_fetched():
            vs = {v: e for v, e in vs.items() if e.get("source", "broadcast") != "radiodns"}
        return vs

    def _prune_schedules(self) -> None:
        now = self.clock()
        for sid, e in list(self.schedules.items()):
            e["programmes"] = [p for p in e["programmes"]
                               if _ts(p.get("start")) + float(p.get("durationS") or 0) > now - SCHEDULE_KEEP_S]
        while len(self.schedules) > MAX_SCHEDULES:
            oldest = min(self.schedules, key=lambda s: self.schedules[s].get("t", 0.0))
            del self.schedules[oldest]

    # ------------------------------------------------------------ serving
    @staticmethod
    def slide_path(sid: str) -> str:
        return f"api/dab/slides/{sid}"

    @staticmethod
    def logo_path(sid: str, variant: str = "square") -> str:
        return f"api/dab/logos/{sid}" + ("" if variant == "square" else f"?variant={variant}")

    def slide(self, sid: str) -> tuple[bytes, str] | None:
        with self.lock:
            s = self.slides.get(sid)
            return (s["bytes"], s["fields"]["contentType"]) if s else None

    def slide_info(self, sid: str) -> dict | None:
        with self.lock:
            s = self.slides.get(sid)
            return dict(s["fields"], path=self.slide_path(sid), rev=s["rev"]) if s else None

    def logo(self, sid: str, variant: str = "square") -> tuple[bytes, str] | None:
        """A service's logo: the variant asked for, else the other one."""
        with self.lock:
            vs = self._shown(sid)
            e = vs.get(variant) or next(iter(vs.values()), None)
            if e is None:
                return None
            if "bytes" in e:
                return e["bytes"], e["contentType"]
            path = self.dir / e["file"]
        try:
            return path.read_bytes(), e["contentType"]
        except OSError:
            return None

    def has_logo(self, sid) -> bool:
        with self.lock:
            return bool(self._shown(sid))

    def logo_paths(self, sid) -> dict:
        """{"logoPath", "logoSource", "logoWidePath", "logoWideSource"} for a
        service with logos ({} without): each source "broadcast" or
        "radiodns", for the picture that path serves."""
        with self.lock:
            vs = {v: e.get("source", "broadcast") for v, e in self._shown(sid).items()}
        out = {}
        if vs:
            v = "square" if "square" in vs else "wide"
            out["logoPath"], out["logoSource"] = self.logo_path(sid, v), vs[v]
        if "wide" in vs:
            out["logoWidePath"], out["logoWideSource"] = self.logo_path(sid, "wide"), vs["wide"]
        return out

    def schedule(self, sid: str, date: str | None = None) -> list[dict] | None:
        """A service's programmes, oldest first; only those starting on
        `date` (UTC, "YYYY-MM-DD") when given. None for a service with none."""
        with self.lock:
            e = self.schedules.get(sid)
            if e is None:
                return None
            progs = list(e["programmes"])
        if date:
            progs = [p for p in progs if str(p.get("start", "")).startswith(date)]
        return progs

    def now_next(self, sid, t: float | None = None) -> tuple[dict | None, dict | None]:
        """What a service has on at UTC `t` (now, from the clock) and what
        comes next, from its stored schedule; (None, None) without one."""
        t = self.clock() if t is None else t
        with self.lock:
            e = self.schedules.get(sid)
            progs = list(e["programmes"]) if e else []
        now = nxt = None
        for p in sorted(progs, key=lambda p: _ts(p.get("start"))):
            start = _ts(p.get("start"))
            dur = float(p.get("durationS") or 0)
            if start <= t and (dur == 0 or t < start + dur):
                now = p
            elif start > t and nxt is None:
                nxt = p
        return now, nxt

    def decorate(self, meta):
        """A DAB session's meta with each service's logo paths, its now and
        next from the stored schedule, and the latest slide's path (a copy;
        anything but a DAB meta as it was).

        Now and next: the decoder works them out only from the programme
        files its own session has heard, which on a real carousel can take
        minutes after the start (BBC National's on 12B: the tablet's beta.8
        check had Radio 4 playing five minutes with null now and next while
        api/dab/schedule already answered from disk). The store keeps every
        schedule heard, across sessions and restarts, so it decides
        whenever it has a programme for the time; the decoder's value
        stands only where the store has none. The time is UTC, from the
        store's clock, so a view fetched later is current even when the
        decoder has sent no new meta (Decoders.tick also re-sends one when
        now or next changes)."""
        if not isinstance(meta, dict) or not isinstance(meta.get("services"), list):
            return meta
        out = dict(meta)
        t = self.clock()
        services = []
        for s in meta["services"]:
            if not isinstance(s, dict):
                services.append(s)
                continue
            sv = dict(s, **self.logo_paths(s.get("sid")))
            now, nxt = self.now_next(s.get("sid"), t)
            if now is not None or nxt is not None:
                sv["now"], sv["next"] = now, nxt
            services.append(sv)
        out["services"] = services
        slide = meta.get("slide")
        if isinstance(slide, dict) and sid_ok(slide.get("sid")):
            # The decoder's meta can name a slide a moment before the
            # supervisor has taken its frame (Decoders.tick): a path only
            # once the picture is here to serve, so a client never fetches
            # a 404.
            info = self.slide_info(slide["sid"])
            out["slide"] = dict(slide, path=self.slide_path(slide["sid"]), rev=info["rev"]) if info else dict(slide)
        return out


def _ts(iso) -> float:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


