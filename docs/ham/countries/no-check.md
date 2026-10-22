# Norway (NO): the line-by-line check

Checked 2026-10-08 against a fresh fetch of N1, re-fetched here (not
reused from the research pass) and confirmed byte-identical to what
`nkom.py`/`no.md` recorded before anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `no.md`? |
|---|---|---|---|
| N1 | `https://lovdata.no/dokument/SF/forskrift/2026-03-23-465` | `c65067ecf826985afb374bf49aa30e56a422075ad656661b72fa687908189791` | yes, exact |

Converted with a tag-stripping pass, read directly against
`ohscore/licences/nkom.py`'s `ALLOCATIONS`, `EMISSIONS`, `REFUSED`,
`SATELLITE`, `CEPT` and `NOTES`, row by row against §5 (begrenset) and
§5a (full).

Verdict key: **MATCH** / **MISMATCH** (fixed) / **GAP** (fixed) /
**NOTED**.

## 1. §5 (begrenset) — all 11 rows

Read in full. **All 11 rows MATCH** `ALLOCATIONS`'s `b=` values exactly:
3.5-3.8/7.0-7.2/14.0-14.35/18.068-18.168/21.0-21.45 MHz at 10 W/6 kHz,
28-29.7 MHz and 50-52/144-146 MHz at 10 W/18 kHz, 432-438 MHz at
10 W/30 kHz (with the 200 kHz exception on 433.6-434.0 MHz), 2300-2450 MHz
at 5 W/20 MHz, and 10.25-10.50 GHz at 1 W/50 MHz.

## 2. §5a (full) — all 36 rows

Read in full, including every power and bandwidth figure down to
1298-1300 MHz's 158 W. **All 36 rows MATCH** `ALLOCATIONS` and
`EMISSIONS` exactly, including:

- The two EIRP-on-top-of-PEP rows (2200 m: *"Maksimal tillatt utstrålt
  effekt er 1 W e.i.r.p."*; 630 m: same wording) — **MATCH**.
- 1850-2000 kHz's *"Gjennomsnittlig sendeeffekt skal ikke overstige 10 W,
  uavhengig av modulasjonstype"* (mean power, not PEP) — **MATCH** against
  the `_M` (mean) unit.
- The elevation-dependent QO-100 uplink EIRP figures on 1260-1262 MHz
  (0.5 W / 50 W / 478 W EIRP by elevation band) — confirmed present and
  genuinely not encodable (the guard has no elevation input), matching
  the module's documented decision to leave them unencoded and hold the
  ordinary band limit.
- The genuine textual contradiction on 1258-1300 MHz (the bandwidth
  column says 150 kHz; the note then describes power for signals
  *"større enn 150 kHz, inkludert amatør TV (ATV)"*) — re-read word for
  word and confirmed it is the primary source's own contradiction, not a
  misreading; `EMISSIONS`'s stricter-reading decision (refuse wider than
  150 kHz) stands.
- 144-146 MHz and 432-438 MHz at **300 W**, not 1000 W — a figure worth
  double-checking since 1000 W appears nearby for the EME/MS allowance;
  confirmed the table's own power column says 300, with the 1000 W
  EME/MS figure sitting only in the Special Conditions column, correctly
  treated by the module as an unencoded conditional uplift.
- Every microwave row from 24.0 GHz to 250 GHz (all at 100 W PEP) was
  also read and is correctly **absent** from `ALLOCATIONS`, matching the
  module's stated scope decision to stop at 10.5 GHz.

## 3. GAP — §7's identification requirement was missing from `NOTES`

§7, paragraph 1: *"Ved bruk av radioamatørstasjon skal fullstendig
kallesignal... oppgis ved begynnelse og slutt av sendingen og med korte
intervaller under sendingen"* — the full call sign must be given at the
start and end of a transmission, and at short intervals during it. This
is the same kind of identification rule every other country's `NOTES`
table already carries (BIPT, ACMA, ISED, FCC all have one), but
`nkom.py`'s `NOTES` list had none — the interference, Ny-Ålesund, EME,
training, airborne and encryption rules were all present, but not this
one.

**Fixed**: added an `"identification"` entry to `NOTES`, citing §7.

## 4. §2, §6, §7 (airborne/interference), §8 — re-read in full

- §2 (*"Forskriften gjelder ikke frekvensområdet 2 GHz–32 GHz i det
  geografiske området innenfor en radius av 20 km fra Ny-Ålesund
  sentrum"*) — **MATCH** against the "ny-alesund" note, word for word.
- §6, paragraph 2 (restricted-licence training under full-licence
  conditions, under physical presence and guidance of a full licensee)
  — **MATCH** against the "training" note.
- §7's unmanned-aircraft paragraph (*"ikke tillatt fra luftfartøy uten
  fører om bord... tillatt ved organisert krise- og redningssamband...
  telemetridata... maksimal utstrålt effekt ikke overstiger 100 mW
  e.i.r.p."*) — **MATCH** against the "airborne" note exactly, including
  the 100 mW EIRP figure.
- §7's interference-reduction rule (*"reduseres til maksimalt 100
  watt"*) — **MATCH** against the "interference" note.
- §8 (encryption prohibited except organised emergency communication and
  training for it) — **MATCH** against the "encryption" note.

## 5. CEPT — re-verified against CT1/CT2 directly

*"Norway LA A"* and *"Svalbard JW A"* — **MATCH** against
`CEPT = {"T/R 61-01": ("no_full",), "T/R 61-02": ("no_full",)}`; Norway
is confirmed absent from CT2 (ECC/REC (05)06), matching `no_begrenset`'s
lack of any CEPT entry.

## Summary

- **Rows checked**: all 11 §5 rows, all 36 §5a rows, the full bandwidth
  column for every row, §§2/6/7/8 in full, and the CEPT Annex entries
  (re-fetched independently).
- **Errors fixed**: one gap — §7's identification requirement (call sign
  at start, end and short intervals) was in the law but missing from
  `NOTES` entirely; added.
- **UNCONFIRMED rows**: none newly found or resolved. `no.md` section 8's
  existing list stands (the call-sign series for `begrenset`, whether a
  foreign HAREC still converts automatically, the pre-2028-vs-2028
  reading question already resolved conservatively) — nothing here
  needed re-opening.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK, after the fix (`tests/test_licence_no.py` included).
