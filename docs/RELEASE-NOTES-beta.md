# OpenHamShack beta: what changes for QO-100 NB and Radio

The beta's notes for the two apps, kept as the work lands (M3) so the
release can quote them. Per-release user-facing notes stay in
`docs/release-notes/`.

## Band limits and transmit permission come from the shared dataset

Both apps now ask the shared OpenHamShack band-plan and licence dataset
(ohs-libs `shack_bandplan`, dataset **2026.10.3**, pinned in
`tools/vendor/requirements.lock`) whether a transmission is allowed, with
the station profile built from the app's settings (callsign, station
country, licence, class, own licence, station conditions):
`ohscore/txguard.py`. Radio's licence and band-plan guard
(`ohsradio/guard.py licence_check`, `plan_check`) and QO-100 NB's plan and
uplink checks (`ohsnb/bandplan.py tx_blocked`, `ohscore/licences
satellite_uplink`) no longer decide anything; the old tables stay for the
Settings pages and the scope's shading, and as the reference ohs-libs
proves the dataset against.

The dataset was converted from these very modules, and ohs-libs'
`test_conformance.py` runs every regime's row edges, every class and the
QO-100 plan through both and requires the same allow/refuse and power
limit. These answers change on purpose:

| Where | Before | Now | Why |
|---|---|---|---|
| RSGB plan, 13 cm 2320.75-2320.80 MHz (local beacons) | Radio allowed | refused (beacon segment) | transcribed from the RSGB plan's PDF (R1 p.25); the old module lacked the row |
| RSGB plan, 13 cm 2320.99-2321.00 MHz (beacons, IARU column) | allowed | refused | R1 p.25 |
| RSGB plan, 13 cm 2400-2450 MHz (satellites, ATV repeater outputs) | allowed to terrestrial signals | refused to terrestrial signals | R1 p.25 |
| RSGB plan, 9 cm 3400.75-3400.80 MHz (local beacons) | allowed | refused | R1 p.26 |
| RSGB plan, 6 cm 5650-5668 MHz (satellite uplinks) | allowed | refused to terrestrial signals | R1 p.27 |
| RSGB plan, 6 cm 5760.75-5760.995 MHz (beacons) | allowed | refused | R1 p.27 |
| RSGB plan, 6 cm 5830-5850 MHz (satellite downlinks) | allowed | refused | R1 p.27 |
| RSGB plan, 3 cm 10368.75-10368.995 MHz (beacons) | allowed | refused | R1 p.28 |
| IARU R1 plan, 3 cm 10368.80-10368.99 MHz (beacons) | allowed | refused | I2 p.51 |
| Radio, any terrestrial signal touching QO-100's uplinks (2400.0-2410.0 MHz) | judged by the licence and plan alone | refused: only a satellite uplink may go there | the dataset's satellite plans apply to every signal touching them |
| RSGB 2321-2322 MHz bandwidth | 25 kHz | 20 kHz (a warning, or a refusal under "enforce") | corrected from the PDF |
| RSGB and IARU R1 plans: 2200 m, 630 m, 3 cm rows | not in the plan (only the licence was judged) | the plan's rows apply | transcribed into the dataset |
| RSGB 630 m, 472-475 kHz | nothing | a warning (CW only at 200 Hz, RSGB Note 1) | a recommendation, never a refusal |

New warnings that never refuse:

- **Band plan gaps and unplanned spans:** where the plan's source prints
  nothing, Radio's transmit card says only the licence was checked there.
- **Researched data:** a regime other than the UK's (checked line by line
  against Ofcom's PDF) carries a note that its data has had one research
  pass, not a line-by-line check. It is shown, never a refusal.

Wording: every refusal sentence is now the dataset's. They name
OpenHamShack, and point to "the station profile" rather than one app's
Settings path, because every app shows the same profile; otherwise they
are the old sentences.

Unchanged on purpose:

- **"Unconfirmed" still refuses** (a row the research could not confirm
  from the instrument is never guessed open); ohs-libs carries vectors for
  it from 2026.10.3.
- **QO-100 NB still warns, never locks, when no licence class is set**
  (Brian, 08/10/2026): the dataset's no-class and no-licence refusals are
  read as "cannot be checked" for the uplink, and the transmit card's
  standing warning stays.
- **One signal's width judges the plans' width limits** (a digital mode
  from another program, somewhere in its dial window), and the window
  judges where it may reach. The library learnt this in ohs-libs 0dd0358
  (`Signal.signal_bw_hz`); without it, FT8 through a loopback device would
  have been refused in every 500 Hz segment.

Transmit paths were tested only into the simulator: nothing in this work
keyed a radio.

## 0.1.11-beta.1 (store) and 0.1.11 (desktop), 10 October 2026

The store packages since 0.1.10-beta.4 change one thing: **the server no
longer leaks file handles.** The shared station store kept a database
connection for every request thread that had ever run, two file handles a
request, real radios and the simulator alike: the store form ran out of
file handles in about 40 minutes.
Each request thread's connection is now given back when it ends (ohs-libs
326d251, `Store.release_thread()`).

The desktop installers move to 0.1.11 because the ones published as 0.1.10
were made before this beta's work. 0.1.11 carries everything above, plus
what the store packages gained along the way: JS8 (receive) and Q65 decoded
by ohsdigi 0.2.0 in every form, the CW decoder that reads the QO-100 beacons,
and the microphone opened only while something needs it.

Transmit paths were tested only into the simulator: nothing keyed a radio.

## 0.1.12-beta.1 (store) and 0.1.12 (desktop), 10 October 2026

The store packages since 0.1.11-beta.1:

- **A platform update no longer stops the radio for good.** The broker
  keeps claims in memory, so a controller restart lost NB's claim and the
  store form treated that as the controller taking the radio back: no
  spectrum and no receive audio until the app was restarted. A lost claim
  is now re-claimed with backoff; only a real release request stops the
  radio (9747285).
- **Gone listeners are dropped.** Receive audio sends silence while the
  radio is idle, so a client that has gone is noticed and its listener and
  thread freed, where before one reconnecting TV left twenty behind
  (a750f32).
- **The CW decoder reads the QO-100 beacons the right way round.** An F1A
  beacon tuned on its key-up tone is heard inside out and is now detected
  and inverted; AFC no longer walks off the pitch towards a carrier outside
  its window, and the tracker ignores carriers outside +-100 Hz
  (ed2687d, 47be138; bench cases 2a0e365). These reach the desktop forms
  too, which is why they move to 0.1.12.

Transmit paths were tested only into the simulator: nothing keyed a radio.

## 0.1.13-beta.1 (store) and 0.1.13 (desktop), 10 October 2026

Since 0.1.12:

- **One CW decoder across the family.** NB and Radio now decode CW with
  the shared OpenHamShack decoder that OpenHamShack Icom also uses, so a
  fix to one reaches all of them. It is the same decoder as 0.1.12 moved
  into a shared library: what it prints on the beacons and on the bench is
  letter for letter unchanged (950fced, d1a0ea5).
- **CW sends and reads @ ( ) ' and ".** The Morse table lacked them, so a
  message containing one lost that character when sent; it now goes out
  and decodes.

Transmit paths were tested only into the simulator: nothing keyed a radio.

## 0.1.14-beta.1 (store) and 0.1.14 (desktop), 12 October 2026

Since 0.1.13:

- **Recordings on the controller.** The store form records receive audio
  (FLAC) and the radio's IQ (SigMF) into the app's data volume through the
  shared OpenHamShack recorder, behind `api/recordings` (1089281, 531f449,
  94e9f36). Old recordings are pruned past a size limit (10 GB by default),
  nothing records with under 2 GB free, and audio stops after 4 hours and IQ
  after 10 minutes; each is a setting.
