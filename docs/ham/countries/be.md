# Belgium (BE): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

Downloads 2026-10-08 with `curl -L -A <browser UA>` (HTTP 200); PDFs converted
with `pdftotext -layout` and the BIPT tables also rendered with `pdftoppm` and
read as images, because their merged cells (one power value spanning many
rows) are ambiguous in text.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| B1 | BIPT, "Besluit van de Raad van het BIPT van 24 mei 2019 betreffende de frequenties, vermogens en transmissiemodi die mogen worden gebruikt door de radioamateurs" — **Bijlage 2** (pp.15–17) is the band/power table | decision 24/05/2019; BIPT page lists publication 27/05/2019; 22 pp. | https://www.bipt.be/file/cc73d96153bbd5448a56f19d925d05b1379c7f21/ba05ea9d3611d44667462d979daa834bca246b0c/2019-05-24-ram-besluit.pdf | `30517ef4b1945deb5f357587923860852fcd49a24a68e11d0563485215fce400` | nl |
| B2 | BIPT, "Frequentiebanden en technische eigenschappen toegestaan voor de radioamateurs. (Uittreksel uit het besluit van de Raad van het BIPT van 24 mei 2019)" — the extract BIPT links as the current table | PDF created 19 Jun 2025; 3 pp. | https://www.bipt.be/file/cc73d96153bbd5448a56f19d925d05b1379c7f21/7578a6d517ba1e5c6db39ca4955c5f58ca067f5f/freq-nl.pdf | `b136d318794b8272d9dfd138c26d25cdf2a350c8358d5821fbc6fd2fdc411a5a` | nl |
| K1 | "Koninklijk besluit van 18 december 2009 betreffende de private radiocommunicatie en de gebruiksrechten voor vaste netten en netten met gedeelde middelen" (consolidated, Justel) — art. 17/1 §3 (classes), 17/7, 17/8 (call sign use); amended by KB 14-12-2018 (in force 01-01-2019) | consolidated text fetched 2026-10-08 | https://www.ejustice.just.fgov.be/eli/besluit/2009/12/18/2009011581/justel | `619bc011f3b800b7064c3dfb5a7cc0ff8e5d80dbf2286e79399ac9d69a775495` (HTML) | nl |
| B3 | BIPT web page "Radioamateurs" (lists the decisions in force; 2026 billing note) | fetched 2026-10-08 | https://www.bipt.be/consumenten/radiofrequenties/privegebruik-hobby/radioamateurs | `136c3511965e0c94b35341cee1a27074e03b8e271b64046a167297e53fbcabfc` | nl |
| B4 | BIPT FAQ "Hoe kies ik mijn roepnaam? Wat zijn de voorwaarden?" | fetched 2026-10-08 | https://www.bipt.be/consumenten/faq/hoe-kies-ik-mijn-roepnaam-wat-zijn-de-voorwaarden | `95a498fb85dd4f1ba2a547eb7fa62b041d08329490a1b8ce7f4b944b52dff1ab` | nl |
| B5 | BIPT, "Raadpleging inzake de frequenties, vermogens en transmissiemodi die mogen gebruikt worden door de radioamateurs" (draft decision, Consult-2024-B1) | 27/03/2024, comments to 28/04/2024 | https://www.bipt.be/file/cc73d96153bbd5448a56f19d925d05b1379c7f21/389a3882ab0d7f2e1ab0f63b76114321d5a2e049/raadpleging-ram-2024-03-27.pdf | `bf0464d638488ca39d58eed883296902d5187a4507fa7e35192d85128340ca8d` | nl |
| CT1 | CEPT T/R 61-01 "CEPT Radio Amateur Licence" | Edition 18 Oct 2024 (Annex 2 ed. 16 Feb 2024) | https://docdb.cept.org/download/4541 (`curl -k`) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| CT2 | ECC/REC/(05)06 "CEPT Novice Radio Amateur Licence" | Edition 16 June 2023 | https://docdb.cept.org/download/4372 (`curl -k`) | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` | en |
| U1 | UBA, "Frequenties / vermogens" **[secondary]** (society restatement; source of the 8 m permit text) | fetched 2026-10-08 | https://www.uba.be/nl/info/frequentie-vermogens | `4e024cd35cc00306c19c736a1e393cf92c8b916ff660b7af1f8f1904df181433` | nl |
| U2 | UBA, "Visiting Belgium" + "Rules and regulations" **[secondary]** | fetched 2026-10-08 | https://www.uba.be/en/visiting-belgium , https://www.uba.be/en/visiting-belgium/rules-and-regulations | `d43780948a6609b3839ddcd4d4f49dd7e059c295b197662295187c82e25f01f5`, `bcb2f40779a908bd4fa43eba0ed94c464b6f19a3a56a942eb43d2fcdcbda12d8` | en |
| U3 | UBA, "Unmanned stations ON" (repeater/beacon list, maintained by ON6URE, "the only official site") | PDF dated 2023-02-05; 26 pp. | https://www.uba.be/sites/default/files/media/files/Unmanned%20stations%20ON%2020230205.pdf | `f775cacab79953d512cc1b4af167236a26f6ac41be94ac88ae5d86d5f6a4acab` | en |
| U4 | UBA band-plan pages (point to IARU-R1 HF and VHF/UHF/SHF plans) | fetched 2026-10-08 | https://www.uba.be/en/hf/bandplanning , https://www.uba.be/en/node/2044 | `08c3869869d45fc2e8d9e343af190634e880ed89a6783d690f3ebaabe61ad92a` (HF page) | en |
| I1 | IARU Region 1 HF band plan 2020 | 2020 | https://www.darc.de/fileadmin/filemounts/referate/hf/hf_r1_bandplan.pdf | `8deb428d565ce79a173d773ff2c0226201c09f0afbb2e46ef1a68729840835cf` | en |
| I2 | IARU Region 1 VHF Handbook | v10.03, Feb 2026 | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf | `147190bd1295cd9050dd735f7d8088f9dbeb1a30c228784fb91b611428caf631` | en |

