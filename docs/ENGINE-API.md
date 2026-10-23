# OpenHamShack QO-100 NB engine API

For whoever builds the Qt UI. The UI talks to the engine through one object,
`ohsnb.radio.Radio`, and reads limits and help text from `ohsnb.state.SPEC`;
it never touches numpy DSP or the device. The engine never imports Qt.

`Radio` is `ohscore.engine.Engine` (shared with OpenHamShack Radio: threads,
set/state, feeds, the safety supervisor, the transmit loop, memories, the
log) plus NB's QO-100 hooks (frequency model, beacon and TX lock, the
bandplan guard, the Pluto-dB power control). The API below is the same
either way; docs/ham/DESIGN-HAM.md section 2.4 says which part is whose.

Everything here is exercised by `tests/test_radio.py`, `tests/test_lock.py`, `tests/test_beacon_modes.py`,
`tests/test_modes_glue.py` and (the external transmitter) `tests/test_extrig.py`; if this document and those tests disagree,
the tests are right and this document has a bug.

## Frequencies

All frequencies are Hz, Python floats (DESIGN.md vocabulary):

| name | meaning |
| --- | --- |
| `dl` | downlink, 10 489 500 000 - 10 490 000 000. What the operator sees and types. The VFO is a dl. |
| `ul` | uplink = dl - 8 089 500 000 (`ohsnb.bandplan.ul()` / `.dl()`) |
| `rxCorr` | how far **high** every signal appears (beacon lock). Display and demodulation subtract it, so beacons sit on nominal frequencies. |
| `txCorr` | added to the uplink so our signal lands where the dial says (TX lock). |

The receiver tunes `IF = dl - LO + rxCorr`, LO being the receive
converter's RX offset (`rxConverter`, from `converters`: the LNB; it was
the setting `lnbLo` up to 0.1.6). (DESIGN.md's table writes
`- rxCorr`; that contradicts its own prose - "how far high ... display
subtracts it" - and the prose is what is implemented and tested.)

Spectrum items are **already corrected**: a bin's frequency is the true
downlink frequency, beacons on their nominal marks.

## Lifecycle and threading

```python
from ohsnb.radio import Radio
from ohscore.engine import TxRefused     # also Feed, slot_start
radio = Radio()                    # loads $OHS_NB_CONF / ~/.config/openhamshack-nb/config.json; opens nothing
feeds = {k: radio.subscribe(k, 64) for k in ("wide", "zoom", "meter", "lock", "state", "toast", "events")}
# Both apps also offer "decoders" (the decoder sessions' results, below).
# NB also offers "mmb" (the multimedia beacon), "midtext" (the middle beacon's text) and "kgstv" (KG-STV pictures);
# the Beacon view subscribes to those itself. And "skim" (the band skimmer's list) and "overpower" (signals over the
# beacon, and LEILA's siren), which the Band view subscribes to.
radio.start()                      # opens device + audio, starts receive. Never transmits.
...                                # a QTimer at ~30 Hz: radio.heartbeat(); drain every feed
radio.stop()                       # unkeys, closes, saves
```

- Every method may be called from the Qt main thread; all are thread-safe
  and return quickly (none waits on the device).
- **Watchdog**: if neither `heartbeat()` nor any feed's `drain()`/`get()` is
  called for `watchdogSec` (default 2 s) while transmitting, the engine
  unkeys and posts an error toast. Call `heartbeat()` from the same timer that
  drains the feeds - if the UI hangs, transmit stops.
- After a Settings save that changed a `restart` key, call `stop()` then
  `start()`. That never keys the transmitter (nothing does except `ptt()` and
  `send()`).
- `start()` raises `ohscore.devices.DeviceError` with an operator-readable
  sentence if the device cannot be opened (e.g. "No Pluto at ip:192.168.2.1
  ..."). If the device fails later, the engine unkeys, sets `error`, retries
  every 2 s, and posts a toast when it is back - still unkeyed.

## Radio methods

| call | does | raises |
| --- | --- | --- |
| `Radio(cfg=None, *, conf_path=None, data_dir=None, audio=None, device=None, persist=True)` | `cfg` a dict of state keys (else loaded from the config file); `audio`/`device` inject a backend or device (tests); `persist=False` never writes the config. | |
| `start()` | open device and audio, start threads | `DeviceError` |
| `stop()` | unkey, stop threads, close, save | |
| `set(authorise=False, **changes) -> dict` | validate every change against `state.SPEC` (plus cross-key rules), apply all or none, return the keys that actually changed. Keys marked `auth` need `authorise=True` (pass it only from the Settings dialog). Lowering `txGainCeiling` brings `txGain` down with it. | `ValueError(sentence)` |
| `state() -> dict` | snapshot of every key (settings, controls, status) | |
| `ptt(on: bool)` | key / unkey. Voice modes send the microphone; `cw` keys a steady carrier at `cwPitch` (tune / straight key); digital modes key with the microphone (for external software through a loopback sound device); `freedv` encodes the microphone. `ptt(False)` is a normal end: the engine stops taking audio and lets the device send what it already holds (up to a few hundred ms) before it stops, and `keyed` stays true until it has. | `TxRefused(sentence)` (a `ValueError`) |
| `halt()` | stop transmitting now, dropping whatever the device still holds: Escape, Halt TX, a Stop button. Use `ptt(False)` for a released PTT. | |
| `tx_idle() -> bool` | whether a new over can be keyed now: not `keyed` and the last over's TX thread finished (its key-down done). `keyed` drops at `halt()`, the thread a little later; a caller replacing one over with another (the FT8 panel) waits for this, as `send()` refuses "Already transmitting" until then. | |
| `send(mode, **msg)` | render a whole transmission with the mode's encoder and key for its duration. `mode` must equal the current mode, unless it is one of the app's `OVER_MODES` (NB: `kgstv`), which go from any mode and are judged as themselves. ft8/ft4 start 0.5 s into a slot — the current one if that is at most 1.5 s (FT8) / 0.5 s (FT4) ago, so an answer decoded at the end of a slot goes out in the next, otherwise the next one (`slot_start()`); `period="even"/"odd"` picks the slot parity. `late_start=True` (ft8; the FT8 panel passes it): an over too late for that but asked for within `SLOT_TRUNCATE` (6 s) of the boundary of a slot of that parity starts at once with the symbols already past dropped, the waveform aligned to the slot as a punctual over's would be (WSJT-X's late start; `slot_truncate()`, the measured decode rates in its comment); the over log says how much was dropped. The occupied bandwidth is measured from the rendered audio and checked against the bandplan before keying. Refused before key-up, any mode: a transmission longer than `txTimeoutSec` (it would be cut off part-way). `hsmodem` and `kgstv` also need `callsign` set (their station frame / callsign line carries it). | `ValueError` / `TxRefused` |
| `send_voice(slot)` | send voice memory `slot` (0-5; `ohscore/keyer.py`, files in `<data>/keyer`) in a voice mode: PTT's own request, keyed through the same guard and voice chain (mic gain, compressor, transmit filter, HAM's FM/AM modulators), with the recording read where the microphone would be; the over ends by itself when the recording does. Refused before key-up: not a voice mode, an empty slot, longer than `txTimeoutSec`. `txSource` is `voice:<n>`; the transmit card's standing line (`tx_warn` key `keyer`) says what is going out. With `keyerRepeat`, it goes again `keyerRepeatSec` after each normal end, sent by the supervisor (never feeding the watchdog), until `ptt()` (either way), `halt()`, a change of `vfo`, `txVfo`, `split`, `mode`, RIT/XIT (`KEYER_CANCEL`), `keyerRepeat` off, a refusal or an emergency unkey. `keyer.record(slot)` / `stop_recording()`, `keyer.preview(slot)` (the monitor output; never keys) and `keyer.slots` (store, rename, clear, read_wav) are the editor's; any key-up stops a recording or preview first. | `ValueError` / `TxRefused` |
| `hsmodem_dir() -> Path` | `<data>/hsmodem`: where the hsmodem decoder saves what stations send | |
| `beacon_here(beacon, dl, snap=True)` | click-to-lock: the signal at downlink `dl`, as the scopes show it now, is the `"lower"`, `"middle"` or `"upper"` beacon. While running (and `snap`), the engine looks for a second within 500 Hz of `dl` for the beacon's exact centre (BPSK: the squared line, checked for being the beacon; F1A: the midpoint of its two tones), then sets `rxCorr` (through `set()`, so `rxCorrHand` becomes true) so that centre lands on the beacon's `ref`; with nothing clear there - or stopped, or `snap=False` - `dl` itself is put on the beacon's marker (an F1A beacon's nominal tone). In Auto the tracker restarts there with a +-2 kHz search for 30 s before widening. A toast says what happened. Returns at once. | `ValueError` for another beacon name |
| `auto_tune(dial=None)` | SSB auto-tune (ohscore/dsp/autotune.py): with `dial`, the receive dial is moved there first (`vfo` = dial - RIT); then the receive channel is listened to (`autoBusy` = `"tune"`, `autoHeard` counting the seconds) and, on another thread, the station's suppressed carrier is found from its spectrum and its pitch harmonics (and, when it leaks, the carrier's own line, which `autoTune` then mentions) - a first look after 4 s (the harmonics alone may answer), then one every second until the harmonics and the station's leaked carrier agree, or 12 s have been heard (autotune.Listener). Found: `vfo` (or `rit`, while `ritOn`) moves by the offset through `set()`, `autoTune` says by how much and what was measured, and an info toast. Refused (no voice, a carrier or data mode at the first look; still ambiguous, or settled only by the harmonics with no leaked carrier to confirm them, after 12 s, the refusal then beginning "after 12 s, "; the dial or mode changed while listening): nothing moves, `autoTuneRefused` says why, warn toast. A refusal for want of certainty ends with its guesses ("Best guess +8 Hz, or -135 Hz: press Auto-tune again…"), and an answer's toast with its next best fit; for 30 s (Engine.GUESS_SECONDS), while the dial and mode stay where it left them, `auto_tune()` without `dial` moves straight to the next of them (then back) instead of listening, saying so in `autoTune` and an info toast (Engine._try_guess). Returns at once. | `ValueError` when not running, not USB/LSB, or already listening |
| `best_audio()` | Best audio (ohscore/dsp/autoaudio.py): 4 s of the receive channel plus the noise blanker's impulse count on the wideband stream (`autoBusy` = `"audio"`), then `filterLo`, `filterHi`, `agc`, `nr`, `nrStrength` (when NR is on) and `nb` are set once through `set()`; `autoAudio` is the one-line summary, `autoAudioWhy` a line per setting with its rule. Refused (nothing above the noise): nothing changes, `autoAudioRefused` says why. | as `auto_tune` |
| `subscribe(kind, maxlen=64) -> Feed` | a new bounded feed; any number per kind | `ValueError` for an unknown kind |
| `unsubscribe(feed)` | stop delivering to it | |
| `heartbeat()` | the watchdog's "UI is alive" | |
| `memories() -> list[dict]` | `{name, dl, mode, builtin}`: the built-in presets (beacons, FT8 10489.540, JS8 10489.548, FreeDV 10489.640, emergency 10489.860, contest 10489.870 ...) then the operator's | |
| `save_memory(name, dl=None, mode=None)` / `delete_memory(name)` / `recall(name)` | operator memories (persisted in the config); `recall` sets `vfo` and `mode` | `ValueError` |
| `log_qso(call, *, t=None, dl=None, mode=None, rstSent, rstRcvd, name, grid, comment)` | append to `$OHS_NB_DATA/log.jsonl` (default `~/.local/share/openhamshack-nb/`); frequency and mode default to the radio's | `ValueError` |
| `log_entries() -> list[dict]` | the log | |
| `test_rig(changes=None) -> str` | Settings' "Test connection": read the external radio's frequency once with the link settings in `changes` over the current ones, and return a sentence ("IC-9700 answered: 1296.200000 MHz"). Reads only. Uses the running link when the settings are the same (Windows will not open a COM port twice). | `ohscore.rig.RigError(sentence)` |
| `export_adif(path=None) -> Path` | ADIF 3: PROP_MODE SAT, SAT_NAME QO-100, BAND 13cm / BAND_RX 3cm, FREQ uplink, FREQ_RX downlink | |
| `device_context() -> dict` | the open radio's IIO context attributes (firmware, model, serial), from the context it already holds; `{}` when none is open. Never opens a radio. | |
| `start_recording(limit_s=None, folder=None) -> Path` | record the receive IQ to a SigMF pair in `folder` (default `recordings_dir()`; the store form gives its recordings folder) until `stop_recording()`, `stop()` or `limit_s` seconds (default `recLimitMin` minutes; 0 none); returns the `.sigmf-data` path. Below. | `ValueError(sentence)`: not running, already recording, folder not writable |
| `stop_recording() -> Path or None` | end it; the writer finishes on its own thread and a toast says when it is saved | |
| `recordings_dir() -> Path` | `<data>/recordings` (`ohscore.host.recordings_dir`) | |
| `start_playback(path, loop=None, realtime=True) -> Path` | play a SigMF recording (either file of the pair) through the receiver instead of the radio, receive-only, until `stop_playback()`; `loop` sets `playLoop`; `realtime=False` plays as fast as receive takes it. Below. | `ValueError(sentence)`: recording in progress, not a playable recording, or it does not start (the radio is then as it was) |
| `stop_playback()` | back to the radio: the configured device starts again | `DeviceError` as `start()` |
| `dish_open()` (NB) | dish alignment: measure the middle beacon and the transponder from the receive stream, hold the receive gain where it is, refuse transmit, until `dish_close()`. Opening it twice is opening it once. Below. | `ValueError(sentence)` while transmitting (`keyed`, or `rigKeyed`) |
| `dish_close()` (NB) | end it: the gain back to the operator's setting, the phone page stopped and `dishPhone` false, transmit allowed | |
| `dish_reset()` (NB) | forget `dishBest` | |
| `dish_snapshot() -> dict` (NB) | what the phone page serves: `{open, snr, best, rise, where, tone}` (`tone` the pitch in Hz) | |
| `status_lines` | a deque of the last 120 one-a-second status lines (two minutes), for Help › Save diagnostics… (`ohscore/diag.py`) | |
| `decoders.catalogue() -> list[dict]` | every decoder this installation has, whichever library decodes it (shack_sdr, shack_cw, ohsdigi): `{id, family, inputs, rateHz, bandwidthHz, outputs, panel, params, needs, engine, available, why, whyText, version, fixed}`. `fixed`: can run on a frequency of its own. `[]` without shack_sdr. Below. | |
| `decoders.start(decoder, freq_hz, params=None) -> dict` | a decoder session on `freq_hz` (a dial frequency: the signal's own, RTTY's centre between mark and space), independent of the dial; saved in `decoderSessions` and started again with the radio. Returns the session (below). | `ohscore.decoders.Refused(sentence)` (a `ValueError`) with `code`: `unknown_decoder`, `decoder_unavailable` (`needs` names a codec, if that is why), `bad_params`, `outside_span`, `too_many_sessions` (`decodersMax`), `not_running` |
| `decoders.stop(id) -> bool` | stop a session and forget it; False if there was none | |
| `decoders.sessions() -> list[dict]` | the mode decoder (`id` `"vfo"`, while the mode is decoded by shack_sdr: RTTY) and every fixed session | |
| `decoders.session(id, since=None) -> dict or None` | one session, with `results`: its kept results (the last 500 or 30 minutes) newer than `rev` `since` | |
| `decoders.codecs(rescan=False) -> list[dict]` | every codec the loader knows (codec2, faad2, fdk-aac, mbelib): `{id, for, state, path, version, why, whyText, where, host, shippable}`, `state` `found`, `missing` or `refused`. The first call looks (and probes a new file in a child process); later ones answer from that until `rescan`. | |

