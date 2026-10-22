# Germany (DE): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

All PDFs below were downloaded on 2026-10-08 with `curl -L -A <browser UA>`
(HTTP 200) and converted with `pdftotext -layout`; the band-plan charts were
also rendered to PNG with `pdftoppm` and read as images, because their
two-column layout does not survive text extraction.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| D1 | "Verordnung zum Gesetz über den Amateurfunk (Amateurfunkverordnung - AFuV)", consolidated text incl. **Anlage 1** "Nutzungsbedingungen für die im Frequenzplan für den Amateurfunkdienst und den Amateurfunkdienst über Satelliten ausgewiesenen Frequenzbereiche" | Printed: "Stand: Zuletzt geändert durch Art. 1 V v. 27.5.2024 I Nr. 175". Anlage 1 "(Fundstelle: BGBl. 2024 I Nr. 175, S. 1 – 4)". PDF CreationDate 30 May 2025. 12 pages. | https://www.gesetze-im-internet.de/afuv_2005/AFuV.pdf (index https://www.gesetze-im-internet.de/afuv_2005/) | `a384594c4ec77915aa9e354fa13b8d650eaf58148ad1a98d22d7496ec28d6f9d` | de |
| D2 | "Rufzeichenplan für den Amateurfunkdienst in Deutschland" — "Auszug aus der Verfügung Nr. 15 / 2025 (Amtsblatt 05 / 2025 vom 05.03.2025)" | valid from 01.04.2025; replaces Vfg 61/2024 | https://www.bundesnetzagentur.de/DE/Fachthemen/Telekommunikation/Frequenzen/SpezielleAnwendungen/Amateurfunk/DL_Vfg_AFu/Rufzeichenplan_10_24_Auszug_aus_Vfg_15_2025.pdf?__blob=publicationFile&v=4 | `55a9e8ecb6ddcbe94d487b37fff98a56d76883de88f7c8526f9d1c7e96af2ce1` | de |
| D3 | Bundesnetzagentur web page "Amateurfunk" (CEPT/Novice recognition, class description) | fetched 2026-10-08 (page lists exam dates "Stand 7. Oktober 2026") | https://www.bundesnetzagentur.de/DE/Fachthemen/Telekommunikation/Frequenzen/SpezielleAnwendungen/Amateurfunk/start.html | `2957b809eff904e805e64104d58b1b729a6c2906d27c396238588aae6941254a` (HTML, changes with each fetch) | de |
| D4 | "Verordnung über das Nachweisverfahren zur Begrenzung elektromagnetischer Felder (BEMFV)", § 9 | current consolidated text, fetched 2026-10-08 | https://www.gesetze-im-internet.de/bemfv/__9.html | not recorded (HTML) | de |
| D5 | buzer.de AFuV change history **[secondary]** | fetched 2026-10-08 | https://www.buzer.de/AFuV.htm | — | de |
| D6 | DARC news "Keine Duldungsregelung 2026 für Klasse E auf 6 m; Unklarheiten bei 70 MHz" **[secondary]** (society, reporting BNetzA) | 22.12.2025 | https://www.darc.de/nachrichten/meldungen/aktuelles-details/news/keine-duldungsregelung-2026-fuer-klasse-e-auf-6-m-unklarheiten-bei-70-mhz/ | — | de |
| D7 | DARC news "Aktueller Status zur Duldung 70 MHz" **[secondary]** | 13.03.2026 | https://www.darc.de/nachrichten/meldungen/aktuelles-details/news/aktueller-status-zur-duldung-70-mhz | — | de |
| D8 | DARC news "Positive Entwicklung bei 70 MHz!" (on Bundesrat-Drucksache 364/26, 5. VO zur Änderung der Frequenzverordnung) **[secondary]** | 23.06.2026 | https://www.darc.de/nachrichten/meldungen/aktuelles-details/news/positive-entwicklung-bei-70-mhz | — | de |
| D9 | DARC news "50 MHz in der Klasse E ab 2025 wieder befristet erlaubt. 70 MHz Duldung für Klasse A verlängert." (reports BNetzA Amtsblatt 24/2024, 18.12.2024) **[secondary]** | Dec 2024 | https://www.darc.de/der-club/distrikte/g/distrikts-news/news/50-mhz-in-der-klasse-e-ab-2025-wieder-befristet-erlaubt-70-mhz-duldung-fuer-klasse-a-verlaengert-1/ | — | de |
| B6 | DARC VHF/UHF/SHF-Referat, "Bandplan 6m, 50 MHz" | "Bandplan: Stand 04/2026", © 04.04.2026 | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/VHF_Bandplan_6_m_April_2026.pdf | `4af281593d0f366293ca03ba732b51b388ce75e1fa66e8c50c059f36ffb08851` | de |
| B2 | DARC, "Bandplan 2m, 144 - 146 MHz" | "Bandplan: Stand 08/2017", © 13.08.2017 | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/VHF_Bandplan_2_m_August_2017.pdf | `aa52a8d58aa7e845be4359c2bbbd14428ba0d08ba6a7bd29eba7d20d52c59ac0` | de |
| B70 | DARC, "Bandplan 70cm, 430 - 440 MHz" (p.1 general, "Stand 08/2017", © 15.08.2017; p.2 "(automatische Stationen)", "Stand 05/2025", © 07.05.2025) | 2 pages | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/UHF_Bandplan_70_cm_Mai_2025.pdf | `cf27544270a9bcc7c6dd99695fd76112697fdcfb69fdfbd898f8332db5d98a60` | de |
| B23 | DARC, "Bandplan 23cm, 1240 - 1300 MHz" | "Bandplan: Stand 11/2011", © 28.11.2011 | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/UHF_Bandplan_23_cm.pdf | `ea13943b8f88ae808080d7362d7484d9fe3aa544fb95f09be7ba12fd76a2aa36` | de |
| B13 | DARC, "Bandplan 13cm, 2320 - 2450 MHz" | "Bandplan: Stand 06/2015", © 30.11.2011 | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/UHF_Bandplan_13_cm_Juni_2015.pdf | `ec49b1874e6092b5c90a9639a3c32b887f2ecd2ed44e3b85ac00aafb7fc6b3dd` | de |
| B3 | DARC, "Bandplan 3cm, 10.0 – 10.5 GHz" | "Bandplan: Stand 12/2013" | https://www.darc.de/fileadmin/filemounts/referate/vus/bandplaene/SHF_Bandplan_10_GHz_Dezember_2013.pdf | `60372b5590e98930d7130143f04c8c0c921719d6fd5696773246eaf00bb30820` | de |
| BHF | DARC HF-Referat (Tom Kamp DF5JL), "Vereinfachter Kurzwellen-Bandplan für DL unter Berücksichtigung der AFuV und des IARU-Region 1-Bandplans" | "Stand: Dez. 2025", v2.01; PDF created 30 Dec 2025 | https://www.darc.de/fileadmin/filemounts/referate/hf/Dokumente/Bandplan_DL_vereinfacht_v2.01.pdf | `8b405eb47e05a93c24076f2417c17aca693c1ecf01214300e78837b656cd508c` | de |
| I1 | IARU Region 1 HF band plan (DARC-hosted copy; DARC page says "gültig ab 16. Oktober 2020") | 2020 | https://www.darc.de/fileadmin/filemounts/referate/hf/hf_r1_bandplan.pdf | `8deb428d565ce79a173d773ff2c0226201c09f0afbb2e46ef1a68729840835cf` | en |
| I2 | IARU Region 1 VHF Handbook | v10.03, PDF created 17 Feb 2026, 133 pages | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf | `147190bd1295cd9050dd735f7d8088f9dbeb1a30c228784fb91b611428caf631` | en |
| A1 | AMSAT-DL, "QO-100 NB Transponder Bandplan and Operating Guidelines" **[secondary]** for licence purposes | page dated 19.10.2018 (plan revised Dec 2020) | https://amsat-dl.org/en/p4-a-nb-transponder-bandplan-and-operating-guidelines | — | en |
| CT1 | CEPT, Recommendation T/R 61-01 "CEPT Radio Amateur Licence" (Annex 2 table of equivalence) | "Edition of 18 October 2024" (Annex 2 "Edition of 16 February 2024"); PDF created 29 Oct 2024; 13 pp. | https://docdb.cept.org/download/4541 (fetched with `curl -k`: the site's TLS chain does not verify) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| CT2 | CEPT, ECC/REC/(05)06 "CEPT Novice Radio Amateur Licence" (Annex 2) | "Edition 16 June 2023"; 10 pp. | https://docdb.cept.org/download/4372 (`curl -k`) | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` | en |

