"""Radio's ui/2 screens (openhamshack docs/contract/SCREENS.md, step 5 of
§16): the launcher entries, their tile status, and every screen a client
draws - home, DAB, FM, Ships, Aircraft, Weather Sats and its picture
viewer, APRS, Sondes and DMR - served by the shared server's ui/v2 routes
(ohscore/server/uiv2.py, which says how the routes, channels and the pump
work; docs/SERVER-API.md "ui/2 screens"). What each replaces on the
Android TV is docs/UI-PARITY-RADIO.md.

Built with ohs-libs shack_ui v2, so every document passes the contract's
rules (shack_ui check.py, the rules the vectors pin and every renderer
enforces) as it is served. Receive only: no screen places ptt or txArm,
and every call is an existing route at its existing level (reads view;
tuning, DAB, the scan, the volume, the map sessions, Weather Sats'
record and skip, DMR's hold control).

**Documents are static; the socket carries the radio.** A document holds
the screen's shape and nothing that changes while it is open: collections
start empty and each patched part starts with its placeholder. The live
socket's snap fills them a moment later. uiv2.py says why: a document's
rev is its ETag and the socket's hello, and must not move with every
aircraft. Station lists that change weekly (the band scan's) go over the
socket too, for the same reason.

**Holds as the TV holds today** (SCREENS.md §6). Ships, Aircraft, APRS
and Sondes hold their receiver session by client id (`api/<x>/session`,
`{"client": $client}`), under the names presence already renews
(`ais`, `adsb`, `aprs`, `sonde`: SERVER-API "Client presence"). DMR holds
a decoder session on its channel through ui/v2/hold/dmr (dmr.py says why
it needs a route of its own). DAB holds nothing while open: a station
plays when a tile is pressed, under the client's id, and presence ends it
when the client goes, as on the TV. Home, FM and Weather Sats hold
nothing; Weather Sats is polled and never opens a socket.
"""
from __future__ import annotations

from ohscore.server.uiv2 import UnknownScreen

from ohsradio.i18n import _

from . import dmr, listen, traffic, wxsat
from .common import ui

# The screens by id: (builder, feed or None, poller or None).
SCREENS = {
    "radio/home": (listen.home, listen.feed_home, None),
    "radio/fm": (listen.fm, listen.feed_fm, None),
    "radio/dab": (listen.dab, listen.feed_dab, None),
    "radio/ships": (traffic.ships, traffic.feed_ships, None),
    "radio/aircraft": (traffic.aircraft, traffic.feed_aircraft, None),
    "radio/aprs": (traffic.aprs, traffic.feed_aprs, None),
    "radio/sonde": (traffic.sondes, traffic.feed_sondes, None),
    "radio/dmr": (dmr.screen, dmr.feed, None),
    "radio/wxsat": (wxsat.screen, None, wxsat.poll),
    "radio/wxsat/viewer": (wxsat.viewer, None, None),
}
# What the descriptor asks of a client: the ui/2 renderer.
MIN_CLIENT = "2.0"


def _entry(eid, title, screen, icon, forms=("tv", "phone", "tablet")):
    return ui().entry(eid, title, screen, icon=icon, forms=list(forms))


def descriptor(srv, req) -> dict:
    """GET ui/v2/app: the launcher's tiles for Radio, in order (§1). The
    maps are TV and tablet only, as today's map screens are TV-only
    (SCREENS.md §8.1). No `art` yet: Radio serves no tile pictures of its
    own, so each entry names an icon from the client's set."""
    info = srv.info
    entries = [
        _entry("radio", _("Radio"), "radio/home", "radio"),
        _entry("dab", _("DAB Radio"), "radio/dab", "dab"),
        _entry("fm", _("FM"), "radio/fm", "fm"),
        _entry("ships", _("Ships"), "radio/ships", "ship", ("tv", "tablet")),
        _entry("aircraft", _("Aircraft"), "radio/aircraft", "aircraft", ("tv", "tablet")),
        _entry("wxsat", _("Weather Sats"), "radio/wxsat", "satellite"),
        _entry("aprs", _("APRS"), "radio/aprs", "aprs", ("tv", "tablet")),
        _entry("sonde", _("Sondes"), "radio/sonde", "balloon", ("tv", "tablet")),
        _entry("dmr", _("DMR"), "radio/dmr", "dmr"),
    ]
    entries = [e for e in entries if e["id"] not in _absent(srv)]
    return ui().descriptor(entries, min_client=MIN_CLIENT, app=info.app_id, kind=info.kind, name=_("Radio"),
                           version=info.version)


