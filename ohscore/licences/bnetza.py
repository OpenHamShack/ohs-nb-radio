"""The German amateur licence (BNetzA): who may transmit where, at what power.

Source: Amateurfunkverordnung (AFuV), Anlage 1 "Nutzungsbedingungen ..."
as replaced by the Dritte Verordnung zur Änderung der AFuV (BGBl. 2024 I
Nr. 175), in force 24 June 2024 [D1], Part A (the table, "lfd. Nr." rows
1-45, pp.9-11) and Part B (the additional conditions B1-B17, pp.11-12), as
transcribed in docs/ham/countries/de.md section 3. Nobody has yet done the
line-by-line check the UK had (docs/ham/licence-check.md): do it against
the PDF before relying on this.

Units are the table's own: "PEP" is § 2 Nr. 7, the transmitter's peak
envelope power into a resistive load, i.e. at the transmitter output; "ERP"
is § 2 Nr. 8, relative to a half-wave dipole. Classes A and E are almost all
PEP; every class-N figure, and class A's 2200 m, 630 m and 60 m, are ERP.
B11 adds 3.05 W ERP for every class on 1247-1263 MHz on top of the row's
PEP figure, so those rows carry two limits that both apply.

The bandwidth caps of Part B (B1, B3, B4, B6-B9, B16) are law, not band
plan, and are EMISSIONS here.

What is left out, and why (de.md sections 1, 3 and 8):
- B15's weekend uplift on 1850-2000 kHz (A 750 W, E 100 W PEP): the AFuV
  does not define "Wochenende" [UNCONFIRMED], so only the weekday figures
  (75 W and 10 W PEP) are encoded.
- 70-70.5 MHz: no class has it in Anlage 1, the class-A toleration expired
  on 31.12.2025, and whether BNetzA set conditions after Bundesrat-Drucksache
  364/26 is [UNCONFIRMED]: refused.
- B5 (6 m: horizontal polarisation, fixed stations only), B10 (no contests
  on 1850-2000 kHz on weekdays, 2200 m, 30 m), B12/B17 (automatic and remote
  stations) and the BEMFV notification are NOTES: shown, not enforced.
"""
from __future__ import annotations

ID = "bnetza-2024"
TITLE = "BNetzA amateur licence (AFuV Anlage 1, 2024)"
SHORT = "Germany (BNetzA)"
AUTHORITY = "Bundesnetzagentur"
COUNTRY = ("DE",)
PLAN = ""
# [D1] in docs/ham/countries/de.md.
SOURCE = {
    "title": "Amateurfunkverordnung (AFuV), Anlage 1 (BGBl. 2024 I Nr. 175)",
    "url": "https://www.gesetze-im-internet.de/afuv_2005/AFuV.pdf",
    "version": "Stand: zuletzt geändert durch Art. 1 V v. 27.5.2024 I Nr. 175; in force 24 June 2024",
    "date": "2024-06-24",
    "checked": "2026-10-08",
    "sha256": "a384594c4ec77915aa9e354fa13b8d650eaf58148ad1a98d22d7496ec28d6f9d",
}
CLASSES = ("de_n", "de_e", "de_a")
CLASS_NAME = {"de_n": "Class N", "de_e": "Class E", "de_a": "Class A"}

_P, _E = "PEP", "ERP"


