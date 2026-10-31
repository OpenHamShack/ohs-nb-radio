"""The maps: Aircraft (ADS-B), Ships (AIS), APRS and Sondes.

One shape for all four, Aircraft's (the contract's worked example,
SCREENS.md §12, as ohs-libs examples/radio_aircraft.py builds it): the
map full-bleed with the box's ground, the station and the traffic with
fading trails; a header of filter chips, the session's state and the
clock; the nearest (or newest) panel; a details panel for the selected
item that Left/Right steps through; a menu of view choices kept per
device (`local`). Filters are tags on each item, so hiding a band or a
kind costs the box nothing.

Each holds its receiver session while open, by the client's id, under the
name presence renews (`adsb`, `ais`, `aprs`, `sonde`). The start waits for
the receiver to reopen at the session's rate, hence 30 s (SERVER-API
"ADS-B"). A refused start's error carries the remedies the TV's refusal
cards offer (Stop decoders, Stop DAB), which the client draws on its hold
banner (§6).

Items are worded here, in the box's language: the client formats nothing
but the ticking "heard ... ago" (§2.1, D4). Trails grow a point at a time
as an item moves (common.sync), at most 30, as the TV keeps them.
"""
from __future__ import annotations

from ohsradio.i18n import _

from .common import OSM, WORDS, dist_text, nm_text, place, station, station_layer, sync, ui

# The receiver session each map holds, by screen: its route and presence name.
SERVICE = {"radio/aircraft": "adsb", "radio/ships": "ais", "radio/aprs": "aprs", "radio/sonde": "sonde"}


def _hold(s, name: str) -> None:
    A = ui().A
    s.hold(name, start=A.post(f"api/{name}/session", {"client": A.CLIENT}, level="control", timeout_s=30),
           stop=A.delete(f"api/{name}/session?client={{$client}}", level="control"))


def _hidden(key: str, tag: str, shown: bool = True) -> dict:
    """A menu toggle over the hide set: lit while the tag is *not* hidden."""
    return ui().local(key, [], has=tag, not_=shown)


def _toggle(key: str, text: str, tag: str, tone: str | None = None, shown: bool = True) -> dict:
    p, A = ui().p, ui().A
    return p.toggle(text, _hidden(key, tag, shown), A.local(key, toggle=tag), **({"tone": tone} if tone else {}))


def _stepper(text: str, key: str, default, options) -> dict:
    p, A = ui().p, ui().A
    return p.choice([p.option(v, t) for v, t in options], ui().local(key, default), A.local(key, set=A.VALUE),
                    style="stepper", text=text)


def _forget(key: str, default=None) -> dict:
    return _stepper(_("Forget after"), key, default, [
        (None, _("Radio's setting")), (60, _("1 min")), (180, _("3 min")), (300, _("5 min")), (600, _("10 min")),
        (1800, _("30 min"))])


