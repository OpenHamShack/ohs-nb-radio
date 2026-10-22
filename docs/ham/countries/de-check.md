# Germany (DE): the line-by-line check

Checked 2026-10-08 against a fresh download of D1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`de.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `de.md`? |
|---|---|---|---|
| D1 | `https://www.gesetze-im-internet.de/afuv_2005/AFuV.pdf` | `a384594c4ec77915aa9e354fa13b8d650eaf58148ad1a98d22d7496ec28d6f9d` | yes, exact |

Converted with `pdftotext -layout` and read directly against
`ohscore/licences/bnetza.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`SATELLITE`, `CEPT` and `NOTES`. The BNetzA "Amateurfunk" web page (D3) was
also re-fetched live to check the CEPT quotes `de.md` already recorded.

Verdict key: **MATCH** / **MISMATCH** (wrong figure, fixed) / **GAP**
(something the law states that the code never encoded, fixed) / **NOTED**
(true but worth flagging, not fixed).

## 1. Anlage 1 Part A, the 45-row table — every row, by `lfd. Nr.`

Read in full from the PDF (p.9: row 1; p.10: rows 2-37; p.11: rows 38-45,
footnotes, B1-B9; p.12: B10-B17). Every row's band edges, status letter
(P/S), and per-class power figure (A, E, N columns) were checked against
`ALLOCATIONS` one by one.

**All 45 rows MATCH** — every band edge, every status letter, every power
figure (including the ERP rows: 1 W ERP on 2200 m/630 m, 9,14 W ERP on
60 m, 6,1 W ERP on class N's 2 m/70 cm, 10 W ERP on class N's 10 m), and
every blank cell (a class genuinely absent from that row, not just
unencoded) in `ohscore/licences/bnetza.py`.

Two rows needed special attention and both were already handled
correctly:

- **Rows 19-21 (23 cm) and B11's Galileo exclusion.** The table attaches
  condition "11" to all three rows (19: 1240-1250, 20: 1250-1260, 21:
  1260-1300 MHz), but B11's text names a narrower sub-range, 1247-1263 MHz,
  "die abgestrahlte Leistung auf maximal 3,05 Watt ERP beschränkt". `_r()`
  splits row 19 at 1247 MHz and row 21 at 1263 MHz, applying `_galileo()`
  (both the row's PEP figure and 3.05 W ERP) only to the overlap —
  **MATCH**, confirmed by overlaying the two ranges by hand.
- **Row 45 ("> 275 GHz"): no class holds it** (table prints "–" in every
  column) **and `ALLOCATIONS` has no row for it**, which is the correct
  encoding (absence = refused) — **MATCH**, not a gap. B14 (the four
  windows 444-453, 510-546, 711-730, 909-926, 945-951 GHz and >956 GHz,
  "Nutzungsbedingungen legt die Bundesnetzagentur fest") is a future
  BNetzA-set condition with nothing to encode yet; `de.md` already says
  so.

## 2. GAP — five rows' B9 bandwidth cap (10 MHz) missing from `EMISSIONS`

The condition column was read for every one of rows 33-44 specifically,
because `de.md`'s own table had already flagged row 33 as having "no
bandwidth note" — worth checking whether the same was true of its
neighbours. It wasn't, uniformly:

| Row | Band | Condition column | Has B9 (10 MHz)? |
|---|---|---|---|
| 33 | 24-24.05 GHz | "13 17" | No |
| 34 | 24.05-24.25 GHz | "9 17" | **Yes** |
| 35 | 47-47.2 GHz | "13 17" | No |
| 36-39 | 76-81 GHz | "9 13 17" (all four) | **Yes** |
| 40 | 122.25-123 GHz | "9 17" | **Yes** |
| 41 | 134-136 GHz | "9 13 17" | **Yes** |
| 42 | 136-141 GHz | "9 13 17" | **Yes** |
| 43 | 241-248 GHz | "13 17" | No |
| 44 | 248-250 GHz | "13 17" | No |

`EMISSIONS` had rows for every B9 band through 10.5 GHz (row 32) and then
stopped — rows 34, 36-39, 40, 41-42 (five B9 obligations, three of them
merged into contiguous ranges) were never encoded, so the module's own
docstring claim ("B1, B3, B4, B6-B9, B16 ... are EMISSIONS here") was not
quite true above 10.5 GHz. Rows 33, 35, 43 and 44 correctly have no
bandwidth entry — the law states none.

**Fixed**: added `_bw(24050000, 24250000, "ae", 10e6, "B9")`,
`_bw(76000000, 81000000, "ae", 10e6, "B9")` (merging rows 36-39, which
share the identical B9 obligation and AE classes),
`_bw(122250000, 123000000, "ae", 10e6, "B9")`, and
`_bw(134000000, 141000000, "ae", 10e6, "B9")` (merging rows 41-42, same
reasoning). Classes are "ae" throughout because class N holds none of
these rows (confirmed: the N column is blank for every row from 19
onward — N only has 10 m, 2 m and 70 cm).

## 3. GAP — B2 (2200 m site notification) was in neither `EMISSIONS` nor `NOTES`

Row 1 (135.7-137.8 kHz, 2200 m) carries conditions "1 2 10"; row 2
(472-479 kHz, 630 m) carries only "1". B1 (800 Hz) was already in
`EMISSIONS` and B10 (no contests/remote stations) was already in `NOTES`'s
"contest" entry, but **B2 itself — "Die Betriebsorte sind bei der
Bundesnetzagentur schriftlich oder elektronisch anzuzeigen. Die
Sendeantenne ist gegenüber anderen Anlagen ausreichend zu entkoppeln.
Werden Störungen bei Primärfunkdiensten auch in benachbarten
Frequenzbereichen verursacht, ist der Betrieb einzustellen" — was absent
from the module entirely**, in `ALLOCATIONS`, `EMISSIONS` and `NOTES`
alike. It is the same kind of obligation the FCC module already encodes
as a prior-notification condition for 2200 m/630 m, except B2 is
registration/siting paperwork rather than a gating condition with its own
settings key, so — matching this module's existing pattern for similarly
procedural rules (B5, B10, B12, B17, the BEMFV EMF notification) — it is
a `NOTES` entry, not a new `CONDITIONS` table.

**Fixed**: added a `"notification"` entry to `NOTES`, naming row 1 only
(630 m does not carry B2) and stating the three obligations verbatim.

## 4. B13 (amateur-satellite service) vs. `SATELLITE` — every one of 20 ranges

B13's full text names two lists — bands where amateur-satellite is
**primary** (7000-7100 kHz, 14000-14250 kHz, 18068-18168 kHz,
21000-21450 kHz, 24890-24990 kHz, 28-29.7 MHz, 144-146 MHz, 24-24.05 GHz,
47-47.2 GHz, 134-136 GHz, 248-250 GHz — 11 ranges) and where it is
**secondary** (435-438 MHz, 1260-1270 MHz, 2400-2450 MHz, 5650-5670 MHz,
5830-5850 MHz, 10.45-10.50 GHz, 76-81 GHz, 136-141 GHz, 241-248 GHz — 9
ranges) — plus a direction restriction sentence naming exactly three of
those twenty: 1260-1270 MHz and 5650-5670 MHz Earth-to-space only,
5830-5850 MHz space-to-Earth only. Every other range carries no stated
direction, so "both" is correct for it.

All 20 ranges are present in `SATELLITE` (three pairs of adjoining ranges
— 134-136+136-141 GHz, 241-248+248-250 GHz, and the already-contiguous
28-29.7 MHz, 144-146 MHz entries — are stored as single merged rows,
which loses no information since `SATELLITE` records direction, not the
primary/secondary amateur-satellite-service status, and every merge is
between ranges with the same direction). The three direction-restricted
ranges have the right tag (`"up"` for 1260-1270 and 5650-5670 MHz,
`"down"` for 5830-5850 MHz) and every other range is `"both"`. **MATCH**,
all 20 ranges, no omissions, no wrong directions.

## 5. CEPT — re-fetched D3 live, not just re-read from `de.md`

Re-fetched `https://www.bundesnetzagentur.de/.../Amateurfunk/start.html`
(the same D3 URL `de.md` cites) today, independent of the research pass,
since it is a live HTML page with no fixed checksum to compare against.
It confirms, verbatim:

