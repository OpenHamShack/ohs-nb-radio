# Canada (CA): amateur licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM (ohsradio) / OpenHamShack NB. Research only - no
code reads this file yet. Modelled on docs/ham/bandplan-r1-uk.md, whose UK
data was checked line by line against Ofcom's PDF (docs/ham/licence-check.md).

Markers: **[verified]** read in the primary source (cite page/section/clause);
**[secondary]** from a non-regulator source only; **[derived]** worked out
here; **UNCONFIRMED** not found in a primary source - must NOT be encoded as
a permission until confirmed. Never guess a limit.

The licence is law (the TX guard enforces it); the band plan is a voluntary
code (the guard warns).

**Shape of the Canadian regime, in one paragraph.** Canada has no station
licence for amateurs (abolished 2000); a person holding an *Amateur Radio
Operator Certificate* is exempt from the licence requirement (Regs s.15.3).
The binding technical rules are **RBR-4 Issue 3 (July 2022)**, made binding
by s.45 of the Radiocommunication Regulations. RBR-4 regulates **bandwidth,
not modes** (except on 60 m), and expresses power as a **transmitter** limit
(DC input, or RF output into a matched load) that depends only on whether
the holder has the Advanced qualification - not on band. The only radiated-
power limits are 2200 m (1 W EIRP), 630 m (1 W EIRP; 5 W unconfirmed) and
60 m (100 W ERP PEP). HF (< 30 MHz) access needs Honours, Morse, or Advanced
on top of Basic.

## Sources

Working copies were kept in a session scratchpad, not in the repo; the checksums identify exactly what was read. HTML pages: SHA-256 is of the HTML as
fetched 2026-10-08; "pages" for HTML = not paginated, cited by section.

| Key | Document (exact title) | Version / date (as printed) | URL | SHA-256 of the file read, pages |
|---|---|---|---|---|
| R4 | RBR-4, "Standards for the Operation of Radio Stations in the Amateur Radio Service" (Regulation by Reference) | "Issue 3 / July 2022" (PDF created 2022-08-03). ISED's amateur publications list (page dated 2025-07-15, key PUB) still lists Issue 3 July 2022 as current; no Issue 4 found. | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/sites/default/files/attachments/2022/RBR-4-i3-2022-07EN.pdf | e805024a0ea5de502169457c101a2f15227837a04b2ee8d4c0e6cd8fd9c5acdd, 19 PDF pages (i-iii + printed pp.1-16). Cited by printed page. |
| RR | Radiocommunication Regulations, SOR/96-484 (Justice Laws full text) | "current to 2026-09-21 and last amended on 2021-04-01" | https://laws-lois.justice.gc.ca/eng/regulations/SOR-96-484/FullText.html | e4050f14ec42e1e1a5cb1643a2485f504c7edb33cd927613565af07a484368af (HTML) |
| R3 | RIC-3, "Information on the Amateur Radio Service" | "Issue 5 / March 2022"; page "Date modified: 2022-03-21". Note: RICs "have no status in law" (preface). | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/licences-and-certificates/radiocom-information-circulars-ric/ric-3-information-amateur-radio-service | 61dc8778d38aeb167024849dafc4b0ee5ddb3f724a2754b0416ef25f5f923547 (HTML) |
| R9 | RIC-9, "Call Sign Policy and Special Event Prefixes" | "Issue 2 (Provisional), October 2005"; page modified 2016-04-25; "no status in law" | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/node/314 | f73fa66980cb14648c20537207dafee7ea4ff7afd2ee686f03e012e4b9cbd711 (HTML) |
| R3B | RBR-3, "Technical Requirements Respecting Identification of Radio Stations" | "Issue 1 / September 2007" | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/sites/default/files/attachments/2022/rbr3e.pdf | 7ad2d1ba429747287db53420867d35c040f619f1e1a1277e60f7344c3c025cf3, 4 pp. |
| PUB | ISED Amateur Radio Operator Certificate Services, "Publications" | page "Date modified 2025-07-15" (lists RIC-1 Issue 8 May 2025, RIC-3 Issue 5, RIC-9 Issue 2, RBR-3 Issue 1, RBR-4 Issue 3) | https://ised-isde.canada.ca/site/amateur-radio-operator-certificate-services/en/publications | 483b61e0ad37e9fe2847069a41bf5514b153cf96bf9928a610eb32a4a57b2d58 (HTML) |
| T22 | "Canadian Table of Frequency Allocations (2022)", 2022 Edition | page "Date modified: 2023-01-27" | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/learn-more/key-documents/consultations/canadian-table-frequency-allocations-sf10759 | 9c95bdfdd1cc3a45d8357f88b77636981dc75fc036ed10e20103be3f4c610f50 (HTML). Primary services in CAPITALS, secondary in normal case (per ISED Spectrum Allocation Tool). |
| T26 | SMSE-003-26, "Proposed Revisions to the Canadian Table of Frequency Allocations 2026 Edition" (consultation) | "March 2026"; comments due "May 4th, 2026" | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/node/2469 | 7d3b402f448c2a20fe8469f741dea32542d69722d89f481a851135323c431316 (HTML) |
| T18 | SMSE-07-18, "Decision on Proposed Revisions to the Canadian Table of Frequency Allocations" | "April 2018" | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/sites/default/files/attachments/2022/SMSE-07-18-CTFA-2018-decision.pdf | 805266c9ed9063ba73eafb338072f331b69c3b89e7f5dbc22113eef3ebdeef37, 6 pp. |
| F5 | "Policy and Technical Framework for Amateur Service Use in the 5 MHz Band" | "January 2014"; posted 2014-01-22 (historical; superseded in part by T18/R4) | https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/policy-and-technical-framework-amateur-service-use-5-mhz-band | ace26b749c0585f2d1a00231c81f4f5cf0a9ce9529b94d539076020644bcb639 (HTML) |
| C1 | CEPT Recommendation T/R 61-01, "CEPT Radio Amateur Licence" | "Edition of 18 October 2024" (Annex 4 "latest updated October 2024"); docdb page confirms 18-10-2024 is current as of 2026-10-08 | https://docdb.cept.org/download/4541 (fetched with `curl -k`: docdb's TLS chain did not verify on this host) | aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691, 13 pp. |
| C2 | ECC Recommendation (05)06, "CEPT Novice Radio Amateur Licence" | "Edition 16 June 2023" | https://docdb.cept.org/download/4372 (curl -k) | f1761f8ead4a87bf78d0cca3307226a812b37d64667be91b6195b77a4c73c2e4, 10 pp. |
| P97 | 47 CFR Part 97 (eCFR XML), §97.107 and §97.119(g) - the US side of the Canada-US arrangement | eCFR as of 2026-10-06 (the copy read for us.md) | https://www.ecfr.gov/ (api versioner, title 47 part 97) | 7b86cd2b22f11437adc8720a19fd244529295a1f76728c214cb91b4e3c4583e3  |
| BHF | RAC, "Canadian 0 - 30MHz Band Plan" (graphic, 1 page; image only, read visually) | "Effective Date: June 1, 2023" (PDF dated 2023-06-25/30) | https://www.rac.ca/mivahih/2023/06/RAC_Bandplan_0–30_MHz.pdf (index https://www.rac.ca/operating/bandplans/) | 5823d8aa39042fcaeb7b8241ae52eaeedf2cc8da213d698a81403b0f6439efa8, 1 p. |
| B60 | RAC, "60 metres" page | "July 28, 2022" | https://www.rac.ca/60metres/ | 0d55fbef9e96dc6fff283e0ec953437baa36e269a45dff23b42df0b2f934e0de (HTML) |
| B6 | RAC 50 MHz (6m) page | "plan approved October 1997" | https://www.rac.ca/50-mhz-6m-page/ | 7c1423b3a92df803644bc6eee6356e56610225b30714848244dc68b3df050e41 |
| B2 | RAC 144 MHz (2m) page / "Canadian Amateur Two Metre (2m) Band Plan" | approved by RAC Board "October 2020", published TCA Nov-Dec 2020 | https://www.rac.ca/144-mhz-2m-page/ | 5231a696a3e6f2b95d2d14e479a795f8150669c77c2e20f7f16a8c3548c36802 |
| B135 | RAC 220 MHz (135 cm) page | "approved in October 1997 and is now under revision" | https://www.rac.ca/220-mhz-135-cm-page/ | 71c4f3d0a32f0c78cf0f0ba5ac07425cfb72e2eb3526bda9c3ad1bb085fc86e7 |
| B70 | RAC 432 MHz (70 cm) page | "Approved at Niagara Falls September 23rd 1995" | https://www.rac.ca/432-mhz-70-cm-page/ | ad130238c415de805ed3339f5d3970853278e2671e75f13720d8b218143e7f9a |
| B33 | RAC 902 MHz (33 cm) page | "plan approved October 1997" | https://www.rac.ca/902-mhz-33-cm-page/ | bcf9206318a628dfa784313bcc117895eec30dd197359e3b1ea678188e01d2c3 |
| B23 | RAC 1240 MHz (23 cm) page | "plan approved October 1997" | https://www.rac.ca/1240-mhz-23-cm-page/ | 0edc6567e28df3c9cc66ec66a0e09f43264e4d4dc1c2528a7ad4047a3d96600c |
| B13 | RAC 2300 MHz (13 cm) page | "plan was approved October 1997" | https://www.rac.ca/2300-mhz-13-cm-page/ | 4487db767dde8b70018d6c136c75a8f2b9d75c87e37b565c56b734ab0abb5788 |
| BMW | RAC Microwave Bands page | sub-plans "approved May 23 1998" / "Oct 14, 2003" | https://www.rac.ca/microwave-bands-page/ | c126b91d1958571bd169a57e2ea8d3c3702c350f9f56c026c65f1a1806444c3b |
| RAC26 | RAC, "Regulatory Roundup" (Dave Goodwin VE3KG), The Canadian Amateur | "TCA: January/February 2026", pp.26-28 | https://www.rac.ca/mivahih/2026/01/Regulatory_JF2026TCA.pdf | c61556fa4e2c28584b9b207c8f3162aea13187c274e18f9421a7db6feeedae02, 3 pp. |
| W1 | WSJT-X `models/FrequencyList.cpp` (default dial table) | `master`, fetched 2026-10-08, commit not recorded | https://raw.githubusercontent.com/WSJTX/wsjtx/master/models/FrequencyList.cpp | 334688bd22b72c12a562a6460abff13cf67862ff2f3504707f741b16b9fc3760 |

