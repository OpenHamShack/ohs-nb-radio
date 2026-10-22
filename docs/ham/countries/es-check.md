# Spain (ES): the line-by-line check

Checked 2026-10-08 against fresh downloads of B1, B2 and C26, plus the
S1/S3 resolutions, all re-fetched here (not reused from the research
pass) and confirmed byte-identical to what `es.md` recorded before
anything else was read.

| Key | URL | SHA-256 (fetched here) | Matches `es.md`? |
|---|---|---|---|
| B1 | `https://boe.es/boe/dias/2013/07/12/pdfs/BOE-A-2013-7624.pdf` | `132cd7359dd474676497c4535e61f6090af400ec67c9f5947822379358547d12` | yes, exact |
| B2 | `https://www.boe.es/boe/dias/2015/04/10/pdfs/BOE-A-2015-3864.pdf` | `6edf0020827f17cfcf49409d6f4873706978d9106c95aa08c89c5c0645b8ca2f` | yes, exact |
| C26 | `https://www.boe.es/buscar/pdf/2026/BOE-A-2026-15661-consolidado.pdf` | `70a4714bde6eac0f97e5d1c6b56d9ff326f8dc5883491fade5ad67c36e8e6b1e` | yes, exact |
| S1 | `https://www.ure.es/?wpdmdl=1483546` | `b6a3a9afa3057f996be026bb9d8ad795c4d0f68ae8fbc7b7b80eed694504e666` | yes, exact |
| S3 | `https://www.ure.es/download/1503648/?wpdmdl=1503648` | `2e44e0591b2c84321823a8ef5f9c358074da0b356722b861402eae1e5f45c3b6` | yes, exact |

**Scope note, stated plainly rather than glossed over**: C26 (the CNAF,
325 pages) has genuinely no text layer on its tabular/status pages —
confirmed directly (`pdftotext` on pages 151, 252 and 259 returns only
the BOE header and page number, nothing else), matching `es.md`'s own
claim that it was read by rendering pages to images. This check
re-rendered and re-read two of the most legally significant note pages
(UN-100 at p.252, UN-122 at p.259) as a spot-check, and read B1 and B2
in full (both have real text layers). The remaining ~28 CNAF pages
`es.md` cites for band status were not independently re-rendered this
pass — that would mean re-doing the entire visual read `es.md`'s
research already did, which is beyond what a spot-check check can cover
without becoming a second full research pass. This is disclosed rather
than silently assumed.

Verdict key: **MATCH** / **MISMATCH** / **GAP** / **NOTED**.

## 1. B1 Anexo I §3.1's power table — read in full

The table's merged power cells (1000 W PEP spanning nine HF rows 1.8-28
MHz; 600 W PEP spanning 50/70/144-146 MHz; 300 W PEP for 430-440 MHz;
1000 W EIRP spanning 1240-1300 and 2300-2450 MHz; 1000 W EIRP spanning
5.65-250 GHz) were read directly from the PDF layout rather than
assumed — **all MATCH** `setid.py`'s base figures before the §3.2
secondary-band halving is applied.

## 2. §3.2 (the 50% secondary rule) applied per CNAF status

*"La potencia máxima de las emisiones en bandas de frecuencias atribuidas
con carácter secundario al servicio de radioaficionados no superarán el
50% de los valores indicados en la tabla anterior"* — confirmed verbatim.
Checked every row `setid.py` halves (160 m below 1830 kHz, 30 m, 6 m,
4 m, 1240-1258 MHz, all of 13 cm, 6 cm and 3 cm) against its CNAF
primary/secondary status as `es.md` recorded it, and the arithmetic in
every case is exactly half the §3.1 base figure (e.g. 6 m: 600 W → 300 W,
not URE's claimed 600 W, re-confirming the module's documented decision
to prefer the law's own 50% rule over the society's page).

## 3. §3.3 (EME/meteor scatter) and the "above 10.5 GHz" scope decision

*"...se podrán utilizar potencias de cresta de la envolvente de hasta
1000 w"* for EME/MS in IARU sub-bands outside towns — **MATCH** against
`NOTES`'s "eme" entry. Confirmed the module's stated scope decision (rows
above 10.5 GHz left out because "the apps' hardware stops at 5.85 GHz")
is a deliberate exclusion, not a gap — the 24-250 GHz CNAF rows `es.md`
documents were correctly never meant to be encoded here.

## 4. B2's DA2 rewrite — the three special-authorisation bands, exactly

