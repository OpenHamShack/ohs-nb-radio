"""The IARU Region 3 band plan, 160 m to 6 cm, as data: the generic plan
for an Asia-Pacific station whose country has no national plan written
here (ohsradio/plans/__init__.py choose()).

R3 states the weight itself: "In all cases of conflict between a band
plan and the national regulations of a country, the latter shall
prevail" [P1 p.3]. The licence is the law; the guard warns outside this
plan (or refuses, under "enforce") and always refuses its beacon and
satellite segments.

Source: IARU Region 3 Band Plan, Document R3-004 Rev. 2, agreed by the
19th Region 3 Conference on 6 Nov 2024 (P1), transcribed in
docs/ham/bandplan-iaru-regions.md section 5 with each row's PDF page.

Decisions taken while encoding:

- Mode words follow P1's definitions [P1 p.3-4]: "Narrowband" is CW and
  digital modes up to 500 Hz; "Phone" is SSB, AM, FM and digital voice;
  "All modes" is any mode fitting the bandwidth (every class). Rows that
  carry an "Image" centre of activity also admit the image class, since
  the plan puts its image centre there.
- The IBP "500 Hz guard band for beacons" may be 500 Hz in all or each
  side: the plan does not say [unverified either way]. The guard is
  +-1 kHz, as R1 and R2 protect: wide enough for either reading, and it
  costs nothing R3 plans for (source document, section 3, 20 m).
- Satellite segments are refused: P1 defines a satellite segment as one
  that "should be kept clear of other operating modes" [P1 p.4]. That
  includes 29300-29510 kHz ("Satellite - uplink and downlink"), which
  the source document's section 6 lists as shared; the definition is the
  same one that makes 145.8-146 MHz exclusive, so it is applied alike.
  The shared ones stay transmittable: 21125-21450 kHz (inside CW and
  narrowband rows), 144.000-144.025 ("satellite and terrestrial") and
  3400-3410 MHz (weak-signal rows).
- Every beacon sub-band is refused, including 50.020-50.080 MHz, which
  the plan does not call exclusive: no ordinary traffic is planned there.
- The 9 cm radio-astronomy band (3345.8-3352.5 MHz, "No operation") is
  "not for transmitting" (modes empty): no kind in base.KINDS refuses it
  without misnaming it, so the guard warns, and refuses under "enforce".
- 30 m starts at 10110 kHz as printed; 10100-10110 is allocated but
  unplanned, so the guard is silent there. 40 m ends at 7200: P1 says
  7200-7300 "is not allocated to the amateur service in Region 3".
  440-450 MHz is left out: only Australia and the Philippines hold it,
  and P1 itself drops it. The printed 6 cm row 5850-5925 is left out: R3
  has no amateur allocation above 5850 MHz.
- Overlapping rows as printed are split where the next row begins (20 m
  narrowband to 14110 against phone from 14100; 10 m inputs to 29590
  against simplex from 29520; 13 cm all modes from 2304.3 against the
  beacons to 2304.4), the more specific row winning.
- P1 has no repeater, FM simplex or calling sub-bands on 2 m and only
  coarse segments above it; where it is "All modes" with no bandwidth,
  max_bw is None. On 6 m above 50.5 MHz the limit was removed in Nov 2024.

All frequencies Hz.
"""
from __future__ import annotations

from .base import (ALL, CLASS_WORD, CW, FM, HF_ALL, MODE_CLASS, NARROW, NONE, WEAK, Seg,  # noqa: F401
                   make_lookup)
from .base import k as _k
from .base import m as _m

ID = "iaru-r3"
TITLE = "IARU Region 3 band plan"
SHORT = "IARU Region 3"
REGION = 3
COUNTRY = ()
SOURCE = {"title": "IARU Region 3 Band Plan, Document R3-004 (R3-004-Band-Plans-IARU-Region-3.pdf)",
          "url": "https://iaru-r3.org/wp-content/uploads/2025/01/R3-004-Band-Plans-IARU-Region-3.pdf",
          "version": "Rev. 2, November 2024 (agreed by the 19th IARU Region 3 Conference)",
          "date": "2024-11-06", "checked": "2026-10-08"}
