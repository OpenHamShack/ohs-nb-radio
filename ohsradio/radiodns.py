"""DAB station logos from RadioDNS (24/10/2026; docs/SERVER-API.md "Logos
from RadioDNS").

A DAB service's logo comes over the air in its ensemble's SPI service
(ohscore/dabpics.py), but only after minutes of listening to that
ensemble, so a fresh station list shows almost none. Most UK broadcasters
also publish the same service information on the internet, found through
RadioDNS (ETSI TS 103 270) and written in the same SPI format (ETSI TS 102
818). This module fetches it in the background and gives the logos to the
same store the over-the-air ones go to, so `api/dab/logos/{sid}` serves
both and no client ever touches the internet.

Brian allowed it "as long as it can still be used without internet still":
**offline, everything is exactly as before**. No route, a resolver that
does not answer, a timeout, a refusal or the `radioDnsLogos` setting off
all end the same way - the logos the air brought and nothing else, nothing
on any listener's screen, one log line per cause. So:

- **Never on a path anything waits for.** One daemon thread, at the lowest
  priority the system gives a thread, started only for the program an
  operator runs (Radio's `persist`; a test's throw-away radio starts none),
  that does nothing for STARTUP_DELAY_S after start and then wakes every
  CHECK_S, or when a band scan stores a new DAB list (`nudge`). A scan,
  a session or playback never waits for it, and it holds the logo store's
  lock only to put a finished picture in.
- **Short timeouts and backoff per host.** DNS gets DNS_TIMEOUT_S per
  server, HTTP HTTP_TIMEOUT_S per request. A failure (timeout, no route,
  a server error) puts that host - "dns" for the resolver - in backoff,
  BACKOFF_BASE_S doubling to BACKOFF_MAX_S, kept on disk so a restart
  cannot undo it; a failing resolver ends the whole run, since nothing
  after it can work. Nothing loops faster than CHECK_S.
- **The setting off means no traffic at all**: it is read before every
  query and request, and while it is off the store shows none of the
  fetched logos either (dabpics.py `show_fetched`), as before the feature.

**What goes out.** DNS queries for `<scids>.<sid>.<eid>.<gcc>.dab.radiodns.org`
(CNAME) and `_radiospi._tcp.<the broadcaster's name>` (SRV, else the older
`_radioepg._tcp`) to the system's own resolvers; then plain GETs, one per
broadcaster for its SI.xml and one per logo picture, to the hosts those
documents name. The User-Agent is "OpenHamShack-Radio/<version>" and that
is all a request says about this station: no cookies (the opener has no
cookie handler), no query string of ours, no callsign, locator or address.

**The resolver is our own**, a minimal one over UDP: Python's standard
library cannot ask for an SRV (or a CNAME) record, and Radio carries no
DNS package. The servers are /etc/resolv.conf's `nameserver` lines (inside
a Dock360 container too: pasta writes one), or on Windows the registry's;
none found is a cause like any other ("no resolver"). $OHS_RADIODNS_RESOLVER
("host:port") overrides them: tests/scratch_home.py points it at a closed
local port, so a test can never ask the real internet.

**Which logos.** Of each service's `multimedia` elements, as the
over-the-air path chooses (shack_sdr spi.rs `choose`): `square` the square
one nearest 128x128, `wide` the landscape one nearest 320x240. Over the
air wins: a variant the air has already brought is never fetched, and one
that comes later replaces the fetched one (dabpics.py). A weekly look
(REFRESH_S) refetches a picture only when its URL changed (broadcasters
version theirs: `...1077.png?ver=...`).

**The service's name.** A service is looked up with its ensemble's EId and
the ECC that ensemble sends (bandscan.py keeps it since this module; an
older list has only the ISO country, turned back into the ECC by
COUNTRY_ECC), SCIdS 0 (the primary component). Only 16-bit audio SIds:
RadioDNS has no DAB lookup for a data service. A service listed in several
ensembles is looked up once, through the first ensemble that names it.

Programme information (PI.xml) is not fetched: the air brings the guide
for the ensembles that send one, and a guide per service per day is many
more requests for little.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import random
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger("ohsradio.radiodns")

STATE_FILE = "radiodns.json"        # in the logo store's folder (data/dab)
STARTUP_DELAY_S = 120.0
CHECK_S = 900.0
REFRESH_S = 7 * 86_400.0
DNS_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 10.0
BACKOFF_BASE_S = 600.0
BACKOFF_MAX_S = 86_400.0
PAUSE_S = 0.2                       # between HTTP requests: no burst at a broadcaster
MAX_DOC_BYTES = 8 << 20             # BBC's SI.xml was 340 kB, Planet Radio's 300 kB (24/10/2026)
MAX_LOGO_BYTES = 1 << 20
SPI_PATH = "/radiodns/spi/3.1/SI.xml"
XSI_PATH = "/radiodns/epg/XSI.xml"  # the older RadioEPG name for the same document

T_CNAME, T_SRV = 5, 33
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"

# ISO 3166 country -> {country id (the SId's first nibble): ECC}, ETSI TS
# 101 756 tables 3-7: the inverse of shack_sdr codes.rs `country`, for a
# station list made before the ECC was kept with it.
_ECC_TABLE = {
    0xE0: {0x1: "DE", 0x2: "DZ", 0x3: "AD", 0x4: "IL", 0x5: "IT", 0x6: "BE", 0x7: "RU", 0x8: "PS", 0x9: "AL",
           0xA: "AT", 0xB: "HU", 0xC: "MT", 0xD: "DE", 0xF: "EG"},
    0xE1: {0x1: "GR", 0x2: "CY", 0x3: "SM", 0x4: "CH", 0x5: "JO", 0x6: "FI", 0x7: "LU", 0x8: "BG", 0x9: "DK",
           0xA: "GI", 0xB: "IQ", 0xC: "GB", 0xD: "LY", 0xE: "RO", 0xF: "FR"},
    0xE2: {0x1: "MA", 0x2: "CZ", 0x3: "PL", 0x4: "VA", 0x5: "SK", 0x6: "SY", 0x7: "TN", 0x9: "LI", 0xA: "IS",
           0xB: "MC", 0xC: "LT", 0xE: "ES", 0xF: "NO"},
    0xE3: {0x2: "IE", 0x3: "TR", 0x8: "NL", 0x9: "LV", 0xA: "LB", 0xC: "HR", 0xE: "SE"},
    0xE4: {0x2: "EE", 0x8: "PT", 0x9: "SI"},
}
COUNTRY_ECC = {(iso, cid): ecc for ecc, row in _ECC_TABLE.items() for cid, iso in row.items()}


def user_agent() -> str:
    """The program and its version, nothing else (module docstring)."""
    try:
        version = VERSION_FILE.read_text().strip()
    except OSError:
        version = "0"
    return f"OpenHamShack-Radio/{version}"


# ---------------------------------------------------------------- names
def fqdn(sid: str, eid: str, ecc: str | None, country: str | None, scids: int = 0) -> str | None:
    """The RadioDNS name of a DAB service (TS 103 270 5.1.2), or None when
    it cannot be made: `0.c224.ce15.ce1.dab.radiodns.org` for SId C224 in
    ensemble CE15 with ECC E1."""
    sid, eid = str(sid or "").lower(), str(eid or "").lower()
    if len(sid) != 4 or len(eid) != 4 or not all(c in "0123456789abcdef" for c in sid + eid):
        return None
    cid = int(sid[0], 16)
    e = str(ecc or "").lower()
    if len(e) != 2 or not all(c in "0123456789abcdef" for c in e):
        found = COUNTRY_ECC.get((str(country or "").upper(), cid))
        if found is None:
            return None
        e = f"{found:02x}"
    return f"{scids:x}.{sid}.{eid}.{sid[0]}{e}.dab.radiodns.org"


def bearer(name: str) -> str:
    """The SPI bearer id the same service is listed under: `dab:ce1.ce15.c224.0`."""
    scids, sid, eid, gcc = name.split(".")[:4]
    return f"dab:{gcc}.{eid}.{sid}.{scids}"


# ---------------------------------------------------------------- DNS
class DnsFailure(Exception):
    """The resolver did not answer usefully: no route, a timeout, SERVFAIL,
    a refusal. Not "there is no such name", which is an answer."""


def system_resolvers() -> list[tuple[str, int]]:
    """The resolvers to ask: $OHS_RADIODNS_RESOLVER, else the system's."""
    env = os.environ.get("OHS_RADIODNS_RESOLVER", "").strip()
    if env:
        host, _, port = env.rpartition(":")
        try:
            return [(host.strip("[]") or "127.0.0.1", int(port))]
        except ValueError:
            return []
    out = []
    try:
        for line in Path("/etc/resolv.conf").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                out.append(parts[1].split("%")[0])
    except OSError:
        pass
    if not out and sys.platform == "win32":
        out = _windows_resolvers()
    good = []
    for a in out:
        try:
            ipaddress.ip_address(a)
            good.append((a, 53))
        except ValueError:
            continue
    return good