## 1. Regulator and legal instruments

- **Regulator:** BIPT / IBPT (Belgisch Instituut voor postdiensten en
  telecommunicatie). Amateur licences are "vergunningen van de 5e categorie".
- **Law:** Wet van 13 juni 2005 betreffende de elektronische communicatie, art.
  13 (spectrum management) and art. 40 (technical rules) [B1 §§11–12].
- **Royal decree:** KB 18-12-2009 as amended by KB 14-12-2018 (in force
  01-01-2019), which created the three certificate classes [K1 art. 17/1 §3;
  B1 §§2–4]. Two documents are needed to operate: the *bedieningscertificaat*
  (operator certificate, 5 years, carries the call sign) and, for own
  equipment, the yearly *stationsvergunning* [B3].
- **The band/power table:** BIPT Council decision of **24 May 2019** [B1],
  Bijlage 2; "Dit besluit treedt in werking op de dag van publicatie op de
  website van het BIPT" [B1 §27] (BIPT page: 27/05/2019). It repealed the
  decision of 24 April 2012 [B1 §23]. BIPT's page still lists it as the decision
  in force in 2026 [B3], and BIPT's current extract (B2, generated June 2025)
  reproduces it.
- **Pending (2026-10-08):** BIPT consultation of 27/03/2024 [B5] on a new
  decision after WRC-23 (ITU-R M.2164): it would cut class A on 23 cm to
  1255.76–1258 MHz and 1260–1262 MHz (50 W e.i.u.v.), 1296–1298 MHz (50 W) and
  1298–1300 MHz (150 W), and give class B 1296–1300 MHz [B5 pp.6–7]. **No final
  decision found** — BIPT's page lists only the 2019 decision. CEPT ECC Decision
  (25)01 on the 23 cm band was adopted in 2025 [secondary: pi4raz.nl
  2025-07-28]. Treat 23 cm as liable to change; re-check before every release.

## 2. Licence classes

