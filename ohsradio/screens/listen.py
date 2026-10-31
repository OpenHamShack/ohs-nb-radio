"""The listening screens: home (the dial), FM and DAB.

None of them holds anything while open: the dial is the operator's, and a
DAB station plays when a tile is pressed, under the client's id
(`"client": $client` on POST api/decoders/sessions), so presence ends it
when the client goes, as it ends the TV's today (SERVER-API "Client
presence"). Their audio is api/audio/rx, opened by the screen's audio
part and closed when the screen is popped.
"""
from __future__ import annotations

from ohscore.server.app import map_stop_words

from ohscore import smeter_cal
from ohscore.padactions import STEPS_HZ

from ohsradio import bands as bands_mod, xvtr
from ohsradio.i18n import _
from ohsradio.state import MODES

from .common import audio, mhz, mute, sync, ui, volume



def freq_text(hz, mode) -> str:
    if hz is None:
        return ""
    return " ".join(x for x in (mhz(hz, 1 if mode == "wfm" else 3), (mode or "").upper()) if x)


def _post(path, body=None, **kw):
    # Every call here is control: the routes they reach are control in
    # ROUTES (ohscore/server/app.py) and the manifest, and none transmits.
    return ui().A.post(path, body, level="control", **kw)


def owner_actions(owner: dict) -> list[dict]:
    """The remedy for whoever holds the receiver: stop it, as the TV's
    "receiver busy" card offers."""
    by = owner.get("by")
    if by == "dab":
        return [_post("api/decoders/sessions", {"decoder": "dab", "stop": True}, text=_("Stop DAB"))]
    words = map_stop_words()
    if by in words:
        return [ui().A.delete(f"api/{by}/session?all=1", level="control", text=words[by])]
    return []


def owner_banner() -> dict:
    """Who has the receiver when it is not the operator (a DAB station, a
    map, a pass, the band scan), in Radio's own sentence; hidden while the
    operator has it."""
    return ui().p.banner("", id="rxOwner", tone="warn", hidden=True)


def owner_set(st: dict) -> dict:
    owner = st.get("rxOwner") or {}
    if not owner:
        return {"hidden": True, "text": "", "actions": None}
    return {"hidden": False, "text": owner.get("text") or "", "actions": owner_actions(owner) or None}


# ---------------------------------------------------------------- home
def _pad(action: str, step: int, **kw) -> dict:
    """The controller's input host (api/shack/pad/action), the same route
    the pad's knobs and the TV's keys use: tune and step by the box's step,
    band by its band stacks. Receive only: the route refuses `ptt`."""
    return _post("api/shack/pad/action", {"action": action, "kind": "turn", "step": step}, **kw)