## 1. Regulator and legal instruments

- **Regulator:** Bundesnetzagentur für Elektrizität, Gas, Telekommunikation,
  Post und Eisenbahnen (BNetzA). Ministry: Bundesministerium für Digitales
  und Verkehr.
- **Law:** Gesetz über den Amateurfunk (Amateurfunkgesetz – AFuG) of
  23 June 1997.
- **Ordinance:** Amateurfunkverordnung (AFuV) of 15 Feb 2005 (BGBl. I S. 242),
  "zuletzt durch Artikel 1 der Verordnung vom 27. Mai 2024 (BGBl. 2024 I
  Nr. 175) geändert" [D1 p.1]. That is the *Dritte Verordnung zur Änderung der
  Amateurfunkverordnung*, which replaced Anlage 1 in full. It and the
  *Zweite Verordnung zur Änderung der AFuV* of 21 June 2023 (BGBl. 2023 I
  Nr. 160, which introduced class N) both took effect on **24 June 2024**
  [D5 **[secondary]**; D3 confirms "Seit dem 24. Juni 2024 gibt es eine neue
  Klasse N"].
- **The power/band table is AFuV Anlage 1**, Part A ("Tabellarische
  Übersicht") and Part B ("Zusätzliche Nutzungsbestimmungen") [D1 pp.9–12].
  § 9(2): the licence entitles use of the Anlage 1 ranges "nach Maßgabe der in
  seiner Zulassung festgelegten Zeugnisklasse" [D1 p.4].
- **EMF:** BEMFV § 9(1): a fixed amateur station with "einer äquivalenten
  isotropen Strahlungsleistung (EIRP) von 10 Watt oder mehr" must be notified
  to BNetzA before use [D4]. Not a band limit; worth a UI note.
- **Call-sign plan:** BNetzA Vfg 15/2025, valid from 01.04.2025 [D2].
- **Pending / changed since 2024 (as of 2026-10-08):**
  - The class-E **50 MHz** "Duldung" (temporary toleration, 50.000–50.400 MHz
    100 W PEP, 50.4–52 MHz 25 W PEP, 12 kHz, horizontal, fixed stations,
    valid 1.1.–31.12.2025 [D9]) was **not renewed**: "Ab dem 1.1.2026 dürfen die
    betroffenen Funkamateure auf 50 MHz nicht mehr senden" [D6]. Class E has
    no 6 m from 2026.
  - The class-A **70 MHz** toleration (70.150–70.210 MHz, 25 W ERP, horizontal
    [secondary, D9 and search results]) expired 31.12.2025 and was **not
    renewed**: "Für das Jahr 2026 gibt es weiterhin keine Duldungsregelung, die
    den Sendebetrieb auf 70 MHz erlaubt" [D7, 13.03.2026]. A draft 5th
    amendment of the Frequenzverordnung (Bundesrat-Drucksache 364/26) carries
    a footnote "Der Frequenzbereich 70 - 70,5 MHz können für Aussendungen durch
    den Amateurfunkdienst genutzt werden" [D8, 23.06.2026], but BNetzA still has
    to set usage conditions. **Status at 2026-10-08: no 70 MHz for any class
    [UNCONFIRMED whether BNetzA acted between July and October 2026; nothing
    found].** Re-check before release.
  - The 160 m weekend and 13/6 cm class-E HAMNET tolerations of earlier years
    are now inside Anlage 1 itself (B 15; E rows 22–29), so nothing pending there.

## 2. Licence classes

| class id | national name | exam level | CEPT equivalence | callsign prefixes (personal, D2) |
|---|---|---|---|---|
| `a` | Amateurfunkzeugnis Klasse A | full (§ 4(1)) | T/R 61-01 CEPT licence / T/R 61-02 HAREC. D3: "Klasse A … (Harmonised Amateur Radio Examination Certificate / HAREC)"; CEPT visitors get "die Betriebsrechte der deutschen Klasse A" | DA1, DA2, DB1–9, DC0–9, DD0–9, DF1–9, DG0–9, DH0–9, DJ0–9, DK1–9, DL1–9, DM1–9 (DN1–DN6 = old training calls, expiring) |
| `e` | Klasse E | "Grundzüge" of technical knowledge (§ 4(2)) | ECC Rec (05)06 CEPT Novice. D3: "Klasse E ( Novice )"; (05)06 visitors get "die Betriebsrechte der deutschen Klasse E" | DA6, DO1–DO9 (DN7–DN8 old training calls, expiring) |
| `n` | Klasse N (since 24.06.2024) | "wesentlichen Grundzüge" (§ 4(3)); D3 calls it "Entry-Class" | **none** (no CEPT instrument covers it; D3 lists only A↔T/R 61-01 and E↔(05)06) [derived from D3's silence: no CEPT operation abroad] | DN9 |

§ 19(1) [D1 p.8]: old class 3 = E; all other old classes = A.

## 3. Permitted bands and power, per class

Source for every row: D1 Anlage 1 A (row number "lfd. Nr." given), on
**p.9** (row 1), **p.10** (rows 2–37), **p.11** (rows 38–45, footnotes, B 1–9),
**p.12** (B 10–17). "PEP" is defined in § 2 Nr. 7 as transmitter peak envelope
power into a resistive load ("an einen reellen Abschlusswiderstand abgeben
kann") — i.e. transmitter output; "ERP" § 2 Nr. 8 is relative to a half-wave
dipole [D1 p.2]. Classes A and E are almost entirely **W PEP (transmitter
output)**; class N is entirely **W ERP**; LF/MF and 60 m are ERP for class A.

| lo Hz | hi Hz | band | status | a | e | n | notes (B = Anlage 1 Teil B) | source |
|---|---|---|---|---|---|---|---|---|
| 135700 | 137800 | 2200 m | S | 1 W ERP | — | — | B1 800 Hz max; B2 site notification, stop if interfering; B10 no remote stations except § 13a remote, no contests | D1 row 1, p.9 |
| 472000 | 479000 | 630 m | S | 1 W ERP | — | — | B1 800 Hz | row 2, p.10 |
| 1810000 | 1850000 | 160 m | P | 750 W PEP | 100 W PEP | — | B3 2.7 kHz | row 3 |
| 1850000 | 1890000 | 160 m | S | 75 W PEP | 75 W PEP | — | B3, B10, B12 (auto stations 50 W ERP), **B15 weekends: A 750 W PEP, E 100 W PEP, contests allowed** | row 4 |
| 1890000 | 2000000 | 160 m | S | 10 W PEP | 10 W PEP | — | B3, B10, **B15 weekends as above** | row 5 |
| 3500000 | 3800000 | 80 m | P | 750 W PEP | 100 W PEP | — | B3 | row 6 |
| 5351500 | 5366500 | 60 m | S | 9,14 W ERP | — | — | B3 2.7 kHz. 9.14 W ERP = 15 W EIRP [derived: ×1.64] | row 7 |
| 7000000 | 7200000 | 40 m | P | 750 W PEP | — | — | B3; B13 7000–7100 also amateur-sat (primary) | row 8 |
| 10100000 | 10150000 | 30 m | S | 150 W PEP | — | — | **B1 800 Hz max**; B10; B12 | row 9 |
| 14000000 | 14350000 | 20 m | P | 750 W PEP | — | — | B3; B13 14000–14250 also sat | row 10 |
| 18068000 | 18168000 | 17 m | P | 750 W PEP | — | — | B3; B13 sat | row 11 |
| 21000000 | 21450000 | 15 m | P | 750 W PEP | 100 W PEP | — | B3; B13 sat | row 12 |
| 24890000 | 24990000 | 12 m | P | 750 W PEP | — | — | B3; B13 sat | row 13 |
| 28000000 | 29700000 | 10 m | P | 750 W PEP | 100 W PEP | 10 W ERP | **B4 7 kHz below 29 MHz, 40 kHz above**; B13 sat | row 14 |
| 50000000 | 50400000 | 6 m | S | 750 W PEP | — | — | B5 (below); B16 12 kHz | row 15 |
| 50400000 | 52000000 | 6 m | S | 25 W PEP | — | — | B5; B16 12 kHz | row 16 |
| 144000000 | 146000000 | 2 m | P | 750 W PEP | 75 W PEP | 6,1 W ERP | B6 40 kHz; B13 sat (primary). 6.1 W ERP = 10 W EIRP [derived] | row 17 |
| 430000000 | 440000000 | 70 cm | P | 750 W PEP | 75 W PEP | 6,1 W ERP | B7 2 MHz (AM-TV 7 MHz); B13 435–438 sat (secondary) | row 18 |
| 1240000000 | 1250000000 | 23 cm | S | 750 W PEP | 75 W PEP | — | B8; **B11 1247–1263 MHz 3,05 W ERP**; B17 | row 19 |
| 1250000000 | 1260000000 | 23 cm | S | 750 W PEP | 75 W PEP | — | B8, B11, B17 | row 20 |
| 1260000000 | 1300000000 | 23 cm | S | 750 W PEP | 75 W PEP | — | B8, B11 (to 1263), B13 (1260–1270 sat **Earth→space only**), B17 | row 21 |
| 2320000000 | 2400000000 | 13 cm | S | 75 W PEP | 5 W PEP | — | B9 10 MHz (TV 20 MHz); B17 | row 22 |
| 2400000000 | 2450000000 | 13 cm | S | 75 W PEP | 5 W PEP | — | B9; B13 sat (secondary; other secondary services have priority); B17 | row 23 |
| 3400000000 | 3475000000 | 9 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 24 |
| 5650000000 | 5670000000 | 6 cm | S | 75 W PEP | 5 W PEP | — | B9; B13 sat Earth→space only; B17 | row 25 |
| 5670000000 | 5725000000 | 6 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 26 |
| 5725000000 | 5755000000 | 6 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 27 |
| 5755000000 | 5830000000 | 6 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 28 |
| 5830000000 | 5850000000 | 6 cm | S | 75 W PEP | 5 W PEP | — | B9, B17; B13 sat space→Earth only | row 29 |
| 10000000000 | 10400000000 | 3 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 30 |
| 10400000000 | 10450000000 | 3 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 31 |
| 10450000000 | 10500000000 | 3 cm | S | 75 W PEP | 5 W PEP | — | B9; B13 sat (secondary); B17 | row 32 |
| 24000000000 | 24050000000 | 1.2 cm | P | 75 W PEP | 5 W PEP | — | B13 (sat primary), B17; no bandwidth note | row 33 |
| 24050000000 | 24250000000 | 1.2 cm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 34 |
| 47000000000 | 47200000000 | 6 mm | P | 75 W PEP | 5 W PEP | — | B13, B17 | row 35 |
| 76000000000 | 77500000000 | 4 mm | S | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 36 |
| 77500000000 | 78000000000 | 4 mm | S | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 37 |
| 78000000000 | 79000000000 | 4 mm | S | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 38, p.11 |
| 79000000000 | 81000000000 | 4 mm | S | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 39 |
| 122250000000 | 123000000000 | 2.5 mm | S | 75 W PEP | 5 W PEP | — | B9, B17 | row 40 |
| 134000000000 | 136000000000 | 2 mm | P | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 41 |
| 136000000000 | 141000000000 | 2 mm | S | 75 W PEP | 5 W PEP | — | B9, B13, B17 | row 42 |
| 241000000000 | 248000000000 | 1 mm | S | 75 W PEP | 5 W PEP | — | B13, B17 | row 43 |
| 248000000000 | 250000000000 | 1 mm | P | 75 W PEP | 5 W PEP | — | B13, B17 | row 44 |
| > 275 GHz | | | – | – | – | – | B14: 444–453, 510–546, 711–730, 909–926, 945–951 GHz and > 956 GHz usable, no protection, conditions set by BNetzA | row 45 |

Status column (footnote 1, p.11): "P: Amateurfunkdienst ist primärer
Funkdienst, S: Amateurfunkdienst ist sekundärer Funkdienst … Die mit „P"
gekennzeichneten Frequenzbereiche können gleichzeitig auch anderen primären
Funkdiensten zugewiesen sein."

**Original wording of the limits** (D1 pp.9–12, translation in brackets):

- Table header: "Zulässige Frequenzbereiche und maximale Leistung für Inhaber
  einer Zulassung zum Amateurfunkdienst mit Berechtigungsumfang der Klasse A /
  Klasse E / Klasse N" [permitted ranges and maximum power for holders of an
  amateur licence with the privileges of class A / E / N]. Cells verbatim:
  "1 W ERP", "750 W PEP", "100 W PEP", "75 W PEP", "10 W PEP", "9,14 W ERP",
  "150 W PEP", "25 W PEP", "10 W ERP", "6,1 W ERP", "5 W PEP". An empty cell
  means not permitted.
- Footnote 2: "PEP: Spitzenleistung (§ 2 Nr. 7); ERP: effektive
  Strahlungsleistung (§ 2 Nr. 8)".
- § 2 Nr. 7: "„Spitzenleistung (PEP)" die Leistung, die der Sender unter
  normalen Betriebsbedingungen während einer Periode der Hochfrequenzschwingung
  bei der höchsten Spitze der Modulationshüllkurve durchschnittlich an einen
  reellen Abschlusswiderstand abgeben kann" [the power the transmitter can
  deliver on average into a resistive load during one RF cycle at the highest
  crest of the modulation envelope].
- B1: "Maximal zulässige belegte Bandbreite einer Amateurfunk-Aussendung:
  800 Hz." [max occupied bandwidth 800 Hz]. B3: "… 2,7 kHz." B4: "… unterhalb
  29 MHz: 7 kHz, oberhalb 29 MHz: 40 kHz." B6: "… 40 kHz." B7: "… 2 MHz; bei
  amplitudenmodulierten Fernsehaussendungen: 7 MHz." B8: "… 2 MHz; bei
  amplitudenmodulierten oder digitalen Fernsehaussendungen: 7 MHz und bei
  frequenzmodulierten Fernsehaussendungen: 18 MHz." B9: "… 10 MHz; bei
  Fernsehaussendungen: 20 MHz." B16: "… 12 kHz."
- B5: "Amateurfunk-Aussendungen dürfen weder schädliche Störungen beim
  Rundfunkempfang verursachen noch Schutz vor Aussendungen des Rundfunkdienstes
  beanspruchen. Amateurfunk-Aussendungen im Frequenzband 50 – 52 MHz dürfen
  keine funktechnischen Störungen an Windprofilmessradaren verursachen. … Es
  sind ausschließlich Aussendungen mit horizontaler Polarisation zulässig. Die
  Nutzung ist auf ortsfeste Amateurfunkstellen beschränkt." [no harmful
  interference to broadcast reception, no protection; no interference to wind
  profiler radars; **horizontal polarisation only; fixed stations only**.]
- B10: "Der Betrieb von fernbedienten Amateurfunkstellen mit Ausnahme von
  Amateurfunkstellen im Remote-Betrieb ist nicht gestattet.
  Amateurfunk-Wettbewerbe (Contestbetrieb) dürfen in diesem Frequenzbereich
  nicht durchgeführt werden." [remote-controlled stations not permitted except
  § 13a remote operation; no contests.]