- **Enable TX for the digital modes.** The store form can key each over of
  an armed digital-mode QSO itself, through the same path and lease as PTT,
  and a TV the station's administrator allowed digital transmit may arm it,
  never voice (f3bbac2, 2b73306; needs platform 2.0.0-beta.6 for the TV).
- The FT8 sequencer moved from the desktop window into the shared core
  (86e72d3), which is why the desktop forms move to 0.1.14 as well.

Transmit paths were tested only into the simulator: nothing keyed a radio.

## 0.1.16 (desktop), 12 October 2026

The first desktop release published on openhamshack.com, and the first
that looks there for updates:

- **Updates come from openhamshack.com.** The apps check
  https://openhamshack.com/desktop/nb/update.json (QO-100 NB) and
  /desktop/ham/update.json (Radio). The old openhamshacknb and openhamshackham
  download sites are gone for good. A copy older than 0.1.16 is never
  offered another update, so reinstall once from
  https://openhamshack.com/downloads/; after that, updates arrive by
  themselves as before.
- **The source is at https://openhamshack.com/source/**, which is where the
  About box and THIRD-PARTY.txt now point.
- **IC-9700 setup assistant** (QO-100 NB, Settings › Transmitter ›
  *IC-9700 setup...*). *Find* fills in the radio's CI-V address and sound
  device. *Check and set* shows each radio setting CAT PTT needs, changes
  only what you tick and can put the radio back as it was. *Set audio
  level* runs only once you have ticked that the radio is on a dummy load
  (c9f75d2..edc37ad).

0.1.15 was built but never published; everything in it is in 0.1.16, and
its notes follow.

## 0.1.15-beta.1 (store) and 0.1.15 (desktop), 12 October 2026

Since 0.1.14:

- **QO-100 NB can key an IC-9700 for its own digital overs (CAT PTT).**
  Off by default: Settings › Transmitter, *Key the IC-9700 for digital modes
  (CAT PTT)*. With it on, NB keys the 9700 by CI-V for Enable TX in FT8 and
  FT4 and for the lines you send in PSK, RTTY and CW, as WSJT-X does, and
  sends the audio to the radio's own USB sound device. It never keys the
  radio for voice: speech stays on the radio's own PTT (892d81a, 3bad3dc,
  d1f6f71, 35f01fe).
- **The right data mode by itself.** Choosing a digital mode puts the radio
  in USB-D (LSB-D through an inverting upconverter), and going back to USB
  or LSB puts it back in plain SSB.
- **DATA MOD is checked.** NB reads the radio's DATA MOD setting and will
  not key it unless it takes its audio from USB, so a radio set to MIC or
  LAN is never keyed with no audio going in.
- **Answering a CQ with a modifier answers the station.** "CQ DX OH8ZZ
  KP20" was answered as DX and "CQ POTA EA8XYZ IL18" as POTA, by a
  double-click on the desktop and by Enable TX; the call after the modifier
  is now the one answered (a584d59).

For desktop users coming from 0.1.10, the last version published on the
download sites, 0.1.15 also carries everything in 0.1.11 to 0.1.14 above.

### For IC-9700 users

On the radio:

- SET › Connectors › MOD Input › **DATA MOD = USB**.
- Set **USB MOD Level** (same menu) so the ALC barely moves.
- **23 cm on MAIN**, and satellite mode off.
- CI-V address **A2** (the radio's default).

In QO-100 NB, Settings › Transmitter:

- Turn on **Key the IC-9700 for digital modes (CAT PTT)**.
- **IC-9700 sound device:** choose the radio's *USB Audio CODEC*.
- **Delay before audio:** 100 ms, or more if your upconverter's relay is
  slow to switch.
- **Digital audio level:** start at -10 dB.

Try it into a dummy load first. NB never keys the radio for voice: speech
is always keyed on the radio itself.

Transmit paths were tested only into the simulator: nothing keyed a radio.
CAT PTT has not yet been tried on a real IC-9700.
