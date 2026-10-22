"""The Spanish amateur licence (SETID): who may transmit where, at what power.

Sources, as transcribed in docs/ham/countries/es.md (keys are that file's):
[B1] Orden IET/1311/2013, the Reglamento de uso del dominio público
radioeléctrico por radioaficionados, Anexo I s.3 (power table p.21, its
row spans confirmed from the BOE consolidated text [B1c] of 10 Apr 2015);
[B2] Orden IET/614/2015, which rewrote the Reglamento's Disposición
adicional segunda (the bands needing a special authorisation); [C26] the
CNAF, Orden TDF/732/2026, in force 18 Jul 2026, which says which bands
amateurs have and whether primary or secondary; and the SETID resolutions
[S1] (QO-100, to 26 Dec 2026), [S2] (160 m contests, 2026) and [S3] (8 m,
18 months). The ID's year is the CNAF's: it is the newest instrument, and
it changed 23 cm (UN-122).

No single Spanish table gives an amateur's rights, so each row is put
together from three: the CNAF's status, B1's power for the band, and
B1 s.3.2, which halves that power wherever amateurs are secondary. Every
secondary figure here is therefore [derived] (table value x 50 %), and its
note says so. The research has not had the line-by-line check the UK's
had (docs/ham/licence-check.md); the CNAF pages are scanned images, read
by eye.

Decisions:
- 6 m and 4 m are 300 W PEP: secondary, so half of B1's 600 W. URE says
  600 W; the research's safe reading (es.md s.8) is the law as read.
- 23 cm from 1258 MHz follows ECC/DEC/(25)01 Annex 1 (UN-122, from 18 Jul
  2026), capped at the 500 W EIRP the band would otherwise have. Wideband
  signals there are held to -17 dBW/MHz EIRP, which the guard cannot
  express per MHz: on 1258-1296 MHz the 20 mW total is never above it, and
  on 1296-1300 MHz signals wider than 150 kHz are refused.
- The bands needing SETID's special authorisation (B2) are CONDITIONS,
  one per range, refused until the operator says they hold it.
- 2400-2410 MHz is the QO-100 resolution [S1] alone: satellite only, to
  26 Dec 2026, 1500 W EIRP. A holder of a special authorisation loses
  terrestrial use of that 10 MHz here, and after S1 expires the 10 MHz is
  refused for everyone: one row cannot be S1's (no authorisation, 1500 W
  EIRP) and an authorisation holder's (500 W EIRP) at once, and the
  research gives the holder's terms only through DA2. S1 also requires an antenna of at least 21.5 dBi, which
  no table here can check; it is in NOTES.
- Bands are written to 10.5 GHz; the research's 24-250 GHz rows are left
  out (the apps' hardware stops at 5.85 GHz).
- The EME/meteor-scatter allowance (B1 s.3.3: 1000 W PEP outside towns, in
  the IARU sub-bands) raises power, needs a judgement of where the station
  is, and is not encoded: the band's ordinary limit applies.
"""
from __future__ import annotations

ID = "setid-2026"
TITLE = "Spanish amateur authorisation (Orden IET/1311/2013, CNAF 2026)"
SHORT = "Spain (SETID)"
AUTHORITY = "Secretaría de Estado de Telecomunicaciones e Infraestructuras Digitales (SETID)"
COUNTRY = ("ES",)
PLAN = ""
SOURCE = {
    "title": "Orden IET/1311/2013, Reglamento de uso del dominio público radioeléctrico por radioaficionados, "
             "Anexo I; with Orden IET/614/2015 (DA2), CNAF Orden TDF/732/2026 and the SETID resolutions in force",
    "url": "https://boe.es/boe/dias/2013/07/12/pdfs/BOE-A-2013-7624.pdf",
    "version": "BOE consolidated text of 10 Apr 2015; CNAF in force 18 Jul 2026 "
               "(sha256 70a4714b...e6b1e); resolutions signed 13 Oct 2025 and 4 Dec 2025",
    "date": "2013-07-12",
    "checked": "2026-10-08",
    "sha256": "132cd7359dd474676497c4535e61f6090af400ec67c9f5947822379358547d12",
}
# One class (B1 Art. 5): the Disposición transitoria única gave every older
# EA/EB/EC authorisation the same rights.
CLASSES = ("autorizacion",)
CLASS_NAME = {"autorizacion": "Spanish"}

# Two caps at once are a tuple of (watts, unit) pairs, which limits_of()
# reads as Limits: importing Limit from the package would be circular once
# the package imports this module.
_P, _I = "PEP", "EIRP"
_C = "autorizacion"


def _r(lo_khz, hi_khz, limit, note, src, extras=None):
    """A row in kHz; `limit` is (watts, unit) or a tuple of such pairs, all applying."""
    row = (lo_khz * 1e3, hi_khz * 1e3, {_C: limit}, note, src)
    return row + (extras,) if extras else row


