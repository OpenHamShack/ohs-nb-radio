# Netherlands (NL): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

Downloads 2026-10-08 with `curl -L -A <browser UA>` (HTTP 200); PDFs
converted with `pdftotext -layout`; HTML converted with a small tag-stripper
that keeps table cells. wetten.overheid.nl has no page numbers, so rows are
cited by their position in Bijlage 1.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| W1 | "Regeling gebruik van frequentieruimte met meldingsplicht 2015" (BWBR0036375), art. 4, 6, 7, 8, 10 and **Bijlage 1 "Radiozendamateurs — Beperkingen en voorschriften als bedoeld in artikel 7, onder a, en examenvereiste als bedoeld in artikel 4, tweede lid"** | "Geldend van 20-06-2024 t/m heden" (checked 2026-10-08: no later version listed) | https://wetten.overheid.nl/BWBR0036375/ | `759fa7ad689cccc5c0da71f424a20e9c12bea5f2592e2f4e8a3b46bddc59de66` (HTML) | nl |
| W2 | Stcrt. 2024, 18998 (amendment in force 20-06-2024: 50 MHz rows) — read via the official summary | 14-06-2024 | https://zoek.officielebekendmakingen.nl/stcrt-2024-18998.html | — | nl |
| W3 | Stcrt. 2023, 31710 (amendment in force 01-01-2024: N 14.0–14.35 MHz) | 20-10-2023 | https://zoek.officielebekendmakingen.nl/stcrt-2023-31710.html | — | nl |
| G1 | Agentschap Telecom (now RDI), "Vergunningen radiozendamateurs — Gedragslijn voor Agentschap Telecom bij de beoordeling van vergunningaanvragen voor het gebruik van radiozendamateurfrequenties" | dated "15-6-2021"; RDI page lists it "Richtlijn 22-06-2021"; 33 pp. | https://www.rdi.nl/site/binaries/site-content/collections/documenten/2017/04/1/gedragslijn-vergunningen-radiozendamateurs/Gedragslijn+vergunningen+radiozendamateurs+juni+2021.pdf | `a9d50eb74d30321a44af8bac827ac4b6cb78d721f29c9884437b12e354cdb094` | nl |
| R1 | RDI web page "Beschikbaarheid frequenties en geplande evenementen" | "Voor het laatst aangepast op 24 september 2026" | https://www.rdi.nl/onderwerpen/vergunningen-en-registraties/radiozendamateurs/beschikbaarheid-frequenties | `643f9f0f1aeaf31a714ebb3ae1b4224e6a6869dd94070fcdd71722d8c5afeff3` (HTML) | nl |
| R2 | RDI web page "Registreren en vergunning aanvragen radiozendamateurs" | fetched 2026-10-08 | https://www.rdi.nl/onderwerpen/vergunningen-en-registraties/radiozendamateurs/registreren-als-radiozendamateur | `72f013cfb506da0cb490997e8b75781bbf7b064a10b1bdafceaa46f9e2b7f69b` (HTML) | nl |
| CT1 | CEPT T/R 61-01 "CEPT Radio Amateur Licence" | Edition 18 Oct 2024 (Annex 2 ed. 16 Feb 2024) | https://docdb.cept.org/download/4541 (`curl -k`) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| CT2 | ECC/REC/(05)06 "CEPT Novice Radio Amateur Licence" | Edition 16 June 2023 | https://docdb.cept.org/download/4372 (`curl -k`) | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` | en |
| V1 | VERON web page "Frequentiegebruik in Nederland volgens het NFP" **[secondary; out of date — see §8]** | fetched 2026-10-08 | https://veron.nl/vereniging/radioamateur/frequentiegebruik/ | `abbe287f74105a288ddc6af7ac2188a215dba3f0c5fc2ecff14d459ebb79e9cd` | nl |
| V2 | VRZA, "cursus radiozendamateur-N, Hoofdstuk 1" (call-sign prefixes) **[secondary]** | 2025-05-01 | https://cursus.vrza.nl/files/N_HS1/N_HS1_20250501.pdf | `5ce4417b566bd4c1dc1b3e14e400568b8c3d4a3b2c061035dd5146ac9de80eb6` | nl |
| I1 | IARU Region 1 HF band plan 2020 | 2020 | https://www.darc.de/fileadmin/filemounts/referate/hf/hf_r1_bandplan.pdf | `8deb428d565ce79a173d773ff2c0226201c09f0afbb2e46ef1a68729840835cf` | en |
| I2 | IARU Region 1 VHF Handbook | v10.03, Feb 2026 | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf | `147190bd1295cd9050dd735f7d8088f9dbeb1a30c228784fb91b611428caf631` | en |

