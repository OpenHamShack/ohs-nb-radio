# Generic IARU Region 1, 2 and 3 band plans

Compiled 2026-10-08. This is the source document for the fallback plans
used when a country has no national plan written (`ohsradio/plans/`). It
covers the bands OpenHamShack HAM uses: 160, 80, 60, 40, 30, 20, 17, 15, 12 and
10 m, 6 m, 4 m (R1 only), 2 m, 70 cm, 23 cm, 13 cm, 9 cm and 6 cm. The UK
plan, with its own sources, is in `bandplan-r1-uk.md`. This document reuses
that file's keys I1 to I3 for the same IARU Region 1 documents.

Every row carries a source key and page number. All three plans were read
from the PDFs themselves, which were downloaded on the fetch date shown.

How to read the markers:

- **[unverified]**: not confirmed from a primary source.
- **[derived]**: worked out here, not stated in a source.
- **(as printed)**: the source says this, although it looks like a typo
  or contradicts another row. The figure is copied unchanged, and the
  likely meaning is given separately.

**Two kinds of rule, with different weight.** The ITU Radio Regulations
(T1) and the national licence are law. The three IARU plans are voluntary
codes of practice: each one says so, and each defers to national rules
(see "What the code should do with these" below).

**Re-check before each release.** R1 revises its plans at its triennial
General Conference; the next one was not found published at the fetch
date. R2's band planning committee can now amend its plan between
assemblies, after 60 days without objection (N2). R3 revises at its
triennial conference, last held in November 2024.

## Sources

All were fetched on **2026-10-08**. The sha256 is that of the PDF as
downloaded.

| Key | Document (issuing body) | Version / effective date | URL | Size, sha256 |
|---|---|---|---|---|
| I1 | "IARU Region 1 HF Band Plan", edited by DF5JL (IARU Region 1, HF Committee C4) | **"Effective from 16 OCT 2020"** (Novi Sad virtual General Conference), 4 pages. The PDF was created 6 Jun 2021; its metadata subject reads "Bandplan geändert nach Cavtat (nur 7 MHz)". | https://www.iaru-r1.org/wp-content/uploads/2021/06/hf_r1_bandplan.pdf | 152,466 B, `8deb428d565ce79a173d773ff2c0226201c09f0afbb2e46ef1a68729840835cf` |
| I2 | "IARU-R1 VHF Handbook" (IARU Region 1, VHF/UHF/SHF Committee C5) | **Version 10.03, February 2026** (confirmed on its cover, p. 1). 132 printed pages; the PDF has 133 and was modified 18 Feb 2026. Page numbers below are the printed "n / 132" numbers. | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf | 2,184,161 B, `147190bd1295cd9050dd735f7d8088f9dbeb1a30c228784fb91b611428caf631` |
| I3 | The separate R1 VHF, UHF and SHF band-plan sheets (IARU R1 C5) | Each is headed "Effective December 2020 (VGC Novi Sad)". The C5 page itself notes that the UHF sheet's 432 MHz plan is "still based on outdated VHF Handbook 9.01". **Superseded by I2 and not used for rows.** | https://www.iaru-r1.org/wp-content/uploads/2020/12/VHF-Bandplan.pdf, …/2021/03/UHF-Bandplan.pdf, …/2020/12/SHF-Bandplan.pdf | VHF 48,406 B `f99ab6dc…c6f7`; UHF 45,037 B `9ded9995…b509`; SHF 35,642 B `30963816…df10` |
| I5 | IARU R1 web pages "Band plans", "Documents HF" and "VHF & up bandplanning" | The band-plans page was last updated 9 Jun 2021. Its HF entry says that after approval by the Novi Sad 2020 conference the modifications "became effective at 16 October 2020". None of the three pages lists a later HF plan. | https://www.iaru-r1.org/on-the-air/band-plans/ ; https://www.iaru-r1.org/about-us/committees-and-working-groups/hf-committee-c4/documents-hf/ ; https://www.iaru-r1.org/about-us/committees-and-working-groups/vhf-uhf-shf-committee-c5/vhf-up-bandplanning/ | (HTML) |
| N1 | "IARU Region 2 Band Plan" (IARU Region 2) | Title page: **"September 2020"**, 21 pages. It incorporates the Oct 2019 Lima General Assembly change, which adds satellite uplinks at 21125–21450 kHz. The PDF was regenerated 18 Oct 2022 (Ghostscript; HTTP Last-Modified 18 Oct 2022). It is the plan the R2 "Band plans" page links ("Updated on October 4, 2020"). | https://www.iaru-r2.org/wp-content/uploads/2020/02/IARU-Region-2-Band-plan.pdf (index: https://www.iaru-r2.org/en/reference/band-plans/) | 200,883 B, `e8c85d051a2a928479bd1ef1f820cc32308fa795074f3b4a700e51d7262c6dcb` |
| N2 | IARU R2 and ARRL news pages: "Revised IARU Region 2 Band Plan Now Available" (4 Oct 2020); ARRL "IARU Region 2 Releases 2020 Revision of its Band Plan" (60-day objection procedure); ARRL on the 20th GA (Lima, ended 3 Oct 2019); "XXII General Assembly of IARU-R2" (Salvador, Brazil, 6–10 Oct 2025) | The 2025 GA report lists no band-plan change. | https://www.iaru-r2.org/en/revised-iaru-region-2-band-plan-now-available/ ; https://www.arrl.org/news/iaru-region-2-releases-2020-revision-of-its-band-plan ; https://arrl.org/news/20th-international-amateur-radio-union-region-2-general-assembly-held-in-peru ; https://www.iaru-r2.org/en/xxii-general-assembly-of-iaru-r2/ | (HTML) |
| P1 | "IARU Region 3 Band Plan", Document R3-004 (IARU Region 3) | **"Rev. 2: November 2024"**, "Agreed by 19th IARU Region 3 Conference, November 06th, 2024" (Bangkok, 4–8 Nov 2024), 21 pages. The PDF was created 23 Jan 2025. Its pages carry no numbers; page numbers below are PDF pages. | https://iaru-r3.org/wp-content/uploads/2025/01/R3-004-Band-Plans-IARU-Region-3.pdf | 290,479 B, `7d351c62ca91b2accea547c45c83316b0779701ce72affcc39c32616adbf5070` |
| P2 | IARU R3, "HF Band Plan Committee 40m Band Plan Harmonisation Project" | 4 Oct 2024. A proposal for the 19th Conference only; nothing was adopted. | https://www.iaru-r3.org/2024/iaru-region-3-hf-band-plan-committee-40m-band-plan-harmonisation-project/ | (HTML) |
| T1 | ITU, "Radio Regulations, edition of 2024, Volume 1: Articles", Article 5 (Table of Frequency Allocations) | 2024 edition (WRC-23), in force 1 Jan 2025. PDF modified 30 Aug 2024. Page numbers below are PDF pages; the printed "RR5-n" page is given where useful. | https://search.itu.int/history/HistoryDigitalCollectionDocLibrary/1.49.48.en.101.pdf | 2,684,920 B, `040907a35846479b1f34ba628e35964dd4ce6d2b3fc05c2ff9b45e8ff215f5de` |

**Version check for R1 HF.** No R1 HF plan later than 16 Oct 2020 was
found. The 26th General Conference was held at Zlatibor, Serbia, on
1–4 Nov 2023. (The brief called it "Zürich 2023"; it was Zlatibor.) Its
agenda included an "HF Bandplan" item and a C4 draft. A German conference
summary records only a recommendation that a working group continue the
digital-mode plan review with the other regions. Neither I5 nor the PDF
at I1 shows a newer plan.

So **I1 (effective 16 Oct 2020) is used as current.** If Zlatibor 2023
adopted HF changes, they have not been published in a new plan document
[unverified that none were adopted].

---

## 0. Summary: where the regions differ

### Allocations [T1]

- **Band edges.** Each region's band edges differ under the ITU table, not
  only under the band plans:

  | Band | R1 | R2 | R3 |
  |---|---|---|---|
  | 160 m | 1810–1850 primary; 1850–2000 only by footnote 5.96 in listed countries, 10 W mean [T1 p.60–61] | 1800–2000 [T1 p.61] | 1800–2000 [T1 p.61] |
  | 80 m | 3500–3800 [T1 p.65] | **3500–4000** [T1 p.65] | **3500–3900** [T1 p.65] |
  | 40 m | 7000–7200 [T1 p.69] | **7000–7300**; 7200–7300 subject to 5.142 [T1 p.69] | 7000–7200 [T1 p.69] |
  | 2 m | **144–146** [T1 p.90] | 144–148 [T1 p.90] | 144–148 [T1 p.90] |
  | 70 cm | 430–440, AMATEUR **primary** (shared with radiolocation) [T1 p.103] | 430–440 **secondary**. 420–430 and 440–450 only by 5.270 (Australia, USA, Jamaica, Philippines) and 5.284 (Canada, 440–450) [T1 p.103–105] | 430–440 **secondary** [T1 p.103] |

- **6 m.** R1 has 50–52 MHz, **secondary**, under broadcasting, with many
  national exceptions (5.166A–5.169B). R2 and R3 have 50–54 MHz primary
  [T1 p.82–84].
- **4 m (70 MHz)** has **no Article 5 allocation in any region**. In CEPT
  it exists only through ECA9 (69.9–70.5 MHz, secondary, national) [I2 p.34,
  p.37]. R2 and R3 plans have no 4 m band.
- **9 cm.** R2 and R3 have 3300–3500 MHz secondary. **In R1 there is no
  regional amateur allocation:** footnote 5.431 adds 3400–3475 MHz for
  Germany only [T1 p.136, p.138]. The R1 plan still plans 3400–3475 for
  countries that permit it [I2 p.49].
- **6 cm.** All regions have 5650–5850 MHz secondary; R2 adds 5850–5925
  [T1 p.148].

### The band plans

- **IBP beacons.** All three protect 14100, 18110, 21150, 24930 and 28200
  kHz, but with different widths:
  - **R1:** ±1 kHz "Beacons exclusively", and 28190–28225 kHz is wholly
    beacons [I1 p.1–2].
  - **R2:** ±1 kHz "IBP (exclusive)"; the 10 m exclusive part is only
    28199–28201, inside a 28190–28225 beacon segment [N1 p.8–10].
  - **R3:** only "500 Hz guard band for beacons" around each frequency
    [P1 p.8–12].
- **Maximum bandwidth.**
  - **R1:** 200 / 500 / 2700 Hz on HF.
  - **R2:** the same, plus AM at 6 kHz where marked (*) [N1 p.1].
  - **R3:** 200 / 500 / 2700 Hz. "Phone" is defined as up to 6 kHz, and
    up to 25 kHz on 50 MHz and above [P1 p.4].
  - **R3 6 m:** the Nov 2024 conference **removed the bandwidth limit on
    50.5–54 MHz** [P1 p.1, p.13].
- **FT8, WSPR and JT65 dials** are listed **only by R3** [P1 p.5–13]. R1
  (I1, I2) and R2 (N1) list none.
- **Emergency centres** differ by region:
  - **R1:** 3760, 7110, 14300, 18160, 21360 [I1 p.1–2]
  - **R2:** 3750, 3985, 7060, 7240, 7275, 14300, 18160, 21360 [N1 p.6–9]
  - **R3:** 3600, 7110, 14300, 18160, 21360 ("all modes ±5 kHz")
    [P1 p.6–10]
