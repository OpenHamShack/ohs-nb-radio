"""Radio's ui/1 screens (CLIENT-UI-PLAN.md §5, step 1b of §10): the app
descriptor and four screens a client draws natively - radio/home,
radio/dab, radio/fm and radio/ships - served by the shared server's
ui/v1 routes (ohscore/server/uiv1.py; docs/SERVER-API.md "ui/1 screens").
What each replaces on the Android TV, and what it leaves out, is
docs/UI-PARITY-RADIO.md.

Built with ohs-libs shack_ui, so every screen is checked against the
pinned schema, and refused if any action declared transmit, as it is made.
Receive only: every action here is an existing route at its existing
level (reads are view; tuning, DAB, the scan and the volume are control),
and no screen places ptt or enableTx.

How the closed vocabulary was made to say what the TV screens say, where
the plan is silent (each is in UI-PARITY-RADIO.md's "Judgement calls"):

- **Lists that change while the screen is open** (the ships nearest first)
  are rows bound by index into a feed (`ais.vessels.0.name`), as many as
  there are when the screen is built: ui/1 has no item template. Lists
  that change weekly (the band scan's stations) are built as they stand
  when the screen opens.
- **The DAB station playing** is behind a session id no binding can name,
  so it comes from a feed of its own, `ui/v1/data/dab` (view; `data()`
  below), and the actions that start, change and stop it use POST
  api/decoders/sessions's `replace` and `stop` (SERVER-API "DAB"), which
  need no id.
- **Sessions a native component keeps alive** (the AIS map's lease, every
  10 s, and its DELETE on close) are the native `map` component's, like the
  TV's AisLease today: a renewal loop is client code, not a document.
"""
from __future__ import annotations

from ohscore import shacklibs
from ohscore.server.uiv1 import Request, UnknownScreen
from ohsradio.i18n import _
from ohsradio.state import MODES

SCREENS = ("radio/home", "radio/dab", "radio/fm", "radio/ships")
# The ships listed beside the map: the TV's nearest panel shows about this
# many at once, and a row per ship is a row of bindings the client keeps.
SHIPS_LISTED = 12
# What the descriptor asks of a client: the ui/1 renderer. A native
# component it lacks is left out or replaced by its fallback (§5.3).
MIN_CLIENT = "1.0"
# Feeds every screen shares: the engine's state diffs and the meters on
# Radio's existing socket (two feeds so a binding names which).
STATE = "ws:api/events?kinds=state"
METER = "ws:api/events?kinds=meter"


def _ui():
    return shacklibs.ui()


def _post(path: str, body=None):
    # Every post here is control: the routes they reach are control in
    # ROUTES (ohscore/server/app.py) and the manifest, and none transmits.
    return _ui().Action.post(path, "control", body)


def _native(req: Request, name: str, fallback, *, layer: str | None = None, **props):
    """A native component, or only its fallback for a client that said
    it lacks it (§5.3). `layer` (map's `ais`) is negotiated as `map.ais`."""
    ui = _ui()
    if req.lacks(f"{name}.{layer}" if layer else name):
        return fallback
    return ui.native(name, fallback=fallback, **props)


def _needs_newer():
    return _ui().node("text", text=_("This needs a newer OpenHamShack app."))


def _audio(req: Request):
    # The receive audio player (api/audio/rx, 48 kHz; stereo when the
    # client asks ?channels=2). Muting is the player's (audio.mute), as on
    # the TV, where Mute silences the player and changes nothing on the box.
    return _native(req, "audio", _ui().node("empty", text=_("This OpenHamShack app cannot play the sound here.")),
                   path="api/audio/rx", channels=2, timeshift=True)


def _volume():
    ui = _ui()
    return ui.node("slider", label=_("Volume"), value=ui.Bind("state.volume"), min=0, max=1, step=0.05,
                   action=_post("api/set", {"volume": "$value"}))


def _mute():
    ui = _ui()
    return ui.node("button", label=_("Mute"), icon="mute", action=ui.Action.native("audio.mute"))


