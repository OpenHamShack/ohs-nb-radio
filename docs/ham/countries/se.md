# Sweden (SE): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**Headline:** Sweden has no individual amateur licence. Transmitting is
exempt from licensing for holders of a certificate, under **PTSFS 2025:1**
(in force 17 March 2025), which also created the national **instegscertifikat**
(entry level). Power is low by European standards (**200 W PEP** for the full
certificate on most bands; more needs an individual PTS permit), and there is
**no 2300-2400 MHz, no 3.4 GHz and no 70 MHz** in the exemption. **13 cm is
2400-2450 MHz only, at 100 mW PEP** — that is the QO-100 uplink limit unless a
PTS permit is held.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| P1 | "Post- och telestyrelsens föreskrifter om undantag från tillståndsplikt för användning av vissa radiosändare", **PTSFS 2025:1** | "beslutade den 20 februari 2025", "Utkom från trycket den 4 mars 2025", in force 17 March 2025 (ikraftträdande clause, p.60); repeals PTSFS 2022:19. 71 pages. | https://pts.se/contentassets/b05c8a7d01a64783aafc6a19e1b78590/ptsfs-2025-1-foreskrifter-om-undantag-fran-tillstandsplikt-for-anvandning-av-vissa-radiosandare.pdf | `bd9ece78d49dcd45691cbdef8414e5c8fee089cd0f923ee483fcdc73dc4d571d` | Swedish |
| P2 | PTS, "Amatörradioverksamhet i Sverige" (letter "Till den det vederbör") | dated 2022-07-01; PDF ModDate 3 Mar 2025 | https://pts.se/contentassets/a77f2128e5404beb8ea063ec527ed682/amatorradio-i-sverige.pdf | `9fb0519afa76a0860456658376b2862c215b4ce703fd307e210857fc56ab1cb9` | Swedish |
| P3 | PTS, "Amateur radio licenses in Sweden" (English version of P2) | dated 2022-07-01; PDF ModDate 19 Dec 2024 | https://pts.se/contentassets/8a829f8840544a8d9e83f3c69f0eaa70/amateur-radio-in-sweden-1.pdf | `cf3c4024765083dd26846463bd297a8852b58f0f5440d08e1ec2093bac6c2246` | English |
| P4 | PTS web page "Amatörradio" | "uppdaterad 2025-03-06" (as reported by the fetch) | https://pts.se/radio/amatorradio/ | — | Swedish |
| S1 | SSA "BANDPLAN KORTVÅG" (SSA HF Bandplan v3.3) | "v.3.3 2025-09-30"; header "Enligt IARU Region 1 2020-10-16"; file posted 2026-03-04 | https://www.ssa.se/ssa/dokument/bandplaner/ (download via session token) | `7ab79228b082a1f185d6518409a773fda4d88e3aecc5c7b7accb57027cdf354c` | Swedish |
| S2 | SSA "BANDPLAN VHF-UHF" (SSA VUHF Bandplan v3.2) | "v.3.2 2025-09-30"; header "Enligt IARU Region 1 (dec 2020) med NRAU tillägg"; posted 2026-03-04 | https://www.ssa.se/ssa/dokument/bandplaner-vhf-shf/ | `dd745b9db67859de3c6ea2dd36e26f8cfaefee4670486f44d18310fae2371277` | Swedish |
| S3 | SSA "Bandplan 2400 - 2450 MHz" | "Utgåva: 2020-11-25, SM6AFV" | same page as S2 | `1cf12be89ae63d426090bce4a1378bf759ae52b4acd740bfe0dda3a85d00e4f7` | Swedish |
| S4 | SSA "Bandplan 3400 - 3410 MHz" | "Utgåva: 2020-11-25, SM6AFV" | same page as S2 | `32e5ce0ed2e5575f0c2fa407e36845a19ef1d71225f5d6dd17c6e767b58dd38d` | Swedish |
| S5 | SSA "Bandplan 70 - 70,5 MHz" | "Utgåva: 2020-11-28, SM6EAN" | same page as S2 | `21a3e20bce6c4c7ba3d0ccc33c67b2d872244bbc67e73aa0660a1d4df6b9b485` | Swedish |
| S6 | SSA news "Sverige – vi har ett instegscertifikat" | 4 March 2025 | https://www.ssa.se/sverige-vi-har-ett-instegscertifikat/ | — | Swedish |
| S7 | SSA "Amateur radio visitors to Sweden" | undated, fetched 2026-10-08 | https://www.ssa.se/international/amateur-radio-visitors-to-sweden/ | — | English |
| S8 | SSA "Amatörradiocertifikat" | fetched 2026-10-08 | https://www.ssa.se/amatorradio/amatorradiocertifikat/ | — | Swedish |
| X1 | SK4EA club page "Information om instegscertifikat" | undated (footer 2026) | https://sk4ea.se/infomation-om-instegscertifikat/ | — | Swedish |
| C1 | CEPT Recommendation T/R 61-01, Annex 2 | "latest updated on 18 October 2024", annex "Edition of 16 February 2024" | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | English |
| C2 | ECC/REC/(05)06, Annex 2 | "Edition 16 February 2024" | https://docdb.cept.org/download/4413 | `30f2b55b5d3b30289b6e4ca847dbb3623435592512e99d2ad4a8e748615155d3` | English |

