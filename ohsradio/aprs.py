"""Stations on a map: Radio's APRS receive (29/10/2026; docs/SERVER-API.md "APRS").

    radio.aprs.join(client)         # POST api/aprs/session: start, or keep alive; raises Refused
    radio.aprs.leave(client)        # DELETE api/aprs/session?client=
    radio.aprs.end("stopped")       # DELETE api/aprs/session?all=1, or the radio stopping
    radio.aprs.view()               # the session (also `aprs` in the state)
    radio.aprs.table.view(...)      # GET api/aprs/stations[?since=rev][&sinceS=seconds]
    radio.aprs.table.station(call)  # GET api/aprs/stations/{call}, with its track and recent packets
    radio.aprs.table.messages()     # GET api/aprs/messages
    radio.aprs.tick(now)            # the supervisor, ten times a second

**Receive only.** Nothing here transmits, digipeats or answers a message:
there is no send path at all, and the receiver hold refuses a key-up while
it runs. shack_packet is used for its receiver and its parser only (its
SDR monitor's Pipeline and `aprs.parse`); its engine, digipeater and
radio links are never imported.

**Shaped exactly like AIS** (ais.py), and for the same reasons: decoding
only while a client has the map open, renewed at least every
CLIENT_LEASE_S (or vouched for by client presence, "aprs" in its holds);
no linger after the last client goes (LINGER_S, 0: CLIENT-UI-PLAN 7.3);
the receiver given back exactly as it was. While it holds the receiver a
tune or a key-up is refused with a sentence saying why; background
decoder sessions pin the span and refuse it `span_pinned` unless the
caller says to stop them (`dropSessions`).

**The receiver.** The dial goes to 144.800 MHz in FM (Engine.hold_receiver
with `tune`), so a client shows what the radio is listening to; the
receiver's centre goes 25 kHz above it (CENTRE_HZ), so its own DC spike -
a zero-IF RSP's LO leakage - sits on no packet station. AIS centres
between its two channels for the same reason. Nothing at the dial is
demodulated (silence plays): the channel is cut from the device's own
samples, as AIS's are.

**Decoding is shack_packet's SDR monitor** (sdr.Pipeline): its FFT
channeliser cuts 144.800 out of the receiver's IQ at about 19.2 kS/s, its
discriminator makes the audio, and its demod.Receiver (two demodulators,
seven slicers each, FX.25) finds the frames; `aprs.parse` reads them
(positions plain, compressed and ambiguous, Mic-E, weather, objects,
items, messages, status - checked against direwolf's decode_aprs in
ohs-libs). Nothing is written twice: no demodulator, channeliser or APRS
parser of Radio's own. aprslib (MIT) was the brief's first thought for
parsing; it was left out because shack_packet's parser already covers
every format this needs and is the family's one (PLATFORM-PLAN 1.4).

The Pipeline runs on a worker thread of its own, fed from the receive
thread through a bounded queue (QUEUE_BLOCKS): about 5 % of one core at
2.4 MS/s (ohs-libs README, "The SDR monitor"), never on the receive
thread, and a stall drops IQ (counted, `dropped`) rather than delaying
the receiver.

**The station table** (StationTable) is keyed by callsign with SSID, and
by name for objects and items: the latest position, symbol, course, speed,
altitude, comment, status and weather each packet brings, merged; when it
was last heard, how many packets, whether directly or through a
digipeater, the path; a short track and the last few packets. Messages
and bulletins heard are kept beside it. Everything is kept for KEEP_S (24
hours, fixed by the TV client's contract rather than a setting, so the
map is never empty on first open) in the data folder
(`aprs/stations.json`), and survives a restart. Every change bumps `rev`;
the `aprs` feed on api/events carries each change as it happens.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from ohscore.countries import distance_bearing
from ohscore.decoders import Refused, sessions_text

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.aprs")

SID = "aprs"
APRS_HZ = 144_800_000.0
# The receiver's centre: 25 kHz above the channel, where shack_packet's own
# ChannelPlan.centre_for puts it (DC 25 kHz clear of every channel), and
# well inside the 2 m band.
CENTRE_HZ = APRS_HZ + 25_000.0
MIN_RATE = 96_000.0
CLIENT_LEASE_S = 30.0
LINGER_S = 0.0            # no linger (ais.py's docstring)
CLIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_CLIENTS = 32
KEEP_S = 24 * 3600.0
# The track: a point when a station has moved TRACK_MIN_M, the last
# TRACK_POINTS of them. A fixed station re-beaconing every ten minutes adds
# none, so the points kept are the ones that draw a line.
TRACK_POINTS = 240
TRACK_MIN_M = 25.0
RECENT_PACKETS = 20
MESSAGES_KEPT = 500
# The same packet heard again within DUPE_S (a digipeater's copy of one
# heard direct, or the other way about) is one packet, as every APRS
# program's 30 s duplicate window has it. A message's retries come minutes
# apart until it is acknowledged, so a message is one for MESSAGE_DUPE_S.
DUPE_S = 30.0
MESSAGE_DUPE_S = 1800.0
# IQ blocks waiting for the worker: some seconds of the receiver at any
# rate Radio runs. Past it a block is dropped, never the receive thread held.
QUEUE_BLOCKS = 64
SAVE_S = 30.0
EXPIRE_EVERY_S = 10.0
REMOVED_KEPT = 2000
HEARD_KEPT = 1000
# Symbols that move (APRS 1.0.1 appendix 2): the primary table's vehicles,
# people, craft and aircraft; the alternate table's few.
MOVING_PRIMARY = set(">kjuvb<[sYO'^XafURP=Ce")
MOVING_ALTERNATE = set(">kusv^")
# shack_packet's weather keys to the contract's.
WX_KEYS = {"tempC": "temp_c", "humidity": "humidity_pct", "pressureHpa": "pressure_hpa",
           "windDirDeg": "wind_dir_deg", "windKmh": "wind_kmh", "gustKmh": "gust_kmh", "rain1hMm": "rain_hour_mm"}


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def station_kind(symbol: str, speed_kmh, weather: bool) -> str:
    """What sort of station a position says it is: "wx", "igate", "digi",
    "mobile" or "station" (objects and items are said by their packet)."""
    table, code = (symbol + "  ")[:2]
    if weather or code == "_":
        return "wx"
    if code == "&":
        return "igate"
    if code == "#":
        return "digi"
    moving = MOVING_PRIMARY if table == "/" else MOVING_ALTERNATE
    if code in moving or (isinstance(speed_kmh, (int, float)) and speed_kmh > 0):
        return "mobile"
    return "station"


def wind_fixed(text: str, p) -> None:
    """A positioned weather report's wind speed in mph, as APRS 1.0.1
    ch. 12 has it (and direwolf reads it, and shack_packet's own
    format_weather writes it). shack_packet 0.2.0 reads the CSE/SPD place
    after a weather symbol as a moving station's speed, in knots
    (aprs._extras), so its wind_kmh is 15 % high; undone here for the
    uncompressed form until ohs-libs fixes it. An `s` field, which the
    library reads right, wins there and is left alone here."""
    pos = p.position
    if pos is None or pos.compressed or not pos.symbol.endswith("_") or "wind_kmh" not in p.weather:
        return
    at = text.find("_")
    if at < 0 or re.search(r"s\d{3}", text[at + 8:].split(" ")[0]):
        return
    mph = round(p.weather["wind_kmh"] / 1.852)
    p.weather["wind_kmh"] = round(mph * 1.609344, 1)


def packet_text(p) -> str:
    """What a packet said, in its sender's words: the status, the message,
    else the comment."""
    if p is None:
        return ""
    return (p.status or p.message or p.comment or "").strip()


class StationTable:
    """Every station, object and item heard, and the messages (module
    docstring). Thread-safe: packets arrive on the supervisor's thread,
    clients read on the server's."""

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()
        self.s: dict[str, dict] = {}
        self.tracks: dict[str, deque] = {}         # key -> [t, lat, lon]
        self.recent: dict[str, deque] = {}         # key -> [t, raw, text]
        self.msgs: deque = deque(maxlen=MESSAGES_KEPT)    # [t, from, to, text, id]
        self.seen: dict[tuple, float] = {}         # (source, info) -> when first heard
        self.rev = 0
        self.removed: deque = deque(maxlen=REMOVED_KEPT)  # (rev, key)
        self.dirty = False
        self.saved_at = 0.0
        self.load()
        self.expire(time.time())

    # -- packets ----------------------------------------------------------
    def heard(self, frame, packet, t: float) -> dict:
        """One AX.25 frame (shack_packet ax25.Frame) and its APRS reading
        (aprs.Packet, or None for one that is not APRS) heard at UTC `t`:
        {"stations": [entries changed], "removed": [keys], "message": the
        message heard or None}."""
        out = {"stations": [], "removed": [], "message": None}
        src = str(frame.source)
        info = bytes(frame.info)
        direct = not frame.digipeated
        with self.lock:
            first = self.seen.get((src, info))
            if first is not None and t - first < DUPE_S:
                # A copy of one already heard: only whether it came direct.
                v = self.s.get(src)
                if direct and v is not None and not v["heardDirect"]:
                    v["heardDirect"] = True
                    out["stations"].append(self._bump(v))
                return out
            self.seen[(src, info)] = t
            raw = frame.monitor()
            text = packet_text(packet)
            v = self._entry(src, t)
            v["packets"] += 1
            v["heardDirect"] = direct
            v["via"] = list(frame.path)
            self._recent(src, t, raw, text)
            kind = packet.kind if packet is not None else ""
            if kind in ("object", "item"):
                name = packet.name
                if name and not packet.live:
                    if self.s.pop(name, None) is not None:
                        self.tracks.pop(name, None)
                        self.recent.pop(name, None)
                        self.rev += 1
                        self.removed.append((self.rev, name))
                        out["removed"].append(name)
                elif name and packet.position is not None:
                    o = self._entry(name, t)
                    o["kind"], o["owner"] = kind, src
                    o["packets"] += 1
                    o["heardDirect"], o["via"] = direct, list(frame.path)
                    self._position(o, packet, t)
                    self._recent(name, t, raw, text)
                    out["stations"].append(self._bump(o))
            elif packet is not None:
                wind_fixed(frame.text(), packet)
                if packet.position is not None:
                    self._position(v, packet, t)
                elif packet.weather:
                    self._weather(v, packet)
                    v["kind"] = "wx"
                if kind == "status" and packet.status:
                    v["status"] = packet.status.strip()
                if kind == "message" and packet.addressee:
                    out["message"] = self._message(src, packet, t)
            out["stations"].insert(0, self._bump(v))
            self.dirty = True
            if len(self.seen) > 4 * HEARD_KEPT:
                self.seen = {k: w for k, w in self.seen.items() if t - w < MESSAGE_DUPE_S}
        return out

    def _entry(self, key: str, t: float) -> dict:
        v = self.s.get(key)
        if v is None:
            v = self.s[key] = {"call": key, "kind": "station", "symbol": None, "lat": None, "lon": None,
                               "courseDeg": None, "speedKmh": None, "altM": None, "comment": "", "status": "",
                               "lastHeard": None, "lastHeardTs": None, "firstHeard": _iso(t), "heardDirect": False,
                               "via": [], "packets": 0, "source": "rf", "wx": None}
        v["lastHeard"], v["lastHeardTs"] = _iso(t), t
        return v

    def _bump(self, v: dict) -> dict:
        self.rev += 1
        v["rev"] = self.rev
        return dict(v)

    def _position(self, v: dict, p, t: float) -> None:
        pos = p.position
        v["lat"], v["lon"] = round(pos.lat, 6), round(pos.lon, 6)
        if len(pos.symbol) == 2:
            v["symbol"] = {"table": pos.symbol[0], "code": pos.symbol[1]}
        v["courseDeg"], v["speedKmh"] = p.course_deg, p.speed_kmh
        if p.altitude_m is not None:
            v["altM"] = p.altitude_m
        if p.comment and p.comment.strip():
            v["comment"] = p.comment.strip()
        if p.weather:
            self._weather(v, p)
        if v["kind"] not in ("object", "item"):
            v["kind"] = station_kind(pos.symbol, p.speed_kmh, bool(p.weather))
        tr = self.tracks.setdefault(v["call"], deque(maxlen=TRACK_POINTS))
        if tr:
            km, _b = distance_bearing(tr[-1][1], tr[-1][2], v["lat"], v["lon"])
            if km * 1000.0 < TRACK_MIN_M:
                return
        tr.append([round(t, 1), v["lat"], v["lon"]])

    @staticmethod
    def _weather(v: dict, p) -> None:
        wx = dict(v["wx"] or {k: None for k in WX_KEYS})
        for mine, theirs in WX_KEYS.items():
            if theirs in p.weather:
                wx[mine] = p.weather[theirs]
        v["wx"] = wx

    def _recent(self, key: str, t: float, raw: str, text: str) -> None:
        self.recent.setdefault(key, deque(maxlen=RECENT_PACKETS)).append([round(t, 1), raw, text])

    def _message(self, src: str, p, t: float) -> dict | None:
        """A message or bulletin heard (never answered: receive only)."""
        mid = p.message_id or None
        for m in reversed(self.msgs):
            if t - m[0] >= MESSAGE_DUPE_S:
                break
            if (m[1], m[2], m[3], m[4]) == (src, p.addressee, p.message, mid):
                return None                       # a retry of one already heard
        m = [round(t, 1), src, p.addressee, p.message, mid]
        self.msgs.append(m)
        return self._message_view(m)

    @staticmethod
    def _message_view(m: list) -> dict:
        return {"t": _iso(m[0]), "from": m[1], "to": m[2], "text": m[3], "id": m[4]}

    # -- ageing -------------------------------------------------------------
    def expire(self, now: float, keep_s: float = KEEP_S) -> list[str]:
        """Drop everything not heard for `keep_s`; the keys dropped."""
        with self.lock:
            gone = [k for k, v in self.s.items() if now - float(v.get("lastHeardTs") or 0) > keep_s]
            for k in gone:
                self.s.pop(k, None)
                self.tracks.pop(k, None)
                self.recent.pop(k, None)
                self.rev += 1
                self.removed.append((self.rev, k))
            for d in (self.tracks, self.recent):
                for q in d.values():
                    while q and now - q[0][0] > keep_s:
                        q.popleft()
            while self.msgs and now - self.msgs[0][0] > keep_s:
                self.msgs.popleft()
                self.dirty = True
            if gone:
                self.dirty = True
        return gone

    # -- views --------------------------------------------------------------
    def view(self, since: int | None = None, since_s: float | None = None, now: float | None = None) -> dict:
        """{rev, full, stations, removed}, newest first: every station, or
        (`since`, a rev) only those changed after it and the keys removed
        after it, as ais.VesselTable.view; and (`since_s`, seconds) only
        those heard in the last that many seconds."""
        now = time.time() if now is None else now
        with self.lock:
            oldest = self.removed[0][0] if len(self.removed) == self.removed.maxlen else 0
            full = since is None or since < oldest or since > self.rev
            out = [dict(v) for v in self.s.values() if full or v.get("rev", 0) > since]
            removed = [] if full else [k for r, k in self.removed if r > since]
            rev = self.rev
        if since_s is not None:
            out = [v for v in out if now - float(v.get("lastHeardTs") or 0) <= since_s]
        out.sort(key=lambda v: (-float(v.get("lastHeardTs") or 0), v["call"]))
        return {"rev": rev, "full": full, "stations": out, "removed": removed}

    def station(self, key: str) -> dict | None:
        with self.lock:
            v = self.s.get(key)
            if v is None:
                return None
            out = dict(v)
            out["track"] = [{"t": _iso(p[0]), "lat": p[1], "lon": p[2]} for p in self.tracks.get(key, ())]
            out["recent"] = [{"t": _iso(p[0]), "raw": p[1], "text": p[2]} for p in self.recent.get(key, ())]
        return out

    def messages(self) -> list[dict]:
        """Every message and bulletin heard in the last KEEP_S, oldest first."""
        with self.lock:
            return [self._message_view(m) for m in self.msgs]

    def __len__(self) -> int:
        return len(self.s)

    # -- disk -----------------------------------------------------------------
    def load(self) -> None:
        if self.path is None:
            return
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict) or doc.get("schema") != 1:
            return
        for v in doc.get("stations", []):
            if isinstance(v, dict) and isinstance(v.get("call"), str):
                self.s[v["call"]] = v
        for name, store, n in (("tracks", self.tracks, TRACK_POINTS), ("recent", self.recent, RECENT_PACKETS)):
            for k, items in (doc.get(name) or {}).items():
                if k in self.s and isinstance(items, list):
                    store[k] = deque((list(p) for p in items if isinstance(p, list) and len(p) == 3), maxlen=n)
        for m in doc.get("messages") or []:
            if isinstance(m, list) and len(m) == 5:
                self.msgs.append(m)
        self.rev = int(doc.get("rev") or 0)

    def save(self, force: bool = False) -> None:
        if self.path is None:
            return
        with self.lock:
            if not self.dirty or (not force and time.time() - self.saved_at < SAVE_S):
                return
            doc = {"schema": 1, "rev": self.rev, "stations": list(self.s.values()),
                   "tracks": {k: list(q) for k, q in self.tracks.items()},
                   "recent": {k: list(q) for k, q in self.recent.items()}, "messages": list(self.msgs)}
            self.dirty, self.saved_at = False, time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save the APRS station table: %s", e)