- B11: "Im Teilbereich von 1 247 – 1 263 MHz ist die abgestrahlte Leistung auf
  maximal 3,05 Watt ERP beschränkt. Der Betrieb von fernbedienten und
  automatisch arbeitenden Amateurfunkstellen ist in diesem Bereich nicht
  zulässig." [1247–1263 MHz: radiated power max 3.05 W ERP; no remote/automatic
  stations.]
- B12: "Maximal zulässige Strahlungsleistung für automatisch arbeitende
  Amateurfunkstellen: 50 Watt ERP."
- B15: "Abweichend von den besonderen Nutzungsbestimmungen ist an Wochenenden
  bei Nutzung der Frequenzbereiche 1 850 – 1 890 kHz und 1 890 – 2 000 kHz die
  Verwendung einer Sendeleistung von maximal 750 Watt PEP durch Inhaber … der
  Klasse A und die Verwendung einer Sendeleistung von maximal 100 Watt PEP
  durch Inhaber … der Klasse E zugelassen. An Wochenenden dürfen abweichend von
  der zusätzlichen Nutzungsbestimmung Nummer 10 Amateurfunk-Wettbewerbe
  (Contestbetrieb) durchgeführt werden." [At weekends on 1850–2000 kHz class A
  may use up to 750 W PEP and class E up to 100 W PEP; contests allowed at
  weekends.] "Wochenende" is not defined in D1 **[UNCONFIRMED: exact start/end
  times; treat Sat 00:00 – Sun 24:00 local as a guess only, or refuse the
  uplift]**.