| class id | national name | exam level | CEPT equivalence | callsign prefixes (B4) |
|---|---|---|---|---|
| `a` | bedieningscertificaat klasse A ("HAREC-certificaat") | HAREC (T/R 61-02) [K1 art. 17/1 §3 1°] | T/R 61-01: "Belgium — ON — A" [CT1 p.5] | ON1, ON4, ON5, ON6, ON7, ON8, ON9 |
| `b` | klasse B (novice, "nieuw" in 2019) | ECC (05)06 / ERC Report 32 [K1 17/1 §3 2°] | ECC/REC/(05)06: "Belgium — ON — B" [CT2 p.5] | ON2 |
| `c` | klasse C ("basiscertificaat") | ECC Report 89 entry level [K1 17/1 §3 3°] | **none** — "there is no automatic recognition of foreign ECC Report 89 licences" [U2, secondary]; not in CT1/CT2 | ON3 |

K1 art. 17/1 §3 (original): "1 het klasse A-bedieningscertificaat dat
overeenstemt met het geharmoniseerde certificaat voor het "HAREC"-
radioamateurexamen … 2 het klasse B-bedieningscertificaat dat overeenstemt met
het beginnerscertificaat bedoeld in aanbeveling ECC (05)06 … 3 het klasse
C-bedieningscertificaat dat overeenstemt met het basiscertificaat bedoeld in
het rapport 89 van het ECC".

## 3. Permitted bands and power, per class

