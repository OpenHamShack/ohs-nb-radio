"""QO-100 NB's ui/2 screens (openhamshack docs/contract/SCREENS.md), what a
TV, phone or tablet shows of NB's receive side. The routes are shared
(ohscore/server/uiv2.py); the documents are built here with ohs-libs
shack_ui v2 (shacklibs.ui()), which checks every rule a renderer enforces.

| Screen | Title | What |
|---|---|---|
| `nb/home` | QO-100 NB | the dial and mode, the wide scope with its labels and the zoom scope (spectrum/1 and overlay/1), beacon lock and signal, the decodes (FT8/FT4/Q65/JS8 as a list; CW, RTTY and PSK as running text), receive audio, the receive settings, status; and, only while `SCREENS_TRANSMIT` is on (it is off: receive-only), PTT, Enable TX and the transmit settings where the contract lets a renderer draw them |
| `nb/signals` | Band activity | every signal on the transponder (the skimmer) and the over-power and LEILA watch; OK tunes |
| `nb/beacon` | QO-100 beacon | the middle beacon's text blocks, the DX-cluster spots and the beacon's decode health |
| `nb/decodes` | Decodes | the decodes full screen (from home, no tile): dB, DT, audio frequency, message and country under a header line per slot; CW, RTTY and PSK as running text |

**Bookmarks** are the engine's memories, as on the old TV: a picker on
home, CH+/CH- stepping them (a `send`, so the box steps from the dial as
it is), and ticks and names on the scopes (ohsnb/overlay.py). **Decodes**
come grouped by slot under a header line (a row field, `slotHead`: the
contract has no list section headers), are cleared when the mode leaves
the slot modes, as the old TV closed its panel, and by Clear.

**One tree for every client.** Every form gets the same parts (what
differs is the parts' `forms`), so one channel per screen serves them all;
shack_ui keeps a document per rev on it and greets each client with the
rev it fetched. The documents hold no live values (the dial, the lock,
the decodes): those come in the snap, so a document's rev changes only
with the client, the build and, the one exception, the memories (the
bookmark picker's options, which a renderer must have from the start).

**Live state follows the engine only while someone watches.** The shared
pump (uiv2.Live) calls `feed` only while a channel has a client, and only
those calls drain NB's subscriptions to the engine's feeds (Follower).
That matters for transmit: the engine's watchdog counts any feed being
drained as the user interface being alive (Engine._supervise), so a
thread that drained forever would keep a hung desktop's transmitter on.
A socket open is a client, the same as api/events has always counted.

**Holds.** `nb/home` and `nb/signals` hold the receiver (`receiver`, §6):
the start wakes a radio given back while idle, and when the radio is
stopped or was handed to another app it refuses with the sentence and a
"Start the radio" remedy, rather than taking the Pluto back on every
renewal from under the app it was handed to. The stop gives nothing back:
NB keeps its receiver for its other listeners and its background decoders
(beacon text, skimmer, over-power watch), as it always has. NB has no
client presence, so there is nothing to renew (`renewS` none).

**Transmit (§7)** is, for now, not in the documents at all: `SCREENS_TRANSMIT`
(below) is False, so a renderer never sees ptt or txArm. With it on, it is
placed, never keyed here: `ptt` (phone and tablet;
a renderer never draws it on a TV) and `txArm` (`digital`, so a TV an
administrator allowed digital transmit may draw it), and the transmit
settings marked `tx` with a lease on one of them, enabled only while this
client holds it. Every call names the level the server checks.

**Left out**, and why:
- answering a decode with Enable TX: NB's reply is `POST api/autotx
  {"reply": ...}`, the txArm's own arm route, which no document call may
  reach (§7.3), and `txArm.choices` has no defined shape for a choice
  bound to a selected decode; only "Call CQ" is offered;
- SSTV, KG-STV and the beacon's pictures and bulletins (pictures arriving
  block by block need an image route this server does not have), FreeDV
  and HSModem's own displays;
- the logbook, saving and deleting memories, recordings, the decoder
  sessions view and settings other than receive and transmit: the
  desktop's and the controller's (a read-only log, which today's Remote
  has, was left for after the switch: Brian, 31/10/2026, day-to-day
  features only);
- "Hide decoder": the side's `hidden` would have to be a `local` value
  (§2.1 allows it), and the Android renderer reads `hidden` only as a
  literal and keeps a split's ratio with one side gone (the full-screen
  decodes are the other way round: the list without the scope);
- click-to-lock on a beacon, which has no HTTP route;
- a per-device "Signal labels" choice: the schema takes only a boolean
  for a spectrum's `overlay`, so the labels are always on;
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ohscore import shacklibs
from ohscore.i18n.text import _
from ohscore.modes import MODES
from ohscore.server import shack
from ohscore.server.uiv2 import UnknownScreen

log = logging.getLogger("ohsnb.screens")

APP = "shack-qo100nb"
ENTRY = "qo100nb"
SPECTRUM = {"path": "api/spectrum/v1", "name": "main"}
ZOOM = {"path": "api/spectrum/v1", "name": "zoom"}
# The tuning steps today's Remote offers on NB (shack/Tuning.kt NB_STEPS),
# 100 Hz first.
STEPS = [10, 50, 100, 500, 1000, 5000]
DIAL_MIN, DIAL_MAX = 10_489_500_000, 10_490_000_000
SLOT_MODES = ("ft8", "ft4", "q65", "js8")
TEXT_MODES = ("cw", "rtty", "psk31", "psk63", "psk125")
MAX_DECODES = 60
# A bookmark is "the one the radio is on" (the picker shows it chosen) with
# the dial this close and the same mode; CH+/CH- pass over it. The old TV's
# Bookmarks.current and Bookmarks.step, moved to the box (SCREENS.md D9).
BOOKMARK_TOL_HZ = 50.0
MAX_TEXT = 600              # characters of running CW/RTTY/PSK text kept
MAX_SIGNALS = 80
MAX_SPOTS = 40
# The overlay layers each scope draws (ohsnb/overlay.py makes them).
SCOPE_LAYERS = ("band", "dial", "sessions", "bookmarks", "beacons", "alerts")
ZOOM_LAYERS = ("dial", "bookmarks", "beacons", "signals", "alerts")
FEEDS = ("state", "meter", "events", "toast", "overpower", "skim", "midtext", "mmb")
HOLD = "receiver"

# Receive-only first (Brian, 31/10/2026). The ui/2 screens go live without any
# transmit part: no ptt, no txArm, no transmit settings (the calls marked
# tx=True with a lease), no Halt and no Enable TX line, because neither
# renderer has keyed a real radio yet. Turning transmit on is this one line,
# after the T-tests with Brian present; the code behind it is kept whole and
# tested with the switch on, so that is all it takes. It is deliberately not
# a user setting or a config key: when a station may transmit from these
# screens is a release decision, not something to find toggled on a box.
# The "Transmit" status field stays either way: receive-only it reads
# "Receiving" (or the reason transmit is blocked), which is worth knowing.
SCREENS_TRANSMIT = False

# Ids that exist in the home document only when SCREENS_TRANSMIT is on; the
# live follower must not name them otherwise.
TX_IDS = frozenset(("txInfo", "split", "txGain", "micGain", "cwWpm"))

# State keys a screen shows, so a change to anything else (the supervisor
# publishes its CPU and stream figures ten times a second) costs nothing.
SHOWN = frozenset((
    "vfo", "mode", "filterLo", "filterHi", "cwPitch", "rxLock", "rxSnr", "simulator", "device", "keyed",
    "segment", "rit", "ritOn", "error", "nr", "nb", "split", "agc", "beaconMode", "beacon", "rfGain",
    "nrStrength", "txGain", "micGain", "cwWpm", "zoomSpanHz", "running", "deviceStatus", "beaconUsed",
    "beaconLevel", "rxDial", "txBlocked", "recording", "recFile", "skimDecode", "skimState", "midTextState",
    "midTextDecode", "mmbState", "mmbDecode", "callsign"))


def decoder_word(state, on) -> str:
    """A background decoder's state (mmbState, midTextState) as a word. The
    engine's state may be a whole sentence of why it is unavailable (a
    missing module, with its Python error), which is the desktop's to show:
    a TV gets "Unavailable"."""
    if not on:
        return _("Off")
    return {"off": _("Off"), "searching": _("Searching"), "tracking": _("Tracking"),
            "receiving": _("Receiving"), "listening": _("Listening"),
            "error": _("Error")}.get(str(state or "").strip().lower(), _("Unavailable"))


def lock_word(state: dict) -> tuple[str, str]:
    """rxLock as words and a tone (ENGINE-API `rxLock`)."""
    return {"locked": (_("Locked"), "good"), "searching": (_("Searching"), "warn"), "lost": (_("Lost"), "bad"),
            "hold": (_("Held"), "info"), "manual": (_("Manual"), "info"),
            "off": (_("Off"), "muted")}.get(str(state.get("rxLock")), ("", "muted"))


def _lib():
    return shacklibs.ui()


def _iso(t: float | None) -> str | None:
    if not t:
        return None
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mhz(hz) -> str | None:
    try:
        return f"{float(hz) / 1e6:.4f}"
    except (TypeError, ValueError):
        return None


def tap_offset(state: dict) -> float:
    """The spectrum's `offsetHz` for the mode (§3.7): minus where in the
    audio the mode listens, so a tap puts the signal where it decodes (an
    FT8 or FreeDV signal 1500 Hz above the dial, CW at the pitch, SSB in
    the middle of its filter). The same numbers today's Remote copies into
    ModeAudio, here taken from the engine's own registry and state."""
    mode = str(state.get("mode") or "usb")
    lo, hi = float(state.get("filterLo") or 300.0), float(state.get("filterHi") or 2700.0)
    if mode == "usb":
        centre = (lo + hi) / 2
    elif mode == "lsb":
        centre = -(lo + hi) / 2
    elif mode == "cw":
        centre = float(state.get("cwPitch") or 700.0)
    elif mode == "am":
        centre = 0.0
    else:
        info = MODES.get(mode) or next((m for k, m in MODES.items() if k.startswith(mode + "_")), None)
        centre = float(info.offset_hz) if info is not None else 0.0
    return -round(centre)