# ECC/DEC/(25)01 Annex 1 figures, in dBW in the Decision [C3 p.6]; the
# conversion to watts is arithmetic.
_M17_DBW = 10 ** (-17 / 10)      # -17 dBW = 19.95 mW
_17_DBW = 10 ** (17 / 10)        # 17 dBW = 50.1 W
_22_DBW = 10 ** (22 / 10)        # 22 dBW = 158.5 W
_UN122 = {"valid_from": "2026-07-18"}

_HALF = "secondary: half of B1's table figure (B1 s.3.2) [derived]"

ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _I), "secondary (UN-108)", "C26 p.98, p.255; B1 p.21"),
    _r(472, 479, (1.0, _I), "secondary (RR 5.80A); the 5 W EIRP more than 800 km from Africa reaches no part of Spain",
       "C26 p.101; B1 p.21"),
    _r(1810, 1830, (500.0, _P), f"{_HALF}, from 1000 W PEP", "C26 p.104; B1 p.21 s.3.2"),
    _r(1830, 1850, (1000.0, _P), "primary", "C26 p.104; B1 p.21"),
    # S2: the 1.8 MHz conditions (B1 Anexo I), for contests only, in 2026.
    _r(1850, 2000, (1000.0, _P), "contests only, 1 Jan - 31 Dec 2026 (SETID resolution of 4 Dec 2025)",
       "S2", {"valid_from": "2026-01-01", "valid_to": "2026-12-31"}),
    _r(3500, 3800, (1000.0, _P), "primary, shared", "C26 p.110; B1 p.21"),
    # Not in B1's table; the CNAF's own figure (RR 5.133B).
    _r(5351.5, 5366.5, (15.0, _I), "secondary (RR 5.133B)", "C26 p.112"),
    _r(7000, 7100, (1000.0, _P), "primary", "C26 p.113; B1 p.21"),
    _r(7100, 7200, (1000.0, _P), "primary", "C26 p.114; B1 p.21"),
    _r(10100, 10150, (500.0, _P), f"{_HALF}, from 1000 W PEP", "C26 p.116; B1 p.21 s.3.2"),
    _r(14000, 14250, (1000.0, _P), "primary", "C26 p.119; B1 p.21"),
    _r(14250, 14350, (1000.0, _P), "primary", "C26 p.119; B1 p.21"),
    _r(18068, 18168, (1000.0, _P), "primary", "C26 p.121; B1 p.21"),
    _r(21000, 21450, (1000.0, _P), "primary", "C26 p.122; B1 p.21"),
    _r(24890, 24990, (1000.0, _P), "primary", "C26 p.123; B1 p.21"),
    _r(28000, 29700, (1000.0, _P), "primary", "C26 p.125; B1 p.21"),
    # S3: 18 months from notification. The notification date is not in the
    # research; signing (13 Oct 2025) plus 18 months is the earliest the
    # authorisation can end, so that is the end used [derived].
    _r(40650, 40750, (100.0, _P), "8 m experimental: fixed stations only, after notice to the Jefatura "
       "Provincial; ends 18 months from notification, taken as from signing [derived]", "S3",
       {"valid_from": "2025-10-13", "valid_to": "2027-04-13"}),
    _r(50000, 52000, (300.0, _P), f"{_HALF}, from 600 W PEP (URE says 600 W; es.md s.8)",
       "C26 p.129, p.252 (UN-100); B1 p.21 s.3.2"),
    _r(70150, 70250, (300.0, _P), f"{_HALF}, from 600 W PEP (URE says 600 W; es.md s.8)",
       "C26 p.130, p.264 (UN-132); B1 p.21 s.3.2"),
    _r(144000, 146000, (600.0, _P), "primary", "C26 p.134; B1 p.21"),
    _r(430000, 432000, (300.0, _P), "primary, shared with radiolocation", "C26 p.146; B1 p.21"),
    _r(432000, 438000, (300.0, _P), "primary, shared; must accept ISM interference on 433.05-434.79 MHz (B1 s.3.4)",
       "C26 p.146; B1 p.21"),
    _r(438000, 440000, (300.0, _P), "primary, shared", "C26 p.146; B1 p.21"),
    _r(1240000, 1258000, (500.0, _I), f"{_HALF}, from 1000 W EIRP", "C26 p.151; B1 p.21 s.3.2"),
    # UN-122 -> ECC/DEC/(25)01 Annex 1: narrowband -17 dBW EIRP on
    # 1258-1296 MHz (the 1260-1270 MHz satellite uplink's higher,
    # elevation-dependent figures are not encoded: the terrestrial figure
    # holds), transmitter power 17 dBW on 1296-1298 and 22 dBW on 1298-1300
    # MHz ("peak envelope power or carrier power", C3 fn 2: PEP is the
    # stricter), each also under the band's 500 W EIRP [derived].
    _r(1258000, 1296000, (_M17_DBW, _I), "secondary; ECC/DEC/(25)01 Annex 1: -17 dBW EIRP [derived: 19.95 mW]",
       "C26 p.151, p.259 (UN-122); C3 p.6", _UN122),
    _r(1296000, 1298000, ((_17_DBW, _P), (500.0, _I)),
       "secondary; ECC/DEC/(25)01 Annex 1: 17 dBW transmitter power [derived: 50.1 W PEP], and 500 W EIRP "
       f"({_HALF})", "C26 p.151, p.259 (UN-122); C3 p.6; B1 p.21 s.3.2", _UN122),
    _r(1298000, 1300000, ((_22_DBW, _P), (500.0, _I)),
       "secondary; ECC/DEC/(25)01 Annex 1: 22 dBW transmitter power [derived: 158.5 W PEP], and 500 W EIRP "
       f"({_HALF})", "C26 p.151, p.259 (UN-122); C3 p.6; B1 p.21 s.3.2", _UN122),
    _r(2300000, 2316000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2)", "C26 p.161; B2; B1 p.21"),
    _r(2316000, 2332000, (500.0, _I), f"{_HALF}; free of special authorisation (DA2)", "C26 p.161; B2; B1 p.21"),
    _r(2332000, 2400000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2)", "C26 p.161; B2; B1 p.21"),
    # S1: QO-100 only, from any authorised station, to 26 Dec 2026.
    _r(2400000, 2410000, (1500.0, _I), "QO-100 uplink only, directional antenna of at least 21.5 dBi "
       "(SETID resolution of 4 Dec 2025)", "S1", {"valid_to": "2026-12-26", "satellite_only": True}),
    _r(2410000, 2450000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2); ISM (B1 s.3.4)",
       "C26 p.161; B2; B1 p.21"),
    _r(5650000, 5700000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2)", "C26 p.170; B2; B1 p.21"),
    _r(5700000, 5720000, (500.0, _I), f"{_HALF}; free of special authorisation (DA2)", "C26 p.170; B2; B1 p.21"),
    _r(5720000, 5760000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2)", "C26 p.170; B2; B1 p.21"),
    _r(5760000, 5762000, (500.0, _I), f"{_HALF}; free of special authorisation (DA2)", "C26 p.170; B2; B1 p.21"),
    _r(5762000, 5850000, (500.0, _I), f"{_HALF}; special authorisation needed (DA2)", "C26 p.170; B2; B1 p.21"),
    _r(10000000, 10450000, (500.0, _I), _HALF, "C26 p.175; B1 p.21"),
    _r(10450000, 10500000, (500.0, _I), f"{_HALF}; also amateur-satellite", "C26 p.175; B1 p.21"),
]