`send()` message options by mode (unknown options are dropped, not errors):

| mode | options |
| --- | --- |
| `cw` | `text`, `wpm` (default `cwWpm`); offset is `cwPitch`. Works with no ohscore.modes (built-in keyer). |
| `ft8`, `ft4` | `text` (a standard message, e.g. `"CQ GM4BRI IO86"`), `freq` (audio offset Hz), `period` |
| `psk31`, `psk63`, `psk125`, `rtty` | `text`, `freq` (audio offset Hz) |
| `sstv` | `image` (H x W x 3 uint8 RGB, scaled to fit), `sstvMode` (robot36 default, martinm1, scottie_s1, pd120 - not `mode`, which is send()'s own argument) |
| `hsmodem` (NB) | `name` and `data` (bytes) for a file - frame type from the extension: `.jpg`/`.jpeg` a picture (sent as is), `.txt`/`.blt` ASCII, `.htm(l)` HTML, else binary (zipped, as HSmodem does) - or `text` (sent as `message.txt`, ASCII); `ftype` forces the frame type. Speed is `hsSpeed`, the call and locator `callsign`/`locator` (each overridable as `speed`, `callsign`, `locator`). One transmission is HSmodem's: the first frame repeated for ~6 s (preamble), two station frames, the rest once, the last six times; `ohscore.modes.hsmodem.plan(**msg, speed=)` says its frames and seconds without rendering. Centred 1500 Hz above the dial. |
| `kgstv` (NB, from 0.1.18) | `picture` (H x W x 3 uint8 RGB, any size: cut to 4:3 from the middle and scaled to 320x240, as KG-STV does), `scale` (the JPEG scale index, 10 = x1.0 default; NB offers 8, 10, 12, 15 - `ohscore.modes.kgstv.QUALITIES`). The callsign line is always the station's `callsign` and `locator` (not overridable). An **over mode** (`Engine.OVER_MODES`): sent whatever mode the radio is in, and judged as KG-STV (band-plan class, its measured width) by every check; a change of `mode` while it is keyed unkeys it. `ohscore.modes.kgstv.Transmission(picture, line, scale)` gives its `seconds`, `blocks_sent(t)` and `preview()` without keying. Tones 1200/1800 Hz above the dial (KG-STV's dial: 10489.6249 MHz USB). Through an IC-9700 by CAT PTT as the other CAT modes. |

Whether a mode can decode/encode here is `state()["modes"][mode]` =
`{"decode": bool, "encode": bool, "missing": "sentence saying what to install"}`.
List every mode in the UI; show the sentence instead of controls when it
cannot run.

Other helpers the UI needs:

