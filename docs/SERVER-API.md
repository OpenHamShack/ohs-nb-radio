# The store form's API (QO-100 NB and Radio)

`python3 -m ohsnb --server` and `python3 -m ohsradio --server` run the engine
headless in a container on an OpenHamShack controller, as the store apps
`shack-qo100nb` (kind `qo100nb`) and `shack-radio` (kind `radio`). This is
their wire contract, for OpenHamShack Remote and anyone else who builds a
client (BETA-PLAN D8: "API first for Qt apps, the remote app as the UI").
It is the engine's own API (docs/ENGINE-API.md) over HTTP and WebSocket;
where this file is silent, ENGINE-API.md says what a call does.

The code is `ohscore/server/` (shared), `ohsnb/server.py` and
`ohsradio/server.py` (each app's facts), tested by `tests/test_server.py`. The
desktop window never imports any of it (also tested): no servers inside
the desktop apps.

## Reaching it

- Through the controller only: `<controller>/shack-qo100nb/…`,
  `<controller>/shack-radio/…`. Paths below are relative to that base;
  build no absolute URLs (`X-Forwarded-Prefix` is the controller's).
- The controller's proxy signs the person in and sends the identity
  headers (CONTROLLER-CONTRACT 5.3). The app believes them only when
  `X-OpenHamShack-Proxy-Secret` equals its own `DOCK360_SHACK_PROXY_SECRET`
  (constant-time). Anything else is `401 {"code": "proxy_required"}` - also
  when no secret is configured at all, so the manifest's health check
  accepts 401 as healthy.
- Levels: `view` reads, `control` changes the receiver, `transmit` keys
  and changes Settings-only keys. The proxy enforces the manifest's
  minimums; the app checks again. A refusal is `403 {"code":
  "level_too_low", "level", "needs"}`. `X-OpenHamShack-Transmit` (`full`,
  `digital`, `none`) says what the request may transmit; `digital` admits
  only Enable TX (below).
- Errors are `{"error": "<one sentence>", "code": "<snake_case>"}`.

## Endpoints

| Method, path | Level | Does |
|---|---|---|
| `GET /` | view | a status page and the Recordings (record, play, download, delete); nothing fetched from elsewhere, one small script that posts to `api/recordings` |
| `GET api/status` | view | the app and radio at a glance: `app`, `kind`, `name`, `version`, `running`, `onAir`, `txError`, `txBlocked`, `tx.remote` (the lease; its presence says this server has it), `radioError`, `reconnecting` (true while a claim the broker lost is being taken back; `radioError` then says "Reconnecting to the station…"), `autoTx` (below), `device`, `mode`, `vfo`, `txDial`, `simulator`, `broker`, `audio`, `station`, `sharedLog`, `recordings`, `decoders` (`{"available", "sessions", "cpuMax", "codecsMissing"}`: whether to show a Decoders view; `codecsMissing` is `null` until the first look, never a scan of its own) |
| `GET api/state` | view | `Radio.state()`: every key |
| `GET api/spec` | view | the settings registry (type, limits, choices, help, auth, restart) |
| `POST api/set` | control (transmit for `auth` keys) | `{key: value, …}` or `{"changes": {…}}` through `Radio.set()`, all or nothing; answers `{"changed": {…}}`. The station profile's keys (callsign, locator, country, licence, class, own licence, conditions) are refused: they are set on the controller. So are the device addresses and audio devices (the broker and the API own those). |
| `POST api/start`, `api/stop` | control | start or stop the radio (stop releases the broker's claim) |
| `POST api/ptt` | control to unkey, transmit to key | `{"on": true, "remote": "<client id>"}` keys under that client's lease; `{"on": false}` unkeys. Always `200` with the status: a refused key-up has `onAir` false and `txError` saying why. |
| `POST api/ptt/heartbeat` | transmit | `{"remote": …}` every 1 s once keyed, and while automatic transmit is armed by that client (keyed or not); `409 not_lease_holder` when that client holds neither |
| `POST api/autotx` | transmit to arm, control to disarm | automatic transmit in the digital modes (below). `{"on": true, "remote", …}` arms and chooses; `{"on": false}` disarms and ends any over on the air. `200` with the status; a refusal is `409`/`400` `{"error", "code", "autoTx", "txError"}` |
| `POST api/halt` | control | stop transmitting now, whoever keyed |
| `GET api/memories`, `POST api/recall {"name"}` | view, control | memories |
| `GET api/log`, `POST api/log`, `GET api/log.adi` | view, control, view | the station's shared logbook as this app shows it (ENGINE-API `log_qso`), and ADIF |
| `GET api/events?kinds=state,toast,meter,lock,events` | view | WebSocket: one JSON message per feed item, `{"kind": …, …item}`; first `{"kind": "hello", "status": …}`. `wide` and `zoom` only when asked: `{"kind", "t", "startHz", "binHz", "n", "cdb"}`, `cdb` the bins as little-endian int16 centi-dB in base64. A decode (`events`) that names a sender (`call`) also carries its DXCC entity when cty.dat can place it: `country` (cty.dat's name), `dxcc` (primary prefix), `continent`; absent otherwise. |
| `GET api/events` (state resync) | view | A `state` item is a diff, published once, and a client too slow to drain its queue loses the oldest. When that has happened the server sends the whole state before any later diff: a `state` message in the usual shape, `{"kind": "state", "changes": {…every key…}, "full": true}`. `full` is new and optional (absent on ordinary diffs); a client that merges `changes` as it always has needs no change, and one that wants to can replace its copy instead. Diffs it had not yet received are folded into the snapshot, not sent after it. Other kinds (meter, spectrum, events) still drop oldest-first. |
| `GET api/events?kinds=…,cwskim,cwspot` | view | Radio's CW skimmer (ENGINE-API `cwskim`, `cwspot`). Neither kind is in the default set, so a client that does not ask never gets them. `cwskim` comes once a second, at most `cwSkimMax` channels (about 8 kB/s at 64). `cwspot` is coalesced to at most 5 items a second. A slow client loses snapshots, which do no harm, and spots, which it recovers through `rev`. |
| `GET api/cwskim` | view | Radio only: `{"state", "why"?, "band", "segment", "cover", "channels", "carriers", "spotsRev", "spots": [...]}`. That is the `cwskim` item, plus every spot of the last 30 minutes (at most 500, newest first, each a `cwspot` `spot`). Fetch it when a view opens, and after a gap in `rev`. It is `{"state": "off", ...}` with empty lists while `cwSkim` is false. A tap on a spot or channel only tunes: one `POST api/set {"mode": "cw", "vfo": dial}` at Control level, never a reply and never Enable TX (Brian, 13/10/2026). |
| `GET api/decoders` and the routes under it | view, control | decoder sessions, below ("Decoders") |
| `GET api/events?kinds=…,decoder` | view | the decoder sessions' results, below |
| `GET api/overpower` | view | QO-100 NB only (404 `not_found` elsewhere): `{"state", "beacon", "marginDb", "capture", "lastCapture", "events": [...]}` - signals over the middle beacon and LEILA sirens of the last 30 minutes, open ones first, each as ENGINE-API `overpower` describes. The same list comes as `overpower` items on `api/events?kinds=…,overpower` (not in the default set) on every change and once a second while anything is active. A `leila` entry is the siren pattern measured on six real sirens; why LEILA marks a station is unknown, so show it as "LEILA?". Tapping an entry only tunes: `POST api/set {"vfo": …}` at Control level, never TX. |
| `GET`/`POST`/`DELETE api/smeter/calibrate` | view / control / control | Radio only (404 `not_found` elsewhere, like `api/overpower` above): the S-meter calibration table, below. |
| `POST api/overpower/capture` | control | save the last 20 s of receive IQ now (the LEILA evidence ring; `leilaCapture` must be on): `202 {"ok": true}`, the file then appears in Recordings as `…-LEILA`; `409 nothing_to_save` with the sentence why not. Receive only. |
| `GET api/audio/rx[?channels=1\|2]` | view | receive audio, raw PCM over a long-lived response, its format in the headers before any audio: `Content-Type: audio/L16; rate=<rate>; channels=<n>` and `X-Audio-Format: {"encoding": "s16le", "rate": <rate>, "channels": <n>}`. The rate is the app's: **48000 for Radio** (since 23/10/2026), 12000 for QO-100 NB. **Mono unless `?channels=2`** (below, "Receive audio format"); `400 bad_channels` for anything but 1 or 2 |
| `GET api/audio/tx` | transmit | WebSocket: binary frames of PCM are the microphone while it is open (voice modes; keying is still `api/ptt`), always **12 kHz mono s16le** in both apps; the first text frame is `{"kind": "hello", "format": {"encoding": "s16le", "rate": 12000, "channels": 1}}` |
| `POST api/shack/pad/action` | control (transmit for `power`) | the controller's input host: `{"action", "kind", "step"}` from `<app>/pad-actions.json`; answers the pad faces. `ptt` is refused here: a pad keys through `api/ptt` like any client. |
| `GET api/shack/busy` | the platform | `{"busy": <on air>, "why"}` for the update gate |
| `POST api/shack/release` | the platform | the broker asks for the radio back: `409 {"onAir": true}` while keyed (unless `"stop": true`), else `202` and the radio stops |
| `GET api/recordings` | view | the recordings, newest first, and the status below (Recordings) |
| `GET api/recordings/status` | view | what is recording now, the last that ended, disk use and limits |
| `POST api/recordings/start {"kind": "audio" \| "iq"}` | control | start recording; `400 bad_kind`, `409 already_recording`/`not_running`/`cannot_record`, `507 low_disk` |
| `POST api/recordings/stop {"kind"?}` | control | stop that kind, or both; the status with `stopped` |
| `GET api/recordings/file?id=&part=data\|meta[&download=1]` | view | one file of a recording; `Range: bytes=…` answers `206` |
| `POST api/recordings/delete {"id"}` | control | delete a recording (`409 recording_active` while it records) |

## Decoders

Decoders running beside the mode's, each on a frequency of its own,
whatever the dial does (ENGINE-API `decoders`, RADIO-SDR-PLAN §4.4 in the
openhamshack repo). Milestone 1 has one: RTTY (45.45, 50, 75 Bd; 170, 425,
450, 850 Hz; normal or reversed), shack_sdr's Rust decoder, the same one
the RTTY mode now uses. Nothing here transmits. The mode decoder itself is
unchanged: its decodes still come as `events`, and it is listed as the
session `vfo` while the mode is decoded by shack_sdr.

| Method, path | Level | Does |
|---|---|---|
| `GET api/decoders` | view | `{"decoders": [entry…], "codecs": [codec…], "limits": {"sessions", "cpuMax", "threads"}, "sessions": [session…]}`. Fetch it once when a view opens. The first fetch after a start may take a moment: it is when the codecs are first looked for. |
| `POST api/decoders/sessions` | control | `{"decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45, "shift": 170, "reverse": false}}`. `201` with the session, or `400 bad_params`, `404 unknown_decoder`, `409 decoder_unavailable` (`needs` names a codec when that is why; a slot mode, which runs only as the mode, says so too), `409 outside_span`, `429 too_many_sessions` (`decodersMax`, default 4), `503 not_running`. Sessions are kept in the settings and start again with the radio. |
| `DELETE api/decoders/sessions/{id}` | control | stop it: `{"stopped": true}`; `404 unknown_session` (the `vfo` session stops with its mode, never here) |
| `GET api/decoders/sessions/{id}?since=<rev>` | view | the session, with `results`: its kept results (the last 500 or 30 minutes) newer than `rev`. Fetch it after a gap in `rev`. `404 unknown_session`. |
| `POST api/decoders/codecs/rescan` | control | look for codecs again without a restart: `{"codecs": [...]}` |

Not yet: `listen` (a session's audio in place of the demodulator, M3) and
`api/decoders/files` (a picture a decoder saved, M2).

An entry (the catalogue):

```json
{"id": "rtty", "family": "amateur", "inputs": ["iq"], "rateHz": 12000.0, "bandwidthHz": 3000.0,
 "outputs": ["text"], "panel": "text", "params": [{"key": "baud", "type": "choice", "choices": [45.45, 50.0, 75.0], "default": 45.45}, ...],
 "needs": [], "engine": "shack_sdr", "available": true, "why": null, "whyText": "", "version": "0.1.0", "fixed": true}
```

`panel` says how a client shows the results (`text`, `slots`, `frames`,
`image`, `meta`), so a new decoder needs no client release. `engine` is
the library that decodes (`shack_sdr`, `shack_cw`, `ohsdigi`); `fixed`
whether it can run on a frequency of its own (CW through shack_cw can;
FT8, FT4, Q65 and JS8 run only as the mode).

A session:

```json
{"id": "ds_3f2a", "decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45, "shift": 170},
 "state": "synced", "why": null, "whyText": "", "since": "2026-10-22T10:00:00Z", "rev": 812,
 "stats": {"snrDb": 14.2, "offsetHz": -12.5, "cpu": 0.004, "dropped": 0}, "panel": "text"}
```

`state` is one of `starting`, `running`, `nosignal`, `synced`, `outside`
(its frequency left the receiver's span: fed nothing, and back by itself
when the span covers it), `budget` (paused at `decodeCpuMax`), `error` or
`stopped`. `why` is a code and `whyText` the server's sentence for it;
prefer your own translation of the code (CONTROLLER-CONTRACT §9).

A codec:

```json
{"id": "faad2", "for": ["dabplus", "drm"], "state": "missing", "path": null, "version": null, "why": "not_found",
 "whyText": "Ask your controller's administrator to install faad2 (Controller › Optional libraries).",
 "where": null, "host": true, "shippable": false}
```

`host` is true on a controller: the app cannot install anything, and
says to ask the administrator. Results on `api/events?kinds=…,decoder`
(not in the default set), one message per result:

```json
{"kind": "decoder", "session": "ds_3f2a", "rev": 813, "t": 1792663200.25, "type": "text", "text": "CQ TEST DE ", "offsetHz": -12.5, "snrDb": 14.0}
{"kind": "decoder", "session": "ds_3f2a", "rev": 814, "t": 1792663201.0, "type": "state", "state": "outside", "why": "outside_span", "whyText": "..."}
```

`rev` rises by one per result, per session; a client that sees a gap
fetches the session with `?since=`. `t` is UTC from the samples. Text is
not yet coalesced: RTTY's results come a character or a few at a time,
about seven a second at 45.45 Bd.

## Receive audio format

`GET api/audio/rx` is 16-bit signed little-endian PCM, interleaved when it
has two channels, over a response that never ends (silence while the radio
is stopped, so a gone client is noticed). The format is announced before
the first byte and never changes within a response: read the headers and
play what they say.

- **Rate:** the app's (`audio.rate` in `api/status`): Radio 48000, QO-100
  NB 12000. No query changes it.
- **Channels:** mono unless the client asks `?channels=2`. Stereo is opt-in
  because Remote builds installed before 23/10/2026 follow the announced
  rate but play every stream as one channel. With `?channels=2` the
  response is stereo for its whole life, whatever the mode: a mono mode is
  the same audio on both sides, so a mode change never needs a new
  header. Without it, a stereo mode is sent averaged (L+R)/2, as a mono
  FM receiver plays it. `audio.stereo` in `api/status` says whether the
  current mode is making stereo now (wide FM with its pilot, once the
  stereo decoder is in).

`api/status` `audio`:

```json
{"encoding": "s16le", "rate": 48000, "channels": 1, "stereo": false, "listeners": 1,
 "tx": {"encoding": "s16le", "rate": 12000, "channels": 1}}
```

`rate`/`channels` are what a request with no query gets; `tx` is
`api/audio/tx`'s microphone format.

## S-meter calibration

Radio only (QO-100 NB has no bands, and is outside this: its calibration
stays a desktop-window preference). A calibration says what to add to the
receiver's raw dBFS reading to get dBm, for one radio, one band and (an
SDRplay RSP, say) one antenna input; held in the engine's own `sMeterCal`
setting (ohsradio/state.py, ohscore/smeter_cal.py has the math), so the
store web page and OpenHamShack Remote see the same calibrated S-units the
desktop window does, not a figure only the desktop ever measured.

It does not hold - and is reported as not holding rather than silently
wrong - while the receiver's own AGC (`rxGainMode` not `manual`) chooses
the gain, nobody here knows what it is, or (an SDRplay RSP) its LNA state
(`sdrplayLna`) has moved since the calibration was made: that stage's
steps are not a fixed number of dB, so it cannot be corrected for the way
a later manual `rxGain` change is (dB for dB).

The `meter` feed item (ENGINE-API.md) gains four fields on Radio,
alongside its unchanged raw `rx` (dBFS): `dbm` and `s` (e.g. `"S9+12"`,
IARU Region 1: S9 is -73 dBm below 30 MHz, -93 dBm at and above, 6 dB per
S-unit) while a calibration holds for the dial's current radio, band and
antenna; otherwise both are `null` and `why`/`whyText` say why not
(`between_bands`, `no_calibration`, `agc`, `extra_changed` - an RSP's LNA
state moved - with `why` `null` and `whyText` `""` while calibrated).

| Method, path | Level | Does |
|---|---|---|
| `GET api/smeter/calibrate` | view | `{"calibrations": {key: {"offset", "gain", "when", "extraName"?, "extraValue"?}, ...}}`, every stored entry. `key` is the device, its address, `@`+antenna where the driver reports one, and `\|`+band - not meant to be parsed, only matched against itself. |
| `POST api/smeter/calibrate` | control | `{"dbm": -93}`: the current reading (a 3 s power average, the same ballistics Calibrate… previews) is `-93` dBm. `{"dbfs": -78.2, "dbm": -93}`: a level of `-78.2` dBFS measured some other way is `-93` dBm. `dbm` must be a finite number, -140..+30 dBm (ohscore/smeter_cal.py `PLAUSIBLE_DBM_LO`/`HI` - generous, to catch a typo rather than second-guess a real extreme); otherwise `400 bad_params`. `409 cannot_calibrate` with a sentence while the AGC (or an RSP's LNA state) means no gain is known, between bands, with no reading, or within 3 dB of full scale (clipping). `200 {"calibration": {...}}`, the entry just stored. |
| `DELETE api/smeter/calibrate` | control | clears the calibration for the dial's current radio, band and antenna (not the whole table). `200 {"ok": true}` whether or not one was stored. |

## Recordings

Made and kept on the controller, in `/data/recordings` on the module's data
volume (`/var/lib/dock360/modules/<id>/data/recordings/`), which survives
updates (Brian, 12/10/2026). Receive only: nothing here keys. The API and
the JSON shapes are ohs-libs' `shack_rec` (python/shack_rec/README.md), the
same on Icom and Flex; what is this app's own:

- **`kinds`: `["audio", "iq"]`.** Both may run at once, one of each.
- **Audio** is what `api/audio/rx` sends - demodulated, after the engine's
  noise reduction when `nr` is on - as **FLAC**, 16-bit at the app's audio
  rate (`sampleRate`: 48000 for Radio, 12000 for QO-100 NB): lossless
  (a recording can be decoded again later), played by every browser,
  ExoPlayer and AVPlayer; NB's about 30-45 MB an hour, Radio's about four
  times that. `channels` is 2 when the mode was making stereo as the
  recording started (wide FM once its stereo decoder is in), else 1, and
  holds for the whole file: a later mode change is converted to it (mono
  on both sides, or stereo averaged). The sidecar `<id>.json`
  has `station` (the callsign), `freqHz` (the receive dial), `mode`,
  `radio` (the device), `processing` (`nr`, `nb`, `agc`), and `changes`
  (frequency and mode as they changed, seconds in). The radio stopping
  ends it (`stopped`: "the radio stopped").
- **IQ** is the engine's SigMF recording (ENGINE-API "IQ recording"):
  `.sigmf-data` (ci16_le at the device rate, `sampleRate`) and
  `.sigmf-meta`, exactly what the desktop app writes, so it plays back
  through the `file` device and the `ohsnb.analyse_*` tools read it. It is
  large - 290 MB a minute at 1.2 MS/s - so it stops by itself at
  `RECORDINGS_IQ_MAX_MINUTES` (10) or sooner if the limit or the free space
  would be passed, and the radio stopping ends it.
- **Settings** (module settings, one number each): `RECORDINGS_LIMIT_GB`
  (10: past it the oldest go, never one recording), `RECORDINGS_MIN_FREE_GB`
  (2: nothing starts below it, `507 low_disk`, and a recording stops there),
  `RECORDINGS_AUDIO_MAX_HOURS` (4), `RECORDINGS_IQ_MAX_MINUTES` (10).
- `api/status` carries `recordings: {"kinds", "active"}` (no disk scan),
  so a client knows to show a Record button and whether it is lit.
- The status page at the base path lists them with a player, downloads
  and delete, and has Record audio / Record IQ / Stop.

Status, from `api/recordings/status` (and inside `api/recordings`):

```json
{"recording": true, "kinds": ["audio", "iq"],
 "active": [{"id": "shackqo100nb-20261012-100000Z-10489.750000MHz-USB", "kind": "audio",
             "format": "flac", "startUtc": "2026-10-12T10:00:00Z", "seconds": 12.4,
             "bytes": 98304, "maxSeconds": 14400, "maxBytes": 10000000000,
             "droppedSeconds": 0.0, "freqHz": 10489750000, "mode": "USB"}],
 "last": {"id": "…", "kind": "iq", "stopped": "the time limit", "error": ""},
 "usage": {"bytes": 1234567, "limitBytes": 10000000000, "freeBytes": 80000000000,
           "floorBytes": 2000000000},
 "limits": {"limitBytes": 10000000000, "floorBytes": 2000000000,
            "audioMaxSeconds": 14400, "iqMaxSeconds": 600}}
```

A recording in `api/recordings`'s `recordings` list:

```json
{"id": "shackqo100nb-20261012-100000Z-10489.750000MHz-USB", "kind": "audio", "format": "flac",
 "startUtc": "2026-10-12T10:00:00Z", "endUtc": "2026-10-12T10:05:00Z", "seconds": 300.0,
 "sampleRate": 12000, "channels": 1, "freqHz": 10489750000, "mode": "USB",
 "station": "GM4BRI", "radio": "pluto", "app": "shack-qo100nb", "complete": true,
 "stopped": "by the operator", "recording": false, "bytes": 1601234,
 "parts": {"data": {"name": "….flac", "bytes": 1600000, "type": "audio/flac"},
           "meta": {"name": "….json", "bytes": 1234, "type": "application/json"}}}
```

An IQ one has `"kind": "iq"`, `"format": "sigmf-ci16_le"`, `sampleRate` the
IQ rate, no `channels`, and parts `….sigmf-data`
(`application/octet-stream`) and `….sigmf-meta` (`application/json`).
To play: `api/recordings/file?id=<id>&part=data` (FLAC); to save:
add `&download=1`.

## Transmitting

In this order, and nothing keys otherwise (CONTROLLER-CONTRACT 6.2):

1. the Transmit level;
2. the engine's key-up check - the licence and band plan from the station
   profile and the shared dataset (`ohscore/txguard.py`), the radio's
   range, the gain ceiling, the app's own rules;
3. a broker claim in `tx` mode on the radio and the broker's `onair` yes,
   told the signal: NB the uplink (with TX lock's correction) and the
   occupied width; Radio the occupied signal and the power chain's estimate;
4. the key-up, held under the client's lease: unkeyed 5 s after its last
   heartbeat (`txError` "Transmit stopped: remote controller lost …").

Unkeying runs the other way: RF off, then the broker told and the claim
back to `rx`. A claim the broker takes back unkeys at once and stops the
radio. While the radio is still wanted the server then re-claims it for
receive with `{"reclaim": true}` (CONTROLLER-CONTRACT 7.2: a broker restart
loses every claim), backing off from 1 s to 30 s or waiting the broker's
`retryAfter`; transmitting never resumes by itself. Only `api/stop` or a
hand-over (`api/shack/release`, or `releaseRequested` on a heartbeat) ends
wanting the radio. The engine's own unkeys (time-out, dead air, a refusal on re-check)
end the lease and put the engine's reason in `txError`.

## Automatic transmit (digital modes)

WSJT-X's Enable TX with CAT PTT: the operator arms it, chooses what to
send, and the server keys the radio itself for each over and unkeys at its
end. Code `ohscore/server/autotx.py`, tests `tests/test_server_autotx.py`.

- **Arm:** `POST api/autotx {"on": true, "remote": "<client id>"}`, at
  the Transmit level, in `ft8`, `ft4`, `q65` (sequenced) or `psk31`,
  `psk63`, `psk125`, `rtty`, `cw` (a line at a time), with a callsign in
  the station profile. Arming sends nothing. One client at a time
  (`409 armed_elsewhere`); while armed, no other client may key PTT.
  Never armed after a restart: it lives only in memory.
- **Choose**, in the same body (arming again first if need be):
  - `"cq": true` (optional `"period": "even"|"odd"`, `"offset"` audio Hz
    200-2900, default 1500): call CQ in the slot that can start soonest,
    then every slot of that parity;
  - `"reply": <a decode as api/events sent it>` (`text`, `slot`, `snr`,
    `df`, and `call`/`grid` when the event has them): answer it as the
    desktop's double-click does - the other parity, on its frequency,
    our report from its SNR;
  - `"text": "<line>"` in a text mode: sent now, keyed for its length.
- **Sequencing** is the desktop FT8 panel's (`ohscore/ft8seq.py`): each
  decode addressed to us moves the QSO on; each over is handed to the
  engine just before our slot starts, so the slot before has decoded.
  After 73 (Tx5), or on hearing the other station's 73 once reports are
  exchanged, the QSO is logged and automatic transmit turns itself off.
- **Every over keys through PTT's path** (Transmitting, above): the
  engine's key-up check on the occupied band measured from the rendered
  message, the broker's tx claim and on-air answer, and the lease held
  under the arming client's id. The engine's time-out and watchdog apply.
- **The arm is a lease.** The arming client heartbeats it every 1 s with
  `api/ptt/heartbeat`, between overs as well as during them; 5 s without
  one disarms and ends any over. Also off, and any over ended: `api/halt`,
  `api/ptt {"on": false}`, `api/autotx {"on": false}`, `api/stop`, a lost
  broker claim, a hand-over, a change of mode, and six minutes with no
  operator choice and no answer from the other station (WSJT-X's Tx
  watchdog; heartbeats do not count). Off once an over has ended: a
  refused or cut-short over (its reason in `txError` and `autoTx.why`),
  and the QSO complete. It never re-arms by itself.
- **Each over sent** is published on `api/events` as `{"mode", "t", "dial",
  "tx": {"slot", "df", "text"}}` (`slot` the slot's start, as decodes name
  theirs), for a remote's decode list to show beside what it heard. It has
  no top-level `text` or `slot` on purpose: a reader of decodes (an older
  Remote, the sequencer, the desktop panel) never takes it for a station
  heard. It goes straight to the feed, so no spot or skimmer entry is made.
- `status.autoTx`: `{"armed", "remote", "mode", "active", "dx", "next"
  (the next over's message), "period", "offset", "sequenced", "text",
  "why" (why it last went off)}`.
- **TVs:** the controller caps a TV at Control, so a TV cannot arm -
  unless the controller's administrator has allowed that TV digital-mode
  transmit (Brian, 11/10/2026, openhamshack `docs/REMOTE-KEYS.md`;
  CONTROLLER-CONTRACT 5.5). Such a TV arrives at Control with
  `X-OpenHamShack-Transmit: digital` and may arm this, and heartbeat its
  own arm on `api/ptt/heartbeat` (the manifest marks that route
  `digital: true`); never `api/ptt` on, `api/audio/tx`, or a heartbeat for
  anything but its arm. Each over it sends asks the broker with
  `"digital": true`, and the broker admits that TV for nothing else. With
  no Transmit header (a controller older than 5.5) the level alone decides.

Tested only into the simulator: nothing in this server has keyed a radio.

## Wide FM and listening outside the amateur bands (Radio)

What openhamshack-remote `docs/RADIO-LISTEN-CONTRACT.md` §1-2 asked of the
server, as built on 23/10/2026 (code `ohscore/dsp/wfm.py`,
`ohsradio/radio.py`; tests `tests/test_ham_wfm.py`,
`tests/test_ham_listen.py`, `tests/test_core_wfm.py`).

- **`mode: "wfm"`** is in `api/spec`'s `mode` choices and `state.modes`,
  and is set like any mode: `POST api/set {"changes": {"mode": "wfm"}}`.
  Mono, 50 us de-emphasis by default; `wfmDeemphasis` (control level,
  `50` or `75`, unit us) is the other. The audio is the ordinary
  `api/audio/rx` stream, 48 kHz since 23/10/2026, flat to 15 kHz (it was
  12 kHz and 5 kHz); stereo (`?channels=2`, and `audio.stereo` in status)
  and RDS wait for shack_sdr's decoder (RADIO-SDR-PLAN M3). No squelch in
  wfm: `sqlOpen` reads true.
- **The passband in state:** `rxFilterLo` and `rxFilterHi`, Hz from the
  receive dial (`rxDial`), the demodulator's real edges in every mode.
  wfm is `-90000`/`90000`: a 180 kHz channel, the bank's filter at those
  edges. In the other modes they are what a client computed before from
  `filterLo`/`filterHi`, `cwPitch`/`cwWidth` and `amWidth` (FM is
  ±6250), so drawing from these keys alone is right everywhere.
- **A receiver too slow for it** (under 240 kS/s; a Hermes-Lite 2 at its
  default 192 kS/s or at 48) refuses it: `api/set` answers `400` with the
  sentence, for example "Wide FM needs the receiver to run at 240 kS/s or
  more, and the hl2 runs at 48 kS/s", and `state.modes.wfm` is
  `{"decode": false, "encode": false, "missing": "<that sentence>"}`. The
  RSPdx (2.4 MS/s), RTL-SDR and Pluto (1.2 or 2.4) all take it.
- **Never transmitted.** In wfm `txBlocked` is "WFM is for listening only:
  nothing is ever transmitted in it", whatever the dial, the licence or the
  radio, and every key-up is refused with it (`api/ptt` answers `onAir`
  false with it in `txError`; `send`, Tune and voice memories alike).
  `state.modes.wfm.encode` is false.
- **The listening areas** (contract §2) all receive on an RSPdx: a dial
  anywhere from the lowest to the highest channel of each is taken, the
  passband lies inside the receiver's span there, and a station there is
  heard in the area's mode (tested on an RSPdx-shaped simulator for LW, MW,
  both CB plans, broadcast FM, airband, marine VHF, DAB Band III's dial,
  LPD433 and PMR446). On the RSPdx itself transmit is refused as on any
  receiver ("This radio can only receive"; wfm's own sentence in wfm). On a
  radio that transmits, outside the amateur bands, the licence refuses
  with its usual sentence ("118.0056-118.011 MHz is not an amateur band").
  **LPD433 is the exception:** 433.075-434.775 MHz is inside 70 cm, so a
  licensed amateur may transmit FM there under the licence and band plan
  like anywhere else on 70 cm; Remote should not tag that area "RX" as if
  transmit were impossible.
- **Dials are whole Hz and are never rounded.** `api/set` keeps
  `118008333` (an 8.33 kHz channel) to the hertz in `vfo` and `rxDial`,
  and the engine's channel is cut there exactly (a carrier 1 kHz above it
  is heard at 1000.0 Hz). Only the radio's centre (DC) moves in 1 kHz
  steps, which no client sees.
- **AM is ±4 kHz by default in Radio** (`amWidth` 4000, 1000-5000), wide
  enough for airband voice and AM broadcast; it was ±3 kHz. NB keeps 3000.

## What it is not (yet)

- No web console: Remote is the UI. The status page only says how it is.
- No IC-9700 external transmitter or serial PTT sequencer in the store
  form: a container is given no serial devices for them.
- The one SoapySDR receiver in the store form is Radio's SDRplay RSP
  (since 12/10/2026; QO-100 NB's image has none): `device` soapy is the
  broker's `sdrplay-1`, claimed for receive only. The claim sets
  `soapyArgs` (`driver=sdrplay`, plus the broker device's serial if it has
  one) and keeps any other `key=value` the configured soapyArgs carries,
  which is how the driver's own settings reach it (`rfgain_sel`, the LNA
  state). `soapyAntenna` picks the input (`Antenna C` is an RSPdx's HF
  socket; "" is the driver's default) through `POST api/set` at control
  level, applied live with no restart where the driver allows it
  (SoapySDRPlay3 does); the current input and the inputs the open radio
  reports are `antenna`/`antennas` under `deviceStatus` in `api/state`,
  kept at their last value while the radio is closed. `soapyAntennaLabels`
  is the operator's own name for each input ("Antenna C" -> "80 m
  dipole"), one line of JSON ({"Antenna C": "80 m dipole"}), also set
  through `api/set` at control level: a client names an input as
  "Antenna C - 80 m dipole" by combining `antenna`/`antennas` with this
  the way Settings' Radio page does (ohscore/antennas.py `display_name`).
  Despite the name, `soapyAntenna`/`soapyAntennaLabels` are not only for
  `device` soapy: they apply the same way to `sdrplay` and `rtlsdr`
  below, through shack_sdr's own `antennas()`/`set_antenna` rather than
  SoapySDR's (ohscore/devices/sdrsource.py) - the setting kept its
  SoapySDR-era name because a client is being built against it. A
  key-up through a receiver is refused with "This radio can only receive"
  before the broker is asked. The image runs SDRplay's API service beside
  the server (store/radio/entrypoint.sh) and asks for the USB bus; the
  controller needs a udev rule for the RSP (Host -> Hardware, plugdev).
- Radio's other receive-only receivers go through shack_sdr's own
  bindings, not SoapySDR (RADIO-SDR-PLAN §6): `device` rtlsdr is the
  broker's `rtlsdr-1` (an RTL-SDR, 0bda:2838; the image carries Debian's
  librtlsdr0) and `device` sdrplay the same RSP as soapy, `sdrplay-1`,
  through SDRplay's API directly. The claim's USB serial becomes
  `sdrSerial` (a platform key, like soapyArgs). `rtlsdr` has one input,
  "RX"; `sdrplay`'s inputs depend on the RSP model (SoapySDRPlay3's own
  names - "Antenna A/B/C", "Hi-Z", "Tuner 1/2 ..."), both reported and
  switched through `soapyAntenna` exactly as the soapy path above is.
  `device` libresdr is the broker's `libresdr-1`, opened by the Pluto
  driver at the address the claim gives (`plutoUri`). SDRplay's API stays
  in the image until the platform stages it as a host library (§6.3); an
  image built with
  `SHACK_STORE_DROP_SDRPLAY=1` carries none and starts the service from
  `/opt/hostlibs/sdrplay-api/`, and without it the RSP says "Ask your
  controller's administrator to install SDRplay's API".
- Hermes-Lite 2 discovery uses a LAN broadcast the container's network may
  not pass; give its address in the broker's device instead.