- **2 m repeaters.**
  - **R1:** inputs 144.975–145.194 and outputs 145.575–145.794. Each output
    is 600 kHz above its input, so the radio transmits 600 kHz below the
    output [derived from the channel edges; I2 p.38–39].
  - **R2:** 600 kHz splits, 144.6–145.5 and 146–148 [N1 p.11–12].
  - **R3:** no repeater sub-bands; 144.035–145.8 is "All modes" [P1 p.14].
- **70 cm.**
  - **R1:** a detailed plan, with 12.5 kHz repeater systems at 1.6, 2.0
    and 7.6 MHz shifts [I2 p.41–44].
  - **R2:** plans only 420–435.
    - 420–432 is ATV.
    - 432–433.1 is weak signal and beacons.
    - 433.1–435 and 438–450 are "Local Option".
    - 435–438 is satellite (exclusive) [N1 p.13].
  - **R3:** four coarse segments [P1 p.15].
- **Satellite at 21 MHz.** All three now have satellite uplinks at
  21125–21450 kHz on a non-exclusive basis [I1 p.4; N1 p.9; P1 p.10].
  P1's own footnote (2), "No amateur satellite allocation has been made in
  the R1 and R2 bandplan", is out of date.
- **Contest-free bands.**
  - **R1:** 5, 10, 18 and 24 MHz [I1 p.3].
  - **R2:** 136 kHz, 472 kHz, 60, 30, 17 and 12 m [N1 p.2].
  - **R3:** names the contest bands instead: 160, 80, 40, 20, 15 and 10 m
    [P1 p.4].
- **Bands a plan leaves undivided or silent:**
  - R2 and R3 have no 4 m band.
  - R3 30 m starts at **10110** (as printed): 10100–10110 is unplanned,
    although it is allocated [P1 p.7; T1 p.71].
  - R1 1850–2000 kHz is planned although only some R1 countries have it.
  - R2 70 cm 438–450 and 433.1–435, and 23 cm and up, carry large "Local
    Option" or unspecified-bandwidth blocks.
  - R3 above 2 m is mostly "All modes" with no bandwidth.

---

## 1. ITU Article 5 allocations for the app's bands [T1]

Status codes:

- **P**: primary
- **P\***: primary, shared with other primary services
- **S**: secondary
- **fn**: only by a country footnote

Footnotes that restrict the amateur service in named countries are listed
where they matter; the rest are omitted.

| Band | Region 1 | Region 2 | Region 3 | Page |
|---|---|---|---|---|
| 160 m | 1810–1850 P (5.98–5.100 restrict some countries); 1850–2000 fn 5.96 (listed countries, ≤200 kHz, mean power ≤10 W) | 1800–1850 P; 1850–2000 P\* (fixed, mobile, radiolocation, radionav) | 1800–2000 P\* (fixed, mobile, radionav) | p.60–62 (RR5-16) |
| 80 m | 3500–3800 P\* (fixed, mobile) | 3500–3750 P (5.119: Peru also fixed/mobile); 3750–4000 P\* | 3500–3900 P\* (fixed, mobile) | p.65–66 |
| 60 m | 5351.5–5366.5 S, ≤15 W EIRP (5.133B) | same; Mexico ≤20 W, listed R2 countries ≤25 W EIRP | same, ≤15 W EIRP | p.67–68 |
| 40 m | 7000–7100 P (amateur and amateur-satellite); 7100–7200 P | as R1, plus 7200–7300 P (5.142: must not constrain broadcasting in R1/R3) | as R1 | p.69 |
| 30 m | 10100–10150 S | same | same | p.71 |
| 20 m | 14000–14250 P (amateur and amateur-satellite); 14250–14350 P (5.152: fixed in some countries) | same | same | p.73 |
| 17 m | 18068–18168 P (amateur and amateur-satellite) | same | same | p.75 |
| 15 m | 21000–21450 P (amateur and amateur-satellite) | same | same | p.75 |
| 12 m | 24890–24990 P (amateur and amateur-satellite) | same | same | p.77 |
| 10 m | 28000–29700 P (amateur and amateur-satellite) | same | same | p.78 |
| 6 m | 50–52 S under broadcasting. 5.166A: 50–50.5 P in AT, CY, VA, HR, DK, ES, FI, HU, LV, NL, CZ, UK, SK, SI. 5.169: 50–54 P in southern Africa. 5.166B/C: field-strength limit, no protection from wind profilers | 50–54 P | 50–54 P (5.167 and 5.167A: not amateur in BD, BN, IN, IR, PK, SG; shared in ID, TH; 5.168 shared with broadcasting in AU, CN, KP) | p.82–84 |
| 4 m | none (CEPT ECA9: 69.9–70.5 S, national [I2 p.34]) | none | none | n/a |
| 2 m | 144–146 P (amateur and amateur-satellite) | 144–146 P; 146–148 P (5.217: not amateur in AF, BD, CU, GY, IN) | 144–146 P; 146–148 P\* (fixed, mobile) | p.90–91 |
| 70 cm | 430–440 P\* (with radiolocation); amateur-satellite 435–438 under 5.282 | 430–440 S (5.278: P in AR, BR, CO, CR, CU, GY, HN, PA, PY, UY, VE); 420–430 and 440–450 fn 5.270 (US, JM) and 5.284 (CA, 440–450) | 430–440 S; 420–430 and 440–450 fn 5.270 (AU, PH) | p.103–105 |
| 23 cm | 1240–1300 S; 1260–1270 amateur-satellite uplink only (5.282); 5.332A protect RNSS (GNSS) | same | same | p.112, p.114 |
| 13 cm | 2300–2450 S; 2400–2450 amateur-satellite (5.282) | same | same | p.130 |
| 9 cm | **none** (5.431: 3400–3475 S in Germany only) | 3300–3500 S; 3400–3410 amateur-satellite (5.282) | 3300–3500 S; 3400–3410 amateur-satellite (5.282) | p.136, p.138 |
| 6 cm | 5650–5850 S; 5650–5670 amateur-satellite up only (5.282); 5830–5850 amateur-satellite down (S) | 5650–5925 S; same satellite segments | 5650–5850 S; same satellite segments | p.148 |

Satellite operation under 5.282 is on a non-interference basis: "subject
to not causing harmful interference to other services" [T1 p.105]. P1
repeats this as "Permitted on a non-interference basis" in each band
[P1 p.15–18].

---

## 2. Encoding conventions [derived]

How each plan's vocabulary maps onto the code's mode classes `{cw, ssb,
am, fm, digi, dv, image}` and kinds `"" | beacon | satellite | output`.

The mapping is mine; the plans' own definitions are cited.

| Plan term | Source definition | Classes |
|---|---|---|
| R1 "CW" | (column) | cw |
| R1 "Narrow band modes" | "All modes using up to 500 Hz bandwidth, including CW, RTTY, PSK, etc." [I1 p.3] | cw, digi |
| R1 "All modes" | "CW, Phone and those other modes listed as Centres of Activity, plus AM" [I1 p.3] | cw, ssb, am, digi, dv, image. Add fm only where the bandwidth allows it (29–29.7 MHz) |
| R1 VHF "Telegraphy" / "MGM" / "SSB" | MGM is machine-generated modes | cw / digi / ssb |
| R1 VHF "FM / Digital voice" | | fm, dv |
| R1 VHF "ALL MODE(S)" | | all seven classes |
| R1 "ATV / Digital ATV" | | image (wideband). The code's image class means SSTV and fax, so ATV is out of scope for a narrowband rig |
| R2 "CW" / "DM" / "SSB" / "FM, DV" | DM: "Any mode devoted to digital data communication" [N1 p.2] | cw / digi / ssb / fm, dv |
| R2 "All modes" | | all seven classes; AM only where BW is marked (*), at 6 kHz [N1 p.1] |
| R3 "CW" / "Narrowband modes" | Narrowband: "CW, RTTY, PSK, JT65, WSPR, FT8, SIM31 … not exceeding 500Hz" [P1 p.4] | cw / cw, digi |
| R3 "Digimodes" | [P1 p.4] | digi |
| R3 "Phone" | "SSB, DSB AM, FM and Digital Voice modes … not exceeding 6 kHz. On 50 MHz and above … not exceed 25 kHz" [P1 p.4] | ssb, am, fm, dv |
| R3 "All modes" | "Any mode fitting in the specified bandwidth" [P1 p.3] | all seven classes |
| R3 "WB" | "Wide bandwidth modes including FM" [P1 p.4] | fm, plus wideband |

- **Bandwidth.** Every plan defines maximum bandwidth at the −6 dB points
  [N1 p.2; P1 p.3]. Where a plan gives no figure, encode `None`. That
  means unlimited by the plan; the national limit still applies.
- **Frequencies** in R1 and R2 are transmitted frequencies, not
  suppressed-carrier dial frequencies [I1 p.3; N1 p.3]. An LSB voice signal
  must therefore sit wholly above the segment's lower edge.
- **Lowest LSB dial in R1:** 1843, 3603, 7053 kHz.
- **Highest USB dial on R1 60 m:** 5363 kHz.
- **Highest USB dial on 20–10 m in R1:** 3 kHz below the band edge
  [I1 p.3].
- **Sideband (all three plans):** LSB below 10 MHz, USB above; USB on
  60 m [I1 p.3; N1 p.4; P1 p.4].
- **CW** is accepted across every band except beacon segments [I1 p.3;
  N1 p.2]. R2 also says "preferably not … in repeater inputs".

---

## 3. IARU Region 1

### 3.1 HF [I1]

All figures are in kHz, from the plan effective 16 Oct 2020. Pages:
p.1 covers 1.8–14 MHz, p.2 covers 18–28 MHz, p.3 has the definitions and
notes, and p.4 the history.

"ACDS" means "automatically controlled data stations (unattended)".

#### 160 m (I1 p.1)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1810 | 1838 | 200 | cw | | CW |
| 1838 | 1840 | 500 | cw, digi | | Narrow band modes |
| 1840 | 1843 | 2700 | all modes | | All modes; digimodes. Lowest LSB dial is 1843 |
| 1843 | 2000 | 2700 | all modes | | All modes |

Centre of activity: **1836 CW QRP**.

The 1850–2000 part is not allocated in most of R1 (see §1).

#### 80 m (I1 p.1)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 3500 | 3510 | 200 | cw | | CW; priority for intercontinental operation |
| 3510 | 3560 | 200 | cw | | CW; CW contest preferred |
| 3560 | 3570 | 200 | cw | | CW |
| 3570 | 3580 | 200 | cw, digi | | Narrow band; digimodes |
| 3580 | 3590 | 500 | cw, digi | | Narrow band; digimodes |
| 3590 | 3600 | 500 | cw, digi | | Narrow band; digimodes, ACDS |
| 3600 | 3620 | 2700 | all modes | | Digimodes, ACDS. Lowest LSB dial is 3603 |
| 3600 | 3650 | 2700 | all modes | | SSB contest preferred (overlaps the previous row, as printed) |
| 3650 | 3700 | 2700 | all modes | | |
| 3700 | 3775 | 2700 | all modes | | SSB contest preferred |
| 3775 | 3800 | 2700 | all modes | | SSB contest preferred; priority for intercontinental operation |