def home(srv, params, req):
    """The dial: what it is on and in which band, the S-meter, the
    waterfall to tune from, the step, the mode, the bands, the volume, and
    the way to DAB, FM and the maps (the TV's dial screen: TvEngine,
    TvRadioReadout, TvRadioRow, TvBandsPanel; the phone's ◀ ▶ tuning)."""
    u = ui()
    p, A, T, item = u.p, u.A, u.T, u.item
    s = u.Screen("radio/home", title=_("Radio"), req=req)
    s.backdrop("plain")
    s.collection("bands")
    s.live("ui/v2/live/radio/home")
    # Band down and up, as the TV's CH-/CH+ and the pad's band knob; the
    # step down and up, as its rewind and fast-forward (◀◀ ▶▶ step).
    s.key("chUp", _pad("band", 1, hint=_("Band")))
    s.key("chDown", _pad("band", -1))
    s.key("ff", _pad("step", 1, hint=_("Step")))
    s.key("rew", _pad("step", -1))
    s.key("menu", A.show("bands", hint=_("Bands")))
    modes = [p.option(m, m.upper()) for m in MODES]
    bands = p.panel("bands", p.column(
        p.text(_("Bands"), style="caption", tone="muted"),
        p.list("bandList", from_="bands", keep_focus=True, focus={"initial": True},
               # The band's own spot from the box's band stacks: dial and
               # mode in one set, as the TV's band button sends them.
               on_activate=A.seq(_post("api/set", {"changes": {"vfo": item("vfo"), "mode": item("mode")}}),
                                 A.hide("bands")),
               template=p.row(p.text(item("label"), style="title", size="m", w=90),
                              p.text(item("rangeText"), tone="muted", weight=1),
                              p.badge(item("here"), style="pill", tone="accent"), gap="s", pad="s")),
        gap="s"), slot="end", w=360, surface="glass")
    step = p.row(p.button("◀", _pad("step", -1), style="quiet", label=_("Smaller step")),
                 p.column(p.text(_("Step"), style="caption", tone="muted"),
                          p.text("", id="stepText", style="numeric", size="l"), align="center"),
                 p.button("▶", _pad("step", 1), style="quiet", label=_("Larger step")),
                 gap="s", surface="card")
    s.root = p.stack(p.column(
        p.row(p.column(p.text("", id="dialLabel", style="title", size="l", lines=1),
                       p.row(p.badge("", id="modeBadge", style="pill", tone="accent"),
                             p.text("", id="bandLine", size="m", lines=1),
                             p.text("", id="bandRange", tone="muted", lines=1), gap="s"),
                       p.text("", id="rds", tone="muted", lines=1), weight=1),
              p.meter(None, id="smeter", min=-140, max=-20, style="levels", label=_("Signal"), w=420,
                      surface="card"),
              p.column(p.badge(_("Stopped"), id="running", style="pill", tone="muted"),
                       p.text(T.clock("local", "hm"), style="numeric", size="l"), align="end"),
              gap="m"),
        p.row(p.button("◀", _pad("tune", -1), label=_("Tune down"), forms=["phone", "tablet"]),
              # The dial in hertz; Left/Right on a TV step by the box's step.
              p.frequency("dial", 0, _post("api/set", {"changes": {"vfo": A.VALUE}}), unit="MHz",
                          steps=list(STEPS_HZ), step=1000, weight=1, focus={"initial": True}),
              p.button("▶", _pad("tune", 1), label=_("Tune up"), forms=["phone", "tablet"]),
              gap="m"),
        owner_banner(),
        p.banner("", id="error", tone="bad", hidden=True),
        p.spectrum("scope", {"path": "api/spectrum/v1", "name": "main"}, overlay=True,
                   layers=["band", "dial", "passband", "channels", "beacons", "stations", "sessions"],
                   tap=_post("api/set", {"changes": {"vfo": A.HZ}}) | {"offsetHz": 0},
                   drag={"snapHz": 12_500}, weight=1),
        p.row(p.button(_("Bands"), A.show("bands"), icon="list"),
              step,
              p.choice(modes, None, _post("api/set", {"changes": {"mode": A.VALUE}}), id="mode", style="menu",
                       text=_("Mode")),
              mute(), volume(),
              p.button(_("Start the radio"), _post("api/start"), id="start", icon="play", hidden=True),
              gap="m"),
        p.row(p.button(_("DAB Radio"), A.open("radio/dab"), icon="dab"),
              p.button(_("FM"), A.open("radio/fm"), icon="fm"),
              p.button(_("Ships"), A.open("radio/ships"), icon="ship"),
              p.button(_("Aircraft"), A.open("radio/aircraft"), icon="aircraft"),
              gap="m", forms=["tv", "tablet"]),
        audio(controls="mute"),
        p.hints(style="pills", forms=["tv"]),
        gap="s", pad="m"), bands)
    return s


def _step_text(hz: int) -> str:
    return _("{n} kHz").format(n=f"{hz / 1000:g}") if hz >= 1000 else _("{n} Hz").format(n=hz)


def _range_text(lo: float, hi: float) -> str:
    unit, div = ("GHz", 1e9) if lo >= 1e9 else ("MHz", 1e6)
    return f"{lo / div:g} – {hi / div:g} {unit}"


def _band_label(name: str) -> str:
    # "2m" -> "2 m", "70cm" -> "70 cm": the band bar's spelling.
    return name[:-2] + " cm" if name.endswith("cm") else name[:-1] + " m" if name.endswith("m") else name


def _smeter(radio, st: dict) -> dict:
    """The S-meter: in dBm on S-units where the receiver is calibrated for
    this band (SERVER-API "S-meter calibration"), else the raw level in
    dBFS, labelled so, never an S figure it cannot stand behind. A number
    always, so the meter is drawn (a null main value hides a part)."""
    level = getattr(radio, "rx_level", -200.0)
    f = radio._smeter_fields(st) if hasattr(radio, "_smeter_fields") else {"dbm": None}
    if f.get("dbm") is not None:
        s9 = smeter_cal.s9_dbm(st.get("vfo") or 0)
        ticks = [{"at": s9 - 6 * (9 - n), "label": str(n)} for n in (1, 3, 5, 7, 9)]
        ticks += [{"at": s9 + d, "label": f"+{d}"} for d in (20, 40, 60)]
        return {"value": max(s9 - 54, min(s9 + 60, f["dbm"])), "min": s9 - 54, "max": s9 + 60, "ticks": ticks,
                "label": _("Signal {s}").format(s=f.get("s") or "")}
    value = level if st.get("running") and level > -199 else -140.0
    return {"value": round(max(-140.0, min(-20.0, value)), 1), "min": -140, "max": -20,
            "ticks": [{"at": x, "label": str(x)} for x in (-120, -100, -80, -60, -40)],
            "label": _("Signal, dBFS (uncalibrated)")}


