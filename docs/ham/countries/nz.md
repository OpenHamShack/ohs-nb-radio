# New Zealand (NZ): amateur licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM (ohsradio) / OpenHamShack NB. Research only - no
code reads this file yet. Modelled on docs/ham/bandplan-r1-uk.md, whose UK
data was checked line by line against Ofcom's PDF (docs/ham/licence-check.md).

Markers: **[verified]** read in the primary source (cite page/section/clause);
**[secondary]** from a non-regulator source only; **[derived]** worked out
here; **UNCONFIRMED** not found in a primary source - must NOT be encoded as
a permission until confirmed. Never guess a limit.

The licence is law (the TX guard enforces it); the band plan is a voluntary
code (the guard warns).

**Summary of the NZ structure (it differs from most countries).** There is
no individual amateur station licence. Every qualified amateur transmits
under one shared *General User Radio Licence* (GURL) gazetted by RSM, plus
two shared *General User Spectrum Licences* (GUSLs) for the 3300-3410 MHz
range. There is one operator class (the GAOC). Power is 30 dBW (1000 W) PEP
transmitter output on almost every band, with EIRP limits on 2200 m, 630 m,
60 m, 11 m (telemetry) and 33 cm.

## Sources

Working copies were kept in a session scratchpad, not in the repo; the checksums identify what was read. Page = PDF page index (1-based)
unless the document prints its own page numbers, in which case the printed
number is used and said so.

| Key | Document (exact title) | Version / date (as printed) | URL | SHA-256 of the file read, pages |
|---|---|---|---|---|
| G25 | "Radiocommunications Regulations (General User Radio Licence for Amateur Radio Operators) Notice 2025" (NZ Gazette print, RSM-hosted copy) | Notice ID **2025-go3272**; "comes into force on 1 July 2025" (cl. 1(2)); "Dated at Wellington this 1st day of July 2025", signed Claire Smollett, National Manager RSM; footer "2025-go3272 01-07-2025 09:00"; Licence Number 409957; Licence "Commencement Date: 15 December 2023" (cl. 2(4)). Revokes the 2023 Notice 2023-go5698 (cl. 9(1)). | https://www.rsm.govt.nz/assets/Uploads/documents/gazette/radiocommunications-regulations-general-user-radio-licence-for-amateur-radio-operators-notice-2025.pdf (Gazette page https://gazette.govt.nz/notice/id/2025-go3272 is bot-blocked from here, see §11) | `7d362e49d12b71c6823bde6da4aa68ee3d1c40b8e1a5eddadd41372af6a26ce2`, 4 pp (printed pp. 1-4) |
| G23 | RRF "Record of Radio Licence" for the GURL, as published with the 2023 Notice (title on file: "general-user-radio-licence-for-amateur-radio-operators-notice-2023") | Licence ID 412924, commencement 15 Dec 2023, granted 6 Dec 2023. **Superseded** - read only to diff against G25. | https://www.rsm.govt.nz/assets/Uploads/documents/gazette/general-user-radio-licence-for-amateur-radio-operators-notice-2023.pdf | `aaa941708f36155f1c4bb0ca6d9cb31f1ce6677b6edb11b9a5c876465a1bcf79`, 8 pp |
| RRF1 | Register of Radio Frequencies (RRF) public API: GURL licence ID **426368** (licence number 409957), its spectrum records | Status "Current", commencement 2025-06-19, lastUpdated 2026-02-02, version 14; 46 spectrum rows, all "Current". Fetched 2026-10-08. | https://rrf.rsm.govt.nz/api/public_licence/radio-licence/426368 and .../public_licence/licence/426368/spectrums | `9017aed307d38b14924fca935c6559c78506bf7e44e41c7f386ac038fb76fc6f` (licence), `7c71edc1f4385a2b0d0c8a5749d73829d78f8f50c8cf8af3757f745e59225a6c` (spectrums); JSON |
| SL1 | RRF: "General User Spectrum Licence for Amateur Radio Operators", licence ID **404591** (licence number 402228), 3300-3400 MHz | Current; commencement 2023-07-01, expiry 2033-06-30; lastUpdated 2026-02-02. Fetched 2026-10-08. | https://rrf.rsm.govt.nz/api/public_licence/spectrum-licence/404591 (+ /licence/404591/spectrums) | `b95dbff80e2a087218e5b885dfc6d73632b33265ec93190590a3f53d35551168`, `5ee1e07aa8134d80c5c995c09271917f6ef14de5fcdd96ae84436c68033b94ff`; JSON |
| SL2 | RRF: GUSL for Amateur Radio Operators, licence ID **435381** (licence number 428073), 3400-3410 MHz | Current; commencement **2026-07-01**, expiry **2027-06-30**; lastUpdated 2026-05-07. Replaces ID 404593 (3400-3410, spectrum status "Expired", end 2026-06-30; the licence record itself returned "Access is denied"). | https://rrf.rsm.govt.nz/api/public_licence/spectrum-licence/435381 (+ spectrums); 404593 spectrums at .../licence/404593/spectrums | `ef8ee52ddb5c69cb45c9d9630227729cceb0588bbcb599a752270d52ed4ace1a`, `28e7e05cc56cef940c0e73be7241b5f25ce0b70ca847edd7153523d0a7780218`; 404593: `801cb91977aac2e7efbc73cd02959ee42948f6a04f28557406a7916f0f888ee8`; JSON |
| L34 | RSM letter to NZART on amateur use of 3300-3410 MHz (filename "rsm-letter-on-amateur-radio-use-of-3400-3410-mhz") | "2 June 2023", signed Daniel O'Grady, Manager RSM Policy and Planning; contains a later bracketed edit "[435381 from 1 July 2026]" (PDF ModDate 2026-06-25) | https://www.rsm.govt.nz/assets/Uploads/documents/gazette/rsm-letter-on-amateur-radio-use-of-3400-3410-mhz.pdf | `80374697318000a6f501696562d4f9cd302dd2a4d23c514494dcba7dc3d24c78`, 1 p |
| R01 | Radiocommunications Regulations 2001 (SR 2001/240), whole, legislation.govt.nz | "Version as at 4 September 2026" | https://www.legislation.govt.nz/regulation/public/2001/0240/latest/whole.html (WAF-protected; read via headless Chromium DOM dump) | `871021a7070197939d42b16566f80e217b9712d4788c3c0e572b3c8615c4ff70` (DOM dump, HTML) |
| P46 | RSM, "Radio Operator Certificate and Callsign Rules (PIB 46)" | Cover: "Issue 19.1 \| July 2025". Its amendment table lists "20 / June 2025 / Requirements for visiting radio amateur updated" (numbering inconsistency in the source). | https://www.rsm.govt.nz/assets/Uploads/documents/pibs/radio-operator-certificate-and-callsign-rules-pib-46.pdf | `74b805573c86114f20748067258dba8081eab1e746c92bf0a87fa8baf45df2b3`, 27 pp (printed page numbers cited) |
| W1 | RSM web pages: "Amateur Radio Operators GURL"; "Amateur Radio Operators GUSL"; "Visiting amateur operators"; "Amateur licences" (repeater/beacon/fixed link); "General User Radio Licence (GURL) notices" | undated web pages, fetched 2026-10-08 | https://www.rsm.govt.nz/licensing/frequencies-for-anyone/amateur-radio-operators ; .../amateur-radio-operators-gusl ; .../amateur-radio-operators/visiting-amateur-operators ; https://www.rsm.govt.nz/licensing/licences-you-must-pay-for/amateur-licences ; https://www.rsm.govt.nz/about/publications/gazette-notices/general-user-radio-licence-gurl-notices | `684cd19a…0aff`, `d103768b…ea14`, `cc812a36…61c0`, `8003b10c…4dfe`, `2db57a91…218b` (HTML) |
| C34 | RSM, "Assignment of the 3340-3460 MHz Radio Spectrum — Discussion document" + project page | "1 July 2026"; submissions "no later than 5pm on 26 August 2026"; project page "Last reviewed: 13 July 2026" | https://www.rsm.govt.nz/assets/Uploads/documents/consultations/2026-3340-3460-mhz-spectrum-band/assignment-of-3340-3460-mhz-radio-frequency-spectrum-discussion-document.pdf ; https://www.rsm.govt.nz/projects-and-auctions/current-projects/assignment-of-3340-3460-mhz-radio-spectrum | `37424cdd62374392eeb4d3fb19e27ea43c2d494c2a488635b851282cf57f84f1`, 76 pp; page `ace6e0cb…d56d` |
| C23 | RSM project pages "Future allocations of 2300 MHz & 2600 MHz spectrum" and "Future use of the 24–30 GHz spectrum" | "Last reviewed: 30 June 2026"; 24-30 GHz page has "July 2026 update" | https://www.rsm.govt.nz/projects-and-auctions/current-projects/future-allocations-of-2300-mhz-and-2600-mhz-spectrum ; .../future-use-of-the-24-30-ghz-spectrum | `6ca1c05c…1abf`, `1e17e1ab…dc74` (HTML) |
| T61 | CEPT ECC, Recommendation T/R 61-01 "CEPT Radio Amateur Licence" | Edition footer "Edition of 18 October 2024" on Annex 4 p. 10 (other pages carry older edition footers) | https://docdb.cept.org/document/925 (copy from the CA research run, `r23/ca/cept_4541.pdf`) | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691`, 13 pp |
| N1 | NZART, "New Zealand Amateur Radio Band Plans" (4-page chart, image-only PDF; read visually) | Web page: "printable copy of the current band plan (updated June 2026)"; every page footer "© Copyright NZART, April 2026"; upload path 2026/07 | https://nzart.org.nz/wp-content/uploads/2026/07/Bandplan-2026-June.pdf (index https://nzart.org.nz/info/band-plans/) | `261ca13696f8dbef9b9ac8430cfa71c88f62ef5a9f7a4401d3c0039829e369de`, 4 pp |
| N2 | NZART, "New Zealand 2 m Band Plan 2022" / "New Zealand 70 cm Band Plan 2022" | Review "completed in September 2022" (index page) | https://nzart.org.nz/wp-content/uploads/2024/11/NZ-2m-70cm-Band-Plan-2022-final.pdf | `cae36b7042e90c17a36460a96ad93b166f011528b30d1719f8ed0b80b7e80ba7`, 2 pp |
| N3 | NZART, "33 cm Band Plan", "ZL 33cm band plan version 1.4a" | approved by NZART Council 6 July 2021 (index page) | https://nzart.org.nz/wp-content/uploads/2024/11/33cm-Band-Plan-2021.pdf | `d8e3e4e2b621bd6479c2d7db1ce9b51ac4b9a3e86bcbf96242dcd0cee9e2b41e`, 1 p |
| N4 | "Amateur radio HF usage in New Zealand", compiled by Mark ZL3AB and Gary ZL2IFB (linked by NZART; "not a bandplan") | "Updated February 2026" | https://nzart.org.nz/wp-content/uploads/2024/11/NZ-Amateur-Radio-HF-usage-Feb26.pdf | `a27d6c3a6bb782127a378b5ff0ac29751fa7e822982e404747e6c351c5a475a6`, 12 pp |
| N5 | NZART web pages: "60 m Band Access"; "2009 – Access by NZ Radio Amateurs to Spot Frequencies Near 5 MHz"; "2006 – Operating on the 614 – 622 MHz band"; "Band Plans" index | 60 m page "UPDATE: 15 January 2025"; others undated | https://nzart.org.nz/info/60-m-band-access/ ; https://nzart.org.nz/info/2009-access-by-nz-radio-amateurs-to-spot-frequencies-near-5-mhz-2 ; https://nzart.org.nz/info/2006-operating-on-the-614-622-mhz-band ; https://nzart.org.nz/info/band-plans/ | `a4c4f9fc…94e68b`, `27ddfe4d…8b`, `bf81c872…ff`, `597d6073…72f` (HTML) |

