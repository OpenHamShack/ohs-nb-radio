"""OpenHamShack Radio's configuration file: ohscore.config bound to Radio's
name and environment variables ($OHS_RADIO_CONF, $OHS_RADIO_DATA,
$OHS_RADIO_UI_CONF) and its state registry. Separate from QO-100 NB's in
every respect, so the two install and run side by side
(docs/ham/DESIGN-HAM.md section 1).

Radio was OpenHamShack HAM: the package and folder were openhamshack-ham
and the variables $OHSRADIO_* until the OpenHamShack rename (17/10/2026).
The former variables are still read when the new ones are not set
(ohscore/config.py AppId.former_env). An installation under the old
package name is not moved to the new one automatically: see
docs/update-feed.md and docs/names.md."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ohscore import countries
from ohscore.config import AppId, Config

from . import state

APP = AppId(name="openhamshack-radio", env="OHS_RADIO", former_env="OHSRADIO")

# 2: the licence class has no default (Brian, 05/10/2026). Files written
# before it are version 1 (no number at all).
# 3: the licence and plan follow the station's country (08/10/2026).
VERSION = 3


def _repair(cfg: dict) -> None:
    # Nothing that raises power: a stored drive above 1 cannot exist (the
    # registry's range), and the per-band ceiling is applied by the engine
    # once it knows the band.
    pass


def _licence_acknowledged(conf: Path) -> bool:
    """Whether the window's preferences beside `conf` (ohscore/ui/prefs.py:
    ui.json, or $OHS_RADIO_UI_CONF) record the licence box ticked. Read as a
    plain file so the engine needs no window code; anything unreadable is
    "no", as it is for the window."""
    env = APP.getenv("UI_CONF")
    p = Path(env) if env else conf.with_name("ui.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("licenceAck") is True
    except (OSError, ValueError, AttributeError):
        return False


def _migrate(raw: dict, path: Path, notes: list[str]) -> dict:
    try:
        stored = int(raw.get(Config.VERSION_KEY, 0))
    except (TypeError, ValueError):
        stored = 0
    if stored < 2:
        raw = _migrate_class(raw, path, notes)
    if stored < 3:
        raw = _migrate_country(raw, notes)
    return raw


def _migrate_country(raw: dict, notes: list[str]) -> dict:
    """Version 2 -> 3 (08/10/2026): the licence and band plan follow the
    station's country ("auto") instead of being Ofcom's and the RSGB's for
    everyone. Every earlier save wrote licence "ofcom-2024" and plan
    "rsgb-2026" - the only choices there were - so neither is evidence of
    a choice. Where the callsign puts the station in the UK, "auto" gives
    exactly those, and the file says "auto" from now on. Anywhere else -
    no callsign, or one from abroad - nothing changes under the operator:
    the two stay pinned to Ofcom and RSGB, as they were, and a note says
    how to follow the station's country instead. A UK operator therefore
    sees no difference, and nobody is silently moved off the licence they
    have been keying under."""
    st = countries.station(raw.get("callsign", ""), raw.get("stationCountry", ""), None)
    uk = st.regime == "ofcom-2024"
    lic = raw.get("licence", "ofcom-2024")
    if lic == "ofcom-2024":
        raw["licence"] = "auto" if uk else "ofcom-2024"
    plan = raw.get("plan", "rsgb-2026")
    if plan == "rsgb-2026":
        raw["plan"] = "auto" if uk and st.country.plan == "rsgb-2026" else "rsgb-2026"
    if not uk and raw.get("licence") == "ofcom-2024":
        where = st.entity or "not known (no callsign set)"
        notes.append(f"Licence: kept as the UK's (Ofcom) and the RSGB band plan, as before. OpenHamShack Radio now follows "
                     f"the station's country, which your callsign puts in {where}: choose 'auto' in Settings › "
                     f"Licence & plan to follow it.")
    return raw


def _migrate_class(raw: dict, path: Path, notes: list[str]) -> dict:
    """Version 1 -> 2. Until 05/10/2026 Foundation was the default class and
    every save wrote it, so a stored "foundation" is either a choice or the
    default nobody looked at. Intermediate and Full can only have been
    chosen: kept. Foundation is kept only where the operator ticked the
    licence box ("I hold an amateur licence of the class I have chosen
    above" in Welcome, "... of the class set in Settings" in Settings ›
    Station): a statement that Foundation is theirs, even though it had
    been preselected. Anywhere else (the box never ticked, a
    headless-only install with no window preferences at all) nobody ever
    said Foundation, so the class becomes unset and transmit stays locked
    until one is chosen: one click for a real Foundation licensee, against
    keying under a class the operator may not hold."""
    if raw.get("licenceClass") == "foundation" and not _licence_acknowledged(path):
        raw["licenceClass"] = ""
        notes.append("Licence class: Foundation was only the old default and was never confirmed, so it is "
                     "now unset. Transmit stays locked until you choose your class (Settings › Licence & plan).")
    return raw


CONFIG = Config(APP, state.REG, repair=_repair, freq_key="rf", version=VERSION, migrate=_migrate)
conf_path = CONFIG.conf_path
data_dir = CONFIG.data_dir
load = CONFIG.load
save = CONFIG.save
