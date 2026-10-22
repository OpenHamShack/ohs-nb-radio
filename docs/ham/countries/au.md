# Australia (AU): amateur licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM (ohsradio) / OpenHamShack NB. Research only - no
code reads this file yet. Modelled on docs/ham/bandplan-r1-uk.md, whose UK
data was checked line by line against Ofcom's PDF (docs/ham/licence-check.md).

Markers: **[verified]** read in the primary source (cite page/section/clause);
**[secondary]** from a non-regulator source only; **[derived]** worked out
here; **UNCONFIRMED** not found in a primary source - must NOT be encoded as
a permission until confirmed. Never guess a limit.

The licence is law (the TX guard enforces it); the band plan is a voluntary
code (the guard warns).

Page references are to the PDF page (1-based, as `pdftotext` numbers them),
which for CL, LCD and RQZ equals the printed page number. ACMA web pages were
read through the Internet Archive because www.acma.gov.au and docdb.cept.org
timed out / failed TLS from this host; the snapshot date is given per page.

## Sources

| Key | Document (exact title) | Version / date (as printed) | URL | SHA-256 of the file read, pages |
|---|---|---|---|---|
| CL | Radiocommunications (Amateur Stations) Class Licence 2023 | Register ID **F2023L01648**, "Dated: 7 December 2023", "Authorised Version F2023L01648 registered 12/12/2023", commences 19 Feb 2024 (s 2). Federal Register API on 2026-10-08: latest version = **compilation number 0** (as made), `hasUnincorporatedAmendments: false`, no amending instruments; sunsets 1 Apr 2034. | https://legislation.gov.au/F2023L01648/asmade/2023-12-12/text/original/pdf (versions: https://www.legislation.gov.au/F2023L01648/latest/versions) | `50036cf5e634e1e66922ef912b064f532919759063ab0b8f1d5570e812ab9f1c`, 34 pp |
| ES | Explanatory Statement to the amateur class licensing reform instruments (registered with F2023L01648) | "Authorised Version Explanatory Statement registered 12/12/2023 to F2023L01648" | https://legislation.gov.au/F2023L01648/asmade/2023-12-12/es/original/pdf | `2fa84ac687c0ad853f629f07c62de15dd5454031856e008c70fe3c0433342dce`, 27 pp |
| LCD | Radiocommunications Licence Conditions (Amateur Licence) Determination 2025 | **F2025L01087**, "Dated: 11 September 2025", commences 30 September 2025 (s 2); compilation 0, latest; repeals F2015L01113 | https://www.legislation.gov.au/F2025L01087/asmade/2025-09-12/text/original/pdf | `389a5988b8ce6134c501c2ba4e66bfa175c1dd8a4b88d0832999dd3bfc36172b`, 22 pp |
| INT | Radiocommunications (Interpretation) Determination 2025 | **Compilation No. 1**, compilation date 21 June 2025, includes F2025L00711; "Authorised Version F2025C00737 registered 25/07/2025" (title F2025L00362) | https://www.legislation.gov.au/F2025L00362/2025-06-21/2025-06-21/text/original/pdf | `3fa3b513ca313980f0284d0502abf73e6ecd3f41ab62db62ae76b7a97c22983f`, 35 pp |
| ARSP | Australian Radiofrequency Spectrum Plan (2025 Update) 2021 | **Compilation No. 1**, compilation date 9 October 2025, includes F2025L01230; "Authorised Version F2025C01105 registered 26/11/2025" (title F2021L00617) | https://www.legislation.gov.au/F2021L00617/2025-10-09/2025-10-09/text/original/pdf | `5c22bd127b930fb85ad52ce5e9b8a039976d400edd07ec87488c51aeda8edc59`, 221 pp |
| RQZ | Radiocommunications (Australian Radio Quiet Zone Western Australia) Frequency Band Plan 2023 | F2023L00286, "Dated: 16 March 2023", registered 20/03/2023, commences 1 April 2023; compilation 0, latest | https://www.legislation.gov.au/F2023L00286/asmade/2023-03-20/text/original/pdf | `0f1e03df8cb8a00eca44ca85a9191420fc38ea37be0311cb50e3c459503ed6c2`, 5 pp |
| CSP | ACMA, "Amateur radio call sign policy" | "SEPTEMBER 2024" (PDF created 2 Sep 2024). Still the policy linked from ACMA's Amateur radio resources page in the 4 Sep 2026 snapshot. | https://www.acma.gov.au/sites/default/files/2024-09/Amateur%20radio%20call%20sign%20policy_September%202024.pdf (read via web.archive.org) | `a7114cec4162e13256441d7029bc275d5aa2c035efd9f109c5d6de32b959dd17`, 28 pp |
| AW1 | ACMA web page "Overseas amateurs visiting Australia" (Tables A and B of equivalent qualifications) | "Last updated: 02 June 2025"; Wayback snapshot 2026-09-16 22:13:36 | https://www.acma.gov.au/overseas-amateurs-visiting-australia | HTML `8f7a6663c9689b1ffa241e22a40625a60dcf2241d6aa793e3d068db9860dc39d` |
| AW2 | ACMA web page "Amateur class licence" | "Last updated: 01 May 2025"; snapshot 2026-06-08 | https://www.acma.gov.au/amateur-class-licence | HTML `1514817bb8b0f27211e409f2f458e1ca8959643e8b061faf618fe12ad3857870` |
| AW3 | ACMA web page "Amateur radio operating procedures" | "Last updated: 02 December 2025"; snapshot 2026-09-04 | https://www.acma.gov.au/amateur-radio-operating-procedures | HTML `112478d296035e680b96216844d132d5475c913d97c2fe4714989e1233e7cd5d` |
| AW4 | ACMA web page "Amateur radio call signs" | "Last updated: 09 September 2026"; snapshot 2026-09-17 | https://www.acma.gov.au/amateur-radio-call-signs | HTML `c07a8ae78e3d67b4e378c010bb580f27753667469d4b8366b9410a6d55f7d672` |
| AW5 | ACMA web page "Amateur radio resources" (document and legislation list) | snapshot 2026-09-04 | https://www.acma.gov.au/amateur-radio-resources | HTML `234386589fd6412d89ddb6918094d1575af2d42e67d98c1eaf13295400011186` |
| FYSO | ACMA, "Five-year spectrum outlook 2026–31 and 2026–27 work program – Draft for consultation" | "MARCH 2026" (draft; final version not checked) | https://www.acma.gov.au/sites/default/files/2026-03/Five-year%20spectrum%20outlook%202026-31.pdf (via web.archive.org) | `ca074a1528d0e68f266c307205b358009b5480ec2a6ccd630ff15e98c0a819b9`, 67 pp |
| TR | CEPT Recommendation T/R 61-01 "CEPT Radio Amateur Licence" | "approved Nice 1985; amended May 2016 … Annex 4: latest updated October 2024", "Edition of 18 October 2024" | https://docdb.cept.org/download/4541 (via web.archive.org, page snapshot 2026-04-09) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691`, 13 pp |
| NR | ECC Recommendation (05)06 "CEPT Novice Radio Amateur Licence" | "Approved 05 October 2005, amended 27 May 2016 … Editorial update Annex 2: June 2023", "Edition 16 June 2023" | https://docdb.cept.org/download/4372 (via web.archive.org) | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4`, 10 pp |
| W1 | WIA, "Australian Amateur Radio Band Plan – Revision 2026-1" (footer "Australian Amateur Radio Band Plan – Feb 2026") | Revision 2026-1, Feb 2026 (PDF created 1 Mar 2026) | https://www.wia.org.au/members/bandplans/data/documents/WIA%20Australian%20Band%20Plan%202026.pdf | `7fb19388f56b1648368249df41997442cccaaef350ba272fed617a73aabccca7`, 37 pp |

