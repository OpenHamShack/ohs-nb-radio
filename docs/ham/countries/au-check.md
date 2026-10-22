# Australia (AU): the line-by-line check

Checked 2026-10-08 against a fresh download of CL, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`au.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `au.md`? |
|---|---|---|---|
| CL | `https://legislation.gov.au/F2023L01648/asmade/2023-12-12/text/original/pdf` | `50036cf5e634e1e66922ef912b064f532919759063ab0b8f1d5570e812ab9f1c` | yes, exact |

Converted with `pdftotext -layout`, read directly against
`ohscore/licences/acma.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`CONDITIONS`, `SATELLITE`, `CEPT` and `NOTES`, row by row against
Schedule 2 Tables A, B and C.

Verdict key: **MATCH** / **MISMATCH** (fixed) / **GAP** / **NOTED**.

## 1. Table A (Foundation) — all 4 items

Read in full: items 1(a-c), 2, 3, 4(a-b). **All MATCH** `ALLOCATIONS`'s
`f=True` rows exactly — 3.5-3.7, 7.0-7.1, 21.0-21.45 MHz (item 1); 7.1-7.3
MHz (item 2, hard 8 kHz cap, not the PSD rule); 28-29.7 MHz (item 3, PSD
rule at 16 kHz); 144-148 and 430-450 MHz (item 4, no limitation). Confirmed
Foundation genuinely has no 14.000-14.350 MHz (20 m) row anywhere in Table
A — `ALLOCATIONS`'s 14000-14350 row correctly omits `f=True`.

## 2. Table B (Standard) — all 5 items

Read in full: items 1(a-d), 2, 3, 4, 5(a-f). **All MATCH** `ALLOCATIONS`'s
`s=True` rows — the mode split is uniformly "J3E or R3E → 100 W pX,
otherwise → 30 W pY" on every item **except item 4** (50-52 MHz), which
adds **C3F** to the high-power list: *"if the station uses emission mode
C3F, J3E or R3E – 100 watts pX"*. This matches the module's documented,
deliberate conservative choice (`acma.py`'s docstring: "OpenHamShack's 'image'
class cannot tell C3F television from SSTV, so it gets pY: the
stricter") — re-confirmed from the primary text that this really is an
exception specific to item 4, not a universal Table B rule, so treating
`image` as `_OTHER` (pY) everywhere never over-grants power.

## 3. GAP/MISMATCH — Table C (Advanced), 50-52 MHz has no bandwidth limitation

Read all 9 items of Table C (1, 2, 3(a-g), 4(a-c), 5, 6, 7(a-g), 8, 9(a-h)).
Every item's "C3F, J3E or R3E → 400 W pX, otherwise → 120 W pY" split
**MATCHES** `ALLOCATIONS`'s `A` tuple on every row (and, as with Table B,
is deliberately held to pY for `image` everywhere, never over-granting).

But item 6 (50.000-52.000 MHz) reads:

> *(a) if the station uses emission mode C3F, J3E or R3E – 400 watts pX
> (b) in any other case – 120 watts pY*
> Limitations: **No limitation**

— while item 4 of **Table B**, the same 50-52 MHz range for Standard,
reads *"A person must not operate an amateur station with an emission
mode that has a necessary bandwidth exceeding 100 kHz"*. So **Standard is
capped to 100 kHz on 50-52 MHz, but Advanced has no cap there at all.**

`EMISSIONS`'s single row for 50-52 MHz applied the 100 kHz cap to every
class in `CLASSES` (Foundation, Standard, Advanced alike) — harmless for
Foundation, which never holds 50-52 MHz at all, but wrong for Advanced,
which the law leaves uncapped. This was found by reading Table C item 6's
own Limitations column directly, rather than assuming it matched Table
B's cap the way every other shared-bandwidth row in this module does.

**Fixed**: gave `_bw()` an optional `classes=` parameter (default
`CLASSES`, unchanged everywhere else) and restricted the 50-52 MHz row to
`classes=("au_standard",)`, with a note explaining why Advanced is
excluded and the source narrowed to Table B item 4 alone (Table C item 6
is cited in the row's own comment, not its `src`, since it is evidence
*against* a limitation rather than for one).

## 4. The LF/MF EIRP rows (items 1-2) and location conditions (s 18)

- Item 1 (2200 m, 1 W pX EIRP, 2.1 kHz) and item 2 (630 m, 5 W pX EIRP,
  3 kHz): both Advanced-only, no mode split — **MATCH** `ALLOCATIONS`
  exactly.
- s 18(1) (*"must not operate ... within the 3.4 GHz to 3.6 GHz frequency
  band if the operation would cause a transmission to occur in the area
  described by the HCIS identifiers ... Schedule 3"*) and s 18(3)
  (*"must not operate an amateur station in the RQZ"*, with s 18(4)
  pointing to the separate RQZ band-plan instrument) — both **MATCH**
  `CONDITIONS`'s `inAu34GhzExcludedArea` and `inWaQuietZone` keys exactly,
  re-read in full rather than taken from `au.md`'s quotes.

## 5. `NOTES` — re-verified against ss 12, 13, 15

- s 12(1) (call sign at beginning/end of transmission, every 10 min if
  longer) — **MATCH** `NOTES`'s "identification" entry.
- s 13(2)(b)-(c) (*"must not operate an amateur station ... that is, or
  as, an amateur repeater station [or] beacon station"*) — **MATCH**
  `NOTES`'s "repeater" entry.
- s 13(4) (automatic/computer-controlled mode **and** a timer that shuts
  down an unintended transmission after more than 10 minutes) — **MATCH**
  `NOTES`'s "unattended" entry, word for word.

## 6. The edge convention (s 5(3))

*"a reference to a part of the spectrum or frequency band includes all
frequencies that are greater than but not including the lower frequency,
up to and including the higher frequency"* — confirmed verbatim, matching
`EDGES = "lower-open"`.

## 7. `REFUSED` — 60 m

Searched the entire CL text for "5" MHz / "5351" / "5366" / "60 m": no
match anywhere in Schedule 2's three tables. 60 m genuinely has no row in
any table, confirming `REFUSED`'s entry (60 m is in the spectrum plan but
not the class licence) is correct — re-confirmed by absence in the
primary instrument itself, not merely by `au.md`'s claim about the
spectrum plan.

## Summary

- **Rows checked**: all 4 Table A items, all 5 Table B items, all 9
  Table C items, every `EMISSIONS` bandwidth/PSD figure, both `CONDITIONS`
  keys, all three `NOTES` entries checked against their sections, the
  edge convention, and the 60 m `REFUSED` entry.
- **Errors fixed**: one — the 50-52 MHz `EMISSIONS` row wrongly capped
  Advanced to 100 kHz (Table B's Standard-only limit); Table C item 6
  itself says "No limitation" for Advanced on that range. Restricted the
  row to Standard only.
- **UNCONFIRMED rows**: none newly found or resolved. `au.md` section
  11's existing list stands (the "radiated power" vs pX/pY ambiguity, the
  HCIS-cell-to-coordinate mapping, which spectrum licences overlap
  amateur bands beyond 3.4-3.6 GHz, the visitor call-sign separator, the
  Japanese 3rd/4th-class asterisk) — nothing here needed re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK, after the fix (`tests/test_licence_au.py` included).
