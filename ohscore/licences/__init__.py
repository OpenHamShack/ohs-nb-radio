"""Licence regimes as data: who may transmit where, at what power, by
country. docs/ham/adding-a-country.md is the guide to writing one; this
docstring is the contract it describes.

Why in ohscore: the regime is the law of the station's country, and both
apps need it - OpenHamShack Radio for every transmission (ohsradio/guard.py), OpenHamShack
NB for whether the operator's class may use a 13 cm satellite uplink at
all, and at what power. Band plans stay with HAM (ohsradio/plans/); NB's
QO-100 plan is AMSAT-DL's and international.

A regime is a module (or, for the operator's own licence, an object built
by `custom()`) with these attributes. Frequencies are Hz; powers watts.

Required:
  ID          "ofcom-2024": regulator and edition; a new edition is a new ID
  TITLE       "Ofcom amateur licence (2024 conditions)"
  SHORT       "UK (Ofcom)": the Settings choice
  AUTHORITY   "Ofcom"
  COUNTRY     ISO 3166-1 alpha-2 codes it applies in, ("GB",)
  SOURCE      {"title", "url", "version", "date" (ISO), "checked" (ISO),
              optional "sha256"}: the document the data was transcribed
              from, and when somebody last checked it against the original
  CLASSES     class ids, lowest first ("foundation", "intermediate", "full")
  CLASS_NAME  {class id: "Foundation"} - used as "{name} licence: ..."
  ALLOCATIONS [(lo, hi, {class: limit}, note, source[, extras])] - where
              each class may transmit and at what power; a class absent from
              a row may not transmit there. Rows never overlap.
              A limit is (watts, unit), or a tuple of Limit(watts, unit,
              modes) that all apply - a Limit with `modes` (a set of
              MODE_CLASSES) applies only to those: Canada's Basic 560 W PEP
              for SSB and 190 W carrier for anything else is
              (Limit(560, "PEP", {"ssb", "digi"}), Limit(190, "carrier",
              {"cw", "am", "fm", "dv", "image"})). A mode the guard is not
              told gets every limit, the strictest winning.
              extras, a dict, optional: "valid_from" / "valid_to" (ISO
              dates: NZ's 3400-3410 MHz ends 2027-06-30), "regions" (the
              IARU regions the row applies in: US Region 3 territories have
              narrower 75 m and 40 m), "unconfirmed" (True: the research
              could not confirm the row from the instrument - refused until
              somebody does), "satellite_only" (True: the amateur-satellite
              service only - the Netherlands' 2400-2450 MHz, Italy's
              145.8-146 MHz: OpenHamShack Radio refuses it, QO-100 NB's uplink
              check allows it; the row needs a SATELLITE entry too).
              A row that needs a separate permit (Ireland's and Spain's
              13 cm) is a CONDITIONS entry with default False and when
              False: refused until the operator says they hold it.

Optional (absent = the licence says nothing of the kind):
  PLAN        the national band plan's id (ohsradio/plans), "" for none
  CHANNELLED  [{"lo", "hi", "label", "where", "segments": [(lo, hi)],
              "limits": {class: ((watts, unit), ...)}, "max_bw", "src"}] -
              an allocation usable only inside listed channels (60 m).
              Several limits apply together (UK: 100 W PEP and 200 W EIRP).
  EMISSIONS   [(lo, hi, {class: frozenset of MODE_CLASSES}, max_bw | None,
              note, src)] - per-class mode or bandwidth limits (a US
              Technician's CW-only HF segments). A class absent from a row
              is not restricted by it.
  REFUSED     [(lo, hi, sentence, src)] - refused for every class with that
              whole sentence (UK gaps; bands needing a Notice of Variation).
  CONDITIONS  [{"key", "lo", "hi", "label", "default", "when", "refuse" |
              "limit", "src"}] - a yes/no the operator answers about the
              station (Settings › Licence & plan, stored under `key` in the
              stationConditions setting): where the answer is `when`
              (default True), the band [lo, hi] is refused with the sentence
              `refuse`, or held to `limit` (a Limit). `default` is the
              answer until the operator gives one, and must be the
              restrictive side unless a decision says otherwise: the UK's
              "within 100 km of Charing Cross" defaults to no (Brian,
              05/10/2026); Australia's 3.4-3.6 GHz excluded areas, a US
              70 cm radar area or "I have notified UTC" (2200 m / 630 m)
              default to the answer that refuses.
  SATELLITE   [(lo, hi, "both" | "up" | "down", src)] - where the
              amateur-satellite service is permitted, for the classes that
              hold the allocation, at its power. "up" is Earth to space.
              QO-100's uplink is 2400.050-2400.300 MHz: a regime with no
              SATELLITE row there does not let QO-100 NB transmit to it.
  CEPT        {"T/R 61-01" | "T/R 61-02" | "ECC/REC (05)06": (home class
              ids)} - which of this regime's classes a CEPT licence is.
  CEPT_VISITOR {recommendation: class id} - the class a visitor holding
              that CEPT licence has here.
  NOTES       [(topic, sentence, src)] - beacon, repeater, remote-control,
              unattended or airborne rules: shown, not enforced.
  EDGES       "closed" (default) or "lower-open" (Australia: every band is
              (lower, upper]). The guard requires the whole occupied signal
              to lie inside an allocation, so either reads the same; it is
              recorded so a reader checking the data knows.

Units: PEP; mean and carrier (judged on PEP, which is never lower, so
either is enforced strictly - an FT8 or FM signal's mean is its PEP, an SSB
one's far less, so SSB under a mean limit is held tighter than the law
does); ERP (relative to a half-wave dipole, 2.15 dBi) and
EIRP (relative to isotropic), both computed from PEP at the antenna and the
antenna gain the operator entered for the band. A regime whose document
says "output power" means PEP at the transmitter: write PEP and say so in
the row's note.

`validate(regime)` returns the problems with one (empty when it is sound);
every registered regime must pass it (tests/test_licence_regimes.py).
"""
from __future__ import annotations