Source: B1 Bijlage 2 (class A p.15, B and C p.16, notes p.17), cross-checked
cell by cell against B2 (pp.1–2, rendered as images). Column header (B1):
"Toegestane maximumvermogen (8)" [permitted maximum power]. **The decision
does not say whether "W" means PEP, mean, or carrier, nor where it is
measured — [UNCONFIRMED]**; K1 has no definition either. Only some cells name
a reference: "e.u.v." (= effectief uitgestraald vermogen, **ERP**) and
"e.i.u.v." (= equivalent isotroop uitgestraald vermogen, **EIRP**); B2 writes
the French abbreviations "p.a.r." (ERP) and "p.i.r.e." (EIRP) for the same
cells. Recommend encoding plain-W cells as **PEP at transmitter output**
(the usual CEPT convention and what UBA's English page implies by "1500 Watt
output" [U2]) and flagging it.

Status: "P primaire dienst; PEX primaire en exclusieve dienst; S secundaire
dienst" [B1 p.17].

| lo Hz | hi Hz | band | status | a | b | c | notes (B1 "Verwijzing") | source |
|---|---|---|---|---|---|---|---|---|
| 135700 | 137800 | 2200 m | S | 1 W ERP ("1 W e.u.v.") | — | — | | B1 p.15 |
| 472000 | 479000 | 630 m | S | 5 W EIRP ("5 W e.i.u.v.") | — | — | | B1 p.15 |
| 501000 | 504000 | 600 m | S | 5 W EIRP (cell shared with 472 row) | — | — | **A1A only; (6) max bandwidth 100 Hz** | B1 p.15; B2 p.1 |
| 1810000 | 1830000 | 160 m | S | 1500 W | 100 W | — | (1) no interference to primary **or secondary** services, no protection | B1 p.15–16 |
| 1830000 | 1850000 | 160 m | PEX | 1500 W | 100 W | — | | B1 |
| 1850000 | 2000000 | 160 m | S | **150 W** | 100 W | — | | B1 |
| 3500000 | 3800000 | 80 m | P | 1500 W | 100 W | 25 W | | B1 |
| 5351500 | 5366500 | 60 m | S | **15 W ERP ("15 W e.u.v.")** | — | — | see 3.1 (law says ERP; WRC-15 and UBA say EIRP) | B1 p.15 |
| 7000000 | 7100000 | 40 m | PEX | 1500 W | 100 W | 25 W | (2) sat allowed | B1 |
| 7100000 | 7200000 | 40 m | S | 1500 W | 100 W | 25 W | | B1 |
| 10100000 | 10150000 | 30 m | S | 1500 W | 100 W | 25 W | | B1 |
| 14000000 | 14350000 | 20 m | PEX | 1500 W | 100 W | 25 W | (2) sat 14.000–14.250 | B1 |
| 18068000 | 18168000 | 17 m | PEX | 1500 W | 100 W | — | (2) | B1 |
| 21000000 | 21450000 | 15 m | PEX | 1500 W | 100 W | 25 W | (2) | B1 |
| 24890000 | 24990000 | 12 m | PEX | 1500 W | 100 W | — | (2) | B1 |
| 28000000 | 29700000 | 10 m | PEX | 1500 W | 100 W | 25 W | (2) | B1 |
| 40660000 | 40690000 | 8 m | S | **5 W ERP, individual BIPT permit only** | — | — | from U1 [secondary]: permit as annex to station licence, 1 calendar year, A1A/F3E/J2D/J2B/J3E, logbook sent to BIPT yearly | U1 |
| 50000000 | 52000000 | 6 m | S | 200 W | 100 W | — | | B1 |
| 69945000 | 69955000 | 4 m | S | 10 W EIRP ("10 W e.i.u.v.") | — | — | printed "69,950 – 69,950"; (7) max bandwidth **10 kHz** → channel 69.945–69.955 [derived] | B1 p.15 |
| 70112500 | 70412500 | 4 m | S | 50 W | — | — | | B1 p.15 |
| 144000000 | 146000000 | 2 m | PEX | 1500 W | 50 W | 50 W | (2) sat | B1 |
| 430000000 | 433050000 | 70 cm | P | 1500 W | 50 W | 50 W | | B1 |
| 433050000 | 434790000 | 70 cm | P | **200 W** | 50 W | 50 W | (9) (D)ATV ≤ 200 W EIRP | B1 |
| 434790000 | 440000000 | 70 cm | P | 1500 W | 50 W | 50 W | (3) sat 435–438 | B1 |
| 1240000000 | 1270000000 | 23 cm | S | 200 W | — | — | (3) 1260–1270 sat, (4) Earth→space only | B1 p.15 |
| 1270000000 | 1300000000 | 23 cm | S | 200 W | — | — | (10) **(D)ATV ≤ 20 W ERP** | B1 p.15 |
| 2300000000 | 2450000000 | 13 cm | S | 200 W | — | — | (3) sat 2400–2450; (5) ISM 2400–2483.5 | B1 p.15 |
| 5650000000 | 5725000000 | 6 cm | S | 200 W | — | — | (3) 5650–5670 sat, (4) Earth→space | B1 |
| 5725000000 | 5850000000 | 6 cm | S | 200 W | — | — | (2) 5830–5850 sat; (5) ISM | B1 |
| 10000000000 | 10450000000 | 3 cm | S | 200 W | — | — | | B1 |
| 10450000000 | 10500000000 | 3 cm | S | 200 W | — | — | (2) sat | B1 |
| 24000000000 | 24050000000 | 1.2 cm | PEX | 200 W | — | — | (2), (5) | B1 |
| 24050000000 | 24250000000 | 1.2 cm | S | 200 W | — | — | | B1 |
| 47000000000 | 47200000000 | 6 mm | PEX | 200 W | — | — | (2) | B1 |
| 75500000000 | 76000000000 | 4 mm | P | 200 W | — | — | (2) | B1 |
| 76000000000 | 81000000000 | 4 mm | S | 200 W | — | — | (2) | B1 |
| 122250000000 | 123000000000 | 2.5 mm | S | 200 W | — | — | (2) | B1 |
| 142000000000 | 144000000000 | 2 mm | PEX | 200 W | — | — | (2) | B1 |
| 144000000000 | 149000000000 | 2 mm | S | 200 W | — | — | (2) | B1 |
| 241000000000 | 248000000000 | 1 mm | S | 200 W | — | — | (2) | B1 |
| 248000000000 | 250000000000 | 1 mm | PEX | 200 W | — | — | (2) | B1 |

Classes B and C: "Alle klassen van uitzending zijn toegestaan met
uitzondering van ATV of D-ATV" [all emissions except ATV/D-ATV] [B1 p.16].
Class A: "Alle klassen van uitzending zijn toegestaan" except 501–504 kHz (A1A).

**Original wording of the notes** (B1 p.17; translation in brackets):
- (1) "De stations gebruikt door radioamateurs in de frequentieband 1,81 - 1,83
  MHz mogen geen storingen veroorzaken op stations van een primaire of
  secundaire dienst en genieten geen enkele bescherming…" [no interference to
  primary or secondary services; no protection].
