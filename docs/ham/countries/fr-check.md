# France (FR): the line-by-line check

Checked 2026-10-08 against fresh downloads of A1, A0 (for the still-live
paragraph 3) and C3 (the pending ECC Decision), all re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`fr.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `fr.md`? |
|---|---|---|---|
| A1 | `https://arcep.fr/uploads/tx_gsavis/19-1412.pdf` | `bfe689f456b2f5c8cc8a0f30c552dc67e34d3cd0234869e99cf119e53bb80620` | yes, exact |
| A0 | `https://www.arcep.fr/uploads/tx_gsavis/12-1241.pdf` | `1ab883ea2ff444c77b9a058f1da55ad8c670d8a1489fef54f5267875643f6fb6` | yes, exact |
| C3 | `https://docdb.cept.org/download/4810` | `03b8a640cb40e0e2b766f456b0f909282aecb5b850a8f06a059d027cbbad5203` | yes, exact |

Converted with `pdftotext -layout`, read directly against
`ohscore/licences/arcep.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`SATELLITE`, `CEPT` and `NOTES`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. A1's "classes other than classe 3" table — every row, both regions

Read A1's full annex table (both paragraph 1, amateur, and paragraph 2,
amateur-satellite) cell by cell, since the power column is genuinely
merged across many rows (confirmed directly from the PDF's own row
layout, not inferred): 1 W covers the two LF/MF rows, 500 W covers
1800-4000 kHz and 7000-24990 kHz, 15 W covers only 5351.5-5366.5 kHz,
250 W covers only 28-29.7 MHz, and 120 W covers every row from 50 MHz to
250 GHz. **All of it MATCHES** `ALLOCATIONS` exactly, region by region —
every "Non attribuée" (not allocated) Region 1 cell lines up with
`arcep.py`'s `regions=_R2` tag (1800-1810, 1850-2000, 3800-4000,
7200-7300 kHz, 52-54, 146-148, 220-225, 3300-3500, 5850-5925 MHz), and
every status letter (A/B/C/D) matches the note text.

## 2. The classe 3 row

A1's second table, *"Pour la classe de certificat d'opérateur 3"*: a
single row, 144.000-146.000 MHz, primary in both regions, **10 W**. Both
the amateur table and the amateur-satellite table repeat this row
identically. **MATCH** against `ALLOCATIONS`'s `_r(144000, 146000, 120,
10, ...)` (the `10` is the classe3 figure) — classe3 genuinely has no
other row anywhere in A1.

## 3. A0 §3 — occupied bandwidth and classe 3 emissions (still in force)

Read directly, since A1 only replaces A0's paragraphs 1 and 2:
*"La largeur de bande occupée ne doit pas dépasser 6 kHz pour les
fréquences inférieures à 28 MHz, 12 kHz pour les fréquences comprises
entre 28 et 144 MHz et 20 kHz pour les fréquences comprises entre 144 et
225 MHz."* and *"Le titulaire d'un certificat d'opérateur de classe 3 est
autorisé à utiliser uniquement les classes d'émissions A1A, A2A, A3E,
G3E, J3E et F3E."*

- Bandwidth: **MATCH**, `EMISSIONS`'s three tiers (6 kHz below 28 MHz,
  12 kHz on 28-29.7/50-54 MHz, 20 kHz on 144-146/146-148/220-225 MHz)
  reproduce this exactly.
- **NOTED, not a code error**: the text's own two brackets ("28 to
  144 MHz" and "144 to 225 MHz") both touch 144 MHz, so the law itself is
  ambiguous about which bracket 144.000 MHz belongs to. `fr.md` already
  flagged this and chose 20 kHz for 2 m, which `EMISSIONS` encodes; a
  fresh read of the same sentence confirms the ambiguity is in the source
  text, not introduced by the research.
- Classe 3 emissions: *A1A, A2A, A3E, G3E, J3E, F3E* = Morse CW (plain and
  modulated), AM, FM, SSB — no digital, no data, no ATV. **MATCH**
  against `_C3 = frozenset({"cw", "am", "fm", "ssb"})` exactly; no digital
  mode is among the six, confirmed by reading each designator rather than
  assuming.

## 4. The amateur-satellite table — every row, both regions

Read in full. **All rows MATCH** `SATELLITE`, including the two
direction-restricted ones (*"Terre vers espace"* on 5650-5725 MHz →
`"up"`, *"Espace vers Terre"* on 5830-5850 MHz → `"down"`) and every
undirected row defaulting to `"both"`. Two rows the table gives — 438-440
MHz (*"Terre vers espace"*, Region 2 only) and 3400-3500 MHz (Region 2
only, no direction given) — are genuinely absent from `SATELLITE`, exactly
as the module's docstring says: *"a SATELLITE row cannot carry a region:
left out (a Region 2 station loses nothing it can transmit terrestrially)"*
— confirmed as a deliberate, correctly-reasoned omission, not a gap,
since both ranges are already open to ordinary terrestrial TX via the
general `ALLOCATIONS` rows (434-440 MHz and the R2-only 3300-3500 MHz
row) regardless of whether `SATELLITE` separately flags them.

## 5. C3 (ECC/DEC/(25)01) — the pending 23 cm figures, re-verified

Re-fetched independently (not re-read from `fr.md`'s quotes) and checked
every one of the three narrowband figures ARCEP's TNRBF note F53b points
to:

- *"1258-1296 MHz: Maximum value of e.i.r.p. = -17 dBW"* = 0.02 W EIRP —
  **MATCH** against `_r(1258000, 1296000, (0.02, _I), ...)`.
- *"1296-1298 MHz: Maximum transmitter power = 17 dBW"* = 50 W — **MATCH**
  against `_r(1296000, 1298000, 50, ...)`.
- *"1298-1300 MHz: Maximum transmitter power = 22 dBW"* = 158 W, which is
  **higher** than A1's own 120 W PEP cap for this range — `arcep.py`
  correctly takes the lower of the two (120 W, not 158 W), exactly as its
  comment says ("ECC 22 dBW, held to A1's 120 W PEP [derived]"); recomputed
  the dBW-to-watts conversion independently (10^(22/10) ≈ 158.5 W) to
  confirm 120 W is indeed the stricter figure, not a transcription slip.
- The broadband -17 dBW/MHz EIRP figure is correctly left as a `NOTES`
  entry, not an enforced row — confirmed that applying it per-row isn't
  expressible the way `ALLOCATIONS` works (it's a spectral-density limit,
  not a flat power cap), matching the module's docstring reasoning.
- `valid_to`/`valid_from` dates (2028-06-26 / 2028-06-27) match the TNRBF
  wording *"limitée à compter du 27 juin 2028"* (limited from 27 June
  2028) exactly.

## 6. CEPT — re-verified directly against CT1

Re-fetched CT1 (T/R 61-01) independently and confirmed, verbatim: *"France
F HAREC, class1 and class 2"* and the note *"In France from 23 April 2012
there is only one licence class 'HAREC'. Old licence class 1 and 2 holder
keep the benefit of their class."* — **MATCH** against
`CEPT = {"T/R 61-01": ("harec",), "T/R 61-02": ("harec",)}`; `classe3`
correctly has no CEPT entry anywhere (confirmed: CT1's France row names
only one class, HAREC).

## 7. `REFUSED` gaps

- 5250-5351.5 kHz and 5366.5-5450 kHz: confirmed — A1's table has exactly
  one 60 m row, 5351.5-5366.5 kHz. **MATCH**.
- 70-70.5 MHz: confirmed — A1's table jumps from 52-54 MHz (Region 2 only)
  straight to 144-146 MHz; no 70 MHz row anywhere, in either region.
  **MATCH**.

## Summary

- **Rows checked**: every row of A1's two tables (amateur and
  amateur-satellite, both regions, both certificate classes), A0 §3's
  bandwidth and classe-3-emission rules, all three C3 figures for the
  pending 1258-1300 MHz regime, the CEPT Annex 2 entry (re-fetched), and
  both `REFUSED` gaps.
- **Errors fixed**: none. `ohscore/licences/arcep.py` is unchanged — every
  band edge, power figure, region restriction, satellite direction, and
  the pending-2028 dBW-to-watts conversions all matched on independent
  recomputation.
- **UNCONFIRMED rows**: none newly found or resolved. `fr.md` section 8's
  existing list stands (L1's Art. 7/7-2 from a secondary compendium since
  Legifrance blocks scripted fetches, the 144 MHz bandwidth-bracket
  ambiguity, whether ARCEP will separately amend 2012-1241 for 23 cm) —
  nothing here needed re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_fr.py` included); no code changed.