import re
from datetime import date as _date
from types import SimpleNamespace
from typing import NamedTuple

from . import ofcom

from ..i18n.text import _

UNITS = ("PEP", "mean", "carrier", "ERP", "EIRP")


class Limit(NamedTuple):
    """A power limit: watts in `unit`, for the mode classes in `modes`
    (None: every mode)."""
    watts: float
    unit: str
    modes: frozenset | None = None


def limits_of(value) -> tuple:
    """A class's limit as written - (watts, unit) or a tuple of Limits - as
    a tuple of Limits."""
    if isinstance(value, Limit):
        return (value,)
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], (int, float)):
        return (Limit(float(value[0]), value[1]),)
    return tuple(v if isinstance(v, Limit) else Limit(*v) for v in value)


def applicable(value, mode_class: str | None) -> tuple:
    """The Limits of `value` that apply to a signal of `mode_class` (None:
    the mode is not known, so all of them)."""
    return tuple(lim for lim in limits_of(value) if mode_class is None or lim.modes is None
                 or mode_class in lim.modes)


def row_extras(row) -> dict:
    return row[5] if len(row) > 5 and isinstance(row[5], dict) else {}


def row_in_force(row, region: int | None = None, today: str | None = None) -> bool:
    """Whether an allocation row applies: in date (ISO strings compare as
    dates) and in the station's IARU region, when the row says either."""
    ex = row_extras(row)
    if today is None:
        today = _date.today().isoformat()
    if ex.get("valid_from") and today < ex["valid_from"]:
        return False
    if ex.get("valid_to") and today > ex["valid_to"]:
        return False
    if ex.get("regions") and region is not None and region not in ex["regions"]:
        return False
    return True
SAT_DIRECTIONS = ("both", "up", "down")
CEPT_RECS = ("T/R 61-01", "T/R 61-02", "ECC/REC (05)06")

# What a regime's EMISSIONS (and a band plan's segments) speak of: every
# mode of both apps maps to one class.
MODE_CLASSES = ("cw", "ssb", "am", "fm", "digi", "dv", "image")
MODE_CLASS = {"usb": "ssb", "lsb": "ssb", "am": "am", "fm": "fm", "cw": "cw", "ft8": "digi", "ft4": "digi",
              "q65": "digi", "js8": "digi", "wspr": "digi", "psk31": "digi", "psk63": "digi", "psk125": "digi",
              "rtty": "digi", "hsmodem": "digi", "freedv": "dv", "sstv": "image"}

