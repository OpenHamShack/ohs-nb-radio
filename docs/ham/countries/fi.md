# Finland (FI): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**Headline:** Finland splits the law in two. **Radiotaajuusmääräys 4 AG/2026 M**
(the national frequency allocation table, in force 31 March 2026) holds every
amateur band, its power and its repeater pairs; **Radioamatöörimääräys 6 K/2019
M** holds the operating rules (power definitions, bandwidths, call signs). Two
classes: **perusluokka** (basic, modules K + T1) and **yleisluokka** (general,
K + T2, HAREC). Power is stated in a peculiar way: one number which is **PEP if
the carrier is suppressed by ≥6 dB, otherwise carrier power**, and above 30 MHz
two numbers (carrier and PEP). **23 cm needs a separate, case-by-case licence.**
QO-100 (2400-2450 MHz) is open to both classes.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| F1 | Traficom, "Radiotaajuusmääräys 4 AG/2026M" with annex "Taajuusjakotaulukko (liite Radiotaajuusmääräykseen 4 AG/2026M)" (211-page table), Dnro TRAFICOM/265115/03.04.05.00/2025 | "Antopäivä: 26.3.2026", "Voimaantulopäivä: 31.3.2026", "Voimassa: toistaiseksi"; repeals 4 AF/2025M; PDF 239 pages | https://www.finlex.fi/api/media/authority-regulation/1070975/mainPdf/main.pdf?typeDiscriminator=traficom-communications (Finlex record https://www.finlex.fi/fi/viranomaiset/maarayskokoelmat/traficom-viestinta/2026/3) | `d272fe71d37a8b953d5ec349185826fc4439e6ac481ef5f50beff26a8b96258b` | Finnish |
| F2 | Liikenne- ja viestintävirasto, "Radioamatöörimääräys", **6 K/2019 M** | "Annettu Helsingissä 9 päivänä huhtikuuta 2019"; § 18: in force 9 April 2019 "toistaiseksi" (Traficom page says "Voimaantulopäivä: 10.4.2019"); repeals 6 J/2018 M; 6 pages | https://www.finlex.fi/api/media/authority-regulation/545106/mainPdf/main.pdf?typeDiscriminator=traficom-communications (record https://finlex.fi/fi/viranomaiset/maarayskokoelmat/traficom-viestinta/2019/45134) | `7c635555b0b78c2930fe1ae6252766689846757c43bef3f2de9ded9f74e2bfd5` | Finnish |
| F3 | Same, official English translation "Regulation governing amateur radio stations and their use" (6 K/2019 M) | 2019 | https://www.finlex.fi/api/media/authority-regulation/687676/mainPdf/main.pdf?typeDiscriminator=traficom-communications | `d1c17ca63eb4898017f9129200fc66384bc16233635b9fced74557b95a4fef4e` | English |
| F4 | Traficom, "Radioamatööriviestinnän taajuusalueet" (Yhteenveto — a summary for amateurs, explicitly a compilation of F1) | dated "15.8.2025" in the header; PDF created 21 May 2026; 4 pages | https://www.traficom.fi/files/media/file/Radioamat%C3%B6%C3%B6riviestinn%C3%A4n%20taajuusalueet.pdf | `3ca7937c455156d9123c99aa6a5d5a71a2f6d3c22e43d3dc671f861ccf6d5dee` | Finnish |
| F5 | Traficom web page "Radioamatööritoiminnan pätevyydet ja taajuudet" | "Sivu on viimeksi päivitetty 8.10.2026" | https://traficom.fi/fi/radioluvat-ja-taajuudet/radiotaajuuksien-kaytto/radioamatooritoiminnan-patevyydet-ja-taajuudet | `f2fabd20ec449e7344829bf82468b93527de29765e0a78d8e64dab104b5b668d` (HTML snapshot) | Finnish |
| F6 | Traficom web page "Qualifications and frequencies in amateur radio operations" (English version of F5) | fetched 2026-10-08 | https://traficom.fi/en/radio-licences-and-frequencies/use-radio-frequencies/qualifications-and-frequencies-amateur-radio-operations | `3179582807be6f936878740ef19cc1ab1ffebb1136ce784083907c0d8bd69962` (HTML snapshot) | English |
| S1 | SRAL, "IARU-taajusjakosuositus" page | "Päivitetty vastaamaan vuoden 2017 tilannetta"; fetched 2026-10-08 | https://www.sral.fi/toiminta/maaraykset/iaru-taajuusjakosuositus/ | `7a4965121ee81d845b0f47d06a44de1868174d28a7e3bf0b92dd2a805c8213cd` (HTML snapshot) | Finnish |
| C1 | CEPT Recommendation T/R 61-01, Annex 2 | "latest updated on 18 October 2024", annex "Edition of 16 February 2024" | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | English |
| C2 | ECC/REC/(05)06, Annex 2 | "Edition 16 February 2024" | https://docdb.cept.org/download/4413 | `30f2b55b5d3b30289b6e4ca847dbb3623435592512e99d2ad4a8e748615155d3` | English |

