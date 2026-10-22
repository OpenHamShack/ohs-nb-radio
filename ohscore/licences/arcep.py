"""The French amateur licence (ARCEP): who may transmit where, at what power.

Source: ARCEP decision 2012-1241 of 2 October 2012 [A0], whose annex
paragraphs 1 and 2 (the band and power tables) were replaced in full by
decision 2019-1412 of 24 September 2019 [A1, pp.3-9]; paragraph 3 (occupied
bandwidth, class 3 emissions) is still A0 p.14. As transcribed in
docs/ham/countries/fr.md section 3. Nobody has yet done the line-by-line
check the UK had (docs/ham/licence-check.md): do it against the PDFs
before relying on this.

Power is "puissance en crête maximale à la sortie de l'émetteur" - PEP at
the transmitter output (RR 1.157) - except 135.7-137.8 kHz, 472-479 kHz and
5351.5-5366.5 kHz, where it is EIRP [A1 p.6 note (1)].

Classes: since 2012 there is one certificate, equivalent to HAREC; the old
classes 1 and 2 keep identical rights, so both are `harec` here. Class 3 is
the legacy novice, no longer issued: 144-146 MHz at 10 W, and only the
emission classes A1A, A2A, A3E, G3E, J3E and F3E [A0 §3 p.14] - no data or
digital voice.

Region: the same decision covers metropolitan France, Corsica, Réunion and
Mayotte (ITU Region 1) and Guadeloupe, Martinique, Guyane,
Saint-Pierre-et-Miquelon, Saint-Barthélemy and Saint-Martin (Region 2). The
rows A1 gives to Region 2 only carry `regions` (2,).

Dated rows: TNRBF note F53b [K1, secondary, corroborated by CEPT's
implementation table] limits 1258-1300 MHz from 27 June 2028 to ECC/DEC/
(25)01 Annex 1. The narrowband figures are encoded from that date, each
the lower of ECC's figure and A1's 120 W (fr.md s.3.1, [derived]).

What is left out, and why (fr.md sections 3.1, 4 and 8):
- ECC/DEC/(25)01's broadband limit (-17 dBW per MHz EIRP above 150 kHz)
  and its elevation-dependent satellite uplink on 1260-1262 MHz cannot be
  expressed by a row: the narrowband -17 dBW EIRP is applied to all of
  1258-1296 MHz, which is never more than either allows.
- Satellite on 438-440 MHz and 3400-3500 MHz is Region 2 only, and a
  SATELLITE row cannot carry a region: left out (a Region 2 station loses
  nothing it can transmit terrestrially).
- Stations above 5 W ERP must be declared to ANFR: a NOTE.
"""
from __future__ import annotations

ID = "arcep-2019"
TITLE = "ARCEP amateur conditions (decision 2012-1241 as amended by 2019-1412)"
SHORT = "France (ARCEP)"
AUTHORITY = "ARCEP"
COUNTRY = ("FR",)
PLAN = ""
# [A1] in docs/ham/countries/fr.md; A0 for paragraph 3.
SOURCE = {
    "title": "ARCEP décision n° 2019-1412 du 24 septembre 2019 modifiant la décision n° 2012-1241 (annexe, "
             "paragraphes 1 et 2)",
    "url": "https://arcep.fr/uploads/tx_gsavis/19-1412.pdf",
    "version": "Decision 2019-1412 of 24 Sep 2019, JORF 13 Feb 2020; with decision 2012-1241 annex paragraph 3 "
               "(sha256 1ab883ea...b6f6fb6)",
    "date": "2019-09-24",
    "checked": "2026-10-08",
    "sha256": "bfe689f456b2f5c8cc8a0f30c552dc67e34d3cd0234869e99cf119e53bb80620",
}
CLASSES = ("classe3", "harec")
CLASS_NAME = {"classe3": "Class 3", "harec": "HAREC"}

_P, _I = "PEP", "EIRP"
_R2 = (2,)


def _r(lo_khz, hi_khz, harec, classe3=None, note="", src="A1 p.4", **extras):
    lim = {"harec": harec if isinstance(harec, tuple) else (float(harec), _P)}
    if classe3 is not None:
        lim["classe3"] = (float(classe3), _P)
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


