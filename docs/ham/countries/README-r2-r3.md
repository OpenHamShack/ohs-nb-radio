# Countries in ITU Regions 2 and 3: index rows and cross-country notes

**To merge into `docs/ham/countries/README.md`.** That file is owned by the
agent researching Europe. These rows and notes were kept here so the two
pieces of research did not collide. Compiled 2026-10-08.

## Index rows

| ISO2 | File | Regulator | Governing instrument (version in force 2026-10-08) | Classes (suggested ohsradio keys) | Band plan | Confidence |
|---|---|---|---|---|---|---|
| US | `us.md` | FCC | 47 CFR Part 97 (eCFR 2026-10-06; last amended with effect from 13 Feb 2026) + 47 CFR 2.106 footnotes | `novice`, `technician`, `general`, `advanced`, `extra` | ARRL band plan page (undated) + chart rev. 1/16/2026 | High: read from eCFR XML and diffed across the 2026 change |
| CA | `ca.md` | ISED | RBR-4 Issue 3 (July 2022) + Canadian Table of Frequency Allocations 2022 + Radiocommunication Regulations SOR/96-484 | `ca_basic`, `ca_basic_hf` (Honours / Morse / pre-2002), `ca_advanced` | RAC: HF plan effective 1 Jun 2023; VHF/UHF mostly 1995-98; 2 m Oct 2020 | High for law; RAC plans weak |
| AU | `au.md` | ACMA | Radiocommunications (Amateur Stations) Class Licence 2023, F2023L01648, compilation 0 (unamended) | `foundation`, `standard`, `advanced` | WIA band plan 2026 | High for law; ACMA web pages read via archive.org |
| NZ | `nz.md` | RSM (MBIE) | GURL for Amateur Radio Operators Notice 2025, Gazette 2025-go3272, in force 1 Jul 2025; 9 cm by two separate GUSLs | `nz_gaoc`, `nz_gaoc_new` (first 3 months / 50 QSOs), `nz_visitor_cept` | NZART chart June 2026 | High; a post-July-2025 Gazette notice could not be ruled out |

## Cross-country notes that matter to the code interface

These are things the UK-shaped `ofcom.py` / `rsgb_2026.py` model does not
yet express. Raise them with whoever owns `adding-a-country.md`.

### 1. Power is measured at different points, in different units

The limit field needs a unit and a reference point, plus a mode condition.

| Country | Default limit | Reference point | Exceptions |
|---|---|---|---|
| UK | 25 / 100 / 1000 / 400 W PEP | Transmitter output | Some rows are ERP or EIRP |
| US | 1500 W PEP | Transmitter output ("supplied to the antenna transmission line") | 60 m ERP (gain in dBd); 2200 m and 630 m EIRP **plus** a PEP cap; 76-81 GHz peak EIRP |
| CA | Basic 560 W PEP for SSB-type emissions, **190 W carrier for any other emission**; Advanced 2250 / 750 W; or 250 / 1000 W DC input | Into a matched load | 2200 m and 630 m EIRP; 60 m ERP |
| AU | Advanced 400 W pX for J3E/R3E (and C3F), **120 W pY (mean) otherwise**; Standard 100 W pX / 30 W pY; Foundation 10 W pX for any mode | Transmitter output (see note) | 2200 m / 630 m "pX EIRP" |
| NZ | 30 dBW PEP | Transmitter output | Five bands in dBW EIRP |

- **CA and AU tie the limit to the emission designator.** An SSB voice
  transmission and an FT8 transmission on the same band get different
  limits. In AU, FT8 is J2D, not J3E, so on the plain reading it gets the
  **mean** (pY) limit. In CA, J2D counts as "single sideband".
- **[derived] What the guard needs from each mode:** its designator, and its
  crest factor (to turn PEP into mean power).
- **AU wording is ambiguous.** The instrument says "radiated power", but its
  units (pX/pY) and the explanatory statement point to transmitter output.
  `au.md` §11 keeps this as UNCONFIRMED. Encoding the figure as a cap on
  transmitter output is the safe choice either way.

### 2. Classes are not simply ordered by power

Each country has its own oddities:

- **AU** classes differ in **which bands** they get, not just in power.
  Foundation has no 20 m, 17 m, 12 m, 30 m, 160 m or 6 m.
- **CA** Basic alone has **nothing below 30 MHz, including 10 m**. The
  Honours / Morse / pre-2002 holder is a separate key.
- **US** class limits are **legal sub-bands inside HF bands**, and they
  differ by ITU Region. Region 3 US territories have narrower 75 m and 40 m.
- **NZ** has one class, plus a time-limited restriction on new holders:
  no 5-25 MHz until the certificate has been held 3 months and 50 contacts
  made. That needs a "certificate date" setting or a checkbox.

### 3. Band-edge convention

- **AU, by law:** every band is (lower, upper]. The lower edge is excluded
  and the upper edge included (CL s 5(3)).
