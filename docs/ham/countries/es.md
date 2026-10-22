# Spain (ES): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**How Spanish law is put together (read first).** No single table gives a
Spanish amateur's rights. Three primary texts must be combined:
(1) the **CNAF** (national frequency allocation table) says *which* bands the
amateur service has and whether primary or secondary (UPPER-CASE service name
= primary, lower-case = secondary, RR convention); (2) the **Reglamento**
(Orden IET/1311/2013, Anexo I §3) gives the power per band, and its §3.2 halves
that power in any band where the amateur allocation is **secondary**;
(3) Disposición adicional segunda (DA2) and SETID *resoluciones* add bands that
need a special authorisation or are open only temporarily. Every power figure
below for a secondary band is therefore **[derived]** (table value × 50 %), and
says so.

## Sources

Downloaded 2026-10-08 with `curl -L -A 'Mozilla/5.0' --max-time 60` (BOE,
URE) or `curl -k` (CEPT docdb, whose TLS chain curl cannot verify), converted
with `pdftotext -layout`. The CNAF 2026 allocation tables and national notes
(PDF pp. 95-325) are **scanned images with no text layer**; they were rendered
with `pdftoppm` and read visually page by page (no OCR available), so each CNAF
citation below gives the PDF page that was read.

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| B1 | "Orden IET/1311/2013, de 9 de julio, por la que se aprueba el Reglamento de uso del dominio público radioeléctrico por radioaficionados" — BOE núm. 166, 12 Jul 2013 (BOE-A-2013-7624), original publication (26 pp.) | in force 13 Jul 2013 | https://boe.es/boe/dias/2013/07/12/pdfs/BOE-A-2013-7624.pdf | `132cd7359dd474676497c4535e61f6090af400ec67c9f5947822379358547d12` | es |
| B1c | Same, BOE consolidated text ("Última actualización, publicada el 10/04/2015, en vigor a partir del 11/04/2015") | consolidated 10 Apr 2015 | https://www.boe.es/buscar/act.php?id=BOE-A-2013-7624 | HTML; power-table rowspans read from the HTML (`rowspan="9"` 1000 p.c.e., `rowspan="3"` 600 p.c.e., `rowspan="2"`/`"5"` 1000 p.i.r.e.) | es |
| B2 | "Orden IET/614/2015, de 6 de abril …" — Disposición final primera rewrites DA2 of the Reglamento (BOE núm. 86, 10 Apr 2015, BOE-A-2015-3864) | in force 11 Apr 2015 | https://www.boe.es/boe/dias/2015/04/10/pdfs/BOE-A-2015-3864.pdf | `6edf0020827f17cfcf49409d6f4873706978d9106c95aa08c89c5c0645b8ca2f` | es |
| C26 | "Orden TDF/732/2026, de 10 de julio, por la que se aprueba el Cuadro Nacional de Atribución de Frecuencias" (BOE-A-2026-15661), consolidated PDF, 325 pp.; the annex is headed "CNAF 2025" | published BOE 17 Jul 2026, **in force 18 Jul 2026** (Disposición final segunda: "el día siguiente al de su publicación"); replaces Orden ETD/1449/2021 | https://www.boe.es/buscar/pdf/2026/BOE-A-2026-15661-consolidado.pdf (HTML: https://www.boe.es/buscar/act.php?id=BOE-A-2026-15661) | `70a4714bde6eac0f97e5d1c6b56d9ff326f8dc5883491fade5ad67c36e8e6b1e` | es |
| S1 | SETID Resolución "… por la que se autoriza la realización, en determinadas condiciones y con carácter temporal y experimental, de emisiones del servicio de aficionados en la banda de frecuencias 2400 a 2410 MHz por titulares de autorizaciones de radioaficionado" (QO-100) | signed 04/12/2025; valid **until 26 Dec 2026** | via URE: https://www.ure.es/?wpdmdl=1483546 | `b6a3a9afa3057f996be026bb9d8ad795c4d0f68ae8fbc7b7b80eed694504e666` | es |
| S2 | SETID Resolución authorising 1850-2000 kHz for contests, 1 Jan - 31 Dec 2026 | signed 04/12/2025 | via URE: https://www.ure.es/download/?wpdmdl=753763 | `d0c900259e2e3d2c50b4ce9677538ec3c86171968116af4e870148fa4fab8319` | es |
| S3 | SETID Resolución authorising 40.650-40.750 MHz (8 m), 18 months | signed 13/10/2025 | via URE: https://www.ure.es/download/1503648/?wpdmdl=1503648 | `2e44e0591b2c84321823a8ef5f9c358074da0b356722b861402eae1e5f45c3b6` | es |
| U1 | URE, "Bandas atribuidas" (band-by-band plan pages) | page fetched 2026-10-08; undated | https://www.ure.es/bandas-atribuidas/ | `5f80d670342e696c38ae4765192a4b81d219a483258942599f12a85645c9f741` | es |
| U2 | URE, "El nuevo Cuadro Nacional de Atribución de Frecuencias (CNAF 2026)" (informative note, with Easy Telecom Law Firm) | 30 Jul 2026 | https://www.ure.es/images/noticias/generales/Nota_informativa_CNAF_2026_y_CMR-27_URE.pdf | `e2cbb8c8fafede6c5aa56a0bd5be74a120d1e3226970c8db5694bd9b1abbb172` | es — **[secondary]** |
| C1 | CEPT T/R 61-01 "CEPT Radio Amateur Licence", edition 16 Feb 2024 | PDF 29 Oct 2024 | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| C2 | CEPT ECO implementation tables: T/R 61-01 (doc 925), T/R 61-02 (926), ECC/REC/(05)06 (1024), ECC/DEC/(25)01 (28651) | fetched 2026-10-08 | https://docdb.cept.org/implementation/925 (etc.) | — | en |
| C3 | ECC Decision (25)01 (1258-1300 MHz amateur measures to protect Galileo) | 27 Jun 2025 | https://docdb.cept.org/download/4810 | `03b8a640cb40e0e2b766f456b0f909282aecb5b850a8f06a059d027cbbad5203` | en |

