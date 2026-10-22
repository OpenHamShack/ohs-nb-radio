# Norway (NO): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**Headline:** Norway replaced its amateur regulation on **23 March 2026**. The
2009 "Forskrift om radioamatørlisens" (FOR-2009-11-05-1340) is repealed; the
law is now **"Forskrift om radioamatørvirksomhet" (FOR-2026-03-23-465)**, which
introduces a second, national-only class ("begrenset lisens") and splits 23 cm
from 1 January 2028. Anything written about Norway before April 2026 (including
the NRRL band-plan PDFs, all dated 2018/2019) predates it.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| N1 | Lovdata, "Forskrift om radioamatørvirksomhet", FOR-2026-03-23-465 (consolidated "SF" view) | Fastsatt 23.03.2026, i kraft 23.03.2026, kunngjort 25.03.2026 14.25. No "Sist endret" field: not amended since. Fetched 2026-10-08. | https://lovdata.no/dokument/SF/forskrift/2026-03-23-465 (as-published: https://lovdata.no/dokument/LTI/forskrift/2026-03-23-465) | `c65067ecf826985afb374bf49aa30e56a422075ad656661b72fa687908189791` (HTML page snapshot; Lovdata page chrome changes, so the hash identifies this fetch, not the legal text) | Norwegian (bokmål) |
| N2 | Lovdata, "Forskrift om radioamatørlisens", FOR-2009-11-05-1340 | Marked **Opphevet** (repealed) "ved forskrift 23 mars 2026 nr. 465". Used only for "what changed". | https://lovdata.no/dokument/SFO/forskrift/2009-11-05-1340 | (HTML, not hashed) | Norwegian |
| N3 | Nkom, høringsbrev "Høring av endring av forskrift om radioamatørlisens av 5. november 2009 nr. 1340", ref. 2510184-1 | 24.11.2025 (consultation, closed 15.12.2025) | https://nkom.no/hoeringer/horing-om-radioamatorforskriften/_/attachment/download/ca2107ed-753a-4ae8-bd10-1200bee90f4a:38f419adceec4830d4f3feb631e25e1dd0c4f4cf/... | (PDF, 6 pages, not hashed) | Norwegian |
| N4 | Nkom web page "Radioamatør" (licence, call-sign series, LC contest calls, club calls) | fetched 2026-10-08; quotes 2026 fees; links "Liste over norske kallesignaler 5.10.2026" | https://nkom.no/frekvenser-og-elektronisk-utstyr/radioamator | `a52d3f1699072a91a5d49807c57ac37432442b5d219f21627a656016db6af5b8` (HTML snapshot) | Norwegian |
| N5 | Nkom, "Liste over norske kallesignaler 5.10.2026.csv" (register export; used only for prefix counts, no personal data copied) | 5.10.2026 | same page as N4 (attachment) | `bc83d4fb5322496c8693716f711bc21d6e2627914025d4dcc9df0b075e3a6913` | Norwegian |
| N6 | Lovdata, "Forskrift om nummerressurser for elektronisk kommunikasjonsnett og -tjenester" (nummerforskriften) FOR-2004-02-16-426, § 35b | Sist endret FOR-2024-12-20-3423 fra 01.01.2025 | https://lovdata.no/dokument/SF/forskrift/2004-02-16-426 | `113292667012b4e81cfdb5f9b7e9d147218ae0c912832eabbbd2c15d91edddd9` (HTML snapshot) | Norwegian |
| B1 | NRRL "Norsk båndplan 2m (144 – 146 MHz)" | "Oppdatert pr jan 2019"; PDF created 10 Apr 2019 | https://nrrl.no/wp-content/uploads/2m.pdf | `444e4454ca33b6a19c9bf740876488d4229038bc2b130a2b59910dbcb08b4094` | Norwegian |
| B2 | NRRL "Norsk båndplan 70cm (432 – 438 MHz)" | "Oppdatert pr jan 2019" | https://nrrl.no/wp-content/uploads/70cm.pdf | `5ddbe1df5a58fda312ac4aabade15431108af87591dd02d91bfd8b5f0e5c880f` | Norwegian |
| B3 | NRRL "Norsk båndplan 6m (50 – 52 MHz)" | "Oppdatert pr aug 2018" | https://nrrl.no/wp-content/uploads/6m.pdf | `a649e66599c07a7f93cc04ec7a65bb973a83b81e19999cde80ef7b87b914017d` | Norwegian |
| B4 | NRRL "Norsk båndplan 4m (69,9 – 70,5 MHz)" | "Oppdatert pr apr 2019" | https://nrrl.no/wp-content/uploads/4m.pdf | `fa1532b2d7deea5cdc5e7109cfb31469e9bf3a07bc1fe19577612983a73257cb` | Norwegian |
| B5 | NRRL "Norsk båndplan 23cm (1240 – 1300 MHz)" | "Oppdatert pr aug 2018" (predates the 2028 split in N1) | https://nrrl.no/wp-content/uploads/23cm.pdf | `0a3e9cbf87de92ce1cea6f1e6bbb738063fbc6a9805c978b4586bd7149c46342` | Norwegian |
| B6 | NRRL "Norsk båndplan 13cm (2300 – 2450 MHz)" | "Oppdatert pr aug 2018", note "Per 2026-03-25, fjernet komma i tittel"; PDF ModDate 25 Mar 2026 | https://nrrl.no/wp-content/uploads/13cm.pdf | `400890130c53b861e08f8e8e02bc8ff5f02ca0c4b826e86f5b7e73e221ee03fe` | Norwegian |
| B7 | NRRL "Norsk båndplan" 9 cm / 6 cm / 3 cm | "Oppdatert pr aug 2018", edited 2026-03-25 (unit fix only) | https://nrrl.no/wp-content/uploads/9cm.pdf, .../6cm.pdf, .../3cm.pdf | 9cm `80327f9f9dca719d96905ee90d62e4adcf69d829a75526b03a709c617bbb8dc1`; 6cm `37d822146aadc693d4f8657aaa879adfae0a618ec6b00417b6532df84bec1532`; 3cm `296a62965a0a7d3ce5912ad3bdd74c45d7cab37ad258ebcbe72b6237b28607bf` | Norwegian |
| B8 | IARU Region 1 HF band plan as hosted by NRRL ("Effective 01 June 2016, edited by DK4VW") | 2016 edition (NB: IARU's current HF plan is the 16 Oct 2020 edition) | https://nrrl.no/wp-content/uploads/hf_r1_bandplan.pdf | `57cd3f1be55f35ade710ef6ed2f20d82bda8a405059993221e74a604e9275812` | English |
| B9 | NRRL "Båndplaner" index page (links B1-B8, plus hotspot and crossband plans) | fetched 2026-10-08 | https://nrrl.no/tema/bandplaner/ | — | Norwegian |
| B10 | NRRL "Information to visiting radio amateurs" | undated, fetched 2026-10-08 | https://nrrl.no/?p=118077 | — | English |
| C1 | CEPT Recommendation T/R 61-01, Annex 2 (Table 1) | "latest updated on 18 October 2024", annex page "Edition of 16 February 2024" | https://docdb.cept.org/download/4541 (page https://docdb.cept.org/document/925) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | English |
| C2 | ECC/REC/(05)06, Annex 2 | "Edition 16 February 2024" | https://docdb.cept.org/download/4413 (page https://docdb.cept.org/document/1024) | `30f2b55b5d3b30289b6e4ca847dbb3623435592512e99d2ad4a8e748615155d3` | English |

All PDFs downloaded with `curl -L -A 'Mozilla/5.0' --max-time 60/90`, HTTP 200,
converted with `pdftotext -layout`. Lovdata/Nkom pages are HTML and were
converted to text with a tag-stripping script; the § numbers below are the
regulation's own.

## 1. Regulator and legal instruments

- **Regulator:** Nasjonal kommunikasjonsmyndighet (**Nkom**), Lillesand, under
  Digitaliserings- og forvaltningsdepartementet.
- **Law:** lov 13. desember 2024 nr. 76 om elektronisk kommunikasjon
  (ekomloven) § 11-2, § 13-1.
- **Regulation:** **Forskrift om radioamatørvirksomhet, FOR-2026-03-23-465**
  [N1]. "Fastsatt av Nasjonal kommunikasjonsmyndighet 23. mars 2026"; § 12:
  "Forskriften trer i kraft straks. Fra samme tid oppheves forskrift 5.
  november 2009 nr. 1340 om radioamatørlisens." (In force immediately; from
  the same time the 2009 regulation is repealed.) Frequencies are in **§ 5**
  (begrenset lisens) and **§ 5a** (full lisens).