def _windows_resolvers() -> list[str]:
    """Every interface's NameServer / DhcpNameServer, the registry's record
    of what Windows itself asks."""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                    for name in ("NameServer", "DhcpNameServer"):
                        try:
                            val = winreg.QueryValueEx(sub, name)[0]
                        except OSError:
                            continue
                        out += [a for a in str(val).replace(",", " ").split() if a not in out]
    except OSError:
        return []
    return out


def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("ascii")
        if not 0 < len(raw) < 64:
            raise ValueError(name)
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _read_name(msg: bytes, off: int) -> tuple[str, int]:
    """A (possibly compressed) name at `off`: (name, offset after it)."""
    labels, end, hops = [], None, 0
    while True:
        if off >= len(msg):
            raise DnsFailure("truncated name")
        n = msg[off]
        if n & 0xC0 == 0xC0:
            if off + 1 >= len(msg) or hops > 32:
                raise DnsFailure("bad name pointer")
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | msg[off + 1]
            hops += 1
            continue
        if n == 0:
            return ".".join(labels), (end if end is not None else off + 1)
        labels.append(msg[off + 1:off + 1 + n].decode("ascii", "replace"))
        off += 1 + n


def dns_query(name: str, qtype: int, servers: list[tuple[str, int]], timeout: float = DNS_TIMEOUT_S) -> list:
    """Ask each server in turn; the first answer wins. CNAME: [target];
    SRV: [(priority, weight, port, target)], best first. [] when the name
    or record does not exist (an answer). Raises DnsFailure when no server
    answered usefully."""
    if not servers:
        raise DnsFailure("no resolver")
    qid = random.getrandbits(16)
    q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + _encode_name(name) + struct.pack(">HH", qtype, 1)
    why = "no answer"
    for i, (host, port) in enumerate(list(servers)):
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(fam, socket.SOCK_DGRAM) as s:
                s.settimeout(timeout)
                s.connect((host, port))
                s.send(q)
                deadline = time.monotonic() + timeout
                while True:
                    s.settimeout(max(0.01, deadline - time.monotonic()))
                    msg = s.recv(4096)
                    if len(msg) >= 12 and struct.unpack(">H", msg[:2])[0] == qid:
                        break
        except OSError as e:          # timeout, unreachable, refused: the next server
            why = e.__class__.__name__ if isinstance(e, socket.timeout) else (e.strerror or str(e))
            continue
        flags = struct.unpack(">H", msg[2:4])[0]
        rcode = flags & 0xF
        if not flags & 0x8000 or flags & 0x0200:
            why = "truncated answer" if flags & 0x0200 else "not an answer"
            continue
        if rcode not in (0, 3):
            why = f"rcode {rcode}"
            continue
        if i:
            # The one that answered goes first from now on: a dead first
            # server would otherwise cost its timeout on every query.
            servers.insert(0, servers.pop(i))
        return [] if rcode == 3 else _answers(msg, name, qtype)   # 3, NXDOMAIN: an answer
    raise DnsFailure(why)