# ---------------------------------------------------------------- documents

def _tune(lib) -> dict:
    return lib.A.post("api/set", {"vfo": lib.A.HZ}, level="control")


def _receiver_hold(s, lib) -> None:
    s.hold(HOLD, start=lib.A.post(f"ui/v2/hold/{HOLD}", {"client": lib.A.CLIENT}, level="control", timeout_s=30),
           stop=lib.A.delete(f"ui/v2/hold/{HOLD}?client={{$client}}", level="control"))


def _words() -> dict:
    """The settings' choices as a person reads them (the engine's own are
    identifiers); a choice not here shows as it is."""
    return {"off": _("Off"), "fast": _("Fast"), "medium": _("Medium"), "slow": _("Slow"), "auto": _("Auto"),
            "hold": _("Hold"), "manual": _("Manual"), "middle": _("Middle"), "lower": _("Lower"),
            "upper": _("Upper")}


def _choice_of(lib, spec: dict, key: str) -> list[dict]:
    words = _words()
    return [lib.p.option(c, str(c).upper() if key == "mode" else words.get(str(c), str(c)))
            for c in (spec.get(key) or {}).get("choices") or []]


def _labelled(lib, text: str, part: dict) -> dict:
    """A slider or number with its words above it (neither part has a
    label of its own; `label` is only what a screen reader says)."""
    # Not also as the part's `label`: the Android renderer draws a
    # slider's or number's label beside its value, so it read twice ("Gain
    # (AGC off)" over "Gain (AGC off) 0", parity check 31/10/2026). The
    # caption beside it is what a screen reader finds instead.
    return lib.p.column(lib.p.text(text, style="caption", tone="muted"), part, gap="xs")


def _bookmark_keys(s, lib) -> None:
    """CH+ and CH- step the bookmarks, as on the old TV (SCREENS.md §8.2
    has the keys). A `send` (§5.1), because the step is relative to the
    dial now and no call's body may compute it (§5.2: no expressions);
    NbScreens.event does it at Control level."""
    s.key("chUp", lib.A.send("bookmark", 1, hint=_("Next bookmark")))
    s.key("chDown", lib.A.send("bookmark", -1, hint=_("Previous bookmark")))


def _decode_template(lib, wide: bool) -> dict:
    """A decode row under its slot's header ("11:30:15", on a slot's first
    row only: a part whose value is null is not drawn, §2.1). On the home
    screen's narrow side DT, the audio frequency and the country share a
    caption line; full screen they are columns under DECODE_COLUMNS."""
    p, item = lib.p, lib.item
    head = p.text(item("slotHead"), style="caption", tone="muted")
    if not wide:
        return p.column(head, p.row(p.text(item("snrText"), style="numeric", w=40),
                                    p.column(p.text(item("text"), style="mono", tone=item("tone")),
                                             p.text(item("line2"), style="caption", tone="muted"), weight=1),
                                    gap="s"), gap="xs")
    return p.column(head, p.row(*(p.text(item(f), style="numeric", w=w) for f, _t, w in DECODE_COLUMNS[:3]),
                                p.text(item("text"), style="mono", tone=item("tone"), weight=1),
                                p.text(item("country"), tone="muted", w=DECODE_COLUMNS[-1][2]), gap="s"),
                    gap="xs")


# The full-screen list's columns (field, heading, width); the message
# takes what is left between the third and the last.
DECODE_COLUMNS = (("snrText", "dB", 44), ("dtText", "DT", 48), ("freqText", "Freq", 56), ("text", "Message", None),
                  ("country", "Country", 200))


def _decode_header(lib) -> dict:
    p = lib.p
    words = {"dB": _("dB"), "DT": _("DT"), "Freq": _("Freq"), "Message": _("Message"), "Country": _("Country")}
    return p.row(*(p.text(words[t], style="caption", tone="muted", **({"w": w} if w else {"weight": 1}))
                   for _f, t, w in DECODE_COLUMNS), gap="s")


