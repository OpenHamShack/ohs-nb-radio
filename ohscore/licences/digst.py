"""The Danish amateur rules (Digitaliseringsstyrelsen): who may transmit
where, at what power.

Source: [D1] Bekendtgørelse om anvendelse af radiofrekvenser uden
tilladelse samt om amatørradioprøver og kaldesignaler m.v., BEK nr. 499 af
29. maj 2026, in force 1 July 2026: § 5 and Bilag 4 (pp.13-18), as
transcribed in docs/ham/countries/dk.md section 3. Denmark re-issues the
order about once a year; its amateur annex was unchanged across the last
three, and whether a later one exists could not be checked [UNCONFIRMED]:
re-check before relying on it. The research has not had the line-by-line
check the UK's had (docs/ham/licence-check.md).

Every figure is PEP at the transmitter's final stage (Bilag 4 pkt. 2),
except on 135.7-137.8 and 472-479 kHz, where "ERP" is defined as the PEP
fed to the antenna times the antenna's efficiency. That is neither this
interface's ERP (against a dipole) nor its EIRP, but it never exceeds the
EIRP (efficiency times directivity, directivity at least 1), so EIRP is
used: never laxer than the law [derived]. Spectral width is law (pkt.
3.2): 2.1 kHz below 1810 kHz, 8 kHz to 30 MHz, 16 kHz on 50-146 MHz;
above 146 MHz the band's own width, which the allocation already holds.

Decisions:
- 23 cm changes on 1 January 2029, already law: 1258-1296 MHz goes, and
  1296-1298 MHz drops to 50 W. Dated rows.
- 1298-1300 MHz: 500 W only with an antenna of at least 30 dBi at 15
  degrees elevation or more, otherwise 160 W. OpenHamShack cannot see the
  elevation, so 160 W is the limit; the 500 W case is a NOTE.
- The amateur-satellite table (1.5) gives no direction, so each of its
  rows is "both". From 2029, 1260-1262 MHz becomes an elevation-dependent
  satellite allocation by reference to ECC/DEC/(25)01, whose figures the
  research does not give for Denmark: not encoded, so refused from then.
- Category D may use only factory-built, CE-marked equipment. A condition
  cannot single out one class, so it is a NOTE.
- A visiting CEPT licensee's Danish category is left to the operator: the
  research derives it from the equivalence tables, not from D1.
- Bands are written to 10.5 GHz; the research's 24-250 GHz rows are left
  out (the apps' hardware stops at 5.85 GHz). The Faroes (OY) and
  Greenland (OX) have their own rules, not researched: not covered.
"""
from __future__ import annotations

ID = "digst-2026"
TITLE = "Danish amateur rules (BEK nr. 499 of 29 May 2026, Bilag 4)"
SHORT = "Denmark (Digitaliseringsstyrelsen)"
AUTHORITY = "Digitaliseringsstyrelsen"
COUNTRY = ("DK",)
PLAN = ""
SOURCE = {
    "title": "Bekendtgørelse om anvendelse af radiofrekvenser uden tilladelse samt om amatørradioprøver og "
             "kaldesignaler m.v., BEK nr. 499 af 29/05/2026, Bilag 4",
    "url": "https://www.retsinformation.dk/eli/lta/2026/499/pdf",
    "version": "Udgivet 2 June 2026, in force 1 July 2026; repeals BEK nr. 1423 af 25/11/2025",
    "date": "2026-05-29",
    "checked": "2026-10-08",
    "sha256": "c31d1b18e2e2763adf6ed2ca1844c89329226a4c18482b3a0297a94a96430fe5",
}
CLASSES = ("dk_d", "dk_b", "dk_a")
CLASS_NAME = {"dk_d": "Category D", "dk_b": "Category B", "dk_a": "Category A"}

_P, _I = "PEP", "EIRP"