Not read (looked for, not obtained): RIC-1 Issue 8 text; RIC-2 (not an
amateur document as far as found - exam syllabus/procedure is in RIC-3 §5);
the US-Canada Convention text itself (TIAS 2508 / Canada Treaty Series 1952
No. 7) - only its summaries in R3 §8.1 and P97 §97.107; CPC-2-0-03 / Safety
Code 6 (RF exposure); SLPB-001-19 (3500 MHz) and SMSE-012-22 (5850-5925 MHz)
decision texts; the RAC 2m PDF version and RAC repeater-pair tables.

---

## 1. Regulator and instruments

- **Regulator:** Innovation, Science and Economic Development Canada (ISED),
  Spectrum Management Operations Branch (policy) and the **Amateur Radio
  Service Centre**, Sault Ste. Marie (certificates, call signs, examiner
  accreditation) [verified R3 §1].
- **Act/Regulations:** Radiocommunication Act; Radiocommunication Regulations
  SOR/96-484, amateur provisions **ss.42-49** plus s.15.3 (licence exemption)
  and s.26 (certificate types) [verified RR].
  - s.15.3: amateur radio apparatus is exempt from the s.4(1) licence
    requirement if the operator holds a s.42 certificate/licence and operates
    per s.45 [verified RR s.15.3].
  - s.42: who may operate (Basic qualification; Radiotelephone Operator's
    General Certificates (Aeronautical/Maritime/Land); foreign licensee who is
    a citizen of a country with a reciprocal arrangement; US citizen with an
    FCC licence) [verified RR s.42].
  - s.44: **Advanced** needed to (a) install/operate a transmitter or RF
    amplifier "that is not commercially manufactured"; (b) install apparatus
    "for receiving and automatically retransmitting radiotelephone
    communications within the same frequency band" or "for an amateur radio
    club station" [verified RR s.44].
  - s.45: operate per "Standards for the Operation of Radio Stations in the
    Amateur Radio Service" (= RBR-4) "as amended from time to time"
    [verified RR s.45].
  - s.46 supervised third-party operation; s.47 only amateur-to-amateur, no
    secret code/cipher, no music, commercially recorded material, broadcast
    programming, business communications; s.48 emergencies; s.49 no
    remuneration [verified RR ss.46-49].
- **RBR-4 Issue 3, July 2022** - the technical instrument: bands, bandwidths,
  qualifications, power, identification [verified R4]. No newer issue found
  (PUB, 2025-07-15; RAC26, Jan/Feb 2026 discusses pending RIC-3 changes only).
- **Canadian Table of Frequency Allocations, 2022 Edition** - allocation
  status (primary/secondary) and the Canadian footnotes C6, C11, C21 that
  RBR-4 quotes [verified T22]. A 2026 edition is under consultation (T26).
- **RIC-3 Issue 5 (March 2022)** - privileges summary, exam syllabus,
  reciprocal operation. **RIC-9 Issue 2 (Provisional), Oct 2005** - call sign
  policy. Both state they "have no status in law" [verified R3 preface, R9].
- **RBR-3 Issue 1 (Sept 2007)** - general station ID rule for *licensed*
  stations under RR s.41 [verified R3B]. Amateur ID is governed specifically
  by RBR-4 §9 (see §7).

## 2. Licence classes

One certificate, the **Amateur Radio Operator Certificate**, carrying one or
more qualifications [verified RR s.26(1)(e); R3 §4.1]:

| Qualification | How obtained [R3 §5] | What it adds | Source |
|---|---|---|---|
| Basic (B) | 100-question exam, pass 70% | All amateur bands above 30 MHz; transmitter power limit of §10.2; commercially made or kit transmitters only; no remote control of fixed stations; may operate cross-band repeaters | R4 Sch. I col. IV; R4 §10.2; R3 §4.5.1 |
| Basic with Honours (B/H) | Basic exam score of 80% or above | Adds all bands below 30 MHz | R4 Sch. I definitions; R3 §4.5.1 |
| Morse Code (5 w.p.m.) (5) | Send and receive at >= 5 wpm for 3 consecutive minutes; pass mark 100% (5 or fewer errors = 100%) | With Basic: adds all bands below 30 MHz | R4 Sch. I; R3 §4.5.3, §5.2 |
| Advanced (A) | 50-question exam, pass 70% (Basic must already be held - Schedule I says "B and A") | With Basic: all bands below 30 MHz; power limit of §10.3; home-built transmitters/amplifiers; same-band repeaters; club stations; remote control of fixed stations incl. radio links | R4 Sch. I; R4 §10.3; RR s.44; R3 §4.5.2 |

Equivalences [verified]:
- Morse Code (12 w.p.m.) = Basic with Honours [RR s.26(3)].
- Basic issued **before 1 April 2002** gets Basic-with-Honours privileges;
  Basic issued on/after that date gets them only on demonstrating >= 80%
  [R3 §4.3, §4.4].
- Radiotelephone Operator's General Certificate (Aeronautical/Maritime/Land)
  holders may be authorised with Basic privileges [R3 §4.3; RR s.42(e)-(g)].
- Old certificates under the repealed regulations map per RR Schedule I;
  e.g. "Amateur Digital Radio Operator's Certificate" = Basic + Advanced
  privileges [R3 §4.2].
- Non-qualified persons may operate only with a qualified operator present
  performing control functions [RR s.46; R3 §4.5.4].

**Suggested ohsradio class keys [derived].** Privileges collapse to two
independent bits - HF access and power tier - so three keys suffice:

| Key | Meaning | HF (< 30 MHz) | Power tier |
|---|---|---|---|
| `ca_basic` | Basic only (issued on/after 2002-04-01, < 80%) | No | Basic (§10.2) |
| `ca_basic_hf` | Basic + Honours, or Basic + Morse (5 or 12 wpm), or Basic issued before 2002-04-01 | Yes | Basic (§10.2) |
| `ca_advanced` | Basic + Advanced (with or without Honours/Morse) | Yes | Advanced (§10.3) |

Visitors (see §8): CEPT T/R 61-01 holders and other "authorized foreign
amateurs" get Basic+Advanced provisions capped at their own licence
[verified R4 §3.2; R3 §8.2.1] - map to `ca_advanced` intersected with the
home licence.

## 3. Frequency privileges and power, per class

### Power limits (apply on every band; transmitter limits, not radiated)

Quoted exactly from R4 §10 (p.4):

