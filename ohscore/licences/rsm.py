"""The New Zealand amateur licence (RSM general user licences): who may
transmit where, at what power.

Source: "Radiocommunications Regulations (General User Radio Licence for
Amateur Radio Operators) Notice 2025", NZ Gazette 2025-go3272, in force
1 July 2025, licence 409957 [G25], clause 3's 46 spectrum rows; and, for
3300-3410 MHz, which the GURL does not cover, the two General User Spectrum
Licences for Amateur Radio Operators [SL1, SL2] - as transcribed in
docs/ham/countries/nz.md (sections 2-8).

New Zealand has no station licence and one operator class, the General
Amateur Operator's Certificate (GAOC). Every qualified amateur transmits
under the one shared GURL. Three classes here all the same:

- `nz_gaoc_new`: a GAOC held less than 3 months, or with fewer than 50
  logged contacts - no transmission between 5 and 25 MHz (G25 cl. 7(3));
- `nz_gaoc`: the GAOC;
- `nz_visitor_cept`: a visitor whose licence meets T/R 61-01 or T/R 61-02,
  up to 90 days (G25 cl. 8(1)), on the same GURL. Clause 7(3) is in the
  clause for New Zealand operators, so it is not applied to visitors.

Power is in dBW. General condition 11: peak envelope power at the
transmitter output, so 30 dBW is 1000 W PEP. Special condition 8 makes a
row's figure e.i.r.p.; whether that is peak or mean the Notice does not
say (nz.md s.11 item 2), so it is judged as peak-envelope e.i.r.p. - the
stricter. Watts here are 10^(dBW/10) [derived: unit conversion].

The Notice lists overlapping rows (7.0-7.1 and 7.0-7.2 MHz) that always
carry the same figure; here they are merged into the union nz.md s.3 gives.
3300-3400 MHz runs to the GUSL's expiry on 30 June 2033 and 3400-3410 MHz
only from 1 July 2026 to 30 June 2027: dated rows. 26.95-27.30 MHz is
telemetry and telecommand only (SC4), which OpenHamShack does not do: refused.

QO-100 is below the horizon from New Zealand; 2400-2450 MHz carries
amateur-satellite both ways (SC5, SC6) for every class.
"""
from __future__ import annotations

import math

ID = "rsm-2025"
TITLE = "RSM General User Radio Licence for Amateur Radio Operators (Gazette 2025-go3272)"
SHORT = "New Zealand (RSM)"
AUTHORITY = "RSM"
COUNTRY = ("NZ",)
PLAN = ""
# [G25] in docs/ham/countries/nz.md.
SOURCE = {
    "title": "Radiocommunications Regulations (General User Radio Licence for Amateur Radio Operators) "
             "Notice 2025",
    "url": "https://www.rsm.govt.nz/assets/Uploads/documents/gazette/radiocommunications-regulations-general-"
           "user-radio-licence-for-amateur-radio-operators-notice-2025.pdf",
    "version": "NZ Gazette 2025-go3272, in force 1 July 2025, licence 409957 (RRF record current, last updated "
               "2026-02-02)",
    "date": "2025-07-01",
    "checked": "2026-10-08",
    "sha256": "7d362e49d12b71c6823bde6da4aa68ee3d1c40b8e1a5eddadd41372af6a26ce2",
}
CLASSES = ("nz_gaoc_new", "nz_gaoc", "nz_visitor_cept")
CLASS_NAME = {"nz_gaoc_new": "GAOC (first 3 months or under 50 contacts)", "nz_gaoc": "GAOC",
              "nz_visitor_cept": "Visiting CEPT"}


def _dbw(dbw, unit="PEP"):
    # Rounded down to the centiwatt, never up: 14 dBW is 25.11 W, not 25.12.
    return (math.floor(10 ** (dbw / 10.0) * 100 + 1e-9) / 100, unit)


PEP30 = _dbw(30)                  # 1000 W PEP at the transmitter (GC11)


def _every(lim, new=True):
    """Every class at `lim`; `new` False leaves out nz_gaoc_new (5-25 MHz)."""
    out = {"nz_gaoc": lim, "nz_visitor_cept": lim}
    if new:
        out["nz_gaoc_new"] = lim
    return out