---

## 1. Regulator and instruments

- **Regulator:** Radio Spectrum Management (RSM), a business unit of the
  Ministry of Business, Innovation and Employment (MBIE). Powers are the
  chief executive's under the Radiocommunications Act 1989 [verified, G25
  preamble; P46 §2.2].
- **Statute:** Radiocommunications Act 1989; **Regulations:**
  Radiocommunications Regulations 2001 (SR 2001/240), version as at 4 Sep
  2026 [verified, R01].
  - reg 6(3): transmission is prohibited except under a radio licence, a
    general user radio licence, or an exemption; reg 6(2)(b): regs 6-15H do
    not apply to transmissions under a general user *spectrum* licence (this
    is how the 3300-3410 MHz GUSLs sit outside the GURL regime) [verified, R01 reg 6].
  - reg 9: the chief executive may grant a GURL of a class; must publish it
    on the internet and gazette notice within 10 working days; reg 9(5)
    "General user radio licences grant every person the right to transmit
    radio waves on any frequency specified in the licence" [verified, R01 reg 9].
  - reg 22: where a certificate of competency is a licence condition,
    operating without one is an offence [verified, R01 reg 22].
  - regs 22A-29: certificates of competency issued by the chief executive
    or appointed Approved Radio Examiners (ARX); valid until revoked (reg
    26); may be suspended/revoked (reg 27); re-examination (reg 29)
    [verified, R01].
  - Schedule 1 cl. 8: call sign used must be the one on the licence, on the
    operator's certificate, or a temporary call sign authorised by gazette
    notice [verified, R01 Sch 1 cl 8].
  - Schedule 6 fee category A: "Licence for an amateur beacon, amateur
    fixed link, or amateur repeater" $66 (incl. GST) [verified, R01 Sch 6].
- **The operating licence (law the TX guard enforces):**
  "Radiocommunications Regulations (General User Radio Licence for Amateur
  Radio Operators) Notice 2025", **NZ Gazette 2025-go3272**, in force
  **1 July 2025**, licence number **409957**, licence commencement 15 Dec
  2023 [verified, G25 cl. 1-2]. It revoked the 2023 Notice (2023-go5698, 15
  Dec 2023) [verified, G25 cl. 9(1)]. The *only* change in 2025 was removing
  ITU-R M.1544 from the recognised overseas qualifications [verified, G25
  Explanatory Note]; the spectrum table is identical to the 2023 record
  [verified, diff of G23 §2 against G25 cl. 3, all 46 rows]. RSM's GURL
  notices index lists the 2025 Notice as current and the RRF shows licence
  409957 (ID 426368) "Current", last updated 2026-02-02, with 46 spectrum
  rows matching G25 exactly [verified, W1; RRF1]. No 2026 replacement notice
  was found [see §11 for the limits of that check].
- **3300-3410 MHz** is not in the GURL. It is authorised by two GUSLs
  ("General User Spectrum Licence for Amateur Radio Operators") created
  when management rights over 3300-3800 MHz started on 1 July 2023
  [verified, L34; W1 GUSL page; SL1; SL2].
- **Supporting rules:** PIB 46 "Radio Operator Certificate and Callsign
  Rules" (Issue 19.1, July 2025) - called up by GURL general condition 1
  [verified, G25 cl. 6(1); P46].
- **Band plan (voluntary):** NZART band plans (N1-N3). NZART states that
  MBIE defines band limits, internal segments derive from IARU Region 3
  plans with NZ adaptations [verified as NZART's statement, N1 p. 1 header;
  N5 index].

## 2. Licence classes (names, how obtained, what "class" key ohsradio would use)

