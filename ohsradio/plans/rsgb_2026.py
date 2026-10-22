"""The RSGB 2026 band plan, 160 m to 6 cm, as data.

Source: RSGB 2026 Band Plan, "Updated January-2026" (file 260125) [R1],
transcribed in docs/ham/bandplan-r1-uk.md sections 2 and 3, where each
band's own "effective from" date is given; the line-by-line check of
these tables against the PDF is recorded in docs/ham/licence-check.md.
Dial frequencies of the digital modes come from WSJT-X [W1] via
ohsradio/bands.py.

The band plan is a voluntary code of practice (the licence is the law):
the guard warns when a transmission is outside what a segment is for,
unless the operator chooses "enforce" - except for two kinds of segment it
always refuses, whatever that setting: **beacons** (the IBP slots and the
VHF/UHF beacon sub-bands) and **satellites** (10 m, 2 m, 70 cm, 3 cm), as
QO-100 NB refuses the QO-100 beacon segments (bandplan-r1-uk.md section 3,
"What the guard does with these").

Segment edges around FM channels are the channel's edges (half the
channel spacing either side of the first and last channel), derived here
from the plan's channel lists so that an FM signal on the end channel is
inside its segment.

A segment's `modes` is the set of mode classes it is for; an empty set
means "not for transmitting" (a repeater's own output); None means the
plan reserves it (beacons, satellites). Where the transcribed table is
silent between two of its segments, there is no segment: the plan guard
says nothing there and only the licence applies. Bandwidths are the
plan's ("CW only = 200 Hz; narrow band = 500 Hz; all modes = 2.7 kHz" on
HF); None = the plan sets none.

All frequencies Hz.
"""
from __future__ import annotations

from .. import bands as _bands
from .base import (ALL, CLASS_WORD, CW, FM, HF_ALL, MODE_CLASS, NARROW, NONE, WEAK, Seg,  # noqa: F401
                   make_lookup)
from .base import k as _k
from .base import m as _m

ID = "rsgb-2026"
TITLE = "RSGB band plan 2026"
SHORT = "RSGB 2026"
REGION = 1
COUNTRY = ("GB",)
SOURCE = {"title": "RSGB 2026 Band Plan (260125_rsgb_band_plan_2026.pdf)",
          "url": "https://rsgb.services/public/bandplans/docs/260125_rsgb_band_plan_2026.pdf",
          "version": "Updated January 2026 (file 260125); each band has its own effective-from date",
          # The date is the file name's (260125); the plan itself says "Updated January-2026".
          "date": "2026-01-25", "checked": "2026-10-04"}


