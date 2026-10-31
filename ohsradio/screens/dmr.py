"""DMR (the TV's DmrPanel and DmrSession): one channel's two timeslots,
the calls heard, and which slots to hear.

`radio/dmr` with no parameters chooses a channel: the operator's own
repeaters (Radio ships no repeater list: SERVER-API "Local frequencies")
and the dial. `radio/dmr?f=<Hz>` decodes that channel.

**The hold.** The TV starts a `dmr` decoder session when the panel
opens, listens to it, and stops it by its id when the panel closes
(DmrSession.kt). A screen's hold stop is a fixed path that cannot name the
id the start was answered with, so shack_ui's Holds keeps it on the box:
the hold is `POST`/`DELETE ui/v2/hold/dmr`, Holds remembers which session
each client holds, and presence going stops it as the DELETE would. Several
clients on one channel share one session, counted here, which stops with
its last holder. It is client-scoped and unsaved, like a DAB station
(the TV's was saved as a background session, and a TV switched off at the
wall left it decoding). Which slots to hear is `POST ui/v2/hold/dmr-listen`,
a route of its own: a repeated hold start returns the session it has.

Receive only, like every decoder.
"""
from __future__ import annotations

from ohscore.decoders import Refused

from ohsradio.i18n import _

from .common import audio, mhz, sync, ui

DECODER = "dmr"
# A repeater channel is 12.5 kHz, so an entry within a quarter of one is it
# (DmrRepeaters.NEAR_HZ on the TV).
NEAR_HZ = 3_125.0
LOG = 50               # calls kept in the log, newest first
STATUS = {"bad_params": 400, "unknown_decoder": 404, "unknown_session": 404, "decoder_unavailable": 409,
          "outside_span": 409, "receiver_busy": 409, "span_pinned": 409, "on_air": 409, "too_many_sessions": 429,
          "not_running": 503, "no_audio": 409, "rate_too_low": 409, "out_of_range": 409}
LISTEN = {"off": None, "1": "1", "2": "2", "both": "both"}


def _hz(value) -> float | None:
    try:
        hz = float(value)
    except (TypeError, ValueError):
        return None
    return hz if 1e6 <= hz <= 6e9 else None


def _repeaters(radio) -> list[dict]:
    """The operator's own entries worth a DMR channel: filed as a
    repeater or DMR, or in DMR mode (DmrRepeaters.isRepeater on the TV)."""
    out = []
    for e in radio.localfreq.mine.entries():
        cat = (e.get("category") or "").lower()
        if "repeater" in cat or cat == "dmr" or (e.get("mode") or "").lower() == "dmr":
            out.append(e)
    return out


def name_at(radio, hz: float) -> str | None:
    near = [e for e in radio.localfreq.mine.entries() if abs(float(e.get("freqHz") or 0) - hz) <= NEAR_HZ]
    near.sort(key=lambda e: ("repeater" not in (e.get("category") or "").lower(), abs(float(e["freqHz"]) - hz)))
    return ((near[0].get("name") or "").strip() or None) if near else None


def session_on(radio, hz: float) -> dict | None:
    for s in radio.decoders.sessions():
        if s.get("decoder") == DECODER and abs(float(s.get("freqHz") or 0) - hz) < 1.0:
            return s
    return None


def running(radio) -> str | None:
    """The status line for the DMR tile: the channels being decoded."""
    on = [s for s in radio.decoders.sessions() if s.get("decoder") == DECODER]
    if not on:
        return None
    return _("Decoding {where}").format(where=", ".join(mhz(s["freqHz"], 4) for s in on))


# ---------------------------------------------------------------- screens
def screen(srv, params, req):
    hz = _hz(params.get("f"))
    if hz is None:
        return chooser(srv, req)
    return channel(srv, hz, req)


def chooser(srv, req):
    """Which channel to decode: the operator's repeaters and the dial. A
    screen without a socket, built as the list stands when it opens."""
    u = ui()
    p, A, item = u.p, u.A, u.item
    radio = srv.radio
    s = u.Screen("radio/dmr", title=_("DMR"), req=req)
    s.backdrop("plain")
    channels = s.collection("channels")
    vfo = radio.state().get("vfo")
    if vfo:
        channels.put("dial", hz=int(vfo), name=_("The dial"), sub=mhz(vfo, 4))
    for e in _repeaters(radio):
        channels.put(f"mine:{e['id']}", hz=int(e["freqHz"]), name=(e.get("name") or "").strip() or mhz(e["freqHz"], 4),
                     sub=" · ".join(x for x in (mhz(e["freqHz"], 4), (e.get("sub") or "").strip()) if x))
    s.root = p.column(
        p.text(_("DMR"), style="title", size="xl"),
        p.text(_("Choose a channel to decode. Add your repeaters in Local frequencies to list them here."),
               tone="muted"),
        p.list("channelList", from_="channels", focus={"initial": True}, keep_focus=True,
               on_activate=A.open("radio/dmr", {"f": item("hz")}),
               template=p.row(p.icon("dmr"), p.column(p.text(item("name"), style="title", size="m"),
                                                      p.text(item("sub"), tone="muted"), weight=1), gap="s", pad="s"),
               empty=p.empty(_("No DMR channels yet"), icon="dmr")),
        gap="m", pad="l")
    return s


