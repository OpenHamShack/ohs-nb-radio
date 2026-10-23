"""Which modes go together, and what a slot mode is, as data.

The UI overhaul of October 2026 (docs/ui-overhaul-2026-10.md, sections 2 and
5.1) groups the modes three ways - Voice, Digital, Pictures & data - and
lays the window out per group: a *workspace*. Before this module the same
facts were spread as literals through the window: `mode in ("ft8", "ft4")`
in the scopes, the panels, click-to-tune and the decode labels; FT8's 50 Hz
and FT4's 83 Hz tone widths written out twice in the zoom scope; the mode
names in the rail. Adding Q65 meant finding every one of them. Now they are
asked of here, and a mode is added in one place.

No Qt, on purpose: the pad's MODE key (ohscore/padactions.py) runs in the
store form too, which has no window, and cycles in group order.

The group names are ids, not words: the window says them in the
operator's language (ohscore/ui/modegrid.py group_label).
"""
from __future__ import annotations

from dataclasses import dataclass

VOICE, DIGITAL, PICTURES = "voice", "digital", "pictures"

# Every mode either app has, in the order its group shows it. The order is
# fixed so a button stays where the operator's hand learnt it (decision 3:
# recency is only used where room is short). An app shows the ones it has
# (groups()). "kgstv" is not a radio mode: KG-STV is received in the
# background and sent as an over (Engine.OVER_MODES); its button opens
# Beacon › KG-STV instead (decision 4), so it is in OVER_BUTTONS too.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (VOICE, ("usb", "lsb", "cw", "am", "fm", "wfm", "freedv")),
    (DIGITAL, ("ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty")),
    (PICTURES, ("sstv", "kgstv", "hsmodem")),
)
OVER_BUTTONS = frozenset({"kgstv"})

# What each mode is called on a button, a tab or in the logbook. Mode names
# are not translated (docs/I18N.md). Moved here from ohscore/ui/rail.py,
# which re-exports it; Q65 and JS8 were missing there, so the panel title
# said "q65".
MODE_LABELS = {"usb": "USB", "lsb": "LSB", "cw": "CW", "am": "AM", "fm": "FM", "wfm": "WFM", "freedv": "FreeDV",
               "ft8": "FT8", "ft4": "FT4", "q65": "Q65", "js8": "JS8", "psk31": "PSK31", "psk63": "PSK63",
               "psk125": "PSK125", "rtty": "RTTY", "sstv": "SSTV", "kgstv": "KG-STV", "hsmodem": "HSmodem",
               "wspr": "WSPR"}

# The workspace each group brings when the workspace follows the mode
# (Auto). Pictures share Digital's (decision 1): their panel wants room
# the way a decode list does, and a fourth layout to tune was not worth it.
# Watch is never brought by a mode; it is only ever picked.
WORKSPACES = ("digital", "voice", "watch")
GROUP_WORKSPACE = {VOICE: "voice", DIGITAL: "digital", PICTURES: "digital"}


@dataclass(frozen=True)
class SlotSpec:
    """A mode that transmits and decodes in fixed UTC periods.

    period      seconds per slot
    tone_width  the occupied bandwidth in Hz above the audio offset: the
                width of the RX and TX marks on the zoom and of the band
                the TX mark claims on the scopes
    transmits   whether this app sends it
    label_at    seconds into the slot a decode's waterfall label is pinned
                to: near the middle of the transmission, where the signal is
                on the waterfall
    queue_at    seconds into the other station's slot the QSO panel queues
                our next over (ft8seq.plan_over's decode_wait): early enough
                for the engine to render and start on the boundary, late
                enough that the decodes which decide what we say are in
    """
    period: float
    tone_width: float
    transmits: bool
    label_at: float
    queue_at: float = 2.5