def _r(lo_khz, hi_khz, a, e=None, n=None, note="", src=""):
    lim = {}
    for cls, v in (("de_a", a), ("de_e", e), ("de_n", n)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    return (lo_khz * 1e3, hi_khz * 1e3, lim, note, "D1 Anl.1 A " + src)


# B11: 1247-1263 MHz, "die abgestrahlte Leistung auf maximal 3,05 Watt ERP
# beschränkt", for every class, on top of the row's PEP: two limits that
# both apply. Plain (watts, unit) pairs rather than licences.Limit, so this
# module imports nothing from the package that registers it.
def _galileo(watts):
    return ((float(watts), _P), (3.05, _E))


ALLOCATIONS = [
    _r(135.7, 137.8, (1.0, _E), note="secondary", src="row 1 p.9"),
    _r(472, 479, (1.0, _E), note="secondary", src="row 2 p.10"),
    _r(1810, 1850, 750, 100, note="primary", src="row 3 p.10"),
    _r(1850, 1890, 75, 75, note="secondary; weekday figure (B15 weekend uplift not encoded)", src="row 4 p.10"),
    _r(1890, 2000, 10, 10, note="secondary; weekday figure (B15 weekend uplift not encoded)", src="row 5 p.10"),
    _r(3500, 3800, 750, 100, note="primary", src="row 6 p.10"),
    _r(5351.5, 5366.5, (9.14, _E), note="secondary", src="row 7 p.10"),
    _r(7000, 7200, 750, note="primary", src="row 8 p.10"),
    _r(10100, 10150, 150, note="secondary", src="row 9 p.10"),
    _r(14000, 14350, 750, note="primary", src="row 10 p.10"),
    _r(18068, 18168, 750, note="primary", src="row 11 p.10"),
    _r(21000, 21450, 750, 100, note="primary", src="row 12 p.10"),
    _r(24890, 24990, 750, note="primary", src="row 13 p.10"),
    _r(28000, 29700, 750, 100, (10.0, _E), note="primary", src="row 14 p.10"),
    _r(50000, 50400, 750, note="secondary; fixed stations, horizontal polarisation (B5)", src="row 15 p.10"),
    _r(50400, 52000, 25, note="secondary; fixed stations, horizontal polarisation (B5)", src="row 16 p.10"),
    _r(144000, 146000, 750, 75, (6.1, _E), note="primary", src="row 17 p.10"),
    _r(430000, 440000, 750, 75, (6.1, _E), note="primary", src="row 18 p.10"),
    # Rows 19-21 split at B11's 1247 and 1263 MHz.
    _r(1240000, 1247000, 750, 75, note="secondary", src="row 19 p.10"),
    _r(1247000, 1250000, _galileo(750), _galileo(75), note="secondary; 3.05 W ERP (B11)", src="row 19 p.10, B11 p.12"),
    _r(1250000, 1260000, _galileo(750), _galileo(75), note="secondary; 3.05 W ERP (B11)", src="row 20 p.10, B11 p.12"),
    _r(1260000, 1263000, _galileo(750), _galileo(75), note="secondary; 3.05 W ERP (B11)", src="row 21 p.10, B11 p.12"),
    _r(1263000, 1300000, 750, 75, note="secondary", src="row 21 p.10"),
    _r(2320000, 2400000, 75, 5, note="secondary", src="row 22 p.10"),
    _r(2400000, 2450000, 75, 5, note="secondary; also amateur-satellite (B13)", src="row 23 p.10"),
    _r(3400000, 3475000, 75, 5, note="secondary", src="row 24 p.10"),
    _r(5650000, 5670000, 75, 5, note="secondary", src="row 25 p.10"),
    _r(5670000, 5725000, 75, 5, note="secondary", src="row 26 p.10"),
    _r(5725000, 5755000, 75, 5, note="secondary", src="row 27 p.10"),
    _r(5755000, 5830000, 75, 5, note="secondary", src="row 28 p.10"),
    _r(5830000, 5850000, 75, 5, note="secondary", src="row 29 p.10"),
    _r(10000000, 10400000, 75, 5, note="secondary", src="row 30 p.10"),
    _r(10400000, 10450000, 75, 5, note="secondary", src="row 31 p.10"),
    _r(10450000, 10500000, 75, 5, note="secondary", src="row 32 p.10"),
    _r(24000000, 24050000, 75, 5, note="primary", src="row 33 p.10"),
    _r(24050000, 24250000, 75, 5, note="secondary", src="row 34 p.10"),
    _r(47000000, 47200000, 75, 5, note="primary", src="row 35 p.10"),
    _r(76000000, 77500000, 75, 5, note="secondary", src="row 36 p.10"),
    _r(77500000, 78000000, 75, 5, note="secondary", src="row 37 p.10"),
    _r(78000000, 79000000, 75, 5, note="secondary", src="row 38 p.11"),
    _r(79000000, 81000000, 75, 5, note="secondary", src="row 39 p.11"),
    _r(122250000, 123000000, 75, 5, note="secondary", src="row 40 p.11"),
    _r(134000000, 136000000, 75, 5, note="primary", src="row 41 p.11"),
    _r(136000000, 141000000, 75, 5, note="secondary", src="row 42 p.11"),
    _r(241000000, 248000000, 75, 5, note="secondary", src="row 43 p.11"),
    _r(248000000, 250000000, 75, 5, note="primary", src="row 44 p.11"),
]

# Part B's maximum occupied bandwidths, for every class that holds the row,
# whatever the mode. Where a figure depends on the mode (B7-B9: wider for
# television), the narrower general figure is used: OpenHamShack sends no
# television.
_ALL = frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})


def _bw(lo_khz, hi_khz, classes, hz, b):
    # `classes` is a string of class letters ("ae"): each is the class "de_<letter>".
    return (lo_khz * 1e3, hi_khz * 1e3, {f"de_{c}": _ALL for c in classes}, float(hz), f"{b}: {hz:g} Hz",
            f"D1 Anl.1 {b} pp.11-12")