def band_items(radio, st: dict) -> dict:
    """The bands this Radio has, each with its spot from the box's band
    stacks (the last used, else the band's first): what a band button sets."""
    out = {}
    stacks = st.get("bandStacks") or {}
    for b in bands_mod.BANDS:
        if xvtr.deferred(radio.st, b):
            continue
        reg = None
        stack = stacks.get(b.name) or {}
        regs = stack.get("regs") or []
        if regs:
            reg = regs[min(int(stack.get("i") or 0), len(regs) - 1)]
        vfo, mode = (reg["vfo"], reg["mode"]) if reg else b.stack[0]
        out[b.name] = {"label": _band_label(b.name), "rangeText": _range_text(b.lo, b.hi), "vfo": int(vfo),
                       "mode": mode, "here": _("Here") if st.get("band") == b.name else None}
    return out


def feed_home(srv, params, ch) -> None:
    radio = srv.radio
    st = radio.state()
    rds = st.get("rds") or {}
    label = st.get("dialLabel")
    label = label.get("text") if isinstance(label, dict) else None
    ch.set("dialLabel", value=label or freq_text(st.get("vfo"), st.get("mode")))
    b = bands_mod.BY_NAME.get(st.get("band") or "")
    ch.set("modeBadge", text=(st.get("mode") or "").upper())
    ch.set("bandLine", value=" · ".join(x for x in (_band_label(b.name) if b else None, st.get("segment")) if x))
    ch.set("bandRange", value=_range_text(b.lo, b.hi) if b else "")
    ch.set("rds", value=" · ".join(x for x in ((rds.get("ps") or "").strip(), (rds.get("rt") or "").strip()) if x))
    ch.set("running", text=_("Running") if st.get("running") else _("Stopped"),
           tone="good" if st.get("running") else "muted")
    ch.set("start", hidden=bool(st.get("running")))
    step = srv.pad().step_hz
    ch.set("dial", value=int(round(st.get("vfo") or 0)), step=step)
    ch.set("stepText", value=_step_text(step))
    ch.set("mode", value=st.get("mode"))
    ch.set("rxOwner", **owner_set(st))
    err = st.get("error") or ""
    ch.set("error", text=err, hidden=not err)
    ch.set("smeter", **_smeter(radio, st))
    ch.set("volume", value=st.get("volume"))
    sync(ch, "bands", band_items(radio, st))


# ---------------------------------------------------------------- FM
def fm(srv, params, req):
    """FM: RDS now playing, the band scan's stations by frequency and A-Z,
    tune by frequency, Scan now (the TV's TvFmScreen and the readout's RDS
    lines)."""
    u = ui()
    p, A, T, item = u.p, u.A, u.T, u.item
    s = u.Screen("radio/fm", title=_("FM"), req=req)
    s.backdrop("plain")
    s.collection("byFreq")
    s.collection("byName")
    s.live("ui/v2/live/radio/fm")
    scan = _post("api/scan", {"band": "fm"}, text=_("Scan now"))
    tune = _post("api/set", {"changes": {"vfo": item("hz"), "mode": "wfm"}})
    row = p.row(p.text(item("freqText"), style="numeric", w=110),
                p.column(p.text(item("name"), style="title", size="s", lines=1),
                         p.text(item("pty"), tone="muted", size="s"), weight=1),
                p.badge(item("stereoText"), style="outline"),
                gap="s", pad="s")
    empty = p.empty(_("No FM stations found yet"), icon="fm", action=scan)

    def listing(id_, coll):
        return p.list(id_, from_=coll, template=row, on_activate=tune, keep_focus=True, empty=empty)

    s.root = p.split(
        p.column(
            p.text(_("Now playing"), style="caption", tone="muted"),
            p.text("", id="ps", style="display", size="xl", fit=True),
            p.text("", id="rt", lines=2),
            p.row(p.text("", id="pty", tone="muted"),
                  p.badge(_("Stereo"), id="stereo", style="outline", tone="good", hidden=True),
                  p.badge(_("Traffic"), id="tp", style="outline", tone="info", hidden=True), gap="s"),
            p.frequency("dial", 0, _post("api/set", {"changes": {"vfo": A.VALUE, "mode": "wfm"}}), unit="MHz",
                        steps=[100_000], step=100_000, min=87_500_000, max=108_000_000, text=_("Tune by frequency")),
            owner_banner(),
            p.row(p.button(_("Scan now"), scan, icon="retry", style="quiet"), volume(), mute(), gap="m"),
            p.text("", id="scanText", tone="muted", size="s"),
            audio(controls="timeshift"),
            gap="s", weight=1),
        p.tabs("stations", [p.tab("freq", _("By frequency"), listing("byFreqList", "byFreq")),
                            p.tab("name", _("A-Z"), listing("byNameList", "byName"))],
               selected="freq", focus_selects=True),
        ratio=0.5, compact="stack", gap="l", pad="m")
    return s