All fetched 2026-10-08 (HTTP 200), `pdftotext -layout`. F1 references are
"table p.N" = the table's own folio "N (211)"; the PDF page is N + 9.

## 1. Regulator and legal instruments

- **Regulator:** Liikenne- ja viestintävirasto **Traficom**. Exams are taken
  at SRAL (Suomen Radioamatööriliitto) [F5].
- **Law:** laki sähköisen viestinnän palveluista (917/2014), §§ 96-97, 265,
  304 [F1, F2].
- **F1 Radiotaajuusmääräys 4 AG/2026M** (in force 31.3.2026): the allocation
  table; amateur rows say "Katso Liikenne- ja viestintäviraston määräys 6",
  "Pätevyystodistus vaaditaan" (certificate required) and give the power. F1
  § 3.12: "Radioluvassa voidaan perustellusta syystä oikeuttaa yleisluokan
  radioamatööri kokeilua varten käyttämään radioamatööriviestintään
  tarkoitetulla taajuudella suurempaa tehoa kuin taajuusjakotaulukossa
  määrätään." — *A radio licence may, for good reason, entitle a general-class
  amateur to use higher power than the table for experiments* (individual
  "erikoislupa"; not encodable).
- **F2 Radioamatöörimääräys 6 K/2019M**: transmitter construction and use,
  call signs, encryption, bandwidth, spurious emissions.
- **Licence:** a station radio licence ("radiolupa") is required; annual fee;
  renewed every 5 years [F5].
- **Changes in F1 vs 4 AF/2025 (amateur):** removed the 433.000-433.375 /
  434.600-434.975 MHz 1.6 MHz-split repeater sub-bands; added FM calling notes
  at 29.600, 51.510, 145.500, 433.500 MHz; added ECC/DEC/(25)01 and ITU-R
  M.2164 references to 1240-1300 MHz [F1 annex "Radiotaajuusmääräykseen 4
  AF/2025M tehdyt muutokset"].
- **Pending:** F1 is re-issued about yearly (2025 AF → 2026 AG); next likely
  spring 2027. A 2021 temporary amendment to F2 (OF prefix for SRAL's
  centenary) expired 23.12.2021. No other pending change found.
- **Åland (OH0)** and **Market Reef (OJ0)** are under the same Finnish rules
  (call-sign rules in F2 § 6; Traficom gives OJ0 for Märket [F6]).

## 2. Licence classes

F5: "Perusluokan todistuksen saat moduuleilla K ja T1. Yleisluokan
HAREC-todistuksen saat moduuleilla K ja T2." — *The basic-class certificate
needs modules K and T1; the general-class HAREC certificate needs K and T2.*

| class id (lowercase, for code) | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `perus` | Perusluokka (basic) | K (rules/operating) + T1 (basic technical) | **listed under T/R 61-01**: Finland "OH | L, P, T, Y" [C1 p.5] — P = perusluokka; **also** listed in ECC/REC/(05)06 Annex 2 as "Finland OH P" with footnote 1 "Finland has no national licence class equivalent to the CEPT Novice ..." [C2 p.5]. See §5. | OH, OG (chosen), OH0 Åland |
| `yleis` | Yleisluokka (general) | K + T2 = HAREC | **T/R 61-01** (Y) | same |

Older classes still valid: L, T (teknillinen luokka) — both in C1's list; F2
§ 5 treats "yleisluokan tai teknillisen luokan pätevyystodistus" alike for
station supervisors. The power table in F1 knows only "perusluokka" and
"yleisluokka"; **[UNCONFIRMED]** how Traficom maps old L and T holders (most
likely T → yleisluokka rights; not found in F1/F2).

F2 § 9: operating someone else's station must not exceed either the user's or
the station licensee's class; under the licensee's direct supervision the
licensee's class applies.

## 3. Permitted bands and power, per class

**Power reference.** F2 § 3: "4) modulaatiohuipputeholla (pX) radiolähettimen
normaaliolosuhteissa antennin syöttöjohtoon yhden radiotaajuisen jakson aikana
modulaatioverhokäyrän korkeimmassa huipussa antaman tehon keskiarvoa; 5)
kantoaaltoteholla (pZ) moduloimattoman radiolähettimen antennin syöttöjohtoon
yhden radiotaajuusjakson aikana antaman tehon keskiarvoa" — *PEP (pX): the mean
power supplied to the antenna feeder during one RF cycle at the highest crest
of the modulation envelope; carrier power (pZ): the mean power supplied to the
feeder by the unmodulated transmitter during one RF cycle.* Both are
**transmitter output into the feeder**.