# FT8 and FT4 as they always were (ohscore/ui/scope.py drew FT4 83.3 Hz wide
# in one place and 83 in the other; 83.3 is the mode's 4 tones x 20.8 Hz).
# FT4's 1.875 s is the quarter slot plan_over always capped FT8's 2.5 s at
# for it.
#
# Q65-60A (NB only): 108 Hz is its occupied bandwidth at 60 s
# (ohscore/modes/q65.py, from WSJT-X's Q65 table). Its transmission runs from
# 1 s to about 50 s (85 symbols of 0.576 s, engine SLOT_LEAD), so the label
# sits at 25 s. Its decoder runs once, 55 s into the period
# (q65.Decoder.EARLY_S), and ohsdigi takes 0.2 s over it on ohs-dev (a slow
# laptop several times that), so the panel queues our over at 56.5 s,
# leaving the plan_over cutoff (0.8 s) and a little for rendering. FT8's 2.5 s would have held the transmitter
# keyed and waiting for nearly a whole minute, and the decode that changes
# the message would then land after it was queued every time.
#
# JS8 Normal: 8 tones of 6.25 Hz, the FT8 frame timing (ohsdigi
# JS8_SUBMODES "normal": 15 s, 0.5 s start, 12.64 s long). Sent since
# 17/10/2026 (Brian), a frame per period; queue_at is where the JS8 panel
# queues the next frame for the next period, just after the one before
# has ended (13.14 s), so a message goes out in consecutive periods.
SLOT_MODES: dict[str, SlotSpec] = {
    "ft8": SlotSpec(period=15.0, tone_width=50.0, transmits=True, label_at=7.0),
    "ft4": SlotSpec(period=7.5, tone_width=83.3, transmits=True, label_at=3.5, queue_at=1.875),
    "q65": SlotSpec(period=60.0, tone_width=108.0, transmits=True, label_at=25.0, queue_at=56.5),
    "js8": SlotSpec(period=15.0, tone_width=50.0, transmits=True, label_at=7.0, queue_at=13.5),
}


@dataclass(frozen=True)
class Js8Speed:
    """One of JS8's five speeds, as ohsdigi's JS8_SUBMODES has it (JS8Call's
    own table; tests/test_js8_speeds.py holds the two equal).

    letter      the submode letter js8 and JS8Call's logs use
    period      seconds per period
    start       seconds into the period a frame starts (the engine's lead)
    duration    seconds the frame lasts (79 symbols)
    spacing     tone spacing, Hz (8 tones)
    late        how much later than `start` a frame may still begin: within
                the slack the period leaves after the frame, so it always
                ends inside its own period. Normal's 1.5 s is FT8's (engine
                SLOT_LATE); the others are not measured, only kept to under
                half that slack.
    """
    letter: str
    period: float
    start: float
    duration: float
    spacing: float
    late: float

    def slot(self) -> SlotSpec:
        """As a slot spec: the marks are its 8 tones wide, labels sit mid-
        frame, and the next frame is queued just after this one ends."""
        return SlotSpec(period=self.period, tone_width=8 * self.spacing, transmits=True,
                        label_at=round(self.start + self.duration / 2, 1),
                        queue_at=round(self.start + self.duration + 0.35, 2))


# Slowest first, as a speed picker reads. Brian (17/10/2026): all five
# decoded at once, as JS8Call does, and sent at the one picked (Normal by
# default, the QO-100 "JS8Call" preset's). Decoding all five costs about
# 8 % of one core on ohs-dev (ohsdigi, depth 3), so none is optional.
JS8_SPEEDS: dict[str, Js8Speed] = {
    "slow": Js8Speed("E", 30.0, 0.5, 25.28, 3.125, 1.5),
    "normal": Js8Speed("A", 15.0, 0.5, 12.64, 6.25, 1.5),
    "fast": Js8Speed("B", 10.0, 0.2, 7.9, 10.0, 0.8),
    "turbo": Js8Speed("C", 6.0, 0.1, 3.95, 20.0, 0.8),
    "ultra": Js8Speed("I", 4.0, 0.1, 2.528, 31.25, 0.5),
}
JS8_DEFAULT_SPEED = "normal"


def js8_slot(speed: str) -> SlotSpec:
    """The slot spec for JS8 at `speed` (Normal's for an unknown one)."""
    return JS8_SPEEDS.get(speed, JS8_SPEEDS[JS8_DEFAULT_SPEED]).slot()


def slot_spec(mode: str) -> SlotSpec | None:
    return SLOT_MODES.get(mode)


def is_slot(mode: str) -> bool:
    """Whether `mode` uses the slot panel, its RX/TX offsets and its labels."""
    return mode in SLOT_MODES


def group_of(mode: str) -> str | None:
    for g, modes in GROUPS:
        if mode in modes:
            return g
    return None


def workspace_for(mode: str) -> str:
    """The workspace Auto brings for `mode`; Voice for anything unknown,
    which is the layout every mode had before workspaces."""
    return GROUP_WORKSPACE.get(group_of(mode) or VOICE, "voice")


def groups(modes, buttons=()) -> list[tuple[str, list[str]]]:
    """[(group, [mode, ...])] for an app whose radio modes are `modes`,
    in GROUPS' order, groups left empty dropped. `buttons` adds over-mode
    buttons the app offers (NB: "kgstv")."""
    have = set(modes) | (set(buttons) & OVER_BUTTONS)
    out = []
    for g, ms in GROUPS:
        keep = [m for m in ms if m in have]
        if keep:
            out.append((g, keep))
    return out


def label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode.upper())
