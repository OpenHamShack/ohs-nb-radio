"""The UK amateur licence (Ofcom): who may transmit where, at what power.

Source: Ofcom OFW611, "Amateur Radio Wireless Telegraphy Licence
Conditions Booklet", Schedule 1 Tables A, B and C and their notes [O1],
as transcribed in docs/ham/bandplan-r1-uk.md section 1 and checked line by
line against the PDF (docs/ham/licence-check.md, which records the page
of each row and the PDF's checksum). Re-check before each release: Ofcom
changed the licence in February 2024 and October 2025.

Moved from ohsradio/licences/ on 08/10/2026, when the station country became
a setting: QO-100 NB needs it too, to check a 13 cm satellite uplink
against the operator's class, and an app may import only ohscore. The
shape every regime module has is ohscore/licences/__init__.py's docstring
and docs/ham/adding-a-country.md; this one is the worked example.

This is the law, so ohsradio/guard.py enforces it whatever the band-plan
setting: a transmission must lie wholly inside allocations the class has,
at no more than the class's power there. Limits are per *sub-allocation*
(a Full licensee has 1000 W on 1810-1850 kHz but 32 W on 1850-2000 kHz),
and some are not PEP but ERP or EIRP, which the guard computes from the
power chain's antenna gain.

Each row: (lo Hz, hi Hz, {class: (watts, "PEP" | "ERP" | "EIRP")}, note,
source). A class missing from a row may not transmit there.
"""
from __future__ import annotations

ID = "ofcom-2024"
TITLE = "Ofcom amateur licence (2024 conditions)"
SHORT = "UK (Ofcom)"
AUTHORITY = "Ofcom"
COUNTRY = ("GB",)
PLAN = "rsgb-2026"
# [O1] in docs/ham/bandplan-r1-uk.md; checksum and page map in licence-check.md.
SOURCE = {
    "title": "Ofcom OFW611, Amateur Radio Wireless Telegraphy Licence Conditions Booklet, Schedule 1",
    "url": "https://www.ofcom.org.uk/siteassets/resources/documents/spectrum/emf/"
           "emf-amateur-licence-terms-and-conditions.pdf",
    "version": "Published 21 February 2024 (PDF modified 28 Nov 2024; Ofcom's page updated 14 Oct 2025)",
    "date": "2024-02-21",
    "checked": "2026-10-04",
    "sha256": "718e8136d3ebcf52559e48a8d9aa5cdd624691fec07d3609968d574935baded6",
}
CLASSES = ("foundation", "intermediate", "full")
CLASS_NAME = {"foundation": "Foundation", "intermediate": "Intermediate", "full": "Full"}

_P, _E, _I = "PEP", "ERP", "EIRP"