def _shape(srv, req, sid: str, title: str, coll: str, *, symbols, colors: dict, chips: list[dict], hide_key: str,
           row: dict, details: list[dict], menu: list[dict], empty: str, empty_icon: str, list_title: str,
           layers: list[dict] = (), trails: bool = True, labels=None, more_collections=(), keys: dict | None = None):
    """The map screen every traffic kind shares (module docstring)."""
    u = ui()
    p, A, T = u.p, u.A, u.T
    s = u.Screen(sid, title=title, req=req)
    s.backdrop("plain")
    s.words(WORDS)
    s.colors(colors)
    s.symbols(symbols + u.Symbols.load("station"))
    s.collection(coll, filter={"hide": u.local(hide_key, []), "maxAgeS": u.local(f"{SERVICE[sid]}.forgetS", None)})
    for c in more_collections:
        s.collection(c)
    s.selection(coll, from_=coll)
    _hold(s, SERVICE[sid])
    s.live(f"ui/v2/live/{sid}")
    s.key("menu", A.show("menu", hint=_("Menu")))
    s.key("play", A.part("map", "fit", hint=_("Show all")))
    s.key("chUp", A.part("map", "zoomIn", hint=_("Zoom")))
    s.key("ff", A.part("map", "zoomIn"))
    s.key("chDown", A.part("map", "zoomOut"))
    s.key("rew", A.part("map", "zoomOut"))
    style = SERVICE[sid] + ".style"
    traffic = p.layer(coll, "markers", from_=coll, selection=coll, labels=labels or u.local(f"{SERVICE[sid]}.labels",
                                                                                            "all"),
                      **({"trails": {"fade": True, "width": 2.5}} if trails else {}))
    the_map = p.map(
        "map", align="fill",
        ground={"tiles": "api/map/tiles/{z}/{x}/{y}.png", "land": "api/map/land", "zoom": [3, 14],
                "style": u.local(style, "real")},
        attribution=OSM,
        view={"fit": "layers", "minKm": 60, "maxKm": 600, "free": "start"},
        follow={"zoom": 10}, back=A.focus("nearest"),
        keys={"ok": A.part("map", "selectCentre", hint=_("Choose"))},
        layers=[station_layer(srv.radio), *layers, traffic])
    header = p.row(
        p.choice(chips, u.local(hide_key, []), A.local(hide_key, set=A.VALUE), id="chips", style="chips", multi=True,
                 inverted=True),
        p.spacer(weight=1),
        p.badge("", id="emergency", style="pill", tone="emergency", hidden=True),
        p.badge(_("Starting"), id="status", style="dot", tone="warn"),
        p.text(T.clock("local", "hm"), style="numeric", size="l"),
        id="header", align="top-fill", h=72, pad="m", gap="m", surface="scrim")
    nearest = p.panel("nearest", p.column(
        p.text(list_title, style="caption", tone="muted"),
        p.text("", id="count", style="title", size="m"),
        p.text("", id="session", tone="muted", lines=2),
        p.list("list", from_=coll, selection=coll, weight=1, keep_focus=True, focus={"initial": True},
               on_activate=A.show("details", hint=_("Details")), empty=p.empty(empty, icon=empty_icon), template=row),
        gap="s"),
        slot="end", w=300, open=True, surface="glass", back=A.part("map", "fit"),
        keys={"left": A.focus("map", hint=_("Map"))})
    detail = p.panel("details", p.scroll(p.column(*details, gap="s")), slot="end", w=375, for_=coll, step=True,
                     surface="glass", keys=keys or {})
    menu_panel = p.panel("menu", p.column(
        *menu,
        p.text(_("Map"), style="caption", tone="muted"),
        # The zoom keys' on-screen route (SCREENS §8.2: a key is a shortcut,
        # never the only way; a Siri Remote has no chUp/chDown/rew/ff).
        p.row(p.button(_("Zoom in"), A.part("map", "zoomIn"), style="quiet"),
              p.button(_("Zoom out"), A.part("map", "zoomOut"), style="quiet"),
              p.button(_("Show all"), A.part("map", "fit"), style="quiet"), gap="s"),
        _stepper(_("Style"), style, "real", [("real", _("Real")), ("night", _("Night"))]),
        _stepper(_("Labels"), f"{SERVICE[sid]}.labels", "all", [("all", _("All")), ("none", _("Off"))]),
        _forget(f"{SERVICE[sid]}.forgetS"),
        gap="s"),
        slot="end", w=315, surface="glass")
    s.root = p.stack(the_map, header, nearest, detail, menu_panel, p.hints(id="hints", align="bottom-start",
                                                                            style="pills"))
    return s


def _grid(*fields: dict) -> dict:
    return ui().p.grid(*fields, columns={"tv": 2, "tablet": 2, "phone": 2}, gap="s")


def _row(sym: bool = True) -> dict:
    """A list row: tone bar (or symbol), title and route, second line, distance."""
    u = ui()
    p, item = u.p, u.item
    lead = p.icon(sym=item("sym"), tone=item("tone"), size="m") if sym else p.badge(style="pill", tone=item("tone"),
                                                                                     w=9, h=27)
    return p.row(
        lead,
        p.column(p.row(p.text(item("title"), style="title", size="m", lines=1),
                       p.text(item("routeText"), tone="accent", lines=1), gap="xs"),
                 p.text(item("line2"), tone="muted", lines=1),
                 p.badge(item("emergencyText"), style="pill", tone="emergency"),
                 weight=1),
        p.text(item("distText"), style="numeric", tone="muted"),
        gap="s", pad="s")


def _status(ch, view: dict, n: int, one: str, many: str) -> None:
    """The header's dot and the panel's count and sentence, from the session view."""
    state = view.get("state")
    tone = {"running": "good", "tracking": "good", "scanning": "accent", "idle": "muted"}.get(state, "warn")
    # The header's chip says one word, as the old app's RECEIVING did: the
    # session's sentence ("Listening to AIS on 161.975 and ...") ran off the
    # right edge of a TV there, and is the panel's to say in full.
    word = {"running": _("Receiving"), "tracking": _("Receiving"), "scanning": _("Scanning"),
            "idle": _("Stopped")}.get(state, _("Starting"))
    ch.set("status", text=word, tone=tone)
    ch.set("count", value=(one if n == 1 else many).format(n=n))
    ch.set("session", value=view.get("text") or "")


# ---------------------------------------------------------------- Aircraft
BANDS = [  # tag, colour name, dark, light, upper bound (ft), chip, menu row
    ("band:low", "band.low", "#FF9F43", "#B8610F", 5_000),
    ("band:lower", "band.lower", "#FFD54F", "#9A7A00", 15_000),
    ("band:middle", "band.middle", "#57E39B", "#1E8A55", 25_000),
    ("band:upper", "band.upper", "#4FC3FF", "#0A6FA8", 35_000),
    ("band:top", "band.top", "#C08BFF", "#7B3FC4", None),
]