def channel(srv, hz: float, req):
    u = ui()
    p, A, T, item = u.p, u.A, u.T, u.item
    radio = srv.radio
    f = str(int(round(hz)))
    name = name_at(radio, hz)
    s = u.Screen("radio/dmr", title=name or _("DMR"), req=req)
    s.backdrop("plain")
    s.collection("calls")
    # Every parameter goes on the live path too: the socket builds the
    # same document from it, and a different one would never match (uiv2.py).
    s.live(f"ui/v2/live/radio/dmr?f={f}")
    s.hold("dmr", *hold_actions(srv, f))

    def slot(n: int) -> dict:
        return p.card(p.column(
            p.badge(_("Slot {n}").format(n=n), id=f"slot{n}", style="dot", tone="muted", pulse=False),
            p.text(None, id=f"talker{n}", style="title", size="l", lines=1),
            p.text(None, id=f"group{n}", tone="muted", lines=1),
            p.text(None, id=f"timer{n}", style="numeric")), w=260)

    listen = p.choice([p.option("off", _("Off")), p.option("1", _("Slot 1")), p.option("2", _("Slot 2")),
                       p.option("both", _("Both"))], "both",
                      A.post("ui/v2/hold/dmr-listen", {"client": A.CLIENT, "listen": A.VALUE}, level="control"),
                      id="listen", style="segmented", text=_("Hear"))
    s.root = p.column(
        p.row(p.column(p.text(name or mhz(hz, 4), style="title", size="xl"),
                       p.text(mhz(hz, 4) if name else None, tone="muted"), weight=1),
              p.badge("", id="state", style="pill", tone="muted"),
              p.text(T.clock("local", "hm"), style="numeric", size="l"), gap="m"),
        p.banner("", id="why", tone="warn", hidden=True),
        p.row(slot(1), slot(2), p.meter(id="level", style="bar", source={"audio": "audio"}, weight=1), gap="m"),
        p.row(listen, gap="m"),
        p.list("log", from_="calls", follow="top", keep_focus=True, weight=1, focus={"initial": True},
               empty=p.empty(_("No calls heard yet"), icon="dmr"),
               template=p.row(p.text(item("slotText"), tone="muted", w=40),
                              p.text(item("callsign"), style="title", size="s", w=130),
                              p.text(item("name"), weight=1, lines=1),
                              p.text(item("tg"), tone="muted", lines=1),
                              p.badge(item("flag"), style="outline", tone=item("flagTone")),
                              p.text(item("durText"), style="numeric", tone="muted"),
                              p.text(T.time(item("at"), "local", "hms"), style="numeric", tone="muted"),
                              gap="s", pad="xs")),
        audio(controls="mute"),
        gap="m", pad="m")
    return s


def _id(v) -> str | None:
    # IDs come through the decoder's feed as JSON numbers, floats included.
    return None if v is None else str(int(v))


def _who(x: dict) -> str | None:
    if x.get("srcCallsign"):
        return x["srcCallsign"]
    if x.get("alias"):
        return x["alias"]
    return _id(x.get("src"))


def _to(x: dict) -> str | None:
    if x.get("callType") == "private":
        return _("Private")
    if x.get("dstName"):
        return x["dstName"]
    return None if x.get("dst") is None else _("TG {n}").format(n=_id(x["dst"]))