def home(srv, req):
    lib = _lib()
    A, T, p, item, local = lib.A, lib.T, lib.p, lib.item, lib.local
    spec = srv.radio.STATE.spec
    s = lib.Screen("nb/home", title=_("QO-100 NB"), req=req)
    s.collection("decodes")
    s.collection("signals")
    s.live("ui/v2/live/nb/home")
    _receiver_hold(s, lib)
    s.key("menu", A.show("rx", hint=_("Receive")))
    s.key("info", A.show("side", tab="status", hint=_("Status")))
    s.key("play", A.part("audio", "mute", hint=_("Mute")))
    _bookmark_keys(s, lib)
    set_ = lambda key, value=None, **kw: A.post("api/set", {key: A.VALUE if value is None else value},  # noqa: E731
                                               level="control", **kw)
    # Labels always: ui2.schema.json takes only a boolean for `overlay`, so
    # a per-device "Signal labels" choice (`local`, as the desktop's L key
    # is) cannot reach it yet.
    labels = True

    header = p.row(
        p.frequency("dial", None, set_("vfo"), unit="MHz", steps=STEPS, step=100, min=DIAL_MIN, max=DIAL_MAX,
                    focus={"initial": True}),
        p.choice(_choice_of(lib, spec, "mode"), None, set_("mode"), id="mode", style="menu", text=_("Mode")),
        p.badge(None, id="lock", style="pill", tone="muted", label=_("Beacon lock")),
        p.badge(_("Simulator"), id="sim", style="outline", tone="info", hidden=True),
        p.badge(None, id="onair", style="pill", tone="onAir", hidden=True),
        p.spacer(weight=1),
        p.meter(None, id="smeter", min=-120, max=-20, style="bar", label=_("Signal"), w=160,
                ticks=[{"at": -110, "label": "-110"}, {"at": -70, "label": "-70"}, {"at": -30, "label": "-30"}]),
        p.text(T.clock("utc", "hm"), id="clock", style="numeric", tone="muted"),
        gap="m", align="center")

    # The wide scope ticks and names the bookmarks and beacons, as the old
    # TV's did, and the over-power alerts; the zoom adds the skimmer's
    # signals, named once it is close enough (ohsnb/overlay.py).
    scopes = p.column(
        p.spectrum("scope", SPECTRUM, overlay=labels, layers=list(SCOPE_LAYERS),
                   tap=_tune(lib) | {"offsetHz": 0}, drag={"snapHz": 10}, weight=1),
        p.spectrum("zoom", ZOOM, overlay=labels, layers=list(ZOOM_LAYERS), tap=_tune(lib) | {"offsetHz": 0}, h=130),
        gap="xs", weight=1)

    decodes = p.column(
        p.row(p.button(_("Full screen"), A.open("nb/decodes"), icon="list", style="quiet"),
              p.button(_("Clear"), A.send("clearDecodes", hint=_("Clear")), style="quiet"), gap="s"),
        p.text(None, id="rxText", style="mono", lines=10, hidden=True),
        p.list("decodeList", from_="decodes", follow="top", keep_focus=True, template=_decode_template(lib, False),
               empty=p.empty(_("Decodes appear here in FT8, FT4, Q65 and JS8"), icon="ft8")),
        gap="s")
    signals = p.list("signalList", from_="signals", keep_focus=True, on_activate=item("action"),
                     template=p.row(p.badge(style="dot", tone=item("tone")),
                                    p.text(item("freqText"), style="numeric", w=96),
                                    p.text(item("label"), weight=1),
                                    p.text(item("snrText"), style="numeric", tone="muted"), gap="s"),
                     empty=p.empty(_("The skimmer has heard nothing yet"), icon="list"))
    status = p.scroll(p.column(
        p.field(_("Radio"), None, id="stRadio"),
        p.field(_("Beacon lock"), None, id="stLock"),
        p.field(_("Beacon"), None, id="stBeacon"),
        p.field(_("Segment"), None, id="stSegment"),
        p.field(_("Receive"), None, id="stReceive"),
        p.field(_("Transmit"), None, id="stTransmit"),
        p.field(_("Recording"), None, id="stRecording"),
        p.field(_("Version"), f"{srv.info.name} {srv.info.version}", id="stVersion"),
        gap="xs"))
    side = p.tabs("side", [p.tab("decodes", _("Decodes"), decodes, icon="ft8"),
                           p.tab("signals", _("Signals"), signals, icon="list"),
                           p.tab("status", _("Status"), status, icon="info")],
                  selected="decodes", focus_selects=True, w=330)

    # The bookmarks (the engine's memories: NB's band-plan presets, then the
    # operator's) as a menu, its value (the one the radio is on) live. The
    # options are in the document as well as patched live (Follower.
    # bookmarks): the Android renderer at 7bfb932 crashed on a choice with
    # no options, the moment between the document and the snap.
    controls = p.row(
        p.choice(bookmark_options(bookmark_list(srv.radio)), None, A.post("api/recall", {"name": A.VALUE}, level="control"), id="bookmark", style="menu",
                 text=_("Bookmark")),
        p.toggle(_("Noise reduction"), None, set_("nr"), id="nr"),
        p.button(_("Receive"), A.show("rx"), icon="more", style="quiet"),
        p.button(_("Signals"), A.open("nb/signals"), icon="list", style="quiet"),
        p.button(_("Beacon"), A.open("nb/beacon"), icon="satellite", style="quiet"),
        p.button(_("Mute"), A.part("audio", "mute"), icon="mute", style="quiet"),
        gap="s")

    # Transmit (§7), only while SCREENS_TRANSMIT: see its comment. Placed,
    # never keyed here. The renderer draws ptt only off a TV and txArm on a
    # TV only when the launcher's tile says this TV may transmit digital;
    # `forms` says the same so a TV's layout leaves no gap.
    transmit = None
    if SCREENS_TRANSMIT:
        transmit = p.row(
            p.ptt("ptt", "api/ptt", "api/ptt/heartbeat", forms=["phone", "tablet"]),
            p.tx_arm("txArm", "api/autotx", "api/ptt/heartbeat", digital=True,
                     choices=[{"value": "cq", "text": _("Call CQ"), "body": {"cq": True}}]),
            p.text(None, id="txInfo", tone="muted", weight=1),
            p.button(_("Transmit settings"), A.show("tx"), style="quiet", forms=["phone", "tablet"]),
            p.button(_("Halt"), A.post("api/halt", {}, level="control"), icon="stop", tone="bad", style="quiet"),
            gap="s", align="center")

    rx_panel = p.panel("rx", p.scroll(p.column(
        p.text(_("Receive"), style="title"),
        # Segmented choices get a caption too: their `text` is not drawn
        # over the buttons, so the panel's first row had no name.
        _labelled(lib, _("AGC"), p.choice(_choice_of(lib, spec, "agc"), None, set_("agc"), id="agc",
                                          style="segmented", text=_("AGC"))),
        _labelled(lib, _("Gain (AGC off)"), p.slider(None, -20, 60, set_("rfGain"), id="rfGain", step=1)),
        _labelled(lib, _("Filter low (Hz)"), p.slider(None, 0, 1000, set_("filterLo"), id="filterLo", step=50)),
        _labelled(lib, _("Filter high (Hz)"), p.slider(None, 1000, 4000, set_("filterHi"), id="filterHi",
                                                       step=50)),
        p.toggle(_("Noise blanker"), None, set_("nb"), id="nb"),
        _labelled(lib, _("Noise reduction strength"), p.slider(None, 0, 100, set_("nrStrength"), id="nrStrength",
                                                               step=5)),
        p.toggle(_("RIT"), None, set_("ritOn"), id="ritOn"),
        _labelled(lib, _("RIT offset"), p.number(None, set_("rit"), id="rit", min=-5000, max=5000, step=10,
                                                 unit="Hz", style="stepper")),
        _labelled(lib, _("Beacon lock"), p.choice(_choice_of(lib, spec, "beaconMode"), None, set_("beaconMode"),
                                                  id="beaconMode", style="segmented", text=_("Beacon lock"))),
        _labelled(lib, _("Lock to"), p.choice(_choice_of(lib, spec, "beacon"), None, set_("beacon"), id="beacon",
                                              style="segmented", text=_("Lock to"))),
        p.choice([p.option(v, f"{v // 1000} kHz") for v in (2000, 5000, 10000, 25000, 50000)], None,
                 set_("zoomSpanHz"), id="zoomSpan", style="stepper", text=_("Zoom span")),
        gap="s")), slot="end", w=340, surface="glass")

    tx_panel = None
    if SCREENS_TRANSMIT:
        tx_panel = p.panel("tx", p.scroll(p.column(
            p.text(_("Transmit"), style="title"),
            _labelled(lib, _("Transmit gain (dB)"), p.slider(
                None, -89.75, 0, A.post("api/set", {"txGain": A.VALUE}, level="control", tx=True, lease="ptt"),
                id="txGain", step=0.25)),
            _labelled(lib, _("Microphone gain (dB)"), p.slider(
                None, -20, 30, A.post("api/set", {"micGain": A.VALUE}, level="control", tx=True, lease="ptt"),
                id="micGain", step=1)),
            p.toggle(_("Split"), None, A.post("api/set", {"split": A.VALUE}, level="control", tx=True, lease="ptt"),
                     id="split"),
            _labelled(lib, _("CW speed"), p.number(
                None, A.post("api/set", {"cwWpm": A.VALUE}, level="control", tx=True, lease="txArm"),
                id="cwWpm", min=5, max=50, step=1, unit="wpm", style="stepper")),
            gap="s")), slot="end", w=340, surface="glass", forms=["phone", "tablet"])

    s.root = p.stack(
        p.column(header,
                 p.text(None, id="sub", style="caption", tone="muted"),
                 p.banner(None, id="problem", tone="warn"),
                 p.split(scopes, side, ratio=0.66, compact="stack", weight=1),
                 controls,
                 *([transmit] if transmit else []),
                 p.audio("audio", "api/audio/rx", controls="mute", autoplay=True),
                 gap="s", pad="s", align="fill"),
        rx_panel, *([tx_panel] if tx_panel else []),
        p.hints(id="hints", align="bottom-start"))
    return s