def _band_words() -> dict:
    return {"band:low": (_("Low"), _("Below 5,000 ft")), "band:lower": (_("Lower"), _("5,000 to 15,000 ft")),
            "band:middle": (_("Middle"), _("15,000 to 25,000 ft")), "band:upper": (_("Upper"), _("25,000 to 35,000 ft")),
            "band:top": (_("Top"), _("35,000 ft and above"))}


def _kinds() -> list[tuple[str, str]]:
    return [("kind:light", _("Light")), ("kind:airliner", _("Airliner")), ("kind:heavy", _("Heavy")),
            ("kind:rotor", _("Rotor")), ("kind:other", _("Other"))]


def aircraft(srv, params, req):
    """Aircraft (the TV's TrafficScreen and AircraftUi): the contract's
    worked example on Radio's own table. The photo, from Planespotters by
    their terms, goes only to the client that selected the aircraft
    (hook_aircraft)."""
    u = ui()
    p, A, T, item = u.p, u.A, u.T, u.item
    words = _band_words()
    colors = {name: {"dark": dark, "light": light} for _t, name, dark, light, _u in BANDS}
    colors["band.ground"] = {"dark": "#B8C4CF", "light": "#5E6B77"}
    colors["band.none"] = {"dark": "#8FA3B3", "light": "#5A6E7E"}
    chips = [p.option(tag, words[tag][0], tone=name) for tag, name, *_r in BANDS]
    chips.append(p.option("ground", _("Ground"), tone="band.ground"))
    details = [
        p.row(p.icon(sym=item("sym"), tone=item("tone"), size="xl", surface="card"),
              p.column(p.text(item("kindText"), style="caption", tone="muted"),
                       p.text(item("title"), style="display", size="xl"),
                       p.text(item("icaoLine"), tone="muted", style="mono"), weight=1),
              gap="s"),
        p.text(item("regLine")),
        p.text(item("opLine"), tone="muted"),
        # Planespotters' terms: their picture, fetched by the client from
        # their host, with the photographer's credit and a link to the
        # photo (a QR code on a TV): SCREENS.md §9, SERVER-API "Photos".
        p.image(item("photo.src"), h=140, fit="cover", credit=item("photo.credit"), link=item("photo.link"),
                qr=True, alt=item("photo.alt")),
        p.text(item("routeLong"), tone="accent"),
        p.banner(item("emergencyText"), tone="emergency"),
        _grid(p.field(_("Altitude"), item("sub")), p.field(_("Vertical"), item("vertText")),
              p.field(_("Speed"), item("speedText")), p.field(_("Track"), item("trackText")),
              p.field(_("Squawk"), item("squawk"), tone=item("squawkTone")), p.field(_("From"), item("distText")),
              p.field(_("Heard"), [T.ago(item("at")), item("rssiText")]),
              p.field(_("Messages"), item("messagesText"))),
    ]
    menu = [p.text(_("Show"), style="caption", tone="muted"),
            *[_toggle("adsb.hide", words[tag][1], tag, name) for tag, name, *_r in BANDS],
            _toggle("adsb.hide", _("Altitude unknown"), "band:none", "band.none"),
            _toggle("adsb.hide", _("Hide aircraft on the ground"), "ground", shown=False),
            p.text(_("Kinds"), style="caption", tone="muted"),
            *[_toggle("adsb.hide", text, tag) for tag, text in _kinds()]]
    s = _shape(srv, req, "radio/aircraft", _("Aircraft"), "aircraft", symbols=u.Symbols.load("aircraft"),
               colors=colors, chips=chips, hide_key="adsb.hide", row=_row(sym=False), details=details, menu=menu,
               empty=_("Listening for aircraft on 1090 MHz"), empty_icon="aircraft", list_title=_("Nearest"),
               keys={"ok": A.seq(A.part("map", "follow"), A.show("hud"), hint=_("Follow"))})
    # The follow HUD (the TV's FOLLOW mode): the map keeps the selected
    # aircraft centred; Back closes it and stops following.
    hud = p.panel("hud", p.row(
        p.column(p.badge(_("Following"), style="outline", tone="accent"),
                 p.text(item("title"), style="title", size="l"),
                 p.text([item("routeText"), item("kindText")], tone="muted")),
        p.field(_("Altitude"), item("sub")), p.field(_("Speed"), item("speedText")),
        p.field(_("Heading"), item("trackText")), p.field(_("From"), item("distText")),
        gap="l", pad="m"),
        slot="bottom", max_w=860, surface="glass", for_="aircraft",
        on_close=A.seq(A.part("map", "unfollow"), A.show("details")))
    s.root["children"].insert(4, hud)
    return s


