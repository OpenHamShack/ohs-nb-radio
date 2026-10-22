# Digital modes in Rust: ohsdigi

FT8 and FT4 move from WSJT-X's command-line tools to our own implementation,
in Rust, called from Python as an extension module (Brian, 06/10/2026). More
modes are to follow - JS8 first - so the crate is laid out for them. This
document is the design: what the crate is, why it is shaped as it is, how
Python uses it, how it is built and shipped, and what phase 2 (the decoder)
builds on.

**Phase 1, done:** the encoders, the crate, its packaging and its use by
`ohscore/modes/ft8.py`.
**Phase 2, done:** the decoder (its own section, below). **Since 07/10/2026
ohsdigi is NB's and HAM's FT8/FT4 decoder**; jt9 is the fallback and the
shadow ("In the app", below).
**JS8, done 10/10/2026:** modem, decoder and message layer, ported from
JS8Call 2.2.0 ("JS8", below); NB and Radio decode JS8 with it, js8 as
fallback. **Q65, done 10/10/2026:** codec, encoder and decoder, ported from
WSJT-X 2.7.0 ("Q65", below); NB decodes and sends Q65 with it, jt9 and
q65code as fallback.

## Sources

- **WSJT-X 2.7.0** - the version the Windows bundle already carries and the
  one Debian ships - is the specification and the test reference:
  `/srv/source-site/files/wsjtx-2.7.0.tgz` (sha256 `3788f5df…ec93`).
  The encoder follows `lib/77bit/packjt77.f90`, `lib/chkcall.f90`,
  `lib/fmtmsg.f90`, `lib/ft8/{genft8,encode174_91,gen_ft8wave,ldpc_174_91_c_generator}.f90`,
  `lib/ft4/{genft4,gen_ft4wave}.f90`, `lib/gfsk_pulse.f90` and `lib/crc14.cpp`.
  WSJT-X is GPL-3.0-or-later, as we are; every ported file keeps its
  copyright (Joe Taylor K1JT, Steve Franke K9AN, Bill Somerville G4WJS, Nico
  Palermo IV3NWV and the WSJT Development Group) and names the WSJT-X files
  it follows.
- **ft8_lib** (Karlis Goba, MIT) was available as a clearer second reading;
  where the two differ, WSJT-X wins, because WSJT-X is what is on the air.
- **JS8Call** (GPL-3.0), read only far enough to shape the module boundaries:
  v2.2.0 (`lib/js8/genjs8.f90`, `lib/js8/js8*_params.f90`, `lib/crc12.cpp`,
  `lib/ft8/ldpc_174_87_params.f90`, `varicode.cpp`) and v2.3.1 (`JS8.cpp`,
  `JS8.hpp`, `JS8Submode.cpp`, `Modulator.cpp`, `commons.h`), from
  github.com/js8call/js8call. JS8 is now ported from 2.2.0 (Debian's
  js8call_2.2.0+ds source package, the code its `js8` binary is built
  from); see "JS8" below for the files.

## What the protocols share (and what they do not)

| Layer | FT8 | FT4 | JS8 (from its source) |
| --- | --- | --- | --- |
| Payload | 77 bits, pack77 | the same 77 bits | 75 bits: 72 (twelve 6-bit characters) + a 3-bit frame type; its own packing (varicode, Huffman, "JSC" word compression); no pack77 |
| CRC | CRC-14, poly 0x2757, augmented | the same | CRC-12, poly 0xC06, augmented, then XOR 42 (`crc12.cpp`, `JS8::CRC12`) |
| FEC | LDPC (174,91) | the same | LDPC (174,87) - the WSJT-X 1.x FT8 code; JS8's `ldpc_174_87_params.f90` is byte-identical to WSJT-X 2.7.0's |
| Scrambling | none | payload XOR rvec | none |
| Bits to tones | 3 bits, Gray `0,1,3,2,5,6,4,7` | 2 bits, Gray `0,1,3,2` | 3 bits, no Gray |
| Sync | Costas `3,1,4,0,6,5,2` at 0, 36, 72 | four 4x4 Costas arrays at 0, 33, 66, 99 | 7x7 Costas at 0, 36, 72: "original" `4,2,5,6,1,3,0` thrice (Normal) or three different arrays (Fast, Turbo, Slow) |
| Symbols | 79 x 1920 samples, 6.25 Hz | 103 (+2 ramp) x 576, 20.83 Hz | 79; 1920/1200/600/3840 samples by submode, spacing = baud |
| Shaping | GFSK, BT 2 | GFSK, BT 1, whole-symbol ramps | plain continuous-phase FSK |

So the boundaries follow the layers, not the modes:

```
rust/ohsdigi/src/
  lib.rs          Mode, encode(); the crate's front door
  fortran.rs      Fortran semantics pack77 depends on (private)
  msg77/          the 77-bit payload: pack77, unpack77, CallHashes
    callsign.rs   pack28/unpack28, chkcall
    hash.rs       the 10/12/22-bit hash tables (save_hash_call, hash10/12/22)
    text.rs       free text, base 42
    tables.rs     ARRL sections, RTTY Roundup multipliers
  crc.rs          crc_augmented(bits, width, poly); crc14, crc14_ok
  ldpc/           one module of tables (and an encoder) per code
    ldpc174_91.rs GENERATOR, encode()
  ft8.rs          FT8's frame: COSTAS, GRAY, tones(payload)
  ft4.rs          FT4's frame: COSTAS, GRAY, RVEC, scramble(), tones(payload)
  gfsk.rs         gfsk_pulse, ft8_waveform, ft4_waveform
  python.rs       the PyO3 module (feature "python")
```

- **msg77** is what FT8, FT4 (and in WSJT-X FST4, Q65, MSK144) share. A JS8
  message layer would be a sibling (`js8msg/`), not a variant of it.
- **crc** is one function over bits for any width and polynomial; JS8's
  CRC-12 is `crc_augmented(bits, 12, 0xC06) ^ 42`.
- **ldpc** holds codes, not modes. JS8 adds `ldpc174_87.rs` (the tables
  WSJT-X 2.7.0 still ships). A belief-propagation decoder needs only a
  code's parity-check tables (N, K, the Mn/Nm lists), so one decoder serves
  both codes.
- **ft8 / ft4** are the frames: sync arrays, Gray map, scrambling, symbol
  layout - small, and per mode. JS8 would be `js8.rs` with its submode table
  (Costas set, samples per symbol) and no Gray map.
- **gfsk** builds audio from tones with a pulse and BT given; JS8's
  unshaped FSK is the same integrator with no pulse.

Constants other code needs (the Costas arrays, `RVEC`, the generator rows,
`crc14_ok`, `unpack77` and `CallHashes`) are plain `pub` items, so a decoder
uses them as the encoder does.

## JS8

`src/js8/` is a port of JS8Call 2.2.0, held to JS8Call's own code at every
layer (`tests/js8_golden.rs`). Where the plan above guessed at the layout,
the port differs: JS8's (174,87) LDPC lives in `js8/ldpc.rs` with its own
BP and OSD, because WSJT-X 1.9's decoders (which JS8Call kept) differ from
2.7.0's in more than tables - no a-priori mask, another early stop, and
OSD's second pre-processing rule, which JS8 reaches at its usual depth.

| File | Ports (JS8Call 2.2.0) | Held to |
| --- | --- | --- |
| `js8/mod.rs` | `genjs8.f90`, `js8{a,b,c,e,i}_params.f90`, `crc12.cpp`, `Modulator.cpp` | tones for 300 random frames = `genjs8` compiled unchanged (`harness/js8/js8gen`) |
| `js8/ldpc.rs`, `ldpc_tables.rs` | `encode174.f90`, `bpdecode174.f90`, `osd174.f90`, `ldpc_174_87_params.f90` | (through the decoder below) |
| `js8/decode.rs` | `js8a_decode.f90`, `syncjs8.f90`, `baselinejs8.f90`, `js8_downsample.f90`, `syncjs8d.f90`, `js8dec.f90`, `subtractjs8.f90`, `genjs8refsig.f90` | the same lines as `js8 -8 -b <x> -d 3` (frame, header, SNR, DT, frequency, order): 574 decodes in 200 crowded slots of our audio, all five speeds; JS8Call's own recording `A_2_9.wav` |
| `js8/varicode.rs` | `varicode.cpp`, `decodedtext.cpp` | `buildMessageFrames` and `DecodedText` compiled unchanged against Qt 5 (`harness/js8/varicodeh`): 910 texts, 2 952 random frames |
| `js8/jsc.rs`, `jsc.bin.gz` | `jsc.cpp`, `jsc_map.cpp` (`jsc_list.cpp` rebuilt and checked by `harness/gen_js8_tables.py`) | as varicode |

