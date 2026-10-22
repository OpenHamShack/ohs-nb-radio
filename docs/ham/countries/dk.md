# Denmark (DK): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**Headline:** Denmark re-issues its frequency order every year or so. The
current one is **BEK nr. 499 af 29. maj 2026**, in force **1 July 2026**
(replacing BEK 1423 of 25 Nov 2025, which replaced BEK 939 of 18 Jun 2025 —
the amateur annex is unchanged across all three). The regulator is now
**Digitaliseringsstyrelsen** (the BEK uses that name; the task brief's
"SDFI / Energistyrelsen" are its predecessors). Three certificate categories,
**A, B and D**; A = HAREC/CEPT, B = CEPT Novice, D = national entry level
(VHF and up, 50 W, factory-built gear only). Denmark has unusually generous
allocations: **60 m 5250-5450 kHz at up to 1000 W**, 4 m 69.8875-70.5125 MHz,
3.4 GHz, and **QO-100 uplink at 250 W (A) / 100 W (B)**. Several 23 cm changes
are already dated **1 January 2029**.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| D1 | Lovtidende A, "Bekendtgørelse om anvendelse af radiofrekvenser uden tilladelse samt om amatørradioprøver og kaldesignaler m.v.", **Nr. 499** | dated 29. maj 2026, "Udgivet den 2. juni 2026", § 23: "træder i kraft den 1. juli 2026"; j.nr. 2026-467; 41 pages | https://www.retsinformation.dk/eli/lta/2026/499/pdf (identical file at https://www.lovtidende.dk/api/pdf/256437) | `c31d1b18e2e2763adf6ed2ca1844c89329226a4c18482b3a0297a94a96430fe5` | Danish |
| D2 | Same title, BEK nr. 1423 af 25/11/2025 — retsinformation print marked "**(Historisk)**", printed 8 Oct 2026 | repealed by D1 § 23 stk. 2 | https://www.retsinformation.dk/api/pdf/253831 | `b93e4f29e2b3545cb2beb45ced529f0e024a38f5a7846d8af3517e240eb4d4fd` | Danish |
| D3 | Same title, Nr. 939 af 18. juni 2025 (Lovtidende) | in force 1 Jul 2025; superseded | https://www.lovtidende.dk/api/pdf/250849 | `7f3418181627da77ea6223c50d5f6d2437566a1547111402b214f4f10c0a09d1` | Danish |
| D4 | Bekendtgørelse af lov om radiofrekvenser (LBK nr. 119 af 21/01/2026) — the law D1 is made under | 21 Jan 2026 | https://www.retsinformation.dk/eli/lta/2026/119/pdf | `012d4fb9f336b989a51d354b658699b623acc6c834b81fbf4e73d76ba9f7989b` | Danish |
| D5 | Digitaliseringsstyrelsen, web page "Radioamatører" | fetched 2026-10-08 (lists exams to Dec 2026) | https://digst.dk/tele/frekvenser/radioamatoerer/ | `64e584ed1f0802eff7c834467242d33905eb5151546bbd165bf2cb87078eb34d` (HTML snapshot) | Danish |
| D6 | Digitaliseringsstyrelsen, "Vejledning om amatørradioprøver" | "marts 2026"; PDF 23 Mar 2026 | https://digst.dk/media/iwwfz5lp/vejledning-om-amatoerradioproever-2026.pdf | `66ac9509af804a18e9d8e6d57e9c23508026618ae4d8863c121a36b01621e416` | Danish |
| E1 | EDR, "VUSHF båndplan" web page ("Båndplanen er kopieret fra VUSHF-udvalgets hjemmeside") | undated; fetched 2026-10-08 | https://www.edr.dk/baandplan-vushf/ | `0052e14e10bd893f61823d0cfbd8667d91101772900d0e4526ab815eb8f689a6` (HTML snapshot) | Danish |
| E2 | EDR, "Båndplan HF" web page | "3. juli 2020", updated "21. juni 2021" | https://edr.dk/2020/07/03/7464/ | `9e173db563a236606cd33ac3cd5abbc371fe73efc73a376237ab350add45d93c` (HTML snapshot) | English/Danish |
| C1 | CEPT Recommendation T/R 61-01, Annex 2 | "latest updated on 18 October 2024", annex "Edition of 16 February 2024" | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | English |
| C2 | ECC/REC/(05)06, Annex 2 | "Edition 16 February 2024" | https://docdb.cept.org/download/4413 | `30f2b55b5d3b30289b6e4ca847dbb3623435592512e99d2ad4a8e748615155d3` | English |

