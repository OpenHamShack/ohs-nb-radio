# Radio's ui/2 screens against the Android TV screens

Step 5 of openhamshack `docs/contract/SCREENS.md` (§16): Radio serves every
TV screen as a ui/2 document (`ohsradio/screens/`; the wire contract is
`docs/SERVER-API.md` "ui/2 screens"). This is what each screen of today's
Android TV client has, what the document serves instead, and every gap
with its reason, for the parity step (§16 step 7) before the hand-written
screens are deleted. It replaces this file's ui/1 version, which compared
four ui/1 screens (gone, with ui/1, on 30/10/2026).

The TV's screens are named as SCREENS.md §15 and the ui/1 comparison read
them (`~/openhamshack-remote`, 28-30/10/2026). Everything below is
receive only: no screen places `ptt` or `txArm`, every call is an
existing route at its existing level (tests press each one at its level
and one level lower: `tests/test_ham_screens.py`), and nothing a document
can say keys a radio.

## Every screen

| Behaviour | Today's TV | ui/2 |
|---|---|---|
| Which tiles | the client's entry table and probes (`launcher/Entries.kt`) | `ui/v2/app`: Radio, DAB Radio, FM, Ships, Aircraft, Weather Sats, APRS, Sondes, DMR; the maps TV and tablet only; an entry this build lacks (no AIS, no ADS-B) is left out |
| Tile status | none, or the client's own polls | `ui/v2/status`: the dial or Stopped, the DAB station, each map's session text, Weather Sats recording, DMR channels decoding |
| Holding the receiver | `MapLease` (AIS), its ADS-B twin, the DMR panel's session | screen `holds`, renewed through presence; see each screen |
| Refusal cards with remedies | hand-built per map | the box's error `actions` on the hold banner: Stop the decoders (retry with `dropSessions`), Stop DAB, stop the other map |
| Live data | per-screen polling and `api/events` parsing | one live socket per screen (LiveHub), coalesced frames at the client's rate; Weather Sats polled |
| Words and numbers | formatted on the TV | formatted and translated on the box; the client ticks only clocks, ages and countdowns |

## radio/home

**Android TV:** `ui/TvEngine.kt`, `ui/TvRadio.kt` (`TvRadioReadout`,
`TvRadioRow`, `TvBandsPanel`).

| Android TV | ui/2 `radio/home` |
|---|---|
| Frequency, mode, `dialLabel` | `frequency` part `dial`, its value a number of hertz with `unit` (Left/Right step, digits to entry) → `POST api/set {"changes": {"vfo"}}`; `choice` `mode`; text `dialLabel` |
| Band and segment, the band's range ("2 · FM simplex 144 – 148 MHz") | texts `bandLine` and `bandRange`, a mode badge |
| RDS name and text | text `rds` |
| S-meter (S1-9, +20/+40/+60) | `meter` `smeter`: dBm on S-units where the receiver is calibrated, else dBFS labelled uncalibrated. The parity check of 31/10 found it undrawn: the box sent a null value while the receiver read nothing, and a null main value hides a part; it now always sends a number |
| ◀ STEP ▶ | ◀ and ▶ around `stepText`: the box's step (`api/shack/pad/action` `step`, turned), which the dial's Left/Right, ◀◀ ▶▶ and the phone's tuning use |
| Bands panel | panel `bands` (Menu, or the Bands button): a list of the bands with their ranges; a row sets the band's spot from the box's band stacks, dial and mode in one `api/set` |
| Phone ◀ ▶ tuning | ◀ and ▶ beside the dial on phones and tablets → `api/shack/pad/action` `tune` |
| Who holds the receiver | banner `rxOwner` with its remedy (Stop DAB, stop the map) |
| Waterfall, tap to tune | `spectrum` on `api/spectrum/v1` with the band, dial, passband, channels, beacons, stations and sessions layers; `tap` tunes |
| Band step (CH+/CH-) | keys `chUp`/`chDown` and Band down/up → `POST api/shack/pad/action` |
| Mute | the audio part's own mute (nothing changes on the box) |
| — | Volume (`POST api/set {"volume"}`), Start the radio while it is stopped |

**Gaps.** The bands panel lists Radio's own bands (`ohsradio/bands.py`),
not the TV's plan-driven buttons with listening areas (DAB, airband):
those need the band plan as data (SCREENS.md D9). Recent bands and the
DMR and antenna items are not served. The antenna is a Settings key.

## radio/fm