Not obtained: the 2016 SETID "Resolución 5 MHz"
(avance.digital.gob.es/…/Resolucion5MHz.pdf now returns an HTML page). Orden
ITC/1791/2006 (the old Reglamento named in the brief) is **repealed** by B1
(Disposición derogatoria única) and was not used.

## 1. Regulator and legal instruments

- **Ministerio para la Transformación Digital y de la Función Pública**,
  **Secretaría de Estado de Telecomunicaciones e Infraestructuras Digitales
  (SETID)**, Subdirección General de Planificación y Gestión del Espectro.
  (B1 still says "SETSI", the old name.)
- **Reglamento de uso del dominio público radioeléctrico por radioaficionados**,
  Orden IET/1311/2013 [B1], DA2 rewritten by Orden IET/614/2015 [B2]; BOE
  consolidated text dated 10 Apr 2015 [B1c] — no later amendment.
- **CNAF**: Orden TDF/732/2026 [C26], in force **18 Jul 2026**. Its national
  note **UN-122** now makes ECC/DEC/(25)01 Annex 1 binding on amateurs in
  **1258-1300 MHz with no transition period** (see 3.1). CEPT records Spain as
  "implemented 18-07-2026" for ECC/DEC/(25)01 [C2]. URE's own summary headline
  ("El CNAF 2026 no modifica las condiciones de uso", 30 Jul 2026) is
  contradicted by URE's detailed note [U2 §2.1], which confirms the UN-122
  change and that it applies from 18 Jul 2026.
- Temporary SETID resolutions in force on 2026-10-08: QO-100 2400-2410 MHz
  until 26 Dec 2026 [S1]; 1850-2000 kHz for contests in 2026 [S2]; 8 m
  40.650-40.750 MHz for 18 months from notification (signed 13 Oct 2025) [S3].
  All three are renewed (or not) annually; re-check each January.

## 2. Licence classes

