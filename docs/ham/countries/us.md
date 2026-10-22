# United States (US): amateur licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM (`ohsradio`) and OpenHamShack NB. This is
research only: no code reads it yet. It is modelled on
`docs/ham/bandplan-r1-uk.md`, whose UK data was checked line by line against
Ofcom's PDF (`docs/ham/licence-check.md`). The code interface for adding a
country is being defined separately in `docs/ham/adding-a-country.md`.

Markers:

- **[verified]**: read in the primary source. The citation gives the section
  and paragraph.
- **[secondary]**: from a non-regulator source only.
- **[derived]**: worked out here, not stated in a source.
- **UNCONFIRMED**: not found in a primary source. It must NOT be encoded as a
  permission until it is confirmed.

Two kinds of rule carry different weight. The FCC rules are law, so the TX
guard enforces them. The ARRL band plan is voluntary, so the guard only
warns.

**The rules changed this year.** The FCC rules on 60 m were rewritten with
effect from **13 Feb 2026** [F2]. Anything written about US 60 m before that
date is wrong.

## Sources

The regulatory text was read in eCFR's XML from the versioner API, "as of"
2026-10-06. That is the latest point-in-time the API serves, and no amendment
to Part 97 was published after 13 Feb 2026 (see F2/F3).

| Key | Document | Version / date | URL | SHA-256 (file read) |
|---|---|---|---|---|
| F1 | 47 CFR Part 97, "Amateur Radio Service" (eCFR, full part) | eCFR point-in-time 2026-10-06. Last amendments: 91 FR 1405/1430-1431 (14 Jan 2026, effective 13 Feb 2026) and 90 FR 57698 (12 Dec 2025, effective 10 Feb 2026). | https://www.ecfr.gov/api/versioner/v1/full/2026-10-06/title-47.xml?part=97 (human page: https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97) | `7b86cd2b22f11437adc8720a19fd244529295a1f76728c214cb91b4e3c4583e3` |
| F1a | The same, as of 2026-01-13 and 2026-01-20, diffed against F1 to see exactly what the 2026 order changed | eCFR | same API with those dates | (not kept) |
| F2 | FCC Report and Order FCC 25-60, ET Docket 23-120, "Implementation of the Final Acts of the World Radiocommunication Conference (Geneva, 2015) (WRC-15), Other Allocation Issues..." | Released 9 Dec 2025 [secondary: ARRL]; 91 FR 1405, published 14 Jan 2026, **effective 13 Feb 2026** | https://www.federalregister.gov/documents/2026/01/14/2026-00587/ | metadata via the federalregister.gov API |
| F3 | Federal Register API listing of every document affecting 47 CFR 97 | fetched 2026-10-08; newest entry is F2 | https://www.federalregister.gov/api/v1/documents.json?conditions[cfr][title]=47&conditions[cfr][part]=97 | — |
| F4 | 47 CFR 2.106, US Table of Frequency Allocations, including footnotes US23 (60 m), US103 (3.3 GHz), US275 (902 MHz) and 5.133B | eCFR point-in-time 2026-10-06 | https://www.ecfr.gov/api/versioner/v1/full/2026-10-06/title-47.xml?part=2&section=2.106 | `dd041c99153e7b6cacb4d7019797cea24e61b25540bd31f7dea61fed2fdc45ce` |
| F5 | FCC FR doc, "Facilitating Shared Use in the 3100-3550 MHz Band", 85 FR 64062 | 9 Oct 2020, effective 9 Nov 2020 | https://www.federalregister.gov/documents/2020/10/09/2020-22528/ | — |
| F6 | FCC Public Notice DA 16-1048, "Amateur Service Operation in CEPT Countries" | released 16 Sep 2016, 3 pp. | https://docs.fcc.gov/public/attachments/DA-16-1048A1.pdf | `129632912ba8396175cc4c473b873ccb946fb1e5075e817d3df7c459374a4a97` |
| C1 | CEPT Recommendation T/R 61-01, "CEPT Radio Amateur Licence" | Edition of 18 Oct 2024 (Annex 4 latest updated Oct 2024), 13 pp. | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` |
| C2 | ECC Recommendation (05)06, "CEPT Novice Radio Amateur Licence" | Edition 16 June 2023, 10 pp. | https://docdb.cept.org/download/4372 | `f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4` |
| A1 | ARRL, "Band Plan" web page | undated page. Its 60 m section reflects the Feb 2026 change. Fetched 2026-10-08. | https://www.arrl.org/band-plan | `bf3ee91b…67ce` (HTML) |
| A2 | ARRL, "US Amateur Radio Bands" chart (Hambands4, B/W 11×8.5) | "rev. 1/16/2026"; PDF dated 12 Feb 2026 | https://www.arrl.org/files/file/Regulatory/Band%20Chart/Hambands4_BW_11x8_5.pdf | `50110f1fd49f96af3abb7b4d65498c1e040e82bd856dc2f5f248c727dd3299b3` |
| A3 | ARRL, "3 GHz band" chronology page (quotes US103) | fetched 2026-10-08 | https://www.arrl.org/3-ghz-band | — |
| A4 | ARRL news, "Amateurs with General Class Licenses to be Granted Reciprocal Licenses in Some CEPT Countries" | 2009 | https://www.arrl.org/news/amateurs-with-general-class-licenses-to-be-granted-reciprocal-licenses-in-some-cept-countries | — |
| W1 | WSJT-X `models/FrequencyList.cpp`, as already used by `ohsradio/bands.py` | — | see `bandplan-r1-uk.md` | — |

The FCC's own web pages (fcc.gov) returned HTTP 403 to every fetch, both
through the fetch tool and through curl with a browser user-agent. Two things
therefore come from secondary sources and are marked as such: the
call-sign-group page, and the release date of F2.

---

## 1. Regulator and instruments

- **Regulator.** Federal Communications Commission (FCC). Within it, the
  Wireless Telecommunications Bureau handles amateur licensing. Federal
  (government) spectrum is managed by NTIA, and Part 97 defers to it through
  the sharing rules.
- **Governing instrument.** 47 CFR Part 97 [F1]. The parts that matter here:

| Section | Covers |
|---|---|
| §97.3 | Definitions: PEP, ERP, EIRP, Line A, NRQZ |
| §97.9 | Licence classes |
| §97.107 | Reciprocal operating |
| §97.119 | Identification |
| §97.203, §97.205, §97.207 | Beacons, repeaters, space stations |
| §97.301 | Frequency privileges by class |
| §97.303 | Sharing |
| §97.305 | Emissions per segment |
| §97.307 | Emission standards: bandwidth and symbol rate |
| §97.309 | Digital codes |
| §97.311 | Spread spectrum |
| §97.313 | Power |

- **The allocations are law too.** The binding allocations, with their
  footnotes, are in 47 CFR 2.106 [F4]. The Note to §97.303 says so: "The
  Table of Frequency Allocations contains the complete, unabridged, and
  legally binding frequency sharing requirements".
- **Regions.** §97.301 has a column for each ITU Region. A station uses the
  column of the Region it is in.
  - The 50 states, DC, Puerto Rico, the USVI, Navassa, Johnston and Midway
    are **Region 2**.
  - American Samoa, Baker, the CNMI, Guam, Howland, Jarvis, Kingman, Palmyra
    and Wake are **Region 3** [F1 Appendix 1].
  - **[derived]** OpenHamShack HAM must therefore ask which Region a US station is
    in. It cannot assume Region 2.
- **Altitude.** §97.301 applies only to a station "located within 50 km of
  the Earth's surface" [F1 §97.301 preamble].

## 2. Licence classes

The classes are Novice, Technician, General, Advanced and Amateur Extra
[F1 §97.9(a)]. New licences are issued only as Technician, General and Extra.
Novice and Advanced survive as renewals of existing grants [secondary:
general knowledge; §97.9 lists all five and does not say which are still
issued].

| Class | Suggested ohsradio key | Examination | Notes |
|---|---|---|---|
| Novice | `novice` | (no longer issued) | §97.301(e) band list, shared with Technician, plus separate power limits |
| Technician | `technician` | Element 2 | Everything in §97.301(a) (6 m and up), plus the §97.301(e) HF CW/10 m segments |
| General | `general` | Elements 2+3 | §97.301(a) + (d) |
| Advanced | `advanced` | (no longer issued) | §97.301(a) + (c) |
| Amateur Extra | `extra` | Elements 2+3+4 | §97.301(a) + (b) |

- **CEPT and IARP visitors.** A control operator with "a CEPT radio-amateur
  license or IARP of any class" gets §97.301(a). One holding "a CEPT radio
  amateur license, or ... a Class 1 IARP license" also gets §97.301(b), the
  Extra HF table [F1 §97.301(a),(b)].
  - **[derived]** In code, a CEPT visitor in the US is an `extra`.
  - A Canadian visitor is limited to the lesser of their Canadian
    privileges and Extra [F1 §97.107(a)].
- **Pending upgrade.** A holder of a CSCE who is awaiting an upgrade may use
  the higher class for up to 365 days, adding the indicator /KT, /AG or /AE
  [F1 §97.9(b), §97.119(f)].
  - **[derived]** ohsradio can model this simply as "set the higher class".

## 3. Frequency privileges and power, per class

**How power is measured [F1 §97.3(b)(9)].** "PEP" is "the average power
supplied to the antenna transmission line by a transmitter during one RF
cycle at the crest of the modulation envelope". It is measured at transmitter
output, not as DC input.

**The default limit.** Unless a row says otherwise, the limit is **1500 W PEP
transmitter output** [F1 §97.313(b)]. Over everything sits the duty to use
"the minimum transmitter power necessary" [§97.313(a)].

Column key:

- **N**: Novice
- **T**: Technician
- **G**: General
- **A**: Advanced
- **E**: Extra
- **"—"**: may not transmit there

Edges are as printed in §97.301, converted to kHz or MHz. **The Region 2
column is the default.** Where Region 3 differs it is noted. Region 1 does
not apply to US territory.

### 3.1 LF / MF / HF

**Power on HF.** Every class is limited to 1500 W PEP, except as noted in the
table. Novice and Technician are limited to 200 W PEP on their HF segments
[§97.313(c)(2)].

| Segment (R2) | R3 if different | N | T | G | A | E | Status / sharing | Source |
|---|---|---|---|---|---|---|---|---|
| 135.7–137.8 kHz (2200 m) | same | — | — | ✓ | ✓ | ✓ | Secondary. **1500 W PEP and ≤ 1 W EIRP.** Fixed stations only. UTC notification required (§3.4). | §97.301(b)-(d); §97.303(g); §97.313(k) |
| 472–479 kHz (630 m) | same | — | — | ✓ | ✓ | ✓ | Secondary. **500 W PEP and ≤ 5 W EIRP.** In Alaska within 800 km of Russia: **≤ 1 W EIRP**. Fixed stations only. UTC notification required. | §97.301(b)-(d); §97.303(g); §97.313(l) |
| 1800–2000 kHz (160 m) | same (R1 col: 1810–1850) | — | — | ✓ | ✓ | ✓ | (a) | §97.301(b)-(d) |
| 3500–3525 kHz | same | — | — | — | — | ✓ | (a) | §97.301(b) |
| 3525–3600 kHz | same | ✓ CW, 200 W | ✓ CW, 200 W | ✓ | ✓ | ✓ | (a) | §97.301(b)-(e); §97.307(f)(9); §97.313(c)(2) |
| 3600–3700 kHz | 3600–3700 | — | — | — | — | ✓ | | §97.301(b) |
| 3700–3800 kHz | 3700–3800 | — | — | — | ✓ | ✓ | | §97.301(b),(c) |
| 3800–4000 kHz | **R3: 3800–3900** (E/A/G); R3 Extra 3600–3900 | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 5 MHz (60 m) | see §3.3 | — | — | ✓ | ✓ | ✓ | Secondary. ERP limits. | §97.301(b)-(d); §97.303(h); §97.313(i) |
| 7000–7025 kHz | same | — | — | — | — | ✓ | | §97.301(b) |
| 7025–7125 kHz | same | ✓ CW, 200 W | ✓ CW, 200 W | ✓ | ✓ | ✓ | (i) | §97.301(b)-(e); §97.313(c)(2) |
| 7125–7175 kHz | same | — | — | — | ✓ | ✓ | | §97.301(b),(c) |
| 7175–7300 kHz | **R3: 7175–7200** (G); R3 E/A to 7200 | — | — | ✓ | ✓ | ✓ | 7.2–7.3 must accept broadcast interference (R1/R3 programming) | §97.301(b)-(d); §97.303(i) |
| 10100–10150 kHz (30 m) | same | — | — | ✓ **200 W** | ✓ **200 W** | ✓ **200 W** | Secondary to fixed service of other nations (j) | §97.301(b)-(d); §97.303(j); §97.313(c)(1) |
| 14000–14025 kHz | same | — | — | — | — | ✓ | | §97.301(b) |
| 14025–14150 kHz | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 14150–14175 kHz | same | — | — | — | — | ✓ | | §97.301(b) |
| 14175–14225 kHz | same | — | — | — | ✓ | ✓ | | §97.301(b),(c) |
| 14225–14350 kHz | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 18068–18168 kHz (17 m) | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 21000–21025 kHz | same | — | — | — | — | ✓ | | §97.301(b) |
| 21025–21200 kHz | same | ✓ CW, 200 W | ✓ CW, 200 W | ✓ | ✓ | ✓ | | §97.301(b)-(e); §97.313(c)(2) |
| 21200–21225 kHz | same | — | — | — | — | ✓ | | §97.301(b) |
| 21225–21275 kHz | same | — | — | — | ✓ | ✓ | | §97.301(b),(c) |
| 21275–21450 kHz | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 24890–24990 kHz (12 m) | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |
| 28000–28500 kHz | same | ✓ 200 W | ✓ 200 W | ✓ | ✓ | ✓ | N/T: CW and RTTY/data on 28.0–28.3; CW and SSB (J3E/R3E) on 28.3–28.5 | §97.301(e); §97.305(c)(3)(xvii),(xviii); §97.307(f)(10); §97.313(c)(2) |
| 28500–29700 kHz | same | — | — | ✓ | ✓ | ✓ | | §97.301(b)-(d) |

**One more Region 1/3 limit.** A station in ITU Region 1 or 3 is limited to
200 W PEP on 7050–7075 kHz [§97.313(c)(3)].

**[derived] Region 3 phone on 40 m.** In Region 3, phone/image on
7075–7100 kHz is allowed to classes that have that spectrum [§97.305(c)(3)(v),
§97.307(f)(11)]. So is the West-of-130°W / south-of-20°N part of Region 2,
i.e. Hawaii, part of Alaska, and Pacific possessions.

### 3.2 VHF / UHF / SHF / EHF: §97.301(a)

**Who may transmit here.** Technician, General, Advanced and Extra all have
§97.301(a), as do CEPT and IARP visitors of any class. Novice has none of
(a), only 222–225 MHz and 1270–1295 MHz from (e).

**Power.** 1500 W PEP unless the table says otherwise.

| Segment (R2) | R3 | Classes | Power | Status / sharing | Source |
|---|---|---|---|---|---|
| 50–54 MHz (6 m) | 50–54 | T,G,A,E | 1500 W PEP | (a) | §97.301(a) |
| 144–148 MHz (2 m) | 144–148 | T,G,A,E | 1500 W PEP | (a),(k): in R3, 146–148 MHz must accept interference from other nations' fixed/mobile | §97.301(a); §97.303(k) |
| 219–220 MHz | **R2 only** | T,G,A,E | **50 W PEP** | **Fixed point-to-point digital message forwarding only.** 30-day prior notice to ARRL, plus AMTS notice/approval within 640/80 km (§3.4) | §97.301(a); §97.303(l); §97.313(h) |
| 222–225 MHz (1.25 m) | **R2 only** | N,T,G,A,E | 1500 W PEP; **Novice 25 W PEP** | (a) | §97.301(a),(e); §97.313(d) |
| 420–430 MHz | **R2 only** (US by RR 5.270) | T,G,A,E | 1500 W PEP (50 W PEP in US270 areas) | **No transmitting north of Line A** (§3.4). Secondary to Canadian/US land mobile near Buffalo, Cleveland and Detroit. | §97.301(a); §97.303(m)(1)-(3) |
| 430–440 MHz | 430–440 | T,G,A,E | 1500 W PEP. **50 W PEP from US270 areas** (military radars) unless coordinated. **435–438 MHz Earth/telecommand stations: up to 611 W ERP / 1 kW EIRP**, with antenna elevation > 10°. | Secondary to US Gov radiolocation (b) | §97.301(a); §97.303(b),(d),(m); §97.313(f) |
| 440–450 MHz | **R2 only** | T,G,A,E | as 430–440 | (m)(3) | §97.301(a) |
| 902–928 MHz (33 cm) | **R2 only** | T,G,A,E | 1500 W PEP. **50 W PEP within 241 km of White Sands Missile Range.** | **Prohibited** inside the WSMR box (TX/NM 31°41′–34°30′N, 104°11′–107°30′W). Also prohibited outside the US and its R2 insular areas. **Colorado/Wyoming box** (39–42°N, 103–108°W) excludes 902.4–902.6, 904.3–904.7, 925.3–925.7 and 927.3–927.7 MHz. Secondary; must accept ISM. | §97.301(a); §97.303(n); §97.313(g); F4 US275 |
| 1240–1300 MHz (23 cm) | 1240–1300 | T,G,A,E (N: 1270–1295 only) | 1500 W PEP; **Novice 5 W PEP** | Secondary (b),(d),(o) | §97.301(a),(e); §97.313(e) |
| 2300–2310 MHz (13 cm) | 2300–2310 | T,G,A,E | 1500 W PEP | (d),(p). 2305–2310 is secondary to FCC fixed/mobile/radiolocation (WCS) | §97.301(a); §97.303(p) |
| **2310–2390 MHz** | — | **none** | — | **Not amateur. Refuse.** | §97.301(a) (gap) |
| 2390–2450 MHz (13 cm) | 2390–2450 | T,G,A,E | 1500 W PEP | (d),(e),(p). Must accept ISM interference (2400–2450). | §97.301(a); §97.303(e) |
| **3300–3450 MHz** | ? | **see note** | ? | **Not in Part 97.** Permitted only by footnote US103: amateur operation "may continue ... on a secondary basis while the band's future uses are finalized" and "may be required to cease ... at any time". 3450–3500 MHz ceased 14 Apr 2022 [A3]. | F4 US103; A2; A3 |
| 5650–5925 MHz (5 cm) | **R3: 5650–5850** | T,G,A,E | 1500 W PEP | (a),(b),(e),(r). 5850–5925 (R2) must accept FSS/ITS (ITS mobile). 5725–5875 must accept ISM. | §97.301(a); §97.303(r) |
| 10.0–10.5 GHz (3 cm) | 10.0–10.5 | T,G,A,E | 1500 W PEP | (a),(b),(k). Pulse prohibited (US128). | §97.301(a); F4 US128 |
| 24.00–24.25 GHz | same | T,G,A,E | 1500 W PEP | (b),(d),(e) | §97.301(a) |
| 47.0–47.2 GHz | same | T,G,A,E | 1500 W PEP | — | §97.301(a) |
| 76–81 GHz | same | T,G,A,E | **316 W peak EIRP** | (c),(f),(s) | §97.301(a); §97.313(m) |
| 122.25–123.00 GHz | same | T,G,A,E | 1500 W PEP | (e),(t) | §97.301(a) |
| 134–141 GHz | same | T,G,A,E | 1500 W PEP | (c),(f) | §97.301(a) |
| 241–250 GHz | same | T,G,A,E | 1500 W PEP | (c),(e),(f) | §97.301(a) |
| above 275 GHz | same | T,G,A,E | 1500 W PEP | (f) | §97.301(a) |

**Power by station type, not class.** Some limits depend on what the station
is, not on the operator's class:

- **Spread spectrum:** 10 W PEP transmitter output [§97.313(j)].
- **Beacons:** 100 W [§97.203(c)].

### Gaps inside nominal bands (refuse for every class)

- **2310–2390 MHz.**
- **3450–3500 MHz.** The amateur allocation ended 14 Apr 2022 [F5, A3].
- **3300–3450 MHz.** Recommend refusing this too, with a note; see §11.
- **420–430 MHz north of Line A** [§97.303(m)(1)].
- **902–928 MHz inside the White Sands box, and outside US R2 territory**
  [§97.303(n)(2)].
- **219–220 MHz for anything except fixed digital forwarding**
  [§97.303(l)(1)]. OpenHamShack HAM should refuse this sub-band outright.
- **Region 3: 222–225 MHz, 420–430 MHz, 440–450 MHz, 902–928 MHz,
  5850–5925 MHz, and 7200–7300 kHz.** None of these is in the R3 column.

### 3.3 60 m [F1 §97.303(h), §97.305(c)(3)(iii), §97.307(f)(14), §97.313(i); F4 US23 and 5.133B; F2]

These rules are in force from 13 Feb 2026.

- **Who.** General, Advanced and Extra [§97.301(b)-(d), each listing "60 m
  5.3515-5.3665 MHz" with sharing note (h)]. Technician and Novice have no
  60 m.
- **Where.** §97.303(h)(3): "amateur stations may transmit only in the
  5351.5-5366.5 kHz band and on the four center frequencies specified in the
  table below".

| Channel | Center (kHz) | USB carrier ("dial", kHz) | Limit | Status |
|---|---|---|---|---|
| 1 | 5332.0 | 5330.5 | **100 W ERP** | Secondary |
| 2 | 5348.0 | 5346.5 | **100 W ERP** | Secondary |
| (band) | 5351.5–5366.5 continuous | — | **9.15 W ERP** (= 15 W EIRP, RR 5.133B) | Secondary |
| 4 | 5373.0 | 5371.5 | **100 W ERP** | Secondary |
| 5 | 5405.0 | 5403.5 | **100 W ERP** | Secondary |

The old channel 3 (5358.5 kHz center / 5357.0 dial) **was removed** from the
table. It now lies inside the 5351.5–5366.5 band at 9.15 W ERP [F1a diff].

- **Emissions.** Phone, RTTY, data and CW only, and "Emissions must not
  exceed a bandwidth of 2.8 kilohertz" [§97.307(f)(14)(i)].
  - On the discrete channels, phone/data/RTTY (2K80J3E, 2K80J2D, 60H0J2B) "may
    set the carrier frequency 1.5 kHz below the center frequency". CW
    (150HA1A) is set **at** the center frequency [§97.303(h)(3)].
  - "For all 60 m spectrum, Amateur operators shall ensure that their
    emissions do not occupy more than 2.8 kHz."
- **What changed in 2026.** The old rule limited phone to USB. The old rule
  also had an emission table restricting designators. Both were removed in
  2026 [F1a diff of §97.307(f)(14)]. US23 [F4] still names the four
  designators for the four channels.
  - **[derived]** On the channels, keep the guard to USB-only with the
    signal centred. That is also what the ARRL plan says [A1].
- **How ERP is computed.** ERP = transmitter PEP × antenna gain relative to
  a half-wave dipole. A dipole is presumed to be 0 dBd. "Licensees using other
  antennas must maintain in their station records either the antenna
  manufacturer's data on the antenna gain or calculations of the antenna
  gain" [§97.313(i)].
- **Sharing.** Must not cause interference to, and must accept interference
  from:
  - US (NTIA/FCC) and other nations' fixed service;
  - other nations' mobile-except-aeronautical service [§97.303(h)(1),(2)].
- **Data transmissions.** Keep data/RTTY transmissions short "so as not to
  cause harmful interference to United States Government stations"
  [§97.307(f)(14)(ii)].
- **A wording mismatch, harmless.** §97.313(i) says "100 W ERP", while US23
  says "100 W PEP" ERP. Both mean a PEP-based ERP.

**[derived] Guard.** 60 m needs two kinds of power check:

- a **channel** check (≤ 100 W ERP, with the 2.8 kHz signal inside
  center ± 1.4 kHz);
- a **band** check (≤ 9.15 W ERP, wholly inside 5351.5–5366.5).

The guard must also ask for antenna gain in dBd; dBi − 2.15 = dBd.

**Note on the default FT8 dial.** The WSJT-X default dial of 5357 kHz
(`ohsradio/bands.py`) is inside the new band, but **only at 9.15 W ERP**.

### 3.4 Other per-band exceptions and notifications

- **2200 m and 630 m [§97.303(g)].**
  - "shall only operate at fixed locations".
  - Not within **1 km horizontal distance** of a transmission line carrying
    PLC on the same band.
  - **Prior notification to the Utilities Telecom Council** (UTC: call sign,
    band(s), antenna coordinates). Operation may begin "after the 30-day
    period unless UTC notifies the station" that it is within 1 km of PLC.
  - ARRL points at https://utc.org/plc-database-amateur-notification-process/
    [A1].
  - **[derived] Guard.** A per-band setting, "UTC notified on (date)",
    must be ≥ 30 days old before TX. A per-band "fixed station" checkbox is
    needed as well.
  - Must take "all necessary measures" if causing interference, including
    termination [§97.303(g)(5)].
- **219–220 MHz [§97.303(l)].**
  - Data forwarding only.
  - Written notification to ARRL ≥ 30 days before transmitting.
  - Within 640 km of an AMTS coast station: notify that AMTS licensee
    ≥ 30 days ahead.
  - Within 80 km: written approval from that AMTS licensee.
- **420–430 MHz.** "No amateur station shall transmit from north of Line A"
  [§97.303(m)(1)].
  - Line A is a polyline defined in §97.3(a)(30). It runs from Aberdeen WA,
    along 48°N, through Duluth, then along 85°W and 41°N, to Searsport ME.
  - **[derived]** A 4-character locator is too coarse near the line, so
    this should be an operator setting ("north of Line A"), as the UK's
    `nearLondon` is.
- **70 cm, 50 W PEP areas** [§97.313(f); §2.106 US270].
  - These are areas around military radars: parts of TX, FL, CA, MA, AZ/NM
    (White Sands), CO and others.
  - The coordinates are in the 2.106 footnote. **They were not extracted
    here; UNCONFIRMED list.**
  - **[derived]** Make this an operator setting.
- **33 cm** [§97.303(n)(2),(3); §97.313(g)]: the WSMR and CO/WY boxes as in
  the table above.
- **National Radio Quiet Zone** (MD/VA/WV box, §97.3(a)(33)). Applies only
  to beacons and to stations that need notification [§97.203(e)].
  - **Arecibo.** Repeaters within 16 km need notification [§97.205(h)].
  - These are station-establishment matters, not TX-guard matters.

## 4. Emission, bandwidth and symbol-rate limits

These come from F1 §97.305 and §97.307, as they stood 2026-10-06.

**CW is allowed on any frequency** authorized to the control operator
[§97.305(a)]. Everything else is restricted to the sub-bands below
[§97.305(c)].

**HF data and phone sub-bands** (all classes; your class still limits which
parts you may use):

| Band | RTTY / data | Phone / image |
|---|---|---|
| 160 m | entire band | entire band |
| 2200 m, 630 m | entire band | entire band (phone and image) |
| 80/75 m | 3500–3600 RTTY/data | 3600–4000 phone/image ("75 m entire band") |
| 40 m | 7000–7100 and 7100–7125 RTTY/data | 7125–7300 phone/image. 7075–7100 phone/image **only R1/R3 and R2 west of 130°W / south of 20°N** [§97.307(f)(11)]. |
| 30 m | entire band (no phone) | — |
| 20 m | 14000–14150 RTTY/data | 14150–14350 phone/image |
| 17 m | 18068–18110 RTTY/data | 18110–18168 phone/image |
| 15 m | 21000–21200 RTTY/data | 21200–21450 phone/image |
| 12 m | 24890–24930 RTTY/data | 24930–24990 phone/image |
| 10 m | 28000–28300 RTTY/data | 28300–29700 phone/image |

**Novice and Technician on HF.**

- On their 80/40/15 m segments they may transmit **CW only**, using
  international Morse [§97.307(f)(9)].
- On 28.3–28.5 MHz: CW, or **J3E/R3E (SSB)** only [§97.307(f)(10)].
- On 28.0–28.3 MHz, RTTY/data is allowed. (f)(9) is not attached to that row,
  so Technicians may run FT8 at 28.074.

**VHF and up.**

- 6 m: **50.0–50.1 MHz is CW-only**. 50.1–54 allows MCW, phone, image,
  RTTY and data; "test" is allowed from 51 MHz [§97.305(c)(4)].
- 2 m: **144.0–144.1 MHz is CW-only**. 144.1–148 is all modes [§97.305(c)(4)].
- 219–220 MHz: data only.
- 222–225 MHz: everything, including spread spectrum.
- UHF and up: everything, including SS. Pulse is allowed only on 33 cm,
  13 cm, 5 cm, 1.2 cm and the mm bands.

**Standards in §97.307(f)** (selected):

- **(f)(3) HF RTTY/data.**
  - Must use a specified code (§97.309(a)).
  - "The authorized bandwidth is **2.8 kHz** except in the 2200 m band and
    630 m band."
  - On 2200 m and 630 m: "the symbol rate must not exceed **300 bauds**, or
    for frequency-shift keying, the frequency shift between mark and space
    must not exceed 1 kHz."
  - **The HF 300-baud limit is gone.** It was replaced by the 2.8 kHz
    bandwidth limit by FCC 23-93 (88 FR 85126), effective 8 Jan 2024. It
    survives only on 2200 m and 630 m.
- **(f)(5) 6 m and 2 m**: specified codes "must not exceed **19.6
  kilobauds**". Unspecified codes are also allowed (§97.309(b)). "The
  authorized bandwidth is **20 kHz**."
- **(f)(6) 1.25 m (222–225) and 70 cm**: "must not exceed **56 kilobauds**";
  "The authorized bandwidth is **100 kHz**."
- **(f)(7) 33 cm and up**: no symbol-rate or bandwidth limit beyond (a)/(b).
- **(f)(13) 219–220 MHz**: unspecified codes allowed; "The authorized
  bandwidth is 100 kHz."
- **(f)(1)** No angle-modulated emission may have a modulation index above 1
  at the highest modulation frequency. This is the HF FM deviation limit.
- **(f)(2)** "No non-phone emission shall exceed the bandwidth of a
  communications quality phone emission of the same modulation type."
- **(f)(8)** Data designators A–R / 1,2,7,9,X / D,W are allowed where (f)(8)
  is cited, i.e. from 6 m upwards.
- **(f)(12)** F8E is allowed (33 cm and up).
- **(f)(14)** 60 m, as in §3.3.

**General standards.**

- **§97.307(b)**: "Emissions resulting from modulation must be confined to
  the band or segment available to the control operator."
  - **[derived]** The guard's "whole signal inside the segment" rule
    applies, including the class boundaries.
- **Spurious emissions** [§97.307(d),(e)]:
  - below 30 MHz: −43 dB, for transmitters installed after 1 Jan 2003;
  - 30–225 MHz: −60 dB (25 µW / −40 dB for ≤ 25 W).

**Spread spectrum** [§97.311]: 10 W PEP. Only between FCC-regulated points,
or with a country that permits it.

## 5. Antenna gain, ERP and EIRP

The definitions are in §97.3(b):

- **EIRP** = power supplied to the antenna × gain relative to isotropic.
- **ERP** = power × gain relative to a half-wave dipole.
- "Multiply ERP by 1.64 to convert to EIRP", i.e. +2.15 dB.

Where antenna gain matters:

- **Mostly it does not.** US power limits are **transmitter output PEP**
  almost everywhere, and gain is irrelevant to them.
- **Gain does matter on:**
  - 60 m (ERP, dipole presumed 0 dBd);
  - 2200 m (1 W EIRP);
  - 630 m (5 W EIRP, or 1 W EIRP in western Alaska);
  - 435–438 MHz satellite uplinks (611 W ERP / 1 kW EIRP);
  - 76–81 GHz (316 W peak EIRP).
- **Gain on 60 m.** It must be documented in the station records
  (§97.313(i)).
- **Feedline loss.** None of the definitions credits feedline loss
  ("power supplied to the antenna"). **[derived]** OpenHamShack should let the
  operator enter the loss, as the UK guard's power chain does.

## 6. Station types

- **Repeaters** [§97.205].
  - Any Technician or higher may be a repeater licensee or control operator.
  - A repeater may operate on 10 m and up **except** in these segments:
    28.0–29.5, 50.0–51.0, 144.0–144.5, 145.5–146.0, 222.00–222.15,
    431.0–433.0 and 435.0–438.0 MHz.
  - A repeater may be automatically controlled.
  - Coordination is voluntary but carries weight in interference disputes
    (§97.205(c)).
- **Beacons** [§97.203].
  - Technician or higher.
  - At most 1 channel per band, at 100 W.
  - Automatic control is allowed only in these segments:
    - 28.20–28.30 MHz
    - 50.06–50.08 MHz
    - 144.275–144.300 MHz
    - 222.05–222.06 MHz
    - 432.300–432.400 MHz
    - 33 cm and up
  - NRQZ notification is required in the MD/VA/WV box.
- **Auxiliary, telecommand, and automatically controlled digital stations**
  are covered by §97.201, §97.211–97.215 and §97.221. They are not relevant to
  a single-operator transceiver.
- **Space stations** [§97.207(c)]. Space stations may use:
  - 17 m, 15 m, 12 m and 10 m;
  - 6 mm, 4 mm, 2 mm and 1 mm;
  - the segments 7.0–7.1 MHz, 14.00–14.25, 144–146, 435–438, **2400–2450**,
    5830–5850, 10.45–10.50 GHz and 24.00–24.05 GHz.
- **Earth and telecommand stations**: 611 W ERP / 1 kW EIRP on 435–438 MHz,
  as above.
- **13 cm amateur-satellite status [verified].** 2400–2450 MHz is authorized
  to US space stations (§97.207(c)(2)). Internationally it is an
  amateur-satellite band under RR 5.282 [F4], which also covers 435–438,
  1260–1270 (uplink only), 3400–3410 (R2/R3) and 5650–5670 (uplink only).
  - **QO-100 (25.9°E) is not visible from any US state or territory**
  [derived]. A geostationary satellite is above the horizon only within
  about 81° of longitude of its sub-point, and less away from the equator.
  That puts the limit near 55°W even at the equator. Puerto Rico and the
  USVI, at about 65°W, are about 91° away. Satellite rules therefore matter
  only for LEO work.
- **[derived] What the guard should refuse.** On the strength of the ARRL
  plan [A1], the guard should treat these as "satellite" and refuse them, as
  the UK guard does:
  - 435–438 MHz ("Satellite only (internationally)");
  - 145.80–146.00 MHz ("OSCAR subband");
  - 29.300–29.510 MHz.
  - Only 435–438 has legal force behind it, and only for repeaters
    (§97.205(b)).

## 7. Call signs, indicators and identification

- **Format** [secondary, FCC sequential call sign system page, which
  returned 403]:
  - one- or two-letter prefix (K, N, W, AA–AL, KA–KZ, NA–NZ, WA–WZ);
  - a digit 0–9;
  - a one- to three-letter suffix.
- **Groups by class:**
  - Group A (Extra): 1×2, 2×1, and 2×2 with AA–AL.
  - Group B (Advanced): 2×2.
  - Group C (Technician/General): 1×3.
  - Group D (Novice, or by request): 2×3.
- **Vanity calls.** A licensee may hold a vanity call from their class's
  group or a lower one. **[derived]** As with the UK, a format check against
  the class can only warn.
- **Call areas.** C1 Table 3 lists the call area digit for each state and
  territory:

| Digit | States |
|---|---|
| W1 | CT, ME, MA, NH, RI, VT |
| W2 | NJ, NY |
| W3 | DE, DC, MD, PA |
| W4 | AL, FL, GA, KY, NC, SC, TN, VA |
| W5 | AR, LA, MS, NM, OK, TX |
| W6 | CA |
| W7 | AZ, ID, MT, NV, OR, UT, WA, WY |
| W8 | MI, OH, WV |
| W9 | IL, IN, WI |
| W0 | CO, IA, KS, MN, MO, NE, ND, SD |

  Prefixes outside the 48 contiguous states [C1]:

| Prefix | Area |
|---|---|
| KL7 | Alaska |
| KH6 | Hawaii |
| KP4 | Puerto Rico |
| KP2 | USVI |
| KH2 | Guam |
| KH0 | CNMI |
| KH8 | American Samoa |
| KH1 | Baker/Howland |
| KH3 | Johnston |
| KH4 | Midway |
| KH5 | Palmyra/Jarvis |
| KH5K | Kingman |
| KH7 | Kure |
| KH9 | Wake |
| KP1 | Navassa |
| KP5 | Desecheo |

  - A call's digit does **not** have to match where the station is now.
    Calls are not reissued when a licensee moves [secondary, general
    knowledge]. There is no compulsory portable indicator.
- **Indicators** [§97.119(c)]. Optional self-assigned indicators (e.g.
  "/7", "/M", "/QRP") must be separated by "/" (or a word for it). They may go
  before, after, or both. They must not conflict with another country's
  prefix. **There is no regional letter or compulsory "/P"** of the UK kind.
- **Identification** [§97.119(a),(b)].
  - The call sign goes at the end of each communication and **at least every
    10 minutes**.
  - Allowed forms: CW (≤ 20 wpm if sent by an automatic ID device), English
    phone, or RTTY/data in a specified code when the communication itself is
    digital.
  - An image emission may be used under §73.682.
- **Reciprocal visitors** [§97.119(g)]. The indicator for the station's
  location goes **before** the home call, e.g. "W4/G4ABC". **Canadians put it
  after**, e.g. "VE3ABC/W4". At least once per contact, the visitor must give
  the location by city and state.

## 8. Reciprocal operating

**Visitors in the US** [§97.107]:

- Non-US citizens holding their own government's licence may operate where
  there is a multilateral or bilateral arrangement.
- They may not exceed **Extra** privileges.
- US citizens and FCC licensees cannot use §97.107.
- **CEPT T/R 61-01** holders get the CEPT-licence privileges, which in the US
  means **Amateur Extra** [C1 Annex 4 Table 3, col. 4]. §97.301(a)/(b)
  explicitly includes "a CEPT radio-amateur license".
- **CEPT Novice** holders (ECC Rec (05)06) operate on "the operating terms
  and conditions of the amateur service licence granted by the alien's
  government", i.e. those of the CEPT Novice Licence [C2 Annex 4].
- **IARP** (CITEL Inter-American Amateur Radio Permit): any class gives
  §97.301(a). Class 1 also gives §97.301(b) [F1].
- **Canada**: under the US–Canada Convention (TIAS 2508), on Canadian terms,
  capped at Extra [§97.107(a)].

**US licensees abroad:**

- **CEPT** [F6, C1, C2]. Applies to US *citizens* only.
  - **Amateur Extra or Advanced** = CEPT Radio Amateur Licence (T/R 61-01).
  - **General** = CEPT Novice (ECC Rec (05)06), only in countries that
    implement (05)06. The UK, France and Italy did not, as of [A4]; check
    the current list on docdb.
  - **Technician** has no CEPT reciprocity.
  - The operator must carry the FCC PN DA 16-1048, proof of citizenship and
    the licence [F6].
- **IARP**: CITEL countries [secondary].
- **Canada**: under the TIAS 2508 convention [secondary for the Canadian
  side; see `ca.md`].

## 9. ARRL band plan (voluntary)

Source [A1], fetched 2026-10-08. The page itself is undated. The ARRL Board
adopted the 222 MHz section in July 1991 and the 902 MHz and up sections in
2012. The page says the 2 m plan "has been proposed by the ARRL VHF-UHF
Advisory Committee". The chart [A2] is rev. 1/16/2026.

| Band | Plan rows [A1] |
|---|---|
| 2200 m / 630 m | 135.7–137.8: 1 W EIRP max. 472–479: 5 W EIRP max (1 W EIRP in Alaska within 496 miles of Russia). **Register with UTC first.** |
| 160 m | 1.800–2.000 CW. 1.800–1.810 digital. 1.810 CW QRP. 1.843–2.000 SSB, SSTV and other wideband modes. 1.910 SSB QRP. 1.995–2.000 experimental. 1.999–2.000 beacons. |
| 80 m | 3.570–3.600 RTTY/data. 3.590 RTTY/data DX. 3.790–3.800 DX window. 3.845 SSTV. 3.885 AM calling. |
| 60 m | 5330.5, 5346.5, 5371.5, 5403.5 (USB dial): "USB phone and CW/RTTY/data". 5351.5–5366.5: "USB phone and CW/RTTY/data; 9.15 watts ERP Maximum". "Only one signal at a time is permitted on individual frequencies (channels)". The 15 kHz band "will only support multiple QRP users". Note 2: "CW and digital emissions must be centered 1.5 kHz above the channel frequencies indicated", i.e. above the USB dial frequency. |
| 40 m | 7.040 RTTY/data DX. 7.080–7.125 RTTY/data. 7.171 SSTV. 7.290 AM calling. |
| 30 m | 10.130–10.140 RTTY. 10.140–10.150 packet. |
| 20 m | 14.070–14.095 RTTY. 14.095–14.0995 packet. **14.100 NCDXF beacons.** 14.1005–14.112 packet. 14.230 SSTV. 14.286 AM calling. |
| 17 m | 18.100–18.105 RTTY. 18.105–18.110 packet. |
| 15 m | 21.070–21.110 RTTY/data. 21.340 SSTV. |
| 12 m | 24.920–24.925 RTTY. 24.925–24.930 packet. |
| 10 m | 28.000–28.070 CW. 28.070–28.150 RTTY. 28.150–28.190 CW. **28.200–28.300 beacons.** 28.300–29.300 phone. 28.680 SSTV. 29.000–29.200 AM. **29.300–29.510 satellite.** 29.520–29.590 repeater inputs. 29.600 FM simplex. 29.610–29.700 repeater outputs. |
| 6 m | **50.0–50.1 CW, beacons. 50.060–50.080 beacon sub-band.** 50.1–50.3 SSB, CW. 50.10–50.125 DX window. 50.125 SSB calling. 50.3–50.6 all modes. 50.6–50.8 non-voice. 50.62 digital (packet) calling. 50.8–51.0 radio remote control (20 kHz channels). 51.0–51.1 Pacific DX window. 51.12–51.48 repeater inputs (19 channels). 51.62–51.98 repeater outputs. 51.5–51.6 simplex. 52.0–52.48 inputs. 52.5–52.98 outputs. 52.525 primary FM simplex. 52.54 secondary. 53.0–53.48 inputs. 53.5–53.98 outputs. 53.0 remote base simplex. 53.1/53.2/53.3/53.4 and 53.5/53.6/53.7/53.8 radio remote control. 52.02, 52.04, 53.02, 53.52, 53.9 simplex. **[derived] Repeater pairs are 500 kHz apart** (51.12→51.62, 52.0→52.5, 53.0→53.5). |
| 2 m | 144.00–144.05 EME (CW). 144.05–144.10 general CW and weak signal. 144.10–144.20 EME and weak-signal SSB. **144.200 national calling.** 144.200–144.275 general SSB. **144.275–144.300 propagation beacons.** 144.30–144.50 "New OSCAR subband". 144.50–144.60 linear translator inputs. 144.60–144.90 FM repeater inputs. 144.90–145.10 weak signal and FM simplex (145.01/.03/.05/.07/.09 packet). 145.10–145.20 linear translator outputs. 145.20–145.50 FM repeater outputs. 145.50–145.80 misc. and experimental. **145.80–146.00 OSCAR subband.** 146.01–146.37 repeater inputs. 146.40–146.58 simplex. **146.52 national simplex calling.** 146.61–146.97 repeater outputs. 147.00–147.39 repeater outputs. 147.42–147.57 simplex. 147.60–147.99 repeater inputs. **[derived] Offset is ±600 kHz.** Below 147 MHz the input is lower (−600). From 147.00 up the input is higher (+600). |
| 1.25 m | 222.0–222.150 weak-signal modes. 222.0–222.025 EME. **222.05–222.06 propagation beacons.** 222.1 SSB/CW calling. 222.15–222.25 local option. 222.25–223.38 FM repeater inputs only. 223.40–223.52 FM simplex. 223.52–223.64 digital, packet. 223.64–223.70 links, control. 223.71–223.85 local option. 223.85–224.98 repeater outputs only. **[derived] Offset is −1.6 MHz**, the conventional pairing; not stated in A1. |
| 70 cm | 420.00–426.00 ATV repeater or simplex, control links, experimental. 426.00–432.00 ATV simplex (427.250 video). 432.00–432.07 EME. 432.07–432.10 weak-signal CW. **432.100 calling.** 432.10–432.30 mixed-mode weak signal. **432.30–432.40 propagation beacons.** 432.40–433.00 mixed-mode weak signal. 433.00–435.00 auxiliary/repeater links. **435.00–438.00 "Satellite only (internationally)".** 438.00–444.00 ATV repeater input (439.250 video) and links. 442.00–445.00 repeater inputs and outputs (local option). 445.00–447.00 shared aux/control/repeaters/simplex. **446.00 national simplex.** 447.00–450.00 repeater inputs and outputs (local option). **[secondary/derived] Offset is ±5 MHz, set by local coordinators.** A1 does not fix the direction. |
| 33 cm | 902.000–902.075 repeater inputs (25 MHz split, paired with 927.000–927.075) or weak signal. 902.075–902.125 weak signal. 902.100 weak-signal calling (regional option). 902.125–903.000 repeater inputs (paired with 927.125–928.000). 903.000–903.100 beacons and weak signal. 903.100 calling (regional option). 903.100–903.400 weak signal. 903.400–909.000 mixed modes. 909–915, 915–921 and 921–927 broadband multimedia (ATV, DATV, SS). 927.000–927.075 and 927.125–928.000 repeater outputs. 927.075–927.125 simplex. 927.500 FM simplex calling. |
| 23 cm | 1240–1246 ATV ch.1. 1246–1248 FM/digital links, paired with 1258–1260. 1248–1252 digital. 1252–1258 ATV ch.2. 1260–1270 satellite uplinks, experimental, simplex ATV. 1270–1276 repeater inputs (25 kHz), paired with 1282–1288. 1276–1282 ATV ch.3. 1282–1288 repeater outputs. 1288–1294 broadband experimental, simplex ATV. 1294–1295 FM simplex (**1294.500 national FM simplex calling**). 1295.000–1295.800 narrow-band image, experimental. 1295.800–1296.080 EME. 1296.080–1296.200 CW/SSB weak signal (**1296.100 calling**). **1296.200–1296.400 beacons.** 1296.400–1297.000 general narrow band. 1297–1300 digital. Note: "The need to avoid harmful interference to FAA radars may limit amateur use of certain frequencies in the vicinity of the radars." |
| 13 cm | 2300.000–2303.000 analog and digital, paired with 2390–2393. 2303.000–2303.750 (< 50 kHz). 2303.75–2304.000 SSB/CW/digital weak signal. 2304.000–2304.100 EME. 2304.10–2304.300 weak signal (**2304.100 national weak-signal calling**). **2304.300–2304.400 beacons.** 2304.400–2304.750 SSB/CW/digital and NBFM (≤ 6 kHz). 2304.750–2305.000 (< 50 kHz). 2305.000–2310.000 analog and digital (2305–2310 is primary WCS, Part 27). **2310–2390 NON-AMATEUR.** 2390–2400 paired channels. **2400.000–2410.000 "Amateur Satellite Communications" (≤ 6 kHz).** 2410.000–2450.000 broadband modes (≤ 22 MHz). 2424.100 Japanese EME TX. |
| 9 cm | A1 still carries the full 3300–3500 MHz plan from 2012. 3400.000–3410.000 is "Amateur Satellite Communications" and 3400.100 EME calling. **The 3450–3500 rows are obsolete (cessation 2022)**, and 3300–3450 continues only under US103. |

**FT8/FT4/WSPR dials.** No ARRL table gives them. WSJT-X's defaults for
Region 2, already in `ohsradio/bands.py` [W1], are used in practice:

| Band | FT8 dial (MHz) |
|---|---|
| 160 m | 1.840 |
| 80 m | 3.573 |
| 60 m | 5.357 (only at 9.15 W ERP) |
| 40 m | 7.074 |
| 30 m | 10.136 |
| 20 m | 14.074 |
| 17 m | 18.100 |
| 15 m | 21.074 |
| 12 m | 24.915 |
| 10 m | 28.074 |
| 6 m | 50.313 |
| 2 m | 144.174 |
| 70 cm | 432.174 |

**[derived] Shapes that differ from the UK and Region 1**, and so matter to
the code:

- Bands are wider: 160 m runs to 2000 kHz, 80 m to 4000, 40 m to 7300,
  6 m to 54 MHz, 2 m to 148 MHz, and 70 cm covers 420–450 MHz.
- 1.25 m and 33 cm exist only in Region 2.
- There is no 4 m (70 MHz).
- Repeater offsets: 6 m 500 kHz; 2 m ±600 kHz, with the direction depending
  on the sub-band; 70 cm 5 MHz.
- The class boundaries inside HF bands are **legal** sub-bands, not plan
  sub-bands.

## 10. Pending changes (as of 2026-10-08)

- **VHF/UHF symbol rate.** The Further Notice in WT Docket 16-239 (FCC 23-93,
  88 FR 85171, 7 Dec 2023) proposed removing the 19.6/56 kbaud limits on
  6 m, 2 m, 1.25 m and 70 cm, and asked what bandwidth limit to use instead.
  It also asked about 2200 m and 630 m.
  - **No order has been published.** The eCFR text of 2026-10-06 still has
    19.6 kbaud / 20 kHz and 56 kbaud / 100 kHz.
  - Re-check §97.307(f)(3),(5),(6) before each release.
- **3300–3450 MHz.** This may be withdrawn "at any time" (US103).
- **Removed rules.** The "Delete, Delete, Delete" order (90 FR 57698,
  effective 10 Feb 2026) removed §§97.27–97.29, §97.315(b)(2), §97.521(b) and
  Appendix 2. None of these affects frequencies or power.
- **Re-check before each release.** Re-run the eCFR versioner query
  (`/api/versioner/v1/versions/title-47.json?part=97`) and look for entries
  dated after 2026-02-13.

## 11. Confidence and gaps

**Confidence: HIGH** for everything marked with a § citation. It was read
directly from the eCFR XML of 2026-10-06, and diffed against January 2026 to
isolate the 60 m change.

**UNCONFIRMED / gaps:**

1. **3300–3450 MHz: which classes, and under what limits.** Part 97 no longer
   lists the band. US103 permits continued secondary use but names no class
   and no power. ARRL's chart lists it among bands open to all classes except
   Novice [A2].
   - **Recommendation: refuse in the guard**, with the message "permitted
     only under US103, may be withdrawn at any time", until someone decides
     otherwise.
2. **The 70 cm 50 W PEP areas (§2.106 US270).** The coordinates were not
   extracted. Model this as an operator setting, not a location check.
3. **The call-sign-group mapping** (§7) is from secondary sources; the FCC
   page returned 403. Use it only for warnings.
4. **The F2 release date (9 Dec 2025)** is from ARRL. The FR publication and
   effective dates come from federalregister.gov.
5. **Which classes are still issued** (Novice and Advanced renewal-only)
   rests on general knowledge, not on §97.9's text.
6. **ARRL band plan dates.** A1 is undated. The 2 m section is described as
   "proposed". Repeater offsets for 70 cm and 1.25 m are convention, not
   plan text.
7. **The current CEPT (05)06 list** (which countries accept US Generals) was
   not extracted; C2 Annex 2 has it. **The IARP list of countries** was not
   researched.
8. **The Region 3 territories.** The R3 column was read, but the US-specific
   notes for them were not cross-checked against §2.106 Region 3 footnotes.

**Biggest risks for the guard:**

- **60 m.** It changed in Feb 2026. The old fifth channel, 5358.5, is gone;
  the new continuous band is limited to 9.15 W ERP; and the guard needs an
  ERP computation with antenna gain in dBd.
- **The class sub-band edges on HF.** These are legal limits, and they move
  by Region: Region 3 differs on 75 m and 40 m.
- **Operator-location rules.** Line A, White Sands, CO/WY, the 70 cm radar
  areas and Region 3 territories all depend on where the operator is. They
  need operator settings.