**Android TV:** `ui/RadioStations.kt` (`TvFmScreen`, `NowPlayingFm`,
`RdsLines`), the RDS branch of `TvRadioReadout`.

| Android TV | ui/2 `radio/fm` |
|---|---|
| RDS name, RadioText, genre, Stereo, Traffic | texts `ps`, `rt`, `pty`; badges `stereo` (the receiver's pilot) and `tp` |
| Station grid, A-Z / MHz sort | `tabs` By frequency and A-Z, each a `list` from its collection (`byFreq`, `byName`), filled over the socket from the scan |
| Tune a station | a row's OK → `POST api/set {"changes": {"vfo": <hz>, "mode": "wfm"}}` |
| Tune by frequency | `frequency` part, 87.5-108 MHz in 100 kHz steps |
| Scan now and its progress | Scan now; `scanText`; an empty list offers the scan |
| Mute | audio mute, timeshift controls; Volume |

**Gaps.** Genre chips (filter by genre) are not served: the genre is on
each row. "Leaves DAB if open" before tuning: the box refuses the tune
while DAB holds the receiver, and the banner offers Stop DAB.

## radio/dab

**Android TV:** `ui/DabRadioUi.kt` (`TvDabScreen`, `DabReadout`,
`DabStations`), `shack/EngineSession.kt`, `shack/Dab.kt`.

| Android TV | ui/2 `radio/dab` |
|---|---|
| Station tiles with logos, the playing one lit | `grid` of cards from `stations` (logo, name, "DAB+ · 64 kb/s · genre"); `selected` from the item's `playing` |
| Choose a station, live on the same block, another block | the tile → `POST api/decoders/sessions {"decoder": "dab", ..., "replace": true, "client": $client}` |
| Now playing: slide or logo, name, DLS, ensemble, why | image `slide`, texts `service`, `dls`, `detail`, `ensemble`, banner `why`; the Android renderer does not draw the name and bit rate yet (parity check, 31/10), though the document sends them |
| Transmitters heard | a section listing `transmitters`, one line each |
| Stop | Stop (and Play on the remote) → `{"decoder": "dab", "stop": true}` |
| Level bars, timeshift | `meter` reading the audio part (not drawn by the Android renderer yet: parity check, 31/10); audio with `timeshift` controls |
| Scan now | Scan now; an empty grid offers it |

**Holds.** None while open, as on the TV: the station plays under the
client's id and ends when its last client goes (presence), or on Stop.

**Gaps.** Favourites, last played, sleep timer and generated station art
are box state still to come (SCREENS.md D8, D9). Unplayable services
(DAB+ without faad2) show their reason once chosen, not dimmed in the
grid.

## radio/ships, radio/aircraft, radio/aprs, radio/sonde

**Android TV:** on Remote main, `ui/TrafficScreen.kt`, `ui/AircraftUi.kt`,
`ui/ShipsUi.kt`, `ui/ShipsMapView.kt` and `shack/Traffic*.kt`. APRS and
Sondes have no screen on main: `ui/AprsUi.kt` and `ui/SondeUi.kt` are on
Remote's `feature/screens-remote` (and `feature/tv-launcher`,
`feature/appletv`), which is what the parity screenshots of them show.

| Android TV | ui/2 (all four) |
|---|---|
| The map: land, OSM tiles, attribution | `map` with Radio's `api/map/land` and `api/map/tiles`; station mark always labelled |
| Markers per kind, hand-drawn | shack_ui's symbol sets (aircraft, ships, APRS by table and code, sondes) and data colours by band, ship type, APRS kind or flight phase |
| Trails | `trail`, a point pushed as an item moves, 30 kept (sondes: their track, 60) |
| LIST / MAP / DETAILS / FOLLOW / MENU modes | the nearest panel, the map, the details panel (Left/Right steps), Aircraft's follow HUD, the menu panel |
| Filters, labels, rings, forget, map style per device | header chips and menu toggles over the collection's `hide` tags; `local` preferences |
| Nearest first (ships, aircraft), newest first (APRS, sondes) | the table's own order |
| Units: nm, kn and ft on Ships and Aircraft; metric on APRS and Sondes (hard-wired per screen: Radio has no units setting) | the same, worded on the box |
| Status, "APRS · RECEIVING" | a one-word chip (Receiving, Scanning, Starting, Stopped); the session's sentence in the panel |
| Sondes: the selected sonde's readout along the bottom | panel `readout`, `for: sondes`: altitude, climb, temperature, humidity, pressure, battery, speed |
| The lease and its refusal cards | hold `ais`, `adsb`, `aprs`, `sonde`: `POST api/<x>/session {"client": $client}` (30 s), `DELETE ...?client=`; refusals carry their remedies |
| Aircraft photo (Planespotters), its credit and a QR of its link | `image` with `src` as Planespotters gave it, `credit`, `link`, `qr: true`; sent only to the client that selected the aircraft |
| Emergencies (squawk 7700, SART) | pinned, an emergency pill in the header and in the row |