- B17 / Part A (1): links of remote/automatic stations "können in besonders
  begründeten Fällen mit einer Strahlungsleistung von bis zu 1 000 W ERP
  betrieben werden"; terrestrial remote/automatic stations above 30 MHz max
  "50 Watt ERP (ausgenommen Remote-Betrieb)". Not relevant to a personal
  station.

### 3.1 Per-band exceptions

- **60 m:** class A only, exactly the WRC-15 band 5351.5–5366.5 kHz, 9,14 W
  ERP (≈ 15 W EIRP [derived]), 2.7 kHz, secondary [row 7]. No national
  channels.
- **70 MHz / 4 m:** not in Anlage 1. Not permitted for any class in 2026 (see
  §1 pending). Former toleration (class A, 70.150–70.210 MHz, 25 W ERP,
  horizontal) expired 31.12.2025 [D6, D7 secondary].
- **50 MHz:** class A only (E toleration ended 31.12.2025 [D6]); 750 W PEP
  below 50.4 MHz, 25 W PEP 50.4–52; 12 kHz; horizontal polarisation; fixed
  stations only (no /p, /m on 6 m) [B5, B16].
- **160 m:** three sub-bands with different powers, weekend uplift on
  1850–2000 kHz (B15); 1850–2000 no contests on weekdays, no unattended remote
  stations (B10).