# The regimes written so far: the UK's (checked line by line,
# docs/ham/licence-check.md) and the fifteen researched on 08/10/2026
# (docs/ham/countries/), which have not yet had that second check. Imported
# here, after Limit, because several build their rows from it.
from . import acma, arcep, bipt, bnetza, comreg, digst, fcc, ised, mimit, nkom, pts, rdi, rsm, setid, traficom  # noqa: E402

REGIMES = {m.ID: m for m in (ofcom, comreg, bnetza, rdi, bipt, arcep, setid, mimit, nkom, pts, digst, traficom,
                             fcc, ised, acma, rsm)}

# Not regimes but choices of the `licence` setting: follow the station's
# country, or the operator's own entered licence.
AUTO = "auto"
CUSTOM = "custom"
CUSTOM_CLASS = "own"


def get(regime_id: str):
    """The written regime with this id, or None."""
    return REGIMES.get(regime_id)


def all_class_ids() -> list[str]:
    """Every class id of every written regime, in order, without repeats:
    the `licenceClass` setting's choices."""
    out: list[str] = []
    for r in REGIMES.values():
        out += [c for c in r.CLASSES if c not in out]
    return out


def class_name(lic, cls: str) -> str:
    return getattr(lic, "CLASS_NAME", {}).get(cls, cls) if lic is not None else cls


# --------------------------------------------------------------- queries
def class_can_transmit(lic, cls: str, lo: float, hi: float) -> bool:
    """Whether `cls` has any allocation (or channelled one) touching [lo, hi]."""
    if lic is None:
        return False
    if any(cls in row[2] and row[0] < hi and row[1] > lo and row_in_force(row) and not row_extras(row).get("unconfirmed")
           for row in lic.ALLOCATIONS):
        return True
    return any(cls in ch["limits"] and ch["lo"] < hi and ch["hi"] > lo for ch in getattr(lic, "CHANNELLED", []))


def satellite_uplink(lic, cls: str, lo: float, hi: float, conditions: dict | None = None,
                     today: str | None = None) -> tuple[bool | None, tuple | None, str]:
    """May class `cls` transmit to a satellite on [lo, hi]? (allowed, (watts,
    unit) of the tightest row, sentence). allowed is None when the regime
    has no SATELLITE table at all - it says nothing either way.
    `conditions` are the operator's answers to the regime's CONDITIONS
    (condition_answers): one that refuses the range refuses the uplink
    (Ireland's 13 cm permit not held), one that limits it tightens the
    limit (Sweden's 100 mW without a PTS permit); unanswered ones take
    their default."""
    if lic is None:
        return None, None, ""
    sats = getattr(lic, "SATELLITE", None)
    if sats is None:
        return None, None, f"{lic.TITLE} as written here says nothing about the amateur-satellite service"
    name = class_name(lic, cls)
    covered = lo
    for a, b, direction, _src in sorted(s for s in sats if s[0] < hi and s[1] > lo):
        if a > covered + 1e-6 or direction == "down":
            break
        covered = max(covered, b)
    if covered < hi - 1e-6:
        return False, None, f"{lic.TITLE} does not permit an amateur-satellite uplink on {_mhz(lo)}-{_mhz(hi)} MHz"
    rows = [r for r in lic.ALLOCATIONS if r[0] < hi and r[1] > lo and row_in_force(r, today=today)]
    if not rows or any(cls not in r[2] or row_extras(r).get("unconfirmed") for r in rows):
        return False, None, f"{name} licence: {_mhz(lo)}-{_mhz(hi)} MHz is not available to this class"
    lims = [x for r in rows for x in limits_of(r[2][cls])]
    answers = conditions or {}
    for cond in getattr(lic, "CONDITIONS", []):
        if not (cond["lo"] < hi and cond["hi"] > lo):
            continue
        if bool(answers.get(cond["key"], cond.get("default", False))) != cond.get("when", True):
            continue
        if "refuse" in cond:
            return False, None, cond["refuse"]
        lims.append(cond["limit"])
    # Watts compared across units only as a rough order: the uplink check
    # is a yes/no; the figure is shown, not enforced (NB does not know its
    # power at the antenna).
    lim = min(lims, key=lambda x: x.watts)
    return True, (lim.watts, lim.unit), f"{name} licence: satellite uplink allowed, {lim.watts:g} W {lim.unit} at most"