- *"Inhabern einer gültigen CEPT-Amateurfunkgenehmigung ... gemäß der
  CEPT-Empfehlung T/R 61-01 ist die Teilnahme am Amateurfunkdienst in
  Deutschland ... gestattet. Dabei dürfen die Betriebsrechte der deutschen
  Klasse A ... wahrgenommen werden."* — T/R 61-01 visitor → class A.
- *"Inhabern einer gültigen CEPT-Novice-Amateurfunkgenehmigung ... gemäß
  der ECC-Empfehlung (05)06 ... Dabei dürfen die Betriebsrechte der
  deutschen Klasse E ... wahrgenommen werden."* — ECC (05)06 visitor →
  class E.
- Class A = HAREC.

**MATCH** against `CEPT`, `CEPT_VISITOR` and `CEPT_SRC` exactly as encoded
(`CEPT_VISITOR = {"T/R 61-01": "de_a", "ECC/REC (05)06": "de_e"}`).

## Summary

- **Rows checked**: all 45 Anlage 1 Part A rows, all 17 Part B conditions
  (B1-B17), the 20-range B13 satellite table, the CEPT visitor mapping
  (re-verified live against D3), and the existing `NOTES`/`REFUSED`
  entries.
- **Errors fixed**: two gaps — the B9 10 MHz bandwidth cap missing for
  five rows above 10.5 GHz (24.05-24.25 GHz, 76-81 GHz, 122.25-123 GHz,
  134-141 GHz), and B2's 2200 m site-notification obligation, present in
  neither `EMISSIONS` nor `NOTES` before this check.
- **UNCONFIRMED rows**: none newly found. `de.md` section 8's existing
  list stands unchanged (70 MHz status after June 2026, the meaning of
  "Wochenende" in B15, the 13 cm repeater pairing, Vfg 11/2005 and
  93/2005, the 24.06.2024 entry-into-force date, the QO-100 wideband
  uplink edges) — nothing checked against D1 or the live D3 page needed
  re-opening or escalating.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK, after both fixes (`tests/test_licence_de.py` included).
