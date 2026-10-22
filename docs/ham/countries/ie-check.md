# Ireland (IE): the line-by-line check

Checked 2026-10-08 against a fresh download of C1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`ie.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `ie.md`? |
|---|---|---|---|
| C1 | `https://www.comreg.ie/media/2023/05/ComReg-0945R6.pdf` | `9c6252ab5677f155726fcd71649593b4a125b245268db5e9bd28242ea280e3cb` | yes, exact |

Converted with `pdftotext -layout`, read directly against
`ohscore/licences/comreg.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`CONDITIONS`, `SATELLITE` and `NOTES`, row by row against Table 2 (HF,
pp.20-23), Table 3 (VHF+, pp.23-26), the Additional Bands of A1.5 (p.27)
and the eight numbered Notes (p.26-27).

Verdict key: **MATCH** / **MISMATCH** (wrong figure) / **GAP** (something
missing) / **NOTED** (worth flagging, not a code change).

## 1. Table 2 (HF) — every row

All 14 rows (135.7 kHz through 10 m) checked, including the two power
units (W/dBW/e.i.r.p. vs P.E.P.) and the "Maritime Mobile Permitted"
flags, which carry the Spike Island 17 dBW island exception. **All 14
MATCH**, including the two-regime 60 m entry: the "5000-5500" row's own
footnote text, *"Transmission is restricted to the following spot
frequencies: 5.280 MHz; 5.300 MHz; 5.332 MHz; 5.348 MHz; 5.400 MHz and
5.405 MHz"*, confirmed verbatim — the spot frequencies genuinely give no
carrier-vs-centre or bandwidth convention, so `REFUSED`'s decision to
block everything outside the WRC-15 segment stands, re-confirmed from the
PDF rather than taken on faith from `ie.md`.

## 2. Table 3 (VHF/UHF/SHF/microwave) — every row

All 21 rows (30-49 MHz through 248-250 GHz) checked. **All 21 MATCH**,
including:

- the 69.9-70.5 MHz row's self-contradiction ("50W ... Fixed Operation
  Only" in the power cell, "For Mobile Operation Max Power is 25W" in the
  notes cell) — `ALLOCATIONS` correctly encodes the fixed 50 W figure and
  leaves mobile to `NOTES`, exactly as `ie.md` recommended;
  Note 7's full text, re-read directly, confirms the mobile exception is
  narrower still: *"The Maximum Power at the output of the transmitter or
  amplifier shall be 17 dBW, with the exceptions of 70.125 - 70.450 MHz
  where the Maximum Power shall be 14 dBW"* — matches `NOTES`'s existing
  wording;
- the single printed "10000-10500 ... 158W" row, which `ALLOCATIONS`
  correctly splits into two rows (10000-10270, 10300-10500 MHz) around
  `REFUSED`'s 10.270-10.300 GHz gap, confirmed by the row's own
  parenthetical: *"Licensees may not use the portion of the band between
  10.270-10.300 GHz"*;
- 430-432 MHz at 50 W vs 432-440 MHz at 400 W — two separate rows, both
  **MATCH**.

## 3. A1.5 Additional Bands — both rows

- **1300-1304 MHz**: printed power is literally *"0W (0 dBW) P.E.P"* —
  self-contradictory (0 dBW is 1 W, not 0 W) — `REFUSED` blocks it.
  **MATCH**.
- **2400-2450 MHz**: *"An individual application must be submitted to use
  any of the additional bands below"* [A1.5] — `CONDITIONS`'s
  `holdsComRegSatellitePermit` key, defaulting to refuse, and
  `ALLOCATIONS`'s `satellite_only=True` 25 W PEP row both **MATCH**.

## 4. Notes 1-8 (p.26-27) vs `NOTES`

All eight re-read. Note 7 (mobile, 17 dBW with the 70.125-70.450 MHz
14 dBW exception) and Note 8 (maritime mobile, 10 dBW) **MATCH** `NOTES`
exactly; Note 2 (Spike Island, 17 dBW) **MATCH**. Notes 1, 3-6 are mode
definitions, not limits, and are not independently encoded — correct,
nothing to check there.

## 5. CEPT and visitor sections (C1 §§1.13-1.16, 2.1, 3.1-3.4)

Re-read directly rather than taken from `ie.md`'s quotes:

- *"ComReg does not recognise Novice or Intermediate Licences as suitable
  qualifications"* [§1.15] and again at §3.2 (*"does not recognise novice
  or intermediate licences as being suitable qualifications"*) — confirms
  `CEPT_VISITOR` is correctly empty (no ECC Rec (05)06 recognition at
  all).
- *"Amateur Station Licensees from countries that have not signed CEPT
  Agreement T/R 61-01 need to obtain a Visitors Temporary Licence from
  ComReg before they may operate"* [§3.1] — confirms, by implication,
  that T/R 61-01 signatories do **not** need one; they operate directly
  as CEPT visitors, matching `CEPT = {"T/R 61-01": ("cept1", "cept2")}`.
- §2.1: one CEPT exam (T/R 61-02/HAREC) yields Class 1 (with Morse) or
  Class 2 (without) — matches `CLASS_NAME` and the class descriptions in
  `ie.md` §2.
- `CEPT_VISITOR` is correctly left empty/unmapped for T/R 61-01 too
  (comment: "which class a T/R 61-01 visitor holds is not stated; both
  have the same bands, so the operator's choice changes nothing") —
  **MATCH**, the source genuinely never says which class a visitor
  becomes, and it makes no practical difference since Table 2/3 give both
  classes identical bands and powers.

## Summary

- **Rows checked**: all 14 Table 2 rows, all 21 Table 3 rows, both A1.5
  additional-band rows, the 60 m two-regime split, the 10.270-10.300 GHz
  exclusion, all eight Notes, and the CEPT/visitor sections.
- **Errors fixed**: none. Every band edge, every power figure (including
  the e.i.r.p. rows and the two self-contradictory "0 dBW" and "Fixed
  Operation Only + mobile power" rows, both already handled the way the
  source's own contradictions demand), every status letter, and every
  `NOTES`/`CONDITIONS`/`SATELLITE` entry matched the PDF exactly on a
  fresh, independent read. `ohscore/licences/comreg.py` is unchanged.
- **UNCONFIRMED rows**: none newly found, and none resolved either — the
  60 m spot-frequency carrier/centre convention and channel width are
  still not stated anywhere in C1, so they remain refused per the
  existing house-rule decision; `ie.md` section 8's list otherwise
  stands.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_ie.py` included); no code changed,
  so this run simply reconfirms the existing green state.