def _alt_text(a: dict) -> str | None:
    if a.get("onGround"):
        return _("Ground")
    alt = a.get("altBaro")
    if alt is None:
        alt = a.get("altGeo")
    if alt is None:
        return None
    if alt >= 6_000:
        return _("FL{fl}").format(fl=f"{round(alt / 100):03d}")
    return _("{ft} ft").format(ft=f"{alt:,.0f}")


def _band(a: dict) -> tuple[str, str]:
    """(tag, colour) of an aircraft's altitude band."""
    if a.get("onGround"):
        return "band:ground", "band.ground"
    alt = a.get("altBaro") if a.get("altBaro") is not None else a.get("altGeo")
    if alt is None:
        return "band:none", "band.none"
    for tag, name, _d, _l, top in BANDS:
        if top is None or alt < top:
            return tag, name
    return BANDS[-1][0], BANDS[-1][1]


def _kind(a: dict) -> tuple[str, str]:
    """(symbol, kind tag) from DO-260B's emitter category."""
    if a.get("onGround"):
        sym = "ground"
    else:
        sym = None
    cat = a.get("category") or ""
    kind = {"A1": "light", "A2": "light", "B1": "light", "B4": "light", "A3": "airliner", "A4": "airliner",
            "A6": "airliner", "A5": "heavy", "A7": "rotor"}.get(cat, "other")
    return sym or {"light": "light", "airliner": "jet", "heavy": "heavy", "rotor": "rotor"}.get(kind, "other"), \
        f"kind:{kind}"


def aircraft_item(a: dict) -> dict:
    """One aircraft as the screen draws it (item fields: SCREENS.md §2.2)."""
    band_tag, tone = _band(a)
    sym, kind = _kind(a)
    title = (a.get("callsign") or "").strip() or a["icao"]
    route = a.get("route") or {}
    emergency = a.get("emergencyText")
    alt = _alt_text(a)
    speed = None if a.get("groundSpeed") is None else _("{kn} kn").format(kn=f"{a['groundSpeed']:.0f}")
    tags = [band_tag, kind, "ground" if a.get("onGround") else "airborne"]
    vr = a.get("verticalRate")
    return {
        "lat": a.get("lat"), "lon": a.get("lon"), "rot": a.get("track"), "sym": sym, "tone": tone,
        "label": title, "sub": alt, "tags": tags, "at": a.get("lastHeard"), "pin": True if emergency else None,
        "title": title, "kindText": a.get("categoryText"),
        "routeText": f"{route['from']} → {route['to']}" if route.get("from") and route.get("to") else None,
        "routeLong": f"{route.get('fromName') or route['from']} → {route.get('toName') or route['to']}"
        if route.get("from") and route.get("to") else None,
        "line2": " · ".join(x for x in (alt, speed) if x) or None,
        "emergencyText": emergency,
        "distText": nm_text(a.get("distanceKm"), a.get("bearingDeg")),
        "icaoLine": " · ".join(x for x in (a["icao"], a.get("category")) if x),
        "vertText": None if vr is None else _("{fpm} ft/min").format(fpm=f"{vr:+,.0f}"),
        "speedText": speed,
        "trackText": None if a.get("track") is None else f"{a['track']:.0f}°",
        "squawk": a.get("squawk"), "squawkTone": "emergency" if emergency else None,
        "rssiText": None if a.get("rssiDb") is None else _("{db} dBFS").format(db=f"{a['rssiDb']:.1f}"),
        "messagesText": None if a.get("messages") is None else f"{a['messages']:,}",
    }


def selected_fields(radio, icao) -> dict:
    """What only the selected aircraft's details show, for the client that
    selected it: who it is (adsbdb's registration, type, operator) and its
    photo (SERVER-API "Photos"): Planespotters' `src` as given, which the
    client fetches itself, with the credit and link their terms require;
    {"src": None} for none."""
    a = (radio.adsb.table.aircraft(icao) if icao else None) or {}
    info = a.get("info") or {}
    out = {"regLine": " · ".join(x for x in (info.get("registration"), info.get("type")) if x) or None,
           "opLine": (info.get("airline") or {}).get("name") or info.get("owner")}
    ph = a.get("photo") or {}
    if not ph.get("src"):
        return out | {"photo": {"src": None}}
    return out | {"photo": {"src": ph["src"], "credit": ph.get("credit"), "link": ph.get("link"),
                            "alt": _("Photo of {what}").format(what=(a.get("callsign") or icao).strip())}}


def hook_aircraft(srv, ch) -> None:
    """Only the selected aircraft needs its photo and who it is: sent to
    the client that selected it, not to every TV, and dropped when the
    selection moves."""
    radio = srv.radio
    ch.on_select(lambda client, key: client.up("aircraft", key, selected_fields(radio, key)) if key else None,
                 sel="aircraft")