Not read (named so nobody assumes they were): the ITU Radio Regulations
(definitions of pX/pY, App. 1), ACMA RALI AA1 / repeater assignment
requirements, the ACMA "Amateur Radio Qualification Framework April 2024",
the final (non-draft) FYSO 2026–31, IARU Region 3 band plan.

## 1. Regulator and instruments

- **Regulator:** Australian Communications and Media Authority (ACMA). [verified CL p1]
- **Personal stations** have been authorised since **19 February 2024** by the
  **class licence** CL (made under s 132 of the Radiocommunications Act 1992),
  not by individual licences. No application or fee. [verified CL s 2, s 10 p2/p6; AW2]
  - The 2015 overseas-visitor class licence (F2015L01114) was repealed by CL s 4. [verified CL p2]
  - CL has **never been amended**: the Register shows compilation 0 as latest,
    no unincorporated amendments, no amending titles (API query 2026-10-08). [verified]
- **Legacy apparatus ("non-assigned") amateur licences** in force on
  18 Feb 2024 run on until expiry and cannot be renewed; their conditions are
  in LCD Part 3, whose Schedule 1 tables are the same as CL Schedule 2.
  The ACMA "expects that the last amateur licence to which this Part applies
  will expire in June 2028". [verified LCD s 13 note p9; LCD Sch 1 p16–19; ES p3]
- **Repeaters and beacons** still need an individual **apparatus licence**
  ("amateur licence (amateur repeater station)" / "(amateur beacon
  station)"), conditions in LCD Parts 4–5. CL s 13(2)(b)–(c) forbids
  operating a repeater or beacon under the class licence. [verified CL s 13(2) p8; LCD Parts 4–5 p12–15; AW2]
- **Definitions** (pX, pY, EIRP, amateur station, repeater, beacon, necessary
  bandwidth) come from INT, which mostly says "has the meaning given by the
  Radio Regulations". [verified INT s 11 p9–12, p24, p27]
- **Spectrum plan** ARSP sets primary/secondary status; the class licence
  sets what an amateur may do. A band in ARSP that is absent from CL Sch 2
  is **not authorised** (see 60 m). [verified CL s 17 p9–10]
- **Radio Quiet Zone:** RQZ band plan, referenced by CL s 18(3). [verified]

## 2. Licence classes (names, how obtained, what "class" key ohsradio would use)

Three qualification levels; privileges are set by CL s 17 and Sch 2 Tables
A/B/C. A person may operate if they hold a qualification, or under the
supervision of someone who does (CL s 11). [verified CL s 8, s 11, s 17, p5/p7/p9–10]

| ohsradio key [derived] | Instrument wording | How obtained | Table |
|---|---|---|---|
| `au_foundation` | "ACMA recognition certificate (Foundation)" or "recognised qualification (Foundation Type)" | ACMA exam via an accredited assessor (≥70 % in regulatory and theory, pass practical) or exemption (CL Sch 5 cl 2, 4, p28–30); pre-2024 Foundation certificates of proficiency are deemed Foundation Type (CL Sch 7(2) p33) | CL Sch 2 Table A p18 |
| `au_standard` | "… (Standard)" / "(Standard Type)" | as above; old Standard / Novice / Novice Limited certificates deemed Standard Type (CL Sch 7(3); INT p11) | Table B p18–19 |
| `au_advanced` | "… (Advanced)" / "(Advanced Type)" | as above; old Advanced / Unrestricted / Limited certificates deemed Advanced Type (CL Sch 7(1); INT p9–10) | Table C p20–21 |
| `au_visitor_<type>` | holder of a "recognised overseas qualification" of one of the three Types | see §8: not resident, ≤365 continuous days, overseas call sign | Table A/B/C by Type |

- If a person holds more than one certificate, the Tables do not say which
  prevails. **[derived]** Use the highest; each of s 17(1)–(3) restricts only
  the holder of that level, and the ACMA "may give a person more than one ACMA
  recognition certificate" (CL Sch 5 cl 3(5) p29).
- Old licence names ("Limited", "Novice", "Intermediate", "Unrestricted") map
  as in the CL Sch 7 / AW1 tables. ohsradio should only expose the three keys.

## 3. Frequency privileges and power, per class

**Edge convention (law):** "a reference to a part of the spectrum or frequency
band includes all frequencies that are greater than but not including the
lower frequency, up to and including the higher frequency." So every band
below is the half-open interval **(lower, upper]**. [verified CL s 5(3) p4; same in LCD s 5(3) p4]
**[derived]** The guard must check the whole occupied bandwidth, not just
the carrier, against (lower, upper].

**Power units:** column 2 states "watts pX" (peak envelope power) or "watts
pY" (mean power); the two LF/MF rows say "pX EIRP". INT defines pX and pY only
as "the meaning given by the Radio Regulations" (INT p27). **[secondary, RR not
read here]** RR 1.157/1.158 define PEP and mean power as power "supplied to
the antenna transmission line", i.e. transmitter output. The ES calls them
"transmitter output power limits" (ES p3). **But** CL s 17(1)(d) etc. reads
"at a **radiated** power that does not exceed the maximum power limit". See §5
and §11 for this ambiguity.

**Mode split (Standard/Advanced):** the higher figure applies only "if the
station uses emission mode J3E or R3E" (plus **C3F** where the row says so);
"in any other case" the lower **pY** figure applies. Emission mode = ITU RR
App. 1 designation (CL s 5(2) p4). Foundation has no mode split.

"—" = may not transmit. All limits are maxima. Status column is the ARSP
Australian Table (capitals = primary, lower case = secondary).

