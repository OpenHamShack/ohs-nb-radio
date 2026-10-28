# Radio's ui/1 screens against the Android TV screens

Step 1b of openhamshack `docs/CLIENT-UI-PLAN.md` (§10): Radio serves its TV
screens as ui/1 documents (`ohsradio/screens.py`; the wire contract is
`docs/SERVER-API.md` "ui/1 screens"). This is what each screen of today's
Android TV client has, what the document serves instead, and every gap
with its reason, so the client session knows what its renderer and native
components must carry before the hand-written screens are deleted
(§5.8).

The Android screens were read in `~/openhamshack-remote` at main
`0a3e38a`, and Ships at `feature/ships` `649fe1a` (not on main yet), on
28/10/2026. `DabRadioLook.kt`, `DabRadioSession.kt` and `shack/DabRadio.kt`
do not exist in that repo: Radio's DAB on a TV is `ui/DabRadioUi.kt` over
`shack/EngineSession.kt` and `shack/Dab.kt`.

Everything below is receive only. Every action is an existing route at
the level it already had (tests press each one at its declared level and
one level lower: `tests/test_ham_screens.py`), and no screen places `ptt`
or `enableTx`.

## radio/home

**Android TV:** `ui/TvEngine.kt` (`TvEngine`, the one TV screen for NB and
Radio), `ui/TvRadio.kt` (`TvRadioReadout`, `TvRadioRow`, `TvBandsPanel`).
There is no landing page: Radio opens on its dial and waterfall. DAB
Radio and Ships are separate Fire TV launcher tiles today.

| Android TV | ui/1 `radio/home` |
|---|---|
| Frequency, mode pill, `dialLabel` ("GB7IR · Irvine · DMR") | `value` on `state.vfo` (`freq`), `chip` on `state.mode`, `nowPlaying` titled `state.dialLabel.text` |
| WFM with RDS: station name, RadioText | `nowPlaying` `detail`/`subtitle` on `state.rds.ps`/`rt` (the full RDS view is `radio/fm`) |
| S-meter card | `meter` on `meter.rx` (`db`); the S-unit scale is the client's, as today |
| Who holds the receiver (DAB, the scan) | `text` on `state.rxOwner.text` |
| Connecting / reconnecting, simulator, on-air flags | `text` on `state.error`; the rest is the renderer's (connection) or the launcher tile's (`onAir`) |
| Waterfall | native `waterfall`, stream `main`, layers band, dial, channels, beacons, stations, sessions |
| Tune (dial entry) | `frequencyField` → `POST api/set {"changes": {"vfo"}}` |
| Mode picker | `choice` of `MODES` → `POST api/set {"changes": {"mode"}}` |
| Bands panel; band step | Band down / Band up → `POST api/shack/pad/action {"action": "band", "kind": "turn", "step"}` (what `TvRadioRow` sends without plan data) |
| Mute (client side only) | `audio.mute` native verb (the same: nothing changes on the box) |
| Volume (none: the TV's own) | `slider` → `POST api/set {"volume"}` (asked for by the plan's example) |
| Stations (FM only), DAB | buttons opening `radio/fm`, `radio/dab`, `radio/ships` |
| — | Start the radio → `POST api/start` |

**Gaps.**
- *Step size* (OK holds, Left/Right adjusts, `e.step(by)`): a client-only
  dial behaviour with no route behind it. It belongs in the renderer's
  `frequencyField` on a TV, not in a document.
- *Bands panel* (the band list with edges): replaced by Band down/up;
  a list of bands needs the band plan's data as a feed, which Radio does
  not serve on its own yet. The waterfall's band layer shows the edges.
- *DMR item and Antenna item:* not in this step (DMR has its own TV
  panel; the antenna is a Settings key). Next with a `radio/dmr` screen
  and a `settingsForm`.
- *Stop DAB / stop the receiver's owner* from home: DAB's Stop is on
  `radio/dab`. Stopping AIS for everyone (`DELETE api/ais/session?all=1`)
  is a DELETE, which ui/1 cannot send (below).
- *Back closes DAB:* ui/1's Back is the client's and calls nothing on the
  box. Freeing a station when the TV leaves is §7's presence (step 0b);
  until then the DAB screen's Stop does it.

## radio/dab

**Android TV:** `ui/DabRadioUi.kt` (`TvDabScreen`, `DabReadout`,
`DabStations`, `DabBlocksSheet`), logic in `shack/EngineSession.kt` and
`shack/Dab.kt`, HTTP in `shack/ShackClient.kt`.