def feed_aircraft(srv, params, ch) -> None:
    a = srv.radio.adsb
    view = a.table.view()
    items = {x["icao"]: aircraft_item(x) for x in view.get("aircraft") or []}
    sync(ch, "aircraft", items, trail="tone")
    emergencies = [it for it in items.values() if it.get("emergencyText")]
    ch.set("emergency", hidden=not emergencies,
           text=" · ".join(f"{it['title']}: {it['emergencyText']}" for it in emergencies[:2]))
    _status(ch, a.view(), len(items), _("{n} aircraft"), _("{n} aircraft"))
    # A photo or details looked up after the aircraft was selected reach
    # that client now: shack_ui runs the select hook again, only for an
    # aircraft whose fields changed, so nothing flickers twice a second.
    seen = ch.__dict__.setdefault("_ui_selected", {})
    for key in {cv.selected("aircraft") for cv in ch.clients("aircraft")}:
        now = selected_fields(srv.radio, key)
        if seen.get(key) != now:
            seen[key] = now
            ch.refresh("aircraft", key)


# ---------------------------------------------------------------- Ships
SHIP_TYPES = [  # tag, colour, dark, light
    ("type:passenger", "ship.passenger", "#4FC3FF", "#0A6FA8"),
    ("type:cargo", "ship.cargo", "#57E39B", "#1E8A55"),
    ("type:tanker", "ship.tanker", "#FF6B6B", "#B3261E"),
    ("type:fishing", "ship.fishing", "#FFD54F", "#9A7A00"),
    ("type:pleasure", "ship.pleasure", "#C08BFF", "#7B3FC4"),
    ("type:service", "ship.service", "#FF9F43", "#B8610F"),
    ("type:other", "ship.other", "#B8C4CF", "#5E6B77"),
    ("type:station", "ship.station", "#8FA3B3", "#5A6E7E"),
]


def _ship_words() -> dict:
    return {"type:passenger": _("Passenger"), "type:cargo": _("Cargo"), "type:tanker": _("Tanker"),
            "type:fishing": _("Fishing"), "type:pleasure": _("Sailing and pleasure"), "type:service": _("Service"),
            "type:other": _("Other"), "type:station": _("Stations and aids")}


def _ship_type(v: dict) -> str:
    if v.get("class") in ("base", "aton"):
        return "type:station"
    t = v.get("shipType") or 0
    if t == 30:
        return "type:fishing"
    if t in (36, 37):
        return "type:pleasure"
    for lo, tag in ((50, "type:service"), (60, "type:passenger"), (70, "type:cargo"), (80, "type:tanker")):
        if lo <= t < lo + 10:
            return tag
    return "type:other"


def ship_item(v: dict) -> dict:
    tag = _ship_type(v)
    cls = v.get("class")
    distress = cls == "sart"
    moving = (v.get("speed") or 0) >= 0.5
    if distress:
        sym = "distress"
    elif cls == "base":
        sym = "baseStation"
    elif cls == "aton":
        sym = "aton"
    else:
        sym = "vessel" if moving else "vesselStopped"
    name = (v.get("name") or "").strip() or str(v["mmsi"])
    speed = None if v.get("speed") is None else _("{kn} kn").format(kn=f"{v['speed']:.1f}")
    size = _("{l} × {b} m").format(l=v["length"], b=v["beam"]) if v.get("length") and v.get("beam") else None
    return {
        "lat": v.get("lat"), "lon": v.get("lon"),
        "rot": v.get("heading") if v.get("heading") is not None else v.get("course"),
        "sym": sym, "tone": "emergency" if distress else dict((t, c) for t, c, *_r in SHIP_TYPES)[tag],
        "label": name, "tags": [tag, "moving" if moving else "still"], "at": v.get("lastHeard"),
        "pin": True if distress else None,
        "title": name, "line2": " · ".join(x for x in (v.get("shipTypeText"), speed) if x) or None,
        "emergencyText": _("Distress beacon") if distress else None,
        "distText": nm_text(v.get("distanceKm"), v.get("bearingDeg")),
        "mmsi": str(v["mmsi"]), "callsign": v.get("callsign"), "kindText": v.get("shipTypeText"),
        "navText": v.get("navStatusText"), "destination": v.get("destination"), "eta": v.get("eta"),
        "speedText": speed, "courseText": None if v.get("course") is None else f"{v['course']:.0f}°",
        "sizeText": size, "draughtText": None if v.get("draught") is None else _("{m} m").format(m=v["draught"]),
        "snrText": None if v.get("snrDb") is None else _("{db} dB").format(db=f"{v['snrDb']:.1f}"),
    }