| # | Band (lower, upper] | Foundation (Table A) | Standard (Table B) | Advanced (Table C) | ARSP status (Australian Table) | Source |
|---|---|---|---|---|---|---|
| 1 | 135.7 kHz – 137.8 kHz (2200 m) | — | — | **1 W pX EIRP**; necessary BW ≤ 2.1 kHz | Amateur, secondary (fn 67A) | CL Sch 2 T-C item 1 p20; ARSP p18 |
| 2 | 472 kHz – 479 kHz (630 m) | — | — | **5 W pX EIRP**; necessary BW ≤ 3 kHz | Amateur, secondary (fn 80A) | CL T-C item 2 p20; ARSP p20 |
| 3 | 1.800 – 1.875 MHz (160 m) | — | — | C3F/J3E/R3E 400 W pX; other 120 W pY; BW>8 kHz → PSD ≤1 W/100 kHz | 1800–1825 AMATEUR; 1825–1875 RADIONAVIGATION + AMATEUR (both primary), Radiolocation sec. (fn 97 Loran) | CL T-C item 3(a) p20; ARSP p22 |
| 4 | 3.500 – 3.700 MHz (80 m) | 10 W pX; BW>8 kHz → PSD ≤1 W/100 kHz | J3E/R3E 100 W pX; other 30 W pY; same PSD rule | 400 W pX (C3F/J3E/R3E) / 120 W pY; same PSD rule | AMATEUR primary | CL T-A item 1(a) p18; T-B 1(a) p18; T-C 3(b) p20; ARSP p24 |
| 5 | 3.776 – 3.800 MHz (80 m DX) | — | — | 400 W pX / 120 W pY; **BW ≤ 8 kHz** | AMATEUR primary (AUS57) | CL T-C 4(a) p20; ARSP p24 |
| 6 | 7.000 – 7.100 MHz (40 m) | 10 W pX; PSD rule >8 kHz | 100 W pX / 30 W pY; PSD rule >8 kHz | 400 W pX / 120 W pY; PSD rule >8 kHz | AMATEUR, AMATEUR-SATELLITE primary | CL T-A 1(b); T-B 1(b); T-C 3(c); ARSP p27 |
| 7 | 7.100 – 7.300 MHz (40 m) | 10 W pX; **BW ≤ 8 kHz** | 100 W pX / 30 W pY; **BW ≤ 8 kHz** | 400 W pX / 120 W pY; **BW ≤ 8 kHz** | **Amateur secondary** (AUS12: RR 4.4 conditions); 7100–7200 FIXED/MOBILE primary, 7200–7300 BROADCASTING primary | CL T-A 2 p18; T-B 2 p19; T-C 4(b) p20; ARSP p27, p107 |
| 8 | 10.100 – 10.150 MHz (30 m) | — | — | 400 W pX / 120 W pY; **BW ≤ 8 kHz** | Amateur secondary (FIXED primary, AUS57) | CL T-C 4(c) p20; ARSP p29 |
| 9 | 14.000 – 14.350 MHz (20 m) | — | 100 W pX / 30 W pY; PSD rule >8 kHz | 400 W pX / 120 W pY; PSD rule >8 kHz | AMATEUR primary; 14.000–14.250 also AMATEUR-SATELLITE | CL T-B 1(c) p18; T-C 3(d) p20; ARSP p30 |
| 10 | 18.068 – 18.168 MHz (17 m) | — | — | 400 W pX / 120 W pY; PSD rule >8 kHz | AMATEUR, AMATEUR-SATELLITE primary | CL T-C 3(e) p20; ARSP p32 |
| 11 | 21.000 – 21.450 MHz (15 m) | 10 W pX; PSD rule >8 kHz | 100 W pX / 30 W pY; PSD rule >8 kHz | 400 W pX / 120 W pY; PSD rule >8 kHz | AMATEUR, AMATEUR-SATELLITE primary | CL T-A 1(c); T-B 1(d) p18–19; T-C 3(f); ARSP p33 |
| 12 | 24.890 – 24.990 MHz (12 m) | — | — | 400 W pX / 120 W pY; PSD rule >8 kHz | AMATEUR, AMATEUR-SATELLITE primary | CL T-C 3(g) p20; ARSP p34 |
| 13 | 28.000 – 29.700 MHz (10 m) | 10 W pX; BW>**16 kHz** → PSD ≤1 W/100 kHz | 100 W pX / 30 W pY; PSD rule >16 kHz | 400 W pX / 120 W pY; PSD rule >16 kHz | AMATEUR, AMATEUR-SATELLITE primary | CL T-A 3 p18; T-B 3 p19; T-C 5 p20; ARSP p35 |
| 14 | 50.000 – 52.000 MHz (6 m low) | — | **C3F**/J3E/R3E 100 W pX; other 30 W pY; **BW ≤ 100 kHz** | C3F/J3E/R3E 400 W pX; other 120 W pY; **BW ≤ 100 kHz** | **Amateur secondary**; BROADCASTING primary (fn 168) | CL T-B 4 p19; T-C 6 p20; ARSP p39, p131 |
| 15 | 52.000 – 54.000 MHz (6 m) | — | J3E/R3E 100 W pX; other 30 W pY; no limitation | 400 W pX (C3F/J3E/R3E) / 120 W pY; no limitation | AMATEUR primary | CL T-B 5(a) p19; T-C 7(a) p21; ARSP p39 |
| 16 | 144.000 – 148.000 MHz (2 m) | 10 W pX; no limitation | 100 W pX (J3E/R3E) / 30 W pY | 400 W pX / 120 W pY | AMATEUR primary; 144–146 also AMATEUR-SATELLITE | CL T-A 4(a) p18; T-B 5(b) p19; T-C 7(b) p21; ARSP p43 |
| 17 | 430.000 – 450.000 MHz (70 cm) | 10 W pX; no limitation | 100 W pX (J3E/R3E) / 30 W pY | 400 W pX / 120 W pY | **Amateur secondary** (RADIOLOCATION primary, AUS101A defence); amateur-satellite only by RR 5.282 (435–438) | CL T-A 4(b) p18; T-B 5(c) p19; T-C 7(c) p21; ARSP p51, p146 |
| 18 | 1.240 – 1.300 GHz (23 cm) | — | 100 W pX (J3E/R3E) / 30 W pY | 400 W pX / 120 W pY | Amateur secondary (RNSS, radiolocation etc. primary; AUS1A, AUS87, AUS101, AUS103; RR 5.282 for 1260–1270, 5.332A) | CL T-B 5(d) p19; T-C 7(d) p21; ARSP p54 |
| 19 | 2.300 – 2.302 GHz (13 cm) | — | — | 400 W pX / 120 W pY | Amateur secondary (in 2300–2450 row; FIXED/MOBILE/RADIOLOCATION primary) | CL T-C 7(e) p21; ARSP p61 |
| 20 | 2.400 – 2.450 GHz (13 cm) | — | 100 W pX (J3E/R3E) / 30 W pY | 400 W pX / 120 W pY | Amateur secondary; ISM (fn 150); amateur-satellite only via RR 5.282 | CL T-B 5(e) p19; T-C 7(f) p21; ARSP p61 |
| 21 | 3.300 – 3.400 GHz (9 cm) | — | — | 400 W pX / 120 W pY | Amateur secondary (RADIOLOCATION primary AUS100A) | CL T-C 7(g) p21; ARSP p64 |
| 22 | 3.400 – 3.600 GHz (9 cm) | — | — | 400 W pX / 120 W pY, **but excluded in the HCIS areas of CL Sch 3 and in spectrum-licensed areas** (see below) | Amateur secondary | CL T-C 8 p21; s 18(1)–(2) p10; Sch 3 p22; ARSP p64 |
| 23 | 5.650 – 5.850 GHz (6 cm) | — | 100 W pX (J3E/R3E) / 30 W pY | 400 W pX / 120 W pY | Amateur secondary; 5830–5850 also Amateur-satellite (space-to-Earth) sec.; 5725–5850 ISM | CL T-B 5(f) p19; T-C 9(a) p21; ARSP p68–69 |
| 24 | 10.000 – 10.500 GHz (3 cm) | — | — | 400 W pX / 120 W pY | Amateur secondary; 10.45–10.5 also Amateur-satellite sec. | CL T-C 9(b) p21; ARSP p75 |
| 25 | 24.000 – 24.250 GHz (12 mm) | — | — | 400 W pX / 120 W pY | 24.00–24.05 AMATEUR, AMATEUR-SATELLITE primary; 24.05–24.25 Amateur secondary | CL T-C 9(c) p21; ARSP p85 |
| 26 | 47.000 – 47.200 GHz (6 mm) | — | — | 400 W pX / 120 W pY | AMATEUR, AMATEUR-SATELLITE primary | CL T-C 9(d) p21; ARSP p93 |
| 27 | 76.000 – 81.000 GHz (4 mm) | — | — | 400 W pX / 120 W pY | 77.5–78 AMATEUR + AMATEUR-SAT primary; 76–77.5 and 78–81 secondary | CL T-C 9(e) p21; ARSP p97 |
| 28 | 122.250 – 123.000 GHz (2.5 mm) | — | — | 400 W pX / 120 W pY | Amateur secondary | CL T-C 9(f) p21; ARSP p100 |
| 29 | 134.000 – 141.000 GHz (2 mm) | — | — | 400 W pX / 120 W pY | 134–136 primary (+ AMATEUR-SAT); 136–141 secondary | CL T-C 9(g) p21; ARSP p101 |
| 30 | 241.000 – 250.000 GHz (1.2 mm) | — | — | 400 W pX / 120 W pY | 248–250 primary; 241–248 secondary | CL T-C 9(h) p21; ARSP p105 |

