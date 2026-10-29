"""Aircraft on a map: Radio's ADS-B (Brian, 28/10/2026; docs/SERVER-API.md "ADS-B").

    radio.adsb.join(client)          # POST api/adsb/session: start, or keep alive; raises Refused
    radio.adsb.leave(client)         # DELETE api/adsb/session?client=
    radio.adsb.end("stopped")        # DELETE api/adsb/session?all=1, or the radio stopping
    radio.adsb.view()                # the session (also `adsb` in the state)
    radio.adsb.table.view(since)     # GET api/adsb/aircraft[?since=rev]
    radio.adsb.table.aircraft(icao)  # GET api/adsb/aircraft/{icao}, with its track
    radio.adsb.tick(now)             # the supervisor, ten times a second

Shaped exactly like AIS (ais.py): decoding only while a client has the map
open, a CLIENT_LEASE_S lease the client renews (or client presence
vouches for), no linger after the last one goes (LINGER_S, 0, as AIS since
28/10/2026), the receiver held and given back as it was. What differs:

**The rate.** Mode S's bits differ around ±1 MHz from the carrier, so the
receiver's IF filter decides what can be heard (shack_sdr README, ADS-B).
An SDRplay RSP below 5 MS/s filters to 1.536 MHz, and a real capture made
so on ohs-box (28/10/2026, 2.4 MS/s) gave no ADS-B message to any decoder;
at 6 MS/s it opens 5 MHz and the worst bit's margin more than triples. So
the session opens an RSP at RSP_RATE (6 MS/s: the most the engine's
12 kHz decimation allows below 8, and the same 5 MHz filter 8 would get),
and anything else at MIN_RATE (2.4 MS/s, an RTL-SDR's dump1090 rate) if
it runs slower. A different rate means reopening the radio
(Radio.restart_at): the device is closed and opened again at the new rate
under the same broker claim, and when the session ends it is reopened at
the operator's own `sampleRate` - the operator's setting is never
changed. The engine's rule that a rate change is the operator's choice
(Engine._rate_sentence) is kept in spirit: the operator chose ADS-B by
opening the map, and gets the radio back as it was. A reopen ends any
recording in progress; a recording started while ADS-B holds the receiver
records at its rate and centre.

**The receiver** is held at 1090.000 MHz exactly: the hold puts the centre
on the hold's frequency, not the dial path's offset (rxLo), so the whole
2 MHz of Mode S sits in the band. The decoder works on the magnitude, so
the receiver's DC spike in the middle of it is taken out by its DC blocker.

**Gain and notches:** the operator's gain stands unless the receiver
reports overload (bcastgain.py, as for AIS); both RSP notches stay out,
whatever their settings (Brian's brief), though neither's stopband
reaches 1090 MHz.

**Decoding** is shack_sdr's `adsb` decoder on a host of its own, given the
station's locator for its range check: it reports an aircraft only once it
has earned it (a confirmed address, a position fix seen twice, within
500 km, nothing impossible: shack_sdr README), at most once a second each.

**The aircraft table** is keyed by ICAO address: the decoder's latest
state, its distance and bearing from the station, when it was first and
last heard, and a track. An aircraft not heard for `adsbKeepMinutes`
(default 5) is dropped. Unlike the vessel table it is not kept over a
restart: aircraft move on in minutes, and a five-minute-old map is no map.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone

from ohscore import sdr
from ohscore.countries import distance_bearing, locator_position
from ohscore.decoders import Refused, sessions_text
from ohscore.devices import DeviceError

from ohsradio.i18n import _

log = logging.getLogger("ohsradio.adsb")

SID = "adsb"
CENTRE_HZ = 1_090_000_000.0
MIN_RATE = 2_400_000.0
RSP_RATE = 6_000_000.0
CLIENT_LEASE_S = 30.0
LINGER_S = 0.0            # no linger (ais.py's docstring)
CLIENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_CLIENTS = 32
# The track: a point when an aircraft has moved TRACK_MIN_M or TRACK_MIN_S
# has passed, the last TRACK_POINTS (half an hour of an airliner, a point
# every 10 s at most).
TRACK_POINTS = 240
TRACK_MIN_M = 500.0
TRACK_MIN_S = 10.0
EXPIRE_EVERY_S = 5.0
REMOVED_KEPT = 2000


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def category_text(cat) -> str | None:
    """An emitter category's words (DO-260B Table 2-14), "A3" and so on."""
    return {"A1": _("Light aircraft"), "A2": _("Small aircraft"), "A3": _("Large aircraft"),
            "A4": _("Large aircraft, high vortex"), "A5": _("Heavy aircraft"), "A6": _("High performance aircraft"),
            "A7": _("Rotorcraft"), "B1": _("Glider"), "B2": _("Balloon or airship"), "B3": _("Parachutist"),
            "B4": _("Ultralight or hang glider"), "B6": _("Unmanned aircraft"), "B7": _("Space vehicle"),
            "C1": _("Emergency vehicle on the ground"), "C2": _("Service vehicle on the ground"),
            "C3": _("Obstacle"), "C4": _("Obstacles"), "C5": _("Line obstacle")}.get(cat or "")


