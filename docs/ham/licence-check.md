# Licence and band-plan data: the line-by-line check

The gate `bandplan-r1-uk.md` section 7 set before `ohsradio/licences/ofcom.py`
was written: every row of that document's Ofcom Schedule 1 table, its gap
list, the 60 m segments and conditions, the 431-432 MHz exclusion and the
RSGB 2026 rows for 160 m-10 m, 2 m, 70 cm and 23 cm, checked against the
PDFs themselves. Done 2026-10-04 by a research agent working from fresh
downloads (checksums below), converted with `pdftotext -layout`.

**What changed because of it** (all in `bandplan-r1-uk.md`, and the data
files follow): the 15 m satellite sub-band is 21125-21245 kHz, not
21125-21450; the 10 m repeater outputs row ends at 29700 kHz; the 2 m
simplex and RV rows have the plan's printed edges (simplex 145.200-145.5935,
inputs 144.990-145.1935, outputs 145.5935-145.7935 MHz) rather than first and
last channel centres; the WRC-15 sentence on 60 m is cited to the RSGB plan,
not the licence. No figure in the Ofcom power table was wrong.

**Decisions taken on the findings**: 2300-2302 MHz is refused (it is in no
row of Schedule 1, and Ofcom's own guidance does not list it among the NoV
bands even though the RSGB plan does); the airborne 500 mW EIRP limit is not
encoded (OpenHamShack HAM is not an airborne station); 15 m's satellite sub-band
is shared, not exclusive, so it is not refused - only the exclusive ones are
(10 m 29.300-29.510, 2 m 145.806-146.000, 70 cm 435-438 MHz, 3 cm 10.475-10.500 GHz).

Verdict key: **MATCH** / **MISMATCH** (gives the correct figure) /
**NOT FOUND** (claim not located in the cited source). The bandplan-r1-uk.md
quoted in the tables below is the version before the corrections.


## 1. Source files

| Key | URL used | SHA-256 | Pages | Printed date/version |
|---|---|---|---|---|
| O1 | https://www.ofcom.org.uk/siteassets/resources/documents/spectrum/emf/emf-amateur-licence-terms-and-conditions.pdf | `718e8136d3ebcf52559e48a8d9aa5cdd624691fec07d3609968d574935baded6` | 24 | Body text (p.1): "Published 21 February 2024". PDF `CreationDate`/`ModDate`: 28 Nov 2024 11:5x GMT. Title: "emf-amateur-licence-terms-and-conditions". |
| O2 | https://www.ofcom.org.uk/siteassets/resources/documents/manage-your-licence/amateur/amateur_radio_licence_guidance_for_licensees.pdf | `89fe14a5a818eaa8afc2c006ecff6710783c290bcd37da8ca2659168270dcd76` | 27 | Body text (p.1): **"Updated 14 October 2025"** (confirms the doc's Sources-table date exactly). PDF `CreationDate`/`ModDate`: 9 Oct 2025 08:1x/08:3x BST (file itself is a few days older than the printed "Updated" date — not a contradiction, Ofcom evidently republished text without rebuilding the PDF the same day, or vice versa). |
| R1 | https://rsgb.services/public/bandplans/docs/260125_rsgb_band_plan_2026.pdf — fetched directly, no fallback needed | `ea57433369857cc69be4dccc0fbb085ddcf1e8c16b5e2364bd96c2e1af773c83` | 34 | Front page: "RSGB 2026 Band Plan ... Updated: January-2026". PDF Title metadata: `260125_rsgb_band_plan_2026.xlsx` (matches the "file 260125" the doc cites). `CreationDate`/`ModDate`: 27 Jan 2026 10:25 GMT. |

All three downloaded with `curl -L -A <browser UA> --max-time 60`, HTTP 200 (428791, 490069 and 770359 bytes). Converted with `pdftotext -layout`.

---

## 2. Schedule 1 power-limit table (O1 Tables A/B/C) — every row

All 31 rows in the doc's merged Foundation/Intermediate/Full table were checked against O1 Table A (p.15–16), Table B (p.17–19) and Table C (p.20–22).

