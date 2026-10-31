"""ui/2 routes: server-driven screens (openhamshack docs/contract/SCREENS.md;
docs/SERVER-API.md "ui/2 screens"), built with ohs-libs shack_ui v2.

    GET  ui/v2/app                 the app's launcher entries (§1)
    GET  ui/v2/status              each entry's tile status (§1)
    GET  ui/v2/screen/<id>[?...]   one screen document: 200 + ETag, 304, 406 (§2)
    GET  ui/v2/live/<id>[?...]     its live socket: hello, snap, patch frames (§4)
    GET  ui/v2/poll/<id>[?...]     a polled screen's ops (§4.5)
    POST/DELETE ui/v2/hold/<name>  an app's own hold, for one no API route
                                   can name by client (§6; Radio's DMR)

The shared server only serves them; what the screens say is the app's
(AppInfo.screens, an object with the functions below; ohsradio/screens/
for Radio). An app without screens answers 404 on every ui/v2 path.

    descriptor(srv, req) -> dict            ui/v2/app
    status(srv, req) -> dict                ui/v2/status
    build(srv, sid, params, req) -> Screen  raises UnknownScreen
    poll(srv, sid, params, req) -> dict     raises UnknownScreen for a screen that is not polled
    opened(srv, sid, params, channel)       once, when a live channel is made (on_select hooks)
    feed(srv, sid, params, channel)         bring a channel up to date from the radio
    hold(srv, name, method, body, q, client) -> (status, dict) or a shack_ui Response
    gone(srv, client)                       presence says the client went (Holds.gone)

**One channel per screen and its parameters.** A client compares the
socket's `hello` rev with the rev of the document it holds (§4.1), and
that rev hashes the form, level and language too. So the socket builds
the client's document again from the same request and hands it to the
hub (`serve_blocking(..., document=)`), which registers it as one more
variant of the channel and greets the client with its rev; the live data
is shared by every variant. A document never carries live data: its
collections start empty and the socket's snap fills them, since a rev
that moved with every aircraft would have the client refetch for ever.

**The pump.** The radio's tables (aircraft, ships, stations) already keep
themselves; a screen's `feed` copies what a client should see into its
channel, field by field, and LiveHub sends only what changed, at each
client's maxHz, latest wins (shack_ui live.py). A pump thread calls each
feed every PUMP_S while the channel has a client, so the app needs no
hook in every table: a table that changes nothing costs one comparison
per field and no frame. It runs only while some channel has a client.

**Presence.** A live socket is a stream like api/events: it is registered
under the client's id (`X-OpenHamShack-Client`), so the client's going
closes it, and opening one takes back a radio given back to the station
(app.py WAKE). Weather Sats is polled, never a socket, so it wakes and
holds nothing.

The level shack_ui reads from `X-OpenHamShack-Level` is replaced by the
one the proxy check already established (`who`), so a document's `level`
is never a header the app has not authenticated.
"""
from __future__ import annotations

import dataclasses
import logging
import re
import socket
import threading
from urllib.parse import urlencode, urlsplit

from .. import shacklibs
from ..i18n.text import _
from . import ws

log = logging.getLogger("ohscore.server.uiv2")

PREFIX = "/ui/v2/"
# How often a channel with a client is brought up to date. A client asks
# at most 2 frames a second (1 on a TV, SCREENS.md §4.3), so twice a
# second is as fresh as any client can show.
PUMP_S = 0.5
SCREEN_ID_RE = re.compile(r"^[a-z0-9-]+(?:/[a-z0-9-]+)+$")
HOLD_RE = re.compile(r"^[a-z0-9-]+$")


class UnknownScreen(LookupError):
    """No screen by that id, or none that answers this way (404)."""


def request(handler, who: dict):
    """shack_ui's Req for this request (raises shack_ui.Unsupported for a
    client of another ui major), with the level and transmit right the
    proxy check gave rather than the header's."""
    ui = shacklibs.ui()
    req = ui.Req.from_headers(handler.headers)
    return dataclasses.replace(req, level=who.get("level", "view"), transmit=who.get("transmit") or "none")


def params_of(q: dict) -> dict[str, str]:
    """A screen's parameters from the query: one value each, the first."""
    return {k: v[0] for k, v in sorted(q.items()) if v}


def channel_name(sid: str, params: dict) -> str:
    return f"{sid}?{urlencode(sorted(params.items()))}"