def _iso(t) -> str | None:
    from datetime import datetime, timezone
    if t is None:
        return None
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def feed(srv, params, ch) -> None:
    hz = _hz(params.get("f"))
    if hz is None:
        return
    radio = srv.radio
    T = ui().T
    s = session_on(radio, hz)
    sess = radio.decoders.session(s["id"]) if s else None
    if sess is None:
        ch.set("state", text=_("Not decoding"), tone="muted")
        ch.set("why", hidden=True, text="")
        return
    ch.set("state", text=sess.get("state") or "", tone="good" if sess.get("state") == "synced" else "muted")
    ch.set("why", hidden=not sess.get("whyText"), text=sess.get("whyText") or "")
    slot_param = (sess.get("params") or {}).get("slot") or "both"
    ch.set("listen", value=slot_param if sess.get("listening") else "off")
    meta = sess.get("meta") or {}
    for x in meta.get("slots") or []:
        n = int(x.get("slot") or 0)
        if n not in (1, 2):
            continue
        voice = x.get("state") == "voice"
        ch.set(f"slot{n}", tone="good" if voice else "muted", pulse=voice,
               text=_("Slot {n}").format(n=n) + (" · " + _("Encrypted") if x.get("encrypted") else ""))
        ch.set(f"talker{n}", value=_who(x))
        ch.set(f"group{n}", value=_to(x))
        ch.set(f"timer{n}", value=T.since(_iso(x["callStart"])) if voice and x.get("callStart") else None)
    calls = {}
    for res in sess.get("results") or []:
        if res.get("type") != "frame" or res.get("frame") not in ("call_end", "sms"):
            continue
        sms = res["frame"] == "sms"
        r = dict(res.get("fields") or {}, t=res.get("t"))
        calls[str(res["rev"])] = {
            "slotText": _("TS{n}").format(n=_id(r.get("slot"))), "callsign": _who(r),
            "name": r.get("text") if sms else (r.get("srcName") or r.get("alias")),
            "tg": _to(r) if not sms else _("Message"), "at": _iso(r.get("t")),
            "durText": None if r.get("durationS") is None else _("{s} s").format(s=f"{r['durationS']:.0f}"),
            "flag": _("Emergency") if r.get("emergency") else _("Encrypted") if r.get("encrypted") else None,
            "flagTone": "emergency" if r.get("emergency") else "warn"}
    keep = sorted(calls, key=int, reverse=True)[:LOG]
    sync(ch, "calls", {k: calls[k] for k in keep}, keep)


# ---------------------------------------------------------------- the hold
def holds(srv):
    """The server's Holds (one per server, as each has its own radio), with
    the DMR hold defined on it."""
    h = srv.__dict__.get("_ui_holds")
    if h is None:
        h = srv._ui_holds = ui().Holds()
        h.define("dmr", start=lambda client, req: _start(srv, client, req), stop=lambda sid: _stop(srv, sid))
        srv._ui_dmr_holders = {}
    return h


def hold_actions(srv, f: str) -> tuple[dict, dict]:
    """The screen's hold, with the channel added: the start's body names
    it, and the stop's query too (Holds' actions carry only the client)."""
    start, stop = holds(srv).actions("dmr")
    start = start | {"body": {**start["body"], "freqHz": int(f)}}
    stop = stop | {"path": f"{stop['path']}&f={f}"}
    return start, stop


def _start(srv, client: str, hz) -> str:
    """Holds' start: this channel's session, started if there is none; a
    new one listens to both slots. Refusals go to the hold banner."""
    radio = srv.radio
    d = radio.decoders
    if hz is None:
        raise ui().HoldRefused(400, _("Give freqHz, the channel's centre in hertz"), "bad_params")
    try:
        s = session_on(radio, hz)
        if s is None:
            s = d.start(DECODER, hz, {"slot": "both"}, save=False)
            d.listen(s["id"], True)
        if d.listening == s["id"]:
            srv.holds.add(("listen", s["id"]), client)
    except Refused as e:
        raise ui().HoldRefused(STATUS.get(e.code, 400), str(e), e.code) from None
    n = srv._ui_dmr_holders
    n[s["id"]] = n.get(s["id"], 0) + 1
    return s["id"]


def _stop(srv, sid: str) -> None:
    n = srv._ui_dmr_holders
    n[sid] = n.get(sid, 1) - 1
    if n[sid] > 0:
        return
    n.pop(sid, None)
    srv.radio.decoders.stop(sid)
    srv.holds.forget(("listen", sid))


def hold(srv, method: str, body: dict, params: dict, client):
    """ui/v2/hold/dmr: shack_ui's Holds answers (the channel from the
    start's body). The stop's `f` is for a reader of the logs: Holds knows
    the session by client."""
    return holds(srv).answer(method, "dmr", client, _hz(body.get("freqHz")))


def listen(srv, method: str, body: dict, client):
    """POST ui/v2/hold/dmr-listen {"client", "listen": "1"|"2"|"both"|"off"}:
    the slot param, then listening, on the session this client holds."""
    d = srv.radio.decoders
    sid = holds(srv).held("dmr", client) if client else None
    if method != "POST" or sid is None:
        return 404, {"error": _("This client holds no DMR channel"), "code": "unknown_session"}
    want = body.get("listen")
    if want not in LISTEN:
        return 400, {"error": _("listen is 1, 2, both or off"), "code": "bad_params"}
    try:
        if want == "off":
            if d.listening == sid:
                d.listen(sid, False)
            srv.holds.forget(("listen", sid))
        else:
            if (d.session(sid) or {}).get("params", {}).get("slot") != LISTEN[want]:
                d.configure(sid, {"slot": LISTEN[want]})
            d.listen(sid, True)
            srv.holds.add(("listen", sid), client)
    except Refused as e:
        return STATUS.get(e.code, 400), {"error": str(e), "code": e.code}
    return 200, d.session(sid) | {"results": []}
