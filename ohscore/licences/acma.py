"""The Australian amateur licence (ACMA class licence 2023): who may
transmit where, at what power.

Source: the Radiocommunications (Amateur Stations) Class Licence 2023,
F2023L01648, compilation 0 (never amended as of 2026-10-08) [CL], Schedule 2
Tables A (Foundation), B (Standard) and C (Advanced), with s 17-18, as
transcribed in docs/ham/countries/au.md (sections 2-8). Since 19 February
2024 personal stations need no individual licence; legacy apparatus
licences (to about June 2028) carry the same tables (LCD 2025 Sch 1).

Decisions:

- Power is "watts pX" (peak envelope) or "watts pY" (mean). Standard and
  Advanced get the higher pX figure only "if the station uses emission
  mode J3E or R3E" (and C3F, analogue television, where the row says so);
  in any other case the lower pY figure. Encoded as a Limit per mode
  class: SSB voice the pX figure, everything else - FT8 (J2D), CW, FM, AM,
  digital voice - the pY one. OpenHamShack's "image" class cannot tell C3F
  television from SSTV, so it gets pY: the stricter. Foundation is 10 W pX
  whatever the mode. CL s 17 says "radiated power" but the units are the
  Radio Regulations' transmitter-line powers and the explanatory statement
  calls them transmitter output limits (au.md s.5, s.11 item 1): the
  figure is held as a cap on transmitter output, the cautious reading
  either way.
- Bands are (lower, upper] by law (CL s 5(3)); the guard requires the whole
  signal inside, so EDGES only records it.
- The "PSD rule" (a signal wider than 8 kHz, 16 kHz on 10 m, may run only at
  1 W per 100 kHz) cannot be expressed: those bands are held to 8 kHz
  (16 kHz on 10 m), which refuses some lawful low-power wide signals and
  never allows an unlawful one.
- 60 m is allocated in the spectrum plan but not in the class licence:
  refused.
- The WA Radio Quiet Zone (no transmission at all within 150 km of
  26.704167 S, 116.658889 E) and the 3.4-3.6 GHz HCIS exclusions are
  station conditions defaulting to the answer that refuses.

QO-100 is below the horizon from all of Australia; 2400-2450 MHz is
amateur-satellite only under RR 5.282, held by Standard and Advanced.
"""
from __future__ import annotations

from . import Limit

ID = "acma-2023"
TITLE = "ACMA Radiocommunications (Amateur Stations) Class Licence 2023"
SHORT = "Australia (ACMA)"
AUTHORITY = "ACMA"
COUNTRY = ("AU",)
PLAN = ""
EDGES = "lower-open"
# [CL] in docs/ham/countries/au.md.
SOURCE = {
    "title": "Radiocommunications (Amateur Stations) Class Licence 2023 (F2023L01648)",
    "url": "https://legislation.gov.au/F2023L01648/asmade/2023-12-12/text/original/pdf",
    "version": "As made, dated 7 December 2023, registered 12 Dec 2023, in force 19 Feb 2024; compilation 0, "
               "no amendments as of 2026-10-08",
    "date": "2023-12-07",
    "checked": "2026-10-08",
    "sha256": "50036cf5e634e1e66922ef912b064f532919759063ab0b8f1d5570e812ab9f1c",
}
CLASSES = ("au_foundation", "au_standard", "au_advanced")
CLASS_NAME = {"au_foundation": "Foundation", "au_standard": "Standard", "au_advanced": "Advanced"}

_SSB = frozenset({"ssb"})
_OTHER = frozenset({"cw", "am", "fm", "digi", "dv", "image"})
F = (10.0, "PEP")                                                     # Table A: 10 W pX, any mode
S = (Limit(100.0, "PEP", _SSB), Limit(30.0, "mean", _OTHER))          # Table B: 100 W pX J3E/R3E, 30 W pY
A = (Limit(400.0, "PEP", _SSB), Limit(120.0, "mean", _OTHER))         # Table C: 400 W pX, 120 W pY


def _lim(f=False, s=False, a=True):
    out = {}
    if f:
        out["au_foundation"] = F
    if s:
        out["au_standard"] = S
    if a:
        out["au_advanced"] = A
    return out


