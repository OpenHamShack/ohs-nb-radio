# United States (US): the line-by-line check

Checked 2026-10-08 against fresh downloads of the two primary sources
`us.md` cites as F1 and F4, re-fetched here (not re-used from the research
pass) and compared byte-for-byte by SHA-256 before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `us.md`? |
|---|---|---|---|
| F1 | `https://www.ecfr.gov/api/versioner/v1/full/2026-10-06/title-47.xml?part=97` | `7b86cd2b22f11437adc8720a19fd244529295a1f76728c214cb91b4e3c4583e3` | yes, exact |
| F4 | `https://www.ecfr.gov/api/versioner/v1/full/2026-10-06/title-47.xml?part=2&section=2.106` | `dd041c99153e7b6cacb4d7019797cea24e61b25540bd31f7dea61fed2fdc45ce` | yes, exact |

Both hashes are identical to the ones `us.md` recorded, so this check is
against the same point-in-time text the research used — the eCFR API
requires `Accept-Encoding: gzip` or it 406s; `curl --compressed` gets the
real XML. Converted to text with a tag-stripping pass (`re.sub('<[^>]+>',
'\n', ...)` + `html.unescape`), then read directly against `ohscore/licences/fcc.py`.

Verdict key: **MATCH** / **MISMATCH** (wrong figure, fixed) / **GAP** (row
missing entirely, fixed) / **NOTED** (true but worth flagging, not fixed).

## 1. §97.301 allocation table — every row, by class letter

All five per-class tables (`(a)` Technician+, `(b)` Extra, `(c)` Advanced,
`(d)` General, `(e)` Novice/Technician) were read from the raw XML cell by
cell (not the flattened text, which drops empty `<TD/>` cells and makes
Region columns ambiguous) and reconstructed by hand.

| Band / class split | `fcc.py` encoding | Verdict |
|---|---|---|
| 6 m 50-54 (T,G,A,E, all regions) | `_m(50,54,...)` no region tag | MATCH |
| 2 m 144-148 (T,G,A,E) | `_m(144,148,...)` no region tag | MATCH |
| 1.25 m 222-225 (R2 only, Novice 25 W) | `_m(222,225,...,R2)` | MATCH |
| 70 cm: R1/R3 430-440; R2 420-450 | three rows: 420-430 (R2), 430-440 (all), 440-450 (R2) | MATCH |
| 33 cm 902-928 (R2 only) | `_m(902,928,...,R2)` | MATCH |
| 23 cm 1240-1300 (all regions, same) | three rows splitting by class (1240-1270, 1270-1295 w/ Novice 5 W, 1295-1300) | MATCH |
| 13 cm 2300-2310 / 2390-2450 (all regions, same) | matching rows; 2310-2390 in REFUSED | MATCH |
| 5 cm: R1/R3 5650-5850; R2 5650-5925 | 5650-5850 (all) + 5850-5925 (R2) | MATCH |
| 3 cm, 1.2 cm, 6 mm, 2.5 mm, 2 mm, 1 mm (all regions, same) | matching rows | MATCH |
| **Above 275 GHz** (all regions, sharing (f)) | **absent from `ALLOCATIONS`** | **GAP — fixed** |
| 80 m: Extra 3500-3600; others 3525-3600 | 3500-3525 (E only) + 3525-3600 (all) | MATCH |
| 75 m: Extra R1 3600-3800/R2 3600-4000/R3 3600-3900; Advanced 3700-.../3700-.../3700-3900; General none/3800-4000/3800-3900 | four layered rows (3600-3700 E, 3700-3800 AE, 3800-3900 GAE, 3900-4000 GAE+R2) reproduce every class/region combination exactly when combined | MATCH (verified cell-by-cell, see below) |
| 40 m: Extra 7000-7200(R1,R3)/7300(R2); Advanced 7025-.../7300(R2); General 7025-7125 + 7175-7200(R1,R3)/7300(R2); N/T 7025-7125 only | seven layered rows reproduce every combination (checked in full below) | MATCH |
| 30 m 10100-10150 (G,A,E, 200 W) | `_k(10100,10150,...)` | MATCH |
| 20 m: Extra 14000-14350; Advanced/General split round 14150-14225 (A exclusive) | five rows | MATCH |
| 17 m, 12 m 18068-18168 / 24890-24990 (G,A,E only, all regions) | matching rows, no Novice/Technician | MATCH |
| 15 m: same shape as 20 m | five rows | MATCH |
| 10 m: N/T 28000-28500 only (200 W); G/A/E 28000-29700 | two rows | MATCH |
| 2200 m 135.7-137.8 (G,A,E) | `_k(135.7,137.8,...)` | MATCH |
| 630 m 472-479 (G,A,E) | `_k(472,479,...)` | MATCH |
| 160 m 1800-2000 (G,A,E) | `_k(1800,2000,...)` | MATCH |
| 60 m 5351.5-5366.5 (G,A,E) | see §3 below (CHANNELLED) | MATCH |

