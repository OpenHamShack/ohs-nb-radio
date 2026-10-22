"""Mode panels, one per kind of mode (DESIGN.md "User interface")."""
from __future__ import annotations

from ...modegroups import is_slot
from .ft8 import Ft8Panel
from .hsmodem import HsmodemPanel
from .sstv import SstvPanel
from .text import TEXT_MODES, TextPanel
from .voice import VoicePanel


def panel_key(mode: str) -> str:
    if mode == "fm":
        return "fm"
    if is_slot(mode):
        return "slot"
    if mode == "cw":
        return "cw"
    if mode in TEXT_MODES:
        return "text"
    if mode == "sstv":
        return "image"
    if mode == "hsmodem":
        return "data"
    return "voice"


def make_panel(key: str, bridge, prefs, parent=None, big: bool = False):
    # A panel only one app has (HAM's FM/repeater panel) comes from its Face;
    # an app without one gets the voice panel.
    own = bridge.face.panel(key, bridge, prefs, parent, big) if hasattr(bridge.face, "panel") else None
    if own is not None:
        return own
    if key == "slot":
        return Ft8Panel(bridge, prefs, parent, big=big)
    if key == "cw":
        return TextPanel(bridge, prefs, parent, cw=True, big=big)
    if key == "text":
        return TextPanel(bridge, prefs, parent, big=big)
    if key == "image":
        return SstvPanel(bridge, prefs, parent, big=big)
    if key == "data":
        return HsmodemPanel(bridge, prefs, parent, big=big)
    return VoicePanel(bridge, prefs, parent)


__all__ = ["make_panel", "panel_key"]