All PDFs fetched 2026-10-08 (HTTP 200), converted with `pdftotext -layout`.
PTSFS page numbers below are the PDF page numbers, which match the printed
folio. The SSA PDFs sit behind a per-session token; they were fetched with a
cookie-holding client from the listing pages.

## 1. Regulator and legal instruments

- **Regulator:** Post- och telestyrelsen (**PTS**). SSA (Föreningen Sveriges
  Sändareamatörer) has issued certificates and call signs on PTS's behalf since
  1 October 2004 [P2].
- **Law:** lagen (2022:482) om elektronisk kommunikation (LEK) 3 kap. 4 §;
  förordningen (2022:511) 3 kap. 26 § [P1 p.1].
- **Instrument:** **PTSFS 2025:1**, "föreskrifter om undantag från
  tillståndsplikt för användning av vissa radiosändare" [P1]. Amateur rules are
  individual paragraphs in 3 kap. in frequency order (27 §, 35 §, 38-41 §,
  43 §, 46 §, 48-49 §, 52 §, 59-64 §, 85-86 §, 98-99 §, 103-104 §, 123 §,
  154 §, 185 §, 203 §, 213 §, 226 §, 235 §, 248 §, 256 §, 258-259 §); the
  Bilaga (p.60 ff.) lists them under "Amatörradiotrafik".
- **Since 1 Oct 2004** amateur transmitters are licence-exempt for
  certificate holders: "Undantaget från tillståndsplikt gäller endast den som
  har ett giltigt amatörradiocertifikat utfärdat eller erkänt av PTS" [P2].
- **Higher power / other bands = individual PTS permit:** P4: an individual
  permit is needed for "högre effekt än gränsen för undantag för
  tillståndsplikt" (*higher power than the exemption limit*); SSA: "För högre
  effekt, max 1 kW krävs tillstånd från PTS" [S1, S2]. PTS may issue temporary
  70 MHz permits [S5]; issues none for 2320 MHz or 3400 MHz [S3, S4]; satellite
  power on 2.4 GHz may be applied for [S3].
- **Pending as of 2026-10-08:** no amendment to PTSFS 2025:1 found (PTS page
  P4 last updated 2025-03-06; searches for PTSFS 2025/2026 amendments found
  none) — **[UNCONFIRMED] that none exists**; PTS's regulation search page was
  behind a bot check.

## 2. Licence classes

P1 2 kap. 1 §: "amatörradiocertifikat: kunskapsbevis utfärdat eller godkänt av
Post- och telestyrelsen ... som utvisar att godkänt kunskapsprov avlagts" and
"instegscertifikat för amatörradio: kunskapsbevis utfärdat eller godkänt av
Post- och telestyrelsen ... som utvisar att godkänt kunskapsprov avlagts".

| class id (lowercase, for code) | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `certifikat` | Amatörradiocertifikat | HAREC: "kunskaper i enlighet med Annex 6 i CEPT Rekommendation T/R 61-02 ... version 5 februari 2016" [P1 27 §, p.14] | **T/R 61-01**: Sweden "SM, SA", national licences "All" [C1 p.7, notes 15-16] | SM, SA (and older 7S/8S, SB-SL special/club) — see §6 |
| `insteg` | Instegscertifikat för amatörradio | "kunskaper i enlighet med ECC Report 89" [P1 49 §, p.17] | **none**. Sweden is not in ECC/REC/(05)06 Annex 2 [C2 p.5]; SSA: "International reciprocal rights cannot be assumed" [S8] | **SH** [secondary: S6 (proposal), X1, ARNewsline] |

Older certificate classes (A, B, C, CEPT 1, CEPT 2, Klass 1 — differing only
in Morse speed) are all the full certificate today [P2, P3; C1 note 16 "All"].

Instegscertifikat conditions [P1 49 §, p.17]:
- "Ett svenskt instegscertifikat får endast användas med CE-märkta
  radiosändare." — *A Swedish entry certificate may only be used with
  CE-marked transmitters* (no home-built or modified TX — relevant to SDR/Pluto
  users: **a Pluto/HL2 is not CE-marked as an amateur transmitter**
  [derived]; the app should warn).
- "Instegscertifikat för amatörradiosändare ger inte rätt att använda
  automatiska amatörradiosändare eller fjärrstyrning av amatörradiosändare." —
  *gives no right to automatic stations or remote control.*

## 3. Permitted bands and power, per class

Reference: almost every row reads "**Högsta effekt tillförd antennsystemet: N W
p.e.p.**" — *maximum power supplied to the antenna system, PEP* (i.e.
transmitter output PEP into the feeder). Exceptions in bold: 135.7 kHz ERP,
472 kHz EIRP, 60 m EIRP, insteg 2 m ERP. No bandwidth or primary/secondary
status is stated in P1 (status per ITU/EFIS, not encoded here).

