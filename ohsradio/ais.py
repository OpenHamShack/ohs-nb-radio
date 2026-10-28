"""Ships on a map: Radio's AIS (Brian, 28/10/2026; docs/SERVER-API.md "AIS").

    radio.ais.join(client)        # POST api/ais/session: start, or keep alive; raises Refused
    radio.ais.leave(client)       # DELETE api/ais/session?client=
    radio.ais.end("stopped")      # DELETE api/ais/session?all=1, or the radio stopping
    radio.ais.view()              # the session (also `ais` in the state)
    radio.ais.table.view(since)   # GET api/ais/vessels[?since=rev]
    radio.ais.table.vessel(mmsi)  # GET api/ais/vessels/{mmsi}, with its track
    radio.ais.tick(now)           # the supervisor, ten times a second

**Decoding only while someone looks.** AIS needs the whole receiver at
162 MHz, so it runs only while a client has its map open: the client
starts the session and renews it (`join`) at least every CLIENT_LEASE_S;
a client that leaves says so, or simply stops renewing. The session ends
LINGER_S after the last client has gone - long enough that a TV moving
between views, or a phone that slept a moment, does not hand the receiver
to and fro - and gives the receiver back exactly as it was.

**The receiver.** Held like a DAB station's (Engine.hold_receiver;
`rxOwner` says so): the dial and the receiver's centre to 162.000 MHz,
midway between the channels 87B (161.975, "A") and 88B (162.025, "B"), so
the receiver's own DC spike sits 25 kHz from both and on neither. Nothing
at the dial is demodulated (silence plays). While it holds, a tune or a
key-up is refused with a sentence saying why; the operator ends it with
`end` (DELETE api/ais/session?all=1) or by closing the map. Background
decoder sessions pin the span: AIS is refused `span_pinned` unless the
caller says to stop them (`dropSessions`), as DAB is. When it ends, the
dial, mode and repeater offset from before and the receiver's centre are
put back (Engine.release_receiver, Radio._held_retune).

**Gain and notches** (Radio's broadcast policy, bcastgain.py; notch.py).
The operator's gain stands unless the receiver reports overload: AIS is a
weak-signal service like 2 m, not a broadcast multiplex, so it starts at
the operator's own gain rather than broadcast's lower default, steps down
only on debounced overload and creeps back. The RSP's DAB notch is held
out: its stopband is >30 dB from 160 to 230 MHz (the RSPdx datasheet,
notch.py), so the auto rule putting it in on overload - right on 2 m -
would take 30 dB off AIS itself.

**Decoding** is shack_sdr's `ais` decoder on a host of its own (one
worker, as a held DAB session has: a stuck decoder starves only itself),
fed the device's own samples at its own rate; at 2.4 MS/s it costs about
3 % of a core (ohs-libs tests/ais.rs).

**The vessel table** (VesselTable) is keyed by MMSI: the latest position,
course, speed, heading, navigational status, name, callsign, type,
dimensions and destination each message type brings, merged; when it was
last heard and how many messages; its distance and bearing from the
station's locator; and a short track. A vessel not heard for
`aisKeepMinutes` is dropped. It is kept in the data folder
(`ais/vessels.json`) and survives a restart, so a map opened after one
shows the ships it had, as old as they are. Every change bumps `rev`, so a
client asks only for what changed (`since`), and the `ais` feed on
api/events carries each change as it happens.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from ohscore import sdr
from ohscore.countries import distance_bearing, locator_position
from ohscore.decoders import Refused, sessions_text

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.ais")

SID = "ais"
CENTRE_HZ = 162_000_000.0
MIN_RATE = 96_000.0
CLIENT_LEASE_S = 30.0
LINGER_S = 60.0
CLIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_CLIENTS = 32
# The track: a point when a vessel has moved TRACK_MIN_M or TRACK_MIN_S
# has passed, the last TRACK_POINTS of them (two hours of a ship reporting
# every minute or moving 25 m between reports).
TRACK_POINTS = 120
TRACK_MIN_M = 25.0
TRACK_MIN_S = 60.0
# The fastest a reported position may move from the last one: 60 knots
# (the standard's speed field tops out at 102.2, but nothing afloat near a
# shore station does 60), plus 1 km for GNSS jitter and the slack between
# when a ship fixed its position and when we heard it. A position past it
# is set aside (`jumps`); a second one that agrees with it is taken - the
# old one was the wrong one - so a vessel cannot be stuck on a bad first fix.
JUMP_MAX_M_S = 60 * 1852.0 / 3600.0
JUMP_SLACK_M = 1000.0
SAVE_S = 30.0
EXPIRE_EVERY_S = 10.0
# Changes remembered for `since` (a client further behind gets the whole table).
REMOVED_KEPT = 2000


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ship_type_text(code) -> str | None:
    """The ship type's words (ITU-R M.1371-5 Table 53); None for 0 (not
    available) or no code."""
    if not isinstance(code, (int, float)) or int(code) <= 0:
        return None
    c = int(code)
    exact = {30: _("Fishing"), 31: _("Towing"), 32: _("Towing, long or wide"), 33: _("Dredging or underwater ops"),
             34: _("Diving ops"), 35: _("Military ops"), 36: _("Sailing"), 37: _("Pleasure craft"),
             50: _("Pilot vessel"), 51: _("Search and rescue vessel"), 52: _("Tug"), 53: _("Port tender"),
             54: _("Anti-pollution"), 55: _("Law enforcement"), 58: _("Medical transport"),
             59: _("Non-combatant ship")}
    if c in exact:
        return exact[c]
    group = {2: _("Wing in ground"), 4: _("High-speed craft"), 6: _("Passenger"), 7: _("Cargo"), 8: _("Tanker"),
             9: _("Other type")}.get(c // 10)
    return group or _("Reserved")


def nav_status_text(code) -> str | None:
    """The navigational status's words (Table 45); None for 15 (not defined)."""
    if not isinstance(code, (int, float)):
        return None
    return {0: _("Under way using engine"), 1: _("At anchor"), 2: _("Not under command"),
            3: _("Restricted manoeuvrability"), 4: _("Constrained by her draught"), 5: _("Moored"),
            6: _("Aground"), 7: _("Engaged in fishing"), 8: _("Under way sailing"), 14: _("AIS-SART active")
            }.get(int(code))


