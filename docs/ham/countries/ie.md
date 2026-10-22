# Ireland (IE): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

PDFs downloaded 2026-10-08 with `curl -L -A <browser UA>` (HTTP 200),
converted with `pdftotext -layout`. irts.ie sits behind a JavaScript bot check
that curl cannot pass, so IRTS documents were taken from the Internet Archive
(`id_` raw captures) — the capture timestamp is given.

## Sources

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| C1 | ComReg, "Amateur Station Licence Guidelines", Reference: ComReg 09/45R6 | "Date: 29/05/2023"; 34 pages; PDF created 29 May 2023 | https://www.comreg.ie/media/2023/05/ComReg-0945R6.pdf | `9c6252ab5677f155726fcd71649593b4a125b245268db5e9bd28242ea280e3cb` | en |
| C0 | ComReg 09/45R5 (superseded, used only to see what R6 changed) | May 2023; 35 pages | https://www.comreg.ie/media/2023/05/ComReg-0945R5.pdf | `53af89a7f25440fadf05adf71d5fd317b9ac7162899ba8b5b304d17162b7adfa` | en |
| C2 | ComReg web page "Radio Amateurs" (links R6 as current; contest power table; visitor rules) | page metadata `dateModified` 2026-05-08; fetched 2026-10-08 | https://www.comreg.ie/industry/radio-spectrum/licensing/search-licence-type/radio-amateurs-2/ | `db0796d09136d9232c422d2f2ea166a2236e76bf014cc270b8ecd1173c90caa4` (HTML) | en |
| S1 | S.I. No. 192 of 2009, "Wireless Telegraphy (Amateur Station Licence) Regulations 2009" | in force 1 June 2009 | https://www.irishstatutebook.ie/eli/2009/si/192/made/en/print | `385089ed9c6a064e1afac755a01cbbdd318a9d72b8213a48b80d09ad77edd749` (HTML) | en |
| R1 | IRTS, "Irish 40–44 MHz (8 metre) Band Plan for Amateur Service" + "Irish 54.0–69.9 MHz (5 metre) Band Plan" | "V3.0 (13 October 2018)"; 2 pages | Archive capture 2021-05-05 of https://www.irts.ie/dnloads/Irish_8m_5m_band_plans.pdf | `a33a6a349918e7266e1dad07cd1175aeae0ab5c5952577f6580fe8accef17558` | en |
| R2 | IRTS, "Voice Repeaters in Ireland (sorted by output frequency)" | Archive capture 2026-06-06 13:23 UTC | http://web.archive.org/web/20260606132309/https://www.irts.ie/cgi/repeater.cgi | `392135629f8688430c36f08bd78b015e3923eda7a08a7ec1267652e7384e3316` (gzip as served) | en |
| I1 | IARU Region 1 HF band plan (2020; C1 A1.4 points to IARU-R1 plans; IRTS hosts copies "Updated October 2020") | 2020 | https://www.darc.de/fileadmin/filemounts/referate/hf/hf_r1_bandplan.pdf | `8deb428d565ce79a173d773ff2c0226201c09f0afbb2e46ef1a68729840835cf` | en |
| I2 | IARU Region 1 VHF Handbook | v10.03, Feb 2026, 133 pp. | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf | `147190bd1295cd9050dd735f7d8088f9dbeb1a30c228784fb91b611428caf631` | en |
| A1 | AMSAT-DL, "QO-100 NB Transponder Bandplan and Operating Guidelines" [secondary for licence purposes] | page 19.10.2018 | https://amsat-dl.org/en/p4-a-nb-transponder-bandplan-and-operating-guidelines | — | en |
| CT1 | CEPT, Recommendation T/R 61-01 "CEPT Radio Amateur Licence" (Annex 2 table of equivalence) | "Edition of 18 October 2024" (Annex 2 "Edition of 16 February 2024"); PDF created 29 Oct 2024; 13 pp. | https://docdb.cept.org/download/4541 (fetched with `curl -k`: the site's TLS chain does not verify) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| CT2 | CEPT, ECC/REC/(05)06 "CEPT Novice Radio Amateur Licence" (Annex 2) | "Edition 16 June 2023"; 10 pp. | https://docdb.cept.org/download/4372 (`curl -k`) | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` | en |