| ohsradio key (proposed) | Name | How obtained | Privileges | Source |
|---|---|---|---|---|
| `nz_gaoc` | General Amateur Operator's Certificate (of Competency), "GAOC" | Pass a written exam approved by the chief executive covering Sch 4 cl 4(2) topics, or an exam meeting HAREC (CEPT T/R 61-02 Annex 6) requirements recognised by the chief executive; issued by an ARX together with a call sign. Only NZ citizens or residents (P46: "permanent" resident; visa > 1 year may be referred). | All bands/powers in G25 cl. 3 and the GUSLs, subject to the 5-25 MHz rule below | [verified, R01 Sch 3(d), Sch 4 cl 4; P46 §2.9.1, §3.6, §4.10.1; W1; G25 cl. 7(1)] |
| `nz_gaoc_new` (sub-state of `nz_gaoc`) | GAOC holder in first 3 months **or** with fewer than 50 logged contacts | automatic | Same as `nz_gaoc` **except no transmission on amateur bands between 5 MHz and 25 MHz** (i.e. 60, 40, 30, 20, 17, 15, 12 m). Logbook must be kept for at least a year and produced on request. | [verified, G25 cl. 7(3)] |
| `nz_visitor_cept` | Visiting operator with a current certificate/authorisation/licence that "meets the requirements of Recommendation CEPT T/R 61-01 or CEPT T/R 61-02" | No application for ≤ 90 days | Operates under the same GURL (same spectrum and power). Cl. 7(3) (5-25 MHz rule) is in the section for NZ operators only, so on its text does not apply to visitors [derived]. | [verified, G25 cl. 8(1); W1 visiting page] |
| `nz_visitor_long` | Visitor > 90 days | Written application to RSM Licensing with HAREC evidence etc. | Approval-based; privileges not stated | [verified, P46 §3.5.2; W1]; privileges UNCONFIRMED |

- **Only one class exists.** Schedule 3 lists only "general amateur
  operator's certificate" for amateurs [verified, R01 Sch 3(d)]. The
  *Limited* amateur operator's certificate exam was revoked 17 June 2004
  (Sch 4 cl 5) and holders were deemed GAOC holders [verified, R01 Sch 4 cl
  5 and Amendment Regulations 2004 reg 12]. There is no Advanced, Novice or
  Foundation class [verified by absence, R01 Sch 3; P46 App. B lists only
  GAOC for amateur].
- **No new entry-level qualification** was found in R01 (as at 4 Sep 2026),
  P46 (July 2025) or RSM/NZART pages read. **UNCONFIRMED** that none is
  under consultation (no RSM consultation page about it was found).
- **No station licence.** The GURL is shared by every amateur, free, no
  renewal [verified, W1 GURL page "Fees $0.00"].
- **Immigrants:** a valid HAREC (T/R 61-02) is recognised for operating
  under the GURL; reciprocal recognition with Australia ("Amateur
  Operator's Certificate of Proficiency (Advanced)") and Japan ("First
  Class" and "Second Class Amateur Radio Operator") for issuing a permanent
  NZ call sign [verified, P46 §3.7.1-3.7.2, printed pp. 14-15].
- **Club stations:** trustee must hold a GAOC; suffix "XT" allows
  supervised trainee operation, log kept 1 year [verified, P46 §3.3].

## 3. Frequency privileges and power, per class

Units: the instrument gives power in **dBW**. General condition 11:
"Except as provided to the contrary in this notice, maximum power in dBW is
the peak envelope power (PX) of the radio transmitter, as defined in the
International Radio Regulations Article 1, No. 1.157" → **PEP at the
transmitter output** [verified, G25 cl. 6(11)]. Special Condition 8: "The
maximum power is the radiated power in dBW e.i.r.p." [verified, G25 cl.
5(8)]. Watts are [derived]: 30 dBW = 1000 W; 14 dBW = 25.1 W; 11.8 dBW =
15.1 W; 7 dBW = 5.0 W. NZART's chart prints the same watt values (5 W, 25 W,
15 W) [secondary, N1 p. 1-2].

Status column: "Primary" here only means the GURL attaches no SC1 "accept
interference / must not cause interference" condition; the GURL never uses
the words primary/secondary [derived]. SC1 = "These frequencies are, or may
be, allocated for use by other services. Amateur operators must accept
interference from, and must not cause interference to, such other
services." SC2 = ISM/SRD designated, must accept interference from ISM and
SRD. SC3 = temporary basis until further notice. SC4 = telemetry or
telecommand only. SC5/SC6 = amateur-satellite earth-to-space / space-to-earth
also permitted. SC7 = unwanted emissions 800-915 MHz ≤ -79 dBW (-49 dBm)
e.i.r.p. in 100 kHz. SC8 = power is e.i.r.p. [verified, G25 cl. 5].

The Notice lists overlapping rows (e.g. 7.0-7.1 and 7.0-7.2). The guard
should allow the **union** of rows; where rows overlap, every overlapping
row carries the same dBW figure, so the power limit is unambiguous [derived
from G25 cl. 3].

All rows: G25 cl. 3 (printed pp. 1-2) unless marked. Low/High exactly as
printed (MHz). All classes: `nz_gaoc` and `nz_visitor_cept` identical;
`nz_gaoc_new` differs only where marked.