- (2) "De frequentiesegmenten: 7,000-7,100 / 14,000-14,250 / 18,068-18,168 /
  21,000-21,450 / 24,890-24,990 / 28,000-29,700 / 144,000-146,000 MHz /
  5830,000-5850,000 MHz / 10,450-10,500 / 24,000-24,050 / 47,000-47,200 /
  75,500-81,000 / 122,250-123,000 / 142,000-149,000 / 241,000-250,000 GHz mogen
  worden gebruikt voor communicatie tussen radioamateurs via satelliet, met
  hetzelfde statuut…" [may be used for amateur-satellite, same status].
- (3) "De communicatie tussen radioamateurs via satelliet mag geschieden in de
  banden 435,0 - 438,0 MHz, 1260,0 - 1270,0 MHz, 2400,0- 2450,0 MHz, 5650,0 -
  5670,0 MHz op voorwaarde dat daaruit geen schadelijke interferentie
  voortvloeit voor de andere diensten." [satellite allowed there provided no
  harmful interference to other services].
- (4) "… 1260,0 - 1270,0 en 5650,0 - 5670,0 MHz … is beperkt tot de richting
  aarde-ruimte." [Earth→space only].
- (5) ISM bands 2400–2483.5 MHz, 5725–5875 MHz, 24.0–24.25 GHz, 244–246 GHz:
  "Storingen veroorzaakt door die toepassingen moeten worden aanvaard."
- (6) "Maximale bandbreedte van 100 Hz". (7) "Maximale bandbreedte van 10 kHz"
  (B1). **B2 (the 2025 extract) prints "10 Hz"** — a transcription error or a
  change; the decision text (B1) says 10 kHz. Encode as 10 kHz but flag.
- (8) "Om uitzonderlijke experimenten te verrichten, kan … een tijdelijke
  vergunning worden verleend voor vermogens die hoger zijn" [temporary permits
  for higher power, for exceptional experiments].
- (9) "… 433.05 MHz – 434.79 MHz wordt het vermogen beperkt tot 200 W e.i.u.v
  in de modus (D)ATV." [(D)ATV in 433.05–434.79: 200 W EIRP].
- (10) "… 1270 MHz – 1300 MHz wordt het vermogen beperkt tot 20 W e.u.v in de
  modus (D)ATV." [(D)ATV in 1270–1300: 20 W ERP].

### 3.1 Per-band exceptions

- **60 m:** class A only, 5351.5–5366.5 kHz, **"15 W e.u.v." = 15 W ERP** in
  the decision [B1 p.15]; B2 has "15 W p.a.r." (also ERP). UBA's English page
  says "15 W EIRP" [U2, secondary] and WRC-15 RR 5.133B sets 15 W EIRP. Law =
  ERP (≈ 24.6 W EIRP [derived]). **Recommendation for code: enforce 15 W EIRP**
  (stricter, never illegal) and note it.
- **4 m:** class A only: one channel at 69.950 MHz (10 W EIRP, ≤ 10 kHz) and
  70.1125–70.4125 MHz (50 W). 70.0–70.1125 and 70.4125–70.5 MHz **not
  allowed**.
- **8 m (40.66–40.69 MHz):** class A, only with an individual yearly BIPT
  permit, 5 W ERP, listed modes [U1, secondary — primary BIPT text not found].
  Refuse unless a permit setting exists.
- **160 m:** 1810–1830 kHz must not interfere even with *secondary* services
  (note 1); class A 150 W above 1850 kHz.
- **70 cm:** class A 200 W (not 1500 W) in 433.05–434.79 MHz (the ISM/SRD
  segment); (D)ATV there ≤ 200 W EIRP.
- **23 cm:** (D)ATV above 1270 MHz ≤ 20 W ERP; whole band likely to change
  (§1 pending).
- **Class B/C:** no ATV/D-ATV anywhere.
- **Class C equipment:** may hold equipment up to 100 W but "Het gebruik en
  het houden van externe vermogensversterkers is verboden voor de houders van
  een bedieningscertificaat van klasse C" [no external amplifiers, B1 §26].
  Class A/B may hold equipment up to table power + 3 dB, but may not transmit
  above the table [B1 §§24–25].