Quirks are ported, not fixed (each is marked in the source): syncjs8d's
third Costas reference takes the first one's phase and its bounds check
never sees the end array of a signal starting after 0 s; js8dec's buffer
length differs from the downsampler's; the per-speed SNR offsets live in
five otherwise identical files; on lower-case text JS8Call's frame builder
never returns (ours returns an error). Within a pass the candidates are
decoded in parallel, which is exact: js8dec reads the audio only through
the pass's one long FFT.

Sensitivity is JS8Call's by construction - the decodes are line-for-line
the same - and was measured anyway: Normal at depth 3, 40 random frames
per dB in white noise (SNR in 2500 Hz), both decoders gave 0/40 at
-22 dB, 2/40 at -21, 29/40 at -20 and 40/40 from -19 up. A period takes
about 0.1 s at depth 3 on ohs-dev.

Python: `js8_decode`, `js8_unpack`, `js8_frames`, `js8_encode_audio`,
`js8_tones`, `JS8_SUBMODES` (docs/OHSDIGI-PYTHON.md). In the apps,
`ohscore/modes/js8.py` decodes Normal with it (js8 as fallback) and reads
every frame as JS8Call shows it; sending stays off until Brian says.

Development: `examples/js8dev.rs` (decode WAVs in js8's format, write
test slots, noise sweeps, answer `varicodeh`'s protocol); the reference
tools build with `harness/js8/build.sh <js8call source> <workdir>` in the
same gfortran container as the FT8 harness (plus Qt 5 for varicodeh).
JS8Call's `js8` itself is Debian's (`apt install js8call`), on shack.

## Q65

`src/q65/` is a port of WSJT-X 2.7.0's Q65, held to WSJT-X itself
(`tests/q65_golden.rs`). Its 77-bit messages are FT8's (`msg77`, unchanged);
what is new is the codec and the decoder.

| File | Ports (WSJT-X 2.7.0) | Held to |
| --- | --- | --- |
| `q65/mod.rs` | `lib/qra/q65/genq65.f90` (including its RR73 rewrite), the tone spacing and start delay from `widgets/mainwindow.cpp`, the waveform from `Modulator/Modulator.cpp` | tones for 89 messages = `q65code` |
| `q65/qra.rs`, `tables.rs` | `lib/qra/q65/q65.c`, `qracodes.c`, `npfwht.c`, `pdmath.c`, `qra15_65_64_irr_e23.c`, `fadenlorentz.c` (tables by `harness/gen_q65_tables.py`) | (through the decoder) |
| `q65/decode.rs` | `lib/q65_decode.f90`, `lib/qra/q65/q65.f90`, `q65_loops.f90`, `q65_set_list.f90`, `q65_ap.f90`, `lib/spec64.f90`, `ana64.f90`, `twkfreq.f90`, `smo121.f90` | the lines `jt9 -3` prints (text, SNR, DT, frequency, "q" flag, order) |

Evidence, all against Debian's wsjtx 2.7.0 on shack:

- **WSJT-X's audio, our decoder:** 224 periods from WSJT-X's own `q65sim`
  - Q65-15A, -30A and -60A without fading, -60A with 2 Hz, -120B with
  5 Hz, -60C with 20 Hz and -60D with 50 Hz Doppler spread, -28 to -10 dB,
  depth 3 - decode to the same 176 lines as jt9, flag for flag (one
  15 s recording of three stations is in `testdata/q65/`).
- **Our audio, their decoder:** crowded periods made with ohsdigi's
  waveform (`q65::sim::crowded`), 12 per set at 60A depth 1 and 3, 15A,
  30B depth 2, 120C, 60D depth 3, 300A and (8) 60E: 133 decodes, the same
  lines as jt9 (the test regenerates the first few of each set from their
  seeds and compares with `testdata/q65/jt9-batch.txt`). Q65-15E, whose
  65 tones are wider than the 6 kHz it is demodulated at, decodes nothing
  in either.
- **Sensitivity:** Q65-60A at depth 1, 20 random messages per dB near
  1500 Hz in white noise (SNR in 2500 Hz): both decoders 0/20 at -29 dB,
  1/20 at -28, 10/20 at -27, 15/20 at -26, 18/20 at -25, 19/20 at -24,
  20/20 at -23 - the same files, the same decodes.

Two details matter for matching jt9. jt9's own defaults when `-c`/`-x`/
`-g` are not given are MyCall K1ABC, DxCall W9XYZ and DX grid EN37, so a
plain `jt9 -3` runs the "q3" list decode (206 likely replies to W9XYZ);
`Q65Params::jt9` has the same, and the Python call defaults to no calls
instead. And for 60 s periods jt9 sets an "EME delay" of 2.5 s, which
widens the time search to +5.5 s; `q65_decode` does the same unless told
otherwise.

Not ported, because `jt9` run on one WAV never reaches it: averaging
over periods, the NA VHF contest caller list, the drift search and
"decode again". The quirks it does reach are ported and marked (the
a-priori mask a skipped pass leaves behind, `lagpk` carried between
frequency bins, `spec64`'s uneven passband smoothing).

Speed: about 0.6 s for a Q65-60A period at depth 1 on ohs-dev, up to
3 s at depth 3 on a wide submode with nothing to find (the search loops
are serial, as in the Fortran).

Python: `q65_decode`, `q65_encode`, `q65_encode_audio`, `Q65_PERIODS`
(docs/OHSDIGI-PYTHON.md). In the apps, `ohscore/modes/q65.py` decodes and
sends Q65-60A with it (jt9/q65code as fallback), and the engine now
starts a Q65-60 transmission 1 s into its period, as WSJT-X does (it was
0.5 s, DT -0.5 at every receiver).

Development: `examples/q65dev.rs` (tones, test periods, decodes in jt9's
format, sweeps); `jt9`, `q65code` and `q65sim` themselves are Debian's
wsjtx on shack.

## Bit-exact with WSJT-X

### The port

Which message type a line of text becomes is decided by trying each packer
in a fixed order - DXpedition, Field Day, telemetry, WSPR, standard,
RTTY Roundup, nonstandard, EU VHF, then free text - each with its own idea
of a callsign, a report or a grid. Much of that behaviour is Fortran's,
not the algorithm's: CHARACTER*13 words that truncate and blank-pad,
list-directed READs that accept `+5,` and `-5/` but not `+5;` or `+5.`, Z
input that reads `+07` as telemetry 7, B edit descriptors that print
asterisks when a value overflows its field (which WSJT-X then cannot read
back: "*** bad message ***"). `fortran.rs` writes those semantics once, and
`msg77` follows packjt77.f90's structure closely - same functions, same
order, same fall-throughs - with idiom kept for the parts with one obvious
meaning (bit fields, base-N arithmetic, tables). Encoding a message
reproduces ft8code/ft4code end to end: their 37-character argument, fmtmsg,
a fresh hash table per message, pack77 then unpack77 "as sent", and, for
FT4, ft4code's double pack (the second after genft4 strips leading blanks).

The waveform is gen_ft8wave / gen_ft4wave in **single precision**, step for
step. In double precision it differed from WSJT-X's by up to 75/32767 of
full scale by the end of an FT8 transmission: WSJT-X's f32 phase increments
carry a slow drift of their own. In f32 it matches WSJT-X's ft8sim output to
3.6/32767, the rounding of ft8sim's 65 536-entry sine table.

### The test

`tools/digi-corpus.py` runs WSJT-X's own ft8code and ft4code (Debian's
2.7.0+repack-1) on WSJT-X's examples (`ft8code -T`, `ft4code -t`), a fixed
list of edge cases found while porting, and seeded generated messages
covering every type and its edges (reports out of range, every ARRL
section and RTTY multiplier, compound and hashed calls, telemetry around
2^23, WSPR forms, spacing and case, over-long words and messages) plus
random combinations of awkward tokens. It records, for each message and
mode, the type, the "as received" text, the 77 bits and the channel symbols
- or that WSJT-X refused it, or crashed on it.

The committed corpus (`rust/ohsdigi/testdata/wsjtx-2.7.0-ft8-ft4.tsv.gz`,
6,111 messages, 620 KB) is checked by `cargo test` (`tests/corpus.rs`) and,
through the installed binary, by `tests/test_ohsdigi.py`, so neither needs
WSJT-X. Result: **11,967 of the 12,222 encodings (6,111 messages x FT8 and
FT4) identical in every field; the other 255 are messages for which WSJT-X
has no single answer** (next section). A 146,090-message fuzz run
(`--count 150000 --seed 7`, checked with `OHSDIGI_EXTRA_CORPUS`): 285,775
identical, 6,405 undefined in WSJT-X, no difference.

### Where WSJT-X has no answer

In a few places packjt77.f90 reads a variable it never set. The result is
whatever was in memory: ft8code and ft4code disagree for the same message,
and the bits can be garbage (`<...> ZZZZZZZZZ/`). There is nothing to
reproduce, so ohsdigi refuses these (`EncodeError::Undefined`, a
`BadMessage` in Python) rather than send garbage:

- **two unbracketed nonstandard calls** ("W9XYZ PJ4/K1ABC"): pack77_4's
  n12 and c11 (the common one; WSJT-X's own GUI always brackets one call);
- a bracketed call too short to hash ("<AB>"): pack77_4's n12;
- a WSPR-form call with a four-character suffix: pack77_06's npfx;
- an RTTY report read as a null value (","): pack77_3's irpt;
- a three-digit CQ number read as null ("CQ /123 K1ABC"): pack28's nqsy.

One is consistent enough to follow: pack77_3 asks whether an **unset
serial number** is positive when the second-last word is not a 5x9 report,
which decides whether e.g. "K1ABC W9XYZ 73 GL" is tried as an RTTY Roundup
exchange. ft8code always behaves as if it were 0 (so: free text); ft4code
often does not. ohsdigi gives ft8code's answer for both modes and says so
(`Encoded.undefined_in_wsjtx`); the corpus compares FT8 for these and only
counts FT4.

Also reproduced rather than corrected: WSJT-X's own type-5 example,
"<PA3XYZ> <G4ABC/P> R 590003 IO91NP", decodes as "<G4ABC/P> <G4ABC/P> …"
because PA3XYZ and G4ABC/P share the 12-bit hash 3211.

## Python API

The module is `ohscore.ohsdigi` (`ohscore/ohsdigi.abi3.so`, `ohscore\ohsdigi.pyd`).

```python
from ohscore import ohsdigi
ohsdigi.__version__, ohsdigi.WSJTX_VERSION         # "0.2.0", "2.7.0"
e = ohsdigi.encode("ft8", "CQ GM4BRI IO86")       # as ft8code would; raises ohsdigi.BadMessage
e.message, e.sent, e.i3, e.n3, e.type_name       # as read, as it will be received, i3.n3
e.bits                                           # "0001…" (77)
e.tones                                          # bytes: 79 tones 0..7 (FT8), 103 tones 0..3 (FT4)
e.undefined_in_wsjtx                             # None, or which unset WSJT-X variable
e.waveform(f0=1500.0, fs=12000.0)                # bytes, float32 little-endian
ohsdigi.tones("ft4", bits)                        # payload -> symbols
ohsdigi.waveform("ft8", tones, f0, fs)            # symbols -> audio
h = ohsdigi.CallHashes(); h.set_mycall("G4XYZ")   # hash tables kept across messages
ohsdigi.pack77("<PJ4/K1ABC> W9XYZ -11", h)        # -> (bits, i3, n3)
ohsdigi.unpack77(bits, received=True, hashes=h)   # -> (text, ok)
```

- Plain values cross the boundary - str, int, bytes - and no numpy at the
  Rust end: the numpy crate would tie each build to a numpy ABI, and these
  arrays are small enough that one copy costs nothing
  (`np.frombuffer(w, "<f4")` reads the audio without another).
- `BadMessage` is a `ValueError`, which the UI already shows; its text says
  why (bad message, a WSJT-X run-time error, or an undefined result).
- The hash tables are an object the caller owns, not module state as in
  WSJT-X: an encoder starts from empty each time (as ft8code does), a
  decoder keeps one per receiver for the session.
- The Python version is not part of the binary's identity: PyO3's abi3,
  minimum 3.11 - Pi OS bookworm has 3.11, Debian 13 and the Windows bundle
  3.13 - so one build per platform serves them all.

## Threading

Anything that takes real time runs with the GIL released (`Python::detach`):
the waveform today (a few milliseconds), the decoder in phase 2 (tens of
milliseconds a slot), so the radio's other threads - RX, the UI, the
supervisor - keep running meanwhile. The Rust types hold no global state
(the hash tables are passed in), so two decoders - FT8 and FT4, or two
receivers - can run on two threads at once. Python objects that wrap mutable
Rust state (`CallHashes`) are borrow-checked by PyO3 at run time; one
receiver's decoder owns its table.

## Selection and fallback

`ohscore/modes/ft8.py` imports `ohscore.ohsdigi` once, at import time:

- Only `ImportError` means "not here" (an architecture we ship no binary
  for, a source tree with nothing built). A module that loads but is broken
  is not hidden behind the fallback.
- A module following a WSJT-X other than 2.7.0 is not used: jt9 2.7.0 is
  what decodes the other end of every test.
- `ENCODER` says which encoder each mode uses (`ohsdigi`, `ft8code`/`ft4code`,
  or none); `CAN_ENCODE` is "jt9 and an encoder"; `describe_encoder()` is in
  the start-up facts and the diagnostics report ("ft8/ft4 encoder").
- Without ohsdigi, encoding runs ft8code/ft4code and the numpy GFSK
  approximation exactly as before, except that a message WSJT-X answers
  with "*** bad message ***" is now refused on both paths rather than sent
  as all-zero (FT8) or uninitialised (FT4) tones.
- Decoding: ohsdigi where the module has the decoder, jt9 where it does not
  (`describe_decoder()`, "ft8/ft4 decoder" in the facts). The decoder's own
  choice, slot by slot, is under "In the app" below.

## Packaging

| Platform | What ships | Built | Proven |
| --- | --- | --- | --- |
| Linux amd64 | `openhamshack-{nb,ham}_<v>_amd64.deb`, `ohscore/ohsdigi.abi3.so` inside | `tools/build-ohsdigi.sh` (container) | corpus + jt9 round trip on the development machine (Debian 13, Python 3.13); loads and encodes in bookworm's Python 3.11 in the build container; packaged module imported from an extracted .deb (`test_packaging.py`) |
| Linux arm64 | `_arm64.deb` | cross-built in the same container (Debian's aarch64-linux-gnu-gcc) | **builds, links (glibc ≤ 2.34, libgcc_s), packages; never run** - no Pi or arm64 emulation was available |
| Linux, anything else | `_all.deb`, no ohsdigi | - | the fallback path, as every release before |
| Windows x64 | `_internal\ohscore\ohsdigi.pyd` in the installer | cross-built in the same container (mingw-w64); imports only python3.dll and system DLLs | the Windows test VM (Windows 11, Python 3.13), 06/10/2026: the corpus passes through the cross-built .pyd; WSJT-X 2.7.0's jt9.exe decodes its FT8 and FT4 audio for seven message types, with no ft4code anywhere; a full `build-windows.ps1` run froze it into an installer, and the frozen program named ohsdigi in its bundle as its encoder and decoded the simulator's ohsdigi-encoded FT8. That installer was built but not installed |

- **The container** (`rust/build.Containerfile`): `rust:1.98.1-bookworm`
  pinned by digest, plus Debian's aarch64 cross-gcc and mingw-w64. Bookworm
  because a module linked on Debian 13 asks for glibc 2.38+ and will not
  load on Pi OS bookworm (2.36). PyO3 0.29 links Windows modules against
  python3.dll by raw-dylib, so no Windows Python is needed to build one.
- **Reproducible:** `Cargo.lock`, `--locked`, fixed in-container paths,
  registry paths remapped, one codegen unit and LTO. Two clean builds of one
  commit gave identical bytes for all three targets, and no binary names a
  host path. Binaries are never committed; `release.sh` builds them from the
  release commit into `${RELEASES}-build/<pkg>-<v>-ohsdigi/` (beside the
  site, not on it) with their `SHA256SUMS`.
- **Per-architecture .debs** rather than one with every binary inside: dpkg
  refuses the wrong one outright instead of the program silently falling
  back, and nobody downloads a DLL to run on a Pi. `build-deb.sh --arch`
  refuses a module built for another machine, and never ships the developer
  build `--install` leaves in `ohscore/` (linked against the host's glibc).
- **Windows:** `build-windows.ps1 -Ohsdigi` takes the cross-built `.pyd`
  (refusing to build without it - an installer without ohsdigi could not
  send FT4), checks its checksum, runs the test suite (and so the corpus)
  through it, and checks the frozen program reports ohsdigi from inside the
  bundle as its encoder. ft8code.exe stays in the bundle as the fallback.
- **Licences:** ohsdigi is our own source, GPL-3.0-or-later; no third-party
  source is added. Compiled into the module are PyO3, pyo3-ffi, libc,
  once_cell and Rust's standard library (MIT or Apache-2.0; used under MIT),
  and on Windows libgcc and mingw-w64 start-up code.
  `rust/ohsdigi/LICENSE-THIRD-PARTY` has their notices; the Debian copyright
  file and `packaging/windows/THIRD-PARTY.txt` cite them, and the Windows
  bundle carries it as `licences\ohsdigi-LICENSE-THIRD-PARTY.txt`.

Sizes (release builds): Linux amd64 618 KB, arm64 595 KB, Windows 1.26 MB.

**The ohs-ohsdigi wheel (09/10/2026).** For the OpenHamShack apps that are
not the NB/HAM bundles, the same module is also packaged as a pip wheel per
platform - Linux x86_64 and arm64 (manylinux_2_35), Windows x64 and macOS
universal2 - by `tools/build-wheels.sh` with maturin, and gained a small
app API (`decode`, `encode_audio`, `version`) beside the WSJT-X-shaped one.
Both are docs/OHSDIGI-PYTHON.md. The bare-module path above is unchanged.

## Decoder

*Phase 2, built alongside phase 1 and merged onto it. Status, 07/10/2026:
**FT8 (stages 1-6) and FT4 are ported and match WSJT-X 2.7.0** - stage by
stage against WSJT-X's own routines, end to end against `/usr/bin/jt9` on
every simulated slot, and on real QO-100 slots (below) - down to the
decoded text. **ohsdigi is the FT8/FT4 decoder in both apps**; jt9 is the
fallback, and checks ohsdigi's work as the shadow ("In the app").*

### What was built

```
rust/ohsdigi/src/decode/
  mod.rs          layout, what is not ported
  ft8.rs          sync8 (+ get_spectrum_baseline, baseline), ft8_downsample,
                  sync8d, ft8b (fine sync, the four metric sets, regular and
                  a-priori passes, checks, SNR), subtractft8 + gen_ft8wave
                  (complex), and ft8_decode's pass structure - including
                  jt9's file mode (below)
  ft4.rs          getcandidates4 (+ ft4_baseline), ft4_downsample, sync4d,
                  get_ft4_bitmetrics, the AP passes, subtractft4 +
                  gen_ft4wave, ft4_decode's passes
  ldpc.rs         decode174_91 (BP with platanh and the early stop), osd174_91
  ldpc_tables.rs  Mn/Nm/nrw, the parity-check half of the code, generated
                  by harness/gen_ldpc_tables.py from WSJT-X's DATA statements
                  (the generator is phase 1's ldpc::ldpc174_91::GENERATOR)
  ap.rs           a-priori bits from MyCall/DxCall (ft8apset; ft4_decode's)
  util.rs         indexx, shell/pctile, polyfit/determ, Nuttall window,
                  gfsk_pulse (+ a cached table), FFT plans (rustfft)
  sim.rs          deterministic test slots (seeded; ft8sim/ft4sim levels)
  py.rs           ft8_decode / ft4_decode for Python, GIL released
rust/ohsdigi/tests/decode_sim.rs   single and crowded generated slots
rust/ohsdigi/tests/jt9_golden.rs   ten fixed slots + jt9's decodes of them
rust/ohsdigi/harness/              the verification harness (below)
rust/ohsdigi/examples/dev.rs       stage dumps, WAVs, timing (harness's tool)
ohscore/modes/decoder_shadow.py     jt9-beside comparison in the running app
```

Ported, as asked, idiomatically but with WSJT-X's decision rules kept
verbatim, quirks included - because the acceptance test is "decodes what
jt9 decodes", and a cleaner rule that decodes differently would be a
different decoder to validate. The ones worth knowing about are noted in
the code: the unstable `indexx` sort that orders equal-sync candidates;
baseline's abscissa `i - i0` with i0 half the *width*; ft8b's `twkfreq1`
whose result is immediately overwritten (so it is not ported); OSD's
`k+20` pivot search and its "nhardmin > 0" acceptance; subtractft8's
filter centred one sample early; ft8b subtracting a decode *before*
deciding it is a likely false one; and FT4's `napwid`, read uninitialised
by ft4_decode.f90 on a first candidate's regular passes (ohsdigi uses the
80 it is evidently meant to be; it cannot arise at depth 1).

Arithmetic is single precision wherever the Fortran uses default REAL;
baseline/polyfit are double, as there.

**One structural change, exactly equivalent:** within a pass, candidates
are decoded in parallel (rayon) and their signals subtracted afterwards in
candidate order. WSJT-X's ft8b reads audio only through the downsampler's
long FFT, which it computes once per pass (`newdat`) and does not refresh
after a subtraction - so no candidate's decode sees another's subtraction
within a pass, and the parallel form produces identical results. FT4 has
the same property (`dobigfft`).

**jt9's file mode.** NB runs `jt9 -8 -p 15 file.wav`. In file mode jt9
decodes FT8 three times - the slot cut at 41 and 47 half-symbols
(zero-filled), then at 50 - carrying early decodes, their subtraction (with
DT refinement at depth 3) and the dedupe list between calls; at depth 1
only the last call does anything. With no early decodes the final call
decodes the 47-cut audio, a WSJT-X quirk. `Ft8Params::jt9_file_mode`
(default on) reproduces all of it; off, one set of passes on the whole slot.

**jt9's dummy calls.** jt9 has MyCall K1ABC and DxCall W9XYZ unless given
`-c`/`-x` (jt9.f90), and its a-priori passes use them: the first
end-to-end run found exactly one decode jt9 made and ohsdigi did not, "K1ABC
W9XYZ R-09" at -20 dB, marked `a2`. `Ft8Params::jt9()` / `Ft4Params::jt9()`
carry those calls (packed by ft8code); `default()` is the same
configuration without calls. NB used to run jt9 that way, so on the air
its MyCall AP looked for K1ABC; it now passes the operator's call and the
FT8 sequencer's DX call (`-c`/`-x`, quoted so a call with "/" survives
Fortran's list-directed read, and `b` for none), as WSJT-X gives its
decoder (`ohscore/modes/ft8.py`, `_jt9_call`).

Not ported: contest a-priori variants (ncontest 1-8: NA/EU VHF, Field Day,
RTTY Roundup, WW Digi, Fox/Hound, ARRL Digi) - NB has no contest mode -
and ft8_a7 (WSJT-X 2.6's "a7" decodes of last cycle's messages), which
needs state across slots and which jt9, started once per WAV as NB starts
it, never reaches either. osd174_91's second pre-processing rule (npre2)
runs only at OSD depth 3+; FT8 and FT4 call with 2.

### Verification

**The harness** (`rust/ohsdigi/harness/`): `build.sh <workdir>` extracts
WSJT-X 2.7.0 from the archived tarball and compiles its own Fortran - sync8,
ft8b, decode174_91, osd174_91, subtractft8, ft4_decode and everything under
them, plus `crc14.cpp` against Boost and `packjt77` - with gfortran in a
throwaway `rust:1-bookworm` container (the development machine has no gfortran), into `ft8h`.
Only two WSJT-X files are touched, by sed-inserted dump calls: ft8b.f90
(refined sync, the four LLR sets, the sync bail-out, each decode) and
ft4_decode.f90 (candidates, sync search, bit metrics); the numbers dumped
are WSJT-X's own. `examples/dev.rs` writes the same lines from ohsdigi and
`compare.py` sets them side by side:

```
harness/build.sh ~/scratch/hw                       # ~1 min
cargo build --release --example dev                 # in rust/ohsdigi
harness/compare.py ~/scratch/hw stages 10 1         # FT8 stages 1-4, depth 1 (or 3)
harness/compare.py ~/scratch/hw subtract 4          # FT8 stage 5
harness/compare.py ~/scratch/hw ft4 10 1            # FT4 stages
harness/compare.py ~/scratch/hw ap 4                # stage 6, against jt9 -Q 0..5
harness/compare.py ~/scratch/hw e2e ft8 10 1        # vs jt9, SNR sweep
harness/compare.py ~/scratch/hw e2e-nb ft8 6 1      # same, NB's own encoder's audio
harness/compare.py ~/scratch/hw time ft8 10 1
harness/compare.py ~/scratch/hw golden              # regenerate tests/jt9_golden.rs
```

Test audio is ohsdigi's own seeded generator (`sim.rs`): WSJT-X's simulator
levels (SNR in 2500 Hz, x100 into 16-bit), GFSK as gen_ft8wave/gen_ft4wave,
30 real messages packed by ft8code, optional linear drift. The source
tarball has no sample WAVs (WSJT-X ships its samples separately), so none
were used.

### Stage by stage, against WSJT-X's own routines

The last full run (`compare.py stages 10 1|3`, `subtract 4`, `ft4 10 1|3`),
on slots of 18 (FT8) or 12 (FT4) signals from -22 to +2 dB:

```
FT8 stages, depth 1, 10 slots of 18 signals at -22..+2 dB
  stage 1 sync8: candidates WSJT-X 2564 ohsdigi 2564; same position+freq+dt+sync(1e-3): 2564, different 0
  stage 1 baseline sbase: max |diff| 6.00e-06 dB
  stage 2 fine sync on 579 candidates: ibest equal 579, delf equal 579, nsync equal 579; sync bail-outs agree 1985, disagree 0
  stage 3 LLRs (2316 sets): max|diff|/max|llr| median 3.7e-07, 99% 1.1e-06, max 1.7e-06
  stage 4 LDPC on WSJT-X's LLRs: 6948/6948 results identical (nharderror, ntype, 91 bits); dmin max |diff| 0.0e+00
  per-candidate decodes (no subtraction, no AP): WSJT-X 164 ohsdigi 164 both 164
FT8 stages, depth 3, 10 slots of 18 signals at -22..+2 dB
  stage 1 sync8: candidates WSJT-X 4009 ohsdigi 4009; same position+freq+dt+sync(1e-3): 4009, different 0
  stage 1 baseline sbase: max |diff| 6.00e-06 dB
  stage 2 fine sync on 960 candidates: ibest equal 960, delf equal 960, nsync equal 960; sync bail-outs agree 3049, disagree 0
  stage 3 LLRs (3840 sets): max|diff|/max|llr| median 4.2e-07, 99% 1.3e-06, max 1.8e-06
  stage 4 LDPC on WSJT-X's LLRs: 11520/11520 results identical (nharderror, ntype, 91 bits); dmin max |diff| 0.0e+00
  per-candidate decodes (no subtraction, no AP): WSJT-X 166 ohsdigi 166 both 166
FT8 stage 5 subtractft8 (10 signals a slot, alternate ones with DT refinement):
  input rms 191.4, residual rms 99.40; ohsdigi vs WSJT-X: max |diff| 0.011, rms diff 5.79e-04
  input rms 159.5, residual rms 99.28; ohsdigi vs WSJT-X: max |diff| 0.018, rms diff 1.04e-03
  input rms 210.2, residual rms 99.45; ohsdigi vs WSJT-X: max |diff| 0.017, rms diff 6.21e-04
  input rms 212.0, residual rms 99.58; ohsdigi vs WSJT-X: max |diff| 0.015, rms diff 7.72e-04
FT4, depth 1, 10 slots of 12 signals at -18..+2 dB
  candidates WSJT-X 124 ohsdigi 124, same freq(0.01 Hz)+strength(1e-3) 124
  sync search: 144/144 (candidate, segment) pairs with identical ibest and idf
  bit metrics: max|diff|/max median 4.9e-07, max 8.2e-07
  decodes WSJT-X 109 ohsdigi 109 both 109
FT4, depth 3, 10 slots of 12 signals at -18..+2 dB
  candidates WSJT-X 403 ohsdigi 403, same freq(0.01 Hz)+strength(1e-3) 403
  sync search: 424/425 (candidate, segment) pairs with identical ibest and idf
  bit metrics: max|diff|/max median 6.3e-07, max 3.7e-06
  decodes WSJT-X 116 ohsdigi 116 both 116
```

Reading it:

- **Stage 1** (sync8): every candidate identical - position in the list,
  frequency bin, DT step, sync score to 1e-3 - and the noise baseline
  within 6e-6 dB. Order matters (it sets subtraction order), and matches.
- **Stage 2** (downsample, sync8d): the refined time offset, frequency
  tweak and hard sync count are identical for every candidate, and the
  sync bail-outs are the same ones.
- **Stage 3** (ft8b's four metric sets): within 2e-6 of the largest LLR -
  the difference between FFTW and rustfft in single precision.
- **Stage 4** (decode174_91: BP; BP + OSD on channel LLRs; BP + OSD on BP's
  outputs), fed WSJT-X's own LLRs: every result bit-identical, dmin
  included.
- **Stage 5** (subtractft8, with and without DT refinement): residual
  audio within 0.02 of a 16-bit sample unit (rms 1e-3) of WSJT-X's, on
  ~100-unit noise.
- **Stage 6** (a-priori): `compare.py ap` decodes weak signals carrying
  jt9's calls near 1500 Hz at every QSO state (`jt9 -Q 0..5`, which
  selects AP types 1-6), depths 1 and 3, -24 to -20 dB: in every one of
  the 36 configurations, the same messages decoded **with the same AP
  type** (a1-a5 all occurred) as jt9.
- **FT4**: candidates, the coarse/fine sync search and bit metrics agree
  the same way. One (candidate, segment) pair of 425 at depth 3 chose a
  different sync peak - a near-tie between two lags, float noise - and
  went on to the same decodes.
- **Text**: since the merge with phase 1, decodes are unpacked by the
  crate's unpack77: on 72 slots (depth 1 and 3) the decoded text is
  identical to jt9's, line for line.

### Sensitivity, ohsdigi against jt9

Decodes of the transmitted messages, summed over 10 slots per SNR; "jt9
only"/"ours only" are messages one found and the other did not; "false"
counts decodes of messages not sent.

```
FT8 end to end, depth 1: 10 slots per SNR, 12 signals a slot (distinct messages, >=60 Hz apart, DT +-0.8 s, drift +-0.1 Hz/s)
   SNR  sent   jt9 ohsdigi  both jt9 only ours only false jt9 false ours
   -24   120     0      0     0        0         0         0          0
   -22   120     0      0     0        0         0         0          0
   -20   120    70     70    70        0         0         0          0
   -18   120   108    108   108        0         0         0          0
   -16   120   108    108   108        0         0         0          0
   -14   120   115    115   115        0         0         0          0
   -12   120   115    115   115        0         0         0          0
   -10   120   112    112   112        0         0         0          0
    -8   120   120    120   120        0         0         0          0
    -6   120   115    115   115        0         0         0          0
    -4   120   108    108   108        0         0         0          0
    -2   120   118    118   118        0         0         0          0
     0   120   116    116   116        0         0         0          0
     2   120   116    116   116        0         0         0          0
     4   120   113    113   113        0         0         0          0
     6   120   118    118   118        0         0         0          0
     8   120   117    117   117        0         0         0          0
    10   120   118    118   118        0         0         0          0

FT8 end to end, depth 3: 10 slots per SNR, 12 signals a slot (distinct messages, >=60 Hz apart, DT +-0.8 s, drift +-0.1 Hz/s)
   SNR  sent   jt9 ohsdigi  both jt9 only ours only false jt9 false ours
   -24   120     0      0     0        0         0         0          0
   -22   120     2      2     2        0         0         0          0
   -20   120   101    101   101        0         0         0          0
   -18   120   113    113   113        0         0         0          0
   -16   120   116    116   116        0         0         0          0
   -14   120   118    118   118        0         0         0          0
   -12   120   120    120   120        0         0         0          0
   -10   120   119    119   119        0         0         0          0
    -8   120   120    120   120        0         0         0          0
    -6   120   115    115   115        0         0         0          0
    -4   120   116    116   116        0         0         0          0
    -2   120   119    119   119        0         0         0          0
     0   120   119    119   119        0         0         0          0
     2   120   118    118   118        0         0         0          0
     4   120   116    116   116        0         0         0          0
     6   120   120    120   120        0         0         0          0
     8   120   119    119   119        0         0         0          0
    10   120   119    119   119        0         0         1          1

FT4 end to end, depth 1: 10 slots per SNR, 8 signals a slot (distinct messages, >=100 Hz apart, DT +-0.3 s)
   SNR  sent   jt9 ohsdigi  both jt9 only ours only false jt9 false ours
   -20    80     0      0     0        0         0         0          0
   -18    80     8      8     8        0         0         0          0
   -16    80    77     77    77        0         0         0          0
   -14    80    80     80    80        0         0         0          0
   -12    80    80     80    80        0         0         0          0
   -10    80    80     80    80        0         0         0          0
    -8    80    80     80    80        0         0         0          0
    -6    80    80     80    80        0         0         0          0
    -4    80    80     80    80        0         0         0          0
    -2    80    80     80    80        0         0         0          0
     0    80    80     80    80        0         0         0          0
     2    80    80     80    80        0         0         0          0
     4    80    80     80    80        0         0         0          0
     6    80    80     80    80        0         0         0          0
     8    80    80     80    80        0         0         0          0
    10    80    80     80    80        0         0         0          0

FT4 end to end, depth 3: 10 slots per SNR, 8 signals a slot (distinct messages, >=100 Hz apart, DT +-0.3 s)
   SNR  sent   jt9 ohsdigi  both jt9 only ours only false jt9 false ours
   -20    80     0      0     0        0         0         0          0
   -18    80    40     40    40        0         0         0          0
   -16    80    80     80    80        0         0         0          0
   -14    80    80     80    80        0         0         0          0
   -12    80    80     80    80        0         0         0          0
   -10    80    80     80    80        0         0         0          0
    -8    80    80     80    80        0         0         0          0
    -6    80    80     80    80        0         0         0          0
    -4    80    80     80    80        0         0         0          0
    -2    80    80     80    80        0         0         0          0
     0    80    80     80    80        0         0         0          0
     2    80    80     80    80        0         0         0          0
     4    80    80     80    80        0         0         0          0
     6    80    80     80    80        0         0         0          0
     8    80    80     80    80        0         0         0          0
    10    80    80     80    80        0         0         0          0
```

**ohsdigi decoded exactly what jt9 decoded at every SNR, depth and mode:
no message found by only one of them, and the same false decodes (one
each, the same one, at depth 3).** The sensitivity curve is therefore
jt9's: FT8 50 % at about -20 dB at depth 1 (85 % at depth 3), FT4 50 %
at about -17 dB, in WSJT-X's 2500 Hz convention, on these crowded slots.
`tests/jt9_golden.rs` keeps ten of these comparisons as a cargo test.

The losses at high SNR are WSJT-X's own behaviour, reproduced: every one
checked at -4 dB was a signal with |DT| > 0.45 s, which a depth-1 decode
(two passes, BP only) misses.

**NB's own FT8 encoder's audio** (`ohscore.modes.ft8._gfsk_audio`, the
simulator's and - without ohsdigi - the transmitter's) was decoded **about
5 dB worse** than WSJT-X's waveform, by jt9 as much as by ohsdigi: its
Gaussian smoothing (sigma = a quarter symbol) was about four times WSJT-X's
BT = 2 pulse, so neighbouring tones smeared into each other; FT4 was given
BT = 2 as well, not its 1. The tables below are that old waveform. It is
now gen_ft8wave / gen_ft4wave ported to numpy (WSJT-X's gfsk_pulse, BT 2
and 1, its framing and ramps), held by `tests/test_ohsdigi.py` to within
0.02 of full scale of `gfsk::ft8_waveform`/`ft4_waveform` sample by sample
(the residue is single-precision phase drift in WSJT-X's own). Measured
with jt9, one signal a slot, 20 slots per SNR: FT8 is now decoded 50 % of
the time at -20 dB where the old waveform needed about -14.5, and slot for
slot exactly as often as ohsdigi's waveform; FT4 gained about 1 dB.

```
FT8 end to end on NB's own encoder, depth 1: 6 slots per SNR, 12 signals a slot
   SNR  sent   jt9 ohsdigi  both jt9 only ours only
   -24    72     0      0     0        0         0
   -22    72     0      0     0        0         0
   -20    72     0      0     0        0         0
   -18    72     5      5     5        0         0
   -16    72    12     12    12        0         0
   -14    72    46     46    46        0         0
   -12    72    58     58    58        0         0
   -10    72    63     63    63        0         0
    -8    72    68     68    68        0         0
    -6    72    66     66    66        0         0
    -4    72    66     66    66        0         0
    -2    72    70     70    70        0         0
     0    72    70     70    70        0         0
     2    72    70     70    70        0         0

FT4 end to end on NB's own encoder, depth 1: 6 slots per SNR, 8 signals a slot
   SNR  sent   jt9 ohsdigi  both jt9 only ours only
   -20    48     0      0     0        0         0
   -18    48     1      1     1        0         0
   -16    48    32     32    32        0         0
   -14    48    48     48    48        0         0
   -12    48    48     48    48        0         0
   -10    48    48     48    48        0         0
    -8    48    48     48    48        0         0
    -6    48    48     48    48        0         0
    -4    48    48     48    48        0         0
    -2    48    48     48    48        0         0
     0    48    48     48    48        0         0
     2    48    48     48    48        0         0
```

### Speed

The development machine (Ryzen 9 6900HX, 16 threads, load ~1), 10 crowded slots each,
`compare.py time`. jt9's figure is its whole process, as NB pays it (FFTW
wisdom warm); ohsdigi's is the decode call. "One core" is `threads=1`;
"all cores" the default, cores - 1 (15 here).

| | jt9 | ohsdigi, one core | ohsdigi, all cores |
| --- | --- | --- | --- |
| FT8, depth 1 (NB today) | 0.23 s | 0.14 s | 0.08 s |
| FT8, depth 3 | 1.24 s | 0.55 s | 0.27 s |
| FT4, depth 1 | 0.022 s | 0.009 s | 0.005 s |
| FT4, depth 3 | 0.25 s | 0.10 s | 0.04 s |

Part of jt9's figure is process start and reading the WAV, which ohsdigi
does not pay at all. Where ohsdigi's FT8 time goes (`dev profile`, one pass,
one core): ~4 ms sync8, ~1 ms the long FFT, ~0.12 ms per candidate in ft8b
(~230 candidates), and ~3 ms per subtraction (two 180 000-point FFTs) -
subtraction is the largest share at depth 3, and it is sequential by
construction.

**The Pi 400.** A decode must finish within about 2 s of the slot's end.
PERF.md's unverified estimate puts a Cortex-A72 at 6-10x slower than the development machine
per core. On that basis, at depth 1 (what NB runs): jt9 ~1.4-2.4 s - at or
past the budget already - and ohsdigi ~0.9-1.4 s on one core, ~0.6-1.0 s on
four. At depth 3: jt9 ~8-13 s, ohsdigi ~3-5 s on one core and ~2-3 s on
four - still over. What keeps depth 3 slow is serial: subtraction (two
180,000-point FFTs per signal, sequential by construction) and the
41/47/50 file-mode structure that decodes the slot three times. Measure on
a Pi before planning around these numbers.

### Real slots

Brian's rule (06/10/2026) was that ohsdigi would replace jt9 only once it
decoded as much as jt9 did on real slots as well as simulated ones. The
evidence, all QO-100 narrowband FT8 through NB's own receive chain
(`ohsnb --analyse` on SigMF recordings from Brian's dish, both decoders on
the same 16-bit samples with the same calls):

- **07/10/2026, a three-hour recording: 2,659 decodes, every one found by
  both** - none by only one of them - with the same SNR spread.
- 07/10/2026, on the branch that made the switch, two more recordings
  (~10 minutes, 40 slots, 80 decode passes) through the app's decoder with
  ohsdigi first and jt9 as the shadow: 354 decodes each, 354 in both, no
  disagreement.

One difference was found on the way, in the Python glue rather than the
decoder: ohsdigi started each slot with empty hashed-call tables, so a
message to the operator's own call in `<>` showed `<...>` where jt9 showed
the call. jt9 knows MyCall and the DX call because its a-priori set-up
packs a message made of them before decoding (FT8's ft8apset before MyCall
is set, so MyCall's hash is saved too; FT4's ft4_decode after);
`ft8._jt9_hashes` reproduces both, and on seven hashed-call messages with
five MyCall/DX call combinations, in both modes, ohsdigi now names exactly
the calls jt9 names (`tests/test_modes_ft8.py`). The recordings could not show
it: `ohsnb --analyse` decodes with no MyCall, and then neither decoder
knows any call.

### In the app: ohsdigi decodes, jt9 is the fallback and the shadow

`ohscore/modes/ft8.py`, `Decoder`, every decode pass (13.5 s into an FT8
slot and at its end; 6.0 s and the end for FT4):

- **Which decoder.** The `ft8Decoder` setting (Settings › Station, "FT8
  and FT4 decoder"): `auto` (the default) is ohsdigi first, `jt9` puts jt9
  first. Asked every pass, so a change applies from the next slot. Where
  only one is installed it decodes either way: ohsdigi alone (no WSJT-X)
  now offers FT8 and FT4 both ways.
- **Fallback.** Without ohsdigi (the `all` .deb, a source run without the
  build) jt9 decodes, and the log says why once. If ohsdigi raises on a
  pass, jt9 decodes that pass; the first such failure is logged with its
  traceback, the rest are not repeated, and the next good pass is
  ohsdigi's again. With no jt9 behind it the failure is the slot's error
  event, as a jt9 failure always was.
- **Status.** `ft8DecoderInUse` (`ohsdigi`, `jt9`, `jt9 (ohsdigi failed)`;
  empty in other modes) - the FT8 panel shows it under band activity, and
  the diagnostics report has it with the setting.
- **The same events.** ohsdigi's decodes become exactly the events jt9's
  output did: SNR as is, DT rounded as jt9's `f5.1` and frequency as its
  `nint` (a half away from zero), `ap` "a1".."a6" for an a-priori decode,
  and `lowConfidence` only on an a-priori decode with quality under 0.17 -
  WSJT-X's own rule (decoder.f90). Depth 1, as NB runs jt9. The call,
  grid and so the country column come from the text, as before.
  `tests/test_modes_ft8.py` (OhsdigiMatchesJt9) holds each decoder alone to
  identical events on ten FT8/FT4 fixtures.
- **Shadow** (`ohscore/modes/decoder_shadow.py`). Where both are installed,
  the other decoder decodes every pass too, on exactly the same samples
  and calls, after the first one's decodes have gone out and on its own
  thread (so the slot's final pass never waits for it; on a Pi jt9 alone
  can take most of the 1.5 s between the passes). It never emits. A
  disagreement is one INFO line in the log:

  ```
  decoder shadow ft8 12:34:45: ohsdigi 12, jt9 11, both 11; ohsdigi 0.041 s, jt9 0.180 s; ohsdigi only: CQ X1ABC AA00 @1234 Hz -0.3 s
  ```

  and agreement a DEBUG one. Running counts - passes, decodes each found
  and found alone, mean and worst times, the last ten disagreements, and
  shadow failures - are in the diagnostics report's "ft8/ft4 decoder
  comparison" section. On by default (one band and one recording is the
  evidence so far); `OHSDIGI_SHADOW=0` turns it off - the name is kept
  from when it named the shadow.
- `ohsnb --analyse` captures both decoders' lists per slot from
  `decoder_shadow.record` and tables them, whichever is first.

**Decode time** (the development machine, 16 threads, load ~5 from other
work; the app's own decoder on the two recordings above, per pass):
ohsdigi median 0.037 s, worst 0.057 s; jt9 (its whole process, FFTW wisdom
warm after the first) median 0.156 s, worst 0.725 s (the first, cold
run). The budget is the 1.5 s from the 13.5 s pass to the slot's end; on
a Pi, see "Speed" above - ohsdigi was the faster of the two there too by
the estimate, and is now the one the operator waits for.

### Python API (decoder)

```python
from ohscore import ohsdigi
h = ohsdigi.CallHashes(); h.set_mycall("G4XYZ")   # one per receiver, kept
d = ohsdigi.ft8_decode(pcm16, depth=1, mycall="G4XYZ", dxcall="", hashes=h)
#   pcm16: bytes, int16 little-endian, 12 kHz, slot start at 0 (as jt9's WAV)
#   -> [{"text", "bits", "snr", "dt", "freq", "ap", "hard_errors", "qual"}, ...]
ohsdigi.ft4_decode(pcm16, depth=1, mycall=..., dxcall=..., hashes=h)
ohsdigi.JT9_MYCALL, ohsdigi.JT9_DXCALL           # "K1ABC", "W9XYZ": jt9's own
```

Other keywords: `nfa`/`nfb` (Hz), `nfqso`, `ap` (FT8 a-priori passes on/off),
`qso_progress` (0-5, WSJT-X's QSO state: which AP types are tried),
`jt9_file_mode` (FT8: reproduce jt9's 41/47/50 calls; default on),
`threads` (0, the default, is cores - 1; 1 is one core). Decodes are unpacked into `hashes` in candidate order, as
WSJT-X's serial loop does; the validity test inside the parallel part
unpacks into a copy of the tables as they stood at the start of the pass.

### Threads

Each decode runs on a rayon pool of its own, `threads` wide, which is taken
down when the call returns (`util::with_pool`) - not rayon's global pool,
which is as wide as the machine and whose workers live for the rest of the
process. In NB the decoder shares the process with the receive path and the
UI: the default leaves them a core, and nothing of the decoder's runs
between slots. Starting a pool costs tens of microseconds per slot.

**The segfault in the full Python suite (found, not ohsdigi's).** With the
decoder-bearing module installed, the suite died with SIGSEGV in
`test_ham_ui.Window.test_second_display_and_theme_switch` (5 of 5 runs on
06/10), and only once `test_decoder_shadow.RealExtension` had decoded
earlier in the process. The kernel's records of those five crashes put
every one on the main thread's stack (sp 0x7ffc...-0x7fff...), inside
`QWidget::update`, `QWidget::setPalette`, QtTest, or a jump through a freed
vtable - never in ohsdigi or on a rayon thread. A core dump of the same
crash reproduced without ohsdigi (Python's collector forced to run at every
allocation, `gc.set_threshold(1)`; 3 of 3 runs) shows the mechanism:
`QApplication::setStyleSheet` repolishes every widget it has styled, calls
Python reimplementations (`event()`, `sizeHint()`) that allocate, an
allocation starts a garbage collection, the collection frees the previous
test's closed window - Python-owned, kept only by a reference cycle - and
Qt carries on into `QWidget::setPalette` on the freed widgets (their
vtable pointers are glibc free-list values in the core). A real decode
merely moved where the collector next ran. The fix is in the UI, not
here: `ohscore/ui/qtapp.py` (`_GuiThreadGc`) turns automatic collection
off while the QApplication exists and collects from a timer on the GUI
thread, between events, so Qt objects are never freed inside a Qt call
or on another thread; `tests/test_qtapp_gc.py` covers it, and a stress
run of hundreds of decodes interleaved with window and theme work, with
the decodes on a worker thread as in NB, does not crash.

The per-call pool stays for its own reasons (no decode takes every core
from the receive path and the UI; no idle threads between slots), and
`tests/decode_sim.rs` checks a decode leaves no thread behind.

### How it sits on phase 1

The decoder uses the crate's own items: `crc::crc14_ok`,
`ldpc::ldpc174_91::{GENERATOR, encode}` (OSD builds its unit-vector
generator from the rows), `ft8::{COSTAS, GRAY, tones}`,
`ft4::{COSTAS, GRAY, RVEC, scramble, tones}`, `msg77::{pack77, unpack77,
CallHashes}`. Its own additions outside `src/decode/` are two lines -
`pub mod decode;` in lib.rs and `decode::py::register(m)` in python.rs's
`#[pymodule]` (with `PyCallHashes` made `pub(crate)` so the decoder takes
the same class) - and rustfft, rayon and an optimised `[profile.test]` in
Cargo.toml. Subtraction keeps its own `gen_ft8wave_complex`: it needs
WSJT-X's complex, table-lookup reference, not the transmit waveform.

The parity-check tables stayed in `decode/` rather than moving beside the
generator in `ldpc/`; if JS8's (174,87) code arrives, move both them and
`decode/ldpc.rs` into `ldpc/` so one BP/OSD serves both codes.

### What remains

- **Watch the shadow.** ohsdigi decodes now; the comparison counts in
  testers' diagnostics reports, and any "decoder shadow" INFO line in a
  log, are how a disagreement on another band or another station's
  signals will show. Once those have stayed at zero for long enough, jt9
  can stop being the shadow by default (it costs a jt9 run per pass).
- **A receiver's own hash table.** jt9, started once per WAV, forgets
  hashed calls between slots, and ohsdigi reproduces that. WSJT-X's GUI
  keeps them for the session; ohsdigi could too (`hashes=`, one
  `CallHashes` per receiver), showing calls jt9 shows as `<...>` - a
  deliberate difference from jt9, so a decision for later, with the shadow
  told to expect it.
- **Speed for the Pi at depth 2-3:** parallel subtraction of signals far
  enough apart in frequency not to interact (not bit-exact, so it needs its
  own verification run), a decimated amplitude filter instead of the
  180,000-point FFT pair, and measurement on a real Pi 400/500.
- **Not ported:** contest AP variants; ft8_a7; OSD npre2. None is reached
  by NB today.

## JS8: the plan (assessed 09/10/2026; done 10/10/2026)

The assessment that left JS8 out of the first wheel ordered the work as
encoder, frame-level decoder, other speeds, message layer, multi-frame
assembly. It was done in that order the next day ("JS8", above), with
two differences: the (174,87) code's decoders are their own (WSJT-X 1.9's
BP and OSD differ from 2.7.0's in more than tables), and the app API got
JS8 calls of its own (`js8_decode` and friends) rather than `"js8"` in
`decode`'s `MODES`, so a decode keeps its frame structure. Multi-frame
assembly stays the app's job, as planned.

## HSmodem (the QO-100 multimedia beacon, and station to station)

Added 06/10/2026: `src/hsmodem/`, a port of DJ0ABR's HSmodem - the modem of
AMSAT-DL's multimedia beacon - and of the liquid-dsp objects it is built
from. Licences, sources, the protocol and what is unverified are in
docs/hsmodem-research.md; this section is how it sits in the crate.

```
src/hsmodem/
  frame.rs      the 258-byte frame: header, CRC-16, RS, scrambler, bytes<->symbols;
                pack(), Packer (Pack()'s counter rules), Deframer (unpack_data)
  rs.rs         RS(255,223), HSmodem's parameters, our own encoder/decoder
  liquid.rs     liquid-dsp 1.3.2's NCO, AGC, symsync, firpfb/interp/decim,
                eqlms, APSK/QPSK/BPSK modem, filter design - as liquid computes them
  demod.rs      km_symtrack, HSmodem's audio front end, its watchdog
  speed.rs      HSmodem's ten speed modes (sr[]): BPSK/QPSK/8APSK, 1200-7200 bit/s
  receiver.rs   NB's receive chain at any speed: IQ (resampler, coarse AFC),
                SSB audio (mixer, low-pass, then as IQ) or HSmodem's audio; statistics
  resample.rs   the arbitrary-ratio resampler both directions share
  modulator.rs  frames -> baseband at k samples/symbol, HSmodem's sound-card audio,
                or ssb_audio: what NB transmits (12 kHz, centred at 1500 Hz)
  py.rs         the Python binding
```

Added 07/10/2026: station to station. NB's "hsmodem" mode sends with
`Packer` + `ssb_audio` through its ordinary transmit chain and receives
with `Receiver::ssb` from its ordinary 12 kHz decoder feed; the coarse
search is the Mth power of the constellation's symmetry (7 for 8APSK, 4
QPSK, 2 BPSK). docs/hsmodem-research.md section 8 has the speeds, the
protocol and the interop runs against HSmodem's own code.

Python (`ohscore.ohsdigi`):

```python
rx = ohsdigi.HsReceiver(12000.0)            # complex baseband at 12 kHz, beacon at 0 Hz
rx = ohsdigi.HsReceiver(48000.0, audio=True, centre=1500.0)   # HSmodem's sound-card path
rx = ohsdigi.HsReceiver(12000.0, ssb=True, speed=4)           # a station's SSB audio, speed mode 4
rx.feed(iq.astype(np.complex64).tobytes())  # -> [{"type","status","counter","payload","symbol",
                                            #      "corrected","rotation"}, ...]
rx.stats()        # symbols, frames_ok, fec_failed, crc_failed, resets, mer_db, freq_hz, in_sync, ...
rx.record(True); rx.take_record()           # per-symbol stage values, the harness's layout
ohsdigi.HsPacker().pack(payload, ftype, status, repeat=False)   # 258 bytes, Pack()'s counter
ohsdigi.hs_pack(payload, ftype, status, counter)
ohsdigi.hs_baseband(frames, k=5, flush=0, speed=9)   # complex64 bytes, RRC 0.2, k samples a symbol
ohsdigi.hs_audio(frames, speed=9, marker=False)      # HSmodem's sound-card audio at that mode's rate
ohsdigi.hs_ssb_audio(frames, speed, rate=12000.0, centre=1500.0, peak=0.85, lead=0, tail=0)
ohsdigi.hs_speeds()                                  # [{mode, bitrate, scheme, baud, afc_span, ...}]
ohsdigi.hs_crc16(data)
```

`feed` runs with the GIL released; a receiver is one object per stream,
used from one thread. What the payloads mean - files, DX spots, spectra -
is read in Python (`ohscore/modes/hsmodem.py`).

Verification is against HSmodem's own source and its bundled liquid
binary: `harness/hsmodem/build.sh` (container) and `harness/hsmodem/compare.py`
(`frames`, `rs`, `stages`, `iq`, `corpus`, and `speeds`/`corpus4` for the
station-to-station modes), with `examples/hsdev.rs` as
ohsdigi's side. Frames and RS are byte-identical to HSmodem's; receive is the
same frames at the same symbols, hard symbols 100 % at >= 16 dB Es/N0
(docs/hsmodem-research.md section 6 has the table). `tests/hsmodem.rs`
replays the corpus in `testdata/hsmodem/` (190 KB), and `tests/hsmodem_speeds.rs`
HSmodem's own mode-4 audio (200 KB) and NB's own link at every speed;
`examples/hsspeeds.rs` prints the sensitivity per speed.

Cost: 23 s of 12 kHz IQ in 0.065 s on the development host (0.3 % of one
core), resampler and AFC included.