class AprsService:
    """The APRS session and the station table (module docstring)."""

    def __init__(self, radio):
        self.radio = radio
        folder = Path(radio.data_dir) / "aprs" if getattr(radio, "data_dir", None) else None
        self.table = StationTable(folder / "stations.json" if folder is not None else None)
        self.lock = threading.RLock()
        self.clients: dict[str, float] = {}
        self.state = "idle"
        self.why: str | None = None
        self.started_at: float | None = None
        self.linger_until: float | None = None
        # Set by the server: whether client presence vouches for a client
        # ("aprs" in its holds), as AisService.vouch.
        self.vouch = None
        self.q: queue.Queue | None = None
        self.worker: threading.Thread | None = None
        self.heard: deque = deque(maxlen=HEARD_KEPT)     # decoded, for tick
        self.index = 0
        self.counts = {"frames": 0, "packets": 0, "dropped": 0}
        self.expired_at = 0.0
        self._published: dict | None = None

    # -- the session --------------------------------------------------------
    def texts(self) -> dict:
        return {"tune": _("The receiver is listening to APRS on 144.800 MHz for the station map: close the map, "
                          "or stop APRS, to tune or change mode"),
                "transmit": _("The receiver is listening to APRS for the station map: stop APRS to transmit"),
                "on_air": _("Not while transmitting: APRS takes the receiver to 144.800 MHz"),
                "busy": _("APRS has the receiver for the station map: stop APRS first")}

    def join(self, client: str, drop_sessions: bool = False) -> dict:
        """Client `client` has the map open: start APRS if it is not
        running, and keep it running for CLIENT_LEASE_S more. Raises
        Refused (code, sentence) when it cannot start."""
        client = str(client or "")
        if not CLIENT_RE.match(client):
            raise Refused("bad_client", _("The client must name itself: 1-64 letters, digits, '.', '_', ':' or "
                                          "'-'"))
        now = time.monotonic()
        with self.lock:
            if client not in self.clients and len(self.clients) >= MAX_CLIENTS:
                raise Refused("too_many_clients", _("Too many screens have the APRS map open"))
            if self.state != "running":
                self._start(drop_sessions)
            self.clients[client] = now + CLIENT_LEASE_S
            self.linger_until = None
            self._publish()
            return self.view()

    def _vouched(self, client: str) -> bool:
        try:
            return self.vouch is not None and bool(self.vouch(client))
        except Exception:  # noqa: BLE001 - a vouch that fails vouches for nobody
            return False

    def leave(self, client: str) -> dict:
        with self.lock:
            if self.clients.pop(str(client or ""), None) is not None and not self.clients and \
                    self.state == "running":
                self.linger_until = time.monotonic() + LINGER_S
            self._publish()
            return self.view()

    def _start(self, drop_sessions: bool) -> None:
        r = self.radio
        from ohscore import shacklibs
        try:
            # The SDR monitor is a subpackage the package's own import
            # leaves out: asked for by name, so a wheel without it refuses
            # here rather than on the worker.
            sdr = importlib.import_module(shacklibs.packet().__name__ + ".sdr")
        except ImportError:
            raise Refused("decoder_unavailable", _("APRS needs the shack_packet library, which this install does "
                                                   "not have")) from None
        if not r.running:
            raise Refused("not_running", _("Start the radio to see APRS stations: APRS needs the receiver"))
        pinning = r.decoders.pinned_by() if r.PINS_SPAN else []
        if pinning:
            if not drop_sessions:
                raise Refused("span_pinned", _("APRS takes the receiver to 144.800 MHz and stops {sessions}")
                              .format(sessions=sessions_text(pinning)), sessions=pinning)
            r.decoders.stop_background()
        r.client_activity("decoder")
        r.hold_receiver(SID, "aprs", CENTRE_HZ, "APRS", MIN_RATE, feed=self._feed, texts=self.texts(),
                        tune={"vfo": APRS_HZ, "mode": "fm"})
        self.q = queue.Queue(maxsize=QUEUE_BLOCKS)
        self.index = 0
        self.counts = {"frames": 0, "packets": 0, "dropped": 0}
        self.worker = threading.Thread(target=self._work, args=(sdr, self.q), name="aprs", daemon=True)
        self.worker.start()
        self.state, self.why = "running", None
        self.started_at = time.time()
        log.info("APRS started: 144.800 MHz, the receiver at %.3f MHz", CENTRE_HZ / 1e6)

    def end(self, why: str = "stopped") -> None:
        """End the session now, whoever has the map open: the receiver back
        as it was. `why` as ais.AisService.end."""
        # As AIS: the receiver given back before the state says idle.
        with self.lock:
            q, worker, self.q, self.worker = self.q, self.worker, None, None
            if q is not None:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    # The worker drains a full queue in well under its join
                    # below; one more try, then it sees self.q gone.
                    try:
                        q.get_nowait()
                        q.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass
            if self.state == "running":
                h = self.radio.held
                if h is not None and h.get("session") == SID:
                    self.radio.release_receiver(SID)
                log.info("APRS ended (%s)", why)
            self.state, self.why = "idle", why
            self.clients.clear()
            self.linger_until = None
        if worker is not None and worker is not threading.current_thread():
            worker.join(2.0)
        self.table.save(force=True)
        self._publish()

    def _feed(self, raw, settled: bool) -> None:
        """The receive thread, once per block, while APRS holds the
        receiver: the block onto the worker's queue, or dropped."""
        q = self.q
        n = len(raw)
        r = self.radio
        if q is None or not settled or r.centre is None:
            self.index += n
            return
        try:
            q.put_nowait((raw.copy(), self.index, time.time() - n / float(r.geo.fs), float(r.geo.fs),
                          float(r.centre)))
        except queue.Full:
            self.counts["dropped"] += 1
        self.index += n

    def _work(self, sdr, q: queue.Queue) -> None:
        """The worker: IQ blocks through shack_packet's Pipeline, made
        afresh whenever the rate or the centre is not the one it was made
        for (a gap in `index` it notices itself and resynchronises)."""
        plan = sdr.ChannelPlan((sdr.Channel("aprs", APRS_HZ, "APRS", "aprs"),))
        pipe, made_for = None, None
        while True:
            item = q.get()
            if item is None or self.q is not q:
                return
            raw, index, t, fs, centre = item
            try:
                if made_for != (fs, centre):
                    pipe, made_for = sdr.Pipeline(fs, centre, plan, spectrum=False, diversity=True), (fs, centre)
                for d in pipe.process(sdr.IqBlock(raw, index, t)):
                    self.heard.append(d)
            except Exception:  # noqa: BLE001 - a block the pipeline cannot take costs that block
                log.warning("APRS: a block could not be decoded", exc_info=True)
                pipe, made_for = None, None

    # -- the supervisor ------------------------------------------------------
    def tick(self, now_mono: float | None = None) -> None:
        now = time.monotonic() if now_mono is None else now_mono
        r = self.radio
        with self.lock:
            if self.state == "running":
                for c, until in list(self.clients.items()):
                    if until < now and not self._vouched(c):
                        del self.clients[c]
                if not self.clients and self.linger_until is None:
                    self.linger_until = now + LINGER_S
                lost = r.held is None or r.held.get("session") != SID
                if not r.running:
                    self.end("radio_stopped")
                elif lost:
                    self.end("lost")
                elif self.linger_until is not None and now >= self.linger_until:
                    self.end("idle")
        while self.heard:
            try:
                d = self.heard.popleft()
            except IndexError:
                break
            self._frame(d)
        t = time.time()
        if t - self.expired_at >= EXPIRE_EVERY_S:
            self.expired_at = t
            for key in self.table.expire(t):
                r._publish("aprs", {"type": "removed", "call": key, "rev": self.table.rev})
        self.table.save()
        self._publish()

    def _frame(self, d) -> None:
        """One decoded frame (shack_packet sdr.Decoded) into the table and
        onto the feed."""
        self.counts["frames"] += 1
        f = d.frame
        if f is None:
            return
        r = self.radio
        r._publish("aprs", {"type": "packet", "t": _iso(d.time), "raw": f.monitor(), "call": str(f.source),
                            "aprs": d.aprs is not None})
        if d.aprs is None:
            return
        self.counts["packets"] += 1
        got = self.table.heard(f, d.aprs, float(d.time))
        for v in got["stations"]:
            r._publish("aprs", {"type": "station", "rev": v["rev"], "station": v})
        for key in got["removed"]:
            r._publish("aprs", {"type": "removed", "call": key, "rev": self.table.rev})
        if got["message"] is not None:
            r._publish("aprs", {"type": "message", "message": got["message"]})

    # -- views -------------------------------------------------------------
    def view(self) -> dict:
        with self.lock:
            now = time.monotonic()
            ends = None
            if self.state == "running" and self.linger_until is not None:
                ends = max(0.0, self.linger_until - now)
            return {"state": self.state, "why": self.why, "text": self._text(), "clients": len(self.clients),
                    "startedAt": _iso(self.started_at) if self.state == "running" else None,
                    "endsInS": None if ends is None else round(ends, 1), "freqHz": APRS_HZ,
                    "centreHz": CENTRE_HZ, "leaseS": CLIENT_LEASE_S, "lingerS": LINGER_S,
                    "keepS": KEEP_S, "stations": len(self.table), "rev": self.table.rev, **self.counts}

    def _text(self) -> str:
        if self.state == "running":
            return _("Listening to APRS on 144.800 MHz")
        return {"idle": _("Stopped: nobody had the APRS map open"),
                "stopped": _("Stopped"),
                "radio_stopped": _("Stopped: the radio stopped"),
                "lost": _("Stopped: the receiver was taken back")}.get(self.why or "", _("Not running"))

    def _publish(self) -> None:
        v = self.view()
        key = {"state": v["state"], "why": v["why"], "clients": v["clients"], "ending": v["endsInS"] is not None}
        if key != self._published:
            self._published = key
            self.radio._status(aprs=v)
            self.radio._publish("aprs", {"type": "session", "session": v})
