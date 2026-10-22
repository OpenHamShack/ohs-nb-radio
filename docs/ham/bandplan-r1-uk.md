# UK licence limits and the RSGB / IARU Region 1 band plans

Compiled 2026-10-04 for `DESIGN-HAM.md` §5.1 and §6. This is the source
document for `ohsradio/licences/ofcom.py` and `ohsradio/plans/*.py`. Every row
carries a source key; the sources and their dates are listed in the first
table.

How to read the markers:

- **[unverified]**: not confirmed from a primary source.
- **[derived]**: worked out here, not stated in a source.

**Two kinds of rule, with different weight.** The Ofcom licence is law, so
the TX guard enforces it. The RSGB band plan is a voluntary code of
practice, so the guard warns by default (DESIGN-HAM §6, rules 2 and 3).

**Re-check before each release.** Ofcom changed the licence in February 2024
and again in October 2025. The RSGB plan is revised every January, band by
band.

## Sources

| Key | Document | Date / version | URL |
|---|---|---|---|
| O1 | Ofcom OFW611, "Amateur Radio Wireless Telegraphy Licence Conditions Booklet" (conditions + Schedule 1 Tables A/B/C) | The document says "Published 21 February 2024". The PDF was modified 28 Nov 2024; Ofcom's page says "last updated 14 Oct 2025". | https://www.ofcom.org.uk/siteassets/resources/documents/spectrum/emf/emf-amateur-licence-terms-and-conditions.pdf |
| O2 | Ofcom, "Amateur Radio Guidance" | updated 14 Oct 2025 | https://www.ofcom.org.uk/siteassets/resources/documents/manage-your-licence/amateur/amateur_radio_licence_guidance_for_licensees.pdf |
| O3 | Ofcom, "Implementing Phase 2 and 3 of the Amateur Review" | 14 Oct 2025 | https://www.ofcom.org.uk/siteassets/resources/documents/manage-your-licence/amateur/amateur-radio-phase-2-and-3-review.pdf |
| O4 | Ofcom Statement, "Updating the amateur radio licensing framework" | 11 Dec 2023, effective 21 Feb 2024 | https://www.ofcom.org.uk/__data/assets/pdf_file/0037/272998/Statement-Updating-the-amateur-radio-licensing-framework.pdf |
| O5 | Ofcom, "Notice of coordination procedures" | 21 Feb 2024 | https://www.ofcom.org.uk/siteassets/resources/documents/manage-your-licence/amateur/notice-of-coordination-procedures |
| R1 | RSGB 2026 Band Plan (the Excel master, as a PDF) | "Updated January-2026", file 260125. Each band has its own "effective from" date, given below. | https://rsgb.services/public/bandplans/docs/260125_rsgb_band_plan_2026.pdf (index: https://rsgb.org/main/operating/band-plans/) |
| I1 | IARU Region 1 HF Band Plan | "Effective from 16 OCT 2020" (Novi Sad virtual General Conference) | https://www.iaru-r1.org/wp-content/uploads/2021/06/hf_r1_bandplan.pdf |
| I2 | IARU Region 1 VHF Handbook | v10.03, Feb 2026 | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf |
| I3 | IARU Region 1 VHF/UHF/SHF band-plan PDFs | VHF Dec 2020; UHF Mar 2021; SHF Dec 2020 | https://www.iaru-r1.org/about-us/committees-and-working-groups/vhf-uhf-shf-committee-c5/vhf-up-bandplanning/ |
| W1 | WSJT-X `models/FrequencyList.cpp` (the default dial table) | `master`, fetched 2026-10-04; commit not recorded | https://raw.githubusercontent.com/WSJTX/wsjtx/master/models/FrequencyList.cpp |
| F1 | freedv-gui `src/config/ReportingConfiguration.cpp` (the default frequency list) | `master`, fetched 2026-10-04 | https://raw.githubusercontent.com/drowe67/freedv-gui/master/src/config/ReportingConfiguration.cpp |
| U1 | ukrepeater.net: the access page, the tone-letter image, and the `csvcreate_all.php` export | page undated; CSV fetched 2026-10-04 | https://www.ukrepeater.net/access.htm, https://ukrepeater.net/csvcreate_all.php |
| X1 | RadioReference wiki, CTCSS (secondary source) | undated | https://wiki.radioreference.com/index.php/CTCSS |
| S1 | Wikipedia, "S meter", which cites IARU R1 Technical Recommendation R.1 (secondary source) | fetched 2026-10-04 | https://en.wikipedia.org/wiki/S_meter |
| I4 | IARU-R1 VHF Handbook (as I2), "IARU Region 1 Technical Recommendation S-METER READINGS, Brighton 1981, Torremolinos 1990", the recommendation's text, p. 104 | v10.03, Feb 2026; read 2026-10-05 | https://www.iaru-r1.org/wp-content/uploads/2026/02/VHF_Handbook_V10_03_final.pdf |