## 1. Regulator and legal instruments

- **Regulator:** Rijksinspectie Digitale Infrastructuur (RDI; formerly
  Agentschap Telecom), under the Ministry of Economic Affairs (Economische
  Zaken / EZK).
- **Law:** Telecommunicatiewet art. 3.9; Frequentiebesluit 2013 art. 3–5 (use
  without a licence but with a notification duty).
- **The instrument:** *Regeling gebruik van frequentieruimte met meldingsplicht
  2015* (W1). Amateurs do not hold a licence; they **register** (art. 5–6) and
  must have passed the N or F exam (art. 4(2)). Art. 7: use must comply with
  "de beperkingen en voorschriften ten aanzien van de beschikbare
  frequentieruimte, de toepassingen, het zendvermogen en de bekwaamheid die …
  zijn opgenomen in bijlage 1" [the limits on spectrum, applications, power
  and competence in annex 1]. **Bijlage 1 is the table to encode.**
- **Versions:** current text in force since **20-06-2024** (Stcrt. 2024,
  18998: 50–50.5 MHz became primary at 120 W, the "Alleen A1A en J3E"
  restriction dropped, 50.45 boundary moved to 50.5 [W2]). Previous change
  01-01-2024 (Stcrt. 2023, 31710) corrected N 20 m to 14.0–14.35 MHz [W3].
- The task brief mentions "Regeling gebruik van frequentieruimte zonder
  vergunning en met meldingsplicht" — the current citation title is the one
  above (W1 art. 13); "zonder vergunning en zonder meldingsplicht 2015" is a
  different regulation that does not cover amateurs.
- **Permits (vergunning):** repeaters, beacons and **higher power** need an
  individual permit (R2); policy in the Gedragslijn (G1).
- **Pending (2026-10-08):** none found in wetten.overheid.nl (no newer
  version). The 2026 RDI fee regulation (Stcrt. 2025, 35920) changes fees only.

## 2. Licence classes ("categorie registratie")

| class id | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `f` | F-registratie ("full") | RZAM-F exam (CBR) | T/R 61-01: "Netherlands — PA — F" [CT1 p.6]; W1 Bijlage 1 fn 1 equates a HAREC from another CEPT administration with the F exam | PA, PB, PC, PE, PF, PG, PH **[secondary: V2 says "PD is gereserveerd voor de N-vergunning"]** |
| `n` | N-registratie ("novice") | RZAM-N exam | ECC/REC/(05)06: "Netherlands — PD — N" [CT2 p.5]; W1 fn 1 equates (05)06 Annex 4 novice certificates with N | PD |

W1 Bijlage 1 footnote 1 (original): "Een registratie met volledige toegang
wordt aangemerkt als F (full), terwijl een registratie met beperkte toegang
wordt aangemerkt als N (novice)." [A registration with full access is F, one
with restricted access is N.] There is no third (entry) class. ("Class A" in
the task brief does not exist in the current Dutch rules **[UNCONFIRMED what
was meant; no A class found]**.)

## 3. Permitted bands and power, per class