- `ohsnb.state.SPEC[key]` - type, default, min, max, choices, unit, help, kind, persist, auth, restart.
- `ohsnb.state.MODES` - mode names in display order.
- `ohsnb.bandplan.SEGMENTS` - `(dl_lo, dl_hi, label, allowed mode classes or None, max bandwidth)` for the bandplan strip; `BEACONS` for markers; `segment_at(dl)`; `tx_blocked(lo, hi, mode)`.
- `ohscore.audio.list_devices()` - `[{index, name, inputs, outputs, rate}]` for the Settings audio pickers (choose by name).
- `ohscore.diag` - the log file (`<data>/logs/<app>.log`, started by each app's `main()`), the start-up facts, `redact()`, and the report and zip that `ohscore/ui/diagnostics.py` puts behind Help › Save diagnostics….

## Feeds

`Feed` is a bounded drop-oldest queue: the engine `put()`s and never blocks;
the UI calls `drain(max_items=None) -> list` (oldest first) or `get()` (one
item or `None`). `feed.dropped` counts items a slow consumer lost; `len(feed)`
is what is waiting. A UI that falls behind loses spectrum lines; it can never
stall receive.

| kind | rate | item |
| --- | --- | --- |
| `wide` | `scopeFps` | `(t, start_dl_hz, bin_hz, db)` |
| `zoom` | `scopeFps` | `(t, start_dl_hz, bin_hz, db)` |
| `meter` | 10 Hz | dict, below |
| `lock` | rx: every 0.5 s tracking / ~1 s searching; tx: about once a second while keyed | dict, below |
| `events` | as decoded | dict, below |
| `state` | on change (operator changes at once; engine status batched at up to 10 Hz) | `{"t", "changes": {key: value}}` |
| `toast` | as needed | `{"t", "level": "info"/"warn"/"error", "text"}` |
| `mmb` | as the multimedia beacon delivers (NB only) | dict, below |
| `midtext` | a block about every 25 s while the middle beacon decodes (NB only) | dict, below |
| `kgstv` | a block every second or so while a KG-STV picture comes in (NB only) | dict, below |
| `skim` | once a second of signal while the band skimmer runs (NB only) | `{"t", "entries": [...]}`, below |
| `overpower` | on every change, and once a second while anything is over the beacon or a siren sounds (NB only) | `{"t", "events": [...], "beacon"}`, below |
| `cwskim` | once a second while the CW skimmer runs (Radio only) | `{"t", "state", ...}`, below |
| `cwspot` | as spots are made or change (Radio only) | `{"t", "rev", "spot"}`, below |

All `t` are UNIX wall-clock seconds (float).

Transmit conditions that last are not toasts: they are the status key
`txWarning`, `{"key", "level", "text"[, "detail"]}` or `{}`, which the
transmit card shows as one standing line. Several at once: the highest
level shows, then the higher priority, then the most recent. Set and
cleared by the engine (`tx_warn(key, text, level, priority, detail)`,
`tx_clear(*keys)`); keys today: NB `level` (own downlink over the beacon),
`trim` (the level guard's last trim), `rig-aim` (the IC-9700 transmitting
where NB would not); HAM `power` (estimate over the licence, or unknown),
`plan` (band plan in warn). Refusals and unkeys stay toasts.

### Spectrum items (`wide`, `zoom`)

`(t, start_dl_hz, bin_hz, db)`: `db` is a `numpy.float32` array; bin `i` is
centred on `start_dl_hz + i * bin_hz` (true downlink, rxCorr already taken
out). Levels are dBFS: a full-scale complex tone reads 0 dB in its bin; noise
reads lower as bins narrow, as on any analyser.

- **wide** covers 10489.475-10490.025 MHz (the passband +-25 kHz) with about
  `wideBins` bins (exactly `len(db)`; e.g. 2064 bins of 266.7 Hz at 1.2 MS/s
  and 2048). Each line averages `wideAvg` Hann-windowed FFTs. Because rxCorr
  moves continuously, `start_dl_hz` moves by sub-bin amounts from line to
  line: place each line by its own start rather than assuming a fixed grid
  (or resample) - that is what keeps beacons still on the waterfall while
  the LNB drifts.
- **zoom** is centred on `rxDial + zoomPan` and spans `zoomSpanHz` with about
  `zoomBins` bins (`zoomAvg` averages); its bins sit on a fixed grid relative
  to the centre.

### `meter`

```python
{"t": 1791100000.1, "rx": -78.2,      # dBFS in the receive passband (S-meter)
 "mic": -23.0,                         # microphone level, dBFS (while keyed with mic audio)
 "txPeak": 0.88,                       # modulator envelope peak after ALC, 0..1
 "keyed": False,
 "vsBeacon": -7.9,                     # own downlink vs beacon, dB; None until measured this over
 "beacon": -40.1,                      # beacon power, dBFS
 "rigKeyed": False}                    # the external radio (IC-9700) is transmitting
```

Radio also adds `dbm`, `s`, `why` and `whyText` (docs/SERVER-API.md "S-meter
calibration"): `rx`'s dBFS, read against a calibration held server-side so
every reader agrees, when one holds for the dial's current radio, band and
antenna - else `dbm`/`s` are `None` and `why`/`whyText` say why not.

### `lock`

Receive (`kind: "rx"`), tracking:

```python
{"t": ..., "kind": "rx", "state": "locked",      # "searching" | "locked" | "lost" | "held" (Hold, Manual)
 "rxCorr": 1801.2, "err": 0.4, "rate": 0.12,      # Hz, Hz (last measured, after correction), Hz/s drift
 "snr": 28.6, "used": "middle",                   # dB in 2.5 kHz; beacon steering rxCorr ("" if none)
 "level": -40.1,                                  # beacon power dBFS
 "cross": -0.3,                                   # middle minus lower error, Hz (None unless both heard)
 "beacons": {"middle": {"err": 0.4, "snr": 28.6}, "lower": {"err": 0.7, "snr": 25.1}}}
```

plus `"rejected": [...]`, sentences for any measurement refused as not the
beacon (`"middle at 10489.7454: level not steady, 14 dB swing (speech?)"`).

while searching: `{"t", "kind": "rx", "state": "searching", "rxCorr", "window": 2000.0, "narrow": True,
"found": {"middle": 1800.0, "lower": 1799.0}, "rejected": [...]}` - `window` the half-width searched
(+-2 kHz around a correction worth trusting first, then `beaconSearchHz`), `"confirming": True` while a
single beacon waits to be seen again, `"widened": True` on the search that gave up the narrow window;
plus `"acquired": <Hz>`, `"wide": bool` and `state: "locked"` on the item that ends the search.

In Hold and Manual (`beaconMode`) the items say `state: "held"`: the beacons
measured where the held correction puts them - `err` is how far the beacon
is from there now - and `rxCorr` is never changed by the engine.

`rxCorr` set through `set()` - typed, nudged, click-to-lock - is the
operator's: `rxCorrHand` becomes true, and in Auto the tracker starts again
from it with the narrow search. Only a lock found by a full-width search
clears `rxCorrHand`, and only a correction with it false is used for the
GPS-locked LNB's first `txCorr`.

Transmit (`kind: "tx"`), about once a second while keyed:

```python
{"t": ..., "kind": "tx",
 "err": 2999.8,        # where our signal landed minus where it should, Hz
 "z": 16.2,            # confidence (robust z-score of the correlation peak); >= 8 is believed
 "how": "speckle",     # "spectrum" (carriers/tones) or "speckle" (speech-like, delay-aligned)
 "delay": 0.33,        # measured loop delay, s (speckle only, else None)
 "confident": True,
 "window": 75000.0,    # search half-width this time: 75 kHz until first lock, then 3 kHz
 # only when confident:
 "ownDl": 10489703000.1,   # where our signal actually is (draw it on the scope)
 "vsBeacon": -10.8,
 "txCorr": -3000.1, "applied": -3000.1}   # new txCorr and the step just applied (only if txLock is on)
```

With an external transmitter (`txRadio` not `"sdr"`) the `tx` items come
while *it* is keyed (`rigKeyed`), and differ: `how` is `"carrier"` (the
radio in CW: a line, placed to a fraction of a hertz), `"spectrum"` (an
over NB keyed by CAT PTT: the audio NB sent, matched as the Pluto's
baseband is - FT8's tones wherever the offset put them) or `"band"`
(anything else the radio sends - speech, another program's data: the edge
of the occupied band nearest the carrier, a couple of hundred hertz);
`delay` is None; `applied` is always None and `rigTxCorr`
is the correction as it stands - nothing is applied during the over (see
below).

### `events`

Decoder output as DESIGN.md "Modes" defines it, each with `"mode"`, plus `"t"`
(UNIX time) and `"dial"` (receive dial when decoded):

- ft8/ft4: `{"mode":"ft8","slot":<utc>,"snr":-12,"dt":0.2,"df":1234,"text":"CQ GM4BRI IO86","call":"GM4BRI","grid":"IO86"}`,
  plus `"ap":"a1".."a6"` on an a-priori decode and `"lowConfidence":true` on one WSJT-X would mark "?".
  The same whichever decoder produced it (ohsdigi, or jt9: `ft8DecoderInUse`); `{"mode":..,"slot":..,"error":".."}` when a slot could not be decoded at all.
- psk/rtty/cw: `{"mode":"psk31","df":1500,"text":"abc","snr":...}` (streaming text). RTTY's, decoded by
  shack_sdr since Radio's SDR milestone 1, are `{"mode":"rtty","text":"CQ","center":1000.0,"offsetHz":-2.1,"snr":11.0}`:
  `text` may be several characters, `offsetHz` is how far the signal sits from `center`.
- freedv: `{"mode":"freedv","sync":true,"snr":4.1,"text":"..."}`
- sstv: `{"mode":"sstv","state":"start|line|done","name":"...png","line":n,"of":m}` - a `start` with `"partial": true` is a picture joined part way through, started from its line syncs with no VIS header heard: its first line is not the top, and it ends when the syncs stop (its PNG has only the lines received)
- hsmodem (NB): `{"mode":"hsmodem","kind":...}` with the kinds and fields of
  the `mmb` feed below - `image`, `bulletin` (a text file or typed message,
  with `text`), `file`, `file_start`, `file_progress`, `file_bad`, `repeat`,
  `station` (the sender's `call`, `loc`, `name`) - files saved under
  `hsmodem_dir()` (a second file of one name as name-2.ext); and `stats`
  about once a second: `{"speed", "mer", "ok", "failed", "sync", "freq",
  "last"}` (`freq`: how far the station is off the dial + 1500 Hz).

The exact fields come from ohscore/modes; the engine adds `t` and `dial` and
guarantees `mode`.

### `decoders`

Decoder sessions' results (`ohscore/decoders.py`; RADIO-SDR-PLAN §4.3-4.4 in
the openhamshack repo). Not in anyone's default set: a client asks for it.
A session is shack_sdr's (Rust decoders on threads of their own, the GIL
released) or a Python-backed one (CW through shack_cw); the mode decoder
is the session `"vfo"` while the mode is decoded by shack_sdr (RTTY), and
keeps sending its `events` items as well, unchanged. A fixed session takes
a 12 kHz channel at its frequency from the engine's filter bank.

```json
{"session": "ds_3f2a", "rev": 813, "t": 1792663200.25, "type": "text", "text": "CQ TEST DE ", "offsetHz": -12.5, "snrDb": 14.0}
{"session": "ds_3f2a", "rev": 814, "t": 1792663201.0, "type": "state", "state": "outside", "why": "outside_span", "whyText": "..."}
```

- `rev` rises by one per result, per session: a gap means one was missed;
  `decoders.session(id, since=rev)` has the last 500 (or 30 minutes).
- `t` is UTC from the samples, never the clock.
- `type`: `text` (`text`, `offsetHz`, `snrDb`), `frame`, `image`, `audio`,
  `meta` (later milestones), or `state` (`state`, `why` a code, `whyText`).
- States: `starting`, `running`, `nosignal`, `synced`, `outside` (the
  frequency left the receiver's span: fed nothing, and back by itself when
  the span covers it), `budget` (paused at `decodeCpuMax`; never the mode
  decoder), `error`, `stopped`.

A session, as `sessions()` gives it:

```json
{"id": "ds_3f2a", "decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45},
 "state": "synced", "why": null, "whyText": "", "since": "2026-10-22T10:00:00Z", "rev": 812,
 "stats": {"snrDb": 14.2, "offsetHz": -12.5, "cpu": 0.004, "dropped": 0, "baud": 45.45, "sync": true, "chars": 120},
 "panel": "text"}
```

### `mmb` (OpenHamShack QO-100 NB)

What QO-100's multimedia beacon carries, decoded in the background from the
wide IQ while `mmbDecode` is on (ohsnb/beaconrx.py; formats in
docs/hsmodem-research.md). Each item has `"mode": "mmb"`, `"t"` and `"kind"`:

- `bulletin`: `{"name", "text", "data", "path"}` - a .blt/.txt file, unzipped; `path` is where it was saved ('' if not)
- `image`: `{"name", "data", "path"}` - a JPEG, as received
- `file`: `{"name", "data", "path"}` - any other file (HTML, binary), unzipped
- `file_start` / `file_progress`: `{"name", "blocks", "have"}` while one arrives; `repeat`, `file_bad`: `{"name"}`
- `dx`: `{"reporter", "qrg_khz", "dxcall", "comment", "utc", "loc"}` - a DX-cluster spot (any band; QO-100 spots are 10489500-10490000 kHz)
- `cw`: `{"text"}` - a CW-skimmer line
- `nbspec` / `wbspec`: `{"values" (uint8 array, 0-63), "start", "step"}` (Hz) - the transponders' spectra as the beacon sends them
- `station`: `{"call", "loc", "name"}`
- `stats`, about once a second: `{"mer", "ok", "failed", "sync", "freq", "last"}` - also in the `mmb*` status keys

### `midtext` (OpenHamShack QO-100 NB)

The middle beacon's text (10489.750 MHz, 400 bit/s BPSK, AO-40 uncoded
blocks; ohsnb/beacontext.py, format in ohsnb/dsp/ao40.py), decoded in the
background from the wide IQ while `midTextDecode` is on, through a 4 kHz
channel of its own that follows `rxCorr`. One item per block whose CRC
passed - a block that fails is only counted, in `midTextLost`:

- `{"t", "type", "lines", "text", "highlight", "repaired", "snr"}` - `type` is the block's first character
  (DK0SB sends `K`, `L`, `M`, `N` in turn, one block every 25.4 s); `lines` its eight 64-character lines,
  right-stripped, bit 7 cleared and anything unprintable shown as `·`; `text` the lines joined with `\n` and
  right-stripped; `highlight` per line, the columns whose bit 7 was set (the spec's "highlighted" characters);
  `repaired` true when the block passed its CRC only after one weak symbol was flipped; `snr` the decoder's
  symbol SNR, dB.

The latest block of each type is also written to `<data>/midbeacon/<type>.txt`
(`ohsnb.beacontext.saved_blocks(folder)` reads them back as
`{type: (text, mtime)}`). The status keys `midText*` (below) say how it
is decoding; `midTextState` is `receiving` while a block has decoded in
the last 60 s, `tracking` with the carrier found and none yet, `searching`
before that.

### `kgstv` (OpenHamShack QO-100 NB)

KG-STV pictures (JJ0OBZ's digital SSTV, heard at 10489.6249 MHz USB;
ohsnb/kgstvrx.py, format in ohscore/dsp/kgstv.py and docs/kgstv-research.md),
received in the background from the wide IQ while `kgstvDecode` is on,
through a 12 kHz channel of its own (1.2 kHz wide) at the tones' centre,
10489.6264, that follows `rxCorr`. Only frames whose CRC passed make
items; one that fails is counted in `kgstvLost`. Each item has `"t"` and
`"kind"`:

- `start`: `{"id", "call"}` - a new picture; `id` counts up from 1 per session.
- `block`: `{"id", "x", "y", "rgb", "call", "blocks", "mode"}` - block (`x`, `y`) of 20 x 15 arrived (or a
  repeat of one missed); `rgb` is its 16 x 16 pixels, 768 bytes of RGB rows; `blocks` how many the picture
  has now; `mode` `MSK/NORM`, `MSK/CONV`, `4L-FSK/NORM` or `4L-FSK/CONV`.
- `done`: `{"id", "call", "why", "blocks", "bad", "mode", "path"}` - `why` is `end` or `abort` (the sender
  said so), `timeout` (30 s with nothing) or `restart` (a block came for a place the picture already had: a
  new picture); `bad` the blocks heard that did not decode; `path` the PNG it was saved as
  (`<data>/kgstv/<UTC>_<call>.png`), or `""` under 50 blocks.
- `call`: `{"call"}` - a station's callsign frame, when it differs from the last one.
- `text`: `{"text", "call"}` - a KG-STV text message (Shift-JIS, decoded).

`ohsnb.kgstvrx.saved_pictures(folder)` lists the kept pictures, newest first,
as `[(path, mtime)]`. The status keys `kgstv*` (below) say how it is
decoding; `kgstvState` is `receiving` while a frame has decoded in the last
30 s, `listening` otherwise.

### `skim` (OpenHamShack QO-100 NB)

The band skimmer's list (ohsnb/skimmer.py; the work is ohsnb/dsp/skim.py,
whose docstring says how): every signal on the transponder, found from the
wide IQ while `skimDecode` is on, whatever the dial is tuned to. Each item
is the whole list as it stands, in frequency order - a UI replaces what it
showed, it does not merge. Each entry:

- `id` - stable while the signal is followed (negative: a calling window);
- `f` - where to point at it, Hz: an SSB voice's dial (its suppressed
  carrier, measured or guessed), a narrow signal's own frequency as a 4 kHz
  look measured it, a calling window's calling frequency, otherwise the
  middle of its occupied band;
- `lo`, `hi` - its occupied band as the 50 Hz band spectrum sees it (a
  calling window: the window);
- `kind` - `ssb` (a voice), `cw` (keyed), `carrier`, `data` (steady: PSK,
  RTTY, a modem; or auto-tune said not a voice), `digital` (a calling
  window: FT8, FT4/FT8 contest, Q65, JS8), `beacon` (the band plan's beacon
  and AMSAT-DL slots, one entry each), `known` (a signal from
  docs/qo100-unidentified-signals.md, by frequency: KG-STV with its dial,
  the ARQ link, the hourly multicarrier, the 10-minute burst), `signal`
  (not looked at yet);