def ships(srv, params, req):
    """Ships (the TV's ShipsScreen): the AIS table on the map."""
    u = ui()
    p, T, item = u.p, u.T, u.item
    words = _ship_words()
    colors = {c: {"dark": d, "light": li} for _t, c, d, li in SHIP_TYPES}
    chips = [p.option(t, words[t], tone=c) for t, c, *_r in SHIP_TYPES]
    details = [
        p.row(p.icon(sym=item("sym"), tone=item("tone"), size="xl", surface="card"),
              p.column(p.text(item("kindText"), style="caption", tone="muted"),
                       p.text(item("title"), style="display", size="xl"),
                       p.text(item("mmsi"), tone="muted", style="mono"), weight=1), gap="s"),
        p.banner(item("emergencyText"), tone="emergency"),
        p.text(item("navText"), tone="accent"),
        _grid(p.field(_("Callsign"), item("callsign")), p.field(_("Destination"), item("destination")),
              p.field(_("ETA"), item("eta")), p.field(_("Speed"), item("speedText")),
              p.field(_("Course"), item("courseText")), p.field(_("From"), item("distText")),
              p.field(_("Size"), item("sizeText")), p.field(_("Draught"), item("draughtText")),
              p.field(_("Heard"), [T.ago(item("at")), item("snrText")])),
    ]
    menu = [p.text(_("Show"), style="caption", tone="muted"),
            *[_toggle("ais.hide", words[t], t, c) for t, c, *_r in SHIP_TYPES],
            _toggle("ais.hide", _("Hide ships standing still"), "still", shown=False)]
    return _shape(srv, req, "radio/ships", _("Ships"), "vessels", symbols=u.Symbols.load("ships"), colors=colors,
                  chips=chips, hide_key="ais.hide", row=_row(), details=details, menu=menu,
                  empty=_("No ships heard yet: they appear within a minute of the map opening."), empty_icon="ship",
                  list_title=_("Nearest"))


def feed_ships(srv, params, ch) -> None:
    a = srv.radio.ais
    view = a.table.view()
    items = {str(v["mmsi"]): ship_item(v) for v in view.get("vessels") or []}
    sync(ch, "vessels", items, trail="tone")
    distress = [it for it in items.values() if it.get("emergencyText")]
    ch.set("emergency", hidden=not distress, text=" · ".join(f"{it['title']}: {it['emergencyText']}"
                                                              for it in distress[:2]))
    _status(ch, a.view(), len(items), _("{n} ship"), _("{n} ships"))


# ---------------------------------------------------------------- APRS
APRS_KINDS = [  # kind, colour, dark, light
    ("mobile", "aprs.mobile", "#4FC3FF", "#0A6FA8"),
    ("wx", "aprs.wx", "#57E39B", "#1E8A55"),
    ("digi", "aprs.digi", "#FF9F43", "#B8610F"),
    ("igate", "aprs.igate", "#C08BFF", "#7B3FC4"),
    ("station", "aprs.station", "#FFD54F", "#9A7A00"),
    ("object", "aprs.object", "#B8C4CF", "#5E6B77"),
]


def _aprs_words() -> dict:
    return {"mobile": _("Moving"), "wx": _("Weather"), "digi": _("Digipeaters"), "igate": _("Gateways"),
            "station": _("Stations"), "object": _("Objects and items")}


def _wx_text(wx: dict | None) -> str | None:
    if not wx:
        return None
    bits = []
    if wx.get("tempC") is not None:
        bits.append(_("{c} °C").format(c=f"{wx['tempC']:.1f}"))
    if wx.get("humidity") is not None:
        bits.append(_("{p} %").format(p=f"{wx['humidity']:.0f}"))
    if wx.get("pressureHpa") is not None:
        bits.append(_("{h} hPa").format(h=f"{wx['pressureHpa']:.1f}"))
    if wx.get("windKmh") is not None:
        bits.append(_("wind {k} km/h").format(k=f"{wx['windKmh']:.0f}"))
    return " · ".join(bits) or None


def aprs_item(x: dict, here, symbols) -> dict:
    kind = x.get("kind") or "station"
    kind = "object" if kind in ("object", "item") else kind
    if kind not in {k for k, *_r in APRS_KINDS}:
        kind = "station"
    sym = x.get("symbol") or {}
    km, bearing = place(here, x.get("lat"), x.get("lon"))
    speed = None if x.get("speedKmh") is None else _("{k} km/h").format(k=f"{x['speedKmh']:.0f}")
    return {
        "lat": x.get("lat"), "lon": x.get("lon"), "rot": x.get("courseDeg"),
        "sym": symbols.for_aprs(f"{sym.get('table') or ''}{sym.get('code') or ''}"),
        "tone": dict((k, c) for k, c, *_r in APRS_KINDS)[kind], "label": x["call"],
        "tags": [f"kind:{kind}", "direct" if x.get("heardDirect") else "via"], "at": x.get("lastHeard"),
        "title": x["call"], "line2": (x.get("comment") or x.get("status") or "").strip() or None,
        "distText": dist_text(km, bearing), "comment": (x.get("comment") or "").strip() or None,
        "statusText": (x.get("status") or "").strip() or None,
        "viaText": " ".join(x.get("via") or []) or (_("Heard direct") if x.get("heardDirect") else None),
        "wxText": _wx_text(x.get("wx")), "speedText": speed,
        "altText": None if x.get("altM") is None else _("{m} m").format(m=f"{x['altM']:,.0f}"),
        "packetsText": None if x.get("packets") is None else f"{x['packets']:,}",
        "ownerText": x.get("owner"),
    }


