"""The Dutch amateur registration (RDI): who may transmit where, at what power.

Source: "Regeling gebruik van frequentieruimte met meldingsplicht 2015"
(BWBR0036375), Bijlage 1, the version in force since 20-06-2024 [W1], as
transcribed in docs/ham/countries/nl.md section 3. Dutch amateurs do not
hold a licence; they register (art. 5-6), and art. 7 binds them to the
limits of Bijlage 1, which is what is encoded here. wetten.overheid.nl has
no page numbers, so rows cite their position in Bijlage 1 (F rows 1-38, N
rows 39-44). Nobody has yet done the line-by-line check the UK had
(docs/ham/licence-check.md): do it against the regulation before relying
on this.

Power is PEP at the stage coupled to the antenna (Bijlage 1 footnote 2),
except 60 m, which the row gives as 15 W e.i.r.p.

There are two categories, N and F; there is no class A (nl.md s.2).

What is left out, and why (nl.md sections 3.1 and 8):
- Rows 8 and 9 overlap as printed (10.10-10.15 MHz no contests; 10.14-10.15
  MHz at most 500 Hz): split at 10.14 MHz, the 500 Hz in EMISSIONS.
- No contests (630 m, 30 m) and no duplex (6 m above 50.5 MHz, 4 m): NOTES,
  as OpenHamShack cannot tell a contest or a duplex contact from any other.
- RDI's announced closures of 2320-2400 MHz and 2355 MHz around events are
  time-limited and change; the guard cannot know them: a NOTE.
- Up to +6 dB by individual permit in primary bands (Gedragslijn ch. VI):
  not encoded, as the UK NoV is not.
"""
from __future__ import annotations

ID = "rdi-2024"
TITLE = "RDI amateur registration (Regeling meldingsplicht 2015, Bijlage 1, 2024)"
SHORT = "Netherlands (RDI)"
AUTHORITY = "Rijksinspectie Digitale Infrastructuur"
COUNTRY = ("NL",)
PLAN = ""
# [W1] in docs/ham/countries/nl.md.
SOURCE = {
    "title": "Regeling gebruik van frequentieruimte met meldingsplicht 2015 (BWBR0036375), Bijlage 1",
    "url": "https://wetten.overheid.nl/BWBR0036375/",
    "version": "Geldend van 20-06-2024 t/m heden (no later version listed on 2026-10-08)",
    "date": "2024-06-20",
    "checked": "2026-10-08",
    "sha256": "759fa7ad689cccc5c0da71f424a20e9c12bea5f2592e2f4e8a3b46bddc59de66",
}
CLASSES = ("nl_n", "nl_f")
CLASS_NAME = {"nl_n": "N", "nl_f": "F"}

_P, _I = "PEP", "EIRP"


def _r(lo_khz, hi_khz, f, n=None, note="", src="", **extras):
    lim = {}
    for cls, v in (("nl_f", f), ("nl_n", n)):
        if v is not None:
            lim[cls] = v if isinstance(v, tuple) else (float(v), _P)
    row = (lo_khz * 1e3, hi_khz * 1e3, lim, note, "W1 Bijlage 1 " + src)
    return row + (extras,) if extras else row


ALLOCATIONS = [
    _r(135.7, 137.8, 400, note="secondary; A1A only (EMISSIONS); 400 W PEP as printed", src="row 1"),
    _r(472, 479, 100, note="secondary; A1A, F1A, G1A, J2A only (EMISSIONS); no contests", src="row 2"),
    _r(1810, 1850, 400, note="primary", src="row 3"),
    _r(1850, 1880, 400, note="secondary", src="row 4"),
    _r(3500, 3800, 400, note="primary", src="row 5"),
    _r(5351.5, 5366.5, (15.0, _I), note="secondary", src="row 6"),
    _r(7000, 7200, 400, 100, note="primary", src="rows 7, 39"),
    _r(10100, 10140, 400, note="secondary; no contests", src="row 8"),
    _r(10140, 10150, 400, note="secondary; no contests; at most 500 Hz (EMISSIONS)", src="rows 8, 9"),
    _r(14000, 14350, 400, 100, note="primary", src="rows 10, 40"),
    _r(18068, 18168, 400, note="primary", src="row 11"),
    _r(21000, 21450, 400, note="primary", src="row 12"),
    _r(24890, 24990, 400, note="primary", src="row 13"),
    _r(28000, 29700, 400, 100, note="primary", src="rows 14, 41"),
    _r(50000, 50500, 120, note="primary (since 20-06-2024)", src="row 15"),
    _r(50500, 52000, 30, note="secondary; no duplex", src="row 16"),
    _r(70000, 70500, 50, note="secondary; no duplex", src="row 17"),
    _r(144000, 146000, 400, 25, note="primary", src="rows 18, 42"),
    _r(430000, 436000, 400, 25, note="primary", src="rows 19, 43"),
    _r(436000, 440000, 400, 25, note="secondary", src="rows 20, 44"),
    _r(1240000, 1300000, 120, note="secondary", src="row 21"),
    _r(2320000, 2400000, 120, note="secondary; closed during RDI-announced events", src="row 22"),
    # "Uitsluitend satellietverkeer (aarde naar ruimte)": no terrestrial use.
    _r(2400000, 2450000, 120, note="secondary; satellite traffic only, Earth to space", src="row 23",
       satellite_only=True),
    _r(3400000, 3410000, 120, note="secondary", src="row 24"),
    _r(5650000, 5850000, 120, note="secondary", src="row 25"),
    _r(10000000, 10500000, 120, note="secondary", src="row 26"),
    _r(24000000, 24050000, 120, note="primary", src="row 27"),
    _r(24050000, 24250000, 120, note="secondary", src="row 28"),
    _r(47000000, 47200000, 120, note="primary", src="row 29"),
    _r(75500000, 76000000, 120, note="primary", src="row 30"),
    _r(76000000, 77500000, 120, note="secondary", src="row 31"),
    _r(77500000, 78000000, 120, note="primary", src="row 32"),
    _r(78000000, 81500000, 120, note="secondary", src="row 33"),
    _r(122250000, 123000000, 120, note="secondary", src="row 34"),
    _r(134000000, 136000000, 120, note="primary", src="row 35"),
    _r(136000000, 141000000, 120, note="secondary", src="row 36"),
    _r(241000000, 248000000, 120, note="secondary", src="row 37"),
    _r(248000000, 250000000, 120, note="primary", src="row 38"),
]

