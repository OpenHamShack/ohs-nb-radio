"""May this station transmit this signal? Both apps ask here, and the
answer comes from the shared band-plan and licence dataset (ohs-libs
shack_bandplan) applied to the station profile, never from tables in this
repository (BETA-PLAN architecture change 5: band limits and TX
permission are data, driven by the profile's country, region and class).

Why an adapter rather than calling shack_bandplan from each app:

- The apps keep their settings in their own state (callsign,
  stationCountry, licence, licenceClass, customLicence,
  stationConditions); `profile()` is the one place that turns those into
  the shared station profile (SERVICES.md section 2.1), so the two apps
  cannot drift in how they read it.
- A verdict here has the shape the engines already consume (refused,
  warning, limit_w, limit_kind, segment), with the dataset's warnings
  sorted into the licence's power warning and the band plan's, which the
  transmit card shows apart (ohsradio/radio.py _licence_warnings).
- Resolving a profile reads cty.dat, so contexts are cached per profile
  and day: _derive() asks on every dial step.

The dataset was converted from this repository's own ohscore/licences,
ohsradio/plans and ohsnb/bandplan.py, and ohs-libs' test_conformance.py proves
it gives the same allow/refuse and limits as those modules on a grid of
every row edge, except a listed set of intended differences
(docs/RELEASE-NOTES-beta.md). The modules stay, for the Settings pages
and the scope's shading, and as the other side of that proof.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date

from . import shacklibs

# Refusals that mean the licence cannot be worked out, not that it says
# no: QO-100 NB warns instead of locking on these (ohsnb/radio.py
# _licence_warning, Brian 08/10/2026); Radio locks.
LICENCE_UNKNOWN = frozenset({"no_regime", "no_country", "no_class", "at_sea"})
# Dataset warnings that are the band plan's, shown as the plan warning;
# power_estimated_over is the licence's power warning; the rest are notes.
PLAN_WARNINGS = frozenset({"plan_mode", "plan_bandwidth", "plan_output", "plan_advice", "plan_gap",
                           "plan_unplanned"})
# Modes the dataset's vocabulary (shack_bandplan vocab.json modeClass) does
# not know yet, as the class it should file them under. A mode it does not
# know has no class, and a signal with no class is judged by where it
# reaches alone - any segment's mode rule passes it - so an app's new mode
# must be named here until ohs-libs adds it. KG-STV is a picture mode, as
# SSTV is ("image"). Wide FM is never transmitted (Engine._tx_blocked
# refuses it first), but the licence chip still judges the dial in it, as
# FM.
MODE_ALIASES = {"kgstv": "image", "wfm": "fm"}
# Settings a station profile condition may still live under, from before
# stationConditions (the UK's nearLondon).
LEGACY_CONDITIONS = ("nearLondon",)


@dataclass
class Verdict:
    refused: str = ""              # the sentence, if keying must not happen
    code: str = ""                 # the dataset's refusal code (BANDPLAN-DATA.md section 6.2)
    warning: str = ""              # the licence's: an estimate over the power limit
    plan_warning: str = ""         # the band plan's, when its guard is "warn"
    notes: list = field(default_factory=list)   # everything else the dataset said (researched data...)
    limit_w: float | None = None
    limit_kind: str = "PEP"
    segment: str = ""
    data_version: str = ""

    @property
    def ok(self) -> bool:
        return not self.refused

    @property
    def licence_unknown(self) -> bool:
        return self.code in LICENCE_UNKNOWN


def profile(st: dict) -> dict:
    """The station profile (SERVICES.md section 2.1) an app's state
    describes. Only what the check reads; antenna gain travels with each
    signal because the power chain is per band in Radio."""
    choice = st.get("licence") or "auto"
    lic = {"regime": choice, "class": st.get("licenceClass", "") or ""}
    if choice == "custom":
        lic["custom"] = list(st.get("customLicence") or [])
    conditions = {k: bool(st[k]) for k in LEGACY_CONDITIONS if k in st}
    conditions.update({k: bool(v) for k, v in (st.get("stationConditions") or {}).items()})
    out = {"callsign": st.get("callsign", "") or "", "licence": lic, "conditions": conditions}
    if st.get("stationCountry"):
        # A DXCC entity's prefix (GM, EA8, K: ohscore/state.py), which is the
        # profile's dxccPrefix, not its ISO country: GM and G are one
        # country with two sets of conditions (Scotland's 146 MHz edge).
        out["dxccPrefix"] = str(st["stationCountry"]).strip().upper()
    if st.get("novs"):
        out["novs"] = list(st["novs"])
    return out


# The QO-100 narrowband plan with every licence question set aside: a
# station's own licence is judged separately (ohsnb/radio.py
# _uplink_refusal), and NB judges the plan whether or not a licence is set.
PLAN_ONLY = {"callsign": "", "licence": {"regime": "custom", "class": "own", "custom": [
    {"lo": 2_400_000_000, "hi": 2_450_000_000, "watts": 10_000, "unit": "PEP", "satellite": True,
     "note": "set aside: only the satellite's plan is judged"}]}}


class Guard:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._bp = None

    @property
    def bp(self):
        if self._bp is None:
            self._bp = shacklibs.bandplan()
        return self._bp

    def data(self):
        return self.bp.bundled()

    def context(self, prof: dict, plan: str = ""):
        key = (json.dumps(prof, sort_keys=True), plan or "", date.today().isoformat())
        with self._lock:
            ctx = self._cache.get(key)
            if ctx is None:
                if len(self._cache) > 32:
                    self._cache.clear()
                ctx = self.bp.context(prof, self.data(), today=key[2], plan=plan if plan not in ("", "auto") else "")
                self._cache[key] = ctx
            return ctx

    def check(self, prof: dict, lo: float, hi: float, *, mode: str | None = None, pep: float | None = None,
              gain: float | None = None, measured: bool = False, plan: str = "", plan_guard: str = "off",
              signal_bw: float | None = None, satellite: str | None = None) -> Verdict:
        """The verdict for a signal occupying [lo, hi] Hz (both edges are
        judged, never the dial). `signal_bw`: one signal's own width when
        it is known but not where in [lo, hi] it sits (the plans' width
        limits judge that; 0 judges reach alone). `satellite`: a dataset
        satellite id, making this an uplink to it."""
        bp = self.bp
        ctx = self.context(prof, plan)
        mode = MODE_ALIASES.get(mode, mode)
        sig = bp.Signal.edges(lo, hi, mode=mode, power_w=pep, measured=measured, antenna_gain_dbi=gain,
                              purpose="satellite-uplink" if satellite else "terrestrial", satellite=satellite,
                              signal_bw_hz=signal_bw)
        v = bp.check(ctx, sig, plan_guard)
        out = Verdict(data_version=v.get("dataVersion", ""))
        if v["refusal"]:
            out.refused, out.code = v["refusal"]["text"], v["refusal"]["code"]
        if v["limit"]:
            out.limit_w, out.limit_kind = v["limit"]["watts"], v["limit"]["unit"]
        if v["segment"]:
            out.segment = v["segment"].get("label", "")
        for w in v["warnings"]:
            if w["code"] == "power_estimated_over":
                out.warning = out.warning or w["text"]
            elif w["code"] in PLAN_WARNINGS:
                out.plan_warning = out.plan_warning or w["text"]
            else:
                out.notes.append(w["text"])
        return out

    def in_force(self, prof: dict) -> dict:
        """SERVICES.md section 2.2 `derived`: regime, class name, whether
        this profile can transmit at all and the sentence when not."""
        return self.bp.in_force(prof, self.data())


GUARD = Guard()