> **10.1** The transmitting power of an amplifier installed at an amateur
> station shall not be capable of exceeding by more than 3 dB the
> transmitting power limits described in this section.
>
> **10.2** The holder of an Amateur Radio Operator Certificate with Basic
> Qualification is limited to a maximum transmitting power of: a. where
> expressed as direct-current input power, 250 W to the anode or collector
> circuit of the transmitter stage that supplies radio frequency energy to
> the antenna; or b. where expressed as radio frequency output power measured
> across an impedance-matched load, i. 560 W peak envelope power for
> transmitters that produce any type of single sideband emission, or
> ii. 190 W carrier power for transmitters that produce any other type of
> emission.
>
> **10.3** [Advanced:] a. ... 1,000 W [DC input] ...; or b. ... i. 2,250 W
> peak envelope power for transmitters that produce any type of single
> sideband emission, or ii. 750 W carrier power for transmitters that produce
> any other type of emission.

Reference point: **transmitter RF output into an impedance-matched load**
(or DC input to the final stage). No antenna-gain/ERP term except on the
three bands noted below. For a guard that knows only RF output:

| Tier | SSB-type emission (J3E, J2B, J2D, R3E, H3E...) | Any other emission (CW, FM, AM, ...) |
|---|---|---|
| Basic (`ca_basic`, `ca_basic_hf`) | 560 W PEP | 190 W carrier power |
| Advanced (`ca_advanced`) | 2,250 W PEP | 750 W carrier power |

[verified R4 §10.2, §10.3]. **Interpretation risks [derived]:** (i) whether
an SSB transceiver sending FT8/RTTY (J2D/J2B, which are single-sideband
emissions) falls under the PEP limit is how the text reads, but this is an
interpretation; (ii) for AM (A3E) the limit is on *carrier* power, so PEP can
be up to 4x carrier at 100% modulation - a guard measuring PEP should use
the carrier figure as the PEP cap (conservative) unless it can measure
carrier; (iii) §10.1 is a *capability* rule on amplifiers (no more than 3 dB
over the limit), not an extra operating allowance.

### Band table (Schedule I - stations operating in Canada)

Qualification column in R4 Sch. I: "B and 5, B/H, B and A" (HF) or "B"
(above 30 MHz). Status from T22 (CAPS = primary). R4 col. III "*" = "shall
not cause interference nor be protected from interference by stations
licensed in other services operating in that band" [R4 p.7 notes].
Power cells: **Pb** = Basic transmitter limit (560 W PEP SSB / 190 W carrier
other / 250 W DC input); **Pa** = Advanced limit (2,250 W PEP / 750 W carrier
/ 1,000 W DC input). Where a radiated limit also applies, both apply.

| R4 item | Start | End | Max BW (R4 col. II) | `ca_basic` | `ca_basic_hf` | `ca_advanced` | Amateur status (T22) | Provision / source |
|---|---|---|---|---|---|---|---|---|
| 1 | 135.7 kHz | 137.8 kHz | 100 Hz | — | Pb and **1 W EIRP** | Pa and **1 W EIRP** | Secondary (FIXED, MARITIME MOBILE primary) | 5.67A: max 1 W (e.i.r.p.); no harmful interference to radionavigation of 5.67 countries. R4 p.6-7 |
| 2 | 472 kHz | 479 kHz | 1 kHz | — | Pb and **1 W EIRP** (5 W UNCONFIRMED) | Pa and **1 W EIRP** (5 W UNCONFIRMED) | Secondary (MARITIME MOBILE primary) | 5.80A: 1 W e.i.r.p.; administrations "may increase" to 5 W >800 km from listed countries; no protection from aeronautical radionavigation. R4 p.6-7. See §3 exceptions |
| 3 | 1.800 MHz | 2.000 MHz | 6 kHz | — | Pb | Pa | Primary (1800-1850 AMATEUR only; 1850-2000 AMATEUR with RADIOLOCATION, RADIONAVIGATION co-primary) | R4 p.6; T22 |
| 4 | 3.500 MHz | 4.000 MHz | 6 kHz | — | Pb | Pa | Primary (exclusive) | R4 p.6; T22 |
| 5 | 5.332 MHz (centre) | — | 2.8 kHz | — | **100 W ERP PEP** (and Pb) | **100 W ERP PEP** (and Pa) | Secondary / NIB (C21) | C21; R4 p.6, p.8 |
| 6 | 5.348 MHz (centre) | — | 2.8 kHz | — | 100 W ERP PEP | 100 W ERP PEP | Secondary / NIB | C21 |
| 7 | 5.3515 MHz | 5.3665 MHz | 2.8 kHz | — | 100 W ERP PEP "in each channel" | 100 W ERP PEP | Secondary (FIXED, MOBILE exc. aero primary) | C21; T22 row 5 351.5-5 366.5 |
| 8 | 5.373 MHz (centre) | — | 2.8 kHz | — | 100 W ERP PEP | 100 W ERP PEP | Secondary / NIB | C21 |
| 9 | 5.405 MHz (centre) | — | 2.8 kHz | — | 100 W ERP PEP | 100 W ERP PEP | Secondary / NIB | C21 |
| 10 | 7.000 MHz | 7.300 MHz | 6 kHz | — | Pb | Pa | Primary (7.0-7.1 also AMATEUR-SATELLITE) | 5.142 (7.2-7.3 shall not constrain R1/R3 broadcasting). R4 p.6-7 |
| 11 | 10.100 MHz | 10.150 MHz | **1 kHz** | — | Pb | Pa | T22 prints AMATEUR (primary) with C6, but C6: not in accordance with international allocations, no interference to other administrations' fixed service, no protection, may be required to cease | C6. R4 p.6, p.8 |
| 12 | 14.000 MHz | 14.350 MHz | 6 kHz | — | Pb | Pa | Primary (14.00-14.25 also AMATEUR-SATELLITE) | R4 p.6 |
| 13 | 18.068 MHz | 18.168 MHz | 6 kHz | — | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4 p.6 |
| 14 | 21.000 MHz | 21.450 MHz | 6 kHz | — | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4 p.6 |
| 15 | 24.890 MHz | 24.990 MHz | 6 kHz | — | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4 p.6 |
| 16 | 28.000 MHz | 29.700 MHz | 20 kHz | — | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4 p.6 |
| 17 | 50.000 MHz | 54.000 MHz | 30 kHz | Pb | Pb | Pa | Primary (exclusive) | R4 p.6 |
| 18 | 144.000 MHz | 148.000 MHz | 30 kHz | Pb | Pb | Pa | Primary (144-146 also AMATEUR-SATELLITE) | R4 p.6 |
| 19 | 219.000 MHz | 220.000 MHz | 100 kHz | Pb | Pb | Pa | **Secondary** (C11) | C11. R4 p.6, p.8 |
| 20 | 220.000 MHz | 222.000 MHz | 100 kHz | **Exceptional circumstances only** | same | same | Secondary, only "in exceptional circumstances ... to assist in disaster relief efforts" | C11. R4 p.6. Guard: refuse by default (see below) |
| 21 | 222.000 MHz | 225.000 MHz | 100 kHz | Pb | Pb | Pa | Primary (exclusive) | R4 p.6 |
| 22 | 430.000 MHz | 450.000 MHz | **12 MHz** | Pb | Pb | Pa | Secondary (RADIOLOCATION primary; 440-450 via 5.284; 435-438 amateur-satellite via 5.282) | R4 "*"; T22 |
| 23 | 902.000 MHz | 928.000 MHz | 12 MHz | Pb | Pb | Pa | Secondary (FIXED, RADIOLOCATION primary; ISM 5.150) | R4 "*"; T22 |
| 24 | 1.240 GHz | 1.300 GHz | Not specified | Pb | Pb | Pa | Secondary (RNSS, radiolocation, EESS, SR primary) | R4 "*"; T22 (5.282, 5.332; 5.332A proposed T26) |
| 25 | 2.300 GHz | 2.450 GHz | Not specified | Pb | Pb | Pa | Secondary (FIXED, MOBILE, RADIOLOCATION primary; 2400-2450 ISM 5.150; amateur-satellite 2400-2450 via 5.282) | R4 "*"; T22 (C12, C13, C13A, C17, C34) |
| 26 | 3.300 GHz | 3.500 GHz | Not specified | Pb | Pb | Pa | Secondary (3300-3450 RADIOLOCATION, C5 Government exclusive; 3450-3500 FIXED, MOBILE flexible use) | R4 "*"; T22 |
| 27 | 5.650 GHz | 5.925 GHz | Not specified | Pb | Pb | Pa | Secondary (MOBILE/RLAN, RADIOLOCATION, FIXED, FSS primary in parts) | R4 "*"; T22 (C39A-C39C, 5.150, 5.282) |
| 28 | 10.000 GHz | 10.500 GHz | Not specified | Pb | Pb | Pa | Secondary (10.45-10.5 also Amateur-satellite secondary) | R4 "*"; T22 |
| 29 | 24.000 GHz | 24.050 GHz | Not specified | Pb | Pb | Pa | Primary (AMATEUR + AMATEUR-SATELLITE; ISM 5.150) | R4 "-"; T22 |
| 30 | 24.050 GHz | 24.250 GHz | Not specified | Pb | Pb | Pa | Secondary (RADIOLOCATION primary) | R4 "*"; T22 |
| 31 | 47.000 GHz | 47.200 GHz | Not specified | Pb | Pb | Pa | Primary (exclusive, + AMATEUR-SATELLITE) | R4; T22 |
| 32 | 76.000 GHz | 77.500 GHz | Not specified | Pb | Pb | Pa | Secondary | R4 "*"; T22 |
| 33 | 77.500 GHz | 78.000 GHz | Not specified | Pb | Pb | Pa | Primary (with AMATEUR-SATELLITE, RADIOLOCATION) | R4; T22 |
| 34 | 78.000 GHz | 81.000 GHz | Not specified | Pb | Pb | Pa | Secondary | R4 "*"; T22 |
| 35 | 81.000 GHz | 81.500 GHz | Not specified | Pb | Pb | Pa | Secondary (5.561A) | R4 p.7; T22 |
| 36 | 122.250 GHz | 123.000 GHz | Not specified | Pb | Pb | Pa | Secondary | R4 "*"; T22 |
| 37 | 134.000 GHz | 136.000 GHz | Not specified | Pb | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4; T22 |
| 38 | 136.000 GHz | 141.000 GHz | Not specified | Pb | Pb | Pa | Secondary | R4 "*"; T22 |
| 39 | 241.000 GHz | 248.000 GHz | Not specified | Pb | Pb | Pa | Secondary | R4 "*"; T22 |
| 40 | 248.000 GHz | 250.000 GHz | Not specified | Pb | Pb | Pa | Primary (+ AMATEUR-SATELLITE) | R4 p.7; T22 |