## 1. Regulator and legal instruments

- **Regulator:** Commission for Communications Regulation (ComReg / An
  Coimisiún um Rialáil Cumarsáide).
- **Law:** Wireless Telegraphy Act 1926, s.3 (licence required) [C1 1.1].
- **Regulations:** S.I. No. 192 of 2009, in force 1 June 2009 [S1 reg.1].
  Reg. 7(1)(b): the licensee "shall ensure that the Apparatus is used only on
  such radio frequency spectrum as may be specified in the Licence and such
  radio frequencies shall be used in an efficient manner having utmost regard
  to any guidelines that may be issued and amended by the Commission" [S1].
  The bands and powers are therefore set in **Part 2 of each licence**; ComReg
  publishes them as **Annex 1 (Tables 2 and 3) of ComReg 09/45R6** [C1
  pp.19–27], which "specif[ies] the general conditions attached to a Licence"
  [C1 A2.1]. 09/45R6 is the document to encode.
- **Current version:** 09/45R6, 29/05/2023 [C1]. ComReg's licensing page
  (modified 2026-05-08) still links R6 as current [C2]. R6 changed one thing
  that matters for code: R5 made IARU-R1 bandwidths, modes and usage binding
  ("shall be used"); **R6 withdrew that** — "where not specified in Tables 2
  and 3, ComReg no longer places any restriction on bandwidths, preferred modes
  or usage but rather encourages Licensees to take account of any applicable
  Irish national band plans and/or IARU band plans" [C1 A1.3 p.19; C0 A1.3].
- **Pending:** none found. A novice licence was floated by ComReg in 2021
  [secondary: EI7GL blog, Dec 2021] but nothing was enacted; C1 1.15 and C2
  still say ComReg "does not recognise Novice or Intermediate Licences".

## 2. Licence classes

| class id | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `cept1` | CEPT Class 1 Licence | HAREC (T/R 61-02) + Morse (5 wpm) [C1 2.3, A2.13] | T/R 61-01 CEPT licence | EI/EJ + digit 2–9 + 2-character suffix |
| `cept2` | CEPT Class 2 Licence | HAREC, no Morse [C1 2.3] | T/R 61-01 CEPT licence | EI/EJ + digit 2–9 + 3 characters ending in **B** |

**Both classes have exactly the same bands and powers**: "The frequency bands
specified in Tables 2 and 3 below are available for both CEPT Class 1 & CEPT
Class 2 Licence types" [C1 A1.2 p.19]. The distinction is Morse only. For the
guard, one class (`full`) is enough; keep both ids only for call-sign hints.
No novice/entry class exists [C1 1.15].

## 3. Permitted bands and power, per class

Source C1 Annex 1, Table 2 (HF, pp.20–23) and Table 3 (VHF and up, pp.23–26).
Power reference [C1 A2.10 p.30]: "All references to Peak Envelope Power
(P.E.P) for an Amateur Station power will be measured at the output of the
transmitter or R.F. Power Amplifier, if one is present. For measurement of
power in SSB mode, a 1 kHz tone shall be used". e.i.r.p. = PEP (dBW) + antenna
gain (dBi) [C1 A2.11–A2.12]; Annex 4 lets the licensee subtract feeder,
switch and matching losses [C1 p.34].