Source: W1 Bijlage 1, the table rows in order (F rows 1–38, N rows 39–44).
Header (original): "Categorie registratie | Toegestane zendvermogen in watt
(PEP) | Frequentiebanden in MHz | Primair of secundair gebruik (p/s) |
Bijzondere bepalingen". **All figures are W PEP** except the 60 m row (EIRP).

Footnote 2 (original): "Zendvermogen: het door de direct met de
antenne-inrichting te koppelen trap van het radiozendapparaat afgegeven
gemiddeld vermogen, gerekend over één periode van de hoogfrequente
uitgangswissel-spanning tijdens het maximum van de omhullende (Peak Envelope
Power)." [Transmitter power: the mean power delivered by the stage that is
directly coupled to the antenna system, averaged over one RF cycle at the
envelope peak (PEP).] → **PEP at the transmitter/PA output.**

| lo Hz | hi Hz | band | status | f | n | notes ("Bijzondere bepalingen", translated) | W1 row |
|---|---|---|---|---|---|---|---|
| 135700 | 137800 | 2200 m | s | 400 W PEP | — | "Alleen de klasse A1A." [A1A (CW) only] | 1 |
| 472000 | 479000 | 630 m | s | 100 W PEP | — | "Alleen A1A, F1A, G1A, J2A; contesten zijn niet toegestaan." [those emissions only; no contests] | 2 |
| 1810000 | 1850000 | 160 m | p | 400 W PEP | — | | 3 |
| 1850000 | 1880000 | 160 m | s | 400 W PEP | — | | 4 |
| 3500000 | 3800000 | 80 m | p | 400 W PEP | — | | 5 |
| 5351500 | 5366500 | 60 m | s | 15 W EIRP | — | "15 watt e.i.r.p." — "Toegestane effectief uitgestraalde vermogen van de zendinrichting ten opzichte van een isotrope straler (Equivalent Isotropically Radiated Power)" | 6 |
| 7000000 | 7200000 | 40 m | p | 400 W PEP | 100 W PEP | | 7 / 39 |
| 10100000 | 10150000 | 30 m | s | 400 W PEP | — | "Contesten zijn niet toegestaan." [no contests] | 8 |
| 10140000 | 10150000 | 30 m | s | 400 W PEP | — | "Bandbreedte max 500 Hz." [overlapping row: 10.14–10.15 MHz max 500 Hz bandwidth] | 9 |
| 14000000 | 14350000 | 20 m | p | 400 W PEP | 100 W PEP | | 10 / 40 |
| 18068000 | 18168000 | 17 m | p | 400 W PEP | — | | 11 |
| 21000000 | 21450000 | 15 m | p | 400 W PEP | — | | 12 |
| 24890000 | 24990000 | 12 m | p | 400 W PEP | — | | 13 |
| 28000000 | 29700000 | 10 m | p | 400 W PEP | 100 W PEP | | 14 / 41 |
| 50000000 | 50500000 | 6 m | p | 120 W PEP | — | (since 20-06-2024) | 15 |
| 50500000 | 52000000 | 6 m | s | 30 W PEP | — | "Duplexverbindingen zijn niet toegestaan." [no duplex] | 16 |
| 70000000 | 70500000 | 4 m | s | 50 W PEP | — | "Duplexverbindingen zijn niet toegestaan." | 17 |
| 144000000 | 146000000 | 2 m | p | 400 W PEP | 25 W PEP | | 18 / 42 |
| 430000000 | 436000000 | 70 cm | p | 400 W PEP | 25 W PEP | | 19 / 43 |
| 436000000 | 440000000 | 70 cm | s | 400 W PEP | 25 W PEP | | 20 / 44 |
| 1240000000 | 1300000000 | 23 cm | s | 120 W PEP | — | | 21 |
| 2320000000 | 2400000000 | 13 cm | s | 120 W PEP | — | (temporarily unavailable during announced events — §3.1) | 22 |
| 2400000000 | 2450000000 | 13 cm | s | 120 W PEP **satellite uplink only** | — | "Uitsluitend satellietverkeer (aarde naar ruimte)." [satellite traffic only, Earth→space] | 23 |
| 3400000000 | 3410000000 | 9 cm | s | 120 W PEP | — | | 24 |
| 5650000000 | 5850000000 | 6 cm | s | 120 W PEP | — | | 25 |
| 10000000000 | 10500000000 | 3 cm | s | 120 W PEP | — | | 26 |
| 24000000000 | 24050000000 | 1.2 cm | p | 120 W PEP | — | | 27 |
| 24050000000 | 24250000000 | 1.2 cm | s | 120 W PEP | — | | 28 |
| 47000000000 | 47200000000 | 6 mm | p | 120 W PEP | — | | 29 |
| 75500000000 | 76000000000 | 4 mm | p | 120 W PEP | — | | 30 |
| 76000000000 | 77500000000 | 4 mm | s | 120 W PEP | — | | 31 |
| 77500000000 | 78000000000 | 4 mm | p | 120 W PEP | — | | 32 |
| 78000000000 | 81500000000 | 4 mm | s | 120 W PEP | — | | 33 |
| 122250000000 | 123000000000 | 2.5 mm | s | 120 W PEP | — | | 34 |
| 134000000000 | 136000000000 | 2 mm | p | 120 W PEP | — | | 35 |
| 136000000000 | 141000000000 | 2 mm | s | 120 W PEP | — | | 36 |
| 241000000000 | 248000000000 | 1 mm | s | 120 W PEP | — | | 37 |
| 248000000000 | 250000000000 | 1 mm | p | 120 W PEP | — | | 38 |

