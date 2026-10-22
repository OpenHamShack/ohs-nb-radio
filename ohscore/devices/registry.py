"""Device name -> factory, filled by each app.

`make_device` used to be one if-chain in ohsnb that knew every device by
name. The real radios are the same for both apps, but `sim` is not: OpenHamShack
NB simulates the QO-100 transponder, OpenHamShack Radio a terrestrial band. So the
core supplies the radios it owns and each app registers its own simulator
(and anything else only it offers) under the names its `device` setting
lists.

Factories import their driver only when called, so a missing python3-libiio
or python3-soapysdr disables that one device with a sentence instead of
stopping the program.
"""
from __future__ import annotations

from typing import Callable

from .base import Device, DeviceError

Factory = Callable[[dict, float], Device]


def _pluto(cfg: dict, fs: float) -> Device:
    from .pluto import PlutoDevice
    return PlutoDevice(cfg.get("plutoUri", "ip:192.168.2.1"), fs, cfg)


def _soapy(cfg: dict, fs: float) -> Device:
    from .soapy import SoapyDevice
    return SoapyDevice(cfg.get("soapyArgs", ""), fs, cfg)


class DeviceRegistry:
    """Starts with the core's radios (`pluto`, `soapy`); the app adds the
    rest with `register`. A later registration of the same name replaces
    the earlier one."""

    def __init__(self):
        self.factories: dict[str, Factory] = {"pluto": _pluto, "soapy": _soapy}

    def register(self, kind: str, factory: Factory) -> None:
        self.factories[kind] = factory

    def make(self, cfg: dict) -> Device:
        """The configured device, not yet opened."""
        kind = cfg.get("device", "sim")
        fs = float(cfg.get("sampleRate", 1_200_000))
        factory = self.factories.get(kind)
        if factory is None:
            raise DeviceError(f"Unknown device {kind!r}")
        return factory(cfg, fs)