Notes on the table:
- Advanced alone is never held without Basic; HF cells for `ca_advanced`
  come from "B and A" [verified R4 Sch. I].
- 28.000-29.700 MHz is **below 30 MHz**, so `ca_basic` may not use 10 m
  [verified R4 Sch. I item 16 qualification "B and 5, B/H, B and A"].
- Nothing above 250 GHz is in Schedule I. The RAC microwave page says "above
  400 GHz: Available without licence" [secondary BMW] - **UNCONFIRMED**, not
  in RBR-4; do not encode.

### Gaps inside nominal bands (refuse for every class)

- **60 m:** everything in 5.250-5.450 MHz except the four 2.8 kHz channels
  centred on 5.332, 5.348, 5.373, 5.405 MHz and the 5.3515-5.3665 MHz band.
  Occupied spectrum must lie entirely inside a channel/the band [verified C21:
  "Transmissions in any channel may not occupy a bandwidth of more than
  2.8 kHz"]. Channel edges for a guard [derived]: 5330.6-5333.4,
  5346.6-5349.4, 5371.6-5374.4, 5403.6-5406.4 kHz; the RAC graphic draws them
  as +-1.5 kHz (e.g. 5.3305-5.3335) [secondary BHF], which is wider than
  2.8 kHz - use the 2.8 kHz edges. **5358.5 kHz** is no longer a separate
  channel: Issue 3 lists four centre frequencies plus the 15 kHz band, which
  contains 5358.5 [verified R4 items 5-9; T18 D2 struck "five" for "four"].
- **220-222 MHz:** amateur only "in exceptional circumstances ... to assist in
  disaster relief efforts" [verified C11]. Treat as a gap unless an operator
  override records the exceptional authority [derived].
- **1.8-2.0, 3.5-4.0, 7.0-7.3, 28.0-29.7, 50-54, 144-148, 219-220/222-225,
  430-450, 902-928, 1240-1300, 2300-2450, 3300-3500, 5650-5925,
  10.0-10.5 GHz** are contiguous in Schedule I - no internal gaps.

### Per-band exceptions

- **2200 m (135.7-137.8 kHz):** 1 W EIRP (5.67A) [verified R4 p.7]; RAC
  note 4 agrees "Maximum power is 1 Watt EIRP" [secondary BHF]. No
  notification/registration requirement found in RBR-4 (the UK-style
  notification does not appear) - none found, so none encoded.
- **630 m (472-479 kHz):** RBR-4 quotes only 5.80A: 1 W EIRP, and
  "Administrations may increase this limit of e.i.r.p. to 5 W in portions of
  their territory which are at a distance of over 800 km" from listed
  countries (incl. the Russian Federation) [verified R4 p.7]. T22 lists only
  "Amateur 5.80A" for the band - no Canadian footnote raising it [verified
  T22]. **RAC states "a maximum of five watts EIRP on the 630m band"**
  [secondary BHF note 5]; ARRL news (2014) said "5 W (or 1 W EIRP in some
  locations)" [secondary]. **5 W is UNCONFIRMED** - no ISED text found that
  exercises the 5.80A option. Guard: 1 W EIRP.
- **60 m (5 MHz):** C21 (CAN-18): "Amateur stations are allowed to operate
  with a maximum **effective radiated power of 100 W PEP in each channel** and
  are restricted to the following emission modes and designators: telephony
  (2K80J3E), data (2K80J2D), RTTY (60H0J2B) and CW (150HA1A). Transmissions in
  any channel may not occupy a bandwidth of more than 2.8 kHz. ... shall not
  cause interference to fixed and mobile operations in Canada or in other
  countries ..." [verified R4 p.8; T22 C21]. Canada deliberately did **not**
  adopt 5.133B's 15 W EIRP [verified T18 §4.2.1]. ERP is relative to a
  half-wave dipole: 100 W ERP = 164 W EIRP (20 dBW ERP = 22.15 dBW EIRP)
  [derived]. Within 5351.5-5366.5 "in each channel" is ambiguous (is the
  15 kHz band one channel, or may several 2.8 kHz emissions run at
  100 W ERP each?) - **UNCONFIRMED**; guard: one emission, 100 W ERP PEP.
  Upper-sideband dial convention: dial = centre - 1.5 kHz (5330.5, 5346.5,
  5371.5, 5403.5 kHz); in the 15 kHz band USB dial 5351.5-5363.7 kHz
  [secondary B60, BHF note 2].
- **30 m (10.100-10.150 MHz):** max bandwidth **1 kHz** (narrower than other
  HF bands) [verified R4 item 11]; C6 cease-on-interference [verified].
- **40 m 7.200-7.300:** 5.142 - shall not constrain R1/R3 broadcasting
  [verified R4 p.7]. (In Regions 1/3, Schedules II/IV end at 7.200.)
- **219-220 MHz:** secondary only [verified C11]. (RBR-4 has no US-style
  "point-to-point digital only" condition - none found.)
- **23 cm:** WRC-23 5.332A (no harmful interference to RNSS receivers;
  administration must rapidly eliminate it) is *proposed* for the Canadian
  Table [verified T26 Table 17], not yet adopted.
- **13 cm:** 2305-2320 / 2345-2360 MHz WCS (C13), 2320-2345 MHz satellite
  radio + terrestrial broadcasting primary (C13A), 2360-2400 MHz aeronautical
  mobile telemetry with Government priority (C12) [verified T22]. Amateur is
  secondary across 2300-2450 [verified T22, R4 "*"] - permitted, but heavy
  primary use; guard may warn [derived].
- **9 cm:** 3300-3450 MHz radiolocation "For the exclusive use of the
  Government of Canada" (C5 on the radiolocation entry); 3450-3500 MHz
  FIXED/MOBILE (3500 MHz flexible-use/5G band) with amateur secondary
  [verified T22]. Permitted by R4 item 26, but secondary in a 5G band.
- **5 cm:** 5725-5825 MHz licence-exempt RLAN (C39A); 5850-5925 MHz FIXED/
  FSS/MOBILE with amateur secondary (C39C) [verified T22]. Effect of
  SMSE-012-22 (Dec 2022: RLAN 5850-5895, C-V2X 5895-5925) on the amateur
  entry not read - **UNCONFIRMED**, permission stands per R4.