F1 qualifies each HF/LF number: "Lukuarvo tarkoittaa modulaatiohuipputehoa,
jos lähetteen kantoaaltoa on vaimennettu vähintään 6 dB. Muissa tapauksissa
lukuarvo tarkoittaa kantoaaltotehoa." — *The figure means PEP if the carrier is
suppressed by at least 6 dB; otherwise it means carrier power.* Above 30 MHz
the rows give a carrier-power limit and a separate, higher PEP limit for
suppressed-carrier emissions.

Encoding hint [derived]: model each row as `(carrier_W, pep_W_if_suppressed)`.
For SSB use the PEP figure; for CW, FM and other unsuppressed emissions use the
carrier figure; for AM the carrier figure applies to the carrier (PEP ≈ 4×).
Whether a single-tone digital mode sent through an SSB exciter (FT8, J2D)
counts as "carrier suppressed" is **not stated** — treat it as carrier power
(the stricter reading).

Status: **pex** = exclusive primary, **pri** = primary shared, **sec** =
secondary, from F4 (F1 encodes status by capitalisation of the service name).

| lo Hz | hi Hz | band | status | `perus` | `yleis` | notes | source |
|---|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | sec | **1 W EIRP** | **1 W EIRP** | "Säteilyteho enintään 1 W EIRP." | F1 table p.4 |
| 472 000 | 479 000 | 630 m | sec | **1 W EIRP** | **1 W EIRP** | BW ≤ 1 kHz (F2 § 16) | F1 p.6 |
| 1 810 000 | 1 850 000 | 160 m | pri | 120 W | 1500 W | PEP if carrier ≥6 dB suppressed, else carrier | F1 p.8 |
| 1 850 000 | 2 000 000 | 160 m | sec | **15 W carrier / 60 W PEP** | **15 W carrier / 60 W PEP** | both classes | F1 p.8 |
| 3 500 000 | 3 800 000 | 80 m | pri | 120 W | 1500 W | | F1 p.14 |
| 5 351 500 | 5 366 500 | 60 m | pri (F4) | **15 W EIRP** | **15 W EIRP** | WRC-15 segment exactly | F1 p.20 |
| 7 000 000 | 7 200 000 | 40 m | pex | 120 W | 1500 W | 7000-7100 also amateur-satellite | F1 p.25 |
| 10 100 000 | 10 150 000 | 30 m | sec | 120 W | 1500 W | BW ≤ 1 kHz (F2 § 16) | F1 p.30 |
| 14 000 000 | 14 350 000 | 20 m | pex | 120 W | 1500 W | 14000-14250 also amateur-satellite | F1 p.36-37 |
| 18 068 000 | 18 168 000 | 17 m | pex | 120 W | 1500 W | also amateur-satellite | F1 p.42 |
| 21 000 000 | 21 450 000 | 15 m | pex | 120 W | 1500 W | also amateur-satellite | F1 p.46 |
| 24 890 000 | 24 990 000 | 12 m | pex | 120 W | 1500 W | also amateur-satellite | F1 p.50 |
| 28 000 000 | 29 700 000 | 10 m | pex | 120 W | 1500 W | also amateur-satellite | F1 p.55 |
| 50 000 000 | 50 500 000 | 6 m | pri | 30 W carrier / 120 W PEP | 150 W carrier / 200 W PEP | Russian-border field-strength limit | F1 p.60 |
| 50 500 000 | 52 000 000 | 6 m | sec | 30 W / 120 W PEP | 150 W / 200 W PEP | same | F1 p.60 |
| 70 000 000 | 70 050 000 | 4 m | sec | **beacons only** (25 W) | **beacons only** (25 W) | station class "Amatöörimajakka (ATM) TX"; BW ≤ 1 kHz | F1 p.61 |
| 70 050 000 | 70 250 000 | 4 m | sec | 30 W | 100 W | regional limits (3.1) | F1 p.62 |
| 70 250 000 | 70 300 000 | 4 m | sec | 25 W | 25 W | regional limits | F1 p.62 |
| 144 000 000 | 146 000 000 | 2 m | pex | 30 W carrier / 120 W PEP | 150 W carrier / 600 W PEP | yleis: **600 W carrier for A1A and digital ≤3 kHz in 144.000-144.150** | F1 p.70, sat. p.72 |
| 432 000 000 | 435 000 000 | 70 cm | pri | 30 W / 120 W PEP | 150 W / 600 W PEP | yleis: 600 W carrier A1A/digital ≤3 kHz in 432.000-432.150 | F1 p.94 |
| 435 000 000 | 436 000 000 | 70 cm | pri | 30 W / 120 W PEP | 150 W / 600 W PEP | **amateur-satellite only** (no terrestrial row) [derived from F1] | F1 p.96 |
| 436 000 000 | 438 000 000 | 70 cm | pri | 30 W / 120 W PEP | 150 W / 600 W PEP | amateur + amateur-satellite; "Laajakaistaiset datalähetteet ovat sallittuja" (wideband data allowed) | F1 p.96-97 |
| 1 240 000 000 | 1 300 000 000 | 23 cm | sec | **separate licence** | **separate licence** | "Luvat myönnetään tapauskohtaisesti ja määräajaksi" | F1 p.118-119, F4, F5 |
| 2 300 000 000 | 2 400 000 000 | 13 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | | F1 p.131 |
| 2 400 000 000 | 2 450 000 000 | 13 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | amateur **and** amateur-satellite rows | F1 p.131 |
| 3 400 000 000 | 3 408 000 000 | 9 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | ends 3408, not 3410 | F1 p.136 |
| 5 650 000 000 | 5 850 000 000 | 6 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | rows 5650-5670 (+sat), 5670-5725, 5725-5830, 5830-5850 (+sat s→E) | F1 p.141-143 |
| 10 000 000 000 | 10 280 000 000 | 3 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | | F1 p.151 |
| 10 368 000 000 | 10 370 000 000 | 3 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | narrowband only | F1 p.151 |
| 10 450 000 000 | 10 500 000 000 | 3 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | amateur + amateur-satellite | F1 p.152 |
| 24 000 000 000 | 24 050 000 000 | 1.2 cm | pri | 30 W / 120 W PEP | 150 W / 600 W PEP | + satellite | F1 p.168 |
| 24 050 000 000 | 24 250 000 000 | 1.2 cm | sec | 30 W / 120 W PEP | 150 W / 600 W PEP | | F1 p.169 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | pex | 30 W / 120 W PEP | 150 W / 600 W PEP | + satellite | F1 p.179 |
| 76 000 000 000 | 77 500 000 000 | 4 mm | sec | same | same | + satellite | F1 p.189 |
| 77 500 000 000 | 78 000 000 000 | 4 mm | pri | same | same | + satellite | F1 p.189-190 |
| 78 000 000 000 | 81 500 000 000 | 4 mm | sec | same | same | rows 78-79, 79-81, 81.0-81.5 (+sat) | F1 p.191-193 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | sec | same | same | | F1 p.200 |
| 134 000 000 000 | 136 000 000 000 | 2 mm | pri | same | same | | F1 p.201 |
| 136 000 000 000 | 141 000 000 000 | 2 mm | sec | same | same | + satellite | F1 p.202 |
| 241 000 000 000 | 248 000 000 000 | 1 mm | sec | same | same | + satellite | F1 p.209 |
| 248 000 000 000 | 250 000 000 000 | 1 mm | pri | same | same | + satellite | F1 p.210 |

