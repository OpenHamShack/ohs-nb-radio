"""The Italian amateur licence (MIMIT): who may transmit where, at what power.

Sources, as transcribed in docs/ham/countries/it.md (keys are that file's):
[A26] Allegato 26 of the Codice delle comunicazioni elettroniche, as
replaced by DM 1 March 2021 (MIMIT's "testo vigente"): Art. 11, amateurs
only on the bands the national plan gives them; Art. 15, 500 W PEP for
everything, "fatte salve" lower limits in the plan. [PA]/[PB] and [PN]: the
PNRF approved by DM 31 August 2022, Tables A and B and the notes, which say
which bands amateurs have (and give the only lower limits: 1 W EIRP on
2200 m and 630 m, 15 W EIRP on 60 m). [SPER]: MIMIT's letter to ARI of 31
July 2026 renewing the experimental 160 m, 8 m and 4 m authorisations to
31 December 2026. The ID's year is the PNRF's, the allocation table in
force. The research has not had the line-by-line check the UK's had
(docs/ham/licence-check.md).

Italy's allocation is narrower than IARU Region 1's (it.md s.3.2): no
1810-1830 kHz but experimentally, 70 cm only 430-434 and 435-438 MHz,
23 cm only 1240-1245 and 1270-1298 MHz, 3 cm from 10.3 GHz. There is no
halving on secondary bands, unlike Spain.

Decisions:
- Class N (CEPT Novice) was created by D.Lgs. 48/2024 and DM 26 January
  2026, but its bands and power await a decreto direttoriale that has not
  been published (it.md s.1, s.8). The class is here so an operator can
  choose it, and it has no allocation at all: every transmission is
  refused, and its name says why.
- QO-100: the PNRF lists the amateur-satellite service only in 2440-2450
  MHz, not in 2400-2440 MHz. Whether an uplink to QO-100 on the terrestrial
  amateur allocation is lawful is [UNCONFIRMED] (it.md s.4), so there is no
  SATELLITE row there and QO-100 NB may not transmit to QO-100 under this
  regime; the operator who knows otherwise enters their own licence.
  Terrestrial use of 2400-2440 MHz is allowed.
- The three experimental 4 m channels (SPER) are "single frequencies, 25
  kHz max" at 70.100, 70.200 and 70.300 MHz; whether each frequency is a
  channel's centre or its edge is not stated, so the channels are
  unconfirmed rows (refused), written centred.
- ECC/DEC/(25)01's 23 cm limits are expected with the next PNRF (2027) and
  are not law yet; with no date, they are not encoded.
- Bands are written to 10.5 GHz; the research's 24-250 GHz rows are left
  out (the apps' hardware stops at 5.85 GHz).
"""
from __future__ import annotations

ID = "mimit-2022"
TITLE = "Italian amateur licence (Allegato 26, PNRF 2022)"
SHORT = "Italy (MIMIT)"
AUTHORITY = "Ministero delle Imprese e del Made in Italy (MIMIT)"
COUNTRY = ("IT",)
PLAN = ""
SOURCE = {
    "title": "PNRF (DM 31 agosto 2022), Tabelle A and B and Note; with Allegato 26 al Codice delle comunicazioni "
             "elettroniche (DM 1 marzo 2021) Art. 11 and 15",
    "url": "https://www.mimit.gov.it/images/stories/digitale/03-Tabella_B.docx.pdf",
    "version": "PNRF 2022 (Table A sha256 ffa33a0d...e7a1, Notes f4654ebe...72e1); Allegato 26 testo vigente, "
               "PDF of 12 May 2025 (sha256 aa44a045...25403); SPER prot. U.0187525 of 31 Jul 2026",
    "date": "2022-08-31",
    "checked": "2026-10-08",
    "sha256": "185b1c94d5324e85ce0ab6699c07bf9bb68212b38bdc66c1a850bf313c7c22e5",
}
CLASSES = ("it_n", "it_a")
CLASS_NAME = {"it_n": "Class N (not yet in force)", "it_a": "Class A"}

_P, _I = "PEP", "EIRP"


def _r(lo_khz, hi_khz, limit, note, src, extras=None):
    """A class-A row in kHz; class N has none (see the docstring)."""
    row = (lo_khz * 1e3, hi_khz * 1e3, {"it_a": limit}, note, src)
    return row + (extras,) if extras else row