def aprs(srv, params, req):
    """APRS (the TV's AprsUi): the stations heard in the last day on the
    map, newest first. Receive only: nothing here sends."""
    u = ui()
    p, T, item = u.p, u.T, u.item
    words = _aprs_words()
    colors = {c: {"dark": d, "light": li} for _k, c, d, li in APRS_KINDS}
    chips = [p.option(f"kind:{k}", words[k], tone=c) for k, c, *_r in APRS_KINDS]
    details = [
        p.row(p.icon(sym=item("sym"), tone=item("tone"), size="xl", surface="card"),
              p.column(p.text(item("title"), style="display", size="xl"),
                       p.text(item("ownerText"), tone="muted"), weight=1), gap="s"),
        p.text(item("comment")),
        p.text(item("statusText"), tone="muted"),
        p.text(item("wxText"), tone="accent"),
        _grid(p.field(_("From"), item("distText")), p.field(_("Speed"), item("speedText")),
              p.field(_("Altitude"), item("altText")), p.field(_("Packets"), item("packetsText")),
              p.field(_("Heard"), T.ago(item("at")))),
        p.field(_("Path"), item("viaText")),
    ]
    menu = [p.text(_("Show"), style="caption", tone="muted"),
            *[_toggle("aprs.hide", words[k], f"kind:{k}", c) for k, c, *_r in APRS_KINDS],
            _toggle("aprs.hide", _("Only stations heard direct"), "via", shown=False)]
    return _shape(srv, req, "radio/aprs", _("APRS"), "stations", symbols=u.Symbols.load("aprs"), colors=colors,
                  chips=chips, hide_key="aprs.hide", row=_row(), details=details, menu=menu,
                  empty=_("No APRS stations heard yet"), empty_icon="aprs", list_title=_("Newest"))


def feed_aprs(srv, params, ch) -> None:
    a = srv.radio.aprs
    symbols = ui().Symbols.load("aprs")
    here = station(srv.radio)
    view = a.table.view()
    items = {x["call"]: aprs_item(x, here, symbols) for x in view.get("stations") or []}
    sync(ch, "stations", items, trail="tone")
    _status(ch, a.view(), len(items), _("{n} station"), _("{n} stations"))


# ---------------------------------------------------------------- Sondes
SONDE_PHASES = [  # phase, colour, dark, light
    ("ascent", "sonde.ascent", "#4FC3FF", "#0A6FA8"),
    ("descent", "sonde.descent", "#FF9F43", "#B8610F"),
    ("landed", "sonde.landed", "#B8C4CF", "#5E6B77"),
]


def _phase_words() -> dict:
    return {"ascent": _("Rising"), "descent": _("Falling"), "landed": _("Landed")}


def sonde_item(x: dict, here) -> dict:
    phase = x.get("phase") if x.get("phase") in ("ascent", "descent", "landed") else "ascent"
    tone = dict((k, c) for k, c, *_r in SONDE_PHASES)[phase]
    km, bearing = place(here, x.get("lat"), x.get("lon"))
    alt = None if x.get("altM") is None else _("{m} m").format(m=f"{x['altM']:,.0f}")
    climb = None if x.get("climbMs") is None else _("{v} m/s").format(v=f"{x['climbMs']:+.1f}")
    burst = x.get("burst") or {}
    landing = x.get("landing") or {}
    return {
        "lat": x.get("lat"), "lon": x.get("lon"), "rot": x.get("headingDeg"), "sym": phase, "tone": tone,
        "label": x["serial"], "sub": alt, "tags": [f"phase:{phase}"], "at": x.get("lastHeard"),
        "trail": [[q["lat"], q["lon"], tone] for q in (x.get("track") or [])[-60:]
                  if q.get("lat") is not None and q.get("lon") is not None],
        "title": x["serial"], "line2": " · ".join(y for y in (x.get("type"), alt, climb) if y) or None,
        "distText": dist_text(km, bearing), "kindText": x.get("type"),
        "freqText": None if x.get("freqHz") is None else _("{mhz} MHz").format(mhz=f"{x['freqHz'] / 1e6:.3f}"),
        "altText": alt, "climbText": climb,
        "speedText": None if x.get("speedKmh") is None else _("{k} km/h").format(k=f"{x['speedKmh']:.0f}"),
        "tempText": None if x.get("tempC") is None else _("{c} °C").format(c=f"{x['tempC']:.1f}"),
        "humidityText": None if x.get("humidity") is None else _("{p} %").format(p=f"{x['humidity']:.0f}"),
        "pressureText": None if x.get("pressureHpa") is None else _("{h} hPa").format(h=f"{x['pressureHpa']:.1f}"),
        "batteryText": None if x.get("batteryV") is None else _("{v} V").format(v=f"{x['batteryV']:.1f}"),
        "burstText": None if burst.get("altM") is None else (
            _("Predicted at {m} m") if burst.get("predicted") else _("At {m} m")).format(m=f"{burst['altM']:,.0f}"),
        "landingAt": landing.get("utc"),
    }