def _answers(msg: bytes, name: str, qtype: int) -> list:
    qd, an = struct.unpack(">HH", msg[4:8])
    off = 12
    for _ in range(qd):
        _, off = _read_name(msg, off)
        off += 4
    out = []
    for _ in range(an):
        _, off = _read_name(msg, off)
        if off + 10 > len(msg):
            raise DnsFailure("truncated record")
        rtype, _, _, rdlen = struct.unpack(">HHIH", msg[off:off + 10])
        off += 10
        rdata_at = off
        off += rdlen
        if rtype != qtype:
            continue                  # an SRV query answered through a CNAME: the CNAME itself
        if rtype == T_CNAME:
            out.append(_read_name(msg, rdata_at)[0].lower())
        elif rtype == T_SRV and rdlen >= 7:
            pri, weight, port = struct.unpack(">HHH", msg[rdata_at:rdata_at + 6])
            out.append((pri, weight, port, _read_name(msg, rdata_at + 6)[0].lower()))
    if qtype == T_SRV:
        out.sort(key=lambda r: (r[0], -r[1]))
    return out


# ---------------------------------------------------------------- SPI documents
class EntitiesRefused(ValueError):
    """A document declaring entities: nothing legitimate needs them, and
    they are how an XML bomb works."""


def parse_si(data: bytes) -> dict[str, list[dict]]:
    """An SPI SI.xml (or RadioEPG XSI.xml): {bearer id: [multimedia]}, each
    multimedia {"url", "width", "height"}. Namespaces are ignored: SPI 3.1,
    its predecessors and XSI name the same elements in different ones."""
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        raise EntitiesRefused()
    root = ET.fromstring(data)
    out: dict[str, list[dict]] = {}

    def local(el):
        return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""

    for svc in root.iter():
        if local(svc) != "service":
            continue
        ids, pics = [], []
        for el in svc.iter():
            tag = local(el)
            if tag in ("bearer", "serviceID") and el.get("id"):
                ids.append(el.get("id").strip().lower())
            elif tag == "multimedia" and el.get("url"):
                w, h = el.get("width"), el.get("height")
                kind = el.get("type", "")
                if not (w and h):
                    # The two sizes the spec fixes by type (TS 102 818 5.2.6).
                    w, h = {"logo_colour_square": ("32", "32"), "logo_colour_rectangle": ("112", "32")}.get(
                        kind, (None, None))
                try:
                    pics.append({"url": el.get("url").strip(), "width": int(w), "height": int(h)})
                except (TypeError, ValueError):
                    continue
        for i in ids:
            out.setdefault(i, pics)
    return out