(Row numbers above count F rows then N rows as printed; the N block is
"N | 100 | 7,0–7,2 | p", "N | 100 | 14,0–14,35 | p", "N | 100 | 28,0–29,7 | p",
"N | 25 | 144,0–146,0 | p", "N | 25 | 430,0–436,0 | p", "N | 25 | 436,0–440,0 | s".)

### 3.1 Per-band exceptions

- **60 m:** F only, the WRC-15 band 5351.5–5366.5 kHz, 15 W EIRP (row 6). No
  bandwidth set.
- **30 m:** no contests (whole band); 10.140–10.150 MHz ≤ 500 Hz bandwidth
  (rows 8–9). (10.100–10.140 has no bandwidth limit in law.)
- **160 m:** only 1810–1880 kHz; 1880–2000 kHz not allocated.
- **LF/MF:** 2200 m CW (A1A) only at 400 W PEP (row 1 — unusually high, but as
  printed); 630 m 100 W PEP, listed emissions only, no contests.
- **6 m:** 50.0–50.5 MHz 120 W PEP primary; 50.5–52.0 30 W PEP secondary, no
  duplex (rows 15–16). The VERON page (V1) still shows the pre-2024 rows
  (50.0–50.45, "Alleen A1A en J3E") — ignore it.
- **4 m:** 70.0–70.5 MHz, F only, 50 W PEP, no duplex (row 17). No 4 m for N.
- **13 cm:** 2320–2400 MHz terrestrial; **2400–2450 MHz Earth→space satellite
  only** — no terrestrial use (no 2.4 GHz ATV/FM/narrowband terrestrial).
  2300–2320 MHz not allocated.
- **Event closures:** RDI publishes periods when amateurs "kunt geen gebruik
  maken van de volgende frequentie(s)", e.g. "Nederland-Duitsland, JC Arena te
  Amsterdam | 22 september 2026 … t/m 25 september 2026 … | 2320-2400 MHz" and
  "Military Boekelo | 28 september 2026 … t/m 7 oktober 2026 | 2355 MHz" [R1].
  These are time-limited and change; the guard cannot know them — UI note.