| lo Hz | hi Hz | band | status | cept1 / cept2 (same) | notes | source |
|---|---|---|---|---|---|---|
| 135700 | 137800 | 2200 m | Secondary | 1 W (0 dBW) EIRP | | C1 T2 p.20 |
| 472000 | 479000 | 630 m | Secondary | 5 W (7 dBW) EIRP | no harmful interference to aeronautical radionavigation / maritime; protect 490 kHz | C1 T2 p.20 |
| 1810000 | 1850000 | 160 m | Primary | 400 W (26 dBW) PEP | | C1 T2 p.21 |
| 1850000 | 2000000 | 160 m | Primary | 10 W (10 dBW) PEP | | C1 T2 p.21 |
| 3500000 | 3800000 | 80 m | Primary | 400 W (26 dBW) PEP | maritime mobile permitted; harbour islands 17 dBW | C1 T2 p.21 |
| 5000000–5500000 spot channels | | 60 m | Secondary | 200 W (23 dBW) PEP | **only** on spot frequencies 5.280, 5.300, 5.332, 5.348, 5.400, 5.405 MHz; emissions A1A, J3E, G1B; modes CW, SSB, PM | C1 T2 p.21 |
| 5351500 | 5366500 | 60 m | Secondary | 15 W (12 dBW) EIRP | WRC-15 band (RR 5.133B) | C1 T2 pp.21–22 |
| 7000000 | 7100000 | 40 m | Primary | 400 W (26 dBW) PEP | maritime mobile permitted; harbour islands 17 dBW | C1 T2 p.22 |
| 7100000 | 7200000 | 40 m | Primary | 400 W (26 dBW) PEP | as above | C1 T2 p.22 |
| 10100000 | 10130000 | 30 m | Secondary | 400 W (26 dBW) PEP | **"Morse Only"** | C1 T2 p.22 |
| 10130000 | 10150000 | 30 m | Secondary | 400 W (26 dBW) PEP | narrowband digimodes ≤ 500 Hz; no news bulletins; SSB only in safety-of-life emergencies | C1 T2 p.22 |
| 14000000 | 14350000 | 20 m | Primary | 400 W (26 dBW) PEP | maritime mobile permitted | C1 T2 p.22 |
| 18068000 | 18168000 | 17 m | Primary | 400 W (26 dBW) PEP | | C1 T2 p.23 |
| 21000000 | 21450000 | 15 m | Primary | 400 W (26 dBW) PEP | | C1 T2 p.23 |
| 24890000 | 24990000 | 12 m | Primary | 400 W (26 dBW) PEP | | C1 T2 p.23 |
| 28000000 | 29700000 | 10 m | Primary | 400 W (26 dBW) PEP | | C1 T2 p.23 |
| 30000000 | 49000000 | 8 m etc. | Secondary | 50 W (17 dBW) PEP | whole 30–49 MHz range | C1 T3 p.23 |
| 50000000 | 52000000 | 6 m | Secondary | 100 W (20 dBW) PEP | | C1 T3 p.24 |
| 54000000 | 69900000 | 5 m | Secondary | 50 W (17 dBW) PEP | | C1 T3 p.24 |
| 69900000 | 70500000 | 4 m | Secondary | 50 W (17 dBW) PEP, "Fixed Operation Only" | Notes column: "For Mobile Operation Max Power is 25W (14 dBW) P.E.P" — see 3.1 | C1 T3 p.24 |
| 144000000 | 146000000 | 2 m | Primary | 400 W (26 dBW) PEP | maritime mobile permitted | C1 T3 p.24 |
| 430000000 | 432000000 | 70 cm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.24 |
| 432000000 | 440000000 | 70 cm | Primary | 400 W (26 dBW) PEP | | C1 T3 p.24 |
| 1240000000 | 1300000000 | 23 cm | Secondary | 158 W (22 dBW) PEP | | C1 T3 p.24 |
| 2300000000 | 2400000000 | 13 cm | Secondary | 158 W (22 dBW) PEP | **stops at 2400** | C1 T3 p.24 |
| 2400000000 | 2450000000 | 13 cm | Secondary | **only by individual application**: 25 W (14 dBW) PEP, "AMSAT Restricted to Satellite Operation Only" | additional band, max 12 months | C1 A1.5 p.27 |
| 5570000000 | 5650000000 | 6 cm | Secondary | 158 W (22 dBW) PEP | | C1 T3 p.24 |
| 5650000000 | 5850000000 | 6 cm | Secondary | 158 W (22 dBW) PEP | | C1 T3 p.24 |
| 10000000000 | 10270000000 | 3 cm | Secondary | 158 W (22 dBW) PEP | | C1 T3 p.25 |
| 10270000000 | 10300000000 | 3 cm | — | **excluded** | "Licensees may not use the portion of the band between 10.270-10.300 GHz" | C1 T3 p.25 |
| 10300000000 | 10500000000 | 3 cm | Secondary | 158 W (22 dBW) PEP | 10450–10500 "used for Amateur Satellite Service" | C1 T3 p.25 |
| 24000000000 | 24050000000 | 1.2 cm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 47000000000 | 47200000000 | 6 mm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 76000000000 | 77500000000 | 4 mm | Secondary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 77500000000 | 78000000000 | 4 mm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 78000000000 | 81000000000 | 4 mm | Secondary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 134000000000 | 136000000000 | 2 mm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 136000000000 | 141000000000 | 2 mm | Secondary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 241000000000 | 248000000000 | 1 mm | Secondary | 50 W (17 dBW) PEP | | C1 T3 p.25 |
| 248000000000 | 250000000000 | 1 mm | Primary | 50 W (17 dBW) PEP | | C1 T3 p.26 |
| 1300000000 | 1304000000 | — | Secondary | individual application only: "0W (0 dBW) P.E.P", "Restricted to Repeater Operation Only" | **source is self-contradictory: 0 dBW = 1 W, not 0 W**; refuse | C1 A1.5 p.27 |

