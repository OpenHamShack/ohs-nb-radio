"""How big the window is, in the terms the layout decides by.

The overhaul (docs/ui-overhaul-2026-10.md, section 3) gives the window
three tiers - Full, Compact, Tight - picked from its size divided by the
text scale, so "Larger text" moves the window into a smaller tier rather
than clipping what was laid out for 100 %. One pure function decides, and
both the window and the tests call it: a tier table written twice (once in
the window, once in a test) is two tables that drift.

The minimum is 1024 x 600 at 100 % (decision 5: 1180 x 700, the floor
until then, still broke the layout and kept 1280 x 720 screens out),
scaled with the text and never more than the screen has room for.

No Qt here: sizes are plain numbers, and the screen's room is passed in.
"""
from __future__ import annotations

import math

FULL, COMPACT, TIGHT = "full", "compact", "tight"
TIERS = (FULL, COMPACT, TIGHT)

# (width, height) at 100 % text from which a tier applies; anything
# smaller than Compact's, down to the minimum, is Tight.
FULL_FROM = (1500, 860)
COMPACT_FROM = (1180, 700)
MIN_SIZE = (1024, 600)

# Settings › Display › Text size (decision 11). 130 % is the largest: at
# 1.3 the minimum is already 1332 x 780, more than a 1366 x 768 laptop has.
TEXT_SCALES = (1.0, 1.15, 1.3)


def nearest_scale(v) -> float:
    """The TEXT_SCALES step nearest `v` (1.0 for anything that is not a
    number): a hand-edited ui.json cannot set a size the layout was never
    checked at."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 1.0
    if math.isnan(f):
        return 1.0
    return min(TEXT_SCALES, key=lambda s: abs(s - f))


def tier(width: float, height: float, scale: float = 1.0) -> str:
    """FULL, COMPACT or TIGHT for a window of `width` x `height` (logical
    pixels) showing text at `scale`."""
    w, h = width / scale, height / scale
    if w >= FULL_FROM[0] and h >= FULL_FROM[1]:
        return FULL
    if w >= COMPACT_FROM[0] and h >= COMPACT_FROM[1]:
        return COMPACT
    return TIGHT


def _scaled(n: int, scale: float) -> int:
    # Rounded before the ceiling: 600 * 1.3 is 780.0000000000001 in floats.
    return math.ceil(round(n * scale, 6))


def minimum_size(scale: float = 1.0, room: tuple[int, int] | None = None) -> tuple[int, int]:
    """The smallest the window may be at text `scale`, capped to `room`
    (the screen's available width and height) when given: a minimum
    larger than the screen would push the window's edges off it."""
    w, h = _scaled(MIN_SIZE[0], scale), _scaled(MIN_SIZE[1], scale)
    if room is not None:
        w, h = min(w, int(room[0])), min(h, int(room[1]))
    return w, h


def scale_fits(scale: float, room: tuple[int, int]) -> bool:
    """Whether text at `scale` leaves the window its whole minimum on a
    screen with `room` available. Settings offers only the sizes that do."""
    w, h = _scaled(MIN_SIZE[0], scale), _scaled(MIN_SIZE[1], scale)
    return w <= room[0] and h <= room[1]