Centres of activity:

- 3555 CW QRS
- 3560 CW QRP
- 3630 Digital Voice
- 3690 SSB QRP
- 3735 Image
- **3760 R1 Emergency**

#### 60 m (I1 p.1, notes p.3)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 5351.5 | 5354.0 | 200 | cw, digi | | CW, narrow band modes |
| 5354.0 | 5366.0 | 2700 | all modes | | All modes; USB for voice. Highest USB dial is 5363 |
| 5366.0 | 5366.5 | 20 | digi | | "Weak signal narrow band modes", printed "20 (!)" |

The plan's notes for this band [I1 p.3]:

- The 60 m details are "proposed usage" (LA17_C4_REC_02).
- Use the WRC-15 band only "if there are no other frequencies available
  at 5 MHz under domestic (ITU-R article 4.4) permissions".
- Local nets and rag-chews should not use it.
- No contests.
- ITU limit: 15 W EIRP [T1 p.68].

#### 40 m (I1 p.1)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 7000 | 7040 | 200 | cw | | CW |
| 7040 | 7047 | 500 | cw, digi | | Narrow band; digimodes |
| 7047 | 7050 | 500 | cw, digi | | Narrow band; digimodes, ACDS |
| 7050 | 7053 | 2700 | all modes | | Digimodes, ACDS. Lowest LSB dial is 7053 |
| 7053 | 7060 | 2700 | all modes | | Digimodes |
| 7060 | 7100 | 2700 | all modes | | SSB contest preferred |
| 7100 | 7130 | 2700 | all modes | | |
| 7130 | 7175 | 2700 | all modes | | SSB contest preferred |
| 7175 | 7200 | 2700 | all modes | | SSB contest preferred; priority for intercontinental activity |

Centres of activity:

- 7030 CW QRP
- 7070 Digital Voice
- 7090 SSB QRP
- **7110 Region 1 Emergency**
- 7165 Image

#### 30 m (I1 p.1)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 10100 | 10130 | 200 | cw | | CW |
| 10130 | 10150 | 500 | cw, digi | | Narrow band; digimodes |

There is no SSB segment. The only centre of activity is **10116 CW QRP**.
Contests are not allowed.

#### 20 m (I1 p.1)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 14000 | 14060 | 200 | cw | | CW; CW contest preferred |
| 14060 | 14070 | 200 | cw | | CW |
| 14070 | 14089 | 500 | cw, digi | | Narrow band; digimodes |
| 14089 | 14099 | 500 | cw, digi | | Narrow band; digimodes, ACDS |
| **14099** | **14101** | none | (none) | **beacon** | "International Beacon Project — Beacons exclusively" |
| 14101 | 14112 | 2700 | all modes | | Digimodes, ACDS |
| 14112 | 14125 | 2700 | all modes | | |
| 14125 | 14300 | 2700 | all modes | | SSB contest preferred |
| 14300 | 14350 | 2700 | all modes | | |

Centres of activity:

- 14055 QRS
- 14060 CW QRP
- 14130 Digital Voice
- 14195 ±5 priority for DXpeditions
- 14230 Image
- 14285 SSB QRP
- **14300 Global Emergency**

#### 17 m (I1 p.2)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 18068 | 18095 | 200 | cw | | CW |
| 18095 | 18105 | 500 | cw, digi | | Digimodes |
| 18105 | 18109 | 500 | cw, digi | | Digimodes, ACDS |
| **18109** | **18111** | none | (none) | **beacon** | IBP, beacons exclusively |
| 18111 | 18120 | 2700 | all modes | | Digimodes, ACDS |
| 18120 | 18168 | 2700 | all modes | | |

Centres of activity:

- 18086 CW QRP
- 18130 SSB QRP
- 18150 Digital Voice
- **18160 Emergency**

#### 15 m (I1 p.2; satellite note p.4)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 21000 | 21070 | 200 | cw | | CW |
| 21070 | 21090 | 500 | cw, digi | | Digimodes |
| 21090 | 21110 | 500 | cw, digi | | Digimodes, ACDS |
| 21110 | 21120 | 2700 | cw, digi, dv, image (**not SSB**) | | "All modes … Digimodes, ACDS, (not SSB)" |
| 21120 | 21149 | 500 | cw, digi | | Narrow band modes |
| **21149** | **21151** | none | (none) | **beacon** | IBP, beacons exclusively |
| 21151 | 21450 | 2700 | all modes | | |

Centres of activity:

- 21055 QRS
- 21060 QRP
- 21180 Digital Voice
- 21285 SSB QRP
- 21340 Image
- **21360 Global Emergency**

The 2020 history note says 21125–21450 is designated for amateur
satellites "on a non-exclusive basis, noting that frequencies above
21400 kHz are clearly preferred" [I1 p.4]. That makes it a shared segment,
not satellite-only.

#### 12 m (I1 p.2)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 24890 | 24915 | 200 | cw | | CW |
| 24915 | 24925 | 500 | cw, digi | | Digimodes |
| 24925 | 24929 | 500 | cw, digi | | Digimodes, ACDS |
| **24929** | **24931** | none | (none) | **beacon** | IBP, beacons exclusively |
| 24931 | 24940 | 2700 | all modes | | Digimodes, ACDS |
| 24940 | 24990 | 2700 | all modes | | |

Centres of activity: 24906 CW QRP, 24950 SSB QRP, 24960 Digital Voice.

#### 10 m (I1 p.2)

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 28000 | 28070 | 200 | cw | | CW |
| 28070 | 28120 | 500 | cw, digi | | Digimodes |
| 28120 | 28150 | 500 | cw, digi | | Digimodes, ACDS |
| 28150 | 28190 | 500 | cw, digi | | Narrow band modes |
| **28190** | **28199** | none | (none) | **beacon** | IBP, "Regional time shared beacons, exclusively" |
| **28199** | **28201** | none | (none) | **beacon** | IBP, "Worldwide time shared beacons, exclusively" |
| **28201** | **28225** | none | (none) | **beacon** | IBP, "Continuous duty beacons, exclusively" |
| 28225 | 28300 | 2700 | all modes | | "All modes — Beacons" (shared, not exclusive) |
| 28300 | 28320 | 2700 | all modes | | Digimodes, ACDS |
| 28320 | 29000 | 2700 | all modes | | |
| 29000 | 29100 | none ("unrestricted") | all modes + fm | | |
| 29100 | 29200 | none | all modes + fm | | FM simplex, 10 kHz channels |
| 29200 | 29300 | none | all modes + fm | | Digimodes, ACDS |
| 29300 | 29510 | none | all | **satellite** | "Satellite Links" (downlink restriction removed 2014) |
| **29510** | **29520** | (none) | (none) | guard | "Guard Channel" |
| 29520 | 29590 | 6000 | all modes + fm | | FM repeater input, RH1–RH8 |
| 29590 | 29610 | 6000 | all modes + fm | | 29600 FM calling channel; 29610 FM simplex repeater (parrot, input and output) [derived row edges; the plan gives only spot frequencies] |
| 29620 | 29700 | 6000 | all modes + fm | **output** | FM repeater output, RH1–RH8 (RH1 = 29520/29620, RH8 = 29590/29690 [I1 p.4]) |

Centres of activity:

- 28055 QRS
- 28060 QRP
- 28330 Digital Voice
- 28360 SSB QRP
- 28680 Image

#### R1 HF notes [I1 p.3]

- **AM** "may be used in the telephony sub-bands providing consideration is
  given to adjacent channel users". This conflicts with the printed
  2700 Hz limit; the code should warn rather than refuse [derived].
- **Unattended stations.** "any unmanned transmitting stations on HF shall
  only be activated under operator control, except for beacons agreed with
  the IARU Region 1 Beacon Coordinator".
- **Contest-free bands:** 5, 10, 18 and 24 MHz.
- **No FT8 or other digital dial frequencies** are listed.

### 3.2 6 m: 50–54 MHz [I2 p.35–36]

All figures are in MHz. R1's allocation is only 50–52 MHz, secondary;
many countries hold less (§1). The table follows the plan.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| **50.000** | **50.030** | 500 Hz | (none) | **beacon** | Reserved for the Synchronised Beacon Project: 50.000–.010 R1, .010–.020 R2, .020–.030 R3 |
| 50.030 | 50.100 | 500 Hz | cw | | "Telegraphy exclusive (except Beacon Project)". 50.050 future international CW centre; 50.090 intercontinental CW centre |
| 50.100 | 50.130 | 2700 Hz | cw, ssb | | Intercontinental section; 50.110 intercontinental centre (footnote a: not for calling within Europe) |
| 50.130 | 50.200 | 2700 Hz | cw, ssb | | International section; 50.150 international centre |
| 50.200 | 50.300 | 2700 Hz | cw, ssb | | General usage; 50.285 crossband |
| 50.300 | 50.400 | 2700 Hz | cw, digi | | MGM and narrowband telegraphy. 50.305 PSK; 50.310–.320 EME; 50.320–.380 meteor scatter |
| **50.400** | **50.500** | 1000 Hz | (none) | **beacon** | "Beacons exclusive" |
| 50.500 | 50.700 | none | all modes | | 50.540–.580 simplex FM/DV gateways; 50.600–.700 digital communications; 50.630 DV calling |
| 50.700 | 50.900 | 12 kHz | fm, dv | **output** | 50.710–50.890 FM/DV repeater outputs (the −500 kHz option, Novi Sad 2020) |
| 50.900 | 51.200 | none | all modes | | Wideband digital experiments, note (e) |
| 51.200 | 51.400 | 12 kHz | fm, dv | | 51.210–.390 repeater inputs |
| 51.400 | 52.000 | none | all modes | | 51.410–.590 FM/DV simplex; 51.510 FM calling. 51.810–.990 repeater outputs (the older +600 kHz option): kind **output** for that sub-range |
| 52.000 | 54.000 | 500 kHz | all modes | | Where allocated, plan as 4 × 500 kHz blocks (note f) |

Wideband experiments, note (e):

- maximum 50 kHz in 50.5–50.7;
- maximum 500 kHz in 51.4–52.0;
- maximum 200 kHz in a segment printed "50.9-50.2" (as printed; probably
  50.9–51.2 [derived]).

The plan accepts legacy MGM below 50.300, "but effort should be made to
move this to 50.300 – 50.400" [I2 p.36].

### 3.3 4 m: 70.0–70.5 MHz (R1 only, national) [I2 p.37]

There is no ITU allocation. Under CEPT ECA9, administrations "may
authorise all or parts of the band 69.9-70.5 MHz" on a secondary basis.
The code should offer this band only when the country's own plan says so
[derived].

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| **70.000** | **70.090** | 1000 Hz | (none) | **beacon** | Coordinated beacons (telegraphy, MGM) |
| **70.090** | **70.100** | 1000 Hz | (none) | **beacon** | Temporary and personal beacons |
| 70.100 | 70.250 | 2700 Hz | cw, ssb, digi | | 70.185 crossband; **70.200 CW/SSB centre**; 70.250 meteor scatter |
| 70.250 | 70.294 | 12 kHz | am, fm | | **70.260 AM/FM calling**; 70.270 MGM centre |
| 70.294 | 70.500 | 12 kHz | fm, digi | | FM channels at 12.5 kHz spacing. 70.3125 and 70.3250 digital; **70.4500 FM calling**; 70.4625, 70.4750; 70.4875 digital |