- **Elsewhere:** closed intervals, by convention.
- **[derived] Practical effect.** None, as long as the guard requires the
  whole occupied bandwidth to lie strictly inside the band. Do that
  everywhere.

### 4. Things that depend on where the operator is

All of these need operator settings, as the UK's `nearLondon` does.
Locator-based checks are too coarse near the boundaries.

- **US:**
  - north of Line A (no 420-430 MHz);
  - White Sands box (no 33 cm), with 50 W PEP within 241 km of it;
  - CO/WY box (four 33 cm slivers);
  - 70 cm 50 W PEP radar areas (US270);
  - Alaska within 800 km of Russia (630 m at 1 W EIRP);
  - **which ITU Region** the station is in (Region 2 or Region 3
    territories).
- **AU:**
  - **WA radio quiet zone**: no transmission at all within 150 km of
    26.704167 S, 116.658889 E;
  - 3.4-3.6 GHz excluded in about 200 HCIS map-grid cells and in
    spectrum-licensed areas. Refuse that band by default.
- **CA:** none found beyond the general non-interference rule.
- **NZ:** none found.

### 5. Allocations with dates, and allocations that are not in the main instrument

- **NZ 3400-3410 MHz** is valid **1 Jul 2026 – 30 Jun 2027 only**, under a
  separate GUSL. 3300-3400 MHz runs to 2033.
  - **[derived]** Allocation rows need an optional `valid_from` /
    `valid_to`.
- **US 3300-3450 MHz** is not in Part 97 at all. It is allowed only by
  footnote US103, "may be required to cease ... at any time", with no class
  or power stated. `us.md` recommends refusing it.
- **US 60 m** changed on 13 Feb 2026. Older data is wrong.

### 6. 60 m differs in all four countries, and from the UK