def _k(lo_khz, hi_khz, lim, note, src, extras=None):
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


def _m(lo_mhz, hi_mhz, lim, note, src, extras=None):
    return _k(lo_mhz * 1e3, hi_mhz * 1e3, lim, note, src, extras)


# CL Schedule 2: Table A p18, Table B pp.18-19, Table C pp.20-21. Every band
# is (lower, upper].
ALLOCATIONS = [
    _k(135.7, 137.8, {"au_advanced": (1.0, "EIRP")}, "2200 m, secondary; 1 W pX EIRP; 2.1 kHz at most",
       "CL Sch 2 Table C item 1 p20"),
    _k(472, 479, {"au_advanced": (5.0, "EIRP")}, "630 m, secondary; 5 W pX EIRP; 3 kHz at most",
       "CL Sch 2 Table C item 2 p20"),
    _k(1800, 1875, _lim(), "160 m", "CL Sch 2 Table C item 3(a) p20"),
    _k(3500, 3700, _lim(True, True), "80 m, primary", "CL Sch 2 Table A 1(a) p18, B 1(a) p18, C 3(b) p20"),
    _k(3776, 3800, _lim(), "80 m DX window; 8 kHz at most", "CL Sch 2 Table C item 4(a) p20"),
    _k(7000, 7100, _lim(True, True), "40 m, primary", "CL Sch 2 Table A 1(b), B 1(b), C 3(c) pp.18-20"),
    _k(7100, 7300, _lim(True, True), "40 m, secondary; 8 kHz at most",
       "CL Sch 2 Table A 2 p18, B 2 p19, C 4(b) p20"),
    _k(10100, 10150, _lim(), "30 m, secondary; 8 kHz at most", "CL Sch 2 Table C item 4(c) p20"),
    _k(14000, 14350, _lim(s=True), "20 m, primary", "CL Sch 2 Table B 1(c) p18, C 3(d) p20"),
    _k(18068, 18168, _lim(), "17 m, primary", "CL Sch 2 Table C item 3(e) p20"),
    _k(21000, 21450, _lim(True, True), "15 m, primary", "CL Sch 2 Table A 1(c), B 1(d), C 3(f) pp.18-20"),
    _k(24890, 24990, _lim(), "12 m, primary", "CL Sch 2 Table C item 3(g) p20"),
    _k(28000, 29700, _lim(True, True), "10 m, primary", "CL Sch 2 Table A 3 p18, B 3 p19, C 5 p20"),
    _m(50, 52, _lim(s=True), "6 m, secondary to broadcasting; 100 kHz at most",
       "CL Sch 2 Table B 4 p19, C 6 p20"),
    _m(52, 54, _lim(s=True), "6 m, primary", "CL Sch 2 Table B 5(a) p19, C 7(a) p21"),
    _m(144, 148, _lim(True, True), "2 m, primary", "CL Sch 2 Table A 4(a) p18, B 5(b) p19, C 7(b) p21"),
    _m(430, 450, _lim(True, True), "70 cm, secondary", "CL Sch 2 Table A 4(b) p18, B 5(c) p19, C 7(c) p21"),
    _m(1240, 1300, _lim(s=True), "23 cm, secondary", "CL Sch 2 Table B 5(d) p19, C 7(d) p21"),
    _m(2300, 2302, _lim(), "13 cm, secondary", "CL Sch 2 Table C item 7(e) p21"),
    _m(2400, 2450, _lim(s=True), "13 cm, secondary; ISM; amateur-satellite only by RR 5.282",
       "CL Sch 2 Table B 5(e) p19, C 7(f) p21"),
    _m(3300, 3400, _lim(), "9 cm, secondary", "CL Sch 2 Table C item 7(g) p21"),
    _m(3400, 3600, _lim(), "9 cm, secondary; not in the HCIS areas of Schedule 3 or spectrum-licensed areas",
       "CL Sch 2 Table C item 8 p21; s 18(1)-(2) p10"),
    _m(5650, 5850, _lim(s=True), "5 cm, secondary", "CL Sch 2 Table B 5(f) p19, C 9(a) p21"),
    _m(10000, 10500, _lim(), "3 cm, secondary", "CL Sch 2 Table C item 9(b) p21"),
    _m(24000, 24250, _lim(), "12 mm", "CL Sch 2 Table C item 9(c) p21"),
    _m(47000, 47200, _lim(), "6 mm, primary", "CL Sch 2 Table C item 9(d) p21"),
    _m(76000, 81000, _lim(), "4 mm", "CL Sch 2 Table C item 9(e) p21"),
    _m(122250, 123000, _lim(), "2.5 mm, secondary", "CL Sch 2 Table C item 9(f) p21"),
    _m(134000, 141000, _lim(), "2 mm", "CL Sch 2 Table C item 9(g) p21"),
    _m(241000, 250000, _lim(), "1.2 mm", "CL Sch 2 Table C item 9(h) p21"),
]