The plan does not say "exclusive" for the 70 MHz beacon segments. Treat
them as beacon segments by usage [derived].

### 3.4 2 m: 144–146 MHz [I2 p.38–40]

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 144.000 | 144.025 | 2700 Hz | all | **satellite** | "Satellites (downlinks only)" (Varna 2014). No transmission below 144.0025 (footnote r) |
| 144.025 | 144.100 | 500 Hz | cw | | Telegraphy. **144.050 CW centre**; 144.100 random meteor scatter. Footnote a: telegraphy exclusive 144.000–144.110 |
| 144.100 | 144.150 | 500 Hz | cw, digi | | 144.110–144.160 CW and MGM EME |
| 144.150 | 144.400 | 2700 Hz | cw, ssb, digi | | **144.300 SSB centre** |
| **144.400** | **144.490** | 500 Hz | (none) | **beacon** | "Beacons exclusive" |
| 144.491 | 144.493 | 500 Hz | digi | | Personal weak-signal MGM beacons; experimental MGM |
| 144.500 | 144.794 | 20 kHz | all | | 144.500 image centre (SSTV, fax); 144.600 data centre; 144.750 ATV talkback. No unmanned stations here except linear transponders and ARDF beacons (footnote f) |
| 144.794 | 144.9625 | 12 kHz | digi, dv | | MGM and digital communications. **144.800 APRS**; 144.8125–144.8625 DV internet voice gateways |
| 144.975 | 145.194 | 12 kHz | fm, dv | | "Repeater Input exclusive" |
| 145.194 | 145.206 | 12 kHz | fm, dv | | Space communication (footnote p: 145.200 simplex, or 145.200/145.800 split, for manned spacecraft) |
| 145.206 | 145.5625 | 12 kHz | fm, dv | | 145.2375, 145.2875, 145.3375 FM internet gateways; **145.375 DV calling**; **145.500 FM calling** |
| 145.575 | 145.7935 | 12 kHz | fm, dv | **output** | "Repeater Output exclusive" |
| 145.794 | 145.806 | 12 kHz | fm, dv | | Space communication (footnote p) |
| **145.806** | **146.000** | 12 kHz | all | **satellite** | "Satellite exclusive" |

- **General note i:** "In Europe no input or output channels of telephony
  repeaters shall be allowed to operate between 144.000 and 144.794 MHz."
- **Missing footnote:** the 144.000 row cites footnote "(s)", which the
  handbook does not define; footnote r is the guard-band rule (as
  printed).
- **Pairing [derived]:** the channel edges imply a 600 kHz shift, with
  each output 600 kHz above its input. The rows above do not state this.

### 3.5 70 cm: 430–440 MHz [I2 p.41–44]

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 430.000 | 431.975 | none | all | | "Sub-regional (national) bandplanning". 430.025–.375 FM repeater outputs (F/PA/ON, 1.6 MHz shift): kind **output** for that sub-range. 430.400–.575 digital links; 430.600–.925 digital repeaters; 430.925–431.025 multimode; 431.050–431.9875 R1 repeater inputs (7.6 MHz shift); 431.625–.975 inputs (F/PA/ON) |
| 432.000 | 432.400 | 2700 Hz | all (narrow) | | **432.050 CW centre**; **432.200 SSB centre**; 432.350 microwave talkback; 432.370 meteor scatter |
| **432.400** | **432.490** | 500 Hz | (none) | **beacon** | "Beacons exclusive" |
| 432.491 | 432.493 | 500 Hz | digi | | Experimental MGM |
| 432.500 | 432.975 | none | all | | **432.500 APRS** ("NEW APRS FREQUENCY"); 432.600–.9875 R1 repeater inputs (25 kHz spacing, 2 MHz shift); in the UK these are outputs |
| 433.000 | 433.375 | none | fm, dv | | Repeater inputs (12.5 kHz spacing, 1.6 MHz shift); in the UK these are outputs |
| 433.400 | 433.5875 | — | fm, dv | | Simplex, 25 kHz spacing. 433.400 SSTV (FM/AFSK); **433.450 DV calling**; **433.500 FM calling** |
| 433.600 | 434.000 | none | all | | 433.625–.775 digital communications; 434.000 centre of digital experiments |
| 434.000 | 434.5875 | none | all | | Digital communications by exception (434.450–.575); LoRa (note p: 125 kHz maximum) |
| 434.600 | 434.9875 | none | all | **output** | R1 repeater outputs (12.5 kHz spacing, 1.6 or 2.0 MHz shift); in the UK these are inputs |
| 435.000 | 436.000 | none | all | **satellite** | Satellite service |
| 436.000 | 438.000 | none | all | **satellite** | Satellite service and digital TV. 437.000 DATV/data centre. DATV simplex and repeater inputs are allowed; no repeater outputs, gateways or fixed infrastructure; "the Satellite Service shall have priority" (§1.5.4) |
| 438.000 | 440.000 | none | all | | 438.025–.175 digital; 438.200–.525 digital repeaters; 438.550–.625 multimode. 438.650–439.5875 R1 repeater outputs (7.6 MHz shift): kind **output** for that sub-range. 439.800–.975 digital links |

Plan notes:

- Analogue ATV is no longer permitted in 430–440 MHz from 1 Jan 2021
  (VGC2020).
- No telephony repeaters between 432.000 and 432.600 MHz.
- Common FM simplex internet gateway frequencies: 433.950–434.050
  (note n).
- Countries without the full band may use repeater channels with inputs at
  431.225–431.600 and outputs at 432.825–433.200 (note r).

### 3.6 23 cm: 1240–1300 MHz [I2 p.45–47]

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1240.000 | 1240.500 | 2700 Hz | all | | Reserved for future (alternative narrowband section, CT08_C5_27) |
| **1240.500** | **1240.750** | 500 Hz | (none) | **beacon** | Beacons (reserved for future) |
| 1240.750 | 1241.000 | 20 kHz | fm, dv | | Reserved for future |
| 1241.000 | 1243.250 | 20 kHz | all | | 1240–1241 digital communications. 1242.025–1242.700 repeater outputs RS1–RS28: kind **output** for that sub-range. 1242.725–1243.250 digital |
| 1243.250 | 1260.000 | national | image (ATV) | | ATV and DATV. 1258.150–1259.350 repeater outputs R20–R68 |
| 1260.000 | 1270.000 | national | all | **satellite** | Satellite service (uplink only [T1 p.105; I2 p.101]) |
| 1270.000 | 1272.000 | 20 kHz | all | | 1270.025–.700 repeater inputs RS1–RS28; 1270.725–1271.250 digital |
| 1272.000 | 1290.994 | national | image (ATV) | | ATV and DATV |
| 1290.994 | 1291.481 | 20 kHz | fm, dv | | Repeater inputs RM0–RM19 (1291.000–1291.475, 25 kHz) |
| 1291.494 | 1296.000 | national | all | | 1293.150–1294.350 repeater inputs R20–R68 |
| 1296.000 | 1296.150 | 500 Hz | cw, digi | | 1296.000–.025 moonbounce |
| 1296.150 | 1296.800 | 2700 Hz | cw, ssb, digi | | **1296.200 narrowband centre**; 1296.400–.600 linear transponder input; 1296.500 image; 1296.600 narrowband data; 1296.600–.700 transponder output; 1296.741–.743 experimental MGM; 1296.750–.800 local beacons (10 W ERP maximum) |
| **1296.800** | **1296.994** | 500 Hz | (none) | **beacon** | "Beacons exclusive" |
| 1296.994 | 1297.481 | 20 kHz | fm, dv | **output** | Repeater outputs RM0–RM19 (1297.000–1297.475) |
| 1297.494 | 1297.981 | 20 kHz | fm, dv | | Simplex SM20–SM39. **1297.500 FM centre**; **1297.725 DV calling**; 1297.900–.975 FM internet gateways |
| 1298.000 | 1299.000 | 20 kHz | all | | Mixed analogue or digital, 25 kHz channels |
| 1299.000 | 1299.750 | 150 kHz | all | | 5 × 150 kHz high-speed data channels |
| 1299.750 | 1300.000 | 20 kHz | all | | 8 × 25 kHz FM/DV channels |

The "national" bandwidth comes from footnote d: "Bandwidth limits
according to national regulations".

The plan also says: "During contests and band openings, local traffic
using narrow-band modes should operate between 1296.500 - 1296.800 MHz."

### 3.7 13 cm: 2300–2450 MHz [I2 p.48]

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 2300.000 | 2320.000 | 20 kHz | all | | Sub-regional (national) planning. Alternative narrowband segments 2304–2306 (where 2320–2322 is unavailable) and 2308–2310 ("in HB") |
| 2320.000 | 2320.800 | — | all | | 2320.000–.025 EME; **2320.200 SSB centre**; 2320.750–.800 local beacons (10 W ERP maximum) |
| **2320.800** | **2321.000** | — | (none) | **beacon** | "BEACONS EXCLUSIVE" |
| 2321.000 | 2322.000 | 20 kHz | fm, dv | | Voice simplex and repeaters |
| 2322.000 | 2400.000 | — | all | | 2322–2355 ATV; 2355–2365 digital; 2365–2370 repeaters; 2370–2392 ATV; 2392–2400 digital |
| 2400.000 | 2450.000 | — | all | **satellite** | Amateur Satellite Service. 2400–2402 alternative narrowband; **2400.500 centre**; 2400.800–2401.000 coordinated narrowband beacons; 2427–2443 ATV "if no satellite uses this segment" |

### 3.8 9 cm: 3400–3475 MHz [I2 p.49]

This band is national only in R1 (§1).

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 3400.000 | 3400.800 | — | all | | **3400.100 centre of activity and EME** (moved from 3456, note b); 3400.750–.800 local beacons |
| **3400.800** | **3400.995** | — | (none) | **beacon** | "BEACONS ONLY" |
| 3401.000 | 3402.000 | — | all | | |
| 3402.000 | 3410.000 | — | all | **satellite** | "SATELLITE DOWNLINKS" (only some R1 countries have the satellite allocation, note c) |
| 3410.000 | 3475.000 | — | all | | |

### 3.9 6 cm: 5650–5850 MHz [I2 p.50]

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 5650.000 | 5670.000 | — | all | **satellite** | Amateur satellite uplink. **5668.200 narrowband centre** (in 5668–5670) |
| 5670.000 | 5700.000 | — | digi | | MGM |
| 5700.000 | 5760.000 | — | all | | |
| 5760.000 | 5760.800 | 2700 Hz | all | | **5760.200 narrowband centre**; 5760.750–.800 local beacons |
| **5760.800** | **5760.990** | — | (none) | **beacon** | "BEACONS ONLY" |
| 5761.000 | 5830.000 | — | all | | "Any wideband system shall protect narrowband applications, which have priority" (note d) |
| 5830.000 | 5850.000 | — | all | **satellite** | Amateur satellite downlink |

---

## 4. IARU Region 2 [N1]