Also: repeater-only sub-bands **438.0625-438.1625 MHz** (outputs, −5 MHz)
— F4 lists 438.0625-438.1625 as an amateur band (sec), but F1 gives it only
as "Amatööritoistinasema (ATT) TX" (repeater transmitter); a manned station
may not transmit there [derived].

**Original wording (F1), with translation:**
- HF rows (e.g. 1810-1850 kHz, p.8): "Lähettimen teho perusluokassa enintään
  120 W ja yleisluokassa enintään 1500 W. Lukuarvo tarkoittaa
  modulaatiohuipputehoa, jos lähetteen kantoaaltoa on vaimennettu vähintään
  6 dB. Muissa tapauksissa lukuarvo tarkoittaa kantoaaltotehoa." — *Transmitter
  power at most 120 W in the basic class and 1500 W in the general class. The
  figure means PEP if the carrier is suppressed ≥6 dB, otherwise carrier
  power.*
- 1850-2000 kHz (p.8): "Lähettimen teho enintään 15 W. Modulaatiohuipputeho
  60 W, jos lähetteen kantoaaltoa on vaimennettu vähintään 6 dB." — *Transmitter
  power at most 15 W; PEP 60 W if the carrier is suppressed ≥6 dB.*
- 135.7 kHz / 472 kHz: "Säteilyteho enintään 1 W EIRP." — *Radiated power at
  most 1 W EIRP.* 60 m (p.20): "Säteilyteho enintään 15 W EIRP."
