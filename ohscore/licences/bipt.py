"""The Belgian amateur licence (BIPT): who may transmit where, at what power.

Source: Besluit van de Raad van het BIPT van 24 mei 2019 betreffende de
frequenties, vermogens en transmissiemodi die mogen worden gebruikt door de
radioamateurs, Bijlage 2 (class A p.15, B and C p.16, notes p.17) [B1],
cross-checked by the research against BIPT's current extract (June 2025)
[B2], as transcribed in docs/ham/countries/be.md section 3. Classes come
from KB 18-12-2009 art. 17/1 §3 as amended in 2018 [K1]. Nobody has yet
done the line-by-line check the UK had (docs/ham/licence-check.md).

**Most of this table is refused, deliberately.** The decision gives most
figures as plain "W" and says nowhere - nor does K1 - whether that is PEP,
mean or carrier power, or where it is measured [UNCONFIRMED, be.md s.3 and
s.8]. Read as PEP at the transmitter, a figure that the law meant as ERP
would let a gain antenna radiate more than allowed, so the rule for this
data applies: a figure with no stated reference is encoded with its row
marked unconfirmed, and the guard refuses it until somebody confirms the
reference with BIPT. The figures are kept in the rows so that confirming it
is a one-line change. Only the cells that name a reference are in force:
2200 m (1 W e.u.v. = ERP), 630 m and 600 m (5 W e.i.u.v. = EIRP) and 60 m.

Other decisions (be.md s.3.1, s.8):
- 60 m: the decision says "15 W e.u.v." (ERP); WRC-15 and UBA say 15 W
  EIRP. The research recommends the stricter EIRP, which can never be
  illegal, and that is what is encoded.
- 4 m 69.950 MHz: printed "69,950 - 69,950" with note (7)'s maximum
  bandwidth, which the decision gives as 10 kHz and BIPT's 2025 extract as
  10 Hz [UNCONFIRMED]; the channel is therefore unconfirmed too.
- 8 m (40.66-40.69 MHz) by individual BIPT permit is known only from UBA's
  page [secondary]: refused.
- (D)ATV limits (notes 9 and 10) and the ban on ATV for classes B and C:
  NOTES, as OpenHamShack sends no television.
- The 2024 consultation on 23 cm has no final decision: the 2019 rows stand.
"""
from __future__ import annotations

ID = "bipt-2019"
TITLE = "BIPT amateur licence (Council decision of 24 May 2019)"
SHORT = "Belgium (BIPT)"
AUTHORITY = "BIPT"
COUNTRY = ("BE",)
PLAN = ""
# [B1] in docs/ham/countries/be.md.
SOURCE = {
    "title": "Besluit van de Raad van het BIPT van 24 mei 2019 (frequenties, vermogens en transmissiemodi "
             "radioamateurs), Bijlage 2",
    "url": "https://www.bipt.be/file/cc73d96153bbd5448a56f19d925d05b1379c7f21/"
           "ba05ea9d3611d44667462d979daa834bca246b0c/2019-05-24-ram-besluit.pdf",
    "version": "Decision of 24/05/2019, published 27/05/2019; still listed by BIPT as in force on 2026-10-08",
    "date": "2019-05-24",
    "checked": "2026-10-08",
    "sha256": "30517ef4b1945deb5f357587923860852fcd49a24a68e11d0563485215fce400",
}
CLASSES = ("be_c", "be_b", "be_a")
CLASS_NAME = {"be_c": "Class C", "be_b": "Class B", "be_a": "Class A"}

_P, _E, _I = "PEP", "ERP", "EIRP"
_UNREF = "plain 'W', reference not stated: unconfirmed"


def _r(lo_khz, hi_khz, a, b=None, c=None, note="", src="B1 Bijl.2 pp.15-16", **extras):
    lim = {}
    for cls, v in (("be_a", a), ("be_b", b), ("be_c", c)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, src)
    return row + (extras,) if extras else row


# A row of plain-"W" figures: kept, refused (see the module docstring).
def _u(lo_khz, hi_khz, a, b=None, c=None, note="", src="B1 Bijl.2 pp.15-16"):
    note = f"{note}; {_UNREF}" if note else _UNREF
    return _r(lo_khz, hi_khz, a, b, c, note, src, unconfirmed=True)


ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _E), note="S; 1 W e.u.v.", src="B1 Bijl.2 p.15"),
    _r(472, 479, (5.0, _I), note="S; 5 W e.i.u.v.", src="B1 Bijl.2 p.15"),
    _r(501, 504, (5.0, _I), note="S; A1A only, 100 Hz (note 6)", src="B1 Bijl.2 p.15, note 6 p.17"),
    _u(1810, 1830, 1500, 100, note="S; note 1"),
    _u(1830, 1850, 1500, 100, note="PEX"),
    _u(1850, 2000, 150, 100, note="S"),
    _u(3500, 3800, 1500, 100, 25, note="P"),
    _r(5351.5, 5366.5, (15.0, _I), note="S; printed 15 W e.u.v. (ERP), encoded as the stricter 15 W EIRP",
       src="B1 Bijl.2 p.15"),
    _u(7000, 7100, 1500, 100, 25, note="PEX"),
    _u(7100, 7200, 1500, 100, 25, note="S"),
    _u(10100, 10150, 1500, 100, 25, note="S"),
    _u(14000, 14350, 1500, 100, 25, note="PEX"),
    _u(18068, 18168, 1500, 100, note="PEX"),
    _u(21000, 21450, 1500, 100, 25, note="PEX"),
    _u(24890, 24990, 1500, 100, note="PEX"),
    _u(28000, 29700, 1500, 100, 25, note="PEX"),
    _u(50000, 52000, 200, 100, note="S"),
    _r(69945, 69955, (10.0, _I), note="S; printed 69,950-69,950 with note 7's bandwidth (10 kHz or 10 Hz)",
       src="B1 Bijl.2 p.15, note 7 p.17; B2 p.1", unconfirmed=True),
    _u(70112.5, 70412.5, 50, note="S", src="B1 Bijl.2 p.15"),
    _u(144000, 146000, 1500, 50, 50, note="PEX"),
    _u(430000, 433050, 1500, 50, 50, note="P"),
    _u(433050, 434790, 200, 50, 50, note="P; (D)ATV 200 W EIRP (note 9)"),
    _u(434790, 440000, 1500, 50, 50, note="P"),
    _u(1240000, 1270000, 200, note="S", src="B1 Bijl.2 p.15"),
    _u(1270000, 1300000, 200, note="S; (D)ATV 20 W ERP (note 10)", src="B1 Bijl.2 p.15"),
    _u(2300000, 2450000, 200, note="S; ISM interference must be accepted (note 5)", src="B1 Bijl.2 p.15"),
    _u(5650000, 5725000, 200, note="S"),
    _u(5725000, 5850000, 200, note="S; ISM (note 5)"),
    _u(10000000, 10450000, 200, note="S"),
    _u(10450000, 10500000, 200, note="S"),
    _u(24000000, 24050000, 200, note="PEX"),
    _u(24050000, 24250000, 200, note="S"),
    _u(47000000, 47200000, 200, note="PEX"),
    _u(75500000, 76000000, 200, note="P"),
    _u(76000000, 81000000, 200, note="S"),
    _u(122250000, 123000000, 200, note="S"),
    _u(142000000, 144000000, 200, note="PEX"),
    _u(144000000, 149000000, 200, note="S"),
    _u(241000000, 248000000, 200, note="S"),
    _u(248000000, 250000000, 200, note="PEX"),
]