| # | Low (MHz) | High (MHz) | Ref. freq (MHz) | Power `nz_gaoc` / visitor | Unit and reference point | `nz_gaoc_new` | Status / conditions | Source |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.1300 | 0.1900 | 0.1600 | 7 dBW (5.0 W) | e.i.r.p. (SC8) | same | SC1, SC3 (temporary), SC8 | G25 p.1 |
| 2 | 0.4720 | 0.4790 | 0.4755 | 14 dBW (25.1 W) | e.i.r.p. (SC8) | same | SC1, SC8 | G25 p.1 |
| 3 | 1.8000 | 1.9500 | 1.8750 | 30 dBW (1000 W) | PEP, Tx output (GC11) | same | SC1 | G25 p.1 |
| 4 | 3.5000 | 3.9000 | 3.7000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.1 |
| 5 | 5.3515 | 5.3665 | 5.3590 | 11.8 dBW (15.1 W) | e.i.r.p. (SC8) | **—** (5-25 MHz rule) | SC1, SC8 | G25 p.1; cl. 7(3) |
| 6 | 7.0000 | 7.1000 | 7.0500 | 30 dBW | PEP, Tx output | **—** | SC5, SC6 (satellite) | G25 p.1 |
| 7 | 7.0000 | 7.2000 | 7.1000 | 30 dBW | PEP, Tx output | **—** | none (primary) | G25 p.1 |
| 8 | 7.1000 | 7.2000 | 7.1500 | 30 dBW | PEP, Tx output | **—** | SC1 | G25 p.1 |
| 9 | 7.2000 | 7.3000 | 7.2500 | 30 dBW | PEP, Tx output | **—** | SC1 | G25 p.1 |
| 10 | 10.1000 | 10.1500 | 10.1250 | 30 dBW | PEP, Tx output | **—** | SC1 | G25 p.1 |
| 11 | 14.0000 | 14.2500 | 14.1250 | 30 dBW | PEP, Tx output | **—** | SC5, SC6 | G25 p.1 |
| 12 | 14.0000 | 14.3500 | 14.1750 | 30 dBW | PEP, Tx output | **—** | none (primary) | G25 p.1 |
| 13 | 18.0680 | 18.1680 | 18.1180 | 30 dBW | PEP, Tx output | **—** | SC5, SC6 | G25 p.1 |
| 14 | 21.0000 | 21.4500 | 21.2250 | 30 dBW | PEP, Tx output | **—** | SC5, SC6 | G25 p.1 |
| 15 | 24.8900 | 24.9900 | 24.9400 | 30 dBW | PEP, Tx output | **—** | SC5, SC6 | G25 p.1 |
| 16 | 26.9500 | 27.3000 | 27.1250 | 7 dBW (5.0 W) | e.i.r.p. (SC8) | same | SC1, SC2 (ISM/SRD), **SC4 telemetry/telecommand only**, SC8 | G25 p.1 |
| 17 | 28.0000 | 29.7000 | 28.8500 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.1 |
| 18 | 50.0000 | 51.0000 | 50.5000 | 30 dBW | PEP, Tx output | same | none (primary) | G25 p.1 |
| 19 | 51.0000 | 54.0000 | 52.5000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.1 |
| 20 | 144.0000 | 146.0000 | 145.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.1 |
| 21 | 146.0000 | 148.0000 | 147.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.1 |
| 22 | 430.0000 | 440.0000 | 435.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.1 |
| 23 | 433.0500 | 434.7900 | 433.9200 | 30 dBW | PEP, Tx output | same | SC2 (ISM/SRD) | G25 p.1 |
| 24 | 435.0000 | 438.0000 | 436.5000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 25 | 915.0000 | 928.0000 | 921.5000 | 14 dBW (25.1 W) | e.i.r.p. (SC8) | same | SC2, SC7 (OOB 800-915 MHz), SC8 | G25 p.2 |
| 26 | 1240.0000 | 1300.0000 | 1270.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.2 |
| 27 | 1260.0000 | 1270.0000 | 1265.0000 | 30 dBW | PEP, Tx output | same | SC5 (satellite uplink only) | G25 p.2 |
| 28 | 2396.0000 | 2450.0000 | 2423.0000 | 30 dBW | PEP, Tx output | same | SC2 (ISM/SRD) | G25 p.2 |
| 29 | 2400.0000 | 2450.0000 | 2425.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 30 | 3300.0 | 3400.0 | 3350.0 | 30 dBW | "Peak Envelope Power" (RRF powerType); emission field "100MXXX" | same | GUSL SC1 (accept/no interference; licence may be cancelled at any time); expiry 2033-06-30 | SL1 |
| 31 | 3400.0 | 3410.0 | 3405.0 | 30 dBW | "Peak Envelope Power" (RRF); emission "10M0XXX" | same | GUSL SC1, SC2 (sat E-s), SC3 (sat s-E); **valid 2026-07-01 to 2027-06-30 only** | SL2 |
| 32 | 5650.0000 | 5670.0000 | 5660.0000 | 30 dBW | PEP, Tx output | same | SC5 | G25 p.2 |
| 33 | 5650.0000 | 5850.0000 | 5750.0000 | 30 dBW | PEP, Tx output | same | SC2 | G25 p.2 |
| 34 | 5830.0000 | 5850.0000 | 5840.0000 | 30 dBW | PEP, Tx output | same | SC6 | G25 p.2 |
| 35 | 10000.0000 | 10500.0000 | 10250.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.2 |
| 36 | 10450.0000 | 10500.0000 | 10475.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 37 | 24000.0000 | 24050.0000 | 24025.0000 | 30 dBW | PEP, Tx output | same | SC2, SC5, SC6 | G25 p.2 |
| 38 | 24050.0000 | 24250.0000 | 24150.0000 | 30 dBW | PEP, Tx output | same | SC1, SC2 | G25 p.2 |
| 39 | 47000.0000 | 47200.0000 | 47100.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 40 | 76000.0000 | 81000.0000 | 78500.0000 | 30 dBW | PEP, Tx output | same | SC1, SC5, SC6 | G25 p.2 |
| 41 | 122250.0000 | 123000.0000 | 122625.0000 | 30 dBW | PEP, Tx output | same | SC1, SC2 | G25 p.2 |
| 42 | 134000.0000 | 136000.0000 | 135000.0000 | 30 dBW | PEP, Tx output | same | none | G25 p.2 |
| 43 | 134000.0000 | 141000.0000 | 137500.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 44 | 136000.0000 | 141000.0000 | 138500.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.2 |
| 45 | 241000.0000 | 248000.0000 | 244500.0000 | 30 dBW | PEP, Tx output | same | SC1 | G25 p.2 |
| 46 | 241000.0000 | 250000.0000 | 245500.0000 | 30 dBW | PEP, Tx output | same | SC5, SC6 | G25 p.2 |
| 47 | 244000.0000 | 246000.0000 | 245000.0000 | 30 dBW | PEP, Tx output | same | SC2 | G25 p.2 |
| 48 | 248000.0000 | 250000.0000 | 249000.0000 | 30 dBW | PEP, Tx output | same | none | G25 p.2 |
| 49 | 275000.0000 | 1000000.0000 | 637500.0000 | 30 dBW | PEP, Tx output | same | SC1, SC3 (temporary) | G25 p.2 |

**Merged TX-guard ranges (union of rows) [derived from the table above]:**
0.130-0.190; 0.472-0.479; 1.800-1.950; 3.500-3.900; 5.3515-5.3665;
7.000-7.300; 10.100-10.150; 14.000-14.350; 18.068-18.168; 21.000-21.450;
24.890-24.990; 26.950-27.300 (telemetry/telecommand only); 28.000-29.700;
50.000-54.000; 144.000-148.000; 430.000-440.000; 915.000-928.000;
1240-1300; 2396-2450; 3300-3410 (GUSL; 3400-3410 date-limited);
5650-5850; 10000-10500; 24000-24250; 47000-47200; 76000-81000;
122250-123000; 134000-141000; 241000-250000; 275000-1000000 MHz.

### Gaps inside nominal bands (refuse for every class)

All [derived] from the absence of a row in G25 cl. 3 / GUSLs, which list
every authorised range:

- **2200 m:** NZ authorises 130-190 kHz, wider than the ITU 135.7-137.8 kHz
  band; nothing to refuse inside it. Below 130 kHz and 190-472 kHz: refuse.
- **160 m:** 1950-2000 kHz is **not** authorised (band ends 1.9500 MHz).
- **80 m:** 3900-4000 kHz not authorised (band ends 3.9000 MHz).
- **60 m:** only 5351.5-5366.5 kHz. The two AREC spot frequencies near 5
  MHz (5320.0-5322.8 and 5395.0-5397.8 kHz) are **not amateur bands** -
  see §3 exceptions.
- **11 m:** 26.95-27.30 MHz is telemetry/telecommand only (SC4) - refuse
  voice/ordinary amateur traffic there.
- **6 m:** whole 50-54 MHz authorised; nothing to refuse.
- **2 m:** whole 144-148 MHz authorised.
- **70 cm:** whole 430-440 MHz authorised.
- **33 cm:** 915-928 MHz only (not 902-928 as in the USA).
- **23 cm:** whole 1240-1300 MHz.
- **13 cm:** **2300-2396 MHz is NOT authorised** (2300-2395 MHz is under a
  mobile management right expiring 2030 [verified, C23]); the band is
  **2396-2450 MHz** only. Refuse 2300-2395.999 MHz.
- **9 cm:** only 3300-3410 MHz, via GUSL. 3410-3500 MHz not authorised. NZART
  chart: "We have no 9 cm Band in the new Amateur Radio GURL" [secondary, N1 p. 2].
- **6 cm:** 5650-5850 MHz only (5850-5925 not authorised).
- **3 cm:** 10000-10500 MHz.
- **1.2 cm:** 24000-24250 MHz.
- **No authorisation** found for 1.25 m (220 MHz), 2450-2483.5 MHz,
  3410-3500 MHz, 75.5-76 GHz, 81-81.5 GHz, 119.98-120.02 GHz, 141-148.5
  GHz, or anything between 250 and 275 GHz [derived].

### Per-band exceptions (60 m, 2200 m / 630 m EIRP and notifications, location exclusions, etc.)

- **EIRP bands:** 130-190 kHz 7 dBW e.i.r.p.; 472-479 kHz 14 dBW e.i.r.p.;
  60 m 11.8 dBW e.i.r.p.; 26.95-27.3 MHz 7 dBW e.i.r.p.; 915-928 MHz 14 dBW
  e.i.r.p. [verified, G25 cl. 3 + SC8]. No notification/registration
  requirement for 2200 m or 630 m was found [verified by absence in G25].