- 6 m (p.60): "Lähettimen teho perusluokassa enintään 30 W. Modulaatiohuipputeho
  120 W, jos lähetteen kantoaaltoa on vaimennettu vähintään 6 dB. Lähettimen
  teho yleisluokassa enintään 150 W. Modulaatiohuipputeho 200 W, jos lähetteen
  kantoaaltoa on vaimennettu vähintään 6 dB." — *Basic: 30 W (120 W PEP with
  suppressed carrier); general: 150 W (200 W PEP).*
- 2 m, 70 cm, 13 cm and up: same wording with "Modulaatiohuipputeho 600 W" for
  the general class.
- 144/432 MHz extra: "Taajuusalueella 144,000 - 144,150 MHz saa yleisluokassa
  läheteluokalla A1A sekä digitaalisilla lähetelajeilla, joiden kaistanleveys
  on enintään 3 kHz, käyttää 600 W kantoaaltotehoa." — *In 144.000-144.150 MHz
  the general class may use 600 W carrier power with A1A (CW) and digital
  emissions of at most 3 kHz bandwidth* (same text for 432.000-432.150).
- 4 m (p.62): "Lähettimen teho perusluokassa enintään 30 W ja yleisluokassa
  enintään 100 W." (70.050-70.250); "Lähettimen teho perusluokassa ja
  yleisluokassa enintään 25 W." (70.250-70.300); beacons 70.000-70.050:
  "Lähettimen teho enintään 25 W."
- 1240-1300 MHz (p.118-119, on the radionavigation/radiolocation rows):
  "Myös radioamatööriliikennettä taajuusalueella 1240 - 1300 MHz. Luvat
  myönnetään tapauskohtaisesti ja määräajaksi. ECC:n päätös ECC/DEC/(25)01.
  ITU-R M.2164 mukainen käyttö." — *Also amateur traffic in 1240-1300 MHz.
  Licences are granted case by case and for a fixed period. ECC/DEC/(25)01;
  use per ITU-R M.2164.* F4: "Taajuusalueen käyttö vaatii erillistä lupaa" —
  *use of the band requires a separate licence*; F5 links an application form
  "Hae radiolupaa radioamatööriliikenteelle taajuusalueelle 1240–1300 MHz".

### 3.1 Per-band exceptions

- **Bandwidth (law, F2 § 16):** "Alle 30 MHz taajuuksilla suurin sallittu
  kaistanleveys on 8 kHz. Taajuusalueilla 50 - 146 MHz suurin sallittu
  kaistanleveys on 18 kHz. Kuitenkin taajuusalueilla 472 - 479 kHz, 10100 -
  10150 kHz ja 70,00 - 70,050 MHz suurin sallittu kaistanleveys on 1 kHz." —
  *Below 30 MHz max 8 kHz; 50-146 MHz max 18 kHz; but 472-479 kHz, 10 100-10 150
  kHz and 70.000-70.050 MHz max 1 kHz.* Above 146 MHz: no numeric limit, only
  F2 § 7 "ei saa käyttää tarpeettoman suurta lähetystehoa tai
  -kaistanleveyttä" (*no unnecessarily high power or bandwidth*). (F2 does not
  give a limit for 135.7 kHz; the 2.1 kHz band width bounds it.)
