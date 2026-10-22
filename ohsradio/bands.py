"""The bands OpenHamShack Radio knows, their band stack registers and their
repeater conventions (docs/ham/DESIGN-HAM.md section 5.2).

A **band** here is a stretch of spectrum the operator thinks of by name
("20 m", "70 cm"): it gives the band bar its buttons, the band stack its
registers and the readout its digit grouping. What may be transmitted
where is not decided here: that is the licence (ohsradio/licences/ofcom.py,
law) and the band plan (ohsradio/plans/rsgb_2026.py, a code of practice),
both judged by ohsradio/guard.py. The edges below are the widest UK amateur
allocation in the band (bandplan-r1-uk.md section 1), so a band's button
lands somewhere the licence has.

Numbers are Hz. Dial frequencies and repeater pairs are from
docs/ham/bandplan-r1-uk.md (RSGB 2026 [R1], WSJT-X [W1]); JS8 dials are
JS8Call 2.2.0's own defaults [J1] (FrequencyList.cpp, "Modes::JS8").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ohscore.licences import MODE_CLASS


@dataclass(frozen=True)
class Band:
    name: str                  # "20m"
    label: str                 # what the band bar prints: "20", "70cm"
    lo: float
    hi: float
    stack: tuple               # the three registers a first visit seeds: (dial, mode)
    ft8: float | None = None   # FT8 / FT4 / WSPR dials (USB), WSJT-X's defaults [W1]
    ft4: float | None = None
    wspr: float | None = None
    js8: float | None = None   # JS8 dial (USB), JS8Call's default [J1]
    deferred: str = ""         # why the band is shown but has no radio here yet
    rpt_offset: float | None = None   # the UK repeater split here, Hz: what - and + start from
    experimental: str = ""     # a sentence: works, but at the edge of what the hardware is specified for

    @property
    def hf(self) -> bool:
        return self.hi < 30e6

    @property
    def centre(self) -> float:
        return (self.lo + self.hi) / 2


def _b(name, label, lo, hi, stack, **kw):
    return Band(name, label, float(lo), float(hi), tuple((float(f), m) for f, m in stack), **kw)


# In band-bar order. The first register is what a first visit lands on.
# rpt_offset is each band's usual UK repeater split, the size of the shift
# - and + start from on arriving in the band (the operator can change it):
# RH -100 kHz, 6 m +500 kHz, RV -600 kHz, RB +1.6 MHz, RM -6 MHz, from
# RSGB 2026 [R1] as tabled in bandplan-r1-uk.md sections 2 and 3. 70 cm's
# other schemes (RU 7.6, DV 9, RBW 5 MHz) are the exceptions an operator
# types in. A band with no repeaters has none and leaves the offset alone.
BANDS: list[Band] = [
    _b("160m", "160", 1_810_000, 2_000_000, [(1_840_000, "ft8"), (1_850_000, "lsb"), (1_825_000, "cw")],
       ft8=1_840_000, js8=1_842_000, wspr=1_836_600),
    _b("80m", "80", 3_500_000, 3_800_000, [(3_573_000, "ft8"), (3_700_000, "lsb"), (3_530_000, "cw")],
       ft8=3_573_000, js8=3_578_000, ft4=3_575_000, wspr=3_568_600),
    # 60 m: eleven UK segments inside these edges, Full licence only (the guard
    # says so); USB by UK practice.
    _b("60m", "60", 5_258_500, 5_406_500, [(5_357_000, "ft8"), (5_371_500, "usb"), (5_262_000, "cw")],
       ft8=5_357_000, ft4=5_357_000),
    _b("40m", "40", 7_000_000, 7_200_000, [(7_074_000, "ft8"), (7_150_000, "lsb"), (7_030_000, "cw")],
       ft8=7_074_000, js8=7_078_000, ft4=7_047_500, wspr=7_038_600),
    _b("30m", "30", 10_100_000, 10_150_000, [(10_136_000, "ft8"), (10_116_000, "cw"), (10_140_000, "ft4")],
       ft8=10_136_000, js8=10_130_000, ft4=10_140_000, wspr=10_138_700),
    _b("20m", "20", 14_000_000, 14_350_000, [(14_074_000, "ft8"), (14_200_000, "usb"), (14_025_000, "cw")],
       ft8=14_074_000, js8=14_078_000, ft4=14_080_000, wspr=14_095_600),
    _b("17m", "17", 18_068_000, 18_168_000, [(18_100_000, "ft8"), (18_130_000, "usb"), (18_086_000, "cw")],
       ft8=18_100_000, js8=18_104_000, ft4=18_104_000, wspr=18_104_600),
    _b("15m", "15", 21_000_000, 21_450_000, [(21_074_000, "ft8"), (21_250_000, "usb"), (21_030_000, "cw")],
       ft8=21_074_000, js8=21_078_000, ft4=21_140_000, wspr=21_094_600),
    _b("12m", "12", 24_890_000, 24_990_000, [(24_915_000, "ft8"), (24_950_000, "usb"), (24_906_000, "cw")],
       ft8=24_915_000, js8=24_922_000, ft4=24_919_000, wspr=24_924_600),
    _b("10m", "10", 28_000_000, 29_700_000, [(28_074_000, "ft8"), (28_500_000, "usb"), (29_600_000, "fm")],
       ft8=28_074_000, js8=28_078_000, ft4=28_180_000, wspr=28_124_600, rpt_offset=100_000),
    _b("6m", "6", 50_000_000, 52_000_000, [(50_313_000, "ft8"), (50_150_000, "usb"), (51_510_000, "fm")],
       ft8=50_313_000, js8=50_318_000, ft4=50_318_000, rpt_offset=500_000,
       deferred="6 m has no radio here yet: the Hermes-Lite 2 stops at 38.4 MHz and the Pluto cannot receive "
                "below 70 MHz. A 6 m transverter on the HL2 is the planned route."),
    _b("4m", "4", 70_000_000, 70_500_000, [(70_154_000, "ft8"), (70_200_000, "usb"), (70_450_000, "fm")],
       ft8=70_154_000, wspr=70_091_000,
       experimental="4 m sits on the Pluto's 70 MHz receive floor; performance there is unmeasured."),
    _b("2m", "2", 144_000_000, 146_000_000, [(145_500_000, "fm"), (144_300_000, "usb"), (144_174_000, "ft8")],
       ft8=144_174_000, js8=144_178_000, ft4=144_170_000, wspr=144_489_000, rpt_offset=600_000),
    _b("70cm", "70cm", 430_000_000, 440_000_000, [(433_500_000, "fm"), (432_200_000, "usb"), (432_174_000, "ft8")],
       ft8=432_174_000, wspr=432_300_000, rpt_offset=1_600_000),
    _b("23cm", "23cm", 1_240_000_000, 1_325_000_000,
       [(1_297_500_000, "fm"), (1_296_200_000, "usb"), (1_296_174_000, "ft8")],
       ft8=1_296_174_000, wspr=1_296_500_000, rpt_offset=6_000_000),
    _b("13cm", "13cm", 2_310_000_000, 2_450_000_000,
       [(2_320_200_000, "usb"), (2_320_050_000, "cw"), (2_321_000_000, "fm")]),
    _b("9cm", "9cm", 3_400_000_000, 3_410_000_000, [(3_400_100_000, "usb"), (3_400_050_000, "cw"),
                                                    (3_400_200_000, "usb")]),
    _b("6cm", "6cm", 5_650_000_000, 5_850_000_000, [(5_760_100_000, "usb"), (5_760_050_000, "cw"),
                                                    (5_760_200_000, "usb")]),
]
BY_NAME = {b.name: b for b in BANDS}
NAMES = [b.name for b in BANDS]


def band_at(f: float) -> Band | None:
    for b in BANDS:
        if b.lo <= f <= b.hi:
            return b
    return None


def natural_sideband(f: float) -> str:
    """LSB below 10 MHz, USB above: the convention a band change follows
    when the stack register does not say otherwise (design 5.2)."""
    return "lsb" if f < 10e6 else "usb"


# ------------------------------------------------------------------ repeaters
@dataclass(frozen=True)
class RepeaterScheme:
    name: str            # "RV" (2 m), "RB" (70 cm) ...
    out_lo: float        # output channel range (what the operator dials)
    out_hi: float
    shift: float         # input = output + shift
    step: float          # channel spacing; 0: the plan gives none, so any frequency in the range is one
    first: int           # channel number of out_lo (channel names only where `name` is set)
    note: str = ""


# UK pairs, RSGB 2026 [R1] as tabled in bandplan-r1-uk.md section 3 (and the
# 10 m RH channels, section 2). The UK's 70 cm pairs run the opposite way to
# IARU R1's, so the direction is per scheme, never inherited.
REPEATERS: list[RepeaterScheme] = [
    RepeaterScheme("RH", 29_620_000, 29_690_000, -100_000, 10_000, 1),
    RepeaterScheme("RV", 145_600_000, 145_787_500, -600_000, 12_500, 48),
    RepeaterScheme("RB", 433_000_000, 433_375_000, +1_600_000, 25_000, 0,
                   "RBW repeaters share these outputs with inputs 5 MHz up (438.000-438.375): set the shift by hand"),
    RepeaterScheme("RU", 430_812_500, 430_975_000, +7_600_000, 12_500, 65),
    RepeaterScheme("DV", 439_400_000, 439_775_000, -9_000_000, 12_500, 0, "9 MHz DV pairs"),
    RepeaterScheme("RM", 1_297_000_000, 1_297_375_000, -6_000_000, 25_000, 0),
]

# Simplex channel names: (name, first frequency, step, first number, last frequency).
SIMPLEX = [("V", 145_200_000, 12_500, 16, 145_562_500), ("U", 433_400_000, 12_500, 272, 433_575_000),
           ("SM", 1_297_500_000, 25_000, 20, 1_297_750_000)]


def repeater_at(f: float, schemes: list[RepeaterScheme] | None = None) -> RepeaterScheme | None:
    """The scheme whose output channel `f` is on (within 1 kHz), or None.
    `schemes` are the plan in force's (ohsradio/plans/repeaters.py); the UK's
    when not given."""
    for r in REPEATERS if schemes is None else schemes:
        if r.out_lo - 1_000 <= f <= r.out_hi + 1_000:
            if not r.step:
                return r
            k = round((f - r.out_lo) / r.step)
            if abs(r.out_lo + k * r.step - f) <= 1_000:
                return r
    return None


def channel_name(f: float, schemes: list[RepeaterScheme] | None = None, simplex: list | None = None) -> str:
    """Channel name for an FM frequency ("RV55", "V40", "RB4"), or '': the
    UK's unless the plan in force's schemes and simplex names are given."""
    r = repeater_at(f, schemes)
    if r is not None:
        return f"{r.name}{r.first + round((f - r.out_lo) / r.step)}" if r.name and r.step else ""
    for name, lo, step, first, hi in SIMPLEX if simplex is None else simplex:
        if lo - 1_000 <= f <= hi + 1_000:
            k = round((f - lo) / step)
            if abs(lo + k * step - f) <= 1_000:
                return f"{name}{first + k}"
    return ""


def auto_shift(f: float, schemes: list[RepeaterScheme] | None = None) -> float:
    """The shift 'auto' means at `f`: the scheme's, or 0 (simplex)."""
    r = repeater_at(f, schemes)
    return r.shift if r is not None else 0.0