- **60 m:** one band 5351.5-5366.5 kHz, not channelised, 11.8 dBW e.i.r.p.,
  SC1 [verified, G25 cl. 3]. It entered the GURL with the December 2023
  licence (it is present in G23) [verified, G23 §2]; NZART: "Application
  for a sub licence is no longer required" and an NZART request for more
  power "was declined" [secondary, N5 60 m page]. Subject to the 5-25 MHz
  new-licensee rule [verified, G25 cl. 7(3)].
- **AREC 5 MHz spot frequencies (not amateur bands):** from 24 Aug 2006 the
  licensee of two frequencies permits temporary non-interference access by
  amateurs at 5.3214 and 5.3964 MHz centre (USB dial 5.3200 and 5.3950
  MHz, 2K8 SSB), **AREC activities only, AREC call signs**, no contests
  [secondary, N5 5 MHz page]. This is a third-party permission, not the
  GURL; the guard should not open these by default. Conditions **UNCONFIRMED**
  in any RSM source.
- **614-622 MHz ATV repeaters:** "not an amateur band"; NZART holds spectrum
  licences for specific ATV repeater sites; individual amateurs may operate
  only within those licences' parameters [secondary, N5 614 page, quoting
  MED letter POL/1/24/3/1 of 3 Aug 2006]. Not a GURL band - refuse.
- **New licensees (5-25 MHz):** GAOC holders may not operate between 5 MHz
  and 25 MHz until they have held the GAOC 3 months **and** logged 50
  contacts in that period [verified, G25 cl. 7(3)]. Bands affected
  [derived]: 60, 40, 30, 20, 17, 15, 12 m. 160 m, 80 m, 10 m and above
  remain available.
- **3300-3410 MHz (GUSL):** "secondary to the other use in the band and
  ... on an opportunistic basis"; RSM "strongly encourage[s]" listening first
  or checking the RRF; RSM may cancel the GUSL if interference reports
  arise [verified, L34 points 2-4; SL1/SL2 SC1]. **3400-3410 MHz licence
  expires 2027-06-30** [verified, SL2] - the guard must date-limit it.
- **Location:** "Transmit Location: All New Zealand" [verified, G25 cl.
  4(1)]. No exclusion zones in the GURL. ZL7/8/9/5 call signs relate to
  island/Antarctic operation (§7). Whether the GURL covers Antarctica (Ross
  Dependency) is **UNCONFIRMED**.
- **Airborne / maritime mobile:** no rule found in G25 [UNCONFIRMED; not
  prohibited on the text].

## 4. Emission, bandwidth and symbol-rate limits

- **None in the GURL.** G25 states no emission classes, bandwidth or symbol
  rate limits [verified by absence, G25 cl. 3-8].
- The RRF records each GURL row with an emission designator equal to the
  segment width plus "XXX" (e.g. 60 m "15K0XXX", 160 m "150KXXX", 2 m
  "2M00XXX", 70 cm "10M0XXX") [verified, RRF1]. These read as "any emission
  that fits in the segment", not as a per-signal bandwidth cap [derived].
  Implication: the guard's legal check is band-edge containment, not mode.
- **Encryption:** "Communications must not be encoded for the purpose of
  obscuring their meaning, except for control signals by the operators of
  remotely controlled amateur stations" [verified, G25 cl. 6(4)].
- **Content:** only between amateur stations; personal/self-training/
  technical; brief personal third-party messages allowed without fee
  [verified, G25 cl. 6(3)].
- **Unwanted emissions:** outside the bands must comply with ETSI ETS 300
  684 [verified, G25 cl. 6(8)]; on 915-928 MHz, emissions in 800-915 MHz ≤
  -79 dBW (-49 dBm) e.i.r.p. per 100 kHz [verified, G25 SC7]. GUSLs record
  an "Unwanted Emission Limit" of -50 at both band edges (unit not stated in
  the JSON) [verified, SL1/SL2; unit UNCONFIRMED].
- **ITU-R compliance "as far as is compatible with practical
  considerations"** [verified, G25 cl. 6(5)].
- **11 m:** telemetry/telecommand only [verified, G25 SC4].
- Band-plan bandwidth keys (voluntary) are in §9.

## 5. Antenna gain, ERP/EIRP treatment

- Default: **PEP at the transmitter output**; antenna gain is not counted
  [verified, G25 cl. 6(11)].
- SC8 bands: limit is **e.i.r.p.**, so antenna gain and feeder loss count
  [verified, G25 SC8]. The Notice does not say whether the e.i.r.p. figure is
  peak-envelope or mean; GC11's PX definition is stated for "maximum power
  in dBW ... of the radio transmitter" except where provided otherwise
  [verified]. Treat SC8 limits as **peak-envelope e.i.r.p.** (the
  conservative reading) - [derived]; the intended reference is
  **UNCONFIRMED**.
- RRF stores even the SC8 rows with powerType "Peak Envelope Power"
  [verified, RRF1] - a register artefact; the gazetted SC8 governs [derived].
- GUSLs carry a radiation-pattern record code "HTL", 0-360°, value 30
  [verified, SL1/SL2]; meaning of "HTL" **UNCONFIRMED** (possibly a
  horizontal-plane limit). Spectrum power is 30 dBW PEP [verified].
- Implication for ohsradio [derived]: on 2200 m, 630 m, 60 m, 11 m and 33 cm
  the guard needs the user's antenna gain (dBi) and feed loss to compare
  e.i.r.p.; with no data it should assume 0 dBi and warn.

## 6. Station types: repeaters, beacons, unattended / automatic, satellite (13 cm 2400-2450 amateur-satellite status)

- **Repeaters, beacons, fixed links:** "may not be established pursuant to
  this licence" [verified, G25 cl. 6(7); GUSLs same, SL1]. They need an
  individual radio licence applied for through an Approved Radio Certifier
  or Engineer, fee $66 per repeater/beacon/fixed-link transmitter per year
  [verified, W1 "Amateur licences"; R01 Sch 6 cat. A]. Not available in
  3300-3410 MHz [verified, L34]. NZART band plans refer frequency
  coordination to "ELG" [secondary, N1 p. 1, p. 4]; ELG's role/authority
  **UNCONFIRMED**.
- **Remote control:** implied lawful - GC4 exempts "control signals by the
  operators of remotely controlled amateur stations" from the
  no-encoding rule [verified, G25 cl. 6(4)]. No rule on unattended
  automatic (e.g. digipeater, unattended FT8) operation was found;
  NZART lists "Digipeaters Licenced in some regions" (144.625) [secondary,
  N1 p. 3]. Unattended automatic operation under the GURL: **UNCONFIRMED** -
  the guard should treat beacon/repeater/automatic modes as needing a
  separate licence.
- **Satellite:** amateur-satellite use is permitted only where SC5/SC6
  apply [verified, G25 SC5/SC6]:
  E-s and s-E: 7.0-7.1, 14.0-14.25, 18.068-18.168, 21.0-21.45,
  24.89-24.99, 28.0-29.7, 144-146, 435-438, **2400-2450**, 10450-10500,
  24000-24050, 47000-47200, 76000-81000, 134000-141000, 241000-250000 MHz;
  3400-3410 MHz (GUSL) [verified, SL2].
  E-s only: 1260-1270, 5650-5670 MHz. s-E only: 5830-5850 MHz.
  No satellite permission: 2396-2400 MHz, 3300-3400 MHz, 50-54, 430-435,
  438-440 MHz, 1240-1260/1270-1300 MHz [derived from absence].
- **13 cm 2400-2450:** amateur-satellite both directions (SC5, SC6) and ISM
  (SC2 on 2396-2450) [verified, G25 p. 2]. QO-100 uplink 2400.05-2400.30 is
  therefore within the GURL [derived] (QO-100 is not visible from NZ - not
  a practical concern).

## 7. Call signs, portable/location indicators, identification rules

- **Identification:** call sign "at least once every 15 minutes during
  communications" [verified, G25 cl. 6(2)]. Call-sign use must follow PIB
  46 [verified, G25 cl. 6(1)]. No language or mode-of-ID rule found.