# HF, kHz (bandplan-r1-uk.md section 2).
HF = (
    _k((1810, 1838, "CW", CW, 200, ""), (1838, 1840, "narrow digital", NARROW, 500, ""),
       (1840, 2000, "all modes", HF_ALL, 2700, "")) +
    _k((3500, 3570, "CW", CW, 200, ""), (3570, 3580, "narrow digital (200 Hz)", NARROW, 200, ""),
       (3580, 3600, "narrow digital", NARROW, 500, ""), (3600, 3800, "all modes", HF_ALL, 2700, "")) +
    # 60 m: the UK's eleven segments; all modes, USB, up to 6 kHz under the
    # licence's Note G (the licence guard enforces those).
    _k(*[(lo, hi, "60 m segment", HF_ALL, 6000, "") for lo, hi in
         ((5258.5, 5264), (5276, 5284), (5288.5, 5292), (5298, 5307), (5313, 5323), (5333, 5338), (5354, 5358),
          (5362, 5374.5), (5378, 5382), (5395, 5401.5), (5403.5, 5406.5))]) +
    _k((7000, 7040, "CW", CW, 200, ""), (7040, 7050, "narrow digital", NARROW, 500, ""),
       (7050, 7200, "all modes", HF_ALL, 2700, "")) +
    _k((10100, 10130, "CW", CW, 200, ""), (10130, 10150, "narrow digital", NARROW, 500, "")) +
    _k((14000, 14070, "CW", CW, 200, ""), (14070, 14099, "narrow digital", NARROW, 500, ""),
       (14099, 14101, "IBP beacons", None, None, "beacon"), (14101, 14112, "all modes", HF_ALL, 2700, ""),
       (14112, 14125, "all modes, no digital", HF_ALL - {"digi"}, 2700, ""),
       (14125, 14350, "all modes", HF_ALL, 2700, "")) +
    _k((18068, 18095, "CW", CW, 200, ""), (18095, 18109, "narrow digital", NARROW, 500, ""),
       (18109, 18111, "IBP beacons", None, None, "beacon"), (18111, 18168, "all modes", HF_ALL, 2700, "")) +
    _k((21000, 21070, "CW", CW, 200, ""), (21070, 21110, "narrow digital", NARROW, 500, ""),
       (21110, 21120, "all modes, no SSB", HF_ALL - {"ssb"}, 2700, ""),
       (21120, 21149, "narrow digital", NARROW, 500, ""), (21149, 21151, "IBP beacons", None, None, "beacon"),
       (21151, 21450, "all modes", HF_ALL, 2700, "")) +
    _k((24890, 24915, "CW", CW, 200, ""), (24915, 24929, "narrow digital", NARROW, 500, ""),
       (24929, 24931, "IBP beacons", None, None, "beacon"), (24931, 24990, "all modes", HF_ALL, 2700, "")) +
    _k((28000, 28070, "CW", CW, 200, ""), (28070, 28190, "narrow digital", NARROW, 500, ""),
       (28190, 28225, "IBP beacons", None, None, "beacon"), (28225, 29100, "all modes", HF_ALL, 2700, ""),
       (29100, 29200, "FM simplex", ALL, 12500, ""), (29200, 29300, "all modes", ALL, None, ""),
       (29300, 29510, "satellites", None, None, "satellite"), (29510, 29515, "all modes", ALL, None, ""),
       (29515, 29595, "repeater inputs", FM, 12500, ""), (29595, 29605, "FM calling", FM, 12500, ""),
       (29605, 29615, "all modes", ALL, None, ""), (29615, 29700, "repeater outputs", NONE, None, "output"))
)

# VHF and up, MHz (bandplan-r1-uk.md section 3).
VHF = (
    _m((70.000, 70.090, "beacons", None, None, "beacon"), (70.100, 70.250, "narrow band", WEAK, 2700, ""),
       (70.250, 70.294, "all modes", ALL, None, ""), (70.294, 70.500, "FM channels", FM, 12500, "")) +
    # 2 m: the RV and simplex edges are the plan's printed rows (R1 p.20), not
    # first/last channel centres; the simplex row includes the two 5 W ad-hoc
    # repeater outputs (145.575, 145.5875).
    _m((144.025, 144.100, "CW", CW, 500, ""), (144.100, 144.150, "CW & MGM", NARROW, 500, ""),
       (144.150, 144.400, "SSB & MGM", WEAK, 2700, ""),
       (144.400, 144.490, "beacons", None, None, "beacon"),
       (144.96875, 144.990, "low-power repeater inputs", FM, 12500, ""),
       (144.990, 145.1935, "repeater inputs", FM, 12500, ""), (145.200, 145.5935, "FM simplex", FM, 12500, ""),
       (145.5935, 145.7935, "repeater outputs", NONE, None, "output"),
       (145.806, 146.000, "satellites", None, None, "satellite")) +
    _m((430.39375, 430.78125, "DV repeater inputs", FM, 12500, ""),
       (430.80625, 430.98125, "repeater outputs (RU)", NONE, None, "output"),
       (432.000, 432.400, "narrow band", WEAK, 2700, ""), (432.400, 432.490, "beacons", None, None, "beacon"),
       (432.9875, 433.3875, "repeater outputs (RB)", NONE, None, "output"),
       (433.39375, 433.58125, "FM simplex", FM, 12500, ""),
       (434.5875, 434.9875, "repeater inputs (RB)", FM, 12500, ""),
       (435.000, 438.000, "satellites", None, None, "satellite"),
       (438.40625, 438.58125, "repeater inputs (RU)", FM, 12500, ""),
       (439.39375, 439.78125, "DV repeater outputs", NONE, None, "output")) +
    _m((1290.9875, 1291.3875, "repeater inputs (RM)", FM, 25000, ""),
       (1296.150, 1296.800, "narrow band", WEAK, 2700, ""), (1296.800, 1296.990, "beacons", None, None, "beacon"),
       (1296.990, 1297.3875, "repeater outputs (RM)", NONE, None, "output"),
       (1297.4875, 1297.7625, "FM simplex", FM, 25000, "")) +
    _m((2320.000, 2320.800, "narrow band", WEAK, 2700, ""), (2320.800, 2320.990, "beacons", None, None, "beacon"),
       (2321.000, 2322.000, "FM & DV", FM, 25000, "")) +
    _m((3400.000, 3400.800, "narrow band", WEAK, 2700, ""), (3400.800, 3400.995, "beacons", None, None, "beacon")) +
    _m((5760.000, 5762.000, "narrow band", WEAK, 2700, ""),
       (10475.000, 10500.000, "satellites", None, None, "satellite"))
)