def signals(srv, req):
    lib = _lib()
    A, p, item = lib.A, lib.p, lib.item
    s = lib.Screen("nb/signals", title=_("Band activity"), req=req)
    s.collection("signals")
    s.collection("alerts")
    s.live("ui/v2/live/nb/signals")
    _receiver_hold(s, lib)
    s.key("play", A.part("audio", "mute", hint=_("Mute")))
    row = p.row(p.badge(style="dot", tone=item("tone")),
                p.text(item("freqText"), style="numeric", w=110),
                p.column(p.text(item("label"), style="title", size="s"),
                         p.text(item("line2"), tone="muted", style="caption"), weight=1),
                p.text(item("snrText"), style="numeric", tone="muted"), gap="s")
    s.root = p.column(
        p.row(p.text(_("Band activity"), style="title"), p.spacer(weight=1),
              p.frequency("dial", None, A.post("api/set", {"vfo": A.VALUE}, level="control"), unit="MHz",
                          steps=STEPS, step=100, min=DIAL_MIN, max=DIAL_MAX),
              p.text(None, id="state", tone="muted"), gap="m", align="center"),
        p.spectrum("scope", SPECTRUM, overlay=True, layers=["band", "dial"],
                   tap=_tune(lib) | {"offsetHz": 0}, h=150),
        p.split(
            p.section(_("Signals on the transponder"),
                      p.list("signalList", from_="signals", keep_focus=True, on_activate=item("action"),
                             focus={"initial": True}, template=row,
                             empty=p.empty(_("The skimmer has heard nothing yet"), icon="list"))),
            p.section(_("Over the beacon, and LEILA"),
                      p.list("alertList", from_="alerts", keep_focus=True, on_activate=item("action"),
                             template=row, empty=p.empty(_("Nothing over the beacon in the last 30 minutes"),
                                                         icon="info"))),
            ratio=0.55, compact="tabs", weight=1),
        p.audio("audio", "api/audio/rx", controls="mute", autoplay=True),
        p.hints(id="hints"),
        gap="s", pad="s")
    return s


def beacon(srv, req):
    lib = _lib()
    p, item = lib.p, lib.item
    s = lib.Screen("nb/beacon", title=_("QO-100 beacon"), req=req)
    s.collection("blocks")
    s.collection("spots")
    s.live("ui/v2/live/nb/beacon")
    s.root = p.column(
        p.row(p.text(_("QO-100 beacon"), style="title"), p.spacer(weight=1),
              p.field(_("Middle beacon text"), None, id="midState"),
              p.field(_("Multimedia beacon"), None, id="mmbState"), gap="m", align="center"),
        p.split(
            p.grid(id="blockGrid", from_="blocks", columns={"tv": 2, "tablet": 2, "phone": 1}, gap="s",
                   template=p.card(p.column(p.text(item("title"), style="caption", tone="muted"),
                                            p.text(item("text"), style="mono", lines=8))),
                   empty=p.empty(_("Waiting for the middle beacon's text (a block every 25 s)"), icon="satellite")),
            p.section(_("DX cluster"),
                      p.list("spotList", from_="spots", follow="top", keep_focus=True, on_activate=item("action"),
                             focus={"initial": True},
                             template=p.row(p.text(item("utc"), style="numeric", tone="muted", w=48),
                                            p.text(item("dxcall"), style="title", size="s", w=100),
                                            p.text(item("qrgText"), style="numeric", w=96),
                                            p.text(item("comment"), tone="muted", weight=1), gap="s"),
                             empty=p.empty(_("No DX-cluster spots from the beacon yet"), icon="list"))),
            ratio=0.6, compact="tabs", weight=1),
        gap="s", pad="s")
    return s


