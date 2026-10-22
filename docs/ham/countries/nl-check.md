# Netherlands (NL): the line-by-line check

Checked 2026-10-08 against a fresh download of W1, plus the two CEPT
instruments it relies on for visitor reciprocity, all re-fetched here
(not reused from the research pass) and confirmed byte-identical to what
`nl.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `nl.md`? |
|---|---|---|---|
| W1 | `https://wetten.overheid.nl/BWBR0036375/` | `759fa7ad689cccc5c0da71f424a20e9c12bea5f2592e2f4e8a3b46bddc59de66` | yes, exact |
| CT1 | `https://docdb.cept.org/download/4541` | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | yes, exact |
| CT2 | `https://docdb.cept.org/download/4372` | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` | yes, exact |

W1 converted with a tag-stripping pass (`re.sub('<[^>]+>', '\n', ...)` +
`html.unescape`); CT1/CT2 with `pdftotext -layout`. Read directly against
`ohscore/licences/rdi.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`SATELLITE` and `CEPT`.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. Bijlage 1 — all 44 rows (38 F, 6 N)

Read every row of the table in document order: band edges (as printed in
MHz, comma decimal), power, p/s status, and "Bijzondere bepalingen". **All
44 rows MATCH** `ALLOCATIONS` exactly, including the two figures that
look unusual on a first read but are exactly as printed:

- **2200 m, 400 W PEP** — the F-row power column literally reads "400"
  for 0,1357-0,1378 MHz, unusually high for a band this narrow
  internationally but correct against the Dutch text; `nl.md` had already
  flagged this as "as printed", re-confirmed here rather than taken on
  faith.
- **Row 1's "Alleen de klasse A1A"** and **row 2's "Alleen A1A, F1A, G1A,
  J2A; contesten zijn niet toegestaan"** — both quoted verbatim in the raw
  HTML, matching `EMISSIONS`'s CW-only restriction on 2200 m/630 m and
  `NOTES`'s "no contests" entry for 630 m.
- **Rows 8/9's overlap** — the table genuinely prints two rows for 30 m
  (10,1-10,15 MHz "Contesten zijn niet toegestaan" and 10,14-10,15 MHz
  "Bandbreedte max 500 Hz"), confirming `ALLOCATIONS`'s split at
  10140 kHz and `EMISSIONS`'s 500 Hz entry for the narrower overlap is the
  correct reconstruction, not a guess.
- **Row 23's "Uitsluitend satellietverkeer (aarde naar ruimte)"** (satellite
  traffic only, Earth to space) on 2400-2450 MHz — matches
  `ALLOCATIONS`'s `satellite_only=True` row and `SATELLITE`'s `"up"` tag
  exactly: the raw text leaves no ambiguity about direction (unlike, say,
  Germany's B13, which states direction only for specific ranges — here
  the Dutch row states it for this one range directly).
- **The N block** (6 rows: 7.0-7.2, 14.0-14.35, 28.0-29.7, 144-146,
  430-436, 436-440) at 100/100/100/25/25/25 W — all **MATCH**, and N
  genuinely has no row for any other band (confirmed: the N block is
  exactly six rows, nothing else), matching `ALLOCATIONS`'s `n=None`
  default everywhere else.

## 2. Footnotes 1-3 vs the module's claims

- **Footnote 1** (CEPT/HAREC equivalence for registration): re-read in
  full. It equates a foreign HAREC (CEPT T/R 61-02 Annex 4) with the F
  exam, and an equivalent novice certificate (ECC (05)06 Annex 4) with
  the N exam — this is about *becoming* a Dutch registrant with a foreign
  qualification, not about short-stay CEPT reciprocal operation, exactly
  as `rdi.py`'s comment already says. **MATCH**, no change.
- **Footnote 2** (PEP definition: power at the stage directly coupled to
  the antenna system) — matches the module's docstring claim verbatim.
  **MATCH**.
- **Footnote 3** (self-built equipment spurious-emission limits, Tables 1
  and 2) — informational only, correctly not encoded (the module docstring
  doesn't claim to encode it, and `nl.md` lists it as a gap item already).
  Not a change.

## 3. CEPT reciprocity — re-fetched CT1/CT2 directly, not re-read from `nl.md`

Independently re-downloaded both CEPT instruments (not reused from the
research pass) and grepped their Annex 2 equivalence tables for
"Netherlands":

- CT1 (T/R 61-01), line 263: *"Netherlands PA F 13"* — confirms
  `CEPT = {"T/R 61-01": ("nl_f",), ...}`.
- CT2 (ECC/REC (05)06), line 196: *"Netherlands PD N"* — confirms
  `CEPT = {..., "ECC/REC (05)06": ("nl_n",)}` and
  `CEPT_VISITOR = {"ECC/REC (05)06": "nl_n"}`.

**MATCH**, both, confirmed from the primary CEPT documents directly
rather than from `nl.md`'s quotes of them.

## 4. `REFUSED` and `SATELLITE` gaps

- 1880-2000 kHz: confirmed — row 4 (160 m secondary) ends at 1,88 MHz,
  nothing above it. **MATCH**.
- 5250-5351.5 kHz and 5366.5-5450 kHz: confirmed — row 6 is the only
  60 m row, exactly 5351.5-5366.5 kHz. **MATCH**.
- 2300-2320 MHz: confirmed — row 22 (13 cm) starts at 2.320,0 MHz, nothing
  below it. **MATCH**.
- `SATELLITE`'s single entry (2400-2450 MHz, "up") is the only satellite
  provision anywhere in Bijlage 1 — confirmed, no other row's
  "Bijzondere bepalingen" column mentions satellite traffic. **MATCH**.

## Summary

- **Rows checked**: all 44 Bijlage 1 rows (38 F, 6 N), all three
  footnotes, the CEPT Annex 2 equivalence for both instruments
  (re-fetched independently), and the four `REFUSED` gaps plus the one
  `SATELLITE` entry.
- **Errors fixed**: none. `ohscore/licences/rdi.py` is unchanged — every
  band edge, power figure, emission restriction and satellite/CEPT entry
  matched the primary sources exactly on a fresh, independent read,
  including the two figures that read as surprising at first glance
  (2200 m's 400 W PEP, and the deliberately overlapping 30 m rows).
- **UNCONFIRMED rows**: none newly found or resolved. `nl.md` section 8's
  existing list stands (call-sign prefix allocation per class, /P and /M
  suffix rules, whether VERON publishes its own national plan, the
  pending IARU-R1 September 2026 changes) — nothing here needed
  re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_nl.py` included); no code changed.