PDFs fetched 2026-10-08, HTTP 200, `pdftotext -layout`. Page numbers are D1's
printed page numbers (= PDF pages). Bilag 4 (the amateur annex) is pp.13-18.

## 1. Regulator and legal instruments

- **Regulator:** **Digitaliseringsstyrelsen** (Ministry of Digitalisation),
  Landgreven 4, København [D1, D5]. (Earlier: Energistyrelsen, then SDFI;
  D2's journal header reads "Digitaliseringsmin., Digitaliseringsstyrelsen".)
  The frequency register is still at frekvensregister.sdfi.dk.
- **Law:** lov om radiofrekvenser, LBK nr. 119 af 21. januar 2026 [D4].
- **Order:** **BEK nr. 499 af 29/05/2026** [D1]. § 5: amateur and
  amateur-satellite frequencies in **Bilag 4** may be used without a licence
  ("må anvendes uden tilladelse") subject to Bilag 4's powers, requirements and
  limits. §§ 14-17 exams and certificates; §§ 18-20 call signs; § 22 fines;
  § 23 in force 1 July 2026, repeals BEK 1423/2025.
- **Pending / dated changes (written into D1 Bilag 4):** from **1 January
  2029**: 1258-1296 MHz removed; 1296-1298 MHz and 23 cm beacon/digi/repeater
  powers drop to 50 W; satellite 1262-1270 MHz removed; 1260-1262 MHz loses
  category D and becomes elevation-dependent (ECC/DEC/(25)01); the −6 MHz 23 cm
  repeater pairing ends. Denmark has re-issued this order mid-year in 2025 and
  2026, so a mid-2027 version is likely. **[UNCONFIRMED]** that no amendment
  after D1 exists (retsinformation's status page is a JavaScript app; the
  RetsNyt notice "Nye regler for radioamatører og skibe fra 1. juli 2026"
  matches D1).
- **Faroe Islands (OY) and Greenland (OX)** are not covered by D1: Greenland
  has its own "Bekendtgørelse for Grønland om anvendelse af radiofrekvenser
  uden tilladelse" and the Faroes their own regulator (Fjarskiftiseftirlitið).
  **Not researched here** — treat OX/OY as separate countries in code.

## 2. Licence classes

D1 § 14: "Digitaliseringsstyrelsen afholder skriftlige prøver til opnåelse af
certifikat i kategorierne A, B og D." Bilag 6 (p.32): "Kategori A: Almindelig
teknisk prøve, begrænset teknisk prøve samt ikke-teknisk prøve. Kategori B:
Begrænset teknisk prøve, samt ikke-teknisk prøve. Kategori D: Ikke-teknisk
prøve." (A: full technical + limited technical + non-technical; B: limited
technical + non-technical; D: non-technical only.)

| class id (lowercase, for code) | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `a` | Certifikat kategori A | HAREC; D1 § 15 stk. 2: HAREC certificate per T/R 61-02 may be issued to category A holders | **T/R 61-01**: "Denmark OZ A", "Faroe Islands OY A", "Greenland OX A" [C1 p.5] | OZ, OU, OV, 5P, 5Q (free choice) |
| `b` | Certifikat kategori B | limited technical + non-technical | **ECC/REC/(05)06 Novice**: "Denmark OZ B", "Faroe Islands OY B", "Greenland OX B" [C2 p.5] | same |
| `d` | Certifikat kategori D | non-technical only (20 questions, 15 to pass) | **none** (national) | same |

Category D extra rule (Bilag 4 pkt. 3.1 nr. 5, p.17): "Personer, der har
Kategori D-certifikat, må alene benytte fabriksfremstillede radioanlæg, som
ikke er undtaget fra bestemmelserne i bekendtgørelse om radioudstyr og
elektromagnetiske forhold." — *D holders may only use factory-made equipment
that is not exempt from the radio-equipment (RED/EMC) order*, i.e. CE-marked
commercial radios only. (An SDR such as a Pluto used as an amateur TX is
not that [derived]; warn D users.)

Supervised use (pkt. 3.1 nr. 3-4): a B holder may use A powers under physical
supervision of an A holder; a D holder may use B (or A) frequencies, powers and
equipment under physical supervision of a B (or A) holder.

## 3. Permitted bands and power, per class

