"""Radio's store form (`python3 -m ohsradio --server`): its facts for the
shared server in ohscore/server.

The broker is told the occupied signal on the transmit dial and the
power chain's estimate at the antenna (estPep): the broker's own licence
check judges power only when it is given, and an estimate is what Radio
has (ohsradio/guard.py: advisory until measured). The Pluto and the
Hermes-Lite 2 are lent by the broker, and so is an SDRplay RSP through
SoapySDR (receive only; the image carries the SDRplay API and its Soapy
module, and the manifest asks for the USB bus). The serial PTT sequencer
needs a device a container is not given.
"""
from __future__ import annotations

from ohscore.server.app import AppInfo

# "soapy" is the SDRplay because that is the only SoapySDR receiver the
# store image can open; another would need its module there and a class
# of its own here.
DEVICES = {"pluto": "pluto-1", "hl2": "hl2-1", "soapy": "sdrplay-1"}


def onair_body(radio) -> dict:
    s = radio.state()
    lo, hi = radio._occupied(s["mode"], s["txDial"])
    body = {"freqHz": int(round((lo + hi) / 2)), "bandwidthHz": int(round(hi - lo)), "mode": s["mode"]}
    if s.get("estPep"):
        body["powerW"] = round(float(s["estPep"]), 3)
    return body


def info(version: str, commit: str = "") -> AppInfo:
    return AppInfo("shack-radio", "radio", "Radio", version, onair_body, lambda dev: DEVICES.get(dev, ""), commit)