# ---------------------------------------------------------------- descriptor
def descriptor(srv, req: Request) -> dict:
    """GET ui/v1/app: what the launcher draws (§5.3, §6.2). One entry per
    screen a person opens from the launcher; Aircraft is left out until
    Radio serves an ADS-B screen. Icons: Radio has no PNG of its own to
    serve yet (the brand kit's are a draft awaiting Brian), so `icon` is
    null and each entry names a generic `icon` the client has."""
    info = srv.info
    ui = _ui()

    def entry(eid, title, screen, icon, text):
        return {"id": eid, "title": title, "screen": screen, "icon": icon,
                "status": {"text": ui.Bind(text).to_json(), "onAir": ui.Bind("status.onAir").to_json()}}

    return {
        "ui": ui.UI_VERSION, "app": info.app_id, "kind": info.kind, "name": _("Radio"), "version": info.version,
        "icon": None, "minClient": MIN_CLIENT, "spectrum": 1, "overlay": 1, "screens": list(SCREENS),
        # The tiles' status: api/status, every 15 s while the launcher shows.
        "data": {"status": {"src": "get:api/status", "poll": 15}},
        "status": {"text": ui.Bind("status.dialLabel.text").to_json(), "onAir": ui.Bind("status.onAir").to_json(),
                   "running": ui.Bind("status.running").to_json()},
        "entries": [
            entry("radio", _("Radio"), "radio/home", "radio", "status.dialLabel.text"),
            entry("dab", _("DAB Radio"), "radio/dab", "dab", "status.rxOwner.text"),
            entry("fm", _("FM"), "radio/fm", "fm", "status.dialLabel.text"),
            entry("ships", _("Ships"), "radio/ships", "ships", "status.ais.text"),
        ],
    }


# ---------------------------------------------------------------- screens
def screen(srv, sid: str, params: dict, req: Request) -> dict:
    build = {"radio/home": home, "radio/dab": dab, "radio/fm": fm, "radio/ships": ships}.get(sid)
    if build is None:
        raise UnknownScreen(sid)
    return build(srv, params, req).to_json()


def home(srv, params, req):
    """The landing screen: what the dial is on, now playing, the waterfall,
    tuning, the volume, and the way to DAB, FM and Ships (the TV's dial
    screen, TvEngine/TvRadioReadout/TvRadioRow)."""
    ui = _ui()
    node, Bind, Action = ui.node, ui.Bind, ui.Action
    modes = [{"value": m, "label": m.upper()} for m in MODES]
    root = node(
        "column",
        node("nowPlaying", title=Bind("state.dialLabel.text"), subtitle=Bind("state.rds.rt"),
             detail=Bind("state.rds.ps"), label=_("Now playing")),
        node("row",
             node("value", label=_("Dial"), value=Bind("state.vfo", format="freq")),
             node("chip", label=_("Mode"), text=Bind("state.mode")),
             node("meter", label=_("Signal"), value=Bind("meter.rx", format="db"), min=-140, max=0),
             focusGroup=True),
        # Who has the receiver when it is not the operator (a DAB station,
        # the ship map, the band scan): the sentence Radio already words.
        node("text", text=Bind("state.rxOwner.text"), role="warning"),
        node("text", text=Bind("state.error"), role="error"),
        _native(req, "waterfall", _needs_newer(), stream="main",
                layers=["band", "dial", "channels", "beacons", "stations", "sessions"]),
        node("row",
             node("frequencyField", label=_("Frequency"), value=Bind("state.vfo"),
                  action=_post("api/set", {"changes": {"vfo": "$value"}})),
             node("choice", label=_("Mode"), value=Bind("state.mode"), options=modes,
                  action=_post("api/set", {"changes": {"mode": "$value"}})),
             node("button", label=_("Band down"), icon="previous",
                  action=_post("api/shack/pad/action", {"action": "band", "kind": "turn", "step": -1})),
             node("button", label=_("Band up"), icon="next",
                  action=_post("api/shack/pad/action", {"action": "band", "kind": "turn", "step": 1})),
             focusGroup=True),
        node("row", _volume(), _mute(), _audio(req), focusGroup=True),
        node("row",
             node("button", label=_("DAB Radio"), icon="dab", action=Action.open("radio/dab")),
             node("button", label=_("FM"), icon="fm", action=Action.open("radio/fm")),
             node("button", label=_("Ships"), icon="ships", action=Action.open("radio/ships")),
             node("button", label=_("Start the radio"), icon="power", action=_post("api/start")),
             focusGroup=True),
    )
    return ui.Document("radio/home", root, title=_("Radio"), data={"state": STATE, "meter": METER})


def _service_detail(svc: dict) -> str:
    parts = [(svc.get("kind") or "").upper()]
    if svc.get("bitrate"):
        parts.append(_("{n} kb/s").format(n=f"{svc['bitrate']:g}"))
    if svc.get("ptyName"):
        parts.append(svc["ptyName"])
    return " · ".join(p for p in parts if p)