- **ISED's non-interference rule generally:** R4 §8 - no interference to
  other services and no protection, per Column I of Schedule I [verified R4
  p.3].

### Operation outside Canada (Canadian-registered ships/aircraft in international waters/airspace)

R4 §7 [verified p.2]: such stations "may operate on any frequency within the
frequency bands and corresponding bandwidths set out in Schedules II, III or
IV" (ITU Region 1/2/3) subject to the same qualifications. Differences from
Schedule I worth encoding [verified R4 pp.9-15]:

| | Region 1 (Sch. II) | Region 2 (Sch. III) | Region 3 (Sch. IV) |
|---|---|---|---|
| 160 m | 1.810-1.850 | 1.800-2.000 | 1.800-2.000 |
| 80 m | 3.500-3.800 | 3.500-4.000 | 3.500-3.900 |
| 60 m | 5.3515-5.3665 only, 2.8 kHz, **5.133B: 15 W e.i.r.p.** | same | same |
| 40 m | 7.000-7.200 | 7.000-7.300 | 7.000-7.200 |
| 6 m | 50.000-52.000 | 50-54 | 50-54 |
| 2 m | 144-146 | 144-148 | 144-148 |
| 1.25 m | — | 220.000-225.000, 100 kHz | — |
| 70 cm | 430-440, BW not specified | 430-440, BW not specified | 430-440, BW not specified |
| 33 cm | — | 902-928, 12 MHz | — |
| 9 cm | — | 3.300-3.500 | 3.300-3.500 |
| 5 cm | 5.650-5.850 | 5.650-5.925 | 5.650-5.850 |
| VE0 | prefix for vessels on international voyages [R4 Sch. V] |

(The 60 m 15 W EIRP abroad is confirmed by RAC too [secondary B60].)

## 4. Emission, bandwidth and symbol-rate limits

- **Bandwidth is the only general emission control.** "The maximum
  permissible bandwidth of a transmitted signal is set out in Column II" and
  is "determined by measuring the frequency band occupied by that signal at a
  level that is **26 dB below the maximum amplitude** of that signal"
  [verified R4 §4, p.2]. Values per band are in the §3 table: 100 Hz (2200 m),
  1 kHz (630 m, 30 m), 2.8 kHz (60 m), 6 kHz (160/80/40/20/17/15/12 m),
  20 kHz (10 m), 30 kHz (6 m, 2 m), 100 kHz (219-225 MHz), 12 MHz (70 cm,
  33 cm), "Not specified" (23 cm and up).
- Consequences [derived]: AM (~6 kHz) is allowed on HF except 30 m and
  60 m; FM is effectively 10 m and up (20 kHz on 10 m, 30 kHz on 6/2 m);
  wideband digital/DATV (e.g. 2-8 MHz DVB-S) is legal on 70 cm and 33 cm up
  to 12 MHz and unrestricted from 23 cm.
- **60 m only:** emissions restricted to 2K80J3E, 2K80J2D, 60H0J2B, 150HA1A
  [verified C21].
- **No symbol-rate / baud limits** found in RBR-4 or the Regulations - none
  encoded (Canada dropped US-style baud rules). RAC band plans use baud
  categories ("<=2400 B", ">=4800 B") as voluntary guidance only.
- **Other technical rules** [verified R4 §11, pp.4-5]:
  - "An unmodulated carrier in a frequency band below 30 MHz may be
    transmitted only for brief tests."
  - "Signals may not be automatically retransmitted in a frequency band below
    29.5 MHz unless those signals are received from a station operated by a
    person qualified to transmit in the frequency bands below 30 MHz."
  - AM limited to no more than 100% modulation.
  - Below 148.000 MHz, frequency stability at least that of crystal control;
    the station must be able to determine transmit frequency to crystal-
    calibrator accuracy and indicate or prevent overmodulation (radiotelephone).
- Content limits: no secret code/cipher, music, commercially recorded
  material, broadcast programming, business communications [verified RR s.47].

## 5. Antenna gain, ERP/EIRP treatment

- General limits are **transmitter output into a matched load** (or DC
  input); **no antenna-gain or ERP limit** applies on any band except the
  three below [verified R4 §10].
- **2200 m and 630 m: EIRP** (1 W) [verified 5.67A, 5.80A].
- **60 m: ERP, 100 W PEP** [verified C21]. ISED chose ERP deliberately over
  transmitter power despite RAC asking for transmitter output: "Industry
  Canada will specify limits in terms of maximum effective radiated power"
  [verified F5 ¶21, decision 4-3]. RAC: "If your antenna has more gain than a
  dipole, you must reduce your power accordingly" [secondary B60]. The guard
  needs a declared antenna gain (dBd) and feeder loss to enforce this
  [derived]; with an unknown antenna, assume 0 dBd (dipole) - but an
  efficient vertical/beam could exceed, so prompt the user [derived].
- **Amplifier capability:** amplifier must not be *capable* of exceeding the
  limit by more than 3 dB [verified R4 §10.1].
- RF exposure / antenna structures: RBR-4 §12 points to CPC-2-0-03 (antenna
  siting and land-use consultation) [verified R4 p.5]; CPC-2-0-03 and Safety
  Code 6 not read.

## 6. Station types

- **Repeaters.** Installing apparatus "for receiving and automatically
  retransmitting radiotelephone communications within the same frequency
  band" requires **Advanced** [verified RR s.44(b)(i)]. Basic holders may
  operate *cross-band* repeaters and use repeaters set up by Advanced holders
  [verified R3 §4.5.1]. Repeater call signs: same-band radiotelephone
  repeater above 30 MHz needs an Advanced applicant; a repeater transmitting
  below 30 MHz needs "an applicable Morse code qualification"; a Basic holder
  may get a call sign for a **digital repeater** above 30 MHz [verified R9
  §1.6, provisional 2005 policy]. Below 29.5 MHz, automatic retransmission
  only of HF-qualified stations [verified R4 §11].
- **Remote control.** Basic: "no remote control of fixed stations permitted
  regardless of medium used for control"; operation through a repeater is
  not remote control. Advanced: "remote control of fixed stations, including
  the use of radio links" [verified R3 §4.5.1-4.5.2]. This is RIC policy
  ("no status in law"); RAC reports ISED is "willing to expand access to
  remotely-controlled stations beyond just Advanced", pending a new RIC-3
  [secondary RAC26]. Guard implication: if ohsradio offers remote/network TX of
  a fixed station, `ca_basic`/`ca_basic_hf` should be refused [derived].
- **Home-built transmitters/amplifiers:** Advanced only; Basic may assemble
  "commercially available transmitter kits of professional design" and
  re-program radios by software (no circuit modification) [verified RR
  s.44(a); R3 §4.5.1]. A software-defined transmitter assembled from parts
  (e.g. Pluto + home-made PA) is arguably "not commercially manufactured" -
  **interpretation risk, UNCONFIRMED** how ISED treats SDR builds.
- **Club stations:** Advanced to install [RR s.44(b)(ii)]; club call signs
  have 3-letter suffixes and an Advanced sponsor/trustee [verified R9 §1.5].
- **Beacons / unattended stations:** no specific RBR-4, Regulations or RIC-3
  provision found for beacons or unattended operation as such -
  **UNCONFIRMED** (no permission or prohibition encoded). RAC plans reserve
  beacon segments (§9).
- **Radio control of models:** any frequency in Schedule I bands above
  30 MHz [verified R4 §5].
- **Satellite.** Amateur-satellite allocations in T22 [verified]: 7.0-7.1,
  14.00-14.25, 18.068-18.168, 21.0-21.45, 24.89-24.99, 28.0-29.7 MHz,
  144-146 MHz (primary); 435-438 MHz, 1260-1270 MHz (Earth-to-space only),
  **2400-2450 MHz**, 3400-3410 MHz (Regions 2/3), 5650-5670 MHz (Earth-to-
  space only) under **5.282**: "may operate subject to not causing harmful
  interference to other services" [verified T22 5.282]; 10.45-10.5 GHz
  secondary; 24.00-24.05, 47.0-47.2, 77.5-78, 134-136, 248-250 GHz primary;
  76-77.5, 78-81, 81-81.5, 136-141, 241-248 GHz secondary [verified T22].
  **13 cm 2400-2450 MHz:** amateur secondary, amateur-satellite per 5.282,
  also ISM (5.150) [verified T22]. Note T22's 5725-5850 MHz row shows no
  amateur-satellite entry, though RAC's plan has "Amateur Satellite Down Link
  Only 5830-5850" [secondary BMW] - status of a 5830-5850 downlink in Canada
  **UNCONFIRMED** (irrelevant to terrestrial TX, which R4 item 27 permits).
