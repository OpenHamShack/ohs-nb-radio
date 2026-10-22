# Sweden (SE): the line-by-line check

Checked 2026-10-08 against a fresh download of P1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`pts.py`/`se.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `se.md`? |
|---|---|---|---|
| P1 | `https://pts.se/.../ptsfs-2025-1-...pdf` | `bd9ece78d49dcd45691cbdef8414e5c8fee089cd0f923ee483fcdc73dc4d571d` | yes, exact |

Converted with `pdftotext -layout`, read against
`ohscore/licences/pts.py`'s `ALLOCATIONS`, `REFUSED`, `SATELLITE`, `CEPT`
and `NOTES`, paragraph by paragraph.

Verdict key: **MATCH** / **MISMATCH** / **GAP** (fixed) / **NOTED**.

## 1. The Bilaga index — the complete, authoritative list of paragraphs

P1's own appendix (p.60-61) lists every amateur-radio paragraph in one
table: 28 full-certificate rows (§27 through §259) and 6
entry-certificate rows (§49, §60, §63, §86, §99, §104). This is the
single most useful thing to check first, since it is PTS's own
enumeration, not a derived list — **it confirms nothing was missed and
nothing extra was added**:

- The 22 full-certificate paragraphs within the module's stated
  10.5 GHz scope (§27, 35, 38, 39, 40, 41, 43, 46, 48, 52, 59, 61, 62,
  64, 85, 98, 103, 123, 154, 185, 203, 213) all have a matching
  `ALLOCATIONS` row.
- The 6 remaining full-certificate paragraphs (§226, 235, 248, 256,
  258, 259 — all 24-250 GHz) are correctly absent, matching the
  module's documented "written to 10.5 GHz" scope decision.
- All 6 entry-certificate paragraphs (§49 on 40 m, §60 on 20 m, §63 on
  15 m, §86 on 10 m, §99 on 6 m, §104 on 2 m) have a matching `i=`
  value in `ALLOCATIONS` — and no entry-certificate row exists for any
  other band, matching `insteg`'s six-band restriction exactly.

## 2. Every power figure, read directly rather than from the index

Read the full text of every paragraph (not just the index) to check the
actual figures: §27 (1 W ERP, 2200 m), §35 (1 W EIRP, 630 m), §38-41
(160 m's four steps: 200/10/100/10 W PEP), §43 (200 W, 80 m), §46 (15 W
EIRP, 60 m), §48/49 (200/25 W, 40 m), §52 (150 W, 30 m — the one HF band
not at 200 W), §59/60, §61, §62/63, §64, §85/86, §98/99, §103/104
(200 W / **25 W ERP**, not PEP, for entry-certificate 2 m), §123, §154,
§185 (100 mW PEP, 13 cm), §203, §213. **All MATCH** `ALLOCATIONS`
exactly, including the one figure most likely to be mistyped (30 m's
150 W, deliberately lower than every other full-certificate HF band) and
the one unit that breaks the general PEP pattern (§104's 25 W ERP,
confirmed radiated, not transmitter-output).

## 3. GAP — §27's identification requirement was missing from `NOTES`

§27, read in full: *"Mottagare- och sändarstationens anropssignaler ska
sändas i början och i slutet av varje radioförbindelse. Anropssignalerna
ska också upprepas med korta mellanrum under pågående
radioförbindelse"* — call signs must be sent at the start and end of
every contact, and repeated at short intervals while it continues. This
rule is applied to every other band by the recurring *"I övrigt gäller
27 § tredje–sjätte styckena"* (otherwise §27's third-to-sixth paragraphs
apply) clause attached to almost every row, so it is genuinely universal
law, not a minor aside — but `NOTES` had no identification entry at all
(only ce-marking, unattended, automatic, and permit).

**Fixed**: added an `"identification"` entry to `NOTES`, citing §27.
(The same gap, same fix, was found independently in Norway's `nkom.py`
during this same pass — worth noting since it suggests the omission
pattern, not the specific country, was the common cause.)

## 4. §27's other recurring clauses — already correctly handled

- Automatic-station identification (*"Automatiska amatörradiosändare...
  ska alltid kunna identifieras genom att en anropssignal regelbundet
  sänds..."*) — **MATCH** against the "automatic" note.
- §49's CE-marking and no-automatic/no-remote-control rules for the
  entry certificate — **MATCH** against the "ce-marking" and
  "unattended" notes, word for word.

## 5. CEPT — re-verified against CT1/CT2 directly

*"Sweden[15] SM, SA All[16]"* — **MATCH** against
`CEPT = {"T/R 61-01": ("certifikat",), "T/R 61-02": ("certifikat",)}`;
Sweden is confirmed absent from CT2 (ECC/REC (05)06), matching
`insteg`'s lack of any CEPT entry.

## Summary

- **Rows checked**: all 22 in-scope full-certificate paragraphs and all
  6 entry-certificate paragraphs, cross-checked against P1's own
  authoritative Bilaga index (not just the body text), plus §27's
  recurring clauses and the CEPT Annex entries.
- **Errors fixed**: one gap — §27's identification requirement (call
  sign at start, end, and short intervals throughout) was in the law,
  applied to nearly every band by its own recurring cross-reference
  clause, but missing from `NOTES` entirely; added.
- **UNCONFIRMED rows**: none newly found or resolved. `se.md` section
  8's existing list stands (whether any amendment to PTSFS 2025:1 has
  been published since, the SH call-sign series for `insteg`, PTS's
  individual-permit terms) — nothing here needed re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK, after the fix (`tests/test_licence_se.py` included).
