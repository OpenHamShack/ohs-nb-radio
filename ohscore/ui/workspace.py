"""Workspaces: how much room each part of the window gets, per kind of operating.

The UI overhaul of October 2026 (docs/ui-overhaul-2026-10.md, section 2)
gives the window three layouts - Digital, Voice and Watch - instead of
one that every mode squeezed into. A workspace decides proportions and
the forms of the rail's cards, nothing else: the radio, the scopes'
settings, the views and every control are the same in all three. This
module is the model of that, without Qt, so the rules are tested on
their own and the window only carries them out:

- what each workspace is by default (SPECS);
- which one is in force: Auto follows the mode (ohscore/modegroups.py
  workspace_for), or the operator pinned one (Workspaces);
- what the operator made of each, as kept in ui.json "workspaces"
  (ohscore/ui/prefs.py): the splitters as fractions, the rail's width, the
  view last shown, the cards expanded (layout(), remember()).

Decisions, Brian's of 17/10/2026 (plan section 10):

- A mode button, mode key or the pad's MODE key is a request to operate:
  it brings that mode's workspace and returns to Auto, even from one the
  operator pinned (decision 2). Tuning from the Band list, a memory or a
  scope changes the mode without that, so browsing the band from Watch
  stays in Watch. The window tells mode_requested() which is which; a
  mode change seen only on the state feed is never a request.
- Watch is never brought by a mode, only picked (W, the Workspace button,
  View › Workspace).
- Pictures share Digital's layout (decision 1): modegroups says so.

A switch must only resize and show or hide: the Mac test of 17/10 lost
receive blocks to heavy window work (FINDINGS 10, 29), so nothing here
asks for a widget to be built.

The window's tier (ohscore/ui/layoutrules.py, overhaul section 3) has the
last word on the forms: a workspace's are for the Full tier. Compact
narrows the rail to COMPACT_RAIL with every card compact; Tight puts the
rail in a drawer and gives the scopes their least sizes (forms(),
rail_width(), wide_min(), zoom_min()).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..modegroups import workspace_for
from .layoutrules import COMPACT as COMPACT_TIER
from .layoutrules import FULL as FULL_TIER
from .layoutrules import TIGHT

AUTO = "auto"
DIGITAL, VOICE, WATCH = "digital", "voice", "watch"
WORKSPACES = (DIGITAL, VOICE, WATCH)
# W steps through them in this order, pinning each.
CYCLE = WORKSPACES

FULL, COMPACT, HIDDEN = "full", "compact", "hidden"

# The rail cards whose expanded state a workspace remembers.
CARDS = ("receive", "transmit")

# Compact's rail, px at 100 % (plan section 3), unless the operator
# dragged it in Compact ("railCompact") or the cards need more.
COMPACT_RAIL = 260
# Tight's scopes: the wide one at least this tall (with at least 40 px of
# it waterfall: ohscore/ui/scope.py), the zoom this wide.
TIGHT_WIDE_MIN, TIGHT_ZOOM_MIN = 120, 160


@dataclass(frozen=True)
class Spec:
    """A workspace's defaults (plan section 2.1).

    wide      the wide scope's share of the body's height
    zoom      the zoom scope's share of the lower width
    rail      the rail's width in px (never narrower than its cards need)
    wide_min  the least the wide scope may be dragged to, px
    zoom_min  the least the zoom scope may be, px: wide enough to click
              the RX and TX offsets of a slot mode on it
    mode, receive, transmit   each rail card's form: FULL, COMPACT, or
              HIDDEN (Watch's Transmit card, which still comes back while
              anything transmits or a warning stands: transmit_form())
    """
    wide: float
    zoom: float
    rail: int
    wide_min: int
    zoom_min: int
    mode: str
    receive: str
    transmit: str


# Digital: the decode list is what is read all the time, so the wide
# scope is a strip (a quarter of the height, enough to find the QO-100
# segment) and the zoom is tall and narrow, which suits FT8's labels.
# Voice: the zoom and the Receive card get the room - the passband is
# what is listened to. Watch: two thirds of the height is the band, with
# a slim rail of what a listener touches. The figures are the plan's
# mock-ups (section 4) measured at 1920 x 1080.
SPECS = {
    DIGITAL: Spec(wide=0.25, zoom=0.17, rail=320, wide_min=110, zoom_min=160,
                  mode=FULL, receive=COMPACT, transmit=COMPACT),
    VOICE: Spec(wide=0.42, zoom=0.45, rail=320, wide_min=160, zoom_min=260,
                mode=FULL, receive=FULL, transmit=FULL),
    WATCH: Spec(wide=0.66, zoom=0.22, rail=210, wide_min=160, zoom_min=160,
                mode=COMPACT, receive=COMPACT, transmit=HIDDEN),
}


class Workspaces:
    """Which workspace is in force. `choice` is AUTO or the pinned one,
    as ui.json "workspace" keeps it."""

    def __init__(self, choice: str = AUTO):
        self.choice = choice if choice in (AUTO, *WORKSPACES) else AUTO

    @property
    def pinned(self) -> bool:
        return self.choice != AUTO

    def effective(self, mode: str) -> str:
        """The workspace to show while the radio is in `mode`."""
        return self.choice if self.pinned else workspace_for(mode)

    def pin(self, ws: str) -> None:
        if ws in WORKSPACES:
            self.choice = ws

    def auto(self) -> None:
        self.choice = AUTO

    def cycle(self, mode: str) -> str:
        """W: pin the workspace after the one showing (Digital, Voice,
        Watch, round again), and return it."""
        now = self.effective(mode)
        self.choice = CYCLE[(CYCLE.index(now) + 1) % len(CYCLE)]
        return self.choice

    def mode_requested(self) -> None:
        """A mode button, key or pad press: back to following the mode."""
        self.choice = AUTO


def default_view(ws: str, watch_view: str = "mode") -> str:
    """The lower view a workspace opens on before the operator chose one:
    Operate ("mode"), or for Watch the app's band view (NB's Band list,
    Radio's CW Activity), `watch_view`."""
    return watch_view if ws == WATCH else "mode"


