"""The store form's HTTP and WebSocket API over one engine (docs/SERVER-API.md).

One process, one Radio, run headless in a container on an OpenHamShack
controller. Everything a person does arrives through the platform's proxy,
which has already signed them in and checked the route's minimum level
(CONTROLLER-CONTRACT 5.2); this server believes the identity headers only
after this app's proxy secret matches (5.3), checks the level again
(defence in depth, and for what a path glob cannot say), and never trusts
a source address. No secret configured is a locked app: every request is
401 proxy_required, which the manifest's health check counts as healthy.

Transmitting, in this order (CONTROLLER-CONTRACT 6.2): the Transmit level;
the engine's own guard (licence and band plan from the station profile
and the shared dataset, ohscore/txguard.py, through Engine.ptt's key-up
check); a broker claim in tx mode on the radio and the broker's on-air
answer; only then the key-up, held under the client's lease (REMOTE-API
7: heartbeat every 1 s, unkeyed after 5 s of silence). Unkeying runs the
other way: RF off, then the broker told. A claim the broker takes back
unkeys at once and stops the radio, then is re-claimed for receive while
the radio is still wanted (a broker restart loses every claim); only a
person's stop or a hand-over ends wanting it.

Automatic transmit in the digital modes (autotx.py, WSJT-X's Enable TX)
keys through the same path, one over at a time, under the arming remote's
lease; anything that ends a transmission here also disarms it.

Recordings (recording.py, shack_rec) are made and kept here, on the data
volume, receive only: api/recordings and the status page's Recordings.

Threads: http.server's one per request, one for the lease, one for the
broker's heartbeat, one for automatic transmit. The engine is thread-safe (ENGINE-API.md).
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import numpy as np

from ..engine import ReceiverHeld, SpanPinned, TxRefused
from ..padactions import PAD_TX_ACTIONS
from ..i18n.text import _
from .. import shacklibs, smeter_cal
# The host module gets its own import line: the source scrub passes the
# word only straight after "import ", never mid-list.
from . import shack
from . import overlay, presence, spectrum, uiv1, ws
from .audio import CHANNELS, MIC_FORMAT
from .autotx import AutoTx, Refused
from .recording import server_recordings
from .timeshift import Gone as TimeshiftGone, Timeshift

log = logging.getLogger("ohscore.server")

LEASE_S = 5.0                  # REMOTE-API 7 TX_REMOTE_LEASE
# Re-claiming a claim the broker lost: first try at once, then doubling to
# a ceiling, unless the broker says how long (retryAfter). The ceiling keeps
# a box whose controller was down for an hour back within 30 s of it.
RECLAIM_FIRST_S = 1.0
RECLAIM_MAX_S = 30.0
# Receive audio with the engine silent (stopped, re-claiming): this much
# real-time silence per wait, so a listener's socket is written and a gone
# client found (get_audio_rx).
IDLE_AUDIO_S = 0.5
REMOTE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
# X-Forwarded-Prefix as the page's <base>: a path, never a host (house rule:
# no absolute URLs), and nothing that could close the attribute.
PREFIX_RE = re.compile(r"^(/[A-Za-z0-9._~%-]+)*$")
FILE_CHUNK = 64 * 1024
FEED_KINDS_DEFAULT = ("state", "toast", "meter", "lock", "events")
SPECTRUM = ("wide", "zoom")
# Settings the station profile owns on the platform (SERVICES.md 2): they
# change on the controller, and reach the engine through the shared store.
PROFILE_KEYS = frozenset({"callsign", "locator", "stationCountry", "licence", "licenceClass", "customLicence",
                          "stationConditions"})
# Settings the store form cannot use or the controller does instead: the
# device's address comes from the broker's claim, there is no sound card.
PLATFORM_KEYS = frozenset({"audioBackend", "audioIn", "audioOut", "audioOut2", "plutoUri", "hl2Address",
                           "soapyArgs", "sdrSerial", "openAipKey"})
# Radio's openAIP key for a local-frequencies refresh: a module setting,
# which only the controller's administrator sees and sets, rather than an
# engine setting api/state would show every viewer (openAipKey is refused
# above for that reason).
OPENAIP_KEY_ENV = "OPENAIP_API_KEY"


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    if hasattr(o, "__fspath__"):
        return os.fspath(o)
    return str(o)


def dumps(obj) -> bytes:
    return json.dumps(obj, default=_json_default, separators=(",", ":")).encode()


def _url_key(k) -> str | None:
    """The URL key beside a path key: "path" -> "url", "logoPath" -> "logoUrl"."""
    if k == "path":
        return "url"
    if isinstance(k, str) and k.endswith("Path") and len(k) > 4:
        return k[:-4] + "Url"
    return None


def with_urls(obj, base: str):
    """`obj` with a URL beside every path the engine hands out for the app's
    own routes ("path": "api/dab/logos/C221" gains "url":
    "<base>api/dab/logos/C221"). The engine never knows where the app is
    served from; the request does (X-Forwarded-Prefix, `_base`), so the URL
    is made here, per request, and is only ever a path (house rule: no
    absolute URLs). Only values naming an `api/` route are touched, so a
    filesystem path can never become a link. The same object comes back
    when there is nothing to add."""
    if isinstance(obj, dict):
        out = None
        for k, v in obj.items():
            nv = with_urls(v, base) if isinstance(v, (dict, list)) else v
            uk = _url_key(k)
            add = uk is not None and isinstance(v, str) and v.startswith("api/") and uk not in obj
            if nv is not v or add:
                if out is None:
                    out = dict(obj)
                out[k] = nv
                if add:
                    out[uk] = base + v
        return obj if out is None else out
    if isinstance(obj, list):
        new = [with_urls(v, base) if isinstance(v, (dict, list)) else v for v in obj]
        return obj if all(a is b for a, b in zip(new, obj)) else new
    return obj


def spectrum_item(kind: str, item) -> dict:
    """(t, start_hz, bin_hz, db) as JSON: the bins as centi-dB in int16,
    base64, about a tenth of the bytes of a JSON list."""
    t, start, bin_hz, db = item
    cdb = np.clip(np.round(np.asarray(db, np.float32) * 100.0), -32768, 32767).astype("<i2")
    out = {"kind": kind, "t": t, "startHz": float(start), "binHz": float(bin_hz), "n": int(cdb.size),
           "cdb": base64.b64encode(cdb.tobytes()).decode()}
    dc = getattr(item, "dc_bins", None)
    if dc is not None:
        # The bins the engine filled in over the receiver's DC spike
        # (inclusive): a client may mask them its own way.
        out["dcBins"] = [int(dc[0]), int(dc[1])]
    return out


class AppInfo:
    """What the server says about the app it serves, and the app's own
    transmit facts (each app knows where its signal goes on air)."""

    def __init__(self, app_id: str, kind: str, name: str, version: str, onair_body, device_for,
                 commit: str = "", screens=None, presence: bool = False):
        self.app_id, self.kind, self.name, self.version, self.commit = app_id, kind, name, version, commit
        # Whether the app hangs its client-scoped holds off the platform's
        # client presence (presence.py; CLIENT-UI-PLAN 7.2-7.4). Radio only
        # so far: NB keeps its feature leases until it is brought over.
        self.presence = presence
        self.onair_body = onair_body        # radio -> {"freqHz", "bandwidthHz", "mode"}
        self.device_for = device_for        # device setting -> broker device name, "" for none
        # The app's ui/1 screens (uiv1.py): an object with descriptor(srv,
        # req), screen(srv, id, params, req) and data(srv, name, req); None
        # serves none (ui/v1 answers 404).
        self.screens = screens


class Server:
    LEASE_S = LEASE_S

    def __init__(self, radio, info: AppInfo, audio, *, secret: str | None = None, broker=None,
                 clock=time.monotonic, wall=time.time, recordings: dict | None = None):
        self.radio = radio
        self.info = info
        self.audio = audio
        self.secret = os.environ.get(shack.PROXY_SECRET_ENV, "") if secret is None else secret
        # Only a test sets this (directly, after construction): a tiny send
        # buffer on a spectrum socket so a client that stops reading stalls
        # the server's write at once, rather than at however many rows the
        # host's autotuned kernel buffer happens to absorb on the day
        # (test_a_stalled_client_gets_the_newest_row_and_a_gap).
        self.test_sndbuf: int | None = None
        self.broker = broker
        self.clock = clock
        self.lock = threading.RLock()
        self.lease: dict | None = None      # {"id", "last", "device"}
        self.tx_error = ""
        self.radio_error = ""
        self.stop_ev = threading.Event()
        self.wanted = True                  # whether the radio should be running (run.py retries)
        # A claim the broker lost while the radio was wanted, being taken
        # back: {"device", "at" (next try, self.clock), "delay"}. While set,
        # the broker loop re-claims and run.py's plain retry stands aside.
        self.reclaim: dict | None = None
        # The engine says why it unkeyed itself (time-out, dead air, a
        # refusal on re-check) only as a toast; the lease reads it from here
        # so txError tells the remote, as REMOTE-API 7 promises.
        self._toasts = radio.subscribe("toast", 32)
        self.httpd: ThreadingHTTPServer | None = None
        self.threads: list[threading.Thread] = []
        # Automatic transmit for the digital modes: off until a remote arms
        # it, and never on after a restart (it lives only here).
        self.digi = AutoTx(self, wall)
        # `recordings` is ServerRecordings' keywords (a test's folder, limits, disk).
        # Without shack_rec (a desktop build run with --server) it is
        # NoRecordings, which refuses rather than stopping the server.
        self.recordings = server_recordings(radio, audio, info, **(recordings or {}))
        # The broadcast station's last minutes (timeshift.py): to listen
        # behind live (api/audio/rx?behind=) and record from the past. Its
        # writer runs with the HTTP server (serve); NB never has a station.
        limits = getattr(getattr(self.recordings, "rec", None), "limits", None)
        self.timeshift = Timeshift(radio, audio, Path(radio.data_dir) / "timeshift",
                                   **({"floor_bytes": limits.floor_bytes} if limits is not None else {}))
        self.recordings.timeshift = self.timeshift
        # The network for a local-frequencies refresh (Radio): None is the
        # real one; a test gives a reader of fixture files.
        self.localfreq_fetch = None
        # Radio's band scan (ohsradio/bandscan.py) runs only while nobody is
        # using the radio: it hears of the listeners here, and of what only
        # the server knows makes the radio busy. A listener arriving is
        # someone using it (Engine.client_activity: the scan gives way).
        scan = getattr(radio, "bandscan", None)
        if scan is not None:
            scan.listeners = audio.listeners
            scan.probes.append(self._scan_busy)
        audio.on_listen = lambda: radio.client_activity("listener")
        # spectrum/1 and overlay/1 (spectrum.py, overlay.py): the client
        # count and per-stream levels every socket shares, and the
        # overlay's sources.
        self.spectrum = spectrum.Shared()
        self.overlay = overlay.Overlay(radio)
        # Client presence (presence.py; CLIENT-UI-PLAN 7.2-7.4): who made
        # each client-scoped hold and each client's open streams, always
        # kept (cheap); `presence` is the platform's feed, set by run.py
        # only for an app that asks for it on a controller that lists the
        # service. Without it nothing below ever ends anything.
        self.holds = presence.Holds()
        self.presence: presence.PresenceWatch | None = None
        # The radio given back to the broker because nobody was using it
        # (park): the engine stopped and the claim released, still wanted,
        # so the next client to come takes it again (wake). run.py's retry
        # stands aside meanwhile, as it does for a re-claim.
        self.parked = False
        # A client's leaving freed something: give the radio back once
        # nothing else holds it. Kept only while what stops it is
        # transmitting (7.4: retried after), or a nightly scan woke it.
        self.park_pending = False
        self._gone_later: list[tuple[str, str]] = []
        self._gone_lock = threading.Lock()
        self.events_sockets = 0
        # A client present in this app with "ais" (or "adsb") in its holds
        # is renewing that map's lease (7.2): it need not renew it apart.
        for name in ("ais", "adsb"):
            svc = getattr(radio, name, None)
            if svc is not None:
                svc.vouch = (lambda client, hold=name: self.presence is not None
                             and self.presence.renews(client, hold))

    def _scan_busy(self) -> str:
        """The band scan's reasons to wait that only the server knows."""
        if self.digi.remote is not None:
            return _("Automatic transmit is armed")
        if self.recordings.summary().get("active"):
            return _("An audio recording is being made")
        return ""

    # ---------------------------------------------------------- lifecycle
    def device(self) -> str:
        return self.info.device_for(self.radio.st.get("device", "sim"))

    def start_radio(self, requester: str = "auto", acting: str = "-", reclaim: bool = False) -> str:
        """Claim the radio for receive (when the broker lends it) and start
        the engine. '' or why not; never transmits. `reclaim` re-takes a
        claim the broker lost when it restarted (CONTROLLER-CONTRACT 7.2)."""
        dev = self.device()
        if self.broker is not None and dev:
            why = self.broker.claim(dev, "rx", requester=requester, acting=acting,
                                    reason=_("Receive with {app}").format(app=self.info.name), reclaim=reclaim)
            if why:
                self.radio_error = why
                return why
            self._apply_access(dev)
        try:
            self.radio.start()
        except Exception as e:  # noqa: BLE001  a radio that will not open is a status, not a crash
            self.radio_error = str(e)
            if self.broker is not None and dev:
                self.broker.release(dev)
            return self.radio_error
        self.radio_error = ""
        self.reclaim = None
        return ""

    def _apply_access(self, dev: str) -> None:
        """The broker says where the radio is: a network address, or for a
        USB receiver which one."""
        with self.broker.lock:
            access = (self.broker.claims.get(dev) or {}).get("access") or {}
        if access.get("reach") == "usb":
            self._apply_usb_access(dev, access)
            return
        addr = access.get("address") if access.get("reach") == "network" else None
        if not addr:
            return
        # The device's class is its broker name's stem (pluto-1 is a pluto).
        key = {"pluto": "plutoUri", "libresdr": "plutoUri", "hl2": "hl2Address"}.get(dev.rsplit("-", 1)[0], "")
        if key:
            val = f"ip:{addr}" if key == "plutoUri" else addr
            try:
                self.radio.set(authorise=True, **{key: val})
            except ValueError as e:
                log.warning("broker address not taken: %s", e)

    def _apply_usb_access(self, dev: str, access: dict) -> None:
        """A USB receiver the broker lends is reached through SoapySDR, so
        the claim decides soapyArgs as an address decides plutoUri: a class
        the broker knows names its driver, and a serial the station gave
        the device picks that one of two alike. soapyArgs is a platform key
        (refused over api/set) for this reason. Only the SDRplay family so
        far, the one receiver the Radio image carries a SoapySDR module for
        (store/radio/Containerfile).

        Any other key=value the configured soapyArgs carries is kept: it is
        how a driver's own settings reach the device when it opens - for an
        RSP, rfgain_sel (its LNA state; ohs-box's RSPdx on an 80 m dipole
        wants 4, or the IF AGC runs out of range in the evening)."""
        serial = str(access.get("serial") or "").strip()
        if not re.match(r"^[A-Za-z0-9]{1,32}$", serial):
            serial = ""
        if self.radio.st.get("device") in ("rtlsdr", "sdrplay"):
            # shack_sdr's own receivers (ohscore/devices/sdrsource.py): the
            # claim's serial picks the one the broker lent, as soapyArgs'
            # serial= does below; none (a dongle without one) is the first.
            try:
                self.radio.set(authorise=True, sdrSerial=serial)
            except ValueError as e:
                log.warning("broker device not taken: %s", e)
            return
        driver = {"sdrplay": "sdrplay"}.get(dev.rsplit("-", 1)[0], "")
        if not driver:
            return
        args = [f"driver={driver}"]
        if serial:
            args.append(f"serial={serial}")
        for part in str(self.radio.st.get("soapyArgs") or "").split(","):
            k, _eq, v = part.strip().partition("=")
            if k not in ("driver", "serial") and re.match(r"^[A-Za-z0-9_.-]{1,32}=[A-Za-z0-9_.-]{1,32}$",
                                                          f"{k}={v}"):
                args.append(f"{k}={v}")
        args = ",".join(args)
        try:
            self.radio.set(authorise=True, soapyArgs=args)
        except ValueError as e:
            log.warning("broker device not taken: %s", e)

    def stop_radio(self, why: str = "") -> None:
        self.digi.disarm(why or _("The radio stopped"))
        self.end_lease(why)
        self.radio.stop()
        self.parked = False
        self._give_back()

    def _give_back(self) -> None:
        """Release the broker's claim on the radio, if this app has one:
        api/stop's last step, and the park's."""
        dev = self.device()
        if self.broker is not None and dev:
            self.broker.release(dev)

    # ---------------------------------------------------------- presence
    # CLIENT-UI-PLAN 7.3: when a client goes (goodbye at once, otherwise
    # its 30 s lease), its streams close; a client-scoped hold it was the
    # last client of ends at once (no linger, Brian 28/10/2026), the
    # receiver back to its prior dial and mode; and when the radio is then
    # held for nothing, the broker's claim is given back so another app, a
    # desktop or a scan can have it. Station-scoped work - saved background
    # decoder sessions, the CW skimmer, recordings, the nightly scan - is
    # never ended, and keeps the radio. Transmit is never touched (7.4).
    def client_gone(self, client: str, why: str) -> None:
        """The platform says `client` has gone (presence.PresenceWatch's
        thread). While the radio is on the air nothing is released (7.4);
        it is done once it is not (_presence_loop)."""
        with self._gone_lock:
            if self.radio.state().get("keyed"):
                self._gone_later.append((client, why))
                return
            closed = self.holds.end_streams(client)
            ended = []
            d = self.radio.decoders
            for kind, sid in self.holds.leave(client):
                if kind == "held":
                    if d.stop(sid):
                        ended.append(f"decoder session {sid}")
                elif kind == "listen" and d.listening == sid:
                    try:
                        d.listen(sid, False)
                        ended.append(f"listening to {sid}")
                    except Exception:  # noqa: BLE001 - a session gone since is not listened to
                        pass
            for name in ("ais", "adsb"):
                svc = getattr(self.radio, name, None)
                if svc is None:
                    continue
                with svc.lock:
                    had = client in svc.clients
                if not had:
                    continue
                svc.leave(client)
                with svc.lock:
                    last = svc.state == "running" and not svc.clients
                if last:
                    svc.end("idle")
                    ended.append(name)
                    # ADS-B reopens the radio at the operator's rate on a
                    # thread of its own: done before the park looks, or the
                    # reopen could follow the claim's release.
                    t = getattr(svc, "restoring", None)
                    if t is not None:
                        t.join(15.0)
            if closed or ended:
                log.info("presence: %s gone (%s): %d stream(s) closed%s", client, why, closed,
                         (", ended " + ", ".join(ended)) if ended else "")
                self.park_pending = True
        self._maybe_park()

    def client_arrived(self, client: str) -> None:
        """A client has come to this app: the radio is wanted again."""
        self.wake(f"client {client}")

    def wake(self, why: str) -> None:
        """Take back a radio the park gave the broker: someone wants it."""
        with self._gone_lock:
            if not self.parked:
                return
            self.parked = False
            self.park_pending = False
        log.info("presence: taking the radio back (%s)", why)
        err = self.start_radio()
        if err:
            log.info("presence: the radio could not be taken back: %s", err)

    def idle_reason(self) -> str:
        """Why the radio is still in use ('' when nothing holds it): no
        client-scoped hold left, no station-scoped hold, nothing on the
        air. In the store form nobody operates the radio but through a
        client, so a client's open stream or socket is the operator."""
        r = self.radio
        st = r.state()
        if st.get("keyed") or self.lease is not None or self.digi.remote is not None:
            return "transmit"
        if r.held is not None:
            return "receiver held"
        if r.decoders.fixed:
            return "decoder sessions"
        if st.get("cwSkim"):
            return "CW skimmer"
        if getattr(r, "rec", None) is not None or getattr(r, "play", None) is not None \
                or self.recordings.summary().get("active"):
            return "recording"
        if self.audio.listeners() or self.spectrum.clients or self.events_sockets:
            return "a client's stream"
        for name in ("ais", "adsb"):
            svc = getattr(r, name, None)
            t = getattr(svc, "restoring", None)
            if svc is not None and (svc.state == "running" or (t is not None and t.is_alive())):
                return name
        scan = getattr(r, "bandscan", None)
        if scan is not None:
            if scan.thread is not None and scan.thread.is_alive():
                return "band scan"
            if self._scan_due(scan):
                return "band scan due"
        return ""

    @staticmethod
    def _scan_due(scan) -> bool:
        """Whether the nightly scan (station-scoped) is due now."""
        now = scan.clock()
        try:
            return any((t := scan.next_due(b, now)) is not None and t <= now for b in ("fm", "dab"))
        except Exception:  # noqa: BLE001 - a scanner that cannot say is never woken for
            return False

    def _maybe_park(self) -> None:
        """Give the radio back to the broker if a client's leaving left it
        held for nothing. Only after a leaving (park_pending): a radio
        nobody with presence ever used keeps today's behaviour. Kept
        pending only while it is on the air or a scan runs (retried); any
        other use - an older client listening, a background decoder - ends
        the wish, and the next leaving asks again."""
        with self._gone_lock:
            if not self.park_pending or self.parked:
                return
            dev = self.device()
            if self.broker is None or not dev or not self.wanted or not self.radio.state().get("running"):
                self.park_pending = False
                return
            why = self.idle_reason()
            if why:
                if why not in ("transmit", "band scan", "band scan due"):
                    self.park_pending = False
                return
            self.park_pending = False
            self.parked = True
            # Only the engine stopped and the claim released: not api/stop's
            # disarm and end of the transmit lease, which idle_reason has
            # just said are not there to end. The engine must stop before
            # the claim goes: another app may open the radio the moment the
            # broker lends it.
            self.radio.stop()
            self._give_back()
        log.info("presence: nobody is using %s: given back to the station", dev)

    def _presence_loop(self) -> None:
        while not self.stop_ev.wait(1.0):
            try:
                if self.presence is not None:
                    self.presence.tick()
                if self._gone_later and not self.radio.state().get("keyed"):
                    later, self._gone_later = self._gone_later, []
                    for client, why in later:
                        self.client_gone(client, why)
                if self.parked:
                    scan = getattr(self.radio, "bandscan", None)
                    if scan is not None and self._scan_due(scan):
                        # Station-scoped: the nightly scan runs on a parked
                        # radio as on one nobody is using, then it parks again.
                        self.wake("the nightly band scan")
                        self.park_pending = True
                self._maybe_park()
            except Exception:  # noqa: BLE001  the loop must outlive one bad pass
                log.exception("presence")

    def serve(self, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
        server = self

        class Handler(_Handler):
            srv = server

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        loops = [("lease", self._lease_loop), ("broker", self._broker_loop),
                 ("digi", self._digi_loop), ("timeshift", lambda: self.timeshift.run(self.stop_ev)),
                 ("http", self.httpd.serve_forever)]
        if self.presence is not None:
            watch = self.presence
            loops += [("presence", lambda: watch.run(self.stop_ev)), ("presence-tick", self._presence_loop)]
        for name, fn in loops:
            t = threading.Thread(target=fn, name=f"server-{name}", daemon=True)
            t.start()
            self.threads.append(t)
        return self.httpd

    def shutdown(self) -> None:
        # First, before the HTTP server, the recordings and the radio are
        # wound down: SIGTERM from a container stop comes with a grace
        # period, and the operator's dial must be on disk inside it
        # (Engine.save_now; stop_radio saves again at its end).
        self.radio.save_now()
        self.stop_ev.set()
        if self.presence is not None:
            self.presence.stop()
        self.recordings.stop()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.stop_radio(_("The app is stopping"))

    def pad(self):
        if getattr(self, "_pad", None) is None:
            self._pad = self.radio.pad_actions()
        return self._pad

    # ---------------------------------------------------------- status
    def status(self) -> dict:
        st = self.radio.state()
        with self.lock:
            lease = self.lease
            remote = None if lease is None else {
                "id": lease["id"], "leaseSeconds": LEASE_S,
                "secondsLeft": max(0, round(LEASE_S - (self.clock() - lease["last"])))}
        return {"app": self.info.app_id, "kind": self.info.kind, "name": self.info.name,
                "version": self.info.version, "commit": self.info.commit,
                "running": bool(st.get("running")), "onAir": bool(st.get("keyed")),
                "txError": self.tx_error, "txBlocked": st.get("txBlocked", ""),
                # tx.remote's presence says this box has the lease (GUIDE 2:
                # clients refuse to transmit through one without it).
                "tx": {"remote": remote, "leaseSeconds": LEASE_S},
                "autoTx": self.digi.view(),
                "radioError": self.radio_error or st.get("error", ""),
                # True while a claim the broker lost is being taken back:
                # radioError is then a passing state, not a fault.
                "reconnecting": self.reclaim is not None,
                # Client presence (SERVER-API "Client presence"): whether the
                # controller's service is followed, who is here, and
                # `released` while the radio is given back to the station
                # because nobody was using it. Absent without the service.
                **({"presence": {**self.presence.view(), "released": self.parked}}
                   if self.presence is not None else {}),
                # Radio's map sessions (docs/SERVER-API.md "AIS", "ADS-B")
                # and its DMR ID list ("DMR") and what the dial is on ("The
                # dial label"), as api/state has them; absent in an app with
                # none (NB).
                **{k: st[k] for k in ("ais", "adsb", "dmrIds", "dialLabel") if k in st},
                "device": st.get("device"), "mode": st.get("mode"), "vfo": st.get("vfo"),
                "txDial": st.get("txDial"), "simulator": bool(st.get("simWhy")),
                "broker": self.broker.view() if self.broker is not None else None,
                # What api/audio/rx sends a listener asking nothing (mono),
                # whether the mode is making stereo now, and the microphone's
                # format for api/audio/tx.
                "audio": {**self.audio.rx_format(1), "stereo": self.radio.audio_channels() == 2,
                          "listeners": self.audio.listeners(), "tx": MIC_FORMAT},
                "station": self.radio.state().get("station"),
                "sharedLog": self.shared_log(),
                # What can be recorded and what is (api/recordings has the rest).
                "recordings": self.recordings.summary(),
                # What the timeshift holds (timeshift.py; SERVER-API "Timeshift").
                "timeshift": self.timeshift.status(),
                # Whether to show a Decoders view: no scan here (api/decoders).
                "decoders": st.get("decoders") or self.radio.decoders.status(),
                # The decoder session holding the receiver ({}: the operator
                # has it), and on a controller what host libraries it lends.
                "rxOwner": st.get("rxOwner") or {},
                # What the receiver covers, and whether background decoder
                # sessions pin it (Radio; {} in QO-100 NB).
                "span": st.get("span") or {},
                # The gain a broadcast station plays with in place of the
                # operator's (Radio; {} while none plays, and in NB).
                "broadcastGain": st.get("broadcastGain") or {},
                # The RSP's notch filters and why each is in or out (Radio;
                # {} for any other radio, and in NB).
                "notches": st.get("notches") or {},
                "hostLibs": st.get("hostLibs") or {}}

    def shared_log(self) -> dict:
        try:
            s = self.radio.station
            info = s.pairing_info() or {}
            return {"contacts": s.logbook.count(), "paired": bool(info.get("controllerId")),
                    "sync": s.sync.status()["state"]}
        except Exception as e:  # noqa: BLE001  the status must answer whatever the store does
            return {"error": str(e)}

    # ---------------------------------------------------------- transmit
    def key(self, remote: str, acting: str, start=None, digital: bool = False) -> str:
        """Key under `remote`'s lease: PTT, or `start` (automatic transmit's
        send of one over, `digital`: the broker is told, so it can admit a
        TV allowed digital transmit and nothing else). Sets tx_error, and
        leaves the radio unkeyed, on any refusal; answers it ('' when keyed)."""
        with self.lock:
            self.tx_error = ""
            if self.lease is not None and self.lease["id"] != remote and self.radio.state().get("keyed"):
                self.tx_error = _("Another remote is transmitting")
                return self.tx_error
            if self.digi.remote not in (None, remote):
                self.tx_error = _("Automatic transmit is armed by another remote")
                return self.tx_error
            # A receiver (an SDRplay through SoapySDR) is refused here, before
            # the broker is asked: the engine would refuse too, but only
            # after the broker had been told this app was on the air.
            st = self.radio.state()
            if st.get("running") and not st.get("canTx"):
                self.tx_error = _("This radio can only receive")
                return self.tx_error
            dev = self.device()
            if self.broker is not None and dev:
                why = self.broker.claim(dev, "tx", requester="person", acting=acting,
                                        reason=_("Transmit with {app}").format(app=self.info.name))
                if not why:
                    why = self.broker.on_air(dev, self.info.onair_body(self.radio), acting, digital=digital)
                if why:
                    self.tx_error = why
                    self._back_to_rx(dev)
                    return self.tx_error
            self._toasts.drain()
            try:
                (start or (lambda: self.radio.ptt(True)))()
            except (TxRefused, ValueError) as e:
                self.tx_error = str(e)
                if self.broker is not None and dev:
                    self.broker.off_air(dev)
                    self._back_to_rx(dev)
                return self.tx_error
            self.lease = {"id": remote, "last": self.clock(), "device": dev}
            return ""

    def _back_to_rx(self, dev: str) -> None:
        if self.broker is not None and dev and self.broker.held(dev, "tx"):
            self.broker.set_mode(dev, "rx")

    def unkey(self, why: str = "") -> None:
        """PTT off or halt: also the end of automatic transmit (any unkey
        ends the lease, GUIDE 2, and the arm is held under it)."""
        self.digi.disarm(why or _("Transmit switched off"))
        self.end_lease(why)

    def halt_if_keyed(self, why: str) -> None:
        if self.radio.state().get("keyed") or self.lease is not None:
            self.end_lease(why)

    def end_lease(self, why: str = "") -> None:
        """RF off first, then the broker told; the lease ends."""
        with self.lock:
            lease, self.lease = self.lease, None
            keyed = bool(self.radio.state().get("keyed"))
            if keyed:
                self.radio.halt() if why else self.radio.ptt(False)
            if why:
                self.tx_error = why
            dev = lease["device"] if lease else self.device()
        if self.broker is not None and dev and (keyed or lease):
            end = self.clock() + 1.5          # a normal end drains at most 1 s (ENGINE-API safety 4)
            while self.radio.state().get("keyed") and self.clock() < end:
                time.sleep(0.02)
            if self.radio.state().get("keyed"):
                self.radio.halt()
            self.broker.off_air(dev)
            self._back_to_rx(dev)

    def heartbeat(self, remote: str) -> tuple[int, dict]:
        with self.lock:
            keyed = bool(self.radio.state().get("keyed"))
            if self.digi.remote == remote:
                # The arm is a lease of its own, between overs as well as
                # during them: a remote that goes quiet disarms (autotx.py).
                self.digi.last = self.clock()
                if self.lease is not None and self.lease["id"] == remote:
                    self.lease["last"] = self.clock()
                    if keyed:
                        self.radio.heartbeat()
                return 200, {"ok": True, "armed": True, "onAir": keyed,
                             "remote": {"id": remote, "secondsLeft": LEASE_S, "leaseSeconds": LEASE_S}}
            if self.lease is None or not keyed:
                return 409, {"error": _("not transmitting under a remote lease"), "code": "not_lease_holder",
                             "onAir": keyed, "txError": self.tx_error}
            if self.lease["id"] != remote:
                return 409, {"error": _("transmit is held by another remote"), "code": "not_lease_holder",
                             "onAir": True, "txError": ""}
            self.lease["last"] = self.clock()
            self.radio.heartbeat()
            return 200, {"ok": True, "remote": {"id": remote, "secondsLeft": LEASE_S, "leaseSeconds": LEASE_S}}

    def _lease_loop(self) -> None:
        while not self.stop_ev.wait(0.25):
            with self.lock:
                lease = self.lease
                keyed = bool(self.radio.state().get("keyed"))
            if lease is None:
                continue
            if not keyed:
                # Unkeyed elsewhere (time-out, dead air, a refusal on
                # re-check): the lease ends, the broker is told, and the
                # engine's reason becomes txError.
                why = next((t["text"] for t in reversed(self._toasts.drain())
                            if t.get("level") in ("warn", "error")), "")
                self.end_lease("")
                if why:
                    self.tx_error = why
                continue
            if self.clock() - lease["last"] > LEASE_S:
                why = _("Transmit stopped: remote controller lost (no word from {id} for {s:.0f} s)").format(
                    id=lease["id"], s=LEASE_S)
                self.digi.disarm(why)
                self.end_lease(why)
            else:
                self.radio.heartbeat()

    def _digi_loop(self) -> None:
        while not self.stop_ev.wait(0.1):
            try:
                self.digi.tick()
            except Exception:  # noqa: BLE001  the loop must outlive one bad pass; the safe way is off
                log.exception("automatic transmit")
                if self.digi.disarm(_("Automatic transmit stopped: an internal error")):
                    self.halt_if_keyed(_("Automatic transmit stopped: an internal error"))

    def _broker_loop(self) -> None:
        while not self.stop_ev.wait(0.5):
            if self.broker is None:
                continue
            try:
                lost, asked = self.broker.beat()
            except Exception:  # noqa: BLE001  the loop must outlive one bad pass
                log.exception("broker heartbeat")
                continue
            for dev, why in lost:
                if dev == self.device():
                    self._lost_claim(dev, why)
            self._reclaim_step()
            for dev, _req in asked:
                if dev == self.device() and not self.radio.state().get("keyed"):
                    self.wanted = False
                    self.stop_radio("")
                    self.radio_error = _("The radio was handed to another app")

    def _lost_claim(self, dev: str, why: str) -> None:
        """The broker no longer has our claim (a heartbeat answered 404/410,
        or the controller was silent for longer than the lease). RF off and
        the engine stopped at once, whatever happens next: the radio is not
        ours to use. But a lost claim is not a hand-over. The usual cause is
        the broker restarting (a platform update restarts the controller,
        and its claims live in memory), and until 10/10 this set wanted =
        False, so NB sat stopped for hours after an update while WB and Flex,
        which re-claim, came back. A person's stop and a hand-over
        (release_request, or releaseRequested on a heartbeat) are what end
        wanting the radio; this only re-claims it."""
        with self.lock:
            self.lease = None
        self.digi.disarm(why)
        keyed = bool(self.radio.state().get("keyed"))
        self.radio.halt()
        self.radio.stop()
        log.warning("%s", why)
        if keyed and self.tx_error == "":
            self.tx_error = why
        if not self.wanted:
            self.radio_error = why
            return
        self.reclaim = {"device": dev, "at": self.clock(), "delay": RECLAIM_FIRST_S}
        self.radio_error = _("Reconnecting to the station…")

    def _reclaim_step(self) -> None:
        """One try at re-taking a lost claim, when one is due. Backs off
        from RECLAIM_FIRST_S to RECLAIM_MAX_S, or waits the broker's own
        retryAfter (503 broker_restarting during its 15 s grace). Always in
        receive: a transmission the loss ended is never resumed by itself."""
        r = self.reclaim
        if r is None:
            return
        if not self.wanted or r["device"] != self.device() or self.radio.state().get("running"):
            # A person stopped it, it was handed over, they picked another
            # device, or a person's start got there first.
            self.reclaim = None
            return
        if self.clock() < r["at"]:
            return
        why = self.start_radio(reclaim=True)
        if not why:
            log.info("re-claimed %s", r["device"])
            return
        refused = self.broker.refused
        if refused is None or refused["code"] in ("device_held", "device_on_air", "queued"):
            # The claim was granted and the radio itself would not open, or
            # another app holds the radio now: no longer a reconnection.
            # Still wanted, so run.py's retry carries on as it does at
            # start-up, and radioError says what is wrong.
            self.reclaim = None
            return
        wait = refused["retryAfter"] if refused["retryAfter"] else r["delay"]
        r["delay"] = min(r["delay"] * 2, RECLAIM_MAX_S)
        r["at"] = self.clock() + max(wait, 0.5)
        log.info("re-claim of %s: %s; next try in %.0f s", r["device"], why, wait)
        self.radio_error = _("Reconnecting to the station…")

    def release_request(self, body: dict) -> tuple[int, dict]:
        """The broker asks for the radio back (CONTROLLER-CONTRACT 7.5)."""
        if self.radio.state().get("keyed"):
            if body.get("stop"):
                self.unkey(_("Transmit stopped by the controller"))
            else:
                return 409, {"onAir": True}
        self.digi.disarm(_("The radio was handed to another app"))
        self.wanted = False
        self.stop_radio("")
        self.radio_error = _("The radio was handed to another app")
        return 202, {"released": True}


# ---------------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    srv: Server = None             # set per server
    protocol_version = "HTTP/1.1"
    server_version = "OpenHamShack"

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def handle(self):
        # ThreadingHTTPServer runs each connection on a thread of its own,
        # and the station store opens a SQLite connection per thread that
        # it never frees by itself: give it back when this connection's
        # thread is done, or every polled /api/status costs two fds.
        try:
            super().handle()
        finally:
            self.srv.radio.release_station_thread()

    # ---------------------------------------------------------- plumbing
    def _send(self, status: int, body, ctype: str = "application/json", extra: dict | None = None) -> None:
        raw = body if isinstance(body, bytes) else dumps(with_urls(body, self._base()))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        if "Cache-Control" not in (extra or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, text: str, code: str, **more) -> None:
        self._send(status, {"error": text, "code": code, **more})

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 1 << 20:
            raise ValueError(_("The request is too large"))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ValueError(_("The request is not JSON")) from None
        if not isinstance(data, dict):
            raise ValueError(_("The request must be a JSON object"))
        return data

    def _who(self) -> dict | None:
        return shack.shack_identity(self.headers.get, self.srv.secret)

    def _client(self, value) -> str | None:
        """The client id a request names (presence's `client`, the same id
        as the transmit lease's `remote` and AIS's `client`), or None when
        it names none - an older client, which presence never judges.
        Raises ValueError (400) for one that is not an id."""
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not REMOTE_RE.match(value):
            raise ValueError(_("The client must name itself: 1-64 letters, digits, '.', '_', ':' or '-'"))
        return value

    def _need(self, who: dict, level: str) -> bool:
        if shack.level_at_least(who["level"], level):
            return True
        names = {"view": _("View"), "control": _("Control"), "transmit": _("Transmit")}
        self._error(403, _("This needs the {needs} level; your level for {app} is {level}.").format(
            needs=names.get(level, level), app=self.srv.info.name, level=names.get(who["level"], who["level"])),
            "level_too_low", level=who["level"], needs=level)
        return False

    # ---------------------------------------------------------- routing
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")

    def do_PUT(self):
        self._route("PUT")

    def _route(self, method: str) -> None:
        u = urlsplit(self.path)
        path, query = u.path.rstrip("/") or "/", parse_qs(u.query)
        who = self._who()
        if who is None:
            self._error(401, _("This app answers only through the OpenHamShack controller."), "proxy_required")
            return
        if who["level"] == "none":
            # The broker's release request and the busy gate are the
            # platform itself, and reach only their own two routes.
            if path == "/api/shack/release" and method == "POST":
                status, ans = self.srv.release_request(self._safe_body() or {})
                self._send(status, ans)
            elif path == "/api/shack/busy":
                self._send(200, self._busy())
            else:
                self._error(403, _("This needs the View level."), "level_too_low", level="none", needs="view")
            return
        try:
            handler = ROUTES.get((method, path))
            if handler is None:
                handler = next(((need, fn) for (m, prefix), (need, fn) in PREFIX_ROUTES.items()
                                if m == method and path.startswith(prefix) and len(path) > len(prefix)), None)
            if handler is None:
                self._error(404, _("There is nothing at {path}").format(path=path), "not_found")
                return
            need, fn = handler
            # Enable TX's heartbeat also admits a TV allowed digital
            # transmit (CONTRACT 5.5); post_heartbeat holds it to the arm.
            digital = (method, path) in DIGITAL_ROUTES and who["transmit"] == "digital"
            if not digital and not self._need(who, need):
                return
            if self.srv.parked and ((method != "GET" and path not in NO_WAKE) or path in WAKE_GETS):
                # Given back because nobody was using it: whoever asks for
                # something now - an older client with no presence too -
                # takes it again first, a second or two.
                self.srv.wake(f"{method} {path}")
            fn(self, who, query)
        except SpanPinned as e:
            # Any route that tunes (api/set, api/recall, ...) out
            # of the span background decoders pin: not a bad request, and
            # the client is told what it would stop (SERVER-API "The pinned
            # span"). Only api/set takes dropSessions.
            self._error(409, str(e), e.code, sessions=e.sessions, span=self.srv.radio.state().get("span") or {})
        except ValueError as e:
            self._error(400, str(e), "bad_request")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _safe_body(self):
        try:
            return self._body()
        except ValueError:
            return None

    def _busy(self) -> dict:
        keyed = bool(self.srv.radio.state().get("keyed"))
        return {"busy": keyed, "why": _("{app} is transmitting").format(app=self.srv.info.name) if keyed else ""}

    # ---------------------------------------------------------- pages
    def _base(self) -> str:
        """The path this app is served under, from X-Forwarded-Prefix (the
        controller strips it before the request arrives), ending in "/".
        Only ever a path: links stay relative to it, never absolute."""
        prefix = (self.headers.get("X-Forwarded-Prefix") or "").rstrip("/")
        return (prefix if PREFIX_RE.match(prefix) else "") + "/"

    def page(self, who, q):
        """The status page at the base path: the app is a server for
        OpenHamShack Remote (D8), and a person who opens it in a browser
        sees what it is and how it is, and its recordings: record, play,
        download and delete them (Brian, 12/10/2026). Nothing is fetched
        from anywhere else; the one script only posts to this app's own
        api/recordings and reloads."""
        s = self.srv.status()
        rows = [(_("Radio"), s["device"] or ""), (_("Running"), _("yes") if s["running"] else _("no")),
                (_("On the air"), _("yes") if s["onAir"] else _("no")),
                (_("Dial"), f"{(s['vfo'] or 0) / 1e6:.6f} MHz"), (_("Mode"), str(s["mode"] or "").upper()),
                (_("Problem"), s["radioError"] or s["txError"] or "-")]
        body = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
        title = html.escape(s["name"])
        doc = (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width'>"
               f"<base href='{html.escape(self._base(), quote=True)}'>"
               f"<title>{title}</title><style>body{{font:15px system-ui,sans-serif;margin:24px;color:#111;"
               f"background:#fff}}th{{text-align:left;padding:4px 16px 4px 0}}"
               f"td{{padding:4px 12px 4px 0;vertical-align:middle}}button{{font:inherit;margin:2px 6px 2px 0}}"
               f".rec td,.rec th{{border-top:1px solid #8884}}.warn{{color:#a40}}audio{{height:32px;max-width:260px}}"
               f"@media(prefers-color-scheme:dark)"
               f"{{body{{background:#111;color:#eee}}a{{color:#8bf}}.warn{{color:#f96}}}}</style><h1>{title}</h1><p>"
               + html.escape(_("Use OpenHamShack Remote to operate this app. This page shows how it is."))
               + "</p>" + self._hostlibs_html(s) + f"<table>{body}</table>" + self._recordings_html(s)
               + f"<p>{html.escape(s['version'])}</p></html>")
        self._send(200, doc.encode(), "text/html; charset=utf-8")

    @staticmethod
    def _hostlibs_html(s: dict) -> str:
        """A controller too old for host libraries, said where an
        administrator opening this page will see it first."""
        why = (s.get("hostLibs") or {}).get("why")
        return f"<p class=warn>{html.escape(why)}</p>" if why else ""

    def _recordings_html(self, s: dict) -> str:
        from .. import sigmf
        e = html.escape
        rec = self.srv.recordings
        st = rec.listing()
        if st.get("unavailable"):
            return f"<h2>{e(_('Recordings'))}</h2><p class=warn>{e(st['unavailable'])}</p>"
        active = {a["kind"]: a for a in st["active"]}
        u = st["usage"]

        def mb(n):
            return e(sigmf.size_text(float(n or 0)))
        parts = [f"<h2>{e(_('Recordings'))}</h2><p id=recnow>"]
        for kind, a in active.items():
            # The numbers are spans the script below keeps current, so a
            # recording in progress counts up without reloading the page
            # (which would stop anything being played from the list).
            parts.append(e(_("Recording {kind}: {seconds} s, {size}.")).format(
                kind=e(_("audio") if kind == "audio" else _("IQ")),
                seconds=f"<span id=s-{kind}>{a['seconds']:.0f}</span>",
                size=f"<span id=z-{kind}>{e(sigmf.size_text(a['bytes']))}</span>") + " ")
        parts.append("</p><p>")
        for kind, label in (("audio", _("Record audio")), ("iq", _("Record IQ"))):
            dis = " disabled" if kind in active or not s["running"] else ""
            parts.append(f"<button data-start={kind}{dis}>{e(label)}</button>")
        parts.append(f"<button data-stop=1{'' if active else ' disabled'}>{e(_('Stop'))}</button></p>")
        fs = float(self.srv.radio.state().get("fs") or 0)
        if fs:
            parts.append(f"<p class=warn>{e(_('IQ recordings are large. {cost} An IQ recording stops by itself after {minutes:g} minutes.').format(cost=sigmf.cost_sentence(fs), minutes=st['limits']['iqMaxSeconds'] / 60))}</p>")
        parts.append("<p>" + e(_("{used} of {limit} used; {free} free. The oldest are deleted past {limit}; nothing records with less than {floor} free.").format(
            used=sigmf.size_text(u["bytes"]), limit=sigmf.size_text(u["limitBytes"]), free=sigmf.size_text(u["freeBytes"]),
            floor=sigmf.size_text(u["floorBytes"]))) + "</p>")
        if st["last"] and st["last"].get("error"):
            parts.append(f"<p class=warn>{e(st['last']['error'])}</p>")
        rows = []
        for r in st["recordings"]:
            q = "api/recordings/file?id=" + e(urllib.parse.quote(r["id"]))
            mins, secs = divmod(int(round(r.get("seconds") or 0)), 60)
            play = (f"<audio controls preload=none src='{q}&amp;part=data'></audio>"
                    if r["kind"] == "audio" else "")
            links = (f"<a href='{q}&amp;part=data&amp;download=1'>{e(r['parts']['data']['name'].rsplit('.', 1)[-1])}</a>"
                     + (f" <a href='{q}&amp;part=meta&amp;download=1'>{e(r['parts']['meta']['name'].rsplit('.', 1)[-1])}</a>"
                        if "meta" in r["parts"] else ""))
            delete = "" if r.get("recording") else f"<button data-delete='{e(r['id'], quote=True)}'>{e(_('Delete'))}</button>"
            freq = f"{r['freqHz'] / 1e6:.6f} MHz" if r.get("freqHz") else ""
            rows.append(f"<tr><td>{e(str(r.get('startUtc') or '').replace('T', ' '))}</td>"
                        f"<td>{e(_('audio') if r['kind'] == 'audio' else _('IQ'))}</td><td>{e(freq)}</td>"
                        f"<td>{e(str(r.get('mode') or ''))}</td><td>{mins}:{secs:02d}</td><td>{mb(r['bytes'])}</td>"
                        f"<td>{play}</td><td>{links}</td><td>{delete}</td></tr>")
        if rows:
            parts.append("<table class=rec><tr>" + "".join(f"<th>{e(h)}</th>" for h in (
                _("Started (UTC)"), _("Kind"), _("Frequency"), _("Mode"), _("Length"), _("Size"), "", _("Download"), ""))
                + "</tr>" + "".join(rows) + "</table>")
        else:
            parts.append(f"<p>{e(_('No recordings yet.'))}</p>")
        confirm = json.dumps(_("Delete this recording?"))
        parts.append("<script>(()=>{const post=(p,b)=>fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},"
                     "body:JSON.stringify(b)}).then(r=>r.json().then(j=>{if(!r.ok)alert(j.error||r.status);location.reload()}));"
                     "document.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>post('api/recordings/start',{kind:b.dataset.start}));"
                     "document.querySelectorAll('[data-stop]').forEach(b=>b.onclick=()=>post('api/recordings/stop',{}));"
                     f"document.querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{{if(confirm({confirm}))post('api/recordings/delete',{{id:b.dataset.delete}})}});"
                     + ("setInterval(()=>fetch('api/recordings/status').then(r=>r.json()).then(j=>{if(!j.recording)"
                        "return location.reload();j.active.forEach(a=>{const s=document.getElementById('s-'+a.kind),"
                        "z=document.getElementById('z-'+a.kind);if(s)s.textContent=Math.round(a.seconds);"
                        "if(z)z.textContent=(a.bytes/1e6).toFixed(1)+' MB'})}),2000);" if active else "")
                     + "})()</script>")
        return "".join(parts)

    def get_status(self, who, q):
        self._send(200, self.srv.status())

    def get_state(self, who, q):
        self._send(200, self.srv.radio.state())

    def get_spec(self, who, q):
        spec = self.srv.radio.STATE.spec
        self._send(200, {k: {f: v for f, v in s.items() if f in ("type", "kind", "default", "min", "max", "choices",
                                                                  "unit", "help", "auth", "restart")}
                         for k, s in spec.items()})

    def post_set(self, who, q):
        body = self._body()
        # dropSessions: the operator agreed to stop the background decoder
        # sessions a tune out of their span would stop (SpanPinned). Beside
        # "changes", or among the keys of the flat form; never a setting.
        drop = body.get("dropSessions") is True
        changes = body.get("changes") if isinstance(body.get("changes"), dict) else body
        changes = {k: v for k, v in changes.items() if k != "dropSessions"}
        owned = sorted(PROFILE_KEYS & set(changes))
        if owned:
            raise ValueError(_("{keys}: set in the station profile on the controller, not here").format(
                keys=", ".join(owned)))
        plat = sorted(PLATFORM_KEYS & set(changes))
        if plat:
            raise ValueError(_("{keys}: the controller looks after these").format(keys=", ".join(plat)))
        spec = self.srv.radio.STATE.spec
        auth = any(spec.get(k, {}).get("auth") for k in changes)
        if auth and not self._need(who, "transmit"):
            return
        try:
            changed = self.srv.radio.set(authorise=auth, drop_sessions=drop, **changes)
        except ReceiverHeld as e:
            # Not a bad request: the receiver is a DAB session's until it
            # stops (Engine.hold_receiver).
            self._error(409, str(e), e.code, rxOwner=self.srv.radio.state().get("rxOwner") or {})
            return
        self._send(200, {"changed": changed})

    def post_start(self, who, q):
        self.srv.wanted = True
        self.srv.parked = False
        why = self.srv.start_radio("person", who["device"], reclaim=self.srv.reclaim is not None) if not self.srv.radio.state().get("running") else ""
        self._send(200, {**self.srv.status(), "startError": why})

    def post_stop(self, who, q):
        self.srv.wanted = False
        self.srv.stop_radio("")
        self._send(200, self.srv.status())

    def post_ptt(self, who, q):
        body = self._body()
        if body.get("on"):
            if not self._need(who, "transmit"):
                return
            remote = str(body.get("remote") or "")
            if not REMOTE_RE.match(remote):
                raise ValueError(_("remote must be 1 to 64 letters, digits, '.', '_', ':' or '-'"))
            self.srv.key(remote, who["device"])
        else:
            self.srv.unkey("")
            self.srv.tx_error = ""
        self._send(200, self.srv.status())

    def post_autotx(self, who, q):
        """Automatic transmit (autotx.py): `{"on": true, "remote"}` arms it
        (Transmit), with `"cq": true` (`period`, `offset`), `"reply": <a
        decode as api/events sent it>` or `"text": "<a line>"` to choose
        what goes; `{"on": false}` disarms and ends any over on the air
        (Control: anyone who may change anything may stop it)."""
        body = self._body()
        if not body.get("on"):
            why = _("Automatic transmit switched off by {user}").format(user=who["user"])
            if self.srv.digi.disarm(why):
                self.srv.halt_if_keyed(why)
            self._send(200, self.srv.status())
            return
        if not self._may_enable_tx(who):
            return
        remote = str(body.get("remote") or "")
        if not REMOTE_RE.match(remote):
            raise ValueError(_("remote must be 1 to 64 letters, digits, '.', '_', ':' or '-'"))
        digi = self.srv.digi
        # Armed, overs will key: a band scan gives the receiver back now.
        self.srv.radio.client_activity("transmit")
        try:
            digi.arm(remote, who["device"])
            if body.get("cq"):
                digi.cq(remote, body.get("period"), body.get("offset"))
            elif isinstance(body.get("reply"), dict):
                digi.reply(remote, body["reply"])
            elif body.get("text") is not None:
                digi.send_text(remote, str(body["text"]))
        except Refused as e:
            self._error(e.status, str(e), e.code, autoTx=self.srv.digi.view(), txError=self.srv.tx_error)
            return
        self._send(200, self.srv.status())

    def _may_enable_tx(self, who) -> bool:
        """Whether `who` may arm automatic transmit: the Transmit level, as
        for PTT, or a TV the controller's administrator allowed digital
        transmit (Brian, 11/10/2026, openhamshack docs/REMOTE-KEYS.md
        "Decided"; CONTROLLER-CONTRACT 5.5: `X-OpenHamShack-Transmit:
        digital`, which arrives with the Control level).

        Admitted here, in the heartbeat route (DIGITAL_ROUTES) and nowhere
        else: post_ptt and api/audio/tx keep needing Transmit, so such a TV
        never sends voice. Every over it arms still goes through Server.key,
        so the licence, the band plan and the broker decide as for anyone,
        and the broker is told the over is digital. The arm's dead-man (the
        arming device's heartbeat, autotx.py) covers a TV that sleeps or
        drops off the network."""
        if who["transmit"] == "digital" and shack.level_at_least(who["level"], "control"):
            return True
        return self._need(who, "transmit")

    def post_heartbeat(self, who, q):
        body = self._body()
        remote = str(body.get("remote") or "")
        if who["level"] != "transmit" and self.srv.digi.remote != remote:
            # Here on a digital-only right: it keeps an arm alive and holds
            # no other lease, so a heartbeat for anything else is refused.
            self._error(403, _("This TV may only transmit with Enable TX"), "level_too_low",
                        level=who["level"], needs="transmit")
            return
        status, ans = self.srv.heartbeat(remote)
        self._send(status, ans)

    def post_halt(self, who, q):
        # Stopping a transmission needs no transmit level: anyone who may
        # change anything may stop it.
        self.srv.unkey(_("Transmit stopped by {user}").format(user=who["user"]))
        self._send(200, self.srv.status())

    def get_cwskim(self, who, q):
        """Radio's CW skimmer: the cwskim item and the last 30 minutes'
        spots (docs/SERVER-API.md). Only an app with one has the route's
        answer; NB has none."""
        view = getattr(self.srv.radio, "cwskim_view", None)
        if view is None:
            self._error(404, _("This app has no CW skimmer."), "not_found")
            return
        self._send(200, view())

    # ---------------------------------------------------------- decoders
    # api/decoders (docs/SERVER-API.md "Decoders"; RADIO-SDR-PLAN §4.4): the
    # engine's decoder sessions (ohscore/decoders.py). Nothing here transmits.
    REFUSAL_STATUS = {"bad_params": 400, "unknown_decoder": 404, "unknown_session": 404,
                      "decoder_unavailable": 409, "outside_span": 409, "receiver_busy": 409, "on_air": 409,
                      "span_pinned": 409, "bad_client": 400, "too_many_clients": 429,
                      "rate_too_low": 409, "out_of_range": 409, "too_many_sessions": 429, "not_running": 503,
                      "device_error": 503}

    def get_decoders(self, who, q):
        d = self.srv.radio.decoders
        self._send(200, {"decoders": d.catalogue(), "codecs": d.codecs(), "limits": d.limits(),
                         "sessions": d.sessions()})

    def post_decoder_session(self, who, q):
        from ..decoders import Refused as DecoderRefused
        b = self._body()
        decoder, freq, params = b.get("decoder"), b.get("freqHz"), b.get("params") or {}
        d = self.srv.radio.decoders
        # A decoder that takes the receiver (DAB) may name its block in
        # params instead of giving freqHz (the block's centre).
        held = isinstance(decoder, str) and d.holds_receiver(decoder)
        client = self._client(b.get("client"))
        if held and b.get("stop") is True:
            self._held_gives_way(who, b, None, {})
            return
        if not isinstance(decoder, str) or not isinstance(params, dict) or isinstance(freq, bool) \
                or not (isinstance(freq, (int, float)) or (held and freq is None and params.get("block"))):
            self._error(400, _("Give decoder, freqHz and, if any, params"), "bad_params")
            return
        if held and self.srv.digi.remote is not None:
            # Armed, the next over would key wherever DAB had taken the
            # receiver; the operator disarms first, as for any key-up.
            self._error(409, _("Not while automatic transmit is armed: switch it off first"), "on_air")
            return
        if held and b.get("replace") is True and self._held_gives_way(who, b, freq, params, client):
            return
        try:
            sess = d.start(decoder, None if freq is None else float(freq), params,
                           drop_sessions=b.get("dropSessions") is True)
        except DecoderRefused as e:
            more = {"needs": e.needs} if e.needs else {}
            if e.sessions is not None:
                more["sessions"] = e.sessions
            self._error(self.REFUSAL_STATUS.get(e.code, 400), str(e), e.code, **more)
            return
        log.info("decoder session %s started by %s: %s at %.0f Hz", sess["id"], who.get("user", "?"), decoder,
                 sess["freqHz"])
        if held:
            # Client-scoped: it ends when the last client that asked for
            # it goes (presence). A background session is station-scoped
            # (saved, started again with the radio) and never recorded.
            self.srv.holds.add(("held", sess["id"]), client)
        self._send(201, sess)

    def _held_gives_way(self, who, b: dict, freq, params: dict, client: str | None = None) -> bool:
        """`"stop": true` and `"replace": true` on POST api/decoders/sessions
        for a decoder that holds the receiver (DAB): what a ui/1 screen
        needs, since its actions are POSTs to fixed paths (CLIENT-UI-PLAN
        §5.5) and cannot carry the session id a DELETE or a live change
        names, nor a DELETE at all. The same Control level as the route.

        - stop: the playing station stops, exactly as DELETE
          api/decoders/sessions/{id} would; 404 unknown_session when none
          plays.
        - replace: the playing station gives way to this one. On the same
          block only the service changes, live (200, the same session, as
          POST api/decoders/sessions/{id} {"params"}); on another block it
          stops and the new one starts (the usual 201). With none playing
          it is an ordinary start.

        True when the request has been answered; False to go on and start."""
        d = self.srv.radio.decoders
        decoder = b["decoder"]
        sid = d.held_by(decoder)
        if b.get("stop") is True:
            if sid is None or not d.stop(sid):
                self._error(404, _("No {decoder} station is playing").format(decoder=decoder.upper()),
                            "unknown_session")
            else:
                self._forget_session(sid)
                log.info("decoder session %s stopped by %s", sid, who.get("user", "?"))
                self._send(200, {"stopped": True, "id": sid})
            return True
        if sid is None:
            return False
        cur = d.session(sid) or {}
        block = str(params.get("block") or "").strip().upper()
        same = (block == cur.get("block")) if block else \
            (freq is not None and abs(float(freq) - float(cur.get("freqHz") or 0.0)) < 8_000.0)
        if same:
            from ..decoders import Refused as DecoderRefused
            try:
                sess = d.configure(sid, {k: v for k, v in params.items() if k != "block"})
            except DecoderRefused as e:
                self._error(self.REFUSAL_STATUS.get(e.code, 400), str(e), e.code)
                return True
            log.info("decoder session %s set by %s: %s", sid, who.get("user", "?"), params)
            # Choosing the station is asking for it too.
            self.srv.holds.add(("held", sid), client)
            self._send(200, sess)
            return True
        d.stop(sid)
        self._forget_session(sid)
        log.info("decoder session %s stopped by %s for another block", sid, who.get("user", "?"))
        return False

    def post_decoder_session_params(self, who, q):
        """POST api/decoders/sessions/{id} {"params": {...}}: change a
        running session live (DAB's service). And POST
        api/decoders/sessions/{id}/listen {"listen": true|false}: hear the
        session instead of the demodulator, or the demodulator again."""
        from ..decoders import Refused as DecoderRefused
        parts = urlsplit(self.path).path.rstrip("/").split("/")
        if parts[-1] == "listen" and len(parts) >= 2:
            self._listen(who, parts[-2])
            return
        b = self._body()
        params = b.get("params")
        if not isinstance(params, dict):
            self._error(400, _("Give params"), "bad_params")
            return
        sid = self._session_id()
        try:
            sess = self.srv.radio.decoders.configure(sid, params)
        except DecoderRefused as e:
            self._error(self.REFUSAL_STATUS.get(e.code, 400), str(e), e.code)
            return
        log.info("decoder session %s set by %s: %s", sid, who.get("user", "?"), params)
        self._send(200, sess)

    def _forget_session(self, sid: str) -> None:
        self.srv.holds.forget(("held", sid))
        self.srv.holds.forget(("listen", sid))

    def _listen(self, who, sid: str) -> None:
        from ..decoders import Refused as DecoderRefused
        b = self._body()
        on = b.get("listen", True)
        if not isinstance(on, bool):
            self._error(400, _("listen is true or false"), "bad_params")
            return
        client = self._client(b.get("client"))
        try:
            sess = self.srv.radio.decoders.listen(sid, on)
        except DecoderRefused as e:
            self._error(404 if e.code == "unknown_session" else 409, str(e), e.code)
            return
        log.info("decoder session %s %s by %s", sid, "listened to" if on else "no longer listened to",
                 who.get("user", "?"))
        # Listening is client-scoped (the session itself may not be); off
        # is off for everyone, there being one thing heard.
        if on:
            self.srv.holds.add(("listen", sid), client)
        else:
            self.srv.holds.forget(("listen", sid))
        self._send(200, sess)

    def _session_id(self) -> str:
        return urlsplit(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def get_decoder_session(self, who, q):
        try:
            since = int(q["since"][0]) if "since" in q else None
        except ValueError:
            self._error(400, _("since must be a whole number"), "bad_params")
            return
        sess = self.srv.radio.decoders.session(self._session_id(), since)
        if sess is None:
            self._error(404, _("There is no decoder session called {id}").format(id=self._session_id()),
                        "unknown_session")
            return
        self._send(200, sess)

    def delete_decoder_session(self, who, q):
        sid = self._session_id()
        if sid == "vfo" or not self.srv.radio.decoders.stop(sid):
            self._error(404, _("There is no decoder session called {id}").format(id=sid), "unknown_session")
            return
        self._forget_session(sid)
        log.info("decoder session %s stopped by %s", sid, who.get("user", "?"))
        self._send(200, {"stopped": True})

    def post_codecs_rescan(self, who, q):
        self._send(200, {"codecs": self.srv.radio.decoders.codecs(rescan=True)})

    def get_decoder_files(self, who, q):
        """GET api/decoders/files: the pictures decoders saved (SSTV's),
        newest first, by name; each is fetched from api/decoders/files/{name}."""
        self._send(200, {"files": self.srv.radio.decoders.files()})

    def get_decoder_file(self, who, q):
        """GET api/decoders/files/{name}: one saved picture, as PNG
        (`download=1` asks a browser to save it rather than show it). The
        name must be one the list gives: anything else is 404, a path
        included (the host refuses any name that could leave its folder)."""
        name = unquote(self._session_id())
        data = self.srv.radio.decoders.file(name)
        if data is None:
            self._error(404, _("There is no decoded picture called {name}").format(name=name), "no_file")
            return
        extra = {}
        if q.get("download", [""])[0] in ("1", "true"):
            extra["Content-Disposition"] = f'attachment; filename="{name}"'
        self._send(200, data, "image/png" if name.lower().endswith(".png") else "application/octet-stream",
                   extra)

    # ---------------------------------------------------------- DAB's pictures
    # Slides, logos and the programme guide a DAB session received
    # (ohscore/dabpics.py, docs/SERVER-API.md "DAB pictures"). Radio only.
    def _dab_pictures(self):
        pics = getattr(self.srv.radio, "dab_pictures", None)
        if pics is None:
            self._error(404, _("This app has no DAB."), "not_found")
        return pics

    def _dab_sid(self):
        from ..dabpics import sid_ok
        sid = unquote(self._session_id()).upper()
        if not sid_ok(sid):
            self._error(400, _("A service id is four or eight hexadecimal digits"), "bad_params")
            return None
        return sid

    def get_dab_slides(self, who, q):
        """GET api/dab/slides: the latest slide of each service heard since
        the radio started, newest first."""
        pics = self._dab_pictures()
        if pics is not None:
            self._send(200, {"slides": [pics.slide_info(sid) for sid in reversed(list(pics.slides))]})

    def get_dab_slide(self, who, q):
        """GET api/dab/slides/{sid}: that service's latest slide, as the
        picture it is (JPEG or PNG)."""
        pics = self._dab_pictures()
        sid = self._dab_sid() if pics is not None else None
        if sid is None:
            return
        got = pics.slide(sid)
        if got is None:
            self._error(404, _("No slide has come from {sid} yet").format(sid=sid), "no_slide")
            return
        self._send(200, got[0], got[1])

    def get_dab_logo(self, who, q):
        """GET api/dab/logos/{sid}[?variant=square|wide]: that service's
        logo from its ensemble's SPI, kept on disk; the other variant when
        the one asked for never came."""
        pics = self._dab_pictures()
        sid = self._dab_sid() if pics is not None else None
        if sid is None:
            return
        variant = q.get("variant", ["square"])[0]
        if variant not in ("square", "wide"):
            self._error(400, _("variant is square or wide"), "bad_params")
            return
        got = pics.logo(sid, variant)
        if got is None:
            self._error(404, _("No logo has come for {sid} yet").format(sid=sid), "no_logo")
            return
        self._send(200, got[0], got[1])

    def get_dab_schedule(self, who, q):
        """GET api/dab/schedule/{sid}[?date=YYYY-MM-DD]: that service's
        programmes from SPI, all that are known or those starting on a UTC
        date."""
        pics = self._dab_pictures()
        sid = self._dab_sid() if pics is not None else None
        if sid is None:
            return
        date = q.get("date", [""])[0]
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            self._error(400, _("date is YYYY-MM-DD"), "bad_params")
            return
        progs = pics.schedule(sid, date or None)
        if progs is None:
            self._error(404, _("No programme guide has come for {sid} yet").format(sid=sid), "no_schedule")
            return
        self._send(200, {"sid": sid, "date": date or None, "programmes": progs})

    # ---------------------------------------------------------- the band scan
    # Radio's FM and DAB station lists (ohsradio/bandscan.py,
    # docs/SERVER-API.md "Station lists"). NB has none: 404.
    SCAN_STATUS = {"bad_params": 400, "receiver_busy": 409, "unsupported": 409, "not_running": 503}

    def _scanner(self):
        scan = getattr(self.srv.radio, "bandscan", None)
        if scan is None:
            self._error(404, _("This app has no station lists."), "not_found")
        return scan

    def get_fm_stations(self, who, q):
        scan = self._scanner()
        if scan is not None:
            self._send(200, scan.view("fm"))

    def get_dab_stations(self, who, q):
        scan = self._scanner()
        if scan is not None:
            self._send(200, scan.view("dab"))

    def post_scan(self, who, q):
        scan = self._scanner()
        if scan is None:
            return
        band = self._body().get("band", "both")
        try:
            got = scan.scan_now(band if isinstance(band, str) else "")
        except ValueError as e:
            # The scanner's Refused (a ValueError with its code): ohscore
            # never imports an app's package.
            code = getattr(e, "code", "bad_params")
            self._error(self.SCAN_STATUS.get(code, 409), str(e), code)
            return
        log.info("band scan of %s started by %s", "+".join(got["bands"]), who.get("user", "?"))
        self._send(202, got)

    # ui/v1 (uiv1.py, docs/SERVER-API.md "ui/1 screens"): the app's
    # server-driven screens. NB serves none yet and answers 404.
    def _ui(self, who):
        screens = self.srv.info.screens
        if screens is None:
            self._error(404, _("This app serves no screens."), "not_found")
            return None, None
        if not uiv1.ui_major_ok(self.headers.get("X-OpenHamShack-UI")):
            self._error(406, _("This app serves ui/1 screens, which this OpenHamShack app cannot show."),
                        "ui_unsupported", ui=[uiv1.UI_VERSION])
            return None, None
        req = uiv1.Request(self._base(), uiv1.parse_components(self.headers.get("X-OpenHamShack-Components")),
                           who.get("level", "view"), self.headers.get("X-OpenHamShack-UI"))
        return screens, req

    def _send_ui(self, body: dict) -> None:
        """A descriptor or screen: its rev as the ETag, 304 when the client
        has it (§5.7), and never through with_urls (uiv1.py says why)."""
        rev = uiv1.rev_of(body)
        if "screen" in body:
            body = {**body, "rev": rev}
        etag = f'"{rev}"'
        # no-cache, not no-store: kept, but asked about every time, so a
        # screen never opens from a stale copy (§5.7) and costs a 304.
        extra = {"ETag": etag, "X-OpenHamShack-UI": uiv1.UI_VERSION, "Cache-Control": "no-cache"}
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(200, dumps(body), extra=extra)

    def get_ui_app(self, who, q):
        screens, req = self._ui(who)
        if screens is not None:
            self._send_ui(screens.descriptor(self.srv, req))

    def get_ui_screen(self, who, q):
        screens, req = self._ui(who)
        if screens is None:
            return
        sid = urlsplit(self.path).path.rstrip("/")[len("/ui/v1/screen/"):]
        params = {k: v[0] for k, v in q.items()}
        try:
            doc = screens.screen(self.srv, sid, params, req)
        except uiv1.UnknownScreen:
            self._error(404, _("There is no screen called {id}").format(id=sid), "unknown_screen")
            return
        self._send_ui(doc)

    def get_ui_data(self, who, q):
        """A screen's own data feed (`get:ui/v1/data/<name>`): what an
        existing route has, shaped for binding where that route's own shape
        cannot be bound to (Radio's DAB station is behind a session id)."""
        screens, req = self._ui(who)
        if screens is None:
            return
        name = urlsplit(self.path).path.rstrip("/")[len("/ui/v1/data/"):]
        try:
            body = screens.data(self.srv, name, req)
        except uiv1.UnknownScreen:
            self._error(404, _("There is nothing at {path}").format(path=self.path), "not_found")
            return
        self._send(200, body)

    # api/ais and api/map (docs/SERVER-API.md "AIS" and "Map"): Radio's ships
    # on a map. NB has neither and answers 404.
    def _ais(self):
        a = getattr(self.srv.radio, "ais", None)
        if a is None:
            self._error(404, _("This app has no AIS."), "not_found")
        return a

    def get_ais_session(self, who, q):
        a = self._ais()
        if a is not None:
            self._send(200, a.view())

    def post_ais_session(self, who, q):
        """POST api/ais/session {"client": id[, "dropSessions": true]}: this
        client has the map open - start AIS, or keep it running. Again at
        least every leaseS seconds while the map is open."""
        from ..decoders import Refused as DecoderRefused
        a = self._ais()
        if a is None:
            return
        b = self._body()
        if a.state != "running" and self.srv.digi.remote is not None:
            # Armed, the next over would key wherever AIS had taken the
            # receiver; the operator disarms first, as for DAB.
            self._error(409, _("Not while automatic transmit is armed: switch it off first"), "on_air")
            return
        try:
            view = a.join(b.get("client"), drop_sessions=b.get("dropSessions") is True)
        except DecoderRefused as e:
            more = {"sessions": e.sessions} if e.sessions is not None else {}
            self._error(self.REFUSAL_STATUS.get(e.code, 400), str(e), e.code, **more)
            return
        self._send(200, view)

    def delete_ais_session(self, who, q):
        """DELETE api/ais/session?client=id: this client closed the map.
        ?all=1: stop AIS now, whoever has the map open."""
        a = self._ais()
        if a is None:
            return
        if q.get("all", [""])[0] in ("1", "true"):
            a.end("stopped")
            log.info("AIS stopped by %s", who.get("user", "?"))
            self._send(200, a.view())
            return
        self._send(200, a.leave(q.get("client", [""])[0]))

    def get_ais_vessels(self, who, q):
        """GET api/ais/vessels[?since=rev]: every vessel, or what changed."""
        a = self._ais()
        if a is None:
            return
        try:
            since = int(q["since"][0]) if "since" in q else None
        except ValueError:
            self._error(400, _("since must be a whole number"), "bad_params")
            return
        st = a.table.station
        loc = self.srv.radio.state().get("locator") or ""
        self._send(200, {**a.table.view(since), "session": a.view(),
                         "keepMinutes": int(self.srv.radio.state().get("aisKeepMinutes", 60)),
                         "station": {"locator": loc or None, "lat": st[0] if st else None,
                                     "lon": st[1] if st else None}})

    def get_ais_vessel(self, who, q):
        a = self._ais()
        if a is None:
            return
        try:
            mmsi = int(self._session_id())
        except ValueError:
            self._error(400, _("An MMSI is a number of up to nine digits"), "bad_params")
            return
        v = a.table.vessel(mmsi)
        if v is None:
            self._error(404, _("No vessel {mmsi} has been heard lately").format(mmsi=mmsi), "unknown_vessel")
            return
        self._send(200, v)

    # api/adsb (docs/SERVER-API.md "ADS-B"): Radio's aircraft, on the same
    # map as its ships, shaped as api/ais is. NB has none and answers 404.
    def _adsb(self):
        a = getattr(self.srv.radio, "adsb", None)
        if a is None:
            self._error(404, _("This app has no ADS-B."), "not_found")
        return a

    def get_adsb_session(self, who, q):
        a = self._adsb()
        if a is not None:
            self._send(200, a.view())

    def post_adsb_session(self, who, q):
        """POST api/adsb/session {"client": id[, "dropSessions": true]}: this
        client has the aircraft map open - start ADS-B, or keep it running.
        Again at least every leaseS seconds while the map is open. Starting
        may reopen the radio at a faster rate (a second or two)."""
        from ..decoders import Refused as DecoderRefused
        a = self._adsb()
        if a is None:
            return
        b = self._body()
        if a.state != "running" and self.srv.digi.remote is not None:
            # Armed, the next over would key wherever ADS-B had taken the
            # receiver; the operator disarms first, as for AIS and DAB.
            self._error(409, _("Not while automatic transmit is armed: switch it off first"), "on_air")
            return
        try:
            view = a.join(b.get("client"), drop_sessions=b.get("dropSessions") is True)
        except DecoderRefused as e:
            more = {"sessions": e.sessions} if e.sessions is not None else {}
            self._error(self.REFUSAL_STATUS.get(e.code, 400), str(e), e.code, **more)
            return
        self._send(200, view)

    def delete_adsb_session(self, who, q):
        """DELETE api/adsb/session?client=id: this client closed the map.
        ?all=1: stop ADS-B now, whoever has the map open."""
        a = self._adsb()
        if a is None:
            return
        if q.get("all", [""])[0] in ("1", "true"):
            a.end("stopped")
            log.info("ADS-B stopped by %s", who.get("user", "?"))
            self._send(200, a.view())
            return
        self._send(200, a.leave(q.get("client", [""])[0]))

    def get_adsb_aircraft(self, who, q):
        """GET api/adsb/aircraft[?since=rev]: every aircraft, or what changed."""
        a = self._adsb()
        if a is None:
            return
        try:
            since = int(q["since"][0]) if "since" in q else None
        except ValueError:
            self._error(400, _("since must be a whole number"), "bad_params")
            return
        st = a.table.station
        loc = self.srv.radio.state().get("locator") or ""
        self._send(200, {**a.table.view(since), "session": a.view(),
                         "keepMinutes": int(self.srv.radio.state().get("adsbKeepMinutes", 5)),
                         "station": {"locator": loc or None, "lat": st[0] if st else None,
                                     "lon": st[1] if st else None}})

    def get_adsb_one(self, who, q):
        a = self._adsb()
        if a is None:
            return
        icao = self._session_id().upper()
        if not re.match(r"^~?[0-9A-F]{6}$", icao):
            self._error(400, _("An ICAO address is six hexadecimal digits"), "bad_params")
            return
        v = a.table.aircraft(icao)
        if v is None:
            self._error(404, _("No aircraft {icao} has been heard lately").format(icao=icao), "unknown_aircraft")
            return
        self._send(200, v)

    def _send_bytes(self, status: int, raw: bytes, ctype: str, headers: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _map(self):
        """Radio's map module (ohsradio/mapdata.py), which the engine
        carries so this shared server never imports Radio; None (and a 404)
        for an app with no map."""
        m = getattr(self.srv.radio, "mapdata", None)
        if m is None:
            self._error(404, _("This app has no map."), "not_found")
        return m

    def get_map_info(self, who, q):
        mapdata = self._map()
        if mapdata is None:
            return
        r = self.srv.radio
        tiles = r.map_tiles
        land = mapdata.Land.load()
        st = r.ais.table.station if getattr(r, "ais", None) is not None else None
        self._send(200, {
            "land": land.info() if land is not None else None,
            "bounds": list(land.bounds) if land is not None else None,
            "attribution": [mapdata.ATTRIBUTION],
            "tiles": {**tiles.stats(), "url": "api/map/tiles/{z}/{x}/{y}.png", "minZoom": 0,
                      "maxZoom": mapdata.MAX_ZOOM, "size": 256, "attribution": mapdata.ATTRIBUTION},
            "station": {"locator": r.state().get("locator") or None, "lat": st[0] if st else None,
                        "lon": st[1] if st else None}})

    def get_map_land(self, who, q):
        """GET api/map/land?bbox=w,s,e,n[&detail=auto|fine|coarse][&format=geojson|compact]."""
        mapdata = self._map()
        if mapdata is None:
            return
        land = mapdata.Land.load()
        if land is None:
            self._error(404, _("This install has no land map"), "no_land")
            return
        bbox = mapdata.parse_bbox(q.get("bbox", [""])[0]) if "bbox" in q else tuple(land.bounds)
        detail = q.get("detail", ["auto"])[0]
        fmt = q.get("format", ["geojson"])[0]
        if bbox is None or detail not in ("auto", "fine", "coarse") or fmt not in ("geojson", "compact"):
            self._error(400, _("bbox is west,south,east,north in degrees; detail auto, fine or coarse; format "
                               "geojson or compact"), "bad_params")
            return
        if detail == "fine" and max(bbox[2] - bbox[0], bbox[3] - bbox[1]) > 4 * mapdata.FINE_MAX_SPAN_DEG:
            detail = "coarse"
        body = land.geojson(bbox, detail) if fmt == "geojson" else land.compact(bbox, detail)
        raw = dumps(body)
        headers = {"Cache-Control": "max-age=86400"}
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            import gzip
            raw = gzip.compress(raw, 6)
            headers["Content-Encoding"] = "gzip"
        ctype = "application/geo+json" if fmt == "geojson" else "application/json"
        self._send_bytes(200, raw, ctype, headers)

    def get_map_tile(self, who, q):
        """GET api/map/tiles/{z}/{x}/{y}.png: an OpenStreetMap tile from the
        cache (fetched first when allowed), or 404: draw the land map."""
        if self._map() is None:
            return
        tiles = self.srv.radio.map_tiles
        m = re.fullmatch(r"/api/map/tiles/(\d{1,2})/(\d{1,7})/(\d{1,7})\.png", urlsplit(self.path).path)
        got = tiles.get(int(m[1]), int(m[2]), int(m[3])) if m else None
        if got is None:
            self._error(404, _("No map picture here: draw the built-in map"), "no_tile")
            return
        png, max_age = got
        self._send_bytes(200, png, "image/png", {"Cache-Control": f"max-age={max_age}"})

    def get_overpower(self, who, q):
        """NB's over-power and LEILA watch: its list of the last 30 minutes
        and its state (docs/SERVER-API.md). Radio has none."""
        view = getattr(self.srv.radio, "overpower_view", None)
        if view is None:
            self._error(404, _("This app has no over-power watch."), "not_found")
            return
        self._send(200, view())

    def post_overpower_capture(self, who, q):
        """Save the LEILA evidence ring now: receive IQ, never a key-up."""
        save = getattr(self.srv.radio, "leila_capture_now", None)
        if save is None:
            self._error(404, _("This app has no over-power watch."), "not_found")
            return
        try:
            save()
        except ValueError as e:
            self._error(409, str(e), "nothing_to_save")
            return
        log.info("%s saved the LEILA evidence capture", who["user"])
        self._send(202, {"ok": True})

    def get_smeter_cal(self, who, q):
        """The stored S-meter calibrations: Radio only (its `band`, and
        hence per-band calibration, is what makes server-side storage worth
        having; NB has none, like api/overpower above). `GET
        api/smeter/calibrate` in docs/SERVER-API.md."""
        table = getattr(self.srv.radio, "smeter_table", None)
        if table is None:
            self._error(404, _("This app has no S-meter calibration."), "not_found")
            return
        self._send(200, {"calibrations": table()})

    def post_smeter_cal(self, who, q):
        """{"dbm": y}: the current (3 s average) reading is y dBm.
        {"dbfs": x, "dbm": y}: a reading of x dBFS measured elsewhere is
        y dBm. Either way, refused with a sentence while the receiver's own
        AGC chooses the gain (smeter_calibrate's ValueError)."""
        calibrate = getattr(self.srv.radio, "smeter_calibrate", None)
        if calibrate is None:
            self._error(404, _("This app has no S-meter calibration."), "not_found")
            return
        body = self._body()
        if "dbm" not in body:
            self._error(400, _("dbm is required"), "bad_params")
            return
        try:
            dbm = smeter_cal.validate_dbm(body["dbm"])
            dbfs = smeter_cal.validate_dbfs(body["dbfs"]) if "dbfs" in body else None
        except ValueError as e:
            self._error(400, str(e), "bad_params")
            return
        try:
            rec = calibrate(dbm, dbfs)
        except ValueError as e:
            self._error(409, str(e), "cannot_calibrate")
            return
        log.info("S-meter calibrated by %s: %s", who.get("user", "?"), rec)
        self._send(200, {"calibration": rec})

    def delete_smeter_cal(self, who, q):
        """Clear this radio's (band's, antenna's) calibration."""
        forget = getattr(self.srv.radio, "smeter_forget", None)
        if forget is None:
            self._error(404, _("This app has no S-meter calibration."), "not_found")
            return
        forget()
        self._send(200, {"ok": True})

    def get_memories(self, who, q):
        self._send(200, {"memories": self.srv.radio.memories()})

    def post_recall(self, who, q):
        self.srv.radio.recall(str(self._body().get("name", "")))
        self._send(200, {"ok": True})

    def get_log(self, who, q):
        self._send(200, {"qsos": self.srv.radio.log_entries()})

    def post_log(self, who, q):
        body = self._body()
        call = body.pop("call", "")
        rec = self.srv.radio.log_qso(call, **{k: v for k, v in body.items()
                                              if k in ("t", self.srv.radio.FREQ_KEY, "mode", "rstSent", "rstRcvd",
                                                       "name", "grid", "comment")})
        self._send(201, rec)

    def get_adif(self, who, q):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = self.srv.radio.export_adif(os.path.join(d, "log.adi"))
            raw = open(p, "rb").read()
        self._send(200, raw, "text/plain; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="{self.srv.info.app_id}.adi"'})

    def post_pad_action(self, who, q):
        """The controller's input host sends a pad press for this app when it
        is in front (CONTROLLER-PAD.md 6.1). `ptt` never arrives here: the
        pad keys through /api/ptt and the lease like any client."""
        body = self._body()
        action = str(body.get("action") or "")
        if action in ("ptt", "transmit"):
            raise ValueError(_("A pad keys through api/ptt, not as an action"))
        if action in PAD_TX_ACTIONS and not self._need(who, "transmit"):
            return
        self.srv.pad().perform(action, str(body.get("kind") or "press"), int(body.get("step") or 1))
        self._send(200, self.srv.pad().faces())

    def get_shack_busy(self, who, q):
        self._send(200, self._busy())

    def post_shack_release(self, who, q):
        status, ans = self.srv.release_request(self._body())
        self._send(status, ans)

    # ---------------------------------------------------------- recordings
    # shack_rec's API (its README; docs/SERVER-API.md "Recordings"):
    # View lists and downloads, Control starts, stops and deletes.
    # ---------------------------------------------------------- local frequencies
    # Radio's (ohsradio/localfreq.py, docs/SERVER-API.md "Local frequencies"):
    # reading at View, the operator's own list at Control, a refresh for an
    # administrator. Nothing here touches the radio.
    def _localfreq(self):
        if not hasattr(type(self.srv.radio), "localfreq"):
            self._error(404, _("This app has no local frequencies."), "not_found")
            return None
        return self.srv.radio.localfreq

    def get_local_frequencies(self, who, q):
        lf = self._localfreq()
        if lf is None:
            return
        radius = None
        if q.get("radiusKm"):
            try:
                radius = float(q["radiusKm"][0])
            except ValueError:
                radius = -1
            if not lf.RADIUS_MIN_KM <= radius <= lf.RADIUS_MAX_KM:
                self._error(400, _("radiusKm must be a number from {lo} to {hi}").format(lo=lf.RADIUS_MIN_KM,
                                                                                         hi=lf.RADIUS_MAX_KM),
                            "bad_radius")
                return
        category = (q.get("category") or [""])[0] or None
        if category is not None and category not in lf.CATEGORIES:
            self._error(400, _("category must be one of {names}").format(names=", ".join(lf.CATEGORIES)),
                        "bad_category")
            return
        self._send(200, self.srv.radio.local_frequencies(radius, category))

    def _mine_answer(self, lf, fn) -> bool:
        try:
            status, ans = fn()
        except lf.Invalid as e:
            self._error(400, str(e), "bad_field", field=e.field)
            return False
        self._send(status, ans)
        return status < 300

    def post_local_mine(self, who, q):
        lf = self._localfreq()
        if lf is None:
            return
        body = self._body()
        modes = self.srv.radio.STATE.modes
        if self._mine_answer(lf, lambda: (201, lf.mine.add(body, modes))):
            log.info("my frequencies: %s added one", who["user"])

    def _mine_id(self) -> str:
        return urllib.parse.unquote(urlsplit(self.path).path.rstrip("/").rsplit("/", 1)[-1])

    def put_local_mine(self, who, q):
        lf = self._localfreq()
        if lf is None:
            return
        eid, body = self._mine_id(), self._body()
        modes = self.srv.radio.STATE.modes

        def edit():
            e = lf.mine.update(eid, body, modes)
            return (200, e) if e is not None else (404, {"error": _("There is no entry {id} in my frequencies").format(
                id=eid), "code": "unknown_entry"})
        self._mine_answer(lf, edit)

    def delete_local_mine(self, who, q):
        lf = self._localfreq()
        if lf is None:
            return
        eid = self._mine_id()
        if not lf.mine.delete(eid):
            self._error(404, _("There is no entry {id} in my frequencies").format(id=eid), "unknown_entry")
            return
        self._send(200, {"deleted": eid})

    def post_local_refresh(self, who, q):
        """An administrator's download of newer data. Radio's levels stop
        at Transmit, so "admin" is the controller's administrator flag
        (X-OpenHamShack-Admin, CONTROLLER-CONTRACT 5.3) at Control level:
        a refresh asks third parties for data on the station's behalf and
        replaces what everyone sees."""
        lf = self._localfreq()
        if lf is None:
            return
        if not who.get("admin"):
            self._error(403, _("Only the controller's administrator may refresh the local frequencies."),
                        "not_admin")
            return
        fetch = self.srv.localfreq_fetch or lf.http_fetch
        key = os.environ.get(OPENAIP_KEY_ENV, "").strip()
        try:
            summary = self.srv.radio.local_refresh(fetch, key)
        except RuntimeError as e:
            self._error(409, str(e), "refresh_running")
            return
        log.info("local frequencies refreshed by %s: %s", who["user"],
                 ", ".join(f"{r['source']} {'ok' if r['ok'] else 'no'}" for r in summary["results"]))
        self._send(200, summary)

    def _refused(self, e) -> None:
        self._error(e.status, e.text, e.code)

    def get_recordings(self, who, q):
        self._send(200, self.srv.recordings.listing())

    def get_recordings_status(self, who, q):
        self._send(200, self.srv.recordings.status())

    def post_recordings_start(self, who, q):
        body = self._body()
        kind = str(body.get("kind") or "audio")
        # What is heard is what is recorded: a band scan gives the receiver back first.
        self.srv.radio.client_activity("recording")
        try:
            st = self.srv.recordings.start(kind, body)
        except self.srv.recordings.Refused as e:
            self._refused(e)
            return
        log.info("%s started recording %s", who["user"], kind)
        self._send(200, st)

    def post_recordings_stop(self, who, q):
        kind = self._body().get("kind") or None
        stopped = self.srv.recordings.stop(str(kind) if kind else None)
        self._send(200, {**self.srv.recordings.status(), "stopped": stopped})

    def post_recordings_delete(self, who, q):
        try:
            gone = self.srv.recordings.delete(str(self._body().get("id") or ""))
        except self.srv.recordings.Refused as e:
            self._refused(e)
            return
        log.info("%s deleted recording %s", who["user"], gone["id"])
        self._send(200, {"deleted": gone})

    def get_recordings_file(self, who, q):
        """One file of a recording, with single-range requests so a player
        can seek (shack_rec.http): http.server has no range support of its own."""
        from .. import shacklibs
        try:
            path, ctype = self.srv.recordings.file(q.get("id", [""])[0], q.get("part", ["data"])[0])
            f = open(path, "rb")
        except self.srv.recordings.Refused as e:
            self._refused(e)
            return
        except OSError:
            self._error(404, _("There is no such recording."), "no_recording")
            return
        rh = shacklibs.rec()             # after file(): NoRecordings has refused by now
        with f:
            size = os.fstat(f.fileno()).st_size
            try:
                rng = rh.parse_range(self.headers.get("Range"), size)
            except rh.RangeNotSatisfiable:
                self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                return
            status, headers = rh.file_headers(size, ctype, path.name, q.get("download", [""])[0] in ("1", "true"), rng)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return
            first, last = rng if rng else (0, size - 1)
            f.seek(first)
            left = last - first + 1
            while left > 0:
                chunk = f.read(min(FILE_CHUNK, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---------------------------------------------------------- streams
    def ws_events(self, who, q):
        """The engine's feeds as JSON messages, one per item:
        {"kind": "state" | "toast" | ..., ...item}. ?kinds=a,b picks them;
        spectrum kinds are offered but not sent unless asked."""
        radio = self.srv.radio
        # "decoder" is the decoder sessions' results (SERVER-API "Decoders"):
        # the engine's feed `decoders`, each item sent as kind "decoder".
        asked = [{"decoder": "decoders"}.get(k, k) for k in q.get("kinds", [",".join(FEED_KINDS_DEFAULT)])[0].split(",")]
        kinds = [k for k in dict.fromkeys(asked) if k in radio.FEED_KINDS]
        client = self._client(q.get("client", [""])[0])
        if not ws.handshake(self):
            return
        sock = ws.Socket(self.rfile, self.wfile)
        feeds = {k: radio.subscribe(k, 256 if k not in SPECTRUM else 8) for k in kinds}
        # `gone` is the client closing it, or its presence saying it went.
        token, gone = self.srv.holds.open_stream(client)
        with self.srv.lock:
            self.srv.events_sockets += 1

        def reader():
            try:
                while sock.recv() is not None:
                    pass
            except (OSError, ConnectionError):
                pass
            gone.set()
        threading.Thread(target=reader, daemon=True).start()
        base = self._base()
        try:
            sock.send_text(json.dumps(with_urls({"kind": "hello", "status": self.srv.status()}, base),
                                      default=_json_default))
            state_dropped = 0
            while not gone.wait(0.05):
                for k, f in feeds.items():
                    items = f.drain()
                    if k == "state" and f.dropped != state_dropped:
                        # A state change is published once, as a diff, into a
                        # feed that drops its oldest when full. A client that
                        # stalled past that lost changes it can never hear of
                        # again (a settled value does not change twice), so
                        # send the whole state instead, in the shape it
                        # already merges, marked "full". What was drained is
                        # older than this and is replaced by it, not sent
                        # after it. Same repair as the desktop Bridge.pump.
                        state_dropped = f.dropped
                        log.warning("events client %s: state feed dropped changes, resending the whole state",
                                    who.get("user", "?"))
                        items = [{"changes": dict(radio.state()), "full": True}]
                    for item in items:
                        msg = spectrum_item(k, item) if k in SPECTRUM else with_urls({"kind": EVENT_KIND.get(k, k), **(
                            item if isinstance(item, dict) else {"item": item})}, base)
                        sock.send_text(json.dumps(msg, default=_json_default))
        except (OSError, ConnectionError):
            pass
        finally:
            for f in feeds.values():
                radio.unsubscribe(f)
            sock.close()
            with self.srv.lock:
                self.srv.events_sockets -= 1
            self.srv.holds.close_stream(token)

    def ws_spectrum(self, who, q):
        """spectrum/1 and overlay/1 on one WebSocket (spectrum.py; SERVER-API
        "spectrum/1"). The old wide/zoom on api/events are untouched."""
        try:
            shacklibs.spectrum()
        except shacklibs.SharedLibraryMissing as e:
            # A desktop build run with --server (recording.py NoRecordings
            # says why it carries no server-only library).
            self._error(503, _("The spectrum feed is not available in this installation: {why}").format(why=e),
                        "spectrum_unavailable")
            return
        client = self._client(q.get("client", [""])[0])
        if not ws.handshake(self):
            return
        sock = ws.Socket(self.rfile, self.wfile)
        if self.srv.test_sndbuf is not None:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.srv.test_sndbuf)
        shared = self.srv.spectrum
        if not shared.join():
            # The ninth client (§2.4): told why, as a text frame on the
            # socket it opened, then closed (1013, try again later).
            try:
                sock.send_text(json.dumps({"type": "error", "code": "busy", "message": _(
                    "{app} already serves {n} spectrum clients; try again when one has gone.").format(
                    app=self.srv.info.name, n=spectrum.MAX_CLIENTS)}))
            except (OSError, ConnectionError):
                pass
            sock.close(1013)
            return
        token, ended = self.srv.holds.open_stream(client)
        try:
            sess = spectrum.Session(self.srv.radio, sock, shared, self.srv.overlay)
            # The client's presence gone ends the session as the client
            # closing it would (`gone`); the waiter ends with the session.
            threading.Thread(target=lambda: (ended.wait(), sess.gone.set()), daemon=True,
                             name="spectrum-presence").start()
            sess.run()
        except (OSError, ConnectionError):
            pass
        finally:
            ended.set()
            shared.leave()
            sock.close()
            self.srv.holds.close_stream(token)

    def get_overlay(self, who, q):
        """overlay/1's snapshot over HTTP (CLIENT-UI-PLAN §3.1): the same
        message the socket sends on subscribe, for loHz..hiHz (default the
        wide scope's span) plus half a span either side."""
        try:
            lo = float(q["loHz"][0]) if q.get("loHz") else None
            hi = float(q["hiHz"][0]) if q.get("hiHz") else None
        except ValueError:
            lo = hi = -1.0
        if lo is None and hi is None:
            try:
                lo, hi = self.srv.radio.wide_span()
            except (AttributeError, TypeError):
                lo = hi = None          # the radio has never started: no span yet
        if lo is None or hi is None or not (0 <= lo < hi):
            self._error(400, _("loHz and hiHz must be frequencies in Hz, loHz below hiHz."), "bad_range")
            return
        # dumps without with_urls: an item's action paths stay paths, as on
        # the socket (overlay.py).
        self._send(200, dumps({"type": "overlay", "rev": 0, "op": "snapshot",
                               "items": self.srv.overlay.items(lo, hi)}))

    def get_audio_rx(self, who, q):
        """Receive audio as raw PCM over a long-lived response, its format
        in the headers (GUIDE 2: announced up front). Mono unless the
        client asks `?channels=2` (StreamAudio's docstring says why)."""
        try:
            channels = int(q.get("channels", ["1"])[0])
        except ValueError:
            channels = 0
        if channels not in CHANNELS:
            self._error(400, _("channels must be 1 or 2"), "bad_channels")
            return
        client = self._client(q.get("client", [""])[0])
        if "behind" in q:
            try:
                behind = float(q["behind"][0])
            except ValueError:
                behind = -1.0
            if not 0.0 <= behind < 1e6:
                self._error(400, _("behind must be a number of seconds, 0 or more"), "bad_behind")
                return
            if behind > 0:
                token, ended = self.srv.holds.open_stream(client)
                try:
                    self._audio_behind(channels, behind, ended)
                finally:
                    self.srv.holds.close_stream(token)
                return
        a = self.srv.audio
        fmt = a.rx_format(channels)
        silence = bytes(int(fmt["rate"] * IDLE_AUDIO_S) * 2 * channels)
        # `ended` is set when the client's presence says it has gone.
        token, ended = self.srv.holds.open_stream(client)
        lq = a.listen(channels)
        try:
            self.send_response(200)
            self.send_header("Content-Type", f"audio/L16; rate={fmt['rate']}; channels={channels}")
            self.send_header("X-Audio-Format", json.dumps(fmt))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            while not self.srv.stop_ev.is_set() and not ended.is_set():
                try:
                    pcm = lq.get(timeout=IDLE_AUDIO_S)
                except Exception:  # noqa: BLE001  queue.Empty: the engine is not playing
                    # Send that much silence. A write is the only way this
                    # thread learns the client has gone: sending nothing
                    # while the radio was stopped kept every dead listener
                    # (and its thread) for good - ohs-box showed 20 from one
                    # TV reconnecting every 7 s. Silence also keeps a client
                    # player fed, like the video stream's null packets.
                    pcm = silence
                self.wfile.write(pcm)
        except (OSError, ConnectionError):
            pass
        finally:
            a.unlisten(lq)
            self.srv.holds.close_stream(token)

    # A timeshifted stream is sent at the pace it plays, PACE_AHEAD_S ahead
    # at most: sent as fast as the network takes it, an hour behind would
    # be an hour of audio into a player that buffers what it is given, and
    # "behind" would shrink as it did.
    PACE_AHEAD_S = 1.0

    def _audio_behind(self, channels: int, behind: float, ended: threading.Event | None = None) -> None:
        """api/audio/rx?behind=: the timeshift (timeshift.py) from `behind`
        seconds ago, in the same format as live, carrying on from there in
        real time. It ends when the buffer is cleared (the station changed
        or stopped): the client goes back to live."""
        ts = self.srv.timeshift
        try:
            gen, index, ago = ts.position(behind)
        except TimeshiftGone:
            self._error(409, _("Nothing is kept to listen behind live: the timeshift keeps a DAB or wide FM "
                               "station while it plays"), "no_timeshift")
            return
        fmt = self.srv.audio.rx_format(channels)
        rate = ts.rate
        utc = ts.utc(index)
        try:
            self.send_response(200)
            self.send_header("Content-Type", f"audio/L16; rate={fmt['rate']}; channels={channels}")
            self.send_header("X-Audio-Format", json.dumps(fmt))
            # Further back than is kept is clamped, not refused: a client
            # seeking back 30 s at a time lands on the oldest audio, and is
            # told so (clamped) rather than getting an error to work round.
            self.send_header("X-Timeshift", json.dumps({
                "behindS": round(ago, 3), "clamped": ago < behind - 0.05,
                "startUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(utc)) if utc else None}))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            t0, sent = time.monotonic(), 0
            step = int(rate * 0.1)
            while not self.srv.stop_ev.is_set() and not (ended is not None and ended.is_set()):
                pcm = ts.read(gen, index, step, timeout=IDLE_AUDIO_S)
                if not len(pcm):
                    continue
                index += len(pcm)
                if channels == 1:
                    pcm = ((pcm[:, 0].astype(np.int32) + pcm[:, 1]) // 2).astype("<i2")
                self.wfile.write(pcm.astype("<i2", copy=False).tobytes())
                sent += len(pcm)
                ahead = sent / rate - (time.monotonic() - t0)
                if ahead > self.PACE_AHEAD_S:
                    self.srv.stop_ev.wait(ahead - self.PACE_AHEAD_S)
        except TimeshiftGone:
            pass
        except (OSError, ConnectionError):
            pass

    def ws_audio_tx(self, who, q):
        """A remote microphone: binary frames of PCM in MIC_FORMAT, used by PTT
        in a voice mode while this socket is open. Transmit level, like
        keying."""
        if not ws.handshake(self):
            return
        sock = ws.Socket(self.rfile, self.wfile)
        a = self.srv.audio
        a.mic_writer = who["device"]
        try:
            sock.send_text(json.dumps({"kind": "hello", "format": MIC_FORMAT}))
            while True:
                fr = sock.recv()
                if fr is None:
                    break
                op, data = fr
                if op == 0x2:
                    a.feed_mic(data)
        except (OSError, ConnectionError):
            pass
        finally:
            if a.mic_writer == who["device"]:
                a.mic_writer = ""
            sock.close()


#: Transmit routes a digital-only right also passes (CONTROLLER-CONTRACT 5.5):
#: the arm's heartbeat. Matches the manifest's `digital: true` rule, which
#: the controller enforces first. Never api/ptt's key-up or api/audio/tx.
DIGITAL_ROUTES = {("POST", "/api/ptt/heartbeat")}
# A radio given back to the station (Server.parked) is taken again by any
# request but these, which want nothing from it, and by these GETs, which
# open a stream from it.
NO_WAKE = frozenset({"/api/stop", "/api/halt", "/api/shack/release", "/api/ptt/heartbeat"})
WAKE_GETS = frozenset({"/api/audio/rx", "/api/spectrum/v1", "/api/events"})
# Feeds whose items go out under another kind's name on api/events.
EVENT_KIND = {"decoders": "decoder"}

ROUTES = {
    ("GET", "/"): ("view", _Handler.page),
    ("GET", "/api/status"): ("view", _Handler.get_status),
    ("GET", "/api/state"): ("view", _Handler.get_state),
    ("GET", "/api/spec"): ("view", _Handler.get_spec),
    ("POST", "/api/set"): ("control", _Handler.post_set),
    ("POST", "/api/start"): ("control", _Handler.post_start),
    ("POST", "/api/stop"): ("control", _Handler.post_stop),
    ("POST", "/api/ptt"): ("control", _Handler.post_ptt),
    ("POST", "/api/ptt/heartbeat"): ("transmit", _Handler.post_heartbeat),
    ("POST", "/api/autotx"): ("control", _Handler.post_autotx),
    ("POST", "/api/halt"): ("control", _Handler.post_halt),
    ("GET", "/api/cwskim"): ("view", _Handler.get_cwskim),
    ("GET", "/api/fm/stations"): ("view", _Handler.get_fm_stations),
    ("GET", "/api/dab/stations"): ("view", _Handler.get_dab_stations),
    ("GET", "/api/dab/slides"): ("view", _Handler.get_dab_slides),
    ("POST", "/api/scan"): ("control", _Handler.post_scan),
    ("GET", "/api/overpower"): ("view", _Handler.get_overpower),
    ("POST", "/api/overpower/capture"): ("control", _Handler.post_overpower_capture),
    ("GET", "/api/smeter/calibrate"): ("view", _Handler.get_smeter_cal),
    ("POST", "/api/smeter/calibrate"): ("control", _Handler.post_smeter_cal),
    ("DELETE", "/api/smeter/calibrate"): ("control", _Handler.delete_smeter_cal),
    ("GET", "/api/memories"): ("view", _Handler.get_memories),
    ("POST", "/api/recall"): ("control", _Handler.post_recall),
    ("GET", "/api/log"): ("view", _Handler.get_log),
    ("POST", "/api/log"): ("control", _Handler.post_log),
    ("GET", "/api/log.adi"): ("view", _Handler.get_adif),
    ("GET", "/api/events"): ("view", _Handler.ws_events),
    ("GET", "/api/spectrum/v1"): ("view", _Handler.ws_spectrum),
    ("GET", "/api/overlay/v1"): ("view", _Handler.get_overlay),
    ("GET", "/api/audio/rx"): ("view", _Handler.get_audio_rx),
    ("GET", "/api/audio/tx"): ("transmit", _Handler.ws_audio_tx),
    ("GET", "/api/shack/busy"): ("view", _Handler.get_shack_busy),
    ("POST", "/api/shack/pad/action"): ("control", _Handler.post_pad_action),
    ("POST", "/api/shack/release"): ("view", _Handler.post_shack_release),
    ("GET", "/api/decoders"): ("view", _Handler.get_decoders),
    ("GET", "/api/ais/session"): ("view", _Handler.get_ais_session),
    ("POST", "/api/ais/session"): ("control", _Handler.post_ais_session),
    ("DELETE", "/api/ais/session"): ("control", _Handler.delete_ais_session),
    ("GET", "/api/ais/vessels"): ("view", _Handler.get_ais_vessels),
    ("GET", "/api/adsb/session"): ("view", _Handler.get_adsb_session),
    ("POST", "/api/adsb/session"): ("control", _Handler.post_adsb_session),
    ("DELETE", "/api/adsb/session"): ("control", _Handler.delete_adsb_session),
    ("GET", "/api/adsb/aircraft"): ("view", _Handler.get_adsb_aircraft),
    ("GET", "/api/map/info"): ("view", _Handler.get_map_info),
    ("GET", "/api/map/land"): ("view", _Handler.get_map_land),
    ("GET", "/ui/v1/app"): ("view", _Handler.get_ui_app),
    ("POST", "/api/decoders/sessions"): ("control", _Handler.post_decoder_session),
    ("POST", "/api/decoders/codecs/rescan"): ("control", _Handler.post_codecs_rescan),
    ("GET", "/api/decoders/files"): ("view", _Handler.get_decoder_files),
    ("GET", "/api/recordings"): ("view", _Handler.get_recordings),
    ("GET", "/api/recordings/status"): ("view", _Handler.get_recordings_status),
    ("GET", "/api/recordings/file"): ("view", _Handler.get_recordings_file),
    ("POST", "/api/recordings/start"): ("control", _Handler.post_recordings_start),
    ("POST", "/api/recordings/stop"): ("control", _Handler.post_recordings_stop),
    ("POST", "/api/recordings/delete"): ("control", _Handler.post_recordings_delete),
    ("GET", "/api/local-frequencies"): ("view", _Handler.get_local_frequencies),
    ("POST", "/api/local-frequencies/mine"): ("control", _Handler.post_local_mine),
    # Control here; the handler also wants the administrator flag.
    ("POST", "/api/local-frequencies/refresh"): ("control", _Handler.post_local_refresh),
}
# Routes with a path parameter: (method, prefix) -> (level, handler); the
# rest of the path after the prefix is the parameter. Exact routes first.
PREFIX_ROUTES = {
    ("GET", "/api/decoders/sessions/"): ("view", _Handler.get_decoder_session),
    ("GET", "/api/ais/vessels/"): ("view", _Handler.get_ais_vessel),
    ("GET", "/api/adsb/aircraft/"): ("view", _Handler.get_adsb_one),
    ("GET", "/api/map/tiles/"): ("view", _Handler.get_map_tile),
    ("DELETE", "/api/decoders/sessions/"): ("control", _Handler.delete_decoder_session),
    ("POST", "/api/decoders/sessions/"): ("control", _Handler.post_decoder_session_params),
    ("GET", "/api/decoders/files/"): ("view", _Handler.get_decoder_file),
    ("GET", "/api/dab/slides/"): ("view", _Handler.get_dab_slide),
    ("GET", "/api/dab/logos/"): ("view", _Handler.get_dab_logo),
    ("GET", "/api/dab/schedule/"): ("view", _Handler.get_dab_schedule),
    ("GET", "/ui/v1/screen/"): ("view", _Handler.get_ui_screen),
    ("GET", "/ui/v1/data/"): ("view", _Handler.get_ui_data),
    ("PUT", "/api/local-frequencies/mine/"): ("control", _Handler.put_local_mine),
    ("DELETE", "/api/local-frequencies/mine/"): ("control", _Handler.delete_local_mine),
}