| lo Hz | hi Hz | band | status | `insteg` | `certifikat` | notes | source |
|---|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | (not stated) | — | **1 W ERP** | "Högsta effekt: 1 W e.r.p." | P1 27 § p.14 |
| 472 000 | 479 000 | 630 m | — | — | **1 W EIRP** | "Högsta effekt: 1 W e.i.r.p." | P1 35 § p.15 |
| 1 810 000 | 1 850 000 | 160 m | — | — | 200 W PEP | | P1 38 § p.16 |
| 1 850 000 | 1 900 000 | 160 m | — | — | **10 W PEP** | | P1 39 § p.16 |
| 1 900 000 | 1 950 000 | 160 m | — | — | **100 W PEP** | | P1 40 § p.16 |
| 1 950 000 | 2 000 000 | 160 m | — | — | **10 W PEP** | | P1 41 § p.16 |
| 3 500 000 | 3 800 000 | 80 m | — | — | 200 W PEP | insteg has **no 80 m** | P1 43 § p.16 |
| 5 351 500 | 5 366 500 | 60 m | — | — | **15 W EIRP** | WRC-15 segment exactly | P1 46 § p.16 |
| 7 000 000 | 7 200 000 | 40 m | — | 25 W PEP | 200 W PEP | | P1 48 § p.16, 49 § p.17 |
| 10 100 000 | 10 150 000 | 30 m | — | — | **150 W PEP** | | P1 52 § p.17 |
| 14 000 000 | 14 350 000 | 20 m | — | 25 W PEP | 200 W PEP | | P1 59 §, 60 § p.18 |
| 18 068 000 | 18 168 000 | 17 m | — | — | 200 W PEP | | P1 61 § p.18 |
| 21 000 000 | 21 450 000 | 15 m | — | 25 W PEP | 200 W PEP | | P1 62 §, 63 § p.18 |
| 24 890 000 | 24 990 000 | 12 m | — | — | 200 W PEP | | P1 64 § p.18 |
| 28 000 000 | 29 700 000 | 10 m | — | 25 W PEP | 200 W PEP | | P1 85 §, 86 § p.21 |
| 50 000 000 | 52 000 000 | 6 m | — | 25 W PEP | 200 W PEP | | P1 98 §, 99 § p.23 |
| 144 000 000 | 146 000 000 | 2 m | — | **25 W ERP** | 200 W PEP | insteg limit is ERP, not PEP output | P1 103 §, 104 § p.23 |
| 432 000 000 | 438 000 000 | 70 cm | — | — | 200 W PEP | 430-432 / 438-440 not amateur; insteg has **no 70 cm** | P1 123 § p.26 |
| 1 240 000 000 | 1 300 000 000 | 23 cm | — | — | 200 W PEP | | P1 154 § p.34 |
| 2 400 000 000 | 2 450 000 000 | 13 cm | — | — | **0.1 W PEP** ("100 mW p.e.p.") | **2300-2400 not amateur** | P1 185 § p.47 |
| 5 650 000 000 | 5 850 000 000 | 6 cm | — | — | 200 W PEP | | P1 203 § p.51 |
| 10 000 000 000 | 10 500 000 000 | 3 cm | — | — | 200 W PEP | | P1 213 § p.53 |
| 24 000 000 000 | 24 250 000 000 | 1.2 cm | — | — | 200 W PEP | | P1 226 § p.55 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | — | — | 200 W PEP | | P1 235 § p.57 |
| 75 500 000 000 | 81 000 000 000 | 4 mm | — | — | 200 W PEP | one block | P1 248 § p.59 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | — | — | 200 W PEP | | P1 256 § p.60 |
| 134 000 000 000 | 141 000 000 000 | 2 mm | — | — | 200 W PEP | | P1 258 § p.60 |
| 241 000 000 000 | 250 000 000 000 | 1 mm | — | — | 200 W PEP | | P1 259 § p.60 |

**Original wording (P1), with translation:**