- **Higher power by permit:** F holders can apply for up to +6 dB (i.e. 1600 W
  on 400 W bands) **only in primary bands**, per location: "De verhoging mag
  maximaal +6dB bedragen ten opzichte van het onder de registratievoorwaarden
  toegestane vermogen in de betreffende band" and "Zenden met een hoger vermogen
  kan alleen worden toegestaan in de frequentiebanden waar het gebruik door
  radiozendamateurs een primaire status heeft" [G1 ch. VI]. Treat like the UK
  NoV: not encoded unless a setting is added.
- **Operation:** art. 10(1): the amateur operates the station himself and only
  he may remote-control it; call sign at start and end of each transmission
  and at least every five minutes; no encryption; only contacts with other
  amateur stations [W1 art. 10].
- **Self-built equipment:** footnote 3 sets spurious limits (e.g. −36 dBm or
  −60 dBc 50–1000 MHz; −30 dBm or −50 dBc 1–40 GHz) [W1 Bijlage 1 Tabel 1].
- Fixed antennas must be entered in the Antenneregister (R2).

### 3.2 Gaps: not permitted for any class (list explicitly)

- 1880–2000 kHz.
- 5250–5351.5 and 5366.5–5450 kHz.
- 146–148 MHz (Region 2 only).
- 1300–2320 MHz (incl. 2300–2320).
- **2400–2450 MHz for any terrestrial use** (satellite uplink only, F).
- 2450–3400 MHz; 3410–5650 MHz (9 cm is only 3400–3410); 5850–10000 MHz;
  10.5–24 GHz.
- N class: everything except 7.0–7.2, 14.0–14.35, 28.0–29.7, 144–146, 430–440 MHz.
  N has **no 160/80/60/30/17/15/12 m, no 6 m, no 4 m, no 23 cm or above**.

## 4. Satellite / QO-100

- Row 23: "F | 120 | 2.400,0 – 2.450,0 | s | Uitsluitend satellietverkeer
  (aarde naar ruimte)." → **F: QO-100 uplink permitted, 120 W PEP
  (transmitter output), no extra permission.** N: not permitted.
- The registration itself is the permission; nothing further needed.
- 10.0–10.5 GHz: F 120 W PEP secondary (row 26); 10.45–10.5 GHz has no
  separate satellite note in W1 [derived: downlink reception needs nothing].
- No other satellite sub-band is fixed in law; IARU-R1 satellite segments
  (145.806–146.000, 435–438 MHz) are band-plan only.
- AMSAT-DL NB plan (uplink 2400.005–2400.490 MHz, "keep your signal below
  Beacon level") applies as practice [secondary; see de.md A1].

## 5. CEPT / visiting operators

- T/R 61-01 Annex 2: "Netherlands — PA — F 13", footnote 13: "New licences will
  be granted as Full licence in line with CEPT (with or without the remark Morse
  code included)." [CT1 p.6]. A CEPT visitor transmits as **PA/<home call>**
  with F privileges [derived from CT1 + W1 fn 1].
- ECC/REC/(05)06 Annex 2: "Netherlands — PD — N" [CT2 p.5]. A CEPT-Novice
  visitor transmits as **PD/<home call>** with N privileges. (05)06 also lists
  the Dutch Caribbean (PJ2/4/5/6/7, Region 2) with their own bands.
- W1 Bijlage 1 fn 1 (original): "Met het met goed gevolg afgelegd hebben van
  een examen voor de categorie F wordt gelijk gesteld een HAREC-certificaat,
  verstrekt door een andere administratie van de … (CEPT) … Met het met goed
  gevolg afgelegd hebben van een examen wordt voor de categorie N gelijk
  gesteld een certificaat … dat gelijkwaardig is aan een N-certificaat …
  opgenomen in Annex 4 van ECC Recommendation (05) 06." [A foreign HAREC
  counts as the F exam; an equivalent novice certificate counts as N.]
- Dutch N holders abroad: (05)06 countries only. F holders: T/R 61-01.

## 6. Callsigns

- Allocated at registration ("combinatie van letters of cijfers", W1 art. 6(3));
  callbook at https://callbook.rdi.nl/ (R2).