- **30 m:** 800 Hz occupied bandwidth (not 2.7 kHz) — rules out SSB (B1).
- **23 cm Galileo exclusion:** 1247–1263 MHz radiated power ≤ 3,05 W ERP for
  every class (B11) — an ERP limit layered on a PEP limit; the guard needs
  antenna gain here.
- **13 cm:** 2320–2450 MHz only. **2300–2320 MHz not allocated**; above 2450
  not allocated. Class E 5 W PEP, class A 75 W PEP, class N none.
- **Bandwidth caps** per row (B1/B3/B4/B6/B7/B8/B9/B16) are law, not band plan
  — 2.7 kHz on all HF bands except 30 m (800 Hz) and 10 m (7 kHz / 40 kHz).
- **Remote operation (§ 13a):** class A only [D1 p.6].
- **Antenna gain:** no general gain rule; ERP rows (2200 m, 630 m, 60 m, all
  of class N, 23 cm Galileo segment) need the gain chain. BEMFV: ≥ 10 W EIRP
  fixed station must be notified [D4].
- **Airborne / maritime:** no separate power limit in Anlage 1; only the call-sign suffixes "/am", "/mm" [D2 Nr. 9]. Note 6 m is fixed-station only (B5).

### 3.2 Gaps: not permitted for any class (list explicitly)

Inside IARU-R1 amateur allocations or common hardware ranges:
- 5250–5351.5 and 5366.5–5450 kHz (only the WRC-15 band).
- 50 MHz for E and N; 70–70.5 MHz (all classes, 2026).
- 146–148 MHz (not in Region 1 anyway).
- 1300–2320 MHz (incl. 2300–2320 MHz).
- 2450–3400 MHz; 3475–5650 MHz (9 cm stops at 3475).
- 5850–10000 MHz.
- 10.5–24 GHz; 24.25–47 GHz etc.
- Classes E and N: 7, 10, 14, 18, 24 MHz, 60 m, LF/MF. Class N: everything
  except 28–29.7, 144–146, 430–440 MHz.

## 4. Satellite / QO-100

- B13 [D1 p.12]: "Die Frequenzbereiche 435 – 438 MHz, 1 260 – 1 270 MHz,
  2 400 – 2 450 MHz, 5 650 – 5 670 MHz, 5 830 – 5 850 MHz, 10,45 – 10,50 GHz, …
  können auch für Amateurfunkdienst über Satelliten genutzt werden; der
  Amateurfunkdienst über Satelliten ist dabei sekundärer Funkdienst. In den
  Frequenzbereichen 435 – 438 MHz, 1 260 – 1 270 MHz, 2 400 – 2 450 MHz und
  5 650 – 5 670 MHz sind andere sekundäre Funkdienste gegenüber dem
  Amateurfunkdienst über Satelliten bevorrechtigt." [these ranges may also be
  used for the amateur-satellite service (secondary); in 435–438, 1260–1270,
  2400–2450 and 5650–5670 MHz other secondary services take precedence.]
  1260–1270 and 5650–5670 MHz Earth→space only; 5830–5850 space→Earth only.
- **QO-100 uplink 2400–2450 MHz:** class A **75 W PEP**, class E **5 W PEP**,
  class N **not permitted**. No extra permission required — it is the ordinary
  row 23. Limit is transmitter PEP, not EIRP.
- **10.45–10.5 GHz** (QO-100 downlink): amateur + amateur-satellite secondary;
  A 75 W / E 5 W PEP (row 32). Receive needs no licence (§ 9(5)).
- Class N may use satellites on 10 m, 2 m and 70 cm within its ERP limits
  (B13 covers 28–29.7 and 144–146 as primary sat; 435–438 secondary).
- AMSAT-DL NB transponder plan [A1, secondary]: uplink 2400.005–2400.490 MHz
  (CW 2400.005–.040, digimodes 500 Hz .040–.080, digimodes 2.7 kHz .080–.150,
  SSB .150–.245, SSB .255–.350, emergency/broadcast ~.3575–.365, mixed
  .365–.490); "keep your signal below Beacon level"; no transmission below the
  lower or above the upper beacon. WB uplink 2401.5–2409.5 MHz **[UNCONFIRMED,
  not in A1]**.

## 5. CEPT / visiting operators

- D3: "Inhabern einer gültigen CEPT-Amateurfunkgenehmigung (CEPT-Lizenz) gemäß
  der CEPT-Empfehlung T/R 61-01 ist die Teilnahme am Amateurfunkdienst in
  Deutschland für einen Zeitraum von bis zu drei Monaten je Aufenthalt
  gestattet. Dabei dürfen die Betriebsrechte der deutschen Klasse A gemäß
  Anhang 1 der Amateurfunkverordnung (AFuV) wahrgenommen werden. Beim Senden
  muss der Genehmigungsinhaber das … Heimatrufzeichen mit vorangestelltem
  Präfix "DL/" verwenden." [T/R 61-01 visitors: up to 3 months per stay,
  class A privileges, prefix DL/.]