- 27 § (p.14): "135,7–137,8 kHz: Radiosändare för amatörradiotrafik. Högsta
  effekt: 1 W e.r.p." — *Transmitters for amateur traffic. Maximum power 1 W
  ERP.* "De tekniska egenskaperna hos amatörradiosändaren ska anpassas så att
  de inte stör användningen av andra radioanläggningar." — *The technical
  characteristics shall be adapted so as not to disturb other radio users.*
  "Den som använder en amatörradiosändare ska ha ett amatörradiocertifikat." —
  *Whoever uses an amateur transmitter must hold an amateur certificate.*
  (Paragraphs 3-6 of 27 § — certificate, exam, call sign, automatic stations —
  are applied to every other full-certificate band by "I övrigt gäller 27 §
  tredje–sjätte styckena" — *otherwise 27 § paragraphs 3-6 apply*.)
- 35 § (p.15): "472–479 kHz ... Högsta effekt: 1 W e.i.r.p."
- 38 § (p.16): "1 810–1 850 kHz ... Högsta effekt tillförd antennsystemet: 200
  W p.e.p." — *Maximum power supplied to the antenna system: 200 W PEP.*
- 39 §: "1 850–1 900 kHz ... 10 W p.e.p."; 40 §: "1 900–1 950 kHz ... 100 W
  p.e.p."; 41 §: "1 950–2 000 kHz ... 10 W p.e.p." (all "tillförd
  antennsystemet").
- 43 §: "3,5–3,8 MHz ... 200 W p.e.p."
- 46 § (p.16): "5,3515–5,3665 MHz: Radiosändare för amatörradiotrafik. Högsta
  effekt: 15 W e.i.r.p."
- 48 §: "7,0–7,2 MHz ... 200 W p.e.p."
- 49 § (p.17): "7,0–7,2 MHz: Radiosändare för amatörradiotrafik med svenskt
  instegscertifikat. Högsta effekt tillförd antennsystemet: 25 W p.e.p." —
  *for amateur traffic with a Swedish entry certificate: 25 W PEP to the
  antenna system.*
- 52 §: "10,10–10,15 MHz ... 150 W p.e.p."
- 59 § / 60 §: "14,00–14,35 MHz ... 200 W p.e.p." / "... med svenskt
  instegscertifikat ... 25 W p.e.p. I övrigt gäller vad som framgår av 49 §
  tredje till sjätte styckena." (*otherwise 49 § paragraphs 3-6 apply* — the
  CE-marking, ECC Report 89, call-sign and no-automatic/remote rules.)
- 61 § 18,068–18,168 MHz 200 W p.e.p.; 62 § / 63 § 21,00–21,45 MHz 200 / 25 W
  p.e.p.; 64 § 24,89–24,99 MHz 200 W p.e.p.; 85 § / 86 § 28,0–29,7 MHz 200 /
  25 W p.e.p.; 98 § 50,0–52,0 MHz 200 W p.e.p.; 99 § "50–52 MHz:
  Radiosändare för amatörradiotrafik med svenskt instegscertifikat. Högsta
  effekt tillförd antennsystemet: 25 W p.e.p."
- 103 § (p.23): "144–146 MHz ... Högsta effekt tillförd antennsystemet: 200 W
  p.e.p." 104 §: "144–146 MHz: Radiosändare för amatörradiotrafik med svenskt
  instegscertifikat. **Högsta effekt: 25 W e.r.p.**" — *Maximum power 25 W ERP*
  (radiated, so antenna gain counts).
- 123 § (p.26): "432–438 MHz ... 200 W p.e.p."
- 154 § (p.34): "1 240–1 300 MHz ... 200 W p.e.p."
- 185 § (p.47): "2 400–2 450 MHz: Radiosändare för amatörradiotrafik. Högsta
  effekt tillförd antennsystemet: 100 mW p.e.p." — *maximum power supplied
  to the antenna system: 100 mW PEP.*
- 203 § 5,65–5,85 GHz, 213 § 10,0–10,5 GHz, 226 § 24,00–24,25 GHz, 235 §
  47,0–47,2 GHz, 248 § 75,5–81,0 GHz, 256 § 122,25–123,00 GHz, 258 § 134–141
  GHz, 259 § 241–250 GHz: each "Högsta effekt tillförd antennsystemet: 200 W
  p.e.p."

### 3.1 Per-band exceptions

- **160 m in four steps:** 1810-1850 200 W, 1850-1900 10 W, 1900-1950 100 W,
  1950-2000 10 W PEP (full certificate). Encode as four rows.
- **60 m:** 5351.5-5366.5 kHz, **15 W EIRP**, full certificate only. No
  national 60 m channels.
- **30 m:** 150 W PEP (not 200).
- **Insteg 2 m:** 25 W **ERP** (guard must use the antenna gain chain:
  ERP = P·G(dBd)); all other insteg rows are 25 W PEP output.
- **13 cm:** 2400-2450 MHz only, **100 mW PEP** to the antenna system. SSA
  [S3]: "I Sverige har PTS bjudit ut bandet 2300 - 2400 MHz till auktion
  varför bandet tagits bort ut föreskriften för amatörradio; PTS ger för
  närvarande inga tillstånd för 2320MHz. Ansökan om högre effekt i bandet
  2400 MHz för satellitkommunikation kan göras till PTS." — *PTS auctioned
  2300-2400 MHz, so the band was removed from the amateur rules; PTS currently
  issues no permits for 2320 MHz. Higher power at 2400 MHz for satellite
  communication may be applied for from PTS.* [secondary for the permit
  practice; the 100 mW limit itself is P1 185 §]
- **3.4 GHz:** not in P1. S4: "För närvarande finns inget Svenskt
  amatörradioband eller frekvenser i 3400MHz-bandet ... PTS ger för närvarande
  inga tillstånd för 3400MHz."
- **70 MHz:** not in P1. S5: "För närvarande finns inget Svenskt
  amatörradioband eller frekvenser i 70MHz-bandet ... Tilldelning av
  tillfälliga tillstånd i 70MHz-bandet kan ges av PTS." — *no Swedish 70 MHz
  amateur band; PTS may grant temporary permits.* Guard: refuse (no permit
  setting).