**Power reference** (Bilag 4 pkt. 2, p.16): "Ved sendeeffekt forstås
spidssendeeffekt (PEP), det vil sige den maksimale middeleffekt, som senderen i
løbet af en periode af HF-signalet afgiver til en refleksionsfri belastning på
50 ohm ... Effekten måles med et spidsvisende effektmeter på det sted, hvor
antennen (antennekablet) eller en antennetuner tilsluttes senderens sidste
trin." — *Transmit power means PEP, the maximum mean power delivered by the
transmitter during one RF cycle into a matched 50 Ω load ..., measured with a
peak-reading meter where the antenna (cable) or tuner connects to the final
stage.* So all figures are **W PEP at the transmitter output**, except LF/MF:
"I frekvensbåndene 135,7-137,8 kHz og 472-479 kHz forstås ved sendeeffekt den
effektivt udstrålede effekt (ERP), det vil sige den til antennen tilførte spids
sendeeffekt multipliceret med antennens virkningsgrad." (p.17) — *in 135.7 and
472 kHz, transmit power means ERP, i.e. the PEP fed to the antenna multiplied
by the antenna's efficiency.* "Tilsvarende begrænsninger gælder for et
eventuelt tilsluttet forstærkertrin." — *the same limits apply to any added
amplifier.*

Status (primary/secondary) is not stated in D1. Table "1.1 Amatørradiotjenesten
- bemandede radioanlæg" (manned stations, p.13), "0" = not permitted (shown —):

| lo Hz | hi Hz | band | `a` | `b` | `d` | notes | source |
|---|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | 1 W ERP* | 1 W ERP* | — | *ERP as defined above | D1 Bilag 4 1.1 p.13, pkt. 2 p.17 |
| 472 000 | 479 000 | 630 m | 1 W ERP* | 1 W ERP* | — | | same |
| 1 810 000 | 1 850 000 | 160 m | 1000 W PEP | 100 W PEP | — | | p.13 |
| 1 850 000 | 2 000 000 | 160 m | **10 W PEP** | **10 W PEP** | — | | p.13 |
| 3 500 000 | 3 800 000 | 80 m | 1000 W | 100 W | — | | p.13 |
| 5 250 000 | 5 450 000 | 60 m | **1000 W** | **100 W** | — | national: whole 5250-5450 kHz | p.13 |
| 7 000 000 | 7 200 000 | 40 m | 1000 W | 100 W | — | | p.13 |
| 10 100 000 | 10 150 000 | 30 m | 1000 W | 100 W | — | | p.13 |
| 14 000 000 | 14 350 000 | 20 m | 1000 W | 100 W | — | | p.13 |
| 18 068 000 | 18 168 000 | 17 m | 1000 W | 100 W | — | | p.13 |
| 21 000 000 | 21 450 000 | 15 m | 1000 W | 100 W | — | | p.13 |
| 24 890 000 | 24 990 000 | 12 m | 1000 W | 100 W | — | | p.13 |
| 28 000 000 | 29 700 000 | 10 m | 1000 W | 100 W | 50 W | | p.13 |
| 50 000 000 | 52 000 000 | 6 m | 1000 W | 100 W | 50 W | | p.13 |
| 69 887 500 | 70 512 500 | 4 m | **25 W** | **25 W** | **25 W** | national edges 69.8875-70.5125 | p.13 |
| 144 000 000 | 146 000 000 | 2 m | 1000 W | 100 W | 50 W | | p.13 |
| 432 000 000 | 438 000 000 | 70 cm | 1000 W | 100 W | 50 W | 430-432/438-440 not amateur | p.13 |
| 1 240 000 000 | 1 258 000 000 | 23 cm | 250 W | 100 W | 50 W | | p.13 |
| 1 258 000 000 | 1 296 000 000 | 23 cm | 250 W | 100 W | 50 W | **band removed from 2029-01-01** (note 1) | p.13 |
| 1 296 000 000 | 1 298 000 000 | 23 cm | 250 W → **50 W from 2029** | 100 W → **50 W from 2029** | 50 W | note 2 | p.13-14 |
| 1 298 000 000 | 1 300 000 000 | 23 cm | **500 W** if antenna ≥30 dBi and elevation ≥15°, else **160 W** | same as A | 50 W | note 3 | p.13-14 |
| 2 400 000 000 | 2 450 000 000 | 13 cm | 250 W | 100 W | — | 2300-2400 not amateur | p.13 |
| 3 400 000 000 | 3 410 000 000 | 9 cm | 250 W | 100 W | — | | p.13 |
| 5 650 000 000 | 5 850 000 000 | 6 cm | 250 W | 100 W | — | | p.13 |
| 10 000 000 000 | 10 500 000 000 | 3 cm | 250 W | 100 W | — | | p.13 |
| 24 000 000 000 | 24 250 000 000 | 1.2 cm | 250 W | 100 W | — | | p.13 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | 250 W | 100 W | — | | p.13 |
| 76 000 000 000 | 81 500 000 000 | 4 mm | 250 W | 100 W | — | | p.13 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | 250 W | 100 W | — | | p.13 |
| 134 000 000 000 | 141 000 000 000 | 2 mm | 250 W | 100 W | — | | p.13 |
| 241 000 000 000 | 250 000 000 000 | 1 mm | 250 W | 100 W | — | | p.13 |