def decodes(srv, req):
    """The decodes full screen, as the old TV's FT8 page: every column, a
    header row per slot, CW/RTTY/PSK as running text in its place."""
    lib = _lib()
    A, T, p = lib.A, lib.T, lib.p
    s = lib.Screen("nb/decodes", title=_("Decodes"), req=req)
    s.collection("decodes")
    s.live("ui/v2/live/nb/decodes")
    _receiver_hold(s, lib)
    s.key("play", A.part("audio", "mute", hint=_("Mute")))
    _bookmark_keys(s, lib)
    s.root = p.column(
        p.row(p.text(_("Decodes"), style="title"),
              p.frequency("dial", None, A.post("api/set", {"vfo": A.VALUE}, level="control"), unit="MHz",
                          steps=STEPS, step=100, min=DIAL_MIN, max=DIAL_MAX),
              p.badge(None, id="modeBadge", style="pill", tone="accent"),
              p.spacer(weight=1),
              p.button(_("Clear"), A.send("clearDecodes"), style="quiet"),
              p.text(T.clock("utc", "hms"), style="numeric", tone="muted"), gap="m", align="center"),
        _decode_header(lib) | {"forms": ["tv", "tablet"]},
        p.text(None, id="rxText", style="mono", hidden=True, weight=1),
        # Columns on a TV or tablet; a phone is too narrow for five (the
        # country wrapped under the row, reading as the next row's), so
        # it gets home's two-line row.
        p.list("decodeList", from_="decodes", follow="top", keep_focus=True, focus={"initial": True},
               template=_decode_template(lib, True), weight=1, forms=["tv", "tablet"],
               empty=p.empty(_("Decodes appear here in FT8, FT4, Q65 and JS8"), icon="ft8")),
        p.list("decodeListNarrow", from_="decodes", follow="top", keep_focus=True, focus={"initial": True},
               template=_decode_template(lib, False), weight=1, forms=["phone"],
               empty=p.empty(_("Decodes appear here in FT8, FT4, Q65 and JS8"), icon="ft8")),
        p.audio("audio", "api/audio/rx", controls="mute", autoplay=True),
        p.hints(id="hints"),
        gap="s", pad="s")
    return s


SCREENS = {"nb/home": home, "nb/signals": signals, "nb/beacon": beacon, "nb/decodes": decodes}


# ---------------------------------------------------------------- live state

class _Unopened:
    """Where changes to a screen no client has opened go: nowhere."""

    def __getattr__(self, op):
        return lambda *a, **kw: None

    def view(self) -> dict:
        return {"collections": {}}


class NbScreens:
    """AppInfo.screens for QO-100 NB: what ohscore/server/uiv2.py asks of
    an app's screens (descriptor, status, build, poll, opened, feed, hold,
    gone). One per server, made by ohsnb/server.info()."""

    def __init__(self):
        self.lock = threading.RLock()
        self.channels: dict[str, object] = {}
        self.follower: Follower | None = None

    # -- the routes
    def descriptor(self, srv, req) -> dict:
        lib = _lib()
        forms = ["tv", "phone", "tablet"]
        return lib.descriptor([
            lib.entry(ENTRY, _("QO-100 NB"), "nb/home", icon="dish", forms=forms),
            lib.entry("signals", _("Band activity"), "nb/signals", icon="list", forms=forms),
            lib.entry("beacon", _("QO-100 beacon"), "nb/beacon", icon="satellite", forms=forms),
        ], app=srv.info.app_id, kind=srv.info.kind, name=srv.info.name, version=srv.info.version)

    def status(self, srv, req) -> dict:
        st = srv.radio.state()
        if st.get("keyed"):
            main = (_("On the air"), "onAir")
        elif not st.get("running"):
            main = (srv.radio_error or _("Stopped"), "warn")
        else:
            word, tone = lock_word(st)
            mode = str(st.get("mode") or "").upper()
            main = (" · ".join(x for x in (mode, word) if x), tone)
        sk = (_("Skimmer off"), "muted") if not st.get("skimDecode") else (_("Skimming"), "default")
        mid = str(st.get("midTextState") or "")
        return _lib().status({ENTRY: main, "signals": sk,
                              "beacon": (_("Receiving") if mid == "receiving" else _("Listening"),
                                         "good" if mid == "receiving" else "muted")})

    def build(self, srv, sid: str, params: dict, req):
        make = SCREENS.get(sid)
        if make is None:
            raise UnknownScreen(sid)
        return make(srv, req)

    def poll(self, srv, sid: str, params: dict, req) -> dict:
        raise UnknownScreen(sid)            # every NB screen is live, none polled

    def opened(self, srv, sid: str, params: dict, channel) -> None:
        with self.lock:
            self.channels[sid] = channel
            if self.follower is None:
                self.follower = Follower(self, srv)
            # A channel made late starts from the engine as it is now.
            self.follower.stale = True
        channel.on_event(lambda client, name, value: self.event(srv, client, name, value))

    def event(self, srv, client, name, value) -> None:
        """A `send` action's event from a live socket (SCREENS.md §5.1):
        `bookmark` (CH+/CH-, value +1 or -1) recalls the next bookmark,
        `clearDecodes` empties the decode lists. Both at Control level, by
        the level the controller's proxy gave the socket: a view-only TV
        changes neither the radio nor what another screen shows."""
        req = getattr(client, "req", None)
        if not shack.level_at_least(str(getattr(req, "level", "") or ""), "control"):
            self.channel("nb/home").toast(_("View only: this device cannot change the radio"), tone="warn", s=4)
            return
        f = self.follower
        if name == "clearDecodes" and f is not None:
            f.clear_decodes()
        elif name == "bookmark" and value in (1, -1):
            st = srv.radio.state()
            m = step_bookmark(srv.radio.memories(), st.get("vfo"), int(value))
            if m is None:
                return                      # at the end of the band, as the old TV stopped
            try:
                srv.radio.recall(str(m["name"]))
            except Exception as e:  # noqa: BLE001 - a refusal is the operator's to read, not the socket's end
                self.channel("nb/home").toast(str(e), tone="warn", s=6)

    def feed(self, srv, sid: str, params: dict, channel) -> None:
        """The pump's call, every half second for each channel with a client
        (uiv2.Live): one pass over the engine's feeds serves all three."""
        with self.lock:
            f = self.follower
        if f is not None:
            f.pump()

    def gone(self, srv, client: str) -> list[str]:
        return []                           # NB has no client presence (module docstring)

    def channel(self, sid: str):
        return self.channels.get(sid) or _Unopened()

    def hold(self, srv, name: str, method: str, body: dict, params: dict, client):
        """The receiver hold (module docstring). Answers as SCREENS.md §5.3
        and §6: {} or the contract's error with remedy `actions`, as a
        shack_ui Response, so a remedy's path is never given a `url`."""
        lib = _lib()
        if name != HOLD:
            raise UnknownScreen(name)
        if method == "DELETE":
            return lib.serve_json({})
        if srv.parked:
            srv.wake(f"ui/2 hold by {client or '-'}")
        if srv.radio.state().get("running"):
            return lib.serve_json({})
        if not srv.wanted:
            return lib.serve_json({"error": srv.radio_error or _("The radio is stopped."), "code": "receiver_stopped",
                                   "actions": [lib.A.post("api/start", {}, level="control",
                                                          text=_("Start the radio"))]}, 409)
        return lib.serve_json({"error": srv.radio_error or _("The radio is starting."), "code": "receiver_starting"},
                              503)