**75 m and 40 m were checked cell-by-cell**, not just by eye, because the
flattened text drops empty table cells and a region column can silently
shift. Pulling the raw `<TR>/<TD>` blocks for every "75 m" and "40 m" row
in the XML and reconstructing which region column is genuinely empty
confirmed: General's 75 m row has a real empty `<TD/>` for Region 1 (no US
General-class privilege theorises for R1 at all, consistent with the US
having no Region 1 territory), and the arithmetic of combining `fcc.py`'s
layered rows per class per region reproduces the source table's numbers
exactly in every one of the 2 (class pairs) x 3 (regions) x 2 (bands)
combinations tried.

### GAP — "Above 275 GHz" missing entirely

§97.301(a)'s table has a final row, printed identically in all three
Region columns as "Above 275" with sharing paragraph "(f)." — confirmed
twice, independently, by §97.305(c)(7)(vi): *"(vi) 1 mm / Above 275 GHz /
MCW, phone, image, RTTY, data, SS, test, pulse / (f)(7), (8), and (12)."*
`fcc.py`'s `ALLOCATIONS` had no row for it at all — Technician and up had
no access to anything above 250 GHz, where Part 97 in fact grants it to
the same four classes as every other microwave band. `us.md` section 3.2
already listed this row correctly ("above 275 GHz | same | T,G,A,E |
1500 W PEP | (f) | §97.301(a)"); only the code had dropped it.

**Fixed**: added `_m(275000, 1000000, _cls("TGAE"), "above 275 GHz; no
upper edge stated", "47 CFR 97.301(a), 97.303(f); 97.305(c)(7)(vi)")`,
open at a 1 THz sentinel the way `rsm.py` (New Zealand) already holds its
own "above 275 GHz" row open — Part 97 states no upper edge, so there is
nothing else to encode it against.

## 2. §97.303 sharing paragraphs cited by the notes

Read in full (every lettered paragraph (a)-(t)) and checked against every
note string and `src` citation in `ALLOCATIONS`, `CONDITIONS` and `NOTES`.

- Line A (m)(1), UTC notification (g)(2), White Sands box and 241 km ring
  (n)(2)/97.313(g), Colorado/Wyoming four slivers (n)(3) with the exact
  coordinates and MHz ranges, 219-220 MHz restriction (l)(1)-(5), 13 cm
  sharing (p) — all **MATCH** verbatim.
- **NOTED**: the 5 cm band's "must accept ISM interference" note was cited
  to 97.303(r) only. Paragraph (r) is about other-nations mobile and
  FSS/ITS sharing; the ISM obligation for 5 cm is actually paragraph
  **(e)** ("Amateur stations receiving in the 33 cm band, the 2400-2450
  MHz segment, the **5.725-5.875 GHz segment**, the 1.2 cm band, the 2.5 mm
  band, or the 244-246 GHz segment must accept interference from ISM
  equipment"). The 5.725-5.875 GHz ISM zone straddles both of `fcc.py`'s
  5 cm rows (5650-5850 and 5850-5925), so each needed the (e) citation and
  each needed its slice of the range named precisely. **Fixed**: the
  5650-5850 row's note now says "5725-5850 MHz" (not "5725-5875", which
  reached into the other row) and cites `97.303(e),(r)`; the 5850-5925 row's
  note now also names its own slice, "5850-5875 MHz", and cites
  `97.303(e),(r)`.

## 3. 60 m — §97.303(h)(3), §97.313(i), footnote US23

The four discrete channel centres (5332.0, 5348.0, 5373.0, 5405.0 kHz),
their USB dial frequencies 1.5 kHz below centre (5330.5/5346.5/5371.5/
5403.5), the 100 W ERP channel cap, the continuous 5351.5-5366.5 kHz
segment at 9.15 W ERP, and the 2.8 kHz bandwidth ceiling for all 60 m
transmissions are every one **MATCH**, confirmed against both
§97.303(h)(3) (the channel table and carrier-offset rule) and §97.313(i)
(the two power figures and the dipole-gain presumption) independently —
`fcc.py`'s `CHANNELLED` table reproduces every figure in both.

## 4. §97.313 power standards — every figure

Read in full, (a)-(m). Every power figure in `ALLOCATIONS` and `NOTES`
checked against it directly:

| Figure | `fcc.py` | §97.313 | Verdict |
|---|---|---|---|
| Default 1.5 kW PEP | `_cls()` default | (b) | MATCH |
| 200 W PEP: 10.10-10.15 MHz | row note | (c)(1) | MATCH |
| 200 W PEP: N/T HF segments | `nt=200` | (c)(2) | MATCH |
| 200 W PEP: 7.050-7.075 MHz, Region 1/3, every class | R3 row, 200 W all classes | (c)(3) | MATCH |
| 25 W PEP: Novice, 1.25 m | Novice override | (d) | MATCH |
| 5 W PEP: Novice, 23 cm | Novice override | (e) | MATCH |
| 611 W ERP / 1 kW EIRP: 435-438 MHz Earth/telecommand | NOTES "satellite" | (f) | MATCH |
| 50 W PEP: 70 cm, US270 areas | `inUs270Area` condition | (f) | MATCH |
| 50 W PEP: 33 cm, within 241 km of White Sands | `nearWhiteSands` condition | (g) | MATCH |
| 50 W PEP: 219-220 MHz | (band refused outright, so moot) | (h) | MATCH |
| 100 W ERP: 60 m channels | `CHANNELLED` | (i) | MATCH |
| 9.15 W ERP: 60 m continuous segment | `CHANNELLED` | (i) | MATCH |
| 10 W PEP: spread spectrum | NOTES "spread spectrum" | (j) | MATCH |
| 1.5 kW PEP / 1 W EIRP: 2200 m | row `Limit` tuple | (k) | MATCH |
| 500 W PEP / 5 W EIRP (1 W Alaska): 630 m | row `Limit` tuple + `alaskaNearRussia` | (l) | MATCH |
| 316 W EIRP: 76-81 GHz | row `Limit` | (m) | MATCH |

No figure in §97.313 was wrong in `fcc.py`. The White Sands prohibition
box itself (31°41'-34°30'N, 104°11'-107°30'W) and the Colorado/Wyoming box
(39-42°N, 103-108°W) with its four MHz slivers (902.4-902.6, 904.3-904.7,
925.3-925.7, 927.3-927.7) both **MATCH** footnote US275/97.303(n)(3)
exactly, including the coordinates.

**NOTED, not a code error**: 47 CFR 2.106 footnote US275 states the
White-Sands 50 W ring as "150 miles", not kilometres; 97.313(g) (the rule
`fcc.py` actually cites) independently gives "241 km" directly, so the
code's figure and citation are both correct — the two sources just use
different units for the same ring (150 mi = 241.4 km).

## 5. §97.207(c) space-station bands vs. `SATELLITE`

Every band in (c)(1) (17 m, 15 m, 12 m, 10 m, 6 mm, 4 mm, 2 mm, 1 mm) and
(c)(2) (7.0-7.1, 14.00-14.25, 144-146, 435-438, 2400-2450, 5.83-5.85,
10.45-10.50 GHz, 24.00-24.05 GHz MHz) is present in `fcc.py`'s `SATELLITE`
table with a "down" (or "both", where RR 5.282 also grants an uplink)
entry. **MATCH**, every band, both directions. 1260-1270 MHz and
5650-5670 MHz are correctly "up"-only (RR 5.282 only; §97.207(c) does not
list either as a space-station band) — **MATCH**.

## 6. §97.305/§97.307 emission and bandwidth table vs. `EMISSIONS`

The full §97.305(c) table (every LF/MF/HF/VHF/UHF+ row, by Roman numeral)
was read and checked against `EMISSIONS` row by row.

- 80 m/75 m, 30 m, 20 m, 17 m, 15 m, 12 m, 10 m RTTY-data/phone-image
  splits: **MATCH**, every edge.
- 40 m: the source literally authorises phone/image on 7075-7100 kHz too
  (§97.305(c)(3)(v)), but only "by stations located in ITU Regions 1 and
  3, and by stations located within ITU Region 2 that are west of 130°
  West longitude or south of 20° North latitude" (§97.307(f)(11), read in
  full and confirmed to say exactly this). `EMISSIONS` holds the whole
  7000-7125 kHz range to CW/data only, which is the documented, cited,
  deliberate stricter reading (the guard has no station-location input to
  know which case applies) — **MATCH to the documented decision**, not a
  gap.