- `label` - what to call it (`SSB`, `SSB?`, `CW`, `KG-STV picture`, `FT8`, ...);
- `mode` - the mode to tune it in; `dial` - where the dial goes, Hz, or None
  (tune as a click at `f` would);
- `exact` - `dial` is measured, not guessed: an SSB dial two auto-tune looks
  agreed on within 10 Hz (`measured` `"twice"`); `"once"` means one look
  answered and its answer is in `dial` but unconfirmed; `""` that `dial` is
  where the spectrum puts the carrier (the band's edge less 300 Hz). A
  dial is dropped (back to the spectrum's guess) when the signal's band no
  longer starts where a voice on it could, and an unconfirmed answer after
  2 minutes;
- `why` - the last look's refusal (auto-tune's own sentence), if it refused;
- `snr` - its strongest 50 Hz bin over the floor, dB; `first`, `last` - UNIX
  seconds it was first and last seen; `active` - seen in the last 20 s
  (quiet ones stay listed, then go after 2 minutes); `looks` - looks taken
  at it; `count` - signals in a calling window (1 otherwise); `calls` (calling
  windows only) - the calls the operator's own FT8/FT4/Q65/JS8 decoder
  heard in that window in the last 2 minutes, newest first.

The skimmer's CPU is a budget, `skimBudget` per cent of one core: what it
uses is charged against the signal heard, and a look - auto-tune on a
voice, the costly part - starts only while the account is in credit. A
slower machine gets fewer looks a minute (`skimLooks`), never a slower
receiver; a skimmer that falls behind drops receive blocks (`skimDropped`)
rather than hold the receive thread. The `skim*` status keys (below) say
how it is doing.

### `overpower` (OpenHamShack QO-100 NB)

The over-power and LEILA watch (ohsnb/overpower.py; the judging is
ohsnb/dsp/overpower.py, shared with `--analyse`), running while `opWatch` is
on, whatever the dial is tuned to. Each item is the whole list of the last
30 minutes - a UI replaces what it showed. `Radio.overpower_view()`
returns the same list with the watch's state (`state`, `beacon`,
`marginDb`, `capture`, `lastCapture`, `events`). Two kinds of entry, both
with `id`, `kind`, `start`, `end` (UNIX seconds), `active`, `freq` (dial
Hz, the middle of `lo`-`hi`), `lo`, `hi`, `width` (Hz) and `call` (the
callsign the operator's own decoder heard there, when it heard exactly
one: during the event, or for a siren in the 20 s before it; else None):

- `kind: "overpower"` - a signal with more power in a 1 kHz slice than the
  middle beacon has in its own, by at least `marginDb` (3 dB), for 2 s or
  more, outside the beacons' guard zones, both read off the same 1 s
  spectral line. `excessDb`: the most it was over. `lo`-`hi`: where its
  own bins were. `leila`: a LEILA siren sounded on it during it or in the
  20 s after; `siren`: that siren's `id`. A pile-up merges into one event
  as wide as the stations in it. Nothing is judged while beacon lock has
  not got the beacon (`beacon` is then `unlocked`) or the beacon does not
  stand 10 dB over the transponder (`weak`).
- `kind: "leila"` - AMSAT-DL's LEILA siren: two tones `lo` and `hi` ~205 Hz
  apart taking turns every 200 ms (docs/qo100-research.md section 9 has
  the six real ones it was built from and checked on). `levelDb`: its power over the
  middle beacon's (about +2 dB measured; this coarser estimate reads a
  few dB high); `on`: the over-power event it marks, if any. The pattern
  is measured; what makes LEILA mark a station is not known, so UIs say
  "LEILA?".

`Radio.leila_capture_now()` saves the evidence ring (below) at once;
ValueError says why it cannot (`opWatch` off, `leilaCapture` off, nothing
kept yet). With `leilaCapture` on, the watch keeps the last 20 s of receive
IQ in memory (ci16, 96 MB at 1.2 MS/s, 100 MB at most) and saves it to
the Recordings folder, as `...-LEILA.sigmf-data`/`-meta`, when a siren
ends - the siren and the over before it. The IQ is after mirroring and
the noise blanker (`openhamshack:capture` says so); `openhamshack:leila` is the
siren's entry. A toast names the file; `opCapture` is its name.

The watch costs about 4.5 % of one core at 1.2 MS/s on the development VM
(1.5 % the spectral lines, 3 % the siren), measured over the real
recordings; `opCpu` says what it costs here. A watch that falls behind
drops receive blocks (`opDropped`) rather than hold the receive thread.

### `cwskim` (Radio)

The CW skimmer (ohs-libs `shack_cw.skim`, run by `ohsradio/cwskim.py` in a
child process): every keyed signal in the CW segment of the band the
receive dial is in, decoded at once, whatever the dial is tuned to and
whatever the mode. Receive only. It never retunes the receiver, and it
skims only the part of the segment that is inside the receiver's span
(CW-SKIMMER-PLAN in the openhamshack repo; Brian's decisions of
13/10/2026). It is **off by default** (`cwSkim`) and switched on per use.

