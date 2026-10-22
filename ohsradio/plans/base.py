"""What every band plan module is (docs/ham/adding-a-country.md, "The band
plan"). A plan is a code of practice, not law: the guard warns outside
it, unless the operator chooses "enforce", and always refuses its beacon
and satellite segments (ohsradio/guard.py plan_check).

A plan module has:

  ID          "rsgb-2026", "iaru-r1-2020"...: issuer and edition
  TITLE       "RSGB band plan 2026"
  SHORT       the Settings choice, "RSGB 2026"
  SOURCE      {"title", "url", "version", "date", "checked"} as for a licence
  REGION      the IARU region it belongs to (1, 2 or 3)
  COUNTRY     ISO codes of the country it is national for; () for a
              regional (IARU) plan
  SEGMENTS    sorted, non-overlapping Seg rows (below); between two rows the
              plan is silent and only the licence applies
  CENTRES     [(Hz, label, mode)]: centres of activity, the memories' presets
  IBP         [Hz]: the NCDXF/IARU beacon frequencies the scope marks
  MODE_CLASS, CLASS_WORD   from here (one vocabulary for every plan)
  segment_at(f), overlapping(lo, hi)   from make_lookup() below

Seg.modes is the set of mode classes the segment is for; an empty set
means "not for transmitting" (a repeater's own output); None means
reserved - kind "beacon", "satellite" or "protected" - and refused for
everyone. "protected" is a band the plan says no amateur may use at all
(radio astronomy, IARU R2/R3 3332-3339 and 3345.8-3352.5 MHz): it was
added on 08/10/2026 so those need not pose as satellite segments.
max_bw is the plan's bandwidth for the segment, Hz, or None.

`validate(plan)` lists what is wrong with one; tests/test_ham_plans.py
runs it on every registered plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ohscore.licences import MODE_CLASS as _ALL_MODES, MODE_CLASSES

# OpenHamShack Radio's modes, as the plans speak of them (ohscore/licences has the
# same vocabulary for licence emission limits).
MODE_CLASS = {m: c for m, c in _ALL_MODES.items() if m in (
    "usb", "lsb", "am", "fm", "cw", "ft8", "ft4", "wspr", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv")}
CLASS_WORD = {"ssb": "SSB", "am": "AM", "fm": "FM", "cw": "CW", "digi": "digital modes", "dv": "digital voice",
              "image": "SSTV"}

ALL = frozenset(MODE_CLASSES)
HF_ALL = ALL - {"fm"}             # FM on HF belongs above 29 MHz (10 m FM simplex and repeaters)
CW = frozenset({"cw"})
NARROW = frozenset({"cw", "digi"})
WEAK = frozenset({"cw", "ssb", "digi"})        # VHF/UHF narrow band: CW, SSB, MGM
FM = frozenset({"fm", "dv"})
NONE: frozenset = frozenset()
KINDS = ("", "beacon", "satellite", "protected", "output")
RESERVED = ("beacon", "satellite", "protected")


@dataclass(frozen=True)
class Seg:
    lo: float
    hi: float
    label: str
    modes: frozenset | None      # None: reserved (beacon / satellite / protected), always refused
    max_bw: float | None = None
    kind: str = ""               # "beacon", "satellite", "output" (a repeater's output: not for transmitting)

    @property
    def refused(self) -> bool:
        return self.kind in RESERVED


def k(*segs):
    """Rows in kHz: (lo, hi, label, modes, max_bw, kind)."""
    return [Seg(lo * 1e3, hi * 1e3, label, modes, bw, kind) for lo, hi, label, modes, bw, kind in segs]


def m(*segs):
    """Rows in MHz."""
    return [Seg(lo * 1e6, hi * 1e6, label, modes, bw, kind) for lo, hi, label, modes, bw, kind in segs]


def make_lookup(segments: list[Seg]):
    """segment_at(f) and overlapping(lo, hi) over a sorted segment list."""
    def segment_at(f: float) -> Seg | None:
        for s in segments:
            if s.lo <= f < s.hi:
                return s
        return None

    def overlapping(lo: float, hi: float) -> list[Seg]:
        """Segments [lo, hi] reaches into (a zero-width signal counts where it is)."""
        eps = 1e-6
        return [s for s in segments
                if (lo < s.hi - eps and hi > s.lo + eps) or (lo == hi and s.lo <= lo < s.hi)]
    return segment_at, overlapping


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate(plan) -> list[str]:
    p: list[str] = []
    pid = getattr(plan, "ID", "?")
    for attr in ("ID", "TITLE", "SHORT", "SOURCE", "SEGMENTS", "REGION"):
        if not getattr(plan, attr, None):
            p.append(f"{pid}: {attr} is missing")
    src = getattr(plan, "SOURCE", {}) or {}
    for key in ("title", "url", "version", "date", "checked"):
        if not src.get(key):
            p.append(f"{pid}: SOURCE has no {key}")
    for key in ("date", "checked"):
        if src.get(key) and not _ISO_DATE.match(src[key]):
            p.append(f"{pid}: SOURCE {key} must be an ISO date, not {src[key]!r}")
    if getattr(plan, "REGION", None) not in (1, 2, 3):
        p.append(f"{pid}: REGION must be 1, 2 or 3")
    segs = list(getattr(plan, "SEGMENTS", []))
    if segs != sorted(segs, key=lambda s: s.lo):
        p.append(f"{pid}: SEGMENTS are not sorted")
    for s in segs:
        if not s.lo < s.hi:
            p.append(f"{pid}: {s.label} {s.lo:.0f}-{s.hi:.0f} Hz: lower edge not below upper")
        if s.kind not in KINDS:
            p.append(f"{pid}: {s.label}: kind {s.kind!r} is not one of {KINDS}")
        if s.kind in RESERVED and s.modes is not None:
            p.append(f"{pid}: {s.label}: a {s.kind} segment is reserved (modes None)")
        if s.modes is None and s.kind not in RESERVED:
            p.append(f"{pid}: {s.label}: modes None is only for {', '.join(RESERVED)} segments")
        if s.modes and not set(s.modes) <= set(MODE_CLASSES):
            p.append(f"{pid}: {s.label}: unknown mode classes {sorted(set(s.modes) - set(MODE_CLASSES))}")
        if s.max_bw is not None and not s.max_bw > 0:
            p.append(f"{pid}: {s.label}: max_bw must be above 0 Hz")
    for a, b in zip(segs, segs[1:]):
        if b.lo < a.hi - 1e-6:
            p.append(f"{pid}: {a.label} ({a.lo:.0f}-{a.hi:.0f}) and {b.label} ({b.lo:.0f}-{b.hi:.0f}) overlap")
    for f, label, mode in getattr(plan, "CENTRES", []):
        if mode not in MODE_CLASS:
            p.append(f"{pid}: centre {label} at {f:.0f} Hz: mode {mode!r} is not an OpenHamShack Radio mode")
    return p