- ECC Rec (05)06 Novice visitors: same, class **E** privileges, prefix **"DO/"**
  [D3; D2 Nr. 5].
- CEPT tables: T/R 61-01 Annex 2 "Germany — DL — 1, 2 and A" [CT1 p.6]; ECC/REC/(05)06 Annex 2 "Germany — DO — E" [CT2 p.5]. Class N appears in neither.
- Others: "Kurzzeitzulassung" up to three months [D2 Nr. 5].
- German A holders may operate abroad under T/R 61-01; E holders under (05)06
  [D3]. **Class N has no CEPT operation abroad** [derived — D3 maps only A and
  E].
- HAREC (T/R 61-02): class A exam = HAREC (D3 calls class A HAREC). Further
  detail: BNetzA Vfg 11/2005 (CEPT) and Vfg 93/2005 (Novice) — **not
  downloaded** (BNetzA link returned 404 on 2026-10-08).

## 6. Callsigns

Structure [D2 intro]: "2-buchstabigen Präfix (DA - DR ohne DE und DI), einer
Ziffer (0-9) und einem meist 2- oder 3-buchstabigen Suffix".

Personal calls (PZ) by class [D2 Nr. 1 table]:
- **A:** DA1, DA2, DB1–DB9, DC0–DC9, DD0–DD9, DF1–DF9, DG0–DG9, DH0–DH9,
  DJ0–DJ9, DK1–DK9, DL1–DL9, DM1–DM9. Expiring training calls DN1–DN6 (A).
- **E:** DA6, DO1–DO9. Expiring training calls DN7–DN8 (E).
- **N:** **DN9** only.
- Club/repeater/special: DA0, DA7 (E club), DA8 (N club), DB0/DM0 repeaters
  (A), DO0 repeaters (E), DP0–DP2, DP8 (N, special/exterritorial), DR1–DR6
  emergency-service clubs (DR1/DR4 A, DR2/DR5 E, DR3/DR6 N).
- Training calls DN1–DN8: no new issue from 24.06.2025, valid until
  31.12.2028 [D2 Nr. 10; D1 § 19(3)].

Suffixes [D2 Nr. 9–11; D1 § 11]: "/m" (mobil, land vehicle or inland water),
"/mm" (maritim mobil), "/am" (aeronautisch mobil), "/p" (portabel); "/T"
(Trainee, mandatory in training operation), "/r" (remote, optional; "/Tr"
order); "/Ueb" for DR-club exercises.

Regex hints (class *hint* only; a DN0–DN8 or club call is not a personal
class):
- N: `^DN9[A-Z]{2,3}$`
- E: `^(DO[1-9]|DA6)[A-Z]{2,3}$`
- A: `^(D[BCDFGHJ][0-9]|D[KLM][1-9]|DA[12])[A-Z]{2,3}$`
- Visitors: `^DL/` → A privileges, `^DO/` → E privileges.

## 7. National band plan

DARC publishes per-band charts [B6, B2, B70, B23, B13, B3]; HF follows the
IARU R1 HF plan [I1], with DARC's simplified DL chart [BHF] overlaying AFuV
limits. Recommendations only, except where the AFuV sets a bandwidth.

### HF (BHF, "Stand Dez. 2025"; IARU-R1 2020 segments)

| Band | Segments (kHz), IARU bandwidth | DL-specific notes |
|---|---|---|
| 2200 m | 135.7–137.8 CW/data 200 Hz | AFuV 800 Hz |
| 630 m | 472–475 CW 200 Hz; 475–479 CW/data 500 Hz | |
| 160 m | 1810–1838 CW 200; 1838–1840 500; 1840–1850 all 2700 (P); 1850–1890, 1890–2000 all 2700 (S) | 1836 CW QRP |
| 80 m | 3500–3570 CW 200; 3570–3580 CW/data 200; 3580–3600 500; 3600–3800 all 2700 | QRS 3555, QRP 3560, SSB QRP 3690, **DL emergency 3643**, R1 emergency 3760. Contest-preferred: CW 3510–3560, 3600–3650; SSB 3700–3775; 3775–3800 SSB intercontinental |
| 60 m | 5351.5–5354 CW/data 200; 5354–5366 all 2700; 5366–5366.5 weak signal 20 Hz | |
| 40 m | 7000–7040 CW 200; 7040–7050 500; 7050–7200 all 2700 | QRP 7030, SSB QRP 7090, DL/R1 emergency 7110; contest SSB 7060–7100, 7130–7175; 7175–7200 intercontinental |
| 30 m | 10100–10130 CW 200; 10130–10150 CW/data 500 | QRP 10116; AFuV 800 Hz |
| 20 m | 14000–14070 CW 200; 14070–14099 500; 14099–14101 IBP; 14101–14350 all 2700 | QRS 14055, QRP 14060, SSB QRP 14285, emergency 14300; contest CW 14000–14060, SSB 14125–14300 |
| 17 m | 18068–18095 CW; 18095–18109 500; 18109–18111 IBP; 18111–18168 all | QRP 18086, SSB QRP 18130, emergency 18160 |
| 15 m | 21000–21070 CW; 21070–21110 500; 21110–21120 2700 (no SSB); 21120–21149 500; 21149–21151 IBP; 21151–21450 all | QRS 21055, QRP 21060, SSB QRP 21285, emergency 21360 |
| 12 m | 24890–24915 CW; 24915–24929 500; 24929–24931 IBP; 24931–24990 all | QRP 24906, SSB QRP 24950 |
| 10 m | 28000–28070 CW; 28070–28190 500; 28190–28225 IBP; 28225–28300 beacons 2700; 28300–29000 all; 29000–29300 all (AM/FM simplex usual); 29300–29510 satellite; 29510–29520 guard; 29520–29700 FM 6 kHz | FM rpt inputs 29520–29590, calling 29600, simplex 29610, rpt outputs 29620–29690 (**input below output, −100 kHz**) |

### 6 m (B6, Stand 04/2026; secondary, "NIB")

- 50.000–50.030 synchronised beacons (R1 .000–.010, R2 .010–.020, R3 .020–.030);
  50.000–50.100 CW exclusive 500 Hz; 50.050 future intl CW calling; 50.090 CW
  intercontinental (outside Europe).
