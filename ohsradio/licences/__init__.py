"""Licence regimes moved to ohscore/licences/ on 08/10/2026 (QO-100 NB
needs them for the 13 cm uplink); this keeps `from ohsradio.licences import
ofcom` working for code and tests written before."""
from __future__ import annotations

from ohscore.licences import REGIMES, ofcom  # noqa: F401
from ohscore.licences import get as _get

LICENCES = REGIMES


def get(licence_id: str):
    return _get(licence_id) or ofcom