def _r(lo_khz, hi_khz, a, b, d, note="", src="D1 Bilag 4 1.1 p.13", extras=None):
    """A row in kHz; a, b and d are the categories' limits (None: "0" in
    the table, not permitted). A bare number is W PEP."""
    lim = {}
    for cls, v in (("dk_a", a), ("dk_b", b), ("dk_d", d)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


# Bilag 4 pkt. 2 p.17: on LF/MF "ERP" is PEP times antenna efficiency;
# EIRP bounds it from above (see the docstring) [derived].
_LF = (1.0, _I)
_LF_NOTE = "1 W 'ERP' as Bilag 4 pkt. 2 defines it (PEP x antenna efficiency), held as 1 W EIRP [derived]"
_TO_2028 = {"valid_to": "2028-12-31"}
_FROM_2029 = {"valid_from": "2029-01-01"}

ALLOCATIONS = [
    _r(135.7, 137.8, _LF, _LF, None, _LF_NOTE, "D1 Bilag 4 1.1 p.13, pkt. 2 p.17"),
    _r(472, 479, _LF, _LF, None, _LF_NOTE, "D1 Bilag 4 1.1 p.13, pkt. 2 p.17"),
    _r(1810, 1850, 1000, 100, None),
    _r(1850, 2000, 10, 10, None),
    _r(3500, 3800, 1000, 100, None),
    _r(5250, 5450, 1000, 100, None, "national: the whole of 5250-5450 kHz"),
    _r(7000, 7200, 1000, 100, None),
    _r(10100, 10150, 1000, 100, None),
    _r(14000, 14350, 1000, 100, None),
    _r(18068, 18168, 1000, 100, None),
    _r(21000, 21450, 1000, 100, None),
    _r(24890, 24990, 1000, 100, None),
    _r(28000, 29700, 1000, 100, 50),
    _r(50000, 52000, 1000, 100, 50),
    _r(69887.5, 70512.5, 25, 25, 25, "national edges"),
    _r(144000, 146000, 1000, 100, 50),
    _r(432000, 438000, 1000, 100, 50),
    _r(1240000, 1258000, 250, 100, 50),
    _r(1258000, 1296000, 250, 100, 50, "withdrawn from 1 Jan 2029 (note 1)", "D1 Bilag 4 1.1 p.13-14 note 1",
       _TO_2028),
    _r(1296000, 1298000, 250, 100, 50, "to 31 Dec 2028 (note 2)", "D1 Bilag 4 1.1 p.13-14 note 2", _TO_2028),
    _r(1296000, 1298000, 50, 50, 50, "from 1 Jan 2029 (note 2)", "D1 Bilag 4 1.1 p.13-14 note 2", _FROM_2029),
    _r(1298000, 1300000, 160, 160, 50, "500 W for A and B only with >= 30 dBi at >= 15 degrees (note 3, not "
       "encoded)", "D1 Bilag 4 1.1 p.13-14 note 3"),
    _r(2400000, 2450000, 250, 100, None),
    _r(3400000, 3410000, 250, 100, None),
    _r(5650000, 5850000, 250, 100, None),
    _r(10000000, 10500000, 250, 100, None),
]

# Bilag 4 pkt. 3.2 p.17: spectral width. Every mode class is allowed.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})
_W = "D1 Bilag 4 pkt. 3.2 p.17"


def _em(lo_khz, hi_khz, bw_hz):
    return (lo_khz * 1e3, hi_khz * 1e3, {c: _ALL for c in CLASSES}, float(bw_hz), "", _W)


EMISSIONS = ([_em(135.7, 137.8, 2100), _em(472, 479, 2100)] +
             [_em(a, b, 8000) for a, b in ((1810, 2000), (3500, 3800), (5250, 5450), (7000, 7200),
                                           (10100, 10150), (14000, 14350), (18068, 18168), (21000, 21450),
                                           (24890, 24990), (28000, 29700))] +
             [_em(a, b, 16000) for a, b in ((50000, 52000), (69887.5, 70512.5), (144000, 146000))])

_GAP = "dk.md s.3.2"
REFUSED = [
    (430e6, 432e6, "430-432 MHz is not an amateur band in Denmark", _GAP),
    (438e6, 440e6, "438-440 MHz is not an amateur band in Denmark", _GAP),
    (2300e6, 2400e6, "2300-2400 MHz is not an amateur band in Denmark", _GAP),
]

# Table 1.5 (amateur-satellite, manned stations, p.16), to 10.5 GHz; the
# classes and powers are the allocation rows'.
_SAT = "D1 Bilag 4 1.5 p.16"
SATELLITE = [(a * 1e3, b * 1e3, "both", _SAT) for a, b in (
    (7000, 7100), (14000, 14250), (18068, 18168), (21000, 21450), (24890, 24990), (28000, 29700),
    (144000, 146000), (435000, 438000), (1260000, 1262000), (1262000, 1270000), (2400000, 2450000),
    (3400000, 3410000), (5660000, 5670000), (10450000, 10500000))]

# dk.md s.5: A is the CEPT licence (T/R 61-01 Annex 2 "Denmark OZ A") and
# gets a HAREC (D1 § 15 stk. 2); B is the CEPT Novice (ECC/REC/(05)06 Annex
# 2 "Denmark OZ B"); D is national only.
CEPT = {"T/R 61-01": ("dk_a",), "T/R 61-02": ("dk_a",), "ECC/REC (05)06": ("dk_b",)}
CEPT_SRC = ("BEK nr. 499/2026 § 15 stk. 2, § 16, § 19 stk. 2; CEPT T/R 61-01 Annex 2 (16 Feb 2024) p.5; "
            "ECC/REC/(05)06 Annex 2 p.5")
CEPT_VISITOR: dict = {}

NOTES = [
    ("category-d", "Category D may use only factory-built radio equipment that is not exempt from the radio "
                   "equipment rules (CE-marked): not a home-built transmitter or a software-defined radio used "
                   "as one.", "D1 Bilag 4 pkt. 3.1 nr. 5 p.17"),
    ("supervised", "A Category B holder may use Category A powers, and a Category D holder Category B or A "
                   "frequencies and powers, under the physical supervision of a holder of that category.",
     "D1 Bilag 4 pkt. 3.1 nr. 3-4"),
    ("eme", "On 1298-1300 MHz Categories A and B may use 500 W with an antenna of at least 30 dBi at 15 degrees "
            "elevation or more; OpenHamShack holds 160 W.", "D1 Bilag 4 1.1 note 3"),
    ("identification", "Give the call sign at the start and end of each contact and at least every ten minutes.",
     "D1 Bilag 4 pkt. 3.1 nr. 1"),
    ("encryption", "No encryption on international contacts (including Greenland and the Faroes) or on the "
                   "repeater and satellite bands.", "D1 Bilag 4 pkt. 3.3 nr. 4 p.18"),
    ("unattended", "Beacons, digipeaters and repeaters are limited to listed sub-bands at 100 W (A, B) or 50 W "
                   "(D), 25 W on 4 m.", "D1 Bilag 4 1.2-1.4 pp.14-16"),
]