# A26 Art. 15: 500 W PEP "fed to the antenna feed line", for every band,
# unless the PNRF sets less.
_A = (500.0, _P)
_SPER = {"valid_from": "2026-07-31", "valid_to": "2026-12-31"}

ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _I), "secondary (PNRF note 8)", "PA p.1; PN p.2"),
    _r(472, 479, (1.0, _I), "secondary (PNRF notes 15, 16)", "PA p.2; PN p.2"),
    # SPER: "potenza massima di trasmissione" 10 W, no reference: PEP.
    _r(1810, 1830, (10.0, _P), "experimental, to 31 Dec 2026; 10 W transmitter power, read as PEP", "SPER",
       _SPER),
    _r(1830, 1850, _A, "primary", "PA p.2; A26 Art. 15"),
    _r(3500, 3800, _A, "secondary in Italy", "PA p.4; A26 Art. 15"),
    _r(5351.5, 5366.5, (15.0, _I), "secondary (PNRF note 32B)", "PA p.5; PN p.4"),
    _r(7000, 7100, _A, "primary", "PA p.6; A26 Art. 15"),
    _r(7100, 7200, _A, "primary", "PA p.6; A26 Art. 15"),
    _r(10100, 10150, _A, "secondary", "PA p.6-7; A26 Art. 15"),
    _r(14000, 14250, _A, "primary", "PA p.8; A26 Art. 15"),
    _r(14250, 14350, _A, "primary", "PA p.8; A26 Art. 15"),
    _r(18068, 18168, _A, "primary", "PA p.8-9; A26 Art. 15"),
    _r(21000, 21450, _A, "primary", "PA p.9; A26 Art. 15"),
    _r(24890, 24990, _A, "primary", "PA p.10; A26 Art. 15"),
    _r(28000, 29700, _A, "primary", "PB p.1; A26 Art. 15"),
    _r(40660, 40700, (10.0, _P), "experimental, to 31 Dec 2026; 10 W transmitter power, read as PEP", "SPER",
       _SPER),
    _r(50000, 52000, _A, "secondary (PNRF notes 56, 57)", "PB p.1; PN p.8; A26 Art. 15"),
    _r(70087.5, 70112.5, (10.0, _P), "experimental channel 70.100 MHz: centre or edge not stated", "SPER",
       {**_SPER, "unconfirmed": True}),
    _r(70187.5, 70212.5, (10.0, _P), "experimental channel 70.200 MHz: centre or edge not stated", "SPER",
       {**_SPER, "unconfirmed": True}),
    _r(70287.5, 70312.5, (10.0, _P), "experimental channel 70.300 MHz: centre or edge not stated", "SPER",
       {**_SPER, "unconfirmed": True}),
    _r(144000, 145800, _A, "primary, exclusively amateur (PNRF note 69)", "PB p.2; PN p.9"),
    _r(145800, 146000, _A, "exclusively amateur-satellite, satellite contacts only (PNRF note 69)", "PB p.2; PN p.9",
       {"satellite_only": True}),
    _r(430000, 432000, _A, "secondary", "PB p.5; A26 Art. 15"),
    _r(432000, 434000, _A, "secondary; ISM 433.05-434.79 MHz (PNRF notes 100A, 101)", "PB p.5; A26 Art. 15"),
    _r(435000, 436000, _A, "primary, and amateur-satellite", "PB p.5; A26 Art. 15"),
    _r(436000, 438000, _A, "secondary", "PB p.6; A26 Art. 15"),
    _r(1240000, 1245000, _A, "secondary (PNRF note 116)", "PB p.8; A26 Art. 15"),
    # Note 117 allocates 1267-1270 MHz to the amateur-satellite service,
    # Earth to space; 1260-1267 is a "use" only and is not encoded (it.md
    # s.8). 500 W PEP [derived]: A26 Art. 15 applies to the satellite
    # service too.
    _r(1267000, 1270000, _A, "amateur-satellite only, Earth to space (PNRF note 117); 500 W PEP [derived]",
       "PB p.8; PN p.19", {"satellite_only": True}),
    _r(1270000, 1298000, _A, "secondary (PNRF note 116A)", "PB p.8; A26 Art. 15"),
    _r(2300000, 2400000, _A, "secondary (PNRF notes 154-156)", "PB p.12-13; A26 Art. 15"),
    _r(2400000, 2440000, _A, "secondary; amateur only, no amateur-satellite", "PB p.13; A26 Art. 15"),
    _r(2440000, 2450000, _A, "secondary, and amateur-satellite", "PB p.13; A26 Art. 15"),
    # 5650-5670 MHz: amateur-satellite only (RR 5.282, Earth to space); no
    # terrestrial amateur use. 500 W PEP [derived], as 1267-1270 MHz.
    _r(5650000, 5670000, _A, "amateur-satellite only, Earth to space; 500 W PEP [derived]", "PB p.16",
       {"satellite_only": True}),
    _r(5760000, 5770000, _A, "primary; no protection from foreign FSS earth stations (PNRF note 193)",
       "PB p.16; PN p.29"),
    _r(5830000, 5850000, _A, "secondary, and amateur-satellite (space to Earth)", "PB p.16; A26 Art. 15"),
    _r(10300000, 10450000, _A, "secondary", "PC p.1; A26 Art. 15"),
    _r(10450000, 10500000, _A, "secondary, and amateur-satellite", "PC p.1; A26 Art. 15"),
]