*"2.300-2.450 MHz, excepto la subbanda 2.316-2.332 MHz."* and
*"5.650-5.850 MHz, excepto las subbandas 5.700-5.720 MHz y 5.760-5.762
MHz."* and *"24.050-24,250 GHz."* — read directly from B2's text (not
`es.md`'s quote of it). **MATCH** exactly:

- `ALLOCATIONS`/`CONDITIONS` correctly split 2300-2450 MHz into three
  SA-gated sub-ranges (2300-2316, 2332-2400, 2410-2450 — the fourth,
  2400-2410, is carved out for S1) around the one free sub-band
  (2316-2332 MHz).
- `ALLOCATIONS`/`CONDITIONS` correctly split 5650-5850 MHz into three
  SA-gated sub-ranges around **two** free sub-bands (5700-5720 and
  5760-5762 MHz) — getting the count of free gaps right matters here,
  since a careless reading could merge them into one.
- 24.050-24.250 GHz is DA2's third SA band, but it falls inside the
  module's deliberately-excluded 24+ GHz range (see §3), so it correctly
  needs no `CONDITIONS` entry here.

## 5. S1, S3 — confirmed via hash, not re-extracted

Both documents re-downloaded from the same URE mirror URLs `es.md`
cites and hash-confirmed identical, so the verbatim Spanish text
`es.md` already quotes from them (*"1500 vatios... 21,5 dBi... hasta el
26 de diciembre de 2026"* for S1; *"100 W... únicamente desde estaciones
fijas"* for S3) is the same text `setid.py` was built from — re-reading
it from `es.md`'s own quote block, not a second extraction, since the
files are byte-identical to what the research already read.

## 6. UN-100 and UN-122 — re-rendered and re-read as images

- **UN-100** (p.252): *"La banda de frecuencias 50,0 a 52,0 MHz podrá
  ser utilizada por los radioaficionados en territorio nacional bajo las
  condiciones de la nota 5.164... Esta utilización tiene la
  consideración de uso especial."* — confirms "uso especial" (special
  use) is the CNAF's way of marking 6 m secondary, matching `es.md`'s
  reading and justifying the §3.2 halving to 300 W.
- **UN-122** (p.259): *"Para la banda de frecuencias 1258-1300 MHz, el
  Anexo 1 de la Decisión de la CEPT ECC/DEC(25)01 establece las medidas
  técnicas y operacionales con las que deberá operar el servicio de
  radioaficionados."* — **MATCH**, word for word, against `ALLOCATIONS`'s
  comment and `es.md`'s quote.

## 7. CEPT — Articles 11, 13, 14 read in full

*"Las autorizaciones de radioaficionado otorgadas por la SETSI... tendrán,
a todos los efectos, la consideración de licencias CEPT"* (Art. 11),
*"La licencia CEPT permite la utilización de todas las bandas... en las
condiciones que apliquen en el país donde se va a operar la estación"*
(Art. 14 b), and the "EA" prefix rule (Art. 14 e) — all **MATCH**
`CEPT = {"T/R 61-01": (_C,), "T/R 61-02": (_C,)}` and `CEPT_VISITOR`
exactly.

## Summary

- **Rows checked**: all of B1's power table, §3.2's halving rule applied
  to every secondary row, §3.3's EME note, B2's three DA2
  special-authorisation bands (and their free sub-bands, counted
  correctly), S1/S3 via hash confirmation, two spot-checked CNAF note
  pages (UN-100, UN-122), and Articles 11/13/14 on CEPT.
- **Errors fixed**: none. `ohscore/licences/setid.py` is unchanged —
  every power figure, special-authorisation gap and CEPT mapping
  matched on independent re-reading of the text-based sources, and the
  two spot-checked image-only CNAF pages matched `es.md`'s quotes
  exactly.
- **UNCONFIRMED rows**: none newly found or resolved; none of this
  pass's work touched the ~28 CNAF status/table pages this check could
  not practically re-render. `es.md` section 8's existing list stands
  (60 m bandwidth/mode conditions, the SA claims for 76-250 GHz being
  URE-only, the 50/70 MHz power conflict with URE's page) — all already
  correctly resolved in favour of the law's own text, which this check
  re-confirms rather than re-litigates.
- **Tests**: `python3 -m unittest discover -s tests -p 'test_*licen*'` —
  230 tests, OK (`tests/test_licence_es.py` included); no code changed.
