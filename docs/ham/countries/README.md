# National licences and band plans: index

Researched 2026-10-08 for OpenHamShack HAM / OpenHamShack NB, to extend the UK-only
licence guard (`ohsradio/licences/ofcom.py`, `ohsradio/plans/rsgb_2026.py`) to
eleven more countries. Each file follows one template: sources (with
SHA-256 of every downloaded document), regulator and instruments, classes,
a per-sub-allocation power table with the source's own wording and a
translation, satellite/QO-100, CEPT equivalence, callsigns, national band
plan, and a confidence/gaps section. The encoding interface is
`docs/ham/adding-a-country.md`.

**Nothing here has had the line-by-line second check the UK entry had**
(`licence-check.md`). Each file was compiled from primary sources by one
research pass; before a country's licence table is encoded, do the same
check against the downloaded PDF it cites. Anything marked
**[UNCONFIRMED]** must be encoded as "refused", never as a guess.

**Encoded 08/10/2026** as regimes in `ohscore/licences/` (`comreg`, `bnetza`,
`rdi`, `bipt`, `arcep`, `setid`, `mimit`, `nkom`, `pts`, `digst`, `traficom`,
`fcc`, `ised`, `acma`, `rsm`), each with `tests/test_licence_<iso>.py`; the
countries in `ohscore/countries.py` WRITTEN, the repeater pairs in
`ohsradio/plans/repeaters.py`. Each module's docstring lists what it refuses
because the research could not confirm it. Still owed: the line-by-line
check above, for every one of them.

## Index

| Country | Regulator | Classes (code id) | Licence instrument (in force) | Band plan | Licence conf. | Plan conf. |
|---|---|---|---|---|---|---|
| [Ireland](ie.md) | ComReg | `cept1`, `cept2` (identical bands; Morse only) | ComReg 09/45R6 Guidelines (29 May 2023) under S.I. 192/2009 | IRTS (via archive.org; irts.ie blocks scripts) | high | medium |
| [Germany](de.md) | BNetzA | `a`, `e`, `n` (N since 24 Jun 2024) | AfuV + Anlage 1, BGBl. 2024 I Nr. 175 (24 Jun 2024); Vfg 15/2025 callsigns | DARC (6 m 04/2026 ... 23 cm 2011) | high | medium |
| [Netherlands](nl.md) | RDI | `f`, `n` (no class A exists) | Regeling gebruik van frequentieruimte met meldingsplicht 2015, Bijlage 1 (version from 20 Jun 2024) | RDI Gedragslijn (Jun 2021) | high | medium |
| [Belgium](be.md) | BIPT | `a`, `b`, `c` | BIPT Council decision 24 May 2019 (Bijlage 2); KB 18-12-2009 as amended | UBA | medium-high (power reference unstated) | medium |
| [France](fr.md) | ARCEP / ANFR | `harec`, `classe3` (legacy, not issued) | ARCEP 2012-1241 as amended by 2013-1515 and 2019-1412; arrêté 21 Sep 2000 | REF (HF 2016/2021, VHF+ 2017) | high | medium |
| [Spain](es.md) | Ministerio para la Transformación Digital (SETID) | `autorizacion` (single class) | Orden IET/1311/2013; Orden IET/614/2015; CNAF Orden TDF/732/2026 (18 Jul 2026) | URE | medium-high | medium |
| [Italy](it.md) | MIMIT | `a`; `n` created 2026 but unpublished | Allegato 26 (DM 1 Mar 2021); CCE arts 134-145; PNRF 31 Aug 2022; DM 26 Jan 2026 | ARI (VHF+ Rev 0.6 2018; IARU R1 HF) | medium-high (A), low (N) | medium |
| [Norway](no.md) | Nkom | `full`, `begrenset` | Forskrift om radioamatørvirksomhet, FOR-2026-03-23-465 (23 Mar 2026) | NRRL (2018/2019, predates the law) | high | medium |
| [Sweden](se.md) | PTS | `certifikat`, `insteg` | PTSFS 2025:1 (17 Mar 2025) | SSA HF v3.3, VUHF v3.2 (30 Sep 2025) | high | medium-high |
| [Denmark](dk.md) | Digitaliseringsstyrelsen | `a`, `b`, `d` | BEK nr. 499 of 29 May 2026 (1 Jul 2026) | EDR (web; 4 m plan not found) | high | low-medium |
| [Finland](fi.md) | Traficom | `perus`, `yleis` | Radioamatöörimääräys 6 K/2019M; Radiotaajuusmääräys 4 AG/2026M (31 Mar 2026) | none national: IARU R1 + pairs fixed in the regulation | high | medium |