SOURCES = [SOURCE]

PHONE = frozenset({"cw", "ssb", "am", "fm", "dv"})            # "CW, phone"
PHONE_NB = PHONE | {"digi"}                                    # "CW, narrowband/digimodes, phone"
DIGI = frozenset({"digi"})
NBFM = frozenset({"cw", "ssb", "digi", "fm"})
IMAGE = {"image"}

# HF, kHz [P1 p.5-12].
HF = (
    _k((1800, 1830, "CW", CW, 200, ""), (1830, 1840, "CW, narrowband", NARROW, 500, ""),
       (1840, 2000, "all modes", ALL, 2700, "")) +
    _k((3500, 3510, "CW, DX", CW, 200, ""), (3510, 3535, "CW", CW, 200, ""),
       (3535, 3600, "CW, phone, digimodes", PHONE_NB, 2700, ""),
       (3600, 3775, "CW, digimodes, phone", PHONE_NB | IMAGE, 2700, ""),
       (3775, 3800, "CW, phone, DX", PHONE, 2700, ""),
       (3800, 3900, "CW, phone, digimodes", PHONE_NB | IMAGE, 2700, "")) +
    _k((5351.5, 5354, "CW, narrowband digimodes", NARROW, 500, ""), (5354, 5366, "all modes, USB", ALL, 2700, ""),
       (5366, 5366.5, "weak-signal modes", DIGI, 20, "")) +
    # 7030-7040 is printed 2700 Hz for "CW, NB, Phone"; encoded as printed.
    _k((7000, 7030, "CW", CW, 200, ""), (7030, 7040, "CW, narrowband, phone", PHONE_NB, 2700, ""),
       (7040, 7060, "all modes", ALL, 2700, ""), (7060, 7100, "all modes", ALL, 2700, ""),
       (7100, 7200, "all modes", ALL, 2700, "")) +
    _k((10110, 10130, "CW", CW, 200, ""), (10130, 10150, "CW, narrowband digimodes", NARROW, 500, "")) +
    # 14070-14110 narrowband overlaps 14100-14112 as printed; the narrowband
    # row is taken to stop at the IBP guard, where the next row begins.
    _k((14000, 14070, "CW", CW, 200, ""), (14070, 14099, "CW, narrowband", NARROW, 500, ""),
       (14099, 14101, "IBP beacon guard", None, None, "beacon"),
       (14101, 14112, "CW, narrowband, phone", PHONE_NB, 2700, ""),
       (14112, 14350, "CW, phone", PHONE | IMAGE, 2700, "")) +
    # 18095-18110 is printed 2700 Hz for "CW, Narrowband - Digimodes".
    _k((18068, 18095, "CW", CW, 200, ""), (18095, 18109, "CW, narrowband digimodes", NARROW, 2700, ""),
       (18109, 18111, "IBP beacon guard", None, None, "beacon"),
       (18111, 18120, "CW, narrowband, phone", PHONE_NB, 2700, ""), (18120, 18168, "CW, phone", PHONE, 2700, "")) +
    _k((21000, 21070, "CW", CW, 200, ""), (21070, 21110, "CW, narrowband", NARROW, 500, ""),
       (21110, 21125, "CW, narrowband digimodes", NARROW, 2700, ""),
       (21125, 21149, "CW, narrowband digimodes, satellite uplink", NARROW, 2700, ""),
       (21149, 21151, "IBP beacon guard", None, None, "beacon"),
       (21151, 21450, "CW, phone, satellite uplink", PHONE | IMAGE, 2700, "")) +
    _k((24890, 24915, "CW", CW, 200, ""), (24915, 24929, "CW, narrowband", NARROW, 500, ""),
       (24929, 24931, "IBP beacon guard", None, None, "beacon"),
       (24931, 24940, "CW, narrowband, phone", PHONE_NB, 2700, ""), (24940, 24990, "CW, phone", PHONE, 2700, "")) +
    # 10 m: the inputs (29510-29590) and simplex (29520-29620) rows overlap
    # as printed; the simplex row is taken from where the inputs end. R3
    # has no guard channel at 29510-29520.
    _k((28000, 28070, "CW", CW, 200, ""), (28070, 28150, "CW, narrowband", NARROW, 500, ""),
       (28150, 28190, "CW, narrowband, DX", NARROW, 500, ""),
       (28190, 28201, "beacons, IBP", None, None, "beacon"),
       (28201, 28225, "continuous-duty beacons", None, None, "beacon"),
       (28225, 29100, "all modes", ALL, 2700, ""), (29100, 29300, "all modes", ALL, 6000, ""),
       (29300, 29510, "satellites", None, None, "satellite"),
       (29510, 29590, "FM repeater inputs", ALL, 6000, ""), (29590, 29620, "FM simplex, calling", ALL, 6000, ""),
       (29620, 29700, "repeater outputs", NONE, None, "output"))
)