def sondes(srv, params, req):
    """Sondes (the TV's SondeUi): the radiosondes decoded, their tracks,
    and where each is predicted to burst and land."""
    u = ui()
    p, T, item = u.p, u.T, u.item
    words = _phase_words()
    colors = {c: {"dark": d, "light": li} for _k, c, d, li in SONDE_PHASES}
    chips = [p.option(f"phase:{k}", words[k], tone=c) for k, c, *_r in SONDE_PHASES]
    details = [
        p.row(p.icon(sym=item("sym"), tone=item("tone"), size="xl", surface="card"),
              p.column(p.text(item("kindText"), style="caption", tone="muted"),
                       p.text(item("title"), style="display", size="xl"),
                       p.text(item("freqText"), tone="muted", style="mono"), weight=1), gap="s"),
        _grid(p.field(_("Altitude"), item("altText")), p.field(_("Climb"), item("climbText")),
              p.field(_("Speed"), item("speedText")), p.field(_("From"), item("distText")),
              p.field(_("Temperature"), item("tempText")), p.field(_("Humidity"), item("humidityText")),
              p.field(_("Pressure"), item("pressureText")), p.field(_("Battery"), item("batteryText")),
              p.field(_("Burst"), item("burstText")),
              p.field(_("Lands"), T.time(item("landingAt"), "local", "hm")),
              p.field(_("Heard"), T.ago(item("at")))),
    ]
    menu = [p.text(_("Show"), style="caption", tone="muted"),
            *[_toggle("sonde.hide", words[k], f"phase:{k}", c) for k, c, *_r in SONDE_PHASES]]
    # Where each sonde is predicted to burst and to land: marks of their own,
    # so the list holds only sondes.
    marks = p.layer("predictions", "markers", from_="predictions", labels="none")
    s = _shape(srv, req, "radio/sonde", _("Sondes"), "sondes", symbols=u.Symbols.load("sondes"), colors=colors,
               chips=chips, hide_key="sonde.hide", row=_row(), details=details, menu=menu,
               empty=_("No radiosondes decoded yet: listening on 400 to 406 MHz"), empty_icon="balloon",
               list_title=_("Newest"), layers=[marks], trails=True, more_collections=("predictions",))
    # The selected sonde's readout along the bottom, over the map, as the
    # old app's: altitude large, then climb, temperature, humidity,
    # pressure and battery, without opening the details.
    readout = p.panel("readout", p.row(
        p.column(p.text(_("Altitude"), style="caption", tone="accent"),
                 p.text(item("altText"), style="display", size="xl"),
                 p.text(item("title"), tone="muted", style="mono"), w=260),
        _grid(p.field(_("Climb"), item("climbText")), p.field(_("Temperature"), item("tempText")),
              p.field(_("Humidity"), item("humidityText")), p.field(_("Pressure"), item("pressureText")),
              p.field(_("Battery"), item("batteryText")), p.field(_("Speed"), item("speedText"))),
        gap="l", pad="m"),
        slot="bottom", max_w=860, open=True, for_="sondes", surface="glass", focus=False)
    s.root["children"].insert(len(s.root["children"]) - 1, readout)
    return s


def feed_sondes(srv, params, ch) -> None:
    s = srv.radio.sonde
    here = station(srv.radio)
    listed = s.sondes().get("sondes") or []
    items = {x["serial"]: sonde_item(x, here) for x in listed}
    sync(ch, "sondes", items)
    marks = {}
    for x in listed:
        b, land = x.get("burst") or {}, x.get("landing") or {}
        if b.get("lat") is not None and b.get("lon") is not None:
            marks[f"{x['serial']}:burst"] = {"lat": b["lat"], "lon": b["lon"], "tone": "warn",
                                             "sym": "burstPredicted" if b.get("predicted") else "burst"}
        if land.get("lat") is not None and land.get("lon") is not None:
            marks[f"{x['serial']}:landing"] = {"lat": land["lat"], "lon": land["lon"], "sym": "landing",
                                               "tone": "accent"}
    sync(ch, "predictions", marks)
    _status(ch, s.view(), len(items), _("{n} radiosonde"), _("{n} radiosondes"))