# 1296-1300 MHz: ECC/DEC/(25)01 holds signals wider than 150 kHz to -17
# dBW/MHz EIRP, a density the guard cannot judge, so they are refused.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})
EMISSIONS = [(1296e6, 1300e6, {_C: _ALL}, 150e3,
              "wideband (> 150 kHz) is -17 dBW/MHz EIRP, not expressible: refused", "C3 p.6 (UN-122)")]

# Gaps inside bands other countries have, each a whole sentence (es.md s.3.2).
REFUSED = [
    (5250e3, 5351.5e3, "Only 5351.5-5366.5 kHz of 60 m is open to amateurs in Spain", "es.md s.3, s.3.2; C26 p.112"),
    (5366.5e3, 5450e3, "Only 5351.5-5366.5 kHz of 60 m is open to amateurs in Spain", "es.md s.3, s.3.2; C26 p.112"),
    (70.0e6, 70.15e6, "Only 70.150-70.250 MHz of 4 m is open to amateurs in Spain", "es.md s.3.2; C26 p.264 (UN-132)"),
    (70.25e6, 70.5e6, "Only 70.150-70.250 MHz of 4 m is open to amateurs in Spain", "es.md s.3.2; C26 p.264 (UN-132)"),
    (3400e6, 3410e6, "3.4 GHz is not allocated to amateurs in Spain", "es.md s.3.2"),
]

