# Signals on the NB transponder that OpenHamShack NB does not decode

From the 3 h recording of 2026-10-07 (15:22-18:30 UTC, 500 kHz wide,
`~/openhamshack-samples/qo100-2026-10-07/`). `--analyse --other-modes` only counts
FT4/Q65/JS8/PSK31 decodes and does not list unknowns, so this list came from a
separate pass: 2 s every 20 s across the band, then short excerpts of each
candidate. The scripts used are kept beside the recording in `nbid/` - they are
throwaway, not part of the app.

Already decoded and seen in the recording: FT8, FT4, JS8, PSK31, CW, SSB voice,
the multimedia beacon, analogue SSTV (Scottie S1 at 10489.633, 16:38 UTC), and
since 08/10 the middle beacon's text and KG-STV.

| Frequency | What it is | Confidence | Decoder |
| --- | --- | --- | --- |
| 10489.6264 centre (USB dial 10489.6249) | **KG-STV** digital picture (JJ0OBZ): 1200 Bd MSK, tones 1200/1800 Hz, ~2.2 min per 320x240 picture. Four on the recording: VU2SAA 15:29 (coded), DL4CQ 17:13 and 17:17, DG8RP 18:23 | Certain - decoded | **Done 08/10** (ohscore/dsp/kgstv.py, ohsnb/kgstvrx.py, the Beacon view's KG-STV page): 1192 of the four pictures' 1200 blocks, MSK coded and uncoded. The picture codec was read from kgstv.exe (docs/kgstv-research.md). 4L-FSK: never heard, decoded on a guess that only a passing CRC lets through. |
| 10489.750 middle beacon | AO-40-format 400 bit/s BPSK: an uncoded text block (K, L, M, N in turn), then a 5200-symbol AO-40 FEC frame, one block every 25.4 s | Certain - the uncoded blocks decode with a good CRC, and the FEC frame's 65-bit sync matches in full | **Uncoded blocks: done 08/10** (ohsnb/dsp/ao40.py, ohsnb/beacontext.py, the Beacon view's Middle beacon page). FEC frames: not decoded (gr-satellites' ao40_fec_deframer is the reference); whether they carry the same text is unknown. |
| 10489.6355-.6378 | Connected ARQ data: ~4.3 s blocks, ~0.8 s replies, ~7.5 s cycle; 15:27-15:41, 15:50-16:15 | Probably VARA HF, possibly ARDOP | VARA is closed: not feasible, and a private link anyway. ARDOP (ardopcf) only if it turns out to be that. |
| 10489.528-.534 | Faint, wide, same on/off times as the row above | That station's spurious, probably | - |
| 10489.6452-.6464 | ~1.1 kHz steady multicarrier, starts on the hour (16:00, 17:00, 18:00), ~10.5 min; a burst of evenly spaced tones every ~16 s | **Unidentified.** Not FreeDV 1600/700D/2020 (codec2, +-150 Hz, both sidebands) | Identify first: record 10 min from 16:59 UTC, try fldigi MT63-1000, freedv-gui 2.x (700E, RADE), ardopcf. |
| 10489.597 | ~5.5 s burst every ~10 min: 0.45 s tone, then dense multi-tone | **Unidentified.** Guess: an ARQ modem's beacon (VARA/ARDOP/FreeDATA) | Unknown |

Sources: [sigidwiki KG-STV](https://sigidwiki.com/wiki/KG-STV), docs/kgstv-research.md,
[PY4ZBZ KG-STV](https://qsl.net/py4zbz/kg.htm),
[AMSAT-DL tlmspec.txt](https://amsat-dl.org/wp-content/uploads/2019/01/tlmspec.txt).

The band skimmer (ohsnb/dsp/skim.py `KNOWN`, 08/10) names each of these by
its frequency on its list and on the wide scope - KG-STV with its USB dial
10489.6249 - so an operator sees what they are without decoding them.

Order agreed 08/10: middle-beacon text first, then KG-STV receive; identify
10489.646 before building anything for it; skip VARA.

## 17/10/2026: five recordings from Brian's Mac (15:41-15:57 UTC)

Five NB recordings (Pluto, 1.2 MS/s, 13 min in all, receive only), four
with the dial at 10489.540 and one at 10489.818. It was JOTA-JOTI weekend,
and the FT8 window had a pile-up on 7P8GE. Method: a whole-band waterfall
per recording (32k-point FFTs, 0.22 s lines, memmapped), occupied runs
over a local median floor, then spectrogram crops of each run and NB's own
decoders on 12 kHz USB audio cut from the IQ with the recording's rxCorr
track applied. The scripts are throwaway and are not in the repo. The
crops are in `ohs-dev:~/build/iq-17oct-report/`.

| Downlink (MHz) | What | Confidence | NB |
| --- | --- | --- | --- |
| .5112, .5250 (and .5061, .5173, .5216 briefly) | CW QSOs: IU5OHC-G4TQM, DL0FF-F6GHG | Certain (decoded) | CW decoder |
| .5401-.5432 | FT8 calling window, 7P8GE pile-up | Certain | FT8 (181 decodes in rec 1) |
| .5521, .7709 | FT8 well off the calling window (DG7MHR calling BG8KUV, DK5AI calling 7P8GE; the second is in the SSB segment) | Certain (ohsdigi decoded) | Not heard: the FT8 decoder only listens at the calling dial |
| .5695 | Weak (~8 dB) slow FSK, ~45 Hz shift, all five recordings | Low. A QRSS or FSK-CW beacon? | No |
| .5877-.5882 | Carrier keyed ~0.4 s on / 0.4 s off for up to a minute, with sidebands every ~137 Hz (a buzzy note). Not Hellschreiber (a 245 px/s raster shows no glyphs) | Low. Someone testing? | No |
| .5955-.5974 | The burst from 07/10: a 0.45 s tone, then 2-8 s of MFSK. Tones sit on a 93.75 Hz grid (about 20 of them, ~1.9 kHz wide), keyed at 46.875 Bd (12000/256), often two at once. Three bursts in 80 s in rec 3, so not only once every 10 minutes | Unidentified. An ARQ modem's connect or beacon frame (VARA, ARDOP, FreeDATA?) | No |
| .6115-.6128 (USB dial 10489.6104) | SSTV Scottie S1, MMSSTV preamble, VIS 60, 2300 Hz-ramp lines, FSK ID (1900/2100 Hz) and a CW ID after it: LX9S's JOTA-JOTI picture | Certain (decoded) | SSTV decoder: 2 full pictures, 1 partial |
| .6257-.6273 | KG-STV, 1200 Bd MSK (z² lines 1200 Hz apart): DH1BM (MSK/CONV), Z31RQ/SP3BGD, DJ0ZK | Certain (decoded) | KG-STV |
| .6532 | RTTY 45.45 Bd, 170 Hz shift: "DA IST EIN TEST ... DE HB0AA" | Certain (decoded) | RTTY decoder |
| .650-.745 and .755-.850, .865-.990 | USB voice QSOs, ~15 at a time. The one at Brian's dial (10489.818, rec 5, 2-45 s) is USB voice | Certain (harmonics on spectrograms) | SSB. Until 17/10 the skimmer listed every one as "SSB?" (see skim.ssb_label) |
| .6986, .9114, .8281 | A short downward sweep, a carrier being tuned, short carriers: stations tuning up | Medium | - |
| .750, .8500-.8527, .9936-.9963, the CW beacons | Middle beacon, AMSAT-DL slot (voice in it at the time), multimedia beacon (no frames decoded in rec 1), lower and upper beacons | Certain | Named. Beacon lock said the lower/upper beacons were "not heard" (SNR +0.2 dB) although both are plainly on the waterfall |

Nothing in these recordings is a documented mode that NB lacks a decoder
for. The unknowns are either unidentifiable from one side of an ARQ link
(.597) or not a mode at all (.5695, .588).