(The source is in English; cells are quoted as printed, e.g. "400W (26 dBW)
P.E.P", "15W (12 dBW) e.i.r.p.", "1W (0 dBW) e.i.r.p".)

### 3.1 Per-band exceptions

- **60 m — two regimes side by side** [C1 T2 pp.21–22]:
  1. Row "5000 – 5500": 200 W (23 dBW) PEP, "Transmission is restricted to the
     following spot frequencies: 5.280 MHz; 5.300 MHz; 5.332 MHz; 5.348 MHz;
     5.400 MHz and 5.405 MHz", "Emission Classification: A1A, J3E, G1B",
     "Modes: CW, SSB, PM". Whether the spot frequency is the carrier (USB dial)
     or the channel centre is **not stated [UNCONFIRMED]**; channel width is
     not stated.
  2. Row "5351.5-5366.5": 15 W (12 dBW) e.i.r.p., and the 5000–5500 row adds
     "Stations using the frequency band 5351.5-5366.5 kHz shall not exceed a
     maximum radiated power of 15 W (e.i.r.p.)". None of the spot frequencies
     falls in 5351.5–5366.5 [derived], so the two do not overlap.
- **30 m:** 10100–10130 kHz "Morse Only"; 10130–10150 ≤ 500 Hz digimodes; SSB
  only for emergency traffic [C1 T2 p.22]. These are licence conditions, not
  band plan — enforce.
- **4 m (69.9–70.5 MHz):** 50 W PEP; the power cell says "Fixed Operation
  Only" but the notes cell says "For Mobile Operation Max Power is 25W
  (14 dBW) P.E.P", and Note 7 says mobile max 17 dBW "with the exceptions of
  70.125 - 70.450 MHz where the Maximum Power shall be 14 dBW" [C1 pp.24, 27].
  **The source contradicts itself on whether mobile 4 m is allowed.** Safe
  encoding: fixed 50 W PEP; mobile 25 W PEP and only 70.125–70.450 MHz
  **[UNCONFIRMED interpretation]**.
- **Mobile (/M) on any band:** "The Maximum Power at the output of the
  transmitter or amplifier shall be 17 dBW" (50 W) [C1 Note 7 p.27].
- **Maritime mobile (/MM):** "The Maximum Power permitted when in maritime
  mobile mode shall be 10 dBW" (10 W) [C1 Note 8 p.27]; rows marked "Maritime
  Mobile Permitted" are 3.5, 7, 14, 18, 21, 24, 28 MHz and 144 MHz. Inland
  waterways count as maritime mobile [C1 5.7]. Mobile stations may not be
  used "within any estuary, dock, or harbour or in the vicinity of an airport"
  [C1 5.5].
- **Islands within harbour areas** (e.g. Spike Island): 17 dBW PEP [C1 Note 2
  p.26].
- **430–432 MHz:** 50 W PEP (vs 400 W above 432) [C1 T3 p.24].
- **13 cm:** 2300–2400 MHz by right; **2400–2450 MHz only by application**,
  satellite only, 25 W PEP [C1 A1.5].
- **3 cm:** 10.270–10.300 GHz excluded [C1 T3 p.25].
- **Bandwidth:** none set by licence except where a row says so (30 m, 60 m
  emissions) [C1 A1.3].
- **Contest power uplift (website, not in C1):** ComReg's page lists contests
  during which "licensed Radio Amateurs are temporarily permitted to transmit
  increased power for the duration of the contest": **1500 W** on 1.810–1.850,
  1.850–2.000, 3.5–3.8, 7.0–7.2, 14.00–14.35, 21.0–21.45, 28.0–29.7 MHz (band
  list varies per contest; IOTA and Scandinavian omit 160 m; ARRL 10 m is 28
  MHz only) and **1000 W** in VHF/UHF FD (144–146, 70.125–70.450, 50–52, 430–440,
  1240–1300 MHz) and CQWW VHF (144–146, 50–52) [C2]. "Transmission at the
  increased power outside of the contest date is not permitted". The table
  gives "Power (W)" with **no reference (PEP / EIRP) [UNCONFIRMED]** and no
  exact contest dates — encoding would need a contest calendar. Recommend:
  not encoded; mention in UI.
- **Additional bands / special events:** more frequencies or power by
  individual application, ≤ 12 months [C1 1.12, 3.5–3.8, A1.6].

### 3.2 Gaps: not permitted for any class (list explicitly)

- 5250–5450 kHz except the six spot channels and 5351.5–5366.5 kHz.
- 49–50 MHz; 52–54 MHz; 70.5–144 MHz; 146–430 MHz.
- 1300–2300 MHz (1300–1304 only by application, repeaters).
- **2400–2450 MHz without an individual authorisation**; 2450–5570 MHz —
  **no 9 cm (3.4 GHz) allocation at all**.
- 5850–10000 MHz; 10.270–10.300 GHz; 10.5–24.0 GHz; **24.05–24.25 GHz (not
  listed)**; 47.2–76 GHz; **122.25–123 GHz (not listed)**; 81–134 GHz; 141–241
  GHz; above 250 GHz.

## 4. Satellite / QO-100

- 2400–2450 MHz is **not in Table 3**. It is an "Additional Band" [C1 A1.5
  p.27]: "An individual application must be submitted to use any of the
  additional bands below which are for special events or for temporary
  experimental purposes" — row "2400-2450 / Secondary / 25W (14 dBW) P.E.P /
  A1A, A2A, A3E, R3E, H3E, J2B, J3E, J2F F1B, F2B, F3E, G1B / AMSAT /
  Restricted to Satellite Operation Only". Additional bands are granted "for a
  maximum period of twelve months" [C1 3.8].
- **So a QO-100 uplink in Ireland needs an individual, time-limited ComReg
  authorisation; limit 25 W PEP at the transmitter/PA output.** OpenHamShack should
  refuse 2400–2450 MHz unless the user declares that authorisation (a setting
  like the UK NoV), and then cap at 25 W PEP.
- 10.45–10.5 GHz: within 10.3–10.5 GHz, 158 W PEP, "10450-10500 MHz is used for
  Amateur Satellite Service" [C1 T3 p.25]. Receive-only QO-100 needs nothing.
- No other satellite sub-band is set in the licence; IARU plans apply
  voluntarily.
- QO-100 NB plan [A1]: uplink 2400.005–2400.490 MHz, "keep your signal below
  Beacon level".

## 5. CEPT / visiting operators

- C2: "TR/61-01 Signatories — non Novice or Intermediate Licence — EI/ home
  call-sign — no longer than 3 months". "Non TR/61-01 Signatories — >= 3 Months
  <= 1 Year — licence must be seen to be equivalent or reciprocal to TR/61-01
  Signatories — non Novice or Intermediate Licence."
- C1 3.1–3.4: visitors from non-T/R 61-01 countries need a Visitors Temporary
  Licence (€30, ≤ 12 months, not renewable, HAREC-equivalent only), call sign
  EIxVxx.
- **ECC Rec (05)06 (CEPT Novice) is not implemented** for visitors: ComReg
  "does not recognise novice or intermediate licences" [C1 3.2; C2]. A UK
  Foundation/Intermediate holder may not operate in Ireland.
- T/R 61-01 Annex 2 [CT1 p.6]: "Ireland — EI, EJ — 1 and 2" (footnote 8: "EJ is a special prefix for offshore islands"). Ireland is **absent** from the ECC/REC/(05)06 Annex 2 table [CT2 p.5], consistent with C1.
- Visitors under T/R 61-01 get the full Irish privileges (the only privileges
  there are) [derived — single class].
- HAREC (T/R 61-02): the Irish exam is HAREC, run by IRTS [C1 1.13, 1.16].

## 6. Callsigns

[C1 4.2–4.14, pp.12–15]
- "‘EI’ call-signs are used for Amateur Stations located on Ireland's mainland
  while ‘EJ’ call-signs are used for Amateur Stations located on any of the
  islands."
- **Class 1:** EI/EJ + digit 2–9 + C1 (0–9 or A–Z) + C2 (A–Z). e.g. EI7GL.
  Regex: `^E[IJ][2-9][0-9A-Z][A-Z]$`.
- **Class 2:** EI/EJ + digit 2–9 + C1 + C2 (0–9 or A–Z) + "B". e.g. EI4ABB.
  Regex: `^E[IJ][2-9][0-9A-Z]{2}B$`. (Older Class 2 calls may not follow
  this; hint only.) A class-2 → class-1 upgrade is the one case a call changes
  [C1 4.3].
- **Club:** EI + 0–9 + up to four characters, last a letter.
- **Automatic stations:** EI + band digit (0 = 28 MHz, 1 = 40 MHz, 2 = 145 MHz,
  4 = 70 MHz, 5 = 5 MHz, 6 = 50 MHz, 7 = 435 MHz, 8 = 1300 MHz, 9 = 10 GHz) + two
  location letters + type letter (D digital voice, P packet, X cross-band,
  G gateway, R analogue voice, H beacon, T TV). e.g. EI2TRR, EI7MLR.
- **Visitors:** EI/EJ + 2–9 + "V" + two characters.
- **Special event:** EI/EJ + 0–9 + up to four characters, last a letter.
- **Suffixes:** "/M" land mobile, "/MM" maritime mobile (incl. inland waters)
  [C1 5.3, 5.6]. "/P" is not mentioned in C1 [UNCONFIRMED whether required].
  Mobile and maritime stations must send their location at start/end and every
  30 minutes [C1 5.4, 5.9].
- Logbook is a licence condition, recording power in dBW or W [C1 6.1–6.2].

## 7. National band plan

ComReg points to the IARU-R1 plans [C1 A1.4]; IRTS hosts the IARU-R1 HF/VHF/
UHF plans (2020) and publishes its own plans only for the extra Irish bands
(8 m and 5 m) [R1]. IRTS coordinates repeaters [C1 Annex 3]. So: **HF, 6 m,
4 m, 2 m, 70 cm, 23 cm and up = IARU-R1** (see the UK document and [I1]/[I2]
for the segment tables), plus the Irish specifics below.

### HF
IARU-R1 2020 plan [I1] unchanged. Licence overrides: 30 m CW-only below
10130 kHz (law); 60 m only the six spot channels + WRC-15 band.

### 8 m (40–44 MHz) — IRTS plan V3.0, 13 Oct 2018 [R1 p.1]

| lo–hi MHz | max BW | usage |
|---|---|---|
| 40.000–40.100 | 1000 Hz | **lower beacon band** (40.013 Ireland planned) |
| 40.100–40.200 | 500 Hz | CW; 40.150 CW calling; 40.190–40.200 future intercont. CW |
| 40.200–40.300 | 2700 Hz | CW/SSB; 40.200 future DX calling; 40.250 SSB calling; 40.285 cross-band |
| 40.300–40.400 | 2700 Hz | MGM/narrow; 40.305 PSK; 40.310–.320 EME; 40.320–.380 MS |
| 40.400–40.660 | 20 kHz | all modes; 40.410 SSTV; 40.440–.480 FM gateways; **40.490–40.510 NOT TO BE USED** (3rd harmonic near 121.5 MHz); 40.520–.650 digital; 40.600 DV calling |
| 40.660–40.680 | 1000 Hz | upper beacon band |
| 40.680–40.700 | 2700 Hz | SSB channels 40.681–40.696 (ISM-only countries) |
| 40.700–43.000 | 20 kHz | 40.710–40.890 rpt inputs (outputs 41.810–41.990, **input 1.1 MHz below output**); 41.210–41.390 rpt inputs paired with outputs 56.810–56.990 (cross-band, 15.6 MHz); 41.410–41.590 FM/DV simplex, **41.500 FM calling**; 42.000–43.000 simplex 12.5 kHz, 42.500 calling |
| 43.000–45.000 | 500 kHz | all modes (licence ends at 49 MHz) |

### 5 m (54–69.9 MHz) — IRTS V3.0 [R1 p.2]

| lo–hi MHz | max BW | usage |
|---|---|---|
| 54.000–56.000 | 500 kHz | all modes |
| 56.000–58.000 | 20 kHz | 56.010–56.090 rpt inputs (outputs 57.810–57.890, input 1.8 MHz below); 56.100–56.800 digital; 56.810–56.990 rpt outputs (inputs 41.210–41.390) |
| 58.000–59.500 | 20 kHz | 58.000–58.475 FM/DV simplex; **58.500 FM calling**; 58.540–.580 gateways; 58.610 SSTV; 58.620–.750 digital; 58.630 DV calling |
| 59.500–59.600 | 2700 Hz | MGM/narrow; 59.505 PSK; 59.510–.520 EME; 59.520–.580 MS |
| 59.600–59.700 | 2700 Hz | SSB/CW general; 59.685 cross-band |
| 59.700–59.800 | 2700 Hz | 59.710–.750 intl SSB DX; 59.710 intl SSB calling; 59.750 national SSB calling |
| 59.800–59.900 | 500 Hz | CW exclusive; 59.850 national CW calling; 59.870–.890 intl CW DX; 59.890 intl CW calling |
| **59.900–60.100** | 1000 Hz | **beacon band** (60.013 Ireland planned) |
| 60.100–69.900 | 8 MHz | experimental broadband, centre 65.00 |

### 6 m / 4 m
IARU-R1 [I2 pp.35–37]. 6 m beacons exclusive 50.400–50.500; R1 6 m repeaters:
inputs 51.210–51.390 with outputs either 50.710–50.890 (−500 kHz, Novi Sad
2020) or 51.810–51.990 (+600 kHz). 4 m (70.000–70.500): 70.000–70.090 beacons,
70.100–70.250 CW/SSB (70.200 centre), 70.250–70.294 AM/FM (70.260 calling),
70.294–70.500 FM channels 12.5 kHz (70.450 FM calling). Irish 4 m practice from
R2: simplex "simplexers" on 70.375 and 70.475 MHz; 4 m links on 70.2875 and
70.400 MHz.

### 2 m
IARU-R1 [I2 p.38]. Irish repeaters (R2, June 2026) are all **RV48–RV63:
outputs 145.600–145.7875 MHz, inputs 145.000–145.1875 MHz, input 600 kHz
below output**. Satellite exclusive 145.806–146.000; beacons
144.400–144.490.

### 70 cm — Irish practice (from the IRTS repeater list, R2) [secondary to a plan, but IRTS-published]

Three repeater systems are in use in Ireland (output → input):
- **RU66–RU78: outputs 430.825–430.975 MHz, inputs 438.425–438.575 MHz —
  input 7.6 MHz ABOVE output** (reverse of the German use of the same
  pairs). e.g. RU76 EI7MLR out 430.950 / in 438.550.
- **RU240–RU268 (= UK RB0–RB14): outputs 433.000–433.350, inputs
  434.600–434.950 — input 1.6 MHz above output.**
- Digital: DVU-R20–R24 outputs 430.250–430.300, inputs 439.250–439.300
  (+9 MHz); RU668 out 438.600 / in 431.000 (−7.6 MHz); GB7DN (NI) out
  439.4125 / in 430.4125 (−9 MHz).
- Licence: 430–432 MHz is only 50 W PEP.
- IARU-R1 [I2 pp.41–42]: satellites 435–438; beacons 432.400–432.490; SSB
  centre 432.200; FM calling 433.500; DV calling 433.450.

### 23 cm and up
IARU-R1 [I2 p.45]: RM0–RM19 inputs 1291.000–1291.475, outputs 1297.000–1297.475
(input 6 MHz below output); beacons 1296.800–1296.994; narrowband centre
1296.200. No Irish 23 cm repeater found in R2 [UNCONFIRMED whether any
exist].

### Differences from IARU R1 (for code)

1. Ireland has **8 m (40–44 MHz) and 5 m (54–69.9 MHz)** plans that do not
   exist in R1 (licence covers 30–49 and 54–69.9 MHz).
2. 70 cm Irish 7.6 MHz repeaters put the **output at 430.8–431.0 and input at
   438.4–438.6** — opposite to R1 footnote (f) HB/DL/OE usage (input 431.05–431.99,
   output 438.65–439.59).
3. 70 cm 1.6 MHz pairs follow the UK RB scheme (output 433, input 434.6), the
   reverse of the R1 plan's 433.000–433.3875 inputs / 434.600–434.9875 outputs.
4. 30 m: the licence forbids non-CW below 10130 kHz (R1 only recommends).
5. 60 m: six fixed spot channels + WRC-15 band, not R1's 60 m segment plan.

## 8. Confidence and gaps

**Overall: high** for licence bands/powers (one primary PDF, every row read
with page numbers; ComReg's page confirms R6 is still current in 2026);
**medium** for band plan (Ireland has no national plan for 2 m/70 cm beyond
IARU-R1; repeater conventions taken from the IRTS list via an archive
capture).

UNCONFIRMED / to re-check:
- 60 m spot frequencies: carrier vs centre, and allowed bandwidth.
- 4 m mobile: the R6 row says "Fixed Operation Only" and also gives a mobile
  power; encode conservatively.
- 1300–1304 MHz "0W (0 dBW)" — internally inconsistent; refuse.
- Contest power uplift (1500 W / 1000 W): reference (PEP?) and dates not given;
  not encoded.
- Whether "/P" portable suffix is required — C1 is silent.
- The IRTS's own 2 m/70 cm plan document (if any beyond IARU-R1) could not be
  fetched; irts.ie blocks scripted access.
- No pending ComReg changes found; R6 dated 29/05/2023.