All figures are in kHz up to 10 m and in MHz above. N1 is a "voluntary
band plan … Operators are cautioned to consult all applicable national
plans and regulatory documents before transmitting" [N1 p.1].

"ACDS" means automatically controlled data stations. They are allowed
only where a segment names them [N1 p.1].

"(\*)" means DSB AM is allowed at up to 6 kHz.

### 4.1 HF

#### 160 m (N1 p.5–6)

The band is primary in R2; radiolocation and radionavigation are also
primary at 1850–2000.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1800 | 1810 | 500 | digi | | DM |
| 1810 | 1830 | 200 | cw | | CW |
| 1830 | 1839 | 200 | cw | | CW; DX window |
| 1839 | 1840 | 200 | cw, digi | | DX window; ACDS |
| 1840 | 1843 | 2700 | cw, ssb, digi (DM ≤200 Hz) | | SSB DX window |
| 1843 | 1850 | 2700 | cw, ssb | | SSB DX window |
| 1850 | 2000 | 2700 (\*) | all modes | | |

Centres of activity: 1812 CW QRP, 1910 SSB QRP.

#### 80 m (N1 p.6)

The band is primary. The plan notes that shortwave broadcasting from R1
and R3 may be heard above 3800 kHz, and that some R2 countries do not
permit the whole band.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 3500 | 3510 | 200 | cw | | DX window |
| 3510 | 3560 | 200 | cw | | CW contest preferred |
| 3560 | 3570 | 200 | cw | | |
| 3570 | 3580 | 200 | cw, digi | | |
| 3580 | 3590 | 500 | cw, digi | | |
| 3590 | 3600 | 500 | cw, digi | | ACDS |
| 3600 | 3625 | 2700 (\*) | all modes | | ACDS |
| 3600 | 3650 | 2700 | all modes | | SSB contest preferred (overlaps the previous row, as printed) |
| 3650 | 3700 | 2700 | all modes | | |
| 3700 | 3775 | 2700 | all modes | | SSB contest preferred |
| 3775 | 3800 | 2700 | all modes | | DX window |
| 3800 | 3875 | 2700 | all modes | | |
| 3875 | 3900 | 2700 (\*) | all modes | | |
| 3900 | 4000 | 2700 | all modes | | |

Centres of activity:

- 3555 CW QRS
- 3560 CW QRP
- 3690 SSB QRP
- 3735 Image
- **3750 Emergency**
- 3845 Image
- 3885 AM
- **3985 Emergency**

#### 60 m (N1 p.7)

The band is secondary in R2. "Not all countries in Region 2 have approved
operations in this band yet, and some specify different frequencies".

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 5351.5 | 5354 | 500 | cw, digi | | |
| 5354 | 5366 | 2700 | all modes | | USB is best practice |
| 5366 | 5366.5 | 20 | cw, digi | | ACDS |

Avoid the band for local nets (footnote 1). No contests. ITU limits:
15 W EIRP, 20 W in Mexico, 25 W in the listed countries [T1 p.68].

#### 40 m (N1 p.7)

The band is primary. 7200–7300 "shall not impose constraints on the
broadcasting service intended for use within Region 1 and Region 3".

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 7000 | 7025 | 200 | cw | | DX window |
| 7025 | 7040 | 200 | cw | | |
| 7040 | 7047 | 500 | cw, digi | | |
| 7047 | 7050 | 500 | cw, digi | | ACDS |
| 7050 | 7053 | 2700 | all modes | | ACDS |
| 7053 | 7060 | 2700 | all modes | | |
| 7060 | 7100 | 2700 | all modes | | SSB contest preferred |
| 7100 | 7130 | 2700 (\*) | all modes | | |
| 7130 | 7200 | 2700 (\*) | all modes | | SSB contest preferred |
| 7200 | 7300 | 2700 (\*) | all modes | | |

Centres of activity:

- 7030 QRP
- **7060 R2 Emergency** (printed in the 7053–7060 row; it is the segment's top edge)
- 7070 DV
- 7090 SSB QRP
- 7165 Image
- **7240 R2 Emergency**
- **7275 R2 Emergency**
- 7285 SSB QRP
- 7290 AM

#### 30 m (N1 p.8)

The band is secondary. The plan says "CW Beacons should be avoided".

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 10100 | 10130 | 200 | cw | | |
| 10130 | 10140 | 500 | cw, digi | | ACDS |
| 10140 | 10150 | 2700 | cw, digi | | (as printed: 2700 Hz, but CW and DM only) |

Centre of activity: 10116 CW QRP. No contests.

#### 20 m (N1 p.8)

The band is primary and exclusive.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 14000 | 14025 | 200 | cw | | DX window |
| 14025 | 14060 | 200 | cw | | CW contest preferred |
| 14060 | 14070 | 200 | cw | | |
| 14070 | 14089 | 500 | cw, digi | | |
| 14089 | 14099 | 500 | cw, digi | | ACDS |
| **14099** | **14101** | 200 | (none) | **beacon** | "IBP (exclusive)" |
| 14101 | 14112 | 2700 | all modes | | ACDS |
| 14112 | 14190 | 2700 | all modes | | SSB contest preferred |
| 14190 | 14200 | 2700 | all modes | | SSB DX window; contest preferred |
| 14200 | 14285 | 2700 | all modes | | SSB contest preferred |
| 14285 | 14300 | 2700 (\*) | all modes | | |
| 14300 | 14350 | 2700 | all modes | | |

Centres of activity:

- 14055 CW QRS
- 14060 CW QRP
- 14230 Image
- 14285 SSB QRP and AM calling
- **14300 Global Emergency**

#### 17 m (N1 p.9)

The band is primary and exclusive.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 18068 | 18095 | 200 | cw | | |
| 18095 | 18105 | 500 | cw, digi | | |
| 18105 | 18109 | 500 | cw, digi | | ACDS |
| **18109** | **18111** | 200 | (none) | **beacon** | IBP (exclusive) |
| 18111 | 18120 | 2700 | all modes | | ACDS |
| 18120 | 18168 | 2700 | all modes | | |

Centres of activity: 18086 CW QRP, 18130 QRP, **18160 Global Emergency**.

#### 15 m (N1 p.9)

The band is primary and exclusive.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 21000 | 21070 | 200 | cw | | |
| 21070 | 21090 | 500 | cw, digi | | |
| 21090 | 21110 | 500 | cw, digi | | ACDS |
| 21110 | 21120 | 2700 | cw, digi | | ACDS |
| 21120 | 21149 | 500 | all modes (≤500 Hz) | | (as printed) |
| **21149** | **21151** | 200 | (none) | **beacon** | IBP (exclusive) |
| 21151 | 21380 | 2700 | all modes | | |
| 21380 | 21450 | 2700 (\*) | all modes | | |

Centres of activity:

- 21060 CW QRP
- 21285 SSB QRP
- 21340 Image
- **21360 Global Emergency**

Footnote 2: "Amateur Satellite uplink signals are permitted in the
subband 21125 to 21450 kHz on a non-exclusive basis … shall avoid causing
interference to the … IBP".

#### 12 m (N1 p.10)

The band is primary and exclusive.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 24890 | 24915 | 200 | cw | | |
| 24915 | 24925 | 500 | cw, digi | | |
| 24925 | 24929 | 500 | cw, digi | | ACDS |
| **24929** | **24931** | 200 | (none) | **beacon** | IBP (exclusive) |
| 24931 | 24940 | 2700 | all modes | | ACDS |
| 24940 | 24990 | 2700 | all modes | | |

Centres of activity: 24906 CW QRP, 24950 SSB QRP.

#### 10 m (N1 p.10)

The band is primary and exclusive.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 28000 | 28070 | 200 | cw | | |
| 28070 | 28120 | 500 | cw, digi | | |
| 28120 | 28150 | 500 | cw, digi | | ACDS |
| 28150 | 28190 | 500 | cw, digi | | |
| **28190** | **28225** | 200 | (none) | **beacon** | "Beacons, IBP (exclusive) 28199-28201 kHz" |
| 28225 | 28300 | 2700 | all modes | | Beacons (shared) |
| 28300 | 28320 | 2700 | all modes | | ACDS |
| 28320 | 29000 | 2700 | all modes | | |
| 29000 | 29200 | 6000 | all modes + fm | | AM preferred |
| 29200 | 29300 | 6000 | all modes + fm | | ACDS |
| 29300 | 29510 | 6000 | all | **satellite** | Satellite |
| **29510** | **29520** | — | (none) | guard | "Guard band, no transmission allowed" |
| 29520 | 29590 | 6000 | fm, dv | | "Repeater inputs (exclusive)", 10 kHz channels |
| 29590 | 29620 | 6000 | fm, dv | | **29600 FM calling** |
| 29620 | 29700 | 6000 | fm, dv | **output** | Repeater outputs, "9 channels of 10 kHz from 29620 to 26690 kHz" (as printed; means 29690 [derived]) |

Centres of activity:

- 28055 CW QRS
- 28060 CW QRP
- 28330 DV
- 28360 SSB QRP
- 28680 Image

The whole 28190–28225 segment is encoded as a beacon segment, as the plan
gives it: a 200 Hz CW beacon segment whose exclusive IBP part is
28199–28201.

### 4.2 6 m: 50–54 MHz [N1 p.11]

The band is primary and exclusive in R2.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 50.000 | 50.100 | 500 Hz | cw | **beacon** (shared) | "CW — Beacons" (not marked exclusive) |
| 50.100 | 50.125 | 2700 Hz | cw, ssb | | DX window. "Calling QRG (exclusive) 50.110 MHz" |
| 50.125 | 50.400 | 2700 Hz | cw, ssb, digi | | **50.305 PSK centre** |
| 50.400 | 50.500 | 2700 Hz (\*) | all modes | **beacon** (shared) | "Beacons, ACDS (Digital Beacons)" |
| 50.500 | 50.600 | 2700 Hz (\*) | all modes | | ACDS |
| 50.600 | 50.800 | 12 kHz | all modes | | ACDS |
| 50.800 | 51.000 | 12 kHz | all modes | | Radio remote control (20 kHz channels) |
| 51.000 | 51.110 | 2700 Hz | cw, ssb | | DX window |
| 51.110 | 51.480 | 12 kHz | fm, dv | | "Repeater inputs (exclusive)", 10 kHz channels from 51.120 (output +500 kHz, as printed "+500 Hz") |
| 51.500 | 51.600 | 12 kHz | fm, dv | | Simplex |
| 51.620 | 51.980 | 12 kHz | fm, dv | **output** | Repeater outputs (input −500 kHz, as printed "−500 Hz") |
| 52.000 | 52.100 | 12 kHz | fm, dv | | Internet voice gateways (IVG), 10 kHz channels |
| 52.100 | 54.000 | 12 kHz | all modes | | |

N1 names no FM calling frequency on 6 m.

### 4.3 2 m: 144–148 MHz [N1 p.11–12]

The band is primary and exclusive in R2.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 144.000 | 144.025 | 2700 Hz | all | **satellite** | Satellites. Satellites must not transmit below 144.0025 (note 1) |
| 144.000 | 144.110 | 500 Hz | cw | | EME and weak signal (overlaps the row above, as printed) |
| 144.110 | 144.150 | 2700 Hz | cw, digi | | EME and weak signal |
| 144.150 | 144.180 | 2700 Hz | cw, ssb, digi | | Weak signal |
| 144.180 | 144.275 | 2700 Hz | cw, ssb | | Weak signal. "Calling QRG (exclusive) 144.200 MHz" |
| 144.275 | 144.300 | 500 Hz | cw | **beacon** | "Beacons" (not marked exclusive) |
| 144.300 | 144.360 | 2700 Hz | cw, ssb | | Calling QRG 144.300 |
| 144.360 | 144.400 | 12 kHz | digi | | ACDS. **144.390 APRS** |
| 144.400 | 144.500 | 500 Hz | cw, digi | **beacon** | Beacons; ACDS (digital beacons). 144.490 ISS FM voice uplink (note 2) |
| 144.500 | 144.600 | — | — | | Local option |
| 144.600 | 144.900 | 12 kHz | fm, dv | | "Repeater inputs (exclusive)" (output +600 kHz) |
| 144.900 | 145.000 | 12 kHz | fm, dv | | Weak signal (as printed) |
| 145.000 | 145.100 | 12 kHz | all | | ACDS, IVG (10 kHz channels). 145.010 must be protected for APRS in the Caribbean (note 3) |
| 145.100 | 145.200 | — | — | | Local option |
| 145.200 | 145.500 | 12 kHz | fm, dv | **output** | Repeater outputs (input −600 kHz) |
| 145.500 | 145.790 | 12 kHz | all | | |
| **145.790** | **145.800** | — | (none) | guard | "Guard band, no transmission allowed" |
| **145.800** | **146.000** | 12 kHz | all | **satellite** | "Satellites (exclusive)" |
| 146.000 | 146.390 | 12 kHz | fm, dv | | "Repeater inputs (exclusive)" (output +600 kHz), channels 146.01–146.37 |
| 146.390 | 146.600 | 12 kHz | fm, dv | | **146.520 FM calling** |
| 146.600 | 146.990 | 12 kHz | fm, dv | **output** | Repeater outputs (input −600 kHz). Printed "last channel 144.970 MHz" (as printed; means 146.970 [derived]) |
| 146.990 | 147.400 | 12 kHz | fm, dv | | "Repeater inputs (exclusive) (output +600 kHz) (first channel 147.000 MHz)" |
| 147.400 | 147.590 | 12 kHz | fm, dv | | |
| 147.590 | 148.000 | 12 kHz | fm, dv | **output** | Repeater outputs (input −600 kHz) |

N1's 147.0–147.4 = inputs, 147.6–148.0 = outputs is the reverse of common
US practice. In the US, 147.0–147.4 MHz are usually repeater outputs with
inputs 600 kHz higher [unverified: no primary source fetched]. The code
should not hard-refuse either side; national plans (for example the
ARRL's) will override this [derived].

### 4.4 70 cm: 420–450 MHz [N1 p.13]

The band is secondary in R2. 420–430 and 440–450 MHz exist only in the
footnote countries (§1).

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 420.000 | 426.000 | — | image (ATV) | | ATV repeater or simplex (421.25 video carrier); control links; experimental |
| 426.000 | 432.000 | — | image (ATV) | | ATV simplex (427.25 video carrier). Countries without 430–450 use 430–432 as a local option (note 1) |
| 432.000 | 432.025 | 500 Hz | cw | | EME |
| 432.025 | 432.100 | 500 Hz | cw, digi | | EME and weak signal |
| 432.100 | 432.300 | 2700 Hz | cw, ssb | | Weak signal. **432.100 SSB/CW calling** |
| 432.300 | 432.400 | 500 Hz | cw | **beacon** | "Beacons" (not marked exclusive) |
| 432.400 | 432.420 | 2700 Hz | cw, digi | **beacon** | Beacons; ACDS (digital beacons) |
| 432.420 | 433.000 | 2700 Hz | cw, ssb, digi | | |
| 433.000 | 433.050 | 12 kHz | digi | | ACDS |
| 433.050 | 433.100 | 12 kHz | all | | IVG |
| 433.100 | 435.000 | — | — | | Local option |
| **435.000** | **438.000** | — | all | **satellite** | "Satellite (exclusive)" |
| 438.000 | 450.000 | — | — | | Local option (note 1) |

N1 names no 70 cm repeater sub-bands or FM calling frequency; both are
"local option".

### 4.5 23 cm: 1240–1300 MHz [N1 p.14–15]

The band is secondary in R2.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1240.000 | 1246.000 | — | image (ATV) | | ATV channel 1 |
| 1246.000 | 1248.000 | 20 kHz | fm, dv | | Point-to-point links, paired with 1258–1260 |
| 1248.000 | 1252.000 | 20 kHz | digi | | |
| 1252.000 | 1258.000 | — | image (ATV) | | ATV channel 2 |
| 1258.000 | 1260.000 | 20 kHz | fm, dv | | Point-to-point links, paired with 1246–1248 |
| 1260.000 | 1270.000 | — | all | **satellite** (shared) | "Priority to Satellite uplinks, Experimental, Simplex ATV" |
| 1270.000 | 1276.000 | 20 kHz | fm, dv | | Repeater inputs, 25 kHz, paired with 1282–1288. A regional option uses 1270–1274, paired with 1290–1294 |
| 1276.000 | 1282.000 | — | image (ATV) | | ATV channel 3 |
| 1282.000 | 1288.000 | 20 kHz | fm, dv | **output** | Repeater outputs, paired with 1270–1276 |
| 1288.000 | 1294.000 | — | all | | Broadband experimental; simplex ATV. 1290–1294 repeater outputs as a regional option (overlap, as printed) |
| 1294.000 | 1295.000 | 20 kHz | fm, dv | | **1294.500 FM simplex calling** |
| 1295.000 | 1295.800 | — | all | | Narrowband image; experimental |
| 1295.800 | 1296.080 | 2700 Hz | cw, ssb, digi | | EME and weak signal |
| 1296.080 | 1296.200 | 2700 Hz | cw, ssb | | Weak signal. **1296.100 CW/SSB calling** |
| 1296.200 | 1296.400 | 500 Hz | cw, digi | **beacon** | Beacons; ACDS (digital beacons) |
| 1296.400 | 1297.000 | 2700 Hz | all | | General narrowband |
| 1297.000 | 1300.000 | 150 kHz | digi | | |

### 4.6 13 cm: 2300–2450 MHz [N1 p.15–16]

The band is secondary in R2; ISM users may be heard.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 2300.000 | 2303.000 | 1 MHz | all | | Analogue and digital, including full duplex; paired with 2390–2393 |
| 2303.000 | 2303.750 | 50 kHz | all | | Paired with 2393–2393.750 |
| 2303.750 | 2304.000 | 3000 Hz | cw, ssb, digi | | Weak signal |
| 2304.000 | 2304.100 | 3000 Hz | cw, ssb, digi | | EME and weak signal |
| 2304.100 | 2304.300 | 3000 Hz | cw, ssb, digi | | Weak signal. **2304.100 calling** |
| 2304.300 | 2304.400 | 3000 Hz | cw, digi | **beacon** | Beacons; ACDS (digital beacons) |
| 2304.400 | 2304.750 | 6000 Hz | cw, ssb, digi, fm | | Weak signal (NBFM) |
| 2304.750 | 2305.000 | 50 kHz | all | | Paired with 2394.750–2395 |
| 2305.000 | 2310.000 | 1 MHz | all | | Paired with 2395–2400 |
| 2310.000 | 2390.000 | — | — | | Local option |
| 2390.000 | 2400.000 | 1 MHz / 50 kHz | all | | Pairs for 2300–2310; 2393.750–2394.750 experimental |
| 2400.000 | 2450.000 | — | all | **satellite** | "Satellites". Broadband applications allowed in 2410–2450 at up to 22 MHz, without interfering with satellites |

### 4.7 9 cm: 3300–3500 MHz [N1 p.16–17]

The band is secondary in R2.

- **Radio astronomy.** "Radio Astronomy protected band" at 3332–3339 and
  3345.8–3352.5 MHz; the plan gives no bandwidth or mode there. Encode as
  **refuse** [derived from the plan's wording, and from P1 p.17: "No
  operation"].
- **3300–3400:** full-duplex pairs at 1 MHz, 200 kHz and 50 kHz, with
  experimental slots.
- **3360–3400:** broadband, 22 MHz; ATV at local option on 3360–3380.
- **3400.000–3400.300:** 3000 Hz; cw, ssb, digi. EME; **3400.100 EME
  calling**; satellite.
- **3400.300–3401.000:** 3000 Hz; weak signal and satellite.
- **3401.000–3410.000:** satellite (kind **satellite**).
- **3410–3455:** duplex pairs.
- **3455.000–3455.500:** 100 kHz. Crossband linear translator.
- **3455.500–3456.300:** 6000 Hz; cw, ssb, digi, NBFM. Weak signal;
  **3456.100 calling**.
- **3456.300–3457.000:** 1000 Hz; cw, digi. Beacons and ACDS (kind
  **beacon**).
- **3457–3460:** duplex.
- **3460–3500:** broadband, 22 MHz; ATV at local option 3460–3480.

Footnote 1: "There are no restrictions for modes and bandwidth for
satellites communications".

### 4.8 6 cm: 5650–5925 MHz [N1 p.18]

The band is secondary in R2.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 5650 | 5670 | — | all | **satellite** | Satellite (uplink) |
| 5650 | 5760 | — | all | | (overlaps the row above, as printed) |
| 5760.0 | 5760.3 | 2700 Hz | all | | EME and weak signal. **5760.1 calling** |
| 5760.3 | 5761.0 | 2700 Hz | cw, digi | **beacon** | Beacons; ACDS (digital beacons) |
| 5761 | 5765 | — | all | | Weak signal |
| 5765 | 5850 | — | all | | |
| 5830 | 5850 | — | all | **satellite** | Satellite (downlink) |
| 5850 | 5925 | — | all | | |

### 4.9 R2 bands outside the app's list

N1 also plans 1.25 m (220–225 MHz, p.12–13) and 33 cm (902–928 MHz,
p.13–14). Both are R2-only allocations [T1 p.99, p.112]. The app does not
cover them; they are noted so nobody mistakes them for omissions.

---

## 5. IARU Region 3 [P1]

R3's own wording on precedence [P1 p.3]:

- **Basic principle 1:** "In all cases of conflict between a band plan and
  the national regulations of a country, the latter shall prevail."
- **Basic principle 2:** different national arrangements are allowed
  provided they do not cause harmful interference.
- **Satellite definition:** "This segment should be kept clear of other
  operating modes" [P1 p.4].
- **CoA:** a "Centre of Activity" frequency (IARU recommended).

### 5.1 HF

All figures are in kHz.

#### 160 m (P1 p.5)

The band is primary.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1800 | 1830 | 200 | cw | | CW |
| 1830 | 1840 | 500 | cw, digi | | CW and narrowband. **1836 QRP CoA** |
| 1840 | 2000 | 2700 | all modes | | |

Digital dials: WSPR 1836.6, JT65 1838, **FT8 1840**.

#### 80 m (P1 p.6)

The band is primary. The R3 allocation ends at 3900.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 3500 | 3510 | 200 | cw | | CW, DX |
| 3510 | 3535 | 200 | cw | | CW |
| 3535 | 3600 | 2700 | cw, ssb, am, fm, dv, digi | | CW, phone, digimodes. 3560 QRP CoA |
| 3600 | 3775 | 2700 | cw, ssb, am, fm, dv, digi | | CW, digimodes, phone |
| 3775 | 3800 | 2700 | cw, ssb, am, fm, dv | | CW, phone, DX |
| 3800 | 3900 | 2700 | cw, ssb, am, fm, dv, digi | | CW, phone, digimodes |

Centres of activity:

- **3600 Emergency** (all modes ±5 kHz)
- 3690 Digital Voice, and also 3690 SSB QRP (both as printed)
- 3735 Image
- 3795 DX phone (printed in the 3800–3900 row)
- 3845 Image

Digital dials: WSPR 3568.6, JT65 3570, **FT8 3573**.

#### 60 m (P1 p.6)

The band is secondary.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 5351.5 | 5354 | 500 | cw, digi | | CW, narrowband digimodes |
| 5354 | 5366 | 2700 | all modes | | All modes; USB for phone |
| 5366 | 5366.5 | 20 | digi | | Weak-signal modes; "Maximum bandwidth suggested 20Hz" |

#### 40 m (P1 p.7)

The band is primary; 7000–7100 is also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 7000 | 7030 | 200 | cw | | CW |
| 7030 | 7040 | 2700 | cw, digi, ssb, am, fm, dv | | "CW, NB, Phone". 7030 QRP CoA (as printed: 2700 Hz, phone allowed) |
| 7040 | 7060 | 2700 | all modes | | All modes, narrowband, phone |
| 7060 | 7100 | 2700 | all modes | | 7095 DX phone CoA |
| 7100 | 7200 | 2700 | all modes | | **7110 Emergency CoA** (all modes ±5 kHz); 7165 Image CoA |

- **Misplaced centres:** 7070 Digital Voice CoA and 7090 SSB QRP CoA are
  printed in the 7040–7060 row (as printed). They actually fall in
  7060–7100.
- **Digital dials:** WSPR 7038.6, **FT8 7074**, JT65 7076, RTTY DX 7040.
- **7200–7300:** P1 states that this range "is not allocated to the amateur
  service in Region 3" [P1 p.1].
- **Proposed revision:** P2 proposed reworking 40 m; nothing was adopted.

#### 30 m (P1 p.7)

The band is secondary.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 10110 | 10130 | 200 | cw | | CW (lower edge **10110 as printed**; the allocation starts at 10100 [T1 p.71]; 10100–10110 is unplanned) |
| 10130 | 10150 | 500 | cw, digi | | CW, narrowband digimodes |

- **Centre of activity:** 10116 QRP CoA.
- **Footnote 1:** "Some Administrations allow phone in the segment
  10115-10140 kHz."
- **Digital dials:** **FT8 10136**, JT65 10138, WSPR 10138.6.

#### 20 m (P1 p.8)

The band is primary; 14000–14250 is also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 14000 | 14070 | 200 | cw | | CW. 14055 QRS CoA; 14060 QRP CoA |
| 14070 | 14110 | 500 | cw, digi | | CW, narrowband. Overlaps the next row (as printed) |
| **14099.75** | **14100.25** | — | (none) | **beacon** | "14100 kHz – International Beacon, 500 Hz guard band for beacons" [derived edges, read as ±250 Hz] |
| 14100 | 14112 | 2700 | cw, digi, ssb, am, fm, dv | | CW, narrowband digimodes, phone |
| 14112 | 14350 | 2700 | cw, ssb, am, fm, dv | | CW, phone. The plan prints 14112–14250 and 14250–14350 as two rows with one set of notes |

Centres of activity:

- 14130 Digital Voice
- 14195 DX phone
- 14230 Image
- 14285 SSB QRP
- **14300 Global Emergency** (all modes ±5 kHz)

Digital dials: **FT8 14074.0**, JT65 14076.0, WSPR 14095.6.

**The width of the beacon guard band is ambiguous [derived].** "500 Hz
guard band" can mean 500 Hz in total (±250 Hz) or 500 Hz each side.
±250 Hz is used above.

A conservative implementation can use the R1/R2 ±1 kHz window instead.
The IBP beacons transmit CW (and a carrier); protecting ±1 kHz costs
nothing that R3 itself plans for [derived].

#### 17 m (P1 p.9)

The band is primary, and also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 18068 | 18095 | 200 | cw | | 18086 QRP CoA |
| 18095 | 18110 | 2700 | cw, digi | | "CW, Narrowband – Digimodes" (as printed: 2700 Hz) |
| **18109.75** | **18110.25** | — | (none) | **beacon** | "18110 kHz – International Beacon, 500 Hz guard band" [derived edges] |
| 18110 | 18120 | 2700 | cw, digi, ssb, am, fm, dv | | CW, narrowband, phone |
| 18120 | 18168 | 2700 | cw, ssb, am, fm, dv | | CW, phone |

Centres of activity:

- 18130 SSB QRP
- 18160 Digital Voice
- **18160 Emergency CoA** (both as printed)

Digital dials: **FT8 18100.0**, JT65 18102.0, WSPR 18104.6.

#### 15 m (P1 p.10)

The band is primary, and also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 21000 | 21070 | 200 | cw | | 21055 QRS CoA; 21060 QRP CoA |
| 21070 | 21110 | 500 | cw, digi | | CW, narrowband |
| 21110 | 21125 | 2700 | cw, digi | | CW, narrowband digimodes |
| 21125 | 21150 | 2700 | cw, digi | | CW, narrowband digimodes. "Satellite – only uplink". The satellite service has no bandwidth limit (footnote 1) |
| **21149.75** | **21150.25** | — | (none) | **beacon** | "21150 kHz – International Beacon, 500 Hz guard band" [derived edges] |
| 21150 | 21450 | 2700 | cw, ssb, am, fm, dv | | CW, phone; satellite uplink |

Centres of activity:

- 21180 Digital Voice
- 21295 DX phone
- 21340 Image
- **21360 Global Emergency** (all modes ±5 kHz)

Digital dials: **FT8 21074.0**, JT65 21076.0, and WSPR printed "21.0946 kHz"
(as printed; means 21094.6 [derived]).

#### 12 m (P1 p.11)

The band is primary, and also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 24890 | 24915 | 200 | cw | | 24906 QRP CoA |
| 24915 | 24930 | 500 | cw, digi | | CW, narrowband |
| **24929.75** | **24930.25** | — | (none) | **beacon** | "24930 kHz – International Beacon, 500 Hz guard band" [derived edges] |
| 24930 | 24940 | 2700 | cw, digi, ssb, am, fm, dv | | CW, narrowband, DX, phone |
| 24940 | 24990 | 2700 | cw, ssb, am, fm, dv | | CW, phone |

Centres of activity: 24950 SSB QRP, 24960 "Digital CoA" (as printed).

Digital dials: **FT8 24915.0**, JT65 24917.0, WSPR 24924.6.

#### 10 m (P1 p.12)

The band is primary, and also amateur-satellite.

| Lo | Hi | Max BW (Hz) | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 28000 | 28070 | 200 | cw | | 28055 QRS CoA |
| 28070 | 28150 | 500 | cw, digi | | CW, narrowband |
| 28150 | 28190 | 500 | cw, digi | | CW, narrowband, DX |
| **28190** | **28201** | 200 | (none) | **beacon** | "Beacons. 28200 kHz – International Beacon, 500 Hz guard band" |
| **28201** | **28225** | 200 | (none) | **beacon** | "Beacons - Continuous duty" |
| 28225 | 29100 | 2700 | all modes | | All modes. 28330 DV CoA; 28360 QRP CoA; 28495 DX CoA; 28680 Image CoA |
| 29100 | 29300 | 6000 | all modes + fm | | All modes |
| 29300 | 29510 | 6000 | all | **satellite** | "Satellite – uplink and downlink" |
| 29510 | 29590 | 6000 | all modes + fm | | FM repeater input |
| 29520 | 29620 | 6000 | all modes + fm | | FM simplex. **29600 International Calling Channel** (overlaps the row above, as printed) |
| 29620 | 29700 | 6000 | all modes + fm | **output** | FM repeater output |

- **No guard channel:** R3 has none at 29510–29520.
- **Digital dials:** **FT8 28074.0**, JT65 28076.0, WSPR 28124.6.

### 5.2 6 m: 50–54 MHz (P1 p.13)

The band is primary. Some administrations grant other services primary
status here (footnote 1).

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 50.000 | 50.100 | 200 Hz | cw | | CW. International beacons at 50.020–50.080 (kind **beacon** for that sub-range) |
| 50.100 | 50.500 | 2700 Hz | cw, ssb, am, fm, dv, digi | | CW, phone, narrowband, digimodes. **50.110 DX CoA** |
| 50.500 | 54.000 | none | all, incl. WB | | "All modes, WB". The bandwidth limit was **removed at the 19th Conference (Nov 2024)** [P1 p.1] |

Digital dials: JT65 50.2760, WSPR 50.2937, **FT8 50.3130**.

### 5.3 2 m: 144–148 MHz (P1 p.14)

144–146 is primary, and also amateur-satellite; 146–148 is primary.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 144.000 | 144.025 | 2700 Hz | digi | **satellite** (shared) | "Narrowband – Digimodes – satellite and terrestrial". Satellites must not transmit below 144.0025 (footnote 1) |
| 144.025 | 144.035 | — | cw, digi | | EME, weak signal |
| 144.035 | 145.800 | 25 kHz | all | | All modes. **144.100 DX CoA**, also the suggested DX calling frequency |
| **145.800** | **146.000** | 25 kHz | all | **satellite** | "All modes Satellites" |
| 146.000 | 148.000 | — | all | | All modes |

Footnotes:

- WSPR 144.4890.
- **144.800 is the suggested APRS spot frequency.** 144.390 is used by
  MARTS, RAST, SARTS and ORARI, and 144.640 by CRAC, CTARL and HARTS.
- 145.825 is the suggested satellite APRS frequency.
- P1 has no repeater, FM simplex or calling sub-bands on 2 m.

### 5.4 70 cm: 430–440 MHz (P1 p.15)

The band is secondary. P1 drops 440–450 because only Australia and the
Philippines hold it in R3 [P1 p.1].

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 430.000 | 431.900 | 25 kHz | all | | All modes |
| 431.900 | 432.240 | 2700 Hz | cw, ssb, digi | | EME, weak signal |
| 432.240 | 435.000 | 25 kHz | all | | All modes |
| **435.000** | **438.000** | — | all | **satellite** | "Satellites – All modes" (non-interference basis) |
| 438.000 | 440.000 | — | all | | All modes |

Footnote 1: the band is "heavily used by ISM and other unlicensed
services".

### 5.5 23 cm: 1240–1300 MHz (P1 p.16)

The band is secondary.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 1240 | 1260 | — | all | | All modes |
| **1260** | **1270** | — | all | **satellite** | "Satellites, all modes. Limited to the Earth-to-Space direction only" |
| 1270 | 1296 | — | all | | All modes |
| 1296 | 1297 | 2700 Hz | cw, ssb, digi | | EME, weak signal, SSB, digimodes |
| 1297 | 1300 | — | all | | All modes |

### 5.6 13 cm: 2300–2450 MHz (P1 p.16)

The band is secondary.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 2300.000 | 2303.750 | — | all | | All modes |
| 2303.750 | 2304.000 | 2700 Hz | cw, ssb, digi | | Weak signal |
| 2304.000 | 2304.100 | 2700 Hz | cw, ssb, digi | | Weak signal, EME |
| 2304.100 | 2304.300 | 2700 Hz | cw, ssb, digi | | Weak signal. **2304.100 calling** |
| **2304.300** | **2304.400** | 2700 Hz | (none) | **beacon** | Beacons (CW, digimodes) |
| 2304.400 | 2400.000 | — | all | | All modes. The plan prints this row as "2304.3-2400.0" (as printed; overlaps the beacons) |
| **2400.000** | **2450.000** | — | all | **satellite** | "Satellite All modes" |

### 5.7 9 cm: 3300–3500 MHz (P1 p.17)

The band is secondary; 3400–3410 is also amateur-satellite.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| 3300.0 | 3345.8 | — | all | | All modes |
| **3345.8** | **3352.5** | — | (none) | refuse | "Radio Astronomy protected band. No operation." |
| 3352.5 | 3400.0 | — | all | | All modes |
| 3400.0 | 3400.3 | 2700 Hz | cw, ssb, digi | **satellite** (shared) | Satellite, EME. **3400.10 calling** |
| 3400.3 | 3410.0 | 2700 Hz | cw, ssb, digi | **satellite** (shared) | Weak signal |
| 3410.0 | 3455.5 | — | all | | All modes |
| 3455.5 | 3456.3 | — | cw, ssb, digi, fm | | Weak signal. **3456.10 calling** |
| **3456.3** | **3457.0** | 2700 Hz | (none) | **beacon** | Beacons, digimode beacons |
| 3457.0 | 3500.0 | — | all | | All modes |

### 5.8 6 cm: 5650–5850 MHz (P1 p.18)

The band is secondary.

| Lo | Hi | Max BW | Classes | Kind | Usage |
|---|---|---|---|---|---|
| **5650** | **5670** | — | all | **satellite** | "Satellites, all modes. Limited to the Earth-to-Space direction only" |
| 5670 | 5760 | — | all | | All modes |
| 5760.0 | 5760.3 | 2700 Hz | cw, ssb, digi | | EME, weak signal. **5760.1 calling** |
| **5760.3** | **5761.0** | 2700 Hz | (none) | **beacon** | Beacons, digimode beacon |
| 5761 | 5765 | — | all | | All modes, weak signal |
| 5765 | 5830 | — | all | | All modes |
| **5830** | **5850** | — | all | **satellite** | "Satellites … Space-to-Earth direction only" |
| 5850 | 5925 | — | all | | All modes (as printed: the R3 table has no amateur allocation above 5850 [T1 p.148]) |

---

## 6. What the code should do with these

**The law is the national licence, not the IARU plan.** All three plans
say so themselves:

- **R1:** the handbook says operators "should take notice of these
  agreements which are made for operating convenience, but no right to
  reserved frequencies can be derived". It says its plans "are generic for
  all members states … we advise to look also to the bandplanning of the
  country of the operator" [I2 p.34]. The HF plan presents 60 m and 630 m
  as "proposed usage" [I1 p.3].
- **R2:** "this voluntary band plan … national and/or local band plans
  may not follow the IARU Region 2 band plan exactly" [N1 p.1].
- **R3:** "In all cases of conflict between a band plan and the national
  regulations of a country, the latter shall prevail" [P1 p.3].

So, with the same weighting as `bandplan-r1-uk.md` [derived]:

1. **Band edges are a licence question.**
   - The fallback should use the ITU regional allocation (§1) as its
     outer edges.
   - It should be shown as "generic — check your national licence".
   - Footnote-only bands are offered only when a national plan enables
     them: R1 1850–2000 kHz, R1 70 MHz, R1 3.4 GHz, R2/R3 420–430 and
     440–450 MHz.
2. **Segments, bandwidths and modes are advisory.** A mode or bandwidth
   outside the segment produces a warning, not a refusal. This matches
   DESIGN-HAM §6, rules 2 and 3.
3. **Always refuse to transmit** in the segments below, because their own
   plan's wording forbids transmission or reserves them exclusively for
   beacons. These carry `kind="beacon"` (or a guard), with no allowed
   modes.

   | Region | Segment | Plan wording | Source |
   |---|---|---|---|
   | R1 | 14099–14101, 18109–18111, 21149–21151, 24929–24931 kHz | "Beacons exclusively" | I1 p.1–2 |
   | R1 | 28190–28225 kHz | "…time shared beacons, exclusively" / "Continuous duty beacons, exclusively" | I1 p.2 |
   | R1 | 29510–29520 kHz | "Guard Channel" | I1 p.2 |
   | R1 | 50.000–50.030 MHz | "Reserved for Synchronised Beacon Project" | I2 p.35 |
   | R1 | 50.400–50.500 MHz | "Beacons exclusive" | I2 p.35 |
   | R1 | 144.000–144.0025 MHz | "No transmission shall be made below 144,0025 MHz" | I2 p.40 |
   | R1 | 144.400–144.490 MHz | "Beacons exclusive" | I2 p.38 |
   | R1 | 432.400–432.490 MHz | "Beacons exclusive" | I2 p.41 |
   | R1 | 1296.800–1296.994 MHz | "Beacons exclusive" | I2 p.46 |
   | R1 | 2320.800–2321.000 MHz | "BEACONS EXCLUSIVE" | I2 p.48 |
   | R1 | 3400.800–3400.995 MHz | "BEACONS ONLY" | I2 p.49 |
   | R1 | 5760.800–5760.990 MHz | "BEACONS ONLY" | I2 p.50 |
   | R2 | 14099–14101, 18109–18111, 21149–21151, 24929–24931, 28199–28201 kHz | "IBP (exclusive)" | N1 p.8–10 |
   | R2 | 29510–29520 kHz | "Guard band, no transmission allowed" | N1 p.10 |
   | R2 | 145.790–145.800 MHz | "Guard band, no transmission allowed" | N1 p.12 |
   | R2 | 3332–3339, 3345.8–3352.5 MHz | "Radio Astronomy protected band" | N1 p.16 |
   | R3 | 3345.8–3352.5 MHz | "Radio Astronomy protected band. No operation." | P1 p.17 |
   | R3 | IBP 14100, 18110, 21150, 24930, 28200 kHz ± guard | "500 Hz guard band for beacons" (edges [derived], see §5.1 20 m) | P1 p.8–12 |
   | R3 | 28201–28225 kHz | "Beacons - Continuous duty" | P1 p.12 |

4. **Beacon segments not marked exclusive.** These should warn by
   default. Refusing them is a safe choice, since no listed plan puts
   ordinary QSO traffic there [derived].
   - R1: 70.000–70.100 MHz and the 1240.500–1240.750 "reserved for future"
     beacons.
   - R2: 28190–28199 and 28201–28225 kHz; 50.000–50.100, 50.400–50.500,
     144.275–144.300, 144.400–144.500, 432.300–432.420, 1296.200–1296.400,
     2304.300–2304.400, 3456.3–3457.0 and 5760.3–5761.0 MHz.
   - R3: 50.020–50.080, 2304.3–2304.4, 3456.3–3457.0 and 5760.3–5761.0 MHz.
   - **Exception:** R2 50.000–50.100 is also the R2 CW segment, so it must
     not be refused.
5. **Satellite-only segments: refuse terrestrial transmission, allow
   satellite operation.**

   | Region | Segment (MHz) | Plan wording | Source |
   |---|---|---|---|
   | R1 | 145.806–146.000 | "Satellite exclusive" | I2 p.39 |
   | R1 | 435–438 | DATV simplex allowed in 436–438, satellites have priority | I2 p.42–44 |
   | R1 | 1260–1270 | uplink only | I2 p.45 |
   | R1 | 2400–2450 | | I2 p.48 |
   | R1 | 3402–3410 | | I2 p.49 |
   | R1 | 5650–5670 | | I2 p.50 |
   | R1 | 5830–5850 | | I2 p.50 |
   | R2 | 145.800–146.000 | "(exclusive)" | N1 p.12 |
   | R2 | 435–438 | "(exclusive)" | N1 p.13 |
   | R2 | 29300–29510 kHz | | N1 p.10 |
   | R3 | 145.8–146, 435–438, 1260–1270, 2400–2450, 5650–5670, 5830–5850 | Satellite: "should be kept clear of other operating modes" | P1 p.4 |

   Plain refusal would be wrong here. These segments are where satellite
   *uplinks* go: modes A, J and V/U uplink in 145.8–146.0, and modes B
   and S uplink in 435–438 [I2 p.102]. So refuse ordinary terrestrial
   transmission, and allow it once the operator selects a satellite (or
   satellite mode). Without satellite support, refuse with a message that
   says why [derived].

   Shared segments are **not** satellite-only:
   - 21125–21450 kHz (all three regions)
   - R1 144.000–144.025
   - R3 144.000–144.025
   - R2 1260–1270 ("priority")
   - R2/R3 3400–3410
   - 10.45–10.50 GHz
   - R1 29300–29510 (R3's is refused: `iaru_r3.py` applies P1's own
     definition of a satellite segment, which also makes 145.8–146 MHz
     exclusive, to its "Satellite - uplink and downlink" row)
   - R2 2400–2450, 5650–5670, 5830–5850: N1 labels them satellite but,
     unlike 145.8–146 and 435–438, not "(exclusive)"; `iaru_r2.py`
     leaves them transmittable
6. **Repeater outputs (`kind="output"`)** should warn on simplex
   transmission rather than refuse. R1 says "Established simplex
   frequencies on repeater output channels may be retained" [I2 p.39].
   Inputs marked "(exclusive)" (R1 2 m, R2 10 m, 6 m and 2 m) are for
   repeater access; they need no special handling beyond a hint.
7. **Centres of activity** become click-to-tune markers. Emergency centres
   should be marked for the operator to keep clear of: the plans give
   emergency traffic priority [N1 p.2; P1 p.4]. For R1 and R2, take FT8
   and other digital dials from the WSJT-X default table (W1 in
   `bandplan-r1-uk.md`), since neither plan lists them. For R3, the plan's
   own dials agree with WSJT-X's usual FT8 values [derived; W1 not
   re-fetched here].

---

## 7. What could not be confirmed

- **Whether R1's Zlatibor 2023 conference changed the HF plan.** No
  revised plan is published (I5); the newest PDF says "Effective from
  16 OCT 2020". The Zlatibor C4 recommendations themselves were not
  fetched [unverified].
- **Whether R2 amended its plan after September 2020** under the 60-day
  procedure. No announcement was found; the 2025 GA report mentions none
  (N2). The PDF was regenerated in October 2022 but still says "September
  2020". The two copies were not compared [unverified that the content is
  unchanged since 2020].
- **The R3 IBP guard-band width** ("500 Hz guard band"): total or per side
  is not stated. The ±250 Hz edges above are [derived].
- **The US 2 m repeater convention** (147.0–147.4 MHz as outputs) is from
  memory, not from a fetched source [unverified]. It is noted only to flag
  N1's printed direction.
