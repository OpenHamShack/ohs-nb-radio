"""The devices OpenHamShack Radio offers: the core's Pluto family, SoapySDR
receivers and the RTL-SDR and SDRplay receivers shack_sdr reaches
(ohscore/devices/sdrsource.py), the Hermes-Lite 2 (ohscore/devices/hl2.py),
a LibreSDR by name, and its own `sim`, a simulated set of amateur bands
(docs/ham/DESIGN-HAM.md section 4)."""
from __future__ import annotations

from ohscore.devices import Device, DeviceRegistry


def _sim(cfg: dict, fs: float) -> Device:
    from .sim import HamSim
    return HamSim(cfg, fs)


def _hl2(cfg: dict, fs: float) -> Device:
    # The HL2 runs at its own rate (hl2Rate), not the Pluto's sampleRate.
    from ohscore.devices.hl2 import HL2Device
    return HL2Device(cfg.get("hl2Address", ""), float(cfg.get("hl2Rate", 192_000)), cfg)


def _libresdr(cfg: dict, fs: float) -> Device:
    # A LibreSDR is a Pluto to the driver (libiio, the AD936x), and the same
    # plutoUri reaches it. A device of its own only so the store form claims
    # the broker's libresdr-1 for it, the class the broker keeps apart from
    # the Pluto (RADIO-SDR-PLAN §6.1).
    from ohscore.devices.pluto import PlutoDevice
    return PlutoDevice(cfg.get("plutoUri", "ip:198.51.100.10"), fs, cfg)


REGISTRY = DeviceRegistry()
REGISTRY.register("sim", _sim)
REGISTRY.register("hl2", _hl2)
REGISTRY.register("libresdr", _libresdr)
make_device = REGISTRY.make

__all__ = ["REGISTRY", "make_device"]