- **Third-party traffic:** Canada does not prohibit international third-party
  communications [verified R4 §6].

## 7. Call signs, portable/location indicators, identification rules

**Prefixes by location** [verified R4 Sch. V p.16; R9 §1.2]:

| Prefix | Location |
|---|---|
| VE1, VA1 | Nova Scotia |
| VE2, VA2 | Quebec |
| VE3, VA3 | Ontario |
| VE4, VA4 | Manitoba |
| VE5, VA5 | Saskatchewan |
| VE6, VA6 | Alberta |
| VE7, VA7 | British Columbia |
| VE8 | Northwest Territories |
| VE9 | New Brunswick |
| VE0 | International waters - "only when the amateur radio station is operated from vessels that make international voyages" |
| VO1 | Newfoundland |
| VO2 | Labrador |
| VY1 | Yukon |
| VY2 | Prince Edward Island |
| VY0 | Nunavut |
| CY0 | Sable Island (R9 Table I, C1 Annex 4; **not** in R4 Sch. V) |
| CY9 | St. Paul Island (same) |

- Call signs are issued by the residence address's prefix; moving to another
  prefix area requires a change of call sign [verified R9 §1.2]. Certificate
  authorises operation anywhere in Canada; the registered address is a
  contact address, not a station location [secondary RAC26].
- Suffixes: permanent calls have 2 or 3 letters; 2-letter only after 5 years
  of Basic (in VE1-VE7, VO1) or freely in VE8, VE9, VY0-2, VO2; single-letter
  and 4-character suffixes only as special-event calls; club calls 3 letters
  [verified R9 §1.3, §1.5].
- Special-event prefixes (R9 Table I) [verified]: CF, CG, CH, CI, CJ, CK, CY,
  CZ, VB, VC, VD, VF, VG, VX, XJ, XK, XL, XM, XN, XO + digit (e.g. VE3 -> CG3,
  CK3, VX3, XM3, VC3; VA3 -> CF3, CJ3, VG3, XL3, VB3; VO1 -> CH1, CY1, XJ1,
  XN1, VD1; VY0 -> CI0, CZ0, XK0, XO0, VF0). Note CY1/CY2 are VO special
  prefixes while CY0/CY9 are islands.
- Call sign regex for Settings validation [derived from the above]:
  regular `^(VE[0-9]|VA[1-7]|VO[12]|VY[0-2])[A-Z]{2,3}$`; special/island
  calls need a broader pattern; warn rather than refuse.

**Identification** [verified R4 §9, p.3]: "The operator of an amateur station
in Canada shall identify the station by transmitting the assigned call
sign." ... "shall transmit the applicable identification, in English or
French, at the beginning and end of each period of exchange of communication
or test transmission, and at intervals of no more than 30 minutes throughout
the period of exchange of communication." (RBR-3 §2's "at least once in each
transmission and at least once every 30 minutes" applies to *licensed*
stations under RR s.41 [verified R3B]; amateur stations are licence-exempt
under s.15.3, so RBR-4 §9 is the operative rule - RAC26 nevertheless cites
RBR-3 [secondary].) Guard: ID reminder at start, end, and <= 30 min.

**Portable indicators for Canadians in Canada:** no requirement found in
RBR-4, the Regulations, RIC-3 or RIC-9 - none encoded (**UNCONFIRMED** that
"/VE3" etc. is unnecessary, but nothing requires it).

**US licensees in Canada** [verified R4 §9 a-c]: FCC call sign; then by
radiotelephony add the word "mobile" or "portable", by radiotelegraphy add
"/"; then add the Canadian prefix for the station's location from Sch. V
(e.g. "W1AW portable VE3", "W1AW/VE3"). Per the Convention, give location by
city and province at least once per contact [verified R3 §8.1].

## 8. Reciprocal operating

**Visitors in Canada.**
- Eligible: (a) US citizen **and resident** with an FCC amateur licence
  [verified R4 §2(a)]; RR s.42(j) says "issued to a citizen of the United
  States" [verified]; no registration or permit needed [verified R3 §8.1].
  US amateurs "must abide by the Radiocommunication Regulations and RBR-4"
  [verified R3 §8.1].
- (b) any other foreign licensee who is a **citizen** of the issuing country,
  where a reciprocal arrangement exists [verified R4 §2(b); RR s.42(i)].
- Privileges: "in accordance with the provisions applicable to the holder of
  an Amateur Radio Operator Certificate with Basic and Advanced
  Qualifications, but not exceeding the privileges of the amateur radio
  licence granted to them by their own administration" [verified R4 §3.2].
- CEPT T/R 61-01 visitors: privileges "equivalent to a Canadian with ...
  both Basic Qualification and Advanced Qualification" [verified R3 §8.2.1];
  T/R 61-01 Annex 4 Table 2 col. 4: "Amateur Radio Operator Certificate with
  Advanced qualifications"; col. 2 prefixes VE1-VE9, VO1, VO2, VY0-VY2, CY0,
  CY9 [verified C1 p.9]. (Note: C1 Annex 4 lists VE prefixes only, not VA.)
- ECC Rec (05)06 (CEPT Novice): Canada **not listed** as a participating
  non-CEPT country [verified C2 Annex 4, Table 2 lists USA and Dutch
  Caribbean only].
- IARP: Canada is a signatory of the Inter-American Convention [verified R3
  §8.2.2]; foreign IARP holders' privileges in Canada not stated beyond
  R4 §3.2 - **UNCONFIRMED** detail.

