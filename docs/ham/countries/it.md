# Italy (IT): licence limits and band plan

Compiled 2026-10-08 for OpenHamShack HAM / OpenHamShack NB. Input to a later encoding step
(ohsradio/licences/<id>.py, ohsradio/plans/<id>.py); see docs/ham/licence-check.md
for how the UK entry was verified. Licence = law (guard enforces); band plan =
voluntary (guard warns, except beacon/satellite sub-bands, which are refused).

Markers: **[UNCONFIRMED]** = not confirmed from a primary source (say what was
found instead); **[derived]** = worked out here, not stated in a source;
**[secondary]** = from a non-primary source only.

**How Italian law is put together.** Two primary texts: the **PNRF** (national
frequency allocation plan) decides which bands the amateur service has,
primary (UPPER CASE) or secondary (lower case), plus band-specific notes;
**Allegato 26** of the Codice delle comunicazioni elettroniche sets one power
limit for everything — 500 W PEP — "fatte salve" (subject to) any lower limit in
the PNRF. Unlike Spain there is no 50 % rule for secondary bands. Italy's
allocations are notably **narrower** than IARU R1: 70 cm is cut to 430-434 and
435-438 MHz, 23 cm to 1240-1245 and 1270-1298 MHz (+ satellite 1260/1267-1270),
3 cm starts at 10.3 GHz, 6 cm is three slivers, and 24.05-24.25 GHz is absent.

## Sources

Downloaded 2026-10-08 with `curl -L -A 'Mozilla/5.0' --max-time 60` (MIMIT,
ARI) or `curl -k` (CEPT docdb), converted with `pdftotext -layout`; PNRF Table
B p.13 also rendered to PNG to confirm the 2400-2450 MHz rows.