# Emission rules in Bijlage 1's "Bijzondere bepalingen". A1A, F1A, G1A and
# J2A are all telegraphy for aural reception, which is OpenHamShack's CW; no data
# or voice mode is among them.
EMISSIONS = [
    (135.7e3, 137.8e3, {"nl_f": frozenset({"cw"})}, None, "Alleen de klasse A1A", "W1 Bijlage 1 row 1"),
    (472e3, 479e3, {"nl_f": frozenset({"cw"})}, None, "Alleen A1A, F1A, G1A, J2A", "W1 Bijlage 1 row 2"),
    (10140e3, 10150e3, {"nl_f": frozenset({"cw", "ssb", "am", "fm", "digi", "dv", "image"})}, 500.0,
     "Bandbreedte max 500 Hz", "W1 Bijlage 1 row 9"),
]

REFUSED = [
    (1880e3, 2000e3, "The Dutch 160 m allocation ends at 1880 kHz", "W1 Bijlage 1 rows 3-4; nl.md s.3.2"),
    (5250e3, 5351.5e3, "Dutch 60 m use is only 5351.5-5366.5 kHz", "W1 Bijlage 1 row 6; nl.md s.3.2"),
    (5366.5e3, 5450e3, "Dutch 60 m use is only 5351.5-5366.5 kHz", "W1 Bijlage 1 row 6; nl.md s.3.2"),
    (2300e6, 2320e6, "The Dutch 13 cm allocation starts at 2320 MHz", "W1 Bijlage 1 row 22; nl.md s.3.2"),
]

# Row 23 is the only satellite provision in Bijlage 1; IARU satellite
# segments elsewhere are band plan, not law (nl.md s.4).
SATELLITE = [(2400e6, 2450e6, "up", "W1 Bijlage 1 row 23")]

# T/R 61-01 Annex 2 "Netherlands - PA - F" [CT1 p.6]; ECC/REC/(05)06 Annex 2
# "Netherlands - PD - N" [CT2 p.5]; Bijlage 1 footnote 1 equates a foreign
# HAREC with the F exam.
CEPT = {"T/R 61-01": ("nl_f",), "T/R 61-02": ("nl_f",), "ECC/REC (05)06": ("nl_n",)}
CEPT_SRC = ("CEPT T/R 61-01 Annex 2 p.6; ECC/REC/(05)06 Annex 2 p.5; Regeling meldingsplicht 2015 Bijlage 1 "
            "footnote 1")
# (05)06 visitors transmit as PD/ with N privileges (nl.md s.5). The F
# mapping for T/R 61-01 visitors is marked [derived] in the research, so it
# is left for the operator to choose.
CEPT_VISITOR = {"ECC/REC (05)06": "nl_n"}

NOTES = [
    ("contest", "Contests are not permitted on 630 m or 30 m.", "W1 Bijlage 1 rows 2, 8"),
    ("duplex", "Duplex contacts are not permitted on 50.5-52 MHz or 70-70.5 MHz.", "W1 Bijlage 1 rows 16, 17"),
    ("closures", "RDI announces periods when 2320-2400 MHz or single frequencies may not be used around events; "
                 "check its 'Beschikbaarheid frequenties' page before transmitting on 13 cm.",
     "RDI 'Beschikbaarheid frequenties en geplande evenementen' (2026-09-24)"),
    ("power", "F holders may apply to RDI for up to 6 dB more power in primary bands; OpenHamShack applies the "
              "registration's figures.", "RDI Gedragslijn (June 2021) ch. VI"),
]