- **Call-sign numbering plan:** nummerforskriften § 35b [N6] delegates the
  call-sign plan to Nkom ("Nkom fastsetter og forvalter nummerplan for
  identifikasjon (kallesignal) ved bruk av radioamatørstasjoner i henhold til
  ITUs radioreglement artikkel 19 og appendiks 42"). The plan itself is not in
  the regulation; Nkom's web page [N4] describes the series.
- **Pending / dated changes as of 2026-10-08:**
  - **23 cm split on 1 January 2028** (written into N1 § 5a, see 3.1).
  - The consultation [N3] proposed a remote-control rule (no remote operation
    of a station in JW/JX/3Y unless the operator is physically on the same
    territory). **It is not in the adopted text** [N1] — § 8 became
    "Kryptering". Hamweekly/SSA reported "remote ban lifted" [secondary].
  - No further amendment is shown on Lovdata (N1 has no "Sist endret").

## 2. Licence classes

N1 § 4: "Radioamatørlisens har to lisensklasser • Full lisens (HAREC klasse A)
• Begrenset lisens (kun gyldig i Norge)." (Two classes: Full licence (HAREC
class A); Restricted licence (valid only in Norway).)

| class id (lowercase, for code) | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `full` | Full lisens (A) | HAREC (T/R 61-02) | **T/R 61-01**: Norway "LA", Svalbard "JW", national licence equivalent "A" [C1 p.6] | LA, LB (current issue series LBnXX), LC (contest 2x1), JW/JX/3Y for the territories [N1 § 4, N4] |
| `begrenset` | Begrenset lisens | National entry exam (NRRL question bank; N3 cites ECC Report 89 as the starting point) | **none** — "kun gyldig i Norge" [N1 § 4]; Norway is **not** listed in ECC/REC/(05)06 Annex 2 [C2 p.5] | **[UNCONFIRMED]** — see §6 |

- Holders of call signs issued under the 2009 regulation (one class, HAREC)
  are Full licence holders [derived: the 2009 regulation had a single class,
  and § 4 of N2 granted the licence on a HAREC-level exam].
- N1 § 7: "Kallesignal tildelt radioamatør med begrenset lisens kan kun
  benyttes for sending i henhold til kravene til begrenset lisens." (A call
  sign issued to a restricted-licence holder may only be used for transmitting
  under the restricted-licence conditions.)
- N1 § 9: equipment (incl. kits) used by a restricted holder "skal kunne
  benyttes i henhold til lisenskravene for begrenset lisens" (must be capable
  of being used within the restricted-licence conditions).
- N1 § 6: a restricted holder may, for training towards Full, transmit under
  Full conditions under the physical presence and supervision of a Full
  licensee, using the station's or supervisor's call.

## 3. Permitted bands and power, per class