- 50.100–50.130 intercontinental; 50.110 interc. calling; 50.130–50.200 general
  intl; 50.150 centre of activity; 50.200–50.300 general SSB/CW 2700 Hz (50.285
  crossband); 50.300–50.400 MGM/CW narrow 2700 Hz (50.305 PSK, 50.310–50.320 EME,
  50.320–50.380 MS).
- **50.400–50.500 beacons exclusive** (1000 Hz), 50.401 ±500 Hz WSPR beacons.
- 50.500–51.000 1000 Hz → 12 kHz: 50.510 SSTV, 50.520–50.540 FM internet gateways,
  50.550 image, 50.600 RTTY, 50.620–50.750 digital, 50.630 DV calling.
- 51.000–52.000 all modes: **FM/DV repeater inputs 51.210–51.390**, simplex
  51.410–51.590, calling 51.510, **repeater outputs 51.810–51.990** (20 kHz
  raster; input **below** output, −600 kHz [derived]).

### 2 m (B2, Stand 08/2017; primary)

| lo–hi MHz | usage | max BW |
|---|---|---|
| 144.000–144.110 | CW exclusive; 144.050 CW calling; 144.100 random MS | 500 Hz |
| 144.110–144.150 | CW/MGM, EME MGM 144.110–144.160; 144.138 PSK31 | 500 Hz |
| 144.150–144.180 | CW, MGM, SSB; 144.160–.180 alt. MGM, 144.170 MGM calling | 2700 Hz |
| 144.180–144.360 | CW & SSB; 144.195–.205 random MS SSB; **144.300 SSB calling** | 2700 Hz |
| 144.360–144.399 | CW, MGM, SSB; 144.370 MGM calling | 2700 Hz |
| **144.400–144.490** | **beacons, no operation**; 144.4920 ±500 Hz WSPR beacons | 500 Hz |
| 144.490–144.500 | guard | |
| 144.500–144.794 | all modes, no gateways; 144.500 SSTV, 144.525 ATV SSB talkback, 144.600 RTTY, 144.630–.660 linear transponder output, 144.660–.690 input, 144.700 FAX, 144.750 ATV talkback | 20 kHz |
| 144.794–144.969 | digital incl. automatic stations/gateways; **144.800 APRS**; 144.8125–144.8625 DV simplex AP/GW; 144.925 control bursts | |
| 144.969–145.194 | **NBFM repeater inputs** RV46–RV63, channels 144.975–145.1875 | 12.5 kHz |
| 145.194–145.206 | V16 145.200 space comms Earth→space | |
| 145.206–145.569 | NBFM simplex (also DV, no gateway); 145.300 RTTY, **145.375 DV calling**, **145.500 FM calling**; 145.2375/.2875/.3375 FM internet gateways | 12.5 kHz |
| 145.569–145.794 | **NBFM repeater outputs** RV46–RV63, channels 145.575–145.7875 | 12.5 kHz |
| 145.794–145.806 | V64 145.800 space→Earth | |
| **145.806–146.000** | **amateur satellite** | |

Repeaters: input = output − 600 kHz (input **below**) [derived from channel
pairs].

### 70 cm (B70 p.1 Stand 08/2017 + p.2 Stand 05/2025; primary)

- 430.000–431.975 "Subregionale Bandplanung": 430.025/.050 FM internet gateway;
  430.100–430.325 NBFM/DV simplex (no networking); 430.350–430.375 DVR/DV
  gateways; **430.4125–430.575 DV/packet duplex inputs (+9.4 MHz → outputs
  439.8125–439.975)**; **430.600–430.9375 DV/packet inputs (+7.6 MHz → outputs
  438.200–438.5375)**; **430.950–431.8375 NBFM repeater inputs (+7.6 MHz →
  outputs 438.550–439.4375)**; **431.850–431.9875 DV repeater inputs (+7.6 MHz →
  439.450–439.5875)**. Max BW 25 kHz / 12.5 kHz as charted.
- 432.000–432.100 CW (500 Hz); 432.000–.025 EME; 432.050 CW calling; 432.088 PSK31.
- 432.100–432.399 SSB/CW 2700 Hz; **432.200 SSB calling**; 432.350 microwave
  talkback; 432.370 FSK441.
- **432.400–432.490 beacons exclusive, no operation**; 432.490–432.500 guard.
- 432.500 APRS (12.5 kHz); 432.500–432.600 linear transponder in; 432.600–432.700
  out; 432.500–432.994 all modes 20 kHz; 432.800–432.875 FM internet gateways.
- 433.000–435.000 all modes / ATV: 433.050–434.775 NBFM simplex U244–U382; 433.300
  RTTY; 433.400 SSTV; **433.450 DV calling**; **433.500 FM calling**; 433.600 RTTY;
  433.6125–433.6875 digital (DV hotspots); 433.700 FAX; 433.775–433.9875 NBFM
  simplex; 434.000 DATV (≤2 MHz, p.1) / 434.250 DATV ≤1 MHz (p.2); 434.000–434.200
  digital broadband experiments; 434.7125–434.7875 DV simplex repeaters;
  434.800–435.000 digital experiments/automatic stations. p.2 (2025) adds 433.175
  Meshcom (250 kHz), 433.775 LoRa-APRS RX, 433.900 LoRa-APRS TX (125 kHz),
  434.100 Meshtastic (125 kHz).
- **435.000–438.000 satellites** (& ATV, 437.000 DATV ≤2 MHz on p.1; 437.500 DATV
  ≤1 MHz on p.2).
- 438.0125–438.1875 DV/packet simplex; 438.200–438.5375 DV/packet repeater
  outputs (−7.6); 438.550–439.4375 NBFM repeater outputs (−7.6); 439.450–439.5875
  DV repeater outputs (−7.6); 439.600–439.800 digital experiments; 439.8125–439.975
  DV/packet outputs (−9.4); **439.9875 POCSAG paging (TX only)**.
- Repeater shift sign: the 430/431 MHz frequency is the **input**, below the
  438/439 MHz output (input = output − 7.6 MHz, or − 9.4 MHz for the 439.8x
  digital pairs).

### 23 cm (B23, Stand 11/2011; secondary)