- **Identification:** call at start and end of each transmission and at least
  every five minutes [K1 art. 17/8 §3].
- No band-plan bandwidths are law except notes (6) and (7).

### 3.2 Gaps: not permitted for any class (list explicitly)

- 5250–5351.5 and 5366.5–5450 kHz.
- 40.66–40.69 MHz without a permit; all other 30–50 MHz.
- 69.955–70.1125 MHz and 70.4125–70.5 MHz (and below 69.945 MHz).
- 146–148 MHz.
- 1300–2300 MHz; 2450–5650 MHz (**no 9 cm / 3.4 GHz**); 5850–10000 MHz;
  10.5–24 GHz; 24.25–47 GHz.
- Class B: everything except 1.81–2.0, 3.5–3.8, 7.0–7.2, 10.1–10.15, 14.0–14.35,
  18.068–18.168, 21.0–21.45, 24.89–24.99, 28.0–29.7, 50–52, 144–146, 430–440 MHz
  (**no 60 m, no 4 m, no 23 cm and up**).
- Class C: only 3.5–3.8, 7.0–7.2, 10.1–10.15, 14.0–14.35, 21.0–21.45, 28.0–29.7,
  144–146, 430–440 MHz (**no 160 m, 17 m, 12 m, 6 m**).

## 4. Satellite / QO-100

- 2300–2450 MHz: **class A only, 200 W** (reference unconfirmed — see §3),
  secondary; note (3): satellite use of 2400–2450 MHz allowed "op voorwaarde
  dat daaruit geen schadelijke interferentie voortvloeit voor de andere
  diensten"; note (5): ISM interference must be accepted [B1 pp.15, 17]. No
  extra permission. **QO-100 uplink: class A yes (200 W); B and C no.**
- 10.45–10.5 GHz: class A, satellite allowed (note 2). Reception needs nothing.
- Satellite segments also allowed by note (2) on 7.0–7.1, 14.0–14.25, 18, 21,
  24, 28 MHz and 144–146 MHz for all classes that have those bands, and 435–438
  MHz (note 3) for A, B, C.

## 5. CEPT / visiting operators

