"""The devices QO-100 NB offers: the core's Pluto family and SoapySDR
receivers, plus its own `sim`, the simulated QO-100 transponder."""
from __future__ import annotations

from ohscore.devices import Device, DeviceRegistry


def _sim(cfg: dict, fs: float) -> Device:
    from .sim import SimDevice
    return SimDevice(cfg, fs)


REGISTRY = DeviceRegistry()
REGISTRY.register("sim", _sim)
make_device = REGISTRY.make

__all__ = ["REGISTRY", "make_device"]
