"""SDR devices behind one interface (DESIGN.md "Devices").

The real radios (Pluto family, SoapySDR receivers) live here because both
apps drive the same hardware. Which devices an app offers, and what its
`sim` simulates, is the app's: it fills a `DeviceRegistry`
(ohscore/devices/registry.py)."""
from __future__ import annotations

from .base import Device, DeviceError
from .registry import DeviceRegistry

__all__ = ["Device", "DeviceError", "DeviceRegistry"]