# ------------------------------------------------------------------ band stacks
# What a register keeps besides its dial and mode.
STACK_KEYS = ("filterLo", "filterHi", "agc", "rptShift", "rptOffsetHz", "ctcssTx")

# How far above the start of an SSB segment an LSB dial goes, so the whole
# voice (300-2700 Hz below the dial) is inside the segment, not hanging
# over its lower edge into the digital one below.
LSB_CLEARANCE = 3_000.0


def sideband(b: Band) -> str:
    """The sideband `b` is worked on: what its own registers use, which is
    LSB below 10 MHz and USB above except where national practice says
    otherwise (UK 60 m is USB), else the convention."""
    return next((m for _f, m in b.stack if m in ("usb", "lsb")), natural_sideband(b.lo))


def ssb_start(b: Band, plan) -> float | None:
    """The dial at the start of the band plan's SSB segment in `b`, or None
    where the plan has no SSB in the band (30 m).

    "The SSB segment" is the widest segment in the band that allows SSB at
    a voice's width: not the first. On 20 m the first is the 11 kHz
    all-modes slot at 14.101, which is the digital modes' and the
    beacons' neighbourhood; the widest is 14.125-14.350, where SSB is.
    Reserved segments (beacons, satellites) never count. Widest-first
    ties go to the lower segment."""
    segs = [s for s in plan.overlapping(b.lo, b.hi)
            if s.modes and "ssb" in s.modes and not s.refused and (s.max_bw is None or s.max_bw >= 2_700)]
    if not segs:
        return None
    s = max(segs, key=lambda s: min(s.hi, b.hi) - max(s.lo, b.lo))
    lo = max(s.lo, b.lo)
    return lo + LSB_CLEARANCE if sideband(b) == "lsb" else lo