def dab(srv, params, req):
    """DAB: the station playing (name, programme text, slide or logo,
    ensemble, transmitters heard), the band scan's stations to choose from,
    Scan now and Stop (the TV's TvDabScreen in DabRadioUi.kt)."""
    ui = _ui()
    node, Bind = ui.node, ui.Bind
    listed = srv.radio.bandscan.view("dab")
    stations = []
    for ens in listed.get("ensembles") or []:
        tiles = [node("card",
                      node("image", src=svc.get("logoPath"), alt=svc.get("label") or svc["sid"]),
                      node("text", text=svc.get("label") or svc["sid"]),
                      node("text", text=_service_detail(svc), role="caption"),
                      action=_post("api/decoders/sessions",
                                   {"decoder": "dab", "freqHz": ens.get("freqHz"),
                                    "params": {"block": ens.get("block"), "service": svc["sid"]},
                                    "replace": True}))
                 for svc in ens.get("services") or [] if svc.get("sid")]
        if tiles:
            title = " · ".join(x for x in (ens.get("label"), ens.get("block")) if x)
            stations.append(node("section", node("grid", *tiles, columns=2), title=title))
    if not stations:
        stations = [node("empty", text=listed.get("statusText") or _("No DAB stations found yet"),
                         action=_post("api/scan", {"band": "dab"}), actionLabel=_("Scan now"))]
    root = node(
        "row",
        node("column",
             node("nowPlaying", title=Bind("dab.title"), subtitle=Bind("dab.dls"), image=Bind("dab.imagePath"),
                  detail=Bind("dab.detail"), label=_("Now playing")),
             node("text", text=Bind("dab.ensemble")),
             node("text", text=Bind("dab.whyText"), role="warning"),
             node("section", node("text", text=Bind("dab.transmittersText")), title=_("Transmitters heard")),
             node("row",
                  node("button", label=_("Stop"), icon="stop",
                       action=_post("api/decoders/sessions", {"decoder": "dab", "stop": True})),
                  node("button", label=_("Scan now"), icon="scan", action=_post("api/scan", {"band": "dab"})),
                  _volume(), _mute(), focusGroup=True),
             node("text", text=Bind("state.bandScan.text"), role="caption"),
             _audio(req)),
        node("column", *stations),
    )
    return ui.Document("radio/dab", root, title=_("DAB Radio"),
                       data={"state": STATE, "dab": {"src": "get:ui/v1/data/dab", "poll": 1}})


def _fm_name(st: dict) -> str:
    ps = (st.get("ps") or "").strip()
    return ps or _("{mhz} MHz").format(mhz=f"{(st.get('best') or {}).get('hz', 0) / 1e6:.1f}")


def _fm_tile(st: dict):
    ui = _ui()
    node = ui.node
    best = st.get("best") or {}
    kids = [node("text", text=_fm_name(st)), node("value", value=best.get("hz"), format="freq")]
    if st.get("ptyName"):
        kids.append(node("text", text=st["ptyName"], role="caption"))
    if best.get("stereo"):
        kids.append(node("badge", text=_("Stereo")))
    return node("card", *kids, action=_post("api/set", {"changes": {"vfo": best.get("hz"), "mode": "wfm"}}))


def fm(srv, params, req):
    """FM: RDS now playing, the band scan's stations by frequency and A-Z,
    tune by frequency, Scan now (the TV's TvFmScreen in RadioStations.kt
    and the readout's RDS lines in TvRadio.kt)."""
    ui = _ui()
    node, Bind = ui.node, ui.Bind
    listed = srv.radio.bandscan.view("fm")
    rows = [s for s in listed.get("stations") or [] if (s.get("best") or {}).get("hz")]
    if rows:
        by_freq = node("grid", *[_fm_tile(s) for s in rows], columns=2)
        by_name = node("grid", *[_fm_tile(s) for s in sorted(rows, key=lambda s: _fm_name(s).lower())], columns=2)
        stations = node("tabs", node("section", by_freq, title=_("By frequency")),
                        node("section", by_name, title=_("A-Z")))
    else:
        stations = node("empty", text=listed.get("statusText") or _("No FM stations found yet"),
                        action=_post("api/scan", {"band": "fm"}), actionLabel=_("Scan now"))
    root = node(
        "row",
        node("column",
             node("nowPlaying", title=Bind("state.rds.ps"), subtitle=Bind("state.rds.rt"),
                  detail=Bind("state.rds.ptyName"), label=_("Now playing")),
             node("row",
                  node("value", label=_("Dial"), value=Bind("state.vfo", format="freq")),
                  node("badge", text=_("Stereo"), on=Bind("meter.stereo")),
                  node("badge", text=_("Traffic"), on=Bind("state.rds.tp")),
                  focusGroup=True),
             node("text", text=Bind("state.rxOwner.text"), role="warning"),
             node("row",
                  node("frequencyField", label=_("Tune by frequency"), value=Bind("state.vfo"),
                       action=_post("api/set", {"changes": {"vfo": "$value", "mode": "wfm"}})),
                  node("button", label=_("Scan now"), icon="scan", action=_post("api/scan", {"band": "fm"})),
                  _volume(), _mute(), focusGroup=True),
             node("text", text=Bind("state.bandScan.text"), role="caption"),
             _audio(req)),
        stations,
    )
    return ui.Document("radio/fm", root, title=_("FM"), data={"state": STATE, "meter": METER})