def aid_type_text(code) -> str | None:
    """An aid to navigation's kind (Table 74), in brief."""
    if not isinstance(code, (int, float)) or int(code) <= 0:
        return None
    c = int(code)
    if c == 1:
        return _("Reference point")
    if c == 2:
        return _("RACON")
    if c == 3:
        return _("Fixed structure off shore")
    if 5 <= c <= 19:
        return _("Fixed light or beacon")
    if 20 <= c <= 31:
        return _("Floating buoy or light vessel")
    return _("Aid to navigation")


def station_class(kind: int, mmsi: int) -> str:
    """What sort of station: "A" or "B" (ships' two classes), "base",
    "aton" (an aid to navigation), "sar" (an aircraft), "sart" (a
    distress beacon: SART, MOB or EPIRB, 970/972/974xxxxxx), "other"."""
    if 970_000_000 <= mmsi < 980_000_000:
        return "sart"
    if kind in (1, 2, 3, 5):
        return "A"
    if kind in (18, 19, 24):
        return "B"
    if kind in (4, 11):
        return "base"
    if kind == 21:
        return "aton"
    if kind == 9:
        return "sar"
    return "other"


class VesselTable:
    """Every station heard, by MMSI (module docstring). Thread-safe: frames
    arrive on the supervisor's thread, clients read on the server's."""

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()
        self.v: dict[int, dict] = {}
        self.tracks: dict[int, deque] = {}
        self.rev = 0
        self.removed: deque = deque(maxlen=REMOVED_KEPT)    # (rev, mmsi)
        self.dirty = False
        self.saved_at = 0.0
        self.station: tuple[float, float] | None = None
        self.load()

    # -- the station ------------------------------------------------------
    def set_station(self, locator: str) -> None:
        pos = locator_position(locator or "")
        if pos == self.station:
            return
        self.station = pos
        with self.lock:
            for v in self.v.values():
                self._range(v)

    def _range(self, v: dict) -> None:
        if self.station is not None and v.get("lat") is not None and v.get("lon") is not None:
            km, brg = distance_bearing(self.station[0], self.station[1], v["lat"], v["lon"])
            v["distanceKm"], v["bearingDeg"] = round(km, 2), round(brg, 1)
        else:
            v["distanceKm"] = v["bearingDeg"] = None

    # -- frames -----------------------------------------------------------
    def heard(self, f: dict, t: float) -> dict | None:
        """One decoded frame's fields (shack_sdr's `ais` frame) heard at UTC
        `t`: the vessel as it now stands, or None for a frame with no MMSI."""
        try:
            mmsi = int(f.get("mmsi") or 0)
            kind = int(f.get("type") or 0)
        except (TypeError, ValueError):
            return None
        if mmsi <= 0:
            return None
        if f.get("plausible") is False:
            # shack_sdr's own check (its msg::plausible: the MMSI's form for
            # the message type, numbers in range): kept off the map, and
            # never the first word of a new vessel.
            return None
        with self.lock:
            v = self.v.get(mmsi)
            if v is None:
                v = self.v[mmsi] = {"mmsi": mmsi, "class": station_class(kind, mmsi), "messages": 0,
                                    "firstHeard": _iso(t)}
            v["messages"] += 1
            v["lastHeardTs"] = t
            v["lastHeard"] = _iso(t)
            v["channel"] = f.get("channel")
            v["snrDb"] = f.get("snrDb")
            v["lastType"] = kind
            if v["class"] in ("other",) and station_class(kind, mmsi) != "other":
                v["class"] = station_class(kind, mmsi)
            self._merge(v, kind, f, t)
            self.rev += 1
            v["rev"] = self.rev
            self.dirty = True
            return dict(v)

    def _merge(self, v: dict, kind: int, f: dict, t: float) -> None:
        def take(*keys, rename=None):
            for k in keys:
                if k in f:
                    v[(rename or {}).get(k, k)] = f[k]

        def text(k, to=None):
            if f.get(k):
                v[to or k] = f[k]

        if kind in (1, 2, 3, 18, 19, 27) or (kind in (4, 9, 11, 21) and f.get("lat") is not None):
            if f.get("lat") is not None and f.get("lon") is not None and self._believable(v, f, t):
                v["lat"], v["lon"] = f["lat"], f["lon"]
                v["positionAt"] = _iso(t)
                v["positionTs"] = t
                v["accuracy"] = bool(f.get("accuracy"))
                self._range(v)
                self._track(v, t)
            take("speed", "course", "heading")
        if kind in (1, 2, 3, 27):
            take("navStatus")
            v["navStatusText"] = nav_status_text(v.get("navStatus"))
        if kind in (1, 2, 3):
            take("turn")
        if kind == 5:
            text("shipName", "name")
            text("callsign")
            take("imo", "destination", "draught", "toBow", "toStern", "toPort", "toStarboard", "shipType")
            m, d, h, mi = (f.get(k) for k in ("etaMonth", "etaDay", "etaHour", "etaMinute"))
            v["eta"] = f"{m:02.0f}-{d:02.0f} {h or 0:02.0f}:{mi or 0:02.0f}" if m and d else None
        if kind == 19:
            text("shipName", "name")
            take("shipType", "toBow", "toStern", "toPort", "toStarboard")
        if kind == 24:
            if f.get("partNo") == 0:
                text("shipName", "name")
            else:
                text("callsign")
                text("vendorId")
                take("shipType", "toBow", "toStern", "toPort", "toStarboard", "mothershipMmsi")
        if kind == 21:
            text("name")
            take("aidType", "virtualAid", "offPosition", "toBow", "toStern", "toPort", "toStarboard")
            v["aidTypeText"] = aid_type_text(v.get("aidType"))
        if "shipType" in v:
            v["shipTypeText"] = ship_type_text(v.get("shipType"))
        bow, stern, port, stbd = (v.get(k) for k in ("toBow", "toStern", "toPort", "toStarboard"))
        v["length"] = (bow + stern) if isinstance(bow, (int, float)) and isinstance(stern, (int, float)) \
            and bow + stern > 0 else None
        v["beam"] = (port + stbd) if isinstance(port, (int, float)) and isinstance(stbd, (int, float)) \
            and port + stbd > 0 else None

    def _believable(self, v: dict, f: dict, t: float) -> bool:
        """Whether position `f` could follow the vessel's last one (JUMP_*).
        Not believed, it is kept as `pendingPos`, and a later one that could
        follow *it* is believed. Off the map either way until then."""
        def reach(a, b, dt):
            km, _ = distance_bearing(a[0], a[1], b[0], b[1])
            return km * 1000.0 <= JUMP_SLACK_M + JUMP_MAX_M_S * max(dt, 0.0)

        new = (f["lat"], f["lon"])
        if v.get("lat") is None or v.get("positionTs") is None:
            return True
        if reach((v["lat"], v["lon"]), new, t - v["positionTs"]):
            v.pop("pendingPos", None)
            return True
        p = v.get("pendingPos")
        if p is not None and reach((p[0], p[1]), new, t - p[2]):
            v.pop("pendingPos", None)
            return True
        v["pendingPos"] = [new[0], new[1], t]
        v["jumps"] = int(v.get("jumps") or 0) + 1
        return False

    def _track(self, v: dict, t: float) -> None:
        tr = self.tracks.setdefault(v["mmsi"], deque(maxlen=TRACK_POINTS))
        point = [round(t, 1), v["lat"], v["lon"], v.get("speed"), v.get("course")]
        if tr:
            last = tr[-1]
            km, _b = distance_bearing(last[1], last[2], v["lat"], v["lon"])
            if km * 1000 < TRACK_MIN_M and t - last[0] < TRACK_MIN_S:
                return
        tr.append(point)

    # -- ageing -------------------------------------------------------------
    def expire(self, now: float, keep_s: float) -> list[int]:
        """Drop every vessel not heard for `keep_s`; the MMSIs dropped."""
        with self.lock:
            gone = [m for m, v in self.v.items() if now - float(v.get("lastHeardTs") or 0) > keep_s]
            for m in gone:
                self.v.pop(m, None)
                self.tracks.pop(m, None)
                self.rev += 1
                self.removed.append((self.rev, m))
            if gone:
                self.dirty = True
        return gone

    # -- views --------------------------------------------------------------
    def view(self, since: int | None = None) -> dict:
        """{rev, full, vessels, removed}: every vessel, or (`since`) only
        those changed after that rev and the MMSIs removed after it. A
        `since` older than the removals remembered, or newer than now (a
        restart reset the count), gets the whole table, `full` true."""
        with self.lock:
            oldest = self.removed[0][0] if len(self.removed) == self.removed.maxlen else 0
            full = since is None or since < oldest or since > self.rev
            vessels = [dict(v) for v in self.v.values() if full or v.get("rev", 0) > since]
            removed = [] if full else [m for r, m in self.removed if r > since]
            rev = self.rev
        vessels.sort(key=lambda v: (v.get("distanceKm") is None, v.get("distanceKm") or 0.0, v["mmsi"]))
        return {"rev": rev, "full": full, "vessels": vessels, "removed": removed}

    def vessel(self, mmsi: int) -> dict | None:
        with self.lock:
            v = self.v.get(mmsi)
            if v is None:
                return None
            out = dict(v)
            out["track"] = [{"t": _iso(p[0]), "lat": p[1], "lon": p[2], "speed": p[3], "course": p[4]}
                            for p in self.tracks.get(mmsi, ())]
        return out

    def __len__(self) -> int:
        return len(self.v)

    # -- disk -----------------------------------------------------------------
    def load(self) -> None:
        if self.path is None:
            return
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        # Schema 2 since the decoder read real air right (28/10/2026): a
        # table saved by beta.13 holds only scrambled frames (its decoder
        # had each octet's bits reversed) and is dropped, not shown.
        if not isinstance(doc, dict) or doc.get("schema") != 2:
            return
        for v in doc.get("vessels", []):
            if isinstance(v, dict) and isinstance(v.get("mmsi"), int):
                self.v[v["mmsi"]] = v
        for k, tr in (doc.get("tracks") or {}).items():
            try:
                self.tracks[int(k)] = deque((list(p) for p in tr), maxlen=TRACK_POINTS)
            except (TypeError, ValueError):
                continue
        self.rev = int(doc.get("rev") or 0)

    def save(self, force: bool = False) -> None:
        if self.path is None:
            return
        with self.lock:
            if not self.dirty or (not force and time.time() - self.saved_at < SAVE_S):
                return
            doc = {"schema": 2, "rev": self.rev, "vessels": list(self.v.values()),
                   "tracks": {str(m): list(tr) for m, tr in self.tracks.items()}}
            self.dirty, self.saved_at = False, time.time()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("could not save the vessel table: %s", e)