"PSD rule" = the Column 3 text "If a person operates an amateur station with
an emission mode that has a necessary bandwidth exceeding 8 kHz [16 kHz on
10 m], the maximum power spectral density from the station must not be greater
than 1 watt per 100 kHz". "BW ≤ x" = "A person must not operate an amateur
station with an emission mode that has a necessary bandwidth exceeding x".
Rows 15–30 say "No limitation". [verified, pages as cited]

Summary by class [derived from the table]:
- **Foundation:** 80 m (3.5–3.7), 40 m (7.0–7.3), 15 m, 10 m, 2 m, 70 cm,
  all at **10 W pX**, any mode. Nothing else.
- **Standard:** Foundation bands plus 20 m, 6 m, 23 cm, 2.4 GHz, 5.7 GHz;
  100 W pX for J3E/R3E (and C3F on 50–52 MHz), otherwise 30 W pY.
- **Advanced:** everything in the table; 400 W pX for C3F/J3E/R3E,
  otherwise 120 W pY; 2200 m/630 m at 1 W / 5 W pX EIRP.

### Gaps inside nominal bands (refuse for every class)

All [derived] from the table, i.e. from CL Sch 2:
- **1.875 – 2.000 MHz** (160 m above 1875 kHz): not authorised.
- **3.700 – 3.776 MHz** and **3.800 – 4.000 MHz**: not authorised (ARSP p24:
  FIXED/MOBILE).
- **5 MHz / 60 m (5351.5–5366.5 kHz): NOT authorised.** ARSP allocates
  "Amateur 133B" (secondary, 15 W e.i.r.p. per RR 5.133B) in the Australian
  Table [verified ARSP p26, p123], but CL Sch 2 lists no 5 MHz band, and an
  amateur "must not operate … except on a frequency within a frequency band
  listed" in the relevant table (CL s 17). The WIA band plan has no 60 m
  page (W1). So 60 m must be refused.
- **7.300 MHz and above**: not authorised.
- **29.700 – 50 MHz**, **54 – 144 MHz**, **148 – 430 MHz**, **450 – 1240 MHz**:
  not authorised.
- **2.302 – 2.400 GHz** (spectrum-licensed 2.3 GHz band) and **2.450 – 3.300 GHz**:
  not authorised.
- **3.600 – 5.650 GHz**, **5.850 – 10.000 GHz**, **10.5 – 24 GHz**,
  **24.25 – 47 GHz**, **47.2 – 76 GHz**, **81 – 122.25 GHz**,
  **123 – 134 GHz**, **141 – 241 GHz**, **above 250 GHz**: not authorised.
- Foundation additionally has no 160 m, 30 m, 20 m, 17 m, 12 m, 6 m or
  anything above 450 MHz. Standard additionally has no LF/MF, 160 m,
  3.776–3.8, 30 m, 17 m, 12 m, 2.300–2.302 GHz, 3.3–3.6 GHz, or anything above
  5.850 GHz.

### Per-band exceptions (60 m, 2200 m / 630 m EIRP and notifications, location exclusions, etc.)

- **2200 m / 630 m:** Advanced only. Limits are **EIRP** (1 W pX EIRP and
  5 W pX EIRP), not transmitter output [verified CL T-C items 1–2 p20]. ARSP
  fn 80A: 1 W EIRP, administrations may allow **5 W** more than 800 km from
  listed countries [verified ARSP p117]; Australia uses 5 W. **No
  notification or registration requirement** appears in CL (unlike the UK)
  [verified by reading CL in full].
- **60 m:** see Gaps. Not authorised.
- **3.4–3.6 GHz:** "must not operate an amateur station on a frequency within
  the 3.4 GHz to 3.6 GHz frequency band if the operation would cause a
  transmission to occur in the area described by the HCIS identifiers in the
  table in Schedule 3" [verified CL s 18(1) p10]. Schedule 3 lists ~200 HCIS
  cells (e.g. BV, CV, …, BU9N) on the Australian Spectrum Map Grid 2012 [verified CL Sch 3 p22].
  WIA says the allocation "has been withdrawn for most of the populated
  parts of Australia" and recommends using 3300–3400 only [secondary W1 p27].
  **[derived]** ohsradio cannot resolve HCIS cells without the ACMA grid; the
  guard should refuse 3.4–3.6 GHz unless an operator override that asserts
  location outside Sch 3 is added (and see the next bullet).
- **Spectrum-licensed areas (all bands):** if a spectrum licence authorises
  devices at a frequency within an area, an amateur may not operate at those
  frequencies within that area [verified CL s 18(2) p10]. Which amateur
  bands overlap a spectrum licence today is **UNCONFIRMED** (3.4–3.6 GHz is
  the obvious one; ARSP and FYSO note 2302–2400 MHz is spectrum-licensed,
  which is already outside the amateur band [verified FYSO p34]).
- **Radio Quiet Zone WA:** "A person must not operate an amateur station in
  the RQZ" — no frequency qualifier, so **all frequencies** [verified CL
  s 18(3)–(4) p10]. The RQZ is everything within **150 km** of **26.704167° S,
  116.658889° E (GDA94)**: inner zone 0–70 km, outer 70–150 km (the RQZ's own
  frequency range is 70 MHz – 25.25 GHz, but CL s 18(3) is not limited to
  it) [verified RQZ Sch 1 p5, s 5 p2]. **[derived]** If ohsradio knows the
  station's position, refuse all TX inside 150 km of that point.
- **50–52 MHz:** amateur is secondary to BROADCASTING (ARSP p39, fn 168).
  No class-licence condition about TV (the LCD has one for *beacons and
  repeaters* only: must not interfere with the primary service, LCD s 20,
  s 27 p12/p15) [verified].
- **7.1–7.3 MHz, 70 cm, 23 cm, microwave secondary bands:** secondary status
  only; no geographic exclusion in the licence.
- **Radio-astronomy sites (AUS87, AUS103):** ARSP footnotes name Narrabri,
  Parkes, Mopra, Mt Pleasant, Ceduna, Tidbinbilla and the Murchison
  observatory [verified ARSP p110, p112]. These are planning footnotes, not
  amateur licence conditions; W1 recommends a 250 km buffer on several
  microwave bands [secondary W1 p24–34]. Guard should **warn**, not refuse.
- **Pine Gap / other defence-site exclusions:** none found in CL, LCD or
  ARSP amateur rows. Nothing to encode. (Defence is primary on 70 cm, 23 cm,
  3.3–3.4, 5.65–5.85, 10 GHz per AUS100A/AUS101A — secondary-status only.)
- **23 cm and GNSS:** WIA warns that RR 5.332A (WRC-23) could bring power
  restrictions on 1258–1296 MHz if GNSS interference is reported; no
  Australian restriction exists today [secondary W1 p22; ARSP lists 332A on p54].

## 4. Emission, bandwidth and symbol-rate limits

[verified CL Sch 2 Column 3 and s 5(2), pages in §3]
- Emission mode = ITU RR Appendix 1 designation (CL s 5(2)). Necessary
  bandwidth = RR meaning (INT p24).
- **No mode restrictions for any class** except the bandwidth / PSD rules
  and the power-by-mode split. No symbol-rate limits. No restriction on
  self-built or modified equipment for Foundation (searched CL for
  "commercial", "manufactur"; none). [verified]
  - The old Foundation restrictions (commercial equipment only, listed modes)
    were in the pre-2024 LCD; ACMA relaxed Foundation digital modes in 2020
    [secondary: WIA news 2020-07-29 via search, not read in full].
