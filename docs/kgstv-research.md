# KG-STV: what it is, where each fact comes from

Compiled 2026-10-08 for the KG-STV receiver (ohscore/dsp/kgstv.py). Marks as in
qo100-research.md: **[local]** measured here, **[derived]** worked out rather
than found stated, **[unverified]** not confirmed. Everything not so marked is
either stated by the program's author or seen on real signal, and says which.

## 1. The program

- **KG-STV**, "Digital Image TRX software", by K.G., **JJ0OBZ** (Myoko,
  Niigata). Windows only, freeware, no source. Version 1.0.0 build 000 of
  08/02/2010; the last is 1.0.1 build 004 (kgstv.exe dated 11/07/2010).
  The handover had this as "JA-origin, by JE3HHT"; JE3HHT is Makoto Mori,
  MMSSTV's author, and has nothing to do with KG-STV.
- Its site, <http://www2.plala.or.jp/hikokibiyori/soft/kgstv/>, no longer
  answers (plala closed its home pages). The Internet Archive has the zip:
  `http://web.archive.org/web/20240525020351/http://www2.plala.or.jp/hikokibiyori/soft/kgstv/kgstv.zip`
  (510 808 bytes: kgstv.exe, readme.txt for build 001, readme2.txt for
  002->003, readme3.txt for 003->004; all three readmes in Shift-JIS).
  Downloaded 08/10 **[local]**; not kept in the repository.
- No open decoder exists that I could find. sigidwiki's page and PY4ZBZ's
  Portuguese write-up (10/06/2010) restate the readme's specification; an
  AMSAT-BB thread found by search says the program "appears to have been
  abandoned in 2010 ... not really enough documentation available to make a
  compatible decoder" (thread not readable here: HTTP 403).

Sources: <https://sigidwiki.com/wiki/KG-STV>, <https://qsl.net/py4zbz/kg.htm>,
<https://www.sigidwiki.com/images/7/73/KG-STV_Readme.pdf>, the readmes above.

## 2. The author's specification (readme.txt, "KG-STVの伝送規格"), translated

| Item | Stated |
|---|---|
| Modulation | MSK, or MSK combined with 4-level FSK |
| Rate | 1200 baud |
| Tones | MSK: space 1200 Hz, mark 1800 Hz. 4L-FSK: '00' 1200, '01' 1400, '10' 1600, '11' 1800 Hz |
| Bandwidth | 500-2500 Hz |
| Error correction | none, or Viterbi (NASA standard K=7) |
| Whitening | yes: a period-127 m-sequence added to every bit |
| Interleaver | none |
| Header | 256 bits of repeated 01 |
| Frame | sync + 54-bit information chunk + data chunk of any length |
| Error detection | CRC 16 CCITT |
| Sync | 63-bit m-sequence |
| Picture | JPEG-compatible, 16x16 pixels, 4:1:1 subsampling |
| Text | Shift-JIS |
| Emission | F1D (SSB), F2D (FM) |

Information chunk (system code 0), bit positions: sys 0-3, command 4-7,
coding mode 8, modulation mode 9, block x 10-15, block y 16-21, JPEG scale
22-25, data size 26-37, CRC 38-53. "The information chunk is always MSK and
convolutionally coded." The data chunk is the data and its CRC, straight
after the information chunk's CRC. Commands: 0 text, 1 image, 2 BSR reply
(a repeated block), 3 end, 4 BSR request, 5 abort, 6 callsign. End, abort
and BSR frames carry no data chunk. A transmission starts with the 01
header; a picture is one frame per block; a normal end sends the end frame
three times (configurable from build 003), an abort the abort frame three
times. The callsign frame goes first, five times by default (1-12, build
004).

Sync: `000011100001001000110110010110101110111100110001010100111111010`.
Whitening: `1110110011000100100111001111100100000100011010101001101101001010`
`000101100001100101111111010110111011110001110100010101110000001`.

Other facts from the readmes: 320x240 pictures, 15 rows of 20 blocks, sent
left to right and top to bottom (vertical and random scan were added in
build 003); the receiver times a picture out after 30 s with nothing heard;
a picture is saved once at least 50 blocks arrived (build 004 default);
received pictures are saved as `date_time_callsign.jpg`; text up to 510
single-byte characters.

## 3. What real signal settled

