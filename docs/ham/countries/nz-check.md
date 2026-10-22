# New Zealand (NZ): the line-by-line check

Checked 2026-10-08 against a fresh download of G25, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`nz.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `nz.md`? |
|---|---|---|---|
| G25 | `https://www.rsm.govt.nz/.../radiocommunications-regulations-general-user-radio-licence-for-amateur-radio-operators-notice-2025.pdf` | `7d362e49d12b71c6823bde6da4aa68ee3d1c40b8e1a5eddadd41372af6a26ce2` | yes, exact |

Converted with `pdftotext -layout`; this one is short enough (4 printed
pages) to read in full rather than by section. Read directly against
`ohscore/licences/rsm.py`'s `ALLOCATIONS`, `REFUSED`, `SATELLITE`, `CEPT`
and `NOTES`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Clause 3's spectrum table — all 47 rows, counted directly

Counted the table rows in the raw PDF text (47, matching `nz.md`'s own
count of 46-47 depending on whether the RRF API's slightly different
tally is used) and checked every one against `rsm.py`. The table
deliberately prints several overlapping rows at the same dBW figure for
one band (e.g. four rows for 7.0-7.3 MHz, three for 134-141 GHz, four for
241-250 GHz) purely to attach different Special Conditions to different
sub-ranges — `rsm.py` merges these into one `ALLOCATIONS` row per band for
power purposes (since the dBW figure never differs across the merge) and
keeps the narrower sub-ranges separately in `SATELLITE` wherever SC5/SC6
(satellite) apply to less than the full merged range. **All 47 rows
MATCH**, including the two subtle cases checked by hand rather than
assumed:

- **134-141 GHz**: three overlapping rows — 134-136 GHz (no condition),
  134-141 GHz (SC5, SC6), 136-141 GHz (SC1) — meaning satellite use
  actually spans the *entire* 134-141 GHz range, not just one half.
  `SATELLITE`'s `(134000, 141000, "both", ...)` entry correctly uses the
  full range, matching the row that actually carries SC5/SC6, not the
  half-range rows that don't.
- **241-250 GHz**: same shape — satellite (SC5, SC6) is stated for the
  *whole* 241-250 GHz row, while SC1 and the ISM/SRD note (SC2) are
  narrower sub-ranges. `SATELLITE`'s `(241000, 250000, "both", ...)`
  matches the full-range row, not a half.
- **275,000-1,000,000 MHz** ("above 275 GHz"): this is not an invented
  sentinel — the Gazette table itself prints the upper edge as
  `1000000.0000` MHz (1 THz), literally. `ALLOCATIONS`'s last row
  reproduces this exactly; `fcc.py`'s own comment about holding its
  "above 275 GHz" row open "the way rsm.py (NZ) already holds its own
  ... row open" is itself confirmed accurate by this fresh read — NZ's
  row is sourced, not arbitrary.

## 2. Special Conditions 1-8 — re-read in full

All eight, quoted directly: SC1 (accept/no interference), SC2 (ISM/SRD),
SC3 (temporary), SC4 (telemetry/telecommand only), SC5 (satellite
Earth-to-space), SC6 (satellite space-to-Earth), SC7 (800-915 MHz
unwanted-emission limit), SC8 (power is e.i.r.p.) — every row's SC
assignment in `rsm.py`'s notes and in `SATELLITE`'s direction tags
**MATCHES** the table exactly, confirmed row by row rather than taken
from `nz.md`'s transcription.

## 3. `REFUSED` — SC4's telemetry/telecommand-only row

SC4: *"Use is limited to telemetry or telecommand"*, attached only to the
26.95-27.30 MHz row. `REFUSED`'s entry for that range (OpenHamShack does not
do telemetry/telecommand, so it refuses the whole row rather than
guessing at a narrower permitted use) **MATCHES**. The 2300-2396 MHz gap
(13 cm genuinely starts at 2396 MHz in the table, with nothing below it)
and the 1950-2000/3900-4000 kHz band-edge gaps (160 m ends at 1.9500 MHz,
80 m at 3.9000 MHz, confirmed by the table's own printed High (MHz)
column) also **MATCH**.

## 4. GC11 (PEP) and clauses 7/8 (NZ operators vs visitors)

- GC11: *"Except as provided to the contrary in this notice, maximum
  power in dBW is the peak envelope power (PX) of the radio transmitter"*
  — **MATCH** against the module's `_dbw()` default unit and docstring.
- Clause 7 is headed *"Terms, conditions and restrictions applying to New
  Zealand amateur operators"* and clause 8 *"...applying to visiting
  amateur operators"* — two structurally separate clauses. Clause 7(3)
  (the 5-25 MHz new-licensee restriction) sits inside clause 7, confirming
  `rsm.py`'s decision that `nz_visitor_cept` is never subject to it (the
  `_every()` helper always includes `nz_visitor_cept`, independent of the
  `new=` flag that controls `nz_gaoc_new`) — re-verified from the clause
  structure itself, not assumed.
- Clause 8(1)'s CEPT T/R 61-01/61-02 visitor route **MATCHES**
  `CEPT_VISITOR`.

## 5. CEPT — re-fetched the same CT1 PDF independently

Re-used a fresh download of CT1 (already re-verified byte-for-byte
against the DE/FR/CA checks' own re-fetches of the same URL) and grepped
its Annex 4 table for New Zealand specifically: *"New Zealand ZL
General[19] General[19]"*, with footnote 19 reading *"The 'General User
Radio Licence' allow holders of a CEPT amateur radio licence to operate
in New Zealand for up to 90 days on all allocated amateur bands..."* —
**MATCH**, confirming `CEPT = {"T/R 61-01": ("nz_gaoc_new", "nz_gaoc")}`
independently of `nz.md`'s own quote of the same table.

## 6. `NOTES`

- GC2 (call sign every 15 minutes) — **MATCH** against the "identification"
  entry.
- GC7 (*"Amateur beacons, repeaters and fixed links may not be
  established pursuant to this licence"*) — **MATCH** against the
  "repeater" entry.

## Summary

- **Rows checked**: all 47 of clause 3's spectrum rows, all 8 Special
  Conditions, all 11 General Conditions, clauses 7 and 8 in full, and the
  CEPT Annex 4 entry (re-fetched independently).
- **Errors fixed**: none. `ohscore/licences/rsm.py` is unchanged — every
  band edge, dBW figure, Special Condition assignment and merge decision
  matched the Gazette notice exactly on a fresh, independent read,
  including the two places (134-141 GHz, 241-250 GHz) where several
  overlapping rows at the same power had to be disentangled by hand to
  confirm which sub-range genuinely carries satellite permission.
- **UNCONFIRMED rows**: none newly found or resolved. `nz.md` section
  11's existing list stands (whether SC8's e.i.r.p. figure is peak or
  mean, the AREC spot-frequency conditions, unattended-operation rules,
  the GUSL radiation-pattern "HTL" code) — nothing here needed
  re-opening; the two GUSL rows (3300-3400 and 3400-3410 MHz) were not
  re-fetched this pass since they live in RSM's RRF JSON API rather than
  a stable PDF, and `nz.md` already records their specific record IDs,
  dates and hashes from the research pass.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_nz.py` included); no code changed.