The segment is the rows of the band plan in force (`planInUse`,
`ohsradio/plans`, what the scope's strip draws) whose only mode is CW in
the dial's band, joined. Example: 14 000-14 070 kHz for 20 m in IARU R1
and RSGB 2026.

Each item is the whole picture: a UI replaces what it showed. It does
not merge.

```json
{"t": 1791100000.2, "state": "running", "band": "20m",
 "segment": {"lo": 14000000, "hi": 14070000, "plan": "rsgb-2026"},
 "cover": {"lo": 14000000, "hi": 14070000},
 "spotsRev": 812,
 "channels": [
   {"id": 41, "f": 14025310.0, "dial": 14024610.0, "wpm": 27.5, "snr": 18.2,
    "text": "TU GM4BRI 5NN TEST DL1ABC", "call": "DL1ABC", "kind": "cq",
    "first": 1791099880.1, "active": true, "decoding": true}
 ],
 "carriers": [{"f": 14012000.0, "snr": 30.1}]}
```

- `state`: `running`; `partial` (`cover` narrower than `segment`);
  `outside` (no overlap: `channels` empty, `why` a sentence naming both
  ranges); `off`; `error` (with `why`; the worker is restarted after 2,
  4, 8 ... s, up to 60 s).
- `cover`: the part of the segment being skimmed, 3 kHz in from each edge
  of the receiver's span.
- `channels`: at most `cwSkimMax`, strongest first.
  - `id`: stable while the signal is followed.
  - `f`: the signal's own frequency, Hz.
  - `dial`: where Radio's dial goes to hear it in CW, `f - cwPitch`.
  - `wpm`: the sender's speed, once learnt.
  - `snr`: key-on dB in 500 Hz, averaged over QSB (the RBN's measure).
  - `text`: the channel's last 48 characters, as the neural engine printed
    them with its language model (up to 1 s after they were sent); the
    classic engine's copy only feeds the spots. Keep your own
    history by `id`.
  - `call`: the station identified there, if any.
  - `kind`: `cq`, `dx` or `beacon`, if there is a call.
  - `active`: seen in the last 20 s. A quiet one stays listed for 2 minutes.
  - `decoding`: has a decoder. A track waiting for a channel has none.
- `carriers`: steady unkeyed lines, for a scope layer. Never decoded.
- `spotsRev`: the newest `cwspot` revision. A client that sees it jump past
  what it holds fetches `GET api/cwskim` (SERVER-API).

### `cwspot` (Radio)

`{"t", "rev", "spot": {"id", "call", "f", "dial", "mode": "cw", "wpm",
"snr", "kind", "status", "hits", "first", "last", "band", "channel",
"confidence", "country", "dxcc", "continent"[, "bustedOf"]}}`.

- `rev` counts up by one per item.
- `status`: `valid` (passed the callsign check and seen twice: two
  decodes within 150 Hz and 10 minutes, by either of the two CW engines
  every channel runs, for a call on the callsign list - the RBN week
  shipped with shack_cw, and MASTER.SCP if there is one (`cwSkimScp`) -
  or already confirmed; three for any other call of a
  call's shape in a DXCC entity, and for every call while there is no
  list), `unconfirmed` (fewer: show it dim), `busted` (a Morse-alike misreading of a stronger call
  confirmed beside it: `bustedOf` names that call; never show it as a
  spot), `qsy` (a confirmed call now more than 1 kHz from where it was).
- `kind`: `cq` (calling CQ or a contest CQ), `dx` (sending its call: DE,
  TU, twice over) or `beacon` (VVV DE, /B, an NCDXF frequency).
- `snr`: key-on dB in 500 Hz (the RBN's measure); `wpm`: the median over
  the hits; `f`/`dial` as in `cwskim`, to 10 Hz; `channel` is the `cwskim`
  channel `id`; `first`/`last` UNIX seconds; `confidence` 0-1, for sorting
  and dimming.
- `country`, `dxcc`, `continent`: from the same cty.dat as the decodes
  (the operator's own file first).
- A spot whose status, kind or frequency changes, or whose hits change up
  to 4, is sent again with the same `id`. Otherwise it is sent at most
  every 10 minutes.
- Spots stay on the box (Brian, 13/10/2026): nothing is sent to the RBN,
  PSK Reporter or any other network.

Skimmer output is **never** on `events`. A client's CW strip shows only
the dial's own decoder, and an old client that does not ask for these two
kinds gets neither.

The skimmer's state keys (ohsradio/state.py; Radio only):

| key | kind | type | default | range | meaning |
| --- | --- | --- | --- | --- | --- |
| `cwSkim` | setting | bool | **false** | | Decode every CW signal in the band's CW segment, whatever the dial is on. Off by default; switched on per use. |
| `cwSkimSquelch` | setting | float | 6 | 3 .. 20 dB | The decoders' squelch (`snr_db`). A signal is followed once it stands this plus 2 dB over the floor. |
| `cwSkimMax` | setting | int | 64 | 8 .. 256 | Signals decoded at once, strongest first. |
| `cwSkimScp` | setting | bool | false | | Also download Super Check Partial's MASTER.SCP into the data folder when the skimmer starts, at most once a day (a conditional GET). The callsign list is the RBN week shipped with shack_cw plus MASTER.SCP if it is there (downloaded, or put there by the operator); a call on it is spotted after two decodes, any other after three. |
| `cwSkimState`, `cwSkimWhy` | status | str | `off`, `""` | | As `cwskim`'s `state` and `why`. |
| `cwSkimSignals`, `cwSkimChannels` | status | int | 0 | | Signals being followed / decoders running. |
| `cwSkimCpu` | status | float | 0 | % | The skimmer's own share of one core. |
| `cwSkimDropped` | status | int | 0 | | Receive blocks the skimmer missed because it fell behind. It never holds up receive. |

None of them is a transmit key, so none needs `auth`. Each is an
ordinary `set()` at Control level.

## Safety behaviour the UI can rely on

1. Nothing keys except `ptt(True)` and `send()`: not `start()`, a restart, a
   device reconnect, or `set()`.
2. Every key-up is checked: device can transmit; mode is not AM; the whole
   occupied signal is inside 10489.505-10489.990 and off the beacon,
   broadcast and multimedia segments; the segment allows the mode
   (CW-only, digimodes 500 Hz / 2.7 kHz, SSB-only, mixed); <= 2.7 kHz;
   `txGain <= txGainCeiling`; the TX LO can stay outside the passband. A
   refusal raises `TxRefused` with the reason, sets `txBlocked` and posts a
   warn toast. `state()["txBlocked"]` always says whether keying here
   *would* be refused (`""` if not) - use it to grey out the PTT button.
3. Moving the dial (or split/XIT/mode/filter) while keyed re-checks; if the
   new place is refused the engine unkeys with a toast.
4. TX time-out (`txTimeoutSec`), dead air in voice (`deadAirSec` without mic
   audio) and the UI watchdog (`watchdogSec`) unkey with a toast.
   These, a refusal on re-check (3), a device failure and `halt()` stop RF
   at once and drop what the device has queued. Only a normal end - a
   `send()` all sent, `ptt(False)` - waits for the queue, for at most what
   the device said it held plus 0.25 s and never more than 1 s; an
   emergency during that wait still stops at once.
5. `txGain` can never exceed `txGainCeiling`; only Settings (`authorise=True`)
   can change the ceiling.
6. Beacon level: `levelMode` `limit` (default) trims TX gain down so our
   downlink sits `levelMarginDb` under the beacon; `auto` also raises it
   back, never above the ceiling; `manual` only warns. Going clearly above
   the beacon (+0.5 dB) sets the standing warning `txWarning` (key `level`),
   whatever `levelMode`; it clears once back under 0 dB, and an over that
   ends above it leaves it in the past tense until the next key-up.
7. An external transmitter is never keyed by anything here: see the next
   section.

## An external transmitter (IC-9700)

`txRadio` `"civ"` (CI-V over the radio's USB serial port, `civPort`) or
`"rigctld"` (Hamlib's rigctld, `rigctldHost`:`rigctldPort`) makes another
radio NB's transmitter, through an upconverter (`rigTxConverter`, a
converter from `converters`, and `rigIfBand`). NB never sets its power,
and **keys it only for its own digital-mode overs, and only with
`rigCatPtt` on** (CAT PTT, since 12/10/2026; off by default, and before
then NB could not key it at all). The drivers in `ohscore/rig` can read
frequency, mode, DATA mode, MOD Input and transmit state, set frequency,
set USB or LSB with DATA on or off - used to take the radio out of FM
between overs (`rigFmToSsb`) and, with `rigCatPtt`, to put it in USB-D
for the digital modes - and send PTT on/off only under the digital over
path's `PttPermit` (ohscore/rig/base.py). `start()` opens the link on its own
thread (`ohscore.rig.link.RigLink`, polled every `rigPollMs`); a link that
cannot open or stops answering does not stop the radio - `rigLink` says
`error`/`lost` and `rigError` why, and it retries every 2 s.

- **Tuning**: the radio is kept on `rig = ul(txDial) + rigTxCorr - LO`
  (a down-converter: low-side) or `LO - (ul(txDial) + rigTxCorr)` (an
  inverting one: high-side), LO being the converter's TX offset. It is
  never written while it transmits.
- **Its knob**: a frequency the radio reports that NB did not set moves
  `vfo` (split off) when `rigRxFollows`, else `txVfo` (split on), so
  `txDial` - the TX marker - is where it is aimed. Aimed off the
  transponder, NB leaves both alone until its own dial is moved.
- **Mode**: NB's `mode` follows the radio's USB/LSB/CW on air (`rigMode`)
  when it changes, unless NB is in a digital mode.
- **Keying** (`rigKeyed`): TX lock measures its downlink as above and
  `vsBeacon` its level (warn-only: `levelMode` never acts on it). When it
  unkeys, the median of the over's `carrier` and `spectrum` measurements
  is taken off `rigTxCorr` (kept apart from `txCorr`, the SDR's; at most
  2 kHz an over, and only when at least two, and most, agree to within
  30 Hz) and
  the link retunes the radio; `rigTxCorrTrusted` is set. `band`
  measurements are never applied.
- **Guard**: `rigTxBlocked` judges where it is aimed (`rigAimDl`, `rigMode`,
  and NB's transmit audio edges as its bandwidth) as `txBlocked` judges NB;
  for the radio's own PTT it is advice, and keying there puts up a standing
  error saying NB cannot unkey it. NB's own `ptt()` is always refused
  (`txBlocked` says to key the radio), as is `send()` unless CAT PTT
  applies (below).
- **CAT PTT** (`rigCatPtt`, ohsnb/extrig.py `CatPtt`): a `send()` in
  ft8, ft4, q65, js8, psk31/63/125, rtty or cw, or a `kgstv` picture
  (0.1.18; whatever NB's own mode), keys the radio by CAT.
  `_key` judges it as NB judges itself (licence, band plan, beacons, the
  occupied band measured from the rendered audio) plus the radio's own:
  `rigLink` ok, not already keyed by hand, `rigTxAudioOut` chosen, on the
  transmit frequency, where it is aimed judged as USB-D, and its DATA MOD
  (`rigModInput`) taking USB audio when the link can read it (CI-V; not
  rigctld). The audio goes to `rigTxAudioOut` (never the system default)
  at `rigTxAudioDb`, through `Engine._tx_audio_out`; the Pluto is not
  touched. Sequence: USB-D (LSB-D through an inverting converter;
  re-asserted with a warning toast if changed on the radio since), PTT on,
  read back, `rigPttDelayMs` (a timed over is keyed that much early), the
  audio, drained; audio stopped, `rigPttTailMs`, PTT off, read back.
  `rigCatKeyed` is true meanwhile. `halt()`, a change of mode,
  `rigCatPtt` or `rigTxAudioOut`, the watchdog, the time-out and `stop()`
  unkey at once, without the tail. A link lost mid-over unkeys the engine
  with an error toast saying the radio's state cannot be confirmed, and the
  PTT off is sent again once the link answers.
- **Data mode**: with `rigCatPtt` on, choosing a CAT mode asks the link
  for USB-D once, between overs; choosing USB or LSB after that asks for
  plain SSB. One-shot requests: a mode changed on the radio is left until
  the next CAT key-up.
- **Setup assistant** (ohsnb/rigsetup.py `RigSetup`, CI-V only, nothing on
  connect): `detect()` finds the CI-V address (19 00) and the radio's
  sound device by name; `read()`/`plan()` list DATA MOD, USB MOD Level,
  satellite mode, the band on MAIN and the selected band as now -> will
  be; `apply(rows, keys)` sets the confirmed rows (never while the radio
  or NB transmits, and only if the radio still matches the check) under a
  SetupPermit naming exactly those writes, saving the originals first in
  `rigSetupSaved`; `restore()` puts them back and empties it. While it
  holds the port the link is paused and a CAT over is refused.
  `level_set(dummy_load=True)` keys the radio through the CAT path above
  (source `setup:level`, a 1500 Hz tone, `rigCatPtt` on and a CAT mode
  chosen), reads ALC and Po each 0.3 s, raises the over's level 2 dB at a
  time until ALC moves and stores 3 dB under that as `rigTxAudioDb`; 6 s
  at most, and halt() or any unkey ends it with nothing stored.
- **Receive audio** while it transmits: `rigAudio` mute / lower by
  `rigAudioLowerDb` / keep, as a factor on top of `volume` and `mute`
  (which it never changes), lifted `rttSec` + 0.3 s after it unkeys, and at
  once if the link is lost. Scopes, locks and decoders are unaffected.
- Settings refuse `txRadio` other than `"sdr"` without `rigTxConverter`,
  with a receive-only one, or with one that puts the IF outside the radio's
  band, with a sentence giving the numbers.

## Converters

`converters` is the ordered list of converter definitions
(`ohscore/converters.py`, docs/converters.md): `{"title", "type": "down" |
"up", "use": "rx" | "tx" | "rxtx", "rxOffset", "txOffset", "inverted",
"maxDriveDbm"}` (a stored `rxtx` bool from before `use` is read: true is
"rxtx", false "rx"), titles
unique ignoring case; `radio = air - offset` (down), `air + offset` (up),
`offset - air` (inverted). `set()` refuses a list that does not validate,
whole. NB chooses from it by title:

- `rxConverter`, the LNB: must be a down-converter that does not invert,
  is not TX only, and puts the downlink inside 70 MHz-6 GHz. Required; a config whose
  choice is missing falls back on load to the first that works.
- `txConverter`, between the Pluto and 2400 MHz: `""` (the default) for
  none. One that is named must be TX only or RX/TX; the SDR is then tuned to the IF
  (an inverting one has the engine mirror the IQ it writes) and `txGain`
  is held so that the Pluto's +6.5 dBm at 0 dB, plus `txGain`, stays at or
  under its `maxDriveDbm`. Never inherited from the IC-9700's.
- `rigTxConverter`: above.

A config from 0.1.6 or before with `lnbLo`, `upconverterLo` and
`upconverterSide` is migrated on load (and in a dict handed to `Radio`):
the LNB becomes a receive-only converter (the 9750 MHz preset when it was
9750), the upconverter a TX-only one, inverted when it was high-side;
tuning is identical (`tests/test_nb_converters.py`).

## IQ recording

`start_recording()` writes the receive IQ exactly as the device delivered
it (after any software decimation; before the converter mirror and the
noise blanker; transmit never) to `<base>.sigmf-data` (ci16_le, full scale
32768) and `<base>.sigmf-meta` (ohscore/sigmf.py's docstring has the
format decisions). It never blocks receive: the receive thread hands the
block to a writer thread, and a writer more than two seconds behind loses
blocks, counted in `recDropped` and marked in the file as a gap capture.
Samples the radio's stream never delivered (a stalled link, found by the
prefetch reader, ohscore/rxprefetch.py) are a gap capture too, counted
apart in `recRxLost` and `openhamshack:rx_lost_samples`, and the end toast
says which of the two it was. While it runs, `recording` is true and the
supervisor updates `recSeconds`, `recBytes`, `recDropped` and `recRxLost`; a time limit, a full disk or
`stop()` ends it by itself (`recording` goes false), and a toast says
"Recording saved ..." when the writer has finished. The metadata's
`openhamshack:` extension holds the app, version and OS, the device's status
(no serial), gain, receive settings, callsign, and the app's own
(`_rec_extra`: NB the LNB converter and beacon lock, HAM band and
converter); a capture starts at each retune and gap, and annotations mark
`keyed` and the app's `REC_STATES` (NB `rxLock`, `beaconUsed`,
`rigKeyed`), with `REC_TRACK` values (NB `rxCorr`) once a second in
`openhamshack:track`. NB's `core:frequency` is the LNB's nominal downlink at
DC; the true downlink there is it minus `rxCorr`.

## IQ playback

`start_playback()` stops the radio and starts a "file" device
(`ohscore/devices/filedev.py`, whose docstring has the decisions) in its
place, behind the same device interface: everything after `read()` is
what runs on air. It plays ci16_le (ours), cf32_le, ci8 and cu8, one
channel, at real time. Each capture's `core:frequency` (the on-air
frequency at DC) is matched through the app's own converter, so a
recording plays on the frequencies it was received on whatever LNB the
operator has; the receiver may tune within 0.45 x fs of the recorded
centres, the difference made up by an NCO, and further is refused with a
sentence (`DeviceError` from `set_rx_if`; `rx_range` for HAM's dial
check). Gaps the file marks are silence up to 15 s, longer ones jump the
clock.

Time stamps for the decoders come from the recording (`own_clock`:
`Engine._audio_utc` uses the device's `utc_end`), so FT8/FT4 decodes carry
the slot they were sent in, not now; a loop moves the clock on by whole
minutes, so slots and parity still line up. While playing, `canTx` is
false and `txBlocked` says "Playing a recording: there is no transmitter
...", `start_recording()` is refused, and NB's IC-9700 link is not
started.

The recording seeds the dial and mode it was made on (`openhamshack:receive`)
and, in NB, beacon lock's `rxCorr` (its `openhamshack:beacon_lock.rxCorr`).
Those keys - `Engine.PLAY_KEYS`: `vfo`, `mode`, and NB's `rxCorr`,
`rxCorrHand`, `txCorr`, `txCorrTrusted` - are the recording's while it
plays: every save in the meantime writes the operator's own values in
their place, and `stop_playback()` gives them back. Anything else the
operator changes while playing is kept. Status: `playing`, `playFile`,
`playPos`, `playLength`, `playUtc` (when the sample playing was
recorded), `playEnded`; the end without a loop is silence, a toast, and
`playEnded` - going back to the radio, which may open hardware, is left
to the operator.

## Dish alignment (OpenHamShack QO-100 NB)

`dish_open()` measures from the wideband block the wide scope gets
(`Engine._rx_wide`), never by opening the radio, so it works on a
recording as on air (`ohsnb/dishmeter.py` has the decisions). Every
quarter second: `dishSnr`, the middle beacon's SNR in 2.5 kHz, computed
as beacon lock's (`BeaconTracker._bpsk_snr`) but against the noise
either side of the beacon (+-12 kHz), so it reads 2-3 dB under the
badge's `rxSnr`, which takes its noise inside its own filtered 4 kHz
channel; `dishBest`, the most since opening or `dish_reset()`;
`dishRise`, the median level across the transponder over the median
beside it (None when the sample rate leaves too little room beside it);
`dishWhere`, where the beacon was measured - within 1 kHz of where
`rxCorr` puts it while beacon lock is locked, else the strongest 1.8 kHz
within +-15 kHz of there. Spectra are averaged half-and-half with the
previous quarter second.

While open:

- the receive gain is held: AGC becomes manual at the gain the radio
  reports now (`Device.rx_gain_now()`; Pluto: `hardwaregain`; the
  `rxGain` setting when the radio cannot say), through
  `Engine._rx_gain_wanted`, never through `set()` - `rxGainMode` and
  `rxGain` are not changed, so closing it (or the program stopping)
  leaves the operator's choice as it was. Manual gain is left alone; a
  recording's gain is its own. `dishGain` says which; `dishHeldDb` is the
  gain held, logged when it is held and given back, and a recording
  running marks it (an annotation `dishHeldDb: <dB>`; `dishGain` then says so).
- transmit is refused: `txBlocked` is "Dish alignment is open: close it
  to transmit", and `ptt()`/`send()` raise `TxRefused` with it. NB cannot
  stop an IC-9700 being keyed on the radio itself.
- `dishTone` replaces the receive audio with a sine whose pitch follows
  `dishSnr` (`dishmeter.tone_hz`: 200 Hz at 0 dB, +50 Hz per dB, at most
  1700 Hz), through the same volume and mute (`Engine._rx_heard`).
- `dishPhone` serves the phone page on `dishPort`, on every IPv4
  interface, answering only addresses that are not on the Internet
  (`dishmeter.allowed_client`: private, link-local, loopback, 100.64/10),
  else 403. `GET /` is one self-contained page (no external assets; the
  tone is the phone's WebAudio), `GET /s` is `dish_snapshot()` as JSON,
  `POST /reset` is `dish_reset()`. `dishUrls` lists its addresses;
  `dishPhoneError` says why it did not start (port in use), and
  `dishPhone` goes back to false. `dish_close()` stops it; it is never
  kept on for next time.

## The simulator, and why it is the radio

`simWhy` is set by `start()` from the device it opened - its `kind`, not
the `device` setting, so a recording played back is never "the
simulator" - and cleared by `stop()`: a sentence for the operator when
that device is the simulator, '' otherwise. `simFallback` is true when
the simulator is standing in for a radio that was asked for and could
not be had; a fallback is also said once as a `warn` toast at start. The
window's SIMULATOR badge shows while `simWhy` is not empty, with it as
the hover; a headless run prints it.

The reason comes from `config.DEVICE_WHY` (`"_deviceWhy"`), a key that is
not a setting: `{"fallback": bool, "why": str}`, put into the dict
`Config.load()`/`Config.clean()` return when the saved `device` is not
one the app knows (fallback), or the file could not be read at all
(fallback: every setting is back to its default), and by
`config.override_device()` for `--device` on the command line (not a
fallback). The engine reads it once, in its constructor, from the dict it
is handed or the file it loads; `save()` never writes it. With none, the
simulator is what Settings › Radio says. Choosing a radio in Settings
(`set(device=...)`) ends a fallback or override: from the next start the
sentence is the Settings one.

There is no fallback on a failed open: a radio that cannot be opened
leaves the engine stopped with `error` saying why, never on the
simulator.

## State keys

Generated from `ohsnb/state.py` (the source of truth - read it at run time
rather than copying numbers into the UI). `auth`: needs `set(authorise=True)`.
`restart`: takes effect on the next `start()`. Status keys are read-only.

### setting

| key | type | default | range / choices | unit | persisted | auth | restart | meaning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `device` | enum | 'sim' | sim, pluto, soapy |  | yes | yes | yes | Which radio. The simulated transponder needs no hardware and is the default. |
| `plutoUri` | str | 'ip:192.168.2.1' |  |  | yes | yes | yes | libiio URI: ip:192.168.2.1 (Pluto over USB), ip:pluto.local, ip:<address> (Pluto+, LibreSDR), usb:<bus>.<dev>.<n>. |
| `soapyArgs` | str | 'driver=rtlsdr' |  |  | yes |  | yes | SoapySDR device arguments for a receive-only SDR, e.g. driver=airspy. |
| `soapyAntenna` | str | '' |  |  | yes |  | yes | The SoapySDR receiver's antenna input, as its driver names it (an SDRplay RSPdx: Antenna A, Antenna B or Antenna C). Empty: the driver's default. |
| `sampleRate` | enum | 1200000 | 600000, 1200000 | S/s | yes |  | yes | Complex sample rate shared by receive and transmit. 1.2 MS/s keeps the transponder in the flat middle of the SDR's filter and lets one TX LO position reach almost the whole band; 600 kS/s costs about a third less CPU but cannot transmit on 2400.210-2400.290 MHz. |
| `converters` | list | ['QO-100: LNB 9750 MHz'] |  |  | yes | yes | yes | Converter definitions, in your order: LNBs, upconverters, transverters. Each has a title, a type (down: the radio below the air frequency; up: above), RX only, TX only or RX/TX, RX and TX offsets in Hz, whether it inverts, and the most drive its input takes. |
| `rxConverter` | str | 'QO-100: LNB 9750 MHz' |  |  | yes |  | yes | The LNB: the converter the receiver works through (9750 MHz for a standard 25 MHz-reference LNB). Beacon lock measures its error; you do not need to know it. |
| `txConverter` | str | '' |  |  | yes | yes | yes | The converter between the Pluto and 2400 MHz, if any. Usually none: the Pluto transmits on the uplink itself. |
| `rxGainMode` | enum | 'slow_attack' | manual, slow_attack, fast_attack |  | yes |  |  | Receiver gain control in the SDR. |
| `rxGain` | float | 40 | 0 .. 73 | dB | yes |  |  | Receiver gain when gain control is manual. |
| `beaconMode` | enum | 'auto' | auto, hold, manual |  | yes |  |  | Beacon lock. Auto tracks a beacon and corrects the receive frequency continuously. Hold stops tracking and keeps the correction exactly as it is (a fading beacon, or your own overs). Manual: no tracking; set rxCorr by hand. In Hold and Manual nothing follows the LNB's drift. |
| `beacon` | enum | 'middle' | middle, lower |  | yes |  |  | Beacon to lock to. The middle BPSK beacon is GPS-referenced and mid-band; the lower F1A beacon is the fallback (and is used automatically when the chosen one is not heard). |
| `beaconSearchHz` | float | 50000 | 2000 .. 55000 | Hz | yes |  |  | How far either side of the expected position to search for a beacon. Unmodified LNBs need tens of kHz. |
| `txLock` | bool | True |  |  | yes |  |  | Find our own signal in the downlink while transmitting and correct txCorr. |
| `lnbGpsLocked` | bool | False |  |  | yes |  |  | The LNB has a GPS/reference-locked oscillator. Then the beacon error is mostly the SDR's own reference, and a first txCorr is predicted from it before ever keying. |
| `mmbDecode` | bool | True |  |  | yes |  |  | Receive AMSAT-DL's multimedia beacon (10489.995 MHz: bulletins, pictures, DX-cluster spots, transponder spectra) in the background, from the wide receive signal, whatever you are tuned to. About half a per cent of one core on a laptop. |
| `midTextDecode` | bool | True |  |  | yes |  |  | Decode the middle beacon's text (10489.750 MHz, 400 bit/s BPSK: DK0SB's K, L, M and N message blocks) in the background, whatever you are tuned to. Needs beacon lock, or a receive correction within a few hundred hertz. |
| `kgstvDecode` | bool | True |  |  | yes |  |  | Receive KG-STV pictures (10489.6249 MHz USB: 320x240, about two minutes each, one 16x16 block at a time) in the background, whatever you are tuned to. Pictures of 50 blocks or more are saved. |
| `skimDecode` | bool | True |  |  | yes |  |  | Find and name every signal on the transponder in the background, whatever you are tuned to: SSB voices with their dial measured, CW, data, the beacons and the FT8 windows (the Band view, and marks on the wide scope). |
| `skimBudget` | float | 10 | 1 .. 50 | % | yes |  |  | The most of one processor core the band skimmer may use. Less only means SSB dials are measured more slowly; receiving is never held up. |
| `opWatch` | bool | True |  |  | yes |  |  | Watch the whole transponder for signals with more power than the middle beacon, and for AMSAT-DL's LEILA siren (`overpower`, above). |
| `leilaCapture` | bool | False |  |  | yes |  |  | Keep the last 20 s of receive IQ (about 96 MB) and save it when a LEILA siren ends, or on `leila_capture_now()`. |
| `rttSec` | float | 0.25 | 0.2 .. 0.4 | s | yes |  |  | Satellite round trip (about 0.24-0.28 s depending on where you are). |
| `levelMode` | enum | 'limit' | manual, limit, auto |  | yes |  |  | Own-signal level against the beacon: manual warns only; limit trims TX gain down when we are less than the margin below the beacon; auto also raises it back up (never above the ceiling). |
| `levelMarginDb` | float | 6 | 0 .. 30 | dB | yes |  |  | How far below beacon level our downlink should sit. |
| `txRadio` | enum | 'sdr' | sdr, civ, rigctld |  | yes | yes | yes | What transmits. The SDR (the Pluto) is keyed by OpenHamShack QO-100 NB; an IC-9700 is keyed on the radio itself for voice; NB tunes it, follows it, shows and corrects where it lands, and keys it only for its own digital-mode overs when `rigCatPtt` is on. |
| `civPort` | str | '' |  |  | yes |  | yes | The IC-9700's USB serial port: COM5 (Windows), /dev/ttyUSB0 or /dev/serial/by-id/... (Linux), or socket://host:port for a network serial port. |
| `civBaud` | enum | 115200 | 4800, 9600, 19200, 38400, 57600, 115200 | baud | yes |  | yes | CI-V speed. The IC-9700's CI-V USB Baud Rate is Auto by default, which follows this. |
| `civAddress` | int | 162 | 1 .. 223 |  | yes |  | yes | The radio's CI-V address (the IC-9700's default is A2h). |
| `rigctldHost` | str | '127.0.0.1' |  |  | yes |  | yes | The computer rigctld runs on (127.0.0.1: this one). |
| `rigctldPort` | int | 4532 | 1 .. 65535 |  | yes |  | yes | rigctld's TCP port (4532 unless started with -t). |
| `rigTxConverter` | str | '' |  |  | yes | yes | yes | The IC-9700's upconverter to 2400 MHz, from the converter list. Required, and deliberately without a default: a guessed LO would put the uplink somewhere else entirely. An inverting (high-side) one turns the radio's USB into LSB and runs its knob the other way; OpenHamShack QO-100 NB converts. |
| `rigIfBand` | enum | '23cm' | 23cm, 70cm, 2m |  | yes |  |  | The IC-9700 band feeding the upconverter. |
| `rigPollMs` | int | 100 | 50 .. 1000 | ms | yes |  | yes | How often the radio is asked its frequency and whether it is transmitting: the delay before the TX marker follows its knob and before receive audio mutes. |
| `rigRxFollows` | bool | True |  |  | yes |  |  | Turning the radio's knob moves the receive dial too, as on a transceiver. Off: it moves only the transmit dial (split). |
| `rigFmToSsb` | bool | True |  |  | yes |  |  | When the radio is found in FM, which the narrowband transponder does not carry, switch it to SSB (USB on air), between overs. Off: NB never changes the radio's mode, and only warns. |
| `rigAudio` | enum | 'mute' | mute, lower, keep |  | yes |  |  | Receive audio while the radio transmits. Mute stops your microphone hearing your own downlink from the speaker; the scopes, locks and level measurement carry on regardless. |
| `rigAudioLowerDb` | float | 20.0 | 3 .. 60 | dB | yes |  |  | How far 'Lower' turns receive audio down while the radio transmits. |
| `rigCatPtt` | bool | False |  |  | yes | yes |  | Key the IC-9700 by CAT for NB's own digital-mode overs (FT8, FT4, Q65, JS8, PSK, RTTY and CW lines), never for voice. |
| `rigTxAudioOut` | str | '' |  |  | yes | yes |  | The IC-9700's own sound device for NB's digital-mode audio; never the system default. |
| `rigTxAudioDb` | float | -10.0 | -40 .. 0 | dB | yes |  |  | Level of the digital-mode audio sent to the IC-9700. |
| `rigPttDelayMs` | int | 100 | 0 .. 1000 | ms | yes |  |  | After keying the IC-9700, the wait before the audio starts (PA and upconverter relays). |
| `rigPttTailMs` | int | 50 | 0 .. 1000 | ms | yes |  |  | After the audio has played, the wait before unkeying the IC-9700. |
| `rigSetupSaved` | dict | {} |  |  | yes | yes |  | The IC-9700 settings as they were before the setup assistant changed them (ohsnb/rigsetup.py), for "Restore the radio as it was"; empty when there is nothing to restore. Written only by the assistant. |
| `txFilterLo` | float | 300 | 50 .. 1000 | Hz | yes |  |  |  |
| `txFilterHi` | float | 2700 | 1500 .. 2950 | Hz | yes |  |  | Transmit audio high edge. The occupied width (high - low) may not exceed 2.7 kHz. |
| `txGainCeiling` | float | -10 | -89.75 .. 0 | dB | yes | yes |  | The most transmit gain any control can set. |
| `txTimeoutSec` | float | 300 | 10 .. 1800 | s | yes | yes |  | Unkey after this long transmitting. |
| `deadAirSec` | float | 3 | 1 .. 30 | s | yes | yes |  | Voice modes: unkey after this long with no microphone audio. |
| `watchdogSec` | float | 2 | 0.5 .. 10 | s | yes | yes |  | Unkey if the user interface stops servicing the engine for this long. |
| `audioBackend` | enum | 'portaudio' | portaudio, null |  | yes |  | yes | null runs with no sound card (headless, tests). |
| `audioIn` | str | '' |  |  | yes |  | yes | Microphone device name; empty for the system default. |
| `audioOut` | str | '' |  |  | yes |  | yes | Speaker device name; empty for the system default. |
| `audioOut2` | str | '' |  |  | yes |  | yes | Optional second output carrying receive audio to other software (e.g. a loopback device). |
| `callsign` | str | '' |  |  | yes |  |  |  |
| `locator` | str | '' |  |  | yes |  |  |  |
| `ft8Decoder` | enum | 'auto' | auto, jt9 |  | yes |  |  | Which FT8/FT4 decoder comes first: auto is ohsdigi (OpenHamShack's port of WSJT-X 2.7.0's) where it is built, jt9 otherwise; jt9 puts jt9 first. The other, where installed, is the fallback and checks the first's work (ohscore/modes/decoder_shadow.py). Asked at every slot: no restart. |
| `simRxErrorHz` | float | 1800 | -60000 .. 60000 | Hz | yes |  | yes | Simulated LNB error at start: how far high everything appears. |
| `simDriftHz` | float | 400 | 0 .. 20000 | Hz | yes |  | yes | Size of the simulated LNB's slow wander. |
| `simDriftSec` | float | 600 | 10 .. 7200 | s | yes |  | yes | Timescale of the simulated LNB's wander. |
| `simUlErrorHz` | float | -11000 | -70000 .. 70000 | Hz | yes |  | yes | Simulated SDR transmit error: where our signal really goes, relative to where we aim it. |
| `simRefGainDb` | float | -20 | -89.75 .. 0 | dB | yes |  | yes | Transmit gain at which our simulated downlink equals the beacon. |
| `recLimitMin` | float | 0.0 | 0 .. 600 | min | yes |  |  | Stop an IQ recording by itself after this many minutes (0: only when you stop it). At 1.2 MS/s a minute takes about 290 MB. |
| `checkUpdates` | bool | True |  |  | yes |  |  | Look for a new version when the program starts and once a day while it runs (the window reads it: ohscore/ui/update.py, docs/update-feed.md). |
| `simSignals` | bool | True |  |  | yes |  | yes | Populate the simulated band with other stations. |
| `simSeed` | int | 0 | 0 .. 2.14748e+09 |  | yes |  | yes | 0 = different every run. |
| `simRealtime` | bool | True |  |  |  |  | yes | Pace the simulator to real time (tests turn this off to run faster). |

### control

| key | type | default | range / choices | unit | persisted | auth | restart | meaning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `rxCorr` | float | 0 | -250000 .. 250000 | Hz | yes |  |  | Receive error: how far high every signal appears. Beacon lock maintains it; persisted so the next start begins close. |
| `txCorr` | float | 0 | -120000 .. 120000 | Hz | yes |  |  | Correction added to the uplink so our signal lands where the VFO says. TX lock maintains it. |
| `txCorrTrusted` | bool | False |  |  | yes |  |  | txCorr came from a TX lock (or a GPS-LNB prediction), so the first search can be narrow. |
| `rigTxCorr` | float | 0.0 | -120000 .. 120000 | Hz | yes |  |  | Correction added to the external radio's uplink (its reference and the upconverter's LO error together), kept apart from txCorr, which is the SDR's. TX lock maintains it from a carrier or from NB's own CAT PTT digital overs. |
| `rigTxCorrTrusted` | bool | False |  |  | yes |  |  | rigTxCorr came from a TX lock, so the first search can be narrow. |
| `rxCorrHand` | bool | False |  |  | yes |  |  | rxCorr was last set by the operator (typed, nudged or click-to-lock), not found by beacon lock's own search. The GPS-locked LNB's transmit prediction never uses such a value. |
| `vfo` | float | 1.04897e+10 | 1.04895e+10 .. 1.049e+10 | Hz | yes |  |  | Receive dial (downlink). |
| `mode` | enum | 'usb' | usb, lsb, cw, am, ft8, ft4, q65, js8, psk31, psk63, psk125, rtty, freedv, sstv, hsmodem |  | yes |  |  |  |
| `freedvMode` | enum | '700d' | 700d, 700c, 700e, 1600, 2020 — FreeDV waveform; `state()['modes']['freedv']['waveforms']` maps each to the sentence why it cannot run here (empty = usable) |  | yes |  |  |  |
| `hsSpeed` | enum | 4410 | 1200, 2400, 3000, 4000, 4410, 4800, 5500, 6000, 6600, 7200 (`ohsnb.bandplan.HSMODEM_SPEEDS`: those whose measured width fits 2.7 kHz - all ten) | bit/s | yes |  |  | HSmodem speed, sending and receiving (both stations must agree; changing it swaps the decoder). Widths: `ohsnb.bandplan.HSMODEM_WIDTH`. |
| `split` | bool | False |  |  | yes |  |  | Transmit on txVfo instead of following the receive dial. |
| `txVfo` | float | 1.04897e+10 | 1.04895e+10 .. 1.049e+10 | Hz | yes |  |  | Transmit dial (downlink) when split is on. |
| `rit` | float | 0 | -5000 .. 5000 | Hz | yes |  |  |  |
| `ritOn` | bool | False |  |  | yes |  |  |  |
| `xit` | float | 0 | -5000 .. 5000 | Hz | yes |  |  |  |
| `xitOn` | bool | False |  |  | yes |  |  |  |
| `filterLo` | float | 300 | 0 .. 1000 | Hz | yes |  |  | SSB/digital receive filter low edge. |
| `filterHi` | float | 2700 | 1000 .. 4000 | Hz | yes |  |  | SSB/digital receive filter high edge. |
| `cwWidth` | float | 500 | 50 .. 1500 | Hz | yes |  |  |  |
| `cwPitch` | float | 700 | 300 .. 1200 | Hz | yes |  |  |  |
| `amWidth` | float | 3000 | 1000 .. 5000 | Hz | yes |  |  | AM filter, either side of carrier. |
| `agc` | enum | 'medium' | off, fast, medium, slow |  | yes |  |  |  |
| `rfGain` | float | 0 | -20 .. 60 | dB | yes |  |  | Fixed audio gain when AGC is off. |
| `nb` | bool | False |  |  | yes |  |  | Impulse noise blanker. |
| `nbThreshold` | float | 8 | 3 .. 30 |  | yes |  |  | Blank samples this many times the mean level. |
| `nr` | bool | False |  |  | yes |  |  | Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW and AM. Decoders always get the audio without it. |
| `nrStrength` | float | 50 | 0 .. 100 | % | yes |  |  | How far noise reduction may pull the noise down: 0 % leaves the audio untouched, 100 % up to 40 dB. |
| `volume` | float | 0.5 | 0 .. 1 |  | yes |  |  |  |
| `mute` | bool | False |  |  | yes |  |  |  |
| `txGain` | float | -40 | -89.75 .. 0 | dB | yes |  |  | SDR transmit gain. Cannot exceed txGainCeiling. |
| `micGain` | float | 0 | -20 .. 30 | dB | yes |  |  |  |
| `compressor` | float | 6 | 0 .. 20 | dB | yes |  |  | Speech compression (0 = off). |
| `monitor` | bool | False |  |  | yes |  |  | Hear your own transmit audio. |
| `monitorLevel` | float | 0.3 | 0 .. 1 |  | yes |  |  |  |
| `cwWpm` | float | 20 | 5 .. 50 | wpm | yes |  |  |  |
| `pttMode` | enum | 'hold' | hold, toggle |  | yes |  |  | How the UI's space bar keys (UI-side). |
| `keyerRepeat` | bool | False |  |  |  |  |  | Send a voice memory again and again, keyerRepeatSec after each ends, until PTT, Esc or a retune. |
| `keyerRepeatSec` | float | 10.0 | 1 .. 300 | s | yes |  |  | Voice keyer: the pause between repeats, listening for a reply. |
| `wideBins` | int | 2048 | 256 .. 8192 |  | yes |  |  | Bins across the wide scope. |
| `wideAvg` | int | 2 | 1 .. 16 |  | yes |  |  | FFTs averaged per wide line. |
| `zoomSpanHz` | float | 12000 | 2000 .. 50000 | Hz | yes |  |  |  |
| `zoomBins` | int | 1024 | 128 .. 4096 |  | yes |  |  |  |
| `zoomAvg` | int | 2 | 1 .. 16 |  | yes |  |  |  |
| `zoomPan` | float | 0 | -25000 .. 25000 | Hz | yes |  |  | Zoom scope centre relative to the receive dial. |
| `scopeFps` | float | 20 | 1 .. 50 | lines/s | yes |  |  |  |
| `playLoop` | bool | False |  |  |  |  |  | Start an IQ recording again from the beginning when it ends. |
| `dishTone` | bool | False |  |  |  |  |  | Dish alignment: a tone that rises with the middle beacon's SNR, in place of the receive audio. |
| `dishPhone` | bool | False |  |  |  |  |  | Dish alignment: serve the phone page (the same numbers and a tone) to this network while the tool is open. |
| `dishPort` | int | 8099 | 1024 .. 65535 |  | yes |  |  | Dish alignment: the phone page's port. |

### status

| key | type | default | range / choices | unit | persisted | auth | restart | meaning |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `running` | bool | False |  |  |  |  |  | The engine has the device open and is receiving. |
| `keyed` | bool | False |  |  |  |  |  | Transmitting. |
| `txSource` | str | '' |  |  |  |  |  | What is keying: ptt, send:<mode>, tune, voice:<n> (voice memory n). |
| `txSeconds` | float | 0 |  |  |  |  |  | Seconds into the current transmission. |
| `txOnAir` | bool | False |  |  |  |  |  | The over is on the air: past its slot wait and key-up. keyed is true from the moment an over is queued, so a timed FT8 over is keyed for most of the slot before it; this is what an on-air light should follow. |
| `txStartAt` | float | 0 |  |  |  |  |  | When the queued over's audio is due (UTC seconds), for a timed one (FT8, FT4, Q65, JS8); 0 otherwise. |
| `canTx` | bool | False |  |  |  |  |  | The open device can transmit. |
| `simWhy` | str | '' |  |  |  |  |  | Why the open device is the simulator, as a sentence for the operator ('' when it is not, or nothing is open). |
| `simFallback` | bool | False |  |  |  |  |  | The simulator is standing in for a radio that was asked for and could not be had (simWhy says why). |
| `txBlocked` | str | '' |  |  |  |  |  | Why keying here would be refused right now ('' = it would not). |
| `txWarning` | dict | {} |  |  |  |  |  | The transmit card's one standing warning: {key, level, text} of the most important transmit condition now ({} = none). Engine.tx_warn / tx_clear. |
| `rxDial` | float | 0 |  |  |  |  |  | Downlink the receiver is demodulating (vfo + RIT). |
| `txDial` | float | 0 |  |  |  |  |  | Downlink our transmission is meant to land on (txVfo or vfo, + XIT). |
| `txUl` | float | 0 |  |  |  |  |  | Uplink we are aiming at, including txCorr. |
| `segment` | str | '' |  |  |  |  |  | Bandplan segment under the receive dial. |
| `rxLock` | str | 'off' |  |  |  |  |  | Beacon lock: searching, locked, lost (Auto), hold, manual; off before the radio starts. |
| `rxWindow` | float | 0 |  |  |  |  |  | How far either side the beacon search is looking, Hz: +-2 kHz around the correction held first, then beaconSearchHz. |
| `rxReject` | str | '' |  |  |  |  |  | The last signal beacon lock looked at and refused as not a beacon, and why. |
| `rxErr` | float | 0 |  |  |  |  |  | Last measured beacon error after correction, Hz. |
| `rxRate` | float | 0 |  |  |  |  |  | Drift rate, Hz/s. |
| `rxSnr` | float | 0 |  |  |  |  |  | Beacon SNR in 2.5 kHz, dB. |
| `beaconUsed` | str | '' |  |  |  |  |  | Which beacon is steering rxCorr. |
| `beaconLevel` | float | -200 |  |  |  |  |  | Beacon power, dBFS. |
| `txLockState` | str | 'idle' |  |  |  |  |  | TX lock: idle, searching (own signal not yet found this over), landed (found txErr off the dial; correcting), locked. |
| `txErr` | float | 0 |  |  |  |  |  | Last measured own-signal error, Hz. |
| `txConfidence` | float | 0 |  |  |  |  |  | Peak-to-noise of the last own-signal measurement. |
| `ownDl` | float | 0 |  |  |  |  |  | Where our own signal was last seen landing (corrected downlink, dial frequency). |
| `vsBeacon` | float | None |  |  |  |  |  | Own downlink level relative to the beacon, dB (None until measured). |
| `txPpm` | float | 0 |  |  |  |  |  | txCorr as parts per million of the uplink. |
| `rigLink` | str | 'off' |  |  |  |  |  | External transmitter link: off, connecting, ok, lost, error. |
| `rigError` | str | '' |  |  |  |  |  | Why the external transmitter link is not working, or what it refused. |
| `rigFreq` | float | 0.0 |  |  |  |  |  | The external radio's own frequency (its IF band), Hz. |
| `rigKeyed` | bool | False |  |  |  |  |  | The external radio is transmitting (read from it, whoever keyed it). |
| `rigCatKeyed` | bool | False |  |  |  |  |  | NB has keyed the external radio by CAT for a digital over (`rigCatPtt`). |
| `rigModInput` | str | '' |  |  |  |  |  | Where the external radio takes its transmit audio from in its current mode (mic, acc, mic,acc, usb, mic,usb, lan), when its link can read it. |
| `rigMode` | str | '' |  |  |  |  |  | The external radio's mode on air (after an inverting upconverter). |
| `rigAimDl` | float | 0.0 |  |  |  |  |  | Downlink the external radio is aimed at, rigTxCorr taken out. |
| `rigTxBlocked` | str | '' |  |  |  |  |  | Why NB would not transmit where the external radio is aimed (advisory: NB cannot stop it being keyed). |
| `mmbState` | str | 'off' |  |  |  |  |  | Multimedia beacon receiver: off, searching, receiving, error (or why it is unavailable). |
| `mmbMer` | float | 0.0 |  | dB |  |  |  | Multimedia beacon decode quality: modulation error ratio of its symbols, dB. |
| `mmbFrames` | int | 0 |  |  |  |  |  | Multimedia beacon frames decoded since the radio started. |
| `mmbLost` | int | 0 |  |  |  |  |  | Multimedia beacon frames that came and did not decode. |
| `mmbLast` | float | 0.0 |  |  |  |  |  | When the last multimedia beacon frame decoded (Unix time; 0: none yet). |
| `mmbFreq` | float | 0.0 |  | Hz |  |  |  | How far the multimedia beacon is from 10489.995 MHz after rxCorr, Hz. |
| `mmbCpu` | float | 0.0 |  |  |  |  |  | The multimedia beacon receiver's share of one core, per cent. |
| `midTextState` | str | 'off' |  |  |  |  |  | Middle beacon text receiver: off, searching (for its carrier), tracking (carrier found, no block for a minute), receiving, error. |
| `midTextSnr` | float | 0.0 |  |  |  |  |  | Middle beacon text decode quality: its symbols' SNR, dB (0 while searching). |
| `midTextFrames` | int | 0 |  |  |  |  |  | Middle beacon text blocks decoded since the radio started. |
| `midTextLost` | int | 0 |  |  |  |  |  | Middle beacon text blocks whose sync was heard and which did not decode. |
| `midTextLast` | float | 0.0 |  |  |  |  |  | When the last middle beacon text block decoded (Unix time; 0: none yet). |
| `midTextFreq` | float | 0.0 |  |  |  |  |  | How far the middle beacon is from 10489.750 MHz after rxCorr, Hz, as its decoder has it. |
| `kgstvState` | str | 'off' |  |  |  |  |  | KG-STV picture receiver: off, listening, receiving (a frame decoded in the last 30 s), error. |
| `kgstvFrames` | int | 0 |  |  |  |  |  | KG-STV frames decoded since the radio started (picture blocks, callsigns, end frames). |
| `kgstvLost` | int | 0 |  |  |  |  |  | KG-STV frames whose sync was heard and which did not decode. |
| `kgstvLast` | float | 0.0 |  |  |  |  |  | When the last KG-STV frame decoded (Unix time; 0: none yet). |
| `kgstvCall` | str | '' |  |  |  |  |  | The callsign the last KG-STV station sent ('' until one has). |
| `kgstvFreq` | float | 0.0 |  |  |  |  |  | How far the KG-STV signal's centre is from 10489.6264 MHz after rxCorr, Hz (0 unless receiving). |
| `skimState` | str | 'off' |  |  |  |  |  | Band skimmer: off, running, error. |
| `skimSignals` | int | 0 |  |  |  |  |  | Band skimmer: entries on its list heard in the last 20 s (a calling window counts once). |
| `skimExact` | int | 0 |  |  |  |  |  | Band skimmer: SSB stations among them whose dial auto-tune has measured. |
| `skimCpu` | float | 0.0 |  |  |  |  |  | Band skimmer: its share of one core over the last 10 s, per cent. |
| `skimLevel` | int | 0 |  |  |  |  |  | Band skimmer: 0 uses every spectrum frame; 1 and 2 every second and fourth, when the spectrum alone costs more than half of skimBudget. |
| `skimLooks` | float | 0.0 |  |  |  |  |  | Band skimmer: looks at signals (a voice's dial, a narrow signal's keying) finished in the last minute. |
| `skimDropped` | int | 0 |  |  |  |  |  | Band skimmer: receive blocks it fell too far behind to take, since it started. |
| `opState` | str | 'off' |  |  |  |  |  | Over-power and LEILA watch: off, running, error. |
| `opBeacon` | str | '' |  |  |  |  |  | Whether the last spectral line could be judged: ok, unlocked, weak, none. |
| `opActive` | int | 0 |  |  |  |  |  | Signals over the beacon now. |
| `opLeila` | int | 0 |  |  |  |  |  | LEILA sirens heard in the last 30 minutes. |
| `opCpu` | float | 0.0 |  |  |  |  |  | The watch's share of one core over the last 10 s, per cent. |
| `opDropped` | int | 0 |  |  |  |  |  | Receive blocks the watch fell too far behind to take, since it started. |
| `opCapture` | str | '' |  |  |  |  |  | The last LEILA evidence capture saved ('' until one has been). |
| `dishOpen` | bool | False |  |  |  |  |  | Dish alignment is open (transmit is refused meanwhile). |
| `dishSnr` | float | None |  |  |  |  |  | Dish alignment: the middle beacon's SNR in 2.5 kHz, dB (None: not measured). |
| `dishBest` | float | None |  |  |  |  |  | Dish alignment: the best SNR since it opened or was reset, dB. |
| `dishRise` | float | None |  |  |  |  |  | Dish alignment: the transponder's noise over the noise beside it, dB (None: no room beside it at this sample rate). |
| `dishWhere` | str | '' |  |  |  |  |  | Dish alignment: where the beacon was measured (where beacon lock has it, or the strongest signal near where it should be). |
| `dishGain` | str | '' |  |  |  |  |  | Dish alignment: what it did to the receive gain, and that it is restored. |
| `dishHeldDb` | float | None |  |  |  |  |  | Dish alignment: the receive gain it is holding, dB (None: not holding). Marked in a recording. |
| `dishUrls` | str | '' |  |  |  |  |  | Dish alignment: the phone page's addresses, comma-separated ('' when off). |
| `dishPhoneError` | str | '' |  |  |  |  |  | Dish alignment: why the phone page could not start. |
| `fs` | float | 0 |  |  |  |  |  | Device sample rate. |
| `cpu` | float | 0 |  |  |  |  |  | Receive processing time as a fraction of real time. |
| `overruns` | int | 0 |  |  |  |  |  | Times receive lost samples: a gap in the radio's stream (a stalled link) or processing more than two seconds behind (ohscore/rxprefetch.py). For a device read without the prefetch queue, blocks processed slower than real time. |
| `rxLate` | int | 0 |  |  |  |  |  | Receive blocks that took longer to process than they last; behind the prefetch queue they cost latency, not samples. |
| `rxLostS` | float | 0.0 |  |  |  |  |  | Seconds of receive samples lost in all. |
| `rxBehindS` | float | 0.0 |  |  |  |  |  | Seconds of receive read from the radio and not yet processed. |
| `rxStreamPct` | float | 100.0 |  |  |  |  |  | Share of the radio's stream that reached the program over the last ten seconds, percent (100: nothing known to be missing). |
| `deviceStatus` | dict | {} |  |  |  |  |  | Device status, shown verbatim. |
| `audio` | dict | {} |  |  |  |  |  | Audio status: devices, rates, buffer fill. |
| `modes` | dict | {} |  |  |  |  |  | Per mode: whether it can decode/encode here, or the sentence saying what to install. |
| `error` | str | '' |  |  |  |  |  | Why the engine is not running, if it is not. |
| `recording` | bool | False |  |  |  |  |  | Receive IQ is being recorded. |
| `recFile` | str | '' |  |  |  |  |  | The recording's .sigmf-data file (the last one, once it has stopped). |
| `recSeconds` | float | 0.0 |  |  |  |  |  | Seconds of IQ in the recording. |
| `recBytes` | int | 0 |  |  |  |  |  | Bytes of IQ written to the recording so far. |
| `recDropped` | int | 0 |  |  |  |  |  | Samples the recording lost because the disk could not keep up. |
| `recRxLost` | int | 0 |  |  |  |  |  | Samples the recording is missing because the receive stream never delivered them (counted apart from the disk's). |
| `playing` | bool | False |  |  |  |  |  | An IQ recording is being played instead of the radio (start_playback). |
| `playFile` | str | '' |  |  |  |  |  | The .sigmf-data file being played. |
| `playPos` | float | 0.0 |  |  |  |  |  | Seconds into the recording. |
| `playLength` | float | 0.0 |  |  |  |  |  | The recording's length, seconds. |
| `playUtc` | float | 0.0 |  |  |  |  |  | When the sample being played was recorded (UTC, seconds since 1970). |
| `playEnded` | bool | False |  |  |  |  |  | The recording has been played to its end (and is not looping). |
| `autoBusy` | str | '' |  |  |  |  |  | What is listening to the receive channel now: tune (auto-tune), audio (best audio), or '' for nothing. |
| `autoHeard` | int | 0 |  |  |  |  |  | Seconds of the station auto-tune or best audio has heard so far (while autoBusy). |
| `autoTune` | str | '' |  |  |  |  |  | What the last auto-tune did: how far it moved the dial (or RIT) and what it measured. |
| `autoTuneRefused` | str | '' |  |  |  |  |  | Why the last auto-tune refused to move anything ('' when it did). |
| `autoAudio` | str | '' |  |  |  |  |  | What best audio last measured and chose, in one line. |
| `autoAudioWhy` | str | '' |  |  |  |  |  | Best audio's reason for each choice, one line per setting. |
| `autoAudioRefused` | str | '' |  |  |  |  |  | Why the last best audio changed nothing ('' when it applied). |
| `ft8DecoderInUse` | str | '' |  |  |  |  |  | The decoder FT8/FT4 decodes are coming from: ohsdigi, jt9, or 'jt9 (ohsdigi failed)' after a fallback; '' in other modes. |
| `decoderMissing` | str | '' |  |  |  |  |  | Why the chosen mode cannot be decoded here (no decoder in this installation, or it failed to start); '' when it can, or the mode needs none. |
