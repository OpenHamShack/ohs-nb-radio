# ohsdigi from Python: the ohs-ohsdigi wheel and its app API

ohsdigi (rust/ohsdigi) is the one FT8/FT4, Q65 and JS8 encoder and decoder
for every OpenHamShack app - Icom, Digital Modes, NB and Radio. This page
is the contract those apps code against: how they get the module, the
three calls they use for FT8/FT4, and the Q65 and JS8 calls. How the crate
works inside, and how it is held bit-exact against WSJT-X 2.7.0 and
JS8Call 2.2.0, is docs/digimodes-rust.md.

## Getting it

```
pip install ohs_ohsdigi-<version>-cp311-abi3-<platform>.whl
```

```python
import ohsdigi            # the import name is ohsdigi, not ohs_ohsdigi
```

| | |
| --- | --- |
| Distribution | `ohs-ohsdigi` ("ohsdigi" alone is too generic a name to claim) |
| Import | `ohsdigi` - the same name the NB/HAM bundles' copied-in module has, so code works with either |
| Python | CPython 3.11 and later: one abi3 wheel per platform |
| Dependencies | none (not even numpy) |
| Licence | GPL-3.0-or-later; the wheel carries LICENSE and LICENSE-THIRD-PARTY |

Wheels, all built by `tools/build-wheels.sh` into `rust/dist/wheels/` with a
`SHA256SUMS`:

| Platform | Tag | Runs on | Built | Tested by the script |
| --- | --- | --- | --- | --- |
| Linux x86_64 | `manylinux_2_35_x86_64` | glibc 2.35+: Ubuntu 22.04+, Debian 12+ | bookworm container | round trip in Python 3.11 (container) and the host's |
| Linux arm64 | `manylinux_2_35_aarch64` | Pi OS bookworm and later, other arm64 glibc 2.35+ | same container, cross gcc | built only |
| Windows x64 | `win_amd64` | Windows 10/11 | same container, mingw-w64 | built only |
| macOS | `macosx_11_0_universal2` | macOS 11+, Apple silicon and Intel | the Mac mini, natively | round trip, arm64 and x86_64 (Rosetta 2) |

The manylinux tag is what maturin's symbol check allows for the module as
built (its newest glibc symbol is 2.35), not just the build system's age.
An older tag (manylinux2014) would need a zig or manylinux-image build;
nothing we ship to needs it.

The NB/HAM bundles keep copying the bare module made by
`tools/build-ohsdigi.sh` (`ohscore/ohsdigi.abi3.so`, `ohsdigi.pyd`). It is
built from the same source with the same calls; only the packaging
differs.

## The app API

These three calls (and `MODES`) are the stable surface: their arguments and
the keys they return do not change within a major version; new optional
keyword arguments and new dict keys may appear. Everything else in the
module (`encode`, `ft8_decode`, `ft4_decode`, `pack77`, `unpack77`,
`tones`, `waveform`, `CallHashes`, the HSmodem classes) mirrors WSJT-X's
tools and NB's needs; apps may use it, but its shape follows WSJT-X.

### `decode(mode, audio, *, time=None, depth=1, freq_min=200.0, freq_max=4000.0, freq_qso=1500.0, mycall="", dxcall="", hashes=None, threads=0) -> list[dict]`

Decode one slot.