class AisService:
    """The AIS session and the vessel table (module docstring)."""

    def __init__(self, radio):
        self.radio = radio
        folder = Path(radio.data_dir) / "ais" if getattr(radio, "data_dir", None) else None
        self.table = VesselTable(folder / "vessels.json" if folder is not None else None)
        self.lock = threading.RLock()
        self.clients: dict[str, float] = {}
        self.state = "idle"
        self.why: str | None = None
        self.started_at: float | None = None
        self.linger_until: float | None = None
        self.host = None
        self.sid: str | None = None
        self.index = 0
        self.offset: float | None = None
        self.counts = {"frames": 0, "channelA": 0, "channelB": 0, "damaged": 0, "implausible": 0}
        self.expired_at = 0.0
        self._published: dict | None = None

    # -- the session --------------------------------------------------------
    def texts(self) -> dict:
        return {"tune": _("The receiver is listening to AIS for the ship map: close the map, or stop AIS, to "
                          "tune or change mode"),
                "transmit": _("The receiver is listening to AIS for the ship map: stop AIS to transmit"),
                "on_air": _("Not while transmitting: AIS takes the receiver to 162 MHz"),
                "busy": _("AIS has the receiver for the ship map: stop AIS first")}

    def join(self, client: str, drop_sessions: bool = False) -> dict:
        """Client `client` has the map open: start AIS if it is not
        running, and keep it running for CLIENT_LEASE_S more. Raises
        Refused (code, sentence) when it cannot start."""
        client = str(client or "")
        if not CLIENT_RE.match(client):
            raise Refused("bad_client", _("The client must name itself: 1-64 letters, digits, '.', '_', ':' or "
                                          "'-'"))
        now = time.monotonic()
        with self.lock:
            if client not in self.clients and len(self.clients) >= MAX_CLIENTS:
                raise Refused("too_many_clients", _("Too many screens have the ship map open"))
            if self.state != "running":
                self._start(drop_sessions)
            self.clients[client] = now + CLIENT_LEASE_S
            self.linger_until = None
            self._publish()
            return self.view()

    def leave(self, client: str) -> dict:
        with self.lock:
            if self.clients.pop(str(client or ""), None) is not None and not self.clients and \
                    self.state == "running":
                self.linger_until = time.monotonic() + LINGER_S
            self._publish()
            return self.view()

    def _start(self, drop_sessions: bool) -> None:
        r = self.radio
        m = sdr.load()
        if m is None:
            raise Refused("decoder_unavailable", _("AIS needs the shack_sdr library, which this install does not "
                                                   "have"))
        if not r.running:
            raise Refused("not_running", _("Start the radio to see ships: AIS needs the receiver"))
        pinning = r.decoders.pinned_by() if r.PINS_SPAN else []
        if pinning:
            if not drop_sessions:
                raise Refused("span_pinned", _("AIS takes the receiver to 162 MHz and stops {sessions}")
                              .format(sessions=sessions_text(pinning)), sessions=pinning)
            r.decoders.stop_background()
        r.client_activity("decoder")
        r.hold_receiver(SID, "ais", CENTRE_HZ, "AIS", MIN_RATE, feed=self._feed, texts=self.texts())
        host = m.Host(threads=1, cpu_max=0.0, ring_s=2.0, max_sessions=1)
        try:
            sid = host.start("ais", {"offsetHz": 0.0}, input="iq", rate=float(r.geo.fs), pinned=True)
        except Exception:
            host.close()
            r.release_receiver(SID)
            raise
        self.host, self.sid, self.index, self.offset = host, sid, 0, 0.0
        self.state, self.why = "running", None
        self.started_at = time.time()
        self.counts = {"frames": 0, "channelA": 0, "channelB": 0, "damaged": 0, "implausible": 0}
        log.info("AIS started: the receiver at %.3f MHz", CENTRE_HZ / 1e6)

    def end(self, why: str = "stopped") -> None:
        """End the session now, whoever has the map open: the receiver back
        as it was. `why`: "stopped" (asked), "idle" (nobody looking),
        "radio_stopped", "lost" (the receiver was taken back)."""
        # All of it under the lock, the receiver given back before the state
        # says idle: a client that reads "idle" finds the receiver its own.
        # (The engine never calls in here holding its own lock, so taking
        # the engine's inside this one cannot deadlock.)
        with self.lock:
            host, self.host, self.sid = self.host, None, None
            if host is not None:
                try:
                    host.close()
                except Exception:  # noqa: BLE001 - closing a host that failed is still closing it
                    log.warning("AIS: closing its decoder host", exc_info=True)
            if self.state == "running":
                h = self.radio.held
                if h is not None and h.get("session") == SID:
                    self.radio.release_receiver(SID)
                log.info("AIS ended (%s)", why)
            self.state, self.why = "idle", why
            self.clients.clear()
            self.linger_until = None
        self.table.save(force=True)
        self._publish()

    def _feed(self, raw, settled: bool) -> None:
        """The receive thread, once per block, while AIS holds the receiver."""
        host, sid = self.host, self.sid
        if host is None:
            return
        n = len(raw)
        r = self.radio
        if not settled or r.centre is None:
            self.index += n
            return
        off = CENTRE_HZ - float(r.centre)
        if off != self.offset:
            try:
                host.configure(sid, {"offsetHz": off})
                self.offset = off
            except Exception:  # noqa: BLE001 - an offset out of range: fed as it is
                pass
        try:
            host.feed(sid, raw, time.time() - n / float(r.geo.fs), self.index)
        except Exception:  # noqa: BLE001 - the host closing under us
            return
        self.index += n

    # -- the supervisor ------------------------------------------------------
    def tick(self, now_mono: float | None = None) -> None:
        now = time.monotonic() if now_mono is None else now_mono
        r = self.radio
        self.table.set_station(r.st.get("locator") or "")
        with self.lock:
            if self.state == "running":
                for c, until in list(self.clients.items()):
                    if until < now:
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
            host, sid = self.host, self.sid
        if host is not None:
            try:
                items = host.poll()
            except Exception:  # noqa: BLE001 - closed between the read and now
                items = []
            for it in items:
                if it.get("session") != sid:
                    continue
                if it.get("type") == "frame" and it.get("frame") == "ais":
                    self._frame(it)
            try:
                # The decoder's counters are in the session's `stats`. Read
                # as "counters" (beta.13), damaged showed 0 on real air beside
                # 99 frames, which looked like a CRC never checked.
                st = host.status(sid).get("stats") or {}
                self.counts["damaged"] = int(st.get("damaged", 0))
                self.counts["implausible"] = int(st.get("implausible", 0))
            except Exception:  # noqa: BLE001
                pass
        t = time.time()
        if t - self.expired_at >= EXPIRE_EVERY_S:
            self.expired_at = t
            keep = float(r.st.get("aisKeepMinutes", 60)) * 60.0
            for mmsi in self.table.expire(t, keep):
                r._publish("ais", {"type": "removed", "mmsi": mmsi, "rev": self.table.rev})
        self.table.save()
        self._publish()

    def _frame(self, it: dict) -> None:
        f = it.get("fields") or {}
        v = self.table.heard(f, float(it.get("t") or time.time()))
        self.counts["frames"] += 1
        ch = f.get("channel")
        if ch in ("A", "B"):
            self.counts["channel" + ch] += 1
        r = self.radio
        r._publish("ais", {"type": "nmea", "t": it.get("t"), "channel": ch, "mmsi": f.get("mmsi"),
                           "msgType": f.get("type"), "sentences": f.get("nmea") or []})
        if v is not None:
            r._publish("ais", {"type": "vessel", "rev": v["rev"], "vessel": v})

    # -- views -------------------------------------------------------------
    def view(self) -> dict:
        with self.lock:
            now = time.monotonic()
            ends = None
            if self.state == "running" and self.linger_until is not None:
                ends = max(0.0, self.linger_until - now)
            return {"state": self.state, "why": self.why, "text": self._text(), "clients": len(self.clients),
                    "startedAt": _iso(self.started_at) if self.state == "running" else None,
                    "endsInS": None if ends is None else round(ends, 1), "centreHz": CENTRE_HZ,
                    "leaseS": CLIENT_LEASE_S, "lingerS": LINGER_S, "vessels": len(self.table),
                    "rev": self.table.rev, **self.counts}

    def _text(self) -> str:
        if self.state == "running":
            return _("Listening to AIS on 161.975 and 162.025 MHz")
        return {"idle": _("Stopped: nobody had the ship map open"),
                "stopped": _("Stopped"),
                "radio_stopped": _("Stopped: the radio stopped"),
                "lost": _("Stopped: the receiver was taken back")}.get(self.why or "", _("Not running"))

    def _publish(self) -> None:
        v = self.view()
        # The countdown itself is not news ten times a second; that it began is.
        key = {"state": v["state"], "why": v["why"], "clients": v["clients"], "ending": v["endsInS"] is not None}
        if key != self._published:
            self._published = key
            self.radio._status(ais=v)
            self.radio._publish("ais", {"type": "session", "session": v})