# ECC/DEC/(25)01 Annex 1 [C3 p.6], from 27 June 2028 (TNRBF note F53b):
# -17 dBW EIRP = 0.02 W, 17 dBW = 50 W [derived: dBW to watts].
_F53B_TO = {"valid_to": "2028-06-26"}
_F53B_FROM = {"valid_from": "2028-06-27"}

ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _I), note="secondary", src="A1 p.3"),
    _r(472, 479, (1.0, _I), note="secondary", src="A1 p.3"),
    _r(1800, 1810, 500, note="Region 2 only", src="A1 p.3", regions=_R2),
    _r(1810, 1850, 500, note="primary", src="A1 p.3"),
    _r(1850, 2000, 500, note="Region 2 only", src="A1 p.3", regions=_R2),
    _r(3500, 3800, 500, note="R1 primary shared; R2 primary to 3750", src="A1 p.3"),
    _r(3800, 4000, 500, note="Region 2 only", src="A1 p.3", regions=_R2),
    _r(5351.5, 5366.5, (15.0, _I), note="secondary; the WRC-15 band only", src="A1 p.3"),
    _r(7000, 7200, 500, note="primary"),
    _r(7200, 7300, 500, note="Region 2 only", regions=_R2),
    _r(10100, 10150, 500, note="secondary"),
    _r(14000, 14350, 500, note="primary"),
    _r(18068, 18168, 500, note="primary"),
    _r(21000, 21450, 500, note="primary"),
    _r(24890, 24990, 500, note="primary"),
    _r(28000, 29700, 250, note="primary"),
    _r(50000, 52000, 120, note="R1 secondary, R2 primary"),
    _r(52000, 54000, 120, note="Region 2 only", regions=_R2),
    _r(144000, 146000, 120, 10, note="primary; class 3 emissions limited (EMISSIONS)", src="A1 p.4, p.6"),
    _r(146000, 148000, 120, note="Region 2 only", regions=_R2),
    _r(220000, 225000, 120, note="Region 2 only", regions=_R2),
    _r(430000, 434000, 120, note="secondary"),
    _r(434000, 440000, 120, note="R1 primary shared, R2 secondary"),
    _r(1240000, 1258000, 120, note="secondary"),
    _r(1258000, 1300000, 120, note="secondary; until ECC/DEC/(25)01 applies on 27 June 2028", **_F53B_TO),
    _r(1258000, 1296000, (0.02, _I), note="from 27 June 2028: ECC/DEC/(25)01 narrowband -17 dBW EIRP [derived]",
       src="A1 p.4; ECC/DEC/(25)01 Annex 1 p.6; TNRBF F53b", **_F53B_FROM),
    _r(1296000, 1298000, 50, note="from 27 June 2028: ECC/DEC/(25)01 17 dBW transmitter power [derived]",
       src="A1 p.4; ECC/DEC/(25)01 Annex 1 p.6; TNRBF F53b", **_F53B_FROM),
    _r(1298000, 1300000, 120, note="from 27 June 2028: ECC 22 dBW, held to A1's 120 W PEP [derived]",
       src="A1 p.4; ECC/DEC/(25)01 Annex 1 p.6; TNRBF F53b", **_F53B_FROM),
    _r(2300000, 2450000, 120, note="secondary", src="A1 p.5"),
    _r(3300000, 3500000, 120, note="Region 2 only", src="A1 p.5", regions=_R2),
    _r(5650000, 5850000, 120, note="secondary", src="A1 p.5"),
    _r(5850000, 5925000, 120, note="Region 2 only", src="A1 p.5", regions=_R2),
    _r(10000000, 10450000, 120, note="secondary", src="A1 p.5"),
    _r(10450000, 10500000, 120, note="secondary, national primary status", src="A1 p.5"),
    _r(24000000, 24050000, 120, note="primary", src="A1 p.5"),
    _r(24050000, 24250000, 120, note="secondary", src="A1 p.5"),
    _r(47000000, 47200000, 120, note="primary", src="A1 p.5"),
    _r(76000000, 77500000, 120, note="secondary", src="A1 p.5"),
    _r(77500000, 78000000, 120, note="primary", src="A1 p.5"),
    _r(78000000, 81500000, 120, note="secondary", src="A1 p.5"),
    _r(122250000, 123000000, 120, note="secondary", src="A1 p.5"),
    _r(134000000, 136000000, 120, note="primary", src="A1 p.5"),
    _r(136000000, 141000000, 120, note="secondary", src="A1 p.5"),
    _r(241000000, 248000000, 120, note="secondary", src="A1 p.5"),
    _r(248000000, 250000000, 120, note="primary", src="A1 p.5"),
]