- **60 m:** 5351.5-5366.5 kHz, 15 W EIRP, both classes. No wider national
  allocation (F1 p.20 shows 5450-5480 kHz as land mobile).
- **160 m:** 1850-2000 kHz is 15 W carrier / 60 W PEP for both classes.
- **6 m regional limit (F1 p.60, F4):** "Radioamatöörilähettimen aiheuttama
  sähkökentän voimakkuus Venäjän Federaation ja Suomen välisellä rajalla 10 m
  korkeudessa ei saa ylittää tasoa +6 dBuV/m yli 10 % ajasta." — *field
  strength at the Russian border, 10 m height, must not exceed +6 dBµV/m for more
  than 10 % of the time.* F4 adds that transmitters may not be used in part of
  Tohmajärvi municipality. Traficom publishes a separate guide for computing
  the 50 MHz field strength. Not encodable; warn users in eastern Finland.
- **4 m regional limits (F1 p.61-62):** "a) Radioamatöörilähettimiä ei saa
  käyttää seuraavien kuntien alueella: Lieksa, Ilomantsi, Joensuu, Kontiolahti,
  Polvijärvi, Juuka, Nurmes, Valtimo, Kuhmo, Hyrynsalmi, Suomussalmi,
  Ristijärvi ja Sotkamo. b) Lähempänä kuin 50 km:n etäisyydellä Venäjän
  Federaation ja Suomen välisestä valtakunnanrajasta lähetysantennin
  pääsäteilykeila ei saa osoittaa suuntaan 0 - 180 astetta ja suurin sallittu
  lähetysteho on 25 W. c) Lähempänä kuin 50 km:n etäisyydellä Norjan ja Suomen
  välisestä valtakunnanrajasta suurin sallittu lähetysteho on 25 W." — *a) no
  amateur TX in those 13 municipalities; b) within 50 km of the Russian border
  the main lobe must not point 0-180° and max 25 W; c) within 50 km of the
  Norwegian border max 25 W.* The app could check a 4 m TX against the station
  locator if it held border geometry; otherwise a setting.
- **2 m / 70 cm weak-signal bonus:** general class 600 W carrier for CW and
  ≤3 kHz digital in 144.000-144.150 and 432.000-432.150 MHz.
- **70 cm:** 435-436 MHz is amateur-**satellite** only; terrestrial use only
  432-435 and 436-438 MHz [derived from F1 rows].
- **23 cm:** not in the general authorisation — separate case-by-case licence;
  the guard should refuse unless a "23 cm licence" setting is added.
- **Power meter rule (F2 § 16):** a transmitter able to exceed the limit must
  have a meter that reliably shows compliance.
- **Encryption (F2 § 8):** forbidden except authentication/integrity parts,
  satellite command links, and control links of specially licensed stations.
- **Unattended stations (F2 § 5):** need a special licence; supervisor must hold
  general or technical class.
- **Aircraft (F2 § 15):** only with approval; below 30 MHz any amateur band,
  above 30 MHz only exclusive (pex) bands.
- **Higher power:** general class may get an individual special licence (F1
  § 3.12); not encodable.

### 3.2 Gaps: not permitted for any class (list explicitly)

Within 135.7 kHz - 10.5 GHz: 137.8-472 kHz; 479-1810 kHz; 2000-3500 kHz;
3800-5351.5 kHz; 5366.5-7000 kHz; 7200-10 100 kHz; 10 150-14 000 kHz;
14 350-18 068 kHz; 18 168-21 000 kHz; 21 450-24 890 kHz; 24 990-28 000 kHz;
29.7-50 MHz; 52-70 MHz; **70.000-70.050 MHz for manned stations (beacons
only)**; 70.3-144 MHz; 146-432 MHz (**430-432 MHz not amateur**); **435-436
MHz terrestrial**; 438-440 MHz (except repeater outputs 438.0625-438.1625);
440-2300 MHz **with 1240-1300 MHz only by separate licence**; 2450-3400 MHz;
**3408-5650 MHz**; 5850-10 000 MHz; **10.280-10.368 GHz**; **10.370-10.450
GHz**; 10.5-24 GHz.

## 4. Satellite / QO-100

- **2400-2450 MHz** carries both a "Radioamatöörisatelliittiliikenne" row and a
  "Radioamatööriliikenne" row [F1 table p.131], same limits: **`perus` 30 W
  carrier / 120 W PEP (suppressed carrier); `yleis` 150 W carrier / 600 W PEP**.
  Secondary. No extra permission; normal station licence.
