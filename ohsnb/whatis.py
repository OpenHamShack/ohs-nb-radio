"""What is the signal under the mouse, and the one click that does
something with it: the "What is this?" card a right-click on either scope
opens (ohsnb/ui/whatis.py; docs/ui-overhaul-2026-10.md section 5.6).

An operator looking at the waterfall sees a trace and wants to know what it
is and how to hear it. The band skimmer (ohsnb/dsp/skim.py) has usually
already worked that out - it names calling windows, beacons, voices, CW,
carriers and data, and the signals the surveys found but NB cannot decode -
and the band plan says what the segment is for. This puts the two together
for one frequency and picks the action that fits: Decode FT8 on a calling
window, Decode CW on a beacon, Listen and auto-tune on a voice whose
carrier is not measured yet, a Beacon page for what NB decodes in the
background.

No Qt and no window: skimmer entries (as `Skimmer.entries()` gives them),
the engine's state and the over-power watch's events in, an `Ident` out.
The words are the card's (they are translated there); `Ident.what` and
`Hint`'s keys are the vocabulary between the two. tests/test_whatis.py
runs each row of the plan's table through it.

Every action tunes the receiver or shows a page. None keys, arms or touches
a transmit setting, and the card greys them all while anything is on the
air or armed (plan section 7, rule 4); that rule is the window's to apply,
since only it knows.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import bandplan
from .dsp.skim import FIXED

# An entry is taken for the click when its lo..hi holds it, or failing that
# when its nearer edge is this close: on a zoomed-out wide scope a pixel is
# 100 Hz or more, and a narrow CW trace is a pixel or two wide.
NEAR_HZ = 300.0
# An over-power event explains the click this far beyond its own bins: the
# watch measures in 1 kHz slices, so the bins it reports are narrower than
# what made the slice go over.
OVER_NEAR_HZ = 500.0
OVER_FADE_S = 60.0           # an ended event still explains its column this long (opview.FADE_S)

# The beacons' keys in the skimmer's FIXED table, by the label it gives them.
_BEACON_KEY = {label: seg for seg, (_kind, label, _mode) in FIXED.items()}

# What the surveys found at fixed places and NB does not decode
# (docs/qo100-unidentified-signals.md): (centre, +-Hz, key). The card says
# what each key means. The skimmer names some of these itself (its KNOWN
# table); these add what was learnt about them, and the ones only the
# 17/10/2026 recordings showed, which the skimmer lists as plain data or a
# carrier. Downlink Hz, so only right once beacon lock is.
@dataclass(frozen=True)
class Hint:
    centre: float
    tol: float
    key: str


HINTS = [
    Hint(10_489_569_500.0, 300.0, "slowfsk"),       # weak slow FSK, ~45 Hz shift, all five recordings
    Hint(10_489_588_000.0, 500.0, "keyedcarrier"),  # carrier keyed 0.4 s on/off, sidebands every ~137 Hz
    Hint(10_489_596_500.0, 1_200.0, "arqburst"),    # 0.45 s tone then MFSK on a 93.75 Hz grid
    Hint(10_489_636_650.0, 1_400.0, "arq"),         # connected ARQ data, probably VARA HF
    Hint(10_489_645_800.0, 800.0, "multicarrier"),  # ~1.1 kHz multicarrier on the hour, not FreeDV
]


@dataclass(frozen=True)
class Action:
    """One thing the card offers. `key`:

    decode    `mode` at `dial` (a calling window, a beacon in CW) or, when
              `dial` is None, with `f` where `mode` hears it (a CW signal)
    listen    USB (or `mode`) at `dial`
    autotune  a voice whose carrier is not measured: USB on the skimmer's
              guess, then auto-tune listens there (the window's skim_tune)
    view      Beacon › `page` (decoded in the background; tunes nothing)
    try       `mode` with `f` where it hears it, offered as a guess
    """
    key: str
    mode: str = "usb"
    dial: float | None = None
    f: float | None = None
    page: str = ""


@dataclass(frozen=True)
class Ident:
    """What the card says about one frequency.

    what     one of: window, beacon_cw, beacon_mid, mmb, kgstv, broadcast,
             ssb_measured, ssb_voice, ssb_shape, cw, data, known, carrier,
             faint, unlooked, signal, nothing
    entry    the skimmer's entry, or None
    segment  the band plan's segment at the click (bandplan.segment_at)
    hint     a HINTS key for what the surveys learnt there, or ""
    actions  the one-click actions, the likeliest first
    tries    "Try as..." guesses (unidentified data)
    over     the over-power event (or LEILA siren) at the click, or None
    skimmer  the skimmer's state ("off", "running", "error")
    """
    what: str
    f: float
    entry: dict | None = None
    segment: dict | None = None
    hint: str = ""
    actions: tuple = ()
    tries: tuple = ()
    over: dict | None = None
    skimmer: str = "off"


def _snap(f: float, step: float) -> float:
    return round(f / step) * step


def listen_dial(e: dict) -> float:
    """A USB dial that puts the signal where it is heard: a narrow one
    (CW, a carrier, PSK) as a 1 kHz tone, one up to a voice's width centred
    at 1.5 kHz of audio, and anything wider from its low edge so as much of
    it as the 2.4 kHz filter holds is heard."""
    lo, hi = float(e["lo"]), float(e["hi"])
    width = hi - lo
    if width <= 500.0:
        return _snap(float(e.get("f") or (lo + hi) / 2) - 1000.0, 10)
    if width <= 2_400.0:
        return _snap((lo + hi) / 2 - 1500.0, 10)
    return _snap(lo - 200.0, 10)


def beacon_mark(key: str) -> float:
    """The key-down (mark) tone of an F1A beacon. QO-100's CW beacons are
    frequency-shift keyed: decoding the space tone prints the keying upside
    down (bandplan PRESETS, GUIDE section 5), so Decode CW puts the mark on
    the pitch. Lower: the upper of its two tones; upper: the lower."""
    b = bandplan.BEACONS[key]
    return b["dl"] + b["shift"] if key == "lower" else b["dl"] - b["shift"]


def pick(f: float, entries: list[dict]) -> dict | None:
    """The skimmer's entry for a click at `f`: the narrowest that holds it,
    else the nearest within NEAR_HZ of an edge."""
    holding = [e for e in entries if e["lo"] <= f <= e["hi"]]
    if holding:
        return min(holding, key=lambda e: e["hi"] - e["lo"])
    near = [(min(abs(f - e["lo"]), abs(f - e["hi"])), e) for e in entries]
    near = [(d, e) for d, e in near if d <= NEAR_HZ]
    return min(near, key=lambda de: de[0])[1] if near else None


def over_at(f: float, events: list[dict], now: float) -> dict | None:
    """The over-power event or siren explaining a click at `f`: active
    first, then the strongest; ended ones only while the scope still shows
    them."""
    hits = [e for e in events if e["lo"] - OVER_NEAR_HZ <= f <= e["hi"] + OVER_NEAR_HZ
            and (e.get("active") or now - float(e.get("end") or 0) <= OVER_FADE_S)]
    if not hits:
        return None
    return max(hits, key=lambda e: (bool(e.get("active")), e["kind"] == "leila" or bool(e.get("leila")),
                                    float(e.get("excessDb") or e.get("levelDb") or 0)))


def hint_at(f: float) -> str:
    for h in HINTS:
        if abs(f - h.centre) <= h.tol:
            return h.key
    return ""


def identify(f: float, entries: list[dict], st: dict, events: list[dict] = (), now: float = 0.0) -> Ident:
    """What is at dial frequency `f`. `entries`: the skimmer's latest list;
    `st`: the engine's state (cwPitch, skimState); `events`: the over-power
    watch's list; `now`: wall-clock seconds, for an event that has ended."""
    seg = bandplan.segment_at(f)
    skim = str(st.get("skimState") or "off")
    over = over_at(f, list(events or ()), now)
    e = pick(f, entries) if entries else None
    base = dict(f=f, segment=seg, over=over, skimmer=skim)
    if e is None:
        return Ident("nothing", hint=hint_at(f), **base)
    base["entry"] = e
    kind = e["kind"]
    centre = float(e.get("f") or (e["lo"] + e["hi"]) / 2)
    hint = hint_at(centre)
    pitch = float(st.get("cwPitch") or 700.0)
    if kind == "digital":
        return Ident("window", actions=(Action("decode", mode=e["mode"], dial=float(e["dial"])),), **base)
    if kind == "beacon":
        key = _BEACON_KEY.get(e["label"], "")
        if key in ("lower beacon", "upper beacon"):
            mark = beacon_mark(key.split()[0])
            return Ident("beacon_cw", actions=(Action("decode", mode="cw", dial=_snap(mark - pitch, 10)),), **base)
        if key == "middle beacon":
            return Ident("beacon_mid", actions=(Action("view", page="midtext"),), **base)
        if key == "multimedia beacon":
            return Ident("mmb", actions=(Action("view", page="bulletins"),), **base)
        return Ident("broadcast", actions=(Action("listen", dial=listen_dial(e)),), **base)
    if kind == "known":
        if e.get("dial") is not None:
            # KG-STV, the one named signal with a dial: received in the
            # background whatever the mode, so its page is the action.
            return Ident("kgstv", actions=(Action("view", page="kgstv"), Action("listen", dial=float(e["dial"]))),
                         **base)
        return Ident("known", hint=hint, actions=(Action("listen", dial=listen_dial(e)),), **base)
    if kind == "ssb":
        if e.get("exact") and e.get("dial") is not None:
            return Ident("ssb_measured", actions=(Action("listen", dial=float(e["dial"])),), **base)
        # Since 17/10/2026 "SSB" means speech was heard and "SSB?" only
        # that it is voice-shaped (skim.ssb_label); either way the carrier
        # is not measured, so the action is auto-tune's.
        return Ident("ssb_voice" if e.get("voice") else "ssb_shape", actions=(Action("autotune"),), **base)
    if kind == "cw":
        return Ident("cw", actions=(Action("decode", mode="cw", f=centre),), **base)
    if kind == "data":
        return Ident("data", hint=hint, actions=(Action("listen", dial=listen_dial(e)),),
                     tries=(Action("try", mode="psk31", f=centre), Action("try", mode="rtty", f=centre)), **base)
    if kind == "carrier":
        return Ident("carrier", hint=hint, actions=(Action("listen", dial=listen_dial(e)),), **base)
    # A "signal": nothing named it yet. A narrow one the skimmer has looked
    # at and found nothing standing out in (Mac test FINDINGS 7: "Signal
    # (narrow)", "nothing stands out in the channel"), a wide one not
    # looked at yet, or one looked at that is neither voice nor data.
    what = "unlooked" if not e.get("looks") else "faint" if e["hi"] - e["lo"] < 500.0 else "signal"
    return Ident(what, hint=hint, actions=(Action("listen", dial=listen_dial(e)),), **base)


__all__ = ["Action", "Hint", "HINTS", "Ident", "identify", "listen_dial", "beacon_mark", "pick", "over_at"]