Corrections to the brief that came out of the research: Spain's Orden
ITC/1791/2006 is repealed (IET/1311/2013 replaced it); the Netherlands has
no class A; Denmark's regulator is now Digitaliseringsstyrelsen; Norway's
2009 regulation was replaced in March 2026.

## CEPT mapping (visiting operators)

| Country | T/R 61-01 (HAREC) | ECC Rec (05)06 (Novice) | National only |
|---|---|---|---|
| IE | cept1, cept2 | not implemented: UK Foundation/Intermediate may not operate | — |
| DE | a | e | n |
| NL | f | n | — |
| BE | a | b | c |
| FR | harec | not implemented | classe3 |
| ES | autorizacion | no information found | — |
| IT | a | n (adopted, not in force) | — |
| NO | full | not implemented | begrenset |
| SE | certifikat | not implemented | insteg |
| DK | a | b | d |
| FI | yleis (perus also listed in T/R 61-01 as "P") | perus listed | — |

## Cross-country differences that affect the code

**1. The power reference differs by country, by class and by row.** The
UK's (watts, "PEP"|"ERP"|"EIRP") per row and class is necessary but not
sufficient:

- Germany: PEP at the transmitter for A and E, but **ERP for every class-N
  row** (2 m/70 cm 6.1 W ERP, 10 m 10 W ERP), and an extra 3.05 W ERP cap
  for all classes on 1247-1263 MHz.
- Finland: one figure meaning PEP if the carrier is suppressed by at least
  6 dB and carrier power otherwise; above 30 MHz there are **separate
  carrier and PEP limits**, so a row needs two values.
- Spain: PEP to 440 MHz, EIRP from 23 cm, and **half the figure on any band
  where amateurs are secondary** (many rows are therefore derived).
- France: peak power at the transmitter output; EIRP on 136 kHz, 472 kHz,
  60 m.
- Sweden: PEP "supplied to the antenna system"; insteg 2 m is ERP.
- Denmark: on 135.7/472 kHz "ERP" is defined as PEP x antenna efficiency.
- Belgium: plain "W" with no stated reference on most rows — UNCONFIRMED.
- ECC Decision (25)01 23 cm limits mix EIRP and transmitter power in dBW.

**2. Rows need dates.** Effective-from: 23 cm under ECC (25)01 in Spain
(18 Jul 2026, already live), France (27 Jun 2028), Norway (1 Jan 2028),
Denmark (1 Jan 2029), Italy (2027 plan). Expiry: Spain's QO-100 resolution
(26 Dec 2026), 160 m contest permit (31 Dec 2026) and 8 m permit (~Apr
2027); Italy's 4 m experimental channels (31 Dec 2026). The guard must
refuse an expired row.

**3. "Needs a separate permission" is a row state**, refused unless the
operator records it (as the UK NoV): Ireland 2400-2450 MHz; Spain 2300-2450
MHz, most of 5650-5850 MHz and 24.05-24.25 GHz; Finland all of 23 cm;
Sweden QO-100 above 100 mW.

**4. Bandwidth, emission and mode limits are law in several countries**,
not band-plan advice: Germany (2.7 kHz most HF, 800 Hz on 30 m), Norway
(per band), Denmark, Finland, Ireland (30 m CW-only below 10.130 MHz),
France class 3 (A1A/A2A/A3E/G3E/J3E/F3E only, so no digital), Netherlands
(no contests on 30 m). The licence model needs per-class allowed emissions
and per-row max bandwidth.

**5. Satellite-only rows** (amateur-satellite, not terrestrial): Netherlands
2400-2450 MHz (F only), Italy 145.8-146 MHz and 5650-5670 MHz, Finland
435-436 MHz. A terrestrial TX there is illegal, not merely off-plan.

**6. QO-100 uplink (2400-2450 MHz) by class:**