Table "1.5 Amatørradiosatellittjenesten - bemandede radioanlæg" (amateur-
satellite, manned, p.16) — same powers, these ranges: 7000-7100 kHz,
14.000-14.250, 18.068-18.168, 21.000-21.450, 24.890-24.990 MHz (A 1000 / B 100
/ D —); 28.0-29.7, 144-146, **435-438 MHz** (A 1000 / B 100 / D 50); **1260-1262
MHz** (A 250 / B 100 / D 50; note 1: "Kategori D udgår og sendeeffekten gøres
afhængig af elevationsvinklen fra 1. januar 2029, jf. ECC/DEC/(25)01"); **1262-1270
MHz** (A 250 / B 100 / D 50; note 2: "Frekvensbåndet udgår fra 1. januar 2029");
**2400-2450 MHz** (A 250 / B 100 / D —); 3400-3410; 5660-5670 MHz; **10.45-10.50
GHz**; 24.00-24.05; 47.0-47.2; 76.0-81.5; 134-141; 241-250 GHz (A 250 / B 100 /
D —).

Unattended stations (tables 1.2 beacons, 1.3 digipeaters/mailboxes, 1.4
repeaters, pp.14-16) are separately limited to listed sub-bands at A/B 100 W,
D 50 W (4 m 25 W). OpenHamShack HAM is an attended station; not encoded, but the
repeater table is useful for shifts (§7).

**Original wording (D1), with translation:**
- Bilag 4 title (p.13): "Radiofrekvenser til amatørradio- og
  amatørradiosatellittjenesten, der under overholdelse af bestemte
  sendeeffekter samt øvrige krav og begrænsninger må anvendes uden tilladelse,
  jf. § 5" — *Frequencies for the amateur and amateur-satellite services that
  may be used without a licence subject to specified transmit powers and other
  requirements.*
- "Det er herunder anført, hvilke frekvensbånd og hvilke sendeeffekter
  certifikaterne i kategorierne A, B og D giver adgang til at anvende." — *Listed
  below are the bands and powers that certificates A, B and D give access to.*
- Rows verbatim (1.1, "Frekvensbånd | Kategori A | Kategori B | Kategori D"):
  "135,7-137,8 kHz 1W 1W 0"; "472-479 kHz 1W 1W 0"; "1810-1850 kHz 1000 W 100
  W 0"; "1850-2000 kHz 10 W 10 W 0"; "3500-3800 kHz 1000 W 100 W 0";
  "5250-5450 kHz 1000 W 100 W 0"; "7000-7200 kHz 1000 W 100 W 0";
  "10,1000-10,1500 MHz 1000 W 100 W 0"; ... "28,0000-29,7000 MHz 1000 W 100 W
  50 W"; "50,0000-52,0000 MHz 1000 W 100 W 50 W"; "69,8875-70,5125 MHz 25 W 25W
  25 W"; "144-146 MHz 1000 W 100 W 50 W"; "432-438 MHz 1000 W 100 W 50 W";
  "1240-1258 MHz 250 W 100 W 50 W"; "1258-1296 MHz1) 250 W 100 W 50 W";
  "1296-1298 MHz 250 W2) 100 W2) 50 W"; "1298-1300 MHz 500 W3) 500 W3) 50 W";
  "2400-2450 MHz 250 W 100 W 0"; "3400-3410 MHz 250 W 100 W 0"; ...
- Notes (p.13-14): "1) Frekvensbåndet udgår fra 1. januar 2029." — *The band is
  withdrawn from 1 January 2029.* "2) Sendeeffekten reduceres til 50 W fra 1.
  januar 2029." — *Power is reduced to 50 W from 1 January 2029.* "3)
  Antenneforstærkning ≥ 30 dBi og elevation ≥15 grader ellers 160 W." —
  *Antenna gain ≥30 dBi and elevation ≥15°, otherwise 160 W.*

### 3.1 Per-band exceptions