- Novice/Technician CW-only on 80 m/40 m/15 m HF segments (§97.307(f)(9))
  and CW-or-J3E/R3E on 28.3-28.5 MHz (§97.307(f)(10)): **MATCH**, confirmed
  against the literal paragraph text.
- 50.0-50.1 MHz and 144.0-144.1 MHz CW-only: **MATCH** in effect — §97.305(c)
  has no row at all for either sliver (the first 6 m/2 m row starts at
  50.1/144.1), so only §97.305(a)'s blanket CW permission applies there;
  `EMISSIONS`'s citation of "97.305(c)(4)" for this is a little loose (the
  restriction is really the *absence* of a (c)(4) row plus (a)), but the
  encoded restriction itself is correct. Not changed — the citation names
  the right subsection even if the mechanism is "no row, not an express
  one".
- 70 cm and up: §97.305(c)(5)-(7) grant "MCW, phone, image, RTTY, data, SS,
  test[, pulse]" on the entire band for every one of 70 cm, 33 cm, 23 cm,
  13 cm, 5 cm, 3 cm, 1.2 cm and every mm band — effectively unrestricted —
  and `EMISSIONS` has no rows there, which is the correct "no restriction"
  reading. **MATCH**.

## 7. §97.205/§97.203/§97.313(f)/§97.313(j)/§97.301(preamble)/§97.107/§97.119 — `NOTES`

