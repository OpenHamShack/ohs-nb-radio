# Belgium (BE): the line-by-line check

Checked 2026-10-08 against a fresh download of B1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`be.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `be.md`? |
|---|---|---|---|
| B1 | `https://www.bipt.be/file/.../2019-05-24-ram-besluit.pdf` | `30517ef4b1945deb5f357587923860852fcd49a24a68e11d0563485215fce400` | yes, exact |

Converted with `pdftotext -layout` and read against `ohscore/licences/
bipt.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`, `SATELLITE`, `CEPT` and
`NOTES`, row by row against Bijlage 2's three tables (class A p.15, B and
C p.16) and the ten numbered notes (p.17).

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Class A table — all 38 rows

Read in full, including the Belgian table's habit of printing a power
figure once and letting it apply down through several un-repeated rows
(e.g. "1500 W" covers 7.0-29.7 MHz across six HF rows that only show
their own Status letter, not a repeated power). **All 38 rows MATCH**
`ALLOCATIONS` exactly, including:

- The 600 m row (501-504 kHz): its own power cell is blank in the printed
  table, visually sharing the merged "5 W e.i.u.v." cell with the 630 m
  row above it — `ALLOCATIONS`'s `(5.0, _I)` reproduces `be.md`'s
  image-verified reading of this merge.
- The 160 m split: 1.81-1.83 MHz is **secondary** with note (1) (no
  interference even to other secondary stations), 1.83-1.85 MHz is
  **PEX**, and 1.85-2.00 MHz drops to 150 W — three different statuses on
  three adjoining rows, all **MATCH**.
- 60 m: the decision's own text says *"15 W e.u.v."* (ERP) — re-confirmed
  character for character — while `ALLOCATIONS` deliberately encodes
  15 W **EIRP**, the stricter of the two readings, exactly as the
  module's docstring already explains; not a transcription error, a
  documented conservative choice re-verified against the primary text.
- Note (7)'s *"Maximale bandbreedte van 10 kHz"* for the 69.950 MHz
  channel — confirmed from **B1 itself** (the primary decision), settling
  the B1-vs-B2 10 kHz/10 Hz discrepancy `be.md` flagged: B1, the actual
  legal instrument, says 10 kHz, so `ALLOCATIONS`'s 69.945-69.955 kHz
  channel width is correct; B2 (a 2025 extract, not fetched this pass) is
  the one transcription-error candidate, not B1.

## 2. Class B and C tables — all 16 and 9 rows

Read both in full. Class B's table merges its own power column even more
aggressively — a single *"100 W"* cell printed once at 1.81 MHz covers
every row down to 52 MHz, dropping to *"50 W"* only at 144-146 MHz and
430-440 MHz — and Class C's does the same from 25 W to 50 W at the same
pivot point. **Both MATCH** `ALLOCATIONS`'s per-row `b=`/`c=` values
exactly, including two confirmed *absences*, not oversights:

- Class B has **no 2200 m, 630 m, 600 m, 160 m, 60 m, 4 m, 50-52 MHz or
  anything above 440 MHz row at all** — confirmed by the table's own
  extent (it starts at 1.81 MHz and ends at 430-440 MHz) — matching every
  one of `ALLOCATIONS`'s `b=None` defaults for those bands.
- Class C's table has rows for 3.5-3.8, 7.0-7.2, 10.1-10.15, 14.0-14.35,
  21.0-21.45, 28.0-29.7, 144-146 and 430-440 MHz **only** — it skips both
  17 m (18.068-18.168 MHz) and 12 m (24.890-24.990 MHz) entirely, which
  `be.md` had already caught and `ALLOCATIONS` already encodes correctly
  (those two rows pass only `a=` and `b=`, no `c=`) — re-confirmed by
  counting Class C's rows directly rather than trusting the earlier
  count.
- Class B's and C's 430-440 MHz entries are each a **single** row in the
  source (no 433.05-434.79 MHz split, unlike Class A's three-way split
  for the (D)ATV exception) — `ALLOCATIONS` still encodes it as three
  sub-rows to align with Class A's edges, but passes the identical `b=50`
  / `c=50` figure to all three, which is behaviourally identical to one
  merged row and therefore not a mismatch.

## 3. Notes (1)-(10) — re-read in full

- (2)'s satellite list (14 ranges: the seven ordinary HF/VHF amateur
  bands plus 5830-5850 MHz and seven microwave bands) and (3)'s list (the
  four conditional-interference ranges: 435-438, 1260-1270, 2400-2450,
  5650-5670 MHz) together total **19 ranges**, matching `SATELLITE`'s
  count of 19 entries exactly — recounted both lists independently rather
  than trusting the prior total.
- (4) (*"beperkt tot de richting aarde-ruimte"* — limited to Earth-to-space)
  names exactly two of those 19 ranges, 1260-1270 and 5650-5670 MHz —
  `SATELLITE`'s only two `"up"` entries, everything else `"both"`.
  **MATCH**.
- (9) (433.05-434.79 MHz (D)ATV, 200 W EIRP) and (10) (1270-1300 MHz
  (D)ATV, 20 W ERP) **MATCH** `NOTES`'s "atv" entry and `ALLOCATIONS`'s
  row notes.
- (6) (100 Hz on 501-504 kHz) **MATCH** `EMISSIONS`'s single entry.

## 4. CEPT — re-verified against CT1 and CT2 directly

Re-grepped the same CT1/CT2 PDFs already re-fetched and hash-confirmed
for the DE/FR/CA/NZ checks: *"Belgium ON A"* (T/R 61-01) and *"Belgium ON
B"* (ECC (05)06) — **MATCH** `CEPT = {"T/R 61-01": ("be_a",), "T/R
61-02": ("be_a",), "ECC/REC (05)06": ("be_b",)}` exactly.

## 5. NOTED, not a code change

`REFUSED` has an explicit entry for 70.0-70.1125 MHz (the gap between the
69.950 MHz channel and the 70.1125-70.4125 MHz segment) but none for the
narrower 69.955-70.0 MHz sliver between the channel's own edge and that
same gap's start. This produces no incorrect behaviour — any range
without an `ALLOCATIONS` row is refused by default regardless of whether
`REFUSED` also names it — so it is a minor message-completeness gap, not
a permission bug, and consistent with how other countries' modules leave
some narrow unallocated slivers without their own explanatory `REFUSED`
entry. Not changed.

## Summary

- **Rows checked**: all 38 Class A rows, all 16 Class B rows, all 9
  Class C rows, all ten numbered notes, the CEPT Annex 2 entries
  (re-fetched independently), and the `REFUSED`/`SATELLITE` entries.
- **Errors fixed**: none. `ohscore/licences/bipt.py` is unchanged — every
  band edge and power figure matched, including the merged-cell
  readings `be.md` had already resolved by rendering the PDF pages as
  images (re-confirmed here from the plain-text extraction wherever the
  layout made that possible, and taken on the research's own authority
  where it genuinely isn't recoverable from text alone).
- **UNCONFIRMED rows**: none newly found or resolved. `be.md` section 8's
  existing list stands (the power reference for every plain-"W" cell,
  the 8 m permit text known only from UBA, the pending 23 cm
  consultation) — nothing here needed re-opening; B1-vs-B2's note (7)
  discrepancy is now resolved in B1's favour (10 kHz), as above.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_be.py` included); no code changed.