Brian's 3-hour recording of 07/10/2026 (15:22-18:26 UTC,
`~/openhamshack-samples/qo100-2026-10-07/openhamshack-nb-20261007-152223Z-10489.540MHz-FT8`,
1.2 MS/s, rxCorr track applied) has four KG-STV pictures, all at USB dial
10489.6249 MHz (tones centred on 10489.6264) **[local]**:

| UTC | Station | Mode | Blocks decoded by ohscore/dsp/kgstv.py |
|---|---|---|---|
| 15:28:57 | VU2SAA ("VU2SAA    Sam     NK03CA"): an aircraft | MSK/CONV | 298 of 300 |
| 17:13:16 | DL4CQ: the Earth from the Moon, "JO31GM SAT QO-100 TEST" | MSK/NORM | 300 of 300 |
| 17:17:40 | DL4CQ: a cartoon in a hammock, same captions | MSK/NORM | 300 of 300 |
| 18:22:58 | DG8RP: his dish, "OP: René" | MSK/NORM | 294 of 300 |

(The decoder alone, through a 1.2 kHz low-pass at 12 kS/s. DG8RP's signal
jumped 700 Hz for 12 s mid-picture; his missing blocks are there. The whole
recording played back through OpenHamShack NB itself - beacon lock, the engine's
own channel - gave 298, 300, 300 and 296: 1194 of 1200, five frames lost,
no channel block dropped **[local]**.)

Established on those frames - every one of them, not a sample:

- The sync word matches bit for bit; 1 = 1800 Hz (above the centre).
- The information chunk is the NASA K=7 code (171, 133) with the **133
  output first**, 108 channel bits, **no tail**: the data chunk starts at
  bit 171 after the sync's first bit. [derived: as a register with the
  newest bit at the bottom, the generators are 155 and 117 octal.]
- Whitening is XORed with the channel bits and **restarts at each chunk**
  (the information chunk's 108 coded bits start the sequence; the data
  chunk starts it again).
- **CRC**: polynomial 1021, register preset **1D0F**, MSB first, no final
  XOR (CRC-16/AUG-CCITT). Chunk plus CRC leaves 0.
- `size` is in **bits**; image data chunks are not byte-padded (sizes of 75,
  77, 99 bits occur).
