"""Weather Sats and its picture viewer (the TV's WxSatUi): the contract's
worked example (SCREENS.md §12; ohs-libs examples/radio_wxsat.py) on
Radio's own passes and pictures.

**Read-only and never holds.** The screen is polled (§4.5), never a
socket, so opening it wakes and holds nothing: passes are recorded by
the plan whether anyone looks or not. Its only calls are a pass's own
record or skip (control), as the TV's OK on a pass does.

**Polled as snaps.** Each poll answer is the screen's whole state as a
snap (shack_ui poll_answer): the client applies it to the document's own
state, so a pass that aged out of the day, or a picture the disk rules
pruned, is simply gone, with nothing remembered per client. The document
keeps its collections empty for that reason.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ohsradio import wxsat as wxsat_mod
from ohsradio.i18n import _

from .common import OSM, ui

PAST_H = 24.0          # passes shown from this long ago
AHEAD_H = 48.0         # to this far ahead
FRAMES_H = 24          # the map's frames: the last day's passes
TRAIL_EVERY = 3        # every third 10 s track point: a sky plot needs no more
COLORS = {"sat.meteor-m2-3": ("#5FD3FF", "#0B6E99"), "sat.meteor-m2-4": ("#B48CFF", "#6A3FC0"),
          "plan.record": ("#57E39B", "#1E8A55"), "plan.busy": ("#FFC857", "#9A6A00"),
          "plan.skip": ("#7F8C99", "#5A6672"), "plan.conflict": ("#FF6B6B", "#B3261E"),
          "plan.recording": ("#C08BFF", "#7B3FC4"), "plan.decoding": ("#4FE3E3", "#0B7F7F")}
SAT = {"paths": [{"d": "M10 10 H14 V14 H10 Z", "fill": "ink"},
                 {"d": "M2 10.5 H9 V13.5 H2 Z M15 10.5 H22 V13.5 H15 Z", "fill": "tone", "stroke": "ink", "w": 0.5}]}
# Products first in the gallery and the viewer: MCIR, as the old app
# opened on (it has colour by night too, where `rgb` is missing), then
# `rgb` and `ir` as the API orders them.
FIRST = ("mcir", "rgb", "ir")


def _plan_words() -> dict:
    return {"record": (_("Will record"), "plan.record"), "skip-low": (_("Too low"), "plan.skip"),
            "skip-disabled": (_("Skipped"), "plan.skip"), "skip-busy": (_("Receiver in use"), "plan.busy"),
            "skip-conflict": (_("Receiver busy"), "plan.conflict"), "recording": (_("Recording"), "plan.recording"),
            "decoding": (_("Decoding"), "plan.decoding"), "done": (_("Done"), "plan.record"),
            "failed": (_("Failed"), "plan.conflict"), "missed": (_("Missed"), "plan.skip")}


def _compass(deg) -> str:
    if deg is None:
        return ""
    names = [_("N"), _("NE"), _("E"), _("SE"), _("S"), _("SW"), _("W"), _("NW")]
    return names[int(((deg % 360) + 22.5) // 45) % 8]


def northbound(p: dict) -> bool:
    """A pass rising in the south flies north: its pictures are drawn
    upside down unless turned (the TV turns them 180°)."""
    az = p.get("aosAzDeg")
    return az is not None and 90.0 < az < 270.0


def _action(p: dict, now_iso: str):
    """OK on a pass: record or skip by its plan (the TV's), with "Record
    anyway?" where that takes the receiver from someone; none once it is
    over."""
    A = ui().A
    if p["los"] <= now_iso:
        return None
    path = f"api/wxsat/passes/{p['id']}/record"
    plan = p.get("plan") or ""
    if plan in ("record", "recording"):
        return A.delete(path, level="control", text=_("Skip this pass"))
    if plan == "skip-busy":
        return A.post(path, level="control", text=_("Record anyway"), confirm=A.ask(
            _("Record anyway?"), _("Someone is using the receiver. Recording this pass stops what they hear."),
            tone="warn", yes=_("Record"), no=_("Cancel")))
    if plan.startswith("skip-"):
        return A.post(path, level="control", text=_("Record this pass"))
    return None


def pass_item(p: dict, now_iso: str) -> dict:
    u = ui()
    T = u.T
    words = _plan_words()
    plan_text, plan_tone = words.get(p.get("plan"), (p.get("plan") or "", "plan.skip"))
    track = p.get("track") or []
    top = max(track, key=lambda q: q.get("el") or 0, default=None)
    act = _action(p, now_iso)
    item = {
        "label": p["sat"], "freqText": _("{mhz} MHz").format(mhz=f"{p['freqHz'] / 1e6:.3f}"),
        "when": T.time(p["aos"], "local+utc", "dayhm"),
        "dirText": _("{a} to {b}, highest {el}°").format(a=_compass(p.get("aosAzDeg")), b=_compass(p.get("losAzDeg")),
                                                         el=f"{p['maxElDeg']:.0f}"),
        "planText": plan_text, "planTone": plan_tone,
        "countdown": T.countdown(p["aos"], [_("in {d}"), _("up, sets in {d}"), _("over")], then=p["los"]),
        "tone": f"sat.{p['id'].rsplit('-', 1)[0]}" if f"sat.{p['id'].rsplit('-', 1)[0]}" in COLORS else "accent",
        "trail": [[q["t"], q["az"], q["el"]] for q in track[::TRAIL_EVERY] + track[-1:]],
        "aos": {"az": p.get("aosAzDeg"), "el": 0, "text": _("AOS")},
        "los": {"az": p.get("losAzDeg"), "el": 0, "text": _("LOS")},
        "max": None if top is None else {"az": top["az"], "el": top["el"], "text": f"{p['maxElDeg']:.0f}°"},
        "summary": _("{sat}, highest {el}°").format(sat=p["sat"], el=f"{p['maxElDeg']:.0f}"),
        "whyText": p.get("why"),
        "hint": act.get("text") if act else None,
        "action": act,
    }
    return item


def image_item(im: dict, passes: dict) -> dict | None:
    products = _products(im)
    if not products:
        return None
    first = products[0]
    p = passes.get(im.get("passId"), {})
    T = ui().T
    return {"id": im["id"], "thumb": f"{first['url']}?w=400", "label": im.get("sat") or im["id"],
            "when": T.time(im["aos"], "local", "dayhm") if im.get("aos") else None,
            "maxElText": None if im.get("maxElDeg") is None else _("highest {el}°").format(el=f"{im['maxElDeg']:.0f}"),
            "rotate": 180 if northbound(p) else 0}


def _products(im: dict) -> list[dict]:
    got = [x for x in im.get("products") or [] if x.get("url")]
    return sorted(got, key=lambda x: (FIRST.index(x["kind"]) if x.get("kind") in FIRST else len(FIRST)))


def screen(srv, params, req):
    """The four tabs: Passes (with the sky plot of the one chosen), Live
    (the pass in the sky), Gallery and Map; polled."""
    u = ui()
    p, A, T, item = u.p, u.A, u.T, u.item
    s = u.Screen("radio/wxsat", title=_("Weather Sats"), req=req)
    s.backdrop("aurora")
    s.words({"s": "{n}s", "min": "{n}m", "h": "{n}h", "d": "{n}d"})
    s.colors({k: {"dark": d, "light": li} for k, (d, li) in COLORS.items()})
    s.symbols({"sat": SAT})
    for c in ("passes", "images", "frames"):
        s.collection(c)
    s.selection("pass", from_="passes")
    s.poll("ui/v2/poll/radio/wxsat", 5)
    row = p.row(
        p.badge(style="pill", tone=item("tone"), w=6, h=48),
        p.column(p.text([item("label"), item("freqText")], style="title", size="s"),
                 p.text(item("when"), tone="muted"),
                 p.text(item("dirText"), tone="muted", size="s"), weight=1),
        p.column(p.badge(item("planText"), style="outline", tone=item("planTone")),
                 p.text(item("countdown"), style="numeric", size="s"), align="end"),
        gap="s", pad="s")
    passes = p.split(
        # OK on a pass runs the pass's own action: record or skip by plan.
        p.list("passList", from_="passes", selection="pass", w=480, focus={"initial": True}, keep_focus=True,
               on_activate=item("action"), empty=p.empty(_("No passes in the next two days"), icon="satellite"),
               template=row),
        p.column(p.text(_("Next pass"), id="nextName", style="caption", tone="muted"),
                 p.text("", id="nextCountdown", style="display", size="xxl"),
                 p.skyplot("sky", from_="passes", selection="pass", show="selected", w=250, h=250, min_el=15,
                           rings=[30, 60]),
                 p.column(p.text(item("summary")), p.text(item("whyText"), tone=item("planTone")),
                          p.text(item("hint"), tone="muted", size="s"), id="passInfo", for_="pass", gap="xs"),
                 gap="s", weight=1),
        gap="l", compact="stack")
    live = p.row(
        p.skyplot("liveSky", from_="passes", show={"key": None}, w=390, h=390, min_el=15, rings=[30, 60], now=None),
        p.column(
            p.badge(_("Nothing up"), id="liveState", style="pill", tone="muted"),
            p.text(None, id="liveSat", style="title", size="xl"),
            p.text(None, id="liveLine", tone="muted"),
            p.meter(None, id="snr", min=0, max=25, style="bar", label=_("Signal"),
                    ticks=[{"at": 0, "label": "0"}, {"at": 10, "label": "10"}, {"at": 20, "label": "20 dB"}],
                    zones=[{"from": 0, "to": 3, "tone": "bad"}, {"from": 3, "to": 8, "tone": "warn"},
                           {"from": 8, "to": 25, "tone": "good"}]),
            p.field(_("Elevation now"), None, id="elNow"),
            p.text(None, id="liveCountdown", style="numeric", size="xl"),
            id="liveInfo", gap="s", weight=1),
        gap="l")
    card = p.card(p.stack(
        p.image(item("thumb"), fit="cover", align="fill", hero=item("id"), rotate=item("rotate"), alt=item("label")),
        p.column(p.text(item("label"), style="title", size="s"),
                 p.text([item("when"), item("maxElText")], size="s", tone="muted"),
                 align="bottom-fill", surface="scrim", pad="s")),
        surface="card", action=A.open("radio/wxsat/viewer", {"image": item("id")}))
    gallery = p.grid(id="galleryGrid", from_="images", columns={"tv": 4, "tablet": 3, "phone": 2}, aspect=1.25,
                     gap="m", template=card,
                     empty=p.empty(_("No pictures yet: they appear after a pass is decoded"), icon="picture"))
    the_map = p.map(
        "wxmap", ground={"tiles": "api/map/tiles/{z}/{x}/{y}.png", "land": "api/map/land", "zoom": [3, 9],
                         "style": "night"},
        attribution=OSM, view={"center": [52.0, 2.0], "zoom": 5},
        views=[{"center": [52.0, 2.0], "zoom": 5, "label": _("Europe")},
               {"center": [55.0, -3.5], "zoom": 7, "label": _("UK")}],
        keys={"down": A.part("wxmap", "view", hint=_("Europe or UK")), "ok": A.part("wxmap", "play", hint=_("Play")),
              "play": A.part("wxmap", "play"), "left": A.part("wxmap", "prev", hint=_("Earlier")),
              "right": A.part("wxmap", "next", hint=_("Later"))},
        layers=[p.layer("frames", "images", from_="frames", frame=-1, alpha=0.92, fade_ms=600, play_ms=1400,
                        scrubber=True, empty=_("Pictures from the last day appear here once passes are projected"))])
    s.root = p.column(
        p.row(p.icon(sym="sat", tone="sat.meteor-m2-3", size="l"),
              p.column(p.text(_("Weather Sats"), style="title", size="xl"),
                       p.text("", id="elements", tone="muted"), weight=1),
              p.text(T.clock("local+utc", "hm"), style="numeric", size="l"),
              gap="m"),
        p.tabs("tabs", [p.tab("passes", _("Passes"), passes), p.tab("live", _("Live"), live),
                        p.tab("gallery", _("Gallery"), gallery), p.tab("map", _("Map"), the_map)],
               selected="passes", focus_selects=True, weight=1, badges={"live": None}),
        p.hints(style="pills", forms=["tv"]),
        pad="l", gap="m")
    return s


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def poll(srv, params, req) -> dict:
    """GET ui/v2/poll/radio/wxsat: the passes, pictures, the map's frames
    and the Live tab, as a snap; every 2 s while a pass records, 10 s
    otherwise (as the TV's WxSatSession polls)."""
    u = ui()
    w = srv.radio.wxsat
    if w is None:
        return u.poll_answer()
    now_iso = _iso(w.clock())
    view = w.passes_view(AHEAD_H, PAST_H)
    passes = {x["id"]: x for x in view.get("passes") or []}
    images = {}
    for im in w.images_view():
        it = image_item(im, passes)
        if it is not None:
            images[im["id"]] = it
    frames = {f["imageId"]: f for f in w.composite_view("rgb", FRAMES_H)["frames"]}
    for f in w.composite_view("ir", FRAMES_H)["frames"]:
        frames.setdefault(f["imageId"], f)
    order = sorted(frames, key=lambda k: frames[k].get("aos") or "")
    T = u.T
    frame_items = u.Collection({k: {"src": frames[k]["url"], "bounds": frames[k]["bounds"],
                                    "label": T.time(frames[k].get("aos"), "local", "dayhm")} for k in order}, order)
    parts = _live_parts(w, passes, now_iso)
    parts["elements"] = {"value": _elements_text(view.get("tle") or {})}
    recording = w.status_view().get("state") == "recording"
    # Upcoming first (one in the sky now included), soonest first; then
    # the day's past passes, newest first. The old app opened on what is
    # coming; a list in AOS order opened on a day of passes already over.
    coming = sorted((x for x in passes.values() if x["los"] > now_iso), key=lambda x: x["aos"])
    gone = sorted((x for x in passes.values() if x["los"] <= now_iso), key=lambda x: x["aos"], reverse=True)
    listed = {x["id"]: pass_item(x, now_iso) for x in coming + gone}
    return u.poll_answer({"passes": listed, "images": images,
                          "frames": frame_items}, parts, every_s=2 if recording else 10)


def _elements_text(tle: dict) -> str:
    if not tle:
        return ""
    age = tle.get("ageDays")
    text = _("Orbits from {source}").format(source=tle.get("source") or "?")
    if age is not None:
        text += " · " + _("{d} days old").format(d=f"{age:.1f}")
    return text


def _live_parts(w, passes: dict, now_iso: str) -> dict:
    """The Live tab and the next-pass heading: what is in the sky or
    recording now, from api/wxsat/status; Live's tab badge while recording."""
    st = w.status_view()
    state = st.get("state")
    T = ui().T
    upcoming = [x for x in passes.values() if x["aos"] > now_iso and (x.get("plan") == "record")]
    nxt = min(upcoming, key=lambda x: x["aos"], default=None)
    words = {"recording": (_("Recording"), "onAir"), "decoding": (_("Decoding"), "accent"),
             "waiting": (_("Waiting"), "muted"), "idle": (_("Nothing up"), "muted")}
    text, tone = words.get(state, (_("Nothing up"), "muted"))
    live = passes.get(st.get("passId")) if state == "recording" else None
    return {
        "nextName": {"value": _("Next pass: {sat}").format(sat=nxt["sat"]) if nxt
                     else _("No pass will be recorded in the next two days")},
        "nextCountdown": {"value": T.countdown(nxt["aos"], [_("in {d}"), _("now")]) if nxt else ""},
        "liveState": {"text": text, "tone": tone},
        "liveSat": {"value": st.get("sat")},
        "liveLine": {"value": st.get("text")},
        "snr": {"value": st.get("snrDb") if state == "recording" else None},
        "elNow": {"value": None if st.get("el") is None or state != "recording" else f"{st['el']:.0f}°"},
        "liveCountdown": {"value": T.countdown(live["los"], [_("sets in {d}"), _("over")]) if live else None},
        "liveSky": {"show": {"key": live["id"] if live else None},
                    "now": {"az": st["az"], "el": st["el"]} if live and st.get("az") is not None else None},
        "tabs": {"badges": {"live": "onAir" if state == "recording" else None}},
    }


def viewer(srv, params, req):
    """One decoded pass: a product strip along the bottom, the picture
    turned for a northbound pass, a glass caption. Pictures are asked at
    1920 px (?w=), the box's copy at the next 200 px."""
    u = ui()
    p, T = u.p, u.T
    w = srv.radio.wxsat
    image = params.get("image") or ""
    im = next((x for x in (w.images_view() if w is not None else []) if x["id"] == image), None)
    s = u.Screen("radio/wxsat/viewer", title=(im or {}).get("sat") or _("Picture"), req=req)
    s.backdrop("plain")
    if im is None:
        s.root = p.empty(_("That picture is no longer kept"), icon="picture", action=u.A.back(text=_("Back")))
        return s
    passes = {x["id"]: x for x in w.passes_view(AHEAD_H, wxsat_mod.MAX_PAST_HOURS).get("passes") or []}
    turn = 180 if northbound(passes.get(im.get("passId"), {})) else 0
    pages = []
    for i, x in enumerate(_products(im)):
        img = p.image(f"{x['url']}?w=1920", fit="contain", rotate=turn, alt=x.get("name") or x["kind"],
                      **({"hero": im["id"]} if i == 0 else {}))
        pages.append(p.tab(x["kind"], x.get("name") or x["kind"].upper(), img))
    first = _products(im)[0] if _products(im) else {}
    size = f"{first['w']} × {first['h']}" if first.get("w") and first.get("h") else None
    s.root = p.stack(
        p.tabs("products", pages, align="fill", selected=pages[0]["id"] if pages else None, focus_selects=True,
               place="bottom", style="pills", focus={"initial": True}),
        p.column(p.text(im.get("sat") or "", style="title", size="l"),
                 p.text(T.time(im["aos"], "local+utc", "dayhm") if im.get("aos") else None, tone="muted"),
                 p.text(" · ".join(x for x in (None if im.get("maxElDeg") is None else _("Max elevation {el}°").format(
                     el=f"{im['maxElDeg']:.1f}"), size) if x), tone="muted", size="s"),
                 align="top-start", pad="m", surface="glass"))
    return s