**Canadians abroad.**
- **United States:** Canadians operate under TIAS 2508 and FCC §97.107(a):
  "The operating terms and conditions of the amateur service license issued
  by the Government of Canada" and "the applicable rules of this part, but not
  to exceed the control operator privileges of an FCC-granted Amateur Extra
  Class operator license" [verified P97 §97.107(a)]; "limited by U.S. band
  edges and mode restrictions" [verified R3 §8.1]. ID: the US location
  indicator goes **after** the Canadian call for Canadian licensees (e.g.
  VE3XYZ/W2), with city and state at least once per contact [verified P97
  §97.119(g)]. Canadians must still respect their own class: e.g. `ca_basic`
  gets no HF in the US [derived from R3 §8.1 "same privileges as they have in
  Canada"].
- **CEPT T/R 61-01:** Canada participates. To qualify, "a Canadian needs to
  hold an Amateur Radio Operator Certificate with Basic Qualification and
  Advanced Qualification and have their call sign on their certificate"
  [verified R3 §8.2.1; C1 Annex 4 col. 3 "Amateur Radio Operator Certificate
  with Basic and Advanced Qualifications and call sign"]. Basic+Honours or
  Basic+Morse alone does **not** qualify. RAC issues the permit; "A
  Canadian-issued CEPT permit has no legal status in Canada" [verified R3].
- **IARP:** "Class 1 permits are issued to those who hold an Amateur Radio
  Operator Certificate with Basic Qualification and Morse Code (12 w.p.m.),
  while Class 2 permits are issued to those who hold only the Basic
  Qualification. The Advanced Qualification and Morse Code (5 w.p.m.) are
  not considered" [verified R3 §8.2.2]. Class 1 = all amateur frequencies;
  Class 2 = above 30 MHz [verified]. Oddity: 12 wpm Morse is no longer
  examined, so most current Canadians get Class 2 [derived] - flag.
- **Ships/aircraft in international waters/airspace:** Schedules II-IV
  (see §3) [verified R4 §7]; elsewhere, the local jurisdiction's rules
  [verified R4 p.3].

## 9. National band plan (RAC - voluntary; guard warns)

RAC plans are coordinated by the RAC Band Planning Committee and approved by
the RAC Board [secondary RAC bandplans index]. Several VHF/UHF plans date from
1995-1998 and RAC says 220 MHz "is now under revision".

### HF and LF/MF - RAC 0-30 MHz Band Plan, effective 1 June 2023 [secondary BHF]

Read from the graphic (image-only PDF); edges as printed. Overlays (e.g.
"Digital" under "CW") mean both uses share the span.

| Band | Segments (kHz/MHz as printed) |
|---|---|
| 2200 m | CW 135.7-137.4; Digital 137.4-137.6; QRSS 137.6-137.8 kHz |
| 630 m | CW 472-479; Digital 475-479 kHz (overlay) |
| 160 m | CW 1.800-1.840 (Digital 1.800-1.810 overlay); Phone 1.840-2.000 |
| 80 m | CW 3.500-3.580; Digital 3.580-3.583; CW 3.583-3.589; Digital 3.589-3.600; Phone 3.600-3.842; SSTV 3.842-3.845; Phone 3.845-4.000 |
| 60 m | Each channel CW/Phone/Digital (graphic 5.3305-5.3335, 5.3465-5.3495, 5.3515-5.3665, 5.3715-5.3745, 5.4035-5.4065); digital/FT8 centred dial 5357 kHz USB [B60] |
| 40 m | CW 7.000-7.040 (Digital 7.035-7.040 overlay); Phone 7.040-7.300 with Digital 7.070-7.125 overlay; SSTV 7.165-7.175 |
| 30 m | CW 10.100-10.130; Digital 10.130-10.150 (CW overlay 10.140-10.150) |
| 20 m | CW 14.000-14.070; Digital 14.070-14.112 (CW overlay 14.073-14.1005); Phone 14.112-14.350; SSTV 14.230-14.236 |
| 17 m | CW 18.068-18.100; Digital 18.095-18.110; Phone 18.110-18.168 |
| 15 m | CW 21.000-21.070; Digital 21.070-21.125 (small CW overlay 21.080-21.083; a 21.090 mark whose meaning is unclear in the graphic); CW 21.125-21.150; Phone 21.150-21.450; SSTV 21.340-21.343 |
| 12 m | CW 24.890-24.920; Digital 24.920-24.940 (CW overlay 24.925-24.940); Phone 24.940-24.990; SSTV 24.975-24.978 |
| 10 m | CW 28.000-28.070; Digital 28.070-28.1895; Beacons 28.1895-28.2005; CW 28.2005-28.300; Digital 28.300-28.320; Phone 28.320-28.680; SSTV 28.680-28.683; Phone 28.683-29.300; Satellite 29.300-29.520; FM 29.520-29.700 |

RAC notes [secondary BHF]: LSB on 160/80/40 m, USB elsewhere incl. 60 m;
avoid NCDXF beacons on 14.100, 18.110, 21.150, 24.930, 28.200 MHz; RAC's
notes 4-6 restate 2200 m 1 W EIRP / 100 Hz, 630 m "five watts EIRP" / 1 kHz
(see §3 - unconfirmed), 60 m 100 W ERP / 2.8 kHz.

**FT8 default dials (WSJT-X, all regions)** [secondary W1]: 1.840, 3.573,
5.357, 7.074, 10.136, 14.074, 18.100, 21.074, 24.915, 28.074, 50.313,
144.174, 222.174 (R2 only), 432.174, 1296.174 MHz. Conflicts with the RAC
graphic [derived]: 1.840 sits on the CW/Phone boundary; 3.573 is in RAC's
CW segment (RAC digital is 3.580-3.583/3.589-3.600); 24.915 is in RAC's CW
segment (RAC digital starts 24.920). Guard should not warn on established
FT8 dials just because RAC's graphic lags.

### 6 m - approved October 1997 [secondary B6]

50.0-50.6 narrow band (SSB, AM); 50.0-50.05 CW/beacons/EME; 50.05-50.1
CW/beacons; 50.1 CW calling; 50.1-50.6 SSB/AM (<= 2.3 kHz); 50.105-50.115 DX
window (50.110 DX calling); 50.125 national SSB calling; 50.4 AM calling;
50.6-51.0 experimental; 50.7 RTTY calling; 50.8-50.98 R/C models (10 ch,
20 kHz); 51-51.1 Pacific DX window; 51.1-52 FM simplex & packet (51.7 packet
calling); 52-52.05 Pacific DX window; 52.525 national FM calling; **52-53
repeater inputs, 53-54 outputs** (offset 1 MHz [derived]). FT8 50.313 is not
mentioned in this 1997 plan.

### 2 m - approved October 2020 [secondary B2]

| Segment (MHz) | Use |
|---|---|
| 144.000-144.100 | EME, narrow band digital, CW, weak signal; JT65 JA window 144.085 |
| 144.100-144.180 | CW, SSB, narrow digital, EME; **144.174 FT8**; 144.144/144.150 MSK144; 144.115-144.135 digital EME (144.125) |
| 144.180-144.265 | CW, SSB, narrow modes < 3 kHz incl. FAX/SSTV; 144.200 SSB/CW calling |
| 144.265-144.270 | No transmissions (guard) |
| 144.270-144.300 | Propagation beacon network exclusive |
| 144.300-144.310 | No transmissions (guard) |
| 144.310-144.500 | Wide band digital (packet, APRS); 144.340 ATV coordination; **144.390 national APRS**; 144.450 AM; 144.489 WSPR; 20 kHz raster 144.37-144.49 |
| 144.500-144.900 | FM/digital/linear repeater inputs |
| 144.900-145.100 | Wide band digital (20 kHz raster 144.91-145.09) |
| 145.100-145.500 | Repeater outputs |
| 145.500-145.590 | ARISS links exclusive |
| 145.590-145.790 | Wide band digital (145.59-145.79, 20 kHz) |
| 145.790-145.800 | No transmissions (guard) |
| 145.800-146.000 | Satellite uplink/downlink and ARISS exclusive |
| 146.000-146.010 | No transmissions (guard) |
| 146.010-146.370 | Repeater inputs |
| 146.400-146.595 | FM simplex, 15 kHz raster 146.415-146.595; **146.520 national FM calling** |
| 146.610-147.390 | Repeater outputs |
| 147.420-147.570 | FM simplex & hotspots, 30 kHz raster (147.420...147.570) |
| 147.435-147.585 | Wide band digital, interleaved 30 kHz raster |
| 147.600-147.990 | Repeater inputs |

Repeater offset [derived from the paired ranges; RAC does not state it as a
number here]: **600 kHz** - 144.5-144.9 in / 145.1-145.5 out (+600);
146.01-146.37 in / 146.61-146.97 out (+600); 147.60-147.99 in / 147.00-147.39
out (-600). Wide-band digital = >3 kHz and <30 kHz (note 1); hotspots not
recommended on 2 m, max 500 mW, no gain antennas (note 13).

### 1.25 m (222-225 MHz) - October 1997, "now under revision" [secondary B135]

222.00-222.05 EME exclusive; 222.05-222.10 CW (222.1 CW calling);
222.10-222.275 SSB (222.2 SSB calling); 222.275-222.30 beacons; 222.31-223.37
repeater inputs; 223.39-223.49 high speed data; 223.49-223.59 FM simplex;
223.59-223.89 data (223.685-223.805 narrow packet, centres 223.70/.73/.76/.79);
223.91-225 repeater outputs. Offset **1.6 MHz** [derived: 222.31 -> 223.91].
219-220 secondary "to be addressed in the new band plan".

### 70 cm (430-450 MHz) - approved 23 Sept 1995 [secondary B70]

430.025-431.5 digital; 431.5-433 CW/SSB/EME/narrow AM (432.000 EME centre,
432.100 CW calling, 432.200 SSB calling); 432.3-432.4 beacon network
exclusive; 432.4-433 experimental narrow; 433-434.8 digital; 434.8-434.9
analogue repeater links; 434.9-435 guard; **435-438 satellites**; **438-444
ATV** (439.250 video carrier); 442-445 repeater outputs; 444.000 spread
spectrum centre; 445.0-445.775 links; 445.8-445.975 digital; 446.0-446.175 FM
simplex (**446.000 national FM calling**); 446.2-446.375 remote base;
446.4-446.775 links; 446.8-446.975 digital; **447-450 repeater inputs**.
Offset **+5 MHz** (442-445 out / 447-450 in) [derived]. Note 9: spread
spectrum within "IC bandwidth limit of 12 MHz".

### 33 cm (902-928 MHz) - October 1997 [secondary B33]

902.0-902.5 packet; 902.5-902.9 TTY/packet; 902.9-903.1 CW/EME (903.100 DX
calling); 903.1-903.5 CW/SSB/etc. (903.200 SSB calling); 903.3-903.32 beacon
network; 903.32-903.4 general beacons; 903.5-903.9 linear translators;
903.9-904.0 experimental beacons; 904.0-904.3 control links; 904.3-905.0 FM
simplex 25 kHz (**904.500 FM calling**); 905-907 high-rate data; **907-910
repeater inputs; 919-922 repeater outputs** (offset 12 MHz [derived]);
910-916 FSTV; 916-916.5 packet; 916.5-919 high-rate data; 922-928 FSTV/spread
spectrum/experimental.

### 23 cm (1240-1300 MHz) - October 1997 [secondary B23]

1240-1246 ATV ch 1; 1246-1248 NBFM links (duplex 1258); 1248-1252 high-rate
data; 1252-1258 ATV ch 2; 1258-1260 links; **1260-1270 satellite uplinks**;
**1270-1276 repeater inputs; 1282-1288 repeater outputs** (offset 12 MHz
[derived]); 1276-1282 ATV ch 3; 1288-1294 wideband experimental; 1294-1295
NBFM simplex (**1294.500 FM calling**); 1295-1295.8 SSTV/FAX; 1295.8-1296 EME
expansion; 1296-1296.05 EME exclusive; **1296.100 CW/SSB calling**;
1296.4-1296.8 translators; 1296.8-1297 experimental beacons; 1297-1299
digital; 1299-1300 high-rate data.

### 13 cm (2300-2450 MHz) - October 1997 [secondary B13]

2300-2303 high-rate data; 2303-2304.1 packet/CW/EME; **2304.100 CW/SSB DX
calling**; 2304.2 SSB local calling; 2304.3-2304.32 beacon network;
2304.32-2304.4 general beacons; 2304.5-2304.9 translators; 2304.9-2305
experimental beacons; 2305-2306 FM simplex (2305.2 calling); 2306-2309
repeater inputs; 2310-2390 experimental/FSTV/high speed digital (6 MHz
raster); 2390-2396 FSTV; 2396-2400 data/links; **2400-2403, 2403-2408,
2408-2410 satellite**; 2410-2413 repeater outputs; 2413-2418 high-rate data;
2418-2430 FSTV (2424-2424.5 Japanese EME); **2430-2438 satellite**;
2438-2450 WBFM/FSTV/spread spectrum. (Pre-dates WCS/SDARS in 2305-2360 -
much of 2310-2390 now sits in licensed commercial spectrum [derived from
T22].)

### Microwave [secondary BMW]

- 3300-3500 (1998): 3300-3400 digital; 3400-3410 satellite; 3400-3450
  digital/video; 3450-3500 weak signal/EME; **3456.1 calling**; 3456.3-3457
  beacons; 3400-3405 R1 EME window.
- 5650-5925 (1998): 5650-5670 satellite uplink; 5650-5725 digital;
  5759-5765 weak signal/EME (**5760.1 calling**, 5760.5-5761 beacons);
  5770-5925 digital/video; 5830-5850 satellite downlink.
- 10.0-10.5 GHz (2003): 10.360-10.380 narrowband only (<20 kHz), **10.3681
  calling**; 10.450-10.500 amateur-satellite only; wideband >20 MHz should
  use 10.000-10.200.
- 24 GHz (2003): 24.192-24.194 narrowband (24.1921 calling); 24.048-24.050
  alternate; 24.000-24.050 kept clear for satellites.
- 47 GHz: 47.0881 calling.
- **Warning:** RAC's page still shows pre-WRC-2000 bands (75.5-76 GHz,
  119.98-120.02 GHz, 142-149 GHz) "since Industry Canada has not yet approved
  the changed allocations". That is obsolete: RBR-4 Issue 3 Sch. I has the
  post-WRC-2000 bands (76-81.5, 122.25-123, 134-141, 241-250 GHz) and **none**
  of 75.5-76, 119.98-120.02, 142-149 GHz. Do not import RAC's microwave
  table as permissions.

## 10. Pending changes (as of 2026-10-08)

- **RBR-4:** no new issue or consultation found; Issue 3 (July 2022) current
  [verified PUB 2025-07-15; secondary RAC26].
- **RIC-3 revision (pending, no date):** ISED "willing to expand access to
  remotely-controlled stations beyond just Advanced Amateurs"; changes to 3 of
  the 50 Advanced exam topics; both to be released together in a new RIC-3;
  delayed by ISED staffing and November 2025 budget cuts [secondary RAC26].
- **Call sign policy:** RAC's "top regulatory priority"; ISED may require
  public consultation; no change yet [secondary RAC26]. RIC-9 is still the
  2005 "Provisional" issue [verified PUB].
- **Advanced question bank update "paused"** [secondary RAC26]; new Basic
  question bank released 2025 (updated 26 Aug 2025) [secondary RAC26].
- **RIC-1 Issue 8 (May 2025):** examiners may examine anywhere in Canada
  [secondary RAC26; PUB lists Issue 8].
- **Canadian Table 2026 Edition (SMSE-003-26, March 2026):** proposes adding
  WRC-23 **5.332A** to 1240-1300 MHz (amateur must not interfere with RNSS;
  administration must rapidly eliminate interference) [verified T26 ¶75-78,
  Table 17]; no change proposed to the 3300-3400 MHz Canadian Table (no
  mobile allocation added) [verified T26 ¶26]. Comments closed 4 May 2026;
  **no decision found** as of 2026-10-08.
- **DND over-the-horizon radar (central Ontario):** HF, not authorised on
  amateur allocations per DND; interference risk only [secondary RAC26].
- **60 m:** stable since July 2022 (C21 CAN-18); no further change found.

## 11. Confidence and gaps

High confidence (read in force, in primary text): the full Schedule I band
list, bandwidths and qualification gates; the Basic/Advanced power wording;
2200 m 1 W EIRP; 60 m channels, 100 W ERP PEP and emission list; call-sign
prefixes; the 30-minute ID rule; US-visitor ID format; CEPT equivalence
(Basic + Advanced only); IARP class rules.

UNCONFIRMED / risks:

1. **630 m 5 W EIRP** - RAC says 5 W; ISED text only quotes 5.80A (1 W,
   "may increase" to 5 W >800 km from listed countries). No ISED decision
   found exercising it. Encode 1 W EIRP.
2. **60 m "in each channel" inside 5351.5-5366.5 kHz** - whether multiple
   simultaneous 2.8 kHz emissions are each allowed 100 W ERP is unclear.
   Encode one emission, 100 W ERP PEP, entirely within the band.
3. **60 m ERP needs antenna data** - the guard cannot enforce 100 W ERP from
   transmitter power alone; requires declared antenna gain (dBd) and loss.
4. **SSB vs "other emission" power** - digital modes via an SSB exciter
   (J2D) read as "single sideband emission" (560/2,250 W PEP); AM is limited
   on *carrier* power. Interpretation, not stated in examples by ISED.
5. **SDR / home-assembled transmitters for Basic holders** - RR s.44(a)
   restricts "not commercially manufactured" transmitters/amplifiers to
   Advanced; how ISED treats an SDR board plus home-built PA is not stated.
6. **Remote control** - RIC-3 bars Basic holders from remote control of
   fixed stations; RIC has "no status in law", and a relaxation is pending.
   Encode the restriction; recheck on each RIC-3 issue.
7. **Beacons / unattended operation** - no Canadian provision found either
   way.
8. **Portable/location suffix for Canadians inside Canada** - no requirement
   found.
9. **Foreign IARP holders in Canada** - privileges not stated beyond R4 §3.2.
10. **5830-5850 MHz amateur-satellite downlink** - in RAC plan, absent from
    the Canadian Table row; irrelevant to terrestrial permission.
11. **SMSE-012-22 (5850-5925 MHz) and SLPB-001-19 (3450-3650 MHz)** decision
    texts not read; Canadian Table 2022 (dated after/around them) still
    shows amateur secondary in 5850-5925 and 3450-3500, and RBR-4 permits
    both.
12. **Above 250 GHz** - RAC's "above 400 GHz available without licence" is
    not in RBR-4. Not encoded.
13. **RAC band plans are old** (6 m, 220, 70 cm, 33 cm, 23 cm, 13 cm:
    1995-1998) and the HF plan was read from an image (15 m digital/CW detail
    near 21.080-21.125 is ambiguous). Warn-only, never enforce. RAC's
    microwave page lists obsolete pre-WRC-2000 bands - must not be imported.
14. **US-Canada Convention (TIAS 2508)** text itself not read; relied on
    RIC-3 §8.1 and 47 CFR 97.107/97.119(g).
15. **CY0/CY9** appear in RIC-9 and CEPT Annex 4 but not in RBR-4 Sch. V;
    RIC-9 is provisional (2005).

Biggest risks for the TX guard: (a) letting `ca_basic` onto 10 m or any HF
(Basic alone is VHF+ only); (b) treating 220-222 MHz as open; (c) treating
60 m as a band rather than four channels + 15 kHz; (d) encoding 630 m at
5 W; (e) importing RAC's obsolete microwave bands; (f) forgetting that the
30 m bandwidth limit is 1 kHz (blocks SSB/AM there).