- **10.45-10.50 GHz:** amateur and amateur-satellite, same limits.
- Other amateur-satellite rows: 7000-7100, 14000-14250, 18068-18168,
  21000-21450, 24890-24990 kHz, 28.0-29.7, 144-146 (incl. 145.800-146.000
  separate row), 435-438 MHz, 5650-5670 MHz (uplink), 5830-5850 MHz
  ("satelliitista maahan", downlink), 24.00-24.05, 47.0-47.2, 76-81.5 GHz.
- 1260-1270 MHz uplinks fall under the separate 23 cm licence.

## 5. CEPT / visiting operators

- **T/R 61-01:** C1 Annex 2: "Finland | OH | L, P, T, Y" and "Aland Islands |
  OH0 | L, P, T, Y" [C1 p.5]. This lists **perusluokka (P)** as equivalent to
  the CEPT licence, although Traficom only calls the general class "HAREC"
  [F5]. A Finnish basic-class holder therefore appears to qualify for CEPT
  operation abroad under T/R 61-01 — **[UNCONFIRMED]** whether host countries
  accept it in practice; the entry may be historical (P was an old class whose
  privileges may have differed).
- **ECC/REC/(05)06:** Finland is listed with "OH | P" but footnote 1: "Finland
  has no national licence class equivalent to the CEPT Novice Radio Amateur
  Licence, but accepts unilaterally visiting operators to use their CEPT Novice
  class licence under following conditions: ... Visiting operators are
  required to follow their own national frequency and power guidelines during
  operation in Finland. Used frequencies and output powers may however under
  no circumstances exceed the Finnish elementary novice class guidelines as
  stated in Regulation FICORA 6." [C2 p.5] — i.e. CEPT Novice visitors are
  capped at perusluokka limits.
- **Visitors (F6):** "Foreign radio amateurs with a CEPT license can operate
  amateur radio in Finland without a special permit for a stay of up to three
  months. The temporary call sign to be used is OH/your call (just the prefix
  OH without district number). If you operate in Åland, you need to use OH0
  instead of OH, and in case you organize a trip to Märket Reef, the correct
  prefix is OJ0." Matches F2 § 6 (4th paragraph): foreign stations prefix
  "OH/" (mainland) or "OH0/" (Åland).

## 6. Callsigns

- **Issue [F5/F6]:** "Kutsumerkit jaetaan normaalisti OH-maatunnusten
  sarjasta ... Ilman toivetta numero on satunnainen. Numero 0 annetaan vain
  Ahvenanmaalla sijaitseville radioamatööriasemille." — *Calls are normally
  from the OH series; without a request the digit is random; digit 0 only for
  stations on Åland.* Default suffix: a free 3-letter group. Custom calls:
  prefix **OH or OG**, digit 1-9, suffix 1-4 characters A-Z/0-9 ending in a
  letter (paid). OG calls and 1-letter-suffix OH calls are time-limited (≤5
  years).
- **Calls do not encode the class** (perus vs yleis) — no class hint possible.
  The digit does not encode a region any more except 0 = Åland [F5].
- **Portable / location rules (F2 § 6):** a call with digit 0 used outside
  Åland must append "/1"-"/9"; a call with another digit used on Åland must be
  prefixed "OH0/" or suffixed "/0"; foreign stations prefix "OH/" or "OH0/";
  any extra suffix may be added after a slash ("lisämerkin tai merkkisarjan").
  Call must be sent at the start of a contact and at least every 10 minutes.
- **Regex hints:** `^(OH|OG)[1-9][A-Z0-9]{0,3}[A-Z]$` mainland;
  `^OH0[A-Z]{1,3}$` Åland (separate DXCC); `^OJ0` Market Reef; `^OF`/`^OI`
  special-event [secondary].

## 7. National band plan

**SRAL has no national band plan of its own.** Its page [S1] says the IARU
Region 1 recommendation applies ("Bandijakotaulukko on suositus, jonka
noudattaminen on vapaaehtoista" — *the band plan is a recommendation,
following it is voluntary*) and links the IARU R1 HF PDF of 2019 and the IARU
V/U/SHF plan. Use the current IARU R1 HF (2020) and VHF Handbook plans for
Finland. SRAL's Finnish notes (translation of the R1 text, "päivitetty
vastaamaan vuoden 2017 tilannetta"):
- highest USB dial: 14347, 18165, 21447, 24987 kHz; lowest LSB dial 1843, 3603,
  7053 kHz; highest USB dial on 60 m 5363 kHz;
