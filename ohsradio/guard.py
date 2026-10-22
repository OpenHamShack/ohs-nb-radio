"""The transmit guard: the licence (law, always enforced), the band plan
(a code of practice: warn, enforce or off) and the plan's reserved
segments (beacons, satellites: always refused). docs/ham/DESIGN-HAM.md
section 6, rules 2 and 3.

Both edges of the occupied signal are judged, never the dial: an LSB
signal dialled on 1850.5 kHz puts 2.7 kHz of speech below 1850 kHz, where
an Intermediate licensee has 100 W rather than 32 W; an FT8 tone at
1.5 kHz above the 60 m dial of 5357 kHz leaves the UK segment.

Power is advisory until measured (Brian, 05/10/2026): an *estimate* from
the power chain (ohsradio/power.py) over the class's limit is a warning,
never a refusal, because the chain is numbers the operator typed and can
be wrong either way. A *measured* excess (`measured=True`: the radio's
forward-power sensor) is a refusal, and the engine unkeys on it. The
licence's frequencies, and the plan's beacon and satellite segments,
stay hard whatever the power.

Every function here is pure: the engine passes the state it has.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ohscore import licences
from ohscore.licences import ofcom

from . import plans


def khz(f: float) -> str:
    return f"{f / 1e3:.1f}".rstrip("0").rstrip(".") if f < 30e6 else mhz(f)


def mhz(f: float) -> str:
    s = f"{f / 1e6:.4f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def span(lo: float, hi: float) -> str:
    """'1850-2000 kHz', '430-431 MHz'."""
    if hi < 30e6:
        return f"{khz(lo)}-{khz(hi)} kHz"
    return f"{mhz(lo)}-{mhz(hi)} MHz"


def watts(w: float) -> str:
    if w >= 10:
        return f"{w:.0f} W"
    if w >= 1:
        return f"{w:.1f} W"
    if w >= 1e-3:
        return f"{w * 1e3:.3g} mW"
    return f"{w * 1e6:.3g} µW"


# The class is unset until the operator chooses one (ohsradio/state.py).
NO_CLASS = ("No licence class chosen: transmit stays locked until you choose yours "
            "(Settings › Licence & plan, or the Welcome screen)")
# No regime in force: the station's country has none written here and the
# operator has entered none (ohscore/countries.py). The engine passes a
# sentence naming the country; this is the one when nothing is known.
NO_REGIME = ("No licence is set up for this station's country yet: transmit stays locked until you choose a "
             "licence or enter your own (Settings › Licence & plan)")
NO_REGIME_IN = ("No licence for {country} is written into OpenHamShack yet: transmit stays locked until you enter your "
                "own licence's segments and power limits (Settings › Licence & plan › Your own licence)")
NO_COUNTRY = ("The station's country is not known: transmit stays locked until you set your callsign or "
              "choose the country (Settings › Station), or enter your own licence (Settings › Licence & plan)")
# A row the research could not confirm from the instrument (the regime
# marks it): refused until somebody does, never guessed open.
UNCONFIRMED = ("{span} is marked unconfirmed in OpenHamShack's data for {regime}: it stays refused until it has been "
               "checked against the licence")
# OpenHamShack Radio has no satellite mode: a band the licence gives to the
# amateur-satellite service alone is refused (NB's uplink check allows it).
SATELLITE_ONLY = ("{regime} allows {span} for the amateur-satellite service only: OpenHamShack Radio does not "
                  "transmit there")
OUTSIDE_OWN = ("{span} is outside every segment of your own licence (Settings › Licence & plan): add the segment "
               "if your licence allows it")
# A class kept from another regime: one regime's Full is not another's.
WRONG_CLASS = ("Your licence class belongs to a different licence than {regime}: choose your class again "
               "(Settings › Licence & plan)")


@dataclass
class Verdict:
    refused: str = ""          # the sentence, if keying must not happen
    warning: str = ""          # an objection that only warns: the band plan's, or an estimate over the limit
    limit_w: float | None = None   # the class's power limit where the signal sits
    limit_kind: str = "PEP"
    segment: str = ""          # the plan segment under the signal

    @property
    def ok(self) -> bool:
        return not self.refused


def power_in(kind: str, pep_w: float, ant_gain_dbi: float) -> float:
    """The licence's measure from PEP at the antenna: ERP is relative to a
    half-wave dipole (2.15 dBi), EIRP to an isotropic antenna."""
    if kind == "ERP":
        return pep_w * 10 ** ((ant_gain_dbi - 2.15) / 10)
    if kind == "EIRP":
        return pep_w * 10 ** (ant_gain_dbi / 10)
    return pep_w


def max_pep_for(kind: str, limit_w: float, ant_gain_dbi: float) -> float:
    """The PEP at the antenna that meets `limit_w` in `kind`."""
    return limit_w / max(1e-12, power_in(kind, 1.0, ant_gain_dbi))


def licence_check(cls: str, lo: float, hi: float, pep_w: float | None, ant_gain_dbi: float = 0.0,
                  near_london: bool = False, measured: bool = False, lic=ofcom, mode: str | None = None,
                  conditions: dict | None = None, no_regime: str = "", region: int | None = None,
                  today: str | None = None) -> Verdict:
    """Whether a signal occupying [lo, hi] Hz at `pep_w` watts PEP at the
    antenna (None: power not judged) is within licence class `cls` of
    regime `lic` (ohscore/licences: a written regime, or the operator's own
    from licences.custom()). Power over the limit refuses only when
    `measured`; an estimate warns.

    `lic` None means no regime is in force - the station's country has none
    written and the operator has entered none - and refuses with
    `no_regime`, the sentence saying how to set one up. `conditions` are the
    station conditions the operator declared ({"nearLondon": True});
    `near_london` is the older spelling of that one; a condition not
    answered takes its `default`. `mode` lets a regime's EMISSIONS and
    mode-conditional limits judge the mode; without it every limit applies
    and the strictest wins. `region` (the station's IARU region) and `today`
    (ISO date) select the allocation rows that apply; a row marked
    unconfirmed is refused.

    Every sentence comes from the regime's data or is a whole sentence with
    the regime's names in it, never built from fragments, so a later
    translation can take them whole."""
    if hi < lo:
        lo, hi = hi, lo
    v = Verdict()
    if lic is None:
        v.refused = no_regime or NO_REGIME
        return v
    if not cls:
        v.refused = NO_CLASS
        return v
    if cls not in lic.CLASSES:
        v.refused = WRONG_CLASS.format(regime=lic.SHORT)
        return v
    name = licences.class_name(lic, cls)
    conditions = dict(conditions or {})
    if near_london:
        conditions["nearLondon"] = True

    def over(sentence: str, got: float, unit: str) -> None:
        if measured:
            v.refused = f"{sentence} (measured {watts(got)}{unit})"
        else:
            v.warning = (f"{sentence}, and the power chain's estimate is {watts(got)}{unit}. An estimate, so a "
                         f"warning, not a refusal: check it with a power meter")
    for a, b, sentence, _src in getattr(lic, "REFUSED", []):
        if lo < b and hi > a:
            v.refused = sentence
            return v
    for ch in getattr(lic, "CHANNELLED", []):
        if not (lo < ch["hi"] and hi > ch["lo"]):
            continue
        if cls not in ch["limits"]:
            who = " or ".join(licences.class_name(lic, c) for c in ch["limits"])
            v.refused = f"{name} licence: {ch['label']} is open only to {who} licensees"
            return v
        if not any(a <= lo and hi <= b for a, b in ch["segments"]):
            v.refused = (f"{ch['label']}: the signal must lie inside one of {ch['where']} "
                         f"({span(lo, hi)} does not)")
            return v
        if ch.get("max_bw") is not None and hi - lo > ch["max_bw"] + 1e-6:
            v.refused = (f"{ch['label']} allows {ch['max_bw'] / 1e3:g} kHz at most; this signal is "
                         f"{(hi - lo) / 1e3:.1f} kHz")
            return v
        lims = ch["limits"][cls]
        first = lims[0]
        v.limit_w, v.limit_kind = first
        if pep_w is not None:
            for w, kind in lims:
                got = power_in(kind, pep_w, ant_gain_dbi)
                if got > w * 1.0001:
                    over(f"{name} licence: {watts(w)} {kind} maximum on {ch['label']}", got,
                         "" if kind == "PEP" else " " + kind)
                    break
        return v
    rows = sorted((r for r in lic.ALLOCATIONS if (lo < r[1] and hi > r[0] or (lo == hi and r[0] <= lo <= r[1]))
                   and licences.row_in_force(r, region, today)), key=lambda r: r[0])
    # The class must hold every part of [lo, hi], contiguously.
    covered = lo
    mine = []
    for r in rows:
        if cls not in r[2]:
            continue
        if r[0] > covered + 1e-6:
            break
        covered = max(covered, r[1])
        mine.append(r)
    if not mine or covered < hi - 1e-6:
        where = rows[0] if rows else None
        if where is None and getattr(lic, "ID", "") == licences.CUSTOM:
            # The operator's own segments are not the whole amateur service:
            # say what is known, not that the band is not amateur.
            v.refused = OUTSIDE_OWN.format(span=span(lo, hi))
        elif where is None:
            v.refused = f"{span(lo, hi)} is not an amateur band"
        elif not any(cls in r[2] for r in rows):
            v.refused = f"{name} licence: {span(where[0], where[1])} is not available"
        else:
            v.refused = f"{name} licence: the signal would leave the allocation ({span(lo, hi)})"
        return v
    for r in mine:
        if licences.row_extras(r).get("unconfirmed"):
            v.refused = UNCONFIRMED.format(span=span(r[0], r[1]), regime=lic.SHORT)
            return v
        if licences.row_extras(r).get("satellite_only"):
            v.refused = SATELLITE_ONLY.format(span=span(r[0], r[1]), regime=lic.SHORT)
            return v
    extra_limits = []          # (Limit, label) from conditions that hold power down here
    for cond in getattr(lic, "CONDITIONS", []):
        if not (lo < cond["hi"] and hi > cond["lo"]):
            continue
        answer = conditions.get(cond["key"], cond.get("default", False))
        if bool(answer) != cond.get("when", True):
            continue
        if "refuse" in cond:
            v.refused = cond["refuse"]
            return v
        extra_limits.append((cond["limit"], cond["label"]))
    mclass = licences.MODE_CLASS.get(mode) if mode else None
    for a, b, per_class, max_bw, _note, _src in getattr(lic, "EMISSIONS", []):
        if not (lo < b and hi > a) or mode is None:
            continue
        allowed = per_class.get(cls)
        if allowed is None:
            continue                       # a class not in the row is not restricted by it
        if mclass not in allowed:
            v.refused = f"{name} licence: {mode.upper()} is not permitted on {span(a, b)}"
            return v
        if max_bw is not None and hi - lo > max_bw + 1e-6:
            v.refused = f"{name} licence: {span(a, b)} allows signals up to {max_bw:.0f} Hz; this one is {hi - lo:.0f} Hz"
            return v
    # The tightest limit among the rows the signal touches, of those that
    # apply to its mode, and any a station condition adds.
    worst = None
    cands = [(lim, f"on {span(r[0], r[1])}") for r in mine for lim in licences.applicable(r[2][cls], mclass)]
    cands += [(lim, f"({label})") for lim, label in extra_limits if mclass is None or lim.modes is None
              or mclass in lim.modes]
    for lim, where in cands:
        allowed_pep = max_pep_for(lim.unit, lim.watts, ant_gain_dbi)
        if worst is None or allowed_pep < worst[0]:
            worst = (allowed_pep, lim.watts, lim.unit, where)
    if worst is None:
        return v
    _, w, kind, where = worst
    v.limit_w, v.limit_kind = w, kind
    if pep_w is not None:
        got = power_in(kind, pep_w, ant_gain_dbi)
        if got > w * 1.0001:
            over(f"{name} licence: {watts(w)} {kind} maximum {where}", got, "" if kind == "PEP" else " " + kind)
    return v


# Typical occupied bandwidth of one signal in each mode, Hz, for judging a
# segment's bandwidth limit before the audio exists (a digital mode's dial
# window is 3 kHz, its signal 50 Hz). Measured audio replaces these. JS8
# is its widest speed's, Ultra's 298 Hz rounded up (ohsnb/bandplan.py
# SIGNAL_WIDTH gives the measurements).
SIGNAL_WIDTH = {"cw": 100.0, "ft8": 50.0, "ft4": 90.0, "js8": 300.0, "wspr": 6.0, "psk31": 60.0, "psk63": 120.0,
                "psk125": 240.0, "rtty": 250.0, "freedv": 1250.0, "sstv": 2500.0}


def plan_check(mode: str, lo: float, hi: float, guard: str = "warn", plan=None, width: float | None = None) -> Verdict:
    """The band plan's view of a signal on [lo, hi] in `mode`, `width` Hz
    wide (default: hi - lo). Beacon and satellite segments are refused
    whatever `guard` says; otherwise `guard` "enforce" refuses, "warn"
    warns, "off" says nothing."""
    plan = plan or plans.get("rsgb-2026")
    if hi < lo:
        lo, hi = hi, lo
    v = Verdict()
    segs = plan.overlapping(lo, hi)
    for s in segs:
        if s.refused:
            v.refused = (f"The signal would reach the {s.label} ({span(s.lo, s.hi)}), where the band plan "
                         f"keeps everyone off")
            v.segment = s.label
            return v
    if segs:
        v.segment = segs[0].label
    if guard == "off":
        return v
    cls = plan.MODE_CLASS.get(mode)
    width = hi - lo if width is None else width
    why = ""
    for s in segs:
        if s.modes is not None and not s.modes:
            why = f"{span(s.lo, s.hi)} is {s.label}: not for transmitting"
            break
        if cls not in s.modes:
            why = f"{plan.CLASS_WORD.get(cls, mode.upper())} is not what the {s.label} segment ({span(s.lo, s.hi)}) is for"
            break
        if s.max_bw is not None and width > s.max_bw + 1e-6:
            why = f"The {s.label} segment ({span(s.lo, s.hi)}) is for signals up to {s.max_bw:.0f} Hz; this one is {width:.0f} Hz"
            break
    if why:
        if guard == "enforce":
            v.refused = f"Band plan: {why}"
        else:
            v.warning = f"Band plan: {why}"
    return v


def max_drive(limit_pep_w: float, full_pep_w: float) -> float:
    """The drive (0..1, amplitude) at which the estimated PEP reaches
    `limit_pep_w`, given `full_pep_w` at full drive (power goes as drive^2)."""
    if full_pep_w <= 0:
        return 1.0
    return max(0.0, min(1.0, math.sqrt(limit_pep_w / full_pep_w)))