---

## 1. Ofcom licence: classes, call signs and limits

### What changed in 2024 [O4, O1]

Ofcom published its statement on 11 Dec 2023, and the new conditions took
effect on **21 Feb 2024**.

- **Power by class:**
  - Foundation: up to 25 W PEP. It also gained 2.4 GHz and 5.7 GHz at 2 W.
  - Intermediate: up to 100 W.
  - Full: **1000 W (30 dBW) on Primary bands, 400 W (26 dBW) on most
    others** [O2 Table 3].
- **Unattended stations:** repeaters, beacons and data stations under 25 W
  ERP no longer need an NoV [O1 cond. 6(12–18)].
- **Regional letter (RSL):** now optional, except in Intermediate
  "2"-series calls.
- **Airborne use:** Primary bands only, at 500 mW EIRP [O2 §4.3].

### What changed in October 2025 [O3]

These changes took effect on **14 Oct 2025**.

- Intermediate call signs are now issued as **M8** (replacing 2#0) and
  **M9** (replacing 2#1).
- A licensee may change call sign once every 5 years.
- A person may hold only one personal licence.
- Licences must be revalidated every 5 years.
- Special-event calls now take the form "GBdccccca".

### Call signs [O2 Table 1, O1 cond. 6(22–26)]

Scotland's regional letter is **M** for individual calls and **S** for club
calls.

| Class | Prefixes issued | Scottish form |
|---|---|---|
| Foundation | M3, M6, M7 | MM3 / MM6 / MM7 (letter optional) |
| Intermediate | M8, M9 (formerly 2#0, 2#1) | MM8 / MM9 (optional). In 2-series calls the letter is mandatory: 2M0, 2M1 |
| Full | M0, M1, M5, G0–G8 (G2 is reissue only) | GM4BRI, MM0… (optional) |
| Club | G or M prefix | GS…, MS… |

- **The other regional letters (individual / club):** England E / X, Wales
  W / C, Northern Ireland I / N, Isle of Man D / T, Jersey J / H, Guernsey
  U / P.
- **Suffixes:** any "/suffix" may be added to a call [O1 cond. 6(26)].
- **Implication [derived]:** the Settings page can check that a call sign's
  form matches the declared class. It should only warn, because an older
  call stays valid under a newer class.

### Schedule 1 power limits [O1 Tables A/B/C]

Limits are PEP unless the row says otherwise.

- **Status** gives Amateur / Amateur-Satellite.
- **Pri.** = Primary; **Sec.** = Secondary.
- **NIB** = "no interference basis".
- **"—"** means the class may not transmit there.

| Band | Status | Foundation | Intermediate | Full |
|---|---|---|---|---|
| 135.7–137.8 kHz | Sec. (NIB) / – | 1 W ERP | 1 W ERP | 1 W ERP |
| 472–479 kHz | Sec. / – | — | — | **5 W EIRP** |
| 1810–1830 kHz | Pri. (NIB to non-UK) / – | 25 W | 100 W | 1000 W |
| 1830–1850 kHz | Pri. / – | 25 W | 100 W | 1000 W |
| 1850–2000 kHz | Sec. (NIB) / – | 25 W | **32 W (15 dBW)** | **32 W** |
| 3500–3800 kHz | Pri., shared / – | 25 W | 100 W | 1000 W |
| 5 MHz, eleven segments (below) | Sec. (NIB inside UK) / – | — | — | **100 W, max 200 W EIRP** |
| 7000–7100 kHz | Pri. / Pri. | 25 W | 100 W | 1000 W |
| 7100–7200 kHz | Pri. / – | 25 W | 100 W | 1000 W |
| 10100–10150 kHz | Sec. / – | 25 W | 100 W | **400 W** |
| 14000–14250 kHz | Pri. / Pri. | 25 W | 100 W | 1000 W |
| 14250–14350 kHz | Pri. / – | 25 W | 100 W | 1000 W |
| 18068–18168, 21000–21450, 24890–24990 kHz; 28.0–29.7 MHz | Pri. / Pri. | 25 W | 100 W | 1000 W |
| 50–51 MHz | Pri. (NIB to non-UK) / – | 25 W | 100 W | 1000 W |
| 51–52 MHz | Sec. (NIB) / – | 25 W | 100 W | **100 W** |
| 70.0–70.5 MHz | Sec. (NIB) / – | 25 W | 100 W | **160 W (22 dBW)** |
| 144–146 MHz | Pri. / Pri. | 25 W | 100 W | 1000 W |
| 430–431 MHz | Sec. / – | 25 W ERP | **40 W ERP** | **40 W ERP** |
| 431–432 MHz | Sec. Not within 100 km of Charing Cross. / – | 25 W ERP | 40 W ERP | 40 W ERP |
| 432–435, 438–440 MHz | Sec. / – | 25 W | 100 W | 400 W |
| 435–438 MHz | Sec. / Sec. | 25 W | 100 W | 400 W |
| 1240–1260, 1270–1325 MHz | Sec. / – | — | 100 W | 400 W |
| 1260–1270 MHz | Sec. / Sec. (Earth→space only) | — | 100 W | 400 W |
| 2310–2350, 2390–2400 MHz | Sec. (NIB) / – | — | 100 W | 400 W |
| 2400–2450 MHz | Sec. (accept ISM) / Sec. | **2 W** | 100 W | 400 W |
| 3400–3410 MHz | Sec. (NIB) / – | — | 100 W | 400 W |
| 5650–5670 MHz | Sec. / Sec. (Earth→space) | 2 W | 100 W | 400 W |
| 5670–5680 MHz | Sec. / – | 2 W | 100 W | 400 W |
| 5755–5765, 5820–5830 MHz | Sec. (accept ISM) / – | 2 W | 100 W | 400 W |
| 5830–5850 MHz | Sec. (ISM) / Sec. (space→Earth) | — | 100 W | 400 W |
| 10.000–10.125, 10.225–10.450 GHz | Sec. / – | **1 W** | 100 W | 400 W |
| 10.450–10.475 GHz | Sec. / Sec. | 1 W | 100 W | 400 W |
| 10.475–10.500 GHz | **not allocated** / Sec. | 1 W | 100 W | 400 W |
| 24.00–24.05 GHz | Pri. (ISM) / Pri. | — | 100 W | 1000 W |
| 24.05–24.15 GHz | Sec., written Ofcom consent only | — | 100 W | 400 W |
| 24.15–24.25 GHz | Sec. | — | 100 W | 400 W |
| 47.0–47.2, 75.875–76, 77.5–78, 134–136, 248–250 GHz | Pri. / Pri. | — | 100 W | 1000 W |
| 75.5–75.875, 76–77.5, 78–81, 136–141, 241–248 GHz | Sec. / Sec. | — | 100 W | 400 W |
| 122.25–123 GHz | Sec. / – | — | 100 W | 400 W |

**Gaps the guard must refuse for every class.** These are not in the licence
at all:

- 2350–2390 MHz
- 13 cm above 2450 MHz
- 3410–3475 MHz
- 10.125–10.225 GHz

**Innovation bands** (Full licence plus an NoV only) [R1 notes]:

- 70.5–71.5 MHz
- 146–147 MHz. In Scotland, or within 40 km of it, the band ends at
  146.9375 MHz and the limit is 50 W ERP.
- 2300–2302 MHz
- above 275 GHz

The guard treats these as "not available" unless the operator records an
NoV.

### 60 m [O1 Table C, Note G]

60 m is open only to Full licensees, at 100 W PEP and at most 200 W EIRP.
Transmissions must stay inside the eleven UK segments (kHz):

- 5258.5–5264
- 5276–5284
- 5288.5–5292
- 5298–5307
- 5313–5323
- 5333–5338
- 5354–5358
- 5362–5374.5
- 5378–5382
- 5395–5401.5
- 5403.5–5406.5

The WRC-15 band 5351.5–5366.5 kHz is **not** granted separately; only its
overlap with these segments may be used. (O1 does not mention the WRC-15
band at all; the plan's Note 4 does [R1 p.10]. Corrected after the line-by-line
check, `licence-check.md`.)

Note G attaches these conditions:

- double sideband no wider than 6 kHz
- antenna no higher than 20 m
- no interference to MOD use
- operation only from the main station address, or from a temporary UK
  location reported every 30 minutes to within 5 km
- a telephone at hand
- net call-sign rules apply

**What the guard can enforce [derived]:** the segments, the bandwidth and
the power. Antenna height, location and telephone are on the operator, so
Settings shows them as a checklist the first time 60 m is used.

### Coordination and station types [O5, O1 cond. 6]

- **431–432 MHz:** excluded within 100 km of London. The guard needs a
  station-location setting to apply this (DESIGN-HAM question 12).
- **430–440 MHz:** repeaters and beacons above 25 W ERP need an NoV and MOD
  coordination.
- **1240–1325 MHz:** every repeater, beacon, gateway and data station needs
  Ofcom, MOD and CAA clearance.
- **Unattended beacons:** exclusion zones around five points in England. None
  is in Scotland.
- **Beacons, gateways and data stations:** 5 W ERP. Intermediate and Full
  licensees may run beacons and data stations at 25 W ERP.
- **Repeaters:** need an Intermediate or Full licence, may not operate below
  28 MHz, and are limited to 5 W ERP (25 W ERP for a Full licence).
- **Remote control over amateur radio:** above 30 MHz only.

OpenHamShack HAM is an attended station. None of these station types is in its
scope; the list is here so nobody mistakes them for omissions.

---

## 2. RSGB 2026 band plan: HF [R1]

The HF plan follows IARU R1 2020 [I1]. The 60 m plan and the extra
centres are UK-only.

- **Bandwidth limits by segment:** CW only = 200 Hz; narrow band = 500 Hz;
  all modes = 2.7 kHz.
- **Frequencies are transmitted frequencies**, not the suppressed carrier.
  For LSB, the plan gives a "lowest dial" so that the signal stays inside
  the segment.

| Band (plan effective from) | CW only | Narrow band / digital | All modes | Beacons, centres of activity |
|---|---|---|---|---|
| 160 m (1 Jan 2016) | 1810–1838 | 1838–1840 | 1840–2000 (lowest LSB dial 1843) | QRP CW 1836; DF beacons 1960 |
| 80 m (1 Jun 2016) | 3500–3570 (3500–3510 intercontinental) | 3570–3580 (200 Hz), 3580–3600 (500 Hz; 3590–3600 unattended) | 3600–3800 (lowest LSB dial 3603) | QRS 3555, QRP 3560, DV 3630, UK emergency 3663, SSB QRP 3690, image 3735, R1 emergency 3760 |
| 60 m (1 Jan 2026; UK usage plan) | — | — | all modes within the segments, USB | CW QRP 5262, UK emergency 5278.5, beacons 5290, AM (6 kHz) 5317, WSPR in 5362–5374.5 |
| 40 m (1 Jan 2012) | 7000–7040 | 7040–7050 (7047–7050 unattended) | 7050–7200 (lowest LSB dial 7053) | QRP 7030, PSK31 from 7040, DV 7070, SSB QRP 7090, R1 emergency 7110, image 7165; 7175–7200 intercontinental |
| 30 m (1 Jun 2016) | 10100–10130 | 10130–10150 | none (SSB only in emergencies) | QRP 10116; no contests or bulletins |
| 20 m (1 Jan 2009) | 14000–14070 | 14070–14099 (14089–14099 unattended) | 14101–14350 (no digimodes 14112–14125) | **IBP beacons 14099–14101**; QRS 14055, QRP 14060, DV 14130, DXpeditions 14195±5, image (SSTV) 14230, QRP 14285, emergency 14300 |
| 17 m (1 Jan 2009) | 18068–18095 | 18095–18109 | 18111–18168 | **IBP 18109–18111**; QRP 18086, SSB QRP 18130, DV 18150, emergency 18160 |
| 15 m (1 Jan 2021) | 21000–21070 | 21070–21110, 21120–21149 | 21110–21120 (no SSB), 21151–21450 | **IBP 21149–21151**; QRS 21055, QRP 21060, DV 21180, QRP 21285, image 21340, emergency 21360; satellites 21125–21245 (non-exclusive; R1 p.15 Note 1 - this read 21125–21450 before the check) |
| 12 m (1 Jan 2009) | 24890–24915 | 24915–24929 | 24931–24990 | **IBP 24929–24931**; QRP 24906, SSB QRP 24950, DV 24960 |
| 10 m (1 Jan 2024) | 28000–28070 | 28070–28190 | 28225–29700 | **IBP 28190–28225**; QRS 28055, QRP 28060, DV 28330, QRP 28360, image 28680; FM simplex 29100–29200 (10 kHz channels); satellites 29300–29510; repeater inputs 29520–29590, calling 29600, outputs 29620–29700 (RH1–8, **−100 kHz**; the printed row edge, R1 p.17 - the last channel is 29690) |

All frequencies in the table are in kHz.

### Plan notes that change what the guard does [R1]

- **60 m, 2026 Note 2:** nothing may be transmitted above 5358 kHz (FT8 uses
  a 5357 dial). An FT8 tone above 1 kHz audio would cross that line; the
  occupied-edge check catches it [derived].
- **60 m, Note 4:** avoid the WRC-15 band for UK-to-UK contacts.
- **No contests** on 5, 10, 18 or 24 MHz.
- **AM and extended SSB** only in the all-modes segments.
- **Toneburst:** "Toneburst access is being withdrawn in line with IARU-R1
  recommendations." See §5.

### Digital-mode dial frequencies [W1]

All dials are USB, in kHz.

| Band | FT8 | FT4 | WSPR |
|---|---|---|---|
| 2200 m / 630 m | — | — | 136.000 / 474.200 |
| 160 m | 1840.0 | — | 1836.6 |
| 80 m | 3573.0 | 3575.0 | 3568.6 |
| 60 m | 5357.0 ("provisional") | 5357.0 | — |
| 40 m | 7074.0 | 7047.5 | 7038.6 |
| 30 m | 10136.0 | 10140.0 | 10138.7 |
| 20 m | 14074.0 | 14080.0 | 14095.6 |
| 17 m | 18100.0 | 18104.0 | 18104.6 |
| 15 m | 21074.0 | 21140.0 | 21094.6 |
| 12 m | 24915.0 | 24919.0 | 24924.6 |
| 10 m | 28074.0 | 28180.0 | 28124.6 |
| 6 m | 50313.0 (50323 intercontinental) | 50318.0 | 50293 is R2/R3 only |
| 4 m | 70154.0 (R1) | — | 70091.0 |
| 2 m | 144174.0 | 144170.0 | 144489.0 |
| 70 cm | 432174.0 | — | 432300.0 |
| 23 cm | 1296174.0 | — | 1296500.0 |

- **MSK144** (R1): 50.380, 70.230 and 144.360 MHz.
- **DXpedition FT8:** 3567, 7056, 10131, 14090, 18095, 21091, 24911 and
  28091 kHz. These dials are listed for receive. The design does not offer
  them for transmit (that is a DXpedition's own frequency).

### Other modes

- **FreeDV** [F1] defaults, in MHz:
  - 160 m: 1.870
  - 80 m: 3.625, 3.643, 3.693, 3.697, 3.803
  - 60 m: 5.4035, 5.3685
  - 40 m: 7.177, 7.197
  - 20 m: 14.236, 14.240
  - 17 m: 18.118
  - 15 m: 21.313
  - 12 m: 24.933
  - 10 m: 28.330, 28.720

  freedv.org gives the UK centres as 3.640 LSB (primary), 3.643 (secondary)
  and 5.3685 USB. 5.3685 lies inside the UK segment 5362–5374.5 but outside
  the WRC-15 band.
- **PSK31:** 3580, 7040/7070, 10142, 14070, 18100, 21070, 24920 and 28120 kHz
  are common usage **[unverified convention]**. The RSGB plan names only
  7040 (Note 2) and 50.305 MHz.
- **RTTY:** around 14080–14099 kHz **[unverified convention]**.
- **SSTV:** the RSGB "image" centres in the table above (3735, 7165, 14230,
  21340, 28680 kHz).

---

## 3. RSGB 2026 band plan: VHF, UHF, microwave [R1]

| Band (plan effective from) | Segments and centres | Repeaters (output / input; user shift) |
|---|---|---|
| 6 m (1 Jan 2026) | CW 50.000–50.100 (beacon project 50.000–50.030); SSB/CW 50.100–50.300 (calling 50.150); MGM 50.300–50.400 (PSK 50.305); **beacons 50.400–50.500**; DV calling 50.630; FM calling 51.510; FM simplex 51.410–51.590 (20 kHz) | Outputs 50.720–50.870 (10 kHz). Inputs 51.220–51.370 (**+500 kHz**), or the new 2026 inputs 51.720–51.730 / 51.770–51.870 (**+1 MHz**). The pairing is inferred: the ukrepeater export shows 18 repeaters at 500 kHz and 3 at 1 MHz [U1]. |
| 4 m (1 Jan 2021) | **Beacons 70.000–70.090**; narrow band 70.100–70.250 (CW/SSB 70.200, meteor scatter 70.250); AM/FM calling 70.260; MGM 70.270; FM calling 70.450; 12.5 kHz channels 70.294–70.500 | none |
| 2 m (1 Jan 2025) | CW 144.025–144.150 (centre of activity 144.050); SSB/MGM 144.150–144.400 (**SSB calling 144.300**; MGM meteor scatter 144.370); **beacons 144.400–144.490**; image 144.500; data 144.600; **UK DV calling 144.6125**; APRS 144.800; FM simplex V16–V45, row 145.200–145.5935 (channels 145.200–145.5625, 12.5 kHz; R1 p.20); **FM calling 145.500**; ISS 145.200 up / 145.800 down; **satellites 145.806–146.000** | RV48–RV63: output channels 145.600–145.7875, inputs 145.000–145.1875, **−600 kHz**; the printed rows are 145.5935–145.7935 (outputs) and 144.990–145.1935 (inputs) [R1 p.20]. Low-power ad-hoc repeaters on 144.975 / 145.575 and 144.9875 / 145.5875. |
| 70 cm (1 Jan 2026) | Narrow band 432.000–432.400 (CW/SSB 432.200); **beacons 432.400–432.490**; FM simplex U272–U286, 433.400–433.575 (**calling 433.500**); **UK DV calling 438.6125**; APRS alternative 433.800; hotspots 434.000 / 438.800; **satellites 435–438** (DATV 437) | **RB0–RB15: outputs 433.000–433.375, inputs 434.600–434.975 (+1.6 MHz).** RU65–RU78: outputs 430.8125–430.975, inputs 438.4125–438.575 (+7.6 MHz). 9 MHz DV pairs: inputs 430.400–430.775, outputs 439.400–439.775 (−9 MHz). RBW (5 MHz): outputs 433.000–433.375, inputs 438.000–438.375. All four schemes appear in the ukrepeater export [U1]. |
| 23 cm (1 Jan 2024) | Narrow band 1296.150–1296.800 (centre 1296.200); **beacons 1296.800–1296.990**; simplex SM20–SM30, 1297.500–1297.750; DV calling 1297.725 | **RM0–RM15: outputs 1297.000–1297.375, inputs 1291.000–1291.375 (−6 MHz).** 9 such repeaters in [U1]. ATV outputs 1300–1325 (UK only). |
| 13 cm (1 Jan 2024) | Narrow band 2320.000–2320.800 (SSB 2320.200); **beacons 2320.800–2320.990**; FM/DV 2321–2322; wideband 2322–2350 and 2390–2400; ATV outputs 2435 / 2440 | — |
| 9 cm (1 Jan 2021) | Narrow band 3400.000–3400.800 (centre of activity 3400.100); **beacons 3400.800–3400.995**; wideband/DATV outputs 3402–3410 | — |
| 6 cm, 3 cm (1 Jan 2024) | 6 cm narrow band 5760.000–5762.000 (centre 5760.100). 3 cm narrow band 10368.000–10370.000 (centre 10368.100); alternative 10450–10452; 10475–10500 satellites only | — |

All frequencies in the table are in MHz.

**What the guard does with these [derived]:**

- **Beacon sub-bands** (bold above) and the **IBP slots** (§2) are refused
  whatever the bandplan-guard setting, as OpenHamShack NB refuses the QO-100
  beacon segments.
- **Satellite sub-bands** (2 m 145.806–146.000, 70 cm 435–438, 10 m
  29.300–29.510, 3 cm 10475–10500) are refused too. The design has no
  satellite operation (DESIGN-HAM §10), and terrestrial operation there
  breaks the plan's intent.

---

## 4. Where the UK differs from IARU Region 1

- **IARU R1 HF plan:** the current plan is dated 16 Oct 2020 [I1], and the
  R1 site still links it. No later published amendment was found
  **[unverified: whether the 2023 General Conference or a 2026 meeting
  changed it]**.
- **RSGB HF vs R1:** the segments match, apart from these UK additions:
  - the eleven 5 MHz segments (R1 covers only 5351.5–5366.5, with 5354–5366
    all modes and a USB dial of at most 5363);
  - the UK emergency frequencies 3663 and 5278.5 kHz;
  - DF beacons on 1960 kHz;
  - internet gateways on 29.270–29.290 MHz.
- **VHF Handbook:** v10.03, Feb 2026 [I2]. The band-plan PDFs date from
  Dec 2020 to Mar 2021 [I3].
- **70 cm repeater direction is reversed.** In R1, inputs are 433.000–433.3875
  and outputs 434.600–434.9875. In the UK, outputs are 433 and inputs 434.6.
  R1 also uses 7.6 MHz pairs with outputs at 438.650–439.5875; the UK uses
  its RU and 9 MHz schemes instead.
- **DV calling:** R1 uses 145.375 and 433.450 MHz; the UK uses 144.6125 and
  438.6125 MHz.
- **2 m:** R1 treats 145.575 and 145.5875 as repeater outputs; the UK uses
  them for 5 W ad-hoc repeaters.
- **23 cm:** R1 adds RS repeaters (outputs 1242.025–1242.700, inputs
  1270.025–1270.700) and RM16–RM19. The UK uses RM0–RM15.
- **6 m:** the UK does not use R1's 51.9 MHz repeater outputs [R1 2021
  change log].
- **RSGB summary:** its plans follow R1 "with some local differences on
  frequencies above 430 MHz" [R1].

**Implication for the data model [derived]:** a plan is a complete,
self-contained table per region, not a set of patches on R1. The repeater
pairs differ in *direction*, so a "shift" attribute inherited from R1 would
be wrong in the UK.

---

## 5. Repeater access: CTCSS and toneburst

### CTCSS tones

- **IARU R1 standard** [I2, FM.24 table], 35 tones in Hz: 67.0, 71.9, 74.4,
  77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 100.0, 103.5, 107.2, 110.9,
  114.8, 118.8, 123.0, 127.3, 131.8, 141.3, 146.2, 151.4, 156.7, 162.2,
  167.9, 173.8, 179.9, 186.2, 203.5, 210.7, 218.1, 225.7, 233.6, 241.8,
  250.3.
- **The common 50-tone set** [X1, secondary; TIA-603 itself not checked]
  adds 69.3, 97.4, 136.5, 159.8, 165.5, 171.3, 177.3, 183.5, 189.9, 192.8,
  196.6, 199.5, 206.5, 229.1 and 254.1. Whether the first is 69.3 or 69.4
  is **[unverified]**. The decoder bank uses all 50, because receive should
  recognise any tone.

### UK tone letters [U1, tone image]

| A | B | C | D | E | F | G | H | J |
|---|---|---|---|---|---|---|---|---|
| 67.0 | 71.9 | 77.0 | 82.5 | 88.5 | 94.8 | 103.5 | 110.9 | 118.8 |

- There is no letter I.
- The page text also lists 123.0, 136.5 and 141.3 Hz without letters. It
  prints them as "123.08" and "136.58", which look like typos.

### Scotland: tones in use

This is an indicative tally of the analogue repeaters in the ukrepeater CSV
of 2026-10-04 [U1]. It is **not a published zone table**; the ukrepeater
map is an image with no data behind it.

| Tone | Area | Examples |
|---|---|---|
| G 103.5 | central belt and west (20 repeaters) | GB3AY, GB3CS, GB3GL, GB3FE |
| F 94.8 | east and Tayside (11) | GB3ED, GB3DD, GB3PR, GB3AG |
| J 118.8 | Borders | GB3HK, GB3LB, GB3DU |
| E 88.5 | Western Isles | GB3IG, GB3EI |
| A 67.0 | Highlands, north-east | GB3BI, GB3SS, GB3AO |
| C 77.0 | Orkney, Shetland, Langholm | GB3OC, GB3LU, GB3AS |
| 69.3 | an outlier with no letter | MB5TH |

### 1750 Hz toneburst

- **ukrepeater.net:** "1750Hz tone burst access … is still permitted in
  addition to CTCSS" [U1].
- **RSGB:** toneburst is being withdrawn [R1].
- **IARU FM.24:** CTCSS or 1750 Hz may be used, but CTCSS is preferred, and
  every new repeater since 1 Jan 2015 should use CTCSS on receive and on
  transmit [I2 p.119].

### CTCSS deviation

The recommended CTCSS deviation level in the UK was not found
**[unverified]**. The design's 10–15 % of peak deviation is common practice,
not a sourced figure.

### Repeater data

The ukrepeater.net CSV export exists [U1]. **Its terms of reuse were not
checked [unverified]**, which is why DESIGN-HAM makes the repeater list an
operator import (question 7).

---

## 6. S-meter calibration [I4, S1]

The recommendation's text, as the IARU-R1 VHF Handbook prints it [I4]
(read 2026-10-05; until then this section rested on [S1] alone):

> Standardisation of S-meter readings
> - One S-unit corresponds to a signal level difference of 6 dB,
> - On the bands below 30 MHz a meter deviation of S-9 corresponds to an
>   available power of -73 dBm from a continuous wave signal generator
>   connected to the receiver input terminals,
> - On the bands above 30 MHz this available power shall be -93 dBm,
> - The metering system shall be based on quasi-peak detection with an
>   attack time of 10 msec ± 2 msec and a decay time constant of at least
>   500 msec.

So:

- **S9 = −73 dBm** below 30 MHz: the *available power* of the generator,
  which is 50 µV across a matched 50 Ω input ([S1]'s figure; −93 dBm is
  5 µV). OpenHamShack's Calibrate… takes either form.
- **S9 = −93 dBm** from 30 MHz up. The handbook's prose beside the box says
  the 1990 amendment "reconfirmed the −93 dBm reference level for
  frequencies above 144 MHz, but no statement was issued for the bands
  between 30 and 144 MHz"; the box itself says "above 30 MHz". OpenHamShack
  takes the box: everything from 30.000 MHz up (6 m, 4 m, and NB's 10 GHz
  downlink) uses −93 dBm. Exactly 30 MHz is in neither "below" nor
  strictly "above"; it is not an amateur frequency, and is put with VHF.
- **One S-unit = 6 dB.**
- **Ballistics:** attack 10 ms, decay time constant ≥ 500 ms. OpenHamShack's
  meter feed is 10 Hz, so its attack is one frame; its decay is 500 ms.
- Readings **above S9** are given as dB over S9 ("S9+20 dB"): the
  recommendation does not say so, but [S1] and every receiver do
  [unverified as a rule; universal as practice].

Used by `ohscore/ui/smeter.py` (both apps).

---

## 7. Not confirmed, to re-check before data files are written

- Whether the Ofcom booklet's *text* changed on 14 Oct 2025. The copy read
  says "Published 21 February 2024", while the web page is dated 14 Oct
  2025. The Phase 2/3 changes (M8/M9, revalidation) appear in O2 and O3.
- Which commit of the WSJT-X frequency table was read. Record the commit when
  `ohsradio/plans` is written.
- Any IARU R1 HF band-plan change after 2020.
- An official per-area CTCSS map for Scotland.
- The UK CTCSS deviation recommendation.
- The terms of reuse for the ukrepeater.net data.
- The text of IARU R1 Technical Recommendation R.1.
- Every source above was read on 2026-10-04 by a research agent, which
  downloaded and read the Ofcom booklet, the RSGB 2026 plan, the IARU HF
  plan and the VHF Handbook in full. **The line-by-line check of sections 1-3
  against the Ofcom booklet, Ofcom's guidance and the RSGB 2026 plan was done
  on 2026-10-04 and is recorded in [`licence-check.md`](licence-check.md)**
  (checksums, page of each row, four corrections made above). The IARU HF
  plan and the VHF Handbook were not part of that check.
