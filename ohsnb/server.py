"""QO-100 NB's store form (`python3 -m ohsnb --server`): its facts for the
shared server in ohscore/server.

Where the signal goes on air is NB's own knowledge: the dial is a
downlink, so the broker's licence check (CONTROLLER-CONTRACT 7.4) is
told the uplink, with TX lock's correction, and the occupied width of the
mode at the dial. Only the Pluto is lent by the broker; the IC-9700 as an
external transmitter needs a serial port no container is given, so the
store form transmits with the Pluto or not at all.
"""
from __future__ import annotations

from ohscore.server.app import AppInfo

from . import bandplan

DEVICES = {"pluto": "pluto-1"}


def onair_body(radio) -> dict:
    s = radio.state()
    lo, hi = radio._occupied(s["mode"], s["txDial"])
    ul_lo, ul_hi = bandplan.ul(lo) + s["txCorr"], bandplan.ul(hi) + s["txCorr"]
    return {"freqHz": int(round((ul_lo + ul_hi) / 2)), "bandwidthHz": int(round(ul_hi - ul_lo)),
            "mode": s["mode"], "satellite": "qo100-nb"}


def info(version: str, commit: str = "") -> AppInfo:
    return AppInfo("shack-qo100nb", "qo100nb", "QO-100 NB", version, onair_body,
                   lambda dev: DEVICES.get(dev, ""), commit)