- LSB below 10 MHz, USB above, USB on 5 MHz;
- contests not in 3500-3510 and 3775-3800 kHz except DX; no contests on 5, 10,
  18, 24 MHz.

**What is national is in the law (F1)** — repeater pairs and calling
frequencies:

| band | repeater inputs (ATT RX) | outputs (ATT TX) | shift (input rel. output) | spacing | F1 |
|---|---|---|---|---|---|
| 10 m | 29.520-29.590 MHz | 29.620-29.690 MHz | **−100 kHz** | 10 kHz, 8 kHz emission | p.56 |
| 6 m | 51.210-51.390 MHz | 51.810-51.990 MHz (RF81-RF99) | **−600 kHz** | 20 kHz | p.60 |
| 2 m | 144.9750-145.1875 MHz (RV48-RV63) | 145.5750-145.7875 MHz | **−600 kHz** | 12.5 kHz | p.71 |
| 2 m (25 kHz legacy) | 145.000-145.175 MHz (RV48-RV62) | 145.600-145.775 MHz | −600 kHz | 25 kHz | p.71 |
| 70 cm | 432.5000-432.5875 MHz | 434.5000-434.5875 MHz | **−2.0 MHz** | 12.5 kHz | p.95-96 |
| 70 cm | 432.600-432.975 / 432.6000-432.9875 MHz | 434.600-434.975 / 434.6000-434.9875 MHz | **−2.0 MHz** | 25 / 12.5 kHz | p.95-96 |
| 70 cm | 433.0625-433.1625 (12.5 kHz) / 433.075-433.150 (25 kHz) MHz | 438.0625-438.1625 / 438.075-438.150 MHz | **−5.0 MHz** | | p.96-97 |
| 23 cm | — (separate licence) | | | | |

(The 1.6 MHz-split pairs 433.000-433.375 → 434.600-434.975 were deleted on
31.3.2026.)

FM calling frequencies written into F1: **29.600, 51.510, 145.500, 433.500
MHz**. 70.000-70.050 MHz is a legal beacon-only segment.

For everything else (CW/SSB segments, beacon segments 50.400-50.500,
144.400-144.490, 432.400-432.490 MHz, satellite segments 145.806-146.000,
435-438 MHz, 2400-2450 MHz) follow IARU R1.

**Differences from IARU R1:**
1. 70 cm: only 432-438 MHz; repeaters −2.0 MHz (R1: −7.6 MHz on 430/438) and a
   −5 MHz pair with outputs at 438.0625-438.1625; 435-436 MHz satellite-only in
   law.
2. 4 m: only 70.000-70.300 MHz; 70.000-70.050 legal beacon segment; regional
   exclusions in the east.
3. 23 cm: not generally available.
4. 9 cm ends 3408 MHz; 3 cm is three pieces (10.000-10.280, 10.368-10.370,
   10.450-10.500 GHz).
5. 160 m upper part low power (15 W / 60 W PEP).

## 8. Confidence and gaps

**Overall: high for the licence (law), medium for the band plan.** F1 (in
force 31.3.2026) and F2 are the current official texts, downloaded, hashed and
read row by row; every limit above is quoted with the table page. Finland has
no national band plan beyond what the law fixes; SRAL defers to IARU R1.

UNCONFIRMED / open:
- **Power reference for constant-envelope digital via SSB** (J2x) — "carrier
  suppressed ≥6 dB" not defined for it; stricter carrier reading proposed.
- **Old class letters L and T** — rights in today's table not stated in F1/F2.
- **T/R 61-01 listing of P (perusluokka)** vs Traficom calling only yleisluokka
  "HAREC" — conflicting signals about basic-class CEPT use abroad.
- **F4 vs F1 discrepancies:** F4 lists 6 m as 50.500-51.990 MHz secondary and
  438.0625-438.1625 MHz as a band; F1 (law) has 50.500-52.000 MHz and only
  repeater outputs at 438.06-438.16. Use F1.
- **23 cm licence terms** (power, segments) — case by case; not public.
- **OJ0 Market Reef** — Traficom web page only (F6), not in F2.
- Next F1 revision expected ~March 2027.