- Callsign frames carry ASCII; DL4CQ and DG8RP send five at the start
  (DL4CQ's first picture six) and one after every tenth block. End frames:
  ten at the end of each picture seen.
- Coded (CONV) data chunks, from VU2SAA: the same code over the data and its
  CRC, then whitened, restarting - 2 x (size + 16) channel bits; whether a
  tail follows is [unverified] (decoding does not need it).
- System code 0 and JPEG scale index 10 on all four.

## 4. The picture codec

The readme says only "JPEG-compatible". Each image block's data parses into
exactly six JPEG blocks with the standard (Annex K) Huffman tables and not a
bit over - on all 1192 blocks. The rest came from reading kgstv.exe's own
decoder (C++Builder; the routine at 0x4098d8 and the coefficient readers at
0x40ab08 and 0x40abd8) **[local]**:

- The Huffman tables in the program (0x4cff50-0x4d0a50) are Annex K's.
- **Extra bits**: when the top bit is set the value is the bits; when clear,
  it is `-(bits + 2^(n-1))`. JPEG's rule is `bits - (2^n - 1)`. A standard
  decoder parses the stream and gets every negative coefficient wrong: on
  DL4CQ's picture black space came out mid-grey, with grey blocks wherever a
  star was.
- **DC**: absolute. Six predictors, one per block of the MCU, all zero at
  the start of every MCU (the routine copies them from zeros at 0x4ce198),
  so there is no prediction across blocks or frames.
- **Quantisation**: the Annex K example tables (as doubles at 0x4cea10 and
  0x4cec10) times a scale the 4-bit index picks from a table at 0x4ce118:
  0.07, 0.08, 0.09, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6,
  1.8, 2.0. Index 10 (x1.0) is what all four stations used.
- **Order** in the MCU: four luma blocks, then two chroma blocks. The luma
  order (top-left, top-right, bottom-left, bottom-right) is the only one in
  which the pictures join up; the chroma order is **Cr then Cb**, the reverse
  of JPEG's - the other way round Africa is blue and the sea orange.
  [derived from the pictures, not read from the code.]
- **Not checked against the program** [unverified]: its inverse DCT and
  colour conversion; this uses JPEG's (JFIF). A level or two of difference
  would not show.

## 5. Still unknown

- **4L-FSK** never appeared on the recording. The decoder slices four levels
  at +-200 Hz and 0 and takes the dibit MSB first, as the readme's tone
  table suggests, with whitening over the bits as for MSK [unverified]; a
  CRC that does not pass lets nothing through, so a wrong guess shows as
  "lost" frames, not a wrong picture.
- **BSR request** (command 4): no data chunk, per the readme; what its x
  and y mean (one missing block per request?) [unverified]. The receiver
  counts them and ignores them.
- **Text** (command 0): Shift-JIS per the readme, never seen on air.
- System codes other than 0.
- Whether kgstv.exe honours a different scale index in one frame of a
  picture [unverified]: NB's sender uses one only for a block whose data
  would not fit the 12-bit size field at the chosen scale, which no real
  picture at x0.6 or coarser comes near (section 6).

## 6. Sending (from 0.1.18)

NB sends KG-STV pictures from the KG-STV view (ohscore/modes/kgstv.py builds
the over from ohscore/dsp/kgstv.py; the simulator's station uses the same
code). What it sends, and where each choice comes from:

| Choice | Source |
|---|---|
| MSK, uncoded ("MSK/NORM") | What DL4CQ and DG8RP sent; every detail of it checked on air (section 3). The coded variant is decoded, but only its information chunk is certain to match the program's coding. |
| Tones 1200/1800 Hz, 1200 Bd, continuous phase | The readme (section 2); verified on the recording. |
| 256-bit 0101 preamble; callsign x5; a callsign line after every tenth block | The readme's defaults; DL4CQ and DG8RP did the same. |
| End frame x5 | The readme says 3 (configurable); every station heard sent 10. **[derived]** five as a margin over a fade for 0.4 s. |
| Band-limited to MSK's main lobe (-6 dB at 700 and 2300 Hz) | **[local]** Unfiltered, MSK's f^-4 sidelobes made the 99.5 % width the engine measures and the band plan judges swing from 2.3 to 5.6 kHz with the picture (a busy photograph at x0.6: 2.8 kHz, refused in the 2.7 kHz segment). Filtered it is 1.39-1.41 kHz for every picture and quality, as any KG-STV station's SSB filter would make it; NB's receiver channel is +-1.2 kHz anyway. |
| 32 more preamble bits after the last end frame, 5 ms fades | **[local]** NB's own receiver lost the final frame on a clean signal without the tail (the unterminated code's last bits sit in the receiver's settling). The fades stop key clicks. |
| Scale index 10 (x1.0) by default; x0.6, x1.4, x2.0 offered | Index 10 is what every station heard used; the program offers the scale as its picture quality beside the over's length ("TxTime"), and so does NB. |
| Callsign line "CALL LOCATOR" | The program's Callsign box is free text; stations put their call and often a name and locator in it ("DG8RW JN69CV", "PA3EKI - Jack - JO21GW", "DH1BM Bernhard JO32PO", ohs-box, 10-12/10/2026). NB sends the station's call and locator. No call, no picture: KG-STV itself refuses ("Set your callsign"). |
| 4:3 cut from the middle, then scaled to 320x240 | The readme: pictures are resized to 320x240 and the excess top/bottom or left/right is cut off. |
| Halt stops the RF at once; no abort frames | **[derived]** The program sends the abort frame three times when its operator stops a picture; NB's Halt/Escape is an emergency unkey and sends nothing more. A receiver keeps what it had and times the picture out after 30 s (and saves it from 50 blocks). |

Over lengths, measured with this encoder on real pictures received on
ohs-box (PA3EKI, DH1BM, TA2VB) and on noise, the worst case: at x1.0,
93-172 s for pictures and 264 s for noise; at x2.0, 83-134 s and 177 s; at
x0.1 a busy photograph reaches 322 s. NB's default transmit time-out is
300 s, so every picture fits at the standard quality; NB does not raise
the time-out for KG-STV (ohsnb/ui/kgstvsend.py says why) but shows each
quality's length and offers the finest one that fits.

**Interop with kgstv.exe** itself: not yet tried. Everything above is
proved against NB's receiver, which was itself proved on real stations'
frames and on the program's own decoder (sections 3 and 4).