def emergency_text(code) -> str | None:
    """The emergency state's words; None for none or not known."""
    return {"general": _("Emergency"), "lifeguard": _("Medical emergency"), "minfuel": _("Minimum fuel"),
            "nordo": _("Radio failure"), "unlawful": _("Unlawful interference"), "downed": _("Aircraft down"),
            "reserved": _("Emergency")}.get(code or "")


# The decoder's field names (shack_sdr's) to the API's.
RENAME = {"gs": "groundSpeed", "vrate": "verticalRate", "vrateSource": "verticalRateSource"}
DROP = ("posT", "firstT")


class AircraftTable:
    """Every aircraft the decoder reports, by ICAO address (module
    docstring). Thread-safe: frames arrive on the supervisor's thread,
    clients read on the server's."""

    def __init__(self):
        self.lock = threading.Lock()
        self.a: dict[str, dict] = {}
        self.tracks: dict[str, deque] = {}
        self.rev = 0
        self.removed: deque = deque(maxlen=REMOVED_KEPT)    # (rev, icao)
        self.station: tuple[float, float] | None = None
        # Set by Radio to flightroutes.FlightRoutes.lookup (flightroutes.py):
        # given a callsign, the route it flies, or None - never a fetch on
        # this thread. None here (a test's bare table) means no routes shown.
        self.route_lookup = None

    def set_station(self, locator: str) -> None:
        pos = locator_position(locator or "")
        if pos == self.station:
            return
        self.station = pos
        with self.lock:
            for v in self.a.values():
                self._range(v)

    def _range(self, v: dict) -> None:
        if self.station is not None and v.get("lat") is not None and v.get("lon") is not None:
            km, brg = distance_bearing(self.station[0], self.station[1], v["lat"], v["lon"])
            v["distanceKm"], v["bearingDeg"] = round(km, 2), round(brg, 1)
        else:
            v["distanceKm"] = v["bearingDeg"] = None

    def heard(self, f: dict, t: float) -> dict | None:
        """One `adsb` frame's fields (the aircraft's whole state as the
        decoder has it) heard at UTC `t`: the aircraft as it now stands."""
        icao = str(f.get("icao") or "")
        if not icao:
            return None
        with self.lock:
            v = self.a.get(icao)
            if v is None:
                v = self.a[icao] = {"icao": icao, "firstHeard": _iso(f.get("firstT") or t)}
            for k, x in f.items():
                if k not in DROP:
                    v[RENAME.get(k, k)] = x
            v["lastHeardTs"] = t
            v["lastHeard"] = _iso(t)
            v["positionAt"] = _iso(f.get("posT"))
            v["categoryText"] = category_text(v.get("category"))
            v["emergencyText"] = emergency_text(v.get("emergency"))
            self._range(v)
            if v.get("lat") is not None and f.get("posT") is not None:
                self._track(v, float(f["posT"]))
            self.rev += 1
            v["rev"] = self.rev
            return dict(v)

    def _track(self, v: dict, t: float) -> None:
        tr = self.tracks.setdefault(v["icao"], deque(maxlen=TRACK_POINTS))
        point = [round(t, 1), v["lat"], v["lon"], v.get("altBaro"), v.get("groundSpeed"), v.get("track")]
        if tr:
            last = tr[-1]
            if t <= last[0]:
                return
            km, _b = distance_bearing(last[1], last[2], v["lat"], v["lon"])
            if km * 1000 < TRACK_MIN_M and t - last[0] < TRACK_MIN_S:
                return
        tr.append(point)

    def expire(self, now: float, keep_s: float) -> list[str]:
        with self.lock:
            gone = [k for k, v in self.a.items() if now - float(v.get("lastHeardTs") or 0) > keep_s]
            for k in gone:
                self.a.pop(k, None)
                self.tracks.pop(k, None)
                self.rev += 1
                self.removed.append((self.rev, k))
        return gone

    def view(self, since: int | None = None) -> dict:
        """As ais.VesselTable.view: everything, or only what changed after
        `since` and what was dropped; nearest first."""
        with self.lock:
            oldest = self.removed[0][0] if len(self.removed) == self.removed.maxlen else 0
            full = since is None or since < oldest or since > self.rev
            items = [dict(v) for v in self.a.values() if full or v.get("rev", 0) > since]
            removed = [] if full else [k for r, k in self.removed if r > since]
            rev = self.rev
        items.sort(key=lambda v: (v.get("distanceKm") is None, v.get("distanceKm") or 0.0, v["icao"]))
        for v in items:
            v["route"] = self.route_lookup(v.get("callsign")) if self.route_lookup else None
        return {"rev": rev, "full": full, "aircraft": items, "removed": removed}

    def aircraft(self, icao: str) -> dict | None:
        with self.lock:
            v = self.a.get(icao)
            if v is None:
                return None
            out = dict(v)
            out["track"] = [{"t": _iso(p[0]), "lat": p[1], "lon": p[2], "altBaro": p[3], "groundSpeed": p[4],
                             "track": p[5]} for p in self.tracks.get(icao, ())]
        out["route"] = self.route_lookup(out.get("callsign")) if self.route_lookup else None
        return out

    def __len__(self) -> int:
        return len(self.a)