def _mhz(f: float) -> str:
    return f"{f / 1e6:.3f}".rstrip("0").rstrip(".")


def clean_conditions(value: dict) -> dict:
    """The `stationConditions` setting: {condition key: bool}."""
    if not isinstance(value, dict) or len(value) > 50:
        raise ValueError(_("Station conditions must be a short list of yes/no answers"))
    out = {}
    for key, ans in value.items():
        if not (isinstance(key, str) and re.match(r"^[a-z][A-Za-z0-9]{0,40}$", key)):
            raise ValueError(_("{key} is not a station condition").format(key=repr(key)))
        out[key] = bool(ans)
    return out


def condition_answers(lic, st: dict) -> dict:
    """The operator's answer to each of `lic`'s CONDITIONS: from
    stationConditions, else a setting of the same key (the UK's
    nearLondon predates stationConditions), else nothing - the guard then
    takes the condition's default."""
    answers = {}
    stored = st.get("stationConditions") or {}
    for cond in getattr(lic, "CONDITIONS", []):
        key = cond["key"]
        if key in stored:
            answers[key] = bool(stored[key])
        elif key in st:
            answers[key] = bool(st[key])
    return answers


# --------------------------------------------------------------- the operator's own licence
def clean_custom(value: list) -> list:
    """The `customLicence` setting: the operator's own allowed segments.
    Each {"lo": Hz, "hi": Hz, "watts": W, "unit": one of UNITS,
    "satellite": bool, "note": str}. Raises ValueError with a sentence
    (the registry's validate hook)."""
    if not isinstance(value, list):
        raise ValueError(_("Your licence's segments must be a list"))
    if len(value) > 100:
        raise ValueError(_("Your licence can have at most 100 segments"))
    out = []
    for i, seg in enumerate(value, 1):
        if not isinstance(seg, dict):
            raise ValueError(_("Segment {i} of your licence is not a segment").format(i=i))
        try:
            lo, hi, w = float(seg["lo"]), float(seg["hi"]), float(seg["watts"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(_("Segment {i} of your licence needs a lower edge, an upper edge and a power").format(
                i=i)) from None
        unit = seg.get("unit", "PEP")
        if unit not in UNITS:
            raise ValueError(_("Segment {i}: the power must be one of {units}, not {unit}").format(
                i=i, units=", ".join(UNITS), unit=repr(unit)))
        if not (0 < lo < hi <= 300e9):
            raise ValueError(_("Segment {i}: the lower edge must be below the upper edge").format(i=i))
        if not 0 < w <= 10_000:
            raise ValueError(_("Segment {i}: the power must be above 0 W and at most 10 kW").format(i=i))
        note = str(seg.get("note", ""))[:120].replace("\n", " ")
        out.append({"lo": lo, "hi": hi, "watts": w, "unit": unit, "satellite": bool(seg.get("satellite", False)),
                    "note": note})
    out.sort(key=lambda s: s["lo"])
    for a, b in zip(out, out[1:]):
        if b["lo"] < a["hi"] - 1e-6:
            raise ValueError(_("Your licence's segments overlap: {a_lo}-{a_hi} MHz and {b_lo}-{b_hi} MHz. "
                               "Give each frequency one power limit.").format(
                a_lo=_mhz(a["lo"]), a_hi=_mhz(a["hi"]), b_lo=_mhz(b["lo"]), b_hi=_mhz(b["hi"])))
    return out


def custom(segments: list, country: str = "") -> SimpleNamespace:
    """A regime from the operator's own segments, with one class, CUSTOM_CLASS
    ("Your licence: ..."). The operator's statement, not a document: its
    SOURCE says so."""
    where = f" in {country}" if country else ""
    return SimpleNamespace(
        ID=CUSTOM, TITLE=f"your own licence{where} (entered in Settings)", SHORT="Your own licence",
        AUTHORITY="", COUNTRY=(), PLAN="",
        SOURCE={"title": "Entered by the operator in Settings", "url": "", "version": "", "date": "", "checked": ""},
        CLASSES=(CUSTOM_CLASS,), CLASS_NAME={CUSTOM_CLASS: "Your"},
        ALLOCATIONS=[(s["lo"], s["hi"], {CUSTOM_CLASS: (s["watts"], s["unit"])}, s.get("note", ""),
                      "entered by the operator") for s in segments],
        SATELLITE=[(s["lo"], s["hi"], "both", "entered by the operator") for s in segments if s.get("satellite")],
    )


# --------------------------------------------------------------- validation
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _overlaps(spans):
    spans = sorted(spans)
    return [(a, b) for a, b in zip(spans, spans[1:]) if b[0] < a[1] - 1e-6]


def validate(lic, custom_regime: bool = False) -> list[str]:
    """Every problem with a regime, as sentences; [] when it is sound.
    What it checks is what the guard relies on: identity and a dated
    source; classes named; rows well formed, in declared units and never
    overlapping (an overlap is two answers for one frequency); every
    optional table inside the allocations it qualifies, or - for REFUSED -
    outside them all."""
    p: list[str] = []
    rid = getattr(lic, "ID", "?")

    def need(attr):
        if not getattr(lic, attr, None):
            p.append(f"{rid}: {attr} is missing")
    for attr in ("ID", "TITLE", "SHORT", "CLASSES", "CLASS_NAME", "ALLOCATIONS", "SOURCE"):
        need(attr)
    if not custom_regime:
        need("AUTHORITY")
        need("COUNTRY")
        src = getattr(lic, "SOURCE", {}) or {}
        for k in ("title", "url", "version", "date", "checked"):
            if not src.get(k):
                p.append(f"{rid}: SOURCE has no {k}")
        for k in ("date", "checked"):
            if src.get(k) and not _ISO_DATE.match(src[k]):
                p.append(f"{rid}: SOURCE {k} must be an ISO date (YYYY-MM-DD), not {src[k]!r}")
        for c in getattr(lic, "COUNTRY", ()):
            if not re.match(r"^[A-Z]{2}$", c):
                p.append(f"{rid}: COUNTRY {c!r} is not an ISO 3166-1 alpha-2 code")
    classes = tuple(getattr(lic, "CLASSES", ()))
    for c in classes:
        if c not in getattr(lic, "CLASS_NAME", {}):
            p.append(f"{rid}: class {c!r} has no CLASS_NAME")

    def limit_ok(where, cls, value):
        if cls not in classes:
            p.append(f"{where}: class {cls!r} is not one of CLASSES")
        try:
            lims = limits_of(value)
        except TypeError:
            lims = ()
        if not lims or not isinstance(value, tuple):
            p.append(f"{where}: a limit is (watts, unit) or a tuple of Limit, not {value!r}")
            return
        for lim in lims:
            if not (isinstance(lim.watts, (int, float)) and lim.watts > 0):
                p.append(f"{where}: power {lim.watts!r} must be above 0 W")
            if lim.unit not in UNITS:
                p.append(f"{where}: unit {lim.unit!r} is not one of {', '.join(UNITS)}")
            if lim.modes is not None and not set(lim.modes) <= set(MODE_CLASSES):
                p.append(f"{where}: limit modes {sorted(set(lim.modes) - set(MODE_CLASSES))} are not mode classes")
        if any(lim.modes is not None for lim in lims):
            covered = set().union(*(lim.modes or MODE_CLASSES for lim in lims))
            if covered != set(MODE_CLASSES):
                p.append(f"{where}: class {cls!r}'s limits leave {sorted(set(MODE_CLASSES) - covered)} with "
                         f"no limit: give every mode class one")

    spans, when = [], []
    for row in getattr(lic, "ALLOCATIONS", []):
        if len(row) not in (5, 6) or (len(row) == 6 and not isinstance(row[5], dict)):
            p.append(f"{rid}: an allocation row is (lo, hi, limits, note, source[, extras]), not {row!r}")
            continue
        lo, hi, limits, _note, src = row[:5]
        for key, val in row_extras(row).items():
            if key not in ("valid_from", "valid_to", "regions", "unconfirmed", "satellite_only"):
                p.append(f"{rid} {lo:.0f}-{hi:.0f} Hz: unknown extra {key!r}")
            elif key.startswith("valid_") and not _ISO_DATE.match(str(val)):
                p.append(f"{rid} {lo:.0f}-{hi:.0f} Hz: {key} must be an ISO date, not {val!r}")
            elif key == "regions" and not set(val) <= {1, 2, 3}:
                p.append(f"{rid} {lo:.0f}-{hi:.0f} Hz: regions must be among 1, 2, 3")
        where = f"{rid} {lo:.0f}-{hi:.0f} Hz"
        if not lo < hi:
            p.append(f"{where}: lower edge not below upper")
        if not src:
            p.append(f"{where}: no source")
        if not limits:
            p.append(f"{where}: no class may use it (leave it out, or put it in REFUSED)")
        for cls, lim in limits.items():
            limit_ok(where, cls, lim)
        spans.append((lo, hi))
        ex = row_extras(row)
        when.append((lo, hi, set(ex.get("regions") or (1, 2, 3)), ex.get("valid_from", ""),
                     ex.get("valid_to", "9999-12-31")))
    for ch in getattr(lic, "CHANNELLED", []):
        where = f"{rid} {ch.get('label', '?')}"
        if not ch.get("src"):
            p.append(f"{where}: no source")
        segs = list(ch.get("segments", []))
        if not segs:
            p.append(f"{where}: no segments")
        for a, b in segs:
            if not (ch["lo"] <= a < b <= ch["hi"]):
                p.append(f"{where}: segment {a:.0f}-{b:.0f} Hz is not inside {ch['lo']:.0f}-{ch['hi']:.0f} Hz")
        if _overlaps(segs):
            p.append(f"{where}: segments overlap")
        for cls, lims in ch.get("limits", {}).items():
            for lim in lims:
                limit_ok(where, cls, lim)
        if ch.get("max_bw") is not None and not ch["max_bw"] > 0:
            p.append(f"{where}: max_bw must be above 0 Hz")
        spans.append((ch["lo"], ch["hi"]))
        when.append((ch["lo"], ch["hi"], {1, 2, 3}, "", "9999-12-31"))
    # Rows that never apply together - different IARU regions, or dates
    # that do not meet - may share frequencies; rows that apply at once
    # may not: that would be two answers for one frequency.
    when.sort()
    for i, a in enumerate(when):
        for b in when[i + 1:]:
            if b[0] >= a[1] - 1e-6:
                break
            if a[2] & b[2] and a[3] <= b[4] and b[3] <= a[4]:
                p.append(f"{rid}: {a[0]:.0f}-{a[1]:.0f} Hz and {b[0]:.0f}-{b[1]:.0f} Hz overlap: one frequency, "
                         f"two answers")

    def inside(lo, hi):
        covered = lo
        for a, b in sorted(spans):
            if a <= covered + 1e-6 and b > covered:
                covered = b
        return covered >= hi - 1e-6

    for row in getattr(lic, "REFUSED", []):
        lo, hi, sentence, src = row
        if any(lo < b and hi > a for a, b in spans):
            p.append(f"{rid}: REFUSED {lo:.0f}-{hi:.0f} Hz overlaps an allocation: refused and allowed at once")
        if not sentence or not src:
            p.append(f"{rid}: REFUSED {lo:.0f}-{hi:.0f} Hz needs its sentence and a source")
    for cond in getattr(lic, "CONDITIONS", []):
        for k in ("key", "lo", "hi", "label", "default", "src"):
            if k not in cond:
                p.append(f"{rid}: a CONDITIONS entry has no {k}")
        if ("refuse" in cond) == ("limit" in cond):
            p.append(f"{rid}: CONDITIONS {cond.get('key')!r} needs exactly one of refuse and limit")
        if "limit" in cond and not isinstance(cond["limit"], Limit):
            p.append(f"{rid}: CONDITIONS {cond.get('key')!r}: limit must be a Limit")
        if not re.match(r"^[a-z][A-Za-z0-9]*$", str(cond.get("key", ""))):
            p.append(f"{rid}: CONDITIONS key {cond.get('key')!r} must be a camelCase word")
    sat_spans = [(a, b) for a, b, d, _s in getattr(lic, "SATELLITE", []) or [] if d in ("both", "up")]
    for row in getattr(lic, "ALLOCATIONS", []):
        if row_extras(row).get("satellite_only"):
            covered = row[0]
            for a, b in sorted(sat_spans):
                if a <= covered + 1e-6 and b > covered:
                    covered = b
            if covered < row[1] - 1e-6:
                p.append(f"{rid}: {row[0]:.0f}-{row[1]:.0f} Hz is satellite_only but no SATELLITE entry covers it")
    for lo, hi, direction, src in getattr(lic, "SATELLITE", []) or []:
        if direction not in SAT_DIRECTIONS:
            p.append(f"{rid}: SATELLITE direction {direction!r} is not one of {', '.join(SAT_DIRECTIONS)}")
        if not inside(lo, hi):
            p.append(f"{rid}: SATELLITE {lo:.0f}-{hi:.0f} Hz is outside the allocations")
        if not src:
            p.append(f"{rid}: SATELLITE {lo:.0f}-{hi:.0f} Hz has no source")
    for lo, hi, per_class, max_bw, _note, src in getattr(lic, "EMISSIONS", []):
        if not inside(lo, hi):
            p.append(f"{rid}: EMISSIONS {lo:.0f}-{hi:.0f} Hz is outside the allocations")
        for cls, modes in per_class.items():
            if cls not in classes:
                p.append(f"{rid}: EMISSIONS class {cls!r} is not one of CLASSES")
            bad = set(modes) - set(MODE_CLASSES)
            if bad:
                p.append(f"{rid}: EMISSIONS modes {sorted(bad)} are not mode classes ({', '.join(MODE_CLASSES)})")
        if max_bw is not None and not max_bw > 0:
            p.append(f"{rid}: EMISSIONS max_bw must be above 0 Hz")
        if not src:
            p.append(f"{rid}: EMISSIONS {lo:.0f}-{hi:.0f} Hz has no source")
    for rec, home in getattr(lic, "CEPT", {}).items():
        if rec not in CEPT_RECS:
            p.append(f"{rid}: CEPT recommendation {rec!r} is not one of {', '.join(CEPT_RECS)}")
        for cls in home:
            if cls not in classes:
                p.append(f"{rid}: CEPT class {cls!r} is not one of CLASSES")
    if getattr(lic, "CEPT", None) and not getattr(lic, "CEPT_SRC", ""):
        p.append(f"{rid}: CEPT has no CEPT_SRC")
    for rec, cls in getattr(lic, "CEPT_VISITOR", {}).items():
        if rec not in CEPT_RECS or cls not in classes:
            p.append(f"{rid}: CEPT_VISITOR {rec!r} -> {cls!r} names an unknown recommendation or class")
    return p


def cept_suggestion(home_lic, home_cls: str, visited_lic) -> str:
    """A sentence about operating under CEPT in a visited country, from
    the two regimes' data; "" when neither says anything."""
    if home_lic is None:
        return ""
    recs = [rec for rec, classes in getattr(home_lic, "CEPT", {}).items() if home_cls in classes]
    if not recs:
        if getattr(home_lic, "CEPT", None):
            return (f"Your {class_name(home_lic, home_cls)} licence is not a CEPT licence ({home_lic.SHORT}): "
                    f"operating abroad needs a licence from the country you are in")
        return ""
    rec = recs[0]
    there = getattr(visited_lic, "CEPT_VISITOR", {}).get(rec) if visited_lic is not None else None
    if there:
        return (f"Under CEPT {rec} your licence gives the {class_name(visited_lic, there)} class here "
                f"({visited_lic.SHORT})")
    return f"Your licence is a CEPT licence ({rec}): the rules of the country you are in apply - choose its class"