# A0 §3 p.14: occupied bandwidth at most 6 kHz below 28 MHz, 12 kHz from 28
# to 144 MHz, 20 kHz from 144 to 225 MHz (2 m read as "entre 144 et 225
# MHz"); class 3 only A1A, A2A, A3E, G3E, J3E, F3E - Morse, AM, FM, SSB.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})
_C3 = frozenset({"cw", "am", "fm", "ssb"})
_BW = "A0 annexe §3 p.14"


def _bw(lo_khz, hi_khz, hz, classe3=False):
    per = {"harec": _ALL}
    if classe3:
        per["classe3"] = _C3
    return (lo_khz * 1e3, hi_khz * 1e3, per, float(hz), f"at most {hz / 1e3:g} kHz", _BW)


EMISSIONS = [_bw(lo, hi, 6000) for lo, hi in (
    (135.7, 137.8), (472, 479), (1800, 2000), (3500, 4000), (5351.5, 5366.5), (7000, 7300), (10100, 10150),
    (14000, 14350), (18068, 18168), (21000, 21450), (24890, 24990))] + [
    _bw(28000, 29700, 12000), _bw(50000, 54000, 12000),
    _bw(144000, 146000, 20000, classe3=True), _bw(146000, 148000, 20000), _bw(220000, 225000, 20000)]

REFUSED = [
    (5250e3, 5351.5e3, "French 60 m use is only 5351.5-5366.5 kHz", "A1 p.3; fr.md s.3.1"),
    (5366.5e3, 5450e3, "French 60 m use is only 5351.5-5366.5 kHz", "A1 p.3; fr.md s.3.1"),
    (70e6, 70.5e6, "70-70.5 MHz is not allocated to amateurs in France", "A1 (no row); fr.md s.3.1"),
]

# The amateur-satellite table [A1 pp.7-9]. 5650-5725 MHz "Terre vers
# espace", 5830-5850 MHz "Espace vers Terre"; the rest name no direction.
_SAT = "A1 pp.7-9"
SATELLITE = [(a * 1e3, b * 1e3, d, _SAT) for a, b, d in (
    (7000, 7100, "both"), (14000, 14250, "both"), (18068, 18168, "both"), (21000, 21450, "both"),
    (24890, 24990, "both"), (28000, 29700, "both"), (144000, 146000, "both"), (435000, 438000, "both"),
    (1240000, 1300000, "both"), (2400000, 2415000, "both"), (2415000, 2450000, "both"),
    (5650000, 5725000, "up"), (5830000, 5850000, "down"), (10450000, 10500000, "both"),
    (24000000, 24050000, "both"), (47000000, 47200000, "both"), (76000000, 81500000, "both"),
    (134000000, 141000000, "both"), (241000000, 250000000, "both"))]

# T/R 61-01 Annex 2: "HAREC, class1 and class 2" [C1 p.5]; T/R 61-02
# implemented 01-09-2009 [C2]; ECC/REC/(05)06 "not implemented" [C2]; class 3
# gives no CEPT rights.
CEPT = {"T/R 61-01": ("harec",), "T/R 61-02": ("harec",)}
CEPT_SRC = ("CEPT T/R 61-01 Annex 2 p.5; CEPT ECO implementation tables for T/R 61-01, T/R 61-02 and "
            "ECC/REC/(05)06 (fetched 2026-10-08)")
# A CEPT visitor's French class is marked [derived] in the research: left
# for the operator to choose.
CEPT_VISITOR: dict = {}

NOTES = [
    ("declaration", "A station above 5 W ERP must be declared to ANFR within two months.", "A0 §5.2 p.8; L1 Art. 7"),
    ("operating", "Check that the frequency is clear first, do not use one frequency permanently, and have a power "
                  "indicator. Identify at the start and end, every 15 minutes and on changing frequency.",
     "A1 p.7; A0 Art. 4 p.10"),
    ("pending", "From 27 June 2028, 1258-1300 MHz follows ECC/DEC/(25)01: broadband signals above 150 kHz are "
                "limited to -17 dBW EIRP per MHz, which OpenHamShack does not judge.", "TNRBF note F53b; C3 p.6"),
]