EMISSIONS = [
    _bw(135.7, 137.8, "a", 800, "B1"),
    _bw(472, 479, "a", 800, "B1"),
    _bw(1810, 2000, "ae", 2700, "B3"),
    _bw(3500, 3800, "ae", 2700, "B3"),
    _bw(5351.5, 5366.5, "a", 2700, "B3"),
    _bw(7000, 7200, "a", 2700, "B3"),
    _bw(10100, 10150, "a", 800, "B1"),
    _bw(14000, 14350, "a", 2700, "B3"),
    _bw(18068, 18168, "a", 2700, "B3"),
    _bw(21000, 21450, "ae", 2700, "B3"),
    _bw(24890, 24990, "a", 2700, "B3"),
    _bw(28000, 29000, "aen", 7000, "B4"),
    _bw(29000, 29700, "aen", 40000, "B4"),
    _bw(50000, 52000, "a", 12000, "B16"),
    _bw(144000, 146000, "aen", 40000, "B6"),
    _bw(430000, 440000, "aen", 2e6, "B7"),
    _bw(1240000, 1300000, "ae", 2e6, "B8"),
    _bw(2320000, 2450000, "ae", 10e6, "B9"),
    _bw(3400000, 3475000, "ae", 10e6, "B9"),
    _bw(5650000, 5850000, "ae", 10e6, "B9"),
    _bw(10000000, 10500000, "ae", 10e6, "B9"),
    # Rows 34, 36-39 and 41-42 also carry B9 (10 MHz); rows 33, 35, 43 and
    # 44 do not (checked against the table's own condition column: only
    # "13 17" or "13" there, never "9") - de.md already flagged row 33 as
    # "no bandwidth note", but these five were missing from EMISSIONS
    # until this check, leaving the 10 MHz cap unenforced above 10.5 GHz.
    _bw(24050000, 24250000, "ae", 10e6, "B9"),
    _bw(76000000, 81000000, "ae", 10e6, "B9"),
    _bw(122250000, 123000000, "ae", 10e6, "B9"),
    _bw(134000000, 141000000, "ae", 10e6, "B9"),
]

REFUSED = [
    (5250e3, 5351.5e3, "German 60 m use is only 5351.5-5366.5 kHz", "D1 Anl.1 A row 7 p.10; de.md s.3.2"),
    (5366.5e3, 5450e3, "German 60 m use is only 5351.5-5366.5 kHz", "D1 Anl.1 A row 7 p.10; de.md s.3.2"),
    (70e6, 70.5e6, "70-70.5 MHz is not in the German amateur licence in 2026: the toleration for class A ended on "
                   "31 December 2025, and no new conditions from BNetzA have been confirmed",
     "de.md s.1 pending, s.3.1 (D6, D7, D8)"),
    (2300e6, 2320e6, "The German 13 cm allocation starts at 2320 MHz", "D1 Anl.1 A row 22 p.10; de.md s.3.2"),
]

# B13 [D1 p.12]: the amateur-satellite service may use these ranges; the
# table's status column marks the HF and 2 m rows too (de.md s.3, rows 8-17).
# 1260-1270 and 5650-5670 MHz are Earth to space only, 5830-5850 MHz space
# to Earth only.
_SAT = "D1 Anl.1 B13 p.12"
SATELLITE = [(a * 1e3, b * 1e3, d, _SAT) for a, b, d in (
    (7000, 7100, "both"), (14000, 14250, "both"), (18068, 18168, "both"), (21000, 21450, "both"),
    (24890, 24990, "both"), (28000, 29700, "both"), (144000, 146000, "both"), (435000, 438000, "both"),
    (1260000, 1270000, "up"), (2400000, 2450000, "both"), (5650000, 5670000, "up"),
    (5830000, 5850000, "down"), (10450000, 10500000, "both"), (24000000, 24050000, "both"),
    (47000000, 47200000, "both"), (76000000, 81000000, "both"), (134000000, 141000000, "both"),
    (241000000, 250000000, "both"))]

# BNetzA's page [D3]: T/R 61-01 visitors "dürfen die Betriebsrechte der
# deutschen Klasse A ... wahrnehmen"; ECC (05)06 visitors class E. Class A is
# HAREC; class N is in neither CEPT table [CT1 p.6, CT2 p.5].
CEPT = {"T/R 61-01": ("de_a",), "T/R 61-02": ("de_a",), "ECC/REC (05)06": ("de_e",)}
CEPT_SRC = ("Bundesnetzagentur, 'Amateurfunk' page (fetched 2026-10-08); CEPT T/R 61-01 Annex 2 p.6; "
            "ECC/REC/(05)06 Annex 2 p.5")
CEPT_VISITOR = {"T/R 61-01": "de_a", "ECC/REC (05)06": "de_e"}

NOTES = [
    ("location", "6 m (50-52 MHz) is for fixed stations only, with horizontal polarisation. Shown, not enforced.",
     "D1 Anl.1 B5 p.11"),
    ("contest", "No contests on 2200 m, 30 m or (on weekdays) 1850-2000 kHz. At weekends 1850-2000 kHz allows class "
                "A 750 W and class E 100 W PEP, but the regulation does not define the weekend, so OpenHamShack applies "
                "the weekday figures.", "D1 Anl.1 B10, B15 pp.11-12"),
    ("unattended", "Automatic stations: at most 50 W ERP; remote-controlled stations only as § 13a remote operation "
                   "(class A).", "D1 Anl.1 B10, B12, B17 pp.11-12; § 13a"),
    ("emf", "A fixed station radiating 10 W EIRP or more must be notified to BNetzA before use (BEMFV § 9).",
     "BEMFV § 9(1)"),
    ("notification", "2200 m (135.7-137.8 kHz): the operating site must be notified to BNetzA in writing or "
                      "electronically before use, the transmit antenna must be adequately decoupled from other "
                      "installations, and operation must stop if it interferes with a primary service, including "
                      "in a neighbouring band. Row 1 only (row 2, 630 m, does not carry this condition). Shown, "
                      "not enforced.", "D1 Anl.1 B2 p.11"),
]