# 6 m and up, MHz [P1 p.13-18].
VHF = (
    _m((50.000, 50.020, "CW", CW, 200, ""), (50.020, 50.080, "international beacons", None, None, "beacon"),
       (50.080, 50.100, "CW", CW, 200, ""), (50.100, 50.500, "CW, phone, narrowband, digimodes", PHONE_NB, 2700, ""),
       (50.500, 54.000, "all modes, wideband", ALL, None, "")) +
    _m((144.000, 144.025, "digimodes, satellite and terrestrial", DIGI, 2700, ""),
       (144.025, 144.035, "EME, weak signal", NARROW, None, ""), (144.035, 145.800, "all modes", ALL, 25_000, ""),
       (145.800, 146.000, "satellites", None, None, "satellite"), (146.000, 148.000, "all modes", ALL, None, "")) +
    _m((430.000, 431.900, "all modes", ALL, 25_000, ""), (431.900, 432.240, "EME, weak signal", WEAK, 2700, ""),
       (432.240, 435.000, "all modes", ALL, 25_000, ""), (435.000, 438.000, "satellites", None, None, "satellite"),
       (438.000, 440.000, "all modes", ALL, None, "")) +
    _m((1240, 1260, "all modes", ALL, None, ""), (1260, 1270, "satellite uplinks", None, None, "satellite"),
       (1270, 1296, "all modes", ALL, None, ""), (1296, 1297, "EME, weak signal", WEAK, 2700, ""),
       (1297, 1300, "all modes", ALL, None, "")) +
    _m((2300.000, 2303.750, "all modes", ALL, None, ""), (2303.750, 2304.000, "weak signal", WEAK, 2700, ""),
       (2304.000, 2304.100, "weak signal, EME", WEAK, 2700, ""),
       (2304.100, 2304.300, "weak signal, calling", WEAK, 2700, ""),
       (2304.300, 2304.400, "beacons", None, None, "beacon"), (2304.400, 2400.000, "all modes", ALL, None, ""),
       (2400.000, 2450.000, "satellites", None, None, "satellite")) +
    # 9 cm: 3400-3410 is satellite and terrestrial weak signal alike (shared).
    _m((3300.0, 3345.8, "all modes", ALL, None, ""),
       (3345.8, 3352.5, "radio astronomy, no operation", None, None, "protected"),
       (3352.5, 3400.0, "all modes", ALL, None, ""), (3400.0, 3400.3, "satellite, EME", WEAK, 2700, ""),
       (3400.3, 3410.0, "weak signal, satellite", WEAK, 2700, ""), (3410.0, 3455.5, "all modes", ALL, None, ""),
       (3455.5, 3456.3, "weak signal, calling", NBFM, None, ""), (3456.3, 3457.0, "beacons", None, None, "beacon"),
       (3457.0, 3500.0, "all modes", ALL, None, "")) +
    _m((5650.0, 5670.0, "satellite uplinks", None, None, "satellite"), (5670.0, 5760.0, "all modes", ALL, None, ""),
       (5760.0, 5760.3, "EME, weak signal", WEAK, 2700, ""), (5760.3, 5761.0, "beacons", None, None, "beacon"),
       (5761.0, 5765.0, "all modes, weak signal", ALL, None, ""), (5765.0, 5830.0, "all modes", ALL, None, ""),
       (5830.0, 5850.0, "satellite downlinks", None, None, "satellite"))
)