# The IARU R1 FM calling channels (RSGB band plan 2026: 145.500 MHz on 2 m,
# 433.500 MHz on 70 cm). RSGB 2026 marks them in its CENTRES; the regional
# R1 plan carries no CENTRES, so a station planned by it needs these.
FM_CALLING_R1 = {"2m": 145_500_000, "70cm": 433_500_000}


def fm_calling(b: Band, plan) -> float | None:
    """The FM calling channel of `b` in `plan`, or None where there is not
    one to offer. Read from the plan's own centres of activity when it
    marks an "FM calling" in the band; otherwise the R1 constants, and only
    for a Region 1 plan: R2/R3 call elsewhere, and a wrong channel would
    be worse than the SSB landing."""
    if b.name not in FM_CALLING_R1:
        return None                      # 10 m's FM calling is not part of this rule
    for f, label, m in getattr(plan, "CENTRES", []):
        if m == "fm" and label == "FM calling" and b.lo <= f <= b.hi:
            return float(f)
    if getattr(plan, "REGION", None) == 1:
        return FM_CALLING_R1[b.name]
    return None


def first_register(b: Band, mode: str, plan) -> tuple[float, str]:
    """Where a first visit to `b` lands, given the mode the operator is in
    when they press the band (Brian, 13/10/2026): in a digital mode, the
    band's FT8 dial (FT4's from FT4, where the band has one); otherwise the
    start of the plan's SSB segment in the band's sideband. A band with
    neither falls back to its first listed register.

    On 2 m and 70 cm, from FM, the radio stays in FM and goes to the FM
    calling channel (Brian, 13/10/2026): an FM operator pressing 2 m wants
    to listen and call, and an SSB landing would switch their mode away."""
    if mode == "fm" and plan is not None:
        f = fm_calling(b, plan)
        if f is not None:
            return f, "fm"
    if MODE_CLASS.get(mode) == "digi":
        if mode == "ft4" and b.ft4:
            return b.ft4, "ft4"
        if b.ft8:
            return b.ft8, "ft8"
    f = ssb_start(b, plan) if plan is not None else None
    if f is not None:
        return f, sideband(b)
    return b.stack[0]


