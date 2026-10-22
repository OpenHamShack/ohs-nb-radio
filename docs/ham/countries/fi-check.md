# Finland (FI): the line-by-line check

Checked 2026-10-08 against fresh downloads of F1 and F2, re-fetched here
(not reused from the research pass) and confirmed byte-identical to what
`traficom.py`/`fi.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `fi.md`? |
|---|---|---|---|
| F1 | `https://www.finlex.fi/api/media/authority-regulation/1070975/mainPdf/main.pdf` | `d272fe71d37a8b953d5ec349185826fc4439e6ac481ef5f50beff26a8b96258b` | yes, exact |
| F2 | `https://www.finlex.fi/api/media/authority-regulation/545106/mainPdf/main.pdf` | `7c635555b0b78c2930fe1ae6252766689846757c43bef3f2de9ded9f74e2bfd5` | yes, exact |

Converted with `pdftotext -layout`. F1 is a 211-page national allocation
table; rather than re-transcribe all 36 `ALLOCATIONS` rows from it, this
check read F1 and F2's power/bandwidth definitions in full and then
spot-checked the rows most likely to carry a transcription slip — the
mode-dependent HF rows, the two LF/MF EIRP rows, 60 m, the 4 m regional
exclusions, the 144 MHz weak-signal bonus, and the 1240-1300 MHz
case-by-case licence note — against `ohscore/licences/traficom.py`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Power definitions (F2 §3, F1's recurring qualifier) — read in full

F2 §3(4)-(5): PEP (pX) and carrier power (pZ), both *"radiolähettimen...
antennin syöttöjohtoon"* (transmitter power into the antenna feeder) —
**MATCH** the module's docstring. F1's recurring sentence, *"Lukuarvo
tarkoittaa modulaatiohuipputehoa, jos lähetteen kantoaaltoa on
vaimennettu vähintään 6 dB. Muissa tapauksissa lukuarvo tarkoittaa
kantoaaltotehoa"* (the figure means PEP if the carrier is suppressed by
at least 6 dB, otherwise carrier power), appears verbatim on every HF row
checked — confirming `_pc()`'s mode-dependent `Limit` structure (SSB
gets the PEP figure, everything else the carrier figure) reproduces the
law's own qualifier exactly, not a simplification of it.

## 2. Spot-checked `ALLOCATIONS` rows — all MATCH

- **2200 m**: *"Säteilyteho enintään 1 W EIRP"* — **MATCH** `_EIRP1` for
  both classes.
- **160 m** (1810-1850 kHz): *"Lähettimen teho perusluokassa enintään
  120 W ja yleisluokassa enintään 1500 W"* — **MATCH** `_HF` (120/1500).
  Status is printed in capitals (RADIOAMATÖÖRILIIKENNE), confirming
  primary.
- **160 m** (1850-2000 kHz): *"Lähettimen teho enintään 15 W.
  Modulaatiohuipputeho 60 W..."* — **MATCH** `_pc(15, 60)` for both
  classes; status printed lower-case, confirming secondary.
- **60 m**: *"Säteilyteho enintään 15 W EIRP"*, status upper-case
  (primary) — **MATCH** the `(15.0, "EIRP")` row and its "primary (F4)"
  note.
- **4 m beacon segment** (70.000-70.050 MHz): confirmed printed as
  station class *"Amatöörimajakka (ATM) TX"* (beacon TX only), with the
  Lieksa/Ilomantsi/Joensuu/... 13-municipality list and the 50 km
  Russian/Norwegian border rules (25 W, main lobe not 0-180°) quoted
  verbatim — **MATCH** `REFUSED`'s beacon-only entry and both
  `CONDITIONS` entries, including the municipality list reproduced
  character for character.
- **144.000-144.150 MHz weak-signal bonus**: *"Taajuusalueella 144,000 -
  144,150 MHz saa yleisluokassa läheteluokalla A1A sekä digitaalisilla
  lähetelajeilla, joiden kaistanleveys on enintään 3 kHz, käyttää 600 W
  kantoaaltotehoa"* — confirmed this exception is stated for
  **yleisluokka (general) only**, not basic; `_WEAK`'s structure gives
  `perus` the ordinary `_pc(30, 120)` figure unconditionally and only
  gives `yleis` the mode-split 600 W/150 W structure — **MATCH**, the
  asymmetry is in the source, not an encoding choice.
- **1240-1300 MHz**: *"Myös radioamatööriliikennettä taajuusalueella 1240
  - 1300 MHz. Luvat myönnetään tapauskohtaisesti ja määräajaksi"* (also
  amateur traffic in 1240-1300 MHz; licences are granted case by case and
  for a fixed period) — found on every overlapping row (radiolocation,
  radionavigation-satellite, Earth-exploration-satellite) in the table,
  confirming there is no separate amateur-specific row with published
  terms — **MATCH** `REFUSED`'s entry pointing the operator to their own
  licence.

## 3. F2 §16 (bandwidth) — read in full

*"Alle 30 MHz taajuuksilla suurin sallittu kaistanleveys on 8 kHz.
Taajuusalueilla 50 - 146 MHz suurin sallittu kaistanleveys on 18 kHz.
Kuitenkin taajuusalueilla 472 - 479 kHz, 10100 - 10150 kHz ja 70,00 -
70,050 MHz suurin sallittu kaistanleveys on 1 kHz"* — **MATCH**
`EMISSIONS` exactly: the three 1 kHz exceptions, the 8 kHz HF default,
and the 18 kHz VHF default.

## 4. CEPT — re-verified against CT1/CT2 directly

*"Finland OH L, P, T, Y"* (T/R 61-01) — **MATCH** `CEPT = {"T/R 61-01":
("yleis",), "T/R 61-02": ("yleis",)}`. *"Finland OH[1] P"* with footnote
1 (*"Finland has no national licence class equivalent to the CEPT Novice
... Used frequencies and output powers may however under no
circumstances exceed the Finnish elementary novice class guidelines"*,
read in full) — **MATCH** `CEPT_VISITOR = {"ECC/REC (05)06": "perus"}`
exactly: a CEPT Novice visitor is capped at basic-class limits, which is
precisely what the footnote states.

## Summary

- **Rows checked**: F1/F2's power and bandwidth definitions in full, and
  a representative spot-check of the rows most likely to carry a
  transcription error (2200 m, both 160 m rows, 60 m, the 4 m beacon
  segment and its regional conditions, the 144 MHz weak-signal
  asymmetry, and 1240-1300 MHz's case-by-case licence note), plus the
  CEPT Annex entries re-fetched independently. Given F1's size (211
  pages, ~36 `ALLOCATIONS` rows), this is a spot-check of the highest-risk
  rows rather than an exhaustive line-by-line pass across the whole
  table — stated plainly rather than implied otherwise.
- **Errors fixed**: none. `ohscore/licences/traficom.py` is unchanged —
  every figure checked matched exactly, including the one asymmetry most
  likely to be miscoded (the 144 MHz weak-signal bonus applying to the
  general class only, not both).
- **UNCONFIRMED rows**: none newly found or resolved. `fi.md` section 8's
  existing list stands (whether carrier-suppressed digital modes via an
  SSB exciter count as PEP, the old L/T class rights, the apparent
  conflict between T/R 61-01 listing basic-class P and Traficom calling
  only the general class "HAREC") — nothing here needed re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_fi.py` included); no code changed.