**Power reference.** Both tables head the power column "Tillatt maksimal
utgangseffekt fra sender (watt)", and N1 § 3 i defines it:
"utgangseffekt fra sender: Den maksimale gjennomsnittsverdien av
omhyllingskurven til det modulerte radiosignalet målt over en periode av
radiosignalet (PEP), målt der antennen er tilkoblet senderens siste trinn."
(*Transmitter output power: the maximum mean value of the envelope of the
modulated signal measured over one RF cycle (PEP), measured where the antenna
is connected to the transmitter's final stage.*) So every plain figure below
is **W PEP at the transmitter output**. Exceptions (EIRP, mean) are marked.

Bandwidth column "Tillatt maksimal båndbredde" (maximum permitted bandwidth) is
a **legal** limit in Norway, not band-plan advice — the guard should enforce it.

Status: "Primær"/"Sekundær". The regulation does not separate amateur from
amateur-satellite service (except the 1260-1270 MHz satellite note). Both
classes may use a band only where a row exists in their table.

| lo Hz | hi Hz | band | status | `begrenset` | `full` | max BW | notes | source |
|---|---|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | Sec. | — | 200 W PEP **and** max 1 W EIRP | 1 kHz | "Maksimal tillatt utstrålt effekt er 1 W e.i.r.p." | N1 § 5a |
| 472 000 | 479 000 | 630 m | Sec. | — | 100 W PEP **and** max 1 W EIRP | 1 kHz | same EIRP wording | N1 § 5a |
| 1 810 000 | 1 850 000 | 160 m | Pri. | — | 1000 W PEP | 6 kHz | | N1 § 5a |
| 1 850 000 | 2 000 000 | 160 m | Sec. | — | 10 W **mean** | 6 kHz | "Gjennomsnittlig sendeeffekt skal ikke overstige 10 W, uavhengig av modulasjonstype." | N1 § 5a |
| 3 500 000 | 3 800 000 | 80 m | Pri. | 10 W PEP | 1000 W PEP | 6 kHz | | N1 § 5, § 5a |
| 5 260 000 | 5 410 000 | 60 m | Sec. | — | 100 W PEP | 6 kHz | national block, wider than WRC-15 (see 3.1) | N1 § 5a |
| 7 000 000 | 7 200 000 | 40 m | Pri. | 10 W PEP | 1000 W PEP | 6 kHz | | N1 § 5, § 5a |
| 10 100 000 | 10 150 000 | 30 m | Sec. | — | 1000 W PEP | **1 kHz** | | N1 § 5a |
| 14 000 000 | 14 350 000 | 20 m | Pri. | 10 W PEP | 1000 W PEP | 6 kHz | | N1 § 5, § 5a |
| 18 068 000 | 18 168 000 | 17 m | Pri. | 10 W PEP | 1000 W PEP | 6 kHz | | N1 § 5, § 5a |
| 21 000 000 | 21 450 000 | 15 m | Pri. | 10 W PEP | 1000 W PEP | 6 kHz | | N1 § 5, § 5a |
| 24 740 000 | 24 890 000 | (below 12 m) | Sec. | — | 1000 W PEP | 6 kHz | national extension below the ITU 12 m band | N1 § 5a |
| 24 890 000 | 24 990 000 | 12 m | Pri. | — | 1000 W PEP | 6 kHz | | N1 § 5a |
| 28 000 000 | 29 700 000 | 10 m | Pri. | 10 W PEP | 1000 W PEP | 18 kHz | | N1 § 5, § 5a |
| 50 000 000 | 52 000 000 | 6 m | Pri. | 10 W PEP | 1000 W PEP | 18 kHz | | N1 § 5, § 5a |
| 69 900 000 | 70 500 000 | 4 m | Sec. | — | 100 W PEP (1000 W EME/MS*) | 18 kHz | | N1 § 5a |
| 144 000 000 | 146 000 000 | 2 m | Pri. | 10 W PEP | 300 W PEP (1000 W EME/MS*) | 18 kHz | | N1 § 5, § 5a |
| 432 000 000 | 438 000 000 | 70 cm | Pri. | 10 W PEP | 300 W PEP (1000 W EME/MS*) | 30 kHz; **200 kHz in 433.6-434.0 MHz** | 430-432 and 438-440 MHz are **not** amateur in Norway | N1 § 5, § 5a |
| 1 240 000 000 | 1 300 000 000 | 23 cm (**until 2027-12-31**) | Sec. | — | 300 W PEP (1000 W EME/MS*) | 20 MHz | "Allokeringen gjelder til og med 31. desember 2027." | N1 § 5a |
| 1 240 000 000 | 1 258 000 000 | 23 cm (**from 2028-01-01**) | Sec. | — | 300 W PEP | 18 MHz | | N1 § 5a |
| 1 258 000 000 | 1 296 000 000 | 23 cm (from 2028) | Sec. | — | **0.02 W EIRP** | 150 kHz | sat. 1260-1270 allowed; 1260-1262 elevation-dependent EIRP (3.1) | N1 § 5a |
| 1 296 000 000 | 1 298 000 000 | 23 cm (from 2028) | Sec. | — | 50 W PEP | 150 kHz | >150 kHz incl. ATV: 0.02 W/1 MHz EIRP | N1 § 5a |
| 1 298 000 000 | 1 300 000 000 | 23 cm (from 2028) | Sec. | — | 158 W PEP (EME 500 W, conditions) | 150 kHz | >150 kHz incl. ATV: 0.02 W/1 MHz EIRP | N1 § 5a |
| 2 300 000 000 | 2 450 000 000 | 13 cm | Sec. | **5 W PEP** | 100 W PEP | 20 MHz | whole 2300-2450, no gap | N1 § 5, § 5a |
| 3 400 000 000 | 3 410 000 000 | 9 cm | Sec. | — | 100 W PEP | 7 MHz | | N1 § 5a |
| 5 650 000 000 | 5 850 000 000 | 6 cm | Sec. | — | 100 W PEP | 20 MHz | | N1 § 5a |
| 10 250 000 000 | 10 500 000 000 | 3 cm | Sec. | **1 W PEP** | 100 W PEP | 50 MHz | 10.00-10.25 GHz is **not** amateur in Norway | N1 § 5, § 5a |
| 24 000 000 000 | 24 050 000 000 | 1.2 cm | Pri. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 24 050 000 000 | 24 250 000 000 | 1.2 cm | Sec. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 47 000 000 000 | 47 200 000 000 | 6 mm | Pri. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 76 000 000 000 | 77 500 000 000 | 4 mm | Sec. | — | 100 W PEP | 50 MHz | 75.5-76.0 GHz not listed | N1 § 5a |
| 77 500 000 000 | 78 000 000 000 | 4 mm | Pri. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 78 000 000 000 | 81 000 000 000 | 4 mm | Sec. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | Sec. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 134 000 000 000 | 136 000 000 000 | 2 mm | Pri. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 136 000 000 000 | 141 000 000 000 | 2 mm | Sec. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 241 000 000 000 | 248 000 000 000 | 1 mm | Sec. | — | 100 W PEP | 50 MHz | | N1 § 5a |
| 248 000 000 000 | 250 000 000 000 | 1 mm | Pri. | — | 100 W PEP | 50 MHz | | N1 § 5a |

\* EME/MS: see 3.1.

**Original wording (N1), with translation:**

- § 5 heading/intro: "Frekvenser med vilkår som angitt i tabell nedenfor
  tillates brukt til radioamatørvirksomhet for radioamatør med begrenset
  lisens." — *Frequencies with the conditions in the table below may be used
  for amateur activity by an amateur with a restricted licence.* Columns:
  "Frekvensbånd | Status | Tillatt maksimal utgangseffekt fra sender (watt) |
  Tillatt maksimal båndbredde | Spesielle vilkår".
- § 5 rows verbatim: "3500–3800 kHz Primær 10 6 kHz", "7000–7200 kHz Primær 10
  6 kHz", "14000–14350 kHz Primær 10 6 kHz", "18068–18168 kHz Primær 10 6 kHz",
  "21000–21450 kHz Primær 10 6 kHz", "28000–29700 kHz Primær 10 18 kHz",
  "50–52 MHz Primær 10 18 kHz", "144–146 MHz Primær 10 18 kHz", "432–438 MHz
  Primær 10 30 kHz Båndbredde 200 kHz er tillatt i frekvensområdet 433,6–434,0
  MHz", "2300–2450 MHz Sekundær 5 20 MHz", "10,25–10,50 GHz Sekundær 1 50 MHz".
- § 5a intro: "... for radioamatør med full lisens (A)."
- 135.7 / 472 kHz: "Maksimal tillatt utstrålt effekt er 1 W e.i.r.p." —
  *Maximum permitted radiated power is 1 W EIRP.*
- 1850-2000 kHz: "Gjennomsnittlig sendeeffekt skal ikke overstige 10 W,
  uavhengig av modulasjonstype." — *Mean transmitter power shall not exceed
  10 W, regardless of modulation type.*
- 4 m / 2 m / 70 cm / 23 cm (to 2027): "1000 W tillates brukt til EME og MS
  forutsatt bruk av retningsantenne og logging av tid, asimut og elevasjon ved
  sending." — *1000 W may be used for EME and MS provided a directional antenna
  is used and time, azimuth and elevation are logged when transmitting.*
- 1240-1300 MHz: "Allokeringen gjelder til og med 31. desember 2027. Fra 1.
  januar 2028 kan kun allokeringene nedenfor benyttes." — *This allocation
  applies up to and including 31 December 2027. From 1 January 2028 only the
  allocations below may be used.*
- 1258-1296 MHz, power "0,02", note "Målt som utstrålt effekt e.i.r.p." —
  *Measured as radiated power EIRP* (i.e. 20 mW EIRP). "Kommunikasjon mot
  satellitt er tillatt i frekvensområdet 1260-1270 MHz." — *Communication
  towards satellites is permitted in 1260-1270 MHz.* "For kommunikasjon mot
  satellitt i frekvensområdet 1260 til 1262 MHz er tillatt utstrålt effekt
  avhengig av elevasjonsvinkel (Ɵ) over horisonten: 0° < Ɵ < 15°: 0,5 W
  e.i.r.p. 15° ≤ Ɵ < 55°: 50 W e.i.r.p. 55° ≤ Ɵ < 90°: 478 W e.i.r.p." —
  *For satellite uplinks in 1260-1262 MHz the permitted radiated power depends
  on elevation angle: <15° 0.5 W EIRP; 15-55° 50 W EIRP; 55-90° 478 W EIRP.*
- 1258-1300 MHz (on the 1258-1296, 1296-1298 and 1298-1300 rows): "I
  frekvensområdet 1258–1300 MHz og med en båndbredde større enn 150 kHz,
  inkludert amatør TV (ATV), er maksimal tillatt utstrålt effekt 0,02 W/1 MHz
  e.i.r.p." — *In 1258-1300 MHz, with a bandwidth greater than 150 kHz,
  including ATV, the maximum radiated power is 0.02 W per 1 MHz EIRP.* (The
  same rows give 150 kHz as the maximum bandwidth, so this sentence reads as
  contradicting the bandwidth column; see 3.1.)
- 1298-1300 MHz: "For EME tillates sendereffekt på 500 W forutsatt bruk av
  retningsbestemt antenne med minimum 30 dBi forsterkning og minimum
  elevasjonsvinkel 15° over horisonten." — *For EME, 500 W transmitter power is
  permitted provided a directional antenna of at least 30 dBi gain and an
  elevation of at least 15° above the horizon.*
- After each table: "Radiotjenester med primær status har samme rettigheter i
  samme frekvensbånd. Radiotjenester med sekundær status skal ikke forstyrre
  radiotjenester med primær status og må akseptere forstyrrelser fra slike." —
  *Primary services have equal rights in the same band. Secondary services
  shall not interfere with primary services and must accept interference from
  them.*

### 3.1 Per-band exceptions

- **60 m:** Full only, **5260-5410 kHz as one block**, 100 W PEP, 6 kHz BW,
  secondary [N1 § 5a]. This is a national allocation much wider than WRC-15's
  5351.5-5366.5 kHz (15 W EIRP); Norway sets no EIRP limit on 60 m. Unchanged
  from 2009 [N2 § 7]. Guard: allow 5 260 000-5 410 000 Hz for `full` at 100 W
  PEP; bandwidth ≤ 6 kHz.
- **12 m extension:** 24 740-24 890 kHz, secondary, Full, 1000 W [N1 § 5a].
  Unusual; keep it.
- **4 m:** 69.9-70.5 MHz, Full only, 100 W PEP, 18 kHz (was 16 kHz in 2009
  [N2]).
- **EME/MS 1000 W** on 4 m, 2 m, 70 cm, 23 cm (until 2027): conditional on a
  directional antenna and logging time/azimuth/elevation. The guard cannot
  verify the conditions [derived]: encode the base limit (100/300/300/300 W)
  and expose EME/MS as an operator-declared override, or refuse above the
  base limit.
- **23 cm, two regimes [N1 § 5a]:**
  - Until **2027-12-31**: 1240-1300 MHz, 300 W PEP, 20 MHz BW.
  - From **2028-01-01**: 1240-1258 300 W/18 MHz; 1258-1296 **20 mW EIRP**/150
    kHz; 1296-1298 50 W/150 kHz; 1298-1300 158 W/150 kHz (EME 500 W with
    ≥30 dBi and ≥15° elevation); satellite uplink 1260-1270 allowed, 1260-1262
    elevation-dependent EIRP; anything >150 kHz incl. ATV in 1258-1300 at
    0.02 W/MHz EIRP.
  - **[derived] interpretation issue:** the table lists both regimes at once.
    The natural reading is that only the 1240-1300 row applies until the end of
    2027 and only the split rows from 2028. Whether the 1260-1262 elevation
    EIRP rule and the 0.02 W/MHz ATV rule already apply before 2028 is not
    stated. The code should be date-aware; a conservative build could apply
    the 2028 rules now.
  - **[derived] contradiction:** the 1258-1300 rows give max bandwidth 150 kHz
    and also a rule for "båndbredde større enn 150 kHz". Read literally, the
    bandwidth column forbids >150 kHz; the note then reads as permitting wider
    signals (ATV) at 0.02 W/MHz EIRP. Ask Nkom before encoding; meanwhile
    refuse >150 kHz in 1258-1300 from 2028 (the stricter reading).
- **70 cm 200 kHz window:** 433.6-434.0 MHz allows 200 kHz bandwidth (both
  classes); elsewhere 30 kHz.
- **Interference rule (N1 § 7):** "Dersom bruk av frekvenser avsatt til
  radioamatørvirksomhet, forårsaker forstyrrelser skal utgangseffekten
  reduseres til maksimalt 100 watt." — *If use of amateur frequencies causes
  interference, output power shall be reduced to at most 100 W.* Not
  encodable; mention in UI.
- **Ny-Ålesund (Svalbard) exclusion, N1 § 2:** "Forskriften gjelder ikke
  frekvensområdet 2 GHz–32 GHz i det geografiske området innenfor en radius av
  20 km fra Ny-Ålesund sentrum." — *The regulation does not apply to 2-32 GHz
  within 20 km of Ny-Ålesund centre* (i.e. no amateur authorisation there).
  Ny-Ålesund ≈ 78.92 N, 11.93 E [secondary, coordinates not in N1].
- **Unmanned aircraft (N1 § 7):** no transmission from aircraft without a
  pilot aboard (drones, models), except organised emergency comms and
  telemetry for experiments at max **100 mW EIRP**. OpenHamShack HAM is not
  airborne; not encoded.
- **Encryption (N1 § 8):** prohibited, except organised emergency comms
  (domestic) and training for it.
- **Antenna gain:** no general gain rule; only the ≥30 dBi EME condition at
  1298-1300 MHz from 2028.
- **Mobile/portable:** no separate power limit.

### 3.2 Gaps: not permitted for any class (list explicitly)

Within 135.7 kHz - 10.5 GHz, everything not in a row above, notably:
- 137.8-472 kHz; 479-1810 kHz; 2000-3500 kHz; **3800-5260 kHz**;
  **5410-7000 kHz**; 7200-10 100 kHz; 10 150-14 000 kHz; 14 350-18 068 kHz;
  18 168-21 000 kHz; 21 450-24 740 kHz; 24 990-28 000 kHz; 29.7-50 MHz;
  52-69.9 MHz; 70.5-144 MHz; 146-432 MHz (**430-432 MHz not amateur in
  Norway**); **438-440 MHz** (not amateur); 440-1240 MHz; 1300-2300 MHz;
  2450-3400 MHz; 3410-5650 MHz; 5850-10 250 MHz (**10.00-10.25 GHz not
  amateur**); 10.5-24 GHz.
- From 2028-01-01, nothing new is removed from 1240-1300, but 1258-1296 MHz is
  effectively QRP (20 mW EIRP).
- For `begrenset`, everything outside its 11 rows: no 160 m, 60 m, 30 m,
  12 m, 4 m, 23 cm, 9 cm, 6 cm, LF/MF or above 10.5 GHz.

## 4. Satellite / QO-100

- **QO-100 uplink 2400-2450 MHz:** inside the 2300-2450 MHz row, so permitted
  to both classes without extra permission: **`full` 100 W PEP, `begrenset` 5 W
  PEP**, transmitter output, 20 MHz max BW, secondary [N1 § 5, § 5a]. There is
  no satellite-specific wording for 13 cm and no EIRP limit. (A 5 W PEP limit
  into a dish is workable for QO-100 narrowband — 5 W into a 1.2 m dish is a
  common station [derived].)
- **10.45-10.5 GHz (QO-100 downlink, receive):** inside 10.25-10.50 GHz, both
  classes may transmit there (begrenset 1 W). Receive needs no licence.
- **Other satellite rules:** only 23 cm has explicit satellite wording (see
  3.1). 2 m 145.806-146.000 and 70 cm 435-438 MHz are satellite-only in the
  NRRL plan, not in law [B1, B2].

## 5. CEPT / visiting operators

- **T/R 61-01:** implemented. Annex 2 Table 1 [C1 p.6]: "Norway | LA | A" and
  "Svalbard | JW | A". Norway's `full` class = CEPT licence. A Norwegian
  `full` holder abroad uses the T/R 61-01 regime of the host country.
- **ECC/REC/(05)06 (Novice):** **not implemented** — Norway is absent from
  Annex 2 [C2 p.5], and NRRL states "CEPT Novice license is currently not
  implemented in Norway and cannot be used" [B10, secondary]. `begrenset` is
  explicitly "kun gyldig i Norge".
- **T/R 61-02 (HAREC):** the 2026 regulation does not repeat the 2009 rule
  (N2 § 4 third paragraph: foreign T/R 61-02 exam passes entitle the holder to
  a Norwegian licence). N1 § 4 only says Nkom issues licence and call sign
  "etter bestått prøve" and that exam guidelines are set by Nkom.
  **[UNCONFIRMED]** whether a foreign HAREC certificate still converts directly
  (very likely by Nkom practice; not in the text).
- **Visitors** [B10, secondary]: CEPT-licence holders use **LA/<call>**
  (JW/<call> on Svalbard), stays up to 3 months, follow the Norwegian
  regulation (N1 § 5a limits apply), no airborne TX.

## 6. Callsigns

- **Territories (N1 § 4):** "Ved bruk av radioamatørstasjon på norsk hovedland
  benyttes prefix i serien LA-LN, på Svalbard og Bjørnøya prefiks JW, på Jan
  Mayen prefiks JX og på Bouvetøya, Peter I's Øy og norske landområder i
  Antarktis prefiks 3Y." — *Mainland: LA-LN; Svalbard & Bjørnøya: JW; Jan
  Mayen: JX; Bouvet, Peter I Island and Norwegian Antarctica: 3Y.* "Radioamatører
  som har et norsk kallesignal som ikke begynner med LA benytter et av de
  aktuelle prefiksene (JW, JX eller 3Y) foran sitt norske kallesignal, for
  eksempel JW/LB1XX." — *Holders of a call not starting LA prefix it, e.g.
  JW/LB1XX* (LA-calls replace LA with JW etc.).
- **Class in the call (N1 § 4):** "Det tildeles kallesignal som identifiserer
  lisensklasse fastsatt av Nkom." — *Call signs are issued that identify the
  licence class, as set by Nkom.* **[UNCONFIRMED]: which series identifies
  `begrenset`.** Nkom's page [N4] (fetched 2026-10-08) still describes only one
  issuing series: "Kallesignalet er på formen LBnXX, der n er et tall mellom 0
  og 9 og X er en bokstav mellom A og Z." The register export of 5.10.2026
  [N5] contains 5865 LA, 1457 LB, 7 JW, 1 JX and single LG/LI/LJ/LM
  special-event calls — **no new prefix series**; the newest personal
  registrations (Apr-Sep 2026) are all LB6-LB8 2x2. A consultation response
  (not Nkom) suggested an "LF" series for the national class [secondary, not
  adopted as far as found]. So do **not** infer class from the call in Norway
  yet.
- **Series [N4]:** individual LAnXXA (1983-2014 series; older LAnX/LAnXX also
  exist), **LBnXX** (since ~2014, sequential); club **LAnXXX** (last letter not
  A) or **LAnXXXX**, 10-year validity; contest **LC** 2x1 ("LC-serien, som bare
  skal benytte i nasjonale og internasjonale tester"), 5-year; repeaters/
  beacons may get own calls (NRRL allocates from Nkom series).
- **Portable suffixes:** N1 has no /P /M rule; only the territory prefixes
  above. Visitors: "LA/" prefix [B10].
- **Regex hints** (warn only): `^(LA|LB)\d[A-Z]{1,4}$` personal/club (any
  class until Nkom says otherwise); `^LC\d[A-Z]$` contest; `^(JW|JX|3Y)` or
  `^(JW|JX|3Y)/` territory.

## 7. National band plan

NRRL (Norsk Radio Relæ Liga), "Båndplaner" [B9]: NRRL follows IARU Region 1
("vi i Norge følger båndplanen i vår region, som er Region 1. I tillegg gjøres
det enkelte mindre nasjonale tilpasninger"). N1 § 7: "Sendinger ... bør være i
samsvar med nasjonale og internasjonale retningslinjer og båndplaner" (*should*
follow the plans: voluntary). All VHF/UHF plans are "© NRRL v/ VHF-manager",
dated 2018/2019 and refer to the IARU R1 VHF Handbook as "kun veiledende".
**They predate N1**: their headers carry the 2009 limits (e.g. 23 cm "Max
100W", where N1 now gives 300 W), and the 23 cm plan knows nothing of the 2028
split. Use N1 for limits, never the plan headers.

**HF:** NRRL simply republishes the **IARU R1 HF plan "Effective 01 June 2016"**
[B8]; no national HF plan. Use the current IARU R1 HF plan (2020) for HF and
note that NRRL's copy is older. Norway-specific HF ranges the IARU plan does
not cover: 60 m 5260-5410 kHz (IARU plan only covers 5351.5-5366.5),
24.740-24.890 MHz (no plan), 1850-2000 kHz (IARU "all modes" applies; 10 W
mean legal limit).

**6 m (50-52 MHz)** [B3, aug 2018]:
| lo MHz | hi MHz | max BW | use |
|---|---|---|---|
| 50.000 | 50.100 | 500 Hz | CW exclusive (50.000-50.010 reserved for R1 synchronised beacon project; 50.050 future CW centre; 50.090 intercontinental CW) |
| 50.100 | 50.200 | 2.7 kHz | SSB/CW; 50.100-50.130 intercontinental, 50.110 interc. centre; 50.130-50.200 international, 50.150 centre |
| 50.200 | 50.300 | 2.7 kHz | SSB/CW general; 50.285 crossband |
| 50.300 | 50.400 | 2.7 kHz | MGM/narrowband/CW; 50.305 PSK; 50.310-50.320 EME; 50.320-50.380 MS |
| 50.400 | 50.500 | 1.0 kHz | **beacons exclusive** |
| 50.500 | 52.000 | 18 kHz | all modes: 50.510 SSTV; 50.540-50.580 FM internet GW; 50.600 RTTY; 50.620-50.750 digital, 50.630 DV calling, 50.700 Winlink; **51.210-51.390 repeater RX (input)**; 51.410-51.590 FM/DV simplex, **51.510 FM calling**; **51.810-51.990 repeater TX (output)**; 20 kHz spacing |
Repeaters: input 51.21-51.39, output 51.81-51.99 → **input 600 kHz below output (shift −600 kHz)** [derived from the paired ranges].

**4 m (69.9-70.5 MHz)** [B4, apr 2019]:
| lo | hi | BW | use |
|---|---|---|---|
| 69.900 | 70.000 | 2.7 kHz | CW/SSB, national segment ("brukes bl.a. i Danmark/OZ") |
| 70.000 | 70.090 | 1 kHz | coordinated **beacons** |
| 70.090 | 70.100 | 1 kHz | temporary and private beacons |
| 70.100 | 70.250 | 2.7 kHz | CW/SSB/MGM; 70.185 crossband; **70.200 CW/SSB calling** |
| 70.250 | 70.294 | 12 kHz | all modes; 70.250 MS calling; 70.260 AM/FM calling; 70.270 MGM centre |
| 70.294 | 70.500 | 12 kHz | FM/DV, 25 kHz channels; 70.3125, 70.3250 digital; **70.450 FM calling**; 70.4625/70.4750/70.4875 digital |
Note: legacy PMR channels still registered in southern Norway (70.050 Vestfold, 70.200 Bergen, 70.250 Stavanger, 70.350 Gjøvik, 70.400 Oslo; RX freq, TX +10 MHz) [B4].

**2 m (144-146 MHz)** [B1, jan 2019]:
| lo MHz | hi MHz | max BW (−6 dB) | use |
|---|---|---|---|
| 144.000 | 144.025 | 2.7 kHz | satellite (downlink only) |
| 144.025 | 144.105 | 500 Hz | CW/EME; 144.050 activity centre; 144.100 random MS CW |
| 144.105 | 144.165 | 500 Hz | CW/MGM; 144.110-144.160 EME MGM |
| 144.165 | 144.400 | 2.7 kHz | CW/SSB/MGM; 144.170 alt. MGM calling; 144.195-144.205 random MS SSB; **144.300 SSB calling** |
| 144.400 | 144.490 | 500 Hz | **beacons exclusive** |
| 144.491 | 144.493 | 500 Hz | experimental MGM |
| 144.500 | 144.794 | 20 kHz | all modes; 144.500 SSTV/fax; 144.600 data; 144.6375-145.6875 Norwegian crossband (own channel plan); 144.750 ATV talkback |
| 144.794 | 144.9625 | 12 kHz | MGM/digital; **144.800 APRS**; 144.8125, 144.8375/144.8500/144.8625 DV internet GW; 144.825 APRS secondary; 144.925/144.950 Winlink |
| **144.975** | **145.194** | 12 kHz | **repeater RX (input) exclusive**, 12.5 kHz |
| 145.194 | 145.206 | 12 kHz | space communication |
| 145.206 | 145.5625 | 12 kHz | FM/DV simplex 12.5 kHz (145.2125-145.5625); 145.2375/145.2875/145.3375 FM internet GW; **145.300 emergency (Nødsamband)**; **145.375 DV calling**; **145.500 FM calling** |
| **145.575** | **145.7935** | 12 kHz | **repeater TX (output) exclusive**, 12.5 kHz |
| 145.794 | 145.806 | 12 kHz | space communication |
| 145.806 | 146.000 | 12 kHz | **satellite exclusive** |
Repeaters: −600 kHz (input below output) [derived from ranges; matches R1].

**70 cm (432-438 MHz)** [B2, jan 2019]:
| lo MHz | hi MHz | BW | use |
|---|---|---|---|
| 432.000 | 432.025 | 500 Hz | CW, EME |
| 432.025 | 432.100 | 500 Hz | CW/MGM; 432.050 CW centre; 432.088 PSK31 |
| 432.100 | 432.400 | 2.7 kHz | CW/SSB/MGM; **432.200 SSB centre**; 432.350 microwave talkback; 432.370 FSK441 |
| 432.400 | 432.490 | 500 Hz | **beacons exclusive** |
| 432.491 | 432.493 | 500 Hz | experimental MGM |
| 432.500 | 432.600 | 12 kHz | all modes; **432.500 APRS (new)**; 432.5125-432.5875 linear transponder RX |
| **432.600** | **432.975** | 12 kHz | **repeater RX (input)**, 12.5 kHz, **2 MHz split** |
| 433.000 | 433.225 | 12 kHz | crossband channels |
| 433.225 | 433.375 | 12 kHz | 433.250 FM emergency |
| 433.400 | 433.600 | 12 kHz | 433.400 SSTV; 433.425-433.575 simplex 25 kHz; **433.450 DV calling; 433.500 FM calling**; 433.5250-433.5875 simplex 12.5 kHz |
| 433.600 | 434.000 | 20 kHz | all modes; 433.625-433.775 digital (433.700/433.725 emergency Winlink/packet); 433.800 old APRS (deprecated); 433.950-433.9875 FM internet GW |
| 434.000 | 434.600 | 12 kHz | all modes; 434.000 digital experiments centre; 434.0125-434.0500 FM simplex internet GW; 434.450-434.500 digital; 434.5125-434.5875 linear transponder TX |
| **434.600** | **434.975** | 12 kHz | **repeater TX (output)**, 12.5 kHz, 2 MHz split |
| 435.000 | 438.000 | 20 kHz | **satellite exclusive** |
Repeaters: input 432.600-432.975, output 434.600-434.975 → **shift −2.0 MHz**
("Vi bruker 2MHz repeater splitt i Norge"). **Not the R1 −7.6 MHz** (and R1's
430-432 / 438-440 repeater ranges are illegal in Norway).

**23 cm (1240-1300 MHz)** [B5, aug 2018 — pre-dates the 2028 legal split]:
| lo MHz | hi MHz | BW | use |
|---|---|---|---|
| 1240.000 | 1240.500 | 2.7 kHz | all modes, digital (reserved) |
| 1240.500 | 1240.750 | 500 Hz | beacons (reserved) |
| 1240.750 | 1241.000 | 20 kHz | FM/DV (reserved) |
| 1241.000 | 1243.250 | 20 kHz | all modes; **1242.025-1242.700 repeater TX (output) RS1-RS28**; 1242.725-1243.250 digital RS29-RS50 |
| 1243.250 | 1260.000 | — | ATV/digital ATV; **1258.150-1259.350 repeater TX (output) R20-R68** |
| 1260.000 | 1270.000 | — | satellite |
| 1270.000 | 1272.000 | 20 kHz | all modes; **1270.025-1270.700 repeater RX (input) RS1-RS28**; 1270.725-1271.250 digital RS29-RS50 |
| 1272.000 | 1290.994 | — | ATV/digital ATV |
| 1290.994 | 1291.481 | 20 kHz | FM/DV **repeater RX (input) RM0-RM19** 1291.000-1291.475, 25 kHz |
| 1291.494 | 1296.000 | — | all modes; **1293.150-1294.350 repeater RX (input) R20-R68** |
| 1296.000 | 1296.150 | 500 Hz | CW/MGM; 1296.000-1296.025 EME; 1296.138 PSK31 |
| 1296.150 | 1296.800 | 2.7 kHz | CW/SSB/MGM; **1296.200 narrowband centre**; 1296.400-1296.600 lin. transponder RX; 1296.500 SSTV; 1296.600 data; 1296.600-1296.700 transponder TX; 1296.741-1296.743 exp. MGM; 1296.750-1296.800 local beacons (max 10 W ERP) |
| 1296.800 | 1296.994 | 500 Hz | **beacons exclusive** |
| 1296.994 | 1297.481 | 20 kHz | FM/DV **repeater TX (output) RM0-RM19** 1297.000-1297.475 |
| 1297.494 | 1297.981 | 20 kHz | FM/DV simplex SM20-SM39 1297.500-1297.875; **1297.500 FM centre**; **1297.725 DV calling**; 1297.900-1297.975 FM internet GW |
| 1298.000 | 1299.000 | 20 kHz | simplex analog+digital, RS1-RS39 |
| 1299.000 | 1299.750 | 150 kHz | 5 × 150 kHz high-speed data (centres 1299.075/.225/.375/.525/.675) |
| 1299.750 | 1300.000 | 20 kHz | 8 × 25 kHz FM/DV (1299.775-1299.975) |
Repeaters: RM0-RM19 output 1297.000 / input 1291.000 → **−6 MHz**; RS1-RS28
output 1242.025 / input 1270.025 → **+28 MHz (input above output)**; R20-R68
output 1258.150 / input 1293.150 → **+35 MHz (input above output)** [derived
from paired ranges]. **From 2028, 1258-1296 MHz is 20 mW EIRP max**, so the
R20-R68 outputs and the 1270/1293 inputs, ATV at 1243-1260/1272-1291 (>150 kHz,
0.02 W/MHz EIRP) and the satellite segment are all hit; NRRL has not
re-planned yet (as of B5).

**13 cm (2300-2450 MHz)** [B6]:
| lo MHz | hi MHz | BW | use |
|---|---|---|---|
| 2300.000 | 2320.000 | 20 kHz | all modes; 2304-2306 narrowband (for countries without 2320-2322) |
| 2320.000 | 2320.150 | 500 Hz | CW; 2320.000-2320.025 EME; 2320.138 PSK31 |
| 2320.150 | 2320.800 | 2.7 kHz | CW/SSB; 2320.200 SSB centre (printed "2020,200", a typo); 2320.750-2320.800 local beacons (max 10 W ERP) |
| 2320.800 | 2321.000 | — | **beacons exclusive** |
| 2321.000 | 2322.000 | 20 kHz | FM/DV simplex and repeaters |
| 2322.000 | 2400.000 | 5 MHz | 2322-2355 ATV; 2355-2365 digital; 2365-2370 repeaters; 2370-2392 ATV; 2392-2400 digital |
| 2400.000 | 2450.000 | 20 MHz | **satellite**; 2400-2402 narrowband; 2427-2443 ATV if not used by satellites |

**9 cm (3400-3410 MHz)** [B7]: 3400.000-3400.800 CW/MGM 500 Hz (3400.100 EME
centre; 3400.750-3400.800 local beacons max 10 W ERP); 3400.800-3400.995
beacons only; 3401-3402 all modes 2.7 kHz; **3402-3410 satellite downlink**.

**6 cm (5650-5850 MHz)** [B7]: 5650-5668 satellite; 5668-5670 satellite
uplink, 5668.200 narrowband centre; 5670-5700 MGM; 5700-5720 ATV; 5720-5760
all modes; 5760-5760.800 narrowband (5760.200 centre; 5760.750-.800 local
beacons); 5760.800-5760.990 beacons only; 5762-5830 all modes, narrowband
priority; **5830-5850 satellite downlink**.

**3 cm (10.25-10.50 GHz)** [B7]: 10.250-10.350 MGM; 10.350-10.368 all;
10.368-10.3688 narrowband (10.3682 centre; 10.36875-10.36880 local beacons max
10 W ERP); 10.36880-10.36899 beacons exclusive; 10.369-10.450 all; 10.450-10.500
all, 10.450-10.452 narrowband alternative. **NB: the NRRL plan does not mark
10.45-10.50 GHz as satellite**, unlike IARU R1 (10.450-10.500 satellite,
QO-100 downlink 10.489-10.500).

**Differences from IARU R1:**
1. 70 cm: only 432-438 MHz is amateur; **repeaters 432.600-432.975 in /
   434.600-434.975 out, −2 MHz** (R1: 430/438 MHz, −7.6 MHz); FM calling
   433.500, DV calling 433.450, APRS 432.500 (433.800 deprecated).
2. 2 m: Norwegian crossband plan 144.6375-145.6875; 145.300 emergency;
   145.375 DV calling; APRS secondary 144.825.
3. 6 m: repeaters 51.21-51.39 in / 51.81-51.99 out; FM calling 51.510.
4. 4 m: 69.9-70.0 national CW/SSB segment; FM calling 70.450.
5. 23 cm: national RS/R channel schemes with +28/+35 MHz pairs; plan will be
   superseded by the 2028 legal split.
6. HF: NRRL hosts the 2016 R1 plan, not the 2020 one; 60 m legal band
   (5260-5410) much wider than R1's planned 5351.5-5366.5.
7. 3 cm: 10.00-10.25 GHz not amateur; NRRL plan lacks the satellite marking at
   10.45-10.50 GHz.

## 8. Confidence and gaps

**Overall: high for the licence (law), medium for the band plan.** The law is
a single, fresh (March 2026), consolidated Lovdata text with no amendments,
read in full; every limit above is quoted from it. The band plans are NRRL's
own PDFs but are 2018/2019 vintage and predate the new regulation.

UNCONFIRMED / open:
- **Call-sign series for `begrenset lisens`** — N1 says the call identifies
  the class; Nkom has not published which series (N4 still only describes
  LBnXX; N5 shows no new series as of 5.10.2026). Do not infer class from
  Norwegian calls.
- **Whether foreign HAREC (T/R 61-02) still converts** — rule dropped from the
  regulation text; Nkom practice not confirmed.
- **23 cm pre-2028 vs post-2028 reading**, and the 150 kHz bandwidth vs ">150
  kHz ATV at 0.02 W/MHz EIRP" contradiction — ask Nkom; [derived] conservative
  encoding proposed in 3.1.
- **NRRL 23 cm plan** will need replacing before 2028; watch nrrl.no.
- Ny-Ålesund centre coordinates are not in N1 [secondary].
- Pending: none found beyond the 2028 23 cm change.