| Android TV | ui/1 `radio/dab` |
|---|---|
| Now playing: logo or badge, name, DLS, ensemble and status, kind and bit-rate chips | `nowPlaying` on `ui/v1/data/dab` (polled every second, as the TV polls its session): `title`, `dls`, `imagePath` (the slide, else the logo), `detail` ("DAB · 128 kb/s · Pop music"); `text`s for `ensemble` and `whyText` |
| Transmitters heard (Radio's TII names) | a `section` with one `text` on `transmittersText`, a line per transmitter |
| Station tiles, two wide, playing one lit, unplayable dimmed with `why` | a `grid` (`columns: 2`) of `card`s per ensemble (`section` titled "label · block"): logo, name, "kind · kb/s · genre"; pressing one → `POST api/decoders/sessions {..., "replace": true}` |
| Choose a service live (`decoderParams`) | the same tile: `replace` on the same block changes the service in the same session |
| Open another block (`DELETE` then `POST`) | the same tile: `replace` on another block stops the old session and starts the new one |
| Stop (`DELETE api/decoders/sessions/{id}`) | Stop → `POST api/decoders/sessions {"decoder": "dab", "stop": true}` |
| Scan now (`POST api/scan`) and its progress | Scan now → `POST api/scan {"band": "dab"}`; `text` on `state.bandScan.text`; an empty list offers the same scan |
| Server list `api/dab/stations`, re-read on `stations` | built from `api/dab/stations` when the screen is asked for (below) |
| Mute | `audio.mute`; plus Volume |

**Gaps.**
- *The playing tile lit, unplayable ones dimmed:* the tiles are built
  once; which one plays is in `ui/v1/data/dab` (`service`) but ui/1 has no
  binding that changes a node's look. The now-playing card says which.
  An unplayable service (DAB+ without faad2) still shows its reason in
  `whyText` once chosen.
- *Block stepping (Left/Right) and Remote's own all-block scan:* not
  served. Radio has its own scanned list (`api/dab/stations`), which the
  TV already prefers; the per-block walk was the fallback for a Radio
  without one.
- *Lists refresh:* the station list is the last scan's when the screen
  opens; after Scan now the client asks for the screen again (on the
  `stations` event or `stationsAt`). The plan does not say when a
  renderer refetches a screen.

## radio/fm

**Android TV:** `ui/RadioStations.kt` (`TvFmScreen`, `NowPlayingFm`,
`RdsLines`, `TrafficMarker`) and the RDS branch of `TvRadioReadout` in
`ui/TvRadio.kt`.

| Android TV | ui/1 `radio/fm` |
|---|---|
| Now playing: RDS name, RadioText, genre, stereo, traffic | `nowPlaying` on `state.rds.ps`, `rt`, `ptyName`; `badge`s Stereo (`meter.stereo`) and Traffic (`state.rds.tp`) |
| The dial | `value` on `state.vfo` (`freq`) |
| Station grid (name, MHz, genre, Stereo), A-Z / MHz sort | `tabs`: By frequency and A-Z, each a two-wide `grid` of `card`s (name or MHz, the frequency, genre, Stereo badge) |
| Tune a listed station | the tile → `POST api/set {"changes": {"vfo": best.hz, "mode": "wfm"}}` |
| Tune by frequency | `frequencyField` → the same with `$value` |
| Scan now | `POST api/scan {"band": "fm"}`; `state.bandScan.text`; an empty list offers it |
| Mute | `audio.mute`; plus Volume |

**Gaps.**
- *Genre chips (filter by genre):* ui/1 has no client-side filter over a
  list; the genre is on each tile. Two tabs carry the two sorts instead
  of a toggle.
- *"Leaves DAB if open" before tuning:* the box refuses a tune while DAB
  holds the receiver (`409 receiver_busy`, its sentence), which the
  client shows; Stop on `radio/dab` frees it. The TV did both in one
  press.
- *Step to 100 kHz on tuning a station:* the client's dial step, as on
  home.
- *A tile tunes in `wfm` only:* the TV picks `fm` for a station outside
  broadcast FM; every station in the scan's list is broadcast FM.

## radio/ships

**Android TV:** on `feature/ships` only: `ui/ShipsUi.kt` (`ShipsScreen`),
`ui/ShipsMapView.kt`, `shack/Ships.kt`, `shack/Ais.kt` (`Vessel`,
`AisTable`, `Plausible`), `shack/ShipsMap.kt` (`MapView`, `ShipsNav`,
`LandCell`, `MapInfo`), `shack/AisLease.kt`, `ShipsActivity.kt`.

| Android TV | ui/1 `radio/ships` |
|---|---|
| The map: land polygons, OSM tiles, ships coloured by type, track tails, attribution | native `map` with `layers: ["ais"]`; its props name `api/map/info`, `api/map/land`, `api/map/tiles/{z}/{x}/{y}.png`, `api/ais/vessels`, `api/ais/vessels/{mmsi}`, `api/events?kinds=ais` |
| The AIS lease: `POST api/ais/session` every 10 s, `DELETE ?client=` on close or background | the map component's (`ais.session`, `renewS: 10`), as `AisLease` is today |
| Refusals with their remedies (span pinned, DAB, on air, not running, view only) | the component's, from the codes the route answers |
| Nearest list (`NearestPanel`): plausible, not stale, nearest first | a `sheet` titled Nearest ships: a `list` of `card`s bound by index into `api/ais/vessels` (polled every 10 s; the server sorts nearest first): name, type, distance |
| Selecting a ship fetches its track | each card: `local` `map.ais.selected` with that row's `mmsi` binding; the map fetches the track |
| AIS state, who holds the receiver | `text`s on `ais.session.text` and `state.rxOwner.text` |
| D-pad modes (LIST, MAP, DETAILS, FOLLOW, MENU), CH+/CH- zoom, Play for "show all", filter/settings panel | the map component's: they are frame-rate interaction on one focusable surface |

**Gaps.**
- *The list's length:* rows are bound by index, so the sheet has as many
  as the table held when the screen opened (at most 12); a ship heard
  later shows on the map and in the list the next time the screen is
  asked for.
- *The plausibility filter and "forget after" setting:* the server's
  table already drops implausible frames and ships older than
  `aisKeepMinutes`; the TV's own 300 km and stale filters are the map
  component's.
- *A client without `map.ais`:* gets the fallback, a sentence and the
  list, and holds no AIS session, so the list shows only what the table
  kept from someone else's map.

## Judgement calls (where §5-6 was silent)

- **`entries[]`:** Radio, DAB Radio, FM, Ships, in the order §6.2 names
  them; Ships is an entry of Radio's descriptor, not an app of its own
  (§6.7 retired its tile). No Aircraft until an ADS-B screen exists.
- **DELETE and the DAB session id:** ui/1's actions are POSTs to fixed
  paths. Rather than a new route, `POST api/decoders/sessions` (control,
  as before) takes `"stop": true` and `"replace": true` (SERVER-API
  "DAB"). AIS's start, renewal and DELETE stay in the native map
  component. Stopping AIS for everyone is not offered. A `do: "delete"`
  or a templated path would be a ui/1 change for ohs-libs.
- **Lists:** ui/1 has no item template. Lists that change while open
  (ships) are rows bound by index (`ais.vessels.3.name`); lists that
  change weekly (stations) are built from the data when the screen opens.
  Transmitters heard are one text of lines (`transmittersText`), so their
  numbers are worded on the server, not by the client's formatter.
- **`ui/v1/data/dab`:** a view-level feed of Radio's own under `ui/v1/`,
  because the playing station is behind a session id no binding can
  name.
- **The map's props:** the paths the component needs, relative, with
  `{z}/{x}/{y}` and `{mmsi}` as in SERVER-API, and `renewS` for the
  lease. Components are negotiated as `map.ais/1` (§5.3's spelling); a
  client must list the layer, not just `map`.
- **Selecting a ship:** `local` with a binding as its value. §5.2 allows
  bindings in a post's body; this reads it as allowed in a local value
  too.
- **Feeds:** `state` and `meter` are two feeds on the same socket, so a
  binding says which; a `state` feed is the merged diffs.
- **Volume and Start:** the TV has neither (the TV's own volume; the
  radio starts with the app). Volume is the plan's own example; Start
  covers a stopped radio, which otherwise only the controller could
  start.
- **Icon:** `icon` is null: the brand kit's Radio PNG is a draft awaiting
  Brian (openhamshack `brand/README.md`), and the store image carries no
  PNG. Each entry names a generic icon the client has.
- **`minClient`:** "1.0", the ui/1 renderer version; component versions
  are negotiated per request instead.
- **`X-OpenHamShack-UI`:** absent or 1.x is served; another major is
  `406 ui_unsupported` with the versions this app serves.
- **Caching:** `rev` is a hash of the document, also its `ETag`;
  `no-cache` so a screen is always revalidated and never opens stale
  (§5.7).
