"""External rigs: radios the program reads and tunes, and keys only for a
digital over under a PttPermit (base.py: since 12/10/2026, by Brian's
decision; before that they could not be keyed at all).

- `civ`: Icom CI-V (the IC-9700) over a serial port or socket://;
  `civsim` emulates the radio for tests and demos.
- `rigctl`: Hamlib's rigctld over TCP; `rigctlsim` is a fake rigctld.
- `link`: RigLink, the thread that polls one rig for its owner.

QO-100 NB uses these for an IC-9700 as its uplink transmitter
(ohsnb/extrig.py). They are in the core because they know nothing about
QO-100: OpenHamShack Radio's planned CAT link would use them as they are. The
settings they read are named the same in both apps: civPort, civBaud,
civAddress, rigctldHost, rigctldPort.
"""
from __future__ import annotations

from .base import ForbiddenCommand, PttPermit, Rig, RigError, RigTimeout, SetupPermit

KINDS = ("civ", "rigctld")


def make_rig(kind: str, cfg: dict) -> Rig:
    if kind == "civ":
        from .civ import CivRig
        return CivRig(cfg.get("civPort", ""), int(cfg.get("civBaud", 115200)), int(cfg.get("civAddress", 0xA2)))
    if kind == "rigctld":
        from .rigctl import RigctldRig
        return RigctldRig(cfg.get("rigctldHost", "127.0.0.1"), int(cfg.get("rigctldPort", 4532)))
    raise RigError(f"Unknown rig link {kind!r}")


def probe(kind: str, cfg: dict) -> int:
    """Open the rig, read its frequency once, close it: Settings' "Test
    connection". Reads only. Raises RigError with a sentence."""
    rig = make_rig(kind, cfg)
    try:
        rig.open()
        return rig.read_freq()
    finally:
        rig.close()


__all__ = ["ForbiddenCommand", "PttPermit", "SetupPermit", "Rig", "RigError", "RigTimeout", "KINDS", "make_rig", "probe"]