def _hms(t) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%H:%M:%S") if t else ""


def decode_tone(text: str, mycall: str, low_confidence: bool = False) -> str | None:
    """A decode's tone: one addressed to this station stands out most
    (`accent`), then a CQ (`info`, the old TV's blue rows), then an
    uncertain decode is quiet. The renderer's theme picks the colours."""
    words = text.split()
    if mycall and mycall in words:
        return "accent"
    if words[:1] == ["CQ"]:
        return "info"
    return "muted" if low_confidence else None


def _decode_item(ev: dict, mycall: str) -> dict:
    """One decode as a row: what the old TV showed (dB, the message, the
    country) plus DT and the audio frequency, all formatted here; `slot`
    is the slot it belongs to, `slotHead` set only on a slot's first row
    (Follower.event)."""
    text = str(ev.get("text") or "")
    t = ev.get("slot") or ev.get("t")
    snr, dt, df = ev.get("snr"), ev.get("dt"), ev.get("df")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    dt_text = f"{dt:+.1f}" if num(dt) else ""
    df_text = f"{df:.0f}" if num(df) else ""
    country = str(ev.get("country") or "")
    line2 = " · ".join(x for x in (country, _("{dt} s").format(dt=dt_text) if dt_text else "",
                                   _("{hz} Hz").format(hz=df_text) if df_text else "") if x)
    return {"at": _iso(ev.get("t")), "slot": _hms(t), "slotHead": None, "timeText": _hms(t),
            "snrText": f"{snr:+.0f}" if num(snr) else "", "dtText": dt_text, "freqText": df_text,
            "text": text, "call": ev.get("call"), "country": country or None, "line2": line2 or None,
            "tone": decode_tone(text, mycall, bool(ev.get("lowConfidence"))), "mode": ev.get("mode")}


def bookmark_list(radio) -> list[dict]:
    """The memories a bookmark can be, in frequency order."""
    try:
        marks = [m for m in radio.memories() if m.get("name") and isinstance(m.get("dl"), (int, float))]
    except Exception:  # noqa: BLE001 - no memories is an empty picker, never a stopped screen
        return []
    return sorted(marks, key=lambda m: m["dl"])


def bookmark_options(marks: list[dict], near: str | None = None) -> list[dict]:
    """The picker's options; `near` names the bookmark nearest a dial that
    is on none, whose option then says so (Follower.bookmarks)."""
    return [{"value": m["name"], "text": (_("Near {name}").format(name=m["name"]) if m["name"] == near
                                          else f"{m['name']} · {_mhz(m['dl'])}")} for m in marks]


def nearest_bookmark(memories: list[dict], hz) -> dict | None:
    marks = [m for m in memories if isinstance(m.get("dl"), (int, float))]
    if not marks or not isinstance(hz, (int, float)):
        return None
    return min(marks, key=lambda m: abs(m["dl"] - hz))


def current_bookmark(memories: list[dict], hz, mode: str) -> dict | None:
    """The bookmark the radio is on: the dial within BOOKMARK_TOL_HZ and
    the same mode."""
    if not isinstance(hz, (int, float)):
        return None
    return next((m for m in memories if isinstance(m.get("dl"), (int, float))
                 and abs(m["dl"] - hz) <= BOOKMARK_TOL_HZ and m.get("mode") == mode), None)


def step_bookmark(memories: list[dict], hz, by: int) -> dict | None:
    """CH+ (by > 0) and CH-: the next bookmark above the dial or below it,
    more than BOOKMARK_TOL_HZ away so the one the radio is on is passed
    over. None at either end, as the old TV stopped there rather than
    wrapping from the upper beacon to the lower."""
    marks = sorted((m for m in memories if isinstance(m.get("dl"), (int, float)) and m.get("name")),
                   key=lambda m: m["dl"])
    if not marks:
        return None
    if not isinstance(hz, (int, float)):
        return marks[0] if by > 0 else marks[-1]
    if by > 0:
        return next((m for m in marks if m["dl"] > hz + BOOKMARK_TOL_HZ), None)
    return next((m for m in reversed(marks) if m["dl"] < hz - BOOKMARK_TOL_HZ), None)


def _signal_item(e: dict) -> dict:
    f = e.get("dial") or e.get("f")
    action = {"do": "call", "method": "POST", "path": "api/set", "level": "control",
              "body": {"changes": {"vfo": float(f), **({"mode": e["mode"]} if e.get("mode") else {})}}} if f else None
    kind = str(e.get("kind") or "signal")
    calls = e.get("calls") or []
    line2 = " · ".join(x for x in (kind, ", ".join(calls[:4]) if calls else "",
                                   _("measured") if e.get("exact") == "twice" else "") if x)
    return {"label": str(e.get("label") or kind), "freqText": _mhz(e.get("f")), "line2": line2,
            "snrText": f"{e['snr']:.0f} dB" if isinstance(e.get("snr"), (int, float)) else "",
            "tone": "good" if e.get("active") else "muted", "tags": [kind] + (["active"] if e.get("active") else []),
            "at": _iso(e.get("last")), "action": action}


def _alert_item(e: dict) -> dict:
    if e.get("kind") == "leila":
        label = _("LEILA?")
        line2 = _("{db:+.1f} dB against the beacon").format(db=e["levelDb"]) if isinstance(
            e.get("levelDb"), (int, float)) else ""
    else:
        label = _("{db:+.1f} dB over the beacon").format(db=float(e.get("excessDb") or 0.0))
        line2 = (_("LEILA sounded") if e.get("leila") else "")
    if e.get("call"):
        line2 = " · ".join(x for x in (str(e["call"]), line2) if x)
    f = e.get("freq")
    return {"label": label, "freqText": _mhz(f), "line2": line2, "snrText": "",
            "tone": "bad" if e.get("active") else "warn", "at": _iso(e.get("end") or e.get("start")),
            "action": {"do": "call", "method": "POST", "path": "api/set", "level": "control",
                       "body": {"changes": {"vfo": float(f)}}} if f else None}