- `mode`: `"ft8"` or `"ft4"`.
- `audio`: 12 kHz mono, starting at the slot boundary - 15 s for FT8,
  7.5 s for FT4; shorter is padded with silence, longer is cut. A signal
  sent on time starts 0.5 s in and decodes with `dt` near 0. Accepted:
  - anything with the buffer protocol - numpy arrays, `array.array`,
    `memoryview` - one-dimensional, of **int16** (as is), **float32** or
    **float64** (full scale ±1.0, scaled to int16 range);
  - `bytes` / `bytearray`: **int16 little-endian** (a WAV's data chunk).
  A list is refused (`TypeError`): whether `[0.5, ...]` is half scale or
  half an LSB is exactly the mistake that decodes nothing and says nothing.
- `time`: anything; copied into every result, so the caller can stamp a
  slot (e.g. its UTC start as epoch seconds). Not interpreted.
- `depth`: WSJT-X's 1-3 (fast, normal, deep). 1 by default: what NB runs,
  and the only depth a Pi 400 finishes in the ~2 s after a slot ends. A
  desktop can afford 3.
- `freq_min`, `freq_max`: the audio band searched (Hz). `freq_qso`: where
  the operator is working; decodes near it are tried first and hardest.
- `mycall`, `dxcall`: enable WSJT-X's a-priori decoding for the QSO in
  progress.
- `hashes`: an `ohsdigi.CallHashes()` kept across slots, so a hashed call
  heard in full earlier shows by name instead of `<...>`. Without it each
  call starts empty, as jt9 run once per file does.
- `threads`: 0 = cores - 1. The GIL is released while decoding, so other
  Python threads (the UI) keep running.

Each result:

| Key | Type | Meaning |
| --- | --- | --- |
| `time` | as passed | the `time` argument |
| `snr` | int | dB in 2500 Hz, as WSJT-X reports it |
| `dt` | float | seconds relative to the nominal start (0.5 s into the slot) |
| `freq` | float | Hz of tone 0 |
| `message` | str | the message as WSJT-X shows it |
| `mode` | str | `"ft8"` / `"ft4"` |
| `bits` | str | the 77 payload bits, `'0'`/`'1'` |
| `ap` | int | 0 = no a-priori help, 1-6 WSJT-X's AP type |
| `hard_errors` | int | hard bit errors corrected |
| `qual` | float | WSJT-X's decode quality |

### `encode_audio(mode, message, freq=1500.0, sample_rate=12000.0) -> bytes`

The transmission as **float32 little-endian** samples, full scale ±1.0,
tone 0 at `freq` Hz, exactly as WSJT-X generates it (GFSK, ramped):
151 680 samples for FT8, 60 480 for FT4 at 12 kHz. Start it 0.5 s after
the slot boundary. Raises `ohsdigi.BadMessage` (a `ValueError`) for a
message WSJT-X would not send; `str()` says why.

```python
import array, numpy as np
samples = np.frombuffer(ohsdigi.encode_audio("ft8", "CQ G4XYZ IO91", 1500.0), dtype="<f4")
# or, without numpy: a = array.array("f"); a.frombytes(ohsdigi.encode_audio(...))
```

The message's normalised and as-received forms, its tones and its type
are on `ohsdigi.encode(mode, message)` (`.message`, `.sent`, `.tones`,
`.type_name`).

### `version() -> str`

ohsdigi's version, the same as the wheel's (`importlib.metadata.version("ohs-ohsdigi")`)
and `ohsdigi.__version__`. `ohsdigi.WSJTX_VERSION` is the WSJT-X release it
reproduces (`"2.7.0"`).

### `MODES`

`("ft8", "ft4")` - the modes `decode` and `encode_audio` take. Q65 and
JS8 have calls of their own (below): Q65's decode takes a period length,
submode and tolerance that `decode` has no room for, and JS8's decodes are
frames with a message layer on top, not WSJT-X messages.

## Q65

A port of WSJT-X 2.7.0's Q65 (rust/ohsdigi/src/q65): genq65, the QRA
codec and the decoder `jt9 -3` runs. Held to WSJT-X itself - tones equal
q65code's, and on test periods (ohsdigi's audio and WSJT-X's q65sim, with
Doppler fading) the decodes print as jt9 prints them
(rust/ohsdigi/tests/q65_golden.rs). Added 10/10/2026: check
`hasattr(ohsdigi, "q65_decode")` with an older module.