def _absent(srv) -> set[str]:
    """Entries this Radio cannot open: a feature its build lacks."""
    radio = srv.radio
    out = set()
    for eid, attr in (("ships", "ais"), ("aircraft", "adsb"), ("aprs", "aprs"), ("sonde", "sonde"),
                      ("wxsat", "wxsat")):
        if getattr(radio, attr, None) is None:
            out.add(eid)
    return out


def status(srv, req) -> dict:
    """GET ui/v2/status: one line and a tone per tile (§1), polled by the
    platform while a launcher shows."""
    st = srv.radio.state()
    owner = st.get("rxOwner") or {}
    dial = (st.get("dialLabel") or {}).get("text") if isinstance(st.get("dialLabel"), dict) else None
    out = {}
    if not st.get("running"):
        out["radio"] = (_("Stopped"), "muted")
    elif st.get("keyed"):
        out["radio"] = (_("On the air"), "onAir")
    else:
        out["radio"] = (dial or listen.freq_text(st.get("vfo"), st.get("mode")), "good")
    if owner.get("by") == "dab":
        out["dab"] = (owner.get("text") or _("Playing"), "accent")
    if st.get("mode") == "wfm" and st.get("running"):
        rds = st.get("rds") or {}
        out["fm"] = ((rds.get("ps") or "").strip() or listen.freq_text(st.get("vfo"), "wfm"), "accent")
    for eid, key in (("ships", "ais"), ("aircraft", "adsb"), ("aprs", "aprs"), ("sonde", "sonde")):
        v = st.get(key) or {}
        if v.get("state") not in (None, "idle"):
            out[eid] = (v.get("text") or "", "accent")
    w = getattr(srv.radio, "wxsat", None)
    if w is not None:
        v = w.status_view()
        if v.get("state") in ("recording", "decoding", "waiting"):
            out["wxsat"] = (v.get("text") or "", "onAir" if v["state"] == "recording" else "default")
    n = dmr.running(srv.radio)
    if n:
        out["dmr"] = (n, "accent")
    return ui().status(out)


def _spec(sid: str):
    spec = SCREENS.get(sid)
    if spec is None:
        raise UnknownScreen(sid)
    return spec


def build(srv, sid: str, params: dict, req):
    """GET ui/v2/screen/<sid>: the Screen (validated and turned to JSON by
    the route, through shack_ui serve_document)."""
    builder = _spec(sid)[0]
    if sid in ("radio/ships", "radio/aircraft", "radio/aprs", "radio/sonde") and \
            getattr(srv.radio, traffic.SERVICE[sid], None) is None:
        raise UnknownScreen(sid)
    return builder(srv, params, req)


def poll(srv, sid: str, params: dict, req) -> dict:
    poller = _spec(sid)[2]
    if poller is None:
        raise UnknownScreen(sid)
    return poller(srv, params, req)


def opened(srv, sid: str, params: dict, channel) -> None:
    """A live channel was made: hooks for what only one client needs."""
    if sid == "radio/aircraft":
        traffic.hook_aircraft(srv, channel)


def feed(srv, sid: str, params: dict, channel) -> None:
    fn = _spec(sid)[1]
    if fn is not None:
        fn(srv, params, channel)


def hold(srv, name: str, method: str, body: dict, params: dict, client):
    if name == "dmr":
        return dmr.hold(srv, method, body, params, client)
    if name == "dmr-listen":
        return dmr.listen(srv, method, body, client)
    raise UnknownScreen(name)


def gone(srv, client: str) -> list[str]:
    """Presence says `client` went: the holds shack_ui keeps for it end."""
    return [f"screen hold {n}" for n in dmr.holds(srv).gone(client)]
