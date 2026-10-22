# Canada (CA): the line-by-line check

Checked 2026-10-08 against a fresh download of R4, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`ca.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `ca.md`? |
|---|---|---|---|
| R4 | `https://ised-isde.canada.ca/.../RBR-4-i3-2022-07EN.pdf` | `e805024a0ea5de502169457c101a2f15227837a04b2ee8d4c0e6cd8fd9c5acdd` | yes, exact |

Converted with `pdftotext -layout`, read directly against
`ohscore/licences/ised.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`CHANNELLED`, `SATELLITE` and `CEPT`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Schedule I — all 40 items

Read the full table (Column I band, Column II max bandwidth, Column III
operating provision, Column IV qualification) and every footnote it
cites (5.67A, 5.80A, 5.142, 5.561A, C6, C11, C21). **All 40 items MATCH**
`ALLOCATIONS` and `EMISSIONS`, including:

- The qualification split: items 1-16 (below 30 MHz) require "B and 5,
  B/H, B and A" — plain Basic does not qualify — while items 17-40
  require only "B". `ised.py`'s `_hf()` (excludes `ca_basic`) vs `_all()`
  (includes it) reproduces this exactly for every item.
- Item 11 (30 m)'s unusually narrow **1 kHz** bandwidth (every other HF
  band here is 6 kHz) — confirmed printed, not a typo, and matches
  `EMISSIONS`'s `_bw(10100e3, 10150e3, 1000.0, 11)`.
- Items 19/20/21 (219-220, 220-222, 222-225 MHz): three genuinely
  separate rows with three different provisions (C11 secondary, C11
  "Exceptional circumstances only", and unrestricted primary
  respectively) — `ALLOCATIONS` keeps 219-220 and 222-225 as ordinary
  rows and `REFUSED` blocks 220-222 MHz outright, matching the source's
  own three-way split exactly rather than merging it into one range.
- Items 32-35 (76-81.5 GHz) and 37-40 (134-250 GHz): `ised.py` merges
  these into two rows each (`76000-81500` and `134000-141000` /
  `241000-250000`) since every sub-item shares the same qualification
  and "Not specified" bandwidth; the merged rows' notes ("secondary
  except 77.5-78 GHz", "primary to 136 GHz, secondary above", "secondary
  to 248 GHz, primary above") correctly state which sub-range differs in
  status — confirmed against each item's own Column III entry
  ("-" = primary, "*" = secondary) one by one, not assumed from the
  merge.
- C21's four 60 m channel centres (5332, 5348, 5373, 5405 kHz) plus the
  continuous 5351.5-5366.5 kHz band, **100 W ERP PEP** "in each channel",
  2.8 kHz maximum, and the four emission designators (2K80J3E, 2K80J2D,
  60H0J2B, 150HA1A) — all **MATCH** `CHANNELLED` and `NOTES`'s "60 m"
  entry exactly.
- 5.80A's exact wording (*"Administrations may increase this limit of
  e.i.r.p. to 5 W in portions of their territory..."*) was re-read in
  full: Canada's own footnote table has no Canadian footnote exercising
  that option on 472-479 kHz, re-confirming (not just re-reading
  `ca.md`'s claim) that the "1 W EIRP, 5 W unconfirmed" decision is
  correct and that `ALLOCATIONS`'s `_EIRP1` (1 W) rather than a guessed
  5 W is the right call.

## 2. §10 power limits — re-read in full

*"10.2 ... 560 W peak envelope power for transmitters that produce any
type of single sideband emission, or 190 W carrier power for
transmitters that produce any other type of emission"* and *"10.3 ...
2,250 W peak envelope power ... or 750 W carrier power ..."* — **MATCH**
`BASIC` and `ADVANCED` exactly, including the mode split (`_SSB` only
gets the PEP figure; everything else gets the carrier figure) that the
module's docstring already explains as the conservative reading of an
ISED-unconfirmed interpretation question (whether a data/digital-voice
mode run through an SSB exciter counts as "single sideband").

## 3. The amateur-satellite table (T22, via `ca.md` s.6) vs `SATELLITE`

All 18 ranges `ca.md` lists from T22 are present in `SATELLITE`, merged
where contiguous and sharing the same direction (76-77.5+78-81+81-81.5 →
one row; 134-136+136-141 → one row; 241-248+248-250 → one row). The two
direction-restricted ranges (1260-1270 MHz and 5650-5670 MHz, both
Earth-to-space only under RR 5.282) carry `"up"`; everything else is
`"both"`. **MATCH**, and the 5830-5850 MHz downlink that only appears in
RAC's own (non-regulatory) plan, not in T22, is correctly left out —
re-confirmed as a deliberate omission, not a missed row, since it has no
bearing on `ised.py`'s terrestrial permission (item 27 already covers
5650-5925 MHz generically).

## 4. `REFUSED` gaps

- The four 60 m inter-channel gaps (5333.4-5346.6, 5349.4-5351.5,
  5366.5-5371.6, 5374.4-5403.6 kHz): recomputed independently from each
  channel centre ± 1.4 kHz (half of C21's 2.8 kHz) and the band edges —
  all four **MATCH** `REFUSED` exactly.
- 220-222 MHz ("exceptional circumstances only" per C11): **MATCH**,
  confirmed item 20's Column III text verbatim.

## 5. CEPT — re-verified against R3's own wording (quoted in `ca.md`)

*"a Canadian needs to hold an Amateur Radio Operator Certificate with
Basic Qualification and Advanced Qualification and have their call sign
on their certificate"* — Basic with Honours or Morse alone does not
qualify. **MATCH** against `CEPT = {"T/R 61-01": ("ca_advanced",)}` and
`CEPT_VISITOR = {"T/R 61-01": "ca_advanced"}`; `ca_basic` and
`ca_basic_hf` correctly hold no CEPT entry.

## Summary

- **Rows checked**: all 40 Schedule I items, every cited footnote
  (5.67A, 5.80A, 5.142, 5.561A, C6, C11, C21), §10's four power figures,
  the 18-range amateur-satellite table, and the five `REFUSED` gaps.
- **Errors fixed**: none. `ohscore/licences/ised.py` is unchanged — every
  band edge, bandwidth figure, qualification requirement, power tier and
  satellite direction matched the primary source exactly on a fresh,
  independent read, including the two deliberately-UNCONFIRMED decisions
  (630 m's 1 W vs RAC's unsourced 5 W; the 5850-5925 MHz
  SMSE-012-22 question) re-confirmed as still correctly unresolved rather
  than guessed.
- **UNCONFIRMED rows**: none newly found or resolved. `ca.md`'s existing
  list stands (the 5 W 630 m claim, SMSE-012-22's effect on 5850-5925 MHz,
  the 5830-5850 MHz downlink status, SDR home-built interpretation,
  the "above 400 GHz" RAC claim not in RBR-4) — nothing here needed
  re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_ca.py` included); no code changed.
