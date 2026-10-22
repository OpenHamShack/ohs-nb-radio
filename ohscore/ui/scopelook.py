"""How the scopes' traces look: colours, widths, fill. Settings › Display.

One look for every scope - wide, zoom and the second display - because it
is a matter of taste, not of what one scope is for; what a scope shows
(scale, peaks, smoothing) stays per scope in its adjust panel.

Stored in prefs["scopeLook"] as {item: value}; missing items are the
preset's ("preset", default "classic"), and Classic is exactly the look the
scopes had before any of this was adjustable, so an empty dict - every
existing ui.json - changes nothing.

Themes: the colours are the same in the light and dark themes. The scopes
are dark-backed in both (theme.py keeps "scope" dark in LIGHT, because a
waterfall on white is unreadable), so a trace colour that reads on one
reads on the other, and storing two sets would only give the operator two
things to keep in step. The one theme-dependent part is Classic's
background, which stays the theme's own "scope" token, as it always was.

Painting asks look(prefs) every frame. It returns the cached Look - its
QColors, QPens and gradient already built - unless the stored dict or the
theme changed, which costs one dict comparison; nothing is constructed per
paint.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPen

from . import theme

# Item -> (label, kind). Kinds: "colour" ("#rrggbb" or "#aarrggbb"),
# "width" (1-3 px), "bool", "percent".
ITEMS = {
    "trace": ("Trace", "colour"),
    "traceWidth": ("Trace width", "width"),
    "fill": ("Fill under the trace", "bool"),
    "fillColour": ("Fill", "colour"),
    "fillOpacity": ("Fill opacity", "percent"),
    "peak": ("Peak hold", "colour"),
    "marker": ("Peak markers", "colour"),
    "grid": ("Grid", "colour"),
    "gridOpacity": ("Grid opacity", "percent"),
    "background": ("Background", "colour"),
}

# Classic's values are the literals the scope painted with before 05/10.
# Its background "" means "the theme's own scope colour".
PRESETS = {
    "classic": {"trace": "#ebd6eeff", "traceWidth": 1, "fill": True, "fillColour": "#4fd1e8", "fillOpacity": 54.0,
                "peak": "#4696aac8", "marker": "#ffd666", "grid": "#141a23", "gridOpacity": 100.0, "background": ""},
    "amber": {"trace": "#ebffc45a", "traceWidth": 1, "fill": True, "fillColour": "#ffa01e", "fillOpacity": 50.0,
              "peak": "#50c8a064", "marker": "#78dcff", "grid": "#2a2010", "gridOpacity": 100.0,
              "background": "#0a0703"},
    "green": {"trace": "#eb78ff8c", "traceWidth": 1, "fill": True, "fillColour": "#28dc5a", "fillOpacity": 45.0,
              "peak": "#505aaa6e", "marker": "#ffd666", "grid": "#0f2414", "gridOpacity": 100.0,
              "background": "#020804"},
    "contrast": {"trace": "#ffffffff", "traceWidth": 2, "fill": True, "fillColour": "#ffffff", "fillOpacity": 22.0,
                 "peak": "#b4ffff00", "marker": "#00ffff", "grid": "#3a3a3a", "gridOpacity": 100.0,
                 "background": "#000000"},
}
PRESET_NAMES = [("classic", "Classic"), ("amber", "Amber"), ("green", "Green phosphor"),
                ("contrast", "High contrast")]

# Classic's fill fades from cyan (79, 209, 232) at the trace to deep blue
# (20, 50, 110) at the foot. Another fill colour fades the same way: each
# channel to the same fraction, so Classic comes out exactly as before.
_FOOT = (20 / 79, 50 / 209, 110 / 232)


def values(d: dict | None) -> dict:
    """Every item's value: the stored ones over the stored preset's."""
    d = d if isinstance(d, dict) else {}
    preset = d.get("preset") if d.get("preset") in PRESETS or d.get("preset") == "custom" else "classic"
    out = dict(PRESETS.get(preset, PRESETS["classic"]))
    for k, v in d.items():
        if k in ITEMS and _valid(k, v):
            out[k] = v
    out["preset"] = preset
    return out


def _valid(k: str, v) -> bool:
    """A hand-edited ui.json with a wrong type falls back to the preset's
    value for that item rather than failing to paint."""
    kind = ITEMS[k][1]
    if kind == "colour":
        return isinstance(v, str) and ((v == "" and k == "background") or QColor(v).isValid())
    if kind == "width":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "bool":
        return isinstance(v, bool)
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# The widest trace drawn, in device pixels (see trace_passes): 7 passes.
# Only a width of 3 on a 2x screen reaches it, and gets 4 device pixels
# rather than 6 - still the widest choice, at a bounded cost.
MAX_DEVICE_WIDTH = 4


def _hairline(colour: QColor) -> QPen:
    """A one-device-pixel pen for the spectrum polylines.

    Why cosmetic: Qt's raster engine draws an antialiased polyline on its
    fast path (the cosmetic stroker) only when the pen comes out at most
    one *device* pixel wide. A plain QPen(colour, 1) is one logical pixel,
    so on any screen scaled by more than 1 - KDE's 105 % on the test
    laptop, 125 % or 150 % on many Windows laptops - it fell to the general
    stroker. On that laptop (i5-1135G7, 07/10) the wide scope's paint went
    from 3.5 ms to 27 ms, twenty times a second, and the GUI thread to
    ~75 % of a core. PyQt holds the GIL through drawPolyline, so it was not
    only the window that paid: the receive thread waited for the GIL and
    overran ~1.2 times a second, with audio underruns behind it. Width is
    then made in device pixels by drawing the hairline more than once
    (trace_passes)."""
    pen = QPen(colour, 1)
    pen.setCosmetic(True)
    return pen


def trace_passes(width: int, dpr: float) -> tuple:
    """Offsets, in logical pixels, at which to draw a hairline polyline so
    that it comes out about `width` logical pixels wide on a screen of
    device-pixel ratio `dpr`.

    The pen stays one device pixel (see _hairline); a wider line is the
    same polyline again, one device pixel across and down (and up and back
    for an odd width): 1 -> one pass, 2 -> three, 3 -> five. At a ratio of
    1 that is exactly what the scope drew before 07/10, so a Pi on a plain
    monitor draws the same pixels at the same cost; at 2 a 1 px trace is
    two device pixels, as wide as it looked with a scaled pen."""
    dpr = dpr if dpr > 0 else 1.0
    w = max(1, min(MAX_DEVICE_WIDTH, round(width * dpr)))
    ks = [k for k in range(-((w - 1) // 2), w // 2 + 1) if k]
    offs = [(0, 0)] + [(k, 0) for k in ks] + [(0, k) for k in ks]
    return tuple((dx / dpr, dy / dpr) for dx, dy in offs)


class Look:
    """One resolved look: what painting needs, built once."""

    def __init__(self, d: dict | None):
        v = values(d)
        self.v = v
        self.trace = QColor(v["trace"])
        self.trace_pen = _hairline(self.trace)
        self.width = max(1, min(3, int(v["traceWidth"])))
        self.fill = bool(v["fill"])
        fc = QColor(v["fillColour"])
        self.fill_top = (fc.red(), fc.green(), fc.blue())
        self.fill_foot = tuple(c * k for c, k in zip(self.fill_top, _FOOT))
        self.fill_opacity = max(0.0, min(100.0, float(v["fillOpacity"]))) / 100.0
        self.peak_pen = _hairline(QColor(v["peak"]))
        self.marker = QColor(v["marker"])
        m = QColor(self.marker)
        m.setAlpha(120)
        self.marker_edge = QPen(m, 1)
        g = QColor(v["grid"])
        g.setAlphaF(max(0.0, min(100.0, float(v["gridOpacity"]))) / 100.0)
        self.grid_pen = QPen(g, 1)
        self.background = QColor(v["background"]) if v["background"] else theme.c("scope")
        # What the scope's cached layers depend on.
        self.fill_key = (self.fill_top, self.fill_opacity)
        self.static_key = (v["grid"], v["gridOpacity"], self.background.name(QColor.NameFormat.HexArgb))


_cache: tuple[dict, str, Look] | None = None


def look(prefs) -> Look:
    global _cache
    d = prefs.get("scopeLook") or {}
    name = theme.t()["name"]
    if _cache is None or _cache[0] != d or _cache[1] != name:
        _cache = (dict(d), name, Look(d))
    return _cache[2]