| Country | Permitted classes and limit |
|---|---|
| IE | individual 12-month ComReg authorisation, satellite only, 25 W PEP |
| DE | a 75 W PEP, e 5 W PEP; n none |
| NL | f 120 W PEP, satellite uplink only; n none |
| BE | a 200 W; b, c none |
| FR | harec 120 W PEP transmitter output, no extra permission (2400-2415 MHz amateur-satellite row); classe3 none |
| ES | yearly resolution only: 2400-2410 MHz, max 1500 W EIRP, antenna gain >= 21.5 dBi, valid to 26 Dec 2026 |
| IT | a, via the ordinary amateur allocation (PNRF names amateur-satellite only at 2440-2450) [derived] |
| NO | full 100 W, begrenset 5 W |
| SE | certifikat 100 mW PEP (more needs a PTS permit); insteg none |
| DK | a 250 W, b 100 W, d none |
| FI | perus 30 W carrier / 120 W PEP; yleis 150 W / 600 W PEP |

**7. Classes with no 13 cm at all:** DE n, NL n, BE b and c, FR classe3, SE
insteg, DK d. Sweden has no 2300-2400 MHz (auctioned); Denmark none either;
Spain only 2316-2332 MHz without special authorisation.

**8. 4 m / 70 MHz:** IE 69.9-70.5 MHz 50 W PEP; NL f only, 50 W PEP, no
duplex; BE a only (69.950 MHz and 70.1125-70.4125 MHz); NO full only,
69.9-70.5 MHz; DK all classes, 69.8875-70.5125 MHz, 25 W; FI 70.0-70.3 MHz
(70.000-70.050 beacons only; no TX in 13 eastern municipalities, 25 W within
50 km of the Russian/Norwegian border); ES 70.150-70.250 MHz secondary; IT
three experimental 25 kHz channels at 10 W to end 2026; **DE, FR, SE none.**

**9. 60 m:** most use only the WRC-15 band 5351.5-5366.5 kHz at 15 W EIRP
(FR, ES, IT, SE, FI, NL; BE prints "e.u.v." = ERP, encode the stricter EIRP).
Exceptions: NO 5260-5410 kHz at 100 W; DK 5250-5450 kHz at 1000 W (a) / 100
W (b); IE six spot frequencies at 200 W PEP plus the WRC-15 band.

**10. Italy's allocation is narrower than IARU R1:** no 1810-1830 kHz,
434-435 or 438-440 MHz, 1245-1260 or 1298-1300 MHz, 10.0-10.3 GHz,
24.05-24.25 GHz; 80 m is secondary.

**11. Location-dependent rules** (need a setting, as the UK's `nearLondon`):
Finland 6 m/4 m border zones; Ny-Ålesund (Svalbard) 2-32 GHz within 20 km;
France's overseas departments are ITU Region 2 with extra bands; Dutch RDI
closures of 2320-2400 MHz around announced events (not expressible
statically). Faroe (OY), Greenland (OX), Åland (OH0) are separate callsign
areas; Faroe and Greenland rules were not researched.

**12. Repeater shift sign is per country**, never inherited from the IARU
channel name:

- 70 cm, 7.6 MHz: DE input below output (outputs 438-439); IE the reverse
  (outputs 430.8-431.0, inputs above).
- 70 cm, 1.6 MHz: FR/IT/NL/BE outputs 430.025-430.375 with input 1.6 MHz
  **above**.
- 70 cm, Nordic: -2 MHz (SE also -1.6 MHz on older machines; FI also -5
  MHz).
- 23 cm: DE/NL/BE/FR/IT use 28 MHz pairs (1242/1270/1298), FR/IT RS inputs
  28 MHz above outputs.

**13. Class from callsign is a weak hint at best.** Usable: SE (SH =
insteg, secondary source), DE (DO = e, DN9 = n, DA-DM = a), NL (PD = n, secondary), BE
(ON2 = b, ON3 = c), IE (class 2 suffix ends in B). Not usable: DK (free
choice of call), FI (no class in the call), NO (law says calls identify the
class, but the begrenset series is unpublished), and in BE the certificate,
not the call in use, decides privileges.

## Biggest gaps (details in each file's section 8)

- Belgium: whether its plain "W" figures are PEP and where measured.
- Italy class N, Norway begrenset callsigns: unpublished.
- Spain 6 m/4 m power: the law as read gives 300 W PEP, URE says 600 W.
- Germany 4 m: Bundesrat draft 364/26 pending, no conditions yet.
- Denmark: the EDR band plan is unreliable (UK content on its HF page) and
  the Danish 4 m plan was not found.
- France: Legifrance/ANFR blocked scripted downloads; visitor and suffix
  rules are from a secondary compendium.
- Band plans in general are older and less authoritative than the
  licences; most national plans predate the 2024-2026 licence changes.