- **Higher power:** any power above the table needs an individual PTS
  permit (SSA: up to 1 kW). Not encodable; refuse.
- **Insteg:** CE-marked transmitters only; no automatic stations, no remote
  control [P1 49 §].
- **Training/demonstration exemption [P1 27 §]:** a non-holder may transmit
  under supervision of a certificate holder, using the supervisor's or club's
  call.
- **Automatic stations [P1 27 §]:** beacons, repeaters, position transmitters
  must identify regularly (CW, voice or otherwise) with the responsible
  person's call; the operator needs their own full certificate.
- **No bandwidth limits, no antenna-gain rule, no mobile/portable power rule,
  no geographic exclusions** in P1 for amateur.

### 3.2 Gaps: not permitted for any class (list explicitly)

Within 135.7 kHz - 10.5 GHz, everything not in a row above, notably:
137.8-472 kHz; 479-1810 kHz; 2000-3500 kHz; 3800-5351.5 kHz; 5366.5-7000 kHz;
7200-10 100 kHz; 10 150-14 000 kHz; 14 350-18 068 kHz; 18 168-21 000 kHz;
21 450-24 890 kHz; 24 990-28 000 kHz; 29.7-50 MHz; **52-144 MHz (incl.
70-70.5 MHz)**; 146-432 MHz (**430-432 MHz not amateur**); **438-440 MHz**;
440-1240 MHz; **1300-2400 MHz (incl. 2300-2400 MHz)**; **2450-5650 MHz (incl.
3400-3410 MHz)**; 5850-10 000 MHz; 10.5-24 GHz.

For `insteg`, everything except 7.0-7.2, 14.0-14.35, 21.0-21.45, 28.0-29.7,
50-52 and 144-146 MHz.

## 4. Satellite / QO-100

- **QO-100 uplink 2400-2450 MHz:** full certificate only, **100 mW PEP
  supplied to the antenna system** [P1 185 §, p.47]. No EIRP limit, so dish
  gain is unrestricted (100 mW into a 1.2 m dish is marginal for SSB, enough
  for CW/narrow digital [derived]). Higher power requires an individual PTS
  permit, which SSA says may be applied for "för satellitkommunikation" [S3,
  secondary]. `insteg`: **not permitted** (no 13 cm row).
- **10.45-10.5 GHz:** inside 10.0-10.5 GHz, full certificate 200 W PEP.
  Receive needs nothing.
- P1 has no amateur-satellite-specific rules; satellite sub-bands are only in
  the SSA plan.

## 5. CEPT / visiting operators

- **T/R 61-01:** implemented. C1 Annex 2 (p.7): "Sweden | SM, SA | All",
  note 15: "After 1 October 2004 amateur radio is exempted from licencing.
  Exemption is only applicable for anyone who has a valid amateur radio
  certificate..." So every Swedish full certificate = CEPT licence.
- **ECC/REC/(05)06:** **not implemented** — Sweden is absent from Annex 2
  [C2 p.5]. SSA: visitors with "Novice, Intermediate, or similar licenses
  cannot operate" in Sweden [S7, secondary]. `insteg` is national only.