SEGMENTS: list[Seg] = sorted(HF + VHF, key=lambda s: s.lo)

# Centres of activity: (Hz, label, mode). The scope marks the beacon
# frequencies; the memories list carries the rest as presets.
CENTRES = [
    (1_836_000, "QRP CW", "cw"), (3_555_000, "QRS", "cw"), (3_560_000, "QRP CW", "cw"),
    (3_663_000, "UK emergency", "lsb"), (3_690_000, "SSB QRP", "lsb"), (3_735_000, "SSTV", "lsb"),
    (5_262_000, "CW QRP", "cw"), (5_278_500, "UK emergency", "usb"), (5_317_000, "AM", "am"),
    (7_030_000, "QRP CW", "cw"), (7_090_000, "SSB QRP", "lsb"), (7_110_000, "R1 emergency", "lsb"),
    (7_165_000, "SSTV", "lsb"), (10_116_000, "QRP CW", "cw"), (14_055_000, "QRS", "cw"),
    (14_060_000, "QRP CW", "cw"), (14_230_000, "SSTV", "usb"), (14_285_000, "SSB QRP", "usb"),
    (14_300_000, "emergency", "usb"), (18_086_000, "QRP CW", "cw"), (21_060_000, "QRP CW", "cw"),
    (21_340_000, "SSTV", "usb"), (28_060_000, "QRP CW", "cw"), (28_680_000, "SSTV", "usb"),
    (29_600_000, "FM calling", "fm"), (144_050_000, "CW centre", "cw"), (144_300_000, "SSB calling", "usb"),
    (144_500_000, "SSTV", "usb"), (144_612_500, "DV calling", "fm"), (144_800_000, "APRS", "fm"),
    (145_500_000, "FM calling", "fm"), (432_200_000, "CW/SSB centre", "usb"), (433_500_000, "FM calling", "fm"),
    (438_612_500, "DV calling", "fm"), (1_296_200_000, "narrow band centre", "usb"),
    (1_297_725_000, "DV calling", "fm"), (2_320_200_000, "SSB centre", "usb"),
    (3_400_100_000, "narrow band centre", "usb"), (5_760_100_000, "narrow band centre", "usb"),
]

# The five NCDXF/IARU beacon frequencies (the IBP slots' centres): the
# scope marks them.
IBP = [14_100_000.0, 18_110_000.0, 21_150_000.0, 24_930_000.0, 28_200_000.0]


segment_at, overlapping = make_lookup(SEGMENTS)

# Repeater pairs (ohsradio/plans/repeaters.py): the UK schemes bands.py has
# carried since 04/10/2026, RSGB 2026 [R1] as tabled in bandplan-r1-uk.md
# sections 2 and 3, and each band's usual split.
REPEATERS = list(_bands.REPEATERS)
SIMPLEX = list(_bands.SIMPLEX)
RPT_OFFSET = {b.name: b.rpt_offset for b in _bands.BANDS if b.rpt_offset}
