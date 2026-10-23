"""Where a click on a scope should put the dial, and the default step, per mode.

A click means "I want to hear *that*". What the dial must be for that depends
on the mode: SSB's dial is the suppressed carrier, so the click is the dial;
CW is heard at the pitch above the dial; the keyboard modes' decoders listen
at their registry offset; FT8 lives on 500 Hz dial channels with the signals
spread across the 3 kHz audio window.
"""
from __future__ import annotations

from ..modegroups import is_slot

DEFAULT_STEP = {"usb": 50, "lsb": 50, "am": 500, "cw": 10, "ft8": 500, "ft4": 500, "psk31": 10, "psk63": 10,
                "psk125": 10, "rtty": 10, "freedv": 100, "sstv": 100,
                "fm": 12500, "wfm": 100_000, "wspr": 10}


def snap(f: float, step: float) -> float:
    return round(f / step) * step


def click_to_dial(mode: str, f: float, st: dict, text_offset: float = 1000.0) -> float:
    if mode == "cw":
        return snap(f - float(st.get("cwPitch", 700.0)), 10)
    if mode in ("psk31", "psk63", "psk125", "rtty"):
        return snap(f - text_offset, 10)
    if is_slot(mode):
        return snap(f - 1500.0, 500)
    if mode in ("freedv", "sstv"):
        return snap(f - 1500.0, 100)
    if mode == "am":
        return snap(f, 500)
    if mode == "fm":
        # FM channels: 12.5 kHz in the UK on 2 m and 70 cm (a 6.25 kHz grid
        # catches the odd offset simplex and DV channels too).
        return snap(f, 6250)
    if mode == "wfm":
        # Broadcast FM sits on a 100 kHz raster, with a few stations on the
        # 50 kHz between; 50 catches both, and a click on a 180 kHz-wide
        # station is never more than 25 kHz out.
        return snap(f, 50_000)
    return snap(f, 100)