# Gaps inside bands other countries have (it.md s.3.2), whole sentences.
_NOT = "PNRF 2022 (it.md s.3.2)"
REFUSED = [
    (5250e3, 5351.5e3, "Only 5351.5-5366.5 kHz of 60 m is allocated to amateurs in Italy", "PN note 32B; it.md s.3.1"),
    (5366.5e3, 5450e3, "Only 5351.5-5366.5 kHz of 60 m is allocated to amateurs in Italy", "PN note 32B; it.md s.3.1"),
    (434e6, 435e6, "434-435 MHz is not allocated to amateurs in Italy", _NOT),
    (438e6, 440e6, "438-440 MHz is not allocated to amateurs in Italy", _NOT),
    (1245e6, 1267e6, "1245-1267 MHz is not allocated to amateurs in Italy", _NOT),
    (1298e6, 1300e6, "1298-1300 MHz is not allocated to amateurs in Italy", _NOT),
    (5670e6, 5760e6, "5670-5760 MHz is not allocated to amateurs in Italy", _NOT),
    (5770e6, 5830e6, "5770-5830 MHz is not allocated to amateurs in Italy", _NOT),
    (10000e6, 10300e6, "10.0-10.3 GHz is not allocated to amateurs in Italy", _NOT),
]

# SPER's experiments are open to every class-A holder who logs each
# contact on ARI's portal within 24 hours; refused until the operator says
# they take part.
CONDITIONS = [
    {"key": "ariExperiment160m", "lo": 1810e3, "hi": 1830e3, "default": False, "when": False,
     "label": "Taking part in the 1810-1830 kHz experiment (logging on ARI's portal)",
     "refuse": ("1810-1830 kHz is open in Italy only for MIMIT's 2026 propagation experiment, with each contact "
                "logged on ARI's portal within 24 hours; tick it in Settings › Licence & plan if you take part"),
     "src": "SPER"},
    {"key": "ariExperiment8m", "lo": 40.66e6, "hi": 40.70e6, "default": False, "when": False,
     "label": "Taking part in the 40.660-40.700 MHz experiment (logging on ARI's portal)",
     "refuse": ("40.660-40.700 MHz is open in Italy only for MIMIT's 2026 propagation experiment, with each "
                "contact logged on ARI's portal within 24 hours; tick it in Settings › Licence & plan if you "
                "take part"),
     "src": "SPER"},
]

# it.md s.4. Nothing over 2400-2440 MHz: see the docstring (QO-100).
_SAT = "PNRF 2022 (it.md s.4)"
SATELLITE = [
    (7000e3, 7100e3, "both", _SAT), (14000e3, 14250e3, "both", _SAT), (18068e3, 18168e3, "both", _SAT),
    (21000e3, 21450e3, "both", _SAT), (24890e3, 24990e3, "both", _SAT), (28000e3, 29700e3, "both", _SAT),
    (145.8e6, 146e6, "both", "PB p.2; PN note 69"), (435e6, 436e6, "both", "PB p.5"),
    (1267e6, 1270e6, "up", "PB p.8; PN note 117"), (2440e6, 2450e6, "both", "PB p.13"),
    (5650e6, 5670e6, "up", "PB p.16"), (5830e6, 5850e6, "down", "PB p.16"),
    (10450e6, 10500e6, "both", "PC p.1"),
]

# it.md s.5: class A is the CEPT licence (CCE art. 135 c.3) and the patente
# is a HAREC (A26 Art. 2 c.2); a visiting CEPT licensee may operate a
# portable or mobile station, not airborne, under Italian rules (CCE art.
# 140 c.1), which are class A's. Class N's CEPT Novice status is adopted
# but its privileges unpublished, so it is not mapped, and a visiting
# Novice is not authorised [UNCONFIRMED].
CEPT = {"T/R 61-01": ("it_a",), "T/R 61-02": ("it_a",)}
CEPT_SRC = ("CCE art. 135 c.3, 140 c.1; Allegato 26 Art. 2 c.2; CEPT T/R 61-01 (16 Feb 2024) p.6 note 9; "
            "ECO implementation tables (fetched 2026-10-08)")
CEPT_VISITOR = {"T/R 61-01": "it_a"}

NOTES = [
    ("class-n", "Class N's bands and power have not been published (DM 26 January 2026 leaves them to a later "
                "decree): OpenHamShack refuses every transmission for it until they are.", "DMN Art. 1 c.4, Art. 4"),
    ("experimental", "ARI's portal gives CW and narrow modes for 1810-1830 kHz and 3 kHz at most for 40.660-40.700 "
                     "MHz; that is ARI's statement, not MIMIT's letter, and is not enforced.", "it.md s.3 (secondary)"),
    ("unattended", "Unattended repeaters: 10 W ERP at most, callsign every 10 minutes, carrier only while a signal "
                   "is present.", "A26 Art. 9"),
    ("beacon", "Beacons are identified by the callsign followed by /B.", "CCE art. 143 c.4"),
    ("airborne", "Portable and mobile operation excludes aircraft.", "CCE art. 134 c.2"),
    ("identification", "Identify at the start and end of each contact and every 10 minutes.", "A26 Art. 12 c.6"),
]
