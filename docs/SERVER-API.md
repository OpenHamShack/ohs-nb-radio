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
| `GET api/status` | view | the app and radio at a glance: `app`, `kind`, `name`, `version`, `running`, `onAir`, `txError`, `txBlocked`, `tx.remote` (the lease; its presence says this server has it), `radioError`, `reconnecting` (true while a claim the broker lost is being taken back; `radioError` then says "Reconnecting to the station…"), `presence` (Radio on a controller with client presence: `{"service", "connected", "clients", "released"}`, "Client presence" below; absent otherwise), `autoTx` (below), `device`, `mode`, `vfo`, `txDial`, `dialLabel` (Radio: what the dial is on, `null` off any known entry: "The dial label" below; absent in QO-100 NB), `simulator`, `broker`, `audio`, `station`, `sharedLog`, `recordings`, `decoders` (`{"available", "sessions", "cpuMax", "codecsMissing"}`: whether to show a Decoders view; `codecsMissing` is `null` until the first look, never a scan of its own), `rxOwner` (the decoder session holding the receiver, `{}` while the operator has it: "DAB" below), `span` (what the receiver covers and whether background decoder sessions pin it: "The pinned span" below; `{}` in QO-100 NB), `broadcastGain` (the receiver gain a DAB station or wide FM plays with in place of the operator's: "Broadcast gain" below; `{}` while none plays, and in QO-100 NB), `hostLibs` (on a controller, the host libraries it lends, `{}` elsewhere: "Host libraries" below), `dmrIds` (Radio: the DMR callsign list, "DMR" below; absent in QO-100 NB) |
| `GET api/state` | view | `Radio.state()`: every key |
| `GET api/spec` | view | the settings registry (type, limits, choices, help, auth, restart) |
| `POST api/set` | control (transmit for `auth` keys) | `{key: value, …}` or `{"changes": {…}}` through `Radio.set()`, all or nothing; answers `{"changed": {…}}`. A tune out of the span background decoders pin is `409 span_pinned` with the sessions it would stop, unless the body has `"dropSessions": true` ("The pinned span" below); a receiver DAB holds is `409 receiver_busy`. The station profile's keys (callsign, locator, country, licence, class, own licence, conditions) are refused: they are set on the controller. So are the device addresses and audio devices (the broker and the API own those). |
| `POST api/start`, `api/stop` | control | start or stop the radio (stop releases the broker's claim) |
| `POST api/ptt` | control to unkey, transmit to key | `{"on": true, "remote": "<client id>"}` keys under that client's lease; `{"on": false}` unkeys. Always `200` with the status: a refused key-up has `onAir` false and `txError` saying why. |
| `POST api/ptt/heartbeat` | transmit | `{"remote": …}` every 1 s once keyed, and while automatic transmit is armed by that client (keyed or not); `409 not_lease_holder` when that client holds neither |
| `POST api/autotx` | transmit to arm, control to disarm | automatic transmit in the digital modes (below). `{"on": true, "remote", …}` arms and chooses; `{"on": false}` disarms and ends any over on the air. `200` with the status; a refusal is `409`/`400` `{"error", "code", "autoTx", "txError"}` |
| `POST api/halt` | control | stop transmitting now, whoever keyed |
| `GET api/memories`, `POST api/recall {"name"}` | view, control | memories |
| `GET api/log`, `POST api/log`, `GET api/log.adi` | view, control, view | the station's shared logbook as this app shows it (ENGINE-API `log_qso`), and ADIF |
| `GET api/events?kinds=state,toast,meter,lock,events[&client=<id>]` | view | WebSocket: one JSON message per feed item, `{"kind": …, …item}`; first `{"kind": "hello", "status": …}`. `wide` and `zoom` only when asked: `{"kind", "t", "startHz", "binHz", "n", "cdb"}`, `cdb` the bins as little-endian int16 centi-dB in base64; a `wide` item may add `dcBins: [lo, hi]`, the bins (inclusive, into `cdb`) filled in over the receiver's DC spike (Radio: "The DC spike" below). A decode (`events`) that names a sender (`call`) also carries its DXCC entity when cty.dat can place it: `country` (cty.dat's name), `dxcc` (primary prefix), `continent`; absent otherwise. |
| `GET api/spectrum/v1[?client=<id>]` | view | WebSocket: spectrum/1 and overlay/1, the shared waterfall feed and the labels on it (below, "spectrum/1 and overlay/1"). Beside `wide`/`zoom` on `api/events`, which stay as they are. `client` (here, on `api/events` and on `api/audio/rx`): the client's presence id, so the socket closes when that client's presence goes (Radio: "Client presence" below); optional, `400 bad_request` when it is not an id. |
| `GET api/overlay/v1?loHz=&hiHz=` | view | overlay/1's snapshot over HTTP, the same message the socket sends on subscribe (below) |
| `GET api/events` (state resync) | view | A `state` item is a diff, published once, and a client too slow to drain its queue loses the oldest. When that has happened the server sends the whole state before any later diff: a `state` message in the usual shape, `{"kind": "state", "changes": {…every key…}, "full": true}`. `full` is new and optional (absent on ordinary diffs); a client that merges `changes` as it always has needs no change, and one that wants to can replace its copy instead. Diffs it had not yet received are folded into the snapshot, not sent after it. Other kinds (meter, spectrum, events) still drop oldest-first. |
| `GET api/events?kinds=…,cwskim,cwspot` | view | Radio's CW skimmer (ENGINE-API `cwskim`, `cwspot`). Neither kind is in the default set, so a client that does not ask never gets them. `cwskim` comes once a second, at most `cwSkimMax` channels (about 8 kB/s at 64). `cwspot` is coalesced to at most 5 items a second. A slow client loses snapshots, which do no harm, and spots, which it recovers through `rev`. |
| `GET api/cwskim` | view | Radio only: `{"state", "why"?, "band", "segment", "cover", "channels", "carriers", "spotsRev", "spots": [...]}`. That is the `cwskim` item, plus every spot of the last 30 minutes (at most 500, newest first, each a `cwspot` `spot`). Fetch it when a view opens, and after a gap in `rev`. It is `{"state": "off", ...}` with empty lists while `cwSkim` is false. A tap on a spot or channel only tunes: one `POST api/set {"mode": "cw", "vfo": dial}` at Control level, never a reply and never Enable TX (Brian, 13/10/2026). |
| `GET api/decoders` and the routes under it | view, control | decoder sessions, below ("Decoders") |
| `GET api/events?kinds=…,decoder` | view | the decoder sessions' results, below |
| `GET api/fm/stations`, `GET api/dab/stations` | view | Radio only (404 `not_found` elsewhere): the station lists the weekly band scan made, below ("Station lists") |
| `GET api/dab/slides`, `GET api/dab/slides/{sid}` | view | Radio only: the latest SlideShow picture of each DAB service heard, and one service's as the picture itself (`image/jpeg` or `image/png`); below, "DAB pictures and service information" |
| `GET api/dab/logos/{sid}[?variant=square\|wide]` | view | Radio only: a DAB service's logo from its ensemble's SPI, kept across restarts |
| `GET api/dab/schedule/{sid}[?date=YYYY-MM-DD]` | view | Radio only: a DAB service's programme guide from SPI |
| `POST api/scan` | control | Radio only: `{"band": "fm" \| "dab" \| "both"}` scans now; `202 {"bands", "progress"}`, or `400 bad_params`, `409 receiver_busy` / `unsupported` with the sentence, `503 not_running` |
| `GET api/events?kinds=…,stations` | view | Radio only: `{"kind": "stations", "band", "scannedAt", "count", "t"}` each time a scan has made a band's list anew; not in the default set |
| `GET api/overpower` | view | QO-100 NB only (404 `not_found` elsewhere): `{"state", "beacon", "marginDb", "capture", "lastCapture", "events": [...]}` - signals over the middle beacon and LEILA sirens of the last 30 minutes, open ones first, each as ENGINE-API `overpower` describes. The same list comes as `overpower` items on `api/events?kinds=…,overpower` (not in the default set) on every change and once a second while anything is active. A `leila` entry is the siren pattern measured on six real sirens; why LEILA marks a station is unknown, so show it as "LEILA?". Tapping an entry only tunes: `POST api/set {"vfo": …}` at Control level, never TX. |
| `GET`/`POST`/`DELETE api/smeter/calibrate` | view / control / control | Radio only (404 `not_found` elsewhere, like `api/overpower` above): the S-meter calibration table, below. |
| `POST api/overpower/capture` | control | save the last 20 s of receive IQ now (the LEILA evidence ring; `leilaCapture` must be on): `202 {"ok": true}`, the file then appears in Recordings as `…-LEILA`; `409 nothing_to_save` with the sentence why not. Receive only. |
| `GET api/audio/rx[?channels=1\|2][&behind=<s>][&client=<id>]` | view | receive audio, raw PCM over a long-lived response, its format in the headers before any audio: `Content-Type: audio/L16; rate=<rate>; channels=<n>` and `X-Audio-Format: {"encoding": "s16le", "rate": <rate>, "channels": <n>}`. The rate is the app's: **48000 for Radio** (since 23/10/2026), 12000 for QO-100 NB. **Mono unless `?channels=2`** (below, "Receive audio format"); `400 bad_channels` for anything but 1 or 2. Radio: `behind=<s>` plays the timeshift from that long ago (below, "Timeshift"), `409 no_timeshift` without one |
| `GET api/audio/tx` | transmit | WebSocket: binary frames of PCM are the microphone while it is open (voice modes; keying is still `api/ptt`), always **12 kHz mono s16le** in both apps; the first text frame is `{"kind": "hello", "format": {"encoding": "s16le", "rate": 12000, "channels": 1}}` |
| `POST api/shack/pad/action` | control (transmit for `power`) | the controller's input host: `{"action", "kind", "step"}` from `<app>/pad-actions.json`; answers the pad faces. `ptt` is refused here: a pad keys through `api/ptt` like any client. |
| `GET api/shack/busy` | the platform | `{"busy": <on air>, "why"}` for the update gate |
| `POST api/shack/release` | the platform | the broker asks for the radio back: `409 {"onAir": true}` while keyed (unless `"stop": true`), else `202` and the radio stops |
| `GET api/recordings` | view | the recordings, newest first, and the status below (Recordings) |
| `GET api/recordings/status` | view | what is recording now, the last that ended, disk use and limits |
| `POST api/recordings/start {"kind": "audio" \| "iq", "fromSecondsAgo"?, "fromItemStart"?, "lastMinutes"?}` | control | start recording; audio may start in the past (Radio: "Timeshift"); `400 bad_kind`/`bad_params`, `409 already_recording`/`not_running`/`cannot_record`/`no_timeshift`, `507 low_disk` |
| `POST api/recordings/stop {"kind"?}` | control | stop that kind, or both; the status with `stopped` |
| `GET api/recordings/file?id=&part=data\|meta[&download=1]` | view | one file of a recording; `Range: bytes=…` answers `206` |
| `POST api/recordings/delete {"id"}` | control | delete a recording (`409 recording_active` while it records) |
| `GET api/ais/session`, `POST api/ais/session {"client"}`, `DELETE api/ais/session?client=\|all=1` | view, control, control | Radio only: the AIS session a ship map keeps alive (below, "AIS") |
| `GET api/ais/vessels[?since=rev]`, `GET api/ais/vessels/{mmsi}` | view | Radio only: the vessel table, and one vessel with its track |
| `GET api/events?kinds=…,ais` | view | Radio only: each AIS message's sentences, each vessel as it changes, the session; not in the default set |
| `GET api/aprs/session`, `POST api/aprs/session {"client"}`, `DELETE api/aprs/session?client=\|all=1` | view, control, control | Radio only: the APRS session a station map keeps alive (below, "APRS"); receive only |
| `GET api/aprs/stations[?since=rev][&sinceS=seconds]`, `GET api/aprs/stations/{call}` | view | Radio only: the APRS stations heard in the last 24 hours, and one with its track and recent packets |
| `GET api/aprs/messages` | view | Radio only: the APRS messages and bulletins heard (read only: nothing is ever sent) |
| `GET api/events?kinds=…,aprs` | view | Radio only: each packet heard, each station as it changes, each message, the session; not in the default set |
| `GET api/map/info`, `GET api/map/land?bbox=`, `GET api/map/tiles/{z}/{x}/{y}.png` | view | Radio only: the map to draw ships on (below, "Map") |
| `GET api/wxsat/passes[?hours=48]`, `GET api/wxsat/status`, `GET api/wxsat/images` | view | Radio only: weather-satellite passes, their plans and what is being recorded (below, "Weather satellites") |
| `POST`/`DELETE api/wxsat/passes/{id}/record` | control | Radio only: force or skip one pass |
| `GET api/local-frequencies?radiusKm=&category=` | view | Radio only: what there is to listen to near the station (below, "Local frequencies") |
| `POST api/local-frequencies/mine`, `PUT`/`DELETE api/local-frequencies/mine/{id}` | control | Radio only: the operator's own list ("my frequencies") |
| `POST api/local-frequencies/refresh` | control **and** the administrator flag | Radio only: download newer data (below) |
| `GET ui/v1/app` | view | Radio only (404 `not_found` in QO-100 NB): the ui/1 app descriptor the OpenHamShack launcher draws its tiles from (below, "ui/1 screens") |
| `GET ui/v1/screen/{id}[?params]` | view | Radio only: one ui/1 screen document, `radio/home`, `radio/dab`, `radio/fm` or `radio/ships`; `404 unknown_screen`, `406 ui_unsupported` for a client that takes only another major version (below) |
| `GET ui/v1/data/dab` | view | Radio only: the DAB station playing, flat for a screen to bind to (below) |

## Decoders

Decoders running beside the mode's, each on a frequency of its own,
whatever the dial does (ENGINE-API `decoders`, RADIO-SDR-PLAN §4.4 in the
openhamshack repo). DAB (Radio, below: it takes the whole receiver), wide
FM (`wfm`: a 240 kS/s channel of its own, `panel` `meta`, its RDS as the
session's `meta`; refused on every receiver before 23/10/2026, and now
`409 rate_too_low` only below 144 kS/s), CW through shack_cw, RTTY
(45.45, 50, 75 Bd; 170, 425,
450, 850 Hz; normal or reversed), and since 23/10/2026 PSK31/63/125
(`psk`, several stations in one session) and SSTV (`sstv`, fourteen
modes, pictures as files): shack_sdr's Rust decoders, the same ones the
RTTY, PSK and SSTV modes now use (below, "PSK" and "SSTV"). Nothing here
transmits. The mode decoder itself is unchanged: its decodes still come
as `events`, and it is listed as the session `vfo` while the mode is
decoded by shack_sdr.

| Method, path | Level | Does |
|---|---|---|
| `GET api/decoders` | view | `{"decoders": [entry…], "codecs": [codec…], "limits": {"sessions", "cpuMax", "threads"}, "sessions": [session…]}`. Fetch it once when a view opens. The first fetch after a start may take a moment: it is when the codecs are first looked for. |
| `POST api/decoders/sessions` | control | `{"decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45, "shift": 170, "reverse": false}}`. `201` with the session, or `400 bad_params`, `404 unknown_decoder`, `409 decoder_unavailable` (`needs` names a codec when that is why; a slot mode, which runs only as the mode, says so too), `409 outside_span` (in Radio: it, the other sessions and the dial cannot fit in one span), `409 receiver_busy` (DAB plays), `429 too_many_sessions` (`decodersMax`, default 4), `503 not_running`; for DAB also an optional `"client": "<id>"`, the client asking (Radio: the station ends when the last client that asked for it goes, "Client presence" below), and `409 span_pinned` (background sessions pin the span: `sessions` lists them; send `"dropSessions": true` to stop them and play), `409 receiver_busy`, `on_air`, `rate_too_low`, `out_of_range` (below). Sessions are kept in the settings and start again with the radio, except DAB's. |
| `DELETE api/decoders/sessions/{id}` | control | stop it: `{"stopped": true}`; `404 unknown_session` (the `vfo` session stops with its mode, never here) |
| `GET api/decoders/sessions/{id}?since=<rev>` | view | the session, with `results`: its kept results (the last 500 or 30 minutes) newer than `rev`. Fetch it after a gap in `rev`. `404 unknown_session`. |
| `POST api/decoders/sessions/{id}` | control | `{"params": {"service": "C3A7"}}`: change a running session's parameters live (DAB's station). `200` with the session; `400 bad_params` (a value the decoder refuses, or another DAB block), `404 unknown_session` |
| `POST api/decoders/codecs/rescan` | control | look for codecs again without a restart: `{"codecs": [...]}`; also looks at the controller's host libraries again (`hostLibs`) |
| `GET api/decoders/files` | view | the pictures decoders saved (SSTV's, whether a session's or the mode's), newest first: `{"files": [{"name", "session", "decoder", "t", "size"}...]}`. `t` is UTC seconds, `size` bytes; `session` and `decoder` are `""` for a picture saved before 23/10/2026. Answers with the radio stopped too. |
| `GET api/decoders/files/{name}[?download=1]` | view | one of them, `Content-Type: image/png`; `download=1` adds `Content-Disposition: attachment`. `404 no_file` for a name not in the list (a path or a dotted name included). |
| `POST api/decoders/sessions/{id}/listen` | control | `{"listen": true}`: hear the session's sound instead of the demodulator's on `api/audio/rx` (and the desktop's speaker, and a recording); `{"listen": false}` gives the demodulator back. One session at a time: listening to another takes over. `200` with the session (`listening` true or false); `404 unknown_session`, `409 no_audio` (its decoder makes no sound), `400 bad_params` (`listen` not true or false). An optional `"client": "<id>"` beside `listen` names who listens (Radio: listening ends when the last of them goes, "Client presence" below). Stopping the session ends it; it is never saved, so after a restart the radio is heard. Since 28/10/2026 (DMR). |

A DAB session's sound replaces the demodulator's (below) by itself; any
other session that makes sound (DMR's voice, below) does when listened to
(`listen`). Each session in a list says `listening`, and `api/status`
`decoders` names the session listened to as `listening` (null: the radio).

An entry (the catalogue):

```json
{"id": "rtty", "family": "amateur", "inputs": ["iq"], "rateHz": 12000.0, "bandwidthHz": 3000.0,
 "outputs": ["text"], "panel": "text", "params": [{"key": "baud", "type": "choice", "choices": [45.45, 50.0, 75.0], "default": 45.45}, ...],
 "needs": [], "engine": "shack_sdr", "available": true, "why": null, "whyText": "", "version": "0.1.0", "fixed": true,
 "partial": false, "missing": [], "missingText": ""}
```

`partial` says part of what it decodes needs a codec that is `missing`
(`missingText` the sentence): DAB without faad2 is `available` and
`partial` with `missing: ["faad2"]`, because old DAB plays and DAB+ does
not. It is never refused `409 decoder_unavailable` for that.

`panel` says how a client shows the results (`text`, `slots`, `frames`,
`image`, `meta`), so a new decoder needs no client release. `engine` is
the library that decodes (`shack_sdr`, `shack_cw`, `ohsdigi`); `fixed`
whether it can run on a frequency of its own (CW through shack_cw can;
FT8, FT4, Q65 and JS8 run only as the mode).

A session:

```json
{"id": "ds_3f2a", "decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45, "shift": 170},
 "state": "synced", "why": null, "whyText": "", "since": "2026-10-22T10:00:00Z", "rev": 812,
 "stats": {"snrDb": 14.2, "offsetHz": -12.5, "cpu": 0.004, "fed": 1440000, "dropped": 0}, "panel": "text"}
```

`state` is one of `starting`, `running`, `nosignal`, `synced`, `outside`
(its frequency left the receiver's span: fed nothing, and back by itself
when the span covers it; QO-100 NB only, since Radio pins its span for
its sessions, below), `budget` (paused at `decodeCpuMax`), `error` or
`stopped`. `why` is a code and `whyText` the server's sentence for it;
prefer your own translation of the code (CONTROLLER-CONTRACT §9).

`stats.fed` and `stats.dropped` count the samples given to the session
and thrown away unread (its decoder fell more than two seconds behind).
A session fed for three seconds with nearly all of it dropped says why
(23/10/2026; before then it stayed `starting` and said nothing):
`decoder_stuck`, with `state` `error`, when its decoder has taken none of
it - the decoder is caught inside a block and will not come back (shack_sdr
0.2.0's DAB search can do this on a real receiver); stop the session and
start it again, and restart the app if that does not help -
and `decoder_behind` (the state unchanged) when it takes some but cannot
keep up. Each clears by itself when less than half is dropped. The server
logs each once, and a stuck one is also a `toast`.

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

A session whose decoder sends `meta` (wide FM, PSK, SSTV; DAB below)
carries the latest as `meta` in the session, and each new one comes as a
`meta` result.

### PSK

`psk` decodes PSK31, PSK63 and PSK125 (BPSK, Varicode; no QPSK), several
stations in one session. Its frequency is a centre; `params.channels`
lists the stations as offsets in Hz from it, comma-separated, up to 16
(`"-400,0,350"`; default `"0"`, the one on its frequency). Other params:
`baud` 31.25, 62.5 or 125 (31.25), `afc` (true) and `afcRangeHz` 0-100
(15, each side of each channel), `squelch` 0-20 dB (3; 0 is off). All
change live through `POST api/decoders/sessions/{id}` - a waterfall tap
sends the list with one more offset - and a channel kept in the new list
keeps its lock; a list of more than 16 is `400 bad_params`. A channel the
session's band cannot hold makes the session `error` with why
`channel_outside`.

```json
{"kind": "decoder", "session": "ds_7c10", "rev": 41, "t": 1792663200.25, "type": "text", "text": "C", "offsetHz": -399.2, "snrDb": -9.8}
{"kind": "decoder", "session": "ds_7c10", "rev": 42, "t": 1792663201.0, "type": "meta",
 "fields": {"channels": [{"offsetHz": -400.0, "freqHz": -399.2, "sync": true, "snrDb": -9.6, "imdDb": -28.4},
                         {"offsetHz": 350.0, "freqHz": 350.0, "sync": false, "snrDb": null, "imdDb": null}], "whyText": ""}}
```

One `text` result per character, `t` its first symbol's time. Its
`offsetHz` is the frequency it was heard on, from the session's centre:
route it to the nearest of the session's channels, one line per channel.
`snrDb` is in 2.5 kHz (add 19 dB at 31.25 Bd for the symbol's own
bandwidth). Characters come about a second after they were sent at
PSK31. `meta` comes once a second while a channel hears a signal: per
channel its `offsetHz` (as given), `freqHz` (where it is tracking, same
reference), `sync`, `snrDb` and `imdDb` (null until the tones stand 20 dB
over the noise). `stats` adds `chars` and `channels`.

**The PSK modes** (`psk31`, `psk63`, `psk125` in `api/set mode`) are the
same decoder as the session `vfo`. Their `events` keep their shape -
`{"mode": "psk31", "text", "center", "df", "snr"}`, `center` and `df` the
audio frequency (Hz above the dial) the station is on, `snr` in the
symbol's bandwidth as before - and add `channel`, the audio frequency of
the channel it belongs to. The mode's own channel is at 1000 Hz;
**`pskChannels`** (control, `POST api/set`, not kept over a restart) adds
up to 15 more, audio frequencies 200-2900 Hz above the dial
(`{"pskChannels": [1450, 1720]}`; `[]` for none). Show a character whose
`channel` is not 1000 on that station's own line. The `vfo` session's
`params.channels` are offsets from its `audioCentreHz` (1500), not from
the dial. PSK125 transmits as PSK31 and PSK63 do.

### SSTV

`sstv` receives pictures in fourteen modes - `martin1`, `martin2`,
`scottie1`, `scottie2`, `scottiedx`, `robot36`, `robot72`, `pd50`, `pd90`,
`pd120`, `pd160`, `pd180`, `pd240`, `pd290` - from a VIS header, or from a
run of line syncs when the header was missed (joined part way). Its
frequency is the picture's **1900 Hz leader**: an SSB dial plus 1900.
Params: `mode` ("" for any, the default, or one of the ids), `syncStart`
(true: start from line syncs), `afcRangeHz` 0-150 (150). `panel` is
`image`.

```json
{"kind": "decoder", "session": "ds_51e0", "rev": 1, "t": 1792663200.5, "type": "image", "event": "start", "width": 320, "height": 240, "format": "rgb"}
{"kind": "decoder", "session": "ds_51e0", "rev": 3, "t": 1792663200.5, "type": "image", "event": "lines", "from": 0, "rgb": "<base64>"}
{"kind": "decoder", "session": "ds_51e0", "rev": 168, "t": 1792663236.9, "type": "image", "event": "done", "file": "ds_51e0_sstv_20261023-101500Z_robot36.png"}
{"kind": "decoder", "session": "ds_51e0", "rev": 167, "t": 1792663236.9, "type": "meta",
 "fields": {"state": "done", "mode": "robot36", "vis": 8, "partial": false, "width": 320, "height": 240, "rows": 240,
            "started": 1792663200.5, "slantPpm": 1.8, "snrDb": 32.9, "offsetHz": -0.1, "syncs": 239, "missed": 0,
            "corrected": true, "file": "ds_51e0_sstv_20261023-101500Z_robot36.png", "whyText": ""}}
```

The picture is progressive: `lines` carries rows from row `from` (0 at
the top), `rgb` base64 of `width` x 3 bytes a row, several rows a result,
as they are read. A row may come again - when the picture ends the
decoder straightens it and resends the rows that moved - and is simply
painted again. `done` names the PNG in `api/decoders/files`
(`file`; never a path), which is the finished picture to show and keep.
`meta`, every sixteen rows and at the end, says `state` (`receiving`,
`done`, or `lost` for a picture that stopped before its end), the `mode`,
`partial` (joined part way: it starts wherever it was joined), the
sender's sound card (`slantPpm`), `snrDb` in 2.5 kHz and `offsetHz`. A
header for a mode not decoded is `{"state": "unsupported", "mode", "vis"}`
and one too weak to read `{"state": "bad_vis"}`; no picture follows
either. `stats` adds `images`, `partials`, `lines`, `visHeard`, `visBad`.

**The SSTV mode** is the same decoder as the session `vfo`, fed the
dial's audio; its `events` keep their shape -
`{"mode": "sstv", "state": "start", "name", "fmt", "width", "height"}`
(`partial: true` when joined part way), `{"state": "line", "name",
"line", "of", "row"}` (`line` from 1, `row` base64 RGB) and `{"state":
"done", "name", "path"}` - with two changes: `fmt` is the id above
(`martin1`, where it was `martinm1`), and `done` adds **`file`**, the
name to fetch from `api/decoders/files/{file}`, which is what a client
should keep rather than only what it painted. A header the decoder
cannot read is `{"mode": "sstv", "state": "unsupported" | "bad_vis",
"fmt"}`. Sending SSTV is unchanged: Robot 36, Martin M1, Scottie S1 and
PD120 (`sstvMode` `robot36`, `martinm1`, `scottie_s1`, `pd120`).

Pictures are kept in the app's data folder (`sstv/`); past
`decoderFilesKeep` (a setting, default 100) the oldest the decoders saved
are deleted after each new one.

## The pinned span (Radio)

Radio's receiver covers a span around its centre - the wide scope's,
`USABLE` (0.46) of half the sample rate either side: 1104 kHz at the
RSPdx's 2.4 MS/s, 552 kHz at 1.2 MS/s - and the centre follows the dial.
A decoder session on a frequency of its own (a *background* session: not
the mode's `vfo`, not DAB) would leave the span the moment the operator
tuned away, so while one runs the centre is **pinned** (Brian,
23/10/2026; openhamshack RADIO-SDR-PLAN §8.5). Code `ohsradio/radio.py`
"the pinned span" and `ohscore/span.py`; tests `tests/test_ham_span_pin.py`.

- **`span`** in `api/status`, `api/state` and its `state` diffs:
  `{"centreHz", "loHz", "hiHz", "pinned", "by", "sessions"}`. `pinned` is
  true while background sessions hold it; `by` their ids; `sessions`
  `[{"id", "decoder", "freqHz", "label"}]` (`label` "RTTY on 14.0933 MHz").
  `{}` while the radio is stopped, and always in QO-100 NB, which never
  pins (its receiver stays on the transponder; its sessions go `outside`).
  A client draws the span on its spectrum and greys out tuning outside it
  while `pinned`.

  ```json
  {"centreHz": 145148000.0, "loHz": 144596000.0, "hiHz": 145700000.0, "pinned": true,
   "by": ["ds_3f2a"], "sessions": [{"id": "ds_3f2a", "decoder": "aprs", "freqHz": 144800000.0,
                                     "label": "APRS on 144.8000 MHz"}]}
  ```
- **Where it is pinned**, when a session starts: the centre it has now, if
  every session (each its channel's width) and the dial (its passband by
  mode, as "The DC spike" below says) fit inside the span and none of
  them is within 5 kHz of the centre itself (DC, where the receiver's own
  spike is); otherwise
  the middle of the sessions and the dial, moved the least that keeps them
  all off DC, on a whole kHz where it can; otherwise the session is
  refused `409 outside_span` with the sentence ("7.0500 MHz is too far
  from the dial (14.0700 MHz): the receiver covers 552 kHz at once, so
  tune nearer to it first").
- **Tuning inside it** moves the dial, never the centre: the sessions are
  not retuned or reset and their results carry on. A dial put on the
  centre (DC) moves the pin the least that clears it, the sessions still
  inside; `span` says where.
- **Tuning outside it** (a `vfo`, `mode`, `rit`, `ritOn`, `rptReverse`,
  `rptShift` or `rptOffsetHz` that would take the receive dial or its
  passband out of the span) is refused on every route that tunes -
  `api/set`, `api/recall` and any other route that tunes - with `409 span_pinned`:
  `{"error": "Tuning to 7.0500 MHz stops RTTY on 14.0933 MHz: the receiver
  stays on 13.8990 MHz to 14.4510 MHz while they run", "code":
  "span_pinned", "sessions": [...], "span": {...}}`. Nothing changes. Ask
  the operator ("Tuning to 7.0500 MHz stops: RTTY on 14.0933 MHz.
  Continue?") and send the same `api/set` again with `"dropSessions":
  true` (beside `changes`, or among the keys of the flat form): the
  change is validated first, then those sessions stop (and leave
  `decoderSessions`), and the capture follows the dial again. Other routes
  take no flag: stop the sessions (`DELETE api/decoders/sessions/{id}`)
  and try again.
- **Unpinned** when the last background session stops: the centre follows
  the dial again from where it is.
- **Saved sessions** start again with the radio and pin it again; one that
  no longer fits with the dial is not started (the log says why).
- **Precedence** with what holds the whole receiver itself (`rxOwner`):
  - *DAB*: background sessions were there first. `POST
    api/decoders/sessions` for `dab` is `409 span_pinned` ("Playing DAB
    takes the receiver to Band III and stops RTTY on 145.6000 MHz", with
    `sessions`) unless it carries `"dropSessions": true`. While DAB plays,
    a background session is `409 receiver_busy` ("The receiver is playing
    DAB from block 11D: stop the DAB station to add a decoder").
  - *The band scan*: never while a decoder session runs (`POST api/scan`
    `409 receiver_busy` "Not scanning now: A decoder is running", and the
    nightly scan skips); a session starting during a scan ends the scan
    first, which puts the operator's centre back, and is pinned there.
- **Transmit is not affected.** It goes out on `txDial` through its own
  local oscillator, never the capture: a repeater's input 600 kHz below a
  pinned span keys and transmits as ever, and `txBlocked` judges the
  transmit dial as before.

## The DC spike (Radio)

A receiver that mixes straight to zero IF - the Pluto family, the RTL-SDR,
an SDRplay RSP, a SoapySDR receiver - puts its own DC offset and LO
leakage at the exact centre of its span: a carrier that is not on the air,
on the trace and down the waterfall (Brian, 23/10/2026: the RSPdx with
SDRplay's own correction at dcCal 4, trackTime 63 still showed it). Three
things deal with it; code `ohscore/dsp/dcblock.py`, `Engine._dc_mask`,
`Radio._dial_edge`; tests `tests/test_dc_spike.py`.

- **A DC blocker** on the receive IQ before anything looks at it (scopes,
  demodulator, decoders): first order, its corner 5 Hz. It follows a
  residue that wanders within a tenth of a second and leaves a signal
  1 kHz from the centre as it was (0.0001 dB, 0.3°). Recordings keep what
  the radio sent. The setting `dcBlock` (Settings › Radio, `api/spec`):
  `auto` (the default: on for those receivers, off for the Hermes-Lite 2,
  which mixes digitally, the simulator and a recording played back), `on`
  or `off`.
- **The wide scope fills in its bins over DC** while the blocker runs:
  the two either side of the centre bin and itself, a straight line
  between their neighbours, so the residue and the LO's phase noise round
  it (a bin or two at 586 Hz a bin) never stand as a line. Display only.
  The `wide` item says which: `"dcBins": [lo, hi]`, indices into its
  bins, inclusive; absent when nothing was filled in (blocker off, or DC
  outside the item). A client may mask them its own way.
- **The DC keep-out** (offset tuning), one rule whether the centre
  follows the dial or background decoders pin it ("The pinned span"
  above): the centre never comes within the dial's passband plus 5 kHz of
  the receive dial. The passband by mode: SSB and the digital modes their
  filter (3 kHz at least), CW its filter at the pitch, AM `amWidth`, FM its
  channel (`fmDeviation` + 5 kHz), wide FM its 90 kHz channel plus 10 kHz
  (105 kHz clear of DC in all). A tune that would land the dial there
  moves the centre instead, the least that clears it; pinned, the pin
  moves likewise while every session still fits. `span` says where the
  centre is.

## spectrum/1 and overlay/1

The waterfall feed every OpenHamShack app is to serve in one shape, and
what is drawn on it (openhamshack CLIENT-UI-PLAN.md §2 and §3; the JSON
is ohs-libs `spec/schemas/spectrum.schema.json` and `overlay.schema.json`,
the binary row the vectors in `spec/vectors/spectrum/`). Code
`ohscore/server/spectrum.py` and `overlay.py`, the encoding ohs-libs'
`shack_spectrum` (vendored, the store images only); tests
`tests/test_server_spectrum.py`. Both apps serve it. Receive only:
nothing here keys, and no action on an item transmits.

**The old feeds stay.** `wide` and `zoom` on `api/events` are unchanged,
byte for byte: installed Remotes and the desktop apps read them, and each
goes one Remote release after the last client reading it has moved
(§2.5). A client finds spectrum/1 from the app's UI descriptor, never by
probing.

**`GET api/spectrum/v1`** upgrades to a WebSocket. Text frames are JSON,
binary frames are rows. Nothing in it is a URL, so `X-Forwarded-Prefix`
does not enter into it; it works the same over HTTP and HTTPS. Ping every
30 s (the socket answers pings). A desktop build run with `--server` has
no `shack_spectrum` and answers `503 spectrum_unavailable` instead.

| Stream | From | |
|---|---|---|
| `main` | the engine's `wide` feed | the wide scope, cropped to the app's span |
| `zoom` | the engine's `zoom` feed | around the dial (`zoomSpanHz`, `zoomPan`) |

The client subscribes, any time and as often as it likes; a new
subscribe for a stream replaces the old one at once:

```json
{"type": "subscribe", "stream": "main", "cols": 1280, "fps": 15,
 "loHz": 144100000, "hiHz": 144500000, "reduce": "peak", "depth": 8}
```

| Field | Rule |
|---|---|
| `stream`, `cols` | required. `cols` over 2048 is 2048 |
| `fps` | a ceiling, by capture time; default and most 25 |
| `loHz`, `hiHz` | a crop inside the stream's span, default the whole span; outside it is clipped to it (going beyond is a tune: `api/set`) |
| `reduce` | `peak` (default: a column takes its highest bin) or `mean` (the power average of its bins) |
| `depth` | 8 (default) or 16 bits a column |

A subscribe the server cannot use is answered `{"type": "error", "code":
"unknown_stream" | "bad_subscribe" | "bad_message", "stream"?, "message"}`
and changes nothing; the socket stays open. A socket that has subscribed
to nothing is sent descriptions but no rows (the box sends nothing for a
stream nobody watches).

The server sends:

- **`{"type": "stream", …}`** for each stream when the socket opens (once
  a row of it has been seen) and whenever it changes: `rev`
  (counted per app, shared by every socket), `centreHz`, `spanHz`,
  `loHz`, `hiHz`, `binHz`, `rbwHz` (1.5 bins: the Hann window's),
  `srcBins`, `rate` (`scopeFps`), `units` `dB`, `calibrated` false,
  `dcBins` as on `wide` ("The DC spike" above), `pinned` `{"by": [ids]}`
  on `main` while decoder sessions pin the span ("The pinned span"),
  `label` (Wide, Zoom). `rev` moves when the bins change or the span moves
  by a whole bin or more; each row carries its own `loHz`, so the
  tracking's sub-bin corrections in QO-100 NB do not churn it. The order
  of these messages on a socket numbers the streams: a row's stream index.
- **`{"type": "levels", "stream", "dbFloor", "dbStep", "noiseDb",
  "peakDb"}`**: the quantisation window, one per stream for every client
  (shack_spectrum's `LevelsWindow`: floor the 20th percentile less 10 dB,
  top at least 60 dB above, moved only after 2 s more than 3 dB out).
  Sent before the first row of a new subscription and whenever the window
  moves, with `levelsChanged` on the next row; and again about once a
  second, while the socket is idle, for `noiseDb`/`peakDb`. `dbStep` is
  for the subscription's own depth.
- **Rows**, binary, CLIENT-UI-PLAN §2.3: 32 bytes of header (magic `OS`,
  version 1, flags `depth16`, `levelsChanged`, `streamChanged`, `gap`;
  stream index, column count, sequence, capture time in ms, `loHz`,
  `colHz`), then the columns. Value `v` is `dbFloor + v x dbStep`.

**Latest wins.** Each socket has a writer of its own and at most one row
waiting per stream. A row made while the client has not taken the last
replaces the waiting one; the next row written carries `gap`, and the
sequence (stamped when a row is made) jumps. A slow client sees the
present with holes, never the past.

**Caps** the client cannot raise: 25 rows a second and 2048 columns a
stream (asking for more is clamped, not refused), and **8 sockets** an
app: the ninth is sent `{"type": "error", "code": "busy", "message"}`
and closed (1013). **Not applied:** the plan's 15 fps for a TV and 4 fps
and 512 columns for a tunnel (internet) client. The identity headers say
who and at what level, not what device or path, so this server cannot
tell either apart and does not guess; every client gets the default caps.

**overlay/1** comes on the same socket, for the range the socket has
subscribed to see (the union of its streams' crops, a whole span where it
gave none) **plus half that range's width either side** (§3.1 says "half
a span" without saying which; the view's own, so a small pan needs
nothing new):

```json
{"type": "overlay", "rev": 41, "op": "snapshot" | "upsert" | "remove", "items": [...]}
```

A `snapshot` on every subscribe; then, four times a second, `upsert` for
items new or changed and `remove` (`[{"id"}]`) for items gone (the dial
and sessions are looked at each time; the band plan, local frequencies
and station lists every 10 s). `rev`
counts per socket; after a gap, subscribe again for a snapshot.
**`GET api/overlay/v1?loHz=&hiHz=`** (view) answers the snapshot for
that range and margin, `rev` 0; without both it uses the wide scope's
span, and `400 bad_range` when there is none (the radio has not run) or
the range is not two frequencies, low then high.

An item (§3.2): `id`, `kind`, `layer`, `loHz`, `hiHz`, `centreHz`,
`label`, `short`, `detail`, `prio`, `readAtHzPerPx`, `role`, `active`,
`expires` (null), `source`, and `actions` where there is something to do:

| Layer | Kind | From | `role` | First action |
|---|---|---|---|---|
| `band` | `segment` | the band plan in force for the station profile, as the transmit guard reads it (shack_bandplan) | `segment.<kind>` for beacon or satellite segments, else by modes: `segment.cw`, `segment.cw-digi`, `segment.all` (four modes or more) | none |
| `dial` | `dial`, `passband`, `tx` | `api/state`: the dial, the passband the scopes draw, the transmit dial while keyed | `dial`, `passband`, `tx` | none |
| `channels` | `channel` | Radio's local frequencies, every category but `beacon` | `channel.<category>` (`channel.<userCategory>` for my frequencies: `channel.repeater`) | tune: `POST api/set {"changes": {"vfo", "mode"}}` |
| `beacons` | `beacon` | the NCDXF/IARU entries of the same list | `beacon.ncdxf` | tune |
| `stations` | `station` | the band scan's FM list (by `best.hz`, labelled by PS) and DAB ensembles | `station.fm`, `station.dab` | FM tune in `wfm`; DAB one action per service, playing it (`POST api/decoders/sessions`) |
| `sessions` | `session` | decoder sessions, but the mode's own (`vfo`) | `session.<decoder>`; `active` while `running` or `synced` | none |

Every action is at Control level. QO-100 NB has the band and dial
layers and its sessions; it has no local frequencies or station lists.
Spots, bookmarks, alerts and signals are not produced yet. Labels are in
the server's language, like every other sentence it sends (it does not
read `Accept-Language` yet); a segment's label is the dataset's own.
Action paths are relative to the app's base and carry no `url`.

The plan has each app convert its sources through a shared helper in
ohs-libs (`shack_spectrum.overlay`). That helper does not exist yet
(`shack_spectrum` 0.2.0 has the row, decimation, levels and sender only),
so this app's conversion is its own, in `ohscore/server/overlay.py`, to
move there when it does.

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
  current mode is making stereo now (wide FM with its pilot), or a DAB
  station playing in stereo.

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

A later `rxGain` change is corrected in the sense the device reports in
`deviceStatus` (since 23/10/2026): `gainIsReduction` (raising `rxGain`
lowers the signal) and `gainModel` - `"db"`, a plain gain; `"sdrplay"`,
`device` sdrplay's reduction of 79 - `rxGain` held to 20-59 dB, so a
change past either end moves nothing; `"soapysdrplay3"`, an RSP under
SoapySDRPlay3's sense (`device` soapy, `driver=sdrplay`, either path),
where the first 39 dB of `rxGain` are IF gain reduction and every dB
above is an LNA state (up to `rfgrRange`'s top): there a change inside
the first 39 dB is corrected the right way round, and one that moves the
LNA state makes the calibration not hold (`extra_changed`). A device that
reports nothing is `"db"`.

Under `"soapysdrplay3"` the LNA state is derived from `rxGain` itself
(SoapySDRPlay3's own split, above), not read from a setting of its own the
way `sdrplayLna` is for plain `"sdrplay"` - so a calibration stored on
this path has no `extraName`/`extraValue` (the table entry below shows
only `offset`, `gain` and `when`), and the check that the LNA state has
not moved is made from the stored `gain` at calibration time against the
dial's current `rxGain`, not from a stored extra field. A `rxGain` change
that crosses the 39 dB split still reports `extra_changed` - it is just
not recorded as a separate stage.

The `meter` feed item (ENGINE-API.md) gains four fields on Radio,
alongside its unchanged raw `rx` (dBFS): `dbm` and `s` (e.g. `"S9+12"`,
IARU Region 1: S9 is -73 dBm below 30 MHz, -93 dBm at and above, 6 dB per
S-unit) while a calibration holds for the dial's current radio, band and
antenna; otherwise both are `null` and `why`/`whyText` say why not
(`between_bands`, `no_calibration`, `agc`, `extra_changed` - an RSP's LNA
state moved - `broadcast_gain` - a broadcast station's gain moved it: "Broadcast
gain" below - with `why` `null` and `whyText` `""` while calibrated).

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
  times that. `channels` is 2 for a broadcast station (below) or when
  the mode was making stereo as the recording started, else 1, and
  holds for the whole file: a later mode change is converted to it (mono
  on both sides, or stereo averaged). The sidecar `<id>.json`
  has `station` (the callsign), `freqHz` (the receive dial), `mode`,
  `radio` (the device), `processing` (`nr`, `nb`, `agc`), and `changes`
  (frequency and mode as they changed, seconds in). The radio stopping
  ends it (`stopped`: "the radio stopped").
- **A broadcast station** (Radio, from 24/10/2026): while a DAB session
  holds the receiver (`rxOwner`), or the mode is `wfm`, a recording is
  the station's:
  - **Audio** is always **stereo**, 48 kHz FLAC, whatever the station's
    stereo flag says as it starts (a station's stereo is known only once
    its pilot or first audio frame is heard, and the count is fixed for
    the file; a mono station costs almost nothing more in FLAC). `mode`
    is `"DAB"`, `"DAB+"` or `"WFM"`; `freqHz` the block's centre (DAB)
    or the dial (wide FM). The sidecar adds `broadcast`, the station as
    the recording started:

    ```json
    {"kind": "dab", "mode": "DAB", "label": "Shack MP2 Tone", "shortLabel": "ShackMP2",
     "sid": "C221", "block": "11D", "freqHz": 222064000.0,
     "ensemble": "Shack Test Mux", "eid": "C1CE", "ptyName": "Pop music",
     "dls": "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right",
     "title": "1 kHz left", "artist": "Shack MP2 Tone", "itemRunning": true, "itemToggle": true}
    ```

    (`title`/`artist` are DL Plus's item title and artist, `itemRunning`
    and `itemToggle` its item bits, TS 102 980), or for wide
    FM `{"kind": "wfm", "mode": "WFM", "label", "ps", "pi", "rt",
    "ptyName", "freqHz"}` (`label` is the PS name). A field the station
    has not sent yet is null. `changes` also carries `label`, `sid`/`pi`,
    `ensemble`, `dls`/`rt`, `title` and `artist` as each changed, seconds
    in: what was playing when, a small "now playing" history.
  - **IQ** is the whole block (every station on it), so its
    `.sigmf-meta` says `openhamshack:receive.mode` `"dab"` (or `"dab+"`,
    `"wfm"`) instead of the operator's mode from before DAB took the
    receiver, and carries the same object as `openhamshack:broadcast`.
    Played back, it tunes to the block and leaves the operator's mode.
- **In the list:** each entry of `api/recordings` carries `broadcast`,
  the same start-of-recording object (null for a recording of anything
  else), so a client shows the station, mode, title and artist without
  fetching each sidecar; never `changes`, which stays in the sidecar.
  `station` in an entry is, as it always was, the operator's callsign
  (shack_rec's field), not the broadcast station.
- **Names** (the id, and the files' base name) are the app's own name,
  the UTC start, then what it is (host.recording_name):

  | Recording | Id |
  |---|---|
  | DAB audio | `openhamshack-radio-20261024-041948Z-BBC-Radio-4-DAB` (`-DABplus` for DAB+; `-11B-DAB` when no station plays) |
  | DAB IQ | `openhamshack-radio-20261024-041948Z-11B-218.640MHz-DAB` |
  | wide FM audio | `openhamshack-radio-20261024-041948Z-SIM-ONE-WFM` (`-88.600000MHz-WFM` before RDS is heard) |
  | wide FM IQ | `openhamshack-radio-20261024-041948Z-88.600MHz-SIM-ONE-WFM` |
  | anything else | `openhamshack-radio-20261024-041948Z-14.074000MHz-USB` (audio), `...-14.074MHz-USB` (IQ) |

  The station's name is folded to ASCII, `&` is "and", any other run of
  characters that are not letters or digits one `-`, cut to 40. DAB+ is
  `DABplus` because a `+` in a query is a space. Clients must still
  URL-encode an id. Before 24/10/2026 audio ids began with the module's
  id squeezed (`shackradio-`, `shackqo100nb-`) and IQ ones with the app's
  name; both kinds now begin `openhamshack-radio-` (`openhamshack-nb-`).
- **Playing one in a client:** `GET api/recordings/file?id=<id>&part=data`
  is the FLAC file itself (`Content-Type: audio/flac`, `Content-Disposition:
  inline`, `Accept-Ranges: bytes`): `Range: bytes=a-b` answers `206` with
  `Content-Range`, a range past the end `416`, so ExoPlayer, AVPlayer and
  an `<audio>` element seek in it. It is not WAV: FLAC, 16-bit, at the
  rate and channels in the listing (`sampleRate`, `channels`): Radio's
  48000 and, for a broadcast station, 2.
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
 "active": [{"id": "openhamshack-nb-20261012-100000Z-10489.750000MHz-USB", "kind": "audio",
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
{"id": "openhamshack-nb-20261012-100000Z-10489.750000MHz-USB", "kind": "audio", "format": "flac",
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

## Timeshift (Radio)

While a broadcast station plays - a DAB station holding the receiver, or
wide FM - the controller keeps its last `timeshiftMinutes` (a setting, 60
by default, 0 for off, at most 240) of receive audio on disk, so a client
can listen from behind live and a recording can start in the past (Brian,
24/10/2026, for the TV's DAB Radio). ohscore/server/timeshift.py has the
decisions.

- **What is kept** is what `api/audio/rx` sends, as two channels at 48
  kHz, lossless, compressed in the app's own format (about 40 % of raw
  PCM on band-limited noise, 20 % for a mono station, in measurements on
  synthetic audio). The folder
  (`timeshift` in the data folder) never holds more than the same audio
  as raw PCM would take (11.5 MB a minute) and keeps the recordings'
  free-space floor (`RECORDINGS_MIN_FREE_GB`): below it the timeshift
  stops and `timeshift.why` says so.
- **One station's, and nothing survives a restart.** It is cleared and
  starts again when the station changes (another DAB service or block,
  another wide FM frequency), when it stops or the radio does, when the
  setting changes to 0, and whenever the app starts. A stream behind live
  ends when it is cleared; the client goes back to live.

`api/status` `timeshift`:

```json
{"available": true, "startUtc": "2026-10-24T04:10:00Z", "lengthS": 1834.5, "capS": 3600,
 "station": {"kind": "dab", "mode": "DAB", "label": "Shack MP2 Tone", "sid": "C221", "block": "11D", "...": "..."},
 "itemStartUtc": "2026-10-24T04:38:12Z"}
```

`station` is the same object as a recording's `broadcast` (Recordings),
as it is now. `itemStartUtc` is where the current DL Plus item starts,
as far back as is kept, null when no item is on (or nothing is kept);
`itemStartInBuffer` is true when that is the item's real start, false
when the item began before the buffer and `itemStartUtc` is the buffer's
start ("from the start of this song, as far back as I have"). DL Plus
arrives a few seconds after the sound, so the first item heard after
tuning in is false. An item starts, and `itemStartInBuffer` is true,
when its title or artist changes, when DL Plus's item toggle flips, when
item running goes from false to true, or when an item appears after the
station has sent DLS alone for 10 s or more (between items, or a station
that sends DL Plus only for songs). `why` appears when it
stopped for a reason (low disk). `available` is false, `lengthS` 0, while
nothing is kept. The server keeps no per-client position: a client
tracks its own.

**Listening behind live: `GET api/audio/rx?behind=<seconds>[&channels=2]`.**
The same raw PCM stream as live, in the same format and headers, starting
that many seconds ago (clamped to what is kept) and carrying on in real
time from there. It is sent at the pace it plays, at most a second ahead,
so a player's buffer never fills with minutes of it. It adds a header:

    X-Timeshift: {"behindS": 30.0, "clamped": false, "startUtc": "2026-10-24T04:40:00Z"}

`behindS` is how far behind it actually starts. Further back than is kept
(`behind=99999`) is **clamped**, not refused: the stream starts at the
oldest audio kept, `behindS` says how far back that is, and `clamped` is
true. A client
does everything by opening a new stream:

- **pause:** stop reading and close; note the wall-clock time;
- **resume:** `behind=` the old offset plus the seconds paused;
- **back or forward 30 s:** `behind=` the offset plus or minus 30;
- **catch up to live:** no `behind` (or `behind=0`): the live stream.

`400 bad_behind` for a negative or unreadable value; `409 no_timeshift`
while nothing is kept.

**Recording from the past:** `POST api/recordings/start` with `"kind":
"audio"` and one of:

| Field | Starts at |
|---|---|
| `"fromSecondsAgo": 45` | that long ago, clamped to what is kept |
| `"fromItemStart": true` | `itemStartUtc`: the start of the current DL Plus item (DAB), or the buffer's start for an item on since before it, or now with no item; `why` says when it was not the item's real start |
| `"lastMinutes": 5` | that long ago, and **ends at now**: a finished recording of the last minutes, made at once (FLAC is written at 20-35 times real time on shack, so five minutes take 10-15 s; meanwhile it is the audio recording that is running) |
| none of them | `recordLeadSeconds` ago (a setting, 30 by default, 0-300), only while a broadcast station plays; otherwise now, as always |

The recording is then the ordinary one: the past, then on into live with
nothing lost or repeated at the join, stopped as usual (except
`lastMinutes`, which stops itself: `stopped` "the timeshift's minutes are
all in it"). Its `startUtc` and its name are when its first sample was
played; the sidecar adds `fromSecondsAgo`. The answer is the status, plus:

```json
"timeshift": {"fromSecondsAgo": 30.0, "startUtc": "2026-10-24T04:40:00Z", "untilNow": false, "why": ""}
```

`why` is "" when it started where asked, else the sentence saying where
it did. Refused: `400 bad_params` for more than one of the three, a
negative or unreadable number, or any of them with `"kind": "iq"` (IQ is
not kept); `409 no_timeshift` when one is asked for and nothing is kept.

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

## Client presence (Radio)

When a client goes, what it started for itself ends, and a radio nobody is
using goes back to the station (openhamshack `docs/CLIENT-UI-PLAN.md`
§7.2-7.4, as built on 28/10/2026; code `ohscore/server/presence.py` and
`Server.client_gone` in `ohscore/server/app.py`; tests
`tests/test_ham_presence.py`). Radio only: QO-100 NB keeps its feature
leases. Receive only: nothing here keys.

**The platform keeps presence, Radio follows it.** A client renews `POST
api/shack/v1/presence {"client", "app": "shack-radio", "screen", "holds"}`
on the controller every 10 s and says goodbye on the way out; 30 s without
a renewal is gone. Radio reads `api/shack/v1/presence/events` (`arrived`,
`moved`, `gone{why: goodbye|expired}`) under its app token, only when the
controller's services map lists `"presence": 1`. Without it - an older
controller, the desktop, a run with no token - nothing changes.

**Who holds what.** The `client` id is the client's one stable id: the
transmit lease's `remote`, AIS's `client`. A client with presence sends it
where it makes a hold:

| Hold (client-scoped) | Named by |
|---|---|
| a DAB station | `"client"` in `POST api/decoders/sessions` (a start, `replace` too) |
| listening to a session | `"client"` in `POST api/decoders/sessions/{id}/listen` |
| the ship and aircraft maps | `"client"` in `POST api/ais/session` / `api/adsb/session`, as before; `"ais"` / `"adsb"` in its presence holds renews them without renewing the session |
| the APRS station map | `"client"` in `POST api/aprs/session`; `"aprs"` in its presence holds renews it without renewing the session |
| receive audio, spectrum/1 and overlay/1, `api/events` | `?client=<id>` on `api/audio/rx`, `api/spectrum/v1`, `api/events` |

All optional and backward compatible: a hold made without an id, or by a
client the platform has never listed, is never ended by presence (an older
client keeps today's behaviour, CLIENT-UI-PLAN §12). Station-scoped work
is never ended by presence: background decoder sessions (they are saved),
the CW skimmer, recordings, the nightly band scan.

**When a client goes** (goodbye at once; otherwise its 30 s lease):

1. its audio, spectrum and `api/events` streams close;
2. a DAB station or listen it was the **last** client to ask for ends at
   once - no linger (Brian, 28/10/2026) - the receiver back on the dial,
   mode and repeater offset from before (`rxOwner` `{}`), as a stop does;
   it leaves the AIS/ADS-B/APRS session, which ends at once if it was the last;
3. if the radio is then held for nothing - no client's stream or socket,
   no held receiver, no decoder session, skimmer, recording or scan, not
   on the air, no transmit lease, Enable TX not armed - Radio **gives it
   back**: the engine stops and the broker's claim is released, as
   `api/stop` releases it, so the Hardware page shows it free and another
   app can claim it. `api/status` then has `running` false, `radioError`
   "" and `presence.released` true. The radio is still wanted: the next
   client to arrive in Radio, or any client's `POST`/`DELETE` (bar
   `api/stop`, `api/halt`) or stream opened (`api/audio/rx`,
   `api/spectrum/v1`, `api/events`), claims it again for receive, a
   second or two, before the request is answered; a nightly scan falling due does too, and gives it back
   after.

**Transmit is untouched** (§7.4): nothing here unkeys or disarms. While the
radio is on the air nothing is released; it is done once it is not. A
vanished client's transmit lease and Enable TX arm (5 s) have ended long
before its presence (30 s) does.

**A controller restart** forgets every client and sends no `gone`. Radio
lists `GET api/shack/v1/presence` each time its event stream (re)connects
and every minute; a client seen before and missing from the list has one
lease (30 s) to reappear - a client still there does, within one renewal -
and is gone, `expired`, if it does not.

## DAB (Radio)

DAB and DAB+ from one Band III block through shack_sdr's DAB decoder
(ohs-libs `rust/shack_sdr/README.md` "DAB"), as a decoder session that
takes the receiver while it plays. What openhamshack-remote
`docs/RADIO-LISTEN-CONTRACT.md` §3 asked for, as built on 23/10/2026
(code `ohscore/decoders.py` "Held sessions", `Engine.hold_receiver`; tests
`tests/test_ham_dab.py`). Receive only: nothing here keys.

**Start:** `POST api/decoders/sessions` at control level:

```json
{"decoder": "dab", "freqHz": 222064000, "params": {"block": "11D", "service": "C221"}}
```

- `freqHz` is the block's centre (the dial a client shows). `params.block`
  ("11D", any case) may be given instead of it, or as well, when the two
  must agree. Neither, a frequency that is not a block's centre (within
  8 kHz), or a block that does not exist is `400 bad_params` with the
  sentence.
- `params.service` is the station's service id in hex; `""` or none lists
  the ensemble without playing anything (a scan: stop when `meta.complete`,
  about 0.8 s after sync; allow 1.5 s for a block that holds an ensemble).
- `201` with the session (below). Refused, each with its sentence:
  `409 receiver_busy` (another DAB session holds the receiver, or an IQ
  recording is playing), `409 span_pinned` (background decoder sessions
  pin the span, `sessions` naming them: send `"dropSessions": true` to
  stop them and play; "The pinned span" above), `409 on_air` (transmitting, or automatic
  transmit armed), `409 rate_too_low` (the receiver runs below 2.048 MS/s:
  "DAB needs the receiver to run at 2.048 MS/s or more, and the pluto runs
  at 1.2 MS/s: choose 2.4 MS/s in Settings › Radio (the radio restarts)",
  or "... and the hl2 cannot (it runs at 0.192 MS/s)" for a radio with no
  such rate), `409 out_of_range` (outside what the radio receives), `503
  not_running`. The rate is never changed for the session: that reopens
  the radio, which on a controller gives the broker's claim back and takes
  it again, so it stays the operator's choice. The RSPdx (2.4 MS/s) needs
  nothing; a Pluto, LibreSDR, RTL-SDR or SoapySDR receiver at 1.2 MS/s is
  told to choose 2.4.

**The receiver is the session's while it runs,** and only one DAB session
runs at a time.

- The dial (`vfo`) goes to the block's centre and the receiver's centre
  with it (DC on the block's unused middle carrier). The mode is left as
  it was; nothing at the dial is demodulated.
- `rxOwner` in `api/state` and `api/status` says who holds it, `{}` while
  the operator has it (the band scan holds it too, `"by": "scan"`, but
  gives it back at once: "Station lists" below):
  `{"by": "dab", "session": "ds_3f2a", "block": "11D", "freqHz": 222064000,
  "prior": {"vfo": 145500000, "mode": "fm", "rptOffsetHz": 600000},
  "text": "<the tuning sentence below>"}`.
- Tuning is refused: `api/set` with `vfo`, `mode`, `rit`, `ritOn`,
  `rptReverse` or `rptShift` answers `409 receiver_busy`, with `error` "The
  receiver is playing DAB from block 11D: stop the DAB station to tune or
  change mode" and `rxOwner`. Anything else (volume, mute, settings) still
  changes.
- Transmitting is refused: `txBlocked` is "The receiver is playing DAB from
  block 11D: stop the DAB station to transmit", and `api/ptt` answers
  `onAir` false with it in `txError`.
- **Stopping** (`DELETE api/decoders/sessions/{id}`, `api/stop`, the
  radio stopping, or - on a controller with client presence - the last
  client that asked for the station going: "Client presence" below)
  puts back the dial, mode and repeater offset from
  before (`prior`), and the receiver follows the dial again. A DAB session
  is never saved in `decoderSessions` and never starts again with the
  radio: a start that retuned to Band III by itself would lose the dial.

**Choose the station live:** `POST api/decoders/sessions/{id}
{"params": {"service": "C3A7"}}`. Another `block` is `400 bad_params`:
stop the session and start one there.

**Without the session's id** (what a ui/1 screen sends, since its
actions are POSTs to fixed paths: "ui/1 screens" below), on the same
`POST api/decoders/sessions` at the same control level:

- `{"decoder": "dab", "stop": true}` stops whichever DAB station plays,
  as the DELETE above would: `200 {"stopped": true, "id"}`, or `404
  unknown_session` when none does.
- `"replace": true` beside an ordinary start lets the station playing
  give way: on the same block only the service changes, live (`200` with
  the same session); on another block it stops and the new session starts
  (`201`); with none playing it is an ordinary start. Without `replace` a
  second station is still `409 receiver_busy`.

**Its sound** is Radio's ordinary receive audio, in place of the
demodulator's: `api/audio/rx` at 48 kHz, the station's own two channels
with `?channels=2` and L+R averaged without; `audio.stereo` in status is
true while the station is stereo. An audio recording made meanwhile is
the station (Recordings, "A broadcast station"): 48 kHz stereo FLAC,
`mode` "DAB" or "DAB+", `freqHz` the block's centre, named after the
station. While the station makes no sound (no sync yet, a DAB+
station without faad2) the stream carries silence after half a second,
never a gap.

**The session** (`GET api/decoders/sessions/{id}`, and in the list) is the
usual one with `"panel": "meta"`, `"holdsReceiver": true`, `"block":
"11D"` and `meta`, the ensemble's feed:

```json
{"sync": true, "complete": true,
 "ensemble": {"id": "C1CE", "label": "Shack Test Mux", "shortLabel": "ShackTes"},
 "services": [{"sid": "C221", "label": "Shack MP2 Tone", "shortLabel": "ShackMP2", "bitrate": 128,
               "kind": "dab", "subchannel": 1, "protection": "3", "why": null, "whyText": "", "needs": []},
              {"sid": "C3A7", "label": "Shack DAB+ Data", "shortLabel": "ShackDAB", "bitrate": 64,
               "kind": "dab+", "subchannel": 2, "protection": "3-A", "why": "needs_codec:faad2",
               "whyText": "Needs faad2: install it to hear DAB+ stations. Radio never includes it: see Help › Codecs.",
               "needs": ["faad2"]}],
 "playing": "C221", "why": null, "whyText": "", "audio": {"codec": "mp2"}, "block": "11D",
 "dls": "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right",
 "tii": [{"main": 11, "sub": 1, "levelDb": -0.5, "confidence": 1.0},
         {"main": 1, "sub": 7, "levelDb": -8.5, "confidence": 1.0}],
 "transmitters": [{"main": 11, "sub": 1, "levelDb": -0.5, "confidence": 1.0, "site": "Crystal Palace",
                   "area": "London", "ensemble": "SDL National", "erpKw": 5.73, "lat": 51.42417, "lon": -0.07494,
                   "distanceKm": 3.8, "bearingDeg": 113, "match": "eid", "listedAs": null},
                  {"main": 1, "sub": 7, "levelDb": -8.5, "confidence": 1.0, "site": "Wrotham",
                   "area": "North West Kent", "ensemble": "SDL National", "erpKw": 25.0, "lat": 51.3207,
                   "lon": 0.2877, "distanceKm": 31.4, "bearingDeg": 114, "match": "eid",
                   "listedAs": null}]}
```

`ensemble` is null and `services` empty until heard. `dls` is the playing
station's programme text, null until one is complete and cleared when the
station changes (it needs no faad2). `audio.codec` is `mp2`, `he-aac`,
`he-aac-v2` or `aac-lc`. The same feed arrives as `decoder` items of
`type` `meta` (`fields` is the feed) on `api/events?kinds=…,decoder`
whenever it changes. `stats` adds DAB's counters (`frames`, `fibsOk`,
`fibsBad`, `audioFrames`, `audioErrors`, `superframes`, `aus`,
`auErrors`).

**Transmitters heard** (`transmitters`, with the decoder's own `tii`
beside it). Every DAB transmitter sends a code of its own (TII, EN 300 401
§14.8: a main identifier 0-69 and a sub identifier 0-23) in the gaps
between frames, so a receiver can tell the transmitters of a
single-frequency network apart. shack_sdr reads them (ohs-libs
`rust/shack_sdr/README.md` "DAB", `tii`); Radio names each from Ofcom's
list of UK DAB transmitters, bundled (`ohsradio/data/dabtx/`, Open
Government Licence v3.0) and refreshed with the local frequencies below.
Strongest first; empty until about 1.5 s after sync, then updated every
3 s at most, and only when something in it changes. Only what is worth
showing is in `transmitters` (`tii` keeps everything the decoder listed):
a code the list knows for this ensemble at `confidence` 0.5 or more, or
at any confidence within 150 km of the station (the decoder lists a weak
transmitter beside a loud one at 0.3, since it cannot tell it from the
loud one's intermodulation, and a near one is worth showing while a code
from the far end of the country is not); a code it does not know only at
0.8 or more. On nine real blocks recorded in Ayrshire this showed every
transmitter there and nothing else. Each entry:

| Field | Meaning |
|---|---|
| `main`, `sub` | The TII code as numbers (Ofcom's list writes them in hex: "0B"/"01" is 11/1). |
| `levelDb` | That transmitter's share of the signal received, dB, to 0.5: 0 for a lone one, about -3 each for two equal ones. |
| `confidence` | 0-1, to 0.1: how clearly its code stands above the noise (two transmitters with one sub identifier are a best fit, at most 0.7). |
| `site`, `area`, `ensemble` | The site's name, its area and the multiplex, from the list; all null for a code the list does not have (an Irish one, a new site). |
| `erpKw` | Its licensed effective radiated power, kW (null if the list has none). |
| `lat`, `lon` | The site, degrees. |
| `distanceKm`, `bearingDeg` | From the station's locator (great circle, to 0.1 km; bearing from true north, whole degrees); null without a locator or a site. |
| `match` | How it was found: `eid` (the ensemble's id and the code), `site` (the code is another ensemble's at a site that also carries this one: real sites often send one code on every multiplex they carry, as Darvel sends Central Scotland's 63/5 on Ayr's and Glasgow's multiplexes too), `sub` (this ensemble's only transmitter with that sub identifier, heard under another main one: West Kilbride, listed for Ayr as 64/7, sends 63/7), `block` (the ensemble is not in the list; the code on this block, nearest the station), or null (a code the list does not know). |
| `listedAs` | `{"main", "sub"}`: the code the list gives the site, when it was matched by `site` or `sub` and differs from what is heard; else null. A client may say "West Kilbride (sends 63/7)". |

A TV might show "Crystal Palace, 4 km ESE, 0 dB", a line each. Nothing about
it is needed to play a station. The simulator's ensemble on 11D is sent
by two transmitters, with the codes of Sound Digital's Crystal Palace
and, 8 dB down, Wrotham (its EId, C1CE, is Sound Digital's), as in the
example above, seen from IO91WK.

**The codes** (the feed's `why`, a service's, the session's), each with
its sentence in `whyText`; prefer your own translation of the code:

| Code | `whyText` |
|---|---|
| `no_signal` | No DAB signal on this block. |
| `no_sync` | A signal, but not DAB, or too weak to lock to. |
| `fic_errors` | DAB heard, but too weak to read the station list. |
| `service_not_found` | This station is not on this block. |
| `needs_codec:faad2` | desktop: "Needs faad2: install it to hear DAB+ stations. Radio never includes it: see Help › Codecs."; controller: "Needs faad2: ask your controller's administrator to install it (Controller › Optional libraries) to hear DAB+ stations."; a controller too old for host libraries: "Update the controller to use SDRplay radios and DAB+" |
| `codec_config`, `codec_open` | faad2 could not play this station's sound. |
| `unsupported_protection` | This station uses a coding Radio cannot read. |

Without faad2 the ensemble is still found and listed and old DAB plays; a
DAB+ station chosen says `needs_codec:faad2` and is silent. faad2
installed later is picked up after `POST api/decoders/codecs/rescan`.

**The simulator** carries one ensemble on 11D (222.064 MHz), shack_sdr's
DAB transmitter model's test ensemble, the one in the example above (old
DAB C221 with programme text, a 1 kHz tone left and 1.5 kHz right; DAB+
C3A7), heard when the simulator runs at 2.4 MS/s (`sampleRate`). Since
beta.7 it is the model's showcase: the same two services with a slide in
each one's X-PAD, a programme type (C221 Pop music, C3A7 Varied) and
language, DL Plus on C221 (title "1 kHz left", artist "Shack MP2 Tone"),
and an SPI data service whose logos (both variants of both services)
and four six-hour programmes of today (UTC) arrive a few seconds after
a service starts playing - everything the next section describes.

## DAB pictures and service information (Radio)

Everything here comes off air: SlideShow's pictures (ETSI TS 101 499,
in a service's PAD or a packet-mode component), station logos and the
programme guide from the ensemble's SPI service (TS 102 818, binary TS
102 371), and what the FIC says of each service (genre, language,
announcements, where else it is). **Nothing is ever fetched**: no
RadioDNS, no internet lookup; a URL a broadcaster sends
(`clickThroughUrl`) is passed on as text, never followed. Code
`ohscore/dabpics.py`, shack_sdr README "DAB"; tests
`tests/test_ham_dab_pictures.py`. A TV shows these; it never needs more
than view level.

**URLs.** Every `…Url` below is a path under the app's own base: the
request's `X-Forwarded-Prefix` and then the route
(`"/apps/radio/api/dab/logos/C221"`), never a host or scheme. Each sits
beside the `…Path` it was made from (`"api/dab/logos/C221"`, relative to
the app's base), which the feed and the session carry too: use whichever
suits the client's base URL handling. The same picture keeps its URL; a
new slide is told by `slide.rev`, so add `?rev=` to defeat a cache.

**The session's `meta`** (the DAB session above: `GET
api/decoders/sessions/{id}`, and its `meta` items on the `decoder` feed)
carries, beside what "DAB" lists:

```json
{"ensemble": {"id": "C1CE", "label": "Shack Test Mux", "shortLabel": "ShackTes",
              "ecc": "E1", "country": "GB", "ltoMinutes": 60, "utc": "2026-10-24T12:34:00Z"},
 "services": [{"sid": "C221", "label": "Shack MP2 Tone", "bitrate": 128, "kind": "dab", "...": "...",
               "pty": {"code": 10, "id": "pop_music", "dynamic": false}, "ptyName": "Pop music",
               "language": "en", "userApps": ["slideshow"], "hasSlideshow": true,
               "announcements": ["traffic", "news"], "clusters": [5],
               "components": [{"scids": 2, "label": "Shack Sport"}],
               "alsoOn": {"ensembles": [{"eid": "C182", "khz": [220352], "block": "11C"}],
                          "fm": [{"pi": "C201", "mhz": [97.6, 104.9]}],
                          "services": ["C222"], "hardLink": true},
               "now": {"name": "Shack MP2 Tone Afternoon", "start": "2026-10-24T12:00:00Z",
                       "durationS": 21600, "description": "Test tones from the Shack"},
               "next": {"name": "Shack MP2 Tone Evening", "start": "2026-10-24T18:00:00Z",
                        "durationS": 21600, "description": null},
               "logoPath": "api/dab/logos/C221", "logoUrl": "/apps/radio/api/dab/logos/C221",
               "logoSource": "broadcast",
               "logoWidePath": "api/dab/logos/C221?variant=wide",
               "logoWideUrl": "/apps/radio/api/dab/logos/C221?variant=wide", "logoWideSource": "radiodns"}],
 "dls": "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right",
 "dlPlus": {"itemTitle": "1 kHz left", "itemArtist": "Shack MP2 Tone", "itemAlbum": null,
            "programmeNow": null, "programmeHost": null, "stationNameLong": null,
            "itemRunning": true, "itemToggle": true,
            "tags": [{"type": "item_title", "text": "1 kHz left"}, {"type": "item_artist", "text": "Shack MP2 Tone"}]},
 "slide": {"sid": "C221", "contentType": "image/png", "name": "slide-c221.png", "categoryTitle": "Shack test card",
           "categoryId": null, "slideId": null, "clickThroughUrl": null, "width": 320, "height": 240, "size": 816,
           "rev": 7, "path": "api/dab/slides/C221", "url": "/apps/radio/api/dab/slides/C221"},
 "announcements": [{"cluster": 5, "types": ["traffic"], "subchannel": 4, "new": true, "services": ["C221"]}],
 "spi": {"sid": "E1C00001", "subchannel": 3, "state": "listening", "logos": 4, "schedules": 2}}
```

Per service (each field null, empty or false until the FIC has said):

- `pty`: the programme type (genre) as FIG 0/17 sends it: `code` 0-31,
  `id` the European RDS/DAB table's code (`pop_music`, `news`, `varied`,
  …; null under another table), `dynamic` (the type follows the items
  within the programme rather than the programme as a whole). `ptyName`
  is it worded, in Radio's language ("Pop music"): show it beside the bit
  rate. FM's `ptyName` is the same table.
- `language`: ISO 639 (`"en"`, `"gd"`), FIG 0/5.
- `userApps`: what the service carries besides sound (FIG 0/13):
  `slideshow`, `spi`, `journaline`, `tpeg`, …, or `ua_<hex>`.
  `hasSlideshow` says whether to keep room for a slide.
- `announcements`: the types of announcement that may interrupt it
  (FIG 0/18: `alarm`, `traffic`, `transport`, `warning`, `news`,
  `weather`, `event`, `special_event`, `programme_info`, `sport`,
  `finance`), and `clusters`. Listed only: Radio never switches to an
  announcement.
- `components`: the labels of its secondary components (FIG 1/4, 2/4).
- `alsoOn` (service following, listed only; nothing retunes): other
  ensembles carrying it (FIG 0/24) with their frequencies and Band III
  block (FIG 0/21), FM frequencies with the RDS PI it is linked to (FIG
  0/6, 0/21), linked DAB services, and whether any link is hard (the same
  programme rather than a related one). An `fm` entry with `mhz: []` is
  right: the ensemble names the RDS PI (in a linkage set) but sends no FM
  frequencies for it. BBC National on 12B does this for every service (its
  only FIG 0/21 entry is an AM one, which Radio does not list), so Radio 4
  is `{"pi": "C204", "mhz": []}`. To find the FM station, match the PI
  against the FM scan (`api/fm/stations`, each entry's `pi`).
- `now` and `next`: what is on and what comes next, from the SPI
  programme guide, times ISO UTC; null when no guide is held for the
  service. Radio works them out from every schedule it has stored (they
  survive restarts and other sessions) at the current UTC, so they are
  there from the first second of a session whenever a guide was heard
  before, and are current in every fetch of the session. When they change
  - a programme ends, or a guide arrives - the feed gets a fresh `meta`
  item marked `"refresh": true` (its `rev` is the session's current one:
  it is no new result of the decoder's).
- `logoUrl` (square, 128x128 preferred) and `logoWideUrl` (320x240
  preferred): present only once a logo has come, each with its source,
  `logoSource` and `logoWideSource`: `"broadcast"` (the ensemble's SPI)
  or `"radiodns"` (fetched, "Logos from RadioDNS" below). Labels are FIG
  2's (UTF-8) when the ensemble sends one.

Beside the services: `ensemble.ecc`, `country` (ISO 3166, from the ECC
and the ensemble id), `ltoMinutes` (local time offset) and `utc` (the
ensemble's clock, to the minute); `dlPlus`, the playing label's DL Plus
(ETSI TS 102 980), null when the station sends none - show `itemTitle`
by `itemArtist` when both are there, else `dls`; `slide`, the playing
service's latest slide, null until one; `announcements`, those on air
now; `spi`, the ensemble's SPI service (`state` `listening`, `resting`,
`idle` or `too_wide`), null when it has none.

**Pictures as files.**

- `GET api/dab/slides/{sid}`: the service's latest slide, the picture
  itself, `Content-Type` `image/jpeg` or `image/png` (at most 450 KB).
  `404 no_slide` before one; `400 bad_params` for an id that is not four
  or eight hex digits. Slides are kept in memory only (the latest per
  service, 32 services at most): a slide is what is on now, and a restart
  forgets them.
- `GET api/dab/slides`: `{"slides": [<the slide map above>…]}`, newest
  first.
- `GET api/dab/logos/{sid}[?variant=square|wide]`: the logo; the other
  variant when the one asked for never came; `404 no_logo`. Kept on the
  app's disk (its data folder's `dab` folder, at most 512 files and 24 MB,
  fetched ones going first, then the oldest) so lists show logos after a
  restart. SPI takes a few minutes of listening on a real ensemble to
  bring them; they come while a service of that ensemble plays, never
  during the band scan. Logos from RadioDNS (below) are served the same
  way, from the same store.
- `GET api/dab/schedule/{sid}[?date=YYYY-MM-DD]`: `{"sid", "date",
  "programmes": [{"name", "start", "durationS", "description"}…]}`, oldest
  first; with `date`, those starting on that UTC day. Kept on disk; a
  programme that ended more than a day ago is dropped. `404 no_schedule`.

**On the feed** (`api/events?kinds=…,decoder`), besides `meta` items, a
DAB session sends `frame` items as pictures and guides arrive, never
with their bytes:

```json
{"kind": "decoder", "session": "ds_3f2a", "rev": 88, "t": 1792843200.4, "type": "frame", "frame": "slide",
 "fields": {"sid": "C221", "contentType": "image/png", "name": "slide-c221.png", "...": "...",
            "path": "api/dab/slides/C221", "url": "/apps/radio/api/dab/slides/C221"}}
{"kind": "decoder", "...": "...", "frame": "logo",
 "fields": {"sid": "C221", "variant": "square", "contentType": "image/png", "width": 128, "height": 128,
            "path": "api/dab/logos/C221", "url": "/apps/radio/api/dab/logos/C221"}}
{"kind": "decoder", "...": "...", "frame": "schedule",
 "fields": {"sid": "C221", "programmes": 4, "path": "api/dab/schedule/C221", "url": "/apps/radio/api/dab/schedule/C221"}}
```

A slide item means: fetch the new picture now (or show the next one in
turn). A TV that only polls can watch `meta.slide.rev` instead.

**Logos from RadioDNS.** So a station list has logos before each
ensemble has been listened to, Radio also fetches them from the
broadcasters' own servers (ohsradio/radiodns.py; ETSI TS 103 270 and TS
102 818), in the background, at the lowest priority, never on a path a
scan, a session or playback waits for. For each stored service (16-bit
SId) it asks the system's resolvers for the CNAME of
`<scids>.<sid>.<eid>.<gcc>.dab.radiodns.org` (`0.c224.ce15.ce1.dab.radiodns.org`),
then the SRV `_radiospi._tcp.<target>` (else `_radioepg._tcp`), fetches
that server's `SI.xml` once for all its services, and takes the square
logo nearest 128x128 and the wide one nearest 320x240, as over the air.
Clients never touch the internet: the logos are served by
`api/dab/logos/{sid}` with `logoSource: "radiodns"`. Over the air wins
per variant: a variant the ensemble has sent is never fetched, and one it
sends later replaces the fetched one. It looks two minutes after start,
then whenever a DAB scan stores a list, and refreshes each service weekly
(a picture is refetched only when its URL changed). A failure (no route,
a timeout, a server error) backs off per host, ten minutes doubling to a
day, and is one log line; nothing is ever shown to a listener. Offline,
the API answers exactly as it did without the feature. What goes out:
those DNS queries, then GETs to the SPI servers and the logo URLs their
documents name, with `User-Agent: OpenHamShack-Radio/<version>`, no cookie
and nothing about the station. The `radioDnsLogos` setting (`api/set`,
control level; default true) turns it off: no query or request at all,
and the fetched logos are hidden (kept on disk, back when it is turned on
again). Programme information (PI.xml) is not fetched.

**What is not done:** a slide's TriggerTime (a slide is shown when it is
whole) and categories as a browsable set; SPI's genres, links and
"advanced" (compressed) files; Journaline and the other data
applications (listed in `userApps`, not decoded); announcement switching
and service following (listed only).

## Broadcast gain (Radio)

A broadcast station is the strongest thing on the antenna by tens of dB,
so it does not play at the operator's manual `rxGain`, which is set for
weak amateur signals (an RSPdx on a local DAB multiplex at rxGain 40
reported thousands of overloads and dropped audio at 48 dB SNR). While a
DAB session holds the receiver, or the mode is `wfm`, Radio applies a gain
of its own (ohsradio/bcastgain.py has the reasoning). AIS holding the
receiver ("AIS" below) uses the same policy with one difference: it starts
at the operator's own gain, not the broadcast default, and moves only on
overload - AIS is weak signals, not a multiplex (`broadcastGain` while it
runs says so).

- **The operator's settings never change.** `rxGain`, `rxGainMode` and
  the antenna keep what the operator set, in `api/state`, Settings and the
  saved configuration; only what the device is given changes. When the
  station ends - the session stopped, `api/stop`, a mode change out of
  `wfm`, the radio stopping - the device gets the operator's exact gain
  back.
- It starts at a broadcast default for the device's `gainModel` (`db`:
  30; `sdrplay`: 30, gRdB 49; `soapysdrplay3`: 45, gRdB 59 at LNA state
  6, where every Band III block of a sweep on ohs-box was clean), or the
  operator's own where that is already less gain.
- **DAB steers by its FIB errors** (the session's `fibsOk`/`fibsBad`, a
  second at a time). Clean FIBs move nothing, whatever the overload flag
  says (an RSP's flickers on clean blocks). Errors with overload reported:
  one step less gain; errors without: one step more, as far as the
  operator's own gain. A step that makes the errors worse is undone and
  never tried again for that station (`floorDb` on the weak side), so it
  backs off only until the errors stop and never past the weak-signal
  cliff.
- **Wide FM, and DAB before it has FIBs,** have only the device's overload
  report (`deviceStatus` `overloads` rising, SDRplay RSPs): one step less
  after overload in three 1 s windows running, and one step back after
  30 s clear, never past the start and never into a gain that overloaded
  in the last 5 minutes. A radio that reports no overload (RTL-SDR,
  Pluto, SoapySDR, the simulator) holds the default there; for DAB its
  FIB errors still steer it (trying less gain first).
- Nothing changes under the radio's own AGC (`rxGainMode` not `manual`),
  on a Hermes-Lite 2 (its gain is `hl2Lna`), or while a recording plays.
  The band scan and background `wfm` decoder sessions keep the operator's
  gain: the scan gives the receiver back at once, and a background session
  shares it with the dial.

`broadcastGain` in `api/state` and `api/status`, for a client to show:

```json
{"auto": true, "db": 45.0, "operatorDb": 40.0, "gainModel": "soapysdrplay3", "adaptive": true,
 "state": "settled", "signal": "fibs", "fibBad": 0.0, "overloaded": false, "backoffs": 0,
 "atLimit": false, "floorDb": null,
 "text": "Broadcast gain 45, chosen for this station. Your own gain, 40, is back when it stops."}
```

`db` is in `rxGain`'s own units and sense (`gainModel`, "S-meter
calibration" above: under `soapysdrplay3` a higher figure is less gain).
`state`: `settling` (the first 5 s), `adjusting` (errors or overload in
the last 5 s), `limit` (still errors, and no gain it may set is better:
`atLimit`), `settled`, or `fixed` (`adaptive` false and no FIBs to steer
by). `signal` is what it steers by now: `fibs` (with `fibBad`, the share
of FIBs failing in the last window) or `overload` (`fibBad` null).
`floorDb` is the gain found to be on the weak side, never set again for
this station, or null. While a
station plays and the operator's gain stands it is `{"auto": false, "db":
null, "why": "agc" | "no_rx_gain" | "playback", "text": ...}`; `{}` while
none plays. There is no per-session override: set `rxGainMode` to an AGC
mode to keep the device's own control for broadcast listening.

The S-meter reads the gain applied: a calibration made at the operator's
gain is corrected for it dB for dB, or, where the broadcast gain moved an
RSP's LNA state (`soapysdrplay3`), does not hold (`why`
`broadcast_gain`). `POST api/smeter/calibrate` answers `409
cannot_calibrate` while a broadcast gain applies; the stored calibrations
are never touched.

## RSP notch filters (Radio)

An SDRplay RSP has two switchable notches ahead of its LNA: a DAB notch
(Band III) and a broadcast notch (FM and MW together, one switch). A
strong transmitter in either band can overload the front end wherever the
receiver is tuned (Brian's RSPdx, 8 km from a DAB transmitter on 11B,
overloaded on 2 m). Two settings in `api/spec`, control level, Settings ›
Radio under "RTL-SDR and SDRplay"; code `ohsradio/notch.py`, tests
`tests/test_ham_notch.py`:

| Setting | Values (default `auto`) | `auto` |
|---|---|---|
| `dabNotch` | `auto`, `on`, `off` | out, until the RSP reports overload in three one-second windows running while its span is clear of 150-240 MHz; then in, and out again after 5 minutes with no overload (10, 20... up to 60 if it comes back within the hour). Always out while the span touches 150-240 MHz - the notch's own stopband (>30 dB 160-230 MHz, >20 dB 155-235 on an RSPdx) with a margin: Band III, marine VHF and AIS - and while a DAB session or AIS holds the receiver |
| `rfNotch` | `auto`, `on`, `off` | in only while the whole span is below 60 MHz and clear of LW (148.5-283.5 kHz) and MW (526.5-1705 kHz); out above 60 MHz |

`on` (in) and `off` (out) hold a notch wherever the receiver is.

**Measured cost on 2 m** (ohs-box, 24/10/2026, Store Radio beta.7, RSPdx,
Antenna A, 145.300 MHz FM, rxGain 40, back-to-back minutes): the DAB
notch in took about 4 dB off the signal and about 2.5 dB off
signal-to-floor, and there were no overloads with it in or out. So
`dabNotch` auto leaves it out until overload says it is needed (beta.7
put it in everywhere outside Band III). The overload count is the
SDRplay API's (`deviceStatus.overloads`, read as broadcast gain reads
it); a radio that keeps none - SoapySDR with SoapySDRPlay3 - never gets
it in on `auto`. The span
is the RSP's own: its local oscillator plus and minus half the sample rate,
so through a converter it is the IF the RSP sees. What the switches cover,
from SDRplay's datasheets (the API specification does not say): on an
RSPdx, DAB >30 dB 160-230 MHz; FM >30 dB 77-115 MHz and MW >30 dB
500-1530 kHz - and the FM notch also takes at least 4 dB off 2 m
(144-148 MHz), which is why `auto` leaves it out above 60 MHz (2 m, 70 cm
and the FM band itself). `rfNotch: "on"` puts it in everywhere, for a
station near a strong FM transmitter.

- **Which radios:** an RSP whose model has the switch - RSPdx (and dx R2),
  RSP1A, RSP1B and RSPduo have both; the RSP2 only `rfNotch`; the RSP1
  neither. On an RSPduo's Tuner 1 Hi-Z input `rfNotch` is that port's
  MW-only notch. Every other radio ignores both settings: they stay in
  `api/spec` and Settings, and the device is never asked. That holds for
  `device sdrplay`, `device soapy` reaching an RSP through shack_sdr
  (ohs-box), and SoapySDR with SoapySDRPlay3 installed (its
  `rfnotch_ctrl`/`dabnotch_ctrl`).
- **Live:** applied on the running stream, one SDRplay API update per
  switch that changes, never a reopen: when either setting changes and
  whenever the receiver's centre moves (a dial change out of the span, a
  DAB session taking or giving back the receiver, the band scan). A radio
  lost and reopened comes back with the notches it had.
- **What is applied** is `deviceStatus.options` in `api/status`: each
  switch the open RSP has, as SDRplay's API holds it (`rf_notch`,
  `dab_notch`, and `bias_t` and `hdr`, which Radio never changes), e.g.
  `{"rf_notch": false, "dab_notch": false, "bias_t": false, "hdr": false}`
  on an RSPdx tuned to 11B with both on `auto`. Absent for a radio
  without them.
- **Why each is in or out** is `notches` in `api/state` and `api/status`,
  per switch the open RSP has: `{"dab_notch": {"setting": "auto", "in":
  true, "why": "overload", "text": "in: overload seen at 145.300 MHz"},
  "rf_notch": {"setting": "auto", "in": false, "why": "band", "text":
  "out: tuned above 60 MHz or within MW or LW broadcasting"}}`. `why`:
  `setting` (on or off), and for `dabNotch` auto `default` (no overload
  seen), `overload`, `clear` (taken out after the hold), `stopband` (150-240 MHz),
  `dab`, `ais`; for `rfNotch` auto `below_60mhz` or `band`. `{}` for a radio
  without them.

## Station lists (Radio)

Radio scans the FM band and DAB's Band III by itself once a week, at night,
while nobody is using the radio, and keeps what it finds (code
`ohsradio/bandscan.py`, tests `tests/test_ham_bandscan.py`; Brian,
23/10/2026). Receive only: nothing here keys, and the scan never stands in
anybody's way.

**When.** The first moment after `scanHour` o'clock local time (3 by
default) and within the hour, a band whose list is older than
`scanEveryDays` (7; the same night a week later counts) is scanned if Radio
is idle: no `api/audio/rx` listener, nothing changed for `scanIdleMinutes`
(30), not transmitting or automatic transmit armed, not recording (IQ or
audio) or playing a recording, no decoder session, the CW skimmer off, and
nothing holding the receiver (`rxOwner`). Busy, that night is skipped (the
band's `status` `busy`, `statusText` the reason) and the next night tries
again. `scanAuto` false stops the nightly scans; `POST api/scan` still
works. All four are control-level settings in `api/spec`.

**It gives the radio back at once.** The scan holds the receiver
(`rxOwner` `{"by": "scan", "session": "bandscan", "block": "the FM band"
| "Band III (DAB)", "freqHz": <the receiver's centre now>, "prior": {…},
"text": "Radio is scanning the FM band for its station list: it is yours
again the moment you use it"}`) but moves only the receiver's centre: the
dial (`vfo`), the mode and every other setting stay as the operator left
them, and `txBlocked` goes on judging that dial. The moment anyone does
anything - an `api/set` that changes anything, a listener connecting to
`api/audio/rx`, a key-up or arming automatic transmit, a decoder session,
a recording, `api/stop` - the scan ends before that request is handled:
everything it kept (dial, mode, repeater settings, RIT, gain mode, gain,
the RSP's LNA state, the antenna, the de-emphasis, the sample rate) and
the receiver's centre are put back exactly, then the request applies. The
band's status is then `aborted` and its last list stays. While it runs,
`api/audio/rx` carries silence. The sample rate is never changed (that
reopens the radio and, on a controller, hands the broker's claim back).

**How long** (at the RSPdx's 2.4 MS/s, its only rate in Radio): FM is
eleven hops of 3 s across 87.5-108 MHz (about 35-40 s); DAB is 41 blocks
(5A-13F) of 1.2 s each, and a block holding an ensemble is listened to
1.2 s more at a time, up to 6 s, until its list is complete and every
service has its programme type (about 55 s, plus 1.2 s for each block
that needs it). On the local blocks' captures every type comes with the
labels, so only a block slow to complete pays: 12A, which beta.8 left
incomplete at 2.4 s, listens 3.6 s if it needs one step more;
a block with a service that never sends a type pays the whole 6 s, at
most 38 s more over the eight local ensembles. At 1.2 MS/s FM takes 26
hops and DAB is refused
(`unsupported`: it needs 2.048 MS/s).

**Progress** in `api/state` (and its `state` diffs): `bandScan` is
`{"band": "fm" | "dab", "percent": 0-100, "phase": "tuning" | "listening" |
"decoding", "freqHz", "text": "FM: 95.15 MHz (5 of 11)"}` while a scan
runs, `{}` otherwise. `stationsAt` is `{"fm": <ISO UTC> | null, "dab": …}`,
when each list was last made; it changes with the list, as does the
`stations` event.

**`GET api/fm/stations`**:

```json
{"scannedAt": "2026-11-02T03:00:41Z", "nextDue": "2026-11-09T03:00:00Z", "status": "ok", "statusText": "",
 "stations": [
  {"pi": "C201", "ps": "SIM ONE ", "pty": 10, "ptyName": "Pop music", "rt": null,
   "best": {"hz": 88600000, "level": -38.0, "stereo": true},
   "alts": [{"hz": 91300000, "level": -47.0, "stereo": true}]},
  {"pi": null, "ps": null, "pty": null, "ptyName": null, "rt": null,
   "best": {"hz": 97700000, "level": -46.0, "stereo": true}, "alts": []}]}
```

One entry per programme: stations with the same PI are merged, the
strongest frequency `best` and the others `alts` (strongest first); a
station without RDS is one entry of its own with `pi` null. `level` is
the carrier in dBFS (relative: no calibration), `stereo` whether its pilot
was heard. `ps` is as sent (8 characters, padded); `rt` is RadioText when
the 3 s on its hop were enough to read it, often null. By `best.hz`. To
tune: `POST api/set {"changes": {"mode": "wfm", "vfo": best.hz}}`.

**`GET api/dab/stations`**: the same `scannedAt`, `nextDue`, `status`,
`statusText`, and

```json
{"ensembles": [{"block": "11D", "freqHz": 222064000, "id": "C1CE", "label": "Shack Test Mux", "country": "GB", "ecc": "E1",
                "services": [{"sid": "C221", "label": "Shack MP2 Tone", "kind": "dab", "bitrate": 128,
                              "pty": 10, "ptyName": "Pop music", "language": "en", "hasSlideshow": true,
                              "logoPath": "api/dab/logos/C221", "logoUrl": "/apps/radio/api/dab/logos/C221",
                              "logoSource": "broadcast",
                              "logoWidePath": "api/dab/logos/C221?variant=wide",
                              "logoWideUrl": "/apps/radio/api/dab/logos/C221?variant=wide",
                              "logoWideSource": "radiodns"},
                             {"sid": "C3A7", "label": "Shack DAB+ Data", "kind": "dab+", "bitrate": 64,
                              "pty": 9, "ptyName": "Varied", "language": "en", "hasSlideshow": true}]}]}
```

`pty` (the code, 0-31) and `ptyName` are the genre to show beside the bit
rate, `language` ISO 639, `country` ISO 3166, `ecc` the ensemble's
extended country code (`"E1"`; absent from a list made before it was
kept); null when the scan's second or two on the block did not
catch them. `logoUrl` and `logoWideUrl` (and their `…Path`, and
`logoSource`/`logoWideSource`) appear once a logo has come from listening
to that ensemble or from RadioDNS ("DAB pictures and service information"
above); the scan itself brings none, but a new list is looked up in
RadioDNS straight after.

To play one: `POST api/decoders/sessions {"decoder": "dab", "freqHz":
freqHz, "params": {"block": block, "service": sid}}` ("DAB" above).

`status` is `never` (not scanned yet), `scanning`, `ok`, `busy` (the night
was skipped), `aborted` (someone wanted the radio), `unsupported` (this
radio cannot: "The hl2 does not receive the FM band", the DAB rate
sentence) or `failed`, with `statusText` the sentence (`""` for `ok`).
`scannedAt` is null until the first good scan; `nextDue` is when the next
nightly attempt will be (ISO UTC), null with `scanAuto` off. The lists are
kept in the app's data folder (`bandscan/fm.json`, `bandscan/dab.json`) and
survive updates.

**`POST api/scan`** refuses, with the sentence in `error`, while the
radio is busy as above - except that a listener or a recent change is no
reason to refuse the person asking: `409 receiver_busy` ("Not scanning
now: Automatic transmit is armed", "... A band scan is running already"),
`409 unsupported`, `400 bad_params` for another `band`, `503 not_running`.
`both` scans what this radio can (`bands` says which).

## DMR (Radio)

A `dmr` session (since 28/10/2026) decodes a DMR Tier II channel - a
repeater, a radio on a simplex channel, or a TDMA direct-mode pair - with
**both timeslots at once**: calls with their IDs, talkgroup or private,
colour code, talker alias, encrypted and emergency flags, level and bit
error rate, and short messages. All of that is ohs-libs shack_sdr's own
Rust (shack_sdr README "DMR"). Its **voice** is AMBE+2, which only the
user's mbelib turns into sound: Radio never includes it (Settings ›
Decoders › Codecs; on a controller a host library). Without mbelib
everything but the sound still decodes, the entry is `available` with
`partial: true, missing: ["mbelib"]`, and a session says
`needs_codec:mbelib` while a call goes unheard. **Encrypted calls are
shown as encrypted and never decoded**, whatever is installed. Receive
only, like every decoder.

**Start:** `POST api/decoders/sessions {"decoder": "dmr", "freqHz":
439612500}` at control level - the channel's centre frequency. It takes a
12.5 kHz channel of the bank at 48 kS/s (any rate from 16 kS/s works), so
it sits beside the dial and other sessions in the span as any narrow
decoder does. `params`: `slot`, `"1"`, `"2"` or `"both"` (default), the
slots whose voice is heard, both mixed; changed live with `POST
api/decoders/sessions/{id} {"params": {"slot": "2"}}`. To hear it:
`POST api/decoders/sessions/{id}/listen {"listen": true}` (above); its
sound is 8 kHz mono in the decoder, converted to the stream's own rate.

**The session's `meta`** (in its view and as `meta` items on the
`decoder` feed), whenever a slot changes and once a second during a call:

```json
{"mode": "bs", "cc": 1,
 "slots": [
  {"slot": 1, "state": "voice", "src": 9990001, "dst": 99, "callType": "group", "cc": 1,
   "alias": "MX0TST Test", "encrypted": false, "emergency": false,
   "callStart": 1793166482.24, "lastHeard": 1793166484.92, "rssiDb": -61.8, "ber": 0.0012,
   "srcCallsign": "MX0TST", "dstName": "Test Ninety-Nine"},
  {"slot": 2, "state": "idle", "src": 9990003, "dst": 98, "callType": "group", "cc": 1,
   "alias": null, "encrypted": true, "emergency": false,
   "callStart": 1793166478.10, "lastHeard": 1793166479.30, "rssiDb": -62.0, "ber": 0.0,
   "srcCallsign": "Q9CCC", "srcName": "Charlie", "srcCountry": "Otherland"}]}
```

- `mode`: what the channel carries - `bs` (a repeater's output), `ms` (a
  radio, simplex or a repeater's input) or `direct` (TDMA direct mode);
  null until a burst is heard. `cc`: the colour code heard.
- Each slot: `state` `idle`, `voice` (a call in progress) or `data` (a
  message arriving); `src` and `dst` the radio IDs (DMR IDs, 24-bit);
  `callType` `group` (`dst` is a talkgroup) or `private` (`dst` is a
  radio); `alias` the talker alias once its fragments have all arrived;
  `encrypted`, `emergency`; `callStart` and `lastHeard` UTC seconds;
  `rssiDb` the channel's power, dB full scale; `ber` the share of bits the
  error correction fixed over the slot's last two seconds or so (0.01 is
  1 %).
- `srcCallsign`, `srcName`, `srcCountry` and `dstName`, **only when
  known** (absent otherwise): the caller named and the talkgroup's name,
  below ("Callsigns and names").
- **An idle slot keeps its last call's** `src`, `dst`, `callType`, `cc`,
  `alias`, `encrypted` and `callStart`, so a client shows "last heard"
  without keeping history of its own. Fields not yet known are null: a
  call heard without its header ("late entry") has `src` and `dst` null
  for up to a superframe (360 ms), until the embedded link control names
  it.

**Results** on the `decoder` feed and in `GET api/decoders/sessions/{id}`
(`type: "frame"`, `frame` naming it), each with `slot` (1 or 2):

| `frame` | Fields |
|---|---|
| `call_start` | `src`, `dst`, `callType`, `cc`, `encrypted`, `emergency`, `lateEntry` |
| `call_end` | `src`, `dst`, `callType`, `cc`, `encrypted`, `emergency`, `alias`, `durationS`, `ber` (over the whole call), `rssiDb` |
| `talker_alias` | `src`, `alias`: as soon as an alias is complete |
| `sms` | `src`, `dst`, `group`, `text`, `sap`, `srcPort`, `dstPort`, `octets`: a short message (an IP/UDP datagram, Motorola's text messaging and its like) |
| `data` | as `sms` without `text`: a data message with no text found in it |

Every result with a `src` may also carry `srcCallsign`, `srcName` and
`srcCountry`, and one to a talkgroup (`callType` `group`, or an `sms`/`data`
with `group` true) `dstName`, as the slots do; the kept results in
`GET api/decoders/sessions/{id}` are the named ones.

The session's `stats` add `bursts`, `syncs`, `misses`, `calls`,
`voiceFrames`, `lcOk`, `lcBad` and `dataMessages` to the usual ones;
`snrDb` is the symbols' (about 7 dB over the channel's C/N) and
`offsetHz` the carrier's offset while `sync` holds.

**Codes** (`why`, worded as `whyText`): `needs_codec:mbelib` - "Calls are
shown, but their voice needs mbelib: install it to hear them. Radio never
includes it: see Help › Codecs." (on a controller: "...ask your
controller's administrator to install it (Controller › Optional
libraries)"). Refusals of `listen`: `no_audio`.

**The simulator** has a DMR repeater on 439.6125 MHz (colour code 1),
playing shack_sdr's DMR test transmitter's showcase over and over: on
slot 1 a talkgroup call from 9990001 to talkgroup 99 with the talker alias
"MX0TST Test", then an SMS from 9990002 to 9990001 ("Hello from the DMR
simulator"); on slot 2, overlapping it, a private call from 9990002
("MX0ABC") to 9990001 and an encrypted call from 9990003 to talkgroup 98.
Country code 999 is no country's, so the IDs name nobody. With mbelib the
test voice frames play as a buzz.

### Callsigns and names

A DMR call carries only numbers. Since 28/10/2026 Radio names them from
two lists it fetches itself in the background (ohsradio/dmrids.py): the
radio IDs registered with **radioid.net** (callsign, first name, city,
state, country) and **Brandmeister**'s talkgroup names. Every client gets
the names in the session's `meta` and results; **no client ever reaches
the internet for them**, and no route serves the lists themselves.

- **Offline, nothing changes.** With no list yet, no route out or the
  sources failing, a session shows bare IDs as it always did: no error
  anywhere, no wait. A fetch never sits on a request's path: a lookup
  reads a small database on the controller's own disk.
- **The talker alias wins.** A callsign at the start of the alias the
  caller's radio sends (`"MX0TST Test"` gives `"MX0TST"`) is
  `srcCallsign`, list or no list; the list's `srcName` and `srcCountry`
  are added only when the list gives that ID the same callsign (else they
  would describe the ID's owner, not the caller). An alias with no
  callsign in it leaves the list's callsign standing.
- **`dstName`** is for talkgroups only; a private call's `dst` is a radio.
- **The setting** `dmrIdLookup` (bool, default `true`; `api/set`, Settings
  › Decoders › DMR): off means no traffic at all and the fields exactly as
  before (no `src*`/`dstName`, the alias's callsign included). The copy on
  disk is kept for when it is on again; turned on, a fetch is tried within
  seconds.
- **The cache** lives in the app's data folder, `dmrids/`: `users.sqlite`
  (about 12 MB for a list of radioid.net's size), `talkgroups.json`,
  `state.json` (each source's validators, last look and backoff). It is
  never part of Radio's package or repository: radioid.net's data-use
  policy forbids republishing its list, so each controller (or desktop)
  fetches its own. A refresh is built beside the live copy and renamed
  over it only when whole and non-empty, so a lookup sees the old list or
  the new one, never half; a download cut short leaves the old one.
- **What goes out:** `GET https://radioid.net/static/user.csv` (17 MB) and
  `GET https://api.brandmeister.network/v2/talkgroup` (about 17 kB
  gzipped), each **once a week**, first tried three minutes after start;
  the users list conditional (`If-None-Match`, `If-Modified-Since`), so an
  unchanged week costs a 304. User-Agent `OpenHamShack-Radio/<version>`
  and nothing else about the station: no cookies, no query, no callsign,
  locator or contact address. A failure backs off silently, an hour
  doubling to a day, kept across restarts, and is retried at that pace for
  ever. Names are never logged: only counts and causes.

`dmrIds` in `api/status` and `api/state` (and its `state` diffs when a
list is fetched or the setting changes):

```json
{"available": true, "count": 287041, "updatedUtc": "2026-10-28T14:02:11Z",
 "source": "radioid.net", "talkgroups": 1874}
```

`available` is true while names are being added from a list (false with
no list yet, offline, or the setting off); `count` the IDs in the users
list (0 without one); `updatedUtc` when that list was last downloaded
(not when a 304 confirmed it), null without one; `source` where it came
from, null without one; `talkgroups` the talkgroup names held.

**The simulator's** IDs are under country code 999 and named by their
aliases (`MX0TST`, `MX0ABC`); tests serve their own fake lists, whose
callsigns start with Q, a prefix no country issues.

**Not yet:** Tier III trunking and CSBKs, rate 1 data, GPS positions in
the embedded link control, real-air checks (recordings of local repeaters
are to come). On a controller mbelib is a host library (below), staged
by platform 2.0.0-beta.10 and later.

## Host libraries (store form)

What the image may not carry comes from the controller's host:
`store/radio/module.yaml` declares `host_libraries: [faad2, sdrplay-api, mbelib]`
(mbelib since 28/10/2026, needing platform beta.10),
and a controller that knows the key (platform beta.9 or later) mounts each
at `/opt/hostlibs/<name>` read-only and sets `SHACK_HOSTLIBS`. Its
administrator installs them (Controller › Optional libraries); Radio can
only say so. `hostLibs` in `api/status` and `api/state`:

```json
{"supported": true, "root": "/opt/hostlibs", "libraries": {"faad2": true, "sdrplay-api": false, "mbelib": true}, "why": ""}
```

On an older controller, which installs the app with the key ignored and
mounts nothing, it is `{"supported": false, "root": null, "libraries": {},
"why": "Update the controller to use SDRplay radios and DAB+"}`. The status
page shows that sentence, and it replaces "ask your administrator" for the
RSP, the faad2 codec and a DAB+ station's `whyText`, because nothing an
administrator installed would reach the app. Nothing else changes and the
app runs on. `{}` outside the store form.

## Wide FM and listening outside the amateur bands (Radio)

What openhamshack-remote `docs/RADIO-LISTEN-CONTRACT.md` §1-2 asked of the
server, as built on 23/10/2026 (code `ohscore/dsp/wfm.py`,
`ohsradio/radio.py`; tests `tests/test_ham_wfm.py`,
`tests/test_ham_fmstereo.py`, `tests/test_ham_listen.py`,
`tests/test_core_wfm.py`).

- **`mode: "wfm"`** is in `api/spec`'s `mode` choices and `state.modes`,
  and is set like any mode: `POST api/set {"changes": {"mode": "wfm"}}`.
  50 us de-emphasis by default; `wfmDeemphasis` (control level, `50` or
  `75`, unit us) is the other. The audio is the ordinary `api/audio/rx`
  stream, 48 kHz since 23/10/2026, flat to 15 kHz (it was 12 kHz and
  5 kHz). No squelch in wfm: `sqlOpen` reads true.
- **Stereo** (since 23/10/2026, shack_sdr's `wfm.Receiver`: pilot PLL,
  blend to mono on a weak signal): a station with its 19 kHz pilot is
  heard in stereo with `?channels=2` and averaged without, exactly as a
  DAB station is. `audio.stereo` in `api/status` is the receiver's stereo
  flag (the pilot held 150 ms; off after 300 ms without it), and the
  `meter` item carries `stereo` (true/false) in wfm, ten times a second.
  A blended weak station is still a stereo station: the flag says so,
  the sound is nearer mono. Without the shack-sdr wheel (a package built
  for no platform) wide FM is mono and has no RDS.
- **RDS** in `api/state` (and its `state` diffs on `api/events`) as `rds`:

  ```json
  {"pi": "C201", "ps": "SIM ONE ", "rt": "Sim One: 1 kHz left, 1.5 right", "pty": 10,
   "ptyName": "Pop music", "ta": false, "tp": false, "ct": "2026-10-23T15:05:00+01:00",
   "af": [91300000], "stereo": true, "ts": 1792747301.5}
  ```

  The library's field names (ohs-libs `rust/shack_sdr/README.md`
  "Broadcast FM"): `pi` the programme identification in hex, `ps` the
  8-character name as sent (padding kept; trim it to show it), `rt`
  RadioText (null until a whole one is heard twice alike), `pty` the
  programme type number and `ptyName` its name (European table, in the
  server's language), `ta`/`tp` traffic flags, `ct` the station's clock
  (ISO 8601 with its offset, or null), `af` alternative frequencies in Hz,
  `stereo` the stereo flag, `ts` when the newest field arrived (UTC
  seconds). A field is published only once it is stable, and never half
  old and half new. `rds` is **null** until a station's PI is heard,
  outside wfm, while something else holds the receiver (`rxOwner`), and
  from the moment the dial moves: every retune, however small, clears it
  in the same `api/set` and starts the receiver again, so the last
  station's name is never shown against a new frequency.
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

## Local frequencies (Radio)

What there is to listen to near the station (Brian, 23/10/2026): from the
station profile's locator, every listening frequency within a radius,
nearest first, for Remote and the desktop to list and tune. Code
`ohsradio/localfreq.py`, data `ohsradio/data/localfreq/`, built by
`tools/localfreq-build.py`; tests `tests/test_ham_localfreq.py` and
`tests/test_ham_server_localfreq.py`. NB answers `404 not_found`. Nothing
here transmits or touches the radio: a client tunes with the ordinary
`POST api/set {"changes": {"vfo": freqHz, "mode": mode}}` and its own step.

**`GET api/local-frequencies?radiusKm=&category=`** (view). `radiusKm` 1 to
2000 (default the `localRadiusKm` setting, 100, itself settable through
`api/set` at control); `category` one of `airband`, `enroute`, `marine`,
`pmr`, `cb`, `lpd`, `beacon`, `mine` (default all). `400 bad_radius` /
`400 bad_category` otherwise.

```json
{"locator": "IO75TU", "radiusKm": 100, "generatedAt": "2026-10-23T12:00:00Z",
 "attributions": [{"source": "OurAirports", "text": "Airfield frequencies from OurAirports (public domain)",
                   "licence": "Public domain", "url": "https://ourairports.com/data/"}, ...],
 "entries": [{"id": "ourairports:EGPF:118800000", "category": "airband", "name": "Glasgow Airport",
              "sub": "TWR Glasgow Tower", "freqHz": 118800000, "mode": "am", "step": 8333,
              "distanceKm": 4.1, "bearingDeg": 299, "source": "ourairports"},
             {"id": "itu-marine:16:156800000", "category": "marine", "name": "Marine Ch 16",
              "sub": "distress, safety and calling", "freqHz": 156800000, "mode": "fm", "step": 25000,
              "source": "itu-marine"},
             {"id": "mine:m3f2a9c1d", "category": "mine", "name": "GB3GA", "sub": "", "freqHz": 145712500,
              "mode": "fm", "source": "mine", "userCategory": "repeater", "notes": "CTCSS 103.5",
              "locator": "IO75TU", "distanceKm": 0.0, "bearingDeg": 0}],
 "ncdxf": {"now": {"14100000": {"call": "4U1UN", "location": "United Nations, New York"}, "18110000": {...}, ...},
           "at": "2026-10-23T12:00:00Z", "nextChangeS": 10.0, "slotSeconds": 10, "cycleSeconds": 180,
           "frequencies": [14100000, 18110000, 21150000, 24930000, 28200000],
           "schedule": [{"slot": 0, "call": "4U1UN", "location": "United Nations, New York"}, ...],
           "credit": "NCDXF/IARU International Beacon Project"}}
```

- **Order:** by category in the order above; inside one, the entries
  with a position nearest first, then those without one (the channel
  tables) in table order. `distanceKm`/`bearingDeg` (from true north) are
  present only for an entry with a position. An airspace (openAIP) is 0 km
  when the station is inside it, else the distance to its nearest corner.
- **`mode`** is Radio's own mode name (`am`, `fm`, `cw`, `usb`...);
  **`step`** (Hz, optional) the channel raster: 8333 for an 8.33 kHz
  airband channel (its `freqHz` is the real carrier, 118008333, never the
  channel's name 118.010), 25000 marine and LPD, 12500 PMR446, 10000 CB,
  10 the beacons.
- **`source`:** `ourairports`, `openaip`, `itu-marine`, `hmcg`,
  `osm-marine`, `channels`, `ncdxf`, `mine`. `attributions` names only
  the sources with an entry in this answer; a client shows every `text`
  wherever it shows the list (the licences require it).
- **The beacons:** five `beacon` entries, one per NCDXF/IARU frequency,
  their `sub` naming the beacon on it now; `ncdxf.now` is the same per
  band (keys are `freqHz` as strings), computed from UTC when asked.
  Each beacon sends 10 s per band, moving up a band each slot, so
  `nextChangeS` says when to ask again. A beacon may be off the air; the
  schedule says only whose turn it is.
- **No locator** in the station profile: positioned sources are left
  out, the tables and "mine" are listed, and `why` says so.
- **"Mine"** entries are listed whatever the radius.

**My frequencies** (control): the operator's own list, in the data folder
(`/data/local-frequencies-mine.json`), not the settings, at most 500.

| Field | Rule |
|---|---|
| `name` | 1-60 characters, required |
| `freqHz` | whole Hz, 10 kHz to 10 GHz, required |
| `mode` | one of Radio's modes (`api/spec` `mode` choices), required |
| `category` | 1-30 letters, digits, spaces, `-`, `_` (e.g. `repeater`); default `other`; listed as `userCategory` |
| `locator` | optional Maidenhead, 4, 6 or 8 characters (gives it a distance) |
| `sub`, `notes` | optional, 60 and 300 characters |

No other field is accepted (`400 bad_field` naming it), so nothing about
a person can be stored; line breaks and control characters are refused.
`POST api/local-frequencies/mine` answers `201` with the entry and its
`id`; `PUT …/mine/{id}` takes only what changes and answers `200` with the
entry; `DELETE …/mine/{id}` answers `{"deleted": id}`; an unknown id is
`404 unknown_entry`. A refusal is `400 {"error", "code": "bad_field",
"field"}`.

**`POST api/local-frequencies/refresh`**: an administrator's action.
Radio's levels stop at Transmit, so "admin" is the controller's
administrator flag (`X-OpenHamShack-Admin: 1`, CONTROLLER-CONTRACT 5.3) on
a Control-level request; anyone else gets `403 not_admin`. It downloads,
synchronously (allow a minute: OurAirports is 14 MB of CSV):

- OurAirports' two CSVs (worldwide), replacing the bundled copy;
- OpenStreetMap marine VHF tags from Overpass within `localRadiusKm` of
  the station, added to the bundled GB/IE extract;
- openAIP airspaces with frequencies within the radius, if the module
  setting `OPENAIP_API_KEY` is set (sent only as the
  `x-openaip-api-key` header), added to the bundled copy.

- in Radio, Ofcom's DAB transmitter list (`ofcom-dab` in `results`,
  "Transmitters heard" above), replacing the bundled copy; it lands in
  `/data/dabtx/`.

Each lands in `/data/localfreq/` and succeeds or fails alone; a failed or
unreadable one leaves the bundled copy in use. Never run at start-up, never
needed: a controller with no route out lists the bundled data. `409
refresh_running` while one runs. The answer:

```json
{"refreshedAt": "2026-10-23T12:00:00Z",
 "results": [{"source": "ourairports", "ok": true, "entries": 27407, "why": "", "fetched": "2026-10-23"},
             {"source": "osm-marine", "ok": true, "entries": 41, "why": "", "fetched": "2026-10-23"},
             {"source": "openaip", "ok": false, "entries": 0, "why": "No openAIP API key is set"}],
 "sources": [{"source": "ourairports", "entries": 27407, "fetched": "2026-10-23", "coverage": "worldwide",
              "attribution": {...}, "refreshable": true}, ...]}
```

**The data and its licences**, each file with its own notice
(`<name>.LICENCE.txt`) beside it:

| File | From | Licence, attribution | Bundled coverage |
|---|---|---|---|
| `ourairports.json.gz` | OurAirports `airports.csv`, `airport-frequencies.csv` | public domain | worldwide: airfields (not closed) with a 118-137 or 225-400 MHz frequency; CNTR/ACC/CTR/FIR under `enroute` |
| `openaip.json` | openAIP API | CC BY-NC 4.0, "Contains data from openAIP (www.openaip.net), CC BY-NC 4.0" | empty in a release built without a key; filled around the station by Refresh |
| `osm-marine.json` | OpenStreetMap via Overpass (`vhf`, `contact:vhf`, `seamark:radio_station:channel` and the other tags in `OSM_VHF_KEYS`) | ODbL 1.0 (a derived database), "Contains information from OpenStreetMap, which is made available here under the Open Database License (ODbL)" | GB, IE, IM, JE, GG |
| `hmcg.json` | MCA Advice Note 1033 (4 April 2025), Table 5 | OGL v3.0, "Contains public sector information licensed under the Open Government Licence v3.0" | UK: the MSI aerials (positions approximate, to about 5 km) and Ch 67 |
| `itu-marine.json` | ITU RR Appendix 18 (plus the UK's M and M2) | facts | the channel plan |
| `channels.json` | CEPT ERC Rec 70-03, Ofcom IR 2030 | facts | PMR446 16, CB CEPT 40 FM, CB UK 27/81 40, LPD433 69 |
| `ncdxf.json` | NCDXF/IARU International Beacon Project | credited | 18 beacons, 5 frequencies |

Not used, by Brian's choice: RepeaterBook, UKRepeater/ETCC, G3USF's list,
NATS AIP, VATSIM. No repeater list is shipped; repeaters are the
operator's own entries.

### The dial label

What the dial is on, named beside the frequency (Brian, 28/10/2026: "name
the repeater that is selected"): `dialLabel` in `api/state` (and its
`state` diffs) and `api/status`, worked out again whenever the dial,
mode or filter changes and whenever "my frequencies" is edited. Radio
only; absent in NB. Code `LocalFrequencies.dial_label` in
`ohsradio/localfreq.py`, `Radio._dial_label`; tests `DialLabel` and
`OnTheRadio` in `tests/test_ham_localfreq.py`, and
`tests/test_ham_server_localfreq.py`. It reads only what Radio already
has, the lists above and the operator's own: no repeater list is fetched
or shipped for it (the paragraph above; nor do UKRepeater or the RSGB's
ETCC API carry a licence that would allow it).

```json
{"kind": "repeater", "name": "GB3GA", "callsign": "GB3GA", "place": "Glasgow", "sub": "Glasgow", "mode": "fm",
 "cc": null, "ctcss": null, "network": null, "distanceKm": 12.3, "bearingDeg": 270,
 "freqHz": 145712500, "rxOffsetHz": -600000, "source": "mine", "id": "mine:m3f2a9c1d",
 "text": "GB3GA · Glasgow · FM"}
```

`null` when nothing is in reach.

- **Reach:** an entry is matched when the dial (`vfo`) is within half the
  receive passband of its `freqHz` (`rxFilterHi - rxFilterLo`: 6.25 kHz
  either side in FM, the AM width in AM, 1.2 kHz in USB), or within the
  entry's own `step` where that is tighter, so a wide filter never names
  the 8.33 kHz channel next door. The mode decides nothing else: a
  repeater is named however it is being listened to.
- **Which, of several:** the operator's own entries first, and among
  them one whose category is `repeater` before any other; then the
  bundled lists. Inside each, the nearest in frequency, then the nearest
  on the ground, then those with no position. A bundled entry with a
  position counts only within `localRadiusKm` of the station and only
  with a locator set, as in the listing; the operator's own count
  wherever they are.
- **`kind`:** `repeater` (one of "my frequencies" with category
  `repeater`), `mine` (any other of them), or the bundled entry's
  category (`airband`, `enroute`, `marine`, `pmr`, `cb`, `lpd`, `beacon`).
  `source` and `id` are the listing's, so a client can open the entry.
- **`text`:** what to show, the parts the entry has joined with " · ":
  its name, its `sub`, its mode in capitals ("Glasgow Airport · TWR
  Glasgow Tower · AM").
- **Only what is stored is said.** "My frequencies" has no callsign,
  place, CTCSS, colour code or network field, and none is read out of
  `notes`. For a repeater of the operator's, `callsign` is its `name`
  and `place` its `sub`; for everything else `callsign` and `place` are
  null. `cc`, `ctcss` and `network` are always null today: they are in
  the shape so a client can be written for them, and will be filled only
  if "my frequencies" gains those fields (a separate decision).
- **`rxOffsetHz`:** for a `repeater`, where it listens relative to
  `freqHz` (its input is `freqHz + rxOffsetHz`): the plan in force's
  repeater pairs (`ohsradio/plans/repeaters.py`), the table the dial's
  own `rptShift: "auto"` uses. `null` for anything else, and for a
  repeater off those pairs.
- **`distanceKm`, `bearingDeg`:** from the station's locator, as in the
  listing; `null` without a locator or a position.
- **Cost:** no network and no reading per change: the bundled entries
  are indexed by frequency once per process and the operator's file is
  read again only when its stamp changes. The first label of a run reads
  the bundled lists (about 0.1 s).

The desktop shows `text` on the readout's title line beside the
frequency (not in the one-line Tight header, which has no room).
OpenHamShack Remote's TV mode can show it under the frequency; nothing
there is built yet.

## AIS (Radio)

Ships on a map (Brian, 28/10/2026). Radio decodes AIS - both channels,
87B (161.975 MHz, "A") and 88B (162.025 MHz, "B") - **only while a client
has the ship map open**, keeps a table of every vessel heard, and serves
it. Code `ohsradio/ais.py` (and shack_sdr's `ais` decoder); tests
`tests/test_ham_ais.py`. Receive only: nothing here keys.

**The session.** A client opening its map calls `POST api/ais/session
{"client": "<id>"}` (control) and calls it again at least every `leaseS`
seconds (30) while the map stays open - every 10 s is right. `<id>` is the
client's own stable name, 1-64 of `A-Za-z0-9._:-` (the same id it uses as
`remote` elsewhere does). Closing the map, it calls `DELETE
api/ais/session?client=<id>`; a client that simply vanishes is forgotten
when its lease runs out. When no client is left the session ends **at
once** (`lingerS` 0 since 28/10/2026; it was 60 s, long enough for a TV
moving between views, until Brian decided on no linger: CLIENT-UI-PLAN
7.3) and the receiver goes back exactly as it was: the dial, mode and
repeater offset, and the receiver's centre. A client with client presence
and `"ais"` in its holds is renewing this lease through presence, and its
presence going ends its share at once ("Client presence" below); a client
without presence renews the lease as before. `DELETE api/ais/session?all=1` (control) ends it
at once whoever has the map open (an operator who wants the radio back).

While it runs AIS **holds the receiver** like a DAB station: `rxOwner` is
`{"by": "ais", "session": "ais", "block": "AIS", "freqHz": 162000000,
"prior": {...}, "text": "..."}`, the dial is at 162.000 MHz (the receiver's
DC spike falls between the channels, on neither), nothing at the dial is
demodulated (silence plays), and a tune (`api/set`) or a key-up is
refused `409 receiver_busy` with the sentence "The receiver is listening to
AIS for the ship map: close the map, or stop AIS, to tune or change mode".
A TV's map should show that it holds the receiver (`rxOwner.by == "ais"`).

Every answer of the session routes is the session view (also `ais` in
`api/state` and `api/status`, and `session` items on the feed):

```json
{"state": "running", "why": null, "text": "Listening to AIS on 161.975 and 162.025 MHz",
 "clients": 1, "startedAt": "2026-10-28T06:20:31Z", "endsInS": null,
 "centreHz": 162000000.0, "leaseS": 30.0, "lingerS": 0.0,
 "vessels": 6, "rev": 412, "frames": 380, "channelA": 191, "channelB": 189, "damaged": 3}
```

- `state`: `running` or `idle`. `why` (idle): `idle` (nobody had the map
  open), `stopped` (DELETE ?all=1), `radio_stopped`, `lost` (the receiver
  was taken back), `null` before the first session. `text` says it in a
  sentence. `endsInS`: seconds until it ends with no client, `null` while
  any client has it. `frames`: messages decoded this session, per channel;
  `damaged`: frames that failed their CRC, counted per slicer (the
  decoder reads each channel five ways, so one damaged burst counts up to
  five, and real air shows many: 2097 beside 228 good frames in five
  minutes off the Clyde); `implausible`: frames with a good CRC whose MMSI
  or numbers cannot be meant (never put in the table).
- **Refusals** (`{"error", "code"}`): `400 bad_client` (no or a bad
  `client`); `409 span_pinned` with `sessions` (background decoder
  sessions pin the span: AIS would stop them; again with `"dropSessions":
  true` to stop them, as for DAB, "The pinned span"); `409
  receiver_busy` (a DAB station has the receiver: the sentence says so);
  `409 on_air` (transmitting, or automatic transmit armed); `409
  decoder_unavailable` (no shack_sdr with AIS); `429 too_many_clients`
  (32); `503 not_running` (the radio is stopped: "Start the radio to see
  ships"). A view-level client (`403 level_too_low`) cannot start AIS but
  may read the table: show what is there and say decoding needs Control.
- **Gain and notches:** the operator's gain stands; `broadcastGain` only
  steps it down if the receiver reports overload (and back), as for wide
  FM but starting from the operator's own gain. The RSP's DAB notch stays
  out (`notches.dab_notch.why: "ais"`): its stopband covers 162 MHz.

**The vessels.** `GET api/ais/vessels` (view):

```json
{"rev": 412, "full": true, "removed": [], "keepMinutes": 60,
 "station": {"locator": "IO75RL", "lat": 55.479, "lon": -4.542},
 "session": {...the session view...},
 "vessels": [{"mmsi": 235999001, "class": "A", "name": "CLYDE SPIRIT", "callsign": "MCLY1",
              "imo": null, "shipType": 60, "shipTypeText": "Passenger",
              "lat": 55.6043, "lon": -4.9871, "positionAt": "2026-10-28T06:21:04Z", "accuracy": true,
              "speed": 16.0, "course": 255.4, "heading": 255, "turn": 0.0,
              "navStatus": 0, "navStatusText": "Under way using engine",
              "destination": "BRODICK", "eta": "10-29 18:30", "draught": 4.5,
              "length": 90, "beam": 16, "toBow": 70, "toStern": 20, "toPort": 8, "toStarboard": 8,
              "distanceKm": 29.31, "bearingDeg": 287.5,
              "lastHeard": "2026-10-28T06:21:04Z", "lastHeardTs": 1793168464.0,
              "firstHeard": "2026-10-28T06:20:32Z", "messages": 14, "channel": "A", "snrDb": 23.8,
              "lastType": 1, "rev": 410}]}
```

- One entry per MMSI, **nearest first**. A field is absent or `null` until
  a message has brought it: a Class A ship's name comes in its type 5
  (every six minutes on the air), so a new ship shows first as a position
  with no name - draw it with its MMSI. Everything is merged from each
  message type: positions (1, 2, 3, 18, 19, 27; 4 and 21 for base stations
  and aids), names and voyage (5, 19, 24), aids (21).
- Units: degrees (`lat` north, `lon` east, negative west), knots,
  degrees true (`course`, `heading`: `null` when not available), metres
  (`length`, `beam`, `to*`, `draught`), degrees a minute (`turn`). Times are
  ISO 8601 UTC; `lastHeardTs` is the same as epoch seconds, for ageing a
  symbol without parsing. `eta` is "MM-DD HH:MM" UTC as the ship gave it.
- `class`: `A`, `B` (ships' two transponder classes), `base` (a base
  station), `aton` (an aid to navigation: `aidType`, `aidTypeText`,
  `virtualAid`, `offPosition`), `sar` (an aircraft), `sart` (a distress
  beacon, SART/MOB/EPIRB: show it unmistakably), `other`.
- `shipTypeText`, `navStatusText`, `aidTypeText` are sentences in the
  server's language; `shipType`, `navStatus`, `aidType` the standard's
  numbers (ITU-R M.1371-5 tables 53, 45, 74) for a client that words them
  itself or picks a symbol (`shipType` 30 fishing, 36 sailing, 37 pleasure,
  50-59 service craft, 60-69 passenger, 70-79 cargo, 80-89 tanker).
- `distanceKm`, `bearingDeg`: from the station's locator (the station
  profile), `null` without one or without a position.
- **What gets in.** Only frames shack_sdr calls plausible (the MMSI's
  form for its message type - ships 2xx-7xx MID, base stations 00MID,
  aids 99MID, SAR 111MID, the 970/972/974 beacons - and every number in
  range): an implausible one never creates a vessel. A position that could
  not follow the vessel's last (more than 60 knots plus 1 km) is set aside
  and counted in `jumps`; a later one that agrees with it is believed.
- A vessel not heard for `aisKeepMinutes` (a setting, 1-1440, default 60)
  is dropped. The table is kept on the controller and survives a restart:
  a map opened after one shows the ships it had, with their real ages.

**Keeping up.** Every change bumps `rev`. `GET api/ais/vessels?since=<rev>`
answers only the vessels changed after that rev, in `vessels`, and the
MMSIs dropped after it, in `removed`, with `full: false`. When `full` is
true (no `since`, a `since` too old, or a newer one than the server has:
it restarted) the answer is the whole table and the client replaces its
copy. Live, `GET api/events?kinds=ais` (WebSocket, not in the default set)
sends, as they happen:

- `{"kind": "ais", "type": "vessel", "rev", "vessel": {...as above}}` - a
  vessel heard (the whole entry, not a diff).
- `{"kind": "ais", "type": "removed", "rev", "mmsi"}` - dropped by age.
- `{"kind": "ais", "type": "session", "session": {...}}` - the session
  started, ended, gained or lost a client, or began its linger.
- `{"kind": "ais", "type": "nmea", "t", "channel", "mmsi", "msgType",
  "sentences": ["!AIVDM,1,1,,A,...*hh"]}` - every message as NMEA 0183, for
  a log or other software.

A map client: fetch `api/ais/vessels` when the map opens, then follow the
feed; after a reconnect, `?since=` the last `rev` seen. A slow feed client
can lose items (oldest first); the `rev` gap says so - fetch `?since=`.

`GET api/ais/vessels/{mmsi}` (view): one vessel as above plus `track`, its
recent positions oldest first, `[{"t", "lat", "lon", "speed", "course"}]` -
a point when it has moved 25 m or a minute has passed, the last 120. `404
unknown_vessel` when it is not in the table; `400 bad_params` for an MMSI
that is not a number.

Simulator: Radio's simulator puts six fictional ships and a buoy in the
Firth of Clyde off the Ayrshire coast (`ohsradio/devices/simais.py`):
a ferry Ardrossan-Brodick, a cargo ship up the firth, a fishing boat off
Girvan, a Class B yacht, a pilot boat moored at Troon and a light on Lady
Isle - real bursts on both channels, decoded like a ship's, positions every
few seconds and names every half minute. Open the map with the radio on
the simulator and they appear within a minute.

## ADS-B (Radio)

Aircraft on the same map as the ships (Brian, 28/10/2026). Radio decodes
ADS-B - Mode S extended squitters on 1090 MHz, with what an aircraft's
other replies add - **only while a client has the aircraft map open**,
keeps a table of every aircraft it believes in, and serves it. Shaped
exactly like "AIS" above: read that first; only the differences are
spelled out here. Code `ohsradio/adsb.py` (and shack_sdr's `adsb`
decoder); tests `tests/test_ham_adsb.py`. Receive only: nothing here keys.

**The session.** `POST api/adsb/session {"client": "<id>"}` (control),
again at least every `leaseS` (30) seconds while the map is open;
`DELETE api/adsb/session?client=<id>` closing it; `DELETE
api/adsb/session?all=1` (control) to end it at once. It ends as soon as
the last client goes (`lingerS` 0, as AIS), and the receiver goes back
exactly as it was; presence renews it and ends a client's share as for
AIS (`"adsb"` in holds). A client with both maps open runs one session or the other, never
both: each holds the whole receiver, so starting ADS-B while AIS runs is
`409 receiver_busy` (and the reverse).

**The receiver.** While it runs ADS-B holds the receiver like AIS:
`rxOwner` is `{"by": "adsb", "session": "adsb", "block": "ADS-B",
"freqHz": 1090000000, ...}`; a tune or key-up is refused `409
receiver_busy` ("The receiver is listening to ADS-B for the aircraft map:
close the map, or stop ADS-B, to tune or change mode"). The receiver's
centre is **1090.000 MHz exactly** (no dial offset), so all of Mode S's
2 MHz is in the band.

**The rate.** Mode S needs a wide IF filter: an SDRplay RSP filters to
1.536 MHz below 5 MS/s, which cuts Mode S away (a real capture at 2.4
MS/s gave no ADS-B message at all: shack_sdr README, ADS-B). So the
session **reopens an RSP at 6 MS/s** (5 MHz filter), and any other
receiver at 2.4 MS/s if it runs slower (an RTL-SDR at 2.4 is what
dump1090 uses); a Hermes-Lite 2 cannot (`409 rate_too_low`). The reopen
closes and opens the device under the same broker claim, takes a second
or two, and ends a recording in progress; when the session ends the radio
is reopened at the operator's own `sampleRate`, which is never changed.
A device the driver has not yet given back (an RSP the SDRplay service is
still releasing) is asked for again after 0.5, 1, 2, 4 and 8 s before the
reopen fails. The POST answers only when the device itself is at 1090 MHz
at the session's rate and its samples are from there, and `deviceStatus`
in `api/state` already says so. `rateHz` in the session view says the
rate it runs at. A recording started while ADS-B holds the receiver
(`POST api/recordings/start {"kind": "iq"}`) is at that rate and centre,
and is named and described as ADS-B, not by the operator's mode from
before: `...-1090.000MHz-ADS-B`, `core:description` "1090.000000 MHz
ADS-B", `openhamshack:receive.mode` "ads-b", and `openhamshack:service`
`{"kind": "adsb", "mode": "ADS-B", "freqHz"}` (never
`openhamshack:broadcast`, which is DAB's and wide FM's). An AIS session's
recordings likewise say AIS. At 6 MS/s an IQ recording is 24 MB/s.

Every answer of the session routes is the session view (also `adsb` in
`api/state` and `api/status`, and `session` items on the feed). It is
always there in Radio, idle or not: after the radio stops it says
`"state": "idle", "why": "radio_stopped"`; `GET api/adsb/session` answers
it whether the radio runs or not:

```json
{"state": "running", "why": null, "text": "Listening to ADS-B on 1090 MHz",
 "clients": 1, "startedAt": "2026-10-28T09:20:31Z", "endsInS": null,
 "centreHz": 1090000000.0, "rateHz": 6000000.0, "leaseS": 30.0, "lingerS": 0.0,
 "aircraft": 6, "rev": 412, "messages": 1525, "df17": 1135, "aircraftSeen": 6}
```

- `state`, `why`, `text`, `clients`, `endsInS` as AIS's. `messages`: Mode
  S messages that passed their parity this session (`df17` of them
  extended squitters); `aircraftSeen`: aircraft that came onto the map.
- **Refusals** as AIS's (`400 bad_client`, `409 span_pinned` with
  `sessions` and `dropSessions`, `409 receiver_busy`, `409 on_air`, `409
  decoder_unavailable`, `429 too_many_clients`, `503 not_running` "Start
  the radio to see aircraft"), and `409 rate_too_low` (this receiver
  cannot run at 2.4 MS/s) and `503 device_error` (the receiver would not
  open at the faster rate; it is back at the operator's rate). Every one
  is refused before the radio is reopened. A view-level client may read
  the table but not start ADS-B.
- **Gain and notches:** the operator's gain stands unless the receiver
  reports overload (as AIS); both RSP notches are out while ADS-B runs,
  whatever their settings (`notches.*.why: "adsb"`).

**What is shown.** An aircraft appears only once the decoder believes in
it: an address confirmed by two extended squitters whose parity is
exact, a position from an even/odd pair that the next position confirms,
within 500 km of the station (the station profile's locator), and nothing
impossible (over 1000 kn, an impossible jump). Expect the first aircraft
a few seconds after the map opens, not the first second. Real air sends
far more noise than aircraft through any decoder; this is why nothing
invented appears.

**The aircraft.** `GET api/adsb/aircraft` (view):

```json
{"rev": 412, "full": true, "removed": [], "keepMinutes": 5,
 "station": {"locator": "IO75RL", "lat": 55.479, "lon": -4.542},
 "session": {...the session view...},
 "aircraft": [{"icao": "F00202", "source": "adsb", "callsign": "SIM202",
               "category": "A5", "categoryText": "Heavy aircraft",
               "squawk": "4521", "emergency": "none", "emergencyText": null,
               "lat": 55.47402, "lon": -4.34406, "positionAt": "2026-10-28T09:21:04Z",
               "altBaro": 37000, "altGeo": 37175, "groundSpeed": 459.8, "track": 286.4,
               "heading": null, "airspeed": null, "airspeedType": null,
               "verticalRate": 0, "verticalRateSource": "baro", "onGround": false,
               "adsbVersion": 2, "distanceKm": 12.47, "bearingDeg": 92.5,
               "lastHeard": "2026-10-28T09:21:04Z", "lastHeardTs": 1793178064.4,
               "firstHeard": "2026-10-28T09:20:35Z", "messages": 37, "rssiDb": -35.8,
               "rev": 410,
               "route": {"from": "GLA", "to": "LGW", "fromName": "Glasgow", "toName": "London Gatwick",
                         "fromIcao": "EGPF", "toIcao": "EGKK", "source": "adsbdb"}}]}
```

- One entry per ICAO address (six hex digits; a `~` first for an
  anonymous or TIS-B address), **nearest first**. A field is `null` until
  heard: an aircraft's callsign comes every five seconds or so, so it may
  appear first as its address.
- Units: degrees (`lat` north, `lon` east), feet (`altBaro`, barometric;
  `altGeo`, GNSS height), knots (`groundSpeed`, `airspeed`), degrees true
  (`track`, over the ground; `heading`, where the aircraft points, sent
  with an air speed), feet a minute (`verticalRate`, `verticalRateSource`
  `baro` or `geo`). `airspeedType`: `ias` or `tas`. `onGround`: from
  surface positions and the replies' flight status.
- `category`: DO-260B's emitter category ("A1" light ... "A5" heavy, "A7"
  rotorcraft, "B1" glider, "C1" emergency vehicle on the ground, ...;
  `categoryText` in the server's language) - for the symbol.
- `squawk`: the Mode A code. `emergency`: `none`, `general`, `lifeguard`,
  `minfuel`, `nordo`, `unlawful`, `downed` - from the aircraft's own
  emergency report or its squawk (7500, 7600, 7700); `emergencyText` in
  words, `null` for none. **Show an emergency unmistakably.**
- `source`: `adsb`, `adsr` (rebroadcast) or `tisb` (radar, rebroadcast).
- `rssiDb`: its signal, dB full scale; `messages`: how many it has sent us.
- `distanceKm`, `bearingDeg` as AIS's.
- An aircraft not heard for `adsbKeepMinutes` (a setting, 1-60, default
  5) is dropped. **The table is not kept over a restart**, unlike the
  vessels': aircraft move on in minutes.
- **Flight routes.** `route`: `{"from", "to", "fromName", "toName",
  "fromIcao", "toIcao", "source": "adsbdb"}`, or `null` while the route is
  unknown, not yet looked up, or the lookup failed. Code
  `ohsradio/flightroutes.py`; hooked into the table through
  `AircraftTable.route_lookup` (set by `Radio`), never fetched on a
  request thread. Radio asks adsbdb.com (free, no key) for each new
  callsign it hears, once, in a background thread at most once a second,
  and keeps the answer on disk for 7 days (an unknown callsign, 1 day; a
  failure, retried after 10 minutes); a callsign shaped like a
  registration (a hyphen, or a US N-number) is never asked, since adsbdb
  has no such entry. The `adsbRouteLookup` setting (`api/set`, Settings ›
  ADS-B; default `true`) turns the lookups off: offline, or with it off,
  every aircraft's `route` is `null`, as before this feature. What goes
  out: one GET per new callsign, saying only the callsign and
  "OpenHamShack-Radio" with its version.

**Keeping up** exactly as AIS: `GET api/adsb/aircraft?since=<rev>` answers
what changed after it (`aircraft`) and what was dropped (`removed`, ICAO
addresses), `full: false`. Live, `GET api/events?kinds=adsb` (not in the
default set) sends:

- `{"kind": "adsb", "type": "aircraft", "rev", "aircraft": {...as above}}`
  - an aircraft's whole entry, at most once a second each.
- `{"kind": "adsb", "type": "removed", "rev", "icao"}` - dropped by age.
- `{"kind": "adsb", "type": "session", "session": {...}}`.

`GET api/adsb/aircraft/{icao}` (view): one aircraft as above plus
`track`, its recent positions oldest first, `[{"t", "lat", "lon",
"altBaro", "groundSpeed", "track"}]` - a point when it has moved 500 m or
10 s have passed, the last 240. `404 unknown_aircraft` when it is not in
the table; `400 bad_params` for something that is not an address.

**The map** is the same `api/map/*` as the ships' (below): draw aircraft
over it by `lat`/`lon`, rotated by `track`.

Simulator: Radio's simulator puts six fictional aircraft (addresses
F000xx, callsigns SIM...) around Glasgow Prestwick
(`ohsradio/devices/simadsb.py`): a jet on approach to runway 30, a heavy
overflying at FL370, a light aircraft in the circuit, a departure from
Glasgow climbing south-west, a helicopter over the Firth of Clyde, and an
aircraft taxiing on Prestwick's apron - real Mode S replies, keyed by
shack_sdr's transmitter, earned by the decoder like any aircraft. Open
the map with the radio on the simulator and they appear within seconds.

**Not done:** MLAT, ACARS and VDL2; Comm-B contents (an aircraft's
selected altitude, heading and so on, in DF20/21).

## APRS (Radio)

APRS stations on a map (29/10/2026). Radio decodes APRS on 144.800 MHz -
1200 baud AFSK on FM, the UK and European channel - **only while a client
has the APRS map open**, keeps a table of every station, object and item
heard and every message, and serves it. Code `ohsradio/aprs.py` (and
shack_packet's SDR monitor and APRS parser, vendored from ohs-libs);
tests `tests/test_ham_aprs.py`. **Receive only**: nothing here transmits,
digipeats or acknowledges a message, and there is no route that sends.

**The session** is AIS's, route for route: `POST api/aprs/session
{"client": "<id>"[, "dropSessions": true]}` (control) when the map opens and
again at least every `leaseS` seconds (30; every 10 s is right), `DELETE
api/aprs/session?client=<id>` when it closes, `DELETE api/aprs/session?all=1`
(control) to end it at once whoever has it open. It ends **at once** when
the last client goes (`lingerS` 0, CLIENT-UI-PLAN 7.3) and the receiver
goes back exactly as it was: dial, mode, repeater offset and centre. A
client with client presence and `"aprs"` in its holds renews the lease
through presence, and its presence going ends its share at once.

While it runs APRS **holds the receiver**: `rxOwner` is `{"by": "aprs",
"session": "aprs", "block": "APRS", "freqHz": 144800000, "prior": {...},
"text": "..."}`, the dial reads 144.800 MHz in FM, and the receiver's
centre is 144.825 MHz (`centreHz`), 25 kHz above the channel so its own
DC spike sits on no station. Nothing at the dial is demodulated (silence
plays): the channel is cut from the receiver's IQ. A tune or a key-up is
refused `409 receiver_busy`: "The receiver is listening to APRS on 144.800
MHz for the station map: close the map, or stop APRS, to tune or change
mode". Only one thing holds the receiver at a time, so APRS, AIS, ADS-B
and a DAB station refuse one another with the holder's sentence ("APRS
has the receiver for the station map: stop APRS first"). The operator's
gain stands, as on 2 m.

Every answer of the session routes is the session view (also `aprs` in
`api/state` and `api/status`, and `session` items on the feed):

```json
{"state": "running", "why": null, "text": "Listening to APRS on 144.800 MHz",
 "clients": 1, "startedAt": "2026-10-29T06:20:31Z", "endsInS": null,
 "freqHz": 144800000.0, "centreHz": 144825000.0, "leaseS": 30.0, "lingerS": 0.0, "keepS": 86400.0,
 "stations": 6, "rev": 412, "frames": 73, "packets": 73, "dropped": 0}
```

- `state`, `why`, `text`, `endsInS`, `clients` as AIS's; `why` (idle)
  `idle` (nobody had the map open), `stopped`, `radio_stopped`, `lost`.
  `frames`: AX.25 frames decoded this session (good FCS); `packets`: those
  that were APRS; `dropped`: receiver blocks the decoder could not keep up
  with (a busy controller; each loses up to a block of air).
- **Refusals** (`{"error", "code"}`): `400 bad_client`; `409 span_pinned`
  with `sessions` (again with `"dropSessions": true` to stop them); `409
  receiver_busy` (DAB, AIS or ADS-B has the receiver); `409 on_air`
  (transmitting, or automatic transmit armed); `409 decoder_unavailable`
  (no shack_packet); `409 rate_too_low` (a receiver below 96 kS/s); `429
  too_many_clients` (32); `503 not_running`. A view-level client (`403
  level_too_low`) cannot start APRS but may read the table.

**The stations.** `GET api/aprs/stations` (view):

```json
{"rev": 412, "full": true, "removed": [], "session": {...the session view...},
 "stations": [{"call": "GM0SIM-9", "kind": "mobile", "symbol": {"table": "/", "code": ">"},
               "lat": 55.4705, "lon": -4.612667, "courseDeg": 12.0, "speedKmh": 55.6, "altM": null,
               "comment": "]On the A77", "status": "", "lastHeard": "2026-10-29T06:21:04Z",
               "lastHeardTs": 1793254864.0, "firstHeard": "2026-10-29T06:20:33Z",
               "heardDirect": false, "via": ["MB7SIM*", "WIDE2-1"], "packets": 14, "source": "rf",
               "wx": null, "rev": 410},
              {"call": "GM2SIM-13", "kind": "wx", "symbol": {"table": "/", "code": "_"},
               "lat": 55.509, "lon": -4.594, "courseDeg": null, "speedKmh": null, "altM": null,
               "comment": "Prestwick WX", "status": "", "heardDirect": true, "via": ["WIDE1-1"],
               "wx": {"tempC": 11.1, "humidity": 82.0, "pressureHpa": 1004.2, "windDirDeg": 230.0,
                      "windKmh": 27.8, "gustKmh": 40.2, "rain1hMm": 0.5}, "...": "..."},
              {"call": "AYRSHOW", "kind": "object", "owner": "GM0SIM", "...": "..."}]}
```

- One entry per callsign with SSID (`call`), and per name for an object or
  item (`owner` is the station that placed it), **most recently heard
  first**. Merged from every packet: positions (plain, compressed,
  ambiguous - the middle of the square - and Mic-E), status, weather,
  objects and items. A station heard only sending messages or status has
  `lat`/`lon` `null`: list it, but it has no place on the map. A killed
  object or item is removed (`removed`, and a `removed` feed item).
- `kind`: `object` or `item` (from the packet); else from the last
  position's symbol: `wx` (a weather station, or weather heard), `igate`
  (symbol code `&`), `digi` (`#`), `mobile` (a vehicle, person, craft or
  aircraft symbol, or a reported speed), `station` (anything else).
  `symbol` is the APRS table (`/`, `\`, or an overlay character) and code,
  for a client's own icon set; `null` until a position has said it.
- Units: degrees (`lat` north, `lon` east), degrees true, km/h, metres
  (`altM`); `wx` in Celsius, %, hPa, degrees, km/h and millimetres in the
  last hour, each `null` until heard; `wx` itself is `null` for a station
  that has sent none. Times ISO 8601 UTC; `lastHeardTs` epoch seconds.
- `heardDirect`: whether its last packet was heard from its own
  transmitter rather than through a digipeater (`via` shows the path as
  sent, `*` on each digipeater that has repeated it). Draw a station heard
  only through a digipeater differently: it is not in direct range.
  `packets` counts packets, a digipeater's copy of one already heard within
  30 s not counted again (it may only turn `heardDirect` on). `source` is
  `"rf"`: everything here came off the air (Radio has no APRS-IS).
- **Kept 24 hours** (`keepS`), fixed rather than a setting, on the
  controller (`aprs/stations.json`): a restart keeps the map, and a map
  opened for the first time in a while shows what was heard today.

**Keeping up.** Every change bumps `rev`. Two filters, either or both:

- `?since=<rev>`: as AIS - only the stations changed after that rev, and
  the keys removed after it in `removed`, with `full: false`; `full: true`
  (the whole table) when it is too old or newer than the server's.
- `?sinceS=<seconds>`: only stations heard in the last that many seconds
  (`sinceS=3600`: the last hour). The TV contract names this parameter;
  it is read as seconds, as every `…S` field in this API is (`leaseS`,
  `endsInS`, `keepS`), not as a rev: a rev has its own parameter, `since`.

Live, `GET api/events?kinds=aprs` (WebSocket, not in the default set):

- `{"kind": "aprs", "type": "station", "rev", "station": {...as above}}` - a
  station, object or item heard (the whole entry).
- `{"kind": "aprs", "type": "removed", "rev", "call"}` - dropped after 24
  hours, or a killed object or item.
- `{"kind": "aprs", "type": "message", "message": {"t", "from", "to", "text", "id"}}`
  - a message or bulletin heard for the first time (a retry is not news).
- `{"kind": "aprs", "type": "packet", "t", "raw", "call", "aprs"}` - every
  frame decoded, in monitor form (`CALL>DEST,PATH:info`), `aprs` false for
  a frame that is not APRS: for a packet log.
- `{"kind": "aprs", "type": "session", "session": {...}}` as AIS's.

`GET api/aprs/stations/{call}` (view; `{call}` with its SSID, any case):
one entry as above plus `track`, `[{"t", "lat", "lon"}]` oldest first - a
point each time it has moved 25 m, the last 240 in 24 hours - and
`recent`, its last 20 packets `[{"t", "raw", "text"}]`, `raw` the monitor
line and `text` what it said (its status, message or comment). `404
unknown_station` when nothing by that name was heard in the last day.

`GET api/aprs/messages` (view): every message and bulletin heard in the
last 24 hours, oldest first, `[{"t", "from", "to", "text", "id"}]` (`id`
the sender's message number, `null` for none; a bulletin is to `BLN…`).
Read only, whoever it is addressed to: Radio never acknowledges or answers
one, so a station sending to this one's call sees no ack.

Simulator: Radio's simulator puts fictional stations around Ayr on
144.800 (`ohsradio/devices/simaprs.py`, every call ending `SIM`): a
digipeater (MB7SIM), a home station with a status line, an object (the
Ayr show's talk-in) and a message to GM4BRI (GM0SIM), a Mic-E car on the
A77 heard direct and through the digipeater in turn (GM0SIM-9), a walker
on the shore (GM1SIM-7) and a weather station at Prestwick (GM2SIM-13).
Each packet is real AFSK from shack_packet's own modulator on FM, decoded
exactly as off the air; one a second, round them in turn, so the map fills
within a quarter of a minute.
## Weather satellites (Radio)

Meteor-M LRPT passes, predicted and recorded by themselves (Brian,
29/10/2026). This is the first half of the feature: prediction, a plan for
each pass, and an IQ recording of each pass recorded. Decoding the
pictures comes later; until then `api/wxsat/images` is always `[]` and
nothing sets the `decoding` plan. Code `ohsradio/wxsat.py` (passes, plans,
recording), `wxsat_orbit.py` (SGP4, the vendored `sgp4` wheel),
`wxsat_tle.py` (element sets); tests `tests/test_ham_wxsat.py`. Receive
only: nothing here keys.

| Satellite | id (settings) | Frequency | Mode |
|---|---|---|---|
| Meteor-M N2-3 (NORAD 57166) | `meteor-m2-3` | 137.100 MHz | LRPT |
| Meteor-M N2-4 (NORAD 59051) | `meteor-m2-4` | 137.900 MHz | LRPT |

(WMO OSCAR, 29/10/2026. N2-4 moved between the two while it was
commissioned in 2024; a move is one line in `wxsat.SATELLITES`.)

**The station** is the `locator` setting (the station profile's), the
centre of its square on the WGS-84 ellipsoid at height 0. Without a
locator there are no passes.

### GET api/wxsat/passes[?hours=48] (view)

The passes in the sky at any time from an hour ago to `hours` ahead (1-72;
`400 bad_params` outside), in order of AOS:

```json
{"station": {"lat": 55.47917, "lon": -4.54167},
 "tle": {"source": "celestrak", "fetchedUtc": "2026-10-29T05:30:00Z", "ageDays": 0.68, "stale": false},
 "minElevDeg": 15,
 "passes": [{"id": "meteor-m2-3-20261029T0919Z", "sat": "Meteor-M N2-3", "freqHz": 137100000, "mode": "LRPT",
             "aos": "2026-10-29T09:19:21Z", "tca": "2026-10-29T09:26:53Z", "los": "2026-10-29T09:34:20Z",
             "maxElDeg": 41.9, "aosAzDeg": 19.0, "losAzDeg": 175.5,
             "track": [{"t": "2026-10-29T09:19:21Z", "az": 19.0, "el": 0.0}, "...every 10 s, LOS last..."],
             "plan": "record", "why": null, "imageId": null}]}
```

- Times are ISO 8601 UTC. AOS and LOS are the horizon (0°), whatever the
  minimum: a pass is recorded horizon to horizon. `id` is the satellite's
  id and its AOS to the minute; a newer element set moving AOS by a few
  seconds keeps the plan a client gave it.
- `plan` and `why` (`why` is a translated sentence, or null):
  - `record` - it will be recorded: automatic recording on, the satellite
    enabled, `maxElDeg` at least `minElevDeg`; or a client forced it.
  - `skip-low` - it never rises to `minElevDeg`.
  - `skip-disabled` - the satellite is switched off, automatic recording
    is off, or a client skipped this pass; `why` says which. (The agreed
    plans have no plain "skip", so a skip by hand is this one.)
  - `skip-busy` - at AOS a person was using the receiver: a DAB station
    playing, the AIS or ADS-B map open, or someone listening. Left alone;
    only `POST .../record` takes it from them.
  - `skip-conflict` - at AOS the receiver was held by something a pass
    never preempts: transmitting, the transmit lease or automatic transmit,
    an IQ or audio recording, a recording playing, the band scan,
    background decoder sessions, the CW skimmer, another pass.
  - `recording`, then `done` or `failed` (`why` says what went wrong).
  - `missed` - it was to be recorded and Radio was not running then.
  - `decoding` - reserved for the decoder.
- `imageId` is null until the decoder exists.
- `tle`: where the element sets come from and how old they are (below).

### GET api/wxsat/status (view)

```json
{"state": "recording", "passId": "meteor-m2-3-20261029T0919Z", "sat": "Meteor-M N2-3", "freqHz": 137100000,
 "az": 104.2, "el": 38.7, "snrDb": null, "lockPct": null, "lines": null, "etaS": 412,
 "text": "Recording Meteor-M N2-3 until 09:34 UTC"}
```

`state`: `idle` (nothing to record), `waiting` (the next pass to record:
its id, where the satellite is now, `etaS` to its AOS), `recording` (the
pass, the satellite's position now, `etaS` to LOS); `decoding` is the
decoder's. `snrDb`, `lockPct` and `lines` are the decoder's and null for
now. `text` says it in a sentence (also why there are no passes: no
locator, or no `sgp4`).

### POST api/wxsat/passes/{id}/record (control)

Force the pass: recorded whatever its plan. One already in the sky starts
at once. If the receiver is held only by client-scoped holds - a DAB
station, a listened decoder session, the AIS or ADS-B map - they are ended
first, the same ending a client's leaving gets ("Client presence" above:
the server's `end_client_holds`, beside `client_gone`), whoever made them;
streams stay open and hear silence while the pass records. Answers `200`
with the pass (`plan` `record`, or `recording` when it started).
Refusals, `{"error", "code", "why"}` (`why` is the sentence again):
`404 unknown_pass`; `409 pass_over`; `409 receiver_busy` - a recording, the
band scan, background decoders, the CW skimmer or another pass has the
receiver; `409 on_air` - transmitting, the transmit lease or automatic
transmit armed. None of those is ever preempted.

### DELETE api/wxsat/passes/{id}/record (control)

Skip the pass: `plan` becomes `skip-disabled` ("Skipped by hand"). One
being recorded stops now and the receiver goes back as it was; nothing
else is touched. `200` with the pass, `404 unknown_pass`. A later `POST`
un-skips it.

### GET api/wxsat/images (view)

`[]`, always, until the decoder exists.

### Recording

A pass **holds the receiver** as AIS does: from AOS to LOS `rxOwner` is
`{"by": "wxsat", "session": "wxsat", "block": "Meteor-M N2-3", "freqHz":
137100000, ...}`, the dial is on the satellite's nominal frequency, nothing
at the dial is demodulated, and a tune or key-up is refused `409
receiver_busy` with "The receiver is recording a Meteor-M N2-3 pass: skip
the pass to tune or change mode". It changes the antenna to the pass's
(`wxsatAntenna`, else the input whose label says 2 m - "2 m", "VHF", "dual
band", a Diamond X-series model - else the operator's own). At LOS, not
before, the dial, mode, repeater offset and antenna from before are put
back. The radio is not given back to the station (presence's park) while
a pass records or is about to rise, and a parked radio is taken back for
one.

**The file** is the engine's IQ recording format ("Recordings" above):
SigMF, `ci16_le` (complex int16, "cs16" in SoapySDR's words), in Radio's
recordings folder, so it is listed by `api/recordings` like any other,
named `openhamshack-radio-<UTC start>-137.100MHz-Meteor-M-N2-3-LRPT`.
`core:frequency` is the satellite's nominal frequency, at 0 Hz in the
file: the device's samples are shifted there (the hardware need not sit
exactly on it) and **decimated by the whole number that brings the rate
to 1 MS/s or below** - 800 kS/s from the RSPdx's 2.4 MS/s, 1 MS/s from a
2 MS/s device. The rate is `core:sample_rate`; read it rather than
assuming 1 MS/s. **No Doppler correction**: the satellite drifts +-3.4 kHz
across the pass, well inside the recording, and following it is the
decoder's job. The global metadata is the engine's (`openhamshack:device`,
gain, the app and station), `openhamshack:service` names the satellite
(`{"kind": "wxsat", "mode": "LRPT", "label", "freqHz", "norad", "passId"}`),
and `openhamshack:wxsat` carries what a decoder needs: `passId`,
`satellite`, `norad`, `nominalHz`, `aos`, `tca`, `los`, `maxElDeg`, `tle`
(the three lines it was predicted from), `tleSource`, `deviceRate`,
`decimation`, `antenna`, `forced`. A pass is 10-15 minutes, about 3 GB
at 800 kS/s, and it obeys the same disk rules as every recording
("Recordings": `RECORDINGS_LIMIT_GB`, the free-space floor, the oldest
pruned first): with the 10 GB default about three passes are kept. One
that does not fit is cut short and ends `failed`, saying the disk limit
stopped it; no room at all is `failed` at AOS.

### Element sets (TLE)

Each satellite takes the first source that has it:

1. **`operator`** - the `wxsatTle` setting: two-line element sets, lines
   separated by `|` (a setting cannot hold a line break), matched by the
   NORAD number in the lines, never by the name.
2. **`celestrak`** - Celestrak's GP data for the weather group, one GET a
   day of `https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle`
   in the background while `wxsatOnlineTle` is on, saying only
   "OpenHamShack-Radio/<version>". Kept in the data folder
   (`wxsat/celestrak.txt`) and used offline. A failure is silent: backoff
   from an hour doubling to a day, one log line per cause.
3. **`bundled`** - `ohsradio/data/wxsat/tle.txt`, shipped with Radio, so a
   station never online still predicts. Between the cache and the bundle
   the newer epoch wins.

`tle.source` is the operator's if any set in use is theirs, else
`celestrak` if any is, else `bundled`. **`ageDays` is measured from the
element sets' epoch** (the oldest in use), not from when they were
fetched: accuracy decays from the epoch, Celestrak may serve a set days
old, and a pasted set has no fetch time. **`stale` is true past 14 days.**
`fetchedUtc` is when the source in use was fetched (Celestrak: the fetch;
the bundle: the date it was made; the operator's: null).

### Settings

| Setting | Default | |
|---|---|---|
| `wxsatAuto` | `true` | record passes by themselves; off, every pass is `skip-disabled` unless forced |
| `wxsatMinElevDeg` | `15` | 0-90°: lower passes are `skip-low` |
| `wxsatSatellites` | `"meteor-m2-3,meteor-m2-4"` | the satellites wanted, comma-separated ids; one left out is `skip-disabled` |
| `wxsatAntenna` | `""` | the input to record on, by its name or the operator's label; empty: the 2 m one by its label |
| `wxsatOnlineTle` | `true` | fetch Celestrak's element sets once a day |
| `wxsatTle` | `""` | the operator's own element sets (lines separated by `\|`) |

All are control level, set with `api/set`.

## Map (Radio)

What to draw the ships and aircraft on: **land that is always there**, bundled with
Radio, and **OpenStreetMap's map** when the controller has internet,
fetched and cached by Radio and served through its own route - the client
never touches the internet. Code `ohsradio/mapdata.py`; data
`ohsradio/data/mapland` (made by `tools/mapland-build.py`); tests
`tests/test_ham_map.py`.

`GET api/map/info` (view):

```json
{"bounds": [-11.0, 49.0, 2.5, 61.0],
 "land": {"source": "osm-land-polygons", "date": "2026-10-28", "licence": "ODbL-1.0",
          "bounds": [-11.0, 49.0, 2.5, 61.0],
          "levels": {"fine": {"toleranceDeg": 0.0002, "cellDeg": 0.5, "maxSpanDeg": 2.5},
                     "coarse": {"toleranceDeg": 0.005, "cellDeg": 2.0, "maxSpanDeg": 360.0}}},
 "attribution": [{"text": "© OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright"}],
 "tiles": {"enabled": true, "online": true, "cached": 120, "cachedMb": 2.1, "capMb": 200,
           "backoffS": 0, "lastError": null, "url": "api/map/tiles/{z}/{x}/{y}.png",
           "minZoom": 0, "maxZoom": 18, "size": 256,
           "attribution": {"text": "© OpenStreetMap contributors", "url": "..."}},
 "station": {"locator": "IO75RL", "lat": 55.479, "lon": -4.542}}
```

- **Attribution:** draw `attribution[0].text` on the map whenever it
  shows (bottom right, never hidden behind a control): the land and the
  tiles are both OpenStreetMap's, and its licence asks for that.
- `bounds`: where the bundled land covers (Great Britain, Ireland, the
  Isle of Man, the Channel Islands, Orkney and Shetland, and the near
  coast of France). Outside it the land map is empty sea.
- `land` is `null` if the install has no land data (draw the grid alone).
- `tiles.enabled`: the `mapOnlineTiles` setting (default on). `online`:
  tiles may be fetched now (the setting on and Radio not backing off after
  a failed fetch). Neither promises a given tile: always be ready for 404.

`GET api/map/land?bbox=west,south,east,north[&detail=auto|fine|coarse][&format=geojson|compact]`
(view; degrees; no bbox is the whole of `bounds`):

- **GeoJSON** (default, `application/geo+json`): a `FeatureCollection`
  with `detail` (the level used) and `attribution`, and one `Feature`
  whose geometry is a `MultiPolygon` of every land polygon in the cells the
  box touches - more than the box, never less; clip as you draw. Rings
  are closed, `[lon, lat]`, 4 decimals.
- **Compact** (`format=compact`, `application/json`): `{"detail", "scale":
  0.0001, "attribution", "polygons": [[ring, ...], ...]}`, each polygon a
  list of rings (the outline, then holes), each ring a flat list of
  integers: the first point whole, the rest as differences from the point
  before, `[lon0, lat0, dlon1, dlat1, ...]`, in units of `scale` degrees.
  About a third of GeoJSON's size and quicker to parse on a TV.
- `detail=auto` gives `fine` (about 20 m) for a box up to `maxSpanDeg`
  (2.5) degrees across and `coarse` (about 500 m) beyond; `fine` for a
  box over 10 degrees is answered `coarse`. The Firth of Clyde at fine
  detail is about 25,000 points.
- **Fill the polygons; never stroke them.** The data is cut into cells,
  and a stroke would draw the cut lines; the coastline is the land's
  edge against the sea colour.
- With `Accept-Encoding: gzip` the answer is gzipped. It changes only
  when Radio is updated: `Cache-Control: max-age=86400`; cache it by box.
- `400 bad_params` for a box that is not west<east, south<north inside
  the world, or an unknown detail or format.

`GET api/map/tiles/{z}/{x}/{y}.png` (view): the standard OpenStreetMap
256-pixel tile (Web Mercator, the slippy-map numbering), `image/png` with
`Cache-Control: max-age=<how long it stays fresh>`, or `404 no_tile` when
there is none to give - offline, the setting off, not yet fetched and the
fetch failed, beyond zoom 18 - and the client **draws the bundled land
for that square instead**. A tile Radio has not got is fetched while the
request waits (up to 4 s), so with internet the first look succeeds.

How a client should use tiles (the OSM tile policy is Radio's to keep,
and it keeps it only if the clients ask sensibly):

- Ask only for the tiles **in view**: no margin, no other zoom levels
  ahead, no "download this area". Radio fetches exactly what is asked and
  nothing more (bulk and offline downloading are forbidden by the policy).
- Draw the land first, then the tiles over it as they arrive, so a
  missing tile shows land, not a hole; after a 404, ask for that tile
  again only when the view changes or after a minute.
- Keep a tile for its `max-age`.

What Radio does (for reference): one User-Agent, "OpenHamShack-Radio/<version>
(+https://openhamshack.com)", and nothing about the station; the caching
headers honoured (fresh for max-age less Age, at least a day;
stale-while-revalidate and stale-if-error; conditional revalidation); two
fetches at a time; a backoff from one minute to an hour after a failure,
so offline costs one request a minute, not one a tile; at most
`mapTileCacheMb` (default 200) of tiles, the least recently shown going
first. Settings: `mapOnlineTiles` (off: no traffic at all and no tile,
cached or not) and `mapTileCacheMb`.

## ui/1 screens (Radio)

Radio's TV screens as server-driven ui/1 documents (openhamshack
`docs/CLIENT-UI-PLAN.md` §5-6, step 1b), which the OpenHamShack client
draws natively; a new panel then needs no client release. Built with
ohs-libs `shack_ui` (pinned in `tools/vendor`), which checks every
document against ohs-libs `spec/schemas/ui.schema.json` as it is served,
so a screen that would break a client, or that has an action declaring
`transmit`, is never sent. Code `ohsradio/screens.py`,
`ohscore/server/uiv1.py`; tests `tests/test_ham_screens.py`; what each
screen replaces on the Android TV, and what it leaves out,
`docs/UI-PARITY-RADIO.md`. Receive only: every action is an existing
route at its existing level, and no screen places `ptt` or `enableTx`.

**Requests.** The client sends `X-OpenHamShack-UI: 1.0` and
`X-OpenHamShack-Components: waterfall/1, map.ais/1, audio/1, ...` (a
native component, or one of its layers after a dot, and the newest
version it draws). A native component the list lacks is left out and its
fallback sent in its place; with no header at all (a browser, curl) every
native component goes out with its fallback beside it. A client whose
`X-OpenHamShack-UI` has another major version gets `406 {"code":
"ui_unsupported", "ui": ["1.0"]}`. Each answer carries `ETag` (the
document's `rev`, a hash of its content) and `Cache-Control: no-cache`;
`If-None-Match` with it answers `304`. Every path in a document is
relative to the app's base (`api/set`, never `/api/set`), whatever
`X-Forwarded-Prefix` says; documents are not given `url`s beside their
paths, as other answers are.

**`GET ui/v1/app`**:

```json
{"ui": "1.0", "app": "shack-radio", "kind": "radio", "name": "Radio", "version": "0.1.22",
 "icon": null, "minClient": "1.0", "spectrum": 1, "overlay": 1,
 "screens": ["radio/home", "radio/dab", "radio/fm", "radio/ships"],
 "data": {"status": {"src": "get:api/status", "poll": 15}},
 "status": {"text": {"bind": "status.dialLabel.text"}, "onAir": {"bind": "status.onAir"},
            "running": {"bind": "status.running"}},
 "entries": [{"id": "radio", "title": "Radio", "screen": "radio/home", "icon": "radio",
              "status": {"text": {"bind": "status.dialLabel.text"}, "onAir": {"bind": "status.onAir"}}},
             {"id": "dab", "title": "DAB Radio", "screen": "radio/dab", "icon": "dab", "status": {...}},
             {"id": "fm", "title": "FM", "screen": "radio/fm", "icon": "fm", "status": {...}},
             {"id": "ships", "title": "Ships", "screen": "radio/ships", "icon": "ships", "status": {...}}]}
```

`entries` are the launcher's tiles in that order (§6.2); each `status`
binds into `data` (`api/status`, every 15 s): DAB's text is
`rxOwner.text`, Ships' `ais.text`. `icon` is null until Radio serves a PNG
of its own; an entry's `icon` names one the client has. No Aircraft entry
until there is an ADS-B screen.

**The screens.** Each binds `state` (`ws:api/events?kinds=state`, the
merged state diffs) and, where it shows a meter or the stereo flag,
`meter` (`ws:api/events?kinds=meter`).

| Screen | Binds | Does (method, path, body; level) |
|---|---|---|
| `radio/home` | the dial (`state.vfo`, `freq`), mode, `dialLabel.text`, RDS `ps`/`rt`, the signal (`meter.rx`, `db`), `rxOwner.text` (who has the receiver), `error`; native `waterfall` (`stream` main, the band, dial, channels, beacons, stations and sessions layers) and `audio` (`api/audio/rx`) | Frequency: `POST api/set {"changes": {"vfo": $value}}`; Mode (a choice of `state.MODES`): `{"changes": {"mode": $value}}`; Band down/up: `POST api/shack/pad/action {"action": "band", "kind": "turn", "step": -1\|1}`; Volume: `POST api/set {"volume": $value}`; Start the radio: `POST api/start` (all control); Mute: the `audio.mute` native verb; opens `radio/dab`, `radio/fm`, `radio/ships` |
| `radio/dab` | `dab` (`get:ui/v1/data/dab`, every second): title, programme text, slide or logo, detail ("DAB+ · 64 kb/s · Varied"), ensemble, `whyText`, transmitters heard; `state.bandScan.text`; native `audio` | A tile per service of `api/dab/stations`, by ensemble: `POST api/decoders/sessions {"decoder": "dab", "freqHz", "params": {"block", "service"}, "replace": true}`; Stop: `{"decoder": "dab", "stop": true}` ("DAB" above: neither needs the session id); Scan now: `POST api/scan {"band": "dab"}`; Volume (all control); Mute |
| `radio/fm` | RDS `ps`, `rt`, `ptyName`, `tp`; the dial; `meter.stereo`; `rxOwner.text`; `state.bandScan.text`; native `audio` | A tile per station of `api/fm/stations`, by frequency and A-Z (`tabs`): `POST api/set {"changes": {"vfo": best.hz, "mode": "wfm"}}`; Tune by frequency: the same with `$value`; Scan now: `POST api/scan {"band": "fm"}`; Volume (all control); Mute |
| `radio/ships` | `ais` (`get:api/ais/vessels`, every 10 s): `session.text` and the nearest ships, a row each bound by index (`ais.vessels.0.name`, `shipTypeText`, `distanceKm`), as many as the table held when the screen opened (at most 12); `rxOwner.text`; native `map` with layer `ais` | The map component, as the TV's map does today: `POST api/ais/session {"client"}` every 10 s while it shows and `DELETE api/ais/session?client=` when it closes (control), `api/map/info`, `api/map/land`, `api/map/tiles/{z}/{x}/{y}.png`, `api/ais/vessels[/{mmsi}]`, `api/events?kinds=ais` (view); its props name each path. A row selects its ship on the map: `local` `map.ais.selected` with the row's `mmsi` binding |

A screen is built when it is asked for: the station lists are as the last
scan left them, so a client asks again after a `stations` event or a
change of `stationsAt` (or simply on opening the screen).

**`GET ui/v1/data/dab`** (view): what the DAB screen binds to, from the
DAB session playing (whose own view, `GET api/decoders/sessions/{id}`,
needs its id):

```json
{"playing": true, "session": "ds_3f2a", "block": "11D", "service": "C221", "title": "Shack MP2 Tone",
 "dls": "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right", "detail": "DAB · 128 kb/s · Pop music",
 "ensemble": "Shack Test Mux · 11D", "imagePath": "api/dab/slides/C221?rev=7",
 "imageUrl": "/apps/radio/api/dab/slides/C221?rev=7", "why": null, "whyText": "",
 "transmitters": [...as in the session's meta...],
 "transmittersText": "Crystal Palace, 4 km, 0 dB\nWrotham, 31 km, -8.5 dB"}
```

`service` is the station asked for, so a change shows at once; `dls`
follows when the decoder has it. `imagePath` is the station's latest
slide, else its logo, else null. `transmittersText` is one line per
transmitter, worded here because ui/1 has no repeated row to fill from a
list. While nothing plays: `playing` false, `title` "Not playing", the
rest null or empty.

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
  **Since 23/10/2026 the image carries neither SDRplay's API nor
  SoapySDRPlay3** (SoapySDRPlay3 is built against SDRplay's headers, which
  come only in its installer): the API and its service are the
  controller's host library `sdrplay-api` ("Host libraries" above), and
  `device` soapy with `driver=sdrplay` opens the RSP through shack_sdr's
  own binding to that API instead, with nothing in the station's settings
  changed: `serial=` picks the RSP, `rfgain_sel=` is the LNA state, and
  the antenna names are SoapySDRPlay3's. `deviceStatus` then has `"via":
  "sdrplay-api"`. `rxGain` keeps SoapySDRPlay3's meaning on this path
  (since 0.1.22-beta.3's fix): the same gRdB and LNA state for the same
  settings, and `deviceStatus` `gain` is SoapySDR's overall figure, with
  `gRdB` and `lnaState` beside it. Since shack_sdr's SDRplay source opens
  the RSP exactly as SoapySDRPlay3 does (ohs-libs shack_sdr README
  "SDRplay: parity with SoapySDRPlay3"), `deviceStatus` also carries three
  counters for telling a hot signal from a starved one: `overloads` (the
  API's power-overload events, now acknowledged and so corrected, where
  they were silently ignored before 23/10/2026) and `apiGaps`/`apiLost`
  (packets the API's callback dropped before shack_sdr read them, counted
  from its own sample numbering - never 0 only because nothing arrived).
  Where SoapySDR does have an SDRplay module (a desktop
  with SoapySDRPlay3, an image built with `SHACK_STORE_DROP_SDRPLAY=0`),
  SoapySDR opens it as before.
- Radio's other receive-only receivers go through shack_sdr's own
  bindings, not SoapySDR (RADIO-SDR-PLAN §6): `device` rtlsdr is the
  broker's `rtlsdr-1` (an RTL-SDR, 0bda:2838; the image carries Debian's
  librtlsdr0) and `device` sdrplay the same RSP as soapy, `sdrplay-1`,
  through SDRplay's API directly. The claim's USB serial becomes
  `sdrSerial` (a platform key, like soapyArgs). `rtlsdr` has one input,
  "RX"; `sdrplay`'s inputs depend on the RSP model (SoapySDRPlay3's own
  names - "Antenna A/B/C", "Hi-Z", "Tuner 1/2 ..."), both reported and
  switched through `soapyAntenna` exactly as the soapy path above is.
  `device` sdrplay's `deviceStatus` carries the same `overloads`/`apiGaps`/
  `apiLost` counters as the soapy path above - the same source, just with
  its own (not SoapySDRPlay3's) gain sense.
  `device` libresdr is the broker's `libresdr-1`, opened by the Pluto
  driver at the address the claim gives (`plutoUri`). The image starts
  SDRplay's service from `/opt/hostlibs/sdrplay-api/`; without the host
  library the RSP says "Ask your controller's administrator to install
  SDRplay's API (Controller › Optional libraries) to use this radio", and
  on a controller too old for host libraries "Update the controller to use
  SDRplay radios and DAB+".
- Hermes-Lite 2 discovery uses a LAN broadcast the container's network may
  not pass; give its address in the broker's device instead.
