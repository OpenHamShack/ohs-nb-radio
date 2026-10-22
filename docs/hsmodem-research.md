# HSmodem and the QO-100 multimedia beacon: research notes

Compiled 2026-10-06 for receiving AMSAT-DL's High-Speed Multimedia Beacon in
OpenHamShack NB (Brian's decision, 06/10: "option 1"); section 8 added 07/10
for HSmodem station to station, sending and receiving (Brian, 07/10).
Same conventions as qo100-research.md:
every fact has a source; **[read in source]** means I read it in the code
named; **[derived]** is my own working; **[measured]** is a run of
HSmodem's own code on shack; **[unverified]** is what no source or run
settles - most of those need a dish (Ray).

---

## 1. Licences - checked before anything was ported

| What | Where | Licence | Used how |
|---|---|---|---|
| **HSmodem**, the beacon's tree | github.com/amsat-dl/QO-100-Modem, branch main, commit `cbd30059c18607654c1530b7606c18e375b7f74c` (24 Oct 2022) | **GPL-3.0** (`LICENSE`); file headers say "GPL version 2 or (at your option) any later version", (c) Kurt Moraw DJ0ABR | Ported to Rust (frame, constellation, scrambler table, CRC, receive loop, tracker wiring, modulator wiring); GPL-2-or-later and GPL-3.0 are both compatible with our GPL-3.0-or-later |
| HSmodem, DJ0ABR's own repository | github.com/dj0abr/SSB_HighSpeed_Modem (last commit 15 Mar 2021, "Version 0.87") | GPL-3.0 | Read for comparison; the AMSAT-DL tree is the same code plus the beacon build (filesend.cpp, `AMS_TESTMODE`, zip) |
| **liquid-dsp** "1.3.2", as HSmodem ships it | `hsmodem/SharedLibs/{x86_64,aarch64}/libliquid.so` (version string 1.3.2; exports the 2020+ `liquid_error_*` API); source: github.com/dj0abr/liquid-dsp (fork, 2021) and the v1.3.2 tag of github.com/jgaeddert/liquid-dsp | **MIT**, (c) Joseph Gaeddert | Ported to Rust (NCO, AGC, symsync, firpfb, firinterp, firdecim, eqlms, APSK modem, filter design); notice in `rust/ohsdigi/LICENSE-THIRD-PARTY` |
| **Schifra** Reed-Solomon (in `hsmodem/fec/`) | schifra.com | "General Schifra License" - its own terms, not GPL | **Not ported.** ohsdigi's RS(255,223) is written from the textbook algorithms with HSmodem's parameters (a fact, not code) and checked against Schifra itself (section 6) |
| ams_extension, the beacon's feeder | github.com/amsat-dl/ams_extension (2021) | **none stated** | Read for facts only (what the beacon sends, the DX-cluster text format); nothing copied |
| gr-satellites QO-100 beacon receiver | github.com/daniestevez/gr-satellites `python/filereceiver/qo100_multimedia.py`, `examples/qo100-multimedia-beacon/` | GPL-3.0-or-later, (c) Daniel Estévez EA4GPZ | Read as an independent second reading of the file format; nothing copied |

HSmodem's README lists its third-party parts: Schifra (it says "GPL V.2"),
liquid-dsp (MIT), libsoundio (MIT), FFTW (GPL-2+), codec2 (LGPL-2.1),
portaudio. Only liquid-dsp's algorithms are in ohsdigi.

## 2. Sources

- AMSAT-DL, "QO-100 High Speed Multi Media Beacon":
  <https://amsat-dl.org/en/qo-100-high-speed-multi-media-beacon/>
  (fetched 06/10/2026).
- AMSAT-DL wiki, HSmodem pages (fetched 06/10/2026):
  [start](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:start),
  [techdata](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:techdata),
  [packer](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:packer) (frame
  format), [filetx](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:filetx)
  (file transfer), [streaming_intro](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:streaming_intro),
  [streaming_beacon](https://wiki.amsat-dl.org/doku.php?id=en:hsmodem:streaming_beacon).
- HSmodem manual rev 2.03 (DJ0ABR, DD1US):
  <http://www.dd1us.de/Downloads/Manual%20HSModem%20rev%202.03.pdf> - linked
  from the beacon page; not read (the source and the wiki answered
  everything it would) **[unverified that it says nothing different]**.
- Daniel Estévez EA4GPZ, "Decoding the QO-100 multimedia beacon with GNU
  Radio", 15 May 2022:
  <https://destevez.net/2022/05/decoding-the-qo-100-multimedia-beacon-with-gnu-radio/>
  - a receiver written from the source and run on the real beacon.
- HSmodem source files named below are in `hsmodem/` of the AMSAT-DL tree
  at the commit above.

## 3. The beacon

| Item | Value | Source |
|---|---|---|
| Downlink centre | **10489.995 MHz** | AMSAT-DL beacon page |
| "Zero beat, SSB" | 10489.9933 MHz | AMSAT-DL beacon page. That puts the centre 1700 Hz up the audio, not HSmodem's 1500 Hz **[derived]** - one of the two is off by 200 Hz, or the page assumes some offset. NB decodes from IQ around 10489.995 and its frequency acquisition covers +-171 Hz, so either works **[derived]** |
| Modulation | 8APSK, 2400 Bd, 7200 bit/s gross, 2.7 kHz | beacon page ("Symbol rate: 7200 bit/s" there means the bit rate); EA4GPZ: 2.4 kBd |
| HSmodem speed mode | **9**: 48000 Hz audio, TX interpolation 20, RX pre-decimation 5, 3 bits/symbol | `hsmodem.cpp` `sr[]` **[read in source]**; ams_extension `getBCconfigdata()` sets `txdata[9] = 9; // mode 8APSK 7200 bps` **[read in source]** |
| Station | DK0SB, Bochum, JO31OK, "Amsat-DL Bochum" | ams_extension `getBCconfigdata()` **[read in source]** |
| On air since | end of May 2022 (test transmissions mid-May) | beacon page; EA4GPZ |
| Contents (as published) | NB transponder activity, WB transponder activity, DX-cluster messages, CW skimmer, AMSAT bulletins; APRS "planned" | beacon page; wiki streaming_beacon |
| Contents EA4GPZ actually saw (May 2022) | ASCII bulletins `amsat_1.blt`, `amsat_2.blt`... and `qo100info.html` (the browser page for the streams) as files; streams of spectrum/waterfall, DX cluster, CW skimmer | EA4GPZ |
| Pictures | the beacon's config calls its file folder "Folder for Amsat Bulletins, Pictures..."; `filesend.cpp` sends `.jpg` as type 2. Whether the beacon sends any picture today is **[unverified]** - nobody reports one | ams_extension `ams_config.txt` **[read in source]** |
| File cycle | one file from the folder every `BULLETIN_CYCLETIME` seconds (60 in the shipped config), round robin | ams_config.txt, filesend.cpp **[read in source]**; the live value **[unverified]** |
| Stream timing | "mixed in a time grid of 250 ms" | wiki streaming_beacon. In the source the five TX queues (GUI, external DX/CW, NB spectrum, WB spectrum, files) are served round robin, one frame each turn (`distrubution.cpp`) **[read in source]** |
| How it is transmitted | HSmodem built with `-DAMS_TESTMODE` (`Makefile_ams`): `modulator()` hands each 8APSK symbol, **unfiltered, one complex sample per symbol**, x0.9, to `ams_testTX()`, which ships blocks of 7500 int32 I/Q pairs over UDP (port 40809) to a separate "Pluto driver" running the Pluto at 3.072 MS/s with 64x interpolation | `liquid_if.cpp`, ams_extension.cpp **[read in source]**. The Pluto driver is **not published**: its pulse shaping, interpolation and what it does when the queue runs dry are **[unverified]**. EA4GPZ measured RRC, roll-off 0.2 on the received signal |
| Marker tone | HSmodem's sound-card build adds a 100 Hz tone at a quarter of full scale when `marker` is on (`tuning.cpp`, `liquid_if.cpp`); the beacon build never reaches that line. The wiki tells listeners to watch "the 100Hz subcarrier" while tuning. Whether the beacon carries one (from the Pluto driver) is **[unverified]** | source; wiki streaming_beacon |
| Repeats | file and stream frames go through `modem_sendPSKData(..., repeat=1)`: sent once, then repeated 21 times *if the sound card is not playing* (`isPlaying(io_pbidx)`). In the beacon build no sound card is opened (`io_pbidx` stays -1), so that test reads outside its array - what the beacon does is **[unverified]**. The receiver keeps file blocks across repeats either way | hsmodem.cpp, libkmaudio **[read in source]** |

## 4. The modem (all **[read in source]**, all confirmed by running it - section 6)

- **Constellation:** liquid-dsp's `LIQUID_MODEM_APSK8`: one point at 0
  and seven on a circle of radius 1.06904495 at angles 2πk/7; map from
  symbol to point index `{0,2,4,3,1,7,5,6}`; ring slicer at 0.53452247
  (`modem_apsk_const.c`). EA4GPZ: "a point at zero and seven points
  equally spaced along a circle".
- **Pulse shape:** RRC, β = 0.2, 15 symbols delay in HSmodem's sound-card
  modulator (`liquid_if.cpp` init_modulator; its tau of -0.2 gives a whole
  number of samples at 20x, so the filter's fractional delay is 0). On
  the beacon: done by the unpublished Pluto driver; EA4GPZ measured RRC 0.2.
- **Sound-card signal:** symbols interpolated by 20 at 48 kHz, mixed up
  to 1500 Hz by liquid's NCO, `usb = re + im`, times 0.1.
- **Receiver** (`liquid_if.cpp` demodulator, `symboltracker.cpp`): the
  sound-card sample f is taken as the complex f + jf, mixed down from
  1500 Hz, decimated by 5 (liquid Kaiser decimator, 8 symbols delay,
  40 dB, scaled 1/5 - and given only the first 80 of the 81 taps it
  designs) to 9600 S/s, then `km_symtrack` (DJ0ABR's copy of liquid's
  symtrack): AGC (bandwidth 0.018), symsync with a 16-phase RRC bank
  (k 4, m 7, β 0.2, loop bandwidth 0.0009, two outputs a symbol), carrier
  NCO as a PLL (bandwidth 0.0009) driven by the demodulator's phase error
  Im(r·conj(x̂)), and a 9-tap LMS equaliser (Kaiser low-pass at 0.45,
  rate 0.018), decision-directed after the first 200 symbols. **Hard
  decisions only**: no soft bits reach the FEC.
- **Watchdog:** if more than 5 s and more than two frame-times pass with
  no good frame, the tracker is reset (`hsmodem.cpp` GRdata_rxdata). A
  second reset fires 1 s after the FFT level detector sees a signal
  appear (`fft.cpp`); ohsdigi does not port that one.
- **Frame** (frameformat.h, frame_packer.cpp; wiki packer): 258 bytes =
  3-byte header `53 E1 A6` (not scrambled, not FEC-protected) + RS(255,223)
  codeword. The 223 data bytes are: frame counter bits 0-7; status byte =
  counter bits 8-9 (<<6) | first/next/last/single (<<4) | 4-bit type;
  219 payload bytes; CRC-16 big-endian over the first 221. The 255-byte
  codeword is XORed with `scrambler.cpp`'s table (400 bytes, which are one
  100-byte sequence four times **[derived]**; EA4GPZ guessed an LFSR).
  At 3 bits a symbol a frame is exactly 688 symbols, 286.7 ms.
- **CRC:** reflected CCITT, polynomial 0x8408, initial 0xFFFF, no final
  XOR (`crc16.cpp`) - CRC-16/MCRF4XX (EA4GPZ; check value 0x6F91 for
  "123456789" **[derived]**).
- **RS:** Schifra with `field_descriptor 8`, `primitive_polynomial06`
  `{1,1,1,0,0,0,0,1,1}` read lowest power first = x⁸+x⁷+x²+x+1 (0x187, the
  CCSDS field polynomial), generator roots α¹²⁰…α¹⁵¹ with α = 2, 32 parity
  bytes after the data (`fec.cpp`, Schifra headers). EA4GPZ: "polynomial
  ... from CCSDS", "first consecutive root ... 120", and he notes 120 buys
  nothing for a t=16 code.
- **Symbols:** bytes to 8APSK symbols MSB first, 3 bytes to 8 symbols
  (`constellation.cpp`). The header is symbols `2 4 7 6 0 6 4 6`.
- **Sync:** every received symbol, the last 688 hard symbols are a
  candidate frame; the header is looked for in its first 8 symbols under
  each of the 7 rotations of the outer ring (`rotate8APSKsyms`: a rotation
  maps symbol `0 1 2 3 4 5 6 7` to `0 4 3 1 5 7 2 6`; the table has 8 rows,
  the 8th equal to the 1st), allowing 2 mismatches (Linux; 5 on Windows).
  A hit is rotated back, descrambled, RS-decoded and CRC-checked; a
  failure just moves on a symbol. EA4GPZ instead runs seven decoders, one
  per rotation.
- **Frame counter** (`Pack()`): +1 per new frame, unchanged for a repeat
  (except type 1), reset to 0 by a file's first frame, untouched by type 8.

## 5. What the frames carry

Frame types (wiki packer; oscardata `config.cs`): 1 BER test, **2 image**,
**3 ASCII file**, **4 HTML file**, **5 binary file**, 6 audio (codec2),
7 user info (call, locator, name), **8 external data (streams)**.

### Files (types 2-5) - `filesend.cpp`, oscardata `receivefile.cs`, gr-satellites

- The file is preceded by a 55-byte header: 50 bytes file name (NUL
  padded), 2 bytes **file ID = CRC-16 (as above) over the file's bytes**,
  3 bytes file size, MSB first. Header + file are cut into 219-byte
  payloads: the first frame holds the header and the first **164** bytes,
  the others 219, the last padded with zeros. Status: 0 first, 1 next,
  2 last, 3 single (header + file fit one frame). The frame counter
  numbers the blocks from 0.
  - The wiki's filetx page says the ID is "CRC16 of the file name" and
    the first frame holds "163 bytes"; the source (filesend.cpp,
    `Crc16_messagecalc(CRC16FILETX, filearray + 55, len)`) and EA4GPZ's
    receiver (offset 164) agree with each other, so they are followed.
  - `prepare_filesend()` has `if (namelen > 50) len = 50;` - it clips
    the file length, not the name, for names over 50 characters (a bug;
    the beacon's names are short) **[read in source]**.
- **Types 3, 4, 5 are ZIP archives** (miniz, default level) holding one
  member whose name is the file's name; the header's name and size are
  the ZIP's. **Type 2 (image) is the JPEG itself**, not zipped. The wiki:
  "images have to be sent as JPG files with a resolution of max. 640 x
  480 pixel" (a limit of oscardata's GUI).
- The beacon names files by extension (`sendFile()`): `.html/.htm` → 4,
  `.blt/.txt` → 3, `.jpg` → 2, anything else → 5.
- oscardata keeps the blocks of an incomplete file (by its ID) and fills
  gaps from the next transmission (`receivefile.cs`); NB does the same.

### External data (type 8) - `extdata.cpp`; ams_extension.cpp

Payload byte 0 is the stream type:

| Byte 0 | Stream | Format |
|---|---|---|
| 0 | **DX cluster** | byte 1: the length of the telnet line it came from (not of what follows, ams_extension.cpp `FormatAndSendMessage`); from byte 2 a NUL-terminated string `reporter~qrg~dxcall~message~utctime~qthloc`, fields cut from fixed columns of the cluster's "DX de" line (6-14, 14-26, 26-39, 39-70, 70-76, 76-80) and trimmed, each truncated (`%.20s`, `%.40s` for the message). Source cluster: `dx.w1nr.net:23`, logged in as DK0SB. The frequency is the cluster's, in kHz (e.g. `10489500.0`) **[read in source]**; whether the live beacon still uses that cluster is **[unverified]** |
| 1 | **NB spectrum** | 275 values of 6 bits, packed LSB first from byte 1. Made from 550 16-bit levels at 1 kHz steps; the pair maximum kept (2 kHz steps); scaled so the lower beacon (levels 24-26) is 63. The code's comment puts the first raw level at 10489.475 MHz with the lower beacon at index 25, so value k covers 10489.475 + 2k ... +2k+1 kHz; the comment above the receiver says "10489.525 - 10490.025" - the frequency axis is **[unverified]** (follow the code: 10489.475 + 2k kHz) |
| 2 | **CW skimmer** | byte 0 = 2 and then the feeding program's bytes, zero padded to 219. The feeding program is not in either repository; its format is **[unverified]**. NB shows its printable text |
| 3 | **WB spectrum** | 266 values of 6 bits, packed as above, 30 kHz steps from 10491.500 MHz; levels have 350 subtracted before scaling to the left beacon (indices 0-16) |
| 25 | "generic data" | passed to the web socket as is |

A DX or CW frame identical to the previous one is dropped by HSmodem's
receiver (`ext_modemRX`); NB does the same.

What HSmodem does with them: forwards them to a web socket on port 40134
(the 219-byte payload, after a 3-byte header in `ws_build_txframe`), where
the beacon's `qo100info.html` (transmitted as a type-4 file) draws them.
That page's script is the only full description of the CW-skimmer
format; I found no copy of it published **[unverified]**.

## 6. Verification - HSmodem's own code against ohsdigi

`rust/ohsdigi/harness/hsmodem/build.sh` fetches the AMSAT-DL tree at the
commit above and compiles HSmodem's `frame_packer.cpp`, `constellation.cpp`,
`scrambler.cpp`, `crc16.cpp`, `fec.cpp` (Schifra), `symboltracker.cpp`
and `liquid_if.cpp` **unchanged** with a small driver (`hsh.cpp`) in a
rust:1-bookworm container, linked against the `libliquid.so` HSmodem
ships - so the DSP is HSmodem users' own binary. `hsh_ams` is the same
with `-DAMS_TESTMODE`, the beacon's build. `compare.py` drives it and
ohsdigi's `examples/hsdev.rs` with identical inputs. Results on shack,
06/10/2026 **[measured]**:

| Stage | Result |
|---|---|
| `Pack()`: header, counter rules, CRC, Schifra parity, scrambling | 20 random specs (files of every type, repeats, type-8 frames): **byte-identical** |
| RS decoder vs Schifra's | 4000 HSmodem codewords with 0-24 random byte errors: same success/failure on **4000/4000**, same data on all 2763 corrected; both correct every pattern of <= 16 errors and none of 17+ |
| Symbols (beacon build: what goes to the Pluto driver) | max difference 5e-7 |
| Sound-card TX audio (48 kHz) | max difference 1.4e-6 of peak |
| Receive, audio path (HSmodem's TX audio + noise + offset 0, +3, -5 Hz; Es/N0 30-10 dB; 21 s, 74 frames) | **hard symbols 100 %** identical at 16 dB and above, >= 99.91 % at 12-14 dB; soft symbols (equaliser output) differ by ~1e-3 median; symbol timing (tau) and AGC gain agree to ~3e-3; carrier NCO within 0.2 Hz (1 Hz at 12 dB); **the same frames, found at the same symbol, every case**; header hits that failed RS identical in count. At 10 dB both lose lock and decode nothing; past a carrier slip the two trajectories diverge, as chaotic loops do |
| Receive, IQ path (the same tracker on complex baseband at 9600 S/s) | the same: 100 % hard symbols at >= 16 dB, same frames in every case (76/76, 73/73, 74/74) |

The small float differences are liquid's C (its own summation order,
libm, and `conj()` in double) against Rust's single precision; every
decision taken from them agrees. A compact corpus (4 s of IQ made by
HSmodem's transmitter, HSmodem's hard symbols and frames for it, and
`Pack()` output for a spec) is in `rust/ohsdigi/testdata/hsmodem/`;
`rust/ohsdigi/tests/hsmodem.rs` replays it on every `cargo test`.

**What ohsdigi adds**, both switchable off: a resampler (NB's channel is not
at 9600 S/s), and coarse frequency acquisition - HSmodem's carrier loop
pulls in about +-20 Hz (+-30 Hz loses frames) **[measured]**, and HSmodem's
user tunes by hand. NB estimates the residual from the 7th power of the
outer-ring soft symbols when nothing decodes, over +-171 Hz. The 7th power
folds every 2400/7 = 342.9 Hz: a carrier that far off turns each symbol by
exactly one outer-ring point, so the constellation looks perfect and
nothing decodes. The correction is therefore kept within +-171 Hz of the
tuned frequency (beacon lock leaves less than that), and NB restarts the
receiver when rxCorr jumps by more than 40 Hz. Both were found on NB's
simulator (the search, chasing noise before beacon lock, had walked onto
the fold) and have tests in `tests/hsmodem.rs`.

On NB's simulator end to end (its beacon framed and modulated by ohsdigi,
received from the wide IQ while tuned elsewhere), with the band full and
the LNB drifting: 273 frames in 80 s, none lost, MER about 22 dB - after
a fix to NB's filter bank, whose channels jumped pi/4 in phase whenever
beacon lock moved one across a 50 Hz bin boundary (two frames lost at
each crossing before).
Sensitivity (ohsdigi, our own test signal): every frame down to Es/N0 12
dB, 7 of 80 at 11 dB, none at 10 dB **[measured]** - the same cliff as
HSmodem in the comparison above. HSmodem's techdata page reports a minimum
of "+17 dB" SNR for 8APSK-6000 on air with a 40 cm dish; its SNR is
measured differently **[unverified how]**.

## 7. What needs the real beacon (Ray)

1. That the beacon decodes at all with NB: the Pluto driver's pulse
   shaping and level are unpublished; EA4GPZ's RRC 0.2 is the evidence.
2. Its frequency: 10489.995 vs the "zero beat" figure (section 3); NB's
   status shows the frequency its acquisition settled on.
3. Which streams it carries today, and whether pictures appear.
4. The CW-skimmer format, and the NB spectrum's frequency axis.
5. Whether frames repeat (section 3, "Repeats"), and how often each
   bulletin comes round.
6. Decode margin on a typical station (EA4GPZ: S/N "around 20 dB ... no
   bit errors").

## 8. Station to station (07/10)

The "hsmodem" mode in NB (ohscore/modes/hsmodem.py Encoder/Decoder, ohsdigi's
speed.rs, modulator.rs ssb_audio, receiver.rs Receiver::ssb).

### Speeds - `hsmodem.cpp` sr[] **[read in source]**

| Mode | Audio rate | TX interp. | RX decim. | Bits | Line speed | GUI label (oscardata Form1.Designer.cs) |
|---|---|---|---|---|---|---|
| 0 | 48000 | 40 | 10 | 1 (BPSK) | 1200 | "1200 BPSK BW: 1300 Hz" |
| 1 | 48000 | 20 | 5 | 1 | 2400 | "2400 BPSK BW: 2500 Hz" |
| 2 | 48000 | 32 | 8 | 2 (QPSK) | 3000 | "3000 QPSK BW: 1700 Hz" |
| 3 | 48000 | 24 | 6 | 2 | 4000 | "4000 QPSK BW: 2400 Hz" |
| 4 | 44100 | 20 | 5 | 2 | 4410 | "4410 QPSK BW: 2500 Hz (QO-100 Standard)" - the GUI's default |
| 5 | 48000 | 20 | 5 | 2 | 4800 | "4800 QPSK BW: 2700 Hz" |
| 6 | 44100 | 24 | 6 | 3 (8APSK) | 5500 | "5500 8APSK BW: 2300 Hz" |
| 7 | 48000 | 24 | 6 | 3 | 6000 | "6000 8APSK BW: 2500 Hz (QO-100 Transceiver)" |
| 8 | 44100 | 20 | 5 | 3 | 6600 | "6600 8APSK BW: 2600 Hz" |
| 9 | 48000 | 20 | 5 | 3 | 7200 | "7200 8APSK BW: 2700 Hz (QO-100 SDR)" |

Mode 10 is RTTY, not this modem. `getMod()` (liquid_if.cpp): 1 bit BPSK,
2 QPSK, 3 `LIQUID_MODEM_APSK8` - the table's comment says "8PSK", the
modem is the beacon's 1+7 APSK. Symbol rate = audio / TX interpolation;
the tracker always gets four samples a symbol. The QPSK modes XOR each
symbol with itself shifted right before liquid's modulator (`_sendToModulator`)
and after the demodulator. The same RRC (beta 0.2, 15 symbols) at every
speed. HSmodem does not detect a sender's speed: both GUIs are set alike.

**Occupied width [measured]**, as NB's engine measures every send (99.5 %
of the power, Engine._occupied), most of five contents, +20 Hz:
1200 1.34 kHz, 2400 2.66, 3000 1.68, 4000 2.23, 4410 2.46, 4800 2.68,
5500 2.07, 6000 2.25, 6600 2.48, 7200 2.69 (ohsnb/bandplan.py
HSMODEM_WIDTH). Edge to edge an RRC 0.2 is 1.2 Rs - 2.88 kHz at 2400 Bd -
but the last 0.5 % of the power is in that roll-off. All ten fit QO-100's
2.7 kHz by that measure, and DJ0ABR's own labels agree, so NB offers all
ten; the default is the GUI's "QO-100 Standard", 4410 QPSK.

### What one transmission is **[read in source]**

The GUI (ArraySend.cs) hands the modem one 219-byte payload at a time with
type and status (first/next/last/single), in the 55-byte-header format of
section 5; files other than pictures are zipped first (oscardata's
ZipStorer: .NET System.IO.Compression), pictures are JPEGs. hsmodem.cpp's
handling of each (`GRdata_rxdata` side: the UDP handler, `toGR_sendData`,
`modem_sendPSKData`, `sendStationInfo`):

- first or single frame: `sendAnnouncement()` (a spoken announcement, only
  if configured), the frame with `repeat=5` - sent once, then, the sound
  card not playing yet, `6 * ((caprate / txinterpolfactor) * bits / 8) /
  258 + 1` more (13 at 4410, 21 at 7200: about six seconds - the preamble);
  then `sendStationInfo()`: type 7, status 1, as a repeat, twice (call 20
  bytes, locator 10, name 20);
- next frames once; the last with `repeat=5` while playing: six in all.

Repeats keep the frame counter (Pack()); the receiving GUI (receivefile.cs)
numbers blocks by the counter and keeps blocks per file ID across sends.
**Pictures** (Form1.cs `prepareImage`): resized to the chosen resolution
(160x120 ... 640x480) and saved as JPEG at quality 100, 95, ... until it
fits a budget - 12000, 22500, 45000 or 90000 bytes for "low, 30s" ...
"very high, 4min", divided by 640/width.
**Marker**: HSmodem adds its 100 Hz tuning tone (tuning.cpp, a quarter of
full scale) when `marker` is on - 1 by default in hsmodem.cpp, set by the
GUI. NB sends none (it is outside the modem, and widens the signal to
100 Hz above the dial); NB receives HSmodem with it on (below).

### Verification **[measured]**

`harness/hsmodem/hsh.cpp` takes `HSH_SPEED`: HSmodem's modulator and
receiver files, unchanged, run at any mode with the libliquid HSmodem
ships. `compare.py speeds` sends a file transfer of each mode's frames
(first frame repeated, middle once, last repeated) both ways:

| Mode | HSmodem TX -> NB RX (Es/N0 60 dB / noisy + off tune) | NB TX -> HSmodem RX (60 dB / noisy) | Pack() |
|---|---|---|---|
| 0-9 | every frame, every mode | every frame, every mode | byte-identical |

"Noisy" is Es/N0 10 dB (BPSK), 13 (QPSK), 19 (8APSK), HSmodem's signal 0.3
of NB's search span off tune (HSmodem's receiver has no AFC; NB's signal
reached it on tune, 3 dB stronger). With `HSH_MARKER=1` (HSmodem's 100 Hz
marker on) NB still decodes every frame at every mode, noisy. NB's chain
in these runs is the one the engine uses: HSmodem's audio resampled to
12 kHz, `Receiver::ssb` (mix down from 1500 Hz, low-pass, resample to four
samples a symbol, the coarse search at the Mth power: 7th 8APSK, 4th QPSK,
square BPSK, span Rs/M) and HSmodem's tracker and deframer.

One finding: NB's signal preceded by 200 symbols of digital silence
reached HSmodem's receiver clean, and it locked only after its 5 s
watchdog reset (frames from symbol 12615 instead of 1062 at mode 4); with
any noise, or no lead-in, at once. NB sends no lead-in (HSmodem sends
none); over a radio there is always noise.

`testdata/hsmodem/speed4-*` is 2.3 s of HSmodem's own mode-4 sound-card
audio for a three-block transfer; `tests/hsmodem_speeds.rs` decodes it
through NB's path on every `cargo test`.

ZIP: a ZIP made by NB (Python's zipfile) opened and extracted by .NET's
System.IO.Compression.ZipFile, as oscardata's zip.cs does, on Windows 11
(the test virtual machine, .NET 4.0.30319.42000, PowerShell 5.1): identical bytes; a ZIP made
there with `CreateEntryFromFile`, as oscardata zips an outgoing file, read
by NB's `unzip_one`: identical bytes.

Sensitivity, NB to NB (`examples/hsspeeds`, white noise, no offset): every
frame down to Es/N0 8 (1200), 7 (2400), 11 (3000), 10 (4000), 10 (4410),
9 (4800), 12 (5500), 13 (6000-7200) dB - as SNR in 2.5 kHz: 4.8, 6.8, 8.8,
9.0, 9.5, 8.8, 10.7, 12.0, 12.5, 12.8 dB. 120 Hz off tune costs 0-2 dB.

NB to NB through the simulator (two engines on one transponder,
tests/test_hsmodem_link.py): a 6 kB JPEG and a 1.2 kB text file byte for
byte at 4410 and 2400, the sender at TX gain -27 dB (7 dB under the
beacon by the simulator's reference; 13 dB under as NB's own-signal
measurement reads a 2.4 kHz signal against the beacon): MER 13.0 dB
(4410, 3.0 dB over its cliff) and 12.5 dB (2400, 5.5 dB over). At -20.5
dB (about 6.5 dB under as measured - the level guard's margin): 4410 MER
19, 7200 MER 18 - 9 and 5 dB over their cliffs. TX lock found the
sender's 25 Hz uplink error from the HSmodem signal, and the level guard
trimmed an HSmodem transmission sent too strong.

### Not proven

1. **DJ0ABR's Windows program itself** (hsmodem.exe + oscardata.exe) has
   not been run: the Windows test machine has no sound device (Win32_SoundDevice is empty)
   and hsmodem.exe will not modulate without a playback device; a virtual
   audio cable is a system-wide driver install, which was not to be done.
   What that leaves unexercised is the program around the modem: its
   sound-card I/O (libkmaudio), hsmodem.cpp's glue (read, not run - the
   repetition count, the station frame), and oscardata's file assembly and
   display (read; its ZIP library checked as above). A run with a virtual
   cable, or a Linux hsmodem against a loopback sound device, would close it.
2. **On air** with a real HSmodem station: level, the transponder's own
   filtering and drift over a long file, and whether stations really use
   4410 by default.
3. HSmodem's FFT-triggered receiver reset (fft.cpp) is not ported; NB's
   coarse search and the watchdog cover acquisition instead.