- **Prefix by class [secondary, V2]:** "In Nederland beginnen calls met PA t/m
  PI, gevolgd door een cijfer en daarna minstens één letter. PD is gereserveerd
  voor de N-vergunning. PI is voor …" (clubs/repeaters). F holders: PA, PB, PC,
  PE, PF, PG, PH. No primary RDI rule document found **[UNCONFIRMED]**.
- Regex hints: N `^PD[0-9][A-Z]{1,3}$`; F `^P[ABCEFGH][0-9][A-Z]{1,3}$`;
  club/repeater/beacon `^PI[0-9]`. Digit 6 after PA–PH is reported to mark
  special-event calls [secondary].
- Suffixes: W1 does not regulate /P, /M, /MM [UNCONFIRMED]; it requires the
  call at start, end and every 5 minutes (art. 10(1)(c)), readable in data/image
  modes (d), and the spelling alphabet of Bijlage 3 (h). Group stations in
  Scouting events add "J" (art. 10(2)(c)).

## 7. National band plan

The Netherlands has **no national amateur band plan document of its own that
we could find**; VERON (the IARU member society) and VRZA follow the IARU-R1
plans [UNCONFIRMED that VERON publishes nothing separate]. The regulator's
Gedragslijn (G1) contains the **national repeater and beacon plan** used to
license unattended stations; it is the authoritative source for where Dutch
repeaters and beacons are.

### HF and 6/4 m
IARU-R1 HF plan 2020 [I1]; 6 m and 4 m per IARU-R1 [I2 pp.35–37]. Law adds:
no 160 m above 1880 kHz; 30 m 500 Hz above 10.140 MHz.

### Beacons (G1 Bijlage III "Bandplan bakens") — refuse transmit here

| range MHz | band |
|---|---|
| 28.225–28.300 | 10 m |
| 50.000–50.100 (* SBP only) | 6 m |
| 50.400–50.500 (** coordinated only) | 6 m |
| 70.000–70.090 (**), 70.090–70.100 | 4 m |
| 144.400–144.490 | 2 m |
| 432.400–432.490 | 70 cm |
| 1296.800–1296.994 | 23 cm |
| 2320.800–2321.000 | 13 cm |
| 3400.800–3400.995 | 9 cm |
| 5760.800–5760.990 | 6 cm |
| 10368.800–10368.990 | 3 cm |
| 24048.800–24048.995 | 1.5 cm |
| 47088.800–47089.000 | 6 mm |
| 77500.800–77501.000 | 4 mm |

Note: "50.000 – 50.100 MHz wordt uitsluitend gebruikt voor het IARU
Synchronized Beacon Project" — note 50.000–50.100 is wider than IARU's
50.000–50.030 SBP range and covers the IARU CW segment; treat as "beacons
present", warn rather than refuse below 50.030 is **[derived — decision for
code]**.

### 2 m (G1 Bijlage I + II; IARU-R1 otherwise)

| range MHz | use (G1) | shift |
|---|---|---|
| 144.79375–144.80625 | APRS, centre 144.800 | — |
| 144.80625–144.96875 | "Relaisstations" (simplex digital nodes 144.8125–144.9625, 12.5 kHz) | — |
| 145.56875–145.59375 | "Bovenregionale relaisstations" outputs 145.575 / 145.5875 (inputs 144.975 / 144.9875) | −600 kHz |
| 145.59375–145.79375 | repeater **outputs** 145.6000–145.7875 (inputs 145.0000–145.1875) | **input 600 kHz below output** |

IARU-R1 [I2 p.38] otherwise: 144.000–144.025 satellite downlink; CW
144.025–144.150; SSB centre 144.300; beacons 144.400–144.490; FM simplex
145.206–145.5625 (145.500 calling, 145.375 DV calling); **satellite
145.806–146.000**.

### 70 cm (G1 Bijlage I + II)

