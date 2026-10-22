"""The devices OpenHamShack Radio offers: the core's Pluto family and SoapySDR
receivers, the Hermes-Lite 2 (ohscore/devices/hl2.py), and its own `sim`,
a simulated set of amateur bands (docs/ham/DESIGN-HAM.md section 4)."""
from __future__ import annotations

from ohscore.devices import Device, DeviceRegistry


def _sim(cfg: dict, fs: float) -> Device:
    from .sim import HamSim
    return HamSim(cfg, fs)


def _hl2(cfg: dict, fs: float) -> Device:
    # The HL2 runs at its own rate (hl2Rate), not the Pluto's sampleRate.
    from ohscore.devices.hl2 import HL2Device
    return HL2Device(cfg.get("hl2Address", ""), float(cfg.get("hl2Rate", 192_000)), cfg)


REGISTRY = DeviceRegistry()
REGISTRY.register("sim", _sim)
REGISTRY.register("hl2", _hl2)
make_device = REGISTRY.make

__all__ = ["REGISTRY", "make_device"]