- **T/R 61-02:** the full certificate requires "Annex 6 i CEPT Rekommendation
  T/R 61-02 ... version 5 februari 2016" [P1 27 §]; foreign HAREC holders
  resident in Sweden can obtain an SA call via SSA [S7/SSA "Obtaining a
  Swedish callsign", secondary].
- **Visitors** [S7, secondary]: CEPT-licence holders, stays up to 3 months,
  "SM/your call" or "SA/your call", optionally with the call-area digit
  ("SM6/your call"); same terms as Swedish full certificate holders.

## 6. Callsigns

- P1 27 §: "Den som innehar amatörradiocertifikat ska ha en egen
  anropssignal. Denna framgår av certifikatet, eller tidigare av
  amatörradiotillståndet." — *The holder must have their own call sign, shown
  on the certificate (or the earlier licence).* Same for insteg [P1 49 §].
- C1 gives Swedish prefixes **SM, SA** for T/R 61-01 use.
- **Insteg: SH series** (e.g. SH5XYZ) — SSA news 4 Mar 2025 said the proposal
  to PTS was SH "though final delegation awaits" [S6]; club page X1
  ("Anropssignaler ur SH-prefixserien") and ARNewsline (31 Jul 2025, "Sweden's
  new callsign prefix SH") say it is in use [secondary]. **[UNCONFIRMED] from
  PTS.**
- **Call-area digit 0-7** after the prefix indicates a district (e.g. SM0
  Stockholm area, SM7 south) [secondary; no primary map found]. SK = club
  stations, SL/SJ/7S/8S = special/club/contest [secondary].
- **Portable:** P1 has no /P /M rule. Visitors prefix SM/ or SA/ (optionally
  with district) [S7].
- **Regex hints** (warn only): `^SH\d[A-Z]{2,3}$` → insteg; `^(SM|SA)\d[A-Z]{1,3}$`
  → full certificate (an SM/SA call is never insteg [derived from the SH
  series being exclusive to insteg, secondary]); `^S[B-L]\d` and `^[78]S\d` →
  club/special.

## 7. National band plan

SSA HF plan v3.3 (2025-09-30) [S1] "Enligt IARU Region 1 2020-10-16" and SSA
VHF-UHF plan v3.2 (2025-09-30) [S2] "Enligt IARU Region 1 (dec 2020) med NRAU
tillägg". Both repeat "Max 200 W p.e.p. ... För högre effekt, max 1 kW krävs
tillstånd från PTS." Both shade the insteg bands ("Frekvensband upplåtna även
för instegscertifikat"). (S1's header also cites "PTS frekvensplan PTSFS
2025:2" while its footer cites PTSFS 2025:1 — an SSA labelling slip; P1 is
2025:1.)

**HF [S1]** — IARU R1 2020 segments; Swedish notes:
| lo kHz | hi kHz | max BW Hz | use / notes |
|---|---|---|---|
| 135.7 | 137.8 | 200 | CW, QRSS, digimodes; "Högsta utstrålad effekt 1 W e.r.p." |
| 472 | 475 | 200 | CW |
| 475 | 479 | 500 (rec.) | CW, digimodes; avoid NDBs |
| 1810 | 1838 | 200 | CW exclusive; 1836 CW QRP |
| 1838 | 1840 | 500 | narrowband; no packet on 160 m; PSK 1838.150 |
| 1840 | 1843 | 2700 | all modes, digimodes; SSB QRP 1843 |
| 1843 | 2000 | 2700 | all modes; "Max 10 W p.e.p. inom 1850-1900 och 1950-2000. Max 100 W inom 1900-1950 kHz" |
| 3500 | 3510 | 200 | CW exclusive, intercontinental priority |
| 3510 | 3570 | 200 | CW exclusive; contest 3510-3560; QRS 3555; QRP 3560 |
| 3570 | 3580 | 200 | narrowband/digimodes |
| 3580 | 3590 | 500 | narrowband/digimodes |
| 3590 | 3600 | 500 | narrowband, automatic digimodes |
| 3600 | 3620 | 2700 | all modes, automatic digimodes |
| 3600 | 3650 | 2700 | SSB contest; DV 3630 |
| 3650 | 3700 | 2700 | SSB QRP 3690 |
| 3700 | 3775 | 2700 | SSB contest 3700-3800; image 3775 (sic, R1 has 3735); R1 emergency 3760 |
| 3775 | 3800 | 2700 | intercontinental SSB priority |
| 5351.5 | 5354.0 | 200 | CW, digimodes; "Högsta utstrålad effekt 15 W e.i.r.p." |
| 5354.0 | 5366.0 | 2700 | all modes, USB recommended |
| 5366.0 | 5366.5 | 20 | extreme narrowband only |
| 7000 | 7040 | 200 | CW exclusive; QRP 7030 |
| 7040 | 7050 | 500 | narrowband; automatic 7047-7050 |
| 7050 | 7060 | 2700 | all modes; automatic 7050-7053 |
| 7060 | 7100 | 2700 | SSB contest; DV 7070; SSB QRP 7090 |
| 7100 | 7130 | 2700 | R1 emergency 7110 |
| 7130 | 7175 | 2700 | SSB contest; image 7165 |
| 7175 | 7200 | 2700 | intercontinental SSB priority |
| 10100 | 10130 | 200 | CW exclusive; QRP 10116; "Max effekt 150 W p.e.p." |
| 10130 | 10150 | 500 | narrowband, digimodes |
| 14000 | 14070 | 200 | CW exclusive; contest 14000-14060; QRS 14055; QRP 14060 |
| 14070 | 14099 | 500 | narrowband; automatic 14089-14099 |
| 14099 | 14101 | 200 | **IBP beacons exclusive** |
| 14101 | 14112 | 2700 | all modes, digimodes, automatic |
| 14112 | 14350 | 2700 | SSB contest 14125-14300; DV 14130; DXpedition 14195±5; image 14230; SSB QRP 14285; emergency 14300 |
| 18068 | 18095 | 200 | CW exclusive; QRP 18086 |
| 18095 | 18105 | 500 | narrowband |
| 18105 | 18109 | 500 | automatic digimodes |
| 18109 | 18111 | 200 | **IBP beacons exclusive** |
| 18111 | 18120 | 2700 | all modes, automatic |
| 18120 | 18168 | 2700 | SSB QRP 18130; DV 18150; emergency 18160 |
| 21000 | 21070 | 200 | CW exclusive; QRS 21055; QRP 21060 |
| 21070 | 21090 | 500 | narrowband; 21090-21110 automatic digimodes |
| 21110 | 21120 | 2700 | all modes except SSB |
| 21120 | 21149 | 500 | narrowband |
| 21149 | 21151 | 200 | **IBP beacons exclusive** |
| 21151 | 21450 | 2700 | DV 21180; SSB QRP 21285; image 21340; emergency 21360 |
| 24890 | 24915 | 200 | CW exclusive; QRP 24906 |
| 24915 | 24929 | 500 | narrowband; automatic 24925-24929 |
| 24929 | 24931 | 200 | **IBP beacons exclusive** |
| 24931 | 24990 | 2700 | all modes; automatic 24931-24940; SSB QRP 24950; DV 24960 |
| 28000 | 28070 | 200 | CW exclusive; QRS 28055; QRP 28060 |
| 28070 | 28190 | 500 | narrowband; 28070-28120 digi; 28120-28150 automatic |
| 28190 | 28225 | 200 | **beacons exclusive** (28190-28199 regional time-shared, 28199-28201 IBP, 28201-28225 continuous) |
| 28225 | 28300 | 2700 | all modes, beacons |
| 28300 | 28320 | 2700 | all modes, digimodes, automatic |
| 28320 | 29000 | 2700 | DV 28330; SSB QRP 28360; image 28680 |
| 29000 | 29100 | unlimited | all modes |
| 29100 | 29200 | unlimited | FM simplex, 10 kHz channels, ±2.5 kHz deviation |
| 29200 | 29300 | unlimited | digimodes, automatic |
| 29300 | 29510 | unlimited | **satellite downlink** ("Fyrband ... Gäller även segmentet för 10 m satellit nerlänk" — no transmission) |
| 29510 | 29520 | — | guard band, no transmission |
| 29520 | 29590 | 6000 | **FM repeater input** RH1-RH8 |
| 29600 | 29620 | 6000 | FM simplex; 29600 calling; 29610 simplex parrot |
| 29620 | 29700 | 6000 | **FM repeater output** RH1-RH8, "100 kHz duplexskift" |
10 m repeaters: **−100 kHz** (input below output). SSB: LSB below 10 MHz, USB
above; lowest LSB dial 3 kHz above band edge, USB 3 kHz below the top.

**6 m [S2]:** 50.000-50.100 CW 500 Hz (centres 50.050, 50.090); 50.100-50.130
intercontinental DX only; 50.100-50.200 CW/SSB 2.7 kHz (50.110 DX centre,
50.150); 50.200-50.300 general, 50.285 crossband; 50.300-50.400 CW/MGM
(PSK 50.305, EME 50.310-50.320, MS 50.320-50.380); **50.400-50.500 beacons
only** 1 kHz (50.401 ±500 Hz WSPR beacons); 50.500-52.000 all modes 12 kHz
(SSTV 50.510, image 50.550, RTTY 50.600, digi 50.620-50.750, **FM 51.510**);
**51.210-51.390 repeater in, 51.810-51.990 repeater out**, RF81-RF99, 20/10 kHz
spacing → **−600 kHz** [derived].

**2 m [S2]:**
| lo MHz | hi MHz | BW | use |
|---|---|---|---|
| 144.000 | 144.025 | 2.7 kHz | **satellites only** ("Ingen sändning under 144.025") |
| 144.025 | 144.100 | 500 Hz | CW, EME; 144.050 CW centre; 144.100 MS random |
| 144.100 | 144.150 | 500 Hz | CW, MGM; EME MGM 144.110-144.160 |
| 144.150 | 144.400 | 2.7 kHz | CW/SSB/MGM; 144.170 MGM centre; MS SSB 144.195-144.205; **144.300 SSB centre** |
| 144.400 | 144.490 | 500 Hz | **beacons exclusive** |
| 144.491 | 144.493 | 500 Hz | experimental MGM |
| 144.500 | 144.794 | 20 kHz | all modes; image 144.500; RTTY/MGM 144.600; ATV talkback 144.750 |
| 144.794 | 144.9625 | 12 kHz | MGM/digital; **APRS 144.800**; DV internet GW 144.8125-.8625 |
| **144.975** | **145.194** | 12 kHz | **repeater input** 144.975-145.1935, RV46-RV63, 12.5 kHz, 600 kHz shift |
| 145.194 | 145.206 | 12 kHz | space comms (145.200 crewed spacecraft) |
| 145.206 | 145.5625 | 12 kHz | FM simplex V17-V45; **145.500 calling**; RTTY 145.300; internet GW 145.2375/.2875/.3375; **DV 145.375** |
| **145.575** | **145.7935** | 12 kHz | **repeater output** 145.575-145.7875 |
| 145.794 | 145.806 | 12 kHz | space comms |
| 145.806 | 146.000 | 12 kHz | **satellite exclusive** |
Repeaters **−600 kHz**.

**70 cm [S2]** (only 432-438 MHz legal):
| lo MHz | hi MHz | BW | use |
|---|---|---|---|
| 432.000 | 432.025 | 500 Hz | EME exclusive |
| 432.025 | 432.100 | 500 Hz | CW/MGM; 432.050 CW centre; PSK31 432.088 |
| 432.100 | 432.399 | 2.7 kHz | CW/SSB/MGM; **432.200 SSB centre**; 432.350 microwave talkback; FSK441 432.370 |
| 432.400 | 432.490 | 500 Hz | **beacons exclusive** |
| 432.491 | 432.493 | 500 Hz | experimental MGM |
| 432.500 | 432.594 | 12 kHz | all modes; linear transponder in 432.500-432.600; **NRAU digital repeater in 432.500-432.575 (2 MHz shift)** |
| 432.594 | 432.994 | 12 kHz | linear transponder out 432.600-432.800 (R1); **NRAU repeater in 432.600-432.975, RU368-RU398, "nya med 2 MHz skift"** |
| 432.994 | 433.381 | 12 kHz | **old repeater in 433.000-433.375, RU368-RU398, "1.6 MHz skift"** |
| 433.394 | 433.581 | 12 kHz | SSTV 433.400; FM simplex U272-U286; **433.500 FM centre** |
| 433.600 | 434.000 | 20 kHz | RTTY 433.600; FAX 433.700; **APRS 433.800** |
| 434.000 | 434.494 | 20 kHz | NRAU digital channels |
| 434.500 | 434.594 | 20 kHz | **NRAU digital repeater out 434.500-434.575** (the plan prints the row as "433.500 – 433.594", a typo) |
| 434.594 | 434.981 | 12 kHz | **NRAU repeater out 434.600-434.975**, RU368-RU398, 12.5 kHz, 2 MHz shift |
| 435.000 | 438.000 | 20 kHz | **satellite exclusive** |
70 cm repeaters: outputs 434.600-434.975; inputs **−2.0 MHz** (new, 432.600-432.975)
or **−1.6 MHz** (old, 433.000-433.375). A repeater's actual shift must come from
the repeater list, not the band [derived]. **Not R1's −7.6 MHz.**

**23 cm [S2]:** 1240.000-1243.250 all modes (1240-1241 digital); 1243.250-1260
ATV/data (**repeater out 1258.150-1259.350, R20-R68**); 1260-1270 **satellite
only**; 1270-1272 all modes (**repeater in 1270.025-1270.700 RS1-RS28**,
packet RS29-RS50); 1272-1290.994 ATV; **1290.994-1291.481 repeater in
1291.000-1291.475 RM0-RM19, 25 kHz, 6 MHz shift**; 1291.494-1296 all modes;
1296.000-1296.150 CW/MGM (EME 1296.000-.025, CW centre 1296.050, PSK31
1296.138); 1296.150-1296.400 CW/SSB/MGM (**SSB centre 1296.200**, FSK441
1296.370); 1296.400-1296.600 transponder in; 1296.600-1296.800 transponder
out, SSTV/FAX 1296.500, MGM/RTTY 1296.600, 1296.750-.800 local beacons max
10 W; **1296.800-1296.994 beacons exclusive**; **1296.994-1297.481 repeater
out 1297.000-1297.475 RM0-RM19 (−6 MHz)**; 1297.494-1297.981 FM simplex SM20-
SM39, **1297.500 FM centre**; 1299.000-1299.750 5×150 kHz DD; 1299.750-1300
8×25 kHz FM/DV. (No row for 1297.981-1299.000 in S2.)

**13 cm [S3, 2020]:** 2400-2450 "Satellitsegment"; 2400-2402 narrowband;
2400.5 activity centre; 2400.8-2401.0 narrowband beacons; 2427-2443 ATV only if
unused by satellites; "Max 100mW".

**3.4 GHz / 70 MHz:** no Swedish band [S4, S5].

**Differences from IARU R1:**
1. 70 cm: only 432-438 MHz; repeaters 2 MHz (new) or 1.6 MHz (old) split with
   outputs 434.600-434.975 (NRAU), not R1's 430/438 MHz −7.6 MHz; NRAU
   digital repeater pair 432.500-432.575 / 434.500-434.575.
2. 13 cm: only 2400-2450 (whole segment treated as satellite); no 2320 MHz
   narrowband; 3.4 GHz and 70 MHz absent.
3. HF: R1 2020 segments with Swedish legal power notes (160 m steps, 30 m
   150 W, 60 m 15 W EIRP).
4. The plan marks bands also open to insteg.

## 8. Confidence and gaps

**Overall: high for the licence (law), medium-high for the band plan.** P1 is
the current regulation (in force 17 Mar 2025), downloaded and read paragraph by
paragraph with page numbers; every power figure above is quoted. The SSA plans
are current (v3.3 / v3.2, 2025-09-30). The 13 cm, 3.4 GHz and 70 MHz plans are
2020 editions but consistent with P1.

UNCONFIRMED / open:
- **No later amendment to PTSFS 2025:1** — none found, but PTS's regulation
  search was bot-blocked; re-check https://pts.se/regelbibliotek/ before
  release.
- **SH call-sign series for insteg** — SSA/club/news sources only; PTS has not
  been seen stating it.
- **Call-area digit meaning** (0-7 districts) and SB-SL/7S/8S usage —
  secondary only.
- **PTS individual permits** (higher power, 70 MHz, satellite power on 2.4 GHz)
  — exist per SSA/PTS web text; terms not public, not encodable.
- **CE-marking rule for insteg** — law, but the app cannot tell whether the
  user's transmitter is CE-marked; warn insteg users of SDR transmitters.