| Doc row (band) | Verdict | O1 page/table |
|---|---|---|
| 135.7–137.8 kHz | MATCH | A/B/C p.15,17,20 |
| 472–479 kHz | MATCH (absent from A & B, 5 W EIRP in C) | C p.20 |
| 1810–1830 kHz | MATCH | A/B/C p.15,17,20 |
| 1830–1850 kHz | MATCH | A/B/C p.15,17,20 |
| 1850–2000 kHz | MATCH (25/32/32 W) | A/B/C p.15,17,20 |
| 3500–3800 kHz | MATCH | A/B/C p.15,17,20 |
| 5 MHz, 11 segments | MATCH (absent A/B, 100 W/200 W EIRP C) | C p.20, Note G p.23 |
| 7000–7100 kHz | MATCH | A/B/C p.15,17,20 |
| 7100–7200 kHz | MATCH | A/B/C p.15,17,20 |
| 10100–10150 kHz | MATCH (25/100/**400 W**) | A/B/C p.15,17,20 |
| 14000–14250 kHz | MATCH | A/B/C p.15,17,20 |
| 14250–14350 kHz | MATCH | A/B/C p.15,17,20 |
| 18068–18168 / 21000–21450 / 24890–24990 kHz; 28.0–29.7 MHz | MATCH (each) | A/B/C p.15–16,17–18,20–21 |
| 50–51 MHz | MATCH | A/B/C p.15,17,20 |
| 51–52 MHz | MATCH (25/100/**100 W**, Full capped) | A/B/C p.16,17,20 |
| 70.0–70.5 MHz | MATCH (25/100/**160 W**) | A/B/C p.16,17,20 |
| 144–146 MHz | MATCH | A/B/C p.16,17,20 |
| 430–431 MHz | MATCH (25/**40/40 W ERP**) | A/B/C p.16,17,20 |
| 431–432 MHz (Charing Cross) | MATCH | A/B/C p.16,17,20 — see note below on coordinate typo |
| 432–435, 438–440 MHz | MATCH | A/B/C |
| 435–438 MHz | MATCH | A/B/C |
| 1240–1260, 1270–1325 MHz | MATCH (— /100/400; absent from A) | B/C p.17,20 |
| 1260–1270 MHz | MATCH (Earth→space only) | B/C p.17,20 |
| 2310–2350, 2390–2400 MHz | MATCH (absent from A) | B/C p.17,20 |
| 2400–2450 MHz | MATCH (2/100/400) | A/B/C p.16,17,20 |
| 3400–3410 MHz | MATCH (absent from A) | B/C p.18,21 |
| 5650–5670 MHz | MATCH | A/B/C |
| 5670–5680 MHz | MATCH | A/B/C |
| 5755–5765, 5820–5830 MHz | MATCH | A/B/C |
| 5830–5850 MHz | MATCH (absent from A) | B/C p.18,21 |
| 10.000–10.125, 10.225–10.450 GHz | MATCH (1/100/400) | A/B/C |
| 10.450–10.475 GHz | MATCH | A/B/C |
| 10.475–10.500 GHz | MATCH ("not allocated"/Sec.) | A/B/C |
| 24.00–24.05 GHz | MATCH (absent A; 100/1000) | B/C p.18,21 |
| 24.05–24.15 GHz | MATCH | B/C |
| 24.15–24.25 GHz | MATCH | B/C |
| 47.0–47.2, 75.875–76, 77.5–78, 134–136, 248–250 GHz | MATCH (absent A; 100/1000 each) | B/C p.18–19,21–22 |
| 75.5–75.875, 76–77.5, 78–81, 136–141, 241–248 GHz | MATCH (absent A; 100/400 each) | B/C p.18–19,21–22 |
| 122.25–123 GHz | MATCH (absent A; 100/400) | B/C p.19,21 |

**Every row checked matches O1 exactly**, including the bolded special-case values (32 W Int/Full on 1850–2000 kHz, 400 W on 10.10–10.15 MHz Full, 40 W ERP on 430–432 MHz, 100 W cap on 51–52 MHz Full, 160 W on 70 MHz Full). No wrong figures found in this table.

### Omissions from O1 Schedule 1 that the doc table drops (1.8 MHz – 5.85 GHz)

- **Airborne 500 mW EIRP.** Every Primary-status band in this range (1810–1830, 1830–1850, 3500–3800, 7000–7100, 7100–7200 in Tables A–C) carries an extra line in the source: *"500 mW EIRP airborne"*. The doc's per-row table drops this column entirely; it is only mentioned once, generically, in the prose above ("Airborne use: Primary bands only, at 500 mW EIRP"). That generic bullet is accurate but the table itself gives no way to tell, band by band, which rows it applies to (it is exactly "primary-status rows," which is consistent, but not stated).
- **Note (f)** ("Unless airborne power limits are stipulated for the frequency band, the use of Radio Equipment is not permitted airborne") is paraphrased, not quoted — fine, but worth knowing it exists as a formal note.
- **Source-internal inconsistency, not a doc error:** Table C's Charing Cross row prints the longitude as `(51°30'30''N,00°07'4''W)` — missing a digit — where Tables A and B both print `(51°30'30''N, 00°07'24''W)`. Verified against the raw extracted bytes (not a `pdftotext` artifact). The doc doesn't quote the coordinate at all, so this doesn't affect it, but it's worth knowing if anyone later copies coordinates out of Table C specifically.

### Gaps refused for every class

Confirmed by the row sequence in Tables B/C (Table A is a subset): 2350–2390 MHz (B/C jump 2310–2350 → 2390–2400), 3410–3475 MHz region (jump 3400–3410 → 5650–5670), 10.125–10.225 GHz (jump 10.000–10.125 → 10.225–10.450). **MATCH.** "13 cm above 2450 MHz" is likewise consistent (next row after 2400–2450 is 3400–3410).

### 60 m (O1 Table C, Note G)

All eleven segments (5258.5–5264, 5276–5284, 5288.5–5292, 5298–5307, 5313–5323, 5333–5338, 5354–5358, 5362–5374.5, 5378–5382, 5395–5401.5, 5403.5–5406.5 kHz) are **MATCH**, verbatim against O1 Table C, p.20. Power "100 W, max 200 W EIRP" **MATCH** (Table C: *"100 W (20 dBW) but not exceeding 200 W EIRP"*). Note G's itemised conditions on p.23 all **MATCH** the doc's bullet summary (6 kHz double-sideband bandwidth, 20 m antenna height, MOD non-interference, main-station-or-reported-temporary-location, telephone at hand, net call-sign rules). The doc's summary omits conditions IV (net calls restricted to military/cadet orgs) and V (care not to radiate outside the segment) — minor, not wrong, just not itemised.

One sentence is **NOT FOUND in O1**: *"The WRC-15 band 5351.5–5366.5 kHz is not granted separately; only its overlap with these segments may be used."* O1 Table C/Note G never mentions WRC-15 or 5351.5–5366.5 kHz at all (`grep -n "WRC\|5351" O1.txt` returns nothing). This fact is true and is correctly sourced elsewhere in the doc (§4, attributed to R1/IARU, and indeed R1's own 60 m notes state *"Note 4: Contacts within the UK should avoid the WRC-15 band (5351.5 - 5366.5 kHz) if possible"* — R1 p.10). The §1 sentence is simply mis-attributed to the O1 citation it sits under; it should cite R1, not O1.

### 431–432 MHz Charing Cross exclusion

**MATCH** against O1 Tables A/B/C (p.15–16/17/20) and independently corroborated by R1 p.22: *"Exclusion: 431-432 MHz not available within 100km radius of Charing Cross, London."* and *"Power Restriction: 430-432 MHz is 40W erp maximum."*

### Innovation bands statement

The doc's list — 70.5–71.5 MHz; 146–147 MHz (Scotland/40 km: ends 146.9375 MHz, 50 W ERP); 2300–2302 MHz; above 275 GHz — is **MATCH**, and the citation `[R1 notes]` is correct: R1 p.5 literally says *"Innovation Bands: 70.5-71.5 MHz, 146-147 MHz, 2300-2302 MHz and >275 GHz / Access to these bands requires an appropriate NoV, which is available to Full Licensees only"*. R1 p.21 confirms the 146–147 MHz Scotland/40 km carve-out and 50 W ERP cap (*"LICENCE NOTES: Full Licensees only, with NoV, 50W erp max"*, *"The absolute band frequency limit in or within 40km of Scotland is 146.93750 MHz"*).

**Worth flagging:** O2 §6.6, "Additional frequency bands" (p.24), Ofcom's own official list of NoV-accessible extra bands, is *shorter* — it names only 70.5–71.5 MHz, 146–147 MHz, and above 275 GHz. **It omits 2300–2302 MHz.** This isn't a doc error (the doc correctly cites R1, not O2, for the 2300–2302 MHz entry) but it is a real discrepancy between Ofcom's own guidance and the RSGB plan that the data file's author should be aware of before encoding "Innovation bands" as a single authoritative list — Ofcom's O1 Schedule 1 has no row for 2300–2302 MHz either way (it's a genuine schedule gap, sitting below the 2310 MHz start of the 13 cm amateur allocation).

### Foundation omissions

Confirmed directly from Table A (p.15–16): Table A has no row for 1240–1325 MHz (jumps 438–440 MHz → 2400–2450 MHz) and no row for 472–479 kHz or any 5 MHz/60 m segment. **MATCH** — "Foundation really has no 1240-1325 MHz and no 472 kHz/60 m" is correct.

---

## 3. RSGB 2026 HF band plan (R1) — 160 m to 10 m

| Band | Doc claim | Verdict | R1 page |
|---|---|---|---|
| 160 m | CW 1810–1838; narrow 1838–1840; all-modes 1840–2000 (LSB dial 1843); QRP 1836; DF beacons 1960 | MATCH | p.8 |
| 80 m | CW 3500–3570 (3500–3510 intercontinental); narrow 3570–3580(200 Hz)/3580–3600(500 Hz; 3590–3600 unattended); all-modes 3600–3800 (LSB dial 3603); QRS 3555, QRP 3560, DV 3630, UK emerg. 3663, SSB QRP 3690, image 3735, R1 emerg. 3760 | MATCH, every figure | p.9 |
| 60 m | all-modes/USB within the 11 segments; CW QRP 5262, UK emerg. 5278.5, beacons 5290, AM(6 kHz) 5317, WSPR 5362–5374.5 | MATCH | p.10 |
| 40 m | CW 7000–7040; narrow 7040–7050 (7047–7050 unattended); all-modes 7050–7200 (LSB dial 7053); QRP 7030, PSK31 from 7040, DV 7070, SSB QRP 7090, R1 emerg. 7110, image 7165; 7175–7200 intercontinental | MATCH, every figure | p.11 |
| 30 m | CW 10100–10130; narrow 10130–10150; no all-modes segment (SSB only in emergencies); QRP 10116; no contests/bulletins | MATCH | p.12 |
| 20 m | CW 14000–14070; narrow 14070–14099 (14089–14099 unattended); all-modes 14101–14350 (no digimodes 14112–14125); IBP 14099–14101; QRS 14055, QRP 14060, DV 14130, DXped 14195±5, image 14230, QRP 14285, emerg. 14300 | MATCH, every figure | p.13 |
| 17 m | CW 18068–18095; narrow 18095–18109; all-modes 18111–18168; IBP 18109–18111; QRP 18086, SSB QRP 18130, DV 18150, emerg. 18160 | MATCH | p.14 |
| 15 m | CW 21000–21070; narrow 21070–21110, 21120–21149; all-modes(no SSB) 21110–21120, all-modes 21151–21450; IBP 21149–21151; QRS 21055, QRP 21060, DV 21180, QRP 21285, image 21340, emerg. 21360; **satellites 21125–21450 (non-exclusive)** | **MISMATCH** on satellite sub-band; everything else MATCH | p.15 |
| 12 m | CW 24890–24915; narrow 24915–24929; all-modes 24931–24990; IBP 24929–24931; QRP 24906, SSB QRP 24950, DV 24960 | MATCH | p.16 |
| 10 m | CW 28000–28070; narrow 28070–28190; all-modes 28225–29700; IBP 28190–28225; QRS 28055, QRP 28060, DV 28330, QRP 28360, image 28680; FM simplex 29100–29200(10 kHz); satellites 29300–29510; rpt inputs 29520–29590, calling 29600, **outputs 29620–29690** (RH1–8, −100 kHz) | **MISMATCH** on repeater-output upper edge; everything else MATCH | p.17 |

### Mismatch 1 — 15 m satellite sub-band

Doc says *"satellites 21125–21450 (non-exclusive)"*. R1 p.15 actually says:

> "Note 1: 21,125-21,245 is also designated for use by amateur satellites"

**Correct figure: 21125–21245 kHz**, not 21125–21450 kHz. The upper bound looks like a typo/transposition (swapped the last two digits of "245" into something resembling the band's own upper edge "450").

### Mismatch 2 — 10 m FM repeater outputs

Doc says repeater *"outputs 29620–29690 (RH1–8, −100 kHz)"*. R1 p.17 literally says:

> "29,620-29,700    6 kHz    All modes - FM repeater outputs (RH1-RH8)"

**Correct figure per the printed segment: 29620–29700 kHz.** (Arithmetic note for whoever fixes this: the inputs are RH1–8 at 10 kHz spacing starting 29520 kHz, ending exactly at 29590 kHz for 8 channels; if the outputs are also 8 channels at 10 kHz spacing starting 29620 kHz, the last *channel centre* would fall at 29690 kHz — which is almost certainly where the doc's 29690 came from. But the band-plan row's own stated edge is 29700 kHz, 10 kHz wider than 8 channels strictly requires. Recommend using the printed row boundary, 29620–29700, since that's what R1 actually states, and treat 29690 as "last channel centre" if that distinction matters to the TX guard.) FM simplex 29100–29200, calling 29600, satellites 29300–29510, inputs 29520–29590, shift direction (output above input) and "−100 kHz" are otherwise correctly stated.

**Bandwidth-by-segment rule** ("CW only = 200 Hz; narrow band = 500 Hz; all modes = 2.7 kHz") is **MATCH**, confirmed as the literal bandwidth column value on every one of 160/80/40/20/17/15/12/10 m (60 m and 30 m use their own per-segment widths, as the doc's table already shows separately).

---

## 4. RSGB 2026 VHF/UHF band plan (R1) — 2 m, 70 cm, 23 cm

### 2 m (p.20–21)

| Item | Doc claim | Verdict |
|---|---|---|
| CW/MGM 144.025–144.150 (CoA 144.050) | MATCH | R1: "144.025-144.100 ... 144.050 MHz Telegraphy CoA" + "144.100-144.150 Telegraphy and MGM" — note this segment is Telegraphy **and MGM**, not pure CW; the doc's "CW" label is a slight simplification but the edges and CoA are right. |
| SSB/MGM 144.150–144.400 (SSB calling 144.300; MGM meteor scatter 144.370) | MATCH | — |
| Beacons 144.400–144.490 | MATCH | — |
| Image 144.500; data 144.600; UK DV calling 144.6125; APRS 144.800 | MATCH (all four) | — |
| FM simplex V16–V45, **145.200–145.5625** (12.5 kHz) | **MISMATCH** | R1: *"145.200-145.5935   12 kHz   FM/DV V16-V45 FM/DV simplex (Note 3) (Note 5) (Note-6)"*. Correct upper edge is **145.5935 MHz**, not 145.5625 MHz. 145.5625 MHz is the *centre frequency of the last named channel (V45)*, not the segment boundary — the segment itself continues up to 145.5935 MHz and that extra space is where the two low-power ad-hoc repeater outputs (145.5750, 145.5875 MHz) that the doc lists separately actually live. |
| FM calling 145.500 | MATCH | — |
| ISS 145.200 up / 145.800 down | MATCH | — |
| Satellites 145.806–146.000 | MATCH | R1: *"145.806-146.000 12 kHz All Modes - Satellite exclusive"* |
| RV48–RV63 repeaters: outputs **145.600–145.7875**, inputs **145.000–145.1875**, −600 kHz | **MISMATCH against the printed segment rows** | R1's own segment rows are *"144.990-145.1935 ... Repeater input exclusive"* and *"145.5935-145.7935 ... Repeater output"*. The doc's figures are not these — they are the first/last *channel centre* computed from Note 2 (*"RV48 input = 145.000 MHz, output = 145.600 MHz"*) extended arithmetically across 16 channels (RV48–RV63) at 12.5 kHz spacing. That arithmetic is internally consistent and the shift (**−600 kHz**, input below output) is correct either way, but if the data file is meant to record what the plan's segment-boundary rows actually say, those are 144.990–145.1935 kHz (input) and 145.5935–145.7935 kHz (output) — about 10 kHz wider on each side than the doc's channel-centre figures. |
| Low-power ad-hoc repeaters 144.975/145.575 and 144.9875/145.5875 | MATCH | R1: *"144.9750, 144.9875 MHz Low power / Adhoc repeater inputs (Note 11)"*, *"145.5750, 145.5875 MHz Low power / Adhoc repeater outputs (Note 11)"*, Note 11: "5W erp max" |

### 70 cm (p.22)

| Item | Doc claim | Verdict |
|---|---|---|
| Narrow band 432.000–432.400 (CW/SSB 432.200) | MATCH | — |
| Beacons 432.400–432.490 | MATCH | — |
| FM simplex U272–U286, 433.400–433.575 (calling 433.500) | MATCH (against the embedded channel list) | R1's row header for this stretch reads 433.3940–433.5810 (padded by half a channel each side); the named channels themselves run U272=433.4000 → U286=433.5750, calling U280=433.5000 — exactly what the doc states. |
| UK DV calling 438.6125 | MATCH | — |
| APRS alternative 433.800 | MATCH | — |
| Hotspots 434.000 / 438.800 | MATCH | — |
| Satellites 435–438 (DATV 437) | MATCH | R1: "435.0000-436.0000 Satellites only" + "436.0000-438.0000 Satellites and Experimental DATV/Data; 437.0000 ... CoA" |
| RB0–RB15: outputs 433.000–433.375, inputs 434.600–434.975, **+1.6 MHz** | MATCH | R1 embedded text gives exactly "433.0000-433.3750 MHz (RB0-RB15)" and "434.6000-434.9750 MHz (RB0-RB15)"; 434.600−433.000 = +1.6 MHz |
| RU65–RU78: outputs 430.8125–430.975, inputs 438.4125–438.575, **+7.6 MHz** | MATCH | R1: "430.8125-430.9750 MHz RU65-RU78 ... outputs", "438.4125-438.5750 MHz RU65-RU78 ... inputs"; 438.4125−430.8125 = +7.6 MHz |
| 9 MHz DV pairs: inputs 430.400–430.775, outputs 439.400–439.775, **−9 MHz** | MATCH | R1: "430.400-430.775 MHz UK DV 9MHz split repeaters - Inputs", "439.400-439.775 MHz UK DV 9MHz split repeaters - Outputs"; 430.400−439.400 = −9 MHz |
| RBW (5 MHz): outputs 433.000–433.375, inputs 438.000–438.375 | MATCH | R1: "...and RBW0-RBW30 5MHz split repeater outputs" (same 433.0000–433.3750 line) and "438.0000-438.3750 RBW00-RBW30 5MHz split repeaters - inputs" |
| Charing Cross exclusion + 40 W ERP power restriction | MATCH, independently corroborated | R1 p.22: "Exclusion: 431-432 MHz not available within 100km radius of Charing Cross, London." / "Power Restriction: 430-432 MHz is 40W erp maximum." |

### 23 cm (p.23)

| Item | Doc claim | Verdict |
|---|---|---|
| Narrow band 1296.150–1296.800 (centre 1296.200) | MATCH | — |
| Beacons 1296.800–1296.990 | MATCH | R1 embedded text: "1296.800-1296.990 MHz Propagation Beacons only" (row header 1296.800–1296.994 is the half-channel-padded version; doc's figure matches the quoted text) |
| Simplex SM20–SM30, 1297.500–1297.750 | MATCH | — |
| DV calling 1297.725 | MATCH | R1: "1297.725 MHz Digital Voice (DV) Calling (IARU recommended)" |
| RM0–RM15: outputs 1297.000–1297.375, inputs 1291.000–1291.375, **−6 MHz** | MATCH | R1: "1297.000-1297.375 MHz (RM0-RM15)" (output), "1291.000-1291.375 MHz (RM0-RM15) 25 kHz spacing" (input); 1291.000−1297.000 = −6 MHz |
| ATV outputs 1300–1325 (UK only) | MATCH | R1: "1300.000-1325.000 TV repeaters (UK only) (Note 9)" |

### 6 m and 4 m (checked incidentally, both referenced by the doc's VHF table)

Both fully **MATCH**: 6 m CW/beacon-project/SSB/MGM/beacon/DV/FM segments, outputs 50.720–50.870, inputs 51.220–51.370 (+500 kHz) and the new 2026 inputs 51.720–51.730 / 51.770–51.870 (+1 MHz) all confirmed verbatim on R1 p.18. 4 m beacons 70.000–70.090, narrow band 70.100–70.250 (CW/SSB 70.200, MS 70.250), AM/FM calling 70.260, MGM 70.270, FM calling 70.450, 12.5 kHz channels 70.294–70.500, "none" for repeaters, all confirmed verbatim on R1 p.19, including the Full-licence 160 W (22 dBW) cap cross-matching O1 Table C.

---

## Summary of actionable mismatches

1. **15 m satellite sub-band** (doc §2, 15 m row): doc says 21125–21450 kHz; R1 (p.15, Note 1) says **21125–21245 kHz**.
2. **10 m FM repeater outputs** (doc §2, 10 m row): doc says 29620–29690 kHz; R1 (p.17) literally says **29620–29700 kHz**.
3. **2 m FM simplex V16–V45 segment** (doc §3, 2 m row): doc says 145.200–145.5625 MHz; R1 (p.20) literally says **145.200–145.5935 MHz** — 145.5625 is channel V45's centre, not the segment edge.
4. **2 m RV48–RV63 repeater input/output ranges** (doc §3, 2 m row): doc gives computed channel-centre spans (145.000–145.1875 in / 145.600–145.7875 out); R1's printed segment rows (p.20) are **144.990–145.1935 in / 145.5935–145.7935 out**. Shift (−600 kHz) is right either way; only the absolute edges differ, by about half a channel on each side.
5. **60 m WRC-15 sentence** (doc §1): the claim about the WRC-15 band not being granted separately is not present anywhere in O1 — it should be cited to R1 (p.10, Note 4), not O1.
6. **Innovation-bands cross-check** (not a doc error, but a gap worth knowing about): Ofcom's own O2 §6.6 list of NoV-accessible bands (p.24) omits 2300–2302 MHz, which only appears in R1's "Innovation Bands" note (p.5). The doc correctly cites R1 for this, but a future reader shouldn't assume O1/O2 also grant NoV access to 2300–2302 MHz on the same footing as the other three.
7. **Omission, not an error:** the doc's Schedule-1 table drops the "500 mW EIRP airborne" figure that O1 attaches to every Primary-status HF/6m/2m row; it's covered only by one generic bullet elsewhere in §1.

No mismatches were found anywhere in the 31-row O1 Schedule 1 table itself, the four-item gap list, the eleven 60 m segments, the 431–432 MHz exclusion, the Foundation-omission claims, or in the 80 m / 40 m / 30 m / 20 m / 17 m / 12 m / 60 m / 6 m / 4 m / 70 cm / 23 cm band-plan rows.