def ships(srv, params, req):
    """Ships: the AIS map as the native map component with its `ais` layer
    (§5.4), and the nearest ships beside it (the TV's ShipsScreen, on
    openhamshack-remote feature/ships). The map component keeps the AIS
    session alive (POST api/ais/session every 10 s, DELETE on close), draws
    the bundled land, the tiles and the ships, and owns the D-pad modes;
    the side sheet is what any client can show of the table."""
    ui = _ui()
    node, Bind = ui.node, ui.Bind
    have = len(srv.radio.ais.table.view()["vessels"]) if getattr(srv.radio, "ais", None) is not None else 0
    rows = [node("card",
                 node("text", text=Bind(f"ais.vessels.{i}.name")),
                 node("text", text=Bind(f"ais.vessels.{i}.shipTypeText"), role="caption"),
                 node("value", value=Bind(f"ais.vessels.{i}.distanceKm", format="distance")),
                 action=ui.Action.local("map.ais.selected", Bind(f"ais.vessels.{i}.mmsi").to_json()))
            for i in range(min(have, SHIPS_LISTED))]
    listing = node("list", *rows) if rows else node("empty", text=_("No ships heard yet: they appear within a "
                                                                      "minute of the map opening."))
    fallback = node("column", _needs_newer(), node("text", text=Bind("ais.session.text")))
    themap = _native(req, "map", fallback, layer="ais", layers=["ais"],
                     info="api/map/info", land="api/map/land", tiles="api/map/tiles/{z}/{x}/{y}.png",
                     ais={"session": "api/ais/session", "vessels": "api/ais/vessels",
                          "vessel": "api/ais/vessels/{mmsi}", "events": "api/events?kinds=ais", "renewS": 10})
    root = node(
        "row",
        themap,
        node("sheet",
             node("text", text=Bind("ais.session.text")),
             node("text", text=Bind("state.rxOwner.text"), role="warning"),
             listing,
             title=_("Nearest ships")),
    )
    return ui.Document("radio/ships", root, title=_("Ships"),
                       data={"state": STATE, "ais": {"src": "get:api/ais/vessels", "poll": 10}})


# ---------------------------------------------------------------- data feeds
def data(srv, name: str, req: Request) -> dict:
    if name == "dab":
        return dab_now(srv.radio)
    raise UnknownScreen(name)


def _transmitter_line(t: dict) -> str:
    where = t.get("site") or _("Unknown transmitter {main}/{sub}").format(main=t.get("main"), sub=t.get("sub"))
    if t.get("distanceKm") is not None:
        return _("{site}, {km} km, {db} dB").format(site=where, km=f"{t['distanceKm']:.0f}",
                                                   db=f"{t.get('levelDb') or 0:g}")
    return _("{site}, {db} dB").format(site=where, db=f"{t.get('levelDb') or 0:g}")


def dab_now(radio) -> dict:
    """GET ui/v1/data/dab: the DAB station playing, flat enough to bind to
    (the session's own view, GET api/decoders/sessions/{id}, is behind an
    id). `playing` false and the rest null while none plays."""
    d = radio.decoders
    sid = d.held_by("dab")
    sess = d.session(sid) if sid else None
    if not sess:
        return {"playing": False, "session": None, "block": None, "title": _("Not playing"), "dls": None,
                "detail": None, "ensemble": None, "imagePath": None, "why": None, "whyText": "",
                "transmitters": [], "transmittersText": ""}
    meta = sess.get("meta") or {}
    # The station asked for, before the one the decoder last reported: a
    # change of station is shown at once, its name and logo with it, while
    # the decoder takes a moment to switch (its programme text follows).
    playing = (sess.get("params") or {}).get("service") or meta.get("playing")
    svc = next((s for s in meta.get("services") or [] if s.get("sid") == playing), {}) if playing else {}
    slide = meta.get("slide") or {}
    image = None
    if slide.get("path") and slide.get("sid") == playing:
        image = f"{slide['path']}?rev={slide.get('rev', 0)}"
    elif svc.get("logoPath"):
        image = svc["logoPath"]
    ens = meta.get("ensemble") or {}
    tx = meta.get("transmitters") or []
    return {"playing": True, "session": sid, "block": sess.get("block"), "service": playing,
            "title": svc.get("label") or sess.get("block"), "dls": meta.get("dls"), "detail": _service_detail(svc),
            "ensemble": " · ".join(x for x in (ens.get("label"), sess.get("block")) if x) or None,
            "imagePath": image, "why": meta.get("why") or sess.get("why"),
            "whyText": meta.get("whyText") or sess.get("whyText") or "",
            "transmitters": tx, "transmittersText": "\n".join(_transmitter_line(t) for t in tx)}