class Live:
    """One per Server: the LiveHub, which channel belongs to which screen,
    and the pump that keeps the channels with clients current."""

    def __init__(self, srv, pump_s: float = PUMP_S):
        self.srv = srv
        self.pump_s = pump_s
        self._hub = None
        self.lock = threading.Lock()
        self.screens: dict[str, tuple[str, dict]] = {}     # channel name -> (sid, params)
        self._pump: threading.Thread | None = None
        self._wake = threading.Event()

    @property
    def hub(self):
        # Made on first use: a desktop form run with --server carries no
        # shack_ui (it is the store form's), and must still start.
        if self._hub is None:
            self._hub = shacklibs.ui().LiveHub()
        return self._hub

    def channel(self, sid: str, params: dict, doc: dict):
        """The channel for this screen, made, hooked and fed the first time
        it is asked for; `doc` is added as a variant either way (shack_ui
        never re-seeds a channel that exists)."""
        name = channel_name(sid, params)
        screens = self.srv.info.screens
        with self.lock:
            new = name not in self.screens
            ch = self.hub.channel(name, document=doc)
            self.screens[name] = (sid, dict(params))
        if new:
            screens.opened(self.srv, sid, params, ch)
            self.feed(name)
        return name, ch

    def feed(self, name: str) -> None:
        sid, params = self.screens[name]
        try:
            self.srv.info.screens.feed(self.srv, sid, params, self.hub.channel(name))
        except Exception:  # noqa: BLE001 - one screen's fault must not stop the others' frames
            log.exception("ui/2 feed for %s", sid)

    def busy(self) -> list[str]:
        with self.lock:
            names = list(self.screens)
        return [n for n in names if self.hub.channel(n).sessions]

    def start_pump(self) -> None:
        with self.lock:
            self._wake.set()
            if self._pump is not None and self._pump.is_alive():
                return
            self._pump = threading.Thread(target=self._run, name="ui2-pump", daemon=True)
            self._pump.start()

    def _run(self) -> None:
        stop = self.srv.stop_ev
        while not stop.is_set():
            names = self.busy()
            if not names:
                # Nobody is watching: sleep until a socket opens.
                self._wake.clear()
                if not self.busy():
                    self._wake.wait(timeout=5.0)
                continue
            for name in names:
                self.feed(name)
            stop.wait(self.pump_s)


# ---------------------------------------------------------------- handlers
def _send(handler, resp) -> None:
    """A shack_ui Response, as it is: never through app.py's with_urls,
    which would put an absolute `url` beside each path (SCREENS.md §11:
    every path relative)."""
    if resp.status == 304:
        handler.send_response(304)
        for k, v in resp.headers.items():
            handler.send_header(k, v)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    handler._send(resp.status, resp.body, resp.headers.get("Content-Type", "application/json"),
                  extra={k: v for k, v in resp.headers.items() if k != "Content-Type"})


def _not_found(handler, path: str) -> None:
    handler._error(404, _("There is nothing at {path}").format(path=path), "not_found")


def serve_get(handler, who: dict, q: dict) -> None:
    """Every GET under ui/v2/ (app.py PREFIX_ROUTES, view level)."""
    ui = shacklibs.ui()
    srv = handler.srv
    path = urlsplit(handler.path).path.rstrip("/")
    screens = srv.info.screens
    if screens is None:
        handler._error(404, _("This app serves no screens."), "not_found")
        return
    try:
        req = request(handler, who)
    except ui.Unsupported as e:
        _send(handler, ui.serve.unsupported_response(e.asked))
        return
    rest = path[len(PREFIX):]
    kind, _sep, sid = rest.partition("/")
    params = params_of(q)
    if kind == "app" and not sid:
        _send(handler, ui.serve_json(screens.descriptor(srv, req)))
    elif kind == "status" and not sid:
        _send(handler, ui.serve_json(screens.status(srv, req)))
    elif kind in ("screen", "live", "poll") and SCREEN_ID_RE.match(sid):
        try:
            if kind == "screen":
                _send(handler, ui.serve_document(handler.headers, lambda _r: screens.build(srv, sid, params, req)))
            elif kind == "poll":
                _send(handler, ui.serve_json(screens.poll(srv, sid, params, req)))
            else:
                _live(handler, sid, params, req)
        except UnknownScreen:
            handler._error(404, _("There is no screen called {id}").format(id=sid), "unknown_screen")
    else:
        _not_found(handler, path)


def _live(handler, sid: str, params: dict, req) -> None:
    srv = handler.srv
    doc = srv.info.screens.build(srv, sid, params, req).json()
    if "live" not in doc:
        raise UnknownScreen(sid)
    client = handler._client(handler.headers.get("X-OpenHamShack-Client") or None)
    if not ws.handshake(handler):
        return
    sock = ws.Socket(handler.rfile, handler.wfile)
    live = srv.ui_live
    name, _ch = live.channel(sid, params, doc)
    token, gone = srv.holds.open_stream(client)
    done = threading.Event()

    def presence_gone():
        # The client's presence went: end the socket as its closing would.
        # shutdown() makes the blocked read return; the hub then cleans up.
        while not gone.wait(1.0):
            if done.is_set():
                return
        try:
            handler.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    threading.Thread(target=presence_gone, daemon=True, name="ui2-presence").start()
    live.start_pump()
    try:
        live.hub.serve_blocking(sock, name, dataclasses.replace(req, client=client or req.client), document=doc)
    finally:
        done.set()
        sock.close()
        srv.holds.close_stream(token)


def serve_hold(handler, who: dict, q: dict) -> None:
    """POST and DELETE ui/v2/hold/<name> (control): an app's own hold."""
    srv = handler.srv
    path = urlsplit(handler.path).path.rstrip("/")
    name = path[len(PREFIX + "hold/"):]
    screens = srv.info.screens
    if screens is None or not HOLD_RE.match(name):
        _not_found(handler, path)
        return
    body = handler._body() if handler.command == "POST" else {}
    client = handler._client((q.get("client") or [None])[0] or body.get("client"))
    try:
        ans = screens.hold(srv, name, handler.command, body, params_of(q), client)
    except UnknownScreen:
        _not_found(handler, path)
        return
    if hasattr(ans, "body"):
        _send(handler, ans)         # shack_ui Holds.answer's Response (a NamedTuple, so first)
    else:
        handler._send(*ans)
