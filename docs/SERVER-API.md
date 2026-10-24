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
| `GET api/status` | view | the app and radio at a glance: `app`, `kind`, `name`, `version`, `running`, `onAir`, `txError`, `txBlocked`, `tx.remote` (the lease; its presence says this server has it), `radioError`, `reconnecting` (true while a claim the broker lost is being taken back; `radioError` then says "Reconnecting to the station…"), `autoTx` (below), `device`, `mode`, `vfo`, `txDial`, `simulator`, `broker`, `audio`, `station`, `sharedLog`, `recordings`, `decoders` (`{"available", "sessions", "cpuMax", "codecsMissing"}`: whether to show a Decoders view; `codecsMissing` is `null` until the first look, never a scan of its own), `rxOwner` (the decoder session holding the receiver, `{}` while the operator has it: "DAB" below), `span` (what the receiver covers and whether background decoder sessions pin it: "The pinned span" below; `{}` in QO-100 NB), `broadcastGain` (the receiver gain a DAB station or wide FM plays with in place of the operator's: "Broadcast gain" below; `{}` while none plays, and in QO-100 NB), `hostLibs` (on a controller, the host libraries it lends, `{}` elsewhere: "Host libraries" below) |
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
| `GET api/events?kinds=state,toast,meter,lock,events` | view | WebSocket: one JSON message per feed item, `{"kind": …, …item}`; first `{"kind": "hello", "status": …}`. `wide` and `zoom` only when asked: `{"kind", "t", "startHz", "binHz", "n", "cdb"}`, `cdb` the bins as little-endian int16 centi-dB in base64; a `wide` item may add `dcBins: [lo, hi]`, the bins (inclusive, into `cdb`) filled in over the receiver's DC spike (Radio: "The DC spike" below). A decode (`events`) that names a sender (`call`) also carries its DXCC entity when cty.dat can place it: `country` (cty.dat's name), `dxcc` (primary prefix), `continent`; absent otherwise. |
| `GET api/events` (state resync) | view | A `state` item is a diff, published once, and a client too slow to drain its queue loses the oldest. When that has happened the server sends the whole state before any later diff: a `state` message in the usual shape, `{"kind": "state", "changes": {…every key…}, "full": true}`. `full` is new and optional (absent on ordinary diffs); a client that merges `changes` as it always has needs no change, and one that wants to can replace its copy instead. Diffs it had not yet received are folded into the snapshot, not sent after it. Other kinds (meter, spectrum, events) still drop oldest-first. |
| `GET api/events?kinds=…,cwskim,cwspot` | view | Radio's CW skimmer (ENGINE-API `cwskim`, `cwspot`). Neither kind is in the default set, so a client that does not ask never gets them. `cwskim` comes once a second, at most `cwSkimMax` channels (about 8 kB/s at 64). `cwspot` is coalesced to at most 5 items a second. A slow client loses snapshots, which do no harm, and spots, which it recovers through `rev`. |
| `GET api/cwskim` | view | Radio only: `{"state", "why"?, "band", "segment", "cover", "channels", "carriers", "spotsRev", "spots": [...]}`. That is the `cwskim` item, plus every spot of the last 30 minutes (at most 500, newest first, each a `cwspot` `spot`). Fetch it when a view opens, and after a gap in `rev`. It is `{"state": "off", ...}` with empty lists while `cwSkim` is false. A tap on a spot or channel only tunes: one `POST api/set {"mode": "cw", "vfo": dial}` at Control level, never a reply and never Enable TX (Brian, 13/10/2026). |
| `GET api/decoders` and the routes under it | view, control | decoder sessions, below ("Decoders") |
| `GET api/events?kinds=…,decoder` | view | the decoder sessions' results, below |
| `GET api/fm/stations`, `GET api/dab/stations` | view | Radio only (404 `not_found` elsewhere): the station lists the weekly band scan made, below ("Station lists") |
| `POST api/scan` | control | Radio only: `{"band": "fm" \| "dab" \| "both"}` scans now; `202 {"bands", "progress"}`, or `400 bad_params`, `409 receiver_busy` / `unsupported` with the sentence, `503 not_running` |
| `GET api/events?kinds=…,stations` | view | Radio only: `{"kind": "stations", "band", "scannedAt", "count", "t"}` each time a scan has made a band's list anew; not in the default set |
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
| `GET api/local-frequencies?radiusKm=&category=` | view | Radio only: what there is to listen to near the station (below, "Local frequencies") |
| `POST api/local-frequencies/mine`, `PUT`/`DELETE api/local-frequencies/mine/{id}` | control | Radio only: the operator's own list ("my frequencies") |
| `POST api/local-frequencies/refresh` | control **and** the administrator flag | Radio only: download newer data (below) |

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
| `POST api/decoders/sessions` | control | `{"decoder": "rtty", "freqHz": 14083500, "params": {"baud": 45.45, "shift": 170, "reverse": false}}`. `201` with the session, or `400 bad_params`, `404 unknown_decoder`, `409 decoder_unavailable` (`needs` names a codec when that is why; a slot mode, which runs only as the mode, says so too), `409 outside_span` (in Radio: it, the other sessions and the dial cannot fit in one span), `409 receiver_busy` (DAB plays), `429 too_many_sessions` (`decodersMax`, default 4), `503 not_running`; for DAB also `409 span_pinned` (background sessions pin the span: `sessions` lists them; send `"dropSessions": true` to stop them and play), `409 receiver_busy`, `on_air`, `rate_too_low`, `out_of_range` (below). Sessions are kept in the settings and start again with the radio, except DAB's. |
| `DELETE api/decoders/sessions/{id}` | control | stop it: `{"stopped": true}`; `404 unknown_session` (the `vfo` session stops with its mode, never here) |
| `GET api/decoders/sessions/{id}?since=<rev>` | view | the session, with `results`: its kept results (the last 500 or 30 minutes) newer than `rev`. Fetch it after a gap in `rev`. `404 unknown_session`. |
| `POST api/decoders/sessions/{id}` | control | `{"params": {"service": "C3A7"}}`: change a running session's parameters live (DAB's station). `200` with the session; `400 bad_params` (a value the decoder refuses, or another DAB block), `404 unknown_session` |
| `POST api/decoders/codecs/rescan` | control | look for codecs again without a restart: `{"codecs": [...]}`; also looks at the controller's host libraries again (`hostLibs`) |
| `GET api/decoders/files` | view | the pictures decoders saved (SSTV's, whether a session's or the mode's), newest first: `{"files": [{"name", "session", "decoder", "t", "size"}...]}`. `t` is UTC seconds, `size` bytes; `session` and `decoder` are `""` for a picture saved before 23/10/2026. Answers with the radio stopped too. |
| `GET api/decoders/files/{name}[?download=1]` | view | one of them, `Content-Type: image/png`; `download=1` adds `Content-Disposition: attachment`. `404 no_file` for a name not in the list (a path or a dotted name included). |

A DAB session's sound replaces the demodulator's (below). Not yet:
`listen` for other sessions (M3).

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
  times that. `channels` is 2 when the mode was making stereo as the
  recording started (wide FM with its pilot, or DAB), else 1, and
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
- **Stopping** (`DELETE api/decoders/sessions/{id}`, `api/stop`, or the
  radio stopping) puts back the dial, mode and repeater offset from
  before (`prior`), and the receiver follows the dial again. A DAB session
  is never saved in `decoderSessions` and never starts again with the
  radio: a start that retuned to Band III by itself would lose the dial.

**Choose the station live:** `POST api/decoders/sessions/{id}
{"params": {"service": "C3A7"}}`. Another `block` is `400 bad_params`:
stop the session and start one there.

**Its sound** is Radio's ordinary receive audio, in place of the
demodulator's: `api/audio/rx` at 48 kHz, the station's own two channels
with `?channels=2` and L+R averaged without; `audio.stereo` in status is
true while the station is stereo. An audio recording made meanwhile is
the station: 48 kHz, two channels when it began in stereo, `freqHz` the
block's centre. While the station makes no sound (no sync yet, a DAB+
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
                   "distanceKm": 3.8, "bearingDeg": 113, "match": "eid"},
                  {"main": 1, "sub": 7, "levelDb": -8.5, "confidence": 1.0, "site": "Wrotham",
                   "area": "North West Kent", "ensemble": "SDL National", "erpKw": 25.0, "lat": 51.3207,
                   "lon": 0.2877, "distanceKm": 31.4, "bearingDeg": 114, "match": "eid"}]}
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
3 s at most, and only when something in it changes. Each entry:

| Field | Meaning |
|---|---|
| `main`, `sub` | The TII code as numbers (Ofcom's list writes them in hex: "0B"/"01" is 11/1). |
| `levelDb` | That transmitter's share of the signal received, dB, to 0.5: 0 for a lone one, about -3 each for two equal ones. |
| `confidence` | 0-1, to 0.1: how clearly its code stands above the noise (two transmitters with one sub identifier are a best fit, at most 0.7). |
| `site`, `area`, `ensemble` | The site's name, its area and the multiplex, from the list; all null for a code the list does not have (an Irish one, a new site). |
| `erpKw` | Its licensed effective radiated power, kW (null if the list has none). |
| `lat`, `lon` | The site, degrees. |
| `distanceKm`, `bearingDeg` | From the station's locator (great circle, to 0.1 km; bearing from true north, whole degrees); null without a locator or a site. |
| `match` | How it was found: `eid` (the ensemble's id and the code: certain), `block` (the code on this block, nearest the station, because the list has no row for this ensemble id), or null. |

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
C3A7), heard when the simulator runs at 2.4 MS/s (`sampleRate`).

## Broadcast gain (Radio)

A broadcast station is the strongest thing on the antenna by tens of dB,
so it does not play at the operator's manual `rxGain`, which is set for
weak amateur signals (an RSPdx on a local DAB multiplex at rxGain 40
reported thousands of overloads and dropped audio at 48 dB SNR). While a
DAB session holds the receiver, or the mode is `wfm`, Radio applies a gain
of its own (ohsradio/bcastgain.py has the reasoning):

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
| `dabNotch` | `auto`, `on`, `off` | out, until the RSP reports overload in three one-second windows running while its span is clear of 174-240 MHz; then in, and out again after 5 minutes with no overload (10, 20... up to 60 if it comes back within the hour). Always out in Band III and while a DAB session holds the receiver |
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
  seen), `overload`, `clear` (taken out after the hold), `band_iii`,
  `dab`; for `rfNotch` auto `below_60mhz` or `band`. `{}` for a radio
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
(5A-13F) of 1.2 s each, 2.4 s for a block holding an ensemble (about 55 s
plus 1.2 s per ensemble). At 1.2 MS/s FM takes 26 hops and DAB is refused
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
{"ensembles": [{"block": "11D", "freqHz": 222064000, "id": "C1CE", "label": "Shack Test Mux",
                "services": [{"sid": "C221", "label": "Shack MP2 Tone", "kind": "dab", "bitrate": 128},
                             {"sid": "C3A7", "label": "Shack DAB+ Data", "kind": "dab+", "bitrate": 64}]}]}
```

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

## Host libraries (store form)

What the image may not carry comes from the controller's host:
`store/radio/module.yaml` declares `host_libraries: [faad2, sdrplay-api]`,
and a controller that knows the key (platform beta.9 or later) mounts each
at `/opt/hostlibs/<name>` read-only and sets `SHACK_HOSTLIBS`. Its
administrator installs them (Controller › Optional libraries); Radio can
only say so. `hostLibs` in `api/status` and `api/state`:

```json
{"supported": true, "root": "/opt/hostlibs", "libraries": {"faad2": true, "sdrplay-api": false}, "why": ""}
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