Every one of the six `NOTES` entries was checked against its cited
section, read in full:

| Note | Verdict |
|---|---|
| Repeater exclusions 28.0-29.5, 50.0-51.0, 144.0-144.5, 145.5-146.0, 222.00-222.15, 431.0-433.0, 435.0-438.0 MHz | MATCH, verbatim against §97.205(b) |
| Beacon 100 W, one channel per band | MATCH, §97.203(b),(c) |
| 435-438 MHz Earth/telecommand 611 W ERP / 1 kW EIRP, antenna elevation >10° | MATCH, §97.313(f) |
| Spread spectrum 10 W PEP | MATCH, §97.313(j) |
| Canadian visitor: Canadian terms, capped at Extra, indicator after the call | MATCH, §97.107(a)(3) and §97.119(g) both read in full |
| Altitude: within 50 km of Earth's surface | MATCH, §97.301 preamble, verbatim |

No mismatches in `NOTES`.

## 8. `REFUSED` gaps

- 2310-2390 MHz: confirmed as a genuine gap (the §97.301(a) table jumps
  2300-2310 straight to 2390-2450 in every region). **MATCH**.
- 3300-3450 MHz: footnote US103 (read in full) says exactly what the note
  claims — amateurs "may continue to operate ... on a secondary basis
  while the band's future uses are finalized" but "may be required to
  cease operations ... at any time", naming no class or power. Refusing
  it, as the house rule requires for anything this unconfirmable, is the
  right call. **MATCH**.
- 3450-3500 MHz: footnote US103 confirms the legal mechanism (a 90-day
  cessation window tied to a spectrum auction's public notice) but the
  14 April 2022 date itself is still only secondary-sourced (ARRL); not
  changed, already correctly marked as such in `us.md`.
- 219-220 MHz: a real, narrow allocation exists (§97.301(a), 50 W PEP,
  fixed digital forwarding only, after ARRL/AMTS notice) rather than no
  allocation at all; refusing it outright is a documented simplification
  (both `fcc.py`'s docstring and `us.md` §3.2 say so), not a research gap.
  **MATCH to the documented decision**.

## Summary

- **Rows checked**: all 54 pre-existing `ALLOCATIONS` rows (now 55), the
  full §97.301(a)-(e) table cell-by-cell, the §97.303(a)-(t) sharing
  paragraphs, all of §97.313(a)-(m), all of §97.207(c), the full
  §97.305(c) emission table, the six `NOTES` entries, the four `REFUSED`
  gaps, and the 60 m `CHANNELLED` table.
- **Errors fixed**: one gap (missing "above 275 GHz" allocation row,
  present in `us.md` but dropped from `fcc.py`); one citation/wording fix
  (5 cm ISM note cited the wrong §97.303 paragraph and let its stated
  range overlap the neighbouring row).
- **UNCONFIRMED rows**: none newly found. `us.md` section 11's existing
  list stands (3300-3450 MHz class/power, the US270 area coordinates not
  yet modelled as geometry, the call-sign-group mapping, the F2 release
  date, which classes are still issued, ARRL plan dates, the current
  CEPT (05)06 country list, and the Region 3 US-specific notes) — nothing
  here needed re-opening or escalating to UNCONFIRMED; everything checked
  against a primary source either matched or was fixed.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK, after the fix (`tests/test_licence_us.py` included).