SEGMENTS: list[Seg] = sorted(HF + VHF, key=lambda s: s.lo)

# Centres of activity and digital dials the plan states [P1 p.5-17]:
# (Hz, label, mode). JT65 dials are left out (not an OpenHamShack Radio mode).
# Some are printed in a neighbouring row (7070, 7090, 3795): they are
# centres all the same. 24960 is printed "Digital CoA" and read as digital
# voice, as R1 has it. 21094.6 is printed "21.0946 kHz". The satellite
# APRS frequency 145.825 is left out: the guard refuses that segment.
CENTRES = [
    (1_836_000, "QRP", "cw"), (1_836_600, "WSPR", "wspr"), (1_840_000, "FT8", "ft8"),
    (3_560_000, "QRP", "cw"), (3_568_600, "WSPR", "wspr"), (3_573_000, "FT8", "ft8"),
    (3_600_000, "emergency", "lsb"), (3_690_000, "digital voice", "freedv"), (3_690_000, "SSB QRP", "lsb"),
    (3_735_000, "image", "sstv"), (3_795_000, "DX phone", "lsb"), (3_845_000, "image", "sstv"),
    (7_030_000, "QRP", "cw"), (7_038_600, "WSPR", "wspr"), (7_040_000, "RTTY DX", "rtty"),
    (7_070_000, "digital voice", "freedv"), (7_074_000, "FT8", "ft8"), (7_090_000, "SSB QRP", "lsb"),
    (7_095_000, "DX phone", "lsb"), (7_110_000, "emergency", "lsb"), (7_165_000, "image", "sstv"),
    (10_116_000, "QRP", "cw"), (10_136_000, "FT8", "ft8"), (10_138_600, "WSPR", "wspr"),
    (14_055_000, "QRS", "cw"), (14_060_000, "QRP", "cw"), (14_074_000, "FT8", "ft8"),
    (14_095_600, "WSPR", "wspr"), (14_130_000, "digital voice", "freedv"), (14_195_000, "DX phone", "usb"),
    (14_230_000, "image", "sstv"), (14_285_000, "SSB QRP", "usb"), (14_300_000, "global emergency", "usb"),
    (18_086_000, "QRP", "cw"), (18_100_000, "FT8", "ft8"), (18_104_600, "WSPR", "wspr"),
    (18_130_000, "SSB QRP", "usb"), (18_160_000, "digital voice", "freedv"), (18_160_000, "emergency", "usb"),
    (21_055_000, "QRS", "cw"), (21_060_000, "QRP", "cw"), (21_074_000, "FT8", "ft8"),
    (21_094_600, "WSPR", "wspr"), (21_180_000, "digital voice", "freedv"), (21_295_000, "DX phone", "usb"),
    (21_340_000, "image", "sstv"), (21_360_000, "global emergency", "usb"),
    (24_906_000, "QRP", "cw"), (24_915_000, "FT8", "ft8"), (24_924_600, "WSPR", "wspr"),
    (24_950_000, "SSB QRP", "usb"), (24_960_000, "digital voice", "freedv"),
    (28_055_000, "QRS", "cw"), (28_074_000, "FT8", "ft8"), (28_124_600, "WSPR", "wspr"),
    (28_330_000, "digital voice", "freedv"), (28_360_000, "QRP", "usb"), (28_495_000, "DX", "usb"),
    (28_680_000, "image", "sstv"), (29_600_000, "international calling", "fm"),
    (50_110_000, "DX", "usb"), (50_293_700, "WSPR", "wspr"), (50_313_000, "FT8", "ft8"),
    (144_100_000, "DX calling", "usb"), (144_489_000, "WSPR", "wspr"), (144_800_000, "APRS", "fm"),
    (2_304_100_000, "calling", "usb"), (3_400_100_000, "calling", "usb"), (3_456_100_000, "calling", "usb"),
    (5_760_100_000, "calling", "usb"),
]

# The five NCDXF/IARU beacon frequencies [P1 p.8-12].
IBP = [14_100_000.0, 18_110_000.0, 21_150_000.0, 24_930_000.0, 28_200_000.0]


segment_at, overlapping = make_lookup(SEGMENTS)