REFUSED = [
    (5351.5e3, 5366.5e3, "60 m is not in the Australian amateur class licence, although the spectrum plan "
                         "allocates it (CL s 17 and Schedule 2).", "au.md s.3, gaps; CL s 17 pp.9-10"),
]

# Necessary bandwidth (CL Sch 2 column 3), every mode, every class holding
# the band. The hard caps are as written; the "PSD rule" bands are held to
# the width above which the 1 W / 100 kHz density rule would start.
_EVERY = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})


def _bw(lo_hz, hi_hz, bw_hz, note, src, classes=CLASSES):
    return (lo_hz, hi_hz, {c: _EVERY for c in classes}, bw_hz, note, src)


_PSD = "the PSD rule (above {:g} kHz, 1 W per 100 kHz) cannot be judged: held to {:g} kHz"
EMISSIONS = [
    _bw(135.7e3, 137.8e3, 2100.0, "2.1 kHz at most", "CL Sch 2 Table C item 1 p20"),
    _bw(472e3, 479e3, 3000.0, "3 kHz at most", "CL Sch 2 Table C item 2 p20"),
    _bw(1800e3, 1875e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table C item 3(a) p20"),
    _bw(3500e3, 3700e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table A 1(a), B 1(a), C 3(b)"),
    _bw(3776e3, 3800e3, 8000.0, "8 kHz at most", "CL Sch 2 Table C item 4(a) p20"),
    _bw(7000e3, 7100e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table A 1(b), B 1(b), C 3(c)"),
    _bw(7100e3, 7300e3, 8000.0, "8 kHz at most", "CL Sch 2 Table A 2, B 2, C 4(b)"),
    _bw(10100e3, 10150e3, 8000.0, "8 kHz at most", "CL Sch 2 Table C item 4(c) p20"),
    _bw(14000e3, 14350e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table B 1(c), C 3(d)"),
    _bw(18068e3, 18168e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table C item 3(e) p20"),
    _bw(21000e3, 21450e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table A 1(c), B 1(d), C 3(f)"),
    _bw(24890e3, 24990e3, 8000.0, _PSD.format(8, 8), "CL Sch 2 Table C item 3(g) p20"),
    _bw(28000e3, 29700e3, 16000.0, _PSD.format(16, 16), "CL Sch 2 Table A 3, B 3, C 5"),
    # Table B item 4 caps Standard to 100 kHz on 50-52 MHz; Table C item 6
    # says "No limitation" for Advanced on the same range (Foundation does
    # not hold 50-52 MHz at all - absent from Table A). A single row for
    # every class, as this used to be, wrongly held Advanced to the cap
    # too; found by reading Table C item 6 directly rather than assuming
    # it matched Table B's.
    _bw(50e6, 52e6, 100000.0, "100 kHz at most (Standard only; Advanced has no limitation here)",
        "CL Sch 2 Table B 4 p19", classes=("au_standard",)),
]

# Where the station is (au.md s.3, per-band exceptions). Both default to
# the answer that refuses.
CONDITIONS = [
    {"key": "inWaQuietZone", "lo": 135.7e3, "hi": 250e9, "default": True,
     "label": "Station within 150 km of 26.704167 S, 116.658889 E (the WA Radio Quiet Zone)",
     "refuse": ("No amateur station may operate within 150 km of 26.704167 S, 116.658889 E, the Western "
                "Australia Radio Quiet Zone (Amateur Stations Class Licence s 18(3)); untick it in Settings › "
                "Licence & plan if this station is outside it."),
     "src": "CL s 18(3)-(4) p10; RQZ band plan Sch 1 p5"},
    {"key": "inAu34GhzExcludedArea", "lo": 3400e6, "hi": 3600e6, "default": True,
     "label": "Station in a 3.4-3.6 GHz excluded area (HCIS cells of Schedule 3, or a spectrum-licensed area)",
     "refuse": ("3.4-3.6 GHz may not be used where a transmission would reach the HCIS areas of Schedule 3 of "
                "the Amateur Stations Class Licence or a spectrum-licensed area (s 18(1)-(2)); untick it in "
                "Settings › Licence & plan if this station is clear of them."),
     "src": "CL s 18(1)-(2) p10, Sch 3 p22"},
]

# The amateur-satellite service in the spectrum plan (au.md s.6). The class
# licence makes no distinction, so a class holding a band holds its
# satellite use. 1260-1270 and 5650-5670 MHz are Earth-to-space under RR
# 5.282 (as us.md and ca.md read the same footnote); 5830-5850 MHz is
# space-to-Earth.
_ARSP = "ARSP 2021 (2025 update), Australian Table (au.md s.6)"
_282 = "ARSP 2021, RR 5.282 (au.md s.6)"
SATELLITE = [(a * 1e6, b * 1e6, d, s) for a, b, d, s in (
    (7.0, 7.1, "both", _ARSP), (14.0, 14.25, "both", _ARSP), (18.068, 18.168, "both", _ARSP),
    (21.0, 21.45, "both", _ARSP), (24.89, 24.99, "both", _ARSP), (28.0, 29.7, "both", _ARSP),
    (144, 146, "both", _ARSP), (435, 438, "both", _282), (1260, 1270, "up", _282), (2400, 2450, "both", _282),
    (3400, 3410, "both", _282), (5650, 5670, "up", _282), (5830, 5850, "down", _ARSP),
    (10450, 10500, "both", _ARSP), (24000, 24050, "both", _ARSP), (47000, 47200, "both", _ARSP),
    (76000, 81000, "both", _ARSP), (134000, 141000, "both", _ARSP), (241000, 250000, "both", _ARSP))]

# CEPT T/R 61-01 Annex 4 Table 2 (au.md s.8): only Advanced is the CEPT
# licence; a CEPT licence holder visiting operates as Advanced (ACMA's
# table of equivalent qualifications), up to 365 days, without registering.
CEPT = {"T/R 61-01": ("au_advanced",)}
CEPT_SRC = ("CEPT T/R 61-01 (18 Oct 2024) Annex 4 Table 2 and footnote 18; ACMA, Overseas amateurs visiting "
            "Australia, Table A (updated 2 Jun 2025)")
CEPT_VISITOR = {"T/R 61-01": "au_advanced"}

NOTES = [
    ("unattended", "An unattended station must run in automatic or computer-controlled mode with a timer that "
                   "shuts it down after 10 minutes of unintended transmission.", "CL s 13(4) p8"),
    ("repeater", "Repeaters and beacons need an apparatus licence; they may not operate under the class licence.",
     "CL s 13(2)(b)-(c) p8"),
    ("identification", "Send the call sign at the beginning and end of each transmission, and at least every 10 "
                       "minutes during a longer one.", "CL s 12(1) p7"),
    ("spectrum licences", "No amateur operation where a spectrum licence authorises devices at that frequency in "
                          "that area; which amateur bands that touches today, beyond 3.4 GHz, is not established.",
     "CL s 18(2) p10; au.md s.11 item 4"),
    ("visitors", "A visitor (not resident, at most 365 continuous days) operates with the Foundation, Standard or "
                 "Advanced privileges ACMA's table gives their home licence, and adds VK before the call sign.",
     "CL s 8(b), s 9, s 12(3); ACMA visitors page Table A"),
]
