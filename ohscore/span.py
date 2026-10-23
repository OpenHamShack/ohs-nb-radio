"""Where to put the receiver's centre so that several channels fit in its
span at once: the capture pinned for background decoders (RADIO-SDR-PLAN
§8.5, Brian 23/10/2026 "pin the capture").

    centre = choose_centre([(144_800_000, 6_000), (145_500_000, 3_000)], half=552_000)

Each item is (centre Hz, half width Hz): a decoder session's channel, or
the operator's dial with its passband. A centre fits when every item lies
wholly inside `half` of it (the span's usable part: past it are the bank's
filter edges, where a channel is attenuated and aliased) and no item comes
within `guard` of the centre itself (DC: the receiver's own spike, and the
LO leakage beside it, sit there, so a channel on it hears a carrier that is
not on the air).

A pure function, so the rules can be tested on numbers alone; the engine
(ohsradio/radio.py Radio.pin_plan) supplies the span, the items and the
device's tuning range.
"""
from __future__ import annotations

import math

# Clear space between DC and the nearest edge of any channel. The bank's
# DC bin is a few hundred hertz wide at every rate Radio runs, but the
# spike's skirt and the slow wander of a Pluto's or RTL's DC offset spread
# it a few kilohertz; 5 kHz keeps a 12 kHz decoder channel off all of it
# and costs nothing against a span of hundreds of kilohertz.
DC_GUARD_HZ = 5_000.0
# Centres are kept on whole kilohertz where that still fits, as the
# band-following centre is (plan_centre): a readable number in the logs and
# on Remote, and one that does not change by a few hertz between two
# sessions started at nearly the same place.
STEP_HZ = 1_000.0


def fits(centre: float, items, half: float, guard: float = DC_GUARD_HZ) -> bool:
    """Whether every (f, hw) item is inside the span around `centre` and
    off its DC."""
    for f, hw in items:
        d = abs(f - centre)
        if d + hw > half + 1e-6 or d < hw + guard - 1e-6:
            return False
    return True


def choose_centre(items, half: float, *, guard: float = DC_GUARD_HZ, keep: float | None = None,
                  prefer: float | None = None, lo: float = -math.inf, hi: float = math.inf) -> float | None:
    """The centre for `items`, or None when no centre holds them all.

    `keep` (the centre now) wins whenever it fits: a session started where
    the span already reaches moves nothing, so nothing already running
    sees a retune. Otherwise the nearest centre to `prefer` that fits -
    by default the middle of everything, so the items sit as far from both
    filter edges as they can - preferring a whole STEP_HZ. `lo`/`hi` bound
    the centre (the device's tuning range)."""
    items = [(float(f), float(hw)) for f, hw in items]
    if not items:
        return keep
    if keep is not None and lo <= keep <= hi and fits(keep, items, half, guard):
        return keep
    # Every centre that keeps every item inside the span: an interval.
    left = max(max(f + hw for f, hw in items) - half, lo)
    right = min(min(f - hw for f, hw in items) + half, hi)
    if left > right + 1e-6:
        return None
    if prefer is None:
        prefer = (min(f - hw for f, hw in items) + max(f + hw for f, hw in items)) / 2
    # Inside it, the centre may not fall on any item (DC): the nearest
    # centre that fits is the preferred one clipped to the interval, or the
    # edge of an item's keep-out where that pushed it.
    raw = [min(max(prefer, left), right), left, right]
    for f, hw in items:
        raw += [f - hw - guard, f + hw + guard]
    cands = set()
    for c in raw:
        if left - 1e-6 <= c <= right + 1e-6:
            cands.add(c)
            for r in (math.floor(c / STEP_HZ), math.ceil(c / STEP_HZ)):
                cands.add(r * STEP_HZ)
    ok = [c for c in cands if left - 1e-6 <= c <= right + 1e-6 and fits(c, items, half, guard)]
    if not ok:
        return None
    return min(ok, key=lambda c: (c % STEP_HZ != 0, abs(c - prefer), c))