def _m(lo_mhz, hi_mhz, lim, note, src, extras=None):
    row = (lo_mhz * 1e6, hi_mhz * 1e6, lim, note, src)
    return row + (extras,) if extras else row


_G1, _G2 = "G25 cl. 3 p.1", "G25 cl. 3 p.2"
_NEW = "; not for new GAOC holders (cl. 7(3))"

ALLOCATIONS = [
    _m(0.130, 0.190, _every(_dbw(7, "EIRP")), "2200 m: 7 dBW e.i.r.p.; temporary (SC3)", _G1 + ", SC8"),
    _m(0.472, 0.479, _every(_dbw(14, "EIRP")), "630 m: 14 dBW e.i.r.p.", _G1 + ", SC8"),
    _m(1.800, 1.950, _every(PEP30), "160 m: 30 dBW PEP (SC1)", _G1),
    _m(3.500, 3.900, _every(PEP30), "80 m: 30 dBW PEP (SC1)", _G1),
    _m(5.3515, 5.3665, _every(_dbw(11.8, "EIRP"), new=False), "60 m: 11.8 dBW e.i.r.p." + _NEW,
       _G1 + ", SC8; cl. 7(3)"),
    _m(7.000, 7.300, _every(PEP30, new=False), "40 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(10.100, 10.150, _every(PEP30, new=False), "30 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(14.000, 14.350, _every(PEP30, new=False), "20 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(18.068, 18.168, _every(PEP30, new=False), "17 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(21.000, 21.450, _every(PEP30, new=False), "15 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(24.890, 24.990, _every(PEP30, new=False), "12 m: 30 dBW PEP" + _NEW, _G1 + "; cl. 7(3)"),
    _m(28.000, 29.700, _every(PEP30), "10 m: 30 dBW PEP", _G1),
    _m(50, 54, _every(PEP30), "6 m: 30 dBW PEP (SC1 above 51 MHz)", _G1),
    _m(144, 148, _every(PEP30), "2 m: 30 dBW PEP (SC1 above 146 MHz)", _G1),
    _m(430, 440, _every(PEP30), "70 cm: 30 dBW PEP (SC1; 433.05-434.79 MHz ISM/SRD)", _G1 + "-2"),
    _m(915, 928, _every(_dbw(14, "EIRP")), "33 cm: 14 dBW e.i.r.p. (ISM/SRD; SC7 out-of-band limit)",
       _G2 + ", SC8"),
    _m(1240, 1300, _every(PEP30), "23 cm: 30 dBW PEP (SC1)", _G2),
    _m(2396, 2450, _every(PEP30), "13 cm: 30 dBW PEP (ISM/SRD; amateur-satellite 2400-2450)", _G2),
    _m(3300, 3400, _every(PEP30), "9 cm, general user spectrum licence: secondary, opportunistic, may be "
       "cancelled", "GUSL 404591 (SL1)", {"valid_from": "2023-07-01", "valid_to": "2033-06-30"}),
    _m(3400, 3410, _every(PEP30), "9 cm, general user spectrum licence 1 July 2026 to 30 June 2027 only",
       "GUSL 435381 (SL2)", {"valid_from": "2026-07-01", "valid_to": "2027-06-30"}),
    _m(5650, 5850, _every(PEP30), "5 cm: 30 dBW PEP (ISM/SRD)", _G2),
    _m(10000, 10500, _every(PEP30), "3 cm: 30 dBW PEP (SC1)", _G2),
    _m(24000, 24250, _every(PEP30), "1.2 cm: 30 dBW PEP", _G2),
    _m(47000, 47200, _every(PEP30), "6 mm: 30 dBW PEP", _G2),
    _m(76000, 81000, _every(PEP30), "4 mm: 30 dBW PEP (SC1)", _G2),
    _m(122250, 123000, _every(PEP30), "2.4 mm: 30 dBW PEP (SC1)", _G2),
    _m(134000, 141000, _every(PEP30), "2.1 mm: 30 dBW PEP", _G2),
    _m(241000, 250000, _every(PEP30), "1.2 mm: 30 dBW PEP", _G2),
    _m(275000, 1000000, _every(PEP30), "above 275 GHz: 30 dBW PEP; temporary (SC3)", _G2),
]

REFUSED = [
    (1.950e6, 2.000e6, "160 m in New Zealand ends at 1950 kHz (GURL 2025, clause 3).", "nz.md s.3, gaps"),
    (3.900e6, 4.000e6, "80 m in New Zealand ends at 3900 kHz (GURL 2025, clause 3).", "nz.md s.3, gaps"),
    (5.3200e6, 5.3228e6, "5320 kHz is an AREC spot frequency for AREC activities under AREC call signs, not an "
                         "amateur band, so OpenHamShack does not transmit there.", "nz.md s.3 exceptions, s.11 item 7"),
    (5.3950e6, 5.3978e6, "5395 kHz is an AREC spot frequency for AREC activities under AREC call signs, not an "
                         "amateur band, so OpenHamShack does not transmit there.", "nz.md s.3 exceptions, s.11 item 7"),
    (26.95e6, 27.30e6, "26.95-27.30 MHz is open to amateurs for telemetry and telecommand only (GURL 2025, "
                       "special condition 4), so OpenHamShack does not transmit there.", "G25 cl. 3 p.1, SC4"),
    (614e6, 622e6, "614-622 MHz is not an amateur band: only NZART's licensed ATV repeater sites use it.",
     "nz.md s.3 exceptions"),
    (2300e6, 2396e6, "13 cm in New Zealand starts at 2396 MHz: 2300-2396 MHz is a mobile management right.",
     "nz.md s.3, gaps"),
    (3410e6, 3500e6, "3410-3500 MHz is not open to New Zealand amateurs.", "nz.md s.3, gaps"),
]

# Amateur-satellite: SC5 (Earth-to-space) and SC6 (space-to-Earth) rows of
# G25, and SL2's SC2/SC3 for 3400-3410 MHz (nz.md s.6).
SATELLITE = [(a * 1e6, b * 1e6, d, s) for a, b, d, s in (
    (7.0, 7.1, "both", _G1), (14.0, 14.25, "both", _G1), (18.068, 18.168, "both", _G1),
    (21.0, 21.45, "both", _G1), (24.89, 24.99, "both", _G1), (28.0, 29.7, "both", _G1),
    (144, 146, "both", _G1), (435, 438, "both", _G2), (1260, 1270, "up", _G2), (2400, 2450, "both", _G2),
    (3400, 3410, "both", "GUSL 435381 (SL2) SC2, SC3"), (5650, 5670, "up", _G2), (5830, 5850, "down", _G2),
    (10450, 10500, "both", _G2), (24000, 24050, "both", _G2), (47000, 47200, "both", _G2),
    (76000, 81000, "both", _G2), (134000, 141000, "both", _G2), (241000, 250000, "both", _G2))]

# CEPT T/R 61-01 Annex 4 (nz.md s.8): the GAOC ("General") is the CEPT
# licence; a visitor whose licence meets T/R 61-01 or T/R 61-02 operates
# under the GURL for up to 90 days.
CEPT = {"T/R 61-01": ("nz_gaoc_new", "nz_gaoc")}
CEPT_SRC = "CEPT T/R 61-01 (18 Oct 2024) Annex 4 pp.10-11 and footnote 19; G25 cl. 8(1)"
CEPT_VISITOR = {"T/R 61-01": "nz_visitor_cept", "T/R 61-02": "nz_visitor_cept"}

NOTES = [
    ("repeater", "Repeaters, beacons and fixed links may not be set up under the GURL: each needs its own radio "
                 "licence.", "G25 cl. 6(7)"),
    ("identification", "Send the call sign at least once every 15 minutes during communications.", "G25 cl. 6(2)"),
    ("unattended", "No rule on unattended automatic operation was found; treat it as needing an individual "
                   "licence.", "nz.md s.6, s.11 item 4"),
    ("visitors", "A visitor may operate for up to 90 days, with ZL before or after the home call; a longer stay "
                 "needs RSM's written approval.", "G25 cl. 8; PIB 46 s.3.5.2"),
    ("9 cm", "3300-3410 MHz is used opportunistically under general user spectrum licences that RSM may cancel "
             "at any time; listen first.", "RSM letter of 2 June 2023 (L34)"),
]