- **Format:** "ZL", one digit 0-9, then one to six letters [verified, P46
  §3.2, printed p. 12]. Each amateur/club may hold one primary and one
  secondary permanent call [verified, P46 §3.2.1].
- **Series** [verified, P46 App. A Table 2, printed pp. 22-23]:

  | Prefix | Use | Issued by |
  |---|---|---|
  | ZL0 + letters | Temporary | RSM |
  | ZL1, ZL2, ZL3, ZL4 + 1-4 letters (A-Y first letter) | Ordinary amateur; single-letter = temporary | Amateur ARX |
  | ZL5 | Antarctica (temporary) | Amateur ARX |
  | ZL6 | NZART special purpose (only with NZART written approval, P46 §3.2.2.4) | Amateur ARX |
  | ZL7 | Chatham Islands (permanent only for residents > 90 days/yr) | Amateur ARX |
  | ZL8 | Kermadec Islands (temporary) | Amateur ARX |
  | ZL9 | Sub-Antarctic islands (temporary) | Amateur ARX |
  | ZL10-ZL100 + suffix | Commemorative anniversaries, 3 days-3 months | Amateur ARX |
  | ZM0 | Amateur special purposes | RSM (Table 3) |
  | ZM1-ZM9 | Amateur special events; any ZL holder may substitute ZM for ZL during a recognised contest or as control station for special events | G25 cl. 7(2); P46 §3.2.2, Table 3 |
  | ZK1-9 | "Amateur – AREC" (with Notes 2-3: ZK2 Niue and ZK3 Tokelau being phased/allocated to those territories) | NZART ARX (Table 1) |
  | ZL…XT (suffix) | Club station supervised trainee | P46 §3.3 |

  Temporary calls: 3-12 months (ZL10-100: 3 days-3 months), max two per
  holder, one single-letter; 5- or 6-letter temporary calls for special
  events [verified, P46 §3.2.2, §3.2.2.2]. ZL5/7/8/9 applicants must show
  genuine intention to visit and (except Chathams) permission to land
  [verified, P46 §3.2.2.1].
- **Niue / Tokelau / Cook Islands are not NZ amateur jurisdictions:** Cook
  Islands now E5, Niue E6, Tokelau ZK3 [verified, P46 Table 1 notes]. Out
  of scope for the NZ guard [derived].
- **Visitors:** home call with "ZL" as prefix or suffix, separated by "/"
  (telegraphy) or "stroke" (telephony); may use ZL7/ZL8/ZL9 on the
  Chathams/Kermadecs/Sub-Antarctic islands [verified, G25 cl. 8(2)-(3)].
- **Portable / mobile suffixes for NZ holders (/P, /M, /MM, district
  numerals when moving):** no rule found. **UNCONFIRMED** - the NZ call sign
  digit is not described as a district that must change on travel.
- **Call-sign class check [derived]:** since there is one class, a call
  sign's form cannot be used to infer privileges (except ZM/ZL0/ZL6 temp
  forms).

## 8. Reciprocal operating (visitors in; this country's licensees abroad: CEPT T/R 61-01 / ECC Rec (05)06, IARP, bilateral)

**Visitors into NZ:**
- Up to **90 days**, no application, if the certificate/authorisation/
  licence "meets the requirements of Recommendation CEPT T/R 61-01 or CEPT
  T/R 61-02", produced on request [verified, G25 cl. 8(1); W1; P46 §3.5.1
  (wording: "issued by countries participating in" T/R 61-01/61-02)].
- **ITU-R M.1544 was removed** as a qualifying route in the 2025 Notice
  [verified, G25 Explanatory Note]. *Inconsistency:* both GUSLs still list
  "ITU-R M.1544 or CEPT T/R 61-01 or CEPT T/R 61-02" [verified, SL1, SL2
  visitor condition 1] - so a visitor qualifying only via M.1544 is in the
  GUSL text but not the GURL. Guard should follow the GURL (narrower) [derived].
- Over 90 days: written approval from RSM Licensing (HAREC evidence,
  passport, NZ address, dates) [verified, P46 §3.5.2; W1].
- Visitors use the same GURL spectrum and power [verified, W1 visiting
  page: "You will operate ... under the New Zealand ... GURL"].
- ECC Rec (05)06 (CEPT Novice) is **not** a qualifying route [verified by
  absence in G25 cl. 8; NZ not listed in ECC (05)06 copy read in the CA
  run - secondary for this file].

**NZ licensees abroad:**
- NZ is listed in **T/R 61-01 Annex 4** (non-CEPT countries): call-sign
  prefix "ZL"; national licence equivalent to the CEPT licence: "General";
  privileges granted to CEPT licence holders: "General", footnote 19: "The
  'General User Radio Licence' allow holders of a CEPT amateur radio
  licence to operate in New Zealand for up to 90 days on all allocated
  amateur bands without the requirement to obtain any permits or approvals,
  or register with the regulator" [verified, T61 Annex 4 p. 10-11]. So a
  GAOC = CEPT licence for travel to T/R 61-01 countries [verified, T61].
- **Bilateral:** P46 lists reciprocal recognition with Australia (AOCP
  Advanced) and Japan (1st/2nd class) - for recognising *their*
  qualifications towards an NZ call sign [verified, P46 §3.7.2]. What
  Australia/Japan grant NZ holders is outside RSM documents
  (**UNCONFIRMED** here; see the AU research file for Australia).
- **IARP:** n/a (Americas/CITEL).

## 9. National band plan, per band (CW / narrow digital / SSB / FM simplex / repeaters with offsets / beacons / satellite / digital dial freqs)

Voluntary. Source N1 (NZART June 2026 / © April 2026) unless marked; pages
are N1 PDF pages. Keys [N1 p. 3]: **C** = CW or modes < 1 kHz bandwidth;
**A** = all modes < 16 kHz; **AN** = all modes < 6 kHz; **AW** = all modes;
**D** = data < 16 kHz; **DN** = data < 6 kHz; **1** = standard 1 MHz narrow
band segment; **T** = telemetry/telecontrol (11 m); **Ri/Ro** = repeater
input/output; **B** = beacons; **FM** = FM simplex; **S** = satellites;
**L** = linking. Note 1: end frequencies of each block are band limits.

Note: N1's header still links the **2017** GURL PDF (stale link) [verified,
N1 p. 1 header] - the legal band edges in §3 are from G25, and they agree
with every N1 band edge except 3300-3410 (GUSL, shown by N1 as such).

