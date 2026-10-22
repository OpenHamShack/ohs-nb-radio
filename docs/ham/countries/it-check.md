# Italy (IT): the line-by-line check

Checked 2026-10-08 against fresh downloads of A26, the three PNRF tables
(A, B, C), the PNRF Notes and the SPER renewal letter, all re-fetched
here (not reused from the research pass) and confirmed byte-identical to
what `it.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `it.md`? |
|---|---|---|---|
| A26 | `.../Allegato_n_26_al_CdC_testo_vigente.pdf` | `aa44a04565fcd06a37541ee7f0c66c733a7f59f5449ab7e149124d8352c25403` | yes, exact |
| PA | `.../02-Tabella_A.pdf` | `ffa33a0dcabc5a0e9ef23832434de8f187a02a2af7cf7f93c767bc0207f4e7a1` | yes, exact |
| PB | `.../03-Tabella_B.docx.pdf` | `185b1c94d5324e85ce0ab6699c07bf9bb68212b38bdc66c1a850bf313c7c22e5` | yes, exact |
| PC | `.../04-Tabella_C.pdf` | `dc5dcec6129ef6d5cb9961452636fd6ecb79679593b8e8a45d835d10dcae3612` | yes, exact |
| PN | `.../05-Note.pdf` | `f4654ebecbedf4253cc2c11b13bbb5a83d5977114a24300424821135836472e1` | yes, exact |
| SPER | `.../aut_sperimentazioni_160_40_2026.pdf` | `0b00484f2717b3d0363c501ddf843a1ebfa2d49c4143e7a5192d3038d8e46870` | yes, exact |

Unlike Spain's CNAF, Italy's PNRF PDFs **have a real text layer** (checked:
`pdftotext` returns the full table, not just headers), so this check read
the actual table rows directly rather than relying on `it.md`'s
image-rendered transcription. Read against `ohscore/licences/mimit.py`'s
`ALLOCATIONS`, `REFUSED`, `CONDITIONS`, `SATELLITE` and `CEPT`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. A26 Articles 11, 12 and 15 — read in full

*"possono operare soltanto sulle bande di frequenze attribuite ai predetti
servizi in Italia dal piano nazionale di ripartizione delle frequenze"*
(Art. 11.1), the 500 W PEP figure "fatte salve" lower PNRF limits
(Art. 15.1), and the start/end/10-minute identification rule, with packet
call sign in every packet (Art. 12.6) — all **MATCH** the module's
docstring and `NOTES` exactly.

## 2. SPER — re-read in full, not just quoted

*"potenza massima di trasmissione pari a 10 W"* (no reference stated, so
read as PEP — matches `ALLOCATIONS`'s choice), the three single
frequencies *"70.100 MHz - 70.200 MHz - 70.300 MHz"* each at 25 kHz max
(the Ministry of Defence's stated reason for not assigning the whole
70-70.4 MHz band), and *"fino al 31 dicembre 2026"* — all **MATCH**
`ALLOCATIONS`'s three experimental 4 m rows and the `_SPER` date range.

## 3. PNRF Tables A/B/C — case-sensitive service names checked row by row

The PNRF distinguishes primary (**RADIOAMATORE**, upper case) from
secondary (*Radioamatore*, lower case) by capitalisation alone — read
every row's exact capitalisation from the raw table text rather than
trusting a summary. **Every row MATCHES** `ALLOCATIONS`'s status note,
including the subtle ones:

- **80 m (3500-3800 kHz)**: *Radioamatore* lower case, confirming Italy's
  unusually narrow secondary status there (most of Europe has 80 m
  primary) — re-confirmed directly from the table, not assumed.
- **50-52 MHz**: *Radioamatore* lower case with notes "7A 56 57" —
  **MATCH** against `ALLOCATIONS`'s "notes 56, 57" citation.
- **52-68 MHz**: genuinely has **no** Radioamatore row at all — confirming
  Italy has no regular 4 m allocation outside the SPER experimental
  channels.
- **144.0-146.0 MHz**: a single PNRF row, **RADIOAMATORE** and
  **RADIOAMATORE VIA SATELLITE** both upper case under note 69 — the
  144.0-145.8/145.8-146.0 MHz split comes entirely from note 69's own
  text (*"La banda di frequenze 144,0-145,8 MHz è ad uso esclusivo del
  servizio di radioamatore. La banda di frequenze 145,8-146,0 MHz è ad
  uso esclusivo del servizio di radioamatore via satellite..."*, read in
  full), confirming `ALLOCATIONS`'s split and the `satellite_only=True`
  flag on the upper half.
- **70 cm**: 430-432 and 432-434 MHz both *Radioamatore* lower case
  (secondary); **434-435 MHz has no Radioamatore row at all**
  (confirming the `REFUSED` gap); **435-436 MHz is RADIOAMATORE and
  RADIOAMATORE VIA SATELLITE both upper case (primary)** — re-confirmed
  this is the one genuinely primary 70 cm sub-band, matching
  `ALLOCATIONS`'s "primary, and amateur-satellite" row exactly; 436-438
  MHz *Radioamatore* lower case (secondary); **438-440 MHz has no
  Radioamatore row at all** (confirming the second `REFUSED` gap).
- **23 cm**: the trickiest band in the whole table. 1240-1245 MHz has its
  own lower-case *Radioamatore* row (note 116) — secondary, matching
  `ALLOCATIONS`. **1245-1260 MHz has no Radioamatore entry anywhere.**
  1260-1270 MHz lists *"Radioamatore via satellite"* only inside the
  **UTILIZZAZIONI** (uses) column of another service's row, not as its
  own attributed service — confirming `it.md`'s and `ALLOCATIONS`'s
  reading that this is a mention, not a grant, and that the real
  attribution is PNRF note 117's text (*"La banda 1.267-1.270 MHz è
  anche attribuita al servizio di radioamatore via satellite
  (Terra-spazio)"*, read in full), which is why only 1267-1270 MHz (not
  the full 1260-1270 MHz) is encoded as `satellite_only=True`. 1270-1298
  MHz has its own lower-case *Radioamatore* row (note 116A) — secondary,
  matching. **1298-1300 MHz has no Radioamatore row.** Three separate
  `REFUSED` gaps (1245-1267, and implicitly within 1260-1270, and
  1298-1300 MHz) all confirmed directly rather than inferred.
- **13 cm**: 2400-2440 MHz's row lists *Radioamatore* (lower case) with
  **no "Radioamatore via satellite" anywhere in that row** — confirming
  `ALLOCATIONS`'s "amateur only, no amateur-satellite" note for this
  range, which is exactly why the QO-100 uplink question is correctly
  left UNCONFIRMED rather than assumed. 2440-2450 MHz has both
  *Radioamatore* and *Radioamatore via satellite*, both lower case
  (secondary) — matching the "secondary, and amateur-satellite" row.
- **6 cm**: 5650-5670 MHz has **only** *"Radioamatore via satellite"*
  (lower case) — **no plain terrestrial Radioamatore row at all** —
  confirming `satellite_only=True` is correct, not a guess. 5670-5760 MHz
  has no amateur row anywhere (`REFUSED` gap). **5760-5770 MHz is
  RADIOAMATORE, upper case (primary)** — re-confirmed as the one
  genuinely primary 6 cm sub-band, matching `ALLOCATIONS`'s row and PN
  note 193's text about no protection from foreign FSS earth stations,
  read in full. 5770-5830 MHz has no amateur row (`REFUSED` gap).
  5830-5850 MHz has both *Radioamatore* and *Radioamatore via satellite
  (s-T)*, both lower case — matching "secondary, and amateur-satellite
  (space to Earth)".
- **3 cm**: 10.0-10.3 GHz has no Radioamatore row at all (`REFUSED` gap);
  10.3-10.4 and 10.4-10.45 GHz each have their own lower-case
  *Radioamatore* row (merged by `ALLOCATIONS` into one 10.3-10.45 MHz
  row since both are secondary with no satellite note); 10.45-10.5 GHz
  adds *Radioamatore via satellite* — matching the separate "secondary,
  and amateur-satellite" row at that edge.

## 4. CEPT — re-verified against CT1 directly

*"Italy I A[9]"* — **MATCH** against `CEPT = {"T/R 61-01": ("it_a",),
"T/R 61-02": ("it_a",)}`.

## Summary

- **Rows checked**: every row of PNRF Tables A, B and C that the amateur
  service touches (checking capitalisation for primary/secondary status
  row by row, not summarised), the four PNRF notes quoted in full (8, 16,
  32B, 69, 117, 193), A26 Articles 11/12/15, the SPER letter in full, and
  the CEPT Annex entry.
- **Errors fixed**: none. `ohscore/licences/mimit.py` is unchanged — every
  band edge and status matched, including the genuinely tricky 23 cm
  "utilizzazione vs attribuzione" distinction (1260-1270 MHz) that the
  original research already got right and this check independently
  re-derived from the same raw table text.
- **UNCONFIRMED rows**: none newly found or resolved; the QO-100 uplink
  question (2400-2410 MHz has no amateur-satellite attribution in the
  PNRF) is re-confirmed as genuinely unresolved in the primary source,
  not an oversight. `it.md` section 8's existing list stands (Class N's
  unpublished bands/power, the pending 2027 PNRF with ECC/DEC/(25)01).
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_it.py` included); no code changed.
