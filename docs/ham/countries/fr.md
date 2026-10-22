# France (FR): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

Scope: metropolitan France, Corsica, and the overseas departments/collectivities
governed by ARCEP decision 2012-1241 (Guadeloupe, Martinique, Guyane, Réunion,
Mayotte, Saint-Pierre-et-Miquelon, Saint-Barthélemy, Saint-Martin). New
Caledonia, French Polynesia, Wallis-et-Futuna and the TAAF have their **own**
table (arrêté du 2 mars 2021, NOR ECOI2101798A, ITU Region 3 / R1 columns) and
are **not** covered here; seen only via [K1], not encoded.

## Sources

All PDFs downloaded 2026-10-08 with `curl -L -A 'Mozilla/5.0' --max-time 60`,
HTTP 200, converted with `pdftotext -layout`; the A1 power column was also
checked by rendering pages 3-5 to PNG (`pdftoppm`), because the power cells are
merged across many rows and the text layout alone does not show their extent.

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| A0 | "Décision n° 2012-1241 de l'Autorité de régulation des communications électroniques et des postes en date du 2 octobre 2012 fixant les conditions d'utilisation des fréquences par les stations radioélectriques du service d'amateur ou du service d'amateur par satellite" (14 pp.) | 2 Oct 2012; JORF 7 Mar 2013 (NOR ARTL1304101S, per [K1]) | https://www.arcep.fr/uploads/tx_gsavis/12-1241.pdf | `1ab883ea2ff444c77b9a058f1da55ad8c670d8a1489fef54f5267875643f6fb6` | fr |
| A1 | "Décision n° 2019-1412 de l'Autorité de régulation des communications électroniques et des postes en date du 24 septembre 2019 modifiant la décision n° 2012-1241 modifiée …" (9 pp.) - **replaces paragraphs 1 and 2 of A0's annex in full; this is the current band/power table** | 24 Sep 2019; JORF 13 Feb 2020 (NOR ARTL1932668S, per [K1]) | https://arcep.fr/uploads/tx_gsavis/19-1412.pdf | `bfe689f456b2f5c8cc8a0f30c552dc67e34d3cd0234869e99cf119e53bb80620` | fr |
| A2 | "Décision n° 2013-1515 … du 17 décembre 2013 modifiant la décision n° 2012-1241" (7 pp.; intermediate version, superseded by A1; used only to confirm history: added 472-479 kHz, 2400-2415 MHz sat) | 17 Dec 2013; JORF 12 Mar 2014 | https://www.r-e-f.org/images/stories/ARCEP/2013_1515.pdf | `164443d72868054b506505461c00167846e0dac8017da75f0305ae2e9352d06c` | fr |
| L1 | Arrêté du 21 septembre 2000 fixant les conditions d'obtention des certificats d'opérateur, d'attribution et de retrait des indicatifs des services d'amateur (consolidated, LEGITEXT000020278007) | Consolidated version "06 June 2021" (last amended by arrêté du 2 mars 2021, NOR ECOI2101792A) | https://www.legifrance.gouv.fr/loda/id/LEGITEXT000020278007 | not downloaded (Legifrance returns a Cloudflare 403 to curl); Art. 3, Art. 5 and Annex II digit table read via WebFetch 2026-10-08 | fr |
| K1 | F6KGL/F5KFF (F6GPX), "Textes de Réglementation", compendium of the texts with consolidated versions | "version juin 2026" | http://f6kgl.f5kff.free.fr/Textes.htm | `c2772722d3e35127edb25deaa150cd9e50f5dd25512aa32060b4c3492abf8235` | fr — **[secondary]**, used for full L1 text (Art. 7, 7-2, Annex II), TNRBF 2026 notes, and as evidence that A0+A2+A1 is still the current set as of June 2026 |
| C1 | CEPT ECC Recommendation T/R 61-01 "CEPT Radio Amateur Licence" | Edition 16 Feb 2024 (PDF dated 29 Oct 2024) | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| C2 | CEPT ECO implementation tables for T/R 61-01 (doc 925), T/R 61-02 (926), ECC/REC/(05)06 (1024), ECC/DEC/(25)01 (28651) | fetched 2026-10-08 | https://docdb.cept.org/implementation/925 (etc.) | — | en |
| C3 | ECC Decision (25)01 "… technical and operational measures for the use of the frequency band 1258-1300 MHz by the amateur and amateur-satellite services in order to protect the RNSS (space-to-Earth)" | 27 Jun 2025 | https://docdb.cept.org/download/4810 | `03b8a640cb40e0e2b766f456b0f909282aecb5b850a8f06a059d027cbbad5203` | en |
| R1 | REF Commission HF, "PLAN DES BANDES HF IARU Région 1" (7 pp.) | "Applicable au 01/06/2016 — M.à.j : allocation bande 60m suite WRC-2015"; PDF title "MàJ 2021", created 2 Jun 2021 | http://hf.r-e-f.org/planhf/plan_des_bandes_hf.pdf | `3b862c86335e1e829f1cad951955cfa41715da11c461878876367348bbdf78ab` | fr |
| R2 | REF Commission THF, per-band plan pages "PLAN DE LA BANDE IARU RÉGION 1 …" for 50, 70, 144, 432, 1296, 2300, 5760, 10368 MHz | each "m.à.j. F6ETI" 09/11/2017 (50), 28/11/2017 (70, 144, 432, 1296, 5.7G, 10G), 29/11/2017 (2.3G) | http://thf.r-e-f.org/plans_des_bandes/{50,70,144,432,1296,2_3g,5_7g,10g}.htm | see note ¹ below the table | fr |
| R3 | REF Commission THF, "Introduction à la publication de la mise à jour des plans des bandes THF — VARNA 2014" (3 pp.) | Feb 2015 | http://thf.r-e-f.org/docs/Plans%20des%20bandes%20THF_v2a.pdf | `a5c079c0357e83b3aa25b3636f7f1b97bc64002d3be4e4dbc1d490d20794ed50` | fr |