| Key | Document (exact title) | Date / version | URL | SHA-256 (if downloaded) | Language |
|---|---|---|---|---|---|
| A26 | "Allegato n. 26 con sub allegati A, B, C, D, E, F, G, H, I, L (art. 134) — Adeguamento della normativa tecnica relativa all'esercizio dell'attività radioamatoriale", as replaced by DM 1° marzo 2021 (GU Serie generale n. 70, 22 Mar 2021, pp. 34 ff.) — MIMIT's "testo vigente" (30 pp.) | DM 1 Mar 2021; PDF built 12 May 2025 | https://www.mimit.gov.it/images/stories/documenti/allegati/Allegato_n_26_al_CdC_testo_vigente.pdf | `aa44a04565fcd06a37541ee7f0c66c733a7f59f5449ab7e149124d8352c25403` | it |
| CCE | D.Lgs. 1 agosto 2003 n. 259, Codice delle comunicazioni elettroniche, Capo VII "Radioamatori", artt. 134-145 (as rewritten by D.Lgs. 207/2021 and D.Lgs. 48/2024), MIMIT extract "Vigente al: 28-4-2025" | 28 Apr 2025 | https://www.mimit.gov.it/images/stories/documenti/allegati/artt_da_134_a_145_del_CdC.pdf | `b80f837d9adfa1db1085dfe7b4db24eafcfa1bc653cf6cc64ac52aa56d97cf69` | it |
| P0 | Decreto del Ministro dello Sviluppo Economico 31 agosto 2022, approving the PNRF (GU n. 214, 13 Sep 2022, S.O. n. 35; errata GU n. 236, 8 Oct 2022) | 31 Aug 2022 | https://www.mimit.gov.it/images/stories/digitale/Decreto_PNRF_31-08-2022_firmato.pdf | `bca38251b01ee0729f694ce7e5cae37562a6eb31ba6d2d548d2b84738cefccc3` | it |
| PA | PNRF "Tabella di attribuzione" A (0-27.5 MHz), 10 pp. | 2022 | https://www.mimit.gov.it/images/stories/digitale/02-Tabella_A.pdf | `ffa33a0dcabc5a0e9ef23832434de8f187a02a2af7cf7f93c767bc0207f4e7a1` | it |
| PB | PNRF Tabella B (27.5-10 000 MHz), 19 pp. | 2022 | https://www.mimit.gov.it/images/stories/digitale/03-Tabella_B.docx.pdf | `185b1c94d5324e85ce0ab6699c07bf9bb68212b38bdc66c1a850bf313c7c22e5` | it |
| PC | PNRF Tabella C (10-3000 GHz), 20 pp. | 2022 | https://www.mimit.gov.it/images/stories/digitale/04-Tabella_C.pdf | `dc5dcec6129ef6d5cb9961452636fd6ecb79679593b8e8a45d835d10dcae3612` | it |
| PN | PNRF "Note" (explanatory/technical notes), 47 pp. | 2022 | https://www.mimit.gov.it/images/stories/digitale/05-Note.pdf | `f4654ebecbedf4253cc2c11b13bbb5a83d5977114a24300424821135836472e1` | it |
| DMN | "DECRETO 26 gennaio 2026. Criteri generali e modalità per il conseguimento della patente di classe N e delle modalità di assegnazione e gestione dei nominativi a scelta per l'attività radioamatoriale" (GU Serie generale n. 51, 3 Mar 2026, pp. 17-18) | 26 Jan 2026 | https://ispettorati.mise.gov.it/images/ispettorati/Modulistica_DGST/DM_26_gennaio_2026__GU_51_del_332026.pdf | `e7bbf4cecadeb6eb4ba17eaebf2abeeabe0f66f34f1ac69e2575e855464fae1b` | it |
| CONS | MIMIT, "Consultazione pubblica on line sulla predisposizione del decreto recante 'Modifiche all'allegato n. 26 …'" — scheda informativa e quesiti | open 29 May - 30 Jun 2025 | https://www.mimit.gov.it/images/stories/documenti/allegati/scheda_informativa_e_quesiti_Consultazione_pubblica_online_radioamatori_2025.pdf | `0d8bc4b1344032b81e5900b0953035017a709ba2c984f75491439d6940b40ef0` | it |
| SPER | MIMIT DG Servizi Territoriali to ARI, "Rinnovo autorizzazione per sperimentazioni di radiopropagazione nelle bande 40.660-40.700 MHz, 70-70.400 MHz e 1810-1830 KHz. Anno 2026" (prot. U.0187525, 31-07-2026) | signed 31 Jul 2026; valid to 31 Dec 2026 | https://sperimentazioni.ari.it/doc/aut_sperimentazioni_160_40_2026.pdf | `0b00484f2717b3d0363c501ddf843a1ebfa2d49c4143e7a5192d3038d8e46870` | it |
| ARIV | ARI, "Band Plan Italiano VHF – UHF – SHF – EHF", Rev. 0.6 (IV3KKW), based on PNRF 2015 and IARU R1 Landshut 2017 / VHF Handbook 8.01 (15 pp.) | 24 Jan 2018 | https://www.ari.it/images/stories/VHF2018/BandPlanItalianoVUSEHF_v06.pdf (linked from https://www.ari.it/bandplan.html) | `8db5715c28648c5e05e99270ad8be59a7eb24a3d132ddae8baa7092a1a2f99ad` | it |
| ARIH | IARU Region 1 HF Band Plan "Effective from 16 OCT 2020", as hosted by ARI (linked from https://www.ari.it/band-plan-hf-iaru-reg-1.html) | PDF modified 10 Jan 2024 | https://www.ari.it/images/stories/hf/hf_r1_bandplan2020.pdf | `d211e39b9ae1b7191853ec605de9a6c2f954dbc4d9fe907d78f3b9a2cd46a6c6` | en |
| C1 | CEPT T/R 61-01, edition 16 Feb 2024 | PDF 29 Oct 2024 | https://docdb.cept.org/download/4541 | `aa4d7961b29ff57ca96209f23f1bff8e47a0c15f2bb6eba4706ecc69dfe4f691` | en |
| C2 | CEPT ECO implementation tables (T/R 61-01, T/R 61-02, ECC/REC/(05)06, ECC/DEC/(25)01) | fetched 2026-10-08 | https://docdb.cept.org/implementation/925 (etc.) | — | en |
| C3 | ECC Decision (25)01 (1258-1300 MHz) | 27 Jun 2025 | https://docdb.cept.org/download/4810 | `03b8a640cb40e0e2b766f456b0f909282aecb5b850a8f06a059d027cbbad5203` | en |

Not obtained: Gazzetta Ufficiale / Normattiva consolidated texts (MIMIT's
extracts were used instead); no official table of regional callsign digits.

## 1. Regulator and legal instruments

- **Ministero delle Imprese e del Made in Italy (MIMIT)** (ex-MISE),
  Direzione generale per i servizi territoriali; licences issued by the
  Ispettorati territoriali ("Case del made in Italy").
- **Codice delle comunicazioni elettroniche** (D.Lgs. 259/2003, text rewritten
  by D.Lgs. 207/2021 and corrected by D.Lgs. 48/2024), Capo VII artt. 134-145
  [CCE]. Art. 134 c.3: amateur activity « è disciplinata dalle norme di cui al
  presente Capo e dell'allegato n. 26 ».
- **Allegato 26**, as replaced by **DM 1 March 2021** [A26] — Art. 11: amateurs
  may operate « soltanto sulle bande di frequenze attribuite ai predetti
  servizi in Italia dal piano nazionale di ripartizione delle frequenze »;
  Art. 15: power.
- **PNRF** approved by DM 31 Aug 2022 [P0] (replaced DM 5 Oct 2018). Still the
  current edition on MIMIT's page on 2026-10-08.
- **Pending as of 2026-10-08:**
  - **Class N** (CEPT Novice, ECC/REC (05)06): created by D.Lgs. 48/2024 (CCE
    art. 135 b, 136); DM 26 Jan 2026 [DMN] « È recepita la raccomandazione
    CEPT ECC/REC (05)06 » and sets the exam pass mark, but the exam programme,
    and the class's bands and power, are left to a « decreto direttoriale …
    recante modifica all'allegato n. 26 » (DMN Art. 1 c.4) that has **not been
    published**; DMN Art. 4: « Nelle more … continuano ad applicarsi le
    disposizioni vigenti ». MIMIT consulted on the Allegato 26 changes 29 May -
    30 Jun 2025 [CONS] (class N "restrizioni operative di frequenza e potenza",
    callsigns for class N, vanity calls, keeping a call when moving region).
  - **Vanity callsigns** (CCE art. 139 c.2-bis): ≤ 5 characters, €250 one-off
    (DMN Art. 2) — procedure in force; callsign formats not yet published.
  - **New PNRF** incorporating WRC-23 and **ECC/DEC/(25)01** (23 cm): CEPT
    records Italy "planned 07-09-2026 — The implementation is expected to be
    completed by 2027 with the publication of the revised National Table of
    Frequency Allocations (NTFA)" [C2].

## 2. Licence classes

| class id | national name | exam level | CEPT equivalence | callsign prefixes |
|---|---|---|---|---|
| `a` | "autorizzazione generale di classe A" / "patente di operatore di classe A" (the only class issued today; old class B merged into A by DM 21 Jul 2005) | HAREC — patente must read « Harmonized Amateur Examination Certificate - HAREC - level A - CEPT TR 61-02 » (A26 Art. 2 c.2) | T/R 61-01: national licence "A" (C1 p.6, note 9); CCE art. 135 c.3: class A holders get the "attestazione equivalente CEPT T/R 61-01" | I, I + letter (IK, IZ, IU, IW, IV, IN, IX, IS, IT …) + region digit |
| `n` | "classe N" (novizio) | ECC/REC (05)06 / ERC Report 32 | CEPT Novice | **not yet operational — no bands, power or callsign format published [UNCONFIRMED]**; do not offer in the UI until the decreto direttoriale appears |

## 3. Permitted bands and power, per class

Power, A26 Art. 15 (p.4 of the PDF, GU p.37): **500 W PEP**, defined as peak
envelope power fed to the antenna feed line, fixed or mobile/portable, "fatte
salve" lower PNRF limits. The only PNRF amateur power limits found are the three
EIRP limits below. Status: P = RADIOAMATORE (primary), S = Radioamatore
(secondary) in the PNRF table.

| lo Hz | hi Hz | band | status | a | notes | source |
|---|---|---|---|---|---|---|
| 135 700 | 137 800 | 2200 m | S | 1 W EIRP | PNRF note 8 (RR 5.67A); listed as "-Radioamatore" use in the 130-148.5 kHz row | PA p.1 (printed 4); PN p.2 |
| 472 000 | 479 000 | 630 m | S | 1 W EIRP | notes 15, 16 (RR 5.80A) | PA p.2; PN p.2 |
| 1 830 000 | 1 850 000 | 160 m | P | 500 W PEP | **1810-1830 is NOT allocated** (only under SPER, 10 W) | PA p.2 |
| 3 500 000 | 3 800 000 | 80 m | **S** | 500 W PEP | secondary in Italy (FISSO/MOBILE primary) | PA p.4 |
| 5 351 500 | 5 366 500 | 60 m | S | 15 W EIRP | note 32B (RR 5.133B) | PA p.5; PN p.4 |
| 7 000 000 | 7 100 000 | 40 m | P | 500 W PEP | also amateur-sat | PA p.6 |
| 7 100 000 | 7 200 000 | 40 m | P | 500 W PEP | | PA p.6 |
| 10 100 000 | 10 150 000 | 30 m | S | 500 W PEP | | PA p.6-7 |
| 14 000 000 | 14 250 000 | 20 m | P | 500 W PEP | also amateur-sat | PA p.8 |
| 14 250 000 | 14 350 000 | 20 m | P | 500 W PEP | | PA p.8 |
| 18 068 000 | 18 168 000 | 17 m | P | 500 W PEP | also amateur-sat | PA p.8-9 |
| 21 000 000 | 21 450 000 | 15 m | P | 500 W PEP | also amateur-sat | PA p.9 |
| 24 890 000 | 24 990 000 | 12 m | P | 500 W PEP | also amateur-sat | PA p.10 |
| 28 000 000 | 29 700 000 | 10 m | P | 500 W PEP | also amateur-sat | PB p.1 |
| 50 000 000 | 52 000 000 | 6 m | S | 500 W PEP | notes 56, 57 (wind profilers; no protection) | PB p.1; PN p.8 |
| 144 000 000 | 145 800 000 | 2 m | P | 500 W PEP | note 69: « ad uso esclusivo del servizio di radioamatore » | PB p.2; PN p.9 |
| 145 800 000 | 146 000 000 | 2 m | P (sat) | 500 W PEP | note 69: exclusive amateur-**satellite**, « limitatamente ai collegamenti con i satelliti » — satellite QSOs only | PB p.2; PN p.9 |
| 430 000 000 | 432 000 000 | 70 cm | S | 500 W PEP | | PB p.5 |
| 432 000 000 | 434 000 000 | 70 cm | S | 500 W PEP | ISM 433.05-434.79 (notes 100A, 101) | PB p.5 |
| 435 000 000 | 436 000 000 | 70 cm | P (+ sat P) | 500 W PEP | | PB p.5 |
| 436 000 000 | 438 000 000 | 70 cm | S | 500 W PEP | amateur only (no amateur-sat entry in the national row); 436-436.1 telemetry (note 101A) | PB p.6 |
| 1 240 000 000 | 1 245 000 000 | 23 cm | S | 500 W PEP | note 116 | PB p.8 |
| 1 260 000 000 | 1 270 000 000 | 23 cm | sat only | 500 W PEP [derived] | "Radioamatore via satellite" is listed only as a *use* (utilizzazione) of 1260-1270; note 117: « La banda 1.267-1.270 MHz è anche attribuita al servizio di radioamatore via satellite (Terra-spazio) con statuto di servizio secondario » — encode **1267-1270 MHz, Earth→space only** | PB p.8; PN p.19 |
| 1 270 000 000 | 1 298 000 000 | 23 cm | S | 500 W PEP | note 116A; **ECC/DEC/(25)01 not yet applied (planned 2027)** | PB p.8 |
| 2 300 000 000 | 2 400 000 000 | 13 cm | S | 500 W PEP | notes 154-156 | PB p.12-13 |
| 2 400 000 000 | 2 440 000 000 | 13 cm | S | 500 W PEP | **amateur only — no amateur-satellite in this row** (rendered page checked) | PB p.13 (printed 26) |
| 2 440 000 000 | 2 450 000 000 | 13 cm | S (+ sat S) | 500 W PEP | | PB p.13 |
| 5 650 000 000 | 5 670 000 000 | 6 cm | sat S only | 500 W PEP [derived] | "Radioamatore via satellite" only (RR 5.282: Earth→space) — no terrestrial amateur | PB p.16 |
| 5 760 000 000 | 5 770 000 000 | 6 cm | **P** | 500 W PEP | note 193: no protection from foreign FSS earth stations; ISM | PB p.16; PN p.29 |
| 5 830 000 000 | 5 850 000 000 | 6 cm | S (+ sat S, s-T) | 500 W PEP | | PB p.16 |
| 10 300 000 000 | 10 450 000 000 | 3 cm | S | 500 W PEP | **10.000-10.300 GHz NOT allocated** | PC p.1 |
| 10 450 000 000 | 10 500 000 000 | 3 cm | S (+ sat S) | 500 W PEP | | PC p.1 |
| 24 000 000 000 | 24 050 000 000 | 1.2 cm | P (+ sat P) | 500 W PEP | **24.05-24.25 GHz NOT allocated** | PC p.6 |
| 47 000 000 000 | 47 200 000 000 | 6 mm | P (+ sat) | 500 W PEP | | PC p.11 |
| 76 000 000 000 | 77 500 000 000 | 4 mm | S (+ sat) | 500 W PEP | | PC p.14 |
| 77 500 000 000 | 78 000 000 000 | 4 mm | P (+ sat) | 500 W PEP | | PC p.14 |
| 78 000 000 000 | 81 000 000 000 | 4 mm | S (+ sat) | 500 W PEP | | PC p.14 |
| 81 000 000 000 | 81 500 000 000 | 4 mm | S (+ sat) | 500 W PEP | only via note 279 on the 81-84 GHz row (RR 5.561A) | PC p.14; PN p.46 |
| 122 250 000 000 | 123 000 000 000 | 2.5 mm | S | 500 W PEP | ISM | PC p.16 |
| 134 000 000 000 | 136 000 000 000 | 2 mm | P (+ sat) | 500 W PEP | | PC p.17 |
| 136 000 000 000 | 141 000 000 000 | 2 mm | S (+ sat) | 500 W PEP | | PC p.17 |
| 241 000 000 000 | 248 000 000 000 | 1.2 mm | S (+ sat) | 500 W PEP | | PC p.19 |
| 248 000 000 000 | 250 000 000 000 | 1.2 mm | P (+ sat) | 500 W PEP | | PC p.19 |

Temporary experimental bands (SPER, 31 Jul - **31 Dec 2026**, all class-A
holders, logging on ARI's portal within 24 h; guard should refuse unless an
explicit "experimental authorisation" flag is set):

| lo Hz | hi Hz | what | limit | source |
|---|---|---|---|---|
| 1 810 000 | 1 830 000 | 160 m extension | 10 W "potenza massima di trasmissione"; ARI portal: "modi NB e CW" **[secondary]** | SPER |
| 40 660 000 | 40 700 000 | 8 m | 10 W; ARI portal: "max BW 3 kHz" **[secondary]** | SPER |
| 70 100 000, 70 200 000, 70 300 000 (channels) | — | 4 m: **three single channels only, ≤ 25 kHz each** | 10 W | SPER |

Original wording (translations mine):

- A26 Art. 15 (p.4): « Fatte salve eventuali limitazioni delle potenze
  riportate dal Piano nazionale di ripartizione delle frequenze, le stazioni del
  servizio di radioamatore possono operare con le seguenti potenze massime,
  definite come potenza di picco (p.e.p) cioè potenza media fornita alla linea
  di alimentazione dell'antenna durante un ciclo a radiofrequenza, in
  corrispondenza della massima ampiezza dell'inviluppo di modulazione: fisso o
  mobile/portatile 500 W. » — "Subject to any power limits in the PNRF, amateur
  stations may use the following maximum power, defined as peak envelope power,
  i.e. the mean power supplied to the antenna feed line during one RF cycle at
  the crest of the modulation envelope: fixed or mobile/portable 500 W."
- A26 Art. 11 (p.3): « Le stazioni del servizio di radioamatore e del servizio
  di radioamatore via satellite possono operare soltanto sulle bande di
  frequenze attribuite ai predetti servizi in Italia dal piano nazionale di
  ripartizione delle frequenze. » — "only on the bands the PNRF allocates".
- PN note 8: « La banda di frequenze 135,7-137,8 kHz è anche attribuita al
  servizio di radioamatore con statuto di servizio secondario. La massima
  potenza isotropa equivalente irradiata (e.i.r.p.) … non può superare 1 W. »
- PN note 16: « La massima potenza equivalente irradiata (e.i.r.p.) dalle
  stazioni del servizio di radioamatore che impiegano frequenze nella banda
  472-479 kHz non deve eccedere 1W. »
- PN note 32B: « La banda di frequenze 5351,5-5366,5 kHz è anche attribuita al
  servizio di radioamatore con statuto di servizio secondario. Le stazioni …
  non devono superare la massima potenza isotropa equivalente irradiata di 15 W
  (e.i.r.p.) (WRC-15). »
- PN note 69: « La banda di frequenze 144,0-145,8 MHz è ad uso esclusivo del
  servizio di radioamatore. La banda di frequenze 145,8 – 146,0 MHz è ad uso
  esclusivo del servizio di radioamatore via satellite, limitatamente ai
  collegamenti con i satelliti radioamatoriali che operano in accordo alle
  disposizioni dell'ITU. »
- PN note 193: « Nella banda di frequenze 5.760-5.770 MHz l'utilizzazione del
  servizio di radioamatore non gode di protezione nei confronti delle stazioni
  terrene trasmittenti del servizio fisso via satellite (T-s), operanti negli
  altri Paesi … »
- SPER: « potenza massima di trasmissione pari a10 W; limitatamente alla banda
  70-70.400 MHz, il Ministero della Difesa fa presente l'impossibilità di
  assegnare l'intera banda, ma solo le seguenti singole frequenze, a 25 KHz max:
  70.100 MHz - 70.200 MHz - 70.300 MHz. » Validity: « fino al 31 dicembre 2026 ».

### 3.1 Per-band exceptions

- **60 m**: 5351.5-5366.5 kHz, 15 W EIRP, secondary (PN 32B). No other channels.
- **70 MHz**: not in the PNRF; only the three experimental channels above,
  10 W, until 31 Dec 2026.
- **2300-2450 MHz**: whole range amateur (secondary) at 500 W PEP; amateur-
  satellite listed only in 2440-2450 (§4).
- **23 cm**: 1240-1245 and 1270-1298 MHz terrestrial; 1245-1267 and 1298-1300
  MHz refused. ECC/DEC/(25)01 (−17 dBW EIRP narrowband in 1258-1296 MHz, etc.,
  see C3 p.6) is **not yet law in Italy**; expected with the new PNRF (2027).
  Encode as a pending rule.
- **Unattended repeaters** (A26 Art. 9): max **10 W e.r.p.**, callsign every 10
  min, carrier only while a signal is present, drop-out ≤ 10 s.
- **Beacons** (CCE art. 143 c.4): identified by callsign + "/B".
- **Aircraft**: CCE art. 134 c.2 — portable/mobile operation allowed « escluso
  quello aereo » (not aeronautical mobile). The guard has no airborne mode.
- **Identification**: at start and end and every 10 minutes; packet callsign in
  every packet (A26 Art. 12 c.6).
- **Bandwidth/emission**: no bandwidth limit in A26; ARI says the "Note" column
  of its plan is mandatory « con OBBLIGO di rispetto » (ARIV p.7) — that is the
  society's statement, not law **[secondary]**.
- **Regional limits**: none found in A26 or the PNRF for the amateur service.

### 3.2 Gaps: not permitted for any class

137.8-472 kHz; 479-1830 kHz (**1810-1830 only experimental**); 1850-3500 kHz;
3800-5351.5 kHz; 5366.5-7000 kHz; 7200-10100 kHz; 10150-14000; 14350-18068;
18168-21000; 21450-24890; 24990-28000 kHz; 29.7-50 MHz (**40.66-40.70 only
experimental**); 52-144 MHz (**70.1/70.2/70.3 only experimental**); 146-430
MHz; **434-435 MHz**; **438-440 MHz**; 440-1240 MHz; **1245-1267 MHz**
(1260-1267 satellite-use only, not encoded); **1298-1300 MHz**; 1300-2300 MHz;
**2450-5650 MHz**; **5670-5760 MHz**; **5770-5830 MHz**; 5850-10300 MHz;
**10.0-10.3 GHz**; 10.5-24.0 GHz; **24.05-47 GHz**; 47.2-76 GHz; 81.5-122.25
GHz; 123-134 GHz; 141-241 GHz; above 250 GHz. Also 5650-5670 MHz is satellite-
only (refuse terrestrial use) and 145.8-146.0 MHz is satellite-only.

## 4. Satellite / QO-100

- **QO-100 uplink 2400.05-2409.5 MHz**: the PNRF row 2400-2440 MHz lists
  **"Radioamatore" (secondary) but not "Radioamatore via satellite"**;
  amateur-satellite appears only in 2440-2450 MHz (PB p.13, confirmed on the
  rendered page). [derived] Transmission in 2400-2410 MHz at ≤ 500 W PEP is
  within the amateur allocation; whether MIMIT regards an uplink to QO-100 there
  as needing the amateur-satellite allocation was not found
  **[UNCONFIRMED]**. QO-100 is in wide, open use by Italian amateurs and no
  restriction or special permission was found. Recommendation for the guard:
  allow 2400-2410 MHz at 500 W PEP and say why in the UI.
- **10.45-10.50 GHz** (QO-100 downlink): amateur and amateur-satellite,
  secondary (PC p.1).
- Other amateur-satellite: 7.0-7.1, 14.0-14.25, 18.068-18.168, 21.0-21.45,
  24.89-24.99, 28-29.7 MHz (primary); 145.8-146.0 MHz (exclusive); 435-436 MHz
  (primary); 1267-1270 MHz (Earth→space, note 117); 2440-2450; 5650-5670
  (uplink); 5830-5850 MHz (space→Earth); 24.00-24.05, 47-47.2, 76-81(.5),
  134-141, 241-250 GHz.

## 5. CEPT / visiting operators

- T/R 61-01: Italy "implemented 21-10-2019 — Implemented by a decree of
  Ministry of the Communications issued the 1st December 1990, published in the
  Italian Official Gazette No.5 dated 7 January 1991" [C2]; national licence
  "A", prefix "I" (C1 p.6, note 9: both old classes became class "A" in 2005).
- CCE art. 140 c.1: CEPT-licence holders « sono ammessi, in occasione di
  soggiorni temporanei, ad esercitare in territorio italiano la propria stazione
  portatile o installata su mezzi mobili, escluso quello aereo, senza formalità
  ma nel rispetto delle norme vigenti in Italia » — visitors get the class-A
  table above (portable/mobile, not airborne). Callsign form I/own-call (I +
  region digit optional) per T/R 61-01 **[secondary]**.
- T/R 61-02 (HAREC): implemented 28-03-2012 [C2]; A26 Art. 2 c.4: HAREC
  holders staying > 3 months may get an Italian patente.
- ECC/REC (05)06 (Novice): CEPT table says "not implemented / see remarks"
  (06-02-2026) [C2], but DMN (26 Jan 2026, GU 3 Mar 2026) formally adopts it;
  the class-N privileges are still unpublished. Treat CEPT Novice visitors as
  **not authorised** until the Allegato 26 amendment appears **[UNCONFIRMED]**.

## 6. Callsigns

A26 Art. 6 c.1: « Il nominativo … è formato dalla lettera I … cui può seguire
una seconda lettera, seguita da una singola cifra legata alla regione di
appartenenza e da un gruppo di lettere. » The Ministry may move to up to 7
characters if callsigns run out. Repeaters and club stations get calls under
Art. 6 c.2 / 9 c.2; beacons add "/B" (CCE art. 143 c.4). SWL tags: « lettera I
(Italia), numero di protocollo, sigla della provincia » (Art. 8). Vanity calls
≤ 5 characters (CCE art. 139 c.2-bis) — format not yet published.

The second letter no longer indicates a class (one class since 2005). The
region digits are not listed in A26; the usual mapping (I1 Piemonte/Liguria,
IX1 Valle d'Aosta, I2 Lombardia, I3 Veneto, IN3 Trentino-Alto Adige, IV3 Friuli-
Venezia Giulia, I4 Emilia-Romagna, I5 Toscana, I6 Marche/Abruzzo,
I7 Puglia/Basilicata, I8 Campania/Calabria/Molise, I0 Lazio/Umbria, IS0
Sardegna, IT9 Sicilia) is **[secondary]/[UNCONFIRMED]**. No portable suffix
rule exists in A26 (Art. 13: temporary operation away from home needs no
notice).

Regex hint (all → `a` until class N calls exist): `^I[A-Z]?[0-9][A-Z]{1,4}$`.

## 7. National band plan

ARI publishes: **HF** — the IARU R1 HF plan of 16 Oct 2020 as is [ARIH] (same
document as I1 in docs/ham/bandplan-r1-uk.md); **VHF and up** — "Band Plan
Italiano" Rev. 0.6, 24 Jan 2018 [ARIV], built on the **2015** PNRF and Landshut
2017. Both are older than the 2022 PNRF; where the PNRF is narrower the plan
must be clipped to it [derived].

HF (apply ARIH = IARU R1 2020, clipped to Italian allocations):
- 160 m: Italy has only 1830-1850 kHz: 1830-1838 CW, 1838-1840 narrow (500),
  1840-1843 all modes/digimodes, 1843-1850 all modes. (1810-1830 experimental:
  CW and narrow modes.)
- 80 m: 3500-3510 CW intercontinental; 3510-3560 CW (3555 QRS); 3560-3570 CW
  (3560 QRP); 3570-3600 narrow/digimodes (3590-3600 unattended); 3600-3800 all
  modes (3630 DV, 3690 QRP, 3735 image, 3760 emergency, 3775-3800
  intercontinental).
- 60 m: 5351.5-5354.0 CW/narrow 200; 5354.0-5366.0 all modes USB 2700;
  5366.0-5366.5 weak signal 20 Hz.
- 40, 30, 20, 17, 15, 12, 10 m: IARU R1 2020 as in bandplan-r1-uk.md (IBP
  beacons **14099-14101, 18109-18111, 21149-21151, 24929-24931, 28199-28201
  kHz**; **29300-29510 satellite downlink**; 10 m FM repeaters 29520-29590 in /
  29620-29690 out, input 100 kHz below output).

VHF and up [ARIV]:
- **6 m**: 50.000-50.100 CW 500 Hz (50.000-50.030 synchronised beacon
  project; 50.050 European, 50.090 intercontinental CW); 50.100-50.200 CW/SSB
  (50.100-50.130 intercontinental, 50.110 call, 50.150 international);
  50.200-50.300 general (50.285 crossband); 50.300-50.400 CW/MGM (50.305 PSK,
  50.310-50.320 EME, 50.320-50.380 MS); **50.400-50.500 beacons exclusive**
  (1 kHz; 50.401 WSPR); 50.500-52.000 all modes 12 kHz (50.510 SSTV, 50.540-
  50.580 FM/gateways, 50.620-50.750 digital, 50.630 DV call, 51.410-51.590 FM/DV
  simplex, 51.510 FM call); repeaters **in 51.210-51.390 / out 51.810-51.990**
  (20 kHz) — **input 600 kHz below output**.
- **2 m**: **144.000-144.025 satellite downlink only**; 144.025-144.100 CW
  (144.050 CW centre, 144.100 random MS); 144.100-144.150 CW/MGM (EME MGM
  144.110-144.160); 144.150-144.400 CW/SSB/MGM (144.300 SSB); **144.400-
  144.490 beacons exclusive**; 144.491-144.493 experimental MGM; 144.500-
  144.794 all modes 20 kHz (144.500 image, 144.600 data, 144.750 ATV talkback);
  144.794-144.9625 MGM/digital 12 kHz (144.800 APRS; DV gateways 144.8125-
  144.8625); **repeater inputs 144.975-145.194** (shift 600 kHz, 12.5 kHz);
  145.194-145.206 space comms; 145.206-145.5625 FM/DV simplex (145.375 DV call,
  145.500 FM call); **repeater outputs 145.575-145.7935** (input 600 kHz below
  output); 145.794-145.806 space comms; **145.806-146.000 satellite exclusive**
  (PNRF note 69 makes 145.8-146.0 legally satellite-only).
- **70 cm** (Italy: 430-434, 435-438 only): **repeater outputs 430.025-430.375
  (RU002-RU030) with inputs 431.625-431.975 — input 1.6 MHz ABOVE output**;
  second system **inputs 431.225-431.600 (RU226-RU256) with outputs
  432.825-433.200 — input 1.6 MHz below output**; 432.000-432.025 EME;
  432.025-432.100 CW/MGM (432.050); 432.100-432.400 CW/SSB/MGM (432.200 SSB,
  432.350 microwave talkback, 432.370 FSK441); **432.400-432.490 beacons
  exclusive**; 432.491-432.493 experimental; 432.500 APRS; 432.500-432.975 all
  modes; 433.000-433.575 FM/DV (433.400 SSTV, 433.450 DV call, 433.500 FM call,
  simplex 433.400-433.575 at 25 kHz); 433.600-434.000 all modes (433.625-
  433.775 digital, 433.700 FAX); **435.000-438.000 satellite** (ARI: no
  repeaters in 435-438). ARI notes ATV/DATV is not possible on 70 cm in Italy.
- **23 cm** (Italy: 1240-1245, 1270-1298; sat 1260/1267-1270): 1240.000-
  1240.500 future services 2.7 kHz; 1240.500-1240.750 planned beacons; 1240.750-
  1241.000 FM/DV future; 1241-1245 all modes (**repeater outputs 1242.025-
  1242.700 RS1-RS28, inputs 1270.025-1270.700 — input 28 MHz above output**;
  1242.725-1243.250 digital RS29-RS50, paired 1270.725-1271.250); **1260-1270
  satellite**; 1272-1290.994 ATV/DATV (ARI: ATV only as input, centre 1281.5);
  **repeater inputs 1290.994-1291.481 (RM0-RM19), outputs 1296.994-1297.481 —
  input 6 MHz below output**; 1291.494-1296 all modes; 1296.000-1296.025 EME;
  1296.025-1296.150 CW/MGM; 1296.150-1296.800 CW/SSB/MGM (1296.200; 1296.400-
  1296.600 transponder in; 1296.600-1296.800 transponder out; 1296.741-1296.743
  EMGM; 1296.750-1296.800 local beacons 10 W ERP max); **1296.800-1296.994
  beacons exclusive**; 1297.500-1297.975 FM simplex (1297.500 FM, 1297.725 DV
  call, 1297.900-1297.975 gateways).
- **13 cm**: 2300-2320 all modes (2304-2306, 2308-2310 alternative SSB/CW);
  2320.000-2320.025 EME; 2320.025-2320.150 CW; 2320.150-2320.800 CW/SSB
  (2320.200; 2320.750-2320.800 local beacons 10 W ERP); **2320.800-2321.000
  beacons**; 2321-2322 FM/repeaters; 2322-2355 ATV; 2355-2365 digital;
  2365-2370 repeaters; 2370-2392 ATV (ATV translator in/out); 2392-2400 digital;
  **2400-2450 "Satellite"** in ARI's plan (2427-2443 ATV if no satellite).
  Note PNRF 2022 lists amateur-satellite only in 2440-2450.
- **6 cm** (Italy: 5650-5670 sat, 5760-5770, 5830-5850): 5650-5668 satellite
  uplink (ARI also allows amateur WiFi — but the PNRF gives no terrestrial
  amateur use there [derived: refuse]); 5668-5670 satellite / SSB-CW (5668.2);
  5760.000-5760.800 SSB/CW (5760.200; local beacons 5760.750-5760.800, 10 W
  ERP); **5760.800-5760.990 beacons**; 5761-5762 SSB/CW; 5762.010-5770 digital
  ≤ 2 MHz, DATV beacon tests 8 MHz; 5830-5850 satellite downlink and ATV
  (translator outputs).
- **3 cm** (Italy: 10.3-10.5 GHz): 10300-10350 digital; 10350-10368 all modes;
  10368.000-10368.800 narrowband (10368.200; local beacons 10368.750-10368.800,
  10 W ERP); **10368.800-10368.990 beacons**; 10369-10400 all modes;
  10400-10500 satellite and ATV (ATV translator outputs).
- **24 GHz** (Italy: 24.000-24.050): 24000-24048 all (24025 wideband);
  24048.000-24048.800 SSB/CW/satellite (24048.200; local beacons 24048.750-
  24048.800); **24048.800-24048.995 beacons**; 24049-24050 satellite/NB.

Differences from IARU R1 (consequences of the PNRF, not ARI choices):
- No 434-435 / 438-440 MHz: Italy's 70 cm repeater systems are the 430/431.6
  MHz pair (input above output!) and the 431.2/432.8 MHz pair; no ATV on 70 cm.
- No 1245-1260 or 1298-1300 MHz; ATV confined to 1272-1291 MHz (input only).
- No 10.0-10.3 GHz; no 24.05-24.25 GHz; 6 cm is 5760-5770 (primary!) and
  5830-5850 plus a satellite-only 5650-5670.
- 160 m only 1830-1850 kHz (plus experimental 1810-1830 at 10 W).
- 145.8-146.0 MHz is legally satellite-only (PNRF note 69).

## 8. Confidence and gaps

**Overall: medium-high** for class A (current PNRF 2022 tables and notes read
in full; Allegato 26 current per MIMIT's 2025 "testo vigente" and DMN 2026
Art. 4); **low** for anything about class N (not yet defined).

UNCONFIRMED / caveats:
- **Class N**: no bands, power, emissions or callsign format published as of
  2026-10-08. Watch for the decreto direttoriale amending Allegato 26.
- **QO-100**: PNRF 2022 puts amateur-satellite only in 2440-2450 MHz; uplinks in
  2400-2410 MHz rely on the terrestrial amateur allocation [derived].
- **1260-1267 MHz**: satellite listed only as a "utilizzazione"; note 117
  allocates 1267-1270 Earth→space. Encoded conservatively as 1267-1270 uplink.
- Region-digit table [secondary]; no portable suffix in law.
- ARI's VHF+ plan is from 2018 (PNRF 2015); its 2400-2450 "Satellite" label and
  5650-5668 "WiFi" use disagree with PNRF 2022.
- **Pending**: new PNRF (2027) with WRC-23 and ECC/DEC/(25)01 23 cm limits;
  experimental 160 m / 8 m / 4 m authorisations end 31 Dec 2026 (renewed
  yearly by MIMIT letter to ARI).