def _is_rsp(dev) -> bool:
    from ohscore.devices.sdrsource import SdrplayDevice
    return isinstance(dev, SdrplayDevice) or getattr(dev, "kind", "") == "sdrplay"


class AdsbService:
    """The ADS-B session and the aircraft table (module docstring)."""

    def __init__(self, radio):
        self.radio = radio
        self.table = AircraftTable()
        self.lock = threading.RLock()
        # One start at a time, and never under `lock`: a start may reopen
        # the radio, whose stop joins the supervisor thread that takes
        # `lock` in tick().
        self.start_lock = threading.Lock()
        self.clients: dict[str, float] = {}
        self.state = "idle"
        self.why: str | None = None
        self.started_at: float | None = None
        self.linger_until: float | None = None
        # Set by the server: whether client presence vouches for a client
        # (present in this app with the map in its holds), which then need
        # not renew this lease apart (CLIENT-UI-PLAN 7.2). None: nobody does.
        self.vouch = None
        self.host = None
        self.sid: str | None = None
        self.index = 0
        self.counts = {"messages": 0, "df17": 0, "aircraftSeen": 0}
        self.expired_at = 0.0
        self.restoring: threading.Thread | None = None
        self._published: dict | None = None

    def texts(self) -> dict:
        return {"tune": _("The receiver is listening to ADS-B for the aircraft map: close the map, or stop "
                          "ADS-B, to tune or change mode"),
                "transmit": _("The receiver is listening to ADS-B for the aircraft map: stop ADS-B to transmit"),
                "on_air": _("Not while transmitting: ADS-B takes the receiver to 1090 MHz"),
                "busy": _("ADS-B has the receiver for the aircraft map: stop ADS-B first")}

    # -- the session --------------------------------------------------------
    def join(self, client: str, drop_sessions: bool = False) -> dict:
        """Client `client` has the map open: start ADS-B if it is not
        running, and keep it running for CLIENT_LEASE_S more. Raises
        Refused (code, sentence) when it cannot start. Starting may reopen
        the radio at another rate, which takes a second or two."""
        client = str(client or "")
        if not CLIENT_RE.match(client):
            raise Refused("bad_client", _("The client must name itself: 1-64 letters, digits, '.', '_', ':' or "
                                          "'-'"))
        with self.start_lock:
            with self.lock:
                if client not in self.clients and len(self.clients) >= MAX_CLIENTS:
                    raise Refused("too_many_clients", _("Too many screens have the aircraft map open"))
                running = self.state == "running"
            if not running:
                self._start(drop_sessions)
            with self.lock:
                self.clients[client] = time.monotonic() + CLIENT_LEASE_S
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

    def rate_for(self) -> float | None:
        """The rate this session runs the receiver at (module docstring),
        or None when this radio cannot run fast enough."""
        r = self.radio
        if _is_rsp(r.dev):
            return RSP_RATE
        fs = float(r.geo.fs)
        if fs >= MIN_RATE:
            return fs
        return MIN_RATE if r._faster_rate(MIN_RATE) is not None else None

    def _start(self, drop_sessions: bool) -> None:
        r = self.radio
        m = sdr.load()
        if m is None or not any(e.get("id") == "adsb" for e in m.catalogue()):
            raise Refused("decoder_unavailable", _("ADS-B needs the shack_sdr library with its ADS-B decoder, "
                                                   "which this install does not have"))
        t = self.restoring
        if t is not None:
            # The last session's rate is still being put back: after it.
            t.join(timeout=30.0)
        if not r.running:
            raise Refused("not_running", _("Start the radio to see aircraft: ADS-B needs the receiver"))
        pinning = r.decoders.pinned_by() if r.PINS_SPAN else []
        if pinning and not drop_sessions:
            raise Refused("span_pinned", _("ADS-B takes the receiver to 1090 MHz and stops {sessions}")
                          .format(sessions=sessions_text(pinning)), sessions=pinning)
        # Every other reason first, before the radio is reopened for nothing.
        with r.lock:
            why = r._hold_refusal(CENTRE_HZ, 0.0, self.texts())
        if why is not None:
            raise Refused(*why)
        rate = self.rate_for()
        if rate is None:
            raise Refused("rate_too_low", _("ADS-B needs the receiver to run at {least:g} MS/s or more, and the "
                                            "{device} cannot (it runs at {rate:g} MS/s)").format(
                least=MIN_RATE / 1e6, device=r._kind(), rate=float(r.geo.fs) / 1e6))
        if pinning:
            r.decoders.stop_background()
        r.client_activity("decoder")
        if float(r.geo.fs) != rate:
            log.info("ADS-B: reopening the %s at %g MS/s", r._kind(), rate / 1e6)
            try:
                r.restart_at(rate)
            except DeviceError as e:
                raise Refused("device_error", _("The {device} would not open at {rate:g} MS/s for ADS-B: {error}")
                              .format(device=r._kind(), rate=rate / 1e6, error=e)) from None
        try:
            r.hold_receiver(SID, "adsb", CENTRE_HZ, "ADS-B", MIN_RATE, feed=self._feed, texts=self.texts())
        except Refused:
            self._restore_rate()
            raise
        # Running means listening at 1090 MHz: the receive thread moves the
        # centre on its next block, and a client (or a recording started at
        # once) must not find it still on the old one. So wait until the
        # device itself is there and its samples are from there, then put
        # that in deviceStatus at once rather than at the supervisor's next
        # tick: beta.15's POST answered while deviceStatus still showed the
        # operator's 430 MHz. Seconds at most.
        want = r._dev_freq(CENTRE_HZ, r._conv_at(CENTRE_HZ, rx=True))
        end = time.monotonic() + 10.0
        while time.monotonic() < end and r.running and not (
                r.pending_centre is None and r.centre == CENTRE_HZ
                and getattr(r.dev, "rx_if", want) == want and r._rx_settled()):
            time.sleep(0.01)
        r._status(deviceStatus=r._device_status())
        pos = locator_position(r.st.get("locator") or "")
        params = {"refLat": pos[0], "refLon": pos[1]} if pos is not None else {}
        host = m.Host(threads=1, cpu_max=0.0, ring_s=2.0, max_sessions=1)
        try:
            sid = host.start("adsb", params, input="iq", rate=float(r.geo.fs), pinned=True)
        except Exception:
            host.close()
            r.release_receiver(SID)
            self._restore_rate()
            raise
        with self.lock:
            self.host, self.sid, self.index = host, sid, 0
            self.state, self.why = "running", None
            self.started_at = time.time()
            self.counts = {"messages": 0, "df17": 0, "aircraftSeen": 0}
        log.info("ADS-B started: the receiver at %.3f MHz, %g MS/s", CENTRE_HZ / 1e6, float(r.geo.fs) / 1e6)

    def end(self, why: str = "stopped") -> None:
        """End the session now: the receiver back as it was, and the radio
        back at the operator's rate. `why` as ais.AisService.end."""
        with self.lock:
            host, self.host, self.sid = self.host, None, None
            if host is not None:
                try:
                    host.close()
                except Exception:  # noqa: BLE001 - closing a host that failed is still closing it
                    log.warning("ADS-B: closing its decoder host", exc_info=True)
            was = self.state == "running"
            if was:
                h = self.radio.held
                if h is not None and h.get("session") == SID:
                    self.radio.release_receiver(SID)
                log.info("ADS-B ended (%s)", why)
            self.state, self.why = "idle", why
            self.clients.clear()
            self.linger_until = None
        if why == "radio_stopped":
            # Stopped by the operator: it starts again at their own rate.
            self.radio.rate_override = None
        elif was:
            self._restore_rate()
        self._publish()

    def _restore_rate(self) -> None:
        """The operator's rate back, on a thread of its own: the end may
        come from the supervisor, which reopening the radio joins."""
        r = self.radio
        if r.rate_override is None:
            return

        def restore():
            try:
                if r.running and r.rate_override is not None and (r.held is None or r.held.get("by") != "adsb"):
                    log.info("ADS-B: reopening the %s at the operator's rate", r._kind())
                    r.restart_at(None)
            except Exception:  # noqa: BLE001 - the radio reports its own failure to open
                log.warning("ADS-B: the operator's rate could not be put back", exc_info=True)

        t = threading.Thread(target=restore, name="adsb-restore", daemon=True)
        self.restoring = t
        t.start()

    def _feed(self, raw, settled: bool) -> None:
        """The receive thread, once per block, while ADS-B holds the receiver."""
        host, sid = self.host, self.sid
        if host is None:
            return
        n = len(raw)
        r = self.radio
        if not settled or r.centre is None:
            self.index += n
            return
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
            host, sid = self.host, self.sid
        if host is not None:
            try:
                items = host.poll()
            except Exception:  # noqa: BLE001 - closed between the read and now
                items = []
            for it in items:
                if it.get("session") == sid and it.get("type") == "frame" and it.get("frame") == "adsb":
                    self._frame(it)
            try:
                c = host.status(sid).get("stats") or {}
                self.counts["messages"] = int(c.get("messages", 0))
                self.counts["df17"] = int(c.get("df17", 0))
            except Exception:  # noqa: BLE001
                pass
        t = time.time()
        if t - self.expired_at >= EXPIRE_EVERY_S:
            self.expired_at = t
            keep = float(r.st.get("adsbKeepMinutes", 5)) * 60.0
            for icao in self.table.expire(t, keep):
                r._publish("adsb", {"type": "removed", "icao": icao, "rev": self.table.rev})
        self._publish()

    def _frame(self, it: dict) -> None:
        f = it.get("fields") or {}
        new = str(f.get("icao") or "") not in self.table.a
        v = self.table.heard(f, float(it.get("t") or time.time()))
        if v is None:
            return
        if new:
            self.counts["aircraftSeen"] += 1
        self.radio._publish("adsb", {"type": "aircraft", "rev": v["rev"], "aircraft": v})

    # -- views ---------------------------------------------------------------
    def view(self) -> dict:
        with self.lock:
            now = time.monotonic()
            ends = None
            if self.state == "running" and self.linger_until is not None:
                ends = max(0.0, self.linger_until - now)
            running = self.state == "running"
            fs = float(self.radio.geo.fs) if running and getattr(self.radio, "geo", None) is not None else None
            return {"state": self.state, "why": self.why, "text": self._text(), "clients": len(self.clients),
                    "startedAt": _iso(self.started_at) if running else None,
                    "endsInS": None if ends is None else round(ends, 1), "centreHz": CENTRE_HZ, "rateHz": fs,
                    "leaseS": CLIENT_LEASE_S, "lingerS": LINGER_S, "aircraft": len(self.table),
                    "rev": self.table.rev, **self.counts}

    def _text(self) -> str:
        if self.state == "running":
            return _("Listening to ADS-B on 1090 MHz")
        return {"idle": _("Stopped: nobody had the aircraft map open"),
                "stopped": _("Stopped"),
                "radio_stopped": _("Stopped: the radio stopped"),
                "lost": _("Stopped: the receiver was taken back")}.get(self.why or "", _("Not running"))

    def _publish(self) -> None:
        v = self.view()
        key = {"state": v["state"], "why": v["why"], "clients": v["clients"], "ending": v["endsInS"] is not None}
        if key != self._published:
            self._published = key
            self.radio._status(adsb=v)
            self.radio._publish("adsb", {"type": "session", "session": v})