- **60 m:** **5250-5450 kHz, A 1000 W PEP, B 100 W PEP**; no EIRP limit, no
  channelisation in law. Far wider and stronger than WRC-15 (15 W EIRP). The
  8 kHz HF bandwidth limit applies.
- **160 m:** 1850-2000 kHz is 10 W PEP for A and B.
- **4 m:** 69.8875-70.5125 MHz, **25 W PEP for all three categories**. The
  edges extend 12.5 kHz beyond 69.9-70.5 (a channelisation artefact [derived]).
- **23 cm:** dated changes on 2029-01-01 (above). 1298-1300 MHz: 500 W only
  with ≥30 dBi and ≥15° elevation, otherwise 160 W — the guard can check the
  gain from the antenna chain but not the elevation; encode 160 W and let EME
  be an operator override [derived].
- **Bandwidth (Bilag 4 pkt. 3.2, p.17)** — law, enforce:
  "1) I frekvensbånd under 1810 kHz må senderens spektralbredde ikke overstige
  2,1 kHz. 2) I frekvensbånd mellem 1810 kHz og 30 MHz må senderens
  spektralbredde ikke overstige 8 kHz. 3) I frekvensbånd mellem 50 og 146 MHz
  må senderens spektralbredde ikke overstige 16 kHz. 4) I frekvensbånd over 146
  MHz må senderens spektralbredde ikke overstige det pågældende amatørbånds
  bredde." — *below 1810 kHz ≤ 2.1 kHz; 1810 kHz-30 MHz ≤ 8 kHz; 50-146 MHz ≤
  16 kHz; above 146 MHz ≤ the band's width.* Measured at −6 dB up to 146 MHz
  (and −60 dB one bandwidth outside the band edges), at −60 dB above 146 MHz.
- **Category D:** factory-built, non-exempt (CE) equipment only.
- **Encryption (pkt. 3.3 nr. 4, p.18):** "Ved internationale forbindelser (inkl.
  Grønland og Færøerne) og ved anvendelse af frekvensbånd i henhold til punkt
  1.4. og 1.5. må udsendelser ikke krypteres." — *no encryption on
  international contacts (incl. Greenland/Faroes) or on repeater (1.4) and
  satellite (1.5) bands.* Domestic encrypted contacts on other bands are not
  forbidden by this wording [derived].
- **Identification (pkt. 3.1 nr. 1):** call at start and end of each contact
  and **at least every ten minutes**.
- **Antenna gain:** only the 1298-1300 MHz 30 dBi condition.
- **No geographic exclusions** in Denmark proper; OX/OY are outside D1.

### 3.2 Gaps: not permitted for any class (list explicitly)

Within 135.7 kHz - 10.5 GHz: 137.8-472 kHz; 479-1810 kHz; 2000-3500 kHz;
3800-5250 kHz; 5450-7000 kHz; 7200-10 100 kHz; 10 150-14 000 kHz;
14 350-18 068 kHz; 18 168-21 000 kHz; 21 450-24 890 kHz; 24 990-28 000 kHz;
29.7-50 MHz; 52-69.8875 MHz; 70.5125-144 MHz; 146-432 MHz (**430-432 MHz
not amateur**); **438-440 MHz**; 440-1240 MHz; 1300-2400 MHz (**incl.
2300-2400 MHz**); 2450-3400 MHz; 3410-5650 MHz; 5850-10 000 MHz; 10.5-24 GHz.
From 2029-01-01 add **1258-1296 MHz**.

For `d`: everything below 28 MHz; 29.7-50 MHz; and everything above 1300 MHz.

## 4. Satellite / QO-100