EMISSIONS = [
    (501e3, 504e3, {"be_a": frozenset({"cw"})}, 100.0, "A1A only; note 6: 100 Hz", "B1 Bijl.2 p.15, note 6 p.17"),
]

REFUSED = [
    (5250e3, 5351.5e3, "Belgian 60 m use is only 5351.5-5366.5 kHz", "B1 Bijl.2 p.15; be.md s.3.2"),
    (5366.5e3, 5450e3, "Belgian 60 m use is only 5351.5-5366.5 kHz", "B1 Bijl.2 p.15; be.md s.3.2"),
    (40.66e6, 40.69e6, "40.66-40.69 MHz needs an individual permit from BIPT, and its conditions were found only on "
                       "UBA's page, not in a BIPT text: OpenHamShack does not transmit there", "be.md s.3.1 (U1)"),
    (70e6, 70.1125e6, "Belgian 4 m use is only 69.950 MHz and 70.1125-70.4125 MHz", "B1 Bijl.2 p.15; be.md s.3.2"),
    (70.4125e6, 70.5e6, "Belgian 4 m use is only 69.950 MHz and 70.1125-70.4125 MHz", "B1 Bijl.2 p.15; be.md s.3.2"),
]

# Notes (2), (3) and (4) [B1 p.17]: satellite use, same status as the band;
# 1260-1270 and 5650-5670 MHz Earth to space only.
_SAT = "B1 Bijl.2 notes 2-4 p.17"
SATELLITE = [(a * 1e3, b * 1e3, d, _SAT) for a, b, d in (
    (7000, 7100, "both"), (14000, 14250, "both"), (18068, 18168, "both"), (21000, 21450, "both"),
    (24890, 24990, "both"), (28000, 29700, "both"), (144000, 146000, "both"), (435000, 438000, "both"),
    (1260000, 1270000, "up"), (2400000, 2450000, "both"), (5650000, 5670000, "up"), (5830000, 5850000, "both"),
    (10450000, 10500000, "both"), (24000000, 24050000, "both"), (47000000, 47200000, "both"),
    (75500000, 81000000, "both"), (122250000, 123000000, "both"), (142000000, 149000000, "both"),
    (241000000, 250000000, "both"))]

# T/R 61-01 Annex 2 "Belgium - ON - A" [CT1 p.5]; ECC/REC/(05)06 Annex 2
# "Belgium - ON - B" [CT2 p.5]; class A is the HAREC certificate [K1 art.
# 17/1 §3 1°]; class C is in neither. Visitors: UBA's page [U2, secondary]
# gives T/R 61-01 visitors class A and (05)06 visitors class B privileges.
CEPT = {"T/R 61-01": ("be_a",), "T/R 61-02": ("be_a",), "ECC/REC (05)06": ("be_b",)}
CEPT_SRC = ("CEPT T/R 61-01 Annex 2 p.5; ECC/REC/(05)06 Annex 2 p.5; KB 18-12-2009 art. 17/1 §3; "
            "UBA 'Visiting Belgium' (secondary)")
CEPT_VISITOR = {"T/R 61-01": "be_a", "ECC/REC (05)06": "be_b"}

NOTES = [
    ("power", "Most Belgian power figures are plain watts with no stated reference (PEP, mean or radiated), so "
              "OpenHamShack refuses those bands until the reference is confirmed with BIPT.", "be.md s.3, s.8"),
    ("atv", "(D)ATV is limited to 200 W EIRP on 433.05-434.79 MHz and 20 W ERP on 1270-1300 MHz, and classes B "
            "and C may not send ATV or D-ATV at all.", "B1 Bijl.2 p.16, notes 9-10 p.17"),
    ("equipment", "Class C holders may not use or keep an external power amplifier.", "B1 §26"),
    ("pending", "BIPT consulted in 2024 on narrowing 23 cm for class A and opening 1296-1300 MHz to class B; no "
                "decision had been published by 2026-10-08.", "B5 pp.6-7"),
]