def choose(pics: list[dict]) -> dict[str, dict]:
    """{"square": ..., "wide": ...} as the over-the-air path picks them."""
    out = {}
    for variant, (ww, wh), square in (("square", (128, 128), True), ("wide", (320, 240), False)):
        cands = [p for p in pics if (p["width"] == p["height"]) == square and (square or p["width"] > p["height"])]
        if cands:
            out[variant] = min(cands, key=lambda p: abs(p["width"] - ww) + abs(p["height"] - wh))
    return out


def find_service(doc: dict[str, list[dict]], bearer_id: str) -> list[dict] | None:
    """A service's multimedia by its bearer, else by GCC and SId under any
    ensemble: a broadcaster lists one bearer for a service that several
    ensembles carry, and an SId is unique within its country."""
    if bearer_id in doc:
        return doc[bearer_id]
    gcc, _, sid, _ = bearer_id[4:].split(".")
    for b, pics in doc.items():
        p = b[4:].split(".") if b.startswith("dab:") else []
        if len(p) >= 3 and p[0] == gcc and p[2] == sid:
            return pics
    return None


def sniff(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def png_size(raw: bytes) -> tuple[int, int] | None:
    if len(raw) >= 24 and raw[12:16] == b"IHDR":
        return struct.unpack(">II", raw[16:24])
    return None


class HttpFailure(Exception):
    """A request that may work later: no route, a timeout, a server error."""


class HttpRefused(Exception):
    """A definite no (4xx, not a picture, too big): no point asking again soon."""


def _opener():
    # No HTTPCookieProcessor: urllib keeps no cookies unless given one.
    # addheaders emptied so nothing but our own headers goes out.
    op = urllib.request.build_opener()
    op.addheaders = []
    return op


def http_get(url: str, limit: int, timeout: float = HTTP_TIMEOUT_S) -> bytes:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise HttpRefused("not http")
    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    try:
        with _opener().open(req, timeout=timeout) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500 and e.code not in (408, 429):
            raise HttpRefused(f"HTTP {e.code}") from None
        raise HttpFailure(f"HTTP {e.code}") from None
    except (OSError, ValueError) as e:       # URLError, timeouts, resets, a bad URL
        raise HttpFailure(getattr(e, "reason", None) and str(e.reason) or e.__class__.__name__) from None
    if len(data) > limit:
        raise HttpRefused("too big")
    return data


# ---------------------------------------------------------------- the worker
class RadioDns:
    """The background fetcher (module docstring). `stations` returns the
    stored DAB ensembles (bandscan records), `enabled` the setting; `get`
    and `resolvers` are the network, replaced by a test's fakes only where
    a socket cannot stand in."""

    def __init__(self, pics, stations, enabled, clock=time.time, resolvers=system_resolvers, get=http_get,
                 pause_s: float = PAUSE_S):
        self.pics = pics
        self.stations = stations
        self.enabled = enabled
        self.clock = clock
        self.resolvers = resolvers
        self.get = get
        self.pause_s = pause_s
        self.lock = threading.Lock()          # one run at a time
        self.wake = threading.Event()
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self.logged: set = set()
        self.path = pics.dir / STATE_FILE if getattr(pics, "dir", None) is not None else None
        self.services: dict[str, dict] = {}
        self.hosts: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------ disk
    def _load(self) -> None:
        if self.path is None:
            return
        try:
            got = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(got, dict):
            self.services = {k: v for k, v in (got.get("services") or {}).items() if isinstance(v, dict)}
            self.hosts = {k: v for k, v in (got.get("hosts") or {}).items() if isinstance(v, dict)}

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name("." + STATE_FILE + ".part")
            tmp.write_text(json.dumps({"services": self.services, "hosts": self.hosts}, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as e:
            log.log(self._level(("disk", str(e))), "could not keep the RadioDNS state: %s", e)

    # ------------------------------------------------------------ the thread
    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="radio-radiodns", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()
        self.wake.set()

    def nudge(self) -> None:
        """A band scan stored a new DAB list: look at its services soon."""
        self.wake.set()

    def _loop(self) -> None:
        try:
            # The lowest priority a thread can ask for: on Linux a thread's
            # own id takes a nice value of its own.
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
        except (AttributeError, OSError):
            pass
        if self.stop_ev.wait(STARTUP_DELAY_S):
            return
        while not self.stop_ev.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001  a bug here must never reach a listener, nor end the thread
                log.warning("RadioDNS look-up failed", exc_info=True)
            self.wake.wait(CHECK_S)
            self.wake.clear()

    # ------------------------------------------------------------ logging and backoff
    def _level(self, cause) -> int:
        """INFO the first time for a cause, then DEBUG: an offline station
        would otherwise log the same line every quarter of an hour. Log
        lines only: nothing here ever reaches a listener."""
        if cause in self.logged:
            return logging.DEBUG
        self.logged.add(cause)
        return logging.INFO

    def backing_off(self, host: str) -> bool:
        return float(self.hosts.get(host, {}).get("until", 0.0)) > self.clock()

    def _failed(self, host: str, why: str) -> None:
        h = self.hosts.setdefault(host, {"failures": 0})
        h["failures"] = int(h.get("failures", 0)) + 1
        wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (h["failures"] - 1))
        h["until"] = self.clock() + wait
        log.log(self._level((host, why)), "RadioDNS: %s failed (%s); next try in %.0f min", host, why, wait / 60)

    def _worked(self, host: str) -> None:
        self.hosts.pop(host, None)

    def _go(self) -> bool:
        return bool(self.enabled()) and not self.stop_ev.is_set()

    # ------------------------------------------------------------ a run
    def due(self) -> list[tuple[str, str]]:
        """[(sid, name)] of the stored services that need a look: never
        looked at, looked at under another name, or a week ago."""
        now = self.clock()
        out, seen = [], set()
        for ens in self.stations() or []:
            for s in ens.get("services") or []:
                sid = str(s.get("sid") or "").upper()
                if sid in seen:
                    continue
                name = fqdn(sid, ens.get("id"), ens.get("ecc"), ens.get("country"))
                if name is None:
                    continue
                seen.add(sid)
                rec = self.services.get(sid)
                if rec is None or rec.get("fqdn") != name or now - float(rec.get("checkedAt", 0)) > REFRESH_S:
                    out.append((sid, name))
        return out

    def run_once(self) -> dict:
        """One look at every due service; returns counts (for the coverage
        tool and tests). Does nothing with the setting off."""
        counts = {"due": 0, "looked": 0, "found": 0, "logos": 0, "stopped": None}
        if not self._go():
            counts["stopped"] = "off"
            return counts
        with self.lock:
            try:
                return self._run(counts)
            finally:
                self._save()

    def _run(self, counts: dict) -> dict:
        todo = self.due()
        counts["due"] = len(todo)
        if not todo:
            return counts
        if self.backing_off("dns"):
            counts["stopped"] = "backoff"
            return counts
        servers = self.resolvers()
        # Each broadcaster's SPI server, from its CNAME target.
        groups: dict[tuple, list[tuple[str, str]]] = {}
        srv_of: dict[str, tuple | None] = {}
        for sid, name in todo:
            if not self._go():
                counts["stopped"] = "off"
                return counts
            try:
                target = dns_query(name, T_CNAME, servers)
                target = target[0] if target else None
                if target is not None and target not in srv_of:
                    srv = (dns_query(f"_radiospi._tcp.{target}", T_SRV, servers), "spi")
                    if not srv[0]:
                        srv = (dns_query(f"_radioepg._tcp.{target}", T_SRV, servers), "epg")
                    # A target of "." says the service is deliberately not
                    # offered (RFC 2782): as good as no record.
                    srv_of[target] = (srv[0][0][3], srv[0][0][2], srv[1]) if srv[0] and srv[0][0][3] else None
            except DnsFailure as e:
                self._failed("dns", str(e))
                counts["stopped"] = "dns"
                return counts
            except ValueError:            # a CNAME target we cannot ask about
                target = None
            self._worked("dns")
            spi = srv_of.get(target) if target else None
            if spi is None:
                self.services[sid] = {"fqdn": name, "checkedAt": self.clock(), "found": False}
                counts["looked"] += 1
                continue
            groups.setdefault(spi, []).append((sid, name))
        for (host, port, kind), members in groups.items():
            if not self._go():
                counts["stopped"] = "off"
                return counts
            doc = self._document(host, port, kind)
            if doc is None:
                continue                 # backing off, or failed: looked at again later
            for sid, name in members:
                if not self._go():
                    counts["stopped"] = "off"
                    return counts
                counts["looked"] += 1
                pics = find_service(doc, bearer(name))
                done = True
                n = 0
                for variant, pic in choose(pics or []).items():
                    got = self._logo(sid, variant, pic)
                    if got is None:
                        done = False
                    n += bool(got)
                if pics is not None:
                    counts["found"] += 1
                counts["logos"] += n
                if done:
                    self.services[sid] = {"fqdn": name, "checkedAt": self.clock(), "found": pics is not None}
        return counts

    def _document(self, host: str, port: int, kind: str) -> dict | None:
        key = f"{host}:{port}"
        if self.backing_off(key):
            return None
        base = (f"https://{host}" if port == 443 else f"http://{host}" + ("" if port == 80 else f":{port}"))
        paths = [SPI_PATH] if kind == "spi" else [SPI_PATH, XSI_PATH]
        for i, path in enumerate(paths):
            try:
                data = self.get(base + path, MAX_DOC_BYTES)
                self._pause()
                doc = parse_si(data)
            except HttpFailure as e:
                self._failed(key, str(e))
                return None
            except (HttpRefused, ValueError, ET.ParseError) as e:
                if i + 1 < len(paths):
                    continue
                # No document there: an answer, so no backoff; its services
                # are marked looked-at and asked again in a week.
                log.log(self._level((key, 0)), "RadioDNS: no service information at %s (%s)", key, e)
                self._worked(key)
                return {}
            self._worked(key)
            return doc
        return {}

    def _logo(self, sid: str, variant: str, pic: dict) -> bool | None:
        """Fetch one chosen picture into the store. True stored or already
        held, False none to be had (the air's own, a refusal), None failed
        for now."""
        if self.pics.has_broadcast(sid, variant):
            return False
        if self.pics.fetched_url(sid, variant) == pic["url"]:
            return True
        host = urllib.parse.urlsplit(pic["url"]).netloc or pic["url"]
        if self.backing_off(host):
            return None
        if not self._go():
            return None
        try:
            raw = self.get(pic["url"], MAX_LOGO_BYTES)
            self._pause()
        except HttpFailure as e:
            self._failed(host, str(e))
            return None
        except HttpRefused as e:
            log.log(self._level((host, 0)), "RadioDNS: %s refused a logo (%s)", host, e)
            return False
        self._worked(host)
        ctype = sniff(raw)
        if ctype is None:
            log.log(self._level((host, 1)), "RadioDNS: %s sent a logo that is not PNG or JPEG", host)
            return False
        w, h = png_size(raw) or (pic["width"], pic["height"])
        return self.pics.take_fetched(sid, variant, raw, ctype, w, h, pic["url"])

    def _pause(self) -> None:
        if self.pause_s:
            self.stop_ev.wait(self.pause_s)
