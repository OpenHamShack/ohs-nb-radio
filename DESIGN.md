# OpenHamShack QO-100 NB — design

A QO-100 **narrowband** transceiver: one native desktop application. A radio
engine owns the SDR and does all the signal processing; a Qt window is the whole
user interface; both run in one process on the operator's machine. It is the sibling of OpenHamShack QO-100 WB (the OpenHamShack appliance it started beside) — same habits, same safety rules — but it is
a separate program: QO-100 WB moves an MPEG transport stream to DVB firmware;
OpenHamShack QO-100 NB generates and demodulates IQ itself. And unlike QO-100 WB it is **not**
browser-based: it is used at the machine it runs on, so a client/server split,
a WebSocket protocol and browser audio would be cost with no benefit.

Where it runs, in order of how often it will: a **Linux laptop** (Debian,
Ubuntu, Mint), a **Raspberry Pi 400/500** (Raspberry Pi OS), an N150-class mini
PC like QO-100 WB's. Nothing in the design is Linux-only except packaging; a
Windows 10/11 build (PyInstaller + Inno Setup, `packaging/windows/`) carries
the simulator, the Pluto family over libiio, FreeDV, and FT8 and FT4 (sent by
ohsdigi, received by WSJT-X's jt9).

## Shape

```
 Pluto / LibreSDR / Pluto nano ──IQ──┐   ┌──────────── one process ─────────────┐
 RTL-SDR / Airspy / SDRplay (RX) ─IQ─┼──►│ engine (ohsnb.radio)  ◄──► Qt UI       │──► main window
 simulated transponder ──────────IQ──┘   │   numpy DSP, locks,       (ohsnb.ui)  │──► second display window
                     sound card ◄──────► │   modes, PortAudio                   │
                                         └──────────────────────────────────────┘
```

- `python3 -m ohsnb` opens the window. `python3 -m ohsnb --headless` runs the
  engine alone (tests, benchmarking).
- Engine needs only `numpy`. UI needs `PyQt6` (Debian `python3-pyqt6`).
  Audio uses PortAudio through `pyaudio` (`python3-pyaudio`). Optional:
  `python3-libiio` (Pluto family), `python3-soapysdr` (receive-only SDRs),
  `python3-serial` (an IC-9700 over CI-V as the transmitter),
  `wsjtx` (its `jt9` decodes FT8/FT4), `libcodec2` (FreeDV). FT8/FT4 are
  encoded by ohsdigi, our Rust port of WSJT-X 2.7.0's encoder, a compiled
  module in the amd64/arm64 packages and the Windows build
  (docs/digimodes-rust.md); where it is absent WSJT-X's ft8code/ft4code
  encode instead. A missing optional
  piece disables one feature with a sentence saying which package to install;
  it never stops the program.
- Config: `$OHS_NB_CONF` (or the former `$OHSNB_CONF`), else `~/.config/openhamshack-nb/config.json`
  (Windows: `%APPDATA%\openhamshack-nb\config.json`); the folder name,
  openhamshack-nb, has not changed since before the OpenHamShack rename
  (17/10/2026) - only the environment variable prefix did (docs/names.md).
- Data (the log, its ADIF export, received SSTV pictures, what the multimedia beacon sent): `$OHS_NB_DATA`, else
  `~/.local/share/openhamshack-nb/` (Windows: `%APPDATA%\openhamshack-nb\data\`).
  The program's own log is always written to `logs/openhamshack-nb.log` there
  (rotated, 2 MB x 5; `-v` for DEBUG); Help › Save diagnostics… zips it
  with the settings, a system report and a screenshot (`ohscore/diag.py`).
- Everything that differs between Linux and Windows - those folders, where a
  shared library or WSJT-X is found, which install sentence to show - is
  answered in `ohscore/host.py` and nowhere else.
- The engine never imports Qt. The UI never touches numpy DSP or the device.
  That boundary is what keeps the engine testable headless and the UI
  replaceable.
- Code: `ohsnb/` is OpenHamShack QO-100 NB's QO-100 part (bandplan, state keys, beacon
  and TX lock, the transponder sim, the engine's QO-100 hooks, its window's
  QO-100 pieces) on `ohscore/`, the engine, DSP, modes, devices and UI it
  shares with OpenHamShack Radio (docs/ham/DESIGN-HAM.md section 2). `ohscore`
  never imports `ohsnb`; the .deb carries its own copy.

## Frequencies — one vocabulary everywhere

All frequencies are **Hz**, floats in Python, numbers in JSON.

| name | meaning |
| --- | --- |
| `dl` | a **downlink** frequency, 10 489 500 000 – 10 490 000 000. This is what the operator sees and types. The VFO is a `dl`. |
| `ul` | uplink = `dl − 8 089 500 000` |
| `if` | what the receiver tunes = `dl − LO + rxCorr`, LO the LNB's (the receive converter's RX offset; below) - a signal that appears high is found high |
| `rxCorr` | measured receive error in Hz at the downlink (beacon lock): how far *high* every signal appears. Display and demodulation subtract it, so beacons sit on their nominal frequencies. |
| `txCorr` | correction added to the uplink so our own signal lands where the VFO says (TX lock). |

The transponder is a bent pipe: what goes up at `ul` comes down at `ul +
8089.5 MHz` plus the satellite's own (small) LO error, which the beacon
measurement already includes.

## The radio thread model

```
 device.read() ─► RX block ─┬─► Spectrum (wide)        ─► Feed "wide"
   (complex64, fs)          ├─► Zoom channel ─► Spectrum ─► Feed "zoom"
                            ├─► BeaconTracker (rxCorr)
                            ├─► TxMonitor (txCorr, own level vs beacon)
                            └─► VFO channel ─► demod ─► audio 12 kHz ─┬─► speaker (PortAudio)
                                                                      └─► mode decoder(s)
 mic (PortAudio) / mode encoder ─► audio 12 kHz ─► modulator ─► TX IQ ─► device.write()
```

- **One RX thread** runs every RX consumer on each block.
  It must keep up in real time on a Pi 400: everything is block-vectorised
  numpy, no per-sample Python loops anywhere on the RX or TX paths.
- **A reader thread** reads a radio with short buffers (a Pluto, SoapySDR,
  the real-time simulator) into a two-second queue ahead of the RX thread
  (`ohscore/rxprefetch.py`, 17/10/2026). The window can starve the RX thread
  of the GIL for a second or more (a theme change); it then falls behind and
  catches up, and the radio is still drained on time. The reader also tells
  samples lost upstream (a stalled link) from samples dropped here, which
  `overruns` and a recording's gaps report apart. Test it with
  `tools/rx_storm.py`, a scripted UI storm against a Pluto-paced simulator.
- **One TX thread** exists only while keyed.
- **Mode decoders that are slow** (jt9 for a 15 s FT8 slot, SSTV image
  assembly) run on their own worker thread and never block the RX thread.
- The **audio rate is 12 000 Hz** mono everywhere (FT8's native rate; plenty
  for 2.7 kHz SSB). The audio layer resamples to whatever the sound card
  offers (usually 48 kHz, an exact 4:1).

## Devices — `ohscore/devices/` (the `sim` is `ohsnb/devices/sim.py`)

```python
class Device:
    kind: str            # "pluto" | "soapy" | "sim"
    can_tx: bool
    radiates: bool       # False only for the simulator (nothing leaves the computer)
    fs: float            # complex sample rate, shared by RX and TX
    def open(self) -> None
    def close(self) -> None
    def set_rx_if(self, hz: float) -> None        # tuner centre, IF Hz
    def set_rx_gain(self, mode: str, db: float) -> None   # front-end gain, live
    def read(self, n: int) -> np.ndarray          # complex64, blocks until n samples
    def set_tx_freq(self, hz: float) -> None      # TX LO, uplink Hz
    def set_tx_gain(self, db: float) -> None      # Pluto: -89.75 .. 0
    def tx_start(self) -> None ; def tx_stop(self) -> None   # tx_stop drops what is queued
    def write(self, iq: np.ndarray) -> None       # complex64, paced by the device
    def tx_finish(self) -> None                   # over ended: send on any part-block held back
    def tx_queued(self) -> float                  # s written but not yet out, that tx_stop would drop
    def status(self) -> dict                       # shown in the console verbatim
```

- **pluto** — libiio: ADALM-Pluto, Pluto+, LibreSDR, Pluto nano (all AD936x
  under the same IIO driver). URI `ip:192.168.2.1` default, `usb:` accepted.
  Separate RX and TX LOs, one sample rate.
- **soapy** — SoapySDR, receive only: RTL-SDR, Airspy, SDRplay, HackRF … Driver
  args string from settings.
- **sim** — a simulated QO-100 NB downlink so the whole program can be built,
  demonstrated and tested with no dish: beacons, noise floor with the
  transponder's passband shape, a population of SSB, CW, FT8, PSK31 and RTTY
  signals, slow LNB drift, and **our own transmission coming back** ~250 ms
  later, at an uplink error we choose, so beacon lock and TX lock are proven
  end to end. The sim is the default device until the operator picks one.

## Locking — `ohsnb/dsp/lock.py`

**Beacon lock (receive).** Track a beacon's received frequency, compare it to
nominal, and drive `rxCorr` with a slow loop. Correction is applied in software
(the NCOs), not by retuning hardware, so it is smooth and glitch-free. Lock
state is `searching → locked → lost`, with the measured error, its rate of
change, and SNR shown in the console. A lock is taken at 10 dB SNR and held
down to 6 dB (hysteresis, `HOLD_SNR`), each reading still checked for the
beacon's traits: with one threshold, a weak dish's beacon at 8-10 dB flipped
locked/lost 197 times in 13 minutes (07/10/2026).

A candidate is only the beacon if it has the beacon's own traits (the middle
beacon: a 400 Hz symbol line in its envelope, no carrier, a steady level) and
agrees with the other beacon when both are heard; searches start ±2 kHz
around a correction worth trusting before the full range; what was refused
is reported with its reason (`rxReject`). Added 06/10/2026 after a loud SSB
station beside the middle beacon took the lock on air - the same cause as
lock getting worse at ±55 kHz (more such signals in a wider window). The
operator can overrule it all: `beaconMode` Auto / Hold (keep the correction
exactly) / Manual (set it by hand), and click-to-lock - "this signal is the
middle beacon" - which sets `rxCorr` there and, in Auto, restarts the
tracker with the narrow search. In Hold and Manual the beacons are still
measured (their level drives the beacon-level guard), but `rxCorr` moves
only by hand, and a hand-set `rxCorr` never feeds the GPS-LNB `txCorr`
prediction.

**TX lock (transmit).** While keyed, find our own signal in the downlink: we
know exactly what we sent (the TX baseband, delayed by the satellite round
trip), so correlate its spectrum against the received spectrum in a window
around where it should land; the lag of the peak is the error. Integrate into
`txCorr` slowly and only on strong, confident measurements. Persist `txCorr`
(and the ppm it implies) so the next session starts close. When the LNB is
declared GPS-locked, the beacon error is mostly the SDR's own reference, so a
first `txCorr` can be predicted before ever keying.

**Beacon-level guard.** QO-100 NB etiquette: no signal stronger than the
beacon. TX monitor measures our own downlink level against the beacon's and the
console shows it as a meter; optionally the TX gain is trimmed automatically to
sit a set margin below beacon level. Clearly over (+0.5 dB) it says so in the
transmit card's one standing warning line - not a toast per measurement, which
is what 0.1.9 did, "0.0 dB ABOVE" included - and the line goes once the level
is back under the beacon (0 dB): the half dB between is hysteresis, so a level
hovering on the threshold does not flicker it.

## Modes — `ohscore/modes/`

Every mode is a pure module working on 12 kHz float32 audio, testable without a
radio, encoders and decoders looped back against each other in tests.

```python
class Decoder:
    def __init__(self, emit: Callable[[dict], None], **opts)
    def feed(self, audio: np.ndarray, t: float) -> None   # t = UTC seconds of audio[0]
    def reset(self) -> None
class Encoder:
    def render(self, **opts) -> np.ndarray    # float32 audio at 12 kHz, peak ≤ 1
```

Event dicts all carry `mode`; then per mode:

- ft8/ft4: `{"mode":"ft8","slot":<utc>,"snr":-12,"dt":0.2,"df":1234,"text":"CQ GM4BRI IO86","call":"GM4BRI","grid":"IO86"}`; the engine adds `"country":"Scotland","dxcc":"GM","continent":"EU"` to any event with a `call` cty.dat can place (ohscore/engine.py `_with_country`)
- psk/rtty/cw: streaming text `{"mode":"psk31","df":1500,"text":"abc","snr":…}`
- freedv: `{"mode":"freedv","sync":true,"snr":4.1,"text":"…"}`
- sstv: `{"mode":"sstv","state":"start|line|done","name":"…png","line":n,"of":m}`
- hsmodem: `{"mode":"hsmodem","kind":"image|bulletin|file|file_progress|station|stats|…",…}` (the beacon's content events)

Modes: **USB** and **LSB** voice, **CW** (keyer + decoder), **FT8**,
**FT4**, **PSK31/63/125**, **RTTY 45.45/170**, **FreeDV** (whatever modes the
installed codec2 offers), **SSTV** receive and send (Robot 36, Martin 1,
Scottie 1, PD 120), **HSmodem** station to station (files, pictures and
text at HSmodem's ten speeds, 4410 bit/s QPSK by default; below), and
**AM**, receive only, for listening to the beacons.
Each is listed in the console even when its optional package is missing,
with that sentence instead of controls. There is no audio recording; the receive IQ can be
recorded (below).

## The multimedia beacon - `ohsnb/beaconrx.py`

AMSAT-DL's High-Speed Multimedia Beacon (10489.995 MHz, DJ0ABR's HSmodem,
8APSK at 2400 Bd) is received all the time, not as a mode: it is inside the
500 kHz the receiver always covers, so it has a channel of its own off the
shared spectrum, like the beacon trackers, and the dial and mode are
irrelevant to it.

```
 RX block ─► Channel at 10489.995 (12 kHz) ─► queue ─► worker thread:
             (receive thread, non-blocking)             ohsdigi HsReceiver (Rust, GIL released)
                                                        └► ohscore/modes/hsmodem.py: files, DX spots,
                                                           spectra ─► "mmb" feed, mmb* status keys,
                                                           <data>/mmbeacon/
```

- The modem is ohsdigi's port of HSmodem (rust/ohsdigi/src/hsmodem), held
  against HSmodem's own code stage by stage (docs/hsmodem-research.md); the
  content layer is Python. HSmodem station to station (the "hsmodem" mode,
  07/10) reuses both: ohsdigi's receiver at the mode's speed on the VFO
  channel's 12 kHz audio (its SSB front end), the same content layer
  saving to <data>/hsmodem/, and an encoder that renders HSmodem's own
  transmission (preamble, station frames, repeats) as 12 kHz audio for the
  ordinary transmit path - so every transmit guard applies unchanged. The
  speed (`hsSpeed`) is one setting for both directions; the lower panel's
  HSmodem panel sends files, pictures (reduced as HSmodem's GUI does) and
  text (docs/hsmodem-research.md section 8).
- Beacon lock gives the frequency; a coarse 7th-power search (+-171 Hz)
  takes up what is left, and the receiver restarts when rxCorr jumps.
- `mmbDecode` switches it, live. A slow worker drops channel blocks and
  never holds up receive; its cost is in docs/PERF.md.
- The UI is the lower panel's **Beacon** view (`ohsnb/ui/mmbview.py`):
  bulletins, the DX cluster (QO-100 spots also labelled on the wide
  waterfall), pictures and the beacon's own spectra, with its decode
  quality. The simulator's beacon is a real HSmodem signal carrying sample
  content (`ohsnb/devices/mmbeacon.py`).

## IQ recording — `ohscore/sigmf.py`

File › Record receive IQ… (07/10/2026, for testers to send samples) writes
the receive IQ as the engine gets it - after any software decimation,
before the converter mirror and the noise blanker; never transmit - to a
SigMF pair in `<data>/recordings/`: ci16_le, plus a `.sigmf-meta` whose
`openhamshack:` extension says what an analyst needs (LNB, rxCorr and beacon
lock, gain, device and firmware, app, OS, callsign, mode and dial). A
writer thread behind a two-second queue does the disk; a slow disk loses
blocks, counted and marked as gaps, and never stalls receive. Gaps in the
radio's own stream are marked too and counted apart, so the operator is
told whether the disk or the link to the radio lost them. The
module's docstring has the decisions; docs/ENGINE-API.md the API.

## IQ playback — `ohscore/devices/filedev.py`

File › Play IQ recording… (07/10/2026) plays a SigMF recording through
the whole receiver in place of the radio: a receive-only "file" device
behind the device interface, so scopes, beacon lock, demodulators and
decoders are the ones that run on air. Captures are matched on the air
through the app's converter and retunes inside the recording are made up
by an NCO; tuning outside it is refused. The decoders' time stamps are the
recording's, so FT8/FT4 slots are the original UTC. Transmit is
impossible on it. The recording's dial, mode and (NB) rxCorr are seeded
and given back afterwards, never saved meanwhile, so someone else's LNB
error never lands in the operator's config. The device's docstring has
the decisions; docs/ENGINE-API.md the API.

## Engine API — `ohsnb/radio.py` (on `ohscore/engine.py`)

The UI talks to the engine through one object and nothing else:

```python
radio = Radio(config)            # does not open the device or transmit
radio.start()                    # opens device + audio, starts RX
radio.set(**changes)             # validated against ohsnb/state.py; raises ValueError with an operator-readable sentence
radio.state() -> dict            # snapshot
radio.ptt(on: bool)              # voice modes key with mic audio
radio.send(mode, **msg)          # queue a digital transmission (text, FT8 message, CW text, SSTV image)
radio.subscribe(kind, maxlen) -> Feed   # kind: "wide","zoom","events","lock","meter","state","toast"
radio.stop()
```

A `Feed` is a bounded, drop-oldest queue: the RX thread `put`s and never
blocks; the UI drains each feed on a Qt timer (~30 Hz). A slow UI drops
spectrum lines; it can never stall receive. Spectrum items carry
`(t, start_dl_hz, bin_hz, db: float32 array)`.

`ohsnb/state.py` lists every state key — type, range, default, persisted or
not — and is the single source of truth; the UI reads limits from it rather
than hard-coding them.

## Audio — `ohscore/audio.py`

PortAudio via `pyaudio`, input and output device chosen in Settings (by name,
so a USB headset plugged into another port is still found), "system default"
otherwise. RX audio is played with a small jitter buffer; a mic level meter
and a monitor (hear yourself) option. A second output can carry a mode's audio
to other software (e.g. a loopback device for WSJT-X or fldigi) — optional.

## Safety rules (non-negotiable)

1. Never transmits at start or after a restart, a reconnect or a settings save.
2. Transmit only inside the NB uplink allocation, refused on the beacon
   segments, refused with the receive-only device.
3. A transmit time-out (default 5 min) and dead air (voice mode, no mic audio
   for 3 s) unkey.
4. If the UI stops servicing the engine (hang, crash), a watchdog unkeys.
5. TX gain ceiling in settings; the console's power control cannot exceed it.
6. An external transmitter (below) is never keyed by OpenHamShack QO-100 NB, on either
   link: its drivers cannot send a PTT command at all.

## An external transmitter — `ohsnb/extrig.py`, `ohscore/rig/`

Ray, the first on-air tester, receives with NB and a Pluto but transmits
with an **IC-9700** on 23 cm into an upconverter to 13 cm. NB treats that
radio as its transmitter without ever keying it (PTT stays on the radio):

```
 Pluto (RX) ──IQ──► engine ──► scope: TX marker = where the 9700 is aimed,
                      ▲  │              LANDED = where it really came down
       freq, TX state │  │ freq (between overs only)
                      │  ▼
   ohscore/rig: RigLink thread ── CI-V (USB serial) or Hamlib rigctld (TCP) ── IC-9700 ─► upconverter ─► 2.4 GHz
```

- **Drivers** (`ohscore/rig/civ.py`, `rigctl.py`) are whitelists: read
  frequency, mode and transmit state; set frequency; set USB or LSB (and no
  other mode). Nothing else can be sent - CI-V's transmit-state read and its PTT command differ by one byte.
  Every command is sourced in `docs/ic9700-research.md`. They are in the
  core so OpenHamShack Radio's planned CAT link can use them unchanged.
- **RigLink** (`ohscore/rig/link.py`) polls the radio on its own thread
  (`rigPollMs`, 100 ms) so a dead serial port costs that thread, never
  receive; it tells a knob turn from the echo of its own write, and reports
  `lost` (and not transmitting) when the radio stops answering.
- **QO-100 maths** (`ohsnb/extrig.py`): the radio sits at uplink - LO
  (low-side) or LO - uplink (high-side, spectrum inverted, its USB goes up
  as LSB). The upconverter is a converter from the shared list
  (`rigTxConverter`, below) and has no default; Settings refuses one that
  puts the IF outside the radio's band. The radio's correction is `rigTxCorr`, apart
  from the Pluto's `txCorr`.
- **FM is switched to SSB** (`rigFmToSsb`, on; Brian, 08/10): a radio found
  in FM is put in the sideband that goes up as USB, between overs, and a
  notice says so. FM is the only mode NB changes; the rest it judges.
- **TX lock** without our own baseband: what appeared over the unkeyed
  baseline while the radio was keyed. A CW carrier is measured to a
  fraction of a hertz and corrected from, **between overs** (nobody
  documents whether a 9700 obeys a frequency set mid-over); speech is shown
  landing but never corrected from.
- **Receive audio** mutes (or lowers) while the radio transmits, lifted a
  round trip after it unkeys and at once if the link is lost; the scopes,
  locks and decoders carry on.
- The bandplan guard judges where the radio is aimed and warns - advice,
  since NB cannot stop another radio transmitting.
- No radio is needed to develop or test any of it: `ohscore/rig/civsim.py`
  emulates the 9700's CI-V over TCP (`socket://`), `rigctlsim.py` is a fake
  rigctld, and the simulator puts the emulated radio's transmissions
  through the simulated transponder (`SimDevice.attach_external`).

## Converters — `ohscore/converters.py`, `ohsnb/converters.py`

The LNB and any upconverter are entries in one ordered list of converter
definitions shared with OpenHamShack Radio, after SDR Console's Converter
Definitions window (Brian, 07/10/2026): title, down/up, RX only or RX/TX,
RX and TX offsets in Hz, inverted (high-side LO), and the most drive a
transmitting one takes. `radio = air - offset` (down), `air + offset`
(up), `offset - air` (inverted). Model, presets and their sources:
docs/converters.md. NB chooses three by title:

- `rxConverter`, the LNB - IF = dl − its RX offset + rxCorr. Only a
  down-converter that does not invert: beacon lock and the GPS-LNB
  prediction are written for an IF that rises with the downlink, and no
  QO-100 LNB inverts.
- `txConverter`, between the Pluto and 2400 MHz: none by default. Named,
  the SDR is tuned to its IF (the LO plan and TX lock stay in uplink
  terms), an inverting one has the engine mirror the IQ it sends, and
  txGain is held under its most drive (the Pluto gives +6.5 dBm at 0 dB).
- `rigTxConverter`, the IC-9700's (above).

Each transmitter keeps its own, so switching Settings › Transmitter can
never send the Pluto's output to the IC-9700's upconverter frequency.
The transponder's 8089.5 MHz is not a converter (bandplan.ul applies it):
SDR Console's QO-100 entries carry it as a TX offset, NB's presets do not.
`lnbLo`, `upconverterLo` and `upconverterSide` (up to 0.1.6) are migrated
on load, with identical tuning - tests/test_nb_converters.py compares
against figures taken from the code before the change.

## User interface — `ohscore/ui/`, composed by `ohsnb/ui/`

PyQt6, one main window, dark instrument look by default with a light theme.
Everything that matters is drawn by hand (QPainter on cached images): the
bandscope, the waterfall, the frequency readout, the meters. No stock plotting
library, no fonts or images fetched from anywhere — the machine may be
offline; icons are drawn or embedded.

- **Main window**: wide bandscope + waterfall of the whole transponder with
  the bandplan strip, beacon markers, our passband, TX marker and where our
  own signal actually landed; zoom scope around the VFO; big frequency readout
  (downlink, with uplink beneath); mode, filter, AGC, volume, mic, power;
  lock indicators; the Operate panel underneath (FT8/FT4/Q65 and JS8
  activity, PSK/RTTY/CW terminals with macros, FreeDV status, SSTV
  gallery) behind a fixed tab row with Logbook, Memories and the app's
  own views.
- **Second display** (optional): a separate top-level window the operator
  puts on another screen (Settings → pick screen → full screen), showing a
  large waterfall with decodes on it, or the mode panel, chosen there.
- Mouse: click to tune, drag the passband, wheel to step, drag to pan the
  zoom. Keyboard shortcuts for everything; space for PTT (hold or toggle).

The overhaul of October 2026 (docs/ui-overhaul-2026-10.md, which has the
reasons and Brian's decisions in full) added the layout model below. The
rules are pure modules without Qt, so they are tested on their own and the
window only carries them out.

- **Workspaces** (`ohscore/ui/workspace.py`; groups in `ohscore/modegroups.py`).
  Digital, Voice and Watch decide proportions and the rail cards' forms
  (full, compact, hidden) - never the radio, the scopes' settings or any
  control. Auto follows the mode's group (Pictures & data share Digital);
  W, the tab row's Workspace button or View › Workspace pin one. A mode
  button, mode key or the pad's MODE key is a request to operate and goes
  back to Auto; tuning from the Band list, a memory, a scope or "What is
  this?" is not, so browsing from Watch stays in Watch. A switch only
  resizes and shows or hides existing widgets - no rebuild - because the Mac
  test lost receive blocks to heavy window work. Kept in `ui.json`:
  `workspace` (auto or the pinned one) and `workspaces` (per workspace the
  splitters as fractions, the rail width, the view last shown, the cards
  expanded); fractions, so a layout survives a different window size.
- **Tiers** (`ohscore/ui/layoutrules.py`). Full (from 1500 x 860), Compact
  (from 1180 x 700) and Tight, picked from the window's size divided by the
  text scale, so larger text moves to a smaller tier instead of clipping.
  The tier has the last word over a workspace's forms: Compact narrows the
  rail with every card compact; Tight makes the header one line, puts the
  rail in a drawer behind the tab row's Controls button and gives the scopes
  their least sizes. The minimum is 1024 x 600 at 100 %, scaled with the
  text and capped to the screen. Text size (`textScale`: 1.0, 1.15, 1.3) is
  applied through the same rebuild as a theme change.
- **Mode groups** (`ohscore/modegroups.py`). Voice, Digital, Pictures & data,
  in a fixed order (a button stays where the hand learnt it); recency
  (`modeRecent`) is used only where room is short - the compact group
  buttons and the Ctrl + E menu - never to reorder the full grid. The pad's
  MODE key cycles in group order without recency, because the store form
  has no window prefs. KG-STV is an over button, not a mode: changing the
  rail mode unkeys an outgoing picture.
- **Red means the air** (overhaul section 5.3). `tx`, `txGlow` and `err` are
  for on the air, armed, our own signal over the beacon, LEILA, or an error.
  REC (status strip and pad) is amber; messages to us and our own overs are
  the `own` gold; idle TX marks on the scopes are gold dashed and turn red
  on the air; the S-meter's over-S9 / over-beacon zone is neutral while
  receiving and red only while we transmit, when the passband holds our own
  downlink; Radio's NO CLASS / NO TX HERE are amber (a setting to make, not
  a fault). `tests/test_ui_colours.py` paints the widgets and checks.
- **Transmit state** (`ohscore/ui/txstate.py`). One classifier for the
  Transmit card, the TX tile, Halt TX and the pad's HALT key: **ok**,
  **here** (refused at this frequency or mode now: the engine's sentence),
  **setup** (the licence acknowledgement is missing where the app gates on
  it - a real radio, and in Radio the simulator too) or **never** (this run
  cannot transmit: `--receive-only`, or a receive-only device). setup and
  never may collapse the card to one line; `may_collapse()` holds the rule
  that it **never collapses over a warning** - not while anything is on the
  air (`Face.on_air`, which covers an IC-9700 keyed at its own microphone),
  not while keyed or armed, not while a transmit warning stands. Halting is
  outside the classifier: Esc, the tile and the pad's HALT always halt.
- **Scopes**. The waterfall's only drawn control is the Adjust pill
  (`scope.py` `_levels_button`), the word beside the glyph except in Tight.
  A right-click on either NB scope opens "What is this?" (`ohsnb/ui/whatis.py`)
  instead of a bare menu: `ohsnb/whatis.py`, without Qt, maps the band
  skimmer's entries, the band plan and the over-power watch's events at the
  click to what the signal is and one likely action (Decode FT8, Decode CW,
  Listen, Listen and auto-tune, a Beacon page). Every action only tunes or
  shows a page, and all are greyed while anything is on the air or armed.
  Radio does not have the card yet.
- **The pile-up line** (`ohscore/pileup.py`, no Qt) summarises FT8, FT4 and
  Q65 decodes: who the pile-up is on, the callers, and where we stand; a
  click fills the DX call and sends nothing.
- **S (beacon ref)** (`ohscore/ui/smeter.py`): S = 9 + (passband dB - beacon
  dB) / 6, NB's default unit unless the operator chose one. Gain and AGC
  cancel, since both levels come from the same receive IQ before the AGC.
- **First run** (`ohscore/ui/welcome.py`): both apps ask the licence class;
  Skip on every step saves only "seen", never the radio or the
  acknowledgement, so it can never vouch for a licence nobody ticked. NB
  asks the class beside the callsign and transmits without one (with a
  reminder); Radio asks on the licence step and refuses the box without one.

## Tests

`python3 -m unittest discover -s tests` — tests run behaviour, never read
source text. The simulated transponder makes end-to-end tests possible: key
the sim with a known uplink error and assert TX lock converges on it; feed a
rendered FT8 slot through the sim's channel and assert it decodes.