def _fm_name(st: dict) -> str:
    ps = (st.get("ps") or "").strip()
    return ps or mhz((st.get("best") or {}).get("hz", 0), 1)


def feed_fm(srv, params, ch) -> None:
    st = srv.radio.state()
    rds = st.get("rds") or {}
    wfm = st.get("mode") == "wfm"
    ch.set("ps", value=((rds.get("ps") or "").strip() or mhz(st.get("vfo"), 1)) if wfm else _("Not on FM"))
    ch.set("rt", value=(rds.get("rt") or "").strip() if wfm else "")
    ch.set("pty", value=rds.get("ptyName") or "" if wfm else "")
    ch.set("stereo", hidden=not (wfm and srv.radio.audio_channels() == 2))
    ch.set("tp", hidden=not (wfm and rds.get("tp")))
    ch.set("dial", value=int(round(st.get("vfo") or 0)))
    ch.set("rxOwner", **owner_set(st))
    ch.set("scanText", value=(st.get("bandScan") or {}).get("text") or "")
    ch.set("volume", value=st.get("volume"))
    listed = srv.radio.bandscan.view("fm")
    items = {}
    for row in listed.get("stations") or []:
        best = row.get("best") or {}
        if not best.get("hz"):
            continue
        hz = int(best["hz"])
        items[str(hz)] = {"hz": hz, "freqText": mhz(hz, 1), "name": _fm_name(row), "pty": row.get("ptyName") or "",
                          "stereoText": _("Stereo") if best.get("stereo") else None}
    by_freq = sorted(items, key=int)
    sync(ch, "byFreq", items, by_freq)
    sync(ch, "byName", items, sorted(by_freq, key=lambda k: items[k]["name"].lower()))


# ---------------------------------------------------------------- DAB
def dab(srv, params, req):
    """DAB: the band scan's stations as tiles with their logos, the station
    playing (its slide or logo, programme text, ensemble, transmitters
    heard), Stop, Scan now, and the station's sound with its timeshift
    (the TV's TvDabScreen in DabRadioUi.kt)."""
    u = ui()
    p, item = u.p, u.item
    s = u.Screen("radio/dab", title=_("DAB Radio"), req=req)
    s.backdrop("plain")
    s.collection("stations")
    s.collection("transmitters")
    s.live("ui/v2/live/radio/dab")
    scan = _post("api/scan", {"band": "dab"}, text=_("Scan now"))
    # Plays the station, or changes to it live on the same block (`replace`:
    # the session's id is the box's, which no action can name), under this
    # client's id, so the station ends when the last client that asked for
    # it goes. A start waits for the receiver to reopen, hence 30 s.
    play = _post("api/decoders/sessions",
                 {"decoder": "dab", "freqHz": item("freqHz"), "params": {"block": item("block"), "service": item("sid")},
                  "replace": True, "client": u.A.CLIENT}, timeout_s=30)
    tile = p.card(p.column(p.image(item("logo"), aspect=1, fit="contain", alt=item("name"), placeholder="dab"),
                           p.text(item("name"), style="title", size="s", lines=1, fit=True),
                           p.text(item("detail"), tone="muted", size="s", lines=1)),
                  action=play, selected=item("playing"))
    stop = _post("api/decoders/sessions", {"decoder": "dab", "stop": True}, text=_("Stop"))
    s.key("play", stop | {"hint": _("Stop")})
    s.root = p.split(
        p.grid(id="stationGrid", from_="stations", columns={"tv": 4, "tablet": 4, "phone": 3}, aspect=0.9, gap="m",
               template=tile, focus={"initial": True},
               empty=p.empty(_("No DAB stations found yet"), icon="dab", action=scan)),
        p.column(
            p.image(None, id="slide", aspect=4 / 3, fit="contain", hero="playing", alt=_("The station's picture")),
            p.text(_("Not playing"), id="service", style="display", size="xl", fit=True),
            p.text("", id="dls", lines=2),
            p.text("", id="detail", tone="muted", size="s"),
            p.text("", id="ensemble", tone="muted", size="s"),
            p.banner("", id="why", tone="warn", hidden=True),
            p.section(_("Transmitters heard"),
                      p.list("txList", from_="transmitters", focus=False,
                             template=p.text(item("line"), size="s", tone="muted")),
                      id="txSection", hidden=True),
            p.meter(id="levels", style="levels", source={"audio": "audio"}),
            p.row(p.button(_("Stop"), stop, icon="stop"), p.button(_("Scan now"), scan, icon="retry", style="quiet"),
                  volume(), mute(), gap="m"),
            p.text("", id="scanText", tone="muted", size="s"),
            audio(controls="timeshift"),
            gap="s"),
        ratio=0.55, compact="stack", gap="l", pad="m")
    return s