- **Hard bandwidth caps:** 2.1 kHz (2200 m), 3 kHz (630 m), 8 kHz (3.776–3.8,
  7.1–7.3, 10.1–10.15), 100 kHz (50–52 MHz, Standard and Advanced).
- **PSD rule** (bandwidth allowed, but if > 8 kHz, PSD ≤ 1 W / 100 kHz):
  1.8–1.875, 3.5–3.7, 7.0–7.1, 14.0–14.35, 18.068–18.168, 21.0–21.45,
  24.89–24.99; same with a **16 kHz** threshold on 28.0–29.7.
  **[derived]** e.g. 16 kHz FM on 40 m low is lawful only at ≤ 0.16 W total;
  on 10 m a 16 kHz FM signal is fine at full power, anything wider is PSD-limited.
- **No limitation** at 52 MHz and above (except 50–52 MHz).
- **Encoding:** must not transmit "a signal that is encoded, for the purpose
  of obscuring the meaning", except to control a space station, to control
  an unattended amateur station, or for emergency-services operations or
  training exercises [verified CL s 13(2)(d)(iv), 13(3) p8].
- **Spurious emissions:** attenuated below the in-band power supplied to the
  antenna transmission line by the lesser of 43 + 10 log(pX) dB or 50 dB
  (< 30 MHz); lesser of 43 + 10 log(P) dB or 70 dB (≥ 30 MHz, P in watts)
  [verified CL s 15(2)–(3) p9].
- **Simultaneous transmissions** on multiple frequencies must meet
  ARPANSA's multi-frequency exposure rule [verified CL Sch 1 cl 2(4) p13].

## 5. Antenna gain, ERP/EIRP treatment

- Only **2200 m and 630 m** are expressed as EIRP ("watt pX EIRP"). Every
  other row is plain "watts pX" / "watts pY", **with no antenna-gain or
  ERP/EIRP cap**. [verified CL Sch 2 p18–21]
- **Ambiguity:** CL s 17(1)(d), (2)(d), (3)(d) say "at a **radiated power**
  that does not exceed the maximum power limit". pX/pY in the Radio
  Regulations are powers supplied to the antenna transmission line, and the
  ES describes the limits as "transmitter output power limits" (ES p3).
  **[derived]** Read as transmitter output (PEP/mean) except where EIRP is
  stated. The cautious engineering reading (radiated = output minus feeder
  loss, never more) gives the same guard behaviour: limit transmitter output
  to the figure. Flagged in §11.
- **EME exposure (Schedule 1):** a station must not exceed ARPANSA general
  public reference levels where the public can go. "Low risk" stations are
  presumed compliant with documentation: average total power to all
  antennas ≤ 100 W with antennas inaccessible to the public, **or** lowest
  antenna base ≥ 10 m above ground and average total EIRP ≤ 3200 W in any
  direction; mobile stations ≤ 100 W average. Others must measure/calculate
  per AS/NZS 2772.2, IEEE C95.3 or IEC 62232 and keep the record [verified
  CL Sch 1 cl 2–5 p12–16]. **[derived]** ohsradio can surface this as an
  informational warning above 100 W average; it is not a band limit.

## 6. Station types: repeaters, beacons, unattended / automatic, satellite (13 cm 2400-2450 amateur-satellite status)