**Gaps** (after the switch, Brian 31/10, unless noted). An "All" chip.
Aircraft: airports, flight progress and ETA, the cockpit values and
range rings are not served yet (no data in Radio's table for
the first three; rings need a `local` default worded per unit). Sondes:
the profile chart and upcoming launches. APRS: messages and the selected
station's recent packets. Ships: ETA worked out from the voyage.

## radio/wxsat and radio/wxsat/viewer

**Android TV:** `ui/WxSatUi.kt`, `shack/WxSat.kt`, `WxSatSession.kt`.

| Android TV | ui/2 |
|---|---|
| Passes list, plan, countdown, OK records or skips | `list` from `passes`, upcoming first (soonest first) then the day's past ones (newest first), each with its own `action` (Record this pass / Record anyway? / Skip this pass) and a ticking countdown |
| Sky plot of the chosen pass, AOS/LOS/max | `skyplot` from `passes`, `show: selected` |
| Live: the satellite now, signal, elevation | `skyplot` placed by the box's `now`, `meter` `snr`, `elNow`; Live's tab badge while recording |
| Gallery of decoded passes, thumbnails at 400 px, MCIR first | `grid` from `images`, `?w=400`; MCIR, then rgb and ir, in the gallery and the viewer |
| Picture viewer, products, turned for a northbound pass | `radio/wxsat/viewer?image=<id>`: product tabs, `?w=1920`, `rotate: 180` for a pass rising in the south |
| Map of the last day's passes | map `images` layer from `frames` (`api/wxsat/composite`, rgb else ir), with a scrubber |
| Polling, 2 s recording and 10 s idle | `poll` `ui/v2/poll/radio/wxsat`, each answer a snap, `everyS` 2 or 10 |

**Holds.** None: polled, never a socket, so opening it wakes and holds
nothing. A pass's record or skip is its only call.

**Gaps.** Auto-jump to Live when a pass starts (the box could `set` the
tabs' `selected`; left for the parity check).

## radio/dmr

**Android TV:** `ui/DmrPanel.kt`, `shack/Dmr.kt`, `shack/DmrSession.kt`.

| Android TV | ui/2 |
|---|---|
| Opened on a repeater from Local frequencies | `radio/dmr` lists the operator's repeaters and the dial; `radio/dmr?f=<Hz>` decodes one |
| Two slots: talker, talkgroup, call timer, encrypted | cards `slot1`/`slot2`, `talker`, `group`, a ticking `since` timer |
| Call log, newest at the top | `list` from `calls`, `follow: top` |
| Listen: Off, TS1, TS2, Both | `choice` `listen` → `POST ui/v2/hold/dmr-listen {"listen"}` (the slot param, then listening) |
| Level meter | `meter` reading the audio part (not drawn by the Android renderer yet: parity check, 31/10) |
| The session: started on open, stopped by id on close | hold `dmr` → `POST/DELETE ui/v2/hold/dmr`, kept by shack_ui's `Holds`: one session per channel shared by its clients, ended when the last lets go or its presence goes |

## Judgement calls

- **FM is a tile.** The contract's fixture lists eight entries without
  FM; ui/1 had an FM tile and the TV opens FM directly, so it stays.
- **No tile art yet.** Radio serves no PNGs (the brand kit's are a draft
  awaiting Brian); every entry names an icon from the client's set.
- **DMR's hold through shack_ui's `Holds`,** because a hold's stop is a fixed path and
  cannot name the session id the start was answered with. Its session is
  client-scoped and unsaved, where the TV's was saved as a background
  session and outlived a TV switched off at the wall.
- **Weather Sats keeps record and skip.** "Read-only" here means it holds
  nothing and opens no socket; the calls are the contract fixture's and
  the TV's.
- **The photo and who the aircraft is go only to the selecting client,**
  as SCREENS.md §3.3 intends, refreshed when they change, so one looked up
  after selection still arrives.