_SA = "C26 p.161, p.170; B2 (DA2, BOE 10 Apr 2015 p.31216)"
CONDITIONS = [
    {"key": "inContest", "lo": 1850e3, "hi": 2000e3, "default": False, "when": False,
     "label": "Operating in a contest (1850-2000 kHz, 2026)",
     "refuse": ("1850-2000 kHz is open in Spain in 2026 for contests only (SETID resolution of 4 December 2025); "
                "tick it in Settings › Licence & plan if you are operating in a contest"),
     "src": "S2"},
    {"key": "notified8m", "lo": 40.65e6, "hi": 40.75e6, "default": False, "when": False,
     "label": "8 m: fixed station, notified to the Jefatura Provincial",
     "refuse": ("40.650-40.750 MHz may be used only from a fixed station after notice to the Jefatura Provincial "
                "de Inspección de Telecomunicaciones (SETID resolution of 13 October 2025); tick it in Settings › "
                "Licence & plan if you have given notice and are transmitting from a fixed station"),
     "src": "S3"},
    {"key": "holdsSa2300", "lo": 2300e6, "hi": 2316e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 2300-2316 MHz",
     "refuse": ("2300-2316 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
    # 2400-2410 MHz is S1's while it lasts, which needs no special
    # authorisation: these two stop either side of it.
    {"key": "holdsSa2332", "lo": 2332e6, "hi": 2400e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 2332-2400 MHz",
     "refuse": ("2332-2400 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
    {"key": "holdsSa2410", "lo": 2410e6, "hi": 2450e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 2410-2450 MHz",
     "refuse": ("2410-2450 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
    {"key": "holdsSa5650", "lo": 5650e6, "hi": 5700e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 5650-5700 MHz",
     "refuse": ("5650-5700 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
    {"key": "holdsSa5720", "lo": 5720e6, "hi": 5760e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 5720-5760 MHz",
     "refuse": ("5720-5760 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
    {"key": "holdsSa5762", "lo": 5762e6, "hi": 5850e6, "default": False, "when": False,
     "label": "Holds a SETID special authorisation for 5762-5850 MHz",
     "refuse": ("5762-5850 MHz needs a special authorisation from SETID (Orden IET/614/2015); tick it in "
                "Settings › Licence & plan if you hold one"), "src": _SA},
]

# es.md s.4: the CNAF national column's amateur-satellite allocations to
# 10.5 GHz, and S1. 2410-2450 MHz is an uplink only for a holder of the
# special authorisation: the uplink check reads CONDITIONS.
_SAT = "C26 national column (es.md s.4)"
SATELLITE = [
    (7000e3, 7100e3, "both", _SAT), (14000e3, 14250e3, "both", _SAT), (18068e3, 18168e3, "both", _SAT),
    (21000e3, 21450e3, "both", _SAT), (24890e3, 24990e3, "both", _SAT), (28000e3, 29700e3, "both", _SAT),
    (144e6, 146e6, "both", _SAT), (435e6, 438e6, "both", "C26 p.146 (RR 5.282)"),
    (1260e6, 1270e6, "up", "C26 p.151 (RR 5.282)"),
    (2400e6, 2410e6, "up", "S1 (QO-100 only, to 26 Dec 2026)"),
    (2410e6, 2450e6, "both", "C26 p.161 (RR 5.282); B2"),
    (5830e6, 5850e6, "down", "C26 p.170"), (10450e6, 10500e6, "both", "C26 p.175"),
]

# es.md s.5: a Spanish authorisation is a CEPT licence (B1 Art. 11), the
# HAREC is issued (Art. 10), and a visiting T/R 61-01 holder gets all the
# bands on Spanish conditions (Art. 14 b). ECC/REC/(05)06: no information,
# so a CEPT Novice has nothing here.
CEPT = {"T/R 61-01": (_C,), "T/R 61-02": (_C,)}
CEPT_SRC = ("Orden IET/1311/2013 Art. 10, 11, 13-14; CEPT T/R 61-01 (16 Feb 2024) p.7; "
            "ECO implementation tables 925, 926, 1024 (fetched 2026-10-08)")
CEPT_VISITOR = {"T/R 61-01": _C}

NOTES = [
    ("satellite", "The QO-100 resolution requires a directional antenna of at least 21.5 dBi; OpenHamShack does not "
                  "check the antenna's gain against it.", "S1"),
    ("bandwidth", "Modes are free, with bandwidths in line, as a general rule, with the IARU Region 1 band plan.",
     "B1 Anexo I s.3.1 p.21"),
    ("eme", "For EME and meteor scatter, in the IARU sub-bands and outside towns, up to 1000 W PEP may be used; "
            "OpenHamShack holds the band's ordinary limit.", "B1 s.3.3 p.21"),
    ("unattended", "Unattended stations: VHF/UHF at most 50 W output outside towns and 10 W inside, antenna at "
                   "most 6 dBd; HF at most 50 W output.", "B1 Art. 25 h, i"),
    ("portable", "A portable station must be notified to the Jefatura Provincial five days ahead, except for "
                 "non-continuous temporary use of up to 15 consecutive days.", "B1 Art. 17.1"),
]