# Where each row is in O1 (sha256 718e8136...baded6, 24 pages): Schedule 1
# Table A (Foundation) pp.15-16, Table B (Intermediate) pp.17-19, Table C
# (Full) pp.20-22, Note G (60 m) p.23. Rows below 50 MHz are on A p.15 /
# B p.17 / C p.20 unless the row says otherwise; checked row by row in
# docs/ham/licence-check.md section 2.
def _r(lo_khz, hi_khz, f, i, full, note="", src="O1 Sch.1 A p.15, B p.17, C p.20"):
    lim = {}
    for cls, v in (("foundation", f), ("intermediate", i), ("full", full)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    return (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)


# Bands 1.8 MHz - 5.85 GHz (the hardware this program drives) plus the LF/MF
# and 3 cm rows for completeness; in kHz for readability.
ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _E), (1.0, _E), (1.0, _E), "secondary, no interference basis"),
    _r(472, 479, None, None, (5.0, _I), "secondary", "O1 Sch.1 C p.20"),
    _r(1810, 1830, 25, 100, 1000, "primary (no interference basis to non-UK stations)"),
    _r(1830, 1850, 25, 100, 1000, "primary"),
    _r(1850, 2000, 25, 32, 32, "secondary, no interference basis"),
    _r(3500, 3800, 25, 100, 1000, "primary, shared"),
    # 60 m is handled by SIXTY below (Full only, eleven segments, Note G).
    _r(7000, 7100, 25, 100, 1000, "primary"),
    _r(7100, 7200, 25, 100, 1000, "primary"),
    _r(10100, 10150, 25, 100, 400, "secondary"),
    _r(14000, 14250, 25, 100, 1000, "primary"),
    _r(14250, 14350, 25, 100, 1000, "primary"),
    _r(18068, 18168, 25, 100, 1000, "primary"),
    _r(21000, 21450, 25, 100, 1000, "primary"),
    _r(24890, 24990, 25, 100, 1000, "primary"),
    _r(28000, 29700, 25, 100, 1000, "primary"),
    _r(50000, 51000, 25, 100, 1000, "primary (no interference basis to non-UK stations)"),
    _r(51000, 52000, 25, 100, 100, "secondary, no interference basis", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(70000, 70500, 25, 100, 160, "secondary, no interference basis", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(144000, 146000, 25, 100, 1000, "primary", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(430000, 431000, (25.0, _E), (40.0, _E), (40.0, _E), "secondary", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(431000, 432000, (25.0, _E), (40.0, _E), (40.0, _E), "secondary; not within 100 km of Charing Cross", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(432000, 435000, 25, 100, 400, "secondary", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(435000, 438000, 25, 100, 400, "secondary", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(438000, 440000, 25, 100, 400, "secondary", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(1240000, 1260000, None, 100, 400, "secondary", "O1 Sch.1 B p.17, C p.20"),
    _r(1260000, 1270000, None, 100, 400, "secondary (satellite: Earth to space only)", "O1 Sch.1 B p.17, C p.20"),
    _r(1270000, 1325000, None, 100, 400, "secondary", "O1 Sch.1 B p.17, C p.20"),
    _r(2310000, 2350000, None, 100, 400, "secondary, no interference basis", "O1 Sch.1 B p.17, C p.20"),
    _r(2390000, 2400000, None, 100, 400, "secondary, no interference basis", "O1 Sch.1 B p.17, C p.20"),
    _r(2400000, 2450000, 2, 100, 400, "secondary (must accept ISM interference)", "O1 Sch.1 A p.16, B p.17, C p.20"),
    _r(3400000, 3410000, None, 100, 400, "secondary, no interference basis", "O1 Sch.1 B p.18, C p.21"),
    _r(5650000, 5670000, 2, 100, 400, "secondary"),
    _r(5670000, 5680000, 2, 100, 400, "secondary"),
    _r(5755000, 5765000, 2, 100, 400, "secondary (must accept ISM interference)"),
    _r(5820000, 5830000, 2, 100, 400, "secondary (must accept ISM interference)"),
    _r(5830000, 5850000, None, 100, 400, "secondary (ISM)", "O1 Sch.1 B p.18, C p.21"),
    _r(10000000, 10125000, 1, 100, 400, "secondary"),
    _r(10225000, 10450000, 1, 100, 400, "secondary"),
    _r(10450000, 10475000, 1, 100, 400, "secondary"),
    _r(10475000, 10500000, 1, 100, 400, "amateur-satellite only"),
]

# 60 m [O1 Table C p.20, Note G p.23]: Full licence only, inside the eleven UK
# segments, 100 W PEP and at most 200 W EIRP, no wider than 6 kHz.
SIXTY_SEGMENTS_KHZ = [(5258.5, 5264), (5276, 5284), (5288.5, 5292), (5298, 5307), (5313, 5323), (5333, 5338),
                      (5354, 5358), (5362, 5374.5), (5378, 5382), (5395, 5401.5), (5403.5, 5406.5)]
SIXTY = {"lo": 5250e3, "hi": 5450e3, "segments": [(a * 1e3, b * 1e3) for a, b in SIXTY_SEGMENTS_KHZ],
         "class": "full", "pep": 100.0, "eirp": 200.0, "max_bw": 6000.0}

# Not in the licence at all: refused for every class (bandplan-r1-uk.md
# section 1, "Gaps the guard must refuse for every class").
GAPS = [(2350e6, 2390e6, "2350-2390 MHz"), (2450e6, 3400e6, "13 cm above 2450 MHz"),
        (3410e6, 3475e6, "3410-3475 MHz"), (10_125e6, 10_225e6, "10.125-10.225 GHz")]

# Innovation bands: Full licence plus a Notice of Variation only. OpenHamShack Radio
# has no NoV setting yet, so they are refused with that sentence.
INNOVATION = [(70.5e6, 71.5e6, "70.5-71.5 MHz"), (146e6, 147e6, "146-147 MHz"), (2300e6, 2302e6, "2300-2302 MHz")]

# 431-432 MHz may not be used within 100 km of Charing Cross: O1 Schedule 1,
# the note on the 431-432 MHz row of Tables A, B and C (A p.16, B p.17,
# C p.20), which gives Charing Cross as 51°30'30"N, 00°07'24"W; corroborated
# by the RSGB plan [R1 p.22: "431-432 MHz not available within 100km radius
# of Charing Cross, London"]. Checked in docs/ham/licence-check.md section
# 2. (This used to cite O5, the
# coordination notice, which is not where the exclusion is.) Where the
# station is cannot be worked out - a four-character locator is too coarse
# near the boundary - so it is the operator's setting `nearLondon`, unticked
# by default (Brian, 05/10/2026).
LONDON_EXCLUSION = (431e6, 432e6)
LONDON_CLAUSE = "Ofcom licence, Schedule 1, Tables A-C, 431-432 MHz"


# --- the interface's generic tables (ohscore/licences/__init__.py) ------------
# Each is built from the UK-specific tables above, so the transcription that
# docs/ham/licence-check.md checked stays exactly as it was checked.

# 60 m as a channelled allocation: the signal must lie inside one segment.
CHANNELLED = [{"lo": SIXTY["lo"], "hi": SIXTY["hi"], "label": "60 m", "where": "the eleven UK segments",
               "segments": SIXTY["segments"],
               "limits": {SIXTY["class"]: ((SIXTY["pep"], "PEP"), (SIXTY["eirp"], "EIRP"))},
               "max_bw": SIXTY["max_bw"], "src": "O1 Sch.1 C p.20, Note G p.23"}]

# Refused whatever the class, each with its whole sentence.
REFUSED = ([(a, b, f"{label} is not in the UK amateur licence", "bandplan-r1-uk.md s.1, gaps")
            for a, b, label in GAPS] +
           [(a, b, f"{label} is an innovation band: it needs a Full licence and a Notice of Variation",
             "bandplan-r1-uk.md s.1, innovation bands; licence-check.md s.6") for a, b, label in INNOVATION])

# Refused only where the station meets a condition the operator declares.
# Its answer has been the setting `nearLondon` since 05/10/2026, and still
# is: the guard reads a condition's answer from stationConditions first,
# then from a setting of the same key.
CONDITIONS = [{"key": "nearLondon", "lo": LONDON_EXCLUSION[0], "hi": LONDON_EXCLUSION[1],
               "label": "Station within 100 km of Charing Cross",
               # No by default: Brian's decision of 05/10/2026 (DESIGN-HAM.md),
               # the one condition not defaulted to the restrictive side.
               "default": False,
               "refuse": (f"431-432 MHz may not be used within 100 km of Charing Cross ({LONDON_CLAUSE}); "
                          f"Settings › Licence & plan says this station is"),
               "src": "O1 Sch.1 A p.16, B p.17, C p.20"}]

# The amateur-satellite service: Schedule 1's status column ("Amateur /
# Amateur-Satellite"), as transcribed in bandplan-r1-uk.md section 1. It
# applies to the classes that hold the row, at the row's power. "both": the
# column gives the status alone; "up": Earth to space only; "down": space
# to Earth only.
_SAT_SRC = "O1 Sch.1 status column (bandplan-r1-uk.md s.1)"
SATELLITE = [(a * 1e3, b * 1e3, d, _SAT_SRC) for a, b, d in (
    (7000, 7100, "both"), (14000, 14250, "both"), (18068, 18168, "both"), (21000, 21450, "both"),
    (24890, 24990, "both"), (28000, 29700, "both"), (144000, 146000, "both"), (435000, 438000, "both"),
    (1260000, 1270000, "up"), (2400000, 2450000, "both"), (5650000, 5670000, "up"),
    (5830000, 5850000, "down"), (10450000, 10475000, "both"), (10475000, 10500000, "both"))]

# Reciprocal operation. Ofcom's guidance [O2 s.7.1-7.2.1 pp.26-27, fetched
# 08/10/2026, sha256 89fe14a5...dcd76]: T/R 61-01 covers short visits; a
# HAREC (for T/R 61-02) is "only available to holders of the Amateur Radio
# (Full) Licence"; and abroad "only holders of a Full Licence would be able
# to seek authorisation". Which of a visited country's classes that gives
# is the visited country's to say (its CEPT_VISITOR).
CEPT = {"T/R 61-01": ("full",), "T/R 61-02": ("full",)}
CEPT_SRC = ("Ofcom, Amateur Radio Guidance (updated 14 Oct 2025) s.7.1-7.2.1 pp.26-27, "
            "https://www.ofcom.org.uk/siteassets/resources/documents/manage-your-licence/amateur/"
            "amateur_radio_licence_guidance_for_licensees.pdf")
# A visitor to the UK under T/R 61-01 may operate for under three months
# without a UK licence [O2 s.2.1.4.1 p.5], but the guidance does not say
# which UK class's privileges that carries, so none is mapped: the operator
# chooses.
CEPT_VISITOR: dict = {}

# What the licence says about stations that are not simply an operator at a
# microphone. Shown, not enforced: OpenHamShack does not run unattended stations.
NOTES = [
    ("unattended", "Repeaters, beacons and data stations under 25 W ERP no longer need a Notice of Variation.",
     "O1 cond. 6(12-18), bandplan-r1-uk.md s.1"),
    ("airborne", "Airborne use: Primary bands only, at 500 mW EIRP (not encoded: OpenHamShack is not an airborne "
                 "station).", "O2 s.4.3, bandplan-r1-uk.md s.1"),
]