¹ Full SHA-256 of the R2 pages: 50.htm `0435f7531dbaed0eae5261469117e8acaa3bde26a13f2a4940300fd59ed0a886`, 70.htm `14c30baa5004bdba89db7045e052273e9221d28b7058b0c599b3e9fef7c371fe`, 144.htm `89acdd5bb3d1b909940c4df0560cd9118fb341f0b59be9883b19fc6b463e3d7b`, 432.htm `27921b5bedfa295f78d8422538d198c038948a7e6c1ad033b0aa94830cd65648`, 1296.htm `94634dbc6c4bfe1bd9942827835692cad7f43c505ecdbcc35651f26d4b02e9fa`, 2_3g.htm `2ab639bf9b26a06a45d715a938fc8dc971481db2f1b219fdb1bb5368114ac4b2`, 5_7g.htm `e9ec02d0b488fd8e1abd673a1ae256326628621d85d4d9207a1b7f9c0b89ddd4`, 10g.htm `708f8d6adb89ce02979305d2cec97e8a714597ce74b01a5a5202e2594de723e5`.

Not obtainable: the ANFR site (anfr.fr) rejected every scripted request
("Demande rejetée"), including the consolidated TNRBF PDF
(`TNRBF_2026-05-26.pdf`); its amateur notes were read only via [K1].

## 1. Regulator and legal instruments

- **ARCEP** (Autorité de régulation des communications électroniques, des
  postes et de la distribution de la presse) sets the conditions of use of the
  amateur bands: decision **2012-1241** of 2 Oct 2012 [A0], amended by
  **2013-1515** of 17 Dec 2013 [A2] and **2019-1412** of 24 Sep 2019 [A1]
  (60 m). Each is homologated by ministerial arrêté and published in the JORF;
  A1 was published JORF 13 Feb 2020 [K1]. A1 replaces paragraphs "1. Stations
  radioélectriques du service d'amateur" and "2. Stations radioélectriques du
  service d'amateur par satellite" of A0's annex **in full**, so the current
  table is A1 pp.3-9; paragraph "3. Conditions communes" (bandwidth and class 3
  emission limits) is still A0 p.14.
- **Ministry (DGE)** sets certificates and callsigns: arrêté du 21 septembre
  2000 modifié (amended 30 Jan 2009, 23 Apr 2012, 2 Mar 2021) [L1].
- **ANFR** runs the exams, issues/withdraws callsigns (since décret 2014-1621,
  [K1]) and publishes the directory; stations above **5 W PAR (ERP)** must be
  declared to ANFR (L1 Art. 7, as amended 2021; A0 §5.2 p.8).
- **TNRBF** (national allocation table): current version by **arrêté du 26 mai
  2026** (NOR PRMX2611443A) [K1]. Its note **F53b (ADD)** limits amateur and
  amateur-satellite use of **1258-1300 MHz from 27 June 2028** to ECC/DEC/(25)01
  Annex 1 (see 3.1). CEPT lists France as "implemented 26-05-2026 … via note
  F53b" [C2].
- Status as of 2026-10-08: [K1] (June 2026) lists 2012-1241 + 13-1515 + 19-1412
  as the current ARCEP set; no later ARCEP amateur decision was found by search
  of arcep.fr. No class reform is in force or (as far as found) in formal
  consultation. **Pending:** ARCEP has not yet amended 2012-1241 for the 23 cm
  change; the TNRBF note F53b binds from 27 June 2028.

## 2. Licence classes