- T/R 61-01 Annex 2: "Belgium — ON — A" [CT1 p.5]; ECC/REC/(05)06 Annex 2:
  "Belgium — ON — B" [CT2 p.5]. Both use prefix **ON/**.
- UBA [U2, secondary]: T/R 61-01 visitors "can operate … using your own call
  preceded by "ON/"" for ≤ 3 months with class-A privileges; (05)06 visitors
  likewise with "ON/" (example "ON/DO1ABC") and class-B privileges; class C:
  "there is no automatic recognition of foreign ECC Report 89 licences". Note
  both CEPT classes share the same "ON/" prefix, so **the visitor's class cannot
  be inferred from the call** [derived].
- Longer stays: HAREC → Belgian class A; CEPT Novice (ERC Report 32) → class B
  [U2]. K1 art. 17/1 §3 allows certificates on the basis of a foreign exam.

## 6. Callsigns

- B4 (original): "Voor een bedieningscertificaat van klasse A kan je een prefix
  kiezen dat begint met ON1, ON4, ON5, ON6, ON7, ON8 en ON9. Voor een
  bedieningscertificaat van klasse B zal de prefix ON2 zijn. Voor een
  bedieningscertificaat van klasse C zal de prefix ON3 zijn. Bij de keuze van de
  roepnaam gaat het dus enkel om de 2 of 3 laatste letters." [class A chooses
  ON1/ON4–ON9; B is ON2; C is ON3; only the 2–3 suffix letters are chosen.]
- UBA [U2, secondary]: ON0 = repeaters, nodes, beacons; OO, OP, OQ, OR, OS, OT =
  special-event prefixes; OO–OT + one-letter suffix = vanity calls.
- Important for hints: **the privileges follow the operator's certificate, not
  the call used** — an ON2/ON3 operator using a club call (ON4…) keeps ON2/ON3
  limits [U1, secondary].
- Regex hints: A `^ON[1456789][A-Z]{2,3}$`; B `^ON2[A-Z]{2,3}$`; C
  `^ON3[A-Z]{2,3}$`; automatic `^ON0`; special/vanity `^O[O-T][0-9]`.
- Suffixes (/P, /M, /MM): not defined in K1 art. 17/8 **[UNCONFIRMED]**.

## 7. National band plan

UBA (the IARU member society) publishes no Belgian band plan of its own; its
pages point to the IARU-R1 HF plan and the IARU-R1 VHF/UHF/SHF/µW plans, with
"Be aware that not all of these frequencies may be used in Belgium" [U4]. So
the plan is **IARU-R1** ([I1], [I2]; segment tables as in the UK document),
filtered by the licence table above. Repeater practice from UBA's unmanned
stations list [U3, 2023-02-05]:

| band | outputs (TX of repeater) | input | shift sign |
|---|---|---|---|
| 10 m | RH5 29.660 | 29.560 | input 100 kHz below |
| 6 m | RF87–RF99 51.870–51.990 | 51.270–51.390 | input 600 kHz below (R1 Tel Aviv option) |
| 4 m | simplex "G" channels 70.3625, 70.3875 | — | simplex |
| 2 m | RV46–RV63 145.575–145.7875 | 144.975–145.1875 | input 600 kHz below |
| 70 cm (French system) | RU006–RU030 430.075–430.375 | 431.675–431.975 | **input 1.6 MHz ABOVE output** |
| 70 cm (7.6 MHz) | RU656–RU762 438.200–439.525 | 430.600–431.925 | input 7.6 MHz below |
| 23 cm | RM8 1297.200 | 1291.200 | input 6 MHz below |
| 23 cm | RS9–RS28 1298.225–1298.700 | 1270.225–1270.700 | input 28 MHz below |

Other observations from U3: APRS 144.800 and 432.500; packet/nodes on
144.825–144.950 and 430.4–430.85 / 438.05–438.175 (simplex); beacons on
28.207, 50.441, 70.114–70.244, 144.418, 432.450, 1296.857–1296.975,
2320.875 MHz (all inside IARU beacon segments); DATV repeaters on 1275–1294 and
2335–2380 MHz, 10.15–10.22 GHz.

IARU-R1 segments to treat as refuse/warn (all from [I2]): beacons 50.400–50.500,
70.000–70.090, 144.400–144.490, 432.400–432.490, 1296.800–1296.994 MHz;
satellite-exclusive 145.806–146.000, 435.000–438.000 MHz (and 29.300–29.510
MHz on 10 m per [I1]).

### Differences from IARU R1 (for code)

1. 70 cm: Belgium runs **both** the French F/PA/ON 1.6 MHz system (outputs
   430.0–430.4, input above) and the 7.6 MHz system (outputs 438.2–439.6, input
   below) — both endorsed by R1 footnote (f) [I2 p.43].
2. 23 cm repeaters on 1298 MHz with −28 MHz inputs (RS) as well as RM 1297/1291.
3. Licence limits narrow R1 bands: 4 m only 69.950 and 70.1125–70.4125 MHz;
   433.05–434.79 at 200 W; no 9 cm.
4. HF: R1 2020 unchanged.

## 8. Confidence and gaps

**Overall: medium-high.** Bands and numeric limits per class are from the
primary BIPT decision (B1) and its current extract (B2), checked against each
other cell by cell; the **power reference (PEP vs mean, where measured) is not
stated anywhere** found, which matters for the guard. Band plan is IARU-R1 by
reference (high), repeater conventions from the society list (medium).

UNCONFIRMED / to re-check:
- Power reference for plain "W" cells (encode as PEP at output; flag).
- 60 m: law "15 W e.u.v." (ERP) vs WRC-15/UBA EIRP — encode 15 W EIRP.
- Note (7): 10 kHz (B1) vs 10 Hz (B2).
- 8 m 40.66–40.69 MHz permit: only seen on the UBA page.
- Pending BIPT decision on 23 cm (consultation 2024; ECC Decision (25)01);
  could remove most of 1240–1300 MHz for class A and add 1296–1300 MHz for B.
- /P, /M suffix rules not found in K1.
- IARU-R1 2026 conference band-plan changes (40 m, 144.5–144.794 MHz, 23 cm)
  not yet in force [secondary].