Spain has **one** class. B1 Art. 5: a single "autorización de radioaficionado",
obtained after the exam (Art. 10: HAREC per T/R 61-02, "recibirán el
certificado de examen armonizado (HAREC)"). The Disposición transitoria única
of B1 applies the new rules to every existing authorisation, so older
EA/EB/EC holders (former classes A/B/C) all have the same rights now [derived
from B1 DT única].

| class id | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `autorizacion` | "autorización de radioaficionado" | HAREC (T/R 61-02) | T/R 61-01 CEPT licence: national licence "A" (C1 p.7); B1 Art. 11: "Las autorizaciones de radioaficionado otorgadas por la SETSI … tendrán, a todos los efectos, la consideración de licencias CEPT." | EA, EB, EC (+ district digit); ED for unattended stations |

## 3. Permitted bands and power, per class

Power references (B1 Anexo I §3.1 table, p.21; definitions p.19):
**"p.c.e."** = potencia de cresta de la envolvente = **PEP**, defined as power
"suministrada a la línea de alimentación de la antena" (fed to the antenna
feeder, i.e. transmitter output); **"p.i.r.e."** = **EIRP**. Table (B1 p.21,
rowspans confirmed in B1c HTML): 137 kHz 1 W EIRP; 475 kHz 1 W EIRP (5 W EIRP
>800 km from African borders — not reachable anywhere in Spain [derived]);
1.8-28 MHz **1000 W PEP**; 50, 70, 144-146 MHz **600 W PEP**; 430-440 MHz
**300 W PEP**; 1240-1300 and 2300-2450 MHz **1000 W EIRP**; 5.65 GHz-250 GHz
**1000 W EIRP**. §3.2: secondary bands **50 %** of that. No dBW figures.

Status column: P = AFICIONADOS (primary) in C26 national column; S = aficionados
(secondary). "SA" = special authorisation required (DA2) [B2].

| lo Hz | hi Hz | band | status | autorizacion | notes | source |
|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | S | 1 W EIRP | UN-108 | C26 p.98, p.255; B1 p.21 |
| 472 000 | 479 000 | 630 m | S | 1 W EIRP | RR 5.80A | C26 p.101; B1 p.21 |
| 1 810 000 | 1 830 000 | 160 m | S | 500 W PEP [derived] | URE U1 also "500 W máximo en 1810-1830" | C26 p.104; B1 p.21 §3.2 |
| 1 830 000 | 1 850 000 | 160 m | P | 1000 W PEP | | C26 p.104; B1 p.21 |
| 3 500 000 | 3 800 000 | 80 m | P (shared) | 1000 W PEP | | C26 p.110; B1 p.21 |
| 5 351 500 | 5 366 500 | 60 m | S | 15 W EIRP | RR 5.133B (not in B1's table) | C26 p.112 |
| 7 000 000 | 7 100 000 | 40 m | P | 1000 W PEP | also amateur-sat | C26 p.113 |
| 7 100 000 | 7 200 000 | 40 m | P | 1000 W PEP | | C26 p.114 |
| 10 100 000 | 10 150 000 | 30 m | S | 500 W PEP [derived] | U1 agrees "500 W máximo" | C26 p.116 |
| 14 000 000 | 14 250 000 | 20 m | P | 1000 W PEP | also amateur-sat | C26 p.119 |
| 14 250 000 | 14 350 000 | 20 m | P | 1000 W PEP | | C26 p.119 |
| 18 068 000 | 18 168 000 | 17 m | P | 1000 W PEP | also amateur-sat | C26 p.121 |
| 21 000 000 | 21 450 000 | 15 m | P | 1000 W PEP | also amateur-sat | C26 p.122 |
| 24 890 000 | 24 990 000 | 12 m | P | 1000 W PEP | also amateur-sat | C26 p.123 |
| 28 000 000 | 29 700 000 | 10 m | P | 1000 W PEP | also amateur-sat | C26 p.125 |
| 50 000 000 | 52 000 000 | 6 m | S | 300 W PEP [derived] | UN-100; **URE U1 says 600 W + 6 dB antenna max — conflict, see §8** | C26 p.129, p.252; B1 p.21 |
| 70 150 000 | 70 250 000 | 4 m | S | 300 W PEP [derived] | UN-132; **U1 says 600 W PEP — conflict** | C26 p.130, p.264 |
| 144 000 000 | 146 000 000 | 2 m | P | 600 W PEP | also amateur-sat | C26 p.134; B1 p.21 |
| 430 000 000 | 432 000 000 | 70 cm | P (shared radiolocation) | 300 W PEP | | C26 p.146 |
| 432 000 000 | 438 000 000 | 70 cm | P (shared) | 300 W PEP | RR 5.282 sat 435-438; ISM 433.05-434.79 (accept interference, B1 §3.4) | C26 p.146 |
| 438 000 000 | 440 000 000 | 70 cm | P (shared) | 300 W PEP | | C26 p.146 |
| 1 240 000 000 | 1 258 000 000 | 23 cm | S | 500 W EIRP [derived] | U1 agrees "500 W PIRE" | C26 p.151 |
| 1 258 000 000 | 1 300 000 000 | 23 cm | S | **ECC/DEC/(25)01 Annex 1 limits** (3.1), capped at 500 W EIRP | UN-122, in force 18 Jul 2026 | C26 p.151, p.259; C3 p.6 |
| 2 300 000 000 | 2 316 000 000 | 13 cm | S, **SA** | 500 W EIRP [derived] only with special authorisation | | C26 p.161; B2 |
| 2 316 000 000 | 2 332 000 000 | 13 cm | S | 500 W EIRP [derived] | free use (excepted from DA2) | C26 p.161; B2 |
| 2 332 000 000 | 2 450 000 000 | 13 cm | S, **SA** | 500 W EIRP [derived] only with special authorisation | **except 2400-2410 to QO-100 under S1** (§4) | C26 p.161; B2; S1 |
| 5 650 000 000 | 5 700 000 000 | 6 cm | S, **SA** | 500 W EIRP [derived] with SA | | C26 p.170; B2 |
| 5 700 000 000 | 5 720 000 000 | 6 cm | S | 500 W EIRP [derived] | free use | C26 p.170; B2 |
| 5 720 000 000 | 5 760 000 000 | 6 cm | S, **SA** | 500 W EIRP [derived] with SA | | C26 p.170; B2 |
| 5 760 000 000 | 5 762 000 000 | 6 cm | S | 500 W EIRP [derived] | free use | C26 p.170; B2 |
| 5 762 000 000 | 5 850 000 000 | 6 cm | S, **SA** | 500 W EIRP [derived] with SA | 5830-5850 amateur-sat (space→Earth) | C26 p.170; B2 |
| 10 000 000 000 | 10 450 000 000 | 3 cm | S | 500 W EIRP [derived] | U1 agrees | C26 p.175 |
| 10 450 000 000 | 10 500 000 000 | 3 cm | S | 500 W EIRP [derived] | also amateur-sat (secondary) | C26 p.175 |
| 24 000 000 000 | 24 050 000 000 | 1.2 cm | P | 1000 W EIRP | also amateur-sat | C26 p.190 |
| 24 050 000 000 | 24 250 000 000 | 1.2 cm | S, **SA** | 500 W EIRP [derived] with SA | | C26 p.190; B2 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | P | 1000 W EIRP | also amateur-sat | C26 p.200 |
| 76 000 000 000 | 77 500 000 000 | 4 mm | S | 500 W EIRP [derived] | U1: "necesita autorización individual" **[secondary]** | C26 p.206 |
| 77 500 000 000 | 78 000 000 000 | 4 mm | P | 1000 W EIRP | | C26 p.207 |
| 78 000 000 000 | 81 000 000 000 | 4 mm | S | 500 W EIRP [derived] | U1: needs authorisation **[secondary]**; 81-81.5 not in national column | C26 p.207 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | S | 500 W EIRP [derived] | U1: needs authorisation **[secondary]** | C26 p.211 |
| 134 000 000 000 | 136 000 000 000 | 2 mm | P | 1000 W EIRP | | C26 p.211 |
| 136 000 000 000 | 141 000 000 000 | 2 mm | S | 500 W EIRP [derived] | U1: needs authorisation **[secondary]** | C26 p.212 |
| 241 000 000 000 | 248 000 000 000 | 1.2 mm | S | 500 W EIRP [derived] | | C26 p.217-218 |
| 248 000 000 000 | 250 000 000 000 | 1.2 mm | P | 1000 W EIRP | | C26 p.218 |

Temporary (only while the resolution is valid; guard should refuse unless the
operator sets an explicit "temporary authorisation" flag):

| lo Hz | hi Hz | what | limit | validity | source |
|---|---|---|---|---|---|
| 1 850 000 | 2 000 000 | 160 m extension, **contests only** | as 1.8 MHz in B1 Anexo I ("las mismas que … para la banda de frecuencias 1,8 MHz") — i.e. 1000 W PEP | 1 Jan - 31 Dec 2026 | S2 |
| 40 650 000 | 40 750 000 | 8 m experimental | 100 W PEP; fixed stations only; prior notice to the Jefatura Provincial | 18 months from notification of S3 (signed 13 Oct 2025, so ≈ Apr 2027) | S3 |
| 2 400 000 000 | 2 410 000 000 | QO-100 uplink | 1500 W EIRP, directional antenna ≥ 21.5 dBi, to QO-100 only | until 26 Dec 2026 | S1 |

Original wording (translations mine):

- B1 Anexo I §3.1 (p.21): « En los márgenes establecidos en el CNAF para cada
  banda de frecuencias o en los que expresamente sean autorizados, las
  potencias máximas de las emisiones serán las indicadas en la tabla siguiente »
  — "Within the limits set in the CNAF for each band, or those expressly
  authorised, the maximum powers are those in the following table". Rows
  quoted: « 1.8 (160 m). … 28 (10 m). 1000 (p.c.e.). », « 50 (6 m). 70 (4 m).
  144 a 146 (2 m). 600 (p.c.e.). », « 430 a 440 (70 cm). 300 (p.c.e). »,
  « 1.240 a 1.300 (23 cm). 2.300 a 2.450 (13 cm). 1000 (p.i.r.e). »,
  « 5,650 a 5,850 (6 cm). 10 (3 cm) 24 (1,5 cm). 47 (6 mm). 75 a 250.
  1000 (p.i.r.e). », « 137 (2200 m). 1 (p.i.r.e). », « 475 (630 m). 1 (p.i.r.e).
  Hasta 5 vatios (p.i.r.e) en zonas geográficas distantes más de 800 km de la
  frontera de países africanos. »
- B1 §3.2 (p.21): « La potencia máxima de las emisiones en bandas de frecuencias
  atribuidas con carácter secundario al servicio de radioaficionados no
  superarán el 50 % de los valores indicados en la tabla anterior. » — "Maximum
  power in bands allocated to the amateur service on a secondary basis shall
  not exceed 50 % of the values in the table."
- B1 §3.3 (p.21): « Para enlaces por rebote lunar (EME) o por dispersión
  meteórica (MS), dentro de las subbandas de frecuencias recomendadas por la
  [IARU] y en cualquier caso fuera de los cascos urbanos, se podrán utilizar
  potencias de cresta de la envolvente de hasta 1000 w. » — "For EME or meteor
  scatter, within the IARU-recommended sub-bands and always outside urban
  areas, up to 1000 W PEP may be used."
- B1 Anexo I definitions (p.19): « Potencia de cresta de la envolvente (p.c.e.):
  Media de la potencia suministrada a la línea de alimentación de la antena por
  un transmisor … tomado en la cresta más elevada de la envolvente de
  modulación. » — PEP at the antenna feed line. « Medición de potencia: … se
  realizará, siempre que ello sea posible, con relación a la potencia de la
  portadora. » — "measured, where possible, relative to carrier power".
- C26 UN-100 (p.252): « La banda de frecuencias 50,0 a 52,0 MHz podrá ser
  utilizada por los radioaficionados en territorio nacional bajo las
  condiciones de la nota 5.164 del Reglamento de Radiocomunicaciones. Esta
  utilización tiene la consideración de uso especial. El uso de esta banda por
  radioaficionados no podrá causar interferencia perjudicial a estaciones de
  televisión de los países vecinos ni reclamar protección frente a la
  interferencia procedente de ellas. » — 50-52 MHz usable nationally, no
  interference to / no protection from neighbours' TV.
- C26 UN-132 (p.264): « La banda de frecuencias 70,150-70,250 MHz podrá ser
  utilizada por el servicio de aficionados con carácter secundario y con las
  condiciones técnicas establecidas en el anexo I al Reglamento … aprobado por
  Orden IET/1311/2013 » — 70.150-70.250 MHz, secondary, B1 Anexo I conditions.
- C26 UN-108 (p.255): « Se autoriza el uso de la banda 135,7-137,8 kHz para el
  servicio de aficionados, a título secundario … La potencia radiada máxima
  será de 1 vatio (p.i.r.e.) » — secondary, 1 W EIRP.
- C26 UN-122 (p.259): « Para la banda de frecuencias 1258-1300 MHz, el Anexo 1
  de la Decisión de la CEPT ECC/DEC(25)01 establece las medidas técnicas y
  operacionales con las que deberá operar el servicio de radioaficionados. » —
  "In 1258-1300 MHz, Annex 1 of ECC/DEC/(25)01 sets the technical and
  operational measures under which the amateur service must operate."
- B2 (DA2, BOE 10 Apr 2015 p.31216): « 2.300-2.450 MHz, excepto la subbanda
  2.316-2.332 MHz. 5.650-5.850 MHz, excepto las subbandas 5.700-5.720 MHz y
  5.760-5.762 MHz. 24.050-24,250 GHz. » — bands needing a special
  authorisation (Art. 16), except the listed sub-bands. (The 2013 original had
  "5.650 a 5.850 MHz, excepto la subbanda 5.660 a 5.684 MHz" and no 24 GHz
  entry, B1 p.17.)
- S1: « Autorizar hasta el 26 de diciembre de 2026 a los titulares de
  autorizaciones de radioaficionado, la realización de emisiones del servicio de
  aficionados en la banda de frecuencias 2.400 a 2.410 MHz., con una p.i.r.e
  máxima de 1500 vatios y utilizando antenas directivas con una ganancia no
  inferior a 21,5 dBi, desde estaciones de radioaficionados autorizadas situadas
  en cualquier punto del territorio nacional al satélite QO-100 ubicado en la
  posición orbital 25,9ºE … »
- S3: « … emisiones en la banda de 40,650 – 40,750 MHz con potencia de pico de
  la envolvente (PEP) máxima de 100 W. … Las emisiones se efectuarán únicamente
  desde estaciones fijas … »

### 3.1 Per-band exceptions

- **23 cm (binding since 18 Jul 2026)**, UN-122 → ECC/DEC/(25)01 Annex 1 [C3
  p.6]: narrowband (≤ 150 kHz) 1258-1296 MHz **EIRP ≤ −17 dBW** (20 mW);
  1296-1298 MHz **transmitter power ≤ 17 dBW** (50 W); 1298-1300 MHz **≤ 22 dBW**
  (158 W); EME with ≥ 30 dBi antenna ≥ 15° elevation 1298-1300 MHz ≤ 27 dBW;
  amateur-satellite uplink 1260-1262 MHz EIRP −3 dBW (θ < 15°) / 17 dBW (15-55°)
  / 26.8 dBW (55-90°), 1262-1270 MHz −17 dBW; wideband (> 150 kHz, incl. ATV)
  1258-1300 MHz **−17 dBW/MHz EIRP**. "Maximum power means either peak
  envelope power or carrier power (as appropriate) delivered by the transmitter
  to the amateur station antenna" (C3 fn 2). [derived] Effective Spanish limit
  is the lower of this and 500 W EIRP. 1240-1258 MHz is not covered by UN-122;
  URE [U2] additionally quotes ITU-R M.2164 guidance for 1240-1258 MHz (−39 dBW
  … etc.) — that is a recommendation, **not** in the CNAF; not encoded.
- **60 m**: CNAF secondary allocation with RR 5.133B, **15 W EIRP** (C26
  p.112). B1's table has no 5 MHz row. A 3 kHz/CW-SSB condition reported for the
  original 2016 authorisation (ARRL news) could not be confirmed from a current
  primary source **[UNCONFIRMED]**; URE plan: 2700 Hz max.
- **Bandwidth**: B1 Anexo I §3.1: modulation types are free « con anchos de
  banda de emisión acordes, como norma general, al Plan de bandas de la [IARU]
  para la Región 1 » — "with bandwidths in line, as a general rule, with the
  IARU Region 1 band plan". So the IARU R1 bandwidth column is quasi-binding in
  Spain [derived]; the guard should at least warn hard.
- **Unattended stations** (B1 Art. 25 h, i): VHF/UHF ≤ 50 W output outside
  towns, ≤ 10 W inside, antenna ≤ 6 dBd; HF ≤ 50 W output. (Repeaters/beacons;
  not normal operation.)
- **Club stations used by novices** (Art. 30.6 d): ≤ 40 % of the band limit,
  max 100 W EIRP.
- **ISM**: 433.05-434.79 MHz, 2400-2450 MHz, 5725-5800 MHz, 24-24.25 GHz — must
  accept ISM interference (B1 §3.4).
- **RF exposure**: B1 §3.5 caps exposure at 3.5 mW/cm² where people have access.
- **Portable**: Art. 17.1 — portable stations must be notified to the Jefatura
  Provincial 5 days ahead, except non-continuous temporary use up to 15
  consecutive days.
- **Gain rules**: none in B1 for normal stations (URE's "6 dB antenna max" for
  50 MHz is not in B1/B1c) **[UNCONFIRMED as law]**.

### 3.2 Gaps: not permitted for any class

Everything not in the table, in particular: 137.8-472 kHz; 479-1810 kHz;
**1850-2000 kHz** (except contests in 2026 under S2); 3800-5351.5 kHz;
5366.5-7000 kHz; 7200-10100 kHz; 10150-14000 kHz; 14350-18068; 18168-21000;
21450-24890; 24990-28000 kHz; 29.7-50 MHz (**40.65-40.75 MHz only under S3**);
52-70.15 MHz; **70.25-144 MHz (only 70.150-70.250 on 4 m)**; 146-430 MHz;
440-1240 MHz; 1300-2300 MHz; **2450-5650 MHz (no 3.4 GHz)**; 5850-10000 MHz;
10.5-24.0 GHz; 24.25-47 GHz; 47.2-76 GHz; 81-122.25 GHz; 123-134 GHz;
141-241 GHz; above 250 GHz. Special-authorisation (SA) segments above are
refused by default.

## 4. Satellite / QO-100

- **Uplink 2400-2450 MHz**: allocated (secondary, RR 5.282) but **needs a
  special authorisation** under DA2 [B2] — except via **S1**: 2400-2410 MHz to
  QO-100 only, **≤ 1500 W EIRP, directional antenna ≥ 21.5 dBi**, from any
  authorised station, **valid until 26 Dec 2026** (renewed every year since
  2009; next renewal expected Dec 2026). [derived] The guard should allow
  2400.000-2410.000 MHz only while the resolution date is valid, and should
  check antenna gain ≥ 21.5 dBi and EIRP ≤ 1500 W.
- **10.45-10.50 GHz** (QO-100 downlink): amateur and amateur-satellite,
  secondary (C26 p.175).
- Other amateur-satellite allocations in the national column: 7.0-7.1, 14.0-14.25,
  18.068-18.168, 21.0-21.45, 24.89-24.99, 28-29.7, 144-146 MHz (primary);
  435-438 MHz (RR 5.282); 1260-1270 MHz (RR 5.282, Earth→space; now under
  UN-122 limits); 5830-5850 MHz (space→Earth); 24.00-24.05, 47-47.2, 77.5-78,
  134-136, 248-250 GHz (primary); 76-77.5, 78-81, 136-141, 241-248 GHz
  (secondary).

## 5. CEPT / visiting operators

- T/R 61-01: Spain "implemented 01-09-2009" [C2]; equivalent national licence
  "A", prefix "EA" (C1 p.7). B1 Art. 13-14: a foreign CEPT licence is
  equivalent to the Spanish authorisation for non-residents on temporary stays;
  the visitor uses « su distintivo propio precedido del prefijo EA y,
  opcionalmente, el número del distrito desde el que están operando » (Art. 14
  e) — e.g. EA8/G4XYZ; and gets "todas las bandas … en las condiciones que
  apliquen en el país" (Art. 14 b), i.e. the table above.
- Non-CEPT visitors: temporary authorisation ≤ 90 days on application (Art. 15).
- T/R 61-02 (HAREC): implemented 01-09-2009 [C2]; residents holding a foreign
  HAREC get a Spanish authorisation without exam (Art. 5.2 a).
- ECC/REC/(05)06 (Novice): Spain "no info / see remarks" [C2] — treat as not
  implemented; a CEPT Novice holder has no rights in Spain.

## 6. Callsigns

B1 Art. 27: prefix **EA, EB, EC** (individual or club), **ED** (unattended
automatic stations); temporary prefixes ED/EE/EF (contests, local events),
EG/EH (international events), AM/AN (national events), AO (international
events, and optionally from areas outside national sovereignty). **District
digit** = district of residence at grant (0 reserved for royal events):
1 Galicia, Asturias, Cantabria, Castilla y León, La Rioja; 2 Basque Country,
Navarra, Aragón; 3 Catalonia; 4 Madrid, Castilla-La Mancha, Extremadura;
5 Valencia, Murcia, Albacete; 6 Balearics; 7 Andalucía; 8 Canarias; 9 Ceuta
and Melilla. **Suffix** 1-3 letters (3 normally; 1-2 by merit; Y../Z.. =
analogue/digital unattended; UR.. clubs of associations, RC../RK.. radio
clubs). Portable/mobile (Art. 29.2, optional): **/M, /MM, /MA, /P**, optionally
followed by the district digit when operating outside one's own district.

Regex hints (all map to `autorizacion`):
`^E[A-C][0-9][A-Z]{1,3}$` individual/club; `^ED[0-9][YZ][A-Z]{2}$` unattended;
`^(E[D-H]|A[M-O])[0-9]+[A-Z]{1,4}$` temporary/special.

## 7. National band plan

URE publishes the plan per band on one web page [U1] (undated; HF follows the
2016-era IARU R1 HF plan wording; VHF/UHF follow VHF Handbook 8.x era). Guard
should refuse the beacon and satellite segments marked **bold**.

HF (max bandwidth Hz as printed):
- 136 kHz: 135.7-136.0 CW/QRSS (transatlantic tests), 136.0-137.4 CW,
  137.4-137.6 digital (not CW), 137.6-137.8 CW/QRSS; all 200 Hz.
- 160 m: 1810-1838 CW 200 (1836 QRP); 1838-1840 narrow 500; 1840-1843 all modes
  2700; 1843-1850 all modes 2700. LSB.
- 80 m: 3500-3510 CW (intercontinental priority); 3510-3560 CW (3555 QRS);
  3560-3570 CW (3560 QRP); 3570-3600 narrow/digital (3590-3600 unattended),
  200/500; 3600-3620 all modes/digital/unattended 2700; 3620-3775 all modes
  2700 (3690 QRP, 3735 image, 3760 R1 emergency); 3775-3800 all modes
  (intercontinental priority).
- 60 m: 5351.5-5354.0 CW/narrow/digital 500; 5354.0-5366.0 all modes 2700
  (USB voice); 5366.0-5366.5 weak-signal narrow.
- 40 m: 7000-7040 CW 200 (7030 QRP); 7040-7050 narrow/digital 500 (7047-7050
  unattended); 7050-7060 all modes/digital 2700; 7060-7200 all modes 2700 (7070
  DV, 7090 SSB QRP, 7110 R1 emergency, 7165 image, 7175-7200 intercontinental).
- 30 m: 10100-10130 CW 200 (10116); 10130-10150 narrow/digital 500; no contests;
  voice only for life-safety emergencies.
- 20 m: 14000-14070 CW; 14070-14099 narrow/digital (14089-14099 unattended);
  **14099-14101 IBP beacons**; 14101-14112 all modes/digital/unattended;
  14112-14350 all modes (14195 DX-pedition priority, 14230 image, 14285 SSB
  QRP, 14300 global emergency).
- 17 m: 18068-18095 CW; 18095-18109 narrow; **18109-18111 IBP**; 18111-18120
  all modes/unattended; 18120-18168 all modes (18160 emergency). No contests.
- 15 m: 21000-21070 CW; 21070-21110 narrow/digital; 21110-21120 all modes except
  SSB; 21120-21149 narrow; **21149-21151 IBP**; 21151-21450 all modes (21360
  emergency).
- 12 m: 24890-24915 CW; 24915-24929 narrow; **24929-24931 IBP**; 24931-24990 all
  modes. No contests.
- 10 m: 28000-28070 CW; 28070-28190 narrow/digital; **28190-28225 beacons (IBP
  28199-28201)**; 28225-29000 all modes 2700; 29000-29100 all modes 6000;
  29100-29200 FM simplex 10 kHz; 29200-29300 digital/unattended (packet);
  **29300-29510 satellite downlink**; 29510-29520 guard; 29520-29590 FM repeater
  inputs; 29600 FM calling, 29610 simplex repeater; 29620-29690 FM repeater
  outputs ("Desplazamiento: -100 kHz", input 100 kHz below output).

VHF/UHF/SHF:
- 6 m: 50.000-50.100 CW 500 (50.000-50.030 synchronised beacon project);
  50.100-50.130 intercontinental, 50.130-50.200 international (50.150);
  50.200-50.300 general SSB/CW; 50.300-50.400 MGM (EME 50.310-50.320, MS
  50.320-50.380); **50.400-50.500 beacons exclusive**; 50.500-52.000 all modes
  12 kHz; repeater inputs 51.210-51.390, outputs 51.810-51.990 (20 kHz) —
  **input 600 kHz below output**; FM simplex 51.410-51.590, 51.510 calling.
- 4 m: 70.150-70.250 all modes, 70.200 SSB/CW centre.
- 2 m: 144.000-144.110 CW/EME 500 (**144.0025-144.025 satellites**, 144.050 CW
  call, 144.100 MS); 144.110-144.150 CW/MGM (EME MGM); 144.150-144.400 CW/SSB/MGM
  2700 (144.300 SSB calling, 144.370 FSK441); **144.400-144.491 beacons
  exclusive** (144.492 WSPR); 144.500-144.794 all modes 20 kHz (144.630-144.660
  transponder inputs, 144.660-144.690 outputs); 144.794-144.9695 MGM/digital
  (144.800 APRS, DV gateways 144.8125-144.8625); **144.975-145.194 repeater
  inputs**; 145.194-145.206 space comms; 145.206-145.5625 FM/DV simplex (145.500
  FM calling); **145.575-145.7935 repeater outputs** (−600 kHz, input below
  output); 145.794-145.806 space comms; **145.806-146.000 satellites**. No FM in
  144.000-144.500.
- 70 cm: 430.000-431.975 all modes 20 kHz (430.400-430.575 digital links,
  430.600-430.925 digital repeater inputs, 431.050-431.825 analogue repeater
  inputs, paired with outputs 438.650-439.425 — **7.6 MHz, input below
  output** [derived from the IARU HB/DL/OE system]); 432.000-432.025 EME;
  432.025-432.100 CW/MGM; 432.100-432.400 CW/SSB/MGM (432.200 SSB); **432.400-
  432.490 beacons**; 432.500-432.975 all modes (repeater inputs with 2 MHz
  shift); **433.000-433.375 repeater inputs**, outputs **434.600-434.975**
  (1.6 MHz, input below output); 433.400-433.575 FM/DV simplex (433.450 DV,
  433.500 FM calling); 433.600-434.000 all modes (433.800 APRS alternative);
  434.000-434.594 all modes and ATV; **435.000-438.000 satellites** (and ATV per
  URE); 438.000-440.000 sub-regional (438.025-438.175 digital, 438.200-438.525
  digital repeater outputs, 438.550-438.625 multimode, 439.800-439.975 digital
  links). No FM in 432.000-432.500.
- 23 cm (URE plan predates UN-122; inputs near 1270 MHz now limited to −17 dBW
  EIRP): 1240-1241 digital; 1241-1243.25 all modes; 1243.25-1260 ATV/DATV;
  **1260-1270 satellites**; 1270.000-1270.700 FM repeater inputs, 1270.725-
  1271.250 digital repeater inputs; 1272-1290.994 ATV; 1290.994-1291.481 FM
  repeater inputs; 1291.494-1296 all modes; 1296.000-1296.025 EME; 1296.025-
  1296.150 CW/MGM; 1296.150-1296.800 CW/SSB/MGM (1296.200 SSB); **1296.800-
  1296.994 beacons**; 1296.994-1297.481 FM repeater outputs (−6 MHz, input below
  output); 1297.494-1297.981 FM simplex (1297.500); 1298.000-1298.500 FM repeater
  outputs and 1298.525-1298.700 digital repeater outputs (**−28 MHz, input below
  output**); 1298.725-1300 all modes/digital. U2 reports IARU proposals (Vienna,
  Sep 2026) to move repeater inputs to 1257.000-1257.475 (+40 MHz) or
  1257.025-1257.975 (+41 MHz) — not yet in U1 **[secondary]**.
- 13 cm: 2300-2320 all modes; 2320.000-2320.025 EME; 2320.025-2320.150 CW;
  2320.150-2320.800 CW/SSB; **2320.800-2321.000 beacons**; 2321-2322 FM;
  2322-2355 ATV; 2355-2365 digital; 2365-2370 repeaters; 2370-2392 ATV;
  2392-2400 digital; **2400-2450 satellites** (2427-2443 ATV if unused by
  satellites). Note: only 2316-2332 is free of special authorisation.
- 6 cm: **5650-5670 satellite uplink** (5668.2 narrowband); 5670-5700 digital;
  5700-5720 ATV; 5720-5760 all modes; 5760-5762 narrowband (5760.2); 5762-5790
  all modes; **5790-5850 satellite downlink**.
- 3 cm: 10000-10150 digital; 10150-10250 all; 10250-10350 digital; 10350-10368
  all; 10368-10370 narrowband (10368.2); 10370-10450 all; **10450-10500
  all modes/satellites**.
- 24 GHz: 24000-24048 all; 24048-24050 satellites/narrowband (24048.2);
  24050-24250 all (24125 wideband).

Differences from IARU R1:
- HF plan text is the older (pre-Novi-Sad 2020) R1 HF plan (1838-1840 narrow
  segment, 3600-3620 digital/unattended).
- 4 m restricted to 70.150-70.250 MHz.
- URE lists the full 70 cm IARU sub-regional repeater systems; no Spanish-only
  repeater system was found.
- Satellite segment 144.0025-144.025 MHz appears in URE's 2 m plan.

## 8. Confidence and gaps

**Overall: medium-high.** Bands and primary/secondary status were read from the
current CNAF (in force 18 Jul 2026) page by page; the power table and the 50 %
rule are verbatim from the BOE. Confidence is lowered by the derived secondary-
band figures and by URE contradicting them in places.

UNCONFIRMED / conflicts:
- **50 MHz and 70 MHz power.** Law as read: secondary (CNAF national column,
  UN-100, UN-132 "con carácter secundario") → 600 W × 50 % = **300 W PEP
  [derived]**. URE [U1] states "600 W máximo + antena de 6dB máximo" (50 MHz)
  and "600W PEP máximo" (70 MHz). The 6 dB antenna rule is not in B1/B1c and
  probably comes from the repealed 2006 order. Encode 300 W PEP (the safe
  reading) and flag; ask URE/SETID if this matters.
- The SA requirement for 76-81, 122, 136-141, 241-248 GHz is from URE only
  **[secondary]**; DA2 [B2] lists only 2300-2450, 5650-5850 and 24.05-24.25 GHz
  (but allows the SETID to update the list).
- 60 m bandwidth/mode conditions [UNCONFIRMED]; only 15 W EIRP is primary.
- 1240-1258 MHz ITU-R M.2164 values in U2 are guidance, not encoded.
- The CNAF pages are scanned images; values were read visually. Pages read:
  98, 101, 104, 110-116, 119-130, 134, 146, 151, 161, 170, 174-175, 190, 200,
  206-207, 211-212, 216-218 (tables); 252, 255, 259, 264 (UN notes).
- **Pending / time-limited**: S1 (QO-100) expires 26 Dec 2026; S2 (160 m
  contests) 31 Dec 2026; S3 (8 m) ≈ Apr 2027. IARU 23 cm re-planning after
  ECC/DEC/(25)01 (Vienna, Sep 2026) not yet reflected in URE's plan.
