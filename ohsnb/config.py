"""QO-100 NB's configuration file: ohscore.config bound to NB's name, its
environment variables ($OHS_NB_CONF, $OHS_NB_DATA) and its state registry.

The variables were $OHSNB_* until the OpenHamShack rename (17/10/2026);
the former ones are still read when the new ones are not set
(ohscore/config.py AppId.former_env), so a script, a container or a
shortcut that still sets $OHSNB_CONF keeps working. The package and
folder name, openhamshack-nb, has never changed."""
from __future__ import annotations

from ohscore import converters as cv
from ohscore.config import AppId, Config

from . import converters as nbconv
from . import state

APP = AppId(name="openhamshack-nb", env="OHS_NB", former_env="OHSNB")


def _repair(cfg: dict) -> None:
    # The gain ceiling wins over a stored gain, never the other way round;
    # a stored transmit filter wider than QO-100's 2.7 kHz goes back to the
    # default rather than being refused at the first key-up.
    if cfg["txGain"] > cfg["txGainCeiling"]:
        cfg["txGain"] = cfg["txGainCeiling"]
    if cfg["txFilterHi"] - cfg["txFilterLo"] > 2700:
        cfg["txFilterLo"], cfg["txFilterHi"] = 300.0, 2700.0
    # A receive converter that is not in the list (a hand-edited file, or a
    # list that failed validation and went back to the default) falls back
    # to the first LNB that works, else the standard one: receiving is
    # never worth refusing. The transmit converters are left as they are -
    # quietly emptying one would send the Pluto's output straight to 2400
    # MHz instead of to its upconverter's IF, so the transmit guard refuses
    # a missing one instead, and says so.
    if nbconv.rx_ok(nbconv.rx_converter(cfg)):
        usable = [c for c in cv.parse(cfg["converters"]) if not nbconv.rx_ok(c)]
        if not usable:
            cfg["converters"] = cfg["converters"] + [nbconv.LNB_DEFAULT.copy_as(
                cv.unique_title(cfg["converters"], nbconv.LNB_DEFAULT.title)).to_dict()]
            usable = [cv.Converter.from_dict(cfg["converters"][-1])]
        cfg["rxConverter"] = usable[0].title


def _renamed(raw: dict, notes: list[str]) -> dict:
    """beaconLock (on/off) became beaconMode (auto/hold/manual) in 0.1.4.
    On is Auto. Off became Hold, not Manual: off has always meant "stop
    tracking and keep the last correction", which is exactly Hold, and
    Manual would put nudge buttons in front of someone who never asked
    for them. A file with both keys was written by hand; beaconMode wins."""
    if "beaconLock" in raw:
        old = raw.pop("beaconLock")
        if "beaconMode" not in raw:
            raw["beaconMode"] = "auto" if old is True or str(old).lower() in ("true", "1", "on") else "hold"
    # lnbLo and the IC-9700's upconverter LO and side became converter
    # definitions; ohsnb/converters.py says how, and why it is safe.
    return nbconv.migrate(raw, notes)


CONFIG = Config(APP, state.REG, repair=_repair, renamed=_renamed)
conf_path = CONFIG.conf_path
data_dir = CONFIG.data_dir
defaults = CONFIG.defaults
clean = CONFIG.clean
clean_memories = CONFIG.clean_memories
load = CONFIG.load
save = CONFIG.save