| range MHz | use | pairing |
|---|---|---|
| 430.000–430.38125 | repeater **outputs** 430.0125–430.3750 (12.5 kHz; "bovenregionaal" 430.125, 430.275) | **input = output + 1.6 MHz** (431.6125–431.9750) — the "French" F/PA/ON system |
| 430.50625–430.51875 | old APRS 430.5125 (no new permits after 1-4-2017) | — |
| 430.59375–431.03125 | repeater channels 430.600–431.025 (no pairing given; simplex/digital nodes) | — |
| 431.0375–431.2125 | repeaters 431.050–431.200, cross-band to 1297.800–1297.950 | cross-band |
| 432.49375–432.50625 | APRS, centre 432.500 | — |
| 437.99375–438.5125 | repeater **outputs** 438.000–438.500 (inputs 430.400–430.900) | **input 7.6 MHz below output**; status secondary (436–440) |

IARU-R1 [I2 pp.41–42]: CW 432.000–432.100; SSB centre 432.200; **beacons
432.400–432.490**; FM calling 433.500, DV calling 433.450; **satellites
435.000–438.000**. Note the Dutch 438.0–438.5 repeater outputs overlap R1's
435–438 satellite segment edge only at 438.000 [derived].

### 23 cm (G1 Bijlage I + II)

Repeater/transmit frequencies: 1240.000–1241.000 links (shift 59 MHz);
1241.075–1241.825 (shift 54 MHz, pairs with 1295.075–1295.825); 1241.9125–
1242.1875; 1242.700–1243.000 (shift 28 MHz, pairs 1270.725–1270.975);
1243.250–1260.000 and 1272.000–1290.994 ATV (shift ±30–45 MHz); 1295.000–
1295.830 (−54 MHz); 1296.600–1296.800 linear transponder (input 1296.400–
1296.600); 1297.7375–1297.9625; **1297.9625–1298.7125 and 1298.725–1299.000
outputs with input 28 MHz below** (1270.000–1271.000); 1299–1300 links (−59 MHz).
G1 warns the 23 cm band may be restricted later because of Galileo (RNSS).
IARU-R1 [I2 p.45]: beacons 1296.800–1296.994, narrowband centre 1296.200,
satellite 1260–1270.

### Differences from IARU R1 (for code)

1. 70 cm uses **both** the French 1.6 MHz system (outputs 430.0125–430.375,
   inputs +1.6) **and** 7.6 MHz pairs with outputs at 438.0–438.5 (input
   below) — R1 footnote (f) endorses both [I2 p.43].
2. 23 cm repeaters on 1298 MHz output with −28 MHz input (1270), not R1's
   1291/1297 RM system.
3. 6 m beacon reservation 50.000–50.100 (SBP) is wider than R1's 50.000–50.030.
4. Law restricts 2400–2450 MHz to satellite uplink and 160 m to 1880 kHz.
5. 2 m APRS 144.800 and digital nodes 144.8125–144.9625 as R1.

## 8. Confidence and gaps

**Overall: high** for the licence table (single primary, current consolidated
regulation; rows read directly); **medium** for band plan (no VERON national
plan document found; repeater plan from the regulator's 2021 Gedragslijn) and
call signs (secondary only).

UNCONFIRMED / to re-check:
- Call-sign prefix allocation per class (PD = N) — secondary sources only.
- Use of /P, /M suffixes — not in W1.
- Whether VERON publishes a national band plan distinct from IARU-R1.
- 2200 m 400 W PEP is as printed in W1 — looks high but is the law text.
- "Class A" named in the brief: no such Dutch class exists in W1.
- VERON's own frequency table (V1) is stale (pre-2024 6 m rows, N 20 m to
  14.25) — do not use it.
- Pending: IARU-R1 General Conference Sept 2026 adopted band-plan changes
  (40 m wideband digital, 144.5–144.794 MHz bandwidth, new 23 cm plan) with no
  effective dates yet [secondary: VERON news 19-09-2026] — affects all R1
  countries.