- **2400-2450 MHz is in both table 1.1 (amateur) and table 1.5
  (amateur-satellite, manned stations):** **`a` 250 W PEP, `b` 100 W PEP, `d`
  not permitted** [D1 Bilag 4 1.1 p.13, 1.5 p.16]. No extra permission, no
  EIRP cap. (So Danish A/B holders may legally run far more than QO-100 needs;
  AMSAT-DL's EIRP guidance still applies as band-plan advice.)
- **10.45-10.50 GHz:** amateur-satellite for A (250 W) and B (100 W).
- Satellite operation must not be encrypted (pkt. 3.3 nr. 4).
- 1260-1270 MHz satellite uplink: A 250 / B 100 / D 50 W now; from 2029 only
  1260-1262 MHz with elevation-dependent power and no D.

## 5. CEPT / visiting operators

- **T/R 61-01:** implemented; Category A = CEPT licence (C1: "Denmark OZ A;
  Faroe Islands OY A; Greenland OX A").
- **ECC/REC/(05)06:** implemented; Category B = CEPT Novice (C2: "Denmark OZ
  B; Faroe Islands OY B; Greenland OX B"). Category D has no CEPT equivalent.
- **HAREC (T/R 61-02):** D1 § 15 stk. 2 — HAREC certificate issued to A
  holders; § 16: foreign HAREC certificates count as passed Danish exams.
- **Visitors:** D1 § 16 stk. 2: foreign licences are valid during short stays
  where international agreements Denmark has joined say so; § 19 stk. 2: a
  visitor "kan anvende det udenlandske kaldesignal indledt med »OZ/« under
  kortvarige ophold i Danmark" — *may use their foreign call preceded by "OZ/"
  during short stays.* (A visiting CEPT-licence holder gets Category A rights,
  a CEPT-Novice holder Category B rights [derived from the equivalence tables].)

## 6. Callsigns

- D1 § 18 stk. 3: "Digitaliseringsstyrelsen udsteder kaldesignaler til brug for
  amatørradioformål i følgende kaldesignalserier: OU, OV, OZ, 5P, 5Q" — *call
  signs are issued in the series OU, OV, OZ, 5P, 5Q.*
- **Calls do not encode the category:** D5: "Radioamatøren kan selv vælge sit
  kaldesignal, hvis det er ledigt." — *the amateur may choose any free call
  sign.* A call released becomes reissuable after 25 years (§ 18 stk. 4). So no
  class hint can be derived from a Danish call.
- A call requires a Danish station address (§ 18 stk. 2); clubs (legal
  persons) get calls with a responsible certificate holder.
- **Portable:** D1 has no /P /M rule for Danes; visitors prefix "OZ/".
  OX (Greenland) and OY (Faroes) are separate prefixes/administrations.
- **Regex hints:** `^(OZ|OU|OV|5P|5Q)\d[A-Z]{1,4}$` → Danish, any category.

## 7. National band plan

EDR (Experimenterende Danske Radioamatører) publishes plans as web pages, not
dated PDFs. Neither is versioned; both should be treated as lower confidence.

**HF [E2, dated 3 Jul 2020 / updated 21 Jun 2021]:** follows the IARU R1 HF
plan segments for 80/40/30/20/15 m etc. **Warning: its 160 m and 60 m sections
are not Danish** — 160 m carries "1,850-1,900 ... Max 10 W p.e.p / 1,900-1,950
... Max 100 W p.e.p / 1,950-2,000 ... Max 10 W p.e.p" and 60 m lists eleven
channels 5258.5-5406.5 kHz with widths; these are the **UK (Ofcom/RSGB)**
160 m steps and 60 m channels, not Danish law (Danish law: 1850-2000 kHz 10 W
flat; 60 m 5250-5450 kHz contiguous) [derived by comparison with D1 and
docs/ham/bandplan-r1-uk.md]. **Use the IARU R1 2020 HF plan for Denmark**, with
60 m usage per IARU (5351.5-5366.5) as the only planned part and the rest of
5250-5450 kHz unplanned.

**6 m [E1]** (IARU R1 with Danish channel names):
50.000-50.100 CW only, 500 Hz (50.000-50.010 R1 synchronised beacons, 50.010-
50.020 R2, 50.020-50.030 R3; 50.050 future CW calling; 50.090 intercontinental
CW); 50.100-50.200 CW/SSB 2.7 kHz (50.100-50.130 intercontinental, 50.110 DX
call, 50.130-50.200 international, 50.150 SSB centre); 50.200-50.300 local
CW/SSB (50.200 MS centre, 50.285 crossband); 50.300-50.400 MGM (50.305 PSK31,
50.310-50.320 EME, 50.320-50.380 MS); **50.400-50.500 beacons** (50.401 ±500 Hz
WSPR); 50.500-52.000 all modes 12 kHz (50.510 SSTV, 50.520/.530/.540 FM internet
GW, 50.550 image, 50.600 RTTY, 50.620-50.750 digital, 50.630 DV call; **51.210-
51.390 repeater inputs RF81-99**; 51.410-51.590 FM/DV simplex F41-59; **51.510
FM calling**; **51.810-51.990 repeater outputs RF81-99**). No FM channels below
50.500. Repeater shift **−600 kHz** (also D1 Bilag 4 1.4 note 6 for
51.80375-51.99625 MHz: "Korresponderende indgangsfrekvens: -600 kHz").

**4 m:** E1 reproduces only the IARU R1 70.0-70.5 plan (70.000-70.050 beacons,
70.030 personal beacons; 70.050-70.250 CW/SSB, 70.150 MS call, 70.185
crossband, 70.200 CW/SSB call; 70.250-70.294 all modes, 70.260 AM/FM call;
70.294-70.500 FM 12.5 kHz channels, 70.300 RTTY/fax, 70.3125-70.325 packet,
**70.450 FM call**, 70.4875 packet) and says "Danske radioamatører har kun
begrænset adgang til båndet, se derfor den danske båndplan!" — **the Danish
4 m plan it refers to was not found [UNCONFIRMED]**. From the law: beacons
70.000-70.100 MHz (1.2), repeater outputs 70.4875-70.5125 MHz with input −600
kHz (1.4 note 6) → inputs 69.8875-69.9125 MHz [derived].

**2 m [E1]:** 144.000-144.110 CW only (EME, 144.050 CW call, 144.100 random MS
CW); 144.110-144.150 CW/MGM (EME MGM 144.110-144.160, 144.138 PSK31);
144.150-144.180 CW/SSB/MGM (alt. MGM segment, 144.170 alt. MGM call);
144.180-144.360 CW/SSB (144.195-144.205 random MS SSB, **144.300 SSB call**);
144.360-144.399 CW/SSB/MGM (144.370 MGM call); **144.400-144.491 beacons only**
(144.492 ±500 Hz WSPR); 144.500-144.794 all modes 20 kHz, no unattended
stations (144.500 SSTV, 144.525 ATV SSB talkback, 144.600 RTTY, 144.700 image,
144.750 ATV FM talkback); 144.794-144.9625 MGM (**144.800 APRS**; unattended
packet only here); **144.975-145.194 repeater inputs RV46-RV63** (12.5 kHz);
145.194-145.206 space comms (145.200); 145.206-145.5625 FM/DV simplex V17-V47
(145.2375/145.2875/145.3375 internet GW, 145.300 RTTY local, **145.375 DV
call**, **145.500 FM call**); **145.575-145.7935 repeater outputs**; 145.794-
145.806 space comms (145.800); **145.806-146.000 satellite exclusive**.
Repeaters **−600 kHz** (D1 1.4 note 6 for 145.56875-145.79375).

**70 cm [E1] "EDR (NRAU) Båndplan 432 – 438 MHz":**
432.000-432.025 CW, EME exclusive; 432.025-432.100 CW/MGM (432.050 CW centre,
432.088 PSK31); 432.100-432.400 CW/SSB/MGM (**432.200 SSB centre**, 432.350
microwave talkback, 432.370 FSK441); **432.400-432.490 beacons exclusive**;
432.500-432.600 all modes (432.500 alt. APRS; digital channels U201-U207
432.5125-432.5875 duplex with U361-U367 at +2 MHz); **432.600-432.9875 repeater
inputs only, RU368-399**; 433.000-433.3875 FM/DV 12.5 kHz U240-U271;
433.400-433.5875 FM/DV simplex U272-286 (433.400 SSTV, **433.450 DV call**,
**433.500 FM call (mobile)**); 433.600-434.000 FM/DV 20 kHz (433.600 RTTY,
433.625-433.7875 digital U290-303, 433.700 FAX, 433.950-433.9875 FM internet
GW); 434.000-434.594 (434.0125-434.050 internet GW; digital channels);
**434.600-434.9875 repeater outputs RU368-399**; **435.000-438.000 satellite
exclusive**. Repeaters **−2.0 MHz** (D1 1.4 note 7 for 434.50625-434.99375
MHz: "Korresponderende indgangsfrekvens: -2,0 MHz"). D1 also authorises digital
repeaters on **437.9125-437.9625 MHz, input −4.6 MHz** (433.3125-433.3625),
25 kHz digital (notes 9, 12) — inside the satellite segment of the band plan.
E1 note: show consideration near the German border, where 430-440 use differs.

**23 cm [E1] "EDR (NRAU) Båndplan 1240 – 1300 MHz":** 1240-1241 digital
(reserved narrowband for the future); 1242.025-1242.700 DL repeater outputs
RS01-RS28; 1242.725-1243.250 DL packet duplex RS29-RS50; 1243.250-1260 ATV &
DATV; **1260-1270 satellite only**; 1270.025-1270.700 DL repeater inputs
RS01-RS28 (**+28 MHz**); 1270.725-1271.250 packet; 1272-1290.994 ATV/DATV;
**1291.000-1291.475 NRAU repeater inputs RM00-RM19** (25 kHz); 1291.494-1296
all modes; 1296.000-1296.150 CW/MGM (1296.000-1296.025 EME, 1296.138 PSK31;
CW only 1296.000-1296.135); 1296.150-1296.800 CW/SSB/MGM (**1296.200 centre**,
transponder in 1296.400-1296.600, SSTV/fax 1296.500, transponder out
1296.600-1296.700, 1296.600 data, 1296.750-1296.800 local beacons max 10 W
ERP); **1296.800-1296.994 beacons**; **1297.000-1297.475 NRAU repeater outputs
RM00-RM19**; 1297.494-1297.981 FM/DV simplex SM20-SM39 (**1297.500 FM call**,
1297.725 DV call, 1297.900/1297.975 internet GW); 1298.025-1298.975 DL
repeater outputs RS01-RS39; 1299.000-1299.750 5×150 kHz DD; 1299.750-1300 8×25
kHz FM/DV. Repeater shift by law (D1 1.4 notes 8, 10 for 1296.9875-1297.4875
MHz): "**-6,0 MHz. Denne udgår fra 1. januar 2029**" and "**-40 MHz**" — so
−6 MHz (input 1291.0) until end-2028, −40 MHz (input ~1257.0, which stays legal
after 2029) as the alternative/future pairing [derived]. The ATV segments at
1258-1296 MHz disappear in 2029.

**13 cm [E1]:** IARU R1 2300-2450 plan reproduced verbatim (2320 narrowband
etc.) — **but 2300-2400 MHz is not amateur in Denmark** (D1); only the
2400-2450 "Satellitsegment" part applies (2427-2443 ATV if unused by
satellites). Law also designates 2410-2411 / 2445-2446 MHz repeaters and
2411-2415 / 2446-2450 MHz digipeaters, and beacons at 2400.800-2400.990 MHz.

**9 cm, 6 cm, 3 cm [E1]:** IARU R1 plans (3400.000-3400.800 CW/MGM, 3400.100
EME centre, 3400.800-3400.995 beacons, 3402-3410 planned satellite downlink;
5650-5668 satellite uplink, 5668.200 alt. narrowband, 5670-5700 digital,
5700-5720 ATV, 5760.000-5760.800 narrowband (centre printed "5762,200", likely
5760.200), 5760.800-5760.990 beacons, **5790-5850 satellite downlink**;
10.000-10.150 digital, 10.150-10.250 all, 10.250-10.350 digital, 10.350-10.368
all, 10.368.000-10.368.800 narrowband (10.368.200 centre), 10.368.800-10.369.000
beacons, 10.370-10.450 all, **10.450-10.500 satellite**, 10.450-10.452 alt.
narrowband).

**Differences from IARU R1:**
1. 70 cm: only 432-438 MHz legal; NRAU repeaters 432.600-432.9875 in /
   434.600-434.9875 out, **−2 MHz** (R1: 430/438 MHz, −7.6 MHz); digital
   channel pairs U201-207/U361-367 (+2 MHz); legal digital repeaters at
   437.9125-437.9625 (−4.6 MHz) inside the R1 satellite segment.
2. 13 cm: 2300-2400 MHz absent; EDR still prints the R1 2320 MHz plan.
3. 60 m: legal 5250-5450 kHz far exceeds R1's planned 5351.5-5366.5.
4. 4 m: national edges 69.8875-70.5125 MHz; Danish plan not found.
5. 23 cm: national RM (−6 MHz → −40 MHz) and DL RS channel schemes.
6. EDR's HF page carries UK 160 m / 60 m content — ignore those parts.

## 8. Confidence and gaps

**Overall: high for the licence (law), low-medium for the band plan.** D1 is a
fresh (1 July 2026) official text read in full; every power and band above is
quoted from it with page numbers, and its amateur annex is identical to the two
previous versions (D2, D3). The EDR plans are undated web pages, partly copied
from IARU and (for HF 160/60 m) apparently from the UK.

UNCONFIRMED / open:
- **No amendment after BEK 499/2026** — not verifiable from retsinformation's
  JavaScript page; re-check before release (Denmark re-issues mid-year).
- **Danish national 4 m band plan** — referred to by EDR, not found.
- **Faroe Islands (OY) and Greenland (OX)** — separate rules, not researched.
- **EDR HF page** — not a reliable Danish source for 160 m / 60 m.
- **2029 changes** are already law; the guard should be date-aware for 23 cm.
- Status (primary/secondary) is not given in D1; take from ITU RR / EFIS if
  needed.