- **Repeaters / beacons:** not under the class licence (CL s 13(2)(b)–(c),
  note: "may only operate an amateur repeater station or an amateur beacon
  station under a transmitter licence") [verified CL p8]. Apparatus-licence
  conditions: repeater must be incapable of transmitting without a received
  signal; repeater ID at least every 10 min; access control (1750 Hz tone
  burst, the 30 listed CTCSS tones 67.0–192.8 Hz, DTMF, or "any other
  readily available code") when output is on a frequency the originator may
  not use; beacons ID every 10 min; location changes > 7 days need a
  variation [verified LCD ss 19–28, Sch 3 p12–22]. Frequencies, power and
  call signs are per individual licence; ACMA assignment rules (RALI AA1 for
  beacons, repeater RALI) **not read — UNCONFIRMED**.
- **Unattended operation** is allowed under the class licence only if the
  station runs in "automatic mode" or "computer controlled mode" **and** "is
  fitted with a timer that causes automatic shutdown of the station if a
  malfunction causes an unintended transmission that lasts longer than
  10 minutes" [verified CL s 13(4) p8; definitions s 5 p2–3].
  **[derived]** ohsradio must enforce a hardware/software TX watchdog of
  ≤ 10 min whenever it transmits without an operator present (FT8 robots,
  remote operation, beacon-like WSPR). Remote control links may be encrypted
  (s 13(3)(b)).
- ACMA guidance: internet-linked stations (incl. repeaters) must have
  measures so they cannot be operated by unlicensed persons [AW3, guidance].
- **Retransmission:** permission + indicate it is a retransmission [AW3
  guidance; for legacy licences it is a condition, LCD s 9(5) p7]. The
  class licence itself has no retransmission clause [verified by reading CL].
- **Satellite:** CL Sch 2 does not distinguish terrestrial and satellite use.
  ARSP gives AMATEUR-SATELLITE (primary) at 7.0–7.1, 14.0–14.25, 18.068–18.168,
  21.0–21.45, 24.89–24.99, 28.0–29.7, 144–146 MHz, 24.00–24.05, 47.0–47.2,
  77.5–78, 134–136, 248–250 GHz; secondary at 5830–5850 MHz (s-E),
  10.45–10.5, 76–77.5, 78–81, 136–141, 241–248 GHz [verified ARSP p27–105].
- **13 cm 2400–2450 MHz:** the Australian Table row 2300–2450 MHz shows only
  "Amateur" (secondary) plus footnote **282**; there is **no
  amateur-satellite row**. Amateur-satellite use of 435–438, 1260–1270,
  2400–2450, 3400–3410 and 5650–5670 MHz is permitted only under RR 5.282:
  "subject to not causing harmful interference to other services" [verified
  ARSP p61, p146]. Standard and Advanced may transmit (uplink) there; Foundation may not.
- Earth-station transmissions to amateur satellites need nothing extra; there
  is no separate satellite authorisation in CL [verified, no such clause].

## 7. Call signs, portable/location indicators, identification rules

**Identification (law):** transmit own call sign at **the beginning and end
of each transmission** and, if a transmission lasts **more than 10 minutes,
at least once every 10 minutes** [verified CL s 12(1) p7]. A supervised
operator may send the supervisor's call [s 12(2)]. Emergency-services
operations/training: beginning, end and every **30 min** [s 14 p8–9].
ACMA guidance: during an established series of transmissions, call signs
"must be used every 10 minutes", not every over; ID by voice in English,
visual image or an internationally recognised code (e.g. Morse) [AW3].

**Prefix substitution:** VK may be replaced by **AX** on **26 January,
25 April and 17 May** each year [verified CL s 12(4) p7]. Not for repeater,
beacon or contest calls [CSP p9 fn 6].

**VK0 / VK9:** VK0 calls may only be transmitted while in the Australian
Antarctic Territory; VK9 only while in an external Territory other than
the AAT [verified CL s 12(7)–(9) p7]. VK9 territories listed: Coral Sea
Islands, Ashmore and Cartier, Norfolk, Cocos (Keeling), Christmas, Heard and
McDonald; **not** Lord Howe Island [verified CSP p7]. VK0/VK9, special-event
and contest calls are assigned for 12 months [CSP p5, p11].

**State/territory digit** (residence when first assigned; need not change
on moving) [verified CSP p2–3]:

| Digit | Area |
|---|---|
| 0 | Antarctic (Australian Antarctic Territory) |
| 1 | ACT |
| 2 | NSW |
| 3 | VIC |
| 4 | QLD |
| 5 | SA |
| 6 | WA |
| 7 | TAS |
| 8 | NT |
| 9 | Australian External Territories |

**Suffix structure by class** [verified CSP p6, p10 unless stated]:

| Type | Format | Who |
|---|---|---|
| 2-letter | VK + digit + 2 letters (VK7AA) | **Advanced only** (incl. clubs via an Advanced representative) |
| 3-letter | VK + digit + 3 letters (VK8RHP) | **any class** (Foundation, Standard, Advanced) |
| F-series (4-letter) | VK + digit + F + 3 letters (VK2Faaa) | **no longer assigned** ("incompatible with some digital modes"); existing holders may keep them (Foundation, pre-2024) |
| Contest (2x1) | VJ, VK or VL + digit + 1 letter (VL3A); CL s 5 defines it as a two-letter prefix starting with V + digit + one letter, with an assignment period | **Advanced only**; transmit only while competing in an amateur contest (CL s 12(5)) |
| Special event | VI, VK or AX + 1–4 digits + suffix of up to 10 letters | event only (CL s 12(6)) |
| Repeater / beacon | VK + digit + R + 2 letters (VK$Raa–VK$Rzz) | apparatus licence [CSP p23] |
| Reserved | VK$GGA–GGZ (Guides), VK$SAA–SDZ (Scouts), VK$WIA–WIZ and VK$WI (WIA), VK$IYA–IYZ (UN international years) | groups [CSP p16] |

- **Since 2020 the suffix no longer identifies the class** — a 3-letter
  call may belong to Foundation, Standard or Advanced; only a 2-letter
  suffix implies Advanced and an F + 3-letter suffix implies (originally)
  Foundation [verified CSP p6–10; AW4: register shows "the qualification
  level of the amateur to whom it is assigned"].
  **[derived]** ohsradio must not infer the class from a VK call sign; the
  operator must declare it. The only safe check: a VKnXX 2-letter call or a
  VJ/VL contest call implies Advanced.
- **Visitors:** must "add the letters VK at the start of the call sign when
  transmitting it in Australia" [verified CL s 12(3) p7]. ACMA: "use the
  prefix VK before your usual (home country) call sign. You may also use the
  relevant prefix for the state or territory designator … for example …
  VK9 followed by your usual home country call sign" [AW1]. Separator
  ("VK/G4ABC" vs "VKG4ABC") is not specified — **UNCONFIRMED**; the "/"
  form is universal practice [secondary].
- **Portable / mobile (guidance, not law):** "you may add the numeral of the
  state or territory you are operating in to the end of your call sign",
  e.g. "VK6HR portable 8"; vehicle/vessel/aircraft add "mobile", "maritime
  mobile", "aeronautical mobile" [AW3]. CL itself has no portable-suffix
  rule [verified].
- Clubs: club calls may be used by members of any class within their own
  privileges [AW3].

## 8. Reciprocal operating (visitors in; this country's licensees abroad: CEPT T/R 61-01 / ECC Rec (05)06, IARP, bilateral)

**Visitors operating in Australia** [verified CL s 8(b) p5, s 9, Sch 7(4)–(7) p33–34; AW1]:
- A visitor is a "qualified person" if they are visiting from another
  country, **not an Australian resident**, have **not been in Australia for
  more than 365 continuous days** since last entering, hold a **recognised
  overseas qualification**, and have been assigned a call sign by a foreign
  administration.
- "Recognised overseas qualification" = one the ACMA has declared (CL s 9)
  Advanced, Standard or Foundation Type; the pre-2024 "Tables of Equivalent
  Qualifications and Licences" carried over (Sch 7(4)–(7)). No notification,
  no fee: "you can operate in Australia for 365 days without needing to inform us" [AW1].
- The visitor then has exactly the Table A/B/C privileges of that Type.
- Selected mappings from AW1 Table A [verified AW1, snapshot 2026-09-16]:
  - **CEPT**: HAREC (any level), CEPT class 1, class 2, "CEPT licence"
    → **Advanced**.
  - **United Kingdom**: Foundation → **Foundation**; Intermediate →
    **Standard**; Full → **Advanced**.
  - **USA** (licences granted from 3 July 2017): Extra → Advanced, General
    → **Standard**, Technician → **Foundation** (earlier date ranges map
    differently, e.g. pre-15 Apr 2000 General → Advanced).
  - **New Zealand**: General (and pre-1986 Grades I/II), Limited →
    Advanced; Novice → Standard.
  - **Japan**: 1st/2nd class → Advanced; 3rd/4th class → Advanced with an
    asterisk: "Telephone-only operation on frequency bands above 30 MHz with
    10 watts maximum power". **UNCONFIRMED** how this asterisk relates to
    the Table C limits in law; treat as the asterisk says.
  - Netherlands Category D: "(not acceptable)" (Table B).
- CEPT **Novice** licences / ECC Rec (05)06: Australia is **not** a party —
  the Recommendation (Edition 16 June 2023) does not mention Australia
  [verified NR, text search]. A CEPT Novice is recognised only if the
  national novice licence is itself listed in AW1 (several are, at
  Standard).
- **Pending:** "Different arrangements are planned for HAREC … licensees, so
  that they can operate … for any length of time and can apply for an
  Australian call sign" [AW1]. No instrument yet (CL unamended).

**CEPT T/R 61-01:** Australia is a non-CEPT participant listed in Annex 4
(Table 2) with prefix **VK**; the Australian licence equivalent to the CEPT
licence is "Amateur Licence (Amateur Advanced station) or Advanced
qualification for operation under the [CL]"; footnote 18: "The class licence
allows holders of a CEPT amateur radio licence to operate in Australia for
up to 365 days on all allocated amateur bands without the requirement to
obtain any additional approvals" [verified TR p9]. So **only Advanced**
Australians operate abroad under T/R 61-01; Foundation and Standard have no
CEPT equivalence [verified TR p9; AW1 "Australian advanced amateurs may be
able operate in various overseas countries …"]. The Advanced syllabus is
designed to meet HAREC; ACMA will confirm HAREC equivalence on request [AW1].

**IARP (CITEL):** Australia is not a CITEL member; not applicable —
**UNCONFIRMED** (not checked against the CITEL list).

**Bilateral:** the AW1 Table A is described as countries "we have an
arrangement with"; the individual agreements were not read.

## 9. National band plan, per band (CW / narrow digital / SSB / FM simplex / repeaters with offsets / beacons / satellite / digital dial freqs)

Source: WIA "Australian Amateur Radio Band Plan – Revision 2026-1" (W1),
voluntary. Page numbers are W1 pages. "BW" = WIA recommended maximum
bandwidth. Where W1's licence-class or status headings disagree with the
law, the law (§3) wins; disagreements are listed at the end.

**2200 m (p5):** 135.7–137.4 CW; 137.4–137.6 DATA; 137.6–137.8 CW (all
<500 Hz). WSPR/FST4W dial 136.0 kHz USB (137.4–137.6); QRSS 137.6–137.8.

**630 m (p6):** 472–474 CW; 474–476 DATA (CW shared); 476–479 VOICE <2.1 kHz
("NEW") + CW. WSPR dial 474.2 kHz USB; LSB voice 478.5 kHz.

**160 m (p7):** 1800–1810 DATA <3 kHz (CW shared); 1810–1835 CW; 1835–1840
DATA (CW shared); 1840–1843 DATA/voice/CW shared; 1843–1875 VOICE <6 kHz.
FT8 1840 kHz; FT8 F/H 1835; WSPR dial 1836.6; AM 1870 kHz.

**80 m (p8):** 3500–3535 CW; 3535–3570 VOICE <3 kHz (lowest LSB dial 3538);
3570–3600 DATA <3 kHz; 3600–3700 VOICE <6 kHz (lowest LSB dial 3603);
3776–3800 VOICE (Advanced, SSB DX window, lowest LSB dial 3779). FT8 3573,
JT65 3576, WSPR dial 3568.6, emergency 3600 (R3) / **3610 (VK)**, AM 3686.

**40 m (p9):** 7000–7040 CW; 7040–7060 DATA; 7060–7074 VOICE (LSB dial
≥7063); 7074–7080 DATA (WSJT); 7080–7100 VOICE (LSB dial ≥7083); 7100–7200
and 7200–7300 VOICE <3 kHz (secondary; 7200–7300 "daylight only use
possible"). FT8 7074, FT4 7047.5, FT8 DXpedition 7056, WSPR dial 7038.6,
APRS 300 Bd dial 7045.2, Winlink 7050–7056, emergency 7110, AM 7125, SSTV 7171.

**30 m (p10):** 10100–10120 CW; 10120–10131 VOICE USB "Domestic Only" (USB
dial below 10128; "Only Australian Amateurs are permitted to use SSB on this
band" — the law permits any mode ≤ 8 kHz); 10131–10150 DATA. FT8 10136,
FT4 10140, WSPR dial 10138.6, APRS dial 10147.6.

**20 m (p11):** 14000–14070 CW; 14070–14099 DATA; 14099–14101 IBP beacons;
14101–14112 DATA (Winlink); 14112–14350 VOICE (highest USB dial 14347).
FT8 14074, FT4 14080, JT 14077, WSPR dial 14094.6, SSTV 14230, emergency 14300.

**17 m (p12):** 18068–18095 CW; 18095–18109 DATA; 18109–18111 beacons;
18111–18168 VOICE. FT8 18100, FT4 18104, WSPR dial 18104.6, emergency 18160.

**15 m (p13):** 21000–21070 CW; 21070–21149 DATA; 21149–21151 beacons;
21151–21450 VOICE. FT8 21074, FT4 21140, WSPR dial 21094.6, SSTV 21340,
emergency 21360.

**12 m (p14):** 24890–24910 CW; 24910–24929 DATA; 24929–24931 beacons;
24931–24990 VOICE. FT8 24915, FT4 24919, WSPR dial 24924.6, WICEN 24950.

**10 m (p15):** 28000–28070 CW; 28070–28190 DATA; 28190–28200 beacons
(time-shared); 28200–28300 beacons (continuous); 28300–29100 narrowband
VOICE (highest USB dial 29097); 29100–29300 wideband VOICE <16 kHz;
29300–29510 SATELLITE; 29510–29590 FM repeater inputs; 29590–29610 FM
simplex; 29610–29700 FM repeater outputs — **100 kHz offset** (input =
output − 100 kHz) [derived from segment layout]. FT8 28074, FT4 28180,
WSPR dial 28124.6, WICEN 28450, SSTV 28680.

**6 m (p16–17):** 50.000–50.030 IBP beacons; 50.030–50.080 international
beacons; 50.080–50.105 CW; 50.105–50.220 narrowband voice; 50.220–50.330 DATA;
50.330–50.400 voice; 50.400–50.500 domestic beacons; 50.5–52.0 all modes
<8 kHz; 52.0–52.5 experimental wideband <500 kHz; 52.5–52.5375 FM simplex;
52.5375–53.0 repeater inputs; 53.0–53.55 FM/digital simplex; 53.55–54.0
repeater outputs. **Repeater offset −1 MHz, 25 kHz channels**; call-area
channels 52.750/53.750 VK5/8, 52.800/53.800 VK6, 52.825/53.825 VK7,
52.900/53.900 VK3, 52.850/53.850 VK2, 52.950/53.950 VK4. Calling 50.110
(SSB intl), 50.150 national SSB, 50.090 CW, FT8 50.313 (and 50.323),
WSPR dial 50.293, FM call 52.525, APRS 52.050, WICEN 53.150.

**2 m (p18–19):** 144.000–144.025 satellite; 144.025–144.100 CW;
144.100–144.400 SSB/data; 144.400–144.600 beacons; 144.600–144.700 all
modes; 144.700–144.8875 data / digital simplex (hotspots); 144.8875–145.0625
digital repeater outputs (Block C); 145.0625–145.2125 digital simplex;
145.2125–145.4875 FM simplex; 145.4875–145.6625 digital repeater inputs
(Block C); 145.6625–145.800 FM simplex; **145.800–146.000 satellite**;
146.000–146.4125 repeater inputs (Block A); 146.4125–146.6125 FM simplex;
146.6125–147.0125 repeater outputs (Block A); 147.0125–147.3875 repeater
outputs (Block B); 147.3875–147.5625 simplex; 147.5625–147.6125 data;
147.6125–148.000 repeater inputs (Block B). **[derived]** Block A: input =
output − 600 kHz; Block B: input = output + 600 kHz; Block C: input =
output + 600 kHz. Blocks D/E1/E2 (−1.6 MHz) only where a 600 kHz offset
fails an intermod check. Calling: 144.100 SSB, 146.500 FM, APRS 145.175,
WICEN APRS 145.200, FT8 144.174, WSPR dial 144.489.

**70 cm (p20–21):** 430–431 links (A); 431.000–431.9375 repeater inputs
Block A (**−7 MHz**); 431.9375–432.100 CW; 432.1–432.3 SSB; 432.3–432.4
data; 432.4–432.6 beacons; 432.6–433.05 repeater inputs Block B (−7 MHz);
433.05–434.79 LIPD sub-band (no ACMA protection; links D 434.0–434.5,
hotspot inputs 434.5–434.79); 434.79–435.0 Block B alt inputs (**−5 MHz**);
**435–438 satellite**; 438.000–438.9375 repeater outputs Block A;
438.9375–439.0375 FM simplex; 439.0375–439.2375 digital simplex;
439.2375–439.6125 FM simplex; 439.6125–440.0 repeater outputs Block B
(−7 or −5 MHz); 440–441 links (B); 441.0–441.5 all modes; 441.5–441.79
hotspot outputs; 441.8–442.0 hotspot simplex; 442–449 DVB-T ATV (7 MHz,
centre 445.5); 449–450 links (C). Calling 439.000 FM, 432.100 SSB,
FT8 432.313, WICEN 438.950, digital call 439.200, APRS 439.100.

**23 cm (p22–23):** 1240–1257.5 ATV (DVB 1245/1253, FM 1249); 1257.5–1258
repeater outputs; 1260–1270 satellite; 1273–1274 / 1293–1294 legacy repeater
pairs; 1296.000–1296.100 CW; 1296.1–1296.4 SSB; 1296.4–1296.6 beacons;
1296.6–1297.5 FM simplex; 1297.5–1298.0 repeater inputs; 1298–1299 simplex;
1299–1300 EME. Calls 1296.100 SSB, 1297.000 FM. **[derived]** 1257.5 out /
1297.5 in ⇒ inputs 40 MHz above outputs (W1 states no offset here — UNCONFIRMED).

**13 cm (p24–25):** 2300–2302 narrowband (<3 kHz); 2400–2403 satellites;
2403.0–2403.1 EME; 2403.1–2403.4 SSB; 2403.4–2403.6 beacons; 2403.6–2405
FM simplex; 2405–2406 repeater inputs / 2425–2426 outputs (**20 MHz
offset**); ATV 2406–2424 and 2430–2448; 2426–2430 wideband data; 2448–2450
all modes. Calls 2403.100 SSB, 2404.000 FM.

**9 cm (p26–27):** 3300–3302 all; ATV/data 3302–3394; radio-astronomy
sub-bands 3332–3339 and 3345.8–3352.5 (250 km buffer "required"); repeater
out 3356–3357 / in 3396–3397 (40 MHz); 3398.0–3398.4 CW/SSB; 3398.4–3398.6
beacons; 3399–3400 EME. WIA recommends no use of 3400–3600.

**6 cm (p28–29):** 5650–5660 satellite uplinks; ATV 5670–5690, 5735–5755,
5815–5825; repeater out 5730–5735 / in 5770–5775 (+40 MHz, 100 kHz raster
from 5730.1); 5760.0–5760.4 CW/SSB; 5760.4–5760.6 beacons; 5830–5850
satellite downlinks. Call 5760.100 SSB.

**3 cm (p30–31):** narrowband 10368.0–10368.6 (EME, CW/SSB, beacons
10368.4–10368.6); repeaters in 10355–10360 / out 10445–10450 (+90 MHz,
200 kHz raster); 10450–10500 satellite. Call 10368.100.

**12 mm, 6 mm, 4 mm, 2.5 mm, 2 mm, 1.2 mm (p32–37):** narrowband centres
24048.1, 47088.1, 76032.1 MHz, 122.990100 GHz, 134.000150 GHz,
241.000100 GHz; 24000–24050 "SATELLITE"; rest all-modes.

**Where W1 disagrees with the law** [derived, compare §3]: W1 labels
122.25–123 GHz "PRIMARY" but ARSP p100 says Amateur secondary; W1 p16 says
50–52 MHz "Standard and Advanced" — consistent; W1 p10's "Only Australian
Amateurs are permitted to use SSB" is a band-plan convention, not law. The
guard must use §3, never W1, for permissions.

## 10. Pending changes

- **Class licence minor amendments:** ACMA "plan[s] to consult in Q1 2027
  on minor changes to the amateur radio class licence and examination rules
  to clarify, streamline and improve the amateur radio licensing,
  examination and accreditation frameworks" [verified FYSO PDF p58; work
  program table PDF p53, "Q1 2027"; draft March 2026]. Scope does not mention bands or power.
- **Higher power:** a mechanism for high-power use cases beyond scientific
  licences is "on our long-term amateur radio work agenda" — no date
  [verified FYSO p58]. Scientific licences (since 1 Jul 2023) already cover
  some high-power experiments (EME, TEP) — outside ohsradio's guard.
- **2300–2302 MHz:** spectrum licensees want it for wireless broadband;
  ACMA kept it at "initial investigation", to be reassessed in FYSO
  2027–32 [verified FYSO p34]. Risk that Advanced loses 2300–2302.
- **HAREC visitors:** planned arrangements for unlimited-duration operation
  and Australian call signs [AW1]; no instrument yet.
- **60 m:** no proposal found. ARSP allocates it; CL does not authorise it.
  **UNCONFIRMED** whether any consultation exists.
- **Foundation privileges:** no change since CL commenced (Table A is
  identical in LCD 2025 Sch 1, made Sep 2025). No proposal found to give
  Foundation 160 m/60 m/20 m/23 cm or more than 10 W. The 2024 UK-style
  Foundation uplift **did not happen in Australia** [verified CL Table A;
  FYSO lists only "minor" changes].
- **23 cm / GNSS (RR 5.332A, WRC-23):** possible future power restrictions
  if GNSS interference is reported [secondary W1 p22].
- **Re-check before each release:** Federal Register versions page for
  F2023L01648 (compilation number > 0 means amended), ACMA consultations
  page, final FYSO 2026–31, WIA band plan revision.

## 11. Confidence and gaps (every UNCONFIRMED item, what was found instead)

**High confidence [verified from the instrument text]:** every band edge,
power figure, unit and Column 3 limitation in §3 (CL Sch 2, cross-checked
against the identical LCD 2025 Sch 1); the (lower, upper] edge rule; 60 m
not authorised; identification every 10 min; unattended 10-minute timer;
RQZ 150 km exclusion; 3.4–3.6 GHz HCIS exclusion exists; visitor
365-day rule; CL unamended as of 2026-10-08; T/R 61-01 Advanced-only
equivalence.

**UNCONFIRMED / ambiguous:**
1. **"Radiated power" vs pX/pY.** CL s 17 says "radiated power"; Column 2
   uses RR pX/pY (transmitter-line powers; RR text itself not read here);
   ES says "transmitter output power limits". Found: no definition of
   "radiated power" in CL or INT. Guard should treat the figure as a cap on
   transmitter output (conservative either way).
2. **pX/pY definitions** were not read from the ITU RR (only INT's
   pointer). Standard RR 1.157/1.158 meanings assumed [secondary].
3. **HCIS cells of CL Sch 3** — list copied in the instrument, but mapping
   to coordinates needs the ACMA Australian Spectrum Map Grid 2012 (not
   fetched). Recommend refusing 3.4–3.6 GHz by default.
4. **Spectrum-licensed areas (CL s 18(2))** — which spectrum licences
   overlap amateur bands now was not established beyond 3.4 GHz.
5. **Visitor call-sign separator** (VK/… vs VK…) — instrument says "add the
   letters VK at the start"; separator not specified.
6. **Japanese 3rd/4th-class asterisk** in AW1 ("Telephone-only … above
   30 MHz with 10 watts maximum power") — legal effect vs Table C unclear.
7. **IARP / CITEL** — not checked; assumed not applicable.
8. **Repeater/beacon assignment rules (RALI AA1 etc.)** — not read.
9. **Final FYSO 2026–31** — only the March 2026 draft was read.
10. **Old Foundation mode/equipment restrictions removed 2020** — from a
    WIA news search snippet only [secondary]; irrelevant to the current law,
    which has none.
11. **23 cm repeater offset** — derived from segment positions only.
12. **ACMA web pages** were read from Internet Archive snapshots
    (Jun–Sep 2026), not live, because acma.gov.au timed out from this host.

**Biggest risks for the TX guard:**
- Treating **60 m** as allowed because ARSP allocates it — it is not in CL.
- Inferring the **class from a 3-letter call sign** — impossible since 2020.
- Missing the **PSD rule**: wideband modes (>8 kHz HF, >16 kHz on 10 m)
  are limited to 1 W/100 kHz on the "PSD" bands, and are outright
  forbidden on 3.776–3.8, 7.1–7.3 and 10.1–10.15 MHz above 8 kHz.
- Using the **J3E/R3E (C3F) high power figure for other modes** — FM,
  CW, data, AM get only 30 W pY (Standard) or 120 W pY (Advanced).
  Note C3F gets the higher figure only on Standard 50–52 MHz but on every
  Advanced row.
- **3.4–3.6 GHz** and the **WA Radio Quiet Zone** are location-dependent;
  without a position the guard must refuse 3.4–3.6 GHz and should warn
  that all TX is prohibited within 150 km of 26.704167 S 116.658889 E.
- **Lower band edges are excluded** (e.g. exactly 3.500 MHz, 144.000 MHz
  are outside), upper edges included.
- **Unattended FT8/WSPR robots** need the ≤10-minute shutdown timer.
- Future: the Q1 2027 class-licence consultation and the 2300–2302 MHz
  review could change the tables — re-check the Register before release.