class Follower:
    """The engine's feeds into the screens' channels, driven by the pump
    (NbScreens.feed), which calls only while a channel has a client.

    The feeds are drained only from those calls, so with nobody watching
    nothing drains them and the transmit watchdog is never told a UI is
    alive that is not (module docstring). After a gap (nobody watching for
    IDLE_S) the subscriptions are taken again from empty and every screen
    refreshed from the engine's state, so a returning client never sees an
    hour-old backlog of decodes replayed as new."""

    IDLE_S = 5.0
    MIN_S = 0.2         # three channels' feeds in one pump pass drain once

    def __init__(self, screens: NbScreens, srv):
        self.screens, self.srv, self.radio = screens, srv, srv.radio
        self.lock = threading.Lock()
        self.feeds: dict = {}
        self.last = 0.0
        self.stale = True
        self.text = ""
        self.text_mode = ""
        self.decode_keys: list[str] = []
        self.slots: dict[int, list[str]] = {}       # slot start (UNIX s) -> its rows' keys, in arrival order
        self.marks: tuple | list = []               # (memories, the "Near" one) as the picker last showed them
        self.spot_keys: list[str] = []
        self.n = 0
        self.last_state: dict = {}
        self.server_due = 0.0

    def home(self):
        return self.screens.channel("nb/home")

    def sig(self):
        return self.screens.channel("nb/signals")

    def bcn(self):
        return self.screens.channel("nb/beacon")

    def dec(self):
        return self.screens.channel("nb/decodes")

    def decode_views(self):
        """The two screens that list decodes and show the running text."""
        return self.home(), self.dec()

    def pump(self) -> None:
        with self.lock:
            now = time.monotonic()
            if now - self.last > self.IDLE_S:
                for f in self.feeds.values():
                    self.radio.unsubscribe(f)
                kinds = [k for k in FEEDS if k in self.radio.FEED_KINDS]
                self.feeds = {k: self.radio.subscribe(k, 256) for k in kinds}
                self.stale = True
            elif now - self.last < self.MIN_S and not self.stale:
                return
            self.last = now
            if self.stale:
                self.stale = False
                self.refresh()
            self.tick()

    # -- whole-state refresh (a new channel, a client after a gap)
    def refresh(self) -> None:
        self.text_mode = ""             # state() then sets which decode part shows
        self.marks = []                 # and server_bits the bookmarks again
        self.state(dict(self.radio.state()))
        self.server_due = 0.0
        ov = getattr(self.radio, "overpower_view", None)
        if ov is not None:
            self.alerts(ov().get("events") or [])
        self.saved_blocks()

    def tick(self) -> None:
        f = self.feeds
        changed: dict = {}
        for item in f["state"].drain() if "state" in f else []:
            changed.update(item.get("changes") or {})
        if changed.keys() & SHOWN:
            self.state(dict(self.radio.state()))
        now = time.monotonic()
        if now >= self.server_due:
            self.server_due = now + 1.0
            self.server_bits()
        if "meter" in f:
            m = f["meter"].drain()
            if m and isinstance(m[-1].get("rx"), (int, float)):
                self.home().set("smeter", value=m[-1]["rx"])
        for ev in f["events"].drain() if "events" in f else []:
            self.event(ev)
        for t in f["toast"].drain() if "toast" in f else []:
            text = t.get("text") if isinstance(t, dict) else str(t)
            if text:
                tone = {"error": "bad", "warn": "warn"}.get(t.get("level") if isinstance(t, dict) else "", None)
                self.home().toast(text, tone=tone, s=6)
        ops = f["overpower"].drain() if "overpower" in f else []
        if ops:
            last = ops[-1]
            self.alerts(last.get("events") if isinstance(last, dict) and "events" in last else last)
        sk = f["skim"].drain() if "skim" in f else []
        if sk:
            self.skim(sk[-1].get("entries") or [])
        for b in f["midtext"].drain() if "midtext" in f else []:
            self.block(b)
        for m in f["mmb"].drain() if "mmb" in f else []:
            self.mmb(m)

    # -- the parts each state change touches
    def state(self, st: dict) -> None:
        h = self.home()
        mode = str(st.get("mode") or "")
        h.set("dial", value=st.get("vfo"))
        h.set("mode", value=mode)
        offset = {"offsetHz": tap_offset(st)}
        tap = {"do": "call", "method": "POST", "path": "api/set", "body": {"vfo": "$hz"}, "level": "control"}
        h.set("scope", tap=tap | offset)
        h.set("zoom", tap=tap | offset)
        word, tone = lock_word(st)
        snr = st.get("rxSnr")
        lock_text = " · ".join(x for x in (word, f"{snr:.0f} dB" if isinstance(
            snr, (int, float)) else "") if x) or None
        h.set("lock", text=lock_text, tone=tone)
        h.set("sim", hidden=not st.get("simulator") and str(st.get("device")) != "sim")
        keyed = bool(st.get("keyed"))
        h.set("onair", hidden=not keyed, text=_("On the air") if keyed else None)
        sub = [str(st.get("segment") or "")]
        if st.get("ritOn") and st.get("rit"):
            sub.append(_("RIT {hz:+.0f} Hz").format(hz=float(st["rit"])))
        h.set("sub", value=" · ".join(x for x in sub if x) or None)
        for key in ("nr", "nb", "ritOn", "split"):
            if SCREENS_TRANSMIT or key not in TX_IDS:
                h.set(key, value=bool(st.get(key)))
        for key in ("agc", "beaconMode", "beacon"):
            h.set(key, value=st.get(key))
        for key in ("rfGain", "filterLo", "filterHi", "nrStrength", "rit", "txGain", "micGain", "cwWpm"):
            if SCREENS_TRANSMIT or key not in TX_IDS:
                h.set(key, value=st.get(key))
        h.set("zoomSpan", value=int(st["zoomSpanHz"]) if st.get("zoomSpanHz") else None)
        # Running text in CW, RTTY and PSK; the list in the slot modes.
        if mode != self.text_mode:
            # Leaving the slot modes clears their decodes, as the old TV
            # closed its decode panel: FT8 rows lingering under an SSB
            # contact read as something heard now. FT8 to FT4 keeps them.
            if self.text_mode and mode not in SLOT_MODES:
                self.clear_decodes()
            self.text_mode, self.text = mode, ""
            for v in self.decode_views():
                v.set("rxText", value=None, hidden=mode not in TEXT_MODES)
                v.set("decodeList", hidden=mode in TEXT_MODES)
            self.dec().set("decodeListNarrow", hidden=mode in TEXT_MODES)
        d = self.dec()
        d.set("dial", value=st.get("vfo"))
        d.set("modeBadge", text=mode.upper() or None)
        # Status fields.
        running = st.get("running")
        # The device by its setting's name: deviceStatus is the driver's own
        # dict, for the S-meter's calibration, not for people.
        h.set("stRadio", value=" · ".join(x for x in (
            _("Running") if running else (self.srv.radio_error or _("Stopped")), str(st.get("device") or "")) if x))
        h.set("stLock", value=lock_text)
        h.set("stBeacon", value=" · ".join(str(x) for x in (st.get("beaconUsed"), f"{st['beaconLevel']:.0f} dB"
                                                            if isinstance(st.get("beaconLevel"), (int, float))
                                                            else None) if x) or None)
        h.set("stSegment", value=st.get("segment") or None)
        h.set("stReceive", value=_mhz(st.get("rxDial")))
        h.set("stTransmit", value=_("On the air") if keyed else (st.get("txBlocked") or _("Receiving")))
        h.set("stRecording", value=(st.get("recFile") or _("Recording")) if st.get("recording") else _("No"))
        s = self.sig()
        s.set("dial", value=st.get("vfo"))
        s.set("scope", tap=tap | offset)
        s.set("state", value=_("Skimmer off: Settings › Band") if not st.get("skimDecode")
              else str(st.get("skimState") or "") or None)
        b = self.bcn()
        b.set("midState", value=decoder_word(st.get("midTextState"), st.get("midTextDecode")))
        b.set("mmbState", value=decoder_word(st.get("mmbState"), st.get("mmbDecode")))
        self.last_state = st

    def server_bits(self) -> None:
        """What the server holds rather than the engine (the radio's and
        transmit's errors, Enable TX), which no feed announces: once a
        second."""
        h = self.home()
        st = self.last_state
        h.set("problem", text=self.srv.radio_error or self.srv.tx_error or st.get("error") or None)
        self.bookmarks(st)
        if not SCREENS_TRANSMIT:
            return                  # txInfo is not in the document
        at = self.srv.digi.view()
        tx = []
        if at.get("armed"):
            tx.append(_("Enable TX armed"))
            if at.get("next"):
                tx.append(str(at["next"]))
        if self.srv.tx_error:
            tx.append(str(self.srv.tx_error))
        h.set("txInfo", value=" · ".join(tx) or None)

    def bookmarks(self, st: dict) -> None:
        """The bookmark picker's options (when the memories changed: the
        document has those of when it was built) and its value, the
        bookmark the radio is on (null: none chosen)."""
        marks = bookmark_list(self.radio)
        cur = current_bookmark(marks, st.get("vfo"), str(st.get("mode") or ""))
        # Off every bookmark the value is the nearest, its option reading
        # "Near SSB lower": a menu whose value is none of its options shows
        # its first (the Android renderer showed "Lower beacon" at
        # 10489.668) and steps from there, where the old TV stepped from
        # the dial.
        near = None if cur else nearest_bookmark(marks, st.get("vfo"))
        shown = (marks, near["name"] if near else None)
        h = self.home()
        if shown != self.marks:
            self.marks = shown
            h.set("bookmark", options=bookmark_options(*shown))
        pick = cur or near
        h.set("bookmark", value=pick["name"] if pick else None)

    def clear_decodes(self) -> None:
        for v in self.decode_views():
            if self.decode_keys:
                v.rm("decodes", *self.decode_keys)
            v.order("decodes", [])
            v.set("rxText", value=None)
        self.decode_keys, self.slots, self.text = [], {}, ""

    def event(self, ev: dict) -> None:
        if not isinstance(ev, dict) or "tx" in ev or ev.get("error"):
            return          # our own over, or a decoder's failure: not a station heard
        mode = str(ev.get("mode") or "")
        if mode in TEXT_MODES and ev.get("text"):
            if mode != self.text_mode:
                self.text_mode, self.text = mode, ""
            self.text = (self.text + str(ev["text"]))[-MAX_TEXT:]
            for v in self.decode_views():
                v.set("rxText", value=self.text, hidden=False)
            return
        if mode in SLOT_MODES and ev.get("text"):
            t = ev.get("slot") or ev.get("t") or time.time()
            self.decode(_decode_item(ev, str(self.last_state.get("callsign") or "")), round(float(t)))

    def decode(self, row: dict, slot: int) -> None:
        """A slot decode into both lists: slots newest first, each slot's
        rows in the order the decoder gave them under one header row (its
        first row's `slotHead`), as the old TV grouped them. A slot's header
        never moves, since rows join a slot at its end."""
        self.n += 1
        key = f"d{self.n}"
        rows = self.slots.setdefault(slot, [])
        if not rows:
            row = row | {"slotHead": row["slot"]}
        rows.append(key)
        # By the slot's time, not its "HH:MM:SS": at midnight a new slot
        # would sort under the old day's and be trimmed as it arrived.
        order = [k for sl in sorted(self.slots, reverse=True) for k in self.slots[sl]]
        gone = order[MAX_DECODES:]
        if gone:
            order = order[:MAX_DECODES]
            dead = set(gone)
            self.slots = {sl: [k for k in ks if k not in dead] for sl, ks in self.slots.items()}
            self.slots = {sl: ks for sl, ks in self.slots.items() if ks}
        for v in self.decode_views():
            v.up("decodes", key, row)
            if gone:
                v.rm("decodes", *gone)
            v.order("decodes", order)
        self.decode_keys = order

    def skim(self, entries: list) -> None:
        items = {}
        for e in entries:
            if isinstance(e, dict) and e.get("id") is not None:
                items[str(e["id"])] = _signal_item(e)
        keys = list(items)[:MAX_SIGNALS]
        for v in (self.home(), self.sig()):
            old = [k for k in (v.view().get("collections", {}).get("signals", {}).get("items") or {})
                   if k not in items or k not in keys]
            if old:
                v.rm("signals", *old)
            for k in keys:
                v.put("signals", k, items[k])
            v.order("signals", keys)

    def alerts(self, events: list) -> None:
        if not isinstance(events, list):
            return
        items = {str(e["id"]): _alert_item(e) for e in events if isinstance(e, dict) and e.get("id") is not None}
        v = self.sig()
        old = [k for k in (v.view().get("collections", {}).get("alerts", {}).get("items") or {}) if k not in items]
        if old:
            v.rm("alerts", *old)
        for k, it in items.items():
            v.put("alerts", k, it)
        # Open ones first, then newest (as api/overpower lists them).
        v.order("alerts", list(items))

    def block(self, b: dict) -> None:
        if not isinstance(b, dict) or not b.get("type"):
            return
        t = str(b["type"])
        self.bcn().put("blocks", t, {"title": _("Block {t}").format(t=t) + (f" · {b['snr']:.0f} dB" if isinstance(
            b.get("snr"), (int, float)) else ""), "text": str(b.get("text") or ""), "at": _iso(b.get("t"))})
        self.bcn().order("blocks", sorted(self.bcn().view().get("collections", {}).get("blocks", {})
                                          .get("items", {})))

    def saved_blocks(self) -> None:
        """The last block of each type the beacon sent, as NB keeps them on
        disk, so the screen is not empty for the first 100 s."""
        try:
            from ohsnb.beacontext import saved_blocks
            got = saved_blocks(Path(self.radio.data_dir) / "midbeacon")
        except Exception:  # noqa: BLE001 - nothing kept is an empty grid
            return
        for t, (text, mtime) in sorted(got.items()):
            self.block({"type": t, "text": text, "t": mtime})

    def mmb(self, m: dict) -> None:
        if not isinstance(m, dict) or m.get("kind") != "dx":
            return
        try:
            khz = float(m.get("qrg_khz") or 0)
        except (TypeError, ValueError):
            khz = 0.0
        self.n += 1
        key = f"s{self.n}"
        on_nb = DIAL_MIN <= khz * 1000 <= DIAL_MAX
        self.bcn().up("spots", key, {
            "utc": str(m.get("utc") or ""), "dxcall": str(m.get("dxcall") or ""),
            "qrgText": f"{khz:.1f}" if khz else "", "comment": str(m.get("comment") or ""),
            "reporter": str(m.get("reporter") or ""), "at": _iso(m.get("t") or time.time()),
            # Only a spot on the narrowband transponder can be tuned to.
            "action": {"do": "call", "method": "POST", "path": "api/set", "level": "control",
                       "body": {"changes": {"vfo": khz * 1000}}} if on_nb else None})
        self.spot_keys.insert(0, key)
        if len(self.spot_keys) > MAX_SPOTS:
            self.bcn().rm("spots", *self.spot_keys[MAX_SPOTS:])
            del self.spot_keys[MAX_SPOTS:]
        self.bcn().order("spots", list(self.spot_keys))