| Country | Who | Where | Limit | Bandwidth / modes |
|---|---|---|---|---|
| UK | Full | 11 UK segments | 100 W PEP and ≤ 200 W EIRP | ≤ 6 kHz |
| US | General and up | 4 channels (centres 5332, 5348, 5373, 5405 kHz) + 5351.5-5366.5 kHz | Channels **100 W ERP**; band **9.15 W ERP** | ≤ 2.8 kHz; phone, RTTY, data, CW |
| CA | `ca_basic_hf`, `ca_advanced` | Same 4 channels + 5351.5-5366.5 | **100 W ERP PEP** on all of it (Canada did not adopt RR 5.133B's 15 W EIRP) | ≤ 2.8 kHz; 2K80J3E / 2K80J2D / 60H0J2B / 150HA1A |
| AU | — | **Not authorised** (allocated in the spectrum plan, but not in the class licence) | — | — |
| NZ | GAOC (not `nz_gaoc_new`) | 5351.5-5366.5 only | **11.8 dBW EIRP** (15.1 W) | — |

**[derived]** The guard needs:

- an ERP/EIRP computation from antenna gain, accepting dBi or dBd;
- per-channel geometry: a dial at centre − 1.5 kHz for USB, and CW at the
  centre in the US.

### 7. Notifications before first transmission

- **US 2200 m / 630 m:** notify the Utilities Telecom Council (UTC), then
  wait **30 days**. Fixed stations only, and not within 1 km of a power
  line carrying a power-line-carrier signal on the band.
- **US 219-220 MHz:** 30 days' notice to ARRL, plus notice to or approval
  from the AMTS licensee. Data forwarding only, so refuse in OpenHamShack.
- None found in CA, AU or NZ.

### 8. Bands that exist only outside Region 1, or have different edges

The defaults in `ohsradio/bands.py` are UK / Region 1 shaped. They will need
per-country overrides.

| Band | US | CA | AU | NZ |
|---|---|---|---|---|
| 160 m | 1800-2000 | 1800-2000 | 1800-1875 (Advanced only) | 1800-1950 |
| 80 m | 3500-4000 | 3500-4000 | 3500-3700 + 3776-3800 | 3500-3900 |
| 40 m | 7000-7300 | 7000-7300 | 7000-7300 | 7000-7300 |
| 6 m | 50-54 | 50-54 | 50-54 (50-52 secondary, ≤ 100 kHz) | 50-54 |
| 4 m | none | none | none | none |
| 2 m | 144-148 | 144-148 | 144-148 | 144-148 |
| 1.25 m | 219-220 (restricted), 222-225 | 219-220, 222-225 (220-222 disaster relief only) | none | none |
| 70 cm | 420-450 | 430-450 | 430-450 | 430-440 |
| 33 cm | 902-928 | 902-928 | none | 915-928 (14 dBW EIRP) |
| 13 cm | 2300-2310 + 2390-2450 | 2300-2450 | 2300-2302 (Advanced) + 2400-2450 | **2396-2450 only** |

- **Repeater offsets.** All of these come from the band plans, and most are
  [derived] from paired ranges.

| Band | US | CA | AU | NZ |
|---|---|---|---|---|
| 2 m | ±600 kHz | ±600 kHz | ±600 kHz | ±600 kHz |
| 70 cm | ±5 MHz (local) | +5 MHz | **−7 MHz** (Blocks A/B), −5 MHz alternative | −5 MHz (7 MHz by arrangement) |
| 6 m | 500 kHz | 1 MHz | 1 MHz | about 1 MHz (UNCONFIRMED) |
| 23 cm | 12 MHz | 12 MHz | UNCONFIRMED | 20 MHz |

  - On 2 m the direction depends on the sub-band in every country.
  - **The guard should never derive an offset from a single per-band
    constant**, as `bands.py`'s `rpt_offset` does today.
- **No region-specific dial table was found or added.** The WSJT-X Region 2
  and Region 3 dial frequencies are not yet in `ohsradio/bands.py`.

### 9. Reciprocal operating: who maps to what

Sources:

- CEPT T/R 61-01, Edition 18 Oct 2024, Annex 4;
- ECC Rec (05)06, Edition 16 Jun 2023, Annex 4;
- each country's own text.

| Home licence | Equivalent to the CEPT licence (T/R 61-01) | CEPT Novice (ECC Rec (05)06) |
|---|---|---|
| US | Amateur Extra, Advanced (US citizens only) | General (only in countries that implement (05)06) |
| CA | Basic **and** Advanced, with call sign on the certificate | Not a participant |
| AU | Advanced | Not a participant |
| NZ | General Amateur Operator's Certificate (GAOC) | Not a participant |

| Visitor arriving with... | ...gets |
|---|---|
| CEPT licence, in the US | **Amateur Extra** privileges (§97.301(a),(b)). Call sign form W4/G4ABC. |
| CEPT licence, in CA | Basic + Advanced, capped at the home licence |
| CEPT licence, in AU | **Advanced**, up to 365 days, no registration |
| CEPT licence, in NZ | GURL privileges, up to 90 days; longer stays need RSM approval |
| CA licence, in the US | Canadian terms, capped at Extra. **The suffix goes after the call**: VE3ABC/W4. |
| US licence, in CA | US citizens and residents. Basic + Advanced, capped at the US privileges. Form W1AW/VE3. |
| US licence, in AU | Extra → Advanced; General → **Standard**; Technician → **Foundation** (for licences granted since 3 Jul 2017) |
| UK licence, in AU | Full → Advanced; Intermediate → Standard; Foundation → Foundation |
| NZ licence, in AU | General → Advanced |

- **The CEPT recommendations themselves.** T/R 61-01 lists Australia,
  Canada, New Zealand and the USA as non-CEPT participants. ECC Rec (05)06
  lists the USA (General) and the Dutch Caribbean only.
- **IARP** (CITEL, the Americas): the US and CA take part. In the US, a
  Class 1 IARP gets Extra HF privileges. Canada issues Class 1 only with
  12 wpm Morse, which is no longer examined.

### 10. QO-100 and 13 cm satellite status

- **QO-100 is not visible from any of the four countries** [derived].
  - From 25.9°E it is above the horizon only within about 81° of longitude
    of the sub-point. That puts every US/CA territory out of view; Puerto
    Rico, at about 65°W, is about 91° away.
  - Australia (113-154°E) and NZ (166-178°E) are at least about 87° away.
  - Western Australia, at about 113°E, is the nearest at roughly 87°.
    That is still beyond the 81° limit, even before latitude reduces it.
- **[derived] So for OpenHamShack NB in these countries,** satellite rules matter
  only generically.
- **2400-2450 MHz:**
  - It is amateur-satellite under RR 5.282 everywhere.
  - US: authorised for space stations (§97.207).
  - CA: secondary; 5.282.
  - AU: amateur secondary; satellite only via 5.282.
  - NZ: SC5/SC6, both directions.
- **[derived] Refuse the satellite segments in the guard,** as the UK guard
  does:
  - 435-438 MHz;
  - 145.8-146 MHz;
  - 29.3-29.51 MHz;
  - the 13 cm satellite sub-bands named in each national plan.

### 11. Source-access notes for whoever re-checks

- **CEPT docdb** (docdb.cept.org) serves an incomplete TLS certificate
  chain. Fetch with `curl -k` and verify the SHA-256 against the files'
  checksums.
- **fcc.gov** returns 403 to scripted fetches. Use the eCFR versioner API
  instead:
  - `/api/versioner/v1/versions/title-47.json?part=97` lists the amendment
    dates;
  - `/api/versioner/v1/full/<date>/title-47.xml?part=97` gives the full
    text, and needs `Accept-Encoding: gzip`.
- **acma.gov.au** did not answer from this network. Its pages were read
  from Internet Archive snapshots. legislation.gov.au works directly.
- **gazette.govt.nz** blocks automated search. RSM's register record and
  PDFs work.