def layout(ws: str, saved: dict | None, watch_view: str = "mode") -> dict:
    """Workspace `ws` as it should be shown: its defaults with what the
    operator changed (`saved`, its entry in ui.json "workspaces") over
    them. Values of the wrong kind are ignored, as Prefs ignores a
    hand-edited file's."""
    spec = SPECS[ws]
    out = {"wide": spec.wide, "zoom": spec.zoom, "rail": spec.rail, "view": default_view(ws, watch_view),
           "expanded": []}
    s = saved if isinstance(saved, dict) else {}
    for k in ("wide", "zoom"):
        v = s.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v < 1.0:
            out[k] = float(v)
    for k in ("rail", "railCompact"):
        v = s.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            out[k] = v
    if isinstance(s.get("view"), str) and s["view"]:
        out["view"] = s["view"]
    if isinstance(s.get("expanded"), list):
        out["expanded"] = [c for c in s["expanded"] if c in CARDS]
    return out


def remember(all_saved: dict, ws: str, **changes) -> dict:
    """ui.json "workspaces" with `changes` made to `ws`'s entry; a new
    dict, so a Prefs holding the old one sees the assignment."""
    out = dict(all_saved or {})
    out[ws] = {**(out.get(ws) or {}), **changes}
    return out


def expanded_with(expanded: list, card: str, on: bool) -> list:
    """`expanded` with `card` added or taken out, in CARDS' order."""
    have = set(expanded) | {card} if on else set(expanded) - {card}
    return [c for c in CARDS if c in have]


def forms(ws: str, tier: str = FULL_TIER) -> tuple[str, str, str]:
    """(Mode, Receive, Transmit) card forms for `ws` in window `tier`.
    Full: the workspace's own. Compact and Tight: every card compact, and
    Watch's Transmit card still hidden (transmit_form brings it back)."""
    spec = SPECS[ws]
    if tier == FULL_TIER:
        return spec.mode, spec.receive, spec.transmit
    return COMPACT, COMPACT, HIDDEN if spec.transmit == HIDDEN else COMPACT


def rail_width(lay: dict, tier: str, scale: float = 1.0) -> int:
    """The rail's width in px for a workspace's layout() in `tier` (0 in
    Tight, whose rail is a drawer): Full's own, or Compact's - the one
    dragged there, else COMPACT_RAIL at the text `scale` (at 130 % an
    unscaled 260 px cut the Transmit card's words), never wider than Full's."""
    if tier == TIGHT:
        return 0
    if tier == COMPACT_TIER:
        return int(lay.get("railCompact") or min(int(lay["rail"]), round(COMPACT_RAIL * scale)))
    return int(lay["rail"])


def wide_min(ws: str, tier: str = FULL_TIER) -> int:
    return TIGHT_WIDE_MIN if tier == TIGHT else SPECS[ws].wide_min


def zoom_min(ws: str, tier: str = FULL_TIER) -> int:
    return TIGHT_ZOOM_MIN if tier == TIGHT else SPECS[ws].zoom_min


def transmit_form(ws: str, *, on_air: bool, armed: bool, warning: bool, tier: str = FULL_TIER) -> str:
    """The Transmit card's form in `ws` and window `tier` now. Watch hides
    it, but never while anything is on the air (an IC-9700 keyed at its
    own microphone included), armed to go, or a transmit warning stands:
    then it is shown in full (plan section 7, rule 3)."""
    form = forms(ws, tier)[2]
    if form == HIDDEN and (on_air or armed or warning):
        return FULL
    return form
