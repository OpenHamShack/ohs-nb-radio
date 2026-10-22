"""Band plans as data (docs/ham/DESIGN-HAM.md section 5.1; the shape is
ohsradio/plans/base.py). A plan is a complete, self-contained table, not a
set of patches on another (bandplan-r1-uk.md section 4: the UK's 70 cm
repeater pairs run the other way from IARU R1's).

National plans are chosen by the station's country (ohscore/countries.py);
a country without one gets its IARU region's plan, the generic fallback
(docs/ham/bandplan-iaru-regions.md)."""
from __future__ import annotations

from . import iaru_r1, iaru_r2, iaru_r3, rsgb_2026

PLANS = {m.ID: m for m in (rsgb_2026, iaru_r1, iaru_r2, iaru_r3)}
# The IARU regional plans, by region.
REGIONAL: dict[int, str] = {1: iaru_r1.ID, 2: iaru_r2.ID, 3: iaru_r3.ID}

AUTO = "auto"


def get(plan_id: str):
    """The plan with this id; the RSGB plan for an unknown id, as before
    there was a choice (a config naming a plan this version lacks)."""
    return PLANS.get(plan_id, rsgb_2026)


def for_region(region: int | None) -> str:
    """The IARU plan of a region, or "" when it is not written."""
    return REGIONAL.get(region or 0, "")


def choose(setting: str, country_plan: str = "", regime_plan: str = "", region: int | None = None) -> str:
    """The plan in force: the operator's choice, else the station country's
    national plan, else the licence regime's own country's plan (a UK
    licence chosen with no callsign set), else the region's IARU plan,
    else IARU Region 1's - a choice with nothing known, shown as such."""
    if setting and setting != AUTO and setting in PLANS:
        return setting
    for pid in (country_plan, regime_plan, for_region(region), for_region(1)):
        if pid and pid in PLANS:
            return pid
    return rsgb_2026.ID