def seed_stack(b: Band, mode: str | None = None, plan=None) -> list[dict]:
    """The three registers a first visit to `b` starts from. With the mode
    the operator is in and the plan in force, the first is
    first_register()'s and the other two are the band's listed registers
    for other modes, so a second press still offers FT8, SSB and CW; with
    neither, the band's listed registers as they stand."""
    if mode is None:
        return [{"vfo": f, "mode": m} for f, m in b.stack]
    first = first_register(b, mode, plan)
    rest = [r for r in b.stack if r[1] != first[1]]
    rest += [r for r in b.stack if r[1] == first[1] and r[0] != first[0]]
    return [{"vfo": f, "mode": m} for f, m in [first, *rest][:3]]


def clean_stacks(value: dict) -> dict:
    """Validate a persisted bandStacks value: {band: {"i": n, "regs": [{vfo, mode}, ...]}}.
    A register that does not read is dropped (the band re-seeds), never the
    whole setting."""
    out = {}
    for name, entry in value.items():
        b = BY_NAME.get(name)
        if b is None or not isinstance(entry, dict):
            continue
        regs = []
        for r in entry.get("regs", [])[:3]:
            try:
                f = float(r["vfo"])
                m = str(r["mode"])
            except (KeyError, TypeError, ValueError):
                continue
            if b.lo - 1e6 <= f <= b.hi + 1e6:
                reg = {"vfo": f, "mode": m}
                for k in STACK_KEYS:
                    if k in r:
                        reg[k] = r[k]
                regs.append(reg)
        if regs:
            i = entry.get("i", 0)
            out[name] = {"i": int(i) % len(regs) if isinstance(i, (int, float)) else 0, "regs": regs}
    return out