| Band | Segments (MHz unless stated) | Notes | Source |
|---|---|---|---|
| 2200 m | 0.130-0.190 AN | "Radiated power must not exceed 5 watts e.i.r.p." | N1 p.1 |
| 630 m | 0.472-0.479 AN | "25 watts e.i.r.p.", SC1 text | N1 p.1 |
| 160 m | 1.800-1.840 C; 1.840-1.950 AN | | N1 p.1 |
| 80 m | 3.500-3.550 C; 3.550-3.620 AN; 3.620-3.640 DN; 3.640-3.900 AN | N4: 3.620-3.640 "VK/ZL digimodes window"; 3595-3605 kHz civil emergencies | N1 p.1; N4 p.1-2 |
| 60 m | 5.3515-5.354 C; 5.354-5.366 AN ("USB for phone operation"); 5.366-5.3665 DN | "Maximum Effective Isotropic Radiated Power is 11.8 dBW (15 Watts)" | N1 p.1 |
| 40 m | 7.000-7.030 C; 7.030-7.040 DN; 7.040-7.200 AN; 7.200-7.300 AN "Secondary Use" | 7105-7115 kHz civil emergencies (N4) | N1 p.1; N4 p.3 |
| 30 m | Official: 10.100-10.140 C; 10.140-10.150 D. **Trial:** 10.100-10.120 C; 10.120-10.130 AN (SSB, "100W Maximum"); 10.130-10.150 D | N4: "ZL trial for 12 months from 1 November 2025 - 100w recommended". The GURL itself places no mode or 100 W limit here (legal limit 30 dBW PEP). | N1 p.1; N4 p.3 |
| 20 m | 14.000-14.070 C; 14.070-14.112 DN; 14.112-14.350 AN | 14.100 NCDXF beacon (N4) | N1 p.1; N4 p.4 |
| 17 m | 18.068-18.100 C; 18.100-18.110 DN; 18.110-18.168 AN | 18.110 NCDXF beacon (N4) | N1 p.1 |
| 15 m | 21.000-21.070 C; 21.070-21.125 DN; 21.125-21.450 AN | 21.150 NCDXF beacon (N4) | N1 p.1 |
| 12 m | 24.890-24.920 C; 24.920-24.930 DN; 24.930-24.990 AN | 24.930 NCDXF beacon (N4) | N1 p.1 |
| 11 m | 26.950-27.300 T | "Telemetry or tele-control only, 5 W EIRP Maximum, Secondary allocation" | N1 p.1 |
| 10 m | 28.000-28.050 C; 28.050-28.150 DN; 28.150-29.500 A; 29.500-29.600 Ri; 29.600-29.700 Ro | N4: FM repeater inputs 29.520-29.580, outputs 29.620-29.680 (output = input **+100 kHz**; user transmits 100 kHz below the output); FM simplex calling 29.600; satellite downlinks 29.300-29.510 | N1 p.1; N4 p.7-8 |
| 6 m | 50.000-50.110 C; 50.110-51.0 AN; 51.0-52.6 A; 52.6-53.0 Ri; 53.0-53.6 AN; 53.6-54.000 Ro | Beacons 50.000-50.080; 50.110 international calling; 50.125-50.150 intl CW/SSB. Repeater offset not stated (52.6-53.0 in, 53.6-54.0 out; offset **UNCONFIRMED**, likely 1 MHz) | N1 p.1 |
| 2 m | 144.000-144.100 C; 144.100-144.250 A; 144.250-144.300 B; 144.300-144.575 A; 144.575-144.700 D; 144.700-145.200 Ri; 145.200-145.300 A; 145.300-145.800 Ro; 145.800-146.000 S; 146.000-146.4125 Ri; 146.4125-146.600 FM; 146.600-147.0125 Ro; 147.0125-147.3615 Ro (printed "147.3615", probably 147.3625); 147.3615-147.6125 FM/D; 147.6125-148.000 Ri | **Repeater offset: inputs -600 kHz for outputs up to and including 147.000 MHz; +600 kHz above 147.000** (exception Rotorua linear 144.350 out/144.950 in). Amateurs secondary 146-148. | N1 p.1, p.3 |
| 2 m channel list | 144.000-144.100 EME (Oceania); 144.025-144.035 EME (R3); 144.100 Oceania SSB/CW calling (outside NZ); 144.120 JT65/MSK144/Q65/FT4/FT8 weak signal; 144.174 FT8 (R3); 144.200 NZ SSB/CW calling; 144.230 meteor scatter; 144.250-144.300 beacons (geographic, 1 kHz, horizontal pol.); 144.300-144.335 WSPR/FTx/JTx/CW non-geographic beacons ≤ 200 Hz; 144.350 Rotorua linear repeater output; 144.400 AM/RTTY/experimental; 144.450 linear repeater output spare; 144.489 WSPR (R3); **144.500 FM calling**; 144.550 narrow digital; **144.575 APRS**; 144.600-144.700 DV simplex; 144.625 digipeaters (licensed some regions); 144.650 packet; 144.950 Rotorua linear input; 147.050 "Linear Repeater Input, Spare for future use"; 144.725-145.200 repeater inputs; 145.225 FM simplex experimental; 145.250 SSTV/fax/Hell; 145.275-145.300 FM simplex experimental; 145.325-145.775 repeater outputs; 145.800-146.000 satellites; 145.825 satellite APRS; 146.025-146.400 repeater inputs; 146.425-146.600 FM simplex; 146.625-147.375 repeater outputs; 147.400-147.450 DV hotspots; 147.475-147.600 FM simplex; 147.625-147.975 repeater inputs | Note-1: Australian beacons 144.400-144.600. Note-2: DV gives way to licensed digipeaters. (2022 plan N2 identical except no 144.950/147.050 lines.) | N1 p.3; N2 p.1 |
| 70 cm | 430.000-431.95 L; 431.95-432.25 EME A; 432.25-432.3 B; 432.3-432.6 AN; 432.6-432.8 DN; 432.8-433.0 FM; 433.0-435.0 Ri; 435.0-438.0 S; 438.0-440.000 Ro | **Repeaters normally -5 MHz** (input 5 MHz below output); positive offset or a 7 MHz negative offset available via ELG where SRD/LIPD interference on 433 MHz | N1 p.1, p.4 |
| 70 cm channel list | 430.000-431.950 repeater links and 7 MHz-offset inputs; 431.950-432.000 EME guard (Oceania); 431.900-432.240 EME (R3); 432.065 JT65/MSK144/Q65/FT4/FT8; 432.100-432.300 narrow band ≤ 6 kHz; 432.100 Oceania SSB/CW calling; 432.174 FT8 (R3); 432.200 NZ SSB/CW calling; 432.230 MS; 432.250-432.300 beacons; 432.300 WSPR Oceania; 432.300-432.312 non-geographic beacons ≤ 200 Hz; 432.325-432.375 FM simplex; 432.400 AM/RTTY/exp; 432.425-432.475 FM simplex exp; **432.500 FM calling**; 432.525 AM/RTTY/exp; 432.550 narrow digital; 432.575 APRS/simplex data; 432.600 DV simplex; 432.625-432.675 FM digital; 432.650 packet; 432.675 packet (secondary); 432.700 VOIP FM simplex; 432.725-432.800 DV simplex; 432.825-432.975 FM simplex; 433.000-434.975 repeater in/out; 434.800-435.000 national system repeaters; 435.000-438.000 satellites; 438.000-439.775 repeater in/out; 438.325-438.375 DV hotspots; 439.800-440.000 national system repeaters | Notes 1-4 as above; Australian beacons 432.400-432.600 | N1 p.4; N2 p.2 |
| 33 cm | 915-916 Ri (915.5-916 recommended); 916-917 L (point-to-point); 917-925 ATV analogue/digital; 925-926 standard 1 MHz narrow band segment; 926-927 L; 927-928 Ro (927.5-928) | SSB calling 925.200; beacons 925.250-925.300; FM simplex 925.550 (123.0 Hz CTCSS recommended); legacy FM simplex 925.5; P25 925.600 (NAC 293); D-Star 925.700; DMR 925.800 (TS1, CC1, TG99). "14 dBW EIRP" | N1 p.2; N3 |
| 23 cm | 1240-1258 AW; 1258-1260 L; 1260-1270 S (uplink only); 1270-1274 Ri; 1274-1290 AW; 1290-1294 Ro; 1294-1296 AW; 1296-1297 "1"; 1297-1298 AW; 1298-1300 L | SSB calling 1296.2; FM calling 1296.5; beacons 1296.25-1296.30; **repeaters -20 MHz** | N1 p.2 |
| 13 cm | 2396-2400 L; 2400-2401 "1"; 2401-2405 S; 2405-2407 Ri; 2407-2425 AW; 2425-2427 Ro; 2427-2446 AW; 2446-2450 L | SSB calling 2400.200; FM calling 2400.500; beacons 2400.250-2400.300; **repeaters -20 MHz**; satellite 2401-2450 | N1 p.2 |
| 9 cm | 3300-3355 AW; 3355-3359 Ri; 3359-3395 AW; 3395-3399 Ro; 3399-3400 AW; 3400-3401 "1"; 3401-3410 S | "Secondary allocation only, under a GUSL ... We have no 9 cm Band in the new Amateur Radio GURL". Repeater licences not available in this band (L34). | N1 p.2 |
| 6 cm | 5650-5670 S (E-s); 5670-5760 AW; 5760-5761 "1"; 5761-5830 AW; 5830-5850 S (s-E) | | N1 p.2 |
| 3 cm | 10000-10050 L; 10050-10368 AW; 10368-10369 "1"; 10369-10400 AW; 10400-10450 L; 10450-10500 S | | N1 p.2 |
| 1.2 cm | 24000-24048 S; 24048-24049 "1"; 24049-24050 S; 24050-24250 AW | | N1 p.2 |
| 6 mm | 47000-47088 AW; 47088-47089 "1"; 47089-47200 AW | | N1 p.2 |
| 4 mm | 76000-76032 AW; 76032-76033 "1"; 76033-81000 AW | | N1 p.2 |
| 2.4 mm | 122250-123000 AW | | N1 p.2 |
| 2.1 mm | 134000-141000 AW | | N1 p.2 |
| 1.2 mm | 241000-250000 AW | | N1 p.2 |
| 1-0.3 mm | 275000-1000000 AW | | N1 p.2 |