def _service_detail(svc: dict) -> str:
    parts = [(svc.get("kind") or "").upper()]
    if svc.get("bitrate"):
        parts.append(_("{n} kb/s").format(n=f"{svc['bitrate']:g}"))
    if svc.get("ptyName"):
        parts.append(svc["ptyName"])
    return " · ".join(x for x in parts if x)


def _transmitter_line(t: dict) -> str:
    where = t.get("site") or _("Unknown transmitter {main}/{sub}").format(main=t.get("main"), sub=t.get("sub"))
    if t.get("distanceKm") is not None:
        return _("{site}, {km} km, {db} dB").format(site=where, km=f"{t['distanceKm']:.0f}",
                                                   db=f"{t.get('levelDb') or 0:g}")
    return _("{site}, {db} dB").format(site=where, db=f"{t.get('levelDb') or 0:g}")


def playing(radio) -> dict | None:
    """The DAB station playing: its session, block, the service asked for
    (before the one the decoder last reported, so a change shows at once),
    its picture and the decoder's metadata; None while none plays."""
    d = radio.decoders
    sid = d.held_by("dab")
    sess = d.session(sid) if sid else None
    if not sess:
        return None
    meta = sess.get("meta") or {}
    service = (sess.get("params") or {}).get("service") or meta.get("playing")
    svc = next((x for x in meta.get("services") or [] if x.get("sid") == service), {}) if service else {}
    slide = meta.get("slide") or {}
    image = None
    if slide.get("path") and slide.get("sid") == service:
        image = f"{slide['path']}?rev={slide.get('rev', 0)}"
    elif svc.get("logoPath"):
        image = svc["logoPath"]
    ens = meta.get("ensemble") or {}
    return {"session": sid, "block": sess.get("block"), "service": service, "svc": svc, "image": image,
            "dls": meta.get("dls"), "ensemble": " · ".join(x for x in (ens.get("label"), sess.get("block")) if x),
            "whyText": meta.get("whyText") or sess.get("whyText") or "", "transmitters": meta.get("transmitters") or []}


def feed_dab(srv, params, ch) -> None:
    radio = srv.radio
    st = radio.state()
    now = playing(radio)
    ch.set("scanText", value=(st.get("bandScan") or {}).get("text") or "")
    ch.set("volume", value=st.get("volume"))
    if now is None:
        ch.set("service", value=_("Not playing"))
        for pid in ("dls", "detail", "ensemble"):
            ch.set(pid, value="")
        ch.set("slide", src=None)
        ch.set("why", hidden=True, text="")
        ch.set("txSection", hidden=True)
        sync(ch, "transmitters", {})
    else:
        svc = now["svc"]
        ch.set("service", value=svc.get("label") or now["block"])
        ch.set("dls", value=now["dls"] or "")
        ch.set("detail", value=_service_detail(svc))
        ch.set("ensemble", value=now["ensemble"])
        ch.set("slide", src=now["image"])
        ch.set("why", hidden=not now["whyText"], text=now["whyText"])
        ch.set("txSection", hidden=not now["transmitters"])
        sync(ch, "transmitters", {str(i): {"line": _transmitter_line(t)} for i, t in enumerate(now["transmitters"])})
    items = {}
    for ens in radio.bandscan.view("dab").get("ensembles") or []:
        for svc in ens.get("services") or []:
            if not svc.get("sid"):
                continue
            key = f"{ens.get('block')}:{svc['sid']}"
            items[key] = {"sid": svc["sid"], "block": ens.get("block"), "freqHz": ens.get("freqHz"),
                          "name": svc.get("label") or svc["sid"], "detail": _service_detail(svc),
                          "logo": svc.get("logoPath"), "ensemble": ens.get("label"),
                          "playing": bool(now and now["block"] == ens.get("block") and now["service"] == svc["sid"])}
    sync(ch, "stations", items, sorted(items, key=lambda k: (items[k]["name"].lower(), k)))