Since the arrêté of 23 April 2012 there is **one** exam and one certificate,
equivalent to HAREC and to the former class 2; holders of older certificates
keep their class (L1 Art. 3; C1 p.5 note 7: "In France from 23 April 2012 there
is only one licence class "HAREC". Old licence class 1 and 2 holder keep the
benefit of their class and their personal call sign."). The ARCEP table [A1]
distinguishes only "classe 3" from "les classes … autres que la classe 3", so
the old class 1 and class 2 have identical frequency and power rights today.

| class id | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `harec` | "certificat d'opérateur des services d'amateur" (= HAREC; also covers ex-classe 1 and ex-classe 2 holders) | HAREC (T/R 61-02) | T/R 61-01 CEPT licence: "HAREC, class1 and class 2" [C1 p.5] | F1 (ex-2), F2/F3/F5/F6/F8/F9 (ex-1), F4 (HAREC or ex-2); overseas F*digit*; Corsica TK |
| `classe3` | "classe 3" (legacy novice; no longer issued — L1 Art. 5 only preserves the old regulation-exam credit) | below HAREC, national only | **none**: not listed in T/R 61-01; France "not implemented / see remarks — Not enough demand" for ECC/REC/(05)06 [C2] | F0 (TK0 in Corsica) |

## 3. Permitted bands and power, per class

Reference for every watt figure (A1 p.6 note (1), quoted below): **peak
envelope power at the transmitter output** (RR 1.157), **except** 135.7-137.8
kHz, 472-479 kHz and 5351.5-5366.5 kHz, where the figure is **EIRP**. No dBW
figures are used. The table's power column is a merged cell: 1 W covers the
two LF/MF rows; 500 W covers 1800-4000 kHz (A1 p.3) and 7000-24990 kHz (A1
p.4); 15 W covers 5351.5-5366.5 kHz only; 250 W covers 28-29.7 MHz only; 120 W
covers every row from 50 MHz to 250 GHz (A1 p.4-5; checked on the rendered
page — the cell has no lower border before the end of the table).

Region columns: "R1" = metropolitan France, Corsica, Réunion, Mayotte. "R2" =
Guadeloupe, Martinique, Guyane, Saint-Pierre-et-Miquelon, Saint-Barthélemy,
Saint-Martin. Status letters as in A1: (A) primary; (B) primary shared on equal
rights (RR 4.8); (C) secondary; (D) secondary with national primary status;
"NA" = Non attribuée.

| lo Hz | hi Hz | band | status R1 / R2 | harec | classe3 | notes | source |
|---|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | C / C | 1 W EIRP | — | | A1 p.3 |
| 472 000 | 479 000 | 630 m | C / C | 1 W EIRP | — | | A1 p.3 |
| 1 800 000 | 1 810 000 | 160 m | NA / A | 500 W PEP | — | **R2 territories only** | A1 p.3 |
| 1 810 000 | 1 850 000 | 160 m | A / A | 500 W PEP | — | | A1 p.3 |
| 1 850 000 | 2 000 000 | 160 m | NA / B | 500 W PEP | — | **R2 only** | A1 p.3 |
| 3 500 000 | 3 750 000 | 80 m | B / A | 500 W PEP | — | | A1 p.3 |
| 3 750 000 | 3 800 000 | 80 m | B / B | 500 W PEP | — | | A1 p.3 |
| 3 800 000 | 4 000 000 | 80 m | NA / B | 500 W PEP | — | **R2 only** | A1 p.3 |
| 5 351 500 | 5 366 500 | 60 m | C / C | 15 W EIRP | — | WRC-15 band, no other 60 m segments | A1 p.3 |
| 7 000 000 | 7 100 000 | 40 m | A / A | 500 W PEP | — | also amateur-sat (a) | A1 p.4 |
| 7 100 000 | 7 200 000 | 40 m | A / A | 500 W PEP | — | | A1 p.4 |
| 7 200 000 | 7 300 000 | 40 m | NA / A | 500 W PEP | — | **R2 only** | A1 p.4 |
| 10 100 000 | 10 150 000 | 30 m | C / C | 500 W PEP | — | | A1 p.4 |
| 14 000 000 | 14 250 000 | 20 m | A / A | 500 W PEP | — | also amateur-sat | A1 p.4 |
| 14 250 000 | 14 350 000 | 20 m | A / A | 500 W PEP | — | | A1 p.4 |
| 18 068 000 | 18 168 000 | 17 m | A / A | 500 W PEP | — | also amateur-sat | A1 p.4 |
| 21 000 000 | 21 450 000 | 15 m | A / A | 500 W PEP | — | also amateur-sat | A1 p.4 |
| 24 890 000 | 24 990 000 | 12 m | A / A | 500 W PEP | — | also amateur-sat | A1 p.4 |
| 28 000 000 | 29 700 000 | 10 m | A / A | 250 W PEP | — | also amateur-sat | A1 p.4 |
| 50 000 000 | 52 000 000 | 6 m | C / A | 120 W PEP | — | | A1 p.4 |
| 52 000 000 | 54 000 000 | 6 m | NA / A | 120 W PEP | — | **R2 only** | A1 p.4 |
| 144 000 000 | 146 000 000 | 2 m | A / A | 120 W PEP | 10 W PEP | also amateur-sat (both classes) | A1 p.4, p.6 |
| 146 000 000 | 148 000 000 | 2 m | NA / A | 120 W PEP | — | **R2 only** | A1 p.4 |
| 220 000 000 | 225 000 000 | 1.25 m | NA / B | 120 W PEP | — | **R2 only** | A1 p.4 |
| 430 000 000 | 434 000 000 | 70 cm | C / C | 120 W PEP | — | | A1 p.4 |
| 434 000 000 | 440 000 000 | 70 cm | B / C | 120 W PEP | — | amateur-sat 435-438 (R1+R2), 438-440 (R2, Earth→space) | A1 p.4, p.7 |
| 1 240 000 000 | 1 300 000 000 | 23 cm | C / C | 120 W PEP | — | amateur-sat over whole band; **ECC/DEC/(25)01 limits from 27 Jun 2028** (3.1) | A1 p.4, p.8 |
| 2 300 000 000 | 2 450 000 000 | 13 cm | C / C | 120 W PEP | — | amateur-sat 2400-2415, 2415-2450 | A1 p.5, p.8 |
| 3 300 000 000 | 3 500 000 000 | 9 cm | NA / C | 120 W PEP | — | **R2 only** (amateur-sat 3400-3500 R2 only) | A1 p.5, p.8 |
| 5 650 000 000 | 5 850 000 000 | 6 cm | C / C | 120 W PEP | — | amateur-sat 5650-5725 Earth→space, 5830-5850 space→Earth | A1 p.5, p.8 |
| 5 850 000 000 | 5 925 000 000 | 6 cm | NA / C | 120 W PEP | — | **R2 only** | A1 p.5 |
| 10 000 000 000 | 10 450 000 000 | 3 cm | C / C | 120 W PEP | — | | A1 p.5 |
| 10 450 000 000 | 10 500 000 000 | 3 cm | D / D | 120 W PEP | — | amateur-sat (d) | A1 p.5, p.8 |
| 24 000 000 000 | 24 050 000 000 | 1.2 cm | A / A | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 24 050 000 000 | 24 250 000 000 | 1.2 cm | C / C | 120 W PEP | — | | A1 p.5 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | A / A | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 76 000 000 000 | 77 500 000 000 | 4 mm | C / C | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 77 500 000 000 | 78 000 000 000 | 4 mm | A / A | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 78 000 000 000 | 81 500 000 000 | 4 mm | C / C | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | C / C | 120 W PEP | — | | A1 p.5 |
| 134 000 000 000 | 136 000 000 000 | 2 mm | A / A | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 136 000 000 000 | 141 000 000 000 | 2 mm | C / C | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 241 000 000 000 | 248 000 000 000 | 1.2 mm | C / C | 120 W PEP | — | also amateur-sat | A1 p.5 |
| 248 000 000 000 | 250 000 000 000 | 1.2 mm | A / A | 120 W PEP | — | also amateur-sat | A1 p.5 |

Original wording (A1, quoted exactly; translations mine):

- Table heading, amateur service, A1 p.3: « Pour les classes de certificat
  d'opérateur autres que la classe 3 » — "For operator certificate classes
  other than class 3". Column: « Puissance en crête maximale (1) » — "maximum
  peak power (1)". Values printed: « 1 W », « 500 W », « 15 W », « 500 W »,
  « 250 W », « 120 W ».
- A1 p.6: « Pour la classe de certificat d'opérateur 3 … MHz 144,000 à
  146,000 (A) (A) 10 W » — "For operator certificate class 3: 144-146 MHz,
  primary in R1 and R2, 10 W".
- Note (1), A1 p.6: « Puissance en crête maximale à la sortie de l'émetteur,
  tel que défini dans l'article 1.157 du règlement des radiocommunications,
  sauf pour les bandes 135,7-137,8 kHz et 472,0-479,0 kHz et 5351,5-5366,5 kHz
  où la valeur précisée correspond à la puissance isotrope rayonnée
  équivalente maximale (notes 5.67 A, 5.80A et 5.133B du règlement des
  radiocommunications). » — "Maximum peak [envelope] power at the transmitter
  output, as defined in RR 1.157, except for the bands 135.7-137.8 kHz,
  472.0-479.0 kHz and 5351.5-5366.5 kHz, where the value given is the maximum
  equivalent isotropically radiated power (RR 5.67A, 5.80A, 5.133B)."
- A1 p.2 (recital): « la bande 5351,5 - 5366,5 kHz est attribuée aux stations
  radioélectriques du service d'amateur en Régions 1 et 2 à titre secondaire
  avec une puissance rayonnée maximale de 15 W (PIRE) » — "5351.5-5366.5 kHz
  is allocated to amateur stations in Regions 1 and 2 on a secondary basis
  with a maximum radiated power of 15 W (EIRP)."
- (C), A1 p.6: « Attribution à titre secondaire … Les stations
  radioélectriques du service d'amateur ne doivent pas causer de brouillage
  préjudiciable aux stations d'un service primaire et ne peuvent pas prétendre
  à la protection … » — secondary: must not cause harmful interference to, and
  cannot claim protection from, primary services.
- A1 p.7 (end of amateur table): « L'utilisateur d'une station … s'assure
  préalablement que ses émissions ne brouilleront pas des émissions déjà en
  cours d'autres utilisateurs radioamateurs. Il ne doit pas utiliser la même
  fréquence en permanence. Il doit disposer d'un indicateur de puissance. » —
  "The user … checks beforehand that his emissions will not interfere with
  other amateurs' transmissions already in progress. He must not use the same
  frequency permanently. He must have a power indicator."

### 3.1 Per-band exceptions

- **Occupied bandwidth (all classes), A0 §3 p.14** (not replaced by A2/A1): « La
  largeur de bande occupée ne doit pas dépasser 6 kHz pour les fréquences
  inférieures à 28 MHz, 12 kHz pour les fréquences comprises entre 28 et
  144 MHz et 20 kHz pour les fréquences comprises entre 144 et 225 MHz. » —
  "Occupied bandwidth must not exceed **6 kHz below 28 MHz**, **12 kHz from 28
  to 144 MHz** and **20 kHz from 144 to 225 MHz**." No bandwidth limit is
  stated above 225 MHz. [derived] the 144 MHz boundary is ambiguous (in both
  ranges); 2 m is 20 kHz per the plain reading "entre 144 et 225 MHz".
- **Class 3 emission classes, A0 §3 p.14**: « Le titulaire d'un certificat
  d'opérateur de classe 3 est autorisé à utiliser uniquement les classes
  d'émissions A1A, A2A, A3E, G3E, J3E et F3E. » — "A class 3 holder may use
  only emission classes A1A, A2A, A3E, G3E, J3E and F3E." [derived] So no
  data/digital modes (F1D/F2D/J2D/G1D, i.e. FT8, packet, APRS, DMR/D-STAR/C4FM
  digital voice which is F7W/F1E) and no ATV for `classe3`; analogue FM, SSB,
  AM and CW only.
- **60 m**: single WRC-15 band 5351.5-5366.5 kHz, 15 W **EIRP**, secondary
  (A1 p.3). There are no other 60 m channels in France. Bandwidth ≤ 6 kHz (A0 §3).
- **70 MHz (4 m)**: **not allocated** — no row in A1; REF R2 70.htm: « STATUT
  DE LA BANDE: bande non encore ouverte en France » (2017). Refuse.
- **2300-2450 MHz**: whole range permitted at 120 W PEP (secondary), class
  `harec` only. There is no 2310/2350/2390 gap as in the UK.
- **23 cm, pending (binding from 27 June 2028)**: TNRBF note F53b [K1]: «
  Utilisation des attributions ama et amt pour Arcep en R1 et R2, HCR en R3
  dans la bande de fréquences 1258-1300 MHz limitée à compter du 27 juin 2028
  selon les conditions définies dans l'annexe 1 de la décision ECC (25) 01 du
  27 juin 2025. » — "Use of the amateur and amateur-satellite allocations …
  in 1258-1300 MHz limited from 27 June 2028 according to Annex 1 of ECC
  Decision (25)01." ECC/DEC/(25)01 Annex 1 [C3 p.6], verbatim:
  - narrowband (≤ 150 kHz) amateur: 1258-1296 MHz max **e.i.r.p. −17 dBW**;
    1296-1298 MHz max **transmitter power 17 dBW** (50 W); 1298-1300 MHz max
    transmitter power **22 dBW** (158 W); EME with ≥ 30 dBi antenna ≥ 15°
    elevation: 1298-1300 MHz **27 dBW**;
  - narrowband amateur-satellite uplink: 1260-1262 MHz e.i.r.p. −3 dBW (θ <
    15°), 17 dBW (15°-55°), 26.8 dBW (55°-90°); 1262-1270 MHz −17 dBW;
  - broadband (> 150 kHz, incl. ATV): 1258-1300 MHz **−17 dBW/1 MHz e.i.r.p.**;
  - footnote 2: "maximum power means either peak envelope power or carrier
    power (as appropriate) delivered by the transmitter to the amateur station
    antenna". [derived] Until ARCEP amends A1, 120 W PEP stays the general cap;
    after 27 Jun 2028 the lower of the two applies. 1240-1258 MHz is unaffected.
- **Station declaration**: stations above 5 W ERP (PAR) must be declared to
  ANFR within two months (A0 §5.2 p.8; L1 Art. 7). Not a power limit.
- **Region 2 territories** gain 1800-1810, 1850-2000, 3800-4000, 7200-7300 kHz,
  52-54, 146-148, 220-225, 3300-3500, 5850-5925 MHz (rows marked "R2 only").
  The guard needs an "overseas R2 territory" setting to unlock them; default
  (metropolitan) must refuse.
- **Antenna gain**: no gain rule in A0/A1 (power is transmitter output except
  the three EIRP bands). Antenna siting rules (urbanisme, patrimoine) exist but
  are not radio limits.
- **Airborne**: A0 §5.3 p.9 only reminds that aviation authorisations are
  needed; no airborne power figure.
- **Mobile/portable**: no separate power limit; suffixes /P, /M, /MM (L1 Art. 7).
- **Logbook**: compulsory (A0 Art. 6 p.10): date, time, callsigns, frequency,
  emission class, location; kept ≥ 1 year. Identification at start/end, every
  15 min, and on frequency change (A0 Art. 4 p.10).

### 3.2 Gaps: not permitted for any class

Metropolitan France / R1 territories (everything not in the table is refused):
137.8-472 kHz; 479-1810 kHz; 1850-3500 kHz; 3800-5351.5 kHz; 5366.5-7000 kHz;
7200-10100 kHz; 10150-14000 kHz; 14350-18068 kHz; 18168-21000 kHz;
21450-24890 kHz; 24990-28000 kHz; 29.7-50 MHz; **52-144 MHz (no 70 MHz)**;
146-430 MHz; 440-1240 MHz; 1300-2300 MHz; **2450-5650 MHz (no 3.4 GHz in
R1)**; 5850-10000 MHz; 10.5-24.0 GHz; 24.25-47 GHz; 47.2-76 GHz;
81.5-122.25 GHz; 123-134 GHz; 141-241 GHz; above 250 GHz.

R2 territories: as above minus the R2-only rows (1800-1810, 1850-2000,
3800-4000, 7200-7300 kHz, 52-54, 146-148, 220-225, 3300-3500, 5850-5925 MHz).

## 4. Satellite / QO-100

- `harec`: amateur-satellite allocations (A1 p.7-8): 7000-7100, 14000-14250,
  18068-18168, 21000-21450, 24890-24990 kHz (500 W); 28-29.7 MHz (250 W);
  144-146, 435-438, 438-440 (R2 only, « Terre vers espace »), 1240-1300,
  **2400-2415** (C in R1 and R2), **2415-2450**, 3400-3500 (R2 only),
  5650-5725 (« Terre vers espace »), 5830-5850 (« Espace vers Terre »),
  10.45-10.50 GHz (d), 24-24.05, 47-47.2, 76-81.5, 134-141, 241-250 GHz (120 W
  for all ≥ 50 MHz). Same note (1): PEP at transmitter output (A1 p.9 note
  (1) for the satellite table has **no** EIRP exception).
- **QO-100 uplink (2400.05-2400.3 NB, 2401.5-2409.5 MHz WB)**: permitted for
  `harec` with no extra permission, within the 2400-2415 MHz amateur-satellite
  row (secondary) at **120 W PEP transmitter output**. (A2 introduced 2400-2415
  for R1 only; A1 p.8 now shows « 2400,000 à 2415,000 (c) (c) ».)
- **10.45-10.50 GHz** (QO-100 downlink 10489.5-10499.75 MHz): amateur-satellite
  (d) — secondary with national primary status (A1 p.8-9).
- `classe3`: satellite only on 144-146 MHz at 10 W PEP (A1 p.9). No QO-100.
- Note A0 §4 p.7: operating a **space station** additionally needs the
  minister's authorisation under CPCE L.97-2 (not relevant to ground stations).

## 5. CEPT / visiting operators

- T/R 61-01: France "implemented 01-09-2009 — Arrêté du 21/09/2000 modifié par
  l'Arrêté du 02/03/2021" [C2]. National licences equivalent to the CEPT
  licence: "HAREC, class1 and class 2" (C1 p.5, same entry for TK, FG, FY, FM,
  FJ, FP, FS, FR, FH, FT, FO, FK, FW). `classe3` gives no CEPT rights.
- T/R 61-02 (HAREC): implemented 01-09-2009 [C2]; L1 Art. 3 makes the current
  certificate HAREC.
- ECC/REC/(05)06 (CEPT Novice): France "**not implemented** / see remarks —
  Not enough demand", updated 29-04-2025 [C2]. A visiting CEPT Novice holder
  gets nothing.
- Visitor rights (L1 Art. 7-2, via [K1]): stays < 3 months: own call preceded
  by F (plus sub-location letter where needed) and a slash, e.g. « F/HB9xy »;
  stays > 3 months: temporary French call **F#Vxy** (EU nationals) or
  **F#Wxy** (reciprocity countries). [derived] A CEPT visitor operates with the
  `harec` rights in the table above.

## 6. Callsigns

L1 Annex II (digit meanings confirmed on Legifrance; layout via [K1]):
prefix **F** (Corsica **TK**), optional sub-location letter, one digit = class
of the certificate, suffix of 2-3 letters (metropolitan: 3 or 4 for new issues).

| digit | meaning (L1 Annex II) |
|---|---|
| 0 | ex classe 3 → `classe3` |
| 1 | ex classe 2 → `harec` |
| 2, 3, 5, 6, 8, 9 | ex classe 1 → `harec` |
| 4 | classe HAREC ou ex classe 2 → `harec` |
| 7 | réserve |

Sub-location letters: G Guadeloupe, H Mayotte, J Saint-Barthélemy, K New
Caledonia, M Martinique, O French Polynesia & Clipperton, P
Saint-Pierre-et-Miquelon, R Réunion, S Saint-Martin, T TAAF, W Wallis-et-Futuna,
X French satellites, Y Guyane. Suffix series: K.. radio-clubs (F#Kxx metro;
F#Kx overseas/Corsica), Z.. repeaters (F#Zxx), V../W.. foreigners, X../Y..
reserve. Special event: TM (metro), TO (DOM), TK (Corsica), TX (COM), digits
0-999 + 1-4 char suffix. Portable/mobile/maritime: « /P, /M ou /MM » (L1 Art. 7).

Regex hints (class *hints* only):
- `classe3`: `^(F|TK|F[GHJKMOPRSTWY])0[A-Z]{2,4}$`
- `harec`: `^(F|TK|F[GHJKMOPRSTWY])[1-689][A-Z]{2,4}$`
- club/repeater/special: `^F[0-9]K[A-Z]{1,2}$`, `^F[0-9]Z[A-Z]{2}$`,
  `^(TM|TO|TK|TX)[0-9]{1,3}[A-Z0-9]{0,3}[A-Z]$` — operator class unknown.

## 7. National band plan

The REF (Réseau des Émetteurs Français) publishes French translations of the
IARU R1 plans with French additions: HF [R1] (2016 plan, updated 2021 for
60 m — **older than the 2020 Novi Sad IARU R1 HF plan**), VHF/UHF/SHF [R2]
(Landshut 2017 / VHF Handbook 8.01, last updated Nov 2017). French-specific
usages are printed in italics on the R2 pages. Satellite and beacon sub-bands
below are the ones the guard should refuse.

HF [R1] (max bandwidth in Hz as printed):

| band | lo-hi kHz | usage | max BW |
|---|---|---|---|
| 136 k | 135.7-137.8 | CW, QRSS, narrow digimodes | 200 |
| 630 m | 472-475 / 475-479 | CW / CW + narrow digimodes | 200 / ND |
| 160 m | 1810-1838 | CW (1836 QRP) | 200 |
| | 1838-1840 | narrow modes | 500 |
| | 1840-1843 / 1843-1850 | all modes | 2700 |
| 80 m | 3500-3570 | CW (3500-3510 intercontinental priority; 3510-3560 CW contest) | 200 |
| | 3570-3600 | narrow / digimodes (3590-3600 automatic) | 200/500 |
| | 3600-3800 | all modes (3630 digital voice, 3690 QRP, 3735 image, 3760 emergency, 3775-3800 intercontinental priority) | 2700 |
| 60 m | 5351.5-5354.0 | CW, narrow | 200 |
| | 5354.0-5366.0 | all modes, USB | 2700 |
| | 5366.0-5366.5 | weak-signal narrow | 20 |
| 40 m | 7000-7040 | CW (7030 QRP) | 200 |
| | 7040-7050 | narrow, digimodes (7047-7050 automatic) | 500 |
| | 7050-7200 | all modes (7070 DV, 7090 QRP, 7110 emergency, 7165 image, 7175-7200 intercontinental) | 2700 |
| 30 m | 10100-10130 | CW (10116 QRP) | 200 |
| | 10130-10150 | narrow digimodes; **no telephony** | 500 |
| 20 m | 14000-14070 | CW | 200 |
| | 14070-14099 | narrow digimodes | 500 |
| | **14099-14101** | **IBP beacons, exclusive** | — |
| | 14101-14350 | all modes (14130 DV, 14190-14200 DX-peditions, 14230 image, 14285 QRP, 14300 emergency) | 2700 |
| 17 m | 18068-18095 / 18095-18109 | CW / narrow | 200/500 |
| | **18109-18111** | **IBP beacons** | — |
| | 18111-18168 | all modes (18160 emergency) | 2700 |
| 15 m | 21000-21070 / 21070-21110 | CW / narrow | 200/500 |
| | 21110-21120 | all modes except SSB | 2700 |
| | 21120-21149 | narrow | 500 |
| | **21149-21151** | **IBP beacons** | — |
| | 21151-21450 | all modes (21360 emergency) | 2700 |
| 12 m | 24890-24915 / 24915-24929 | CW / narrow | 200/500 |
| | **24929-24931** | **IBP beacons** | — |
| | 24931-24990 | all modes | 2700 |
| 10 m | 28000-28070 / 28070-28190 | CW / narrow | 200/500 |
| | 28190-28199, **28199-28201 (IBP)**, 28201-28225 | beacons | — |
| | 28225-29000 | all modes (beacons to 28300) | 2700 |
| | 29000-29100 / 29100-29200 / 29200-29300 | all modes 6 kHz / FM simplex 10 kHz / automatic | 6000 |
| | **29300-29510** | **satellite downlink** (do not transmit) | — |
| | 29510-29520 | guard | — |
| | 29520-29590 | FM repeater inputs RH1-RH8 | 6000 |
| | 29600 / 29610 | FM calling / simplex parrot | 6000 |
| | 29620-29700 | FM repeater outputs RH1-RH8 (input 100 kHz below) | 6000 |

VHF/UHF/SHF [R2]:

- **6 m** (France 50-52 MHz): 50.000-50.100 CW (50.000-50.030 reserved for
  synchronised beacon project), 50.100-50.130 intercontinental, 50.130-50.300
  SSB/CW (50.150 calling), 50.300-50.400 MGM/narrow (50.310-50.320 EME,
  50.320-50.380 MS), **50.400-50.500 beacons exclusive** (1 kHz), 50.500-52.000
  all modes 12 kHz (50.510 SSTV, 50.540-50.580 FM internet gateways, 50.620-
  50.750 digital, 51.510 FM calling); repeaters: inputs 51.210-51.390, outputs
  51.810-51.990 MHz, 20 kHz spacing — **input 600 kHz below output**.
- **4 m**: no French allocation (plan page exists for IARU R1 only).
- **2 m**: **144.000-144.025 satellite downlink only** (no ground TX below
  144.025); 144.025-144.110 CW exclusive (144.050 CW centre; French: 144.037 and
  144.082 CW emergency); 144.110-144.150 CW/MGM (EME MGM 144.110-144.160);
  144.150-144.400 CW/SSB/MGM (144.300 SSB centre); **144.400-144.490 beacons
  exclusive**; 144.491-144.493 experimental MGM; 144.500-144.794 all modes 20
  kHz (144.500 image; French: linear transponders C1 144.505-144.520, C2
  144.530-144.545, C3 144.555-144.570, C4 144.580-144.595; 144.600 data; French:
  144.650 balloons; 144.750 ATV talkback; French: 144.7875 ATV repeater
  remote control; 144.800 APRS); 144.794-144.990 MGM/digital 12 kHz (internet
  DV gateways 144.8125-144.8825); **repeater inputs 144.975-145.194** (12 kHz);
  145.194-145.206 space communications; 145.206-145.594 FM/DV simplex (145.375
  DV calling; French: 145.450/145.4625/145.475 emergency; 145.500 FM calling);
  **repeater outputs 145.575-145.7935** — R1 standard, **input 600 kHz below
  output**; 145.794-145.806 space comms; **145.806-146.000 satellite exclusive**.
- **70 cm**: 430.025-430.375 **French repeater outputs** (F/PA/ON system, 12.5
  kHz, shift 1.6 MHz) with **inputs 431.625-431.975** — **input 1.6 MHz above
  output**; 430.400-430.575 digital links / F digital repeater inputs, paired
  with 439.800-439.975 outputs (**shift 9.4 MHz, input below output**, REF note
  2.6.2); 430.600-430.925 digital repeaters; 430.925-431.025 multimode;
  431.050-431.825 HB/DL/OE inputs (7.6 MHz, not French usage); 432.000-432.025
  EME CW; 432.025-432.100 CW exclusive (432.050 centre); 432.100-432.400
  SSB/CW/MGM (432.200 SSB centre, 432.350 microwave talkback, 432.370 FSK441);
  **432.400-432.490 beacons exclusive**; 432.500 APRS; 432.525 French emergency;
  432.600-432.975 R1 repeater inputs (2 MHz shift, 25 kHz) [not the French
  system]; **433.000-433.375 R1 repeater inputs**, outputs **434.600-434.975**
  (**shift 1.6 MHz, input below output**); 433.400-433.575 FM/DV simplex (433.450
  DV calling, 433.500 FM mobile calling); 433.625-433.775 digital (French note
  2.6.1: only after local agreement); 434.000 wideband digital experiments;
  **435.000-438.000 amateur-satellite** (ATV simplex tolerated under R1 Varna
  conditions; **no ATV/voice repeater outputs** in 435-438); 438.025-438.525
  digital (French note 2.6.1); 438.550-438.625 multimode; 438.650-439.425
  HB/DL/OE outputs; 439.800-439.975 French digital repeater outputs.
- **23 cm**: 1240.000-1240.750 alternative narrowband (reserved); 1240-1241
  digital (French packet duplex, shift 59 MHz); French repeaters: outputs
  **1242.025-1242.700 (RS1-RS28)** with inputs **1270.025-1270.700** — **input
  28 MHz above output**; outputs 1258.150-1259.350 (R20-R68) with inputs
  1293.150-1294.350 — **input 35 MHz above output** [derived from channel
  edges]; RM0-RM19 inputs 1291.000-1291.475 / outputs 1297.000-1297.475 —
  **input 6 MHz below output**; 1243.25-1258 and 1272-1291 ATV/DATV;
  **1260-1270 satellite service**; 1296.000-1296.025 EME; 1296.025-1296.150
  CW/MGM; 1296.150-1296.800 CW/SSB/MGM (1296.200 centre, 1296.400-1296.600
  transponder inputs, 1296.500 image, 1296.600 narrow data, 1296.600-1296.700
  transponder outputs, 1296.750-1296.800 local beacons 10 W ERP max); **1296.800-
  1296.994 beacons exclusive**; 1297.500-1297.975 FM simplex SM20-SM39 (1297.500
  FM centre, 1297.725 DV calling); 1298.025-1298.975 all modes RS1-RS39;
  1299.000-1299.750 five 150 kHz high-speed data channels; 1299.750-1300.000 eight
  25 kHz FM/DV channels. **Will need re-planning for ECC/DEC/(25)01 by 2028.**
- **13 cm**: 2300-2320 national/sub-regional (2304-2306, 2308-2310 alternative
  narrowband); 2320.000-2320.025 EME; 2320.025-2320.150 CW; 2320.150-2320.800
  CW/SSB (2320.200 centre; 2320.750-2320.800 local beacons 10 W ERP);
  **2320.800-2321.000 beacons exclusive**; 2321-2322 FM/DV simplex and repeaters;
  2322-2355 ATV; 2355-2365 digital; 2365-2370 repeaters; 2370-2392 ATV;
  2392-2400 digital; **2400-2450 amateur-satellite** (2400-2402 alternative
  narrowband; 2427-2443 ATV if not used by satellites). [derived] QO-100 NB
  2400.050-2400.300 and WB 2401.500-2409.500 MHz lie in the satellite segment.
- **6 cm**: **5650-5668 satellite uplink**; 5668-5670 narrowband (5668.2) and
  satellite uplink; 5670-5700 MGM; 5700-5720 ATV; 5720-5760 all modes;
  5760.000-5760.800 narrowband (5760.200; local beacons 5760.750-5760.800, 10 W
  ERP); **5760.800-5760.990 beacons**; 5762-5790 all modes; **5790-5850 satellite
  downlink**.
- **3 cm**: 10000-10150 MGM; 10150-10250 all modes; 10250-10350 MGM;
  10350-10368 all modes; 10368.000-10368.800 narrowband (10368.200 centre;
  10368.750-10368.800 local beacons 10 W ERP); **10368.800-10368.990 beacons**;
  10369-10450 all modes; 10450-10452 alternative narrowband; **10450-10500
  amateur-satellite**.

Differences from IARU R1:
- HF plan is the **2016** IARU R1 plan (1810-1838 CW, 1838-1840 narrow,
  3570-3600 narrow/digimodes), not the 2020 Novi Sad revision used by RSGB.
- 70 cm French repeater system 430.025-430.375 out / 431.625-431.975 in (input
  above output) and 9.4 MHz digital link pairs; 23 cm French RS/R channel
  systems with 28/35 MHz splits; French emergency and linear-transponder spots
  on 2 m and 70 cm.
- 50-52 MHz only (no 52-54 in metropolitan France); no 70 MHz.
- The REF VHF pages date from 2017 (VHF Handbook 8.01); later IARU changes (VHF
  Handbook 9.x/10.x) are not reflected.

## 8. Confidence and gaps

**Overall: high** for the licence table (current ARCEP text read in full,
power column checked on the rendered page, cross-checked against the 2012 and
2013 versions and against [K1]'s June 2026 consolidation); **medium** for the
band plan (REF pages are 2017/2021 and partly out of step with current IARU R1).

UNCONFIRMED / caveats:
- L1 (arrêté 21 Sep 2000) could not be downloaded from Legifrance (Cloudflare);
  Art. 3, Art. 5 and the Annex II digit table were confirmed on Legifrance via
  WebFetch; Art. 7 (/P /M /MM), Art. 7-2 (visitor callsigns) and the
  sub-location letters are from [K1] only **[secondary]**.
- ANFR pages and the TNRBF 2026 PDF were not reachable; note F53b (23 cm from
  27 Jun 2028) and F48 are from [K1] **[secondary]**, corroborated by CEPT's
  implementation table ("implemented 26-05-2026 … via note F53b") [C2].
- Whether ARCEP will also amend 2012-1241 for 23 cm, and with what figures, is
  unknown. Encode the ECC/DEC/(25)01 limits with an effective date of
  2028-06-27.
- 144 MHz bandwidth boundary (12 kHz vs 20 kHz) is ambiguous in A0 §3; I read 2 m
  as 20 kHz.
- Classe 3 privileges outside 144-146 MHz: none in A1; confirmed.
- TOM (NC, PF, WF, TAAF) rules (arrêté 2 Mar 2021) not transcribed.
- No French class reform proposal was found in force or in consultation as of
  2026-10-08 (searched arcep.fr, ANFR and REF news); ANFR changed its exam
  software in March 2026 only.
