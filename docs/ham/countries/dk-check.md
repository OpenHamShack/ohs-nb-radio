# Denmark (DK): the line-by-line check

Checked 2026-10-08 against a fresh download of D1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`digst.py`/`dk.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `dk.md`? |
|---|---|---|---|
| D1 | `https://www.retsinformation.dk/eli/lta/2026/499/pdf` | `c31d1b18e2e2763adf6ed2ca1844c89329226a4c18482b3a0297a94a96430fe5` | yes, exact |

Converted with `pdftotext -layout`, read against `ohscore/licences/
digst.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`, `SATELLITE`, `CEPT` and
`NOTES`, row by row against Bilag 4 tables 1.1 and 1.5.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Table 1.1 (manned stations) — all 29 rows

Read in full, cell by cell. **All 29 rows MATCH** `ALLOCATIONS` exactly,
including the row that needed the closest look: **1298-1300 MHz**, where
*both* Category A and Category B print *"500 W3)"* — not just A — with
footnote 3 (*"Antenneforstærkning ≥ 30 dBi og elevation ≥15 grader ellers
160 W"*) applying identically to both. `ALLOCATIONS`'s row correctly
gives both `a=160` and `b=160` as the unconditioned base figure (the
500 W case is left as an unencodable `NOTES` entry, since the guard has
no elevation input) — confirmed this is not an A-only exception as a
quick read of the note text alone might suggest.

The two dated 2029 changes (note 1: *"Frekvensbåndet udgår fra 1. januar
2029"* on 1258-1296 MHz; note 2: *"Sendeeffekten reduceres til 50 W fra
1. januar 2029"* on 1296-1298 MHz) **MATCH** the module's `_TO_2028`/
`_FROM_2029` dated rows exactly.

## 2. Table 1.5 (amateur-satellite) — all 14 in-scope rows

Counted and checked against `SATELLITE`: 7000-7100 kHz, 14.0-14.25,
18.068-18.168, 21.0-21.45, 24.89-24.99 MHz, 28.0-29.7, 144-146, 435-438,
1260-1262, 1262-1270, 2400-2450, 3400-3410, 5660-5670 MHz, 10.45-10.50
GHz — **14 rows, matching `SATELLITE`'s 14 entries exactly**. The table
genuinely has no direction column at all (unlike Germany's or Norway's
equivalent tables), confirming `SATELLITE`'s uniform `"both"` tag is
correct, not a simplification. Note 1 on 1260-1262 MHz (Category D drops
out and power becomes elevation-dependent under ECC/DEC/(25)01 from
2029) and note 2 on 1262-1270 MHz (band withdrawn from 2029) are both
confirmed present in the source and are documented as future work, not
claimed as already handled — `SATELLITE`'s tuple shape has no date
field, so this is an honest limitation already flagged in the module's
docstring, not a silent gap.

## 3. §2 (power reference) and §3.2 (spectral width) — read in full

- *"Ved sendeeffekt forstås spidssendeeffekt (PEP)..."* (PEP at the
  transmitter's final stage) and the LF/MF ERP exception (*"den
  effektivt udstrålede effekt (ERP), det vil sige den til antennen
  tilførte spids sendeeffekt multipliceret med antennens
  virkningsgrad"*) — **MATCH** the module's docstring and its
  EIRP-as-upper-bound derivation exactly.
- pkt 3.2's four bandwidth tiers (2.1 kHz below 1810 kHz, 8 kHz
  1810 kHz-30 MHz, 16 kHz 50-146 MHz, the band's own width above
  146 MHz) — **MATCH** `EMISSIONS` exactly, confirmed against the literal
  numbered list rather than a summary.

## 4. pkt 3.1 (identification, supervision, Category D equipment) and pkt 3.3 (encryption) — read in full

- nr. 1: call sign at the start and end of each contact, *"dog mindst
  hvert tiende minut"* (at least every ten minutes) — **MATCH** the
  "identification" note.
- nr. 3-4: B may use A's power under A's physical supervision; D may use
  B's or A's frequencies/power/equipment under B's or A's supervision —
  **MATCH** the "supervised" note, both halves.
- nr. 5: Category D factory-built equipment only, not exempt from the
  radio-equipment rules — **MATCH** the "category-d" note, word for
  word.
- pkt 3.3 nr. 4: no encryption on international contacts (including
  Greenland and the Faroes) or on repeater (1.4)/satellite (1.5) bands —
  **MATCH** the "encryption" note exactly.

## 5. CEPT — re-verified against CT1/CT2 directly

*"Denmark OZ A"*, *"Faroe Islands OY A"*, *"Greenland OX A"* (T/R 61-01)
and *"Denmark OZ B"*, *"Faroe Islands OY B"*, *"Greenland OX B"*
(ECC/REC (05)06) — **MATCH** `CEPT` exactly. `CEPT_VISITOR` is correctly
left empty: the module's docstring explains this is deliberate (the
visitor-class mapping is derived from the CEPT equivalence tables, not
stated in D1 itself, so the operator chooses) — the same documented
pattern France's `arcep.py` and (partially) the Netherlands' `rdi.py`
already use for the same reason, re-confirmed as consistent rather than
an oversight.

## Summary

- **Rows checked**: all 29 Table 1.1 rows, all 14 in-scope Table 1.5
  rows, §2's power definitions, pkt 3.1's six numbered requirements,
  pkt 3.2's bandwidth tiers, pkt 3.3's encryption rule, and the CEPT
  Annex entries (re-fetched independently).
- **Errors fixed**: none. `ohscore/licences/digst.py` is unchanged — every
  band edge, power figure (including the easy-to-misread 1298-1300 MHz
  row, where both categories, not just A, get the conditional 500 W),
  bandwidth tier and CEPT mapping matched the primary source exactly.
- **UNCONFIRMED rows**: none newly found or resolved. `dk.md` section 8's
  existing list stands (whether a later amendment to BEK 499/2026
  exists, the Danish national 4 m band plan referenced but not found,
  Faroe Islands/Greenland's separate rules) — nothing here needed
  re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_dk.py` included); no code changed.