**Standard 1 MHz narrow-band segment (f = segment start)** [N1 p. 4]: f+0.200
SSB calling; f+0.250-0.300 beacons (1 kHz); f+0.500 FM calling; f+0.550 FM
simplex; f+0.575 APRS/simplex data; f+0.600 P25; f+0.650 packet; f+0.700
D-Star; f+0.750 YSF/NXDN; f+0.800 DMR.

**HF digital dial frequencies (kHz, USB dial), from N4 ("not a
bandplan")** [secondary, N4 pp. 1-8]: FT8 1840, 3573, 5357, 7074, 10136,
14074, 18100, 21074, 24915, 28074; FT4 3575, 7047.5, 10140, 14080, 18104,
21140, 24919, 28180; WSPR 1836.6, 3592.6, 5364.7, 7083.6 (sic - N4 prints
7083.6, not the usual 7038.6), 10138.7, 14095.6, 18104.6, 21094.6, 24924.6,
28124.6; JS8Call 1842, 3578, 7078. 60 m sub-plan (N4): 5351.5-5354 CW and
digital ≤ 500 Hz (except FT8); 5354-5366 all modes ≤ 2700 Hz (USB); FT8
5357; 5366-5366.5 weak-signal ≤ 20 Hz. N4 notes NZ amateurs may also use
Region 2 digimode frequencies. SSB sideband: LSB 40 m and below, USB 20 m
and above, USB on 60 m [secondary, N4 note 6; N1 p.1].

## 10. Pending changes

- **3340-3460 MHz assignment (RSM consultation):** discussion document 1
  July 2026, submissions closed 5 pm 26 Aug 2026. RSM states "In this
  consultation we are not proposing any changes to this arrangement" (the
  amateur GUSLs) and "will keep a watching brief" [verified, C34 §5.3,
  printed p. 10-11]. Outcome pending as of 2026-10-08. Risk: increased
  private-network/FWA use; GUSLs cancellable at any time.
- **3400-3410 MHz GUSL (ID 435381) expires 30 June 2027** [verified, SL2];
  renewal is not guaranteed.
- **30 m SSB trial** (NZART/band plan, voluntary): 12 months from 1 Nov
  2025 → ends about 1 Nov 2026 [secondary, N4 p.3 fn 3]. Band plan only;
  no GURL change.
- **2300 MHz:** June 2026 Cabinet decisions on 2300-2395 MHz management
  rights (expire 2030); no amateur change stated [verified, C23]. Amateur
  13 cm (2396-2450) unaffected on the text.
- **24-30 GHz:** decisions April 2026 concern 26/28 GHz mobile and
  satellite; amateur 24.00-24.25 GHz not mentioned in what was read
  [verified, C23 page extract] - impact **UNCONFIRMED**.
- **GURL itself:** no draft or consultation for a new amateur GURL was
  found on the RSM pages read (W1, C23, current projects list). **UNCONFIRMED**
  that none exists (gazette.govt.nz search was blocked).
- NZART celebrates its centenary in 2026 (founded 1926) - no regulatory
  effect [secondary, search result only].

## 11. Confidence and gaps (every UNCONFIRMED item, what was found instead)

**High confidence (verified):** band edges and dBW limits for all 46 GURL
rows (gazette text G25, cross-checked row-for-row against the live RRF
record of licence 409957, last updated 2026-02-02); PEP-at-transmitter
reference (GC11) and e.i.r.p. bands (SC8); 5-25 MHz new-licensee rule;
15-minute ID; visitor rule (T/R 61-01/61-02, 90 days, M.1544 removed);
single GAOC class; 3300-3400 (to 2033) and 3400-3410 (2026-07-01 to
2027-06-30) GUSLs at 30 dBW PEP; repeater/beacon licensing outside the GURL.

**UNCONFIRMED / gaps:**
1. **Currency of the GURL beyond 2026-02-02.** gazette.govt.nz is behind an
   Incapsula bot wall (plain curl and headless Chromium both refused), so
   no direct gazette search for a post-July-2025 amateur notice was
   possible. Found instead: RSM's GURL index (fetched today) still lists the
   2025 Notice; RRF licence 426368 "Current". Re-check on gazette.govt.nz
   by hand before release.
2. **e.i.r.p. reference (peak vs mean)** for SC8 bands - Notice silent;
   guard should use peak-envelope e.i.r.p. (conservative).
3. **GUSL "HTL 30" radiation-pattern field** and the unit of the "-50"
   unwanted-emission limits - not explained in any document read.
4. **Unattended/automatic operation** (digipeaters, unattended digital
   modes) under the GURL - no rule found; treat as needing an individual
   licence.
5. **Portable/mobile suffix conventions** for NZ licensees - none found in
   G25 or P46.
6. **Over-90-day visitors' privileges** and **whether GURL covers Ross
   Dependency/Antarctica (ZL5)** - not stated.
7. **AREC 5 MHz spot frequencies** (5320/5395 kHz dial) - NZART page only;
   it is a third-party permission, not an amateur allocation; no RSM text.
8. **614-622 MHz ATV** - NZART page only; not a GURL band.
9. **6 m repeater offset** (52.6-53.0 in / 53.6-54.0 out) - not stated in
   N1; "ELG" coordination role not documented by RSM.
10. **Band-plan typos as printed:** "147.3615" (likely 147.3625) [N1 p.1];
    WSPR 40 m "7083.6" [N4] (WSPR convention is 7038.6); "147.050 Linear
    Repeater Input" sits inside the repeater-output segment. Do not encode
    these without checking with NZART.
11. **PIB 46 version label** - cover "Issue 19.1 July 2025" vs amendment
    table "Issue 20 June 2025".
12. **No new entry-level licence** - none found; no consultation found; not
    proven absent.
13. **Reciprocal privileges abroad** for NZ holders beyond T/R 61-01
    (e.g. what Australia/Japan grant) - outside RSM documents.

**Biggest risks for the TX guard:**
- **13 cm starts at 2396 MHz, not 2300** - radios/firmware built for US/AU/UK
  plans would permit 2300-2396 MHz, which is a mobile management right in
  NZ.
- **160 m ends at 1950 kHz, 80 m at 3900 kHz, 33 cm is 915-928 MHz only.**
- **9 cm (3300-3410) is GUSL-only and date-limited** (3400-3410 expires
  2027-06-30; both cancellable at any time). Encode with an expiry date.
- **New licensees** (< 3 months or < 50 contacts) must be blocked from 5-25
  MHz - the guard needs a user-declared flag (licence date + contact count).
- **11 m (26.95-27.3 MHz) is telemetry/telecommand only at 5 W e.i.r.p.** -
  a generic "amateur band" table that includes it would allow illegal voice.
- **EIRP bands** need antenna gain to be enforced correctly.
- Visitors are covered by the GURL, but NZ's own 5-25 MHz rule is only
  textually for NZ operators.