- 1240.000–1243.250 all, 50 kHz: 1240.000–1241.000 digital links (+59 MHz shift),
  1241.000–1242.000 (+53.5 MHz); **1242.025–1242.700 FM/DV repeater outputs
  RS01–RS28 (input +28 MHz)**; 1242.450–1242.700 DV-DD simplex ±75 kHz;
  1242.725–1243.250 packet duplex outputs RS29–RS50 (+28 MHz).
- 1243.250–1260.000 ATV. **1260–1270 satellites.**
- 1270.025–1270.700 FM/DV repeater **inputs** RS01–RS28 (±28 MHz); 1270.725–1271.250
  packet inputs.
- 1272–1290.994 ATV (16 MHz), 1280.000–1288.000 FM-TV; 1291 ±3 MHz D-ATV.
- 1291.494–1296.000 all; 1294.500–1295.500 digital links (−53.5 MHz).
- 1296.000–1296.150 CW/MGM (DX exclusive, 500 Hz), 1296.000–.025 EME, 1296.138 PSK31.
- 1296.150–1296.800 CW/SSB/MGM 2700 Hz; **1296.200 SSB centre**; 1296.400–.600
  transponder in; 1296.500 SSTV; 1296.600 RTTY; 1296.600–.800 transponder out;
  1296.700 FAX.
- **1296.800–1296.994 beacons, no operation.**
- 1297.494–1297.981 FM simplex; 1297.500 NBFM centre; **1297.725 DV calling**;
  1297.900/.925 Echolink.
- 1298.000–1300.000 all, 25 kHz: **1298.025–1298.975 FM/DV repeater outputs
  RS01–RS39 (−28 MHz)**; 1299.000 digital link (−59 MHz); 1299.075–1299.675
  DD ±75 kHz; 1299.775–1299.975 DV (8 × 25 kHz).
- Shift sign: outputs at 1242.x have input **above** (+28 MHz); outputs at
  1298.x have input **below** (−28 MHz). Remember B11: 1247–1263 MHz ≤ 3.05 W ERP.

### 13 cm (B13, Stand 06/2015; secondary) — note AFuV starts at 2320 MHz

- 2320.000–2322.000 narrowband: 2320.000–2320.150 CW exclusive 500 Hz (EME,
  2320.138 PSK31); 2320.150–2320.800 CW/SSB 2700 Hz (2320.200 SSB centre);
  2320.750–2320.800 beacons (10 W ERP) optional; **2320.800–2320.990 beacons**
  1000 Hz.
- 2321.000–2322.000 FM/DV repeater inputs R12–R14 and simplex (20 kHz).
- 2322.000–2400.000 all modes: RX ATV; 2355–2357 digital simplex; **2357–2365
  digital duplex/HAMNET (+35 MHz), HAMNET 2362 ±2.5 MHz**; **2365–2370 FM/DV
  repeater outputs R12–R14**; 2370 D-ATV; TX ATV; **2392–2400 digital duplex
  (−35 MHz), HAMNET 2392 / 2397 ±2.5 MHz**.
- **2400.000–2450.000 satellites "gemäß besonderem Bandplan"** (QO-100, A1);
  2427/2435/2443 TX ATV only while no satellite operation.
- Repeater pairing: inputs 2321–2322 (R12–R14), outputs 2365–2370 (R12–R14);
  input is **below** output, but the chart gives no exact channel pairing or
  shift **[UNCONFIRMED]**.

### 3 cm (B3, Stand 12/2013; secondary)

- 10000–10150 digital (links +250 MHz; 10100–10150 digital simplex);
  10150–10250 all modes (link/TX ATV 18 MHz); 10250–10350 digital (−250 MHz);
  10350–10368 all; **10368.000–10368.800 narrowband (10368.200 centre)**,
  10368.750–10368.800 beacons (10 W ERP); **10368.800–10368.990 beacons only**;
  10370–10450 all (ATV); **10450–10500 amateur and amateur-satellite**,
  10450–10452 narrowband alternative. Wideband channels 10 MHz max.

### Differences from IARU R1 (for code)

1. 2 m: DL keeps **144.000–144.110 CW exclusive** (2017 plan); IARU R1 now
   has 144.000–144.025 satellite downlinks only [I2 p.37–38] — DL plan
   predates the change.
2. 2 m repeaters: DL lists RV46/RV47 (145.575/145.5875 out) as repeater
   outputs; R1 output segment 145.575–145.7935 matches [I2].
3. 70 cm: DL uses the **HB/DL/OE 7.6 MHz wide-shift system** (inputs 430.6–431.99,
   outputs 438.2–439.59) and 9.4 MHz digital pairs; IARU R1 endorses it as
   footnote (f) [I2 p.43]. Not the 1.6 MHz (433/434.6) system.
4. 70 cm: DL calls 433.450 DV and 433.500 FM, matching R1; DL adds LoRa/Meshcom/
   Meshtastic channels (2025) and keeps POCSAG 439.9875.
5. 23 cm: DL repeaters use **±28 MHz RS pairs (1242/1270/1298)**, not R1's
   1291/1297 RM (−6 MHz) system [I2 p.45; B23].
6. 13 cm: DL band starts at 2320 (AFuV); R1 alternatives 2300–2320 don't
   apply.
7. HF: IARU R1 2020 unchanged; DL adds emergency 3643 kHz and contest
   preferences.
8. Law sets bandwidths that the R1 plan only recommends (2.7 kHz HF, 800 Hz on
   30 m/LF/MF, 12 kHz on 6 m, 40 kHz on 2 m).

## 8. Confidence and gaps

**Overall: high** for the licence table (single primary consolidated text,
every row read from the PDF with page numbers); **medium** for band plans
(DARC charts are old — 2 m 2017, 23 cm 2011, 13 cm 2015 — and graphical).

UNCONFIRMED / to re-check:
- **70 MHz status after June 2026**: Bundesrat-Drucksache 364/26 created a legal
  basis; no BNetzA usage conditions found as of 2026-10-08. Encode as not
  permitted.
- Meaning of "Wochenende" in B15 (160 m uplift).
- 13 cm repeater pairing 2321 ↔ 2365 MHz.
- BNetzA Vfg 11/2005 and 93/2005 (CEPT implementation detail) not downloaded
  (404); CEPT facts taken from the BNetzA web page D3, which is primary.
- Entry-into-force date 24.06.2024 taken from buzer.de [secondary] and the
  BNetzA page [D3] ("Seit dem 24. Juni 2024").
- QO-100 WB uplink edges not from a primary source.