`Q65_PERIODS` maps each T/R period (15, 30, 60, 120, 300 s) to `nsps`,
`start` (where a transmission starts: 0.5 s for 15/30 s, 1 s for longer),
`symbols` (85), `duration` and `baud`; `Q65_SUBMODES` is `("A", ... "E")`
(tone spacing 1, 2, 4, 8, 16 x the baud).

### `q65_decode(audio, period=60, submode="A", *, depth=1, freq_qso=1500.0, tol=10.0, freq_min=200.0, freq_max=4000.0, mycall="", dxcall="", dxgrid="", qso_progress=0, emedelay=None, single=False, hashes=None, threads=0) -> list[dict]`

One period from its boundary, `audio` as `decode` takes it. As jt9 does:
first at `freq_qso` +/- `tol` - with `dxcall` known, a list decode of the
206 likely replies first - then (unless `single`) every other sync
candidate in `freq_min`..`freq_max`. `depth` is WSJT-X's 1-3; `mycall`
and `dxcall` enable its a-priori passes; `qso_progress` (0 calling ... 5
signing off) picks which; `emedelay` defaults to jt9's (2.5 s at 60 s
periods, widening the time search to +5.5 s). Not ported: averaging over
several periods. Each result:

| Key | Type | Meaning |
| --- | --- | --- |
| `text` | str | the message as WSJT-X shows it |
| `snr`, `dt`, `freq` | int, float, float | as jt9 reports them (freq of the sync tone; dt from the nominal start) |
| `ap` | int | jt9's "q" digit: 0 no a-priori help, 1 CQ, 2 MyCall, 3 list decode |
| `averaged` | int | periods averaged (always 1) |
| `bits` | str | the 77 payload bits |
| `period`, `submode` | int, str | as asked |

### `q65_encode(message) -> (sent, tones)` and `q65_encode_audio(message, period=60, submode="A", freq=1500.0, sample_rate=12000.0) -> bytes`

`q65_encode` gives the message as it will be received and its 85 tones
(bytes; 0 is the sync tone, data symbol v is tone v + 1), as genq65 makes
them. `q65_encode_audio` gives the transmission, float32 little-endian,
full scale, sync tone at `freq`, as WSJT-X's modulator plays it
(unshaped continuous-phase FSK, a short fade at the end); start it
`Q65_PERIODS[period]["start"]` after the period boundary. Both raise
`ohsdigi.BadMessage` for a message WSJT-X would not send.

## JS8

A port of JS8Call 2.2.0 (rust/ohsdigi/src/js8): the modem in all five
speeds, the decoder, and the message layer. Held to JS8Call's own code -
the decoder prints what JS8Call's `js8` prints, line for line, and text
becomes the frames JS8Call's buildMessageFrames makes
(rust/ohsdigi/tests/js8_golden.rs). Same stability promise as the app API
above; added 10/10/2026, so check `hasattr(ohsdigi, "js8_decode")` before
relying on it with an older module.

A JS8 *frame* is 12 characters plus three header bits (`i3bit`: first
frame, last frame, fast data); one frame goes in each period. A message is
a run of frames from the one with `first` set to the one with `last` set.

`JS8_SUBMODES` describes the speeds, keyed by name - `normal` (A, 15 s),
`fast` (B, 10 s), `turbo` (C, 6 s), `slow` (E, 30 s), `ultra` (I, 4 s) -
each a dict of `letter`, `period`, `start` (seconds into the period a
transmission starts), `tone_spacing`, `symbols` (79) and `duration`.
Every `submode` argument takes the name or the letter.

### `js8_decode(audio, submode="normal", *, depth=3, freq_min=200.0, freq_max=4000.0, freq_qso=1500.0, threads=0) -> list[dict]`

Decode one period, `audio` as `decode` takes it, from the period
boundary. `depth` is JS8Call's: 1 BP only, 2 with subtraction, 3 (its
default, about 0.1 s a period here) with OSD, 4 one pass more. Each
result:

| Key | Type | Meaning |
| --- | --- | --- |
| `frame`, `i3bit` | str, int | the frame and its header bits |
| `snr`, `dt`, `freq` | int, float, float | as `js8` reports them (dt from the speed's nominal start) |
| `submode` | str | the speed's name |
| `text` | str | the frame as JS8Call shows it: `"KN4CRD: J1Y SNR -05 "`, `"HELLO WORLD"`; the raw frame when it is none of JS8Call's kinds |
| `kind` | str | `heartbeat`, `compound`, `compound_directed`, `directed`, `data` or `unknown` |
| `from`, `to`, `grid` | str or None | the stations and grid the frame names (groups such as `@ALLCALL` included) |
| `first`, `last` | bool | the frame's place in its message |
| `sync`, `hard_errors`, `qual` | float, int, float | the decoder's own numbers |

### `js8_unpack(frame, i3bit) -> dict`

One frame read as above (`text`, `kind`, `from`, `to`, `grid`, `first`,
`last`) - for frames decoded elsewhere, such as by JS8Call's `js8`.

### `js8_frames(text, mycall, mygrid="", *, selected_call="", submode="normal", force_identify=False, force_data=False) -> list[tuple[str, int]]`

The frames JS8Call would send for `text`, each with its `i3bit`, in
order. `selected_call` is the station picked in JS8Call's list (text not
already addressed is sent to it). Text is upper case, as JS8Call sends
it; text no frame can carry (lower case, where JS8Call itself never
returns) raises `ValueError`.

### `js8_encode_audio(frame, i3bit, submode="normal", freq=1500.0, sample_rate=12000.0) -> bytes`

One frame's transmission, float32 little-endian, full scale, tone 0 at
`freq`: what JS8Call's modulator plays (unshaped FSK, a short fade at the
end), to start `JS8_SUBMODES[submode]["start"]` after its period boundary.
`js8_tones(frame, i3bit, submode)` gives the 79 tones.

```python
frames = ohsdigi.js8_frames("J1Y HELLO THERE", "GM4BRI", "IO75")
for k, (frame, i3bit) in enumerate(frames):       # one per 15 s period
    audio = np.frombuffer(ohsdigi.js8_encode_audio(frame, i3bit), "<f4")
```

## Example: a receive loop

```python
import time, ohsdigi, numpy as np

hashes = ohsdigi.CallHashes()
hashes.set_mycall("GM4BRI")
slot_start = ...                      # UTC epoch of the slot boundary
audio = ...                           # np.ndarray float32, 15 s at 12 kHz
for d in ohsdigi.decode("ft8", audio, time=slot_start, hashes=hashes, mycall="GM4BRI"):
    print(time.strftime("%H%M%S", time.gmtime(d["time"])), d["snr"], f'{d["dt"]:.1f}',
          int(d["freq"]), d["message"])
```

## Building and testing

```
tools/build-wheels.sh                   # all four, with round trips where they can run
tools/build-wheels.sh linux-amd64       # one; also linux-arm64, windows-amd64, macos
tools/build-wheels.sh --no-test ...     # build only
```

Linux and Windows build in `rust/build.Containerfile` (maturin pinned by
hash in `rust/ohsdigi/wheel-requirements.txt`); macOS over `ssh mac`, with
its own pinned rustup, Python and maturin under
`/Volumes/OpenHamShackBuild/ohs-ohsdigi-wheel`. Zip timestamps are fixed
(`SOURCE_DATE_EPOCH`), so one commit gives the same wheel bytes; a rebuild
of the macOS wheel gave identical bytes.

`tests/test_ohsdigi_wheel.py` installs a wheel into a fresh venv (under
`~/build`, or `OHSDIGI_WHEEL_WORK`) with `--no-index` and round-trips FT8
and FT4 through `encode_audio` and `decode` from float32, float64, int16
and bytes; it skips when no wheel for the machine has been built.
